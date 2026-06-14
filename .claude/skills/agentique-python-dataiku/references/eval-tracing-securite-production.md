# Évaluation, tracing, observabilité, sécurité & production

> À jour : juin 2026 (LangChain 1.x, LangGraph 1.x, Dataiku DSS 14.x). Référence du skill `agentique-python-dataiku` — voir `SKILL.md` (parent). Réfs croisées : `references/langgraph-v1.md` (RetryPolicy/TimeoutPolicy/durabilité), `references/orchestration-multi-agents.md` (pare-feu d'honnêteté, fan-out), `references/prompting-et-determinisme.md` (code-owned vs LLM), `references/memoire-persistance-hitl.md` (checkpointers, HITL), `references/dataiku-code-agents.md` (LLM Mesh, `BaseLLM`, `get_agent_tool().run()`).

La thèse de ce fichier : **le tracing est le substrat, l'évaluation est la couche de jugement par-dessus, la sécurité et la gouvernance sont des contraintes architecturales — jamais des promesses de prompt.** On instrumente d'abord (toute la trajectoire : chaque appel LLM/outil/retrieval/sous-agent + tokens/coût/latence), on évalue ensuite, on met sous gouvernance enfin. Le corpus (LangChain/LangSmith, Anthropic, OWASP, Dataiku DSS 14) et la source ChatGPT convergent sur la taxonomie ; là où ils divergent, le corpus + le fichier de recency font foi sur APIs/versions.

---

## 0. Contexte Python (à rappeler partout où la version compte)

L'instance Dataiku a **DEUX** code envs : **Python 3.9 ET Python 3.11**. Chaque outil ci-dessous a deux chemins.

| Contexte | Tracing / éval / sécurité |
|---|---|
| **Code env 3.11** (≥ 3.10) | `import langsmith`, `agentevals`, `langgraph.types.RetryPolicy`, OTel SDK possibles. Un Code Agent affecté à un env 3.11 peut tracer via LangSmith/OTel **et** via le `trace` Dataiku. |
| **Contexte 3.9** (backend webapp OWIsMind, 3.9.23) | **stdlib + `dataiku` uniquement, AUCUN import langchain/langsmith/agentevals.** Tracing = `trace.subspan` Dataiku (côté Code Agent 3.11) relayé, ou logging SQL direct maison (`webapp_chat_v5` + tables usage). Retries/timeouts/idempotence = code stdlib à la main. Évaluation = `unittest` + golden queries + recette Evaluate Agent (côté DSS). |

**Ne jamais recommander d'importer `langchain`/`langsmith`/`agentevals` en contexte 3.9.** Le pare-feu d'honnêteté, le suivi d'usage, l'enforcement SQL read-only d'OWIsMind sont tous codés stdlib-only côté backend 3.9.

---

## 1. Modèle mental en un écran

1. **Tracing d'abord, évaluation ensuite.** On ne peut pas évaluer une trajectoire qu'on ne voit pas. (sources : https://www.langchain.com/articles/llm-monitoring-observability · https://www.groundcover.com/learn/observability/ai-agent-observability)
2. **Trois cibles d'évaluation, pas une** : (a) **réponse finale**, (b) **trajectoire** (le chemin d'étapes/tool calls), (c) **étape unique** (à ce point de décision, bon outil + bons args ?). (source : https://docs.langchain.com/langsmith/trajectory-evals)
3. **Offline avant le ship, online après.** Offline = datasets curés, reproductibles, avec références → régression/CI. Online = traces de prod, sans référence → monitoring/anomalies. Les échecs prod alimentent de nouveaux exemples offline (le *flywheel*). (source : https://docs.langchain.com/langsmith/evaluation-concepts)
4. **Hiérarchie des correcteurs : code > LLM-juge > humain.** Le plus rapide/fiable qui suffit. Le code (exact/structurel) est déterministe et gratuit ; le LLM-juge est flexible mais biaisé et doit être validé contre l'humain d'abord ; l'humain est l'or mais lent. (source : https://platform.claude.com/docs/en/test-and-evaluate/develop-tests)
5. **La sécurité est architecturale.** Le prompt injection **ne se résout pas au niveau du prompt** (§5). Les défenses durables : moindre privilège des outils, read-only forcé dans la base, sortie traitée comme non fiable, approbation humaine pour les effets de bord. (source : https://arxiv.org/pdf/2509.08646)
6. **Format de fil standard** : convergence vers OpenTelemetry GenAI semconv (`gen_ai.*`), OpenInference en namespace parallèle émettant désormais les deux. (sources : https://opentelemetry.io/docs/specs/semconv/gen-ai/ · https://futureagi.com/blog/what-is-openinference-2026/)

---

## 2. Tracing & observabilité

### 2.1 Vocabulaire (universel, formulation Dataiku)

- **Trace** = l'enregistrement complet d'un run d'agent : un arbre/timeline d'**observations**.
- Deux types d'observation : les **spans** ont début+fin et peuvent avoir des enfants ; les **events** sont des points horodatés. Chacun porte un nom, des inputs/outputs optionnels, des attributs. (source : https://doc.dataiku.com/dss/latest/agents/tracing.html)
- L'observabilité d'agent « suit tout le run, y compris planification, routing, appels d'outils/API, retrieval, sous-agents, et la réponse finale, sur une seule trace ». (source : https://www.groundcover.com/learn/observability/ai-agent-observability)

### 2.2 LangSmith (env 3.11 ; framework-agnostique)

LangSmith est la plateforme observabilité + évaluation de LangChain. **Pas besoin de construire l'agent en LangChain** pour le tracer (fonctionne avec LangGraph ou du code arbitraire). (source : https://www.langchain.com/langsmith/evaluation)

```python
from langsmith import traceable

@traceable
def toxicity_classifier(inputs: dict) -> dict:
    return {"class": result}
```
Activation par env : `LANGSMITH_TRACING="true"`, `LANGSMITH_API_KEY=...`. LangSmith capture « chaque appel modèle, usage d'outil, et décision » + tokens in/out par trace et latence par étape → on isole l'étape qui pèse en coût/latence. (sources : https://docs.langchain.com/langsmith/evaluate-llm-application · https://www.langchain.com/langsmith/observability)

**Nouveautés post-cutoff Jan-2026 à connaître :**
- **LangSmith Engine** (2026) : analyse les traces, *cluster* les échecs en liste priorisée, ébauche des correctifs, et **propose des exemples d'éval offline** pour ta suite. (source : https://www.langchain.com/blog/introducing-langsmith-engine)
- **Multi-turn Evals + Insights Agent** (2025→2026) : mesurent l'atteinte de l'objectif sur **toute la conversation** — *semantic intent*, *semantic outcome*, *agent trajectory*. (source : https://blog.langchain.com/insights-agent-multiturn-evals-langsmith/)

### 2.3 OpenTelemetry GenAI semconv vs OpenInference

| | **OTel GenAI semconv (`gen_ai.*`)** | **OpenInference** |
|---|---|---|
| Origine | OTel, cadré Déc-2024 ; conventions *agent* ajoutées été 2025 | Arize Phoenix, depuis 2023 |
| Statut | **expérimental** ; opt-in `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` | mature, riches auto-instrumentations |
| Quand | nouveau projet, standard long terme | écosystème Phoenix / besoin d'auto-instrum aujourd'hui |
| Convergence | — | par 2026 émet **aussi** les attributs OTel (back-compat) |

Attributs clés OTel à connaître : `gen_ai.operation.name` (valeurs prédéfinies **`chat`**, **`embeddings`**, **`execute_tool`**, **`invoke_agent`**), `gen_ai.provider.name`/`gen_ai.system`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`/`output_tokens`, `gen_ai.agent.name`, `gen_ai.tool.name`. (sources : https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/ · https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/ · https://www.datadoghq.com/blog/llm-otel-semantic-convention/)

> **Flag recency :** les pages GenAI semconv ont été **déplacées** vers un repo dédié (`open-telemetry/semantic-conventions-genai`) ; les anciennes pages affichent un avis de migration. Consulter le nouveau repo pour la spec vivante. (source : https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/)

Autres options framework-agnostiques : **OpenLLMetry** (Traceloop, Apache-2.0, auto-instrum OpenAI/Anthropic/Cohere/LangChain → OTLP), **Arize Phoenix**, **Langfuse**, **MLflow**, et le peloton 2026 (Braintrust, LangWatch, Helicone, Datadog LLM Observability, Confident AI/DeepEval, Galileo, Ragas). (sources : https://github.com/traceloop/openllmetry · https://github.com/arize-ai/phoenix · https://futureagi.com/blog/what-is-openinference-2026/)

### 2.4 Tracing Dataiku DSS 14 (terrain du lecteur)

**Traces LLM Mesh built-in** (retournées automatiquement à chaque appel) : exécution globale, guardrails de requête (`DKU_LLM_MESH_QUERY_ENFORCEMENT`), invocation LLM (`DKU_LLM_MESH_CALL`), guardrails de réponse (`DKU_LLM_MESH_RESPONSE_ENFORCEMENT`), usage (**tokens, coûts**), inputs/outputs, identification du LLM. Disponibles via l'attribut API `response.trace` et en sortie de Prompt Recipe (si activé).

**Code Agent — objet `trace` (un `SpanBuilder`) pour des spans programmatiques :**
```python
with trace.subspan("Doing something") as subspan:
    do_something()

# greffer la trace propre d'un LLM aval dans ton span :
with trace.subspan("Calling another LLM") as subspan:
    llm = dataiku.api_client().get_default_project().get_llm("some_llm")
    resp = llm.new_completion().with_message("do something").execute()
    subspan.append_trace(resp.trace)
```
Pour un agent LangChain (env 3.11), brancher le pont `LangchainToDKUTracer(dku_trace=trace)` en `config={"callbacks": [tracer]}` pour que les runs LangChain alimentent la trace DSS. (source : https://developer.dataiku.com/latest/concepts-and-examples/agents.html)

**Trace Explorer** (plugin, à installer) : vues Tree / Timeline / Explorer sur la colonne JSON de trace ; inputs/outputs/attributs par nœud. Pour Prompt Recipes, « Raw response output mode » = « Raw » pour peupler `llm_raw_responses`.

**Interaction logging** (feature « Agent Logging » GA en **14.5.0**) : l'agent écrit son activité directement dans un dataset Dataiku — **input utilisateur, réponse finale, liste de tool calls, métadonnées, traces, trajectoires** — depuis Prompt recipes, Agent Hub, Webapps ou l'API LLM Mesh. Ce dataset est « pleinement compatible avec Agent Evaluation » → boucle de monitoring directe. API : `DSSAgentInteractionLoggingSelection.enable(dataset_name, settings=None)`, modes `MODE_INHERIT|MODE_EXPLICIT|MODE_NONE`, `content_mode` `CONTENT_MODE_FULL|CONTENT_MODE_NO_LOGS`. (sources : https://doc.dataiku.com/dss/latest/agents/tracing.html · https://developer.dataiku.com/latest/api-reference/python/agents.html · https://doc.dataiku.com/dss/latest/release_notes/14.html)

> **OWIsMind (3.9) :** le backend fait du **logging SQL direct** (`webapp_chat_v5` + tables usage) — équivalent maison du « write activity to a dataset → evaluate ». L'objet `trace` Dataiku vit côté Code Agent 3.11 ; le Flask 3.9 relaie via le pattern polling-via-thread.

**Mapping concepts ↔ DSS :** Trace ↔ trace LLM Mesh / `trace.subspan`. Dataset/example/experiment ↔ dataset de logs → recette Evaluate Agent → Evaluation Store. Trajectory eval ↔ tool-sequence validation + Trajectory Explorer. LLM-juge ↔ RAGAS + custom traits. Réponse finale ↔ BERTScore + métriques Python.

---

## 3. Évaluation — les trois cibles

| Cible | Question | Correcteur typique |
|---|---|---|
| **Réponse finale** | A-t-il produit la bonne réponse au final ? | code (exact/embedding) ou LLM-juge |
| **Trajectoire** | A-t-il pris un chemin d'étapes/tool calls sensé/attendu ? | trajectory-match (déterministe) ou LLM-juge de trajectoire |
| **Étape unique** | À *ce* point de décision, bon outil + bons args ? | code-match sur nom d'outil + args |

(sources : https://docs.langchain.com/langsmith/trajectory-evals · https://www.langchain.com/resources/llm-evaluation-framework)

**Anti-pattern central : l'évaluation réponse-finale-seulement** passe la réponse mais cache une trajectoire cassée/coûteuse. Évaluer les trois.

### 3.1 Triade du vocabulaire d'éval

- **Dataset** = collection d'**examples**. **Example** = un cas : `inputs`, `reference outputs` optionnels (golden/vérité terrain), `metadata` optionnel.
- **Experiment** = résultats d'une *version* de l'app contre un dataset (outputs + scores + traces par example) → comparaison de versions sur le même dataset. **Splits** = sous-ensembles nommés ; **versions** = auto-créées quand les examples changent, taguables pour la CI. (source : https://docs.langchain.com/langsmith/evaluation-concepts)
- **Evaluator** = fonction qui score et renvoie un feedback (dict `key`/`score`/`comment`). Familles : code/heuristique, LLM-juge (référence-libre ou référence-basé), humain, pairwise, summary (score d'un *experiment* entier).

### 3.2 Boucle offline — `client.evaluate()` (env 3.11)

```python
from langsmith import Client
ls_client = Client()

def correct(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
    score = outputs["class"] == reference_outputs["label"]
    return {"key": "correct", "score": score, "comment": "optional"}

results = ls_client.evaluate(
    toxicity_classifier,             # target (1er positionnel) : inputs dict -> outputs dict
    data=dataset.name,               # dataset name | UUID | itérateur d'examples
    evaluators=[correct],
    experiment_prefix="baseline",
    max_concurrency=4,
    num_repetitions=3,               # gère la non-déterminisme (vote sur N runs)
    metadata=EXPERIMENT_METADATA,
)
```
Args clé d'un evaluator (match par nom) : `inputs`, `outputs`, `reference_outputs`, plus `run`, `example`, `attachments`. **Offline voit Example + Run ; online voit Run seulement (pas de référence)** → les évaluateurs référence-basés sont **offline-only**. (source : https://docs.langchain.com/langsmith/evaluate-llm-application)

### 3.3 Évaluation de trajectoire — `agentevals` (env 3.11)

Package LangChain prêt à l'emploi. Dernière release notée : js 0.0.7 (2026-03-03), Python sur PyPI. (source : https://github.com/langchain-ai/agentevals)

**Trajectory match (déterministe, sans LLM)** — pour workflows bien définis :
```python
from agentevals.trajectory.match import create_trajectory_match_evaluator

evaluator = create_trajectory_match_evaluator(
    trajectory_match_mode="strict",     # strict | unordered | subset | superset
    tool_args_match_mode="exact",       # exact | ignore | subset | superset
    tool_args_match_overrides={
        "get_weather": lambda x, y: x["city"].lower() == y["city"].lower()
    },
)
result = evaluator(outputs=outputs, reference_outputs=reference_outputs)
```

| Mode | Sens |
|---|---|
| `strict` | messages + tool calls exacts, même ordre |
| `unordered` | mêmes tool calls, ordre quelconque |
| `subset` | l'agent n'appelle **que** des outils de la référence (pas d'extra) |
| `superset` | l'agent appelle **au moins** les outils de la référence (extras OK) |

Format de trajectoire = liste de dicts OpenAI-format **ou** objets `BaseMessage` LangChain (`HumanMessage`/`AIMessage(tool_calls=[...])`/`ToolMessage(tool_call_id=...)`).

**Trajectory LLM-as-judge (flexible, coûte des appels LLM)** — défaut pratique car le labeling humain ne *scale* pas :
```python
from agentevals.trajectory.llm import (
    create_trajectory_llm_as_judge,
    TRAJECTORY_ACCURACY_PROMPT,                 # référence-libre
    TRAJECTORY_ACCURACY_PROMPT_WITH_REFERENCE,  # vs trajectoire de référence
)
evaluator = create_trajectory_llm_as_judge(
    prompt=TRAJECTORY_ACCURACY_PROMPT,
    model="openai:o3-mini",        # exemple corpus ; PIN la version du juge
    continuous=False,              # True -> float 0..1 ; choices=[...] pour scores discrets
)
eval_result = evaluator(outputs=outputs)
```
**Graph trajectories (LangGraph)** : `extract_langgraph_trajectory_from_thread(graph, {"configurable": {"thread_id": "1"}})` puis `create_graph_trajectory_llm_as_judge(...)` ou `graph_trajectory_strict_match(...)`. Variantes async : préfixe `create_async_*` (juge `AsyncOpenAI`). (source : https://github.com/langchain-ai/agentevals)

### 3.4 Régression en CI — pytest (env 3.11)

LangSmith a livré les intégrations **Pytest + Vitest/Jest dans `langsmith` v0.3.0** (cache test par URL/host en `>= 0.4.10`). (sources : https://blog.langchain.com/pytest-and-vitest-for-langsmith-evals/ · https://docs.langchain.com/langsmith/pytest)

```python
import pytest
from langsmith import testing as t
from agentevals.trajectory.llm import create_trajectory_llm_as_judge

trajectory_evaluator = create_trajectory_llm_as_judge(model="openai:o3-mini")

@pytest.mark.langsmith
def test_trajectory_accuracy():
    outputs = [...]; reference_outputs = [...]
    t.log_inputs({}); t.log_outputs({"messages": outputs})
    t.log_reference_outputs({"messages": reference_outputs})
    trajectory_evaluator(outputs=outputs, reference_outputs=reference_outputs)
```
Utilitaires : `t.log_inputs/log_outputs/log_reference_outputs`, `t.log_feedback(key=..., score=...)`, `with t.trace_feedback():`. Assertions : `expect(sql).to_contain("customers")`, `expect.embedding_distance(...).to_be_less_than(0.5)`, `expect.edit_distance(...)`. Run : `pytest test_x.py --langsmith-output`. **Cacher les appels LLM** (`LANGSMITH_TEST_CACHE=tests/cassettes`) → CI rapide/déterministe/peu chère ; `LANGSMITH_TEST_TRACKING=false` pour ne pas uploader en local. (source : https://docs.langchain.com/langsmith/pytest)

> **OWIsMind (3.9) :** la régression côté backend = `unittest` stdlib (des centaines de cas), avec **LLM mocké** dans le *scaffolding* déterministe (loop caps, extraction, rendering, paramétrage) + **golden queries** depuis `docs/questions_asked.md` + **tests anti-dérive** (`KNOWN_TOOL_NAMES`/`KNOWN_BLOCK_IDS` ↔ registre). Lancement : `python3 -m unittest discover -s dataiku-agents/tests`.

### 3.5 LLM-as-judge — bien le faire

Tips Anthropic (verbatim) : **rubriques détaillées et claires** ; **sortie empirique/spécifique** (forcer `correct`/`incorrect` ou échelle 1–5) ; **raisonner puis jeter le raisonnement** (penser d'abord, sortir le score, dropper le reasoning). Best practice : **utiliser un modèle différent** du générateur pour juger. (source : https://platform.claude.com/docs/en/test-and-evaluate/develop-tests)

```python
def build_grader_prompt(answer, rubric):
    return f"""Grade this answer based on the rubric:
    <rubric>{rubric}</rubric>
    <answer>{answer}</answer>
    Think through your reasoning in <thinking> tags, then output 'correct' or 'incorrect' in <result> tags."""
```

Design d'éval Anthropic : **task-specific** (refléter la distribution réelle + cas limites : données inexistantes, inputs trop longs, chat hostile, ambiguïté réelle) ; **automatiser** quand possible ; **volume > qualité** (plus de questions à correction automatique bat quelques cas main-gradés). Critères de succès **SMART + multidimensionnels** (ex. F1 ≥ 0.85 *et* 99.5% non-toxique *et* 95% < 200 ms). (source : idem)

**Biais de juge à combattre** (consensus 2025–2026) : position/ordre (favorise 1er/dernier), longueur/verbosité, style, self-preference (favorise ce qui lui ressemble). Mitigations : rubriques explicites/critères séparés ; **pairwise réduit la variance de calibration vs scoring absolu** ; **swap/moyenne des deux ordres** ; ancrer avec des références humaines sur les cas critiques ; **mesurer périodiquement l'accord juge↔humain** (traiter le juge comme un modèle à valider, pas comme la vérité). **PIN (verrouiller) la version du modèle juge** — « exigence d'ingénierie standard, plus optionnel ». (sources : https://aman.ai/primers/ai/LLM-as-a-judge/ · https://arize.com/llm-as-a-judge/ · https://arxiv.org/pdf/2409.16788)

### 3.6 Offline vs online (les deux nécessaires)

| | **Offline** | **Online** |
|---|---|---|
| Cible | datasets / examples | tracing projects (runs / threads) |
| Données | inputs, outputs, **références** | inputs, outputs seulement (pas de référence) |
| Timing | pré-deploy, batch | prod, temps réel |
| Usages | benchmark, régression, CI, backtesting | détection d'anomalies, monitoring qualité, guardrails inline |

Stratégie gagnante = **les deux** : offline *gate* chaque changement, online surveille la réalité, et **les échecs online alimentent de nouveaux examples offline**. Garde une suite offline **stable** : un prompt « meilleur » peut régresser sur held-out (« When 'Better' Prompts Hurt »). (sources : https://docs.langchain.com/langsmith/evaluation-concepts · https://arxiv.org/pdf/2411.13768)

### 3.7 Recette « Evaluate Agent » + Agent Review (Dataiku DSS 14)

**Evaluate Agent recipe** (framework livré en **14.3.0**) — évalue des agents *transactionnels mono-tour* sur **réponse finale ET chemin de décision** ; écrit dans un **GenAI Evaluation Store** pour GenAIOps.
- **Prérequis** : add-on **Advanced LLM Mesh** ; code env **Python 3.9+** avec le preset **« Agent and LLM Evaluation »** ; un LLM embeddings + un LLM completion (via Mesh).
- **Input = un dataset unique** (sortie du pipeline). Colonnes : **input** (requête), **output** (réponse texte), **actual tool calls** (array de noms d'outils), **ground truth** (réponse de référence), **reference tool calls** (outils attendus). Presets alt : « Prompt Recipe », « Agent Interaction Logs ».
- **Métriques built-in** : validation de séquence d'outils (in-order et out-of-order), **LLM-as-judge via RAGAS**, **BERTScore** (comparaison embeddings).
- **Custom** : métriques Python (floats, single ou per-row) ; **custom traits** = assertions LLM no-code en pass/fail par ligne.
- **Outputs** : dataset de sortie (inputs + métriques par ligne), dataset de métriques (1 ligne agrégée/run), Evaluation Store.
- **Analyse** : **Trajectory Explorer** (chrono : input, tool-call nodes avec inputs/outputs/erreurs, guardrail-trigger nodes, final-output) + **Comparisons** côte-à-côte.

**Agent Review** (livré 14.0.0, enrichi 14.4.0) — cadre collaboratif : builders + experts métier définissent des **cas de test**, une **référence**, des **attentes comportementales**, puis auditent l'agent **par LLM-as-a-judge ET feedback humain**. C'est le découplage observabilité / éval batch / revue humaine. (sources : https://doc.dataiku.com/dss/latest/agents/evaluation.html · https://doc.dataiku.com/dss/latest/release_notes/14.html)

> **OWIsMind (3.9) :** le preset « Agent and LLM Evaluation » est compatible Python 3.9+, mais **vérifier sa disponibilité** avant de s'y fier. Le logging SQL direct existant est l'input dataset équivalent.

---

## 4. Sécurité — OWASP LLM Top 10 (2025, l'édition de référence)

| Code | Titre | En une ligne |
|------|-------|----------|
| **LLM01** | Prompt Injection | Input que le modèle traite comme instruction, pas comme donnée |
| **LLM02** | Sensitive Information Disclosure | Le modèle reproduit PII / données proprio / system prompt |
| **LLM03** | Supply Chain | Modèles, datasets, plugins, frameworks compromis |
| **LLM04** | Data and Model Poisoning | Données d'entraînement/fine-tune trafiquées → biais/backdoors |
| **LLM05** | Improper Output Handling | L'app exécute une sortie LLM non validée → injection aval |
| **LLM06** | Excessive Agency | L'agent a plus d'outils/permissions/autonomie que la tâche n'exige |
| **LLM07** | System Prompt Leakage | Extraction des règles/logique du system prompt |
| **LLM08** | Vector and Embedding Weaknesses | Empoisonnement RAG, contrôle d'accès défaillant |
| **LLM09** | Misinformation | Sortie faussement confiante traitée comme autorité |
| **LLM10** | Unbounded Consumption | DoS, « wallet depletion », extraction de modèle par abus de coût |

L'édition 2025 (publiée Nov 2024) a explicitement promu les risques **agentiques** (Excessive Agency, System Prompt Leakage). (sources : https://genai.owasp.org/ · https://aembit.io/blog/owasp-top-10-llm-risks-explained/)

### 4.1 Prompt injection (LLM01) — le problème racine non résolu

Cause racine : le LLM traite **instructions et données dans le même canal**, sans séparation dure → le contenu d'un attaquant peut être lu comme une instruction. « Ces inputs n'ont pas besoin d'être lisibles par un humain — il suffit qu'ils soient parsés par le modèle. » (source : https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- **Directe** : l'input utilisateur change le comportement.
- **Indirecte** (la dangereuse pour les agents qui browsent/query) : l'input vient de pages web, fichiers, documents RAG, **sorties d'outils, lignes de DB** — *l'attaquant n'est pas l'utilisateur*.

Mitigations OWASP : contraindre le comportement (rôle/capacités/limites) ; définir/valider les formats de sortie ; filtrage input/output ; **enforcer le contrôle de privilège** ; **exiger l'approbation humaine** pour les opérations privilégiées ; **ségréguer le contenu externe** (le dénoter clairement comme non fiable) ; tests adversariaux.

> **Vérité dure (consensus 2026) :** le prompt injection **n'est pas soluble au niveau du prompt**. Ne pas s'appuyer sur des garde-fous type « ignore previous instructions » comme contrôle primaire. Les défenses durables sont *architecturales* : outils à moindre privilège, read-only forcé dans la DB elle-même, sortie traitée comme non fiable, approbation humaine pour les actions à effet de bord. « Même si le LLM est détourné, il ne peut exécuter que le plan pré-approuvé, n'utiliser que les outils accordés pour l'étape courante, et ne faire tourner du code que dans un sandbox verrouillé. » (source : https://arxiv.org/pdf/2509.08646)

### 4.2 Excessive Agency (LLM06) — outils à moindre privilège

Le contrôle d'agent à plus fort levier. OWASP nomme **trois dimensions** : moindre fonctionnalité, moindre permission, moindre autonomie. Mitigations : restreindre les permissions au strict nécessaire ; approbation humaine sur les décisions à fort impact ; contrôles d'identité (l'agent agit dans un contexte de sécurité limité, **jamais** avec une identité générique privilégiée) ; **implémenter l'autorisation dans les systèmes externes, indépendamment du LLM** (la DB/API enforce ; le modèle ne détient jamais la seule clé). (sources : https://aembit.io/blog/owasp-top-10-llm-risks-explained/ · https://www.oligo.security/academy/owasp-top-10-llm-updated-2025-examples-and-mitigation-strategies)

Traduction code agent :
- **Un outil étroit par capacité** ; **aucun** outil « run arbitrary SQL/shell » exposé au modèle.
- Le backend résout les **clés logiques → IDs réels** (whitelist). Le modèle émet une *sélection logique*, pas une connection string / table / `agent_id` brut. **C'est exactement la règle OWIsMind** : le front envoie une clé `{key,label}`, le serveur résout l'`agent_id` (CLAUDE.md règle #4).
- Scoper les credentials à la tâche ; jamais réutiliser les credentials larges d'un humain pour un agent.

### 4.3 Improper Output Handling (LLM05) — la sortie comme input non fiable

Valider/sanitiser tout contenu généré avant de le passer à un autre composant ; **empêcher l'exécution de code embarqué** dans les réponses. Pour un code agent : jamais `eval()`/`exec()` sur la sortie ; jamais interpoler du texte modèle dans une string SQL / commande shell / page HTML (XSS) / chemin de fichier sans validation. Le SQL généré est **re-validé côté serveur** et tourne sous contraintes DB dures. (source : https://aembit.io/blog/owasp-top-10-llm-risks-explained/)

### 4.4 Sûreté text-to-SQL & enforcement read-only (directement pertinent ici)

Défense en profondeur, enforcée **hors** du modèle :
- **Rôle DB read-only** sur des **tables spécifiques** → réduit le rayon de souffle d'une injection. (source : https://www.kiuwan.com/blog/top-5-best-practices-for-developers-on-preventing-sql-injections-attacks/)
- **Garde par transaction** : `SET LOCAL transaction_read_only = on;` bloque les écritures même si le rôle est sur-privilégié. *(OWIsMind le fait déjà : `SET LOCAL transaction_read_only TO on` + `SET LOCAL statement_timeout TO '30000'` en `pre_queries`, evidence layer / L045.)*
- **`statement_timeout`** (ex. 30s) → borne les requêtes runaway/DoS (LLM10) au niveau DB.
- **Requêtes paramétrées** = « la méthode la plus efficace » contre l'injection SQL. Jamais de concaténation de string. *(Dataiku : `dataiku.sql.Constant`/`toSQL` — CLAUDE.md règle #3.)*
- **Aucune route SQL générique** exposée au front ; le modèle ne choisit jamais table/connexion.
- **Couche de politique (tendance 2026)** : Open Policy Agent (OPA) devant l'agent text-to-SQL pour des allow-lists row/column/table déclaratives. (source : https://kubetools.io/stop-sql-injection-2026-secure-text-to-sql-agents-open-policy-agent-opa/)

### 4.5 Sandboxing de code (agents qui exécutent du code)

Consensus 2026 : **« Docker n'est pas un sandbox »** — les conteneurs à noyau partagé n'isolent pas suffisamment du code IA non fiable. Pour du code non maîtrisé : **microVMs (Firecracker)** ou **user-space kernels (gVisor)**. **E2B** = runtime open-source (chaque sandbox = microVM Firecracker, noyau + namespace réseau propres). (sources : https://github.com/restyler/awesome-sandbox · https://www.firecrawl.dev/blog/ai-agent-sandbox)

> **Dataiku :** les code agents tournent dans des code envs DSS — **pas de microVM par appel**, isolation au niveau process/env. Donc pour les code agents DSS, s'appuyer fort sur les *autres* contrôles : aucun outil à code arbitraire exposé, SQL read-only, paramétrage, whitelist d'agents, approbation humaine — **pas** sur la résistance à l'évasion de sandbox.

### 4.6 System Prompt Leakage (LLM07) & Sensitive Disclosure (LLM02)

« Traiter les system prompts comme potentiellement exposés plutôt que de s'appuyer dessus pour la sécurité. » Jamais de secrets, connection strings brutes, ou l'unique copie d'une règle d'autorisation dans un system prompt. Appliquer un filtrage de sortie sur les patterns sensibles. (source : https://aembit.io/blog/owasp-top-10-llm-risks-explained/)

---

## 5. Gouvernance Dataiku — guardrails, approbation, RBAC

### 5.1 Guardrails LLM Mesh (LLM Guard Services)

Ensemble extensible screenant prompts **et** réponses. Types documentés : **PII detection** (détecter/rédiger), **prompt-injection detection**, **toxicity**, **topics boundaries**, **bias detection**, **custom guardrails** (logique propre). Configuration à **3 niveaux** : connexion, agent, usage-time. Comme ils sont dans le Mesh, ils s'appliquent **aux agents et tools aussi**, pas seulement aux appels modèle bruts. (Unified + Custom Guardrails depuis 13.4.0.) (sources : https://doc.dataiku.com/dss/latest/generative-ai/guardrails/index.html · https://www.dataiku.com/product/llm-guard-services)

**Custom guardrails** peuvent **rejeter, modifier ou réécrire** une requête ou une réponse — c'est le point de contrôle déterministe à mettre devant/derrière le LLM. Pour le RAG, des **RAG guardrails** évaluent **relevance** et **faithfulness** de la réponse vs les extraits récupérés (voir `references/rag-et-knowledge-banks.md`).

### 5.2 Human-in-the-loop / validation d'outil (approbation avant exécution)

Quand un agent doit obtenir l'approbation avant d'exécuter un outil, la réponse porte un array **`toolValidationRequests`** ; chaque entrée a `id` (obligatoire), `toolCall` (`function.name` + `function.arguments` JSON), et **`allowEditingInputs`** (bool — l'humain peut **éditer les inputs** du tool call). Reprise après approbation :
```python
completion.with_tool_validation_response(tvreq["id"], validated=True)
```
HITL pour Visual Agents livré en **14.0.0** ; gestion trajectoire + HITL améliorée en **14.3.0**. (source : https://developer.dataiku.com/latest/concepts-and-examples/agents.html) Côté LangGraph, l'équivalent est `interrupt()` + reprise par `Command(resume=...)` (voir `references/memoire-persistance-hitl.md`).

### 5.3 RBAC & identité « run-as end-user » (sécurité ligne à ligne)

Le RBAC permet d'exécuter certains outils avec l'**identité de l'utilisateur final** → respecter la **sécurité ligne à ligne** sur les datasets. Conséquence design : ce que le LLM ne doit ni voir ni choisir (tenant id, filtres RLS, secrets) passe **hors bande** dans `tool.run(input, context={...})` — **jamais** dans `input` (que le LLM voit et peut altérer). (sources : ChatGPT source réconcilié · https://doc.dataiku.com/dss/latest/agents/tools/using-tools.html)

### 5.4 Cost Guard — quotas & rate limiting (LLM10)

- **Quotas** (cost control) : filtres de scope (provider / projet / connexions / users), montant en **USD**, période de reset, **blocage** optionnel à l'épuisement, **alertes** email, **Fallback Quota** (catch-all ; une requête peut matcher plusieurs quotas, tous incrémentés). Personnaliser les quotas exige la licence **Advanced LLM Mesh**. **Non cost-trackés** (mais blocables) : SageMaker, Databricks Mosaic AI, Snowflake Cortex.
- **Rate limiting** : Administration > Settings > LLM Mesh > Rate Limiting ; **par modèle et par provider**, en **RPM**. (sources : https://doc.dataiku.com/dss/latest/generative-ai/cost-control.html · https://doc.dataiku.com/dss/latest/generative-ai/rate-limiting.html)

> **Le LLM Mesh EST le gateway** : il centralise auth/quota/audit/routing. Le code d'agent ne doit **pas** réimplémenter le retry provider contre des APIs brutes ; s'appuyer sur le Mesh et n'ajouter que les caps de boucle et l'idempotence. Pour le quota $50/mois/user d'OWIsMind : soit app-side (`webapp_usage_monthly_v1`, O(1)), soit quota Mesh filtré par user (blocage + audit gratuits, mais licence Advanced + config admin).

---

## 6. Fiabilité & tolérance aux pannes

Les agents échouent autrement que le code ordinaire : boucles d'outils infinies, tool calls tronqués, 429/5xx transitoires, raisonnement non progressant. Production = caps explicites + récupération.

### 6.1 Limites de boucle / récursion

LangGraph cape les super-steps avec **`recursion_limit`, défaut = 25** (PAS 1000). Le dépassement lève `GraphRecursionError`. **Augmenter par invocation**, pas en changeant un défaut :
```python
graph.invoke(inputs, config={"recursion_limit": 100})
```
Si tu n'attendais pas autant d'itérations → tu as probablement un **cycle**. (source : https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT)

**Boucle agentique à la main (Dataiku 3.9 / SDK brut)** : toujours borner avec un compteur `max_iterations` + une deadline wall-clock ; **jamais** `while True` non borné.
```python
def process_query(query, max_iterations=8):
    chat = create_chat_session()
    chat.with_message(query, role="user")
    for _ in range(max_iterations):              # cap dur — jamais non borné
        response = chat.execute()
        if not response.tool_calls:
            return response                       # réponse finale
        chat.with_tool_calls(response.tool_calls, role="assistant")
        result = process_tool_calls(response.tool_calls)
        chat.with_tool_output(result, tool_call_id=response.tool_calls[0]["id"])
    raise RuntimeError("agent did not converge within max_iterations")
```
(source : https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/llm-agentic/agents/index.html)

### 6.2 Gestion de `stop_reason` (boucles Claude / LLM Mesh brutes)

La boucle agentique est pilotée par `stop_reason` — **toujours le vérifier** (distinct des erreurs HTTP).

| `stop_reason` | Sens | Traitement |
|---|---|---|
| `end_turn` | Complétion naturelle | Utiliser le contenu. |
| `tool_use` | Appel d'outil | Exécuter, append `tool_result`, reboucler. |
| `max_tokens` | A heurté ton `max_tokens` | Si dernier bloc = `tool_use` **incomplet** → retry avec `max_tokens` plus haut. |
| `pause_turn` | Boucle de server-tool a heurté sa limite (défaut **10/requête**) | Renvoyer la réponse assistant **telle quelle** pour continuer. |
| `refusal` | Refus modèle (renvoyé en **HTTP 200**) | Inspecter `stop_details` ; envisager retry sur un autre modèle. |
| `model_context_window_exceeded` | Fenêtre de contexte (pas ton `max_tokens`) | Réponse valide mais tronquée. |

**Gotcha — réponses `end_turn` vides** : ajouter un bloc de texte juste *après* un `tool_result` apprend au modèle à attendre l'input utilisateur après chaque outil → il finit son tour trop tôt / renvoie vide. **Ne jamais ajouter de texte après un `tool_result`** ; si vide, appendre un *nouveau* message user « Please continue ». **En streaming**, `stop_reason` est `null` dans `message_start`, peuplé dans `message_delta` (pertinent pour le polling-via-thread d'OWIsMind). (source : https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons)

### 6.3 Retries / timeouts / backoff (LangGraph, env 3.11)

```python
from langgraph.types import RetryPolicy, TimeoutPolicy

RetryPolicy(
    initial_interval=0.5, backoff_factor=2.0, max_interval=128.0,
    max_attempts=3, jitter=True,                 # jitter -> évite le thundering herd
    retry_on=(ConnectionError, TimeoutError),
)
TimeoutPolicy(run_timeout=30.0, idle_timeout=5.0, refresh_on="auto")
```
Défaut `retry_on` conservateur : `ConnectionError`, **5xx** httpx/requests, transitoires — **mais pas** `ValueError`/`TypeError`/`RuntimeError` (ne pas retry les bugs). `ToolNode` a `handle_tool_errors` : sur exception d'outil, renvoie l'erreur au LLM comme `ToolMessage` (« errors as context ») → le modèle se corrige sans crasher le graphe. (sources : https://www.langchain.com/blog/fault-tolerance-in-langgraph · https://deepwiki.com/langchain-ai/langgraph/3.8-error-handling-and-retry-policies) Détail dans `references/langgraph-v1.md`.

**Règles framework-agnostiques (valent aussi en 3.9, à coder à la main) :** retry **seulement** 429, 500, 502, 503, 504, **529** (overload Anthropic) ; jamais les 4xx de validation ; **backoff exponentiel + jitter** ; **respecter `Retry-After`** (Anthropic le renvoie sur les 429 — l'honorer avant ton propre backoff). (sources : https://orq.ai/blog/api-rate-limit · https://www.clawpulse.org/blog/llm-api-rate-limiting-best-practices-avoid-429-errors-and-save-40-on-costs)

### 6.4 Exécution durable & reprise

LangGraph (v1.0, oct 2025). Trois **modes de durabilité**, défaut **`"async"`** — le passer explicitement :
```python
graph.invoke(inputs, durability="async")   # "exit" (rapide) | "async" (défaut, équilibré) | "sync" (max durable)
```
Deux couches : **checkpointers** (état court terme par `thread_id`) + **stores** (données long terme inter-threads). **Caveat critique** : checkpoints ≠ exécution durable complète — si deux process reprennent le même `thread_id` concurremment, LangGraph n'a **pas** de coordination ; verrouillage/lease distribués à ta charge (ou pairer avec Temporal/Dapr pour de l'exactly-once). (sources : https://docs.langchain.com/oss/python/langgraph/durable-execution · https://www.diagrid.io/blog/checkpoints-are-not-durable-execution-why-langgraph-crewai-google-adk-and-others-fall-short) Détail dans `references/memoire-persistance-hitl.md`.

> **OWIsMind (3.9) :** les code agents DSS sont request/response (polling-via-thread), pas des graphes durables. La durabilité ici = le store SQL (`webapp_chat_v5` runs/events) + un flag de stop coopératif — pas des checkpointers LangGraph.

### 6.5 Idempotence & échec partiel

Les agents retry et reprennent → tout outil **à effet de bord** doit être sûr à appeler plusieurs fois.
- **Idempotency keys** : un outil qui écrit (créer un enregistrement, envoyer un email, débiter) accepte une clé fournie par l'appelant ; le backend dédoublonne. Sans ça, un step rejoué double-exécute.
- **Préférer les outils read-mostly** (naturellement idempotents) ; gater les écritures derrière l'approbation humaine.
- **Échec partiel en fan-out** (orchestrator-workers, voting) : décider par worker — fail-fast vs collect-and-degrade. Capturer succès/erreur de chaque worker pour que le synthétiseur raisonne sur des résultats partiels. *(OWIsMind : `AGENT_RESULT` = statut machine + fan-out parallèle ; voir `references/orchestration-multi-agents.md`.)*
- **Checkpoint avant effet de bord** pour qu'une reprise ne rejoue pas une écriture déjà appliquée.

---

## 7. Coût & comptabilité de tokens

Les agents sont des **amplificateurs de tokens** : boucles multi-tours, historiques re-envoyés, tokens de raisonnement multiplient la dépense.

- **Prompt caching = le plus gros levier** : jusqu'à **−90% coût / −85% latence** sur les préfixes longs et stables (cache reads ≈ 10× moins cher). Mettre le **stable** (system prompt, schémas d'outils, few-shot, schéma/profil) au **début**, le **dynamique** (la requête) à la **fin** → préfixe cacheable large et réutilisé. Exactement le pattern semantic-model / Dataset-Expert d'OWIsMind. Le caching s'empile avec la Batch API (−50%) → −95%+ effectifs. (sources : https://introl.com/blog/prompt-caching-infrastructure-llm-cost-latency-reduction-guide-2025 · https://www.digitalocean.com/blog/prompt-caching-with-digital-ocean) Détail tokens/pricing Anthropic → skill `claude-api`.
- **Thinking adaptatif** : l'extended thinking « multiplie les coûts » (une réponse visible de 500 tokens peut porter 5 000 tokens de réflexion). Réserver aux tours réellement durs (routing/composition). *Note recency : sur Opus 4.7/4.8 et Fable 5, `thinking.budget_tokens` est retiré (400) — utiliser `thinking: {type:"adaptive"}` + `output_config.effort` ; voir skill `claude-api`.*
- **Outils token-efficients** : retourner du contexte high-signal, des **noms sémantiques pas des UUIDs**, un `response_format` enum (`"concise"` ≈ 72 tokens vs `"detailed"` ≈ 206), pagination/filtrage/truncation. (source : https://www.anthropic.com/engineering/writing-tools-for-agents)
- **Suivi d'usage + cap de budget (LLM10)** : mesurer in/out/total tokens + coût estimé **par échange**, à la source de vérité ; **enforcer un cap mensuel** en pré-flight avant de démarrer un run. *(OWIsMind Run 4 : `webapp_chat_v5` 4 colonnes usage + cumul lifetime `users` + `webapp_usage_monthly_v1` quota O(1) ; le cap 50 $/mois est prêt mais pas branché — hook `/chat/start` avant `start_run`, L049.)*
- **Right-sizing par étape** : router les steps simples vers un petit modèle (Haiku-class), réserver les gros modèles au raisonnement dur (voir `references/modeles-routing-caching.md`).

---

## 8. Versioning & rollout des prompts et agents

Traiter prompts et définitions d'agents comme du code shippé indépendamment du binaire de l'app. (sources : https://www.braintrust.dev/articles/what-is-prompt-versioning · https://tianpan.co/blog/2026-03-13-prompt-versioning-change-management-production)

- **Versions immuables** — tout changement = nouvelle version ; les anciennes restent accessibles pour rollback instantané.
- **Hotfix / rollback sans redéploiement** — changer/revert un prompt indépendamment du binaire.
- **CI eval gate** — avant de déployer une version, tester contre **15–30 examples** (commun + limite + adversarial).
- **Canary** — déployer la nouvelle version sur **5–10%** du trafic, surveiller quality/error/latence, puis promouvoir ou stopper.
- **Échelle d'investissement** : ad-hoc jusqu'à ~10–20 prompts ; rollout (%→A/B) ensuite ; **prompt registry** au-delà de ~50.
- **Séparation d'environnements** dev/staging/prod.

**Dataiku** : config scriptable via `get_settings()` → `get_raw()` / `save()` + versions (agent settings ; pour les semantic models, surface `project.get_semantic_model(...)` / `get_raw()` / `save()` **UNVERIFIED** — confirmer au runtime, ne pas citer comme doc). Versionner le JSON au repo = config-as-code.

> **OWIsMind :** analogue = specs de design gelées (`docs/superpowers/specs/`), golden-query regression, registre-as-manifeste + tests anti-dérive (la couche version-control + eval-gate). Un canary formel n'existe pas encore — candidat d'ajout. Repo = source de vérité des Code Agents ; déployer = recoller le(s) fichier(s) en DSS + **redémarrer le backend** (L047).

---

## 9. Checklist de lancement en production (condensée)

- [ ] **Outils à moindre privilège** : outils étroits, aucun outil arbitrary-SQL/shell, whitelist/résolution côté serveur (LLM06).
- [ ] **Contenu externe ségrégué & traité comme non fiable** (injection indirecte, LLM01).
- [ ] **Output handling** : pas d'`eval`/`exec`/concat-SQL de sortie modèle ; SQL généré re-validé (LLM05).
- [ ] **DB** : rôle read-only + `SET LOCAL transaction_read_only` + `statement_timeout` + requêtes paramétrées.
- [ ] **Approbation humaine** sur les actions à effet de bord / fort impact (`toolValidationRequests` Dataiku ou `interrupt()` LangGraph) ; éditer les inputs autorisé.
- [ ] **RBAC / run-as end-user** + filtres RLS hors bande dans `context`, jamais dans `input`.
- [ ] **Caps de boucle** : `max_iterations` / `recursion_limit` (=25) ; timeouts wall-clock + idle ; jamais `while True` non borné.
- [ ] **`stop_reason` géré** : tool_use / max_tokens (retry sur tool_use incomplet) / pause_turn / refusal / context-exceeded.
- [ ] **Retries** : seulement 429/5xx/529, backoff exponentiel + jitter, honorer `Retry-After`, jamais les erreurs de validation.
- [ ] **Idempotency keys** sur les outils d'écriture ; checkpoint avant effet de bord ; échec partiel géré en fan-out.
- [ ] **Coût** : prompt caching sur préfixe stable ; thinking adaptatif/budgeté ; usage par échange ; cap mensuel pré-flight (LLM10) ; quotas + rate limiting Mesh.
- [ ] **Concurrence** : `asyncio.gather` borné ; pas de reprise concurrente du même `thread_id` ; Mesh comme gateway de fleet.
- [ ] **Déterminisme** : scope LLM minimal, scaffolding déterministe, anti « règles par bug » ; `temperature=0` + modèle/prompt pinnés (voir `references/prompting-et-determinisme.md`).
- [ ] **Évals** : gate CI offline (15–30 cas) + golden-query regression + monitoring de traces online + LLM-juge pinné + tests anti-dérive ; les trois cibles (réponse/trajectoire/étape).
- [ ] **Versioning** : versions immuables, rollback sans redéploiement, canary 5–10%, registry au-delà de ~50 prompts.
- [ ] **Tracing/transparence** : émettre les spans/étapes de planification pour audit (`trace.subspan` Dataiku ; LangSmith/OTel en 3.11) ; interaction logging activé.
- [ ] **Guardrails Mesh** : PII / injection / toxicity / topics / custom (reject/modify/rewrite) configurés aux 3 niveaux.

---

## 10. « Quand utiliser quoi » — éval, tracing, sécurité

| Situation | Choix |
|---|---|
| Workflow d'outils déterministe connu | `create_trajectory_match_evaluator(mode="strict"/"unordered"/"subset"/"superset")` — sans coût LLM |
| Agent flexible, pas de chemin unique correct | `create_trajectory_llm_as_judge(...)` (juge pinné, ordres swappés) |
| Correctness de chemin LangGraph (nodes) | `extract_langgraph_trajectory_from_thread` + graph trajectory evaluators |
| Bon outil à un point de décision | single-step / tool-selection eval (code-match nom+args) |
| Réponse finale catégorielle | code exact/string match |
| Réponse finale texte libre vs golden | embedding/cosine, ROUGE-L, ou LLM-juge à rubrique |
| Objectif sur toute la conversation | Multi-turn Evals (intent / outcome / trajectory) |
| Régression à chaque PR | pytest/Vitest + LangSmith, **cachés**, gating CI (3.11) ; `unittest` + mocks + golden (3.9) |
| Qualité/sécurité live | online evaluators + guardrails sur tracing projects |
| Télémétrie portable cross-vendor | OTel GenAI semconv (`gen_ai.*`) |
| Écosystème Phoenix / auto-instrum existante | OpenInference (émet aussi OTel) |
| Auto-instrum OpenAI/Anthropic/LangChain | OpenLLMetry (Traceloop) → OTLP |
| **Dans Dataiku DSS 14** | traces LLM Mesh + Trace Explorer + Evaluate Agent recipe + Agent Review + Evaluation Store + cost control |
| Code à exécution non fiable | microVM Firecracker/gVisor (E2B) — « Docker n'est pas un sandbox » ; **pas** disponible par appel en DSS → moindre privilège |
| Outil à effet de bord | idempotency key + approbation humaine (LLM06) |
| Fetch de données pour analyse | rôle read-only + `transaction_read_only` + `statement_timeout` + paramétré |

---

## 11. Pitfalls / anti-patterns

- **Évaluer la réponse finale seulement** → ajouter trajectoire + étape.
- **Faire confiance à un LLM-juge non validé comme vérité** → biais position/longueur/self-preference ; calibrer contre l'humain, pinner la version.
- **Même modèle générateur et juge** → self-preference inflate les scores.
- **Pas de suite de régression offline** → les prompts « meilleurs » régressent en silence.
- **Pas de monitoring de prod** → l'offline n'anticipe pas tous les cas réels.
- **Trajectory matching trop strict** → `strict` échoue sur des réordonnancements bénins ; `unordered`/`superset`/`subset` ou LLM-juge.
- **Évaluateur référence-basé en online** → pas de référence en trafic live ; offline-only.
- **Ignorer coût/latence par étape** → impossible d'isoler l'étape chère sans attribution par span.
- **Appels LLM non cachés en CI** → lent, cher, flaky.
- **Se fier au prompt contre l'injection** → architectural, pas prompt-level.
- **Identité générique privilégiée pour l'agent** → run-as end-user + autorisation dans le système externe.
- **Secrets/filtres dans `input`** → le LLM les voit et peut les altérer ; mettre dans `context`.
- **`eval`/`exec`/concat-SQL de sortie modèle** ; **`while True` non borné** ; **outil à effet de bord non idempotent**.
- **Hard-coder une valeur métier pour « fixer » une requête** (« règles par bug ») → corriger dans les artefacts (semantic model / descripteurs d'outils), pas dans des branches d'agent.
- **Importer langchain/langsmith/agentevals en contexte 3.9** → APIs Dataiku natives.

---

## 12. Sources (les plus autoritaires d'abord)

- LangSmith — concepts d'évaluation : https://docs.langchain.com/langsmith/evaluation-concepts · trajectory : https://docs.langchain.com/langsmith/trajectory-evals · pytest : https://docs.langchain.com/langsmith/pytest · evaluate-llm-application : https://docs.langchain.com/langsmith/evaluate-llm-application
- agentevals : https://github.com/langchain-ai/agentevals
- Anthropic — define success criteria & build evals : https://platform.claude.com/docs/en/test-and-evaluate/develop-tests · handling stop reasons : https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons · writing tools : https://www.anthropic.com/engineering/writing-tools-for-agents · building effective agents : https://www.anthropic.com/research/building-effective-agents
- OpenTelemetry GenAI semconv : https://opentelemetry.io/docs/specs/semconv/gen-ai/ · agent spans : https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans/ · attributes : https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/
- OpenInference 2026 : https://futureagi.com/blog/what-is-openinference-2026/ · OpenLLMetry : https://github.com/traceloop/openllmetry · Phoenix : https://github.com/arize-ai/phoenix
- OWASP GenAI — Top 10 : https://genai.owasp.org/ · LLM01 : https://genai.owasp.org/llmrisk/llm01-prompt-injection/ · explained : https://aembit.io/blog/owasp-top-10-llm-risks-explained/ · SQL injection cheat sheet : https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html
- Plan-then-execute resilient agents : https://arxiv.org/pdf/2509.08646 · sandboxing : https://www.firecrawl.dev/blog/ai-agent-sandbox · https://github.com/restyler/awesome-sandbox · text-to-SQL OPA : https://kubetools.io/stop-sql-injection-2026-secure-text-to-sql-agents-open-policy-agent-opa/
- LangGraph — fault tolerance : https://www.langchain.com/blog/fault-tolerance-in-langgraph · recursion limit : https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT · durable execution : https://docs.langchain.com/oss/python/langgraph/durable-execution · checkpoints ≠ durable : https://www.diagrid.io/blog/checkpoints-are-not-durable-execution-why-langgraph-crewai-google-adk-and-others-fall-short
- Prompt caching / coût : https://introl.com/blog/prompt-caching-infrastructure-llm-cost-latency-reduction-guide-2025 · rate limiting : https://orq.ai/blog/api-rate-limit · prompt versioning : https://www.braintrust.dev/articles/what-is-prompt-versioning · https://tianpan.co/blog/2026-03-13-prompt-versioning-change-management-production
- Dataiku DSS 14 — tracing : https://doc.dataiku.com/dss/latest/agents/tracing.html · agent evaluation : https://doc.dataiku.com/dss/latest/agents/evaluation.html · guardrails : https://doc.dataiku.com/dss/latest/generative-ai/guardrails/index.html · cost control : https://doc.dataiku.com/dss/latest/generative-ai/cost-control.html · rate limiting : https://doc.dataiku.com/dss/latest/generative-ai/rate-limiting.html · agents (code/concepts) : https://developer.dataiku.com/latest/concepts-and-examples/agents.html · agents Python API : https://developer.dataiku.com/latest/api-reference/python/agents.html · release notes 14 : https://doc.dataiku.com/dss/latest/release_notes/14.html
</content>
</invoke>
