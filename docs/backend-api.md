# Backend - Référence API & carte des modules

> Plugin **OWIsMind** (Dataiku DSS). Backend Flask modulaire, monté sous `/owismind-api`.
> Documents frères : [architecture.md](./architecture.md) · [frontend.md](./frontend.md) ·
> [data-model.md](./data-model.md) · [security.md](./security.md) · [build-test-deploy.md](./build-test-deploy.md).
>
> Rationale détaillé en mémoire : `memory/PROJECT_STATE.md` (§6 SQL, §8 agents/streaming) et
> `memory/LESSONS.md` (L017/L018 whitelist agents, L019 polling-via-thread). Ce document décrit le code
> **tel qu'implémenté** ; en cas de divergence, la mémoire fait foi pour le *pourquoi*, le code pour le *quoi*.

---

## 1. Vue d'ensemble du backend

Le backend est un **blueprint Flask** (`api`, `url_prefix="/owismind-api"`) défini dans
`python-lib/owismind/api/routes.py` (`routes.py:60`). Toute la logique vit dans le package
`python-lib/owismind/` ; le `backend.py` de la webapp est un **bootstrap mince** qui ne fait que câbler
le blueprint sur l'objet `app` fourni par DSS via le star-import `dataiku.customwebapp` :

```python
# webapps/webapp-owismind-ai-agents/backend.py
from dataiku.customwebapp import *          # fournit l'objet Flask `app`
from owismind.api.routes import register_routes
register_routes(app)                        # enregistre le blueprint /owismind-api
```

`register_routes(app)` (`routes.py:674`) enregistre le blueprint, applique le `log_level` configuré, log le
`storage_status()` résolu et la **table de routes vivante** au boot (utile pour confirmer le build déployé).

Caractéristiques transverses :

- **Python 3.9 / Flask** (pas de FastAPI - backend observé 3.9.x). `/ping` renvoie la version Python réelle.
- **Identité résolue côté serveur** à partir des en-têtes navigateur authentifiés (jamais du corps de requête).
- **Whitelist d'agents serveur** : le front n'envoie qu'une clé logique opaque (`agent_key`), résolue
  vers `(project_key, agent_id)` côté serveur. Un `agent_id` brut n'est jamais accepté.
- **SQL direct, paramétré, sans Flow** au runtime ; `COMMIT` explicite après chaque écriture.
- **Transport = polling, pas SSE** : le proxy nginx interne de DSS bufferise un `text/event-stream` long
  (L019), donc l'agent tourne dans un thread de fond et le front poll des requêtes courtes.
- **Hooks blueprint** : `_log_request_start` / `_log_request_end` (`routes.py:76`, `routes.py:86`) tracent
  méthode + chemin + statut + durée pour chaque requête `/owismind-api/*` (jamais le contenu des messages).

---

## 2. Carte des modules (`python-lib/owismind/`)

| Module | Responsabilité (une ligne) |
|---|---|
| `api/routes.py` | Blueprint Flask `/owismind-api` : toutes les routes HTTP, validation, gardes admin, `register_routes(app)`. |
| `agents/discovery.py` | Découverte **lecture seule** des projets DSS visibles + agents (`list_llms()` filtrés sur `agent:`) - alimente l'espace admin. |
| `agents/stream_manager.py` | Manager in-process des runs agents : `can_accept` (gate admission), `start_run` (worker daemon borné), `poll` (events depuis un curseur), TTL/cap/cooperative stop. |
| `agents/streaming.py` | Exécute **un** run agent (LLM Mesh) et **normalise** les chunks bruts en events JSON-safe (`agent_event` / `answer_delta` / `generated_sql` / `usage_summary` / `trace`). |
| `agents/context.py` | Helpers **purs** (sans `dataiku`) d'assemblage du payload multi-tours : préfixe nom/date, aplatissement des échanges en messages, ordre de replay `with_message`. |
| `security/identity.py` | Résout `{user_id, display_name, groups}` depuis les en-têtes navigateur (cache TTL court), dérive nom complet / prénom ; `IdentityError`. |
| `security/validation.py` | Validateurs **purs** des payloads entrants + bornes (longueur message, session_id, agent_key, history_limit, page conversations, feedback, requêtes Evidence / Source, montants budget, suggestions benchmark, fiche d'agent) ; `ValidationError(code)` stable. |
| `security/impersonation.py` | Impersonation admin « se mettre à la place d'un user » (**lecture seule, temporaire, supprimable**) : `effective_identity` bascule vers la cible portée par l'en-tête `X-OWI-Impersonate` **seulement si le caller réel est admin**. |
| `evidence/sql_parse.py` | Analyse **pure** (sans `dataiku`) du SELECT stocké : tokenizer, `parse_select` (table + prédicats + fragment avancé, raisons de dégradation stables), `validate_fragment` (gate défensive du fragment WHERE). |
| `evidence/query_builders.py` | Builders de **texte SQL purs** Evidence : lookup owner-scopé du `generated_sql`, page de lignes bornée (ORDER BY obligatoire), DISTINCT borné, `render_predicate` (quoters injectés). |
| `evidence/whitelist.py` | Matching **pur** `(schema, table)` parsé ↔ datasets SQL **auto-découverts** du projet (case-insensitive, schéma manquant = wildcard). |
| `evidence/capture.py` | Capture **pure** opportuniste du résultat exact d'un tool SQL (`extract_result`) + caps miroir à la persistance (`cap_result` / `cap_sql_list` : 200 lignes, 50 colonnes, budgets JSON) - jamais de `_bounded()` texte sur ce JSON. |
| `evidence/service.py` | Pipeline Evidence Studio **stateless** : charge le `generated_sql` (owner-scopé), parse, matche un dataset auto-découvert, résout colonnes/schéma live (cache TTL 300 s), re-exécute un SELECT borné **lecture seule** (timeout + `transaction_read_only` en `SET LOCAL`) ; **trust layer** (§3.5 : `verification` / `explanation` / `queries` / `result` / `drilldown`) calculé par des **fonctions pures testées** ; `EvidenceError(code, status)`. |
| `evidence/sql_explain.py` | Explainer SQL **pur** (sans `dataiku`) du trust layer : `explain_select` décompose le SELECT stocké en étapes lisibles + expose les clés GROUP BY drillables ; ne lève jamais (module absent/échec = dégradation honnête, level plafonné). |
| `evidence/chart_payload.py` | Façonnage **pur** du payload Chart.js (`build_chart_payload`) / KPI (`build_kpi_payload`) depuis le résultat SQL capturé + la spec d'artefact : l'agent ne choisit que x / y / type, le backend produit `{labels, datasets}` bornés (`{ok:false}` honnête si inconstructible). |
| `evidence/throttle.py` | Token-bucket **par utilisateur** des routes lecture seule : `can_accept` (Evidence + Source), `usage_can_accept` (`/usage`), `track_can_accept` (`/track`) - absorbe le burst légitime, refuse une rafale scriptée qui pinnerait les threads du backend mono-process. |
| `evidence/source_service.py` | Pipeline **Source Data Explorer** : résout `(agent_key, source_id)` vers un dataset **auto-découvert**, exécute une page **bornée lecture seule** (`source_meta` / `source_rows` / `source_distinct`) + liste les noms de datasets pour le picker admin ; `EvidenceError(code, status)`. |
| `evidence/source_search.py` | Builder **pur** (sans `dataiku`) de la condition de recherche plein-texte du Source Explorer : un ILIKE accent-insensible sur `concat_ws` de toutes les colonnes (fold par `translate`, needle < 2 chars = pas de recherche). |
| `storage/sql_config.py` | Config SQL centrale (connexion / prefix / log_level lus de la config webapp), `new_executor()`, nommage de tables, helpers de sûreté (`sql_value` / `nullable_value` / `pg_identifier` / `bool_literal`). |
| `storage/migrations.py` | DDL idempotent (`CREATE TABLE/INDEX IF NOT EXISTS`) des tables `webapp_chat_v5` / `webapp_users_v1` / `webapp_settings_v1`, garde par-process ; noms logiques `_vN`. |
| `storage/chat_v5.py` | Lectures/écritures de la table chat v4 : write deux phases (user puis reply), feedback owner-scopé, chaîne d'ancêtres (contexte agent), liste de conversations, messages d'une session. |
| `storage/sql_builders.py` | Builders de **texte SQL purs** (sans `dataiku`) : liste de conversations (keyset), messages d'une session, CTE récursive de chaîne d'ancêtres - testables hors DSS. |
| `storage/admin.py` | Registre users/admin (direct SQL) : `record_user` (upsert + bootstrap 1er admin via verrou consultatif), `is_admin` / `count_admins` / `list_users` / `set_admin`. |
| `storage/settings.py` | Registre settings webapp-global clé→JSON ; helpers typés sur la whitelist d'agents (`get_enabled_agents` / `set_enabled_agents` / `resolve_enabled_agent`). |
| `storage/serialization.py` | Normalisation JSON-safe des DataFrames SQLExecutor2 (`rows_to_json_safe` : timestamps ISO, NaN→None via `astype(object)`) ; `parse_json_list`. |
| `storage/pagination.py` | Curseur de **keyset pagination** opaque pour la liste de conversations (`encode_cursor` / `decode_cursor`, base64, décodage défensif). |
| `storage/chat_traces.py` | Persistance **write-only** de la trace agent brute vers un **dataset Flow** (append `write_with_schema`, jamais via SQLExecutor2 → blob hors logs SQL) ; best-effort, borné. |
| `storage/artifacts.py` | Specs d'artefacts (chart / table / KPI) par échange : `_sanitize` (bornes) + `save_artifacts` (UPSERT owner-stamped best-effort) + `read_artifacts` (owner-scopé, read-only + `statement_timeout`). La DONNÉE des artefacts n'est jamais dupliquée (relue du `generated_sql`). Table `webapp_artifacts_v1`. |
| `storage/usage.py` | Comptabilité tokens/coût par utilisateur : `record_usage` incrémente **en une transaction** le cumul lifetime (`webapp_users_v1`) + le bucket mensuel (`webapp_usage_monthly_v1`) depuis les totaux du footer ; best-effort (reconstructible depuis `chat_v5`). |
| `storage/budget.py` | Budget mensuel : résolution de la limite effective (override user actif > boost temporaire global > défaut $50), gate d'enforcement `has_budget` (fail-open), statut `usage_status`, overview admin, set/clear des overrides ; **source de vérité unique** du calcul de limite (cache TTL 30 s de la config globale). |
| `storage/events.py` | Analytics d'usage best-effort : whitelist `EVENT_CATEGORIES` (source de vérité des noms d'events) + `validate_events` (pur, ne lève jamais ; caps batch 40 / props 2000 c, dédup) + `record_events` (1 INSERT multi-lignes `ON CONFLICT DO NOTHING`, jamais de 500). Table `webapp_events_v1`. |
| `storage/suggestions.py` | Intake collaboratif du golden-set : `save_suggestion` (INSERT owner-stamped borné, colonnes superset du golden) + `list_my_suggestions` (owner-scopé, read-only). Le pôle admin LAB relit cross-projet et promeut. Table `webapp_golden_suggestions_v1`. |
| `benchmark_view/` (`aggregate` / `agent_profile` / `lab_io` / `schema_check` / `schemas`) | Consultation benchmark **dans le plugin** : view-models **purs** (`aggregate` = restitution + override, `schemas` = verdict effectif, `schema_check` = colonnes manquantes, `agent_profile` = validation du bloc `benchmark`) + `lab_io` = **seul module I/O DSS** (SQL cross-projet borné : lecture scored, détail 1 ligne, UPDATE override paramétré, listing tables/colonnes). |

