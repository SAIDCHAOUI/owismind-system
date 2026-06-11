# =============================================================================
# OWIsMind — SALESDRIVE v2 "Revenue Code Agent" (Code Agent Dataiku)
# -----------------------------------------------------------------------------
# Replaces the visual SalesDrive agent (agent:rNTZ781a) with deterministic code.
# Architecture : UNDERSTAND -> RESOLVE -> COMPOSE -> QUERY -> RENDER
#
#   1. UNDERSTAND  1 LLM call (strict JSON) doing ONLY the linguistic work:
#                  scope, language, analytical intent, phases, period(s),
#                  group-by axis, top-N, business terms to resolve.
#   2. RESOLVE     The CODE calls the resolver tool once (exact catalog values).
#                  Routing on overall_status is pure Python — ambiguous or
#                  unresolved terms -> deterministic clarification, never SQL.
#   3. COMPOSE     The semantic_question is built from FROZEN templates: the
#                  LLM never writes it. Filters are appended verbatim.
#   4. QUERY       The CODE calls the Semantic Model Query tool directly and
#                  captures the generated SQL + result rows from its return
#                  value (deterministic Evidence capture — no trace guessing).
#   5. RENDER      Markdown table + figures are formatted BY CODE (exact by
#                  construction). A small LLM writes only the headline sentence
#                  and every number it cites is verified against the result —
#                  any unverifiable number -> deterministic fallback headline.
#
# Collaboration contract with the orchestrator ("Le Cerveau", v2.3+):
#   - Streams the SAME event dialect as a visual agent: AGENT_BLOCK_START with
#     the historical blockIds (resolve, query_revenue_semantic,
#     format_tool_output, clarify_user, out_of_scope_msg) and AGENT_TOOL_START
#     with the historical tool names — the orchestrator registry labels apply
#     unchanged.
#   - Emits ONE final structured AGENT_RESULT event {status, language, intent,
#     resolvedFilters, sqlCount, rowCount}. status is machine-readable:
#     ready | need_clarification | out_of_scope | no_data | error.
#   - Creates one trace subspan named "semantic-model-query" per generated SQL
#     with outputs {sql, success, row_count, rows, columns} — the orchestrator
#     Evidence extraction (_find_generated_sql / _extract_result) works as-is
#     and result capture becomes deterministic.
#
# Cornerstones (NON NEGOTIABLE, inherited from OWIsMind):
#   - This agent NEVER invents a figure: every number shown comes from the
#     semantic tool result or is refused.
#   - Refuse rather than hallucinate: unresolved/ambiguous terms -> ask.
#   - The file is STANDALONE: stdlib + dataiku only, pasted into a DSS Code
#     Agent. It must never import from the plugin.
# =============================================================================

import json
import logging
import math
import re
import time
import unicodedata
from datetime import datetime

import dataiku
from dataiku.llm.python import BaseLLM

logger = logging.getLogger("owismind.salesdrive")

# =============================================================================
# 1. CONFIGURATION  (fill the IDs below from the DSS instance before pasting)
# =============================================================================

# LLM Mesh id for the UNDERSTAND call (strict JSON). The orchestrator planner
# id is known to work on the instance; swap in a cheaper/faster model later.
UNDERSTAND_LLM_ID = "openai:LLM-7064-revforecast:vertex_ai/gemini-2.5-pro"
HEADLINE_LLM_ID = None             # None -> reuse UNDERSTAND_LLM_ID

# Agent tool IDS (confirmed on the instance via project.list_agent_tools()).
# If get_agent_tool fails on an id, the code falls back to a name match.
RESOLVER_TOOL_ID = "aNxeOc4"       # Drive_Revenues_resolve_filter_value (InlinePython)
SEMANTIC_TOOL_ID = "v4oqA6R"       # revenue_semantic_query (semantic-model-query)
# Tool NAMES as the orchestrator registry knows them (tool_labels keys). They
# travel in AGENT_TOOL_START events: the live timeline maps them to the French
# business labels — NEVER put ids or technical strings in those events.
RESOLVER_TOOL_NAME = "Drive_Revenues_resolve_filter_value"
SEMANTIC_TOOL_NAME = "revenue_semantic_query"
# Preferred input key of the Semantic Model Query tool. The real key is
# auto-detected from the tool descriptor at runtime (pick_semantic_input_key);
# this constant is only the first candidate.
SEMANTIC_QUESTION_KEY = "question"

MAX_TERMS = 8                      # business terms passed to the resolver
TABLE_MAX_ROWS = 10                # rows displayed in the answer table
HEADLINE_MAX_CHARS = 400           # LLM headline budget (beyond -> fallback)

# Result capture caps — local mirrors of the orchestrator/webapp caps (the
# file is standalone). The webapp re-caps independently before persistence.
MAX_RESULT_ROWS = 50
MAX_RESULT_COLS = 50
_RESULT_CELL_MAX_CHARS = 256
_RESULT_JSON_MAX_CHARS = 64000
_MAX_WALK_DEPTH = 50               # depth guard for the tool-output walker

# =============================================================================
# 2. DOMAIN CONSTANTS (DRIVE_Revenues)
# =============================================================================

KNOWN_PHASES = ("ACTUALS", "BUDGET", "FORECAST", "Q3F", "HLF")
KNOWN_INTENTS = ("total", "breakdown", "top_n", "compare_phases",
                 "compare_periods", "trend", "generic")

# Logical group-by axes -> (dataset column, frozen grouping instruction).
GROUP_BY_RULES = {
    "customer": ("diamond_id",
                 "Group by diamond_id and return MAX(Account_name) AS "
                 "Account_name for display. Never group by Account_name."),
    "parent_group": ("Parent_Group", "Group by Parent_Group."),
    "product": ("Product", "Group by Product."),
    "solution": ("Solution", "Group by Solution."),
    "solution_line": ("SolutionLine", "Group by SolutionLine."),
    "sirano_product": ("sirano_product", "Group by sirano_product."),
    "partner": ("Account_partner", "Group by Account_partner."),
    "distribution_type": ("distribution_type", "Group by distribution_type."),
    "sales_entity": ("sales_entity", "Group by sales_entity."),
    "sales_zone": ("sales_zone", "Group by sales_zone."),
    "month": ("year_month",
              "Group by month (year_month truncated to the month), ordered "
              "chronologically."),
    "year": ("year_month",
             "Group by calendar year derived from year_month, ordered "
             "chronologically."),
}

