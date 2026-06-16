# =============================================================================
# OWIsMind — DATASET EXPERT AGENT (generic, Dataiku Code Agent)
# -----------------------------------------------------------------------------
# A dataset-agnostic sub-agent: point it at a PROFILE dataset (built by
# recipes/profile_dataset_recipe.py) and a VALUE INDEX dataset (built by
# recipes/build_value_index_recipe.py) and it becomes an expert of that
# dataset — it knows the columns, the metrics, the scenario values, the time
# coverage and the exact catalog values, and it answers questions by building
# and executing its OWN read-only SQL. No semantic-model tool, no black box.
#
# Architecture : UNDERSTAND -> RESOLVE -> BUILD SQL -> EXECUTE/REPAIR -> RENDER
#
#   1. UNDERSTAND  1 LLM call (strict JSON). The prompt is GENERATED from the
#                  profile: metrics, scenario values, axes, synonyms — so the
#                  same code understands any dataset.
#   2. RESOLVE     User terms are grounded against the value index by SQL
#                  (exact -> normalized -> fuzzy). Ambiguity policy and the
#                  "VALUE (Column)" round-trip are deterministic code.
#   3. BUILD SQL   Structured intents (total, breakdown, top_n, share_of_total,
#                  compare_scenarios, compare_periods, trend, list_values,
#                  count_distinct) -> DETERMINISTIC SQL templates (the LLM
#                  never writes that SQL). Long-tail "custom" intent -> LLM
#                  SQL constrained by the dataset card + SQL GUARD (single
#                  read-only SELECT on the one table, LIMIT enforced).
#   4. EXECUTE     SQLExecutor2 on the dataset's own connection, transaction
#                  forced read-only + statement_timeout (validated pattern).
#                  Custom SQL gets EXPLAIN dry-run + up to 2 repair attempts
#                  with the database error fed back to the LLM.
#   5. RENDER      Markdown table + figures formatted BY CODE; a small LLM
#                  writes only the headline and every number it cites is
#                  verified against the result — unverifiable -> deterministic
#                  fallback. "about_data" questions are answered from the
#                  profile with ZERO SQL and ZERO hallucination surface.
#
# Collaboration contract with the orchestrator (unchanged dialect):
#   - AGENT_BLOCK_START blockIds: resolve, run_sql, format_output,
#     clarify_user, out_of_scope_msg, about_data.
#   - AGENT_TOOL_START toolNames: resolve_filter_value, dataset_sql_query.
#   - ONE final AGENT_RESULT event {status, language, intent, resolvedFilters,
#     sqlCount, rowCount, attempts} — status: ready | need_clarification |
#     out_of_scope | no_data | error.
#   - One trace subspan "semantic-model-query" PER EXECUTED SQL with outputs
#     {sql, success (REAL, observed), row_count} (+ rows/columns on the
#     successful one) — the orchestrator/webapp Evidence capture works as-is.
#
# Cornerstones (NON NEGOTIABLE, inherited from OWIsMind):
#   - NEVER invents a figure: every number shown comes from the SQL result
#     or the answer is refused/clarified.
#   - Refuse rather than hallucinate; unresolved terms -> ask, never guess.
#   - STANDALONE file: stdlib + dataiku + langgraph. Runs on the Python 3.11
#     code env (LangGraph needs >= 3.10). Pasted into a DSS Code Agent.
#   - LangGraph StateGraph (UNDERSTAND -> RESOLVE -> QUERY -> RENDER) on top of
#     the SAME engine functions; the validated linear original lives in git
#     history (commit before the LangGraph rework) for instant rollback.
# =============================================================================

import difflib
import json
import logging
import math
import re
import time
import unicodedata
from datetime import datetime

import dataiku
from dataiku.llm.python import BaseLLM

from typing import TypedDict

from langgraph.graph import StateGraph, START, END
from langgraph.config import get_stream_writer

logger = logging.getLogger("owismind.dataset_expert")

# =============================================================================
# 1. CONFIGURATION (fill before pasting into the DSS Code Agent)
# =============================================================================

# The two knowledge datasets produced by the Flow recipes:
PROFILE_DATASET = "DRIVE_Revenues_profile"
VALUE_INDEX_DATASET = "DRIVE_Revenues_value_index"
# Optional override of the queried dataset (default: profile's dataset_name).
TARGET_DATASET = ""

# LLM Mesh ids. UNDERSTAND runs on every question -> a fast, cheap model good at
# strict JSON. SQLGEN only runs on the long-tail "custom" intent. MODEL-AGNOSTIC:
# UNDERSTAND forces native JSON output (deterministic extraction -> reliable parse
# on any model). Default = Gemini 2.5 Flash (matches the orchestrator's fast tier).
# ⚠️ VERIFY this id matches your LLM Mesh connection (same note as the orchestrator).
# Fallbacks kept as named options: SONNET_ID (strongest), GPT_MINI_ID (cheapest).
GEMINI_FLASH_ID = "openai:LLM-7064-revforecast:vertex_ai/gemini-2.5-flash"  # <-- VERIFY
SONNET_ID = "openai:LLM-7064-revforecast:vertex_ai/claude-sonnet-4-6"
GPT_MINI_ID = "openai:LLM-7064-revforecast:openai/gpt-5.4-mini"
# Model tier per MODE (propagated by the orchestrator via the injected context).
# Mirrors the orchestrator: eco=mini (near-free), medium=Gemini Flash, high=Sonnet.
# So in HIGH mode the WHOLE stack is Sonnet: orchestrator + this sub-agent + (when a
# Sonnet-backed semantic tool id is set below) the semantic model.
LLM_BY_MODE = {"eco": GPT_MINI_ID, "medium": GEMINI_FLASH_ID, "high": SONNET_ID}
DEFAULT_MODE = "medium"
# Fallback ids when no mode is injected (batch / stand-alone use).
UNDERSTAND_LLM_ID = LLM_BY_MODE[DEFAULT_MODE]
SQLGEN_LLM_ID = LLM_BY_MODE[DEFAULT_MODE]
HEADLINE_LLM_ID = None             # None -> the run's mode-resolved model


def pick_subagent_llm(mode):
    """The sub-agent's own LLM (UNDERSTAND / SQLGEN / headline) for this mode."""
    return LLM_BY_MODE.get(mode, LLM_BY_MODE[DEFAULT_MODE])
# The orchestrator now writes the user-facing analysis, so the sub-agent's own
# LLM headline is redundant overhead (a slow extra reasoning call per query).
# Default OFF: return the deterministic fallback headline + data, and let the
# orchestrator comment. Set True only for stand-alone (no-orchestrator) use.
SUBAGENT_LLM_HEADLINE = False

# --- SQL engine --------------------------------------------------------------
# "semantic_tool" (DEFAULT — user decision 2026-06-12 after A/B testing in DSS):
#   the agent does UNDERSTAND + RESOLVE + COMPOSE, then delegates SQL
#   generation/execution to the DSS Semantic Model Query tool, feeding it a
#   maximally grounded question (exact catalog values, explicit scenarios and
#   periods, axis rules, destination context). The semantic model owns the
#   SQL; every upstream layer exists to hand it the best possible context.
# "direct": the agent builds and runs its OWN read-only SQL (deterministic
#   templates + guarded LLM for the long tail).
# On a TECHNICAL semantic-tool failure the agent falls back to "direct" when
# FALLBACK_TO_DIRECT is True (a legit empty result is NOT a failure).
SQL_ENGINE = "semantic_tool"
FALLBACK_TO_DIRECT = True
SEMANTIC_TOOL_ID = "v4oqA6R"        # Semantic Model Query tool id (instance)
SEMANTIC_TOOL_NAME = "revenue_semantic_query"
SEMANTIC_QUESTION_KEY = "question"  # first candidate; auto-detected at runtime
# Semantic Model Query tool id PER MODE. The tool's underlying LLM is configured in
# DSS (not from code), so to get Sonnet on the semantic model in HIGH mode you create
# a second semantic-model tool backed by Sonnet and put its id under "high" below.
# Until then all modes share the one tool (the upstream grounding is identical).
SEMANTIC_TOOL_ID_BY_MODE = {"eco": SEMANTIC_TOOL_ID, "medium": SEMANTIC_TOOL_ID,
                            "high": SEMANTIC_TOOL_ID}  # <-- set a Sonnet-backed id for "high" if available


def pick_semantic_tool_id(mode):
    return SEMANTIC_TOOL_ID_BY_MODE.get(mode, SEMANTIC_TOOL_ID)

# --- Dataset Lookup tool (simple value retrieval, NO SQL) --------------------
# Dataiku managed "Dataset Lookup" tool: returns up to a few rows matching a
# column/operator/value filter — perfect for "who is the account manager of X?",
# "what's the carrier code of Y?". Reserve SQL (semantic tool) for aggregations,
# rankings, comparisons and calculations; use this for plain attribute lookups.
# The tool's input schema is auto-discovered from its descriptor (we only need
# the id). Set DATASET_LOOKUP_ENABLED = False to disable the lookup path entirely.
DATASET_LOOKUP_ENABLED = True
DATASET_LOOKUP_TOOL_ID = "9FEzVZk"          # instance id (points at the revenue dataset)
DATASET_LOOKUP_TOOL_NAME = "dataset_lookup"
DATASET_LOOKUP_MAX_ROWS = 10                # the tool caps at ~10 rows; mirror it

PROFILE_TTL_SECONDS = 600          # in-process profile cache
MAX_TERMS = 8                      # grounded terms per question
SQL_MAX_ROWS = 500                 # hard LIMIT on every query
LIST_VALUES_LIMIT = 200
TABLE_MAX_ROWS = 12                # rows displayed in the answer table
HEADLINE_MAX_CHARS = 400
MAX_CUSTOM_SQL_ATTEMPTS = 3        # 1 generation + up to 2 repairs
FUZZY_CANDIDATES_LIMIT = 40
FUZZY_MIN_RATIO = 0.62             # below -> unresolved (no best candidate)

# Read-only execution (pattern validated in DSS — evidence backend, L045).
SQL_PRE_QUERIES = ["SET LOCAL statement_timeout TO '30000'",
                   "SET LOCAL transaction_read_only TO on"]

# Result capture caps — mirrors of the orchestrator/webapp caps (standalone
# file; the webapp re-caps independently before persistence).
MAX_RESULT_ROWS = 50
MAX_RESULT_COLS = 50
_RESULT_CELL_MAX_CHARS = 256
_RESULT_JSON_MAX_CHARS = 64000

KNOWN_INTENTS = ("total", "breakdown", "top_n", "share_of_total",
                 "compare_scenarios", "compare_periods", "trend",
                 "list_values", "count_distinct", "about_data", "lookup", "custom")

NBSP = " "
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]*$")

# =============================================================================
# 2. USER-FACING TEXTS (deterministic, fr/en)
# =============================================================================

OUT_OF_SCOPE_TEXT = {
    "fr": ("Cette question sort du périmètre de données que je couvre "
           "({label}). Posez-moi une question sur ces données — je m'en occupe."),
    "en": ("This question is outside the data scope I cover ({label}). "
           "Ask me about this data — I'll take care of it."),
}
NO_DATA_TEXT = {
    "fr": "Aucune donnée trouvée pour les filtres et la période demandés.",
    "en": "No data found for the requested filters and period.",
}
NO_DATA_HINT_SCENARIO = {
    "fr": " Scénarios disponibles : {values}.",
    "en": " Available scenarios: {values}.",
}
NO_DATA_HINT_PERIOD = {
    "fr": " Période couverte par les données : {min} → {max}.",
    "en": " Period covered by the data: {min} → {max}.",
}
INTERNAL_ERROR_TEXT = {
    "fr": ("⚠️ Je n'ai pas pu traiter votre question (incident technique côté "
           "agent données). Pourriez-vous réessayer dans un instant ?"),
    "en": ("⚠️ I could not process your question (technical issue on the data "
           "agent side). Could you try again in a moment?"),
}
PROFILE_MISSING_TEXT = {
    "fr": ("⚠️ Ma base de connaissance du dataset est introuvable (profil non "
           "généré ?). Signalez-le à l'administrateur : la recette de "
           "profilage doit être exécutée."),
    "en": ("⚠️ My dataset knowledge base is missing (profile not generated?). "
           "Please tell the administrator: the profiling recipe must be run."),
}
CLARIFY_AMBIGUOUS_HEADER = {
    "fr": "Votre question mentionne « {raw} », qui peut correspondre à plusieurs valeurs :",
    "en": "Your question mentions “{raw}”, which can match several values:",
}
CLARIFY_AMBIGUOUS_FOOTER = {
    "fr": "Pouvez-vous préciser laquelle vous intéresse ?",
    "en": "Could you tell me which one you mean?",
}
CLARIFY_UNRESOLVED = {
    "fr": "Je n'ai pas trouvé « {raw} » dans les données.{hint} "
          "Pouvez-vous vérifier l'orthographe ou donner la valeur exacte ?",
    "en": "I could not find “{raw}” in the data.{hint} "
          "Could you check the spelling or give the exact value?",
}
CLARIFY_UNRESOLVED_HINT = {
    "fr": " Vouliez-vous dire « {display} » ?",
    "en": " Did you mean “{display}”?",
}
CLARIFY_ECHO_HINT = {
    "fr": "Répondez par exemple : « {example} ».",
    "en": "For example, reply: “{example}”.",
}
MORE_ROWS_NOTE = {
    "fr": "… et {n} ligne(s) supplémentaire(s) non affichée(s).",
    "en": "… and {n} more row(s) not shown.",
}
TRUNCATED_NOTE = {
    "fr": "⚠️ Résultat partiel : la liste ci-dessus peut être incomplète.",
    "en": "⚠️ Partial result: the list above may be incomplete.",
}
HEADLINE_FALLBACK = {
    "fr": "Voici les résultats pour votre question ({scope}) :",
    "en": "Here are the results for your question ({scope}):",
}
HEADLINE_LOOKUP = {
    "fr": "Voici les informations demandées :",
    "en": "Here are the details you asked for:",
}
HEADLINE_SINGLE = {
    "fr": "{metric} ({scope}) : {value}.",
    "en": "{metric} ({scope}): {value}.",
}
PERIOD_ALL_LABEL = {
    "fr": "toutes périodes disponibles",
    "en": "all available periods",
}
ABOUT_HEADER = {
    "fr": "Voici ce que je connais de ce jeu de données :",
    "en": "Here is what I know about this dataset:",
}
ABOUT_METRICS = {"fr": "**Indicateurs**", "en": "**Metrics**"}
ABOUT_SCENARIOS = {"fr": "**Scénarios disponibles**", "en": "**Available scenarios**"}
ABOUT_PERIOD = {"fr": "**Période couverte**", "en": "**Period covered**"}
ABOUT_AXES = {"fr": "**Axes d'analyse**", "en": "**Analysis axes**"}
ABOUT_ROWS = {"fr": "**Volume**", "en": "**Volume**"}


# =============================================================================
# 3. PROFILE — loading + typed accessors (the agent's knowledge)
# =============================================================================

