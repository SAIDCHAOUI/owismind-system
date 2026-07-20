# OWIsMind

OWIsMind is a **Dataiku DSS plugin**: a **Vue 3 + Vite** webapp (built into static assets and served
by DSS) backed by a modular **Flask** backend in `python-lib/`. The backend talks to AI agents through
the **LLM Mesh** and stores conversations, messages, runs and events with **direct SQL**
(`SQLExecutor2`, PostgreSQL) - no Flow at runtime. Agent whitelisting, SQL safety and read-only bounds
are enforced server-side.

The agents themselves are **LangGraph Code Agents** (an orchestrator plus specialized sub-experts),
versioned in this repo as the source of truth and pasted into DSS. Agent evaluation lives in a
**separate DSS project, `OWIsMind_LAB`**, mirrored under `OWIsMind_LAB/`.

## Repository layout

One folder per DSS project, each with the same internal structure (mirroring the DSS UI):
`flow/<zone>_zone/python-recipes/`, `GenAI/{Agents, agents-tools, semantic-models}`, `Notebooks/`,
`project-library/`, `Standard-webapps/`, `docs/`, `tests/`. The plugin lives INSIDE the main
project folder and follows its version.

| Path | Purpose |
| --- | --- |
| `OWIsMind_PRD_V1_3_DEV/` | Repo mirror of the DSS project `OWIsMind_PRD_V1_3_DEV` (v1.3 dev clone of prod, ids preserved). Map: `OWIsMind_PRD_V1_3_DEV/README.md`. |
| `OWIsMind_PRD_V1_3_DEV/plugin/` | The DSS plugin: source (`owismind/`), upload zips (`ready-for-dataiku/`, git-ignored), local build tooling (`tools/`). See `plugin/read.md`. |
| `OWIsMind_LAB/` | The separate benchmark/evaluation DSS project (repo mirror, same structure). Map: `OWIsMind_LAB/README.md`. |
| `docs/` | Engineering reference (architecture, API, data model, security, build/deploy), framing guides (`docs/cadrage/`), full documentation site (`docs/project-documentation/`, read on demand). See `docs/README.md`. |
| `memory/` | Persistent project memory: current context, lessons, durable state, session logs. |

## Running the tests

```sh
# Backend (Flask, python-lib)
python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests

# Agents (LangGraph orchestrator + experts)
python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests

# Benchmark LAB project
python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python

# Frontend (pure Node tests, no browser)
cd OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend && node --test test/*.test.js
```

## AI-assisted workflow

`CLAUDE.md` documents the conventions, non-negotiable rules and memory protocol used when working on
this repository with an AI assistant. Read it before making changes.
