# Plugin/owismind/tests/test_events.py
"""Usage-analytics event capture - PURE layers, provable without a live DSS runtime:
  - storage.events.validate_events : whitelist filtering, caps, coercion, dedup (pure);
  - storage.events.record_events   : ONE committed multi-row INSERT ... ON CONFLICT DO
    NOTHING, server-side user_id, now() ts, best-effort never-raises (fake executor);
  - evidence.throttle track bucket : the /track flood gate (pure take_token core).
A minimal dataiku stub lets the modules import (unittest discover shares sys.modules).
"""
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))


def _ensure_dataiku_stub():
    """Minimal import-time stubs so events / migrations / sql_config import (NO install)."""
    dk = sys.modules.get("dataiku")
    if dk is None:
        dk = types.ModuleType("dataiku")
        sys.modules["dataiku"] = dk
    if not hasattr(dk, "SQLExecutor2"):
        dk.SQLExecutor2 = type("SQLExecutor2", (), {})
    if not hasattr(dk, "default_project_key"):
        dk.default_project_key = lambda: "OWISMIND_DEV"
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

from owismind.storage import events  # noqa: E402
from owismind.evidence.throttle import (  # noqa: E402
    TRACK_BUCKET_CAPACITY,
    TRACK_REFILL_PER_SEC,
    take_token,
)


def _ev(name="webapp_opened", **over):
    """A well-formed client event (override any field via kwargs)."""
    base = {
        "id": "e-%s" % name,
        "name": name,
        "client_ts": "2026-07-02T12:34:56.789Z",
        "seq": 1,
        "app_session_id": "sess-1",
        "view": "chat",
        "conversation_id": "conv-1",
        "agent_key": "ag_abc",
        "mode": "smart",
        "props": {"k": "v"},
    }
    base.update(over)
    return base


class EventCategoriesTests(unittest.TestCase):
    """The whitelist is the single source of truth (names -> category)."""

    def test_expected_size_and_categories(self):
        cats = set(events.EVENT_CATEGORIES.values())
        self.assertEqual(
            cats,
            {"nav", "chat", "ui", "evidence", "source", "feedback", "benchmark", "error"},
        )
        # 41 whitelisted names across the contract's categories.
        self.assertEqual(len(events.EVENT_CATEGORIES), 41)

    def test_known_name_maps(self):
        self.assertEqual(events.EVENT_CATEGORIES["question_sent"], "chat")
        self.assertEqual(events.EVENT_CATEGORIES["source_cell_clicked"], "source")
        # First-class evidence tab-view names (the split of evidence_tab_changed).
        self.assertEqual(events.EVENT_CATEGORIES["evidence_proof_viewed"], "evidence")
        self.assertEqual(events.EVENT_CATEGORIES["source_data_viewed"], "evidence")
        self.assertEqual(events.EVENT_CATEGORIES["chart_viewed"], "evidence")
        # Screen-context consent analytics (offer / include / dismiss).
        self.assertEqual(events.EVENT_CATEGORIES["screen_context_offered"], "chat")
        self.assertEqual(events.EVENT_CATEGORIES["screen_context_included"], "chat")
        self.assertEqual(events.EVENT_CATEGORIES["screen_context_dismissed"], "chat")


class ValidateEventsWhitelistTests(unittest.TestCase):
    def test_unknown_name_dropped(self):
        self.assertEqual(events.validate_events([_ev(name="hack_event")]), [])

    def test_missing_name_dropped(self):
        bad = _ev()
        del bad["name"]
        self.assertEqual(events.validate_events([bad]), [])

    def test_non_dict_items_dropped(self):
        out = events.validate_events(["x", 3, None, _ev()])
        self.assertEqual(len(out), 1)

    def test_non_list_input_is_empty(self):
        self.assertEqual(events.validate_events(None), [])
        self.assertEqual(events.validate_events({"events": []}), [])

    def test_category_stamped_from_whitelist(self):
        out = events.validate_events([_ev(name="theme_changed")])
        self.assertEqual(out[0]["category"], "ui")