class Profile(object):
    """In-memory view of the profile dataset (contract v1, see profiler)."""

    def __init__(self, dataset_payload, columns):
        self.raw = dataset_payload or {}
        self.columns = columns or {}
        # Live schema column names (attached at load time from the dataset's
        # current schema). Lets lookups reach attribute columns — e.g. an account
        # manager — even when the profile recipe hasn't re-run after a schema
        # change (the profile can be stale; the live schema never is).
        self.live_columns = []

    # ---- table-level -------------------------------------------------------
    @property
    def dataset_name(self):
        return TARGET_DATASET or self.raw.get("dataset_name") or ""

    @property
    def metrics(self):
        return [m for m in (self.raw.get("metrics") or [])
                if isinstance(m, dict) and m.get("name") and m.get("agg")]

    def metric(self, name):
        for m in self.metrics:
            if m["name"] == name:
                return m
        return None

    @property
    def default_metric(self):
        m = self.metric(self.raw.get("default_metric") or "")
        return m or (self.metrics[0] if self.metrics else None)

    @property
    def scenario(self):
        s = self.raw.get("scenario")
        if isinstance(s, dict) and s.get("column") and s.get("values"):
            return s
        return None

    @property
    def time(self):
        t = self.raw.get("time")
        if isinstance(t, dict) and t.get("column") and t.get("format"):
            return t
        return None

    def description(self, lang):
        return (self.raw.get("description_%s" % lang)
                or self.raw.get("description_en")
                or self.raw.get("description_fr") or self.dataset_name)

    # ---- columns -----------------------------------------------------------
    def column(self, name):
        return self.columns.get(name)

    def groupable_columns(self):
        out = []
        for name, c in self.columns.items():
            if c.get("groupable") and c.get("role") in ("dimension", "scenario",
                                                        "identifier", "time"):
                out.append(name)
        return out

    def indexed_columns(self):
        return [n for n, c in self.columns.items() if c.get("indexed")]

    def match_column(self, raw):
        """User/LLM column designation -> canonical column name, via exact,
        case/space-insensitive and synonym matching. None when unknown."""
        if not raw:
            return None
        if raw in self.columns:
            return raw
        key = _norm(raw)
        flat = re.sub(r"[\s_]+", "", key)
        for name, c in self.columns.items():
            if _norm(name) == key or re.sub(r"[\s_]+", "", _norm(name)) == flat:
                return name
            for syn in c.get("synonyms") or []:
                if _norm(syn) == key:
                    return name
        return None

    def column_priority(self, name):
        """Ambiguity priority: explicit profile override first, then the most
        SPECIFIC column wins (higher distinct_count = more specific)."""
        c = self.columns.get(name) or {}
        if isinstance(c.get("ambiguity_priority"), int):
            return (0, c["ambiguity_priority"])
        return (1, -(c.get("distinct_count") or 0))

    def attribute_columns(self):
        """All real column names available for a plain lookup (live schema first,
        union with the profiled columns). These are the columns a `lookup` intent
        may RETURN (e.g. account_manager) — not necessarily groupable axes."""
        names, seen = [], set()
        for name in list(self.live_columns) + list(self.columns.keys()):
            if name and name not in seen:
                seen.add(name)
                names.append(name)
        return names

    def match_attribute(self, raw):
        """User/LLM attribute designation -> a real column name (lookup output).
        Like match_column but also scans the LIVE schema, so attributes outside
        the profile (a freshly added column) still resolve. None when unknown."""
        if not raw:
            return None
        canonical = self.match_column(raw)
        if canonical:
            return canonical
        key = _norm(raw)
        flat = re.sub(r"[\s_]+", "", key)
        for name in self.live_columns:
            if _norm(name) == key or re.sub(r"[\s_]+", "", _norm(name)) == flat:
                return name
        return None


def parse_profile_rows(rows):
    """[{key, payload}, ...] -> Profile. Tolerant: bad JSON rows are skipped;
    returns None when the __dataset__ row is missing (profile unusable)."""
    dataset_payload, columns = None, {}
    for row in rows or []:
        key = str(row.get("key") or "")
        try:
            payload = json.loads(row.get("payload") or "")
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if key == "__dataset__":
            dataset_payload = payload
        elif key:
            columns[key] = payload
    if not dataset_payload:
        return None
    return Profile(dataset_payload, columns)


def _read_dataset_rows(name, wanted_columns):
    """Read a (small) DSS dataset as a list of dicts without requiring pandas.
    Tries iter_tuples + schema first, falls back to get_dataframe."""
    ds = dataiku.Dataset(name)
    try:
        schema = ds.read_schema()
        names = [c["name"] if isinstance(c, dict) else c.name for c in schema]
        rows = []
        for t in ds.iter_tuples():
            rows.append(dict(zip(names, t)))
        return rows
    except Exception:
        df = ds.get_dataframe()
        return df.to_dict("records")


def _read_live_columns(name):
    """Current column names of a dataset, straight from its schema (cheap
    metadata read — no scan, instance-safe). Used to ground lookups on the
    real, current columns regardless of profile freshness."""
    schema = dataiku.Dataset(name).read_schema()
    out = []
    for c in schema:
        col = c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
        if col:
            out.append(col)
    return out


# =============================================================================
# 4. PURE HELPERS — parsing / validation
# =============================================================================

def _safe_json_parse(text):
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(),
                     flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def _norm(value):
    """Accent-insensitive lowercase, collapsed whitespace (FROZEN — must match
    the value-index recipe's norm_value)."""
    s = unicodedata.normalize("NFKD", str(value))
    s = s.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s.strip().lower())


def _validate_period(raw):
    if not isinstance(raw, dict):
        return {"mode": "all_available"}
    start = str(raw.get("start") or "")
    end = str(raw.get("end") or "")
    if (raw.get("mode") == "explicit" and _DATE_RE.match(start)
            and _DATE_RE.match(end) and start <= end):
        label = str(raw.get("label") or "").strip()[:60] or ("%s → %s" % (start, end))
        return {"mode": "explicit", "start": start, "end": end, "label": label}
    return {"mode": "all_available"}


# The orchestrator pins the reply language via the injected system context
# ("USER LANGUAGE: fr"). It is AUTHORITATIVE — it reflects the language of the
# USER's actual message, which the orchestrator knows; the sub-agent only sees the
# (possibly English) self-contained task, so its own guess is unreliable.
_FORCED_LANG_RE = re.compile(r"USER LANGUAGE:\s*(fr|en)\b", re.IGNORECASE)
_MODE_RE = re.compile(r"\bMODE:\s*(eco|medium|high)\b", re.IGNORECASE)


def forced_language(context):
    """Reply language pinned by the orchestrator in the injected context, or None."""
    if not context:
        return None
    m = _FORCED_LANG_RE.search(context)
    return m.group(1).lower() if m else None


def forced_mode(context):
    """Model tier (eco/medium/high) the orchestrator pinned in the injected context,
    or None when absent (batch / stand-alone -> DEFAULT_MODE)."""
    if not context:
        return None
    m = _MODE_RE.search(context)
    return m.group(1).lower() if m else None


def validate_understanding(parsed, profile, instruction):
    """Deterministic validation/degradation of the UNDERSTAND output against
    the PROFILE (never against hardcoded business values). Never raises;
    returns None only when structurally unusable (-> retry, then refuse)."""
    if not isinstance(parsed, dict) or profile is None:
        return None
    scope = parsed.get("scope")
    if scope not in ("data", "out_of_scope"):
        return None
    language = parsed.get("language") if parsed.get("language") in ("fr", "en") else "fr"

    out = {"scope": scope, "language": language, "instruction": instruction,
           "intent": "custom", "metric": None, "scenarios": [],
           "period": {"mode": "all_available"}, "periods": [],
           "group_by": None, "list_column": None, "top_n": None,
           "order": "desc", "terms": [], "attributes": [], "clarification": ""}
    if scope == "out_of_scope":
        return out

    intent = parsed.get("intent")
    out["intent"] = intent if intent in KNOWN_INTENTS else "custom"

    metric = profile.metric(str(parsed.get("metric") or ""))
    out["metric"] = (metric or profile.default_metric or {}).get("name")

    scen = profile.scenario
    if scen:
        wanted, seen = [], set()
        for v in parsed.get("scenarios") or []:
            v = str(v)
            if v in scen["values"] and v not in seen:
                seen.add(v)
                wanted.append(v)
        out["scenarios"] = wanted    # empty -> defaults applied at build time

    out["period"] = _validate_period(parsed.get("period"))

    if out["intent"] == "compare_periods":
        periods = []
        for raw in (parsed.get("periods") or [])[:6]:
            p = _validate_period(dict(raw or {}, mode="explicit"))
            if p["mode"] == "explicit":
                periods.append(p)
        if len(periods) >= 2:
            out["periods"] = periods
        else:
            out["intent"] = "custom"   # unusable comparison -> long-tail path

    if out["intent"] == "compare_scenarios":
        if not scen:
            out["intent"] = "total"
        else:
            if len(out["scenarios"]) == 1:
                # "gap vs budget" mentions one scenario: prepend the factual
                # default (generalizes ACTUALS-vs-BUDGET with zero hardcoding).
                defaults = [v for v in (scen.get("default_values") or [])
                            if v not in out["scenarios"]]
                if defaults:
                    out["scenarios"] = [defaults[0]] + out["scenarios"]
            if len(out["scenarios"]) < 2:
                out["scenarios"] = list(scen.get("default_values") or [])[:1]
                out["intent"] = "total"

    group_by = profile.match_column(parsed.get("group_by"))
    if group_by and group_by in profile.groupable_columns():
        out["group_by"] = group_by
    list_column = profile.match_column(parsed.get("list_column"))
    if list_column:
        out["list_column"] = list_column

    top_n = parsed.get("top_n")
    if isinstance(top_n, int) and 1 <= top_n <= 100:
        out["top_n"] = top_n
    if out["intent"] == "top_n" and not out["top_n"]:
        out["top_n"] = 10
    if parsed.get("order") in ("asc", "desc"):
        out["order"] = parsed["order"]

    if out["intent"] in ("breakdown", "top_n", "share_of_total") and not out["group_by"]:
        out["intent"] = "custom"       # no axis -> let the LLM SQL handle it
    if out["intent"] in ("list_values", "count_distinct") and not out["list_column"]:
        if out["group_by"]:
            out["list_column"] = out["group_by"]
        else:
            out["intent"] = "custom"

    terms, seen = [], set()
    stop = _term_stopwords(profile)
    for t in parsed.get("terms") or []:
        t = str(t).strip()
        key = _norm(t)
        if not t or not key or key in stop or key in seen:
            continue
        seen.add(key)
        terms.append(t[:80])
        if len(terms) >= MAX_TERMS:
            break
    out["terms"] = terms

    # Attribute columns to RETURN for a `lookup` (account_manager, carrier_code…).
    # Resolved against the LIVE schema + profile so a freshly added column works.
    attrs, seen_a = [], set()
    for raw in parsed.get("attributes") or []:
        col = profile.match_attribute(raw)
        if col and col not in seen_a:
            seen_a.add(col)
            attrs.append(col)
    out["attributes"] = attrs

    # `lookup` is a plain value retrieval (no aggregation). It needs an entity to
    # filter on AND the lookup path enabled; otherwise fall back to the SQL paths
    # (e.g. "list all account managers" is list_values/custom, not a lookup).
    if out["intent"] == "lookup" and (not terms or not DATASET_LOOKUP_ENABLED):
        out["intent"] = "custom"

    out["clarification"] = str(parsed.get("clarification") or "").strip()[:500]
    return out


def _term_stopwords(profile):
    """Words that must never reach the resolver: metric labels/synonyms,
    scenario values, column names — all PROFILE-derived (rule P3: no hardcoded
    business values), plus a small language-level operator list."""
    stop = set()
    for m in profile.metrics:
        for w in (m.get("name"), m.get("label_fr"), m.get("label_en")):
            if w:
                stop.add(_norm(w))
    scen = profile.scenario
    if scen:
        for v in scen["values"]:
            stop.add(_norm(v))
    for name, c in profile.columns.items():
        stop.add(_norm(name))
        for syn in c.get("synonyms") or []:
            stop.add(_norm(syn))
    stop.update(("total", "sum", "somme", "top", "split", "breakdown",
                 "repartition", "trend", "tendance", "evolution", "delta",
                 "variance", "gap", "ecart", "comparison", "comparaison",
                 "year", "month", "annee", "mois", "ytd", "average",
                 "moyenne", "count", "nombre"))
    stop.discard("")
    return stop


# =============================================================================
# 5. UNDERSTAND — prompt generated from the profile
# =============================================================================

def build_understand_schema(profile):
    """JSON schema for with_json_output, with enums anchored on the profile."""
    scen = profile.scenario
    props = {
        "scope": {"type": "string", "enum": ["data", "out_of_scope"]},
        "language": {"type": "string", "enum": ["fr", "en"]},
        "intent": {"type": "string", "enum": list(KNOWN_INTENTS)},
        "metric": {"type": "string"},
        "period": {"type": "object", "properties": {
            "mode": {"type": "string", "enum": ["explicit", "all_available"]},
            "start": {"type": "string"}, "end": {"type": "string"},
            "label": {"type": "string"}}, "required": ["mode"]},
        "periods": {"type": "array", "items": {"type": "object", "properties": {
            "start": {"type": "string"}, "end": {"type": "string"},
            "label": {"type": "string"}}, "required": ["start", "end"]}},
        "group_by": {"type": "string"},
        "list_column": {"type": "string"},
        "top_n": {"type": "integer"},
        "order": {"type": "string", "enum": ["asc", "desc"]},
        "terms": {"type": "array", "items": {"type": "string"}},
        "attributes": {"type": "array", "items": {"type": "string"}},
        "clarification": {"type": "string"},
    }
    if scen:
        props["scenarios"] = {"type": "array",
                              "items": {"type": "string", "enum": list(scen["values"])}}
    return {"type": "object", "properties": props,
            "required": ["scope", "language"]}


