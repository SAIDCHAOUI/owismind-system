"""Opaque keyset-pagination cursor for the conversation list (pure, no dataiku).

A cursor encodes the last row's ``(last_at_iso, session_id)`` so the next page can
resume with a stable, injection-free keyset filter. Decoding is defensive: any
malformed token degrades to ``None`` (treated as 'first page') rather than raising.
"""
import base64

_SEP = "\x1f"  # unit separator: never present in an ISO timestamp or a uuid session id


def encode_cursor(last_at_iso, session_id):
    raw = "{0}{1}{2}".format(last_at_iso, _SEP, session_id)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(token):
    """Return ``(last_at_iso, session_id)`` or ``None`` if absent/malformed."""
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
    except Exception:
        return None
    parts = raw.split(_SEP)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]
