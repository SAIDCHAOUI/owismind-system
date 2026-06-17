# Evidence Studio v2 - « Trust layer » design (FROZEN CONTRACT)

> 2026-06-10 Run 5. This document freezes the cross-workstream contracts for the Evidence
> Studio trust layer. Implementers MUST NOT change field names/shapes without updating this doc.
> Sources: 4-specialist exploration workflow (orchestrator audit, SQL lineage design,
> backend audit, frontend UX design) - reports in session transcript.

## 0. Goal

Evidence Studio becomes a generic trust layer for non-technical sales users:
where the data comes from, the exact scope/filters, HOW the number was computed
(business language, no SQL jargon), the exact result the agent used (when captured),
an HONEST deterministic verification level, and a drill-down to contributing source
rows when (and only when) it is provably reliable. Raw SQL stays in a collapsed
technical section. Generic for any SQL sub-agent (not DRIVE_Revenues-specific).

Non-negotiables: no new dependency (pure Python 3.9 / existing Vue deps), no LLM in
the proof path, no migration (JSON enrichment of `chat_v4.generated_sql` TEXT),
read-only + bounded + owner-scoped + throttled as today, the frontend NEVER sends
SQL/table/connection names.

## 1. Stored data model (chat_v4.generated_sql - JSON TEXT, NO migration)

Each item (old items stay valid; all new keys optional):

```json
{"sql": "...", "success": true, "row_count": 12,
 "sql_id": "s1q1", "step_index": 1, "agent_key": "salesdrive",
 "result": {"columns": ["customer", "total"],
            "rows": [["Algerie Telecom", 1234.5]],
            "truncated": false}}
```

Caps (pure module `evidence/capture.py`, mirrored independently in the orchestrator):
- `MAX_RESULT_ROWS = 200`, `MAX_RESULT_COLS = 50`, cell → str()[:256] for non-primitives
  (keep int/float/bool/None as-is; floats must be finite), result JSON ≤ 100_000 chars
  (else truncate rows, `truncated: true`).
- Global budget for the serialized sql_list ≤ 262_144 chars (MAX_PERSISTED_TEXT_CHARS):
  drop `result` from oldest items first, ALWAYS preserving the LAST successful item's
  result; never drop sql/success/row_count. `MAX_SQL_ITEMS = 20` (oldest dropped beyond).
- NEVER use chat_v4._bounded() on JSON (text marker corrupts it). The cap helper is pure
  (no dataiku import) and unit-tested.

Opportunistic result extraction from the semantic-model-query tool span `outputs`
(the exact key is NOT confirmed on this instance - extraction is best-effort):
candidate row keys in order: `rows`, `records`, `data`, `result_rows`, `values`;
accepted shapes: list-of-lists (+ separate `columns`/`column_names`/`headers` key) or
list-of-dicts (columns = first dict's keys, stable order). Anything else → no capture
(`result` absent). Absence is honest: `result_captured: false` downstream.

Readback projection: `/conversation` (chat_v4.messages_for_session) must STRIP `result`
from generated_sql items (keep sql/success/row_count/sql_id/step_index/agent_key) so the
thread payload stays light. Only `/evidence/meta` returns the captured result.

## 2. /evidence/meta - enriched contract (additive, all new fields optional)

`available: true` response (v1 fields unchanged: dataset, columns, chips, advanced, sql):

```json
{
  "status": "ok", "available": true,
  "dataset": "DRIVE_Revenues", "columns": [...], "chips": [...],
  "advanced": {"present": false, "display": null}, "sql": "...",

  "source": {"dataset": "DRIVE_Revenues", "schema": "public", "table": "..."},
  "queries": [{"index": 1, "success": true, "row_count": 12, "matched": true,
               "step_index": 1, "agent_key": "salesdrive", "result_captured": true}],
  "verification": {"level": "calc_decomposed", "result_captured": true,
                   "dropped_predicates": 0, "dropped_display": [],
                   "single_source": true, "where_complete": true,
                   "select_understood": true},
  "explanation": {"ok": true, "steps": [{"kind": "filter_eq", "params": ["phase", "ACTUALS"]}]},
  "result": {"captured": true, "columns": [...], "rows": [[...]],
             "row_count": 12, "truncated": false},
  "drilldown": {"available": true, "columns": ["customer"], "reason": null}
}
```

Degraded response gains `verification: {"level": "declared", "result_captured": false}`
(rest unchanged: `{available: false, reason, sql}`).

### Verification levels (deterministic, computed by a pure function with tests)
- `declared` - parse failed OR no dataset matched (degraded panel). Wording: agent claim.
- `source_identified` - dataset matched, but the WHERE could not be fully assessed
  (explain not ok) or multi-source scope without completeness.
- `scope_partial` - matched + at least one predicate mapped, but `where_complete == false`
  (dropped conjuncts / unmapped tables / fragment rejected / set-op arms ignored).
- `scope_exact` - matched + `where_complete == true` + `single_source == true` + no set-op
  on the relevant chain. (Self-join does NOT qualify as single_source.)
- `calc_decomposed` - scope_exact + `select_understood == true` + group/order/having
  resolved + CTE DAG complete.
`result_captured` is an ORTHOGONAL boolean (stored rows present for the active item).
The UI badge maps (level × result_captured) - see §6.

### Explanation steps - frozen `kind` enum (flat ordered list, ≤ 15 steps; params = display
strings, column names verbatim - never translated, never invented)

