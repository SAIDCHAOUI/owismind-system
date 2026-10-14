"""guardrails: prompt-injection defences shared by every AI flow of the factory.

The factory feeds dataset-derived text (sample rows, column descriptions, profile
values) to an LLM, and the LLM's output ends up in places that steer agents (a
business prompt, semantic-model instructions, routing text). That text is
UNTRUSTED. Three layers, all here, all pure (stdlib only, unit-tested):

1. INPUT  - :func:`defang` cleans untrusted text BEFORE the model sees it
   (invisible / control characters, fake fence tags, cell length) and
   :func:`fence` wraps it as data.
2. OUTPUT - :func:`scan` looks for injection-shaped content in anything an AI
   wrote or a human is about to save: override orders, prompt-exfiltration asks,
   role / chat-template spoofing, concealment orders, destructive SQL, links and
   images that can leak data, secrets, invisible characters. Findings carry a
   severity ("high" or "medium") and a readable excerpt.
3. GATES  - the callers decide: high findings stop automatic writes, default a
   review change to "ignored", and make the console demand an explicit
   acknowledgement before a flagged prompt is saved.

Heuristics catch the common shapes, not every attack. They are a net under the
real control, which is a human reading the text (the console shows every prompt
in full and highlights the findings).
"""

import html
import re
import unicodedata

FENCE_TAG = "untrusted_data"
MAX_CELL_CHARS = 200

# Invisible / bidirectional-control characters (used to hide instructions).
_INVISIBLE_RE = re.compile("[\u00ad\u034f\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")
_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FENCE_SPOOF_RE = re.compile(r"</?\s*%s" % FENCE_TAG, re.I)

_HIGH = [
    ("override_order",
     r"\b(ignore|disregard|forget|override|bypass)\b.{0,200}\b(previous|prior|above|earlier|all|any|your|the)\b"
     r".{0,120}\b(instruction|rule|prompt|guideline|constraint|context|polic)",
     "Order to ignore or override the existing instructions"),
    ("override_order_fr",
     r"\b(ignore[rz]?|oublie[rz]?|contourne[rz]?)\b.{0,80}\b(instruction|r[eè]gle|consigne|prompt|contrainte)",
     "Order to ignore or override the existing rules (French)"),
    ("role_change",
     r"\b(you are now|from now on,? you|your new (role|instructions?|task)|new instructions?\s*:)",
     "Attempt to change the agent's role or instructions"),
    ("role_change_fr",
     r"\b(tu es maintenant|vous [eê]tes maintenant|d[eè]sormais,? (tu|vous)|nouvelles? (instructions?|consignes?)\s*:)",
     "Attempt to change the agent's role or instructions (French)"),
    ("prompt_exfiltration",
     r"\b(reveal|print|show|repeat|leak|output|display|dump|disclose|affiche[rz]?|r[eé]v[eè]le[rz]?)\b.{0,80}"
     r"\b(system prompt|hidden (prompt|instruction)|initial (prompt|instruction)|your (instructions|prompt)|"
     r"prompt syst[eè]me|tes instructions)",
     "Ask to reveal the system prompt or hidden instructions"),
    ("persona_swap",
     r"\b(act as|pretend (to be|you are)|behave as|play the role of|roleplay as|simulate being)\b",
     "Asks the model to play another role"),
    ("persona_swap_fr",
     r"\b(tu dois (maintenant|d[eé]sormais)|[aà] partir de maintenant|fais (comme si|semblant)|agis comme|comporte[- ]toi comme)\b",
     "Asks the model to change behaviour (French)"),
    ("prompt_copy",
     r"\b(repeat|recopie[rz]?|copy|translate|summari[sz]e|traduis|r[eé]sume[rz]?|restate|paraphrase)\b.{0,60}"
     r"\b(your|the) (system |initial |hidden )?(instructions|prompt)\b|"
     r"\b(tes|vos|ton|votre) (instructions|prompt)\b",
     "Asks to copy, translate or summarize the instructions"),
    ("jailbreak",
     r"\b(jailbreak|DAN mode|developer mode|do anything now)\b",
     "Known jailbreak wording"),
    ("template_spoof",
     r"(<\|(im_start|im_end|system|assistant|user)\|>|\[/?INST\]|<</?SYS>>|(^|\s)#{2,}\s*(system|assistant)\b)",
     "Chat-template or role marker spoofing"),
    ("fence_spoof",
     r"</?\s*%s" % FENCE_TAG,
     "Tries to close or forge the untrusted-data fence"),
    ("destructive_sql",
     r"\b(drop|alter)\s+(table|database|schema)\b|\btruncate\b\s+\w+|\bgrant\s+\w+.{0,40}\bto\b|\b(delete\s+from|insert\s+into|update\s+\w+\s+set)\b",
     "Write / destructive SQL in a read-only context"),
    ("data_leak_link",
     r"!\[[^\]]*\]\(\s*(https?://|data:)|<\s*(img|iframe|script|object|embed)\b",
     "Markdown image with an external URL (can leak data)"),
    ("exfiltrate_to_url",
     r"\b(send|post|upload|forward|exfiltrate|envoie[rz]?)\b.{0,100}\bhttps?://",
     "Asks to send data to an external URL"),
]

