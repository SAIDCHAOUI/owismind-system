# genai/ - miroir de l'ecran GenAI de Dataiku

Ce dossier reflete l'ecran **GenAI** du projet DSS **OWISMIND_PRD_V1_2** : les
Code Agents, les Agent tools et les Semantic models. Le repo est la source
d'edition ; les objets vivants sont dans DSS.

## Dans Dataiku

Trois onglets de l'ecran GenAI, un sous-dossier chacun :

- **Code Agents** -> `agents/`
- **Agent tools** -> `agent-tools/`
- **Semantic models** -> `semantic-models/`

## Dans ce dossier

| Dossier | Role |
|---|---|
| `agents/` | Les 3 Code Agents (env Python 3.11) : `OWIsMind_orchestrator.py` (`038G7mlF`), `SalesDrive_revenue_expert.py` (`bHrWLyOL`), `CSSO_Trouble_Tickets_Expert.py` (`NcE9LD2i`). Chaque fichier se colle dans son Code Agent DSS. Voir [`agents/README.md`](agents/README.md). |
| `agent-tools/` | Le seul tool avec du Python custom a miroiter : `attribute_lookup_tool.py` (`UUoynaL`), appele par l'orchestrateur. Les autres tools sont de la configuration DSS sans code. Voir [`agent-tools/README.md`](agent-tools/README.md). |
| `semantic-models/` | Snapshots lisibles des 2 modeles semantiques (revenus `AHUh9hb`, tickets `dM4jA4G`), dumps JSON versionnes et `scripts/` (build, dump, repoint). Voir [`semantic-models/README.md`](semantic-models/README.md). |

## Deploiement

Un agent ou un tool modifie dans le repo se **REcolle** dans son objet DSS
(copier le fichier entier dans le Code Agent ou le tool correspondant). Les ids
sont bakes dans chaque fichier et recenses dans [`../registry.json`](../registry.json)
(carte complete : [`../README.md`](../README.md)). Pour le deploiement v1.3,
suivre [`../docs/DEPLOY_V1_3_DEV.md`](../docs/DEPLOY_V1_3_DEV.md).
