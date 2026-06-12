# =============================================================================
# OWIsMind — DATASET PROFILER (Dataiku Python recipe, design-time Flow)
# -----------------------------------------------------------------------------
# Turns ANY input dataset into a machine-readable "dataset profile": the
# knowledge artifact that makes the Dataset Expert code agent an expert of
# that dataset. Data never leaves DSS: only AGGREGATED metadata (schema,
# stats, low-cardinality enum values, a few samples) is sent to the LLM Mesh
# model (which is cleared for the data anyway), never the raw rows.
#
# Flow wiring:
#   INPUT  1 (required): the dataset to profile (e.g. DRIVE_Revenues)
#   INPUT  2 (optional): an EDITABLE dataset of human overrides — schema
#                        {key, field, value} (see OVERRIDES below)
#   OUTPUT 1 (required): the profile dataset — schema {key, payload}
#                        (e.g. DRIVE_Revenues_profile)
#
# Two passes:
#   PASS A (deterministic, zero LLM): schema, types, null rates, distinct
#          counts, verbatim enum values for low-cardinality columns, samples
#          for the rest, numeric/time stats, time-format detection.
#   PASS B (LLM via Mesh): business descriptions, column roles, synonyms,
#          suggested metrics, scenario/time column election, display pairs.
#          Output validated & degraded deterministically; everything the LLM
#          wrote is flagged "llm_generated": true so humans know to review.
#
# OVERRIDES (human-in-the-loop, survives re-runs):
#   Create an *editable* dataset with columns: key, field, value
#     key   = "__dataset__" or a column name
#     field = any profile field (description_fr, role, synonyms, metrics, ...)
#     value = the value; JSON is parsed when possible ("["a","b"]"), else the
#             raw string is used.
#   Overrides are applied AFTER the LLM pass and flagged "human_override".
#
# PROFILE CONTRACT (consumed by agents/dataset_expert_agent.py — FROZEN v1):
#   Output dataset rows: {key: str, payload: str(JSON)}
#   key "__dataset__" -> table-level payload:
#     {profile_version, dataset_name, generated_at, row_count,
#      description_en, description_fr, grain,
#      default_metric, metrics: [{name, agg, column, format,
#                                 label_fr, label_en, description}],
#      scenario: {column, values, default_values} | null,
#      time: {column, format, min, max} | null,
#      notes: [str]}
#   key "<column>" -> column payload:
#     {name, dss_type, role, description_en, description_fr, synonyms,
#      null_pct, distinct_count, is_enum, values: [{v, n}], samples,
#      stats, display_column, groupable, indexed, llm_generated,
#      human_override?}
#   time.format is one of: date | yyyy_mm_dd_str | yyyy_mm_str |
#                          yyyymm_int | year_int
# =============================================================================

import json
import logging
import re
import unicodedata
from datetime import datetime

import dataiku

logger = logging.getLogger("owismind.profiler")

# =============================================================================
# 1. CONFIGURATION (review before the first run)
# =============================================================================

# LLM Mesh id used for the semantic enrichment pass (PASS B). Use the
# STRONGEST model available — this runs once per dataset, the cost is
# amortized over every future question. Leave "" to SKIP the LLM pass
# (deterministic profile only; descriptions stay empty for human filling).
ENRICH_LLM_ID = "openai:LLM-7064-revforecast:vertex_ai/gemini-2.5-pro"

ENUM_MAX_VALUES = 50        # <= N distincts -> full verbatim value list kept
SAMPLES_N = 12              # sample values kept for non-enum columns
SAMPLE_VALUE_MAX_CHARS = 80
MAX_ROWS_IN_MEMORY = 2_000_000   # safety cap for get_dataframe()
FREE_TEXT_AVG_LEN = 120     # avg length above which a string col = free text
PROFILE_VERSION = 1

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
# 2. PURE HELPERS (unit-tested in dataiku-agents/tests/test_profiler.py)
# =============================================================================

def norm_value(value):
    """Accent-insensitive lowercase with collapsed whitespace (the same
    normalization the value-index recipe and the agent's resolver use)."""
    s = unicodedata.normalize("NFKD", str(value))
    s = s.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s.strip().lower())


