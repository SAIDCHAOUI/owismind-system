# Knowledge Pack : Backend Flask API (blueprint, endpoints, identité, validation)

> Zone assignee : la couche HTTP du plugin OWIsMind. Source de verite = le code lu, pas la doc.
> Tous les chemins sont absolus. Les identifiants, noms de table, codes d'erreur et ids de config
> restent VERBATIM en anglais. Texte explicatif en francais.

Fichiers etudies :
- `/Users/saidchaoui/projects/owismind/Plugin/owismind/python-lib/owismind/api/routes.py` (toutes les routes, le blueprint, les gardes)
- `/Users/saidchaoui/projects/owismind/Plugin/owismind/webapps/webapp-owismind-ai-agents/backend.py` (bootstrap)
- `/Users/saidchaoui/projects/owismind/Plugin/owismind/webapps/webapp-owismind-ai-agents/webapp.json` (descripteur + parametres)
- `/Users/saidchaoui/projects/owismind/Plugin/owismind/webapps/webapp-owismind-ai-agents/app.js` (stub vide)
- `/Users/saidchaoui/projects/owismind/Plugin/owismind/python-lib/owismind/security/identity.py` (resolve_identity)
- `/Users/saidchaoui/projects/owismind/Plugin/owismind/python-lib/owismind/security/validation.py` (validateurs purs)
- `/Users/saidchaoui/projects/owismind/Plugin/owismind/python-lib/owismind/storage/admin.py` (registre users, 1er admin)
- `/Users/saidchaoui/projects/owismind/Plugin/owismind/python-lib/owismind/storage/sql_config.py` (is_configured, storage_status)
- `/Users/saidchaoui/projects/owismind/Plugin/owismind/python-lib/owismind/agents/stream_manager.py` (admission, runs)
- `/Users/saidchaoui/projects/owismind/Plugin/owismind/python-lib/owismind/agents/context.py` (MODEL_MODES, suffixe)
- `/Users/saidchaoui/projects/owismind/Plugin/owismind/python-lib/owismind/storage/chat_v5.py` (writes/reads chat)
- `/Users/saidchaoui/projects/owismind/Plugin/owismind/python-lib/owismind/evidence/throttle.py` (token-bucket)
- `/Users/saidchaoui/projects/owismind/docs/backend-api.md` (doc de reference, partiellement perimee)

---

## 1. Bootstrap et blueprint

Le webapp DSS expose un `app` Flask via un star-import. `backend.py` (`backend.py:6-10`) est un bootstrap
mince :

```python
from dataiku.customwebapp import *          # fournit l'objet Flask `app`
from owismind.api.routes import register_routes
register_routes(app)
```

`app.js` (`app.js:1-2`) est volontairement vide : tout le frontend vient de `body.html` (Vue/Vite). Aucune
logique cote app.js.

Le blueprint est defini dans `routes.py:69` :

```python
api = Blueprint("owismind_api", __name__, url_prefix="/owismind-api")
```

`register_routes(app)` (`routes.py:915-933`) : (1) `app.register_blueprint(api)` ; (2)
`sql_config.apply_log_level()` applique le niveau de log configure ; (3) log du `storage_status()` resolu ;
(4) log de la **table de routes vivante** (toutes les regles commencant par `/owismind-api`, triees). Ce
dernier log est un repere operationnel : il confirme, dans le log backend DSS, quel build tourne et combien
de routes sont montees.

### Hooks blueprint-scopes

Deux hooks `before_request` / `after_request` tracent chaque requete (`routes.py:85-107`) :
- `_log_request_start` pose `g._owi_t0 = time.time()` et logue `→ <method> <path>`.
- `_log_request_end` logue `← <method> <path> -> <status> (<ms> ms)`.

Point cle : etant **blueprint-scoped** (decorateurs `@api.before_request`), ils ne se declenchent QUE pour
`/owismind-api/*`, pas pour les health-pings internes de DSS. Le contenu des messages n'est JAMAIS logue
(hygiene/vie privee) ; seules les meta (methode, chemin, statut, duree) le sont.

---

## 2. Conventions transverses

- **Python 3.9 / Flask** (pas de FastAPI). `/ping` renvoie la version Python reelle via `sys.version.split()[0]`.
- **Forme de reponse** : succes = `{"status": "ok", ...}` (souvent un splat `**result` ou `**meta` /
  `**page`). Erreur = `{"status": "error", "error": <code>}` avec un statut HTTP. Les codes d'erreur sont
  des chaines stables, machine-readable, jamais un detail interne.
- **Auth obligatoire sauf `/ping`** : chaque route appelle `resolve_identity(request.headers)` ; un echec
  leve `IdentityError`, transforme en `401 {"error": "unauthenticated"}`.
