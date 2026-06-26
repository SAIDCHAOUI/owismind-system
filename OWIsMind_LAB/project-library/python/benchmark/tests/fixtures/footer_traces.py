"""Synthetic footer-trace and event fixtures shaped like the real DSS footer.

We cannot run DSS here, so these dicts/lists imitate the structure the LLM Mesh
footer trace exposes (verified against the webapp footer walk in
agents/streaming.py and evidence/capture.py): semantic-model-query tool spans
nested under ``outputs`` (with ``sql`` / ``success`` / ``row_count`` and a rows
key), ``usageMetadata`` dicts nested anywhere, and ARTIFACT lifecycle events.

The real key for result rows is instance-dependent (the webapp probes several:
rows / records / data / ...). We exercise two of those shapes here:
  - SQL item 1: list-of-lists rows under "rows" with an explicit "columns" list;
  - SQL item 2: list-of-dicts rows under "records" (columns derived from keys).

A `BIG_RESULT_TRACE` exceeds MAX_RESULT_ROWS / MAX_RESULT_COLS to prove the caps.
"""


def make_sql_span(name, sql, success, row_count, outputs_extra=None):
    """Build one tool span dict the footer walk will recognise (or not, by name)."""
    outputs = {"sql": sql, "success": success, "row_count": row_count}
    if outputs_extra:
        outputs.update(outputs_extra)
    return {
        "type": "tool_call",
        "name": name,
        "outputs": outputs,
    }


# A realistic footer trace: nested spans, two semantic-model-query outputs with
# captured rows (two different row shapes), some usageMetadata dicts, and one
# non-SQL tool span that must be ignored by the SQL walk.
TWO_SQL_TRACE = {
    "trace": None,  # placeholder, set below to the nested run trace
}

_RUN_TRACE = {
    "rootSpan": {
        "name": "OWIsMind_orchestrator",
        "usageMetadata": {
            "promptTokens": 1200,
            "completionTokens": 300,
            "totalTokens": 1500,
            "estimatedCost": 0.012,
        },
        "children": [
            {
                "name": "ask_revenue_expert",
                "usageMetadata": {
                    "promptTokens": 800,
                    "completionTokens": 150,
                    "totalTokens": 950,
                    "estimatedCost": 0.009,
                },
                "children": [
                    # SQL item 1: list-of-lists rows + explicit columns.
                    make_sql_span(
                        "semantic-model-query",
                        "SELECT account_name, SUM(amount_eur) AS revenue "
                        "FROM DRIVE_Revenues GROUP BY account_name ORDER BY 2 DESC",
                        True,
                        2,
                        outputs_extra={
                            "columns": ["account_name", "revenue"],
                            "rows": [
                                ["Maroc Telecom", 1234567.89],
                                ["Airbus", 987654.0],
                            ],
                        },
                    ),
                    # A non-SQL tool span that the SQL walk must skip.
                    {
                        "type": "tool_call",
                        "name": "attribute_lookup",
                        "outputs": {"found_in": "account_name", "value": "Airbus"},
                    },
                    # SQL item 2: list-of-dicts rows under "records".
                    make_sql_span(
                        "semantic-model-query",
                        "SELECT phase, SUM(amount_eur) AS total "
                        "FROM DRIVE_Revenues GROUP BY phase",
                        True,
                        3,
                        outputs_extra={
                            "records": [
                                {"phase": "ACTUALS", "total": 5000000},
                                {"phase": "BUDGET", "total": 4500000},
                                {"phase": "FORECAST", "total": 4800000},
                            ],
                        },
                    ),
                ],
            }
        ],
    }
}
TWO_SQL_TRACE["trace"] = _RUN_TRACE


# The footer trace as the webapp sees it post-walk: extract_* take the inner trace
# (the value under footer_data["trace"]). For the benchmark, callers pass that same
# inner trace. Expose it directly for the tests.
TWO_SQL_INNER_TRACE = _RUN_TRACE


# A trace with NO semantic-model-query span (only usage): SQL extraction must be [].
NO_SQL_TRACE = {
    "rootSpan": {
        "name": "OWIsMind_orchestrator",
        "usageMetadata": {
            "promptTokens": 100,
            "completionTokens": 50,
            "totalTokens": 150,
            "estimatedCost": 0.001,
        },
        "children": [
            {
                "type": "tool_call",
                "name": "attribute_lookup",
                "outputs": {"found_in": "account_name", "value": "Airbus"},
            }
        ],
    }
}


# A SQL span whose result blows past the row/col caps (proves MAX_RESULT_*).
_BIG_COLUMNS = ["c{0}".format(i) for i in range(60)]          # > MAX_RESULT_COLS(50)
_BIG_ROWS = [[j for j in range(60)] for _ in range(250)]       # > MAX_RESULT_ROWS(200)
BIG_RESULT_TRACE = {
    "rootSpan": {
        "name": "OWIsMind_orchestrator",
        "children": [
            make_sql_span(
                "semantic-model-query",
                "SELECT * FROM DRIVE_Revenues",
                True,
                250,
                outputs_extra={"columns": _BIG_COLUMNS, "rows": _BIG_ROWS},
            )
        ],
    }
}


# Normalized stream events (as a benchmark runner would accumulate them): one
# normalized artifact event and one raw ARTIFACT lifecycle event with eventData.
ARTIFACT_EVENTS = [
    {"type": "answer_delta", "text": "Here is the breakdown."},
    {
        "type": "artifact",
        "kind": "chart",
        "title": "Revenue by account",
        "chart": {"type": "bar", "x": "account_name", "y": ["revenue"]},
        "kpi": None,
    },
    {
        "eventKind": "ARTIFACT",
        "eventData": {
            "kind": "kpi",
            "title": "Total revenue",
            "kpi": {"label": "Total", "value": "2 222 221.89 EUR"},
        },
    },
]


# A standalone usageMetadata example (multiple dicts to prove summation).
MULTI_USAGE_TRACE = {
    "a": {"usageMetadata": {"promptTokens": 10, "completionTokens": 5,
                            "totalTokens": 15, "estimatedCost": 0.001}},
    "b": [
        {"usageMetadata": {"promptTokens": 20, "completionTokens": 7,
                           "totalTokens": 27, "estimatedCost": 0.002}},
        {"nested": {"usageMetadata": {"promptTokens": 3, "completionTokens": 1,
                                      "totalTokens": 4, "estimatedCost": 0.0005}}},
    ],
}
