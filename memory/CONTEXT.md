# CONTEXT - OWIsMind (memoire courte, chargee a CHAQUE session)

> Focus + pointeurs seulement. Detail durable : `PROJECT_STATE.md` ; lecons : `LESSONS.md` ; par jour : `sessions/*.md`.
> Gotchas actives (frontend/backend/agents/LAB/memoire) : `.claude/rules/*.md`, chargees AUTO selon les fichiers touches.
> **OWIsMind** = plugin Dataiku DSS : WebApp Vue 3 + Vite (front builde, servi par DSS) + backend Flask modulaire
> (`python-lib/owismind/`) qui parle aux agents via LLM Mesh et stocke en SQL direct (PostgreSQL), sans Flow au runtime.

## Focus courant

**DURABLE STEP SHELL v1.3 - VERIFICATION PRE-TEST TRIPLE + DURCISSEMENT + ZIP v1.3-dev
(2026-07-17 Run 3, branche `OWIsMind_PRD_V1_3-dev`, fixes en working tree, commit de session a faire).**
L'user veut la CERTITUDE (securite + correction + optim) AVANT de tester en DSS. Revue TRIPLE
independante : Fable 5 lead + workflow Opus 6 dimensions (verif adversariale par finding) + GPT-5.6 Sol
(codex read-only) + revue adversariale Opus du diff. Elles ont CONVERGE et debusque ce que les suites
VERTES cachaient (test-doubles infideles au contrat reel, L161). **Zip DEV** :
`Plugin/ready-for-dataiku/owismind-v1_3-dev-upload.zip` (id `owismind_dev`, git-ignore, prod v1.2 intacte).
**7 fix + tests** : C1 CRITICAL `save_plan` ne persistait pas capability_keys/args (feature durable
inoperante en DSS reel) ; C2 HIGH lecture catalogue correlate (data_type/item_level vs column_type) ;
C3 HIGH garde SQL correlate (`TABLE <rel>`, `from"secret"`, meta-fns query_to_xml/dblink/pg_read_file) ;
C4 poll_durable bouclait sur not_found ; C5 `bool("false")` activait le durable ; C6 HIGH double-run
legacy sur echec spawn ; C7 purge des tables durables jamais appelee (cablee au superviseur). C1/C4-C7
= plugin (dans le zip) ; C2/C3 = orchestrateur (a RECOLLER en DSS 3.11, HORS zip). **DOCUMENTES (patch
propose, valider au smoke DSS)** : H3 fencing complet writes terminaux, H4 watchdog stream Mesh muet
(= "run long qui hang"), H5 replay reponse post-crash, M2/M3, deadlines-depuis-hub, goal non persiste.
Non corriges a l'aveugle (justesse dependante de faits DSS). 4 suites vertes apres fix : backend 965,
agents+factory 619, LAB 343, front 365. RIEN execute contre DSS. Rapport
`OWIsMind_PRD_V1_2/docs/SECURITY_AUDIT_2026-07-17_DURABLE_V2.md`. L161. Voir `sessions/2026-07-17.md`.

**Base anterieure (2026-07-17 Runs 1-2) : implementation + audit initial + guide + fix cablage flag**
(couche durable complete, 0 Critical/3 findings corriges au 1er audit, guide `DURABLE_STEP_SHELL.md`,
fix `durable_workflow` inactivable). L157-L160. 17 commits pousses `..b909156` + 3 locaux + Run 3 (working
tree). Voir `sessions/2026-07-17.md`.

## Chaine des sessions (une ligne par run, detail dans sessions/<date>.md)
- 2026-07-17 Run 3 : verification PRE-TEST triple (Fable 5 lead + workflow Opus 6 dim + GPT-5.6 Sol + revue adversariale Opus du diff) -> 7 fix (1 CRITICAL save_plan + 2 HIGH catalogue/garde-SQL + 3 M/L + 1 HIGH double-run) + zip DEV `owismind-v1_3-dev-upload.zip` + residuels etat-machine documentes (H3/H4/H5). backend 965 / agents 619 / LAB 343 / front 365. L161. Voir `sessions/2026-07-17.md`.
- 2026-07-17 (nuit, Runs 1-2) : couche agentique "Durable Step Shell" v1.3 (backend ordonnanceur durable + Code Agent invoque par commande bornee ; dual-path legacy intact ; correlate JOIN SQL read-only ; UI carte de plan ; catalogue factory) ; brainstorm 3 voix Fable 5 + GPT-5.6 Sol ; 1er audit securite (0 Critical, 3 findings corriges) ; guide complet + fix cablage flag. 17 commits pousses `..b909156` + 3 locaux. L157-L160. Voir `sessions/2026-07-17.md`.
- 2026-07-16 Run 1 : git a plat (merge nuit + push tout + suppression branches mergees) ; miroir restructure UI DSS (genai/, project-library/owismind_hub/, docs/) ; 11 README FR ; double audit securite (interne + Sol) + 2 vagues de durcissement, 468 -> 516 tests, 5 commits. L156. Voir `sessions/2026-07-16.md`.
- 2026-07-12 Run 1 (nuit, branche night-20260712) : durcissement adversarial Agent Factory v1.3 TERMINE (6 vagues multi-agents : failure-modes + wizard + console + docs + regenerateur seeds hub + cross-review), 379 -> 468 tests, 10 commits, rien pousse. L152-L155. Voir `sessions/2026-07-12.md`.
- 2026-07-10 Run 3 : setup orchestration Claude + Codex/GPT-5.6 (AGENTS.md, .codex/config.toml, rule model-routing, pointeur CLAUDE.md, teste en reel). L151. Voir `sessions/2026-07-10.md`.
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
- **DURABLE STEP SHELL v1.3 - DEPLOIEMENT DSS DEV** : `DEPLOY_V1_3_DEV.md` phase H (zip + re-paste
  orchestrateur env 3.11 + seeds hub 01 + webapp Auto-start + flag `durable_workflow` sur l'orchestrateur
  DEV + `domain_keywords`), puis les 16 scenarios de validation + le smoke 1 cycle claim/complete sur le
  vrai executeur SQL (seul pattern SQL nouveau = CTE modifiante + SELECT). Calibrer les deadlines par
  mode en reel (durees Mesh non documentees). Rapport a remonter. Voir `sessions/2026-07-17.md`.
