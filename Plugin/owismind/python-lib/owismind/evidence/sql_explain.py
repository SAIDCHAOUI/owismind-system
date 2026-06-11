"""Pure SQL explainer for the Evidence Studio trust layer (NO dataiku import).

Turns ONE agent-generated SELECT into a structured, business-renderable
explanation plus deterministic completeness flags. The single consumer is
``evidence.service.safe_explain`` -> ``normalize_explain``, whose defensive
defaults mean a missing/partial key can only ever UNDER-claim (honesty rules,
frozen contract docs/superpowers/specs/2026-06-10-evidence-trust-layer-design.md §2).

    explain_select(sql) -> {
        "ok": bool,              # False only when the text is not ONE analysable SELECT
        "reason": str | None,    # stable code when ok is False
        "steps": [{"kind", "params"}],   # ordered, <= MAX_STEPS, frozen kind enum
        "where_complete": bool,  # every WHERE conjunct on the main chain decomposed
        "dropped_where": [str],  # verbatim displays of NON-decomposed conjuncts
        "group_keys": [str],     # GROUP BY keys with IDENTITY lineage to the source
        "single_source": bool,   # exactly ONE real-table occurrence on the chain
        "select_understood": bool,  # no opaque SELECT item anywhere on the chain
        "has_set_op": bool, "has_recursive_cte": bool,
        "calc_resolved": bool,   # group/order/having resolved + CTE DAG complete
    }

NEVER RAISES (the whole body is exception-guarded). Anything not positively
understood degrades a flag or yields an ``opaque`` step — never a guess: a wrong
explanation would be a false proof, an under-claimed one is merely less helpful.

Reuses sql_parse's tokenizer/predicate bricks; sql_parse itself is NOT modified
(its contract is locked by the existing test suite). Comments are masked to
spaces first (length-preserving, offsets intact) so commented SQL still explains
— re-executable fragments elsewhere keep rejecting comments (validate_fragment).
"""

import re

from owismind.evidence.sql_parse import (
    MAX_SQL_CHARS,
    _match_paren,
    _read_ident,
    _read_table_ref,
    _split_conjuncts,
    _try_simple,
    parse_select,
    tokenize,
    validate_fragment,
)

# Display/output bounds (mirrored by service.py at the trust boundary).
MAX_STEPS = 15
MAX_PARAM_CHARS = 80
MAX_OPAQUE_CHARS = 120
# Lineage walk bound: CTE chains deeper than this stop resolving (under-claim).
_MAX_LINEAGE_DEPTH = 10
# Derived-subquery analysis bound (FROM (SELECT ...) nesting).
_MAX_DERIVED_DEPTH = 5

_AGG_FUNCS = ("SUM", "COUNT", "AVG", "MIN", "MAX")
_RANK_FUNCS = ("ROW_NUMBER", "RANK", "DENSE_RANK", "NTILE")
_SHIFT_FUNCS = ("LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE")
_JOIN_TYPE_WORDS = ("LEFT", "RIGHT", "FULL", "INNER", "CROSS", "NATURAL", "OUTER")
_SET_OPS = ("UNION", "EXCEPT", "INTERSECT")
# Words that end the FROM item list / start a new clause at scope top level.
_CLAUSE_STARTERS = ("WHERE", "GROUP", "HAVING", "ORDER", "LIMIT", "OFFSET",
                    "FETCH", "WINDOW", "FOR")
# Functions that are transparent for business classification: ROUND(x, 2) means x.
_UNWRAP_FUNCS = ("ROUND", "CAST", "COALESCE", "ABS", "TRUNC", "CEIL", "FLOOR")

_AGG_STEP_KIND = {"SUM": "agg_sum", "AVG": "agg_avg", "MIN": "agg_min", "MAX": "agg_max"}
_FILTER_STEP_KIND = {
    "=": "filter_eq", "!=": "filter_neq", ">": "filter_gt", ">=": "filter_gte",
    "<": "filter_lt", "<=": "filter_lte", "IN": "filter_in", "NOT IN": "filter_notin",
    "BETWEEN": "filter_between", "IS NULL": "filter_null",
    "IS NOT NULL": "filter_notnull", "LIKE": "filter_like", "ILIKE": "filter_like",
}

_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def _mask_comments(sql):
    """Replace -- and /* */ comments with spaces, LENGTH-PRESERVING.

    Token offsets computed on the masked text therefore map 1:1 onto the
    original, so verbatim display slices stay exact. An unterminated block
    comment is left as-is (the tokenizer will then fail -> honest degrade).
    """
    def _blank(m):
        return " " * (m.end() - m.start())
    return _BLOCK_COMMENT_RE.sub(_blank, _LINE_COMMENT_RE.sub(_blank, sql))


def _defaults():
    """The honest all-False shape every failure path returns (under-claims only)."""
    return {
        "ok": False, "reason": None, "steps": [],
        "where_complete": False, "dropped_where": [], "group_keys": [],
        "single_source": False, "select_understood": False,
        "has_set_op": False, "has_recursive_cte": False, "calc_resolved": False,
    }


def _failed(reason):
    out = _defaults()
    out["reason"] = reason
    return out


def _is_word(tok, word):
    return tok.kind == "word" and tok.text.upper() == word


def _display(text, tokens, a, b, cap=MAX_PARAM_CHARS):
    """Verbatim slice of the (masked) text covering tokens [a, b), bounded."""
    if a >= b or a >= len(tokens):
        return ""
    out = text[tokens[a].start: tokens[b - 1].end].strip()
    out = " ".join(out.split())  # collapse comment-mask runs of spaces
    return out[:cap]


