# Agent Factory Console (Standard DSS webapp)

Admin, design-time webapp that drives the OWIsMind "agent factory": it plans and runs the creation
of a new dataset-specialist sub-agent chain (source table -> Flow zone + knowledge recipes/datasets
-> semantic model -> Semantic Model Query tool -> Code Agent -> orchestrator registration) and edits
the Config & Prompt Hub (`/python/owismind_hub/`). It is SEPARATE from the OWIsMind Vue plugin webapp: agent
management is kept apart for now (it may merge into the plugin in a later version).

Four panes, same deploy model as the LAB webapps (`OWIsMind_LAB/Standard-webapps/*`):

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
2. The hub tree under the project library at `/python/owismind_hub/` (at least `capabilities.json` and
   `prompts/orchestrator_persona.md`). It is optional for the console to start (the Vue d'ensemble
   explains that the hub is absent until it is pushed), but the Reglages screen needs it to read/write.

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

## Screens (layout rebuilt 2026-10-14: 3 screens, one idea each)

The engine, the routes and every creation / removal function are unchanged; only the layout and
the wording changed. The shell header carries two nav entries (Vue d'ensemble, Reglages); the
guided run screen is reached from the overview.

- **Vue d'ensemble** (default): a SCHEMA of the orchestrator OWIsMind (root node: Code Agent id,
  number of sub-agents) linked by a trunk to each of its sub-agents (one node per capability of
  `capabilities.json`, read through `GET /api/state`). Each node shows the label, the domain, the
  source dataset, the capability key, the Code Agent id and the active / inactive state, with its
  actions on the node: **Activer / Desactiver** (`/api/capability/enable`, validated + backed-up
  hub write; the confirm modal and a notice after the change remind the operator to re-save the
  orchestrator then open a new conversation, lesson L168) and **Retirer** (the operator TYPES the
  domain name, server-side check, then a removal run is created through
  `/api/guided/start-removal`). One primary button **Ajouter un sous-agent**. When a guided run is
  active, a **Reprendre** banner names it (kind, sub-agent, stage n of N) and Ajouter / Retirer are
  disabled (one active run at a time).
- **Parcours** (add or remove a sub-agent): the server-persisted guided run in ONE readable column:
  the run head (kind, sub-agent, domain + source dataset, "Etape n sur N" + a segmented progress
  bar), the result of the stage that just finished (with any MANUAL leftovers), then the current
  stage card: "Ce qui va se passer" (one plain sentence + the exact objects the click will create,
  fill, check or delete; for the removal the server inventory, plus "Ce qui ne sera JAMAIS touche"
  = the source dataset and any dataset shared with another capability), the operator instructions
  for a manual stage, the button with its guarantee line, and the technical journal in a collapsed
  block (opened automatically on failure; open state survives the 1.5s job polling). "Toutes les
  etapes" is a collapsed list; "Abandonner ce parcours" sits at the bottom (marks the run, deletes
  nothing). Creation = 13 stages (preflight, plan, infra, first build, profile review, semantic
  wizard with AI draft + answers + re-draft, model + tool, template, code generation, Code Agent,
  capability, smoke test, enable); removal = 12 stages (inventory, disable, tool, Code Agent,
  semantic model, scenario, recipes, knowledge datasets, zone if empty, shared catalog rows, hub
  files + capability, final check). Each deletion stage repeats its exact deletion list in a danger
  confirm modal. The start form (domain, source dataset picker, FR / EN labels, optional lookup
  columns) shows a live preview of the 12 objects the run will create (names derived exactly like
  `spec.py`). Per-stage wording lives in `STAGE_UX` (front only; an unknown future stage falls back
  on the server title / detail). Routes `/api/guided/{current,start,start-removal,run,verify,abandon}`
  and `/api/wizard/draft`.
- **Improve** (button on every sub-agent node, added 2026-10-14): a guided REVIEW run that improves
  an existing sub-agent's understanding of its data from BUSINESS feedback, without rebuilding
  anything. 3 stages: (1) read the live semantic model back into the wizard config shape
  (read-only, synchronous at start); (2) the business expert writes, in their own words, the
  questions it got wrong and what it must know; one AI call (`/api/review/propose`, background job)
  reads the current setup, the profile digest, the column descriptions written in DSS by the data
  owners and 20 sample rows (first 300 rows, cells cut at 60 chars, columns whose NAME looks
  personal masked), and returns change cards (column meaning, recognize values, calculations,
  ready-made filters, other words, example questions, general rules, routing text), each with a
  plain-words reason, all kept by default; the expert unticks what is wrong (`/api/review/keep`);
  (3) save: the guarded apply path (factory ownership marker + model version backup), a value
  re-index only when a "recognize values" flag changed, the hub config copy updated, and the
  capability routing text when kept (then the orchestrator reload block). Models not created by
  the factory are refused (`review_not_supported`). Engine: `owismind_factory/review.py` + the
  review stages of `guided.py`; route `/api/guided/start-review`. Wording rule: every text is for a
  business person who knows nothing about AI agents (no technical vocabulary on this screen).
- **Compatibility probe** (no screen any more): the first creation stage explains it. When its
  journal shows that `probe_results.json` is absent from the hub (notebook 00 never recorded), a
  block says it is not blocking (tool + Code Agent stages fall back to guided manual steps), how to
  unlock them (run notebook 00 in DSS, then relaunch the check), and offers a read-only report
  (`/api/probe`, which writes nothing; only notebook 00 records the gates).
