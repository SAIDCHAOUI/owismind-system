"""Tests for benchmark.agent_runner pure helpers (stdlib only, NO DSS).

Covers ``expand_matrix`` (the cartesian product and its ordering / edge cases) and
the message-building path the runner uses (``config.build_message`` with the exact
mode / language tokens). It also drives ``run_one`` / ``run_matrix`` against a FAKE
project / completion (a tiny stub that mimics the streamed-chunk shape of
``streaming.py``), proving the capture wiring, the metrics, and the error / timeout
folding WITHOUT importing dataiku. No real DSS call is made anywhere in this file.
"""

import json
import unittest

from benchmark import agent_runner
from benchmark import config
from benchmark import schemas


# ---------------------------------------------------------------------------
# Fake streamed-completion stubs (mimic the streaming.py chunk shape)
# ---------------------------------------------------------------------------
class _Chunk(object):
    """A streamed chunk: exposes ``.data`` like the DSS SDK chunk does."""

    def __init__(self, data):
        self.data = data


class _FakeCompletion(object):
    """Records ``with_message`` and replays a fixed list of chunks."""

    def __init__(self, chunks):
        self._chunks = chunks
        self.messages = []

    def with_message(self, content, role):
        self.messages.append((content, role))
        return self

    def execute_streamed(self):
        for c in self._chunks:
            yield c


class _FakeLLM(object):
    def __init__(self, completion):
        self._completion = completion

    def new_completion(self):
        return self._completion


class _FakeProject(object):
    """A project whose ``get_llm`` hands back a scripted completion (or raises)."""

    def __init__(self, completion=None, raise_exc=None):
        self._completion = completion
        self._raise_exc = raise_exc
        self.requested_agent_ids = []

    def get_llm(self, agent_id):
        self.requested_agent_ids.append(agent_id)
        if self._raise_exc is not None:
            raise self._raise_exc
        return _FakeLLM(self._completion)


def _text_chunk(text):
    return _Chunk({"type": "content", "text": text})


def _footer_chunk(trace):
    return _Chunk({"type": "footer", "trace": trace})


def _artifact_event_chunk(event_data):
    return _Chunk({"type": "event", "eventKind": "ARTIFACT", "eventData": event_data})


def _trace_with_sql(sql, rows, columns, success=True, row_count=None):
    """A minimal footer trace carrying one semantic-model-query tool output."""
    return {
        "spans": [
            {
                "name": "semantic-model-query",
                "outputs": {
                    "sql": sql,
                    "success": success,
                    "row_count": row_count if row_count is not None else len(rows),
                    "columns": columns,
                    "rows": rows,
                },
                "usageMetadata": {
                    "promptTokens": 100,
                    "completionTokens": 40,
                    "totalTokens": 140,
                    "estimatedCost": 0.0021,
                },
            }
        ]
    }


def _golden(qid="q001", question="Quel est le revenu du compte X ?"):
    return {
        "question_id": qid,
        "question": question,
        "reference_answer": "1 234 EUR",
        "expected_value": "1234",
        "expected_value_type": "currency",
        "category": "revenus",
        "answer_type": "number",
        "difficulty": "medium",
        "language": "fr",
        "active": True,
    }


def _agent(key="orchestrator", agent_id="agent:038G7mlF"):
    return {
        "agent_key": key,
        "agent_label": "OWIsMind orchestrator",
        "project_key": "OWISMIND_DEV",
        "agent_id": agent_id,
    }