def _split_top_commas(tokens, lo, hi):
    """Split tokens[lo:hi) on top-level commas -> list of (a, b) spans."""
    spans, depth, start = [], 0, lo
    for i in range(lo, hi):
        t = tokens[i]
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
        elif t.text == "," and depth == 0:
            spans.append((start, i))
            start = i + 1
    if start < hi:
        spans.append((start, hi))
    return [s for s in spans if s[0] < s[1]]


def _ident_chain(tokens, a, b):
    """``(last_component, True)`` when tokens[a:b) is one dotted ident chain."""
    j = a
    name, j = _read_ident(tokens, j)
    if name is None:
        return None, False
    while j < b and tokens[j].text == ".":
        nxt, j = _read_ident(tokens, j + 1)
        if nxt is None:
            return None, False
        name = nxt
    return (name, True) if j == b else (None, False)


def _parse_with_clause(tokens):
    """Parse a leading ``WITH [RECURSIVE] name AS (body), ...`` prefix.

    Returns ``(ctes, main_lo, recursive)`` where ctes = [{name, lo, hi}] (body
    token spans) and main_lo is the index of the main SELECT. Returns
    ``(None, 0, False)`` when the statement does not start with WITH, and
    ``(None, -1, rec)`` when the WITH prefix is malformed (caller degrades).
    """
    if not tokens or not _is_word(tokens[0], "WITH"):
        return None, 0, False
    i, recursive = 1, False
    if i < len(tokens) and _is_word(tokens[i], "RECURSIVE"):
        recursive, i = True, i + 1
    ctes = []
    while True:
        name, i = _read_ident(tokens, i)
        if name is None:
            return None, -1, recursive
        # Optional explicit column list: name (col, ...) AS — skipped verbatim.
        if i < len(tokens) and tokens[i].text == "(" and not _is_word(tokens[i], "AS"):
            close = _match_paren(tokens, i, len(tokens))
            if close is None:
                return None, -1, recursive
            i = close + 1
        if i >= len(tokens) or not _is_word(tokens[i], "AS"):
            return None, -1, recursive
        i += 1
        # Optional [NOT] MATERIALIZED hint.
        if i < len(tokens) and _is_word(tokens[i], "NOT"):
            i += 1
        if i < len(tokens) and _is_word(tokens[i], "MATERIALIZED"):
            i += 1
        if i >= len(tokens) or tokens[i].text != "(":
            return None, -1, recursive
        close = _match_paren(tokens, i, len(tokens))
        if close is None:
            return None, -1, recursive
        ctes.append({"name": name, "lo": i + 1, "hi": close})
        i = close + 1
        if i < len(tokens) and tokens[i].text == ",":
            i += 1
            continue
        break
    return ctes, i, recursive


# ---------------------------------------------------------------------------
# Scope scanner — one SELECT body -> clause spans + table refs (linear, paren-
# skipping; sub-groups are opaque except derived FROM subqueries, recorded for
# chain analysis). Independent of sql_parse._scan_scopes (which it does not
# modify) but follows the same depth/keyword discipline.
# ---------------------------------------------------------------------------

def _scan_scope(tokens, lo, hi):
    """Scan ONE SELECT body span -> clause/ref descriptor dict, or None.

    The scan STOPS at the first top-level set-operation keyword (first arm
    only, same rule as sql_parse) and records how many arms followed.
    """
    if lo >= hi or not _is_word(tokens[lo], "SELECT"):
        return None
    scope = {
        "lo": lo, "hi": hi,
        "distinct": False, "select_span": None, "refs": [], "derived": [],
        "where_span": None, "group_span": None, "having_span": None,
        "order_span": None, "limit": None, "set_arms": 0, "saw_join": False,
    }
    i = lo + 1
    if i < hi and _is_word(tokens[i], "DISTINCT"):
        scope["distinct"] = True
        i += 1
        # DISTINCT ON (cols): the ON-group is part of the distinct, skip it.
        if i < hi and _is_word(tokens[i], "ON") and i + 1 < hi and tokens[i + 1].text == "(":
            close = _match_paren(tokens, i + 1, hi)
            if close is None:
                return None
            i = close + 1
    # --- locate top-level clause boundaries -------------------------------
    marks = []  # (index, WORD) for top-level clause keywords
    depth = 0
    j = i
    cut = hi
    while j < hi:
        t = tokens[j]
        if t.text == "(":
            close = _match_paren(tokens, j, hi)
            if close is None:
                return None
            j = close + 1
            continue
        if t.kind == "word":
            u = t.text.upper()
            if u in _SET_OPS:
                # First-arm analysis; count the remaining arms at this level.
                cut = j
                arms = 1
                k, d2 = j + 1, 0
                while k < hi:
                    tk = tokens[k]
                    if tk.text == "(":
                        d2 += 1
                    elif tk.text == ")":
                        d2 -= 1
                    elif d2 == 0 and tk.kind == "word" and tk.text.upper() in _SET_OPS:
                        arms += 1
                    k += 1
                scope["set_arms"] = arms
                break
            if u in ("FROM", "WHERE", "GROUP", "HAVING", "ORDER", "LIMIT",
                     "OFFSET", "FETCH", "WINDOW", "FOR"):
                # The FROM of `IS [NOT] DISTINCT FROM` is not a clause start.
                if u == "FROM" and j > lo and _is_word(tokens[j - 1], "DISTINCT") and not scope["distinct"]:
                    j += 1
                    continue
                marks.append((j, u))
        j += 1
    bounds = [m[0] for m in marks] + [cut]
    scope["select_span"] = (i, bounds[0] if bounds else cut)

    def _clause_span(word, skip):
        for idx, (pos, w) in enumerate(marks):
            if w == word:
                end = marks[idx + 1][0] if idx + 1 < len(marks) else cut
                return (pos + skip, end)
        return None

    from_span = _clause_span("FROM", 1)
    scope["where_span"] = _clause_span("WHERE", 1)
    scope["group_span"] = _clause_span("GROUP", 2)   # GROUP BY
    scope["having_span"] = _clause_span("HAVING", 1)
    scope["order_span"] = _clause_span("ORDER", 2)   # ORDER BY
    limit_span = _clause_span("LIMIT", 1)
    if limit_span and limit_span[0] < limit_span[1]:
        t = tokens[limit_span[0]]
        if t.kind == "number" and "." not in t.text:
            scope["limit"] = int(t.text)
    # --- FROM item list: table refs, join types, derived subqueries --------
    if from_span:
        a, b = from_span
        j = a
        pending_join = None  # join-type words collected before the next ref
        while j < b:
            t = tokens[j]
            if t.text == "(":
                close = _match_paren(tokens, j, b)
                if close is None:
                    return None
                if j + 1 < close and _is_word(tokens[j + 1], "SELECT"):
                    scope["derived"].append((j + 1, close))
                    # Optional [AS] alias after the derived table — skipped.
                    j = close + 1
                    if j < b and _is_word(tokens[j], "AS"):
                        j += 1
                    if j < b and tokens[j].kind in ("word", "qident") and \
                            tokens[j].text.upper() not in _CLAUSE_STARTERS + ("ON", "USING", "JOIN") + _JOIN_TYPE_WORDS + _SET_OPS:
                        j += 1
                else:
                    j = close + 1
                continue
            if t.kind == "word":
                u = t.text.upper()
                if u in _JOIN_TYPE_WORDS:
                    pending_join = u if pending_join is None else pending_join
                    j += 1
                    continue
                if u == "JOIN":
                    scope["saw_join"] = True
                    ref, j2 = _read_table_ref(tokens, j + 1, b)
                    if ref is not None:
                        ref["join_type"] = pending_join or "INNER"
                        scope["refs"].append(ref)
                        pending_join = None
                        j = j2
                        continue
                    pending_join = None
                    j += 1
                    continue
                if u in ("ON", "USING"):
                    # Join condition: skip to the next JOIN/clause boundary.
                    j += 1
                    continue
            if t.text == ",":
                scope["saw_join"] = True  # comma join
                ref, j2 = _read_table_ref(tokens, j + 1, b)
                if ref is not None:
                    ref["join_type"] = "INNER"
                    scope["refs"].append(ref)
                    j = j2
                    continue
                j += 1
                continue
            if not scope["refs"] and t.kind in ("word", "qident"):
                ref, j2 = _read_table_ref(tokens, j, b)
                if ref is not None:
                    ref["join_type"] = None  # the FROM anchor, not a join
                    scope["refs"].append(ref)
                    j = j2
                    continue
            j += 1
    return scope


