# PROJECT_STATE - OWIsMind (memoire longue, V2)

> Etat durable de la branche `OWIsMind_PRD_V2_0`. Repart a zero le 2026-10-16 (nettoyage minimal) :
> l'historique v1.x (parcours, matrice de validation v1.2/v1.3, LAB) reste dans git et sur la branche
> `OWIsMind_PRD_V1_3-dev`. En cas de conflit avec `docs/cadrage/` : ce fichier + `LESSONS.md` font foi.

## 1. Produit
Assistant de donnees interne d'Orange Wholesale International : une webapp Vue (plugin DSS) ou l'on
pose une question metier ; un orchestrateur LangGraph delegue a des sous-agents experts, qui ecrivent
le SQL via des modeles semantiques. Tout chiffre affiche est adosse a un SQL (Evidence).

## 2. Architecture
- Plugin DSS : front Vue 3 + Vite (builde dans `resource/owismind-app/`) + backend Flask modulaire
  (`python-lib/owismind/` : `api`, `agents`, `evidence`, `storage`, `security`, `workspace`, `benchmark_view`).
- Agents : Code Agents LangGraph (env 3.11), source = repo, recolles a la main dans DSS.
- Backend : Python 3.9.23 observe (pas de langchain). LLM Mesh pour parler aux agents, polling 500 ms.
- V2 : orchestrateur pilote un espace de travail (Studio) via `write_plan` / `update_plan` /
  `write_note` / `publish_widget` ; events `WORKSPACE` ; etat persiste dans `webapp_workspaces_v1`.
  Spec : `OWIsMind_PRD_V2_0/docs/V2_ARCHITECTURE.md`.

## 3. Identifiants canoniques
| Element | Valeur |
|---|---|
| Plugin | id `owismind`, version `2.0.0`, racine `OWIsMind_PRD_V2_0/plugin/owismind/` |
| WebApp / package / resource | `webapp-owismind-ai-agents` / `owismind` / `owismind-app` |
| Vite | `base` `/plugins/owismind/resource/owismind-app/`, `outDir ../resource/owismind-app` |
| Zip d'upload | `OWIsMind_PRD_V2_0/plugin/ready-for-dataiku/owismind_v2_0-upload.zip` (git-ignore, regenere par `build_dev_plugin.py` / skills) |
| API | `/owismind-api/*`, sante `/owismind-api/ping` |
| SQL | connexion `SQL_owi` (PostgreSQL, `public`), tables prefixees par la project key runtime |
| Tables plugin | `webapp_chat_v5`, `webapp_artifacts_v1`, `webapp_workspaces_v1`, `webapp_events_v1`, `webapp_feedback_v1`, `webapp_settings_v1`, `webapp_users_v1`, `webapp_user_quota_v1`, `webapp_usage_monthly_v1`, `webapp_agent_requests_v1`, `webapp_golden_suggestions_v1` (zero ALTER : create-if-not-exist) |
| Orchestrateur | `OWIsMind_orchestrator` `038G7mlF` |
| Sous-agents | revenus `agent:bHrWLyOL`, tickets `agent:NcE9LD2i` (+ `DeliverySnapshot_expert`, `Invoices_expert` dans `GenAI/Agents/`) |
| Tools | `attribute_lookup` `UUoynaL`, `revenue_semantic_query` `v4oqA6R`, `tickets_semantic_query` `nEirlso` |
| Modeles semantiques | revenus `AHUh9hb`, tickets `dM4jA4G` |
| Modeles LLM | UNE source : `/python/owismind_hub/models.json` (project library), zero id en dur, relu toutes les 30 s |
| Carte complete repo <-> DSS | `OWIsMind_PRD_V2_0/README.md` + `registry.json` |

Project key DSS de la V2 : a confirmer (DEV utilise jusqu'ici : `OWISMIND_PRD_V1_3_DEV` ; V2 a tester
dans une duplication).

## 4. Outillage
- Build front : skill `/build-plugin`. Zip : `python3 OWIsMind_PRD_V2_0/plugin/tools/build_dev_plugin.py`
  (skills `/package-plugin`, `/package-plugin-dev`). Jamais d'install par l'agent.
- Simulateur local : `OWIsMind_PRD_V2_0/dev-harness/` (port 5199, voir son README).
- Tests : backend `python3 -m unittest discover -s OWIsMind_PRD_V2_0/plugin/owismind/tests` ;
  agents `python3 -m unittest discover -s OWIsMind_PRD_V2_0/tests` ;
  front `cd OWIsMind_PRD_V2_0/plugin/owismind/frontend && node --test test/*.test.js`.

## 5. Matrice de validation V2
| Sous-systeme | Etat |
|---|---|
| Phase 1 (protocole workspace + backend + front sur simulateur) | Valide par l'user sur le simulateur (2026-10-15) |
| Phase 2 (Studio, plan, multi-SQL, outils orchestrateur) | Code + tests verts, NON vu en navigateur, NON deploye DSS |
| Benchmark (affichage plugin) | Conserve ; producteur = projet DSS `OWIsMind_LAB` (code sur la branche v1.3) |
| Agent Factory (console + `owismind_factory` + notebooks) | Present, statut V2 a trancher |