# ---------------------------------------------------------------------------
# expand_matrix (pure)
# ---------------------------------------------------------------------------
class TestExpandMatrix(unittest.TestCase):
    def test_cartesian_product_size(self):
        questions = [_golden("q1"), _golden("q2")]
        agents = [_agent("a"), _agent("b")]
        modes = ["eco", "medium", "high"]
        tasks = agent_runner.expand_matrix(questions, agents, modes)
        self.assertEqual(len(tasks), 2 * 2 * 3)

    def test_task_shape(self):
        tasks = agent_runner.expand_matrix([_golden("q1")], [_agent("a")], ["eco"])
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(set(task.keys()), {"question_row", "agent", "mode"})
        self.assertEqual(task["question_row"]["question_id"], "q1")
        self.assertEqual(task["agent"]["agent_key"], "a")
        self.assertEqual(task["mode"], "eco")

    def test_iteration_order_is_question_major_then_agent_then_mode(self):
        questions = [_golden("q1"), _golden("q2")]
        agents = [_agent("a"), _agent("b")]
        modes = ["eco", "high"]
        tasks = agent_runner.expand_matrix(questions, agents, modes)
        triples = [
            (t["question_row"]["question_id"], t["agent"]["agent_key"], t["mode"])
            for t in tasks
        ]
        self.assertEqual(
            triples,
            [
                ("q1", "a", "eco"),
                ("q1", "a", "high"),
                ("q1", "b", "eco"),
                ("q1", "b", "high"),
                ("q2", "a", "eco"),
                ("q2", "a", "high"),
                ("q2", "b", "eco"),
                ("q2", "b", "high"),
            ],
        )

    def test_empty_inputs_yield_empty(self):
        self.assertEqual(agent_runner.expand_matrix([], [_agent()], ["eco"]), [])
        self.assertEqual(agent_runner.expand_matrix([_golden()], [], ["eco"]), [])
        self.assertEqual(agent_runner.expand_matrix([_golden()], [_agent()], []), [])

    def test_inputs_not_mutated(self):
        questions = [_golden("q1")]
        agents = [_agent("a")]
        modes = ["eco"]
        agent_runner.expand_matrix(questions, agents, modes)
        self.assertEqual(len(questions), 1)
        self.assertEqual(len(agents), 1)
        self.assertEqual(modes, ["eco"])


# ---------------------------------------------------------------------------
# message building path used by the runner
# ---------------------------------------------------------------------------
class TestMessageBuilding(unittest.TestCase):
    def test_build_message_appends_exact_tokens(self):
        msg = config.build_message("revenu du compte X", "high", "fr")
        # The token brackets are U+27E6 / U+27E7 (mirrored from production).
        self.assertEqual(
            msg,
            "revenu du compte X "
            + "⟦owi:mode=high⟧"
            + "⟦owi:lang=fr⟧",
        )

    def test_unknown_mode_emits_no_mode_token(self):
        msg = config.build_message("hi", "turbo", "fr")
        self.assertNotIn("owi:mode=", msg)
        self.assertIn("owi:lang=fr", msg)

    def test_none_question_is_safe(self):
        msg = config.build_message(None, "eco", "en")
        self.assertTrue(msg.endswith("⟦owi:lang=en⟧"))


