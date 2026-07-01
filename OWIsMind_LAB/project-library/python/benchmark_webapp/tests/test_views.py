"""benchmark_webapp.views - pure shaping + config validation (no DSS runtime).

Run from the repo root: ``python3 -m unittest discover \
-s OWIsMind_LAB/project-library/python/benchmark_webapp/tests \
-t OWIsMind_LAB/project-library/python``.
"""
import os
import sys
import unittest

# Two levels up from this test file is the library root that holds both the `benchmark` and
# `benchmark_webapp` packages (mirrors the DSS project library `python/`), so it self-bootstraps
# wherever the package tree is moved, as long as the two packages stay siblings.
_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
sys.path.insert(0, _LIB_ROOT)

from benchmark_webapp import views  # noqa: E402


class FormatTests(unittest.TestCase):
    def test_pct(self):
        self.assertEqual(views.fmt_pct(0.825), "82.5 %")
        self.assertEqual(views.fmt_pct(0), "0.0 %")
        self.assertEqual(views.fmt_pct(None), "-")
        self.assertEqual(views.fmt_pct("nope"), "-")

    def test_money(self):
        self.assertEqual(views.fmt_money(1.2345), "$1.2345")
        self.assertEqual(views.fmt_money2(12.5), "$12.50")
        self.assertEqual(views.fmt_money(None), "-")

    def test_secs(self):
        self.assertEqual(views.fmt_secs(1.43), "1.4 s")
        self.assertEqual(views.fmt_secs(None), "-")


class BenchmarkSelectorTests(unittest.TestCase):
    def test_latest_and_options(self):
        rows = [
            {"benchmark_id": "a", "benchmark_name": "A", "last_run_timestamp": "2026-06-25T10:00:00"},
            {"benchmark_id": "b", "benchmark_name": "B", "last_run_timestamp": "2026-06-25T12:00:00"},
            {"benchmark_id": "a", "benchmark_name": "A", "last_run_timestamp": "2026-06-25T10:00:00"},
        ]
        self.assertEqual(views.latest_benchmark_id(rows), "b")
        opts = views.benchmark_options(rows)
        self.assertEqual([o["benchmark_id"] for o in opts], ["b", "a"])
        self.assertEqual(opts[0]["benchmark_name"], "B")

    def test_empty(self):
        self.assertEqual(views.latest_benchmark_id([]), "")
        self.assertEqual(views.benchmark_options(None), [])


class SummaryViewTests(unittest.TestCase):
    def _rows(self):
        return [
            {"benchmark_id": "B1", "benchmark_name": "said", "last_run_timestamp": "t",
             "agent_key": "orch", "agent_label": "Orch",
             "mode": "Smart", "n_questions": 10, "n_ok": 10, "n_error": 0, "error_rate": 0.0,
             "accuracy": 0.8, "mean_score": 4.2, "latency_p50_s": 1.0, "latency_p95_s": 2.0,
             "avg_cost_per_q": 0.01, "total_cost": 0.10, "needs_review_count": 1,
             "judge_total_cost": 0.02},
            {"benchmark_id": "B1", "benchmark_name": "said", "last_run_timestamp": "t",
             "agent_key": "orch", "agent_label": "Orch",
             "mode": "Claude", "n_questions": 10, "n_ok": 10, "n_error": 0, "error_rate": 0.0,
             "accuracy": 0.5, "mean_score": 3.0, "latency_p50_s": 4.0, "latency_p95_s": 8.0,
             "avg_cost_per_q": 0.05, "total_cost": 0.50, "needs_review_count": 2,
             "judge_total_cost": 0.03},
            # a row from another benchmark, must be filtered out when benchmark_id=B1
            {"benchmark_id": "B0", "agent_label": "Orch", "mode": "Smart", "n_ok": 10, "accuracy": 1.0},
        ]

    def test_global_accuracy_weighted(self):
        out = views.summary_view(self._rows(), benchmark_id="B1")
        # 8 correct + 5 correct over 20 ok = 0.65
        self.assertAlmostEqual(out["kpis"]["accuracy"], 0.65, places=6)
        self.assertEqual(out["kpis"]["accuracy_pct"], "65.0 %")
        self.assertEqual(out["kpis"]["n_questions"], 10)
        self.assertEqual(out["kpis"]["n_configs"], 2)
        self.assertEqual(out["kpis"]["needs_review"], 3)
        self.assertEqual(out["kpis"]["total_cost_str"], "$0.60")
        self.assertEqual(out["benchmark_id"], "B1")
        self.assertEqual(out["benchmark_name"], "said")

    def test_rows_sorted_by_accuracy_desc(self):
        out = views.summary_view(self._rows(), benchmark_id="B1")
        self.assertEqual([r["mode"] for r in out["rows"]], ["Smart", "Claude"])
        self.assertEqual(out["rows"][0]["accuracy_pct"], "80.0 %")

    def test_latest_when_no_benchmark_id(self):
        # No benchmark_id -> latest by timestamp; B1 has 't', B0 has none -> B1 wins.
        out = views.summary_view(self._rows())
        self.assertEqual(out["benchmark_id"], "B1")


