"""Workspace protocol v1 (V2.0): the orchestrator's plan / notes / widgets / provenance.

The orchestrator Code Agent drives the user's workspace through ONE event kind
(``eventKind == "WORKSPACE"``) whose ``eventData`` carries a versioned operation
(``plan.set | plan.step | note.add | widget.add | prov.set``). This package is the
backend side of that contract (``contracts/workspace_protocol.v1.json``):

  - ``protocol`` : constants mirrored from the contract + ``normalize_op`` (strict
                   projection, caps, never raises);
  - ``reducer``  : pure state machine ``empty_state`` / ``apply`` / ``finalize`` /
                   ``sanitize`` - same semantics as the frontend reducer, both pinned
                   by the shared fixtures under ``contracts/fixtures/``;
  - ``resolve``  : read-time join of a stored workspace with the exchange's captured
                   SQL items (by ``sql_id``) for ``GET /workspace``.

Pure stdlib (Python 3.9), except ``resolve`` which reuses the Evidence helpers.
"""
