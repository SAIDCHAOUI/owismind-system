"""SQL persistence for the console's guided runs (survives reloads and restarts).

The guided assistant (guided.py) walks an operator from dataset selection to an
enabled orchestrator capability. Its whole state lives in ONE row of a direct
SQL table so a webapp reload or a backend restart never loses the run: the
console re-reads the active run at startup and resumes where the operator was.

Storage follows the plugin backend's proven direct-SQL pattern
(plugin/owismind/python-lib/owismind/storage/):
- physical name ``{PROJECT_KEY}_owismind_factory_guided_v1`` cited as
  ``public."..."`` (project key ALWAYS leads, ``owismind`` namespace present);
- ``CREATE TABLE IF NOT EXISTS`` behind a per-process guard (idempotent DDL,
  never from user input);
- every write carries an explicit COMMIT (post_queries);
- every VALUE is parameterized through ``dataiku.sql`` (Constant + toSQL),
  never interpolated raw; identifiers pass a strict charset gate;
- reads are bounded (LIMIT 1) with a statement timeout.

``dataiku`` is imported lazily inside functions so the module stays importable
in DSS-free unit tests (the whole owismind_factory package rule); tests inject
a fake executor through the ``executor_factory`` constructor parameter.
"""

import hashlib
import json
import re
import threading

LOGICAL_NAME = "factory_guided_v1"

# PostgreSQL truncates identifiers beyond 63 bytes SILENTLY; reject/shorten
# loudly instead (same rule as the plugin's sql_config, lesson L110).
_MAX_IDENTIFIER_BYTES = 63
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# state_json weight cap: a run state is a small machine + journals, never data
# rows. Above the soft cap the journals are trimmed; above the hard cap we
# refuse to write (a bug would otherwise grow the row unbounded).
_STATE_SOFT_CAP = 150000
_STATE_HARD_CAP = 400000
_JOURNAL_TRIM_KEEP = 25

_READ_TIMEOUT_MS = 5000

# One CREATE TABLE per (connection, table) per process.
_ENSURED = set()
_ENSURED_LOCK = threading.Lock()

_DDL = (
    'CREATE TABLE IF NOT EXISTS {table} ('
    ' run_id        TEXT PRIMARY KEY,'
    ' domain        TEXT NOT NULL,'
    ' status        VARCHAR(16) NOT NULL,'
    ' current_stage TEXT NOT NULL,'
    ' state_json    TEXT NOT NULL,'
    ' created_at    TIMESTAMP NOT NULL DEFAULT now(),'
    ' updated_at    TIMESTAMP NOT NULL DEFAULT now()'
    ')'
)


class GuidedStoreError(RuntimeError):
    """A storage-level failure the route layer reports as-is (French-safe text)."""


def shorten_identifier(name):
    """Keep an identifier under the PostgreSQL 63-byte cap, collision-safely.

    Same idea as the plugin's ``sql_config._shorten_identifier``: keep a
    readable head and append a short content hash so two distinct long names
    can never silently collide after truncation.
    """
    if len(name.encode("utf-8")) <= _MAX_IDENTIFIER_BYTES:
        return name
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    head = name[: _MAX_IDENTIFIER_BYTES - len(digest) - 1]
    return "%s_%s" % (head, digest)


def physical_table(project_key):
    """``{PROJECT_KEY}_owismind_factory_guided_v1``, validated and length-safe."""
    key = str(project_key or "").strip()
    if not _IDENTIFIER_RE.match(key):
        raise GuidedStoreError("invalid project key for table naming: %r" % key)
    return shorten_identifier("%s_owismind_%s" % (key, LOGICAL_NAME))


def quote_table(table):
    """Return the cited reference ``public."<table>"`` after a strict charset gate."""
    if not _IDENTIFIER_RE.match(table or ""):
        raise GuidedStoreError("invalid table identifier: %r" % table)
    return 'public."%s"' % table


def _sql_value(value):
    """Parameterize one value through dataiku.sql (the plugin's exact pattern)."""
    from dataiku.sql import Constant, Dialects, toSQL

    return toSQL(Constant(value), dialect=Dialects.POSTGRES)


def _trim_journals(state, keep):
    """Trim every stage journal in place to its last ``keep`` entries."""
    stages = state.get("stages")
    if not isinstance(stages, dict):
        return
    for entry in stages.values():
        journal = entry.get("journal") if isinstance(entry, dict) else None
        if isinstance(journal, list) and len(journal) > keep:
            dropped = len(journal) - keep
            entry["journal"] = (
                [{"step": "journal", "status": "SKIPPED",
                  "detail": "%d earlier entries trimmed for storage" % dropped}]
                + journal[-keep:]
            )


