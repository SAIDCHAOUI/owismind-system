# Plugin/owismind/tests/test_cascading_distinct.py
"""Cascading distinct-value pickers (A4): the /source/distinct + /evidence/distinct
POST request validators AND the service functions that scope the picker by the OTHER
active filters.

Two layers are exercised, mirroring test_source_aggregate.py:
  - the request validators (pure shape/bounds), and
  - ``source_service.source_distinct`` / ``evidence.service.evidence_distinct`` with the
    dataiku-bound seams stubbed (``_resolve_source`` / ``_context`` + the query runners
    monkeypatched), so the WHERE fragments the picker builds are provable without a DSS
    instance.

The picker must only offer values compatible with the OTHER currently-active filters (the
trap the redesign removes: picking a value with zero rows under an active filter). A request
WITHOUT the new fields must stay byte-identical to the pre-cascade picker.
"""
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))


def _ensure_dataiku_stub():
    """Minimal import-time stubs (NO install - the README's "(or a stub)" idiom).

    Both services import evidence.service (and transitively dataiku / SQLExecutor2 /
    dataiku.sql / pandas) at module load. The functions under test never touch them (the
    executing seams are monkeypatched), so bare stubs suffice - and existing stubs from
    sibling test files are EXTENDED, never replaced (unittest discover shares sys.modules).
    ``toSQL`` renders a value as its ``repr`` so quoted SQL fragments read cleanly.
    """
    dk = sys.modules.get("dataiku")
    if dk is None:
        dk = types.ModuleType("dataiku")
        sys.modules["dataiku"] = dk
    if not hasattr(dk, "SQLExecutor2"):
        dk.SQLExecutor2 = type("SQLExecutor2", (), {})
    if not hasattr(dk, "Dataset"):
        dk.Dataset = type("Dataset", (), {})
    sql_mod = sys.modules.get("dataiku.sql")
    if sql_mod is None:
        sql_mod = types.ModuleType("dataiku.sql")
        sys.modules["dataiku.sql"] = sql_mod
    if not hasattr(sql_mod, "Constant"):
        sql_mod.Constant = lambda value: value
    if not hasattr(sql_mod, "toSQL"):
        sql_mod.toSQL = lambda constant, dialect=None: repr(constant)
    if not hasattr(sql_mod, "Dialects"):
        sql_mod.Dialects = type("Dialects", (), {"POSTGRES": "postgres"})
    dk.sql = sql_mod
    if "pandas" not in sys.modules:
        sys.modules["pandas"] = types.ModuleType("pandas")


_ensure_dataiku_stub()

from owismind.evidence import service  # noqa: E402
from owismind.evidence import source_service  # noqa: E402
from owismind.evidence.service import EvidenceError  # noqa: E402
from owismind.security.validation import (  # noqa: E402
    ValidationError,
    validate_evidence_distinct_request,
    validate_source_distinct_request,
)


# --------------------------------------------------------------------------------------
# Request validators (pure)
# --------------------------------------------------------------------------------------