# ---------------------------------------------------------------------------
# SELECT-item classification (business kinds, verbatim displays, NEVER raises:
# anything unrecognised is {"kind": "opaque"}).
# ---------------------------------------------------------------------------

def _strip_cast(tokens, a, b):
    """Drop a trailing top-level ``:: type`` cast from an expression span."""
    j, depth = a, 0
    while j < b - 1:
        if tokens[j].text == "(":
            depth += 1
        elif tokens[j].text == ")":
            depth -= 1
        elif depth == 0 and tokens[j].text == ":" and tokens[j + 1].text == ":":
            return a, j
        j += 1
    return a, b


def _top_level_op(tokens, a, b, ops):
    """Index of the LAST top-level occurrence of one of ``ops`` in [a, b)."""
    depth, found = 0, None
    for j in range(a, b):
        t = tokens[j]
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
        elif depth == 0 and t.kind == "punct" and t.text in ops:
            found = j
    return found


def _classify_expr(text, tokens, a, b, depth=0):
    """Classify one expression span -> a business kind dict. Never raises."""
    a, b = _strip_cast(tokens, a, b)
    if a >= b or depth > 8:
        return {"kind": "opaque"}
    # Whole-expression parens unwrap.
    while tokens[a].text == "(" and _match_paren(tokens, a, b) == b - 1 and b - a > 2:
        a, b = a + 1, b - 1
    # Plain column (dotted chain).
    name, ok = _ident_chain(tokens, a, b)
    if ok and tokens[a].kind in ("word", "qident"):
        upper = tokens[a].text.upper()
        if b - a == 1 and upper in ("TRUE", "FALSE", "NULL"):
            return {"kind": "literal"}
        return {"kind": "column", "name": name}
    if b - a == 1 and tokens[a].kind in ("number", "string"):
        return {"kind": "literal"}
    if b - a == 1 and tokens[a].text == "*":
        return {"kind": "star"}
    # CASE ... END — only meaningful inside an aggregate (agg_filtered).
    if _is_word(tokens[a], "CASE"):
        return {"kind": "case", "span": (a, b)}
    # function-call shaped: WORD ( ... ) [OVER ( ... )] — only when the call
    # covers the WHOLE expression; otherwise fall through to arithmetic below
    # (SUM(a) / NULLIF(SUM(b), 0) must classify as a ratio, not opaque).
    if tokens[a].kind == "word" and a + 1 < b and tokens[a + 1].text == "(":
        close = _match_paren(tokens, a + 1, b)
        if close is not None:
            fname = tokens[a].text.upper()
            over = None
            rest = close + 1
            if rest < b and _is_word(tokens[rest], "OVER") and rest + 1 < b and tokens[rest + 1].text == "(":
                over_close = _match_paren(tokens, rest + 1, b)
                if over_close == b - 1:
                    over = (rest + 2, over_close)
            inside = (a + 2, close)
            if over is not None and fname in _AGG_FUNCS + _RANK_FUNCS + _SHIFT_FUNCS:
                return _classify_window(text, tokens, fname, inside, over)
            if over is None and close + 1 == b:
                if fname in _AGG_FUNCS:
                    return _classify_agg(text, tokens, fname, inside)
                if fname in _UNWRAP_FUNCS:
                    args = _split_top_commas(tokens, a + 2, close)
                    if args:
                        return _classify_expr(text, tokens, args[0][0], args[0][1], depth + 1)
                if a + 2 < close and _is_word(tokens[a + 2], "SELECT"):
                    return {"kind": "subquery"}
                return {"kind": "opaque"}
    # Subquery expression: ( SELECT ... )
    if tokens[a].text == "(" and a + 1 < b and _is_word(tokens[a + 1], "SELECT"):
        return {"kind": "subquery"}
    # Arithmetic: ratio / percent / difference (lowest-precedence split).
    slash = _top_level_op(tokens, a, b, ("/",))
    if slash is not None and a < slash < b - 1:
        left = _classify_expr(text, tokens, a, slash, depth + 1)
        right = _classify_expr(text, tokens, slash + 1, b, depth + 1)
        return {"kind": "ratio", "left": left, "right": right,
                "left_span": (a, slash), "right_span": (slash + 1, b)}
    star = _top_level_op(tokens, a, b, ("*",))
    if star is not None and a < star < b - 1:
        sides = ((a, star), (star + 1, b))
        for sa, sb in sides:
            if sb - sa == 1 and tokens[sa].kind == "number" and float(tokens[sa].text) == 100.0:
                other = sides[1] if (sa, sb) == sides[0] else sides[0]
                return {"kind": "percent", "span": other}
        return {"kind": "opaque"}
    minus = _top_level_op(tokens, a, b, ("-",))
    if minus is not None and a < minus < b - 1:
        return {"kind": "diff", "left_span": (a, minus), "right_span": (minus + 1, b)}
    return {"kind": "opaque"}


