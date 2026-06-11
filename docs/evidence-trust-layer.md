# Evidence Studio v2 — Trust layer

> Technical reference for the Evidence Studio trust layer (2026-06-10 Run 5).
> Frozen contracts: `docs/superpowers/specs/2026-06-10-evidence-trust-layer-design.md`.
> Orchestrator audit: `orchestrator/AUDIT.md`. API details: `docs/backend-api.md`.

## 1. What it is

Evidence Studio is the right-hand "proof" panel of the OWIsMind webapp. The trust
layer turns it from a SQL-scope viewer into a generic, deterministic explanation of
**how an agent answer was produced**, aimed at non-technical sales users:

| Panel section | Source of truth |
|---|---|
| (a) Trust badge (verification level) | deterministic checks, backend-computed |
| (b) Business sources | matched project dataset (auto-discovery) |
| (c) Scope & filters (editable chips) | parsed WHERE predicates (v1, unchanged) |
| (d) "How this number was computed" | `sql_explain` structured steps, i18n-rendered |
| (e) Exact result the agent used | rows captured from the tool trace (when present) |
| (f) Source-data exploration (paginated table) | bounded read-only re-query (v1, unchanged) |
| (g) Technical details (SQL) | raw stored SQL, collapsed footer (v1, unchanged) |

Nothing in the proof path calls an LLM. Every claim maps to a mechanical check.

## 2. Proof lifecycle

1. **Run** — the orchestrator (Code Agent, `orchestrator/orchestrator_agent.py` v2.2)
   executes the plan; each sub-agent's `semantic-model-query` tool span carries
   `outputs.{sql, success, row_count}` (+ possibly the result rows — instance-dependent).
   The orchestrator tags every SQL item with `sql_id` (`s{step}q{n}`), `step_index`,
   `agent_key`, and opportunistically captures a capped result excerpt. Items travel in
   `AGENT_DONE.eventData.generatedSql` AND in the merged footer trace.
2. **Capture** — `agents/streaming.py` merges both channels (trace = authority,
   AGENT_DONE = correlation + early emission so a user-stopped run keeps its SQL).
   `evidence/capture.py` re-caps everything at the write point (never trusts upstream):
   ≤ 200 rows × 50 columns, cells ≤ 256 chars, result ≤ 100 kB, list ≤ 20 items,
   global JSON ≤ 262 144 chars (results shed oldest-first, the last successful item's
   result preserved longest).
3. **Persist** — `storage/chat_v4.save_assistant_message` stores the capped JSON in the
   existing `generated_sql` TEXT column (**no migration**). `/conversation` readback
   strips `result` (thread payload stays light); only `/evidence/meta` returns it.
4. **Prove** — `GET /evidence/meta?exchange_id=` (owner-scoped, throttled, no source SQL
   executed) re-derives everything from the stored SQL: parse (`sql_parse`), dataset
   match (project auto-discovery), explanation (`sql_explain`), verification level,
   captured result, drill-down availability.
5. **Explore / drill** — `POST /evidence/rows` re-queries the matched dataset read-only
   (`SET LOCAL statement_timeout 30s` + `SET LOCAL transaction_read_only`), bounded
   pages; the optional `drill` payload filters to one result group's contributing rows
   after server-side re-validation against the stored SQL's group keys.

## 3. Verification levels (deterministic ladder)

Computed by `evidence/service.py::verification_level` (pure, unit-tested) from the
parse, the dataset match, the explainer flags and the REAL predicate drops:

| Level | Mechanical criterion |
|---|---|
| `declared` | parse failed or no project dataset matched — agent claim only |
| `source_identified` | dataset matched, WHERE not assessable |
| `scope_partial` | matched, ≥1 predicate mapped, completeness broken (drops listed) |
| `scope_exact` | every WHERE conjunct decomposed + single source + no set-op |
| `calc_decomposed` | scope_exact + SELECT computation fully understood (no opaque item) |

`result_captured` is orthogonal (stored rows present). The UI badge maps level ×
captured; dropped/unmapped elements are **listed, never hidden**. A missing or failing
explainer can only LOWER the level (defensive `normalize_explain` adapter).

## 4. Drill-down rules

Offered only when provably exact: single matched source (self-join excluded), complete
WHERE, no set-op / recursive CTE, GROUP BY keys with identity lineage to live schema
columns. The frontend sends `drill: [{column, value}]` (≤ 8) built from the captured
result row; the server re-derives the group keys from the STORED SQL and rejects
anything else (`invalid_drill`, 400). Window/rank/cumulative values are explained but
never claimed re-verifiable. Refusal reasons: `no_group_keys`, `multi_source`,
`incomplete_where`, `set_op`, `not_supported`.

## 5. Adding a new SQL sub-agent / dataset / dialect feature

- **New sub-agent**: add one `CAPABILITIES` entry in the orchestrator (agent_id, labels,
  planner_description, block/tool labels, `dataset_label_fr/en`, `dataset_ref`) and
  enable the agent in the webapp admin whitelist. Nothing else: capture, proof,
  explanation and drill are generic (they key on the stored SQL + project datasets).
- **New dataset**: nothing to do — project PostgreSQL datasets are auto-discovered
  (`service._list_project_sql_datasets`, TTL 300 s).
- **New SQL construct**: extend `evidence/sql_explain.py` (new step kind → add it to the
  frozen enum in the spec, the backend classifier, and `ev.exp.*` keys in
  `frontend/src/i18n/extra.js` fr+en). Unknown constructs already degrade honestly
  (`opaque` step, `select_understood=false`).
- **New result shape from a tool**: extend the candidate keys in
  `evidence/capture.py::extract_result` (and the orchestrator mirror).

## 6. Known limits (honest by design)

- The exact rows key in the tool span `outputs` is **not confirmed on this instance**:
  until verified on a real stored trace (the Flow traces dataset has the raw footer),
  captures may be absent → `result_captured: false`, panel stays useful.
- UNION/INTERSECT/EXCEPT: only the first arm is analysed (the union step says so).
- Aggregations over joins (incl. self-joins): explained, never drillable.
- Window values (rank, running totals, cumulative shares): explained, not re-verifiable.
- Re-executions show *today's* data; only captured rows are "what the agent used".
- Historical exchanges (pre-v2) have no tags/result → proof degrades gracefully.

## 7. Running the tests

```bash
# Backend (pure modules, no DSS needed) — from the repo root
python3 -m unittest discover -s Plugin/owismind/tests -v
# Orchestrator (dataiku stubbed)
python3 -m unittest discover -s orchestrator/tests -v
# Frontend pure logic
cd Plugin/owismind/frontend && npm test
# Compile checks
python3 -m compileall -q Plugin/owismind/python-lib
cd Plugin/owismind/frontend && ./node_modules/.bin/vite build --outDir /tmp/owi_bc --emptyOutDir && rm -rf /tmp/owi_bc
```
