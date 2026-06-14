# LangChain v1 essentiels + `create_agent` + middleware + structured output

> **À jour : juin 2026.** Baseline LangChain 1.x / LangGraph 1.x / Dataiku DSS 14.x. Cette fiche est une référence du skill `agentique-python-dataiku` ; voir `SKILL.md` (parent) pour le cadrage, et les fiches sœurs `references/langgraph-v1.md` (runtime, graphes, checkpointers), `references/dataiku-code-agents.md` (Code Agents, LLM Mesh, `DKUChatModel`) et `references/anti-patterns-deprecations-versions.md`.

---

## 0. Décision en une phrase

Pour une **boucle modèle + outils + un peu de middleware**, partir de `langchain.agents.create_agent`. Pour un **graphe d'orchestration explicite** (branches déterministes, parallélisme, subgraphs, interruptions, reprise de run), descendre vers LangGraph (`references/langgraph-v1.md`). `create_agent` *est* LangGraph sous le capot : commencer là, descendre seulement pour ce que l'abstraction n'expose pas.

## 0bis. Contrainte Python — DOUBLE CHEMIN (fait dur, non négociable)

L'instance Dataiku dispose de **deux code environments : Python 3.9 ET Python 3.11**.

| Contexte | Python | Règle |
|---|---|---|
| **Code env 3.11** (≥ 3.10) | 3.11 | LangChain/LangGraph v1 importables. Un **Code Agent** assigné à un code env 3.11 PEUT `import langchain`/`langgraph`. |
| **Backend webapp OWIsMind** | **3.9.23** | **stdlib-only, AUCUN import langchain**. Appeler LLM Mesh / agents / tools via les **APIs Dataiku natives** directement (voir `references/dataiku-code-agents.md`). |

LangChain/LangGraph v1 **exigent Python ≥ 3.10** (3.9 abandonné en v1) — source : https://docs.langchain.com/oss/python/migrate/langgraph-v1. **Ne jamais recommander d'importer langchain en contexte 3.9.** Dans tout passage où la version compte, présenter les **deux chemins** : (A) code env 3.11 → API LangChain ; (B) contexte 3.9 → patterns LangChain *empruntés* (boucle, hooks, stratégies de structured output, couche d'honnêteté « router pas nier ») mais implémentés en Python pur sur LLM Mesh.

---

## 1. Modèle mental : Agent = Model + Harness

