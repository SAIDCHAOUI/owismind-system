# Documentation - OWIsMind

**OWIsMind** est une WebApp de **chat agentique** packagée en **plugin Dataiku DSS** : un frontend
**Vue 3 + Vite** (buildé en assets statiques servis par DSS) + un backend **Flask** modulaire
(`python-lib/owismind/`) qui parle à des agents **LLM Mesh** et persiste les conversations en **SQL
direct** (`SQLExecutor2`, PostgreSQL), **sans Flow** au runtime.

> Ces documents sont la **référence d'ingénierie** (onboarding / passation production). Ils décrivent
> l'état réel du code. Pour le *pourquoi* d'une décision et le fil des sessions, voir `memory/`
> (source de vérité vivante). En cas de conflit doc ↔ `memory/` : **`memory/` fait foi**.

## Par où commencer

1. Lire **[architecture.md](architecture.md)** pour la vue d'ensemble et le flux de données.
2. Selon ton domaine : **[backend-api.md](backend-api.md)** (API + modules), **[frontend.md](frontend.md)**
   (Vue 3), ou **[data-model.md](data-model.md)** (schéma SQL).
3. Avant de livrer : **[build-test-deploy.md](build-test-deploy.md)** (build/package/déploiement DSS) et
   **[security.md](security.md)** (modèle de sécurité + sûreté instance).

## Les documents

| Document | Contenu |
|---|---|
| [architecture.md](architecture.md) | Architecture système, composants, modèle d'exécution DSS, flux end-to-end d'un tour de chat (polling, pas SSE), carte du dépôt. |
| [backend-api.md](backend-api.md) | Référence exhaustive de l'API HTTP `/owismind-api`, carte des modules `python-lib/owismind/`, cycle de vie d'un run agent, validateurs + codes d'erreur. |
| [frontend.md](frontend.md) | Architecture frontend Vue 3 : stores Pinia, composables (réducteurs purs testés), timeline live, routing HASH, i18n, thème, gotchas F1-F21. |
| [data-model.md](data-model.md) | Modèle de données SQL : tables (`webapp_chat_v4`, `webapp_users_v1`, `webapp_settings_v1`), arbre de conversation (`parent_exchange_id`), écriture en deux phases, dataset de trace write-only, invariants de sûreté. |
| [security.md](security.md) | Modèle de menace, identité serveur, whitelist d'agents dynamique, sécurité SQL (paramétrage, owner-scoping), admin bootstrap, sûreté de l'instance Dataiku (rate/cap/TTL, logging content-free). |
| [build-test-deploy.md](build-test-deploy.md) | Politique NO-INSTALL, noms canoniques, dev local, tests (`unittest` + `node:test`), pipeline build → wire → package → upload DSS manuel, matrice « quoi rebuilder quand ». |

## Le reste du dépôt

- **`memory/`** - mémoire vivante (chargée à chaque session de dev) : `CONTEXT.md` (focus courant),
  `PROJECT_STATE.md` (état/archi/ids canoniques/schéma), `LESSONS.md` (décisions et ce qui a divergé des
  guides), `sessions/` (journal par session). **Source de vérité.**
- **`cadrage/`** - points de départ : `GUIDE_DATAIKU_DSS_PLUGIN_REFERENCE.md` (référence d'ingénierie
  Dataiku condensée), `owismind_webapp_v3_cahier_des_charges_fonctionnel.md` (cahier des charges produit),
  `code_samples_dataiku.md` (snippets notebook validés).
- **`orchestrator/`** - l'agent orchestrateur (Code Agent DSS) : `orchestrator_agent.py` v2.2 à coller
  dans DSS, + `AUDIT.md` et ses tests.
- **`docs/superpowers/specs/`** - specs de conception **gelées** des lots livrés (2026-06-09/10) :
  Evidence Studio v1, trust layer, arbre de conversation… Décisions distillées dans `memory/LESSONS.md`.
  (Les plans d'exécution associés et la maquette d'origine - convertie en Vue 3 - ont été supprimés au
  nettoyage du 2026-06-11.)

## Conventions

- **Code & commentaires en anglais** ; **documentation en français** (les identifiants, noms de routes,
  tables et termes techniques restent sous leur forme d'origine anglaise).
- Le frontend buildé (`Plugin/owismind/resource/owismind-app/`) est **versionné** (politique NO-INSTALL →
  le dépôt doit rester packageable depuis un clone) ; ne **jamais** l'éditer à la main - rebuilder via le
  skill `/build-plugin`. Voir [build-test-deploy.md](build-test-deploy.md).
