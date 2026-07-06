#!/usr/bin/env bash
# OWIsMind PostToolUse dash-guard: after an Edit/Write/MultiEdit/NotebookEdit, warn if the target file
# contains a banned em dash (U+2014) or en dash (U+2013). Exit 2 feeds the warning back to Claude so it
# fixes them. ANY internal error exits 0 so a session is never broken. Pure bash + python3 (no jq).
set -uo pipefail

payload="$(cat)"

printf '%s' "$payload" | python3 -c '
import sys, json, os
try:
    data = json.load(sys.stdin)
    fp = (data.get("tool_input") or {}).get("file_path")
    if not fp or not os.path.isfile(fp):
        sys.exit(0)
    # memory/LESSONS.md is the one documented exception: L084/L093 quote the banned
    # glyphs as the subject of the rule itself (code samples where the char is the operand).
    if fp.replace(os.sep, "/").endswith("memory/LESSONS.md"):
        sys.exit(0)
    with open(fp, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    n_em = text.count("\u2014")
    n_en = text.count("\u2013")
    if n_em or n_en:
        try:
            name = os.path.relpath(fp)
        except Exception:
            name = fp
        sys.stderr.write(
            "OWIsMind dash-guard: %s contains %d em dash (U+2014) and %d en dash (U+2013). "
            "These are banned everywhere (rule #9). Replace them with -, :, , or parentheses.\n"
            % (name, n_em, n_en)
        )
        sys.exit(2)
    sys.exit(0)
except SystemExit:
    raise
except Exception:
    sys.exit(0)
'
exit $?