def build_understand_prompt(profile, current_date, lang_hint="fr"):
    """System prompt of the UNDERSTAND call, GENERATED from the profile."""
    metrics_block = "\n".join(
        '- "%s": %s / %s%s' % (m["name"], m.get("label_fr", ""), m.get("label_en", ""),
                               (" — " + m["description"]) if m.get("description") else "")
        for m in profile.metrics) or "(none)"
    default_metric = (profile.default_metric or {}).get("name", "")

    scen = profile.scenario
    if scen:
        scen_block = (
            'The column "%s" holds SCENARIO values — versions of the same '
            "figures that must NEVER be summed together. Its exact values: %s. "
            'Fill "scenarios" with the values the user explicitly refers to '
            "(map their words to the closest value); leave it EMPTY when none "
            "is mentioned (the system applies the default: %s). Never invent "
            "a scenario value."
            % (scen["column"], ", ".join(scen["values"]),
               ", ".join(scen.get("default_values") or ["(first value)"])))
    else:
        scen_block = "This dataset has no scenario column."

    tm = profile.time
    if tm:
        time_block = ('Main time column: "%s" (coverage %s → %s). Resolve '
                      "relative references using the current date above "
                      '("last year", "YTD", "ce mois-ci", "depuis juillet").'
                      % (tm["column"], tm.get("min"), tm.get("max")))
    else:
        time_block = "This dataset has no time column: ignore periods."

    axes_lines = []
    for name in profile.groupable_columns():
        c = profile.column(name) or {}
        line = '- "%s"' % name
        desc = c.get("description_en") or c.get("description_fr")
        if desc:
            line += ": %s" % desc[:140]
        syns = c.get("synonyms") or []
        if syns:
            line += " (user words: %s)" % ", ".join(syns[:6])
        if c.get("is_enum") and c.get("values"):
            line += " [values: %s]" % ", ".join(v["v"] for v in c["values"][:15])
        axes_lines.append(line)
    axes_block = "\n".join(axes_lines) or "(none)"

    indexed = ", ".join(profile.indexed_columns()) or "(none)"
    attr_cols = profile.attribute_columns()
    attr_block = ", ".join(attr_cols[:60]) or "(none)"

    return (
        "You are the understanding module of a data agent for the dataset "
        '"%s" — %s (one row = %s). You do NOT answer. You do NOT write SQL. '
        "You return ONE JSON object describing the question. "
        "Current date: %s.\n\n"
        "METRICS (field \"metric\" = one name below; default \"%s\"):\n%s\n\n"
        "SCENARIOS:\n%s\n\n"
        "TIME:\n%s\n\n"
        "ANALYSIS AXES (for group_by / list_column — output the exact column "
        "name):\n%s\n\n"
        "ALL COLUMNS (for \"attributes\" on a lookup — output the EXACT name):\n"
        "%s\n\n"
        "INTENTS (field \"intent\"):\n"
        "- \"total\": one aggregated figure.\n"
        "- \"breakdown\": the metric split along ONE axis -> set group_by.\n"
        "- \"top_n\": ranking along one axis -> group_by + top_n (default 10); "
        "\"order\" = \"asc\" for bottom/worst rankings.\n"
        "- \"share_of_total\": per-axis share/percentage of the total -> group_by.\n"
        "- \"compare_scenarios\": compare scenario values (delta/variance/gap) "
        "-> fill \"scenarios\" with the 2+ values involved.\n"
        "- \"compare_periods\": compare time periods (YoY, MoM, H1 vs H1) -> "
        "fill \"periods\" with one {start,end,label} per period.\n"
        "- \"trend\": evolution over time (monthly series).\n"
        "- \"list_values\": the user asks WHICH values exist for an axis "
        "(\"quels clients ?\", \"liste des produits\") -> set list_column.\n"
        "- \"count_distinct\": how many distinct values of an axis -> list_column.\n"
        "- \"lookup\": retrieve an ATTRIBUTE of one or more NAMED entities — NO "
        "maths, no totals, no ranking. \"who is the account manager of X?\", "
        "\"the carrier code and sales zone of Y\". Put the named entit(ies) in "
        "\"terms\" and the column(s) to return in \"attributes\" (exact names "
        "from ALL COLUMNS). This is a fast direct read — PREFER it over a SQL "
        "intent whenever the user just wants a field of a known entity.\n"
        "- \"about_data\": the user asks what this dataset is / what you can "
        "answer / which columns or indicators exist.\n"
        "- \"custom\": a real data question that fits none of the above "
        "(multi-axis splits, ratios between filters, complex conditions...). "
        "Prefer a structured intent whenever one fits.\n"
        "- scope \"out_of_scope\": NOT about this data at all.\n\n"
        "PERIODS: {\"mode\":\"explicit\",\"start\":\"YYYY-MM-DD\",\"end\":"
        "\"YYYY-MM-DD\",\"label\":<as the user said it>} when the user gives "
        "any time scope (\"2025\" -> 2025-01-01..2025-12-31; \"janvier 2026\" "
        "-> 2026-01-01..2026-01-31; \"YTD 2026\" -> 2026-01-01..current date). "
        "{\"mode\":\"all_available\"} when NO period is given — never invent "
        "one, never ask for one.\n\n"
        "TERMS (field \"terms\"): the business VALUES the user names that must "
        "be matched against the data catalog (names, codes, labels of: %s). "
        "Copy them EXACTLY as the user wrote them (accents, typos included) — "
        "never correct, translate or expand. NEVER extract: metric words, "
        "scenario words, dates/periods, operation words (top, split, delta, "
        "compare, sum...), column names themselves. When the user explicitly "
        "designates the column of a value — typically when answering a "
        "disambiguation question — keep/produce the qualified form "
        "\"VALUE (Column)\" with the exact column name. Never strip an "
        "existing \"(Column)\" qualifier.\n\n"
        "CONVERSATION CONTEXT (when provided before the question): it carries "
        "the PREVIOUS assistant message and the user's raw answer. If that "
        "previous message asked a disambiguation question listing candidate "
        "values and the user's answer designates one of them — by name, "
        "column, position (\"the first one\", \"la deuxième\") or partial "
        "wording — output that candidate as a qualified term "
        "\"VALUE (Column)\" copied EXACTLY from the list. Never output a "
        "candidate that is not in the list.\n\n"
        "CLARIFICATION: ONLY when the question is about this data but too "
        "vague to plan at all (e.g. \"et alors ?\"). One short question in the "
        "user's language. Leave empty otherwise.\n\n"
        "HARD RULES:\n"
        "- Output ONLY the JSON object. No markdown fences, no commentary.\n"
        "- \"language\" = language of the question (\"fr\" or \"en\").\n"
        "- A question about the figures, entities or columns of this dataset "
        "is NEVER out_of_scope.\n"
        % (profile.dataset_name, profile.description("en")[:300],
           profile.raw.get("grain") or "one record",
           current_date, default_metric, metrics_block, scen_block,
           time_block, axes_block, attr_block, indexed))


# =============================================================================
# 6. RESOLVE — value grounding on the index + disambiguation policy
# =============================================================================

def parse_qualified_term(term, profile):
    """'IPL (Product)' -> ('Product', 'IPL') when Column matches a profile
    column (case/space-insensitive). None otherwise."""
    m = re.match(r"^(.+?)\s*[\(\[]\s*([A-Za-z0-9_ ]+?)\s*[\)\]]$", str(term or "").strip())
    if not m:
        return None
    value = m.group(1).strip().strip("'\"")
    column = profile.match_column(m.group(2).strip())
    if not column or not value:
        return None
    return (column, value)


def _sql_quote_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def _like_escape(value):
    return (str(value).replace("\\", "\\\\").replace("%", "\\%")
            .replace("_", "\\_"))


def rank_candidates(term_norm, rows):
    """Fuzzy-rank index rows for one term. rows = [{column_name, value,
    value_norm, occurrences}]. Returns candidates sorted by similarity then
    occurrences, shaped like the historical resolver contract."""
    scored = []
    for r in rows or []:
        vnorm = str(r.get("value_norm") or "")
        if not vnorm:
            continue
        ratio = difflib.SequenceMatcher(None, term_norm, vnorm).ratio()
        if term_norm and (term_norm in vnorm or vnorm in term_norm):
            ratio = max(ratio, 0.8)
        scored.append((ratio, int(r.get("occurrences") or 0), r))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    out = []
    for ratio, occ, r in scored:
        out.append({"target_column": str(r.get("column_name") or ""),
                    "target_value": str(r.get("value") or ""),
                    "display_value": str(r.get("value") or ""),
                    "occurrences": occ, "score": round(ratio, 3)})
    return out


def refine_ambiguous(profile, raw_value, candidates, preferred_column=None):
    """Deterministic ambiguity policy (ported from SalesDrive v2, generic):
    1. preferred column (qualified term) filters candidates when any match;
    2. strict exact-value preference evicts normalization collisions;
    3. one distinct value left -> auto-pick by profile column priority.
    Returns ("resolved", candidate) or ("ambiguous", reduced_candidates)."""
    cands = [c for c in (candidates or []) if c.get("target_value")]
    if not cands:
        return ("ambiguous", candidates or [])
    if preferred_column:
        kept = [c for c in cands if c.get("target_column") == preferred_column]
        if kept:
            cands = kept
    raw_low = str(raw_value or "").strip().lower()
    exact = [c for c in cands if str(c["target_value"]).strip().lower() == raw_low]
    if exact:
        cands = exact
    values = {str(c["target_value"]).strip().lower() for c in cands}
    if len(values) == 1:
        cands = sorted(cands, key=lambda c: profile.column_priority(
            c.get("target_column") or ""))
        chosen = cands[0]
        # Transparency: the SAME value also lives in other columns (e.g. an
        # offer name that is both a Product and a Solution). Record them so
        # RENDER can disclose the pick — we still keep the priority column.
        alts, seen = [], {chosen.get("target_column")}
        for c in cands[1:]:
            col = c.get("target_column") or ""
            if col and col not in seen:
                seen.add(col)
                alts.append(col)
        if alts:
            chosen = dict(chosen, alt_columns=alts)
        return ("resolved", chosen)
    return ("ambiguous", cands)


def build_filter_clauses(resolutions):
    """[{column, value}] from resolved items, deduplicated. Values came from
    the index verbatim — exact by construction."""
    out, seen = [], set()
    for r in resolutions or []:
        if r.get("status") != "resolved":
            continue
        column = str(r.get("target_column") or "").strip()
        value = str(r.get("target_value") or "")
        if not column or not value:
            continue
        key = (column, value)
        if key not in seen:
            seen.add(key)
            clause = {"column": column, "value": value}
            alts = [c for c in (r.get("alt_columns") or []) if c and c != column]
            if alts:
                clause["alt_columns"] = alts
            out.append(clause)
    return out


def build_lookup_filter(filters):
    """Build a Dataiku Dataset Lookup filter tree from resolved [{column, value}]
    clauses. One clause -> EQUALS; several values on the SAME column -> OR; several
    columns -> AND of the per-column groups. Returns None when there is nothing to
    filter on (caller then falls back to SQL). Operators match the tool's schema
    (EQUALS / AND / OR), which is auto-discovered from its descriptor at call time."""
    clauses = [f for f in (filters or [])
               if f.get("column") and f.get("value") is not None]
    if not clauses:
        return None
    by_col = {}
    order = []
    for f in clauses:
        col = f["column"]
        if col not in by_col:
            by_col[col] = []
            order.append(col)
        if f["value"] not in by_col[col]:
            by_col[col].append(f["value"])

    def eq(col, val):
        return {"operator": "EQUALS", "column": col, "value": val}

    groups = []
    for col in order:
        vals = by_col[col]
        if len(vals) == 1:
            groups.append(eq(col, vals[0]))
        else:
            groups.append({"operator": "OR",
                           "clauses": [eq(col, v) for v in vals]})
    if len(groups) == 1:
        return groups[0]
    return {"operator": "AND", "clauses": groups}


def extract_lookup_rows(raw):
    """Pull the list of row dicts out of a Dataset Lookup tool result, tolerant to
    the envelope shape: rows live at result['output']['rows'] (dict rows) or a
    {columns, rows} pair (list rows). Returns [] when nothing matched."""
    def walk(node, depth=0):
        if depth > 6 or node is None:
            return None
        if isinstance(node, dict):
            rows = node.get("rows")
            if isinstance(rows, list):
                if not rows:
                    return []
                if isinstance(rows[0], dict):
                    return rows
                cols = node.get("columns")
                if isinstance(cols, list) and cols:
                    names = [c.get("name") if isinstance(c, dict) else str(c)
                             for c in cols]
                    return [dict(zip(names, r)) for r in rows
                            if isinstance(r, (list, tuple))]
            for key in ("output", "result", "data", "records"):
                if key in node:
                    got = walk(node[key], depth + 1)
                    if got is not None:
                        return got
        elif isinstance(node, list):
            if not node or isinstance(node[0], dict):
                return node
        return None
    return walk(raw) or []


def lookup_note(lookup_filter, attributes):
    """A short, human-readable note describing a Dataset Lookup (shown as the
    'SQL' in Evidence technical details — honest: it states it was a direct
    lookup, not a generated query)."""
    def describe(node):
        op = node.get("operator")
        if op in ("AND", "OR"):
            return (" %s " % op).join("(%s)" % describe(c)
                                      for c in node.get("clauses") or [])
        return "%s = %s" % (node.get("column"), node.get("value"))
    cols = ", ".join(attributes or []) or "*"
    return "/* Dataset Lookup (no SQL) */ %s WHERE %s" % (cols, describe(lookup_filter))


def build_clarification(resolutions, lang):
    """Deterministic clarification listing real candidates verbatim, teaching
    the machine-parseable 'VALUE (Column)' echo format (loop-proof)."""
    blocks = []
    for r in resolutions or []:
        status = r.get("status")
        if status == "ambiguous":
            lines = [CLARIFY_AMBIGUOUS_HEADER[lang].format(raw=r.get("raw_value", ""))]
            example, seen = "", set()
            for c in (r.get("candidates") or [])[:5]:
                display = c.get("display_value") or c.get("target_value") or ""
                entry = "- %s (%s)" % (display, c.get("target_column", ""))
                if entry in seen:
                    continue
                seen.add(entry)
                lines.append(entry)
                if not example:
                    example = "%s (%s)" % (display, c.get("target_column", ""))
            lines.append(CLARIFY_AMBIGUOUS_FOOTER[lang])
            if example:
                lines.append(CLARIFY_ECHO_HINT[lang].format(example=example))
            blocks.append("\n".join(lines))
        elif status == "unresolved":
            best = r.get("best_candidate") or {}
            display = best.get("display_value") or best.get("target_value") or ""
            hint = CLARIFY_UNRESOLVED_HINT[lang].format(display=display) if display else ""
            blocks.append(CLARIFY_UNRESOLVED[lang].format(raw=r.get("raw_value", ""),
                                                          hint=hint))
    return "\n\n".join(blocks)


def resolved_filters_summary(resolutions):
    out = []
    for r in resolutions or []:
        if r.get("status") == "resolved":
            out.append({"column": r.get("target_column", ""),
                        "value": r.get("target_value", ""),
                        "display": r.get("display_value", ""),
                        "raw": r.get("raw_value", "")})
    return out


# =============================================================================
# 7. SQL BUILDER — deterministic templates (the LLM never writes these)
# =============================================================================

def qident(name):
    """Double-quoted SQL identifier; rejects anything not column-shaped."""
    s = str(name or "").strip()
    if not _IDENT_RE.match(s) or len(s) > 80:
        raise ValueError("unsafe identifier: %r" % name)
    return '"' + s.replace('"', '') + '"'


def metric_expr(metric):
    """Metric dict -> SQL aggregate expression."""
    agg = metric["agg"]
    if agg == "COUNT" or not metric.get("column"):
        return "COUNT(*)"
    col = qident(metric["column"])
    if agg == "COUNT_DISTINCT":
        return "COUNT(DISTINCT %s)" % col
    if agg in ("SUM", "AVG", "MIN", "MAX"):
        return "%s(%s)" % (agg, col)
    return "SUM(%s)" % col


def _metric_inner(metric):
    """The per-row expression used inside CASE pivots (scenario / period)."""
    if metric["agg"] == "COUNT" or not metric.get("column"):
        return "1"
    return qident(metric["column"])


