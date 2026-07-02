"""Free-text search condition builder for the Source Data Explorer (pure - NO dataiku).

The explorer lets a user type a term and highlights rows where it appears in ANY
column. This module builds the ONE SQL condition for that: a single ILIKE over an
accent-folded ``concat_ws`` of every live column, exactly the shape the agent's
attribute-lookup tool uses (case via lower()/ILIKE, accents via a translate() map).

Callers inject the two quoting functions (identifier + literal) so the builder itself
stays import-free and unit-testable with stub quoters. Folding happens at QUERY time
only; the stored data is never modified.
"""

# Lowercase + accent-fold map, applied char-for-char by SQL translate() on the
# column side and by str.translate() on the needle, so both sides fold identically.
# FROM/TO MUST be the same length (copied verbatim from the attribute-lookup tool).
_ACCENTS_FROM = "àáâãäåçèéêëìíîïñòóôõöùúûüýÿ"
_ACCENTS_TO = "aaaaaaceeeeiiiinooooouuuuyy"
_NEEDLE_TRANSLATION = str.maketrans(_ACCENTS_FROM, _ACCENTS_TO)

# A 1-char needle ILIKE '%x%' matches almost every row; such terms are treated as
# "no search" (the builder returns None) so the whole page is shown instead.
MIN_NEEDLE_CHARS = 2


def fold_needle(term):
    """The term as a LIKE needle: stripped, lowercased, then accent-folded through the
    shared translate map, so it folds the same way as the SQL column side."""
    return str(term or "").strip().lower().translate(_NEEDLE_TRANSLATION)


def like_escape(value):
    """Escape the LIKE wildcards so a typed ``%`` / ``_`` matches literally.

    Backslash-escapes ``\\`` first (so it cannot double-escape a following wildcard),
    then ``%`` and ``_``. Pairs with an ``ESCAPE '\\'`` clause on the ILIKE.
    """
    return (str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_"))


def _accent_fold_sql(col_expr, quote_literal):
    """SQL expression: ``col_expr`` lowercased and accent-folded via translate().

    ``CAST(... AS text)`` keeps it valid for any physical column type; ``col_expr`` is
    an already-quoted identifier or a text expression (here a concat). The accent maps
    are inlined as quoted literals via the injected ``quote_literal``.
    """
    return ("translate(lower(CAST(%s AS text)), %s, %s)"
            % (col_expr, quote_literal(_ACCENTS_FROM), quote_literal(_ACCENTS_TO)))


def build_search_condition(columns, needle, quote_ident, quote_literal):
    """One ILIKE over an accent-folded concat of ALL columns, or None.

    Returns None when there is nothing to search: no columns, or a folded needle
    shorter than ``MIN_NEEDLE_CHARS`` (an over-broad term). Otherwise a single SQL
    condition string matching the term ANYWHERE in the row:

        translate(lower(CAST(concat_ws(' ', "c1", "c2", ...) AS text)),
                  '<FROM>', '<TO>') ILIKE '%<escaped folded needle>%' ESCAPE '\\'

    ``concat_ws`` converts each argument to text and skips NULLs. Identifiers are
    quoted via ``quote_ident``; the needle + accent maps via ``quote_literal`` (the
    needle is already LIKE-escaped so a typed wildcard matches literally).
    """
    folded = fold_needle(needle)
    if not columns or len(folded) < MIN_NEEDLE_CHARS:
        return None
    pattern = quote_literal("%" + like_escape(folded) + "%")
    concat = "concat_ws(' ', %s)" % ", ".join(quote_ident(c) for c in columns)
    return "%s ILIKE %s ESCAPE '\\'" % (_accent_fold_sql(concat, quote_literal), pattern)
