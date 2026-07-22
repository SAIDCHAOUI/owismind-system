# OWIsMind - Agent Factory Console: Python backend (paste into the Standard webapp Python pane).
#
# Admin, DESIGN-TIME webapp that drives the "agent factory": it plans and runs the creation of a
# new dataset-specialist sub-agent chain in this DSS project, and edits the Config & Prompt Hub
# (/python/owismind_hub/). It is SEPARATE from the OWIsMind Vue plugin webapp.
#
# DSS provides the Flask ``app``. The frontend (script.js) calls these routes via
# getWebAppBackendUrl('api/...'). Everything runs against the OFFICIAL public API through the
# ``owismind_factory`` engine, which lives in this project's library (python/). In DSS the project
# library python/ folder is importable, so ``from owismind_factory import ...`` resolves at runtime.
#
# Safety model:
#   - Python 3.9, stdlib + dataiku + flask only. No pandas, no langchain.
#   - Read routes (state / datasets / hub reads) are plain GETs.
#   - EVERY mutating route requires the JSON body to carry {"confirm": true}, else it returns
#     {"status":"error","error":"confirmation_required"} without doing anything.
#   - "plan" is a dry-run (FactoryContext(dry_run=True)): it never touches DSS. "execute" runs for
#     real but is idempotent (ensure_* steps) and has NO deletion path anywhere.
#   - Long actions (probe / execute / wizard draft) run as background JOBS: the POST returns a
#     job_id, the frontend polls GET /api/job/<job_id>. A bounded registry keeps the last 20 jobs.
#     Admission is bounded too (at most 4 running jobs, a single mutating execute at a time,
#     429 beyond), job ids are unguessable (uuid4), and hub writes are size-capped.

import functools
import json
import logging
import re
import threading
import traceback
import uuid

from flask import request, jsonify

import dataiku

# The factory engine (pasted into the DSS project library python/owismind_factory/). The three
# modules below (pipeline / probes / wizard) are authored against FROZEN signatures; this backend
# codes against them exactly. If a module is missing at import time the whole webapp fails loudly,
# which is the desired signal that the library was not pushed.
from owismind_factory import fctx, guided, guided_store, hub, pipeline, probes, wizard
from owismind_factory.spec import DomainSpec, SpecError

logger = logging.getLogger(__name__)

# Hub prompt writes are constrained to this subtree (defense in depth: the path is never trusted).
_PROMPTS_PREFIX = "/python/owismind_hub/prompts/"

# A domain key is snake_case (same shape DomainSpec enforces). Used to build the hub path
# where a wizard draft is persisted, so we validate it before touching the library.
_DOMAIN_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

# Hub write size caps: a prompt stays within the documented persona sanity window, and the
# capabilities registry is bounded in entry count and serialized weight (defense in depth:
# an oversized POST is refused before anything reaches the library).
_PROMPT_MAX_CHARS = 20000
_CAPABILITIES_MAX_ENTRIES = 50
_CAPABILITIES_MAX_BYTES = 200 * 1024


# ----------------------------------------------------------------- error / safety helpers

def _err(code, status=400, extra=None):
    body = {"status": "error", "error": code}
    if extra:
        body.update(extra)
    return jsonify(body), status


