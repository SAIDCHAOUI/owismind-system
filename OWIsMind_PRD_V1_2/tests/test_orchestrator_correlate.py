"""DSS-free adversarial tests for the correlate step (T7, spec section 7.2).

The model only ever writes SQL against logical aliases d1..dN; the CODE owns the
CTE substitution from server-only physical tables, the guard (denylist, literal
blanking, alias allowlist, LIMIT cap), EXPLAIN, preview, sanity and the bounded
read-only execution, with at most 2 execution-guided corrections.

Run from the repo root:
    python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests -v
"""

import importlib.util
import os
import sys
import types
import unittest
from contextlib import contextmanager


def _install_stubs():
    dataiku_mod = types.ModuleType("dataiku")
    dataiku_mod.api_client = lambda: None
    dataiku_mod.Dataset = lambda *a, **k: None
    dataiku_mod.SQLExecutor2 = lambda *a, **k: None
    llm_pkg = types.ModuleType("dataiku.llm")
    llm_python = types.ModuleType("dataiku.llm.python")

    class BaseLLM(object):
        pass

    llm_python.BaseLLM = BaseLLM
    llm_pkg.python = llm_python
    dataiku_mod.llm = llm_pkg
    sys.modules.setdefault("dataiku", dataiku_mod)
    sys.modules.setdefault("dataiku.llm", llm_pkg)
    sys.modules.setdefault("dataiku.llm.python", llm_python)

    lg = types.ModuleType("langgraph")
    lg_graph = types.ModuleType("langgraph.graph")
    lg_graph.START = "__start__"
    lg_graph.END = "__end__"

    class _StateGraph(object):
        def __init__(self, *a, **k):
            pass

        def add_node(self, *a, **k):
            pass

        def add_edge(self, *a, **k):
            pass

        def add_conditional_edges(self, *a, **k):
            pass

        def compile(self, *a, **k):
            return self

        def stream(self, *a, **k):
            return iter(())

    lg_graph.StateGraph = _StateGraph
    lg_config = types.ModuleType("langgraph.config")
    lg_config.get_stream_writer = lambda: (lambda *a, **k: None)
    lg.graph = lg_graph
    lg.config = lg_config
    sys.modules.setdefault("langgraph", lg)
    sys.modules.setdefault("langgraph.graph", lg_graph)
    sys.modules.setdefault("langgraph.config", lg_config)


_install_stubs()

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_MIRROR_DIR = os.path.dirname(_TESTS_DIR)