class BreakdownViewTests(unittest.TestCase):
    def test_shape(self):
        rows = [
            {"benchmark_id": "B1", "agent_label": "Orch", "mode": "Smart", "dimension": "category",
             "bucket": "revenus", "n": 5, "accuracy": 0.8, "mean_score": 4.0},
            {"benchmark_id": "B1", "agent_label": "Orch", "mode": "Smart", "dimension": "category",
             "bucket": "tickets", "n": 5, "accuracy": 0.4, "mean_score": 3.0},
        ]
        out = views.breakdown_view(rows, benchmark_id="B1")
        self.assertEqual(len(out["rows"]), 2)
        self.assertEqual(out["rows"][0]["bucket"], "revenus")
        self.assertEqual(out["rows"][0]["accuracy_pct"], "80.0 %")


def _drow(**over):
    base = {
        "benchmark_id": "B1", "benchmark_name": "said", "attempt_no": 1, "run_id": "r1",
        "run_timestamp": "2026-06-29T10:00:00Z", "question_id": "Q1", "question": "q1",
        "agent_key": "orch", "agent_label": "Orch", "mode": "Smart", "status": "ok",
        "objective_match": "hit", "judge_score": 5, "judge_verdict": "correct", "correct": True,
        "needs_review": False, "answer_text": "a", "latency_total_s": 1.0, "estimated_cost": 0.01,
    }
    base.update(over)
    return base


