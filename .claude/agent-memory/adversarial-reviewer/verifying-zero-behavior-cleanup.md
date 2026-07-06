---
name: verifying-zero-behavior-cleanup
description: How to verify "zero runtime behavior change" cleanup branches in OWIsMind (comment/doc purge + proven-identical consolidation)
metadata:
  type: feedback
---

For OWIsMind "deep clean" branches whose contract is ZERO runtime behavior change:

**How to apply:**
- Comment-only claims on Python files: parse both revisions with `ast`, strip module/func/class
  docstrings from each, compare `ast.dump`. If equal, only comments/docstrings changed. Used this
  on the 5 Code Agent files + tools/recipes + stream_manager/chat_v5; all AST-identical.
- Code Agent docstrings are NOT load-bearing here: grep confirms no `__doc__` usage in
  `dataiku-agents/OWISMIND/`, and agent prompts live in string-literal variables (caught by AST diff),
  so condensing module headers is safe.
- Consolidations (e.g. `sql_config.readonly_pre_queries()`): git grep the literal on `main` vs `HEAD`
  to prove every removed inline copy was byte-identical to the new single source. 6 read sites were
  identical; write variant in `storage/events.py` intentionally left inline.
- Dash scan: Python `t.count()` on the two banned codepoints (U+2014, U+2013) over
  `git diff --name-only main...HEAD` minus `resource/` (generated) and `memory/LESSONS.md` (documented
  15-dash exception). BSD `grep -P` gives false negatives (see L093), never trust it for this check.
  Also note: a hook `dash-guard.sh` blocks Write if the file contains either glyph, so describe them
  by codepoint, never paste the raw glyph.
- Agent id tables: `dataiku-agents/README.md` lists DEV ids only (038G7mlF, agent:bHrWLyOL,
  agent:NcE9LD2i) and defers PROD ids to `OWISMIND/README.md` (Xrv7GvfG, agent:uO5hEzAs). Not a
  mismatch, the top-level README is DEV-scoped by design.
- body.html asset refs must match the rebuilt `resource/owismind-app/index.html` entrypoint assets
  (grep both, diff). Only sanity-check names; never read the generated bundles.
