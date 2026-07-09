# CONTEXT - OWIsMind (memoire courte, chargee a CHAQUE session)

> Focus + pointeurs seulement. Detail durable : `PROJECT_STATE.md` ; lecons : `LESSONS.md` ; par jour : `sessions/*.md`.
> Gotchas actives (frontend/backend/agents/LAB/memoire) : `.claude/rules/*.md`, chargees AUTO selon les fichiers touches.
> **OWIsMind** = plugin Dataiku DSS : WebApp Vue 3 + Vite (front builde, servi par DSS) + backend Flask modulaire
> (`python-lib/owismind/`) qui parle aux agents via LLM Mesh et stocke en SQL direct (PostgreSQL), sans Flow au runtime.

## Focus courant

**RESTRUCTURATION DU REPO EN MIROIR EXACT DU PROJET DSS PROD `OWIsMind_PRD_V1_2` (2026-07-10).**
- Nouvelle arborescence racine **`OWIsMind_PRD_V1_2/`** (`flow/`, `agents/`, `tools/`, `semantic-models/`,
  `tests/`) = miroir 1:1 du projet DSS prod (CLONE de DEV, ids DEV conserves ; orchestrateur `038G7mlF`
  -> sous-agents revenus `agent:bHrWLyOL` + tickets `agent:NcE9LD2i`). L'ancien `dataiku-agents/` a
  DISPARU ; `OWISMIND_PROD_V1` + `promote_agents_to_prod.py` (jumeau prod a la main) = LEGACY SUPPRIMES.
- Plugin `plugin.json` **1.2.0** ; zip prod versionne **`Plugin/ready-for-dataiku/owismind-v1_2-upload.zip`**
  REGENERE (95 entrees, propre ; legacy `owismind-upload.zip` + `owismind-v1_3-upload.zip` supprimes).
  Mecanisme dev coexistant CONSERVE (`tools/build_dev_plugin.py`, id `owismind_dev`, zip
  `owismind-v<VER>-dev-upload.zip` ; slot `--version` -> `owismind_vX_Y-upload.zip`, L148).
- Git = **une branche par version**, nommee comme le projet DSS prod : `OWIsMind_PRD_V1_2` = prod courante
  (source de verite) ; `OWIsMind_PRD_V1_3-dev` = prochaine version (feedback hub WIP preserve, structure
  mergee, plugin.json 1.3.0) ; suffixe `-dev` retire a la validation ; `main` DEPRECIEE.
- Revue adversariale du diff complet : **PASS** (0 bloquant ; neutralite comportementale des .py miroir
  prouvee AST ; 46/46 fichiers comptabilises). 3 suites vertes (miroir 316, LAB 343, plugin 790).
  Detail : `sessions/2026-07-10.md` + L147-L148.

## Chaine des sessions (une ligne par run, detail dans sessions/<date>.md)
- 2026-07-10 : restructuration du repo en miroir exact du projet DSS prod (arbo racine `OWIsMind_PRD_V1_2/`, plugin 1.2.0, zip versionne, branches par version, merge dans `OWIsMind_PRD_V1_3-dev` + bump 1.3.0 ; legacy `OWISMIND_PROD_V1` + `promote_agents_to_prod.py` supprimes). L147-L148. Voir `sessions/2026-07-10.md`.
- 2026-07-08 Run 1 : colonne `Solution` re-ajoutee au modele revenus du clone + les 2 modeles semantiques repointes vers le dataset du clone (revenus VALIDE DSS ; tickets a lancer). L146.
- 2026-07-07 Run 2 : bascule strategie prod = CLONE du projet DSS DEV (memes ids, tickets inclus). L144.
- 2026-07-07 Run 1 : deep clean pro sur branche `refactor/deep-clean-v1.2` (refactor zero-comportement, prouve ; setup Claude Code refondu ; docs v1.1). L141-L143.
- 2026-07-06 Runs 2-4 : Source Data v3 complet (popover, Calculer, plages string, cascade, persistance,
  contexte ecran -> agent, menu de colonne). VALIDE DSS (« tout marche super »). L134-L138.