def _classify_agg(text, tokens, fname, inside):
    """SUM/COUNT/AVG/MIN/MAX( [DISTINCT] arg ) -> agg kind dict."""
    a, b = inside
    distinct = False
    if a < b and _is_word(tokens[a], "DISTINCT"):
        distinct, a = True, a + 1
    if a >= b:
        return {"kind": "opaque"}
    if b - a == 1 and tokens[a].text == "*":
        return {"kind": "agg", "func": fname, "arg": {"kind": "star"}, "distinct": distinct}
    arg = _classify_expr(text, tokens, a, b, 1)
    return {"kind": "agg", "func": fname, "arg": arg, "distinct": distinct,
            "arg_span": (a, b)}


def _classify_window(text, tokens, fname, inside, over):
    """fn(args) OVER (partition/order) -> window kind dict."""
    oa, ob = over
    order_pos = None
    depth = 0
    for j in range(oa, ob):
        t = tokens[j]
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
        elif depth == 0 and _is_word(t, "ORDER"):
            order_pos = j
            break
    order_span = (order_pos + 2, ob) if order_pos is not None else None
    return {"kind": "window", "func": fname, "inside": inside,
            "order_span": order_span, "empty_over": oa >= ob}


def _parse_select_items(text, tokens, scope):
    """The scope's SELECT list -> [{alias, expr, span}] (alias may be None)."""
    a, b = scope["select_span"]
    items = []
    for ia, ib in _split_top_commas(tokens, a, b):
        alias = None
        ea, eb = ia, ib
        if ib - ia >= 3 and _is_word(tokens[ib - 2], "AS") and tokens[ib - 1].kind in ("word", "qident"):
            alias, _ = _read_ident(tokens, ib - 1)
            ea, eb = ia, ib - 2
        elif (ib - ia >= 2 and tokens[ib - 1].kind in ("word", "qident")
              and tokens[ib - 2].text == ")"):
            # Bare alias right after a closing paren: f(...) alias
            alias, _ = _read_ident(tokens, ib - 1)
            ea, eb = ia, ib - 1
        expr = _classify_expr(text, tokens, ea, eb)
        if alias is None and expr["kind"] == "column":
            alias = expr["name"]
        items.append({"alias": alias, "expr": expr, "span": (ea, eb)})
    return items


def _resolve_group_keys(text, tokens, scope, items):
    """``(group_displays, key_names, fully_resolved)`` for one scope's GROUP BY.

    key_names keeps ONLY plain-column keys (identity lineage candidates);
    a positional key resolves through the SELECT items; aliases resolve to
    their item when it is a plain column. Expression keys are displayed but
    excluded (drill on them would be a false proof).
    """
    span = scope["group_span"]
    if not span:
        return [], [], True
    displays, names, resolved = [], [], True
    for ga, gb in _split_top_commas(tokens, span[0], span[1]):
        displays.append(_display(text, tokens, ga, gb))
        name, ok = _ident_chain(tokens, ga, gb)
        if ok:
            names.append(name)
            continue
        if gb - ga == 1 and tokens[ga].kind == "number" and "." not in tokens[ga].text:
            pos = int(tokens[ga].text) - 1
            if 0 <= pos < len(items) and items[pos]["expr"]["kind"] == "column":
                names.append(items[pos]["expr"]["name"])
                continue
        resolved = False  # expression / unresolvable key: shown, never drilled
    # Alias keys: map an alias back to its plain-column item.
    alias_map = {i["alias"].lower(): i for i in items if i["alias"]}
    out_names = []
    for n in names:
        item = alias_map.get(n.lower())
        if item is not None and item["expr"]["kind"] == "column":
            out_names.append(item["expr"]["name"])
        else:
            out_names.append(n)
    return displays, out_names, resolved


