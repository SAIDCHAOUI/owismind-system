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
from owismind_factory import agent_settings, fctx, guided, guided_store, hub, pipeline, probes
from owismind_factory import guardrails, prompt_writer, review, wizard
from owismind_factory.spec import DomainSpec, SpecError

logger = logging.getLogger(__name__)

# Hub prompt writes are constrained to this subtree (defense in depth: the path is never trusted).
_PROMPTS_PREFIX = "/python/owismind_hub/prompts/"

# A domain key is snake_case (same shape DomainSpec enforces). Used to build the hub path
# where a wizard draft is persisted, so we validate it before touching the library.
_DOMAIN_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")

# Hub write size caps: a prompt stays within the documented persona sanity window, and the
# capabilities registry is bounded in entry count and serialized weight. The registry caps
# are the HUB's constants (enforced fail-closed in hub.write_capabilities, the single write
# point); this route only relays them for a readable 400 before the library is touched.
_PROMPT_MAX_CHARS = 20000
_CAPABILITIES_MAX_ENTRIES = hub.CAPABILITIES_MAX_ENTRIES
_CAPABILITIES_MAX_BYTES = hub.CAPABILITIES_MAX_BYTES


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

    Delegates the traversal/subtree rules to ``hub.safe_hub_path`` (the shared
    fail-closed gate also applied inside hub.write_text / hub.delete_path) and
    adds this route's narrower constraint: the /python/owismind_hub/prompts/ prefix.
    """
    try:
        hub.safe_hub_path(path)
    except (TypeError, ValueError):
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

    Client-supplied discovery / schema_hints in the request body are IGNORED, so a
    direct API caller cannot bypass the probe-confirmation gate. The policy itself
    (hub-only + write-probe confirmation) lives in guided.probe_gates, the single
    implementation shared with the guided machine (test:
    tests/test_security_console.py TestProbeGatesNeverFromBody).
    """
    return guided.probe_gates(project)


# Same convention as the guided machine / removal inventory / notebook 04.
_wizard_config_path = hub.wizard_config_path


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
    # Same bounds the agents enforce when they load the file (an out-of-bounds file
    # would be silently ignored at agent start, so refuse it here, readably).
    if path == hub.PERSONA_PATH and len(content.strip()) < agent_settings.PERSONA_MIN_CHARS:
        return _err("persona_too_short", 400, {"min": agent_settings.PERSONA_MIN_CHARS})
    if path.endswith("/business_prompt.md") and len(content) > prompt_writer.PROMPT_MAX_CHARS:
        return _err("business_prompt_too_long", 400, {"limit": prompt_writer.PROMPT_MAX_CHARS,
                                                      "got": len(content)})
    if path.endswith("/understand_extra.md") and len(content) > agent_settings.EXTRA_MAX_CHARS:
        return _err("extra_too_long", 400, {"limit": agent_settings.EXTRA_MAX_CHARS,
                                            "got": len(content)})
    # Prompt-injection gate: a text with high-severity findings (override orders,
    # prompt-exfiltration asks, role spoofing, destructive SQL...) is refused unless
    # the operator explicitly acknowledges the findings after reading them.
    findings = guardrails.scan(content)
    if guardrails.has_high(findings) and body.get("acknowledge_risks") is not True:
        return _err("suspicious_content", 400, {"findings": findings})
    hub.write_prompt(_project(), path, content)
    return jsonify({"status": "ok", "path": path, "findings": findings})


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
    findings = guardrails.scan("\n".join(str((c or {}).get("planner_description") or "")
                                         for c in caps.values() if isinstance(c, dict)))
    if guardrails.has_high(findings) and body.get("acknowledge_risks") is not True:
        return _err("suspicious_content", 400, {"findings": findings})
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


# ----------------------------------------------------------------- central models + agent settings
# models.json is the ONE place that maps smart / pro / claude to an LLM Mesh model,
# centrally and per agent (see owismind_factory.hub "models"). Agents read it at start.

@app.route("/api/models", methods=["GET"])
@_safe
def api_models_get():
    """Central model map: stored file (or embedded defaults), plus the project's LLM list."""
    project = _project()
    stored = hub.read_models(project)
    return jsonify({
        "status": "ok",
        "models": stored or hub.DEFAULT_MODELS,
        "from_file": stored is not None,
        "defaults": hub.DEFAULT_MODELS,
        "available_llms": hub.list_available_llms(project),
    })