# Metric / scenario / operator words that must NEVER reach the resolver, even
# if the UNDERSTAND model extracts them by mistake (defense in depth — same
# DO-NOT-EXTRACT list as the historical visual prompt).
_TERM_STOPWORDS = frozenset((
    "revenue", "revenues", "ca", "turnover", "sales", "chiffre", "affaires",
    "budget", "actuals", "actual", "forecast", "q3f", "hlf", "pipeline",
    "delta", "variance", "gap", "ecart", "comparison", "comparaison",
    "year", "month", "annee", "mois", "ytd", "h1", "h2", "q1", "q2", "q3", "q4",
    "top", "split", "breakdown", "repartition", "trend", "tendance",
    "evolution", "amount", "montant", "sum", "somme", "average", "moyenne",
    "total", "client", "clients", "customer", "customers", "produit",
    "produits", "product", "products",
))

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Columns a user may explicitly designate in a "VALUE (Column)" qualified term
# (the exact format our own clarification teaches). Keys are normalized
# (lowercase, separators stripped) -> canonical dataset column.
_QUALIFIED_COLUMNS = {}
for _col in ("Product", "Solution", "SolutionLine", "sirano_product",
             "distribution_type", "sales_entity", "sales_zone", "Parent_Group",
             "Account_name", "carrier_code", "diamond_id", "booking_type",
             "Account_partner", "Phase"):
    _QUALIFIED_COLUMNS[re.sub(r"[\s_]+", "", _col.lower())] = _col

_QUALIFIED_RE = re.compile(r"^(.+?)\s*[\(\[]\s*([A-Za-z_ ]+?)\s*[\)\]]$")

# Same column priority as the resolver's exact_offer_priority rule: when all
# remaining candidates carry the SAME value, the most specific offer column
# wins deterministically (no clarification needed).
_AMBIGUITY_COLUMN_PRIORITY = {"Product": 1, "Solution": 2, "SolutionLine": 3,
                              "sirano_product": 4}

# =============================================================================
# 3. USER-FACING TEXTS (deterministic, fr/en)
# =============================================================================

OUT_OF_SCOPE_TEXT = {
    "fr": ("Cette question sort du périmètre revenus que je couvre. "
           "Posez-moi une question sur les revenus, la facturation, le "
           "forecast ou le pipeline — je m'en occupe."),
    "en": ("This question is outside the revenue scope I cover. "
           "Ask me about revenue, billing, forecast or pipeline — "
           "I'll take care of it."),
}
NO_DATA_TEXT = {
    "fr": "Aucune donnée trouvée pour les filtres et la période demandés.",
    "en": "No data found for the specified filters and period.",
}
INTERNAL_ERROR_TEXT = {
    "fr": ("⚠️ Je n'ai pas pu traiter votre question (incident technique côté "
           "agent revenus). Pourriez-vous réessayer dans un instant ?"),
    "en": ("⚠️ I could not process your question (technical issue on the "
           "revenue agent side). Could you try again in a moment?"),
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
    "fr": "Je n'ai pas trouvé « {raw} » dans les données de revenus.{hint} "
          "Pouvez-vous vérifier l'orthographe ou donner la valeur exacte ?",
    "en": "I could not find “{raw}” in the revenue data.{hint} "
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
HEADLINE_SINGLE = {
    "fr": "{metric} ({scope}) : {value}.",
    "en": "{metric} ({scope}): {value}.",
}
METRIC_LABEL = {
    "fr": "Revenu total",
    "en": "Total revenue",
}
PERIOD_ALL_LABEL = {
    "fr": "toutes périodes disponibles",
    "en": "all available periods",
}

NBSP = "\u00a0"   # non-breaking space, thousands separator (frozen convention)

# =============================================================================
# 4. UNDERSTAND — prompt + JSON schema (the ONLY free-text LLM interpretation)
# =============================================================================

UNDERSTAND_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "scope": {"type": "string", "enum": ["revenue", "out_of_scope"]},
        "language": {"type": "string", "enum": ["fr", "en"]},
        "intent": {"type": "string", "enum": list(KNOWN_INTENTS)},
        "phases": {"type": "array",
                   "items": {"type": "string", "enum": list(KNOWN_PHASES)}},
        "period": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["explicit", "all_available"]},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "label": {"type": "string"},
            },
            "required": ["mode"],
        },
        "periods": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "label": {"type": "string"},
                },
                "required": ["start", "end"],
            },
        },
        "group_by": {"type": "string", "enum": list(GROUP_BY_RULES.keys())},
        "top_n": {"type": "integer"},
        "terms": {"type": "array", "items": {"type": "string"}},
        "clarification": {"type": "string"},
    },
    "required": ["scope", "language"],
}


