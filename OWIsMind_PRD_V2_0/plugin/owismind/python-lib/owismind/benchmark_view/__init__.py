"""Plugin-side READ of the agent benchmark.

The benchmark is produced by a separate DSS project (OWIsMind_LAB) into a SQL ``scored`` table.
This package lets the plugin webapp consult those results (for any user, via an agent dropdown)
and lets an admin review/override the judge verdicts, WITHOUT importing the LAB project library:
the pure shaping (aggregate / schemas / schema_check / agent_profile) is a small, self-contained
copy of the LAB contracts, and lab_io is the only DSS-touching module (bounded cross-project SQL).
"""
