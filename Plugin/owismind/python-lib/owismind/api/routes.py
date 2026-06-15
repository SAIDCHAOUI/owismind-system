"""OWIsMind WebApp HTTP API (Flask blueprint, mounted under /owismind-api).

Routes:
  - ``/ping``          : health check + resolved storage configuration.
  - ``/me``            : caller identity (resolved server-side) + admin/config flags. POST
                         also records the caller in the users registry + first-admin bootstrap;
                         GET stays read-only.
  - ``/agents``        : the agents the admin enabled (opaque logical keys + labels).
  - ``/chat/start``    : run a real agent for one message in a background worker and
                         return a run_id; persists the user message first (phase one).
  - ``/chat/poll``     : fetch the run's normalised events since a cursor (live timeline);
                         the worker persists the answer + any generated SQL on completion.
  - ``/chat/stop``     : request a cooperative early stop of one's own in-flight run.
  - ``/chat/feedback`` : persist a 👍/👎 (+ optional reasons/comment) on one's own message.
  - ``/conversations`` : names-only, keyset-paginated conversation list (sidebar).
  - ``/conversation``  : all messages of ONE session, fetched lazily on click.
  - ``/evidence/*``    : Evidence Studio — meta / rows / distinct (owner-scoped, read-only, project datasets).
  - ``/admin/*``       : storage view + user/admin + agent-whitelist management (admin-gated).

Transport is polling, not SSE: DSS's internal nginx can buffer a long-lived
event-stream so events would arrive all at once. Instead the agent runs in a
background worker (agents/stream_manager) and the front polls short requests the
proxy never buffers — the same pattern the project's production Dash app uses.

Identity is always resolved from the authenticated browser headers, never from the
request body. The frontend only ever sends logical data (e.g. {session_id, message,
agent_key}); it never chooses table, connection, query, or a raw agent id — the
agent_key is an opaque logical key resolved server-side against the whitelist.
"""

import hashlib
import logging
import sys
import time
from datetime import datetime

from flask import Blueprint, g, jsonify, request

from owismind.agents import context, discovery, stream_manager
from owismind.evidence import service as evidence_service
from owismind.evidence import throttle as evidence_throttle
from owismind.storage import artifacts as artifacts_storage
from owismind.security.identity import IdentityError, derive_full_name, resolve_identity
from owismind.security.validation import (
    MAX_SESSION_ID_LENGTH,
    ValidationError,
    validate_chat_start_request,
    validate_conversations_limit,
    validate_evidence_column,
    validate_evidence_rows_request,
    validate_feedback,
    validate_history_limit,
    validate_optional_exchange_id,
    validate_required_exchange_id,
)
from owismind.storage import admin, chat_v5, settings, sql_config
from owismind.storage.migrations import ensure_chat_table

logger = logging.getLogger(__name__)

# Defensive cap on how many agents an admin can enable in one save.
MAX_ENABLED_AGENTS = 50

# Defensive upper bounds for the /chat/poll query params (opaque server-issued
# run_id is a 32-char uuid hex; cursor is a non-negative event index).
_MAX_RUN_ID_LENGTH = 64

api = Blueprint("owismind_api", __name__, url_prefix="/owismind-api")