- **Reglages**: the orchestrator persona prompt `prompts/orchestrator_persona.md` (editable, plus
  each sub-agent's `prompts/<domain>/understand_extra.md` in the file picker; path allowlist
  unchanged) and the factory settings in read-only (`factory_settings.json`).

**UX rules (user field test 2026-10-14):** the whole UI is in ENGLISH. Manual stages show a
numbered checklist written front-side (`STAGE_UX[key].steps`, exact DSS clicks, copy buttons on
every name to type): "Done, check it" stays disabled until every step is ticked, then the backend
verifies in DSS; a failed check says in plain English what is missing (`NOT_DONE`), the engine's
French message goes to a collapsed "Server message (technical)" block. The engine's French
instruction text is never shown. The semantic wizard is a strict sequence: 1. Draft with AI (only
enabled action), 2. answer the AI's questions (changing an answer locks the check until
"Redraft"), 3. Done, check it. The dry-run plan's MANUAL lines (steps later automated by the run)
are no longer surfaced as "to do by hand". One "Label" field (sent as both label_en and label_fr; the engine only warns, non-blocking, in the log). A compact shell header carries the page identity (back link, eyebrow, title, one subtitle line with "Step n of N: <step>" during a run, and the page action such as "Add a sub-agent"); each stage card repeats "Step n of N". The plan stage is worded "Verify the plan (dry run)" and live runs say "Running..." only. "Reload the orchestrator" is spelled out as 3 steps
(open OWIsMind_orchestrator, Save without edit, start a new conversation) after enable / disable,
at the end of a run and after saving a prompt.

Removed from the UI (backend routes kept, still usable from notebooks / API): the one-shot domain
creation ("Nouveau domaine": `/api/plan` + `/api/execute`, a pre-assistant dev tool duplicating
notebook 03), its standalone semantic wizard, and the raw `capabilities.json` JSON editor
(`/api/hub/capabilities` POST); Activer / Desactiver / Retirer cover the registry.

Local simulator (no DSS, no install): `python3 dev-harness/console_sim.py` then
http://127.0.0.1:5198/ (real console files re-read on each load + the real `backend.py` on a fake
project whose world tracks what a creation builds and a removal deletes).

## Safety model

- **Dry-run first**: "Planifier" builds a plan with `FactoryContext(dry_run=True)`; it never touches
  DSS. "Exécuter" runs for real but every step is idempotent (`ensure_*`), and the **creation flows
  have no deletion step**. The one deletion path is the guided **capability-removal run** (see the
  Vue d'ensemble section above), bounded by the `safe_delete` identity gate, the protected source
  dataset, a server-side typed-domain confirmation and a click per stage.
- **Confirm on every mutation**: every mutating endpoint (`/api/execute`, `/api/probe`,
  `/api/wizard/draft`, `/api/hub/prompt` POST, `/api/hub/capabilities` POST, and every
  `/api/guided/*` POST) requires the JSON body to carry `"confirm": true`, else it returns
  `{"status":"error","error":"confirmation_required"}` and does nothing. The UI gates each of
  these behind a confirm modal. Guided stage runs share the single-mutating-job admission with
  `/api/execute` (one factory mutation at a time), and `/api/guided/verify` is refused (409
  busy) while a guided job runs.
- **Path allowlist**: hub prompt reads/writes are rejected unless the path starts with
  `/python/owismind_hub/prompts/`, and the path is additionally guarded against traversal (`..`) so it can
  never escape that prefix (the path from the client is never trusted).
- **Background jobs**: long actions return a `job_id`; the frontend polls `GET /api/job/<id>`. The
  job registry is bounded (last 20) and lock-guarded; a still-running job is never evicted by the
  bound. The poller retries transient failures with backoff instead of failing the job on the first
  hiccup. The execute job shares its `FactoryContext` with the poller so the journal streams live.
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
- Write access on the hub's `sql_connection` (default `SQL_owi`), used ONLY for the guided-run
  state table `{PROJECT_KEY}_owismind_factory_guided_v1` (CREATE TABLE IF NOT EXISTS + upserts,
  parameterized, committed). Without it the guided run screen reports `storage_not_configured`
  and the other screens keep working.

Because the actions run as the run-as user (not the viewer), treat this webapp as an **admin tool**
and restrict who can open it. See the DSS security note for webapps:
https://doc.dataiku.com/dss/latest/webapps/security.html

There is no per-viewer access control in this console: anyone who can open it can drive the factory
as the run-as identity. Deploy it only where that is acceptable (an admin space), exactly like the
LAB launcher webapp.

## Notes / assumptions

- English-only UI (internal admin tool, user decision 2026-10-14); code and comments in English. No em dash or en dash anywhere.
- No external network calls, no CDN fonts/scripts: everything is self-contained (inline SVG icons,
  local CSS tokens).
- The theme attribute lives on the `#afc` root element (not `document.body`) so the panes never
  clobber the surrounding DSS chrome; light/dark tokens are defined on `#afc` and
  `#afc[data-theme="dark"]`, so dark mode is automatic for every rule that uses the tokens.
- The backend codes against the FROZEN signatures of `pipeline.create_domain`, `probes.run_read_probes`
  / `probes.format_probe_report`, and `wizard.draft_model_config` / `wizard.merge_answers`. Those
  modules are authored in parallel; integration is verified once they land.