class DetailViewTests(unittest.TestCase):
    def _rows(self):
        return [
            _drow(question_id="Q1", judge_score=5, correct=True, needs_review=False,
                  answer_text="a" * 500),
            _drow(question_id="Q2", objective_match="miss", judge_score=2,
                  judge_verdict="incorrect", correct=False, needs_review=True,
                  answer_text="b", latency_total_s=2.0, estimated_cost=0.02),
        ]

    def test_needs_review_first_and_preview_trimmed(self):
        out = views.detail_view(self._rows(), benchmark_id="B1")
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["rows"][0]["question_id"], "Q2")  # needs_review sorts first
        self.assertTrue(out["rows"][0]["needs_review"])
        self.assertLessEqual(len(out["rows"][1]["answer_preview"]), 280)
        # v2: each row carries its evolution (single attempt -> 'first').
        self.assertEqual(out["rows"][0]["n_attempts"], 1)
        self.assertEqual(out["rows"][0]["delta"], "first")

    def test_only_needs_review_filter(self):
        out = views.detail_view(self._rows(), benchmark_id="B1", only_needs_review=True)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["rows"][0]["question_id"], "Q2")

    def test_limit_keeps_needs_review_first(self):
        out = views.detail_view(self._rows(), benchmark_id="B1", limit=1)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["rows"][0]["question_id"], "Q2")
        self.assertTrue(out["rows"][0]["needs_review"])

    def test_latest_attempt_wins(self):
        # Two attempts of Q1: attempt 2 (correct) supersedes attempt 1 (incorrect).
        rows = [
            _drow(question_id="Q1", attempt_no=1, correct=False, judge_verdict="incorrect",
                  run_id="r1", run_timestamp="2026-06-29T10:00:00Z"),
            _drow(question_id="Q1", attempt_no=2, correct=True, judge_verdict="correct",
                  run_id="r2", run_timestamp="2026-06-30T10:00:00Z"),
        ]
        out = views.detail_view(rows, benchmark_id="B1")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["rows"][0]["attempt_no"], 2)
        self.assertTrue(out["rows"][0]["effective_correct"])
        self.assertEqual(out["rows"][0]["n_attempts"], 2)
        self.assertEqual(out["rows"][0]["delta"], "improved")

    def test_surfaces_judge_comment_and_reference_fields(self):
        out = views.detail_view(self._rows(), benchmark_id="B1")
        row = next(r for r in out["rows"] if r["question_id"] == "Q1")
        for key in ("agent_key", "run_id", "attempt_no", "judge_comment", "human_verdict",
                    "human_comment", "reviewed_by", "notes", "expected_value", "expected_sql",
                    "expected_tool", "actual_tools", "effective_correct", "effective_verdict",
                    "overridden"):
            self.assertIn(key, row)

    def test_effective_verdict_reflects_human_override(self):
        rows = [_drow(question_id="Q9", objective_match="miss", judge_score=2,
                      judge_verdict="incorrect", correct=False, needs_review=True,
                      human_verdict="correct", human_comment="magnitude is fine",
                      reviewed_by="u_admin", answer_text="b", judge_comment="off by a lot")]
        out = views.detail_view(rows, benchmark_id="B1")
        row = out["rows"][0]
        self.assertTrue(row["effective_correct"])
        self.assertEqual(row["effective_verdict"], "correct")
        self.assertTrue(row["overridden"])
        self.assertEqual(row["judge_comment"], "off by a lot")
        self.assertEqual(row["human_comment"], "magnitude is fine")


class ReviewViewTests(unittest.TestCase):
    def test_lists_all_attempts(self):
        # review_view does NOT reduce to latest: a reviewer overrides a specific attempt.
        rows = [
            _drow(question_id="Q1", attempt_no=1, correct=False, run_id="r1",
                  run_timestamp="2026-06-29T10:00:00Z"),
            _drow(question_id="Q1", attempt_no=2, correct=True, run_id="r2",
                  run_timestamp="2026-06-30T10:00:00Z"),
        ]
        out = views.review_view(rows, benchmark_id="B1")
        self.assertEqual(out["count"], 2)
        # newest attempt first within the question
        self.assertEqual([r["attempt_no"] for r in out["rows"]], [2, 1])
        self.assertEqual(out["rows"][0]["run_id"], "r2")


