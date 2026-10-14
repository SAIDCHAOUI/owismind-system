# CONTEXT - OWIsMind (memoire courte, chargee a CHAQUE session)

> Focus + pointeurs seulement. Detail durable : `PROJECT_STATE.md` ; lecons : `LESSONS.md` ; par jour : `sessions/*.md`.
> Gotchas actives (frontend/backend/agents/LAB/memoire) : `.claude/rules/*.md`, chargees AUTO selon les fichiers touches.
> **OWIsMind** = plugin Dataiku DSS : WebApp Vue 3 + Vite (front builde, servi par DSS) + backend Flask modulaire
> (`python-lib/owismind/`) qui parle aux agents via LLM Mesh et stocke en SQL direct (PostgreSQL), sans Flow au runtime.

## Focus courant

**2026-10-14 run 3 : Agent Factory (modeles centraux, Settings, prompt metier IA, garde-fous injection).**
Detail `sessions/2026-10-14.md` run 3, lecons L192-L194. Commits ccd8b35..0a3ce0e POUSSES (demande user).
- `owismind_hub/models.json` central ; Settings par agent ; brouillon IA non actif ; Improve editable ; scanner anti-injection fail-closed ; revue securite Fable faite et corrigee (834 tests OK).
- NON deploye dans DSS : l'user n'a rien recolle depuis le debut de la session. Pas a pas donne dans le chat.
- Non valide : UI jamais vue dans un navigateur, rien teste sur vrai Mesh/DSS. Restreindre la webapp console aux admins (F2).

**2026-10-14 : refonte de l'Agent Factory Console REJETEE par l'user, a refaire en session neuve.**
- Prompt pret : `dev-harness/rejected-console-redesign-2026-10-14/NEXT_SESSION_PROMPT.md` (cible :
  3 ecrans = schema orchestrateur -> sous-agents avec actions dessus, ajout, retrait ; garder le
  vocabulaire DSS ; une seule session, sans sous-agent).
- Working tree : console MODIFIEE par la refonte rejetee (non commitee, copie dans ce meme dossier) ;
  reference fonctionnelle = git HEAD. Backend + owismind_factory INTACTS.
- Nouveau : simulateur console `dev-harness/console_sim.py` (port 5198, vrai backend.py sur faux projet).
- Zip DEV regenere 13/10 : `ready-for-dataiku/owismind_v1_3-upload.zip` ; anciens zips dans `archives/`.
- Lecon : la "Sonde" ne lit QUE le projet courant (lecture seule) ; libelles "Avance / Sonde / Mode
  expert / Analyser l'instance" incomprehensibles pour l'user ; le probleme etait la DISPOSITION, pas
  le nombre d'etapes. git bloque par la licence Xcode (`sudo xcodebuild -license`).

**2026-10-14 run 1 : tableaux de resultat agent = resultat COMPLET pagine + compteur honnete.**
Detail `sessions/2026-10-14.md`, lecon L190. Commit `84a1cde` POUSSE (demande user).
- Cause : agents capent la capture a 50 lignes ET comptent apres la coupe ("50 lignes" pour 1000).
- Fix plugin seul : route `/evidence/result-rows` (relit le SELECT stocke de l'agent, LIMIT/OFFSET,
  COUNT exact 1re fenetre, lecture seule, garde `check_rerunnable_select`) ; front `useResultRows`
  dans `ArtifactTable` + `EvidenceResult` : "100 lignes affichees sur T", +20 au scroll, max 500.
- Zip DEV FINAL 14/10 19h44 (`owismind_v1_3-upload.zip`, inclut le run 2) : A UPLOADER + redemarrer le backend.
- Non valide : rendu visuel (pas de Chromium local) et DSS.
- Run 2 : regle user "SQL = creer + lire" ; audit ALTER/DELETE/UPDATE ; WORKFLOW DURABLE RETIRE
  (superviseur, 2 DELETE, 3 tables, routes, UI) ; ZERO ALTER ; seul DELETE restant = quota admin.

## Chaine des sessions (une ligne par run, detail dans sessions/<date>.md)
- 2026-10-14 Run 3 : factory models.json + Settings + prompt metier IA + garde-fous injection + revue Fable, pousse. L192-L194. Voir `sessions/2026-10-14.md` run 3.
- 2026-10-14 Run 2 : audit SQL + retrait workflow durable + zero ALTER. L191. Voir `sessions/2026-10-14.md` run 2.
- 2026-10-14 Run 1 : resultat agent complet pagine + "N sur T lignes" (route /evidence/result-rows), zip DEV, commit 84a1cde pousse. L190. Voir `sessions/2026-10-14.md`.
- 2026-10-13/14 : demo locale v1.3 + zip DEV + rangement archives + simulateur console + refonte console (Fable brief + Opus impl) REJETEE ; prompt de reprise ecrit. Pas de log de session (git bloque Xcode).
- 2026-08-13 Run 3 (soir) : etat des lieux moteur natif + 1er zip DEV v1.3 (deploye, teste par l'user) + 4 correctifs UX. L187-L189. Voir `sessions/2026-08-13.md` run 3.
- 2026-08-12/13 Runs 1-2 : vague UX complete (harness "yeux" + premium partout + Analyze v3 + fusion Evidence + finitions). L183-L186. Voir `sessions/2026-08-13.md`.
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
- **RESULTAT COMPLET (14/10)** : upload zip + test DSS du compteur/scroll ; propose : vrai `row_count`
  dans les 3 agents (recoll DSS) ; chart encore sur 50 lignes. Voir `sessions/2026-10-14.md`.
- **RE-UPLOAD + REVALIDATION DSS** : le zip `owismind_v1_3-upload.zip` du 13/08 18h52 porte les
  4 correctifs UX (non revalides en DSS) ; verifier clair ET sombre. Arbitrages user encore ouverts :
  bloc contexte analyze mono-mesure (toutes les mesures = evolution backend) ; micro-labels 0.08em
  a enteriner dans la charte. Voir `sessions/2026-08-13.md` run 3.
- **Case admin "moteur natif" (propose, non fait)** : exposer `native_engine` dans l'editeur de
  profil ET corriger `applyEditor` qui l'efface (L187 ; `durable_workflow` RETIRE le 14/10).
- **Nettoyage differe front** : API calc*/analyze* de aggregateSurface sans consommateur UI (la
  memoire de vue persiste calcColumn/calcFns) ; dead CSS .pf-lab (AdminView) ; tirets em/en dans
  test/agentPick + evidenceProof (pre-existants). Voir `sessions/2026-08-13.md`.
- **Moteur natif (06/08 run 2)** : entree de TEST flag `native_engine` + checklist
  `OWIsMind_PRD_V1_3_DEV/docs/NATIVE_ENGINE.md` (jamais execute contre un vrai Mesh ; ne pas ouvrir
  la modale de profil de cette entree, L187) ; backlog = recall natif, sql_id par artefact.
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
  gates securite phase 0 ; TroubleTickets repoint (ACTION="repoint") + smoke tickets ;
  promotion Source Data v3 prod ; recolls LAB accumules (`OWIsMind_LAB/README.md`) ;
  residuel L118 ; 2e agent TICKETS -> fiche client 360 (L097-L098).
- Backlog differe : auto-reattach front + toggle analyse approfondie ; DAG parallele ; pgvector ;
  skills write ; trust layer ajustements ; Evidence v3 ; 2e task user 2026-06-09 (a clarifier).
