"""Security tests for the agent-factory console backend (2026-07 security lot D).

Locks the console hardening: bounded job admission (at most 4 running jobs, a
single mutating execute at a time, HTTP 429 beyond, slot freed in the worker's
finally), unguessable uuid4 job ids, and size caps on the hub write routes
(prompt length, capabilities entry count and serialized weight).

DSS-free AND flask-free: flask is not importable locally, so the backend file
is exec'd with a stub ``flask`` module (the route functions are then called
directly with a scripted request) plus the stub ``dataiku`` module used by the
other test files. The real ``owismind_factory`` modules are imported and
monkeypatched per test.

Run from the repo root:
    python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests -v
"""

import os
import re
import sys
import threading
import time
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_PARENT = os.path.abspath(os.path.join(_HERE, "..", "project-library", "python"))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

_BACKEND_PATH = os.path.abspath(os.path.join(
    _HERE, "..", "webapps", "agent-factory-console", "backend.py"))


# ----------------------------------------------------------------- stubs

class _FakeRequest(object):
    """Stand-in for flask.request: tests script .json_body / .args per call."""

    def __init__(self):
        self.json_body = None
        self.args = {}

    def get_json(self, silent=False):
        return self.json_body


class _FakeProject(object):
    project_key = "OWISMIND_TEST"


def _install_dataiku_stub():
    mod = sys.modules.get("dataiku")
    if mod is None:
        mod = types.ModuleType("dataiku")
        sys.modules["dataiku"] = mod
    client = types.SimpleNamespace(get_default_project=lambda: _FakeProject())
    mod.api_client = lambda: client
    return mod


def _load_backend():
    """Exec backend.py with a stub flask + app and return its module namespace."""
    _install_dataiku_stub()
    fake_request = _FakeRequest()
    flask_stub = types.ModuleType("flask")
    flask_stub.request = fake_request
    # jsonify passes the payload through so route returns are plain dicts
    # (or (dict, status) tuples from _err), directly assertable.
    flask_stub.jsonify = lambda payload: payload

    class _App(object):
        def route(self, *_a, **_k):
            def deco(fn):
                return fn
            return deco

    module = types.ModuleType("console_backend_under_test")
    module.__file__ = _BACKEND_PATH
    module.app = _App()
    saved_flask = sys.modules.get("flask")
    sys.modules["flask"] = flask_stub
    try:
        with open(_BACKEND_PATH) as fh:
            code = compile(fh.read(), _BACKEND_PATH, "exec")
        exec(code, module.__dict__)
    finally:
        if saved_flask is None:
            sys.modules.pop("flask", None)
        else:
            sys.modules["flask"] = saved_flask
    module._test_request = fake_request
    return module


_BACKEND = _load_backend()

_SPEC = {"domain": "satisfaction", "base_dataset": "CX_Surveys",
         "label_fr": "Satisfaction", "label_en": "Satisfaction"}


def _call(route_fn, body=None, args=None):
    """Invoke a route function with a scripted request; normalize to (payload, status)."""
    _BACKEND._test_request.json_body = body
    _BACKEND._test_request.args = args or {}
    out = route_fn()
    if isinstance(out, tuple):
        return out[0], out[1]
    return out, 200


def _wait_until(cond, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class _ConsoleTestCase(unittest.TestCase):
    """Pristine job registry per test + monkeypatch helper with restore."""

    def setUp(self):
        _BACKEND._JOBS.clear()
        del _BACKEND._JOBS_ORDER[:]
        _BACKEND._ACTIVE["total"] = 0
        _BACKEND._ACTIVE["mutating"] = 0
        self._patched = []
        self._gates = []

    def tearDown(self):
        # Unblock any still-running worker, wait for every slot to be freed,
        # THEN restore the patched functions (workers hold references to them).
        for gate in self._gates:
            gate.set()
        _wait_until(lambda: _BACKEND._ACTIVE["total"] == 0)
        for obj, name, orig in reversed(self._patched):
            setattr(obj, name, orig)

    def patch(self, obj, name, value):
        self._patched.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def gate(self):
        gate = threading.Event()
        self._gates.append(gate)
        return gate

    def patch_probe(self, work=None):
        self.patch(_BACKEND.probes, "run_read_probes",
                   work or (lambda project: {}))
        self.patch(_BACKEND.probes, "format_probe_report",
                   lambda results: "report")


# ----------------------------------------------------------------- concurrency bounds

class TestJobAdmissionBounds(_ConsoleTestCase):
    def test_fifth_concurrent_job_refused_429(self):
        gate = self.gate()
        self.patch_probe(lambda project: (gate.wait(10), {})[1])
        for _ in range(4):
            payload, status = _call(_BACKEND.api_probe, body={"confirm": True})
            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "ok")
        payload, status = _call(_BACKEND.api_probe, body={"confirm": True})
        self.assertEqual(status, 429)
        self.assertEqual(payload["error"], "too_many_jobs")
        self.assertEqual(_BACKEND._ACTIVE["total"], 4)

    def test_second_mutating_job_refused_429(self):
        gate = self.gate()
        self.patch(_BACKEND.hub, "read_json", lambda project, path: None)
        self.patch(_BACKEND.pipeline, "create_domain",
                   lambda ctx, spec, **kwargs: gate.wait(10))
        body = {"confirm": True, "spec": dict(_SPEC)}
        payload, status = _call(_BACKEND.api_execute, body=body)
        self.assertEqual(status, 200)
        payload, status = _call(_BACKEND.api_execute, body=body)
        self.assertEqual(status, 429)
        self.assertEqual(payload["error"], "too_many_jobs")
        # The mutating cap does not block non-mutating jobs (total is still < 4).
        self.patch_probe(lambda project: (gate.wait(10), {})[1])
        payload, status = _call(_BACKEND.api_probe, body={"confirm": True})
        self.assertEqual(status, 200)

    def test_slot_released_after_job_end(self):
        self.patch_probe()
        for _ in range(4):
            payload, status = _call(_BACKEND.api_probe, body={"confirm": True})
            self.assertEqual(status, 200)
        # The worker's finally frees each slot once the (fast) work is done.
        self.assertTrue(_wait_until(lambda: _BACKEND._ACTIVE["total"] == 0))
        payload, status = _call(_BACKEND.api_probe, body={"confirm": True})
        self.assertEqual(status, 200)

    def test_slot_released_when_job_crashes(self):
        def boom(project):
            raise RuntimeError("probe exploded")
        self.patch_probe(boom)
        payload, status = _call(_BACKEND.api_probe, body={"confirm": True})
        self.assertEqual(status, 200)
        job_id = payload["job_id"]
        self.assertTrue(_wait_until(lambda: _BACKEND._ACTIVE["total"] == 0))
        job, status = _call(lambda: _BACKEND.api_job(job_id))
        self.assertEqual(job["status"], "error")

    def test_refused_job_is_not_registered(self):
        gate = self.gate()
        self.patch_probe(lambda project: (gate.wait(10), {})[1])
        for _ in range(4):
            _call(_BACKEND.api_probe, body={"confirm": True})
        _call(_BACKEND.api_probe, body={"confirm": True})
        self.assertEqual(len(_BACKEND._JOBS), 4)


