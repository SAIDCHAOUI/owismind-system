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
14. **Contexte ecran -> agent (L134-L137)** : canal `screen_context` -> bloc `[ON SCREEN NOW]`, `sanitize_source_state` never-raises, phrase de permission verbatim TOUJOURS preservee, jamais de lignes brutes.

Tests backend : `python3 -m unittest discover` (voir `PROJECT_STATE.md` pour les cibles par module).
