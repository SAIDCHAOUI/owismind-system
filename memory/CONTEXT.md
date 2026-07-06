# CONTEXT - OWIsMind (memoire courte, chargee a CHAQUE session)

> Focus + pointeurs seulement. Detail durable : `PROJECT_STATE.md` ; lecons : `LESSONS.md` ; par jour : `sessions/*.md`.
> Gotchas actives (frontend/backend/agents/LAB/memoire) : `.claude/rules/*.md`, chargees AUTO selon les fichiers touches.
> **OWIsMind** = plugin Dataiku DSS : WebApp Vue 3 + Vite (front builde, servi par DSS) + backend Flask modulaire
> (`python-lib/owismind/`) qui parle aux agents via LLM Mesh et stocke en SQL direct (PostgreSQL), sans Flow au runtime.

## Focus courant

**Passage en production v1.1 (2026-07-06 Run 5) - repo PRET, RIEN encore deploye DSS.**
La PROCHAINE session commence par le deploiement + smoke en suivant le runbook `docs/DEPLOY_PROD_V1_1.md`.
- Agents promus DEV -> PROD_V1 par regeneration scriptee (`tools/promote_agents_to_prod.py`, idempotent :
  copie DEV + ids PROD + retrait du bloc `tickets_expert`) ; 3 revues Opus, 2 findings doc corriges.
- Plugin : `plugin.json` 0.0.1 -> 1.1.0, zip prod `owismind-upload.zip` (95 entrees, bundle `index-DDxpe_gw.js`).
- Nettoyage : plugins dev `owismind_dev`/`owismind_dev_v2` supprimes du disque ; conserves (choix user) :
  outillage dev, `project-documentation/`, mail relance ; impersonation GARDEE pour la beta ; tickets expert HORS PROD.
- Whitelist webapp = DYNAMIQUE (admin, cross-projet) : zero id cote plugin ; seuls ids par projet = cablage interne.
- 788 back + 352 node + 316 agents + 343 LAB verts, 0 tiret. Detail : `sessions/2026-07-06.md` (Run 5) + L139-L140.

**Source Data v3 (2026-07-06 Runs 2-4) - VALIDE DSS par l'user (« tout marche super »), zip `index-DYvX83Tl.js`
uploade + orchestrateur DEV recolle ; prod + dev stable INTACTS.**
- Livre : popover filtres (fermeture structurelle), zone Calculer (mesures choisies), plages de dates sur
  colonnes STRING a valeurs ISO, cascade `/source|/evidence/distinct` GET->POST, persistance des vues par (agent,
  dataset), CONTEXTE ECRAN -> AGENT (bloc `[ON SCREEN NOW]` + bandeau de consentement), filtre depuis cellule
  partout, menu de colonne + tri 3 etats + colonnes filtrees en orange.
- Reste a la demande : promotion vers le plugin DEV principal puis PROD (rebuild + orchestrateur PROD `Xrv7GvfG`
  avec le paragraphe SOURCE-DATA VIEW). Detail : `sessions/2026-07-06.md` (Runs 2-4) + L134-L138.

## Chaine des sessions (une ligne par run, detail dans sessions/<date>.md)
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
- DEPLOYER LA PROD v1.1 : suivre `docs/DEPLOY_PROD_V1_1.md` (plugin, projet prod, agents scenario A/B, smoke dont refus honnete tickets). Promotions futures = `tools/promote_agents_to_prod.py` puis recoll. Voir `sessions/2026-07-06.md` (Run 5).
- Promotion Source Data v3 (dev_v2 -> DEV principal puis PROD) : rebuild + orchestrateur PROD `Xrv7GvfG` avec le paragraphe SOURCE-DATA VIEW. Voir `sessions/2026-07-06.md` (Runs 2-4).
- LAB benchmark, recolls accumules (a batcher, `OWIsMind_LAB/README.md` + guides) : refonte launcher + route `/api/config` (L127-L129), visibilite complete des resultats L117, 2 fixes launcher L115, creation des 2 webapps Standard + variable `benchmark` (L103/L109), finir judge/aggregate/run complet L102.
- Auditer/valider en DSS DEV le residuel L118 (sous-agent revenus + tool lookup + `update_aligned_semantic_model.py` + re-dump) ; l'orchestrateur DEV est deja recolle. Voir `sessions/2026-07-02.md` (Run 1).
- 2e agent TICKETS : finaliser + pofiner (`dataiku-agents/PLAYBOOK_ADD_AGENT.md`) -> debloque la fiche client 360. L097-L098.
- Backlog differe : recueillir les ajustements user sur le trust layer ; consolidation SalesDrive v2 (cas d'ambiguite reelle) ; re-tester en DSS L040/L041 ; Evidence v3 (restriction admin datasets, keyset pagination) ; 2e task mentionnee par l'user le 2026-06-09 (a clarifier).
