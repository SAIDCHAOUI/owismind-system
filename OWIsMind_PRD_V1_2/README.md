# OWIsMind_PRD_V1_2 : miroir repo du projet DSS de production

Ce dossier est le miroir exact du projet Dataiku DSS de production **OWIsMind_PRD_V1_2**
(project key `OWISMIND_PRD_V1_2`). Ce projet DSS est un **clone du projet DEV `OWISMIND_DEV`** :
tous les ids d'objets DSS sont les ids DEV, conservés par la duplication.

Règle de travail : **on édite ici, puis on colle dans DSS** (jamais l'inverse ; une édition
directe dans DSS est écrasée au prochain collage). Les versions avancent par branche git :
une branche par version, nommée comme le projet DSS prod (`OWIsMind_PRD_V1_2` = prod courante,
`OWIsMind_PRD_V1_3-dev` = dev en cours ; la promotion retire le suffixe `-dev`).

## Comment le système marche

La webapp Vue envoie le message et une clé logique d'agent (jamais un id brut) au backend
Flask (`python-lib`, à la racine du repo). Le backend résout la clé via une whitelist côté
serveur et invoque l'orchestrateur par LLM Mesh. L'orchestrateur raisonne et route vers les
sous-agents experts (revenus, tickets) ; chaque sous-agent délègue le SQL à son modèle
sémantique, exécuté en lecture seule sur PostgreSQL. Tout chiffre affiché vient d'un
résultat SQL : l'orchestrateur ne détient aucune donnée métier et ne peut pas en inventer.

## Arborescence

L'arborescence reflète l'UI Dataiku (Flow, GenAI, Project Library, Notebooks, Webapps).

| Dossier / fichier | Rôle | Détail |
|---|---|---|
| `flow/` | Recettes Flow par zone : elles fabriquent les datasets de connaissance (profile, value_index, value_catalog) lus par les agents. | [flow/README.md](flow/README.md) |
| `genai/agents/` | Les 3 Code Agents (orchestrateur + 2 sous-agents), fichiers autonomes à coller dans DSS (env Python 3.11). | [genai/agents/README.md](genai/agents/README.md) |
| `genai/agent-tools/` | Le tool Custom Python `attribute_lookup_tool` (lecture rapide de valeurs, appelé par l'orchestrateur). | [genai/agent-tools/README.md](genai/agent-tools/README.md) |
| `genai/semantic-models/` | Les 2 modèles sémantiques (snapshots `.v1.json`) + scripts (build, dump, repoint) : le cerveau SQL. | [genai/semantic-models/README.md](genai/semantic-models/README.md) |
| `project-library/python/owismind_factory/` | Agent Factory v1.3 : package Python qui industrialise la création de nouveaux agents (probe, builders, wizard, pipeline). Collé dans la project library DSS. | [docs/AGENT_FACTORY.md](docs/AGENT_FACTORY.md) |
| `project-library/owismind_hub/` | Seeds du Config & Prompt Hub (`/owismind_hub/` à la racine de la project library DSS) : prompts et CAPABILITIES lus par les agents au démarrage, avec fallback embarqué dans le code. | [project-library/owismind_hub/README.md](project-library/owismind_hub/README.md) |
| `notebooks/` | Les 7 notebooks runners de la factory, 00 à 06 (probe, push hub, align clone, create domain, wizard, logging, doctor). | [notebooks/README.md](notebooks/README.md) |
| `webapps/` | Console de la factory (webapp Standard, optionnelle : tout est aussi faisable via les notebooks). | [webapps/agent-factory-console/README.md](webapps/agent-factory-console/README.md) |
| `docs/` | Docs du sous-projet : déploiement v1.3, architecture factory, matrice de capacités, playbook manuel. | [docs/](docs/) |
| `tests/` | Tests unitaires sans DSS. Lancer : `python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests` (depuis la racine du repo). | - |
| `registry.json` | Manifeste unique : ids, chemins de fichiers, noms de datasets, bindings modèle + tool, guardrails. Non importé au runtime, tenu en phase avec CAPABILITIES de l'orchestrateur. | [registry.json](registry.json) |

## Ids essentiels

Source de vérité : [registry.json](registry.json). Les ids sont les ids DEV, conservés par le clone.

### Code Agents (env Python 3.11)

| Fichier | Code Agent DSS | Id |
|---|---|---|
| `genai/agents/OWIsMind_orchestrator.py` | OWIsMind_orchestrator | `038G7mlF` (`agent:038G7mlF`) |
| `genai/agents/SalesDrive_revenue_expert.py` | SalesDrive_revenue_expert | `bHrWLyOL` (`agent:bHrWLyOL`) |
| `genai/agents/CSSO_Trouble_Tickets_Expert.py` | CSSO_Trouble_Tickets_Expert | `NcE9LD2i` (`agent:NcE9LD2i`) |

### Tools DSS

| Tool | Type | Id | Appelé par |
|---|---|---|---|
| `revenue_semantic_query` | Semantic Model Query | `v4oqA6R` | le sous-agent revenus (QUERY) |
| `tickets_semantic_query` | Semantic Model Query | `nEirlso` | le sous-agent tickets (QUERY) |
| `attribute_lookup_tool` | Custom Python | `UUoynaL` | l'orchestrateur (built-in) |

### Modèles sémantiques

| Modèle | Id | Domaine |
|---|---|---|
| `Drive_Revenues_Semantic_Model` | `AHUh9hb` | revenus (`DRIVE_Revenues`) |
| `TroubleTickets_Semantic_Model` | `dM4jA4G` | tickets (`TroubleTickets_year`) |

## Déploiement

Un changement d'agent ou de tool se déploie en **collant le fichier correspondant** dans son
objet DSS (Code Agent en env 3.11, Custom Python tool) ; les ids sont dans le CONFIG de
chaque fichier, à vérifier contre `registry.json`. Un changement de recette se déploie dans
le Flow (scénario de refresh). Un changement du backend `python-lib` demande un zip + restart.

- Déploiement de l'Agent Factory v1.3 (lib, hub, notebooks, console) : [docs/DEPLOY_V1_3_DEV.md](docs/DEPLOY_V1_3_DEV.md)
- Ajout manuel d'un agent spécialiste (méthode historique) : [docs/PLAYBOOK_ADD_AGENT.md](docs/PLAYBOOK_ADD_AGENT.md)

## Garde-fous

- **SQL en lecture seule** partout (transaction read-only, statement timeout, tables
  whitelistées) ; aucune ligne brute envoyée au LLM.
- **Honnêteté** : tout chiffre vient d'un résultat SQL ; aucune valeur métier en dur dans le
  code des agents (tout vient du profile / value_index / catalog / overrides).
- **Hub avec fallback** : les agents lisent `/owismind_hub/` au démarrage mais embarquent un
  fallback ; `regenerate_seeds.py` maintient les seeds du repo équivalents aux défauts de
  l'orchestrateur. Jamais de secrets dans le hub ni dans le repo.
- **Contrats gelés** (event kinds, `AGENT_RESULT`, span `semantic-model-query`, `sql_id`,
  registry <-> `KNOWN_*` du sous-agent) : ne jamais renommer, seulement ajouter.

## Règle de version git

Une branche par version. Tout changement se développe et se valide sur la branche `-dev`
courante (`OWIsMind_PRD_V1_3-dev`), est testé dans le clone DSS, puis est promu en retirant
le suffixe `-dev`. **Ne jamais coller du code non testé dans les objets DSS de production.**
`main` est dépréciée.
