# PROJECT_STATE - OWIsMind (mémoire longue)

> Référence canonique de l'état du projet. Mise à jour à la demande / en fin de session.
> En cas de conflit avec les guides de `docs/cadrage/` : **ce fichier + `LESSONS.md` font foi** (les guides
> sont des points de départ ; les noms réels et les solutions qui marchent vivent ici).
> Dernière mise à jour : **2026-07-07 - DEEP CLEAN sur branche `refactor/deep-clean-v1.2`** (L141-L143,
> NON mergée, à tester par l'user) : refactor zéro-comportement prouvé (AST / bundle normalisé / promote
> parity / revue adversariale 0 finding), `readonly_pre_queries()` consolidé (backend 788 -> **790** tests),
> setup Claude Code refondu pour Opus 4.8 (CONTEXT lean + `.claude/rules/` path-scopées + 4 subagents
> `.claude/agents/` + hook dash-guard), docs + project-documentation + site remis à niveau v1.1, READMEs
> racine/tools, zip prod repackagé sur la branche. Détail : `sessions/2026-07-07.md`.
> Avant : **2026-07-06 - PASSAGE EN PRODUCTION v1.1** (L139-L140, Run 5) : agents promus
> DEV -> PROD_V1 par régénération scriptée (`tools/promote_agents_to_prod.py`, idempotent : copie DEV +
> ids PROD + retrait du bloc `tickets_expert`) ; `plugin.json` 0.0.1 -> 1.1.0 + zip prod
> (`owismind-upload.zip`, 95 entrées, bundle `index-DDxpe_gw.js`) ; plugins dev supprimés du disque ;
> impersonation gardée pour la bêta ; tickets expert HORS PROD. **Repo PRÊT, RIEN encore déployé DSS** :
> suivre le runbook `docs/DEPLOY_PROD_V1_1.md`. Avant : **2026-07-06 Runs 2-4 - Source Data v3 VALIDÉ DSS**
> (popover filtres, mesures choisies, plages de dates sur colonnes string, cascade, persistance des vues,
> contexte écran -> agent). Détail : `sessions/2026-07-06.md` + `CONTEXT.md`.
> Antérieur : **2026-06-26 - NETTOYAGE REPO** (L108) : grand ménage (0 code touché). Supprimés :
> junk (16 `.DS_Store` + 31 `__pycache__`) + 56 fichiers suivis docs/scratch/maquettes (`docs/scaling/.workdir`
> + `project-documentation/.workdir`, `style-reference/`, `benchmark_webapp/mockup/`, plan orphelin
> `docs/superpowers/plans/`, `docs/screenshots/`, `docs/scaling/PLAN_*` -> dossiers `docs/scaling/` et
> `docs/superpowers/plans/` retirés). **Doc jamais supprimée** : `project-documentation/` + `docs/` gardés ;
> `project-documentation/` exclue du graphe (`.graphifyignore`) + note `CLAUDE.md` = hors contexte auto des
> agents, lisible à la demande (périmée, à MAJ future). 1132 tests verts. `docs/agentic-research/` gardée.
> Antérieur : **2026-06-14 - SKILL AGENTIQUE** : skill projet `.claude/skills/agentique-python-dataiku/`
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
> (Section gelée au 2026-06-10 : la suite du parcours vit dans CONTEXT.md + memory/sessions/.)
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
stop-génération, **Evidence Studio** = preuves SQL en table interactive). **Stockage chat = `webapp_chat_v5`** (v5 depuis 2026-06-11, + colonne mode 2026-07-02, L126).
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
| Plugin DEV v2 (3e coexistant, 2026-07-06) | id `owismind_dev_v2`, zip `owismind_dev_v2-upload.zip` (label "OWIsMind (DEV v2)", webapp "... (DEV v2)") - `tools/build_dev_plugin.py --v2` ; même pipeline, identité/staging/zip dédiés ; créé pour livrer les data tools sans toucher le dev stable pré-démo | repo |
| Source de build DEV | UNE source `Plugin/owismind/` ; base Vite via env `OWI_PLUGIN_ID` (défaut `owismind`) ; package python renommé `owismind`->`owismind_dev` au packaging (L094) ; tables = create-if-not-exist, isolation = `table_prefix` optionnel au déploiement | repo |
| Connexion SQL | `SQL_owi` (PostgreSQL, schéma `public`) | guide SQL |
| Project key DSS | `OWISMIND_DEV` (résolu via `dataiku.default_project_key()`, **reste la référence du repo**) ; variante test `OWISMIND_LAB` ; **projet PROD parallèle `OWISMIND_PROD_V1`** (table physique `OWISMIND_PROD_V1_drive_revenues` ; migration via `OWISMIND/migrate_semantic_model_to_project.py` qui dérive le remapping des clés - sinon Evidence dégradé, L090) | guide SQL ; 2026-06-18 |
| **Agents DUPLIQUÉS PAR PROJET (2026-06-22, L099)** | Le dossier `dataiku-agents/` est réorganisé en `OWISMIND/{OWISMIND_DEV, OWISMIND_PROD_V1}/`, **une copie complète et auto-suffisante par projet**, tous les fichiers déployables **préfixés** par le projet. **On développe en DEV, on valide, puis on promeut en PROD** (copier le changement dans le jumeau `OWISMIND_PROD_V1_*`, IDs prod déjà câblés). Carte des IDs + workflow = **`dataiku-agents/OWISMIND/README.md`** + chaque `registry.json`. Tests = contre les copies **DEV** | repo ; `OWISMIND/README.md` |
| IDs agents/tools/modèles **DEV** | orchestrateur `038G7mlF` · revenue `agent:bHrWLyOL` · tickets `agent:NcE9LD2i` (en cours) · attribute_lookup `UUoynaL` · revenue_semantic_query `v4oqA6R` · tickets_semantic_query `nEirlso` · modèle revenus `AHUh9hb` (`Drive_Revenues_Semantic_Model`) · modèle tickets `dM4jA4G` (`TroubleTickets_Semantic_Model`) | `OWISMIND/OWISMIND_DEV/registry.json` |
| IDs agents/tools/modèles **PROD** (revenus seulement, tickets pas encore promu) | orchestrateur `Xrv7GvfG` · revenue `agent:uO5hEzAs` · attribute_lookup `szOZCoU` · revenue_semantic_query `sgk5pfln` · modèle revenus `a7K9jYk` (**`Drive_Revenues_Model`**) | `OWISMIND/OWISMIND_PROD_V1/registry.json` |
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

