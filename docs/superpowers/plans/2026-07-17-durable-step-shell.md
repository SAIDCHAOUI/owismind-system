# Durable Step Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.
> **Compagnon OBLIGATOIRE** : `docs/superpowers/specs/2026-07-17-agentic-runtime-design.md`
> (le spec). Chaque tache cite ses sections du spec ; le spec fait foi sur l'architecture.
> Ce plan verrouille les CONTRATS (fichiers, signatures, constantes, cas de test, commandes) ;
> l'implementeur ecrit le code en suivant les patterns EXISTANTS du repo cites dans chaque tache.

**Goal:** Couche agentique durable "CoBuild-like" pour l'orchestrateur OWIsMind v1.3 : runs longs
robustes, plan/execute/verify pour petits modeles, ledger persistant, catalogue multi-datasets,
correlation SQL read-only, UI plan visible ; chemin legacy intact derriere feature flag.

**Architecture:** Backend Flask 3.9 = machine de workflow durable (etat PostgreSQL : runs/steps/
events + lease + fencing attempt_id + superviseur amorti) qui invoque le Code Agent 3.11 par
commandes bornees (plan/execute/replan/review/synthesize) via token machine descendant + bloc
[WORKFLOW PROGRESS] dans le prompt, resultats machine remontes par eventKind OWI_WORKFLOW_CONTROL.

**Tech Stack:** Python 3.9 (backend, ZERO langchain), Python 3.11 LangGraph (Code Agent),
PostgreSQL via SQLExecutor2 (parametrage dataiku.sql Constant/toSQL), Vue 3 + Vite, unittest.

## Global Constraints