def serialize_state(state):
    """JSON-encode a run state within the storage caps (trim journals if needed)."""
    text = json.dumps(state, ensure_ascii=False, sort_keys=False)
    if len(text) > _STATE_SOFT_CAP:
        _trim_journals(state, _JOURNAL_TRIM_KEEP)
        text = json.dumps(state, ensure_ascii=False, sort_keys=False)
    if len(text) > _STATE_HARD_CAP:
        raise GuidedStoreError(
            "run state too large to persist (%d chars > %d)" % (len(text), _STATE_HARD_CAP))
    return text


class GuidedStore(object):
    """CRUD for guided runs over one direct-SQL table.

    :param str connection: DSS SQL connection name (from the hub factory settings).
    :param str project_key: current project key (leads every physical name).
    :param executor_factory: optional zero-arg callable returning an object with
        the ``SQLExecutor2.query_to_df`` contract (tests inject a fake; the
        default builds a real ``dataiku.SQLExecutor2``).
    """

    def __init__(self, connection, project_key, executor_factory=None):
        if not connection or not str(connection).strip():
            raise GuidedStoreError("no SQL connection configured (hub factory_settings.json)")
        self.connection = str(connection).strip()
        self.project_key = str(project_key or "").strip()
        self.table = physical_table(self.project_key)
        self._executor_factory = executor_factory

    # ------------------------------------------------------------------ plumbing

    def _executor(self):
        if self._executor_factory is not None:
            return self._executor_factory()
        import dataiku

        return dataiku.SQLExecutor2(connection=self.connection)

    def _write(self, statements):
        """Run mutating statements followed by an explicit COMMIT."""
        self._executor().query_to_df(
            "SELECT 1 AS ok",
            pre_queries=list(statements),
            post_queries=["COMMIT"],
        )

    def _read(self, query):
        return self._executor().query_to_df(
            query,
            pre_queries=["SET statement_timeout TO %d" % _READ_TIMEOUT_MS],
        )

    def ensure_table(self):
        key = (self.connection, self.table)
        with _ENSURED_LOCK:
            if key in _ENSURED:
                return
        self._write([_DDL.format(table=quote_table(self.table))])
        with _ENSURED_LOCK:
            _ENSURED.add(key)

    # ------------------------------------------------------------------ CRUD

    def save(self, run):
        """Upsert one run row (the run dict is the single source of truth)."""
        state_text = serialize_state(run.get("state") or {})
        self.ensure_table()
        statement = (
            "INSERT INTO {table} (run_id, domain, status, current_stage, state_json) "
            "VALUES ({run_id}, {domain}, {status}, {current}, {state}) "
            "ON CONFLICT (run_id) DO UPDATE SET "
            "status = EXCLUDED.status, current_stage = EXCLUDED.current_stage, "
            "state_json = EXCLUDED.state_json, updated_at = now()"
        ).format(
            table=quote_table(self.table),
            run_id=_sql_value(str(run.get("run_id") or "")),
            domain=_sql_value(str(run.get("domain") or "")),
            status=_sql_value(str(run.get("status") or "")),
            current=_sql_value(str(run.get("current_stage") or "")),
            state=_sql_value(state_text),
        )
        self._write([statement])

    def _row_to_run(self, df):
        if df is None or len(df) == 0:
            return None
        row = df.iloc[0]
        try:
            state = json.loads(row["state_json"])
        except Exception:
            state = {}
        return {
            "run_id": str(row["run_id"]),
            "domain": str(row["domain"]),
            "status": str(row["status"]),
            "current_stage": str(row["current_stage"]),
            "state": state,
        }

    def load_active(self):
        """The most recent run still marked active, or None."""
        self.ensure_table()
        query = (
            "SELECT run_id, domain, status, current_stage, state_json "
            "FROM {table} WHERE status = {active} "
            "ORDER BY updated_at DESC LIMIT 1"
        ).format(table=quote_table(self.table), active=_sql_value("active"))
        return self._row_to_run(self._read(query))

    def load(self, run_id):
        self.ensure_table()
        query = (
            "SELECT run_id, domain, status, current_stage, state_json "
            "FROM {table} WHERE run_id = {run_id} LIMIT 1"
        ).format(table=quote_table(self.table), run_id=_sql_value(str(run_id or "")))
        return self._row_to_run(self._read(query))

    # ------------------------------------------------------------------ probes

    def table_has_rows(self, table_name):
        """True/False when the physical table provably has/lacks rows, None when
        the check itself is impossible (invalid identifier, SQL error): callers
        must treat None as "could not verify", NEVER as "empty"."""
        try:
            query = "SELECT 1 AS ok FROM %s LIMIT 1" % quote_table(str(table_name or ""))
        except GuidedStoreError:
            return None
        try:
            df = self._read(query)
        except Exception:
            return None
        return len(df) > 0