class OverrideTests(unittest.TestCase):
    def _scored(self):
        return [
            {"run_id": "r1", "question_id": "Q1", "agent_key": "orch", "mode": "Smart",
             "correct": False, "human_verdict": ""},
            {"run_id": "r1", "question_id": "Q2", "agent_key": "orch", "mode": "Smart",
             "correct": True, "human_verdict": ""},
        ]

    def test_validate_override_requires_key_and_verdict(self):
        ok, errors = views.validate_override({"run_id": "", "question_id": "Q1",
                                              "agent_key": "orch", "verdict": "correct"})
        self.assertFalse(ok)
        ok, errors = views.validate_override({"run_id": "r1", "question_id": "Q1",
                                              "agent_key": "orch", "verdict": "maybe"})
        self.assertFalse(ok)
        ok, errors = views.validate_override({"run_id": "r1", "question_id": "Q1",
                                              "agent_key": "orch", "mode": "Smart",
                                              "verdict": "correct"})
        self.assertTrue(ok, errors)

    def test_apply_override_sets_human_fields_on_match(self):
        payload = {"run_id": "r1", "question_id": "Q1", "agent_key": "orch", "mode": "Smart",
                   "verdict": "correct", "comment": "magnitude ok",
                   "reviewed_by": "u_admin", "reviewed_at": "2026-06-29T10:00:00Z"}
        rows, matched = views.apply_override(self._scored(), payload)
        self.assertEqual(matched, 1)
        q1 = next(r for r in rows if r["question_id"] == "Q1")
        self.assertEqual(q1["human_verdict"], "correct")
        self.assertTrue(q1["human_correct"])
        self.assertEqual(q1["human_comment"], "magnitude ok")
        self.assertEqual(q1["reviewed_by"], "u_admin")
        # The untouched row keeps its empty override.
        q2 = next(r for r in rows if r["question_id"] == "Q2")
        self.assertEqual(q2["human_verdict"], "")

    def test_apply_override_incorrect_sets_false(self):
        payload = {"run_id": "r1", "question_id": "Q2", "agent_key": "orch", "mode": "Smart",
                   "verdict": "incorrect", "reviewed_by": "u", "reviewed_at": "t"}
        rows, matched = views.apply_override(self._scored(), payload)
        q2 = next(r for r in rows if r["question_id"] == "Q2")
        self.assertEqual(q2["human_verdict"], "incorrect")
        self.assertFalse(q2["human_correct"])

    def test_apply_override_clear_resets_fields(self):
        scored = self._scored()
        scored[0].update({"human_verdict": "correct", "human_correct": True,
                          "human_comment": "x", "reviewed_by": "u", "reviewed_at": "t"})
        payload = {"run_id": "r1", "question_id": "Q1", "agent_key": "orch", "mode": "Smart",
                   "verdict": "", "reviewed_by": "u2", "reviewed_at": "t2"}
        rows, matched = views.apply_override(scored, payload)
        q1 = next(r for r in rows if r["question_id"] == "Q1")
        self.assertEqual(q1["human_verdict"], "")
        self.assertIsNone(q1["human_correct"])
        self.assertEqual(q1["human_comment"], "")

    def test_apply_override_no_match_returns_zero(self):
        payload = {"run_id": "r1", "question_id": "ZZ", "agent_key": "orch", "mode": "Smart",
                   "verdict": "correct", "reviewed_by": "u", "reviewed_at": "t"}
        rows, matched = views.apply_override(self._scored(), payload)
        self.assertEqual(matched, 0)