def _logical_key(project_key, agent_id):
    """Deterministic, opaque logical key for an enabled agent.

    A stable hash of ``project_key:agent_id`` — stable so re-saving the selection
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

    Identity is resolved server-side from the browser auth headers. The side effect —
    recording the caller in the users registry AND the first-admin bootstrap — happens
    ONLY on POST, so a naive prefetch/scanner GET can neither create a user row nor win
    the first-admin election (the operational rule "first to open = admin" must not be
    triggerable by a non-interactive GET). The frontend issues POST once on init; GET
    stays read-only. Both methods return the same shape.
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/me — identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    logger.info(
        "/me — %s user_id=%s groups=%s",
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
            if request.method == "POST":
                admin.record_user(identity)
            is_admin_flag = admin.is_admin(identity["user_id"])
        except Exception:
            logger.exception("/me — user registry failed")

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
        }
    )


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
        logger.warning("/chat/start — identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    try:
        session_id, message, agent_key = validate_chat_start_request(
            request.get_json(silent=True)
        )
    except ValidationError as exc:
        logger.warning("/chat/start — invalid payload: %s", exc.code)
        return jsonify({"status": "error", "error": exc.code}), 400

    # Optional agent-context window (number of prior messages to replay). Read and
    # bounded separately so validate_chat_start_request stays untouched; the value is
    # strictly clamped server-side to [10, 50] (default 20).
    body = request.get_json(silent=True) or {}
    history_limit = validate_history_limit(body.get("history_limit"))

    # Optional conversation-tree edge: the exchange this new turn branches from (NULL for
    # a first turn / root). Never raises — a malformed value degrades to None, and the
    # ancestor-chain read is always user-scoped, so a forged id can only ever match the
    # caller's own rows.
    parent_exchange_id = validate_optional_exchange_id(body.get("parent_exchange_id"))

    if not sql_config.is_configured():
        logger.warning("/chat/start — storage not configured")
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    # Whitelist enforcement: resolve the opaque logical key to a real, still-enabled
    # agent. A forged or stale key matches nothing -> rejected (never runs an agent).
    agent = settings.resolve_enabled_agent(agent_key)
    if not agent:
        logger.warning("/chat/start — agent_key not enabled: %s", agent_key)
        return jsonify({"status": "error", "error": "agent_not_enabled"}), 404
    project_key = agent["project_key"]
    agent_id = agent["agent_id"]

    # Never log message CONTENT (privacy / log hygiene): only its length. Every other
    # module deliberately keeps prompt/answer bodies out of the logs; this request entry
    # point — the one place a body could leak — stays content-free too.
    logger.info(
        "/chat/start — user_id=%s session_id=%s agent_key=%s msg_len=%d",
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
        logger.warning("/chat/start — rejected before write: %s", reason)
        return jsonify({"status": "error", "error": reason}), (
            429 if reason == "rate_limited" else 503
        )

    # Phase one: persist the user message. Done in the request thread so a write
    # error surfaces as a clean HTTP error rather than inside the worker.
    try:
        ensure_chat_table()
        exchange_id = chat_v5.save_user_message(
            session_id, identity, message, agent_key, parent_exchange_id
        )
    except Exception:
        logger.exception("/chat/start — failed to persist user message")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    # Per-turn context prefix (re-states who is asking + the server-side date) prepended
    # to the current user message — the agent is stateless between calls.
    user_prefix = context.build_user_prefix(
        derive_full_name(identity["user_id"]), datetime.now()
    )

    # Spawn the bounded background worker. The agent_id stays server-side; the front
    # only ever receives the opaque run_id.
    try:
        run_id = stream_manager.start_run(
            project_key, agent_id, message, exchange_id,
            identity["user_id"], parent_exchange_id, history_limit, user_prefix,
        )
    except stream_manager.CapacityError:
        logger.warning("/chat/start — concurrency cap reached, rejected")
        return jsonify({"status": "error", "error": "busy"}), 503
    except Exception:
        logger.exception("/chat/start — failed to start agent run")
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
        logger.warning("/chat/poll — identity resolution failed: %s", exc)
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
    which) — a safe no-op the client treats as "already done". Identity comes from the
    auth headers, never the body.
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/chat/stop — identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    payload = request.get_json(silent=True) or {}
    run_id = payload.get("run_id") or ""
    if not isinstance(run_id, str) or not run_id or len(run_id) > _MAX_RUN_ID_LENGTH:
        return jsonify({"status": "error", "error": "invalid_run_id"}), 400

    if not stream_manager.request_stop(run_id, identity["user_id"]):
        return jsonify({"status": "error", "error": "run_not_found"}), 404

    logger.info("/chat/stop — run_id=%s user_id=%s", run_id, identity["user_id"])
    return jsonify({"status": "ok"})


@api.route("/chat/feedback", methods=["POST"])
def chat_feedback():
    """Persist 👍/👎 feedback (+ reasons + comment) on one of the caller's own messages.

    Identity comes from the auth headers (never the body); the UPDATE in
    ``chat_v5.save_feedback`` is owner-scoped (WHERE exchange_id AND user_id), so a
    caller can only rate their own exchange — an exchange owned by someone else is a
    silent no-op. The payload is validated/bounded server-side (rating 0/1/None,
    whitelisted reasons, bounded comment).
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/chat/feedback — identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    if not sql_config.is_configured():
        logger.warning("/chat/feedback — storage not configured")
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    try:
        exchange_id, rating, reasons, comment = validate_feedback(
            request.get_json(silent=True)
        )
    except ValidationError as exc:
        logger.warning("/chat/feedback — invalid payload: %s", exc.code)
        return jsonify({"status": "error", "error": exc.code}), 400

    try:
        ensure_chat_table()
        chat_v5.save_feedback(
            identity["user_id"], exchange_id, rating, reasons, comment
        )
    except Exception:
        logger.exception("/chat/feedback — feedback save failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    logger.info(
        "/chat/feedback — user_id=%s exchange_id=%s rating=%s",
        identity["user_id"],
        exchange_id,
        rating,
    )
    return jsonify({"status": "ok"})