_MEDIUM = [
    ("concealment",
     r"\b(do not|don't|never)\b.{0,60}\b(tell|mention|reveal|show|inform)\b.{0,60}\b(the )?(user|human|operator)\b|"
     r"\b(secretly|without telling|hide this|ne (le )?dis jamais|sans (le )?dire)\b",
     "Order to hide something from the user"),
    ("external_link",
     r"https?://[^\s)>\"']+",
     "External link"),
    ("secret_like",
     r"\b(api[_-]?key|secret|password|passwd|bearer|token)\s*[:=]\s*\S{6,}",
     "Secret-looking value"),
    ("encoded_blob",
     r"[A-Za-z0-9+/]{80,}={0,2}",
     "Long encoded blob (may hide instructions)"),
]

_COMPILED = [(sev, name, re.compile(pat, re.I | re.M), why)
             for sev, group in (("high", _HIGH), ("medium", _MEDIUM))
             for name, pat, why in group]


# Lookalike letters (Cyrillic / Greek) folded to Latin so "Ign\u043ere" cannot dodge a rule.
_HOMOGLYPHS = {ord(k): v for k, v in {
    "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0445": "x",
    "\u0443": "y", "\u0456": "i", "\u0458": "j", "\u04bb": "h", "\u0455": "s", "\u0501": "d",
    "\u03b1": "a", "\u03bf": "o", "\u03b5": "e", "\u03b9": "i", "\u03ba": "k", "\u03bd": "v",
    "\u03c1": "p", "\u03c4": "t", "\u03c5": "u", "\u0391": "A", "\u0392": "B", "\u0395": "E",
    "\u0397": "H", "\u0399": "I", "\u039a": "K", "\u039c": "M", "\u039d": "N", "\u039f": "O",
    "\u03a1": "P", "\u03a4": "T", "\u03a7": "X", "\u0410": "A", "\u0412": "B", "\u0415": "E",
    "\u041a": "K", "\u041c": "M", "\u041d": "H", "\u041e": "O", "\u0420": "P", "\u0421": "C",
    "\u0422": "T", "\u0425": "X",
}.items()}
_SPELLED_RE = re.compile(r"\b(?:[A-Za-z][.\-_*|/ ]){3,}[A-Za-z]\b")


def normalize(text):
    """Canonical form used for matching: entities decoded, NFKC (fullwidth etc.),
    invisible characters dropped, homoglyphs folded, spelled-out words rejoined
    ("i.g.n.o.r.e"), all whitespace collapsed to one space."""
    text = str(text if text is not None else "")
    for _ in range(2):
        text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE_RE.sub("", text).translate(_HOMOGLYPHS)
    text = re.sub(r"(?<=\w)[\u00a0\u2000-\u200a\u202f\u205f\u3000]+(?=\w)", "", text)  # no-break space inside a word
    text = re.sub(r"(?<=\w)<[^>\s]{1,12}>(?=\w)", "", text)  # tag splitting a word: ig<b>nore
    text = _SPELLED_RE.sub(lambda m: re.sub(r"[.\-_*|/ ]", "", m.group(0)), text)
    return re.sub(r"\s+", " ", text).strip()


