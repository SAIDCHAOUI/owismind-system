# Runbooks (incident procedures)

> Audience: OWIsMind operator and support. Last updated: 2026-06-19. Summary: nine concrete
> symptom -> checks -> resolution procedures for the most frequent failures (silent agent,
> storage not configured, agent not enabled, mode with no answer, slowness in High, empty chart,
> non-clickable Evidence source, budget exceeded, agent profile not filled), each with its own checklist.

This document is an intervention toolbox. Each runbook follows the same structure: a symptom
observable on the user side, the checks to run (from least to most costly), the resolution,
then a checklist to tick. Build/package/upload commands are never run by an agent:
only the operator acts (NO INSTALL rule). File names, error codes and config ids are quoted
verbatim from the code.

## Cross-cutting reminders before any diagnosis

Three structuring facts recur in almost every runbook, so let us state them once:

- The transport is **polling by thread** (no SSE): the agent runs in a worker thread on the
  backend, the frontend polls `GET /owismind-api/chat/poll` every 500 ms. The text answer often
  arrives in one block at the end; the usable live signal is the **timeline**, not the prose. Detail in
  [Backend - streaming and runs](../04-backend/03-streaming-and-runs.md).
- The Flask backend (Python 3.9.23) and the two LangGraph **Code Agents** (Python env 3.11) are **two
  distinct processes**. A change in `python-lib/` requires a **Restart backend**; an agent
  change requires you to **re-paste the two Code Agents** (without touching the zip). See
  [Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md).
- The application-level HTTP error codes are stable and carried by `api/routes.py`:
  `storage_not_configured` (409), `agent_not_enabled` (404), `busy` (503), `rate_limited` (429),
  `run_not_found` (404), `storage_unavailable` (500), `agent_unavailable` (500), `unauthenticated` (401),
  `monthly_quota_exceeded` (402, monthly budget exhausted).

The two main observation points:

- **The DSS webapp log** (backend), content-free by design: it never logs the content of a
  message, only its length (`/chat/start - ... msg_len=%d`), the `WARNING` entries (storage not configured,
  agent_key not enabled, pre-write rejection) and at boot an `OWIsMind storage status: ...`. See
  [Monitoring and logs](03-monitoring-and-logs.md).
- **The webapp Admin page** (admin-gated route `GET /owismind-api/admin/storage`) which exposes the
  resolved storage configuration (`storage_status()`): connection, project key, prefix, table names.

---

## Runbook 1 - The agent no longer answers / stays on "Parsing the request"

### Symptom

The timeline shows the first step **"Parsing the request"** (i18n key `tl.kind.turn_start`,
`registries/timelineSteps.js`) and does not advance, or the spinner keeps turning without a final answer. This is the
most frequently reported case from users.

### Mental model

The worker emits `run_started`, then the agent events, then `final_answer` + `run_done`. As long as no
event after `run_started` arrives, the frontend stays on the first step. Two families of causes:
the run is **still running** (long LLM Mesh call, normal in High), or the run **has died** (backend restarted,
agent unreachable, deadline reached).

### Checks (from least to most costly)

| Order | Check | Interpretation |
|---|---|---|
| 1 | Is the mode **High**? | A long Sonnet call is normal. See Runbook 5 before concluding it is a failure. |
| 2 | Wait ~10 to 30 s | Stop and deadlines are evaluated BETWEEN two chunks; a blocked upstream call does not hand back control instantly. |
| 3 | Has the backend been restarted recently? | A restart kills the in-memory state `_RUNS`; the in-flight run is lost. |
| 4 | Browser console: does the poll return `run_not_found`? | TERMINAL code on the frontend side (`TERMINAL_CODES` in `composables/useChatStream.js`): the run has disappeared. |
| 5 | Backend log: `agent_unavailable` or `run_<reason>`? | The agent raised, or the deadline `MAX_RUN_SECONDS` (300 s) / abandonment cut it off. |

### Automatic behaviors to know (before acting)

- If the poll fails with `run_not_found` (typically after a Restart backend mid-run), the frontend does not
  crash: it applies an error event **`run_lost`** and terminates the run cleanly as recoverable
  (`useChatStream.js`). The user can simply **resend their question**.