# ----------------------------------------------------------------- job id opacity

class TestJobIds(_ConsoleTestCase):
    def test_job_ids_opaque_distinct_and_pollable(self):
        self.patch_probe()
        payload1, _ = _call(_BACKEND.api_probe, body={"confirm": True})
        payload2, _ = _call(_BACKEND.api_probe, body={"confirm": True})
        id1, id2 = payload1["job_id"], payload2["job_id"]
        self.assertNotEqual(id1, id2)
        for jid in (id1, id2):
            # Not the old predictable job-N shape; uuid4 hex instead.
            self.assertIsNone(re.match(r"^job-\d+$", jid))
            self.assertTrue(re.match(r"^[0-9a-f]{32}$", jid))
        self.assertTrue(_wait_until(lambda: _BACKEND._ACTIVE["total"] == 0))
        job, status = _call(lambda: _BACKEND.api_job(id1))
        self.assertEqual(status, 200)
        self.assertEqual(job["status"], "done")


# ----------------------------------------------------------------- hub write size caps

class TestHubPromptSizeCap(_ConsoleTestCase):
    _PATH = "/owismind_hub/prompts/orchestrator_persona.md"

    def test_prompt_too_long_refused_nothing_written(self):
        writes = []
        self.patch(_BACKEND.hub, "write_prompt",
                   lambda project, path, content: writes.append(path))
        body = {"confirm": True, "path": self._PATH, "content": "x" * 20001}
        payload, status = _call(_BACKEND.api_hub_prompt_post, body=body)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "content_too_large")
        self.assertEqual(writes, [])

    def test_prompt_at_cap_accepted(self):
        writes = []
        self.patch(_BACKEND.hub, "write_prompt",
                   lambda project, path, content: writes.append(path))
        body = {"confirm": True, "path": self._PATH, "content": "x" * 20000}
        payload, status = _call(_BACKEND.api_hub_prompt_post, body=body)
        self.assertEqual(status, 200)
        self.assertEqual(writes, [self._PATH])


class TestHubCapabilitiesSizeCaps(_ConsoleTestCase):
    def _patch_writes(self):
        writes = []
        self.patch(_BACKEND.hub, "validate_capabilities", lambda caps: [])
        self.patch(_BACKEND.hub, "write_capabilities",
                   lambda project, caps: writes.append(caps))
        return writes

    def test_too_many_entries_refused_nothing_written(self):
        writes = self._patch_writes()
        caps = {"cap_%d" % i: {"domain": "d%d" % i} for i in range(51)}
        payload, status = _call(_BACKEND.api_hub_capabilities_post,
                                body={"confirm": True, "capabilities": caps})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "too_many_capabilities")
        self.assertEqual(writes, [])

    def test_entry_count_at_cap_accepted(self):
        writes = self._patch_writes()
        caps = {"cap_%d" % i: {"domain": "d%d" % i} for i in range(50)}
        payload, status = _call(_BACKEND.api_hub_capabilities_post,
                                body={"confirm": True, "capabilities": caps})
        self.assertEqual(status, 200)
        self.assertEqual(len(writes), 1)

    def test_oversized_payload_refused_nothing_written(self):
        writes = self._patch_writes()
        caps = {"cap": {"blob": "x" * (200 * 1024)}}
        payload, status = _call(_BACKEND.api_hub_capabilities_post,
                                body={"confirm": True, "capabilities": caps})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "capabilities_too_large")
        self.assertEqual(writes, [])


if __name__ == "__main__":
    unittest.main()
