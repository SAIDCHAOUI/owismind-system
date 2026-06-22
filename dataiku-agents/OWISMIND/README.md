# OWISMIND - agent system, split per DSS project

The OWIsMind agents live in **two Dataiku projects** with the **same design** but
**different object ids**. This folder keeps one complete, ready-to-paste copy per
project so you never confuse a DEV id with a PROD id.

```
OWISMIND/
  README.md                         <- you are here (workflow + id map)
  migrate_semantic_model_to_project.py   cross-project: copy a model DEV -> PROD
  remap_semantic_model.py                cross-project: fix a model's table refs in place
  OWISMIND_DEV/         the DEVELOPMENT project  (build + validate HERE first)
  OWISMIND_PROD_V1/     the PRODUCTION project   (promote here once DEV is good)
```

Each project folder is self-contained and every deployable file is **prefixed
with the project key** so the file you open is unambiguous:

```
OWISMIND_DEV/                          (revenue + tickets-being-built)
  agents/
    OWISMIND_DEV_OWIsMind_orchestrator.py        -> Code Agent 038G7mlF
    OWISMIND_DEV_SalesDrive_revenue_expert.py    -> Code Agent bHrWLyOL
    OWISMIND_DEV_CSSO_Trouble_Tickets_Expert.py  -> Code Agent NcE9LD2i  (being built)
  tools/
    OWISMIND_DEV_attribute_lookup_tool.py        -> Custom Python tool UUoynaL
  recipes/         profile + value_index + value_catalog (identical across projects)
  semantic_model/  build/update/dump/drop scripts (DEV ids) + MODEL.md
                   + <ModelName>.v1.json   <- paste the live model config here (see below)
  registry.json    the DEV id manifest

OWISMIND_PROD_V1/                      (revenue only)
  agents/
    OWISMIND_PROD_V1_OWIsMind_orchestrator.py        -> Code Agent Xrv7GvfG
    OWISMIND_PROD_V1_SalesDrive_revenue_expert.py    -> Code Agent uO5hEzAs
  tools/
    OWISMIND_PROD_V1_attribute_lookup_tool.py        -> Custom Python tool szOZCoU
  recipes/         (identical to DEV)
  semantic_model/  update/dump/drop scripts (PROD ids) + MODEL.md
                   + Drive_Revenues_Model.v1.json   <- paste the live model config here
  registry.json    the PROD id manifest
```

## Semantic model config lives in the repo (no more pasting it in chat)

Each model's full config (`get_raw()`) is committed as
`semantic_model/<ModelName>.v1.json` so you never have to paste it in a prompt
again. To refresh it: run the matching `dump_*.py` in a DSS notebook on that
project and paste its output over the file.

| Project | File | Refresh with |
|---|---|---|
| OWISMIND_DEV | `semantic_model/Drive_Revenues_Semantic_Model.v1.json` | `dump_semantic_model.py` (MODEL_ID `AHUh9hb`) |
| OWISMIND_DEV | `semantic_model/TroubleTickets_Semantic_Model.v1.json` | `dump_tickets_semantic_model.py` (MODEL_ID `dM4jA4G`) |
| OWISMIND_PROD_V1 | `semantic_model/Drive_Revenues_Model.v1.json` | `dump_semantic_model.py` (MODEL_ID `a7K9jYk`) |

DEV (revenue + tickets) now hold the live dump; PROD still holds a placeholder
(paste a fresh `dump_semantic_model.py` output to populate it).

## The golden rule: develop in DEV, then promote to PROD

1. Make the change in **OWISMIND_DEV** (edit the `OWISMIND_DEV_*` file, paste it
   into the matching DSS Code Agent / tool, env 3.11). Run it, validate in DSS.
2. Once it works, **promote**: copy the change into the matching
   `OWISMIND_PROD_V1_*` file, keeping the PROD ids, and paste into the PROD
   object. Recipes do not change between projects; semantic-model scripts already
   carry the right per-project model id / table.
3. Never edit PROD without validating in DEV first. The tickets agent is the live
   example: it is being finished in DEV and is intentionally **absent from PROD**
   until it is validated.

## The id map (the whole point of this split)

| Object | DSS kind | OWISMIND_DEV | OWISMIND_PROD_V1 |
|---|---|---|---|
| OWIsMind_orchestrator | Code Agent | `038G7mlF` | `Xrv7GvfG` |
| SalesDrive_revenue_expert | Code Agent | `bHrWLyOL` | `uO5hEzAs` |
| CSSO_Trouble_Tickets_Expert | Code Agent | `NcE9LD2i` | (not in PROD yet) |
| attribute_lookup | Custom Python tool | `UUoynaL` | `szOZCoU` |
| revenue_semantic_query | Semantic Model Query tool | `v4oqA6R` | `sgk5pfln` |
| tickets_semantic_query | Semantic Model Query tool | `nEirlso` | (not in PROD yet) |
| Drive_Revenues model | Semantic Model | `AHUh9hb` (`Drive_Revenues_Semantic_Model`) | `a7K9jYk` (`Drive_Revenues_Model`) |
| TroubleTickets model | Semantic Model | `dM4jA4G` (`TroubleTickets_Semantic_Model`) | (not in PROD yet) |
| physical revenue table | PostgreSQL | `OWISMIND_DEV_drive_revenues` | `OWISMIND_PROD_V1_drive_revenues` |

Where these ids live in code (already baked in):
- orchestrator: `LOOKUP_TOOL_ID` (attribute_lookup) + `CAPABILITIES[...]["agent_id"]`
  (each sub-agent). The orchestrator's own Code Agent id is in its deploy-target header.
- sub-agents: `SEMANTIC_TOOL_ID` (their Semantic Model Query tool).
- semantic_model scripts: `NEW_MODEL_ID` / `MODEL_ID` + `PHYSICAL_TABLE` + project key.

## Tests, datasets, playbook

- Unit tests live in `../tests/` and run against the **DEV** copies (the dev
  source of truth). `python3 -m unittest discover -s dataiku-agents/tests`.
- Column inventory: `../DATASETS.md`. Adding a new specialist:
  `../PLAYBOOK_ADD_AGENT.md`. Engineering reference / contracts: `../CLAUDE.md`
  and `../README.md`.
- Recipes are dataset-agnostic (auto-IO) and identical across projects; they run
  in each project's Flow, no id to change.
