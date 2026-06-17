# =============================================================================
# OWIsMind - VALUE INDEX BUILDER (Dataiku Python recipe, design-time Flow)
# -----------------------------------------------------------------------------
# Builds the "value index" of a dataset: every distinct value of every
# groundable text column, with a normalized form. The Dataset Expert agent
# queries this index at runtime (read-only SQL) to resolve the business terms
# users type ("algerie telecom", "halys", "ipl") into EXACT cell values and
# their column - text-to-SQL is case/accent-sensitive, grounding is what
# prevents silent empty results.
#
# Flow wiring:
#   INPUT  1 (required): the dataset to index (e.g. DRIVE_Revenues)
#   OUTPUT 1 (required): the index dataset (e.g. DRIVE_Revenues_value_index)
#                        *** create the output ON THE SQL CONNECTION of the
#                        source dataset *** so the agent can query it in SQL.
#
# Output schema (FROZEN v1, consumed by agents/dataset_expert_agent.py):
#   column_name  STRING   the source column this value belongs to
#   value        STRING   the EXACT cell value, verbatim
#   value_norm   STRING   normalized form (lowercase, accents stripped,
#                          whitespace collapsed) - match key
#   occurrences  BIGINT   row count of this value in the source dataset
#
# Re-run this recipe (scenario: weekly or after each source refresh) to keep
# the index fresh; the agent always queries live, no cache invalidation needed.
# =============================================================================

import logging
import re
import unicodedata

logger = logging.getLogger("owismind.value_index")

# =============================================================================
# CONFIGURATION
# =============================================================================

# Columns to force-include / exclude, by exact name. Empty = automatic
# selection: string columns that are not free text and not quasi-unique ids.
INCLUDE_COLUMNS = []
EXCLUDE_COLUMNS = []

MAX_VALUES_PER_COLUMN = 20000   # beyond -> the column is NOT indexed (too big
                                # to disambiguate meaningfully; users should
                                # filter on a coarser column)
MAX_VALUE_CHARS = 200           # longer values = free text, skipped
FREE_TEXT_AVG_LEN = 120         # avg length above which a column = free text
ID_UNIQUENESS_RATIO = 0.95      # distinct/rows above which a column = row id
MIN_OCCURRENCES = 1

_NUMERIC_DSS_TYPES = ("tinyint", "smallint", "int", "bigint", "float",
                      "double", "decimal")
_DATE_DSS_TYPES = ("date", "datetime")


# =============================================================================
# PURE HELPERS (unit-tested in dataiku-agents/tests/test_profiler.py)
# =============================================================================

def norm_value(value):
    """Same normalization as the profiler and the agent resolver (FROZEN)."""
    s = unicodedata.normalize("NFKD", str(value))
    s = s.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s.strip().lower())


def should_index_column(name, dss_type, distinct_count, row_count, avg_len):
    """Deterministic selection: index the columns a user could NAME a value
    of. Skips numbers, dates, free text and quasi-unique identifiers."""
    if name in INCLUDE_COLUMNS:
        return True
    if name in EXCLUDE_COLUMNS:
        return False
    if dss_type in _NUMERIC_DSS_TYPES or dss_type in _DATE_DSS_TYPES:
        return False
    if distinct_count == 0 or distinct_count > MAX_VALUES_PER_COLUMN:
        return False
    if avg_len and avg_len > FREE_TEXT_AVG_LEN:
        return False
    if row_count and distinct_count >= ID_UNIQUENESS_RATIO * row_count and row_count > 1000:
        # quasi-unique long-tail ids are still useful when users paste exact
        # ids - but only when short (carrier codes); skip long ones.
        if avg_len and avg_len > 24:
            return False
    return True


def build_index_rows(df, dss_types):
    """-> list of {column_name, value, value_norm, occurrences}. Pure given a
    pandas DataFrame and a {column: dss_type} map."""
    rows = []
    row_count = int(len(df))
    for col in df.columns:
        name = str(col)
        series = df[col].dropna()
        if not len(series):
            continue
        try:
            as_str = series.astype(str).str.strip()
            as_str = as_str[as_str != ""]
            avg_len = float(as_str.str.len().mean()) if len(as_str) else 0.0
            distinct = int(as_str.nunique())
        except Exception:
            continue
        if not should_index_column(name, dss_types.get(name, "string"),
                                   distinct, row_count, avg_len):
            logger.info("Skipping column %s (type=%s distinct=%s avg_len=%.0f)",
                        name, dss_types.get(name), distinct, avg_len)
            continue
        counts = as_str.value_counts()
        kept = 0
        for value, n in counts.items():
            if int(n) < MIN_OCCURRENCES or len(value) > MAX_VALUE_CHARS:
                continue
            rows.append({"column_name": name, "value": value,
                         "value_norm": norm_value(value),
                         "occurrences": int(n)})
            kept += 1
            if kept >= MAX_VALUES_PER_COLUMN:
                break
        logger.info("Indexed column %s: %d values", name, kept)
    return rows


# =============================================================================
# MAIN (DSS recipe entry point)
# =============================================================================

def main():
    from dataiku import recipe

    source = recipe.get_inputs_as_datasets()[0]
    output = recipe.get_outputs_as_datasets()[0]

    schema = source.read_schema(raise_if_empty=True)
    dss_types = {}
    for c in schema:
        name = c["name"] if isinstance(c, dict) else c.name
        dss_types[name] = str((c.get("type") if isinstance(c, dict)
                               else getattr(c, "type", None)) or "string")

    df = source.get_dataframe(infer_with_pandas=False)
    rows = build_index_rows(df, dss_types)

    import pandas as pd
    out = pd.DataFrame(rows, columns=["column_name", "value", "value_norm",
                                      "occurrences"])
    output.write_with_schema(out)
    logger.info("Value index written: %d rows over %d columns",
                len(out), out["column_name"].nunique() if len(out) else 0)


if __name__ == "__main__":
    main()
