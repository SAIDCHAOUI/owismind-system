# CONTEXT - OWIsMind (memoire courte, chargee a CHAQUE session)

> Focus + pointeurs seulement. Detail durable : `PROJECT_STATE.md` ; lecons : `LESSONS.md` ; par jour : `sessions/*.md`.
> Gotchas actives (frontend/backend/agents/LAB/memoire) : `.claude/rules/*.md`, chargees AUTO selon les fichiers touches.
> **OWIsMind** = plugin Dataiku DSS : WebApp Vue 3 + Vite (front builde, servi par DSS) + backend Flask modulaire
> (`python-lib/owismind/`) qui parle aux agents via LLM Mesh et stocke en SQL direct (PostgreSQL), sans Flow au runtime.

## Focus courant

**PREMIER BUILD AUTO + SCENARIO STEP-BASED (2026-07-22, commit 1c88695 pousse).** L'etape guidee
`first_build` est passee de MANUELLE a AUTO : la console lance le scenario, attend (borne 30 min,
poll 10 s, progression au journal / 5 min), verifie les lignes, remonte l'erreur DSS
(`first_error_details` + fix partition + Last runs) si echec, se RATTACHE a un run deja en cours
(jamais de double run). Le scenario de refresh est desormais STEP-BASED (un step `build_flowitem`
par dataset de connaissance, `RECURSIVE_BUILD`, read-back `raw_steps` bruyant), toujours INACTIF +
trigger quotidien ; trigger "dataset modified" NON automatise (forme brute absente de la doc,
2 clics UI). `heal_interrupted` migre un run persiste sur l'ancienne etape manuelle. Zero
changement backend console / front (contrat gele). 692 tests (+16), revue adversariale Opus SAINE.
Restent a l'user : relecture profil, wizard, collage Code Agent (si sonde non confirmee), smoke.
**TERRAIN** : 2e domaine cree de bout en bout par l'user = `opportunities_won` (`agent:4Ghpi5hm`,
tool `iUR8wLX`). Ecart constate puis DIAGNOSTIQUE (L168) : le hub est charge au DEMARRAGE DU
PROCESS de l'orchestrateur -> Playground (process frais) voit le nouvel expert, webapp (process
Mesh chaud) non ; deblocage = re-save de l'orchestrateur ; correctif durable (reload TTL ~60 s
par conversation + textes enable/succes) PROPOSE, decision user en attente. Brief design complet
remis dans le chat pour la refonte UX de la console par Claude Design (portage ES5 a suivre).
PUSH actifs cette session (demande user explicite : "commit et push", il pull pour DSS).