**Hors package** : `resource/compute_available_connections.py` - provider DSS `do(payload, …)` qui alimente
les **dropdowns** des paramètres webapp `sql_connection` (connexions PostgreSQL via `list_connections()`),
`traces_dataset` (datasets SQL-backed + une entrée `(none)`) et `evidence_datasets` (SELECT - même listing
SQL-backed **sans** l'entrée `(none)` : un multiselect vide signifie déjà « désactivé »,
`_evidence_dataset_choices`). Strictement lecture seule.

---

## 3. Référence des routes

**Conventions communes**
- **Auth** : sauf `/ping`, toute route appelle `resolve_identity(request.headers)` ; un échec renvoie
  `401 {"status":"error","error":"unauthenticated"}`.
- Sauf `/ping` et `/me`, les routes refusent si le stockage n'est pas configuré :
  `409 {"error":"storage_not_configured"}`.
- Réponse de succès : toujours `{"status":"ok", ...}`. Réponse d'erreur : `{"status":"error","error":<code>}`.
- Les routes `/admin/*` passent par `_admin_guard()` (`routes.py:1444`) : 401 / 409 / 403 (`forbidden`) / 500.
- **Impersonation admin (temporaire, supprimable)** : un admin peut consulter la webapp « à la place » d'un
  user via l'en-tête `X-OWI-Impersonate` (honoré **seulement si le caller réel est admin**,
  `security/impersonation.py`). Les routes de **LECTURE** basculent vers l'identité **effective** (la cible :
  `/me`, `/usage`, `/conversations`, `/conversation`, `_evidence_guard`, `_source_guard`,
  `/benchmark/suggestions`) ; les routes d'**ÉCRITURE** (`/chat/start`, `/chat/stop`, `/chat/feedback`,
  `/benchmark/suggest`, `/benchmark/suggest-from-chat`, `/admin/benchmark/override`) sont **bloquées**
  en `impersonation_read_only → 403` ; `/track` **droppe** silencieusement les events pendant l'impersonation.

### 3.1 Santé & identité

| Méthode | Chemin | Auth | Corps / Query | Succès | Erreurs (code → HTTP) |
|---|---|---|---|---|---|
| `GET` | `/ping` | **Non** | - | `{status:"ok", python:"3.9.x"}` | - |
| `GET` `POST` | `/me` | Oui | - | voir ci-dessous | `unauthenticated → 401` |

**`/me`** (`routes.py:110`) - renvoie l'identité du caller + flags :
`{status:"ok", user_id, display_name, groups, needs_config, is_admin}`.
- `display_name` = défaut dérivé du login (`said.chaoui → Said`), jamais fourni par DSS (L011/L017).
- `needs_config` = `not sql_config.is_configured()`.
- **Effet de bord GET vs POST** : seul **POST** déclenche `admin.record_user(identity)` (upsert dans le
  registre **et** élection du 1er admin). GET reste **lecture seule** : un prefetch/scanner GET ne peut ni
  créer une ligne user ni gagner l'élection. Les deux méthodes renvoient la même forme. Le front émet POST
  une fois à l'init.
- `/ping` (`routes.py:101`) n'expose **jamais** la config de stockage (atteignable sans auth) - celle-ci
  n'est lisible que par un admin via `/admin/storage`.

### 3.2 Agents

| Méthode | Chemin | Auth | Query / Corps | Succès | Erreurs |
|---|---|---|---|---|---|
| `GET` | `/agents` | Oui | - | `{status:"ok", count, agents:[{key,label}]}` | `unauthenticated → 401` · `storage_not_configured → 409` · `storage_unavailable → 500` |

