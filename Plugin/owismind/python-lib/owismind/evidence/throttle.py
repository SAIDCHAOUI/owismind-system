"""Per-user token-bucket rate gate for the read-only Evidence Studio routes.

The pure core (``take_token``) is dataiku-free and unit-tested; ``can_accept`` is
the thread-safe process-wide wrapper the routes call. Burst-tolerant (capacity
allows the auto-open meta+rows pair and quick interactions) but caps a sustained
scripted flood that could pin worker threads of the mono-process polling backend.
"""
import threading
import time

# Burst capacity and steady refill (tokens/second) per user. meta+rows = 2 tokens,
# a picker open = 1 — all human-paced; only a sustained >REFILL/s flood is denied.
EVIDENCE_BUCKET_CAPACITY = 15
EVIDENCE_REFILL_PER_SEC = 10.0
# Drop idle buckets after this long to bound the dict (mono-process, per-user state).
_BUCKET_TTL_SECONDS = 300

_lock = threading.Lock()
_buckets = {}  # user_id -> [tokens_float, last_ts]


def take_token(buckets, key, now, capacity, refill_per_sec):
    """Pure token-bucket step. Mutates ``buckets`` in place; returns True if allowed.

    A bucket starts full. Tokens refill linearly (capped at capacity) since the last
    call; one token is consumed per allowed request. Deterministic in ``now`` for tests.
    """
    tokens, last = buckets.get(key, (float(capacity), now))
    tokens = min(float(capacity), tokens + max(0.0, now - last) * refill_per_sec)
    if tokens >= 1.0:
        buckets[key] = (tokens - 1.0, now)
        return True
    buckets[key] = (tokens, now)
    return False


def _evict_stale_locked(now):
    for key in [k for k, (_t, ts) in _buckets.items() if (now - ts) > _BUCKET_TTL_SECONDS]:
        _buckets.pop(key, None)


def can_accept(user_id):
    """True if this user may issue one more evidence request now (thread-safe)."""
    now = time.time()
    with _lock:
        _evict_stale_locked(now)
        return take_token(_buckets, user_id, now, EVIDENCE_BUCKET_CAPACITY, EVIDENCE_REFILL_PER_SEC)