def _load(mod_name, path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wf = _load("orchestrator_correlate_under_test",
           os.path.join(_MIRROR_DIR, "genai", "agents",
                        "OWIsMind_orchestrator.py"))


ALIASES = ("d1", "d2")


class GuardTests(unittest.TestCase):
    """_corr_guard_model_sql: the closed, deterministic SQL gate."""

    def _ok(self, sql):
        clean, problem = wf._corr_guard_model_sql(sql, ALIASES)
        self.assertIsNone(problem, problem)
        return clean

    def _ko(self, sql, expected_prefix):
        clean, problem = wf._corr_guard_model_sql(sql, ALIASES)
        self.assertIsNone(clean)
        self.assertTrue(str(problem).startswith(expected_prefix),
                        "%r !~ %r" % (problem, expected_prefix))

    def test_valid_join_is_accepted_and_limit_appended(self):
        clean = self._ok('SELECT d1."customer", d2."tickets" '
                         'FROM d1 JOIN d2 ON d1."customer" = d2."customer"')
        self.assertTrue(clean.endswith("LIMIT %d" % wf.CORRELATE_MAX_ROWS))

    def test_oversized_limit_is_capped(self):
        clean = self._ok("SELECT * FROM d1 JOIN d2 ON d1.k = d2.k LIMIT 99999")
        self.assertIn("LIMIT %d" % wf.CORRELATE_MAX_ROWS, clean)
        self.assertNotIn("99999", clean)

    def test_ddl_dml_rejected(self):
        for bad in ("DROP TABLE d1", "DELETE FROM d1", "UPDATE d1 SET x=1",
                    "INSERT INTO d1 VALUES (1)", "CREATE TABLE t (x int)",
                    "GRANT ALL ON d1 TO evil", "TRUNCATE d1"):
            clean, problem = wf._corr_guard_model_sql(bad, ALIASES)
            self.assertIsNone(clean, bad)

    def test_with_and_semicolons_rejected(self):
        # the CODE owns the CTEs: a model statement may only START with SELECT
        self._ko("WITH x AS (SELECT 1) SELECT * FROM x", "not_a_select")
        # an embedded WITH deeper in the statement hits the keyword denylist
        self._ko("SELECT * FROM d1 WHERE x IN (WITH y AS (SELECT 1) "
                 "SELECT * FROM y)", "forbidden_keyword")
        self._ko("SELECT * FROM d1; SELECT * FROM d2", "multi_statement")

    def test_system_catalogs_rejected(self):
        self._ko("SELECT * FROM d1 JOIN pg_catalog.pg_tables ON true",
                 "forbidden_keyword" if False else "system_table")
        self._ko("SELECT * FROM information_schema.tables", "system_table")

    def test_physical_or_invented_table_rejected(self):
        self._ko('SELECT * FROM "OWISMIND_DEV_drive_revenues"',
                 "table_not_allowed")
        self._ko("SELECT * FROM d1 JOIN secret_table ON true",
                 "table_not_allowed")

    def test_comma_join_to_a_hidden_table_is_rejected(self):
        # Regression: the FROM/JOIN scan must catch EVERY comma-separated table,
        # not just the first - else `FROM d1, secret` reaches a real physical
        # table (secret is not a defined CTE) = cross-table read exfiltration.
        self._ko("SELECT * FROM d1, secret_table WHERE d1.k = secret_table.k",
                 "table_not_allowed")
        # a comma-joined system catalog trips the system-table guard first
        # (defense in depth) - either way it never executes
        self._ko("SELECT * FROM d1 , pg_user", "system_table")
        # legitimate comma-join of two ALLOWED aliases still passes
        self._ok("SELECT * FROM d1, d2 WHERE d1.k = d2.k")
        # SELECT-list and GROUP BY commas are not table refs
        self._ok("SELECT d1.a, d1.b FROM d1 GROUP BY d1.a, d1.b")

    def test_literal_blanking_prevents_false_positives(self):
        clean = self._ok("SELECT d1.k FROM d1 WHERE d1.label = "
                         "'drop the update into merge'")
        self.assertIn("drop the update into merge", clean)

    def test_control_tokens_and_empty_rejected(self):
        self._ko("SELECT 1 FROM d1 ⟦owi:mode=deep⟧", "control_token_in_sql")
        self._ko("", "empty_sql")
        self._ko("EXPLAIN SELECT 1", "not_a_select")

    def test_sql_comments_rejected(self):
        # PostgreSQL treats /**/ as whitespace: a comment between FROM and a
        # table name would smuggle a physical table past the allowlist scan.
        self._ko("SELECT * FROM/**/webapp_users", "comment_in_sql")
        self._ko("SELECT * FROM d1 JOIN/**/webapp_users ON true", "comment_in_sql")
        self._ko("SELECT * FROM d1 -- then a hidden line\nUNION SELECT 1",
                 "comment_in_sql")
        # a literal that merely contains a comment marker stays fine (blanked)
        self._ok("SELECT d1.k FROM d1 WHERE d1.label = 'a /* b */ c'")

    def test_bare_table_relation_form_rejected(self):
        # PostgreSQL `TABLE foo` == `SELECT * FROM foo` reaches a relation with NO
        # FROM/JOIN, so it escaped the alias allowlist scan. The `table` keyword is
        # never legitimate in a model statement (the CODE owns every relation).
        self._ko("SELECT * FROM (TABLE secret_table) q", "forbidden_keyword")
        self._ko("SELECT id FROM d1 WHERE false UNION ALL TABLE secret_table",
                 "forbidden_keyword")

    def test_no_whitespace_quoted_identifier_rejected(self):
        # `FROM"secret"` (no space) is valid PostgreSQL; the allowlist scan now
        # anchors on the keyword boundary and catches the glued quoted relation.
        self._ko('SELECT * FROM"secret_table"', "table_not_allowed")
        self._ko('SELECT * FROM d1 JOIN"secret_table" ON true', "table_not_allowed")
        # a glued ALLOWED alias still passes
        self._ok('SELECT * FROM"d1"')

    def test_query_executing_functions_rejected(self):
        # Functions that run a query passed as text (or read server files) reach
        # arbitrary relations without a FROM/JOIN: read-only allows the inner read.
        self._ko("SELECT query_to_xml('SELECT * FROM secret_table', true, "
                 "false, '') FROM d1", "forbidden_function")
        self._ko("SELECT table_to_xml('secret_table', true, false, '') FROM d1",
                 "forbidden_function")
        self._ko("SELECT dblink('conn', 'SELECT * FROM secret') AS t FROM d1",
                 "forbidden_function")
        self._ko("SELECT pg_read_file('/etc/passwd') FROM d1", "forbidden_function")


class CteBuilderTests(unittest.TestCase):
    def test_ctes_quote_identifiers_and_prefix_model_sql(self):
        agent = object.__new__(wf.MyLLM)
        alias_map = {
            "d1": {"physical": "OWISMIND_DEV_drive_revenues",
                   "columns": [{"name": "customer"}, {"name": "rev\"enue"}]},
            "d2": {"physical": '"already_quoted"',
                   "columns": [{"name": "customer"}]},
        }
        final = agent._correlate_build_final_sql(alias_map,
                                                 "SELECT * FROM d1 LIMIT 5")
        self.assertTrue(final.startswith(
            'WITH d1 AS (SELECT "customer", "rev""enue" '
            'FROM "OWISMIND_DEV_drive_revenues"), '
            'd2 AS (SELECT "customer" FROM "already_quoted") '))
        self.assertTrue(final.endswith("SELECT * FROM d1 LIMIT 5"))


class _FakeDF(object):
    def __init__(self, columns=None, rows=None):
        self.columns = columns or []
        self._rows = rows or []

    def __len__(self):
        return len(self._rows)

    def iterrows(self):
        for i, row in enumerate(self._rows):
            yield i, dict(zip(self.columns, row))

    def head(self, n):
        return _FakeDF(self.columns, self._rows[:n])

    def itertuples(self, index=False, name=None):
        return iter(tuple(r) for r in self._rows)


class _FakeExecutor(object):
    """Scripted SQLExecutor2: read-only enforced, per-prefix responses."""

    def __init__(self, harness):
        self.h = harness

    def query_to_df(self, sql, pre_queries=None, post_queries=None):
        self.h.sql_log.append(sql)
        assert "SET LOCAL transaction_read_only TO on" in (pre_queries or []), \
            "read-only pre-query missing"
        assert post_queries in (None, []), "no write/commit allowed"
        lowered = sql.strip().lower()
        assert lowered.startswith(("select", "explain", "with")), sql
        # Catalog read: mirror the REAL published schema
        # (owismind_factory.catalog.CATALOG_SCHEMA) - the type column is
        # column_type and there is NO item_level column. A prior fake here
        # selected data_type / filtered item_level, which hid a hard mismatch
        # (the real query used columns the catalog never publishes).
        if "physical_table" in lowered and "capability_key" in lowered:  # catalog
            assert "column_type" in lowered, \
                "catalog read must select column_type, got: %s" % sql
            assert "item_level" not in lowered, \
                "catalog schema has no item_level column: %s" % sql
            assert "data_type" not in lowered, \
                "catalog type column is column_type, not data_type: %s" % sql
            key = "d2" if "cap_b" in sql else "d1"
            return _FakeDF(
                ["column_name", "column_type", "description", "physical_table"],
                self.h.catalog_rows[key])
        if lowered.startswith("explain"):
            if self.h.explain_error:
                raise RuntimeError(self.h.explain_error)
            return _FakeDF(["plan"], [["ok"]])
        if "owi_preview" in lowered:
            return _FakeDF(self.h.result_columns,
                           self.h.result_rows[:wf.CORRELATE_PREVIEW_ROWS])
        return _FakeDF(self.h.result_columns, self.h.result_rows)


class _FakeTrace(object):
    def __init__(self):
        self.spans = []

    @contextmanager
    def subspan(self, name):
        span = types.SimpleNamespace(outputs={}, name=name,
                                     append_trace=lambda *_: None)
        self.spans.append(span)
        yield span


class CorrelateFlowTests(unittest.TestCase):
    def setUp(self):
        self.sql_log = []
        self.explain_error = None
        self.catalog_rows = {
            "d1": [["customer", "text", "the customer key",
                    "OWISMIND_DEV_drive_revenues"],
                   ["revenue_eur", "numeric", "actual revenue",
                    "OWISMIND_DEV_drive_revenues"]],
            "d2": [["customer", "text", "the customer key",
                    "OWISMIND_DEV_tickets"],
                   ["ticket_count", "int", "tickets per customer",
                    "OWISMIND_DEV_tickets"]],
        }
        self.result_columns = ["customer", "revenue_eur", "ticket_count"]
        self.result_rows = [["acme", 100.0, 3], ["globex", 50.0, 1]]

        self.agent = object.__new__(wf.MyLLM)
        self.agent._caps = {
            "cap_a": {"enabled": True, "catalog_generation": "rev-20260717-001",
                      "catalog_dataset": "OWIsMind_agent_catalog_v1"},
            "cap_b": {"enabled": True, "catalog_generation": "tick-20260717-001",
                      "catalog_dataset": "OWIsMind_agent_catalog_v1"},
        }
        self.model_sqls = ['SELECT d1."customer", d1."revenue_eur", '
                           'd2."ticket_count" FROM d1 JOIN d2 '
                           'ON d1."customer" = d2."customer" LIMIT 100']
        self.json_calls = []

        harness = self

        def fake_json_call(project, trace, llm_id, system_prompt, user_msg,
                           schema, span_name):
            harness.json_calls.append({"llm_id": llm_id, "user_msg": user_msg})
            sql = harness.model_sqls[min(len(harness.json_calls) - 1,
                                         len(harness.model_sqls) - 1)]
            return {"sql": sql}, {"promptTokens": 5, "completionTokens": 5,
                                  "estimatedCost": 0.001}

        self.agent._workflow_json_call = fake_json_call

        self._orig_dataiku = wf.dataiku

        class _DS(object):
            def __init__(self, name):
                self.name = name

            def get_location_info(self):
                return {"info": {"quotedResolvedTableName":
                                 '"CAT_owismind_agent_catalog_v1"'}}

        wf.dataiku = types.SimpleNamespace(
            Dataset=_DS,
            SQLExecutor2=lambda dataset=None, connection=None:
                _FakeExecutor(harness),
            api_client=lambda: None)
        self.events = []
        self.writer = lambda ev: self.events.append(ev)
        self.trace = _FakeTrace()

    def tearDown(self):
        wf.dataiku = self._orig_dataiku

    def _step(self, keys=("cap_a", "cap_b")):
        return {"id": "S3", "kind": "correlate", "title": "Correlate",
                "task": "join revenue and tickets by customer",
                "capability_keys": list(keys)}

    def _run(self, **kw):
        return self.agent._workflow_correlate(
            None, self.trace, "smart", "fr", self._step(**kw), 3, self.writer)

    def test_happy_path_payload_and_evidence(self):
        payload, usage = self._run()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["row_count"], 2)
        self.assertEqual(payload["columns"], self.result_columns)
        self.assertTrue(payload["all_sources_used"])
        self.assertEqual(payload["output_ref"], "#S3")
        self.assertLessEqual(len(payload["model_view"]["rows"]),
                             wf.CORRELATE_MODEL_ROWS)
        sql_item = payload["generated_sql"][0]
        self.assertTrue(sql_item["sql"].startswith("WITH d1 AS"))
        self.assertTrue(sql_item["sqlId"].startswith("s3qc"))
        # Evidence span emitted with the frozen contract keys
        span = [s for s in self.trace.spans
                if s.name == "semantic-model-query"][0]
        self.assertEqual(span.outputs["row_count"], 2)
        self.assertIn("EXPLAIN", " ".join(self.sql_log))
        self.assertGreaterEqual(usage.get("promptTokens", 0), 5)
        # SQL generation NEVER degrades: pinned to the claude tier even in smart
        self.assertEqual(self.json_calls[0]["llm_id"],
                         wf.LOOP_LLM_BY_MODE["claude"])

    def test_model_never_sees_physical_tables(self):
        self._run()
        for call in self.json_calls:
            self.assertNotIn("OWISMIND_DEV", call["user_msg"])
            self.assertNotIn("CAT_owismind", call["user_msg"])
            self.assertIn("d1:", call["user_msg"])

    def test_needs_at_least_two_sources(self):
        payload, _ = self._run(keys=("cap_a",))
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "correlate_needs_2_sources")

    def test_disabled_or_unknown_capability_refused(self):
        self.agent._caps["cap_b"]["enabled"] = False
        payload, _ = self._run()
        self.assertEqual(payload["error"], "capability_unavailable")
        payload, _ = self.agent._workflow_correlate(
            None, self.trace, "smart", "fr",
            {"id": "S3", "kind": "correlate", "task": "x",
             "capability_keys": ["cap_a", "ghost"]}, 3, self.writer)
        self.assertEqual(payload["error"], "capability_unavailable")

    def test_missing_catalog_generation_is_unavailable(self):
        self.agent._caps["cap_b"].pop("catalog_generation")
        payload, _ = self._run()
        self.assertTrue(payload["error"].startswith("correlate_unavailable"))

    def test_guarded_sql_rejection_consumes_a_fix_then_fails(self):
        self.model_sqls = ["DROP TABLE d1"] * 3
        payload, _ = self._run()
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "correlate_failed")
        self.assertEqual(len(self.json_calls), 1 + wf.CORRELATE_MAX_FIXES)

    def test_db_error_feeds_correction_then_succeeds(self):
        self.explain_error = 'column "revenu" does not exist'
        first = ['SELECT d1."revenu" FROM d1 JOIN d2 ON true']
        good = self.model_sqls[0]
        self.model_sqls = first + [good]

        harness = self

        class _HealingExecutor(_FakeExecutor):
            def query_to_df(self, sql, pre_queries=None, post_queries=None):
                if sql.strip().lower().startswith("explain") \
                        and '"revenu"' not in sql:
                    harness.explain_error = None
                return _FakeExecutor.query_to_df(self, sql, pre_queries,
                                                 post_queries)

        wf.dataiku.SQLExecutor2 = (
            lambda dataset=None, connection=None: _HealingExecutor(harness))
        payload, _ = self._run()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(len(self.json_calls), 2)
        self.assertIn("does not exist", self.json_calls[1]["user_msg"])

    def test_zero_write_enforced_by_harness(self):
        # The fake executor raises on any non-SELECT/EXPLAIN/WITH statement and
        # on any commit; a full happy run under it proves the read-only path.
        payload, _ = self._run()
        self.assertEqual(payload["status"], "ok")
        for sql in self.sql_log:
            self.assertTrue(sql.strip().lower()
                            .startswith(("select", "explain", "with")))


if __name__ == "__main__":
    unittest.main()
