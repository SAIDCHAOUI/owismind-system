"""Resolve the calling user's identity from the browser request (DSS auth).

The WebApp never trusts identity from the request body: the caller is resolved
server-side from the authenticated browser headers via the DSS API client. The
``user_id`` (authIdentifier) is the stable key used to scope chat history per user.
"""

import hashlib
import logging
import threading
import time

import dataiku

logger = logging.getLogger(__name__)


class IdentityError(Exception):
    """Raised when the caller's identity cannot be resolved from the headers."""


# Short-TTL per-process cache of resolved identities. /chat/poll re-resolves the caller
# on every poll (~2 Hz per live chat) and each resolution is a synchronous DSS API
# round-trip that holds a backend worker thread. Caching by a fingerprint of the
# auth-bearing headers (the DSS session cookie) for a few seconds collapses back-to-back
# polls onto one lookup. The TTL is short to bound staleness; only successful lookups are
# cached. Mono-process assumption (same as the rest of the backend).
_AUTH_TTL_SECONDS = 5.0
_AUTH_CACHE_MAX = 512
_auth_cache = {}
_auth_cache_lock = threading.Lock()


def _identity_cache_key(headers):
    """Stable fingerprint of the auth-bearing headers, or None if not cacheable."""
    try:
        cookie = headers.get("Cookie") or headers.get("cookie")
    except Exception:
        cookie = None
    if not cookie:
        return None
    return hashlib.sha256(cookie.encode("utf-8", "ignore")).hexdigest()


def derive_display_name(login):
    """Derive a friendly default display name from a DSS login.

    DSS does NOT return a display name (the auth info has no ``displayName`` key,
    memory L011), but logins follow the ``prenom.nom`` convention. The default
    display name is therefore the capitalised first name - the segment before the
    first dot - title-cased per hyphen group so compound first names read well:

        ``said.chaoui``        -> ``Said``
        ``jean-marc.dupont``   -> ``Jean-Marc``
        ``admin`` (no dot)     -> ``Admin``

    This is only a DEFAULT. A user-facing "set my display name" feature is planned
    but does NOT exist yet; ``admin.record_user`` already COALESCEs on upsert so
    that, once such a feature stores a custom name, it would be preserved instead
    of being reset to this default. Returns ``None`` for an empty login.
    """
    if not login or not str(login).strip():
        return None
    first = str(login).strip().split(".", 1)[0]
    if not first:
        return None
    # Title-case each hyphen-separated segment (jean-marc -> Jean-Marc).
    return "-".join(segment.capitalize() for segment in first.split("-"))


def derive_full_name(login):
    """Derive a 'Prenom Nom' display string from a DSS login.

    DSS returns no display name (L011), but logins follow the 'prenom.nom'
    convention org-wide (confirmed). Title-case every dot/hyphen segment so the
    name reads naturally; a dot-less login degrades to its title-cased self.

        'said.chaoui'        -> 'Said Chaoui'
        'jean-marc.dupont'   -> 'Jean-Marc Dupont'
        'admin'              -> 'Admin'
    """
    if not login or not str(login).strip():
        return None
    segments = [s for s in str(login).strip().split(".") if s]
    if not segments:
        return None
    titled = ["-".join(p.capitalize() for p in seg.split("-")) for seg in segments]
    return " ".join(titled)


def _auth_info(headers):
    """Resolve the browser caller's auth info via the DSS API client.

    A fresh api_client per call: the object is lightweight and this keeps the
    resolution thread-safe under concurrent Flask workers. Header values may
    carry credentials, so they are never logged.
    """
    return dataiku.api_client().get_auth_info_from_browser_headers(dict(headers))


def resolve_identity(headers):
    """Return ``{user_id, display_name, groups}`` for the calling user.

    ``user_id`` is the DSS authIdentifier (login) and is the stable key used to
    scope chat history; ``groups`` defaults to an empty list when absent. Raises
    ``IdentityError`` if the lookup fails or yields no login.

    Results are cached per-process for ``_AUTH_TTL_SECONDS`` keyed on the auth-header
    fingerprint, so rapid back-to-back calls (notably /chat/poll) reuse one DSS lookup.
    """
    cache_key = _identity_cache_key(headers)
    if cache_key is not None:
        now = time.monotonic()
        with _auth_cache_lock:
            entry = _auth_cache.get(cache_key)
            if entry is not None and entry[1] > now:
                return entry[0]

    try:
        info = _auth_info(headers)
    except Exception as exc:  # DSS-side failure: surface as an auth error, no leak
        logger.warning("resolve_identity - auth lookup failed: %s", exc)
        raise IdentityError("auth_lookup_failed") from exc

    user_id = info.get("authIdentifier")
    if not user_id:
        # Log the available KEY NAMES (not values) to diagnose an unexpected shape.
        logger.warning(
            "resolve_identity - no authIdentifier (auth_info_keys=%s)",
            sorted(info.keys()),
        )
        raise IdentityError("no_auth_identifier")

    groups = info.get("groups") or []
    if not isinstance(groups, list):
        groups = [groups]

    # DSS provides no display name (L011); derive a sensible default from the login.
    # This is the INITIAL default; record_user's upsert is written to preserve a
    # custom name if/when a set-name feature stores one (no such route exists yet).
    display_name = derive_display_name(user_id)

    logger.info("resolve_identity - user_id=%s groups=%s", user_id, groups)
    identity = {
        "user_id": user_id,
        "display_name": display_name,
        "groups": groups,
    }

    # Cache the resolved identity (read-only for callers) under a short TTL.
    if cache_key is not None:
        now = time.monotonic()
        with _auth_cache_lock:
            _auth_cache[cache_key] = (identity, now + _AUTH_TTL_SECONDS)
            # Opportunistic eviction so the cache cannot grow unbounded.
            if len(_auth_cache) > _AUTH_CACHE_MAX:
                for key in [k for k, v in _auth_cache.items() if v[1] <= now]:
                    _auth_cache.pop(key, None)
    return identity
