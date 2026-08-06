---
name: captured-result-shape-contract
description: The captured SQL `result` dict has keys columns/rows/truncated only - `captured` exists ONLY on the /evidence/meta response block; confusing the two silently kills artifact rendering
metadata:
  type: project
---

Two DIFFERENT dicts in OWIsMind are both called "result", and mixing them is a silent killer.

**Stored / streamed capture** (inside a `generated_sql` event and inside the persisted
`generated_sql` item): produced by `evidence/capture.extract_result(outputs)` and it returns
EXACTLY `{"columns", "rows", "truncated"}`. There is NO `captured` key and NO `row_count` key.

**API response block** (`/evidence/meta` -> `result`): built by `evidence/service._result_block`
and that one DOES carry `{"captured": True/False, "columns", "rows", "row_count", "truncated"}`.
`evidence/chart_payload.build_chart_payload` consumes THAT shape (it checks `result["captured"]`).

The canonical predicate for "does this item carry a capture" is
`evidence/service.has_captured_result(item)` = result is a dict with list `columns` and list `rows`
(same test inlined in `agents/context.extract_prior_results`). Any new code that gates on
`result.get("captured")` for a streamed/stored result is dead code that always evaluates False.

Found 2026-08-06 in the chantier B native engine (`agents/native_orchestrator.py`): the capture
gate used `result.get("captured")`, so `latest_result` never got set and every
show_chart/show_table/show_kpi was refused with "No captured specialist result to render yet".
Unit tests missed it because the fixture fabricated `RESULT = {"captured": True, ...}`.

**How to verify:** drive the REAL `streaming.run_agent_streamed` with a fake completion whose
footer trace holds a `semantic-model-query` span with `outputs = {sql, success, row_count,
columns, rows}` (that is exactly what SalesDrive_revenue_expert writes, see its
`qsp.outputs[...]` lines) and print `sorted(event["result"].keys())`. Same probe proves that a
sub-agent stream carries NO `sqlId` either (sql_id tagging is done by the orchestrator Code
Agent, not by streaming's trace walker), so anything relying on `latest_sql_id` from a direct
sub-agent run gets None.

See also [[repo-review-pitfalls]], [[security-invariants]].