- **Garde storage** : sauf `/ping` et `/me`, toute route refuse si `sql_config.is_configured()` est faux
  -> `409 {"error": "storage_not_configured"}`. `/me` tolere l'absence de config (il renvoie
  `needs_config: true`).
- **Identite jamais depuis le corps** : le `user_id` vient toujours des en-tetes navigateur authentifies.
  Le front n'envoie que de la donnee logique (`session_id`, `message`, `agent_key`, etc.).
- **Whitelist agents serveur** : le front envoie une cle logique opaque `agent_key` (forme `ag_<12 hex>`),
  resolue serveur en `(project_key, agent_id)`. Un `agent_id` brut n'est jamais accepte.
- **Owner-scoping systematique** : toutes les lectures/ecritures chat et Evidence sont scopees par
  `user_id`. Un id forge ne peut au pire reveler que les propres donnees du caller.

---

## 3. Resolution d'identite (`security/identity.py`)

`resolve_identity(headers)` (`identity.py:101-159`) renvoie `{user_id, display_name, groups}` :
- L'appel reel est `dataiku.api_client().get_auth_info_from_browser_headers(dict(headers))`
  (`identity.py:91-98`) : un `api_client` frais par appel (objet leger, thread-safe sous workers Flask
  concurrents). Les en-tetes peuvent porter des credentials et ne sont JAMAIS logues.
- `user_id = info.get("authIdentifier")` (le login DSS). Absent -> `IdentityError("no_auth_identifier")`
  (les KEY NAMES, pas les valeurs, sont logues pour diagnostic). Echec de l'appel DSS ->
  `IdentityError("auth_lookup_failed")`.
- `groups = info.get("groups") or []`, normalise en liste si scalaire.
- **DSS ne fournit pas de display name** (lecon L011, citee `identity.py:50-60`) : il est DERIVE du login.

### Derivation des noms (convention `prenom.nom`)
- `derive_display_name(login)` (`identity.py:45-68`) : prend le segment avant le premier `.`, title-case
  par groupe de tiret. `said.chaoui` -> `Said` ; `jean-marc.dupont` -> `Jean-Marc` ; `admin` -> `Admin`.
  C'est le `display_name` renvoye par `/me`.
- `derive_full_name(login)` (`identity.py:71-88`) : title-case tous les segments dot/hyphen.
  `said.chaoui` -> `Said Chaoui`. Utilise par `/chat/start` pour construire le suffixe d'agent
  (`routes.py:294`, `derive_full_name(identity["user_id"])`).
- Ces noms sont des DEFAUTS uniquement ; une feature "set my display name" est prevue mais n'existe pas
  encore. `admin.record_user` fait un `COALESCE` a l'upsert pour preserver un nom custom futur.

### Cache TTL court (perf de /chat/poll)
`identity.py:28-31, 111-159` : cache par-process keye sur un SHA-256 du Cookie d'auth (`_identity_cache_key`,
`identity.py:34-42`), TTL `_AUTH_TTL_SECONDS = 5.0`, cap `_AUTH_CACHE_MAX = 512`. Rationale : `/chat/poll`
re-resout le caller a chaque poll (~2 Hz par chat live), et chaque resolution est un round-trip DSS
synchrone qui retient un thread worker. Le cache collapse les polls successifs sur une seule resolution.
Seules les resolutions reussies sont mises en cache ; eviction opportuniste sous lock
(`_auth_cache_lock`). Hypothese mono-process (comme tout le backend).

---

## 4. Catalogue complet des endpoints

Tous montes sous `/owismind-api`. Forme succes `{status:"ok", ...}`, erreur `{status:"error", error:<code>}`.

### 4.1 Sante et identite

**`GET /ping`** (`routes.py:110-116`) : auth NON requise. Renvoie `{status:"ok", python:"<3.9.x>"}`.
Volontairement minimal : n'expose JAMAIS la config de stockage (connexion, project key, noms de table),
car `/ping` est atteignable sans auth. La config resolue n'est lisible que par un admin via
`/admin/storage`.

**`GET|POST /me`** (`routes.py:119-166`) : auth requise. Renvoie
`{status:"ok", user_id, display_name, groups, needs_config, is_admin}`.
- `needs_config = not sql_config.is_configured()`.
- **Effet de bord GET vs POST (design crucial)** : `admin.record_user(identity)` (upsert + election du 1er
  admin) n'est appele QUE sur POST (`routes.py:148-151`). GET reste read-only. Rationale explicite : un
  prefetch/scanner GET ne doit ni creer une ligne user ni gagner l'election "premier a ouvrir = admin". Le
  front emet POST une fois a l'init. Les deux methodes renvoient la meme forme.