def _resolve_order(text, tokens, scope, items):
    """``(entries, fully_resolved)`` — entries = [(display, dir)] for ORDER BY."""
    span = scope["order_span"]
    if not span:
        return [], True
    entries, resolved = [], True
    alias_names = set(i["alias"].lower() for i in items if i["alias"])
    for oa, ob in _split_top_commas(tokens, span[0], span[1]):
        direction = "ASC"
        end = ob
        if end - 1 >= oa and tokens[end - 1].kind == "word" and tokens[end - 1].text.upper() in ("ASC", "DESC"):
            direction = tokens[end - 1].text.upper()
            end -= 1
        # NULLS FIRST/LAST tail tolerated.
        if end - 2 >= oa and _is_word(tokens[end - 2], "NULLS"):
            end -= 2
        name, ok = _ident_chain(tokens, oa, end)
        is_pos = (end - oa == 1 and tokens[oa].kind == "number")
        entries.append((_display(text, tokens, oa, end), direction))
        if not ok and not is_pos:
            resolved = False
        elif ok and name.lower() not in alias_names:
            # A plain column not in the SELECT list is still a resolved sort.
            pass
    return entries, resolved


def _having_steps(text, tokens, scope):
    """``(steps, fully_resolved)`` for the HAVING clause (display-only steps)."""
    span = scope["having_span"]
    if not span:
        return [], True
    where_toks = tokens[span[0]: span[1]]
    conjuncts, has_or = _split_conjuncts(where_toks)
    steps, resolved = [], True
    if has_or:
        return ([{"kind": "having", "params": [_display(text, tokens, span[0], span[1])]}],
                False)
    for conj in conjuncts:
        if not conj:
            continue
        disp = text[conj[0].start: conj[-1].end].strip()[:MAX_PARAM_CHARS]
        steps.append({"kind": "having", "params": [" ".join(disp.split())]})
        # Resolved when shaped <simple pred> or STRICTLY <AGG( ... )> <op> <literal>
        # (anything looser — e.g. a ratio of aggregates — stays unresolved).
        if _try_simple(conj) is not None:
            continue
        if not _is_simple_agg_comparison(conj):
            resolved = False
    return steps, resolved


def _is_simple_agg_comparison(conj):
    """True for the exact shape ``AGG ( ... ) <op> <literal>`` (HAVING check)."""
    if not conj or not (conj[0].kind == "word" and conj[0].text.upper() in _AGG_FUNCS):
        return False
    if len(conj) < 2 or conj[1].text != "(":
        return False
    close = _match_paren(conj, 1, len(conj))
    # Expect exactly: the closing paren, ONE comparison op, ONE literal — done.
    if close is None or close + 3 != len(conj):
        return False
    return conj[close + 1].kind == "op" and conj[close + 2].kind in ("number", "string")


def _predicate_step(pred):
    """One sql_parse predicate dict -> one filter_* step (frozen kinds)."""
    kind = _FILTER_STEP_KIND.get(pred["op"])
    if kind is None:
        return None
    col = pred["column"]
    values = pred.get("values") or []
    if kind in ("filter_null", "filter_notnull"):
        return {"kind": kind, "params": [col]}
    if kind in ("filter_in", "filter_notin"):
        listed = ", ".join(str(v) for v in values)[:MAX_PARAM_CHARS]
        return {"kind": kind, "params": [col, str(len(values)), listed]}
    if kind == "filter_between":
        return {"kind": kind, "params": [col, str(values[0]), str(values[1])]}
    return {"kind": kind, "params": [col, str(values[0])[:MAX_PARAM_CHARS]]}


def _scope_where(text, tokens, scope, covered_by_fragment):
    """``(filter_steps, dropped_displays)`` for one scope's WHERE clause.

    ``covered_by_fragment`` is True ONLY when sql_parse itself emitted a
    VALIDATED advanced fragment for this statement (the exact fragment the
    panel re-applies at runtime) — a non-simple conjunct then renders as
    filter_advanced and stays "complete". On any other shape the conjunct is
    dropped: listed both as a filter_unmapped step (inline honesty, §9) and in
    dropped_where (the completeness counter the verification level reads).
    """
    span = scope["where_span"]
    if not span:
        return [], []
    where_toks = tokens[span[0]: span[1]]
    conjuncts, has_or = _split_conjuncts(where_toks)
    steps, dropped = [], []
    if has_or:
        disp = _display(text, tokens, span[0], span[1], MAX_OPAQUE_CHARS)
        if covered_by_fragment:
            steps.append({"kind": "filter_advanced", "params": [disp]})
        else:
            steps.append({"kind": "filter_unmapped", "params": [disp]})
            dropped.append(disp)
        return steps, dropped
    for conj in conjuncts:
        if not conj:
            continue
        pred = _try_simple(conj)
        if pred is not None:
            step = _predicate_step(pred)
            if step is not None:
                steps.append(step)
                continue
        disp = " ".join(text[conj[0].start: conj[-1].end].split())[:MAX_OPAQUE_CHARS]
        if covered_by_fragment:
            steps.append({"kind": "filter_advanced", "params": [disp]})
        else:
            steps.append({"kind": "filter_unmapped", "params": [disp]})
            dropped.append(disp)
    return steps, dropped


