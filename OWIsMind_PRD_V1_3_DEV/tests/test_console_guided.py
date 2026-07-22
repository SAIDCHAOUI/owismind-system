"""Console backend tests for the guided-assistant routes (DSS-free, flask-free).

Locks the /api/guided/* contract the frontend codes against:
- confirm required on every mutating route;
- one active run at a time (409 active_run_exists);
- run/verify guards (unknown_run, run_not_active, stage_not_runnable,
  stage_not_verifiable, busy while a guided job runs);
- the background stage job: RUNNING marker persisted first, final state saved,
  job result carrying the updated run;
- self-healing of a stage left RUNNING by a backend restart (GET current).

Same harness as test_security_console.py: backend.py is exec'd with stub flask
and dataiku modules in a FRESH namespace (isolated _JOBS registry), and the
real owismind_factory modules are monkeypatched per test.
"""

import json
import os
import sys
import time
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_PARENT = os.path.abspath(os.path.join(_HERE, "..", "project-library", "python"))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

_BACKEND_PATH = os.path.abspath(os.path.join(
    _HERE, "..", "Standard-webapps", "agent-factory-console", "backend.py"))


class _FakeRequest(object):
    def __init__(self):
        self.json_body = None
        self.args = {}

    def get_json(self, silent=False):
        return self.json_body


class _FakeLibFile(object):
    def __init__(self, tree, path):
        self._tree, self._path = tree, path

    def read(self):
        return self._tree[self._path]

    def write(self, content):
        self._tree[self._path] = content


class _FakeFolder(object):
    def __init__(self, library, path):
        self._library, self._path = library, path

    def add_folder(self, name):
        base = self._path.rstrip("/")
        return _FakeFolder(self._library, base + "/" + name)

    def add_file(self, name):
        full = self._path.rstrip("/") + "/" + name
        self._library.files[full] = ""
        return _FakeLibFile(self._library.files, full)


class _FakeLibrary(object):
    def __init__(self):
        self.files = {}
        self.root = _FakeFolder(self, "")

    def get_file(self, path):
        return _FakeLibFile(self.files, path) if path in self.files else None

    def get_folder(self, path):
        if path in ("", "/"):
            return self.root
        prefix = path.rstrip("/") + "/"
        if any(item.startswith(prefix) for item in self.files):
            return _FakeFolder(self, path)
        return None


class _FakeProject(object):
    project_key = "OWISMIND_TEST"

    def __init__(self):
        self.library = _FakeLibrary()

    def get_library(self):
        return self.library


def _install_dataiku_stub():
    mod = sys.modules.get("dataiku")
    if mod is None:
        mod = types.ModuleType("dataiku")
        sys.modules["dataiku"] = mod
    client = types.SimpleNamespace(get_default_project=lambda: _FakeProject())
    mod.api_client = lambda: client
    return mod


def _load_backend():
    _install_dataiku_stub()
    fake_request = _FakeRequest()
    flask_stub = types.ModuleType("flask")
    flask_stub.request = fake_request
    flask_stub.jsonify = lambda payload: payload

    class _App(object):
        def route(self, *_a, **_k):
            def deco(fn):
                return fn
            return deco

    module = types.ModuleType("console_backend_guided_under_test")
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

from owismind_factory import guided, guided_store, hub  # noqa: E402
from owismind_factory.spec import DomainSpec  # noqa: E402

_SPEC_BODY = {"domain": "opportunities", "base_dataset": "DRIVE_Opportunities",
              "label_fr": "Expert opportunités", "label_en": "Opportunities expert"}


def _entry():
    """Return a minimal valid opportunities capability entry."""
    from owismind_factory.registry import KNOWN_BLOCK_IDS, KNOWN_TOOL_NAMES
    return {
        "kind": "agent", "agent_id": "agent:4Ghpi5hm", "domain": "opportunities",
        "label_fr": "Expert opportunités", "label_en": "Opportunities expert",
        "tool_name": "ask_opportunities_expert", "planner_description": "routing text",
        "block_labels": {key: {"fr": "x", "en": "x"} for key in KNOWN_BLOCK_IDS},
        "tool_labels": {key: {"fr": "x", "en": "x"} for key in KNOWN_TOOL_NAMES},
        "dataset_label_fr": "Base", "dataset_label_en": "Base", "source_url": "",
        "lookup_dataset": "DRIVE_Opportunities",
        "lookup_catalog": "DRIVE_Opportunities_value_catalog",
        "lookup_search_columns": [], "pass_context": True, "enabled": True,
    }


