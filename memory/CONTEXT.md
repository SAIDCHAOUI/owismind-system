# CONTEXT - OWIsMind (memoire courte, chargee a CHAQUE session)

> Focus + pointeurs seulement. Detail durable : `PROJECT_STATE.md` ; lecons : `LESSONS.md` ; par jour : `sessions/*.md`.
> Gotchas actives (frontend/backend/agents/LAB/memoire) : `.claude/rules/*.md`, chargees AUTO selon les fichiers touches.
> **OWIsMind** = plugin Dataiku DSS : WebApp Vue 3 + Vite (front builde, servi par DSS) + backend Flask modulaire
> (`python-lib/owismind/`) qui parle aux agents via LLM Mesh et stocke en SQL direct (PostgreSQL), sans Flow au runtime.

## Focus courant

**GRANDE VAGUE UX 2026-08-12/13 (nuit + journee, NON committee avant cette session, NON validee DSS).**
Deux runs dans `sessions/2026-08-13.md` :
- **Nuit (run 1)** : `dev-harness/` racine = "yeux" locaux (Vite root->frontend + mock backend fidele
  aux contrats geles + Playwright zero-install, L183 ; regle d'or : on corrige LE MOCK, jamais le
  plugin ; port 5199). Tokens premium + charte section 0 (arrondis interactifs, elevations, blur
  sanctionne du teaser). PromptBar raffinee, dock Source Data teaser FLOUTE auto-dock + resize libre,
  Analyze workspace v3 (phrase MEASURE 1..8 + BY/FOR, KPI/table a barres, preview 50 lignes),
  ScrollHints, panoplie premium sur TOUTES les pages (8 subagents Opus + critique Sol), contexte
  ecran workspace->blocs calc/analyze existants. 2 revues corrigees.
- **Journee (run 2)** : topbar UNE ligne (dropdown DATASET partage `DatasetPick.vue` + recherche
  nommant le dataset + toggle, hauteurs 40px), toggle Data|Analyze dans le HEADER du panneau,
  filtres UNE ligne (Clear all pilule), chips de mesure REMPLACABLES sur place (replaceMeasureAt),
  tableau group-by poli (vrai nom de groupe, barres inset), **FUSION Evidence Studio = meme
  structure** (SourceWorkspace host-parametrable sur le store evidence + preview ajoutee au store ;
  SourceCalc.vue + SourceAnalyze.vue SUPPRIMES ; onglets Evidence -> KPI -> Source data), workspace
  = UN scrollport (analyse en haut, donnees taille normale dessous), sidebar HOVER flyout (L184),
  Show activity honnete (toast si feed vide), wrap actions colonne etroite, PromptBar focus =
  cadre orange + voile 4px --orange-soft (decision user "luxe"), Evidence accessible SANS SQL
  (atterrit sur Source data, L186, scenario mock "Bonjour"), teaser = invitation permanente
  (X sticky par ECRAN seulement, F24 mis a jour).
Gates : 425/425 node:test, builds Vite propres, 0 erreur console sur ~20 parcours harness.

