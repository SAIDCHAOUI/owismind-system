# Sécurité & sûreté de l'instance Dataiku - OWIsMind

> Modèle de sécurité du plugin DSS **OWIsMind** (WebApp Vue 3 + backend Flask `python-lib/owismind/`).
> Document destiné à un relecteur sécurité / ingénieur senior. Toutes les références pointent vers le
> code réel sous la forme `path:line`. Tout ce qui n'est pas implémenté est explicitement étiqueté
> **« Recommandation / non implémenté »**.
>
> Documents liés : [architecture.md](architecture.md) · [backend-api.md](backend-api.md) ·
> [frontend.md](frontend.md) · [data-model.md](data-model.md) · [build-test-deploy.md](build-test-deploy.md).
>
> La source de vérité opérationnelle reste `memory/PROJECT_STATE.md` (§12) et `memory/LESSONS.md`
> (audits **L011, L015, L016, L017, L018, L026, L027, L028**) ; ce document en est la synthèse vérifiée
> contre le code.

---

## 1. Modèle de menace & posture

OWIsMind est une WebApp **multi-utilisateurs** servie par une instance Dataiku DSS **partagée** : tous les
utilisateurs authentifiés sur l'instance peuvent l'ouvrir. La posture découle de quatre invariants.

| Invariant | Énoncé | Application (code) |
|---|---|---|
| **Frontière de confiance = le navigateur** | Tout ce qui vient du navigateur est non fiance : corps de requête, paramètres de query, en-têtes applicatifs. | Toute requête est validée/bornée avant d'atteindre SQL - `security/validation.py`. |
| **Identité résolue côté serveur** | L'identité de l'appelant n'est **jamais** lue dans le corps de la requête - elle est résolue depuis les en-têtes d'authentification DSS du navigateur. | `security/identity.py:101` `resolve_identity(headers)`. |
| **Le front n'envoie que des données logiques** | Le front envoie un `session_id`, un `message`, une **clé d'agent logique opaque**, une taille de fenêtre de contexte, un `parent_exchange_id` optionnel, un feedback. Il **ne choisit jamais** table, colonne, connexion, requête, ni `agent_id` brut. | `security/validation.py:1-8` (docstring module) ; `storage/settings.py:114` (résolution de la clé). |
| **Aucune surface SQL générique** | Pas de route `/execute-sql`/`/run-query` ; le SQL est construit serveur à partir de constantes contrôlées. | `storage/sql_builders.py` ; `storage/sql_config.py` ; vérifié par grep (aucune route SQL générique). |

**Modèle d'exécution (notes opérationnelles, mémoire L026/L027/L028) :**

- L'agent s'exécute **sous l'identité de la WebApp** (LLM Mesh), pas sous celle de l'utilisateur final. Tout
  agent **whitelisté** est donc joignable par tout utilisateur authentifié → la responsabilité d'exposition
  incombe à l'admin via la whitelist (L026 note c).
- Le modèle polling + état `_RUNS` en mémoire suppose un backend DSS **mono-process** : le cap de
  concurrence, l'ownership des runs et le cache d'identité sont **per-process** (L026 note b ; L028 escalade
  F-01 : la doc DSS 7.0 documente des backends Flask « multithreaded and multiprocessed » réglables → **à
  forcer/vérifier à 1 process** sur l'instance - voir §8 et §9).

---

## 2. Identité

L'identité est résolue **exclusivement** depuis les en-têtes d'authentification du navigateur, via le client
API DSS, jamais depuis le corps de la requête.

- `_auth_info(headers)` (`identity.py:91`) appelle
  `dataiku.api_client().get_auth_info_from_browser_headers(dict(headers))`. Un **client API frais par appel**
  (léger, thread-safe sous workers Flask concurrents).
- `resolve_identity(headers)` (`identity.py:101`) renvoie `{user_id, display_name, groups}` :
  - `user_id` = `authIdentifier` (le login DSS, ex. `said.chaoui`) - clé stable de scoping de tout le stockage
    (`identity.py:125`). Forme réelle de l'auth-info validée en DSS = mémoire **L011** (pas de `displayName`
    renvoyé par DSS).
  - `groups` = `info.get("groups") or []`, normalisé en liste (`identity.py:134-136`).
- **Échec → 401.** Toute défaillance de la résolution lève `IdentityError` (`identity.py:18`), surfacée par les
  routes en `401 unauthenticated` :
  - lookup DSS en échec → `IdentityError("auth_lookup_failed")` (`identity.py:119-123`) ;
  - aucun `authIdentifier` → `IdentityError("no_auth_identifier")` (`identity.py:126-132`).
  - Mapping `IdentityError → 401` répété dans chaque route : `routes.py:162, 229, 365, 554, 589, 625, 677, 725, 770`
    (un bloc par route) et `_admin_guard` (`routes.py:1558`).