def json_safe(value):
    """numpy / pandas scalars -> plain JSON-safe Python values."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    try:
        import math
        if isinstance(value, float) and not math.isfinite(value):
            return None
    except Exception:
        pass
    for caster in (int, float):
        try:
            if isinstance(value, caster):
                return value
        except Exception:
            pass
    try:
        import numpy as np
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            f = float(value)
            import math
            return f if math.isfinite(f) else None
        if isinstance(value, np.bool_):
            return bool(value)
    except Exception:
        pass
    return str(value)[:SAMPLE_VALUE_MAX_CHARS * 4]


def detect_time_format(dss_type, sample_values):
    """Best-effort time format detection from the DSS type + a few samples.
    Returns one of TIME_FORMATS or None. Pure & defensive."""
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


def _coerce_str_list(raw, cap=12, item_cap=60):
    out = []
    for item in (raw if isinstance(raw, list) else []):
        s = str(item).strip()
        if s and s.lower() not in [o.lower() for o in out]:
            out.append(s[:item_cap])
        if len(out) >= cap:
            break
    return out


def validate_enrichment(parsed, column_names):
    """Deterministic validation of the LLM enrichment output. Never raises.
    Unknown columns / roles / aggs degrade field by field. Returns
    {"dataset": {...}, "columns": {name: {...}}} with only valid content."""
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
        # metrics
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
                "format": fmt,
                "unit": unit or None,
                "label_fr": str(m.get("label_fr") or name)[:80],
                "label_en": str(m.get("label_en") or name)[:80],
                "description": str(m.get("description") or "")[:300],
            })
        if metrics:
            clean["metrics"] = metrics
            default = str(ds.get("default_metric") or "")
            clean["default_metric"] = (default if any(m["name"] == default for m in metrics)
                                       else metrics[0]["name"])
        # scenario column election
        scen = ds.get("scenario")
        if isinstance(scen, dict) and scen.get("column") in known:
            clean["scenario"] = {"column": scen["column"],
                                 "default_values": _coerce_str_list(scen.get("default_values"), cap=5)}
        # time column election
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
            role = payload.get("role")
            if role in KNOWN_ROLES:
                clean["role"] = role
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
    """Override 'value' cell -> JSON when parseable, else trimmed string."""
    s = str(raw if raw is not None else "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


def apply_overrides(dataset_payload, column_payloads, override_rows):
    """Apply human override rows {key, field, value} IN PLACE (after the LLM
    pass, so humans always win). Unknown keys/fields are ignored, never fatal."""
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


def default_role(dss_type, distinct_count, row_count, avg_len, time_format,
                 name):
    """Deterministic fallback role when the LLM pass is skipped or silent."""
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
# 3. PASS A — deterministic statistics (pandas; the recipe runs design-time)
# =============================================================================

def profile_dataframe(df, schema_columns):
    """-> (dataset_payload, {column_name: column_payload}). Deterministic."""
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

        # PHYSICAL date detection first: a real date/timestamp column must be
        # profiled as format "date" even when the DSS schema type or the
        # string samples say otherwise — the agent's SQL templates depend on
        # it (seen in DSS: a PostgreSQL `date` profiled as string broke
        # LEFT(col, 10); the agent is cast-safe now, but the profile should
        # still tell the truth).
        tfmt = None
        try:
            import pandas as _pd
            if _pd.api.types.is_datetime64_any_dtype(series):
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
            # Plausible-but-unnamed time column: keep as low-priority candidate.
            time_candidates.append((1, name, tfmt))
        elif tfmt:
            time_candidates.append((0, name, tfmt))

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

        # Time columns are never enums: listing 30 month values as "allowed
        # values" pollutes the UNDERSTAND prompt and the SQL card for nothing.
        if 0 < distinct <= ENUM_MAX_VALUES and not tfmt:
            payload["is_enum"] = True
            try:
                counts = non_null.value_counts()
                payload["values"] = [
                    {"v": str(json_safe(v))[:SAMPLE_VALUE_MAX_CHARS],
                     "n": int(n)}
                    for v, n in counts.items()][:ENUM_MAX_VALUES]
            except Exception:
                payload["values"] = []
        else:
            payload["samples"] = [str(s)[:SAMPLE_VALUE_MAX_CHARS]
                                  for s in sample_values[:SAMPLES_N]]

        payload["role"] = default_role(dss_type, distinct, row_count, avg_len,
                                       tfmt, name)
        if payload["role"] in ("free_text", "measure"):
            payload["groupable"] = False
        if tfmt:
            payload["_time_format"] = tfmt   # promoted below, then cleaned
        columns[name] = payload

    # Deterministic time election (LLM may override): named candidates first.
    if time_candidates:
        time_candidates.sort()
        _, tname, tfmt = time_candidates[0]
        dataset_payload["time"] = {
            "column": tname, "format": tfmt,
            "min": (columns[tname].get("stats") or {}).get("min"),
            "max": (columns[tname].get("stats") or {}).get("max"),
        }
    return dataset_payload, columns


# =============================================================================
# 4. PASS B — LLM enrichment (aggregated metadata only, never raw rows)
# =============================================================================

ENRICH_PROMPT = (
    "You are a senior data analyst documenting a dataset so an AI agent can "
    "answer business questions about it with SQL. You receive AGGREGATED "
    "metadata only (schema, stats, distinct values, samples). Return ONE JSON "
    "object — no markdown fences, no commentary — with this exact shape:\n"
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
            vals = ", ".join("%s(%s)" % (v["v"], v["n"]) for v in c["values"][:ENUM_MAX_VALUES])
            desc += " | ALL VALUES: " + vals
        elif c.get("samples"):
            desc += " | samples: " + ", ".join(c["samples"][:8])
        if c.get("stats"):
            desc += " | stats: " + json.dumps(c["stats"], ensure_ascii=False, default=str)
        lines.append(desc)
    return "\n".join(lines)


def run_enrichment(project, dataset_name, dataset_payload, columns):
    """Calls the Mesh model (2 attempts) and merges the validated output into
    the payloads. Failure is non-fatal: the deterministic profile survives."""
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
            resp = completion.execute()
            parsed = safe_json_parse(getattr(resp, "text", None))
            if parsed:
                break
        except Exception as e:
            logger.warning("Enrichment attempt %d failed: %s", attempt, e)
    if not parsed:
        logger.warning("LLM enrichment produced no usable JSON — profile stays deterministic")
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
        for field, value in fields.items():
            col[field] = value
        col["llm_generated"] = True
        if col.get("role") in ("free_text",):
            col["groupable"] = False
    return True


# =============================================================================
# 5. MAIN (DSS recipe entry point)
# =============================================================================

def main():
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

    df = source.get_dataframe(infer_with_pandas=False)
    if len(df) > MAX_ROWS_IN_MEMORY:
        df = df.head(MAX_ROWS_IN_MEMORY)
        logger.warning("Dataset truncated to %d rows for profiling", MAX_ROWS_IN_MEMORY)

    dataset_payload, columns = profile_dataframe(df, schema_cols_raw)
    dataset_payload["dataset_name"] = dataset_name

    # Pull column-level descriptions already set in the DSS UI (free signal).
    for c in schema_columns:
        comment = (c.get("comment") if isinstance(c, dict) else getattr(c, "comment", None))
        name = c["name"] if isinstance(c, dict) else c.name
        if comment and name in columns and not columns[name]["description_en"]:
            columns[name]["description_en"] = str(comment)[:400]

    project = dataiku.api_client().get_default_project()
    run_enrichment(project, dataset_name, dataset_payload, columns)

    # Default metric fallback when the LLM pass was skipped/failed: first
    # numeric measure column, SUM.
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

    # Human overrides ALWAYS win (applied last).
    if overrides_ds is not None:
        try:
            odf = overrides_ds.get_dataframe(infer_with_pandas=False)
            rows = odf.to_dict("records")
            n = apply_overrides(dataset_payload, columns, rows)
            logger.info("Applied %d human overrides", n)
        except Exception:
            logger.exception("Overrides dataset unreadable — ignored")

    # Cleanup internals + final rows.
    for c in columns.values():
        c.pop("_time_format", None)

    import pandas as pd
    out_rows = [{"key": "__dataset__",
                 "payload": json.dumps(dataset_payload, ensure_ascii=False, default=str)}]
    for name, c in columns.items():
        out_rows.append({"key": name,
                         "payload": json.dumps(c, ensure_ascii=False, default=str)})
    output.write_with_schema(pd.DataFrame(out_rows, columns=["key", "payload"]))
    logger.info("Profile written: %d columns + 1 dataset row", len(columns))


if __name__ == "__main__":
    main()
