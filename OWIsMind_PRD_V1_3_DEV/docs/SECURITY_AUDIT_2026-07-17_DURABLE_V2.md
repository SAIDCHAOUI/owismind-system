# Audit securite + correction - Durable Step Shell v1.3 (revue triple, run 3)

Date : 2026-07-17 (run 3, branche `OWIsMind_PRD_V1_3-dev`).
Base auditee : working tree a `b909156` (apres les 3 fix de l'audit precedent
`SECURITY_AUDIT_2026-07-17_DURABLE.md` : comma-join, commentaire SQL, reaper TOCTOU).

## Methode : trois revues INDEPENDANTES

1. **Fable 5 (lead)** : lecture directe des surfaces sensibles (garde JOIN correlate,
   lease CAS, catalogue), arbitrage des desaccords.
2. **Workflow multi-agents Opus** (6 dimensions : SQL, machine a etats, ressources/
   instance, API/token/authz, objectifs, frontend), chaque finding VERIFIE
   adversarialement par un second agent (8 confirmes / 11 refutes sur 19 signales).
3. **GPT-5.6 Sol** (codex, effort high, read-only) : revue de correction/robustesse/
   surete-ressources (0 Critical, 6 High signales).

Les trois revues ont CONVERGE sur les memes racines, en se completant : le workflow
Opus a trouve le CRITICAL fonctionnel que Sol n'avait pas ; Sol a trouve H2 (catalogue)
et les fragilites etat-machine ; les deux ont confirme le trou SQL `TABLE`/regex.

## Verdict

L'audit precedent (interne) concluait 0 Critical / 2 Important corriges. La revue
triple, plus profonde, a montre que **la feature durable n'etait PAS fonctionnelle en
DSS reel** (2 cassures dures masquees par des test-doubles infideles) et que la garde
SQL du correlate avait **plusieurs contournements restants** de la meme classe que les
deux deja fermes. Tout cela est desormais **CORRIGE et teste**. Restent des durcissements
etat-machine (sous crash/concurrence) DOCUMENTES avec patch propose, a appliquer +
valider lors du smoke DSS DEV.

Aucun code n'a ete execute contre l'instance DSS. Suites locales vertes apres correction :
backend 965, agents+factory 619, LAB 343, front 365.

---

## CORRIGE (avec test de non-regression)

### C1 [CRITICAL, fonctionnel] `save_plan` ne persistait pas `capability_keys`/`args`
`storage/run_state.py` (save_plan). Le plan normalise porte `capability_keys`/`args` en
champs FRERES de `task` ; `save_plan` ne stockait que la STRING `task` dans `task_json`.
Or `durable_runner._step_spec` reconstruit le token `⟦owi:wfstep⟧` en attendant un DICT
JSON dans `task_json`. Resultat : `json.loads("get revenue")` -> ValueError -> spec sans
capabilities -> CHAQUE step d'execution (specialist_query / correlate / attribute_lookup)
echouait en DSS reel (`capability_unavailable` / `correlate_needs_2_sources` /
`missing_term`), se replanifiait, terminait en `partial`. Les objectifs "planifier +
suivre + correler" etaient inoperants. Masque parce que le test-double de
`test_durable_runner.py` serialisait, lui, le dict complet (contrat que le vrai code ne
respectait pas).
**Fix** : `save_plan` serialise le dict complet `{task, capability_keys, args, produces,
checks, depends_on}` (borne par `MAX_TASK_JSON_CHARS`), ce que `_step_spec` sait deja
relire. **Test** : `test_run_state.test_task_json_carries_execution_payload_not_just_the_task_string`.

### C2 [HIGH, fonctionnel] Lecture catalogue correlate incompatible avec le schema publie
`GenAI/Agents/OWIsMind_orchestrator.py` (`_correlate_catalog_schemas`). La requete lisait
`data_type` et filtrait `item_level = 'column'`. Le catalogue (`owismind_factory/catalog.py`
`CATALOG_SCHEMA`) publie `column_type` et n'a PAS de colonne `item_level` -> toute etape
correlate echouait a la lecture catalogue ("undefined column") avant meme de construire le
JOIN. Masque par un `_FakeExecutor` qui renvoyait le schema attendu par l'orchestrateur, pas
le vrai.
**Fix** : requete alignee sur `column_type`, clause `item_level` retiree ; le `_FakeExecutor`
du test rendu FIDELE (asserte `column_type`, refuse `item_level`/`data_type`), donc la
regression est desormais capturee par `test_happy_path_payload_and_evidence`.

