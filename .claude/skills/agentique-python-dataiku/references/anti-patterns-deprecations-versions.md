# Anti-patterns, dépréciations & vérité des versions (2026)

> **À jour : juin 2026** — LangChain 1.x (core 1.4.7), LangGraph 1.x, Dataiku DSS 14.x.
> Ce fichier est la **couche d'autorité sur les versions** du skill : en cas de conflit avec un autre
> fichier `references/`, un tuto, un blog ou la mémoire du modèle, **ce fichier (et le re-check
> `gap-version-recency-recheck-2026.md`) gagne**. Parent : `SKILL.md`. Voir aussi `references/langchain-v1.md`,
> `references/langgraph-v1.md`, `references/orchestration-multi-agents.md`, `references/prompting-et-determinisme.md`.

Le danger n'est pas l'ignorance, c'est l'**obsolescence confiante** : les vieux tutos ReAct pré-v1, les
réponses de modèle entraînées sur 2024-2025, et même certains briefs de recherche affirment des signatures
et des défauts qui ont changé. Ce fichier liste (1) ce qui est **déprécié/déplacé**, (2) les **valeurs et
signatures à corriger**, (3) le **piège Python 3.9 vs 3.11**, (4) les **anti-patterns architecturaux**, puis
un **appendice de signatures et de versions vérifiées**.

---

## 1. Dépréciations & déplacements d'API (LangChain / LangGraph v1)