```
source [dataset]                      join [type, table]            filter_eq [col, val]
filter_neq / filter_gt / filter_gte / filter_lt / filter_lte [col, val]
filter_in / filter_notin [col, n, list≤80chars]   filter_between [col, lo, hi]
filter_null / filter_notnull [col]    filter_like [col, pattern]
filter_advanced [display]             filter_unmapped [display]     group [cols]
distinct []                           agg_sum / agg_avg / agg_min / agg_max [col]
agg_count_star []                     agg_count [col]               agg_count_distinct [col]
agg_filtered [func, col, cond]        calc_ratio [num, den]         calc_percent [expr]
calc_diff [a, b]                      calc_share [col]              window_rank [order]
window_row_number [order]             window_running [col, order]   window_lag [col]
having [display]                      sort [col, dir]               topn [n, col, dir]
limit_arbitrary [n]                   cte_step [i, role]            union [n_arms]
opaque [display≤120chars]
```
Frontend renders `t('ev.exp.' + kind, params)`; unknown kind → `ev.exp.opaque` fallback.
A single `opaque` step DOWNGRADES `select_understood`. `limit_arbitrary` (LIMIT without
resolved ORDER BY) must NEVER be worded as top-N.

Post-review amendments (2026-06-11): `topn` params are now `[n, joined_keys_with_dirs]`
(ALL ordering keys travel - tie-breakers decide which rows make the top-N, FP-07);
`filter_unmapped` IS emitted inline for every non-reproduced conjunct (§9 honesty,
CONTRACT-04); `cte_step` stays RESERVED (declared, not yet emitted - CTE steps are
flattened source-first into the list); drill-down refuses when the drillable key set
exceeds the 8-condition request cap (`not_supported`) instead of silently truncating
(CONTRACT-01); group keys carry the SOURCE column name at the end of the identity
chain, never the outer alias (FP-06).

## 3. /evidence/rows - drill-down extension

Payload gains optional `drill: [{column, value}]` (≤ 8 entries; value: str ≤ 500 |
finite number | bool | null). Server behaviour:
- Re-derives drillable group keys from the STORED SQL (never trusts the client):
  explain → GROUP BY keys with IDENTITY lineage (column-kind hops through simple CTEs)
  resolved in the live colmap. Requires: single matched source on the chain, no join
  (self-join included), `where_complete == true`, no set-op, no recursive CTE.
- Each drill.column must be in (group_keys ∩ colmap) else 400 `invalid_drill`.
- Renders `col = value` conditions (`value null` → `IS NULL`) ADDED to the standard
  conditions (kept_ids + filters + advanced). Everything else (page/sort/caps/timeout/
  throttle/guard) unchanged.

