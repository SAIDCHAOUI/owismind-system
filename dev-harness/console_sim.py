"""Local simulator for the Agent Factory Console (Standard DSS webapp), DSS-free.

Serves the REAL console files (body.html / script.js / style.css) and runs the
REAL backend.py routes against a fake in-memory DSS project (stdlib only, no
install). Same golden rule as the Vue harness: the console code is never
modified; only the fake world below adapts to its contracts.

Fake world: a project library seeded from the repo hub seeds
(project-library/python/owismind_hub), a dataset list, an in-memory guided
store, and the DSS-mutating factory builders patched to succeed after a short
delay (same patch points as tests/test_factory_guided.py).

Run from the repo root:
    python3 dev-harness/console_sim.py      # -> http://127.0.0.1:5198
"""

import json
import os
import sys
import time
import types
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJ = os.path.join(ROOT, "OWIsMind_PRD_V1_3_DEV")
LIB = os.path.join(PROJ, "project-library", "python")
CONSOLE = os.path.join(PROJ, "Standard-webapps", "agent-factory-console")
PORT = 5198
STEP_DELAY = 0.6  # seconds per simulated mutating step (visible live journal)

sys.path.insert(0, LIB)

# ----------------------------------------------------------------- fake DSS project

DATASETS = [
    ("DRIVE_Revenues", "PostgreSQL"), ("DRIVE_Revenues_profile", "PostgreSQL"),
    ("DRIVE_Revenues_value_index", "PostgreSQL"), ("DRIVE_Revenues_Value_Catalog", "PostgreSQL"),
    ("TroubleTickets_year", "PostgreSQL"), ("TroubleTickets_year_profile", "PostgreSQL"),
    ("TroubleTickets_year_value_index", "PostgreSQL"),
    ("TroubleTickets_year_value_catalogue", "PostgreSQL"),
    ("DRIVE_Opportunities", "PostgreSQL"), ("Delivery_Snapshot", "PostgreSQL"),
]


class _LibFile(object):
    def __init__(self, tree, path):
        self._tree, self._path = tree, path

    def read(self):
        return self._tree[self._path]

    def write(self, content):
        self._tree[self._path] = content

    def delete(self):
        self._tree.pop(self._path, None)


class _Folder(object):
    def __init__(self, library, path):
        self._library, self._path = library, path

    def add_folder(self, name):
        return _Folder(self._library, self._path.rstrip("/") + "/" + name)

    def add_file(self, name):
        full = self._path.rstrip("/") + "/" + name
        self._library.files[full] = ""
        return _LibFile(self._library.files, full)

    def list(self):
        prefix = self._path.rstrip("/") + "/"
        return [p for p in self._library.files if p.startswith(prefix)]


class _Library(object):
    def __init__(self):
        self.files = {}
        self.root = _Folder(self, "")

    def get_file(self, path):
        return _LibFile(self.files, path) if path in self.files else None

    def get_folder(self, path):
        if path in ("", "/"):
            return self.root
        prefix = path.rstrip("/") + "/"
        if any(p.startswith(prefix) for p in self.files):
            return _Folder(self, path)
        return None


class _Dataset(object):
    def get_settings(self):
        return types.SimpleNamespace(get_raw=lambda: {"partitioning": {"dimensions": []}})


class _Project(object):
    project_key = "OWISMIND_DEV"

    def __init__(self):
        self.library = _Library()
        hub_dir = os.path.join(LIB, "owismind_hub")
        for dirpath, _dirs, files in os.walk(hub_dir):
            if "__pycache__" in dirpath:
                continue
            for name in files:
                if not name.endswith((".json", ".md")) or name == "README.md":
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, LIB).replace(os.sep, "/")
                with open(full, encoding="utf-8") as fh:
                    self.library.files["/python/" + rel] = fh.read()

    def get_library(self):
        return self.library

    def get_flow(self):
        return None

    def list_datasets(self):
        return [{"name": n, "type": t} for n, t in DATASETS] + \
            [{"name": n, "type": "PostgreSQL"} for n in sorted(WORLD["datasets"])]

    def get_dataset(self, name):
        return _Dataset()


