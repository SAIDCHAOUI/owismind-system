---
name: repo-memory-layout
description: OWIsMind memory/setup file layout and how to verify a "deep clean" slimming lost no load-bearing info
metadata:
  type: project
---

OWIsMind's team memory (git-versioned) and Claude Code setup were reorganized on the
`refactor/deep-clean-v1.2` branch (2026-07-06). Durable map for reviewing memory/setup integrity:

- `memory/CONTEXT.md` = lean (< 120 lines): header + Focus courant (1-2 last runs) + "Chaine des sessions"
  (one line/run pointing to `sessions/<date>.md` + Lxxx) + Regles (2 lines -> CLAUDE.md + rules) + active next-steps.
- `memory/LESSONS.md` = append-only, headers are `## L0xx` (grep `'^## L'`). Status tags per lesson are HISTORICAL;
  `PROJECT_STATE.md` section 11 is authoritative for what is actually deployed.
- `memory/PROJECT_STATE.md` = durable state; section 2b timeline + section 11 matrix.
- Technical gotchas moved OUT of CONTEXT.md into `.claude/rules/*.md` (path-scoped, auto-loaded):
  frontend.md (F1-F22, F7/F9 never existed), backend.md (items 1-14; 1-12 legacy + 13 analytics + 14 screen-ctx),
  agents.md (P0/P0★/P0★★/P3 + recoll process), lab.md (MOCK-is-contract L115), memory.md (P2/P4 hygiene).
- `.claude/agents/*.md` = subagent defs; frontmatter uses `tools`/`effort`/`memory`, NO forced model (good: never fable).
- `.claude/hooks/dash-guard.sh` = PostToolUse hook, uses `text.count("-")` in python3 (correctly avoids the
  BSD-grep `-P` false-negative gotcha, L084/L093); exempts memory/LESSONS.md (those lessons quote the banned glyph).

**How to verify slimming lost nothing:** for each block deleted from CONTEXT.md, confirm the fact survives in
sessions/*.md (recent run detail files were NOT deleted), LESSONS.md, PROJECT_STATE.md, or .claude/rules/*.md.
Deleted session files must be cited by path NOWHERE: `grep -rn "sessions/<date>"` excluding the sessions dir
(note: bare date strings like "2026-06-02" appear as content in LESSONS/PROJECT_STATE - those are NOT path
citations). em-dash operational gotcha (BSD grep) survives in LESSONS L084/L093 + memory-curator + log-session skill.

**Proven-identical consolidation pattern:** `sql_config.readonly_pre_queries()` returns a fresh list
`["SET LOCAL statement_timeout TO '30000'", "SET LOCAL transaction_read_only TO on"]`, replacing inline literals
at 6 call sites (evidence/service, benchmark_view/lab_io, storage/{settings,suggestions,budget,artifacts}).
Verify byte-identity via the diff before trusting "behavior unchanged". Backend suite = 790 tests
(`python3 -m unittest discover -s tests` from `Plugin/owismind/`).
