"""Tests for benchmark.run_params (the single config resolver).

Stdlib only, no DSS. Proves defaults, dataset-name overrides, agents
normalization (the per-agent modes flag, label default, dropping invalid
entries), modes subset / order, language / concurrency / timeout / filter
coercion, judge id override, and the boolean run flags. The resolver is pure and
never raises.
"""

import json
import unittest

from benchmark import run_params, config


def _vars(benchmark):
    """Wrap a benchmark config (dict or JSON string) as merged custom variables."""
    return {"benchmark": benchmark}


class TestDefaults(unittest.TestCase):
    def test_no_benchmark_var(self):
        cfg = run_params.resolve({})
        self.assertEqual(cfg["golden_dataset"], "golden_questions_v1_prepared")
        self.assertEqual(cfg["raw_dataset"], "benchmark_runs_raw")
        self.assertEqual(cfg["scored_dataset"], "benchmark_runs_scored")
        self.assertEqual(cfg["summary_dataset"], "benchmark_summary")
        self.assertEqual(cfg["breakdown_dataset"], "benchmark_breakdown")
        self.assertEqual(cfg["modes"], list(config.MODES))
        self.assertEqual(cfg["language"], "fr")
        self.assertEqual(cfg["concurrency"], config.DEFAULT_CONCURRENCY)
        self.assertEqual(cfg["judge_llm_id"], config.JUDGE_LLM_ID)
        self.assertFalse(cfg["score_all_runs"])
        self.assertFalse(cfg["aggregate_all_runs"])
        self.assertEqual(cfg["history_keep_runs"], 50)   # bounded default on the heavy tables
        self.assertEqual(cfg["agents"], [])
        self.assertEqual(cfg["question_filter"], {})


class TestHistoryKeepRuns(unittest.TestCase):
    def test_default_is_bounded(self):
        self.assertEqual(run_params.resolve({})["history_keep_runs"], 50)

    def test_explicit_zero_means_unlimited(self):
        self.assertIsNone(run_params.resolve(_vars({"history_keep_runs": 0}))["history_keep_runs"])

    def test_explicit_positive_cap(self):
        self.assertEqual(run_params.resolve(_vars({"history_keep_runs": 10}))["history_keep_runs"], 10)

    def test_numeric_string_cap(self):
        self.assertEqual(run_params.resolve(_vars({"history_keep_runs": "25"}))["history_keep_runs"], 25)

    def test_negative_and_garbage_uncapped(self):
        self.assertIsNone(run_params.resolve(_vars({"history_keep_runs": -3}))["history_keep_runs"])
        self.assertIsNone(run_params.resolve(_vars({"history_keep_runs": "abc"}))["history_keep_runs"])

    def test_non_dict_variables_safe(self):
        self.assertEqual(run_params.resolve(None)["agents"], [])
        self.assertEqual(run_params.resolve("nope")["language"], "fr")


class TestBenchmarkObjectForms(unittest.TestCase):
    def test_dict_form(self):
        cfg = run_params.resolve(_vars({"language": "en", "concurrency": 2}))
        self.assertEqual(cfg["language"], "en")
        self.assertEqual(cfg["concurrency"], 2)

    def test_json_string_form(self):
        cfg = run_params.resolve(_vars(json.dumps({"language": "en"})))
        self.assertEqual(cfg["language"], "en")

    def test_garbage_string_falls_back_to_defaults(self):
        cfg = run_params.resolve(_vars("{not json"))
        self.assertEqual(cfg["language"], "fr")
        self.assertEqual(cfg["agents"], [])


class TestDatasetNames(unittest.TestCase):
    def test_overrides(self):
        cfg = run_params.resolve(_vars({
            "golden_dataset": "my_golden",
            "raw_dataset": "r", "scored_dataset": "s",
            "summary_dataset": "su", "breakdown_dataset": "b",
        }))
        self.assertEqual(cfg["golden_dataset"], "my_golden")
        self.assertEqual(cfg["raw_dataset"], "r")
        self.assertEqual(cfg["scored_dataset"], "s")
        self.assertEqual(cfg["summary_dataset"], "su")
        self.assertEqual(cfg["breakdown_dataset"], "b")

    def test_blank_override_keeps_default(self):
        cfg = run_params.resolve(_vars({"golden_dataset": "   "}))
        self.assertEqual(cfg["golden_dataset"], "golden_questions_v1_prepared")


class TestAgents(unittest.TestCase):
    def test_valid_agent_with_modes_true(self):
        cfg = run_params.resolve(_vars({"agents": [{
            "agent_key": "orchestrator",
            "agent_label": "Orchestrator",
            "project_key": "OWISMIND_DEV",
            "agent_id": "agent:038G7mlF",
            "modes": True,
        }]}))
        self.assertEqual(len(cfg["agents"]), 1)
        a = cfg["agents"][0]
        self.assertEqual(a["agent_id"], "agent:038G7mlF")
        self.assertTrue(a["modes"])

    def test_label_defaults_to_key(self):
        cfg = run_params.resolve(_vars({"agents": [{
            "agent_key": "viz", "project_key": "P", "agent_id": "agent:viz",
        }]}))
        self.assertEqual(cfg["agents"][0]["agent_label"], "viz")

    def test_modes_defaults_false(self):
        cfg = run_params.resolve(_vars({"agents": [{
            "agent_key": "viz", "project_key": "P", "agent_id": "agent:viz",
        }]}))
        self.assertFalse(cfg["agents"][0]["modes"])

    def test_modes_string_coercion(self):
        cfg = run_params.resolve(_vars({"agents": [{
            "agent_key": "o", "project_key": "P", "agent_id": "agent:o",
            "modes": "true",
        }]}))
        self.assertTrue(cfg["agents"][0]["modes"])

    def test_invalid_entries_dropped(self):
        cfg = run_params.resolve(_vars({"agents": [
            {"agent_key": "ok", "project_key": "P", "agent_id": "agent:ok"},
            {"agent_key": "", "project_key": "P", "agent_id": "agent:x"},  # blank key
            {"agent_key": "y", "agent_id": "agent:y"},                     # no project
            "not a dict",
        ]}))
        self.assertEqual(len(cfg["agents"]), 1)
        self.assertEqual(cfg["agents"][0]["agent_key"], "ok")

    def test_agents_as_json_string(self):
        cfg = run_params.resolve(_vars({"agents": json.dumps([
            {"agent_key": "o", "project_key": "P", "agent_id": "agent:o", "modes": True}
        ])}))
        self.assertEqual(len(cfg["agents"]), 1)


