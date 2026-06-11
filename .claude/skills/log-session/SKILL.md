---
name: log-session
description: Write an end-of-session log for OWIsMind and refresh the short-term memory (memory/CONTEXT.md), appending any new lesson to memory/LESSONS.md. Use at the end of a session, or when the user asks to log the session or update memory.
---

# /log-session — End-of-session log + memory refresh

Captures what happened this session and keeps the memory current. Communicate in French.

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

6. **Report** (in French): a short "ce qui est en place / prochaines étapes" summary and the paths touched.

## Notes
- This skill only writes memory files — no build, no package, no upload.
- Never invent results: if something was skipped or failed, record it as such.
