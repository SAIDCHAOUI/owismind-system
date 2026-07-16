# notebooks/ : les telecommandes de l'Agent Factory

Sept scripts Python numerotes 00 a 06. Chacun se colle dans un notebook Python
du projet DSS cible (le clone v1.3-dev) et se lance a la main, jamais en automatique.
Ils pilotent le package `owismind_factory` et le Config & Prompt Hub `/owismind_hub/`.

## Dans Dataiku

Chaque fichier devient un notebook Python du projet (Notebooks > New > Python,
coller le contenu). Prerequis : le package `owismind_factory` doit d'abord etre
colle dans la project library du projet
(repo : [`../project-library/python/owismind_factory/`](../project-library/python/owismind_factory/)).

## Dans ce dossier

| Notebook | Role | Garde-fou |
|---|---|---|
| `00_probe_capabilities.py` | Sonde les capacites de l'instance (API factory, cles du Code Agent live, tool Semantic Model Query) et produit un rapport markdown | Lecture seule par defaut (`RUN_WRITE_PROBES = False`) ; les write probes ne creent/suppriment que 2 objets jetables `zz_factory_probe` |
| `01_push_config_hub.py` | Pousse les seeds du Config & Prompt Hub `/owismind_hub/` (settings, capabilities.json, persona, template engine) | Seeds equivalentes aux defauts embarques : ne change rien au comportement ; n'ecrit que ce qui est absent sauf `FORCE = True` |
| `02_align_clone.py` | Aligne un clone : les modeles semantiques d'un projet duplique pointent encore les tables du projet SOURCE ; remappe les cles listees dans `EXPECTED_SOURCE_KEYS` vers la cle du projet courant | Deux verrous : liste vide = mode decouverte (rien n'est remappe, les cles etrangeres sont juste listees) ; `DRY_RUN = True` d'abord (plan seulement) |
| `03_create_domain.py` | LA factory : cree un domaine complet (table source vers chaine specialiste) a partir d'une `SPEC` | Toujours un premier run en `DRY_RUN = True` et LIRE le plan avant d'executer ; idempotent ; le premier build de connaissance n'est jamais lance automatiquement |
| `04_semantic_wizard.py` | Wizard semantique assiste par LLM : draft de config, questions de clarification (en francais), puis config finale sauvee dans le hub | Une seule completion LLM par run, sur metadonnees agregees (jamais de lignes brutes) ; la sortie est un DRAFT a relire |
| `05_enable_interaction_logging.py` | Active le logging des interactions LLM (orchestrateur + sous-agents) vers un dataset de logs unique | `DRY_RUN = True` d'abord : plan seulement ; API publique documentee uniquement |
| `06_prompt_doctor.py` | Lit les logs recents, diagnostique le comportement via un LLM et ecrit une PROPOSITION de prompt revisee dans le hub | Ne modifie JAMAIS un prompt d'agent : la proposition est relue et appliquee a la main, puis re-benchmarkee |

## Deploiement

Ordre officiel, phases et ce qu'il faut verifier a chaque etape :
[`../docs/DEPLOY_V1_3_DEV.md`](../docs/DEPLOY_V1_3_DEV.md)
(phases A a G : clone, install de la library, probe 00, hub 01, re-paste des agents, gates, domaine, logging).
