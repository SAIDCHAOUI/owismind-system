"""suggest.set ("Go further" next steps), backend side of the shared contract.

  - contract parity: the op, its limits and the reduced-state key are declared in
    ``contracts/workspace_protocol.v1.json`` with the same values as protocol.py;
  - the shared fixture ``contracts/fixtures/workspace_suggestions_cases.json`` (also
    loaded by the frontend reducer tests): normalization (trim, per-item drop,
    dedupe, first 3, op dropped when nothing is valid) and reduction (last wins, key
    ABSENT when none, summary / widgets untouched, never carried);
  - sanitize keeps (and re-validates) stored suggestions; finalize keeps them;
    build_carry never carries them; is_empty counts them (the row is persisted);
  - end to end: streaming relays the op, the worker persists a suggestions-only run
    without widgets, and a suggestions-only ancestor never hides the real Studio
    of an older exchange (continuity fallback);
  - /conversation flags (storage.workspace_flags): has_workspace = plan or widgets,
    stored suggestions attached per row from ONE bounded read-only lookup;
  - GET /workspace serves the stored suggestions with the state.
Fully stubbed, no DSS runtime.
"""
import copy
import json
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
sys.path.insert(0, _HERE)

import _dss_stub  # noqa: E402

_dss_stub.install()

from owismind.workspace import protocol as p  # noqa: E402
from owismind.workspace import reducer  # noqa: E402

CONTRACTS = os.path.join(_HERE, "..", "contracts")
FIXTURE = os.path.join(CONTRACTS, "fixtures", "workspace_suggestions_cases.json")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


A = "Comparer 2026 au budget mois par mois"
B = "Voir la répartition par offre"


def _op(seq, items):
    return {"type": "workspace", "v": 1, "op": "suggest.set", "seq": seq, "items": items}


class ContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = _load(os.path.join(CONTRACTS, "workspace_protocol.v1.json"))
        cls.fixture = _load(FIXTURE)

    def test_op_declared(self):
        self.assertIn("suggest.set", p.OPS)
        self.assertIn("suggest.set", self.contract["enums"]["ops"])
        self.assertIn("suggest.set", self.contract["$defs"]["envelope"]["properties"]["op"]["enum"])
        self.assertIn("suggest.set", self.contract["events"])

    def test_limits_match(self):
        caps = self.contract["caps"]
        self.assertEqual(caps["suggestions_max_items"], p.SUGGESTIONS_MAX_ITEMS)
        self.assertEqual(caps["suggestion_min_chars"], p.SUGGESTION_MIN_CHARS)
        self.assertEqual(caps["suggestion_max_chars"], p.SUGGESTION_MAX_CHARS)
        self.assertEqual((p.SUGGESTIONS_MAX_ITEMS, p.SUGGESTION_MIN_CHARS,
                          p.SUGGESTION_MAX_CHARS), (3, 8, 120))
        self.assertEqual(self.fixture["limits"], {
            "suggestions_max_items": 3, "suggestion_min_chars": 8, "suggestion_max_chars": 120})
        for schema in (self.contract["events"]["suggest.set"]["properties"]["items"],
                       self.contract["reduced_state"]["properties"]["suggestions"]):
            self.assertEqual(schema["maxItems"], p.SUGGESTIONS_MAX_ITEMS)
            self.assertEqual(schema["items"]["minLength"], p.SUGGESTION_MIN_CHARS)
            self.assertEqual(schema["items"]["maxLength"], p.SUGGESTION_MAX_CHARS)

    def test_state_key_optional(self):
        # "No suggestions" = key ABSENT: it is not a required reduced-state key.
        self.assertNotIn("suggestions", self.contract["reduced_state"]["required"])
        self.assertNotIn("suggestions", reducer.empty_state())


class SharedFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = _load(FIXTURE)

    def test_normalize_cases(self):
        cases = self.fixture["normalize_cases"]
        self.assertGreaterEqual(len(cases), 10)
        self.assertTrue(any(c["expected"] is None for c in cases))
        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertEqual(p.normalize_op(case["input"], case["default_ts"]),
                                 case["expected"])
                if case["expected"] is not None:
                    self.assertEqual(p.normalize_op(case["expected"]), case["expected"])

    def test_reducer_cases(self):
        cases = self.fixture["reducer_cases"]
        self.assertGreaterEqual(len(cases), 6)
        for case in cases:
            with self.subTest(case=case["name"]):
                state = reducer.reduce_events(case["events"])
                self.assertEqual(state, case["expected"])
                self.assertEqual(state.get("suggestions"), case["expected_suggestions"])
                self.assertEqual(not reducer.is_empty(state), case["persisted"])
                opens = bool(state["plan"] or state["notes"] or state["widgets"])
                self.assertEqual(opens, case["opens_studio"])

    def test_expected_items_respect_the_limits(self):
        for case in self.fixture["normalize_cases"]:
            for item in (case["expected"] or {}).get("items", []):
                self.assertEqual(item, item.strip())
                self.assertTrue(8 <= len(item) <= 120, case["name"])


class ProjectionTests(unittest.TestCase):
    def test_garbage_never_raises(self):
        for junk in (None, 5, "x", {"items": [A]}, {"v": 1, "op": "suggest.set", "seq": 1,
                                                     "items": {"a": A}}):
            self.assertIsNone(p.normalize_op(junk))
        self.assertEqual(p.suggestion_items(None), [])
        self.assertEqual(p.suggestion_items(A), [])

    def test_long_input_list_bounded(self):
        items = ["Suggestion numéro %d" % i for i in range(5000)]
        self.assertEqual(p.suggestion_items(items), items[:3])

    def test_summary_and_finalize_ignore_suggestions(self):
        state = reducer.apply(reducer.empty_state(), _op(1, [A, B]))
        self.assertEqual(state["summary"], {"widget_ids_by_step": {}, "sql_ids": []})
        final = reducer.finalize(state, "done", "ex-1", known_sql_ids=[])
        self.assertEqual(final["suggestions"], [A, B])
        self.assertEqual(final["widgets"], [])
        self.assertEqual(final["summary"], state["summary"])

    def test_apply_never_mutates_input(self):
        state = reducer.apply(reducer.empty_state(), _op(1, [A]))
        snapshot = copy.deepcopy(state)
        new = reducer.apply(state, _op(2, [B]))
        self.assertEqual(state, snapshot)
        self.assertEqual(new["suggestions"], [B])
        new["suggestions"].append("mutated")
        self.assertEqual(state["suggestions"], [A])


class SanitizeTests(unittest.TestCase):
    def _doc(self, **extra):
        doc = reducer.finalize(reducer.empty_state(), "done", "ex-1")
        doc.update(extra)
        return doc

    def test_stored_suggestions_kept(self):
        doc = reducer.sanitize(self._doc(suggestions=[A, B]))
        self.assertEqual(doc["suggestions"], [A, B])
        self.assertFalse(reducer.is_empty(doc))

    def test_stored_suggestions_revalidated(self):
        doc = reducer.sanitize(self._doc(suggestions=["  " + A, A.upper(), "x", 3, B,
                                                      "Voir les tickets ouverts", "Encore une"]))
        self.assertEqual(doc["suggestions"], [A, B, "Voir les tickets ouverts"])

    def test_invalid_or_empty_reads_as_absent(self):
        for bad in ([], ["x"], "Comparer au budget", {"a": A}, None):
            with self.subTest(bad=bad):
                doc = reducer.sanitize(self._doc(suggestions=bad))
                self.assertNotIn("suggestions", doc)
                self.assertTrue(reducer.is_empty(doc))

    def test_sanitize_idempotent(self):
        once = reducer.sanitize(self._doc(suggestions=[A]))
        self.assertEqual(reducer.sanitize(once), once)


class CarryTests(unittest.TestCase):
    _BASE = {"v": 1, "status": "done", "last_seq": 3, "plan": None, "notes": [],
             "widgets": [{"id": "w1", "kind": "text", "title": "T", "text": "x"}],
             "provenance": {}, "suggestions": [A, B],
             "summary": {"widget_ids_by_step": {}, "sql_ids": []}}

    def test_build_carry_drops_suggestions(self):
        carry = reducer.build_carry(reducer.sanitize(self._BASE), "ex-base", 1)
        self.assertEqual(sorted(carry), ["base_exchange_id", "op", "seq", "type", "v",
                                         "widgets"])
        state = reducer.apply_carry(reducer.empty_state(), carry)
        self.assertNotIn("suggestions", state)
        self.assertEqual([w["id"] for w in state["widgets"]], ["w1"])

    def test_normalize_carry_drops_suggestion_keys(self):
        carry = {"v": 1, "op": "studio.carry", "seq": 1, "base_exchange_id": "ex-base",
                 "widgets": [], "suggestions": [A], "items": [A]}
        norm = p.normalize_carry(carry)
        self.assertNotIn("suggestions", norm)
        self.assertNotIn("items", norm)

    def test_suggest_set_not_a_carry(self):
        self.assertIsNone(p.normalize_carry({"v": 1, "op": "suggest.set", "seq": 1,
                                             "items": [A]}))