def _safe(fn):
    """Wrap a route so any uncaught exception degrades to a clean JSON 500 (LAB idiom)."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.error("%s failed\n%s", fn.__name__, traceback.format_exc())
            return _err("server_error", 500)
    return wrapped


def _confirmed(body):
    """True when the JSON body explicitly carries confirm == True."""
    return isinstance(body, dict) and body.get("confirm") is True


def _project():
    """The current DSS project handle (the webapp runs inside its project)."""
    return dataiku.api_client().get_default_project()


def _safe_prompt_path(path):
    """Validate a hub prompt path, returning it unchanged when safe, else None.

    These are VIRTUAL DSS library paths, so we never run os.path on them (which
    could resolve '..'). We reject any traversal or separator trick ('..', '//',
    a backslash) and enforce the /python/owismind_hub/prompts/ prefix, so a crafted path
    can never escape the prompts subtree even if the library API resolves '..'.
    """
    if not isinstance(path, str):
        return None
    if ".." in path or "//" in path or "\\" in path:
        return None
    if not path.startswith(_PROMPTS_PREFIX):
        return None
    return path


# ----------------------------------------------------------------- background jobs

# Module-level, lock-guarded, bounded registry. Job records hold either a shared FactoryContext
# (execute: actions are serialized live at read time) or a plain actions list (probe / wizard).
_JOBS = {}
_JOBS_ORDER = []
_JOBS_LOCK = threading.Lock()
_JOBS_MAX = 20

# Admission bounds: every background job costs a daemon thread plus DSS / LLM calls, so the
# number of running jobs is capped globally and mutating runs (execute + guided stage runs)
# are serialized to one.
_ACTIVE_MAX = 4
_ACTIVE_MUTATING_MAX = 1
_MUTATING_KINDS = ("execute", "guided")
_ACTIVE = {"total": 0, "mutating": 0}


def _new_job(kind, ctx=None):
    """Register a running job (optionally sharing a FactoryContext) and return (job_id, record).

    Admission is bounded: at most _ACTIVE_MAX running jobs overall and _ACTIVE_MUTATING_MAX
    running mutating job. When a bound is hit nothing is registered and (None, None) is
    returned (the route answers 429). Ids are uuid4 hex so another console user cannot
    enumerate or guess them.
    """
    mutating = kind in _MUTATING_KINDS
    with _JOBS_LOCK:
        if _ACTIVE["total"] >= _ACTIVE_MAX:
            return None, None
        if mutating and _ACTIVE["mutating"] >= _ACTIVE_MUTATING_MAX:
            return None, None
        _ACTIVE["total"] += 1
        if mutating:
            _ACTIVE["mutating"] += 1
        job_id = uuid.uuid4().hex
        rec = {"id": job_id, "kind": kind, "status": "running",
               "ctx": ctx, "result": None, "error": None}
        _JOBS[job_id] = rec
        _JOBS_ORDER.append(job_id)
        while len(_JOBS_ORDER) > _JOBS_MAX:
            # Evict the OLDEST job that is not currently running. A running execute
            # job may still be mutating DSS and must stay pollable, so we skip
            # running records; if every tracked job is running we exceed the cap
            # rather than drop a live one.
            victim = None
            for jid in _JOBS_ORDER:
                if _JOBS.get(jid, {}).get("status") != "running":
                    victim = jid
                    break
            if victim is None:
                break
            _JOBS_ORDER.remove(victim)
            _JOBS.pop(victim, None)
    return job_id, rec


def _release_job_slot(kind):
    """Free the admission slot taken by _new_job (called from the worker's finally)."""
    with _JOBS_LOCK:
        _ACTIVE["total"] = max(0, _ACTIVE["total"] - 1)
        if kind in _MUTATING_KINDS:
            _ACTIVE["mutating"] = max(0, _ACTIVE["mutating"] - 1)


def _run_job(rec, work):
    """Run ``work()`` in a daemon thread; store its return as the job result (or the error)."""
    def worker():
        try:
            result = work()
            with _JOBS_LOCK:
                rec["result"] = result
                rec["status"] = "done"
        except Exception as exc:  # noqa: BLE001 - reported to the client, not re-raised
            logger.error("job %s (%s) failed\n%s", rec["id"], rec["kind"], traceback.format_exc())
            with _JOBS_LOCK:
                rec["error"] = str(exc)
                rec["status"] = "error"
        finally:
            # The admission slot is freed whatever happened above, so a crashed
            # job can never leak a slot and starve the console.
            _release_job_slot(rec["kind"])
    th = threading.Thread(target=worker)
    th.daemon = True
    th.start()


@app.route("/api/job/<job_id>", methods=["GET"])
@_safe
def api_job(job_id):
    """Poll a background job. Returns {status: running|done|error, actions, result?, error?}.

    When the job owns a shared FactoryContext, its actions are serialized live under the lock so
    the frontend journal updates as the pipeline progresses.
    """
    with _JOBS_LOCK:
        rec = _JOBS.get(job_id)
        if not rec:
            return _err("unknown_job", 404)
        ctx = rec.get("ctx")
        actions = list(ctx.actions) if ctx is not None else []
        out = {"status": rec["status"], "actions": actions}
        if rec["status"] == "done":
            out["result"] = rec["result"]
        elif rec["status"] == "error":
            out["error"] = rec["error"]
    return jsonify(out)


# ----------------------------------------------------------------- read routes

@app.route("/api/state", methods=["GET"])
@_safe
def api_state():
    """Project + hub snapshot for the overview screen (read-only)."""
    project = _project()
    caps_raw = hub.read_capabilities(project)
    settings = hub.get_settings(project)
    return jsonify({
        "status": "ok",
        "project_key": project.project_key,
        "settings": settings,
        "capabilities": caps_raw or {},
        "hub_ready": caps_raw is not None,
    })


@app.route("/api/datasets", methods=["GET"])
@_safe
def api_datasets():
    """The project's datasets (name + type) for the pickers. Read-only, bounded."""
    project = _project()
    out = []
    for d in project.list_datasets():
        # list_datasets() items are dict-like (DSSDatasetListItem); stay robust either way.
        if isinstance(d, dict):
            name = d.get("name")
            dtype = d.get("type") or ""
        else:
            name = getattr(d, "name", None)
            dtype = getattr(d, "type", "") or ""
        if name:
            out.append({"name": name, "type": dtype})
    out.sort(key=lambda x: x["name"].lower())
    return jsonify({"status": "ok", "datasets": out})


# ----------------------------------------------------------------- plan (synchronous dry-run)

def _spec_from_body(body):
    """Build a validated DomainSpec from the request body, or (None, error_response)."""
    spec_data = (body or {}).get("spec")
    if not isinstance(spec_data, dict):
        return None, _err("spec_required", 400)
    try:
        return DomainSpec.from_dict(spec_data), None
    except SpecError as exc:
        return None, _err("invalid_spec", 400, {"messages": [str(exc)]})


def _gates_from_hub(project, body):
    """Resolve the pipeline gates (tool discovery + agent schema hints) from the hub.

    This console ALWAYS reads both gates from the probe results stored in the hub by
    00_probe_capabilities.py. Client-supplied discovery / schema_hints in the request
    body are IGNORED, so a direct API caller cannot bypass the probe-confirmation gate.
    schema_hints are only used when the write probe CONFIRMED the round-trip; the
    notebook path remains the only channel to override that.
    """
    probe = hub.read_json(project, hub.HUB_ROOT + "/probe_results.json") or {}
    discovery = probe.get("suggested_discovery")
    schema_hints = probe.get("suggested_schema_hints")
    if schema_hints and not schema_hints.get("confirmed"):
        schema_hints = None
    return discovery, schema_hints


def _wizard_config_path(domain):
    """Hub path where a domain's wizard draft is persisted (same convention as the notebook)."""
    return "%s/wizard/%s-config.json" % (hub.HUB_ROOT, domain)


def _wizard_config_fallback(project, body, spec):
    """Resolve the wizard config for plan/execute: the request body wins, else the hub.

    When the body carries an explicit ``wizard_config`` dict we use it verbatim (the console
    sends the freshly drafted config this way). Otherwise we fall back to the config the wizard
    persisted to the hub for this domain, but only when it is a dict without an ``error`` key.
    Returns the config dict or None (None keeps the semantic model unconfigured, as before).
    """
    from_body = (body or {}).get("wizard_config")
    if isinstance(from_body, dict):
        return from_body
    stored = hub.read_json(project, _wizard_config_path(spec.domain))
    if isinstance(stored, dict) and "error" not in stored:
        return stored
    return None


@app.route("/api/plan", methods=["POST"])
@_safe
def api_plan():
    """Dry-run the pipeline and return the action PLAN. Safe: FactoryContext(dry_run=True) never
    touches DSS. No confirm needed (nothing is mutated)."""
    body = request.get_json(silent=True) or {}
    spec, err = _spec_from_body(body)
    if err:
        return err
    project = _project()
    discovery, schema_hints = _gates_from_hub(project, body)
    wizard_config = _wizard_config_fallback(project, body, spec)
    # Non-blocking preflight warnings (collisions, weak routing, name headroom)
    # against what is already registered in the hub.
    caps = hub.read_capabilities(project) or {}
    warnings = spec.preflight(
        existing_capability_keys=list(caps.keys()),
        existing_domains=[c.get("domain") for c in caps.values() if isinstance(c, dict)])
    ctx = fctx.FactoryContext(project=project, dry_run=True, abort_on_failure=False)
    pipeline.create_domain(ctx, spec, wizard_config=wizard_config,
                           discovery=discovery, schema_hints=schema_hints,
                           steps=body.get("steps"))
    return jsonify({"status": "ok", "warnings": warnings,
                    "runbook": ctx.runbook_markdown(), **ctx.summary()})


# ----------------------------------------------------------------- execute (background, confirm)

@app.route("/api/execute", methods=["POST"])
@_safe
def api_execute():
    """Run the pipeline for real in a background job. Requires confirm. Idempotent, no deletions.

    The shared FactoryContext is stored on the job record so GET /api/job/<id> serializes actions
    live. Gated/undocumented steps degrade to MANUAL entries inside the pipeline (never guessed).
    """
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    spec, err = _spec_from_body(body)
    if err:
        return err
    steps = body.get("steps")
    project = _project()
    discovery, schema_hints = _gates_from_hub(project, body)
    wizard_config = _wizard_config_fallback(project, body, spec)
    ctx = fctx.FactoryContext(project=project, dry_run=False, abort_on_failure=False)
    _, rec = _new_job("execute", ctx=ctx)
    if rec is None:
        return _err("too_many_jobs", 429)

    def work():
        pipeline.create_domain(ctx, spec, wizard_config=wizard_config,
                               discovery=discovery, schema_hints=schema_hints,
                               steps=steps)
        summary = ctx.summary()
        # The runbook is the operator's ordered to-do after a real run.
        summary["runbook"] = ctx.runbook_markdown()
        return summary

    _run_job(rec, work)
    return jsonify({"status": "ok", "job_id": rec["id"]})


# ----------------------------------------------------------------- probe (background, confirm)

@app.route("/api/probe", methods=["POST"])
@_safe
def api_probe():
    """Run the Phase 0 read-only probes in a background job. Requires confirm (explicit intent),
    though the probes themselves create/modify/delete nothing."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    project = _project()
    _, rec = _new_job("probe")
    if rec is None:
        return _err("too_many_jobs", 429)

    def work():
        results = probes.run_read_probes(project)
        return {"report": probes.format_probe_report(results), "raw": results}

    _run_job(rec, work)
    return jsonify({"status": "ok", "job_id": rec["id"]})


# ----------------------------------------------------------------- wizard draft (background, confirm)

@app.route("/api/wizard/draft", methods=["POST"])
@_safe
def api_wizard_draft():
    """Draft (or re-draft with answers) the semantic model config via an LLM call, in a background
    job (30-90s). Requires confirm. Only aggregated profile metadata is sent to the LLM."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    profile_dataset = str(body.get("profile_dataset") or "").strip()
    if not profile_dataset:
        return _err("profile_dataset_required", 400)
    base_dataset = str(body.get("base_dataset") or "").strip() or None
    answers = body.get("answers")
    # Optional: when a valid snake_case domain is given we persist the draft to the hub so
    # plan/execute can pick it up later even without the body carrying it. Ignore junk.
    domain = str(body.get("domain") or "").strip()
    if not _DOMAIN_RE.match(domain):
        domain = None
    project = _project()
    _, rec = _new_job("wizard")
    if rec is None:
        return _err("too_many_jobs", 429)

    def work():
        config = wizard.draft_model_config(project, profile_dataset,
                                           answers=answers, base_dataset=base_dataset)
        if domain and isinstance(config, dict) and "error" not in config:
            hub.write_json(project, _wizard_config_path(domain), config)
        return config

    _run_job(rec, work)
    return jsonify({"status": "ok", "job_id": rec["id"]})


# ----------------------------------------------------------------- hub: prompts

@app.route("/api/hub/prompt", methods=["GET"])
@_safe
def api_hub_prompt_get():
    """Read a hub prompt file. The path MUST live under /python/owismind_hub/prompts/ (rejected otherwise)."""
    path = _safe_prompt_path(request.args.get("path") or "")
    if path is None:
        return _err("invalid_path", 400)
    content = hub.read_text(_project(), path)
    return jsonify({"status": "ok", "path": path, "content": content or ""})


@app.route("/api/hub/prompt", methods=["POST"])
@_safe
def api_hub_prompt_post():
    """Write a hub prompt file (a backup of the previous version is made). Requires
    confirm; path MUST live under /python/owismind_hub/prompts/."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    path = _safe_prompt_path(str(body.get("path") or ""))
    if path is None:
        return _err("invalid_path", 400)
    content = body.get("content")
    if not isinstance(content, str):
        return _err("content_required", 400)
    if len(content) > _PROMPT_MAX_CHARS:
        return _err("content_too_large", 400,
                    {"limit": _PROMPT_MAX_CHARS, "got": len(content)})
    hub.write_prompt(_project(), path, content)
    return jsonify({"status": "ok", "path": path})


# ----------------------------------------------------------------- hub: capabilities

@app.route("/api/hub/capabilities", methods=["GET"])
@_safe
def api_hub_capabilities_get():
    """Read the runtime capabilities registry (empty object when the hub file is absent)."""
    caps = hub.read_capabilities(_project())
    return jsonify({"status": "ok", "capabilities": caps or {}})


@app.route("/api/hub/capabilities", methods=["POST"])
@_safe
def api_hub_capabilities_post():
    """Validate then write capabilities.json (a backup of the previous file is made). Requires
    confirm. Validation problems are returned on 400 and nothing is written."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    caps = body.get("capabilities")
    if not isinstance(caps, dict):
        return _err("capabilities_required", 400)
    if len(caps) > _CAPABILITIES_MAX_ENTRIES:
        return _err("too_many_capabilities", 400,
                    {"limit": _CAPABILITIES_MAX_ENTRIES, "got": len(caps)})
    if len(json.dumps(caps).encode("utf-8")) > _CAPABILITIES_MAX_BYTES:
        return _err("capabilities_too_large", 400,
                    {"limit_bytes": _CAPABILITIES_MAX_BYTES})
    problems = hub.validate_capabilities(caps)
    if problems:
        return _err("invalid_capabilities", 400, {"problems": problems})
    hub.write_capabilities(_project(), caps)
    return jsonify({"status": "ok"})


@app.route("/api/capability/enable", methods=["POST"])
@_safe
def api_capability_enable():
    """Flip one capability's enabled flag (validated, backed-up hub write).
    Requires confirm. The UI reminds the operator to re-save the orchestrator
    (the registry is loaded at process start, lesson L168)."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    key = str(body.get("capability_key") or "").strip()
    if not key:
        return _err("capability_key_required", 400)
    project = _project()
    try:
        caps = hub.set_capability_enabled(project, key, bool(body.get("enabled")))
    except KeyError:
        return _err("unknown_capability", 404)
    except ValueError as exc:
        return _err("invalid_capabilities", 400, {"problems": [str(exc)]})
    return jsonify({"status": "ok", "capabilities": caps})


# ----------------------------------------------------------------- guided assistant
# The step-by-step "Assistant" screen. The run STATE lives in one direct-SQL row
# (owismind_factory.guided_store, plugin storage pattern: parameterized values,
# COMMIT on write, PROJECT_KEY-prefixed table), so a reload or a backend restart
# resumes exactly where the operator was. The machine itself is
# owismind_factory.guided; this layer only loads, delegates and saves.

def _guided_store_for(project, settings):
    return guided_store.GuidedStore(
        settings.get("sql_connection") or "SQL_owi",
        project.project_key)


def _guided_job_running():
    with _JOBS_LOCK:
        return any(rec.get("kind") == "guided" and rec.get("status") == "running"
                   for rec in _JOBS.values())


@app.route("/api/guided/current", methods=["GET"])
@_safe
def api_guided_current():
    """The active guided run (full state), or null. Self-heals a stage left
    RUNNING by a backend restart (no guided job can be running in a fresh
    process, so the demotion is safe)."""
    project = _project()
    settings = hub.get_settings(project)
    try:
        store = _guided_store_for(project, settings)
        run = store.load_active()
        if run is not None and not _guided_job_running() and guided.heal_interrupted(run):
            store.save(run)
    except guided_store.GuidedStoreError as exc:
        return _err("storage_not_configured", 500, {"messages": [str(exc)]})
    return jsonify({"status": "ok", "run": run})


@app.route("/api/guided/start", methods=["POST"])
@_safe
def api_guided_start():
    """Create a guided run and execute its (read-only) preflight synchronously.
    Requires confirm. One active run at a time: abandon the current one first."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    spec, err = _spec_from_body(body)
    if err:
        return err
    project = _project()
    settings = hub.get_settings(project)
    try:
        store = _guided_store_for(project, settings)
        active = store.load_active()
        if active is not None:
            return _err("active_run_exists", 409, {"run_id": active.get("run_id")})
        run = guided.start_run(project, spec, settings=settings)
        store.save(run)
    except guided_store.GuidedStoreError as exc:
        return _err("storage_not_configured", 500, {"messages": [str(exc)]})
    return jsonify({"status": "ok", "run": run})


@app.route("/api/guided/start-removal", methods=["POST"])
@_safe
def api_guided_start_removal():
    """Create a guided REMOVAL run (its inventory runs synchronously; nothing
    is deleted before the operator confirms each stage). Requires confirm AND
    the domain name TYPED by the operator (server-side check: a spoofed client
    cannot skip it). One active run at a time."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    key = str(body.get("capability_key") or "").strip()
    if not key:
        return _err("capability_key_required", 400)
    project = _project()
    caps = hub.read_capabilities(project) or {}
    entry = caps.get(key)
    if not isinstance(entry, dict):
        return _err("unknown_capability", 404)
    typed = str(body.get("domain_typed") or "").strip()
    if not typed or typed != str(entry.get("domain") or ""):
        return _err("domain_mismatch", 400)
    settings = hub.get_settings(project)
    try:
        store = _guided_store_for(project, settings)
        active = store.load_active()
        if active is not None:
            return _err("active_run_exists", 409, {"run_id": active.get("run_id")})
        run = guided.start_removal_run(project, key, settings=settings)
        store.save(run)
    except guided_store.GuidedStoreError as exc:
        return _err("storage_not_configured", 500, {"messages": [str(exc)]})
    return jsonify({"status": "ok", "run": run})


@app.route("/api/guided/run", methods=["POST"])
@_safe
def api_guided_run():
    """Execute the CURRENT auto stage in a background job (live journal via the
    shared FactoryContext). Requires confirm. Serialized with execute jobs."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    run_id = str(body.get("run_id") or "").strip()
    if not run_id:
        return _err("run_id_required", 400)
    project = _project()
    settings = hub.get_settings(project)
    try:
        store = _guided_store_for(project, settings)
        run = store.load(run_id)
    except guided_store.GuidedStoreError as exc:
        return _err("storage_not_configured", 500, {"messages": [str(exc)]})
    if run is None:
        return _err("unknown_run", 404)
    if run.get("status") != guided.RUN_ACTIVE:
        return _err("run_not_active", 409)
    if not guided.can_run(run):
        return _err("stage_not_runnable", 400)
    ctx = fctx.FactoryContext(project=project, dry_run=False, abort_on_failure=False)
    _, rec = _new_job("guided", ctx=ctx)
    if rec is None:
        return _err("too_many_jobs", 429)

    # Persist a RUNNING marker on a copy, so a reload during the job shows the
    # stage as running (the in-memory ``run`` stays runnable for the worker).
    try:
        marker = json.loads(json.dumps(run))
        marker["state"]["stages"][marker["current_stage"]]["status"] = "running"
        store.save(marker)
    except Exception:
        logger.warning("could not persist the running marker", exc_info=True)

    def work():
        try:
            updated = guided.run_current_stage(project, run, settings=settings, ctx=ctx)
        except Exception:
            # Surface the failure ON the run (never leave a stage stuck RUNNING).
            stage = run["state"]["stages"].get(run.get("current_stage")) or {}
            stage["status"] = "failed"
            stage["problems"] = ["Erreur inattendue pendant l'exécution : voir les logs backend."]
            store.save(run)
            raise
        store.save(updated)
        return {"run": updated}

    _run_job(rec, work)
    return jsonify({"status": "ok", "job_id": rec["id"]})


@app.route("/api/guided/verify", methods=["POST"])
@_safe
def api_guided_verify():
    """'C'est fait' on a manual stage: verify against DSS, advance only on
    success. Requires confirm. Refused while a guided/execute job is running."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    run_id = str(body.get("run_id") or "").strip()
    if not run_id:
        return _err("run_id_required", 400)
    if _guided_job_running():
        return _err("busy", 409)
    project = _project()
    settings = hub.get_settings(project)
    try:
        store = _guided_store_for(project, settings)
        run = store.load(run_id)
        if run is None:
            return _err("unknown_run", 404)
        if run.get("status") != guided.RUN_ACTIVE:
            return _err("run_not_active", 409)
        if not guided.can_verify(run):
            return _err("stage_not_verifiable", 400)
        run = guided.verify_current_stage(project, run, settings=settings)
        store.save(run)
    except guided_store.GuidedStoreError as exc:
        return _err("storage_not_configured", 500, {"messages": [str(exc)]})
    return jsonify({"status": "ok", "run": run})


@app.route("/api/guided/abandon", methods=["POST"])
@_safe
def api_guided_abandon():
    """Mark the run abandoned (idempotent). NOTHING is deleted in DSS."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    run_id = str(body.get("run_id") or "").strip()
    if not run_id:
        return _err("run_id_required", 400)
    project = _project()
    settings = hub.get_settings(project)
    try:
        store = _guided_store_for(project, settings)
        run = store.load(run_id)
        if run is None:
            return _err("unknown_run", 404)
        if run.get("status") == guided.RUN_ACTIVE:
            guided.abandon_run(run)
            store.save(run)
    except guided_store.GuidedStoreError as exc:
        return _err("storage_not_configured", 500, {"messages": [str(exc)]})
    return jsonify({"status": "ok"})