@app.route("/api/models", methods=["POST"])
@_safe
def api_models_post():
    """Validate then write models.json (previous file backed up). Requires confirm."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    models = body.get("models")
    if not isinstance(models, dict):
        return _err("models_required", 400)
    problems = hub.validate_models(models)
    if problems:
        return _err("invalid_models", 400, {"problems": problems})
    hub.write_models(_project(), models)
    return jsonify({"status": "ok"})


@app.route("/api/agent/settings", methods=["GET"])
@_safe
def api_agent_settings():
    """The Settings view of one agent: LLM per mode, prompts, routing text, tools (read-only)."""
    key = str(request.args.get("key") or "").strip()
    if not key:
        return _err("key_required", 400)
    project = _project()
    caps = hub.read_capabilities(project) or {}
    try:
        bundle = agent_settings.agent_bundle(project, key, caps, hub.get_settings(project))
    except KeyError:
        return _err("unknown_agent", 404)
    bundle["available_llms"] = hub.list_available_llms(project)
    bundle["central_models"] = (hub.read_models(project) or hub.DEFAULT_MODELS).get("modes")
    return jsonify({"status": "ok", "settings": bundle})


@app.route("/api/agent/prompt-draft", methods=["POST"])
@_safe
def api_agent_prompt_draft():
    """Write or improve a sub-agent's business prompt with the factory AI, in a background job
    (30-120s). Returns the text only: NOTHING is saved here, the operator reviews it first.
    Requires confirm. Sends aggregated profile metadata and a few masked sample rows."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    key = str(body.get("capability_key") or "").strip()
    project = _project()
    entry = (hub.read_capabilities(project) or {}).get(key)
    if not isinstance(entry, dict):
        return _err("unknown_capability", 404)
    current = body.get("current")
    instructions = body.get("instructions")
    if not isinstance(current, str):
        current = ""
    if not isinstance(instructions, str):
        instructions = ""
    if len(current) > prompt_writer.MAX_CURRENT_CHARS:
        return _err("current_too_large", 400, {"limit": prompt_writer.MAX_CURRENT_CHARS})
    _, rec = _new_job("prompt")
    if rec is None:
        return _err("too_many_jobs", 429)
    _run_job(rec, lambda: prompt_writer.draft(project, entry, current=current,
                                              instructions=instructions))
    return jsonify({"status": "ok", "job_id": rec["id"]})


@app.route("/api/guardrails/scan", methods=["POST"])
@_safe
def api_guardrails_scan():
    """Scan a text for prompt-injection shapes (pure, writes nothing). The console calls it
    before a Save to show the operator what looks suspicious."""
    body = request.get_json(silent=True) or {}
    text = body.get("text")
    if not isinstance(text, str) or len(text) > 100000:
        return _err("text_required", 400)
    findings = guardrails.scan(text)
    return jsonify({"status": "ok", "findings": findings, "high": guardrails.has_high(findings)})


