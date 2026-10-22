"""Pure helpers that assemble the multi-turn payload sent to a DSS agent.

No ``dataiku`` import - kept pure so it is unit-testable without a DSS runtime.
The official LLM Mesh pattern is to replay each prior turn via
``completion.with_message(content, role)`` (developer.dataiku.com), so we build an
ordered list of ``{"role", "content"}`` dicts: prior messages verbatim, then the
current user turn carrying a compact context block APPENDED AT THE END.

Why a SUFFIX (not a prefix): small models honor an instruction far better when it
sits in the highest-recency slot - the very end of the current message. Burying the
name/date/language directive at the start lets the model forget it. So the block -
user, date, web-app language, and the load-bearing rule "answer in the language of
THIS message" - is appended last (see ``build_user_suffix``).

Reply language (``detect_prompt_language_scored``), deterministic, fr vs en only.
Keep the orchestrator's ``_detect_lang`` fallback and the dev-harness port
(dev-harness/mock/live/lang.mjs) in sync with this algorithm:
  1. Lowercase, fold typographic apostrophes to "'", tokenize into runs of latin
     letters (accented included) and apostrophes; digits/hyphens/punctuation split.
  2. Each token adds evidence: a French elision prefix (l' d' j' c' n' s' m' t' qu'
     jusqu' lorsqu' puisqu') = +1 fr then the remainder is scored as a word; an
     English "n't" = +1 en; an English "'s/'re/'ve/'ll/'d/'m" = +1 en then the head
     is scored as a word.
  3. A word in the shared business-noun list (revenue/revenu, client, budget, total,
     phase, ACTUALS, ...) scores NOTHING. Otherwise, first match wins: French
     function word +1 fr; English function word +1 en; French diacritic +1 fr; for
     5+ letters, a suffix cue +0.5 (-ement -eur -eux -ais -ez -aux -ique = fr,
     -ing -ed -ly -ness -ful = en). Words shared by both languages are in no list.
  4. confidence = min(1, top) * (0.5 + 0.5 * margin / total), 0 on a tie or no
     evidence. ``detect_prompt_language`` keeps the majority language when the
     confidence is > 0.5 (strict majority AND at least one full point), else
     returns the default (the web-app language): "42", "ok", "revenue 2025 EMEA".
"""
import json
import math
import re

# strftime template for the per-turn date stamp (C locale -> English, unambiguous).
_DATE_FMT = "%A, %B %d, %Y at %H:%M"

# Human label of each supported language (for the END-placed context block).
_LANG_LABEL = {"fr": "French", "en": "English"}


# Model modes the front can request (Smart / Pro / Claude). Relayed to the agent
# as a compact control token APPENDED to the current turn (the orchestrator parses
# and strips it, so it never reaches the model as part of the question). Unknown /
# absent -> the orchestrator defaults to "smart" (the recommended tier).
MODEL_MODES = ("smart", "pro", "claude")


def resolve_effective_mode(requested, supports_modes):
    """The EFFECTIVE response mode of a run (persisted on the exchange + relayed).

    Contract (pure, side-effect free):
      - agent WITHOUT the mode dial (``supports_modes`` False) -> ``None`` (the run
        carries no mode token, exactly as before the mode feature existed);
      - agent WITH the dial + a valid requested mode -> that mode ('smart'/'pro'/'claude');
      - agent WITH the dial + a missing/unknown requested mode -> 'smart' (the default).

    Mode is EPHEMERAL in the UI (the picker resets to smart after each send), but the
    mode a given answer actually used is stamped on its exchange row from this value.
    """
    if not supports_modes:
        return None
    return requested if requested in MODEL_MODES else "smart"


# Deterministic reply-language scorer of a RAW user message (stdlib only). Computed
# ONCE by the backend, on the clean message (before the English date stamp could
# contaminate it), and handed to the agent as an authoritative ⟦owi:lang=…⟧ token +
# an end-of-prompt imperative. The algorithm is documented in the module docstring;
# the dev-harness port (dev-harness/mock/live/lang.mjs) uses the SAME word lists and
# its node test asserts the parity, so edit both together.

# Tokens: runs of latin letters (accented included) and apostrophes, on the
# lowercased message with typographic apostrophes folded to "'". Digits, hyphens and
# punctuation split tokens ("montre-moi" -> "montre", "moi").
_TOKEN_RE = re.compile(r"[a-zà-öø-ÿœæ']+")
_APOSTROPHES_RE = re.compile(r"[’‘`´]")
# French-only diacritics: a token carrying one is French evidence (weight 1).
_FR_ACCENT_RE = re.compile(r"[àâæçèéêëîïôœùûüÿ]")
# French elision ("l'", "d'", "qu'", ...) at the start of a token: French evidence,
# and the remainder is scored as a word of its own ("l'évolution" -> "évolution").
_FR_ELISION_RE = re.compile(r"^(?:l|d|j|c|n|s|m|t|qu|jusqu|lorsqu|puisqu)'(?=[a-zà-ÿœ])")
# English contractions: "n't" (no head scoring: "can't" -> "ca" would read French)
# and "'s/'re/'ve/'ll/'d/'m" (the head is scored: "what's" -> "what").
_EN_NEG_RE = re.compile(r"n't$")
_EN_CONTRACTION_RE = re.compile(r"'(?:s|re|ve|ll|d|m)$")

