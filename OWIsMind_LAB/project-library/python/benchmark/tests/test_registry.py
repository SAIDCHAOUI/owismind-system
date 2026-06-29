"""Tests for benchmark.registry (the named per-agent benchmark model + launch resolution).

Stdlib only, no DSS. Covers parsing the registry / run_request out of the variable, the membership
mutations (create / add / remove / redo flag), and the launch resolution (append vs full, attempt
numbering, the golden-active gate, multi-attempt done detection).
"""

import unittest

from benchmark import registry


_AGENT = {
    "agent_key": "orchestrator",
    "agent_label": "OWIsMind Orchestrator (DEV)",
    "project_key": "OWISMIND_DEV",
    "agent_id": "agent:038G7mlF",
}


def _entity(**over):
    base = {
        "benchmark_id": "B1",
        "name": "said",
        "agent_key": _AGENT["agent_key"],
        "agent_label": _AGENT["agent_label"],
        "project_key": _AGENT["project_key"],
        "agent_id": _AGENT["agent_id"],
        "modes": ["Smart", "Pro", "Claude"],
        "status": "active",
        "created_at": "2026-06-29T09:00:00Z",
        "created_by": "user",
        "questions": {},
    }
    base.update(over)
    return base


def _scored(benchmark_id, question_id, mode="Smart", attempt_no=1, agent_key="orchestrator",
            run_id="r1", run_timestamp="2026-06-29T09:00:00Z"):
    return {
        "benchmark_id": benchmark_id, "question_id": question_id, "mode": mode,
        "attempt_no": attempt_no, "agent_key": agent_key,
        "run_id": run_id, "run_timestamp": run_timestamp,
    }


class TestParse(unittest.TestCase):
    def test_parse_registry_dict(self):
        reg = registry.parse_registry({"B1": _entity()})
        self.assertIn("B1", reg)
        self.assertEqual(reg["B1"]["name"], "said")

    def test_parse_registry_json_string(self):
        import json
        reg = registry.parse_registry(json.dumps({"B1": _entity()}))
        self.assertEqual(reg["B1"]["agent_id"], "agent:038G7mlF")

    def test_parse_backfills_id_from_key(self):
        e = _entity()
        del e["benchmark_id"]
        reg = registry.parse_registry({"BX": e})
        self.assertIn("BX", reg)
        self.assertEqual(reg["BX"]["benchmark_id"], "BX")

    def test_parse_drops_unusable_entity(self):
        # no agent_id -> dropped
        e = _entity(agent_id="")
        self.assertEqual(registry.parse_registry({"B1": e}), {})

    def test_parse_drops_no_name(self):
        self.assertEqual(registry.parse_registry({"B1": _entity(name="")}), {})

    def test_parse_run_request(self):
        rq = registry.parse_run_request({"benchmark_id": "B1", "launch_mode": "full"})
        self.assertEqual(rq, {"benchmark_id": "B1", "launch_mode": "full"})

    def test_parse_run_request_defaults_append(self):
        rq = registry.parse_run_request({"benchmark_id": "B1", "launch_mode": "garbage"})
        self.assertEqual(rq["launch_mode"], "append")

    def test_parse_run_request_none_without_id(self):
        self.assertIsNone(registry.parse_run_request({"launch_mode": "append"}))
        self.assertIsNone(registry.parse_run_request(None))


class TestResolveToRun(unittest.TestCase):
    def setUp(self):
        self.entity = _entity(questions={
            "Q1": {"added_at": "2026-06-29T09:00:00Z", "include_next": False, "active": True},
            "Q2": {"added_at": "2026-06-29T09:01:00Z", "include_next": False, "active": True},
            "Q3": {"added_at": "2026-06-29T09:02:00Z", "include_next": False, "active": True},
        })
        self.golden = {"Q1", "Q2", "Q3"}

    def test_append_all_pending_when_no_scored(self):
        to_run = registry.resolve_to_run(self.entity, [], self.golden, "append")
        self.assertEqual(to_run, ["Q1", "Q2", "Q3"])

    def test_append_skips_done(self):
        scored = [_scored("B1", "Q1")]  # Q1 already attempted
        to_run = registry.resolve_to_run(self.entity, scored, self.golden, "append")
        self.assertEqual(to_run, ["Q2", "Q3"])

    def test_append_includes_redo_even_if_done(self):
        ent = _entity(questions=dict(self.entity["questions"]))
        ent["questions"]["Q1"]["include_next"] = True
        scored = [_scored("B1", "Q1")]
        to_run = registry.resolve_to_run(ent, scored, self.golden, "append")
        self.assertIn("Q1", to_run)         # redo flag re-includes a done question
        self.assertEqual(set(to_run), {"Q1", "Q2", "Q3"})

    def test_full_runs_every_member(self):
        scored = [_scored("B1", "Q1"), _scored("B1", "Q2")]
        to_run = registry.resolve_to_run(self.entity, scored, self.golden, "full")
        self.assertEqual(to_run, ["Q1", "Q2", "Q3"])

    def test_inactive_golden_question_dropped(self):
        # Q2 no longer an active golden question -> not run even though pending.
        to_run = registry.resolve_to_run(self.entity, [], {"Q1", "Q3"}, "append")
        self.assertEqual(to_run, ["Q1", "Q3"])

    def test_inactive_member_dropped(self):
        ent = _entity(questions=dict(self.entity["questions"]))
        ent["questions"]["Q2"]["active"] = False
        to_run = registry.resolve_to_run(ent, [], self.golden, "append")
        self.assertEqual(to_run, ["Q1", "Q3"])

    def test_member_order_by_added_at(self):
        ent = _entity(questions={
            "Qb": {"added_at": "2026-06-29T09:05:00Z", "include_next": False, "active": True},
            "Qa": {"added_at": "2026-06-29T09:01:00Z", "include_next": False, "active": True},
        })
        to_run = registry.resolve_to_run(ent, [], {"Qa", "Qb"}, "append")
        self.assertEqual(to_run, ["Qa", "Qb"])


