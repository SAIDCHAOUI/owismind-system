---
name: parallel-workstream-red-tests
description: This repo runs several agents in ONE dirty working tree; re-run git status and the suites at the END of a review and attribute failures by file path
metadata:
  type: feedback
---

Never treat the working tree as frozen during a review, and never attribute a test failure to
the diff you were given without checking which file the failing module covers.

**Why:** on 2026-08-06 the A1/A2/A3 frontend review started with 14 changed paths; by the end of
the same review the tree had grown `agents/native_orchestrator.py` (untracked),
`agents/stream_manager.py`, `api/routes.py` and `security/validation.py` from a concurrent
"chantier B" agent. The plugin suite went from 979 OK to 979 with 4 failures MID-REVIEW
(`test_stream_manager_deadlines`: chantier B added 2 positional args to the worker without
updating the test's fake worker). Reporting that as a defect of the frontend diff would have
been a false accusation; the frontend diff touches zero `python-lib/` files.

**How to apply:**
- Run `git status --short --untracked-files=all` at the START and again at the END; diff the two.
- Run the suites at the END, and for every failure map the failing test module to the source file
  it covers, then check whether that file is in YOUR diff (`git diff --stat -- <path>`).
- Report out-of-scope failures explicitly as out-of-scope, naming the workstream, rather than
  omitting them (the suite really is red and the lead needs to know).

Older accumulated notes for this repo live in a DIFFERENT directory:
`/Users/saidchaoui/projects/owismind/.claude/agent-memory/adversarial-reviewer/` (12 entries,
incl. `owismind-frontend-review-patterns.md` which first recorded this parallel-tree pattern).
Read both directories at the start of a run.