# --- end to end: streaming -> worker -> persistence ---------------------------------
from owismind.agents import stream_manager, streaming  # noqa: E402
import test_streaming_workspace as tsw  # noqa: E402


def _ws_chunk(data):
    return {"type": "event", "eventKind": "WORKSPACE", "eventData": data}


class WorkerSuggestionsTests(tsw._WorkerBase):
    def test_relayed_and_suggestions_only_run_persisted(self):
        chunks = [_ws_chunk({"v": 1, "op": "suggest.set", "seq": 1, "items": [A, B, A]}),
                  _ws_chunk({"v": 1, "op": "suggest.set", "seq": 2, "items": ["court"]})]
        with self.assertLogs("owismind.agents.streaming", level="WARNING"):
            events = self._run("r-sugg", chunks, "ex-sugg")
        ws = [e for e in events if e["type"] == "workspace"]
        self.assertEqual(len(ws), 1)                     # the invalid op is dropped
        self.assertEqual((ws[0]["op"], ws[0]["items"]), ("suggest.set", [A, B]))
        self.assertIn("ts", ws[0])
        self.assertEqual(len(self.saved), 1)
        exchange_id, _uid, _sid, state = self.saved[0]
        self.assertEqual(exchange_id, "ex-sugg")
        self.assertEqual(state["suggestions"], [A, B])
        self.assertEqual(state["status"], "done")
        self.assertEqual((state["plan"], state["widgets"], state["notes"]), (None, [], []))
        self.assertEqual(state["summary"], {"widget_ids_by_step": {}, "sql_ids": []})
        # The stored row reads back intact (storage re-sanitizes before write).
        self.assertEqual(reducer.sanitize(state), state)

    def test_suggestions_alongside_widgets(self):
        fx = tsw._load("workspace_run_multi_facet.json")
        last_seq = max(e["seq"] for e in fx["expected_events"])
        chunks = list(fx["raw_chunks"])
        chunks.append(_ws_chunk({"v": 1, "op": "suggest.set", "seq": last_seq + 1,
                                 "items": [A]}))
        self._run("r-sugg-w", chunks, fx["exchange_id"])
        state = self.saved[0][3]
        final = tsw._load(fx["expected_reduced"])["final"]
        expected = dict(final, suggestions=[A], last_seq=last_seq + 1)
        self.assertEqual(state, expected)


class StudioBaseFallbackTests(unittest.TestCase):
    """A suggestions-only ancestor (no widgets) must not hide the older real Studio."""

    def setUp(self):
        self._orig = stream_manager.workspaces_storage
        self.meta_calls = []
        test = self
        with_widgets = {"v": 1, "status": "done", "widgets": [{"id": "w1"}]}
        only_sugg = {"v": 1, "status": "done", "widgets": [], "suggestions": [A]}
        self.meta = {"ex-3": (only_sugg, "s"), "ex-2": (only_sugg, "s"),
                     "ex-1": (with_widgets, "s"), "ex-0": (with_widgets, "s")}
        self.with_ws = {"ex-3", "ex-2", "ex-1", "ex-0"}

        class _Storage(object):
            @staticmethod
            def workspace_exchange_ids(uid, ids):
                return set(test.with_ws)

            @staticmethod
            def read_workspace_meta(uid, ex):
                test.meta_calls.append(ex)
                return test.meta.get(ex, (None, None))

        stream_manager.workspaces_storage = _Storage

    def tearDown(self):
        stream_manager.workspaces_storage = self._orig

    def _resolve(self, screen_context=None, chain=("ex-3", "ex-2", "ex-1", "ex-0")):
        return stream_manager._resolve_studio_base("u", "ex-new", "s", screen_context,
                                                   list(chain))

    def test_skips_widgetless_ancestors(self):
        base = self._resolve()
        self.assertEqual(base[0], "ex-1")
        self.assertEqual(self.meta_calls, ["ex-3", "ex-2", "ex-1"])

    def test_probes_bounded(self):
        chain = ["ex-s%d" % i for i in range(10)] + ["ex-1"]
        for ex in chain[:-1]:
            self.meta[ex] = self.meta["ex-3"]
        self.with_ws = set(chain)
        self.assertIsNone(self._resolve(chain=chain))
        self.assertEqual(len(self.meta_calls), stream_manager.MAX_STUDIO_BASE_PROBES)

    def test_invalid_ancestor_still_stops(self):
        self.meta["ex-2"] = (self.meta["ex-1"][0], "other-session")
        self.assertIsNone(self._resolve())
        self.assertEqual(self.meta_calls, ["ex-3", "ex-2"])

    def test_pointer_to_widgetless_is_no_base(self):
        self.assertIsNone(self._resolve({"studio_exchange_id": "ex-3"}))
        self.assertEqual(self.meta_calls, ["ex-3"])