def _item_steps(text, tokens, items):
    """SELECT items -> aggregate/calc/window steps + understood flag."""
    steps, understood = [], True
    for item in items:
        expr = item["expr"]
        kind = expr["kind"]
        if kind in ("column", "literal", "star"):
            continue
        if kind == "agg":
            steps.extend(_agg_steps(text, tokens, expr))
            if _agg_opaque(expr):
                understood = False
            continue
        if kind == "window":
            step = _window_step(text, tokens, expr)
            steps.append(step)
            continue
        if kind == "ratio":
            left, right = expr["left"], expr["right"]
            # "share of total" claims SUM(x) / SUM(x) OVER () EXACTLY: same
            # function (SUM), same argument text, and a truly EMPTY over —
            # SUM(rev)/SUM(forecast) OVER () or a PARTITION BY would make the
            # wording a lie (FP-05). Anything else renders as an honest ratio.
            if (left.get("kind") == "agg" and left.get("func") == "SUM"
                    and right.get("kind") == "window" and right.get("func") == "SUM"
                    and right.get("empty_over")):
                larg = left.get("arg_span")
                rarg = right.get("inside")
                ldisp = _display(text, tokens, larg[0], larg[1]) if larg else ""
                rdisp = _display(text, tokens, rarg[0], rarg[1]) if rarg else "?"
                # The window's inside is SUM(<arg>) — compare against SUM(left).
                if ldisp and rdisp.replace(" ", "") == "SUM({})".format(ldisp).replace(" ", ""):
                    steps.append({"kind": "calc_share", "params": [ldisp]})
                    continue
            ld = _display(text, tokens, expr["left_span"][0], expr["left_span"][1])
            rd = _display(text, tokens, expr["right_span"][0], expr["right_span"][1])
            steps.append({"kind": "calc_ratio", "params": [ld, rd]})
            if left.get("kind") == "opaque" or right.get("kind") == "opaque":
                understood = False
            continue
        if kind == "percent":
            sa, sb = expr["span"]
            steps.append({"kind": "calc_percent", "params": [_display(text, tokens, sa, sb)]})
            continue
        if kind == "diff":
            ld = _display(text, tokens, expr["left_span"][0], expr["left_span"][1])
            rd = _display(text, tokens, expr["right_span"][0], expr["right_span"][1])
            steps.append({"kind": "calc_diff", "params": [ld, rd]})
            continue
        # case / subquery / opaque: shown verbatim, understanding lost.
        sa, sb = item["span"]
        steps.append({"kind": "opaque",
                      "params": [_display(text, tokens, sa, sb, MAX_OPAQUE_CHARS)]})
        understood = False
    return steps, understood


def _agg_opaque(expr):
    arg = expr.get("arg") or {}
    if arg.get("kind") == "case":
        # SUM(CASE WHEN <simple pred> THEN x END) is understood (agg_filtered).
        return not expr.get("_case_simple", False)
    return arg.get("kind") in ("opaque", "subquery")


def _agg_steps(text, tokens, expr):
    """One agg expr -> its step(s); CASE-filtered aggregates get agg_filtered."""
    func = expr["func"]
    arg = expr.get("arg") or {}
    if func == "COUNT":
        if arg.get("kind") == "star":
            return [{"kind": "agg_count_star", "params": []}]
        span = expr.get("arg_span")
        disp = _display(text, tokens, span[0], span[1]) if span else ""
        kind = "agg_count_distinct" if expr.get("distinct") else "agg_count"
        return [{"kind": kind, "params": [disp]}]
    if arg.get("kind") == "case":
        ca, cb = arg["span"]
        # ELSE 0 is neutral ONLY for SUM. For AVG it weighs the denominator,
        # for MIN/MAX the 0 competes — "only when <cond>" would then be a lie.
        parsed = _parse_simple_case(text, tokens, ca, cb,
                                    allow_else_zero=(func == "SUM"))
        if parsed is not None:
            cond_disp, then_disp = parsed
            expr["_case_simple"] = True
            return [{"kind": "agg_filtered", "params": [func, then_disp, cond_disp]}]
        return [{"kind": "opaque",
                 "params": [_display(text, tokens, ca, cb, MAX_OPAQUE_CHARS)]}]
    span = expr.get("arg_span")
    disp = _display(text, tokens, span[0], span[1]) if span else ""
    kind = _AGG_STEP_KIND.get(func)
    if kind is None:
        return [{"kind": "opaque", "params": [disp]}]
    return [{"kind": kind, "params": [disp]}]


def _parse_simple_case(text, tokens, a, b, allow_else_zero=True):
    """CASE WHEN <simple pred> THEN <expr> [ELSE 0|NULL] END -> (cond, then).

    ``allow_else_zero`` lets the caller restrict the neutral ELSE to NULL only
    (AVG/MIN/MAX — where ELSE 0 changes the math and the wording would lie).
    """
    if not _is_word(tokens[a], "CASE") or not _is_word(tokens[b - 1], "END"):
        return None
    j = a + 1
    if j >= b or not _is_word(tokens[j], "WHEN"):
        return None
    then_pos, depth = None, 0
    for k in range(j + 1, b - 1):
        t = tokens[k]
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
        elif depth == 0 and _is_word(t, "THEN"):
            then_pos = k
            break
        elif depth == 0 and _is_word(t, "WHEN") and k > j:
            return None  # multiple WHEN branches: not a simple filter
    if then_pos is None:
        return None
    pred = _try_simple(tokens[j + 1: then_pos])
    if pred is None:
        return None
    end = b - 1
    else_pos = None
    depth = 0
    for k in range(then_pos + 1, b - 1):
        t = tokens[k]
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
        elif depth == 0 and _is_word(t, "ELSE"):
            else_pos = k
            break
        elif depth == 0 and _is_word(t, "WHEN"):
            return None
    if else_pos is not None:
        # Only a neutral ELSE keeps the "agg where cond" reading: NULL always,
        # 0 only when the caller's aggregate treats 0 as neutral (SUM).
        ea, eb = else_pos + 1, b - 1
        is_null = eb - ea == 1 and _is_word(tokens[ea], "NULL")
        is_zero = eb - ea == 1 and tokens[ea].text == "0"
        if not (is_null or (is_zero and allow_else_zero)):
            return None
        end = else_pos
    cond = _display(text, tokens, j + 1, then_pos)
    then = _display(text, tokens, then_pos + 1, end)
    return cond, then


