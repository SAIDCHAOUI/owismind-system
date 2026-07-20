# Spec de conception : Durable Step Shell (couche agentique CoBuild-like), OWIsMind v1.3

> Date : 2026-07-17. Statut : validee par panel 3 voix (Fable 5 session lead + agent Fable 5 +
> GPT-5.6 Sol, 1 round de propositions independantes + 1 round de confrontation croisee D1-D7).
> Review user attendue au reveil ; la session de nuit implemente derriere feature flag,
> chemin legacy intact (rollback simple).
> Sources : recherche citee (Cobuild DSS 14.7, doc developpeur Dataiku, patterns petits modeles)
> + cartographie repo verifiee fichier:ligne. Artefacts du panel dans le scratchpad de session.

## 1. Probleme et objectifs

L'orchestrateur actuel est une boucle ReAct plate (3 nodes LangGraph, cap 8 tours), non durable
par conception, bornee par une deadline unique `MAX_RUN_SECONDS = 300` (stream_manager.py:75)
identique pour tous les modes : le mode `claude` (tier lent) est tue en plein run et l'utilisateur
voit `- run_timeout -` verbatim. Aucun plan explicite, memoire de travail limitee a PRIOR DATA
(3 resultats, portee conversation), aucun catalogue cross-domaine, aucune correlation
multi-datasets, aucune survie a un kill du backend.

Objectifs (exigences user A-J du brief) :
1. Runs longs robustes (5-30 min) qui survivent, progressent, rendent toujours un resultat.
2. Petits modeles d'abord : la fiabilite vient d'une couche logicielle deterministe
   (plan -> execute -> verify), pas du prompt (lecon L060).
3. Plan visible + memoire de travail persistee (ledger) + progression crescendo.
4. Multi-datasets (5-10+) sans exploser le contexte : catalogue schema-only + correlation en base.
5. Narration UI conservee et enrichie (plan qui se coche, activite persistante, erreurs conviviales).
6. S'appuyer sur l'Agent Factory v1.3 (ajout de domaine => catalogue + capability automatiques).
7. Compacite Dataiku-native : 4 nouveaux fichiers de code runtime, le reste en edits cibles.
8. Securite absolue : SELECT-only, caps de charge, aucune surcharge instance, read-only strict.

## 2. Decision centrale (la pepite)

**Le backend Flask 3.9 devient une machine de workflow durable ; le Code Agent 3.11 reste le
cerveau, invoque par commande bornee et stateless entre deux commandes.**

- Un appel LLM Mesh n'execute plus jamais un run complet : il execute UNE commande
  (`plan`, `execute` un step, `replan`, `review`, `synthesize`).
- PostgreSQL est la source de verite du run (plan, steps, events, curseur, lease). La RAM
  process (`_RUNS`) n'est plus qu'un cache legacy.
- Chaque etape validee est persistee AVANT de passer a la suivante ; un kill du backend, un
  restart DSS ou un OOM ne perd jamais le travail fait.
- Le chemin chat actuel (ReAct direct, valide DSS) reste INTACT et reste le defaut du trafic
  simple. La couche durable ne s'allume que sur les vraies taches complexes.

Justification : c'est le seul decoupage compatible a la fois avec la regle d'or DSS (l'etat d'un
run long ne doit jamais vivre uniquement dans la memoire du process webapp), le NON-DURABLE by
design de l'orchestrateur (nodes non idempotents, orchestrator.py:2465), l'absence d'annulation
LLM Mesh, le SELECT-only absolu de l'agent, et le pattern officiel Dataiku (thread + polling).

## 3. Repartition stricte des responsabilites

| Responsabilite | Flask 3.9 | Code Agent 3.11 |
|---|---|---|
| Auth, owner scope, resolution agent_key | Oui | Non |
| Persistance run/plan/steps/events, lease, retries, deadlines | Oui | Non |
| Attribution du prochain step, machine d'etat | Oui | Non |
| Contenu du plan, tache par specialiste, SQL de correlation | Non | Oui |
| Appel des sous-agents (CAPABILITIES) | Non | Oui |
| Garde SQL + execution read-only | Non | Oui |
| Gates deterministes de protocole (enums, caps, DAG) | Oui | Non |
| Sanity checks metier des resultats | Partages (protocole cote 3.9, metier cote 3.11) | |
| Narration (production / transport+persistance) | Transport + persistance | Production |
| Reponse finale (redaction / persistance chat_v5) | Persistance | Redaction |
| Reprise apres crash | Oui (lease + fencing) | Stateless |