class TestAttempts(unittest.TestCase):
    def test_done_question_ids(self):
        scored = [_scored("B1", "Q1"), _scored("B1", "Q2", mode="Pro"), _scored("B2", "Q9")]
        done = registry.done_question_ids(scored, "B1", "orchestrator")
        self.assertEqual(done, {"Q1", "Q2"})

    def test_attempt_numbers_per_mode(self):
        scored = [
            _scored("B1", "Q1", mode="Smart", attempt_no=1),
            _scored("B1", "Q1", mode="Smart", attempt_no=2),
            _scored("B1", "Q1", mode="Pro", attempt_no=1),
        ]
        amap = registry.attempt_numbers(scored, "B1", "orchestrator")
        self.assertEqual(amap[("Q1", "Smart")], 2)
        self.assertEqual(amap[("Q1", "Pro")], 1)

    def test_next_attempt_no(self):
        amap = {("Q1", "Smart"): 2}
        self.assertEqual(registry.next_attempt_no(amap, "Q1", "Smart"), 3)
        self.assertEqual(registry.next_attempt_no(amap, "Q1", "Pro"), 1)
        self.assertEqual(registry.next_attempt_no({}, "Qx", "Smart"), 1)

    def test_benchmark_id_of_run(self):
        scored = [_scored("B1", "Q1", run_id="rA"), _scored("B2", "Q2", run_id="rB")]
        self.assertEqual(registry.benchmark_id_of_run(scored, "rB"), "B2")
        self.assertEqual(registry.benchmark_id_of_run(scored, "missing"), "")


class TestMutations(unittest.TestCase):
    def test_create_benchmark_seeds_questions(self):
        reg = registry.create_benchmark({}, "B1", "said", _AGENT, ["Smart"],
                                        "2026-06-29T09:00:00Z", "user", ["Q1", "Q2"])
        self.assertIn("B1", reg)
        self.assertEqual(set(reg["B1"]["questions"].keys()), {"Q1", "Q2"})
        self.assertFalse(reg["B1"]["questions"]["Q1"]["include_next"])

    def test_create_does_not_mutate_input(self):
        reg0 = {}
        registry.create_benchmark(reg0, "B1", "said", _AGENT, ["Smart"], "t")
        self.assertEqual(reg0, {})

    def test_add_questions_idempotent(self):
        reg = registry.create_benchmark({}, "B1", "said", _AGENT, ["Smart"], "t", question_ids=["Q1"])
        reg = registry.add_questions(reg, "B1", ["Q1", "Q2"], "t2")
        self.assertEqual(set(reg["B1"]["questions"].keys()), {"Q1", "Q2"})

    def test_remove_question(self):
        reg = registry.create_benchmark({}, "B1", "said", _AGENT, ["Smart"], "t", question_ids=["Q1", "Q2"])
        reg = registry.remove_question(reg, "B1", "Q1")
        self.assertEqual(set(reg["B1"]["questions"].keys()), {"Q2"})

    def test_set_and_reset_include_next(self):
        reg = registry.create_benchmark({}, "B1", "said", _AGENT, ["Smart"], "t", question_ids=["Q1", "Q2"])
        reg = registry.set_include_next(reg, "B1", "Q1", True)
        self.assertTrue(reg["B1"]["questions"]["Q1"]["include_next"])
        reg = registry.reset_include_next_for(reg, "B1", ["Q1"])
        self.assertFalse(reg["B1"]["questions"]["Q1"]["include_next"])

    def test_rename_and_archive(self):
        reg = registry.create_benchmark({}, "B1", "said", _AGENT, ["Smart"], "t")
        reg = registry.rename_benchmark(reg, "B1", "renamed")
        self.assertEqual(reg["B1"]["name"], "renamed")
        reg = registry.archive_benchmark(reg, "B1")
        self.assertEqual(reg["B1"]["status"], "archived")

    def test_validate_benchmark_name(self):
        ok, err = registry.validate_benchmark_name("fresh", {"said"})
        self.assertTrue(ok)
        self.assertIsNone(err)
        ok, err = registry.validate_benchmark_name("Said", {"said"})  # case-insensitive collision
        self.assertFalse(ok)
        ok, err = registry.validate_benchmark_name("", set())
        self.assertFalse(ok)

    def test_existing_names(self):
        reg = registry.create_benchmark({}, "B1", "Said", _AGENT, ["Smart"], "t")
        self.assertEqual(registry.existing_names(reg), {"said"})


if __name__ == "__main__":
    unittest.main()
