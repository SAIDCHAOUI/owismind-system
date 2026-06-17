# Panorama agentique & arbre de décision (workflow vs agent, choix du niveau d'abstraction)

> **À jour : juin 2026.** Baseline : LangChain 1.x (`langchain` 1.3.x, `langchain-core` 1.4.7), LangGraph 1.x, Dataiku DSS 14.x. Fichier de référence du skill `agentique-python-dataiku` — `SKILL.md` est le parent ; les frères sont cités par nom (ne pas dupliquer leur contenu).

Ce fichier répond à une seule question : **quel niveau d'abstraction et quel framework pour un problème agentique donné ?** Le reste du skill détaille chaque brique : `references/langchain-v1.md`, `references/langgraph-v1.md`, `references/dataiku-code-agents.md`, `references/orchestration-multi-agents.md`, `references/eval-tracing-securite-production.md`, `references/rag-et-knowledge-banks.md`, `references/code-patterns-dataiku.md`, `references/anti-patterns-deprecations-versions.md`.

---

## 1. Modèle mental (à internaliser avant tout choix)

Six principes, convergents entre Anthropic, le mouvement 12-factor et LangChain. Ils gouvernent toutes les décisions ci-dessous.

1. **Le LLM augmenté est l'atome.** Tout se compose à partir d'un LLM + retrieval + outils + mémoire ; le reste n'est que de l'orchestration autour de cet atome. (src : https://www.anthropic.com/research/building-effective-agents)
2. **La plupart des « agents » ne devraient pas être des agents.** Partir d'un seul appel LLM ; ajouter un *workflow* (chemin de code fixe orchestrant des appels LLM) seulement si un appel ne suffit pas ; ajouter un *agent autonome* (le LLM pilote sa propre boucle) seulement si le chemin est réellement imprévisible. « Find the simplest solution possible, and only increase complexity when needed. » (src : https://www.anthropic.com/research/building-effective-agents)
3. **Workflow vs agent autonome = la distinction centrale.** Workflow = « LLMs and tools are orchestrated through predefined code paths » ; agent = « LLMs dynamically direct their own processes and tool usage ». (src : https://www.anthropic.com/research/building-effective-agents)
4. **La fiabilité vient de l'ingénierie logicielle, pas du modèle.** Un bon agent est « mostly just software » avec le LLM placé uniquement là où le raisonnement probabiliste aide vraiment. (src : https://github.com/humanlayer/12-factor-agents)
5. **Le contexte est une ressource finie et qui s'épuise.** Le *context engineering* (curation du jeu minimal de tokens à haut signal à chaque étape) prime désormais sur la formulation du prompt — « context rot » : le rappel se dégrade quand la fenêtre se remplit. (src : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
6. **Possède ta boucle de contrôle, tes prompts et ta fenêtre de contexte.** Ne les délègue pas à la boucle cachée d'un framework. (src : https://github.com/humanlayer/12-factor-agents)

> **Convergence corpus ↔ ChatGPT.** La source ChatGPT formule la même thèse : enseigner « comment choisir le bon niveau d'abstraction, découper les responsabilités, contrôler le contexte et mettre l'agent sous gouvernance » plutôt que « comment écrire un prompt brillant ». LangChain v1 le dit aussi : *« Agent = Model + Harness »*, le harness étant prompt + outils + middleware qui « get the model the right context at the right time ». (src : https://docs.langchain.com/oss/python/langchain/overview)

Ligne la plus tranchante, valable partout (doc Microsoft Agent Framework) : **« If you can write a function to handle the task, do that instead of using an AI agent. »** (src : https://learn.microsoft.com/en-us/agent-framework/overview/)

---

## 2. L'échelle « as-tu vraiment besoin d'un agent ? »

Monte d'un barreau seulement quand le précédent ne suffit pas, et justifie chaque montée par une éval. Chaque barreau ajoute latence, coût et surface d'erreur.

| Barreau | Quand | Coût/risque |
|---|---|---|
| 0. **Fonction déterministe** (pas de LLM) | la tâche se code | nul — toujours préférer si possible |
| 1. **Un appel LLM** (+ self-consistency / vote si la précision est critique) | une tâche bien cadrée, une réponse | 1 appel ; N appels si vote |
| 2. **Workflow** (chemin de code fixe orchestrant des appels LLM) | séquence/branche/boucle métier connue d'avance | prévisible, traçable, debuggable |
| 3. **Agent autonome** (le LLM possède la boucle) | nombre d'étapes imprévisible, chemin non codable, environnement de confiance | plus cher, erreurs cumulatives → guardrails + sandbox + cap d'itérations obligatoires |
| 4. **Multi-agent** (superviseur + sous-agents) | domaines séparés, familles d'outils distinctes, isolation de contexte, parallélisme | recherche multi-agent ≈ **~15× les tokens** d'un chat ; réserver aux tâches à forte valeur et parallélisables (src : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) |

OpenAI dit la même chose autrement : commencer par **un seul agent + outils**, n'évoluer vers le multi-agent que quand la complexité l'exige. (src : https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf)

---

## 3. Workflow vs agent autonome

### 3.1 Les 5 patterns de workflow (chemins de code prédéfinis)

Canon d'Anthropic, *Building Effective Agents* — implémentables en quelques lignes contre une API LLM brute. (src : https://www.anthropic.com/research/building-effective-agents)

| Pattern | Définition (verbatim resserré) | Quand l'utiliser | Productionisé / lié à |
|---|---|---|---|
| **Prompt chaining** (§2.1) | « decomposes a task into a sequence of steps, where each LLM call processes the output of the previous one » + *gates* déterministes entre étapes | la tâche se découpe en sous-tâches fixes ; on échange de la latence contre de la précision | LCEL `a \| b \| c` ; `references/code-patterns-dataiku.md` |
| **Routing** | « classifies an input and directs it to a specialized followup task » | catégories d'entrée distinctes mieux traitées séparément ; permet le *cost-tiering* (petit modèle → cas faciles, gros → cas durs) | `RunnableBranch` ; orchestrateur OWIsMind par domaine métier |
| **Parallelization** | « LLMs working simultaneously … outputs aggregated programmatically » — variantes **sectioning** (sous-tâches indépendantes) et **voting** (même tâche N fois → vote) | sous-tâches indépendantes (vitesse) ou multiples perspectives (confiance) | `RunnableParallel`, `batch(max_concurrency=)` ; le *voting* = self-consistency |
| **Orchestrator-workers** | « a central LLM dynamically breaks down tasks, delegates them to worker LLMs, and synthesizes their results » | la décomposition **n'est pas connue d'avance** (différence avec parallelization) | superviseur multi-agent ; `langgraph-supervisor` |
| **Evaluator-optimizer** | « one LLM call generates a response while another provides evaluation and feedback in a loop » | critères d'éval clairs **et** l'itération améliore mesurablement la sortie | forme productionisée de Reflexion ; étape RENDER vérifiée d'OWIsMind |

```python
# Evaluator-optimizer, framework-agnostic
draft = llm_generate(task)
for _ in range(MAX_ROUNDS):
    verdict = llm_evaluate(task, draft)        # {"pass": bool, "feedback": str}
    if verdict["pass"]:
        break
    draft = llm_generate(task, feedback=verdict["feedback"])
```

### 3.2 L'agent autonome (le LLM possède la boucle)

L'agent reçoit une commande, planifie, agit, observe le *ground truth* de l'environnement (résultats d'outils, exécution de code, tests) à chaque étape, et s'arrête sur condition ou garde max-itérations. La boucle canonique est **ReAct** (thought → action → observation). « The agent loop is just a loop » — les frameworks ajoutent de l'ergonomie, pas de la magie. (src : https://www.anthropic.com/research/building-effective-agents ; https://github.com/humanlayer/12-factor-agents)

```python
# La « boucle agent » entière, à la main
messages = [system_prompt, user_task]
for _ in range(MAX_STEPS):
    resp = llm(messages, tools=TOOLS)          # le modèle choisit l'action
    if resp.tool_calls:
        for call in resp.tool_calls:
            messages.append(tool_result(call, dispatch(call)))
    else:
        return resp.text                       # le modèle a décidé d'arrêter
raise StoppedOnMaxSteps()
```

**Choisir agent plutôt que workflow** : problème ouvert où l'on ne peut ni prédire le nombre d'étapes ni coder le chemin, et où l'on peut faire confiance au modèle dans l'environnement. Caveats : « cost more, higher risk of compounding errors » → guardrails, sandbox, gestion d'erreurs, verification loops.

> Patterns de la littérature (ReAct, Reflexion, Plan-and-Execute / ReWOO / LLMCompiler, Tree-of-Thoughts, self-consistency, agentic RAG) : détaillés dans `references/code-patterns-dataiku.md`. Ici on ne garde que le critère de décision.

### 3.3 Table de décision « quel pattern »

| Situation | Pattern |
|---|---|
| Une tâche cadrée, une réponse | **Un appel LLM** (+ vote si précision critique) |
| Séquence fixe connue de sous-tâches | **Prompt chaining** |
| Catégories d'entrée distinctes / cost-tiering | **Routing** |
| Sous-tâches indépendantes / perspectives multiples | **Parallelization** (sectioning ou voting) |
| Décomposition inconnue jusqu'au runtime | **Orchestrator-workers** / superviseur |
| Critères d'éval clairs + amélioration itérative | **Evaluator-optimizer** |
| Ouvert, #étapes imprévisible, env. de confiance | **Agent autonome (boucle ReAct)** |
| Multi-hop / requête ambiguë / sources hétérogènes | **Agentic RAG** (sinon RAG statique) |

---

## 4. Choisir un framework

### 4.1 La hiérarchie LangChain → LangGraph → Dataiku

C'est l'axe structurant pour le lecteur DSS. Les trois ne sont **pas** concurrents : ce sont trois niveaux d'abstraction empilables.

```
                LangSmith   (observabilité / tracing / évals — produit séparé)
  ┌──────────────────────────────────────────────────────────────────┐
  │  Deep Agents      harness opinionated : planification, sous-agents │ sur ↓
  ├──────────────────────────────────────────────────────────────────┤
  │  langchain        HAUT NIVEAU : create_agent, init_chat_model,     │ sur ↓
  │                   @tool, messages/content_blocks, middleware       │
  ├──────────────────────────────────────────────────────────────────┤
  │  langgraph        RUNTIME BAS NIVEAU : graph, state, durabilité,   │ sur ↓
  │                   checkpointing, human-in-the-loop, streaming      │
  ├──────────────────────────────────────────────────────────────────┤
  │  langchain-core   abstractions : Runnable/LCEL, BaseChatModel,     │
  │                   messages + content blocks, prompts, parsers      │
  └──────────────────────────────────────────────────────────────────┘
       ⤷  le tout peut vivre DANS un Dataiku Code Agent (enveloppe entreprise)
```

- **`create_agent` *est* LangGraph sous le capot.** Les agents v1 de LangChain tournent sur le runtime LangGraph → ils héritent gratuitement de persistance, durabilité, time-travel et human-in-the-loop. (src : https://docs.langchain.com/oss/python/langchain/agents)
- **Commence par `create_agent`**, descends vers le LangGraph brut seulement quand tu as besoin d'un contrôle que l'abstraction agent n'expose pas (branches déterministes, boucles explicites, subgraphs, map-reduce, interruptions, reprise de run). (src : https://www.spheron.network/blog/langgraph-vs-langchain/)
- « Most production systems in 2026 use both: LangChain to build agents quickly, LangGraph to orchestrate/scale them reliably. » (src : https://www.clickittech.com/ai/langchain-1-0-vs-langgraph-1-0/)
- **Dataiku = l'enveloppe entreprise.** Chaque agent DSS devient un *Virtual LLM* dans le **LLM Mesh** → réutilisable partout, avec audit, sécurité, guardrails. C'est le point clé entreprise : l'agent n'est pas qu'un bout de code, c'est un objet gouverné de la plateforme. (apport ChatGPT, cohérent avec le corpus — détail dans `references/dataiku-code-agents.md`).

### 4.2 ⚠️ Le double chemin Python (FAIT DUR — décide quel niveau est même importable)

L'instance Dataiku a **DEUX** code environments : **Python 3.9 ET Python 3.11**. LangChain/LangGraph v1 exigent **Python ≥ 3.10**. Cela conditionne le choix de framework AVANT toute autre considération :

| Contexte | Python | Ce qui est importable | Chemin |
|---|---|---|---|
| **Code Agent assigné à un code env 3.11** | 3.11 (≥ 3.10) | `langchain`, `langgraph`, `create_agent` ; `DKUChatModel` (import exact à confirmer contre la doc DSS — UNVERIFIED, voir §4.2 gap) | tu peux poser `create_agent` dans le Code Agent |
| **Backend webapp OWIsMind** | **3.9.23** | **stdlib uniquement, AUCUN `import langchain`** | appeler LLM Mesh / agents / tools via les **APIs Dataiku natives directement** |

**Ne JAMAIS recommander d'importer langchain dans un contexte 3.9.** Toujours présenter les deux chemins quand la version compte. Les patterns du §3 sont framework-agnostic : en 3.9 on les implémente en appels LLM-Mesh bruts + Python déterministe (exactement ce que fait OWIsMind). En 3.11 on peut s'appuyer sur `create_agent`/LangGraph. (correction utilisateur, autorité — prime sur tout.)

### 4.3 Taxonomie Dataiku DSS 14 (apport ChatGPT, structurellement utile)

| Type d'agent DSS | Quand | Logique |
|---|---|---|
| **Simple Visual Agent** | no-code, un agent + outils | configuration visuelle |
| **Structured Visual Agent** | séquence de blocs avec logique déterministe | workflow visuel |
| **Code Agent** | logique agentique entièrement codée et contrôlée en Python | le terrain du lecteur ; reçoit le code env (3.9 ou 3.11) |

Pour déléguer entre agents : le tool **Query an LLM/Agent** (séparation des responsabilités, garder le superviseur « sur les rails » quand il y a trop d'outils, arbitrage coût/perf en ne déléguant que les cas durs). Voir `references/orchestration-multi-agents.md` et `references/dataiku-code-agents.md`.

### 4.4 LangChain `create_agent` vs LangGraph brut vs Dataiku Visual vs Code Agent

| Besoin | Choix | Pourquoi |
|---|---|---|
| Pipeline linéaire : prompt → modèle → parse ; RAG retrieve-then-generate une fois | **LCEL** (`a \| b \| c`) | déclaratif ; streaming/async/batch/parallélisme gratuits ; pas de boucle/branche |
| Agent : le modèle choisit ses outils, itère vers une réponse | **`create_agent`** (3.11) | harness ReAct standard sur LangGraph ; middleware, structured output, mémoire, HITL inclus |
| Branches déterministes, boucles explicites, subgraphs, interruptions checkpointées, multi-agent, long-running | **LangGraph brut** (3.11) | contrôle impératif de l'automate, cycles, conditional edges, exécution durable |
| No-code / séquence de blocs gouvernée | **Dataiku Visual** (Simple/Structured) | rapidité, gouvernance, pas de Python |
| Logique agentique sur mesure, contrôle total, **contexte 3.9** | **Dataiku Code Agent** + appels LLM-Mesh natifs | seul chemin viable en 3.9 ; en 3.11, peut héberger `create_agent`/LangGraph |

> ⚠️ **Déprécié — ne pas copier des vieux tutos.** `create_react_agent` (de `langgraph.prebuilt`) est **déprécié** en LangGraph v1 → utiliser `langchain.agents.create_agent`. `AgentExecutor` / `initialize_agent` vivent dans **`langchain-classic`** (maintenu jusqu'à décembre 2026). Le kwarg `prompt=` est devenu `system_prompt=`. (src : https://docs.langchain.com/oss/python/migrate/langchain-v1 ; voir `references/anti-patterns-deprecations-versions.md`.)

### 4.5 L'écosystème — quel framework par stack

Tous transfèrent leurs **patterns** à un Code Agent DSS, mais peu sont drop-in (ils amènent leur propre client LLM et leur boucle). Deux camps philosophiques : **autonomie-first** (« laisse le modèle conduire » : OpenAI Agents SDK, Claude Agent SDK, CrewAI crews, smolagents, AutoGen/AG2) vs **contrôle-first** (« tu dessines le graphe » : LangGraph, MS Agent Framework workflows, Google ADK workflow agents, CrewAI Flows, LlamaIndex Workflows). « AutoGen treats work as a conversation, CrewAI mirrors a human team, LangGraph enforces a state machine, and OpenAI's SDK keeps orchestration intentionally lightweight. » (src : https://galileo.ai/blog/autogen-vs-crewai-vs-langgraph-vs-openai-agents-framework)

| Framework | Abstraction | Pick quand… | Recency (juin 2026) |
|---|---|---|---|
| **LangChain `create_agent` / LangGraph** | StateGraph + nodes/edges ; harness ReAct | contrôle max, durabilité, multi-agent ; neutralité vendeur | v1.x ; `langchain-core` 1.4.7 |
| **OpenAI Agents SDK** | `Agent` + `Runner` ; handoffs + agents-as-tools | stack OpenAI, moindre boilerplate, tracing best-in-class | v0.17.x ; Swarm déprécié (src : https://github.com/openai/openai-agents-python) |
| **Claude Agent SDK** | `query()` / `ClaudeSDKClient` ; subagents + hooks | coding / filesystem / shell / DevOps ; même boucle que Claude Code | renommé ex-« Claude Code SDK » ; **Python 3.10+** ; crédit Agent SDK séparé dès 2026-06-15 (src : https://platform.claude.com/docs — l'ancien `docs.anthropic.com` redirige 301) |
| **Pydantic AI** | `Agent[Deps, Output]` | « LLM comme fonction typée » : extraction / classification / routing ; structured output best-in-class + DI | neutre, mature (src : https://github.com/pydantic/pydantic-ai) |
| **CrewAI** | Agent(role/goal/backstory) + Crew + Flow | workflow façonné comme une équipe humaine ; prototypage rapide | 1.14.3 (24 avr. 2026) ; Python 3.10–3.13 (src : https://en.wikipedia.org/wiki/CrewAI) |
| **AutoGen / AG2** | `ConversableAgent` ; group chat | multi-agent conversationnel / débat | AG2 v0.9 (fork actif d'AutoGen 0.2) (src : https://docs.ag2.ai) |
| **MS Agent Framework** | `ChatAgent` + graph workflows | stack Microsoft/Azure ; orchestration graphe entreprise ; analogue direct de LangGraph | **1.0 GA avril 2026** ; SK + AutoGen en maintenance (src : https://visualstudiomagazine.com/articles/2026/04/06/...) |
| **Google ADK** | `LlmAgent` + Sequential/Parallel/Loop + graphs | stack Google Cloud / Gemini / Vertex ; A2A ; Cloud Run | **2.0 GA** ; Python 3.10+ (src : https://google.github.io/adk-docs/) |
| **LlamaIndex** | `FunctionAgent` + `AgentWorkflow` / Workflows | agent RAG-heavy / document-centrique | mature (src : https://developers.llamaindex.ai) |
| **smolagents** | `CodeAgent` / `ToolCallingAgent` | minimal, code-as-action, modèles ouverts/locaux | tiny, actif ; sandbox e2b/docker (src : https://huggingface.co/docs/smolagents) |
| **Haystack** | `Agent` component + Pipelines | pipelines RAG-first de production | mature ; Haystack Enterprise (août 2025) (src : https://github.com/deepset-ai/haystack) |

**Choix par stack (raccourci).** OpenAI → OpenAI Agents SDK ; Azure/.NET → MS Agent Framework ; Google Cloud/Gemini → ADK ; Anthropic + coding → Claude Agent SDK ; agent = fonction typée → Pydantic AI ; RAG/documents → LlamaIndex (ou Haystack) ; code-as-action / modèles locaux → smolagents ; **contrôle max + durabilité, neutre, et terrain Dataiku → LangGraph/LangChain**.

> ⚠️ **Churn de renommage / fork** — vérifier la lignée d'un tuto avant de copier : « AutoGen » (0.2 vs MS 0.4 vs AG2) ; « Claude Code SDK » → « Claude Agent SDK » ; « Semantic Kernel / AutoGen » → « Microsoft Agent Framework ». (src : https://learn.microsoft.com/en-us/agent-framework/overview/)

---

## 5. Bonnes pratiques transverses (tout framework, y compris Code Agent DSS)

- **Monte l'échelle lentement** (§2) : un appel → workflow → agent ; justifie chaque barreau par une éval.
- **Le LLM émet du structuré, du code déterministe valide et exécute** (12-factor 1/4). Le plus gros gain de fiabilité ; c'est le « templates not LLM for SQL » d'OWIsMind. Privilégie `with_structured_output` / `response_format` (LangChain) ou Pydantic `output_type` au parsing de prose.
- **Possède prompts, contexte et control flow** (12-factor 2/3/8) : prompts versionnés, contexte assemblé explicitement, boucle écrite à la main quand la fiabilité compte.
- **Investis dans l'ACI (agent-computer interface)** : schémas d'outils, descriptions, defaults, messages d'erreur = surface produit. Test décisif : *« si un ingénieur humain ne peut pas dire quel outil utiliser, l'agent non plus »* → pas d'outils flous/redondants. (src : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- **Contexte = budget fini** : tokens minimaux à haut signal, prompt système à la « bonne altitude », few-shots canoniques, vide les vieux résultats d'outils ; pour le long-horizon : compaction + note-taking + sous-agents.
- **Handoff vs agents-as-tools est un vrai choix** : handoff = le contrôle *transfère* (un agent à la fois) ; agents-as-tools = sous-agent *appelé comme une fonction*, le contrôle revient à l'orchestrateur. Pour un système auditable, agents-as-tools (un seul orchestrateur responsable) est le défaut plus sûr.
- **Whitelist + résolution côté serveur** : le front envoie une clé logique, le backend résout l'`agent_id` (12-factor + sécurité ACI ; règle OWIsMind).
- **Anti-« règles par bug »** : jamais de valeur métier en dur dans la logique d'un agent → compréhension LLM contrainte (liste de candidats) ou refus honnête (règle P3 OWIsMind).
- **Guardrails + sandbox + cap d'itérations + tracing** partout où il y a autonomie ; verification loops pour les tâches longues (run tests / ground truth avant de marquer une étape « done »).

---

## 6. Mapping OWIsMind / Dataiku (base du lecteur)

Les patterns ci-dessus sous-tendent déjà le design du repo :

- **LLM augmenté (§1)** = Code Agent DSS + LLM Mesh + agent tools (semantic-model-query `v4oqA6R`, resolver) + SQL via `SQLExecutor2`.
- **Routing / orchestrator-workers (§3.1)** = l'orchestrateur « Expert Authority » routant par **domaine métier** vers des Code Agents spécialisés, avec fan-out parallèle.
- **Evaluator-optimizer / verification (§3.1)** = l'étape RENDER qui **vérifie les chiffres ligne par ligne** contre les rows capturées avant de répondre.
- **12-factor « LLM émet du structuré, code exécute »** = pipeline UNDERSTAND (JSON) → RESOLVE → COMPOSE (templates gelés) → QUERY → RENDER ; le **SQL appartient au semantic model** (tool mode-Agent) ; le LLM n'émet jamais un fait métier.
- ⚠️ **Réalité version (§4.2)** : le backend est en **Python 3.9.23** → LangChain/LangGraph v1 (3.10+) ne s'importent pas in-process. Utiliser les patterns conceptuellement, les implémenter en appels LLM-Mesh natifs + Python déterministe. Un Code Agent en code env **3.11** peut, lui, importer langchain.

---

## 7. Pièges / anti-patterns (résumé décisionnel)

- Construire un **agent quand un workflow (ou un seul appel) suffirait** — paye latence + coût + risque pour rien.
- Laisser un framework **cacher control flow / contexte / prompts** — perte de debuggabilité.
- **Outils flous/redondants** — choix d'outil ambigu (échoue au test « l'humain non plus »).
- **Tout balancer dans la fenêtre** (« la grosse fenêtre suffit ») — le context rot dégrade rappel et raisonnement.
- Prompts système **sur-spécifiés** (if/else codé en dur) **ou** vagues — manquer la « bonne altitude ».
- **Fan-out multi-agent réflexe** — ~15× les tokens ; réserver au haut-valeur parallélisable.
- **Confondre `with_structured_output` (modèle) et `response_format` (agent)** ; oublier `tool_call_id` sur un `ToolMessage` ; traiter des ids de modèle d'exemple comme réels.
- **Importer langchain en contexte 3.9** (interdit ici).

> Anti-patterns et dépréciations détaillés (incl. `create_react_agent`, `AgentExecutor`, `message.text()` devenu propriété, `then=` retiré de `add_conditional_edges`) : `references/anti-patterns-deprecations-versions.md`.

---

## 8. Notes de version qui mordent ici (juin 2026)

- **`create_react_agent` déprécié** (LangGraph v1) → `langchain.agents.create_agent`. `AgentExecutor`/`initialize_agent` → `langchain-classic` (maintenu jusqu'à déc. 2026).
- **`recursion_limit` par défaut = 25** (pas 1000). Le relever par invocation : `config={"recursion_limit": N}`. (src : https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT)
- **`astream_events` : version par défaut = `v2`** ; `v3` est opt-in/expérimental et exige LangChain ≥ 1.3. (src : https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/astream_events · https://docs.langchain.com/oss/python/langgraph/streaming)
- **Durabilité LangGraph : défaut `"async"`** ; passer `durability=` explicitement dans les exemples qui en dépendent. (src : https://docs.langchain.com/oss/python/langgraph/durable-execution)
- **`add_conditional_edges` n'a PAS de `then=`** ; signature `(source, path, path_map=None)`. (src : https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges)
- **Ids Anthropic réels et courants** : `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5` (à utiliser tels quels, sans suffixe de date sauf Haiku). **`gpt-5.5` et `gemini-3.5-flash` = NON VÉRIFIÉS** (non-Anthropic) — à confirmer côté OpenAI/Google avant tout usage en prod.
- **`docs.anthropic.com` redirige 301 → `platform.claude.com/docs`.**
- **Dataiku** : Local MCP 14.2.0 · Semantic Models 14.4.0 · extraction structurée de champs 14.5.0. La surface scriptable `project.get_semantic_model(...)` + `get_raw()`/`save()`/`versions` est **NON VÉRIFIÉE** dans la doc publique (project-interne) — confirmer au runtime, ne pas la citer comme documentée.

---

## Sources principales

- Anthropic — *Building Effective Agents* : https://www.anthropic.com/research/building-effective-agents
- Anthropic — *Effective Context Engineering for AI Agents* : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- HumanLayer — *12-Factor Agents* : https://github.com/humanlayer/12-factor-agents
- OpenAI — *A Practical Guide to Building Agents* : https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- LangChain v1 — overview / agents / migration : https://docs.langchain.com/oss/python/langchain/overview · https://docs.langchain.com/oss/python/langchain/agents · https://docs.langchain.com/oss/python/migrate/langchain-v1
- LangChain & LangGraph 1.0 : https://www.langchain.com/blog/langchain-langgraph-1dot0
- LangGraph vs LangChain (quand descendre) : https://www.spheron.network/blog/langgraph-vs-langchain/ · https://www.clickittech.com/ai/langchain-1-0-vs-langgraph-1-0/
- Comparatif frameworks : https://galileo.ai/blog/autogen-vs-crewai-vs-langgraph-vs-openai-agents-framework · https://composio.dev/content/openai-agents-sdk-vs-langgraph-vs-autogen-vs-crewai
- MS Agent Framework (« write a function instead ») : https://learn.microsoft.com/en-us/agent-framework/overview/
- OpenAI Agents SDK : https://github.com/openai/openai-agents-python · Claude Agent SDK : https://platform.claude.com/docs · Pydantic AI : https://github.com/pydantic/pydantic-ai · CrewAI : https://docs.crewai.com/en/concepts/flows · ADK : https://google.github.io/adk-docs/ · LlamaIndex : https://developers.llamaindex.ai · smolagents : https://huggingface.co/docs/smolagents · Haystack : https://github.com/deepset-ai/haystack
- Recency/versions (autoritatif) : `docs/agentic-research/gap-version-recency-recheck-2026.md`
