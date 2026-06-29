"""OWIsMind WebApp HTTP API (Flask blueprint, mounted under /owismind-api).

Routes:
  - ``/ping``          : health check + resolved storage configuration.
  - ``/me``            : caller identity (resolved server-side) + admin/config flags. POST
                         also records the caller in the users registry + first-admin bootstrap;
                         GET stays read-only.
  - ``/usage``         : the caller's own monthly budget status (spend / limit / remaining).
  - ``/agents``        : the agents the admin enabled (opaque logical keys + labels).
  - ``/chat/start``    : run a real agent for one message in a background worker and
                         return a run_id; persists the user message first (phase one).
  - ``/chat/poll``     : fetch the run's normalised events since a cursor (live timeline);
                         the worker persists the answer + any generated SQL on completion.
  - ``/chat/stop``     : request a cooperative early stop of one's own in-flight run.
  - ``/chat/feedback`` : persist a 👍/👎 (+ optional reasons/comment) on one's own message.
  - ``/conversations`` : names-only, keyset-paginated conversation list (sidebar).
  - ``/conversation``  : all messages of ONE session, fetched lazily on click.
  - ``/evidence/*``    : Evidence Studio - meta / rows / distinct (owner-scoped, read-only, project datasets).
  - ``/admin/*``       : storage view + user/admin + agent-whitelist + monthly-budget management (admin-gated).

Transport is polling, not SSE: DSS's internal nginx can buffer a long-lived
event-stream so events would arrive all at once. Instead the agent runs in a
background worker (agents/stream_manager) and the front polls short requests the
proxy never buffers - the same pattern the project's production Dash app uses.

Identity is always resolved from the authenticated browser headers, never from the
request body. The frontend only ever sends logical data (e.g. {session_id, message,
agent_key}); it never chooses table, connection, query, or a raw agent id - the
agent_key is an opaque logical key resolved server-side against the whitelist.
"""

import hashlib
import json
import logging
import sys
import time
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from owismind.agents import context, discovery, stream_manager
from owismind.evidence import chart_payload
from owismind.evidence import service as evidence_service
from owismind.evidence import throttle as evidence_throttle
from owismind.storage import artifacts as artifacts_storage
from owismind.security.identity import IdentityError, derive_full_name, resolve_identity
from owismind.security.validation import (
    MAX_SESSION_ID_LENGTH,
    ValidationError,
    validate_agent_meta,
    validate_budget_amount,
    validate_chat_start_request,
    validate_conversations_limit,
    validate_evidence_column,
    validate_evidence_rows_request,
    validate_expires_days,
    validate_feedback,
    validate_history_limit,
    validate_optional_exchange_id,
    validate_quota_note,
    validate_required_exchange_id,
    validate_suggestion_from_chat,
    validate_suggestion_manual,
    validate_user_id_list,
)
from owismind.storage import admin, budget, chat_v5, settings, sql_config
from owismind.storage import suggestions as suggestions_storage
from owismind.storage.migrations import ensure_chat_table
from owismind.benchmark_view import aggregate as bench_aggregate
from owismind.benchmark_view import agent_profile as bench_profile
from owismind.benchmark_view import lab_io as bench_io
from owismind.benchmark_view import schema_check as bench_schema
# --- BEGIN impersonation (temporary, removable) ---
# Admin "act as user" (read-only). The whole feature lives in security/impersonation.py
# plus the FENCED blocks below; remove the feature = delete that module + these blocks.
from owismind.security import impersonation
# --- END impersonation ---

logger = logging.getLogger(__name__)

# Defensive cap on how many agents an admin can enable in one save.
MAX_ENABLED_AGENTS = 50

# Defensive upper bounds for the /chat/poll query params (opaque server-issued
# run_id is a 32-char uuid hex; cursor is a non-negative event index).
_MAX_RUN_ID_LENGTH = 64

api = Blueprint("owismind_api", __name__, url_prefix="/owismind-api")


def _logical_key(project_key, agent_id):
    """Deterministic, opaque logical key for an enabled agent.

    A stable hash of ``project_key:agent_id`` - stable so re-saving the selection
    keeps the same key, opaque so the chat front never receives a raw agent_id
    (the whitelist requirement: the front references an agent only by this key).
    """
    digest = hashlib.sha1(
        "{}:{}".format(project_key, agent_id).encode("utf-8")
    ).hexdigest()
    return "ag_" + digest[:12]


@api.before_request
def _log_request_start():
    """Trace every OWIsMind API request (method + path) and start a timer.

    Blueprint-scoped, so it fires only for /owismind-api/* (not DSS health pings).
    """
    g._owi_t0 = time.time()
    logger.info("→ %s %s", request.method, request.path)


@api.after_request
def _log_request_end(response):
    """Trace the response status and wall-clock duration of each API request."""
    started = getattr(g, "_owi_t0", None)
    took_ms = (time.time() - started) * 1000.0 if started else -1.0
    logger.info(
        "← %s %s -> %s (%.0f ms)",
        request.method,
        request.path,
        response.status_code,
        took_ms,
    )
    return response


@api.route("/ping", methods=["GET"])
def ping():
    """Liveness health check. Intentionally minimal: it does NOT expose the storage
    configuration (connection name, project key, table names), since /ping is reachable
    without authentication. The resolved storage config is available to admins only via
    /admin/storage."""
    return jsonify({"status": "ok", "python": sys.version.split()[0]})