## 4. Backend hardening (in scope)

- `_EVIDENCE_TIMEOUT_PRE_QUERIES` gains `"SET LOCAL transaction_read_only TO on"`.
- `save_assistant_message` JSON cap (see §1) - closes today's unbounded sql_json hole.
- service.py light refactor: shared `resolve_context` + TTL cache (300 s, same pattern
  as `_candidates_cache`) for `read_schema` keyed by dataset name.
- docs/backend-api.md updated (stale: agent_row_count / not_whitelisted / agent-view).

## 5. Event protocol (orchestrator ↔ webapp ↔ front)

- `streaming.py` agent_event: WHITELISTED eventData pass-through - copy ONLY
  `label`, `stepIndex`, `stepCount`, `agentKey`, `status` (each str-capped 300 chars,
  numbers as-is) when present. NEVER the whole dict; NEVER agentId / message /
  instruction / steps / generatedSql into the live timeline.
- `streaming.py` generated_sql normalized event gains optional `sqlId`, `stepIndex`,
  `agentKey` (live copy stays WITHOUT result rows). Emission strategy: on each
  AGENT_DONE event seen mid-stream carrying eventData.generatedSql, yield the
  corresponding generated_sql events immediately (dedup post-loop by sql text), so a
  user-stopped run still persists its SQL (ORCH-08). Footer-trace extraction stays the
  primary source and is MERGED with AGENT_DONE items by sql text (AGENT_DONE provides
  correlation + result; trace provides authority).
- `stream_manager`: sql_list items now `{sql, success, row_count, sql_id?, step_index?,
  agent_key?, result?}` (result from capture.py, re-capped MIRROR before persistence);
  polled copy of generated_sql stays light (no result). Cap via capture.cap_sql_list
  before save_assistant_message.
- Frontend timeline: `timelineModel.applyEvent` copies `label` (string, ≤ 300) onto the
  event item when present; `timelineSteps.resolveTimelineStep(eventKind, label?)` prefers
  the backend label; KNOWN registry gains orchestrator kinds (CALLING_AGENT, AGENT_DONE,
  PLAN_READY, PLANNING, WRITING_ANSWER, DIRECT_ANSWER, RUNNING_TOOL, TOOL_DONE, DONE,
  START, SUB_AGENT_*); humanize strips SUB_AGENT_AGENT_ prefix. ids/ordering/
  timelineSignature unchanged (F8).

## 6. Frontend panel layout (sections, top = most business)

Order in `.ev-body`: (a) EvidenceTrust (badge pill: level×captured, solid border =
certified, dashed = partial, grey = declared - NEVER green, orange tokens only);
(b) EvidenceSources (dataset business label + freshness only if provided);
(c) EvidenceChips (UNCHANGED, F20); (d) EvidenceCalc (numbered steps from
explanation.steps via ev.exp.*; hidden when steps empty); (e) EvidenceResult (captured
mini-table ≤ 10 visible rows + total row_count; honest one-liner when not captured;
per-row drill chevron ONLY when drilldown.available && result.captured); then drill
banner (rendered by EvidencePanel) + (f) EvidenceTable (UNCHANGED) under an
"explore source data" label; (g) EvidenceSql (UNCHANGED component; ev.sql.title value
becomes "Détails techniques (SQL)" / "Technical details (SQL)").

Trust badge mapping (pure helper `trustLevel(meta)` in composables/evidenceProof.js):
- calc_decomposed + captured → `ev.proof.level.result` (strongest)
- calc_decomposed | scope_exact → `ev.proof.level.source` (+ exact-scope wording)
- scope_partial | source_identified → `ev.proof.level.partial` (+ dropped count note)
- declared / degraded → `ev.proof.level.declared`

