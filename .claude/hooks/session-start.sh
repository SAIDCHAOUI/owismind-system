#!/usr/bin/env bash
# OWIsMind SessionStart hook — surface project memory + active rules at the start of every session.
# stdout from a SessionStart hook is injected into the session context.
set -uo pipefail

cat <<'EOF'
[OWIsMind] Session start — read project memory before coding:
  • memory/CONTEXT.md        current focus, last session (3 lines), active gotchas
  • memory/LESSONS.md        what diverged from the cadrage guides (source of truth)
  • memory/PROJECT_STATE.md  architecture, canonical ids, validated / not-validated matrix

Active non-negotiables:
  - NO INSTALL: never run npm/pip/brew/yarn/pnpm/npx installs — ask the user (safety first).
  - Dataiku safety: before coding, ask "is this risky/slow/overloading for the instance?". Avoid harmful code.
  - SQL direct only: PROJECT_KEY prefix + COMMIT + parametrized queries; no Flow at runtime;
    no generic SQL route; server-side agent whitelist.
  - Never hand-edit resource/owismind-app/ or ready-for-dataiku/ (generated). Build/package via skills.
  - frontend/ and node_modules/ never go in the zip. Code & comments in English.
  - Canonical names: plugin "owismind", package "owismind", webapp "webapp-owismind-ai-agents",
    resource "owismind-app" — the cadrage guides use example names; do not copy them.
  - End the session with /log-session.
EOF
exit 0