PROJECT = _Project()


def _install_dataiku_stub():
    mod = types.ModuleType("dataiku")
    mod.api_client = lambda: types.SimpleNamespace(get_default_project=lambda: PROJECT)
    mod.default_project_key = lambda: PROJECT.project_key
    sql_mod = types.ModuleType("dataiku.sql")

    class Constant(object):
        def __init__(self, value):
            self.value = value

    sql_mod.Constant = Constant
    sql_mod.Dialects = types.SimpleNamespace(POSTGRES="postgres")
    sql_mod.toSQL = lambda node, dialect=None: "'%s'" % str(node.value).replace("'", "''")
    mod.sql = sql_mod
    sys.modules["dataiku"] = mod
    sys.modules["dataiku.sql"] = sql_mod


_install_dataiku_stub()

from owismind_factory import (agent_builder, flow_builder, guided, guided_store,  # noqa: E402
                              hub, pipeline, probes, removal, review, semantic_builder,
                              tool_builder, wizard)

# Dynamic fake world: what a creation run builds, a removal run deletes (so both
# guided flows can be walked end to end on the simulator).
WORLD = {"datasets": set(), "recipes": set(), "scenarios": set(), "zones": set(),
         "agents": {}, "deleted": set()}

# ----------------------------------------------------------------- load the REAL backend.py

class _Request(object):
    def __init__(self):
        self.body = None
        self.args = {}

    def get_json(self, silent=False):
        return self.body


REQUEST = _Request()
ROUTES = {}


class _App(object):
    def route(self, rule, methods=("GET",)):
        def deco(fn):
            for m in methods:
                ROUTES[(m, rule)] = fn
            return fn
        return deco


def _load_backend():
    flask_stub = types.ModuleType("flask")
    flask_stub.request = REQUEST
    flask_stub.jsonify = lambda payload: payload
    sys.modules["flask"] = flask_stub
    module = types.ModuleType("console_backend")
    module.app = _App()
    path = os.path.join(CONSOLE, "backend.py")
    with open(path, encoding="utf-8") as fh:
        exec(compile(fh.read(), path, "exec"), module.__dict__)
    return module


BACKEND = _load_backend()

# ----------------------------------------------------------------- patched factory world

_RUNS = {}


class _MemStore(object):
    def __init__(self, connection, project_key, executor_factory=None):
        pass

    def load_active(self):
        for run in _RUNS.values():
            if run.get("status") == guided.RUN_ACTIVE:
                return json.loads(json.dumps(run))
        return None

    def load(self, run_id):
        run = _RUNS.get(run_id)
        return json.loads(json.dumps(run)) if run else None

    def save(self, run):
        _RUNS[run["run_id"]] = json.loads(json.dumps(run))

    def table_has_rows(self, table):
        return True


def _fake_pipeline(ctx, spec, wizard_config=None, discovery=None, schema_hints=None,
                   steps=None, settings=None):
    for step in pipeline.STEP_NAMES:
        if steps is not None and step not in steps:
            continue
        if ctx.dry_run:
            ctx.plan(step, "%s (%s)" % (step.replace("_", " "), spec.domain))
        elif step == "first_build":
            ctx.manual(step, "lancer le scenario de premier build dans DSS")
        else:
            time.sleep(STEP_DELAY)
            ctx.done(step, "%s ok (%s)" % (step.replace("_", " "), spec.domain))
    if not ctx.dry_run:
        for name in (spec.profile_dataset, spec.value_index_dataset, spec.value_catalog_dataset):
            WORLD["datasets"].add(name)
            WORLD["recipes"].add(spec.recipe_name(name))
        WORLD["scenarios"].add(spec.scenario_name)
        WORLD["zones"].add(spec.zone_name)
        for key in ("tool:%s" % spec.semantic_tool_name, "model:%s" % spec.semantic_model_name):
            WORLD["deleted"].discard(key)
    return ctx