- Backlog Durable Step Shell (differe, spec section 12) : cabler l'auto-reattach front (`fetchActiveRun`
  -> `resumeChatStream`, primitives livrees) + toggle UI "Analyse approfondie" (analysis_mode deep/direct,
  le mode auto marche sans) ; DAG parallele ; pgvector ; skills write (mail/PDF, requiert human approval).
- **FACTORY v1.3 - DEPLOIEMENT** (le clone DSS existe deja) : `OWIsMind_PRD_V1_2/docs/DEPLOY_V1_3_DEV.md` : phase 0 = 3 GATES securite cote DSS (console admins-only + run-as dedie ; SQL_owi SELECT-only + statement timeout au niveau base ; acces/retention du dataset de logs), puis A2 (notebook 02 en 3 passes : decouverte -> EXPECTED_SOURCE_KEYS -> run reel) puis B-D (lib + sonde 00 + push hub 01 + re-paste 3 agents + neutralite). Rapporter le rapport de sonde -> deverrouillage des gates. Puis F (1er domaine + wizard) et G. Synthese audit : `docs/SECURITY_AUDIT_2026-07-16.md`.
- Backlog v1.3 (durcissement non bloquant, voir SECURITY_AUDIT section backlog) : authz par viewer dans la console (WebappImpersonationContext) ; manifeste de reprise par domaine (rejoint le manifeste canonique deja au backlog) ; machine d'etat persistante par domaine ; environnement de validation pre-live ; controle operationnel.
- CODEX : flux end-to-end VALIDE en reel le 2026-07-16 (audit securite livre par Sol via codex-companion, piege L156 : verifier la vivacite du PID, pas le seul statut). Reste : une review croisee avant commit (`/codex:review`). Sur le VPS (saiget/saive) : penser au trust projet dans `~/.codex/config.toml`.
- CLONE prod : lancer `OWIsMind_PRD_V1_2/genai/semantic-models/scripts/repoint_tickets_prod_clone.py` sur le clone
  + smoke tickets end-to-end + tester le grounding `Solution` dans le Playground revenus. Puis smoke complet
  (resolution sous-agent dans le clone, ids des tools si recrees). Voir `sessions/2026-07-08.md` + L146
  (revenus + repoint = FAITS, valides DSS).
- Promotion Source Data v3 (dev_v2 -> DEV principal puis PROD) : rebuild + orchestrateur prod (clone) `038G7mlF` avec le paragraphe SOURCE-DATA VIEW. Voir `sessions/2026-07-06.md` (Runs 2-4).
- LAB benchmark, recolls accumules (a batcher, `OWIsMind_LAB/README.md` + guides) : refonte launcher + route `/api/config` (L127-L129), visibilite complete des resultats L117, 2 fixes launcher L115, creation des 2 webapps Standard + variable `benchmark` (L103/L109), finir judge/aggregate/run complet L102.
- Auditer/valider en DSS DEV le residuel L118 (sous-agent revenus + tool lookup + `update_aligned_semantic_model.py` + re-dump) ; l'orchestrateur DEV est deja recolle. Voir `sessions/2026-07-02.md` (Run 1).
- 2e agent TICKETS : finaliser + pofiner (`OWIsMind_PRD_V1_2/docs/PLAYBOOK_ADD_AGENT.md`) -> debloque la fiche client 360. L097-L098.
- Backlog differe : recueillir les ajustements user sur le trust layer ; consolidation SalesDrive v2 (cas d'ambiguite reelle) ; re-tester en DSS L040/L041 ; Evidence v3 (restriction admin datasets, keyset pagination) ; 2e task mentionnee par l'user le 2026-06-09 (a clarifier).