**`/agents`** (`routes.py:724`) - liste les agents que l'admin a activés, pour le picker côté chat. Projette
`key` (= `logical_key` opaque) et `label` - jamais `agent_id` ni `project_key` (whitelist). Projette **aussi**
la **fiche éditoriale** rédigée par l'admin (display-only, sûre à exposer) : `tagline`, `description`,
`capabilities[]`, `tools[]`, `icon`, `badge`, le flag `modes` (le chat n'affiche le picker de mode de réponse
que si l'agent le supporte), `has_benchmark` (booléen **seul** - jamais la table/connexion, cf. §3.10) et
`sources[]` `{id, label, dataset}` (les datasets bruts explorables via le Source Data Explorer, cf. §3.7 ; le
`dataset` est un nom déjà surfacé par Evidence, la connexion/projet restent serveur).

### 3.3 Chat

| Méthode | Chemin | Auth | Corps / Query | Succès | Erreurs (code → HTTP) |
|---|---|---|---|---|---|
| `POST` | `/chat/start` | Oui | corps JSON (voir) | `{status:"ok", run_id, exchange_id}` | voir tableau dédié |
| `GET` | `/chat/poll` | Oui | `run_id`, `cursor` | `{status:"ok", events, cursor, done, error}` | `unauthenticated → 401` · `invalid_run_id → 400` · `run_not_found → 404` |
| `POST` | `/chat/stop` | Oui | `{run_id}` | `{status:"ok"}` | `unauthenticated → 401` · `impersonation_read_only → 403` · `invalid_run_id → 400` · `run_not_found → 404` |
| `POST` | `/chat/feedback` | Oui | corps JSON (voir) | `{status:"ok"}` | voir tableau dédié |

#### `/chat/start` (`routes.py:160`)

Corps JSON (le front n'envoie que de la donnée logique) :

| Champ | Type | Obligatoire | Bornes / défaut |
|---|---|---|---|
| `session_id` | str | oui | non vide, ≤ 128 chars |
| `message` | str | oui | non vide (strip), ≤ 8000 chars |
| `agent_key` | str | oui | clé logique opaque, ≤ 64 chars (résolue contre la whitelist) |
| `history_limit` | int | non | clampé `[10, 50]`, défaut **20** (nb de **messages** à rejouer) ; jamais d'erreur |
| `parent_exchange_id` | str | non | arête d'arbre ; valeur invalide → `None` (= branche racine) ; jamais d'erreur |
| `mode` | str | non | mode de réponse (`smart`/`pro`/`claude`) résolu au **mode effectif** ; ignoré (→ `None`) si l'agent n'a pas le flag `modes` (le token `⟦owi:mode⟧` ne fuite alors jamais dans le prompt). Stampé sur la ligne à la phase un |
| `webapp_lang` | str | non | langue courante de l'UI (`fr`/`en`) ; sert de départage pour détecter la langue de réponse du tour ; inconnue → `None` |
| `screen_context` | obj | non | pointeur borné vers ce que l'utilisateur regarde `{open, exchange_id, active_tab, source_state?}` ; les artefacts sont relus **owner-scopés** par le worker (un id forgé ne révèle que ses propres données). `source_state` (**opt-in par consentement**, bandeau du prompt) = résumé borné de la vue Source data façonnée par l'user `{surface, dataset, agent?, row_count?, q?, filters?, drill?, calc?, analyze?}`, sanitisé par `context.sanitize_source_state` (whitelist de clés, caps, strip `⟦⟧`, never-raises) et rendu dans le bloc `[ON SCREEN NOW]` (section SOURCE-DATA VIEW, budget 1200 chars avec dégradation, phrase de permission verbatim toujours préservée) ; jamais de lignes brutes ; accepté même panneau Evidence fermé (`{open:false, source_state}`). **Transparence** : le `source_state` consenti est aussi **persisté** sur la ligne d'échange (colonne `screen_ctx`, JSON compact, sanitisé AVANT la phase 1) et relu verbatim par `/conversation` pour l'affichage « contexte écran joint » |

Comportement : (1) validation payload ; (2) résolution whitelist `settings.resolve_enabled_agent(agent_key)` ;
(3) **gate d'admission AVANT toute écriture** `stream_manager.can_accept(user_id)` ; (4) **phase un** :
`chat_v5.save_user_message(...)` persiste la question (réponse encore NULL) ; (5) construction du préfixe
nom/date ; (6) `stream_manager.start_run(...)` spawn le worker de fond et renvoie le `run_id` opaque.
Le `message` stocké reste **brut** (préfixe + historique = build-time uniquement).

Codes d'erreur `/chat/start` :

| Code | HTTP | Cause |
|---|---|---|
| `unauthenticated` | 401 | identité non résolue |
| `impersonation_read_only` | **403** | route d'écriture bloquée pendant qu'un admin impersonne un user (consultation seule) - vérifié avant tout travail |
| `<validation code>` | 400 | payload invalide (`missing_message`, `message_too_long`, `empty_message`, `missing_session_id`, `session_id_too_long`, `missing_agent_key`, `agent_key_too_long`, `invalid_payload`, …) |
| `storage_not_configured` | 409 | connexion SQL non choisie |
| `agent_not_enabled` | 404 | `agent_key` forgé/périmé, ne mappe aucun agent activé |
| `rate_limited` | **429** | gate par-utilisateur (`MIN_START_INTERVAL_SECONDS = 1 s`) - avant écriture |
| `busy` | **503** | cap global de runs concurrents atteint (`can_accept` ou `CapacityError`) |
| `monthly_quota_exceeded` | **402** | crédit mensuel atteint (gate `budget.has_budget`, avant écriture) ; la réponse porte le champ `budget` (statut courant). Fail-open sur erreur de lecture du budget |
| `storage_unavailable` | 500 | échec de persistance du message user |
| `agent_unavailable` | 500 | échec du démarrage du worker |

#### `/chat/poll` (`routes.py:267`)

Query params :

| Param | Type | Défaut | Bornes |
|---|---|---|---|
| `run_id` | str | - (requis) | non vide, ≤ 64 chars sinon `invalid_run_id → 400` |
| `cursor` | int | 0 | nb d'events déjà consommés ; valeur non-int ou < 0 → 0 |

Réponse : `{status:"ok", events:[…], cursor, done, error}`. `events` = events normalisés **depuis** le curseur ;
`cursor` = prochain curseur à renvoyer (= taille totale du buffer) ; `done` = run terminé ; `error` = code
terminal (`null` si OK). **Scope owner** : un `run_id` inconnu **ou appartenant à un autre user** → `run_not_found → 404`
(sans révéler lequel). Cadence côté front : ~500 ms (un poll est une requête courte que le proxy ne bufferise pas).

#### `/chat/stop` (`routes.py:539`)

Corps JSON `{run_id}` (l'id opaque de `/chat/start`, ≤ 64 chars sinon `invalid_run_id → 400`). Demande un
arrêt **coopératif** d'un run en vol du caller : le worker voit la requête entre deux chunks streamés, arrête
d'itérer le flux LLM Mesh (qui n'expose aucune API d'annulation), **persiste la réponse PARTIELLE** accumulée
et termine le run par un event terminal `stopped` (pas une erreur). **Scope owner** : un `run_id` inconnu,
déjà terminé/évincé, ou appartenant à un autre user → `run_not_found → 404` (no-op sûr que le client traite
comme « déjà fini »). Route d'écriture : **bloquée en `impersonation_read_only → 403`** pendant une
impersonation. Identité depuis les en-têtes, jamais le corps.

#### `/chat/feedback` (`routes.py:577`)

Corps JSON :

| Champ | Type | Obligatoire | Bornes |
|---|---|---|---|
| `exchange_id` | str | oui | non vide, ≤ 128 chars |
| `rating` | `0` \| `1` \| `null` | oui | 0 = 👎, 1 = 👍, null = effacer. **`true`/`false` rejetés** (bool est sous-type int) |
| `reasons` | list[str] | non | filtrée sur `{incorrect, incomplete, off_topic, other}` (inconnu ignoré), max 8 |
| `comment` | str | non | tronqué à 2000 chars |

L'`UPDATE` (`chat_v5.save_feedback`) est **owner-scopé** (`WHERE exchange_id AND user_id`) : noter l'échange
d'autrui est un no-op silencieux (0 ligne). Erreurs : `unauthenticated → 401` · `storage_not_configured → 409` ·
`invalid_exchange_id` / `invalid_rating` / `invalid_payload → 400` · `storage_unavailable → 500`.

### 3.4 Conversations (sidebar)

| Méthode | Chemin | Auth | Query | Succès | Erreurs |
|---|---|---|---|---|---|
| `GET` | `/conversations` | Oui | `limit`, `cursor` | `{status:"ok", conversations:[{session_id,title,last_at}], next_cursor, has_more}` | `unauthenticated → 401` · `storage_not_configured → 409` · `invalid_cursor → 400` · `storage_unavailable → 500` |
| `GET` | `/conversation` | Oui | `session_id` | `{status:"ok", session_id, count, rows:[…]}` | `unauthenticated → 401` · `storage_not_configured → 409` · `invalid_session_id → 400` · `storage_unavailable → 500` |

**`/conversations`** (`routes.py:348`) - liste **noms seuls**, **keyset-paginée**, owner-scopée. `limit`
clampé `[1, 60]` (défaut 30) ; `cursor` opaque base64 (≤ 512 chars sinon `invalid_cursor`), décodé en
`(last_at, session_id)`. `title` = premier message user de la session, tronqué côté serveur (≤ 140 chars).
`next_cursor`/`has_more` calculés en fetchant 1 ligne de plus. Ne renvoie **jamais** de corps de message.

**`/conversation`** (`routes.py:390`) - tous les messages d'**une** session du user, **chronologique**, borné
(`SESSION_MESSAGES_CAP = 500`). Chargé **paresseusement** au clic sidebar. Strictement scopé `(user_id,
session_id)` (une session d'autrui → 0 ligne). `rows` suit l'ordre de colonnes stable `chat_v5._COLUMNS`
(`user_groups` / `generated_sql` / `feedback_reasons` décodés en listes), donc le front réutilise un seul mapper.

### 3.5 Evidence Studio (owner-scopé, lecture seule, datasets auto-découverts)

| Méthode | Chemin | Auth | Corps / Query | Succès | Erreurs |
|---|---|---|---|---|---|
| `GET` | `/evidence/meta` | Oui | `exchange_id` | `{status:"ok", available, …}` (voir ci-dessous) | voir ci-dessous |
| `POST` | `/evidence/rows` | Oui | corps JSON (voir) | `{status:"ok", rows:[…], has_more, offset}` | voir ci-dessous |
| `POST` | `/evidence/distinct` | Oui | corps JSON (voir) | `{status:"ok", values:[…], truncated}` | voir ci-dessous |

**Invariant central : le front n'envoie JAMAIS de SQL.** Il n'envoie qu'un
`exchange_id`, des filtres **structurés** `{column, op, values}` (les chips éditables), des `kept_ids`
(chips verrouillées, re-dérivées serveur depuis le SQL stocké), une page bornée, un tri optionnel et
d'éventuels labels `drill` `{column, value}` (les colonnes drillables sont **re-dérivées serveur** depuis
le SQL stocké - jamais le choix du client). Table, connexion, SQL et matching dataset sont **tous résolus
côté serveur** (datasets SQL du projet **auto-découverts**, cache TTL 300 s) ; la re-exécution est un
SELECT **borné, lecture seule** sur la **connexion du dataset matché lui-même** (`SQLExecutor2(dataset=…)`),
avec `SET LOCAL statement_timeout TO '30000'` **et** `SET LOCAL transaction_read_only TO on` en
pre-queries (transaction-scopés - défense en profondeur, jamais hérités par la connexion poolée).
Le schéma live (`read_schema`, métadonnées) est lui aussi en cache TTL 300 s (même pattern thread-safe
que le cache de candidats : résolution **hors lock**, échec jamais mis en cache).
Détail sécurité → [security.md](./security.md).

**Garde commune `_evidence_guard()`** (`routes.py:509`) - chaîne : (1) identité
(`resolve_identity` → `unauthenticated → 401`) ; (2) stockage configuré
(`storage_not_configured → 409`) ; (3) bootstrap de la table chat (`ensure_chat_table` →
`storage_unavailable → 500`) - ainsi, sur une instance configurée mais vierge, un `exchange_id`
inconnu/forgé rend le même 404 owner-scopé qu'ailleurs (pas un 500 distinguable) ; (4) **gate de débit
par utilisateur** (`evidence_throttle.can_accept` → `rate_limited → 429`) : un token-bucket par user
(`evidence/throttle.py`) absorbe le burst légitime (la paire meta+rows de l'auto-ouverture) mais refuse
une rafale scriptée qui pinnerait les threads du backend mono-process. Vérifié **après** le chemin
auth/config/bootstrap (peu coûteux).

#### `GET /evidence/meta` (`routes.py:541`)

Query : `exchange_id` (requis, ≤ 128 chars sinon `invalid_exchange_id → 400`). Owner-scopé : l'échange
d'autrui (ou inexistant) → `exchange_not_found → 404` (sans révéler lequel).

Réponse **interactive** (`available: true`) - champs v1 inchangés + **trust layer** (contrat gelé
`docs/superpowers/specs/2026-06-10-evidence-trust-layer-design.md` §2, blocs **additifs**, tous calculés
par des fonctions **pures, déterministes, testées** - aucun LLM dans le chemin de preuve) :

```json
{"status":"ok", "available":true, "dataset":"<nom DSS>",
 "columns":[{"name","type"}], "chips":[{"id","column","op","values","editable"}],
 "advanced":{"present":bool, "display":"<fragment>|null"}, "sql":"<SQL agent>",

 "source": {"dataset":"<nom DSS>", "schema":"<schéma physique|null>", "table":"<table physique>"},
 "queries": [{"index":1, "success":bool, "row_count":int|null, "matched":bool,
              "step_index":int?, "agent_key":str?, "result_captured":bool}],
 "verification": {"level":"declared|source_identified|scope_partial|scope_exact|calc_decomposed",
                  "result_captured":bool, "dropped_predicates":int,
                  "dropped_display":["<str>"], "single_source":bool,
                  "where_complete":bool, "select_understood":bool},
 "explanation": {"ok":bool, "steps":[{"kind":"<ev.exp.*>", "params":[…]}]},
 "result": {"captured":true, "columns":[…], "rows":[[…]], "row_count":int|null, "truncated":bool}
        |  {"captured":false, "row_count":int|null},
 "drilldown": {"available":bool, "columns":["<casse live>"],
               "reason":null|"no_group_keys"|"multi_source"|"incomplete_where"|"set_op"|"not_supported"}}
```

Sémantique (règles d'honnêteté §9 du contrat) :
- `queries[]` résume **tous** les items SQL stockés (index 1-based ; `matched` = sa table matche un
  dataset découvert, même matcher borné que le pipeline ; `step_index`/`agent_key` seulement si présents) ;
- `verification.level` est l'échelle déterministe du contrat ; `where_complete` =
  `explain.where_complete` **ET** zéro prédicat droppé par le colmap live ; `dropped_predicates` =
  (prédicats parsés − gardés) + conjoncts non décomposés par l'explainer ; `dropped_display` ≤ 10
  chaînes (le **compte** reste exact) ; `result_captured` est **orthogonal** au level ;
- `explanation.steps` (≤ 15) vient de `evidence/sql_explain.explain_select` sur le SQL **actif**
  (import gardé : module absent/en échec → `{"ok": false, "steps": []}`, level plafonné à
  `source_identified`, drill `not_supported` - dégradation honnête, jamais un crash) ;
- `result` = les lignes **exactement vues par l'agent** quand elles ont été capturées
  (`chat_v5.generated_sql[].result`, caps `evidence/capture.py`) ; `row_count` = compte déclaré par
  l'agent, jamais `len(rows)` ; pas de capture → `captured:false` (jamais de lignes inventées) ;
- `drilldown.columns` = clés GROUP BY de l'explainer ∩ schéma live (casse live) ; refus → code stable.

Réponse **dégradée** : `{"status":"ok", "available":false, "reason":<code>, "sql":<SQL brut|null>,
"verification":{"level":"declared","result_captured":false}}`.
Toute `EvidenceError` **sauf** `exchange_not_found` dégrade vers cette forme honnête (le panneau front
affiche alors le SQL brut comme **affirmation** de l'agent, pas comme preuve). Codes `reason` stables :

| Famille | Codes |
|---|---|
| Parse (`sql_parse.parse_select`, best-effort - ne refuse que « pas un SELECT analysable ») | `invalid_sql`, `sql_too_long`, `tokenize_failed`, `comment_unsupported`, `multi_statement`, `not_select`, `unbalanced_parens` |
| Service (`evidence/service.py`) | `no_sql`, `no_successful_sql`, `no_matching_dataset`, `dataset_unavailable`, `dataset_schema_invalid`, `fragment_rejected`, `dataset_table_invalid` |

Erreurs HTTP : `unauthenticated → 401` · `storage_not_configured → 409` · `storage_unavailable → 500` ·
`rate_limited → 429` (gate par-utilisateur) · `invalid_exchange_id → 400` · `exchange_not_found → 404` ·
`evidence_unavailable → 500` (inattendu). Log : une ligne par meta avec
`available`/`reason`/`level`/`result_captured`/`drill_available`.

#### `POST /evidence/rows` (`routes.py:578`)

Corps JSON (validé par `validate_evidence_rows_request`, `validation.py:258`) :

| Champ | Type | Obligatoire | Bornes |
|---|---|---|---|
| `exchange_id` | str | oui | non vide, ≤ 128 chars |
| `filters` | list | non | ≤ 20 items `{column ≤ 128 chars, op ∈ {"=","IN"}, values}` ; `values` = 1..50 (exactement 1 pour `"="`) ; valeur = str ≤ 500 chars, nombre **fini** (NaN/Inf rejetés) ou bool |
| `kept_ids` | list[int] | non | ≤ 100, entiers ≥ 0 (**bool rejeté** - sous-type int) |
| `include_advanced` | bool | non | coercé en bool |
| `limit` | int | non | **clampé** `[1, 100]`, défaut **50** (`DEFAULT_ROWS_LIMIT`) - ne lève jamais ; fenêtre de lignes explicite (remplace l'ancien `page`) |
| `offset` | int | non | **clampé** `[0, 500]` (`MAX_ROWS_OFFSET`) - ne lève jamais (borne le coût du tri OFFSET : la fenêtre navigable = 600 lignes avant de devoir filtrer) |
| `sort` | `{column, dir}` | non | malformé → dégrade à `None` ; `dir` normalisé `asc`/`desc` |
| `drill` | list | non | ≤ 8 items `{column ≤ 128 chars, value}` ; `value` = str ≤ 500, nombre **fini**, bool ou **null** (→ `IS NULL`) ; toute violation **lève** `invalid_drill → 400` (un drill droppé en silence montrerait la page NON drillée) |
| `table` | str | non | sélecteur de table source (multi-table SQL), identifiant borné ≤ 256 chars ; malformé → `None` (= 1re table matchée) ; re-validé serveur contre l'ensemble des tables matchées du SQL (jamais une autorité) |
| `q` | str | non | terme de recherche plein-texte (nettoyé + capé 200 chars, ne lève jamais) ; effectif seulement si sa forme pliée ≥ 2 chars ; matché serveur sur **toutes** les colonnes live |

Comportement : les chips **éditables** voyagent comme `filters` (leur état courant), les chips
**verrouillées** comme `kept_ids` (re-dérivées serveur depuis le SQL stocké) ; le fragment avancé n'est
**jamais** transmis (le serveur le re-valide et le re-applique si `include_advanced`). **Drill-down** :
le serveur re-dérive les colonnes drillables depuis le SQL **stocké** (mêmes gates que `meta.drilldown` :
explain ok, source unique, WHERE complet, pas de set-op/CTE récursif) ; chaque `drill.column` doit
appartenir à cet ensemble (∩ schéma live) sinon `invalid_drill → 400` ; les conditions `col = value`
(`value null` → `IS NULL`) s'**ajoutent** aux conditions standard. Colonnes de filtre/tri
résolues contre le **schéma live** du dataset (case-insensitive). Un `q` non vide ajoute un ILIKE
accent-insensible sur toutes les colonnes. Fenêtre de `limit` lignes (défaut 50) - `LIMIT limit+1` →
`has_more` sans `COUNT(*)`.

Réponse : `{"status":"ok", "rows":[…], "has_more":bool, "offset":int}`.

Erreurs : `rate_limited → 429` (gate par-utilisateur, garde commune) ; validation → 400 (`invalid_payload`,
`invalid_exchange_id`, `invalid_filters`, `invalid_filter_column`, `invalid_filter_op`,
`invalid_filter_values`, `invalid_filter_value`, `filter_value_too_long`, `invalid_kept_ids`,
`invalid_drill`) ; `EvidenceError` → son statut : `exchange_not_found → 404`,
`invalid_filter_column` / `invalid_sort_column` / `invalid_drill → 400` (colonne absente du schéma
live / drill hors de l'ensemble dérivé serveur), tous les codes de
dégradation ci-dessus + `query_failed → 409` (ici **pas** de forme dégradée : la route exige le contexte
interactif) ; `evidence_unavailable → 500` (inattendu).

#### `POST /evidence/distinct` (passé de GET à POST avec la cascade)

Corps : `{exchange_id, column, q?, exclude_id?, filters?, kept_ids?, include_advanced?, drill?, scope_q?}`
(`exchange_id` requis ≤ 128 ; `column` requis ≤ 128 sinon `invalid_filter_column → 400` - forme seule,
l'existence est revalidée contre le schéma live ; `q` optionnel : terme rétrécissant le picker aux valeurs
de **cette** colonne qui matchent, nettoyé par `_clean_source_query`, jamais d'erreur). Alimente le
**picker** de valeurs des chips, désormais **EN CASCADE** : en plus du scope dur de l'agent (tout prédicat
**verrouillé** non éditable + fragment avancé, toujours appliqués ; `exclude_id` = id serveur de la chip en
cours d'édition, qui ne se self-scope jamais), le picker honore les **autres** filtres actifs (`filters`,
la chip éditée étant omise par le client), la recherche table (`scope_q`, sur toutes les colonnes) et le
`drill` actif : une valeur à zéro ligne sous les autres filtres n'est plus proposée. `kept_ids` /
`include_advanced` sont acceptés (parité de forme avec `/evidence/rows`) mais non retransmis (le scope
verrouillé est re-dérivé serveur). Sans les nouveaux champs, comportement byte-identique à l'ancien picker.
Plan `subquery-LIMIT-puis-tri` :
le `DISTINCT … LIMIT` tourne dans une sous-requête et seul le résultat borné est trié (évite de forcer le
tri de toutes les valeurs distinctes d'une grande table). Réponse :
`{"status":"ok", "values":[…], "truncated":bool}` - max **100 valeurs** (`DISTINCT_LIMIT`, fetch 101 →
`truncated` sans faux positif), `NULL` exclus, trié. Mêmes erreurs que `/evidence/rows` (sans les codes
de filtres) + `query_failed → 409` (erreur DB).

### 3.6 Admin (`_admin_guard()`, gardé serveur)

Toutes en `unauthenticated → 401` / `storage_not_configured → 409` / `forbidden → 403` (non admin) / `storage_unavailable → 500`.

| Méthode | Chemin | Corps / Path | Succès | Erreurs spécifiques |
|---|---|---|---|---|
| `GET` | `/admin/storage` | - | `{status:"ok", storage:{…}}` (`sql_config.storage_status()`) | - |
| `GET` | `/admin/users` | - | `{status:"ok", count, users:[…]}` | - |
| `POST` | `/admin/users/set-admin` | `{user_id, is_admin}` | `{status:"ok", users:[…]}` | `missing_user_id → 400` · `cannot_remove_last_admin → 400` |
| `GET` | `/admin/projects` | - | `{status:"ok", count, projects:[…]}` | `discovery_unavailable → 500` |
| `GET` | `/admin/projects/<project_key>/agents` | path `project_key` | `{status:"ok", project_key, count, agents:[{agent_id,description}]}` | `project_not_found → 404` · `discovery_unavailable → 500` |
| `GET` `POST` | `/admin/agents` | GET - / POST `{agents:[{project_key,agent_id}]}` | `{status:"ok", count, agents:[…]}` | `invalid_payload → 400` · `too_many_agents → 400` |

Détails :
- **`/admin/storage`** (`routes.py:493`) - config de stockage résolue : `connection`, `project_key` (+ source),
  `table_prefix` (+ `_input` / `_ignored`), `namespace`, `traces_dataset`, et les noms physiques calculés
  (`chat` / `users` / `settings`).
- **`/admin/users/set-admin`** (`routes.py:516`) - garde **anti-lockout** : refuse de retirer le **dernier**
  admin (`cannot_remove_last_admin`). Renvoie la liste users à jour.
- **`/admin/projects/<project_key>/agents`** (`routes.py:557`) - le `project_key` est revalidé contre la liste
  des projets **visibles** avant le listing (un admin ne peut pas sonder une clé arbitraire/cachée).
- **`/admin/agents` POST** (`routes.py:1663`) - chaque agent demandé est **re-validé serveur** contre les
  listings DSS vivants (projet visible **et** agent réellement présent) avant persistance ; cap
  `MAX_ENABLED_AGENTS = 50`. La `logical_key` opaque est dérivée d'un hash stable de `project_key:agent_id`
  (`_logical_key`, `routes.py:100`) - le front ne reçoit jamais d'`agent_id` brut. Chaque agent porte aussi
  son **profil** éditorial (`validate_agent_meta`, display-only borné : jamais une requête/table/connexion).

### 3.7 Source Data Explorer (lecture seule, datasets bruts configurés par agent)

Tout user authentifié peut explorer les datasets **bruts** qu'un admin a rattachés à un agent (avant/après un
prompt). Le front n'envoie qu'une **clé d'agent opaque** + un **index de source entier** (dans le bloc
`sources` validé de la fiche d'agent) + des filtres Evidence-shaped + un `q` plein-texte ; le serveur résout
l'index vers un dataset **auto-découvert** et exécute une page **bornée lecture seule**. Miroir de `/evidence/*`
(même throttle, mêmes bornes de lignes). Garde commune `_source_guard()` (`routes.py:994`) : identité
(+ impersonation effective) + stockage configuré + throttle par-user, **sans** bootstrap de la table chat
(l'explorer ne lit que des datasets projet, jamais le stockage chat).

| Méthode | Chemin | Auth | Query / Corps | Succès | Erreurs |
|---|---|---|---|---|---|
| `GET` | `/source/meta` | Oui | `agent`, `source` | `{status:"ok", label, columns:[{name,type}]}` | voir ci-dessous |
| `POST` | `/source/rows` | Oui | corps JSON (voir) | `{status:"ok", rows:[…], has_more, offset}` | voir ci-dessous |
| `POST` | `/source/distinct` | Oui | corps JSON (voir) | `{status:"ok", values:[…], truncated}` | voir ci-dessous |
| `GET` | `/admin/sources/datasets` | **Admin** | - | `{status:"ok", datasets:[…]}` | dégrade à `{datasets:[], error}` |

- **`/source/meta`** (`routes.py:1023`) - descripteur d'une source : son `label` + la liste des colonnes live.
  Params `agent` (clé opaque) + `source` (index int) ; table/connexion résolus serveur.
- **`/source/rows`** (`routes.py:1049`) - une fenêtre bornée du dataset source, filtrée + éventuellement
  cherchée. Corps `{agent, source, q?, filters?, limit?, offset?, sort?}` ; jamais de SQL : `filters` en
  `{column, op, values}`, `q` matché serveur sur **toutes** les colonnes ; `limit`/`offset` clampés (mêmes
  bornes que `/evidence/rows`). `LIMIT limit+1` → `has_more` sans `COUNT(*)`.
- **`/source/distinct`** (POST, passé de GET avec la cascade) - valeurs distinctes bornées d'**une** colonne
  (picker de chips). Corps `{agent, source, column, q?, filters?, scope_q?}` : le picker est **EN CASCADE** -
  `filters` (les **autres** chips actives, la chip éditée étant omise par le client) + `scope_q` (recherche
  table sur toutes les colonnes) le scopent via le **même** `_source_conditions` que `/source/rows` ; `q`
  reste la recherche du picker sur cette seule colonne. Sans `filters`/`scope_q`, byte-identique à l'ancien
  picker. Max **100** valeurs (`DISTINCT_LIMIT`), `NULL` exclus.
- **`/admin/sources/datasets`** (`routes.py:1103`, **admin-gated**) - noms des datasets SQL **découverts** du
  projet, pour le picker admin de sources. Un échec de listing dégrade à `{datasets:[], error}` (jamais un 500).

Erreurs `/source/*` (`source_service.EvidenceError(code, status)`) : `source_not_found → 404`,
`no_matching_dataset → 404`, `dataset_table_invalid` / `dataset_schema_invalid` / `query_failed → 409`,
`invalid_filter_column` / `invalid_sort_column → 400` ; validation `invalid_agent` / `invalid_source` /
`invalid_payload → 400` ; `source_unavailable → 500` (inattendu) ; + garde commune `unauthenticated → 401` ·
`storage_not_configured → 409` · `rate_limited → 429`.

### 3.8 Budget & quota mensuel

Crédit mensuel glissant par user (défaut **$50**, mois calendaire, reset le 1er via `date_trunc`) : la dépense
= coût Mesh accumulé dans `webapp_usage_monthly_v1`. `storage/budget.py` résout la limite **effective**
(override user actif > boost temporaire global > défaut). Détail modèle → [data-model.md](./data-model.md).

| Méthode | Chemin | Auth | Query / Corps | Succès | Erreurs spécifiques |
|---|---|---|---|---|---|
| `GET` | `/usage` | Oui | - | `{status:"ok", usage:{…}}` | `rate_limited → 429` · `storage_unavailable → 500` |
| `GET` `POST` | `/admin/budget` | **Admin** | GET - / POST `{limit_usd, enabled, temp_limit_usd?, temp_days?, clear_temp?}` | `{status:"ok", config, period_start, next_reset, users:[…]}` | `invalid_amount` / `invalid_expires → 400` |
| `POST` | `/admin/budget/users` | **Admin** | `{user_ids:[…], clear?, limit_usd?, expires_days?, note?}` | `{status:"ok", config, …, users:[…]}` | `invalid_user_ids` / `too_many_users` / `invalid_amount` / `invalid_expires → 400` |

- **`/usage`** (`routes.py:216`) - statut budget mensuel du **caller lui-même** (dépense, limite effective + sa
  SOURCE - défaut / boost global / override user -, restant, date de reset, tokens mois + lifetime). Strictement
  owner-scopé (identité résolue, jamais un champ du corps) ; throttlé par-user (`usage_can_accept`). Lecture seule.
- **`/admin/budget`** (`routes.py:1515`) - GET = config globale + overview par user (dépense courante + limite
  effective de chacun). POST persiste `{limit_usd, enabled}` **toujours** et gère le boost temporaire
  indépendamment : `clear_temp:true` le retire ; `temp_limit_usd` + `temp_days` en arme un frais ; ni l'un ni
  l'autre (l'édition du seul défaut) **préserve** le boost actif. Retourne l'overview rafraîchi.
- **`/admin/budget/users`** (`routes.py:1575`) - pose/efface un override de limite **par user** pour un /
  plusieurs / tous. `clear:true` retire l'override (retour à la limite globale) ; sinon upsert avec `limit_usd`
  (requis) + `expires_days` optionnel (absent = permanent, un int = boost temporaire) + `note`. Liste `user_ids`
  bornée, tout re-validé serveur.

### 3.9 Analytics d'usage (`POST /track`)

**`POST /track`** (`routes.py:261`) - ingestion **best-effort** d'events d'usage produit batchés par le front
(souvent via `navigator.sendBeacon`, Content-Type `text/plain` → `get_json(force=True)`). **Renvoie TOUJOURS
`200`, jamais de `500`.** Identité résolue serveur (jamais du corps) ; le batch est écrit sous le `user_id`
authentifié. Garanties « le tracking ne casse jamais le produit » : non-authentifié / stockage non configuré →
`accepted=0` (toujours 200) ; events envoyés pendant une **impersonation** admin **droppés** ; token-bucket
par-user (`track_can_accept`) qui droppe silencieusement une rafale ; toute erreur inattendue → `accepted=0`
(route entière try/except). `events_storage.validate_events` (whitelist de noms, caps batch 40 / props 2000 c,
dédup) puis `record_events` (1 INSERT multi-lignes `ON CONFLICT DO NOTHING`). Réponse : `{ok:true, accepted:<int>}`.
Modèle de la table `webapp_events_v1` → [data-model.md](./data-model.md).

### 3.10 Benchmark (suggestions collaboratives + consultation + override admin)

Deux pôles. Les users **suggèrent** des questions/réponses pour le golden-set (stockées owner-stamped dans
`webapp_golden_suggestions_v1`), et tout user **consulte** les résultats de benchmark d'un agent (la table du
scored vit dans le projet **LAB**, lue cross-projet par `benchmark_view/lab_io.py` ; la table/connexion sont
résolues **serveur** depuis la fiche d'agent, jamais acceptées du client). L'admin peut **overrider** le verdict
du juge (human-in-the-loop). Helper `_benchmark_block_for_key` (`routes.py:1289`) : résout la clé opaque → le
bloc `benchmark` validé, ou `None`.

| Méthode | Chemin | Auth | Query / Corps | Succès | Erreurs spécifiques |
|---|---|---|---|---|---|
| `POST` | `/benchmark/suggest` | Oui | `{question, reference_answer, expected_value?, expected_value_type?, category?, language?}` | `{status:"ok", suggestion_id}` | `impersonation_read_only → 403` · `invalid_* → 400` |
| `POST` | `/benchmark/suggest-from-chat` | Oui | `{exchange_id, answer_is_correct, reference_answer?, missing_explanation?, category?}` | `{status:"ok", suggestion_id}` | `impersonation_read_only → 403` · `exchange_not_found → 404` · `empty_agent_answer → 400` · `invalid_* → 400` |
| `GET` | `/benchmark/suggestions` | Oui | - | `{status:"ok", count, suggestions:[…]}` | `unauthenticated → 401` · `storage_not_configured → 409` |
| `GET` | `/benchmark/results` | Oui | `agent`, `benchmark_id?` | `{status:"ok", configured, results:{…}}` | `unauthenticated → 401` · `storage_not_configured → 409` |
| `GET` | `/benchmark/attempt` | Oui | `agent`, `run_id`, `question_id`, `agent_key`, `mode` | `{status:"ok", configured, detail:{…}}` | `unauthenticated → 401` · `storage_not_configured → 409` |
| `GET` | `/admin/benchmark/tables` | **Admin** | `connection?` | `{status:"ok", tables:[…]}` | dégrade à `{tables:[], error}` |
| `POST` | `/admin/benchmark/validate-table` | **Admin** | `{connection?, table}` | `{status:"ok", ok, missing:[…]}` | - |
| `POST` | `/admin/benchmark/override` | **Admin** | `{agent, question_id, run_id, agent_key, mode, verdict, …}` | `{status:"ok", …}` | `agent_has_no_benchmark` / `invalid_override → 400` · `impersonation_read_only → 403` |

- **`/benchmark/suggest`** (`routes.py:1129`) - suggestion **manuelle** (autonome) : question + réponse vouchée,
  bornée serveur, row owner-stamped. Écriture **bloquée en impersonation**.
- **`/benchmark/suggest-from-chat`** (`routes.py:1180`) - suggestion bâtie depuis une réponse de chat du caller :
  la question / réponse agent / `agent_key` / SQL sont **reconstruits de l'échange PERSISTÉ** (owner-scopé),
  jamais du client. « Oui » stocke la réponse agent comme référence (exemple positif) ; « Non » exige la
  correction. `empty_agent_answer → 400` si « Oui » sur un échange sans réponse stockée.
- **`/benchmark/suggestions`** (`routes.py:1261`) - liste les suggestions **du caller** (newest-first,
  owner-scopé + borné).
- **`/benchmark/results`** (`routes.py:1306`) - consultation des résultats d'**un** agent (tout user). `agent`
  = clé opaque (résolue serveur vers la table admin-configurée) ; `benchmark_id` sélectionne le benchmark nommé
  (le plus récent par défaut). Renvoie le view-model (verdict, KPIs, par agent×mode, par catégorie, détail par
  question + évolution des tentatives + attendu vs réel, sélecteur `benchmarks`), recalculé sur le **verdict
  effectif** (override admin prioritaire). Agent sans bloc benchmark → `{configured:false}`.
- **`/benchmark/attempt`** (`routes.py:1339`) - détail **COMPLET** d'**une** tentative (chargé à la demande) :
  les 4 clés (`run_id`, `question_id`, `agent_key`, `mode`) sélectionnent la ligne ; renvoie la réponse agent
  complète + le SQL réellement généré + le tableau capturé de chaque requête. Read-only, 1 ligne.
- **`/admin/benchmark/tables`** (`routes.py:1374`) - tables `public` d'une connexion SQL, pour le picker de
  table de la fiche d'agent. Un échec de lecture dégrade à `{tables:[], error}`.
- **`/admin/benchmark/validate-table`** (`routes.py:1387`) - vérifie qu'une table candidate porte les colonnes
  que la consultation exige (`bench_schema.check_columns`) ; rapporte les colonnes manquantes.
- **`/admin/benchmark/override`** (`routes.py:1407`) - override (ou efface) le verdict du juge sur une ligne
  scored : résout la table serveur depuis la clé opaque, valide, écrit les colonnes `human_*` via un UPDATE
  paramétré borné (`lab_io.write_override`). Écriture **bloquée en impersonation**.

---

## 4. Cycle de vie d'un run agent

Voir `agents/stream_manager.py` (orchestration) et `agents/streaming.py` (normalisation). Rationale → L019.

1. **`/chat/start`** valide, résout l'agent (whitelist), passe la **gate d'admission**, persiste le message
   user (phase un), puis appelle `stream_manager.start_run(...)` → enregistre l'état du run sous un `run_id`
   (uuid hex), spawn **un** thread daemon `_worker`, renvoie `{run_id, exchange_id}`.
2. **Worker** (`stream_manager._worker`) :
   - émet `run_started` ;
   - assemble le **contexte multi-tours** : `chat_v5.history_messages_for_chain(user_id, parent_exchange_id,
     history_limit)` (CTE récursive remontant la **chaîne d'ancêtres** de la branche, user-scopée 2×, bornée
     profondeur + LIMIT) + le tour courant préfixé (`context.build_completion_messages`). Échec d'historique →
     dégrade au tour courant seul (ne casse jamais le chat) ;
   - itère `streaming.run_agent_streamed(project_key, agent_id, messages)` qui rejoue chaque tour via
     `completion.with_message(content, role)` puis `execute_streamed()`, et **normalise** les chunks bruts en
     events JSON-safe ;
   - accumule le texte réponse (cappé `MAX_ANSWER_CHARS`), les SQL générées, et capture la **trace brute**
     (event `trace`, **hors timeline** - persistance seule) ;
   - **phase deux** : `chat_v5.save_assistant_message(exchange_id, answer, sql_list)` puis
     `chat_traces.save_trace(exchange_id, trace_raw)` (best-effort : un échec de stockage n'avorte jamais le run) ;
   - émet `final_answer` puis `run_done` (ou `error`) ; marque `done` **après** les events terminaux (un poll
     voyant `done == True` voit garanti les events terminaux).
3. **`/chat/poll`** renvoie les events depuis le `cursor` + `done`/`error` ; sert de **heartbeat**
   (`last_poll_at`) au worker pour détecter l'abandon.

**Events normalisés** (ordre de stream) :

| Type | Charge utile | Origine |
|---|---|---|
| `run_started` | `exchangeId` | worker (début) |
| `agent_event` | `eventKind, blockId, nextBlockId, toolName, elapsedSeconds` | cycle de vie agent (live) |
| `answer_delta` | `text` | delta de texte réponse (live) |
| `generated_sql` | `sqlIndex, success, rowCount, sql` | footer (0..n) |
| `usage_summary` | `promptTokens, completionTokens, totalTokens, estimatedCost` | footer (totaux) |
| `trace` | `trace` | footer brut - **persistance seule, jamais dans la timeline polled** |
| `final_answer` | `exchangeId, text` | worker (fin) |
| `run_done` | `status:"success"` | worker (succès) |
| `stopped` | - | worker (arrêt coopératif via `/chat/stop` ; la réponse partielle est persistée) |
| `error` | `message` (`agent_unavailable`, `run_timeout`, `run_abandoned`) | worker (échec / coupe) |

**Gate admission rate/capacité** (`can_accept`, `routes.py:226`) :
- cap global concurrent `MAX_CONCURRENT_RUNS = 8` atteint → `busy` (**503**) ;
- spacing par-user `MIN_START_INTERVAL_SECONDS = 1 s` → `rate_limited` (**429**).
La pré-check évite une écriture inutile ; le cap dur dans `start_run` reste le vrai garde (lève `CapacityError`).

**Cooperative stop** (`_stop_reason`, évalué entre chunks) :
- `MAX_RUN_SECONDS = 300 s` → coupe `run_timeout` ;
- `ABANDON_AFTER_SECONDS = 30 s` sans poll après avoir commencé à poller → coupe `run_abandoned` (libère le slot).
La réponse partielle est tout de même persistée. **Limite connue** : évaluées **entre** chunks - un appel
upstream totalement bloqué reste borné seulement par le TTL mémoire (pas de watchdog dédié, choix assumé).

**TTL / mémoire** : `FINISHED_TTL_SECONDS = 60 s` (poll tardif/dupliqué voit encore les events terminaux),
`HARD_TTL_SECONDS = 600 s` (cap absolu de vie d'un run orphelin), `MAX_LIVE_EVENTS = 5000`,
`MAX_ANSWER_CHARS = 1 000 000` (défense en profondeur).

---

## 5. Validation & codes d'erreur

Validateurs **purs** dans `security/validation.py` ; chaque erreur structurelle lève `ValidationError(code)`
avec un `code` **stable, machine-readable** renvoyé tel quel au front (jamais de détail interne).

| Validateur | Entrée | Bornes / comportement | Codes (lève) |
|---|---|---|---|
| `validate_message` | `message` | non vide après strip, ≤ `MAX_MESSAGE_LENGTH = 8000` | `invalid_payload`, `missing_message`, `message_too_long`, `empty_message` |
| `validate_chat_request` | `session_id, message` | session_id non vide, ≤ `MAX_SESSION_ID_LENGTH = 128` | + `missing_session_id`, `empty_session_id`, `session_id_too_long` |
| `validate_chat_start_request` | + `agent_key` | non vide, ≤ `MAX_AGENT_KEY_LENGTH = 64` | + `missing_agent_key`, `empty_agent_key`, `agent_key_too_long` |
| `validate_history_limit` | `history_limit` | clamp `[10, 50]`, défaut **20** - **ne lève jamais** | - |
| `validate_conversations_limit` | `limit` | clamp `[1, 60]`, défaut **30** - **ne lève jamais** | - |
| `validate_feedback` | payload feedback | `exchange_id` requis (≤128) ; `rating ∈ {0,1,None}` (**bool rejeté**) ; reasons filtrées (≤8) ; comment ≤ 2000 | `invalid_payload`, `invalid_exchange_id`, `invalid_rating` |
| `validate_optional_exchange_id` | `parent_exchange_id` | str non vide ≤128 sinon `None` - **ne lève jamais** | - |
| `validate_required_exchange_id` | `exchange_id` | str non vide, ≤128 - **obligatoire** (≠ variante optionnelle) | `invalid_exchange_id` |
| `validate_evidence_column` | nom de colonne | forme seule (≤ `MAX_EVIDENCE_COLUMN_CHARS = 128`) - l'existence est revalidée contre le schéma live par le service | `invalid_filter_column` |
| `validate_evidence_rows_request` | payload `/evidence/rows` | filtres ≤20 (`op ∈ {=,IN}`, values 1..50, str ≤500, bool accepté, NaN/Inf rejetés) ; `kept_ids` ≤100 entiers ≥0 (bool rejeté) ; `limit` **clampée** `[1,100]` déf 50 + `offset` **clampée** `[0,500]` (ne lèvent jamais - bornent le coût du tri OFFSET : fenêtre 600 lignes avant de devoir filtrer) ; `sort` malformé → `None` ; `drill` ≤8 items `{column ≤128, value: str ≤500 \| nombre fini \| bool \| null}` - malformé **lève** (code unique `invalid_drill` ; un drill droppé en silence montrerait la page non drillée) ; `table` ≤256 chars malformé → `None` ; `q` nettoyé + capé 200 chars (ne lève jamais) | `invalid_payload`, `invalid_exchange_id`, `invalid_filters`, `invalid_filter_column`, `invalid_filter_op`, `invalid_filter_values`, `invalid_filter_value`, `filter_value_too_long`, `invalid_kept_ids`, `invalid_drill` |
| `validate_source_rows_request` | payload `/source/rows` | miroir de `validate_evidence_rows_request` mais keyé `(agent, source)` : `agent` clé opaque ≤64, `source` index `[0,8)` (bool rejeté), `q` nettoyé ≤200, filtres ≤20, `limit`/`offset` clampés | `invalid_payload`, `invalid_agent`, `invalid_source`, `invalid_filters`, `invalid_filter_*` |
| `validate_source_meta_params` | query `/source/meta` | `(agent, source)` : `agent` ≤64, `source` `[0,8)` | `invalid_agent`, `invalid_source` |
| `validate_source_distinct_request` | payload `/source/distinct` (POST) | `{agent, source, column, q?, filters?, scope_q?}` : mêmes helpers que `/source/rows` (`filters` ≤20, ops `=`/`IN`/`BETWEEN`) ; `q` (recherche picker sur la colonne) et `scope_q` (recherche table) nettoyés ≤200, ne lèvent jamais | `invalid_payload`, `invalid_agent`, `invalid_source`, `invalid_filter_column`, `invalid_filter_*` |
| `validate_evidence_distinct_request` | payload `/evidence/distinct` (POST) | `{exchange_id, column, q?, exclude_id?, filters?, kept_ids?, include_advanced?, drill?, scope_q?}` : mêmes parseurs que `/evidence/rows` ; `exclude_id` malformé → `None` (ne lève jamais) | `invalid_payload`, `invalid_exchange_id`, `invalid_filter_column`, `invalid_filter_*`, `invalid_kept_ids`, `invalid_drill` |
| `validate_suggestion_manual` | payload `/benchmark/suggest` | `question` + `reference_answer` requis (bornés) ; `expected_value` optionnel exige son `expected_value_type` (enum) ; `category`, `language` (déf `fr`) | `invalid_payload`, `invalid_question`, `invalid_reference`, `invalid_expected_type`, `missing_expected_type` |
| `validate_suggestion_from_chat` | payload `/benchmark/suggest-from-chat` | `exchange_id` requis + `answer_is_correct` bool strict ; verdict « Non » exige `reference_answer` ; `missing_explanation`/`category` optionnels ; Q/R/agent_key/SQL **non** pris du client | `invalid_payload`, `invalid_exchange_id`, `invalid_verdict`, `missing_reference` |
| `validate_budget_amount` | montant USD | nombre **fini** `[0, 1 000 000]` (0 = blocage dur autorisé) ; NaN/Inf/négatif/bool rejetés ; `OverflowError` d'un entier JSON géant → 400 propre | `invalid_amount` |
| `validate_expires_days` | durée boost | None/0/"" → `None` (permanent) ; sinon int `[1, 3650]` (bool rejeté) | `invalid_expires` |
| `validate_user_id_list` | liste d'ids | non vide, dé-dup ordonnée, ≤ `MAX_QUOTA_USERS = 1000`, chaque id ≤128 | `invalid_user_ids`, `too_many_users` |
| `validate_quota_note` | mémo admin | str borné ≤280 chars (non-str → "") - **ne lève jamais** | - |
| `validate_agent_meta` / `validate_sources_block` | fiche d'agent (admin) | display-only **borné/sanitizé, ne lève jamais** : tagline ≤120, desc ≤700, capacités ≤8×120, outils ≤16×48, icône whitelistée, badge ∈ `{"",default,new,beta}` ; `sources` ≤8 `{label ≤60, dataset (regex nom DSS)}` | - |
| `_clean_source_query` | `q` (source + evidence) | non-str → "" ; caractères de contrôle → espace ; whitespace collapsé ; capé 200 chars - **ne lève jamais** (needle plié < 2 chars = pas de recherche) | - |

Codes d'erreur **non issus des validateurs** (levés directement par les routes / le manager) :
`unauthenticated` (401), `storage_not_configured` (409), `agent_not_enabled` (404), `rate_limited` (429),
`busy` (503), `storage_unavailable` (500), `agent_unavailable` (500), `invalid_run_id` (400),
`run_not_found` (404), `invalid_cursor` (400), `invalid_session_id` (400), `forbidden` (403),
`missing_user_id` (400), `cannot_remove_last_admin` (400), `discovery_unavailable` (500),
`project_not_found` (404), `too_many_agents` (400), `impersonation_read_only` (403, routes d'écriture pendant
une impersonation), `monthly_quota_exceeded` (402, gate budget), `exchange_not_found` (404) /
`empty_agent_answer` (400) (`/benchmark/suggest-from-chat`), `agent_has_no_benchmark` / `invalid_override`
(400, `/admin/benchmark/override`), `source_not_found` / `no_matching_dataset` (404) + `source_unavailable`
(500) (`/source/*`). Côté Evidence (`EvidenceError(code, status)`,
`evidence/service.py`) : `exchange_not_found` (404), `invalid_filter_column` / `invalid_sort_column`
(400, colonne absente du schéma live), `invalid_drill` (400, label drill hors de l'ensemble re-dérivé
serveur - miroir du code de validation), `query_failed` et tous les codes de dégradation du §3.5 (409),
`evidence_unavailable` (500, inattendu).

Limites in-route additionnelles : `_MAX_RUN_ID_LENGTH = 64` (`/chat/poll`), cursor ≤ 512 chars
(`/conversations`), `MAX_ENABLED_AGENTS = 50` (`/admin/agents`).

---

## 6. Conventions

- **SQL paramétré uniquement** : valeurs échappées via `sql_config.sql_value` / `nullable_value` ; identifiants
  via `pg_identifier` / `full_table` (constantes contrôlées). Aucune f-string autour de contenu utilisateur.
  Les builders `storage/sql_builders.py` n'interpolent que des fragments déjà échappés + des entiers bornés.
- **`COMMIT` après écriture** : tout CREATE/INSERT/UPDATE part en `pre_queries=[…]` + `post_queries=["COMMIT"]`.
- **Whitelist agents côté serveur** : le front envoie une clé logique opaque ; le backend résout
  `(project_key, agent_id)` (`settings.resolve_enabled_agent`). Détails → [security.md](./security.md).
- **Identité depuis les en-têtes** : jamais du corps. Scope owner systématique sur les lectures/écritures chat.
- **Pas de Flow ni de route SQL générique** au runtime ; le front ne choisit jamais table/connexion/requête.
- **Nommage tables** : `{PROJECT_KEY}_owismind_{logical}`, idiome `_vN` (jamais d'ALTER). Schéma & colonnes →
  [data-model.md](./data-model.md). Mono-process supposé (cohérent avec le modèle de polling).