# Function words (articles, pronouns, prepositions, conjunctions, auxiliaries, common
# request verbs, question words, politeness, calendar words). Weight 1 each. Words
# that exist in BOTH languages (a, an, as, but, car, dont, me, non, on, or, plus, son,
# per, via, compare, ok) are deliberately in neither list.
_FR_WORDS = frozenset("""
le la les un une des du de au aux ce cet cette ces ça ca ceci cela
mon ma mes ton ta tes sa ses notre nos votre vos leur leurs
je tu il elle ils elles nous vous moi toi lui eux se
qui que quoi quel quelle quels quelles lequel laquelle où ou
et mais donc ni si pour par avec sans sous sur dans chez entre vers depuis
pendant avant après apres selon contre comme
est sont suis es sommes êtes etes était etait étaient etaient été ete être etre
ai avons avez ont avoir avait aurait sera serait
fait faire fais faites peux peut pouvez pourrais pourriez pourrait
veux veut voulez voudrais souhaite souhaiterais dois doit devrait faut
montre montrez montrer donne donnez donner affiche affichez afficher
ajoute ajoutez ajouter rajoute rajoutez rajouter explique expliquez expliquer
comparez comparer liste lister analyser calcule calculer refais
combien comment pourquoi quand
merci bonjour bonsoir salut svp stp oui
ne pas moins très tres bien aussi encore déjà deja
tous toutes tout toute chaque quelques autre autres voici voilà voila
aujourd peu beaucoup trop mois année annee années annees semaine trimestre jour jours
""".split())
_EN_WORDS = frozenset("""
the of and to in is are was were be been being am
do does did done doing have has had having
i you he she it we they them us my your his her its our their
this that these those there here
what which who whom whose why how when where
can could would should will shall may might must
please thanks thank hello hi hey
with from by at for about into over under between than then
also just only very all each every some any no not yes
show give tell make add explain display list get need want see help let
more most less much many if so up out same other both
month year week quarter last next previous current
""".split())
# Business nouns and loanwords shared by both languages: ZERO weight, and exempt from
# the suffix cues below (e.g. "reporting" is not English evidence, "management" is
# not French evidence).
_NEUTRAL_WORDS = frozenset("""
revenue revenues revenu revenus client clients budget budgets total totals
phase phases actuals actual forecast forecasts kpi ytd mtd segment segments
management investment payment payments department statement document moment
agreement requirement settlement engagement achievement improvement element
marketing pricing reporting billing booking consulting planning forecasting
ranking leasing trading roaming streaming meeting parking holding building
entrepreneur unique technique boutique critique
""".split())
# Suffix cues (weight 0.5, tokens of 5+ letters, after the word lists): a lone cue
# never decides on its own (see the confidence rule).
_FR_SUFFIXES = ("ement", "eur", "eux", "ais", "ez", "aux", "ique")
_EN_SUFFIXES = ("ing", "ed", "ly", "ness", "ful")
_SUFFIX_MIN_LEN = 5
_SUFFIX_WEIGHT = 0.5
# A language is decided only when the confidence is STRICTLY above this threshold.
LANG_MIN_CONFIDENCE = 0.5


def _score_word(word, scores):
    """Add the evidence of one plain word (no apostrophe) to ``scores``."""
    if not word or word in _NEUTRAL_WORDS:
        return
    if word in _FR_WORDS:
        scores["fr"] += 1.0
    elif word in _EN_WORDS:
        scores["en"] += 1.0
    elif _FR_ACCENT_RE.search(word):
        scores["fr"] += 1.0
    elif len(word) >= _SUFFIX_MIN_LEN:
        if word.endswith(_FR_SUFFIXES):
            scores["fr"] += _SUFFIX_WEIGHT
        elif word.endswith(_EN_SUFFIXES):
            scores["en"] += _SUFFIX_WEIGHT


def _score_token(token, scores):
    """Add the evidence of one token (apostrophe forms handled) to ``scores``."""
    token = token.strip("'")
    if not token:
        return
    m = _FR_ELISION_RE.match(token)
    if m:
        scores["fr"] += 1.0
        _score_token(token[m.end():], scores)
        return
    if _EN_NEG_RE.search(token):
        scores["en"] += 1.0
        return
    m = _EN_CONTRACTION_RE.search(token)
    if m:
        scores["en"] += 1.0
        _score_word(token[:m.start()], scores)
        return
    # Any other apostrophe form: score each side as a plain word.
    for part in token.split("'"):
        _score_word(part, scores)


def detect_prompt_language_scored(message):
    """``(lang, confidence)`` of a user message: lang in ("fr", "en"), confidence 0..1.

    confidence = min(1, top) * (0.5 + 0.5 * margin / total), 0 on a tie or no
    evidence. It exceeds LANG_MIN_CONFIDENCE exactly when one language has a strict
    majority AND at least one full point of evidence (one function word, accent,
    elision or contraction), so the majority language of a mixed sentence wins.
    On a tie / no evidence the returned lang is "fr" with confidence 0.
    """
    scores = {"fr": 0.0, "en": 0.0}
    text = _APOSTROPHES_RE.sub("'", (message or "").lower())
    for token in _TOKEN_RE.findall(text):
        _score_token(token, scores)
    fr, en = scores["fr"], scores["en"]
    total = fr + en
    if total <= 0 or fr == en:
        return "fr", 0.0
    top = max(fr, en)
    confidence = min(1.0, top) * (0.5 + 0.5 * abs(fr - en) / total)
    return ("fr" if fr > en else "en"), confidence


