# Standard-webapps/ - miroir des webapps Standard DSS du projet

Ce dossier est le miroir repo des webapps Standard du projet DSS (`OWIsMind_PRD_V1_3_DEV` sur cette branche). On edite ici, puis on colle le contenu dans la webapp DSS correspondante. NB : la webapp PRINCIPALE (chat Vue 3) n'est pas ici, elle appartient au PLUGIN (`../plugin/owismind/webapps/`).

## Dans Dataiku

Chaque sous-dossier correspond a une webapp **Standard** du projet (panes HTML / JS / CSS / backend Python, comme les webapps du LAB).

## Dans ce dossier

| Dossier | Role |
|---|---|
| [`agent-factory-console/`](agent-factory-console/) | Console de l'Agent Factory (webapp Standard, admin, design-time, **optionnelle**) : plan et execution de la creation d'un nouveau sous-agent de domaine, wizard, edition du Config & Prompt Hub (`/python/owismind_hub/`). |

Tout ce que fait la console est aussi faisable via les notebooks runners 00 a 06 ([`../Notebooks/`](../Notebooks/)) : la console n'est pas un prerequis.

**Important** : la webapp de chat OWIsMind (Vue 3, celle des utilisateurs) ne vit PAS ici. Elle fait partie du plugin, sous `../plugin/owismind/` dans ce dossier projet.

## Deploiement

- Console : creation de la webapp Standard et prerequis (package `owismind_factory` + hub pousses dans la project library) dans [`agent-factory-console/README.md`](agent-factory-console/README.md).
- Contexte v1.3 complet : [`../docs/DEPLOY_V1_3_DEV.md`](../docs/DEPLOY_V1_3_DEV.md).