@api.route("/me", methods=["GET", "POST"])
def me():
    """Return the caller's identity, admin status and storage-config state.

    Identity is resolved server-side from the browser auth headers. The side effect -
    recording the caller in the users registry AND the first-admin bootstrap - happens
    ONLY on POST, so a naive prefetch/scanner GET can neither create a user row nor win
    the first-admin election (the operational rule "first to open = admin" must not be
    triggerable by a non-interactive GET). The frontend issues POST once on init; GET
    stays read-only. Both methods return the same shape.
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/me - identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    # --- BEGIN impersonation (temporary, removable) ---
    # Swap to the EFFECTIVE identity (the impersonated target when an admin carries the
    # header; otherwise the real caller). Downstream uses identity["user_id"] unchanged.
    identity = impersonation.effective_identity(identity)
    # --- END impersonation ---

    logger.info(
        "/me - %s user_id=%s groups=%s",
        request.method,
        identity["user_id"],
        identity["groups"],
    )

    # Resolve admin status (only once storage is configured). The registry WRITE
    # (upsert + first-admin bootstrap) is done on POST only; GET never mutates.
    configured = sql_config.is_configured()
    is_admin_flag = False
    if configured:
        try:
            # --- BEGIN impersonation (temporary, removable) ---
            # Do NOT record/bootstrap the impersonated user: the side effect must only
            # ever apply to a real, non-impersonated caller (a forged registry row /
            # first-admin election under someone else's id would be a bug).
            if request.method == "POST" and not identity.get("impersonating"):
                admin.record_user(identity)
            # --- END impersonation ---
            # is_admin reflects the EFFECTIVE user: while impersonating a normal user it
            # is False, so the admin UI correctly hides (exit is via the banner).
            is_admin_flag = admin.is_admin(identity["user_id"])
        except Exception:
            logger.exception("/me - user registry failed")

    return jsonify(
        {
            "status": "ok",
            "user_id": identity["user_id"],
            # Server-derived friendly default (e.g. "said.chaoui" -> "Said"); the
            # frontend already reads this key and falls back to the raw login if absent.
            "display_name": identity["display_name"],
            "groups": identity["groups"],
            "needs_config": not configured,
            "is_admin": is_admin_flag,
            # --- BEGIN impersonation (temporary, removable) ---
            # Expose the impersonation state so the frontend can show the banner + hide
            # write affordances; real_user_id is the admin actually driving the session.
            "impersonating": identity.get("impersonating", False),
            "real_user_id": identity.get("real_user_id"),
            # --- END impersonation ---
        }
    )


@api.route("/usage", methods=["GET"])
def usage_me():
    """The caller's own monthly budget status (spend, effective limit, remaining, reset).

    Powers the profile's consumption view and the chat budget banner. Strictly
    owner-scoped: the status is read for the auth-resolved user_id only, never a body
    value. Returns the resolved limit and its SOURCE (default / global temp boost /
    per-user override) so the UI can be fully transparent about why the cap is what it is.
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/usage - identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    # --- BEGIN impersonation (temporary, removable) ---
    # Read the EFFECTIVE user's usage (the impersonated target when an admin impersonates).
    identity = impersonation.effective_identity(identity)
    # --- END impersonation ---

    if not sql_config.is_configured():
        logger.warning("/usage - storage not configured")
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    # Per-user token bucket on this always-on read: the legitimate cadence (init + one
    # read per finished run + Settings open) fits easily; a scripted flood is denied so it
    # cannot pin the mono-process backend's threads / the shared SQL connection.
    if not evidence_throttle.usage_can_accept(identity["user_id"]):
        logger.warning("/usage - rate limited user_id=%s", identity["user_id"])
        return jsonify({"status": "error", "error": "rate_limited"}), 429

    try:
        status = budget.usage_status(identity["user_id"])
    except Exception:
        logger.exception("/usage - status read failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    logger.info(
        "/usage - user_id=%s spent=%.4f limit=%.4f source=%s blocked=%s",
        identity["user_id"], status.get("spent_usd"), status.get("limit_usd"),
        status.get("limit_source"), status.get("blocked"),
    )
    return jsonify({"status": "ok", "usage": status})


_SCREEN_TABS = ("evidence", "chart", "table")


def _sanitize_screen_context(raw):
    """Tiny bounded view of what the user is looking at: which exchange (the one
    rendered in the Evidence panel) and which tab. Untrusted input -> None unless it
    is a dict with the panel open; the exchange's artifacts are read OWNER-SCOPED in
    the worker, so a forged exchange_id can only ever reveal the caller's own data."""
    if not isinstance(raw, dict) or not raw.get("open"):
        return None
    exch = raw.get("exchange_id")
    if not isinstance(exch, (str, int)) or isinstance(exch, bool):
        return None
    tab = raw.get("active_tab")
    return {
        "open": True,
        "exchange_id": str(exch)[:128],
        "active_tab": tab if tab in _SCREEN_TABS else None,
    }