Invariants : le modele ne voit JAMAIS un `agent_id`, une table physique, une connexion ni un
`run_id` exploitable ; le backend ne prend JAMAIS une decision metier ; l'agent n'ecrit JAMAIS
en base et ne lit JAMAIS les tables `webapp_*` (le ledger lui arrive par le prompt).

## 4. Runtime durable

### 4.1 Machine d'etat d'un run durable

`queued -> planning -> executing (boucle steps) -> [replanning ->] executing -> synthesizing ->
completed`. Etats terminaux alternatifs : `stopped`, `partial`, `failed`, `deadline_reached`,
`quota_blocked`. Le backend n'avance d'un etat qu'apres COMMIT du resultat precedent.
Execution v1.3 STRICTEMENT sequentielle (le schema de plan porte `depends_on` pour un futur DAG
parallele, differe).

### 4.2 Lease, fencing, superviseur (survie au kill)

- Colonnes `lease_owner` (uuid process+worker), `lease_until`, `worker_heartbeat_at`,
  `last_progress_at` sur le run ; `attempt_id` sur chaque tentative de step (fencing : une
  tentative tardive zombie ne peut jamais ecraser une tentative plus recente ; la finalisation
  verifie `attempt_id` en compare-and-set).
- Superviseur = UN thread lance par `register_routes(app)` : scan toutes les 10 s, claim
  atomique `UPDATE ... WHERE lease_until < now()`, **UN SEUL run recupere par scan** (reprise
  amortie, pas de tempete), reprise au premier step non termine (les steps `completed` ne sont
  jamais rejoues).
- Parametres : `LEASE_SECONDS=45`, `HEARTBEAT_SECONDS=10`, `RECOVERY_SCAN_SECONDS=10`,
  `MAX_ACTIVE_WORKFLOWS=8`, `MAX_ACTIVE_WORKFLOWS_PER_USER=1`, semaphore global
  `MAX_MESH_CALLS=3` (= le MAX_PARALLEL_AGENTS actuel : la charge Mesh ne depasse jamais
  le niveau actuel).
- Prerequis DSS documente : webapp Auto-start active (sinon la reprise attend le prochain
  poll/ouverture ; pas de scenario ni service externe, differes).
- L'IDLE n'est JAMAIS une preuve de mort : un silence Mesh prolonge declenche un event UI
  `waiting_upstream`, mais le lease reste renouvele tant que le worker heartbeat vit. Seul
  l'arret du heartbeat (process mort) libere le lease.
