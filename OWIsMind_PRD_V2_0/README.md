# OWIsMind_PRD_V2_0 : miroir repo du projet DSS V2.0

Ce dossier est le miroir du projet Dataiku DSS de la V2.0 (duplication du projet v1.3 : tous les
ids d'objets DSS, agents, tools, modèles sémantiques, sont conservés par la duplication).

Règle de travail : **on édite ici, puis on colle dans DSS** (jamais l'inverse ; une édition directe
dans DSS est écrasée au prochain collage). Une branche git par version, nommée comme le projet DSS.

## Comment le système marche

La webapp Vue (le plugin, `plugin/owismind/`) envoie le message et une clé logique d'agent (jamais un
id brut) au backend Flask. Le backend résout la clé via une whitelist côté serveur et invoque
l'orchestrateur par LLM Mesh. L'orchestrateur raisonne, écrit un plan et pilote le Studio (espace de
travail) par ses outils `write_plan` / `update_plan` / `write_note` / `publish_widget`, et délègue aux
sous-agents experts. Chaque sous-agent suit UNDERSTAND -> RESOLVE -> QUERY -> RENDER et délègue le SQL
à son modèle sémantique, exécuté en lecture seule. Tout chiffre affiché vient d'un résultat SQL
identifié par son `sql_id`. Spec V2 : [docs/V2_ARCHITECTURE.md](docs/V2_ARCHITECTURE.md).

## Arborescence (miroir de l'UI Dataiku)

| Dossier / fichier | Rôle | Dans DSS |
|---|---|---|
| `plugin/owismind/` | Le plugin : `python-lib/` (backend Flask), `frontend/` (source Vue, jamais dans le zip), `resource/owismind-app/` (front buildé, généré), `webapps/`, `contracts/`, `tests/`. | Administration > Plugins (upload du zip) |
| `plugin/tools/` | `build_dev_plugin.py` : fabrique le zip d'upload dans `plugin/ready-for-dataiku/` (git-ignoré). Script local, jamais dans DSS. | - |
| `GenAI/Agents/` | Les Code Agents (orchestrateur + sous-agents revenus, tickets, delivery, invoices), fichiers autonomes (stdlib + `dataiku` + `langgraph`). | GenAI > Agents, env Python 3.11 |
| `GenAI/agents-tools/` | `attribute_lookup_tool.py` : lecture rapide de valeurs (un ILIKE read-only, repli Value_Catalog), appelé par l'orchestrateur. Les tools Semantic Model Query sont de la config DSS, sans code. | GenAI > Agent tools |
| `GenAI/semantic-models/` | Un fichier de maintenance par modèle (ACTION = dump / update / repoint) + snapshot `.v1.json` ; `TOOL_DESCRIPTIONS.md` = textes "Description for LLM". | GenAI > Semantic models |
| `flow/` | Recettes par zone : fabriquent profile, value_index et value_catalog lus par les agents. `Webapp_Zone` = datasets écrits au runtime par le backend (aucune recette, ne jamais les rebuild). | Flow |
| `project-library/python/owismind_hub/` | Config & Prompt Hub : `models.json` (SEULE source des modèles LLM), capabilities, persona. Lu par les agents, jamais de secret. | Libraries > `python/owismind_hub/` |
| `project-library/python/owismind_factory/` | Moteur de l'Agent Factory (création d'un domaine/sous-agent) : dry-run par défaut, idempotent, Python 3.9. | Libraries > `python/` |
| `Notebooks/` | Télécommandes de la factory, lancées à la main : 00 sonde, 01 push du hub, 02 alignement d'un clone, 03 création de domaine (DRY_RUN d'abord), 04 wizard sémantique, 05 logging, 06 prompt doctor. | Notebooks Python |
| `Standard-webapps/agent-factory-console/` | Console de la factory (webapp Standard admin, optionnelle) : édition du hub, Settings des modèles, assistant guidé. | Webapps Standard |
| `dev-harness/` | Simulateur local du front (Vite + mock backend, port 5199). | - |
| `docs/` | Spec V2, notes de phase, charte V2, Agent Factory, moteur natif, playbook manuel d'ajout d'agent. | - |
| `tests/` | Tests sans DSS des agents, du hub et de la factory : `python3 -m unittest discover -s OWIsMind_PRD_V2_0/tests`. | - |
| `registry.json` | Manifeste : ids, chemins, datasets, bindings modèle + tool. Non importé au runtime. | - |

## Ids essentiels (source : [registry.json](registry.json))

| Objet | Nom | Id |
|---|---|---|
| Code Agent | OWIsMind_orchestrator | `038G7mlF` |
| Code Agent | SalesDrive_revenue_expert | `bHrWLyOL` |
| Code Agent | CSSO_Trouble_Tickets_Expert | `NcE9LD2i` |
| Tool | `attribute_lookup_tool` (Custom Python) | `UUoynaL` |
| Tool | `revenue_semantic_query` (Semantic Model Query) | `v4oqA6R` |
| Tool | `tickets_semantic_query` (Semantic Model Query) | `nEirlso` |
| Modèle sémantique | `Drive_Revenues_Semantic_Model` | `AHUh9hb` |
| Modèle sémantique | `TroubleTickets_Semantic_Model` | `dM4jA4G` |

## Déploiement

- **Agent ou tool** : coller le fichier ENTIER dans son objet DSS (ids dans le CONFIG de chaque
  fichier, à vérifier contre `registry.json`). Orchestrateur et sous-agent modifiés ensemble = recollés ensemble.
- **Recette** : dans le Flow (scénario de refresh).
- **Hub / factory** : recoller TOUS les fichiers modifiés de la library ensemble, puis restart backend.
- **Backend ou front du plugin** : rebuild, zip (`plugin/tools/build_dev_plugin.py`), upload + restart.
- Projet dupliqué : repointer les modèles sémantiques ET les tools Semantic Model Query (notebook 02).

## Garde-fous

- **SQL en lecture seule** côté agents (transaction read-only, statement timeout) ; aucune ligne brute
  envoyée au LLM au runtime.
- **Honnêteté** : tout chiffre vient d'un résultat SQL ; aucune valeur métier en dur dans les agents.
- **Modèles LLM** : uniquement dans `owismind_hub/models.json`, zéro id en dur, zéro repli.
- **Contrats gelés** (event kinds, `AGENT_RESULT`, span `semantic-model-query`, `sql_id`, protocole
  workspace `plugin/owismind/contracts/`) : ne jamais renommer, seulement ajouter.