- NO INSTALL (npm/pip/brew/npx d'install interdits) ; aucune dependance nouvelle.
- SQL : prefixe PROJECT_KEY via les helpers de migrations.py, COMMIT en post_queries, requetes
  parametrees, citation `public."..."`. JAMAIS d'ALTER (sauf ADD COLUMN IF NOT EXISTS).
- Agent : SELECT-only absolu (guard, transaction_read_only, statement_timeout 30 s).
- Le front n'envoie jamais agent_id/table/SQL ; whitelist serveur a 3 niveaux (spec section 11.2).
- Chemin legacy STRICTEMENT inchange sans token workflow (tests anti-regression obligatoires).
- Code + commentaires en anglais ; ZERO tiret cadratin (U+2014) / demi-cadratin (U+2013) partout.
- UI : charte Orange (docs/cadrage/CHARTE_ORANGE_UI.md) ; review par charte-orange-reviewer.
- Feature flag : `durable_workflow` (profil agent, via webapp_settings admin) OFF par defaut.
- Gates par tache : suites vertes AVANT commit, sortie LUE (jamais d'affirmation sans preuve).
- Zones Codex interdites : migrations.py, run_state.py, garde SQL, orchestrateur (regles
  model-routing) ; tout diff Codex re-verifie cote Claude avant commit.

**Commandes de verification (baseline du 2026-07-17 : TOUT VERT)**
```bash
python3 -m unittest discover -s Plugin/owismind/tests            # 830 tests OK (baseline)
python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests          # 516 tests OK, 2 skips
cd Plugin/owismind/frontend && npm test                          # node --test, OK
# compile-check Vite SANS toucher resource/ (T8/T9 seulement) :
cd Plugin/owismind/frontend && npm run build -- --outDir /private/tmp/owismind-vite-check --emptyOutDir
```

---

### Task T1 : Fix timeout legacy par mode + erreurs conviviales (quick win autonome)

Spec : sections 1, 4.3. Corrige LE bug user immediatement, livrable seul.

**Files:**
- Modify: `Plugin/owismind/python-lib/owismind/agents/stream_manager.py` (constantes :36-81,
  `_stop_reason` :121-140, `start_run` :173-224, `_worker` :265-538)
- Modify: `Plugin/owismind/python-lib/owismind/api/routes.py` (`chat_start` :357, passe mode)
- Modify: `Plugin/owismind/frontend/src/components/chat/MessageAgent.vue` (:385, :422)
- Modify: `Plugin/owismind/frontend/src/i18n/extra.js`
- Test: `Plugin/owismind/tests/test_stream_manager_deadlines.py` (NOUVEAU)

**Interfaces (produites, gelees pour T3):**
```python
LEGACY_MAX_RUN_SECONDS_BY_MODE = {None: 300.0, "smart": 300.0, "pro": 600.0, "claude": 1200.0}
def resolve_run_deadline(mode):  # -> float, fallback 300.0 sur mode inconnu
def start_run(..., mode=None):   # signature existante + mode keyword (retro-compatible)
# _stop_reason(run_id, started_at, deadline_s) : le code d'erreur "run_timeout" devient
# "deadline_reached" ; "run_abandoned" inchange.
```

- [ ] **S1 tests d'abord** : `test_stream_manager_deadlines.py` : (a) resolve_run_deadline
  rend 300/300/600/1200/fallback ; (b) _stop_reason rend None sous la deadline du mode et
  "deadline_reached" au-dela (monkeypatch de time.monotonic, pattern des tests existants du
  module) ; (c) start_run stocke le mode et _worker applique la deadline du mode ; (d) le
  chemin sans mode garde exactement 300.0. Run : `python3 -m unittest Plugin.owismind.tests.
  test_stream_manager_deadlines -v` -> FAIL attendu.
- [ ] **S2 implementer** stream_manager (constantes + plumbing mode) + routes.py (passer le
  mode deja resolu ligne ~459-473 a start_run).
- [ ] **S3 front** : dans MessageAgent.vue, remplacer l'affichage verbatim `item.message` des
  events error par un lookup i18n : cles `runError.deadline_reached`, `runError.run_timeout`
  (alias legacy), `runError.run_abandoned`, `runError.agent_unavailable`, fallback generique
  `runError.generic`. Textes FR/EN dans extra.js (suivre le format existant du fichier), ex FR
  deadline : "Le temps maximal d'analyse a ete atteint. Les resultats deja obtenus restent
  affiches." AUCUN code technique brut a l'ecran.
- [ ] **S4 gates** : suite backend complete (830+4 attendus OK) + `npm test` front.
- [ ] **S5 commit** : `fix(runs): per-mode legacy deadlines (claude 1200s) + friendly run error
  messages`

---

### Task T2 : Stockage durable (migrations +3 tables, run_state.py) [Claude only, zone SQL]

Spec : sections 4.2, 10. Patterns de reference OBLIGATOIRES : `storage/artifacts.py` (UPSERT
owner-stamped), `storage/usage.py` (transaction unique), `storage/events.py:282-290` (INSERT
batch), `storage/migrations.py` (idiome `_vN`, `_DDL_BY_LOGICAL`, `_INDEXES_BY_LOGICAL`,
`ensure_*`).

**Files:**
- Modify: `Plugin/owismind/python-lib/owismind/storage/migrations.py` (+3 DDL du spec section 10 :
  `webapp_agent_runs_v1`, `webapp_agent_run_steps_v1`, `webapp_agent_run_events_v1` + indexes)
- Create: `Plugin/owismind/python-lib/owismind/storage/run_state.py`
- Test: `Plugin/owismind/tests/test_run_state.py` (NOUVEAU)

**Interfaces (produites, gelees pour T3/T5):**
```python
# run_state.py - toutes owner-scoped quand user_id est fourni, toutes parametrees + COMMIT
def create_run(exchange_id, session_id, user_id, agent_key, mode, deadline_at)  # -> run_id (uuid4)
def claim_run(run_id, lease_owner, lease_seconds)      # -> bool, UPDATE atomique WHERE lease expiree
def renew_lease(run_id, lease_owner, lease_seconds)    # -> bool (False si le lease a change de main)
def load_run(run_id, user_id=None)                     # -> dict | None
def load_ledger(run_id)                                # -> {"run": dict, "steps": [dict, ordonne par ordinal]}
def save_plan(run_id, plan_dict, plan_revision)        # remplace les steps pending, garde les completed
def start_step(run_id, step_id, attempt_id)            # -> bool (CAS pending/failed -> running)
def complete_step(run_id, step_id, attempt_id, result) # -> bool (FENCED : echoue si attempt_id != courant)
def fail_step(run_id, step_id, attempt_id, error_code, retry_at=None)  # -> bool (fenced)
def append_events(run_id, events)                      # -> next_seq ; batch INSERT, seq via runs.next_event_seq
def read_events(run_id, user_id, cursor, limit=500)    # -> {"events": [...], "cursor": int, "done": bool, "error": code|None}
def request_stop(run_id, user_id)                      # -> bool (durable, owner-scoped)
def find_recoverable_runs(limit=1)                     # -> [run_id] (status actif ET lease expiree)
def set_run_status(run_id, status, error_code=None)
def finalize_exchange_guard(run_id)                    # -> bool (CAS usage_accounted false->true, meme transaction que les increments usage, spec 10)
def read_activity(exchange_id, user_id)                # -> [events] (join runs sur exchange_id, owner-scoped)
def purge_finished_runs(older_than_days=14, max_runs=1000)  # borne, jamais au chemin chaud
```

- [ ] **S1 tests d'abord** (executor SQL mocke, pattern des tests storage existants) :
  create/load owner-scope (404 logique si mauvais user) ; claim_run refuse si lease valide
  d'un autre owner, accepte si expiree ; renew refuse apres vol de lease ; complete_step
  refuse un attempt_id perime (FENCING = le test central) ; save_plan preserve les steps
  completed ; append_events sequence monotone + batch unique ; read_events curseur ;
  finalize_exchange_guard idempotent (2e appel False) ; purge bornee ; CHAQUE requete
  parametree (assert sur l'absence d'interpolation brute, pattern test_sql_builders existant).
  Run cible -> FAIL.
- [ ] **S2 DDL** dans migrations.py (copier les colonnes EXACTES du spec section 10).
- [ ] **S3 implementer** run_state.py. AUCUNE donnee brute dans events (cap payload 8000 c,
  tronque + marqueur). Run tests cible -> PASS.
- [ ] **S4 gates** : suite backend complete.
- [ ] **S5 commit** : `feat(runs): durable run storage (runs/steps/events _v1, lease + attempt
  fencing)`

---

### Task T3 : durable_runner + routage stream_manager + routes [Claude only]

Spec : sections 4, 5.1, 9 (routes). Depend de T1+T2.

**Files:**
- Create: `Plugin/owismind/python-lib/owismind/agents/durable_runner.py`
- Modify: `Plugin/owismind/python-lib/owismind/agents/stream_manager.py` (routage durable)
- Modify: `Plugin/owismind/python-lib/owismind/agents/context.py` (pre-gate + token + PROGRESS)
- Modify: `Plugin/owismind/python-lib/owismind/api/routes.py` (gate, /chat/active, /chat/activity,
  poll routeur, stop durable, start_supervisor dans register_routes)
- Test: `Plugin/owismind/tests/test_durable_runner.py`, `Plugin/owismind/tests/test_workflow_gate.py` (NOUVEAUX)

**Interfaces (produites, gelees pour T4/T5/T8):**
```python
# durable_runner.py (ZERO import langchain)
DURABLE_DEADLINES_BY_MODE = {"smart": {"run": 900, "step": 180, "idle": 60},
                             "pro": {"run": 1200, "step": 300, "idle": 90},
                             "claude": {"run": 1800, "step": 600, "idle": 180}}
LEASE_SECONDS = 45; HEARTBEAT_SECONDS = 10; RECOVERY_SCAN_SECONDS = 10
MAX_ACTIVE_WORKFLOWS = 8; MAX_ACTIVE_WORKFLOWS_PER_USER = 1; MAX_MESH_CALLS = 3
STEP_RETRY_BACKOFF_S = (2.0, 8.0)  # + jitter ; 3 tentatives/step ; MAX_TOTAL_STEP_ATTEMPTS = 18
def start_supervisor()                       # idempotent, UN thread daemon, claim <=1 run/scan
def start_workflow(user_ctx, body, agent_profile)  # -> {"run_id","exchange_id"} | erreur "busy"
def run_claimed_workflow(run_id, lease_owner)      # machine d'etat (spec 4.1), worker daemon
def execute_command(run, command, step=None)       # 1 appel run_agent_streamed borne, consomme workflow_control
def classify_failure(err)                    # -> "transient" | "quota" | "fatal"
def build_partial_answer(run, ledger)        # -> str FR/EN neutre listant les steps termines

# context.py (fonctions PURES, testables sans DSS)
def resolve_analysis_mode(value)             # -> "auto"|"deep"|"direct" (defaut auto, inconnus->auto)
def should_plan(question, domain_keywords, analysis_mode)  # -> bool ; deterministe HAUTE PRECISION :
    # deep->True, direct->False, auto-> (>=2 domaines matches) OU regex comparaison/correlation
    # multi-source explicite. JAMAIS d'appel LLM ici.
def build_workflow_token(command, run_id, step_id=None, attempt_id=None)  # -> "⟦owi:workflow=v1;...⟧"
def build_progress_block(ledger, mode)       # -> str [WORKFLOW PROGRESS], budgets spec section 6,
    # degradation dans l'ordre du spec, refs #Sx toujours conservees
```
Events publics nouveaux (geles, aussi pour T4/T8) : `PLAN_READY, STEP_STARTED, STEP_RETRYING,
STEP_COMPLETED, VERIFYING, REPLANNING, WAITING_UPSTREAM, PARTIAL_RESULT`.
Routes nouvelles : `GET /chat/active?session_id=`, `GET /chat/activity?exchange_id=` (owner-scoped).
`/chat/poll` : si le run est durable -> run_state.read_events ; sinon chemin RAM legacy identique.

- [ ] **S1 tests d'abord** : gate (should_plan : questions simples->False, 2 domaines->True,
  deep/direct forcent, JAMAIS de LLM) ; token (format, parse aller-retour) ; PROGRESS (budgets
  par mode, degradation, refs conservees) ; runner avec run_agent_streamed MOCKE : machine
  d'etat complete sur un plan 2 steps, retry transient avec backoff, quota->quota_blocked sans
  retry, stop entre steps, fencing (resultat tardif ecarte), deadline run->partial, 1 run/user,
  semaphore Mesh=3, superviseur claim 1 run max/scan, partial_answer.
- [ ] **S2 implementer** durable_runner + context + routes + routage stream_manager (le chemin
  legacy ne DOIT PAS changer : test anti-regression = memes events qu'avant sur un run mocke
  sans flag).
- [ ] **S3 gates** : suite backend complete + tests cibles verts.
- [ ] **S4 commit** : `feat(runs): durable workflow runner (supervisor, lease, state machine,
  deterministic complexity gate)`

---

### Task T4 : Protocole workflow dans l'orchestrateur + prompts hub [Claude only]

Spec : sections 5.2, 5.3, 8. Depend de T3 (contrats token/events). Fichiers DISJOINTS de T3.

**Files:**
- Modify: `OWIsMind_PRD_V1_2/genai/agents/OWIsMind_orchestrator.py`
- Create: `OWIsMind_PRD_V1_2/project-library/owismind_hub/prompts/orchestrator_workflow.md`
  (sections PLANNER / REPLANNER / REVIEWER / SYNTHESIZER ; fallbacks embarques dans l'agent,
  pattern `_load_hub_capabilities` :1374-1469)
- Create: `OWIsMind_PRD_V1_2/project-library/owismind_hub/run_settings.json` (deadlines, caps,
  flags ; valeurs = spec 4.3/5.2 ; loader avec validation stricte + repli embarque)
- Test: `OWIsMind_PRD_V1_2/tests/test_orchestrator_workflow.py` (NOUVEAU)

**Interfaces (produites, gelees pour T5/T7):**
```python
def parse_workflow_control(text)  # -> None | {"command","run_id","step_id","attempt_id"} ;
    # last-token-wins, strip du token, ANTI-FORGE : un token au milieu du texte user est ignore
    # (memes regles que parse_mode :1064-1081)
# process_stream : if control -> _process_workflow(control, query, settings, trace) sinon legacy.
# Commandes -> mini-graphes par invocation (spec 8), ZERO checkpointer, ZERO ecriture SQL.
# Remontee machine : chunk {"type":"event","eventKind":"OWI_WORKFLOW_CONTROL",
#   "eventData":{"command":..., "payload":{...}}}  cap 16000 chars, atomique, en FIN de commande.
# plan/replan/review = with_json_output STRICT (schemas spec 5.2 : enum kind fermee, caps,
#   DAG acyclique, ids reimposes S1.. par le code, zero table/agent_id).
# execute (specialist_query / attribute_lookup / render) : REUTILISE _run_subagents,
#   build_tool_specs FILTRE par step.capability_keys (masquage), _record_artifact, events geles.
# clarify -> payload {"status":"clarify","question":...} ; le runner termine proprement.
```

- [ ] **S1 tests d'abord** (pattern test_orchestrator existants, LLM/Mesh mockes) : anti-forge
  token ; sans token -> chemin legacy BYTE-IDENTIQUE (test golden sur la sequence d'events d'un
  run mocke) ; plan invalide (kind inconnu, 13 steps, cycle, table dans task) -> REJETE et
  payload d'erreur structurel ; commande execute filtre les tools par capability ; event
  OWI_WORKFLOW_CONTROL emis une fois, <=16000 c ; fallbacks hub (fichier absent/corrompu ->
  defauts embarques, pattern existant).
- [ ] **S2 implementer** + seeds hub (`regenerate_seeds.py` doit rester byte-equivalent :
  l'etendre si necessaire).
- [ ] **S3 gates** : `python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests` complet.
- [ ] **S4 commit** : `feat(orchestrator): workflow command protocol (plan/execute/replan/
  review/synthesize) behind machine token, legacy path untouched`

---

### Task T5 : Streaming durable (normalisation controle + fusion resultats) [Claude only]

Spec : sections 8, 10 (finalize). Depend de T2+T3+T4.

**Files:**
- Modify: `Plugin/owismind/python-lib/owismind/agents/streaming.py`
- Modify: `Plugin/owismind/python-lib/owismind/agents/durable_runner.py` (consommation)
- Test: `Plugin/owismind/tests/test_streaming_workflow_control.py` (NOUVEAU)

**Interfaces:**
```python
# streaming.py : eventKind OWI_WORKFLOW_CONTROL -> {"type":"workflow_control","command":...,
#   "payload": dict}  ; JAMAIS pousse dans les events publics (test dedie) ; payload JSON
#   invalide -> {"type":"workflow_control","error":"invalid_payload"} (le runner classifie fatal).
# durable_runner : fusion par step -> run_steps (generated_sql_json via les caps de capture
#   existants, artifacts_json <=8, usage_json somme) ; finalize_exchange : chat_v5 phase 2 UNE
#   fois (UPSERT artifacts + UPDATE chat_v5 + usage garde par finalize_exchange_guard).
```

- [ ] **S1 tests d'abord** : normalisation (payload ok / invalide / cap depasse) ; AUCUN
  workflow_control dans la sortie publique de poll ; fusion SQL/artifacts/usage multi-steps ;
  finalize rejoue apres crash simule a CHAQUE sous-phase -> zero double comptage usage, zero
  doublon artifact ; trace brute non persistee dans run_events.
- [ ] **S2 implementer.** **S3 gates** : suite backend complete.
- [ ] **S4 commit** : `feat(runs): durable streaming control channel + idempotent exchange
  finalization`

---

### Task T6 : Catalogue factory (catalog.py + pipeline + registry + seeds) [Codex OK, re-verif Claude]

Spec : section 7.1. Fichiers DISJOINTS de T2-T5. Patterns : `owismind_factory/fctx.py` (ctx.act,
dry-run, ZERO delete), `flow_builder.py` (ensure_* idempotents), `semantic_builder.py`.

**Files:**
- Create: `OWIsMind_PRD_V1_2/project-library/python/owismind_factory/catalog.py`
- Modify: `OWIsMind_PRD_V1_2/project-library/python/owismind_factory/pipeline.py` (step `catalog`
  apres `capability`, avant `smoke`)
- Modify: `OWIsMind_PRD_V1_2/project-library/python/owismind_factory/registry.py` (champs
  OPTIONNELS `catalog_generation`, `catalog_dataset`, `connection_key` ; retro-compat v1.2 testee)
- Test: `OWIsMind_PRD_V1_2/tests/test_factory_catalog.py` (NOUVEAU)

**Interfaces (spec 7.1, gelees pour T7):**
```python
CATALOG_DATASET_NAME = "OWIsMind_agent_catalog_v1"
def ensure_catalog_dataset(ctx, connection, zone=None)          # ensure_* idempotent, dry-run-able
def build_catalog_generation(spec, wizard_config, dataset_schema, physical_table)
    # -> {"generation_id": "<domain>-YYYYMMDD-NNN", "rows": [...]} ; AUCUNE lecture de lignes metier,
    # AUCUN sample de valeur ; descriptions/synonymes issus du wizard_config et du DomainSpec.
def publish_catalog_generation(ctx, capability_key, generation)  # append-only, JAMAIS de DELETE
def searchable_catalog_rows(generation)                          # -> rows avec search_text normalise
```

- [ ] **S1 tests d'abord** : dry-run n'ecrit rien ; publication append-only (2 publications = 2
  generations, zero delete) ; physical_table/connection presents en base mais ABSENTS de toute
  sortie destinee au prompt ; retro-compat registry (capability sans champs catalog = valide) ;
  generation_id deterministe ; aucune valeur metier dans les rows.
- [ ] **S2 implementer.** **S3 gates** : suite OWIsMind_PRD_V1_2/tests complete.
- [ ] **S4 review Claude du diff Codex** (regle model-routing #2) puis commit :
  `feat(factory): agent catalog dataset (append-only generations, server-only physical refs)`

---

### Task T7 : Step correlate (JOIN SQL read-only, garde etendue) [Claude only, zone SQL]

Spec : section 7.2. Depend de T4 (chemin workflow) et T6 (forme du catalogue).

**Files:**
- Modify: `OWIsMind_PRD_V1_2/genai/agents/OWIsMind_orchestrator.py` (execute_correlation_step)
- Test: `OWIsMind_PRD_V1_2/tests/test_orchestrator_correlate.py` (NOUVEAU)

**Contrats:**
```python
# La garde existante est REUTILISEE et etendue parametriquement : guard_custom_sql valide deja
# FROM/JOIN contre un ensemble d'orthographes + CTE auto-decouvertes (SalesDrive:1388-1444) ;
# la version orchestrateur accepte allowed_tables: set[str] (N tables de la generation active).
# Pipeline (spec 7.2, ordre STRICT) : catalogue (lu par le CODE agent via SQL SELECT sur le
# dataset catalog, comme value_index ; le modele ne voit QUE d1..d5 + schemas) -> SQL du modele
# contre alias -> substitution CTE server-side -> garde -> EXPLAIN -> preview LIMIT 10 ->
# sanity checks (liste spec 7.2) -> execution finale (LIMIT 500, transaction_read_only,
# statement_timeout 30 s) -> max 2 corrections LLM avec erreur DB nettoyee.
# Contraintes : meme connexion SQL_owi, pas de cross-connection, pas de table temporaire,
# preview modele <= 15 lignes.
```

- [ ] **S1 tests ADVERSARIAUX d'abord** : refus DDL/DML/`;`/pg_catalog/information_schema/table
  physique inventee/alias hors plan/source hors capability ; substitution CTE correcte sur
  fixtures ; jointure correcte sur fixtures 2 sources ; resultat vide -> check echoue
  proprement ; timeout simule ; ZERO ecriture (mock qui leve sur tout non-SELECT) ; 2
  corrections max puis echec propre.
- [ ] **S2 implementer.** **S3 gates** : suite agents complete.
- [ ] **S4 commit** : `feat(orchestrator): read-only SQL correlation step (logical aliases,
  server-side CTE, guarded)`

---

### Task T8 : UI plan + reconnexion + activite [Codex sur le mecanique, review Claude + charte]

Spec : section 9. Depend de T3 (routes) + T5 (shapes d'events).

**Files:**
- Create: `Plugin/owismind/frontend/src/components/chat/RunPlan.vue`
- Modify: `Plugin/owismind/frontend/src/composables/timelineModel.js` (8 nouveaux events geles),
  `useChatStream.js` (`resumeChatStream({runId, target, cursor})`), `services/backend.js`
  (`fetchActiveRun(sessionId)`, `fetchRunActivity(exchangeId)`), `stores/chat.js` (rattachement
  du run actif au chargement), `MessageAgent.vue` (insertion RunPlan + "Afficher l'activite"),
  `i18n/extra.js` (libelles + erreurs spec 9)
- Test: `Plugin/owismind/frontend/test/runplan.test.js`, extension des tests reducer existants

**Contrats:**
- Events consommes : `plan` (payload {goal, steps[{id,title,status}]}) emis par le runner a
  PLAN_READY, `step_status` ({id, status, duration_s?}) sur chaque transition ; statuts front :
  pending/running/completed/retrying/failed/superseded.
- RunPlan.vue : charte Orange STRICTE : border-radius 0, filets 1px tokens semantiques, orange
  UNIQUEMENT le step actif (`--orange-text`), pas de gradient/ombre/emoji/animation decorative,
  reduced-motion respecte. Progression "N / M".
- Reconnexion : au chargement d'une conversation, fetchActiveRun -> si run actif, reprise du
  poll depuis cursor 0 dans la meme bulle (spec 9).
- [ ] **S1 tests reducer d'abord** (node --test) : sequence plan -> step_status -> replan
  (steps superseded) -> partial ; reconnexion rejoue sans doublons ; erreurs mappees i18n.
- [ ] **S2 implementer.** **S3 gates** : `npm test` + compile-check Vite vers /private/tmp +
  subagent charte-orange-reviewer sur le diff (OBLIGATOIRE, regle #10).
- [ ] **S4 commit** : `feat(ui): run plan card, persistent activity, resume after refresh
  (Orange charter)`

---

### Task T9 : Gates finales + audit securite adversarial

- [ ] Suites COMPLETES relues : backend (>=830+nouveaux), agents+factory (>=516+nouveaux),
  front, compile-check Vite. AUCUN skip nouveau non justifie.
- [ ] Audit securite adversarial (workflow multi-agents) sur le diff complet de la session :
  invariants spec section 11 UN PAR UN (SELECT-only, whitelists 3 niveaux, caps, fencing,
  aucune fuite physical_table/agent_id vers prompt/events/routes, degradation quota/rate-limit,
  logs sans PII). Chaque finding verifie puis corrige, re-run des suites.
- [ ] Mise a jour `OWIsMind_PRD_V1_2/docs/DEPLOY_V1_3_DEV.md` : ajouter la phase de validation
  DSS du Durable Step Shell (16 scenarios + gates du spec section 14) SANS toucher aux phases
  existantes.
- [ ] Commit final + /log-session (memoire, graphe, session log). JAMAIS de push.

## Self-review du plan (fait le 2026-07-17)

- Couverture spec : sections 1-11 toutes mappees (T1=4.3 legacy ; T2=4.2/10 ; T3=4/5.1 ;
  T4=5.2/5.3/8 ; T5=8/10 ; T6=7.1 ; T7=7.2 ; T8=9 ; T9=11/14). Section 12 (differes) = hors
  perimetre par definition. Campagne DSS (14) = post-session avec l'user, documentee en T9.
- Zero placeholder TBD/TODO ; chaque tache a ses cas de test nommes et ses commandes.
- Coherence de types : signatures run_state consommees par T3/T5 identiques ; events geles
  identiques T3/T4/T8 ; token identique T3/T4 ; deadlines identiques spec/T1/T3.
- Fichiers disjoints entre taches paralleles (T4/T6 ; T2 vs T4) : aucun conflit d'agent.
