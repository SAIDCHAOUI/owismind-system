# hub/ - repo seeds of the DSS Config & Prompt Hub (/owismind_hub/)

> These files SEED the `/owismind_hub/` tree in the DSS **project library**
> (pushed by `notebooks/01_push_config_hub.py`, which embeds them; this folder
> is the readable mirror). The hub is what the agents load at startup so the
> team can iterate prompts and register capabilities WITHOUT re-pasting agent
> code. Agents fall back to their embedded defaults on ANY hub problem.

| File | Pushed to | Read by |
|---|---|---|
| `capabilities.json` | `/owismind_hub/capabilities.json` | orchestrator (section 7b loader) |
| `prompts/orchestrator_persona.md` | `/owismind_hub/prompts/orchestrator_persona.md` | orchestrator (PERSONA override) |
| `factory_settings.json` | `/owismind_hub/factory_settings.json` | owismind_factory (instance knobs) |
| (created in DSS) | `/owismind_hub/prompts/<domain>/understand_extra.md` | the domain's specialist (ADDITIVE UNDERSTAND rules) |
| (created in DSS) | `/owismind_hub/templates/dataset_expert.py` | agent_builder (engine template) |
| (created in DSS) | `/owismind_hub/generated/`, `/wizard/`, `/doctor/`, `/backups/` | factory outputs |

## Equivalence guarantee (do not break)

`capabilities.json` and `orchestrator_persona.md` are GENERATED from
`agents/OWIsMind_orchestrator.py` (CAPABILITIES_DEFAULT / PERSONA_DEFAULT) so
pushing the hub changes NOTHING until a human edits a hub file.
`tests/test_factory_registry.py` enforces the equivalence: if you edit the
embedded defaults in the orchestrator, regenerate these seeds (and vice versa),
then re-run the suite.

## Editing rules

- capabilities.json: validated on load (required keys, `agent:` ids, ONE enabled
  capability per domain, frozen block/tool label keys). An invalid file is
  IGNORED by the orchestrator (fallback to embedded defaults + a warning in the
  agent log): check the log after every edit.
- Prompts: plain markdown/text. The persona override must stay between 500 and
  20000 chars (size sanity window); understand_extra files are capped at 4000
  chars and are ADDITIVE only.
- Any edit takes effect at the next agent process start (re-save the agent or
  shutdown/wake it in DSS).
- Never store secrets here: the library is readable by every project reader.
- No em dash / en dash anywhere (project rule #9).
