"""Build a Chart.js-ready payload from a captured SQL result + a chart spec.

The orchestrator only chooses HOW to plot (chart type + which columns are x / y);
this module turns the already-captured result table into a clean, bullet-proof
`{labels, datasets}` payload the frontend hands straight to Chart.js. Doing the
shaping HERE (server-side Python) is the whole point of "the agent only says x/y":
column resolution, number parsing, sorting/capping and pie percentages happen on
trusted code, so a mistyped column or a non-numeric cell degrades to an honest
empty state instead of a broken chart.

Pure + defensive: stdlib only, never raises. Returns ``{"ok": False, "reason": …}``
whenever it cannot build a meaningful chart (no data, unknown column, no numeric
series), so the UI can show an honest empty state.
"""

import math
import re

# Bounds (instance safety + readable charts): a chart with thousands of points
# is neither useful nor cheap to ship; cap and flag truncation.
MAX_POINTS = 200          # categories / x values plotted (line, bar)
MAX_SLICES = 12           # pie slices before the rest is grouped as "Other"
_LABEL_MAX_CHARS = 80
CHART_TYPES = ("line", "bar", "pie")

_LEADING_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _to_number(value):
    """Best-effort numeric coercion. Numbers pass through; formatted strings
    ('1 234,5', '12.5%', '1,234.56', '€ 90') are parsed; anything else -> None.

    Result cells are usually raw numbers already (the display formatting is done
    elsewhere), so the string path is a safety net, not the common case."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    s = str(value).strip()
    if not s:
        return None
    # Strip spaces (incl. NBSP / narrow NBSP), percent and common currency marks.
    s = (s.replace(" ", "").replace(" ", "").replace(" ", "")
         .replace("%", "").replace("€", "").replace("$", "").replace("£", ""))
    # Reconcile decimal comma vs thousands separators: the RIGHT-MOST of , / . is
    # the decimal separator; the other is a thousands group.
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        f = float(s)
        return f if math.isfinite(f) else None
    except ValueError:
        m = _LEADING_NUM_RE.match(s)
        if m:
            try:
                f = float(m.group(0))
                return f if math.isfinite(f) else None
            except ValueError:
                return None
        return None


def _label(value):
    if value is None:
        return ""
    return str(value)[:_LABEL_MAX_CHARS]


def _resolve(columns, name):
    """Case-insensitive column-name -> index, or None."""
    if not name:
        return None
    target = str(name).strip().lower()
    for i, c in enumerate(columns):
        if str(c).strip().lower() == target:
            return i
    return None


def build_chart_payload(result, chart_spec):
    """Return a Chart.js payload for one chart artifact, or an honest empty shape.

    ``result`` is the /evidence/meta result block ({captured, columns, rows, ...}).
    ``chart_spec`` is the artifact's ``chart`` dict ({type, x, y[]}). Output:
      {"ok": True, "labels": [...], "datasets": [{"label","data"}], "truncated": bool}
    or {"ok": False, "reason": "no_data" | "bad_spec" | "x_not_found" |
        "y_not_found" | "no_numeric"}.
    """
    if not isinstance(result, dict) or not result.get("captured"):
        return {"ok": False, "reason": "no_data"}
    columns = result.get("columns") or []
    rows = result.get("rows") or []
    if not columns or not rows:
        return {"ok": False, "reason": "no_data"}

    spec = chart_spec or {}
    ctype = spec.get("type")
    if ctype not in CHART_TYPES:
        return {"ok": False, "reason": "bad_spec"}
    x = spec.get("x")
    y = spec.get("y")
    if isinstance(y, str):
        y = [y]
    if not x or not isinstance(y, list) or not y:
        return {"ok": False, "reason": "bad_spec"}

    xi = _resolve(columns, x)
    if xi is None:
        return {"ok": False, "reason": "x_not_found"}
    y_cols = [(str(c), _resolve(columns, c)) for c in y]
    y_cols = [(name, i) for name, i in y_cols if i is not None]
    if not y_cols:
        return {"ok": False, "reason": "y_not_found"}

    capped = rows[:MAX_POINTS]
    truncated = bool(result.get("truncated")) or len(rows) > MAX_POINTS

    if ctype == "pie":
        # One slice per row, using the FIRST resolved y column; only positive,
        # numeric values are meaningful for a share chart.
        name, yi = y_cols[0]
        pairs = []
        for r in capped:
            v = _to_number(r[yi]) if yi < len(r) else None
            if v is not None and v > 0:
                pairs.append((_label(r[xi]) if xi < len(r) else "", v))
        if not pairs:
            return {"ok": False, "reason": "no_numeric"}
        # Keep the largest MAX_SLICES; fold the tail into a single "Other" slice.
        pairs.sort(key=lambda p: p[1], reverse=True)
        if len(pairs) > MAX_SLICES:
            head = pairs[:MAX_SLICES - 1]
            other = sum(v for _, v in pairs[MAX_SLICES - 1:])
            head.append(("Other", other))
            pairs = head
            truncated = True
        return {"ok": True, "label": name,
                "labels": [lab for lab, _ in pairs],
                "datasets": [{"label": name, "data": [v for _, v in pairs]}],
                "truncated": truncated}

    # line / bar: one dataset per y column; None keeps a gap (line) / empty bar.
    labels = [_label(r[xi]) if xi < len(r) else "" for r in capped]
    datasets, any_numeric = [], False
    for name, yi in y_cols:
        series = []
        for r in capped:
            v = _to_number(r[yi]) if yi < len(r) else None
            if v is not None:
                any_numeric = True
            series.append(v)
        datasets.append({"label": name, "data": series})
    if not any_numeric:
        return {"ok": False, "reason": "no_numeric"}
    return {"ok": True, "labels": labels, "datasets": datasets,
            "truncated": truncated}


def build_kpi_payload(result, kpi_spec):
    """Return a KPI card payload from the captured result + a kpi spec, or an
    honest empty shape. The agent only names the value column (and optional delta
    columns); the figures are read from the FIRST result row by trusted code.

    Output: {"ok": True, "label", "value"[, "delta", "delta_pct"]} or
    {"ok": False, "reason": "no_data" | "bad_spec" | "value_not_found" |
        "no_numeric"}.
    """
    if not isinstance(result, dict) or not result.get("captured"):
        return {"ok": False, "reason": "no_data"}
    columns = result.get("columns") or []
    rows = result.get("rows") or []
    if not columns or not rows:
        return {"ok": False, "reason": "no_data"}
    spec = kpi_spec or {}
    value_col = spec.get("value")
    if not value_col:
        return {"ok": False, "reason": "bad_spec"}
    vi = _resolve(columns, value_col)
    if vi is None:
        return {"ok": False, "reason": "value_not_found"}
    row0 = rows[0]
    value = _to_number(row0[vi]) if vi < len(row0) else None
    if value is None:
        return {"ok": False, "reason": "no_numeric"}
    out = {"ok": True, "label": _label(spec.get("label") or value_col),
           "value": value}
    for key in ("delta", "delta_pct"):
        col = spec.get(key)
        if not col:
            continue
        ci = _resolve(columns, col)
        if ci is not None and ci < len(row0):
            num = _to_number(row0[ci])
            if num is not None:
                out[key] = num
    return out
