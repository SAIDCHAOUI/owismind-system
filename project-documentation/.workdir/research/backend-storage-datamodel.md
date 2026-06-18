# Knowledge pack : Backend storage et modèle de données SQL (OWIsMind)

> Pack de connaissance code-grounded pour la zone "Backend storage and the SQL data model".
> Toutes les références sont sous la forme `chemin:ligne`. Les identifiants, noms de tables,
> noms de colonnes, mots-cles SQL et noms de fonctions sont laisses VERBATIM en anglais.
> Racine des fichiers : `Plugin/owismind/python-lib/owismind/storage/`.

## 0. Vue d'ensemble et principes structurants

Le backend OWIsMind persiste TOUT son etat applicatif (conversations, messages, feedback,
registre utilisateurs, reglages globaux, usage tokens/cout, artefacts) en **SQL direct** via
`dataiku.SQLExecutor2` sur une connexion **PostgreSQL** (schema `public`). Il n'y a **aucun Flow au
runtime**, a une seule exception : le **dataset de trace** (write-only, voir section 8). Le module
`storage/__init__.py:1-3` resume la regle : "Direct SQL via SQLExecutor2 on the admin-configured
PostgreSQL connection (...) no DSS Flow at runtime."

Invariants non negociables (memoire L008, CLAUDE.md python-lib, regle #3) :

- **Connexion configuree par l'admin, jamais codee en dur** (`sql_config.py:114-121`, defaut
  documente = `SQL_owi`). Tant qu'elle n'est pas definie, l'app se declare "not configured"
  (`sql_config.py:178-180`) au lieu de deviner.
- **Un `SQLExecutor2` FRAIS par appel** (`sql_config.py:193-207`) : l'objet porte un etat
  transactionnel, il ne doit jamais etre partage entre threads worker Flask.
- **Nommage physique** : `{PROJECT_KEY}_{namespace}_{logical}` avec namespace `owismind`
  obligatoire (`sql_config.py:264-276`).
- **Versionnement `_vN`, jamais d'`ALTER` de structure** (`migrations.py:9-11`).
- **COMMIT explicite apres chaque ecriture** via `pre_queries=[...]` + `post_queries=["COMMIT"]`.
- **Valeurs toujours parametrees** via `sql_value()` / `nullable_value()` ; identifiants via
  `pg_identifier()` ; jamais de f-string brute autour d'un contenu utilisateur.
