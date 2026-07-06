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

| Path | Purpose |
| --- | --- |
| `Plugin/` | The DSS plugin: Vue 3 frontend (`owismind/frontend/`), Flask backend (`owismind/python-lib/`), webapps, and the packaged upload zip. |
| `dataiku-agents/` | LangGraph Code Agents (orchestrator + revenue/tickets experts), per DSS project, plus the semantic model tooling. Map: `dataiku-agents/OWISMIND/README.md`. |
| `OWIsMind_LAB/` | The separate benchmark/evaluation DSS project (repo mirror). Map: `OWIsMind_LAB/README.md`. |
| `tools/` | Repo-level Python helper scripts (DEV plugin build, agent promotion). See `tools/README.md`. |
| `docs/` | Engineering reference (architecture, API, data model, security, build/deploy) and framing guides in `docs/cadrage/`. See `docs/README.md`. |
| `memory/` | Persistent project memory: current context, lessons, durable state, session logs. |
| `project-documentation/` | Full engineering documentation site (read on demand; may lag behind `memory/` + `docs/`). |
| `owismind-relaunch-email.html` | Standalone HTML communication asset (beta relaunch announcement). |

## Running the tests

```sh
# Backend (Flask, python-lib)
python3 -m unittest discover -s Plugin/owismind/tests

# Agents (LangGraph orchestrator + experts)
python3 -m unittest discover -s dataiku-agents/tests

# Benchmark LAB project
python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python

# Frontend (pure Node tests, no browser)
cd Plugin/owismind/frontend && node --test test/*.test.js
```

## AI-assisted workflow

`CLAUDE.md` documents the conventions, non-negotiable rules and memory protocol used when working on
this repository with an AI assistant. Read it before making changes.
