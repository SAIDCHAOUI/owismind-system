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

import re

FENCE_TAG = "untrusted_data"
MAX_CELL_CHARS = 200

# Invisible / bidirectional-control characters (used to hide instructions).
_INVISIBLE_RE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_CONTROL_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FENCE_SPOOF_RE = re.compile(r"</?\s*%s" % FENCE_TAG, re.I)

_HIGH = [
    ("override_order",
     r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|your|the)\b"
     r"[^.\n]{0,30}\b(instruction|rule|prompt|guideline|constraint|context|polic)",
     "Order to ignore or override the existing instructions"),
    ("override_order_fr",
     r"\b(ignore[rz]?|oublie[rz]?|contourne[rz]?)\b[^.\n]{0,40}\b(instruction|r[eè]gle|consigne|prompt|contrainte)",
     "Order to ignore or override the existing rules (French)"),
    ("role_change",
     r"\b(you are now|from now on,? you|your new (role|instructions?|task)|new instructions?\s*:)",
     "Attempt to change the agent's role or instructions"),
    ("role_change_fr",
     r"\b(tu es maintenant|vous [eê]tes maintenant|d[eè]sormais,? (tu|vous)|nouvelles? (instructions?|consignes?)\s*:)",
     "Attempt to change the agent's role or instructions (French)"),
    ("prompt_exfiltration",
     r"\b(reveal|print|show|repeat|leak|output|display|dump|disclose|affiche[rz]?|r[eé]v[eè]le[rz]?)\b[^.\n]{0,40}"
     r"\b(system prompt|hidden (prompt|instruction)|initial (prompt|instruction)|your (instructions|prompt)|"
     r"prompt syst[eè]me|tes instructions)",
     "Ask to reveal the system prompt or hidden instructions"),
    ("jailbreak",
     r"\b(jailbreak|DAN mode|developer mode|do anything now)\b",
     "Known jailbreak wording"),
    ("template_spoof",
     r"(<\|(im_start|im_end|system|assistant|user)\|>|\[/?INST\]|<</?SYS>>|^\s*#{2,}\s*(system|assistant)\b)",
     "Chat-template or role marker spoofing"),
    ("fence_spoof",
     r"</?\s*%s" % FENCE_TAG,
     "Tries to close or forge the untrusted-data fence"),
    ("destructive_sql",
     r"\b(drop|truncate|alter)\s+(table|database|schema)\b|\b(delete\s+from|insert\s+into|update\s+\w+\s+set)\b",
     "Write / destructive SQL in a read-only context"),
    ("data_leak_link",
     r"!\[[^\]]*\]\(\s*https?://",
     "Markdown image with an external URL (can leak data)"),
    ("exfiltrate_to_url",
     r"\b(send|post|upload|forward|exfiltrate|envoie[rz]?)\b[^.\n]{0,60}\bhttps?://",
     "Asks to send data to an external URL"),
]

_MEDIUM = [
    ("concealment",
     r"\b(do not|don't|never)\b[^.\n]{0,25}\b(tell|mention|reveal|show|inform)\b[^.\n]{0,25}\b(the )?(user|human|operator)\b|"
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


def defang(text, max_chars=None):
    """Clean untrusted text before it reaches a model (never the other way)."""
    text = _INVISIBLE_RE.sub("", str(text if text is not None else ""))
    text = _CONTROL_RE.sub(" ", text)
    text = _FENCE_SPOOF_RE.sub("<fence-removed", text)
    if max_chars is not None and len(text) > max_chars:
        text = text[:max_chars]
    return text


def fence(name, body):
    """Wrap untrusted text as data. ``body`` is defanged here, always."""
    return '<%s name="%s">\n%s\n</%s>' % (FENCE_TAG, name, defang(body), FENCE_TAG)


def scan(text, max_findings=20):
    """Findings for ``text``: [{severity, rule, why, line, excerpt}] (empty = clean)."""
    text = str(text if text is not None else "")
    findings = []
    if _INVISIBLE_RE.search(text):
        findings.append({"severity": "high", "rule": "invisible_chars", "line": 0,
                         "why": "Invisible or bidirectional-control characters (can hide instructions)",
                         "excerpt": ""})
    for sev, name, rx, why in _COMPILED:
        for match in rx.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            findings.append({"severity": sev, "rule": name, "why": why, "line": line,
                             "excerpt": match.group(0).strip()[:120]})
            if len(findings) >= max_findings:
                return findings
    return findings


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
    for key in ("entity_description", "instructions", "planner_description"):
        texts.append(config.get(key))
    for att in config.get("attributes") or []:
        texts.append(att.get("description")) if isinstance(att, dict) else None
    for key in ("metrics", "filters"):
        for item in config.get(key) or []:
            if isinstance(item, dict):
                texts += [item.get("description"), item.get("pseudo_sql"), item.get("llm_instructions")]
    for item in config.get("glossary") or []:
        if isinstance(item, dict):
            texts += [item.get("term")] + list(item.get("synonyms") or [])
    for item in config.get("golden_queries") or []:
        if isinstance(item, dict):
            texts += [item.get("question")]
    return scan("\n".join(str(t) for t in texts if t))
