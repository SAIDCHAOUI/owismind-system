#!/usr/bin/env python3
"""Promote the OWIsMind agent files from OWISMIND_DEV to OWISMIND_PROD_V1.

Regenerates every OWISMIND_PROD_V1_* deployable from its OWISMIND_DEV_* source,
which guarantees functional parity with DEV by construction:

  1. copy the DEV file,
  2. apply the per-project id substitutions (PROD ids baked in below),
  3. orchestrator only: surgically remove the tickets_expert capability block
     (the tickets agent is intentionally absent from PROD until validated;
     BUSINESS_DOMAINS keeps "tickets" so PROD still gives the honest
     "no agent for this domain yet" answer).

After regeneration the residual DEV<->PROD diff of each file must be exactly:
deploy-target headers + id lines + the tickets block. The script prints those
diffs for review, refuses to write on any unexpected state (marker not found,
DEV id surviving in a PROD file, em/en dash glyphs), and compile-checks the
generated files.

NOT covered (update by hand when they change): registry.json (bump
"last_reviewed" and mirror any capability change), the per-project
semantic_model README/MODEL.md, and the semantic_model helper scripts that keep
a per-project copy but are not promoted here (drop_column_and_reindex.py,
dump_semantic_model.py). The id map lives in OWISMIND/README.md; if an id ever
changes in DSS, update the substitution tables below first.

Usage: python3 tools/promote_agents_to_prod.py
"""
import io
import os
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "dataiku-agents", "OWISMIND")
DEV = os.path.join(ROOT, "OWISMIND_DEV")
PROD = os.path.join(ROOT, "OWISMIND_PROD_V1")

# Per-file substitution maps: DEV token -> PROD token. Applied globally
# (comments included) so no DEV id can survive anywhere in a PROD file.
ORCH_SUBS = [
    ("# DEPLOY TARGET: project OWISMIND_DEV", "# DEPLOY TARGET: project OWISMIND_PROD_V1"),
    ("OWIsMind_orchestrator = 038G7mlF", "OWIsMind_orchestrator = Xrv7GvfG"),
    ("agent:bHrWLyOL", "agent:uO5hEzAs"),
    ('LOOKUP_TOOL_ID = "UUoynaL"', 'LOOKUP_TOOL_ID = "szOZCoU"'),
    # PROD has no tickets entry, so the revenue comment must not point "below".
    ("Revenue keeps the full search (validated); see tickets below.",
     "Revenue keeps the full search (validated)."),
]
EXPERT_SUBS = [
    ("# DEPLOY TARGET: project OWISMIND_DEV", "# DEPLOY TARGET: project OWISMIND_PROD_V1"),
    ("SalesDrive_revenue_expert = bHrWLyOL", "SalesDrive_revenue_expert = uO5hEzAs"),
    ("v4oqA6R", "sgk5pfln"),
]
TOOL_SUBS = [
    ("# DEPLOY TARGET: project OWISMIND_DEV", "# DEPLOY TARGET: project OWISMIND_PROD_V1"),
    ("attribute_lookup = UUoynaL", "attribute_lookup = szOZCoU"),
]
SEM_SUBS = [
    ('NEW_MODEL_ID = "AHUh9hb"', 'NEW_MODEL_ID = "a7K9jYk"'),
    # Generic: covers the header comment, get_project(...) and PHYSICAL_TABLE.
    ("OWISMIND_DEV", "OWISMIND_PROD_V1"),
]

# Every DEV-only identifier that must NEVER appear in a PROD file.
DEV_IDS = ["038G7mlF", "bHrWLyOL", "NcE9LD2i", "UUoynaL", "v4oqA6R",
           "nEirlso", "AHUh9hb", "dM4jA4G", "OWISMIND_DEV"]

TICKETS_START = "    # --- Incident tickets (TroubleTickets_year) "
TICKETS_END = "    # Adding a sub-agent (e.g. another domain expert) is one more entry here."

# (dev relative path, prod relative path, substitutions, drop tickets block)
FILES = [
    ("agents/OWISMIND_DEV_OWIsMind_orchestrator.py",
     "agents/OWISMIND_PROD_V1_OWIsMind_orchestrator.py", ORCH_SUBS, True),
    ("agents/OWISMIND_DEV_SalesDrive_revenue_expert.py",
     "agents/OWISMIND_PROD_V1_SalesDrive_revenue_expert.py", EXPERT_SUBS, False),
    ("tools/OWISMIND_DEV_attribute_lookup_tool.py",
     "tools/OWISMIND_PROD_V1_attribute_lookup_tool.py", TOOL_SUBS, False),
    ("semantic_model/update_aligned_semantic_model.py",
     "semantic_model/update_aligned_semantic_model.py", SEM_SUBS, False),
]


def read(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(text)


def drop_tickets_block(text):
    """Remove the tickets_expert CAPABILITIES entry (comment included)."""
    lines = text.splitlines(True)
    start = end = None
    for i, line in enumerate(lines):
        if line.startswith(TICKETS_START) and start is None:
            start = i
        if line.startswith(TICKETS_END):
            end = i
    if start is None or end is None or end <= start:
        sys.exit("FATAL: tickets block markers not found (start=%s end=%s)" % (start, end))
    removed = lines[start:end]
    if not any('"tickets_expert"' in l for l in removed):
        sys.exit("FATAL: removed block does not contain the tickets_expert entry")
    return "".join(lines[:start] + lines[end:]), len(removed)


def promote(src, dst, subs, drop_tickets):
    text = read(src)
    dropped = 0
    if drop_tickets:
        text, dropped = drop_tickets_block(text)
    for a, b in subs:
        if a not in text:
            sys.exit("FATAL: substitution source not found in %s: %r" % (src, a))
        text = text.replace(a, b)
    for bad in DEV_IDS:
        if bad in text:
            sys.exit("FATAL: DEV id %r still present in generated %s" % (bad, dst))
    # Needles built from codepoints so this file itself stays free of the
    # banned glyphs (project rule #9).
    for dash, name in ((u"\u2014", "em dash"), (u"\u2013", "en dash")):
        if dash in text:
            sys.exit("FATAL: %s found in generated %s" % (name, dst))
    write(dst, text)
    print("OK  %s  (tickets lines removed: %d)" % (os.path.relpath(dst, ROOT), dropped))


def main():
    for dev_rel, prod_rel, subs, drop in FILES:
        promote(os.path.join(DEV, dev_rel), os.path.join(PROD, prod_rel), subs, drop)

    print("\n=== RESIDUAL DIFFS (must be: headers + ids + tickets block ONLY) ===")
    for dev_rel, prod_rel, _, _ in FILES:
        print("\n--- %s ---" % os.path.basename(dev_rel))
        p = subprocess.run(["diff", os.path.join(DEV, dev_rel), os.path.join(PROD, prod_rel)],
                           capture_output=True, text=True)
        sys.stdout.write(p.stdout or "(no diff)\n")

    import py_compile
    for _, prod_rel, _, _ in FILES:
        py_compile.compile(os.path.join(PROD, prod_rel), doraise=True)
    print("\npy_compile: %d/%d OK" % (len(FILES), len(FILES)))
    print("Reminder: bump registry.json last_reviewed + re-paste the 4 files in DSS "
          "(Code Agents env 3.11, tool, notebook script). Id map: OWISMIND/README.md.")


if __name__ == "__main__":
    main()