**Dérivation du nom d'affichage** (DSS ne fournit pas de display name - L011) :

- `derive_display_name(login)` (`identity.py:45`) = **prénom capitalisé** (segment avant le 1er `.`, title-case
  par segment hyphéné) : `said.chaoui → Said`, `jean-marc.dupont → Jean-Marc`, `admin → Admin`, vide → `None`.
  C'est ce défaut que `resolve_identity` met dans `display_name` (`identity.py:141`).
- `derive_full_name(login)` (`identity.py:71`) = `Prénom Nom` (toutes les segments title-casées) - utilisé pour
  le préfixe de contexte agent par tour (`routes.py:513-516`).
- Le nom n'est qu'un **défaut** : `admin.record_user` upsert avec `COALESCE` (`admin.py:61`) pour préserver un
  nom custom **si** une feature « set my name » existait. **Recommandation / non implémenté** : aucune route
  « set my name » n'existe encore (le `COALESCE` est prospectif - L017, PROJECT_STATE §12 item 4).

**Cache d'identité (sûreté, pas une faille) :** un cache per-process à TTL court (`_AUTH_TTL_SECONDS = 5.0`,
`identity.py:28`) clé sur une **empreinte SHA-256 du cookie** (`_identity_cache_key`, `identity.py:34`) collapse
les lookups DSS répétés de `/chat/poll` (≈ 2 Hz par chat). Seuls les lookups réussis sont cachés ; éviction
opportuniste bornée par `_AUTH_CACHE_MAX = 512` (`identity.py:151-158`). Les valeurs d'en-tête peuvent porter
des credentials → **jamais loguées** (`identity.py:96-97`).

---

## 3. Whitelist d'agents côté serveur