def period_predicate(time_info, start, end):
    """Time-format-aware period predicate (start/end = YYYY-MM-DD strings).

    String-format predicates compare on LEFT(CAST(col AS text), n): ISO text
    sorts lexicographically, and the CAST makes the SQL valid whether the
    physical column is text, date or timestamp — profile format detection can
    be wrong about the PHYSICAL type (seen in DSS: a real PostgreSQL `date`
    profiled as yyyy_mm_dd_str -> LEFT(date, 10) does not exist)."""
    col = qident(time_info["column"])
    fmt = time_info["format"]
    if fmt in ("date",):
        return ("(%s >= DATE %s AND %s < (DATE %s + INTERVAL '1 day'))"
                % (col, _sql_quote_literal(start), col, _sql_quote_literal(end)))
    if fmt == "yyyy_mm_dd_str":
        expr = "LEFT(CAST(%s AS text), 10)" % col
        return ("(%s >= %s AND %s <= %s)"
                % (expr, _sql_quote_literal(start), expr, _sql_quote_literal(end)))
    if fmt == "yyyy_mm_str":
        expr = "LEFT(CAST(%s AS text), 7)" % col
        return ("(%s >= %s AND %s <= %s)"
                % (expr, _sql_quote_literal(start[:7]), expr,
                   _sql_quote_literal(end[:7])))
    if fmt == "yyyymm_int":
        return ("(%s >= %d AND %s <= %d)"
                % (col, int(start[:4]) * 100 + int(start[5:7]),
                   col, int(end[:4]) * 100 + int(end[5:7])))
    if fmt == "year_int":
        return "(%s >= %d AND %s <= %d)" % (col, int(start[:4]), col, int(end[:4]))
    raise ValueError("unknown time format: %r" % fmt)


def month_bucket_expr(time_info):
    """Monthly bucket expression, cast-safe like period_predicate."""
    col = qident(time_info["column"])
    fmt = time_info["format"]
    if fmt == "date":
        return "TO_CHAR(%s, 'YYYY-MM')" % col
    if fmt in ("yyyy_mm_dd_str", "yyyy_mm_str"):
        return "LEFT(CAST(%s AS text), 7)" % col
    if fmt in ("yyyymm_int", "year_int"):
        return col
    raise ValueError("unknown time format: %r" % fmt)


def _where_sql(parts):
    parts = [p for p in parts if p]
    return (" WHERE " + " AND ".join(parts)) if parts else ""


def _filters_sql(filters):
    return ["%s = %s" % (qident(f["column"]), _sql_quote_literal(f["value"]))
            for f in filters or []]


def _scenario_clause(profile, scenarios):
    scen = profile.scenario
    if not scen:
        return "", []
    values = scenarios or scen.get("default_values") or scen["values"][:1]
    clause = "%s IN (%s)" % (qident(scen["column"]),
                             ", ".join(_sql_quote_literal(v) for v in values))
    return clause, values


def _axis_select(profile, axis):
    """-> (select_cols, group_by_cols, display_alias|None) honoring the
    profile display pair (id column shown with its human label twin)."""
    a = qident(axis)
    col = profile.column(axis) or {}
    display = col.get("display_column")
    if display and profile.column(display) is not None and display != axis:
        return ("%s, MAX(%s) AS %s" % (a, qident(display), qident(display)),
                a, display)
    return (a, a, None)


def build_sql(u, profile, filters, table):
    """Deterministic SQL for every structured intent. Returns (sql, meta) —
    meta = {"format_map": {alias: format}, "unit": str|None} for rendering.
    Raises ValueError for unbuildable combinations (caller degrades)."""
    intent = u["intent"]
    metric = profile.metric(u["metric"] or "") or profile.default_metric
    if metric is None and intent not in ("list_values", "count_distinct"):
        raise ValueError("no metric available")
    scen_clause, scen_values = _scenario_clause(profile, u["scenarios"])
    fmt_map, unit = {}, (metric or {}).get("unit")
    if metric:
        fmt_map[metric["name"]] = metric.get("format", "number")

    period_part = ""
    tm = profile.time
    if tm and u["period"]["mode"] == "explicit":
        period_part = period_predicate(tm, u["period"]["start"], u["period"]["end"])
    where = _where_sql([scen_clause, period_part] + _filters_sql(filters))

    if intent == "total":
        sql = "SELECT %s AS %s FROM %s%s" % (
            metric_expr(metric), qident(metric["name"]), table, where)
        return sql + " LIMIT %d" % SQL_MAX_ROWS, {"format_map": fmt_map, "unit": unit}

    if intent in ("breakdown", "top_n"):
        select_cols, group_col, display = _axis_select(profile, u["group_by"])
        limit = u["top_n"] if intent == "top_n" else SQL_MAX_ROWS
        sql = ("SELECT %s, %s AS %s FROM %s%s GROUP BY %s ORDER BY %s %s LIMIT %d"
               % (select_cols, metric_expr(metric), qident(metric["name"]),
                  table, where, group_col, qident(metric["name"]),
                  "ASC" if u["order"] == "asc" else "DESC", limit))
        return sql, {"format_map": fmt_map, "unit": unit}

    if intent == "share_of_total":
        select_cols, group_col, display = _axis_select(profile, u["group_by"])
        m = metric_expr(metric)
        limit = u["top_n"] or SQL_MAX_ROWS
        sql = ("SELECT %s, %s AS %s, "
               "ROUND(CAST(100.0 * %s / NULLIF(SUM(%s) OVER (), 0) AS numeric), 1) "
               "AS \"share_pct\" FROM %s%s GROUP BY %s ORDER BY %s DESC LIMIT %d"
               % (select_cols, m, qident(metric["name"]), m, m,
                  table, where, group_col, qident(metric["name"]), limit))
        fmt_map["share_pct"] = "percent"
        return sql, {"format_map": fmt_map, "unit": unit}

    if intent == "compare_scenarios":
        scen = profile.scenario
        if not scen or len(u["scenarios"]) < 2:
            raise ValueError("compare_scenarios needs a scenario column + 2 values")
        scol, inner = qident(scen["column"]), _metric_inner(metric)
        pivots, exprs = [], []
        for v in u["scenarios"]:
            expr = ("SUM(CASE WHEN %s = %s THEN %s ELSE 0 END)"
                    % (scol, _sql_quote_literal(v), inner))
            exprs.append(expr)
            pivots.append("%s AS %s" % (expr, qident(v)))
            fmt_map[v] = metric.get("format", "number")
        scen_in = "%s IN (%s)" % (scol, ", ".join(_sql_quote_literal(v)
                                                  for v in u["scenarios"]))
        where2 = _where_sql([scen_in, period_part] + _filters_sql(filters))
        cols, tail = "", ""
        if len(u["scenarios"]) == 2:
            a, b = exprs[0], exprs[1]
            pivots.append("%s - %s AS \"delta\"" % (a, b))
            pivots.append("ROUND(CAST(100.0 * (%s - %s) / NULLIF(%s, 0) AS numeric), 1)"
                          " AS \"delta_pct\"" % (a, b, b))
            fmt_map["delta"] = metric.get("format", "number")
            fmt_map["delta_pct"] = "percent"
        if u["group_by"]:
            select_cols, group_col, display = _axis_select(profile, u["group_by"])
            cols = select_cols + ", "
            tail = (" GROUP BY %s ORDER BY %s DESC LIMIT %d"
                    % (group_col, qident(u["scenarios"][0]),
                       u["top_n"] or SQL_MAX_ROWS))
        sql = "SELECT %s%s FROM %s%s%s" % (cols, ", ".join(pivots), table,
                                           where2, tail)
        if not tail:
            sql += " LIMIT %d" % SQL_MAX_ROWS
        return sql, {"format_map": fmt_map, "unit": unit}

    if intent == "compare_periods":
        if not tm or len(u["periods"]) < 2:
            raise ValueError("compare_periods needs a time column + 2 periods")
        inner = _metric_inner(metric)
        pivots, exprs, preds = [], [], []
        for p in u["periods"]:
            pred = period_predicate(tm, p["start"], p["end"])
            preds.append(pred)
            expr = "SUM(CASE WHEN %s THEN %s ELSE 0 END)" % (pred, inner)
            exprs.append(expr)
            alias = (p.get("label") or ("%s..%s" % (p["start"], p["end"])))[:40]
            pivots.append('%s AS "%s"' % (expr, alias.replace('"', "")))
            fmt_map[alias] = metric.get("format", "number")
        if len(u["periods"]) == 2:
            # delta = second period minus first, in the order the user gave.
            pivots.append("%s - %s AS \"delta\"" % (exprs[1], exprs[0]))
            pivots.append("ROUND(CAST(100.0 * (%s - %s) / NULLIF(%s, 0) AS numeric), 1)"
                          " AS \"delta_pct\"" % (exprs[1], exprs[0], exprs[0]))
            fmt_map["delta"] = metric.get("format", "number")
            fmt_map["delta_pct"] = "percent"
        where2 = _where_sql([scen_clause, "(" + " OR ".join(preds) + ")"]
                            + _filters_sql(filters))
        sql = "SELECT %s FROM %s%s LIMIT %d" % (", ".join(pivots), table,
                                                where2, SQL_MAX_ROWS)
        return sql, {"format_map": fmt_map, "unit": unit}

    if intent == "trend":
        if not tm:
            raise ValueError("trend needs a time column")
        bucket = month_bucket_expr(tm)
        sql = ("SELECT %s AS \"month\", %s AS %s FROM %s%s "
               "GROUP BY 1 ORDER BY 1 LIMIT %d"
               % (bucket, metric_expr(metric), qident(metric["name"]),
                  table, where, SQL_MAX_ROWS))
        return sql, {"format_map": fmt_map, "unit": unit}

    if intent == "list_values":
        col = qident(u["list_column"])
        where3 = _where_sql(_filters_sql(filters))
        sql = ("SELECT DISTINCT %s FROM %s%s ORDER BY 1 LIMIT %d"
               % (col, table, where3, LIST_VALUES_LIMIT))
        return sql, {"format_map": {}, "unit": None}

    if intent == "count_distinct":
        col = qident(u["list_column"])
        sql = ("SELECT COUNT(DISTINCT %s) AS \"count\" FROM %s%s LIMIT %d"
               % (col, table, where, SQL_MAX_ROWS))
        return sql, {"format_map": {"count": "count"}, "unit": None}

    raise ValueError("no deterministic builder for intent %r" % intent)


# =============================================================================
# 8. CUSTOM SQL — LLM generation contract + GUARD
# =============================================================================

SQLGEN_PROMPT = (
    "You write ONE PostgreSQL SELECT query answering the user's question on "
    "the single table described below. Output ONLY the SQL — no markdown "
    "fences, no commentary, no explanation.\n"
    "HARD RULES:\n"
    "- ONE statement, starting with SELECT or WITH. Read-only.\n"
    "- Query ONLY the table {table} — no other table, no DML/DDL.\n"
    "- Use the EXACT column names and the EXACT filter values given "
    "(case-sensitive). Never invent a column or a value.\n"
    "- {scenario_rule}\n"
    "- Always end with LIMIT {max_rows} or less.\n"
    "- Prefer clear aliases; round percentages to 1 decimal.\n"
)

SQLGEN_REPAIR_PROMPT = (
    "The SQL you produced failed. Fix it and output ONLY the corrected SQL "
    "(one read-only SELECT on the same single table, same rules).\n"
    "DATABASE ERROR:\n{error}\n\nFAILED SQL:\n{sql}\n"
)


def build_dataset_card(profile, table):
    """Compact dataset card injected into the SQL-generation prompt."""
    lines = ["TABLE: %s" % table,
             "DATASET: %s — %s" % (profile.dataset_name,
                                   profile.description("en")[:300]),
             "GRAIN: %s" % (profile.raw.get("grain") or "one record"),
             "COLUMNS:"]
    for name, c in profile.columns.items():
        line = '- "%s" %s (%s)' % (name, c.get("dss_type", ""), c.get("role", ""))
        desc = c.get("description_en") or c.get("description_fr")
        if desc:
            line += ": %s" % desc[:120]
        if c.get("is_enum") and c.get("values"):
            line += " | values: %s" % ", ".join(
                "'%s'" % v["v"] for v in c["values"][:ENUM_VALUES_IN_CARD])
        lines.append(line)
    if profile.metrics:
        lines.append("METRICS:")
        for m in profile.metrics:
            lines.append("- %s = %s" % (m["name"], metric_expr(m)))
    tm = profile.time
    if tm:
        lines.append("TIME COLUMN: \"%s\" format=%s coverage %s -> %s"
                     % (tm["column"], tm["format"], tm.get("min"), tm.get("max")))
    return "\n".join(lines)


ENUM_VALUES_IN_CARD = 30

_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|"
    r"vacuum|call|do|execute|reset|listen|notify|refresh|lock|comment|merge|"
    r"into|set)\b", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\blimit\s+(\d+)\s*;?\s*$", re.IGNORECASE)


def _strip_sql_noise(sql):
    s = re.sub(r"^```(?:sql)?\s*|\s*```$", "", str(sql or "").strip(),
               flags=re.MULTILINE).strip()
    s = re.sub(r"--[^\n]*", " ", s)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.DOTALL)
    return s.strip().rstrip(";").strip()


def _allowed_table_names(table):
    """Set of normalized spellings under which the target table may appear."""
    raw = str(table)
    no_quotes = raw.replace('"', "")
    names = {raw.lower(), no_quotes.lower()}
    if "." in no_quotes:
        names.add(no_quotes.split(".")[-1].lower())
    return names


def guard_custom_sql(sql, table, max_rows=SQL_MAX_ROWS):
    """Validate + normalize an LLM-written SQL. Returns (sql, None) on
    success, (None, reason) on rejection. Defense in depth on top of the
    read-only transaction: single SELECT, one whitelisted table, no DML/DDL
    keywords, LIMIT enforced and capped."""
    s = _strip_sql_noise(sql)
    if not s:
        return (None, "empty")
    if ";" in s:
        return (None, "multiple_statements")
    head = s.lstrip().lower()
    if not (head.startswith("select") or head.startswith("with")):
        return (None, "not_a_select")
    if _FORBIDDEN_SQL.search(s):
        return (None, "forbidden_keyword")

    allowed = _allowed_table_names(table)
    cte_names = set()
    for m in re.finditer(r"(?:\bwith\b|,)\s*\"?([A-Za-z_][A-Za-z0-9_]*)\"?\s+as\s*\(",
                         s, re.IGNORECASE):
        cte_names.add(m.group(1).lower())
    for m in re.finditer(r"\b(?:from|join)\s+([\"A-Za-z0-9_.]+|\()", s, re.IGNORECASE):
        token = m.group(1)
        if token == "(":
            continue
        norm = token.replace('"', "").lower()
        short = norm.split(".")[-1]
        if norm in allowed or short in allowed or norm in cte_names or short in cte_names:
            continue
        return (None, "table_not_allowed:%s" % token[:60])

    lm = _LIMIT_RE.search(s)
    if lm:
        if int(lm.group(1)) > max_rows:
            s = _LIMIT_RE.sub("LIMIT %d" % max_rows, s)
    else:
        s = s + " LIMIT %d" % max_rows
    return (s, None)


# =============================================================================
# 8b. SEMANTIC MODEL QUERY ENGINE — composer + tool-output extraction
# -----------------------------------------------------------------------------
# The semantic question is 100% deterministic (frozen templates per intent):
# the LLM never writes it. It carries everything the upstream layers earned —
# exact catalog values from the resolver, explicit scenario values, explicit
# period bounds, the axis + display rule — plus the DESTINATION CONTEXT (the
# tool must know its SQL feeds a result table that an LLM reads to answer).
# =============================================================================

