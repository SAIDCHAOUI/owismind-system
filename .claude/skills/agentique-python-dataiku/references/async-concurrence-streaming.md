# Async, concurrence & streaming (y compris Python < 3.11 et vers un frontend)

> **À jour : juin 2026.** Baseline : LangChain 1.x (`langchain` 1.3.x, `langchain-core` 1.4.7 du 2026-06-12), LangGraph 1.x (GA 2025-10-22), Dataiku DSS 14.x. Fichier de référence du skill `agentique-python-dataiku` ; le parent `SKILL.md` décide *quand* descendre à ce niveau. Voisins cités par nom : `references/langgraph-v1.md` (state/reducers/Command/Send/subgraphs), `references/langchain-v1.md` (`create_agent`, middleware), `references/memoire-persistance-hitl.md` (checkpointers, durabilité), `references/orchestration-multi-agents.md` (fan-out de sous-agents), `references/dataiku-code-agents.md` (LLM Mesh, Code Agent, `DKUChatModel`).

Ce fichier traite du **modèle de programmation concurrent** des agents codés : sync vs async, parallélisme réel (fan-out, `Send` map-reduce, tool calls parallèles), bornage de la concurrence, gestion des 429/backpressure, thread-safety et idempotence sous retry, les **pièges async de Python < 3.11**, puis le **streaming vers un frontend web** (SSE vs polling-via-thread, taxonomie d'événements, patterns Flask/ASGI, annulation, footer d'usage).

## 0. Le double chemin Python — fait dur à garder en tête partout

L'instance Dataiku possède **deux code environments : Python 3.9 ET Python 3.11**. Cette dualité commande tout ce document.

| Contexte | Interpréteur | Règle |
|---|---|---|
| **Code Agent** affecté à un code env **3.11** (≥ 3.10) | 3.11 | Peut importer `langchain` / `langgraph` 1.x. Tout l'API LangGraph ci-dessous est utilisable, **y compris l'async sans caveat**. |
| **Backend webapp OWIsMind** (`python-lib/owismind`, Flask DSS) | **3.9.23** | **stdlib-only, AUCUN import langchain/langgraph.** Appeler LLM Mesh / agents / tools via les **APIs Dataiku natives** (`project.get_llm(...).new_completion().execute_streamed()`, `get_agent_tool().run()`). |

