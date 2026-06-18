# Modèle de sécurité (transversal) - OWIsMind

> Pack de connaissances destiné à la rédaction de documentation utilisateur et développeur.
> Toutes les affirmations sont ancrées dans le code ou la doc effectivement lus, sous la forme `chemin:ligne`.
> Les divergences doc-vs-code et les points incertains / en cours d'évolution sont marqués explicitement.
> Convention typographique : aucun tiret cadratin ni demi-cadratin (regle projet #9). Identifiants, chemins,
> noms de tables et ids de config conserves VERBATIM en anglais.

OWIsMind est un plugin Dataiku DSS : WebApp Vue 3 + Vite (assets statiques servis par DSS) + backend Flask
modulaire (`Plugin/owismind/python-lib/owismind/`) qui parle aux agents via LLM Mesh et stocke tout en SQL
direct (`SQLExecutor2`, PostgreSQL, schema `public`), sans Flow au runtime. La couche agent (orchestrateur +
sous-agent revenus) vit dans `dataiku-agents/` sous forme de Code Agents LangGraph.

La source de verite operationnelle du modele de securite est le document `docs/security.md` (synthese verifiee
contre le code) plus `Plugin/owismind/python-lib/CLAUDE.md` (regles backend) et le `CLAUDE.md` racine (regles
NON NEGOCIABLES #1 a #9).

---

## 1. Posture et modele de menace

OWIsMind est une WebApp MULTI-UTILISATEURS servie par une instance DSS PARTAGEE : tout utilisateur authentifie
sur l'instance peut l'ouvrir (`docs/security.md:19-20`). La posture repose sur quatre invariants
(`docs/security.md:22-27`) :

1. Frontiere de confiance = le navigateur. Tout ce qui vient du navigateur est non fiable (corps de requete,
   params de query, en-tetes applicatifs). Toute requete est validee et bornee avant d'atteindre SQL
   (`security/validation.py`).
2. Identite resolue cote serveur. L'identite de l'appelant n'est JAMAIS lue dans le corps : elle est resolue
   depuis les en-tetes d'authentification DSS du navigateur (`security/identity.py:101`).
3. Le front n'envoie que des donnees logiques : `session_id`, `message`, une cle d'agent logique OPAQUE, une
   taille de fenetre de contexte, un `parent_exchange_id` optionnel, un feedback, un `mode` (eco/medium/high)
   et `webapp_lang`. Il NE choisit jamais table, colonne, connexion, requete, ni `agent_id` brut
   (`security/validation.py:1-8`).
4. Aucune surface SQL generique : pas de route `/execute-sql` ni `/run-query` ; le SQL est construit serveur a
   partir de constantes controlees (`python-lib/CLAUDE.md:17`).

Modele d'execution (notes operationnelles) :
- L'agent s'execute sous l'identite de la WebApp (LLM Mesh), pas sous celle de l'utilisateur final. Tout agent
  WHITELISTE est donc joignable par tout utilisateur authentifie ; la responsabilite d'exposition incombe a
  l'admin via la whitelist (`docs/security.md:31-33`).
- Le modele polling + etat `_RUNS` en memoire suppose un backend DSS MONO-PROCESS : cap de concurrence,
  ownership des runs et cache d'identite sont per-process (`docs/security.md:34-37`). A FORCER / VERIFIER a 1
  process sur l'instance (point operationnel a verrouiller en deploiement).

---

## 2. Deux identites : utilisateur connecte vs run-as-user du backend

Distinction CENTRALE et souvent mal comprise. Il existe deux identites distinctes dans le systeme.

| Aspect | Utilisateur DSS connecte (caller) | Run-as-user du backend (WebApp identity) |
|---|---|---|
| Origine | En-tetes d'auth du navigateur (cookie de session DSS) | Identite sous laquelle tourne le backend de la WebApp DSS |
| Resolution | `resolve_identity(request.headers)` -> `dataiku.api_client().get_auth_info_from_browser_headers(...)` (`identity.py:91-98`, `identity.py:101`) | Implicite : c'est sous cette identite que `dataiku.api_client()`, `SQLExecutor2`, l'exec d'agent LLM Mesh et `list_project_keys()` s'executent |
| Valeur cle | `user_id = authIdentifier` (login DSS, ex. `said.chaoui`) (`identity.py:125`) | N'apparait jamais comme valeur dans le code ; c'est le contexte d'execution DSS |
| Role | Scoping de TOUT le stockage chat (owner-scoping, voir section 6) ; election admin | Execute reellement le SQL et appelle les agents ; voit les projets/agents/datasets selon SES permissions |
| Visibilite des projets/agents | N/A | `discovery.list_project_keys()` "reflects the running identity's permissions: only projects it may access are listed" (`discovery.py:34-43`) |
| Execution SQL | N/A | `SQLExecutor2(connection=conn)` sur la connexion admin-configuree (`sql_config.py:193-207`) |

Consequence de securite majeure : le SQL et les appels d'agent s'executent sous l'identite UNIQUE du backend
(run-as-user), pas sous celle de chaque utilisateur final. C'est pourquoi tout agent whiteliste est joignable
par tout utilisateur authentifie : l'isolation entre utilisateurs ne vient PAS de DSS au niveau SQL, elle est
appliquee DANS le code applicatif par owner-scoping sur `user_id` (section 6). Le `webapp.json`
(`webapps/webapp-owismind-ai-agents/webapp.json`) ne declare AUCUN champ de run-as-user explicite : la WebApp
utilise le comportement de run-as par defaut de DSS pour son backend. INCERTAIN / a verrouiller en deploiement :
le document de securite recommande de confirmer que le backend tourne bien sous l'identite voulue et a 1 process
(`docs/security.md:261-263`, `docs/security.md:312-315`).

### Resolution d'identite, en detail

- `_auth_info(headers)` (`identity.py:91-98`) : un client API DSS FRAIS par appel (leger, thread-safe sous
  workers Flask concurrents). Les valeurs d'en-tete peuvent porter des credentials, donc elles ne sont JAMAIS
  loguees (`identity.py:96-97`).
- `resolve_identity(headers)` (`identity.py:101-159`) renvoie le dict `{user_id, display_name, groups}` :
  - `user_id` = `info.get("authIdentifier")` (`identity.py:125`). Forme reelle validee en DSS (memoire L011) :
    DSS ne renvoie PAS de `displayName`.
  - `groups` = `info.get("groups") or []`, normalise en liste (`identity.py:134-136`).
  - `display_name` = `derive_display_name(user_id)` (prenom capitalise derive du login, `identity.py:45-68`,
    `identity.py:141`) : `said.chaoui -> Said`, `jean-marc.dupont -> Jean-Marc`. Ce n'est qu'un DEFAUT.
- Echec -> 401. Toute defaillance leve `IdentityError` (`identity.py:18-19`), mappee en `401 unauthenticated`
  dans CHAQUE route (par ex. `routes.py:131-134`, `routes.py:204-207`, `routes.py:334-337`,
  `routes.py:720-722`). Deux causes : lookup DSS en echec -> `IdentityError("auth_lookup_failed")`
  (`identity.py:119-123`) ; aucun `authIdentifier` -> `IdentityError("no_auth_identifier")`
  (`identity.py:126-132`).

### Cache d'identite (surete, pas une faille)

Un cache per-process a TTL court (`_AUTH_TTL_SECONDS = 5.0`, `identity.py:28`) cle sur une EMPREINTE SHA-256 du
cookie (`_identity_cache_key`, `identity.py:34-42`) collapse les lookups DSS repetes de `/chat/poll` (environ 2
Hz par chat). Seuls les lookups REUSSIS sont caches (`identity.py:150-154`) ; eviction opportuniste bornee par
`_AUTH_CACHE_MAX = 512` (`identity.py:29`, `identity.py:155-158`). Le cache cle sur le cookie ne mute jamais
l'identite d'un autre utilisateur : un cookie different produit une empreinte differente.

Gotcha : le cache et tout `_RUNS`/`_LAST_START_BY_USER` sont per-process. En multi-process le poll cross-process
renverrait 404, le cap serait multiplie par N, et le rate-gate serait par process (`docs/security.md:261-263`).
D'ou la recommandation 1-process.

---

## 3. Whitelist d'agents cote serveur

Invariant (regle NON NEGOCIABLE #4) : le front ne recoit et n'envoie qu'une cle logique OPAQUE ; le backend
resout `(project_key, agent_id)` uniquement si l'agent est active ; une cle forgee ou desactivee resout `None`.
Le `agent_id` brut ne traverse JAMAIS vers le front.

### Forme de la cle logique opaque

`_logical_key(project_key, agent_id)` (`routes.py:72-82`) :

```python
digest = hashlib.sha1("{}:{}".format(project_key, agent_id).encode("utf-8")).hexdigest()
return "ag_" + digest[:12]
```

Soit `"ag_" + sha1(f"{project_key}:{agent_id}")[:12]` : stable (re-sauver la selection garde la meme cle) et
opaque (le front ne voit jamais l'`agent_id` brut). Borne cote validation : `MAX_AGENT_KEY_LENGTH = 64`
(`validation.py:19`, controle dans `validate_chat_start_request`, `validation.py:101-105`).

### Liste exposee au chat

`GET /agents` (`routes.py:515-550`) projette UNIQUEMENT `{key, label}` :

```python
public = [{"key": a.get("logical_key"), "label": a.get("label")}
          for a in enabled if a.get("logical_key")]
```

(`routes.py:540-544`). Jamais `agent_id` ni `project_key`.

### Resolution (point d'enforcement du chemin chat)

`settings.resolve_enabled_agent(logical_key)` (`storage/settings.py:103-117`) parcourt la liste activee et
renvoie l'entree `{logical_key, project_key, agent_id, label}` SEULEMENT si elle correspond a un agent reel
encore active, sinon `None` :

```python
if not logical_key:
    return None
for agent in get_enabled_agents():
    if agent.get("logical_key") == logical_key:
        return agent
return None
```

Dans `/chat/start` (`routes.py:235-240`) : `agent = settings.resolve_enabled_agent(agent_key)` ; si `not agent`
-> `404 agent_not_enabled` et le run n'est JAMAIS lance. Le `agent_id` resolu reste serveur de bout en bout :
passe au worker via `stream_manager.start_run(project_key, agent_id, ...)` (`routes.py:306-310`) ; le front ne
recoit que le `run_id` opaque (`routes.py:318`). Le worker lui-meme ne surface jamais l'`agent_id` au client
(`stream_manager.py:271-272`, `streaming.py:21-22`).

### Whitelist inviolable a l'ecriture (admin)

`POST /admin/agents` (`routes.py:825-912`) RE-VALIDE chaque agent demande contre les listings DSS LIVE avant
de persister : projet visible (`discovery.list_project_keys()`, `routes.py:856`, `routes.py:872`) ET agent
reellement present dans ce projet (`discovery.list_project_agents(project_key)`, `routes.py:877-888`). Un
`agent_id` forge depuis le front ne peut jamais etre persiste (il est "skipped" avec warning,
`routes.py:882-888`). Cap defensif `MAX_ENABLED_AGENTS = 50` (`routes.py:63`, `routes.py:852-853`). La
discovery est STRICTEMENT read-only (`discovery.py:8-12`), bornee (`MAX_PROJECTS = 500`, `MAX_AGENTS = 200`,
`discovery.py:25-26`), et un agent est tout LLM dont l'id commence par `agent:` (`AGENT_ID_PREFIX = "agent:"`,
`discovery.py:21`, `discovery.py:55-57`).

### Stockage de la whitelist

La whitelist vit dans la table de settings globale `webapp_settings_v1` sous la cle
`SETTING_ENABLED_AGENTS = "enabled_agents"` (`settings.py:29`), une liste JSON de dicts
`{logical_key, project_key, agent_id, label}` (`settings.py:88-95`). La colonne `agent_key` stockee cote chat
est la cle logique OPAQUE, jamais l'`agent_id` brut.

Gotcha : la garde cote router front (UI) n'est que cosmetique ; l'enforcement reel est `resolve_enabled_agent`
serveur (`docs/security.md:224`). Une cle stale (agent retire de la whitelist apres coup) resout aussi `None`
car elle ne matche plus aucune entree activee.

---

## 4. Secrets et configuration

Aucun secret n'est present dans le repo. La configuration sensible est entierement geree par DSS et l'admin.

- Connexion SQL : ADMIN-configuree dans les Settings de la WebApp via un vrai dropdown SELECT
  (`webapp.json` param `sql_connection`, `getChoicesFromPython: true`, peuple par
  `resource/compute_available_connections.py` via `list_connections()`). Resolue cote serveur par
  `sql_config.connection_name()` (`sql_config.py:114-121`), JAMAIS hardcodee (`sql_config.py:1-19`,
  `python-lib/CLAUDE.md:11-13`). Tant qu'aucune connexion n'est configuree, l'app reporte
  "storage_not_configured" plutot que de deviner (`sql_config.py:178-180`, `is_configured()`), et
  `new_executor()` LEVE si aucune connexion n'est configuree (`sql_config.py:202-206`) : jamais de connexion
  implicite.
- Connexion LLM Mesh : geree par DSS. Le code appelle `project.get_llm(agent_id).new_completion()` et streame
  (`streaming.py:4-8`) ; aucun token / cle d'API d'un fournisseur LLM ne transite par le repo.
- Autres params (`webapp.json`) : `table_prefix` (optionnel, borne, voir section 5), `traces_dataset`
  (dataset Flow optionnel, WRITE-ONLY, jamais relu en ligne, `sql_config.py:163-175`), `log_level`.
- Project key : resolu env -> webapp config -> `dataiku.default_project_key()` -> constante de repli
  `OWISMIND_DEV` (`sql_config.py:86-107`). C'est une constante d'infrastructure, pas un secret.

---

## 5. Surete SQL

Stockage en SQL direct (`SQLExecutor2`, PostgreSQL, schema `public`), SANS Flow au runtime (regle NON
NEGOCIABLE #3).

### Parametrage des valeurs, jamais de f-string autour d'input utilisateur

Tout `python-lib/CLAUDE.md:24-25` l'impose : "Parametrize all user input ... Never build SQL with f-strings
around user content." Les helpers centraux (`storage/sql_config.py`) :

- `sql_value(value)` (`sql_config.py:229-231`) = `toSQL(Constant(value), dialect=Dialects.POSTGRES)` : echappe
  toute valeur utilisateur avant inlining.
- `nullable_value(value)` (`sql_config.py:234-243`) -> bare `NULL` pour `None`/vide, sinon `sql_value`.
- `bool_literal(value)` (`sql_config.py:246-254`) inline un bool CONTROLE SERVEUR (`"true"`/`"false"`), jamais
  `Constant(bool)` dont l'echappement n'est pas documente.
- `pg_identifier(name)` (`sql_config.py:210-226`) valide contre `_IDENTIFIER_RE`
  (`^[A-Za-z_][A-Za-z0-9_-]*$`, `sql_config.py:47`) ET rejette les identifiants > 63 octets
  (`_MAX_IDENTIFIER_BYTES`, `sql_config.py:56`, `sql_config.py:220-225`), anti-troncature silencieuse
  PostgreSQL (NAMEDATALEN) qui pourrait faire collisionner deux noms logiques sur le meme nom physique. Les
  identifiants ne sont construits QUE depuis des constantes controlees + le prefixe valide ; JAMAIS d'input
  utilisateur (`sql_config.py:210-216`).

Le prefixe admin est borne `_PREFIX_RE = ^[A-Za-z0-9_-]{1,16}$` (`sql_config.py:52`) ; un prefixe
invalide/trop long est IGNORE (warning memoise une seule fois) et surface a l'admin via `storage_status()`
(`sql_config.py:130-155`, `sql_config.py:282-292`).

### Le front ne choisit jamais table / connexion / requete

- Table fixe controlee : `physical_table(logical) = {PROJECT_KEY}_{namespace}_{logical}`
  (`sql_config.py:264-270`), `full_table(logical)` -> `public."..."` quotee (`sql_config.py:273-276`). Les
  `logical` sont des CONSTANTES (`webapp_chat_v5`, `webapp_users_v1`, `webapp_settings_v1`,
  `webapp_usage_monthly_v1`, `sql_config.py:297-302`).
- Connexion choisie par l'ADMIN (dropdown Settings DSS), jamais hardcodee. `new_executor()`
  (`sql_config.py:193-207`) renvoie une `SQLExecutor2` FRAICHE par appel (etat transactionnel non partage
  entre threads).
- AUCUNE route SQL generique : confirme par la regle #3 et `python-lib/CLAUDE.md:17`. Les seuls textes SQL sont
  assembles par `storage/sql_builders.py` et les modules `storage/*` a partir de fragments deja echappes.

### Discipline COMMIT, pas de DDL destructive

Tout `COMMIT` est explicite via `post_queries=["COMMIT"]` (par ex. `admin.py:81-85`, `admin.py:132-136`,
`settings.py:77-81`). Seuls `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`, `INSERT`,
`UPDATE ... WHERE`, `SELECT` bornes. Idiome `_vN` (jamais d'`ALTER`). Grep `DROP|ALTER|TRUNCATE|DELETE|GRANT|
REVOKE|VACUUM` -> vide (audit `docs/security.md:134-138`).

### Bornes de lignes (caps)

| Lecture | Cap | Code |
|---|---|---|
| Messages d'une session (`/conversation`) | `SESSION_MESSAGES_CAP = 500` | `docs/security.md:144` |
| Liste de conversations (sidebar) | `[1, 60]`, defaut 30 | `validation.py:136-153` (`validate_conversations_limit`) |
| Fenetre de contexte agent (messages) | `[10, 50]`, defaut 20 | `validation.py:111-132` (`validate_history_limit`) |
| Chaine d'ancetres (contexte agent) | `MAX_CHAIN_DEPTH = 200` + LIMIT | `docs/security.md:146` |
| Liste des utilisateurs (admin) | `MAX_USERS_LISTED = 1000` | `admin.py:27`, `admin.py:117` |
| Longueur de message | `MAX_MESSAGE_LENGTH = 8000` | `validation.py:13`, `validation.py:43-47` |

---

## 6. Isolation par proprietaire (owner-scoping, anti-IDOR)

Comme le SQL s'execute sous une identite unique (section 2), l'isolation entre utilisateurs est appliquee DANS
le code par scoping systematique sur le `user_id` resolu des en-tetes. Un appelant ne peut JAMAIS lire ou
modifier les donnees d'un autre.

| Donnee | Scoping | Reference |
|---|---|---|
| Liste de conversations | `WHERE user_id = {user}` | `docs/security.md:158` |
| Messages d'une session | `WHERE user_id = {user} AND session_id = {session}` (un session_id d'autrui -> 0 ligne) | `routes.py:497-509`, `docs/security.md:159` |
| Chaine d'ancetres (contexte) | user-scope dans les DEUX membres du CTE recursif | `docs/security.md:160` |
| Feedback | `UPDATE ... WHERE exchange_id AND user_id` -> no-op si l'echange n'est pas a l'appelant | `routes.py:386-395`, `docs/security.md:161` |
| Poll d'un run | un `run_id` inconnu OU appartenant a un autre user -> `None` -> `404` | `stream_manager.py:526-539` (test `state.get("user_id") != user_id`), `routes.py:349-351` |
| Stop d'un run | meme test owner-scope -> `False` -> `404` | `stream_manager.py:553-569`, `routes.py:379-380` |
| Artefacts (screen context) | lecture OWNER-SCOPED ; un `exchange_id` forge ne revele que les donnees de l'appelant | `routes.py:172-187`, `stream_manager.py:232-256` |
| Evidence (meta/rows/distinct) | `generated_sql` relu `WHERE exchange_id AND user_id` (LIMIT 1) -> 404 si l'echange d'autrui | `docs/security.md:185`, section 7 |

Le `parent_exchange_id` fourni par le client est traite defensivement : `validate_optional_exchange_id`
(`validation.py:192-201`) le degrade en `None` s'il est malforme, et comme tout read reste user-scope, un id
forge ne peut au pire que matcher les PROPRES lignes de l'appelant (`validation.py:194-198`).

Les 404 owner-scope ne revelent jamais LEQUEL des cas (inconnu vs appartenant a autrui) est tombe, ce qui evite
une oracle d'existence (`routes.py:349-351`, `stream_manager.py:529-530`).

---

## 7. Evidence Studio : re-execution de preuve, lecture seule

Evidence Studio est la SEULE surface qui re-execute du SQL derive d'un contenu d'agent (le SELECT stocke dans
`generated_sql`). Le front n'envoie JAMAIS de SQL aux routes `/evidence/*` : seulement un `exchange_id`, des
filtres STRUCTURES `{column, op, values}`, des ids de chips verrouillees, une page et un tri
(`validation.py:204-208`, `validate_evidence_rows_request` `validation.py:268-364`). Table, connexion, requete
et matching de dataset sont resolus SERVEUR, et le pipeline est STATELESS (tout re-derive par appel, rien de
neuf stocke, `service.py:1-29`).

Chaine de defenses (modules `evidence/`) :

- Decouverte de datasets (admin-free) : les datasets sources sont DECOUVERTS automatiquement parmi les datasets
  SQL-backed du projet de la WebApp (`_SQL_DATASET_TYPES = {"PostgreSQL"}`, `service.py:90`,
  `service.py:86-92`), pas de whitelist admin a configurer. Le matching se fait sur la table parsee
  (`match_whitelist`, `whitelist.py:12-32`) ; la reference EXECUTEE est reconstruite depuis le CANDIDAT resolu
  (son `(schema, table)` physique via `get_location_info()`, metadonnees seules), jamais depuis le SQL parse, ce
  qui rend le wildcard de schema sur. Resolution `(schema, table)` mise en cache par process TTL 300 s
  (`_CANDIDATES_TTL_SECONDS`, `service.py:94-101`).
  - DIVERGENCE DOC-vs-CODE A SIGNALER : `docs/security.md:184` decrit une whitelist admin de datasets via un
    param webapp `evidence_datasets` (SELECT). Le code ACTUEL (`whitelist.py:1-9`, `service.py:6-8`,
    `service.py:86-89`) decouvre les datasets AUTOMATIQUEMENT ("no admin whitelist to configure") et le
    `webapp.json` ne declare AUCUN param `evidence_datasets`. Le code prime : la doc de securite est en retard
    sur ce point precis. A confirmer avec l'equipe (en cours d'evolution).
- Owner-scoping : `generated_sql` relu `WHERE exchange_id AND user_id` (LIMIT 1) ; echange d'autrui ou
  inexistant -> `404 exchange_not_found` (`docs/security.md:185`).
- Fidelite stricte / mode degrade : tout ou rien. Chaque colonne de predicat doit resoudre sur le SCHEMA LIVE
  du dataset, le fragment avance doit passer `validate_fragment`, deux colonnes ne differant que par la casse ->
  refus. Sinon `/evidence/meta` renvoie `available:false` + raison stable et le panneau n'affiche que le SQL
  brut, jamais d'application partielle silencieuse (`docs/security.md:186`).
- Gate `validate_fragment` (`sql_parse.py:120-145` et suite) : le fragment WHERE non decomposable (deja execute
  par l'agent) est RE-VALIDE a chaque requete : pas de `;`, parens balancees, pas de commentaire
  (`tokenize` rejette `--` et `/*`, `sql_parse.py:112-113`), AUCUN backslash (semantique d'echappement
  dependante de la config PG -> refus, `sql_parse.py:140-144`), mots interdits (`_BANNED_FRAGMENT_WORDS` :
  `select`, `union`, `insert`, `update`, `delete`, `drop`, `set`, `into`, `execute`, ..., `sql_parse.py:60-64`)
  verifies sur identifiants nus ET quotes, tout nom `pg_*` bloque, <= 2000 chars (`MAX_FRAGMENT_CHARS`,
  `sql_parse.py:55`). Les litteraux string sont masques par le tokenizer avant le scan (donc
  `status = 'selected'` passe, `sql_parse.py:127-128`). Modele de confiance EXPLICITE : le blocage par nom ne
  couvre que `pg_*` et la liste de mots ; la surete large repose sur le fait que le fragment est ECRIT par
  l'agent, deja execute, re-valide a chaque requete, et seulement applique a un SELECT borne lecture-seule sur
  un dataset decouvert (`sql_parse.py:130-134`).
- Requetes bornees : 50 lignes/page (`PAGE_SIZE = 50`, `LIMIT 51 -> has_more` sans `COUNT(*)`,
  `service.py:68`) ; distinct <= 100 valeurs (`DISTINCT_LIMIT = 100`, `service.py:69`) ; page clampee <= 20
  (`MAX_EVIDENCE_PAGE = 20`, `validation.py:216`) ; filtres <= 20 (`MAX_EVIDENCE_FILTERS = 20`,
  `validation.py:209`) ; `IN` <= 50 valeurs (`validation.py:210`) ; valeur <= 500 chars, NaN/Inf rejetes
  (`_validate_evidence_value`, `validation.py:245-265`) ; `kept_ids` <= 100 (`validation.py:217`) ; SQL analyse
  <= 20 000 chars (`MAX_SQL_CHARS`, `sql_parse.py:46`).
- Lecture seule : `SELECT` uniquement, AUCUN COMMIT, execution sur la connexion DU dataset decouvert lui-meme
  (`_evidence_executor` -> `SQLExecutor2(dataset=dataiku.Dataset(dataset_name))`, executeur frais par appel,
  `service.py:769-771`), pas sur la connexion de stockage chat.
- Budget d'execution + read-only force : pre-queries `SET LOCAL statement_timeout TO '30000'` (30 s) et
  `SET LOCAL transaction_read_only TO on` (`_EVIDENCE_TIMEOUT_PRE_QUERIES`, `service.py:120-123`). SET LOCAL
  (pas SET) -> TRANSACTION-scoped : une connexion JDBC poolee ne peut jamais l'emporter vers d'autres
  workloads (`service.py:111-119`). `transaction_read_only` = defense en profondeur : toute regression future
  echoue bruyamment au lieu d'ecrire.
- Rate limiting par utilisateur : `_evidence_guard` (`routes.py:556-584`) applique un token-bucket
  (`evidence_throttle.can_accept`, `routes.py:581-583`) -> `429 rate_limited` sur rafale scriptee.
- Selecteur de table source optionnel (multi-table) : un identifiant borne (`MAX_EVIDENCE_TABLE_CHARS = 256`,
  `validation.py:223`) ; le service le matche contre l'ensemble des tables matchees du SQL, donc le client ne
  choisit jamais une table arbitraire (`validation.py:355-362`).

La validation de route ne verifie que FORME et BORNES ; l'EXISTENCE des colonnes est revalidee par le service
contre le schema LIVE (`400 invalid_filter_column` / `invalid_sort_column`). Les chips verrouillees ne voyagent
que comme ids ; leur SQL est re-derive serveur depuis le `generated_sql` stocke.

---

## 8. Donnees envoyees au LLM, retention, injection de prompt

### Ce qui est envoye a l'agent (aucune ligne brute)

`flatten_exchanges_to_messages` (`context.py:136-155`) construit le payload multi-tours : pour chaque echange
anterieur, le `user_text` et le `assistant_text` VERBATIM, plus, quand present, un bloc SQL BORNE issu du
`generated_sql` stocke (`_format_sql_context`, `context.py:116-133`, cap `MAX_SQL_CONTEXT_CHARS = 4000`,
`context.py:113`). Le contexte rejoue contient donc le TEXTE des reponses + le SQL genere comme grounding, mais
PAS les lignes de donnees brutes des resultats (`context.py:111-112` : "the SQL is for grounding, not verbatim
re-execution"). Les lignes capturees (Evidence) sont persistence-only, surfacees via `/evidence/meta`, jamais
poussees dans le contexte agent ni sur la timeline polled (`stream_manager.py:372-374`).

Le bloc "ON SCREEN NOW" (`build_screen_state`, `context.py:210-237`) decrit ce qui est a l'ecran (specs
d'artefacts + NOMS de colonnes + extrait de la reponse precedente, borne a
`SCREEN_ANSWER_EXCERPT_CHARS = 300`), mais reste une description bornee, pas un dump de lignes. Il est encadre
comme DONNEE DEJA GROUNDED pour ne pas tromper le pare-feu d'honnetete de l'orchestrateur (toute NOUVELLE
figure exige encore un appel au specialiste, `context.py:234-237`).

Le bloc de contexte par-tour (`build_user_suffix`, `context.py:76-108`) ajoute, en FIN de message courant
(slot de plus haute recence), le nom de l'utilisateur, la date serveur, la langue de l'app et la regle
"answer in THIS message's language". Les tokens de controle `owi:mode=...` / `owi:lang=...` sont MACHINE-ONLY :
l'orchestrateur les parse PUIS les STRIPE, ils n'atteignent jamais le modele comme texte visible
(`context.py:82-86`). Le `mode` (eco/medium/high) est relaye via ce token ; le front ne choisit jamais un id de
modele brut (`routes.py:274-279`, `context.py:25-29`).

### Retention

- Messages utilisateur / reponses agent : persistes dans `webapp_chat_v5` (phase un = message user dans
  `/chat/start`, `routes.py:265-269` ; phase deux = reponse + `generated_sql` + usage par le worker,
  `stream_manager.py:418-421`). Cap du texte PERSISTE : `MAX_PERSISTED_TEXT_CHARS = 262_144`
  (`docs/security.md:268-273`).
- Traces brutes d'agent : append WRITE-ONLY sur un dataset Flow admin-selectionne (`traces_dataset`), jamais
  relu en ligne (`sql_config.py:163-175`, `chat_traces.save_trace`, `stream_manager.py:442-447`). Best-effort :
  un echec de stockage de trace ne casse jamais la reponse.
- Usage tokens/cout : par echange dans `webapp_chat_v5` + agregats `webapp_usage_monthly_v1` (best-effort,
  `stream_manager.py:432-437`).

### Injection de prompt : considerations

- Le contenu du message est l'input non fiable par excellence. La mitigation principale n'est PAS de filtrer le
  texte (impossible de facon fiable) mais de CONTRAINDRE ce que l'agent peut faire en aval : seuls des tools
  DSS gouvernes et un moteur SQL read-only/bornes (cote agents) executent du SQL, et la seule re-execution cote
  WebApp (Evidence) est verrouillee par la chaine de la section 7 (read-only, timeout, bornes, fragment
  re-valide). Une instruction injectee ne peut donc pas faire ecrire la base ni lire hors des datasets du projet.
- Les tokens de controle (`owi:mode`, `owi:lang`) sont parses+strippes par l'orchestrateur ; un utilisateur qui
  taperait litteralement ces sequences ne change pas le mode reel cote backend, qui valide `mode` contre
  `MODEL_MODES` (`routes.py:277-279`) et `webapp_lang` contre `_LANG_LABEL` (`routes.py:285-287`).
- Le pare-feu d'honnetete de l'orchestrateur (cote `dataiku-agents/`) impose de ne jamais emettre un FAIT
  metier non source ; le bloc screen-state est cadre pour ne pas le contourner (`context.py:216-219`).
  INCERTAIN : la robustesse de ce pare-feu vit dans les prompts des Code Agents (`dataiku-agents/`), hors du
  perimetre de ce pack et en cours d'edition par un autre ingenieur ; a documenter separement.

---

## 9. Admin : bootstrap, gating, anti-lockout

### Bootstrap "premier a ouvrir = admin", declenche par POST uniquement

`/me` accepte `GET` et `POST` (`routes.py:119`), mais l'effet de bord (enregistrer l'utilisateur + election du
premier admin) n'a lieu QUE sur POST (`routes.py:148-153`). Un `GET`/prefetch/scanner ne peut ni creer une
ligne utilisateur ni gagner l'election (`routes.py:122-128`). `record_user` (`admin.py:38-85`) fait un upsert
idempotent + un `UPDATE ... SET is_admin = true ... WHERE NOT EXISTS (SELECT 1 ... WHERE is_admin = true)`
(`admin.py:75-79`). L'election est SERIALISEE par un verrou consultatif transactionnel
`pg_advisory_xact_lock` (`admin.py:73`, cle `_BOOTSTRAP_LOCK_KEY = 0x4F57494D`, `admin.py:35`) : deux premiers
utilisateurs concurrents ne peuvent pas devenir admin tous les deux (race fermee).

Gotcha operationnel (TOFU = Trust On First Use) : le premier utilisateur a ouvrir l'app APRES configuration
devient admin -> s'assurer en deploiement que c'est bien l'admin deployeur (`docs/security.md:230-231`).

### Routes admin gardees serveur

`_admin_guard()` (`routes.py:713-731`) : resout l'identite (401 sinon), exige le stockage configure (409
sinon), exige `admin.is_admin(user_id)` (403 `forbidden` sinon). Applique a `/admin/storage`, `/admin/users`,
`/admin/users/set-admin`, `/admin/projects`, `/admin/projects/<key>/agents`, `/admin/agents`
(`routes.py:734-826`). `is_admin` (`admin.py:88-96`) lit le flag persistant. La garde cote router front (UI)
n'est que cosmetique : l'enforcement reel est serveur.

### Anti-lockout

`set-admin` ne retire jamais le DERNIER admin restant : `if not value and admin.is_admin(target) and
admin.count_admins() <= 1 -> 400 cannot_remove_last_admin` (`routes.py:770-772`, `admin.count_admins`
`admin.py:99-105`).

---

## 10. Hygiene, logs, codes d'erreur

- Jamais logue : le CONTENU des messages utilisateur / reponses agent (seulement longueur et metadonnees).
  `/chat/start` logue `user_id`, `session_id`, `agent_key`, `msg_len`, JAMAIS le message
  (`routes.py:242-251`). Les valeurs d'en-tete porteuses de credentials ne sont jamais loguees
  (`identity.py:96-97`). En cas d'echec agent, aucun interne agent/SQL/connexion n'est divulgue au client
  (`stream_manager.py:504-515` -> `error: agent_unavailable`).
- `/ping` (`routes.py:110-116`) est volontairement MINIMAL : il N'EXPOSE PAS la config de stockage (connexion,
  project key, noms de tables) car il est atteignable sans authentification. `storage_status()` n'est
  accessible qu'aux admins via `/admin/storage`.
- Codes d'erreur stables, sans detail interne : `ValidationError(code)` renvoie un code machine stable et sur
  (jamais d'interne) au front (`validation.py:22-28`). Le rating de feedback REJETTE explicitement les bools
  (`True`/`False` sont sous-classes d'`int`) : seuls `0`, `1` ou `None` sont acceptes
  (`validation.py:178-180`) ; les raisons sont restreintes a une whitelist `ALLOWED_FEEDBACK_REASONS`
  (`validation.py:157`) puis cappees (`MAX_FEEDBACK_REASONS = 8`, comment <= 2000 chars,
  `validation.py:158-159`, `validation.py:184-188`).
- API DSS en lecture seule (+ run agent) : seules des methodes de LECTURE sont appelees
  (`get_auth_info_from_browser_headers`, `get_webapp_config`, `default_project_key`, `list_connections`,
  `list_datasets`/`read_schema`, listing projets/agents) + l'execution d'agent ; jamais
  `set_*`/`save`/`delete`/`set_variables`/`set_definition` (`docs/security.md:280-284`). La discovery est
  STRICTEMENT read-only et bornee (`discovery.py:8-12`).

---

## 11. Surete de l'instance Dataiku (regle NON NEGOCIABLE #2)

Le worker de fond est borne (`agents/stream_manager.py`) ; pourquoi du polling et pas du SSE : le nginx interne
DSS peut bufferiser un `text/event-stream` long, donc l'agent tourne dans un thread daemon, accumule dans un
dict module-level, et le front POLL des requetes courtes (`stream_manager.py:1-29`). Garde-fous :

| Garde-fou | Valeur | Code |
|---|---|---|
| Cap de concurrence global | `MAX_CONCURRENT_RUNS = 8` (verifie sous `_LOCK` dans `start_run`) | `stream_manager.py:46`, `stream_manager.py:193-197` |
| Pre-check d'admission (avant tout write) | `can_accept(user_id)` : cap global + rate-gate par user | `stream_manager.py:102-124`, `routes.py:256-261` |
| Rate-gate par utilisateur | `MIN_START_INTERVAL_SECONDS = 1.0` (timestamp reserve SOUS le meme lock, pas de TOCTOU) | `stream_manager.py:87`, `stream_manager.py:117-123` |
| Eviction TTL (run fini) | `FINISHED_TTL_SECONDS = 60.0` | `stream_manager.py:51` |
| Eviction TTL (lifetime absolu) | `HARD_TTL_SECONDS = 600.0` | `stream_manager.py:56` |
| Deadline wall-clock cooperative | `MAX_RUN_SECONDS = 300.0` (entre chunks) | `stream_manager.py:81`, `stream_manager.py:142` |
| Arret cooperatif si tab abandonne | `ABANDON_AFTER_SECONDS = 30.0` (via `last_poll_at`) | `stream_manager.py:82`, `stream_manager.py:144` |
| Bornes memoire par run | `MAX_LIVE_EVENTS = 5000`, `MAX_ANSWER_CHARS = 1_000_000`, `MAX_ARTIFACTS_ACCUM = 8` | `stream_manager.py:65-69` |

Limite connue (documentee, pas un bug) : deadline et abandon sont evalues ENTRE chunks ; un appel upstream
totalement fige qui ne yield jamais reste borne uniquement par le TTL memoire. Un watchdog dedie n'est PAS
ajoute (risque plus eleve sur un chemin valide) (`stream_manager.py:78-80`).

---

## 12. Connexions avec le reste du systeme

- Frontend (Vue 3) : n'envoie que des donnees logiques ; reference un agent par cle opaque ; recoit `run_id`
  opaque et poll `/chat/poll`. `noJSSecurity: "false"` dans `webapp.json` (`webapp.json:14`). Le frontend
  buildE est servi par DSS sous `/plugins/owismind/resource/owismind-app/` ; il n'est jamais dans le zip de
  packaging (regle #5).
- Couche agents (`dataiku-agents/`, Code Agents LangGraph, env 3.11) : recoit `agent_messages` (history + tour
  courant + suffixe de contexte) ; emet des events normalises (`run_started`, `agent_event`, `answer_delta`,
  `generated_sql`, `usage_summary`, `artifact`, `final_answer`, `run_done`, `error`, `stopped`). Le pare-feu
  d'honnetete et le grounding SQL vivent cote agents (hors perimetre de ce pack, EN COURS d'edition).
- Stockage (`storage/`) : SQL direct, tables `webapp_chat_v5` / `webapp_users_v1` / `webapp_settings_v1` /
  `webapp_usage_monthly_v1`, plus le dataset Flow `traces_dataset` (write-only). Toutes les ecritures
  parametrees + COMMIT explicite.
- Evidence (`evidence/`) : re-execute le scope SELECT de l'agent en read-only sur les datasets DECOUVERTS du
  projet ; voir section 7.

---

## 13. Recapitulatif des gotchas et points incertains / en evolution

- DIVERGENCE doc-vs-code : `docs/security.md:184` decrit un param admin `evidence_datasets` (whitelist de
  datasets). Le code actuel DECOUVRE les datasets automatiquement (pas de whitelist admin), et `webapp.json`
  ne declare pas ce param. Le code prime (`whitelist.py:1-9`, `service.py:86-89`). A reconcilier dans la doc.
- Run-as-user du backend : `webapp.json` ne declare aucun champ run-as explicite ; l'identite d'execution est
  le comportement DSS par defaut. A VERIFIER / verrouiller en deploiement (`docs/security.md:312-315`).
- Hypothese MONO-PROCESS : tout l'etat in-memory (`_RUNS`, `_LAST_START_BY_USER`, cache d'identite, buckets de
  rate-limit, caches Evidence) est per-process. A forcer a 1 process (`docs/security.md:261-263`).
- TOFU admin : le premier a ouvrir l'app apres config devient admin (`docs/security.md:230-231`).
- Logs SQL DSS : `SQLExecutor2` n'a aucun bind serveur, donc `sql_value` inline la valeur dans le statement
  loggue par DSS ; d'ou le cap `MAX_PERSISTED_TEXT_CHARS = 262_144` sur le texte persiste
  (`docs/security.md:268-273`).
- Tests : plusieurs invariants deja durcis ne sont pas encore couverts par des tests unitaires (TEST-01,
  `docs/security.md:303-310`). Recommandation, non implemente.
- Le pare-feu d'honnetete et la robustesse anti-injection cote agents vivent dans `dataiku-agents/` (prompts
  des Code Agents), hors perimetre de ce pack et en cours d'edition.
