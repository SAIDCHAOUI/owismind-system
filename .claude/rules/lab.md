---
paths: ["OWIsMind_LAB/**"]
description: Specificites du projet benchmark OWIsMind_LAB (contrat MOCK, tests, guides de deploiement). Chargees quand on touche au LAB.
---

# Gotchas OWIsMind_LAB (benchmark / eval des agents)

`OWIsMind_LAB/` = projet DSS SEPARE (miroir repo) qui evalue les agents ; ce n'est PAS le plugin. Carte complete : `OWIsMind_LAB/README.md`. Refs lecons dans `memory/LESSONS.md`.

- **Le MOCK est le contrat (L115, 3 instances)** : le front launcher est developpe/QA contre son propre MOCK JS. Toute divergence entre le MOCK et le vrai backend Python se regle en ALIGNANT LE BACKEND SUR LE MOCK (jamais l'inverse). Les bugs de contrat viennent presque toujours de cette derive.
- **Layout repo <-> DSS** :
  - `project-library/python/{benchmark, benchmark_webapp}` : recolles en project-library, importes `from benchmark ...` / `from benchmark_webapp ...`.
  - `webapps/{benchmark_launcher, benchmark_results}` : 2 webapps Standard (4 panes chacune : body.html / script.js / style.css / backend.py).
  - `local-variables.example.json` : la variable projet `benchmark` (config UNIQUE, zero hardcode).
  - scenario `Run_Benchmark` : 3 steps = `benchmark/dss_steps/step_*.py`.
- **Config** = la variable projet `benchmark` seulement (registre + appartenance + redo + suggestions + agents). Zero dataset neuf pour la config.
- **Nommage** : `agent_key = agent_id` partout (jamais le slug `orchestrator`). Noms de tables physiques > 63 octets raccourcis (meme regle que le plugin).
- **Tests** : `python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python`. Tests node des panes : `node --test` dans le dossier de la webapp.

## Guides de deploiement (a lire pour tout recoll)
- Moteur / setup : `OWIsMind_LAB/project-library/python/benchmark/SETUP_GUIDE.md`.
- Webapp complet (2 webapps Standard, permissions, variable) : `OWIsMind_LAB/project-library/python/benchmark_webapp/DEPLOY_GUIDE.md`.
