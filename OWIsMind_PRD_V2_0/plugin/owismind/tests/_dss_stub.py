# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/_dss_stub.py
"""Shared import-time stubs for the DSS runtime (``dataiku``, ``dataiku.sql``, ``pandas``)
plus the minimal ``flask`` the route tests need.

Every test module used to carry its own ``_ensure_dataiku_stub``, each guarded by
``hasattr`` / "install only if absent" checks. Since ``unittest discover`` shares one
``sys.modules``, only the FIRST imported copy ever installed anything: the other ~19 were
dead code, and the three rival ``toSQL`` renderings meant a file's SQL assertions silently
depended on which sibling happened to sort first. One installer removes that
first-arrival-wins coupling: a file behaves the same alone and inside the full suite.

``toSQL`` uses the ESCAPING rendering, the only one faithful to a real driver: a string
becomes a single-quoted literal with embedded quotes doubled, anything else falls back to
``repr``. So ``toSQL(5)`` renders ``5`` and ``toSQL("a'b")`` renders ``'a''b'`` - a raw
single quote can never appear bare inside a statement.

The file is deliberately NOT named ``test_*``, so unittest never collects it.
"""
import sys
import types


def _to_sql(constant, dialect=None):
    """Render a constant the way a real escaper would (quoted + doubled quotes)."""
    if isinstance(constant, str):
        return "'" + constant.replace("'", "''") + "'"
    return repr(constant)


def install():
    """Install the dataiku / dataiku.sql / pandas stubs (NO install of any package).

    Idempotent, and additive by design: an attribute that already exists is never
    replaced, so a real ``dataiku`` on the path would stay untouched.
    """
    dk = sys.modules.get("dataiku")
    if dk is None:
        dk = types.ModuleType("dataiku")
        sys.modules["dataiku"] = dk
    if not hasattr(dk, "SQLExecutor2"):
        dk.SQLExecutor2 = type("SQLExecutor2", (), {})
    if not hasattr(dk, "Dataset"):
        dk.Dataset = type("Dataset", (), {})
    if not hasattr(dk, "default_project_key"):
        dk.default_project_key = lambda: "OWISMIND_DEV"
    if not hasattr(dk, "api_client"):
        dk.api_client = lambda: None
    sql_mod = sys.modules.get("dataiku.sql")
    if sql_mod is None:
        sql_mod = types.ModuleType("dataiku.sql")
        sys.modules["dataiku.sql"] = sql_mod
    if not hasattr(sql_mod, "Constant"):
        sql_mod.Constant = lambda value: value
    if not hasattr(sql_mod, "toSQL"):
        sql_mod.toSQL = _to_sql
    if not hasattr(sql_mod, "Dialects"):
        sql_mod.Dialects = type("Dialects", (), {"POSTGRES": "postgres"})
    dk.sql = sql_mod
    if "pandas" not in sys.modules:
        sys.modules["pandas"] = types.ModuleType("pandas")


class _FakeRequest(object):
    """Minimal stand-in for ``flask.request``, driven per test by mutating ``REQUEST``."""

    def __init__(self):
        self.headers = {}
        self.args = {}
        self.method = "GET"
        self._json = None

    def get_json(self, silent=False):
        return self._json


REQUEST = _FakeRequest()


def install_flask():
    """Install the minimal ``flask`` stub (Blueprint / jsonify / request / g) so
    ``owismind.api.routes`` imports and its view functions stay directly callable.

    ``jsonify`` returns the payload unchanged, so a handler's return value is either the
    plain dict (200) or a ``(dict, status)`` tuple (error) - exactly what the handlers
    build. Idempotent: an already installed stub is kept, which preserves the
    ``routes.request`` binding taken when ``routes`` was first imported.
    """
    flask = sys.modules.get("flask")
    if flask is not None and hasattr(flask, "_OWI_STUB"):
        return
    flask = types.ModuleType("flask")
    flask._OWI_STUB = True

    class Blueprint(object):
        def __init__(self, name, import_name, url_prefix=None):
            self.name = name
            self.url_prefix = url_prefix

        def route(self, *_a, **_k):
            def _decorator(fn):
                return fn
            return _decorator

        def before_request(self, fn):
            return fn

        def after_request(self, fn):
            return fn

    flask.Blueprint = Blueprint
    flask.jsonify = lambda payload: payload
    flask.request = REQUEST
    flask.g = types.SimpleNamespace()
    sys.modules["flask"] = flask