## Chaine des sessions (une ligne par run, detail dans sessions/<date>.md)
- 2026-07-22 : premier build AUTO (scenario step-based ancre doc + run_scenario_and_wait + migration heal), 692 tests, commit 1c88695 pousse ; 2e expert terrain `opportunities_won` ; diagnostic hub charge au demarrage du process (Playground vs webapp, L168) ; brief design UX console remis. L167-L168. Voir `sessions/2026-07-22.md`.
- 2026-07-21 : assistant guide persistant dans la console (13 etapes, etat SQL, verifs DSS par etape ; moteur Fable + front Sol) construit apres le test opportunities avorte, puis VALIDE EN DSS par l'user (1er expert delivery_snapshot live, 4 fixes terrain). L164-L166. Voir `sessions/2026-07-21.md`.
- 2026-07-20 : deploiement v1.3 guide par l'user (notebooks 00-06, clone aligne VALIDE) ; restructure repo = un dossier racine par projet DSS + hub sous /python/ + UN fichier py par modele semantique ; fix regex console. L162-L163 (pas de fichier session, detail dans les lecons + commits 6e33a75..f39b00d).
- 2026-07-17 Run 3 : verification PRE-TEST triple (Fable 5 lead + workflow Opus 6 dim + GPT-5.6 Sol + revue adversariale Opus du diff) -> 7 fix (1 CRITICAL save_plan + 2 HIGH catalogue/garde-SQL + 3 M/L + 1 HIGH double-run) + zip DEV `owismind-v1_3-dev-upload.zip` + residuels etat-machine documentes (H3/H4/H5). backend 965 / agents 619 / LAB 343 / front 365. L161. Voir `sessions/2026-07-17.md`.
- 2026-07-17 (nuit, Runs 1-2) : couche agentique "Durable Step Shell" v1.3 (backend ordonnanceur durable + Code Agent invoque par commande bornee ; dual-path legacy intact ; correlate JOIN SQL read-only ; UI carte de plan ; catalogue factory) ; brainstorm 3 voix Fable 5 + GPT-5.6 Sol ; 1er audit securite (0 Critical, 3 findings corriges) ; guide complet + fix cablage flag. 17 commits pousses `..b909156` + 3 locaux. L157-L160. Voir `sessions/2026-07-17.md`.
- 2026-07-16 Run 1 : git a plat (merge nuit + push tout + suppression branches mergees) ; miroir restructure UI DSS (genai/, project-library/python/owismind_hub/, docs/) ; 11 README FR ; double audit securite (interne + Sol) + 2 vagues de durcissement, 468 -> 516 tests, 5 commits. L156. Voir `sessions/2026-07-16.md`.
- 2026-07-12 Run 1 (nuit, branche night-20260712) : durcissement adversarial Agent Factory v1.3 TERMINE (6 vagues multi-agents : failure-modes + wizard + console + docs + regenerateur seeds hub + cross-review), 379 -> 468 tests, 10 commits, rien pousse. L152-L155. Voir `sessions/2026-07-12.md`.
- 2026-07-10 Run 3 : setup orchestration Claude + Codex/GPT-5.6 (AGENTS.md, .codex/config.toml, rule model-routing, pointeur CLAUDE.md, teste en reel). L151. Voir `sessions/2026-07-10.md`.
- 2026-07-10 Run 2 (nuit, branche v1.3-dev) : Agent Factory v1.3 complete (package + hub + console + docs + 379 tests + revues). L149-L150. Voir `sessions/2026-07-10.md`.
- 2026-07-10 Run 1 (branche prod) : restructuration du repo en miroir exact du projet DSS prod (arbo racine `OWIsMind_PRD_V1_3_DEV/`, plugin 1.2.0, zip versionne, branches par version). L147-L148 (sur la branche `OWIsMind_PRD_V1_2`).
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
- **HUB CHAUD (L168, action user immediate)** : re-save `OWIsMind_orchestrator` dans DSS puis
  nouvelle conversation -> verifier que l'expert opportunites repond dans la webapp. Decision
  attendue : reload du hub par conversation (TTL ~60 s) + textes enable/succes de l'assistant
  (option recommandee, non implementee). Voir `sessions/2026-07-22.md`.
- **REFONTE UX CONSOLE** : maquette Claude Design attendue (brief remis 2026-07-22) ; au retour,
  portage ES5/DSS (contrat gele) + passage charte-orange-reviewer. Voir `sessions/2026-07-22.md`.
- **ASSISTANT GUIDE (2 experts live : delivery_snapshot + opportunities_won)** : confirmer en DSS
  le premier build AUTO au prochain domaine (library owismind_factory a re-coller si le pull ne
  l'a pas fait) ; smoke metier des 2 nouveaux experts (questions reelles + Evidence + non-regression
  revenus/tickets) ; curation des profils si reponses moyennes ; suppression par l'user des objets
  opportunities avortes du 2026-07-21.
- **Repo, ecart guide/code** : le notebook `01_push_config_hub.py` ne pousse que settings +
  capabilities + persona ; il ne pousse PAS `run_settings.json`, `prompts/orchestrator_workflow.md`
  NI `templates/dataset_expert.py` quand la sonde n'a pas confirme les cles (fallback = simple
  print MANUAL, rate par l'user le 2026-07-21 -> template absent -> code agent jamais genere ;
  l'assistant guide verifie desormais le template avec instructions). Etendre 01 (via le
  regenerateur de seeds) ou corriger le guide.
- **DSS clone v1.3 : re-pointer les 2 tools Semantic Model Query** (L162 : leurs params portent encore
  `project_key OWISMIND_PRD_V1_2` apres duplication ; le notebook 02 ne corrige que les modeles).