class SourceDistinctRequestTests(unittest.TestCase):
    def test_valid_roundtrip(self):
        out = validate_source_distinct_request({
            "agent": "  ag_x  ", "source": "2", "column": "Customer Id",
            "q": "  algerie ",
            "filters": [{"column": "metric", "op": "=", "values": ["Actuals"]}],
            "scope_q": "  paris ",
        })
        agent, source_id, column, q, filters, scope_q = out
        self.assertEqual(agent, "ag_x")
        self.assertEqual(source_id, 2)
        self.assertEqual(column, "Customer Id")
        self.assertEqual(q, "algerie")
        self.assertEqual(filters, [{"column": "metric", "op": "=", "values": ["Actuals"]}])
        self.assertEqual(scope_q, "paris")

    def test_defaults_empty_scope(self):
        # Without filters / scope_q the request validates to empty scope (the legacy picker).
        agent, source_id, column, q, filters, scope_q = validate_source_distinct_request(
            {"agent": "ag_x", "source": 0, "column": "c"})
        self.assertEqual(filters, [])
        self.assertEqual(q, "")
        self.assertEqual(scope_q, "")

    def test_between_filter_accepted(self):
        _a, _s, _c, _q, filters, _sq = validate_source_distinct_request({
            "agent": "ag_x", "source": 0, "column": "c",
            "filters": [{"column": "created", "op": "BETWEEN",
                         "values": ["2025-01-01", "2025-12-31"]}],
        })
        self.assertEqual(filters[0]["op"], "BETWEEN")

    def test_bad_filter_op_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_source_distinct_request({
                "agent": "ag_x", "source": 0, "column": "c",
                "filters": [{"column": "c", "op": ">", "values": ["1"]}],
            })
        self.assertEqual(ctx.exception.code, "invalid_filter_op")

    def test_missing_column_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_source_distinct_request({"agent": "ag_x", "source": 0})
        self.assertEqual(ctx.exception.code, "invalid_filter_column")

    def test_bad_agent_and_source_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_source_distinct_request({"agent": "", "source": 0, "column": "c"})
        self.assertEqual(ctx.exception.code, "invalid_agent")
        with self.assertRaises(ValidationError) as ctx:
            validate_source_distinct_request({"agent": "ag_x", "source": -1, "column": "c"})
        self.assertEqual(ctx.exception.code, "invalid_source")

    def test_non_dict_payload_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_source_distinct_request(None)
        self.assertEqual(ctx.exception.code, "invalid_payload")


