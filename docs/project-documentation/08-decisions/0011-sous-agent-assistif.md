# ADR-0011 - Assistive sub-agent (does not impose a column for an ambiguous term)

> Audience: Agent engineer. Last updated: 2026-06-18. Summary: the revenue expert sub-agent
> assists the Semantic Model (Sonnet) by passing it hints, but it never pins the column of an
> ambiguous offer term: it is the model that decides the hierarchy, and no business value is
> hardcoded.

## Status

Accepted. Code in place in `dataiku-agents/agents/SalesDrive_revenue_expert.py`. 367+ unit tests
green (`tests/test_dataset_expert.py`). The behavior still needs to be re-validated in DSS via the
orchestrator (EVPL case), a point flagged as in flux below.

> IN FLUX: the `dataiku-agents/` layer is being edited live. The function names and wording cited
> here were confirmed in the code at the time of writing, but may change. The EVPL case had not been
> re-validated via the orchestrator at the time the original lesson was written.

## Context and problem

A real question triggered a structural bug: "revenus YTD EVPL, actuals vs budget". The value `EVPL`
exists at several levels of the offer hierarchy (`Product`, `Solution`, and `sirano_product`).

The deterministic sub-agent, in its earlier version, pinned a column itself for this value. The
faulty mechanism lives in `Profile.column_priority`: absent an explicit override, it ranks first the
MOST specific column, that is, the one with the greatest number of distinct values.

```python
def column_priority(self, name):
    c = self.columns.get(name) or {}
    if isinstance(c.get("ambiguity_priority"), int):
        return (0, c["ambiguity_priority"])
    return (1, -(c.get("distinct_count") or 0))
```

Result: `sirano_product` (153 distinct values) beat `Product` (42 distinct values), the agent pinned
`sirano_product = 'EVPL'`, and the `Phase = 'BUDGET'` rows carry no `sirano_product`, so the budget
dropped to 0. Yet the Playground (the Semantic Model alone, Sonnet) resolved `Product = 'EVPL'`
perfectly. The small sub-agent was dictating the wrong answer to a model that would have known how to
do better.

The problem goes beyond EVPL: it is the very principle of "who decides". The sub-agent (fast
extraction, small model) must not settle a semantic question (the offer hierarchy) that the large
model resolves better. And doing it as a hardcoded rule violates the project's P3 rule: no business
value (neither column name nor hierarchy) coded into an agent's logic.

## Decision

The sub-agent ASSISTS the Semantic Model, it does not DICTATE the column of an ambiguous offer term
to it. Concretely, three deterministic mechanisms, all in `SalesDrive_revenue_expert.py`:

1. Resolution of a term present in several columns. When the same exact value lives in several
   columns, `refine_ambiguous` keeps the priority column for the internal filters but records the
   others in `alt_columns` (transparency), instead of discarding them. When several DISTINCT values
   remain (one per column), it prefers the column that STRICTLY dominates by priority if it resolves
   to a single value (for example, an account name takes precedence over its parent group) and
   DISCLOSES the others, rather than forcing a clarification.

2. Deferral of multi-column offer terms. `defer_multicolumn_offer_terms` reclassifies as `deferred`
   any term still `ambiguous` whose candidates span at least two distinct columns (the "Roaming Hub"
   case, which matches a `Product` and a `sirano`). Instead of asking the user about the offer
   hierarchy, the raw term is passed to the Semantic Model with its partial candidates as context.
   The decision rests PURELY on the number of distinct columns, never on a hardcoded column name:

   ```python
   if len(cols) >= 2:
       ...
       deferred.append({"raw": r.get("raw_value", ""), "columns": cols, "samples": samples[:8]})
       out.append(dict(r, status="deferred"))
       continue
   ```

   Conversely, a single-column ambiguity (two distinct entities in a single column, for example two
   different customers) remains a genuine question and continues to trigger a clarification request to
   the user.

3. Composition of the message to the tool, as hints and not as orders. `build_semantic_question` puts
   the user question first as the source of truth (`USER QUESTION (this is the source of truth -
   answer THIS)`), then adds the grounding findings as HINTS. A single-column value (a customer name,
   for example) is suggested directly (exact spelling, anti-typo). A multi-column value is NOT pinned:
   the message emits an `AMBIGUOUS OFFER TERM` marker that explicitly tells the model to decide
   itself.

   ```python
   parts.append(
       "AMBIGUOUS OFFER TERM - \"%s\" is a real data value present in "
       "SEVERAL columns (%s). Do NOT take a pinned column from the "
       "helper here: YOU resolve it, using your offer-hierarchy rules "
       "and the user's intent, then disclose the level you picked."
       % (f["value"], ", ".join(cols)))
   ```

   The wording of the hints block formalizes it: `They are HINTS to ASSIST you, NOT orders ... you
   keep the final say`.