## 4. Structure réelle du plugin (`Plugin/owismind/`) - (snapshot, ré-établi 2026-07-03)

```
Plugin/owismind/
├── plugin.json                 # id="owismind" (racine du zip - PAS de _/plugin.json)
├── frontend/                   # source Vue 3 + Vite (JAMAIS dans le zip ; build -> resource/)
│   └── src/                    # dirs : assets components composables features i18n
│                               #        registries router services stores styles views (détail -> §13.2)
├── python-lib/owismind/        # backend Flask modulaire (mis sur le path d'import par DSS)
│   ├── __init__.py
│   ├── api/                    # routes.py : Blueprint /owismind-api, TOUTES les routes REST
│   ├── agents/                 # dialogue LLM Mesh : streaming, stream_manager (polling), context multi-tours, discovery
│   ├── storage/                # SQL direct PostgreSQL : chat_v5, usage, budget, settings, admin,
│   │                           #   events (analytics), suggestions, artifacts, chat_traces, migrations, sql_config/builders
│   ├── evidence/               # Evidence Studio + trust layer + Source Data Explorer + artefacts :
│   │                           #   service, capture, sql_explain/parse, chart_payload, source_service/search, throttle
│   ├── security/               # identity (auth DSS), validation (payloads), impersonation (admin read-only)
│   └── benchmark_view/         # consultation benchmark côté plugin : view-models purs + lecture SQL cross-projet du LAB
├── resource/owismind-app/      # ASSETS BUILDÉS par Vite (généré - NE PAS éditer ; index.html + assets/index-<hash>.{js,css})
└── webapps/webapp-owismind-ai-agents/
    ├── webapp.json             # baseType=STANDARD, hasBackend=true, libs [jquery,dataiku], params []
    ├── backend.py              # bootstrap : from owismind.api.routes import register_routes; register_routes(app)
    ├── body.html               # entrée DSS = copie du index.html buildé (assets câblés)
    └── app.js / style.css      # slots STANDARD vidés (commentaire) - JAMAIS supprimés (DSS les exige)
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
    `{events,cursor,done,error}` ; owner-scopé) - **POLLING-via-thread, ✅ validé DSS** ; écriture 2 temps dans `chat_v5`.
    Le worker assemble le **contexte multi-tours = chaîne d'ancêtres** de `parent_exchange_id` (`history_messages_for_chain`)
    + préfixe **nom+date** sur le tour courant (L030/L032). `history_limit` = nb messages, clamp `[10,50]`.
  - **`chat/stop`** (POST `{run_id}` → `stream_manager.request_stop`, **owner-scopé** ; pose `stop_requested` →
    worker `break` (LLM Mesh **sans API cancel** → cesser d'itérer) + persiste le partiel + event terminal `stopped` ≠ error) - L034, ✅ DSS.
  - **`chat/feedback`** (POST `{exchange_id, rating(0|1|null), reasons[], comment}` → `chat_v5.save_feedback`,
    **owner-scopé** ; `validate_feedback` whiteliste les raisons, borne le commentaire, rejette `True/False`) - L031.
  - **`conversations`** (GET `?cursor=&limit=` → `{conversations:[{session_id,title,last_at}], next_cursor, has_more}` -
    **noms seuls**, pagination **keyset** ; `build_conversation_list_query`) + **`conversation`** (GET `?session_id=` →
    `{rows:[…échanges incl. parent_exchange_id + feedback]}`, chronologique, borné, chargé **au clic**) - L030/L032.
  - `history` (GET, filtré `user_id`, LIMIT 200, lit `chat_v5` ; **legacy - plus appelé par le front** depuis la sidebar lazy).
    **`chat/trace`** (GET) **supprimé** (trace = dataset Flow write-only, L027/L028). _(`/chat` MOCK + `/chat/stream` SSE supprimés.)_
  - `agents` (GET, **user** - `{key,label}` only, clés logiques opaques ; jamais d'`agent_id`).
  - `admin/storage`, `admin/users`, `admin/users/set-admin`, `admin/projects`, `admin/projects/<key>/agents`,
    `admin/agents` (GET+POST) - **gardées serveur** par `_admin_guard`.
- Modules backend : `security/{identity,validation}.py` (validators : `validate_history_limit`/`validate_feedback`/
  `validate_optional_exchange_id`/`validate_conversations_limit` ; `derive_full_name`), `storage/{chat_v5,chat_traces,admin,settings,
  migrations,sql_config,serialization,sql_builders,pagination}.py` (**purs sans dataiku** : `sql_builders` = `build_ancestor_chain_query`/
  `build_conversation_list_query`/`build_session_messages_query` ; `pagination` = cursor encode/decode),
  **`agents/{discovery,streaming,stream_manager,context}.py`** (`context` = pur : prefix/flatten/SQL-contexte ; `streaming.run_agent_streamed(…, messages)` multi-tours),
  `resource/compute_available_connections.py` (dropdowns connexion + dataset traces).
  ⚠️ `chat_v1/v2/v3.py` **supprimés au fil des bascules** (table COURANTE = `chat_v5.py`) ; `run_events.py`/`history_messages_for_session`/`build_session_history_query` supprimés (code mort).
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
- **Table chat COURANTE = `webapp_chat_v5`** (créée Run 4 2026-06-11, L049 ; ✅ en service DSS et validée au fil des
  sessions suivantes ; + colonne `mode` VARCHAR(16) nullable 2026-07-02, L126 ; module `storage/chat_v5.py`,
  ex-`chat_v4.py` `git mv`) :
  - Colonnes : `exchange_id` PK, `session_id`, `user_id`, `user_display_name`, `user_groups`, `user_text`,
    `assistant_text`, **`generated_sql`** (JSON liste `{sql,success,row_count}`, nullable - L019/v2),
    `agent_key` (**clé logique opaque**), `created_at`, `answered_at`, **`feedback_rating` SMALLINT (0|1|NULL)** +
    **`feedback_reasons` TEXT(JSON)** + **`feedback_comment` TEXT** + **`feedback_at` TIMESTAMP** (L031/v3),
    **`parent_exchange_id` TEXT** (arbre de conversation - L032/v4), **`input_tokens`/`output_tokens`/`total_tokens` INT +
    `estimated_cost` DOUBLE** (usage de l'échange, nullables - L049/v5, écrites dans le MÊME UPDATE que la réponse =
    **source de vérité** des agrégats), **`mode` VARCHAR(16) nullable** ('smart'|'pro'|'claude'|NULL, stampé serveur à
    `/chat/start` via `resolve_effective_mode`, ajouté par **ALTER ADD COLUMN IF NOT EXISTS** = relaxation sanctionnée
    L126, exposé par `/conversation`, affiché dans la ligne usage - ✅ VALIDÉ DSS 2026-07-02 Run 6 ; le mode est
    ÉPHÉMÈRE côté front : Smart par défaut, reset à l'envoi, plus de persistance localStorage).
    Index `(user_id, created_at DESC)` + `(user_id, session_id, created_at DESC)`.
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
    d'affichage **rédigée par l'admin** (tagline/description/capabilities/tools/icon/badge **+ `modes`**,
    booléen 2026-06-24/L101), validée+bornée serveur par `validate_agent_meta` (pur, ne lève jamais ;
    whitelist icônes = registre front) et **stockée DANS ce JSON, PAS de nouvelle table**. Le flag
    **`modes`** (défaut OFF) indique que l'agent gère le sélecteur de modes Smart/Pro/Claude : `/agents`
    l'expose, le front masque le picker si OFF, et **`/chat/start` ne relaie le token `⟦owi:mode=…⟧` que si
    `profile.modes`** (sinon aucun token, plus de fuite chez un agent visuel). Via `storage/settings.py`.
    Voir L017 + L091 + L101. **`profile.benchmark`** (2026-06-29/L111) = bloc `{enabled, connection, table,
    agent_key}` validé/borné par `validate_agent_meta` (table invalide -> "") qui relie un agent à SA table
    `scored` (le LAB), lue en cross-projet par le plugin pour la consultation. `/agents` n'expose que
    `has_benchmark` (jamais la table/connexion). **Package PUR `python-lib/owismind/benchmark_view/`**
    (`schemas` effective_correct, `aggregate` view-model consultation, `schema_check`, `agent_profile`,
    `lab_io` lecture/UPDATE SQL cross-projet) = côté LECTURE du benchmark dans le plugin (modules purs
    portés du LAB, source de vérité = `OWIsMind_LAB/`). Plugin = **consultation seule**, pas de launcher.
    **Détail complet à la demande (2026-07-01/L117)** : la liste lit LIGHT (colonnes lourdes droppées) ;
    au dépli d'une question, route `GET /benchmark/attempt` (tous users) -> `lab_io.read_scored_row_full`
    (`SELECT` paramétré 1 ligne, colonnes lourdes intersectées au schéma live) -> `aggregate.full_detail_view`
    (parse `generated_sql_json`) = **réponse complète + SQL réellement généré par l'agent + tableau capturé**.
    Côté LAB, mêmes vues (`views.full_detail_view` + `dss.read_scored_row_full` via `iter_rows`) exposées par
    `/api/results/attempt` (results) et `/api/review/attempt` (launcher Review, pour décider l'override).
- **Connexion configurable** (plus de hardcode) : params webapp `sql_connection`/`table_prefix`/`log_level`
  (`hideWebAppConfig=false`), lus via `get_webapp_config()`. ⚠️ dropdown Settings KO (L012) → champ texte.
  Nommage `{PROJECT_KEY}_{prefix-}owismind_{logical}` (préfixe optionnel après le project key).
- Tables futures (cahier) : `_messages`, `_runs`, `_run_events`, etc. (toujours `_vN`, jamais d'ALTER).

## 8. Agents & streaming

- **✅ VALIDÉ DSS 2026-07-02 Run 2 - artefacts natifs + narration + recall** (commits user
  `0368dd7`/`0275ae9`) : (a) **artefacts** : le panneau empile TOUS les charts/KPIs ; spec chart
  étendue (`x_label`/`y_label`/`unit` dans le bloc chart ; `description` + `sql_id` top-level,
  additif) ; **binding par artefact** via `sql_id` (stampé par l'orchestrateur `latest_sql_id`,
  résolu par `evidence/service.results_by_sql_map` - ids ambigus exclus - dans `/evidence/meta` ;
  stampé-mais-manquant = payload vide honnête, non-stampé = repli actif legacy ; table bindée
  aussi) ; step bumpé après fan-out = `sql_id` uniques par échange ; dédup specs identiques dans
  `storage/artifacts._sanitize`. (b) **Tools orchestrateur nouveaux** : `tell_user` (smart
  seulement, narration-as-tool anti narrate-and-stop, 2 notes/batch) et `recall_prior_result`
  (exposé seulement si le backend a fourni des résultats rappelables). (c) **Protocole jeton
  `⟦owi:prior=json⟧`** (L119) : backend `chat_v5.chain_context_for_agent` (même lecture que
  l'historique) + `context.extract_prior_results` (3 derniers tours, dédup signature sql+colonnes)
  + `context.build_prior_data_block` (index [PRIOR DATA] + jeton borné dur 24k) ; gate = flag
  profil `modes` (routes -> `start_run(prior_recall_enabled=...)`) ; côté agent : parse AVANT
  `parse_mode`, last-token-wins, flag d'état `recalled` pour les filets de `node_finish`.
  (d) Filet narrate-and-stop : regex prospective, garde `?`, cap 480c, `_MAX_NUDGES=2`.
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
- **2e SOUS-AGENT "tickets" + factory repo (2026-06-19 Run 4, ✅ testé DSS « marche plutôt bien », à pofiner -
  L097/L098)** : expert incidents sur `TroubleTickets_year` (83 738 l., 21 col.). `agents/TroubleTickets_expert.py`
  = copie du moteur revenus, **corps byte-identique** (contrats gelés), seuls l'en-tête CONFIG + les textes
  hiérarchie-d'offre (neutralisés) diffèrent. Orchestrateur : **1 entrée `CAPABILITIES["tickets_expert"]`**
  (domaine `tickets`, déjà dans `BUSINESS_DOMAINS`) + champ `lookup_search_columns` (allowlist de recherche par
  domaine, passée serveur). `tools/attribute_lookup_tool.py` : `searchable_columns` + domaine générique `value`.
  **Modèle sémantique DÉDIÉ par domaine** (jamais une source ajoutée au modèle revenus) ; scripts
  `tools/semantic_model/update_tickets_semantic_model.py` + `dump_tickets_semantic_model.py` ; tool DSS attendu
  `tickets_semantic_query` (Agent OFF, Sonnet). **3 recipes rendues génériques (auto-IO) + NA-safe** (fix
  `infer_with_pandas=False` -> fallback `True` sur int nullable) ; `build_value_catalog_recipe` dataset-adaptatif
  (revenus curé inchangé ; non-revenus = catalogue générique). **Factory repo (source de vérité scaling)** :
  `dataiku-agents/registry.json` (spec par domaine, dev-owned, jamais runtime) + `DATASETS.md` (inventaire
  colonnes) + `PLAYBOOK_ADD_AGENT.md` (runbook). Test anti-dérive **généralisé** à tous les caps. **À finaliser
  DSS** (PLAYBOOK) : override métrique COUNT, modèle sémantique, tool, Code Agent + `agent_id` réel, re-coll
  orchestrateur (pas de zip). Datasets : `TroubleTickets_year` + `_profile` + `_value_index` (sur `SQL_owi`) +
  `_value_catalogue`. Débloque la fiche client 360 (pont `Account_name`/`Customer_id`). Détail → `sessions/2026-06-19.md` Run 4.
- **Audit + durcissement des agents (2026-07-02 Run 1, L118, repo DEV)** : 20 findings confirmés
  implémentés (orchestrateur, expert revenus, cerveau sémantique, tool lookup) ; contrat `AMBIGUOUS TERM`
  porté agent + modèle sémantique ENSEMBLE (`update_aligned_semantic_model.py`). Détail → `sessions/2026-07-02.md` (Run 1).
- **Promotion DEV -> PROD_V1 scriptée (2026-07-06 Run 5, L139)** : `tools/promote_agents_to_prod.py`
  (idempotent : copie DEV + substitution des ids PROD + retrait chirurgical du bloc `tickets_expert`)
  régénère les fichiers PROD ; JAMAIS d'édition manuelle d'un fichier PROD. Ids PROD : orchestrateur
  `Xrv7GvfG`, revenue expert `agent:uO5hEzAs`. Détail → `sessions/2026-07-06.md` (Run 5) + `dataiku-agents/OWISMIND/README.md`.

---

## 8c. Système de benchmark / évaluation des agents (2026-06-25, ⏳ matrix ✅ DSS / juge non re-validé)

> 📁 **Emplacement repo (réorg 2026-06-26)** : tout le benchmark vit désormais sous **`OWIsMind_LAB/`** (miroir
> du projet DSS séparé). `benchmark/` -> `OWIsMind_LAB/project-library/python/benchmark/` ; `benchmark_webapp/`
> -> `OWIsMind_LAB/project-library/python/benchmark_webapp/` (lib `views.py`+`dss.py`) ; les panes web ->
> `OWIsMind_LAB/webapps/{benchmark_launcher, benchmark_results}/` ; variable -> `OWIsMind_LAB/local-variables.example.json`.
> **Packages inchangés** (`from benchmark ...` / `from benchmark_webapp ...`), zéro recoll DSS. Carte : `OWIsMind_LAB/README.md`.
> Tests : `python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python`. Voir **L109**.
> (Les chemins `benchmark/...` / `benchmark_webapp/...` cités plus bas dans 8c/8d = anciens, lire sous `OWIsMind_LAB/...`.)
>
> 🆕 **v2 APPEND MODE (2026-06-30, L113, ⏳ NON validé DSS)** : un benchmark = campagne **NOMMÉE unique
> par agent** (`benchmark_id`+nom), les runs **s'accumulent** (relancer ne joue que les questions pas
> faites ; score global = **dernière tentative** par question via `scoring.latest_attempts`). Registre +
> appartenance des questions + drapeaux « refaire » dans la **variable projet `benchmark`** (`benchmarks`
> map + `run_request`) -> **0 dataset neuf** ; module PUR `benchmark/registry.py`. Colonnes additives :
> `benchmark_id`/`benchmark_name`/`attempt_no` (raw+scored), `expected_sql`/`expected_tool` (golden+raw+
> scored, **signal doux au juge** + affichées), `actual_tools` (scored). **SUMMARY/BREAKDOWN keyés par
> `benchmark_id`** (plus `run_id`), 1 bloc par benchmark, merge par benchmark_id. Results LAB + consultation
> plugin sélectionnent **par benchmark** + évolution + attendu vs réel ; `lab_io.read_scored` lit
> l'intersection des colonnes (rétro-compat tables v1). Launcher : onglet **Benchmarks** (créer/ouvrir/
> lancer ; 3 boutons append/full/new ; toggle redo) ; lancement global retiré. Override = par tentative
> (run_id de la ligne). À déployer : recoller lib+webapps LAB + variable (`benchmarks:{}`,`run_request:null`)
> + upload DEV + redémarrer backend ; un run frais matérialise les colonnes. Détail : `sessions/2026-06-30.md`.

But : mesurer précision (taux de bonnes réponses), latence, coût, tokens **par agent ET par mode**, restitution
lisible. **Archi (spec `docs/superpowers/specs/2026-06-24-agent-benchmark-evaluation-design.md`)** : projet DSS
dédié **`OWIsMind_LAB`** (assaini) + scénario **`Run_Benchmark`** (3 steps Python) + **librairie partagée**
(package repo **`benchmark/` = source de vérité**, recollé en project-library, comme les Code Agents). On appelle
l'orchestrateur **direct via Mesh** (`get_project(project_key).get_llm(agent_id).execute_streamed()`) et on
reconstruit la **réponse COMPLÈTE** (texte + SQL + lignes + artefacts) depuis le **footer trace** - PAS le chemin
webapp HTTP (isolé, prod-safe, vraie latence agent).

- **Package `benchmark/`** : `agent_capture.py` (clé ; réimplémente la capture de `streaming.py` +
  `evidence/capture.py` ; `assemble_full_answer` = la seule chaîne vue par le juge), `schemas.py` (golden **lean
  9 col**, RAW/SCORED/SUMMARY/BREAKDOWN, `BREAKDOWN_DIMENSIONS=("category",)`), `config.py` (modes
  **Smart/Pro/Claude** ; token interne **eco/medium/high** traduit par `build_mode_token` ; `JUDGE_LLM_ID` = Sonnet ;
  `build_plain_message`), **`run_params.py`** (résolveur de config UNIQUE), `judge.py` (**ancre objective
  déterministe** numeric/currency/date/string/list + **juge LLM structuré** `with_json_output` + `final_correctness`
  + `needs_review` sur désaccord), `scoring.py` (`summarize`/`breakdown`, percentiles), `agent_runner.py`
  (`expand_matrix`/`run_one`/`run_matrix` ; concurrence bornée ; erreurs = lignes), `dss_steps/`
  (`step_run_matrix`/`step_judge`/`step_aggregate`). Tests : **173 verts** (`python3 -m unittest discover -s
  benchmark/tests`), NO INSTALL (modules purs stdlib-only ; pandas/dataiku lazy). Doc : `SETUP_GUIDE.md` (4
  étapes), `README.md`, `GOLDEN_IMPORT_PROMPT.md` (prompt IA interne -> golden).
- **Config = UNE variable projet `benchmark`** (section Local variables ; le scénario n'a pas d'onglet Variables) :
  `golden_dataset` (défaut `golden_questions_v1_prepared`), `agents` (liste `{agent_key,agent_label,project_key,
  agent_id,modes}`), `modes`, `language`, `concurrency`, `question_filter`, datasets de sortie, `judge_llm_id`,
  `score_all_runs`/`aggregate_all_runs`. **Zéro hardcode** (noms de datasets inclus). **Flag `modes` PAR agent** :
  `true` = testé sur chaque mode + token ; `false`/absent = **1 appel simple, mode `default`, sans token** (visual agents).
  - **`agents` = catalogue curé, alimenté par le launcher SANS code** (flux « Ajouter un agent » : choisir un
    projet -> `dss.list_project_agents` liste les `list_llms` `agent:` (id+nom) -> cocher -> `connect_agents` upsert
    dans la variable ; retrait via `remove_agent_from_catalog`). Découverte **read-only bornée** (MAX_PROJECTS/AGENTS).
    **`agent_key` = l'agent_id** (préfixe `agent:` retiré), jamais un slug (L115) : `registry.agent_catalog_key`/
    `normalize_agent`/`parse_agents`/`upsert_agents`/`remove_agent`/`serialize_agents` (purs). (2026-07-01.)
- **Datasets managés** (dans `OWIsMind_LAB`) : `golden_questions_v1` -> (recette prepare) -> **`golden_questions_v1_prepared`**
  (lu) -> `benchmark_runs_raw` -> `benchmark_runs_scored` (= détail) -> `benchmark_summary` + `benchmark_breakdown`.
  Schémas pensés **compatibles SQL `benchmark_*_v1`** pour une future section webapp.
- **Cible** : orchestrateur **DEV `agent:038G7mlF`** (cross-projet via `project_key=OWISMIND_DEV`, **pas de préfixe
  dans l'id** ; condition = droits du compte d'exécution sur l'agent). PROD = `agent:Xrv7GvfG` (promotion future).
- **État** : ✅ **step matrix validé DSS** (capture complète fonctionne) ; ⏳ step **Judge corrigé du crash NaN
  (L102)** + run complet + summary/breakdown + dashboard = **NON re-validés DSS**. Commits poussés origin/main
  `6eb1cb4`..`b4b3816`. Détail → `sessions/2026-06-25.md`.

## 8d. Intégration benchmark dans le système - 2 pôles (2026-06-26, ⏳ repo only, NON validé DSS)
**Archi (spec `docs/superpowers/specs/2026-06-25-benchmark-integration-design.md`)** : les 2 pôles vivent à des
endroits DIFFÉRENTS, ce qui tranche le choix de techno.
- **Pôle utilisateur (capture) = DANS le plugin Vue** (produit). Nouvelle table owner-stamped
  **`webapp_golden_suggestions_v1`** (superset du golden lean-9 ; `storage/suggestions.py`,
  `chat_v5.read_exchange`, validateurs, 3 routes `POST /benchmark/suggest`, `POST /benchmark/suggest-from-chat`,
  `GET /benchmark/suggestions` ; 2 WRITE bloquées en impersonation). Front : action menu « ... » -> page
  **`/benchmark` (TOUS users, pas de garde admin)** = `BenchmarkSuggestView` (bi-mode chat/manuel + « mes
  suggestions »), `stores/benchmark.js`. `sql_config.safe_index_name` (length-safe, **L103**).
- **Pôle admin (révision 2026-06-26b) = DEUX webapps DSS STANDARD séparées dans `OWIsMind_LAB`**, PAS le plugin
  (zéro Vite/zip/restart). Package repo **`benchmark_webapp/`** (source de vérité ; recollé en project-library) :
  **`views.py`** (PUR, testé) + **`dss.py` = chokepoint UNIQUE I/O dataiku/SQL** (« READ + APPEND only » : SELECT
  seul sur la connexion partagée ; écritures = append Flow via Dataset API ; verrous promotion/lancement). Deux
  dossiers = deux webapps standard (4 panes chacune) : **`results/`** (consultation **publique, lecture seule**,
  restitution langage clair grand public, verdict « X sur Y », donut de confiance) et **`launcher/`** (config
  **VRAI formulaire** -> `build_config_object` préserve datasets/juge/suggestions + lancement async single-flight
  + revue/promotion des suggestions). **Les deux bilingues EN défaut + FR** (i18n JS, nombres localisés). « Déjà
  promu » dérivé du **golden (source de vérité)**, pas d'un log corruptible (L104). Montage : `benchmark_webapp/README.md`.
  **Prérequis : `golden_dataset` = dataset managé autonome (pas de recette en amont).**
- **Config** : bloc additif **`benchmark.suggestions`** = `{connection: "SQL_owi", table: "<nom physique exact de
  webapp_golden_suggestions_v1>", promoted_dataset: "benchmark_suggestions_promoted"}` (vide -> onglet Suggestions
  « non configuré »). Le nom physique exact est exposé par Admin > Storage (`golden_suggestions`).