- Stop user = `stop_requested=true` durable ; l'appel Mesh en cours va jusqu'a son prochain
  chunk/timeout reseau (pas d'annulation Mesh) ; libelle UI honnete : "Arret demande, attente
  de la fin de l'appel en cours." Le resultat tardif est accepte ou ecarte selon `attempt_id`,
  `stop_requested`, `deadline_at`.

### 4.3 Deadlines (fix du bug + grille par mode)

Chemin DIRECT (legacy, fix immediat du bug user, livrable independamment du reste) :
`LEGACY_MAX_RUN_SECONDS_BY_MODE = {None: 300, "smart": 300, "pro": 600, "claude": 1200}`
(jamais de regression sous les 300 s actuels). L'event `run_timeout` est remplace par
`deadline_reached` mappe en message FR convivial + conservation du partiel deja streame.

Chemin DURABLE :
| Borne | smart | pro | claude |
|---|---|---|---|
| Run global (`deadline_at`) | 900 s | 1200 s | 1800 s |
| Budget d'un step (cooperatif) | 180 s | 300 s | 600 s |
| Idle warning (UI seulement) | 60 s | 90 s | 180 s |

- `ABANDON_AFTER_SECONDS=30` NE s'applique PLUS au durable : un onglet ferme ne tue plus le
  run (comportement Cobuild : le run continue, l'user retrouve tout au retour). Legacy inchange.
- `HARD_TTL_SECONDS=600` (eviction RAM) ne concerne plus que le legacy : un run durable n'est
  jamais evince (sa verite est en SQL).
- Valeurs en dur avec fallback + surchargeables via hub `run_settings.json` apres calibration DSS.

### 4.4 Retries et degradation

Retry AU NIVEAU STEP uniquement (jamais le run entier) : backoff 2 s puis 8 s + jitter,
3 tentatives max par step, `MAX_TOTAL_STEP_ATTEMPTS=18`. Transient uniquement (reseau, timeout
connexion, 5xx, rate-limit RPM Mesh) ; JAMAIS de retry sur quota bloquant (abandon propre
`quota_blocked`), agent desactive, garde SQL refusee, erreur de validation, ValueError/TypeError.
Tout chemin d'echec rend un PARTIEL honnete (steps termines conserves + message convivial).

## 5. Boucle plan / execute / verify

### 5.1 Gate de complexite (le trafic simple ne paie JAMAIS le plan)

`analysis_mode` par message : `auto` (defaut) | `deep` | `direct`.
- `direct` : chemin legacy, toujours.
- `deep` : workflow durable force (toggle UI sobre "Analyse approfondie", off par defaut).
- `auto` : pre-gate DETERMINISTE haute precision cote backend, 0 appel LLM : le workflow ne
  s'active que si (>= 2 domaines du catalogue matchent la question) OU (formulation explicite
  de comparaison/correlation multi-source). Tout le reste part en direct. Un faux negatif est
  traite par le ReAct valide ; un faux positif coute cher : la gate privilegie la PRECISION.
- Le planner peut lui-meme s'effondrer en mode direct (plan a 1 step execute inline) si la
  question s'avere simple.

### 5.2 Schema du plan (with_json_output strict, lecon L056)

Champs : `plan_version`, `goal`, `complexity`, `steps[]` avec `{id "S1..", kind, title <=160c,
capability_keys[], task, depends_on[], produces "#Sx", checks[]}`, `final_checks[]`.
`kind` dans une enum fermee v1.3 : `specialist_query`, `attribute_lookup`, `correlate`,
`render`, `clarify`. Bornes deterministes : `MAX_PLAN_STEPS=12`, `MAX_REPLANS=2`,
`MAX_SPECIALIST_STEPS=10`, `MAX_DEPENDENCIES_PER_STEP=5`, DAG acyclique, ids reimposes par le
code, AUCUNE table/connexion/SQL/agent_id dans le plan. Steps d'ecriture, mail, publication,
approbation humaine native, parallelisme : DIFFERES (le schema les permet deja).

### 5.3 Verification economique (gates 0-token d'abord)

1. Validation JSON stricte de toute sortie machine (planner, resultats, reviewer).
2. Checks deterministes par step (`non_empty`, `metric_present`, `join_key_present`...).
3. Self-correction guidee par l'execution pour le SQL (l'erreur DB nettoyee est renvoyee au
   modele, 2 corrections max) : le pattern qui rend les petits modeles competitifs.
4. UN `review` LLM structure seulement en fin de plan multi-source
   (`{sufficient, missing[], confidence, reason}`) ; les gates deterministes restent prioritaires.
5. Replanner appele UNIQUEMENT sur : retries epuises, resultat vide inattendu, cle de jointure
   absente, source/metrique manquante au review, `clarify`/`out_of_scope` d'un specialiste.
   Il conserve obligatoirement les steps termines, ne peut jamais les reinterpreter.

## 6. Memoire de travail (ledger)

- Verite = SQL (`runs`, `run_steps`, `run_events`). RAM = buffer d'events de la tentative
  courante + generateur Mesh + lease, rien de necessaire a une reprise.
