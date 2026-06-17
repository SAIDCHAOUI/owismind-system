# Modèle de données & stockage

> Documentation du modèle de données du plugin **OWIsMind** (Dataiku DSS).
> Voir aussi : [architecture.md](./architecture.md) · [backend-api.md](./backend-api.md) · [frontend.md](./frontend.md) · [security.md](./security.md) · [build-test-deploy.md](./build-test-deploy.md).

Tous les identifiants, noms de tables/colonnes, mots-clés SQL et noms de fonctions sont laissés sous leur forme anglaise d'origine (telle qu'écrite dans le code). Chaque affirmation renvoie au code source (`path:line`).

---

## 1. Principes de stockage

Le backend persiste tout son état (conversations, messages, feedback, registre utilisateurs, réglages globaux) en **SQL direct** via `SQLExecutor2`, sur une connexion **PostgreSQL** dans le schéma `public`. Il n'y a **aucun Flow au runtime** - à une exception près : le **dataset de trace** (write-only, voir §6).

Les invariants suivants sont structurants et non négociables (mémoire `L008`, `PROJECT_STATE.md §7`) :

- **Connexion configurée par l'admin, jamais codée en dur.** La connexion SQL est lue depuis la config webapp (`get_webapp_config()`) sous le paramètre `sql_connection` ; tant qu'elle n'est pas définie, l'app se déclare « not configured » au lieu de deviner (`sql_config.py:114-121`, `sql_config.py:178-180`). `new_executor()` lève une `RuntimeError` plutôt que d'ouvrir une connexion non choisie (`sql_config.py:193-207`).
- **Un `SQLExecutor2` FRAIS par appel.** L'objet porte un état transactionnel, il ne doit jamais être partagé entre threads worker Flask : `new_executor()` retourne toujours une nouvelle instance (`sql_config.py:193-207`).
- **Nommage physique** : toute table porte le project key en tête + le namespace `owismind` obligatoire, soit `{PROJECT_KEY}_owismind_{logical}` (préfixe optionnel inséré après le project key : `{PROJECT_KEY}_{prefix}-owismind_{logical}`). Construit par `physical_table()` / `full_table()` (`sql_config.py:262-274`, `_namespace()` `sql_config.py:256-259`). Une table est référencée pleinement qualifiée et double-quotée, p. ex. `public."OWISMIND_DEV_owismind_webapp_chat_v4"` (`full_table` `sql_config.py:271-274`). Le project key est résolu une fois à l'import (env → config webapp → `dataiku.default_project_key()` → constante `OWISMIND_DEV`) (`sql_config.py:86-107`).
- **Idiome de versionnement `_vN` - jamais d'`ALTER`.** Un nouveau format de ligne/message = une **nouvelle** table `_vN` créée en `CREATE TABLE IF NOT EXISTS` ; l'ancienne est laissée **inerte** (jamais droppée par le backend). C'est documenté en tête de `migrations.py:9-10` et `migrations.py:36-49`. Historique : chat_v1 → v2 (+`generated_sql`) → v3 (+colonnes feedback) → **v4 (+`parent_exchange_id`)**, table courante (`migrations.py:36-49`, `PROJECT_STATE.md §7`). À chaque bascule la nouvelle table démarre **vide** (données de test des versions précédentes perdues, assumé). Un `CREATE INDEX IF NOT EXISTS` est considéré **additif** (pas un `ALTER`) et reste donc autorisé (`migrations.py:104-110`).
- **COMMIT explicite après chaque écriture.** Toute DDL/DML passe par `pre_queries=[...]` + `post_queries=["COMMIT"]`, la requête principale étant un `SELECT 1 AS ...` sentinelle (p. ex. `chat_v4.py:137-141`, `migrations.py:150-154`, `admin.py:81-85`, `settings.py:77-81`).
- **Valeurs paramétrées uniquement.** Toute valeur est échappée via `sql_value()` (= `toSQL(Constant(value), dialect=POSTGRES)`) ou `nullable_value()` ; jamais de f-string brute autour d'un contenu utilisateur (`sql_config.py:229-243`). Les identifiants passent par `pg_identifier()` (regex + double-quotes), jamais par `sql_value` (`sql_config.py:210-226`).
- **Pas de bind côté serveur.** `SQLExecutor2` n'a pas de paramètre lié côté serveur (référence API Python officielle) : `sql_value` **inline** toujours la valeur dans le texte du statement. C'est la raison du cap `MAX_PERSISTED_TEXT_CHARS` (§4) et du choix d'un dataset pour les traces (§6) (`chat_v4.py:50-60`, `chat_traces.py:8-25`).

