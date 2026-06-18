"""Per-user token-bucket rate gate for the read-only Evidence Studio routes.

The pure core (``take_token``) is dataiku-free and unit-tested; ``can_accept`` is
the thread-safe process-wide wrapper the routes call. Burst-tolerant (capacity
allows the auto-open meta+rows pair and quick interactions) but caps a sustained
scripted flood that could pin worker threads of the mono-process polling backend.
"""
import threading
import time

# Burst capacity and steady refill (tokens/second) per user. meta+rows = 2 tokens,
# a picker open = 1 - all human-paced; only a sustained >REFILL/s flood is denied.
EVIDENCE_BUCKET_CAPACITY = 15
EVIDENCE_REFILL_PER_SEC = 10.0
# Drop idle buckets after this long to bound the dict (mono-process, per-user state).
_BUCKET_TTL_SECONDS = 300

# Separate bucket for the GET /usage budget-status read (profile + chat banner). Its
# own dict so a user actively browsing Evidence never starves the budget refresh and
# vice-versa. The legitimate cadence (init + one read per finished run + Settings open)
# fits comfortably; only a scripted tight loop is denied. Reuses the pure take_token core.
USAGE_BUCKET_CAPACITY = 12
USAGE_REFILL_PER_SEC = 5.0

_lock = threading.Lock()
_buckets = {}  # user_id -> [tokens_float, last_ts]
_usage_buckets = {}  # user_id -> [tokens_float, last_ts] (the /usage read gate)


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


def _evict_stale_locked(buckets, now):
    for key in [k for k, (_t, ts) in buckets.items() if (now - ts) > _BUCKET_TTL_SECONDS]:
        buckets.pop(key, None)


def can_accept(user_id):
    """True if this user may issue one more evidence request now (thread-safe)."""
    now = time.time()
    with _lock:
        _evict_stale_locked(_buckets, now)
        return take_token(_buckets, user_id, now, EVIDENCE_BUCKET_CAPACITY, EVIDENCE_REFILL_PER_SEC)


def usage_can_accept(user_id):
    """True if this user may issue one more GET /usage read now (thread-safe).

    Gates the always-on budget-status endpoint with its own per-user token bucket, so a
    scripted flood of /usage cannot pin the mono-process backend's worker threads or the
    shared SQL connection (the per-request read is O(1) PK lookups, but unbounded volume
    is the failure mode). Independent of the evidence bucket.
    """
    now = time.time()
    with _lock:
        _evict_stale_locked(_usage_buckets, now)
        return take_token(_usage_buckets, user_id, now, USAGE_BUCKET_CAPACITY, USAGE_REFILL_PER_SEC)
