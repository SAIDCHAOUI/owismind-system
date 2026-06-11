# Plugin/owismind/tests/test_evidence_throttle.py
"""evidence.throttle: pure per-user token-bucket core (deterministic in ``now``)."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
from owismind.evidence.throttle import take_token  # noqa: E402

CAP = 15
REFILL = 10.0


class TakeTokenTests(unittest.TestCase):
    def test_full_bucket_allows_a_burst_then_denies(self):
        buckets = {}
        # A fresh key starts full: exactly `capacity` requests pass at t=0.
        for i in range(CAP):
            self.assertTrue(take_token(buckets, "u", 0.0, CAP, REFILL), "req %d" % i)
        # The (capacity+1)-th at the same instant is denied (no refill elapsed).
        self.assertFalse(take_token(buckets, "u", 0.0, CAP, REFILL))

    def test_refill_after_elapsed_time_re_allows(self):
        buckets = {}
        for _ in range(CAP):
            take_token(buckets, "u", 0.0, CAP, REFILL)
        self.assertFalse(take_token(buckets, "u", 0.0, CAP, REFILL))
        # 1.0s later, refill=10 tokens/s restores 10 tokens -> 10 more allowed.
        for i in range(10):
            self.assertTrue(take_token(buckets, "u", 1.0, CAP, REFILL), "refilled %d" % i)
        self.assertFalse(take_token(buckets, "u", 1.0, CAP, REFILL))

    def test_fresh_key_starts_full(self):
        buckets = {}
        self.assertTrue(take_token(buckets, "alice", 100.0, CAP, REFILL))
        # An independent key is unaffected by another's spending.
        for _ in range(CAP):
            take_token(buckets, "alice", 100.0, CAP, REFILL)
        self.assertTrue(take_token(buckets, "bob", 100.0, CAP, REFILL))

    def test_tokens_never_exceed_capacity(self):
        buckets = {}
        take_token(buckets, "u", 0.0, CAP, REFILL)        # spend 1 -> 14 left
        # A long idle stretch would refill far past capacity; it must cap at CAP,
        # so only `capacity` requests pass in the next burst (no unbounded credit).
        for i in range(CAP):
            self.assertTrue(take_token(buckets, "u", 10_000.0, CAP, REFILL), "burst %d" % i)
        self.assertFalse(take_token(buckets, "u", 10_000.0, CAP, REFILL))

    def test_meta_then_rows_pair_always_passes(self):
        # The auto-open meta+rows pair (2 tokens back-to-back) must never be denied.
        buckets = {}
        self.assertTrue(take_token(buckets, "u", 0.0, CAP, REFILL))
        self.assertTrue(take_token(buckets, "u", 0.0, CAP, REFILL))


if __name__ == "__main__":
    unittest.main()