Invariant : **le front ne reçoit et n'envoie qu'une clé logique opaque** ; le backend résout
`(project_key, agent_id)` uniquement si l'agent est activé ; une clé forgée résout `None`. Le `agent_id` brut ne
traverse jamais vers le front (CLAUDE règle #4, mémoire L017/L018).

| Étape | Mécanisme | Code |
|---|---|---|
| Clé logique opaque | `_logical_key(project_key, agent_id)` = `"ag_" + sha1(f"{pk}:{agent_id}")[:12]` - stable & opaque. | `routes.py:102` |
| Liste exposée au chat | `/agents` projette **uniquement** `{key, label}` - jamais `agent_id`/`project_key`. | `routes.py:794-797` |
| Résolution (enforcement) | `settings.resolve_enabled_agent(logical_key)` parcourt la whitelist activée ; renvoie l'entrée seulement si elle correspond à un agent réel **encore activé**, sinon `None`. | `storage/settings.py:114-129` |
| Rejet côté route | `/chat/start` : agent non résolu → `404 agent_not_enabled` ; le run n'est jamais lancé. | `routes.py:404-407` |
| Whitelist inviolable à l'écriture | `POST /admin/agents` **re-valide chaque agent demandé** contre les listings DSS live : projet visible (`discovery.list_project_keys`) **et** agent réellement présent (`discovery.list_project_agents`). Un id forgé depuis le front ne peut jamais être persisté ; cap `MAX_ENABLED_AGENTS = 50`. | `routes.py:1771` (`routes.py:93`, `routes.py:1797-1798`, `routes.py:1801, 1836-1838`) |

Le `agent_id` résolu reste serveur de bout en bout : passé au worker (`stream_manager.start_run`,
`routes.py:524-527`), jamais renvoyé au client (le front ne reçoit que le `run_id` opaque,
`routes.py:537`). La colonne `agent_key` stockée est la **clé logique opaque**, jamais le `agent_id` brut
(`chat_v5.py:21-23`).

---

## 4. Sécurité SQL

Stockage en **SQL direct** (`SQLExecutor2`, PostgreSQL, schéma `public`), **sans Flow au runtime** (CLAUDE
règle #3, mémoire L008/L014/L015).

**Paramétrage des valeurs / quoting des identifiants** (`storage/sql_config.py`) :

- `sql_value(value)` (`sql_config.py:262`) = `toSQL(Constant(value), dialect=Dialects.POSTGRES)` - échappe toute
  valeur utilisateur avant inlining. `nullable_value` (`sql_config.py:267`) → `NULL` pour `None`/vide, sinon
  `sql_value`. `bool_literal` (`sql_config.py:279`) inline un bool **contrôlé serveur** (jamais user input).
- `pg_identifier(name)` (`sql_config.py:225`) valide contre `_IDENTIFIER_RE` (`sql_config.py:48`) **et** rejette
  les identifiants > 63 octets (`_MAX_IDENTIFIER_BYTES`, `sql_config.py:57, 235-240`) - anti-troncature
  silencieuse PostgreSQL (NAMEDATALEN) qui pourrait faire **collisionner deux noms logiques** sur le même nom
  physique (L028). Les identifiants ne sont construits **que** depuis des constantes contrôlées + le préfixe
  validé ; jamais d'input utilisateur (`sql_config.py:228-230`).
- Le préfixe admin est borné `_PREFIX_RE = {1,16}` (`sql_config.py:53`) ; un préfixe invalide/trop long est
  **ignoré** (warning une seule fois, mémoïsé) et surfacé à l'admin via `storage_status()`
  (`sql_config.py:131-156, 394-404`).

**Le front ne choisit jamais table / connexion / requête :**

- Table fixe contrôlée : `physical_table(logical)` = `{PROJECT_KEY}_{namespace}_{logical}` (`sql_config.py:370`),
  `full_table` → `public."..."` quotée (`sql_config.py:385-388`). Les `logical` sont des constantes
  (`CHAT_V4_LOGICAL`, `USERS_V1_LOGICAL`, `SETTINGS_V1_LOGICAL`).
- Connexion choisie **par l'admin** dans les Settings DSS (dropdown peuplé par
  `resource/compute_available_connections.py`), jamais hardcodée (`sql_config.py:115-122`). `new_executor()`
  (`sql_config.py:194`) renvoie une `SQLExecutor2` **fraîche par appel** (état transactionnel non partagé entre
  threads) et **lève** si aucune connexion n'est configurée (`sql_config.py:204-207`) - jamais de connexion
  implicite.
- **Aucune route SQL générique** (`/execute-sql`, `/run-query`) : confirmé par grep (CLAUDE règle #3,
  `python-lib/CLAUDE.md:17`). Les seuls textes SQL sont assemblés par `storage/sql_builders.py` à partir de
  fragments **déjà échappés** par le caller + entiers bornés (`sql_builders.py:1-10`).

**Pas de DDL destructive :** seul `CREATE TABLE IF NOT EXISTS` (+ `CREATE INDEX IF NOT EXISTS`), `INSERT`,
`UPDATE … WHERE`, `SELECT` bornés. Audits L015/L016/L026/L027 : grep `DROP|ALTER|TRUNCATE|DELETE|GRANT|REVOKE|
VACUUM` → vide (re-vérifié pour ce document). Idiome `_vN` (jamais d'`ALTER`). Tout `COMMIT` est explicite
(`pre_queries=[...]`, `post_queries=["COMMIT"]` - ex. `chat_v5.py:181-185, 278-281, 324-326` ; `admin.py:81-85,
132-136` ; `settings.py:86-90`).

**Bornes de lignes (caps) :**

| Lecture | Cap | Code |
|---|---|---|
| Messages d'une session (`/conversation`) | `SESSION_MESSAGES_CAP = 500` | `chat_v5.py:417, 473` |
| Liste de conversations (sidebar) | `[1, 60]`, défaut 30 (`validate_conversations_limit`) | `validation.py:144-156` |
| Chaîne d'ancêtres (contexte agent) | `MAX_CHAIN_DEPTH = 200` + LIMIT `n_exchanges` (dérivé de `history_limit`) | `chat_v5.py:332, 358-367` |
| Liste des utilisateurs (admin) | `MAX_USERS_LISTED = 1000` | `admin.py:27, 117` |

---

## 5. Isolation par propriétaire (owner-scoping / pas d'IDOR)

Toute lecture et écriture des conversations, messages, feedback et runs est scopée au `user_id` de l'appelant
résolu depuis les en-têtes (§2). Un appelant ne peut **jamais** lire ou modifier les données d'un autre.

| Donnée | Scoping | Code |
|---|---|---|
| Liste de conversations | `WHERE user_id = {user}` | `sql_builders.py:39` (`build_conversation_list_query`) |
| Messages d'une session | `WHERE user_id = {user} AND session_id = {session}` | `sql_builders.py:57` (`build_session_messages_query`) - un `session_id` appartenant à autrui ne renvoie aucune ligne (`routes.py:744`) |
| Chaîne d'ancêtres (contexte) | user-scopé dans **les deux** membres du CTE récursif (ancre **et** membre récursif) | `sql_builders.py:239, 243` (`build_ancestor_chain_query`) ; `chat_v5.py:360-367` |
| Feedback | `UPDATE … WHERE exchange_id = {exchange} AND user_id = {user}` - no-op (0 ligne) si l'échange n'est pas à l'appelant | `chat_v5.py:286-305` (`save_feedback`) ; route `routes.py:613-664` |
| Poll d'un run | un `run_id` inconnu **ou** appartenant à un autre user → `None` → `404` (sans révéler lequel) | `stream_manager.py:548-565` (test `state.get("user_id") != user_id`, `stream_manager.py:560`) ; `routes.py:568-570` |

Le `parent_exchange_id` fourni par le client est traité défensivement : `validate_optional_exchange_id`
(`validation.py:195-204`) le dégrade en `None` s'il est malformé, et **comme tout read reste user-scopé**, un id
forgé ne peut au pire que matcher les propres lignes de l'appelant (`validation.py:198-200`, commentaire ;
`routes.py:396`).

---

## 6. Evidence Studio (re-exécution de preuve, lecture seule)

Evidence Studio re-exécute le **scope** du SELECT généré par l'agent (stocké dans `generated_sql`) pour
montrer à l'utilisateur les lignes derrière une réponse. C'est la seule surface qui ré-exécute du SQL dérivé
d'un contenu d'agent - elle est donc verrouillée par une chaîne de défenses dédiée
(`python-lib/owismind/evidence/`). **Aucune route SQL générique nouvelle** : le front n'envoie **jamais** de
SQL aux routes `/evidence/*` - seulement un `exchange_id`, des filtres **structurés** `{column, op, values}`,
des ids de chips verrouillées, une page et un tri (`validation.py:328-332`) ; table, connexion, requête et
whitelist sont résolus serveur, et le pipeline est **stateless** (tout re-dérivé par appel, rien de nouveau
stocké - `service.py:1-15`).

| Défense | Mécanisme | Code |
|---|---|---|
| **Datasets auto-découverts (projet seul)** | Les datasets **SQL du projet de la webapp** sont auto-découverts ; aucun paramètre admin à configurer (`service.py:1-15`, `whitelist.py:1-9`). Chaque dataset est résolu à son `(schema, table)` physique via `get_location_info()` (**métadonnées seules**) ; la table du FROM parsé doit matcher (case-insensitive ; schéma absent d'un côté = wildcard). La référence **exécutée** est reconstruite depuis le **candidat résolu**, jamais depuis le SQL parsé (règle qui rend le wildcard sûr). La résolution `(schema, table)` est **mise en cache par process avec TTL 300 s** (`_dataset_candidates`) : `get_location_info()` est un aller-retour de métadonnées par dataset, donc le coût métadonnées passe de N appels par requête `/evidence/*` à ~0 amorti (DSS redémarre le backend sur un changement de config → cache à froid). | `service.py:742-756` ; `whitelist.py:12-32` |
| **Owner-scoping** | Le `generated_sql` est relu `WHERE exchange_id = … AND user_id = …` (LIMIT 1) : l'échange d'autrui ou inexistant → `404 exchange_not_found` (sans révéler lequel). | `query_builders.py:11-18` ; `service.py:577-591` |
| **Fidélité stricte / mode dégradé** | Tout ou rien : chaque colonne de prédicat doit résoudre sur le **schéma live** du dataset, le fragment avancé doit passer `validate_fragment`, deux colonnes ne différant que par la casse → refus (`dataset_schema_invalid`). Sinon `/evidence/meta` renvoie `available:false` + raison **stable** et le panneau n'affiche que le SQL brut - **jamais d'application partielle silencieuse** du scope de l'agent. | `sql_parse.py:36-39` ; `service.py:811-885`, `service.py:1036-1120` |
| **Gate `validate_fragment`** | Le fragment WHERE non décomposable (déjà exécuté par l'agent) est re-validé **à chaque requête** avant ré-emploi : pas de `;`, parens balancées, pas de commentaire, **aucun backslash** (sémantique d'échappement dépendante de la config PG → refus), mots interdits (`select`, `union`, `insert`, `update`, `delete`, `drop`, `set`, `into`, `execute`, …) vérifiés sur les identifiants **nus ET quotés** (`"pg_sleep"(10)` est déquoté puis vérifié), tout nom `pg_*` bloqué, ≤ 2000 chars. Les littéraux string sont masqués par le tokenizer avant le scan (donc `status = 'selected'` passe). Re-check défensif au moment de l'usage. | `sql_parse.py:55-70`, `sql_parse.py:120-167` ; `service.py:933-942` |
| **Requêtes bornées** | Fenêtre `limit`/`offset` explicite : `limit` défaut 50, clampé ≤ 100 ; `offset` clampé ≤ 500 (fenêtre navigable ≤ 600 lignes avant de devoir filtrer) ; `LIMIT limit+1` → `has_more` sans `COUNT(*)` ; distinct ≤ 100 valeurs (+1 → `truncated`) - le picker distinct est **scopé aux prédicats verrouillés + fragment avancé de l'agent** (pas toute la table), avec un plan `DISTINCT … LIMIT` en sous-requête **puis** tri du seul résultat borné (jamais le tri de toutes les valeurs distinctes) ; filtres ≤ 20 ; `IN` ≤ 50 valeurs ; valeur ≤ 500 chars (NaN/Inf rejetés) ; `kept_ids` ≤ 100 ; fragment ≤ 2000 chars ; SQL analysé ≤ 20 000 chars. `ORDER BY` **obligatoire** (pagination OFFSET déterministe), direction normalisée. | `validation.py:336-347` ; `service.py:1126-1172` ; `service.py:1175-1230` (`evidence_distinct`) ; `validation.py:333-350` ; `sql_parse.py:46-55` ; `query_builders.py:21-64` |
| **Lecture seule** | `SELECT` uniquement, **aucun COMMIT** (rien à committer) ; exécution sur la connexion **du dataset whitelisté lui-même** (`SQLExecutor2(dataset=…)`, exécuteur frais par appel), pas sur la connexion de stockage chat. Colonnes exposées = celles du schéma live dont le nom passe `pg_identifier` (les autres sont masquées). | `service.py:24-27`, `service.py:758-780` |
| **Budget d'exécution** | `SET LOCAL statement_timeout TO '30000'` (30 s) en pre-query - **scoped transaction** : une connexion JDBC poolée ne peut jamais l'emporter vers d'autres workloads ; un scan lent ne peut pas pinner un worker du backend mono-process. | `service.py:124` |
| **Rate limiting** | Gate de débit **par utilisateur** dans `_evidence_guard` (après auth/config/bootstrap) : un token-bucket (capacité 15, refill 10/s) absorbe le burst légitime (la paire meta+rows de l'auto-ouverture) mais refuse `429 rate_limited` une rafale scriptée qui pinnerait les threads du backend mono-process. Cœur pur `take_token` déterministe testé ; buckets per-process, idle évincés (TTL 300 s). | `evidence/throttle.py` ; `routes.py:841-875` (`_evidence_guard`) |
| **Bools & quoting** | Les valeurs **bool** (filtres client + littéraux `TRUE`/`FALSE` parsés) sont routées vers `bool_literal` (mot-clé `true`/`false`), jamais `Constant(bool)` (échappement non documenté) ; toute autre valeur passe par `sql_value`, tout identifiant par `pg_identifier`. | `service.py:127-137` ; `validation.py:383-401` |

La validation de route (`validate_evidence_rows_request`, `validation.py:580-615`) ne vérifie que **forme et
bornes** ; l'**existence** des colonnes est revalidée par le service contre le schéma live (un nom inconnu →
`400 invalid_filter_column` / `invalid_sort_column`). Les chips **verrouillées** ne voyagent que comme ids :
leur SQL est re-dérivé serveur depuis le `generated_sql` stocké, le client ne peut pas les altérer
(`service.py:927-930`). Modèle de confiance du fragment : le blocage **par nom** ne couvre que `pg_*` et la
liste de mots interdits - la sûreté large repose sur le fait que le fragment est **écrit par l'agent**,
déjà exécuté, re-validé à chaque requête, et seulement appliqué à un SELECT borné lecture-seule sur une table
whitelistée par l'admin (`sql_parse.py:130-137`). Les parties pures (`sql_parse`, `query_builders`,
`whitelist`, validateurs) sont couvertes par la suite `unittest` DSS-free (`OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/`).

### Source Data Explorer (même modèle lecture seule, datasets bruts configurés par agent)

Le Source Data Explorer (`evidence/source_service.py`, routes `/source/*`) laisse tout utilisateur authentifié
explorer les datasets **bruts** qu'un admin a rattachés à un agent (bloc `sources` de la fiche d'agent). Il
**réutilise le même modèle de sûreté** qu'Evidence : le front n'envoie qu'une **clé d'agent opaque** + un
**index de source entier** + des filtres structurés `{column, op, values}` + un `q` plein-texte (jamais de SQL) ;
le serveur résout l'index vers un dataset **auto-découvert** et exécute un SELECT **borné**. La ré-exécution
hérite des **mêmes pre-queries transaction-scopées** `readonly_pre_queries()` (`statement_timeout 30 s` +
`transaction_read_only`, `source_service.py:16, 290`), du **même token-bucket** par utilisateur (`_source_guard`)
et des mêmes bornes de lignes. Les agrégats (`/source/aggregate`, `/evidence/aggregate`) restent des **specs
structurées** (mesures whitelistées, cœur pur `evidence/aggregate_core.py`) : le front ne fournit jamais
d'expression SQL. Le picker de sources admin (`/admin/sources/datasets`) est admin-gated et dégrade honnêtement.

