"""Tests for benchmark.history (pure run-history merge + cap). Stdlib only, no DSS."""

import unittest

from benchmark import history


def _row(run_id, ts, q="q"):
    return {"run_id": run_id, "run_timestamp": ts, "question_id": q}


class TestMergeRunHistory(unittest.TestCase):
    def test_appends_new_run_keeping_old(self):
        existing = [_row("r1", "2026-01-01"), _row("r1", "2026-01-01", "q2")]
        new = [_row("r2", "2026-01-02")]
        out = history.merge_run_history(existing, new)
        self.assertEqual(len(out), 3)
        self.assertEqual([r["run_id"] for r in out], ["r1", "r1", "r2"])

    def test_same_run_id_replaces_prior_rows(self):
        # Re-running a run_id (idempotent re-judge/aggregate) drops its old rows.
        existing = [_row("r1", "2026-01-01", "q1"), _row("r2", "2026-01-02", "q1")]
        new = [_row("r1", "2026-01-01", "q1"), _row("r1", "2026-01-01", "q2")]
        out = history.merge_run_history(existing, new)
        # r2 kept once; r1 fully replaced by the two new rows.
        self.assertEqual([r["run_id"] for r in out], ["r2", "r1", "r1"])
        self.assertEqual(sum(1 for r in out if r["run_id"] == "r1"), 2)

    def test_empty_inputs(self):
        self.assertEqual(history.merge_run_history(None, None), [])
        self.assertEqual(history.merge_run_history([], [_row("r1", "t")]), [_row("r1", "t")])
        self.assertEqual(history.merge_run_history([_row("r1", "t")], []), [_row("r1", "t")])


class TestRunsToKeep(unittest.TestCase):
    def setUp(self):
        # Three runs, distinct timestamps; r3 newest, r1 oldest.
        self.rows = [
            _row("r1", "2026-01-01"), _row("r1", "2026-01-01", "q2"),
            _row("r2", "2026-01-02"),
            _row("r3", "2026-01-03"),
        ]

    def test_none_keeps_all(self):
        self.assertEqual(history.runs_to_keep(self.rows, None), {"r1", "r2", "r3"})

    def test_zero_and_negative_keep_all(self):
        self.assertEqual(history.runs_to_keep(self.rows, 0), {"r1", "r2", "r3"})
        self.assertEqual(history.runs_to_keep(self.rows, -5), {"r1", "r2", "r3"})

    def test_cap_keeps_most_recent(self):
        self.assertEqual(history.runs_to_keep(self.rows, 2), {"r2", "r3"})
        self.assertEqual(history.runs_to_keep(self.rows, 1), {"r3"})

    def test_cap_at_or_above_count_keeps_all(self):
        self.assertEqual(history.runs_to_keep(self.rows, 3), {"r1", "r2", "r3"})
        self.assertEqual(history.runs_to_keep(self.rows, 99), {"r1", "r2", "r3"})

    def test_malformed_cap_keeps_all(self):
        self.assertEqual(history.runs_to_keep(self.rows, "abc"), {"r1", "r2", "r3"})

    def test_empty_rows(self):
        self.assertEqual(history.runs_to_keep([], 2), set())

    def test_ranks_by_timestamp_not_insertion_order(self):
        rows = [_row("old", "2026-01-01"), _row("new", "2026-12-31"), _row("mid", "2026-06-15")]
        self.assertEqual(history.runs_to_keep(rows, 2), {"new", "mid"})


if __name__ == "__main__":
    unittest.main()