@api.route("/chat/start", methods=["POST"])
def chat_start():
    """Start a real agent run for one message in a background worker; return a run_id.

    The frontend sends only ``{session_id, message, agent_key}``; identity is
    resolved from the auth headers and ``agent_key`` is an OPAQUE logical key
    resolved server-side against the enabled-agents whitelist (a raw agent_id is
    never accepted). Phase one of the two-phase write happens here (before the run):
    the user message is persisted so the question is stored even if the run later
    fails. The agent itself runs in a background thread (agents/stream_manager); the
    front then polls /chat/poll for the live timeline. 503 ``busy`` if the global
    concurrent-run cap is reached.
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/chat/start - identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    # --- BEGIN impersonation (temporary, removable) ---
    # WRITE route: blocked while an admin impersonates (consultation only, no sending /
    # no budget spend under the user's name). Checked BEFORE any work / whitelist /
    # budget / persist. We block here rather than swap identity (we do not act as them).
    if impersonation.effective_identity(identity).get("impersonating"):
        logger.info("/chat/start - blocked while impersonating (read-only)")
        return jsonify({"status": "error", "error": "impersonation_read_only"}), 403
    # --- END impersonation ---

    try:
        session_id, message, agent_key = validate_chat_start_request(
            request.get_json(silent=True)
        )
    except ValidationError as exc:
        logger.warning("/chat/start - invalid payload: %s", exc.code)
        return jsonify({"status": "error", "error": exc.code}), 400

    # Optional agent-context window (number of prior messages to replay). Read and
    # bounded separately so validate_chat_start_request stays untouched; the value is
    # strictly clamped server-side to [10, 50] (default 20).
    body = request.get_json(silent=True) or {}
    history_limit = validate_history_limit(body.get("history_limit"))

    # Optional conversation-tree edge: the exchange this new turn branches from (NULL for
    # a first turn / root). Never raises - a malformed value degrades to None, and the
    # ancestor-chain read is always user-scoped, so a forged id can only ever match the
    # caller's own rows.
    parent_exchange_id = validate_optional_exchange_id(body.get("parent_exchange_id"))

    if not sql_config.is_configured():
        logger.warning("/chat/start - storage not configured")
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    # Whitelist enforcement: resolve the opaque logical key to a real, still-enabled
    # agent. A forged or stale key matches nothing -> rejected (never runs an agent).
    agent = settings.resolve_enabled_agent(agent_key)
    if not agent:
        logger.warning("/chat/start - agent_key not enabled: %s", agent_key)
        return jsonify({"status": "error", "error": "agent_not_enabled"}), 404
    project_key = agent["project_key"]
    agent_id = agent["agent_id"]

    # Never log message CONTENT (privacy / log hygiene): only its length. Every other
    # module deliberately keeps prompt/answer bodies out of the logs; this request entry
    # point - the one place a body could leak - stays content-free too.
    logger.info(
        "/chat/start - user_id=%s session_id=%s agent_key=%s msg_len=%d",
        identity["user_id"],
        session_id,
        agent_key,
        len(message),
    )

    # Admission pre-check BEFORE any write: reject at-capacity or too-frequent calls so a
    # rejected request never persists a row or does extra SQL work (the worker's hard cap
    # is still the real gate). 429 for the per-user rate gate, 503 for the global cap.
    ok, reason = stream_manager.can_accept(identity["user_id"])
    if not ok:
        logger.warning("/chat/start - rejected before write: %s", reason)
        return jsonify({"status": "error", "error": reason}), (
            429 if reason == "rate_limited" else 503
        )

    # Monthly budget gate (before any write): reject a run once the user has reached
    # their monthly credit. Fails OPEN on a storage error - delivering the answer matters
    # more than a perfectly-timed block, and the spend is still recorded afterwards, so
    # the next request is gated once the read recovers. 402 (Payment Required) carries the
    # current budget status so the front can show exactly what is left.
    try:
        within_budget, budget_status = budget.has_budget(identity["user_id"])
    except Exception:
        logger.exception("/chat/start - budget check failed (allowing the run)")
        within_budget = True
    if not within_budget:
        logger.info(
            "/chat/start - monthly quota exceeded user_id=%s spent=%.4f limit=%.4f",
            identity["user_id"],
            budget_status.get("spent_usd"),
            budget_status.get("limit_usd"),
        )
        return jsonify(
            {"status": "error", "error": "monthly_quota_exceeded", "budget": budget_status}
        ), 402

    # Phase one: persist the user message. Done in the request thread so a write
    # error surfaces as a clean HTTP error rather than inside the worker.
    try:
        ensure_chat_table()
        exchange_id = chat_v5.save_user_message(
            session_id, identity, message, agent_key, parent_exchange_id
        )
    except Exception:
        logger.exception("/chat/start - failed to persist user message")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    # Optional model mode (smart / pro / claude) chosen in the web app. Unknown or
    # absent -> smart (the recommended default). Relayed to the orchestrator via
    # the per-turn suffix token; it never picks a raw model id from the front.
    mode = body.get("mode")
    if mode not in context.MODEL_MODES:
        mode = "smart"
    # Per-agent gate (the real enforcement behind the hidden picker): only relay the
    # mode control token to an agent that actually supports the response-mode dial
    # (its admin profile opted in). For any other agent the orchestrator-only token
    # would just leak into the prompt as visible text, so drop it entirely - the agent
    # then runs with no mode token, exactly as before this feature existed.
    agent_profile = agent.get("profile") if isinstance(agent.get("profile"), dict) else {}
    if not agent_profile.get("modes"):
        mode = None

    # Web-app configured language (fr / en) the user is currently running the UI in.
    # Validated like the mode; absent/unknown -> None. The reply language of THIS turn
    # is detected from the RAW message HERE (clean, before the date stamp would pollute
    # the heuristic), with the web-app language as the tie-break for a neutral message.
    webapp_lang = body.get("webapp_lang")
    if webapp_lang not in context._LANG_LABEL:
        webapp_lang = None
    prompt_lang = context.detect_prompt_language(message, default=webapp_lang or "fr")

    # Per-turn context block (who is asking + server-side date + web-app language + the
    # "answer in THIS message's language" rule) APPENDED to the END of the current user
    # message - the agent is stateless between calls and honors end-of-prompt best.
    user_suffix = context.build_user_suffix(
        derive_full_name(identity["user_id"]), datetime.now(),
        webapp_lang=webapp_lang, prompt_lang=prompt_lang, mode=mode,
    )

    # Optional screen-awareness pointer (the exchange + tab the user is currently
    # viewing in the Evidence panel). Sanitized to a tiny bounded dict; the worker
    # reads that exchange's artifacts OWNER-SCOPED, so a forged id reveals nothing.
    screen_context = _sanitize_screen_context(body.get("screen_context"))

    # Spawn the bounded background worker. The agent_id stays server-side; the front
    # only ever receives the opaque run_id.
    try:
        run_id = stream_manager.start_run(
            project_key, agent_id, message, exchange_id,
            identity["user_id"], parent_exchange_id, history_limit, user_suffix,
            screen_context=screen_context,
        )
    except stream_manager.CapacityError:
        logger.warning("/chat/start - concurrency cap reached, rejected")
        return jsonify({"status": "error", "error": "busy"}), 503
    except Exception:
        logger.exception("/chat/start - failed to start agent run")
        return jsonify({"status": "error", "error": "agent_unavailable"}), 500

    return jsonify({"status": "ok", "run_id": run_id, "exchange_id": exchange_id})


@api.route("/chat/poll", methods=["GET"])
def chat_poll():
    """Return the run's normalised events since ``cursor`` (live timeline polling).

    Query params: ``run_id`` (the opaque id from /chat/start) and ``cursor`` (the
    number of events already consumed, default 0). Returns
    ``{events, cursor, done, error}``: ``events`` are the new normalised events
    (run_started / agent_event / answer_delta / generated_sql / usage_summary /
    final_answer / run_done / error), ``cursor`` is the next cursor to send back,
    ``done`` signals the run finished. The run is scoped to its owner: a run_id that
    is unknown or owned by another user yields 404 (without revealing which).
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/chat/poll - identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    run_id = request.args.get("run_id", "")
    if not run_id or len(run_id) > _MAX_RUN_ID_LENGTH:
        return jsonify({"status": "error", "error": "invalid_run_id"}), 400
    try:
        cursor = int(request.args.get("cursor", 0))
    except (TypeError, ValueError):
        cursor = 0
    if cursor < 0:
        cursor = 0

    result = stream_manager.poll(run_id, identity["user_id"], cursor)
    if result is None:
        return jsonify({"status": "error", "error": "run_not_found"}), 404

    return jsonify({"status": "ok", **result})


@api.route("/chat/stop", methods=["POST"])
def chat_stop():
    """Request a cooperative early stop of one of the caller's own in-flight runs.

    Body: ``{run_id}`` (the opaque id from /chat/start). The worker sees the request
    between two streamed chunks, stops iterating the LLM Mesh stream (which exposes no
    cancel API), persists whatever PARTIAL answer accumulated, and ends the run with a
    terminal ``stopped`` event (not an error). Owner-scoped: a run_id that is unknown,
    already finished/evicted, or owned by another user yields 404 (without revealing
    which) - a safe no-op the client treats as "already done". Identity comes from the
    auth headers, never the body.
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/chat/stop - identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    # --- BEGIN impersonation (temporary, removable) ---
    # WRITE route: blocked while impersonating (read-only consultation). An admin cannot
    # stop a run under the inspected user's name; checked before any work.
    if impersonation.effective_identity(identity).get("impersonating"):
        logger.info("/chat/stop - blocked while impersonating (read-only)")
        return jsonify({"status": "error", "error": "impersonation_read_only"}), 403
    # --- END impersonation ---

    payload = request.get_json(silent=True) or {}
    run_id = payload.get("run_id") or ""
    if not isinstance(run_id, str) or not run_id or len(run_id) > _MAX_RUN_ID_LENGTH:
        return jsonify({"status": "error", "error": "invalid_run_id"}), 400

    if not stream_manager.request_stop(run_id, identity["user_id"]):
        return jsonify({"status": "error", "error": "run_not_found"}), 404

    logger.info("/chat/stop - run_id=%s user_id=%s", run_id, identity["user_id"])
    return jsonify({"status": "ok"})


@api.route("/chat/feedback", methods=["POST"])
def chat_feedback():
    """Persist 👍/👎 feedback (+ reasons + comment) on one of the caller's own messages.

    Identity comes from the auth headers (never the body); the UPDATE in
    ``chat_v5.save_feedback`` is owner-scoped (WHERE exchange_id AND user_id), so a
    caller can only rate their own exchange - an exchange owned by someone else is a
    silent no-op. The payload is validated/bounded server-side (rating 0/1/None,
    whitelisted reasons, bounded comment).
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/chat/feedback - identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    # --- BEGIN impersonation (temporary, removable) ---
    # WRITE route: blocked while impersonating (read-only consultation). An admin cannot
    # rate a message under the inspected user's name; checked before any work.
    if impersonation.effective_identity(identity).get("impersonating"):
        logger.info("/chat/feedback - blocked while impersonating (read-only)")
        return jsonify({"status": "error", "error": "impersonation_read_only"}), 403
    # --- END impersonation ---

    if not sql_config.is_configured():
        logger.warning("/chat/feedback - storage not configured")
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    try:
        exchange_id, rating, reasons, comment = validate_feedback(
            request.get_json(silent=True)
        )
    except ValidationError as exc:
        logger.warning("/chat/feedback - invalid payload: %s", exc.code)
        return jsonify({"status": "error", "error": exc.code}), 400

    try:
        ensure_chat_table()
        chat_v5.save_feedback(
            identity["user_id"], exchange_id, rating, reasons, comment
        )
    except Exception:
        logger.exception("/chat/feedback - feedback save failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    logger.info(
        "/chat/feedback - user_id=%s exchange_id=%s rating=%s",
        identity["user_id"],
        exchange_id,
        rating,
    )
    return jsonify({"status": "ok"})