def detect_prompt_language(message, default="fr"):
    """Reply language of a user message ("fr" / "en").

    Run on the RAW current message (no date prefix). Falls back to ``default`` (the
    web-app language when known) when the scorer is not confident: a neutral or too
    short message ("42", "ok", "revenue 2025 EMEA") or a tie.
    """
    fallback = default if default in _LANG_LABEL else "fr"
    lang, confidence = detect_prompt_language_scored(message)
    return lang if confidence > LANG_MIN_CONFIDENCE else fallback


def build_user_suffix(full_name, now_dt, webapp_lang=None, prompt_lang=None, mode=None):
    """Compact context block APPENDED to the END of the CURRENT user message.

    Placed in the highest-recency slot so even a small model honors it. Carries who
    is asking, the date, the web-app's configured language and - the load-bearing
    rule - the language of THIS message, which the agent must answer in (it always
    wins over earlier turns and over the web-app language) for the chat reply AND
    every tool argument. The control tokens ``⟦owi:mode=…⟧`` / ``⟦owi:lang=…⟧`` are
    machine-only: the agent parses then STRIPS them, so they never reach the model
    as visible text, while the human-readable language imperative stays as the
    final line of the turn. Mirrored verbatim by dev-harness/mock/live/lang.mjs.
    """
    name = full_name or "Unknown user"
    date = now_dt.strftime(_DATE_FMT)
    webapp_label = _LANG_LABEL.get(webapp_lang)
    prompt_label = _LANG_LABEL.get(prompt_lang)
    tokens = ""
    if mode in MODEL_MODES:
        tokens += "⟦owi:mode={0}⟧".format(mode)
    if prompt_lang in _LANG_LABEL:
        tokens += "⟦owi:lang={0}⟧".format(prompt_lang)
    head = "\n\n[Context - User: {name} · Today: {date}".format(name=name, date=date)
    if webapp_label:
        head += " · Web app language: {0}".format(webapp_label)
    head += "]"
    if tokens:
        head += " " + tokens          # inline so stripping leaves the bracket line clean
    parts = [head]
    if prompt_label:
        if webapp_label and webapp_label != prompt_label:
            webapp_rule = "The web-app language ({0}) is NOT the reply language.".format(webapp_label)
        else:
            webapp_rule = "The web-app language never sets the reply language."
        parts.append(
            "IMPORTANT - reply in {p}, the language of my message above: write EVERYTHING "
            "in {p}, the chat reply AND every tool argument (plan steps, widget titles, "
            "subtitles, texts, scope). {w} This rule takes priority over earlier "
            "turns.".format(p=prompt_label, w=webapp_rule))
    return "\n".join(parts)


# Upper bound on the generated-SQL block appended to a prior assistant turn (keeps
# the replayed context compact; the SQL is for grounding, not verbatim re-execution).
MAX_SQL_CONTEXT_CHARS = 4000


def _format_sql_context(generated_sql):
    """Render the stored generated_sql list into a bounded context block (or '').

    ``generated_sql`` is the decoded list of ``{sql, success, row_count}`` for a prior
    turn. Returns "" when there is nothing to add, so rows without SQL are unchanged.
    """
    if not generated_sql:
        return ""
    parts = []
    for item in generated_sql:
        sql = (item.get("sql") if isinstance(item, dict) else None) or ""
        sql = sql.strip()
        if sql:
            parts.append(sql)
    if not parts:
        return ""
    body = "\n".join(parts)[:MAX_SQL_CONTEXT_CHARS]
    return "\n\n[SQL généré pour cette réponse :\n{0}]".format(body)


def flatten_exchanges_to_messages(rows, max_messages):
    """Flatten chronological exchange rows into the last ``max_messages`` messages.

    ``rows`` are oldest->newest, each a dict with ``user_text``/``assistant_text``.
    One exchange yields up to two messages (user then assistant). Empty sides are
    skipped (e.g. a prior run that produced no answer). When an exchange carries a
    decoded ``generated_sql`` list, a bounded SQL block is appended to its assistant
    turn so the agent has the SQL it produced earlier as grounding context.
    """
    messages = []
    for row in rows:
        u = (row.get("user_text") or "").strip()
        a = (row.get("assistant_text") or "").strip()
        if u:
            messages.append({"role": "user", "content": u})
        if a:
            content = a + _format_sql_context(row.get("generated_sql"))
            messages.append({"role": "assistant", "content": content})
    n = max(0, int(max_messages))
    return messages[-n:] if n else []


def exchanges_to_fetch(max_messages):
    """How many EXCHANGES to read to cover ``max_messages`` messages (2 per exchange)."""
    return max(1, int(math.ceil(int(max_messages) / 2.0)))


# --- prior-results recall (grounded follow-ups without re-querying) -----------
# The last exchanges' captured SQL results ride along the current turn as a
# MACHINE token (⟦owi:prior=…⟧) the orchestrator parses and strips before any
# LLM call - the model only reads a short [PRIOR DATA] index and loads the rows
# on demand through its recall_prior_result tool. Everything is bounded so the
# token stays small; the source rows were already read for the history replay
# (same ancestor-chain query), so this adds ZERO database work.
MAX_PRIOR_RESULTS = 3
PRIOR_QUESTION_MAX_CHARS = 160
PRIOR_SQL_MAX_CHARS = 800
PRIOR_MAX_ROWS = 30
PRIOR_MAX_COLS = 40
PRIOR_CELL_MAX_CHARS = 128
PRIOR_TOKEN_MAX_CHARS = 24_000
PRIOR_MIN_ROWS_KEPT = 5
PRIOR_MIN_COLS_KEPT = 6