# --- storage.workspace_flags (/conversation) --------------------------------------
import test_workspace_storage as tws  # noqa: E402
from owismind.storage import workspaces as ws_storage  # noqa: E402


class WorkspaceFlagsTests(tws._Base):
    def test_one_bounded_owner_scoped_read_only_lookup(self):
        self.rows = [
            {"exchange_id": "e1", "has_studio": 0, "suggestions": json.dumps([A, "x", A.upper(), B])},
            {"exchange_id": "e2", "has_studio": 1, "suggestions": None},
            {"exchange_id": "e3", "has_studio": float("nan"), "suggestions": "{bad json"},
            {"exchange_id": "e9", "has_studio": 1, "suggestions": None},     # not asked
        ]
        out = ws_storage.workspace_flags("u.one", ["e1", "e2", "e2", "e3", None, 5])
        self.assertEqual(out, {"e1": {"studio": False, "suggestions": [A, B]},
                               "e2": {"studio": True, "suggestions": []},
                               "e3": {"studio": False, "suggestions": []}})
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertIn("user_id = 'u.one' AND exchange_id IN ('e1', 'e2', 'e3')", call["sql"])
        self.assertIn("SET LOCAL transaction_read_only TO on", call["pre"])
        self.assertIn("SET LOCAL statement_timeout TO '30000'", call["pre"])
        # Only two small facts leave the database, never the document itself.
        self.assertTrue(call["sql"].startswith("SELECT exchange_id, CASE WHEN"))
        self.assertNotIn("workspace FROM", call["sql"])
        self.assertIn("jsonb_typeof(w -> 'plan') = 'object'", call["sql"])
        self.assertIn("jsonb_typeof(w -> 'widgets' -> 0) IS NOT NULL", call["sql"])

    def test_bounded_and_skipped_when_empty(self):
        self.assertEqual(ws_storage.workspace_flags("u", []), {})
        self.assertEqual(self.calls, [])
        ws_storage.workspace_flags("u", ["e%d" % i for i in range(900)])
        self.assertEqual(self.calls[0]["sql"].count("'e"), ws_storage.MAX_LOOKUP_IDS)

    def test_oversize_suggestions_ignored(self):
        self.rows = [{"exchange_id": "e1", "has_studio": 1,
                      "suggestions": json.dumps([A] * 1000)}]
        self.assertEqual(ws_storage.workspace_flags("u", ["e1"]),
                         {"e1": {"studio": True, "suggestions": []}})


class WorkspaceFlagsFailureTests(tws._Base):
    boom = True

    def test_failure_reads_as_empty(self):
        self.assertEqual(ws_storage.workspace_flags("u", ["e1"]), {})


# --- GET /workspace -------------------------------------------------------------
import test_routes_workspace as trw  # noqa: E402


class RouteSuggestionsTests(trw._RouteBase):
    def test_workspace_serves_suggestions(self):
        self.state = reducer.sanitize(reducer.finalize(
            reducer.apply(reducer.empty_state(), _op(1, [A, B])), "done", "ex-1"))
        body = self._get({"exchange_id": "ex-1"})
        if isinstance(body, tuple):
            body = body[0]
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["workspace"]["suggestions"], [A, B])
        self.assertEqual(body["widgets_data"], {})
        self.assertEqual(body["resolved"], {})


if __name__ == "__main__":
    unittest.main()
