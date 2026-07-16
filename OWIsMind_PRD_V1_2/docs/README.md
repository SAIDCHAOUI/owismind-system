# docs : documentation du sous-projet

Index des docs du miroir repo `OWIsMind_PRD_V1_2/`. Elles couvrent surtout l'Agent Factory v1.3
(creation industrialisee des sous-agents experts) et son deploiement sur le clone v1.3-dev.

## Dans ce dossier

| Fichier | C'est quoi | Quand le lire |
|---|---|---|
| [`DEPLOY_V1_3_DEV.md`](DEPLOY_V1_3_DEV.md) | LA marche a suivre pas a pas pour deployer la factory sur le clone v1.3-dev (phases ordonnees, rien ne touche la prod v1.2) | Commencer ici pour tout deploiement |
| [`AGENT_FACTORY.md`](AGENT_FACTORY.md) | L'architecture de la factory : les 3 piliers (`owismind_factory`, Config & Prompt Hub, console webapp) et la carte des modules | Pour comprendre comment ca marche |
| [`CAPABILITY_MATRIX.md`](CAPABILITY_MATRIX.md) | Le rapport de la sonde 00 (capacites API DSS, gates a deverrouiller) : c'est un template a remplir apres `notebooks/00_probe_capabilities.py` | Apres avoir lance la sonde sur l'instance |
| [`PLAYBOOK_ADD_AGENT.md`](PLAYBOOK_ADD_AGENT.md) | L'ancienne methode manuelle pour ajouter un sous-agent specialiste (validee pour tickets) | Reference : largement automatisee par la factory |

## Deploiement

Ces fichiers sont de la doc repo : ils ne se collent pas dans DSS. Le point d'entree
operationnel est [`DEPLOY_V1_3_DEV.md`](DEPLOY_V1_3_DEV.md).