- **DURABLE STEP SHELL v1.3 - DEPLOIEMENT DSS DEV** : `DEPLOY_V1_3_DEV.md` phase H (zip + re-paste
  orchestrateur env 3.11 + seeds hub 01 + webapp Auto-start + flag `durable_workflow` sur l'orchestrateur
  DEV + `domain_keywords`), puis les 16 scenarios de validation + le smoke 1 cycle claim/complete sur le
  vrai executeur SQL (seul pattern SQL nouveau = CTE modifiante + SELECT). Calibrer les deadlines par
  mode en reel (durees Mesh non documentees). Rapport a remonter. Voir `sessions/2026-07-17.md`.
- Backlog Durable Step Shell (differe, spec section 12) : cabler l'auto-reattach front (`fetchActiveRun`
  -> `resumeChatStream`, primitives livrees) + toggle UI "Analyse approfondie" (analysis_mode deep/direct,
  le mode auto marche sans) ; DAG parallele ; pgvector ; skills write (mail/PDF, requiert human approval).
- **FACTORY v1.3 : DEPLOYEE ET VALIDEE (2026-07-21, 1er domaine live).** Reste de `DEPLOY_V1_3_DEV.md` : confirmer les 3 GATES securite de la phase 0 cote DSS (console admins-only + run-as dedie ; SQL_owi timeout/droits au niveau base ; acces/retention du dataset de logs). Synthese audit : `docs/SECURITY_AUDIT_2026-07-16.md`.
- Backlog v1.3 (durcissement non bloquant, voir SECURITY_AUDIT section backlog) : authz par viewer dans la console (WebappImpersonationContext) ; manifeste de reprise par domaine (rejoint le manifeste canonique deja au backlog) ; machine d'etat persistante par domaine ; environnement de validation pre-live ; controle operationnel.
- CODEX : flux end-to-end VALIDE en reel le 2026-07-16 (audit securite livre par Sol via codex-companion, piege L156 : verifier la vivacite du PID, pas le seul statut). Reste : une review croisee avant commit (`/codex:review`). Sur le VPS (saiget/saive) : penser au trust projet dans `~/.codex/config.toml`.
- CLONE prod : lancer `OWIsMind_PRD_V1_3_DEV/GenAI/semantic-models/TroubleTickets_Semantic_Model/TroubleTickets_Semantic_Model.py` (ACTION="repoint") sur le clone
  + smoke tickets end-to-end + tester le grounding `Solution` dans le Playground revenus. Puis smoke complet
  (resolution sous-agent dans le clone, ids des tools si recrees). Voir `sessions/2026-07-08.md` + L146
  (revenus + repoint = FAITS, valides DSS).
- Promotion Source Data v3 (dev_v2 -> DEV principal puis PROD) : rebuild + orchestrateur prod (clone) `038G7mlF` avec le paragraphe SOURCE-DATA VIEW. Voir `sessions/2026-07-06.md` (Runs 2-4).
- LAB benchmark, recolls accumules (a batcher, `OWIsMind_LAB/README.md` + guides) : refonte launcher + route `/api/config` (L127-L129), visibilite complete des resultats L117, 2 fixes launcher L115, creation des 2 webapps Standard + variable `benchmark` (L103/L109), finir judge/aggregate/run complet L102.
- Auditer/valider en DSS DEV le residuel L118 (sous-agent revenus + tool lookup + `Drive_Revenues_Semantic_Model.py` ACTION="update" + re-dump ACTION="dump" (ex update_aligned, consolide 2026-07-20)) ; l'orchestrateur DEV est deja recolle. Voir `sessions/2026-07-02.md` (Run 1).
- 2e agent TICKETS : finaliser + pofiner (`OWIsMind_PRD_V1_3_DEV/docs/PLAYBOOK_ADD_AGENT.md`) -> debloque la fiche client 360. L097-L098.
- Backlog differe : recueillir les ajustements user sur le trust layer ; consolidation SalesDrive v2 (cas d'ambiguite reelle) ; re-tester en DSS L040/L041 ; Evidence v3 (restriction admin datasets, keyset pagination) ; 2e task mentionnee par l'user le 2026-06-09 (a clarifier).
