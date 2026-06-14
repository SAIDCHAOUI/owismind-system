# Orchestration & multi-agents (superviseur, sous-agents, handoffs, hiérarchie, swarm)

> À jour : juin 2026 — LangChain 1.x / LangGraph 1.x, Dataiku DSS 14.x. Fichier de référence du skill `agentique-python-dataiku` (parent : `SKILL.md`). Pour les fondations LangGraph (state/nodes/edges, persistence, streaming) : voir `references/langgraph-v1.md` ; pour `create_agent`, middleware, structured output : `references/langchain-v1.md` ; pour LLM Mesh, tools managés, gouvernance : `references/dataiku-code-agents.md`.

---

## 0. Décider AVANT de coder : mono- vs multi-agent

Règle n°1, partagée par LangChain, Anthropic et OpenAI : **partir d'un seul agent** ; n'introduire le multi-agent que sur preuve. Un agent unique gagne en qualité ET en latence tant qu'il n'y a **qu'au plus un domaine distracteur** ; au-delà de 2 domaines distracteurs il décroche brutalement et ses tokens grimpent avec chaque domaine ajouté (https://www.langchain.com/blog/benchmarking-multi-agent-architectures). Verdict benchmark le plus contre-intuitif : **les plus gros gains multi-agent venaient du context engineering** (supprimer les messages de handoff, transmettre la réponse finale au lieu de la paraphraser), **pas de la topologie** (même source).

