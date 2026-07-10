# Agent Factory Console (Standard DSS webapp)

Admin, design-time webapp that drives the OWIsMind "agent factory": it plans and runs the creation
of a new dataset-specialist sub-agent chain (source table -> Flow zone + knowledge recipes/datasets
-> semantic model -> Semantic Model Query tool -> Code Agent -> orchestrator registration) and edits
the Config & Prompt Hub (`/owismind_hub/`). It is SEPARATE from the OWIsMind Vue plugin webapp: agent
management is kept apart for now (it may merge into the plugin in a later version).

Four panes, same deploy model as the LAB webapps (`OWIsMind_LAB/webapps/*`):

| Pane | File |
|---|---|
| HTML | `body.html` |
| JS | `script.js` |
| CSS | `style.css` |
| Python backend | `backend.py` |

## Prerequisites (project library)

The backend imports the factory engine and the hub from the DSS **project library** (`python/`):

```
from owismind_factory import fctx, hub, pipeline, probes, wizard
from owismind_factory.spec import DomainSpec, SpecError
```

So before this webapp can start, the following must be present in the project library and the hub
tree pushed:

1. `project-library/python/owismind_factory/` (the whole package: `fctx.py`, `spec.py`, `hub.py`,
   `registry.py`, `pipeline.py`, `probes.py`, `wizard.py`, ...). In DSS, the project library
   `python/` folder is on the import path of webapp backends, so `from owismind_factory import ...`
   resolves without any extra wiring.
2. The hub tree under the project library at `/owismind_hub/` (at least `capabilities.json` and
   `prompts/orchestrator_persona.md`). It is optional for the console to start (the Overview screen
   simply shows "HUB ABSENT" until it is pushed), but the Prompts screen needs it to read/write.

If the library is not pushed, the webapp backend fails to start loudly, which is the intended signal.

## Create the Standard webapp in DSS

1. In the DSS project, go to `</> Code` > `Webapps` > `+ New webapp` > `Standard` (an empty
   standard webapp). Name it e.g. `Agent Factory Console`.
2. Paste each file into its pane:
   - HTML pane <- `body.html` (BODY content only, no `<html>`/`<head>`).
   - JS pane <- `script.js`.
   - CSS pane <- `style.css`.
   - Python pane <- `backend.py`. Enable the backend if the editor asks (the Python pane must be on).
3. Save, then start the backend. Open the webapp view.

The frontend reaches the backend through `getWebAppBackendUrl('api/...')` (DSS wires this
automatically inside the webapp iframe).

## Screens

- **Vue d'ensemble**: project key, hub status (ready / absent), factory settings, and the existing
  capabilities as square cards (domain, agent id, enabled state). Read-only.
- **Sonde (Phase 0)**: one button runs the read-only probes in a background job, then shows the
  markdown report (copy button). The probes inspect the instance (Code Agent API shape, Semantic
  Model Query tool schema, `create_agent` availability) and create / modify / delete nothing.
- **Nouveau domaine**: a form (domain key, base dataset or SQL source table, FR/EN labels, lookup
  search columns) -> "Planifier (dry-run)" renders the action plan as a table -> "Exécuter"
  (confirm modal) runs the pipeline in a background job with a live journal; MANUAL steps are listed
  as a checklist at the end. A "Wizard sémantique" section drafts the semantic model config from a
  profile dataset (LLM call), asks clarifying questions, and re-drafts with the answers.
- **Prompts**: edit a hub prompt file (path constrained to `/owismind_hub/prompts/`) and the
  `capabilities.json` registry (server-side validated, previous version backed up).

## Safety model

- **Dry-run first**: "Planifier" builds a plan with `FactoryContext(dry_run=True)`; it never touches
  DSS. "Exécuter" runs for real but every step is idempotent (`ensure_*`), and there is **no
  deletion path anywhere** in the factory or this console.
- **Confirm on every mutation**: every mutating endpoint (`/api/execute`, `/api/probe`,
  `/api/wizard/draft`, `/api/hub/prompt` POST, `/api/hub/capabilities` POST) requires the JSON body
  to carry `"confirm": true`, else it returns `{"status":"error","error":"confirmation_required"}`
  and does nothing. The UI gates each of these behind a confirm modal.
- **Path allowlist**: hub prompt reads/writes are rejected unless the path starts with
  `/owismind_hub/prompts/` (the path from the client is never trusted).
- **Background jobs**: long actions return a `job_id`; the frontend polls `GET /api/job/<id>`. The
  job registry is bounded (last 20) and lock-guarded. The execute job shares its `FactoryContext`
  with the poller so the journal streams live.
- **Capabilities validation**: `POST /api/hub/capabilities` validates with
  `hub.validate_capabilities` (required keys, label dicts, one enabled capability per domain) and
  returns the problems on 400 without writing anything.

## Permissions and identity (important)

A DSS webapp runs as its **run-as user** (the webapp owner / the configured run-as identity), NOT as
the viewer. Give that identity the rights the console needs on this project:

- **WRITE_CONF** (write project configuration) so the factory can create datasets, recipes, zones,
  the scenario, the semantic model, the tool and the Code Agent, and so the backend can write hub
  files to the project library.
- Read access to the source SQL connection used by the base + knowledge datasets.

Because the actions run as the run-as user (not the viewer), treat this webapp as an **admin tool**
and restrict who can open it. See the DSS security note for webapps:
https://doc.dataiku.com/dss/latest/webapps/security.html

There is no per-viewer access control in this console: anyone who can open it can drive the factory
as the run-as identity. Deploy it only where that is acceptable (an admin space), exactly like the
LAB launcher webapp.

## Notes / assumptions

- French-only UI (internal admin tool); code and comments in English. No em dash or en dash anywhere.
- No external network calls, no CDN fonts/scripts: everything is self-contained (inline SVG icons,
  local CSS tokens).
- The theme attribute lives on the `#afc` root element (not `document.body`) so the panes never
  clobber the surrounding DSS chrome; light/dark tokens are defined on `#afc` and
  `#afc[data-theme="dark"]`, so dark mode is automatic for every rule that uses the tokens.
- The backend codes against the FROZEN signatures of `pipeline.create_domain`, `probes.run_read_probes`
  / `probes.format_probe_report`, and `wizard.draft_model_config` / `wizard.merge_answers`. Those
  modules are authored in parallel; integration is verified once they land.