class PromotionTests(unittest.TestCase):
    def test_safe_table_name(self):
        self.assertEqual(
            views.safe_table_name("OWISMIND_DEV_owismind_webapp_golden_suggestions_v1"),
            "OWISMIND_DEV_owismind_webapp_golden_suggestions_v1",
        )
        self.assertIsNone(views.safe_table_name('x"; DROP TABLE y; --'))
        self.assertIsNone(views.safe_table_name(None))
        self.assertIsNone(views.safe_table_name("a b"))

    def test_suggestion_to_golden_requires_reference(self):
        self.assertIsNone(views.suggestion_to_golden(
            {"suggestion_id": "s1", "question": "q", "reference_answer": ""}))
        self.assertIsNone(views.suggestion_to_golden(
            {"suggestion_id": "s1", "question": "", "reference_answer": "r"}))

    def test_minted_question_id_stable_and_matches_golden(self):
        sid = "abc123def4567890aaaabbbbcccc"  # 28-char id
        qid = views.minted_question_id(sid)
        self.assertEqual(qid, "u_" + sid[:24])
        # Idempotent + consistent with what suggestion_to_golden writes as the golden question_id.
        g = views.suggestion_to_golden({"suggestion_id": sid, "question": "q", "reference_answer": "r"})
        self.assertEqual(g["question_id"], qid)
        self.assertEqual(views.minted_question_id(""), "")

    def test_suggestion_to_golden_maps(self):
        g = views.suggestion_to_golden({
            "suggestion_id": "abc123def456", "question": "  Quel revenu ?  ",
            "reference_answer": "12345 EUR", "expected_value": "12345",
            "expected_value_type": "CURRENCY", "category": "revenus", "language": "EN",
            "source": "chat",
        })
        self.assertEqual(g["question"], "Quel revenu ?")
        self.assertEqual(g["reference_answer"], "12345 EUR")
        self.assertEqual(g["expected_value"], "12345")
        self.assertEqual(g["expected_value_type"], "currency")
        self.assertEqual(g["category"], "revenus")
        self.assertEqual(g["language"], "en")
        self.assertTrue(g["active"])
        self.assertTrue(g["question_id"].startswith("u_abc123def456"))

    def test_suggestion_to_golden_drops_value_without_valid_type(self):
        g = views.suggestion_to_golden({
            "suggestion_id": "s1", "question": "q", "reference_answer": "r",
            "expected_value": "12345", "expected_value_type": "money",
        })
        self.assertIsNone(g["expected_value"])
        self.assertIsNone(g["expected_value_type"])

    def test_promotable_filters_and_dedups(self):
        suggestions = [
            {"suggestion_id": "s1", "question": "q1", "reference_answer": "r1"},
            {"suggestion_id": "s2", "question": "q2", "reference_answer": ""},   # no ref -> skip
            {"suggestion_id": "s3", "question": "q3", "reference_answer": "r3"},
        ]
        rows, used = views.promotable_golden_rows(suggestions, already_promoted_ids=["s3"])
        self.assertEqual(used, ["s1"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["question"], "q1")

    def test_suggestions_view_light(self):
        out = views.suggestions_view([
            {"suggestion_id": "s1", "user_id": "u", "source": "manual", "question": "q",
             "reference_answer": "r", "created_at": "2026-06-25T10:00:00"},
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["suggestion_id"], "s1")

    def test_suggestions_view_excludes_promoted(self):
        rows = [
            {"suggestion_id": "s1", "source": "manual", "question": "q1", "created_at": "t1"},
            {"suggestion_id": "s2", "source": "chat", "question": "q2", "created_at": "t2"},
        ]
        out = views.suggestions_view(rows, exclude_ids=["s1"])
        self.assertEqual([s["suggestion_id"] for s in out], ["s2"])


class PlainLanguageTests(unittest.TestCase):
    def test_confidence_band(self):
        self.assertEqual(views.confidence_band(0.9), "high")
        self.assertEqual(views.confidence_band(0.85), "high")
        self.assertEqual(views.confidence_band(0.7), "medium")
        self.assertEqual(views.confidence_band(0.6), "medium")
        self.assertEqual(views.confidence_band(0.4), "low")
        self.assertEqual(views.confidence_band(None), "low")

    def test_summary_kpis_plain_counts(self):
        rows = [
            {"benchmark_id": "B1", "agent_label": "A", "mode": "Smart", "n_questions": 10,
             "n_ok": 10, "accuracy": 0.8, "total_cost": 0.1},
            {"benchmark_id": "B1", "agent_label": "A", "mode": "Claude", "n_questions": 10,
             "n_ok": 10, "accuracy": 0.5, "total_cost": 0.5},
        ]
        k = views.summary_view(rows, benchmark_id="B1")["kpis"]
        # 8 + 5 correct over 20 scored = 13/20.
        self.assertEqual(k["n_correct"], 13)
        self.assertEqual(k["n_ok_total"], 20)
        self.assertEqual(k["band"], "medium")  # 0.65


def _scored(benchmark_id="B1", question_id="Q1", mode="Smart", attempt_no=1, correct=True,
            judge_score=5, status="ok", run_timestamp="2026-06-29T10:00:00Z",
            human_verdict="", agent_key="orchestrator"):
    return {
        "benchmark_id": benchmark_id, "benchmark_name": "said", "question_id": question_id,
        "mode": mode, "attempt_no": attempt_no, "agent_key": agent_key, "status": status,
        "correct": correct, "judge_score": judge_score, "judge_verdict":
        "correct" if correct else "incorrect", "human_verdict": human_verdict,
        "run_timestamp": run_timestamp,
    }


class EvolutionViewTests(unittest.TestCase):
    def test_improved_over_two_attempts(self):
        scored = [
            _scored(question_id="Q1", mode="Smart", attempt_no=1, correct=False, judge_score=2,
                    run_timestamp="2026-06-29T10:00:00Z"),
            _scored(question_id="Q1", mode="Smart", attempt_no=2, correct=True, judge_score=5,
                    run_timestamp="2026-06-30T10:00:00Z"),
        ]
        ev = views.evolution_for_question(scored, "B1", "Q1")
        self.assertEqual(len(ev), 1)
        smart = ev[0]
        self.assertEqual(smart["mode"], "Smart")
        self.assertEqual([a["attempt_no"] for a in smart["attempts"]], [1, 2])
        self.assertEqual(smart["latest"]["attempt_no"], 2)
        self.assertTrue(smart["latest"]["correct"])
        self.assertEqual(smart["delta"], "improved")

    def test_regressed(self):
        scored = [
            _scored(question_id="Q1", attempt_no=1, correct=True),
            _scored(question_id="Q1", attempt_no=2, correct=False,
                    run_timestamp="2026-06-30T10:00:00Z"),
        ]
        ev = views.evolution_for_question(scored, "B1", "Q1")
        self.assertEqual(ev[0]["delta"], "regressed")

    def test_first_attempt(self):
        ev = views.evolution_for_question([_scored(question_id="Q1")], "B1", "Q1")
        self.assertEqual(ev[0]["delta"], "first")

    def test_human_override_wins_in_evolution(self):
        scored = [_scored(question_id="Q1", correct=False, human_verdict="correct")]
        ev = views.evolution_for_question(scored, "B1", "Q1")
        self.assertTrue(ev[0]["latest"]["correct"])
        self.assertTrue(ev[0]["latest"]["overridden"])


class LaunchRequestTests(unittest.TestCase):
    def test_build_append(self):
        self.assertEqual(views.build_launch_request("B1", "append"),
                         {"benchmark_id": "B1", "launch_mode": "append"})

    def test_build_full(self):
        self.assertEqual(views.build_launch_request("B1", "full")["launch_mode"], "full")

    def test_garbage_mode_defaults_append(self):
        self.assertEqual(views.build_launch_request("B1", "zzz")["launch_mode"], "append")

    def test_blank_id_none(self):
        self.assertIsNone(views.build_launch_request("", "append"))


class GoldenReferenceColumnsTests(unittest.TestCase):
    def test_golden_view_carries_reference_sql_tool(self):
        rows = [{"question_id": "q1", "question": "q", "reference_answer": "a",
                 "expected_sql": "SELECT 1", "expected_tool": "show_chart"}]
        g = views.golden_view(rows)[0]
        self.assertEqual(g["expected_sql"], "SELECT 1")
        self.assertEqual(g["expected_tool"], "show_chart")

    def test_prepare_save_keeps_reference_columns(self):
        row, errors, is_new = views.prepare_golden_save(
            {"question": "q", "reference_answer": "a", "expected_sql": "SELECT 2",
             "expected_tool": "show_table"}, [])
        self.assertEqual(errors, [])
        self.assertTrue(is_new)
        self.assertEqual(row["expected_sql"], "SELECT 2")
        self.assertEqual(row["expected_tool"], "show_table")


# --- new view-model tests (Tasks 7, 8, 9) ------------------------------------

class AgentBenchmarksViewTests(unittest.TestCase):
    def test_agent_benchmarks_view_counts(self):
        golden = [
            {"question_id": "q1", "agent_key": "rev", "active": True},
            {"question_id": "q2", "agent_key": "rev", "active": True},
            {"question_id": "q3", "agent_key": "tic", "active": True},
            {"question_id": "q4", "agent_key": "rev", "active": False},
        ]
        reg = {"B1": {"benchmark_id": "B1", "name": "Base", "agent_key": "rev",
                      "modes": ["Smart", "Pro"], "status": "active", "redo": ["q2"]}}
        scored = [{"benchmark_id": "B1", "question_id": "q1", "mode": "Smart", "agent_key": "rev",
                   "correct": True, "attempt_no": 1, "run_timestamp": "2026-06-30T01:00:00Z",
                   "run_id": "r1"}]
        out = views.agent_benchmarks_view(reg, "rev", golden, scored)
        self.assertEqual(out["n_tagged"], 2)               # q1, q2 active+rev
        b = out["benchmarks"][0]
        self.assertEqual(b["n_questions"], 2)
        self.assertEqual(b["n_cells"], 4)                  # 2 questions x 2 modes
        self.assertEqual(b["n_tested"], 1)                 # (q1,Smart)
        self.assertEqual(b["n_pending"], 3)                # 4 - 1
        self.assertEqual(b["n_redo"], 1)                   # q2 flagged


class BenchmarkDetailViewTests(unittest.TestCase):
    def test_benchmark_detail_view_cells_and_runnable(self):
        golden = [{"question_id": "q1", "question": "Q one", "agent_key": "rev", "active": True,
                   "category": "rev", "expected_sql": "select 1", "expected_tool": "show_table"},
                  {"question_id": "q2", "question": "Q two", "agent_key": "rev", "active": True}]
        entity = {"benchmark_id": "B1", "name": "Base", "agent_key": "rev",
                  "agent_label": "Revenue", "project_key": "P", "agent_id": "agent:x",
                  "modes": ["Smart", "Pro"], "status": "active", "redo": ["q1"]}
        scored = [{"benchmark_id": "B1", "question_id": "q1", "mode": "Smart", "agent_key": "rev",
                   "correct": True, "attempt_no": 1, "run_timestamp": "2026-06-30T01:00:00Z",
                   "run_id": "r1"}]
        out = views.benchmark_detail_view(entity, golden, scored)
        self.assertEqual(out["ledger"]["tested"], 1)
        self.assertEqual(out["ledger"]["pending"], 3)
        self.assertEqual(out["ledger"]["redo"], 1)
        # runnable = 3 pending + q1 tested cell pulled back by redo (q1,Smart) -> 4
        self.assertEqual(out["runnable"], 4)
        q1 = next(q for q in out["questions"] if q["question_id"] == "q1")
        smart = next(c for c in q1["cells"] if c["mode"] == "Smart")
        self.assertEqual(smart["status"], "tested")
        self.assertEqual(smart["verdict"], "OK")
        self.assertTrue(q1["redo"])


class GoldenTagViewTests(unittest.TestCase):
    def test_golden_tag_view_scope(self):
        golden = [{"question_id": "q1", "agent_key": "rev", "active": True},
                  {"question_id": "q2", "agent_key": None, "active": True},
                  {"question_id": "q3", "agent_key": "tic", "active": True}]
        self.assertEqual(
            [r["question_id"] for r in views.golden_tag_view(golden, "rev", "this")["rows"]],
            ["q1"]
        )
        self.assertEqual(
            [r["question_id"] for r in views.golden_tag_view(golden, "rev", "untagged")["rows"]],
            ["q2"]
        )
        self.assertEqual(len(views.golden_tag_view(golden, "rev", "all")["rows"]), 3)


class SettingsValidationTests(unittest.TestCase):
    def test_validate_settings(self):
        ok, norm = views.validate_settings({
            "golden_dataset": "g", "judge_llm_id": "j",
            "concurrency": "5", "language": "en",
            "raw_dataset": "r", "scored_dataset": "s",
            "summary_dataset": "su", "breakdown_dataset": "b",
        })
        self.assertTrue(ok, norm)
        self.assertEqual(norm["concurrency"], 5)
        ok2, errs = views.validate_settings({"golden_dataset": "  ", "language": "xx"})
        self.assertFalse(ok2)


if __name__ == "__main__":
    unittest.main()
