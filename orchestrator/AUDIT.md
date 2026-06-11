# Orchestrator audit — v2.1 → v2.2 (Evidence trust layer, 2026-06-10)

## Methodology

Line-by-line review of `orchestrator_agent.py` v2.1 against the frozen contract
(`docs/superpowers/specs/2026-06-10-evidence-trust-layer-design.md`, §1/§5/§7) and its
webapp consumer (`python-lib/owismind/agents/streaming.py`). Focus axes: data leakage into
live events, payload boundedness, protocol stability, honesty of synthesized answers, and
robustness of the trace walkers. Findings numbered ORCH-01..11; fixes applied as a minimal
delta (PLAN/EXECUTE/SYNTHESIZE architecture, `_validate_plan`, verbatim relay, persona and
capabilities registry untouched). Every pure fix is covered by `tests/test_orchestrator_agent.py`
(59 DSS-free unittest cases, dataiku stubbed).

## Findings

| ID | Sev | Problem (v2.1) | Fix (v2.2) |
|---|---|---|---|
| ORCH-01 | High | Webapp relays sub-agent eventData without a whitelist: orchestrator labels lost, risk of leaking the whole dict into the live timeline. | **Webapp-side** (IMPL-2, `streaming.py`): whitelisted pass-through — only `label`, `stepIndex`, `stepCount`, `agentKey`, `status` (str-capped 300). |
| ORCH-02 | High | `generated_sql` items carried no correlation keys and never the result the agent actually used — Evidence Studio could not show "the exact result". | Items tagged `sql_id` (`s{stepIndex}q{n}`), `step_index`, `agent_key` before AGENT_DONE; opportunistic capped `result` capture (`{columns, rows, truncated}`) from the tool span outputs. Local caps: 50 rows, 50 cols, cells str()[:256] (finite primitives kept), serialized ≤ 64 000 chars else rows dropped + `truncated`. |
| ORCH-03 | High | `str(e)` (stack-adjacent internals) emitted in ERROR `eventData.message`, reachable by the client. | Stable machine codes only: `agent_step_failed`, `synthesis_failed`, `internal_error`, `no_user_message`. Raw error stays in `sp.attributes["error"]` + logs. |
| ORCH-04 | Med | Internal `agentId` leaked in CALLING_AGENT eventData. | Removed from eventData; remains in the step span attributes. |
| ORCH-05 | Med | Intranet URLs printed verbatim in the answer's Sources section (leak + useless for business users). | `_sources_block` emits `**Sources** : {business label}` from `dataset_label_fr/en`; `dataset_sources` URLs stay server-only in the registry. |
| ORCH-06 | Med | Both trace walkers (`_find_generated_sql`, `_find_usage_metadata`) recursed unbounded → RecursionError on a pathologically deep trace kills the run. | `_MAX_TRACE_DEPTH = 200` depth guard on both (graceful partial extraction). |
| ORCH-07 | Med | Footer detection relied on `data.get("type") == "footer"` only; SDK builds that signal the footer by class were missed (trace + SQL silently lost). | Shared `_is_footer(chunk, data)` (payload type OR guarded `DSSLLMStreamedCompletionFooter` isinstance), used in `_execute_agent_step`, `_synthesize`, `_answer_capabilities`. |
| ORCH-08 | High | A user-stopped run never sees the footer → generated SQL lost for the whole turn. | **Webapp-side** (IMPL-2, `streaming.py`): yield `generated_sql` events on each mid-stream AGENT_DONE carrying `eventData.generatedSql`; dedup/merge with footer-trace extraction by sql text. |
| ORCH-09 | Med | Step outputs silently cut at `STEP_RESULT_MAX_CHARS` before synthesis → the writer model presents truncated data as complete. | Truncated blocks suffixed with `…[RESULT TRUNCATED — state explicitly that the data above may be incomplete]`. |
| ORCH-10 | Med | (b) non-BUSINESS plans could carry executable steps; (c) PLAN_READY echoed full instructions (user data in an event payload); (d) greet lost on the relay path when `ANNOUNCE_IN_CONTENT=False`. | (b) `_validate_plan` purges steps unless intent == BUSINESS; (c) step summaries `{kind, capability, instruction[:120]}`; (d) unconditional greet flush before the steps loop. |
| ORCH-11 | Low | Registry had no business dataset metadata for downstream consumers. | `dataset_label_fr/en` + `dataset_ref {project_key, dataset_name}` per agent capability. |

## Residual risks (open)

1. **Result capture unconfirmed on the instance.** The exact key carrying the rows in the
   `semantic-model-query` span `outputs` is NOT verified — extraction is best-effort over
   candidate keys (`rows`/`records`/`data`/`result_rows`/`values`). Verify on a real trace
   from the traces dataset; if the key differs, add it to `_RESULT_ROW_KEYS` (append-only).
   Until then `result` may simply be absent (honest: `result_captured: false` downstream).
2. **Semantic misrouting.** The planner can still classify a business question as
   GREETING/OUT_OF_SCOPE (or vice versa); validation is structural, not semantic. Mitigated
   by prompt rules + refuse-rather-than-hallucinate, not eliminated.
3. **`block_labels` coupling.** Per-sub-agent block/tool label maps are hand-maintained in
   the registry; a renamed block in a sub-agent silently falls back to the generic label
   (cosmetic only, but drifts unnoticed).
4. **AGENT_DONE payload size.** `generatedSql` (with capped results) rides inside the
   AGENT_DONE eventData; bounded by the local caps (≤ ~64 KB per query result) but the
   webapp must keep stripping it from the live polled timeline (ORCH-01 whitelist).

## Post-review amendments (2026-06-11, adversarial review round)

- **ORCHV22-02 (fixed)** — `sp.append_trace(sub_trace)` in `_execute_agent_step` is now
  exception-guarded like the other streamed loops: a malformed footer trace degrades the
  merged cost only, never the relayed answer / SQL tagging / AGENT_DONE emission.
- **ORCHV22-01 (webapp-side, fixed)** — the cross-contract docstring in
  `agents/streaming.py::_normalized_sql_event` was inverted (claimed camelCase tagging);
  corrected: the orchestrator tags in snake_case, both spellings stay accepted.
- **CHAT-REG-01 (webapp-side, fixed)** — the footer-trace merge now consumes the
  AGENT_DONE relay map ONE-SHOT (`pop`): two distinct trace spans with the same sql text
  (fail-then-identical-retry) each emit their own event again, byte-identical to the
  DSS-validated pre-trust-layer flow.