class ValidateEventsIdTests(unittest.TestCase):
    def test_missing_id_dropped(self):
        bad = _ev()
        del bad["id"]
        self.assertEqual(events.validate_events([bad]), [])

    def test_non_string_id_dropped(self):
        self.assertEqual(events.validate_events([_ev(id=123)]), [])

    def test_oversized_id_dropped(self):
        self.assertEqual(events.validate_events([_ev(id="x" * 65)]), [])

    def test_max_length_id_kept(self):
        out = events.validate_events([_ev(id="x" * events.MAX_EVENT_ID_CHARS)])
        self.assertEqual(len(out), 1)

    def test_duplicate_ids_deduplicated_in_batch(self):
        out = events.validate_events([_ev(id="same"), _ev(id="same", name="page_viewed")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], "same")


class ValidateEventsCapsTests(unittest.TestCase):
    def test_batch_capped_at_40(self):
        many = [_ev(id="e%d" % i) for i in range(100)]
        self.assertEqual(len(events.validate_events(many)), events.MAX_EVENTS_PER_BATCH)

    def test_props_over_cap_becomes_truncated_sentinel(self):
        big = {"blob": "z" * (events.MAX_PROPS_JSON_CHARS + 100)}
        out = events.validate_events([_ev(props=big)])
        self.assertEqual(out[0]["props"], '{"_truncated": true}')

    def test_props_non_dict_is_none(self):
        self.assertIsNone(events.validate_events([_ev(props="nope")])[0]["props"])
        self.assertIsNone(events.validate_events([_ev(props={})])[0]["props"])

    def test_props_small_object_serialized(self):
        out = events.validate_events([_ev(props={"a": 1})])
        self.assertEqual(out[0]["props"], '{"a":1}')

    def test_string_fields_truncated_to_column_widths(self):
        out = events.validate_events([_ev(
            view="v" * 200, conversation_id="c" * 200,
            agent_key="a" * 200, app_session_id="s" * 200)])[0]
        self.assertEqual(len(out["view"]), 64)
        self.assertEqual(len(out["conversation_id"]), 64)
        self.assertEqual(len(out["agent_key"]), 64)
        self.assertEqual(len(out["app_session_id"]), 64)


class ValidateEventsCoercionTests(unittest.TestCase):
    def test_client_ts_zulu_parsed_to_castable_iso(self):
        out = events.validate_events([_ev(client_ts="2026-07-02T12:34:56.789Z")])[0]
        self.assertTrue(out["client_ts"].startswith("2026-07-02T12:34:56"))
        self.assertIn("+00:00", out["client_ts"])

    def test_client_ts_invalid_is_none(self):
        self.assertIsNone(events.validate_events([_ev(client_ts="not-a-date")])[0]["client_ts"])
        self.assertIsNone(events.validate_events([_ev(client_ts=12345)])[0]["client_ts"])

    def test_client_ts_missing_is_none(self):
        bad = _ev()
        del bad["client_ts"]
        self.assertIsNone(events.validate_events([bad])[0]["client_ts"])

    def test_seq_coerced_to_int_or_none(self):
        self.assertEqual(events.validate_events([_ev(seq="7")])[0]["seq"], 7)
        self.assertIsNone(events.validate_events([_ev(seq="x")])[0]["seq"])
        self.assertIsNone(events.validate_events([_ev(seq=True)])[0]["seq"])

    def test_mode_whitelisted_or_none(self):
        self.assertEqual(events.validate_events([_ev(mode="pro")])[0]["mode"], "pro")
        self.assertIsNone(events.validate_events([_ev(mode="turbo")])[0]["mode"])
        self.assertIsNone(events.validate_events([_ev(mode=None)])[0]["mode"])

    def test_optional_empty_strings_become_none(self):
        out = events.validate_events([_ev(view="", conversation_id="  ", agent_key=None)])[0]
        self.assertIsNone(out["view"])
        self.assertIsNone(out["conversation_id"])
        self.assertIsNone(out["agent_key"])


class _FakeExec:
    def __init__(self, sink):
        self._sink = sink

    def query_to_df(self, sql, pre_queries=None, post_queries=None):
        self._sink.append({"sql": sql, "pre": list(pre_queries or []),
                           "post": list(post_queries or [])})
        return None


