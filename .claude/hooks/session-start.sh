#!/usr/bin/env bash
# OWIsMind SessionStart hook: surface project memory + active rules at the start of every session.
# stdout from a SessionStart hook is injected into the session context.
set -uo pipefail

cat <<'EOF'
[OWIsMind] Session start. memory/ (git-versioned) is the team source of truth; the native auto-memory is a personal cache.
  - memory/CONTEXT.md       auto-imported: current focus, session chain, active next steps (kept lean, < 120 lines)
  - memory/LESSONS.md       read ON DEMAND: what diverged from the cadrage guides (append-only)
  - memory/PROJECT_STATE.md read ON DEMAND: architecture, canonical ids, validation matrix (section 11 = what is deployed)

Technical gotchas live in .claude/rules/*.md (path-scoped via frontmatter) and load AUTOMATICALLY when you touch
matching files: frontend / backend / agents / lab / memory. Do not expect them in CONTEXT.md.

Knowledge graph (graphify-out/, git-ignored, saves ~18x tokens on navigation):
  - For "where is X handled / what touches Y", QUERY THE GRAPH FIRST:  graphify query "<question>"  (--dfs to trace a path).
  - Point codebase-exploring subagents at the graph first too. Stale vs working tree? Run /graphify --update.

Active non-negotiables (full list in CLAUDE.md):
  - NO INSTALL: never run npm/pip/brew/yarn/pnpm/npx installs. Ask the user (safety first).
  - Dataiku safety: before coding, ask "is this risky/slow/overloading for the instance?".
  - SQL direct only: PROJECT_KEY prefix + COMMIT + parametrized queries; no Flow at runtime; no generic SQL route; server-side agent whitelist.
  - Never hand-edit resource/owismind-app/ or ready-for-dataiku/ (generated). frontend/ and node_modules/ never go in the zip.
  - Zero em dash (U+2014) / en dash (U+2013) anywhere. Orange charter for any styling work (docs/cadrage/CHARTE_ORANGE_UI.md).
  - Code and comments in English; communicate with the user in French. End the session with /log-session (never push).
EOF
exit 0