- `is_admin` n'est resolu que si `configured` (sinon `False`). Une exception du registre est avalee
  (`except Exception: logger.exception`) -> renvoie `is_admin: false` plutot que 500.
- Erreur : `unauthenticated -> 401`. Pas de `storage_not_configured` ici (tolere l'instance vierge).

### 4.2 Agents (picker cote chat)

**`GET /agents`** (`routes.py:515-550`) : auth + storage requis. Renvoie
`{status:"ok", count, agents:[{key, label}]}`. Projette UNIQUEMENT `key` (= `logical_key` opaque) et
`label` ; jamais `agent_id` ni `project_key` (whitelist). Erreurs : `unauthenticated -> 401`,
`storage_not_configured -> 409`, `storage_unavailable -> 500`.

### 4.3 Chat

**`POST /chat/start`** (`routes.py:190-318`) : demarre un run agent en worker de fond. Corps JSON :

| Champ | Type | Oblig. | Bornes / defaut |
|---|---|---|---|
| `session_id` | str | oui | non vide (strip), <= 128 (`MAX_SESSION_ID_LENGTH`) |
| `message` | str | oui | non vide (strip), <= 8000 (`MAX_MESSAGE_LENGTH`) |
| `agent_key` | str | oui | opaque, <= 64 (`MAX_AGENT_KEY_LENGTH`), resolu contre la whitelist |
| `history_limit` | int | non | clampe `[10, 50]`, defaut 20 (nb de MESSAGES rejoues) ; ne leve jamais |
| `parent_exchange_id` | str | non | arete d'arbre ; valeur invalide -> `None` ; ne leve jamais |
| `mode` | str | non | `eco`/`medium`/`high` (`context.MODEL_MODES`) ; inconnu/absent -> `medium` |
| `webapp_lang` | str | non | `fr`/`en` (`context._LANG_LABEL`) ; inconnu/absent -> `None` |
| `screen_context` | dict | non | sanitise (voir 5.4) ; sinon `None` |

Sequence exacte (`routes.py:203-318`) :
1. `resolve_identity` -> 401 si echec.
2. `validate_chat_start_request(request.get_json(silent=True))` -> 400 `<code>` si invalide.
3. `validate_history_limit` + `validate_optional_exchange_id` lus separement du corps (le validateur
   principal reste inchange).
4. Garde storage : `409 storage_not_configured` si non configure.
5. **Whitelist** : `settings.resolve_enabled_agent(agent_key)`. `None` (cle forgee/perimee) ->
   `404 agent_not_enabled`. En cas de succes : `project_key`, `agent_id`.
6. Log content-free : `user_id`, `session_id`, `agent_key`, `msg_len` (jamais le contenu du message).
7. **Gate d'admission AVANT toute ecriture** : `stream_manager.can_accept(user_id)` renvoie `(ok, reason)`.
   `reason == "rate_limited"` -> `429`, sinon (`"busy"`) -> `503` (`routes.py:256-261`).
8. **Phase un (ecriture)** : `ensure_chat_table()` puis
   `chat_v5.save_user_message(session_id, identity, message, agent_key, parent_exchange_id)` ->
   renvoie un `exchange_id` (genere en Python, pas de readback). Echec -> `500 storage_unavailable`.
9. Resolution `mode` (defaut `medium`), `webapp_lang`, et detection de langue de reponse de CE tour :
   `prompt_lang = context.detect_prompt_language(message, default=webapp_lang or "fr")` sur le message
   BRUT (avant tout stamp de date qui polluerait l'heuristique).
10. Construction du suffixe par-tour : `context.build_user_suffix(derive_full_name(user_id), datetime.now(),
    webapp_lang=..., prompt_lang=..., mode=...)` (`routes.py:293-296`). Bloc appende a la FIN du message
    courant (l'agent est stateless entre appels et honore mieux la fin de prompt).
11. `screen_context = _sanitize_screen_context(body.get("screen_context"))`.
12. `stream_manager.start_run(project_key, agent_id, message, exchange_id, user_id, parent_exchange_id,
    history_limit, user_suffix, screen_context=...)`. `CapacityError` -> `503 busy` ; autre exception ->
    `500 agent_unavailable`.
13. Succes : `{status:"ok", run_id, exchange_id}`. Le `run_id` est l'unique handle opaque cote front ;
    `agent_id` reste serveur.

Codes d'erreur `/chat/start` : `unauthenticated`(401), `<validation>`(400), `storage_not_configured`(409),
`agent_not_enabled`(404), `rate_limited`(429), `busy`(503), `storage_unavailable`(500),
`agent_unavailable`(500).

**`GET /chat/poll`** (`routes.py:321-353`) : query `run_id` (requis, <= `_MAX_RUN_ID_LENGTH = 64` sinon
`400 invalid_run_id`) et `cursor` (int, defaut 0 ; non-int ou < 0 -> 0). Appelle
`stream_manager.poll(run_id, identity["user_id"], cursor)`. **Owner-scope** : `None` (run inconnu OU
appartenant a un autre user) -> `404 run_not_found` (sans reveler lequel). Succes :
`{status:"ok", events:[...], cursor, done, error}`. `events` = events normalises depuis le curseur,
`cursor` = prochain curseur a renvoyer, `done` = run termine, `error` = code terminal ou `null`.

**`POST /chat/stop`** (`routes.py:356-383`) : corps `{run_id}`. `run_id` non-str/vide/> 64 ->
`400 invalid_run_id`. `stream_manager.request_stop(run_id, user_id)` faux -> `404 run_not_found` (run
inconnu, deja fini/evince, ou d'un autre user : no-op sur que le client traite comme "deja fait"). Succes
`{status:"ok"}`. L'identite vient des headers, jamais du corps.

**`POST /chat/feedback`** (`routes.py:386-429`) : auth + storage requis. Corps valide par
`validate_feedback` (voir 5.3). `chat_v5.save_feedback(user_id, exchange_id, rating, reasons, comment)` est
**owner-scope** (`WHERE exchange_id AND user_id`) : noter l'echange d'autrui est un no-op silencieux.
Erreurs : `unauthenticated`(401), `storage_not_configured`(409), `<validation>`(400),
`storage_unavailable`(500). Succes `{status:"ok"}`.

### 4.4 Conversations (sidebar)

**`GET /conversations`** (`routes.py:432-471`) : query `limit` (clampe `[1, 60]`, defaut 30 via
`validate_conversations_limit`) et `cursor` (token opaque base64 ; borne defensivement a <= 512 chars sinon
`400 invalid_cursor`, `routes.py:454-456`). `chat_v5.list_conversations(user_id, cursor_token, limit)`.
Succes : `{status:"ok", conversations:[...], ...}` (splat du dict `page` : inclut typiquement
`conversations`, `has_more`, et le prochain curseur). Noms seuls, jamais de corps de message,
owner-scope. Erreurs : `unauthenticated`(401), `storage_not_configured`(409), `invalid_cursor`(400),
`storage_unavailable`(500).

**`GET /conversation`** (`routes.py:474-512`) : query `session_id` (strip, non vide, <=
`MAX_SESSION_ID_LENGTH = 128` sinon `400 invalid_session_id`). `chat_v5.messages_for_session(user_id,
session_id)` -> tous les messages d'UNE session, chronologique, borne (`SESSION_MESSAGES_CAP = 500`,
`chat_v5.py:368`), strictement scope `(user_id, session_id)`. Succes :
`{status:"ok", session_id, count, rows:[...]}`. `rows` suit l'ordre de colonnes stable `chat_v5._COLUMNS`
(`chat_v5.py:83-88` : `exchange_id, session_id, user_id, user_display_name, user_groups, user_text,
assistant_text, generated_sql, agent_key, created_at, answered_at, feedback_rating, feedback_reasons,
feedback_comment, parent_exchange_id, input_tokens, output_tokens, total_tokens, estimated_cost`) ->
le front reutilise un seul mapper ligne->message.

### 4.5 Evidence Studio (owner-scope, read-only, datasets auto-decouverts)

Garde partagee `_evidence_guard()` (`routes.py:556-584`), chaine : (1) `resolve_identity` ->
`401 unauthenticated` ; (2) `sql_config.is_configured()` -> `409 storage_not_configured` ;
(3) `ensure_chat_table()` -> `500 storage_unavailable` (bootstrap : sur une instance configuree mais
vierge, un exchange_id forge rend le meme 404 owner-scope qu'ailleurs, pas un 500 distinguable) ;
(4) **gate de debit par user** `evidence_throttle.can_accept(user_id)` -> `429 rate_limited`. Le
token-bucket (`evidence/throttle.py:13-14`) a `EVIDENCE_BUCKET_CAPACITY = 15` jetons,
`EVIDENCE_REFILL_PER_SEC = 10.0` : il absorbe le burst legitime (paire meta+rows de l'auto-ouverture) mais
refuse une rafale scriptee qui pinnerait les threads du backend mono-process. Verifie APRES le chemin
auth/config/bootstrap (peu couteux).

- **`GET /evidence/meta`** (`routes.py:587-640`) : query `exchange_id` (via
  `validate_required_exchange_id`). `evidence_service.evidence_meta(user_id, exchange_id)`. Une
  `EvidenceError(code, status)` -> renvoie ce code/statut ; autre exception -> `500 evidence_unavailable`.
  La route enrichit aussi les artefacts (chart/table/kpi) via `artifacts_storage.read_artifacts` +
  `chart_payload.build_chart_payload` / `build_kpi_payload`, en best-effort (un echec degrade a
  `artifacts: []`, jamais un 500). Une ligne d'observabilite par meta logue
  `available`/`reason`/`level`/`result_captured`/`drill_available`/`artifacts`.
- **`POST /evidence/rows`** (`routes.py:643-671`) : corps valide par `validate_evidence_rows_request` (voir
  5.5). `evidence_service.evidence_rows(user_id, exchange_id, filters, kept_ids, include_advanced, page,
  sort, drill, table)`. Le corps ne porte JAMAIS de SQL ; les chips editables voyagent comme
  `{column, op, values}`, les chips verrouillees comme `kept_ids`.
- **`GET /evidence/distinct`** (`routes.py:674-707`) : query `exchange_id` + `column` (forme seule, via
  `validate_evidence_column`) + `exclude_id` optionnel (int ; malformede ou < 0 -> `None`). Alimente le
  picker de valeurs des chips.

### 4.6 Admin (`_admin_guard()`, gardes serveur)

`_admin_guard()` (`routes.py:713-731`) : (1) `resolve_identity` -> `401` ; (2) `is_configured` -> `409` ;
(3) `admin.is_admin(user_id)` faux -> `403 forbidden` (echec du check -> `500 storage_unavailable`).

- **`GET /admin/storage`** (`routes.py:734-740`) : `{status:"ok", storage: sql_config.storage_status()}`.
  `storage_status()` (`sql_config.py:280-303`) expose `configured`, `connection`, `project_key`(+ source),
  `table_prefix`(+ `_input`/`_ignored`), `namespace`, `traces_dataset`, et les noms physiques calcules
  (`chat`=`webapp_chat_v5`, `users`=`webapp_users_v1`, `settings`=`webapp_settings_v1`,
  `usage_monthly`=`webapp_usage_monthly_v1`).
- **`GET /admin/users`** (`routes.py:743-754`) : `{status:"ok", count, users:[...]}` via `admin.list_users`.
- **`POST /admin/users/set-admin`** (`routes.py:757-778`) : corps `{user_id, is_admin}`. `user_id` vide ->
  `400 missing_user_id`. Garde anti-lockout : si on retire un flag (`value` faux) d'un admin et
  `admin.count_admins() <= 1` -> `400 cannot_remove_last_admin` (`routes.py:771`). Sinon
  `admin.set_admin(target, value)` puis renvoie la liste a jour.
- **`GET /admin/projects`** (`routes.py:784-795`) : `discovery.list_project_keys()`. Echec ->
  `500 discovery_unavailable`.
- **`GET /admin/projects/<project_key>/agents`** (`routes.py:798-822`) : `project_key` revalide contre la
  liste des projets visibles (`if project_key not in set(discovery.list_project_keys())` ->
  `404 project_not_found`) AVANT le listing -> un admin ne peut pas sonder une cle arbitraire/cachee.
  Renvoie `{status:"ok", project_key, count, agents:[{agent_id, description}]}`.
- **`GET|POST /admin/agents`** (`routes.py:825-912`) : GET renvoie la selection stockee (vue admin, inclut
  `project_key`/`agent_id`). POST persiste `{agents:[{project_key, agent_id}]}` : liste non-liste ->
  `400 invalid_payload` ; > `MAX_ENABLED_AGENTS = 50` -> `400 too_many_agents`. Chaque agent demande est
  **RE-VALIDE serveur** contre les listings DSS vivants (projet visible ET agent reellement present) ; un
  agent non present est skippe (loggue). La `logical_key` est derivee d'un hash STABLE de
  `project_key:agent_id` via `_logical_key` (`routes.py:72-82`, `"ag_" + sha1(...)[:12]`) : stable pour que
  re-sauver garde la meme cle, opaque pour que le front ne recoive jamais d'`agent_id` brut. Persistance
  via `settings.set_enabled_agents(enabled, updated_by=user_id)`.

---

## 5. Validation des payloads (`security/validation.py`, pur, sans DSS)

`ValidationError(code, message=None)` (`validation.py:22-28`) porte un `code` stable rendu tel quel au
front. Les bornes :
- `MAX_MESSAGE_LENGTH = 8000`, `MAX_SESSION_ID_LENGTH = 128`, `MAX_AGENT_KEY_LENGTH = 64`.

### 5.1 validate_chat_start_request (`validation.py:84-107`)
Construit sur `validate_chat_request` (`validation.py:56-81`) qui valide `{session_id, message}` :
- `session_id` : doit etre str (sinon `missing_session_id`), non vide apres strip (`empty_session_id`),
  <= 128 (`session_id_too_long`).
- `message` (via `validate_message`, `validation.py:31-53`) : str (`missing_message`), <= 8000
  (`message_too_long`), non vide apres strip (`empty_message`) ; corps non-dict -> `invalid_payload`.
- `agent_key` : str (`missing_agent_key`), non vide (`empty_agent_key`), <= 64 (`agent_key_too_long`). La
  resolution contre la whitelist est faite SEPAREMENT cote serveur (pas ici).

### 5.2 Clamps qui ne levent jamais
- `validate_history_limit` (`validation.py:116-132`) : clamp `[10, 50]` (`MIN=10`, `MAX=50`), defaut 20.
- `validate_conversations_limit` (`validation.py:141-153`) : clamp `[1, 60]`, defaut 30.
- `validate_optional_exchange_id` (`validation.py:192-201`) : str non vide <= 128, sinon `None`.

### 5.3 validate_feedback (`validation.py:162-189`)
Renvoie `(exchange_id, rating, reasons, comment)`. `exchange_id` requis (<= 128) sinon
`invalid_exchange_id`. `rating` doit etre `0`, `1` ou `None` ; **bool rejete explicitement**
(`isinstance(rating, bool)` -> `invalid_rating`, car `True/False` sont sous-types de int). `reasons` filtre
sur `ALLOWED_FEEDBACK_REASONS = ("incorrect", "incomplete", "off_topic", "other")`, cap
`MAX_FEEDBACK_REASONS = 8`. `comment` tronque a `MAX_FEEDBACK_COMMENT_CHARS = 2000`. Corps non-dict ->
`invalid_payload`.

### 5.4 _sanitize_screen_context (`routes.py:169-187`, dans routes.py)
Vue bornee de ce que regarde l'utilisateur. `raw` non-dict ou sans `open` -> `None`. `exchange_id` doit
etre str/int (bool exclu : `not isinstance(exch, (str, int)) or isinstance(exch, bool)`) sinon `None`.
Renvoie `{open:True, exchange_id:str(exch)[:128], active_tab: tab si in _SCREEN_TABS sinon None}`.
`_SCREEN_TABS = ("evidence", "chart", "table")`. Le worker lit les artefacts de cet echange OWNER-SCOPE,
donc un id forge ne peut reveler que les donnees du caller.

### 5.5 validate_evidence_rows_request (`validation.py:268-364`)
Renvoie `(exchange_id, filters, kept_ids, include_advanced, page, sort, drill, table)` :
- `exchange_id` via `validate_required_exchange_id`.
- `filters` : liste <= `MAX_EVIDENCE_FILTERS = 20` ; chaque item `{column, op, values}` ; `op` dans
  `EVIDENCE_FILTER_OPS = ("=", "IN")` sinon `invalid_filter_op` ; `values` liste 1..`MAX_EVIDENCE_IN_VALUES
  = 50` (exactement 1 pour `"="`) ; chaque valeur via `_validate_evidence_value` (`validation.py:245-265`)
  qui accepte bool (legitime sur colonne booleenne), rejette NaN/Inf (`invalid_filter_value` : ils
  rendraient des tokens SQL non quotes), borne str/nombre a `MAX_EVIDENCE_VALUE_CHARS = 500`
  (`filter_value_too_long`).
- `kept_ids` : liste <= `MAX_EVIDENCE_KEPT_IDS = 100` ; entiers >= 0 ; bool rejete (`invalid_kept_ids`).
- `include_advanced` : coerce bool.
- `page` : CLAMPE `[0, MAX_EVIDENCE_PAGE = 20]` (ne leve jamais ; borne le cout du tri OFFSET).
- `sort` : `{column, dir}` ; malforme -> `None` (degradation gracieuse) ; `dir` normalise `asc`/`desc`.
- `drill` : liste <= `MAX_EVIDENCE_DRILL = 8` ; chaque `{column, value}` ; un drill malforme LEVE
  `invalid_drill` (un drill droppe en silence montrerait la page NON drillee = violation d'honnetete de
  scope, pas une degradation cosmetique). `value` peut etre `None` (-> IS NULL).
- `table` : selecteur de source optionnel <= `MAX_EVIDENCE_TABLE_CHARS = 256` ; malforme -> `None` ; le
  service le matche contre l'ensemble des tables matchees du SQL (jamais une table arbitraire).

Autres : `validate_required_exchange_id` (`validation.py:231-235`) leve `invalid_exchange_id` ;
`validate_evidence_column` (`validation.py:238-242`) leve `invalid_filter_column` (forme seule ;
l'EXISTENCE est revalidee contre le schema live par le service).

---

## 6. Admission, identite et "run as user"

### Gate d'admission (`stream_manager.can_accept`, `stream_manager.py:102-124`)
Renvoie `(ok, reason)`. Sous `_LOCK` : evince les runs stale, compte les runs actifs ; si
`active >= MAX_CONCURRENT_RUNS = 8` -> `(False, "busy")` (`503`) ; sinon si le dernier start du user date de
moins de `MIN_START_INTERVAL_SECONDS = 1.0` s -> `(False, "rate_limited")` (`429`). Le slot de spacing est
reserve SOUS LE MEME LOCK (`_LAST_START_BY_USER[user_id] = now`) pour fermer une fenetre de course (deux
`/chat/start` concurrents du meme user ne peuvent pas passer tous deux). C'est une PRE-CHECK avant ecriture
(evite un INSERT + round-trip auth inutile) ; le cap dur dans `start_run` (`stream_manager.py:194-196`,
leve `CapacityError`) reste le vrai garde (TOCTOU benin assume).

Autres bornes (citees `routes.py` doc + `stream_manager.py`) : `MAX_RUN_SECONDS = 300.0`,
`ABANDON_AFTER_SECONDS = 30.0`, `FINISHED_TTL_SECONDS = 60.0`, `HARD_TTL_SECONDS = 600.0`,
`MAX_LIVE_EVENTS = 5000`, `MAX_ANSWER_CHARS = 1_000_000`.

### Election du premier admin (`storage/admin.py`)
`record_user(identity)` (`admin.py:38-85`) fait, en UNE transaction : (1)
`pg_advisory_xact_lock(_BOOTSTRAP_LOCK_KEY = 0x4F57494D)` qui serialise l'election a travers les connexions
concurrentes (relache au COMMIT) ; (2) un UPSERT (`ON CONFLICT (user_id) DO UPDATE` avec `COALESCE` sur
`display_name` pour preserver un nom custom futur) ; (3) un UPDATE garde `SET is_admin = true ... WHERE
NOT EXISTS (SELECT 1 ... WHERE is_admin = true)` qui promeut SEULEMENT s'il n'y a encore aucun admin. Le
verrou consultatif rend le check race-free : sans lui, deux premiers users vraiment concurrents
pourraient chacun voir "aucun admin" (READ COMMITTED) et devenir tous deux admin. Tout cela part en
`pre_queries=[...]` + `post_queries=["COMMIT"]`.

### "Run as user" - implication
Tous ces appels DSS (`api_client().get_auth_info_from_browser_headers`, `SQLExecutor2`,
`get_agent_tool`, discovery) s'executent sous l'identite SOUS LAQUELLE TOURNE LE BACKEND DSS du webapp
(run-as), pas sous le browser caller. Le `user_id` resolu sert UNIQUEMENT au scoping applicatif (chat,
feedback, Evidence, admin). Donc : (a) la whitelist d'agents et la decouverte de projets refletent ce que
l'identite run-as du webapp peut voir, pas ce que le browser user pourrait voir directement ; (b) l'admin
applicatif (flag `is_admin` en table) est distinct des droits DSS - un user non-admin DSS peut etre admin
de l'app et inversement. La securite repose donc sur le scoping serveur (owner-scope SQL) et la whitelist,
pas sur des droits DSS par-user.

---

## 7. Parametres webapp (webapp.json) qui pilotent le backend

`webapp.json:28-64` definit 4 params (Settings DSS, alimentes par
`resource/compute_available_connections.py`) :
- `sql_connection` (SELECT, `getChoicesFromPython`) : connexion PostgreSQL. Tant qu'absent ->
  `is_configured()` faux -> la plupart des routes renvoient `409 storage_not_configured`. Defaut
  `SQL_owi` mentionne en memoire, mais resolu via `connection_name()` (`sql_config.py:114-121`) qui lit la
  config, jamais hardcode.
- `table_prefix` (STRING, optionnel) : prefixe insere apres le project key. Valide par `_PREFIX_RE =
  ^[A-Za-z0-9_-]{1,16}$` (`sql_config.py:52`) ; invalide/trop long -> IGNORE (loggue une fois,
  `storage_status.table_prefix_ignored`). Le project key et le namespace `owismind` restent toujours
  (`sql_config.py:264-276`).
- `traces_dataset` (SELECT, optionnel) : dataset Flow ou la trace brute de chaque run est appendee
  (write-only). Manquant/incompatible -> trace skippee, ne casse jamais le chat.
- `log_level` (SELECT, defaut INFO) : applique au boot par `apply_log_level()` (`sql_config.py:183-189`).

Note webapp.json : `"hasBackend": "true"`, `"noJSSecurity": "false"`, `baseType STANDARD`.

---

## 8. Liens avec le reste du systeme

- **Storage SQL** : routes -> `storage/chat_v5.py` (writes/reads chat, two-phase, owner-scope),
  `storage/admin.py` (registre/admin), `storage/settings.py` (whitelist agents persistee dans
  `webapp_settings_v1`), `storage/sql_config.py` (connexion, naming `{PROJECT_KEY}_{namespace}_{logical}`,
  helpers de surete). `ensure_chat_table()` (de `storage/migrations.py`) est appele avant chaque
  acces table (DDL idempotent).
- **Agents** : `agents/stream_manager.py` (cycle de vie run, admission, poll, stop),
  `agents/streaming.py` (normalisation des chunks LLM Mesh en events), `agents/context.py` (suffixe
  par-tour, MODEL_MODES, detection langue, assemblage multi-tours), `agents/discovery.py` (listing
  read-only projets/agents pour l'admin).
- **Evidence** : `evidence/service.py` (pipeline stateless owner-scope, re-exec SELECT borne read-only),
  `evidence/throttle.py` (token-bucket), `evidence/chart_payload.py` (shaping Chart.js/KPI),
  `storage/artifacts.py` (specs d'artefacts).
- **Frontend** : le front (Vue 3) ne consomme QUE des cles logiques + donnee structuree. Le contrat
  d'erreur (codes stables + statuts HTTP) est l'API que le front mappe en messages i18n.

---

## 9. Gotchas et points en flux

1. **`docs/backend-api.md` est partiellement PERIME** : il cite `chat_v4` / `ensure_chat_v4_table` /
   `chat_v4._COLUMNS` et des numeros de ligne anciens (ex. `routes.py:160` pour `/chat/start`, `routes.py:60`
   pour le blueprint). Le code reel utilise `chat_v5` (`from owismind.storage import ... chat_v5`,
   `routes.py:57`), `ensure_chat_table` (`routes.py:58`), et le blueprint est `routes.py:69`. La table
   physique est `webapp_chat_v5` (`sql_config.py:298`). Pour la doc utilisateur/dev, se fier au code.
2. **`/me` : POST seul mute** ; ne JAMAIS rendre l'effet de bord declenchable par GET (election 1er admin).
3. **`rate_limited`(429) vs `busy`(503)** : 429 = spacing par-user (1 s), 503 = cap global concurrent (8).
   La distinction est intentionnelle pour le retry cote client.
4. **NaN/Inf en filtre Evidence** : rejetes au portail (`invalid_filter_value`) car ils rendraient des
   tokens SQL non quotes en aval. Le bool est ACCEPTE en valeur de filtre (colonne booleenne legitime)
   mais REJETE en `rating` feedback et en `kept_ids` (le piege du sous-type int).
5. **`drill` malforme LEVE** (alors que `sort` malforme degrade a None) : choix d'honnetete de scope.
6. **Identite cachee 5 s** keye sur le Cookie : sur instance mono-process. Si DSS passait multi-process,
   le cache resterait correct (par-process) mais l'election 1er admin reste protegee par le verrou
   consultatif PostgreSQL (cross-connection), pas par le cache.
7. **`new_executor()` refuse de tourner sans connexion configuree** (`sql_config.py:202-206`) : backstop
   defensif ; les routes gardent deja avec `is_configured()`.
8. **`logical_key` stable** : re-sauver la meme selection d'agents preserve les cles -> les conversations
   existantes referencant `agent_key` restent valides (`_logical_key`, hash sha1 tronque).

---

## 10. Diagrammes suggeres
- Sequence `/chat/start` : front -> resolve_identity -> validate -> whitelist -> can_accept (429/503) ->
  save_user_message (phase un) -> build_user_suffix -> start_run (worker) -> {run_id, exchange_id}, puis
  boucle de poll.
- Arbre de gardes : `_evidence_guard` (auth -> config -> bootstrap -> throttle) et `_admin_guard`
  (auth -> config -> is_admin) cote a cote, avec les codes/statuts.
- Diagramme d'etats du run (run_started -> agent_event/answer_delta -> final_answer -> run_done | error |
  stopped) avec les TTL/caps.
- Table de mapping code d'erreur -> statut HTTP (catalogue du paragraphe 5 + 4).
