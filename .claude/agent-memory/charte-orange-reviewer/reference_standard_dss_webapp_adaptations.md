---
name: reference_standard_dss_webapp_adaptations
description: Standard (vanilla-JS) DSS webapps in this repo adapt the Orange charter in 3 sanctioned ways; do NOT false-flag them. Seen clean on benchmark_launcher + agent-factory-console.
metadata:
  type: reference
---

The repo has "Standard" DSS webapps (plain body.html + script.js + style.css, no Vue build)
under `OWIsMind_LAB/webapps/benchmark_launcher/` and
`OWIsMind_PRD_V1_2/webapps/agent-factory-console/`. They follow the Orange charter but
adapt it three ways that are ACCEPTED (both files reviewed clean) - do not report these as
violations:

1. **Theme scope is the app root, not `body`.** The charter says dark via `body[data-theme]`,
   but DSS owns `<body>` in a Standard webapp. So tokens + `[data-theme="dark"]` live on the
   app-root element instead: `#afc[data-theme="dark"]` (console) or `[data-theme]` on `<html>`
   (launcher). The charter INTENT (token-driven dark via a data-theme attribute) is satisfied.
2. **No brand logo image, eyebrow-only header.** These webapps can't easily import
   `orange-logo.png`, so the header is just the charter eyebrow + H1 + 52x4 orange title-bar,
   with NO logo at all. That is fine - the banned thing is a CSS-FABRICATED brand mark (orange
   square + bar), which neither file has. Absence of a logo is not a violation.
3. **ASCII-only French UI strings (missing diacritics)** e.g. "Usine a agents", "Etat", "Cle
   de projet", "Executer", "termine". This is orthography, NOT a charter rule - the charter is
   purely visual style. Out of scope for a charter review; mention it only as an informational
   aside if asked, never as a charter violation.

Also note: `color: #fff` on a solid `--danger`/`--success` button or verdict chip (not just on
orange) is an established repo pattern (validated reference `benchmark_launcher` uses it). The
charter's literal wording sanctions `#fff` only on orange, but white-on-a-solid-status-fill is
effectively the same exception and is not worth blocking. See [[feedback_devs_self_audit_charter]].

The console (`agent-factory-console`) is actually MORE charter-correct than the reference
launcher: it defines a proper `--orange-text` AA token (#a85800 light / #ff9838 dark) for small
orange text and uses the charter's `--orange-deep` #cc6100 for the primary hover, whereas the
launcher lacks `--orange-text` and uses #f16e00 for deep. When a newer file diverges from the
launcher toward the charter's exact tokens, the file is right and the launcher is the laggard.
