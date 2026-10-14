---
paths: ["OWIsMind_PRD_V1_3_DEV/plugin/owismind/python-lib/**", "OWIsMind_PRD_V1_3_DEV/plugin/owismind/webapps/**", "OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/**"]
description: Gotchas backend Flask DSS (SQL direct, streaming, evidence, artefacts). Chargees quand on touche au backend du plugin.
---

# Gotchas backend (Flask DSS, valides DSS sauf mention)

Backend observe = Python 3.9.23 (jamais d'import langchain ici). SQL direct, sans Flow au runtime. Refs lecons dans `memory/LESSONS.md`.

1. **Whitelist agents (L017/L018)** : le front envoie `{key,label}` (cle logique opaque) ; resolution serveur seulement, jamais d'`agent_id` brut depuis le front.
2. **Streaming = POLLING-via-thread (L019)** : `/chat/start` -> `/chat/poll` (500 ms) ; SSE abandonne (bufferise par le proxy DSS) ; stop cooperatif (L034) ; `MAX_CONCURRENT_RUNS=8`, TTL eviction, scope `user_id`.
3. **Contexte agent (L032)** : prefixe user construit a CHAQUE `/chat/start`, colle au message COURANT seulement ; historique rejoue brut ; message stocke BRUT.
4. **Feedback (L031)** : UPDATE owner-scope.
5. **Trace** = dataset Flow append (L027/L028), best-effort cote worker.
6. **Nommage tables (L008/L014)** : `_vN`, jamais d'ALTER (sauf `ADD COLUMN IF NOT EXISTS` idempotent, L126) ; `rows_to_json_safe` (L013) ; noms physiques > 63 octets raccourcis (`sql_config._shorten_identifier`, L110).
7. **Surete** : SQL parametre (`dataiku.sql.Constant/toSQL`) + COMMIT + bornes ; prefixe `PROJECT_KEY` sur les tables ; citation `public."OWISMIND_DEV_..."` ; pas de Flow, pas de route SQL generique exposee ; le front ne choisit jamais table/connexion/requete.
8. **Ne pas editer** `resource/owismind-app/` ni `ready-for-dataiku/` (generes par build/package).
9. **Evidence (L035-L037 DSS / L042 / L045)** : decouverte auto des datasets PostgreSQL ; parseur BEST-EFFORT (L042) ; `statement_timeout 30s` + `transaction_read_only` (L045). MULTISELECT ne se rend pas dans les Settings DSS (L037).
10. **Trust layer (L045)** : `sql_explain` PUR never-raises ; niveaux deterministes ; drill re-derive du SQL stocke ; capture = enrichissement JSON `generated_sql`, caps au point d'ecriture ; fusion footer/relay ONE-SHOT.
11. **SalesDrive v2 + orchestrateur (L047/L048 DSS)** : repo = source de verite ; tools resolver `aNxeOc4`, semantic `v4oqA6R` (`get_agent_tool(id).run()`, noms - pas ids - dans les events) ; span `semantic-model-query` recree au contrat gele ; `AGENT_RESULT` = statut machine jamais affiche ; UNE seule capability revenue `enabled`.
12. **Artefacts (L057 DSS)** : event gele `ARTIFACT` normalise dans `agents/streaming.py` ; specs persistes dans `webapp_artifacts_v1` (UPSERT owner-stamped, lecture read-only + statement_timeout) ; `/evidence/meta` renvoie `artifacts` + un `data` Chart.js par chart (payload Python `evidence/chart_payload.py`) ; l'agent ne fournit que x/y/type/style ; best-effort.
13. **Analytics (L125)** : `webapp_events_v1` = 1 table brute, whitelist events source de verite, `record_events` best-effort (jamais de 500) ; impersonation = drop avant write ; recherches = `{len}` seul, pas de query string en clair.
14. **Contexte ecran -> agent (L134-L137)** : canal `screen_context` -> bloc `[ON SCREEN NOW]`, `sanitize_source_state` never-raises, phrase de permission verbatim TOUJOURS preservee, jamais de lignes brutes. Depuis 2026-08-06 le front l'attache PAR DEFAUT (opt-out) ; le backend est inchange.
15. **Moteur natif (L177-L179, 2026-08-06)** : `agents/native_orchestrator.py` = orchestrateur in-backend derriere le flag admin `profile.native_engine` (OFF = legacy byte-identique). MEME contrat d'events que `run_agent_streamed` ; capture brute = `{columns, rows, truncated}` (JAMAIS de cle 'captured' - predicat `is_captured_result`) ; selection du moteur DANS le try du worker (import paresseux conserve) ; mode = route seule (`resolve_mode`, aucun scan de token) ; `prior_recall_enabled` coupe pour le natif ; capabilities lues du hub project-library (TTL 300 s + fallback). Doc : `OWIsMind_PRD_V1_3_DEV/docs/NATIVE_ENGINE.md`.
16. **Resultat complet pagine (L190, 2026-10-14)** : la capture agent (`generated_sql[].result`) est un EXTRAIT de 50 lignes et son `row_count` est compte APRES la coupe : jamais un total. Le total + la suite viennent de `/evidence/result-rows` (re-run du SELECT stocke en sous-requete LIMIT/OFFSET, COUNT seulement offset 0 ET has_more) ; toute relance passe par DEUX gardes : `sql_parse.check_rerunnable_select` (filtre par jetons, liste blanche de fonctions) PUIS `evidence/plan_guard` sur `EXPLAIN (FORMAT JSON, VERBOSE)` (autoritaire : relations = datasets exacts, fonctions deparsees en liste blanche, fail closed) ; lignes POSITIONNELLES (`frame_to_json_safe_matrix`, pas `rows_to_json_safe` qui ecrase les colonnes dupliquees).
17. **Regle SQL user (L191, 2026-10-14)** : sur la connexion SQL, uniquement CREATE TABLE/INDEX IF NOT EXISTS + SELECT + les ecritures de LIGNES du plugin dans SES tables (INSERT, UPDATE cible par ligne). JAMAIS d'ALTER (colonne nouvelle = dans le CREATE, ou nouvelle table `_vN`), jamais de DROP/TRUNCATE, un seul DELETE autorise (quota admin `build_user_quota_clear`). Supprimer un dataset = API Dataiku officielle, jamais SQL. Tout nouveau thread/timer de demarrage qui touche la base doit etre conditionne a une fonction ACTIVE. Workflow durable RETIRE (git avant le commit de retrait).

Tests backend : `python3 -m unittest discover` (voir `PROJECT_STATE.md` pour les cibles par module).
