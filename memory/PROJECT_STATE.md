# PROJECT_STATE - OWIsMind (mémoire longue)

> Référence canonique de l'état du projet. Mise à jour à la demande / en fin de session.
> En cas de conflit avec les guides de `docs/cadrage/` : **ce fichier + `LESSONS.md` font foi** (les guides
> sont des points de départ ; les noms réels et les solutions qui marchent vivent ici).
> Dernière mise à jour : **2026-06-14 - SKILL AGENTIQUE** : skill projet `.claude/skills/agentique-python-dataiku/`
> (`SKILL.md` + **15 références**, ~70k mots) créé/réconcilié (corpus recherche multi-agents + source ChatGPT) /
> validé local (6/6 scénarios, 0 piège) - **référence d'ingénierie, pas du code déployé** (claims DSS-réels marqués
> `UNVERIFIED`). Corpus `docs/agentic-research/` **gitignoré** (provenance, hors git). **Python : DEUX code envs
> 3.9 ET 3.11** (user, autorité, L054) ; backend webapp = 3.9.23 → jamais d'import langchain en 3.9 ; LangChain/
> LangGraph v1 (≥ 3.10) seulement en code env 3.11. Détail `sessions/2026-06-14.md`, leçons **L053-L054**.
> Antérieur : **2026-06-11 - NETTOYAGE REPO** : `maquette/` (~12 k lignes), `docs/superpowers/plans/`
> et `.demo-screens/` **supprimés** (conversion Vue 3 terminée - voir §9) ; specs gelées conservées
> (`docs/superpowers/specs/`). Trust layer Evidence v2 déployé 🟡 (fonctionne, ajustements user à recueillir - §11).
> **GIT** : repo initialisé (main, commit initial `3bd804f`) ; commit de session via `/log-session` ; **jamais de push**.
> **KNOWLEDGE GRAPH** : `graphify-out/` (git-ignoré, ~2 500 nœuds) - l'interroger D'ABORD pour naviguer ;
> fraîcheur = hook git post-commit + `/log-session` (--update) ; exclusions corpus = `.graphifyignore` versionné (L046).
> Antérieur : **2026-06-10 - EVIDENCE STUDIO v1 ✅ VALIDÉ EN DSS** (user : « ça marche très bien »).
> Panneau « confiance » (3ᵉ colonne) qui **rejoue le SELECT de l'agent en lecture seule** et montre la table
> source avec les filtres WHERE en **chips éditables** ; auto-open en fin de génération, bouton « Preuves » par
> message ; **zéro changement de schéma** (re-dérivé du `generated_sql` stocké). **PAS de whitelist admin** :
> le backend **découvre auto** les datasets SQL du projet (`list_datasets()` filtré PostgreSQL) et matche la
> table de l'agent (pivot DSS - le param `evidence_datasets`/MULTISELECT ne se rendait pas + décision user).
> Package backend neuf `evidence/` (parseur pur + service + token-bucket) + 3 routes `/evidence/{meta,rows,distinct}` ;
> front store+composants. Audit adversarial : **0 injection/authz/XSS**, 5 durcissements instance/perf.
> Détail `sessions/2026-06-10.md`, **leçons L035/L036/L037**. ✅ DSS + 121 unittest · 36 node:test · vite OK · zip 71 entrées.
> ----
> Antérieur **2026-06-09 (✅ TOUT VALIDÉ EN DSS)** : (1) historique multi-tours → agent + sidebar lazy (L030) ;
> (2) feedback par message + SQL dans le contexte + switch sans flash (L031) ; (3) arbre de conversation +
> agent persistant (L032) ; (4) stop-génération (L034). **Stockage chat = `webapp_chat_v4`** (v1/v2/v3 inertes).

---

## 1. Vision produit (1 ligne)
Portail agentique métier OWI : une WebApp de chat avec des agents IA Dataiku, avec **timeline live**
d'exécution et **Evidence Studio** (preuves : dataset / SQL / chart / trace / coût) - packagée en
**plugin Dataiku DSS**.

## 2. Architecture (1 ligne)
Frontend **Vue 3 + Vite** buildé en assets statiques servis par DSS + backend **Flask DSS** (modulaire
dans `python-lib/`) qui parle aux agents via **LLM Mesh** et stocke conversations/messages/runs/events
en **SQL direct** (`SQLExecutor2`, PostgreSQL), **sans Flow** au runtime.

---

## 2b. Parcours (slices livrées, du début à aujourd'hui) - pour reprendre le fil
> Détail par session dans `memory/sessions/` ; leçons dans `LESSONS.md`. Tout ci-dessous est **validé EN DSS**.

1. **2026-06-01 - Setup & socle** : scaffold Vue 3 + Vite, build → `resource/owismind-app/`, **zip runtime
   propre** (sans frontend/node_modules) ; backend Flask **modulaire** (`/owismind-api`, `register_routes`) ;
   `default_project_key()` résout `OWISMIND_DEV` depuis le backend (L007) ; convention de nommage
   `{PROJECT_KEY}_owismind_{logical}` figée (L008). _(slices `setup` + `chat-probe`.)_
2. **2026-06-02 - Chat persistant + storage + admin** : `chat_v1` bout-en-bout (`/me`, `/chat` **MOCK**,
   `/history`), **persistance au reload** ; **storage configurable** par webapp (params + dropdown connexion) ;
   **espace admin** (`webapp_users_v1`, 1er user = admin) ; identité réelle `get_auth_info_from_browser_headers`
   (L011) ; **audit sûreté** (L011-L015).
3. **2026-06-03 - Consolidation** : code mort retiré (probe `/dev/chat-probe/*` = route d'écriture non
   authentifiée), helpers factorisés (`serialization.py`) ; **dropdown connexion confirmé fonctionnel**
   (L016 → **L012 obsolète**).
4. **2026-06-03 - Mécanismes critiques** : **display_name auto-rempli** (prénom dérivé du
   login, backfill no-clobber) + **agents whitelist DYNAMIQUE** (table `webapp_settings_v1`, découverte DSS
   lecture seule, routes admin/user, clés logiques opaques) ; **review multi-agents** ; **✅ validé EN DSS** (L017).