- **Pas de bind cote serveur** : `SQLExecutor2` inline toujours la valeur dans le texte du statement
  (consequence directe = caps de texte et choix d'un dataset pour les traces).
- **Toute lecture/ecriture est owner-scopee `user_id`** dans le `WHERE`.

> **DIVERGENCE DOC vs CODE (a signaler)** : `docs/data-model.md` est **perime**. Il decrit la table
> `webapp_chat_v4` et `CONV_TITLE_MAXLEN = 140`, alors que le code LIVE utilise **`webapp_chat_v5`**
> (colonnes usage ajoutees) et **`CONV_TITLE_MAXLEN = 56`** (`chat_v5.py:332`). Il ne mentionne ni la
> table `webapp_usage_monthly_v1`, ni `webapp_artifacts_v1`, ni les colonnes lifetime de
> `webapp_users_v1`. Ce pack reflete le CODE (source de verite). Les citations `chat_v4.py:*` du doc
> correspondent aux memes mecanismes dans `chat_v5.py`.

---

## 1. `sql_config.py` : configuration et helpers de surete

C'est le socle. Tout le reste de `storage/` en depend.

### 1.1 Constantes statiques (`sql_config.py:32-56`)
`SCHEMA_NAME = "public"`, `APP_NAMESPACE = "owismind"`, `DIALECT = Dialects.POSTGRES`. Noms de params
webapp : `PARAM_CONNECTION = "sql_connection"`, `PARAM_TABLE_PREFIX = "table_prefix"`,
`PARAM_TRACES_DATASET = "traces_dataset"`, `PARAM_LOG_LEVEL = "log_level"`. Fallbacks project key :
`FALLBACK_PROJECT_KEY = "OWISMIND_DEV"`, `PROJECT_KEY_ENV_VAR = "OWISMIND_PROJECT_KEY"`.

### 1.2 Resolution de la connexion (`sql_config.py:114-121`, `connection_name()`)
Lue depuis `get_webapp_config()` (param `sql_connection`, un SELECT peuple par
`resource/compute_available_connections.py` via `list_connections()`). Gere les "param shapes"
ou la valeur arrive enveloppee dans un dict (`val.get("name") or val.get("connection") or
val.get("value")`). `is_configured()` (`sql_config.py:178-180`) = `connection_name() is not None`.

La config webapp est lue UNE FOIS et **cachee pour la vie du process** (`_webapp_config()`,
`sql_config.py:63-82`) : DSS redemarre le backend quand la config change, donc le cache est sur. Ne
leve jamais : une config illisible donne un dict vide (app "not configured").

### 1.3 Resolution du project key (`sql_config.py:86-107`)
Ordre de priorite : env `OWISMIND_PROJECT_KEY` -> config webapp `project_key` ->
`dataiku.default_project_key()` -> constante `OWISMIND_DEV`. Resolu une fois a l'import (n'a pas
besoin d'une connexion SQL) ; le couple `(PROJECT_KEY, PROJECT_KEY_SOURCE)` est expose pour l'admin.

### 1.4 `new_executor()` (`sql_config.py:193-207`)
Retourne TOUJOURS un nouveau `SQLExecutor2(connection=conn)`. **Leve une `RuntimeError`** si aucune
connexion configuree (backstop defensif : les routes gardent avec `is_configured()` d'abord). On
n'ouvre JAMAIS une connexion que l'admin n'a pas explicitement choisie.

### 1.5 Parametrisation et identifiants
- `sql_value(value)` (`sql_config.py:229-231`) = `toSQL(Constant(value), dialect=DIALECT)`. C'est LE
  point de parametrisation des valeurs user.
- `nullable_value(value)` (`sql_config.py:234-243`) : retourne le mot-cle `NULL` pour `None`/`""`,
  sinon `sql_value(value)`. Permet a un champ optionnel (display name manquant) de stocker SQL NULL
  plutot qu'une chaine vide.
- `bool_literal(value)` (`sql_config.py:246-254`) : inline `true`/`false` (mot-cle SQL nu) pour les
  booleens cote serveur deja type-checkes (evite la dependance a `Constant(bool)`).
- `pg_identifier(name)` (`sql_config.py:210-226`) : valide via `_IDENTIFIER_RE`
  (`^[A-Za-z_][A-Za-z0-9_-]*$`), **rejette > 63 octets** (`_MAX_IDENTIFIER_BYTES`, = NAMEDATALEN - 1)
  pour ne PAS laisser PostgreSQL tronquer silencieusement (risque de collision de deux noms logiques
  sur le meme nom physique), puis double-quote en echappant `"` -> `""`. Ne JAMAIS passer d'input
  user ici ; ne JAMAIS utiliser `sql_value` pour un identifiant.

### 1.6 Nommage des tables (`sql_config.py:256-276`)
- `_namespace()` : `owismind` ou `{prefix}-owismind` quand un prefixe valide est configure.
- `physical_table(logical)` : `"{PROJECT_KEY}_{namespace}_{logical}"`. Exemple :
  `webapp_chat_v5` -> `OWISMIND_DEV_owismind_webapp_chat_v5` (sans prefixe) ou
  `OWISMIND_DEV_bidule-owismind_webapp_chat_v5` (prefixe "bidule").
- `full_table(logical)` : reference pleinement qualifiee et quotee, p. ex.
  `public."OWISMIND_DEV_owismind_webapp_chat_v5"`.

**Prefixe admin** (`_resolve_table_prefix()`, `sql_config.py:130-160`) : valide par `_PREFIX_RE`
(`^[A-Za-z0-9_-]{1,16}$`, charset sur + longueur bornee a 16 pour rester sous la limite de 63 octets).
Un prefixe invalide/trop long est **ignore** (sans prefixe) et l'avertissement est emis UNE SEULE
fois (resolu une fois, cache). Le triplet `(effective, raw_input, ignored)` est surface a l'admin via
`storage_status()` pour qu'il sache que le prefixe a ete ignore au lieu d'echouer silencieusement.

### 1.7 `storage_status()` (`sql_config.py:280-303`)
Retourne la config resolue pour l'espace admin : `configured`, `connection`, `project_key`,
`project_key_source`, `table_prefix` (effectif), `table_prefix_input`, `table_prefix_ignored`,
`namespace`, `traces_dataset`, et le mapping `tables` (noms physiques de `webapp_chat_v5`,
`webapp_users_v1`, `webapp_settings_v1`, `webapp_usage_monthly_v1`).

> **Gotcha** : `traces_dataset_name()` (`sql_config.py:163-175`) lit le param `traces_dataset` (picker
> DATASET). La webapp y ECRIT seulement (append), ne le relit jamais. Non configure -> trace skip.

---

## 2. `migrations.py` : DDL idempotente et strategie `_vN`

La DDL vit UNIQUEMENT ici (jamais inline dans une route publique). Tables creees paresseusement a la
PREMIERE ecriture via un helper interne garde `_ensure_table()`. Strategie : nouveau format de ligne
= nouvelle table `_vN`, jamais d'`ALTER` de structure (`migrations.py:9-11`).

### 2.1 Noms logiques (`migrations.py:31-42`)
- `CHAT_V5_LOGICAL = "webapp_chat_v5"`
- `USERS_V1_LOGICAL = "webapp_users_v1"`
- `SETTINGS_V1_LOGICAL = "webapp_settings_v1"`
- `USAGE_MONTHLY_V1_LOGICAL = "webapp_usage_monthly_v1"`
- `ARTIFACTS_V1_LOGICAL = "webapp_artifacts_v1"`

Historique de la table chat : v2 (+`generated_sql`) -> v3 (+colonnes feedback) -> v4
(+`parent_exchange_id`) -> **v5 (+colonnes usage tokens/cost)**. A chaque bascule la nouvelle table
demarre VIDE ; l'ancienne est laissee INERTE (jamais droppee par le backend, ses anciennes
conversations cessent simplement de remonter).

### 2.2 Les 5 tables (DDL `CREATE TABLE IF NOT EXISTS`)

**`webapp_chat_v5`** (`migrations.py:64-87`) - un echange de chat par ligne :

| Colonne | Type | Role |
|---|---|---|
| `exchange_id` | `TEXT PRIMARY KEY` | id genere en Python (`uuid4().hex`, `chat_v5.py:104`), pas de readback. |
| `session_id` | `TEXT` | id de conversation (regroupe les echanges). |
| `user_id` | `TEXT` | login DSS proprietaire ; cle de scoping de TOUTES les lectures/ecritures. |
| `user_display_name` | `TEXT` | SNAPSHOT denormalise du nom a l'ecriture, **non** retro-maj (`chat_v5.py:99-101`). |
| `user_groups` | `TEXT` | liste JSON des groupes DSS au moment de l'ecriture. |
| `user_text` | `TEXT` | message BRUT user (borne par `MAX_PERSISTED_TEXT_CHARS`). Le prefixe nom/date + l'historique injectes a l'agent sont calcules au build-time, jamais stockes. |
| `assistant_text` | `TEXT` | reponse, remplie en phase 2 (`NULL` jusque-la). |
| `generated_sql` | `TEXT` | liste JSON d'items SQL, ou `NULL` (voir section 5). |
| `agent_key` | `TEXT` | **cle logique OPAQUE** de l'agent, jamais l'`agent_id` brut (`chat_v5.py:21-23`). |
| `created_at` | `TIMESTAMP NOT NULL DEFAULT now()` | horodatage phase 1 (defaut DB). |
| `answered_at` | `TIMESTAMP` | horodatage phase 2 (`now()` a l'UPDATE reponse), `NULL` sinon. |
| `feedback_rating` | `SMALLINT` | `0` / `1` / `NULL`. |
| `feedback_reasons` | `TEXT` | liste JSON des raisons (whitelistees cote caller). |
| `feedback_comment` | `TEXT` | commentaire libre borne. |
| `feedback_at` | `TIMESTAMP` | horodatage du feedback (`now()` quand note, `NULL` a l'effacement). |
| `parent_exchange_id` | `TEXT` | arete de l'arbre : echange dont celui-ci a branche ; `NULL` = racine. |
| `input_tokens` | `INTEGER` | tokens prompt du run (footer usage). |
| `output_tokens` | `INTEGER` | tokens completion du run. |
| `total_tokens` | `INTEGER` | total tokens du run. |
| `estimated_cost` | `DOUBLE PRECISION` | cout estime du run. |

Les colonnes usage sont **AUTORITATIVES** : `webapp_users_v1` + `webapp_usage_monthly_v1` sont
reconstructibles par somme de `chat_v5` (`chat_v5.py:18-23`).

**`webapp_users_v1`** (`migrations.py:98-111`) - registre users/admins (1 ligne par user ayant ouvert
la webapp >= 1 fois). PK `user_id`. Colonnes : `display_name`, `user_groups` (JSON), `is_admin`
(`BOOLEAN NOT NULL DEFAULT false`), `first_seen`, `last_seen`, et les compteurs LIFETIME
`total_input_tokens` / `total_output_tokens` (`BIGINT NOT NULL DEFAULT 0`), `total_cost`
(`DOUBLE PRECISION NOT NULL DEFAULT 0`), `last_usage_at` (`TIMESTAMP`).

**`webapp_settings_v1`** (`migrations.py:116-123`) - config globale cle-valeur (PAS par user). PK
`setting_key` ; `setting_value` (JSON), `updated_at`, `updated_by`.

**`webapp_usage_monthly_v1`** (`migrations.py:132-143`) - bucket par (user, mois calendaire). Colonnes
`user_id`, `period_start` (`DATE`), `input_tokens`/`output_tokens` (`BIGINT DEFAULT 0`), `total_cost`
(`DOUBLE PRECISION DEFAULT 0`), `request_count` (`INTEGER DEFAULT 0`), `updated_at`. **PK composite
`(user_id, period_start)`** = exactement une ligne par mois -> le quota mensuel futur est un seul PK
lookup, sans job de reset (un nouveau mois est naturellement une nouvelle ligne).

**`webapp_artifacts_v1`** (`migrations.py:149-156`) - specs d'artefacts (chart/table) rendus par
l'orchestrateur. PK `exchange_id` ; `user_id`, `artifacts` (JSON), `created_at`. Seule la SPEC est
stockee, jamais les lignes de donnees (reutilisees depuis le `generated_sql.result` capture).

### 2.3 ALTER additifs : la SEULE relaxation de la regle no-ALTER (`migrations.py:175-182`)
`_ALTERS_BY_LOGICAL` ne porte que `USERS_V1_LOGICAL` : 4 clauses `ADD COLUMN IF NOT EXISTS`
(`total_input_tokens`, `total_output_tokens`, `total_cost`, `last_usage_at`). Justification explicite
(autorisation user 2026-06-11) : des compteurs ADDITIFS sur le registre existant ne doivent pas
perdre les lignes deja portees (flags admin, `first_seen`). Idempotent (no-op une fois applique).

### 2.4 Index secondaires (`migrations.py:191-197`)
`_INDEXES_BY_LOGICAL` ne porte que `CHAT_V5_LOGICAL` : `(user_id, created_at DESC)` (suffixe
`uc_idx`, liste conversations) et `(user_id, session_id, created_at DESC)` (suffixe `usc_idx`,
lectures par session). `CREATE INDEX IF NOT EXISTS` est considere ADDITIF (pas un ALTER de structure).
La CTE d'ancetres se fait par PK `exchange_id`, donc pas d'index dedie.

### 2.5 `_ensure_table()` (`migrations.py:205-241`)
Garde par process : `_ensured_tables` (set) + `_lock` (threading.Lock), double-check locking. Construit
`pre = [ddl] + [ALTER...] + [CREATE INDEX...]` dans UNE transaction, puis `query_to_df("SELECT 1 ...",
pre_queries=pre, post_queries=["COMMIT"])`. Wrappers publics : `ensure_chat_table()`,
`ensure_users_table()`, `ensure_settings_table()`, `ensure_usage_monthly_table()`,
`ensure_artifacts_table()` (`migrations.py:244-272`).

---

## 3. `chat_v5.py` : ecriture en deux phases, arbre, lectures

### 3.1 Pattern d'ecriture en deux phases
**Phase 1** `save_user_message(session_id, identity, user_text, agent_key, parent_exchange_id=None)`
(`chat_v5.py:91-149`) : genere `exchange_id = uuid4().hex`, normalise `groups` en liste JSON, borne
`user_text` via `_bounded()`, `INSERT` la ligne avec `assistant_text = NULL`, `generated_sql = NULL`,
`answered_at = NULL` (`created_at` par defaut DB). COMMIT. Retourne `exchange_id`. Le full INSERT n'est
PAS logge en INFO (il inlinerait le corps du message) ; seul un log compact (`chat_v5.py:132-141`).
Appelee depuis `api/routes.py:267` dans le **thread de requete** (une erreur de write devient un HTTP
500 propre, pas une erreur dans le worker).

**Phase 2** `save_assistant_message(exchange_id, assistant_text, generated_sql=None, usage=None)`
(`chat_v5.py:173-245`) : `UPDATE` qui remplit `assistant_text`, `generated_sql`, les 4 colonnes usage
et `answered_at = now()`, matche sur l'`exchange_id` de la phase 1. **Tout dans un seul UPDATE atomique**
pour que l'enregistrement usage par echange (source de verite) atterrisse AVEC la reponse. Appelee
depuis `agents/stream_manager.py:419` (best-effort : une erreur de storage n'avorte pas le run, le user
a deja la reponse a l'ecran).

`usage` = les totaux footer `usage_summary` du run :
`promptTokens`/`completionTokens`/`totalTokens`/`estimatedCost`, ou `None` (run arrete tot sans footer).
Coerces via `_usage_literal()` (`chat_v5.py:152-170`) : missing/non-numerique/negatif -> SQL `NULL` ;
floats avec decimales fixes (`{:.10f}`) pour eviter la notation scientifique ; inline comme literal nu
(non-user, controle, mirroir de `bool_literal`).

### 3.2 `_bounded()` et le cap de texte (`chat_v5.py:54-76`)
`MAX_PERSISTED_TEXT_CHARS = 262_144` borne le texte STOCKE (pas la reponse live, bornee separement par
`stream_manager.MAX_ANSWER_CHARS`). Rationale "CRU log safety" : DSS LOGue chaque requete `SQLExecutor2`
(texte complet), `SQLExecutor2` n'a pas de bind serveur, donc `sql_value` inline toujours la valeur dans
le statement logge ; un scenario materialise ces logs dans un dataset ou une cellule SQL trop longue
trippe la limite de longueur de ligne.

> **GOTCHA CRITIQUE** : `_bounded()` ne doit JAMAIS toucher le JSON `generated_sql` : son marqueur de
> troncature corromprait le decodage. Le bornage du `generated_sql` est STRUCTUREL via
> `capture.cap_sql_list()` AVANT la serialisation (`chat_v5.py:182-188`, `chat_v5.py:196-197`).

### 3.3 Feedback hors-bande (`save_feedback`, `chat_v5.py:248-289`)
`UPDATE ... WHERE exchange_id = ... AND user_id = ...` (owner-scope : un user ne note que ses propres
messages, no-op a 0 ligne sinon). `rating in {0, 1, None(clear)}`, `reasons` -> liste JSON, `comment`
borne ; `feedback_at = now()` seulement quand une note est posee, `NULL` a l'effacement (literal SQL
fixe, jamais d'input user).

### 3.4 Lectures
- `_COLUMNS` (`chat_v5.py:83-88`) : ordre stable des colonnes pour la relecture (incluant
  `generated_sql`, feedback, `parent_exchange_id`, les 4 colonnes usage) -> le front reutilise un seul
  mapper `rowsToMessages`.
- `history_messages_for_chain(user_id, parent_exchange_id, max_messages)` (`chat_v5.py:297-325`) :
  contexte agent = chaine d'ancetres (section 6). `[]` si pas de parent. Valide la limite via
  `validate_history_limit` (`security/validation.py:116`, defaut 20, min 10, max 50), derive le nombre
  d'echanges via `exchanges_to_fetch(limit)` = `ceil(limit/2)` (`agents/context.py:158`), execute la
  CTE, recupere newest-first, `reverse()` en chronologique, decode `generated_sql`, aplatit via
  `flatten_exchanges_to_messages` (`agents/context.py:136`, le SQL est annexe au tour assistant comme
  grounding). `MAX_CHAIN_DEPTH = 200` (anti-cycle, `chat_v5.py:294`). Appelee depuis
  `agents/stream_manager.py:299`.
- `list_conversations(user_id, cursor_token, limit)` (`chat_v5.py:335-364`) : NOMS uniquement (jamais
  de corps de message). Pagination keyset (section 7). `CONV_TITLE_MAXLEN = 56` (`chat_v5.py:332`).
- `messages_for_session(user_id, session_id, cap=SESSION_MESSAGES_CAP)` (`chat_v5.py:391-409`) : tous
  les echanges d'UNE session (chrono), user+session scopes, borne `SESSION_MESSAGES_CAP = 500`
  (`chat_v5.py:368`). Decode `user_groups`, `generated_sql`, `feedback_reasons` en listes. Appelee
  depuis `api/routes.py:499` (lazy load route `/conversation`).

### 3.5 Items `generated_sql` et projection des cles (`chat_v5.py:373-388`)
Un item `generated_sql` = `{sql, success, row_count}` + cles optionnelles trust-layer
`sql_id`/`step_index`/`agent_key`/`result`. Sur la relecture `/conversation`, `_project_sql_items`
projette sur `_SQL_ITEM_PUBLIC_KEYS = ("sql", "success", "row_count", "sql_id", "step_index",
"agent_key")` : le `result` capture est DELIBEREMENT projete HORS (le thread reste leger ; seul
`/evidence/meta` renvoie le `result` stocke - contrat trust-layer §1). Items legacy/non-dict passent
tels quels (une cellule corrompue ne casse jamais une reponse).

---

## 4. `usage.py` + `sql_builders.py` : comptabilite usage 3 niveaux

`webapp_chat_v5` est l'AUTHORITATIVE par echange. `usage.py` maintient les 2 accelerateurs DENORMALISES
qui rendent le controle d'usage bon marche (`usage.py:1-19`).

`record_usage(user_id, usage)` (`usage.py:56-104`) : appelee EXACTEMENT une fois par run (juste apres
la persistance de la reponse, `agents/stream_manager.py:433`). Coerce via `_coerce_int` /
`_coerce_cost` (missing/garbage/negatif -> 0). No-op si tout est 0 (run arrete avant le footer) ou pas
de `user_id`. **Les 2 incrementations dans UNE transaction committee** pour que le cumul lifetime et le
bucket mensuel ne divergent jamais l'un de l'autre (`pre_queries=[monthly_sql, users_sql]`,
`post_queries=["COMMIT"]`, `usage.py:92-97`). Best-effort par contrat : le caller (stream_manager) wrappe
dans try/except, une erreur ne touche jamais la reponse a l'ecran, et les agregats sont reconstructibles
depuis chat_v5.

`build_usage_monthly_upsert` (`sql_builders.py:63-86`) : `INSERT ... VALUES (..., date_trunc('month',
now())::date, ..., 1, now()) ON CONFLICT (user_id, period_start) DO UPDATE SET input_tokens =
m.input_tokens + EXCLUDED.input_tokens, ...` (INCREMENT, jamais overwrite ; `request_count` + 1). Le
`period_start` est une expression SQL fixe, jamais user input.

`build_users_usage_increment` (`sql_builders.py:89-107`) : `UPDATE ... SET total_input_tokens =
total_input_tokens + {in_t}, ... last_usage_at = now() WHERE user_id = {user}` (no-op a 0 ligne si la
ligne user n'existe pas ; en pratique l'upsert `/me` tourne toujours d'abord).

> Les fragments tokens/cost passes aux builders sont des LITERAUX numeriques server-computed
> (`usage.py:80-84` : `str(int)`, `"{:.10f}".format(cost)`), jamais d'input user ; seul `user_id` est
> echappe via `sql_value`.

---

## 5. `generated_sql` et le bornage structurel (`evidence/capture.py`)

`cap_sql_list(items)` (`evidence/capture.py:269+`) borne AVANT serialisation (`chat_v5.py:196-197`) :
1. chaque item : `sql` tronque a `MAX_ITEM_SQL_CHARS = 20_000`, tags a `_MAX_TAG_CHARS = 300`, et le
   `result` capte par `cap_result` (rows a `MAX_RESULT_ROWS = 200`, cols a `MAX_RESULT_COLS = 50`,
   cell a `MAX_CELL_CHARS = 256`, JSON a `MAX_RESULT_JSON_CHARS = 100_000`) ;
2. liste bornee aux `MAX_SQL_ITEMS = 20` items les plus RECENTS ;
3. liste serialisee ajustee sous `MAX_PERSISTED_TEXT_CHARS = 262_144` (miroir de chat_v5) en retirant
   des items.

C'est ce qui ferme le "trou" du sql_json precedemment non borne (`chat_v5.py:182-188`). Une liste vide
stocke SQL `NULL` via `nullable_value` pour que "pas de SQL" se relise proprement.

---

## 6. Modele d'arbre de conversation (`sql_builders.py:110-133`)

`parent_exchange_id` transforme `webapp_chat_v5` (plate) en ARBRE : chaque echange pointe vers
l'echange dont il a branche ; `NULL` = racine. Editer/regenerer un prompt cree un echange FRERE.

Le contexte agent d'un echange = sa **chaine d'ancetres uniquement** : on remonte les
`parent_exchange_id` depuis le parent jusqu'a la racine de CETTE branche. Une branche ne voit jamais
les messages venus apres son point de branchement, ni les autres branches.

`build_ancestor_chain_query` = CTE recursive :

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

Invariants : **user-scope dans les DEUX membres** de la CTE (ancre ET membre recursif portent
`user_id = <user>`) ; **double borne** `_depth < MAX_CHAIN_DEPTH` (200, anti-cycle) ET `LIMIT <cap>` ;
lookup d'ancre par PK `exchange_id` ; valeurs pre-echappees cote caller, depth/cap coerces en int dans
le builder.

---

## 7. Lectures, pagination et serialisation

### 7.1 Pagination keyset (`pagination.py`)
Cursor opaque encodant `(last_at_iso, session_id)` separes par `_SEP = "\x1f"` (unit separator, jamais
present dans un timestamp ISO ni un uuid), base64 urlsafe (`encode_cursor`/`decode_cursor`). Decodage
DEFENSIF : tout token malforme degrade en `None` (= "premiere page"), ne leve jamais.

### 7.2 `build_conversation_list_query` (`sql_builders.py:13-45`)
Une ligne par `session_id`. Titre = premier `user_text` de la session, NETTOYE en un nom une-ligne :
```sql
COALESCE(LEFT(BTRIM(regexp_replace(
  (ARRAY_AGG(user_text ORDER BY created_at ASC, exchange_id ASC))[1],
  '[[:space:]]+', ' ', 'g')), {tlen}), '') AS title
```
(newlines/tabs/espaces repetes collapses, trim, puis troncature a `CONV_TITLE_MAXLEN = 56`).
`[[:space:]]` = classe POSIX (pas de backslash a mangler via `str.format`). `last_at = MAX(created_at)`.
Clause curseur : `WHERE (last_at < {cl}) OR (last_at = {cl} AND session_id < {cs})`. Tri
`ORDER BY last_at DESC, session_id DESC`. On fetch `page + 1` lignes pour calculer `has_more`
(`chat_v5.py:346-364`). Le titre est DERIVE (pas de colonne DB titre), donc retroactif et sans
migration (une future colonne titre = feature titre-IA differee).

### 7.3 `build_session_messages_query` (`sql_builders.py:48-60`)
`SELECT {columns} FROM {table} WHERE user_id = {user} AND session_id = {session} ORDER BY created_at
ASC, exchange_id ASC LIMIT {c}`.

### 7.4 `serialization.py`
`rows_to_json_safe(df)` (`serialization.py:15-33`) : SQLExecutor2 retourne des DataFrames pandas dont
les dtypes ne sont pas serialisables par `jsonify`. Timestamps -> ISO 8601 ; tout NaN/NaT -> `None`.
**Subtilite** : cast en `object` AVANT le `where(mask, None)`, sinon dans une colonne numerique (p. ex.
une colonne TEXT all-NULL typee float64 par pandas) le `None` serait re-coerce en NaN, que jsonify
emettrait comme le token nu `NaN` (JSON invalide). `parse_json_list(raw)` (`serialization.py:36-48`) :
decode une cellule JSON-liste, tolere NULL/vide/malforme (-> `[]`).

Les builders SQL purs (`sql_builders.py:1-10`) N'IMPORTENT PAS `dataiku` : testables en unittest sans
runtime DSS, pour asserter la FORME (chaque lecture toujours scopee a un seul `user_id`).

---

## 8. `chat_traces.py` : dataset write-only (la seule exception au "no Flow")

Les traces brutes d'agent NE vont PLUS dans une table/colonne SQL : elles sont APPENDEES sur un dataset
Flow choisi par l'admin (param `traces_dataset`), via `dataiku.Dataset(...).write_with_schema(...)`.

**Pourquoi un dataset et pas une colonne SQL** (`chat_traces.py:8-25`) : DSS logue chaque requete
SQLExecutor2 (texte complet), pas de bind serveur -> un `INSERT ... VALUES ('<huge JSON>')` ecrirait le
blob (jusqu'a des MB) dans un statement logge, et un scenario materialise ces logs dans un dataset ou
une cellule trop longue trippe la limite. `write_with_schema` ne passe PAS par ce query-logging
(ecriture par le dataset writer). Fix confirme empiriquement (reproduit l'app Dash de production).

Mecanismes (`chat_traces.py:88-172`) :
- `save_trace(exchange_id, trace)` : skip si pas de trace ou pas de dataset. JSON-encode (`default=str`),
  cap `MAX_TRACE_BYTES = 4_000_000` (au-dela : marqueur `{"_truncated": True, "_original_bytes": ...}`).
- Ecriture POSITIONNELLE : `write_with_schema` aligne le DataFrame par POSITION, pas par nom.
  `_column_order(dataset)` (`chat_traces.py:64-85`) lit `dataset.read_schema()` et, si le schema porte
  exactement les 3 colonnes `CANONICAL_COLUMNS = ["exchange_id", "trace", "created_at"]` (dans
  n'importe quel ordre), ecrit dans CET ordre (sinon "Name/Type mismatch for column N") ; fallback sur
  `CANONICAL_COLUMNS`.
- `spec_item["appendMode"] = True` (append, pas de TRUNCATE) ; `_WRITE_LOCK` process-wide (mono-process
  suppose, meme hypothese que le modele de polling).
- **Best-effort auto-protege** : toute erreur loggee sur une ligne et avalee -> une ecriture de trace ne
  peut JAMAIS affecter la reponse a l'ecran. Appelee depuis `agents/stream_manager.py:443`.

> **GOTCHA** : le dataset doit etre SQL-TABLE-backed, PAS CSV/filesystem (qui a sa propre limite de
> longueur de ligne, `ERR_FORMAT_LINE_TOO_LARGE`). Marque "MUST be validated in DSS" dans le code
> (`chat_traces.py:157`).

---

## 9. `admin.py` + `settings.py` : registre users et whitelist agents

### 9.1 `admin.py` (registre users/admins)
`record_user(identity)` (`admin.py:38-85`) : UPSERT idempotent (PK `user_id`) qui rafraichit
`user_groups`/`last_seen`, avec `display_name = COALESCE(u.display_name, EXCLUDED.display_name)` (garde
le nom stocke s'il existe, sinon remplit avec le defaut derive ; backfill + prospectif pour un futur
"set my name"). **Election du premier admin race-free** : un `pg_advisory_xact_lock` (cle
`_BOOTSTRAP_LOCK_KEY = 0x4F57494D` = "OWIM", `admin.py:35`) precede l'upsert, puis
`UPDATE ... SET is_admin = true WHERE user_id = ... AND NOT EXISTS (SELECT 1 ... WHERE is_admin =
true)` ; libere au COMMIT -> deux premiers users concurrents ne peuvent pas devenir admin tous les deux
(PostgreSQL READ COMMITTED, `admin.py:33-79`).

Autres : `is_admin(user_id)` (`admin.py:88-96`), `count_admins()` (`admin.py:99-105`, empeche de
retirer le dernier admin), `list_users()` (`admin.py:108-122`, oldest-first, borne
`MAX_USERS_LISTED = 1000`), `set_admin(user_id, value)` (`admin.py:125-137`, via `bool_literal`).

### 9.2 `settings.py` (config globale + whitelist agents)
`get_setting(key, default)` / `set_setting(key, value, updated_by)` (`settings.py:32-84`) : magasin
cle-valeur JSON generique. UPSERT idempotent sur PK `setting_key` avec `EXCLUDED.*`. Un JSON stocke
malforme ne casse jamais une requete (logge + `default`).

**Whitelist agents** sous `SETTING_ENABLED_AGENTS = "enabled_agents"` (`settings.py:29`) : liste JSON
de `{logical_key, project_key, agent_id, label}`. C'est la SOURCE DE VERITE SERVEUR de la resolution
agent. `resolve_enabled_agent(logical_key)` (`settings.py:103-117`) est le POINT D'ENFORCEMENT du chat :
le front n'envoie qu'un `logical_key` opaque (jamais d'`agent_id` brut) ; une cle forgee/perimee matche
rien et donne `None` (ne peut jamais resoudre vers un agent a executer). `get_enabled_agents()` /
`set_enabled_agents()` = helpers types (`settings.py:88-100`).

---

## 10. Connexions au reste du systeme

- **Cycle de vie d'un echange** : `POST /chat/start` (`api/routes.py:267`) -> phase 1
  `save_user_message` (thread requete) -> le worker `stream_manager` execute l'agent (LLM Mesh) ->
  a la fin : phase 2 `save_assistant_message` (`stream_manager.py:419`) + `record_usage`
  (`:433`) + `save_trace` (`:443`) + `save_artifacts` (`:454`), tous best-effort.
- **Reload d'une conversation** : `GET /conversation` -> `messages_for_session` (`routes.py:499`) ;
  liste sidebar -> `list_conversations`.
- **Contexte agent** : `history_messages_for_chain` (`stream_manager.py:299`) -> CTE d'ancetres ->
  `flatten_exchanges_to_messages` (annexe le SQL passe comme grounding).
- **Evidence Studio** : NE cree ni table ni colonne ; relit `generated_sql` de `webapp_chat_v5`
  (owner-scope), re-derive a la volee ; `/evidence/meta` renvoie les `artifacts` + le `result` capture
  (projete hors du thread normal par `_project_sql_items`).
- **Whitelist agents** : `settings.resolve_enabled_agent` est consomme par la couche agents pour
  resoudre `logical_key` -> `(project_key, agent_id)` sans jamais exposer l'id reel.
- **Admin** : `admin.is_admin` gate les routes `/admin/*` ; `storage_status` alimente l'espace admin.

## 11. Plafonds/caps recapitulatifs (instance safety)
`MAX_PERSISTED_TEXT_CHARS = 262_144` (`chat_v5.py:64`), `MAX_CHAIN_DEPTH = 200` (`chat_v5.py:294`),
`CONV_TITLE_MAXLEN = 56` (`chat_v5.py:332`), `SESSION_MESSAGES_CAP = 500` (`chat_v5.py:368`),
`MAX_USERS_LISTED = 1000` (`admin.py:27`), `MAX_TRACE_BYTES = 4_000_000` (`chat_traces.py:50`),
`MAX_ARTIFACTS = 8` / `MAX_ARTIFACTS_JSON_CHARS = 16_000` / `MAX_Y_SERIES = 8` (`artifacts.py:27-29`),
`MAX_SQL_ITEMS = 20` / `MAX_RESULT_ROWS = 200` / `MAX_RESULT_COLS = 50` / `MAX_CELL_CHARS = 256` /
`MAX_RESULT_JSON_CHARS = 100_000` / `MAX_ITEM_SQL_CHARS = 20_000` (`evidence/capture.py:33-49`),
limites de validation `MAX_HISTORY_LIMIT = 50` / `MAX_CONV_PAGE = 60` (`security/validation.py`).

## 12. Incertitudes et points en mouvement
- `docs/data-model.md` est PERIME (chat_v4 / 140) vs code LIVE (chat_v5 / 56) - voir avertissement
  section 0. A reconcilier par les auteurs de doc.
- Le **quota mensuel 50 EUR n'est PAS implemente** : seul le STOCKAGE est pret
  (`webapp_usage_monthly_v1` + hook envisage avant `start_run`). Mentionne dans la memoire projet.
- Le dataset de trace doit etre valide en DSS comme SQL-table-backed et en mode append (commentaire
  `chat_traces.py:157`, "MUST be validated in DSS").
- Le repo `dataiku-agents/` (couche agents) est en cours d'edition LIVE par un autre ingenieur ; le
  present pack ne couvre QUE `python-lib/owismind/storage/` (la zone assignee) et n'a pas inspecte
  `dataiku-agents/`.