# ---------------------------------------------------------------------------
# run_one against a fake project (no DSS): capture wiring + metrics + errors
# ---------------------------------------------------------------------------
class TestRunOne(unittest.TestCase):
    def test_success_captures_full_answer_and_metrics(self):
        trace = _trace_with_sql(
            "SELECT amount FROM t", rows=[[1234]], columns=["amount"])
        completion = _FakeCompletion(
            [
                _text_chunk("Le revenu est "),
                _text_chunk("1234 EUR."),
                _footer_chunk(trace),
            ]
        )
        project = _FakeProject(completion=completion)

        row = agent_runner.run_one(
            project, _agent(), _golden(), "high", "fr", timeout=120,
            run_id="run1", run_timestamp="2026-06-24T00:00:00Z",
            config_json="{}",
        )

        # Every RAW column is present (self-describing row).
        self.assertEqual(set(row.keys()), set(schemas.RAW_COLUMNS))
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["answer_text"], "Le revenu est 1234 EUR.")
        # full_answer carries the text AND the captured table (the key fix).
        self.assertIn("1234 EUR.", row["full_answer"])
        self.assertIn("1234", row["full_answer"])
        self.assertIn("amount", row["full_answer"])
        # SQL + rows captured.
        self.assertEqual(row["n_sql"], 1)
        self.assertEqual(row["total_rows"], 1)
        sql_items = json.loads(row["generated_sql_json"])
        self.assertEqual(len(sql_items), 1)
        self.assertEqual(sql_items[0]["sql"], "SELECT amount FROM t")
        self.assertTrue(sql_items[0]["success"])
        # Usage summed from the trace.
        self.assertEqual(row["prompt_tokens"], 100)
        self.assertEqual(row["completion_tokens"], 40)
        self.assertEqual(row["total_tokens"], 140)
        self.assertAlmostEqual(row["estimated_cost"], 0.0021)
        # Metrics measured.
        self.assertIsInstance(row["latency_total_s"], float)
        self.assertGreaterEqual(row["latency_total_s"], 0.0)
        self.assertIsInstance(row["time_to_first_token_s"], float)
        # Denormalized golden fields.
        self.assertEqual(row["question_id"], "q001")
        self.assertEqual(row["category"], "revenus")
        self.assertEqual(row["mode"], "high")
        self.assertEqual(row["agent_id"], "agent:038G7mlF")
        # The agent id reached the (fake) project.
        self.assertEqual(project.requested_agent_ids, ["agent:038G7mlF"])
        # The exact control-tokened message reached the completion.
        self.assertEqual(len(completion.messages), 1)
        sent, role = completion.messages[0]
        self.assertEqual(role, "user")
        self.assertIn("⟦owi:mode=high⟧", sent)

    def test_artifact_event_is_captured(self):
        trace = _trace_with_sql("SELECT 1", rows=[[1]], columns=["n"])
        completion = _FakeCompletion(
            [
                _text_chunk("Voici un graphique."),
                _artifact_event_chunk(
                    {
                        "kind": "chart",
                        "title": "Revenu mensuel",
                        "chart": {"type": "bar", "x": "month", "y": ["amount"]},
                    }
                ),
                _footer_chunk(trace),
            ]
        )
        project = _FakeProject(completion=completion)
        row = agent_runner.run_one(
            project, _agent(), _golden(), "high", "fr", timeout=120)
        artifacts = json.loads(row["artifacts_json"])
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["kind"], "chart")
        self.assertIn("a bar chart", row["full_answer"])

    def test_no_text_leaves_ttft_none(self):
        trace = _trace_with_sql("SELECT 1", rows=[[1]], columns=["n"])
        completion = _FakeCompletion([_footer_chunk(trace)])
        project = _FakeProject(completion=completion)
        row = agent_runner.run_one(
            project, _agent(), _golden(), "eco", "fr", timeout=120)
        self.assertEqual(row["status"], "ok")
        self.assertIsNone(row["time_to_first_token_s"])
        self.assertEqual(row["answer_text"], "")

    def test_agent_exception_becomes_error_row(self):
        project = _FakeProject(raise_exc=RuntimeError("agent boom"))
        row = agent_runner.run_one(
            project, _agent(), _golden(), "medium", "fr", timeout=120)
        self.assertEqual(set(row.keys()), set(schemas.RAW_COLUMNS))
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["error_type"], "RuntimeError")
        self.assertIn("agent boom", row["error_message"])
        self.assertEqual(row["full_answer"], "")
        self.assertEqual(row["n_sql"], 0)
        self.assertEqual(row["total_tokens"], 0)
        self.assertIsInstance(row["latency_total_s"], float)
        # Golden / agent context still populated on a failure.
        self.assertEqual(row["question_id"], "q001")
        self.assertEqual(row["mode"], "medium")

    def test_inline_timeout_becomes_timeout_row(self):
        project = _FakeProject(raise_exc=TimeoutError("too slow"))
        row = agent_runner.run_one(
            project, _agent(), _golden(), "high", "fr", timeout=1)
        self.assertEqual(row["status"], "timeout")
        self.assertEqual(row["error_type"], "TimeoutError")

    def test_run_one_never_raises_on_bad_inputs(self):
        # A None project would normally explode; run_one folds it into a row.
        row = agent_runner.run_one(
            None, _agent(), _golden(), "eco", "fr", timeout=120)
        self.assertEqual(row["status"], "error")
        self.assertEqual(set(row.keys()), set(schemas.RAW_COLUMNS))

    def test_footer_recognised_by_isinstance_fallback(self):
        # Some SDKs deliver the footer as a dedicated chunk class WITHOUT stamping
        # type == "footer" on .data. The runner must still capture the trace
        # (mirror of streaming._is_footer_chunk). We simulate that by monkeypatching
        # _footer_chunk_class to a stub class and emitting a chunk of that class
        # whose .data carries the trace but no "footer" type marker.
        class _FooterChunk(object):
            def __init__(self, data):
                self.data = data

        trace = _trace_with_sql("SELECT 1", rows=[[7]], columns=["n"])
        # The footer chunk's data has the trace but NO type == "footer".
        footer = _FooterChunk({"trace": trace})
        completion = _FakeCompletion([_text_chunk("hi"), footer])
        project = _FakeProject(completion=completion)

        original = agent_runner._footer_chunk_class
        agent_runner._footer_chunk_class = lambda: _FooterChunk
        try:
            row = agent_runner.run_one(
                project, _agent(), _golden(), "eco", "fr", timeout=120)
        finally:
            agent_runner._footer_chunk_class = original

        # The trace was captured via the isinstance fallback: SQL + usage present.
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["n_sql"], 1)
        self.assertEqual(row["total_rows"], 1)
        self.assertEqual(row["total_tokens"], 140)
        # The captured result row reaches full_answer (the key fix, table case).
        self.assertIn("7", row["full_answer"])
        sql_items = json.loads(row["generated_sql_json"])
        self.assertEqual(sql_items[0]["sql"], "SELECT 1")