5. **2026-06-04 (run 1) - Vrai agent + streaming SSE** : `/chat` MOCK **supprimé** → `/chat/stream` (SSE) ;
   `agents/streaming.py` (`run_agent_streamed`) ; **nouvelle table `webapp_chat_v2`** (col `generated_sql`) ;
   `resolve_enabled_agent` (whitelist côté chat) ; sélecteur agent + timeline + panneau SQL. **SSE bufferisé en
   DSS** (tout d'un bloc) → abandonné au run 2 (L018→L019).
6. **2026-06-04 (run 2) - Streaming live via POLLING-via-thread (✅ VALIDÉ DSS)** : SSE **supprimé** → `/chat/start`
   + `/chat/poll` ; `agents/stream_manager.py` (worker daemon + dict mémoire + cap/TTL/scope user) - **pattern du
   Dash de prod** (`old_webapp_in_dash/`, qui contourne le buffering par design). Front : boucle de poll 500 ms.
   2 fixes front : `reactive()` + `.msg{flex-shrink:0}`. **Validé EN DSS** : timeline live, SQL, multi-agents (L019/L020).
7. **2026-06-04 (run 3) - Brique TRACE (footer BRUT) (✅ VALIDÉ DSS)** : on stocke le **`footer.trace` BRUT** de fin de
   stream (**≠ eventKind**, qui restent UI live éphémère non stockés). Nouveau `storage/chat_traces.py`
   (`save_trace` UPSERT + cap 4 Mo ; `fetch_trace` JOIN `chat_v2.user_id` → scope owner) ; table **`webapp_chat_traces_v1`**
   (col `trace` JSON) ; `streaming.py` émet l'event storage-only `trace` ; worker le capture **sans l'empiler** (jamais
   live) + persiste phase 2 ; route **lazy** `GET /chat/trace`. Aligné **Dash de prod**. Front intact (pas de rebuild). (L021)

8. **2026-06-05 - Conversion frontend Vue 3 (Phases 0-2, ✅ validées en LOCAL)** : on **habille** le socle backend validé avec
   l'UI de la maquette, sur une **archi modulaire à registres**. **Phase 0** (tokens no-op + primitives UI mutualisées),
   **Phase 1** (shell + vue-router hash + Pinia `ui`/`session` + vue-i18n 327 clés), **Phase 2** (chat : transport polling porté,
   store `chat`, markdown sanitizé, timeline registre, composants chat). Validé **dev server + screenshots + build prod temporaire**
   (light/dark, FR/EN). **⚠️ PAS encore buildé dans `resource/` ni testé EN DSS.** Détail complet → **§13**. (L022)

9. **2026-06-05 Run 2 - Frontend Vue 3 COMPLET + audit pré-DSS (✅ VALIDÉ DSS)** : Phase 3 (pages secondaires, fondations
   `components/pages/`, registres `agentMeta`/`faqContent`), Phase 4 (Admin à onglets réutilisant `AdminPanel`, supprimé ensuite),
   Phase 5 (build 197 modules + `body.html` via Write + zip), **testé EN DSS = OK**. Audit sécurité (workflow 6 dim.) **GO** + 4
   correctifs backend. (L024/L025/L026)

10. **2026-06-09 - 4 lots VALIDÉS EN DSS (L030/L031/L032)** : (a) **historique multi-tours → agent** (contexte assemblé backend
    = chaîne d'ancêtres, nom+date) + **sidebar lazy** (`/conversations` paginé + `/conversation` au clic ; plus de fetch unique) ;
    (b) **feedback par message** (colonnes dans la table chat ; `/chat/feedback` owner-scopé ; 👎 popup, 👍 ⋯) + **`generated_sql`
    dans le contexte** + **switch de conv sans flash** ; (c) **arbre de conversation** (éditer un prompt → branche via
    `parent_exchange_id` ; versions turn-level persistées ; contexte tronqué à la branche) + **agent persistant par conversation** ;
    (d) **fix** scroll-vs-navigation. Stockage chat passé **v2→v3→v4** (idiome `_vN`, anciennes inertes). Détail `sessions/2026-06-09.md`.

11. **2026-06-10 - Evidence Studio v1 (✅ VALIDÉ EN DSS)** : panneau « confiance » qui rejoue le SELECT de l'agent
    **en lecture seule** ; table + filtres WHERE en **chips éditables** ; auto-open fin de génération + bouton « Preuves »
    par message ; **zéro changement de schéma** (re-dérivé du `generated_sql` stocké). **PAS de whitelist** - découverte
    auto des datasets SQL du projet, match de la table de l'agent (pivot DSS L037 : MULTISELECT ne se rend pas + décision
    user). Package `evidence/` (`sql_parse`/`query_builders`/`whitelist`/`service`/`throttle`) + 3 routes
    `/evidence/{meta,rows,distinct}` + front (store/composants). Audit adversarial → 0 injection/authz/XSS, 5 durcissements
    instance/perf (L036). Détail `sessions/2026-06-10.md`, **L035/L036/L037**.

**👉 Où on en est** : **TOUT le backend + le frontend V1 + les lots du 2026-06-09 + Evidence Studio v1 sont VALIDÉS EN DSS**
(chat multi-tours avec historique/contexte, sidebar lazy, feedback par message, édition/branches, agent persistant,
stop-génération, **Evidence Studio** = preuves SQL en table interactive). **Stockage chat = `webapp_chat_v4`**.
`maquette/` a été **supprimée du repo** (2026-06-11, conversion terminée - §9). Détail frontend → **§13** ; prochaines étapes → §12.

---

## 3. Identifiants canoniques (CONFIRMÉS sur disque / dans les guides)

| Élément | Valeur réelle | Source |
|---|---|---|
| Plugin id | `owismind` | `Plugin/owismind/plugin.json` |
| WebApp component | `webapp-owismind-ai-agents` | `Plugin/owismind/webapps/` |
| Package python-lib | `owismind` | `Plugin/owismind/python-lib/owismind/` |
| Dossier resource (assets buildés) | `owismind-app` | `vite.config.js`, `body.html` |
| Vite `base` | `/plugins/owismind/resource/owismind-app/` | `vite.config.js` |
| Vite `outDir` | `../resource/owismind-app` (+ `emptyOutDir: true`) | `vite.config.js` |
| Racine plugin (sur disque) | `Plugin/owismind/` (P majuscule) | repo |
| Frontend source | `Plugin/owismind/frontend/` | repo |
| Staging packaging | `Plugin/ready-for-dataiku/owismind-upload/` + `owismind-upload.zip` | repo |
| Plugin DEV (coexistant, L094 ✅ DSS) | id `owismind_dev`, zip `Plugin/ready-for-dataiku/owismind_dev-upload.zip` (label "OWIsMind (DEV)", webapp "OWIsMind - AI Agents (DEV)") - généré par `tools/build_dev_plugin.py` / skill `/package-plugin-dev` | repo |
| Source de build DEV | UNE source `Plugin/owismind/` ; base Vite via env `OWI_PLUGIN_ID` (défaut `owismind`) ; package python renommé `owismind`->`owismind_dev` au packaging (L094) ; tables = create-if-not-exist, isolation = `table_prefix` optionnel au déploiement | repo |
| Connexion SQL | `SQL_owi` (PostgreSQL, schéma `public`) | guide SQL |
| Project key DSS | `OWISMIND_DEV` (résolu via `dataiku.default_project_key()`, **reste la référence du repo**) ; variante test `OWISMIND_LAB` ; **projet PROD parallèle `OWISMIND_PROD_V1`** (table physique `OWISMIND_PROD_V1_drive_revenues` ; agent `agent:uO5hEzAs`, `LOOKUP_TOOL_ID=szOZCoU` ; migration via `tools/semantic_model/migrate_semantic_model_to_project.py` qui dérive le remapping des clés - sinon Evidence dégradé, L090) | guide SQL ; 2026-06-18 |
| Agent « revenue » v1 (visual) | `agent:rNTZ781a` (Structured Visual Agent - revenus) - conservé en filet, **désactivé du registre depuis v2.4 (v2 actif)** | guide SQL / code_samples |
| Agent « revenue » v2 (Code Agent, L047/L048 ✅ DSS 2026-06-11) | `agent:MODpGFcC` ← `salesdrive/salesdrive_agent.py` (repo = source de vérité, + README + 55 tests stub) ; tools : resolver `aNxeOc4` (`Drive_Revenues_resolve_filter_value`), semantic `v4oqA6R` (`revenue_semantic_query`) ; catalogue `DRIVE_Revenues_Value_Catalog` | repo / `sessions/2026-06-11.md` Run 3 |
| Blueprint API | préfixe URL `/owismind-api` | guide build |
| Route santé | `/owismind-api/ping` | guide build |
| Routes Evidence Studio (L035/L042) | `/owismind-api/evidence/{meta,rows,distinct}` (owner-scopées, read-only ; `distinct` accepte `exclude_id` = chip en cours d'édition) | `api/routes.py` |
| ~~Route « vue agent »~~ (SUPPRIMÉE Run 4 2026-06-10) | `/evidence/agent-view` + `is_replayable_select` + `build_agent_view_query` + indicateur « agent saw N rows » retirés partout (front, backend, i18n, tests) | `sessions/2026-06-10.md` Run 4 |
| Source datasets Evidence (L037) | **découverte auto** des datasets SQL du projet (`list_datasets()` filtré PostgreSQL) - **PAS de param admin** (whitelist abandonnée ; MULTISELECT ne se rend pas dans Settings) | `evidence/service.py` `_list_project_sql_datasets` |
| Package Evidence backend (L035/L045) | `python-lib/owismind/evidence/` (`sql_parse`,`query_builders`,`whitelist`,`service`,`throttle`,**`sql_explain`**,**`capture`**) | repo |
| Orchestrateur Code Agent (repo, L045/L047/L048/**L050**) | `orchestrator/orchestrator_agent.py` **v2.4** (+ `AUDIT.md`, 86 tests stub) - à coller dans le Code Agent DSS. **v2.4 « Expert Authority » (L050, ⏳ non validé DSS)** : jamais de fait métier par l'orchestrateur (router-pas-nier ; seul « non » = « pas d'agent pour ce domaine ») ; `CAPABILITY_GAP`/`OUT_OF_SCOPE` déterministes + intent `CONCEPT` ; registre = manifeste + `BUSINESS_DOMAINS` ; manifeste revenus pleine-vérité + `test_manifest_antidrift.py` (vs `salesdrive_agent.KNOWN_PHASES`) ; **registre basculé sur v2 `agent:MODpGFcC`**. v2.3 : entrée registre `salesdrive_v2` (`pass_context`), capture `AGENT_RESULT` (statut machine des sous-agents code, jamais affiché, exposé dans `AGENT_DONE.agentResult`), skip Sources sur clarification/hors-périmètre, `build_subagent_context` (continuité conversationnelle) | repo |
| Spec trust layer (gelée) | `docs/superpowers/specs/2026-06-10-evidence-trust-layer-design.md` · doc `docs/evidence-trust-layer.md` | repo |
| Repo git (2026-06-11) | branche `main`, commit initial `3bd804f` ; pas de remote (push = user) ; commit de session via `/log-session` | repo |
| Knowledge graph (L046) | `graphify-out/` (git-ignoré) · exclusions `.graphifyignore` (versionné) · hooks git post-commit/post-checkout (AST auto) · `/log-session` = `--update` + commit | repo |
| Plateforme | Dataiku DSS 14.4.x | guide build |
| Python backend observé | **3.9.23** (3.11 NON validé) | guide build |

> ⚠️ Les guides de `docs/cadrage/` emploient des **exemples** (`owismind-vue`, `owismindvue`,
> `webapp-owismind-vue`) qui **ne sont pas** les vrais noms. Toujours utiliser le tableau ci-dessus.

---

## 4. Structure réelle du plugin (`Plugin/owismind/`) - à jour 2026-06-01 (slice chat-probe + cleanup)

```
Plugin/owismind/
├── plugin.json                 # id="owismind" v0.0.1 (racine - PAS de _/plugin.json)
├── frontend/                   # source Vue 3 + Vite (JAMAIS dans le zip)
│   ├── src/
│   │   ├── App.vue             # page chat minimale (input + Envoyer + thread)
│   │   ├── main.js             # createApp(App).mount('#app')
│   │   ├── style.css           # reset minimal (body{margin:0} REQUIS pour height:100vh)
│   │   └── services/backend.js # client backend via getWebAppBackendUrl (pingBackend/sendChat/fetchRecent)
│   ├── public/favicon.svg
│   ├── index.html (title OWIsMind, lang fr), package.json, vite.config.js, CLAUDE.md, .gitignore
│   └── node_modules/           # JAMAIS dans le zip ; SEUL l'utilisateur installe
├── python-lib/owismind/        # backend modulaire (mis sur le path d'import par DSS)
│   ├── __init__.py
│   ├── api/routes.py           # Blueprint /owismind-api : ping · dev/chat-probe/{send,recent} · register_routes(app)
│   ├── storage/sql_config.py   # connexion · project_key (cascade) · namespace owismind_ · sql_value/pg_identifier · new_executor
│   ├── storage/migrations.py   # ensure_chat_probe_table() (gardé, CREATE IF NOT EXISTS, COMMIT)
│   ├── storage/repositories.py # insert_exchange (1 aller-retour) · recent_exchanges · rows_to_json_safe
│   └── security/validation.py  # validate_message (vide/long → 400)
├── resource/owismind-app/      # ASSETS BUILDÉS par Vite (généré - NE PAS éditer)
│   ├── index.html, favicon.svg
│   └── assets/index-<hash>.js, index-<hash>.css     # (plus de icons.svg depuis le cleanup)
└── webapps/webapp-owismind-ai-agents/
    ├── webapp.json             # baseType=STANDARD, hasBackend=true, libs [jquery,dataiku], params []
    ├── backend.py              # bootstrap : from owismind.api.routes import register_routes; register_routes(app)
    ├── body.html               # entrée DSS = copie du index.html buildé (assets câblés)
    ├── app.js                  # commentaire (slot JS STANDARD - vidé, JAMAIS supprimé)
    └── style.css               # commentaire (slot CSS STANDARD - vidé, JAMAIS supprimé)
```

Staging d'upload (généré par `/package-plugin`) :
```
Plugin/ready-for-dataiku/owismind-upload/   (+ owismind-upload.zip)
├── plugin.json                 # à la RACINE du zip (copie de Plugin/owismind/plugin.json)
├── python-lib/  resource/  webapps/   # runtime uniquement - pas de frontend/ ni node_modules/
```

### 4.1 Retiré au cleanup - NE PAS réintroduire (archi morte du scaffold)
> Ces éléments venaient du scaffold Vite/DSS ou de samples, **pas** de notre archi (SQL direct + agents LLM
> Mesh + chat Vue). Y revenir = repartir sur des choses qui ne correspondent pas / ne marchent pas.

| Retiré | C'était quoi | Pourquoi ne pas y revenir |
|---|---|---|
| `backend.py` template DSS (`/first_api_call`, `dataiku.Dataset("REPLACE_WITH_YOUR_DATASET_NAME")`) | lecture d'un dataset via webapp config param | Notre modèle = **SQL direct** (`SQLExecutor2`), pas de dataset/Flow au runtime ; le front ne choisit pas de dataset |
| `components/HelloWorld.vue` + `assets/{hero.png,vue.svg,vite.svg}` + `public/icons.svg` | démo Vite/Vue | zéro rapport métier ; orphelins purs |
| `frontend/src/style.css` scaffold (`.hero`/`#next-steps`/`#social`/`.ticks`/`.counter`, var `--accent` **violet**, `#app{width:1126px}`) | CSS de la démo | branding = **Orange `#ff7900`** (pas violet) ; chat en styles **scoped** dans App.vue |
| `webapps/.../style.css` : `.fetch-dataset-*`, `#message`, `@import /static/public/styles/1.0.0/variables.css` | sample jQuery + vars CSS DSS | on n'utilise **pas** les vars CSS DSS (couleurs scoped en dur) ; slot vidé |
| `webapp.json params` (`input_dataset`/`input_column`/`input_int` mandatory) | params scaffold | bloquaient le démarrage ; le front ne choisit jamais table/connexion ; `project_key` résolu **serveur** → `params: []` |
| Backend insert en **2 appels** (`insert_exchange` + `get_exchange`) | INSERT+COMMIT puis SELECT séparé | remplacé par **1 aller-retour** (pre=INSERT, main=SELECT, post=COMMIT) - voir L009 ; `get_exchange` supprimé |
| `CLAUDE.md` / `README.md` dans le zip runtime | docs dev empaquetées par erreur | pollution du livrable ; exclus par `/package-plugin` (L010) |

> Slots STANDARD `app.js` / `style.css` : **vidés (commentaire), jamais supprimés** - DSS les exige (L010).

---

## 5. Chaîne build → package (mécanique validée par les guides)

1. **Build** (depuis `frontend/`) : `npm run build` → sort dans `../resource/owismind-app/` (assets hashés).
   - Pré-requis : `node_modules/` doit exister. **L'agent n'installe PAS** ; sinon demander à l'utilisateur.
2. **Câblage DSS** : `cp resource/owismind-app/index.html webapps/webapp-owismind-ai-agents/body.html`,
   puis vérifier que `body.html` contient `/plugins/owismind/resource/owismind-app/`.
3. **Package** : stager `plugin.json` (racine) + `python-lib/` + `resource/` + `webapps/` dans
   `ready-for-dataiku/owismind-upload/`, zipper, vérifier **absence** de `frontend/` & `node_modules/`.
4. Matrice rebuild : frontend changé → rebuild + recopier body.html + repackager. Backend Python changé →
   repackager + **redémarrer le backend** dans DSS. `app.js`/`style.css` seuls → repackager + refresh.

> Commandes opérationnelles : voir skills `/build-plugin` et `/package-plugin`.

---

## 6. Backend Flask modulaire (✅ EN PLACE - slice chat-probe)

> `backend.py` = bootstrap minimal (`from owismind.api.routes import register_routes; register_routes(app)`).
> Modules : `api/routes.py` (Blueprint `/owismind-api` : `ping`, `dev/chat-probe/send`, `dev/chat-probe/recent`),
> `storage/{sql_config,migrations,repositories}.py`, `security/validation.py`. `/dev/*` = probes temporaires.

- `python-lib/owismind/api/routes.py` : `Blueprint("owismind_api", url_prefix="/owismind-api")` +
  `register_routes(app)`.
- `webapps/webapp-owismind-ai-agents/backend.py` : bootstrap minimal → `from owismind.api.routes import
  register_routes; register_routes(app)`.
- Frontend appelle via `getWebAppBackendUrl('/owismind-api/...')` (nécessite `"dataiku"` dans
  `standardWebAppLibraries`). Ne jamais coder l'URL en dur.
- **Routes RÉELLES (2026-06-04)** :
  - `ping` (santé + `storage_status()`).
  - `me` (POST = identité + `is_admin` + `needs_config` + upsert/bootstrap admin ; GET read-only).
  - **`chat/start`** (POST `{session_id, message, agent_key, history_limit, parent_exchange_id}` → save user (BRUT) +
    lance worker → `{run_id, exchange_id}` ; 429/503 si cap) + **`chat/poll`** (GET `?run_id=&cursor=` →
    `{events,cursor,done,error}` ; owner-scopé) - **POLLING-via-thread, ✅ validé DSS** ; écriture 2 temps dans `chat_v4`.
    Le worker assemble le **contexte multi-tours = chaîne d'ancêtres** de `parent_exchange_id` (`history_messages_for_chain`)
    + préfixe **nom+date** sur le tour courant (L030/L032). `history_limit` = nb messages, clamp `[10,50]`.
  - **`chat/stop`** (POST `{run_id}` → `stream_manager.request_stop`, **owner-scopé** ; pose `stop_requested` →
    worker `break` (LLM Mesh **sans API cancel** → cesser d'itérer) + persiste le partiel + event terminal `stopped` ≠ error) - L034, ✅ DSS.
  - **`chat/feedback`** (POST `{exchange_id, rating(0|1|null), reasons[], comment}` → `chat_v4.save_feedback`,
    **owner-scopé** ; `validate_feedback` whiteliste les raisons, borne le commentaire, rejette `True/False`) - L031.
  - **`conversations`** (GET `?cursor=&limit=` → `{conversations:[{session_id,title,last_at}], next_cursor, has_more}` -
    **noms seuls**, pagination **keyset** ; `build_conversation_list_query`) + **`conversation`** (GET `?session_id=` →
    `{rows:[…échanges incl. parent_exchange_id + feedback]}`, chronologique, borné, chargé **au clic**) - L030/L032.
  - `history` (GET, filtré `user_id`, LIMIT 200, lit `chat_v4` ; **legacy - plus appelé par le front** depuis la sidebar lazy).
    **`chat/trace`** (GET) **supprimé** (trace = dataset Flow write-only, L027/L028). _(`/chat` MOCK + `/chat/stream` SSE supprimés.)_
  - `agents` (GET, **user** - `{key,label}` only, clés logiques opaques ; jamais d'`agent_id`).
  - `admin/storage`, `admin/users`, `admin/users/set-admin`, `admin/projects`, `admin/projects/<key>/agents`,
    `admin/agents` (GET+POST) - **gardées serveur** par `_admin_guard`.
- Modules backend : `security/{identity,validation}.py` (validators : `validate_history_limit`/`validate_feedback`/
  `validate_optional_exchange_id`/`validate_conversations_limit` ; `derive_full_name`), `storage/{chat_v4,chat_traces,admin,settings,
  migrations,sql_config,serialization,sql_builders,pagination}.py` (**purs sans dataiku** : `sql_builders` = `build_ancestor_chain_query`/
  `build_conversation_list_query`/`build_session_messages_query` ; `pagination` = cursor encode/decode),
  **`agents/{discovery,streaming,stream_manager,context}.py`** (`context` = pur : prefix/flatten/SQL-contexte ; `streaming.run_agent_streamed(…, messages)` multi-tours),
  `resource/compute_available_connections.py` (dropdowns connexion + dataset traces).
  ⚠️ `chat_v1/v2/v3.py` **supprimés au fil des bascules** (table COURANTE = `chat_v4.py`) ; `run_events.py`/`history_messages_for_session`/`build_session_history_query` supprimés (code mort).
- Frontend : `App.vue` (onglets Chat/Admin + **sélecteur d'agent** + timeline live + panneau SQL ; `assistant` en
  `reactive()`, boucle de poll 500 ms), `components/AdminPanel.vue` (storage + users + carte « Agents disponibles »),
  `services/backend.js` (**`startChat`+`pollChat`** (polling) + routes + admin + agents).

## 7. Stockage SQL direct (✅ VALIDÉ depuis le backend WebApp - 2026-06-01)

- `SQLExecutor2(connection="SQL_owi")` via factory `new_executor()` (instance FRAÎCHE par appel,
  thread-safety) ; lecture `query_to_df(SELECT...)` ; écriture `pre_queries=[INSERT/CREATE]` +
  `post_queries=["COMMIT"]` (**COMMIT obligatoire**). Pattern **un seul aller-retour** validé :
  `pre=[INSERT]`, requête principale = `SELECT` de relecture par id, `post=[COMMIT]` → la SELECT voit
  sa propre écriture (même transaction) et renvoie la ligne (voir L009).
- **Convention de nommage NON NÉGOCIABLE** : toute table de la WebApp = `{PROJECT_KEY}_owismind_{logical}`
  (namespace `owismind_` TOUJOURS après le project key), cité `public."OWISMIND_DEV_owismind_..."`.
  Centralisée dans `python-lib/owismind/storage/sql_config.py` (`APP_NAMESPACE="owismind"`,
  `physical_table()`, `full_table()`). Voir L008. ⚠️ prime sur l'exemple `{PROJECT_KEY}_{logical}` des guides.
- Paramétrage : `from dataiku.sql import Constant, toSQL, Dialects` (POSTGRES) - **jamais** de f-string
  brute avec input utilisateur ; identifiants via `pg_identifier` (regex + double-quotes).
- Table probe **constatée en base** : `public."OWISMIND_DEV_owismind_webapp_chat_probe"`
  (`id` VARCHAR(64), `created_at` TIMESTAMPTZ, `user_text`, `assistant_text`) - **ABANDONNÉE**, gardée intacte.
- **Table chat COURANTE = `webapp_chat_v5`** (⏳ Run 4 2026-06-11, NON validée DSS - L049 ; module `storage/chat_v5.py`,
  ex-`chat_v4.py` `git mv`) :
  - Colonnes : `exchange_id` PK, `session_id`, `user_id`, `user_display_name`, `user_groups`, `user_text`,
    `assistant_text`, **`generated_sql`** (JSON liste `{sql,success,row_count}`, nullable - L019/v2),
    `agent_key` (**clé logique opaque**), `created_at`, `answered_at`, **`feedback_rating` SMALLINT (0|1|NULL)** +
    **`feedback_reasons` TEXT(JSON)** + **`feedback_comment` TEXT** + **`feedback_at` TIMESTAMP** (L031/v3),
    **`parent_exchange_id` TEXT** (arbre de conversation - L032/v4), **`input_tokens`/`output_tokens`/`total_tokens` INT +
    `estimated_cost` DOUBLE** (usage de l'échange, nullables - L049/v5, écrites dans le MÊME UPDATE que la réponse =
    **source de vérité** des agrégats). Index `(user_id, created_at DESC)` + `(user_id, session_id, created_at DESC)`.
  - Écriture **2 temps** (INSERT user → UPDATE assistant+SQL), COMMIT. **Feedback** : `save_feedback` =
    `UPDATE … WHERE exchange_id AND user_id` (owner-scopé). **Branches** : `parent_exchange_id` (NULL = racine) ;
    éditer/régénérer = nouvel échange **frère** ; contexte agent = **chaîne d'ancêtres** (`build_ancestor_chain_query`
    CTE récursive user-scopée + bornée). Le **message stocké reste BRUT** (préfixe nom/date + historique = build-time only).
  - **Historique des tables chat (toutes inertes, jamais droppées, idiome `_vN` jamais d'ALTER)** : v1 (chat_v1, 2026-06-02)
    → v2 (+`generated_sql`, L019) → v3 (+colonnes feedback, L031) → **v4 (+`parent_exchange_id`, L032 = COURANTE)**.
    ⚠️ À chaque bascule, la nouvelle table démarre **vide** (données de test des versions précédentes perdues, assumé par l'user).
  - ~~`OWISMIND_DEV_owismind_webapp_chat_traces_v1`~~ (table SQL de trace, L021) - **SUPERSÉDÉE (L027/L028)** : les traces ne
    vont **plus** dans une table SQL. Elles sont **appendées sur un dataset Flow** sélectionné par l'admin :
    `chat_traces.save_trace` → `dataiku.Dataset(traces_dataset, ignore_flow=True).write_with_schema(df)` avec
    `spec_item["appendMode"]=True`, **write-only** (`fetch_trace` + route `/chat/trace` **supprimés**), 1 ligne
    `{exchange_id, trace, created_at}`, cap 4 Mo, best-effort **auto-protégé**. ⚠️ `write_with_schema` est **POSITIONNEL** →
    `_column_order(dataset)` lit `read_schema()` et écrit dans l'ordre du dataset (l'ordre des colonnes côté admin est libre).
    Param `traces_dataset` = **SELECT** peuplé par `compute_available_connections.py` (datasets SQL filtrés + « (none) »).
    **✅ validé DSS 2026-06-08** (user : traces enregistrées). Les anciennes tables `_traces_v1`/`_run_events_v1` restent **inertes**.
- **Tables 2026-06-02 (✅ validées en DSS)** :
  - `OWISMIND_DEV_owismind_webapp_chat_v1` (logique `webapp_chat_v1`) : `exchange_id` PK, …, `assistant_text`,
    `agent_key`, `created_at`, `answered_at`. **ABANDONNÉE** au profit de `chat_v2` (intacte, jamais droppée).
  - `OWISMIND_DEV_owismind_webapp_users_v1` (logique `webapp_users_v1`) : `user_id` PK, `display_name`,
    `user_groups`, `is_admin` BOOL, `first_seen`, `last_seen`. **1er user = admin** (bootstrap guardé).
    `display_name` désormais **auto-rempli** = prénom dérivé du login (L017), backfill NULL via COALESCE.
    **+ Run 4 (L049, ⏳ NON validé DSS) : `total_input_tokens`/`total_output_tokens` BIGINT + `total_cost` DOUBLE +
    `last_usage_at`** - cumul lifetime, **seul ALTER autorisé** (`ADD COLUMN IF NOT EXISTS` dans le DDL ET
    `_ALTERS_BY_LOGICAL`, appliqué par `_ensure_table` sans perdre les rows), incrémenté par `storage/usage.record_usage`.
  - **`OWISMIND_DEV_owismind_webapp_usage_monthly_v1`** (logique `webapp_usage_monthly_v1`, ⏳ Run 4 NON validé DSS -
    L049) : PK **`(user_id, period_start DATE)`**, `input_tokens`/`output_tokens` BIGINT, `total_cost` DOUBLE,
    `request_count` INT, `updated_at`. `period_start = date_trunc('month', now())::date` ; UPSERT **incrémente**
    (`+ EXCLUDED`, `request_count + 1`). Quota mensuel futur = **1 lecture par clé**, pas de job de reset.
    `record_usage` fait users + monthly en **UNE transaction**, best-effort (agrégats reconstructibles depuis `chat_v5`).
- **Table 2026-06-03 (✅ validée EN DSS)** :
  - `OWISMIND_DEV_owismind_webapp_settings_v1` (logique `webapp_settings_v1`) : `setting_key` PK,
    `setting_value` (JSON), `updated_at`, `updated_by`. **Config globale webapp** (clé `enabled_agents` =
    whitelist `[{logical_key,project_key,agent_id,label,profile}]`). **`profile`** (2026-06-18, L091) = fiche
    d'affichage **rédigée par l'admin** (tagline/description/capabilities/tools/icon/badge), validée+bornée
    serveur par `validate_agent_meta` (pur, ne lève jamais ; whitelist icônes = registre front) et **stockée
    DANS ce JSON, PAS de nouvelle table**. Via `storage/settings.py`. Voir L017 + L091.
- **Connexion configurable** (plus de hardcode) : params webapp `sql_connection`/`table_prefix`/`log_level`
  (`hideWebAppConfig=false`), lus via `get_webapp_config()`. ⚠️ dropdown Settings KO (L012) → champ texte.
  Nommage `{PROJECT_KEY}_{prefix-}owismind_{logical}` (préfixe optionnel après le project key).
- Tables futures (cahier) : `_messages`, `_runs`, `_run_events`, etc. (toujours `_vN`, jamais d'ALTER).

## 8. Agents & streaming

- **Whitelist DYNAMIQUE implémentée (✅ validée EN DSS - L017)** : plus de `ALLOWED_AGENTS` hardcodé.
  L'admin découvre les projets/agents (`agents/discovery.py`, **lecture seule** : `list_project_keys` →
  `list_project_agents` filtré sur `agent:`), choisit la sélection, persistée en `webapp_settings_v1`
  (clé `enabled_agents`). La POST `/admin/agents` **re-valide** chaque agent contre le listing live.
  Le front user reçoit **uniquement** des **clés logiques opaques** (`ag_<sha1>`) + labels via `/agents` ;
  jamais d'`agent_id`/`project_key`. Depuis **L091 (2026-06-18)**, `/agents` renvoie AUSSI la **fiche
  d'affichage rédigée par l'admin** (tagline/description/capabilities/tools/icon/badge) = source unique des
  cartes de la bibliothèque (fin du registre hardcodé `agentMeta.js`, supprimé) ; toujours **aucun**
  `agent_id`/`project_key`. **Chat → résolution serveur** : `settings.resolve_enabled_agent(key)` mappe
  la clé logique → `(project_key, agent_id)` dans `/chat/stream` (L018) ; la `profile` est ignorée côté chat.
- **Streaming ✅ VALIDÉ EN DSS (L019)** - run agent : `agents/streaming.py` →
  `dataiku.api_client().get_project(project_key).get_llm(agent_id).new_completion().with_message(q)
  .execute_streamed()` (⚠️ `get_project(pk)`, pas `get_default_project()` : l'agent peut être hors projet courant).
- Chunks : footer (`type=="footer"`/isinstance `DSSLLMStreamedCompletionFooter`) ; `type=="event"` → events agent
  (`AGENT_BLOCK_START`, `AGENT_TOOL_START`, …) ; `type` in `content|text` → delta réponse ; footer.trace →
  usage (`usageMetadata`) + SQL généré (`name=="semantic-model-query"`→`outputs.sql`, fallback `eventData.generatedSql`).
- **Transport = POLLING-via-thread (le SSE est ABANDONNÉ, bufferisé par le proxy DSS - L019)** : `agents/
  stream_manager.py` lance un **worker daemon** par envoi (itère `run_agent_streamed`, empile les events normalisés
  dans `_RUNS` dict sous `_LOCK`), le front **poll `/chat/poll`** (500 ms). Pattern porté du **Dash de prod**
  (`old_webapp_in_dash/`) qui ne relaie jamais de réponse HTTP longue → contourne le buffering. Garde-fous :
  `MAX_CONCURRENT_RUNS=8`, TTL éviction (60s/600s), scope `user_id`.
- Events normalisés (mêmes qu'avant) : `run_started`, `agent_event`, `answer_delta`, `generated_sql`,
  `usage_summary`, `final_answer`, `run_done`, `error`. **Usage streamé NON stocké** ; trace brute **non envoyée au front
  live** mais (L027/L028) **appendée sur le dataset Flow** côté worker (phase 2, best-effort). ⚠️ La **réponse texte** tombe
  en bloc à la fin (agent structuré) - le live exploitable = la **timeline**.
- Agents métier prévus (cahier) : Orchestrateur OWIsMind (défaut), Revenues, Tickets, CX,
  Opportunities, Product/Customer Base, Delivery. Ids connus : `agent:rNTZ781a` (visuel, désactivé),
  `agent:MODpGFcC` (SalesDrive v2 Code Agent, live).
- **Système v3 générique `dataiku-agents/` (2026-06-12, ⏳ non validé DSS)** : recettes Flow
  `profile_dataset` + `build_value_index` (expertise fabriquée en design : profil JSON + index de
  valeurs, overrides humains éditables) → `agents/dataset_expert_agent.py` (sous-agent GÉNÉRIQUE :
  SQL par templates 9 intents + garde-fou LLM-SQL `custom`, exécution read-only SQLExecutor2 +
  EXPLAIN + réparations, success véridique dans les spans `semantic-model-query`) →
  `agents/orchestrator_agent.py` v3.0 (= v2.4 + fan-out parallèle + entrée registre
  `revenue_expert`, placeholder id). Guide d'implémentation : `dataiku-agents/README.md`.
  Contrats gelés webapp/Evidence respectés. Détail → L051 + `sessions/2026-06-12.md`.
- **Refonte LangGraph + artefacts webapp (2026-06-15, ✅ VALIDÉ DSS - L055-L057)** : orchestrateur et
  sous-agent portés en **LangGraph** (Code Agents, env **3.11**) - fichiers NOUVEAUX
  `agents/orchestrator_langgraph.py` (boucle agentique sous-agents-comme-outils + tools
  `ask_revenue_expert`/`show_chart`/`show_table`/`current_date`, appels **natifs Mesh**, reasoning,
  réponse dans la langue user, fan-out parallèle) et `agents/dataset_expert_langgraph.py` (StateGraph,
  **moteur SQL byte-identique**, UNDERSTAND force `with_json_output`). gpt-5.4-mini partout
  (reasoning=high sur le modèle Mesh). Originaux `*_agent.py` = rollback intact. Artefacts : tool
  → event gelé `ARTIFACT` → table `webapp_artifacts_v1` (read-only+timeout) → `/evidence/meta` →
  onglets Evidence/Chart/Table, **Chart.js** (payload Python `evidence/chart_payload.py`). `chart.js`
  ajouté au front (bundlé). Détail → `sessions/2026-06-15.md`.

---

## 9. Maquette cible - SUPPRIMÉE du repo (2026-06-11, conversion terminée)

La maquette (SPA HTML/JS/CSS sans framework, `maquette/` + son paquet de docs de transmission) a servi de
**référence visuelle** pour la conversion Vue 3 - **complète et validée en DSS** (§13). Elle a été supprimée
au nettoyage du 2026-06-11, en même temps que `docs/superpowers/plans/` (journaux d'exécution) et
`.demo-screens/` (captures régénérables). Les specs gelées (`docs/superpowers/specs/`) sont conservées.

- Ce qui en survit vit **dans le code** : design system Orange → `styles/tokens.css` (port verbatim),
  dictionnaire i18n → `i18n/messages.json` (port 1:1, PRISTINE - F6), icônes → `components/ui/icons.js`.
- Le *quoi* du frontend actuel → `docs/frontend.md` ; le *pourquoi* → §13 + `LESSONS.md` (L022+).
- Les mentions « maquette » dans les leçons, les sessions et les commentaires du code sont **historiques**
  (provenance) - ne pas chercher ces fichiers sur le disque.

---

## 10. Règles métier non négociables (cahier)
- **Budget** 50€/user/mois (configurable) : 50% info, 80% warning, 100% blocage d'envoi.
- **Lazy loading** dataset (charger à l'ouverture de l'onglet) ; **un agent actif à la fois** ;
  sample obligatoire + warning « vue = échantillon, calcul agent possiblement sur dataset complet ».
- **Evidence Studio** = pilier confiance ; SQL en onglet dédié (ne pas polluer la réponse).
- **Voice input** : ne pas envoyer automatiquement (insérer dans la prompt bar pour édition).
- **Confidentialité** : l'utilisateur ne voit que ses conversations + les agents autorisés.
- **Multilingue** : tout label UI traduisible (FR + EN en V1).
- Trio différenciant : **Conversation + Live Timeline + Evidence Studio**.

---

## 11. Matrice de validation

| Sujet | État | Note |
|---|---|---|
| Scaffold Vue 3 + Vite, build → `resource/owismind-app/` | ✅ Validé | un build existe ; assets câblés dans body.html |
| `vite.config.js` (base + outDir réels) | ✅ Validé | noms réels corrects |
| Zip runtime propre (sans frontend/node_modules) | ✅ Validé | `owismind-upload.zip` conforme |
| Backend Flask modulaire (`routes.py` + `/owismind-api/*`) | ✅ Validé | bootstrap `register_routes(app)` + Blueprint ; `ping`/`dev/chat-probe/{send,recent}` 200 |
| SQLExecutor2 (CREATE/INSERT/UPDATE/SELECT/COMMIT) | ✅ Validé backend | chat_v1 : INSERT+UPDATE 2 temps + COMMIT constatés (logs DSS) |
| `dataiku.default_project_key()` en contexte plugin | ✅ Validé | résout `OWISMIND_DEV` (L007) |
| **Identité** `get_auth_info_from_browser_headers` | ✅ Validé backend | clés réelles connues (L011) ; `authIdentifier`/`groups` OK |
| **chat_v1 bout-en-bout** (`/me`,`/chat`,`/history`) | ✅ Validé DSS | écriture 2 temps, filtrage user, accents OK |
| **Frontend persistant** (reload → history) | ✅ Validé DSS | `App.vue` charge `/me`+`/history` au montage |
| **Storage configurable** (params webapp + nommage préfixe) | ✅ Validé DSS | `storage_status()` correct (logs) ; L014 |
| **Dropdown connexion dans Settings** (`getChoicesFromPython`) | ✅ Validé DSS | fonctionne (L016) ; **L012 obsolète** |
| **Espace admin** (table users, 1er=admin, onglet Admin, promotion) | ✅ Validé DSS | confirmé avec la slice L017 (2026-06-03) |
| **display_name auto-rempli** (prénom dérivé + backfill COALESCE) | ✅ Validé DSS | confirmation user 2026-06-03 (L017) |
| **Agents whitelist** (settings table + `/admin/agents` + `/agents`) | ✅ Validé DSS | re-validation serveur ; confirmation user (L017) |
| **Découverte agents DSS** (`list_project_keys`/`list_llms`, lecture seule) | ✅ Validé DSS | bornée, à la demande ; confirmation user (L017) |
| **Multi-webapps `webapp2`** (collision) | 🟡 En attente | besoin valeur `DKU_CUSTOM_WEBAPP_CONFIG` (id stable webapp) |
| **Vrai agent + streaming live** (`/chat/start`+`/chat/poll`, worker+`run_agent_streamed`) | ✅ Validé DSS | **polling-via-thread** ; SSE abandonné (bufferisé) ; logs : curseur live, zéro buffering (L019) |
| **Stop génération** (bouton ■ → `/chat/stop` ; arrêt coopératif + partiel) | ✅ Validé DSS | LLM Mesh sans API cancel → cesser d'itérer ; terminal `stopped` ≠ error ; pas de schéma (L034) |
| **Table `webapp_chat_v2`** (col `generated_sql`) | ✅ Validé DSS | CREATE IF NOT EXISTS ; réponse+SQL persistés ; remplace v1 |
| **Trace = footer BRUT → DATASET Flow append** (write-only, param `traces_dataset` SELECT) | ✅ Validé DSS (2026-06-08) | user « ça enregistre bien les logs » ; `write_with_schema` **positionnel** (`_column_order`) ; best-effort auto-protégé ; **remplace** la table SQL `_traces_v1`/`/chat/trace` de L021 (L027/L028) |
| **Audit final Dataiku** (`OWISMIND_FINAL_DATAIKU_AUDIT.md`, workflow 11 agents + doc off. + adversarial) | ✅ GO WITH CONDITIONS | 0 Critical/High confirmé ; conditions C1 (1 process) / C2 (append accumule) à verrouiller (L028) |
| **Sélecteur agent + timeline live + panneau SQL** (front) | ✅ Validé DSS | timeline défile live ; 2 fixes : `reactive()` + `.msg{flex-shrink:0}` (L020) |
| **SSE depuis backend webapp DSS** | ❌ KO (bufferisé) | proxy nginx interne DSS bufferise le flux long → polling à la place (L019) |
| Tables webapp créées (DDL idempotent) | ✅ Validé backend | `CREATE TABLE IF NOT EXISTS` (chat_v1, users_v1) |
| Sûreté backend (zéro DDL destructive, API DSS lecture seule) | ✅ Audité | greps vides ; L015 |
| Python 3.11 / FastAPI | ❌ Non validé | ping a retourné 3.9.23 ; ne pas affirmer 3.11 |
| **Conversion maquette → Vue 3 (front V1 complet : Phases 0-5)** | ✅ Validé DSS | confirmation user (« à merveille ») : chat live, identité+prénom, agents, history, pages + Admin. Détail §13 |
| **Audit sécurité pré-DSS** (workflow 6 dim. adversarial) | ✅ GO | 0 critical/high/medium ; 4 correctifs backend (display_name `/me`, bornes RAM, garde récursion, logs). L026 |
| **Préférences unifiées** (store `ui` : thème+langue+`contextMessages`) | ✅ Validé DSS | une seule persistance/préf ; `maxConversations`→`contextMessages` (L029→L030) |
| **Timeline chronologique** (reducer pur `timelineModel.js`) | ✅ Validé DSS | ordre DOM event↔texte ; merge deltas ; node:test (L029) |
| **Historique multi-tours → agent** (contexte = chaîne d'ancêtres ; nom+date) | ✅ Validé DSS | `context.py`+`history_messages_for_chain` ; message stocké BRUT ; user (L030/L032) |
| **Sidebar lazy** (`/conversations` paginé keyset + `/conversation` au clic) | ✅ Validé DSS | noms seuls ; ~120 %+infinite-scroll ; plus de fetch unique `/history` (L030) |
| **Feedback par message** (colonnes table chat ; `/chat/feedback` owner-scopé) | ✅ Validé DSS | 👍/👎 persistés/coloriés ; 👎 popup, 👍 ⋯ ; raisons whitelist (L031) |
| **`generated_sql` dans le contexte agent** (borné, input-only) | ✅ Validé DSS | `_format_sql_context` ; jamais re-stocké (L031) |
| **Switch de conversation sans flash** (overlay centré) | ✅ Validé DSS | `openSession` ne vide plus ; rgba+`:global` dark (L031) |
| **Arbre de conversation** (édition prompt → branche ; `parent_exchange_id` ; CTE ancêtres) | ✅ Validé DSS | versions turn-level persistées ; contexte tronqué à la branche ; `conversationTree.js` pur (L032) |
| **Agent persistant par conversation** (dernier échange + localStorage) | ✅ Validé DSS | `pickDefaultAgent` pur ; adoption différée (race fix) (L032) |
| **Fix scroll vs navigation de versions** (preuve empirique Chrome DevTools) | ✅ Validé DSS | repin seulement switch/nouvel-échange/streaming, jamais sur `turns` (L032 item 8) |
| **Timeline ChatGPT-style** (ticker live 5 lignes/phase, interlacé, gris-shimmer/orange, repli 1 ligne) | ✅ Validé DSS (2026-06-10) | user « comme sur des roulettes » ; sélecteurs purs read-only, signature scroll intacte (L039) |
| **Lifecycle Evidence** (fermeture hors chat `[route.name, evidence.open]` + réouverture auto + re-pin scroll + skeletons) | ✅ Validé DSS (2026-06-10) | continuité = `_autoOpenEvidence` gaté `!sending` (L038) |
| **Nav : URL stamp + `ensureSession`** (fix bouton « New conversation » mort + bump capturé + `canSend` gaté) | ⏳ Packagé, NON validé DSS | dans le zip Run 4 `index-CHg5FN2k.js` ; run survit à Settings (L040) |
| **Chrono par étape** (stamps backend = vérité) | ⏳ Packagé, NON validé DSS | dans le zip Run 4 ; la popup « vue agent » du même lot a été SUPPRIMÉE (Run 4) (L041) |
| **Run 4 « Réparer Evidence Studio »** (Evidence à DROITE + repli sidebar non persisté ; parseur BEST-EFFORT JOIN/CTE/sous-requêtes ; « agent saw N rows » supprimé ; chips tous éditables + popover z-index + caps miroir + `exclude_id`) | ⏳ Packagé, NON validé DSS | inclus dans le zip trust layer 74 entrées ; revue 25 agents 19/19 corrigés (L042/L043) |
| **Trust layer Evidence v2** (badge vérification déterministe 5 niveaux + result_captured ; `sql_explain` steps métier + lineage nom-source ; capture résultat exact opportuniste dans `generated_sql` JSON ; drill-down re-validé serveur ≤8 clés ; meta enrichie ; `transaction_read_only` ; orchestrateur v2.2 corrélé sql_id/step_index/agent_key ; timeline labels backend) | 🟡 Déployé, FONCTIONNE (retour user 2026-06-11 : « ça marche bien ») mais **pas encore comme il veut** - ajustements NON précisés, à recueillir avant tout code | zip **74 entrées `index-DF9WrJFi.js`** ; 304+59 unittest/97 node:test ; revue 26 agents **17/17 corrigés** (L044/L045) ; ~~clé des rows à confirmer~~ → RÉSOLU par SalesDrive v2 (L047 : capture depuis le retour du tool) |
| **SalesDrive v2 Code Agent + orchestrateur v2.3** (UNDERSTAND JSON strict → resolver → semantic_question templates gelés → semantic tool direct → rendu vérifié ; désambiguïsation 3 étages : `pass_context`/valeur-exacte/priorité-colonne/round-trip « VALEUR (Colonne) » ; `AGENT_RESULT` structuré) | ✅ Validé DSS (2026-06-11, retour user « super tout marche ») ; reste : vraie ambiguïté de valeur (« IPL + ») et plan multi-étapes non re-testés ; bascule définitive (retrait entrée visual) à faire | traces réelles (sql_count=1, row_count=10, headline verified=true) ; 55 unittest salesdrive + 62 orchestrateur ; 97 node:test intacts (L047/L048) |
| **Système v3 générique `dataiku-agents/`** (profiler + value index + Dataset Expert + orchestrateur v3 parallèle, moteur HYBRIDE : Semantic Model Query tool par défaut + SQL direct en fallback technique) | ✅ **VALIDÉ DSS (2026-06-12, user « ça marche super bien »)** : recettes exécutées, expert `agent:AKQaQ0Am` live (semantic_tool, mode Agent), orchestrateur routé (`revenue_expert=True`/`salesdrive_v2=False`). ⏳ fan-out parallèle réel (attend un 2ᵉ domaine) ; fallback direct jamais déclenché en réel | 127+86+55 unittest ; fixes réels : cast-safe dates, extraction mode-Agent dernier-gagnant, énumérations IN/OR (L051/L052) ; anomalies semantic model notées (ACTUAL vs ACTUALS, synonyme roaming hub) |
| **Agents LangGraph + artefacts webapp** (orchestrateur agentique sous-agents-comme-outils + sous-agent StateGraph, gpt-5.4-mini reasoning ; `show_chart`/`show_table` → event `ARTIFACT` → `webapp_artifacts_v1` → onglets Chart.js, payload Python) | ✅ **VALIDÉ DSS (2026-06-15, user « tout fonctionne comme sur des roulettes »)** : LangGraph tourne sur Code Agent 3.11 (`get_stream_writer` sync + `graph.stream(custom)` + Mesh natif) ; fix UNDERSTAND = `with_json_output` ; Chart.js bundlé (installé par l'user) | 151 agents + 348 backend + 130 node verts ; revue sécurité Opus sans bloqueur ; L055-L057 |
| **Modèle sémantique aligné + sous-agent ASSISTIF** (NOUVEAU modèle sémantique sur Sonnet 4.6, l'ancien `2O2KcHw` intact ; scripts `dataiku-agents/tools/semantic_model/{build,update}_aligned_semantic_model.py` + `README.md` ; corrections ACTUAL→ACTUALS/glossaire/hiérarchie offre/affichage nom+carrier/Account_partner/une-table-no-join/9 golden queries ; `build_semantic_question` refondu : question user + HINTS, **terme d'offre ambigu NON épinglé → le modèle tranche**) | ✅ Nouveau modèle **créé + indexé + tool `v4oqA6R` repointé + Sonnet** (user, Playground OK) | bug réglé : pin déterministe `sirano_product='EVPL'`→budget=0 (`column_priority` fallback `-distinct_count`) ; `create_semantic_model` + workflow versions, update en place sans re-index, jamais instancier les classes (L058-L059) |
| **Optimisation modèle-agnostique (2026-06-16, agents renommés `OWIsMind_orchestrator` + `SalesDrive_revenue_expert`=`agent:bHrWLyOL`)** : orchestrateur boucle agentique simple (le modèle rend les artefacts librement PUIS rédige, pas de synthèse séparée) ; **narration LIVE écrite par le modèle** (préambule `resp.text` streamé en event `NARRATION` transient ; déterministe en filet ; phases sous-agent narrées) ; **modes Éco/Medium/High** (`pick_loop_llm`, escalade conservatrice vers Sonnet) + sélecteur UI ; **artefact KPI** + styles graphiques ; **Evidence** SQL coloré + « Explore source data » **lazy loading** (≥20 lignes, toutes colonnes, scroll, cap 500) + sélecteur multi-tables ; capture résultat sur le **dernier** SQL (`i==last_i`) ; nettoyage repo (legacy v2 + linéaires v3 retirés, préservés en git) | ✅ **VALIDÉ DSS (2026-06-16, user « super all good ça marche pas mal »)**. **Recoller LES 2 Code Agents** (env 3.11) à chaque modif repo. Reste optionnel : sélecteur SQL multi-résultats, durcir narration mini | 156 agents + 366 backend + 113 node verts ; revues Opus sans bloqueur ; zip **77 entrées `index-BM3sFZCq.js`** ; **L060-L065** ; ⚠️ bloqueur évité : `strict:True` tool specs = 400 OpenAI (L061) |
| **Audit agents + langue/UX/escalade (2026-06-16 Run 4)** : **langue** (détection word-boundary du dernier prompt, bloc contexte appendé EN FIN, token `⟦owi:lang⟧` autoritaire lu en DERNIER = anti-spoof, sous-agent `forced_language`) ; **messages live = vrais** (préambule modèle via `_txt`/answer_delta persisté, pas NARRATION) ; **conscience écran** (`build_screen_state`/`_build_screen_block` owner-scopé gaté panneau ouvert + `screen_context` frontend) ; **timeline UX** (`timelineSegments` ignore narration → max-5 globale + gris/orange) | ⏳ **partiellement validé** : langue/messages-live/écran/timeline gardés ; **escalade L067/L068 RETIRÉE au Run 5** (échec DSS gpt-5.4-mini) | L066-L070 ; voir Run 5 |
| **MODEL-AGNOSTIC : fin de l'escalade + Dataset Lookup + stop optimiste + hiérarchie timeline (2026-06-16 Run 5)** : test DSS Run 4 = gpt-5.4-mini **escalade systématiquement** / **narre puis s'arrête** → **escalade SUPPRIMÉE** (tool `escalate_to_expert`, `can_escalate`, `switch_model`, `ESCALATION_LLM_ID`, `_ESCALATE_*`, auto-escalade, event `ESCALATING`) ; `LOOP_LLM_BY_MODE` {eco/medium:Gemini Flash, high:Sonnet}, **1 modèle/tour** ; sous-agent aussi sur Flash ; prompt ACT-FIRST **+ NARRATE-AS-YOU-GO** ; **Dataset Lookup** `9FEzVZk` + intent `lookup` + champ `attributes` + **schéma LIVE** (`Profile.live_columns`/`match_attribute`/`_read_live_columns`) → account_manager sans SQL, fallback SQL sur échec, span gelé `semantic-model-query` ; **stop optimiste** (`stopGeneration` applique `{type:'stopped'}` direct) ; **hiérarchie timeline** (steps `SUB_AGENT_*` indentés `.sub-step`) | ⏳ **CODÉ + revue, NON validé DSS**. **⚠️ VÉRIFIER `GEMINI_FLASH_ID`** (2 fichiers) ; **recoller LES 2 Code Agents** (env 3.11) + upload zip ; **backend python-lib inchangé → pas de redémarrage** | 193 agents + 114 node verts + build Vite ; zip **77 entrées `index-CZu1PIfv.js`** ; **L071-L074** ; différé : persistance chaîne d'events au reload |
| **Ajustements modèle/UX + 3 audits à l'aveugle (2026-06-16 Run 5b/5c)** : **eco=gpt-5.4-mini GARDÉ** (medium=Gemini, high=Sonnet) ; narration « parle pendant le tool-call » détachée du prompt et OFF en eco (`narration_enabled`) ; **mode propagé au sous-agent** (`MODE:` → `forced_mode` → `pick_subagent_llm`/`SEMANTIC_TOOL_ID_BY_MODE`, threadé dans l'état ; high=Sonnet partout) ; **stop = attente + bannière « Stopping… »** (flag `version.stopping`, revert de l'optimiste) ; **popup de mode** (`ModelModePicker`→`Modal`, coût €/€€/€€€ + enveloppe 50 €). Puis **3 audits à l'aveugle** (sous-agent « architecte » + skill agentique, copies /tmp, zéro contexte) → durcissements : caches keyés stable, `_pair` appariement tool↔output, **garde SQL** (espace-less `FROM"x"` + littéraux blanchis + tables système + `WITH RECURSIVE`), lookup OR `alt_columns`+fallback vide→SQL, cap de boucle honnête, nudge 1×/run, `original_intent`+note dégradée, `_cap_cell` NaN/inf, `u` non muté en place ; `run_parallel` borné (futurs tools) + résolution fuzzy séquentielle (sécu instance) | ⏳ **CODÉ, NON validé DSS. Verdict 3ᵉ audit aveugle = « production-ready côté archi agentique » (0 Critical/0 High).** **⚠️ VÉRIFIER `GEMINI_FLASH_ID`** + **recoller LES 2 Code Agents** + upload zip (pas de redémarrage backend) | 217 agents + 116 node verts + build Vite ; zip **77 entrées `index-3FmqVbc1.js`** ; **L075-L078** ; différé : persistance events reload, sonde id modèle, découpe `n_query` |
| **Run 6 (2026-06-17) : modèles revus + argent €/transparence + désambiguïsation DÉFÉRÉE + source Evidence CLIQUABLE + nettoyage prod** : eco=**Gemini 3.1 Flash-Lite** (DÉFAUT), medium=**Gemini 3.5 Flash**, high=Sonnet, **gpt-5.4-mini/`GPT_MINI_ID` supprimés** (front défaut Éco + badge Recommandé sur Éco) ; **`metric_unit`** dérive `€` du nom de colonne `amount_eur` (aucune config profil) ; **`build_scope_note`** = ligne `[Périmètre]` (scénario/période « aucun filtre d'année »/entité/devise) + PERSONA orchestrateur impose `€` + restitution du périmètre + analyse ; **`defer_multicolumn_offer_terms`** (terme d'offre ambigu ≥2 colonnes → `deferred`, déféré à Sonnet « NEVER default to sirano_product » + divulgation ; mono-colonne demande encore ; P3 par nombre de colonnes) ; **bloc « Sources » retiré** du chat ; **source Evidence cliquable** : champ registre `source_url` (vide) propagé **additif** via items SQL (`_find_generated_sql`→`streaming`→`stream_manager`→`capture`→`service.py` `meta.source.url`/`source_url_for_run`/`with_source_urls`) → `EvidenceSources.vue` `<a target="_blank">` (i18n `ev.proof.sources.open`) ; commentaires agents nettoyés (zéro empreinte IA) | ⏳ **CODÉ, NON validé DSS.** Revue adversariale (Workflow 26 agents, 4 dim × 2 sceptiques) = **0 bug de code**. **⚠️ VÉRIFIER `GEMINI_FLASH_LITE_ID`** + **remplir `source_url`** (si lien voulu) + **recoller LES 2 Code Agents** + upload zip + ⚠️ **REDÉMARRER backend** (python-lib changé : Evidence/source) | 227 agents + 384 backend + 116 node verts + build Vite ; zip **77 entrées `index-8spQsYzC.js`** ; **L080-L082** ; différé : mapping URL par-dataset multi-source |
| **Session nettoyage (2026-06-17, après Run 7c) : réorganisation repo + doc `dataiku-agents/`** : vestiges v2 `orchestrator/`+`salesdrive/` supprimés ; `cadrage/`->`docs/cadrage/`, `agentic-research/`->`docs/agentic-research/` (gitignored), refs à jour partout (logs de session datés intacts) ; **`dataiku-agents/` = mini-repo documenté** (README maître + CLAUDE.md réécrits + sous-READMEs `agents/`/`recipes/`/`tools/` + recette `Value_Catalog` versée en STATUS roadmap + `semantic_model/` déplacé sous `tools/`) ; **archi v3 clarifiée** (grounding **inline `value_index`** + 2 tools `revenue_semantic_query` v4oqA6R + `dataset_lookup` 9FEzVZk ; `Value_Catalog` + tool Python `Drive_Revenues_resolve_filter_value` = roadmap, NON câblés en v3) ; `GEMINI_FLASH_LITE_ID` corrigé `flash-light`->**`flash-lite`** (2 agents, preuve = code déployé collé par l'user) | ✅ **local** (nettoyage/doc only, aucun comportement d'agent changé, pas de DSS) ; revue adversariale doc-vs-code (Workflow 5 agents) = 0 lien cassé, 2 imprécisions LOW corrigées | 227 tests agents verts ; 0 tiret cadratin ; **L085** ; recâblage `dataset_lookup`->tool Python resolver `Value_Catalog` = **DÉFÉRÉ** à une session dédiée |
| **Resolver rapide `attribute_lookup` + suppression totale `dataset_lookup` (2026-06-18)** : nouveau Custom Python tool `dataiku-agents/tools/attribute_lookup_tool.py` (`BaseAgentTool`) = recherche full-text `ILIKE` (insensible casse+accents) sur **toutes les colonnes texte** du fact ; sortie `found_in` (colonne où le terme est + valeur exacte) + `attributes` optionnels ; **fallback alias optionnel** sur `DRIVE_Revenues_Value_Catalog` (suggestions) ; read-only (`statement_timeout`/`transaction_read_only`/`LIMIT`), rien en RAM, **zéro nom de colonne en dur** (schéma lu live, priorité par signaux génériques catalog). **`dataset_lookup` (9FEzVZk) ENTIÈREMENT SUPPRIMÉ** : sous-agent (intent `lookup`, `build_lookup_filter`/`extract_lookup_rows`/`lookup_note`/`_lookup_rows`, `Profile.match_attribute`/`attribute_columns`/`live_columns`, `_read_live_columns`, `HEADLINE_LOOKUP`, chemin `n_query`, prompt UNDERSTAND, `KNOWN_BLOCK_IDS`/`KNOWN_TOOL_NAMES`) + orchestrateur (`block_labels`/`tool_labels`/`_BLOCK_NARR`/`_NARR`, contrat anti-dérive) + 18 tests + doc (CLAUDE.md, README maître, agents/README, tools/README) | ⏳ **tool CONSTRUIT + 33 tests + RUN TEST DSS validé user (blanchard, Algérie Télécom) ; NON BRANCHÉ** (questions simples repassent par le semantic model lent en attendant). 2 agents modifiés (sous-agent + orchestrateur) à recoller AU BRANCHEMENT | **242 tests agents verts** ; `ast.parse` 2 agents OK ; grep `dataset_lookup` = NONE ; **L086** ; branchement (conception + sous-agent vs orchestrateur) = workflow multi-agents prochaine session |
| **`attribute_lookup` BRANCHÉ (ORCHESTRATEUR built-in) + durci + multi-table (2026-06-18 Run 2)** : conseil multi-agents (Workflow) = **4/4 ORCHESTRATEUR built-in** (spec `build_tool_specs` + dispatch inline `node_tools`, comme `show_table`/`current_date`) → **zéro contrat `KNOWN_*`, SOUS-AGENT INCHANGÉ** ; provenance Evidence via subspan `semantic-model-query` (`state['captured']` vestigial) ; **multi-table** (modèle passe un domaine logique → table whitelistée via registre `lookup_domains()`/`lookup_dataset`/`lookup_catalog`, rule #3/#4) ; **SQL = 1 seul `ILIKE`** sur `concat_ws` (au lieu de 18 `OR`), accents par `translate` à la requête (user REFUSE `unaccent`/toucher la base prod ; `accent_fold_sql`, flag unaccent retiré) ; durci (`rows_capped`/`multi_column`, garde needle court, cache TTL clé-dataset, `not_found` adouci, garde found-vide→not_found) ; **Value_Catalog + `suggestions` GARDÉS** (décision user, suppression annulée) ; commentaires zéro empreinte IA | ⏳ **CODÉ + RUN TEST DSS validé** (lookup rapide ~14s + descente expert) ; **À RECOLLER** : MAJ tool DSS `attribute_lookup` + recoller ORCHESTRATEUR (env 3.11) + **SUPPRIMER l'objet tool `Drive_Revenues_resolve_filter_value`** (jamais appelé, 170K en pandas-RAM) | **267 tests agents verts** ; revue adversariale diff (Workflow 3 relecteurs) = 0 crit/0 high, 2 LOW corrigés ; **L087** ; nuance en suspens : `suggestions` aussi sur recherche d'attribut ? ; leçon process : conseiller avant de supprimer |

## 12. Prochaines étapes (à jour 2026-06-09)
> **TOUT le V1 + les 4 lots du 2026-06-09 (historique multi-tours, sidebar lazy, feedback, arbre/branches, agent persistant) sont VALIDÉS EN DSS.** Reste :
1. **Evidence Studio (DIFFÉRÉ - décision user)** : registres `artifacts.js`/`proofModes.js`, `stores/evidence.js`,
   `composables/useEvidenceCalc.js`, `components/evidence/`, aside réservé `AppLayout` (grille `with-evidence`) → onglets SQL
   (`generated_sql`)/Trace/Coût (`usage_summary`). ⚠️ **Blocant lignes** : `generated_sql` = SQL + row_count (**pas les lignes**) →
   réconciliation sans source ; trace = **dataset Flow write-only** (plus lisible en ligne, `/chat/trace` supprimé) → onglet Trace à repenser.
2. **Nettoyage repo - FAIT (2026-06-09, session cleanup)** : legacy backend retiré (`/history` + `history_for_user` + `build_history_query` + `validate_max_conversations`/`*_MAX_CONVERSATIONS` + `_one_line` + `tests/test_history.py`) ; front allégé (`UiShowcase.vue`, `Badge.vue`, dir `components/evidence/` vide supprimés ; clé i18n morte `x.not_available_yet`) ; **fuite de contenu dans les logs corrigée** (`/chat/start` ne logge plus le `preview` du message, seulement `msg_len` - ex-finding audit LOG-01) ; junk purgé (`old_webapp_in_dash/`, screenshots, `__pycache__`, `.DS_Store`, staging décompressé) ; `cadrage/` condensé (2 guides → `GUIDE_DATAIKU_DSS_PLUGIN_REFERENCE.md`, −80 %). `messages.json` laissé **pristine** (invariant F6/L023 ; clés `ev.*` réservées Evidence Studio = pas du code mort).
3. **Durcissement tests (TEST-01, recommandé - NON fait)** : ajouter des tests unitaires DSS-free (stub `dataiku`/`pandas`) pour les invariants déjà durcis mais non couverts - `sql_config.pg_identifier` (rejet injection / >63 octets), `serialization.rows_to_json_safe` (NaN→None), `settings.resolve_enabled_agent` (clé forgée→None), `stream_manager` (cap/TTL/poll-owner/`_stop_reason`), `chat_traces.save_trace` (no-op/troncature) ; + brancher `py_compile`/`compileall` sur `python-lib` comme CI minimale. (Les tests actuels couvrent surtout les bornes de `validation.py`.)
4. (Backend, option) Route « set my name » (`webapp_users_v1.display_name` éditable, COALESCE déjà prospectif - `POST /me` fait l'upsert registry + bootstrap admin mais **n'édite pas encore** le nom choisi) ; multi-webapps `webapp2` (`DKU_CUSTOM_WEBAPP_CONFIG`).
5. **Notes opérationnelles DSS** : 1ᵉʳ admin = 1ᵉʳ à ouvrir l'app ; modèle polling + `_RUNS`/cache auth supposent backend **mono-process**
   (cond. C1) ; agent sous identité webapp (exposition contrôlée par la whitelist) ; bascule de table chat = nouvelle table **vide** (données test perdues, assumé).
   **Fait API (ex-audit DOC-06)** : un param webapp natif `DATASET` n'est pas filtrable en Python (seul `canSelectForeign` existe) → pour distinguer SQL vs filesystem, lire `DSSDatasetListItem.type`/`.connection` (lever derrière l'approche `SELECT` + `getChoicesFromPython` adoptée en L028).
6. **2ᵉ task mentionnée par l'user le 2026-06-09 mais pas encore décrite** - à clarifier.

---

## 13. Frontend Vue 3 - conversion maquette (✅ COMPLET & VALIDÉ EN DSS, 2026-06-05)

> On **habille** le socle backend validé (réutilisé) avec l'UI de la maquette (supprimée du repo après
> conversion - §9), sur une **archi modulaire à registres**
> (ajouter une brique = enregistrer un module isolé). Travail dans `Plugin/owismind/frontend/`. **✅ Phases 0-5 validées EN
> DSS** (confirmation user « ça fonctionne à merveille » : chat live, identité avec prénom, agents, history, pages + Admin) ;
> **Evidence Studio différé** (décision user). Audit sécurité pré-DSS passé GO + 4 correctifs backend (→ L026).
>
> **🟠 STYLE = CHARTE ORANGE (source de vérité : `docs/cadrage/CHARTE_ORANGE_UI.md`, règle non négociable #10).**
> Refonte "maquette Orange" 2026-06-19 (multi-agents, L092) : blanc/noir + orange #FF7900 accent RARE, géométrie
> **carrée**, aplats/filets 1px, H1 36/800 + eyebrow orange + title-bar 52x4, tokens sémantiques. Le logo de marque
> est la VRAIE image `assets/orange-logo.png` (rail + sidebar), **jamais** un visuel généré en CSS. Tout futur style
> applique cette charte.

### 13.1 Stack & deps (installées par l'user - NO INSTALL)
`vue@3.5` · `vite@8` · `@vitejs/plugin-vue@6` · **`pinia@3.0.4`** · **`vue-router@5.1.0`** · **`vue-i18n@11.4.4`** ·
**`markdown-it@14`** · **`dompurify@3.4.8`**. `vite.config.js` (base/outDir) **inchangé/canonique**.

### 13.2 Arborescence réelle `frontend/src/` (créée Phases 0-2)
```
main.js                      # createApp + pinia + i18n + router ; pose body[data-theme] avant mount ; expose window.__pinia en DEV
App.vue                      # shell racine : <AppLayout/> + <ToastHost/> ; session.ensureLoaded() au mount
services/backend.js          # ⚠️ INTACT (12 fns) - client backend validé, NE PAS toucher
styles/{tokens.css,base.css} # tokens (theme.css verbatim + no-op) ; reset+keyframes+utils (.u-no-shrink = L020)
components/ui/               # PRIMITIVES MUTUALISÉES : Icon(+icons.js 57 icônes) Button Tabs Menu Modal ToastHost (+index.js barrel)  [Badge supprimé au cleanup L033]
components/shell/            # AppLayout (grille .app 2col + resize) · Sidebar · MainTop
components/chat/             # AgentPicker(repeuplé /agents) PromptBar MessageUser MessageAgent(timeline+md+sql+actions+nav versions) ChatThread ChatEmpty
components/pages/            # FONDATIONS pages (Phase 3) : PageShell · EmptyState(état vide honnête) · SettingCard (+index.js). [AdminPanel.vue SUPPRIMÉ → logique portée dans AdminView]
composables/                 # useChatStream(polling→applyEvent) · timelineModel.js(REDUCER PUR: createAnswerState/applyEvent/answerText/timelineSignature) · useMarkdown · useTr · useClickOutside · useReducedMotion · useToasts
registries/                  # timelineSteps.js(eventKind→label, mergé i18n) · agentMeta.js(6 fiches + resolveAgentMeta par label) · faqContent.js(groupes Q/A statiques)
stores/                      # ui(SOURCE UNIQUE: thème+langue+contextMessages+sidebar, persistés) · prefs.js(PUR: clamps) · session(/me+/agents) · conversationList/conversationTree/agentPick(PURS) · chat(exchanges+turns=timeline; send/regenerate/branch)
test/                        # node:test PUR (hors src/, jamais buildé/zippé) : timeline · prefs · conversationTree · conversationList · agentPick (.test.js) (`npm test`, 27 tests)
router/index.js              # vue-router HASH ; chat + settings/feedback/faq/agents/project (vues dédiées) + admin(gardée) + help(placeholder) ; /→/chat
i18n/                        # index.js(createI18n legacy:false) + messages.json(327 clés, pristine) + langs.json + extra.js(chaînes Phase 3/4 mergées)
views/                       # ChatView · SettingsView · FeedbackView · FaqView · AgentsView(liste+détail) · ProjectView · AdminView(onglets) · PagePlaceholder(help)  [UiShowcase supprimée au cleanup L033]
assets/orange-logo.png
```
> Registres **prévus non encore créés** (Evidence, différé) : `registries/artifacts.js`, `registries/proofModes.js`, `stores/evidence.js`,
> `composables/useEvidenceCalc.js`, `components/evidence/`. L'aside Evidence est réservé dans `AppLayout` (grille `with-evidence`).

### 13.3 Statut par phase
| Phase | Contenu | Statut |
|---|---|---|
| **0-2 - Socle/Shell/Chat** | tokens+primitives `ui/`, AppLayout/Sidebar/MainTop+router hash+stores+i18n, chat polling+timeline | ✅ fait, **validé DSS** |
| **3 - Pages secondaires** | Settings/Feedback/FAQ/Agents/Project + fondations `components/pages/` (états vides honnêtes) | ✅ fait, **validé DSS** |
| **4 - Admin** | `AdminView` à onglets (`Tabs`) réutilisant la logique de `AdminPanel.vue` ; Quotas/Activity = états vides | ✅ fait, **validé DSS** |
| **5 - Build/package/DSS** | `/build-plugin` (197 modules) + `body.html` (Write) + `/package-plugin` + **test DSS** | ✅ fait, **validé DSS** (confirmation user) |
| **Audit sécurité pré-DSS** | workflow 6 dimensions adversarial → **GO** (0 critical/high/medium) + 4 correctifs backend | ✅ fait (L026) |
| **Evidence Studio** | document « preuve vivante » sur registres | ⏸️ différé (décision user) |

### 13.4 Décisions / conventions frontend (font foi)
- **Evidence Studio DIFFÉRÉ** : V1 = chat + conversations + admin + pages. Points d'extension réservés (registres).
- **Thème** light défaut + dark, swap `body[data-theme]` ; tokens manquants ajoutés en **no-op** (pixel-identique).
- **Conversations** : sidebar lazy via `/conversations` (liste paginée keyset, titre = 1er message) + `/conversation` (messages au clic) ; rename/delete/projets **non persistés** (pas d'API).
- **Versioning + branches = PERSISTÉS** (L032, ✅ DSS) : éditer/régénérer un prompt → échange **frère** via `parent_exchange_id` ; nav N/M **turn-level** ; contexte d'une branche = **chaîne d'ancêtres** (exclut l'après-branche) ; dernière branche restaurée au reload.
- **Picker agent** repeuplé depuis `/agents` (jamais codé en dur → sinon 404 `agent_not_enabled`).
- **Markdown agent** = seul chemin `v-html`, **sanitizé** (markdown-it HTML off + DOMPurify) ; reste en `{{ }}`.
- **i18n** : interpolation **liste** `t('k',[a,b])` ; données `{fr,en}` via `useTr()` ; catalogues domaine mergés (garder `messages.json` pristine).
- **Router HASH** (DSS sans réécriture SPA). **`reactive()`** obligatoire pour la version-réponse (L020). `:global` thème = sélecteur entier (**L022**).

### 13.5 Workflow de validation local (IMPORTANT)
- **Voir le rendu** : `npm run dev` (bg) → `http://localhost:5173/plugins/owismind/resource/owismind-app/` (+ `#/route`), screenshots via
  Chrome DevTools MCP (chemin **dans le repo**). En DEV, pas de backend → `window.__pinia.state.value.{chat,session}` pour injecter une démo.
- **Compile-check** : `./node_modules/.bin/vite build --outDir /tmp/owi_buildcheck --emptyOutDir` puis `rm -rf` - **ne JAMAIS builder dans
  `resource/`** avant la Phase 5 (sinon on écrase l'app déployée ; build officiel = `/build-plugin`).
- **Reste à faire avant DSS** : Phases 3-4, puis Phase 5 (`/build-plugin` recâble `body.html` - via **Edit**, le `cp` est refusé par le hook).