### C3 [HIGH, securite] Contournements restants de la garde d'alias du correlate
`GenAI/Agents/OWIsMind_orchestrator.py` (`_corr_guard_model_sql` + regexes). Trois trous de
la meme classe defense-en-profondeur que les deux deja fermes (le SQL modele lit une table
hors allowlist d'alias `d1..dN`, en lecture seule) :
- `TABLE <relation>` (forme bare-relation PostgreSQL = `SELECT * FROM <rel>`, sans FROM/JOIN
  -> jamais scannee). Ex `SELECT * FROM (TABLE secret) q`, `... UNION ALL TABLE secret`.
- Identifiant quote COLLE au mot-cle sans espace : `FROM"secret"` (le scan exigeait `\s+`).
- Fonctions meta-SQL qui EXECUTENT une requete passee en chaine (donc sans FROM a valider,
  chaine blanchie) : `query_to_xml('SELECT ... FROM autre_table', ...)` et famille
  (`table_to_xml`, `schema_to_xml`, `database_to_xml`, `cursor_to_xml`, `dblink*`), plus les
  lecteurs de fichiers (`pg_read_file`, `lo_import/export`). `transaction_read_only` bloque
  les ecritures mais PAS ces lectures cross-table.
**Fix** : `table` ajoute a la denylist de mots-cles ; `_CORR_FORBIDDEN_FUNC_RE` (nouvelle)
rejette les fonctions meta-SQL ; `_CORR_TABLE_LIST_RE` resserre (`\b(?:from|join)\b\s*`)
attrape l'identifiant quote colle. **Tests** : 3 nouveaux dans `test_orchestrator_correlate`
+ batterie de 18 cas verifiee a la main (0 faux-positif sur le SQL legitime : agregats,
comma-join d'alias, mots-cles/`table` dans un LITTERAL chaine ; le dollar-quoting echoue en
securite = rejet). Seul faux-positif connu, ACCEPTE : une colonne nommee EXACTEMENT un mot-cle
reserve ET citee (`d1."table"`) est rejetee (forbidden_keyword) ; elle echoue FERME (correlate
degrade, ni crash ni fuite), la feature est nouvelle/flag-OFF, et fermer `TABLE <relation>` prime.

### C4 [MEDIUM, robustesse] `poll_durable` bouclait sans fin sur un run inconnu/purge
`agents/durable_runner.py`. `read_events` signalait `not_found` (done=True) mais
`poll_durable` l'ecrasait (recalculait done=False) -> le client interrogeait SQL a l'infini
sur un run purge/inconnu/etranger.
**Fix** : `poll_durable` honore `not_found` et renvoie un etat terminal (done=True). Pas
d'oracle d'existence (inconnu et etranger renvoient la meme forme ; owner-scope dans `load_run`).

### C5 [MEDIUM, securite] Un flag booleen mal type pouvait ACTIVER le durable
`security/validation.py`. `bool("false")` / `bool("0")` valent True en Python -> un profil
admin mal type (`durable_workflow: "false"`) activait le protocole durable.
**Fix** : helper `_coerce_flag` (les chaines falsy `false/0/no/off/""` -> False ; `1`->True,
`0`->False, compat test existant). Applique a `durable_workflow` et `modes`.

### C6 [HIGH (Sol), correction] Fallback legacy pouvait DOUBLER un run durable
`agents/durable_runner.py` (`start_workflow`) + `api/routes.py`. Si `create_run`/`claim_run`
reussissait mais `_spawn_worker` echouait (thread.start sous pression), l'exception remontait
-> la route basculait en run LEGACY sur le meme exchange, alors que le run durable existait
deja et serait repris par le superviseur = double execution, double cout, course sur la reponse.
**Fix** : une fois le run cree, `start_workflow` n'emet plus d'exception (try/except autour de
claim+spawn) et renvoie toujours le `run_id` -> la route ne bascule jamais en legacy si un run
durable existe ; le superviseur reprend le run (immediat si non claim, a l'expiration du lease
sinon). Le fallback legacy reste possible si `create_run` echoue AVANT toute creation.
**Test** : `test_spawn_failure_does_not_raise_so_no_legacy_double_run`.

### C7 [LOW, surete instance] Croissance illimitee des 3 tables durables
`agents/durable_runner.py` (`_supervisor_loop`). `purge_finished_runs` (bornee, deja ecrite
et testee : <= 1000 runs finis depuis > 14j, une transaction) n'etait JAMAIS appelee.
**Fix** : le superviseur l'appelle tous les `PURGE_EVERY_N_SCANS` (360 scans ~= 1h a 10s/scan),
best-effort, hors chemin chaud, charge DB negligeable.

---

## DOCUMENTE (verifie reel ou plausible ; a corriger + valider au smoke DSS DEV)

Non corriges a l'aveugle : ce sont des durcissements etat-machine dont la JUSTESSE depend de
faits DSS invérifiables hors instance (modele de process du backend webapp : mono ou multi ;
semantique de timeout du SDK LLM Mesh en streaming). Le chemin nominal mono-process fonctionne.

- **H3 [Sol, High] Fencing incomplet des ecritures terminales.** Seuls `complete_step`/
  `fail_step` sont fences par `attempt_id`. `set_run_status`, `save_plan`, la finalisation et
  `save_assistant_message` n'ont pas de garde `lease_owner`. En mono-process, l'invariant
  `_WORKERS` (le superviseur saute un run deja dans `_WORKERS`) l'empeche ; mais en MULTI-process
  ou apres CRASH-recovery, un worker zombie pourrait ecrire un etat terminal perime.
  *Patch propose* : ajouter `AND lease_owner = <owner>` (ou un fencing token monotone) au `WHERE`
  de chaque transition terminale + finalisation ; un CAS a 0 ligne fait abandonner le worker.
- **H4 [Sol, High] Stream Mesh muet non borne.** La deadline/idle n'est verifiee qu'a la reception
  d'un evenement. Un `execute_streamed()` qui ne produit AUCUN chunk bloque le thread : le
  heartbeat renouvelle le lease indefiniment, le slot Mesh (`_MESH_SLOTS`) et le thread fuient.
  C'est exactement le risque "run long qui tombe/hang". *Patch propose* : imposer un timeout
  transport/SDK Mesh (a verifier en DSS) ; a defaut un watchdog qui, a `deadline_at`, marque le
  run `deadline_reached` et libere le slot, independamment de l'activite du stream.
- **H5 [Sol, High] Finalisation non idempotente de bout en bout.** Reponse, guard d'usage et
  statut terminal = 3 transactions. Apres un crash entre l'ecriture de la reponse et du statut,
  le superviseur RE-synthetise et peut ECRASER la reponse (le DDL dit pourtant `answer_text` =
  "replayed idempotently after a crash"). *Patch propose* : a la reprise, si `answer_text` est
  deja stocke, le REJOUER au lieu de relancer la synthese LLM ; ecrire reponse + statut terminal
  dans une seule transaction lease-fencee.
- **M2 [Sol] Comptabilite d'usage partielle.** L'usage des commandes plan/replan/review/synthesize
  est recu mais jamais persiste (seul `steps.usage_json`, surtout execute, est somme) -> le budget
  mensuel sous-estime le cout reel. *Patch* : logguer l'usage de chaque commande sous le guard idempotent.
- **M3 [Sol] Render dependant d'un specialist_query sans donnees.** Le resultat specialist ne
  renvoie que colonnes+nb lignes ; `_render_prior_block` exige `model_view` avec les lignes ->
  `missing_render_data`. *Patch* : transporter un `model_view` interne borne (jamais au feed public).
- **[Opus, Medium] Deadlines durables en dur, hub ignore.** `durable_runner` porte des constantes
  (run/step/idle) ; elles ignorent le hub `run_settings.json` -> impossible de calibrer par mode
  en DSS sans re-deployer le zip (calibration que tu voulais faire en reel). *Patch* : sourcer les
  deadlines d'un reglage admin (webapp settings ou hub), constantes actuelles en fallback.
- **[Opus, Low] Goal du plan non persiste.** Le ledger `[WORKFLOW PROGRESS]` et la carte
  `RunPlan.vue` affichent un objectif vide (memoire de travail / plan visible degrades). *Patch* :
  persister le goal a `save_plan` et le rendre dans le ledger + la carte.
- **[Opus, Low] Fenetre reaper au spawn.** Un worker enregistre sous le lock mais demarre hors du
  lock peut etre reape entre l'enregistrement et `thread.start()`. *Patch* : marquer l'entree jusqu'a
  ce que le thread soit vivant, ou enregistrer+demarrer atomiquement.
- **M5/L1 [Sol, Low] Integrite catalogue.** `physical_table` reinjecte tel quel s'il commence par
  `"` ; lecture catalogue par doublement manuel de quotes plutot que `Constant.toSQL`. Risque
  design-time/admin. *Patch* : stocker schema+table separement, toujours quoter cote consommateur.

## REFUTE (verifie et ecarte)

Le workflow Opus a refute 11 signalements (verification adversariale), dont : fonctions non-pg_
dangereuses "en plus" (dblink/lo_* sont soit bloquees par read-only soit desormais denylistees) ;
`load_run` SELECT * "lourd" (la table runs n'a aucun gros blob, PK mono-ligne) ; heartbeat qui
"avale" les exceptions -> double exec (renew_lease et claim partagent le meme chemin SQL, etat
auto-contradictoire) ; poll not_found = probleme d'authz (forme identique inconnu/etranger = pas
d'oracle - c'est C4, corrige cote robustesse pas securite). Les 3 fix de l'audit precedent
(comma-join, commentaire, reaper reservation) ont ete RE-VERIFIES : ils tiennent.

## Deploiement (rappel)

- Correctifs PLUGIN (C1, C4, C5, C6, C7) : dans le zip DEV reconstruit
  `OWIsMind_PRD_V1_3_DEV/plugin/ready-for-dataiku/owismind-v1_3-dev-upload.zip` (id `owismind_dev`, coexiste avec la prod).
- Correctifs AGENT (C2, C3) : dans `GenAI/Agents/OWIsMind_orchestrator.py` -> a RE-COLLER dans le
  Code Agent orchestrateur DSS (env 3.11). Non embarque dans le zip.
- Aucune validation DSS reelle faite (feature flag OFF ; l'utilisateur n'a pas encore teste). Le
  smoke DSS DEV reste indispensable : ces 2 cassures etaient masquees par des test-doubles, seul un
  cycle reel confirme le bout-en-bout.