def _prior_clean(value, cap):
    """String projection for the prior-data token: the ⟦⟧ glyphs would break the
    token framing, so they are dropped from data; bounded."""
    s = str(value) if value is not None else ""
    return s.replace("⟦", "").replace("⟧", "")[:cap]


def extract_prior_results(chain_rows):
    """Up to MAX_PRIOR_RESULTS recallable results from ancestor-chain rows
    (chronological input). Output is NEWEST FIRST (turn 1 = most recent). Pure.

    An exchange contributes its ACTIVE captured result: the LAST successful
    ``generated_sql`` item carrying {columns, rows} (same rule as Evidence).
    Exchanges without a captured result are simply skipped. Duplicate results
    are collapsed onto the NEWEST copy (same sql + columns): a recall turn
    re-emits the recalled data as its own captured item, and without this
    dedup a chain of follow-ups would fill the whole window with copies of
    one dataset.
    """
    out = []
    seen = set()
    for row in reversed(chain_rows or []):
        if len(out) >= MAX_PRIOR_RESULTS:
            break
        if not isinstance(row, dict):
            continue
        items = row.get("generated_sql") or []
        active = None
        for it in reversed(items):
            if not isinstance(it, dict) or not it.get("success"):
                continue
            result = it.get("result")
            if (isinstance(result, dict) and isinstance(result.get("columns"), list)
                    and isinstance(result.get("rows"), list)):
                active = it
                break
        if active is None:
            continue
        result = active["result"]
        columns = [_prior_clean(c, PRIOR_CELL_MAX_CHARS)
                   for c in result["columns"][:PRIOR_MAX_COLS]]
        rows = [[_prior_clean(c, PRIOR_CELL_MAX_CHARS) for c in r[:PRIOR_MAX_COLS]]
                for r in result["rows"][:PRIOR_MAX_ROWS] if isinstance(r, list)]
        if not columns or not rows:
            continue
        sql_full = _prior_clean(active.get("sql"), 10 * PRIOR_SQL_MAX_CHARS)
        signature = (sql_full[:PRIOR_SQL_MAX_CHARS], tuple(columns))
        if signature in seen:
            continue
        seen.add(signature)
        row_count = active.get("row_count")
        if isinstance(row_count, bool) or not isinstance(row_count, int):
            row_count = None
        out.append({
            "question": _prior_clean(row.get("user_text"), PRIOR_QUESTION_MAX_CHARS),
            "sql": sql_full[:PRIOR_SQL_MAX_CHARS],
            "sql_truncated": len(sql_full) > PRIOR_SQL_MAX_CHARS,
            "columns": columns,
            "rows": rows,
            "row_count": row_count,
            "truncated": bool(result.get("truncated"))
            or len(rows) < len(result["rows"])
            or len(result["columns"]) > PRIOR_MAX_COLS,
        })
    return out


