# tests/

Tests unitaires du miroir, SANS Dataiku : aucune connexion DSS n'est requise, tout tourne en local.

## Lancer la suite

Depuis la racine du repo :

```bash
python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests
```

468 tests : tous verts attendus (dont 2 skips pandas normaux en local, couverts en DSS).

## Ce qui est couvert

- Le moteur de la factory : builders, pipeline, preflight, durcissement (`test_factory_builders.py`, `test_factory_core.py`, `test_factory_align.py`, `test_factory_preflight.py`, `test_factory_hardening.py`, `test_factory_doctor.py`).
- Le wizard de creation de domaine (`test_factory_wizard_hardening.py`).
- Les agents : extraction des constantes par AST et contrats geles anti-derive entre le registre et le code des agents (`test_langgraph_agents.py`, `test_attribute_lookup.py`, `test_dataset_expert.py`).
- L'equivalence des seeds du hub avec les defauts embarques de l'orchestrateur, plus le regenerateur deterministe de seeds (`test_factory_registry.py`, `test_hub_seeds_regenerator.py`).
- Le profiler du Flow (`test_profiler.py`).

## Regle

Toute modification de code se valide en relancant la suite AVANT de coller quoi que ce soit dans DSS. Deploiement : voir [../docs/DEPLOY_V1_3_DEV.md](../docs/DEPLOY_V1_3_DEV.md).
