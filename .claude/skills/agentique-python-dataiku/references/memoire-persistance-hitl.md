# Mémoire, persistance, human-in-the-loop & exécution durable

> **À jour : juin 2026.** Baseline : LangChain 1.x (`langchain-core` 1.4.7, 2026-06-12), LangGraph 1.x (GA 2025-10-22), Dataiku DSS 14.x.
> Référence du skill `agentique-python-dataiku` (parent : `SKILL.md`). Voisins cités : `references/langgraph-v1.md`, `references/langchain-v1.md`, `references/dataiku-code-agents.md`, `references/eval-tracing-securite-production.md`, `references/code-patterns-dataiku.md`.

LangGraph fournit, en couplant une **couche de persistance** à un modèle d'exécution par super-steps, quatre capacités qui transforment une démo en runtime exploitable : mémoire de conversation, exécution durable (tolérance aux pannes), human-in-the-loop (HITL) et time travel. Ce document couvre les checkpointers, le store long terme, les modes de durabilité, la gestion de la mémoire (court/long terme), le time travel, les patterns HITL et la tolérance aux pannes — avec, à chaque fois, le double chemin Python 3.11 (LangGraph importable) vs Python 3.9 (stdlib-only, APIs Dataiku natives).

---

## 0. Le double chemin Python (FAIT MATÉRIEL — à rappeler partout)

L'instance Dataiku dispose de **deux** code environments : **Python 3.9 ET Python 3.11**. LangChain/LangGraph v1 exigent **Python ≥ 3.10**.

| Contexte | Python | Import langchain/langgraph ? | Persistance / mémoire / HITL |
|---|---|---|---|
| **Code Agent affecté à un code env 3.11** | ≥ 3.10 | **OUI** | Tout ce document s'applique : `PostgresSaver`, `interrupt()`, `durability=`, `Store`. |
| **Backend webapp OWIsMind** | **3.9.23** | **NON — jamais** | stdlib-only. Persistance = **SQL direct** (`SQLExecutor2`, PostgreSQL) ; appels LLM/agents/tools via **APIs Dataiku natives** (`project.get_llm(...)`, `get_agent_tool(id).run(...)`). |

> Ne **jamais** recommander d'importer langchain dans un contexte 3.9. En 3.9, les concepts LangGraph (checkpointer vs store, idempotence, fork-pas-rollback) restent un **blueprint** que l'on réimplémente à la main en SQL — voir §11.

---

## 1. Modèle mental : deux couches de persistance orthogonales

C'est la confusion la plus fréquente. LangGraph a **deux mécanismes complètement séparés** (source : https://docs.langchain.com/oss/python/langgraph/persistence ; https://docs.langchain.com/oss/python/langgraph/memory) — le corpus et la source ChatGPT concordent sur ce point.

| | **Checkpointer** | **Store** |
|---|---|---|
| Classe de base | `BaseCheckpointSaver` | `BaseStore` |
| Portée | un **thread** (une conversation/un run) | **inter-threads** (tous users/convs) |
| Clé | `thread_id` | tuple `namespace` + `key` |
| Durée de vie | par conversation | persistant au-delà des conversations |
| Rôle | **mémoire court terme**, snapshot complet de l'état après chaque step → continuité, tolérance aux pannes, HITL, time travel | **mémoire long terme** : profils, faits appris, connaissances partagées ; rappelable depuis n'importe quel thread |

Intuition : le *checkpointer* = « ce qui s'est passé dans CETTE conversation » (auto-géré, état complet) ; le *store* = « ce que l'agent sait SUR cet utilisateur/le monde, toutes conversations confondues » (vous décidez quoi écrire et quand).

Les deux s'attachent à la compilation et se combinent :

```python
graph = builder.compile(checkpointer=checkpointer, store=store)
graph.invoke(input, {"configurable": {"thread_id": "thread-1"}})
```