- **État** : 681 tests Python + 124 node ; build Vite OK ; **QA visuelle Playwright** du webapp LAB (clair+sombre) ;
  revue adversariale 4-dim **0 crit/0 high** (corrigés + tests) ; 0 tiret. **DEV packagé** (`index-BoETXxLb.js`,
  72 entrées), prod intacte. **NON validé DSS** (upload DEV + créer la webapp standard en LAB). Détail →
  `sessions/2026-06-26.md`, **L103**.

---

## 8e. Source Data Explorer - exploration des datasets bruts des agents (2026-07-02, ✅ VALIDÉ DSS)

- **But** : les users voient/exploren les données que les agents manipulent (anti « outil magique »),
  pour des prompts précis. Spec : `docs/superpowers/specs/2026-07-02-source-data-explorer-design.md`.
- **Config** : bloc `sources` [{dataset,label}] (max 8) dans le profil d'agent (`validate_sources_block`,
  `security/validation.py`) ; admin le remplit sur la fiche (AdminView, datalist `/admin/sources/datasets`).
- **Backend** : routes read-only `/source/meta|rows|distinct` (`evidence/source_service.py`, garde =
  miroir `_evidence_guard` sans ensure_chat_table + throttle + timeout 30s + read-only) ; recherche
  accent/casse-insensible = 1 ILIKE sur `concat_ws` de toutes les colonnes via `translate()` (module
  PUR `evidence/source_search.py`) ; `q` aussi sur `/evidence/rows` ; **contrat limit/offset** (limit
  1..100 déf 50, offset 0..500, clamp jamais d'erreur, réponse `{rows,has_more,offset}`) ; `/agents`
  sources = `[{id,label,dataset}]` (dataset display-only, jamais accepté en paramètre).
- **Frontend** : `stores/sources.js` + `composables/sourceModel.js` + `components/sources/*`
  (SourcePanel/SourceExplorer/SourceChips/SourceTable) ; CTA sur ChatEmpty (agent du picker) ;
  panneau droite partagé avec Evidence (mutual exclusion, grille `rightOpen`) ; onglet Evidence
  **Source data** = `EvidenceSourcesTab.vue` (sélecteur fusionné tables détectées legacy
  chips+drill+recherche / datasets configurés de l'agent de l'ÉCHANGE via `exch.agentKey` +
  `chat.agentKeyForExchange`) ; recherche Entrée/bouton only ; 100 lignes puis +20 (cap 500) ;
  30 colonnes puis +20 ; pleine hauteur ; sélection persistée `evidence.sourceTabKey`.
- **État** : ✅ validé DSS par l'user (v1 `030689b` + v2). 576 tests back + 147 node. Leçons **L121-L122**.
- **Run 4 (2026-07-02, ✅ VALIDÉ DSS, arc 1 commité user `a2754ca`)** : filtres cherchables (add
  2 étapes, filtre client via `sourceModel.foldSearchTerm` = map d'accents VERBATIM du serveur,
  **recherche serveur sur Entrée** = param optionnel **`q` sur `/source/distinct` + `/evidence/distinct`**,
  flag `serverFiltered` commité à l'atterrissage, `pickerError`, footer Annuler/Appliquer, chips
  Evidence carrées) ; **cell-to-agent** : clic cellule (SourceTable + EvidenceTable) ->
  `CellActionPopover` (**Teleport body**, L123) -> store `promptContext` (modèle pur
  `promptContextModel`, caps 12 valeurs/200 chars, dédup) -> chips dans PromptBar -> bloc
  « Contexte de données : / Data context: » appendé au message à l'envoi (frontend-only, message
  stocké brut = rejoué) ; purge sur changement de session/agent pré-conversation ;
  **`ui/DataLoader.vue`** = overlay de chargement charté (bar-chart carré, 1 barre orange,
  fade-in 150ms, reduced-motion) sur les 2 tables, dim busy déplacé sur les enfants.
  163 node + 582 back. Leçons **L123-L124**.

