---
name: security-invariants
description: Where OWIsMind's security-relevant constraints live and how to verify a diff hasn't weakened them
metadata:
  type: project
---

Security invariants to check on any backend/hook diff.

**Read-only pre-queries** (the SQL safety net): every dataset READ runs under two
transaction-scoped `SET LOCAL` strings, exact and in order:
`SET LOCAL statement_timeout TO '30000'` then `SET LOCAL transaction_read_only TO on`.
Since branch refactor/deep-clean-v1.2 these are centralized in
`storage/sql_config.readonly_pre_queries()` (returns a FRESH list per call). Consumers:
evidence/service, evidence/source_service, storage/{artifacts,budget,settings,suggestions},
benchmark_view/lab_io. Writes use only the timeout string (persist, cannot be read-only).
Test: `OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_sql_config.py::ReadonlyPreQueriesTest`.

**Agent whitelist**: front sends a logical key; `agent_id` is resolved server-side BEFORE
`stream_manager.start_run` is ever called. Invariant documented in stream_manager.py docstring.

**Hooks** (`.claude/`): `guardrail.sh` (PreToolUse) blocks package installs / edits to generated
outputs via `grep -Eiq` on the raw JSON payload, exit 2 = block. `dash-guard.sh` (PostToolUse,
added on deep-clean branch) warns on em/en dashes; ALL error paths exit 0, exit 2 only feeds the
warning back to Claude, LESSONS.md is the documented exception (quotes the banned glyphs).
`settings.json` permissions.allow/deny are the install/output denylist - must stay byte-identical.

**How to apply:** on a "no behavior change" cleanup branch, `git diff main...HEAD` the enforcement
lines (not comments) of guardrail.sh must be empty; permissions.allow/deny must be unchanged;
the pre-query consolidation must produce byte-identical strings. Comment rewordings that preserve
the whitelist/read-only/one-run-per-call rationale are fine.