## Chaine des sessions (une ligne par run, detail dans sessions/<date>.md)
- 2026-08-12/13 : vague UX complete (harness "yeux" + premium partout + Analyze v3 + fusion Evidence + finitions). L183-L186. Voir `sessions/2026-08-13.md`.
- 2026-08-07 Run 1 (nuit) : passe UX attention premium (legendes artefacts + tableaux chat + KPI charte + PromptBar + mise au carre + fix dark canvas). 2 revues, 380/380. L181-L182. Voir `sessions/2026-08-07.md`.
- 2026-08-06 Run 4 (soir) : nettoyage profond (3 fichiers morts + 13 icones + 5 constantes). Voir `sessions/2026-08-06.md` run 4.
- 2026-08-06 Run 3 (jour) : UX luxe (dock Source Data d'office, nuances, prompt hero). L180. Voir `sessions/2026-08-06.md` run 3.
- 2026-08-06 Run 2 (nuit) : UX webapp + moteur orchestrateur in-backend (flag native_engine). L177-L179. Voir `sessions/2026-08-06.md` run 2.
- 2026-08-06 Run 1 : audit v1.3 (16 agents, 72 findings) + lots A-E. L174-L176. Voir `sessions/2026-08-06.md`.
- 2026-07-23 : mode claude sur Sonnet 5 (case Reasoning Model x LiteLLM). L172-L173. Voir `sessions/2026-07-23.md`.
- 2026-07-22 Run 2 : capability removal + disable, VALIDE TERRAIN. L169-L171. Voir `sessions/2026-07-22.md`.
- 2026-07-22 Run 1 : premier build AUTO usine ; diagnostic hub charge au demarrage (L168). L167-L168.
- 2026-07-21 : assistant guide persistant console, VALIDE DSS (1er expert delivery_snapshot). L164-L166.
- 2026-07-20 : deploiement v1.3 guide ; restructure repo un dossier par projet DSS. L162-L163.
- 2026-07-17 : verification pre-test triple + zip DEV ; Durable Step Shell v1.3 complet. L157-L161. Voir `sessions/2026-07-17.md`.
- 2026-07-16 : git a plat + miroir UI DSS + double audit securite. L156.
- 2026-07-12 : durcissement adversarial Agent Factory (6 vagues). L152-L155.
- 2026-07-10 : orchestration Codex/GPT-5.6 (L151) ; Agent Factory v1.3 complete (L149-L150) ; miroir repo prod (L147-L148).
- 2026-07-08 et avant : archive. Detail dans `sessions/*.md` ; jalons dans `PROJECT_STATE.md`.

## Regles
- 10 regles non negociables + identifiants canoniques : `CLAUDE.md`. Rappel : #9 = ZERO tiret cadratin/demi-cadratin
  PARTOUT ; #10 = CHARTE ORANGE a chaque travail de style (`docs/cadrage/CHARTE_ORANGE_UI.md`, section 0 = evolution premium).
- Gotchas techniques : `.claude/rules/{frontend,backend,agents,lab,memory}.md` (path-scoped, chargees auto).

## Prochaines etapes (items encore actifs seulement)
- **VALIDATION DSS DE LA VAGUE 12-13/08 (+ runs 06-07/08 jamais deployes)** : USER teste le harness
  (http://127.0.0.1:5199) puis `/build-plugin` ou `/package-plugin-dev` + upload zip DEV ; valider
  clair ET sombre en DSS reel (fix L181 inclus). Arbitrages user : bloc contexte analyze mono-mesure
  (toutes les mesures = evolution backend) ; micro-labels 0.08em a enteriner dans la charte.
  Voir `sessions/2026-08-13.md` + `sessions/2026-08-06.md` runs 2-3.
- **Nettoyage differe front** : API calc*/analyze* de aggregateSurface sans consommateur UI (la
  memoire de vue persiste calcColumn/calcFns) ; dead CSS .pf-lab (AdminView) ; tirets em/en dans
  test/agentPick + evidenceProof (pre-existants). Voir `sessions/2026-08-13.md`.
- **Moteur natif (06/08 run 2)** : entree de TEST flag `native_engine` + checklist `docs/NATIVE_ENGINE.md`
  (jamais execute contre un vrai Mesh) ; backlog = recall natif, sql_id par artefact.
- **Contenu perime signale (06/08 run 4)** : CAPABILITY_MATRIX template ; registry.json sans domaine
  delivery ; docs/data-model.md OUTDATED ; MODEL.md d'avant re-add Solution.
- **AUDIT v1.3 restes** : trancher FE-06/FE-09/onglet nouveau domaine/AG-01b/BE-03 ; refactors
  section 5 ; recolls DSS (3 Code Agents + attribute_lookup + hub + factory + console).
- **MODE CLAUDE restes (23/07)** : 2 tools Semantic Model Query -> sonnet-5 ; juge LAB sur 4.6.
- **HUB CHAUD (L168)** : re-save orchestrateur DSS puis nouvelle conversation ; decision reload TTL.
- **CAPABILITY REMOVAL** : tester Desactiver/Activer 1 clic ; fallback manuel jamais exerce en reel.
- **REFONTE UX CONSOLE** : maquette Claude Design attendue ; au retour portage ES5/DSS.
- **ASSISTANT GUIDE** : confirmer 1er build AUTO au prochain domaine (recoller factory ENSEMBLE,
  L169) ; smoke delivery_snapshot.
- **Repo/DSS divers** : notebook 01 vs sonde MANUAL ; re-pointer 2 tools Semantic Model Query (L162) ;
  Durable Step Shell phase H (`DEPLOY_V1_3_DEV.md`) + 16 scenarios + smoke claim/complete ;
  gates securite phase 0 ; TroubleTickets repoint (ACTION="repoint") + smoke tickets ;
  promotion Source Data v3 prod ; recolls LAB accumules (`OWIsMind_LAB/README.md`) ;
  residuel L118 ; 2e agent TICKETS -> fiche client 360 (L097-L098).
- Backlog differe : auto-reattach front + toggle analyse approfondie ; DAG parallele ; pgvector ;
  skills write ; trust layer ajustements ; Evidence v3 ; 2e task user 2026-06-09 (a clarifier).
