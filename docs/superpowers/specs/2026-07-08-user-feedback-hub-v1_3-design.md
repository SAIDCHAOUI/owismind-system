# Retours utilisateurs - Hub Help & Support (v1.3)

- Date: 2026-07-08
- Statut: valide (design approuve par l'user le 2026-07-08)
- Branche cible: `refactor/deep-clean-v1.2` (source unique `OWIsMind_PRD_V1_3_DEV/plugin/owismind/`)
- Livrable de test: plugin coexistant `owismind_v1_3` (la prod `owismind` reste intacte, non rebuild)

## Intention

Etendre le feedback (aujourd'hui limite au pouce par reponse d'agent) a deux points de
contact generaux, soumis directement depuis la WebApp au lieu de passer par mail:

- Feature A - **Feedback general**: suggestions UI/UX/produit, avec historique de mes retours
  et la reponse de l'admin visible dedans.
- Feature B - **Demande d'agent data**: l'utilisateur demande un nouvel agent avec des
  capacites sur des donnees; il choisit un de SES projets DSS puis les tables SQL de ce
  projet, decrit le business case, et soumet.

Les deux vivent dans UN hub "Help & Support" (route `/support`, atteint depuis le menu
Help > Support de la sidebar), a deux onglets. La demande d'agent a aussi un bouton
d'entree sur la page Agents.

## Contraintes non negociables (rappel)

- SQL direct only: prefixe `PROJECT_KEY`, requetes parametrees (`dataiku.sql.Constant/toSQL`),
  `COMMIT` apres ecriture, `statement_timeout`, owner-scope au read. Pas de Flow, pas de route
  SQL generique, le front ne choisit jamais table/connexion/requete.
- Identite resolue serveur (jamais du body), via `security/identity.py`.
- Ecritures bloquees pendant l'impersonation admin (consultation read-only), comme les autres
  routes WRITE.
- Surete instance: appels a la demande, bornes, jamais de scan de tous les projets.
- Code + commentaires en anglais; zero tiret cadratin/demi-cadratin partout.
- Charte Orange sur toute l'UI (carre, orange rare, tokens semantiques).
- NO INSTALL.

## Moules reutilises (source de verite a copier, ne pas reinventer)

- Storage: `python-lib/owismind/storage/suggestions.py` (patron exact: bounds par champ,
  `ensure_*_table`, ecriture parametree via `sql_value`/`nullable_value`, COMMIT, read
  owner-scope + read-only + statement_timeout, never-raises au read).
- Migrations: `python-lib/owismind/storage/migrations.py` (registry `_LOGICAL` + `_DDL_BY_LOGICAL`
  + `_INDEXES_BY_LOGICAL` + `ensure_*_table()`; `CREATE TABLE IF NOT EXISTS` idempotent).
- Enumeration DSS prouvee en DSS: `python-lib/owismind/agents/discovery.py`
  (`dataiku.api_client()`, `list_project_keys()`, `get_project(k)`), a etendre en variante
  scopee-utilisateur.
- Front form + "mes soumissions": `frontend/src/views/BenchmarkSuggestView.vue`.
- Front feedback inerte a rendre vivant: `frontend/src/views/FeedbackView.vue`.
- Service API + header impersonation: `frontend/src/services/backend.js`.
- Build plugin coexistant: `OWIsMind_PRD_V1_3_DEV/plugin/tools/build_dev_plugin.py` (id/nom/base d'assets/package renommes).

## Backend

### Tables (migrations.py)

`webapp_feedback_v1` (logique `FEEDBACK_V1_LOGICAL`):
- `feedback_id text PK`, `user_id text NOT NULL`, `category text`, `message text`,
  `linked_session_id text NULL`, `status text NOT NULL DEFAULT 'open'`,
  `admin_response text NULL`, `created_at timestamptz NOT NULL DEFAULT now()`,
  `responded_at timestamptz NULL`.
- Index `(user_id, created_at DESC)`.

`webapp_agent_requests_v1` (logique `AGENT_REQUESTS_V1_LOGICAL`):
- `request_id text PK`, `user_id text NOT NULL`, `project_key text`, `project_label text`,
  `datasets_json text` (JSON: `[{dataset, table, connection}]`), `business_case text`,
  `use_cases text`, `importance text`, `status text NOT NULL DEFAULT 'open'`,
  `admin_response text NULL`, `created_at timestamptz NOT NULL DEFAULT now()`,
  `responded_at timestamptz NULL`.
- Index `(user_id, created_at DESC)`.

Enregistrees dans `_DDL_BY_LOGICAL` + `_INDEXES_BY_LOGICAL`, avec `ensure_feedback_table()` /
`ensure_agent_requests_table()`.

### storage/feedback.py (calque suggestions.py)
- `save_feedback(user_id, category, message, *, linked_session_id=None) -> feedback_id`.
  Enums: `category` valide contre une liste fermee (`bug|wrong|feature|ux|perf|data|routing|other`),
  sinon `other`. Bounds: `message` cap (ex. 8000), `category`/`linked_session_id` capes.
  `status='open'` a l'ecriture. Parametre + COMMIT + statement_timeout.
- `list_my_feedback(user_id, limit) -> rows` (owner-scope, read-only, borne, never-raises).
  Colonnes retournees incluent `status`, `admin_response`, `responded_at`.

### storage/agent_requests.py (calque suggestions.py)
- `save_agent_request(user_id, project_key, project_label, datasets, business_case, use_cases,
  importance) -> request_id`. `datasets` = liste bornee (ex. max 25) d'objets
  `{dataset, table, connection}`, chaque champ cape, serialisee en JSON via le helper de
  serialisation. Champs texte capes. Parametre + COMMIT + statement_timeout.
- `list_my_agent_requests(user_id, limit) -> rows` (owner-scope, read-only, borne, never-raises;
  `datasets_json` re-parse en liste cote read).

### agents/user_catalog.py (NEUF - scoping utilisateur)
Mecanisme documente Dataiku (spike valide): `client.get_auth_info_from_browser_headers(headers)`
-> `authIdentifier`; `client.get_user(login).get_client_as()` -> DSSClient agissant EN TANT
QUE l'utilisateur; puis `list_project_keys()` / `get_project(k).list_datasets()`.

- `list_user_projects(headers) -> {"ok": True, "projects": [{key, label}]}` ou
  `{"ok": False, "reason": <code>}`. Borne (ex. MAX_PROJECTS=300). Never-raises.
- `list_user_sql_datasets(headers, project_key) -> {"ok": True, "datasets":
  [{dataset, table, connection, type}]}` ou `{"ok": False, "reason": <code>}`.
  Filtre aux datasets SQL: `type` dans une whitelist de types SQL DSS (PostgreSQL, MySQL,
  Snowflake, Redshift, BigQuery, Oracle, SQLServer, Greenplum, Teradata, Vertica, Synapse,
  ...) OU presence d'une `connection` + `table` SQL. Exclut explicitement les datasets non-SQL
  (S3, filesystem, etc.). Borne (ex. MAX_DATASETS=500). Never-raises.
- Surete instance: UN appel impersone par requete, a la demande (uniquement quand le formulaire
  est ouvert), resultats bornes. Prerequis DSS = permission "Impersonation in webapps" accordee
  au groupe run-as (action admin au deploiement, hors code). Absence de permission / toute
  erreur -> `{"ok": False}` -> repli saisie manuelle cote front (jamais le catalogue admin,
  jamais un scan de tous les projets).
- Note impersonation webapp: le catalogue resout l'utilisateur via les headers d'auth DSS
  (= le vrai user DSS de la session navigateur). Le formulaire de demande d'agent est un flux
  WRITE, donc bloque pendant l'impersonation admin `X-OWI-Impersonate` comme les autres WRITE.

### Routes (api/routes.py, blueprint `/owismind-api`)
- `GET  /catalog/projects` (READ) -> `list_user_projects(request.headers)`.
- `GET  /catalog/datasets?project_key=...` (READ) -> valide `project_key`, `list_user_sql_datasets`.
- `POST /feedback/submit` (WRITE, bloque en impersonation) -> `validate_feedback_submission` +
  `save_feedback`. Renvoie `{status:"ok", feedback_id}`.
- `GET  /feedback/mine` (READ, effective/owner-scope) -> `list_my_feedback`.
- `POST /agent-request/submit` (WRITE, bloque en impersonation) -> `validate_agent_request` +
  `save_agent_request`. Renvoie `{status:"ok", request_id}`.
- `GET  /agent-request/mine` (READ, effective/owner-scope) -> `list_my_agent_requests`.
Toutes suivent le patron existant (resolve identity, bloc impersonation fence pour les WRITE).

### security/validation.py
- `validate_feedback_submission(body)`: `message` requis non vide + cape; `category` optionnelle;
  `linked_session_id` optionnel. Leve `ValidationError` sur invalide.
- `validate_agent_request(body)`: `business_case` requis; `datasets` liste bornee d'objets bien
  formes OU (mode manuel) `project_key` + `datasets` texte; champs capes.

## Frontend

### Hub `/support` (repurpose FeedbackView.vue)
- `PageShell` + `Tabs.vue` (existe) a 2 onglets. Deep-link `?tab=feedback|agent`.
- Menu Help > Support de la sidebar pointe vers `/support`; route `/feedback` redirige vers
  `/support`. Ajout route `/support` dans `router/index.js` (retire le placeholder `support`).

### Onglet Feedback general
- Formulaire existant rendu vivant: `category` (select), conversation liee optionnelle,
  `message` (textarea). Submit -> `POST /feedback/submit`. Toast succes/erreur (ToastHost).
- Colonne/liste "mes retours": `GET /feedback/mine`, affiche categorie, extrait message, statut
  (pastille), et `admin_response` quand presente.

### Onglet Demander un agent
- Formulaire guide:
  1. Projet: dropdown depuis `GET /catalog/projects`. Si `{ok:false}` -> bascule saisie
     manuelle (input clef de projet).
  2. Tables SQL: multi-select depuis `GET /catalog/datasets`. Repli manuel: input noms de tables.
  3. Champs texte: business case (requis), cas d'usage, importance.
  4. Submit -> `POST /agent-request/submit`.
- Machine a etats du repli catalogue = logique pure testable (node:test, F11).
- Bouton "Demander un agent" sur `AgentsView.vue` -> `router.push('/support?tab=agent')`.
- Liste "mes demandes": `GET /agent-request/mine`, statut + `admin_response`.

### services/backend.js
- Nouvelles methodes: `getCatalogProjects()`, `getCatalogDatasets(projectKey)`,
  `submitFeedback(payload)`, `getMyFeedback()`, `submitAgentRequest(payload)`,
  `getMyAgentRequests()`. Via `getWebAppBackendUrl('/owismind-api/...')`, header impersonation
  reutilise le mecanisme existant.

### i18n (i18n/extra.js, F6)
- Cles plates fr+en pour les 2 onglets, categories, statuts, repli manuel, erreurs. Zero tiret
  cadratin.

### Style
- Charte Orange (carre, orange rare en accent, tokens de `styles/tokens.css`). Revue
  `charte-orange-reviewer` sur le diff UI.

## Versioning / build (v1.3 coexistant)

Generaliser `OWIsMind_PRD_V1_3_DEV/plugin/tools/build_dev_plugin.py` en schema versionne reutilisable:
- `--version 1.3` (ou equivalent) -> plugin id `owismind_v1_3`, label "OWIsMind v1.3",
  webapp `meta.label` "OWIsMind AI Agents v1.3", zip `owismind-v1_3-upload.zip`, base d'assets
  `/plugins/owismind_v1_3/resource/owismind-app/`, package python `owismind_v1_3`.
- Reutilise la reecriture deterministe existante (id / base / package), inchange par ailleurs
  (`APP_NAMESPACE`, prefixe HTTP `/owismind-api`, blueprint, outDir `owismind-app`).
- La prod `owismind` n'est ni rebuild ni touchee (memoire: dev-first-never-touch-prod-artifacts).

## Verification (gates avant "fait")

- Backend: `python3 -m unittest discover` (nouveaux tests storage feedback + agent_requests:
  save/list, bounds, enum; validation). Calques des tests suggestions existants.
- Frontend: node:test sur la machine a etats du repli catalogue; compile-check vite (F1)
  `./node_modules/.bin/vite build --outDir /tmp/owi_bc --emptyOutDir` puis `rm -rf`.
- Build v1.3: `OWIsMind_PRD_V1_3_DEV/plugin/tools/build_dev_plugin.py` version 1.3 -> zip stage sans frontend/node_modules.
- Revue Charte Orange (charte-orange-reviewer) + revue adversariale (adversarial-reviewer) du
  diff vs ces exigences.
- Preuve lue (sortie tests/build), jamais d'affirmation de succes sans preuve.

## Hors scope v1 (YAGNI)

- Ecran de reponse admin in-app (v1 = affichage seul; l'admin repond en editant la table cote
  DSS). A rediscuter si besoin.
- Notifications / mails a la soumission.
- Pagination des historiques (borne fixe suffit en v1).

## Orchestration

Fan-out sous-agents Sonnet sur pistes independantes, consigne d'escalade vers le pilote (Opus)
au moindre doute:
- WS1 backend storage+routes (feedback + agent_requests + migrations + validation).
- WS2 backend catalogue+impersonation (`agents/user_catalog.py` + routes catalogue).
- WS3 frontend hub + 2 onglets + service + i18n + bouton Agents.
- WS4 build tool v1.3.
Le pilote garde: conception, point catalogue/impersonation, integration, revue finale, build+tests.