@app.route("/api/capability/description", methods=["POST"])
@_safe
def api_capability_description():
    """Edit the routing description the orchestrator reads for one sub-agent. Requires confirm."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    key = str(body.get("capability_key") or "").strip()
    if not key:
        return _err("capability_key_required", 400)
    # The routing text is injected in the orchestrator prompt on EVERY turn: same
    # injection gate as the prompts (explicit acknowledgement after reading).
    findings = guardrails.scan(str(body.get("description") or ""))
    if guardrails.has_high(findings) and body.get("acknowledge_risks") is not True:
        return _err("suspicious_content", 400, {"findings": findings})
    try:
        agent_settings.set_planner_description(_project(), key, body.get("description"))
    except KeyError:
        return _err("unknown_capability", 404)
    except ValueError as exc:
        return _err("invalid_description", 400, {"problems": [str(exc)]})
    return jsonify({"status": "ok"})


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


@app.route("/api/guided/start-review", methods=["POST"])
@_safe
def api_guided_start_review():
    """Create a guided REVIEW run for an existing sub-agent: its first stage
    reads the live semantic model synchronously (read-only). Requires confirm.
    One active run at a time. A sub-agent whose model was not created by the
    factory answers 409 review_not_supported (nothing is saved)."""
    body = request.get_json(silent=True) or {}
    if not _confirmed(body):
        return _err("confirmation_required", 400)
    key = str(body.get("capability_key") or "").strip()
    if not key:
        return _err("capability_key_required", 400)
    project = _project()
    caps = hub.read_capabilities(project) or {}
    if not isinstance(caps.get(key), dict):
        return _err("unknown_capability", 404)
    settings = hub.get_settings(project)
    try:
        store = _guided_store_for(project, settings)
        active = store.load_active()
        if active is not None:
            return _err("active_run_exists", 409, {"run_id": active.get("run_id")})
        try:
            run = guided.start_review_run(project, key, settings=settings)
        except guided.ReviewUnsupported as exc:
            return _err("review_not_supported", 409, {"reason": str(exc)})
        store.save(run)
    except guided_store.GuidedStoreError as exc:
        return _err("storage_not_configured", 500, {"messages": [str(exc)]})
    return jsonify({"status": "ok", "run": run})


def _guided_run_id(body):
    """Shared confirm + run_id prefix of the /api/guided/* run routes.
    Returns (run_id, err) where err is a ready error response."""
    if not _confirmed(body):
        return None, _err("confirmation_required", 400)
    run_id = str(body.get("run_id") or "").strip()
    if not run_id:
        return None, _err("run_id_required", 400)
    return run_id, None


def _guided_load(run_id, require_active):
    """Shared project/settings/store/load sequence of the guided run routes.
    Returns (project, settings, store, run, err). require_active=False for the
    idempotent abandon route (a non-active run is a no-op there, never a 409)."""
    project = _project()
    settings = hub.get_settings(project)
    try:
        store = _guided_store_for(project, settings)
        run = store.load(run_id)
    except guided_store.GuidedStoreError as exc:
        return None, None, None, None, _err(
            "storage_not_configured", 500, {"messages": [str(exc)]})
    if run is None:
        return None, None, None, None, _err("unknown_run", 404)
    if require_active and run.get("status") != guided.RUN_ACTIVE:
        return None, None, None, None, _err("run_not_active", 409)
    return project, settings, store, run, None


@app.route("/api/guided/run", methods=["POST"])
@_safe
def api_guided_run():
    """Execute the CURRENT auto stage in a background job (live journal via the
    shared FactoryContext). Requires confirm. Serialized with execute jobs."""
    body = request.get_json(silent=True) or {}
    run_id, err = _guided_run_id(body)
    if err is not None:
        return err
    project, settings, store, run, err = _guided_load(run_id, require_active=True)
    if err is not None:
        return err
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
    run_id, err = _guided_run_id(body)
    if err is not None:
        return err
    # Busy gate BEFORE loading (contract: a busy console answers 409 busy even
    # for an unknown run_id, exactly as before the helper extraction).
    if _guided_job_running():
        return _err("busy", 409)
    project, settings, store, run, err = _guided_load(run_id, require_active=True)
    if err is not None:
        return err
    if not guided.can_verify(run):
        return _err("stage_not_verifiable", 400)
    try:
        run = guided.verify_current_stage(project, run, settings=settings)
        store.save(run)
    except guided_store.GuidedStoreError as exc:
        return _err("storage_not_configured", 500, {"messages": [str(exc)]})
    return jsonify({"status": "ok", "run": run})


# ----------------------------------------------------------------- review of a sub-agent

def _review_feedback_body(body):
    feedback = body.get("feedback") if isinstance(body.get("feedback"), dict) else {}
    answers = body.get("answers") if isinstance(body.get("answers"), dict) else {}
    clean_answers = {}
    for qid, value in list(answers.items())[:10]:
        clean_answers[str(qid)[:60]] = str(value or "")[:1000]
    return ({"wrong": str(feedback.get("wrong") or ""), "know": str(feedback.get("know") or "")},
            clean_answers)


def _review_waiting(run):
    return (guided.is_review(run) and run.get("current_stage") == "review_feedback"
            and guided.can_verify(run))


@app.route("/api/review/propose", methods=["POST"])
@_safe
def api_review_propose():
    """Ask the AI for changes from the business feedback (one LLM call, background
    job, 30-90s). Reads the live model config stored on the run, the profile, the
    owner column descriptions and a bounded masked sample of rows. Writes nothing
    in DSS: the proposal is stored on the run. Requires confirm."""
    body = request.get_json(silent=True) or {}
    run_id, err = _guided_run_id(body)
    if err is not None:
        return err
    project, settings, store, run, err = _guided_load(run_id, require_active=True)
    if err is not None:
        return err
    if not _review_waiting(run):
        return _err("stage_not_verifiable", 400)
    feedback, answers = _review_feedback_body(body)
    if not (feedback["wrong"].strip() or feedback["know"].strip()):
        return _err("feedback_required", 400)
    _, rec = _new_job("wizard")
    if rec is None:
        return _err("too_many_jobs", 429)
    info = run["state"]["review"]
    spec = guided._review_spec(run["state"])

    def work():
        from owismind_factory import review
        result = review.propose(project, spec, info.get("base"), info.get("routing"),
                                feedback, answers=answers)
        if "error" in result:
            return {"error": result["error"]}
        fresh = store.load(run_id)
        if fresh is None or not _review_waiting(fresh):
            return {"error": "the review moved on while the AI was working"}
        guided.record_review_proposal(fresh, result, feedback, answers)
        store.save(fresh)
        return {"run": fresh}

    _run_job(rec, work)
    return jsonify({"status": "ok", "job_id": rec["id"]})


@app.route("/api/review/keep", methods=["POST"])
@_safe
def api_review_keep():
    """Record which proposed changes the expert keeps, then verify the stage
    (advances to the apply stage when at least one known change is kept).
    Requires confirm. Writes nothing in DSS."""
    body = request.get_json(silent=True) or {}
    run_id, err = _guided_run_id(body)
    if err is not None:
        return err
    if _guided_job_running():
        return _err("busy", 409)
    project, settings, store, run, err = _guided_load(run_id, require_active=True)
    if err is not None:
        return err
    if not _review_waiting(run):
        return _err("stage_not_verifiable", 400)
    keep = body.get("keep") if isinstance(body.get("keep"), list) else []
    info = run["state"]["review"]
    # The human has the last word: rewrites replace the AI's text BEFORE anything
    # is applied (only for changes the proposal marks editable; kept ids only).
    edits = body.get("edits") if isinstance(body.get("edits"), dict) else {}
    edits = dict((str(k)[:300], v) for k, v in list(edits.items())[:500]
                 if isinstance(v, str) and str(k) in set(str(x) for x in keep))
    # A kept change the scanner flagged as injection-shaped needs the same explicit
    # acknowledgement as a flagged edit (the human may keep it, knowingly).
    kept_ids = set(str(k) for k in keep)
    flagged = [f for c in info.get("changes") or [] if c.get("id") in kept_ids
               for f in (c.get("flags") or []) if f.get("severity") == "high"]
    if flagged and body.get("acknowledge_risks") is not True:
        return _err("suspicious_content", 400, {"findings": flagged})
    if edits:
        edit_findings = guardrails.scan("\n".join(edits.values()))
        if guardrails.has_high(edit_findings) and body.get("acknowledge_risks") is not True:
            return _err("suspicious_content", 400, {"findings": edit_findings})
        try:
            info["proposal"], info["changes"] = review.apply_edits(
                info.get("proposal"), info.get("changes"), edits)
        except ValueError as exc:
            return _err("invalid_edit", 400, {"problems": [str(exc)]})
    info["keep"] = [str(k)[:300] for k in keep[:500]]
    try:
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
    run_id, err = _guided_run_id(body)
    if err is not None:
        return err
    _project_, _settings, store, run, err = _guided_load(run_id, require_active=False)
    if err is not None:
        return err
    try:
        if run.get("status") == guided.RUN_ACTIVE:
            guided.abandon_run(run)
            store.save(run)
    except guided_store.GuidedStoreError as exc:
        return _err("storage_not_configured", 500, {"messages": [str(exc)]})
    return jsonify({"status": "ok"})