def _window_step(text, tokens, expr):
    func = expr["func"]
    order = ""
    if expr.get("order_span"):
        oa, ob = expr["order_span"]
        order = _display(text, tokens, oa, ob)
    if func in ("ROW_NUMBER",):
        return {"kind": "window_row_number", "params": [order]}
    if func in ("RANK", "DENSE_RANK", "NTILE"):
        return {"kind": "window_rank", "params": [order]}
    if func in _SHIFT_FUNCS:
        ia, ib = expr.get("inside", (0, 0))
        return {"kind": "window_lag", "params": [_display(text, tokens, ia, ib)]}
    # Aggregate over a window: running when ordered, otherwise a whole-partition
    # total (rendered as a share component elsewhere, or a generic running step).
    ia, ib = expr.get("inside", (0, 0))
    arg = _display(text, tokens, ia, ib)
    if expr.get("order_span"):
        return {"kind": "window_running", "params": [arg, order]}
    return {"kind": "window_running", "params": [arg, ""]}


# ---------------------------------------------------------------------------
# Chain assembly + identity lineage + the public entry point.
# ---------------------------------------------------------------------------

def _collect_chain(text, tokens, ctes, main_lo, main_hi):
    """Analyse the main scope + every reachable CTE/derived body, source-first.

    Returns ``(chain, dag_complete)`` — chain = ordered scope analyses
    [{name, scope, items}] (CTEs in declaration order, derived bodies, then the
    outer scope last) or ``(None, False)`` when any body fails to scan.
    """
    analyses = {}
    order = []
    cte_names = set()
    for cte in ctes or []:
        scope = _scan_scope(tokens, cte["lo"], cte["hi"])
        if scope is None:
            return None, False
        analyses[cte["name"].lower()] = {"name": cte["name"], "scope": scope,
                                         "items": _parse_select_items(text, tokens, scope)}
        order.append(cte["name"].lower())
        cte_names.add(cte["name"].lower())
    outer = _scan_scope(tokens, main_lo, main_hi)
    if outer is None:
        return None, False
    chain = [analyses[n] for n in order]
    # Derived FROM subqueries (any scope): analysed as anonymous chain links.
    pending = [outer] + [a["scope"] for a in chain]
    depth = 0
    seen_spans = set()
    while pending and depth < _MAX_DERIVED_DEPTH:
        nxt = []
        for scope in pending:
            for da, db in scope.get("derived", []):
                if (da, db) in seen_spans:
                    continue
                seen_spans.add((da, db))
                sub = _scan_scope(tokens, da, db)
                if sub is None:
                    return None, False
                chain.insert(0, {"name": None, "scope": sub,
                                 "items": _parse_select_items(text, tokens, sub)})
                nxt.append(sub)
        pending = nxt
        depth += 1
    chain.append({"name": None, "scope": outer,
                  "items": _parse_select_items(text, tokens, outer)})
    # DAG completeness: every CTE-shaped ref must resolve to a declared CTE
    # (a ref that is neither a real table nor a known CTE cannot be traced).
    return chain, True


def _real_table_refs(chain, cte_names):
    """All non-CTE table refs across the chain (with multiplicity)."""
    real = []
    for link in chain:
        for ref in link["scope"]["refs"]:
            if ref["table"].lower() not in cte_names:
                real.append(ref)
    return real


def _column_traces_to_source(col, link, by_name, cte_names, depth=0):
    """The SOURCE-TABLE column name ``col`` traces to, or None (no identity).

    Walks CTE references: a scope reading the real table directly resolves a
    plain column to ITSELF; a scope reading a CTE resolves only if that CTE
    exposes the column as a plain-column item (alias or same name), recursively
    — and the returned name is the column at the END of the chain. Returning
    the SOURCE name (not the outer alias) is what makes the drill filter the
    right physical column when a CTE renames (FP-06: a rename plus a homonymous
    source column would otherwise drill an unrelated column).
    """
    if depth > _MAX_LINEAGE_DEPTH:
        return None
    refs = link["scope"]["refs"]
    if not refs:
        return None
    ref = refs[0]
    low = ref["table"].lower()
    if low not in cte_names:
        return col  # reads the real table: the plain column IS the source column
    target = by_name.get(low)
    if target is None:
        return None
    for item in target["items"]:
        alias = (item["alias"] or "").lower()
        if alias == col.lower() and item["expr"]["kind"] == "column":
            return _column_traces_to_source(item["expr"]["name"], target,
                                            by_name, cte_names, depth + 1)
    return None


def explain_select(sql):
    """Best-effort business explanation of one SELECT statement. NEVER raises."""
    try:
        return _explain(sql)
    except Exception:
        return _failed("explain_failed")


