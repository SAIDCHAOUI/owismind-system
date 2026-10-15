"""Admin impersonation ("act as user") for the OWIsMind WebApp - READ-ONLY.

A self-contained, easily removable mechanism: an admin can browse the webapp AS
another user (to consult that user's real interface + conversations for agent
improvement) by carrying a single HTTP header on every API call.

Contract:
  - Header ``X-OWI-Impersonate: <target_user_id>`` is honored ONLY server-side, and
    ONLY when the REAL caller (resolved from the DSS auth headers, never the body) is
    an admin. A non-admin sending the header gets no impersonation (effective user =
    themselves).
  - READ routes scope their data to the EFFECTIVE user (the impersonated target).
  - WRITE routes are BLOCKED while impersonating (consultation only): no sending, no
    feedback, no budget spend under the user's name.

This module is the whole backend surface of the feature: removing it (plus the FENCED
blocks in ``api/routes.py``) reverts impersonation entirely.
"""

import logging

from flask import request

from owismind.security.identity import derive_display_name
from owismind.security.validation import ValidationError, validate_target_user_id
from owismind.storage import admin, sql_config

logger = logging.getLogger(__name__)

# Header the frontend sets (when impersonation is active) on EVERY API call. Honored
# only when the real caller is an admin and the target validates; otherwise ignored.
IMPERSONATION_HEADER = "X-OWI-Impersonate"


def effective_identity(real_identity):
    """Resolve the EFFECTIVE identity for this request from the real caller's identity.

    Reads the ``X-OWI-Impersonate`` header off ``flask.request``. Impersonation is
    granted ONLY when ALL of the following hold:
      - storage is configured (``sql_config.is_configured()``),
      - the header carries a non-empty, length-bounded target id (validated via
        ``validate_target_user_id``),
      - the REAL caller is an admin (``admin.is_admin(real_user_id)``).

    When granted, returns the impersonated identity::

        {"user_id": <target>, "display_name": <derived>, "groups": [],
         "impersonating": True, "real_user_id": <admin>}

    and logs one audit line. Otherwise returns the real identity, annotated::

        {**real_identity, "impersonating": False, "real_user_id": <self>}

    NEVER raises: any error (bad target, storage hiccup, admin-check failure) is treated
    as "not impersonating" and degrades to the real identity. As an optimisation it does
    NOT call ``admin.is_admin`` (a DB round-trip) when no header is present, so normal
    non-impersonated traffic pays no extra cost.
    """
    real_user_id = real_identity.get("user_id")

    # Fast path: no header -> never touch the DB; the caller acts as themselves.
    try:
        header_value = request.headers.get(IMPERSONATION_HEADER)
    except Exception:
        header_value = None
    if not header_value or not str(header_value).strip():
        return {**real_identity, "impersonating": False, "real_user_id": real_user_id}

    # A header is present: honor it only for a configured store + an admin caller + a
    # well-formed target. Any failure -> fall back to the real identity (never raise).
    try:
        if not sql_config.is_configured():
            return {**real_identity, "impersonating": False, "real_user_id": real_user_id}
        target = validate_target_user_id(header_value)
        if not admin.is_admin(real_user_id):
            return {**real_identity, "impersonating": False, "real_user_id": real_user_id}
    except ValidationError:
        return {**real_identity, "impersonating": False, "real_user_id": real_user_id}
    except Exception:
        logger.exception("impersonation - effective_identity check failed; acting as self")
        return {**real_identity, "impersonating": False, "real_user_id": real_user_id}

    # Granted: act as the target (read-only is enforced by the route-level write block).
    logger.info(
        "impersonation - admin %s acting as %s", real_user_id, target
    )
    return {
        "user_id": target,
        "display_name": derive_display_name(target),
        "groups": [],
        "impersonating": True,
        "real_user_id": real_user_id,
    }
