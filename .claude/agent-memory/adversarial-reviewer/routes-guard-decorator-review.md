---
name: routes-guard-decorator-review
description: How to prove behavioural neutrality of api/routes.py guard refactors, and which routes keep an INLINE impersonation fence outside the guard decorator
metadata:
  type: project
---

`api/routes.py` centralises the per-route guard sequence in a `guard(name=, impersonate=,
require_storage=, bootstrap_chat_table=, throttle=, require_admin=)` decorator (added
2026-08-06 on `OWIsMind_PRD_V1_3-dev`), with three presets: `evidence_guard`,
`source_guard`, `admin_guard`. The guarded view receives the resolved identity as its
FIRST positional arg; Flask URL params are forwarded after it.

**The guard is NOT the only impersonation site.** Six routes deliberately keep an inline
fenced block and are not decorated: `me` (swap), `track_events` (drop), `chat_stop`
(block), `catalog_projects` / `catalog_datasets` (swap), `admin_benchmark_override`
(block, AFTER `admin_guard` because that was the original order). Twelve routes still call
`resolve_identity` inline. So a claim like "identity/impersonation is enforced in ONE
place" is an overstatement: when auditing an impersonation removal, delete the module plus
EVERY `--- BEGIN/END impersonation ---` fence, not just the one inside `guard`.

**Ordering contract to check on any change:** identity (401) -> impersonation
(403 `impersonation_read_only` on writes / swap on reads) -> `require_storage` (409) ->
`ensure_chat_table` (500 `storage_unavailable`) -> throttle (429) -> admin (403
`forbidden`). Two deliberate exceptions: `/usage` keeps its throttle INLINE because it uses
`evidence_throttle.usage_can_accept`, not `can_accept`; `/chat/start` keeps `is_configured`
INLINE after payload validation, so a malformed body is 400 even on an unconfigured
instance (`/chat/feedback`, `/benchmark/suggest`, `/feedback/submit` are the opposite: 409
before validation).

**Proof method that works here (no Flask installed, NO INSTALL rule).** `tests/_dss_stub.py`
stubs `dataiku` + a minimal `flask` where `Blueprint.route` is identity and `jsonify` returns
the payload, so views are directly callable and return `dict` or `(dict, status)`. Load the
HEAD file as a SECOND module with `importlib.util.spec_from_file_location` (its imports are
absolute, so it loads fine next to the working-tree one), patch `resolve_identity` /
`ensure_chat_table` on BOTH modules (they are name bindings) while shared module objects
(`sql_config`, `impersonation`, `admin`, `evidence_throttle`) need patching only once, attach
a logging handler to both `logger`s, then compare `(status, body, log lines, observed call
sequence)` over a CARTESIAN product of the guard knobs. 8192 scenarios ran in seconds and is
strictly stronger than reading the diff. Because both versions import the same working-tree
copies of every other module, concurrent edits by other agents cancel out.

**Endpoint names:** `functools.wraps` is load-bearing - without it every guarded view would
be named `guarded` and real Flask would refuse the second `add_url_rule`. Flask is not
installed, so verify by asserting `getattr(routes, view).__name__` is unique across the 44
routed views. See [[security-invariants]] and [[verifying-zero-behavior-cleanup]].