# ---------------------------------------------------------------------------
# run_matrix against a fake project: incremental write + full coverage
# ---------------------------------------------------------------------------
class TestRunMatrix(unittest.TestCase):
    def _project(self):
        trace = _trace_with_sql("SELECT 1", rows=[[1]], columns=["n"])
        # A fresh completion per call would be ideal; the fake replays the same
        # chunk list each time, which is fine for a generator-based stub.
        return _FakeProject(
            completion=_FakeCompletion(
                [_text_chunk("ok"), _footer_chunk(trace)]))

    def test_writes_one_row_per_task(self):
        written = []
        run_config = {
            "run_id": "runX",
            "run_timestamp": "2026-06-24T00:00:00Z",
            "project": self._project(),
            "agents": [_agent("a"), _agent("b", "agent:zzz")],
            "questions": [_golden("q1"), _golden("q2")],
            "modes": ["eco", "high"],
            "language": "fr",
            "concurrency": 2,
            "per_call_timeout_s": 30,
        }
        agent_runner.run_matrix(run_config, write_row=written.append)
        # 2 questions x 2 agents x 2 modes = 8 rows.
        self.assertEqual(len(written), 8)
        for row in written:
            self.assertEqual(set(row.keys()), set(schemas.RAW_COLUMNS))
            self.assertEqual(row["run_id"], "runX")
            self.assertEqual(row["status"], "ok")
            # config snapshot stamped on every row.
            cfg = json.loads(row["config_json"])
            self.assertEqual(cfg["n_questions"], 2)
            self.assertEqual(cfg["language"], "fr")

    def test_empty_matrix_writes_nothing(self):
        written = []
        agent_runner.run_matrix(
            {"project": self._project(), "agents": [], "questions": [],
             "modes": ["eco"]},
            write_row=written.append,
        )
        self.assertEqual(written, [])

    def test_concurrency_floored_and_defaults(self):
        # A bad concurrency value must not crash; it falls back to a safe bound.
        written = []
        run_config = {
            "run_id": "runY",
            "project": self._project(),
            "agents": [_agent("a")],
            "questions": [_golden("q1")],
            "modes": ["eco"],
            "concurrency": "not-a-number",
        }
        agent_runner.run_matrix(run_config, write_row=written.append)
        self.assertEqual(len(written), 1)

    def test_write_failure_does_not_abort_run(self):
        calls = {"n": 0}

        def flaky_write(_row):
            calls["n"] += 1
            if calls["n"] == 1:
                raise IOError("disk full once")

        run_config = {
            "run_id": "runZ",
            "project": self._project(),
            "agents": [_agent("a")],
            "questions": [_golden("q1"), _golden("q2")],
            "modes": ["eco"],
            "concurrency": 1,
        }
        # Must not raise even though the first write throws.
        agent_runner.run_matrix(run_config, write_row=flaky_write)
        self.assertEqual(calls["n"], 2)


if __name__ == "__main__":
    unittest.main()