class EvidenceDistinctRequestTests(unittest.TestCase):
    def test_valid_roundtrip(self):
        out = validate_evidence_distinct_request({
            "exchange_id": "ex1", "column": "solution",
            "q": "  ob ", "exclude_id": "5",
            "filters": [{"column": "metric", "op": "IN", "values": ["Actuals", "Budget"]}],
            "kept_ids": [1, 3], "include_advanced": True,
            "drill": [{"column": "country", "value": "FR"}],
            "scope_q": "  paris ",
        })
        (exchange_id, column, exclude_id, q, filters, kept_ids, include_advanced,
         drill, scope_q) = out
        self.assertEqual(exchange_id, "ex1")
        self.assertEqual(column, "solution")
        self.assertEqual(exclude_id, 5)
        self.assertEqual(q, "ob")
        self.assertEqual(filters, [{"column": "metric", "op": "IN",
                                    "values": ["Actuals", "Budget"]}])
        self.assertEqual(kept_ids, [1, 3])
        self.assertTrue(include_advanced)
        self.assertEqual(drill, [{"column": "country", "value": "FR"}])
        self.assertEqual(scope_q, "paris")

    def test_defaults_empty_scope(self):
        # Without the new fields the request validates to empty scope (legacy picker).
        out = validate_evidence_distinct_request({"exchange_id": "ex1", "column": "c"})
        (_eid, _col, exclude_id, q, filters, kept_ids, include_advanced,
         drill, scope_q) = out
        self.assertIsNone(exclude_id)
        self.assertEqual(q, "")
        self.assertEqual(filters, [])
        self.assertEqual(kept_ids, [])
        self.assertFalse(include_advanced)
        self.assertEqual(drill, [])
        self.assertEqual(scope_q, "")

    def test_exclude_id_malformed_degrades_to_none(self):
        # Negative / non-numeric / bool -> None (never raises: the picker just keeps every
        # locked predicate). A valid non-negative int passes through.
        for bad in (-1, "nope", True, False, None, {}):
            out = validate_evidence_distinct_request(
                {"exchange_id": "ex1", "column": "c", "exclude_id": bad})
            self.assertIsNone(out[2], bad)
        out = validate_evidence_distinct_request(
            {"exchange_id": "ex1", "column": "c", "exclude_id": 0})
        self.assertEqual(out[2], 0)

    def test_between_filter_accepted(self):
        out = validate_evidence_distinct_request({
            "exchange_id": "ex1", "column": "c",
            "filters": [{"column": "created", "op": "BETWEEN",
                         "values": ["2025-01-01", "2025-12-31"]}],
        })
        self.assertEqual(out[4][0]["op"], "BETWEEN")

    def test_bad_kept_ids_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_evidence_distinct_request(
                {"exchange_id": "ex1", "column": "c", "kept_ids": [-1]})
        self.assertEqual(ctx.exception.code, "invalid_kept_ids")

    def test_bad_filter_op_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_evidence_distinct_request({
                "exchange_id": "ex1", "column": "c",
                "filters": [{"column": "c", "op": "LIKE", "values": ["x"]}],
            })
        self.assertEqual(ctx.exception.code, "invalid_filter_op")

    def test_missing_exchange_id_rejected(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_evidence_distinct_request({"column": "c"})
        self.assertEqual(ctx.exception.code, "invalid_exchange_id")


# --------------------------------------------------------------------------------------
# source_service.source_distinct (cascading scope)
# --------------------------------------------------------------------------------------


def _source_ctx(columns):
    colmap = {c["name"].lower(): c["name"] for c in columns}
    return {"label": "L", "dataset": "DS", "table_ref": 'public."T"',
            "columns": columns, "colmap": colmap}


class _Recorder:
    """Stands in for the query runner: records each query, returns canned rows."""

    def __init__(self, *returns):
        self.queries = []
        self._returns = list(returns)

    def __call__(self, ctx, query, op_name):
        self.queries.append(query)
        return self._returns.pop(0) if self._returns else []


_COLS = [
    {"name": "country", "type": "string"},
    {"name": "amount", "type": "double"},
    {"name": "created", "type": "date"},
]


class SourceDistinctServiceTests(unittest.TestCase):
    def setUp(self):
        self._orig_resolve = source_service._resolve_source
        self._orig_run = source_service._run_source_query

    def tearDown(self):
        source_service._resolve_source = self._orig_resolve
        source_service._run_source_query = self._orig_run

    def _patch(self, columns, recorder):
        source_service._resolve_source = lambda ak, sid: _source_ctx(columns)
        source_service._run_source_query = recorder

    def test_legacy_no_scope_is_plain_distinct(self):
        # No filters, no scope_q, no q: a bare DISTINCT of the column (byte-identical to the
        # pre-cascade picker) - no filter predicate, no search fragment.
        rec = _Recorder([{"value": "FR"}])
        self._patch(_COLS, rec)
        source_service.source_distinct("ag_x", 0, "country")
        q = rec.queries[0]
        self.assertIn('SELECT DISTINCT "country" AS value', q)
        self.assertNotIn("ILIKE", q)
        self.assertNotIn(" = ", q)

    def test_cascading_filter_and_scope_search_and_column_search(self):
        # The OTHER filter (metric = Actuals) + the table-level scope_q (over ALL columns) +
        # the picker's own column search all scope the DISTINCT query.
        rec = _Recorder([{"value": "FR"}])
        self._patch(_COLS, rec)
        source_service.source_distinct(
            "ag_x", 0, "country", q="fr",
            filters=[{"column": "amount", "op": "=", "values": ["10"]}],
            scope_q="paris")
        q = rec.queries[0]
        self.assertIn('"amount" = ', q)                                    # the OTHER filter
        self.assertIn('concat_ws(\' \', "country", "amount", "created")', q)  # scope over all
        self.assertIn('concat_ws(\' \', "country")', q)                    # own column search
        self.assertIn('SELECT DISTINCT "country" AS value', q)

    def test_between_filter_scopes_picker(self):
        rec = _Recorder([{"value": "FR"}])
        self._patch(_COLS, rec)
        source_service.source_distinct(
            "ag_x", 0, "country",
            filters=[{"column": "created", "op": "BETWEEN",
                      "values": ["2025-01-01", "2025-12-31"]}])
        q = rec.queries[0]
        self.assertIn('"created" BETWEEN', q)
        self.assertIn("2025-01-01", q)

    def test_unknown_filter_column_rejected(self):
        rec = _Recorder()
        self._patch(_COLS, rec)
        with self.assertRaises(EvidenceError) as ctx:
            source_service.source_distinct(
                "ag_x", 0, "country",
                filters=[{"column": "nope", "op": "=", "values": ["x"]}])
        self.assertEqual(ctx.exception.code, "invalid_filter_column")
        self.assertEqual(rec.queries, [])


# --------------------------------------------------------------------------------------
# evidence.service.evidence_distinct (locked scope UNCHANGED + cascading additions)
# --------------------------------------------------------------------------------------


def _evidence_ctx(columns, predicates=None, advanced=None):
    colmap = {c["name"].lower(): c["name"] for c in columns}
    return {"dataset": "DS", "table_ref": 'public."T"',
            "columns": columns, "colmap": colmap,
            "predicates": predicates or [], "advanced": advanced,
            "sql": "SELECT * FROM t"}


class EvidenceDistinctServiceTests(unittest.TestCase):
    def setUp(self):
        self._orig_context = service._context
        self._orig_run = service._run_evidence_query
        self._orig_drill = service._drill_conditions

    def tearDown(self):
        service._context = self._orig_context
        service._run_evidence_query = self._orig_run
        service._drill_conditions = self._orig_drill

    def _patch(self, ctx, recorder):
        service._context = lambda uid, eid, preferred_table=None: ctx
        service._run_evidence_query = recorder

    _LOCKED = {"id": 5, "column": "country", "op": "=", "values": ["FR"], "editable": False}
    _EDITABLE = {"id": 7, "column": "amount", "op": "IN", "values": [1, 2], "editable": True}

    def test_locked_scope_unchanged_without_new_fields(self):
        # v1 behaviour: the locked (non-editable) predicate scopes the picker; the editable
        # =/IN chip does NOT (the user is picking it). No cascading fields present.
        rec = _Recorder([{"value": "OBS"}])
        self._patch(_evidence_ctx(_COLS, predicates=[self._LOCKED, self._EDITABLE]), rec)
        service.evidence_distinct("u", "ex", "created")
        q = rec.queries[0]
        self.assertIn('"country" = ', q)         # locked predicate scopes the picker
        self.assertNotIn('"amount"', q)          # the editable chip does not self-scope
        self.assertNotIn("ILIKE", q)

    def test_exclude_id_drops_the_edited_locked_predicate(self):
        rec = _Recorder([{"value": "FR"}])
        self._patch(_evidence_ctx(_COLS, predicates=[self._LOCKED]), rec)
        service.evidence_distinct("u", "ex", "country", exclude_id=5)
        q = rec.queries[0]
        self.assertNotIn('"country" = ', q)      # its own predicate must not scope its picker

    def test_kept_ids_none_applies_all_locked(self):
        # kept_ids None (a request that omits it): EVERY locked predicate applies - the
        # pre-kept_ids behaviour, byte-identical to before the fix.
        rec = _Recorder([{"value": "OBS"}])
        self._patch(_evidence_ctx(_COLS, predicates=[self._LOCKED, self._EDITABLE]), rec)
        service.evidence_distinct("u", "ex", "created", kept_ids=None)
        q = rec.queries[0]
        self.assertIn('"country" = ', q)         # locked predicate still scopes
        self.assertNotIn('"amount"', q)          # the editable chip never self-scopes

    def test_kept_ids_drops_removed_locked_predicate(self):
        # A locked predicate whose id is NOT in kept_ids (the user removed that agent chip)
        # must NOT scope the picker - mirroring the row window (_evidence_conditions).
        rec = _Recorder([{"value": "OBS"}])
        self._patch(_evidence_ctx(_COLS, predicates=[self._LOCKED]), rec)
        service.evidence_distinct("u", "ex", "created", kept_ids=[])
        self.assertNotIn('"country" = ', rec.queries[0])

    def test_kept_ids_keeps_present_locked_predicate(self):
        # A locked predicate whose id IS in kept_ids still scopes the picker.
        rec = _Recorder([{"value": "FR"}])
        self._patch(_evidence_ctx(_COLS, predicates=[self._LOCKED]), rec)
        service.evidence_distinct("u", "ex", "created", kept_ids=[5])
        self.assertIn('"country" = ', rec.queries[0])

    def test_kept_ids_gate_composes_with_exclude_id(self):
        # exclude_id and the kept_ids gate coexist: with both locked predicates KEPT
        # (ids in kept_ids), the one being edited (exclude_id) is still dropped while the
        # other one scopes.
        other = {"id": 9, "column": "amount", "op": "=", "values": [10], "editable": False}
        rec = _Recorder([{"value": "FR"}])
        self._patch(_evidence_ctx(_COLS, predicates=[self._LOCKED, other]), rec)
        service.evidence_distinct("u", "ex", "created", exclude_id=9, kept_ids=[5, 9])
        q = rec.queries[0]
        self.assertIn('"country" = ', q)         # id 5 kept, not edited -> scopes
        self.assertNotIn('"amount"', q)          # id 9 is being edited -> dropped

    def test_advanced_fragment_always_applies(self):
        rec = _Recorder([{"value": "FR"}])
        self._patch(_evidence_ctx(_COLS, advanced="amount > 0"), rec)
        service.evidence_distinct("u", "ex", "country")
        self.assertIn("amount > 0", rec.queries[0])

    def test_cascading_client_filter_scopes_picker(self):
        # A client editable/user filter (the OTHER active chip) now scopes the picker.
        rec = _Recorder([{"value": "OBS"}])
        self._patch(_evidence_ctx(_COLS), rec)
        service.evidence_distinct(
            "u", "ex", "country",
            filters=[{"column": "amount", "op": "=", "values": ["10"]}])
        q = rec.queries[0]
        self.assertIn('"amount" = ', q)
        self.assertIn('SELECT DISTINCT "country" AS value', q)

    def test_cascading_between_filter_scopes_picker(self):
        rec = _Recorder([{"value": "FR"}])
        self._patch(_evidence_ctx(_COLS), rec)
        service.evidence_distinct(
            "u", "ex", "country",
            filters=[{"column": "created", "op": "BETWEEN",
                      "values": ["2025-01-01", "2025-12-31"]}])
        self.assertIn('"created" BETWEEN', rec.queries[0])

    def test_scope_q_searches_all_columns(self):
        rec = _Recorder([{"value": "FR"}])
        self._patch(_evidence_ctx(_COLS), rec)
        service.evidence_distinct("u", "ex", "country", scope_q="paris")
        q = rec.queries[0]
        self.assertIn('concat_ws(\' \', "country", "amount", "created")', q)  # over ALL cols
        self.assertIn("ILIKE", q)

    def test_drill_conditions_scope_picker(self):
        # Drill conditions (re-derived server-side; the derivation is proven elsewhere) are
        # ADDED to the picker scope. Inject a marker condition via the patched builder.
        service._drill_conditions = lambda ctx, drill: ['"country" IS NULL']
        rec = _Recorder([{"value": "10"}])
        self._patch(_evidence_ctx(_COLS), rec)
        service.evidence_distinct(
            "u", "ex", "amount",
            drill=[{"column": "country", "value": None}])
        self.assertIn('"country" IS NULL', rec.queries[0])

    def test_column_search_appended_last(self):
        # The picker's OWN column search still applies on top of the cascading scope.
        rec = _Recorder([{"value": "FR"}])
        self._patch(_evidence_ctx(_COLS), rec)
        service.evidence_distinct("u", "ex", "country", q="fr")
        self.assertIn('concat_ws(\' \', "country")', rec.queries[0])

    def test_unknown_client_filter_column_rejected(self):
        rec = _Recorder()
        self._patch(_evidence_ctx(_COLS), rec)
        with self.assertRaises(EvidenceError) as ctx:
            service.evidence_distinct(
                "u", "ex", "country",
                filters=[{"column": "nope", "op": "=", "values": ["x"]}])
        self.assertEqual(ctx.exception.code, "invalid_filter_column")
        self.assertEqual(rec.queries, [])


if __name__ == "__main__":
    unittest.main()