def build_understand_prompt(current_date):
    """System prompt of the UNDERSTAND call. It extracts STRUCTURE only —
    the semantic question and all SQL-bound text are composed by code."""
    return (
        "You are the understanding module of the SalesDrive revenue agent "
        "(dataset DRIVE_Revenues: revenue lines by month, product, customer "
        "and phase). You do NOT answer. You do NOT write SQL. You return ONE "
        "JSON object describing the question. Current date: " + str(current_date) + ".\n\n"
        "FIELDS:\n"
        "- scope: \"revenue\" if the question is about revenue / CA / billing "
        "/ forecast / pipeline / budget on customers, products, zones, "
        "partners or distribution; \"out_of_scope\" otherwise (tickets, NPS, "
        "chitchat, anything else).\n"
        "- language: language of the question (\"fr\" or \"en\").\n"
        "- intent: one of\n"
        "  - \"total\": one aggregated revenue figure.\n"
        "  - \"breakdown\": revenue split along ONE axis (customer, product, "
        "solution, solution_line, sirano_product, partner, distribution_type, "
        "sales_entity, sales_zone, parent_group, month, year).\n"
        "  - \"top_n\": ranking along one axis (set top_n; default 10).\n"
        "  - \"compare_phases\": actuals vs budget (delta / variance / gap "
        "versus budget).\n"
        "  - \"compare_periods\": comparison between several time periods "
        "(fill \"periods\" with one entry per period).\n"
        "  - \"trend\": evolution over time (monthly).\n"
        "  - \"generic\": revenue question that fits none of the above.\n"
        "- phases: scenarios involved. Default is [\"ACTUALS\"] when none is "
        "mentioned. Mentioning budget adds BUDGET; forecast/prévision/landing/"
        "expected billing/pipeline adds FORECAST; Q3F or HLF only if "
        "explicitly mentioned. Never invent a scenario.\n"
        "- period: {\"mode\": \"explicit\", \"start\": \"YYYY-MM-DD\", "
        "\"end\": \"YYYY-MM-DD\", \"label\": <as the user said it>} when the "
        "user gives a period (\"2026\" -> 2026-01-01..2026-12-31; \"janvier "
        "2026\" -> 2026-01-01..2026-01-31; \"YTD 2026\" -> 2026-01-01..current "
        "date). {\"mode\": \"all_available\"} when NO period is given — never "
        "ask for a period, never invent one.\n"
        "- group_by: the axis for breakdown/top_n intents.\n"
        "- terms: business VALUES that must be resolved against the dataset "
        "catalog: customer/account names, carrier codes, diamond ids, parent "
        "groups, products, solutions, solution lines, sirano products, "
        "partners/resellers, distribution types (direct/indirect), sales "
        "entities (GCP/GCS), sales zones. NEVER extract: metric words "
        "(revenue, CA, turnover, amount), scenario words (budget, actuals, "
        "forecast, Q3F, HLF), dates/periods, operations (top, split, delta, "
        "comparison, trend, sum, average). When the user explicitly "
        "designates the category/column of a value — typically when answering "
        "a disambiguation question — keep or produce the qualified form "
        "\"VALUE (Column)\" with the dataset column name: \"IPL (Product)\", "
        "\"IPL (sirano_product)\". Never strip an existing \"(Column)\" "
        "qualifier from a term.\n"
        "- clarification: ONLY when the question is about revenue but too "
        "vague to plan at all (e.g. \"et alors ?\"). One short question in "
        "the user's language. Leave empty otherwise.\n\n"
        "CONVERSATION CONTEXT (when provided before the question): it carries "
        "the PREVIOUS assistant message and the user's raw answer. If that "
        "previous message asked a disambiguation question listing candidate "
        "values and the user's answer designates one of them — by name, by "
        "column, by position (\"the first one\", \"la deuxième\"), or by "
        "partial wording — output that candidate as a qualified term "
        "\"VALUE (Column)\" copied EXACTLY from the list. Never output a "
        "candidate that is not in the list; if the answer clearly matches "
        "none of them, extract terms as usual.\n\n"
        "EXAMPLES:\n"
        "Q: \"CA d'Algérie Télécom en 2025 ?\" -> {\"scope\":\"revenue\","
        "\"language\":\"fr\",\"intent\":\"total\",\"phases\":[\"ACTUALS\"],"
        "\"period\":{\"mode\":\"explicit\",\"start\":\"2025-01-01\","
        "\"end\":\"2025-12-31\",\"label\":\"2025\"},\"terms\":[\"Algérie Télécom\"]}\n"
        "Q: \"Top 5 clients indirects vs budget 2026\" -> {\"scope\":\"revenue\","
        "\"language\":\"fr\",\"intent\":\"top_n\",\"top_n\":5,"
        "\"group_by\":\"customer\",\"phases\":[\"ACTUALS\",\"BUDGET\"],"
        "\"period\":{\"mode\":\"explicit\",\"start\":\"2026-01-01\","
        "\"end\":\"2026-12-31\",\"label\":\"2026\"},\"terms\":[\"indirect\"]}\n"
        "Q: \"écart vs budget sur EVPL\" -> {\"scope\":\"revenue\","
        "\"language\":\"fr\",\"intent\":\"compare_phases\","
        "\"phases\":[\"ACTUALS\",\"BUDGET\"],\"period\":{\"mode\":"
        "\"all_available\"},\"terms\":[\"EVPL\"]}\n"
        "Q: \"Top 10 clients pour le produit 'IPL (Product)'\" (disambiguation "
        "answer) -> {\"scope\":\"revenue\",\"language\":\"fr\",\"intent\":\"top_n\","
        "\"top_n\":10,\"group_by\":\"customer\",\"phases\":[\"ACTUALS\"],"
        "\"period\":{\"mode\":\"all_available\"},\"terms\":[\"IPL (Product)\"]}\n"
        "Q: \"météo à Paris ?\" -> {\"scope\":\"out_of_scope\",\"language\":\"fr\"}\n\n"
        "HARD RULES:\n"
        "- Output ONLY the JSON object. No markdown fences, no commentary.\n"
        "- Copy terms EXACTLY as the user wrote them (accents included) — "
        "never correct, translate or expand them.\n"
        "- A question about revenue, customers, products or amounts is NEVER "
        "out_of_scope.\n"
    )


# =============================================================================
# 5. PURE HELPERS — validation
# =============================================================================

def _safe_json_parse(text):
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


