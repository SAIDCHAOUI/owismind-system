# CONTEXT - OWIsMind (memoire courte, chargee a CHAQUE session)

> Focus + pointeurs seulement. Detail durable : `PROJECT_STATE.md` ; lecons : `LESSONS.md` ; par jour : `sessions/*.md`.
> Gotchas actives (frontend/backend/agents/LAB/memoire) : `.claude/rules/*.md`, chargees AUTO selon les fichiers touches.
> **OWIsMind** = plugin Dataiku DSS : WebApp Vue 3 + Vite (front builde, servi par DSS) + backend Flask modulaire
> (`python-lib/owismind/`) qui parle aux agents via LLM Mesh et stocke en SQL direct (PostgreSQL), sans Flow au runtime.

## Focus courant

**AGENT FACTORY v1.3 IMPLEMENTEE (2026-07-10 Run 2, session de nuit, branche `OWIsMind_PRD_V1_3-dev`).**
- **`OWIsMind_PRD_V1_2/project-library/python/owismind_factory/`** (13 modules, stdlib+dataiku 3.9,
  dry-run, idempotent, ZERO delete) : table source -> zone + 3 recettes clonees + datasets -> modele
  semantique (wizard LLM `with_json_output` + questions FR) -> tool semantic query (GATE) -> Code Agent
  (GATE) -> enregistrement capability. Gates = sondes Phase 0 (`notebooks/00_probe_capabilities.py`) ;
  sans confirmation, fallback = checklist manuelle precise. Notebooks 00-06 ; `align.py` = repoint
  generique de TOUS les modeles d'un clone ; `doctor.py` = prompt doctor (proposition, jamais d'apply).
- **Config & Prompt Hub** `/owismind_hub/` (project library) : PERSONA + capabilities.json + regles
  additives par domaine, charges par les 3 agents au demarrage (validation stricte, fallback silencieux
  durci post-revue adversariale). Seeds repo `OWIsMind_PRD_V1_2/hub/` = equivalence byte-a-byte avec les
  defauts embarques (test anti-derive). Iterer un prompt = editer le hub + redemarrer l'agent (0 re-paste).
- **Console** `webapps/agent-factory-console/` (webapp Standard SEPAREE du plugin, charte Orange PASS) :
  sonde / plan dry-run / execution journalisee / wizard Q&A / editeur de prompts ; confirm:true partout.
- 379 tests verts ; revue adversariale Opus (2 findings corriges) ; 8 commits POUSSES sur origin
  (autorisation user explicite). RIEN n'a ete execute contre DSS : deploiement = 
  **`OWIsMind_PRD_V1_2/factory-docs/DEPLOY_V1_3_DEV.md`** (phases A-G), sondes a lancer par l'user.

## Chaine des sessions (une ligne par run, detail dans sessions/<date>.md)
- 2026-07-10 Run 2 (nuit, branche v1.3-dev) : Agent Factory v1.3 complete (package + hub + console + docs + 379 tests + revues). L149-L150. Voir `sessions/2026-07-10.md`.
- 2026-07-10 Run 1 (branche prod) : restructuration du repo en miroir exact du projet DSS prod (arbo racine `OWIsMind_PRD_V1_2/`, plugin 1.2.0, zip versionne, branches par version). L147-L148 (sur la branche `OWIsMind_PRD_V1_2`).
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
- **FACTORY v1.3** : cloner le projet DSS v1.2 -> v1.3-dev puis suivre `OWIsMind_PRD_V1_2/factory-docs/DEPLOY_V1_3_DEV.md` phases A-D (lib + sonde 00 lecture seule + push hub 01 + re-paste des 3 agents + neutralite). Rapporter le rapport de sonde -> deverrouillage des gates (tool + code agent). Puis phase F (1er domaine + wizard) et G (logging + doctor). Voir `sessions/2026-07-10.md` Run 2.
- CLONE prod : lancer `OWIsMind_PRD_V1_2/semantic-models/scripts/repoint_tickets_prod_clone.py` sur le clone
  + smoke tickets end-to-end + tester le grounding `Solution` dans le Playground revenus. Puis smoke complet
  (resolution sous-agent dans le clone, ids des tools si recrees). Voir `sessions/2026-07-08.md` + L146
  (revenus + repoint = FAITS, valides DSS).
- Promotion Source Data v3 (dev_v2 -> DEV principal puis PROD) : rebuild + orchestrateur prod (clone) `038G7mlF` avec le paragraphe SOURCE-DATA VIEW. Voir `sessions/2026-07-06.md` (Runs 2-4).
- LAB benchmark, recolls accumules (a batcher, `OWIsMind_LAB/README.md` + guides) : refonte launcher + route `/api/config` (L127-L129), visibilite complete des resultats L117, 2 fixes launcher L115, creation des 2 webapps Standard + variable `benchmark` (L103/L109), finir judge/aggregate/run complet L102.
- Auditer/valider en DSS DEV le residuel L118 (sous-agent revenus + tool lookup + `update_aligned_semantic_model.py` + re-dump) ; l'orchestrateur DEV est deja recolle. Voir `sessions/2026-07-02.md` (Run 1).
- 2e agent TICKETS : finaliser + pofiner (`OWIsMind_PRD_V1_2/PLAYBOOK_ADD_AGENT.md`) -> debloque la fiche client 360. L097-L098.
- Backlog differe : recueillir les ajustements user sur le trust layer ; consolidation SalesDrive v2 (cas d'ambiguite reelle) ; re-tester en DSS L040/L041 ; Evidence v3 (restriction admin datasets, keyset pagination) ; 2e task mentionnee par l'user le 2026-06-09 (a clarifier).
