---
name: log-session
description: Write an end-of-session log for OWIsMind, refresh the short-term memory (memory/CONTEXT.md), append any new lesson to memory/LESSONS.md, update the knowledge graph (graphify --update) and commit the session. Use at the end of a session, or when the user asks to log the session or update memory.
---

# /log-session — End-of-session log + memory refresh + graph update + commit

Captures what happened this session, keeps the memory current, keeps the knowledge graph fresh,
and commits the session snapshot. Communicate in French.

## Steps

1. **Determine today's date** from the environment context (`Today's date is …`). Use `YYYY-MM-DD`.

2. **Write the session log** at `memory/sessions/<YYYY-MM-DD>.md` (if the file exists, append a new
   `## <HH:MM or run N>` section instead of overwriting). Include:
   - **Objectif** — what the session set out to do.
   - **Fait** — concrete changes (files created/edited, builds, packages). Be specific.
   - **Décisions** — choices made and why.
   - **Validé / non validé** — what was proven vs. assumed.
   - **Prochaines étapes** — next actions.

3. **Refresh `memory/CONTEXT.md`** (short-term memory, loaded every session). Update:
   - 🎯 Focus courant
   - 🧭 Dernière session (3 lines max, dated)
   - ⚠️ Top gotchas / règles actives (only what's currently relevant)
   - 🔜 Prochaines étapes
   Keep it short — detail belongs in `PROJECT_STATE.md`.

4. **Append lessons** to `memory/LESSONS.md` if anything diverged from the cadrage guides, or failed
   then worked. Use the next `L0xx` id and the format: Contexte / Ce qui a échoué / Solution qui
   marche / Preuve-vérification / Source / Date. Append above the trailing HTML comment marker.

5. **Update `memory/PROJECT_STATE.md`** only for durable state changes (new canonical id, structure
   change, validation-matrix update). Do not duplicate transient notes there.

6. **Update the knowledge graph** (`graphify-out/`, standing user authorization 2026-06-11): run the
   `/graphify --update` incremental pipeline on the repo root. Changed **code-only** files →
   AST-only re-extraction (free, no LLM). Changed **docs/memory** files → semantic re-extraction of
   those files only (subagents; the extraction cache makes this cheap). If graphify is unavailable,
   say so in the report — never skip silently. NO INSTALL still applies (never pip install graphify;
   ask the user).

7. **Commit the session** (standing user authorization 2026-06-11): `git add -A`, then commit with
   message `session <YYYY-MM-DD>: <one-line summary>` ending with the Co-Authored-By trailer. The
   git post-commit hook then refreshes the code graph automatically in the background. **Never push**
   (the user pushes). If the working tree is clean, skip the commit and say so.

8. **Report** (in French): a short "ce qui est en place / prochaines étapes" summary, the paths
   touched, the graph update result (files re-extracted / AST-only / unavailable) and the commit hash.

## Notes
- This skill writes memory files, updates the knowledge graph and commits — no build, no package,
  no upload, no push.
- Never invent results: if something was skipped or failed, record it as such.