---

## 8f. Analytics d'usage - `webapp_events_v1` + `POST /track` (2026-07-02, ✅ VALIDÉ DSS)
- **But** : tracking GA4-like de l'usage de la webapp (fréquentation, features, parcours), distinct des
  logs agentiques. **1 table brute unique** `webapp_events_v1` (SQL_owi ; décision : PAS folder/S3 comme
  l'ancienne webapp Dash, dont le 1-fichier-JSON-par-event s'est avéré la faiblesse principale).
- **Schéma** : `event_id` PK (uuid client, dédup ON CONFLICT), `ts` (serveur), `client_ts`, `seq`
  (ordre intra-session), `user_id` (résolu serveur), `app_session_id` (uuid par chargement),
  `event_name`, `event_category`, `view_name` (VIEW = mot réservé PG), `conversation_id`, `agent_key`,
  `mode`, `props` TEXT (JSON cappé 2000c). Index `(ts)`, `(user_id,ts)`, `(event_name,ts)`,
  `(app_session_id,seq)`.
- **Backend** : `storage/events.py` (**EVENT_CATEGORIES = whitelist source de vérité, 38 noms**,
  `validate_events` pur never-raises, `record_events` 1 INSERT multi-lignes + COMMIT best-effort) ;
  route `POST /track` (batch <=40, get_json force+silent pour sendBeacon, **impersonation = drop avant
  write**, throttle dédié 12/0.5 par s, jamais de 500) ; DDL dans `migrations.py`.
