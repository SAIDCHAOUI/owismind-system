"""OWIsMind agent benchmark and evaluation package.

Source of truth at the repo (recolled into the DSS project OWIsMind_LAB as a
project library). Pure-logic modules (schemas, config, agent_capture, judge,
scoring) import with the stdlib only so the NO INSTALL test environment can run
them. Anything heavy (dataiku, pandas) is imported lazily inside functions.

Design contract: docs/superpowers/specs/2026-06-24-agent-benchmark-evaluation-design.md
"""
