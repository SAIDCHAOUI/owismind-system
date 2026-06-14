# LangGraph v1 : StateGraph, state/reducers, Command, Send, subgraphs

> À jour : juin 2026 — LangGraph 1.x, LangChain 1.x, Dataiku DSS 14.x. Pour chaque affirmation sensible à la version, source inline. Fichier de référence du skill `agentique-python-dataiku` ; le `SKILL.md` parent décide *quand* descendre dans LangGraph.

---

## 0. Quand sortir de `create_agent` pour un `StateGraph` brut

`create_agent` (`langchain.agents`, voir `references/langchain-v1.md`) couvre la boucle standard *model → tools → response* avec middleware (HITL, summarization, PII…). On **descend au Graph API bas niveau** dès qu'on a besoin de :

- mélanger étapes **déterministes** et étapes agentiques (pipeline maîtrisé) ;
- un **état explicite** partagé entre nœuds, avec reducers personnalisés ;
- branches / parallélisme / boucles / map-reduce / sauts explicites (`Command`) que la boucle ReAct ne donne pas ;
- subgraphs réutilisables, interruptions, retries, reprise de run.

C'est précisément le cas d'un **Dataiku Code Agent** orchestrateur sur mesure (le pattern OWIsMind). Le corpus et la source ChatGPT concordent : LangChain `create_agent` pour aller vite, LangGraph quand l'orchestration doit être *explicite et stateful* (source : https://www.langchain.com/blog/langchain-langgraph-1dot0).