> **« An agent is a model calling tools in a loop until a given task is complete. »** Le *harness* = prompt + tools + middleware qui façonnent le comportement autour de la boucle ; son rôle : « get the model the right context at the right time. » (source : https://docs.langchain.com/oss/python/langchain/agents)

Deux objectifs de design v1 (source : https://docs.langchain.com/oss/python/langchain/philosophy) : **standardisation modèle** (une interface — `init_chat_model`, messages, `bind_tools`, `with_structured_output` — sur OpenAI / Anthropic / Google, pour éviter le lock-in) et **orchestration au-delà du texte** (outils appelables dynamiquement). Depuis 2024-10, **LangGraph est la couche d'orchestration préférée** ; les agents v1 sont bâtis dessus → ils héritent durabilité, persistance, streaming, HITL.

La boucle ReAct compilée = cycle LangGraph à deux nœuds : nœud **`model`** → si `tool_calls` → nœud **`tools`** (exécute, appende des `ToolMessage`) → retour modèle. Fin **quand le modèle ne renvoie plus de `tool_calls`**. Garde-fou runtime : `recursion_limit` (**défaut 25**, pas 1000) ; le relever par invocation via `config={"recursion_limit": N}` — source : https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT.

```python
graph.invoke(inputs, config={"recursion_limit": 100})   # relever ponctuellement, ne pas changer le défaut
```

ChatGPT et le corpus concordent sur ce cadrage (workflow = chemins prédéterminés ; agent = processus auto-défini).

---

## 2. Découpage des packages (ce qu'on `pip install`)

| Package | Rôle | Notes |
|---|---|---|
| **`langchain-core`** | Abstractions de base : `Runnable`/LCEL, `BaseChatModel`, messages + content blocks, prompts, parsers, tools base. | Stable, léger. Dernier patch **1.4.7 (2026-06-12)**, cadence indépendante. |
| **`langchain`** | Briques agent haut niveau : `create_agent`, `init_chat_model`, `@tool`, `langchain.messages`, middleware. Namespace **volontairement réduit** en v1. | Série 1.3.x. |
| **`langchain-classic`** | **Nouveau en v1.** Tout ce qui a quitté `langchain` : chaînes legacy (`LLMChain`, `ConversationChain`), retrievers, indexing API, `hub`, parsers de réparation, `AgentExecutor`/`initialize_agent`. **Maintenance jusqu'à décembre 2026.** | `pip install langchain-classic`. |
| **Packages d'intégration** | `langchain-openai`, `langchain-anthropic`, `langchain-google-genai`, `langchain-aws`, `langchain-ollama`… | Versions/cycles propres. |
| **`langgraph`** | Runtime d'orchestration sous `create_agent`. | Série 1.x ; LangGraph 1.1 (mars 2026). |
| **`langsmith`** | Observabilité / tracing / évals. Produit séparé, optionnel. | |

```bash
pip install -U langchain                 # briques agent
pip install -qU "langchain[anthropic]"   # + intégration via extras
pip install langchain-classic            # seulement si chaînes/retrievers/hub legacy
```
(source : https://docs.langchain.com/oss/python/releases/langchain-v1 · https://docs.langchain.com/oss/python/migrate/langchain-v1)

> ⚠️ **NO INSTALL en environnement OWIsMind** : ne jamais lancer ces commandes ici ; les code envs sont gérés par l'utilisateur. Ces lignes documentent le *contenu* des packages, pas une action.

**Où vit quoi dans `langchain` v1** : `langchain.agents` (`create_agent`, `AgentState`) · `langchain.messages` · `langchain.tools` (`@tool`, `BaseTool`, `ToolRuntime`) · `langchain.chat_models` (`init_chat_model`) · `langchain.embeddings` (`init_embeddings`) · `langchain.agents.middleware` · `langchain.agents.structured_output` (`ToolStrategy`, `ProviderStrategy`).

---

## 3. Runnables & LCEL (l'essentiel)

Tout composant composable implémente `Runnable` (langchain-core) → streaming, async, batch, parallélisme, retries, fallbacks, tracing « gratuits ». Méthodes clés (variantes sync + `a…`) :

| Méthode | Usage |
|---|---|
| `invoke` / `ainvoke` | Appel unique |
| `batch` / `abatch` | Parallèle, borné par `max_concurrency` |
| `batch_as_completed` | Résultats au fil de l'eau (hors ordre) |
| `stream` / `astream` | Streaming chunks (les chunks s'additionnent : `full = chunk if full is None else full + chunk`) |
| `astream_events(input, config, version=...)` | Flux d'évènements fin |
| `with_config` / `with_retry` / `with_fallbacks` / `bind` | Config, retry, failover, kwargs pré-liés |
| `assign` / `pick` | Ajouter / sélectionner des clés dict dans un pipeline |

> **CORRECTION version** : `astream_events` a pour **défaut `version="v2"`** (pas v3). `v3` est **opt-in et expérimental**, nécessite **LangChain ≥ 1.3** (protocole orienté content-blocks). Épingler `v2` sauf besoin explicite. (source : https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/astream_events)

**LCEL** = langage déclaratif ; le `|` chaîne des Runnables (sortie → entrée suivante), construit un `RunnableSequence`. C'est le remplaçant canonique du `LLMChain` déprécié :

```python
from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a terse assistant."),
    ("human", "{question}"),
])
model = init_chat_model("anthropic:claude-sonnet-4-6")     # id réel/courant (cf. §4)
chain = prompt | model | StrOutputParser()                 # RunnableSequence -> str
chain.invoke({"question": "What is LCEL?"})
```

Primitives de composition (`langchain_core.runnables`) : `RunnableSequence` (`a|b|c`), `RunnableParallel` (branches concurrentes → dict), `RunnablePassthrough` (+ `.assign(...)` pour ajouter des clés, shape RAG classique), `RunnableLambda` (fonction Python → Runnable), `RunnableBranch` (routage if/elif/else), `RunnableConfigurableFields` / `RunnableConfigurableAlternatives` (sélection runtime via `config["configurable"]`).

`config` (RunnableConfig) = canal latéral universel : `run_name`, `tags`, `metadata`, `callbacks`, `max_concurrency`, `configurable`. Résilience composable : `model.with_retry(stop_after_attempt=3).with_fallbacks([backup_model])`. Les chat models ont aussi un retry exponentiel intégré sur 429/5xx/réseau via `max_retries` (**défaut 6**) + `timeout` à l'init.

---

## 4. Chat models & `init_chat_model`

Factory provider-agnostique. Signature vérifiée (source : https://reference.langchain.com/python/langchain/chat_models/init_chat_model) :

```python
init_chat_model(
    model: str | None = None,
    *,
    model_provider: str | None = None,
    configurable_fields: Literal['any'] | list[str] | tuple[str, ...] | None = None,
    config_prefix: str | None = None,
    **kwargs: Any,                       # api_key, temperature, max_tokens, timeout, max_retries, profile…
) -> BaseChatModel | _ConfigurableModel
```

```python
from langchain.chat_models import init_chat_model
model = init_chat_model("claude-sonnet-4-6")                    # provider inféré: anthropic
model = init_chat_model("openai:gpt-5.5")                       # préfixe explicite
model = init_chat_model("google_genai:gemini-3.5-flash", max_retries=10, timeout=120)
```

**Ids modèles** : `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5` sont **réels et courants** (Opus 4.8 / Sonnet 4.6 = 1M de contexte au tarif standard ; Haiku = 200K) — garder les chaînes exactes, sans suffixe date sur les alias (Haiku = exception avec id daté). En revanche **`gpt-5.5` et `gemini-3.5-flash` sont NON VÉRIFIÉS** (non-Anthropic) : confirmer l'id auprès du provider/intégration avant tout shipping. (source : skill `claude-api` · https://platform.claude.com/docs/en/about-claude/models/overview)

**`bind_tools`** — outils sur un modèle :

```python
from langchain.tools import tool

@tool
def get_weather(location: str) -> str:
    """Get the weather at a location."""
    return f"It's sunny in {location}."

mwt = model.bind_tools([get_weather])
resp = mwt.invoke("What's the weather in Boston?")     # AIMessage
for tc in resp.tool_calls:
    print(tc["name"], tc["args"], tc["id"])
model.bind_tools([get_weather], tool_choice="any")          # forcer un tool quelconque
model.bind_tools([get_weather], tool_choice="get_weather")  # forcer un tool précis
```
⚠️ **Breaking v1** : `bind_tools` renvoie désormais `Runnable[..., AIMessage]` (était `BaseMessage`).

**Model profiles** (nouveau v1.1, enrichi 1.2/1.4) — `.profile` décrit les capacités (catalogue models.dev) ; le framework s'en sert pour choisir la stratégie de structured output et le timing de summarization :

```python
model.profile                              # {'max_input_tokens':400000,'tool_calling':True,'reasoning_output':True,...}
model = init_chat_model("...", profile={"max_input_tokens": 100_000, "tool_calling": True})  # patch d'un self-hosted absent du catalogue
```

**Tokens/coûts** : `UsageMetadataCallbackHandler` (config callbacks) ou `AIMessage.usage_metadata` (`input_tokens`/`output_tokens`/`total_tokens` + details).

**Modèles configurables** (paramétrer sans reconstruire) :
```python
cfg = init_chat_model(temperature=0)       # configurable par défaut
cfg.invoke("hi", config={"configurable": {"model": "claude-sonnet-4-6"}})
```

---

## 5. Messages, content blocks, format standard

Quatre types (`langchain.messages` / `langchain_core.messages`) : `SystemMessage`, `HumanMessage`, `AIMessage`, `ToolMessage` (**`tool_call_id` obligatoire**, doit matcher l'appel d'origine — sinon la boucle casse).

Le gros gain ergonomique v1 = **`.content` vs `.content_blocks`** : `.content` est lâche (str / liste / structure native provider) ; **`.content_blocks` est une vue typée, provider-agnostique, parsée à la demande** → code neutre pour lire reasoning, citations, tool calls, images, fichiers uniformément.

```python
for block in response.content_blocks:
    if block["type"] == "reasoning": print(block.get("reasoning"))
    elif block["type"] == "text":    print(block.get("text"))
    elif block["type"] == "tool_call": print(block["name"], block["args"], block["id"])
```

Types standard : `text` · `reasoning` · `image`/`audio`/`video`/`file` (`url`/`base64`/`file_id` + `mime_type`) · `text-plain` · `tool_call` · `invalid_tool_call`.

Champs `AIMessage` courants : `response.text` (**propriété** en v1, pas `response.text()`), `.content`, `.content_blocks`, `.tool_calls`, `.id`, `.usage_metadata`, `.response_metadata`. `ToolMessage` accepte `artifact={...}` : données accessibles au code mais **non envoyées au modèle** (utile pour transporter lignes brutes / ids sources à côté d'un résumé).

Pour sérialiser les blocs standard dans `content` : `init_chat_model(..., output_version="v1")` (ou `LC_OUTPUT_VERSION=v1`) ; OpenAI Responses « ancien » comportement → `output_version="v0"`.

---

## 6. `create_agent` — la voie v1

`create_agent` (dans `langchain.agents`) remplace **à la fois** `AgentExecutor` et `langgraph.prebuilt.create_react_agent` (ce dernier **déprécié** en LangGraph v1, import shim vers `create_agent`). `AgentExecutor`/`initialize_agent` vivent dans **`langchain-classic`** (maintenance jusqu'à déc. 2026).

### 6.1 Signature (vérifiée)

```python
from langchain.agents import create_agent

def create_agent(
    model: str | BaseChatModel,
    tools: Sequence[BaseTool | Callable[..., Any] | dict[str, Any]] | None = None,
    *,
    system_prompt: str | SystemMessage | None = None,           # SystemMessage accepté depuis 1.1 (cache-control)
    middleware: Sequence[AgentMiddleware[StateT_co, ContextT]] = (),
    response_format: ResponseFormat[ResponseT] | type[ResponseT] | dict[str, Any] | None = None,
    state_schema: type[AgentState[ResponseT]] | None = None,     # DOIT être un TypedDict (étendre AgentState)
    context_schema: type[ContextT] | None = None,                # dataclass: contexte par-run immuable
    checkpointer: Checkpointer | None = None,                    # mémoire multi-tours (thread_id)
    store: BaseStore | None = None,                              # mémoire long terme inter-threads
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
    debug: bool = False,
    name: str | None = None,                                     # sous-agent embarqué (subgraph)
    cache: BaseCache[Any] | None = None,
    transformers: Sequence[TransformerFactory] | None = None,
) -> CompiledStateGraph[...]:
    ...
```
(source : https://reference.langchain.com/python/langchain/agents/factory/create_agent)

Renvoie un `StateGraph` compilé → `.invoke`/`.stream`/`.astream`/`.get_state`, embarquable comme nœud/subgraph. État (`AgentState`, TypedDict) : `messages` (scratchpad/conversation), `structured_response` (si `response_format`), `jump_to` (contrôle interne middleware).

### 6.2 Usage

```python
from langchain.agents import create_agent
from langchain_core.utils.uuid import uuid7
from langgraph.checkpoint.memory import InMemorySaver

agent = create_agent(
    model="claude-sonnet-4-6",
    tools=[get_weather],
    system_prompt="You are a helpful assistant. Be concise.",
    checkpointer=InMemorySaver(),          # mémoire multi-tours
)
result = agent.invoke(
    {"messages": [{"role": "user", "content": "What's the weather in SF?"}]},
    config={"configurable": {"thread_id": str(uuid7())}},
)
print(result["messages"][-1].content_blocks)
```

**`thread_id` scope la *conversation*** (historique, checkpoints) ; **`context` porte les *données par-run*** (user id, project key…) lues par tools/middleware — ne pas les mélanger ni les bricoler dans `config["configurable"]`.

```python
from dataclasses import dataclass
@dataclass
class Context: user_id: str
agent = create_agent(model=model, tools=tools, context_schema=Context)
agent.invoke({"messages": [...]}, context=Context(user_id="123"))
```

**Streaming** : `stream_mode="values"` (snapshot d'état complet à chaque pas), `"updates"` (deltas par nœud), `"messages"` (tokens LLM). ⚠️ **Breaking v1** : le nœud modèle s'appelle **`"model"`** (était `"agent"`).

### 6.3 Migration (recettes)

```python
# create_react_agent (LangGraph) -> create_agent : renommage 'prompt' -> 'system_prompt' + déplacement de package
# from langgraph.prebuilt import create_react_agent
# agent = create_react_agent(model, tools, prompt="...")
from langchain.agents import create_agent
agent = create_agent(model, tools, system_prompt="...")

# AgentExecutor -> create_agent : la boucle EST le graphe ; intermediate_steps -> result["messages"]
# out["output"], out["intermediate_steps"]  =>  out["messages"][-1].content + les paires AIMessage(tool_calls)/ToolMessage
```

Map symbolique : `LLMChain` → LCEL · `AgentExecutor`/`initialize_agent`/`create_react_agent` → `create_agent` · mémoire (`ConversationBufferMemory`…) → checkpointer + `thread_id` · `langchain.chains/.retrievers/.indexes`, `from langchain import hub` → `langchain_classic.*` · `pre_model_hook`/`post_model_hook` → middleware `before_model`/`after_model` · sélection dynamique modèle/prompt → `wrap_model_call` · `config["configurable"]` par-run → `context_schema` + `context=`.

> ⚠️ **Rumeur fausse** : « `create_agent` n'existe plus en 1.1.0 » = un **venv périmé**, retracté ; `from langchain.agents import create_agent` marche en 1.1.0 propre. (source : https://forum.langchain.com/t/create-agent-no-longer-exists-in-langchain-agents-v1-1-0/2350)

---

## 7. Middleware — le modèle d'extensibilité v1

Remplace le couple fragile `pre_model_hook`/`post_model_hook` (« difficiles à combiner »). Chaque middleware gère **une** préoccupation et compose librement (logging, transformation prompt/tool/output, résilience retries/fallbacks/arrêt anticipé, gouvernance rate-limit/guardrails/PII).

### 7.1 Hooks & signatures

**Hooks node-style** (lisent l'état, renvoient un dict de mise à jour ou `None`, peuvent `jump_to`) : `before_agent`, `before_model`, `after_model`, `after_agent` (+ variantes async `abefore_model`…).

**Hooks wrap-style** (vous contrôlez l'exécution — appeler `handler` 0/1/n fois) :
```python
def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse: ...
def wrap_tool_call(self, request: ToolCallRequest, handler) -> ToolMessage | Command: ...
```

### 7.2 Ordre d'exécution (à mémoriser — modèle « onion »)

Pour `middleware=[m1, m2, m3]` :
```
before_agent:   m1 -> m2 -> m3        (déclaration)
  [boucle]
  before_model: m1 -> m2 -> m3        (déclaration)
  wrap_model_call (IMBRIQUÉ, externe = premier):  m1( m2( m3( <model> ) ) )
  after_model:  m3 -> m2 -> m1        (INVERSE)
  [/boucle]
after_agent:    m3 -> m2 -> m1        (INVERSE)
```
**Règle** : `before_*` dans l'ordre ; `after_*` en **inverse** ; `wrap_*` **imbriqués** (premier = plus externe). (source : https://docs.langchain.com/oss/python/langchain/middleware/custom)

### 7.3 Classe vs décorateur

```python
from langchain.agents.middleware import AgentMiddleware, AgentState, before_model, wrap_model_call, hook_config
from typing_extensions import NotRequired
from langchain.messages import AIMessage

class CallCounter(AgentMiddleware):
    class State(AgentState):
        model_call_count: NotRequired[int]
    state_schema = State
    def before_model(self, state, runtime):
        if state.get("model_call_count", 0) > 10:
            return {"jump_to": "end"}
        return None

@before_model
def log_before(state, runtime):
    print(f"{len(state['messages'])} messages")
    return None
```
Décorateurs : `@before_agent`, `@before_model`, `@after_model`, `@after_agent`, `@wrap_model_call`, `@wrap_tool_call`, `@dynamic_prompt`, `@hook_config`.

### 7.4 `jump_to` (court-circuit)

Un hook node sort tôt en renvoyant `jump_to`. **Il doit déclarer ses cibles** via `@hook_config(can_jump_to=[...])`. Cibles : `"end"` (fin), `"model"` (nœud modèle / premier `before_model`), `"tools"` (nœud tools).

```python
from langchain.agents.middleware import after_model, hook_config
@after_model
@hook_config(can_jump_to=["end"])
def block_unsafe(state, runtime):
    if "BLOCKED" in state["messages"][-1].content:
        return {"messages": [AIMessage("I cannot respond to that.")], "jump_to": "end"}
    return None
```

### 7.5 Prompt / modèle / tools dynamiques via `ModelRequest`

`ModelRequest` porte la config de l'appel modèle et offre `request.override(...)` (immuable : renvoie un **nouveau** request). Champs vérifiés : `model`, `messages`, `system_message` (`SystemMessage|None`) **et** `system_prompt` (`str|None`) — les **deux** existent —, `tool_choice`, `tools`, `response_format`, `state`, `runtime`, `model_settings`. (source : https://reference.langchain.com/python/langchain/agents/middleware/types/ModelRequest)

```python
from langchain.agents.middleware import wrap_model_call, dynamic_prompt

@wrap_model_call                                   # swap modèle / injection de tools mid-task
def route(request, handler):
    model = advanced if len(request.messages) > 20 else basic
    return handler(request.override(model=model, tools=request.tools[:2]))

@dynamic_prompt                                    # sucre au-dessus de wrap_model_call : prompt par-run
def make_prompt(request):
    return f"You are assisting user {request.runtime.context.user_id}. Be concise."
```

### 7.6 Middleware prébuilt (v1.1)

`SummarizationMiddleware` (résume près de la limite ; utilise les profiles depuis 1.1) · `ContextEditingMiddleware` (`ClearToolUsesEdit`) · `HumanInTheLoopMiddleware` (approbation avant tool, `InterruptOnConfig`) · `ModelCallLimitMiddleware` / `ToolCallLimitMiddleware` (plafonds coût/boucle) · `ModelFallbackMiddleware` / `ModelRetryMiddleware` (backoff, nouveau 1.1) / `ToolRetryMiddleware` · `LLMToolSelectorMiddleware` (pré-sélection LLM des tools) · `LLMToolEmulator` (test) · `PIIMiddleware` · content-moderation OpenAI (nouveau 1.1) · `TodoListMiddleware` · `ShellToolMiddleware` · `FilesystemFileSearchMiddleware` · `ProviderToolSearchMiddleware` · prompt-caching Anthropic.

```python
from langchain.agents.middleware import SummarizationMiddleware, HumanInTheLoopMiddleware
agent = create_agent(
    model="claude-sonnet-4-6", tools=tools,
    middleware=[
        SummarizationMiddleware(model="claude-sonnet-4-6", trigger={"tokens": 1000}),
        HumanInTheLoopMiddleware(interrupt_on={
            "send_email": {"description": "Review before sending",
                           "allowed_decisions": ["approve", "reject"]}}),
    ],
)
```

---

## 8. Tools (`@tool`)

Le `@tool` transforme une fonction typée en tool appelable. **Type hints obligatoires** (= schéma d'entrée) ; **docstring = description lue par le modèle**.

```python
from langchain.tools import tool, ToolRuntime
from dataclasses import dataclass
from langgraph.types import Command
from langchain.messages import ToolMessage

@tool
def search_db(query: str, limit: int = 10) -> str:
    """Search the customer database.
    Args:
        query: Search terms.
        limit: Max results.
    """
    return f"{limit} results for '{query}'"

@dataclass
class Ctx: user_id: str

@tool
def whoami(runtime: ToolRuntime[Ctx]) -> str:
    """Return current user info."""
    return runtime.context.user_id          # context immuable; runtime.state, runtime.store, runtime.tool_call_id dispo
```

⚠️ `config` et `runtime` sont des **noms de paramètres réservés** ; noms de tools en `snake_case`. Schéma custom via `@tool(args_schema=PydanticModel)` ou `@tool("name", description=...)`. Sorties : `str` / `dict` / `return_direct=True` (court-circuite la boucle) / `Command(update={...})` (met à jour l'état depuis le tool). **Erreurs de tool** → middleware pour les transformer en `ToolMessage` lisibles par le modèle plutôt que crasher :

```python
from langchain.agents.middleware import wrap_tool_call
@wrap_tool_call
def catch_tool_errors(request, handler):
    try:
        return handler(request)
    except Exception as e:
        return ToolMessage(content=f"Tool error: {e}", tool_call_id=request.tool_call["id"])
```

**v1.2** : les tools ont un attribut `extras` (config provider-spécifique : web search, code interpreter, MCP connector… exécutés côté serveur du provider).

---

## 9. Structured output

**Deux entrées distinctes — ne jamais les confondre**, et ne pas confondre non plus avec la **validité d'arguments de tool** (les schémas stricts de tool valident les *args* d'un appel, pas la *forme de la réponse* — mécanique séparée).

| | Niveau **modèle** | Niveau **agent** |
|---|---|---|
| API | `model.with_structured_output(Schema)` | `create_agent(response_format=...)` |
| Boucle | non (one-shot) | oui (puis coerce le tour final) |
| Résultat | objet validé renvoyé directement | `result["structured_response"]` |

### 9.1 `with_structured_output` (modèle)

```python
from pydantic import BaseModel, Field

class Movie(BaseModel):
    """A movie."""
    title: str = Field(description="The title")
    year: int = Field(description="Year released")
    rating: float

m = model.with_structured_output(Movie)
m.invoke("Details about Inception")     # -> Movie(...)
```

Schémas acceptés : Pydantic `BaseModel` (→ instance), `TypedDict` (→ dict), dataclass (→ dict), JSON Schema brut (→ dict). `method=` : `"json_schema"` | `"function_calling"` | `"json_mode"` (+ `"anthropic_json_mode"` pour Anthropic). Capter l'échec sans lever : `with_structured_output(Movie, include_raw=True)` → `{"raw","parsed","parsing_error"}`.

### 9.2 `response_format` (agent) — trois stratégies

```python
from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy, ProviderStrategy
from pydantic import BaseModel

class Plan(BaseModel):
    intent: str
    columns: list[str]

agent = create_agent(model, tools=[...], response_format=Plan)                  # AutoStrategy (schéma nu)
agent = create_agent(model, tools=[...], response_format=ProviderStrategy(Plan))# natif provider
agent = create_agent(model, tools=[...], response_format=ToolStrategy(Plan))    # tool synthétique
result = agent.invoke({"messages": [...]})
plan = result["structured_response"]      # instance Pydantic (ou dict pour TypedDict/JSON-schema)
```

- **`AutoStrategy`** (schéma nu passé directement) → `ProviderStrategy` si le profile du modèle annonce le natif, sinon `ToolStrategy`. (Le schéma nu reste accepté malgré une doc affirmant le contraire.)
- **`ProviderStrategy`** — API native du provider (OpenAI, Anthropic, xAI/Grok, Gemini) : efficace, un appel, pas de tool synthétique. **`strict=` requiert `langchain ≥ 1.2`** (défaut `None`, honoré par **OpenAI et xAI**).
- **`ToolStrategy`** — injecte un tool synthétique dont les args = votre schéma, puis le force. Marche sur **tout** modèle tool-calling, supporte les `Union`, et c'est la **seule** stratégie avec `handle_errors` (boucle de réparation).

`handle_errors` (ToolStrategy) : `True` (catch-all + message par défaut) · `str` (message custom) · type(s) d'exception (filtre) · `Callable` (transforme) · `False` (propage). Sur échec de validation, l'erreur est renvoyée au modèle qui **réessaie**.

### 9.3 Volatilité de version (1.1–1.12) — épingler la version

Le structured output **agent-level** est genuinely fragile :
- **#35539** — `create_agent(response_format=...)` hardcode `tool_choice="any"` pour le tool de sortie ; Anthropic **rejette le forçage de tool quand l'extended thinking est activé** (`"Thinking may not be enabled when tool_choice forces tool use."`). Affecte `langchain` 1.1.x–1.2.10. **Contournement** : `model.with_structured_output(Result, method="anthropic_json_mode")` (natif, thinking-safe) ou descendre en LangGraph brut. (source : https://github.com/langchain-ai/langchain/issues/35539)
- **#34146** — en 1.1.0, `strict:true` était silencieusement retiré du bloc `json_schema` → vérifier qu'on est **≥ 1.2**. (source : https://github.com/langchain-ai/langchain/issues/34146)
- **#34463** — Gemini 3 retombe en `ToolStrategy` quand `tools` + `response_format` sont passés ensemble. Certains endpoints (Groq OpenAI-compat) **rejettent** `strict` (400) → ne pas activer en masse sur un pool hétérogène. (sources : https://github.com/langchain-ai/langchain/issues/34463 · #34155 · #35119)

**Guidance** : si la forme du plan final est la contrainte dure (cas UNDERSTAND), le chemin le plus robuste sur Anthropic est **`with_structured_output(Schema)` sur un modèle nu dans un étage Python déterministe** — moins de pièces mobiles, pas d'interaction `tool_choice`, pas de conflit thinking.

### 9.4 Pydantic v2 → JSON Schema (gotchas provider)

`model_json_schema()` n'est **pas** automatiquement strict-compatible. Ruptures silencieuses fréquentes :
- `Optional[x]` / défauts émettent une clé `default` → **non supportée** (OpenAI/Anthropic) ; la retirer.
- Modèles imbriqués via `$ref` n'héritent pas de `additionalProperties:false` → 400 OpenAI ; descendre dans `$defs` et forcer `additionalProperties:false` + `required` complet sur chaque objet.
- OpenAI exige **tous les props dans `required`** (rendre « optionnel » = union nullable, pas omission) ; contraintes numériques/longueur (`ge`/`le`/`min_length`) **ignorées par OpenAI, rejetées (400) par Anthropic** → les enlever du schéma envoyé, valider en `@field_validator`.
- Récursion : OK OpenAI, **fatale Anthropic**.

```python
def strictify(schema: dict) -> dict:                 # strictifieur minimal
    if schema.get("type") == "object" or "properties" in schema:
        schema["additionalProperties"] = False
        props = schema.get("properties", {})
        schema["required"] = list(props.keys())
        for sub in props.values(): strictify(sub)
    for key in ("$defs", "definitions"):
        for sub in schema.get(key, {}).values(): strictify(sub)
    if "items" in schema: strictify(schema["items"])
    for comb in ("anyOf", "allOf", "oneOf"):
        for sub in schema.get(comb, []): strictify(sub)
    schema.pop("default", None)
    return schema
```
(L'OpenAI SDK fournit `openai.lib._pydantic.to_strict_json_schema`.)

### 9.5 Échecs : distinguer **avant** de parser

| Cas | Signal | Action |
|---|---|---|
| Schéma valide | — | parser, fini |
| Schéma invalide *à la requête* (keyword/limite/`additionalProperties`) | **400** (jamais un corps dégradé) | corriger le schéma, pas le prompt |
| Refus de sûreté | HTTP **200**, `stop_reason:"refusal"` | brancher **avant** `json.loads` (pas un parse error) |
| Coupure `max_tokens` | HTTP 200, `stop_reason:"max_tokens"`, JSON tronqué | retry avec `max_tokens` plus haut |

Le constrained decoding (strict OpenAI/Anthropic) supprime les erreurs `JSON.parse` pour les réponses **bien formées**, mais **pas** les refus, coupures, ni les règles de *contenu* (`pattern`/range). Réparations hors natif (modèles sans constrained decoding) : `langchain_classic.output_parsers` — `OutputFixingParser` (renvoie prompt + sortie + erreur à un LLM) / `RetryOutputParser`. **Borner les boucles** (chaque réparation = un appel LLM de plus) ; pour un étage strict-critique latency-sensitive, préférer natif + **une** réparation bornée, puis échouer proprement (refus honnête).

### 9.6 Streaming de structured output

- `with_structured_output` + streaming : cible **dict** (TypedDict/JSON-schema) → **objets partiels** (toutes les clés parsées jusque-là) à chaque chunk ; cible **Pydantic** → résolu en fin (l'instance validée a besoin de l'objet complet).
- `JsonOutputParser` en streaming rend du JSON partiel progressif mais **lent** (re-parse le buffer accumulé à chaque token) → préférer un parser incrémental (SAX-style) pour du débit.
- Natif + streaming : deltas = texte ; la **garantie de validité ne tient que sur le message complet** → valider en fin de stream. `ProviderStrategy` (JSON natif) ne peut souvent **pas** appeler de tools ni émettre de préambule dans le même tour ; `ToolStrategy` contourne (le structured output *est* un tool call) — d'où le tool synthétique de `create_agent` quand des tools sont présents, et le conflit thinking Anthropic (§9.3). Planifier l'agent pour que le **tour structuré final** soit séparé des tours d'outils.

---

## 10. Quand utiliser quoi

| Besoin | Outil | Pourquoi |
|---|---|---|
| Pipeline linéaire (prompt → modèle → parse ; RAG retrieve-then-generate une fois) | **LCEL** (`a\|b\|c`) | Déclaratif ; streaming/async/batch/parallèle gratuits ; pas de boucle/branche |
| Agent : le modèle choisit les tools, itère vers une réponse | **`create_agent`** | Harness ReAct standard sur LangGraph ; middleware, structured output, mémoire, HITL inclus |
| Branches/boucles explicites, subgraphs parallèles, interrupts checkpointés, multi-agent, latence stricte, long-running | **LangGraph** (graphe à la main) | Contrôle impératif de l'état, cycles, edges conditionnels, exécution durable → `references/langgraph-v1.md` |

Règle : **`create_agent` pour la boucle ; `StateGraph` pour l'architecture.** Atteindre le middleware d'abord (couvre la plupart des « je veux customiser la boucle ») ; descendre en `StateGraph` quand c'est la *forme* du calcul qu'on conçoit.

---

## 11. Application Dataiku — les deux chemins

ChatGPT et le corpus concordent : un Code Agent qui code à la main un pipeline UNDERSTAND → RESOLVE → COMPOSE → QUERY → RENDER *construit le harness à la main* — même rôle que le middleware. Le vocabulaire `before_model`/`wrap_model_call`/`after_model` et `ProviderStrategy` vs `ToolStrategy`+`handle_errors` structure ces pipelines même **sans** importer LangChain. Séparer `context` (par-run : user id, project key) de `thread_id` (conversation) est un cadrage propre même si on persiste en SQL direct.

**Chemin A — code env 3.11.** Un Code Agent assigné à un code env 3.11 peut `import langchain`. Point d'entrée Dataiku propre : initialiser un modèle du LLM Mesh comme chat model LangChain via **`DKUChatModel`** (`from dataiku.langchain.dku_llm import DKUChatModel`), puis `create_agent(model=llm, tools=[...], system_prompt=...)`. Brancher tools Dataiku managés / custom / LangChain. (Signature `create_agent` et import `DKUChatModel` à confirmer contre la doc DSS — voir `references/dataiku-code-agents.md`.)

**Chemin B — contexte 3.9 (backend OWIsMind, 3.9.23).** **stdlib-only, aucun `import langchain`.** Appeler LLM Mesh / agents / tools via les APIs Dataiku natives directement : `llm.with_structured_output(PydanticModel)` ou `completion.with_json_output(schema, strict=...)` (structured output natif Mesh — supporté sur OpenAI / Azure OpenAI / Vertex Gemini ≥ DSS 13.3, expérimental HF, **« support varie » → vérifier la connexion réelle**). Faire la strictification du schéma + le branchement refus/coupure en Python pur. **Ne pas** tenter d'utiliser `create_agent` ici. (source : https://developer.dataiku.com/latest/api-reference/python/llm-mesh.html · https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/json-output/index.html)

---

## 12. Anti-patterns (rappel rapide ; détail → `references/anti-patterns-deprecations-versions.md`)

- Appeler `response.text()` — c'est une **propriété** : `response.text`.
- Importer chaînes/retrievers/`hub` legacy depuis `langchain` — déplacés vers `langchain-classic`.
- Utiliser `langgraph.prebuilt.create_react_agent` ou `AgentExecutor`/`initialize_agent` en code neuf — déprécié/legacy ; `prompt=` est devenu `system_prompt=`.
- Passer un Pydantic/dataclass comme `state_schema` — doit être un **TypedDict** (étendre `AgentState`).
- Confondre `with_structured_output` (modèle) et `response_format` (agent → `result["structured_response"]`).
- Oublier `tool_call_id` sur `ToolMessage`, ou `@hook_config(can_jump_to=[...])` avant un `jump_to`.
- Inverser l'ordre middleware (`after_*` tourne en **inverse**).
- Croire que `recursion_limit` vaut 1000 (**c'est 25**) ; ou que `astream_events` défaut à v3 (**c'est v2**).
- Traiter `gpt-5.5`/`gemini-3.5-flash` comme des ids confirmés (NON VÉRIFIÉS).
- **Importer langchain en contexte Python 3.9** (backend OWIsMind) — emprunter les *patterns*, pas la dépendance.

---

## 13. Sources canoniques

LangChain v1 agents : https://docs.langchain.com/oss/python/langchain/agents · `create_agent` ref : https://reference.langchain.com/python/langchain/agents/factory/create_agent · modèles/`init_chat_model` : https://docs.langchain.com/oss/python/langchain/models (+ https://reference.langchain.com/python/langchain/chat_models/init_chat_model) · messages/content blocks : https://docs.langchain.com/oss/python/langchain/messages · structured output : https://docs.langchain.com/oss/python/langchain/structured-output · middleware (hooks, ordre, `jump_to`) : https://docs.langchain.com/oss/python/langchain/middleware/custom · `ModelRequest` : https://reference.langchain.com/python/langchain/agents/middleware/types/ModelRequest · tools : https://docs.langchain.com/oss/python/langchain/tools · migration v1 : https://docs.langchain.com/oss/python/migrate/langchain-v1 · changelog : https://docs.langchain.com/oss/python/releases/changelog · 1.1 : https://changelog.langchain.com/announcements/langchain-1-1 · `astream_events` : https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/astream_events · Anthropic structured outputs / ids : https://platform.claude.com/docs/en/build-with-claude/structured-outputs · OpenAI structured outputs : https://developers.openai.com/api/docs/guides/structured-outputs · issues #35539 / #34146 / #34463 : https://github.com/langchain-ai/langchain/issues/35539 · Dataiku LLM Mesh : https://developer.dataiku.com/latest/api-reference/python/llm-mesh.html.