The business rule itself (the offer hierarchy `SolutionLine > Solution > Product`, and "never default
to sirano_product") does NOT live in the agent code. It lives in the Semantic Model instructions
(`sqlGenerationConfig.instructions`), versioned in the scripts
`tools/semantic_model/build_aligned_semantic_model.py` and
`tools/semantic_model/update_aligned_semantic_model.py`. The agent code only defers and discloses; it
is the Sonnet model that applies the hierarchy.

### Who decides what

| Decision | Actor | Where |
|---|---|---|
| Recognize that a term is ambiguous (multi-column) | sub-agent (deterministic) | `defer_multicolumn_offer_terms`, by NUMBER of columns |
| Choose the offer level (`Product` vs `Solution` vs `sirano_product`) | Semantic Model (Sonnet) | `sqlGenerationConfig.instructions` instructions |
| Suggest an exact single-column value (anti-typo) | sub-agent (hint) | `build_semantic_question`, `HELPER FINDINGS` block |
| Ask the user (clarification) | sub-agent, ONLY in single-column | `n_resolve` -> `build_clarification` |
| Disclose the ambiguity to the user | sub-agent (deterministic, no figures) | `build_disclosure_notes` in `n_render` |

## Flow in the pipeline

The sub-agent follows the UNDERSTAND -> RESOLVE -> QUERY -> RENDER pipeline (see the canonical home of
the agent-loop diagram in [the agent system](../05-agents/01-agent-system-overview.md)). This
decision materializes at three stages:

- RESOLVE (`n_resolve`): `refine_ambiguous` then `defer_multicolumn_offer_terms`. Deferred terms are
  threaded forward via `offer_terms_for_model`; a single-column ambiguity left `ambiguous` or
  `unresolved` triggers `build_clarification` and stops the turn.
- QUERY (`n_query`): `build_semantic_question` composes the message for the `revenue_semantic_query`
  (`v4oqA6R`) tool, with confident hints and `AMBIGUOUS OFFER TERM` markers.
- RENDER (`n_render`): `build_disclosure_notes` adds transparency lines (constant `DISCLOSE_NOTE`,
  without any figure) that inform the user that the value exists at several levels and that the most
  granular level was preferred by default.

## Rationale

- The reasoning lives in the large model, not the small one. UNDERSTAND is a deterministic extraction
  (see [ADR-0007](0007-json-output-force-sur-understand.md)), not a place for semantic decisions.
  Having the small extraction model settle the offer hierarchy means asking it for an analysis it is
  not equipped for.
- P3: no hardcoded business value. The offer hierarchy is business knowledge; coding it into the agent
  would make it a "rule per bug". By leaving it in the model instructions, we iterate it via
  `update_aligned_semantic_model.py` (in-place modification, without re-indexing) without touching the
  code.
- Decision by STRUCTURE, not by name. `defer_multicolumn_offer_terms` decides on the count of distinct
  columns, never on the `sirano_product` name. The code stays generic and will survive a schema
  change.
- Disclose rather than ask. When a column clearly dominates, preferring the dominant column and
  disclosing the alternatives avoids a tedious clarification for the user while remaining honest.

## Consequences

Positive:
- Fixes the `budget = 0` trap on multi-column terms (the model resolves `Product = 'EVPL'`, not
  `sirano_product`).
- P3-clean code: zero hardcoded column name or hierarchy in the agent.
- Native transparency: the user sees, with no LLM in the evidence path, that the value was ambiguous
  and which level was preferred.
- Fewer pointless clarifications: hierarchy ambiguities are resolved, not bounced back to the user;
  only genuine single-column ambiguities (two distinct entities) are asked.

Negative or watch points:
- The EVPL behavior must be re-tested via the orchestrator in DSS (smoke test: "revenus YTD EVPL,
  actuals vs budget" -> `Product`, budget != 0, transparency note). Not re-validated at the time the
  original lesson was written.
- The guarantee of a deterministic winner on a stubborn ambiguity goes through an explicit
  `ambiguity_priority` override in the profile (first criterion of `column_priority`), to be set on a
  case-by-case basis.
- The fix depends on the Semantic Model instructions: if they regress (for example, "never default to
  sirano_product" is removed), the bug can come back on the model side. These instructions are
  versioned in `tools/semantic_model/`, but the model deployed in DSS must stay aligned.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Give thinking (reasoning) back to the sub-agent so it settles things itself | UNDERSTAND is a deterministic extraction (ADR-0007); it is not the place for a semantic decision, and the small model resolves worse than Sonnet. |
| Code the offer hierarchy (`Product > Solution > sirano_product`) into the agent code | Violates P3 (hardcoded business value). The hierarchy lives in the model instructions, iterable without touching the code. |
| Keep the `column_priority` `-distinct_count` fallback as a definitive pin | This is exactly the cause of the bug: `sirano_product` (more distinct values) won and dropped the budget to 0. |
| Systematically ask the user as soon as a value is ambiguous | Tedious UX; most offer-hierarchy ambiguities can be resolved by the model. We only ask on a genuine single-column ambiguity (two entities). |

## See also

- [The revenue expert sub-agent](../05-agents/03-revenue-expert-subagent.md) - the
  UNDERSTAND/RESOLVE/QUERY/RENDER pipeline where this decision applies.
- [Agent tools and Semantic Model](../05-agents/04-tools-and-semantic-model.md) - the
  `revenue_semantic_query` (`v4oqA6R`) tool and the model instructions that carry the offer hierarchy.
- [Grounding and Semantic Model](0010-grounding-et-semantic-model.md) - how terms are grounded on the
  value_index before being passed to the model.
- [`with_json_output` forced on UNDERSTAND](0007-json-output-force-sur-understand.md) - why the
  extraction does not reason and stays deterministic.
- [Flow recipes and grounding](../05-agents/05-flow-recipes-and-grounding.md) - the building of the
  profile and the value index that feed the resolution.
- [ADR index](README.md) - back to the list of decisions.
