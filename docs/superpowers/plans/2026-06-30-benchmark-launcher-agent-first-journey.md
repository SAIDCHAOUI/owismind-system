# Benchmark Launcher Agent-First Journey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the LAB benchmark Launcher into an agent-first guided journey where a benchmark's questions are auto-derived from a per-question agent tag, runs accumulate in append mode, and the user can never hit a silent dead-end.

**Architecture:** A new `agent_key` column tags each golden question to one logical agent. A benchmark stores no question list: its members are the active golden rows tagged to its agent, and tested/pending status is derived per (question, mode) from the scored dataset. The pure lib (`benchmark/`) owns the model + per-mode launch resolution; the webapp shared lib (`benchmark_webapp/`) owns the pure view-models + the locked DSS I/O; the launcher webapp renders an agents rail master-detail. State lives in the `benchmark` project variable (benchmarks, redo sets, run_request, settings, agent catalog); questions and results live in Flow datasets.

**Tech Stack:** Python 3.9 (stdlib + dataiku + pandas), framework-free vanilla JS (one file) + a thin Flask backend, `unittest` for Python, `node --test` for pure JS helpers (no install).

## Global Constraints

- No em dash (U+2014) and no en dash (U+2013) anywhere: strings, code, comments, commit messages, EN and FR i18n. Use `-` / `:` / `,` / parentheses. (Project rule #9.)
- Orange charter: white/black/flat/square (`border-radius: 0`, only avatars round), a single orange `#FF7900` used rarely (eyebrow, 52x4 title-bar, selected rail edge, the one primary button per screen, the pending dot, the progress fill), semantic tokens (no hex in dur). Banned: gradients, blur/backdrop-filter, glow/big shadows, emoji, color-mix. (Project rule #10.)
- SQL: parametrized, COMMIT after write, READ + APPEND only on the shared connection, no generic SQL route. Golden writes via the Dataset API, never raw SQL.
- Instance safety: bounded concurrency + per-call timeout (unchanged); variable mutations are small read-modify-write under the existing lock; only added reads are the cached discovery + the existing scored read + a bounded `information_schema` for schema validation. No discovery call on every page load.
- Pure modules never raise (degrade to an empty view, not a 500). New pure code is unit-tested.
- Code and comments in English. Bilingual UI EN default + FR.
- NO INSTALL: never run npm/pip/brew installs. `node --test` and `unittest` are built in.
- Backend observed = Python 3.9.23. Do not assume 3.11 features.
- Test command (Python): `python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python`
- Logical `agent_key` is the golden tag and the benchmark match key; the concrete `agent_id` + `project_key` are the call binding, snapshotted on the benchmark. Never tag by label or raw id.

All paths below are relative to the repo root `/Users/saidchaoui/projects/owismind`. The lib import root is `OWIsMind_LAB/project-library/python` (packages import as `from benchmark ...` / `from benchmark_webapp ...`).

---

## File Structure

Created:
- `OWIsMind_LAB/webapps/benchmark_launcher/test/` (node:test pure JS helper tests; new dir)
- `OWIsMind_LAB/webapps/benchmark_launcher/journey.js` (pure JS reducers/derivations, loaded before `script.js`; new, testable)

Modified:
- `OWIsMind_LAB/project-library/python/benchmark/schemas.py` (golden `agent_key`)
- `OWIsMind_LAB/project-library/python/benchmark/registry.py` (drop membership map, redo set, delete, per-mode resolve)
- `OWIsMind_LAB/project-library/python/benchmark/run_params.py` (settings keys; retire category filter for membership)
- `OWIsMind_LAB/project-library/python/benchmark/dss_steps/step_run_matrix.py` (per-mode plan + agent-tagged membership)
- `OWIsMind_LAB/project-library/python/benchmark_webapp/views.py` (new pure view-models, drop config builder)
- `OWIsMind_LAB/project-library/python/benchmark_webapp/dss.py` (variable RMW, discovery, golden tag + bootstrap, settings, delete, run reset)
- `OWIsMind_LAB/webapps/benchmark_launcher/backend.py` (routes)
- `OWIsMind_LAB/webapps/benchmark_launcher/script.js` (agent-first UI)
- `OWIsMind_LAB/webapps/benchmark_launcher/style.css` (rail + screens)
- `OWIsMind_LAB/webapps/benchmark_launcher/body.html` (load journey.js)

Tests modified/created:
- `OWIsMind_LAB/project-library/python/benchmark/tests/test_schemas.py`
- `OWIsMind_LAB/project-library/python/benchmark/tests/test_registry.py`
- `OWIsMind_LAB/project-library/python/benchmark/tests/test_run_params.py`
- `OWIsMind_LAB/project-library/python/benchmark_webapp/tests/test_views.py`
- `OWIsMind_LAB/webapps/benchmark_launcher/test/journey.test.js` (new)

---

# PHASE 1 - Pure data model (`benchmark/`)

### Task 1: Golden `agent_key` column

**Files:**
- Modify: `OWIsMind_LAB/project-library/python/benchmark/schemas.py`
- Test: `OWIsMind_LAB/project-library/python/benchmark/tests/test_schemas.py`

**Interfaces:**
- Produces: `GOLDEN_COLUMNS` includes `"agent_key"`; `RAW_COLUMNS` includes `"agent_key"`; `normalize_golden_row` carries `agent_key` (blank -> None). `agent_key` is NOT added to `_REQUIRED_GOLDEN`.

- [ ] **Step 1: Write the failing test** in `test_schemas.py` (append):

```python
def test_golden_columns_has_agent_key(self):
    self.assertIn("agent_key", schemas.GOLDEN_COLUMNS)

def test_raw_columns_has_agent_key(self):
    self.assertIn("agent_key", schemas.RAW_COLUMNS)

def test_agent_key_not_required(self):
    row = {"question_id": "q1", "question": "x", "reference_answer": "y"}
    ok, errors = schemas.validate_golden_row(row)
    self.assertTrue(ok, errors)  # blank agent_key still validates

def test_normalize_carries_agent_key(self):
    out = schemas.normalize_golden_row(
        {"question_id": "q1", "question": "x", "reference_answer": "y",
         "agent_key": "  revenue_expert "})
    self.assertEqual(out["agent_key"], "revenue_expert")
    out2 = schemas.normalize_golden_row(
        {"question_id": "q1", "question": "x", "reference_answer": "y", "agent_key": ""})
    self.assertIsNone(out2["agent_key"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m unittest benchmark.tests.test_schemas -v` (from the lib root)
Expected: FAIL (`agent_key` not in `GOLDEN_COLUMNS`).

- [ ] **Step 3: Implement** in `schemas.py`. In `GOLDEN_COLUMNS`, add after `"notes"` and before the reference SQL block:

```python
    "agent_key",             # nullable: the LOGICAL agent this question tests (membership tag)
```

In `RAW_COLUMNS`, add right after `"agent_id",`:

```python
    "agent_key_tag",         # the golden agent tag carried for display/breakdown (logical key)
```

(Use `agent_key_tag` in RAW to avoid colliding with the existing `agent_key` runner column which already holds the benchmark agent's key; they are the same value here but keep the names distinct so the raw schema stays unambiguous.) `normalize_golden_row` already loops `GOLDEN_COLUMNS`, so `agent_key` is carried with the trim/None rules automatically; no extra code needed there.

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m unittest benchmark.tests.test_schemas -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add OWIsMind_LAB/project-library/python/benchmark/schemas.py OWIsMind_LAB/project-library/python/benchmark/tests/test_schemas.py
git commit -m "feat(benchmark): add agent_key tag column to golden schema"
```

---

### Task 2: Logical agent_key slug + per-agent name uniqueness

**Files:**
- Modify: `OWIsMind_LAB/project-library/python/benchmark/registry.py`
- Test: `OWIsMind_LAB/project-library/python/benchmark/tests/test_registry.py`

**Interfaces:**
- Produces: `slug_agent_key(label) -> str` (lowercase, `[a-z0-9_]`, collapse runs to `_`, strip, fallback `"agent"`); `names_for_agent(registry, agent_key) -> set[str]` (lowercased names of that agent's benchmarks); `validate_benchmark_name(name, taken_names)` unchanged (callers pass the per-agent set).

- [ ] **Step 1: Write the failing test** in `test_registry.py` (append a class):

```python
class TestAgentKeyAndNames(unittest.TestCase):
    def test_slug_agent_key(self):
        self.assertEqual(registry.slug_agent_key("Revenue Expert"), "revenue_expert")
        self.assertEqual(registry.slug_agent_key("  OWIsMind Orchestrator (DEV) "),
                         "owismind_orchestrator_dev")
        self.assertEqual(registry.slug_agent_key(""), "agent")

    def test_names_for_agent_is_scoped(self):
        reg = {
            "B1": _entity(benchmark_id="B1", name="Baseline", agent_key="revenue_expert"),
            "B2": _entity(benchmark_id="B2", name="Baseline", agent_key="tickets_expert"),
        }
        self.assertEqual(registry.names_for_agent(reg, "revenue_expert"), {"baseline"})
        self.assertEqual(registry.names_for_agent(reg, "tickets_expert"), {"baseline"})
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m unittest benchmark.tests.test_registry -v`
Expected: FAIL (`slug_agent_key` not defined).

- [ ] **Step 3: Implement** in `registry.py` (near the scalar helpers):

```python
import re

def slug_agent_key(label):
    """A stable logical agent key from a human label. Pure, never raises.

    Lowercase, keep [a-z0-9_], collapse other runs to a single '_', strip leading/trailing '_'.
    Falls back to 'agent' for an empty / symbol-only label.
    """
    s = _clean(label).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "agent"


def names_for_agent(registry, agent_key):
    """Lower-cased benchmark names already used BY THIS AGENT (name uniqueness is per agent)."""
    akey = _clean(agent_key)
    return {_clean(e.get("name")).lower() for e in (registry or {}).values()
            if isinstance(e, dict) and _clean(e.get("agent_key")) == akey and _clean(e.get("name"))}
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m unittest benchmark.tests.test_registry -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add OWIsMind_LAB/project-library/python/benchmark/registry.py OWIsMind_LAB/project-library/python/benchmark/tests/test_registry.py
git commit -m "feat(benchmark): logical agent_key slug + per-agent name uniqueness"
```

---

### Task 3: Drop membership map, add redo set + delete; create without seed

**Files:**
- Modify: `OWIsMind_LAB/project-library/python/benchmark/registry.py`
- Test: `OWIsMind_LAB/project-library/python/benchmark/tests/test_registry.py`

**Interfaces:**
- Produces: entity shape now carries `"redo": list[str]` instead of `"questions"`. `normalize_entity` parses a `redo` list (tolerates a legacy `questions` dict by ignoring it). `create_benchmark(registry, benchmark_id, name, agent, modes, created_at, created_by="")` (no `question_ids`). `delete_benchmark(registry, benchmark_id)`. `set_redo(registry, benchmark_id, question_id, value)`. `reset_redo_for(registry, benchmark_id, question_ids)`. Removed: `_normalize_questions`, `add_questions`, `remove_question`, `set_include_next`, `reset_include_next_for`, `archive_benchmark`, `_member_order`.

- [ ] **Step 1: Write the failing test** in `test_registry.py`. First update the shared `_entity` helper (replace `"questions": {}` with `"redo": []`), then add:

```python
class TestEntityRedo(unittest.TestCase):
    def test_normalize_parses_redo_list(self):
        e = registry.normalize_entity(_entity(redo=["q1", "q2", "q1", ""]))
        self.assertEqual(e["redo"], ["q1", "q2"])  # de-duped, blanks dropped, order kept

    def test_normalize_ignores_legacy_questions_map(self):
        raw = _entity()
        raw.pop("redo", None)
        raw["questions"] = {"q9": {"added_at": "x"}}  # legacy shape
        e = registry.normalize_entity(raw)
        self.assertEqual(e["redo"], [])
        self.assertNotIn("questions", e)

    def test_create_benchmark_no_seed(self):
        reg = registry.create_benchmark({}, "B9", "Q4", _AGENT, ["Smart"], "2026-06-30T00:00:00Z")
        self.assertEqual(reg["B9"]["name"], "Q4")
        self.assertEqual(reg["B9"]["redo"], [])
        self.assertEqual(reg["B9"]["modes"], ["Smart"])

    def test_delete_benchmark(self):
        reg = {"B1": _entity()}
        out = registry.delete_benchmark(reg, "B1")
        self.assertNotIn("B1", out)

    def test_set_and_reset_redo(self):
        reg = {"B1": _entity(redo=[])}
        reg = registry.set_redo(reg, "B1", "q1", True)
        self.assertEqual(reg["B1"]["redo"], ["q1"])
        reg = registry.set_redo(reg, "B1", "q1", True)  # idempotent
        self.assertEqual(reg["B1"]["redo"], ["q1"])
        reg = registry.set_redo(reg, "B1", "q1", False)
        self.assertEqual(reg["B1"]["redo"], [])
        reg = registry.set_redo(reg, "B1", "q2", True)
        reg = registry.reset_redo_for(reg, "B1", ["q2", "qX"])
        self.assertEqual(reg["B1"]["redo"], [])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m unittest benchmark.tests.test_registry -v`
Expected: FAIL.

- [ ] **Step 3: Implement** in `registry.py`:

Replace `_normalize_questions` with a redo normalizer:

```python
def _normalize_redo(value):
    """Normalize the redo set into an ordered, de-duped list of question_ids. Never raises."""
    parsed = _coerce_obj(value)
    out, seen = [], set()
    if isinstance(parsed, list):
        for qid in parsed:
            key = _clean(qid)
            if key and key not in seen:
                seen.add(key)
                out.append(key)
    return out
```

In `normalize_entity`, replace the `"questions": _normalize_questions(...)` line with:

```python
        "redo": _normalize_redo(raw.get("redo")),
```

Update `_copy_registry` to clone `redo` instead of `questions`:

```python
def _copy_registry(registry):
    out = {}
    for bid, entity in (registry or {}).items():
        if isinstance(entity, dict):
            clone = dict(entity)
            clone["redo"] = list(entity.get("redo") or [])
            clone.pop("questions", None)
            out[_clean(bid) or _clean(entity.get("benchmark_id"))] = clone
    return out
```

Replace `create_benchmark` (drop `question_ids`):

```python
def create_benchmark(registry, benchmark_id, name, agent, modes, created_at, created_by=""):
    """Return a new registry with a fresh, EMPTY-redo benchmark added. Pure, never raises.

    Membership is auto-derived (active golden rows tagged to the agent), so nothing is seeded here.
    ``agent`` is ``{agent_key, agent_label, project_key, agent_id}``. The caller mints benchmark_id +
    created_at and has validated the name uniqueness (validate_benchmark_name with names_for_agent).
    """
    out = _copy_registry(registry)
    agent = agent if isinstance(agent, dict) else {}
    entity = normalize_entity({
        "benchmark_id": _clean(benchmark_id),
        "name": _clean(name),
        "agent_key": _clean(agent.get("agent_key")),
        "agent_label": _clean(agent.get("agent_label")),
        "project_key": _clean(agent.get("project_key")),
        "agent_id": _clean(agent.get("agent_id")),
        "modes": modes if isinstance(modes, list) else [],
        "status": _STATUS_ACTIVE,
        "created_at": _clean(created_at),
        "created_by": _clean(created_by),
        "redo": [],
    })
    if entity:
        out[entity["benchmark_id"]] = entity
    return out
```

Add `delete_benchmark`, `set_redo`, `reset_redo_for`; delete `add_questions`, `remove_question`, `set_include_next`, `reset_include_next_for`, `archive_benchmark`, `_member_order`:

```python
def delete_benchmark(registry, benchmark_id):
    """Hard-remove a benchmark from the registry. Pure, never raises. Scored rows are untouched."""
    out = _copy_registry(registry)
    out.pop(_clean(benchmark_id), None)
    return out


def set_redo(registry, benchmark_id, question_id, value):
    """Set/clear the 'redo at next run' flag for one member question. Pure, never raises."""
    out = _copy_registry(registry)
    entity = out.get(_clean(benchmark_id))
    if isinstance(entity, dict):
        qid = _clean(question_id)
        redo = entity.setdefault("redo", [])
        if value and qid and qid not in redo:
            redo.append(qid)
        elif not value and qid in redo:
            redo.remove(qid)
    return out


def reset_redo_for(registry, benchmark_id, question_ids):
    """Clear the redo flag for the given questions (after they ran). Pure, never raises."""
    out = _copy_registry(registry)
    entity = out.get(_clean(benchmark_id))
    if isinstance(entity, dict):
        drop = {_clean(q) for q in (question_ids or [])}
        entity["redo"] = [q for q in (entity.get("redo") or []) if q not in drop]
    return out
```

- [ ] **Step 4: Run to verify it passes** (the resolve tests for removed functions will be rewritten in Task 4; if any existing test references `add_questions`/`questions`, update or delete it now so the suite is green).

Run: `python3 -m unittest benchmark.tests.test_registry -v`
Expected: PASS (after pruning obsolete tests in the same file).

- [ ] **Step 5: Commit**

```bash
git add OWIsMind_LAB/project-library/python/benchmark/registry.py OWIsMind_LAB/project-library/python/benchmark/tests/test_registry.py
git commit -m "feat(benchmark): replace membership map with redo set + hard delete"
```

---

### Task 4: Per-mode done detection + resolve_to_run plan

**Files:**
- Modify: `OWIsMind_LAB/project-library/python/benchmark/registry.py`
- Test: `OWIsMind_LAB/project-library/python/benchmark/tests/test_registry.py`

**Interfaces:**
- Produces: `done_cells(scored_rows, benchmark_id, agent_key=None) -> set[tuple[str,str]]` of `(question_id, mode)`; `resolve_to_run(entity, golden_agent_active_ids, scored_rows, launch_mode=LAUNCH_APPEND) -> dict[str, list[str]]` mapping each mode in `entity.modes` to the ordered question_ids to run for that mode. `attempt_numbers` / `next_attempt_no` keep their per-(question, mode) behavior (unchanged). Removed the old question-id-list `resolve_to_run`.

- [ ] **Step 1: Write the failing test** in `test_registry.py`:

```python
class TestResolvePlan(unittest.TestCase):
    def test_done_cells_per_mode(self):
        scored = [_scored("B1", "q1", mode="Smart"), _scored("B1", "q1", mode="Pro"),
                  _scored("B1", "q2", mode="Smart"), _scored("BX", "q3", mode="Smart")]
        self.assertEqual(registry.done_cells(scored, "B1"),
                         {("q1", "Smart"), ("q1", "Pro"), ("q2", "Smart")})

    def test_append_skips_done_cells_per_mode(self):
        e = _entity(benchmark_id="B1", modes=["Smart", "Pro"], redo=[])
        scored = [_scored("B1", "q1", mode="Smart"), _scored("B1", "q1", mode="Pro"),
                  _scored("B1", "q2", mode="Smart")]
        plan = registry.resolve_to_run(e, ["q1", "q2", "q3"], scored, registry.LAUNCH_APPEND)
        # q1 done in both -> not pending; q2 done in Smart, pending in Pro; q3 pending in both.
        self.assertEqual(plan["Smart"], ["q3"])
        self.assertEqual(sorted(plan["Pro"]), ["q2", "q3"])

    def test_append_includes_redo_in_every_mode(self):
        e = _entity(benchmark_id="B1", modes=["Smart", "Pro"], redo=["q1"])
        scored = [_scored("B1", "q1", mode="Smart"), _scored("B1", "q1", mode="Pro")]
        plan = registry.resolve_to_run(e, ["q1"], scored, registry.LAUNCH_APPEND)
        self.assertEqual(plan["Smart"], ["q1"])
        self.assertEqual(plan["Pro"], ["q1"])

    def test_full_runs_every_member_every_mode(self):
        e = _entity(benchmark_id="B1", modes=["Smart", "Pro"])
        plan = registry.resolve_to_run(e, ["q1", "q2"], [], registry.LAUNCH_FULL)
        self.assertEqual(plan["Smart"], ["q1", "q2"])
        self.assertEqual(plan["Pro"], ["q1", "q2"])

    def test_default_mode_when_modes_empty(self):
        e = _entity(benchmark_id="B1", modes=[])
        plan = registry.resolve_to_run(e, ["q1"], [], registry.LAUNCH_APPEND)
        self.assertEqual(list(plan.keys()), ["default"])
        self.assertEqual(plan["default"], ["q1"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m unittest benchmark.tests.test_registry -v`
Expected: FAIL (`done_cells` not defined / `resolve_to_run` returns a list).

- [ ] **Step 3: Implement** in `registry.py` (replace the old `done_question_ids` + `resolve_to_run`):

```python
DEFAULT_MODE = "default"


def done_cells(scored_rows, benchmark_id, agent_key=None):
    """Set of (question_id, mode) cells with >=1 scored attempt in this benchmark. Pure, never raises."""
    bid = _clean(benchmark_id)
    akey = _clean(agent_key)
    out = set()
    for r in (scored_rows or []):
        if not isinstance(r, dict):
            continue
        if _clean(r.get("benchmark_id")) != bid:
            continue
        if akey and _clean(r.get("agent_key")) != akey:
            continue
        qid = _clean(r.get("question_id"))
        if qid:
            out.add((qid, _clean(r.get("mode"))))
    return out


def _entity_modes(entity):
    """The benchmark's run modes; falls back to [DEFAULT_MODE] when empty (a single plain call)."""
    modes = [m for m in (entity.get("modes") or []) if _clean(m)]
    return modes or [DEFAULT_MODE]


def resolve_to_run(entity, golden_agent_active_ids, scored_rows, launch_mode=LAUNCH_APPEND):
    """Per-mode plan {mode: [question_id,...]} for one launch of ``entity``. Pure, never raises.

    members = the agent's active tagged golden ids (the caller filters golden by agent_key + active),
    in the given order. ``full`` runs every (member, mode); ``append`` runs every (member, mode) cell
    not yet done, UNION every (member, mode) where the member is flagged ``redo``.
    """
    if not isinstance(entity, dict):
        return {}
    members = [_clean(q) for q in (golden_agent_active_ids or []) if _clean(q)]
    modes = _entity_modes(entity)
    mode_norm = _clean(launch_mode).lower()
    if mode_norm == LAUNCH_FULL:
        return {m: list(members) for m in modes}
    done = done_cells(scored_rows, entity.get("benchmark_id"), entity.get("agent_key"))
    redo = set(entity.get("redo") or [])
    plan = {}
    for m in modes:
        plan[m] = [q for q in members if (q, m) not in done or q in redo]
    return plan
```

Also update `attempt_numbers` to keep working (it already keys `(qid, mode)` and reads scored; no change needed beyond confirming it is still present).

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m unittest benchmark.tests.test_registry -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add OWIsMind_LAB/project-library/python/benchmark/registry.py OWIsMind_LAB/project-library/python/benchmark/tests/test_registry.py
git commit -m "feat(benchmark): per-mode launch resolution from agent-tagged golden"
```

---

### Task 5: run_params - global settings keys, retire membership category filter

**Files:**
- Modify: `OWIsMind_LAB/project-library/python/benchmark/run_params.py`
- Test: `OWIsMind_LAB/project-library/python/benchmark/tests/test_run_params.py`

**Interfaces:**
- Produces: `resolve(vars)` keeps `golden_dataset`, `raw_dataset`, `scored_dataset`, `summary_dataset`, `breakdown_dataset`, `judge_llm_id`, `concurrency`, `language`, `per_call_timeout_s`, `history_keep_runs`, `agents`, `benchmarks`, `run_request`, `suggestions`. `question_filter` is still parsed (tolerated) but documented as no longer used for membership.

- [ ] **Step 1: Write the failing test** in `test_run_params.py` (append):

```python
def test_settings_keys_present(self):
    cfg = run_params.resolve({"benchmark": {"golden_dataset": "g", "judge_llm_id": "j",
                                            "concurrency": 5, "language": "en"}})
    self.assertEqual(cfg["golden_dataset"], "g")
    self.assertEqual(cfg["judge_llm_id"], "j")
    self.assertEqual(cfg["concurrency"], 5)
    self.assertEqual(cfg["language"], "en")
```

- [ ] **Step 2: Run to verify it fails or passes**

Run: `python3 -m unittest benchmark.tests.test_run_params -v`
Expected: PASS already if these keys exist (they do). If PASS, this task is a documentation-only change: proceed to Step 3 to update the docstring note, then commit. The test guards against regression.

- [ ] **Step 3: Implement** - in `run_params.py` update the `question_filter` docstring line to:

```python
      "question_filter": {},  // legacy: tolerated but no longer used for membership (auto-derived
                              // from the golden agent_key tag); kept only for back-compat reads.
```

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m unittest benchmark.tests.test_run_params -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add OWIsMind_LAB/project-library/python/benchmark/run_params.py OWIsMind_LAB/project-library/python/benchmark/tests/test_run_params.py
git commit -m "chore(benchmark): document settings keys; retire category filter for membership"
```

---

# PHASE 2 - Step engine

### Task 6: step_run_matrix per-mode plan + agent-tagged membership

**Files:**
- Modify: `OWIsMind_LAB/project-library/python/benchmark/dss_steps/step_run_matrix.py`

**Interfaces:**
- Consumes: `registry.resolve_to_run(entity, golden_agent_active_ids, prior_scored, launch_mode) -> {mode: [qid]}`; `schemas.normalize_golden_row` now carries `agent_key`.
- Produces: appends raw rows for exactly the resolved (question, mode) cells; stamps `agent_key_tag` from the golden row.

This step runs inside DSS (needs `dataiku` + `pandas`), so it is verified on the instance, not by a unit test. The pure resolution it relies on is fully tested in Task 4.

- [ ] **Step 1: Edit `run()`** - replace the membership + run block. After loading golden rows, filter to the entity's agent tag:

```python
    golden_rows = _load_golden_rows(cfg["golden_dataset"])
    bench_agent_key = entity.get("agent_key")
    golden_by_id = {}
    golden_agent_active_ids = []
    for r in golden_rows:
        qid = r.get("question_id")
        if not qid:
            continue
        golden_by_id[qid] = r
        if (r.get("agent_key") or None) == bench_agent_key:
            golden_agent_active_ids.append(qid)  # active is already filtered in _load_golden_rows
```

Replace `to_run_ids = registry.resolve_to_run(...)` and the empty-check with the per-mode plan:

```python
    prior = read_history_rows(cfg["raw_dataset"], columns=_RESOLVER_COLUMNS)
    plan = registry.resolve_to_run(entity, golden_agent_active_ids, prior, launch_mode)
    total_cells = sum(len(qids) for qids in plan.values())
    if total_cells == 0:
        raise ValueError(
            "nothing to run for benchmark {0!r} ({1}): every (question, mode) cell is already done. "
            "Use the full re-run, tag more questions to this agent, or flag some 'redo at next run'."
            .format(entity.get("name") or benchmark_id, launch_mode)
        )
    attempt_map = registry.attempt_numbers(prior, benchmark_id, bench_agent_key)
```

Replace the single `run_matrix` call with a per-mode loop (the runner stays unchanged; we call it once per mode with that mode's questions and a single-mode list):

```python
    project = dataiku.api_client().get_project(agent["project_key"])
    bench_name = entity.get("name") or ""
    collected = []

    def write_row(raw):
        raw["benchmark_id"] = benchmark_id
        raw["benchmark_name"] = bench_name
        raw["attempt_no"] = registry.next_attempt_no(attempt_map, raw.get("question_id"), raw.get("mode"))
        # carry the golden agent tag for display/breakdown (distinct from the runner's agent_key col)
        gq = golden_by_id.get(raw.get("question_id")) or {}
        raw["agent_key_tag"] = gq.get("agent_key")
        collected.append(raw)

    for mode, qids in plan.items():
        questions = [golden_by_id[qid] for qid in qids if qid in golden_by_id]
        if not questions:
            continue
        run_config = {
            "run_id": run_id,
            "run_timestamp": run_timestamp,
            "project": project,
            "agents": [agent],
            "modes": [mode],
            "language": cfg["language"],
            "concurrency": cfg["concurrency"],
            "per_call_timeout_s": cfg["per_call_timeout_s"],
            "questions": questions,
        }
        print("benchmark: run {0} benchmark {1!r} mode {2} - {3} question(s)".format(
            run_id, bench_name, mode, len(questions)))
        agent_runner.run_matrix(run_config, write_row)
```

Note for the implementer: `_benchmark_agent(entity)` still derives the agent descriptor + the `supports` bool; keep it. When `supports` is False the entity.modes is `[]`, the plan key is `"default"`, and the runner produces a `"default"` mode row, consistent with `registry.DEFAULT_MODE`.

- [ ] **Step 2: Static check** - run a syntax compile:

Run: `python3 -c "import ast; ast.parse(open('OWIsMind_LAB/project-library/python/benchmark/dss_steps/step_run_matrix.py').read())"`
Expected: no output (parses).

- [ ] **Step 3: Run the whole Python suite** to confirm nothing imports-broke:

Run: `python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python`
Expected: OK.

- [ ] **Step 4: Commit**

```bash
git add OWIsMind_LAB/project-library/python/benchmark/dss_steps/step_run_matrix.py
git commit -m "feat(benchmark): step runs per-mode plan from agent-tagged golden"
```

---

# PHASE 3 - Pure webapp view-models (`benchmark_webapp/views.py`)

> Each task here is a pure function + a unit test in `test_views.py`. Read the existing `test_views.py` header for the fixture style and import (`from benchmark_webapp import views`).

### Task 7: agent_benchmarks_view

**Files:**
- Modify: `OWIsMind_LAB/project-library/python/benchmark_webapp/views.py`
- Test: `OWIsMind_LAB/project-library/python/benchmark_webapp/tests/test_views.py`

**Interfaces:**
- Consumes: `registry.done_cells`, `schemas.effective_correct`.
- Produces: `agent_benchmarks_view(registry, agent_key, golden_rows, scored_rows, summary_rows=None) -> {"agent_key", "n_tagged", "benchmarks": [ {benchmark_id, name, modes, n_questions, n_cells, n_tested, n_pending, n_redo, last_run_timestamp, accuracy_pct} ]}`. `n_questions` = active golden tagged to the agent; `n_cells` = n_questions x len(modes); status counts derived from `done_cells`; `accuracy_pct` from `summary_rows` if present else recomputed from scored latest-attempt effective_correct; archived benchmarks excluded.

- [ ] **Step 1: Write the failing test** in `test_views.py`:

```python
def test_agent_benchmarks_view_counts(self):
    golden = [
        {"question_id": "q1", "agent_key": "rev", "active": True},
        {"question_id": "q2", "agent_key": "rev", "active": True},
        {"question_id": "q3", "agent_key": "tic", "active": True},
        {"question_id": "q4", "agent_key": "rev", "active": False},
    ]
    reg = {"B1": {"benchmark_id": "B1", "name": "Base", "agent_key": "rev",
                  "modes": ["Smart", "Pro"], "status": "active", "redo": ["q2"]}}
    scored = [{"benchmark_id": "B1", "question_id": "q1", "mode": "Smart", "agent_key": "rev",
               "correct": True, "attempt_no": 1, "run_timestamp": "2026-06-30T01:00:00Z",
               "run_id": "r1"}]
    out = views.agent_benchmarks_view(reg, "rev", golden, scored)
    self.assertEqual(out["n_tagged"], 2)               # q1, q2 active+rev
    b = out["benchmarks"][0]
    self.assertEqual(b["n_questions"], 2)
    self.assertEqual(b["n_cells"], 4)                  # 2 questions x 2 modes
    self.assertEqual(b["n_tested"], 1)                 # (q1,Smart)
    self.assertEqual(b["n_pending"], 3)                # 4 - 1
    self.assertEqual(b["n_redo"], 1)                   # q2 flagged
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m unittest benchmark_webapp.tests.test_views -v`
Expected: FAIL.

- [ ] **Step 3: Implement** in `views.py`:

```python
from benchmark import registry as _registry
from benchmark import schemas as _schemas


def _agent_tagged_active_ids(golden_rows, agent_key):
    """Ordered active golden question_ids tagged to ``agent_key``. Pure."""
    out = []
    for g in (golden_rows or []):
        if not isinstance(g, dict):
            continue
        if not _schemas._as_bool(g.get("active"), default=True):
            continue
        if (g.get("agent_key") or None) == (agent_key or None):
            qid = g.get("question_id")
            if qid:
                out.append(qid)
    return out


def agent_benchmarks_view(registry, agent_key, golden_rows, scored_rows, summary_rows=None):
    """Per-agent benchmark list with derived status counts. Pure, never raises."""
    member_ids = _agent_tagged_active_ids(golden_rows, agent_key)
    benchmarks = []
    for entity in (registry or {}).values():
        if not isinstance(entity, dict):
            continue
        if (entity.get("agent_key") or None) != (agent_key or None):
            continue
        if (entity.get("status") or "active") == "archived":
            continue
        bid = entity.get("benchmark_id")
        modes = [m for m in (entity.get("modes") or []) if m] or [_registry.DEFAULT_MODE]
        done = _registry.done_cells(scored_rows, bid, agent_key)
        n_cells = len(member_ids) * len(modes)
        n_tested = sum(1 for q in member_ids for m in modes if (q, m) in done)
        redo = set(entity.get("redo") or [])
        benchmarks.append({
            "benchmark_id": bid,
            "name": entity.get("name"),
            "modes": modes,
            "n_questions": len(member_ids),
            "n_cells": n_cells,
            "n_tested": n_tested,
            "n_pending": n_cells - n_tested,
            "n_redo": sum(1 for q in member_ids if q in redo),
            "last_run_timestamp": _last_run_ts(scored_rows, bid),
            "accuracy_pct": _accuracy_pct(summary_rows, scored_rows, bid),
        })
    benchmarks.sort(key=lambda b: (b.get("name") or "").lower())
    return {"agent_key": agent_key, "n_tagged": len(member_ids), "benchmarks": benchmarks}
```

Add the two small helpers `_last_run_ts(scored_rows, benchmark_id)` (max `run_timestamp` among rows of that benchmark, or None) and `_accuracy_pct(summary_rows, scored_rows, benchmark_id)` (prefer a summary row's accuracy; else compute over latest-attempt `effective_correct` per (question, mode); None when nothing tested). Implement both as straightforward pure reductions.

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m unittest benchmark_webapp.tests.test_views -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add OWIsMind_LAB/project-library/python/benchmark_webapp/views.py OWIsMind_LAB/project-library/python/benchmark_webapp/tests/test_views.py
git commit -m "feat(webapp): agent_benchmarks_view with derived per-mode counts"
```

---

### Task 8: benchmark_detail_view (per-mode question rows + ledger + runnable)

**Files:**
- Modify: `views.py`
- Test: `test_views.py`

**Interfaces:**
- Produces: `benchmark_detail_view(entity, golden_rows, scored_rows) -> {benchmark_id, name, agent{agent_key,agent_label,project_key,agent_id}, modes, ledger:{tested,pending,redo}, runnable, accuracy_pct, questions:[{question_id, question, category, expected_sql, expected_tool, redo, cells:[{mode, status, verdict}]}]}`. `status` in each cell is `"tested"` or `"pending"`; `verdict` is `"OK"`/`"MISS"`/None (latest-attempt effective_correct for that cell). `runnable` = pending cells + (redo question cells across modes not already pending). Replaces the old `benchmark_detail_view`.

- [ ] **Step 1: Write the failing test** in `test_views.py`:

```python
def test_benchmark_detail_view_cells_and_runnable(self):
    golden = [{"question_id": "q1", "question": "Q one", "agent_key": "rev", "active": True,
               "category": "rev", "expected_sql": "select 1", "expected_tool": "show_table"},
              {"question_id": "q2", "question": "Q two", "agent_key": "rev", "active": True}]
    entity = {"benchmark_id": "B1", "name": "Base", "agent_key": "rev",
              "agent_label": "Revenue", "project_key": "P", "agent_id": "agent:x",
              "modes": ["Smart", "Pro"], "status": "active", "redo": ["q1"]}
    scored = [{"benchmark_id": "B1", "question_id": "q1", "mode": "Smart", "agent_key": "rev",
               "correct": True, "attempt_no": 1, "run_timestamp": "2026-06-30T01:00:00Z", "run_id": "r1"}]
    out = views.benchmark_detail_view(entity, golden, scored)
    self.assertEqual(out["ledger"]["tested"], 1)
    self.assertEqual(out["ledger"]["pending"], 3)
    self.assertEqual(out["ledger"]["redo"], 1)
    # runnable = 3 pending + q1's tested cell pulled back by redo (q1,Smart) -> 4
    self.assertEqual(out["runnable"], 4)
    q1 = next(q for q in out["questions"] if q["question_id"] == "q1")
    smart = next(c for c in q1["cells"] if c["mode"] == "Smart")
    self.assertEqual(smart["status"], "tested")
    self.assertEqual(smart["verdict"], "OK")
    self.assertTrue(q1["redo"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m unittest benchmark_webapp.tests.test_views -v`
Expected: FAIL.

- [ ] **Step 3: Implement** `benchmark_detail_view` in `views.py`:

```python
def _latest_cell_verdict(scored_rows, benchmark_id, question_id, mode):
    """Latest-attempt effective verdict for a (benchmark, question, mode) cell, or None if untested."""
    best = None
    for r in (scored_rows or []):
        if not isinstance(r, dict):
            continue
        if r.get("benchmark_id") != benchmark_id or r.get("question_id") != question_id:
            continue
        if (r.get("mode") or "") != (mode or ""):
            continue
        key = (_int(r.get("attempt_no"), 0), str(r.get("run_timestamp") or ""))
        if best is None or key > best[0]:
            best = (key, r)
    if best is None:
        return None
    return "OK" if _schemas.effective_correct(best[1])["correct"] else "MISS"


def benchmark_detail_view(entity, golden_rows, scored_rows):
    entity = entity if isinstance(entity, dict) else {}
    bid = entity.get("benchmark_id")
    agent_key = entity.get("agent_key")
    modes = [m for m in (entity.get("modes") or []) if m] or [_registry.DEFAULT_MODE]
    redo = set(entity.get("redo") or [])
    members = [g for g in (golden_rows or [])
               if isinstance(g, dict) and _schemas._as_bool(g.get("active"), default=True)
               and (g.get("agent_key") or None) == (agent_key or None) and g.get("question_id")]
    questions, tested, runnable = [], 0, 0
    for g in members:
        qid = g.get("question_id")
        cells = []
        for m in modes:
            verdict = _latest_cell_verdict(scored_rows, bid, qid, m)
            is_tested = verdict is not None
            if is_tested:
                tested += 1
            if not is_tested or qid in redo:
                runnable += 1
            cells.append({"mode": m, "status": "tested" if is_tested else "pending",
                          "verdict": verdict})
        questions.append({
            "question_id": qid, "question": g.get("question"), "category": g.get("category"),
            "expected_sql": g.get("expected_sql"), "expected_tool": g.get("expected_tool"),
            "redo": qid in redo, "cells": cells,
        })
    n_cells = len(members) * len(modes)
    return {
        "benchmark_id": bid, "name": entity.get("name"),
        "agent": {"agent_key": agent_key, "agent_label": entity.get("agent_label"),
                  "project_key": entity.get("project_key"), "agent_id": entity.get("agent_id")},
        "modes": modes,
        "ledger": {"tested": tested, "pending": n_cells - tested,
                   "redo": sum(1 for q in members if q.get("question_id") in redo)},
        "runnable": runnable,
        "accuracy_pct": _accuracy_pct(None, scored_rows, bid),
        "questions": questions,
    }
```

(Reuse the existing `_int` helper in `views.py`; if absent, add a small `_int(value, default)`.)

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m unittest benchmark_webapp.tests.test_views -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add OWIsMind_LAB/project-library/python/benchmark_webapp/views.py OWIsMind_LAB/project-library/python/benchmark_webapp/tests/test_views.py
git commit -m "feat(webapp): benchmark_detail_view with per-mode cells, ledger, runnable"
```

---

### Task 9: golden_tag_view, validate_benchmark_name (per agent), build_launch_request, settings_view + validate_settings

**Files:**
- Modify: `views.py`
- Test: `test_views.py`

**Interfaces:**
- Produces:
  - `golden_tag_view(golden_rows, agent_key=None, scope="this") -> {"rows": [...]}` filtering by scope (`"this"` = tagged to agent_key, `"untagged"` = blank tag, `"all"`), each row carrying `question_id, question, reference_answer, expected_value, expected_value_type, category, language, active, notes, expected_sql, expected_tool, agent_key`.
  - `validate_benchmark_name(name, taken_names) -> (ok, error)` (already exists in registry; re-export or wrap). Use `registry.validate_benchmark_name`.
  - `build_launch_request(benchmark_id, launch_mode) -> {"benchmark_id", "launch_mode", "requested_at": None}` (the caller stamps the timestamp).
  - `settings_view(cfg) -> {golden_dataset, judge_llm_id, concurrency, language, raw_dataset, scored_dataset, summary_dataset, breakdown_dataset}`.
  - `validate_settings(form) -> (ok, normalized_or_errors)`: golden_dataset non-blank; concurrency int 1..8; language in (en,fr); dataset names non-blank; returns the normalized dict or a list of error strings.

- [ ] **Step 1: Write failing tests** in `test_views.py`:

```python
def test_golden_tag_view_scope(self):
    golden = [{"question_id": "q1", "agent_key": "rev", "active": True},
              {"question_id": "q2", "agent_key": None, "active": True},
              {"question_id": "q3", "agent_key": "tic", "active": True}]
    self.assertEqual([r["question_id"] for r in views.golden_tag_view(golden, "rev", "this")["rows"]], ["q1"])
    self.assertEqual([r["question_id"] for r in views.golden_tag_view(golden, "rev", "untagged")["rows"]], ["q2"])
    self.assertEqual(len(views.golden_tag_view(golden, "rev", "all")["rows"]), 3)

def test_validate_settings(self):
    ok, norm = views.validate_settings({"golden_dataset": "g", "judge_llm_id": "j",
                                        "concurrency": "5", "language": "en",
                                        "raw_dataset": "r", "scored_dataset": "s",
                                        "summary_dataset": "su", "breakdown_dataset": "b"})
    self.assertTrue(ok, norm)
    self.assertEqual(norm["concurrency"], 5)
    ok2, errs = views.validate_settings({"golden_dataset": "  ", "language": "xx"})
    self.assertFalse(ok2)
```

- [ ] **Step 2: Run to verify it fails**

Run: `python3 -m unittest benchmark_webapp.tests.test_views -v`
Expected: FAIL.

- [ ] **Step 3: Implement** the four functions in `views.py` (straightforward pure shaping/validation following the signatures above; reuse `registry.validate_benchmark_name`). Keep them small and never-raising.

- [ ] **Step 4: Run to verify it passes**

Run: `python3 -m unittest benchmark_webapp.tests.test_views -v`
Expected: PASS.

- [ ] **Step 5: Remove the obsolete config builder** - delete `build_config_object` and any `config_view` membership pieces no longer referenced; run the full Python suite and fix any import errors in `dss.py` / `backend.py` (they are rewired in Phases 4-5).

Run: `python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python`
Expected: OK (after Phase 4-5 are done; if running this task standalone, leave `build_config_object` until Task 15 removes its caller, then delete - note the ordering).

- [ ] **Step 6: Commit**

```bash
git add OWIsMind_LAB/project-library/python/benchmark_webapp/views.py OWIsMind_LAB/project-library/python/benchmark_webapp/tests/test_views.py
git commit -m "feat(webapp): golden tag view, settings view+validate, launch request"
```

---

# PHASE 4 - DSS I/O (`benchmark_webapp/dss.py`)

> These functions touch dataiku and are verified on the instance; unit-test the pure branches where feasible by injecting fakes. Every variable mutation goes through `_REGISTRY_LOCK` + read-modify-write of the `benchmark` variable.

### Task 10: Registry mutation helpers (create, delete, set_modes, set_redo)

**Files:**
- Modify: `OWIsMind_LAB/project-library/python/benchmark_webapp/dss.py`

**Interfaces:**
- Consumes: `registry.create_benchmark/delete_benchmark/rename_benchmark/set_redo`, `views.validate_benchmark_name`, `registry.names_for_agent`.
- Produces: `create_benchmark(name, agent, modes, created_by) -> {ok|error, benchmark_id}`; `delete_benchmark(benchmark_id)`; `set_benchmark_modes(benchmark_id, modes)`; `set_question_redo(benchmark_id, question_id, value)`. All under `_REGISTRY_LOCK`, read-modify-write via the existing `read_raw_benchmark_var` / `_persist_registry` / `write_benchmark_var`. Mint id with `uuid.uuid4().hex`; timestamp with `datetime.now().isoformat()`.

- [ ] **Step 1** Implement `create_benchmark` (no question seed; gate handled in the route via the golden tagged count; here just validate the name per agent):

```python
def create_benchmark(name, agent, modes, created_by=""):
    with _REGISTRY_LOCK:
        raw = read_raw_benchmark_var()
        reg = registry.parse_registry(raw.get("benchmarks"))
        ok, err = views.validate_benchmark_name(name, registry.names_for_agent(reg, agent.get("agent_key")))
        if not ok:
            return {"status": "error", "error": err}
        bid = uuid.uuid4().hex
        reg = registry.create_benchmark(reg, bid, name, agent, modes, datetime.now().isoformat(), created_by)
        _persist_registry(raw, reg)
        return {"status": "ok", "benchmark_id": bid}
```

- [ ] **Step 2** Implement `delete_benchmark`, `set_benchmark_modes`, `set_question_redo` with the same RMW shape (parse, mutate via the registry function, `_persist_registry`).

- [ ] **Step 3** Static check: `python3 -c "import ast; ast.parse(open('OWIsMind_LAB/project-library/python/benchmark_webapp/dss.py').read())"`

- [ ] **Step 4: Commit**

```bash
git add OWIsMind_LAB/project-library/python/benchmark_webapp/dss.py
git commit -m "feat(webapp/dss): benchmark create/delete/modes/redo under registry lock"
```

---

### Task 11: Agent discovery (best-effort, cached) + connect

**Files:**
- Modify: `dss.py`

**Interfaces:**
- Produces: `discover_agents() -> {"status", "agents": [...], "discovery": "ok"|"unavailable"}` (best-effort enumerate agents across accessible DSS projects; on any exception degrade to the cached catalog + `discovery: "unavailable"`); writes the discovered catalog into the variable (`agents`) with a `discovered_at`. `connect_agent(agent_key, agent_label, project_key, agent_id, modes)` -> upsert one catalog entry (RMW). `agents_catalog() -> list` reads the cached catalog (no discovery call).

- [ ] **Step 1** Implement `agents_catalog()` (read-only, from the variable). Implement `connect_agent(...)` (RMW upsert into `agents` by `agent_key`).

- [ ] **Step 2** Implement `discover_agents()` best-effort. VERIFY ON INSTANCE the exact API (section 15 of the spec). Use a guarded call shaped like:

```python
def discover_agents():
    try:
        client = dataiku.api_client()
        found = []
        for pkey in _accessible_project_keys(client):
            try:
                project = client.get_project(pkey)
                for llm in project.list_llms():            # confirm the listing API on the instance
                    lid = getattr(llm, "id", None) or (llm.get("id") if isinstance(llm, dict) else None)
                    if lid and str(lid).startswith("agent:"):
                        label = _llm_label(llm) or str(lid)
                        found.append({"project_key": pkey, "agent_id": str(lid),
                                      "agent_label": label,
                                      "agent_key": registry.slug_agent_key(label), "modes": True})
            except Exception:
                continue
        with _REGISTRY_LOCK:
            raw = read_raw_benchmark_var()
            raw["agents"] = found
            raw["agents_discovered_at"] = datetime.now().isoformat()
            write_benchmark_var(raw)
        return {"status": "ok", "discovery": "ok", "agents": found}
    except Exception:
        return {"status": "ok", "discovery": "unavailable", "agents": agents_catalog()}
```

Implement `_accessible_project_keys(client)` (best-effort `client.list_project_keys()`), `_llm_label(llm)` (best-effort label getter). If `list_llms` is not the right call on this instance, the except path keeps the manual catalog working (the fallback is the contract).

- [ ] **Step 3** Static check parse. Commit:

```bash
git add OWIsMind_LAB/project-library/python/benchmark_webapp/dss.py
git commit -m "feat(webapp/dss): best-effort cached agent discovery + manual connect"
```

---

### Task 12: Golden agent_key write + column bootstrap; settings get/set + schema validation; run reset; redo reconcile

**Files:**
- Modify: `dss.py`

**Interfaces:**
- Produces:
  - `save_golden_question(row)` / `delete_golden_question(qid)` now carry `agent_key`, `expected_sql`, `expected_tool`; before writing, if the golden dataset schema lacks `agent_key`, evolve the schema to add it (`_ensure_golden_agent_key_column`).
  - `read_settings()` / `save_settings(form)` -> read/RMW the global keys (golden_dataset, judge_llm_id, concurrency, language, the 4 dataset names); `save_settings` validates with `views.validate_settings` then validates the golden dataset SCHEMA via `_validate_golden_dataset(name)` (exists + has `question` + `reference_answer`; bootstrap `agent_key` if missing); returns inline errors, never auto-creates.
  - `reset_run_request()` -> clear `run_request` only when the scenario is verifiably idle (`last_status` not running); returns `{ok}` or `{error: "run_active"}`.
  - `reconcile_redo_after_run(benchmark_id, run_id)` -> after a run finishes, `reset_redo_for` the questions that now have a scored row for `run_id` (idempotent), under the lock.

- [ ] **Step 1** Implement `_ensure_golden_agent_key_column(dataset_name)` using the Dataiku Dataset schema API (best-effort, idempotent): read the schema, if no `agent_key` column, append `{"name": "agent_key", "type": "string"}` and save the schema. VERIFY ON INSTANCE.

- [ ] **Step 2** Wire `save_golden_question` / `delete_golden_question` to carry the new columns and call `_ensure_golden_agent_key_column` before the write.

- [ ] **Step 3** Implement `read_settings` / `save_settings` (RMW), `_validate_golden_dataset`, `reset_run_request`, `reconcile_redo_after_run`.

- [ ] **Step 4** Static check + run the Python suite. Commit:

```bash
git add OWIsMind_LAB/project-library/python/benchmark_webapp/dss.py
git commit -m "feat(webapp/dss): golden tag write+bootstrap, settings, run reset, redo reconcile"
```

---

# PHASE 5 - Backend routes

### Task 13: Rewire `backend.py` to the new model

**Files:**
- Modify: `OWIsMind_LAB/webapps/benchmark_launcher/backend.py`

**Interfaces:**
- Produces these routes (all `@_safe`, JSON): `GET /api/agents`, `POST /api/agents/discover`, `POST /api/agents/connect`, `GET /api/agent/benchmarks?agent_key=`, `POST /api/benchmark/create`, `POST /api/benchmark/delete`, `POST /api/benchmark/modes`, `POST /api/benchmark/redo`, `POST /api/benchmark/launch`, `POST /api/run/reset`, `GET /api/run/status`, `GET /api/benchmark/detail?benchmark_id=`, `GET /api/golden?agent_key=&scope=`, `POST /api/golden/save`, `POST /api/golden/delete`, `GET /api/settings`, `POST /api/settings`. Keep `GET /api/suggestions`, `POST /api/suggestions/promote`, `GET /api/review`, `POST /api/override` unchanged. REMOVE `GET/POST /api/config`, `POST /api/run`, `POST /api/benchmark/archive`, `POST /api/benchmark/add-questions`, `POST /api/benchmark/remove-question`, `POST /api/benchmark/rename` (rename can stay if cheap; otherwise drop). 

Key wiring details:
- `POST /api/benchmark/create` reads `{name, agent_key, modes}`; resolves the agent from `dss.agents_catalog()` by `agent_key`; GATES on the golden tagged-active count for that agent (`views.agent_benchmarks_view(...).n_tagged > 0`, or a direct count) and returns `400 no_tagged_questions` if zero; snapshots `{agent_key, agent_label, project_key, agent_id}` onto the benchmark.
- `POST /api/benchmark/launch` reads `{benchmark_id, launch_mode}`; writes `run_request` via `views.build_launch_request` + a stamped timestamp; fires the single-flight scenario (the existing `RUN_LOCK` + DSS "Prevent concurrent executions"); does NOT clear redo here (reconciled post-run).
- `GET /api/run/status` returns scenario status + `scored / total` for the live run_id; on completion calls `dss.reconcile_redo_after_run`.
- `GET /api/agent/benchmarks` calls `views.agent_benchmarks_view(reg, agent_key, golden, scored, summary)`.

- [ ] **Step 1** Rewrite the route table per the interface above, deleting the removed routes. Each new route is a thin `_safe` wrapper delegating to a `dss.*` function and shaping the JSON.

- [ ] **Step 2** Static check: `python3 -c "import ast; ast.parse(open('OWIsMind_LAB/webapps/benchmark_launcher/backend.py').read())"`.

- [ ] **Step 3** Run the full Python suite (now that `build_config_object` and its caller are gone): `python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python`. Expected OK.

- [ ] **Step 4: Commit**

```bash
git add OWIsMind_LAB/webapps/benchmark_launcher/backend.py OWIsMind_LAB/project-library/python/benchmark_webapp/views.py
git commit -m "feat(launcher): agent-first backend routes (discover, agent benchmarks, create/delete/launch/reset, settings)"
```

---

# PHASE 6 - Launcher frontend

> The frontend is framework-free vanilla JS rendered into `#bench-app`. Extract the PURE derivations into `journey.js` (testable with `node --test`, no install); keep the DOM render in `script.js`. Charter + no-em-dash apply to EN and FR strings. These tasks are contract-driven: exact data shapes + microcopy come from the spec wireframes (section 5) and the route contracts above.

### Task 14: Pure journey helpers + tests

**Files:**
- Create: `OWIsMind_LAB/webapps/benchmark_launcher/journey.js`
- Create: `OWIsMind_LAB/webapps/benchmark_launcher/test/journey.test.js`
- Modify: `OWIsMind_LAB/webapps/benchmark_launcher/body.html` (load `journey.js` before `script.js`)

**Interfaces:**
- Produces (attached to `window.Journey` and `module.exports` for node): 
  - `runnableLabel(detail) -> {label, enabled, hint}` driving the `Run pending` button from the single `detail.runnable` + `detail.ledger`.
  - `benchmarkListState(agentView) -> "list" | "empty_has_questions" | "empty_no_questions"`.
  - `createGate(nTagged) -> {canCreate, primaryAction}` (canCreate=false, primaryAction="tag" when nTagged===0).
  - `cellChip(cell) -> {text, kind}` (`Pending` / `OK` / `MISS`).
  - `evolutionToken(prev, cur) -> "improved"|"regressed"|"same"|"new"`.

- [ ] **Step 1: Write the failing test** `test/journey.test.js`:

```js
const test = require("node:test");
const assert = require("node:assert");
const J = require("../journey.js");

test("runnableLabel armed when runnable > 0", () => {
  const r = J.runnableLabel({ runnable: 18, ledger: { tested: 0, pending: 18, redo: 0 } });
  assert.equal(r.enabled, true);
  assert.match(r.label, /18/);
});

test("runnableLabel disabled with reason when nothing runnable", () => {
  const r = J.runnableLabel({ runnable: 0, ledger: { tested: 18, pending: 0, redo: 0 } });
  assert.equal(r.enabled, false);
  assert.ok(r.hint.length > 0);
});

test("createGate locks when no tagged questions", () => {
  assert.deepEqual(J.createGate(0), { canCreate: false, primaryAction: "tag" });
  assert.equal(J.createGate(6).canCreate, true);
});

test("benchmarkListState", () => {
  assert.equal(J.benchmarkListState({ benchmarks: [{}], n_tagged: 6 }), "list");
  assert.equal(J.benchmarkListState({ benchmarks: [], n_tagged: 6 }), "empty_has_questions");
  assert.equal(J.benchmarkListState({ benchmarks: [], n_tagged: 0 }), "empty_no_questions");
});

test("evolutionToken", () => {
  assert.equal(J.evolutionToken("MISS", "OK"), "improved");
  assert.equal(J.evolutionToken("OK", "MISS"), "regressed");
  assert.equal(J.evolutionToken("OK", "OK"), "same");
  assert.equal(J.evolutionToken(null, "OK"), "new");
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd OWIsMind_LAB/webapps/benchmark_launcher && node --test test/`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** `journey.js` with the five pure functions and a UMD-ish export footer:

```js
(function (root, factory) {
  var api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.Journey = api;
})(typeof self !== "undefined" ? self : this, function () {
  function runnableLabel(detail) {
    var n = (detail && detail.runnable) || 0;
    if (n > 0) return { label: "Run pending (" + n + ")", enabled: true, hint: "" };
    return { label: "Run pending (0)", enabled: false,
             hint: "Nothing pending. Tag new questions to this agent, or flag a tested question to redo." };
  }
  function benchmarkListState(v) {
    var has = v && v.benchmarks && v.benchmarks.length > 0;
    if (has) return "list";
    return (v && v.n_tagged > 0) ? "empty_has_questions" : "empty_no_questions";
  }
  function createGate(nTagged) {
    return nTagged > 0 ? { canCreate: true, primaryAction: "create" }
                       : { canCreate: false, primaryAction: "tag" };
  }
  function cellChip(cell) {
    if (!cell || cell.status !== "tested") return { text: "Pending", kind: "pending" };
    return cell.verdict === "OK" ? { text: "OK", kind: "ok" } : { text: "MISS", kind: "miss" };
  }
  function evolutionToken(prev, cur) {
    if (prev == null) return "new";
    if (prev === cur) return "same";
    if (prev === "MISS" && cur === "OK") return "improved";
    if (prev === "OK" && cur === "MISS") return "regressed";
    return "same";
  }
  return { runnableLabel: runnableLabel, benchmarkListState: benchmarkListState,
           createGate: createGate, cellChip: cellChip, evolutionToken: evolutionToken };
});
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd OWIsMind_LAB/webapps/benchmark_launcher && node --test test/`
Expected: PASS.

- [ ] **Step 5** In `body.html`, add before the `script.js` tag: `<script src="journey.js"></script>` (so `window.Journey` is available). Commit:

```bash
git add OWIsMind_LAB/webapps/benchmark_launcher/journey.js OWIsMind_LAB/webapps/benchmark_launcher/test/journey.test.js OWIsMind_LAB/webapps/benchmark_launcher/body.html
git commit -m "feat(launcher): pure journey helpers (runnable, gating, cells, evolution) + node:test"
```

---

### Task 15: Shell - agents rail master-detail, breadcrumb, footer, getting-started strip

**Files:**
- Modify: `OWIsMind_LAB/webapps/benchmark_launcher/script.js`, `style.css`

**Interfaces:**
- Consumes: `GET /api/agents`, `POST /api/agents/discover`, `window.Journey`.
- Produces: a state `S = { route: {level: "home"|"agent"|"benchmark", agentKey, benchmarkId}, agents, agentView, detail, settingsOpen }`; a left AGENTS rail + a right detail panel + a breadcrumb + the always-on data-location footer + the self-erasing Getting Started strip. Header links `Golden / Suggestions / Review`, `EN | FR`, gear.

- [ ] **Step 1** Replace the tab nav with the master-detail shell. Render the rail from `S.agents` (discovery states 1a-1d from the spec wireframes), the footer with the exact copy from the spec section 4, and the Getting Started strip gated on `(no agent) || (agent n_tagged==0) || (0 benchmarks) || (0 runs)`. Selecting a rail row sets `S.route = {level:"agent", agentKey}` and loads the agent view.

- [ ] **Step 2** Fire discovery on first load ONCE (cached server-side); a `Refresh` button re-runs `POST /api/agents/discover`. Never call discover on every render.

- [ ] **Step 3** Manual verification in the DSS preview (`preview.html` MOCK or the deployed webapp): rail renders, footer present, breadcrumb updates. (No automated DOM test; the pure derivations are covered by Task 14.)

- [ ] **Step 4: Commit**

```bash
git add OWIsMind_LAB/webapps/benchmark_launcher/script.js OWIsMind_LAB/webapps/benchmark_launcher/style.css
git commit -m "feat(launcher): agents rail master-detail shell, breadcrumb, footer, getting-started"
```

---

### Task 16: Agent detail - benchmark list + empty states + create (gated)

**Files:**
- Modify: `script.js`, `style.css`

**Interfaces:**
- Consumes: `GET /api/agent/benchmarks?agent_key=`, `POST /api/benchmark/create`, `Journey.benchmarkListState`, `Journey.createGate`.
- Produces: Screen 2 (list, 2b empty-has-questions, 2c empty-no-questions with locked create), Screen 3 (inline create: agent locked, name, modes only, live pending reassurance). Create posts `{name, agent_key, modes}` then routes to the new benchmark detail.

- [ ] **Step 1** Render the three list states via `Journey.benchmarkListState`. In 2c, `New benchmark` is locked and `Tag questions` is the lit action (`Journey.createGate`).
- [ ] **Step 2** Render the create form (Screen 3 wireframe + microcopy). On submit, POST create, handle `400 no_tagged_questions` by swapping to the Tag action.
- [ ] **Step 3** Manual verification: empty states + create on the MOCK/preview.
- [ ] **Step 4: Commit**

```bash
git add OWIsMind_LAB/webapps/benchmark_launcher/script.js OWIsMind_LAB/webapps/benchmark_launcher/style.css
git commit -m "feat(launcher): agent benchmark list, empty states, gated create"
```

---

### Task 17: Benchmark detail - ledger, per-mode questions, run buttons, edit modes, delete

**Files:**
- Modify: `script.js`, `style.css`

**Interfaces:**
- Consumes: `GET /api/benchmark/detail?benchmark_id=`, `POST /api/benchmark/launch`, `POST /api/benchmark/modes`, `POST /api/benchmark/redo`, `POST /api/benchmark/delete`, `Journey.runnableLabel`, `Journey.cellChip`.
- Produces: Screen 4 (a-g). The primary button label + enabled + hint come from `Journey.runnableLabel(detail)` so they can never disagree. The questions table shows one `Journey.cellChip` per mode. `Edit` opens the modes-only editor (`POST /api/benchmark/modes`). `Delete` opens the named confirm (`POST /api/benchmark/delete`) then routes back to the agent list with a toast. Redo checkbox posts `POST /api/benchmark/redo` (immediate, server RMW under lock) and re-renders the ledger + button.

- [ ] **Step 1** Render Screen 4a-4d states. Drive the buttons from `Journey.runnableLabel`. Render per-mode chips.
- [ ] **Step 2** Wire Edit modes, Delete confirm, Redo toggle.
- [ ] **Step 3** Manual verification on the MOCK/preview: a freshly created benchmark shows `Run pending (N)` enabled (the dead-end is gone); all-tested shows the disabled button with its reason + orange Re-run.
- [ ] **Step 4: Commit**

```bash
git add OWIsMind_LAB/webapps/benchmark_launcher/script.js OWIsMind_LAB/webapps/benchmark_launcher/style.css
git commit -m "feat(launcher): benchmark detail (ledger, per-mode cells, run, edit modes, delete)"
```

---

### Task 18: Run lifecycle, golden tagging, settings, i18n, charter sweep

**Files:**
- Modify: `script.js`, `style.css`

**Interfaces:**
- Consumes: `GET /api/run/status`, `POST /api/run/reset`, `GET/POST /api/golden`, `GET/POST /api/settings`, `Journey.evolutionToken`.
- Produces: Screen 5 (progress `scored/total`, single-flight lock messaging, run-complete + re-run evolution, `Reset run state` when stuck), Screen 6 (golden tagging pre-filtered to the agent, agent_key dropdown + Active + full golden CRUD incl `expected_sql`/`expected_tool`), Screen 7 (Settings: golden dataset name editable + judge LLM + concurrency + run language + 4 dataset names + where-data-lives note). All EN strings plus FR equivalents in the `DICT`. Re-run shows a confirm panel with scope (questions x modes) before launch.

- [ ] **Step 1** Implement the run progress poll + states; add `Reset run state` wired to `POST /api/run/reset` (shown only when idle-but-run_request-set per the status payload).
- [ ] **Step 2** Implement the golden tagging screen (Screen 6) and Settings (Screen 7), including the golden-dataset-name field with the inline "not found / wrong schema" error from the save response.
- [ ] **Step 3** Add every new i18n key to `DICT` in BOTH `en` and `fr`. Add the re-run confirm panel.
- [ ] **Step 4: Charter + dash sweep.** Run a Python scan over the launcher files for em/en dashes:

Run: `python3 -c "import glob; [print(f) for f in glob.glob('OWIsMind_LAB/webapps/benchmark_launcher/*.js')+glob.glob('OWIsMind_LAB/webapps/benchmark_launcher/*.css')+glob.glob('OWIsMind_LAB/webapps/benchmark_launcher/*.html') if open(f,encoding='utf-8').read().count(chr(8212))+open(f,encoding='utf-8').read().count(chr(8211))]"`
Expected: no output (no file contains an em/en dash).

- [ ] **Step 5** Run the pure JS tests again to confirm no regression: `cd OWIsMind_LAB/webapps/benchmark_launcher && node --test test/`. Expected PASS.

- [ ] **Step 6: Commit**

```bash
git add OWIsMind_LAB/webapps/benchmark_launcher/script.js OWIsMind_LAB/webapps/benchmark_launcher/style.css
git commit -m "feat(launcher): run lifecycle, golden tagging, settings, FR i18n, charter sweep"
```

---

# PHASE 7 - Whole-suite gate + docs

### Task 19: Full suite, memory, deploy notes

**Files:**
- Modify: `OWIsMind_LAB/project-library/python/benchmark_webapp/DEPLOY_GUIDE.md` (or `OWIsMind_LAB/README.md`) with the new model + the verify-on-instance items.

- [ ] **Step 1** Run the full Python suite and the JS tests:

Run: `python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python && cd OWIsMind_LAB/webapps/benchmark_launcher && node --test test/`
Expected: all OK.

- [ ] **Step 2** Update the deploy guide: re-glue the lib (`benchmark/` + `benchmark_webapp/`) and the launcher webapp panes; add the golden `agent_key` column; reset the `benchmark` variable to `{ "benchmarks": {}, "run_request": null, "agents": [] }` + settings; the verify-on-instance items (discovery API, golden schema evolution, scenario async launch).

- [ ] **Step 3: Commit**

```bash
git add OWIsMind_LAB
git commit -m "docs(benchmark): deploy guide for the agent-first launcher journey"
```

---

## Self-Review (done at authoring time)

- Spec coverage: agent tag (Task 1), discovery + connect (Task 11, 15), auto-membership + per-mode resolve (Task 4, 6, 8), modes-only config (Task 10, 17), hard delete (Task 3, 10, 17), gated create (Task 13, 16), master-detail nav (Task 15-17), tested-derived (Task 8), settings + golden name editable (Task 9, 12, 18), stuck-run reset (Task 12, 18), golden schema validation + column bootstrap (Task 12), run-cost confirm (Task 18), cached discovery (Task 11, 15), footer/data-location (Task 15). All covered.
- Placeholder scan: I/O + frontend tasks intentionally specify contracts + key code rather than every DOM string (a full 143KB vanilla-JS rewrite is not line-spelled in a plan); the spec wireframes (section 5) are the binding microcopy source, referenced explicitly. Pure tasks carry complete code + tests.
- Type consistency: `agent_key` (logical) is the golden tag + benchmark match key throughout; the raw display column is `agent_key_tag` to avoid colliding with the runner `agent_key`; `resolve_to_run` returns `{mode: [qid]}` consistently across Task 4 (def), Task 6 (consumer), Task 8 (view). `runnable` is defined once (Task 8) and consumed by `Journey.runnableLabel` (Task 14).

## Verify on instance (carried from the spec, section 15)
- Agent discovery API (the exact `list_llms` / project enumeration on this instance); fallback = manual connect.
- Golden schema evolution to add `agent_key` via the Dataset API.
- Scenario async launch method used by the existing launcher.
