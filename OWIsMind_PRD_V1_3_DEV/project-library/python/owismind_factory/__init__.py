"""owismind_factory - programmatic creation of OWIsMind dataset-specialist sub-agents.

This package is the engine behind the "agent factory": it automates, through the
OFFICIAL Dataiku public Python API only, the chain

    source table -> Flow zone + knowledge recipes/datasets -> semantic model
    -> Semantic Model Query tool -> Code Agent -> orchestrator registration

Design rules (do not break):
- stdlib + ``dataiku`` only, Python 3.9 compatible (runs in notebooks AND in the
  Standard webapp backend).
- Read-only by default: every mutating call goes through a FactoryContext that is
  ``dry_run=True`` unless explicitly flipped, and records every action.
- Idempotent ``ensure_*`` steps: existing objects are reused, never recreated.
- NO deletion helpers. The only deletions in this package are the Phase 0 write
  probe removing the throwaway objects it just created, behind an explicit flag.
- Undocumented API surfaces (Code Agent source injection, Semantic Model Query
  tool params) are GATED: the caller must pass discovery results produced by the
  Phase 0 probe (``probes.run_read_probes``); without them the factory degrades
  to a precise manual checklist instead of guessing.

Deployment: this folder is pasted into the DSS project library (python/) of the
OWIsMind project, next to the ``/python/owismind_hub/`` config tree (see ``hub.py``).
"""

__version__ = "0.1.0"

from .fctx import FactoryContext  # noqa: F401
from .spec import DomainSpec      # noqa: F401