- **Frontend** : `services/trackModel.js` (pur : whitelist miroir, queue 200, drain 40, limiteur 10
  events d'erreur/session) + `services/track.js` (flush 5s/20, sendBeacon pagehide, no-op en
  impersonation) ; hooks minces dans router afterEach + stores (chat/ui/session/evidence/sources/
  promptContext/benchmark) + MessageAgent (feedback) + tables (cell popover) + main.js (erreurs) +
  backend.js (`error_backend`, path SANS query string = L125, hors /track et /chat/poll).
- **Taxonomie (38 events auto-descriptifs, validée user)** : nav `webapp_opened`/`page_viewed` ; chat
  `question_sent`/`answer_received {duration_ms}`/`answer_stopped`/`question_edited`/
  `answer_regenerated`/`answer_version_switched`/`conversation_created`/`conversation_opened`/
  `cell_value_added_to_prompt`(+removed) ; ui `mode_changed`/`agent_changed`/`theme_changed`/
  `sidebar_toggled` ; evidence `evidence_panel_opened`(+closed)/**`chart_viewed`/`table_viewed`/
  `kpi_viewed`/`source_data_viewed`/`evidence_proof_viewed`** (onglets = events de 1er rang, fallback
  `evidence_tab_viewed {tab}`)/filtres/`evidence_row_drilled`/`evidence_searched {len}` ; source
  `source_explorer_opened`/`source_dataset_switched`/filtres/`source_searched {len}`/
  `source_cell_clicked` ; `feedback_submitted`/`benchmark_suggestion_sent`/`error_frontend`/
  `error_backend`. Privacy : longueurs seules pour les recherches, paths sans query string.
- **Exploitation** : dataset SQL Dataiku direct sur la table ; sessions = gap 30 min sur
  `(user_id, ts)` ; parcours = `app_session_id` + `seq` ; rollups par recette planifiée (hors runtime).
- **État** : ✅ VALIDÉ DSS (2026-07-02, v1 + taxonomie renommée). 614 back + 184 node, parité
  whitelist 38/38 vérifiée par script, revue adversariale 12 Opus (1 HIGH corrigé = L125), zip DEV
  `index-D-NkcYpc.js`. Dashboard d'adoption = à construire. Détail -> `sessions/2026-07-02.md` Run 5.

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

Historique par session : memory/sessions/*.md.

| Sous-système | État | Dernière validation DSS | Référence |
|---|---|---|---|
| Chat multi-tours + arbre de conversation (branches, agent persistant, stop) | ✅ Validé DSS | 2026-06-09 | L030/L032/L034 |
| Storage chat `webapp_chat_v5` (usage tokens/coût + colonne `mode`) | ✅ Validé DSS | 2026-07-02 (Run 6) | L049/L126 |
| Evidence Studio v1 (rejeu du SELECT read-only, table + chips) | ✅ Validé DSS | 2026-06-10 | L035-L037 |
| Trust layer Evidence v2 (badge, `sql_explain`, capture, drill) | 🟡 Déployé, fonctionne ; ajustements user à recueillir | 2026-06-11 | L044/L045 |
| Artefacts natifs (charts / KPI / tables, binding par artefact) | ✅ Validé DSS | 2026-07-02 (Run 2) | L119-L120 |
| Modes Smart/Pro/Claude + mode éphémère (par réponse) | ✅ Validé DSS | 2026-07-02 (Run 6) | L101/L126 |
| Budget / quotas 50 $/mois (`webapp_user_quota_v1`) | ⏳ Codé, non validé DSS | - | `storage/budget.py` (2026-06-18) |
| Analytics d'usage `webapp_events_v1` (+ `POST /track`) | ✅ Validé DSS | 2026-07-02 (Run 5) | L125 |
| Source Data Explorer (admin + panneau + onglet Evidence + cell-to-agent) | ✅ Validé DSS | 2026-07-02 (Runs 3-4) | L121-L124 |
| Data tools sans IA - agrégats DB (`/source/aggregate` + `/evidence/aggregate`, zone Calculer, plages BETWEEN, médiane, factory `aggregateSurface`) | 🟡 Vague 1 validée DSS sur dev_v2 ; vagues 2+3 validées local (QA runtime + 3 revues), zip final dev_v2 à uploader | 2026-07-05 (vague 1, user) | L132-L133 (`sessions/2026-07-06.md`) |
| Source Data v3 (Run 2 : backdrop popover, mesures choisies `calcFns`, plages sur colonnes string, cascade distinct POST, persistance des vues `sourceViewMemory` ; Run 3 : bornes MIMANT le format des valeurs L138, « Filtrer sur cette valeur » depuis la cellule ; Run 4 : filtre-cellule PARTOUT avec toasts + `ColumnMenu` par en-tête (tri 3 états `nextSortDir`, Filter pré-réglé via `requestColumnFilter`) + colonnes filtrées orange) | ✅ Validé DSS sur dev_v2 (user : « tout marche super ») | 2026-07-06 (Runs 2-4, zip `index-DYvX83Tl.js`) | L134-L138 (`sessions/2026-07-06.md` Runs 2-4) |
| Contexte écran -> agent (bandeau consentement, `screen_context.source_state` -> section SOURCE-DATA VIEW du bloc `[ON SCREEN NOW]`, events 41 ; Run 3 : TRANSPARENCE : colonne `screen_ctx` sur chat_v5 + chip cliquable + ligne persistée sous le message) | ✅ Validé DSS sur dev_v2 (orchestrateur DEV recollé ; PROD `Xrv7GvfG` pas encore porté) | 2026-07-06 | L134/L136/L138 (`sessions/2026-07-06.md` Runs 2-3) |
| Benchmark - LAB (moteur + 2 webapps Standard) | ⏳ Codé, non déployé DSS ; launcher refondu 2026-07-03 (panes rééquilibrés, golden legacy fusionné, UI rename) | - | L102-L113/L128 (`OWIsMind_LAB/`) |
| Benchmark - consultation plugin (+ détail attempt) | ⏳ Codé ; fix nom de table validé DSS ; page refondue 2026-07-03 (modes conditionnels, détail par onglets) | 2026-06-26 (fix L110) | L109-L111/L117/L129 |
| Impersonation admin (read-only, « act as user ») | ✅ Validé DSS | 2026-06-19 (Run 3) | L095/L096 |
| Auth gate (écran « non identifié » sur `/me` 401) | ✅ Validé DSS | 2026-06-19 (Run 3) | L094-L096 |
| Plugin DEV coexistant (`owismind_dev` / `owismind_dev_v2`) | 🗑 Zips + staging SUPPRIMÉS du disque (2026-07-06 Run 5, passage prod) ; outillage `tools/build_dev_plugin.py` + skill conservés, re-créable à la demande | 2026-06-19 (Run 3, historique) | L094 (`sessions/2026-07-06.md` Run 5) |
| **Plugin PROD v1.1.0** (`owismind-upload.zip`, 95 entrées, `index-DDxpe_gw.js`) | ⏳ Packagé (repo), À UPLOADER + déployer dans le projet DSS prod : runbook `docs/DEPLOY_PROD_V1_1.md` | - | `sessions/2026-07-06.md` Run 5 |
| Agents DEV - orchestrateur + expert revenus | ✅ Validés DSS ; audit L118 en attente de re-validation | 2026-07-02 (Run 2) | L055-L058/L118-L120 |
| Agents DEV - expert tickets d'incidents | 🟡 Testé DSS (« marche plutôt bien »), à finaliser | 2026-06-19 (Run 4) | L097/L098 |
| Agents PROD (`OWISMIND_PROD_V1`) - revenus (tickets non promu, refus honnête) | 🟡 Fichiers repo PROMUS depuis DEV le 2026-07-06 (Run 5 : régénération scriptée `tools/promote_agents_to_prod.py`, parité vérifiée par 3 revues Opus) ; À RE-COLLER en DSS (runbook §3) ; dernier collage DSS = 2026-06-18 | 2026-06-18 (debug PROD, version antérieure) | L090/L099/**L139** |
| Suivi tokens/coûts (ligne usage sous chaque réponse) | ✅ Validé DSS (ligne usage affichée, confirmée Run 6) | 2026-07-02 | L049/L126 |

## 12. Prochaines étapes
Voir CONTEXT.md « 🔜 Prochaines étapes » (tenu à jour à chaque session) ; historique dans memory/sessions/.

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
components/pages/            # FONDATIONS pages (Phase 3) : PageShell (props `wide`=1080px, `fluid`=pleine largeur opt-in pour la consultation Benchmark, L112) · EmptyState(état vide honnête) · SettingCard (+index.js). [AdminPanel.vue SUPPRIMÉ → logique portée dans AdminView]
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