class RecordEventsTests(unittest.TestCase):
    """record_events writes ONE committed multi-row INSERT and never raises."""

    def setUp(self):
        self.calls = []
        self._orig = {
            "new_executor": events.new_executor,
            "ensure_events_table": events.ensure_events_table,
        }
        events.new_executor = lambda: _FakeExec(self.calls)
        events.ensure_events_table = lambda: None

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(events, name, fn)

    def _record(self, raw):
        clean = events.validate_events(raw)
        return events.record_events("server.user", clean)

    def test_one_committed_multi_row_insert(self):
        accepted = self._record([_ev(id="a"), _ev(id="b", name="page_viewed")])
        self.assertEqual(accepted, 2)
        self.assertEqual(len(self.calls), 1)                 # one transaction
        call = self.calls[0]
        self.assertEqual(call["post"], ["COMMIT"])           # explicit COMMIT
        self.assertEqual(len(call["pre"]), 2)                # timeout guard + INSERT
        self.assertIn("statement_timeout", call["pre"][0])
        insert = call["pre"][1]
        self.assertIn("INSERT INTO", insert)
        self.assertIn("ON CONFLICT (event_id) DO NOTHING", insert)
        # A multi-row VALUES list: two tuples -> exactly one separating "), (".
        self.assertEqual(insert.count("), ("), 1)

    def test_ts_is_server_now_and_user_id_is_server_side(self):
        self._record([_ev(id="a")])
        insert = self.calls[0]["pre"][1]
        self.assertIn("now()", insert)                       # authoritative server ts
        self.assertIn("'server.user'", insert)               # server-resolved identity

    def test_column_order_matches_ddl(self):
        self._record([_ev(id="a")])
        insert = self.calls[0]["pre"][1]
        self.assertIn(
            "(event_id, ts, client_ts, seq, user_id, app_session_id, event_name, "
            "event_category, view_name, conversation_id, agent_key, mode, props)",
            insert,
        )

    def test_absent_nullable_fields_write_null(self):
        # No client_ts / seq / view / conversation_id / agent_key / mode / props.
        self._record([{"id": "min", "name": "webapp_opened", "app_session_id": "s"}])
        insert = self.calls[0]["pre"][1]
        self.assertIn("NULL", insert)                        # nullable columns -> NULL

    def test_noop_when_no_events(self):
        self.assertEqual(events.record_events("u", []), 0)
        self.assertEqual(self.calls, [])

    def test_noop_when_no_user(self):
        self.assertEqual(events.record_events("", events.validate_events([_ev()])), 0)
        self.assertEqual(self.calls, [])

    def test_never_raises_returns_zero_on_executor_failure(self):
        class _Boom:
            def query_to_df(self, *a, **k):
                raise RuntimeError("db down")

        events.new_executor = lambda: _Boom()
        # Must swallow the error and report 0 (best-effort contract).
        self.assertEqual(self._record([_ev(id="a")]), 0)


class TrackThrottleTests(unittest.TestCase):
    """The /track ingest gate: capacity 12, refill 0.5/s (pure take_token core)."""

    def test_capacity_then_denied(self):
        buckets = {}
        for i in range(TRACK_BUCKET_CAPACITY):
            self.assertTrue(
                take_token(buckets, "u", 0.0, TRACK_BUCKET_CAPACITY, TRACK_REFILL_PER_SEC),
                "req %d" % i)
        self.assertFalse(
            take_token(buckets, "u", 0.0, TRACK_BUCKET_CAPACITY, TRACK_REFILL_PER_SEC))

    def test_slow_refill_re_allows_after_two_seconds(self):
        buckets = {}
        for _ in range(TRACK_BUCKET_CAPACITY):
            take_token(buckets, "u", 0.0, TRACK_BUCKET_CAPACITY, TRACK_REFILL_PER_SEC)
        self.assertFalse(
            take_token(buckets, "u", 0.0, TRACK_BUCKET_CAPACITY, TRACK_REFILL_PER_SEC))
        # 0.5 tokens/s -> after 2s one token is back (one more request passes, then denied).
        self.assertTrue(
            take_token(buckets, "u", 2.0, TRACK_BUCKET_CAPACITY, TRACK_REFILL_PER_SEC))
        self.assertFalse(
            take_token(buckets, "u", 2.0, TRACK_BUCKET_CAPACITY, TRACK_REFILL_PER_SEC))


if __name__ == "__main__":
    unittest.main()
