# project-library/ - miroir de la project library DSS

Ce dossier reflète le menu **Libraries** du projet DSS : le code partagé
(`python/`) et l'arbre de configuration `/owismind_hub/` que les agents lisent
à leur démarrage. On édite ici, puis on pousse dans DSS (jamais l'inverse).

## Dans Dataiku

- `python/owismind_factory/` correspond au dossier `python/` de la project
  library du clone v1.3-dev : le code y est importable par les notebooks et le
  backend de la console.
- `owismind_hub/` correspond à l'arbre `/owismind_hub/` à la racine de la
  library : prompts, registre de capabilities, réglages d'instance. Les agents
  le LISENT au démarrage ; seule la factory (notebook ou console) y écrit.
- La library est lisible par tous les lecteurs du projet : **jamais de secret
  ici**.

## Dans ce dossier

| Dossier | Rôle |
|---|---|
| `python/owismind_factory/` | Le moteur de l'Agent Factory v1.3 (13 modules : `fctx`, `spec`, `hub`, `probes`, `flow_builder`, `semantic_builder`, `tool_builder`, `agent_builder`, `registry`, `align`, `pipeline`, `wizard`, `doctor`). Dry-run par défaut, étapes `ensure_*` idempotentes, aucune suppression, API Dataiku publique uniquement, stdlib + `dataiku`, compatible Python 3.9. À coller dans le dossier `python/` de la library du clone v1.3-dev. |
| `owismind_hub/` | Les graines (seeds) du Config & Prompt Hub `/owismind_hub/` : `capabilities.json`, `prompts/orchestrator_persona.md`, `factory_settings.json`. Poussées par le notebook `01_push_config_hub.py`. Détail : [owismind_hub/README.md](owismind_hub/README.md). |

Garde-fous à ne pas casser :

- **Équivalence des seeds** : `capabilities.json` et `orchestrator_persona.md`
  sont générés depuis les défauts embarqués de l'orchestrateur ; pousser le hub
  ne change RIEN tant qu'un humain n'édite pas un fichier du hub (test
  anti-dérive `tests/test_factory_registry.py`).
- **Fallback embarqué** : au moindre problème de hub (fichier absent ou
  invalide), les agents retombent sur leurs défauts embarqués.
- **Lecture seule par défaut** : chaque appel mutant de la factory passe par un
  `FactoryContext` en `dry_run=True` tant qu'on ne le bascule pas explicitement,
  et chaque action est enregistrée.

## Déploiement

Coller `python/owismind_factory/` dans la library du clone v1.3-dev, puis
pousser le hub via `../notebooks/01_push_config_hub.py` : voir
[../docs/DEPLOY_V1_3_DEV.md](../docs/DEPLOY_V1_3_DEV.md), phase B.