| Ancien (legacy / déprécié) | Statut juin 2026 | Voie actuelle | Source |
|---|---|---|---|
| `langgraph.prebuilt.create_react_agent(...)` | **Déprécié** en LangGraph v1 (shim d'import qui pointe vers `create_agent`) | `from langchain.agents import create_agent` | reference.langchain.com/python/langgraph.prebuilt/chat_agent_executor/create_react_agent |
| `AgentExecutor(...)` | **Legacy**, sorti du core en v1.0, **maintenance jusqu'à déc. 2026** | `create_agent` ; ou rester sur `pip install langchain-classic` (pas de fonctionnalité nouvelle) | reference.langchain.com/python/langchain-classic/agents/agent/AgentExecutor |
| `initialize_agent(...)`, agent types (`ZeroShotReAct`, …) | **Legacy**, déprécié depuis LangChain 0.2 (« critical fixes only ») | `create_agent` | focused.io/lab/a-practical-guide-for-migrating-classic-langchain-agents-to-langgraph |
| `pre_model_hook` / `post_model_hook` (params de `create_react_agent`) | **Remplacés** | middleware `@before_model` / `@after_model` (et `wrap_model_call`) | docs.langchain.com/oss/python/migrate/langgraph-v1 |
| `config["configurable"]` pour passer des **dépendances statiques** (deps figées du run) | **Anti-pattern** | **Runtime Context** : `context_schema=` + `invoke(..., context=...)`, lu via `runtime.context` | docs.langchain.com/oss/python/langchain/agents |
| Injection de dépendances « classique » dans un tool (closure / variable globale / `config`) | **Obsolète** | **`ToolRuntime`** : le tool reçoit `state`, `runtime.context`, `store`, `thread_id`, `run_id`, métadonnées | _ChatGPT source (concept) + docs.langchain.com/oss/python/langchain/tools_ |
| `MessageGraph` | **Supprimé** | `StateGraph` avec une clé `messages` | docs.langchain.com/oss/python/migrate/langgraph-v1 |
| `ValidationNode` | **Supprimé** | validation automatique des tools par `create_agent` | docs.langchain.com/oss/python/migrate/langgraph-v1 |
| `HumanInterruptConfig` | Renommé | `langchain.agents.middleware.human_in_the_loop.InterruptOnConfig` | docs.langchain.com/oss/python/migrate/langgraph-v1 |
| Chaînes/retrievers legacy (`LLMChain`, `ConversationChain`, `MultiQueryRetriever`, module `hub`, indexing API, `CacheBackedEmbeddings`, ré-exports `langchain-community`) | **Déplacés** | `langchain-classic` (maintenance déc. 2026) | docs.langchain.com/oss/python/migrate/langchain-v1 |

**Ce que `langchain` (core) expose encore** après la v1 (surface réduite) : `langchain.agents`
(`create_agent`, `AgentState`), `langchain.messages`, `langchain.tools` (`@tool`, `BaseTool`),
`langchain.chat_models` (`init_chat_model`), `langchain.embeddings` (`init_embeddings`).
(source : docs.langchain.com/oss/python/migrate/langchain-v1)

### Recettes de migration (les deux renames qui piègent le plus)

```python
# create_react_agent -> create_agent : changement de package ET de paramètre (prompt -> system_prompt)
# AVANT
from langgraph.prebuilt import create_react_agent
agent = create_react_agent(model, tools, prompt="You are a helpful assistant.")
# APRÈS
from langchain.agents import create_agent
agent = create_agent(model, tools, system_prompt="You are a helpful assistant.")
```

```python
# AgentExecutor -> create_agent : l'ancien intermediate_steps DEVIENT la liste de messages
# AVANT
from langchain.agents import AgentExecutor, create_tool_calling_agent
agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools, return_intermediate_steps=True)
out = executor.invoke({"input": "..."})
answer, steps = out["output"], out["intermediate_steps"]
# APRÈS
from langchain.agents import create_agent
agent = create_agent(llm, tools, system_prompt="...")
out = agent.invoke({"messages": [{"role": "user", "content": "..."}]})
answer = out["messages"][-1].content
# 'steps' == les paires AIMessage(tool_calls)/ToolMessage à l'intérieur de out["messages"]
```

> ⚠️ **Faux signal à ignorer** : la rumeur « `create_agent` n'existe plus dans `langchain.agents` en v1.1.0 »
> est **fausse** — c'était un venv périmé/cache, rétracté par le rapporteur ; `from langchain.agents import
> create_agent` marche dans un env v1.1.0 propre.
> (source : forum.langchain.com/t/create-agent-no-longer-exists-in-langchain-agents-v1-1-0/2350)

---

## 2. Vérité des versions — valeurs & signatures à corriger

Ces corrections **priment** sur tout brief, tuto ou réponse de modèle qui dirait le contraire.
(autorité : `agentic-research/gap-version-recency-recheck-2026.md`)

### 2.1 Valeurs par défaut souvent fausses

| Claim répandu (FAUX) | Valeur correcte | Détail |
|---|---|---|
| `recursion_limit` par défaut = **1000** | **25** | Dépasser → `GraphRecursionError: Recursion limit of 25 reached…`. Augmenter **par invocation**, jamais en changeant un défaut. |
| `astream_events(version="v3")` par défaut | défaut = **`v2`** | `v3` est **opt-in** et flaggé **expérimental** (protocole content-block) ; exige **LangChain ≥ 1.3** (livré le 2026-05-12). Rester sur `v2` sauf besoin précis. |
| `durability` par défaut = `"exit"` / `"sync"` | **`"async"`** | Modes (moins→plus durable) : `"exit"` (checkpoint en fin de run) · `"async"` (persistance asynchrone, défaut équilibré) · `"sync"` (avant chaque step, le plus durable). Le kwarg `durability=` sur `invoke`/`stream` vaut `None` → résout vers le mode du graphe. **Passer `durability=` explicitement** dans les exemples qui en dépendent. |

```python
# recursion_limit : le relever par run (PAS un défaut à 1000)
graph.invoke(inputs, config={"recursion_limit": 100})

# astream_events : rester sur v2 par défaut
async for ev in agent.astream_events(inp, version="v2"):
    ...

# durability : être explicite
graph.invoke(inputs, durability="sync")   # ou "async" (défaut) / "exit"
```

(sources : docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT ·
reference.langchain.com/python/langchain-core/runnables/base/Runnable/astream_events ·
docs.langchain.com/oss/python/langgraph/durable-execution · docs.langchain.com/oss/python/releases/changelog)

> **Conflit de corpus résolu.** Un brief affirmait `recursion_limit=1000 « depuis v1.0.6 »` — **erroné**,
> à barrer ; le défaut reste **25** (corroboré par le doc d'erreur officiel et plusieurs issues 2026).

### 2.2 Signatures à corriger

**`add_conditional_edges` — PAS de paramètre `then=`.**
```python
add_conditional_edges(
    self,
    source: str,
    path: Callable[..., Hashable | Sequence[Hashable]] | Runnable[...],
    path_map: dict[Hashable, str] | list[str] | None = None,
) -> Self
```
Tout code/tuto avec `then=...` décrit une forme **supprimée**. Mapper les retours du routeur via `path_map`.
(source : reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges)

**`@task` — le paramètre est `retry_policy`, pas `retry`.**
```python
from langgraph.func import task
@task(retry_policy=RetryPolicy(max_attempts=3))   # accepte 1 policy OU une séquence
def step(...): ...
# aussi de 1re classe : cache_policy=, timeout= (float | timedelta | TimeoutPolicy)
```
(source : reference.langchain.com/python/langgraph/func/task)

**`PostgresSaver.from_conn_string` — c'est un context-manager classmethod, et `.setup()` est requis.**
```python
from langgraph.checkpoint.postgres import PostgresSaver

with PostgresSaver.from_conn_string("postgresql://...") as checkpointer:  # signature: (conn_string, *, pipeline=False)
    checkpointer.setup()          # OBLIGATOIRE au 1er run (crée les tables de checkpoint)
    graph = builder.compile(checkpointer=checkpointer)
```
- `serde=` n'est **pas** un paramètre de `from_conn_string` — il vit sur `__init__(conn, pipe=None, serde=None)`.
- `pipeline=True` ouvre un `conn.pipeline()` psycopg ; sinon `None`.
- `AsyncPostgresSaver` est dans `langgraph.checkpoint.postgres.aio` (async CM). **Foot-gun historique** : un
  vieux bug forçait `pipeline=True` même indisponible (issue #2407) — vérifier la version installée de
  `langgraph-checkpoint-postgres` (ligne actuelle 1.0.x).
(sources : reference.langchain.com/python/langgraph.checkpoint.postgres/PostgresSaver ·
github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/langgraph/checkpoint/postgres/__init__.py)

**`ModelRequest` a `system_message` ET `system_prompt` ; muter via `request.override(...)`.**
Le dataclass de middleware d'agent porte (entre autres) `model`, `messages`, **`system_message`**
(`SystemMessage | None`), **`system_prompt`** (`str | None`), `tool_choice`, `tools`, `response_format`,
`state`, `runtime`, `model_settings`. `override(**overrides)` renvoie un **nouvel** objet (immuable, l'original
intact) :
```python
@wrap_model_call
def swap(request, handler):
    new_request = request.override(response_format=SimpleResponse, tools=request.tools[:2])
    return handler(new_request)
```
Les briefs qui ne listaient qu'un seul des deux champs système étaient incomplets.
(sources : reference.langchain.com/python/langchain/agents/middleware/types/ModelRequest · …/override)

### 2.3 Docs Anthropic — domaine canonique

`docs.anthropic.com` **301-redirige** vers **`platform.claude.com/docs`**. Mettre à jour tout lien
`docs.anthropic.com/...` → `platform.claude.com/docs/...`. (source : 301 vérifié en live)

---

## 3. Le piège Python 3.9 vs 3.11 (fait dur, à énoncer partout où la version compte)

**L'instance Dataiku a DEUX code environments : Python 3.9 ET Python 3.11.** LangChain/LangGraph v1
**exigent Python ≥ 3.10**. La décision dépend donc du **contexte d'exécution**, pas d'une préférence :

| Contexte | Python | `import langchain` / `langgraph` | Comment appeler le LLM / agent / tool |
|---|---|---|---|
| **Code Agent / recette sur code env 3.11** | 3.11 | ✅ **autorisé** (≥ 3.10) | `create_agent`, `StateGraph`, `DKUChatModel` *(import **UNVERIFIED** — voir ci-dessous)*, ou APIs Mesh natives |
| **Backend webapp OWIsMind** (et **tout** contexte 3.9) | **3.9.23** | ❌ **interdit** | **stdlib + `dataiku` uniquement** : `project.get_llm(id).new_completion()`, `project.get_agent_tool(id).run({...})` |

**Règle non négociable : ne JAMAIS recommander d'importer `langchain`/`langgraph` dans un contexte 3.9.**
Côté 3.9, on **emprunte les patterns** (boucle modèle-outils bornée, taxonomie de hooks, stratégies de
structured output, pare-feu d'honnêteté) — **pas la dépendance**. C'est exactement la posture des Code Agents
OWIsMind : fichier **standalone, stdlib + `dataiku` only**, jamais d'import du plugin, caps mirrorés
localement (cf. `references/dataiku-code-agents.md` et le pattern `get_agent_tool().run()` dans
`references/code-patterns-dataiku.md`).

> **Anti-pattern direct** : copier un starter `from dataiku.langchain.dku_llm import DKUChatModel` +
> `create_agent(...)` (proposé par la source ChatGPT) dans le **backend 3.9** → `import langchain` y est
> impossible. Ce starter n'est valide **que** dans un code env **3.11**. Présenter **toujours les deux
> chemins** quand la version compte.
> **⚠️ Chemin d'import `DKUChatModel` = UNVERIFIED** : `from dataiku.langchain.dku_llm import DKUChatModel`
> est un **import non confirmé contre la doc publique** — `gap-version-recency-recheck-2026.md` ne le valide
> pas, et le corpus le marque partout « à vérifier » (cf. `_chatgpt-source.md` « à VÉRIFIER contre la doc …
> import DKUChatModel » ; `gap-model-selection-routing-caching-fallbacks.md` « [GAP — verify] whether …
> DKUChatModel forwards … »). **Vérifier au runtime** (3.11) avant tout usage ; même statut que
> `project.get_semantic_model` (Appendice B). En cas de doute, préférer les **APIs Mesh natives** documentées.
> (autorité : correction utilisateur dans `_chatgpt-source.md` §CORRECTION UTILISATEUR ;
> docs.langchain.com/oss/python/migrate/langgraph-v1 ; observé : backend OWIsMind 3.9.23, `owismind-project-patterns.md`)

---

## 4. Anti-patterns architecturaux (les erreurs de conception, pas de version)

### 4.1 Boucles de framework cachées que tu ne contrôles pas → *own your control flow* (12-factor)

Confier le **control-flow** à une boucle implicite d'un framework (l'« agent magique » qui décide tout, étape
par étape) est le piège central de fiabilité : non-inspectable, non-testable, error-compounding sur N étapes.
Le principe **12-factor agents** « own your control flow » dit l'inverse : **tu** possèdes la boucle, le
framework n'est qu'une bibliothèque. Concrètement :

- `create_agent` reste un bon défaut **parce que** sa boucle est une `CompiledStateGraph` inspectable et que
  le middleware donne des points d'accroche explicites (`before/after_model`, `wrap_model_call`, `jump_to`).
- Dès que la **topologie** (branches, parallélisme, map-reduce, interruptions arbitraires, machine à états)
  est le sujet → **descendre en `StateGraph`** : *« `create_agent` pour la boucle, `StateGraph` pour
  l'architecture »* (cf. `references/langgraph-v1.md`).
- Côté Dataiku/3.9, l'équivalent validé est **explicite par construction** : pipeline UNDERSTAND → RESOLVE →
  COMPOSE → QUERY → RENDER où *« le LLM ne décide plus rien pendant l'exécution »* — du code déterministe
  pilote ; le LLM planifie **une fois** en JSON strict (cf. `references/orchestration-multi-agents.md`,
  `owismind-project-patterns.md` §0,1,10).

(sources : docs.langchain.com/oss/python/langgraph/workflows-agents ·
www.anthropic.com/research/building-effective-agents — *« only increase complexity when needed »* ;
12-factor-agents — *own your control flow*)

### 4.2 SQL généré par le LLM en autonomie

Laisser le modèle **écrire et exécuter du SQL libre** est à la fois un risque sécurité (LLM05 *Improper
Output Handling*, injection) **et** un défaut de fiabilité. Constat qualitatif robuste : **semantic
layer + templates déterministes ≫ SQL libre du LLM**. Les chiffres avancés (~98-100 % vs 84-90 %)
proviennent de la **note de recherche interne au projet** (`owismind-project-patterns.md` §3,4) ; ils
**ne sont pas adossés à un benchmark NL2SQL externe** (pas d'URL de papier/leaderboard public ici) —
à traiter comme indicatifs, pas comme une mesure publiée. Donc :

- SQL **owned par le code** (templates gelés par intent) ou **owned par le Semantic Model Query tool** ; le
  LLM ne touche au SQL que sur l'intent `custom` (la longue traîne), **et** sous garde dure.
- **Garde de défense en profondeur** au-dessus du read-only DB : une seule instruction, doit démarrer par
  `SELECT`/`WITH`, **aucun** DML/DDL, **une** table whitelistée, `LIMIT` imposé et plafonné, **`EXPLAIN`
  dry-run + ≤ 2 réparations** en re-feedant l'erreur DB au LLM.
- **Exécution read-only enforcée hors du modèle** (Postgres) :
  ```sql
  SET LOCAL statement_timeout TO '30000';
  SET LOCAL transaction_read_only TO on;
  ```
- **Output du modèle = entrée non fiable** : jamais d'`eval`/`exec`, jamais d'interpolation de texte LLM dans
  une string SQL — requêtes paramétrées (Dataiku : `dataiku.sql.Constant`/`toSQL`).

(sources : owismind-project-patterns.md §3,4 · genai.owasp.org/llmrisk/llm01-prompt-injection ·
cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html)

### 4.3 « Règles par bug » (patch valeur-par-valeur)

Hardcoder une **valeur métier** dans la logique d'un agent pour rattraper un cas qui échoue. Interdit
(mandat utilisateur explicite, P3). À la place :

- Compréhension LLM **contrainte à une liste de candidats** (enums ancrés sur le **profil**, dérivé des
  données), ou **refus honnête** — jamais un patch par valeur.
- Les stopwords, le scénario par défaut (« gap vs budget »), les synonymes : **dérivés du profil**, pas
  écrits en dur.
- Quand un invariant métier doit être asserté, il vit dans un **test anti-drift** (qui importe la constante
  source, ex. `KNOWN_PHASES`/`KNOWN_TOOL_NAMES`/`KNOWN_BLOCK_IDS`), **pas** dans la logique de l'agent.

(source : owismind-project-patterns.md §6 ; CLAUDE.md/CONTEXT.md P3)

### 4.4 Routeur/orchestrateur qui **authore un fait métier** (pare-feu d'honnêteté)

Le bug central confirmé sur 817 questions réelles : l'orchestrateur **niait ou inventait au lieu de router**
(« budget 2026 » → « I don't have budget data » **sans appeler** l'agent qui lit pourtant un `Phase` =
`BUDGET`). Cause racine : les règles d'honnêteté interdisaient le **sur**-engagement mais pas le
**sous**-engagement.

- Le routeur **n'émet JAMAIS un fait métier**. Le seul « non » permis est **« je n'ai pas d'agent pour ce
  DOMAINE »** (`CAPABILITY_GAP`) — jamais « la donnée n'existe pas » (ça, c'est l'appel de l'expert via
  `out_of_scope`/`no_data`). **Dans le doute → router.**
- Les intents non-business (`CAPABILITY_GAP`, `OUT_OF_SCOPE`, `CONCEPT`) sont des **templates déterministes**,
  pas de la prose libre (la prose libre est l'endroit où le fait métier halluciné fuit).
- Un domaine devient « staffé » **automatiquement** quand un agent enabled le déclare → ajouter un agent
  ferme le gap **sans toucher au prompt**.

(source : owismind-project-patterns.md §2 ; détail dans `references/orchestration-multi-agents.md`)

### 4.5 `async` dans un contexte Python 3.9 (et autres pièges de boucle)

- **`async`/`await` agentique exige le runtime ≥ 3.10** : pas d'`ainvoke`/`astream`/`aprocess` LangChain
  côté **3.9**. Le parallélisme y passe par `threading`/`queue.Queue` borné, pas par `asyncio.gather` sur du
  langchain. (Le fan-out v3 OWIsMind utilise un **thread pool borné** `MAX_PARALLEL_AGENTS=3`, workers qui ne
  touchent ni la trace ni l'usage ni `yield` — tout l'accumulation se fait sur le **main thread**, car
  `SpanBuilder`/usage **ne sont pas supposés thread-safe**.)
- **Jamais de `while True` non borné** dans une boucle agentique hand-roll : toujours un `max_iterations` +
  un deadline wall-clock. (Le `while True` des tutos Dataiku **doit** être plafonné en prod.)
- **`stop_reason` toujours vérifié** : `tool_use` (exécuter, reboucler) · `max_tokens` (si le dernier bloc
  est un `tool_use` **incomplet**, retry avec `max_tokens` plus haut) · `pause_turn` (renvoyer la réponse
  telle quelle) · `refusal` (renvoyé en **HTTP 200**, pas une erreur).
- Ne **jamais** ajouter un bloc texte **après** un `tool_result` (Claude apprend à finir son tour trop tôt →
  réponses `end_turn` vides).
- **Retries** : seulement 429 / 5xx / **529** (overload Anthropic) ; backoff exponentiel + jitter ; honorer
  `Retry-After` ; **jamais** retry sur une erreur de validation 4xx.
- **Idempotence** : tout tool à effet de bord accepte une **idempotency key** ; checkpoint **avant** les
  effets de bord (un nœud peut être réexécuté depuis le début après reprise — checkpoints aux frontières de
  super-step).

(sources : owismind-project-patterns.md §8 ·
platform.claude.com/docs/en/build-with-claude/handling-stop-reasons ·
docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT ·
www.langchain.com/blog/fault-tolerance-in-langgraph)

### 4.6 Petits anti-patterns LangChain v1 (à connaître)

- ❌ Passer `prompt=` à `create_agent` → le paramètre est **`system_prompt`**.
- ❌ Lire `result["intermediate_steps"]` → lire **`result["messages"]`**.
- ❌ Supposer que `tools` + `response_format` se comporte **identiquement** chez tous les providers → **tester
  le modèle exact** (issues de fallback `ToolStrategy` sur certaines configs Gemini 3 / frictions 1.0.x).
- ❌ Se tromper d'**ordre de middleware** : `before_*` en ordre de déclaration, **`after_*` en ordre inverse**,
  `wrap_*` en oignon (le 1er est le plus externe).
- ❌ Oublier `@hook_config(can_jump_to=[...])` avant de renvoyer `jump_to`.

(source : langchain-agents-create-agent.md §10 ; détail dans `references/langchain-v1.md`)

---

## 5. Appendice A — signatures vérifiées (verbatim, juin 2026)

> Toutes **CONFIRMÉES** contre la doc/le source live (cf. `gap-version-recency-recheck-2026.md` §2).

```python
# init_chat_model
init_chat_model(
    model: str | None = None, *,
    model_provider: str | None = None,
    configurable_fields: Literal['any'] | list[str] | tuple[str, ...] | None = None,
    config_prefix: str | None = None,
    **kwargs: Any,
) -> BaseChatModel | _ConfigurableModel

# create_agent (langchain.agents) — paramètre = system_prompt (PAS prompt)
create_agent(
    model: str | BaseChatModel,
    tools: Sequence[BaseTool | Callable | dict] | None = None, *,
    system_prompt: str | SystemMessage | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    response_format: ... | None = None,
    state_schema: type[AgentState] | None = None,
    context_schema: type | None = None,        # Runtime Context (deps de run), PAS config["configurable"]
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    interrupt_before: list[str] | None = None,
    interrupt_after: list[str] | None = None,
    debug: bool = False, name: str | None = None,
    cache: BaseCache | None = None,
    transformers: Sequence[TransformerFactory] | None = None,
) -> CompiledStateGraph

# add_conditional_edges — AUCUN then=
add_conditional_edges(self, source: str, path: Callable | Runnable,
                      path_map: dict | list[str] | None = None) -> Self

# @task — retry_policy (PAS retry)
task(__func_or_none__=None, *, name=None,
     retry_policy: RetryPolicy | Sequence[RetryPolicy] | None = None,
     cache_policy=None, timeout: float | timedelta | TimeoutPolicy | None = None, **kwargs)

# astream_events — défaut v2
astream_events(self, input, config=None, *,
               version: Literal['v1','v2','v3'] = 'v2', ...) -> AsyncIterator[StreamEvent] | Awaitable

# PostgresSaver.from_conn_string — context manager, serde NON présent ici
PostgresSaver.from_conn_string(cls, conn_string: str, *, pipeline: bool = False) -> Iterator[PostgresSaver]
PostgresSaver.__init__(self, conn, pipe: Pipeline | None = None, serde: SerializerProtocol | None = None)
# -> appeler .setup() une fois avant compile(checkpointer=...)

# Dataiku BaseLLM (custom LLM / code agent) — réponse = dict littéral, clé requise "text"
from dataiku.llm.python import BaseLLM
class MyLLM(BaseLLM):
    def process(self, query: "SingleCompletionQuery", settings: "CompletionSettings",
                trace: "SpanBuilder") -> "CompletionResponse":
        ...
        return {"text": resp, "promptTokens": 46, "completionTokens": 10,
                "estimatedCost": 0.13, "toolCalls": []}   # tout sauf "text" est optionnel
    # variantes : aprocess, process_stream (générateur de chunks), aprocess_stream
```

(sources : reference.langchain.com/python/langchain · …/langgraph · …/langgraph.checkpoint.postgres ·
developer.dataiku.com/latest/tutorials/plugins/agent/generality/index.html)

---

## 6. Appendice B — carte des versions & dates (juin 2026)

| Élément | Version / date | Statut | Source |
|---|---|---|---|
| `langchain-core` | **1.4.7** (2026-06-12) | dernière | pypi.org/project/langchain-core |
| LangChain 1.0 (GA) | **2025-10-22** | stable (pas de breaking avant 2.0) | changelog.langchain.com/announcements/langchain-1-0-now-generally-available |
| LangChain 1.1 | **2025-12-02** *(non recoupé par `gap-version-recency-recheck-2026.md`)* | `SystemMessage` system prompt, model profiles, ModelRetry/Content-Moderation middleware — **date/features non cross-checkées par l'autorité** (qui ne date que GA 1.0 2025-10-22, 1.2.0 2025-12-15, 1.3.0 2026-05-12) ; source inline propre, **à confirmer sur le changelog live** | changelog.langchain.com/announcements/langchain-1-1 |
| LangChain 1.2 | **2025-12-15** | `extras` sur tools (provider tools), `ProviderStrategy` strict | docs.langchain.com/oss/python/releases/changelog |
| LangChain 1.3 | **2026-05-12** | `version="v3"` pour `stream_events`/`astream_events` (opt-in) | docs.langchain.com/oss/python/releases/changelog |
| `AgentExecutor`/`initialize_agent` | **maintenance jusqu'à déc. 2026** | legacy (`langchain-classic`) | focused.io/lab/...migrating-classic-langchain-agents-to-langgraph |
| Dataiku — Local MCP | **14.2.0** (2025-10-17 ; agent-tool en 14.2.1+) | dispo | doc.dataiku.com/dss/latest/release_notes/14.html |
| Dataiku — Semantic Models | **14.4.0** (2026-02-09) | dispo | doc.dataiku.com/dss/latest/release_notes/14.html |
| Dataiku — Extract structured fields | **14.5.0** (2026-04-14 ; résolution screenshot configurable 14.5.2) | dispo | doc.dataiku.com/dss/latest/release_notes/14.html |
| `project.get_semantic_model(id)` + `get_raw()`/`save()`/`versions` | **UNVERIFIED** (mémoire projet) | confirmer au runtime (`dir(project)` / introspect `dataikuapi`) ; **ne pas citer comme documenté** | github.com/dataiku/dataiku-api-client-python — pas de `get_semantic_model` dans la ref publique |

---

## 7. Appendice C — modèles & pricing providers

### Anthropic (CONFIRMÉ — exact ids, pas de suffixe date sur les alias)

| Modèle | Model ID (exact) | Contexte | Input $/1M | Output $/1M |
|---|---|---|---|---|
| Claude Opus 4.8 | `claude-opus-4-8` | **1M** | 5.00 | 25.00 |
| Claude Opus 4.7 | `claude-opus-4-7` | 1M | 5.00 | 25.00 |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | **1M** | 3.00 | 15.00 |
| Claude Haiku 4.5 | `claude-haiku-4-5` (`…-20251001`) | 200K | 1.00 | 5.00 |
| Claude Fable 5 | `claude-fable-5` | 1M | 10.00 | 50.00 |

- `claude-opus-4-8` / `claude-sonnet-4-6` / `claude-haiku-4-5` sont **réels et courants** — ce ne sont **pas**
  des placeholders. **Garder les strings exactes.** 1M de contexte sur Opus 4.8/4.7 et Sonnet 4.6 **sans
  surcharge long-context** (pricing standard). Haiku = 200K. Alias **sans suffixe date** (sauf Haiku, dont
  l'id complet est daté).
- **Recency flags Anthropic** (impactent la conception agent) :
  - **Prefill du dernier message assistant → 400** sur Opus 4.6/4.7/4.8, Sonnet 4.6, Fable 5. Remplacer par
    structured outputs (`output_config.format`) ou une consigne système.
  - `thinking: {type:"enabled", budget_tokens:N}` **supprimé (400)** sur Opus 4.7/4.8 & Fable 5, **déprécié**
    sur Opus 4.6/Sonnet 4.6 → `thinking: {type:"adaptive"}` + `output_config:{effort: low|medium|high|xhigh|max}`
    (`xhigh` dès 4.7 ; `max` = tier Opus + Sonnet 4.6, pas Haiku). `temperature`/`top_p`/`top_k` → 400 sur
    4.7/4.8/Fable 5.
  - `thinking.display` par défaut `"omitted"` sur Opus 4.7/4.8/Fable 5 → mettre `"summarized"` pour exposer le
    raisonnement.

(sources : skill `claude-api` bundled · cloudzero.com/blog/claude-api-pricing · platform.claude.com/docs/en/about-claude/models/overview)

### Non-Anthropic — **UNVERIFIED**, à flagger

- **`gpt-5.5`** (OpenAI) et **`gemini-3.5-flash`** (Google) apparaissent dans des exemples de corpus mais
  **n'ont pas été vérifiés** ici (hors périmètre de la source Anthropic). **Les confirmer côté
  OpenAI/Google avant tout usage en prod.** Dans les exemples de ce skill, les traiter comme **illustratifs**,
  non comme des ids garantis.

(source : gap-version-recency-recheck-2026.md §5)

---

## 8. Réconciliation corpus ↔ ChatGPT (qui gagne sur quoi)

| Sujet | Accord ? | Tranchage |
|---|---|---|
| `create_react_agent` déprécié → `create_agent` ; partir des APIs v1 | **Accord** | Énoncé tel quel. |
| Taxonomie Dataiku (Simple/Structured **Visual** Agents, **Code Agents**, agent = « Virtual LLM » du LLM Mesh) | ChatGPT apporte la structure | **Garder** le cadrage conceptuel ChatGPT (utile, cohérent avec la doc). |
| Signatures / valeurs par défaut / versions | Conflits ponctuels | **Corpus + recency file gagnent** (§2, §5, §6). |
| Starter `DKUChatModel + create_agent` | ChatGPT le donne « à vérifier » | **Valide uniquement en code env 3.11** ; **interdit en 3.9** (§3). |
| Jetons `citeturn…` de la source ChatGPT | — | **Ignorer comme URLs** ; sourcer via les URLs réelles du corpus. |

---

## TL;DR — les 10 corrections à retenir

1. `create_react_agent` **déprécié** → `langchain.agents.create_agent` ; `AgentExecutor`/`initialize_agent` → `langchain-classic` (déc. 2026).
2. `recursion_limit` défaut = **25** (pas 1000) ; relever via `config={"recursion_limit": N}`.
3. `astream_events` défaut = **`v2`** ; `v3` opt-in/expérimental, ≥ LangChain 1.3.
4. `durability` défaut = **`"async"`** ; le passer explicitement.
5. `add_conditional_edges` **sans `then=`** : `(source, path, path_map=None)`.
6. `@task(retry_policy=…)` (pas `retry`) ; `PostgresSaver.from_conn_string(conn, *, pipeline=False)` + **`.setup()`**.
7. `ModelRequest` a **`system_message` ET `system_prompt`** ; muter via `request.override(...)`.
8. **Python 3.9 = stdlib-only, AUCUN `import langchain`** ; v1 seulement en code env **3.11**. Toujours présenter les **deux chemins**.
9. Anti-patterns : boucle de framework cachée (own your control flow) · SQL LLM autonome · règles-par-bug · routeur qui authore un fait métier · `async` en 3.9.
10. `claude-opus-4-8`/`claude-sonnet-4-6`/`claude-haiku-4-5` **réels** ; `gpt-5.5`/`gemini-3.5-flash` **UNVERIFIED**. `docs.anthropic.com` → `platform.claude.com/docs`.
