# =============================================================================
# OWIsMind dataset profiler (Dataiku Python recipe, design-time Flow).
#
# Builds a machine-readable "profile" of a dataset: the knowledge artifact that
# makes the dataset-expert sub-agent fluent in that dataset. Only AGGREGATED
# metadata (schema, stats, low-cardinality values, a few samples) ever reaches
# the LLM, never raw rows.
#
# Flow    : INPUT 1 = dataset to profile; INPUT 2 (optional) = editable overrides
#           {key, field, value}; OUTPUT = profile {key, payload(JSON)}.
# Passes  : A = deterministic stats (zero LLM); B = LLM enrichment (descriptions,
#           roles, synonyms, metrics, scenario/time election), flagged
#           llm_generated. Human overrides are applied LAST and always win.
# Contract: profile v1, rows {key, payload}; key "__dataset__" = table-level,
#           key "<column>" = per-column. Fields summarized in recipes/README.md;
#           time.format is one of TIME_FORMATS.
# =============================================================================

import json
import logging
import math
import re
import unicodedata
from datetime import datetime

import dataiku

# pandas is imported lazily inside the two functions that need it (the local test
# env has no pandas, and the pure helpers below must import without it). numpy is
# optional too: json_safe degrades gracefully when it is absent.
try:
    import numpy as np
except Exception:
    np = None

logger = logging.getLogger("owismind.profiler")

# =============================================================================
# 1. CONFIGURATION
# =============================================================================

# LLM Mesh id for the enrichment pass (PASS B). Use the strongest model: it runs
# once per dataset and the cost is amortized over every future question. Set to
# "" to skip the LLM pass (deterministic profile only, descriptions left empty).
ENRICH_LLM_ID = "openai:LLM-7064-revforecast:vertex_ai/claude-opus-4-7"

ENUM_MAX_VALUES = 50        # <= N distincts: keep the full verbatim value list
SAMPLES_N = 12              # sample values kept per non-enum column
SAMPLE_VALUE_MAX_CHARS = 80
MAX_ROWS_IN_MEMORY = 2_000_000   # safety cap for get_dataframe()
FREE_TEXT_AVG_LEN = 120     # avg length above which a string column = free text
PROFILE_VERSION = 1

# Value-index parity: the profile `indexed` flag MUST match which columns the
# value-index recipe actually grounds, because UNDERSTAND advertises groundable
# columns from `indexed` and RESOLVE filters its catalog candidates to them. If
# `indexed` stays empty, UNDERSTAND is told "labels of: (none)", the model never
# extracts a named entity (e.g. a customer name) as a term, grounding is skipped
# and the SQL writer is left to GUESS the value. Keep INDEX_MAX_DISTINCT /
# INDEX_ID_UNIQUENESS_RATIO and should_index_value_column() in sync with
# build_value_index_recipe.py (same rule, intentionally duplicated like norm_value).
INDEX_MAX_DISTINCT = 20000
INDEX_ID_UNIQUENESS_RATIO = 0.95

KNOWN_ROLES = ("dimension", "measure", "time", "scenario", "identifier",
               "free_text", "other")
KNOWN_AGGS = ("SUM", "AVG", "COUNT", "COUNT_DISTINCT", "MIN", "MAX")
KNOWN_FORMATS = ("amount", "count", "percent", "number")
TIME_FORMATS = ("date", "yyyy_mm_dd_str", "yyyy_mm_str", "yyyymm_int",
                "year_int")

_NUMERIC_DSS_TYPES = ("tinyint", "smallint", "int", "bigint", "float",
                      "double", "decimal")
_DATE_DSS_TYPES = ("date", "datetime")

_RE_YYYY_MM_DD = re.compile(r"^\d{4}-\d{2}-\d{2}")
_RE_YYYY_MM = re.compile(r"^\d{4}-\d{2}$")