SEMANTIC_DESTINATION_NOTE = (
    "CONTEXT: the SQL you generate will produce a result table that is "
    "displayed to the user AND read by another LLM to write the final "
    "answer. Return a clean tabular result with explicit column aliases "
    "(one column per figure, plus the grouping label columns) — never a "
    "prose-only answer.")


# --- transparency disclosure (offer-hierarchy / multi-column value) ----------
def _pretty_col(name):
    """'SolutionLine' -> 'Solution Line', 'sirano_product' -> 'sirano product'."""
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(name or ""))
    return s.replace("_", " ")


DISCLOSE_NOTE = {
    "fr": ("ℹ️ « {value} » existe à plusieurs niveaux de l'offre ({cols}) ; le "
           "niveau le plus précis est privilégié par défaut — précisez si vous "
           "vouliez un autre niveau."),
    "en": ("ℹ️ \"{value}\" exists at several offer levels ({cols}); the most "
           "granular level is used by default — tell me if you meant another "
           "level."),
}


def build_disclosure_notes(filters, lang):
    """Deterministic transparency lines: when a resolved value exists in several
    columns (an offer term that is also a Solution/SolutionLine/sirano code),
    disclose the ambiguity and the default policy WITHOUT asserting which level
    the semantic model picked (it decides). Pure; carries no figures, so it
    never affects the verified headline."""
    lines = []
    for f in filters or []:
        alts = f.get("alt_columns") or []
        if not alts:
            continue
        cols = [f.get("column", "")] + list(alts)
        lines.append(DISCLOSE_NOTE.get(lang, DISCLOSE_NOTE["en"]).format(
            value=f.get("value", ""),
            cols=" / ".join(_pretty_col(c) for c in cols if c)))
    return "\n\n".join(lines)


def build_semantic_question(u, profile, filters):
    """Compose the message for the Semantic Model Query tool. Pure and
    deterministic.

    Philosophy (revised 2026-06-15): the Semantic Model Query tool runs on a
    SMART model (Sonnet) WITH the semantic layer — it understands the dataset
    far better than our small UNDERSTAND model. So this message gives it the
    user's REAL question as the source of truth, then our layers ASSIST it with
    HINTS (a deterministic intent shape, the values/columns the grounding helper
    matched in the live catalog, the preferred presentation, scenario, period).
    Hints are help, NOT orders: the tool keeps the final say. We never force a
    column choice — when a value spans offer levels we SUGGEST the most granular
    and flag the alternative for the tool (and the user)."""
    intent = u["intent"]
    metric = profile.metric(u["metric"] or "") or profile.default_metric
    parts = ['USER QUESTION (this is the source of truth — answer THIS): "%s"'
             % u["instruction"]]

    metric_part = ""
    if metric is not None:
        metric_part = "the %s (%s)" % (metric["name"], metric_expr(metric))

    scen = profile.scenario
    scen_values = []
    if scen:
        scen_values = u["scenarios"] or scen.get("default_values") or scen["values"][:1]

    def axis_sentence(axis):
        col = profile.column(axis) or {}
        # display_columns (list) takes precedence; fall back to display_column.
        displays = [d for d in (col.get("display_columns")
                                or ([col.get("display_column")]
                                    if col.get("display_column") else []))
                    if d and d != axis]
        s = "broken down by %s" % axis
        if displays:
            maxes = " and ".join("MAX(%s) AS %s" % (d, d) for d in displays)
            nevers = " or ".join(displays)
            # Identifier axis with human labels (e.g. diamond_id -> Account_name
            # + carrier_code): keep the id but as the LAST, least-emphasized col.
            tail = (", and keep %s as the LAST, least-emphasized column" % axis
                    if len(displays) > 1 else "")
            s += (". Group by %s ONLY and return %s for display%s; "
                  "never group by %s" % (axis, maxes, tail, nevers))
        return s

    # Deterministic intent hint (guidance, not a replacement of the question).
    hint = ""
    if intent == "total":
        hint = "One aggregated figure: the total of %s." % metric_part
    elif intent in ("breakdown", "top_n"):
        order = "ascending" if u["order"] == "asc" else "descending"
        hint = ("%s %s, ordered by the metric %s%s."
                % (metric_part.capitalize(), axis_sentence(u["group_by"]),
                   order,
                   ", keeping only the top %d" % u["top_n"]
                   if intent == "top_n" else ""))
    elif intent == "share_of_total":
        hint = ("%s %s, with for each row its share of the grand total as a "
                "percentage column named share_pct (1 decimal), ordered by "
                "the metric descending%s."
                % (metric_part.capitalize(), axis_sentence(u["group_by"]),
                   ", keeping only the top %d" % u["top_n"] if u["top_n"] else ""))
    elif intent == "compare_scenarios":
        a, b = u["scenarios"][0], u["scenarios"][1]
        hint = ("Compare %s across the %s values %s: one column per value, "
                "plus the delta amount (%s minus %s) and the delta percentage "
                "versus %s." % (metric_part, (scen or {}).get("column", "scenario"),
                                " and ".join(u["scenarios"]), a, b, b))
        if u["group_by"]:
            hint += " Break the comparison down %s." % axis_sentence(u["group_by"])
        scen_values = u["scenarios"]
    elif intent == "compare_periods":
        descr = "; ".join("%s: from %s to %s" % (p["label"], p["start"], p["end"])
                          for p in u["periods"])
        hint = ("Compare %s across the following periods: %s. One column per "
                "period (aliased with the period label), plus the delta "
                "amount and the delta percentage between the periods."
                % (metric_part, descr))
    elif intent == "trend":
        hint = ("The monthly %s grouped by month, ordered chronologically."
                % metric_part)
    elif intent == "list_values":
        hint = ("The distinct values of %s, ordered alphabetically (at most "
                "%d values)." % (u["list_column"], LIST_VALUES_LIMIT))
    elif intent == "count_distinct":
        hint = "The count of distinct values of %s." % u["list_column"]
    if hint:
        parts.append("EXPECTED SHAPE (guidance, use your judgment): " + hint)

    # Helper findings, presented as HINTS (not orders). A value matched to a
    # SINGLE column is a confident, catalog-exact spelling (e.g. a customer
    # name) -> suggested directly. A value that exists in SEVERAL columns (an
    # ambiguous offer term like 'EVPL', both a Product and a Solution) is NOT
    # pinned to a column: the smart semantic model resolves it with its own
    # hierarchy rules + the user's intent (proven more reliable than our small
    # helper, whose column pick can be wrong — e.g. defaulting to sirano_product).
    if filters:
        confident = [f for f in filters if not f.get("alt_columns")]
        ambiguous = [f for f in filters if f.get("alt_columns")]
        if confident:
            by_col, col_order = {}, []
            for f in confident:
                col = f["column"]
                if col not in by_col:
                    by_col[col] = []
                    col_order.append(col)
                by_col[col].append(str(f["value"]).replace("'", "''"))
            lines = []
            for col in col_order:
                vals = by_col[col]
                if len(vals) == 1:
                    lines.append("%s = '%s'" % (col, vals[0]))
                else:
                    lines.append("%s IN (%s)" % (col, ", ".join("'%s'" % v
                                                                for v in vals)))
            parts.append(
                "HELPER FINDINGS — a grounding assistant matched these values in "
                "the live catalog (exact, typo-free spellings). They are HINTS to "
                "ASSIST you, NOT orders — prefer them when consistent with the "
                "data; you keep the final say. Suggested: %s." % "; ".join(lines))
        for f in ambiguous:
            cols = [f["column"]] + [c for c in (f.get("alt_columns") or [])]
            parts.append(
                "AMBIGUOUS OFFER TERM — \"%s\" is a real data value present in "
                "SEVERAL columns (%s). Do NOT take a pinned column from the "
                "helper here: YOU resolve it, using your offer-hierarchy rules "
                "and the user's intent, then disclose the level you picked."
                % (f["value"], ", ".join(cols)))
        if len(confident) > 1:
            parts.append(
                "If the question ENUMERATES several of these as items to report, "
                "treat them independently (OR) and return ONE ROW PER ITEM with a "
                "clear label; only combine constraints of DIFFERENT kinds (e.g. a "
                "sales channel + an offer) with AND. (Guidance — your judgment.)")

    if scen and intent not in ("list_values",):
        parts.append("SCENARIO (guidance): unless the question implies "
                     "otherwise, consider rows whose %s is in: %s."
                     % (scen["column"], ", ".join(scen_values)))

    tm = profile.time
    if tm and intent != "compare_periods":
        if u["period"]["mode"] == "explicit":
            parts.append("PERIOD: only include rows with %s between %s and %s."
                         % (tm["column"], u["period"]["start"], u["period"]["end"]))
        else:
            parts.append("PERIOD: do not apply any filter on %s." % tm["column"])

    parts.append(SEMANTIC_DESTINATION_NOTE)
    return " ".join(parts)


# --- tool-output extraction (ported from SalesDrive v2, hardened for the
# tool's AGENT MODE) ------------------------------------------------------------
# Agent mode returns a multi-message transcript (reasoning -> schema
# exploration -> probe queries -> final answer). Two consequences, both seen
# live in DSS (2026-06-12: the relayed "answer" was "I'll start by exploring
# the schema..."):
#   - the ANSWER must be selected by KEY PRIORITY (answer/output_text beat a
#     generic text) and, within a priority, the LAST occurrence wins (the
#     final message), never the first (the reasoning preamble);
#   - the TABULAR RESULT keeps the LAST occurrence too (probe-query results
#     come before the final result set).

_SEM_ROW_KEYS = ("rows", "records", "data", "result_rows", "values")
_SEM_COLUMN_KEYS = ("columns", "column_names", "headers")
_SEM_SQL_KEYS = ("sql", "query", "generated_sql")
# key -> priority (lower wins); within a priority the LAST occurrence wins.
_SEM_ANSWER_KEY_PRIORITY = {"answer": 0, "output_text": 0, "completion": 1,
                            "text": 2, "result": 3}
_SEM_MAX_WALK_DEPTH = 50


def extract_tabular_node(outputs):
    """Capped {columns, rows, truncated} from one dict node, or None.
    Accepted shapes: list of dicts, or list of lists + a sibling columns key."""
    for key in _SEM_ROW_KEYS:
        raw = outputs.get(key)
        if not isinstance(raw, list) or not raw:
            continue
        if all(isinstance(r, dict) for r in raw):
            first_keys = list(raw[0].keys())
            columns = [str(c)[:_RESULT_CELL_MAX_CHARS]
                       for c in first_keys[:MAX_RESULT_COLS]]
            rows = [[_cap_cell(r.get(c)) for c in first_keys[:MAX_RESULT_COLS]]
                    for r in raw[:MAX_RESULT_ROWS]]
            truncated = len(raw) > MAX_RESULT_ROWS or len(first_keys) > MAX_RESULT_COLS
        elif all(isinstance(r, (list, tuple)) for r in raw):
            columns, truncated_cols = None, False
            for col_key in _SEM_COLUMN_KEYS:
                cand = outputs.get(col_key)
                if isinstance(cand, list) and cand:
                    columns = [str(c)[:_RESULT_CELL_MAX_CHARS]
                               for c in cand[:MAX_RESULT_COLS]]
                    truncated_cols = len(cand) > MAX_RESULT_COLS
                    break
            if columns is None:
                continue
            rows = [[_cap_cell(c) for c in list(r)[:MAX_RESULT_COLS]]
                    for r in raw[:MAX_RESULT_ROWS]]
            truncated = (len(raw) > MAX_RESULT_ROWS or truncated_cols
                         or any(len(r) > MAX_RESULT_COLS for r in raw[:MAX_RESULT_ROWS]))
        else:
            continue
        result = {"columns": columns, "rows": rows, "truncated": bool(truncated)}
        try:
            serialized = json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            return None
        if len(serialized) > _RESULT_JSON_MAX_CHARS:
            return {"columns": columns, "rows": [], "truncated": True}
        return result
    return None


def extract_semantic_payload(raw_output):
    """Best-effort structured payload from the Semantic Model Query tool
    return value: {"sqls": [str], "result": {...}|None, "answer": str|None,
    "row_count": int|None, "shape_keys": [str]}. Defensive walker — the exact
    output schema is instance-dependent; absence stays honest (None).
    Agent-mode safe: answer by key priority + LAST occurrence; tabular result
    and row_count = LAST occurrence (final result set, not probe queries)."""
    payload = {"sqls": [], "result": None, "answer": None,
               "row_count": None, "shape_keys": []}
    if not isinstance(raw_output, dict):
        return payload
    root = (raw_output.get("output")
            if isinstance(raw_output.get("output"), dict) else raw_output)
    payload["shape_keys"] = sorted(str(k) for k in root.keys())[:30]

    answer_candidates = []   # (priority, walk_order, text)
    state = {"order": 0}

    def _walk(node, depth):
        if depth > _SEM_MAX_WALK_DEPTH:
            return
        if isinstance(node, dict):
            for key in _SEM_SQL_KEYS:
                val = node.get(key)
                if isinstance(val, str) and val.strip() and val not in payload["sqls"]:
                    payload["sqls"].append(val)
            found = extract_tabular_node(node)
            if found is not None:
                payload["result"] = found          # last occurrence wins
            if isinstance(node.get("row_count"), int):
                payload["row_count"] = node["row_count"]   # last wins
            for key, prio in _SEM_ANSWER_KEY_PRIORITY.items():
                val = node.get(key)
                if isinstance(val, str) and val.strip():
                    state["order"] += 1
                    answer_candidates.append((prio, state["order"], val.strip()))
            for v in node.values():
                _walk(v, depth + 1)
        elif isinstance(node, list):
            for item in node:
                _walk(item, depth + 1)

    _walk(root, 0)
    if answer_candidates:
        best_prio = min(c[0] for c in answer_candidates)
        payload["answer"] = max((c for c in answer_candidates
                                 if c[0] == best_prio),
                                key=lambda c: c[1])[2]
    if payload["row_count"] is None and payload["result"] is not None:
        payload["row_count"] = len(payload["result"]["rows"])
    return payload


_SEMANTIC_KEY_CANDIDATES = ("question", "query", "user_question", "input", "text")


def pick_semantic_input_key(descriptor):
    """Auto-detect the input key of the Semantic Model Query tool from its
    descriptor's inputSchema. Pure, never raises."""
    try:
        props = ((descriptor or {}).get("inputSchema") or {}).get("properties") or {}
        if not isinstance(props, dict) or not props:
            return SEMANTIC_QUESTION_KEY
        for cand in _SEMANTIC_KEY_CANDIDATES:
            if cand in props:
                return cand
        str_props = [k for k, v in props.items()
                     if isinstance(v, dict) and v.get("type") == "string"]
        if len(str_props) == 1:
            return str_props[0]
    except Exception:
        pass
    return SEMANTIC_QUESTION_KEY


# =============================================================================
# 9. RESULT SHAPING (caps mirror the orchestrator/webapp)
# =============================================================================

def _cap_cell(value):
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return str(value)[:_RESULT_CELL_MAX_CHARS]