def _explain(sql):
    if not isinstance(sql, str) or not sql.strip():
        return _failed("invalid_sql")
    if len(sql) > MAX_SQL_CHARS:
        return _failed("sql_too_long")
    text = _mask_comments(sql)
    tokens, err = tokenize(text)
    if err:
        return _failed(err)
    if tokens and tokens[-1].text == ";":
        tokens = tokens[:-1]
    if any(t.text == ";" for t in tokens):
        return _failed("multi_statement")
    if not tokens or not (_is_word(tokens[0], "SELECT") or _is_word(tokens[0], "WITH")):
        return _failed("not_select")
    depth = 0
    for t in tokens:
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
            if depth < 0:
                return _failed("unbalanced_parens")
    if depth != 0:
        return _failed("unbalanced_parens")

    ctes, main_lo, recursive = _parse_with_clause(tokens)
    if main_lo < 0:
        return _failed("with_clause_unsupported")
    cte_names = set(c["name"].lower() for c in ctes or [])

    out = _defaults()
    out["ok"] = True
    out["has_recursive_cte"] = recursive

    chain, dag_complete = _collect_chain(text, tokens, ctes, main_lo, len(tokens))
    if chain is None:
        # Bodies that do not scan (degenerate SQL): honest minimal answer.
        out["select_understood"] = False
        return out

    by_name = {link["name"].lower(): link for link in chain if link["name"]}
    outer = chain[-1]

    # --- sources / joins ----------------------------------------------------
    real_refs = _real_table_refs(chain, cte_names)
    # single_source requires (a) exactly ONE real-table occurrence AND (b) no
    # multi-ref scope anywhere on the chain: a self-join THROUGH a CTE (FROM c a
    # JOIN c b) references the same real table twice while real_refs sees it
    # once — any 2-ref/JOIN scope therefore disqualifies, CTE refs included.
    multi_ref_scope = any(
        len(link["scope"]["refs"]) >= 2 or link["scope"]["saw_join"]
        for link in chain
    )
    out["single_source"] = len(real_refs) == 1 and not multi_ref_scope
    has_set_op = any(link["scope"]["set_arms"] for link in chain)
    out["has_set_op"] = has_set_op
    # An unresolvable ref (neither real table nor declared CTE elsewhere) would
    # appear as a "real" table — the DAG stays complete by construction here.
    calc_resolved = dag_complete and not recursive

    steps = []
    if real_refs:
        steps.append({"kind": "source", "params": [real_refs[0]["table"]]})
        for ref in real_refs[1:]:
            steps.append({"kind": "join",
                          "params": [(ref.get("join_type") or "INNER").lower(),
                                     ref["table"]]})
    # CTE self-joins / CTE joins: every ref beyond the first of a scope that is
    # NOT a real table is still a join the user must see (honesty: the join
    # multiplies/filters rows even when both sides are intermediate steps).
    for link in chain:
        for ref in link["scope"]["refs"][1:]:
            if ref["table"].lower() in cte_names:
                steps.append({"kind": "join",
                              "params": [(ref.get("join_type") or "INNER").lower(),
                                         ref["table"]]})

    # --- per-scope analysis, source-first ------------------------------------
    dropped_all = []
    where_complete = True
    select_understood = True
    group_keys = []
    grouping_scopes = 0
    # A non-simple conjunct is only "covered" when sql_parse itself emits a
    # VALIDATED advanced fragment for this statement — that fragment is exactly
    # what the panel re-applies at runtime. Re-deriving the single-table rule
    # here would diverge (sql_parse counts WHERE sub-query scopes too, FP-01):
    # asking sql_parse directly keeps explain and execution provably aligned.
    parsed_for_fragment = parse_select(sql)
    fragment_applied = bool(
        parsed_for_fragment.get("ok")
        and parsed_for_fragment.get("advanced")
        and validate_fragment(parsed_for_fragment["advanced"])
    )
    for link in chain:
        scope = link["scope"]
        fsteps, dropped = _scope_where(text, tokens, scope, fragment_applied)
        steps.extend(fsteps)
        dropped_all.extend(dropped)
        if dropped:
            where_complete = False
        if scope["distinct"]:
            steps.append({"kind": "distinct", "params": []})
        if scope["group_span"]:
            grouping_scopes += 1
            displays, names, resolved = _resolve_group_keys(text, tokens, scope, link["items"])
            steps.append({"kind": "group", "params": [", ".join(displays)[:MAX_PARAM_CHARS]]})
            if not resolved:
                calc_resolved = False
            if grouping_scopes == 1:
                candidate_keys = []
                for name in names:
                    # Keys carry the SOURCE column name (end of the identity
                    # chain) — that is the column the drill must filter on the
                    # physical table (FP-06); the outer alias is display-only.
                    source_name = _column_traces_to_source(name, link, by_name, cte_names)
                    if source_name is not None:
                        candidate_keys.append(source_name)
                # Only keep keys when EVERY group key resolved AND traced —
                # a partial key set would drill a superset of the group.
                if resolved and len(candidate_keys) == len(names):
                    group_keys = candidate_keys
        isteps, understood = _item_steps(text, tokens, link["items"])
        steps.extend(isteps)
        if not understood:
            select_understood = False
        hsteps, hresolved = _having_steps(text, tokens, scope)
        steps.extend(hsteps)
        if not hresolved:
            calc_resolved = False

    if grouping_scopes > 1:
        group_keys = []  # stacked aggregations: drill lineage not provable (v1)

    # --- outer ordering / top-N ----------------------------------------------
    order_entries, order_resolved = _resolve_order(text, tokens, outer["scope"], outer["items"])
    if not order_resolved:
        calc_resolved = False
    limit = outer["scope"]["limit"]
    if limit is not None and order_entries and order_resolved:
        # ALL ordering keys travel in the step (tie-breakers decide WHICH rows
        # make the top-N — hiding them under a "decomposed" badge would lie).
        joined = ", ".join("{} {}".format(d, direction.lower())
                           for d, direction in order_entries)[:MAX_PARAM_CHARS]
        steps.append({"kind": "topn", "params": [str(limit), joined]})
    else:
        if order_entries:
            steps.append({"kind": "sort",
                          "params": [order_entries[0][0], order_entries[0][1].lower()]})
        if limit is not None:
            # LIMIT without a resolved ORDER BY is an arbitrary sample — it
            # must NEVER be worded as a top-N (anti-lie rule).
            steps.append({"kind": "limit_arbitrary", "params": [str(limit)]})

    if has_set_op:
        arms = max(link["scope"]["set_arms"] for link in chain)
        steps.append({"kind": "union", "params": [str(arms)]})
        where_complete = False  # unanalysed arms can widen the row scope
        group_keys = []

    out["steps"] = steps[:MAX_STEPS]
    out["where_complete"] = where_complete
    out["dropped_where"] = dropped_all
    out["group_keys"] = group_keys
    out["select_understood"] = select_understood
    out["calc_resolved"] = calc_resolved and select_understood
    if recursive:
        out["group_keys"] = []
    return out