def _call(route_fn, body=None, args=None):
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


def _make_run(current="plan", status_map=None, run_status="active"):
    spec = DomainSpec.from_dict(_SPEC_BODY)
    state = guided.new_state(spec)
    state["stages"]["preflight"]["status"] = guided.DONE
    state["stages"][current]["status"] = (status_map or {}).get(current, guided.READY)
    return {"run_id": "run1", "domain": spec.domain, "status": run_status,
            "current_stage": current, "state": state}


class _StoreState(object):
    def __init__(self):
        self.active = None
        self.runs = {}
        self.saves = []
        self.raise_on_init = False


_STORE = _StoreState()


class _FakeStore(object):
    def __init__(self, connection, project_key, executor_factory=None):
        if _STORE.raise_on_init:
            raise guided_store.GuidedStoreError("no connection")
        self.connection = connection
        self.project_key = project_key

    def load_active(self):
        return json.loads(json.dumps(_STORE.active)) if _STORE.active else None

    def load(self, run_id):
        run = _STORE.runs.get(run_id)
        return json.loads(json.dumps(run)) if run else None

    def save(self, run):
        _STORE.saves.append(json.loads(json.dumps(run)))


class _Patcher(object):
    def __init__(self):
        self._saved = []

    def set(self, obj, name, value):
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def restore(self):
        while self._saved:
            obj, name, value = self._saved.pop()
            setattr(obj, name, value)


class _GuidedRoutesBase(unittest.TestCase):
    def setUp(self):
        global _STORE
        _STORE = _StoreState()
        self.p = _Patcher()
        self.p.set(guided_store, "GuidedStore", _FakeStore)
        self.p.set(hub, "get_settings",
                   lambda project: {"sql_connection": "SQL_test", "code_env_311": ""})
        self.project = _FakeProject()
        self.project.library.files[hub.CAPABILITIES_PATH] = json.dumps(
            {"opportunities_expert": _entry()})
        self.p.set(_BACKEND, "_project", lambda: self.project)
        # Drain the job registry between tests (fresh namespace, shared module state).
        with _BACKEND._JOBS_LOCK:
            _BACKEND._JOBS.clear()
            del _BACKEND._JOBS_ORDER[:]
            _BACKEND._ACTIVE["total"] = 0
            _BACKEND._ACTIVE["mutating"] = 0

    def tearDown(self):
        self.p.restore()


class TestConfirmGates(_GuidedRoutesBase):
    def test_every_mutating_guided_route_requires_confirm(self):
        for fn in (_BACKEND.api_guided_start, _BACKEND.api_guided_run,
                   _BACKEND.api_guided_verify, _BACKEND.api_guided_abandon):
            payload, status = _call(fn, body={"run_id": "run1", "spec": _SPEC_BODY})
            self.assertEqual(status, 400, fn.__name__)
            self.assertEqual(payload["error"], "confirmation_required", fn.__name__)


class TestCurrent(_GuidedRoutesBase):
    def test_no_active_run(self):
        payload, status = _call(_BACKEND.api_guided_current)
        self.assertEqual(status, 200)
        self.assertIsNone(payload["run"])

    def test_storage_not_configured(self):
        _STORE.raise_on_init = True
        payload, status = _call(_BACKEND.api_guided_current)
        self.assertEqual(status, 500)
        self.assertEqual(payload["error"], "storage_not_configured")

    def test_heals_a_stage_left_running(self):
        run = _make_run(current="infra", status_map={"infra": guided.RUNNING})
        _STORE.active = run
        payload, status = _call(_BACKEND.api_guided_current)
        self.assertEqual(status, 200)
        healed = payload["run"]["state"]["stages"]["infra"]
        self.assertEqual(healed["status"], guided.STAGE_FAILED)
        self.assertTrue(_STORE.saves, "the healed run must be persisted")


