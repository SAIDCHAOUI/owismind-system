# ADR-0008 - Evidence trust layer and artifacts (signal vs data)

> Audience: Developer. Last updated: 2026-06-18. Summary: why Evidence Studio
> re-derives the evidence behind a figure WITHOUT ever putting an LLM in the path, and why an artifact
> (the display SPEC requested by the agent) NEVER carries the data rows, which remain those already
> captured from the SQL result.

## Status

Accepted and validated in DSS (Evidence v1 and the artifacts layer were validated on the instance, with
user feedback "comme sur des roulettes" / "suuuper ca marche tres bien"). Capture of the exact `result`
remains best-effort: see the IN FLUX note further down.

## Context and problem

OWIsMind targets non-technical sales people. When the agent returns a figure (a revenue, a budget), the
user needs to be able to trust it: where the data comes from, which scope and which exact filters were
applied, HOW the number was computed (in business language, not in SQL), which EXACT result was used, an
HONEST verification level, and a drill-down when it is provably reliable. These requirements are frozen
in the spec `docs/superpowers/specs/2026-06-10-evidence-trust-layer-design.md` (§0).

Two pitfalls threatened this trust:

1. Putting an LLM in the evidence path. If a "verification" layer asked a model to explain or score the
   figure, the evidence would itself become a generation, and therefore fallible: false evidence is worse
   than no evidence.
2. Confusing the SIGNAL and the DATA. When the orchestrator asks "display this result as a chart", you
   have to decide who carries the data rows: the agent (risk of error, of divergence from what it
   actually read) or the code (the rows already captured).

## Decision

### 1. Evidence is re-derived, deterministic, zero LLM