def _fake_scenario(ctx, spec, **kwargs):
    time.sleep(STEP_DELAY)
    ctx.done("scenario_run", "scenario finished: SUCCESS")
    return {"outcome": "SUCCESS", "error": None}


def _fake_create_agent(ctx, spec, code, schema_hints, code_env=""):
    time.sleep(STEP_DELAY)
    ctx.done("code_agent", "Code Agent cree")
    agent_id = "Sim%04d" % (int(time.time()) % 10000)
    WORLD["agents"][agent_id] = spec.agent_name
    return "agent:" + agent_id


def _fake_probes(project):
    time.sleep(2)
    return {"simulated": True}


def _fake_probe_report(results):
    return ("# Rapport de sonde (SIMULATION locale)\n\n"
            "- API projet : OK\n- Bibliotheque projet : OK (hub present)\n"
            "- Connexion SQL `SQL_owi` : OK\n- Code env 3.11 : OK\n"
            "- Creation de Code Agent par API : NON DOCUMENTEE -> etape MANUELLE\n"
            "- Semantic Model Query tool : type detecte\n")


def _fake_wizard(project, profile_dataset, answers=None, base_dataset=None):
    time.sleep(2.5)
    config = {
        "planner_description": "Expert des donnees %s (simulation)." % (base_dataset or profile_dataset),
        "attributes": [{"column": "Account_name"}, {"column": "Product"}, {"column": "Month"}],
        "metrics": [{"name": "Total amount (EUR)", "sql": "SUM(amount_eur)"}],
        "golden_queries": [{"question": "Top 10 clients sur 2026", "sql": "SELECT ..."}],
        "questions": [] if answers else [
            {"id": "time_column", "question_fr": "Quelle colonne porte la date de reference ?",
             "why": "Pour les filtres de periode par defaut.", "options": ["Month", "close_date"],
             "default": "Month"},
            {"id": "main_metric", "question_fr": "Quelle mesure afficher par defaut ?",
             "why": "Le profil propose plusieurs colonnes numeriques.",
             "options": ["amount_eur", "quantity"], "default": "amount_eur"},
        ],
    }
    return config


def _world_has(stage_key, item):
    name = item["name"]
    if stage_key == "delete_datasets":
        return name in WORLD["datasets"]
    if stage_key == "delete_recipes":
        return name in WORLD["recipes"]
    if stage_key == "delete_scenario":
        return name in WORLD["scenarios"]
    if stage_key == "delete_zone":
        return name in WORLD["zones"]
    if stage_key == "delete_agent":
        return item.get("id") in WORLD["agents"]
    if stage_key == "delete_tool":
        return "tool:" + name not in WORLD["deleted"]
    return "model:" + name not in WORLD["deleted"]


def _fake_execute_delete(project, stage_key, items, ctx):
    for item in items:
        time.sleep(STEP_DELAY / 2)
        if not _world_has(stage_key, item):
            ctx.skip(stage_key, "%s %s already absent" % (item["kind_fr"], item["name"]))
            continue
        WORLD["datasets"].discard(item["name"])
        WORLD["recipes"].discard(item["name"])
        WORLD["scenarios"].discard(item["name"])
        WORLD["zones"].discard(item["name"])
        WORLD["agents"].pop(item.get("id"), None)
        if stage_key == "delete_tool":
            WORLD["deleted"].add("tool:" + item["name"])
        if stage_key == "delete_model":
            WORLD["deleted"].add("model:" + item["name"])
        ctx.done(stage_key, "deleted %s %s (verified absent)" % (item["kind_fr"], item["name"]))
    return [], []


def _fake_verify_absent(project, stage_key, items):
    return [i for i in items if _world_has(stage_key, i)], []


def _fake_resolve_model(project, spec, tool_id):
    if spec is None or "model:" + spec.semantic_model_name in WORLD["deleted"]:
        return None, None
    return "SimMdl1", spec.semantic_model_name