def defang(text, max_chars=None):
    """Clean untrusted text before it reaches a model (never the other way)."""
    text = unicodedata.normalize("NFKC", str(text if text is not None else ""))
    text = _INVISIBLE_RE.sub("", text)
    text = _CONTROL_RE.sub(" ", text)
    text = _FENCE_SPOOF_RE.sub("<fence-removed", text)
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars]
    return text


def fence(name, body):
    """Wrap untrusted text as data. ``body`` is defanged here, always."""
    return '<%s name="%s">\n%s\n</%s>' % (FENCE_TAG, name, defang(body), FENCE_TAG)


def _scan(text, max_findings=20):
    """Findings for ``text``: [{severity, rule, why, line, excerpt}] (empty = clean).

    Two passes: the RAW text (exact line numbers) then the NORMALIZED text, which
    catches what normalization reveals (multi-line, fullwidth, lookalike letters,
    HTML entities, spelled-out words). A rule already found raw is not repeated.
    """
    text = str(text if text is not None else "")
    findings = []
    if _INVISIBLE_RE.search(text):
        findings.append({"severity": "high", "rule": "invisible_chars", "line": 0,
                         "why": "Invisible or bidirectional-control characters (can hide instructions)",
                         "excerpt": ""})
    seen = set()
    for source, line_known in ((text, True), (normalize(text), False)):
        for sev, name, rx, why in _COMPILED:
            if name in seen and not line_known:
                continue
            for match in rx.finditer(source):
                line = (source.count("\n", 0, match.start()) + 1) if line_known else 0
                findings.append({"severity": sev, "rule": name, "why": why, "line": line,
                                 "excerpt": match.group(0).strip()[:120]})
                seen.add(name)
                if len(findings) >= max_findings * 5 and sev != "high":
                    break  # only MEDIUM volume is capped: every HIGH rule always runs on both passes
    return findings


def scan(text, max_findings=20):
    """Public entry. Highs are listed first and never truncated away by volume;
    any scanner failure is FAIL-CLOSED (reported as a high finding, never as clean)."""
    try:
        findings = _scan(text, max_findings)
    except Exception:
        return [{"severity": "high", "rule": "scanner_error", "line": 0, "excerpt": "",
                 "why": "The safety scan failed: treat this text as suspicious"}]
    findings.sort(key=lambda f: 0 if f["severity"] == "high" else 1)
    return findings[:max_findings]


def has_high(findings):
    return any(f.get("severity") == "high" for f in findings or [])


def summarize(findings, limit=3):
    """One readable line for logs / stage messages."""
    parts = ["%s (line %s): %s" % (f["why"], f["line"], f["excerpt"] or "-")
             for f in (findings or [])[:limit]]
    return "; ".join(parts)


def scan_config(config):
    """Scan every free-text field of a semantic-model config / proposal."""
    texts = []
    config = config if isinstance(config, dict) else {}
    for key in ("entity_name", "entity_description", "instructions", "planner_description",
                "tool_name", "label_en", "label_fr", "domain"):
        texts.append(config.get(key))
    for att in config.get("attributes") or []:
        if isinstance(att, dict):
            texts += [att.get("description"), att.get("name"), att.get("column")]
    for key in ("metrics", "filters"):
        for item in config.get(key) or []:
            if isinstance(item, dict):
                texts += [item.get("name"), item.get("description"), item.get("pseudo_sql"),
                          item.get("llm_instructions")]
    for item in config.get("glossary") or []:
        if isinstance(item, dict):
            texts += [item.get("term")] + list(item.get("synonyms") or [])
    for item in config.get("golden_queries") or []:
        if isinstance(item, dict):
            texts += [item.get("question"), item.get("sql")]
    for item in config.get("profile_overrides") or []:
        if isinstance(item, dict):
            texts += [item.get("key"), item.get("field"), item.get("value")]
    for item in config.get("questions") or config.get("clarifying_questions") or []:
        if isinstance(item, dict):
            texts += [item.get("id"), item.get("question"), item.get("why"), item.get("default"),
                      item.get("answer")]
    return scan("\n".join(str(t) for t in texts if t))
