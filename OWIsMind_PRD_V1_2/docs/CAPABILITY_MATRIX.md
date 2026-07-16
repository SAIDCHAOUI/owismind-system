# Capability matrix - Phase 0 probe results (TEMPLATE, fill from the probe)

> Run `notebooks/00_probe_capabilities.py` on the target instance and replace
> this template with the printed report (also saved to
> `/owismind_hub/probe_report.md`). Statuses below reflect the research +
> client-source verification of 2026-07-10, BEFORE any run on the instance.

| Capability | API | Doc status | Instance status |
|---|---|---|---|
| Managed datasets on SQL connection | `new_managed_dataset().with_store_into()` | CONFIRMED | TO PROBE |
| External SQL table import | `init_tables_import().add_sql_table()` | CONFIRMED | TO PROBE |
| Flow zones | `flow.create_zone()/add_item()` | CONFIRMED | TO PROBE |
| Python recipes with code + env | `new_recipe("python")` + `with_script/set_code_env` | CONFIRMED | TO PROBE |
| Custom python scenario + daily trigger | `create_scenario(..., "custom_python")` | CONFIRMED | TO PROBE |
| Semantic model create/edit/index | `create_semantic_model` + versions + `start_update_distinct_values` | PROVEN (build_aligned 2026-06) | OK (v1.2) |
| Code Agent creation | `create_agent(name, "PYTHON_AGENT")` | CONFIRMED (client source) | TO PROBE |
| Code Agent code injection | raw `versions[*].pythonAgentSettings` | UNDOCUMENTED schema | TO PROBE (gate) |
| Semantic Model Query tool creation | `new_agent_tool(type)` + params | UNDOCUMENTED type/params | TO PROBE (gate) |
| Interaction logging | `create_llm_interaction_logging_dataset` + selection.enable | CONFIRMED | TO PROBE |
| Project library hub | `get_library()` file CRUD | CONFIRMED | TO PROBE |
| Structured LLM output | `with_json_output(schema)` | CONFIRMED | TO PROBE |

## To fill after the probe

- `suggested_schema_hints` (code key + env template): ...
- `suggested_discovery` (tool type string + params template): ...
- Write probe round-trips confirmed: agent [ ] / tool [ ]
- Python 3.11 code env exact name: ...