def _fake_agent_exists(project, name):
    """Known agents by name; once the generated code sits in the hub, the fake
    operator is deemed to have pasted it (manual Code Agent stage)."""
    for agent_id, agent_name in WORLD["agents"].items():
        if agent_name == name:
            return agent_id
    if (hub.HUB_ROOT + "/generated/%s.py" % name) in PROJECT.library.files:
        agent_id = "SimMan%04d" % (int(time.time()) % 10000)
        WORLD["agents"][agent_id] = name
        return agent_id
    return None


# Live semantic model of every domain, as a factory-made raw (review runs read
# it back; a review apply rewrites it through the fake pipeline below).
MODELS = {}


def _fake_model_raw(project, model_id, version_id=None):
    return MODELS.setdefault(model_id, {
        "privateEditorData": {"owismindFactory": {"domain": "sim"}},
        "entities": [{
            "name": "record", "description": "One line per opportunity and month.",
            "attributes": [
                {"column": "Account_name", "description": "Customer name.", "indexDistinctValues": True},
                {"column": "Stage", "description": "Stage of the deal.", "indexDistinctValues": True},
                {"column": "Amount_eur", "description": "Amount.", "indexDistinctValues": False},
                {"column": "Month", "description": "Month of the snapshot.", "indexDistinctValues": False},
            ],
            "metrics": [{"name": "Total amount", "description": "Sum of amounts.",
                         "pseudoSQLExpression": "SUM(Amount_eur)"}],
            "filters": [],
            "primaryKey": {"attributes": []},
        }],
        "glossaryTerms": [{"term": "Customer", "synonyms": ["client"]}],
        "sqlGenerationConfig": {"instructions": "One physical table, never JOIN."},
        "goldenQueries": [{"name": "top", "question": "Top 10 customers by amount",
                           "generatedSql": 'SELECT "Account_name", SUM("Amount_eur") FROM t GROUP BY 1'}],
    })


def _fake_review_propose(project, spec, base_config, routing, feedback, answers=None, llm_id=None):
    time.sleep(2.5)
    proposed = json.loads(json.dumps(base_config))
    for att in proposed["attributes"]:
        if att["column"] == "Stage":
            att["description"] = "Sales stage. 'Closed' means Stage = Won."
        if att["column"] == "Month":
            att["resolvable"] = False
    proposed["metrics"][0]["pseudo_sql"] = "SUM(Amount_eur) / COUNT(DISTINCT Month)"
    proposed["metrics"].append({"name": "Number of deals", "description": "Distinct deals.",
                                "pseudo_sql": "COUNT(DISTINCT Opportunity_id)"})
    proposed["glossary"].append({"term": "Closed deal", "synonyms": ["won", "signed"]})
    proposed["planner_description"] = (routing or "") + " Also owns pipeline questions."
    questions = [] if answers else [
        {"id": "month_scope", "question": "Should a total cover only the latest month by default?",
         "default": "Yes, the latest month"}]
    return {"proposed": proposed, "questions": questions, "used_samples": True, "used_comments": 2,
            "notes": {"column:Stage": "The expert will treat 'closed' as a won deal.",
                      "metric:Number of deals": "The expert can now count deals without duplicates."}}