Evidence Studio stores no new schema for the evidence: everything is RE-DERIVED per call from the
`generated_sql` already persisted in the chat row (`webapp_chat_v5`). The service
`evidence/service.py` is a stateless pipeline (docstring "everything re-derived per call, nothing new
is stored"): it loads the stored SQL item (owner-scoped on `user_id`), takes the LAST successful item
(the agent's final refined query), parses it into table + predicates + fragment via the PURE parser
`evidence/sql_parse.py`, matches the table against the project's auto-discovered PostgreSQL datasets,
reads the schema (metadata only, TTL-cache), and rebuilds a BOUNDED read-only SELECT from STRUCTURED
filters. The client never sends any SQL; the locked chips travel as ids and are re-derived server-side.

The business explanation comes from a PURE explainer (`evidence/sql_explain.py`, "NO dataiku import",
"NEVER RAISES") that turns ONE SELECT into renderable steps (frozen kinds: `source`, `join`,
`filter_eq`, `agg_sum`, `group`, `topn`, `calc_ratio`, etc.). Its golden rule: anything not positively
understood DEGRADES a flag or produces an `opaque` step, never a guess. A wrong explanation would be
false evidence; an under-stated explanation is simply less useful.

No LLM intervenes in this path (service.py: "No LLM is ever involved in this proof path ;
every block is computed by pure, unit-tested functions").

### 2. A DETERMINISTIC trust badge, never green

The verification level is a deterministic scale computed by `verification_level()` (pure) in
`evidence/service.py`. It rises only when static analysis of the SQL proves it, never because
"the SQL ran". The levels:

| Level | When it is assigned |
|---|---|
| `declared` | parse fails or no dataset matches (degraded panel). |
| `source_identified` | table matched but the WHERE could not be evaluated, or nothing mapped without completeness. |
| `scope_partial` | matched + at least one predicate mapped, completeness broken. |
| `scope_exact` | complete WHERE + single source + no set-operation. |
| `calc_decomposed` | `scope_exact` + the SELECT calculation fully understood (group/order/having resolved, complete CTE DAG). |

`result_captured` is ORTHOGONAL: it only says whether captured rows exist for the active item,
not whether the calculation is understood. On the frontend side, `trustLevel()`
(`frontend/src/composables/evidenceProof.js`) maps this verdict to a badge without ever upgrading it:
any unexpected shape (missing `verification` block, unknown level) falls back to the honest floor
`declared`. The badge is NEVER green: its tone goes from solid (strong evidence) to dotted then to grey,
so as not to suggest a certainty the code cannot guarantee.

### 3. Signal vs data separation for artifacts

An artifact is a display SPEC requested by the orchestrator via its tools `show_chart`,
`show_table`, `show_kpi`. The contract is strict: an artifact carries `{kind, title, chart|kpi}` and
NEVER carries the data rows.

On the agent side, the schema of the `show_chart` tool (in `OWIsMind_orchestrator.py`,
`build_tool_specs`) only requests `chart_type` (line / bar / pie), `x`, `y` (column NAMES) and
an optional `style`: "x and y MUST" refer to the columns of the last result. The agent therefore chooses
HOW to plot, not WHAT to plot. The emitted `ARTIFACT` event carries only this spec
(`{kind, title, chart, kpi}`).

On the backend side, `chart_payload.build_chart_payload(result, chart_spec)`
(`evidence/chart_payload.py`) rebuilds the Chart.js payload from the ALREADY CAPTURED RESULT
(`result` = the `result` block of `/evidence/meta`, hence `generated_sql[].result`) and the spec. The
docstring states it explicitly: "Doing the shaping HERE (server-side Python) is the whole point of
'the agent only says x/y'": column resolution, numeric parsing, sort/cap and pie percentages are done
on trusted code, so a mistyped column or a non-numeric cell degrades to an honest empty state rather
than to a false chart. The data remains the data the agent actually read; the agent only provides x / y
/ type / style. Result: zero risk of data error.

The complete pipeline (event `ARTIFACT` -> normalization -> `webapp_artifacts_v1` -> `/evidence/meta`
-> Evidence / Chart / Table tabs) has its canonical home elsewhere: see
[Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md). This diagram is
not redrawn here.

## Why the data is never handed back to the agent

Interactive rendering necessarily means JS (pure Python only outputs a frozen image). The structuring
choice is therefore: Python builds the HARDENED payload, Chart.js renders. If the agent returned the
rows, two sources of truth would coexist (what the agent read vs what the database contains), and the
slightest divergence would produce a chart that lies. By binding the payload to the single captured
`result`, the chart is by construction consistent with the evidence shown in the Evidence tab.

## Bounds and safety (mirror caps)

Capture and persistence are bounded at the point of writing, never trusting an upstream cap. In
`evidence/capture.py` (PURE module, "no dataiku / pandas import", testable outside DSS):

| Cap | Value | Role |
|---|---|---|
| `MAX_RESULT_ROWS` | 200 | the captured table is an evidence EXTRACT, not an export. |
| `MAX_RESULT_COLS` | 50 | columns per result. |
| `MAX_CELL_CHARS` | 256 | any non-primitive cell is stringified and cut. |
| `MAX_RESULT_JSON_CHARS` | 100 000 | serialized size of ONE result; beyond it the trailing rows are dropped. |
| `MAX_SQL_ITEMS` | 20 | number of persisted `generated_sql` items (newest-wins). |
| `MAX_PERSISTED_TEXT_CHARS` | 262 144 | global serialized budget of the SQL list. |
| `MAX_ITEM_SQL_CHARS` | 20 000 | structural bound on an item's SQL text. |

`cap_sql_list()` NEVER fails (persistence must not break because of a capture) and preserves
the result of the LAST successful item as long as possible (this is the shown evidence): it drops the
`result` of the oldest items first. The caps are STRUCTURAL (rows dropped, `truncated` flag flipped),
never a text marker in the JSON, which would corrupt decoding. `extract_result()` is opportunistic:
any output shape not positively recognized returns `None`, which honestly surfaces
`result_captured: false` instead of inventing data.

On the service side, the endpoint that replays SQL does so on the connection of the matched dataset
(`SQLExecutor2(dataset=...)`), forced read-only (`SET LOCAL transaction_read_only`,
`statement_timeout`, `LIMIT` everywhere, never an unbounded `COUNT(*)`), with a TTL cache outside the
lock and a per-user token-bucket. A 6-lens audit confirmed zero injection / IDOR / XSS: the real risks
of such an endpoint are DoS and performance, handled by the bounds above. The drill-down is
RE-VALIDATED server-side (the drill columns are re-derived from the stored SQL, the client list is never
trusted).

> IN FLUX: the exact key of the rows in the tool span is NOT confirmed on the instance. Capture of the
> `result` is therefore best-effort (`_ROW_KEYS` probes several candidate keys) and may be absent ->
> the panel then shows `result_captured: false` without ever guessing. The verification level remains
> valid independently (it only depends on the static analysis of the stored SQL).

## Consequences

Positive:

- The evidence can never over-assert: every degradation path pulls the level DOWN, never up. A schema
  drift only lowers the badge.
- No duplication of sensitive data in a dedicated chat schema: everything lives in the `generated_sql`
  already stored.
- The chart is by construction aligned with the evidence (same captured `result`).
- PURE proof modules, unit-testable without a DSS runtime (caps and levels verified outside the instance).

Negative / accepted trade-offs:

- Without an admin whitelist (the MULTISELECT param type does not render in the DSS Settings), any SQL
  dataset of the project whose table an agent puts in its SELECT is visible as raw rows for ITS own
  conversation (read-only, bounded on 4 axes). Accepted trade-off.
- The RAW end-of-stream trace is stored (`webapp_chat_traces_v1`), an accepted divergence from the
  framing, aligned with the client's production Dash.

## Rejected alternatives

- MULTISELECT admin whitelist to restrict the visible datasets: dropped because the param type does not
  render in the DSS Settings; replaced by auto-discovery of the project's PostgreSQL datasets.
- Persisting the captured rows in a new dedicated schema: avoided (duplication of sensitive data);
  everything stays re-derived from the `generated_sql`.
- Hand-made SVG chart rendering on the Python side: a bundled Chart.js was preferred (interactive vs
  frozen image).
- LLM in the evidence path: forbidden by the spec (§0); the whole layer is deterministic.

## See also

- [Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md) - the canonical
  home of the artifact pipeline and the evidence sequence (capture, sql_parse/explain, levels,
  chart_payload).
- [Understanding results (Evidence Studio)](../01-user-guide/03-understanding-evidence.md) - the same
  notion seen on the user side (badge, chips, drill, chart).
- [The orchestrator (`OWIsMind_orchestrator`)](../05-agents/02-orchestrator.md) - the tools
  `show_chart` / `show_table` / `show_kpi` that emit the artifacts.
- [ADR-0011 - Assistive sub-agent](0011-sous-agent-assistif.md) - another application of the principle
  "the code does not dictate, it provides a verifiable framework".
- [Architecture decisions (ADR index)](README.md) - back to the index.