class TestStart(_GuidedRoutesBase):
    def test_refuses_when_a_run_is_active(self):
        _STORE.active = _make_run()
        payload, status = _call(_BACKEND.api_guided_start,
                                body={"confirm": True, "spec": _SPEC_BODY})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "active_run_exists")
        self.assertEqual(payload["run_id"], "run1")

    def test_invalid_spec_rejected(self):
        payload, status = _call(_BACKEND.api_guided_start,
                                body={"confirm": True, "spec": {"domain": "X Y"}})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "invalid_spec")

    def test_start_runs_preflight_and_persists(self):
        captured = {}

        def fake_start(project, spec, settings=None, **kwargs):
            captured["spec"] = spec.to_dict()
            return _make_run()
        self.p.set(guided, "start_run", fake_start)
        payload, status = _call(_BACKEND.api_guided_start,
                                body={"confirm": True, "spec": _SPEC_BODY})
        self.assertEqual(status, 200)
        self.assertEqual(payload["run"]["run_id"], "run1")
        self.assertEqual(captured["spec"]["domain"], "opportunities")
        self.assertEqual(len(_STORE.saves), 1)


class TestRunStage(_GuidedRoutesBase):
    def test_unknown_run(self):
        payload, status = _call(_BACKEND.api_guided_run,
                                body={"confirm": True, "run_id": "nope"})
        self.assertEqual(status, 404)
        self.assertEqual(payload["error"], "unknown_run")

    def test_run_not_active(self):
        _STORE.runs["run1"] = _make_run(run_status="abandoned")
        payload, status = _call(_BACKEND.api_guided_run,
                                body={"confirm": True, "run_id": "run1"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "run_not_active")

    def test_stage_not_runnable(self):
        # profile_review is a MANUAL stage: waiting_user, never server-runnable.
        _STORE.runs["run1"] = _make_run(current="profile_review",
                                        status_map={"profile_review": guided.WAITING})
        payload, status = _call(_BACKEND.api_guided_run,
                                body={"confirm": True, "run_id": "run1"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "stage_not_runnable")

    def test_background_stage_job_persists_marker_then_result(self):
        _STORE.runs["run1"] = _make_run(current="plan")

        def fake_run_stage(project, run, settings=None, ctx=None, **kwargs):
            run["state"]["stages"]["plan"]["status"] = guided.DONE
            run["current_stage"] = "infra"
            run["state"]["stages"]["infra"]["status"] = guided.READY
            return run
        self.p.set(guided, "run_current_stage", fake_run_stage)
        payload, status = _call(_BACKEND.api_guided_run,
                                body={"confirm": True, "run_id": "run1"})
        self.assertEqual(status, 200)
        job_id = payload["job_id"]
        self.assertTrue(_wait_until(
            lambda: _BACKEND._JOBS[job_id]["status"] == "done"))
        out = _BACKEND.api_job(job_id)
        result = out[0] if isinstance(out, tuple) else out
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["result"]["run"]["current_stage"], "infra")
        # First save = RUNNING marker, second save = final state.
        self.assertGreaterEqual(len(_STORE.saves), 2)
        self.assertEqual(_STORE.saves[0]["state"]["stages"]["plan"]["status"], "running")
        self.assertEqual(_STORE.saves[-1]["current_stage"], "infra")

    def test_stage_job_failure_marks_the_run_failed(self):
        _STORE.runs["run1"] = _make_run(current="plan")

        def exploding(project, run, settings=None, ctx=None, **kwargs):
            raise RuntimeError("boom")
        self.p.set(guided, "run_current_stage", exploding)
        payload, status = _call(_BACKEND.api_guided_run,
                                body={"confirm": True, "run_id": "run1"})
        self.assertEqual(status, 200)
        job_id = payload["job_id"]
        self.assertTrue(_wait_until(
            lambda: _BACKEND._JOBS[job_id]["status"] == "error"))
        self.assertEqual(_STORE.saves[-1]["state"]["stages"]["plan"]["status"], "failed")


class TestVerify(_GuidedRoutesBase):
    def test_busy_while_a_guided_job_runs(self):
        with _BACKEND._JOBS_LOCK:
            _BACKEND._JOBS["j1"] = {"id": "j1", "kind": "guided", "status": "running",
                                    "ctx": None, "result": None, "error": None}
        payload, status = _call(_BACKEND.api_guided_verify,
                                body={"confirm": True, "run_id": "run1"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["error"], "busy")

    def test_stage_not_verifiable(self):
        _STORE.runs["run1"] = _make_run(current="plan")
        payload, status = _call(_BACKEND.api_guided_verify,
                                body={"confirm": True, "run_id": "run1"})
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "stage_not_verifiable")

    def test_verify_delegates_and_persists(self):
        _STORE.runs["run1"] = _make_run(current="profile_review",
                                        status_map={"profile_review": guided.WAITING})

        def fake_verify(project, run, settings=None, **kwargs):
            run["state"]["stages"]["profile_review"]["status"] = guided.DONE
            run["current_stage"] = "wizard"
            return run
        self.p.set(guided, "verify_current_stage", fake_verify)
        payload, status = _call(_BACKEND.api_guided_verify,
                                body={"confirm": True, "run_id": "run1"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["run"]["current_stage"], "wizard")
        self.assertEqual(len(_STORE.saves), 1)


class TestAbandon(_GuidedRoutesBase):
    def test_abandon_marks_and_persists_once(self):
        _STORE.runs["run1"] = _make_run()
        payload, status = _call(_BACKEND.api_guided_abandon,
                                body={"confirm": True, "run_id": "run1"})
        self.assertEqual(status, 200)
        self.assertEqual(_STORE.saves[-1]["status"], "abandoned")

    def test_abandon_is_idempotent_on_terminal_runs(self):
        _STORE.runs["run1"] = _make_run(run_status="abandoned")
        payload, status = _call(_BACKEND.api_guided_abandon,
                                body={"confirm": True, "run_id": "run1"})
        self.assertEqual(status, 200)
        self.assertEqual(_STORE.saves, [])


class TestCapabilityEnable(_GuidedRoutesBase):
    def test_requires_confirm(self):
        body, status = _call(
            _BACKEND.api_capability_enable,
            body={"capability_key": "opportunities_expert", "enabled": False})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "confirmation_required")

    def test_unknown_capability_404(self):
        body, status = _call(
            _BACKEND.api_capability_enable,
            body={"confirm": True, "capability_key": "nope", "enabled": False})
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "unknown_capability")

    def test_flips_and_returns_capabilities(self):
        body, status = _call(
            _BACKEND.api_capability_enable,
            body={"confirm": True, "capability_key": "opportunities_expert",
                  "enabled": False})
        self.assertEqual(status, 200)
        self.assertFalse(body["capabilities"]["opportunities_expert"]["enabled"])


class TestStartRemoval(_GuidedRoutesBase):
    def test_typed_name_mismatch_rejected(self):
        body, status = _call(
            _BACKEND.api_guided_start_removal,
            body={"confirm": True, "capability_key": "opportunities_expert",
                  "domain_typed": "WRONG"})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "domain_mismatch")

    def test_active_run_blocks(self):
        _STORE.active = {"run_id": "r1", "status": "active"}
        body, status = _call(
            _BACKEND.api_guided_start_removal,
            body={"confirm": True, "capability_key": "opportunities_expert",
                  "domain_typed": "opportunities"})
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "active_run_exists")

    def test_creates_and_persists_a_removal_run(self):
        body, status = _call(
            _BACKEND.api_guided_start_removal,
            body={"confirm": True, "capability_key": "opportunities_expert",
                  "domain_typed": "opportunities"})
        self.assertEqual(status, 200)
        run = body["run"]
        self.assertTrue(run["state"].get("removal"))
        self.assertEqual(run["state"]["stage_order"][0], "inventory")
        self.assertTrue(_STORE.saves, "the run must be persisted")


if __name__ == "__main__":
    unittest.main()