def _patch():
    guided_store.GuidedStore = _MemStore
    guided._Env.store = lambda env: _MemStore(None, None)
    pipeline.create_domain = _fake_pipeline
    flow_builder.dataset_exists = lambda project, name: (
        any(n == name for n, _ in DATASETS) or name in WORLD["datasets"])
    flow_builder.recipe_exists = lambda project, name: name in WORLD["recipes"]
    flow_builder.scenario_id_by_name = lambda project, name: (
        "SimScn_" + name if name in WORLD["scenarios"] else None)
    flow_builder._zone_by_name = lambda flow, name: (
        types.SimpleNamespace(id="SimZone", items=[]) if name in WORLD["zones"] else None)
    removal.agent_name_by_id = lambda project, agent_id: WORLD["agents"].get(agent_id)
    removal.resolve_model = _fake_resolve_model
    removal.execute_delete_stage = _fake_execute_delete
    removal.verify_stage_absent = _fake_verify_absent
    removal.scenario_is_running = lambda project, scenario_id: False
    flow_builder.run_scenario_and_wait = _fake_scenario
    semantic_builder.find_model_by_name = lambda project, name: types.SimpleNamespace(id="SimMdl1")
    tool_builder.tool_exists = lambda project, name: (
        None if "tool:" + name in WORLD["deleted"] else "SimTool")
    agent_builder.agent_exists = _fake_agent_exists
    agent_builder.load_engine_template = lambda project: (
        'PROFILE_DATASET = "X"\nVALUE_INDEX_DATASET = "Y"\n'
        'SEMANTIC_TOOL_ID = "Z"\nSEMANTIC_TOOL_NAME = "W"\n')
    agent_builder.generate_subagent_code = (
        lambda template, spec, tool_id, deploy_project=None: "# generated for %s" % spec.domain)
    agent_builder.create_code_agent = _fake_create_agent
    wizard.physical_table_name = lambda project, dataset: "%s_%s" % (PROJECT.project_key, dataset)
    wizard.draft_model_config = _fake_wizard
    semantic_builder.read_model_raw = _fake_model_raw
    review.propose = _fake_review_propose
    semantic_builder.apply_config = lambda ctx, model_id, config, created_this_run=False, version_id=None: (
        ctx.done("semantic_config", "applied %s to %s" % (sorted(config), model_id)) and model_id)
    semantic_builder.start_indexing = lambda ctx, model_id, wait=True: ctx.done("semantic_index", "indexed")
    probes.run_read_probes = _fake_probes
    probes.format_probe_report = _fake_probe_report
    # The engine template a real operator pastes once into the hub.
    PROJECT.library.files[hub.TEMPLATE_AGENT_PATH] = (
        'PROFILE_DATASET = "X"\nVALUE_INDEX_DATASET = "Y"\n'
        'SEMANTIC_TOOL_ID = "Z"\nSEMANTIC_TOOL_NAME = "W"\n')
    # Probe gates already "confirmed" so stages are not blocked on discovery.
    PROJECT.library.files[hub.HUB_ROOT + "/probe_results.json"] = json.dumps(
        {"suggested_discovery": {"type": "SemanticModelQuery"}, "suggested_schema_hints": None})


_patch()

# ----------------------------------------------------------------- HTTP server

def _page():
    def read(name):
        with open(os.path.join(CONSOLE, name), encoding="utf-8") as fh:
            return fh.read()
    return ("<!doctype html><html lang=\"fr\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>Agent Factory Console (simulation)</title>"
            "<style>" + read("style.css") + "</style>"
            "<script>window.getWebAppBackendUrl=function(p){return '/'+String(p).replace(/^\\//,'');};"
            "</script></head><body>" + read("body.html") +
            "<script>" + read("script.js") + "</script></body></html>")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("[console-sim] " + (fmt % args) + "\n")

    def _send(self, status, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _dispatch(self, method):
        url = urlparse(self.path)
        if method == "GET" and url.path in ("/", "/index.html"):
            return self._send(200, _page().encode("utf-8"), "text/html")
        route, kwargs = ROUTES.get((method, url.path)), {}
        if route is None and method == "GET" and url.path.startswith("/api/job/"):
            route, kwargs = ROUTES[("GET", "/api/job/<job_id>")], {"job_id": url.path[9:]}
        if route is None:
            return self._send(404, {"status": "error", "error": "not_found"})
        body = None
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except ValueError:
                body = None
        REQUEST.body = body
        REQUEST.args = {k: v[0] for k, v in parse_qs(url.query).items()}
        out = route(**kwargs)
        status = 200
        if isinstance(out, tuple):
            out, status = out
        self._send(status, out)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")


if __name__ == "__main__":
    print("Agent Factory Console simulator -> http://127.0.0.1:%d" % PORT)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