**Séparer `thread_id` (conversation) de `user_id` (namespace mémoire).** Nouvelle conversation = nouveau `thread_id`, mais même namespace `(user_id, …)` → la mémoire long terme persiste. Les namespaces servent aussi de **cloisonnement multi-tenant** : scoper par `(org_id, user_id, type)` évite les fuites inter-tenants (source : https://docs.langchain.com/oss/python/langgraph/memory).

---

## 2. Checkpointers (persistance court terme, scope thread)

Un **checkpoint** est un snapshot de l'état du graphe à un instant, identifié par un id monotone croissant. LangGraph écrit un checkpoint au fil des **super-steps** (modèle BSP : chaque super-step est un batch parallèle d'exécutions de nœuds). Le couplage state + version-tracking pilote quels nœuds tournent ensuite (source : https://docs.langchain.com/oss/python/langgraph/persistence ; https://reference.langchain.com/python/langgraph/checkpoints).

### 2.1 Threads & `thread_id`

Un **thread** = une conversation/tâche. Toute invocation doit porter un `thread_id` dans `config["configurable"]` ; c'est ainsi que LangGraph isole les users/tâches et sait quel état recharger.

```python
config = {"configurable": {"thread_id": "1"}}
graph.invoke({"messages": [{"role": "user", "content": "hi"}]}, config)
# plus tard, même thread → la conversation continue
graph.invoke({"messages": [{"role": "user", "content": "and again?"}]}, config)
```

Clés `configurable` de la couche persistance :
- `thread_id` — requis ; la conversation.
- `checkpoint_ns` — namespace de checkpoint (défaut `""`) ; utilisé par les subgraphs ; rarement défini à la main.
- `checkpoint_id` — épingle un checkpoint *précis* dans un thread (replay/fork, §6).

> **Renommage v0.2 à connaître** en lisant du vieux code : `thread_ts`/`parent_ts` → `checkpoint_id`/`parent_checkpoint_id` (source : https://changelog.langchain.com/announcements/langgraph-v0-2-increased-customization-with-new-checkpointers).

### 2.2 API `BaseCheckpointSaver`

Toutes les implémentations exposent `get_tuple(config)`, `list(config, *, filter, before, limit)`, `put(...)`, `put_writes(config, writes, task_id)`, `delete_thread(thread_id)` — plus les variantes async `aget_tuple`/`alist`/`aput`/`aput_writes`/`adelete_thread`. Le code applicatif n'appelle quasi jamais ces méthodes directement (le graphe s'en charge) ; on n'utilise en pratique que `delete_thread()` (nettoyage) et les wrappers graphe `get_state`/`get_state_history` (§6) (source : https://reference.langchain.com/python/langgraph/checkpoints).

### 2.3 Les implémentations intégrées

| Implémentation | Package pip | Import | Async | Usage |
|---|---|---|---|---|
| `InMemorySaver` (alias `MemorySaver`) | `langgraph-checkpoint` (bundled) | `from langgraph.checkpoint.memory import InMemorySaver` | les deux | **Tests/dev only.** État perdu au restart. |
| `SqliteSaver` | `langgraph-checkpoint-sqlite` | `from langgraph.checkpoint.sqlite import SqliteSaver` | non | prototype mono-process, fichier. |
| `AsyncSqliteSaver` | `langgraph-checkpoint-sqlite` | `from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver` | oui | dev local async. |
| `PostgresSaver` | `langgraph-checkpoint-postgres` | `from langgraph.checkpoint.postgres import PostgresSaver` | non | **production** (recommandé). |
| `AsyncPostgresSaver` | `langgraph-checkpoint-postgres` | `from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver` | oui | **production** async. |

Guidance officielle : *« Only use `InMemorySaver` for debugging or testing purposes. For production use cases we recommend installing langgraph-checkpoint-postgres and using `PostgresSaver`/`AsyncPostgresSaver`. »* Savers communautaires au même contrat (`from_conn_string` + `.setup()`) : Redis, MongoDB, Oracle, Couchbase, Snowflake (source : https://reference.langchain.com/python/langgraph.checkpoint/memory/InMemorySaver ; https://docs.langchain.com/oss/python/langgraph/add-memory).

### 2.4 SqliteSaver (local / petite échelle)

```python
from langgraph.checkpoint.sqlite import SqliteSaver

with SqliteSaver.from_conn_string("checkpoints.sqlite") as checkpointer:   # ":memory:" pour les tests
    graph = builder.compile(checkpointer=checkpointer)
    graph.invoke(input, {"configurable": {"thread_id": "1"}})
```

### 2.5 PostgresSaver / AsyncPostgresSaver (production) — signatures vérifiées

Install : `langgraph-checkpoint-postgres` (+ `psycopg`). **`.setup()` est obligatoire avant le premier usage** (crée les tables ; idempotent) — c'est le piège Postgres n°1.

Signatures **source-vérifiées** (la recency file fait foi ici) :

```python
# __init__ : serde est ICI (pas sur from_conn_string)
PostgresSaver(conn, pipe: Pipeline | None = None, serde: SerializerProtocol | None = None)

# from_conn_string : context manager classmethod ; pas de serde, pipeline= en kw-only
@classmethod @contextmanager
def from_conn_string(cls, conn_string: str, *, pipeline: bool = False) -> Iterator[PostgresSaver]: ...
```

Usage correct :

```python
from langgraph.checkpoint.postgres import PostgresSaver

DB_URI = "postgresql://postgres:postgres@localhost:5432/postgres?sslmode=disable"
with PostgresSaver.from_conn_string(DB_URI) as checkpointer:
    checkpointer.setup()                       # une seule fois (idempotent)
    graph = builder.compile(checkpointer=checkpointer)
    graph.invoke({"messages": [{"role": "user", "content": "hi"}]}, {"configurable": {"thread_id": "1"}})
```

Async : `AsyncPostgresSaver.from_conn_string(DB_URI)` (async context manager) + `await checkpointer.setup()`.

**Connexion/pool manuels** (serveurs longue durée : réutiliser un pool plutôt que `from_conn_string` par requête). En construisant la connexion soi-même, il **faut** `autocommit=True` et `row_factory=dict_row`, sinon le saver dysfonctionne (échecs silencieux) :

```python
from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

connection_kwargs = {"autocommit": True, "row_factory": dict_row}
with ConnectionPool(conninfo=DB_URI, max_size=20, kwargs=connection_kwargs) as pool:
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    graph = builder.compile(checkpointer=checkpointer)
```

**Foot-guns Postgres :**
- **Pipeline mode** (`pipeline=True`) batche les écritures pour le débit. Un bug ancien faisait que `AsyncPostgresSaver` hard-codait `pipeline=True` même quand indisponible (GitHub #2407) — vérifier la version de `langgraph-checkpoint-postgres` installée (ligne courante 1.0.x) (source : recency file ; https://github.com/langchain-ai/langgraph/issues/2407).
- `ShallowPostgresSaver`/`AsyncShallowPostgresSaver` : ne gardent **que le dernier** checkpoint par thread (pas d'historique → pas de time travel), pour réduire le stockage. Churn connu (note de migration `AsyncShallowPostgresSaver`) — vérifier l'état du package avant adoption.

> **Note Dataiku.** OWIsMind tourne déjà sur PostgreSQL via `SQLExecutor2`. Dans un **Code Agent 3.11**, `PostgresSaver.from_conn_string(...)` + `.setup()` est l'option naturelle, MAIS `.setup()` émet du DDL → le **gater** (une seule fois, hors hot path) pour respecter la règle « ne pas surcharger l'instance », et réutiliser un pool/une connexion plutôt qu'ouvrir par requête. En **backend 3.9**, on n'a pas ce saver : on persiste l'état en SQL direct (le `webapp_chat_v*` joue de facto le rôle de checkpoint thread-scopé).

### 2.6 Sérialisation

Tous les savers utilisent un `SerializerProtocol`. Défaut = **`JsonPlusSerializer`** (ormsgpack + fallback JSON étendu gérant types LangChain/LangGraph, datetimes, enums…). Implication : **tout ce qui est dans le state doit être sérialisable** par JsonPlus — pas d'objets vivants (connexions DB, file handles, threads) dans l'état. Chiffrement at-rest : envelopper le serializer avec `EncryptedSerializer` (source : https://reference.langchain.com/python/langgraph/checkpoints) :

```python
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
checkpointer = PostgresSaver(conn, serde=EncryptedSerializer.from_pycryptodome_aes(encryption_key))
```

---

## 3. Modes de durabilité (granularité de persistance)

Par défaut LangGraph checkpoint fréquemment pour la sûreté, au prix de latence. Le paramètre **`durability`** arbitre sûreté vs vitesse par run. **Défaut = `"async"`** (la recency file fait autorité ; passer `durability=` explicitement dans tout exemple où ça compte). Le kwarg `durability` sur `invoke`/`ainvoke`/`stream` vaut `None` par défaut, ce qui résout vers le mode configuré du graphe (source : https://docs.langchain.com/oss/python/langgraph/durable-execution ; https://reference.langchain.com/python/langgraph/types/Durability).

```python
Durability = Literal['sync', 'async', 'exit']
graph.invoke(input, config, durability="async")   # ← explicite ; ou "sync" / "exit"
```

| Mode | Comportement | Trade-off |
|---|---|---|
| `"sync"` | persiste **synchroniquement avant le step suivant** | durabilité maximale ; surcoût latence |
| `"async"` (**défaut**) | persiste **en asynchrone pendant l'exécution du step suivant** | bon équilibre ; petit risque de perte d'un checkpoint si crash en plein écriture |
| `"exit"` | persiste **uniquement à la sortie du graphe** (succès, erreur ou interrupt) | le plus rapide ; **pas de reprise après crash en plein run** |

Choisir : `"async"` = bon défaut chat ; `"sync"` = workflows à reprise garantie après n'importe quel crash ; `"exit"` = runs courts non critiques à débit max.

> **Note de nommage :** `durability` **a remplacé** l'ancien booléen `checkpoint_during` (pré-1.0). Dans du vieux code : `True` ≈ `"async"`/`"sync"`, `False` ≈ `"exit"`. Vérifier contre la version installée.

> **Caveat majeur.** Les checkpoints LangGraph **ne sont pas** un moteur d'exécution durable distribué complet (à la Temporal/Dapr). Ils snapshotent l'état, mais l'exactly-once des effets de bord à travers les crashes **reste votre responsabilité** (§7). Pire : si deux process reprennent le même `thread_id` en concurrence, *« LangGraph n'a aucune coordination intégrée pour empêcher les deux de s'exécuter »* — verrouillage/leasing distribué à votre charge (source : https://www.diagrid.io/blog/checkpoints-are-not-durable-execution-why-langgraph-crewai-google-adk-and-others-fall-short ; https://aerospike.com/blog/langgraph-production-latency-replay-scale/).

---

## 4. Le Store (mémoire long terme, inter-threads)

`BaseStore` = couche clé/valeur (+ vecteur optionnel) durable et inter-threads. Opérations : `put`, `get`, `search`, `delete`, `list_namespaces` + équivalents async (`aput`/`aget`/`asearch`/…) et `batch`/`abatch` (source : https://docs.langchain.com/oss/python/langgraph/memory).

### 4.1 Namespaces & clés

Les mémoires sont organisées par **namespace** = un **tuple** (chemin de dossier) + une **clé** (id string). Convention : `(user_id, "memories")`, `(user_id, "chitchat")`, `("agent_instructions",)`.

```python
from langgraph.store.memory import InMemoryStore
store = InMemoryStore()
namespace = ("my-user", "chitchat")
store.put(namespace, "a-memory", {"rules": ["User likes short, direct language"], "my-key": "my-value"})
item  = store.get(namespace, "a-memory")
items = store.search(namespace, filter={"my-key": "my-value"}, query="language preferences")
```

### 4.2 Implémentations

| Implémentation | Package | Import | Usage |
|---|---|---|---|
| `InMemoryStore` | bundled | `from langgraph.store.memory import InMemoryStore` | dev/test ; perdu à la sortie. |
| `PostgresStore` / `AsyncPostgresStore` | `langgraph-checkpoint-postgres` | `from langgraph.store.postgres import PostgresStore` / `.aio import AsyncPostgresStore` | prod ; nécessite `.setup()`. |
| Redis / Oracle / autres | communautaire | `langgraph.store.redis`, … | par backend. |

### 4.3 Recherche sémantique (mémoire vectorielle) — GA

`BaseStore.search`/`asearch` ; dispo sur `InMemoryStore` et `PostgresStore` (pgvector). **Désactivée par défaut** — on l'active via un `index` config à la construction. Similarité défaut = **cosine**. `IndexConfig` a trois champs : `"embed"` (fonction/instance d'embeddings, ou string provider), `"dims"` (dimensionnalité), `"fields"` (champs à embedder ; `"$"` = tout le document) (source : https://www.langchain.com/blog/semantic-search-for-langgraph-memory).

```python
from langchain.embeddings import init_embeddings
from langgraph.store.memory import InMemoryStore

embeddings = init_embeddings("openai:text-embedding-3-small")   # provider non-Anthropic — voir note
store = InMemoryStore(index={"embed": embeddings, "dims": 1536, "fields": ["text"]})
store.put(("user_123", "memories"), "1", {"text": "I love pizza"})
items = store.search(("user_123", "memories"), query="I'm hungry", limit=1)
```

Contrôle par item : `put(..., index=False)` stocke sans embedder ; `put(..., index=["champ"])` force les champs embeddés pour cet item. Piège « la recherche sémantique ne marche pas » → vous n'avez pas passé d'`index` (off par défaut), ou les `fields` cherchés ne sont pas ceux stockés.

> **Note sourcing.** L'exemple OpenAI vient du corpus. En contexte Anthropic, utiliser un modèle d'embeddings du provider voulu via le LLM Mesh / `init_embeddings`. Les ids Anthropic courants (`claude-opus-4-8`, `claude-sonnet-4-6`, `claude-haiku-4-5`) sont réels ; `text-embedding-3-small` est un modèle d'embeddings OpenAI (à confirmer selon votre stack).

### 4.4 Accès au Store dans les nœuds/tools

Compiler avec `store=...`, puis y accéder. En 1.0, accès recommandé via l'objet **`Runtime`** (qui porte aussi le `context` typé) ; l'ancien pattern injecte `store: BaseStore` en paramètre de nœud (toujours fonctionnel) ; pour les tools, `from langgraph.config import get_store` récupère le store ambiant.

```python
from langgraph.runtime import Runtime
async def call_model(state: MessagesState, runtime: Runtime[Context]):
    ns = (runtime.context.user_id, "memories")
    memories = await runtime.store.asearch(ns, query=state["messages"][-1].content, limit=3)
    await runtime.store.aput(ns, str(uuid.uuid4()), {"data": "User prefers dark mode"})
```

---

## 5. Mémoire : court terme vs long terme, et les trois types cognitifs

### 5.1 Gestion du court terme (maîtriser la liste de messages)

Le checkpointer persiste l'historique *complet* ; on ne veut pas tout renvoyer au LLM (limites de contexte, latence, coût, « distraction »). Trois stratégies sur le canal `messages` (reducer `add_messages`) (source : https://docs.langchain.com/oss/python/langgraph/add-memory).

**Trim avant l'appel modèle** (n'affecte que ce qu'on *envoie* ; l'historique reste en state) :

```python
from langchain_core.messages.utils import trim_messages, count_tokens_approximately
messages = trim_messages(state["messages"], strategy="last",
                         token_counter=count_tokens_approximately, max_tokens=128,
                         start_on="human", end_on=("human", "tool"))
```

**Supprimer du state via `RemoveMessage`** :

```python
from langchain.messages import RemoveMessage                  # chemin d'import 1.0
from langgraph.graph.message import REMOVE_ALL_MESSAGES
return {"messages": [RemoveMessage(id=m.id) for m in messages[:2]]}   # ou id=REMOVE_ALL_MESSAGES
```

Ne marche **que** si le canal utilise un reducer qui comprend `RemoveMessage` (`add_messages`). Possible aussi hors graphe : `graph.update_state(config, {"messages": RemoveMessage(id=...)})`.

**Résumer (running summary)** via `SummarizationNode` de **LangMem** (`langmem.short_term`) : garde un `RunningSummary` dans une clé de state et collapse les vieux tours au-delà d'un seuil de tokens. LangMem fournit aussi une intégration `pre_model_hook` pour résumer automatiquement avant chaque appel.

> **Règle de validité provider** (verbatim corpus) : après trim/delete, l'historique restant doit rester valide — commencer par un message user, et chaque tool-call assistant doit être suivi de son tool-result, sinon le prochain appel renvoie une 400 (`start_on="human"`, paires tool-call↔tool-result conservées).

### 5.2 Les trois types de mémoire (cadrage cognitif)

Conventions implémentées **par-dessus le Store** — pas des APIs séparées (source : https://docs.langchain.com/oss/python/langgraph/memory).

| Type | Contenu | Implémentation | Exemple |
|---|---|---|---|
| **Sémantique** | faits/connaissances sur user/monde | items Store, en **profil** (1 doc JSON mis à jour) ou **collection** (plusieurs petits docs) | « L'utilisateur s'appelle Sam ; travaille dans les télécoms. » |
| **Épisodique** | expériences/événements passés ; few-shot | items datés/par événement, souvent résumés, rappelés comme exemples | « Mardi dernier, on a comparé 3 devis et choisi le Plan B. » |
| **Procédurale** | règles/instructions (le « comment » de l'agent) | stocker le system prompt/instructions, raffiné par réflexion/méta-prompting | « Toujours répondre en français ; citer le SQL. » |

**Sémantique — profil vs collection :** *profil* = 1 doc JSON continuellement mis à jour (facile à lire, updates peuvent écraser) ; *collection* = plusieurs petits docs (meilleur rappel, mais dedup/conflits à gérer).

### 5.3 Quand écrire la mémoire : hot path vs background

| Approche | Comment | Pour / Contre |
|---|---|---|
| **Hot path** | écrire pendant la requête (un tool `save_memory` que le LLM appelle) | temps réel, dispo immédiatement / ajoute latence à chaque tour |
| **Background** | tâche async/job qui consolide après coup (cron/manuel) | pas de latence requête / logique de déclenchement, mémoire non instantanée |

Le SDK **LangMem** (Memory Manager) analyse les conversations et décide quoi stocker/mettre à jour/supprimer/consolider — à utiliser pour ne pas coder à la main extraction et consolidation.

---

## 6. Time travel : `get_state` / `get_state_history` / `update_state`

Méthodes graphe (checkpointer requis) pour inspecter-éditer-reprendre et explorer des « what-if » (source : https://docs.langchain.com/oss/python/langgraph/use-time-travel).

`get_state`/`get_state_history` renvoient des `StateSnapshot` (NamedTuple). Champs clés : `values`, `next` (nœud(s) à exécuter ; `()` = terminé), `config` (**contient le `checkpoint_id`** — sert au replay/fork), `metadata`, `created_at`, `parent_config`, `tasks`, `interrupts`.

```python
config = {"configurable": {"thread_id": "1"}}
snapshot = graph.get_state(config)                  # snapshot courant
for s in graph.get_state_history(config):           # historique, plus récent d'abord
    print(s.config["configurable"]["checkpoint_id"], s.next)
```

**Replay vs Fork** — deux opérations keyées sur le `config` d'un checkpoint passé :

```python
history = list(graph.get_state_history(config))
target  = next(s for s in history if s.next == ("write_joke",))
graph.invoke(None, target.config)                                   # REPLAY (input None)

fork_config = graph.update_state(target.config, values={"topic": "chickens"})  # FORK
graph.invoke(None, fork_config)
```

`update_state(config, values, as_node=None) -> RunnableConfig` : `values` passe par vos reducers (comme un retour de nœud) ; `as_node` déclare quel nœud « a produit » l'update (contrôle où l'exécution reprend).

**Deux avertissements cardinaux :**
1. **`update_state` n'est PAS un rollback.** Il **crée un nouveau checkpoint** qui branche ; l'historique original est préservé. Modèle = « fork, pas undo ».
2. **Replay/fork RÉ-EXÉCUTENT les nœuds aval** — ce n'est pas une lecture de cache. *« LLM calls, API requests, and interrupts fire again and may return different results. »* Ne pas supposer le déterminisme ; concevoir des nœuds idempotents si vous en dépendez (lien direct avec §7).

Pour les subgraphs : `graph.get_state(config, subgraphs=True)` ; granularité interne via `checkpointer=True` à la compilation du subgraph.

---

## 7. Human-in-the-loop (HITL)

### 7.1 Pourquoi le HITL exige la persistance

LangGraph exécute en super-steps ; pour mettre en pause, le runtime **persiste l'état et s'arrête** ; pour reprendre, il recharge le snapshot et continue — possiblement des heures/jours plus tard, ou après un restart de process. Trois faits qui pilotent tout (source : https://docs.langchain.com/oss/python/langgraph/interrupts ; https://reference.langchain.com/python/langgraph/types/interrupt) :

1. **Un checkpointer est obligatoire pour le HITL** — sans lui, rien à reprendre.
2. **La reprise est keyée par `thread_id`** (même thread = reprendre le même checkpoint).
3. **Le nœud interrompu re-s'exécute DEPUIS SON DÉBUT à la reprise** — pas depuis la ligne `interrupt()`. C'est la source de la majorité des bugs HITL.

### 7.2 Deux façons de pauser : interrupt dynamique vs breakpoint statique

| | **`interrupt()`** (dynamique) | **`interrupt_before`/`interrupt_after`** (statique) |
|---|---|---|
| Défini | dans le code du nœud/tool | au `compile()` (ou par run), par nom de nœud |
| Condition | arbitraire (tout Python sur le state) | toujours, à la frontière du nœud |
| Payload au humain ? | **oui** (toute valeur JSON-sérialisable) | non — s'arrête juste |
| Usage | HITL produit : approve/edit/review/collect | debug, inspection, « toujours pauser ici » |
| Reprise | `Command(resume=...)` | `invoke(None, config)` (ou `Command(resume=...)`) |

Règle : **`interrupt()`** pour le vrai HITL produit ; **breakpoints statiques** pour debug ou garde-fou « toujours pauser avant le nœud dangereux ».

### 7.3 `interrupt()` — la primitive

```python
from langgraph.types import interrupt
def node(state: State):
    answer = interrupt("what is your age?")   # 1er appel: lève GraphInterrupt, value envoyée au client
    return {"human_value": answer}            # à la reprise: interrupt() renvoie Command(resume=...)
```

- `value` (payload) doit être JSON-sérialisable. Au 1er appel, lève `GraphInterrupt` (le runtime l'attrape) ; aux **invocations suivantes dans la même task** (= au replay du nœud), renvoie la valeur fournie au premier appel (ne re-pause pas).
- Valeurs de resume scopées à la task qui exécute le nœud, non partagées entre tasks.
- Côté client : l'interrupt remonte via `.invoke()` (sous `__interrupt__`) et le stream mode `"values"` — plus besoin d'un `getState()` de suivi. Un objet `Interrupt` expose `value` et `id`.

```python
result = graph.invoke({"input": "data"}, config=config)
if "__interrupt__" in result:
    print(result["__interrupt__"])     # liste d'objets Interrupt
```

### 7.4 `Command(resume=...)` — la primitive de reprise

`Command` (champs `resume`, `goto`, `update`, `graph`, sentinelle `Command.PARENT`). En **entrée** de graphe, ne passer que `Command(resume=...)` (ou `invoke(None, ...)`) ; `goto`/`update` sont pour le **retour depuis un nœud**.

```python
from langgraph.types import Command
graph.invoke(Command(resume="Your response here"), config=config)   # même thread_id
```

Nœud qui route ET met à jour le state :

```python
def approval_node(state) -> Command[Literal["proceed", "cancel"]]:
    approved = interrupt({"question": "Do you want to proceed?", "details": state["action_details"]})
    return Command(goto="proceed") if approved else Command(goto="cancel")
```

**Interrupts parallèles (fan-out).** Quand plusieurs branches parallèles interrompent dans le même super-step, reprendre avec un **dict keyé par interrupt id** — crucial pour tout orchestrateur 360°/multi-agents :

```python
resume_map = {i.id: f"answer for {i.value}" for i in stream.interrupts}
graph.invoke(Command(resume=resume_map), config=config)
```

### 7.5 Les quatre patterns HITL canoniques

LangGraph liste officiellement ces 4 cas (source : https://changelog.langchain.com/announcements/interrupt-simplifying-human-in-the-loop-agents) :

1. **Approve / reject** — surfacer l'action proposée, brancher sur le booléen (`Command(goto=...)`, §7.4).
2. **Review / edit state** — `interrupt()` renvoie la valeur corrigée :
   ```python
   def review_node(state):
       edited = interrupt({"instruction": "Review and edit", "content": state["generated_text"]})
       return {"generated_text": edited}
   ```
3. **Review / approve d'un tool call** — `interrupt()` **dans le `@tool`** : le payload de resume peut **éditer les arguments** (approve / reject / edit args en une seule réponse). C'est la façon la plus propre de gater un tool à effet de bord (envoi mail, écriture DB, commande) :
   ```python
   @tool
   def send_email(to, subject, body):
       resp = interrupt({"action": "send_email", "to": to, "subject": subject,
                         "body": body, "message": "Approve sending this email?"})
       if resp.get("action") == "approve":
           return f"Email sent to {resp.get('to', to)}"   # le humain peut surcharger le destinataire
       return "Email cancelled by user"
   ```
4. **Validate input / multi-turn** — `interrupt()` dans une boucle `while`, validation côté serveur jusqu'à valeur valide.

Boucle HITL streaming de production : itérer `stream.messages` (tokens live), sortir si `not stream.interrupted`, sinon relancer avec `stream_input = Command(resume=user_response)`.

### 7.6 Breakpoints statiques

```python
graph = builder.compile(interrupt_before=["node_a"], interrupt_after=["node_b"], checkpointer=checkpointer)
graph.invoke(None, config=config)   # reprise sans payload
```

`interrupt_before` pause **avant** ; `interrupt_after` **après** l'exécution des nœuds nommés. Sans payload, on inspecte/modifie via `get_state`/`update_state` (§6) puis `invoke(None, config)`.

---

## 8. Tolérance aux pannes & exécution durable

### 8.1 Idempotence — la règle non négociable

Parce que (a) le nœud interrompu re-tourne depuis son top et (b) une reprise après crash ré-entre dans les nœuds, **tout effet de bord avant un `interrupt()` (ou tout code qui peut rejouer) doit être idempotent**, ou enveloppé dans un `@task`. Sinon : double débit de carte, double envoi de mail, lignes d'audit dupliquées (source : https://docs.langchain.com/oss/python/langgraph/interrupts).

```python
# BON : upsert idempotent avant interrupt
db.upsert_user(user_id=state["user_id"], status="pending")
approved = interrupt("Approve?")

# BON : effet de bord APRÈS interrupt
approved = interrupt("Approve?")
if approved:
    db.create_audit_log(user_id=state["user_id"])

# MAUVAIS : insert non idempotent avant interrupt → doublons à chaque reprise
audit_id = db.create_audit_log({"user_id": state["user_id"]})
approved = interrupt("Approve?")
```

Le décorateur **`@task`** enregistre le résultat d'une task dans le checkpoint : à la reprise, la task renvoie son résultat caché au lieu de re-tourner — c'est le mécanisme qui rend sûr un effet de bord non idempotent à travers les replays. Signature (recency-vérifiée) : `task(func=None, *, name=None, retry_policy=None, cache_policy=None, timeout=None)` — le param est `retry_policy` (un policy ou une séquence), pas `retry` (source : https://reference.langchain.com/python/langgraph/func/task).

### 8.2 Checkpoints aux frontières de super-steps → ré-exécution des nœuds

La source ChatGPT et le corpus concordent : les checkpoints sont pris **aux frontières de super-steps**, pas au milieu d'une fonction. Conséquence pratique : un nœud peut être **réexécuté depuis le début** après interruption/reprise → sa logique doit être idempotente et ses effets de bord maîtrisés. C'est le même principe que §6 (replay/fork ré-exécutent) et §7.1 (le nœud interrompu re-tourne).

### 8.3 Timeouts de nœud & retry policies

Trois policies composables, attachables au graphe / nœud / task fonctionnelle (source : https://www.langchain.com/blog/fault-tolerance-in-langgraph ; https://deepwiki.com/langchain-ai/langgraph/3.8-error-handling-and-retry-policies) :

```python
from langgraph.types import RetryPolicy, TimeoutPolicy

RetryPolicy(initial_interval=0.5, backoff_factor=2.0, max_interval=128.0,
            max_attempts=3, jitter=True, retry_on=(ConnectionError, TimeoutError))

TimeoutPolicy(run_timeout=30.0,      # mur d'horloge par tentative de nœud
              idle_timeout=5.0,      # temps max sans progrès observable → NodeTimeoutError
              refresh_on="auto")     # signal de progrès : writes canaux / chunks streamés / callbacks

StateGraph(State).add_node("call_llm", call_llm,
                           retry_policy=RetryPolicy(max_attempts=4),
                           error_handler=on_call_llm_failed)   # appelé APRÈS épuisement des retries
```

- **`retry_on` par défaut est conservateur** : retry sur `ConnectionError`, 5xx httpx/requests, catégories transitoires — mais **pas** `ValueError`/`TypeError`/`RuntimeError` (ne pas retry les bugs de prog/validation). `retry_on` peut être un tuple de types ou un callable runtime.
- **Erreurs de tool :** `ToolNode` a un flag `handle_tool_errors` — sur exception, l'erreur est renvoyée au LLM comme `ToolMessage` (« errors as context ») pour qu'il s'auto-corrige plutôt que de crasher le graphe.

### 8.4 `recursion_limit` (cap d'anti-boucle)

**Défaut = 25** (la recency file fait autorité — toute mention de « 1000 » est fausse). Hit → `GraphRecursionError`. Le relever **par invocation** (pas en changeant un défaut) :

```python
graph.invoke(inputs, config={"recursion_limit": 100})   # via config, kw-only
```

Si vous ne vous attendiez pas à autant d'itérations, vous avez probablement un cycle → vérifier la logique. Ne relever que pour des graphes *légitimement* complexes (source : https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT).

### 8.5 Règles de retry framework-agnostic (boucle à la main / SDK brut)

- Retry **uniquement** 429, 500, 502, 503, 504, **529** (overload Anthropic). Jamais les 4xx de validation.
- **Backoff exponentiel + jitter** (le jitter casse les rafales synchronisées « thundering herd »).
- **Respecter `Retry-After`** (Anthropic le renvoie sur 429) au-dessus de votre propre backoff.
- En **boucle agentique à la main** (Dataiku 3.9 ou SDK brut) : toujours borner par `max_iterations` + un mur d'horloge ; jamais de `while True` sans sortie dure (voir `references/code-patterns-dataiku.md`).

> **Note Dataiku.** Le **LLM Mesh est lui-même une gateway** (auth/quota/audit/routing centralisés) → ne pas réimplémenter le retry provider en code d'agent ; s'appuyer sur le Mesh et n'ajouter que les caps de boucle et l'idempotence. Pour de l'exactly-once cross-service mission-critique, coupler à un vrai moteur durable (Temporal/Dapr).

---

## 9. Dataiku « Additional Request Context » ≠ fenêtre de contexte LLM

Distinction explicite (source ChatGPT, à graver) : l'**Additional Request Context** de Dataiku transporte des **identifiants utilisateur, jetons de sécurité, états applicatifs** à travers la chaîne agents/outils. Ce **n'est pas** la fenêtre de contexte du LLM (les tokens envoyés au modèle), **ni** la mémoire agentique (checkpointer/store), **ni** l'historique conversationnel. Trois choses à ne pas mélanger :

| Notion | Quoi | Où ça vit |
|---|---|---|
| **Fenêtre de contexte LLM** | tokens effectivement envoyés au modèle (prompt + historique + tools) | requête au modèle, gérée par trim/summarize (§5.1) |
| **Mémoire agentique** | checkpointer (court terme, thread) + store (long terme, user) | §1–§5 |
| **Additional Request Context (Dataiku)** | user id, security tokens, app state propagés dans la chaîne agents/tools | métadonnée de requête Dataiku, **pas** des tokens modèle |

En contexte d'identité ligne-à-ligne (RBAC, exécution d'un tool sous l'identité de l'utilisateur final), c'est l'Additional Request Context — pas la mémoire — qui porte le security token. Voir `references/dataiku-code-agents.md` et `references/eval-tracing-securite-production.md`.

---

## 10. Pièges & anti-patterns

- **Oublier le checkpointer** → pas de mémoire entre tours ; `get_state`/time-travel/`interrupt()`/breakpoints échouent. Le graphe tourne, mais il oublie.
- **Oublier `.setup()`** (Postgres/Redis) → erreurs « table manquante » au 1er write.
- **psycopg manuel sans `autocommit=True, row_factory=dict_row`** → échecs silencieux/bizarres.
- **`InMemorySaver`/`InMemoryStore` en prod** → tout perdu à chaque restart/redéploiement.
- **`RemoveMessage` sans reducer compatible** → le message n'est pas réellement supprimé (canal doit utiliser `add_messages`).
- **Historique invalide après trim/delete** (pas de message user en tête, tool-call orphelin) → 400 provider.
- **Confondre checkpointer et store** → vouloir partager la mémoire user via `thread_id` (c'est par conversation), ou attendre du store qu'il mémorise le flux conversationnel (il ne snapshot pas).
- **`interrupt()` dans un `try/except Exception`** → le `except` large avale le `GraphInterrupt` et casse la reprise. Garder `interrupt()` hors des try ; n'attraper que des exceptions spécifiques autour de vraie I/O.
- **Réordonner / sauter conditionnellement des `interrupt()` dans un nœud** → les valeurs de resume sont matchées par index/ordre ; garder la séquence d'`interrupt()` stable entre runs.
- **Valeurs non JSON-sérialisables** dans `interrupt()`/`Command(resume=...)` → impossible à persister.
- **Interrupts parallèles avec resume scalaire** → fan-out exige `Command(resume={id: val})`.
- **Attendre un rollback de `update_state`** → c'est un fork ; l'historique persiste.
- **Supposer que replay = cache** → ré-exécution des nœuds aval, re-dépense de tokens.
- **`durability="exit"` ≠ reprise après crash** ; utiliser `"sync"`/`"async"` pour survivre aux crashes.
- **Reprise concurrente du même `thread_id`** depuis deux workers → pas de coordination intégrée ; verrouillage/leasing à votre charge.
- **Croissance illimitée du state** → jamais de trim/summarize → latence et coût explosent.

---

## 11. Transfert aux Code Agents Dataiku (framework-agnostic) — les deux chemins

Le modèle LangGraph reste un **blueprint** même sans LangGraph (backend 3.9) :

1. **Le split « checkpointer vs store » est universel.** Séparer (a) l'état par conversation keyé par un thread/conversation id, de (b) la mémoire user inter-conversations keyée par un user/namespace id. Dans OWIsMind : `webapp_chat_v*` (thread-scopé, le checkpoint de facto) vs tables par-user/mensuelles (inter-thread).
2. **Namespaces = scoping multi-tenant** → scoper par `(user_id, domaine)` (analogue aux lignes SQL owner-scopées).
3. **Assumer le replay ; rendre les effets de bord pré-pause idempotents** — la leçon n°1 de prod ; miroir de la règle « COMMIT après write » et « les effets de bord doivent être sûrs à rejouer ».
4. **Porter un payload d'approbation explicite, JSON-sérialisable** au humain (quoi approuver, avec détails) ; accepter approve / reject / edited-args en une réponse structurée — plus propre qu'un booléen nu.
5. **Posture de durabilité délibérée** : arbitrer débit vs reprise-après-crash, choisir le backend par environnement (Postgres en prod), gater tout DDL/`setup()` hors hot path (« ne pas surcharger l'instance »).
6. **Time travel = fork, pas rollback.** Si vous bâtissez replay/branchement sur votre propre état SQL, écrire une nouvelle ligne de branche, ne jamais muter l'historique.

| Capacité | Chemin **3.11** (LangGraph importable) | Chemin **3.9** (stdlib-only, APIs Dataiku) |
|---|---|---|
| Mémoire court terme (thread) | `PostgresSaver` + `thread_id` | ligne d'échange en SQL direct (`SQLExecutor2`), keyée conversation |
| Mémoire long terme (user) | `PostgresStore` + namespace `(user_id, …)` | tables par-user, scope owner |
| Pause/reprise HITL | `interrupt()` + `Command(resume=...)` | polling-via-thread (`/chat/start` → `/chat/poll`), message stocké, flag stop coopératif |
| Durabilité | `durability=` + checkpoints | fréquence de `COMMIT` de l'état en SQL |
| Idempotence | `@task` / upsert avant interrupt | idempotency key sur tools d'écriture, COMMIT avant effet de bord |
| Recherche sémantique mémoire | `PostgresStore` (pgvector) | pgvector direct ou Knowledge Bank (LLM Mesh) |

> **Note Dataiku transversale.** Les Code Agents DSS sont typiquement request/response (modèle polling-via-thread), pas des graphes durables longue durée. La durabilité y = votre store SQL de conversations/runs/events + un flag stop coopératif — pas des checkpointers LangGraph. Le LLM Mesh fournit déjà gateway, audit et tracing : ne pas réimplémenter ce qu'il offre.

---

## 12. « Quand utiliser quoi » — antisèche

| Objectif | Utiliser |
|---|---|
| Chat multi-tours qui se souvient dans une conversation | **Checkpointer** + `thread_id` |
| Prototype local / tests unitaires | `InMemorySaver`/`InMemoryStore` (ou `:memory:` Sqlite) |
| App locale mono-process | `SqliteSaver` |
| Serveur de production | `PostgresSaver`/`AsyncPostgresSaver` (+ `PostgresStore`) avec pool |
| Se souvenir d'un user à travers des conversations séparées | **Store**, namespace `(user_id, …)` |
| Retrouver des mémoires par le sens | **Store semantic search** (`index={"embed","dims","fields"}`) |
| Pause pour approbation/édition humaine | `interrupt()` + checkpointer + `Command(resume=...)` |
| Gater/éditer un tool call (mail/DB/paiement) | `interrupt()` **dans le `@tool`** (approve/reject/edit args) |
| Toujours pauser avant le nœud X (debug/garde-fou) | `interrupt_before=["X"]`, reprise `invoke(None)` |
| Réessayer / explorer un chemin alternatif | **Time travel** : `get_state_history` → replay/fork |
| Deux branches parallèles veulent un input humain | resume keyé par id `Command(resume={id: val})` |
| Workflow long, doit survivre aux crashes | checkpointer + `durability="sync"` (ou `"async"`) ; effets de bord idempotents / `@task` |
| Runs courts non critiques, débit max | `durability="exit"` |
| Données sensibles at-rest | `EncryptedSerializer` |
| Ne pas coder à la main l'extraction de mémoire | **LangMem** (manager + summarization) |
| Capper le stockage, pas besoin de time travel | `ShallowPostgresSaver` + `delete_thread` |
| **Tout cela en contexte backend 3.9** | **SQL direct + APIs Dataiku natives** — jamais d'import langchain (§0, §11) |

---

## Sources principales

- Persistence — https://docs.langchain.com/oss/python/langgraph/persistence
- Memory — https://docs.langchain.com/oss/python/langgraph/memory · Add/manage memory — https://docs.langchain.com/oss/python/langgraph/add-memory
- Time travel — https://docs.langchain.com/oss/python/langgraph/use-time-travel
- Durable execution — https://docs.langchain.com/oss/python/langgraph/durable-execution
- Interrupts / HITL — https://docs.langchain.com/oss/python/langgraph/interrupts · https://changelog.langchain.com/announcements/interrupt-simplifying-human-in-the-loop-agents
- Checkpoints API — https://reference.langchain.com/python/langgraph/checkpoints · PostgresSaver — https://reference.langchain.com/python/langgraph.checkpoint.postgres
- `interrupt` ref — https://reference.langchain.com/python/langgraph/types/interrupt · Durability type — https://reference.langchain.com/python/langgraph/types/Durability · `@task` — https://reference.langchain.com/python/langgraph/func/task
- Fault tolerance (RetryPolicy/TimeoutPolicy) — https://www.langchain.com/blog/fault-tolerance-in-langgraph · DeepWiki error handling — https://deepwiki.com/langchain-ai/langgraph/3.8-error-handling-and-retry-policies
- `recursion_limit` — https://docs.langchain.com/oss/python/langgraph/errors/GRAPH_RECURSION_LIMIT
- Semantic search — https://www.langchain.com/blog/semantic-search-for-langgraph-memory
- Checkpoints ≠ durable execution — https://www.diagrid.io/blog/checkpoints-are-not-durable-execution-why-langgraph-crewai-google-adk-and-others-fall-short · https://aerospike.com/blog/langgraph-production-latency-replay-scale/
- Dataiku Code Agents (BaseLLM, trace) — https://developer.dataiku.com/latest/concepts-and-examples/agents.html · https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/llm-agentic/agents/index.html
- Recency/versions (autorité) — fichier interne `gap-version-recency-recheck-2026.md` (2026-06-14)