Passer multi-agent quand, et seulement quand (https://docs.langchain.com/oss/python/langchain/multi-agent) :

| Déclencheur | Pourquoi |
|---|---|
| Trop d'outils → routage médiocre | scinder par domaine restaure la précision de sélection |
| Pression sur la fenêtre de contexte | isoler le savoir spécialisé par agent (quarantaine) |
| Développement distribué | des équipes possèdent des agents indépendants |
| Parallélisme réel | lancer des workers concurrents sur sous-tâches indépendantes |
| Contraintes séquentielles / gating | débloquer des capacités après conditions (machine à états par handoff) |

> Avant même d'ajouter un agent : le pattern **Skills** (un seul agent qui charge prompt/connaissance spécialisés à la demande) est le moins cher pour du mono-domaine répété (~15K tokens vs ~9K pour subagents/router sur une tâche 3 domaines) (https://docs.langchain.com/oss/python/langchain/multi-agent). Coût Anthropic du réflexe inverse : un système de recherche multi-agent peut brûler **~15× les tokens** d'un chat simple — réservé au travail à forte valeur et parallélisable (https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).

Corpus et source ChatGPT s'accordent : démarrer simple, descendre en complexité par paliers (single call → workflow → agent → multi-agent), et chaque palier doit se justifier par une éval.

---

## 1. Deux taxonomies coexistantes (les mapper)

Les deux modèles mentaux vivent côte à côte ; ne pas en privilégier un seul.

**Ancienne taxonomie LangGraph « concepts »** (meilleure carte de l'*espace de conception*) : Single · Network (pair-à-pair) · Supervisor (orchestrateur-workers) · Supervisor-as-tools (subagents) · Hierarchical · Custom.

**Nouvelle taxonomie LangChain v1** (cadrage *recommandé pour l'implémentation*, https://docs.langchain.com/oss/python/langchain/multi-agent) :

| Pattern v1 | Usage principal | ≈ ancienne taxonomie |
|---|---|---|
| **Subagents** | l'agent principal coordonne des spécialistes *exposés comme outils* ; tout le routage passe par lui | Supervisor-as-tools |
| **Handoffs** | comportement dynamique selon l'état ; transfert de contrôle par tool call (`Command`) | Network / Swarm + reconfig mono-agent |
| **Skills** | un seul agent charge prompts/savoir à la demande (pas d'agent supplémentaire) | alternative mono-agent |
| **Router** | une étape de classification dirige vers un spécialiste, puis synthèse | superviseur fin |
| **Custom** | `StateGraph` sur mesure mêlant edges déterministes et routage agentique | Custom |

Mapping Anthropic : **orchestrator-workers** = supervisor ; **routing workflow** = Router ; **parallelization** (sectioning/voting) = fan-out de subagents.

**Idée centrale, plus chargée que la topologie : le context engineering.** *« Au cœur du design multi-agent : décider ce que chaque agent voit. »* Le choix de pattern est surtout un choix de *contexte par agent*, arbitré contre latence, coût en tokens et parallélisme (https://docs.langchain.com/oss/python/langchain/multi-agent).

---

## 2. Le primitif de handoff : `Command`

`Command` est l'objet qu'un **node ou un tool** retourne pour **mettre à jour le state ET choisir le prochain node** en une seule étape — il remplace les edges explicites et rend naturels les graphes « sans arêtes » / dynamiques (https://www.langchain.com/blog/command-a-new-tool-for-multi-agent-architectures-in-langgraph).

```python
from langgraph.types import Command
from typing import Literal

def agent(state: MessagesState) -> Command[Literal["other_agent", "__end__"]]:
    ...
    return Command(
        goto="other_agent",                # node(s) cible
        update={"messages": [response]},   # mise à jour du state
    )
```

**`Command` vs edge conditionnel** : un edge conditionnel (`add_conditional_edges`) quand un node *route seulement* sans toucher au state ; `Command` quand il faut *router ET mettre à jour* dans la même étape (le cas du handoff). ⚠️ Signature à jour : `add_conditional_edges(source, path, path_map=None)` — **pas de paramètre `then=`** (https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges).

**Franchir une frontière de subgraph : `graph=Command.PARENT`.** Quand chaque agent est lui-même un subgraph compilé ajouté comme node, un tool *interne* qui veut sauter vers un agent *frère* doit router dans le graphe parent. `Command.PARENT` est le seul saut supporté ; le multi-niveaux se compose en ré-émettant `Command.PARENT` à chaque palier.

```python
return Command(goto="sales_agent", update={...}, graph=Command.PARENT)
```

**Règle non négociable : garder l'historique de conversation valide.** Quand le LLM appelle un tool de handoff, il attend une réponse tool correspondante. Inclure dans l'`update` **l'`AIMessage` qui contient le tool call ET un `ToolMessage` avec le bon `tool_call_id`**, sinon l'agent receveur reçoit un historique malformé et le modèle peut erreur (https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs) :

```python
from langchain.tools import tool
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command
from langchain.agents import ToolRuntime          # injection runtime v1

@tool
def transfer_to_sales(runtime: ToolRuntime) -> Command:
    """Transfer to the sales agent."""
    last_ai = next(m for m in reversed(runtime.state["messages"])
                   if isinstance(m, AIMessage))
    ack = ToolMessage(content="Transferred to sales agent",
                      tool_call_id=runtime.tool_call_id)
    return Command(
        goto="sales_agent",
        update={"active_agent": "sales_agent",
                "messages": [last_ai, ack]},        # paire AIMessage + ToolMessage
        graph=Command.PARENT,
    )
```

**Handoff = reconfiguration sur place (mono-agent, sans second agent).** Un tool peut basculer une variable d'état (`current_step`) qu'un **middleware** lit pour échanger system prompt + jeu d'outils au tour suivant — un seul agent qui se comporte en machine à états (https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs). Pattern portable hors de toute lib de handoff (voir `references/langchain-v1.md` pour `wrap_model_call` / `request.override(...)`).

---

## 3. Pattern A — Subagents / « agents-as-tools » (DÉFAUT recommandé)

L'agent principal appelle chaque sous-agent **comme un tool** : il décide qui invoquer, avec quelle entrée, et comment combiner les résultats. Les sous-agents sont **stateless** (la conversation est tenue par le principal) → chaque invocation a une **fenêtre de contexte propre**. Le principal peut invoquer **plusieurs sous-agents dans un même tour** (parallélisme) (https://docs.langchain.com/oss/python/langchain/multi-agent/subagents).

```python
from langchain.tools import tool
from langchain.agents import create_agent          # v1 : remplace create_react_agent

subagent = create_agent(model="anthropic:claude-haiku-4-5", tools=[...])

@tool("research", description="Research a topic and return findings")
def call_research_agent(query: str) -> str:
    result = subagent.invoke({"messages": [{"role": "user", "content": query}]})
    return result["messages"][-1].content           # renvoyer une réponse PROPRE et concise

main_agent = create_agent(model="anthropic:claude-sonnet-4-6", tools=[call_research_agent])
```

Choix de design (https://docs.langchain.com/oss/python/langchain/multi-agent/subagents) :
- **Un tool par agent** → descriptions fines, contrôle par agent. **Un tool de dispatch paramétré** (« task » qui choisit l'agent) → meilleure montée en charge pour beaucoup d'équipes, moins de contrôle unitaire.
- **Contexte de routage** : le principal route *uniquement* sur les **noms + descriptions** des tools-agents. Noms orientés action (`research_agent`, `code_reviewer`), descriptions « quand m'appeler ». Pour beaucoup d'agents / agents dynamiques : un tool `list_agents` (divulgation progressive) plutôt que tout empiler dans le prompt.
- **Sync vs async** : tool synchrone = bloque jusqu'à la fin, défaut quand le principal a besoin du résultat pour continuer ; pour les jobs longs/indépendants, pattern async à 3 tools (start → check status → fetch result). Corpus et ChatGPT concordent.

**Pourquoi recommandé** : isolation de contexte propre, parallélisme facile, zéro câblage d'edges, et c'est « le plus générique » — fonctionne même avec des agents tiers/opaques (https://www.langchain.com/blog/benchmarking-multi-agent-architectures). **Quarantaine de contexte** (terme Deep Agents, équivalent ChatGPT/Anthropic) : on délègue le travail lourd dans une fenêtre isolée, on ne remonte qu'un **résumé synthétique** (~1 000–2 000 tokens), jamais la trace brute (https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents). **Deep Agents** (`deepagents`) est le harness clé-en-main au-dessus de `create_agent` qui bundle ce pattern (filesystem, subagents, planning, gestion de contexte) (https://github.com/langchain-ai/deepagents).

---

## 4. Pattern B — Supervisor (`langgraph-supervisor`)

Un superviseur LLM délègue à une liste de workers via des **tools de handoff auto-générés** ; les workers rendent le contrôle au superviseur, qui possède la réponse finale. `create_supervisor()` renvoie un `StateGraph` à `.compile()`.

> LangChain **recommande désormais de faire le supervisor via le Pattern A (subagents-as-tools)** pour la plupart des cas (https://pypi.org/project/langgraph-supervisor/). Utiliser cette lib quand on veut la plomberie handoff/forwarding/hiérarchie prête à l'emploi. ⚠️ **Version skew** : `langgraph-supervisor` ≤ 0.0.29 épingle `langgraph<0.7` et **casse sur langgraph ≥ 1.0** → exiger **≥ 0.0.31** (Python ≥ 3.10) (https://github.com/langchain-ai/langgraph-supervisor-py/releases).

```python
from langgraph_supervisor import create_supervisor
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

model = init_chat_model("anthropic:claude-sonnet-4-6")

research_agent = create_agent(model, tools=[web_search], name="research_agent",
                             system_prompt="You are a world-class researcher.")
math_agent = create_agent(model, tools=[add, multiply], name="math_agent",
                          system_prompt="You are a math expert.")

workflow = create_supervisor(
    [research_agent, math_agent], model=model,
    prompt="You manage a research agent and a math agent. Delegate appropriately.",
)
app = workflow.compile()
```

⚠️ Chaque worker DOIT recevoir un `name=` — les tools de handoff et l'attribution des messages en dépendent. `include_agent_name="inline"` injecte les noms en balises XML pour une attribution fiable.

Paramètres clés de `create_supervisor` (v0.0.31, https://reference.langchain.com/python/langgraph-supervisor/supervisor/create_supervisor) :

| Paramètre | Effet |
|---|---|
| `agents` | `CompiledStateGraph` / workflow functional-API / tout `Pregel` |
| `output_mode` | `"last_message"` (défaut : seule la réponse finale de chaque worker) vs `"full_history"` (tout) |
| `add_handoff_messages` | enregistrer ou non les paires AIMessage/ToolMessage au handoff. **Les supprimer (`False`) a amélioré la précision du superviseur ~50 %** en benchmark |
| `add_handoff_back_messages` | idem au retour vers le superviseur |
| `parallel_tool_calls` | déléguer à plusieurs agents d'un coup (OpenAI/Anthropic) |
| `pre_model_hook` / `post_model_hook` | nodes avant/après LLM : HITL, guardrails, trim d'historique, validation |
| `response_format` | sortie finale structurée (surfacée dans la clé `structured_response`) |
| `handoff_tool_prefix` | ex. `"delegate_to_"` ; `supervisor_name` (défaut `"supervisor"`) |

**Tuer le « jeu du téléphone ».** Plutôt que de laisser le superviseur paraphraser (ce qui dégrade la précision), lui donner un tool qui transmet la réponse du worker **verbatim** :

```python
from langgraph_supervisor.handoff import create_forward_message_tool
forwarding_tool = create_forward_message_tool("supervisor")   # arg from_agent
workflow = create_supervisor([research_agent, math_agent], model=model,
                             tools=[forwarding_tool])
```

**Mémoire** : `checkpointer=` (court terme / thread) + `store=` (long terme) au `.compile()`. Voir `references/langgraph-v1.md` pour `PostgresSaver` (`.setup()` requis ; `from_conn_string(conn_string, *, pipeline=False)`).

---

## 5. Pattern C — Hierarchical (superviseurs de superviseurs)

Quand un superviseur a trop de workers : grouper en équipes, chacune avec son superviseur, sous un superviseur top-level. Comme `create_supervisor(...).compile()` renvoie un graphe compilé, **un superviseur compilé est lui-même un « agent » valide** à passer à un superviseur supérieur (https://github.com/langchain-ai/langgraph-supervisor-py/blob/main/README.md).

```python
research_team = create_supervisor([search_agent, scraper_agent], model=model,
    supervisor_name="research_supervisor").compile(name="research_team")
writing_team = create_supervisor([writer_agent, editor_agent], model=model,
    supervisor_name="writing_supervisor").compile(name="writing_team")

top = create_supervisor([research_team, writing_team], model=model,
    supervisor_name="top_level_supervisor").compile(name="top_level_supervisor")
```

À utiliser pour le **développement distribué** (chaque équipe possédée par une sous-équipe) et pour garder petite la décision de routage de chaque superviseur. Coût : plus de hops de « traduction » et de latence.

---

## 6. Pattern D — Swarm / Network (`langgraph-swarm`)

Pair-à-pair : les agents se passent le contrôle **directement** via `Command` — **sans retour par un superviseur**. Exactement un agent « actif » à la fois ; le swarm **mémorise le dernier agent actif** pour reprendre au tour suivant avec lui (https://github.com/langchain-ai/langgraph-swarm-py/blob/main/README.md). `langgraph-swarm` 0.1.0 (déc. 2025, Python ≥ 3.10).

```python
from langgraph.checkpoint.memory import InMemorySaver
from langchain.agents import create_agent
from langgraph_swarm import create_handoff_tool, create_swarm
from langchain.chat_models import init_chat_model

model = init_chat_model("anthropic:claude-sonnet-4-6")
alice = create_agent(model, tools=[create_handoff_tool(agent_name="Bob", description="Transfer to Bob")],
                     system_prompt="You are Alice, an addition expert.", name="Alice")
bob = create_agent(model, tools=[create_handoff_tool(agent_name="Alice", description="Transfer to Alice")],
                   system_prompt="You are Bob, you speak like a pirate.", name="Bob")

workflow = create_swarm([alice, bob], default_active_agent="Alice")
app = workflow.compile(checkpointer=InMemorySaver())     # checkpointer CRUCIAL
```

> ⚠️ Un checkpointer est **indispensable** pour un swarm : sans mémoire court-terme, il oublie l'agent actif entre les tours et « reset » au défaut.

Signatures (v0.1.0) : `create_swarm(agents, *, default_active_agent, state_schema=SwarmState, context_schema=None)` ; `SwarmState(MessagesState)` ajoute `active_agent: str | None`. Le `create_handoff_tool` swarm renvoie un `Command(goto=agent_name, graph=Command.PARENT, update={"messages": ... + [tool_message], "active_agent": agent_name})`. **Toute clé de `Command.update` doit exister dans le state schema du swarm**, sinon elle est silencieusement perdue / erreur.

Benchmark : superviseur et swarm restent **plats en tokens** quand les domaines croissent ; le **swarm consomme moins de tokens** et **dépasse marginalement** le superviseur ; mais le **superviseur est « le plus générique »** (moins d'hypothèses sur les workers) → choix sûr quand les workers sont hétérogènes ou externes (https://www.langchain.com/blog/benchmarking-multi-agent-architectures).

---

## 7. Subgraphs — le substrat de composition

Un système multi-agent est un subgraph-de-subgraphs. Deux modes d'intégration (https://docs.langchain.com/oss/python/langgraph/use-subgraphs) :

- **Schéma de state partagé** → ajouter le subgraph compilé **directement comme node** ; le state passe tel quel et fusionne via les reducers (canal `messages` commun).
- **Schémas différents (historiques isolés / fenêtre propre)** → invoquer dans un **node wrapper** qui transforme parent→enfant à l'entrée et enfant→parent à la sortie. Ajouter un subgraph à schéma différent directement comme node **lève une erreur** (pas de clé partagée).

```python
def call_subgraph(state: State):
    out = subgraph.invoke({"bar": state["foo"]})   # parent -> enfant
    return {"foo": out["bar"]}                      # enfant -> parent
```

Persistance du subgraph (au `.compile()`) : par-invocation (défaut, state frais à chaque appel) / par-thread (`checkpointer=True`, accumule) / stateless (`checkpointer=False`). Le parent doit compiler avec un checkpointer pour les fonctions de persistance ; per-thread + parallel tool calls → conflits, gater avec `ToolCallLimitMiddleware`.

---

## 8. Async vs sync delegation & garde-fous de boucle

- **Sync** : défaut quand le superviseur a besoin du résultat pour continuer (la chaîne est sérielle). **Async** : tâches indépendantes longues — fan-out parallèle (subagents multiples, ou `parallel_tool_calls=True` sur OpenAI/Anthropic), ou pattern async 3-tools.
- **`recursion_limit` par défaut = 25** (PAS 1000). Le dépassement lève `GraphRecursionError`. Le relever **par invocation**, pas en changeant un défaut : `graph.invoke(inputs, config={"recursion_limit": 100})` (https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT). Les sous-agents héritent silencieusement de 25 — penser à le passer aux subgraphs.
- **`durability` par défaut = `"async"`** (persistance asynchrone pendant l'étape suivante). Passer `durability=` explicitement dans tout exemple où ça compte (`"exit"` le plus rapide / `"sync"` le plus durable).
- **`astream_events` : version par défaut = `v2`** ; `v3` est opt-in/expérimental et exige LangChain ≥ 1.3 (le content-block protocol). Épingler `version="v2"` sauf besoin explicite du v3.
- ⚠️ **API périmée** : `create_react_agent` (de `langgraph.prebuilt`) est **DÉPRÉCIÉ** en LangGraph v1 → utiliser `langchain.agents.create_agent`. `AgentExecutor` / `initialize_agent` vivent dans `langchain-classic` (maintenu jusqu'à déc. 2026).

---

## 9. Dataiku : « Query an LLM/Agent », workflow séquentiel, Agent Hub

Correspondance plateforme du supervisor pattern (source ChatGPT, taxonomie Dataiku ; détail API dans `references/dataiku-code-agents.md`) :

- **Tool « Query an LLM/Agent »** : permet à un agent principal de **déléguer à un autre agent ou LLM**. Trois bénéfices documentés : séparation des responsabilités, garder le superviseur « sur les rails » quand il a trop d'outils, et arbitrage coût/performance (ne déléguer que les cas difficiles à un modèle plus puissant) — l'exact analogue du routing/cost-tiering.
- Chaque agent Dataiku devient un **« Virtual LLM » dans le LLM Mesh** → réutilisable partout où le Mesh est exposé, avec audit/sécurité/guardrails. L'agent n'est pas qu'un bout de code : c'est un objet gouverné.
- **Workflow multi-agents séquentiel** (tutoriel officiel Dataiku) = chaînage d'agents façon prompt-chaining.
- **Agent Hub** : orchestrer plusieurs agents dans une même interface de chat. **External Agents** : raccorder des agents Databricks/Bedrock/Vertex AI comme agents managés gouvernés. Publication d'agents Dataiku comme **MCP Tools**.
- Taxonomie d'agents DSS 14 : **Simple Visual** (no-code) · **Structured Visual** (séquences de blocs déterministes) · **Code Agents** (logique agentique 100 % Python).

> ⚠️ **Python dual-path (fait dur, à rappeler partout).** L'instance dispose de **deux** code envs : **3.9 ET 3.11**.
> - LangChain/LangGraph v1 exigent **Python ≥ 3.10** → utilisables **uniquement dans un code env 3.11**. Un Code Agent assigné à un env 3.11 PEUT importer `langchain`/`langgraph` (et donc `create_agent`, supervisor/swarm, subgraphs).
> - Le **backend webapp OWIsMind tourne en 3.9.23** → en tout contexte 3.9 : **stdlib + `dataiku` uniquement, AUCUN import langchain**. Orchestrer en appelant LLM Mesh / agents / tools via les **APIs Dataiku natives** : `project.get_llm(agent_id).new_completion()` (déléguer à un agent), `project.get_agent_tool(id).run({...})` (appeler un tool managé), `SQLExecutor2` (SQL). **Ne JAMAIS recommander d'importer langchain dans un contexte 3.9.** Présenter les deux chemins quand la version compte.

---

## 10. La référence DSS qui tourne en prod : l'orchestrateur « Expert Authority »

C'est l'implémentation 3.9-native, validée DSS, qui matérialise le supervisor/router en restant sans langchain. Toutes les références `file:line` ci-dessous renvoient au repo OWIsMind (corpus `owismind-project-patterns.md`).

### 10.1 Le pare-feu d'honnêteté & routage

**Bug central corrigé** (confirmé sur 817 questions réelles, ~10 plaintes identiques) : l'orchestrateur **niait/inventait au lieu de router** — « budget 2026 pour le Roaming Hub » → « je n'ai pas de données budget » *sans jamais appeler l'agent revenus*, alors que le sous-agent lit une colonne `Phase` dont les valeurs incluent `BUDGET`. Cause racine : les règles interdisaient le *sur*-promesse mais rien n'interdisait le *sous*-promesse (inventer une limite inexistante).

Le pare-feu (architectural, pas seulement prompt — `orchestrator_agent.py:55-63, 665-674`) :

- **L'orchestrateur n'émet JAMAIS un fait métier.** Le seul « non » qu'il peut écrire = **« je n'ai pas d'agent pour ce DOMAINE »** (`CAPABILITY_GAP`) — *jamais* « la donnée n'existe pas » (cela appartient à l'expert via `out_of_scope`/`no_data`). **Dans le doute → router.**
- `BUSINESS` est le **défaut** pour tout ce qui touche un domaine *qui a* un agent, « MÊME si tu n'es pas sûr que le chiffre précis existe — seul l'agent peut confirmer » (`:622-624`).
- **Intents non-business = templates déterministes, pas de prose libre** (la prose libre était la fuite des faits hallucinés) : `CAPABILITY_GAP` / `OUT_OF_SCOPE` rendus depuis des **templates sourcés du registre** (`render_non_business_text :1010-1019`) ; nouvel intent `CONCEPT` (notions télécom générales, ex. SS7 vs LTE, explicitement « connaissance générale, aucun chiffre OWI » `:628-632`) ; `CLARIFY` borné à « demander seulement ».
- **`BUSINESS_DOMAINS`** (`:356-363`) = carte noms-seulement qui distingue un domaine *réel mais non staffé* (→ CAPABILITY_GAP honnête) d'une question *non-OWI* (→ OUT_OF_SCOPE). Un domaine devient « staffé » automatiquement quand un agent activé le déclare (`staffed_domains :366-369`) — **ajouter un agent referme le gap sans changer un prompt**.
- **Test anti-dérive** : il importe les `KNOWN_PHASES` du sous-agent et échoue si la description du planner re-rétrécit le scope (`test_manifest_antidrift.py:44,59`). L'invariant métier vit dans un **test**, pas dans la logique de l'agent (règle P3).

### 10.2 Registre-as-manifest (whitelist serveur)

Le front n'envoie jamais d'`agent_id` ; il envoie une **clé logique opaque**, le backend résout (CLAUDE.md rule 4). Dans l'orchestrateur, **le registre EST un manifeste** : ajouter un agent = une entrée `{key, agent_id, domain, labels, planner_description, block_labels, tool_labels, ...}` (`CAPABILITIES :172-342`) ; `get_capabilities()` filtre sur `enabled` (point d'extension unique). Tout est registre-driven, jamais LLM-driven : le bloc Sources = labels des datasets des capacités effectivement utilisées, émis **par code** (URLs intranet jamais dans la réponse) ; **une seule capacité revenue `enabled` à la fois** (test enforced). Contrats d'événements gelés (jamais renommer, seulement ajouter) : `START, PLANNING, PLAN_READY, CALLING_AGENT, AGENT_DONE, RUNNING_TOOL, TOOL_DONE, WRITING_ANSWER, DONE, ERROR, SUB_AGENT_*` ; `KNOWN_BLOCK_IDS`/`KNOWN_TOOL_NAMES` du sous-agent DOIVENT égaler `block_labels`/`tool_labels` du registre (test anti-dérive cross-fichiers).

### 10.3 Déléguer à un sous-agent depuis du code 3.9 (le snippet validé)

```python
completion = project.get_llm(cfg["agent_id"]).new_completion()  # agent_id type "agent:AKQaQ0Am"
completion.with_message(context_msg, role="system")            # seulement si cfg["pass_context"] (opt-in)
completion.with_message(step["instruction"])
for chunk in completion.execute_streamed():
    data = getattr(chunk, "data", {}) or {}
    if _is_footer(chunk, data):        # le footer final porte la trace complète
        sub_trace = data.get("trace"); continue
    ctype = data.get("type") or getattr(chunk, "type", None)
    if ctype == "event": ...           # relayer ou capturer l'événement timeline
    elif ctype in ("content", "text"): answer_parts.append(data.get("text", ""))
```

Le **footer** (`data.get("type") == "footer"` ou `isinstance(chunk, DSSLLMStreamedCompletionFooter)`, import **guardé** car les builds SDK diffèrent) est le seul endroit pour récupérer l'**usage** (`usageMetadata`) et les spans **SQL généré**. **`AGENT_RESULT`** est un événement final `{status, intent, sqlCount, rowCount, ...}` (`status ∈ {ready, need_clarification, out_of_scope, no_data, error}`) : l'orchestrateur le **capture, ne le relaie jamais** (statut machine, pas du texte) et s'en sert pour **gater le bloc Sources** (une clarification/out-of-scope ne cite aucun dataset).

### 10.4 Fan-out parallèle (thread-safety DSS)

Pour 2+ steps d'agents, fan-out sur un pool borné (`MAX_PARALLEL_AGENTS = 3`, sûreté instance). Pattern dur :
- **Les threads workers ne touchent JAMAIS la trace, l'usage, ni ne yield.** Un worker streame son sous-agent et pousse des événements affichables dans une `queue.Queue` (`("event", idx, payload)`), finit par `("done", idx, {res, sub_trace})`.
- Le **générateur principal draine la queue et re-yield les événements EN DIRECT** ; chaque event est keyé par `stepIndex` → interleaving sûr.
- **Tous les spans, `append_trace`, accumulation d'usage et tagging SQL se font sur le THREAD PRINCIPAL** après chaque step (`SpanBuilder`/`total_usage` supposés non thread-safe).
- **Les plans multi-steps ne relaient jamais le texte en direct** (le relais est mono-step) ; la réponse finale vient du step de synthèse → les événements entrelacés ne corrompent pas le texte. Une analyse 360 = un step par domaine staffé, wall-clockée au **plus lent**, pas à la somme.

Le mono-step est inchangé : un seul step **relaie sa réponse verbatim (0 coût de synthèse)** ; 2+ steps passent par un LLM de synthèse contraint.

---

## 11. UNDERSTAND → RESOLVE → COMPOSE → QUERY → RENDER (le pattern d'orchestration concret du sous-agent)

C'est le pipeline en 5 étapes partagé par le Dataset Expert générique et les agents revenus (`dataset_expert_agent.py:11-33`). **La répartition du travail EST le pattern** : le LLM fait *seulement* de la linguistique et une phrase vérifiée ; tout ce qui est load-bearing est du Python déterministe. C'est l'opposé d'une boucle tool-calling autonome — « le LLM ne décide plus rien pendant l'exécution » — justifié par l'évidence SOTA (semantic layer + templates ≫ LLM-SQL libre, 98-100 % vs 84-90 %) et par le transport DSS buffé qui récompense des appels peu nombreux et bien formés.

| Étape | Le LLM fait | Le CODE fait (déterministe) |
|---|---|---|
| **UNDERSTAND** | 1 appel strict-JSON : scope, langue, intent, scénarios, période(s), axe de group-by, top-N, **termes** métier bruts | valide/dégrade le JSON contre le **profil** ; ne fait jamais confiance à une valeur inventée. Schéma d'enums **ancré sur le profil** (le modèle ne peut pas émettre un scénario inexistant) |
| **RESOLVE** | rien | ancre chaque terme contre un **value index** par SQL (exact → fuzzy) ; politique d'ambiguïté ; clarification |
| **COMPOSE** | rien | construit le SQL ou la question semantic-tool depuis des **templates gelés** |
| **QUERY** | rien (sauf intent `custom` : SQL gardé) | exécute le SQL / appelle le tool managé ; capture SQL + rows |
| **RENDER** | une **headline**, chaque chiffre vérifié | formate la table et les chiffres par code ; headline de fallback déterministe |

Points d'orchestration transférables :
- **UNDERSTAND** : prompt **généré depuis le profil** (le même code comprend n'importe quel dataset). 2 tentatives : JSON natif (`with_json_output(schema=...)`) puis fallback prompt-only. Dégradations déterministes (intent inconnu → `custom` ; `compare_scenarios` à un seul scénario → préfixer le défaut factuel du profil — généralise « gap vs budget » sans aucun hardcode).
- **RESOLVE = la couche anti-résultat-vide** : un filtre non ancré renvoie 0 ligne en silence. Un **value index** (`{column_name, value, value_norm, occurrences}`) interrogé par SQL mappe « algerie telecom »/« ipl » à la **valeur cellule exacte + sa colonne**. `_norm` (NFKD→ASCII→lower→collapse) est **GELÉE et partagée** entre recette et agent. Politique d'ambiguïté déterministe en 3 étapes (terme qualifié `VALUE (Column)` → préférence valeur-exacte stricte → auto-pick par priorité de colonne du profil).
- **COMPOSE pour le tool semantic (moteur hybride, décision DSS la plus récente)** : **« la QUESTION USER MÈNE »**. Question user verbatim EN TÊTE, puis intent hint (guidance), puis **valeurs exactes groupées par colonne → sémantique `IN` par colonne, jamais `Product = A AND Product = B`** (le bug impossible-AND), règle d'énumération (lister plusieurs items → OR + une ligne par item), scénario/période explicites, note de destination (« retourne une table propre avec alias de colonnes, jamais de prose »). On laisse le **Semantic Model Query tool posséder le SQL** ; le moteur SQL direct code-owned devient un **fallback technique** (`FALLBACK_TO_DIRECT`) — un résultat vide légitime n'est PAS un échec (reste `no_data` honnête).
- **Appel du tool managé directement** (rend la capture Evidence déterministe) : `project.get_agent_tool(id).run({...})` et lecture SQL+rows depuis la **valeur de retour**, pas depuis des clés de trace devinées. Clé d'entrée auto-détectée du descriptor (`question` observé). En mode Agent, extraction = **priorité de clés puis DERNIÈRE occurrence** (la finale, pas le préambule « I'll start by exploring the schema… »).
- **RENDER = frontière de confiance** : table et chiffres formatés par code ; la headline LLM est **rejetée si elle cite un chiffre hors de l'ensemble des chiffres autorisés du résultat**, fallback déterministe sinon. Le modèle n'introduit jamais un chiffre invérifiable.

---

## 12. Best practices (synthèse, sourcée)

1. **Démarrer mono-agent ; scinder sur preuve** (mauvais routage, débordement de contexte, parallélisme réel) (https://docs.langchain.com/oss/python/langchain/multi-agent).
2. **Ingénierie le contexte par agent.** Superviseurs/swarms par défaut en `output_mode="last_message"` ; schémas isolés pour les sous-agents longs ; renvoyer des réponses *propres et concises* depuis les tools-agents, pas des transcripts bruts (quarantaine).
3. **Tuer le jeu du téléphone** : `add_handoff_messages=False` + `create_forward_message_tool` (https://www.langchain.com/blog/benchmarking-multi-agent-architectures).
4. **Toujours la paire AIMessage + ToolMessage** sur un handoff `Command` ; **`graph=Command.PARENT`** pour franchir une frontière de subgraph ; toute clé de `update` doit être dans le schéma.
5. **Nommer chaque agent** (`name=`) ; descriptions de tools « niveau routage » (« quand m'appeler ») ; `list_agents` pour beaucoup d'agents (divulgation progressive).
6. **Mémoire délibérée** : checkpointer = thread ; store = long terme ; un swarm en **a besoin** pour mémoriser l'agent actif.
7. **L'orchestrateur n'émet jamais un fait métier** (Expert Authority) : router, ne pas nier ; refus/out-of-scope = templates déterministes (corpus, divergence assumée vs « router/superviseur qui répond » générique).
8. **Le LLM émet du structuré, le code exécute** (12-factor 1/4/8) : SQL en templates gelés, semantic model possède le SQL, headline vérifiée chiffre par chiffre.
9. **Anti « règles-par-bug » (P3)** : jamais de valeur métier en dur dans la logique ; cas inconnus → compréhension LLM contrainte (liste de candidats) ou refus honnête ; les invariants vivent dans des **tests**.
10. **Liveness par événements, réponse-en-un-bloc** : SSE est mort en DSS (proxy buffé) → polling + timeline riche, pas de streaming de tokens des internals de tool.

---

## 13. Anti-patterns & pièges

- Multi-agent trop tôt (perd en qualité ET latence à 1 domaine) · oublier la paire AIMessage/ToolMessage → historique malformé · omettre `graph=Command.PARENT` aux frontières → routage dans le mauvais graphe · clé d'`update` absente du schéma → silencieusement perdue · subgraph à schéma différent ajouté directement comme node → erreur · `output_mode="full_history"` par réflexe → explosion de tokens + fuite de contexte · swarm sans checkpointer → perd l'agent actif · `langgraph-supervisor` ≤ 0.0.29 sur langgraph ≥ 1.0 → casse · per-thread subgraph + parallel tool calls → conflits (gater `ToolCallLimitMiddleware`) · `create_react_agent` (`langgraph.prebuilt`) → déprécié, utiliser `create_agent`.
- **Versions UNVERIFIED** : `gpt-5.5`, `gemini-3.5-flash` (cités dans certains exemples du corpus) ne sont **pas vérifiés** — confirmer côté OpenAI/Google avant usage. Les ids Anthropic `claude-opus-4-8` / `claude-sonnet-4-6` / `claude-haiku-4-5` sont réels/courants. La surface `project.get_semantic_model(...)` + `get_raw()`/`save()`/`versions` est **non vérifiée dans la doc publique** (project-interne) — confirmer au runtime via `dir(project)`.

---

## 14. Index des sources (primaires)

- LangChain multi-agent (taxonomie, when-to-use, context engineering) : https://docs.langchain.com/oss/python/langchain/multi-agent
- Subagents (agent-as-tools) : https://docs.langchain.com/oss/python/langchain/multi-agent/subagents
- Handoffs (`Command`, `Command.PARENT`, règles d'historique) : https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs
- Subgraphs : https://docs.langchain.com/oss/python/langgraph/use-subgraphs
- `Command` (intro du primitif) : https://www.langchain.com/blog/command-a-new-tool-for-multi-agent-architectures-in-langgraph
- Benchmarking multi-agent : https://www.langchain.com/blog/benchmarking-multi-agent-architectures
- `langgraph-supervisor` : https://github.com/langchain-ai/langgraph-supervisor-py · réf `create_supervisor` : https://reference.langchain.com/python/langgraph-supervisor/supervisor/create_supervisor · PyPI : https://pypi.org/project/langgraph-supervisor/
- `langgraph-swarm` : https://github.com/langchain-ai/langgraph-swarm-py · PyPI : https://pypi.org/project/langgraph-swarm/
- Hierarchical agent teams : https://langchain-ai.github.io/langgraph/tutorials/multi_agent/hierarchical_agent_teams/
- Deep Agents : https://github.com/langchain-ai/deepagents
- `recursion_limit` : https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT · `add_conditional_edges` : https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges
- Anthropic — context engineering (quarantaine, ~15× tokens) : https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents · building effective agents : https://www.anthropic.com/research/building-effective-agents
- OpenAI — Practical Guide to Building Agents : https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- Supervisor vs swarm tradeoffs : https://dev.to/focused_dot_io/multi-agent-orchestration-in-langgraph-supervisor-vs-swarm-tradeoffs-and-architecture-1b7e
- Dataiku DSS 14 release notes (Semantic Models 14.4, Local MCP 14.2) : https://doc.dataiku.com/dss/latest/release_notes/14.html
- DSS BaseLLM custom-LLM (`process_stream`) : https://developer.dataiku.com/latest/tutorials/plugins/agent/generality/index.html
- OWIsMind repo (corpus `owismind-project-patterns.md`) : `dataiku-agents/agents/orchestrator_agent.py`, `dataiku-agents/agents/dataset_expert_agent.py`, `orchestrator/tests/test_manifest_antidrift.py` ; leçons `memory/LESSONS.md` L047/L048/L050/L051/L052.