> `langgraph.prebuilt` (dont `create_react_agent`) est **déprécié** en v1 ; la fonctionnalité a migré vers `langchain.agents.create_agent`. `AgentExecutor` / `initialize_agent` vivent dans `langchain-classic` (maintenance jusqu'à déc. 2026). Ne pas écrire de nouveau code sur ces APIs (source : https://changelog.langchain.com/announcements/langgraph-1-0-is-now-generally-available).

### Double-chemin Python Dataiku (FAIT DUR — à rappeler partout)

L'instance Dataiku a **deux** code environments : **Python 3.9 ET Python 3.11**.

| Contexte | Python | Règle |
|---|---|---|
| **Code Agent** sur un code env **3.11** (≥ 3.10) | 3.11 | PEUT importer `langchain` / `langgraph` v1. Tout ce fichier s'applique. |
| **Backend webapp OWIsMind** | **3.9.23** | **stdlib-only, AUCUN import langchain/langgraph.** Parler au LLM Mesh / agents / tools via les **APIs Dataiku natives** directement. |

LangChain/LangGraph v1 exigent **Python ≥ 3.10** → ils ne tournent **que** dans un code env 3.11. **Ne jamais** recommander d'importer langchain dans un contexte 3.9. Présenter les deux chemins dès que la version Python compte.

---

## 1. Modèle mental

LangGraph modélise un agent/workflow en **graphe dirigé** exécuté par un runtime à passage de messages (style Pregel / BSP) (source : https://docs.langchain.com/oss/python/langgraph/graph-api) :

- **State** — structure typée partagée, fil conducteur unique du run.
- **Nodes** — fonctions Python (sync ou async) qui lisent l'état et renvoient une **mise à jour partielle**. Signature conceptuelle `State -> Partial<State>`. *« Les nodes font le travail. »*
- **Edges** — déclarent la suite. *« Les edges disent quoi faire ensuite. »* Statiques (toujours) ou conditionnels (cible choisie au runtime).
- **Reducers** — fonctions pures `(existing, update) -> merged` ; chaque clé d'état absorbe les updates selon son reducer (écrasement par défaut).
- **Super-steps** — exécution par étapes discrètes : tous les nodes déclenchés à l'étape tournent (potentiellement en parallèle), leurs updates sont réduits, puis l'étape suivante démarre. Halte quand aucun node n'est actif et aucun message en transit.

Invariants : un node ne mute **jamais** l'état en place — il **renvoie** un dict des canaux à mettre à jour ; les reducers doivent être **purs et sans état** ; il faut **`.compile()`** un `StateGraph` (un builder) avant de l'exécuter (source : https://reference.langchain.com/python/langgraph/graph/state/StateGraph).

---

## 2. State : schéma typé

Trois types possibles (source : https://reference.langchain.com/python/langgraph/graph/state/StateGraph) :

| Type | Pour | Note |
|---|---|---|
| `TypedDict` | **recommandé** (rapide, simple) | défaut pratique |
| `@dataclass` | défauts de champs | `field(default_factory=...)` pour les listes |
| Pydantic `BaseModel` | validation récursive | plus lent ; **non supporté par `create_agent`** |

```python
from typing_extensions import TypedDict

class State(TypedDict):
    foo: int
    bar: list[str]
```

Chaque clé du schéma est un **channel** (valeur + reducer optionnel). Quand un node renvoie `{"key": value}`, le runtime appelle le reducer du channel avec `(valeur courante, value)`.

### Input / output / private schemas

Le schéma sert par défaut d'input, output et interne. On peut les séparer (source : https://docs.langchain.com/oss/python/langgraph/graph-api) :

```python
builder = StateGraph(OverallState, input_schema=InputState, output_schema=OutputState)
```

- `input_schema` filtre/valide ce que l'appelant passe à `invoke`/`stream`.
- `output_schema` restreint ce que `invoke()` renvoie.
- Les nodes peuvent quand même écrire **n'importe quel** channel d'`OverallState`.
- Un channel **privé** (dans `OverallState`, absent de `output_schema`) est masqué de `invoke()` mais **reste visible** sous `stream(stream_mode="values")` sauf `output_keys=[...]`. Un node peut déclarer un channel privé par son **type de retour annoté**.

---

## 3. Reducers (le cœur de la fusion d'état)

Signature `(Value, Value) -> Value`, attaché via `typing.Annotated` :

```python
from typing import Annotated
from typing_extensions import TypedDict
from operator import add

class State(TypedDict):
    foo: int                          # pas de reducer -> écrasement (last write wins)
    bar: Annotated[list[str], add]    # operator.add -> concatène les listes
```

| Reducer | Comportement |
|---|---|
| Aucun | la nouvelle valeur **écrase** l'ancienne |
| `operator.add` | listes concaténées (`old + new`) ; ints sommés |
| `add_messages` | fusion message-aware (§3.2) |
| callable custom | tout ce que vous voulez |

### 3.1 Reducers personnalisés

```python
def reduce_unique(left: list | None, right: list | None) -> list:
    left = left or []
    right = right or []
    return left + [x for x in right if x not in left]

class State(TypedDict):
    items: Annotated[list, reduce_unique]
```

Un reducer custom doit être **pur** (pas d'I/O, pas de mutation des entrées), gérer le **cas initial `None`/vide**, et renvoyer le **type déclaré** du champ (source : https://docs.langchain.com/oss/python/langgraph/graph-api).

### 3.2 `add_messages` et `MessagesState`

`add_messages` (de `langgraph.graph.message`) est le reducer canonique de l'état conversationnel — **pas** un simple append, mais une fusion intelligente :

```python
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain.messages import AnyMessage   # en 1.x : messages sous langchain.messages

class GraphState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
```

Comportement (source : https://docs.langchain.com/oss/python/langgraph/use-graph-api ; https://docs.langchain.com/oss/python/langgraph/add-memory) :

1. **Append** des nouveaux messages.
2. **Update par `id`** : un message entrant qui partage l'`id` d'un existant le **remplace** (édition d'historique en place).
3. **Assigne un UUID** aux messages sans `id`.
4. **Désérialise** la forme dict `{"type": "human", "content": "..."}` en objets message.
5. **Supprime** via `RemoveMessage(id=...)` ; tout l'historique via `RemoveMessage(id=REMOVE_ALL_MESSAGES)`.

`MessagesState` = équivalent prébuilt d'un TypedDict avec `messages: Annotated[list[AnyMessage], add_messages]`. Le sous-classer pour ajouter des champs :

```python
from langgraph.graph import MessagesState

class State(MessagesState):
    documents: list[str]
```

> **Toujours** `add_messages` / `MessagesState` pour l'historique de chat — **jamais** `operator.add` sur des messages (sinon on perd l'update par id, la désérialisation et `RemoveMessage`).

### 3.3 Pourquoi les reducers sont CRITIQUES pour le parallélisme

Si deux nodes tournent dans le **même super-step** (fan-out) et écrivent tous deux le **même channel sans reducer**, LangGraph ne peut pas trancher et lève **`InvalidUpdateError` / `INVALID_CONCURRENT_GRAPH_UPDATE`** (source : https://docs.langchain.com/oss/python/langgraph/errors/INVALID_CONCURRENT_GRAPH_UPDATE). **Tout channel écrit par des branches parallèles DOIT avoir un reducer** (`operator.add`, `add_messages`, ou custom). C'est la cause n°1 de cette erreur.

---

## 4. Nodes

Fonctions sync ou async ; reçoivent `state` + paramètres injectés optionnels (par **nom + type hint**) ; renvoient un dict partiel (ou un `Command`).

```python
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

def plain_node(state: State):
    return {"key": "value"}

def node_with_config(state: State, config: RunnableConfig):
    step = config["metadata"]["langgraph_step"]
    return state

def node_with_runtime(state: State, runtime: Runtime[ContextSchema]):
    provider = runtime.context.llm_provider
    return state
```

- Paramètres injectables : `config: RunnableConfig`, `runtime: Runtime[...]`, `writer: StreamWriter`, `store: BaseStore`.
- Wrappés en `RunnableLambda` → batching/async/tracing LangSmith automatiques.
- Renvoyer `{}` ou un sous-ensemble de clés ne touche que ces channels ; les autres persistent.

```python
builder.add_node("node_name", node_function)
builder.add_node(my_node)                       # nom déduit du __name__
builder.add_sequence([n1, n2, n3])              # câblage linéaire (sucre sur add_edge)
```

Cache par node (nécessite un backend cache au `compile`) :

```python
from langgraph.cache.memory import InMemoryCache
from langgraph.types import CachePolicy

builder.add_node("expensive_node", expensive_node, cache_policy=CachePolicy(ttl=3))
graph = builder.compile(cache=InMemoryCache())
```

> **Idempotence** : un node peut être **réexécuté depuis le début** après interruption/reprise (checkpoints pris aux frontières de super-steps, pas au milieu d'une fonction). Effets de bord — écritures SQL, appels API — à rendre idempotents. Principe non négociable côté Dataiku (source ChatGPT, cohérent avec la doc durable-execution).

---

## 5. Edges et contrôle de flux

### 5.1 START / END

```python
from langgraph.graph import START, END

builder.add_edge(START, "node_a")   # point d'entrée
builder.add_edge("node_a", END)     # terminal
```

`set_entry_point("x")` ≡ `add_edge(START, "x")` ; `set_finish_point("x")` ≡ `add_edge("x", END)`.

### 5.2 Edges statiques — `add_edge`

```python
builder.add_edge("node_a", "node_b")
```

Plusieurs edges vers une même cible → fan-in (la cible attend toutes les sources). Plusieurs edges sortants → fan-out parallèle.

### 5.3 Edges conditionnels — `add_conditional_edges`

**Signature exacte (v1)** — `(source, path, path_map=None)`. **Il n'y a PAS de paramètre `then=`** : tout code/tuto qui le montre décrit une forme supprimée (source : https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges).

```python
add_conditional_edges(
    source: str,
    path: Callable[..., Hashable | Sequence[Hashable]] | Runnable[...],
    path_map: dict[Hashable, str] | list[str] | None = None,
) -> Self
```

```python
def routing_function(state: State) -> str:
    return "node_b" if state["foo"] else "node_c"

builder.add_conditional_edges("node_a", routing_function)

# path_map optionnel (valeur de retour du routeur -> nom de node ; aide aussi le rendu) :
builder.add_conditional_edges("node_a", routing_function, {True: "node_b", False: "node_c"})
```

Le routeur peut renvoyer : un nom de node, une liste de noms (fan-out), `END`, ou une liste de `Send` (§7). Branche conditionnelle depuis `START` possible (entrée conditionnelle) :

```python
from typing import Literal

def route_from_start(state: State) -> Literal["node_b", "node_c"]:
    return "node_b" if state["value"] > 5 else "node_c"

builder.add_conditional_edges(START, route_from_start)
```

> **Anti-pattern documenté** : pour un même node, choisir **un seul** mécanisme de routage — edges statiques **OU** conditionnel/`Command`. **Ne pas mélanger** edges normaux et routage dynamique sortant du même node (source : https://docs.langchain.com/oss/python/langgraph/graph-api).

---

## 6. `Command` — mettre à jour l'état ET router en un seul retour

```python
from langgraph.types import Command
from typing import Literal

def my_node(state: State) -> Command[Literal["next_node"]]:
    return Command(update={"foo": "bar"}, goto="next_node")
```

`Command` fusionne update d'état et routage, supprimant le besoin d'edge conditionnel séparé. C'est le **primitif universel de handoff** multi-agent : un node/tool renvoie `Command(goto=..., update=..., graph=Command.PARENT)` pour mettre à jour l'état ET router (rend naturels les graphes « edgeless » / dynamiques) (source : https://www.langchain.com/blog/command-a-new-tool-for-multi-agent-architectures-in-langgraph).

- L'**annotation `Command[Literal[...]]` est requise** pour que LangGraph rende le graphe et valide les cibles.
- Vers le graphe **parent** depuis un subgraph : `Command(update=..., goto="x", graph=Command.PARENT)` (§8).
- Reprendre après interrupt : `graph.invoke(Command(resume="yes"), config)`.

**`Command` vs edge conditionnel** : edge conditionnel si le node ne fait que *router* ; `Command` s'il doit *router ET mettre à jour l'état* dans le même step. Pour les handoffs entre agents-subgraphs et les règles de validité d'historique (paire `AIMessage` + `ToolMessage`), voir `references/orchestration-multi-agents.md`.

---

## 7. Send API (map-reduce / fan-out dynamique)

`Send` permet à un edge conditionnel de lancer un **nombre arbitraire, déterminé au runtime**, d'invocations parallèles d'un node, **chacune avec son propre état/payload** (qui n'a pas à matcher le schéma global). Primitif canonique de map-reduce (source : https://reference.langchain.com/python/langgraph/types/Send).

```python
Send(node: str, arg: Any, *, timeout: float | timedelta | TimeoutPolicy | None = None)
```

- `node` — nom du node cible.
- `arg` — payload/état par tâche remis à cette instance de node.
- `timeout` — politique de timeout par tâche poussée (récent).

Un routeur qui renvoie une **liste de `Send`** déclenche les exécutions « map » parallèles ; les sorties remontent dans un channel réduit partagé (le « reduce ») :

```python
import operator
from typing import Annotated
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START
from langgraph.types import Send

class OverallState(TypedDict):
    topic: str
    subjects: list[str]
    jokes: Annotated[list[str], operator.add]   # le reducer collecte les résultats parallèles

def generate_topics(state: OverallState):
    return {"subjects": ["lions", "elephants", "penguins"]}

def generate_joke(state: OverallState):           # reçoit {"subject": ...}, PAS l'état global
    return {"jokes": [f"... {state['subject']} ..."]}

def continue_to_jokes(state: OverallState):
    return [Send("generate_joke", {"subject": s}) for s in state["subjects"]]

builder = StateGraph(OverallState)
builder.add_node("generate_topics", generate_topics)
builder.add_node("generate_joke", generate_joke)
builder.add_edge(START, "generate_topics")
builder.add_conditional_edges("generate_topics", continue_to_jokes, ["generate_joke"])
graph = builder.compile()
```

(source : https://docs.langchain.com/oss/python/langgraph/use-graph-api)

Points clés :
- Le node worker lit le **payload `Send.arg`**, pas l'état global → chaque branche est isolée.
- Le « reduce » marche parce que `jokes` a `operator.add` ; **sans reducer**, les écritures parallèles lèvent `InvalidUpdateError` (§3.3).
- On peut mêler fan-out `Send` et routage conditionnel ordinaire en renvoyant une liste hétérogène.
- **`Send` vs edges multiples** : `Send` pour un fan-out dépendant des données (compte inconnu au build) ; edges statiques multiples pour un ensemble fixe et connu de branches parallèles.

---

## 8. Subgraphs (le substrat de composition)

Un subgraph est un graphe compilé utilisé dans un graphe parent. Les systèmes multi-agents sont des subgraphs-de-subgraphs. Deux modes selon le partage de clés (source : https://docs.langchain.com/oss/python/langgraph/use-subgraphs).

### 8.1 Schéma partagé → ajouter le subgraph compilé directement comme node

Quand les agents communiquent sur un **channel partagé** (ex. `messages` commun). L'état entre tel quel et refusionne via les reducers.

```python
subgraph = subgraph_builder.compile()      # partage des clés avec le State parent
builder = StateGraph(State)
builder.add_node("node_1", subgraph)       # le graphe compilé EST le node
builder.add_edge(START, "node_1")
graph = builder.compile()
```

### 8.2 Schémas différents → invoquer dans un node wrapper (transformer in/out)

Quand chaque agent doit garder un **historique isolé / fenêtre de contexte propre** (aucune clé partagée). Il faut wrapper l'`invoke` et traduire l'état dans les deux sens. Passer un tel subgraph directement à `add_node` **lève une erreur** (pas de clé partagée).

```python
def call_subgraph(state: State):
    subgraph_output = subgraph.invoke({"bar": state["foo"]})   # parent -> child
    return {"foo": subgraph_output["bar"]}                     # child -> parent

builder = StateGraph(State)
builder.add_node("node_1", call_subgraph)
builder.add_edge(START, "node_1")
graph = builder.compile()
```

### 8.3 Persistance des subgraphs (`checkpointer=` au compile)

| Mode | Réglage | Comportement |
|---|---|---|
| Par invocation (défaut) | `compile()` / `None` | état frais à chaque appel ; hérite du checkpointer parent pour interrupts/HITL |
| Par thread | `compile(checkpointer=True)` | l'état s'accumule sur le même thread |
| Stateless | `compile(checkpointer=False)` | pas de checkpointing ; comme une fonction simple |

Contraintes : le **parent doit compiler avec un checkpointer** pour les features de persistance subgraph ; les subgraphs par-thread **ne supportent pas les tool calls parallèles** (gérer avec `ToolCallLimitMiddleware`).

### 8.4 Observer l'exécution imbriquée

```python
subgraph_state = graph.get_state(config, subgraphs=True).tasks[0].state   # état d'un subgraph en pause (HITL)
for chunk in graph.stream(inputs, subgraphs=True, stream_mode="updates"):  # events imbriqués (le namespace dit quel (sous)graphe émet)
    ...
```

---

## 9. Compilation

`StateGraph` est un builder, non exécutable. `compile()` valide la structure (nodes orphelins, edges invalides) et renvoie un `CompiledStateGraph` qui implémente l'interface `Runnable` (`invoke`, `ainvoke`, `stream`, `astream`, `batch`).

```python
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.cache.memory import InMemoryCache

graph = builder.compile(
    checkpointer=InMemorySaver(),       # persistance / threads / time-travel
    cache=InMemoryCache(),              # active les CachePolicy par node
    interrupt_before=["human_review"],  # breakpoints statiques (HITL)
    interrupt_after=["risky_node"],
)
```

Signature constructeur (source : https://reference.langchain.com/python/langgraph/graph/state/StateGraph) :

```python
StateGraph(
    state_schema: type[StateT],
    context_schema: type[ContextT] | None = None,
    *,
    input_schema: type[InputT] | None = None,
    output_schema: type[OutputT] | None = None,
    **kwargs,   # config_schema ici est DÉPRÉCIÉ (v0.6.0 ; retrait v2.0.0)
)
```

---

## 10. Exécution : `invoke`, `stream`, `astream`

### 10.1 `invoke` / `ainvoke`

Tourne jusqu'au bout, renvoie l'état final (filtré sur `output_schema` si défini) :

```python
result = graph.invoke({"messages": [HumanMessage("Hi")]})
result = await graph.ainvoke({"messages": [HumanMessage("Hi")]})
```

### 10.2 `stream` / `astream` et stream modes

| Mode | Émet | Usage |
|---|---|---|
| `values` | snapshot complet de l'état après chaque step | suivre l'évolution globale |
| `updates` | seules les clés changées (`{node: update}`) | voir ce que chaque node a fait |
| `messages` | tuples `(message_chunk, metadata)` | **streaming token-par-token du LLM** |
| `custom` | données émises via `get_stream_writer()` | progression/statut depuis l'intérieur d'un node |
| `checkpoints` | dicts de checkpoint (requiert un checkpointer) | events de persistance |
| `tasks` | start/finish de tâches (résultats, erreurs) | observabilité par tâche |
| `debug` | checkpoints + tasks combinés | détail maximal |

```python
for step in graph.stream(inputs, stream_mode="updates"):
    print(step)                               # {"node_name": {...clés changées...}}

for mode, payload in graph.stream(inputs, stream_mode=["updates", "messages"]):
    ...                                       # modes multiples -> tuples (mode, payload)
```

Données custom depuis un node :

```python
from langgraph.config import get_stream_writer

def node(state: State):
    writer = get_stream_writer()
    writer({"status": "fetching..."})
    return {"answer": "data"}
```

> **Caveat Python < 3.11 async** (pertinent pour le double-chemin) : `get_stream_writer()` peut ne pas se propager ; ajouter alors un paramètre `writer: StreamWriter` au node et threader manuellement `RunnableConfig` dans les `ainvoke` du LLM. En contexte **3.9** webapp OWIsMind, on n'importe de toute façon **pas** LangGraph — ce streaming n'existe que dans un Code Agent 3.11. Pour le streaming côté webapp 3.9, voir le pattern polling-via-thread (mémoire projet L019), pas LangGraph.

**Note événements** : `astream_events` (interface LangChain `Runnable`) a pour **défaut `version="v2"`** ; `v3` est **opt-in et expérimental**, nécessite **LangChain ≥ 1.3** (mai 2026) et sélectionne le protocole content-block (source : https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/astream_events ; https://docs.langchain.com/oss/python/releases/changelog). Épingler `v2` sauf besoin explicite du protocole v3.

---

## 11. `recursion_limit`

`recursion_limit` plafonne le nombre de **super-steps** d'un run ; le dépassement lève `GraphRecursionError`. C'est une clé **top-level** de `config`, **PAS** sous `configurable`.

- **Défaut = 25** (source autoritaire : https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT). Message : `Recursion limit of 25 reached without hitting a stop condition.` Surprend les sous-agents (deepagents #1698 : « subagents silently use default limit of 25 »).
- Le relever **par invocation** via config, jamais en changeant un défaut :

```python
graph.invoke(inputs, config={"recursion_limit": 100})
```

- Inspecter le step courant : `config["metadata"]["langgraph_step"]`.
- Dégrader proprement avant la limite avec `RemainingSteps` :

```python
from langgraph.managed import RemainingSteps

class State(TypedDict):
    remaining_steps: RemainingSteps

def node(state: State):
    if state["remaining_steps"] <= 2:
        return {"messages": ["wrapping up"]}
```

> ⚠️ Une lecture antérieure du corpus annonçait « 1000 depuis v1.0.6 » — **c'est faux**, à rayer. Le défaut est **25** (vérifié 2026-06-14 contre l'error doc officielle + plusieurs issues 2026).

---

## 12. Configuration : Runtime Context vs `config["configurable"]`

Deux voies pour injecter des paramètres par run. La **Context API** (introduite en v0.6) est la voie moderne pour les **dépendances statiques** (choix de modèle, user id, feature flags) ; `config_schema` est déprécié (retrait v2.0).

### 12.1 Moderne : `context_schema` + `Runtime`

```python
from dataclasses import dataclass
from langgraph.runtime import Runtime
from langgraph.graph import StateGraph

@dataclass
class ContextSchema:
    llm_provider: str = "openai"

builder = StateGraph(State, context_schema=ContextSchema)
graph = builder.compile()

graph.invoke(inputs, context={"llm_provider": "anthropic"})   # top-level context=

def node(state: State, runtime: Runtime[ContextSchema]):
    provider = runtime.context.llm_provider
```

Le `Runtime` (injecté par nom+type, ou via `get_runtime`) expose (source : https://reference.langchain.com/python/langgraph/runtime/Runtime) :

| Attribut | Type | Rôle |
|---|---|---|
| `context` | `ContextT` | contexte utilisateur typé, scope run |
| `store` | `BaseStore \| None` | mémoire long terme clé-valeur inter-threads |
| `stream_writer` | `StreamWriter` | émettre des données `custom` |
| `previous` | `Any` | état d'exécution précédent (functional API) |
| `execution_info` | `ExecutionInfo \| None` | métadonnées runtime |

> **`Runtime` ne porte PAS `config`.** Pour le `RunnableConfig`, déclarer un paramètre `config: RunnableConfig` séparé ou appeler `get_config()` (`langgraph.config`).

### 12.2 Legacy : `config["configurable"]`

```python
graph.invoke(inputs, config={"configurable": {"thread_id": "t1", "llm_provider": "anthropic"}})

def node(state: State, config: RunnableConfig):
    provider = config["configurable"]["llm_provider"]
```

`configurable` reste la place du **`thread_id`** (identité de thread / checkpoint) — non déprécié pour cet usage. Réserver `configurable` à l'identité ; préférer `context` pour la config utilisateur dans le code neuf.

> **Sharp edge 1.0** : avec `RemoteGraph`, utiliser `context` (middleware) et `config.configurable` (checkpointing) **ensemble** peut entrer en conflit (issue #6342) — vérifier sur votre version.

---

## 13. Durability / persistance (`durability`)

Compilé avec un `checkpointer`, l'argument `durability` contrôle *quand* les checkpoints sont écrits (remplace `checkpoint_during` déprécié) :

| Mode | Comportement |
|---|---|
| `"exit"` | checkpoint seulement à la sortie (succès/erreur/interrupt). Le plus rapide ; **pas de reprise mi-run**. |
| `"async"` | checkpoint asynchrone pendant que le step suivant tourne. **Défaut** ; bon équilibre, fenêtre de perte minime sur crash. |
| `"sync"` | checkpoint synchrone avant chaque step suivant. Le plus durable ; surcoût. |

```python
graph.invoke(inputs, config={"configurable": {"thread_id": "t1"}}, durability="async")
```

> Le défaut est **`"async"`** ; le kwarg `durability` sur `invoke`/`stream` vaut `None` par défaut → résout vers le mode du graphe. **Passer `durability=` explicitement** dans les exemples où ça compte (le moyen le moins cher de ne pas se tromper). Pour un backend Dataiku long ou sujet à redémarrage, `"async"` est le bon défaut ; `"sync"` si chaque step doit survivre à un crash (source : https://docs.langchain.com/oss/python/langgraph/durable-execution).

---

## 14. Métadonnées runtime utiles (dans un node, `config["metadata"]`)

```python
config["metadata"]["langgraph_step"]           # numéro de super-step courant
config["metadata"]["langgraph_node"]           # nom du node courant
config["metadata"]["langgraph_triggers"]       # edges déclencheurs
config["metadata"]["langgraph_checkpoint_ns"]  # namespace de checkpoint
```

---

## 15. Squelette minimal end-to-end (Code Agent 3.11)

```python
import operator
from typing import Annotated
from typing_extensions import TypedDict
from dataclasses import dataclass
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.runtime import Runtime
from langchain.messages import AnyMessage, HumanMessage, AIMessage

@dataclass
class Ctx:
    model: str = "claude-sonnet-4-6"   # id Anthropic réel et courant (voir references/claude-api)

class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    scratch: Annotated[list[str], operator.add]

def think(state: State, runtime: Runtime[Ctx]):
    return {"scratch": [f"using {runtime.context.model}"]}

def respond(state: State):
    return {"messages": [AIMessage("done")]}

builder = StateGraph(State, context_schema=Ctx)
builder.add_node(think)
builder.add_node(respond)
builder.add_edge(START, "think")
builder.add_edge("think", "respond")
builder.add_edge("respond", END)
graph = builder.compile()

out = graph.invoke(
    {"messages": [HumanMessage("hi")]},
    context={"model": "claude-opus-4-8"},   # id réel ; 1M de contexte au tarif standard
    config={"recursion_limit": 50},
    durability="async",
)
```

> Ce code suppose un **code env Dataiku 3.11**. En contexte **webapp 3.9**, ne pas importer `langgraph`/`langchain` : appeler le LLM Mesh / les agents / tools via les APIs Dataiku natives (voir `references/dataiku-code-agents.md`).

---

## 16. « Quoi utiliser quand »

| Besoin | Utiliser |
|---|---|
| Boucle model→tools→response standard, rapide, middleware out-of-the-box | `create_agent` (`langchain.agents`) — voir `references/langchain-v1.md` |
| Orchestration sur mesure, déterministe + agentique, contrôle total (**Dataiku Code Agent**) | `StateGraph` bas niveau (ce fichier) |
| Sommer/concaténer des résultats entre nodes | `Annotated[..., operator.add]` |
| Historique de chat | `Annotated[list, add_messages]` / `MessagesState` |
| Branches parallèles fixes et connues | edges statiques multiples + reducer sur les channels partagés |
| Parallélisme dynamique data-dependent (map-reduce) | `Send` depuis un edge conditionnel + reducer pour le reduce |
| Brancher sur l'état | `add_conditional_edges` (pas de `then=`) |
| Mettre à jour l'état **et** router en un node | `Command(update=..., goto=...)` |
| Handoff entre agents-subgraphs | `Command(..., graph=Command.PARENT)` — voir `references/orchestration-multi-agents.md` |
| Params utilisateur par run (modèle, user id, flags) | `context_schema` + `Runtime.context` |
| Identité de thread / clé de checkpoint | `config["configurable"]["thread_id"]` |
| Streaming token à l'UI | `stream_mode="messages"` |
| Observabilité step/progression | `stream_mode="updates"` (+ `"custom"`) |
| Runs résilients aux crashs | `compile(checkpointer=...)` + `durability="async"`/`"sync"` |
| Borner les boucles agentiques/cycliques | `recursion_limit` (défaut 25) + `RemainingSteps` |

---

## 17. Pièges / anti-patterns

- **Oublier `.compile()`** — `StateGraph` est un builder, non invocable.
- **Écritures parallèles sur un channel sans reducer** → `InvalidUpdateError` / `INVALID_CONCURRENT_GRAPH_UPDATE`.
- **`recursion_limit` dans `configurable`** — c'est une clé top-level. Et **ne pas** supposer un défaut de 1000 : c'est **25**.
- **Muter l'état en place** au lieu de renvoyer un dict partiel — le runtime n'applique les reducers qu'aux valeurs renvoyées.
- **`operator.add` sur des messages** — perd update-par-id, désérialisation, `RemoveMessage` ; utiliser `add_messages`.
- **Attendre que `Runtime` contienne `config`** — il ne le contient pas (`config: RunnableConfig` séparé ou `get_config()`).
- **Mélanger edges normaux et routage dynamique** sortant du même node.
- **`add_conditional_edges(..., then=...)`** — pas de `then=` ; signature `(source, path, path_map=None)`.
- **Importer `langgraph.prebuilt` / `create_react_agent`** dans du code neuf — déprécié ; `langchain.agents.create_agent`.
- **Payload `Send` mal dimensionné** — le worker reçoit `Send.arg`, pas l'état global.
- **Ajouter un subgraph à schéma différent directement comme node** — lève une erreur ; passer par un wrapper de transformation (§8.2).
- **Effets de bord non idempotents dans un node** — un node peut être réexécuté depuis le début après reprise.
- **Importer langchain/langgraph en contexte Python 3.9** (backend webapp OWIsMind) — interdit ; APIs Dataiku natives uniquement.
- **Croire au protocole d'events `v3` par défaut** — `astream_events` est `v2` par défaut ; `v3` opt-in/expérimental (LangChain ≥ 1.3).

---

## 18. Sources primaires

- Graph API overview — https://docs.langchain.com/oss/python/langgraph/graph-api
- Use the graph API (exemples Send, START routing) — https://docs.langchain.com/oss/python/langgraph/use-graph-api
- StateGraph reference — https://reference.langchain.com/python/langgraph/graph/state/StateGraph
- `add_conditional_edges` reference (signature sans `then=`) — https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges
- Send reference — https://reference.langchain.com/python/langgraph/types/Send
- Runtime reference — https://reference.langchain.com/python/langgraph/runtime/Runtime
- Subgraphs — https://docs.langchain.com/oss/python/langgraph/use-subgraphs
- Command (blog primitif) — https://www.langchain.com/blog/command-a-new-tool-for-multi-agent-architectures-in-langgraph
- Streaming — https://docs.langchain.com/oss/python/langgraph/streaming
- `astream_events` reference — https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/astream_events
- Durable execution — https://docs.langchain.com/oss/python/langgraph/durable-execution
- `GRAPH_RECURSION_LIMIT` (défaut 25) — https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT
- `INVALID_CONCURRENT_GRAPH_UPDATE` — https://docs.langchain.com/oss/python/langgraph/errors/INVALID_CONCURRENT_GRAPH_UPDATE
- LangGraph 1.0 GA / blog 1.0 — https://changelog.langchain.com/announcements/langgraph-1-0-is-now-generally-available · https://www.langchain.com/blog/langchain-langgraph-1dot0
- Changelog LangChain (1.2 / 1.3, events v3) — https://docs.langchain.com/oss/python/releases/changelog