def shape_result(columns, row_tuples):
    """(columns, iterable of tuples) -> {columns, rows, truncated} capped."""
    cols = [str(c)[:_RESULT_CELL_MAX_CHARS] for c in (columns or [])[:MAX_RESULT_COLS]]
    truncated = len(columns or []) > MAX_RESULT_COLS
    rows = []
    for i, t in enumerate(row_tuples or []):
        if i >= MAX_RESULT_ROWS:
            truncated = True
            break
        cells = list(t)[:MAX_RESULT_COLS]
        if len(list(t)) > MAX_RESULT_COLS:
            truncated = True
        rows.append([_cap_cell(c) for c in cells])
    result = {"columns": cols, "rows": rows, "truncated": bool(truncated)}
    try:
        serialized = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        return {"columns": cols, "rows": [], "truncated": True}
    if len(serialized) > _RESULT_JSON_MAX_CHARS:
        return {"columns": cols, "rows": [], "truncated": True}
    return result


# =============================================================================
# 10. RENDER — formats, table, verified headline
# =============================================================================

def format_int_thousands(value):
    sign = "-" if value < 0 else ""
    digits = str(abs(int(value)))
    groups = []
    while digits:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    return sign + NBSP.join(groups)


def format_number(value, fmt, unit=None):
    """Format one numeric value by declared format (profile-driven — no
    business keyword sniffing)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if fmt == "percent":
        txt = ("%.1f" % v).rstrip("0").rstrip(".")
        return (txt or "0") + NBSP + "%"
    if fmt in ("amount", "count", "number"):
        text = format_int_thousands(int(round(v)))
        if fmt == "amount" and unit:
            return text + NBSP + str(unit)
        if fmt == "number" and not float(v).is_integer():
            return ("%.2f" % v)
        return text
    return str(value)


def _column_format(name, fmt_map, profile):
    if name in (fmt_map or {}):
        return fmt_map[name]
    low = str(name).lower()
    if any(tok in low for tok in ("pct", "percent", "%", "share", "ratio")):
        return "percent"
    for m in profile.metrics:
        if m.get("column") and m["column"].lower() in low or m["name"] in low:
            return m.get("format", "number")
    if any(tok in low for tok in ("count", "nb_", "num_")):
        return "count"
    # Semantic-tool result aliases are free-form ("total_revenue", scenario
    # pivot columns named after the scenario values): when the dataset's
    # default metric is an amount, recognize those shapes — gated on the
    # PROFILE (no hardcoded business words beyond generic metric vocabulary).
    dm = profile.default_metric or {}
    if dm.get("format") == "amount":
        scen = profile.scenario or {}
        scen_words = {str(v).lower() for v in (scen.get("values") or [])}
        if (low in scen_words
                or any(tok in low for tok in ("amount", "revenue", "revenu",
                                              "total", "delta", "eur"))):
            return "amount"
    return None


def format_cell(value, column_name, fmt_map, profile, unit=None):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        fmt = _column_format(column_name, fmt_map, profile)
        if fmt:
            return format_number(value, fmt, unit)
        if isinstance(value, float) and not float(value).is_integer():
            return "%.2f" % value
        return format_int_thousands(int(value))
    return str(value)


def build_table(result, lang, fmt_map, profile, unit=None):
    if not result or not result.get("rows"):
        return ""
    columns = result.get("columns") or []
    rows = result["rows"]
    lines = ["| " + " | ".join(str(c) for c in columns) + " |",
             "|" + "|".join(" --- " for _ in columns) + "|"]
    for row in rows[:TABLE_MAX_ROWS]:
        cells = [format_cell(v, columns[i] if i < len(columns) else "",
                             fmt_map, profile, unit)
                 for i, v in enumerate(row)]
        lines.append("| " + " | ".join(cells) + " |")
    table = "\n".join(lines)
    extra = len(rows) - TABLE_MAX_ROWS
    if extra > 0:
        table += "\n\n" + MORE_ROWS_NOTE[lang].format(n=extra)
    if result.get("truncated"):
        table += "\n\n" + TRUNCATED_NOTE[lang]
    return table


def _scope_label(u, profile, lang):
    parts = []
    if u["scenarios"]:
        parts.append(", ".join(u["scenarios"]))
    elif profile.scenario:
        parts.append(", ".join(profile.scenario.get("default_values") or []))
    if u["period"]["mode"] == "explicit":
        parts.append(u["period"]["label"])
    elif profile.time:
        parts.append(PERIOD_ALL_LABEL[lang])
    return ", ".join(p for p in parts if p) or profile.dataset_name


def build_fallback_headline(u, profile, result, lang, fmt_map, unit=None):
    scope = _scope_label(u, profile, lang)
    if u["intent"] == "lookup":
        return HEADLINE_LOOKUP[lang]
    if result and len(result.get("rows") or []) == 1:
        row = result["rows"][0]
        columns = result.get("columns") or []
        numeric = [(columns[i] if i < len(columns) else "", v)
                   for i, v in enumerate(row)
                   if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(numeric) == 1:
            col, val = numeric[0]
            fmt = _column_format(col, fmt_map, profile) or "number"
            metric = profile.metric(u["metric"] or "") or profile.default_metric or {}
            label = metric.get("label_%s" % lang) or metric.get("label_en") or col
            return HEADLINE_SINGLE[lang].format(
                metric=label, scope=scope,
                value=format_number(val, fmt, unit))
    return HEADLINE_FALLBACK[lang].format(scope=scope)


# --- verified LLM headline (ported, frozen rule) ------------------------------

_NUM_TOKEN_RE = re.compile(r"\d(?:[\d\s.,  ]*\d)?")


def _digits(text):
    return re.sub(r"\D", "", str(text))


def allowed_number_set(result, extra_texts):
    allowed = set()
    if result:
        for row in result.get("rows") or []:
            for cell in row:
                if isinstance(cell, bool):
                    continue
                if isinstance(cell, (int, float)):
                    allowed.add(_digits(repr(cell)))
                    try:
                        allowed.add(_digits(str(int(round(float(cell))))))
                        allowed.add(_digits(str(abs(int(round(float(cell)))))))
                    except (OverflowError, ValueError):
                        pass
                    if isinstance(cell, float):
                        allowed.add(_digits("%.1f" % cell))
                        allowed.add(_digits("%.2f" % cell))
                elif isinstance(cell, str):
                    full = _digits(cell)
                    if full:
                        allowed.add(full)
                    for group in re.findall(r"\d+", cell):
                        allowed.add(group)
    for text in extra_texts or []:
        for group in re.findall(r"\d+", str(text)):
            allowed.add(group)
    allowed.discard("")
    return allowed


def verify_headline(text, allowed):
    """True iff EVERY number cited exists in the allowed set. One unverifiable
    figure -> the whole headline is rejected (frozen rule)."""
    if not text:
        return False
    for token in _NUM_TOKEN_RE.findall(text):
        nd = _digits(token)
        if nd and nd not in allowed:
            return False
    return True


HEADLINE_PROMPT = (
    "You write the OPENING of a data answer: one short sentence carrying the "
    "main figure(s), optionally followed by ONE short business signal "
    "sentence IF it is directly visible in the table (large variance, sharp "
    "drop, spike). Plain text only — no markdown, no emoji, no greeting.\n"
    "HARD RULES:\n"
    "- Write in this language: {language}.\n"
    "- Every figure MUST be copied EXACTLY from the RESULT TABLE (no "
    "rounding, no unit conversion, no computed figures).\n"
    "- Never speculate, never suggest alternative filters.\n"
)


# =============================================================================
# 11. ABOUT_DATA — deterministic dataset card answer (zero SQL, zero LLM)
# =============================================================================

def build_about_answer(profile, lang):
    lines = [ABOUT_HEADER[lang], "", "**%s** — %s"
             % (profile.dataset_name, profile.description(lang))]
    grain = profile.raw.get("grain")
    if grain:
        lines.append("_%s_" % grain)
    row_count = profile.raw.get("row_count")
    if row_count:
        lines.append("\n%s : %s lignes" % (ABOUT_ROWS[lang], format_int_thousands(int(row_count)))
                     if lang == "fr" else
                     "\n%s: %s rows" % (ABOUT_ROWS[lang], format_int_thousands(int(row_count))))
    if profile.metrics:
        lines.append("\n%s :" % ABOUT_METRICS[lang] if lang == "fr"
                     else "\n%s:" % ABOUT_METRICS[lang])
        for m in profile.metrics:
            label = m.get("label_%s" % lang) or m.get("label_en") or m["name"]
            desc = (" — " + m["description"]) if m.get("description") else ""
            lines.append("- %s%s" % (label, desc))
    scen = profile.scenario
    if scen:
        lines.append("\n%s : %s" % (ABOUT_SCENARIOS[lang], ", ".join(scen["values"]))
                     if lang == "fr" else
                     "\n%s: %s" % (ABOUT_SCENARIOS[lang], ", ".join(scen["values"])))
    tm = profile.time
    if tm and (tm.get("min") or tm.get("max")):
        lines.append("\n%s : %s → %s" % (ABOUT_PERIOD[lang], tm.get("min"), tm.get("max"))
                     if lang == "fr" else
                     "\n%s: %s → %s" % (ABOUT_PERIOD[lang], tm.get("min"), tm.get("max")))
    axes = []
    for name in profile.groupable_columns():
        c = profile.column(name) or {}
        if c.get("role") == "dimension":
            desc = c.get("description_%s" % lang) or c.get("description_en") or ""
            axes.append("- **%s**%s" % (name, (" — " + desc[:100]) if desc else ""))
    if axes:
        lines.append("\n%s :" % ABOUT_AXES[lang] if lang == "fr"
                     else "\n%s:" % ABOUT_AXES[lang])
        lines.extend(axes[:15])
    return "\n".join(lines)


# =============================================================================
# 12. EVENTS (same dialect as a DSS visual agent)
# =============================================================================

# Declared event contract (FROZEN): every blockId / toolName this agent can
# emit. The orchestrator registry MUST label exactly these ids — the
# anti-drift test (dataiku-agents/tests/test_orchestrator_v3.py) enforces it.
KNOWN_BLOCK_IDS = ("resolve", "run_sql", "lookup", "format_output", "clarify_user",
                   "out_of_scope_msg", "about_data")
KNOWN_TOOL_NAMES = ("resolve_filter_value", "dataset_sql_query", "dataset_lookup")


def _ev(kind, data=None):
    return {"chunk": {"type": "event", "eventKind": kind, "eventData": data or {}}}


def _block(block_id):
    return _ev("AGENT_BLOCK_START", {"blockId": block_id})


def _tool_start(tool_name):
    return _ev("AGENT_TOOL_START", {"toolName": tool_name})


def _agent_result(status, u, resolved_filters=None, sql_count=0,
                  row_count=None, attempts=0):
    return _ev("AGENT_RESULT", {
        "status": status,
        "language": (u or {}).get("language", "fr"),
        "intent": (u or {}).get("intent", ""),
        "resolvedFilters": resolved_filters or [],
        "sqlCount": sql_count,
        "rowCount": row_count,
        "attempts": attempts,
    })


# =============================================================================
# 13. AGENT
# =============================================================================

class ExpertState(TypedDict, total=False):
    """LangGraph state: the pipeline is linear (no parallel writes), so no
    reducers are needed — every channel is last-write."""
    instruction: str
    context: str
    llm_id: str                 # mode-resolved model for this run (eco/medium/high)
    semantic_tool_id: str       # mode-resolved semantic-model tool id
    lang: str
    u: dict
    resolutions: list
    filters: list
    resolved_filters: list
    result: dict
    fmt_map: dict
    unit: object
    tool_answer: str
    tool_row_count: int
    executed: list
    done: bool


class MyLLM(BaseLLM):

    def __init__(self):
        self._profile = None
        self._profile_loaded_at = 0.0
        self._table = None
        self._tools = {}
        self._semantic_key = None    # auto-detected from the tool descriptor

    # ------------------------------------------------------------------ tools
    def _get_tool(self, project, tool_id, tool_name):
        """get_agent_tool(tool_id) with a one-shot fallback matching tool_name
        against list_agent_tools() (covers a recreated tool whose id changed).
        Proven pattern from SalesDrive v2 (validated in DSS)."""
        if tool_id in self._tools:
            return self._tools[tool_id]
        tool = None
        try:
            tool = project.get_agent_tool(tool_id)
            tool.get_descriptor()      # force a roundtrip to validate the id
        except Exception:
            tool = None
            try:
                for item in project.list_agent_tools():
                    raw = item if isinstance(item, dict) else getattr(item, "raw", {})
                    name = str(raw.get("name") or "")
                    if tool_name.lower() in name.lower():
                        tool = project.get_agent_tool(raw.get("id") or name)
                        break
            except Exception:
                logger.exception("Tool lookup failed for %s (%s)", tool_id, tool_name)
        if tool is None:
            raise RuntimeError("Agent tool not found: %s (%s)" % (tool_id, tool_name))
        self._tools[tool_id] = tool
        return tool

    # ------------------------------------------------------------- knowledge
    def _get_profile(self):
        """Profile with in-process TTL cache. Raises RuntimeError when the
        profile dataset is unreadable/absent (handled as PROFILE_MISSING)."""
        now = time.time()
        if self._profile is not None and now - self._profile_loaded_at < PROFILE_TTL_SECONDS:
            return self._profile
        rows = _read_dataset_rows(PROFILE_DATASET, ("key", "payload"))
        profile = parse_profile_rows(rows)
        if profile is None or not profile.dataset_name:
            raise RuntimeError("profile dataset unusable: %s" % PROFILE_DATASET)
        # Attach the live schema column names (best-effort, never breaks loading):
        # lookups can then reach attribute columns absent from a stale profile.
        try:
            profile.live_columns = _read_live_columns(profile.dataset_name)
        except Exception:
            logger.warning("could not read live schema for %s", profile.dataset_name)
            profile.live_columns = []
        self._profile = profile
        self._profile_loaded_at = now
        self._table = None    # re-resolve with the fresh profile
        return profile

    def _get_table(self, dataset_name):
        """Fully-qualified quoted table name of the target dataset."""
        if self._table:
            return self._table
        info = dataiku.Dataset(dataset_name).get_location_info().get("info", {})
        table = info.get("quotedResolvedTableName")
        if not table:
            schema_name, table_name = info.get("schema"), info.get("table")
            if not table_name:
                raise RuntimeError("cannot resolve SQL table for %s" % dataset_name)
            table = ('"%s"."%s"' % (schema_name, table_name) if schema_name
                     else '"%s"' % table_name)
        self._table = table
        return table

    # ------------------------------------------------------------------ SQL
    def _run_sql(self, dataset_name, sql, max_rows=MAX_RESULT_ROWS):
        """Read-only execution -> (columns, row_tuples). Raises on SQL error
        (callers decide whether to repair). Tries the streaming reader first
        to avoid a pandas dependency, falls back to query_to_df. max_rows
        bounds the FETCH (answer queries keep the Evidence cap; the value
        resolver raises it to read its candidate slices)."""
        executor = dataiku.SQLExecutor2(dataset=dataiku.Dataset(dataset_name))
        try:
            reader = executor.query_to_iter(sql, pre_queries=list(SQL_PRE_QUERIES))
            schema = reader.get_schema()
            columns = [c.get("name") if isinstance(c, dict) else getattr(c, "name", str(c))
                       for c in schema]
            rows = []
            for i, t in enumerate(reader.iter_tuples()):
                if i >= max_rows + 1:
                    break
                rows.append(tuple(t))
            return columns, rows
        except AttributeError:
            pass    # SDK without query_to_iter shapes -> dataframe path
        df = executor.query_to_df(sql, pre_queries=list(SQL_PRE_QUERIES))
        columns = [str(c) for c in df.columns]
        rows = [tuple(r) for r in df.head(max_rows + 1).itertuples(index=False,
                                                                   name=None)]
        return columns, rows

    def _explain(self, dataset_name, sql):
        executor = dataiku.SQLExecutor2(dataset=dataiku.Dataset(dataset_name))
        executor.query_to_df("EXPLAIN " + sql, pre_queries=list(SQL_PRE_QUERIES))

    # ----------------------------------------------------------- dataset lookup
    def _lookup_rows(self, project, lookup_filter, filters, attributes):
        """Run the Dataiku Dataset Lookup tool for a plain attribute retrieval and
        return a shaped {columns, rows} result (or None when no row matched). The
        returned columns = the filter columns (entity context) + the requested
        attributes; rows are deduplicated (the fact table has many rows per entity)
        and capped. Raises on a tool error so the caller can fall back to SQL."""
        tool = self._get_tool(project, DATASET_LOOKUP_TOOL_ID,
                              DATASET_LOOKUP_TOOL_NAME)
        raw = tool.run({"filter": lookup_filter})
        rows = extract_lookup_rows(raw)
        if not rows:
            return None
        # Projection: filter columns first (which entity), then the attributes.
        cols = []
        for c in [f.get("column") for f in (filters or [])] + list(attributes or []):
            if c and c not in cols:
                cols.append(c)
        if not cols:                       # nothing requested -> surface all columns
            cols = list(rows[0].keys())[:MAX_RESULT_COLS]
        seen, tuples = set(), []
        for r in rows:
            t = tuple(r.get(c) for c in cols)
            if t in seen:
                continue
            seen.add(t)
            tuples.append(t)
            if len(tuples) >= MAX_RESULT_ROWS:
                break
        return shape_result(cols, tuples)

    def _resolve_terms(self, profile, base_terms, trace):
        """Ground terms on the value index (exact-norm pass + per-term fuzzy
        pass). Returns resolver-contract resolutions."""
        index_table = dataiku.Dataset(VALUE_INDEX_DATASET).get_location_info() \
            .get("info", {}).get("quotedResolvedTableName")
        if not index_table:
            raise RuntimeError("value index dataset is not SQL: %s" % VALUE_INDEX_DATASET)
        indexed_cols = set(profile.indexed_columns())

        norms = {t: _norm(t) for t in base_terms}
        resolutions = []

        # Pass 1: one query, exact normalized matches for every term.
        exact_rows = {}
        norm_list = sorted({n for n in norms.values() if n})
        if norm_list:
            fetch_cap = max(200, 20 * len(norm_list))
            sql = ("SELECT column_name, value, value_norm, occurrences FROM %s "
                   "WHERE value_norm IN (%s) LIMIT %d"
                   % (index_table,
                      ", ".join(_sql_quote_literal(n) for n in norm_list),
                      fetch_cap))
            columns, rows = self._run_sql(VALUE_INDEX_DATASET, sql,
                                          max_rows=fetch_cap)
            idx = {c: i for i, c in enumerate(columns)}
            for t in rows:
                vnorm = str(t[idx.get("value_norm", 2)])
                exact_rows.setdefault(vnorm, []).append({
                    "column_name": t[idx.get("column_name", 0)],
                    "value": t[idx.get("value", 1)],
                    "value_norm": vnorm,
                    "occurrences": t[idx.get("occurrences", 3)],
                })

        for term in base_terms:
            tn = norms[term]
            rows = exact_rows.get(tn) or []
            if not rows:
                # Pass 2 (per unmatched term): substring + fuzzy ranking.
                like = "%" + _like_escape(tn) + "%"
                sql = ("SELECT column_name, value, value_norm, occurrences FROM %s "
                       "WHERE value_norm LIKE %s ESCAPE '\\' "
                       "ORDER BY occurrences DESC LIMIT %d"
                       % (index_table, _sql_quote_literal(like),
                          FUZZY_CANDIDATES_LIMIT))
                try:
                    columns, raw = self._run_sql(VALUE_INDEX_DATASET, sql,
                                                 max_rows=FUZZY_CANDIDATES_LIMIT)
                    idx = {c: i for i, c in enumerate(columns)}
                    rows = [{"column_name": t[idx.get("column_name", 0)],
                             "value": t[idx.get("value", 1)],
                             "value_norm": t[idx.get("value_norm", 2)],
                             "occurrences": t[idx.get("occurrences", 3)]}
                            for t in raw]
                except Exception:
                    logger.exception("Fuzzy index lookup failed for %r", term)
                    rows = []
                if not rows:
                    # Last chance: fetch a bounded slice and fuzzy-rank in
                    # Python (typo like 'halys' -> 'HALYS' already matched by
                    # norm; this covers heavier typos on short catalogs).
                    sql = ("SELECT column_name, value, value_norm, occurrences "
                           "FROM %s ORDER BY occurrences DESC LIMIT 5000"
                           % index_table)
                    try:
                        columns, raw = self._run_sql(VALUE_INDEX_DATASET, sql,
                                                     max_rows=5000)
                        idx = {c: i for i, c in enumerate(columns)}
                        rows = [{"column_name": t[idx.get("column_name", 0)],
                                 "value": t[idx.get("value", 1)],
                                 "value_norm": t[idx.get("value_norm", 2)],
                                 "occurrences": t[idx.get("occurrences", 3)]}
                                for t in raw]
                    except Exception:
                        rows = []

            rows = [r for r in rows if str(r.get("column_name") or "") in indexed_cols
                    or not indexed_cols]
            candidates = rank_candidates(tn, rows)
            exact_cands = [c for c in candidates
                           if _norm(c["target_value"]) == tn]
            if exact_cands:
                distinct_cols = {c["target_column"] for c in exact_cands}
                if len(distinct_cols) == 1 and len(
                        {c["target_value"] for c in exact_cands}) == 1:
                    c = exact_cands[0]
                    resolutions.append({"raw_value": term, "status": "resolved",
                                        "target_column": c["target_column"],
                                        "target_value": c["target_value"],
                                        "display_value": c["display_value"],
                                        "method": "exact_norm", "confidence": 100})
                else:
                    resolutions.append({"raw_value": term, "status": "ambiguous",
                                        "candidates": exact_cands[:8]})
            elif candidates and candidates[0]["score"] >= FUZZY_MIN_RATIO:
                strong = [c for c in candidates if c["score"] >= FUZZY_MIN_RATIO][:8]
                if len(strong) == 1 and strong[0]["score"] >= 0.9:
                    c = strong[0]
                    resolutions.append({"raw_value": term, "status": "resolved",
                                        "target_column": c["target_column"],
                                        "target_value": c["target_value"],
                                        "display_value": c["display_value"],
                                        "method": "fuzzy", "confidence":
                                            int(c["score"] * 100)})
                else:
                    resolutions.append({"raw_value": term, "status": "ambiguous",
                                        "candidates": strong})
            else:
                best = candidates[0] if candidates else None
                resolutions.append({"raw_value": term, "status": "unresolved",
                                    "best_candidate": best or {}})
        return resolutions

    # ------------------------------------------------------------------- LLM
    def _call_json_llm(self, project, system_prompt, user_msg, schema, span,
                       llm_id=None):
        """2 attempts: native JSON mode (with_json_output) then prompt-only.

        UNDERSTAND is a DETERMINISTIC extraction (scope / intent / terms), NOT a
        reasoning task — forcing the JSON schema is what makes it reliable (the
        proven behavior of the original agent). In DSS 14 forced JSON disables
        the model's reasoning for THIS call only, which is what we want here: a
        clean, fast parse instead of a long 'thinking' pass that returns prose
        the parser cannot read. Reasoning stays ON where it helps (the
        orchestrator's routing, the verified headline). If the model/connection
        rejects json mode, the guarded attempt 1 still runs as a plain
        completion and attempt 2 is prompt-only."""
        llm = project.get_llm(llm_id or UNDERSTAND_LLM_ID)
        for attempt, use_json_mode in ((1, True), (2, False)):
            try:
                completion = llm.new_completion()
                if use_json_mode:
                    try:
                        completion.with_json_output(schema=schema)
                    except Exception:
                        pass
                completion.with_message(system_prompt, role="system")
                completion.with_message(user_msg, role="user")
                resp = completion.execute()
                try:
                    if resp.trace:
                        span.append_trace(resp.trace)
                except Exception:
                    pass
                parsed = _safe_json_parse(getattr(resp, "text", None))
                if parsed:
                    span.attributes["attempt"] = attempt
                    return parsed
            except Exception as e:
                logger.warning("JSON LLM attempt %d failed: %s", attempt, e)
                span.attributes["attempt_%d_error" % attempt] = str(e)[:300]
        return None

    def _llm_text(self, project, llm_id, system_prompt, user_msg, span, cap):
        try:
            llm = project.get_llm(llm_id)
            completion = llm.new_completion() \
                .with_message(system_prompt, role="system") \
                .with_message(user_msg, role="user")
            resp = completion.execute()
            try:
                if resp.trace:
                    span.append_trace(resp.trace)
            except Exception:
                pass
            text = (getattr(resp, "text", None) or "").strip()
            return text[:cap] if text else None
        except Exception as e:
            logger.warning("LLM text call failed: %s", e)
            span.attributes["error"] = str(e)[:300]
            return None

    # ------------------------------------------------------------------ MAIN
    def process_stream(self, query, settings, trace):
        """LangGraph entrypoint. Drives a StateGraph
        UNDERSTAND -> RESOLVE -> QUERY -> RENDER (with out-of-scope / clarify /
        about / no-data gates as conditional edges to END). Every stage calls
        the SAME engine functions as the validated linear original (in git
        history for rollback) — only the control flow is a graph; behavior is
        identical. Live timeline events are emitted through LangGraph's custom
        stream writer."""
        try:
            project = dataiku.api_client().get_default_project()
            instruction, conversation_context = self._extract_input(query)
            if not instruction:
                yield {"chunk": {"text": INTERNAL_ERROR_TEXT["fr"]}}
                yield _agent_result("error", None)
                return
            try:
                profile = self._get_profile()
            except Exception:
                logger.exception("Profile unavailable")
                yield {"chunk": {"text": PROFILE_MISSING_TEXT["fr"]}}
                yield _agent_result("error", None)
                return
            # Model tier for THIS run, propagated by the orchestrator (eco=mini,
            # medium=Gemini Flash, high=Sonnet). Threaded through the graph state so
            # node closures never read per-request state off `self` (concurrency-safe).
            mode = forced_mode(conversation_context) or DEFAULT_MODE
            graph = self._build_graph(project, profile, trace)
            initial = {"instruction": instruction,
                       "context": conversation_context, "done": False,
                       "llm_id": pick_subagent_llm(mode),
                       "semantic_tool_id": pick_semantic_tool_id(mode)}
            for chunk in graph.stream(initial, stream_mode="custom",
                                      config={"recursion_limit": 12}):
                yield chunk
        except Exception:
            logger.exception("Dataset expert failure")
            yield {"chunk": {"text": INTERNAL_ERROR_TEXT["fr"]}}
            yield _agent_result("error", None)

    # ---- LangGraph wiring (nodes call the SAME engine; closures bind ctx) ---
    def _build_graph(self, project, profile, trace):
        sa = self                                # access engine helpers in nodes

        def n_understand(state):
            writer = get_stream_writer()
            instruction = state["instruction"]
            context = state.get("context") or ""
            writer(_block("resolve"))
            user_msg = 'QUESTION: "%s"\nReturn ONLY the JSON object.' % instruction
            if context:
                user_msg = context + "\n\n" + user_msg
            with trace.subspan("dataset-expert:understand") as sp:
                sp.inputs["question"] = instruction
                sp.inputs["has_context"] = bool(context)
                parsed = sa._call_json_llm(
                    project,
                    build_understand_prompt(profile,
                                            datetime.now().strftime("%Y-%m-%d")),
                    user_msg, build_understand_schema(profile), sp,
                    llm_id=state.get("llm_id"))
                u = validate_understanding(parsed, profile, instruction)
                # The orchestrator's pinned language (the USER's real language) wins
                # over the sub-agent's own guess on the English-ish self-contained task.
                pinned = forced_language(context)
                if u is not None and pinned:
                    u["language"] = pinned
                sp.outputs["understanding"] = u
            if u is None:
                writer({"chunk": {"text": INTERNAL_ERROR_TEXT["fr"]}})
                writer(_agent_result("error", None))
                return {"done": True}
            lang = u["language"]
            if u["scope"] == "out_of_scope":
                writer(_block("out_of_scope_msg"))
                writer({"chunk": {"text": OUT_OF_SCOPE_TEXT[lang].format(
                    label=profile.description(lang)[:120])}})
                writer(_agent_result("out_of_scope", u))
                return {"u": u, "lang": lang, "done": True}
            if u["clarification"]:
                writer(_block("clarify_user"))
                writer({"chunk": {"text": u["clarification"]}})
                writer(_agent_result("need_clarification", u))
                return {"u": u, "lang": lang, "done": True}
            if u["intent"] == "about_data":
                writer(_block("about_data"))
                writer({"chunk": {"text": build_about_answer(profile, lang)}})
                writer(_agent_result("ready", u))
                return {"u": u, "lang": lang, "done": True}
            return {"u": u, "lang": lang, "done": False}

        def n_resolve(state):
            writer = get_stream_writer()
            u, lang = state["u"], state["lang"]
            resolutions, filters = [], []
            if u["terms"]:
                preferred_columns, base_terms = {}, []
                for t in u["terms"]:
                    q = parse_qualified_term(t, profile)
                    if q:
                        preferred_columns[q[1].strip().lower()] = q[0]
                        base_terms.append(q[1])
                    else:
                        base_terms.append(t)
                writer(_tool_start("resolve_filter_value"))
                with trace.subspan("dataset-expert:resolve-values") as sp:
                    sp.inputs["raw_values"] = base_terms
                    try:
                        resolutions = sa._resolve_terms(profile, base_terms, trace)
                    except Exception as e:
                        logger.exception("Value resolution failed")
                        sp.attributes["error"] = str(e)[:500]
                        writer({"chunk": {"text": INTERNAL_ERROR_TEXT[lang]}})
                        writer(_agent_result("error", u))
                        return {"done": True}
                    refined = []
                    for r in resolutions:
                        if r.get("status") == "ambiguous":
                            pref = preferred_columns.get(
                                str(r.get("raw_value") or "").strip().lower())
                            verdict, data = refine_ambiguous(
                                profile, r.get("raw_value"), r.get("candidates"), pref)
                            if verdict == "resolved":
                                refined.append({
                                    "raw_value": r.get("raw_value", ""),
                                    "status": "resolved",
                                    "target_column": data.get("target_column", ""),
                                    "target_value": data.get("target_value", ""),
                                    "display_value": data.get("display_value", "")
                                                     or data.get("target_value", ""),
                                    "alt_columns": data.get("alt_columns") or [],
                                    "method": "ambiguity_policy", "confidence": 100})
                                continue
                            r = dict(r, candidates=data)
                        refined.append(r)
                    resolutions = refined
                    filters = build_filter_clauses(resolutions)
                    sp.outputs["statuses"] = [r.get("status") for r in resolutions]
                    sp.outputs["filters"] = filters
                if any(r.get("status") in ("ambiguous", "unresolved")
                       for r in resolutions):
                    clarification = build_clarification(resolutions, lang)
                    writer(_block("clarify_user"))
                    writer({"chunk": {"text": clarification or
                            CLARIFY_UNRESOLVED[lang].format(
                                raw=", ".join(u["terms"]), hint="")}})
                    writer(_agent_result("need_clarification", u,
                           resolved_filters=resolved_filters_summary(resolutions)))
                    return {"done": True}
            return {"resolutions": resolutions, "filters": filters,
                    "resolved_filters": resolved_filters_summary(resolutions),
                    "done": False}

        def n_query(state):
            writer = get_stream_writer()
            u, lang = state["u"], state["lang"]
            filters = state.get("filters") or []
            resolved_filters = state.get("resolved_filters") or []
            instruction = state["instruction"]
            table = sa._get_table(profile.dataset_name)
            executed = []
            result, fmt_map, unit = None, {}, None
            tool_answer = None
            tool_row_count = None
            det_failed = None
            engine = SQL_ENGINE

            # --- LOOKUP path (no SQL): a plain attribute retrieval of named
            # entities goes straight to the Dataset Lookup tool. On a tool error or
            # no resolvable filter, demote to "custom" and fall through to SQL. ---
            if u["intent"] == "lookup" and DATASET_LOOKUP_ENABLED:
                lookup_filter = build_lookup_filter(filters)
                if lookup_filter is None:
                    u["intent"] = "custom"          # nothing to look up -> SQL path
                else:
                    writer(_block("lookup"))
                    writer(_tool_start("dataset_lookup"))
                    with trace.subspan("dataset-expert:lookup") as sp:
                        sp.inputs["filter"] = lookup_filter
                        sp.inputs["attributes"] = u.get("attributes")
                        try:
                            result = sa._lookup_rows(project, lookup_filter,
                                                     filters, u.get("attributes"))
                            sp.outputs["row_count"] = (len(result["rows"])
                                                       if result else 0)
                        except Exception as e:
                            logger.exception("Dataset lookup failed -> SQL fallback")
                            sp.attributes["error"] = str(e)[:500]
                            result, u["intent"] = None, "custom"
                    if u["intent"] == "lookup":      # lookup ran (rows or empty)
                        note = lookup_note(lookup_filter, u.get("attributes"))
                        if result is not None and result.get("rows"):
                            # Frozen 'semantic-model-query' span so Evidence + the
                            # orchestrator capture the rows (the 'sql' is an honest
                            # note: it was a direct lookup, not a generated query).
                            with trace.subspan("semantic-model-query") as qsp:
                                qsp.outputs["sql"] = note
                                qsp.outputs["success"] = True
                                qsp.outputs["row_count"] = len(result["rows"])
                                qsp.outputs["columns"] = result["columns"]
                                qsp.outputs["rows"] = result["rows"]
                            executed.append({"sql": note, "success": True,
                                             "row_count": len(result["rows"])})
                        return {"result": result, "fmt_map": {}, "unit": None,
                                "tool_answer": None,
                                "tool_row_count": (len(result["rows"])
                                                   if result else 0),
                                "executed": executed, "done": False}

            writer(_block("run_sql"))
            writer(_tool_start("dataset_sql_query"))

            if engine == "semantic_tool":
                payload = None
                semantic_question = build_semantic_question(u, profile, filters)
                with trace.subspan("dataset-expert:semantic-tool") as sp:
                    sp.inputs["semantic_question"] = semantic_question
                    try:
                        tool = sa._get_tool(project,
                                            state.get("semantic_tool_id") or SEMANTIC_TOOL_ID,
                                            SEMANTIC_TOOL_NAME)
                        if sa._semantic_key is None:
                            try:
                                sa._semantic_key = pick_semantic_input_key(
                                    tool.get_descriptor())
                            except Exception:
                                sa._semantic_key = SEMANTIC_QUESTION_KEY
                        sp.attributes["input_key"] = sa._semantic_key
                        raw = tool.run({sa._semantic_key: semantic_question})
                        payload = extract_semantic_payload(raw)
                        sp.outputs["shape_keys"] = payload["shape_keys"]
                        sp.outputs["sql_count"] = len(payload["sqls"])
                        sp.outputs["row_count"] = payload["row_count"]
                        result = payload["result"]
                        tool_answer = payload["answer"]
                        tool_row_count = payload["row_count"]
                        unit = (profile.metric(u["metric"] or "")
                                or profile.default_metric or {}).get("unit")
                    except Exception as e:
                        logger.exception(
                            "Semantic tool failed%s",
                            " -> direct engine fallback" if FALLBACK_TO_DIRECT else "")
                        sp.attributes["error"] = str(e)[:500]
                        if not FALLBACK_TO_DIRECT:
                            writer({"chunk": {"text": INTERNAL_ERROR_TEXT[lang]}})
                            writer(_agent_result("error", u,
                                   resolved_filters=resolved_filters))
                            return {"done": True}
                        engine = "direct"
                if engine == "semantic_tool":
                    sqls = (payload or {}).get("sqls") or []
                    # The tool's RESULT belongs to the FINAL query it ran (when it
                    # generates several — e.g. a query then a repaired variant). The
                    # webapp's Evidence/chart pick the LAST successful SQL, so the
                    # captured rows/columns MUST ride the LAST span, not the first —
                    # otherwise the active item carries no result ("not kept") and
                    # the chart cannot render (fix for the multi-SQL case).
                    last_i = len(sqls) - 1
                    for i, sql in enumerate(sqls):
                        with trace.subspan("semantic-model-query") as qsp:
                            qsp.outputs["sql"] = sql
                            qsp.outputs["success"] = True
                            qsp.outputs["row_count"] = tool_row_count
                            if i == last_i and result is not None:
                                qsp.outputs["columns"] = result["columns"]
                                qsp.outputs["rows"] = result["rows"]
                        executed.append({"sql": sql, "success": True,
                                         "row_count": tool_row_count})

            if engine == "direct" and u["intent"] != "custom":
                try:
                    sql, meta = build_sql(u, profile, filters, table)
                    fmt_map, unit = meta["format_map"], meta.get("unit")
                except ValueError as e:
                    logger.info("No deterministic SQL (%s) -> custom path", e)
                    u["intent"] = "custom"
                else:
                    with trace.subspan("semantic-model-query") as sp:
                        sp.outputs["sql"] = sql
                        try:
                            columns, rows = sa._run_sql(profile.dataset_name, sql)
                            result = shape_result(columns, rows)
                            sp.outputs["success"] = True
                            sp.outputs["row_count"] = len(result["rows"])
                            sp.outputs["columns"] = result["columns"]
                            sp.outputs["rows"] = result["rows"]
                            executed.append({"sql": sql, "success": True,
                                             "row_count": len(result["rows"])})
                        except Exception as e:
                            logger.exception("Deterministic SQL failed -> "
                                             "falling back to custom path")
                            sp.outputs["success"] = False
                            sp.attributes["error"] = str(e)[:500]
                            executed.append({"sql": sql, "success": False,
                                             "error": str(e)[:200]})
                            det_failed = (sql, str(e)[:500])
                            fmt_map, unit = {}, None
                            u["intent"] = "custom"

            if engine == "direct" and u["intent"] == "custom":
                card = build_dataset_card(profile, table)
                scen = profile.scenario
                scenario_rule = ("No scenario column." if not scen else
                                 ('The column "%s" holds scenario values (%s): '
                                  "NEVER aggregate across several of them "
                                  "unless the question asks a comparison. "
                                  "Default filter: %s."
                                  % (scen["column"], ", ".join(scen["values"]),
                                     ", ".join(scen.get("default_values") or []))))
                system = SQLGEN_PROMPT.format(table=table,
                                              scenario_rule=scenario_rule,
                                              max_rows=SQL_MAX_ROWS)
                filt_text = ("RESOLVED FILTER VALUES (use verbatim): " +
                             "; ".join("%s = '%s'" % (f["column"], f["value"])
                                       for f in filters)) if filters else ""
                user_block = "%s\n\n%s\nQUESTION: %s" % (card, filt_text, instruction)
                if det_failed:
                    user_block += ("\n\nA PREVIOUS ATTEMPT FAILED — avoid this "
                                   "mistake.\nFAILED SQL:\n%s\nDATABASE ERROR:\n%s"
                                   % det_failed)
                sql, last_error = None, None
                sqlgen_llm = state.get("llm_id") or SQLGEN_LLM_ID or UNDERSTAND_LLM_ID
                for attempt in range(1, MAX_CUSTOM_SQL_ATTEMPTS + 1):
                    with trace.subspan("dataset-expert:sqlgen") as sp:
                        sp.attributes["attempt"] = attempt
                        if attempt == 1:
                            raw_sql = sa._llm_text(project, sqlgen_llm,
                                                   system, user_block, sp, 4000)
                        else:
                            raw_sql = sa._llm_text(
                                project, sqlgen_llm,
                                system,
                                user_block + "\n\n" + SQLGEN_REPAIR_PROMPT.format(
                                    error=last_error or "", sql=sql or ""), sp, 4000)
                    guarded, reason = guard_custom_sql(raw_sql, table)
                    if guarded is None:
                        last_error = "guard rejected: %s" % reason
                        executed.append({"sql": (raw_sql or "")[:2000],
                                         "success": False, "error": last_error})
                        continue
                    sql = guarded
                    with trace.subspan("semantic-model-query") as sp:
                        sp.outputs["sql"] = sql
                        sp.attributes["attempt"] = attempt
                        try:
                            sa._explain(profile.dataset_name, sql)
                            columns, rows = sa._run_sql(profile.dataset_name, sql)
                            result = shape_result(columns, rows)
                            sp.outputs["success"] = True
                            sp.outputs["row_count"] = len(result["rows"])
                            sp.outputs["columns"] = result["columns"]
                            sp.outputs["rows"] = result["rows"]
                            executed.append({"sql": sql, "success": True,
                                             "row_count": len(result["rows"])})
                            break
                        except Exception as e:
                            last_error = str(e)[:500]
                            sp.outputs["success"] = False
                            sp.attributes["error"] = last_error
                            executed.append({"sql": sql, "success": False,
                                             "error": last_error[:200]})
                            result = None
                if result is None:
                    writer({"chunk": {"text": INTERNAL_ERROR_TEXT[lang]}})
                    writer(_agent_result("error", u,
                           resolved_filters=resolved_filters,
                           sql_count=len(executed), attempts=len(executed)))
                    return {"done": True}

            return {"result": result, "fmt_map": fmt_map, "unit": unit,
                    "tool_answer": tool_answer, "tool_row_count": tool_row_count,
                    "executed": executed, "done": False}

        def n_render(state):
            writer = get_stream_writer()
            u, lang = state["u"], state["lang"]
            result = state.get("result")
            fmt_map = state.get("fmt_map") or {}
            unit = state.get("unit")
            tool_answer = state.get("tool_answer")
            tool_row_count = state.get("tool_row_count")
            executed = state.get("executed") or []
            resolved_filters = state.get("resolved_filters") or []
            instruction = state["instruction"]
            disclosure = build_disclosure_notes(state.get("filters") or [], lang)
            writer(_block("format_output"))
            if (not result or not result.get("rows")) and tool_answer:
                writer({"chunk": {"text": tool_answer
                        + (("\n\n" + disclosure) if disclosure else "")}})
                writer(_agent_result("ready", u, resolved_filters=resolved_filters,
                       sql_count=len(executed), row_count=tool_row_count,
                       attempts=len(executed)))
                return {"done": True}
            if not result or not result.get("rows"):
                hint = ""
                scen = profile.scenario
                if scen and u["scenarios"]:
                    hint += NO_DATA_HINT_SCENARIO[lang].format(
                        values=", ".join(scen["values"]))
                tm = profile.time
                if tm and u["period"]["mode"] == "explicit" and (tm.get("min")
                                                                 or tm.get("max")):
                    hint += NO_DATA_HINT_PERIOD[lang].format(min=tm.get("min"),
                                                             max=tm.get("max"))
                writer({"chunk": {"text": NO_DATA_TEXT[lang] + hint}})
                writer(_agent_result("no_data", u,
                       resolved_filters=resolved_filters,
                       sql_count=len(executed), row_count=0,
                       attempts=len(executed)))
                return {"done": True}
            table_md = build_table(result, lang, fmt_map, profile, unit)
            headline = build_fallback_headline(u, profile, result, lang,
                                               fmt_map, unit)
            # The LLM headline is now REDUNDANT: the orchestrator writes the
            # user-facing analysis from this result, so a slow extra reasoning call
            # here (often ~tens of seconds) only adds latency. Default OFF -> use
            # the deterministic, hallucination-proof fallback headline (the
            # orchestrator comments on top). Flip SUBAGENT_LLM_HEADLINE on only if
            # the sub-agent is ever used stand-alone (no orchestrator wrapper).
            if SUBAGENT_LLM_HEADLINE:
                allowed = allowed_number_set(
                    result, [instruction, u["period"].get("label", ""),
                             " ".join(p.get("label", "") for p in u["periods"])])
                with trace.subspan("dataset-expert:headline") as sp:
                    candidate = sa._llm_text(
                        project,
                        HEADLINE_LLM_ID or state.get("llm_id") or UNDERSTAND_LLM_ID,
                        HEADLINE_PROMPT.replace("{language}", lang),
                        "USER QUESTION: %s\n\nRESULT TABLE:\n%s" % (instruction,
                                                                    table_md),
                        sp, HEADLINE_MAX_CHARS)
                    if candidate and verify_headline(candidate, allowed):
                        headline = candidate
                        sp.outputs["verified"] = True
                    else:
                        sp.outputs["verified"] = False
            writer({"chunk": {"text": headline + "\n\n" + table_md
                    + (("\n\n" + disclosure) if disclosure else "")}})
            writer(_agent_result("ready", u, resolved_filters=resolved_filters,
                   sql_count=len(executed), row_count=len(result["rows"]),
                   attempts=len(executed)))
            return {"done": True}

        def route(next_node):
            def _r(state):
                return END if state.get("done") else next_node
            return _r

        g = StateGraph(ExpertState)
        g.add_node("understand", n_understand)
        g.add_node("resolve", n_resolve)
        g.add_node("query", n_query)
        g.add_node("render", n_render)
        g.add_edge(START, "understand")
        g.add_conditional_edges("understand", route("resolve"),
                                {"resolve": "resolve", END: END})
        g.add_conditional_edges("resolve", route("query"),
                                {"query": "query", END: END})
        g.add_conditional_edges("query", route("render"),
                                {"render": "render", END: END})
        g.add_edge("render", END)
        return g.compile()

    # ---------------------------------------------------------------- INPUT
    @staticmethod
    def _extract_input(query):
        """(instruction, conversation_context): last user message + the
        orchestrator-injected system context (pass_context continuity)."""
        msgs = query.get("messages", []) or []
        instruction = ""
        for m in reversed(msgs):
            if m.get("role") == "user" and m.get("content"):
                instruction = m["content"]
                break
        context = "\n".join(m["content"] for m in msgs
                            if m.get("role") == "system" and m.get("content"))
        return instruction, context.strip()