def _norm_term(term):
    """Accent-insensitive lowercase, for the stopword check only."""
    s = unicodedata.normalize("NFKD", str(term)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", s.strip().lower())


def _validate_period(raw):
    """-> {"mode": "all_available"} or {"mode": "explicit", start, end, label}."""
    if not isinstance(raw, dict):
        return {"mode": "all_available"}
    start = str(raw.get("start") or "")
    end = str(raw.get("end") or "")
    if raw.get("mode") == "explicit" and _DATE_RE.match(start) and _DATE_RE.match(end) and start <= end:
        label = str(raw.get("label") or "").strip()[:60] or ("%s → %s" % (start, end))
        return {"mode": "explicit", "start": start, "end": end, "label": label}
    return {"mode": "all_available"}


def validate_understanding(parsed, instruction):
    """Deterministic validation/degradation of the UNDERSTAND output.

    Never raises. Unknown enum values degrade field by field (never the whole
    object); only structurally unusable output returns None (-> retry, then
    internal error: refuse rather than guess).
    """
    if not isinstance(parsed, dict):
        return None
    scope = parsed.get("scope")
    if scope not in ("revenue", "out_of_scope"):
        return None
    language = parsed.get("language") if parsed.get("language") in ("fr", "en") else "fr"

    out = {"scope": scope, "language": language, "instruction": instruction,
           "intent": "generic", "phases": ["ACTUALS"],
           "period": {"mode": "all_available"}, "periods": [],
           "group_by": None, "top_n": None, "terms": [], "clarification": ""}
    if scope == "out_of_scope":
        return out

    intent = parsed.get("intent")
    out["intent"] = intent if intent in KNOWN_INTENTS else "generic"

    phases, seen = [], set()
    for p in parsed.get("phases") or []:
        if p in KNOWN_PHASES and p not in seen:
            seen.add(p)
            phases.append(p)
    if out["intent"] == "compare_phases":
        phases = ["ACTUALS", "BUDGET"]          # frozen business rule
    out["phases"] = phases or ["ACTUALS"]

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
            out["intent"] = "generic"           # unusable comparison -> generic

    group_by = parsed.get("group_by")
    out["group_by"] = group_by if group_by in GROUP_BY_RULES else None
    top_n = parsed.get("top_n")
    if isinstance(top_n, int) and 1 <= top_n <= 50:
        out["top_n"] = top_n
    if out["intent"] == "top_n" and not out["top_n"]:
        out["top_n"] = 10
    if out["intent"] in ("breakdown", "top_n") and not out["group_by"]:
        out["group_by"] = "customer"

    terms, seen = [], set()
    for t in parsed.get("terms") or []:
        t = str(t).strip()
        key = _norm_term(t)
        if not t or not key or key in _TERM_STOPWORDS or key in seen:
            continue
        seen.add(key)
        terms.append(t[:80])
        if len(terms) >= MAX_TERMS:
            break
    out["terms"] = terms

    out["clarification"] = str(parsed.get("clarification") or "").strip()[:500]
    return out


# =============================================================================
# 6. PURE HELPERS — semantic question composition (FROZEN templates)
# =============================================================================

def build_semantic_question(u, filter_clauses):
    """Compose the natural-language instruction for the Semantic Model Query
    tool from the validated understanding + resolved filter clauses.

    100% deterministic: every sentence comes from a frozen template; the only
    free text is the user instruction itself (generic intent) and the verbatim
    filter clauses produced by the resolver tool.
    """
    intent = u["intent"]
    phase_list = ", ".join(u["phases"])
    parts = []

    if intent == "compare_phases":
        parts.append(
            "Compare ACTUALS revenue versus BUDGET revenue (revenue = "
            "SUM(amount_eur)). Return: the ACTUALS revenue, the BUDGET "
            "revenue, the delta amount (ACTUALS minus BUDGET) and the delta "
            "percentage versus BUDGET.")
    elif intent == "total":
        parts.append("Compute the total revenue (SUM(amount_eur)).")
        parts.append("Consider ONLY rows whose Phase is in: %s." % phase_list)
    elif intent in ("breakdown", "top_n"):
        column, rule = GROUP_BY_RULES[u["group_by"]]
        parts.append("Compute the revenue (SUM(amount_eur)) broken down by %s." % column)
        parts.append(rule)
        parts.append("Consider ONLY rows whose Phase is in: %s." % phase_list)
        if intent == "top_n":
            parts.append("Order by revenue descending and keep only the top %d." % u["top_n"])
        else:
            parts.append("Order by revenue descending.")
    elif intent == "compare_periods":
        descr = "; ".join(
            "%s: from %s to %s" % (p["label"], p["start"], p["end"]) for p in u["periods"])
        parts.append(
            "Compare the revenue (SUM(amount_eur)) across the following "
            "periods of year_month: %s. Return one row per period with the "
            "period label and its revenue, plus the delta amount and the "
            "delta percentage between the periods." % descr)
        parts.append("Consider ONLY rows whose Phase is in: %s." % phase_list)
    elif intent == "trend":
        parts.append(
            "Compute the monthly revenue (SUM(amount_eur)) grouped by month "
            "(year_month), ordered chronologically.")
        parts.append("Consider ONLY rows whose Phase is in: %s." % phase_list)
    else:  # generic — closest to the historical behaviour, filters still exact
        parts.append(
            "Answer this revenue question on the DRIVE_Revenues data "
            "(revenue = SUM(amount_eur)): \"%s\"." % u["instruction"])
        parts.append("Consider ONLY rows whose Phase is in: %s." % phase_list)

    if intent != "compare_periods":
        if u["period"]["mode"] == "explicit":
            parts.append("Only include rows with year_month between %s and %s."
                         % (u["period"]["start"], u["period"]["end"]))
        else:
            parts.append("Do not apply any filter on year_month.")

    if filter_clauses:
        parts.append(
            "Apply ALL of the following filters with the EXACT values given "
            "(verbatim): " + " AND ".join(filter_clauses) + ".")

    parts.append("Use the explicit filter values above. Do not fuzzy-match on Account_name.")
    return " ".join(parts)


# =============================================================================
# 7. PURE HELPERS — resolver routing, disambiguation policy, clarifications
# =============================================================================

def parse_qualified_term(term):
    """'IPL (Product)' -> ('Product', 'IPL'); None when the term is not
    column-qualified. Only whitelisted dataset columns qualify. This is the
    deterministic round-trip that breaks clarification loops: our own
    clarification teaches this exact format, so echoing it must always work."""
    m = _QUALIFIED_RE.match(str(term or "").strip())
    if not m:
        return None
    value = m.group(1).strip().strip("'\"")
    column = _QUALIFIED_COLUMNS.get(re.sub(r"[\s_]+", "", m.group(2).strip().lower()))
    if not column or not value:
        return None
    return (column, value)


def refine_ambiguous(raw_value, candidates, preferred_column=None):
    """Deterministic ambiguity policy applied AFTER the resolver tool.

    1. preferred_column (from a 'VALUE (Column)' qualified term) keeps only
       the candidates of that column when any exist.
    2. Strict exact-value preference: candidates whose target_value equals the
       raw term (case-insensitive, trimmed) evict normalization collisions
       (e.g. 'IPL +' normalizing to 'ipl' next to the real 'IPL').
    3. One distinct value left -> auto-pick by column priority (resolved, no
       clarification). Several distinct values -> still ambiguous, but on the
       REDUCED candidate list (a real business choice, e.g. IPL vs IPL +).

    Returns ("resolved", candidate) or ("ambiguous", reduced_candidates).
    """
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
        cands = sorted(cands, key=lambda c: _AMBIGUITY_COLUMN_PRIORITY.get(
            c.get("target_column"), 99))
        return ("resolved", cands[0])
    return ("ambiguous", cands)


def refine_resolutions(resolutions, preferred_columns=None):
    """Apply the ambiguity policy to every resolver resolution. preferred_columns
    maps lowercased raw base values -> explicit column from qualified terms."""
    preferred = preferred_columns or {}
    refined = []
    for r in resolutions or []:
        if r.get("status") == "ambiguous":
            pref = preferred.get(str(r.get("raw_value") or "").strip().lower())
            verdict, data = refine_ambiguous(r.get("raw_value"), r.get("candidates"), pref)
            if verdict == "resolved":
                refined.append({
                    "raw_value": r.get("raw_value", ""), "status": "resolved",
                    "target_column": data.get("target_column", ""),
                    "target_value": data.get("target_value", ""),
                    "display_value": data.get("display_value", "") or data.get("target_value", ""),
                    "method": "ambiguity_policy", "confidence": 100,
                })
                continue
            r = dict(r, candidates=data)
        refined.append(r)
    return refined


def build_filter_clauses(resolutions):
    """SQL-safe filter clauses from the resolved items (deduplicated). Built
    by code because the policy above can change the resolver's own list."""
    clauses, seen = [], set()
    for r in resolutions or []:
        if r.get("status") != "resolved":
            continue
        column = str(r.get("target_column") or "").strip()
        value = str(r.get("target_value") or "")
        if not column or not value:
            continue
        clause = "%s = '%s'" % (column, value.replace("'", "''"))
        if clause not in seen:
            seen.add(clause)
            clauses.append(clause)
    return clauses


def build_clarification(resolutions, lang):
    """Deterministic clarification from the resolver output (ambiguous and/or
    unresolved terms). Lists candidates verbatim — never invents values."""
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
                # Teach the machine-parseable echo format: answering with it
                # hits parse_qualified_term and can NEVER loop back here.
                lines.append(CLARIFY_ECHO_HINT[lang].format(example=example))
            blocks.append("\n".join(lines))
        elif status == "unresolved":
            best = r.get("best_candidate") or {}
            display = best.get("display_value") or best.get("target_value") or ""
            hint = CLARIFY_UNRESOLVED_HINT[lang].format(display=display) if display else ""
            blocks.append(CLARIFY_UNRESOLVED[lang].format(raw=r.get("raw_value", ""), hint=hint))
    return "\n\n".join(blocks)


def resolved_filters_summary(resolutions):
    """Compact machine-readable list for AGENT_RESULT.resolvedFilters."""
    out = []
    for r in resolutions or []:
        if r.get("status") == "resolved":
            out.append({"column": r.get("target_column", ""),
                        "value": r.get("target_value", ""),
                        "display": r.get("display_value", ""),
                        "raw": r.get("raw_value", "")})
    return out


# =============================================================================
# 8. PURE HELPERS — semantic tool output extraction
# =============================================================================

_ROW_KEYS = ("rows", "records", "data", "result_rows", "values")
_COLUMN_KEYS = ("columns", "column_names", "headers")
_SQL_KEYS = ("sql", "query", "generated_sql")
_ANSWER_KEYS = ("answer", "text", "output_text", "completion", "result")


def _cap_cell(value):
    """Bound one result cell: JSON-safe primitives stay, the rest is str()[:256]."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return str(value)[:_RESULT_CELL_MAX_CHARS]


def _extract_result(outputs):
    """Capped {columns, rows, truncated} from one dict node, or None.

    Same accepted shapes and caps as the orchestrator capture (frozen mirror):
    list of dicts, or list of lists + a sibling columns key.
    """
    for key in _ROW_KEYS:
        raw = outputs.get(key)
        if not isinstance(raw, list) or not raw:
            continue
        if all(isinstance(r, dict) for r in raw):
            first_keys = list(raw[0].keys())
            columns = [str(c)[:_RESULT_CELL_MAX_CHARS] for c in first_keys[:MAX_RESULT_COLS]]
            rows = [[_cap_cell(r.get(c)) for c in first_keys[:MAX_RESULT_COLS]]
                    for r in raw[:MAX_RESULT_ROWS]]
            truncated = len(raw) > MAX_RESULT_ROWS or len(first_keys) > MAX_RESULT_COLS
        elif all(isinstance(r, (list, tuple)) for r in raw):
            columns = None
            truncated_cols = False
            for col_key in _COLUMN_KEYS:
                cand = outputs.get(col_key)
                if isinstance(cand, list) and cand:
                    columns = [str(c)[:_RESULT_CELL_MAX_CHARS] for c in cand[:MAX_RESULT_COLS]]
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
            result = {"columns": columns, "rows": [], "truncated": True}
        return result
    return None


def extract_semantic_payload(raw_output):
    """Best-effort structured payload from the Semantic Model Query tool
    return value: {"sqls": [str], "result": {...}|None, "answer": str|None,
    "row_count": int|None, "shape_keys": [str]}.

    The walker is defensive: the exact output schema of the managed tool is
    instance-dependent, so every recognised fragment is harvested and absence
    stays honest (None). shape_keys logs the top-level keys for ops debugging.
    """
    payload = {"sqls": [], "result": None, "answer": None,
               "row_count": None, "shape_keys": []}
    if not isinstance(raw_output, dict):
        return payload
    root = raw_output.get("output") if isinstance(raw_output.get("output"), dict) else raw_output
    payload["shape_keys"] = sorted(str(k) for k in root.keys())[:30]

    def _walk(node, depth):
        if depth > _MAX_WALK_DEPTH:
            return
        if isinstance(node, dict):
            for key in _SQL_KEYS:
                val = node.get(key)
                if isinstance(val, str) and val.strip() and val not in payload["sqls"]:
                    payload["sqls"].append(val)
            if payload["result"] is None:
                found = _extract_result(node)
                if found is not None:
                    payload["result"] = found
            if payload["row_count"] is None and isinstance(node.get("row_count"), int):
                payload["row_count"] = node["row_count"]
            if payload["answer"] is None:
                for key in _ANSWER_KEYS:
                    val = node.get(key)
                    if isinstance(val, str) and val.strip():
                        payload["answer"] = val.strip()
                        break
            for v in node.values():
                _walk(v, depth + 1)
        elif isinstance(node, list):
            for item in node:
                _walk(item, depth + 1)

    _walk(root, 0)
    if payload["row_count"] is None and payload["result"] is not None:
        payload["row_count"] = len(payload["result"]["rows"])
    return payload


_SEMANTIC_KEY_CANDIDATES = ("question", "query", "user_question", "input", "text")


def pick_semantic_input_key(descriptor):
    """Auto-detect the input key of the Semantic Model Query tool from its
    descriptor's inputSchema. Tries the known candidates first, then falls
    back to the only string property if there is exactly one. Pure, never
    raises; returns SEMANTIC_QUESTION_KEY when nothing better is found."""
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
# 9. PURE HELPERS — rendering (table, figures, verified headline)
# =============================================================================

def _is_pct_column(name):
    low = str(name).lower()
    return any(tok in low for tok in ("pct", "percent", "%", "_perc", "pourcentage"))


def _is_amount_column(name):
    low = str(name).lower()
    return any(tok in low for tok in ("amount", "revenue", "revenu", "eur",
                                      "actuals", "budget", "forecast", "delta", "total", "ca_"))


def format_int_thousands(value):
    """12345678 -> '12 345 678' (non-breaking spaces, frozen convention)."""
    sign = "-" if value < 0 else ""
    digits = str(abs(int(value)))
    groups = []
    while digits:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    return sign + NBSP.join(groups)


def format_amount(value):
    """EUR amounts: thousands separators, 0 decimals (frozen convention)."""
    try:
        return format_int_thousands(int(round(float(value)))) + NBSP + "EUR"
    except (TypeError, ValueError):
        return str(value)


def format_pct(value):
    """Percentages: 1 decimal max (frozen convention)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    txt = ("%.1f" % v).rstrip("0").rstrip(".")
    return (txt or "0") + NBSP + "%"


def format_cell(value, column_name):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        if _is_pct_column(column_name):
            return format_pct(value)
        if _is_amount_column(column_name):
            return format_amount(value)
        if isinstance(value, float) and not float(value).is_integer():
            return ("%.2f" % value)
        return format_int_thousands(int(value))
    return str(value)


def build_table(result, lang):
    """Markdown table from the captured result, capped at TABLE_MAX_ROWS
    displayed rows. Returns "" when there is nothing tabular to show."""
    if not result or not result.get("rows"):
        return ""
    columns = result.get("columns") or []
    rows = result["rows"]
    lines = ["| " + " | ".join(str(c) for c in columns) + " |",
             "|" + "|".join(" --- " for _ in columns) + "|"]
    for row in rows[:TABLE_MAX_ROWS]:
        cells = [format_cell(v, columns[i] if i < len(columns) else "")
                 for i, v in enumerate(row)]
        lines.append("| " + " | ".join(cells) + " |")
    table = "\n".join(lines)
    extra = len(rows) - TABLE_MAX_ROWS
    if extra > 0:
        table += "\n\n" + MORE_ROWS_NOTE[lang].format(n=extra)
    if result.get("truncated"):
        table += "\n\n" + TRUNCATED_NOTE[lang]
    return table


def _scope_label(u, lang):
    """Human scope chunk for deterministic headlines: phases + period."""
    scope = ", ".join(u["phases"])
    if u["period"]["mode"] == "explicit":
        scope += ", " + u["period"]["label"]
    else:
        scope += ", " + PERIOD_ALL_LABEL[lang]
    return scope


def build_fallback_headline(u, result, lang):
    """Deterministic headline. Single numeric value -> full sentence with the
    figure; anything else -> neutral lead-in (the table carries the data)."""
    scope = _scope_label(u, lang)
    if result and len(result.get("rows") or []) == 1:
        row = result["rows"][0]
        columns = result.get("columns") or []
        numeric = [(columns[i] if i < len(columns) else "", v)
                   for i, v in enumerate(row)
                   if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(numeric) == 1:
            col, val = numeric[0]
            value = format_pct(val) if _is_pct_column(col) else format_amount(val)
            return HEADLINE_SINGLE[lang].format(metric=METRIC_LABEL[lang],
                                                scope=scope, value=value)
    return HEADLINE_FALLBACK[lang].format(scope=scope)


# --- verified LLM headline ----------------------------------------------------

_NUM_TOKEN_RE = re.compile(r"\d(?:[\d\s.,\u00a0\u202f]*\d)?")


def _digits(text):
    return re.sub(r"\D", "", str(text))


def allowed_number_set(result, extra_texts):
    """Set of digit-strings the headline is allowed to cite: every numeric
    cell (raw + rounded forms), every digit group of string cells, plus digit
    groups from the question/period labels (years, months...)."""
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
    """True iff EVERY number cited in the headline exists in the allowed set.
    One unverifiable figure -> the whole headline is rejected (frozen rule)."""
    if not text:
        return False
    for token in _NUM_TOKEN_RE.findall(text):
        nd = _digits(token)
        if nd and nd not in allowed:
            return False
    return True


HEADLINE_PROMPT = (
    "You write the OPENING of a revenue answer: one short sentence carrying "
    "the main figure(s), optionally followed by ONE short business signal "
    "sentence IF it is directly visible in the table (large variance, sharp "
    "drop, spike). Plain text only — no markdown, no emoji, no greeting.\n"
    "HARD RULES:\n"
    "- Write in this language: {language}.\n"
    "- Every figure MUST be copied EXACTLY from the RESULT TABLE (no "
    "rounding, no unit conversion, no computed figures).\n"
    "- EUR amounts: thousands separated, 0 decimals. Percentages: 1 decimal max.\n"
    "- Never speculate, never suggest alternative filters.\n"
)


# =============================================================================
# 10. USAGE / TRACE HELPERS (mirrors of the orchestrator, file is standalone)
# =============================================================================

def _find_usage_metadata(obj, _depth=0):
    found = []
    if _depth > 200:
        return found
    if isinstance(obj, dict):
        if isinstance(obj.get("usageMetadata"), dict):
            found.append(obj["usageMetadata"])
        for v in obj.values():
            found.extend(_find_usage_metadata(v, _depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_usage_metadata(item, _depth + 1))
    return found


# =============================================================================
# 11. EVENTS (same dialect as a DSS visual agent — orchestrator relays as-is)
# =============================================================================

def _ev(kind, data=None):
    return {"chunk": {"type": "event", "eventKind": kind, "eventData": data or {}}}


def _block(block_id):
    return _ev("AGENT_BLOCK_START", {"blockId": block_id})


def _tool_start(tool_name):
    return _ev("AGENT_TOOL_START", {"toolName": tool_name})


def _agent_result(status, u, resolved_filters=None, sql_count=0, row_count=None):
    """Final structured event of the collaboration contract (machine-readable,
    consumed by the orchestrator — never displayed directly)."""
    return _ev("AGENT_RESULT", {
        "status": status,
        "language": (u or {}).get("language", "fr"),
        "intent": (u or {}).get("intent", ""),
        "resolvedFilters": resolved_filters or [],
        "sqlCount": sql_count,
        "rowCount": row_count,
    })


# =============================================================================
# 12. AGENT
# =============================================================================

class MyLLM(BaseLLM):

    def __init__(self):
        self._tools = {}
        self._semantic_key = None    # auto-detected from the tool descriptor

    # ------------------------------------------------------------------ tools
    def _get_tool(self, project, tool_id, tool_name):
        """get_agent_tool(tool_id) with a one-shot fallback matching tool_name
        against list_agent_tools() (covers a recreated tool whose id changed)."""
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

    # ------------------------------------------------------------------- LLM
    def _call_json_llm(self, project, system_prompt, user_msg, schema, span, instruction):
        """2 attempts (native JSON mode then prompt-only) + deterministic
        validation. Returns the validated understanding dict or None."""
        llm = project.get_llm(UNDERSTAND_LLM_ID)
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
                validated = validate_understanding(
                    _safe_json_parse(getattr(resp, "text", None)), instruction)
                if validated:
                    span.attributes["attempt"] = attempt
                    return validated
            except Exception as e:
                logger.warning("Understand attempt %d failed: %s", attempt, e)
                span.attributes["attempt_%d_error" % attempt] = str(e)[:300]
        return None

    def _llm_headline(self, project, question, table_md, language, span):
        """Verified-headline LLM call. Returns the raw text or None on failure
        (verification happens in the caller against the allowed number set)."""
        llm = project.get_llm(HEADLINE_LLM_ID or UNDERSTAND_LLM_ID)
        try:
            completion = llm.new_completion() \
                .with_message(HEADLINE_PROMPT.replace("{language}", language), role="system") \
                .with_message("USER QUESTION: %s\n\nRESULT TABLE:\n%s" % (question, table_md),
                              role="user")
            resp = completion.execute()
            try:
                if resp.trace:
                    span.append_trace(resp.trace)
            except Exception:
                pass
            text = (getattr(resp, "text", None) or "").strip()
            return text[:HEADLINE_MAX_CHARS] if text else None
        except Exception as e:
            logger.warning("Headline LLM failed: %s", e)
            span.attributes["headline_error"] = str(e)[:300]
            return None

    # ------------------------------------------------------------------ MAIN
    def process_stream(self, query, settings, trace):
        t0 = time.perf_counter()
        u = None
        try:
            project = dataiku.api_client().get_default_project()
            instruction, conversation_context = self._extract_input(query)
            if not instruction:
                yield {"chunk": {"text": INTERNAL_ERROR_TEXT["fr"]}}
                yield _agent_result("error", u)
                return

            # ============ UNDERSTAND ============
            yield _block("resolve")
            user_msg = 'QUESTION: "%s"\nReturn ONLY the JSON object.' % instruction
            if conversation_context:
                # Continuity with the previous turn (e.g. a pending
                # disambiguation question and its candidate list).
                user_msg = conversation_context + "\n\n" + user_msg
            with trace.subspan("salesdrive:understand") as sp:
                sp.inputs["question"] = instruction
                sp.inputs["has_context"] = bool(conversation_context)
                u = self._call_json_llm(
                    project,
                    build_understand_prompt(datetime.now().strftime("%Y-%m-%d")),
                    user_msg, UNDERSTAND_JSON_SCHEMA, sp, instruction)
                sp.outputs["understanding"] = u
            if u is None:
                # Refuse rather than guess: no usable structure after 2 attempts.
                yield {"chunk": {"text": INTERNAL_ERROR_TEXT["fr"]}}
                yield _agent_result("error", u)
                return
            lang = u["language"]

            if u["scope"] == "out_of_scope":
                yield _block("out_of_scope_msg")
                yield {"chunk": {"text": OUT_OF_SCOPE_TEXT[lang]}}
                yield _agent_result("out_of_scope", u)
                return

            if u["clarification"]:
                yield _block("clarify_user")
                yield {"chunk": {"text": u["clarification"]}}
                yield _agent_result("need_clarification", u)
                return

            # ============ RESOLVE (deterministic routing) ============
            filter_clauses, resolutions = [], []
            if u["terms"]:
                # "VALUE (Column)" qualified terms (the format our own
                # clarification teaches, or an explicit user designation):
                # the resolver gets the BASE value; the explicit column then
                # drives the ambiguity policy below.
                preferred_columns, base_terms = {}, []
                for t in u["terms"]:
                    q = parse_qualified_term(t)
                    if q:
                        preferred_columns[q[1].strip().lower()] = q[0]
                        base_terms.append(q[1])
                    else:
                        base_terms.append(t)

                yield _tool_start(RESOLVER_TOOL_NAME)
                with trace.subspan("salesdrive:resolve-filter-values") as sp:
                    sp.inputs["raw_values"] = base_terms
                    out = self._get_tool(project, RESOLVER_TOOL_ID, RESOLVER_TOOL_NAME).run(
                        {"raw_values": base_terms, "user_text": instruction})
                    body = out.get("output", out) if isinstance(out, dict) else {}
                    resolutions = refine_resolutions(body.get("resolutions") or [],
                                                     preferred_columns)
                    filter_clauses = build_filter_clauses(resolutions)
                    sp.outputs["overall_status"] = body.get("overall_status", "")
                    sp.outputs["refined_statuses"] = [r.get("status") for r in resolutions]
                    sp.outputs["filter_clauses"] = filter_clauses

                if any(r.get("status") in ("ambiguous", "unresolved") for r in resolutions):
                    clarification = build_clarification(resolutions, lang)
                    yield _block("clarify_user")
                    yield {"chunk": {"text": clarification or CLARIFY_UNRESOLVED[lang]
                                     .format(raw=", ".join(u["terms"]), hint="")}}
                    yield _agent_result("need_clarification", u,
                                        resolved_filters=resolved_filters_summary(resolutions))
                    return

            resolved_filters = resolved_filters_summary(resolutions)

            # ============ COMPOSE + QUERY ============
            semantic_question = build_semantic_question(u, filter_clauses)
            yield _block("query_revenue_semantic")
            yield _tool_start(SEMANTIC_TOOL_NAME)
            with trace.subspan("salesdrive:semantic-tool") as sp:
                sp.inputs["semantic_question"] = semantic_question
                try:
                    tool = self._get_tool(project, SEMANTIC_TOOL_ID, SEMANTIC_TOOL_NAME)
                    if self._semantic_key is None:
                        try:
                            self._semantic_key = pick_semantic_input_key(tool.get_descriptor())
                        except Exception:
                            self._semantic_key = SEMANTIC_QUESTION_KEY
                    sp.attributes["input_key"] = self._semantic_key
                    raw = tool.run({self._semantic_key: semantic_question})
                except Exception as e:
                    logger.exception("Semantic tool failed")
                    sp.attributes["error"] = str(e)[:500]
                    yield {"chunk": {"text": INTERNAL_ERROR_TEXT[lang]}}
                    yield _agent_result("error", u, resolved_filters=resolved_filters)
                    return
                payload = extract_semantic_payload(raw)
                sp.outputs["shape_keys"] = payload["shape_keys"]
                sp.outputs["sql_count"] = len(payload["sqls"])
                sp.outputs["row_count"] = payload["row_count"]

            # Frozen Evidence contract: one "semantic-model-query" span per SQL,
            # outputs {sql, success, row_count} (+ rows/columns on the first) —
            # the orchestrator's _find_generated_sql captures them as today,
            # and result capture is now deterministic (no trace-key guessing).
            for i, sql in enumerate(payload["sqls"]):
                with trace.subspan("semantic-model-query") as sp:
                    sp.outputs["sql"] = sql
                    sp.outputs["success"] = True
                    sp.outputs["row_count"] = payload["row_count"]
                    if i == 0 and payload["result"] is not None:
                        sp.outputs["columns"] = payload["result"]["columns"]
                        sp.outputs["rows"] = payload["result"]["rows"]

            # ============ RENDER (deterministic core + verified headline) =====
            yield _block("format_tool_output")
            result = payload["result"]
            if not result or not result.get("rows"):
                if payload["answer"]:
                    # No tabular rows but the tool produced an answer: relay it
                    # (same trust level as the historical flow), honestly sourced.
                    yield {"chunk": {"text": payload["answer"]}}
                    yield _agent_result("ready", u, resolved_filters=resolved_filters,
                                        sql_count=len(payload["sqls"]),
                                        row_count=payload["row_count"])
                else:
                    yield {"chunk": {"text": NO_DATA_TEXT[lang]}}
                    yield _agent_result("no_data", u, resolved_filters=resolved_filters,
                                        sql_count=len(payload["sqls"]), row_count=0)
                return

            table_md = build_table(result, lang)
            headline = build_fallback_headline(u, result, lang)
            allowed = allowed_number_set(
                result, [instruction, semantic_question,
                         u["period"].get("label", ""),
                         " ".join(p.get("label", "") for p in u["periods"])])
            with trace.subspan("salesdrive:headline") as sp:
                candidate = self._llm_headline(project, instruction, table_md, lang, sp)
                if candidate and verify_headline(candidate, allowed):
                    headline = candidate
                    sp.outputs["verified"] = True
                else:
                    sp.outputs["verified"] = False   # fallback already in place

            yield {"chunk": {"text": headline + "\n\n" + table_md}}
            yield _agent_result("ready", u, resolved_filters=resolved_filters,
                                sql_count=len(payload["sqls"]),
                                row_count=payload["row_count"])
            logger.info("SalesDrive v2 done in %dms",
                        int((time.perf_counter() - t0) * 1000))

        except Exception:
            logger.exception("SalesDrive v2 failure")
            lang = (u or {}).get("language", "fr")
            yield {"chunk": {"text": INTERNAL_ERROR_TEXT.get(lang, INTERNAL_ERROR_TEXT["fr"])}}
            yield _agent_result("error", u)

    # ---------------------------------------------------------------- INPUT
    @staticmethod
    def _extract_input(query):
        """(instruction, conversation_context) from the completion messages.

        instruction = last user message (the orchestrator's self-contained
        rewrite). conversation_context = system messages injected by the
        orchestrator (v2.3 "pass_context": previous assistant message + raw
        user answer — disambiguation continuity). Both empty-safe."""
        msgs = query.get("messages", []) or []
        instruction = ""
        for m in reversed(msgs):
            if m.get("role") == "user" and m.get("content"):
                instruction = m["content"]
                break
        context = "\n".join(m["content"] for m in msgs
                            if m.get("role") == "system" and m.get("content"))
        return instruction, context.strip()
