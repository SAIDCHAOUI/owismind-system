"""Tests for benchmark.registry (the named per-agent benchmark model + launch resolution).

Stdlib only, no DSS. Covers parsing the registry / run_request out of the variable, the redo
mutations (create / redo flag / delete), and the launch resolution (append vs full per mode,
attempt numbering, the golden-agent-active gate, multi-attempt done detection).
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
        "redo": [],
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


class TestEntityRedo(unittest.TestCase):
    def test_normalize_parses_redo_list(self):
        e = registry.normalize_entity(_entity(redo=["q1", "q2", "q1", ""]))
        self.assertEqual(e["redo"], ["q1", "q2"])  # de-duped, blanks dropped, order kept

    def test_normalize_ignores_legacy_questions_map(self):
        raw = _entity()
        raw.pop("redo", None)
        raw["questions"] = {"q9": {"added_at": "x"}}  # legacy shape
        e = registry.normalize_entity(raw)
        self.assertEqual(e["redo"], [])
        self.assertNotIn("questions", e)

    def test_create_benchmark_no_seed(self):
        reg = registry.create_benchmark({}, "B9", "Q4", _AGENT, ["Smart"], "2026-06-30T00:00:00Z")
        self.assertEqual(reg["B9"]["name"], "Q4")
        self.assertEqual(reg["B9"]["redo"], [])
        self.assertEqual(reg["B9"]["modes"], ["Smart"])

    def test_delete_benchmark(self):
        reg = {"B1": _entity()}
        out = registry.delete_benchmark(reg, "B1")
        self.assertNotIn("B1", out)

    def test_set_and_reset_redo(self):
        reg = {"B1": _entity(redo=[])}
        reg = registry.set_redo(reg, "B1", "q1", True)
        self.assertEqual(reg["B1"]["redo"], ["q1"])
        reg = registry.set_redo(reg, "B1", "q1", True)  # idempotent
        self.assertEqual(reg["B1"]["redo"], ["q1"])
        reg = registry.set_redo(reg, "B1", "q1", False)
        self.assertEqual(reg["B1"]["redo"], [])
        reg = registry.set_redo(reg, "B1", "q2", True)
        reg = registry.reset_redo_for(reg, "B1", ["q2", "qX"])
        self.assertEqual(reg["B1"]["redo"], [])


class TestResolvePlan(unittest.TestCase):
    def setUp(self):
        self.entity = _entity(modes=["Smart", "Pro"], redo=[])
        self.golden_ids = ["Q1", "Q2", "Q3"]

    def test_append_all_pending_when_no_scored(self):
        plan = registry.resolve_to_run(self.entity, self.golden_ids, [], "append")
        self.assertEqual(plan["Smart"], ["Q1", "Q2", "Q3"])
        self.assertEqual(plan["Pro"], ["Q1", "Q2", "Q3"])

    def test_append_skips_done_cell(self):
        scored = [_scored("B1", "Q1", mode="Smart")]
        plan = registry.resolve_to_run(self.entity, self.golden_ids, scored, "append")
        self.assertNotIn("Q1", plan["Smart"])   # (Q1, Smart) done
        self.assertIn("Q1", plan["Pro"])         # (Q1, Pro) still pending

    def test_redo_re_includes_done_cell(self):
        scored = [_scored("B1", "Q1", mode="Smart")]
        ent = _entity(modes=["Smart", "Pro"], redo=["Q1"])
        plan = registry.resolve_to_run(ent, self.golden_ids, scored, "append")
        self.assertIn("Q1", plan["Smart"])       # redo flag re-includes

    def test_full_reruns_all_cells(self):
        scored = [_scored("B1", "Q1", mode="Smart"), _scored("B1", "Q2", mode="Pro")]
        plan = registry.resolve_to_run(self.entity, self.golden_ids, scored, "full")
        self.assertEqual(plan["Smart"], ["Q1", "Q2", "Q3"])
        self.assertEqual(plan["Pro"], ["Q1", "Q2", "Q3"])

    def test_no_modes_uses_default(self):
        ent = _entity(modes=[], redo=[])
        plan = registry.resolve_to_run(ent, self.golden_ids, [], "append")
        self.assertIn(registry.DEFAULT_MODE, plan)
        self.assertEqual(plan[registry.DEFAULT_MODE], ["Q1", "Q2", "Q3"])

    def test_done_cells_per_mode(self):
        scored = [
            _scored("B1", "Q1", mode="Smart"),
            _scored("B1", "Q2", mode="Smart"),
            _scored("B1", "Q1", mode="Pro"),
        ]
        cells = registry.done_cells(scored, "B1", "orchestrator")
        self.assertIn(("Q1", "Smart"), cells)
        self.assertIn(("Q2", "Smart"), cells)
        self.assertIn(("Q1", "Pro"), cells)
        self.assertNotIn(("Q2", "Pro"), cells)

    def test_golden_gate_excludes_absent_questions(self):
        # Q3 not in golden_ids -> not planned in any mode
        plan = registry.resolve_to_run(self.entity, ["Q1", "Q2"], [], "append")
        for mode in ("Smart", "Pro"):
            self.assertNotIn("Q3", plan[mode])

    def test_resolve_none_entity_returns_empty(self):
        self.assertEqual(registry.resolve_to_run(None, self.golden_ids, [], "append"), {})


class TestAttempts(unittest.TestCase):
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
    def test_create_does_not_mutate_input(self):
        reg0 = {}
        registry.create_benchmark(reg0, "B1", "said", _AGENT, ["Smart"], "t")
        self.assertEqual(reg0, {})

    def test_rename_benchmark(self):
        reg = registry.create_benchmark({}, "B1", "said", _AGENT, ["Smart"], "t")
        reg = registry.rename_benchmark(reg, "B1", "renamed")
        self.assertEqual(reg["B1"]["name"], "renamed")

    def test_validate_benchmark_name(self):
        ok, err = registry.validate_benchmark_name("fresh", {"said"})
        self.assertTrue(ok)
        self.assertIsNone(err)
        ok, err = registry.validate_benchmark_name("Said", {"said"})  # case-insensitive collision
        self.assertFalse(ok)
        ok, err = registry.validate_benchmark_name("", set())
        self.assertFalse(ok)

class TestAgentKeyAndNames(unittest.TestCase):
    def test_slug_agent_key(self):
        self.assertEqual(registry.slug_agent_key("Revenue Expert"), "revenue_expert")
        self.assertEqual(registry.slug_agent_key("  OWIsMind Orchestrator (DEV) "),
                         "owismind_orchestrator_dev")
        self.assertEqual(registry.slug_agent_key(""), "agent")

    def test_names_for_agent_is_scoped(self):
        reg = {
            "B1": _entity(benchmark_id="B1", name="Baseline", agent_key="revenue_expert"),
            "B2": _entity(benchmark_id="B2", name="Baseline", agent_key="tickets_expert"),
        }
        self.assertEqual(registry.names_for_agent(reg, "revenue_expert"), {"baseline"})
        self.assertEqual(registry.names_for_agent(reg, "tickets_expert"), {"baseline"})


class AgentCatalogTests(unittest.TestCase):
    def test_catalog_key_is_deterministic_and_strips_prefix(self):
        k1 = registry.agent_catalog_key("OWISMIND_DEV", "agent:038G7mlF")
        k2 = registry.agent_catalog_key("OWISMIND_DEV", "agent:038G7mlF")
        self.assertEqual(k1, k2)
        self.assertEqual(k1, "owismind_dev_038g7mlf")
        # same agent id in a different project -> different key
        self.assertNotEqual(k1, registry.agent_catalog_key("OTHER", "agent:038G7mlF"))

    def test_normalize_agent_requires_project_and_id(self):
        self.assertIsNone(registry.normalize_agent({"project_key": "P"}))
        self.assertIsNone(registry.normalize_agent({"agent_id": "agent:x"}))
        self.assertIsNone(registry.normalize_agent("nope"))

    def test_normalize_agent_defaults(self):
        a = registry.normalize_agent({"project_key": "OWISMIND_DEV", "agent_id": "agent:abc"})
        self.assertEqual(a["agent_key"], "owismind_dev_abc")
        self.assertEqual(a["agent_label"], "agent:abc")  # falls back to the id
        self.assertTrue(a["modes"])  # defaults True
        b = registry.normalize_agent({"project_key": "P", "agent_id": "agent:z",
                                      "agent_label": "Nice name", "modes": False})
        self.assertEqual(b["agent_label"], "Nice name")
        self.assertFalse(b["modes"])

    def test_parse_agents_dedupes_and_tolerates_json_string(self):
        raw = [
            {"project_key": "P", "agent_id": "agent:a", "agent_label": "A"},
            {"project_key": "P", "agent_id": "agent:a", "agent_label": "A dup"},  # same key
            {"agent_id": "agent:bad"},  # no project -> dropped
        ]
        out = registry.parse_agents(raw)
        self.assertEqual([a["agent_key"] for a in out], ["p_a"])
        self.assertEqual(out[0]["agent_label"], "A")  # first wins on dedupe
        # a JSON string is parsed too
        self.assertEqual(registry.parse_agents('[{"project_key":"P","agent_id":"agent:a"}]')[0]["agent_key"], "p_a")
        self.assertEqual(registry.parse_agents("garbage"), [])

    def test_upsert_updates_existing_and_appends_new(self):
        cur = registry.parse_agents([{"project_key": "P", "agent_id": "agent:a", "agent_label": "old"}])
        out = registry.upsert_agents(cur, [
            {"project_key": "P", "agent_id": "agent:a", "agent_label": "new"},  # update
            {"project_key": "P", "agent_id": "agent:b", "agent_label": "B"},    # append
        ])
        self.assertEqual([a["agent_key"] for a in out], ["p_a", "p_b"])  # order preserved
        self.assertEqual(out[0]["agent_label"], "new")

    def test_remove_and_serialize(self):
        cur = registry.parse_agents([
            {"project_key": "P", "agent_id": "agent:a"},
            {"project_key": "P", "agent_id": "agent:b"},
        ])
        out = registry.remove_agent(cur, "p_a")
        self.assertEqual([a["agent_key"] for a in out], ["p_b"])
        ser = registry.serialize_agents(out)
        self.assertEqual(ser, [{"agent_key": "p_b", "agent_label": "agent:b",
                                "project_key": "P", "agent_id": "agent:b", "modes": True}])


if __name__ == "__main__":
    unittest.main()