- A chaque commande, le BACKEND construit un bloc `[WORKFLOW PROGRESS]` compact (goal, step
  courant, statuts, resumes 1 ligne des steps faits avec refs `#Sx`, schemas des dependances,
  points non resolus), place EN FIN de prompt (recence, pattern recitation). L'agent ne lit
  aucune table : le ledger transite par le prompt (decision panel D6, evite tout grant DB
  supplementaire a l'agent).
- Budgets de contexte dynamiques par mode (hors system prompt) : total ~26000 (smart) /
  35000 (pro) / 48000 (claude) caracteres, ventiles (goal+step 3000, plan compact 4-6000,
  ledger 6-10000, dependances+previews 8-20000, catalogue 3-6000, erreur 2-3000). Regles de
  compaction dans cet ordre : previews des steps sans dependance d'abord, anciens resultats en
  1 phrase, colonnes catalogue non selectionnees ; JAMAIS tronques : goal, step courant, erreur
  courante, refs `#Sx`. Compression RESTAURABLE : les sorties completes restent en SQL.
- Rows brutes JAMAIS dans le contexte : previews <= 15 lignes. Entre deux echanges, PRIOR DATA
  existant inchange (les resultats finaux du run alimentent `chat_v5.generated_sql` comme
  aujourd'hui, `recall_prior_result` garde son contrat).

## 7. Multi-datasets : catalogue et correlation

### 7.1 Catalogue (possede par la FACTORY, design-time only)

- Nouveau module `owismind_factory/catalog.py` ; table/dataset `OWIsMind_agent_catalog_v1`
  expose dans le Flow, construite UNIQUEMENT a design-time, generations APPEND-ONLY
  (`generation_id`), `capabilities.json` designe la generation active ; publication apres
  validation humaine (jamais d'inference silencieuse des `join_hints`).
- Contenu par (capability, dataset, colonne) : descriptions metier, synonymes, types,
  join_hints, `search_text` ; `connection_name` + `physical_table` STRICTEMENT server-only
  (jamais prompt, events, routes). AUCUN sample de valeur en v1.
- Recherche runtime : exact match + `ILIKE` (top 5 datasets, 12 colonnes/dataset, filtre aux
  capabilities `enabled`, explication deterministe). tsvector/trigram/pgvector DIFFERES tant
  que leur disponibilite DSS n'est pas prouvee. La qualite semantique vient des descriptions
  et du planner, pas des embeddings.
- Pipeline factory : step `catalog` ajoute apres `capability` dans `pipeline.py` ; `registry.py`
  gagne les champs optionnels `catalog_generation`/`catalog_dataset`/`connection_key`
  (retro-compatibles v1.2 ; une capability sans catalogue reste utilisable mais pas candidate
  a `correlate`).

### 7.2 Correlation : VRAI JOIN SQL read-only (decision panel D1)

La jointure Python de resultats capes est PROUVEE biaisee (un cap 500 lignes avant jointure
fausse couverture et agregats) : elle n'est conservee qu'en fallback explicite pour deux
resultats petits ET complets. La voie normale :
1. le catalogue selectionne datasets + colonnes ;
2. le modele ne voit que des alias logiques `d1..d5` + schemas ;
3. il produit un SQL uniquement contre ces alias ;
4. le CODE substitue les CTE depuis les tables physiques whitelistees de la generation active ;
5. garde SQL (extension parametrique du `guard_custom_sql` existant, qui valide DEJA FROM/JOIN
   contre un ensemble + CTE auto-decouvertes : delta 1 -> N tables, pas un moteur neuf) ;
6. `EXPLAIN` -> preview `LIMIT 10` -> sanity checks Python (non-vide si requis, colonnes/types,
   nombres finis, cap rows, toutes sources obligatoires utilisees, pas de duplication de cle,
   coherence des totaux) -> execution finale bornee (500 lignes, `SET LOCAL
   transaction_read_only TO on`, `statement_timeout` 30 s) ;
7. 2 corrections LLM max avec l'erreur DB nettoyee.
Contraintes v1.3 : toutes les sources sur PostgreSQL `SQL_owi`, pas de cross-connection, pas de
table temporaire, pas de materialisation, pas de transfert de dataset vers Python.

## 8. Protocole backend <-> agent (decision panel D6, hybride)

- DESCENDANT : token machine minimal ajoute en fin de message (canal token existant,
  last-token-wins anti-forge comme `owi:mode`) :
  `⟦owi:workflow=v1;command=plan|execute|replan|review|synthesize;run=<id>;step=<id>;attempt=<id>⟧`
  (memes delimiteurs speciaux que les tokens `⟦owi:mode=⟧`/`⟦owi:prior=⟧` existants)
  + le bloc `[WORKFLOW PROGRESS]` construit par le backend. Sans token, l'orchestrateur =
  chemin legacy strictement identique (rollback et benchmarks preserves).
- MONTANT : resultats machine via eventKind dedie `OWI_WORKFLOW_CONTROL` (chunk event du stream
  Mesh, canal identique aux events geles actuels donc deja prouve bout en bout ; cap 16 Ko,
  valide avant persistance, JAMAIS relaye au frontend). Fallback documente si un probe DSS
  montre une troncature : bloc JSON balise en fin de contenu (pattern AGENT_RESULT prouve).
- Cote agent : second chemin dans `process_stream` (`parse_workflow_control` -> mini-graphe
  LangGraph par commande, sans checkpointer : PostgreSQL cote backend EST le checkpoint).
  Reutilisations obligatoires : CAPABILITIES, hub loader, pick_loop_llm, _run_subagents,
  extraction SQL/trace, _record_artifact, events geles. LoopChat reste legacy-only.

## 9. UI (charte Orange)

- NOUVEAU `RunPlan.vue` : carte "Plan d'analyse" au fil du chat ; progression `3/5` ; une ligne
  par step (statuts pending/running/completed/retrying/failed/superseded, duree) ; geometrie
  carree, filets 1px, tokens semantiques, orange UNIQUEMENT sur le step actif, aucun
  gradient/ombre/animation decorative, reduced-motion respecte, pas d'emoji.
- Narration existante INCHANGEE ; nouveaux events timeline : `PLAN_READY, STEP_STARTED,
  STEP_RETRYING, STEP_COMPLETED, VERIFYING, REPLANNING, WAITING_UPSTREAM, PARTIAL_RESULT`.
- "Afficher l'activite" (pattern Cobuild) : detail des events persiste, rechargeable apres
  refresh/navigation via `GET /chat/activity?exchange_id=` ; le SQL reste dans Evidence.
- Reconnexion : `GET /chat/active?session_id=` au chargement -> rattache le run actif, rejoue
  les events SQL depuis cursor 0, reprend le polling dans la meme bulle.
- Erreurs conviviales (mapping i18n, fini le verbatim) : `deadline_reached`, `waiting_upstream`,
  `quota_blocked`, `rate_limited`, `agent_disabled`, `partial_result` ; `run_lost` = legacy only.
- Bouton "Continuer l'analyse" sur `partial`/`deadline_reached`/`stopped` (nouvel exchange qui
  repart du ledger). La reprise APRES CRASH, elle, est automatique (superviseur).

## 10. Schemas SQL (idiome _vN, migrations.py, prefixe PROJECT_KEY, COMMIT, parametrage)

Trois tables runtime backend (DDL complets valides par le panel, resume) :
- `webapp_agent_runs_v1` : run_id PK, exchange_id UNIQUE, session_id, user_id, agent_key, mode,
  status, phase, plan_revision, replan_count, step_cursor, next_event_seq, prompt_lang,
  stop_requested, lease_owner, lease_until, worker_heartbeat_at, last_progress_at, deadline_at,
  retry_at, error_code, answer_text, usage_json, usage_accounted, created/updated/finished_at.
  Index : (user_id,status,updated_at DESC), (status,lease_until), (session_id,updated_at DESC),
  (exchange_id). AUCUN agent_id/table physique/SQL dans cette table.
- `webapp_agent_run_steps_v1` : PK (run_id, step_id), ordinal, plan_revision, kind, title,
  task_json (<=8000c), depends_on_json, output_ref, checks_json, status, attempt_no, attempt_id,
  max_attempts, next_retry_at, result_status, result_summary (<=2000c), result_schema_json,
  model_view_json (<=24000c), generated_sql_json (caps capture existants), artifacts_json (<=8),
  usage_json, error_code, started/finished/updated_at. Index : (run_id,ordinal),
  (status,next_retry_at).
- `webapp_agent_run_events_v1` : PK (run_id, seq), attempt_id, event_type, payload (<=8 Ko),
  created_at. `seq` alloue via `runs.next_event_seq`. Ecriture BATCHEE : flush toutes les 1 s,
  a 8 Ko, ou a chaque transition de step (le pattern INSERT batch existe deja, events.py:282) ;
  `answer_delta`/narration coalesces ; JAMAIS de resultat brut ni d'event `OWI_WORKFLOW_CONTROL`.
  Retention 14 jours apres terminaison, purge interne bornee (<=1000 runs/passage).
Catalogue : `OWIsMind_agent_catalog_v1` possede par la factory (section 7.1, DDL dans catalog.py).

`chat_v5` inchangee : phase 1 au start, phase 2 unique dans `finalize_exchange` (SQL des steps
fusionnes, artifacts fusionnes, usage additionne) ; finalisation IDEMPOTENTE reprise apres crash
(UPSERT artifacts, UPDATE chat_v5, usage garde par `usage_accounted=false` dans la MEME
transaction que les increments users/usage_monthly : zero double comptage).

## 11. Securite (invariants, tous testes)

1. SELECT-only absolu de l'agent : select/with unique, sans `;`, denylist, pas de
   pg_catalog/information_schema, allowlist de tables (1 -> N parametrique), LIMIT cap,
   transaction_read_only + statement_timeout 30 s, compte DB SELECT-only (grant niveau base).
2. Trois niveaux de whitelist : front n'envoie que `agent_key` ; Flask resout via
   webapp_settings ; l'agent resout les specialistes via CAPABILITIES. Le plan ne peut contenir
   que des capability_key actives ; une capability desactivee en cours de run bloque le step.
3. Caps de charge (durs, testes) : 8 workflows actifs, 1/user, 3 appels Mesh simultanes,
   12 steps, 18 tentatives, 2 replans, 3 tentatives/step, 30 s/SQL, 500 lignes capturees,
   15 lignes au modele, 8 artifacts, 16 Ko controle, 8 Ko event public. Au-dela : `queued`.
4. Donnees vers le modele : descriptions, schemas, types, synonymes, agregats bornes. JAMAIS :
   tables completes, resultats intermediaires complets, sample values (off v1), noms physiques,
   credentials, traces brutes.
5. Skills futurs : CAPABILITIES etendu avec `{kind, effect: read|render|write, idempotent,
   requires_approval}` ; le runner v1.3 n'accepte que read|render ; tout write refuse tant que
   validation humaine + idempotence + journal des effets + reversibilite ne sont pas livres
   (mail differe ; PDF local possible en render sans publication externe).
6. Deux modes d'echec Mesh geres : rate-limit RPM -> retry backoff ; quota bloquant -> abandon
   propre. Logs sans prompt/rows/credentials/controle interne.

## 12. Ce qui est explicitement differe

PostgresSaver LangGraph (le backend SQL est le checkpoint) ; reprise au milieu d'un appel Mesh ;
DAG parallele ; pgvector/embeddings ; AI Search natif ; jointures cross-connection ;
materialisation intermediaire ; scenario DSS de reprise ; DSSFuture ; ecriture de Flow ; mails
et actions externes ; approbation humaine native (toolValidationRequests) ; fork/time-travel de
runs ; migration des anciens events ; remplacement de chat_v5 ; reprise auto au boot autrement
que via superviseur amorti ; refactor des plafonds de contexte legacy (SUBAGENT_*, PRIOR_*).

## 13. Fichiers (compacite)

NOUVEAUX (4 code + 2 seeds) :
- `OWIsMind_PRD_V1_3_DEV/plugin/owismind/python-lib/owismind/agents/durable_runner.py` (superviseur, machine d'etat,
  semaphore Mesh, deadlines, backoff, buffer events, finalisation idempotente ; zero langchain)
- `OWIsMind_PRD_V1_3_DEV/plugin/owismind/python-lib/owismind/storage/run_state.py` (CRUD owner-scoped, lease atomique,
  fencing, events cursorises, stop durable, finalize)
- `OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/catalog.py`
- `OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend/src/components/chat/RunPlan.vue`
- Seeds hub : `owismind_hub/run_settings.json` + `owismind_hub/prompts/orchestrator_workflow.md`
  (sections PLANNER/REPLANNER/REVIEWER/SYNTHESIZER, fallbacks embarques).
EDITS : stream_manager.py (routage durable + deadlines legacy par mode), streaming.py
(normalisation `OWI_WORKFLOW_CONTROL`), routes.py (gate, /chat/active, /chat/activity, poll
routeur, stop durable, superviseur), migrations.py (+3 tables), context.py (pre-gate + blocs),
OWIsMind_orchestrator.py (chemin workflow), factory pipeline.py + registry.py, front
timelineModel.js / useChatStream.js / backend.js / chat.js / MessageAgent.vue / i18n extra.js.
Pas de nouveau package, pas de service, pas de broker, pas de dependance, pas de scenario runtime.

## 14. Tests et validation

- Unittest par module : run_state (concurrence simulee, crash entre chaque sous-phase de
  finalisation, lease/fencing, params/COMMIT), durable_runner (worker tue entre 2 steps, lease
  expire, tentative tardive rejetee, 1 run/user, 3 slots Mesh), orchestrateur (anti-forge token,
  structured outputs, plan invalide refuse, legacy strictement inchange), correlate (DDL/DML/
  systeme/semicolon/table inventee/source hors capability refuses, jointure correcte sur
  fixtures, timeout, vide, zero ecriture), catalog factory (dry-run, idempotence, ZERO delete,
  aucune valeur metier), front (reducer pur, i18n).
- Gates : suites completes plugin/factory/LAB + build Vite, AVANT tout commit de code.
- Campagne DSS DEV (post-session, avec l'user) : 16 scenarios obligatoires (runs longs smart/
  claude, stop_backend entre steps, refresh, onglet ferme, silence Mesh, rate limit, quota,
  specialiste indisponible, SQL refuse, correlation revenus x tickets, plan 5 datasets, stop
  pendant appel bloque, capability desactivee en vol, double poll/reprise, aucune donnee brute
  depuis le front). Gates avant activation : feature flag `durable_workflow` sur l'orchestrateur
  DEV uniquement, compte DB confirme SELECT-only, statement_timeout confirme, Auto-start
  confirme, smoke legacy inchange, benchmark comparatif 3 modes, audit securite final.

## 15. Decoupage d'implementation (session de nuit, fichiers disjoints par tache)

- T1 fix timeout legacy (stream_manager + mapping erreurs front) : livrable seul, corrige le
  bug user immediatement.
- T2 stockage durable (migrations + run_state + tests) : zone SQL sensible = Claude.
- T3 durable_runner + routage stream_manager + routes (superviseur, machine d'etat) : Claude.
- T4 protocole workflow orchestrateur (chemin agent + prompts hub + tests) : Claude.
- T5 streaming durable (OWI_WORKFLOW_CONTROL, fusion SQL/usage/artifacts) : Claude.
- T6 catalogue factory (catalog.py + pipeline + registry + seeds + tests) : Codex OK (borne,
  non sensible), re-verifie cote Claude.
- T7 correlate (garde etendue + CTE server-side + tests adversariaux) : zone SQL sensible = Claude.
- T8 UI (RunPlan.vue + reducer + reconnexion + i18n + charte-orange-reviewer) : Codex possible
  sur le mecanique, review Claude.
- T9 gates finales : suites completes + build + audit securite adversarial.
Ordre : T1 d'abord ; T2 -> T3 -> T5 ; T4 et T6 paralleles ; T7 apres T4 ; T8 apres T3 ; T9 final.