LangChain/LangGraph 1.x exigent **Python ≥ 3.10** (3.9 EOL oct. 2025) — ils ne s'installent pas dans l'interpréteur 3.9 (https://docs.langchain.com/oss/python/migrate/langgraph-v1). **Ne jamais recommander d'importer langchain en contexte 3.9.** Les §1–7 décrivent le modèle LangGraph (chemin 3.11) ; les §3 (caveats <3.11) et §8–14 (streaming) couvrent à la fois 3.11-en-async et la réalité 3.9-stdlib d'OWIsMind, qui n'utilise pas LangGraph du tout et obtient le **même contrat consommateur** via une boucle écrite à la main (§13).

## 1. Table de décision

| Vous voulez… | Utilisez | Caveat Python 3.9 (contexte backend) |
|---|---|---|
| Parallélisme I/O réel (sous-agents / appels LLM) | nœuds `async def` + `await graph.ainvoke/astream`, ou `asyncio.gather` dans un nœud | passer `config` manuellement à chaque `await model.ainvoke(...)` (3.11 en async aussi) |
| Map-reduce / fan-out dynamique sur une liste | API `Send` depuis une conditional edge | la clé d'état cible **doit** avoir un reducer sinon `InvalidUpdateError` |
| Borner le nombre de branches simultanées | `config={"max_concurrency": N}` (graphe) ou `asyncio.Semaphore` (in-node) | marche aussi en sync via le thread pool de workers |
| Événements streamés custom | **paramètre** `writer: StreamWriter` | `get_stream_writer()` **ne marche pas** en async < 3.11 — utiliser le paramètre |
| Éviter les 429 proactivement | `InMemoryRateLimiter` sur le modèle (RPM) + votre propre bucket TPM | limiter = requêtes/s seulement, mono-process |
| Récupérer d'un 429/5xx transitoire | `max_retries` modèle (auto) + `RetryPolicy` nœud | rendre les nœuds **idempotents** — le retry rejoue tout le nœud |
| Exécuter du code bloquant dans un graphe async | `await asyncio.to_thread(fn, ...)` | ne jamais appeler une fn bloquante directement dans un nœud async |
| Rester 100 % sync (style DSS / 3.9) | graphe/boucle sync + worker thread + polling | **le pattern OWIsMind** ; voir §11–13 |

## 2. Sync vs async : surfaces symétriques

Tout graphe compilé (et tout `@entrypoint`/objet Pregel) expose un quadruplet sync/async : `invoke`/`ainvoke`, `stream`/`astream` (+ `astream_events`). Pour passer en async : (a) nœuds `async def`, (b) `await` sur l'I/O, (c) appeler `ainvoke`/`astream` (https://docs.langchain.com/oss/python/langgraph/use-graph-api).

```python
result = graph.invoke({"topic": "ice cream"})                  # sync, bloque le thread
result = await graph.ainvoke({"topic": "ice cream"})           # async, même graphe
async for chunk in graph.astream({"topic": "ice cream"}, stream_mode="updates"):
    ...
```

**Quand l'async donne-t-il du *vrai* parallélisme ?** LangGraph parallélise les nœuds d'un **même superstep** (fan-out). Pour que ça se traduise en I/O concurrente, le travail doit céder la boucle (`async`/`await`) ou être déporté. Avec des nœuds **sync**, LangGraph exécute quand même les nœuds d'un même superstep "en parallèle", mais sur un **thread pool** : le CPU-bound reste sérialisé par le GIL, seul l'I/O qui libère le GIL se recouvre. Les gros gains viennent du code async I/O-bound (requêtes concurrentes vers un provider) (https://docs.langchain.com/oss/python/langgraph/use-graph-api).

**Ne jamais appeler une fonction bloquante directement dans un nœud `async def`** — elle gèle la boucle. Déporter :

```python
async def query_dataset(state, config):
    rows = await asyncio.to_thread(run_blocking_sql, state["sql"])   # SQLExecutor2 bloquant -> thread
    return {"rows": rows}
```

Fan-out manuel dans **un seul nœud** via `asyncio.gather` (à coupler avec un `Semaphore`, §5.2) ; pour des sous-appels bloquants, envelopper chacun dans `asyncio.to_thread` pour que `gather` les recouvre vraiment :

```python
async def fan_out_subagents(state, config):
    async def one(sub):
        return await sub_agent.ainvoke({"input": sub}, config)       # passer config (cf. §3)
    results = await asyncio.gather(*(one(s) for s in state["subjects"]))
    return {"answers": results}
```

## 3. Fan-out, `Send` map-reduce & l'exigence de reducer (le footgun n°1)

### 3.1 Fan-out/fan-in statique (supersteps)

Les edges divergentes créent un fan-out, les convergentes un fan-in ; les nœuds d'un même superstep tournent ensemble. **Toute clé d'état écrite par plusieurs nœuds parallèles doit déclarer un reducer**, sinon LangGraph ne sait pas fusionner.

```python
import operator
from typing import Annotated
from typing_extensions import TypedDict

class State(TypedDict):
    aggregate: Annotated[list, operator.add]   # reducer => append-only, parallel-safe
```

### 3.2 API `Send` pour le map-reduce dynamique

Quand le nombre de tâches parallèles n'est connu qu'au runtime, retourner depuis une **conditional edge** une liste de `Send(node_name, private_state)` ; chaque `Send` instancie le nœud cible avec son input scopé, et les sorties refusionnent par le reducer. Rappel signature (recency 2026) : `add_conditional_edges(source, path, path_map=None)` — **pas de paramètre `then=`** (https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges).

```python
from langgraph.types import Send

def continue_to_jokes(state):                       # conditional edge => map step
    return [Send("generate_joke", {"subject": s}) for s in state["subjects"]]

def generate_joke(state):                            # une instance par Send, en parallèle
    return {"jokes": [make_joke(state["subject"])]}  # 'jokes' a besoin d'un reducer operator.add

builder.add_conditional_edges("generate_topics", continue_to_jokes, ["generate_joke"])
```

(https://docs.langchain.com/oss/python/langgraph/use-graph-api — voir aussi `references/orchestration-multi-agents.md` et `references/langgraph-v1.md` pour `Send`/`Command`.)

### 3.3 `InvalidUpdateError` / `INVALID_CONCURRENT_GRAPH_UPDATE`

> "If multiple nodes in e.g. a fanout within a single step return values for `'some_key'`, the graph will throw this error because there is uncertainty around how to update the internal state." (https://docs.langchain.com/oss/python/langgraph/errors/INVALID_CONCURRENT_GRAPH_UPDATE)

Message runtime verbatim : `langgraph.errors.InvalidUpdateError: Can receive only one value per step. Use an Annotated key to handle multiple values.` (https://github.com/langchain-ai/langgraph/issues/2336)

```python
class State(TypedDict):
    result: str                            # CASSÉ : deux nœuds parallèles écrivent 'result' -> InvalidUpdateError

class State(TypedDict):
    result: Annotated[list, operator.add]  # CORRIGÉ : reducer => écritures concurrentes fusionnées
```

Cela mord aussi les **retries en parallèle** : un nœud qui retry dans un superstep peut produire une 2ᵉ écriture sur une clé non réduite (issue #2336).

### 3.4 Ordre des écritures concurrentes : déterministe, pas arbitraire

Les branches parallèles ne fusionnent **pas** dans l'ordre d'arrivée : LangGraph applique les écritures dans un **ordre déterministe** (tri des pending writes), donc replays/reprises sont reproductibles. Concevez le reducer **commutatif/associatif** (`operator.add` sur listes, union d'ensembles, `max`) pour ne jamais dépendre de "qui a fini en premier" (https://medium.com/@gmurro/parallel-nodes-in-langgraph-managing-concurrent-branches-with-the-deferred-execution-d7e94d03ef78).

### 3.5 Fan-in différé pour branches inégales (`defer=True`)

Si les branches ont des longueurs différentes et que l'agrégateur doit attendre **toutes** :

```python
builder.add_node("aggregate", aggregate, defer=True)   # attend toutes les branches pendantes
```

### 3.6 Supersteps transactionnels (tout-ou-rien)

> "While parallel branches are executed in parallel, the entire superstep is **transactional**. If any of these branches raises an exception, **none** of the updates are applied to the state." (https://docs.langchain.com/oss/python/langgraph/use-graph-api)

Conséquence : une branche en échec annule tout le superstep ; au resume, le superstep se ré-exécute. D'où l'exigence d'idempotence (§7) et le `RetryPolicy` par nœud (§5.3).

### 3.7 Exécution parallèle des tools (`ToolNode`)

Le `ToolNode` prébuilt exécute **tous les tool calls d'un même tour LLM en parallèle** via `asyncio.gather` (https://github.com/langchain-ai/langgraph/blob/main/libs/prebuilt/langgraph/prebuilt/tool_node.py). Deux pièges :

1. **Aucun ordre de complétion garanti** — dangereux pour les tools à effet de bord (écritures DB, actions navigateur). Si l'ordre compte, exécuter séquentiellement dans un nœud custom (https://github.com/langchain-ai/langgraphjs/issues/861).
2. **Interrupts perdus** — le premier `GraphInterrupt` qui propage peut annuler les autres coroutines ou perdre leurs interrupts (https://github.com/langchain-ai/langgraph/issues/6624). Pertinent si vous mêlez HITL et tools parallèles.

Supprimer le parallélisme côté provider : `bind_tools(..., parallel_tool_calls=False)`. Note v1 : `create_react_agent` est **déprécié** (→ `langchain.agents.create_agent`) ; son ancien paramètre `version="v2"` dispatchait déjà chaque tool call via `Send`. Voir `references/anti-patterns-deprecations-versions.md`.

## 4. Caveats async Python < 3.11 (verbatim — s'appliquent au 3.9.23, **et au 3.11 dès qu'on est async**)

Avant Python 3.11, les tâches `asyncio` **ne copient pas le `contextvars` parent** dans les tâches enfant. LangGraph/LangChain propagent `RunnableConfig` (callbacks, stream writer, run tree) via un `ContextVar` ; en 3.9/3.10 ce contexte est **perdu à la frontière `await`**, donc callbacks/streaming cassent silencieusement sauf propagation manuelle (https://docs.langchain.com/oss/python/langgraph/streaming).

> Ces caveats ne concernent **que le chemin 3.11-en-async** (un Code Agent qui importe LangGraph et écrit des nœuds `async def`). En **3.9 backend**, on n'importe pas LangGraph : on est soit en boucle sync, soit en thread (§11) — pas de propagation de `ContextVar` à gérer.

### 4.1 Caveat A — passer `RunnableConfig` à la main

> "You **must** explicitly pass `RunnableConfig` into async LLM calls (e.g. `ainvoke()`), as callbacks are not automatically propagated."

```python
async def call_model(state, config):                 # accepter config
    response = await model.ainvoke(
        [{"role": "user", "content": f"Write a joke about {state['topic']}"}],
        config,                                       # explicite ; requis < 3.11
    )
    return {"messages": response}
```

Sans `config`, le token streaming / `astream_events` / le tracing LangSmith de cet appel ne font rien.

### 4.2 Caveat B — `get_stream_writer()` cassé ; utiliser le paramètre `writer`

> "In async code running on Python < 3.11, `get_stream_writer` will not work." Déclarer un **paramètre** `writer: StreamWriter` (lu depuis la config, pas un ContextVar) :

```python
from langgraph.types import StreamWriter

async def generate(state, writer: StreamWriter):     # paramètre injecté, marche en 3.9
    writer({"custom_key": "Streaming custom data"})  # surface dans stream_mode="custom"
    return {"joke": f"This is a joke about {state['topic']}"}
```

En 3.11+ vous pouvez utiliser `from langgraph.config import get_stream_writer` à l'intérieur du nœud. **Nuance** : même en 3.9, si l'agent tourne **en synchrone** (pas de `async def`), `get_stream_writer()` fonctionne — la restriction est spécifique à *async-sur-<3.11*.

### 4.3 Caveat C — API fonctionnelle async (`@task`/`@entrypoint`) exige Python 3.11+

> "To use `async` functions, ensure that you are using **Python 3.11 or higher**." (https://docs.langchain.com/oss/python/langgraph/functional-api)

`@task` renvoie un future, d'où un parallélisme facile — mais 3.11+ seulement. Signature 2026 : le paramètre est **`retry_policy`** (single ou séquence), plus `cache_policy` / `timeout` (https://reference.langchain.com/python/langgraph/func/task). **En 3.9 : ne pas utiliser `@task`/`@entrypoint` async** ; préférer le fan-out `Send` (§3.2), `asyncio.gather` (§2), ou le thread pool (§11).

## 5. Rate limiting, 429 & backpressure sous concurrence

Trois couches indépendantes ; utilisez-les ensemble pour un agent qui fan-out contre un gateway partagé (LLM Mesh). Sert directement la **règle 2 de CLAUDE.md** (rien de risqué/lent/surchargeant).

### 5.1 Couche 1 — limiteur client proactif (`InMemoryRateLimiter`)

Token-bucket attaché au modèle ; **bloque** jusqu'à disponibilité d'un jeton, donc plafonne le RPM sortant *avant* le provider.

```python
from langchain_core.rate_limiters import InMemoryRateLimiter
rate_limiter = InMemoryRateLimiter(
    requests_per_second=0.1,   # 1 req / 10 s — PAS des tokens LLM
    check_every_n_seconds=0.1,
    max_bucket_size=10,        # burst max
)
model = init_chat_model("claude-sonnet-4-6", model_provider="anthropic", rate_limiter=rate_limiter)
```

Limitations dures (verbatim, https://reference.langchain.com/python/langchain-core/rate_limiters/InMemoryRateLimiter) :
- token bucket : 1 jeton/requête ; **jetons ≠ tokens LLM**.
- limite **requêtes/temps seulement** → ne fait **pas** de TPM.
- **mono-process** : ne limite pas across processes.
- **thread-safe** : partager **une seule instance** entre tous les threads/branches pour un plafond global au process.

> Modèles : `claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5` sont des ids Anthropic réels et courants. `gpt-5.5` / `gemini-3.5-flash` apparaissant dans certaines sources sont **NON VÉRIFIÉS** (à confirmer côté OpenAI/Google avant usage).

### 5.2 Couche 1b — le bucket TPM manquant (dual token bucket)

`InMemoryRateLimiter` étant **RPM-only**, un fan-out peut respecter le RPM et exploser le **TPM** (500 petites requêtes à gros prompts). La pratique production : tracker **RPM et TPM** avec un **dual token bucket** + **estimation pré-flight des tokens** ; consommer dans les deux buckets et *attendre plutôt que tirer-puis-429*. Pire panne — "500 requêtes passent le RPM, aucune ne passe le TPM, la file deadlock" — évitée par la mesure pré-flight (https://www.clawpulse.org/blog/llm-api-rate-limiting-best-practices-avoid-429-errors-and-save-40-on-costs, https://tianpan.co/blog/2026-04-15-backpressure-llm-pipelines).

> Pour OWIsMind : la moitié RPM est gratuite via `InMemoryRateLimiter` (chemin 3.11) ; la moitié TPM s'implémente à la main (estimer les tokens du prompt, 2ᵉ bucket, **une instance partagée thread-safe**). En **3.9 backend** sans `InMemoryRateLimiter`, le bornage passe d'abord par `MAX_CONCURRENT_RUNS` (§11) + un délai de démarrage par user.

### 5.3 Couche 2 — retry réactif sur 429/5xx

**(a) Auto au niveau modèle.** Les chat models retry **jusqu'à 6 fois par défaut** sur erreurs réseau, **429** et **5xx**, backoff exponentiel + jitter ; les erreurs client (401/404) ne sont pas réessayées. Régler via `max_retries` (https://docs.langchain.com/oss/python/langchain/models#rate-limiting).

**(b) `RetryPolicy` au niveau nœud** (granularité step) — rejoue **tout le nœud** :

```python
from langgraph.types import RetryPolicy
builder.add_node("call_model", call_model, retry_policy=RetryPolicy(max_attempts=5))
```

Défauts `RetryPolicy` (https://reference.langchain.com/python/langgraph/types/RetryPolicy) :

| champ | défaut | sens |
|---|---|---|
| `initial_interval` | `0.5` | premier back-off (s) |
| `backoff_factor` | `2.0` | multiplicateur/essai |
| `max_interval` | `128.0` | plafond back-off (s) |
| `max_attempts` | `3` | essais totaux |
| `jitter` | `True` | randomise le back-off |
| `retry_on` | `default_retry_on` | callable décidant quelles exceptions retry |

> **Idempotence** : `RetryPolicy` rejoue le nœud entier — un nœud qui a déjà fait un effet de bord (write DB, tool) avant l'échec le répétera. Gardez les nœuds idempotents (§7), surtout les nœuds SQL/storage OWIsMind.

### 5.4 Couche 3 — throttling gateway / LLM Mesh

Pour un gateway d'entreprise partagé, les quotas par tenant, la file et le coalescing appartiennent au gateway : "Run token-bucket logic locally, in front of the provider — not reactively in response to 429s", et utiliser une file pour que les requêtes en surcharge soient **retardées ou rejetées proprement** (https://agentgateway.dev/blog/2025-11-02-rate-limit-quota-llm/). **Pour OWIsMind, le LLM Mesh EST le gateway** : le fan-out de l'orchestrateur doit respecter `max_concurrency` (§6) + limiteur partagé pour qu'une requête 360° d'un user n'affame pas le Mesh (règle 2).

## 6. Borner la concurrence

### 6.1 Graphe : `max_concurrency`

```python
graph.invoke(inputs, config={"max_concurrency": 10})    # ou config={"configurable": {"max_concurrency": 10}}
```

Le knob de backpressure le plus simple : 100 sujets avec `max_concurrency=10` ⇒ jamais plus de 10 sous-agents en vol (https://docs.langchain.com/oss/python/langgraph/use-graph-api).

> Distinct de `recursion_limit` (défaut **25**, **pas** 1000) qui borne le nombre de supersteps, pas la concurrence ; le relever par invocation : `config={"recursion_limit": 100}` (https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT). Détails dans `references/langgraph-v1.md`.

### 6.2 In-node : `asyncio.Semaphore` pour `gather` manuel

`gather` lance **toutes** les coroutines d'un coup ; borner avec un sémaphore :

```python
import asyncio
sem = asyncio.Semaphore(5)                          # 5 sous-appels concurrents max

async def bounded(sub, config):
    async with sem:
        return await sub_agent.ainvoke({"input": sub}, config)

results = await asyncio.gather(*(bounded(s, config) for s in subjects))
```

### 6.3 Monde sync : borner par un thread pool

Sur le runtime sync (3.9), borner les sous-appels bloquants parallèles avec un `ThreadPoolExecutor(max_workers=N)` **unique et partagé**, dimensionné au budget de concurrence du gateway — pas de threads non bornés.

## 7. Idempotence sous retry & replay parallèle

Deux comportements LangGraph forcent l'idempotence des nœuds : (1) les supersteps transactionnels se ré-exécutent au resume (§3.6) ; (2) `RetryPolicy` / `max_retries` rejouent le travail (§5.3). Patterns :

- **Clés d'idempotence** sur les effets externes (upsert DB keyé `(run_id, step)`, pas d'insert aveugle) → un re-run est un no-op. C'est exactement le pattern **UPSERT** de `webapp_usage_monthly_v1` d'OWIsMind.
- **Compute pur dans le nœud, effets de bord en dernier** (un retry avant l'effet ne coûte que du CPU).
- **Reducers commutatifs** (§3.4) → les écritures rejouées/parallèles convergent quel que soit l'ordre.
- **Annulation coopérative** (flag de stop OWIsMind, pas de kill de thread) → un run annulé laisse le storage cohérent.

## 8. Thread-safety des objets partagés

- **Connexions Postgres (psycopg) / checkpointer.** Si vous adoptez `PostgresSaver`/`AsyncPostgresSaver` (chemin 3.11), la connexion **doit** être `autocommit=True` + `row_factory=dict_row` (sinon `setup()` échoue car `CREATE INDEX CONCURRENTLY` ne tourne pas dans une transaction) + `prepare_threshold=0` (poolers/pgbouncer). `from_conn_string(conn_string, *, pipeline=False)` est un **context manager classmethod** (pas de param `serde`, qui est sur `__init__`) ; appeler `.setup()` une fois (https://reference.langchain.com/python/langgraph.checkpoint.postgres/PostgresSaver). Détail dans `references/memoire-persistance-hitl.md`.
  > **OWIsMind aujourd'hui n'utilise pas de checkpointer LangGraph** : il stocke en **SQL direct** via `SQLExecutor2` (COMMIT explicite, requêtes paramétrées). Les principes transfèrent : **une connexion DB par thread** (les connexions psycopg ne sont pas thread-safe en usage concurrent), commit explicite, writes paramétrés/idempotents.
- **Reducer stateless.** Un reducer tourne à chaque écriture (parfois concurrente, parfois rejouée) → fonction **pure de (current, update)** : pas d'état mutable partagé, pas d'I/O, pas de dépendance à l'ordre. `operator.add`/union/`max` sont sûrs ; un reducer qui mute un dict module-level est une race.
- **Partager le limiteur, pas les clients fragiles.** `InMemoryRateLimiter` est explicitement thread-safe et **fait pour être partagé** (une instance = un plafond global). Ne pas partager les objets non documentés thread-safe (curseurs/connexions DB bruts, buffers mutables).

---

# Streaming vers un frontend web

## 9. La décision : SSE vs polling-via-thread

Deux patterns wire pour livrer de l'output incrémental à un navigateur. Le choix est dicté par **le runtime (async ou non) et la présence d'un proxy bufferisant**.

| | **SSE / chunked** | **Polling-via-thread** |
|---|---|---|
| Transport | une réponse `text/event-stream` longue | plusieurs `GET` courts contre un état de run en mémoire |
| Runtime serveur | idéal ASGI (FastAPI/Starlette) ; possible WSGI worker tenu | n'importe lequel (Flask sync/WSGI OK) |
| Risque proxy bufferisant | **élevé** — un proxy tampon livre tout à la fin | **nul** — chaque poll est une requête courte |
| Occupation worker | tient un worker tout le tour | le run occupe un thread de fond ; les workers requête restent libres |
| Annulation | déconnexion client → `GeneratorExit`/`CancelledError` ; ou `request.is_disconnected()` | flag stop explicite + détection d'abandon via heartbeat de poll |
| Reprise après coupure | native via `Last-Event-ID` + checkpointer | triviale — re-poll avec le dernier curseur |

**Règle** : si vous maîtrisez l'edge et tournez en ASGI, **SSE** (le plus simple, reconnexion native). Si vous êtes derrière un proxy non maîtrisé (DSS met un **nginx interne** devant chaque webapp backend, runtime **Flask sync Python 3.9**), **le polling-via-thread est le choix robuste** — et c'est ce qu'OWIsMind expédie (https://flask.palletsprojects.com/en/stable/patterns/streaming/, docstring `stream_manager.py`).

## 10. SSE sur le fil (le format à émettre dans les deux cas)

Flux unidirectionnel serveur→client sur une seule réponse `Content-Type: text/event-stream`. Corps texte cadré par **champs** (un par ligne), **événements séparés par une ligne vide** :

```
event: token
id: 42
data: {"text":"Hel"}

event: usage
data: {"input":1203,"output":88,"cost":0.0041}

event: done
data: {}
```

Sémantique des champs (https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events, https://html.spec.whatwg.org/multipage/server-sent-events.html) : `data:` = payload (lignes `data:` consécutives concaténées par `\n` ; JSON sur une ligne) ; `event:` = type dispatché côté navigateur (défaut `message`) ; `id:` = "last event ID", renvoyé en header `Last-Event-ID` à la reconnexion ; `retry:` = délai de reconnexion (ms) ; ligne débutant par `:` = **commentaire/heartbeat** (anti-idle proxy).

**Headers SSE requis à travers un proxy** (le piège du buffering) :

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
```

Côté nginx : `proxy_buffering off;`, HTTP/1.1, `gzip off;`, pas de cache. Sans ça, les tokens arrivent en un bloc à la fin (https://nginx.org/en/docs/http/ngx_http_proxy_module.html).

Consommation navigateur :

```js
const es = new EventSource("/chat/stream?run=abc");
es.addEventListener("token", (e) => append(JSON.parse(e.data).text));
es.addEventListener("usage", (e) => showFooter(JSON.parse(e.data)));
es.addEventListener("done",  () => es.close());
es.onerror = () => { /* EventSource reconnecte auto avec Last-Event-ID */ };
```

`EventSource` ne fait que GET, sans header custom ni body. Pour un POST/auth, utiliser `fetch()` + `ReadableStream` et parser les frames SSE à la main, ou `@microsoft/fetch-event-source`.

## 11. Flask / WSGI streaming (le cas sync, Python 3.9)

Flask streame via un **générateur** rendu comme corps de réponse ; chaque `yield` est flushé (https://flask.palletsprojects.com/en/stable/patterns/streaming/).

```python
from flask import Response, stream_with_context

@app.route("/chat/stream")
def chat_stream():
    def generate():
        for ev in run_agent_streamed(project_key, agent_id, messages):  # yield des dicts normalisés
            yield f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
        yield "event: done\ndata: {}\n\n"
    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

Caveats Flask critiques : (1) **les headers ne changent plus une fois le corps démarré** — fixer statut + headers *avant* le premier `yield` ; une exception en cours **ne peut pas** transformer un 200 en 500 → signaler l'erreur *dans le flux* (`event: error`). (2) Le **contexte de requête a disparu** pendant le générateur ; toucher `request` lève `RuntimeError` → `stream_with_context(...)`, ou capturer ce qu'il faut *avant*. (3) **Les middlewares WSGI peuvent casser le streaming** (buffering) — raison exacte pour laquelle OWIsMind n'utilise pas ça pour le stream agent.

### 11.1 Pourquoi OWIsMind fait du polling-via-thread

Le nginx interne de DSS bufferise la longue réponse `text/event-stream`. Le pattern éprouvé :

1. **`/chat/start`** lance UN thread daemon qui exécute l'agent, append chaque événement normalisé dans un `dict` module-level keyé par `run_id`, marque `done` à la fin. Renvoie `run_id`.
2. **`/chat/poll?run_id=…&cursor=N`** renvoie les événements depuis `cursor`, plus `done`/`error`, dans une requête courte que le proxy ne bufferise jamais.
3. **`/chat/stop`** pose un flag de stop coopératif que le worker vérifie entre chunks.

```python
import threading, time
from uuid import uuid4

_LOCK = threading.Lock()
_RUNS = {}                       # run_id -> {events, done, error, user_id, last_poll_at, stop_requested, ...}
MAX_CONCURRENT_RUNS = 8          # borne threads vivants + connexions LLM

def start_run(project_key, agent_id, messages, user_id):
    run_id = uuid4().hex
    with _LOCK:
        if sum(1 for s in _RUNS.values() if not s["done"]) >= MAX_CONCURRENT_RUNS:
            raise CapacityError()                      # route -> HTTP 503 "busy"
        _RUNS[run_id] = {"events": [], "done": False, "error": None, "user_id": user_id,
                         "last_poll_at": None, "stop_requested": False, "started_at": time.monotonic()}
    threading.Thread(target=_worker, args=(run_id, project_key, agent_id, messages, user_id),
                     daemon=True).start()
    return run_id

def _worker(run_id, project_key, agent_id, messages, user_id):
    try:
        for ev in run_agent_streamed(project_key, agent_id, messages):   # dicts normalisés (§13)
            if _should_stop(run_id):                   # vérifié ENTRE chunks
                break
            with _LOCK:
                _RUNS[run_id]["events"].append(ev)
        _persist(...)                                  # phase 2 : réponse + usage + trace
    except Exception:
        with _LOCK: _RUNS[run_id]["error"] = "agent_unavailable"
    finally:
        with _LOCK:
            _RUNS[run_id]["done"] = True               # APRÈS append des événements terminaux

def poll(run_id, user_id, cursor):
    with _LOCK:
        s = _RUNS.get(run_id)
        if s is None or s["user_id"] != user_id:       # owner-scopé ; None -> 404
            return None
        s["last_poll_at"] = time.monotonic()           # heartbeat pour détection d'abandon
        evs = s["events"]
        return {"events": evs[cursor:], "cursor": len(evs), "done": s["done"], "error": s["error"]}
```

Durcissements OWIsMind (tous dans `stream_manager.py`) : espacement de démarrage par user (`MIN_START_INTERVAL_SECONDS`), éviction TTL (`FINISHED_TTL`, `HARD_TTL`), caps mémoire par run (`MAX_LIVE_EVENTS`, `MAX_ANSWER_CHARS`), deadline wall-clock (`MAX_RUN_SECONDS`), abandon "le navigateur ne poll plus" (`ABANDON_AFTER_SECONDS` dérivé de `last_poll_at`). **`done` posé sous le même lock, APRÈS** les événements terminaux : un poll qui voit `done` voit forcément `final_answer`/`run_done` (pas de course sur le dernier frame).

**Trade-offs** : N petites requêtes au lieu d'un stream (cadence ~500 ms) ; le worker est un vrai thread OS (borné par le cap) ; annulation coopérative seulement (on stoppe *entre* chunks, pas un appel upstream gelé — il faudrait un watchdog). En contrepartie : proxy-proof, marche en sync 3.9 sans machinerie async.

## 12. FastAPI / Starlette (le cas async, chemin 3.11)

Si vous tournez en ASGI et que l'edge ne bufferise pas, SSE est le chemin le plus propre.

```python
from fastapi.responses import StreamingResponse

@app.get("/chat/stream")
async def chat_stream(request):
    async def gen():
        async for ev in agent.astream(inputs, stream_mode=["messages", "custom"]):
            if await request.is_disconnected():        # annulation coopérative
                break
            yield sse_frame(ev)
        yield "event: done\ndata: {}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

À la déconnexion client, le générateur async est annulé (`CancelledError`/`GeneratorExit`) — l'attraper pour nettoyer ; pattern robuste : poller aussi `await request.is_disconnected()` dans la boucle (https://github.com/fastapi/fastapi/discussions/7572). Pour du SSE riche (auto `id:`, heartbeats, shutdown gracieux), `sse-starlette`'s `EventSourceResponse` (https://github.com/sysid/sse-starlette).

## 13. Mapper la sortie LangGraph sur une taxonomie SSE

LangGraph expose `stream()` (sync) / `astream()` (async). `stream_mode` est le knob clé ; passer une **liste** pour multiplexer token + progress + state.

| `stream_mode` | émet | usage UI |
|---|---|---|
| **`values`** | l'**état complet** après chaque step | rare en UI (verbeux) |
| **`updates`** | `{node_name: delta}` après chaque nœud | frontières step/nœud, progress |
| **`messages`** | chunks token `(message_chunk, metadata)` | **tokens LLM** (réponse live) |
| **`custom`** | ce que le tool écrit via le stream writer | **progress tool** |
| **`debug`** | trace détaillée (checkpoints + tasks) | debug profond |
| **`checkpoints`** / **`tasks`** | événements checkpoint / task | **exigent un checkpointer** (sinon rien) |

Recommandation prod : `["updates", "messages", "custom"]` (https://docs.langchain.com/oss/python/langgraph/streaming). **Sortie v1 vs v2** : en v1, une mode unique donne le payload brut, plusieurs modes donnent des tuples `(mode, data)` ; en `version="v2"`, chaque chunk est un `StreamPart` uniforme `{"type", "ns", "data"}` (`ns` = `()` à la racine, `("node:<task_id>",)` dans un subgraph). **Toujours brancher sur la clé `type`/`mode` réelle, jamais sur l'ordre.**

```python
def sse_frame(part):
    t, d = part["type"], part["data"]
    if t == "messages":
        token, meta = d
        return f"event: token\ndata: {json.dumps({'text': token.content, 'node': meta['langgraph_node']})}\n\n"
    if t == "custom":
        return f"event: progress\ndata: {json.dumps(d)}\n\n"
    if t == "updates":
        return f"event: step\ndata: {json.dumps(list(d.keys()))}\n\n"
    return ""

for part in agent.stream(inputs, stream_mode=["messages", "custom", "updates"], version="v2"):
    if (frame := sse_frame(part)):
        yield frame
```

Filtrage des tokens par nœud (`meta["langgraph_node"]`), par tag (`meta["tags"]`), ou suppression via le tag `nostream` — utile quand seul le nœud final doit atteindre l'utilisateur.

### 13.1 `astream_events` (granularité plus fine)

`astream_events(version="v2")` émet un flux plat d'événements de cycle de vie typés — `on_chat_model_stream` (porte un `AIMessageChunk`), `on_tool_start`/`on_tool_end`, `on_chain_*`, + custom via `adispatch_custom_event`. **Le défaut est `v2`** (`v3` est opt-in/expérimental, exige LangChain ≥ 1.3 — protocole content-block) (https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/astream_events). Plus lourd que `stream_mode="messages"` ; le réserver quand vous avez besoin des frontières start/stop des tools. Clés du dict `StreamEvent` : `event`, `name`, `run_id`, `parent_ids` (v2+), `tags`, `metadata`, `data`.

### 13.2 Progress depuis l'intérieur d'un tool

```python
# Python >= 3.11 (sync ou async) : get_stream_writer() marche via contextvars
from langgraph.config import get_stream_writer

def query_revenue(filters: str) -> str:
    writer = get_stream_writer()
    writer({"status": "resolving values", "stage": 1})
    rows = run_sql(...)
    writer({"status": "fetched", "rows": len(rows)})
    return summarize(rows)
```

**Caveat 3.9 / async < 3.11** : `get_stream_writer()` ne marche pas (cf. §4.2) → déclarer un paramètre `writer: StreamWriter` injecté. En 3.9-async, threader aussi `config` dans `await model.ainvoke(messages, config)` sinon le token stream casse.

### 13.3 Le cas OWIsMind : boucle écrite à la main sur LLM Mesh (3.9, sans LangGraph)

Quand `create_agent`/`astream_events` ne sont pas disponibles (3.9, runtime LLM Mesh non-LangGraph), on streame une **boucle écrite à la main** sur l'API streaming du provider et on **yield les mêmes événements normalisés**. C'est ce qui réconcilie les deux mondes : le **contrat consommateur (§14) est identique** ; seul le producteur diffère.

```python
completion = project.get_llm(agent_id).new_completion()
for m in messages:
    completion.with_message(m["content"], m["role"])     # replay multi-tour

for chunk in completion.execute_streamed():
    data = getattr(chunk, "data", {}) or {}
    if data.get("type") == "footer":                     # DSSLLMStreamedCompletionFooter
        trace = data.get("trace")                        # usage + SQL généré par les tools
        continue
    if data.get("type") in ("content", "text"):
        yield {"type": "answer_delta", "text": data.get("text", "")}
    elif data.get("type") == "event":                    # cycle de vie agent (AGENT_TURN_START, …)
        yield {"type": "agent_event", "eventKind": data.get("eventKind"), ...}
# après la boucle : parcourir la trace footer pour totaux usage + SQL, puis :
yield {"type": "usage_summary", **totals}
yield {"type": "trace", "trace": trace}                  # persistance seulement, PAS la timeline live
```

Détecter le footer **à la fois** par `data["type"] == "footer"` **et** `isinstance(chunk, DSSLLMStreamedCompletionFooter)` (import gardé — shapes SDK variables). Les tool calls partiels portent un `index` pour réassembler across chunks. Code réel : `agents/streaming.py::run_agent_streamed` (https://developer.dataiku.com/latest/concepts-and-examples/llm-mesh.html). Correspondance LangGraph : `answer_delta` ≈ tokens `stream_mode="messages"` ; `agent_event` ≈ `updates`/`astream_events` ; progress tool ≈ writer `custom` ; footer `trace` ≈ `AIMessage.usage_metadata` final. Le frontend ne peut pas dire quel moteur a produit le stream — c'est le but.

## 14. Une taxonomie d'événements stable pour le frontend

Quel que soit le backend (LangGraph, LLM Mesh brut, boucle main), **normaliser vers un petit vocabulaire versionné** pour offrir au frontend un contrat unique. Celui d'OWIsMind (`agents/streaming.py` + `stream_manager.py`) :

| `type` | quand | payload |
|---|---|---|
| `run_started` | le worker démarre | `exchangeId` |
| `agent_event` | chaque step de cycle de vie (clés whitelistées) | `eventKind`, `toolName`, `label`, `stepIndex`, `elapsedSeconds`, … |
| `answer_delta` | chaque chunk de texte | `text` |
| `generated_sql` | un tool a produit du SQL | `sqlIndex`, `sql`, `success`, `rowCount`, … |
| `usage_summary` | fin de tour | `promptTokens`, `completionTokens`, `totalTokens`, `estimatedCost` |
| `final_answer` | réponse complète & persistée | `text` |
| `run_done` / `stopped` / `error` | terminal | statut / message |

Règles de design à copier : **whitelister les champs** relayés des internes agent (jamais le dict brut — il peut porter ids d'agents, instructions, SQL interne ; OWIsMind ne copie que `label / stepIndex / stepCount / agentKey / status`, chacun borné en longueur). **Garder la timeline live légère** (les grosses rows capturées / traces brutes sont persistance-only, relues à la demande via un endpoint séparé, jamais via `/chat/poll`). **Événements terminaux d'abord, puis `done`** sous le même lock. Un `stopped` (annulation user) est un terminal **propre** (rendre la réponse partielle + un marqueur discret, **pas** un toast d'erreur) ; un run abandonné/timeout est un `error`.

## 15. Annulation coopérative, reprise & footer d'usage

**Annulation** — il n'existe pas d'API universelle pour interrompre un appel LLM ; on stoppe *la consommation* entre chunks :
- **SSE/ASGI** : déconnexion → `CancelledError`/`GeneratorExit` + `await request.is_disconnected()` dans la boucle.
- **Polling-via-thread** : `/chat/stop` pose `stop_requested` sur le run du propriétaire ; le worker vérifie entre chunks et break, persiste la réponse partielle, émet `stopped`. OWIsMind dérive aussi une annulation *implicite* : si `last_poll_at` est périmé (onglet fermé), le run est abandonné pour libérer le slot/thread/connexion LLM et **stopper la facturation de tokens sans consommateur** (`stream_manager.py::request_stop`). Le LLM Mesh **n'expose aucune API de cancel** → "arrêter d'itérer le générateur" est le mécanisme supporté.
- **Backpressure** : en polling, liste d'événements capée (`MAX_LIVE_EVENTS`) + réponse capée (`MAX_ANSWER_CHARS`) + runs concurrents bornés (`MAX_CONCURRENT_RUNS`). En SSE, la backpressure est le buffer TCP (un client lent ralentit naturellement les `yield`).

**Reprise** — SSE : `id:` sur chaque événement → reconnexion auto avec `Last-Event-ID` ; pour vraiment *reprendre le calcul*, adosser à un **checkpointer + `thread_id`**. Polling : built-in — re-`GET /chat/poll?cursor=N` ; le run survit au départ du client (borné par TTL), un poll tardif dans `FINISHED_TTL` voit encore les événements terminaux au lieu d'un 404.

**Footer d'usage `↑ in · ↓ out · ~$cost`** :
- **LangChain/LangGraph** : le `AIMessage`/`AIMessageChunk` final porte `usage_metadata` (`input_tokens`, `output_tokens`, `total_tokens`). Pour l'obtenir en streaming, `stream_usage=True`. **Piège connu** : certains providers émettent un `usage_metadata` par chunk (`output_tokens`=1/chunk, `input_tokens` répété) → la somme naïve gonfle les totaux. Préférer le **`usage_metadata` agrégé final** (le dernier non nul), pas une somme sur les chunks (https://github.com/langchain-ai/langchain/issues/30429).
- **LLM Mesh** : le **footer** streamé porte la trace ; l'usage vit dans des dicts `usageMetadata` imbriqués. OWIsMind parcourt la trace, collecte chaque `usageMetadata` (plusieurs appels LLM sous-agent/tool dans un tour) et **les somme** en un totals + `estimatedCost` (`agents/streaming.py::_sum_usage_metadata`).

**Streamer + réconcilier** : émettre un `usage_summary` terminal ; le frontend rend le footer. Côté serveur, le worker capture les mêmes totaux et, en phase persistance, les écrit dans la ligne par-échange (**source de vérité** : `chat_v5.save_assistant_message(..., usage=...)`) + incrémente des agrégats lifetime/mensuel (`UPSERT` keyé `(user_id, month)` → quota mensuel = 1 lecture O(1)). **Best-effort** : un échec d'écriture usage ne doit jamais casser la réponse ; les agrégats sont reconstructibles depuis les lignes par-échange. L'**enforcement** du cap (rejeter `/chat/start` quand le mois dépasse la limite) est un pré-gate avant `start_run` — le storage est prêt côté OWIsMind, le gate lui-même était encore en attente à la dernière session.

## 16. Checklist

1. **Proxy non maîtrisé, ou runtime sync/3.9 ?** → polling-via-thread. Sinon → SSE (ASGI, chemin 3.11).
2. **SSE** : `text/event-stream` + `Cache-Control: no-cache` + `X-Accel-Buffering: no` ; `proxy_buffering off` nginx ; `id:` pour la reprise ; commentaires heartbeat.
3. **Flask** : tous les headers avant le 1er `yield` ; `stream_with_context` si vous touchez `request` ; erreurs *dans le flux* (le statut est verrouillé).
4. **Async < 3.11 (et 3.11-en-async)** : passer `config` à chaque `ainvoke` ; paramètre `writer: StreamWriter` (jamais `get_stream_writer()`) ; pas de `@task` async en 3.9.
5. **Fan-out** : reducer (commutatif) sur toute clé écrite en parallèle (sinon `InvalidUpdateError`) ; borner par `max_concurrency`/`Semaphore`/thread pool ; `defer=True` si branches inégales ; superstep tout-ou-rien → nœuds idempotents + `RetryPolicy`.
6. **Rate limiting** : `InMemoryRateLimiter` (RPM, partagé, thread-safe) + bucket TPM maison ; `max_retries` modèle (auto 429/5xx) + `RetryPolicy` nœud ; writes SQL/usage **idempotents (UPSERT)**.
7. **Multiplexer** tokens + progress + steps sur un canal ; **normaliser** vers un vocabulaire versionné ; **whitelister** les champs sortants.
8. **Footer usage** : lire le `usage_metadata` **agrégé final** / la trace footer (ne pas sommer par chunk sur les providers qui gonflent) ; persister par-échange (vérité) + UPSERT mensuel, best-effort ; gater `/chat/start` sur le cap.

## Sources

- LangGraph — Use the graph API (branches parallèles, `Send`, `max_concurrency`, `defer`, supersteps transactionnels) : https://docs.langchain.com/oss/python/langgraph/use-graph-api
- LangGraph — Streaming (caveats Python < 3.11, `StreamWriter`, `get_stream_writer` cassé, stream modes) : https://docs.langchain.com/oss/python/langgraph/streaming
- LangGraph — `INVALID_CONCURRENT_GRAPH_UPDATE` / `InvalidUpdateError` : https://docs.langchain.com/oss/python/langgraph/errors/INVALID_CONCURRENT_GRAPH_UPDATE · https://github.com/langchain-ai/langgraph/issues/2336
- LangGraph — `add_conditional_edges` (pas de `then=`) : https://reference.langchain.com/python/langgraph/graph/state/StateGraph/add_conditional_edges
- LangGraph — Functional API (async 3.11+, `@task` `retry_policy`) : https://docs.langchain.com/oss/python/langgraph/functional-api · https://reference.langchain.com/python/langgraph/func/task
- LangGraph — `RetryPolicy` (défauts) : https://reference.langchain.com/python/langgraph/types/RetryPolicy
- LangGraph — `recursion_limit` défaut 25 : https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT
- LangGraph — `ToolNode` source + issues parallélisme/interrupts : https://github.com/langchain-ai/langgraph/blob/main/libs/prebuilt/langgraph/prebuilt/tool_node.py · https://github.com/langchain-ai/langgraphjs/issues/861 · https://github.com/langchain-ai/langgraph/issues/6624
- LangGraph — `PostgresSaver` (autocommit/dict_row/from_conn_string) : https://reference.langchain.com/python/langgraph.checkpoint.postgres/PostgresSaver
- LangChain — Models / rate limiting (`InMemoryRateLimiter`, `max_retries`, auto 429) : https://docs.langchain.com/oss/python/langchain/models#rate-limiting · https://reference.langchain.com/python/langchain-core/rate_limiters/InMemoryRateLimiter
- LangChain — `astream_events` (défaut `v2`, `v3` opt-in) : https://reference.langchain.com/python/langchain-core/runnables/base/Runnable/astream_events
- LangChain — usage en streaming (inflation par chunk) : https://github.com/langchain-ai/langchain/issues/30429
- Dual token bucket / TPM+RPM / backpressure : https://www.clawpulse.org/blog/llm-api-rate-limiting-best-practices-avoid-429-errors-and-save-40-on-costs · https://tianpan.co/blog/2026-04-15-backpressure-llm-pipelines · https://agentgateway.dev/blog/2025-11-02-rate-limit-quota-llm/
- Reducers parallèles / exécution différée / commutativité : https://medium.com/@gmurro/parallel-nodes-in-langgraph-managing-concurrent-branches-with-the-deferred-execution-d7e94d03ef78
- Flask Streaming Contents / `stream_with_context` : https://flask.palletsprojects.com/en/stable/patterns/streaming/
- SSE — MDN / WHATWG : https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events · https://html.spec.whatwg.org/multipage/server-sent-events.html
- nginx (X-Accel-Buffering, proxy_buffering) : https://nginx.org/en/docs/http/ngx_http_proxy_module.html
- FastAPI/Starlette — stop on disconnect / sse-starlette : https://github.com/fastapi/fastapi/discussions/7572 · https://github.com/sysid/sse-starlette
- Dataiku LLM Mesh dev guide (streaming `execute_streamed`) : https://developer.dataiku.com/latest/concepts-and-examples/llm-mesh.html
- Versions : `langchain-core` 1.4.7 (2026-06-12) https://pypi.org/project/langchain-core/ · v1 migration / Python 3.10+ https://docs.langchain.com/oss/python/migrate/langgraph-v1
- Code OWIsMind : `python-lib/owismind/agents/stream_manager.py`, `agents/streaming.py`, `api/routes.py`, `python-lib/CLAUDE.md`