La DDL ne vit **que** dans `migrations.py` (jamais inline dans une route publique). Les tables sont créées paresseusement à la première écriture via un helper interne gardé `_ensure_table()`, avec un garde par process (`_ensured_tables` + `_lock`) qui évite de ré-émettre la DDL à chaque requête, et `CREATE TABLE IF NOT EXISTS` qui reste idempotent même en cas de course (`migrations.py:119-156`).

---

## 2. Tables

Trois tables sont définies dans `migrations.py` (`_DDL_BY_LOGICAL` `migrations.py:98-102`). Une quatrième destination de données - le **dataset de trace** - n'est pas une table SQL gérée par le backend (§6).

Liste des tables (nom logique → nom physique cité) :

- `webapp_chat_v4` → `public."OWISMIND_DEV_owismind_webapp_chat_v4"` - exchanges de chat (arbre de conversation + feedback).
- `webapp_users_v1` → `public."OWISMIND_DEV_owismind_webapp_users_v1"` - registre des utilisateurs / admins.
- `webapp_settings_v1` → `public."OWISMIND_DEV_owismind_webapp_settings_v1"` - config globale clé-valeur (dont la whitelist agents).

Les constantes de noms logiques : `CHAT_V4_LOGICAL` / `USERS_V1_LOGICAL` / `SETTINGS_V1_LOGICAL` (`migrations.py:29-31`).

### 2.1 `webapp_chat_v4`

**But** : un échange de chat par ligne (message utilisateur + réponse assistant), écrit en deux phases (§4) et organisé en **arbre de conversation** via `parent_exchange_id` (§3). Porte aussi le feedback par message. DDL : `migrations.py:50-69`.