def build_prior_data_block(prior_results):
    """The visible [PRIOR DATA] index + the machine token, or '' when nothing is
    recallable. HARD size bound: oldest results are dropped first, then the last
    remaining result's rows are halved down to PRIOR_MIN_ROWS_KEPT, then its
    columns down to PRIOR_MIN_COLS_KEPT; a result that still exceeds the cap
    after all that is pathological and the block is dropped entirely."""
    results = [dict(r) for r in (prior_results or []) if isinstance(r, dict)]
    if not results:
        return ""
    while True:
        token = ("⟦owi:prior=" +
                 json.dumps(results, ensure_ascii=False, separators=(",", ":")) +
                 "⟧")
        if len(token) <= PRIOR_TOKEN_MAX_CHARS:
            break
        if len(results) > 1:
            results = results[:-1]          # newest-first: drop the oldest
            continue
        rows = results[0].get("rows") or []
        if len(rows) > PRIOR_MIN_ROWS_KEPT:
            results[0]["rows"] = rows[: max(PRIOR_MIN_ROWS_KEPT, len(rows) // 2)]
            results[0]["truncated"] = True
            continue
        cols = results[0].get("columns") or []
        if len(cols) > PRIOR_MIN_COLS_KEPT:
            keep = max(PRIOR_MIN_COLS_KEPT, len(cols) // 2)
            results[0]["columns"] = cols[:keep]
            results[0]["rows"] = [r[:keep] for r in results[0]["rows"]]
            results[0]["truncated"] = True
            continue
        return ""                            # nothing sane to ship
    lines = ["\n\n[PRIOR DATA - results already fetched earlier in this "
             "conversation, recallable INSTANTLY with recall_prior_result "
             "(no new query):"]
    for i, r in enumerate(results, start=1):
        cols = ", ".join(r.get("columns") or [])
        n = r.get("row_count")
        n_txt = ("%d rows" % n) if isinstance(n, int) else ("%d rows" % len(r.get("rows") or []))
        lines.append(' %d%s: "%s" -> %s (%s)' % (
            i, " (most recent)" if i == 1 else "",
            r.get("question") or "?", n_txt, cols))
    lines.append(" Prefer recall_prior_result over a specialist when these "
                 "already answer the follow-up.]")
    return "\n".join(lines) + token


# --- Studio continuity (the V2 Studio the user sees, continued or not) --------
# A short visible [CURRENT STUDIO] description of the base workspace (validated
# server side by the worker: same user, same session, not running) + a MACHINE
# token (⟦owi:studio=…⟧) carrying only the widget ids, parsed and stripped by the
# orchestrator. No row, no comment, no sql_id and NEVER the base exchange id: the
# worker keeps that id locally, so the agent can never point at another exchange.
STUDIO_BLOCK_MAX_CHARS = 1800
STUDIO_TOKEN_MAX_CHARS = 600
STUDIO_SCOPE_CHARS = 200
STUDIO_TITLE_CHARS = 80
STUDIO_MAX_WIDGETS = 12
_STUDIO_TITLE_LADDER = (STUDIO_TITLE_CHARS, 40, 20)
_STUDIO_HEADER = ("\n\n[CURRENT STUDIO - the dashboard the user sees now, built earlier "
                  "in THIS conversation from real queries]")


def _studio_clean(value, cap):
    """One-line, glyph-safe projection of an agent-written string (bounded)."""
    text = _prior_clean(value, 4 * cap)
    text = " ".join(text.replace('"', "'").split())
    return text[:cap]


def _studio_widget_phrase(widget, title_cap):
    kind = widget.get("kind") or "?"
    parts = [widget.get("id") or "?", kind]
    if kind == "chart":
        ctype = (widget.get("chart") or {}).get("type")
        if ctype:
            parts.append(str(ctype))
    if kind == "text":
        parts.append(widget.get("role") or "section")
    elif widget.get("size"):
        parts.append(str(widget["size"]))
    phrase = " ".join(parts)
    title = _studio_clean(widget.get("title"), title_cap) if title_cap else ""
    return phrase + (' "%s"' % title if title else "")


def build_studio_block(doc):
    """The visible [CURRENT STUDIO] block + the ⟦owi:studio=…⟧ token, or '' when
    the document carries no widget. Pure. HARD bound STUDIO_BLOCK_MAX_CHARS on the
    visible part: titles shrink (80 -> 40 -> 20 chars), then the widget line is
    hard-truncated. The token lists every widget id (<= STUDIO_TOKEN_MAX_CHARS)."""
    if not isinstance(doc, dict):
        return ""
    widgets = [w for w in doc.get("widgets") or []
               if isinstance(w, dict) and isinstance(w.get("id"), str)][:STUDIO_MAX_WIDGETS]
    if not widgets:
        return ""
    scope = next((w for w in widgets if w.get("kind") == "text"
                  and w.get("role") == "scope"), None)
    scope_text = _studio_clean((scope or {}).get("text"), STUDIO_SCOPE_CHARS)
    used = len(widgets)
    capacity = "Capacity: %d of %d used, %d free." % (
        used, STUDIO_MAX_WIDGETS, max(0, STUDIO_MAX_WIDGETS - used))
    head = _STUDIO_HEADER + ("\nScope: " + scope_text if scope_text else "")
    tail = "\n" + capacity
    visible = ""
    for title_cap in _STUDIO_TITLE_LADDER:
        line = "\nWidgets (board order): " + " | ".join(
            _studio_widget_phrase(w, title_cap) for w in widgets)
        visible = head + line + tail
        if len(visible) <= STUDIO_BLOCK_MAX_CHARS:
            break
    if len(visible) > STUDIO_BLOCK_MAX_CHARS:
        room = STUDIO_BLOCK_MAX_CHARS - len(head) - len(tail) - 3
        visible = head + line[:max(0, room)] + "..." + tail
    ids = [w["id"] for w in widgets]
    token = ("⟦owi:studio=" +
             json.dumps({"ids": ids, "n": len(ids)}, ensure_ascii=False,
                        separators=(",", ":")) + "⟧")
    if len(token) > STUDIO_TOKEN_MAX_CHARS:
        return ""
    return visible + token


# Screen-awareness caps (bounded so the block can never bloat the prompt).
MAX_SCREEN_ARTIFACTS = 4
MAX_SCREEN_COLS = 24
SCREEN_ANSWER_EXCERPT_CHARS = 300


def _artifact_phrase(a):
    """One short human phrase describing a rendered artifact spec, or '' if empty."""
    if not isinstance(a, dict):
        return ""
    kind = a.get("kind")
    title = (a.get("title") or "").strip()
    if kind == "chart":
        ch = a.get("chart") or {}
        desc = "a {0} chart".format(ch.get("type") or "")
        if title:
            desc += ' titled "{0}"'.format(title[:120])
        x, ys = ch.get("x"), (ch.get("y") or [])
        if x:
            desc += " (x={0}, y={1})".format(x, ",".join([str(y) for y in ys]))
        return desc
    if kind == "kpi":
        kpi = a.get("kpi") or {}
        return 'a KPI card "{0}" ({1})'.format(
            (kpi.get("label") or title or "")[:120], kpi.get("value") or "")
    if kind == "table":
        return 'a table' + (' titled "{0}"'.format(title[:120]) if title else "")
    return ""


def _screen_columns(artifacts):
    """Collect the data column names referenced by the rendered artifacts (chart
    x/y, kpi value/delta) - enough for the model to know what 'add X' can touch."""
    cols, seen = [], set()
    for a in artifacts or []:
        if not isinstance(a, dict):
            continue
        ch = a.get("chart") or {}
        kpi = a.get("kpi") or {}
        for c in ([ch.get("x")] + list(ch.get("y") or [])
                  + [kpi.get("value"), kpi.get("delta"), kpi.get("delta_pct")]):
            if c and c not in seen:
                seen.add(c)
                cols.append(str(c))
    return cols[:MAX_SCREEN_COLS]


# --- SOURCE-DATA VIEW state (filters/search/computed figures the user shaped) --
# The user can also SHAPE a raw source dataset in the app (the Source data explorer
# and the Evidence "Source data" tab): active filters, a search term, a DB row count
# and DB-computed figures (calc cards + a breakdown). The front attaches a compact
# ``source_state`` on /chat/start BY DEFAULT (opt-out chip since 2026-08-06); it is
# sanitized here (pure, never raises),
# rendered into the same [ON SCREEN NOW] block, and framed as GROUNDED (DB-computed)
# so the honesty firewall stays intact (any OTHER figure still needs a specialist).
SOURCE_STATE_SURFACES = ("explorer", "evidence")
# Aggregate functions the calc cards can carry (mirror of the backend whitelist).
SOURCE_AGG_FNS = ("count", "count_distinct", "sum", "avg", "median", "min", "max")
# The breakdown ("analyze") supports a smaller set (count/sum/avg) + a time bucket.
SOURCE_ANALYZE_FNS = ("count", "sum", "avg")
SOURCE_ANALYZE_BUCKETS = ("month", "quarter", "year")
SOURCE_FILTER_OPS = ("=", "IN", "BETWEEN")

# Caps (mirrored client-side). Everything is bounded so the block can never bloat.
SS_FILTERS = 8
SS_VALUES = 5
SS_VALUE_CHARS = 80
SS_Q_CHARS = 80
SS_DATASET_CHARS = 120
SS_AGENT_CHARS = 80
SS_COLUMN_CHARS = 64
SS_DRILL = 6
SS_CALC_MEASURES = 8
SS_MEASURE_VALUE_CHARS = 40
SS_ANALYZE_ROWS = 5
SS_ROW_COUNT_MAX = 10 ** 15
# Hard budget for the SOURCE-DATA VIEW section alone (the artifacts part is already
# bounded, so the whole [ON SCREEN NOW] block stays well under ~2000 chars).
MAX_SOURCE_STATE_CHARS = 1200

# Human labels for the aggregate functions (used in the rendered figures).
_SS_FN_LABEL = {
    "count": "Row count",
    "count_distinct": "Distinct values",
    "sum": "Sum",
    "avg": "Average",
    "median": "Median",
    "min": "Min",
    "max": "Max",
}


def _clean_ss(value, cap):
    """String projection for a source-state value: drop the ⟦⟧ token glyphs (they
    would break the machine-token framing elsewhere in the prompt), collapse the
    \\r\\n\\t control chars to a space, then bound to ``cap``. None -> ''."""
    s = str(value) if value is not None else ""
    s = s.replace("⟦", "").replace("⟧", "")
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return s[:cap]


def _ss_filters(raw):
    """Sanitized filter list (bounded, whitelisted ops), or [] when none survive."""
    out = []
    if not isinstance(raw, list):
        return out
    for f in raw[:SS_FILTERS]:
        if not isinstance(f, dict):
            continue
        col = _clean_ss(f.get("column"), SS_COLUMN_CHARS)
        op = f.get("op")
        if not col or op not in SOURCE_FILTER_OPS:
            continue
        raw_vals = f.get("values")
        if not isinstance(raw_vals, list):
            continue
        vals = [v for v in (_clean_ss(x, SS_VALUE_CHARS) for x in raw_vals[:SS_VALUES]) if v]
        if not vals:
            continue
        item = {"column": col, "op": op, "values": vals}
        more = f.get("more")
        if isinstance(more, int) and not isinstance(more, bool) and more >= 1:
            item["more"] = more
        out.append(item)
    return out


def _ss_drill(raw):
    """Sanitized drill-down list ([{column, value}], bounded), or []."""
    out = []
    if not isinstance(raw, list):
        return out
    for d in raw[:SS_DRILL]:
        if not isinstance(d, dict):
            continue
        col = _clean_ss(d.get("column"), SS_COLUMN_CHARS)
        val = _clean_ss(d.get("value"), SS_VALUE_CHARS)
        if col and val:
            out.append({"column": col, "value": val})
    return out


def _ss_calc(raw):
    """Sanitized calc block ({column, measures:[{fn, value}]}), or None."""
    if not isinstance(raw, dict):
        return None
    col = _clean_ss(raw.get("column"), SS_COLUMN_CHARS)
    raw_measures = raw.get("measures")
    if not col or not isinstance(raw_measures, list):
        return None
    measures = []
    for m in raw_measures[:SS_CALC_MEASURES]:
        if not isinstance(m, dict):
            continue
        fn = m.get("fn")
        if fn not in SOURCE_AGG_FNS:
            continue
        val = _clean_ss(m.get("value"), SS_MEASURE_VALUE_CHARS)
        if not val:
            continue
        measures.append({"fn": fn, "value": val})
    if not measures:
        return None
    return {"column": col, "measures": measures}


def _ss_analyze(raw):
    """Sanitized breakdown block ({group, bucket, fn, measure_column, rows, total,
    truncated}), or None (dropped unless it has a group, a valid fn and >=1 row)."""
    if not isinstance(raw, dict):
        return None
    group = _clean_ss(raw.get("group"), SS_COLUMN_CHARS)
    fn = raw.get("fn")
    if not group or fn not in SOURCE_ANALYZE_FNS:
        return None
    raw_rows = raw.get("rows")
    rows = []
    if isinstance(raw_rows, list):
        for r in raw_rows[:SS_ANALYZE_ROWS]:
            if not isinstance(r, dict):
                continue
            key = _clean_ss(r.get("key"), SS_VALUE_CHARS)
            val = _clean_ss(r.get("value"), SS_MEASURE_VALUE_CHARS)
            if key and val:
                rows.append({"key": key, "value": val})
    if not rows:
        return None
    bucket = raw.get("bucket")
    bucket = bucket if bucket in SOURCE_ANALYZE_BUCKETS else None
    mc = raw.get("measure_column")
    measure_column = _clean_ss(mc, SS_COLUMN_CHARS) if mc is not None else ""
    total = raw.get("total")
    total = _clean_ss(total, SS_MEASURE_VALUE_CHARS) if total is not None else ""
    return {
        "group": group,
        "bucket": bucket,
        "fn": fn,
        "measure_column": measure_column or None,
        "rows": rows,
        "total": total or None,
        "truncated": bool(raw.get("truncated")),
    }


def sanitize_source_state(raw):
    """Whitelist + bound the untrusted ``source_state`` into a clean dict, or None.

    Pure and NEVER raises (garbage types -> None). Every key is whitelisted and every
    value passes ``_clean_ss``. Returns None when ``surface``/``dataset`` are missing
    (``surface`` must be one of SOURCE_STATE_SURFACES, ``dataset`` a non-empty label)
    or when the state carries no MEANINGFUL user-shaped field: at least one of
    filters / q / drill / calc / analyze must be present (a bare row_count, or an
    agent label, is not an intent the user shaped and does not open the view).
    """
    try:
        if not isinstance(raw, dict):
            return None
        surface = raw.get("surface")
        if surface not in SOURCE_STATE_SURFACES:
            return None
        dataset = _clean_ss(raw.get("dataset"), SS_DATASET_CHARS)
        if not dataset:
            return None
        out = {"surface": surface, "dataset": dataset}

        agent = _clean_ss(raw.get("agent"), SS_AGENT_CHARS) if raw.get("agent") is not None else ""
        if agent:
            out["agent"] = agent

        # row_count: a real int only (bool is NOT an int here); coerce numeric-ish
        # inputs but never a stale/negative value, and cap the magnitude.
        rc = raw.get("row_count")
        if rc is not None and not isinstance(rc, bool):
            try:
                rc_int = int(rc)
                if rc_int >= 0:
                    out["row_count"] = min(rc_int, SS_ROW_COUNT_MAX)
            except (TypeError, ValueError):
                pass

        q = _clean_ss(raw.get("q"), SS_Q_CHARS) if raw.get("q") is not None else ""
        if q:
            out["q"] = q

        filters = _ss_filters(raw.get("filters"))
        if filters:
            out["filters"] = filters
        drill = _ss_drill(raw.get("drill"))
        if drill:
            out["drill"] = drill
        calc = _ss_calc(raw.get("calc"))
        if calc:
            out["calc"] = calc
        analyze = _ss_analyze(raw.get("analyze"))
        if analyze:
            out["analyze"] = analyze

        # A view is only meaningful when the user shaped it (row_count / agent alone
        # is not an intent). Otherwise there is nothing to describe.
        if not any(k in out for k in ("filters", "q", "drill", "calc", "analyze")):
            return None
        return out
    except Exception:
        return None


def _render_filter(f):
    """One filter phrase per the frozen template (=, IN, BETWEEN)."""
    op, col, vals = f["op"], f["column"], f["values"]
    if op == "=":
        return '%s = "%s"' % (col, vals[0])
    if op == "IN":
        quoted = ", ".join('"%s"' % v for v in vals)
        more = f.get("more")
        if more:
            quoted += ", +%d more" % more
        return "%s IN (%s)" % (col, quoted)
    if op == "BETWEEN":
        if len(vals) >= 2:
            return "%s BETWEEN %s AND %s" % (col, vals[0], vals[1])
        return "%s BETWEEN %s" % (col, vals[0])
    return ""


# Verbatim permission sentence carried BY the block itself, so the feature degrades
# gracefully when the orchestrator prompt addendum is not yet pasted in DSS.
_SS_PERMISSION = (
    "  These figures were computed by the DATABASE over the user's ENTIRE filtered "
    "view (not typed by the user). If they answer the question, quote them VERBATIM "
    "with their scope; never recompute, extend or invent a figure that is not "
    "listed - any OTHER figure still requires the specialist."
)


def _render_source_section(ss, drop_breakdown=False, collapse_filters=False,
                           collapse_drill=False):
    """Render the SOURCE-DATA VIEW section BODY (each line conditional on its data).

    The trailing ``_SS_PERMISSION`` sentence is NOT part of the body: it is appended,
    always and last, by ``_source_state_section`` so the budget degradation can never
    drop it. ``drop_breakdown`` / ``collapse_filters`` / ``collapse_drill`` are the
    budget-degradation levers used there when the section exceeds MAX_SOURCE_STATE_CHARS.
    """
    header = ' SOURCE-DATA VIEW the user shaped in the app - dataset "%s"' % ss["dataset"]
    if ss.get("agent"):
        header += ', agent "%s"' % ss["agent"]
    lines = [header + ":"]
    filters = ss.get("filters")
    if filters:
        if collapse_filters:
            parts = ["%s (%d values)" % (f["column"], len(f["values"]) + (f.get("more") or 0))
                     for f in filters]
        else:
            parts = [p for p in (_render_filter(f) for f in filters) if p]
        if parts:
            lines.append("  filters: " + "; ".join(parts) + ".")
    if ss.get("q"):
        lines.append('  search: "%s".' % ss["q"])
    drill = ss.get("drill")
    if drill:
        if collapse_drill:
            lines.append("  drill-down: %d levels." % len(drill))
        else:
            parts = ['%s = "%s"' % (d["column"], d["value"]) for d in drill]
            lines.append("  drill-down: " + ", ".join(parts) + ".")
    if "row_count" in ss:
        lines.append("  rows matching (DB count): %d." % ss["row_count"])
    calc = ss.get("calc")
    if calc:
        figures = "; ".join("%s = %s" % (_SS_FN_LABEL.get(m["fn"], m["fn"]), m["value"])
                            for m in calc["measures"])
        lines.append("  computed figures on %s over the FULL filtered set: %s."
                     % (calc["column"], figures))
    analyze = ss.get("analyze")
    if analyze and not drop_breakdown:
        fn_label = _SS_FN_LABEL.get(analyze["fn"], analyze["fn"])
        subject = analyze.get("measure_column") or "rows"
        per = (" (per %s)" % analyze["bucket"]) if analyze.get("bucket") else ""
        pairs = "; ".join("%s = %s" % (r["key"], r["value"]) for r in analyze["rows"])
        tail = " [top 5 shown; more groups exist]" if analyze.get("truncated") else ""
        lines.append("  breakdown - %s of %s by %s%s: %s%s."
                     % (fn_label, subject, analyze["group"], per, pairs, tail))
    return "\n".join(lines)


def _source_state_section(ss):
    """The rendered SOURCE-DATA VIEW section under the MAX_SOURCE_STATE_CHARS budget.

    The verbatim ``_SS_PERMISSION`` sentence (the grounding / honesty framing) is ALWAYS
    appended last, so the budget degradation can never drop it - the block stays
    self-carrying even in the overflow case (the documented skew state where the
    orchestrator prompt addendum is not yet pasted). Its length is reserved up front,
    so every rung is measured on the BODY alone. Degradation ladder on the body:
    (1) drop the breakdown line; (2) render filters as "<col> (<n> values)" without
    their values; (3) collapse the drill line to "<n> levels."; (4) hard-truncate the
    body so body + permission fits the cap, then '...'.

    Invariant: the returned section is always <= MAX_SOURCE_STATE_CHARS and always
    contains _SS_PERMISSION verbatim.
    """
    tail = "\n" + _SS_PERMISSION
    budget = MAX_SOURCE_STATE_CHARS - len(tail)  # room left for the body
    body = _render_source_section(ss)
    if len(body) <= budget:
        return body + tail
    body = _render_source_section(ss, drop_breakdown=True)
    if len(body) <= budget:
        return body + tail
    body = _render_source_section(ss, drop_breakdown=True, collapse_filters=True)
    if len(body) <= budget:
        return body + tail
    body = _render_source_section(ss, drop_breakdown=True, collapse_filters=True,
                                  collapse_drill=True)
    if len(body) <= budget:
        return body + tail
    # Hard truncate the BODY only (never the permission tail): -3 leaves room for '...'
    # so body + '...' + tail lands exactly on the cap.
    return body[: budget - 3] + "..." + tail


# Tabs the [ON SCREEN NOW] block will name ('sources' displays as "Source data").
_SCREEN_STATE_TABS = ("evidence", "chart", "table", "kpi", "sources")


def build_screen_state(artifacts, last_answer_excerpt=None, active_tab=None, source_state=None):
    """Compact, bounded description of what is CURRENTLY on the user's screen.

    The rendered artifacts (chart/table/KPI in the Evidence panel) + the data
    columns they expose + the gist of the previous answer + an optional SOURCE-DATA
    VIEW section (the filters/search/DB-computed figures the user shaped, attached
    by default with a per-view opt-out). Appended to the current turn so the agent can answer
    "explain this chart" / "why is this median X" instead of replying off-topic.
    Returns "" when nothing is on screen. The block is framed as GROUNDED prior data
    so it never trips the honesty firewall (new figures still require a specialist).
    """
    phrases = [p for p in (_artifact_phrase(a) for a in (artifacts or [])[:MAX_SCREEN_ARTIFACTS]) if p]
    cols = _screen_columns(artifacts)
    excerpt = (last_answer_excerpt or "").strip()
    ss = source_state if isinstance(source_state, dict) else None
    if not phrases and not cols and not excerpt and not ss:
        return ""
    out = ["\n\n[ON SCREEN NOW - what the user can see in the app right now:"]
    if phrases:
        out.append(" Displayed in the Evidence panel: " + "; ".join(phrases) + ".")
    if active_tab in _SCREEN_STATE_TABS:
        tab_label = "Source data" if active_tab == "sources" else active_tab
        out.append(" The user is looking at the '{0}' tab.".format(tab_label))
    if cols:
        out.append(" Underlying data columns: " + ", ".join(cols) + ".")
    if ss:
        out.append("\n" + _source_state_section(ss))
    if excerpt:
        out.append(' Your previous reply began: "{0}".'.format(excerpt[:SCREEN_ANSWER_EXCERPT_CHARS]))
    out.append(" If the user says 'this', 'the chart', 'it', or asks to explain or "
               "change what's shown, they mean THIS. You may explain it directly; for "
               "any NEW figure, still call the specialist.]")
    return "".join(out)


def build_completion_messages(history_messages, current_message, user_suffix):
    """Ordered replay list: prior turns verbatim + current user turn.

    ``user_suffix`` is APPENDED to the current message (end-of-prompt context block
    from ``build_user_suffix``) so the name/date/language directive sits in the
    highest-recency slot. Empty suffix -> the bare message.
    """
    out = list(history_messages or [])
    out.append({"role": "user", "content": current_message + (user_suffix or "")})
    return out