Store additions (stores/evidence.js, additive - seq/rowsSeq idiom preserved):
`drill = ref(null)` → `{labels: [{column, value}], savedChips, savedIncludeAdvanced,
savedSort, savedPage}`; actions `drillIntoResultRow(rowIndex)` (build labels from
meta.result.rows[rowIndex] × meta.drilldown.columns; snapshot; page=0; refreshRows)
and `exitDrill()` (restore snapshot; refreshRows). `evidenceModel.buildRowsPayload`
gains an optional `drill` argument appended to the payload as `drill: labels`.
`close()`/`resetToAgent()` clear drill. MAX 8 drill labels (mirror backend).

i18n: ONE `ev.proof.*` + `ev.exp.*` block appended in extra.js (fr+en, flat keys,
LIST interpolation). All existing ev.* keys kept.

States: COMPLETE / PARTIAL (interactive + honest notes) / SOURCE-ONLY (no calc/result
sections) / UNAVAILABLE (degraded, declared badge) / ERROR (retry) - each stays useful.

## 7. Orchestrator v2.2 (orchestrator/orchestrator_agent.py - repo copy of the DSS Code Agent)

Fixes ORCH-01..11 from the audit: (1) generated_sql items tagged sqlId/stepIndex/
agentKey + opportunistic capped result capture (local caps, standalone file);
(2) agentId removed from CALLING_AGENT eventData; (3) ERROR eventData.message = stable
codes only (str(e) stays in span attributes/logs); (4) _sources_block uses business
labels from the registry (dataset_label_fr/en), never intranet URLs in answer text;
(5) depth guards (_MAX_TRACE_DEPTH=200) on both trace walkers; (6) shared _is_footer
(type == "footer" OR isinstance guard); (7) steps purged when intent != BUSINESS;
(8) synthesis truncation marker; (9) greet flush fix (ANNOUNCE_IN_CONTENT=False path);
(10) PLAN_READY stops echoing instructions (cap 120 chars per step summary);
(11) registry entries gain dataset_label_fr/en + dataset_ref (project_key, dataset_name).
Plus orchestrator/AUDIT.md (findings → fixes → residual risks) and DSS-free unit tests
(sys.modules dataiku stub) for: _validate_plan, _find_generated_sql (tagging+caps+depth),
_safe_json_parse, _sub_event_label, _sources_block, _build_capabilities_answer.

## 8. File boundaries (implementation workstreams - strictly disjoint)

- IMPL-1: `python-lib/owismind/evidence/sql_explain.py` (NEW, pure) +
  `tests/test_evidence_sql_explain.py` (full SQL matrix).
- IMPL-2: `python-lib/owismind/evidence/capture.py` (NEW, pure) +
  `tests/test_evidence_capture.py` + `agents/streaming.py` + `agents/stream_manager.py`
  + `storage/chat_v4.py` (JSON cap + readback projection).
- IMPL-3: `orchestrator/orchestrator_agent.py` (v2.2) + `orchestrator/AUDIT.md` +
  `orchestrator/tests/test_orchestrator_agent.py`.
- IMPL-4: `frontend/src/components/evidence/{EvidenceTrust,EvidenceSources,EvidenceCalc,
  EvidenceResult}.vue` (NEW) + `EvidencePanel.vue` + `frontend/src/composables/
  evidenceProof.js` (NEW pure) + `frontend/test/evidenceProof.test.js`.
- IMPL-5: `frontend/src/stores/evidence.js` + `frontend/src/composables/evidenceModel.js`
  + `frontend/src/i18n/extra.js` + `frontend/src/registries/timelineSteps.js` +
  `frontend/src/composables/timelineModel.js` + their tests.
- IMPL-6 (after 1+2): `evidence/service.py` + `security/validation.py` + `api/routes.py`
  + service tests + `docs/backend-api.md`.

## 9. Honesty rules (hard)

Never present an interpretation as proof; never claim "verified" because SQL ran;
dropped/unmapped elements are LISTED, not hidden; window/rank values are explained but
never claimed re-verifiable; a re-execution is "now", never "what the agent saw";
captured rows are the only "exact result used by the agent"; the LLM decides nothing
in the proof path.