| Colonne | Type | Signification |
|---|---|---|
| `exchange_id` | `TEXT PRIMARY KEY` | Identifiant de l'échange, généré en Python (`uuid4().hex`) - aucun readback nécessaire (`chat_v4.py:98`). |
| `session_id` | `TEXT` | Identifiant de la conversation (regroupe les échanges d'une même session). |
| `user_id` | `TEXT` | Login DSS du propriétaire ; clé de scoping de **toutes** les lectures/écritures. |
| `user_display_name` | `TEXT` | **Snapshot** dénormalisé par message du nom d'affichage dérivé à l'écriture ; intentionnellement **non** rétro-mis-à-jour si le nom change ensuite (`chat_v4.py:93-96`). |
| `user_groups` | `TEXT` | Liste JSON-encodée des groupes DSS du user au moment de l'écriture (`chat_v4.py:99-102`). |
| `user_text` | `TEXT` | Message brut de l'utilisateur (borné par `MAX_PERSISTED_TEXT_CHARS`). Reste **BRUT** : le préfixe nom/date et l'historique injectés à l'agent sont calculés au build-time, jamais stockés. |
| `assistant_text` | `TEXT` | Réponse de l'assistant, remplie en phase 2 (`NULL` jusque-là). |
| `generated_sql` | `TEXT` | Liste JSON de `{sql, success, row_count}` quand le run a généré du SQL ; `NULL` sinon (nullable - `migrations.py:43-44`, `chat_v4.py:152-156`). |
| `agent_key` | `TEXT` | **Clé logique opaque** de l'agent choisi - jamais l'`agent_id` brut, donc un readback ne fuite jamais d'id réel vers le front (`chat_v4.py:18-20`, `chat_v4.py:93-94`). |
| `created_at` | `TIMESTAMP NOT NULL DEFAULT now()` | Horodatage de la phase 1 (posé par défaut DB). |
| `answered_at` | `TIMESTAMP` | Horodatage de la phase 2 (`now()` à l'`UPDATE` réponse), `NULL` tant que non répondu. |
| `feedback_rating` | `SMALLINT` | Note : `0` (👎), `1` (👍) ou `NULL` (non noté / effacé). |
| `feedback_reasons` | `TEXT` | Liste JSON des raisons du feedback (whitelistées côté caller). |
| `feedback_comment` | `TEXT` | Commentaire libre du feedback (borné par `MAX_PERSISTED_TEXT_CHARS`). |
| `feedback_at` | `TIMESTAMP` | Horodatage du feedback (`now()` quand une note est posée, `NULL` quand effacée) (`chat_v4.py:199-201`). |
| `parent_exchange_id` | `TEXT` | Arête de l'arbre : l'échange dont celui-ci a branché ; `NULL` pour une racine / premier tour (`migrations.py:48-49`). |

**Index** (secondaires, idempotents - `migrations.py:111-117`) :

- `..._uc_idx` sur `(user_id, created_at DESC)` - pour la liste de conversations (sidebar) et les lectures par user.
- `..._usc_idx` sur `(user_id, session_id, created_at DESC)` - pour les lectures par session (fenêtre de contexte agent + `/conversation`).

La remontée de chaîne d'ancêtres (CTE récursive) se fait par la **PRIMARY KEY** `exchange_id`, donc aucun index supplémentaire n'est nécessaire pour elle (`migrations.py:108-110`).

> **Evidence Studio : AUCUN changement de schéma.** Le panneau de preuve ne crée ni table ni colonne : il **relit** `generated_sql` de `webapp_chat_v4` (lookup owner-scopé `WHERE exchange_id AND user_id` - `evidence/query_builders.py:11-18`) et **re-dérive tout à la volée** (parse, whitelist, re-exécution bornée lecture seule sur le dataset whitelisté) - pipeline **stateless**, rien de nouveau n'est stocké (`evidence/service.py:1-15`).

### 2.2 `webapp_users_v1`

**But** : une ligne par utilisateur ayant ouvert la webapp au moins une fois (afin qu'un admin puisse en promouvoir d'autres par leur `user_id` exact). Le **premier utilisateur** est bootstrappé comme admin. DDL : `migrations.py:73-82`.

| Colonne | Type | Signification |
|---|---|---|
| `user_id` | `TEXT PRIMARY KEY` | Login DSS de l'utilisateur. |
| `display_name` | `TEXT` | Nom d'affichage ; défaut dérivé du login, rempli via `COALESCE` à l'upsert (backfill des NULL + prospectif pour un futur « set my name ») (`admin.py:43-62`). |
| `user_groups` | `TEXT` | Liste JSON des groupes DSS (rafraîchie à chaque visite). |
| `is_admin` | `BOOLEAN NOT NULL DEFAULT false` | Drapeau admin (gate les routes `/admin/*` côté serveur). |
| `first_seen` | `TIMESTAMP NOT NULL DEFAULT now()` | Première visite. |
| `last_seen` | `TIMESTAMP NOT NULL DEFAULT now()` | Dernière visite (rafraîchie à chaque `record_user`). |

Pas d'index secondaire déclaré (`_INDEXES_BY_LOGICAL` n'a pas d'entrée pour ce logique - `migrations.py:111-117`). Le listing est borné par `MAX_USERS_LISTED = 1000` (`admin.py:27`, `admin.py:108-117`).

**Élection du premier admin race-free** : `record_user` prend un `pg_advisory_xact_lock` (clé `0x4F57494D` = `"OWIM"`) avant l'upsert + un `UPDATE ... WHERE NOT EXISTS (SELECT 1 ... WHERE is_admin = true)`, libéré au COMMIT - deux premiers utilisateurs concurrents ne peuvent pas devenir admin tous les deux (`admin.py:33-85`).

### 2.3 `webapp_settings_v1`

**But** : config globale de la webapp (PAS par utilisateur) en magasin clé-valeur générique - ainsi un nouveau réglage global ne requiert jamais une nouvelle table. `setting_value` porte un payload JSON-encodé. DDL : `migrations.py:87-94`.

| Colonne | Type | Signification |
|---|---|---|
| `setting_key` | `TEXT PRIMARY KEY` | Clé stable du réglage (p. ex. `enabled_agents`). |
| `setting_value` | `TEXT` | Payload JSON-encodé du réglage. |
| `updated_at` | `TIMESTAMP NOT NULL DEFAULT now()` | Dernière mise à jour. |
| `updated_by` | `TEXT` | `user_id` ayant écrit (nullable). |

Pas d'index secondaire. La **whitelist agents** vit ici sous la clé `SETTING_ENABLED_AGENTS = "enabled_agents"`, comme liste JSON d'objets `{logical_key, project_key, agent_id, label}` (`settings.py:28-29`, `settings.py:88-95`). C'est la source de vérité serveur de la résolution agent : le front n'envoie qu'un `logical_key` opaque, `resolve_enabled_agent()` le résout (ou retourne `None` pour une clé forgée/périmée) (`settings.py:103-117`). Écritures par UPSERT idempotent sur la PK (`settings.py:56-81`).

> **Tables inertes** (jamais droppées) : `webapp_chat_v1` / `v2` / `v3`, `webapp_chat_probe`, et les anciennes tables SQL de trace `_traces_v1` / `_run_events_v1` (supersédées par le dataset, §6). Voir `PROJECT_STATE.md §7`.

---

## 3. Le modèle d'arbre de conversation

`parent_exchange_id` transforme `webapp_chat_v4` (par ailleurs plate) en **arbre** : chaque échange pointe vers l'échange dont il a branché ; `NULL` désigne une racine / premier tour (`migrations.py:48-49`, `chat_v4.py:5-7`). Éditer/régénérer un prompt crée un échange **frère** (parent = le `parent_exchange_id` du tour, pas son propre id - voir `frontend.md`).

Le **contexte agent d'un échange = sa chaîne d'ancêtres uniquement** : on remonte les `parent_exchange_id` depuis le parent jusqu'à la racine de **cette** branche. Une branche ne voit donc jamais les messages venus après son point de branchement, ni les échanges des autres branches (`chat_v4.py:238-247`).

Cette remontée est une **CTE récursive** (`build_ancestor_chain_query` - `sql_builders.py:59-82`), de forme :

```sql
WITH RECURSIVE chain AS (
  SELECT *, 1 AS _depth FROM <table>
  WHERE exchange_id = <start> AND user_id = <user>
  UNION ALL
  SELECT t.*, chain._depth + 1 FROM <table> t
  JOIN chain ON t.exchange_id = chain.parent_exchange_id
  WHERE t.user_id = <user> AND chain._depth < <max_depth>
)
SELECT <columns> FROM chain
ORDER BY created_at DESC, exchange_id DESC
LIMIT <cap>
```

Invariants (tous matérialisés dans le builder) :

- **User-scopé dans les DEUX membres** de la CTE (l'ancre ET le membre récursif portent `user_id = <user>`) - un utilisateur ne peut jamais remonter la chaîne d'un autre.
- **Double borne** : `_depth < MAX_CHAIN_DEPTH` (= `200`, anti-cycle - `chat_v4.py:233-235`) **et** `LIMIT <cap>` - bornent le coût de la CTE.
- Lookup d'ancre par **PRIMARY KEY** `exchange_id` ; valeurs `start` et `user` pré-échappées par `sql_value` côté caller, `max_depth`/`cap` coercés en `int` dans le builder.

Côté Python, `history_messages_for_chain(user_id, parent_exchange_id, max_messages)` retourne `[]` quand il n'y a pas de parent, sinon exécute la CTE, récupère les lignes newest-first, les `reverse()` en chronologique, décode `generated_sql`, puis aplatit en messages (le SQL est annexé, lesson L031) bornés à `max_messages` (`chat_v4.py:238-266`). Le nombre d'échanges à remonter est dérivé de la limite validée via `exchanges_to_fetch(limit)` (`chat_v4.py:250-251`).

---

## 4. Écriture en deux phases

Un échange est écrit en deux temps (`chat_v4.py:9-13`) :

1. **`save_user_message(session_id, identity, user_text, agent_key, parent_exchange_id=None)`** (`chat_v4.py:85-143`) : génère l'`exchange_id` (`uuid4().hex`), `INSERT` la ligne utilisateur avec `assistant_text = NULL`, `generated_sql = NULL`, `answered_at = NULL` ; `created_at` posé par le défaut DB. Stocke le snapshot `user_display_name` (`nullable_value`), les `user_groups` (liste JSON), et l'arête `parent_exchange_id` (`nullable_value`). COMMIT. Retourne l'`exchange_id`.
2. **`save_assistant_message(exchange_id, assistant_text, generated_sql=None)`** (`chat_v4.py:146-186`) : `UPDATE` qui remplit `assistant_text`, `generated_sql` (liste JSON, ou SQL `NULL` via `nullable_value` quand vide pour que « pas de SQL » se relise proprement) et estampille `answered_at = now()`, matché sur l'`exchange_id` de la phase 1. COMMIT.

Le **feedback** est rempli **hors bande** (out-of-band) par `save_feedback(user_id, exchange_id, rating, reasons, comment)` : `UPDATE ... WHERE exchange_id = ... AND user_id = ...` (owner-scopé - un user ne note que ses propres messages ; no-op à 0 ligne sinon). `rating ∈ {0, 1, None(clear)}`, `reasons` → liste JSON, `comment` borné ; `feedback_at = now()` seulement quand une note est posée, `NULL` à l'effacement (littéral SQL fixe, jamais d'input user) (`chat_v4.py:189-230`).

**`MAX_PERSISTED_TEXT_CHARS = 262_144`** (`chat_v4.py:60`) borne le texte **stocké** (`_bounded()` ajoute un marqueur de troncature - `chat_v4.py:63-72`). Rationale (CRU log safety) : DSS LOGue chaque requête `SQLExecutor2` (texte complet), et `SQLExecutor2` n'a pas de bind serveur, donc `sql_value` inline toujours la valeur dans le statement loggué ; sur cette instance un scénario matérialise ces logs dans un dataset où une cellule SQL trop longue dépasse la limite de longueur de ligne. Les messages de chat sont normalement de taille KB (les traces, en MB, étaient le vrai coupable et passent par le dataset writer, §6). La réponse **live** n'est pas capée ici (bornée séparément par `stream_manager.MAX_ANSWER_CHARS`) ; seule la copie **stockée** est rognée (`chat_v4.py:50-59`).

> Note : le full INSERT/UPDATE n'est **pas** loggué en INFO par le backend (il inlinerait le corps du message) - seul un log compact est émis (`chat_v4.py:136`, `chat_v4.py:180`).

---

## 5. Lectures

Toutes les lectures sont user-scopées et bornées. Les colonnes JSON-texte sont décodées en listes prêtes à l'emploi via `parse_json_list`, et les DataFrames `SQLExecutor2` normalisés par `rows_to_json_safe` (timestamps → ISO 8601, NaN/NaT → `None`) avant de quitter le backend (`serialization.py:15-48`).

- **Liste des conversations** - `list_conversations(user_id, cursor_token, limit)` (`chat_v4.py:273-302`) bâtie par `build_conversation_list_query` (`sql_builders.py:13-41`). **Noms uniquement** (jamais de corps de message) : une ligne par `session_id`, titre = premier `user_text` de la session tronqué serveur à `CONV_TITLE_MAXLEN = 140` (`COALESCE(LEFT((ARRAY_AGG(user_text ORDER BY created_at ASC, exchange_id ASC))[1], <tlen>), '')`), `last_at = MAX(created_at)`. **Pagination keyset** sur `(last_at, session_id)` décroissant : la clause curseur est `WHERE (last_at < :cl) OR (last_at = :cl AND session_id < :cs)`. On fetch `page + 1` lignes pour calculer `has_more`, et le curseur opaque encode `(last_at_iso, session_id)` (`pagination.py:12-28`).
- **Messages d'une session** - `messages_for_session(user_id, session_id, cap=SESSION_MESSAGES_CAP)` (`chat_v4.py:305-326`) bâtie par `build_session_messages_query` (`sql_builders.py:44-56`). Chargement **lazy** (au clic, route `/conversation`), **user + session scopé**, chronologique (`ORDER BY created_at ASC, exchange_id ASC`), borné par `SESSION_MESSAGES_CAP = 500` (`chat_v4.py:306`). Renvoie les colonnes dans l'ordre stable `_COLUMNS` (`chat_v4.py:78-82`) - incluant `generated_sql`, les colonnes feedback et `parent_exchange_id` - afin que le front réutilise un seul mapper `rowsToMessages`. `user_groups`, `generated_sql` et `feedback_reasons` sont décodés en listes (`chat_v4.py:322-325`).

Les **builders SQL purs** (`sql_builders.py`) n'importent **pas** `dataiku` : ils assemblent le texte SQL à partir de fragments **déjà** échappés/quotés par le caller (valeurs via `sql_value`, table via `full_table`) et d'entiers coercés. Cela permet de tester en `node`/`unittest` que **chaque lecture est toujours scopée à un seul `user_id`** sans runtime DSS vivant (`sql_builders.py:1-10`).

---

## 6. Le dataset de trace (write-only, Flow)

Les traces brutes d'agent **ne** vont **plus** dans une colonne/table SQL. Elles sont **appendées** sur un **dataset Flow** choisi par l'admin (paramètre webapp `traces_dataset`, picker DATASET - `sql_config.py:163-175`), via l'API Dataset (`chat_traces.py:1-33`).

**Pourquoi un dataset et pas une colonne SQL** : `dataiku.Dataset(...).write_with_schema(...)` ne passe **pas** par le query-logging de `SQLExecutor2` ; le blob de trace (jusqu'à des MB) ne tombe donc jamais dans un statement SQL loggué - fix confirmé, qui réplique l'app Dash de production (`chat_traces.py:8-25`). Une ligne = `{exchange_id, trace, created_at}` (`CANONICAL_COLUMNS` - `chat_traces.py:61`).

**Écriture POSITIONNELLE** : `write_with_schema` aligne le DataFrame à la table SQL préexistante **par position**, pas par nom. `_column_order(dataset)` lit `dataset.read_schema()` et, si le schéma porte exactement les trois colonnes (dans n'importe quel ordre), écrit dans **cet** ordre (sinon « Name/Type mismatch for column N ») ; fallback sur `CANONICAL_COLUMNS` si le schéma est vide/illisible/différent (`chat_traces.py:61-85`, `chat_traces.py:159-165`). L'écriture utilise `spec_item["appendMode"] = True` (append, pas de TRUNCATE) et est **best-effort auto-protégée** : toute erreur est loggée sur une ligne et avalée, donc une écriture de trace ne peut **jamais** affecter la réponse déjà à l'écran. Cap `MAX_TRACE_BYTES = 4_000_000` (au-delà : marqueur). Verrou process-wide `_WRITE_LOCK` (mono-process supposé) (`chat_traces.py:47-56`, `chat_traces.py:118-171`).

**Conséquence « not readable inline »** : la webapp ne relit **jamais** ces traces (`fetch_trace` + route `/chat/trace` supprimés - `PROJECT_STATE.md §7`) ; elles existent pour l'analyse offline dans le Flow - la trace n'est donc pas affichable dans l'Evidence Studio. De même, `generated_sql` ne stocke que le SQL + `row_count`, **pas les lignes** de résultat : c'est pourquoi l'Evidence Studio v1 ne « réconcilie » pas des lignes stockées mais **re-exécute** le scope borné du SELECT sur les datasets whitelistés (voir §2.1 et [security.md](./security.md) §6).

---

## 7. Sûreté & invariants

Voir [security.md](./security.md) pour le détail ; côté modèle de données :

- **`pg_identifier` rejette les identifiants invalides** (regex `^[A-Za-z_][A-Za-z0-9_-]*$`) et **trop longs** (> 63 octets, NAMEDATALEN - lève au lieu de laisser PostgreSQL tronquer silencieusement, ce qui pourrait faire collisionner deux noms logiques) (`sql_config.py:46-56`, `sql_config.py:210-226`). Le préfixe admin est borné à 16 caractères et un charset sûr (`_PREFIX_RE` - `sql_config.py:52`, `_resolve_table_prefix` `sql_config.py:130-155`) ; un préfixe invalide est ignoré (sans préfixe) et surfacé à l'admin via `storage_status` (`sql_config.py:278-300`).
- **Toute lecture/écriture est scopée `user_id`** : INSERT/UPDATE (`chat_v4.py`), feedback owner-scopé (`chat_v4.py:189-230`), CTE user-scopée des deux côtés (`sql_builders.py:59-82`), liste/session scopées (`sql_builders.py:13-56`).
- **Plafonds de lignes bornés** partout : `SESSION_MESSAGES_CAP = 500`, `CONV_TITLE_MAXLEN = 140`, `MAX_CHAIN_DEPTH = 200`, `MAX_USERS_LISTED = 1000`, `MAX_PERSISTED_TEXT_CHARS = 262_144`, `MAX_TRACE_BYTES = 4_000_000`.
- **Aucune table/connexion/requête choisie par l'utilisateur** : la connexion vient du dropdown admin (`sql_connection`), les noms de tables de constantes contrôlées, et il n'existe **aucune route SQL générique** (pas de `/execute-sql`). Le front référence un agent uniquement par `logical_key` opaque, résolu serveur (`settings.py:103-117`).
- **Valeurs toujours paramétrées** (`sql_value`/`nullable_value`/`bool_literal`), COMMIT obligatoire, instance Dataiku préservée (travail borné, pas de Flow runtime hors dataset trace write-only).