### Benchmark - lectures SQL cross-projet bornées

La consultation benchmark (`benchmark_view/lab_io.py`, **seul module I/O** du package) lit la table `scored`
qui vit dans le **projet DSS séparé `OWIsMind_LAB`**. La table et la connexion sont **résolues serveur** depuis
la fiche d'agent validée (bloc `benchmark`), **jamais acceptées du client** (qui n'envoie qu'une clé d'agent
opaque). Les lectures sont **bornées** (lecture du scored, détail 1 ligne) ; l'override admin est un **UPDATE
paramétré borné** des seules colonnes `human_*`, réservé aux admins (`/admin/benchmark/override`, bloqué en
impersonation). L'intake collaboratif (`storage/suggestions.py`, `webapp_golden_suggestions_v1`) est
owner-stamped ; c'est le pôle admin LAB qui relit cross-projet et promeut.

---

## 7. Admin

**Bootstrap « premier à ouvrir = admin », déclenché par POST uniquement** (mémoire L027 correctif #7) :

- `/me` accepte `GET` et `POST`, mais l'effet de bord - enregistrer l'utilisateur dans le registre **et**
  l'élection du premier admin - n'a lieu **que sur POST** (`routes.py:189-190`). Un `GET`/prefetch/scanner ne
  peut donc **ni** créer une ligne utilisateur **ni** gagner l'élection (`routes.py:150-158` docstring). Le front
  fait un `POST` une fois à l'init ; `GET` reste read-only ; les deux renvoient la même forme.
- `record_user` (`admin.py:38`) : upsert idempotent + `UPDATE … SET is_admin = true WHERE … AND NOT EXISTS
  (SELECT 1 … WHERE is_admin = true)` (`admin.py:75-79`). L'élection est **sérialisée par un verrou consultatif
  transactionnel** `pg_advisory_xact_lock` (`admin.py:73`, clé `_BOOTSTRAP_LOCK_KEY = 0x4F57494D`,
  `admin.py:35`) → deux premiers utilisateurs concurrents ne peuvent pas devenir admin tous les deux
  (race fermée - L027).

**Routes admin gardées serveur** par `_admin_guard()` (`routes.py:1551-1570`) : résout l'identité (401 sinon),
exige le stockage configuré (409 sinon), exige `admin.is_admin(user_id)` (403 `forbidden` sinon). Appliqué à
`/admin/storage`, `/admin/users`, `/admin/users/set-admin`, `/admin/projects`, `/admin/projects/<key>/agents`,
`/admin/agents` (`routes.py:1572, 1581, 1595, 1729, 1743, 1770`). `is_admin` (`admin.py:88`) lit le flag persistant ;
la garde côté router front n'est que cosmétique (L027 Info).

**Garde-fou anti-lockout :** `set-admin` ne retire jamais le **dernier** admin restant -
`if not value and is_admin(target) and count_admins() <= 1 → 400 cannot_remove_last_admin` (`routes.py:1609-1610`,
`admin.count_admins` `admin.py:99`).

**Note opérationnelle (TOFU, L026 note a / PROJECT_STATE §12 item 5) :** le premier utilisateur à ouvrir l'app
**après** configuration devient admin → s'assurer en déploiement que c'est bien l'admin déployeur.

**Impersonation admin (frontière de confiance, TEMPORAIRE - gardée pour la bêta, code fencé et supprimable,
`security/impersonation.py`) :** un admin peut consulter la webapp « à la place » d'un autre utilisateur pour
diagnostiquer. Garanties :

- **Admin-gated à la source.** `effective_identity(real_identity)` (`impersonation.py:35`) lit l'en-tête
  `X-OWI-Impersonate` (`IMPERSONATION_HEADER`, `impersonation.py:32`) **directement depuis `flask.request`**,
  et ne bascule vers l'identité cible **que si le caller réel est admin** ; sinon l'en-tête est ignoré (un
  non-admin ne peut jamais se faire passer pour autrui).
- **Lecture seule stricte.** Seules les routes de **LECTURE** utilisent l'identité **effective** (la cible :
  `/me`, `/usage`, `/conversations`, `/conversation`, `_evidence_guard`, `_source_guard`,
  `/benchmark/suggestions`). Toutes les routes d'**ÉCRITURE** (`/chat/start`, `/chat/stop`, `/chat/feedback`,
  `/benchmark/suggest`, `/benchmark/suggest-from-chat`, `/admin/benchmark/override`) refusent
  `403 impersonation_read_only` **avant tout travail** : un admin ne peut jamais écrire sous une autre identité.
