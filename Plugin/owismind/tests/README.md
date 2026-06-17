# OWIsMind backend tests

Lightweight test harness for the plugin backend. This directory is **outside
`python-lib/`**, so it is **never packaged** into the deployable zip.

## Run

```bash
# from the repo root
python3 -m unittest discover -s Plugin/owismind/tests -v
```

No installs required: the runnable tests cover **pure-logic** modules only
(stdlib `unittest`). They put `python-lib/` on `sys.path` so `owismind.*` resolves.

## Covered now (runnable without DSS)

- `test_validation.py` - `owismind.security.validation`: `/chat/start` payload shape +
  bounds (the guard in front of every chat write).
- `test_history_limit.py` - `validate_history_limit` (agent-context window clamped to
  [10, 50], default 20) and `validate_optional_exchange_id` (branch parent id or None).
- `test_conversations_limit.py` - `validate_conversations_limit` (sidebar page size
  clamped to [1, 60], default 30, never raises).
- `test_feedback_validation.py` - `validate_feedback` (rating in {0, 1, None}, reason
  whitelist, bounded comment; bool rating rejected).
- `test_session_queries.py` - `storage.sql_builders.build_conversation_list_query` and
  `build_session_messages_query`: user(+session)-scoped, keyset-paginated, row-capped.
- `test_ancestor_chain.py` - `storage.sql_builders.build_ancestor_chain_query`: the
  recursive parent walk is user-scoped in BOTH CTE members and depth + LIMIT bounded.
- `test_pagination.py` - `storage.pagination` opaque cursor round-trips; malformed input
  degrades to None.
- `test_agent_context.py` - `agents.context` pure multi-turn assembly (prefix, flatten
  exchanges → messages, generated-SQL grounding, final completion list).
- `test_identity_names.py` - `security.identity.derive_full_name` (`prenom.nom` →
  `Prenom Nom`); uses a minimal `dataiku` stub so the import succeeds.
- `test_evidence_sql_parse.py` - `evidence.sql_parse`: tokenizer, `parse_select` (table +
  predicates + advanced fragment, stable degraded reasons) and `validate_fragment` (banned
  words on bare AND quoted identifiers, `pg_*`, balanced parens, bounded length).
- `test_evidence_query_builders.py` - `evidence.query_builders`: owner-scoped exchange
  lookup, bounded rows/distinct queries (mandatory ORDER BY), `render_predicate` per op.
- `test_evidence_whitelist.py` - `evidence.whitelist.match_whitelist`: case-insensitive
  table match, missing-schema wildcard, unknown table/schema mismatch rejected.
- `test_evidence_validation.py` - `validate_evidence_rows_request` & co: structured
  filters bounds (ops, values, kept_ids), clamped page, degrading sort - no SQL in any
  accepted payload.
- `test_evidence_throttle.py` - `evidence.throttle.take_token`: the pure per-user
  token-bucket core (burst capacity, linear refill, deterministic in `now`) gating the
  read-only `/evidence/*` routes.

The frontend has matching pure-logic tests (no install - Node's built-in runner) under
`frontend/test/` (the timeline reducer, preference clamps, the conversation tree, agent
pick, the Evidence Studio model `evidenceModel.test.js` - chips/payload/modified - etc.).
Run with `npm test` (or `node --test test/*.test.js`) from `frontend/`.

## To add (need the DSS Python env: `dataiku`, `pandas`)

These modules import `dataiku`/`pandas` at module load, so they need the DSS env (or a
stub) to import. They are the highest-value invariants and should get a CI job inside DSS:

- `sql_config.pg_identifier` - rejects an injected identifier; quoting is correct.
- `storage.serialization.rows_to_json_safe` - NaN/NaT → None, timestamps → ISO.
- `settings.resolve_enabled_agent` - only an enabled `logical_key` resolves; a forged key
  resolves to `None`.
- `agents.stream_manager` - the run state machine: cursor advance, TTL eviction,
  concurrency cap, `can_accept` rate/cap gate, and the cooperative stop (`_stop_reason`).
- `security.identity.derive_display_name` - login → friendly default; cache TTL behaviour.

## CI

There is no CI yet. Minimal recommended pipeline: lint + `python3 -m py_compile` over
`python-lib/owismind/**` + this `unittest` suite + `vite build` (compile check).