@api.route("/conversations", methods=["GET"])
def conversations():
    """Names-only, keyset-paginated conversation list for the signed-in user.

    Powers the lazy sidebar: one page of conversation summaries (session_id, title,
    last_at) - never message bodies. ``cursor`` resumes a previous page; ``limit`` is
    clamped server-side to [1, 60] (default 30). Strictly owner-scoped.
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/conversations - identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    # --- BEGIN impersonation (temporary, removable) ---
    # List the EFFECTIVE user's conversations (the impersonated target for an admin).
    identity = impersonation.effective_identity(identity)
    # --- END impersonation ---

    if not sql_config.is_configured():
        logger.warning("/conversations - storage not configured")
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    limit = validate_conversations_limit(request.args.get("limit"))
    # Bound the opaque cursor before it reaches decode_cursor (defensive: a real
    # base64 cursor for iso(~32) + sep + uuid(36) is well under 128 chars; 512 is
    # generous). Mirrors the run_id (<=64) / session_id (<=128) length guards.
    cursor_token = (request.args.get("cursor") or "").strip() or None
    if cursor_token and len(cursor_token) > 512:
        return jsonify({"status": "error", "error": "invalid_cursor"}), 400
    try:
        ensure_chat_table()
        page = chat_v5.list_conversations(identity["user_id"], cursor_token, limit)
    except Exception:
        logger.exception("/conversations - listing failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    logger.info(
        "/conversations - user_id=%s limit=%d returned %d (has_more=%s)",
        identity["user_id"],
        limit,
        len(page.get("conversations", [])),
        page.get("has_more"),
    )
    return jsonify({"status": "ok", **page})


@api.route("/conversation", methods=["GET"])
def conversation():
    """All messages of ONE session (the user's own), chronological, bounded.

    Fetched lazily when the user clicks a conversation in the sidebar. The session
    is strictly owner-scoped (a session_id owned by another user yields no rows), and
    the read is bounded by an absolute row cap. Rows are shaped like the conversation
    readback (`chat_v5._COLUMNS`), so the frontend reuses one row->message mapper.
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/conversation - identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    # --- BEGIN impersonation (temporary, removable) ---
    # Load the EFFECTIVE user's session (the impersonated target for an admin).
    identity = impersonation.effective_identity(identity)
    # --- END impersonation ---

    if not sql_config.is_configured():
        logger.warning("/conversation - storage not configured")
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    session_id = (request.args.get("session_id") or "").strip()
    if not session_id or len(session_id) > MAX_SESSION_ID_LENGTH:
        return jsonify({"status": "error", "error": "invalid_session_id"}), 400

    try:
        ensure_chat_table()
        rows = chat_v5.messages_for_session(identity["user_id"], session_id)
    except Exception:
        logger.exception("/conversation - load failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    logger.info(
        "/conversation - user_id=%s session_id=%s returned %d rows",
        identity["user_id"],
        session_id,
        len(rows),
    )
    return jsonify(
        {"status": "ok", "session_id": session_id, "count": len(rows), "rows": rows}
    )


@api.route("/agents", methods=["GET"])
def agents_available():
    """List the agents the admin has enabled, for any authenticated caller.

    This powers the chat-side agent picker. It returns ONLY each agent's opaque
    logical key and human label - never a raw agent_id or project key - so the
    chat front references an agent solely by its logical key (server whitelist).
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/agents - identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    if not sql_config.is_configured():
        logger.warning("/agents - storage not configured")
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    try:
        enabled = settings.get_enabled_agents()
    except Exception:
        logger.exception("/agents - query failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    # Project off only the public-safe fields (no agent_id / project_key leak). The
    # admin-authored PROFILE (tagline / description / capabilities / tools / icon /
    # badge) is display copy written by an administrator - safe to expose, and the
    # source of the agent-library cards (no hardcoded descriptions client-side).
    public = []
    for a in enabled:
        key = a.get("logical_key")
        if not key:
            continue
        profile = a.get("profile") if isinstance(a.get("profile"), dict) else {}
        public.append(
            {
                "key": key,
                "label": a.get("label"),
                "tagline": profile.get("tagline", ""),
                "description": profile.get("description", ""),
                "capabilities": profile.get("capabilities", []),
                "tools": profile.get("tools", []),
                "icon": profile.get("icon", "robot"),
                "badge": profile.get("badge", ""),
                # Whether the chat should offer the response-mode dial (Smart / Pro /
                # Claude) for this agent. Only agents whose backend understands the
                # ⟦owi:mode=…⟧ token (the orchestrator) set this; the picker is hidden
                # otherwise. Default off so a plain visual agent never shows it.
                "modes": bool(profile.get("modes", False)),
                # Whether this agent has a benchmark the consultation can show. ONLY the boolean
                # is exposed (never the table / connection / project): the table is resolved
                # server-side from the admin profile when the results are read.
                "has_benchmark": bool(
                    isinstance(profile.get("benchmark"), dict)
                    and profile["benchmark"].get("enabled")
                    and profile["benchmark"].get("table")
                ),
            }
        )
    logger.info(
        "/agents - user_id=%s returned %d enabled agent(s)",
        identity["user_id"],
        len(public),
    )
    return jsonify({"status": "ok", "count": len(public), "agents": public})


# --- Evidence Studio (owner-scoped, read-only, auto-discovered project datasets) ----


def _evidence_guard():
    """Resolve identity + require configured storage (shared by /evidence/*).

    Returns ``(identity, None)`` or ``(None, (response, status))``.

    Also bootstraps the chat table like the other chat-table readers do, so on a
    configured-but-virgin instance an unknown/forged exchange_id yields the same
    owner-scoped 404 as everywhere else (not a distinguishable 500).
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/evidence - identity resolution failed: %s", exc)
        return None, (jsonify({"status": "error", "error": "unauthenticated"}), 401)
    # --- BEGIN impersonation (temporary, removable) ---
    # Evidence reads scope to the EFFECTIVE user (the impersonated target for an admin),
    # so an admin sees exactly the SQL / charts / tables the inspected user sees.
    identity = impersonation.effective_identity(identity)
    # --- END impersonation ---
    if not sql_config.is_configured():
        logger.warning("/evidence - storage not configured")
        return None, (jsonify({"status": "error", "error": "storage_not_configured"}), 409)
    try:
        ensure_chat_table()
    except Exception:
        logger.exception("/evidence - chat table bootstrap failed")
        return None, (jsonify({"status": "error", "error": "storage_unavailable"}), 500)
    # Per-user token-bucket gate: a scripted flood must not pin worker threads of the
    # mono-process polling backend (the legitimate auto-open meta+rows pair fits well
    # within the burst capacity). Checked after the cheap auth/config/bootstrap path.
    if not evidence_throttle.can_accept(identity["user_id"]):
        logger.warning("/evidence - rate limited user_id=%s", identity["user_id"])
        return None, (jsonify({"status": "error", "error": "rate_limited"}), 429)
    return identity, None


@api.route("/evidence/meta", methods=["GET"])
def evidence_meta():
    """Interactive descriptor of one exchange's evidence (or a degraded shape).

    The caller sends ONLY ``exchange_id``: table, connection, SQL and dataset
    matching are all resolved server-side. Owner-scoped - someone else's
    exchange is 404.
    """
    identity, err = _evidence_guard()
    if err:
        return err
    try:
        exchange_id = validate_required_exchange_id(request.args.get("exchange_id"))
    except ValidationError as exc:
        logger.warning("/evidence/meta - invalid exchange_id")
        return jsonify({"status": "error", "error": exc.code}), 400
    try:
        meta = evidence_service.evidence_meta(identity["user_id"], exchange_id)
    except evidence_service.EvidenceError as exc:
        return jsonify({"status": "error", "error": exc.code}), exc.status
    except Exception:
        logger.exception("/evidence/meta - failed")
        return jsonify({"status": "error", "error": "evidence_unavailable"}), 500
    # One observability line per meta: the verification outcome is the trust
    # layer's whole point, so it must be greppable next to available/reason.
    verification = meta.get("verification") or {}
    drilldown = meta.get("drilldown") or {}
    # Attach this exchange's rendered-artifact specs (chart / table the orchestrator
    # asked for). Owner-scoped, best-effort: a read failure degrades to no artifacts,
    # never a 500 - the rest of the evidence panel stays usable.
    try:
        arts = artifacts_storage.read_artifacts(identity["user_id"], exchange_id)
        # Server-side chart shaping: build the Chart.js-ready {labels, datasets}
        # for each chart artifact from the captured result, so the agent only
        # had to pick x / y / type. Pure + bounded; an unbuildable chart yields
        # an honest {ok: false} the frontend renders as an empty state.
        result_block = meta.get("result")
        for a in arts:
            if a.get("kind") == "chart":
                a["data"] = chart_payload.build_chart_payload(result_block, a.get("chart"))
            elif a.get("kind") == "kpi":
                a["data"] = chart_payload.build_kpi_payload(result_block, a.get("kpi"))
        meta["artifacts"] = arts
    except Exception:
        logger.exception("/evidence/meta - artifacts read failed (non-fatal)")
        meta["artifacts"] = []
    logger.info(
        "/evidence/meta - user_id=%s exchange_id=%s available=%s reason=%s "
        "level=%s result_captured=%s drill_available=%s artifacts=%d",
        identity["user_id"], exchange_id, meta.get("available"), meta.get("reason"),
        verification.get("level"), verification.get("result_captured"),
        drilldown.get("available"), len(meta.get("artifacts") or []),
    )
    return jsonify({"status": "ok", **meta})


@api.route("/evidence/rows", methods=["POST"])
def evidence_rows():
    """One bounded page of the evidence table, rebuilt from STRUCTURED filters.

    The body never carries SQL: editable chips travel as {column, op, values},
    locked chips as kept ids (re-derived server-side from the stored SQL), and
    the optional ``drill`` labels are matched server-side against group keys
    re-derived from the stored SQL (the client never picks a drill column set).
    """
    identity, err = _evidence_guard()
    if err:
        return err
    try:
        (exchange_id, filters, kept_ids, include_advanced, page, sort, drill,
         table) = validate_evidence_rows_request(request.get_json(silent=True))
    except ValidationError as exc:
        logger.warning("/evidence/rows - invalid payload: %s", exc.code)
        return jsonify({"status": "error", "error": exc.code}), 400
    try:
        result = evidence_service.evidence_rows(
            identity["user_id"], exchange_id, filters, kept_ids,
            include_advanced, page, sort, drill, table,
        )
    except evidence_service.EvidenceError as exc:
        return jsonify({"status": "error", "error": exc.code}), exc.status
    except Exception:
        logger.exception("/evidence/rows - failed")
        return jsonify({"status": "error", "error": "evidence_unavailable"}), 500
    return jsonify({"status": "ok", **result})


@api.route("/evidence/distinct", methods=["GET"])
def evidence_distinct():
    """Bounded distinct values of ONE column (the filter-chip picker).

    ``exclude_id`` (optional, int) is the server id of the chip being edited:
    its own predicate must not scope its own picker. Malformed values degrade
    to None (the picker is then simply scoped by every locked predicate).
    """
    identity, err = _evidence_guard()
    if err:
        return err
    try:
        exchange_id = validate_required_exchange_id(request.args.get("exchange_id"))
        column = validate_evidence_column(request.args.get("column"))
    except ValidationError as exc:
        logger.warning("/evidence/distinct - invalid payload: %s", exc.code)
        return jsonify({"status": "error", "error": exc.code}), 400
    raw_exclude = request.args.get("exclude_id")
    try:
        exclude_id = int(raw_exclude) if raw_exclude is not None else None
        if exclude_id is not None and exclude_id < 0:
            exclude_id = None
    except (TypeError, ValueError, OverflowError):
        exclude_id = None
    try:
        result = evidence_service.evidence_distinct(
            identity["user_id"], exchange_id, column, exclude_id,
        )
    except evidence_service.EvidenceError as exc:
        return jsonify({"status": "error", "error": exc.code}), exc.status
    except Exception:
        logger.exception("/evidence/distinct - failed")
        return jsonify({"status": "error", "error": "evidence_unavailable"}), 500
    return jsonify({"status": "ok", **result})


# --- benchmark suggestions (the collaborative golden-set intake) -------------
# Any signed-in user proposes a benchmark question + the answer they vouch for. The
# proposal is stored owner-stamped in webapp_golden_suggestions_v1; the admin pole (the
# OWIsMind_LAB benchmark webapp) later reads it cross-project and promotes accepted rows
# into the golden dataset. The two WRITE routes are blocked while impersonating (read-only),
# mirroring /chat/feedback; the "my suggestions" read scopes to the effective user.


@api.route("/benchmark/suggest", methods=["POST"])
def benchmark_suggest():
    """Persist a standalone (manual) benchmark suggestion from the caller.

    Body: ``{question, reference_answer, expected_value?, expected_value_type?, category?,
    language?}``. Validated/bounded server-side; identity comes from the auth headers; the row
    is owner-stamped. Returns ``{status:'ok', suggestion_id}``.
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/benchmark/suggest - identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    # --- BEGIN impersonation (temporary, removable) ---
    # WRITE route: blocked while impersonating (read-only consultation). An admin cannot
    # submit a suggestion under the inspected user's name; checked before any work.
    if impersonation.effective_identity(identity).get("impersonating"):
        logger.info("/benchmark/suggest - blocked while impersonating (read-only)")
        return jsonify({"status": "error", "error": "impersonation_read_only"}), 403
    # --- END impersonation ---

    if not sql_config.is_configured():
        logger.warning("/benchmark/suggest - storage not configured")
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    try:
        fields = validate_suggestion_manual(request.get_json(silent=True))
    except ValidationError as exc:
        logger.warning("/benchmark/suggest - invalid payload: %s", exc.code)
        return jsonify({"status": "error", "error": exc.code}), 400

    try:
        suggestion_id = suggestions_storage.save_suggestion(
            identity["user_id"], "manual",
            fields["question"], fields["reference_answer"],
            expected_value=fields["expected_value"],
            expected_value_type=fields["expected_value_type"],
            category=fields["category"], language=fields["language"],
        )
    except Exception:
        logger.exception("/benchmark/suggest - save failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    logger.info(
        "/benchmark/suggest - user_id=%s suggestion_id=%s (manual)",
        identity["user_id"], suggestion_id,
    )
    return jsonify({"status": "ok", "suggestion_id": suggestion_id})


@api.route("/benchmark/suggest-from-chat", methods=["POST"])
def benchmark_suggest_from_chat():
    """Persist a benchmark suggestion built from one of the caller's own chat answers.

    Body: ``{exchange_id, answer_is_correct, reference_answer?, missing_explanation?,
    category?}``. The question, agent answer, agent_key and generated SQL are reconstructed
    from the PERSISTED exchange server-side (owner-scoped), never trusted from the client. A
    "Yes" verdict stores the agent answer as the reference (a positive example); a "No"
    verdict requires the correct answer. Returns ``{status:'ok', suggestion_id}``.
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/benchmark/suggest-from-chat - identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    # --- BEGIN impersonation (temporary, removable) ---
    if impersonation.effective_identity(identity).get("impersonating"):
        logger.info("/benchmark/suggest-from-chat - blocked while impersonating (read-only)")
        return jsonify({"status": "error", "error": "impersonation_read_only"}), 403
    # --- END impersonation ---

    if not sql_config.is_configured():
        logger.warning("/benchmark/suggest-from-chat - storage not configured")
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    try:
        fields = validate_suggestion_from_chat(request.get_json(silent=True))
    except ValidationError as exc:
        logger.warning("/benchmark/suggest-from-chat - invalid payload: %s", exc.code)
        return jsonify({"status": "error", "error": exc.code}), 400

    # Reconstruct the authoritative Q/A from the persisted exchange (owner-scoped). A forged
    # or someone-else's exchange returns None -> 404 (without revealing which).
    try:
        ensure_chat_table()
        exchange = chat_v5.read_exchange(identity["user_id"], fields["exchange_id"])
    except Exception:
        logger.exception("/benchmark/suggest-from-chat - exchange read failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500
    if not exchange:
        return jsonify({"status": "error", "error": "exchange_not_found"}), 404

    agent_answer = exchange.get("assistant_text")
    # A "Yes" verdict vouches for the agent answer itself; a "No" verdict carries the
    # correction the user supplied. Either way the reference is what the golden set will hold.
    reference = fields["reference_answer"]
    if fields["answer_is_correct"] and not reference:
        reference = agent_answer
    # A "Yes" on an exchange with no stored answer (early-stopped / never-answered) would
    # persist a reference-less, un-promotable suggestion (dead data the reviewer can never
    # vouch for). Reject it cleanly instead of storing it.
    if fields["answer_is_correct"] and not (reference and reference.strip()):
        return jsonify({"status": "error", "error": "empty_agent_answer"}), 400
    sql_items = exchange.get("generated_sql")
    sql_json = json.dumps(sql_items) if sql_items else None

    try:
        suggestion_id = suggestions_storage.save_suggestion(
            identity["user_id"], "chat",
            exchange.get("user_text"), reference,
            exchange_id=fields["exchange_id"],
            session_id=exchange.get("session_id"),
            agent_key=exchange.get("agent_key"),
            agent_answer=agent_answer,
            answer_is_correct=fields["answer_is_correct"],
            missing_explanation=fields["missing_explanation"],
            category=fields["category"],
            generated_sql_json=sql_json,
        )
    except Exception:
        logger.exception("/benchmark/suggest-from-chat - save failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    logger.info(
        "/benchmark/suggest-from-chat - user_id=%s exchange_id=%s correct=%s suggestion_id=%s",
        identity["user_id"], fields["exchange_id"], fields["answer_is_correct"], suggestion_id,
    )
    return jsonify({"status": "ok", "suggestion_id": suggestion_id})


@api.route("/benchmark/suggestions", methods=["GET"])
def benchmark_my_suggestions():
    """List the caller's OWN benchmark suggestions (newest first, owner-scoped + bounded)."""
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/benchmark/suggestions - identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    # --- BEGIN impersonation (temporary, removable) ---
    # READ route: list the EFFECTIVE user's suggestions (the impersonated target for an admin).
    identity = impersonation.effective_identity(identity)
    # --- END impersonation ---

    if not sql_config.is_configured():
        logger.warning("/benchmark/suggestions - storage not configured")
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    suggestions = suggestions_storage.list_my_suggestions(identity["user_id"])
    logger.info(
        "/benchmark/suggestions - user_id=%s returned %d",
        identity["user_id"], len(suggestions),
    )
    return jsonify({"status": "ok", "count": len(suggestions), "suggestions": suggestions})


# --- benchmark consultation (any signed-in user) + admin review/override -----

def _benchmark_block_for_key(agent_key):
    """Resolve an opaque agent logical key to its admin-configured benchmark block, or None.

    The end user only ever sends the opaque key; the table / connection are NEVER accepted from
    the client - they are read here from the server-side enabled-agents whitelist. Returns the
    validated block ({enabled, connection, table, agent_key}) only when it is usable.
    """
    if not agent_key or not isinstance(agent_key, str):
        return None
    agent = settings.resolve_enabled_agent(agent_key)
    if not agent:
        return None
    profile = agent.get("profile") if isinstance(agent.get("profile"), dict) else {}
    block = bench_profile.validate_benchmark_block(profile.get("benchmark"))
    return block if bench_profile.is_configured(block) else None


@api.route("/benchmark/results", methods=["GET"])
def benchmark_results():
    """Consult one agent's benchmark results (any signed-in user). Read-only, bounded.

    ``agent`` is the opaque logical key (resolved server-side to the admin-set table); ``run_id``
    selects the run (latest by default). Returns the consultation view-model (verdict, KPIs, per
    agent x mode, per category, per-question detail) recomputed on the EFFECTIVE verdict.
    """
    try:
        resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/benchmark/results - identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401
    if not sql_config.is_configured():
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    agent_key = request.args.get("agent")
    block = _benchmark_block_for_key(agent_key)
    if block is None:
        return jsonify({"status": "ok", "configured": False,
                        "results": bench_aggregate.results_view([], run_id=None)})

    rows, err = bench_io.read_scored(block)
    if err:
        logger.warning("/benchmark/results - read failed (%s) agent=%s", err, agent_key)
        return jsonify({"status": "ok", "configured": True, "read_error": err,
                        "results": bench_aggregate.results_view([], run_id=None)})
    run_id = request.args.get("run_id") or None
    results = bench_aggregate.results_view(rows, run_id=run_id)
    return jsonify({"status": "ok", "configured": True, "results": results})


@api.route("/admin/benchmark/tables", methods=["GET"])
def admin_benchmark_tables():
    """List the public tables on a SQL connection, for the agent-profile table picker (admin)."""
    _identity, err = _admin_guard()
    if err:
        return err
    connection = request.args.get("connection") or bench_profile.DEFAULT_CONNECTION
    tables, read_err = bench_io.list_tables(connection)
    if read_err:
        return jsonify({"status": "ok", "tables": [], "error": read_err})
    return jsonify({"status": "ok", "tables": tables})


@api.route("/admin/benchmark/validate-table", methods=["POST"])
def admin_benchmark_validate_table():
    """Check a candidate table has the columns the consultation needs (admin). Reports missing ones."""
    _identity, err = _admin_guard()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    connection = body.get("connection") or bench_profile.DEFAULT_CONNECTION
    table = bench_profile.validate_benchmark_block(
        {"enabled": True, "connection": connection, "table": body.get("table")}
    )["table"]
    if not table:
        return jsonify({"status": "ok", "ok": False, "error": "bad_table",
                        "missing": list(bench_schema.REQUIRED_COLUMNS)})
    cols, read_err = bench_io.table_columns(connection, table)
    if read_err:
        return jsonify({"status": "ok", "ok": False, "error": read_err})
    return jsonify({"status": "ok", **bench_schema.check_columns(cols)})


@api.route("/admin/benchmark/override", methods=["POST"])
def admin_benchmark_override():
    """Override (or clear) the judge verdict on one scored row (admin, human-in-the-loop).

    Resolves the agent's benchmark table server-side from the opaque key, validates the override,
    and writes the human_* columns via a bounded parametrized UPDATE (lab_io.write_override).
    """
    identity, err = _admin_guard()
    if err:
        return err
    # --- BEGIN impersonation (temporary, removable) ---
    # WRITE route: an admin acting as another user is read-only; block the override write.
    if impersonation.effective_identity(identity).get("impersonating"):
        return jsonify({"status": "error", "error": "impersonation_read_only"}), 403
    # --- END impersonation ---

    body = request.get_json(silent=True) or {}
    block = _benchmark_block_for_key(body.get("agent"))
    if block is None:
        return jsonify({"status": "error", "error": "agent_has_no_benchmark"}), 400
    ok, errors = bench_aggregate.validate_override(body)
    if not ok:
        return jsonify({"status": "error", "error": "invalid_override", "messages": errors}), 400
    reviewed_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    result, write_err = bench_io.write_override(block, body, identity["user_id"], reviewed_at)
    if write_err:
        logger.warning("/admin/benchmark/override - write failed (%s)", write_err)
        return jsonify({"status": "error", "error": write_err}), 500
    logger.info("/admin/benchmark/override - by=%s agent=%s q=%s verdict=%s",
                identity["user_id"], body.get("agent"), body.get("question_id"),
                body.get("verdict"))
    return jsonify({"status": "ok", **(result or {})})


# --- admin space (server-gated; visible in the UI only to admins) ------------


def _admin_guard():
    """Resolve identity and require configured storage + admin rights.

    Returns ``(identity, None)`` when allowed, or ``(None, (response, status))``
    to short-circuit: 401 unauthenticated, 409 not configured, 403 not admin.
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError:
        return None, (jsonify({"status": "error", "error": "unauthenticated"}), 401)
    if not sql_config.is_configured():
        return None, (jsonify({"status": "error", "error": "storage_not_configured"}), 409)
    try:
        if not admin.is_admin(identity["user_id"]):
            return None, (jsonify({"status": "error", "error": "forbidden"}), 403)
    except Exception:
        logger.exception("admin guard - admin check failed")
        return None, (jsonify({"status": "error", "error": "storage_unavailable"}), 500)
    return identity, None


@api.route("/admin/storage", methods=["GET"])
def admin_storage_get():
    """Resolved storage config (connection, prefix, computed table names)."""
    _identity, err = _admin_guard()
    if err:
        return err
    return jsonify({"status": "ok", "storage": sql_config.storage_status()})


@api.route("/admin/users", methods=["GET"])
def admin_users():
    """List every user who has opened the webapp (with their admin flag)."""
    _identity, err = _admin_guard()
    if err:
        return err
    try:
        users = admin.list_users()
    except Exception:
        logger.exception("admin/users - query failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500
    return jsonify({"status": "ok", "count": len(users), "users": users})


@api.route("/admin/users/set-admin", methods=["POST"])
def admin_set_admin():
    """Set or clear a user's admin flag (never below one remaining admin)."""
    _identity, err = _admin_guard()
    if err:
        return err
    body = request.get_json(silent=True) or {}
    target = body.get("user_id")
    value = bool(body.get("is_admin"))
    if not target or not str(target).strip():
        return jsonify({"status": "error", "error": "missing_user_id"}), 400
    target = str(target).strip()
    try:
        # Guard against locking everyone out: never clear the last remaining admin.
        if not value and admin.is_admin(target) and admin.count_admins() <= 1:
            return jsonify({"status": "error", "error": "cannot_remove_last_admin"}), 400
        admin.set_admin(target, value)
        users = admin.list_users()
    except Exception:
        logger.exception("admin/users/set-admin failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500
    return jsonify({"status": "ok", "users": users})


# --- admin: monthly budgets / quotas -----------------------------------------


@api.route("/admin/budget", methods=["GET", "POST"])
def admin_budget():
    """Get or set the monthly budget config + per-user usage overview.

    GET returns ``{config, period_start, next_reset, users:[...]}`` - the global config
    (default limit, enforcement switch, any global temp boost) and every registered user's
    current-month spend + resolved effective limit. POST persists ``{limit_usd, enabled}``
    (always) and handles the temp boost independently so editing the default never disturbs
    an active boost: ``clear_temp:true`` removes it; ``temp_limit_usd`` + ``temp_days`` arms
    a fresh one; neither (the plain default-limit save) PRESERVES the existing boost. POST
    returns the refreshed overview so the UI updates in one round-trip.
    """
    identity, err = _admin_guard()
    if err:
        return err

    if request.method == "GET":
        try:
            return jsonify({"status": "ok", **budget.admin_overview()})
        except Exception:
            logger.exception("admin/budget - GET failed")
            return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    body = request.get_json(silent=True) or {}
    clear_temp = bool(body.get("clear_temp"))
    try:
        limit_usd = validate_budget_amount(body.get("limit_usd"))
        enabled = bool(body.get("enabled", True))
        # Temp boost is independent of the default-limit save: an explicit clear, a fresh
        # arm (amount + duration both required), or - when no temp field is sent - PRESERVE
        # whatever boost is already active (so a default-limit edit never clears it).
        temp_limit, temp_days, preserve_temp = None, None, False
        raw_temp = body.get("temp_limit_usd")
        if clear_temp:
            pass
        elif raw_temp is None or raw_temp == "":
            preserve_temp = True
        else:
            temp_limit = validate_budget_amount(raw_temp)
            temp_days = validate_expires_days(body.get("temp_days"))
            if temp_days is None:
                raise ValidationError("invalid_expires")
    except ValidationError as exc:
        logger.warning("admin/budget - invalid payload: %s", exc.code)
        return jsonify({"status": "error", "error": exc.code}), 400

    try:
        budget.set_budget_config(
            limit_usd, enabled, temp_limit, temp_days,
            clear_temp=clear_temp, preserve_temp=preserve_temp,
            updated_by=identity["user_id"],
        )
        overview = budget.admin_overview()
    except Exception:
        logger.exception("admin/budget - POST failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500
    logger.info("admin/budget - config saved by %s", identity["user_id"])
    return jsonify({"status": "ok", **overview})


@api.route("/admin/budget/users", methods=["POST"])
def admin_budget_users():
    """Set or clear a PER-USER monthly limit override for one, several or all users.

    Body: ``{user_ids:[...], clear:bool, limit_usd, expires_days, note}``. ``clear:true``
    removes the override(s) (revert to the global limit). Otherwise an override is upserted
    with ``limit_usd`` (required) and an optional ``expires_days`` (absent = permanent,
    an int = a temporary boost). The user_ids list is bounded; everything is re-validated
    server-side. Returns the refreshed overview.
    """
    identity, err = _admin_guard()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    clear = bool(body.get("clear"))
    try:
        user_ids = validate_user_id_list(body.get("user_ids"))
        if not clear:
            limit_usd = validate_budget_amount(body.get("limit_usd"))
            expires_days = validate_expires_days(body.get("expires_days"))
            note = validate_quota_note(body.get("note"))
    except ValidationError as exc:
        logger.warning("admin/budget/users - invalid payload: %s", exc.code)
        return jsonify({"status": "error", "error": exc.code}), 400

    try:
        if clear:
            budget.clear_user_quotas(user_ids, updated_by=identity["user_id"])
        else:
            budget.set_user_quotas(
                user_ids, limit_usd, expires_days, note, updated_by=identity["user_id"]
            )
        overview = budget.admin_overview()
    except Exception:
        logger.exception("admin/budget/users - failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500
    logger.info(
        "admin/budget/users - %s %d user(s) by %s",
        "cleared" if clear else "set", len(user_ids), identity["user_id"],
    )
    return jsonify({"status": "ok", **overview})


# --- admin: agent whitelist configuration ------------------------------------


@api.route("/admin/projects", methods=["GET"])
def admin_projects():
    """List the DSS project keys this webapp's identity can see (read-only)."""
    _identity, err = _admin_guard()
    if err:
        return err
    try:
        projects = discovery.list_project_keys()
    except Exception:
        logger.exception("admin/projects - discovery failed")
        return jsonify({"status": "error", "error": "discovery_unavailable"}), 500
    return jsonify({"status": "ok", "count": len(projects), "projects": projects})


@api.route("/admin/projects/<project_key>/agents", methods=["GET"])
def admin_project_agents(project_key):
    """List the agents of one project (read-only), for the admin picker.

    Returns each agent's id + description. The project_key is validated against the
    visible project list first, so an admin cannot probe an arbitrary/hidden key.
    """
    _identity, err = _admin_guard()
    if err:
        return err
    try:
        if project_key not in set(discovery.list_project_keys()):
            return jsonify({"status": "error", "error": "project_not_found"}), 404
        agents = discovery.list_project_agents(project_key)
    except Exception:
        logger.exception("admin/projects/<key>/agents - discovery failed")
        return jsonify({"status": "error", "error": "discovery_unavailable"}), 500
    return jsonify(
        {
            "status": "ok",
            "project_key": project_key,
            "count": len(agents),
            "agents": agents,
        }
    )


@api.route("/admin/agents", methods=["GET", "POST"])
def admin_agents():
    """Get or set the enabled-agents whitelist.

    GET returns the stored selection (admin view, includes project_key/agent_id).
    POST persists a new selection from ``{agents: [{project_key, agent_id}, ...]}``.
    Every requested agent is RE-VALIDATED server-side against the live DSS listings
    (project visible + agent actually present), so the persisted whitelist can only
    ever contain real, authorised agents - the front cannot inject an arbitrary id.
    """
    identity, err = _admin_guard()
    if err:
        return err

    if request.method == "GET":
        try:
            enabled = settings.get_enabled_agents()
        except Exception:
            logger.exception("admin/agents - GET failed")
            return jsonify({"status": "error", "error": "storage_unavailable"}), 500
        return jsonify({"status": "ok", "count": len(enabled), "agents": enabled})

    # POST: validate the requested agents against live DSS listings, then persist.
    body = request.get_json(silent=True) or {}
    requested = body.get("agents")
    if not isinstance(requested, list):
        return jsonify({"status": "error", "error": "invalid_payload"}), 400
    if len(requested) > MAX_ENABLED_AGENTS:
        return jsonify({"status": "error", "error": "too_many_agents"}), 400

    try:
        visible_projects = set(discovery.list_project_keys())

        # Preserve the admin's add order, de-dup pairs, and keep each pair's authored
        # display profile (tagline/description/capabilities/tools/icon/badge), keyed by
        # the (project_key, agent_id) pair. Last write wins for a duplicated pair.
        ordered_pairs = []
        meta_by_pair = {}
        seen_pairs = set()
        for item in requested:
            if not isinstance(item, dict):
                continue
            project_key = item.get("project_key")
            agent_id = item.get("agent_id")
            if not project_key or not agent_id:
                continue
            pair = (str(project_key), str(agent_id))
            meta_by_pair[pair] = item.get("profile")
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            ordered_pairs.append(pair)

        # Cache each project's live agent listing so a project is listed only once,
        # however many of its agents the admin selected (bounded, read-only discovery).
        listing_cache = {}
        enabled = []
        seen_keys = set()
        for project_key, agent_id in ordered_pairs:
            if project_key not in visible_projects:
                logger.warning(
                    "admin/agents - project %s not visible; skipped", project_key
                )
                continue
            if project_key not in listing_cache:
                listing_cache[project_key] = {
                    a["agent_id"]: a["description"]
                    for a in discovery.list_project_agents(project_key)
                }
            available = listing_cache[project_key]
            if agent_id not in available:
                logger.warning(
                    "admin/agents - agent %s not in project %s; skipped",
                    agent_id,
                    project_key,
                )
                continue
            logical_key = _logical_key(project_key, agent_id)
            if logical_key in seen_keys:
                continue
            seen_keys.add(logical_key)
            enabled.append(
                {
                    "logical_key": logical_key,
                    "project_key": project_key,
                    "agent_id": agent_id,
                    "label": available[agent_id],
                    # Admin-authored display profile - sanitized + bounded server-side
                    # (never a query/table/connection, just the agent-library copy).
                    "profile": validate_agent_meta(
                        meta_by_pair.get((project_key, agent_id))
                    ),
                }
            )

        settings.set_enabled_agents(enabled, updated_by=identity["user_id"])
    except Exception:
        logger.exception("admin/agents - POST failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    logger.info(
        "admin/agents - saved %d enabled agent(s) by %s",
        len(enabled),
        identity["user_id"],
    )
    return jsonify({"status": "ok", "count": len(enabled), "agents": enabled})


def register_routes(app):
    """Wire the OWIsMind API blueprint onto the DSS-provided Flask app.

    Applies the configured log level and logs the live route table + resolved
    storage at boot, so the DSS webapp log confirms which build is running and how
    storage resolved.
    """
    app.register_blueprint(api)
    try:
        sql_config.apply_log_level()
        logger.info("OWIsMind storage status: %s", sql_config.storage_status())
    except Exception:
        logger.exception("startup storage/log configuration failed")
    rules = sorted(
        rule.rule
        for rule in app.url_map.iter_rules()
        if rule.rule.startswith("/owismind-api")
    )
    logger.info("OWIsMind API ready - %d routes: %s", len(rules), ", ".join(rules))