class TestModes(unittest.TestCase):
    def test_subset_and_canonical_order(self):
        cfg = run_params.resolve(_vars({"modes": ["Claude", "Smart"]}))
        self.assertEqual(cfg["modes"], ["Smart", "Claude"])  # Smart/Pro/Claude order

    def test_comma_string(self):
        cfg = run_params.resolve(_vars({"modes": "Claude, Smart"}))
        self.assertEqual(cfg["modes"], ["Smart", "Claude"])

    def test_legacy_internal_keys_aliased(self):
        # smart/pro/claude still accepted, mapped to the display names.
        cfg = run_params.resolve(_vars({"modes": ["claude", "smart"]}))
        self.assertEqual(cfg["modes"], ["Smart", "Claude"])

    def test_friendly_aliases_case_insensitive(self):
        cfg = run_params.resolve(_vars({"modes": ["smart", "PRO"]}))
        self.assertEqual(cfg["modes"], ["Smart", "Pro"])

    def test_unknown_only_falls_back_to_all(self):
        cfg = run_params.resolve(_vars({"modes": ["turbo"]}))
        self.assertEqual(cfg["modes"], list(config.MODES))

    def test_empty_falls_back_to_all(self):
        cfg = run_params.resolve(_vars({"modes": []}))
        self.assertEqual(cfg["modes"], list(config.MODES))


class TestScalars(unittest.TestCase):
    def test_language_validation(self):
        self.assertEqual(run_params.resolve(_vars({"language": "de"}))["language"], "fr")
        self.assertEqual(run_params.resolve(_vars({"language": "en"}))["language"], "en")

    def test_concurrency_clamped(self):
        self.assertEqual(run_params.resolve(_vars({"concurrency": 0}))["concurrency"], 1)
        self.assertEqual(run_params.resolve(_vars({"concurrency": 99}))["concurrency"], 8)
        self.assertEqual(
            run_params.resolve(_vars({"concurrency": "bad"}))["concurrency"],
            config.DEFAULT_CONCURRENCY,
        )

    def test_timeout_coercion(self):
        self.assertEqual(run_params.resolve(_vars({"per_call_timeout_s": 30}))["per_call_timeout_s"], 30.0)
        self.assertEqual(
            run_params.resolve(_vars({"per_call_timeout_s": -5}))["per_call_timeout_s"],
            config.PER_CALL_TIMEOUT_S,
        )

    def test_question_filter(self):
        cfg = run_params.resolve(_vars({"question_filter": {"categories": ["revenus"]}}))
        self.assertEqual(cfg["question_filter"], {"categories": ["revenus"]})
        # JSON string form
        cfg = run_params.resolve(_vars({"question_filter": '{"question_ids":["Q001"]}'}))
        self.assertEqual(cfg["question_filter"], {"question_ids": ["Q001"]})
        # garbage -> empty
        cfg = run_params.resolve(_vars({"question_filter": "oops"}))
        self.assertEqual(cfg["question_filter"], {})

    def test_judge_llm_id_override(self):
        cfg = run_params.resolve(_vars({"judge_llm_id": "my:model"}))
        self.assertEqual(cfg["judge_llm_id"], "my:model")
        cfg = run_params.resolve(_vars({"judge_llm_id": ""}))
        self.assertEqual(cfg["judge_llm_id"], config.JUDGE_LLM_ID)

    def test_run_flags(self):
        cfg = run_params.resolve(_vars({"score_all_runs": "true",
                                        "aggregate_all_runs": True}))
        self.assertTrue(cfg["score_all_runs"])
        self.assertTrue(cfg["aggregate_all_runs"])

    def test_benchmarks_and_run_request_resolved(self):
        # v2: the registry + the pending launch request are parsed into the resolved config.
        entity = {
            "benchmark_id": "B1", "name": "said", "agent_key": "orchestrator",
            "project_key": "OWISMIND_DEV", "agent_id": "agent:038G7mlF",
            "modes": ["Smart"], "questions": {},
        }
        cfg = run_params.resolve(_vars({
            "benchmarks": {"B1": entity},
            "run_request": {"benchmark_id": "B1", "launch_mode": "full"},
        }))
        self.assertIn("B1", cfg["benchmarks"])
        self.assertEqual(cfg["benchmarks"]["B1"]["name"], "said")
        self.assertEqual(cfg["run_request"], {"benchmark_id": "B1", "launch_mode": "full"})

    def test_benchmarks_default_empty(self):
        cfg = run_params.resolve(_vars({}))
        self.assertEqual(cfg["benchmarks"], {})
        self.assertIsNone(cfg["run_request"])


if __name__ == "__main__":
    unittest.main()