# =============================================================================
# 2. PURE HELPERS (unit-tested in tests/test_profiler.py)
# =============================================================================

def norm_value(value):
    """Accent-insensitive lowercase with collapsed whitespace. Same as the
    value-index recipe and the agent resolver (FROZEN normalization)."""
    s = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s.strip().lower())


def json_safe(value):
    """numpy / pandas scalars -> plain JSON-safe Python values (non-finite -> None)."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if np is not None:
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            f = float(value)
            return f if math.isfinite(f) else None
        if isinstance(value, np.bool_):
            return bool(value)
    return str(value)[:SAMPLE_VALUE_MAX_CHARS * 4]


def detect_time_format(dss_type, sample_values):
    """Best-effort time format from the DSS type + a few samples; one of
    TIME_FORMATS or None. Pure and defensive."""
    if dss_type in _DATE_DSS_TYPES:
        return "date"
    samples = [s for s in (sample_values or []) if s is not None][:20]
    if not samples:
        return None
    texts = [str(s).strip() for s in samples]
    if all(_RE_YYYY_MM_DD.match(t) for t in texts):
        return "yyyy_mm_dd_str"
    if all(_RE_YYYY_MM.match(t) for t in texts):
        return "yyyy_mm_str"
    ints = []
    for t in texts:
        try:
            ints.append(int(float(t)))
        except (TypeError, ValueError):
            return None
    if all(190001 <= i <= 209912 and 1 <= i % 100 <= 12 for i in ints):
        return "yyyymm_int"
    if all(1900 <= i <= 2100 for i in ints):
        return "year_int"
    return None


def looks_like_time_name(name):
    low = str(name).lower()
    return any(tok in low for tok in ("date", "month", "year", "period",
                                      "time", "annee", "mois", "jour"))


def time_name_rank(name):
    """Tie-break rank for the default time axis when several date columns exist.
    Prefer a CREATION / OPENED column (the natural event time axis) and avoid a
    close / update / detection column - otherwise a raw alphabetical sort can elect
    e.g. Latest_Closed_Date over creationDate, and a bare 'this year' window would
    silently drop every still-open record. Lower rank wins."""
    low = str(name).lower()
    if any(tok in low for tok in ("creat", "open", "start", "begin", "ouvert",
                                  "creation", "debut")):
        return 0
    if any(tok in low for tok in ("clos", "closed", "end", "resol", "ferm",
                                  "updat", "modif", "detect", "last")):
        return 2
    return 1


def _coerce_str_list(raw, cap=12, item_cap=60):
    """Trimmed, de-duplicated (case-insensitive) list of strings, capped."""
    out, seen = [], set()
    for item in (raw if isinstance(raw, list) else []):
        s = str(item).strip()
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s[:item_cap])
        if len(out) >= cap:
            break
    return out


def validate_enrichment(parsed, column_names):
    """Validate the LLM enrichment field by field; unknown columns/roles/aggs
    are dropped. Never raises. Returns {"dataset": {...}, "columns": {...}}."""
    out = {"dataset": {}, "columns": {}}
    if not isinstance(parsed, dict):
        return out
    known = set(column_names)

    ds = parsed.get("dataset")
    if isinstance(ds, dict):
        clean = {}
        for field in ("description_en", "description_fr", "grain"):
            v = ds.get(field)
            if isinstance(v, str) and v.strip():
                clean[field] = v.strip()[:600]

        metrics = []
        for m in (ds.get("metrics") or [])[:12]:
            if not isinstance(m, dict):
                continue
            agg = str(m.get("agg") or "").upper().replace(" ", "_")
            column = m.get("column")
            name = re.sub(r"[^a-z0-9_]", "_", str(m.get("name") or "").lower())[:40]
            if agg not in KNOWN_AGGS or not name:
                continue
            if agg != "COUNT" and column not in known:
                continue
            fmt = m.get("format") if m.get("format") in KNOWN_FORMATS else "number"
            unit = str(m.get("unit") or "").strip()[:8]
            metrics.append({
                "name": name, "agg": agg,
                "column": column if agg != "COUNT" else None,
                "format": fmt, "unit": unit or None,
                "label_fr": str(m.get("label_fr") or name)[:80],
                "label_en": str(m.get("label_en") or name)[:80],
                "description": str(m.get("description") or "")[:300],
            })
        if metrics:
            clean["metrics"] = metrics
            default = str(ds.get("default_metric") or "")
            clean["default_metric"] = (default if any(m["name"] == default for m in metrics)
                                       else metrics[0]["name"])

        scen = ds.get("scenario")
        if isinstance(scen, dict) and scen.get("column") in known:
            clean["scenario"] = {"column": scen["column"],
                                 "default_values": _coerce_str_list(scen.get("default_values"), cap=5)}
        tm = ds.get("time")
        if isinstance(tm, dict) and tm.get("column") in known:
            clean["time"] = {"column": tm["column"]}
        out["dataset"] = clean

    cols = parsed.get("columns")
    if isinstance(cols, dict):
        for name, payload in cols.items():
            if name not in known or not isinstance(payload, dict):
                continue
            clean = {}
            if payload.get("role") in KNOWN_ROLES:
                clean["role"] = payload["role"]
            for field in ("description_en", "description_fr"):
                v = payload.get(field)
                if isinstance(v, str) and v.strip():
                    clean[field] = v.strip()[:400]
            syns = _coerce_str_list(payload.get("synonyms"))
            if syns:
                clean["synonyms"] = syns
            disp = payload.get("display_column")
            if disp in known and disp != name:
                clean["display_column"] = disp
            if clean:
                out["columns"][name] = clean
    return out


def parse_override_value(raw):
    """Override 'value' cell -> JSON when parseable, else the trimmed string."""
    s = str(raw if raw is not None else "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


def apply_overrides(dataset_payload, column_payloads, override_rows):
    """Apply human {key, field, value} rows in place (humans always win).
    Unknown keys/fields are ignored. Returns the number applied."""
    applied = 0
    for row in override_rows or []:
        key = str(row.get("key") or "").strip()
        field = str(row.get("field") or "").strip()
        value = parse_override_value(row.get("value"))
        if not key or not field or value is None:
            continue
        if key == "__dataset__":
            dataset_payload[field] = value
            dataset_payload.setdefault("notes", [])
            applied += 1
        elif key in column_payloads:
            column_payloads[key][field] = value
            column_payloads[key]["human_override"] = True
            applied += 1
    return applied


def safe_json_parse(text):
    """Parse JSON from an LLM reply, tolerating ```fences``` and surrounding prose."""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()
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


def should_index_value_column(dss_type, distinct_count, row_count, avg_len):
    """Whether this column will be grounded in the value index. MUST mirror
    build_value_index_recipe.should_index_column (minus the per-recipe
    INCLUDE/EXCLUDE allowlists). Drives the profile `indexed` flag so UNDERSTAND
    advertises the right groundable columns and RESOLVE filters candidates to
    them. Skips numbers, dates, free text and quasi-unique long ids."""
    if dss_type in _NUMERIC_DSS_TYPES or dss_type in _DATE_DSS_TYPES:
        return False
    if distinct_count == 0 or distinct_count > INDEX_MAX_DISTINCT:
        return False
    if avg_len and avg_len > FREE_TEXT_AVG_LEN:
        return False
    if (row_count and distinct_count >= INDEX_ID_UNIQUENESS_RATIO * row_count
            and row_count > 1000):
        if avg_len and avg_len > 24:
            return False
    return True


def default_role(dss_type, distinct_count, row_count, avg_len, time_format, name):
    """Deterministic role when the LLM pass is skipped or silent."""
    if time_format:
        return "time"
    if dss_type in _NUMERIC_DSS_TYPES:
        return "measure"
    if avg_len and avg_len > FREE_TEXT_AVG_LEN:
        return "free_text"
    if row_count and distinct_count and distinct_count >= 0.9 * row_count:
        return "identifier"
    low = str(name).lower()
    if low.endswith("_id") or low.startswith("id_") or low == "id":
        return "identifier"
    return "dimension"


# =============================================================================
# 3. PASS A - deterministic statistics (pandas, design-time)
# =============================================================================

def profile_dataframe(df, schema_columns):
    """-> (dataset_payload, {column_name: column_payload}). Deterministic."""
    import pandas as pd

    row_count = int(len(df))
    dss_types = {c["name"]: str(c.get("type") or "string") for c in schema_columns}

    dataset_payload = {
        "profile_version": PROFILE_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "row_count": row_count,
        "description_en": "", "description_fr": "", "grain": "",
        "default_metric": None, "metrics": [],
        "scenario": None, "time": None, "notes": [],
    }

    columns = {}
    time_candidates = []
    for col in df.columns:
        name = str(col)
        series = df[col]
        dss_type = dss_types.get(name, "string")
        non_null = series.dropna()
        null_pct = round(100.0 * (1 - (len(non_null) / row_count)), 2) if row_count else 0.0
        distinct = int(non_null.nunique())

        payload = {
            "name": name, "dss_type": dss_type,
            "role": None, "description_en": "", "description_fr": "",
            "synonyms": [], "null_pct": null_pct, "distinct_count": distinct,
            "is_enum": False, "values": [], "samples": [], "stats": {},
            "display_column": None, "groupable": True, "indexed": False,
            "llm_generated": False,
        }

        sample_values = [json_safe(v) for v in non_null.head(50).tolist()][:50]
        avg_len = 0.0
        if dss_type not in _NUMERIC_DSS_TYPES and len(non_null):
            try:
                avg_len = float(non_null.astype(str).str.len().mean())
            except Exception:
                avg_len = 0.0

        # Time format. A real date/timestamp dtype wins over the schema type or
        # string samples, so a physical date is always profiled as "date".
        tfmt = None
        try:
            if pd.api.types.is_datetime64_any_dtype(series):
                tfmt = "date"
            elif len(non_null):
                first = non_null.iloc[0]
                if hasattr(first, "year") and not isinstance(first, (int, float)):
                    tfmt = "date"   # datetime.date / Timestamp objects
        except Exception:
            pass
        if tfmt is None:
            tfmt = detect_time_format(dss_type, sample_values)
        if tfmt and not looks_like_time_name(name) and dss_type not in _DATE_DSS_TYPES:
            # plausible but unnamed: low priority. (priority, name_rank, name, tfmt)
            time_candidates.append((1, time_name_rank(name), name, tfmt))
        elif tfmt:
            time_candidates.append((0, time_name_rank(name), name, tfmt))

        # Numeric columns get full stats; time columns get min/max only.
        if dss_type in _NUMERIC_DSS_TYPES and not tfmt:
            try:
                payload["stats"] = {
                    "min": json_safe(non_null.min()) if len(non_null) else None,
                    "max": json_safe(non_null.max()) if len(non_null) else None,
                    "sum": json_safe(non_null.sum()) if len(non_null) else None,
                    "avg": json_safe(non_null.mean()) if len(non_null) else None,
                }
            except Exception:
                payload["stats"] = {}
        elif tfmt:
            try:
                payload["stats"] = {
                    "min": str(json_safe(non_null.min()))[:32] if len(non_null) else None,
                    "max": str(json_safe(non_null.max()))[:32] if len(non_null) else None,
                }
            except Exception:
                payload["stats"] = {}

        # Low-cardinality non-time columns become enums (full value list); the
        # rest keep a few samples. Time columns are never enums (a month list
        # would bloat the prompt for nothing).
        if 0 < distinct <= ENUM_MAX_VALUES and not tfmt:
            payload["is_enum"] = True
            try:
                payload["values"] = [
                    {"v": str(json_safe(v))[:SAMPLE_VALUE_MAX_CHARS], "n": int(n)}
                    for v, n in non_null.value_counts().items()][:ENUM_MAX_VALUES]
            except Exception:
                payload["values"] = []
        else:
            payload["samples"] = [str(s)[:SAMPLE_VALUE_MAX_CHARS]
                                  for s in sample_values[:SAMPLES_N]]

        payload["role"] = default_role(dss_type, distinct, row_count, avg_len, tfmt, name)
        if payload["role"] in ("free_text", "measure"):
            payload["groupable"] = False
        # Derive the value-index parity flag so UNDERSTAND advertises groundable
        # columns and RESOLVE can match named entities (human overrides still win).
        payload["indexed"] = should_index_value_column(dss_type, distinct, row_count,
                                                       avg_len) and not tfmt
        if tfmt:
            payload["_time_format"] = tfmt   # promoted below, then dropped
        columns[name] = payload

    # Deterministic time election (the LLM may override). Named candidates win;
    # within them a creation/opened column beats a close/update column (time_name_rank).
    if time_candidates:
        time_candidates.sort()
        _, _, tname, tfmt = time_candidates[0]
        dataset_payload["time"] = {
            "column": tname, "format": tfmt,
            "min": (columns[tname].get("stats") or {}).get("min"),
            "max": (columns[tname].get("stats") or {}).get("max"),
        }
    return dataset_payload, columns


# =============================================================================
# 4. PASS B - LLM enrichment (aggregated metadata only, never raw rows)
# =============================================================================

ENRICH_PROMPT = (
    "You are a senior data analyst documenting a dataset so an AI agent can "
    "answer business questions about it with SQL. You receive AGGREGATED "
    "metadata only (schema, stats, distinct values, samples). Return ONE JSON "
    "object - no markdown fences, no commentary - with this exact shape:\n"
    "{\n"
    '  "dataset": {\n'
    '    "description_en": "...", "description_fr": "...",\n'
    '    "grain": "one row = ...",\n'
    '    "metrics": [{"name": "snake_case", "agg": "SUM|AVG|COUNT|COUNT_DISTINCT|MIN|MAX",\n'
    '                 "column": "<numeric column or null for COUNT>",\n'
    '                 "format": "amount|count|percent|number",\n'
    '                 "unit": "EUR" (optional, currency/unit for amount metrics),\n'
    '                 "label_fr": "...", "label_en": "...", "description": "..."}],\n'
    '    "default_metric": "<name of the most natural metric>",\n'
    '    "scenario": {"column": "<column>", "default_values": ["..."]} or null,\n'
    '    "time": {"column": "<main time column>"} or null\n'
    "  },\n"
    '  "columns": {"<column_name>": {"role": "dimension|measure|time|scenario|identifier|free_text|other",\n'
    '              "description_en": "...", "description_fr": "...",\n'
    '              "synonyms": ["user words for this column, EN and FR"],\n'
    '              "display_column": "<human-label column paired with this id column, or omit>"}}\n'
    "}\n"
    "RULES:\n"
    "- A 'scenario' column is a low-cardinality column whose values are "
    "VERSIONS of the same measures (e.g. actuals/budget/forecast phases, "
    "plan vs real). Mixing its values in one SUM double-counts: if such a "
    "column exists, declare it and pick the most factual value(s) as "
    "default_values (e.g. the 'actuals'-like one). If none exists, null.\n"
    "- Metrics must use ONLY listed numeric columns. Suggest 1-5 metrics, "
    "the business-obvious ones first.\n"
    "- 'display_column': when an identifier column has an obvious human "
    "label twin (e.g. customer_id <-> customer_name), set it on the ID "
    "column.\n"
    "- Descriptions: one dense sentence each, business language, both EN "
    "and FR. Synonyms: the words real users would type (abbreviations, FR "
    "and EN).\n"
    "- NEVER invent columns or values not present in the metadata.\n"
)


def build_enrichment_input(dataset_name, dataset_payload, columns):
    """Compact, aggregated-only description of the dataset for the LLM."""
    lines = ["DATASET: %s" % dataset_name,
             "ROW COUNT: %s" % dataset_payload.get("row_count")]
    tm = dataset_payload.get("time")
    if tm:
        lines.append("DETECTED TIME COLUMN: %s (format %s, %s -> %s)"
                     % (tm["column"], tm["format"], tm.get("min"), tm.get("max")))
    lines.append("COLUMNS:")
    for name, c in columns.items():
        desc = "- %s | type=%s | distinct=%s | nulls=%s%%" % (
            name, c["dss_type"], c["distinct_count"], c["null_pct"])
        if c.get("is_enum") and c.get("values"):
            desc += " | ALL VALUES: " + ", ".join(
                "%s(%s)" % (v["v"], v["n"]) for v in c["values"][:ENUM_MAX_VALUES])
        elif c.get("samples"):
            desc += " | samples: " + ", ".join(c["samples"][:8])
        if c.get("stats"):
            desc += " | stats: " + json.dumps(c["stats"], ensure_ascii=False, default=str)
        lines.append(desc)
    return "\n".join(lines)


def run_enrichment(project, dataset_name, dataset_payload, columns):
    """Call the Mesh model (2 attempts) and merge the validated output in place.
    Failure is non-fatal: the deterministic profile survives. Returns success."""
    if not ENRICH_LLM_ID:
        logger.info("ENRICH_LLM_ID empty -> skipping the LLM pass")
        return False
    user_block = build_enrichment_input(dataset_name, dataset_payload, columns)
    llm = project.get_llm(ENRICH_LLM_ID)
    parsed = None
    for attempt in (1, 2):
        try:
            completion = llm.new_completion()
            completion.with_message(ENRICH_PROMPT, role="system")
            completion.with_message(user_block, role="user")
            parsed = safe_json_parse(getattr(completion.execute(), "text", None))
            if parsed:
                break
        except Exception as e:
            logger.warning("Enrichment attempt %d failed: %s", attempt, e)
    if not parsed:
        logger.warning("LLM enrichment produced no usable JSON - profile stays deterministic")
        return False

    clean = validate_enrichment(parsed, list(columns.keys()))
    ds = clean["dataset"]
    for field in ("description_en", "description_fr", "grain"):
        if ds.get(field):
            dataset_payload[field] = ds[field]
    if ds.get("metrics"):
        dataset_payload["metrics"] = ds["metrics"]
        dataset_payload["default_metric"] = ds.get("default_metric")
    if ds.get("scenario"):
        scol = ds["scenario"]["column"]
        scen_values = [v["v"] for v in (columns[scol].get("values") or [])]
        defaults = [v for v in ds["scenario"].get("default_values") or []
                    if v in scen_values] or scen_values[:1]
        dataset_payload["scenario"] = {"column": scol, "values": scen_values,
                                       "default_values": defaults}
        columns[scol]["role"] = "scenario"
        columns[scol]["groupable"] = True
    if ds.get("time") and ds["time"]["column"] in columns:
        tcol = ds["time"]["column"]
        tfmt = columns[tcol].get("_time_format") or detect_time_format(
            columns[tcol]["dss_type"], columns[tcol].get("samples"))
        if tfmt:
            dataset_payload["time"] = {
                "column": tcol, "format": tfmt,
                "min": (columns[tcol].get("stats") or {}).get("min"),
                "max": (columns[tcol].get("stats") or {}).get("max"),
            }

    for name, fields in clean["columns"].items():
        col = columns[name]
        col.update(fields)
        col["llm_generated"] = True
        if col.get("role") == "free_text":
            col["groupable"] = False
    return True


# =============================================================================
# 5. MAIN (DSS recipe entry point)
# =============================================================================

def main():
    import pandas as pd
    from dataiku import recipe

    inputs = recipe.get_inputs_as_datasets()
    output = recipe.get_outputs_as_datasets()[0]
    source = inputs[0]
    overrides_ds = inputs[1] if len(inputs) > 1 else None

    dataset_name = source.short_name if hasattr(source, "short_name") else source.name
    logger.info("Profiling dataset %s", dataset_name)

    schema_columns = source.read_schema(raise_if_empty=True)
    schema_cols_raw = [{"name": c["name"] if isinstance(c, dict) else c.name,
                        "type": c.get("type") if isinstance(c, dict) else c.type}
                       for c in schema_columns]

    # infer_with_pandas=False preserves exact storage types but raises "Integer
    # column has NA values" when an int column contains NULLs (e.g. a resolution
    # duration that is empty for still-open tickets). Fall back to pandas inference
    # in that case (the NA-int column becomes float, which holds NaN). Role/type
    # classification reads the DSS schema separately (schema_cols_raw), so this only
    # affects stats / enums / samples and stays correct.
    try:
        df = source.get_dataframe(infer_with_pandas=False)
    except ValueError:
        df = source.get_dataframe(infer_with_pandas=True)
    if len(df) > MAX_ROWS_IN_MEMORY:
        df = df.head(MAX_ROWS_IN_MEMORY)
        logger.warning("Dataset truncated to %d rows for profiling", MAX_ROWS_IN_MEMORY)

    dataset_payload, columns = profile_dataframe(df, schema_cols_raw)
    dataset_payload["dataset_name"] = dataset_name

    # Reuse column descriptions already set in the DSS UI (free signal).
    for c in schema_columns:
        comment = (c.get("comment") if isinstance(c, dict) else getattr(c, "comment", None))
        name = c["name"] if isinstance(c, dict) else c.name
        if comment and name in columns and not columns[name]["description_en"]:
            columns[name]["description_en"] = str(comment)[:400]

    project = dataiku.api_client().get_default_project()
    run_enrichment(project, dataset_name, dataset_payload, columns)

    # Fallback metric when the LLM pass was skipped or failed: first measure, SUM.
    if not dataset_payload.get("metrics"):
        for name, c in columns.items():
            if c["role"] == "measure":
                metric_name = re.sub(r"[^a-z0-9_]", "_", name.lower())[:40] or "total"
                dataset_payload["metrics"] = [{
                    "name": metric_name, "agg": "SUM", "column": name,
                    "format": "number", "label_fr": "Total %s" % name,
                    "label_en": "Total %s" % name, "description": "",
                }]
                dataset_payload["default_metric"] = metric_name
                break

    # Human overrides always win (applied last).
    if overrides_ds is not None:
        try:
            try:
                ov_df = overrides_ds.get_dataframe(infer_with_pandas=False)
            except ValueError:
                ov_df = overrides_ds.get_dataframe(infer_with_pandas=True)
            rows = ov_df.to_dict("records")
            logger.info("Applied %d human overrides", apply_overrides(dataset_payload, columns, rows))
        except Exception:
            logger.exception("Overrides dataset unreadable - ignored")

    for c in columns.values():
        c.pop("_time_format", None)   # internal, never serialized

    out_rows = [{"key": "__dataset__",
                 "payload": json.dumps(dataset_payload, ensure_ascii=False, default=str)}]
    out_rows += [{"key": name, "payload": json.dumps(c, ensure_ascii=False, default=str)}
                 for name, c in columns.items()]
    output.write_with_schema(pd.DataFrame(out_rows, columns=["key", "payload"]))
    logger.info("Profile written: %d columns + 1 dataset row", len(columns))


if __name__ == "__main__":
    main()
