# OWIsMind

OWIsMind is a **Dataiku DSS plugin**: a **Vue 3 + Vite** webapp (built into static assets and served
by DSS) backed by a modular **Flask** backend in `python-lib/`. The backend talks to AI agents through
the **LLM Mesh** and stores conversations, messages, runs and events with **direct SQL**
(`SQLExecutor2`, PostgreSQL) - no Flow at runtime. Agent whitelisting, SQL safety and read-only bounds
are enforced server-side.

The agents themselves are **LangGraph Code Agents** (an orchestrator plus specialized sub-experts),
versioned in this repo as the source of truth and pasted into DSS.

## Repository layout

This branch holds ONE DSS project, mirrored with the DSS UI structure:
`flow/<zone>_zone/python-recipes/`, `GenAI/{Agents, agents-tools, semantic-models}`, `Notebooks/`,
`project-library/`, `Standard-webapps/`, `docs/`, `tests/`. The plugin lives INSIDE the project folder
and follows its version. Older versions live on their own git branches.

| Path | Purpose |
| --- | --- |
| `OWIsMind_PRD_V2_0/` | Repo mirror of the DSS project of V2.0. Map: `OWIsMind_PRD_V2_0/README.md`. |
| `OWIsMind_PRD_V2_0/plugin/` | The DSS plugin: source (`owismind/`), upload zips (`ready-for-dataiku/`, git-ignored), local build tooling (`tools/`). See `plugin/read.md`. |
| `docs/cadrage/` | Framing guides: Orange UI charter, DSS plugin engineering reference, Dataiku code samples, functional spec. |
| `memory/` | Persistent project memory: current context, lessons, durable state. |

## Running the tests

```sh
# Backend (Flask, python-lib)
python3 -m unittest discover -s OWIsMind_PRD_V2_0/plugin/owismind/tests

# Agents (LangGraph orchestrator + experts)
python3 -m unittest discover -s OWIsMind_PRD_V2_0/tests

# Frontend (pure Node tests, no browser)
cd OWIsMind_PRD_V2_0/plugin/owismind/frontend && node --test test/*.test.js
```

## AI-assisted workflow

`CLAUDE.md` documents the conventions, non-negotiable rules and memory protocol used when working on
this repository with an AI assistant. Read it before making changes.