- A transient poll blip (the DSS proxy hiccups) is **retried with backoff** up to 5 failures
  (`MAX_POLL_FAILURES`) before giving up: a one-second outage does not break the run.
- The run has hard deadlines on the worker side: `MAX_RUN_SECONDS = 300 s`, `ABANDON_AFTER_SECONDS = 30 s`
  after polling begins if the tab has been closed, TTL eviction (`FINISHED_TTL_SECONDS = 60 s`,
  `HARD_TTL_SECONDS = 600 s`). No run accumulates memory indefinitely.

### Resolution

1. **Wait** first (cause #1/#2): in High, allow at least 20 to 30 s.
2. If `run_not_found` / `run_lost` appears: **resend the question** (the original run is lost, this is
   expected after a restart). No server action is required.
3. If `agent_unavailable` recurs repeatedly: the LLM Mesh agent is unreachable on the DSS side. Verify
   that the two Code Agents are properly **pasted and started** on env 3.11, and that the model ids
   match the Mesh connection (proceed to Runbook 4).
4. If **all** runs stay blocked (not only one user's): check the backend health via
   `GET /owismind-api/ping`; if the backend does not answer, the **Restart backend** from the webapp
   Settings is the way. After restart, in-flight runs are lost (assumed); ask users
   to relaunch their question.
5. If the symptom is isolated to a user clicking fast: they may be `rate_limited` (429,
   minimum spacing `MIN_START_INTERVAL_SECONDS = 1 s`) or hit `busy` (503,
   `MAX_CONCURRENT_RUNS = 8`). This is a guardrail, not a failure: retry after a short pause.

### Checklist

- [ ] Mode identified (High? -> tolerate the latency)
- [ ] Reasonable wait observed (>= 20 s)
- [ ] Browser console read (presence of `run_not_found` / `run_lost`?)
- [ ] Backend log read (`agent_unavailable` / `run_timeout` / `run_abandoned`?)
- [ ] Recent backend restart ruled out or confirmed
- [ ] If run lost: question resent
- [ ] If agent unreachable: proceed to Runbook 4 (ids + re-paste agents)

---

## Runbook 2 - "storage not configured" (HTTP 409 `storage_not_configured`)

### Symptom

The application refuses to send a message, list conversations, record feedback or
open Evidence. The backend returns **`storage_not_configured`** with an HTTP **409**. At boot, the backend
log records an `OWIsMind storage status: ...`.

### Cause

No SQL connection is selected in the webapp Settings. The backend NEVER relies on
an implicit connection: `sql_config.new_executor()` raises if no connection is configured, and each
route guards itself first via `sql_config.is_configured()` (which simply tests `connection_name() is not
None`). As long as the admin has chosen nothing, `is_configured()` is false and the route short-circuits with 409.

### Checks

| Order | Check | Tool |
|---|---|---|
| 1 | Is the connection empty? | Webapp Settings (param `sql_connection`) OR Admin page -> `storage.connection == null`. |
| 2 | Is the chosen connection indeed PostgreSQL? | The `sql_connection` selector only offers PostgreSQL connections (`compute_available_connections.py`). |
| 3 | Has the backend been restarted after choosing the connection? | A backend param change requires a Restart backend to be taken into account. |
| 4 | Does `storage_status()` report the right `project_key`? | Admin page -> `storage.project_key` and `project_key_source`. |

### Resolution

1. Open the OWIsMind **webapp Settings** and select the **SQL connection**: the project's
   canonical connection is **`SQL_owi`** (PostgreSQL, schema `public`).
2. **Restart backend** of the webapp (a param change that affects the backend imposes the restart).
3. **Force refresh** the browser on the user side.
4. Verify via the Admin page that `storage.configured` is `true` and that `storage.connection` is indeed the
   expected connection. The detailed procedure lives in
   [Installation and configuration](01-installation-and-configuration.md).

> Note: tables are created on demand on first use (`CREATE TABLE IF NOT EXISTS`, never a
> destructive ALTER). There is therefore nothing to create manually once the connection is chosen. The physical
> names follow `{PROJECT_KEY}_owismind_{logical}` (e.g. `OWISMIND_DEV_owismind_webapp_chat_v5`).

### Checklist

- [ ] Param `sql_connection` filled in (preferably `SQL_owi`)
- [ ] Connection is indeed PostgreSQL
- [ ] Restart backend done
- [ ] Browser refresh done
- [ ] Admin page: `configured == true`, `connection` correct, `project_key` as expected

---

## Runbook 3 - "agent not enabled" (HTTP 404 `agent_not_enabled`)

### Symptom

When sending a message, the backend returns **`agent_not_enabled`** (HTTP **404**). On the frontend, the agent
chosen in the picker seems valid but the run does not start. Backend log:
`/chat/start - agent_key not enabled: <key>`.

### Cause

The frontend only sends an **opaque logical key** (form `ag_<hash>`), never a raw `agent_id`. The backend
resolves it via `settings.resolve_enabled_agent(agent_key)`. If the key resolves to no
**still-enabled** agent, the route rejects with 404. Typical cases:

- The agent has been **disabled** or **moved** on the admin side -> old conversations referencing that
  key become orphaned (non-resolvable key): this is assumed.
- The frontend picker shows a **stale** list (an agent removed since the last load).
- The underlying agent no longer exists in the DSS project (renamed/deleted).

### Checks

| Order | Check | Tool |
|---|---|---|
| 1 | Is the agent still in the active whitelist? | Admin page (agent whitelist management). |
| 2 | Does the agent still exist on the DSS side? | Listing of the project's LLMs (an agent has an id prefixed `agent:`). |
| 3 | Does the key come from an old conversation? | A conversation created with a since-removed agent will carry a non-resolvable key. |

### Resolution

1. **Reload the picker**: a simple browser refresh repopulates the list from
   `GET /owismind-api/agents` (the frontend never hardcodes the list; a stale list is cause #2).
2. If the agent must remain available: **re-enable it in the Admin whitelist**. The admin POST
   **re-validates** each agent against the live DSS listing and the project against the project keys, so only an
   agent actually present can be persisted (a forged id never passes). Bound:
   `MAX_ENABLED_AGENTS = 50`.
3. If the conversation is old and points to a removed agent: there is no in-place repair
   (orphan assumed); **start a new conversation** with an enabled agent.

### Checklist

- [ ] Picker reloaded (browser refresh)
- [ ] Agent present in the Admin whitelist (otherwise re-enable)
- [ ] Agent still exists on the DSS project side
- [ ] If orphaned conversation: new conversation with a valid agent

---

## Runbook 4 - A mode does not answer (wrong LLM Mesh model id)

### Symptom

A specific mode fails systematically (typically **Eco**, which is the **default**), while the other
modes answer, or conversely. Recurring error on the run side: `agent_unavailable`, or the run stays blocked
on "Parsing the request" for that one mode only.

> IN FLUX: the `dataiku-agents/` layer is being edited live; the model ids migrated recently
> (Run 6). They are best-effort in the observed format and **must be re-verified on the instance**. An id that
> matches no model exposed by the LLM Mesh connection breaks the corresponding mode.

### Cause

Each logical mode (eco / medium / high) drives a unique **Mesh model id** for the whole turn (no
escalation). The mapping lives in the two Code Agents:

- `OWIsMind_orchestrator.py`: `LOOP_LLM_BY_MODE = {eco: GEMINI_FLASH_LITE_ID, medium: GEMINI_FLASH_ID,
  high: SONNET_ID}`, `DEFAULT_MODE = "eco"`.
- Ids observed in the code: `GEMINI_FLASH_LITE_ID = "openai:LLM-7064-revforecast:vertex_ai/gemini-3.1-flash-lite"`
  (eco), `GEMINI_FLASH_ID = "...vertex_ai/gemini-3.5-flash"` (medium),
  `SONNET_ID = "...vertex_ai/claude-sonnet-4-6"` (high).
- The sub-agent `SalesDrive_revenue_expert.py` carries the **same id triplet** (the mode propagates from
  the orchestrator to the sub-agent, so High = Sonnet everywhere). The Semantic Model Query tool
  (`v4oqA6R`) stays on Sonnet in **all** modes.

If one of these ids matches no id exposed by the instance's Mesh connection, **that mode** fails.
Since `DEFAULT_MODE = "eco"`, a wrong `GEMINI_FLASH_LITE_ID` makes the default mode fail, hence almost
all requests.

### Checks

| Order | Check | Interpretation |
|---|---|---|
| 1 | Which modes fail, which work? | Eco only -> suspect `GEMINI_FLASH_LITE_ID`; Medium -> `GEMINI_FLASH_ID`; High -> `SONNET_ID`. |
| 2 | Does the id of the failing mode exist in the Mesh connection? | Compare the exact id string (in both files) to what the LLM Mesh connection exposes on the DSS side. |
| 3 | Do the two Code Agents carry the SAME id? | A divergence between orchestrator/sub-agent can break the mode propagation. |
| 4 | Have the agents been re-pasted after the last repo edit? | A non-re-pasted repo edit = old id still in production. |

### Resolution

1. Fix the offending id in **both files** (`OWIsMind_orchestrator.py` and
   `SalesDrive_revenue_expert.py`) so that it matches **exactly** an id exposed by the Mesh connection.
2. **Re-paste the two Code Agents** on the Python env 3.11 (always both together: some fixes
   live on both sides). No zip action is required for an agent-only change.
3. Re-test the offending mode with a simple question. If the default (Eco) was broken, verify that the
   answers come back in Eco.

The complete re-paste and id verification procedure is in
[Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md).

### Checklist

- [ ] Failing mode(s) identified -> suspected id
- [ ] Exact id compared to the Mesh connection (verbatim string)
- [ ] Id fixed in BOTH agent files
- [ ] BOTH Code Agents re-pasted (env 3.11)
- [ ] Mode re-tested (including Eco if it was the default)

---

## Runbook 5 - Slow answers in High

### Symptom

In **High** mode, the answer takes noticeably longer to arrive than in Eco or Medium. The user
sees the timeline advance then a long wait before `final_answer`.

### Cause (this is NOT necessarily a failure)

High drives **Claude Sonnet 4.6** end to end (orchestrator AND sub-agent loop), and the Semantic
Model Query tool is on Sonnet in all modes anyway. Sonnet reasons longer. Moreover,
the polling transport does not do word-by-word typing: the prose often arrives in one block at the end, which
amplifies the perceived wait. Finally, **stop** and deadlines are evaluated **between two chunks**
(the official LLM Mesh stream exposes no cancel API): during a blocking LLM call, the Stop button
may seem to do nothing for a few seconds.

### Checks

| Order | Check | Interpretation |
|---|---|---|
| 1 | Is the mode High? | Higher latency = expected, not a bug. |
| 2 | Does the timeline advance (steps scrolling)? | If so, the run progresses normally, just slowly. |
| 3 | Does the latency exceed ~5 min? | `MAX_RUN_SECONDS = 300 s` cuts the run off (event `run_timeout`). Beyond that, it is a cutoff, not slowness. |
| 4 | Are all modes slow, or only High? | If Eco/Medium are also slow, suspect the Mesh connection or instance load rather than the model. |

### Resolution

1. **Explain**: High is deliberately slower (Sonnet) but more precise. For a fast answer,
   advise **Eco** (Gemini 3.1 Flash-Lite, the default) or **Medium** (Gemini 3.5 Flash).
2. If the wait is unacceptable, the user can **Stop** (the backend persists the accumulated partial
   answer and emits a discreet "generation stopped" marker; the stop acts between two chunks, hence with
   a small delay).
3. If **all** requests are slow (not only High): this is no longer a model problem.
   Check the instance load and the health of the LLM Mesh connection, and the concurrency cap
   (`MAX_CONCURRENT_RUNS = 8`; beyond it new starts return `busy`).

### Checklist

- [ ] Mode confirmed (High)
- [ ] Timeline progressing (run alive)
- [ ] Latency under 5 min (otherwise: deadline cutoff, not slowness)
- [ ] Advise Eco/Medium if speed is the priority
- [ ] If all modes slow: check instance load + Mesh

---

## Runbook 6 - Empty chart in Evidence

### Symptom

The **Chart** (or **Table**) tab of the Evidence panel is empty even though the text answer does cite
figures, or the chart displays without data.

### Mental model (separate SPEC and DATA)

An **artifact** (`show_chart` / `show_table` / `show_kpi`) carries only the **display spec**
(`{kind, title, chart|kpi}`), NEVER the data rows. The displayed data is the **captured `result`**
of the `generated_sql` already in the database. The Chart.js payload is built on the backend side
(`evidence/chart_payload.py`) from this `result`. So: no captured `result` = empty chart,
even if an artifact spec exists.

### Possible causes

- **Missing `result` capture**: the key of the tool span rows is not confirmed on the instance;
  `capture.extract_result` is **best-effort**. If nothing recognizable is found, the `result` is
  simply absent (`result_captured` false). The live polled copy removes `result` anyway; it
  is only read in persistence via `/evidence/meta`.
- **Multi-SQL**: when there are several queries, the result is attached to the **last** SQL span, and
  Evidence prefers the last successful item WITH a result. An intermediate query without a result does not feed
  the chart (expected behavior).
- **Renamed tool span**: trace extraction relies on the frozen span `semantic-model-query`
  (`_SQL_TOOL_NAME`). A rename on the agents side would break the capture.

### Checks

| Order | Check | Interpretation |
|---|---|---|
| 1 | Does the answer actually cite figures? | If the sub-agent produced no SQL/result, there is nothing to plot (legitimate `no_data` case). |
| 2 | Is the Table tab empty too? | Table AND Chart empty -> no `result` captured at all. |
| 3 | Reproducible on other questions? | If EVERY chart is empty -> broken capture (renamed span?) rather than an isolated case. |
| 4 | Have the agents been edited recently? | A rename of the `semantic-model-query` span breaks the extraction. |

### Resolution

1. If it is **isolated** to one question (the sub-agent did not capture rows for that query): this is
   a known best-effort limitation, not a failure. The text answer remains valid; the absence of a chart
   simply signals `result_captured` false for that run.
2. If **every** chart is empty since an agents edit: verify that the tool span is still called
   `semantic-model-query` on the agents side and that the Semantic Model tool `v4oqA6R` is properly wired. Re-paste the
   two Code Agents after correction.
3. Verify that the backend has indeed been **restarted** if `python-lib/owismind/evidence/` changed (the
   chart payload build lives on the backend side).

The artifact pipeline and the capture are detailed in
[Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md).

### Checklist

- [ ] Answer does contain figures (otherwise: legitimate `no_data`)
- [ ] Table verified (also empty = no `result`)
- [ ] Isolated or systematic determined
- [ ] If systematic: span `semantic-model-query` + tool `v4oqA6R` verified, agents re-pasted
- [ ] Restart backend if `evidence/` changed

---

## Runbook 7 - Non-clickable Evidence source (`source_url` empty)

### Symptom

In the Evidence panel, the **Sources** section shows the dataset but **without a clickable link**
to Dataiku. The expected link title is `ev.proof.sources.open` ("Open the dataset in
Dataiku" / "Open the dataset in Dataiku").

### Cause

The link is only rendered if a **source URL** travels all the way to the backend. This URL is configured on the
**orchestrator** side, not the backend side: in the `CAPABILITIES` registry of `OWIsMind_orchestrator.py`, the
capability `revenue_expert` carries a **`source_url`** field whose default value is an **empty
string** (`"source_url": ""`). As long as it is empty, the orchestrator stamps no URL on the SQL items,
the backend therefore surfaces no `meta.source.url`, and the `EvidenceSources.vue` component (gated on
`meta.source`) does not render an `<a>`.

Architecture reminder: the orchestrator (Code Agent 3.11) and the backend (`/evidence/meta`) are **two
separate processes**. The URL must therefore **travel** from the orchestrator registry through the SQL items (in an
additive way over the frozen capture pipeline: `source_url` is one of the optional trust-layer keys
relayed, cf. `streaming.py` and `evidence/capture.py`), then `service.py` projects it into
`meta.source.url`.

### Checks

| Order | Check | Interpretation |
|---|---|---|
| 1 | Is `source_url` empty in the orchestrator registry? | `CAPABILITIES[...]["source_url"] == ""` -> no clickable source (nominal "not filled in" case). |
| 2 | Has the orchestrator been re-pasted after filling it in? | A non-re-pasted repo edit = old value (empty) still in production. |
| 3 | Does the link remain absent even after filling in + re-paste? | Suspect the propagation: verify that the SQL items do carry `source_url`. |

### Resolution

1. **Fill in `source_url`** on the `revenue_expert` capability in `OWIsMind_orchestrator.py` with
   the Dataiku URL of the dataset (the link to open on click). It is an **optional** step of the
   deployment: without it, everything works, only the link is missing.
2. **Re-paste the orchestrator Code Agent** (and, by rule, both together) on env 3.11.
3. Re-test a revenue question: the Sources section must show an `<a target="_blank">` link (title
   `ev.proof.sources.open`).

> Known limitation (assumed): the URL mapping is currently **single-source** (a single URL per run).
> A per-dataset multi-source mapping is deferred.

### Checklist

- [ ] `source_url` filled in on `revenue_expert` (orchestrator registry)
- [ ] URL = Dataiku link of the intended dataset
- [ ] Orchestrator (and the other agent) re-pasted on 3.11
- [ ] Revenue question re-tested: link present in Sources
- [ ] Multi-source case: accept the current single-source limitation

---

## Runbook 8 - User blocked by monthly budget (HTTP 402 `monthly_quota_exceeded`)

### Symptom

A user can no longer send messages. The chat shows a banner indicating the monthly budget is exhausted.
The backend returns **HTTP 402** (`monthly_quota_exceeded`) with a `budget` object containing `spent_usd`,
`limit_usd`, and `remaining_usd`. The user can still read past conversations and open Evidence panels.

### Cause

The user's accumulated LLM-Mesh `estimatedCost` for the current calendar month has reached (or exceeded)
their effective monthly limit. The effective limit is resolved in this order:
1. An active per-user override in `webapp_user_quota_v1` (wins over everything while active).
2. An active global temporary boost in `webapp_settings_v1` (key `monthly_budget`, field `temp_limit_usd`).
3. The global default limit (default: **$50 USD**, constant `DEFAULT_MONTHLY_LIMIT_USD` in `storage/budget.py`).

Budget enforcement is enabled when the global config has `enabled: true`. The gate **fails open**: if the
budget DB read throws, the run is allowed and the spend is still recorded (the next request is then gated
once the read recovers).

### Checks

| Order | Check | Tool |
|---|---|---|
| 1 | Is budget enforcement enabled? | Admin page > Quotas tab: `config.enabled` field. |
| 2 | Does the user have a per-user override that is still active? | Admin page > Quotas tab: per-user table, `limit_usd` column for that user. |
| 3 | Is the global default limit appropriate? | Admin page > Quotas tab: `config.limit_usd`. |
| 4 | Is the monthly reset not yet due? | Budget resets on the 1st of each calendar month (new DB bucket row, no manual reset). |

### Resolution

Choose the appropriate action from the admin Quotas tab:

- **Permanent per-user boost**: POST `/admin/budget/users` with `{user_ids:[<id>], limit_usd: <new>, expires_days: null}`.
  This creates (or replaces) a permanent per-user override for that user.
- **Temporary per-user boost**: same call with a non-null `expires_days` (e.g. 7 for one week).
- **Global temporary boost**: POST `/admin/budget` with `{temp_limit_usd: <boost>, temp_days: <n>}`. Applies
  to all users WITHOUT a per-user override until expiry.
- **Raise the global default**: POST `/admin/budget` with `{limit_usd: <new>, enabled: true}`. Affects all
  users with no override immediately (a new DB bucket row is never needed; the math is always
  `limit - spent`).
- **Disable enforcement**: POST `/admin/budget` with `{enabled: false}`. Runs are allowed regardless of spend
  (spend is still recorded for reporting).

After the change, the frontend's next `/usage` poll refreshes the budget status and unblocks the send button
automatically.

> The user's own status is always available at `GET /usage` (authenticated, owner-scoped). The backend log
> line to grep: `/chat/start - monthly quota exceeded user_id=<id> spent=... limit=...`.

### Checklist

- [ ] Symptom confirmed (HTTP 402, `monthly_quota_exceeded` in the browser console)
- [ ] Budget enforcement status checked (enabled vs disabled)
- [ ] Effective limit for that user identified (per-user override, temp boost, or global default)
- [ ] Appropriate override applied (per-user, global boost, or default raise)
- [ ] User confirmed unblocked (frontend budget banner dismissed)

---

## Runbook 9 - Agent library card shows "profile to complete"

### Symptom

In the **Agents** section of the app, an agent's library card shows a "profile to complete" placeholder
instead of a tagline, description, capabilities and tools. This is a deliberate design: there is no
hardcoded fallback description. The agent is functional (conversations work), but the library presentation
is empty.

### Cause

Agent descriptions are authored by an admin via the **Administration > Agents > Edit profile** form and
stored as a `profile` object inside the `enabled_agents` JSON in `webapp_settings_v1`. Until an admin fills
in the profile, the `profile` dict is empty or absent, and the `/agents` route returns empty strings for
`tagline`, `description`, `capabilities`, `tools`, etc. The frontend renders the placeholder in that case.

This is not a code bug: it is the intended post-deploy state on a fresh install. The old `agentMeta.js`
(hardcoded descriptions) was intentionally removed.

### Checks

| Order | Check | Interpretation |
|---|---|---|
| 1 | Is the agent present in the whitelist? | If not enabled, it is not visible at all (see Runbook 3). |
| 2 | Has an admin opened Edit profile and saved? | No profile saved -> placeholder (expected). |
| 3 | Is the icon value valid? | `validate_agent_meta` in `security/validation.py` sanitizes the icon against a whitelist; an unrecognized icon silently falls back to `"robot"`. |

### Resolution

1. Open the app as an admin, navigate to **Administration > Agents**.
2. Click **Edit profile** on the agent that shows the placeholder.
3. Fill in all fields: **tagline** (one line, short), **description** (richer text, visible in the library
   card and the agent detail sheet), **capabilities** (list of capability bullet points), **tools** (list
   of tool names), **icon** (name from the frontend icon registry, e.g. `robot`, `chart-bar`), **badge**
   (optional label such as "Beta" or "Revenue").
4. Save. The change is validated server-side by `validate_agent_meta` (pure, never raises, icon
   sanitized), stored in `webapp_settings_v1`, and the `/agents` route immediately returns the filled
   profile on the next frontend poll.

> There is nothing to restart: the profile is read from the DB on every `/agents` call. The change is
> effective immediately after saving.

### Checklist

- [ ] Agent confirmed enabled in the whitelist (otherwise: Runbook 3)
- [ ] Admin opened Administration > Agents and located the agent
- [ ] Edit profile form filled (tagline, description, capabilities, tools, icon, badge)
- [ ] Saved successfully
- [ ] Agent library card reloaded and placeholder replaced by the authored content

---

## See also

- [Monitoring and logs](03-monitoring-and-logs.md) - where to read `storage_status`, the content-free WARNINGs and Evidence observability before intervening.
- [Installation and configuration](01-installation-and-configuration.md) - choose the `SQL_owi` connection and the webapp params (resolves `storage_not_configured`); section 7 for budget, section 8 for agent profiles.
- [Build, packaging and deployment](02-build-package-deploy.md) - the what-to-rebuild-when matrix and the Restart backend procedure.
- [Backend - streaming and run lifecycle](../04-backend/03-streaming-and-runs.md) - polling, deadlines, cooperative stop, error codes (Runbooks 1 and 5).
- [Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md) - `result` capture, chart payload, source_url (Runbooks 6 and 7).
- [Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md) - re-paste the two Code Agents and verify the LLM Mesh ids (Runbooks 4 and 7).