- **Analytics neutralisée.** `POST /track` **droppe** silencieusement les events émis pendant une impersonation
  (aucune activité fantôme attribuée à la cible).

---

## 8. Sûreté de l'instance Dataiku

Exigence non négociable (CLAUDE règle #2) : aucun code risqué, lent ou surchargeant pour l'instance.

**Requêtes bornées + caps de lignes :** voir §4 (caps) - chaque `SELECT` est borné (LIMIT) ; le CTE récursif est
borné en profondeur **et** par LIMIT.

**Worker de fond borné (`agents/stream_manager.py`) - pourquoi du polling, pas du SSE :** le nginx interne DSS
peut bufferiser un `text/event-stream` long → le pattern est : run agent dans un **thread daemon**, accumulation
dans un dict module-level, le front **poll** des requêtes courtes (mémoire L019). Garde-fous :

| Garde-fou | Valeur / mécanisme | Code | Sortie |
|---|---|---|---|
| Cap de concurrence global | `MAX_CONCURRENT_RUNS = 8` (hard cap, vérifié sous `_LOCK` dans `start_run`) | `stream_manager.py:40, 188-190` | `503 busy` |
| Pré-check d'admission (avant tout write) | `can_accept(user_id)` : cap global + rate-gate par user | `stream_manager.py:96-119` ; `routes.py:425-430` | `503 busy` / `429 rate_limited` |
| Rate-gate par utilisateur | `MIN_START_INTERVAL_SECONDS = 1.0` (timestamp réservé **sous le même lock** → pas de TOCTOU spam, L027) | `stream_manager.py:81, 113-119` | `429 rate_limited` |
| Éviction TTL (run fini) | `FINISHED_TTL_SECONDS = 60.0` | `stream_manager.py:45, 152` | - |
| Éviction TTL (lifetime absolu) | `HARD_TTL_SECONDS = 600.0` → zéro fuite de run orphelin | `stream_manager.py:50, 154` | - |
| Deadline wall-clock coopérative | `MAX_RUN_SECONDS = 300.0` (entre chunks) | `stream_manager.py:75, 136` | `error: run_timeout` |
| Arrêt coopératif si tab abandonné | `ABANDON_AFTER_SECONDS = 30.0` (via `last_poll_at`) → libère slot/thread/connexion LLM | `stream_manager.py:76, 138` ; heartbeat `stream_manager.py:563` | `error: run_abandoned` |
| Bornes mémoire par run | `MAX_LIVE_EVENTS = 5000`, `MAX_ANSWER_CHARS = 1_000_000` (events terminaux & persistance jamais bornés) | `stream_manager.py:59-60, 346-353` | - |

> **Limite connue (documentée, pas un bug) :** deadline & abandon sont évalués **entre chunks** ; un appel
> upstream totalement figé qui ne yield jamais reste borné uniquement par le TTL mémoire. Un watchdog dédié
> n'est **pas** ajouté (risque plus élevé sur un chemin validé) - `stream_manager.py:72-74`, mémoire L027.

**Hypothèse mono-process (note opérationnelle) :** `_RUNS`, `_LOCK`, `_LAST_START_BY_USER` et le cache d'identité
sont per-process. En multi-process : poll cross-process en 404, cap ×N, rate-gate par process. **À forcer/vérifier
1 process** sur l'instance (L028 escalade F-01/DOC-01 ; PROJECT_STATE §12 cond. C1).

**Borne de longueur de message :** `MAX_MESSAGE_LENGTH = 8000` (`validation.py:16, 46-50`) - rejette les
payloads pathologiques avant tout traitement.

**Cap du texte persisté (sûreté des logs CRU) :** `MAX_PERSISTED_TEXT_CHARS = 262_144` borne `user_text` /
`assistant_text` **persistés** (`chat_v5.py:68, 80-88, 143, 237`). Raison (mémoire L027) : DSS **logue chaque
requête `SQLExecutor2`** (texte complet) et `SQLExecutor2` n'a **aucun bind serveur** → `sql_value` inline
toujours la valeur dans l'INSERT/UPDATE loggé ; un scénario DSS matérialisant ces logs en dataset peut tripper
la limite de longueur de ligne. Les traces (Mo) - vrai coupable historique - évitent entièrement ce chemin via
le **writer de dataset** (write-only, `chat_traces`, L027/L028).

**Logging content-free (hygiène) :** `/chat/start` logue `user_id`, `session_id`, `agent_key` et `msg_len`
**jamais le contenu** du message (`routes.py:414-420`, commentaire explicite). Les INSERT/UPDATE complets (qui
inlineraient le corps) ne sont **pas** logués (`chat_v5.py:180, 277`). En cas d'échec agent, aucun interne
agent/SQL/connexion n'est divulgué au client (`stream_manager.py:533-537` → `error: agent_unavailable`).

**API DSS en lecture seule (+ run agent) :** seules des méthodes de lecture sont appelées
(`get_auth_info_from_browser_headers`, `get_webapp_config`, `default_project_key`, `list_connections`,
`list_datasets`/`read_schema`, listing projets/agents) + l'exécution d'agent ; **jamais** `set_*`/`save`/`delete`/
`set_variables`/`set_definition` (audits L015/L016/L026). Les traces sont **append write-only** sur un dataset Flow
admin-sélectionné (jamais relu en ligne - `/chat/trace` supprimé, L027/L028).

---

## 9. Hygiène & recommandations

**Délibérément non logué :** le contenu des messages utilisateur / réponses agent (seulement longueurs &
métadonnées, §8) ; les valeurs d'en-tête porteuses de credentials (`identity.py:96-97`) ; les noms de connexions
sont passés en DEBUG (compte seul en INFO, L026 correctif #4). `/ping` est volontairement minimal : il
**n'expose pas** la config de stockage (connexion, project key, noms de tables) car il est atteignable sans
authentification (`routes.py:140-147`) ; `storage_status()` n'est accessible qu'aux admins via `/admin/storage`.

**Analytics d'usage - vie privée (best-effort, `POST /track`, `storage/events.py`, mémoire L125) :** le
tracking produit ne capture **jamais** de contenu. Les hooks front n'émettent que des **métadonnées** : une
recherche est réduite à sa **longueur** (`{len}`, jamais le terme saisi) et les events d'erreur portent le
**chemin sans query string** (le fix HIGH de la revue adversariale L125 : une query string pouvait porter des
PII). Côté serveur, `validate_events` n'accepte que des **noms d'events whitelistés** (`EVENT_CATEGORIES`,
source de vérité ; un nom inconnu/forgé est droppé en silence) et **cape** les props (`MAX_PROPS_JSON_CHARS`) et
la taille de batch ; `record_events` fait un unique INSERT `ON CONFLICT DO NOTHING`. La route **ne renvoie
jamais 500** (best-effort) et **droppe** les events émis pendant une impersonation admin.

**Codes d'erreur stables, sans détail interne :** `ValidationError(code)` renvoie un code machine stable et sûr
(jamais d'interne) au front (`validation.py:25-31`). Notamment, le rating de feedback **rejette explicitement les
bools** (`True`/`False` sont sous-classes d'`int`) : seuls `0`, `1` ou `None` sont acceptés
(`validation.py:181-183`), et les raisons sont restreintes à une whitelist puis cappées
(`ALLOWED_FEEDBACK_REASONS`, `MAX_FEEDBACK_REASONS = 8`, commentaire borné `MAX_FEEDBACK_COMMENT_CHARS = 2000` -
`validation.py:160-162, 184-191`).

**Recommandation / non implémenté - TEST-01 (durcissement tests, PROJECT_STATE §12 item 3) :** plusieurs
invariants de sécurité déjà durcis ne sont **pas** couverts par des tests unitaires (les tests actuels couvrent
surtout les bornes de `validation.py`, les builders SQL purs et les modules purs d'`evidence/`). Recommandé
(DSS-free, via stubs `dataiku`/`pandas`) :
`sql_config.pg_identifier` (rejet injection / > 63 octets), `serialization.rows_to_json_safe` (NaN→None),
`settings.resolve_enabled_agent` (clé forgée → `None`), `stream_manager` (cap / TTL / poll-owner /
`_stop_reason`), `chat_traces.save_trace` (no-op / troncature) ; + brancher `py_compile`/`compileall` sur
`python-lib` comme CI minimale. **Statut : NON fait.**

**Autres recommandations / points opérationnels à verrouiller en déploiement** (notes, pas des failles) :
forcer le backend Flask DSS à **1 process** (§1, §8 ; L028) ; confirmer que l'admin déployeur est bien le premier
à ouvrir l'app (TOFU, §7) ; vérifier que le `traces_dataset` est adossé SQL (pas CSV/filesystem) et que l'append
accumule (L027/L028).
