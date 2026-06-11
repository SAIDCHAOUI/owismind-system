# OWIsMind SalesDrive v2 (Code Agent Dataiku) — repo copy

## Role

`salesdrive_agent.py` is the source of truth for the **SalesDrive v2 Code Agent**: the
deterministic port of the visual SalesDrive revenue agent (`agent:rNTZ781a`). Pipeline:

1. **UNDERSTAND** — 1 LLM call (strict JSON): scope, language, intent (frozen enum:
   `total | breakdown | top_n | compare_phases | compare_periods | trend | generic`),
   phases, period(s), group-by axis, top-N, business terms.
2. **RESOLVE** — the code calls `Drive_Revenues_resolve_filter_value` once; routing on
   `overall_status` is pure Python (ambiguous/unresolved → deterministic clarification).
3. **COMPOSE** — the `semantic_question` is built from frozen templates (the LLM never
   writes it); resolver `filter_clauses` are appended verbatim.
4. **QUERY** — the code calls the Semantic Model Query tool directly
   (`get_agent_tool(...).run(...)`) and captures SQL + rows from the **return value**
   (deterministic Evidence capture — no more trace row-key guessing).
5. **RENDER** — markdown table + figures formatted by code (exact by construction);
   a small LLM writes only the headline, every cited number is verified against the
   result, otherwise a deterministic fallback headline is used.

The file is **standalone**: stdlib + `dataiku` only. It never imports from the plugin.

## Disambiguation policy (loop-proof, added after the IPL incident 2026-06-11)

When the resolver returns ambiguous candidates, the agent applies a deterministic
policy BEFORE asking the user (`refine_ambiguous`):

1. **Qualified terms** — `"VALUE (Column)"` (the exact format our own clarification
   teaches, e.g. `IPL (Product)`) is parsed by `parse_qualified_term`: the resolver
   gets the base value, the explicit column then filters the candidates. Echoing a
   clarification answer can therefore never loop.
2. **Strict exact-value preference** — candidates whose `target_value` equals the
   raw term (case-insensitive) evict catalog normalization collisions (`IPL +`
   normalizes to `ipl` and used to pollute the `IPL` candidate set).
3. **Column priority auto-pick** — when all remaining candidates carry the SAME
   value across columns, Product > Solution > SolutionLine > sirano_product decides
   (same rule as the resolver's `exact_offer_priority`): no clarification at all.
4. Only a **real business choice** (distinct values, e.g. `IPL` vs `IPL +`) still
   triggers a clarification — which now ends with a parseable example answer
   (« Répondez par exemple : “IPL (Product)” »).

**Conversational continuity (the intelligent layer).** The orchestrator (v2.3,
capability flag `pass_context`) forwards the PREVIOUS assistant message + the
user's raw answer as a system message. The UNDERSTAND LLM therefore SEES the
pending disambiguation question and maps any natural answer — "le produit",
"la première", "IPL plus" — to one candidate **from that list only**, emitted as
a qualified `VALUE (Column)` term. Generic for every future clarification
(customers, partners, zones…): zero per-value code, and a wrong pick still goes
through the resolver, so the worst case is an honest re-clarification, never a
wrong figure.

## Collaboration contract with the orchestrator (v2.3+)

- Same event dialect as a visual agent: `AGENT_BLOCK_START` with the historical
  blockIds (`resolve`, `query_revenue_semantic`, `format_tool_output`, `clarify_user`,
  `out_of_scope_msg`) and `AGENT_TOOL_START` with the historical tool names — the
  registry labels of the `salesdrive_v2` capability apply unchanged.
- One final structured **`AGENT_RESULT`** event: `{status, language, intent,
  resolvedFilters, sqlCount, rowCount}` with `status ∈ ready | need_clarification |
  out_of_scope | no_data | error`. The orchestrator captures it (never relays it),
  exposes it in `AGENT_DONE.eventData.agentResult`, and skips the sources block on
  `need_clarification` / `out_of_scope`.
- One trace subspan named `semantic-model-query` per generated SQL with outputs
  `{sql, success, row_count}` (+ `rows`/`columns` on the first) — the orchestrator's
  frozen Evidence extraction (`_find_generated_sql` / `_extract_result`) works as-is.

## Deployment (parallel run, visual agent untouched)

1. Tool ids are wired (confirmed on the instance 2026-06-11):
   `RESOLVER_TOOL_ID = "aNxeOc4"` (Drive_Revenues_resolve_filter_value, InlinePython)
   and `SEMANTIC_TOOL_ID = "v4oqA6R"` (revenue_semantic_query, semantic-model-query).
   The semantic tool's input key is auto-detected from its descriptor at runtime
   (`pick_semantic_input_key`); if a tool is ever recreated with a new id, the code
   falls back to a name match over `list_agent_tools()`.
2. Confirm/adjust `UNDERSTAND_LLM_ID` (defaults to the orchestrator planner id, known
   to work on the instance).
3. Create a new **Code Agent** in DSS (Agents > New > Code agent), paste the FULL
   content of `salesdrive_agent.py`, save, note its agent id.
4. In `orchestrator/orchestrator_agent.py`: put that id in the `salesdrive_v2`
   registry entry, set `salesdrive_v2.enabled = True` and `salesdrive.enabled = False`
   (one revenue capability at a time), then paste the orchestrator v2.3 into its
   Code Agent.
5. Quick-test from the agent itself, then from the webapp. Rollback = flip the two
   `enabled` flags back and re-paste.

On the first real run, check in the trace the `salesdrive:semantic-tool` span:
`shape_keys` lists the actual output keys of the Semantic Model Query tool — if the
rows live under an unrecognised key, add it to `_ROW_KEYS` (append-only).

Always edit the repo copy first, test, then paste — never the other way around.

## Testing (DSS-free)

From the repo root:

```bash
python3 -m py_compile salesdrive/salesdrive_agent.py
python3 -m unittest discover -s salesdrive/tests -v
```

The tests stub `dataiku` before import and cover only the pure functions (validation,
semantic-question composition, clarifications, tool-output extraction, formatting,
verified-headline gate). Anything touching LLM Mesh / agent tools must be validated
on the DSS instance.