@api.route("/conversations", methods=["GET"])
def conversations():
    """Names-only, keyset-paginated conversation list for the signed-in user.

    Powers the lazy sidebar: one page of conversation summaries (session_id, title,
    last_at) — never message bodies. ``cursor`` resumes a previous page; ``limit`` is
    clamped server-side to [1, 60] (default 30). Strictly owner-scoped.
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/conversations — identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    if not sql_config.is_configured():
        logger.warning("/conversations — storage not configured")
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
        logger.exception("/conversations — listing failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    logger.info(
        "/conversations — user_id=%s limit=%d returned %d (has_more=%s)",
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
        logger.warning("/conversation — identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    if not sql_config.is_configured():
        logger.warning("/conversation — storage not configured")
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    session_id = (request.args.get("session_id") or "").strip()
    if not session_id or len(session_id) > MAX_SESSION_ID_LENGTH:
        return jsonify({"status": "error", "error": "invalid_session_id"}), 400

    try:
        ensure_chat_table()
        rows = chat_v5.messages_for_session(identity["user_id"], session_id)
    except Exception:
        logger.exception("/conversation — load failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    logger.info(
        "/conversation — user_id=%s session_id=%s returned %d rows",
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
    logical key and human label — never a raw agent_id or project key — so the
    chat front references an agent solely by its logical key (server whitelist).
    """
    try:
        identity = resolve_identity(request.headers)
    except IdentityError as exc:
        logger.warning("/agents — identity resolution failed: %s", exc)
        return jsonify({"status": "error", "error": "unauthenticated"}), 401

    if not sql_config.is_configured():
        logger.warning("/agents — storage not configured")
        return jsonify({"status": "error", "error": "storage_not_configured"}), 409

    try:
        enabled = settings.get_enabled_agents()
    except Exception:
        logger.exception("/agents — query failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    # Project off only the public-safe fields (no agent_id / project_key leak).
    public = [
        {"key": a.get("logical_key"), "label": a.get("label")}
        for a in enabled
        if a.get("logical_key")
    ]
    logger.info(
        "/agents — user_id=%s returned %d enabled agent(s)",
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
        logger.warning("/evidence — identity resolution failed: %s", exc)
        return None, (jsonify({"status": "error", "error": "unauthenticated"}), 401)
    if not sql_config.is_configured():
        logger.warning("/evidence — storage not configured")
        return None, (jsonify({"status": "error", "error": "storage_not_configured"}), 409)
    try:
        ensure_chat_table()
    except Exception:
        logger.exception("/evidence — chat table bootstrap failed")
        return None, (jsonify({"status": "error", "error": "storage_unavailable"}), 500)
    # Per-user token-bucket gate: a scripted flood must not pin worker threads of the
    # mono-process polling backend (the legitimate auto-open meta+rows pair fits well
    # within the burst capacity). Checked after the cheap auth/config/bootstrap path.
    if not evidence_throttle.can_accept(identity["user_id"]):
        logger.warning("/evidence — rate limited user_id=%s", identity["user_id"])
        return None, (jsonify({"status": "error", "error": "rate_limited"}), 429)
    return identity, None


@api.route("/evidence/meta", methods=["GET"])
def evidence_meta():
    """Interactive descriptor of one exchange's evidence (or a degraded shape).

    The caller sends ONLY ``exchange_id``: table, connection, SQL and dataset
    matching are all resolved server-side. Owner-scoped — someone else's
    exchange is 404.
    """
    identity, err = _evidence_guard()
    if err:
        return err
    try:
        exchange_id = validate_required_exchange_id(request.args.get("exchange_id"))
    except ValidationError as exc:
        logger.warning("/evidence/meta — invalid exchange_id")
        return jsonify({"status": "error", "error": exc.code}), 400
    try:
        meta = evidence_service.evidence_meta(identity["user_id"], exchange_id)
    except evidence_service.EvidenceError as exc:
        return jsonify({"status": "error", "error": exc.code}), exc.status
    except Exception:
        logger.exception("/evidence/meta — failed")
        return jsonify({"status": "error", "error": "evidence_unavailable"}), 500
    # One observability line per meta: the verification outcome is the trust
    # layer's whole point, so it must be greppable next to available/reason.
    verification = meta.get("verification") or {}
    drilldown = meta.get("drilldown") or {}
    # Attach this exchange's rendered-artifact specs (chart / table the orchestrator
    # asked for). Owner-scoped, best-effort: a read failure degrades to no artifacts,
    # never a 500 — the rest of the evidence panel stays usable.
    try:
        meta["artifacts"] = artifacts_storage.read_artifacts(identity["user_id"], exchange_id)
    except Exception:
        logger.exception("/evidence/meta — artifacts read failed (non-fatal)")
        meta["artifacts"] = []
    logger.info(
        "/evidence/meta — user_id=%s exchange_id=%s available=%s reason=%s "
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
        (exchange_id, filters, kept_ids, include_advanced, page, sort, drill) = (
            validate_evidence_rows_request(request.get_json(silent=True))
        )
    except ValidationError as exc:
        logger.warning("/evidence/rows — invalid payload: %s", exc.code)
        return jsonify({"status": "error", "error": exc.code}), 400
    try:
        result = evidence_service.evidence_rows(
            identity["user_id"], exchange_id, filters, kept_ids,
            include_advanced, page, sort, drill,
        )
    except evidence_service.EvidenceError as exc:
        return jsonify({"status": "error", "error": exc.code}), exc.status
    except Exception:
        logger.exception("/evidence/rows — failed")
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
        logger.warning("/evidence/distinct — invalid payload: %s", exc.code)
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
        logger.exception("/evidence/distinct — failed")
        return jsonify({"status": "error", "error": "evidence_unavailable"}), 500
    return jsonify({"status": "ok", **result})


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
        logger.exception("admin guard — admin check failed")
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
        logger.exception("admin/users — query failed")
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
        logger.exception("admin/projects — discovery failed")
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
        logger.exception("admin/projects/<key>/agents — discovery failed")
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
    ever contain real, authorised agents — the front cannot inject an arbitrary id.
    """
    identity, err = _admin_guard()
    if err:
        return err

    if request.method == "GET":
        try:
            enabled = settings.get_enabled_agents()
        except Exception:
            logger.exception("admin/agents — GET failed")
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

        # Group requested agent ids by project so each project is listed only once.
        requested_by_project = {}
        for item in requested:
            if not isinstance(item, dict):
                continue
            project_key = item.get("project_key")
            agent_id = item.get("agent_id")
            if not project_key or not agent_id:
                continue
            requested_by_project.setdefault(str(project_key), set()).add(str(agent_id))

        enabled = []
        seen_keys = set()
        for project_key, requested_ids in requested_by_project.items():
            if project_key not in visible_projects:
                logger.warning(
                    "admin/agents — project %s not visible; skipped", project_key
                )
                continue
            available = {
                a["agent_id"]: a["description"]
                for a in discovery.list_project_agents(project_key)
            }
            for agent_id in requested_ids:
                if agent_id not in available:
                    logger.warning(
                        "admin/agents — agent %s not in project %s; skipped",
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
                    }
                )

        settings.set_enabled_agents(enabled, updated_by=identity["user_id"])
    except Exception:
        logger.exception("admin/agents — POST failed")
        return jsonify({"status": "error", "error": "storage_unavailable"}), 500

    logger.info(
        "admin/agents — saved %d enabled agent(s) by %s",
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
    logger.info("OWIsMind API ready — %d routes: %s", len(rules), ", ".join(rules))
