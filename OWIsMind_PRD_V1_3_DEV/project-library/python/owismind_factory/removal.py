"""Capability removal: probe-based inventory + safe deletion executors.

The guided REMOVAL run (guided.py) deletes everything a capability owns, one
confirmed stage at a time. This module owns the two delicate halves:

- ``build_inventory``: resolve what the capability ACTUALLY owns by probing
  DSS (capability entry + naming conventions + live listings). Nothing is
  assumed from conventions alone: an object enters the inventory only when
  its existence is CONFIRMED. The SOURCE dataset (entry ``lookup_dataset``)
  is listed as PROTECTED and never deletable (user decision 2026-07-22).
- the deletion executors: delete one stage's objects with the identity gate
  (re-read the live name, match it, only then delete), verify disappearance
  by read-back, and report objects the API refused so the guided stage can
  flip to manual instructions.

No persistence and no HTTP here; guided.py drives and persists.
"""

import json

from . import hub

# Stage keys carrying deletable inventory items. catalog_cleanup and
# hub_cleanup have dedicated executors and are not item-based.
DELETE_STAGE_KEYS = ("delete_tool", "delete_agent", "delete_model",
                     "delete_scenario", "delete_recipes", "delete_datasets",
                     "delete_zone")


class RemovalRefused(RuntimeError):
    """The identity/safety gate refused a deletion (never a DSS API error)."""


def safe_delete(handle, expected_name, getter, noun="object", hint="", deleter=None):
    """Delete ``handle`` ONLY after re-reading its live name and matching it.

    Pattern extracted from probes.py (the factory's historical single deletion
    site): a wrong handle must never delete a real object. ``deleter`` lets a
    caller pass extra flags (e.g. ``delete(drop_data=True)`` for datasets).
    """
    live_name = None
    try:
        live_name = getter()
    except Exception:
        pass
    if live_name is None:
        # FAIL-CLOSED: no proof the handle still points at the expected
        # object, so the deletion must not happen.
        raise RemovalRefused(
            "could not re-read the live name of the %s (expected %r): "
            "refusing to delete%s" % (noun, expected_name, hint))
    if live_name != expected_name:
        raise RemovalRefused("refusing to delete %r: expected %s %r"
                             % (live_name, noun, expected_name))
    if deleter is not None:
        deleter()
    else:
        handle.delete()