- 2026-07-06 Run 1 : data tools sans IA (agregats DB + Calculer + plages + unification Evidence), plugin dev_v2. L132-L133.
- 2026-07-03 Run 3 : optimisation des espaces page benchmark plugin (pickers en-tete, hero+stats, bande ref). Local. L131.
- 2026-07-03 Runs 2 + 2b : refonte benchmark launcher LAB + page plugin modes conditionnels + hotfix CSS. Local. L128-L130.
- 2026-07-03 Run 1 : grand nettoyage pre-beta (memoire -72 %, docs 34/34 routes + 8/8 tables, /api/config LAB). L127.
- 2026-07-02 Run 6 : mode ephemere (Smart par defaut) + mode par reponse (`chat_v5.mode`). VALIDE DSS. L126.
- 2026-07-02 Run 5 : analytics d'usage (`webapp_events_v1` + `POST /track` + `track.js`). VALIDE DSS. L125.
- 2026-07-02 Run 4 : Source Data filtres cherchables + cell-to-agent + popover/DataLoader. VALIDE DSS. L123-L124.
- 2026-07-02 Run 3 : Source Data Explorer v1+v2. VALIDE DSS. L121-L122.
- 2026-07-02 Run 2 : artefacts natifs + narration + recall. VALIDE DSS. L119-L120.
- 2026-07-02 Run 1 : audit + durcissement orchestrateur / expert revenus / cerveau semantique. Repo DEV. L118.
- 2026-07-01 Run 3 : visibilite complete des resultats benchmark (reponse + SQL genere + tableau) + override. L117.
- 2026-07-01 Run 2 : clarte benchmark detail + galerie d'agents + flux "ajouter un agent" + nettoyage ultracode. L116.
- 2026-07-01 Run 1 : LAB launcher, nettoyage + 4 fixes + 1 feature (contrat golden, `agent_key=id`). L115.
- 2026-06-30 : mail de relance HTML (L114) ; benchmark v2 append mode + colonnes SQL/tool de reference (L113).
- 2026-06-29 : consultation benchmark pleine largeur (L112) ; benchmark phase finale juge + override + plugin (L111).
- 2026-06-26 : fix nom de table trop long (L110) + reorg benchmark sous `OWIsMind_LAB/` (L109) + nettoyage repo (L108) + re-skin webapps LAB (L107) + integration benchmark 2 poles (L103-L104).
- 2026-06-25 : systeme de benchmark / evaluation des agents (package `benchmark/`, LAB). L102.
- 2026-06-24 : fix UI pouces feedback + modes par agent Smart/Pro/Claude.
- Anterieur au 2026-06-24 : archive. Detail par date dans `sessions/*.md` ; jalons dans `PROJECT_STATE.md` (2b, 8, 11).

## Regles
- 10 regles non negociables + identifiants canoniques : `CLAUDE.md`. Rappel : #9 = ZERO tiret cadratin/demi-cadratin
  PARTOUT ; #10 = CHARTE ORANGE a chaque travail de style (`docs/cadrage/CHARTE_ORANGE_UI.md`).
- Gotchas techniques : `.claude/rules/{frontend,backend,agents,lab,memory}.md` (path-scoped, chargees auto).

## Prochaines etapes (items encore actifs seulement)
- Upload `owismind-v1_2-upload.zip` en DSS (runbook `docs/DEPLOY_PROD_V1_2.md`) pour aligner la version
  affichee (instance encore en 1.1.0) ; puis re-dump du JSON revenus (anterieur au re-add `Solution`).
- CLONE prod : lancer `OWIsMind_PRD_V1_2/semantic-models/scripts/repoint_tickets_prod_clone.py` sur le clone
  + smoke tickets end-to-end + tester le grounding `Solution` dans le Playground revenus. Puis smoke complet
  (resolution sous-agent dans le clone, ids des tools si recrees). Voir `sessions/2026-07-08.md` + L146
  (revenus + repoint = FAITS, valides DSS).
- Promotion Source Data v3 (dev_v2 -> DEV principal puis PROD) : rebuild + orchestrateur prod (clone) `038G7mlF` avec le paragraphe SOURCE-DATA VIEW. Voir `sessions/2026-07-06.md` (Runs 2-4).
- LAB benchmark, recolls accumules (a batcher, `OWIsMind_LAB/README.md` + guides) : refonte launcher + route `/api/config` (L127-L129), visibilite complete des resultats L117, 2 fixes launcher L115, creation des 2 webapps Standard + variable `benchmark` (L103/L109), finir judge/aggregate/run complet L102.
- Auditer/valider en DSS DEV le residuel L118 (sous-agent revenus + tool lookup + `update_aligned_semantic_model.py` + re-dump) ; l'orchestrateur DEV est deja recolle. Voir `sessions/2026-07-02.md` (Run 1).
- 2e agent TICKETS : finaliser + pofiner (`OWIsMind_PRD_V1_2/PLAYBOOK_ADD_AGENT.md`) -> debloque la fiche client 360. L097-L098.
- Backlog differe : recueillir les ajustements user sur le trust layer ; consolidation SalesDrive v2 (cas d'ambiguite reelle) ; re-tester en DSS L040/L041 ; Evidence v3 (restriction admin datasets, keyset pagination) ; 2e task mentionnee par l'user le 2026-06-09 (a clarifier).
