# =============================================================================
# OWIsMind — ORCHESTRATEUR v2.3 "Le Cerveau" (Code Agent Dataiku)
# -----------------------------------------------------------------------------
# Architecture : PLAN -> EXECUTE -> SYNTHESIZE
#
#   1. PLAN       1 appel LLM (petit modèle, JSON strict) -> plan structuré :
#                 intent + liste d'étapes (sous-agents et/ou tools directs).
#   2. EXECUTE    Le CODE exécute le plan, étape par étape, déterministe :
#                 - sous-agent : streaming live, events relayés, trace fusionnée
#                 - tool       : fonction Python, span tracé
#                 Le LLM ne décide plus rien pendant l'exécution.
#   3. SYNTHESIZE - 1 seule étape agent  -> réponse relayée verbatim (0 coût)
#                 - sinon                -> petit LLM rédige la réponse finale
#                                           en streaming, à partir des résultats.
#
# Règles non négociables (cornerstones OWIsMind) :
#   - L'orchestrateur ne répond JAMAIS lui-même à une question métier.
#   - Refuse plutôt qu'halluciner : plan invalide -> clarification.
#   - Toute trace LLM/agent est fusionnée (append_trace) : coût complet du tour.
#   - Le LLM n'écrit JAMAIS d'URL de source ni de capacité non listée.
#
# v2.1 : persona unique partagé (planner + synthèse + capabilities),
#        CAPABILITIES rédigées par le LLM mais ANCRÉES sur le registre.
#
# v2.2 (Evidence trust layer — audit ORCH-01..11, details in orchestrator/AUDIT.md):
#   - generated_sql items tagged sql_id/step_index/agent_key + opportunistic,
#     locally capped result capture from the SQL tool span outputs (ORCH-02).
#   - ERROR eventData.message = stable machine codes only; the raw str(e) stays
#     in span attributes + logs (ORCH-03). agentId removed from CALLING_AGENT
#     eventData — it stays in the step span attributes (ORCH-04).
#   - Sources block = business dataset labels from the registry; intranet URLs
#     never reach the answer text (ORCH-05). Depth guard on both trace walkers
#     (ORCH-06). Shared _is_footer() detection: type == "footer" OR SDK class,
#     guarded import (ORCH-07).
#   - Synthesis: step outputs cut at STEP_RESULT_MAX_CHARS are explicitly
#     flagged as truncated to the writer model (ORCH-09).
#   - Plan: steps purged when intent != BUSINESS (ORCH-10b); PLAN_READY stops
#     echoing full instructions — 120-char summaries (ORCH-10c); greet flushed
#     unconditionally before the steps loop (ORCH-10d).
#   - Registry: dataset_label_fr/en + dataset_ref per agent capability (ORCH-11).
#
# v2.3 (SalesDrive v2 collaboration contract):
#   - CAPABILITIES gains "salesdrive_v2": the Code Agent port of the visual
#     SalesDrive agent (repo: salesdrive/salesdrive_agent.py). Disabled until
#     the DSS Code Agent exists; switching = flip the two "enabled" flags
#     (one revenue capability visible to the planner at a time).
#   - Structured sub-agent status: a code sub-agent may emit ONE final
#     AGENT_RESULT event {status, language, intent, resolvedFilters, sqlCount,
#     rowCount}. It is captured (never relayed to the timeline), exposed in
#     the step result and in AGENT_DONE eventData ("agentResult"), and the
#     sources block is skipped when status is need_clarification /
#     out_of_scope (a question or a refusal cites no dataset). Visual agents
#     that never emit it are unaffected (agent_result stays None).
#
# v2.4 (Expert Authority — foundation): the orchestrator NEVER authors a business
#   fact. Routing is the default; the only "no" it may write is "no agent for this
#   domain" (CAPABILITY_GAP, deterministic template) — never "the data does not
#   exist". OUT_OF_SCOPE is templated too; CONCEPT answers general notions with no
#   OWI figure. Registry is a manifest: add an agent = one entry {key, agent_id,
#   label, description, domain}. BUSINESS_DOMAINS tells a real-but-unstaffed domain
#   (honest gap) from non-OWI (out of scope). Anti-drift test keeps the revenue
#   manifest truthful vs the sub-agent's KNOWN_PHASES. Spec:
#   docs/superpowers/specs/2026-06-11-orchestrator-expert-authority-design.md
#
# EVENT KIND CONTRACT (FROZEN as of v2.2) — the webapp timeline keys its logic
# on these machine identifiers. They are NEVER renamed; new kinds may only be
# ADDED to this list:
#   START, PLANNING, PLAN_READY, DIRECT_ANSWER, CALLING_AGENT, AGENT_DONE,
#   RUNNING_TOOL, TOOL_DONE, WRITING_ANSWER, DONE, ERROR, SUB_AGENT_*
#
# Scaling : ajouter un sous-agent ou un tool = 1 entrée dans CAPABILITIES.
# =============================================================================

import json
import logging
import math
import re
import time
from datetime import date, datetime

import dataiku
from dataiku.llm.python import BaseLLM

# ORCH-07: the footer chunk may be recognised by class when the SDK exposes it.
# Guarded import: older/newer SDK builds differ, and the Code Agent must still
# load when the symbol is absent (fallback = payload type sniffing).
try:
    from dataikuapi.dss.llm import DSSLLMStreamedCompletionFooter
except Exception:  # SDK shape differs / symbol absent
    DSSLLMStreamedCompletionFooter = None

logger = logging.getLogger("owismind.orchestrator")

# =============================================================================
# 1. CONFIGURATION
# =============================================================================

PLANNER_LLM_ID = "openai:LLM-7064-revforecast:vertex_ai/gemini-2.5-pro"
SYNTH_LLM_ID = None                # None -> réutilise PLANNER_LLM_ID (option : modèle moins cher ici)

MAX_STEPS = 4                      # garde-fou : étapes max par plan
HISTORY_MAX_MESSAGES = 8           # historique max passé au planificateur
HISTORY_MAX_CHARS = 1000           # troncature par message d'historique
STEP_RESULT_MAX_CHARS = 4000       # troncature des résultats injectés en synthèse
ANNOUNCE_IN_CONTENT = True         # annonce "J'interroge..." dans le texte (mode mono-étape)

# ORCH-09: appended to any step output cut at STEP_RESULT_MAX_CHARS before
# synthesis, so the writer model flags potentially incomplete data instead of
# presenting a silently truncated result as complete (honesty rule).
STEP_RESULT_TRUNCATED_SUFFIX = ("…[RESULT TRUNCATED — state explicitly that the "
                                "data above may be incomplete]")

# --- v2.2: bounded trace walking + opportunistic result capture ---------------
# These caps are intentionally LOCAL to this file: the Code Agent is pasted into
# DSS standalone and must not depend on the plugin. The webapp re-caps captured
# results independently (evidence/capture.py) before persistence; the mirrors
# below only bound what travels inside AGENT_DONE eventData / the merged trace.
_MAX_TRACE_DEPTH = 200             # ORCH-06: depth guard for both trace walkers
MAX_RESULT_ROWS = 50               # rows kept per captured result (orchestrator-side)
MAX_RESULT_COLS = 50               # columns kept per captured result
_RESULT_CELL_MAX_CHARS = 256       # non-primitive cells -> str()[:256]
_RESULT_JSON_MAX_CHARS = 64000     # serialized result budget; beyond -> drop rows

# ORCH-03: ERROR eventData.message carries one of these STABLE machine codes
# only — never str(e), which stays in span attributes ('error') and logs.
ERROR_CODE_NO_USER_MESSAGE = "no_user_message"
ERROR_CODE_AGENT_STEP_FAILED = "agent_step_failed"
ERROR_CODE_SYNTHESIS_FAILED = "synthesis_failed"
ERROR_CODE_INTERNAL = "internal_error"

# =============================================================================
# 2. TOOLS DIRECTS (fonctions Python)
# -----------------------------------------------------------------------------
# Contrat : run(args: dict) -> dict JSON-sérialisable.
# Pour brancher un Dataiku Agent Tool (ex: Send Message) plus tard :
#   tool = dataiku.api_client().get_default_project().get_agent_tool("TOOL_ID")
#   return tool.run(args)
# =============================================================================

def tool_current_date(args):
    """Tool de démonstration : date du jour (valide le chemin 'tool' de bout en bout)."""
    today = date.today()
    return {"iso_date": today.isoformat(), "year": today.year, "month": today.month}


# =============================================================================
# 3. REGISTRE UNIFIÉ DES CAPACITÉS (sous-agents + tools)
# -----------------------------------------------------------------------------
# Même schéma logique que OWI_AgentRegistry. Bascule dataset en v3 :
# remplacer le corps de get_capabilities() par une lecture du dataset.
# =============================================================================

CAPABILITIES = {
    "salesdrive": {
        "kind": "agent",
        "agent_id": "agent:rNTZ781a",
        "domain": "revenue",
        "label_fr": "SalesDrive (revenus)",
        "label_en": "SalesDrive (revenue)",
        "planner_description": (
            "Revenue and billing on OWI customers across ALL scenarios/phases — "
            "actuals, budget, forecast, Q3F, HLF — broken down by customer, "
            "product, solution, solution line, sirano product, partner, "
            "distribution type, sales entity, sales zone, parent group, month or "
            "year; totals, top-N rankings, period comparisons, actuals-vs-budget "
            "deltas and variance, trends and YTD. Handles multi-period and "
            "multi-phase comparisons WITHIN ONE single step. Data source: "
            "DRIVE_Revenues. You do NOT pre-judge what this data contains — route "
            "the question; only this agent can confirm or deny a specific figure."
        ),
        # ORCH-05: intranet URLs are SERVER-ONLY (kept for ops/debug, never put in
        # answer text). The user-facing sources section uses the business labels.
        "dataset_sources": [
            "https://dataiku-datalab-owi.authidh.itn.intraorange/workspaces/OWISMIND/OWISMIND/DATASET/DRIVE_Revenues",
        ],
        # ORCH-11: business-friendly dataset labels (what the sources section shows)
        # + machine reference for downstream consumers (Evidence Studio).
        "dataset_label_fr": "Base des revenus clients OWI (DRIVE_Revenues)",
        "dataset_label_en": "OWI customer revenue base (DRIVE_Revenues)",
        "dataset_ref": {"project_key": "OWISMIND", "dataset_name": "DRIVE_Revenues"},
        # Libellés humains des étapes internes ; None = bloc technique masqué de la timeline.
        "block_labels": {
            "resolve":                {"fr": "analyse de la question et identification des filtres",
                                       "en": "analyzing the question and resolving filters"},
            "query_revenue_semantic": {"fr": "interrogation de la base de revenus",
                                       "en": "querying the revenue database"},
            "format_tool_output":     {"fr": "mise en forme des résultats",
                                       "en": "formatting the results"},
            "clarify_user":           {"fr": "demande de précision",
                                       "en": "asking for clarification"},
            "out_of_scope_msg":       {"fr": "question hors périmètre",
                                       "en": "out-of-scope notice"},
            "save_resolve_plan": None,
            "routing": None,
            "save_answer_payload": None,
            "render_answer": None,
            "internal_error_msg": None,
        },
        "tool_labels": {
            "Drive_Revenues_resolve_filter_value": {"fr": "résolution des noms (clients, produits…)",
                                                    "en": "resolving names (customers, products…)"},
            "revenue_semantic_query":              {"fr": "génération et exécution de la requête SQL",
                                                    "en": "generating and running the SQL query"},
        },
        "enabled": False,    # v2.4: superseded by the code agent (salesdrive_v2) below
    },
    # v2.3 — Code Agent port of SalesDrive (repo: salesdrive/salesdrive_agent.py).
    # To switch: create the DSS Code Agent, paste the file, put its agent id
    # below, then set THIS entry enabled=True and "salesdrive" enabled=False
    # (one revenue capability at a time — the planner must see a single one).
    "salesdrive_v2": {
        "kind": "agent",
        "agent_id": "agent:MODpGFcC",
        "domain": "revenue",
        "label_fr": "SalesDrive (revenus)",
        "label_en": "SalesDrive (revenue)",
        "planner_description": (
            "Revenue and billing on OWI customers across ALL scenarios/phases — "
            "actuals, budget, forecast, Q3F, HLF — broken down by customer, "
            "product, solution, solution line, sirano product, partner, "
            "distribution type, sales entity, sales zone, parent group, month or "
            "year; totals, top-N rankings, period comparisons, actuals-vs-budget "
            "deltas and variance, trends and YTD. Handles multi-period and "
            "multi-phase comparisons WITHIN ONE single step. Data source: "
            "DRIVE_Revenues. You do NOT pre-judge what this data contains — route "
            "the question; only this agent can confirm or deny a specific figure."
        ),
        "dataset_sources": [
            "https://dataiku-datalab-owi.authidh.itn.intraorange/workspaces/OWISMIND/OWISMIND/DATASET/DRIVE_Revenues",
        ],
        "dataset_label_fr": "Base des revenus clients OWI (DRIVE_Revenues)",
        "dataset_label_en": "OWI customer revenue base (DRIVE_Revenues)",
        "dataset_ref": {"project_key": "OWISMIND", "dataset_name": "DRIVE_Revenues"},
        # The code agent only emits these five blockIds (no hidden technical
        # blocks): same ids as the visual flow, labels reused verbatim.
        "block_labels": {
            "resolve":                {"fr": "analyse de la question et identification des filtres",
                                       "en": "analyzing the question and resolving filters"},
            "query_revenue_semantic": {"fr": "interrogation de la base de revenus",
                                       "en": "querying the revenue database"},
            "format_tool_output":     {"fr": "mise en forme des résultats",
                                       "en": "formatting the results"},
            "clarify_user":           {"fr": "demande de précision",
                                       "en": "asking for clarification"},
            "out_of_scope_msg":       {"fr": "question hors périmètre",
                                       "en": "out-of-scope notice"},
        },
        "tool_labels": {
            "Drive_Revenues_resolve_filter_value": {"fr": "résolution des noms (clients, produits…)",
                                                    "en": "resolving names (customers, products…)"},
            "revenue_semantic_query":              {"fr": "génération et exécution de la requête SQL",
                                                    "en": "generating and running the SQL query"},
        },
        # v2.3: receive the previous assistant message + raw user answer as a
        # system message (conversation continuity for disambiguation answers).
        "pass_context": True,
        "enabled": True,     # v2.4: live revenue expert (agent:MODpGFcC)
    },
    "current_date": {
        "kind": "tool",
        "run": tool_current_date,
        "label_fr": "Date du jour",
        "label_en": "Current date",
        "planner_description": "Returns today's date (ISO), year and month. No arguments needed.",
        "enabled": True,
    },
    # Futurs : "tickets": {...}, "cx": {...}, "send_email": {...}, "web_search": {...}
}


def get_capabilities():
    """Point d'extension unique. v3 : lire OWI_AgentRegistry ici."""
    return {k: v for k, v in CAPABILITIES.items() if v.get("enabled")}


# Business domains the product knows about, with display labels. A domain is
# "staffed" when at least one ENABLED agent capability declares it via "domain".
# The planner uses this map to tell apart a real-but-unstaffed domain
# (-> CAPABILITY_GAP, honest) from a clearly non-OWI question (-> OUT_OF_SCOPE).
# Adding an agent later = give its registry entry the matching "domain"; the gap
# closes with NO prompt change. Names only — never a business value (rule P3).
BUSINESS_DOMAINS = {
    "revenue":       {"fr": "revenus / CA / budget / forecast",   "en": "revenue / billing / budget / forecast"},
    "tickets":       {"fr": "tickets d'incidents",                "en": "incident tickets"},
    "satisfaction":  {"fr": "satisfaction / expérience client",   "en": "customer satisfaction / experience"},
    "opportunities": {"fr": "opportunités / pipeline",            "en": "opportunities / pipeline"},
    "delivery":      {"fr": "livraison (LD / SOF / déconnexions)", "en": "delivery (LD / SOF / disconnections)"},
    "billing":       {"fr": "facturation",                        "en": "billing"},
}


def staffed_domains(caps):
    """Set of business domains covered by at least one enabled agent capability."""
    return {v["domain"] for v in caps.values()
            if v.get("kind") == "agent" and v.get("domain")}


# =============================================================================
# 4. PROTOCOLE D'ÉVÉNEMENTS + LIBELLÉS HUMAINS
# -----------------------------------------------------------------------------
# eventKind = identifiant machine STABLE (la webapp s'en sert pour la logique,
# ex: generatedSql dans AGENT_DONE). Le libellé humain prêt à afficher est
# injecté au runtime dans eventData["label"], dans la langue de l'utilisateur.
# -> Côté webapp : afficher eventData.label, c'est tout.
# Les événements internes des sous-agents sont traduits via block_labels /
# tool_labels du registre ; les blocs techniques (None) sont masqués.
# =============================================================================

STEP_LABELS = {
    "START":           {"fr": "🧠 Prise en charge de votre question",
                             "en": "🧠 Taking care of your question"},
    "PLANNING":        {"fr": "Analyse de votre question et choix de la stratégie…",
                             "en": "Analyzing your question and choosing a strategy…"},
    "PLAN_READY":      {"fr": "Stratégie choisie",
                             "en": "Strategy selected"},
    "DIRECT_ANSWER":   {"fr": "Réponse directe",
                             "en": "Direct answer"},
    "CALLING_AGENT":      {"fr": "Interrogation de l'agent {label}…",
                             "en": "Querying the {label} agent…"},
    "AGENT_DONE":      {"fr": "Agent {label} : réponse reçue ✓",
                             "en": "{label} agent: answer received ✓"},
    "RUNNING_TOOL":       {"fr": "Outil « {label} » en cours…",
                             "en": "Running tool “{label}”…"},
    "TOOL_DONE":       {"fr": "Outil « {label} » : terminé ✓",
                             "en": "Tool “{label}”: done ✓"},
    "WRITING_ANSWER": {"fr": "Rédaction de la réponse finale…",
                             "en": "Writing the final answer…"},
    "DONE":            {"fr": "Terminé ✓",
                             "en": "Done ✓"},
    "ERROR":           {"fr": "⚠️ Un problème est survenu",
                             "en": "⚠️ Something went wrong"},
}

# --- Textes UX --------------------------------------------------------------
ANNOUNCE = {
    "fr": "🔎 J'interroge l'agent **{label}** — « {q} »\n\n",
    "en": "🔎 Querying the **{label}** agent — “{q}”\n\n",
}
EMPTY_ANSWER = {
    "fr": "\n\n⚠️ L'agent spécialisé n'a rien renvoyé cette fois-ci. Pourriez-vous reformuler votre question ? Je m'en occupe tout de suite.",
    "en": "\n\n⚠️ The specialist agent returned nothing this time. Could you rephrase your question? I'll get right on it.",
}
INTERNAL_ERROR = {
    "fr": "⚠️ Oups, un souci technique de mon côté. Pourriez-vous réessayer dans un instant ? Si ça persiste, signalez-le via l'onglet feedback — merci !",
    "en": "⚠️ Oops, a technical hiccup on my side. Could you try again in a moment? If it persists, please report it via the feedback tab — thanks!",
}
PLANNER_FALLBACK_CLARIFY = {
    "fr": "Je veux être sûr de bien vous répondre 🙂 Pourriez-vous préciser le client, l'indicateur et la période qui vous intéressent ?",
    "en": "I want to make sure I get this right 🙂 Could you specify the customer, the metric and the period you're interested in?",
}
ALL_STEPS_FAILED = {
    "fr": "⚠️ Aucune des sources n'a pu répondre cette fois-ci. Réessayez dans un instant ou reformulez votre question — je reste à votre disposition.",
    "en": "⚠️ None of the sources could answer this time. Please retry shortly or rephrase your question — I'm here to help.",
}

# --- Deterministic non-business templates (R1/R2: no business-fact surface) ---
CAPABILITY_GAP_TEXT = {
    "fr": "Je n'ai pas encore d'agent pour {domain}, donc je préfère ne rien inventer. "
          "En revanche, je peux vous aider sur : {available}.",
    "en": "I don't have an agent for {domain} yet, so I won't make anything up. "
          "I can however help you with: {available}.",
}
CAPABILITY_GAP_GENERIC = {
    "fr": "Je n'ai pas encore d'agent pour répondre à ça, et je ne vais pas inventer. "
          "Je peux vous aider sur : {available}.",
    "en": "I don't have an agent for that yet, and I won't make anything up. "
          "I can help you with: {available}.",
}
OUT_OF_SCOPE_REDIRECT = {
    "fr": "Ça sort un peu de mon terrain de jeu 🙂 Je suis spécialisé dans les données métier OWI. "
          "Je peux vous aider sur : {available}.",
    "en": "That's a bit outside my playground 🙂 I focus on OWI business data. "
          "I can help you with: {available}.",
}

# --- Accompagnement utilisateur (templates déterministes — AUCUN appel LLM) ---
GREETING_PREFIX = {
    "fr": "Bonjour {name} ! ",
    "en": "Hello {name} ! ",
}
MULTI_INTRO = {
    "fr": "📋 Pour répondre à votre question, je vais interroger {n} sources : {labels}. Je reviens vers vous avec la synthèse.\n\n",
    "en": "📋 To answer your question, I will query {n} sources: {labels}. I'll be back with the synthesis.\n\n",
}
STEP_PROGRESS = {
    "fr": "→ {label}…\n",
    "en": "→ {label}…\n",
}
STEP_OK = {
    "fr": "   ✓ terminé ({secs}s)\n",
    "en": "   ✓ done ({secs}s)\n",
}
STEP_FAIL = {
    "fr": "   ✗ indisponible\n",
    "en": "   ✗ unavailable\n",
}
SYNTH_INTRO = {
    "fr": "\n✍️ Je rédige la synthèse…\n\n",
    "en": "\n✍️ Writing the synthesis…\n\n",
}

# =============================================================================
# 5. PERSONA + PLANIFICATEUR (prompt + schéma JSON)
# =============================================================================

# --- PERSONA PARTAGÉ --------------------------------------------------------
# Source UNIQUE de la voix d'OWIsMind. Injecté dans le planner (direct_answer),
# la synthèse et les capabilities -> voix cohérente et chaleureuse partout.
OWISMIND_PERSONA = (
    "# WHO YOU ARE\n"
    "You are OWIsMind, the internal data assistant of Orange Wholesale International. "
    "You talk to sales managers, business-development leads and executives — busy people who "
    "want a sharp answer, not a lecture.\n\n"
    "# YOUR VOICE\n"
    "- A sharp, friendly colleague — never a corporate robot.\n"
    "- In French, always address the user with 'vous'. You may use their first name.\n"
    "- Warm and direct, a light touch of humour when it fits — never at the expense of precision.\n"
    "- Concise. Get to the point. No empty openers ('I'd be happy to…', 'Great question!').\n"
    "- At most one emoji, and only if it genuinely adds something.\n"
    "- Never sound like an AI: no stilted phrasing, no meta-commentary about yourself.\n\n"
    "# YOUR HONESTY (NON-NEGOTIABLE)\n"
    "- You'd rather say 'I don't know' or 'I don't have that data' than make something up.\n"
    "- You NEVER invent a figure, a source, or a capability you don't have.\n"
)

PLANNER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string",
                   "enum": ["BUSINESS", "GREETING", "CAPABILITIES", "CLARIFY",
                            "OUT_OF_SCOPE", "CAPABILITY_GAP", "CONCEPT"]},
        "domain": {"type": "string"},
        "language": {"type": "string", "enum": ["fr", "en"]},
        "user_first_name": {"type": "string"},
        "direct_answer": {"type": "string"},
        "synthesis_hint": {"type": "string"},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["agent", "tool"]},
                    "capability": {"type": "string"},
                    "instruction": {"type": "string"},
                },
                "required": ["kind", "capability", "instruction"],
            },
        },
    },
    "required": ["intent", "language"],
}


def build_planner_prompt(caps, current_datetime="", user_display_name="", session_context=""):
    agents = {k: v for k, v in caps.items() if v["kind"] == "agent"}
    tools = {k: v for k, v in caps.items() if v["kind"] == "tool"}

    agents_block = "\n".join('- "%s" (agent): %s' % (k, v["planner_description"]) for k, v in agents.items()) or "(none)"
    tools_block = "\n".join('- "%s" (tool): %s' % (k, v["planner_description"]) for k, v in tools.items()) or "(none)"

    first_agent = next(iter(agents), None)
    first_tool = next(iter(tools), None)

    staffed = staffed_domains(caps)
    domain_lines = []
    for dom, lab in BUSINESS_DOMAINS.items():
        mark = "HAS an agent" if dom in staffed else "NO agent yet"
        domain_lines.append('- %s (%s): %s' % (dom, mark, lab["en"]))
    domains_block = "\n".join(domain_lines)

    examples = [
        'User: "Bonjour !" (session context says the user is Said Chaoui) -> '
        '{"intent": "GREETING", "language": "fr", "user_first_name": "Said", '
        '"direct_answer": "Bonjour Said ! Ravi de vous retrouver 🙂 Une question sur vos données métier OWI ?"}',
        'User: "je m\'appelle comment ?" -> {"intent": "GREETING", "language": "fr", '
        '"user_first_name": "Said", "direct_answer": "Vous vous appelez Said Chaoui 🙂 '
        'Que puis-je faire pour vous sur les données OWI ?"}',
        'User: "Quelle est la capitale du Japon ?" -> {"intent": "OUT_OF_SCOPE", "language": "fr", '
        '"direct_answer": "Ah, ça sort un peu de mon terrain de jeu 🙂 Je suis spécialisé dans les '
        'données métier OWI — les revenus de vos clients, par exemple. Une question là-dessus ?"}',
    ]
    if first_agent:
        examples.append(
            'User: "Combien on a fait avec algerie telecom en 2025 ?" -> '
            '{"intent": "BUSINESS", "language": "fr", "steps": [{"kind": "agent", '
            '"capability": "%s", "instruction": "Quel est le revenu total réalisé avec '
            'algerie telecom en 2025 ?"}]}' % first_agent)
        examples.append(
            'History: [revenus algerie telecom 2025] then User: "et en 2024 ?" -> '
            '{"intent": "BUSINESS", "language": "fr", "steps": [{"kind": "agent", '
            '"capability": "%s", "instruction": "Quel est le revenu total réalisé avec '
            'algerie telecom en 2024 ?"}]}' % first_agent)
        examples.append(
            'User: "Compare le CA d\'algerie telecom entre 2024 et 2025" -> ONE single step '
            '(the agent handles multi-period comparisons): {"intent": "BUSINESS", "language": "fr", '
            '"steps": [{"kind": "agent", "capability": "%s", "instruction": "Compare le revenu '
            'total d\'algerie telecom entre 2024 et 2025"}]}' % first_agent)
    if first_agent and first_tool:
        examples.append(
            'User: "Quelle est la date du jour et le CA d\'algerie telecom en 2025 ?" -> two steps: '
            '{"intent": "BUSINESS", "language": "fr", "steps": ['
            '{"kind": "tool", "capability": "%s", "instruction": "today"}, '
            '{"kind": "agent", "capability": "%s", "instruction": "Quel est le revenu total '
            'réalisé avec algerie telecom en 2025 ?"}], '
            '"synthesis_hint": "donner la date puis le chiffre"}' % (first_tool, first_agent))
    if first_agent:
        examples.append(
            'User: "Give me the budget 2026 for the Roaming Hub" -> the revenue '
            'agent owns ALL phases, route it (do NOT deny budget): '
            '{"intent": "BUSINESS", "language": "en", "steps": [{"kind": "agent", '
            '"capability": "%s", "instruction": "Give me the budget 2026 revenue '
            'for the Roaming Hub"}]}' % first_agent)
    examples.append(
        'User: "combien de tickets d\'incidents avec 1&1 en 2025 ?" and NO agent '
        'covers the tickets domain -> {"intent": "CAPABILITY_GAP", "language": '
        '"fr", "domain": "tickets"}')
    examples.append(
        'User: "quelle est la différence entre le SS7 et le LTE ?" (general '
        'concept, no OWI data) -> {"intent": "CONCEPT", "language": "fr", '
        '"direct_answer": "<short general explanation, framed as general '
        'knowledge, no OWI figure>"}')

    ctx_header = ""
    if current_datetime:
        ctx_header += "Current date and time (server): " + str(current_datetime) + "\n"
    if user_display_name:
        ctx_header += "You are assisting: " + str(user_display_name) + "\n"
    if session_context:
        ctx_header += ("SESSION CONTEXT provided by the application (may contain the user's "
                       "name and the current date — trust it):\n---\n"
                       + session_context.strip() + "\n---\n")
    if ctx_header:
        ctx_header += "\n"

    return (
        OWISMIND_PERSONA + "\n" +
        ctx_header +
        "You are the PLANNING MODULE (the brain) of OWIsMind, Orange Wholesale "
        "International's internal business-intelligence assistant. Analyze the user's "
        "CURRENT question (using the conversation history for context) and output ONE "
        "JSON object describing the execution plan. You NEVER answer business questions "
        "yourself: business data ONLY comes from the capabilities below.\n\n"
        "AVAILABLE AGENTS (business data):\n" + agents_block + "\n\n"
        "AVAILABLE TOOLS (direct actions):\n" + tools_block + "\n\n"
        "BUSINESS DOMAINS (the product's known domains; an agent may or may not be "
        "wired for each):\n" + domains_block + "\n\n"
        "INTENTS (field \"intent\"):\n"
        "- \"BUSINESS\": needs business data or an action -> build \"steps\". This is "
        "the DEFAULT for anything touching a domain that HAS an agent, EVEN IF you "
        "are unsure the specific figure exists — only the agent can confirm.\n"
        "- \"CAPABILITY_GAP\": the question is about a real BUSINESS DOMAIN that has "
        "NO agent yet -> set \"domain\" to that domain key. Do NOT answer; the code "
        "emits an honest 'no agent for this yet' message.\n"
        "- \"CONCEPT\": a GENERAL telco/business notion with no OWI-specific data "
        "(e.g. 'difference between SS7 and LTE'). Put a short, general-knowledge "
        "answer in \"direct_answer\", explicitly framed as general knowledge, with "
        "NO OWI figure. If an agent OWNS the methodology (e.g. 'how do you compute "
        "the forecast' -> the revenue agent), prefer BUSINESS instead.\n"
        "- \"GREETING\": greetings, thanks, small talk, personal/session questions "
        "(the user's own name, today's date, who you are) -> \"direct_answer\" using "
        "the session context. NEVER refuse these coldly.\n"
        "- \"CAPABILITIES\": the user asks what you can do -> no answer needed (handled by code).\n"
        "- \"CLARIFY\": business-related but genuinely contentless/ambiguous -> "
        "\"direct_answer\" = ONE short question. Prefer BUSINESS (the agent's own "
        "clarification is grounded in real data) whenever an agent could handle it.\n"
        "- \"OUT_OF_SCOPE\": clearly unrelated to OWI business data (weather, trivia) "
        "-> handled by code.\n\n"
        "PLANNING RULES (intent BUSINESS):\n"
        "1. Each step = {\"kind\": \"agent\"|\"tool\", \"capability\": <exact key from the lists>, "
        "\"instruction\": <self-contained instruction>}.\n"
        "2. MINIMUM number of steps. One step per DATA DOMAIN involved - an agent handles "
        "comparisons, rankings and multi-period analysis within its domain in ONE step.\n"
        "3. Each \"instruction\" must be SELF-CONTAINED, in the user's language: resolve "
        "pronouns and ellipses from the history (e.g. \"et en 2024 ?\" -> full question for 2024).\n"
        "4. Preserve customer/product names EXACTLY as the user wrote them - never correct, "
        "translate or expand them.\n"
        "5. NEVER invent capability keys. Only use keys listed above.\n"
        "6. Maximum " + str(MAX_STEPS) + " steps. If the question needs more, choose the most important ones.\n"
        "7. Optional \"synthesis_hint\": one short sentence guiding the final answer when steps > 1.\n"
        "8. Resolve RELATIVE time references (\"cette annee\", \"ce mois-ci\", \"YTD\", "
        "\"le mois dernier\", \"this year\") into EXPLICIT periods in the instructions, "
        "using the current date above.\n\n"
        "EXTRA OUTPUT FIELD:\n"
        "- \"user_first_name\": if the session context reveals the user's name, return their "
        "FIRST name here. Omit it otherwise.\n\n"
        "TONE for \"direct_answer\" (your full voice is defined at the top of this prompt):\n"
        "- For OUT_OF_SCOPE: decline kindly with a light touch, then suggest what you CAN help "
        "with. No cold refusals, no walls.\n"
        "- For GREETING / personal questions: answer naturally using the session context, "
        "like a colleague who remembers you.\n\n"
        "HARD RULES:\n"
        "- Output ONLY the JSON object. No markdown fences, no commentary.\n"
        "- NEVER put figures, amounts or any business data in \"direct_answer\".\n"
        "- You do NOT know what the data contains. You NEVER tell the user that a "
        "metric, a scenario (budget/forecast/actuals/Q3F/HLF), a figure or a record "
        "is unavailable, missing, or zero — that is ONLY the agent's call.\n"
        "- You MAY state you lack an AGENT for a domain (CAPABILITY_GAP). You may "
        "NEVER state that the DATA does not exist.\n"
        "- A question about revenues, customers, tickets, products, amounts, budget "
        "or forecast is NEVER GREETING/OUT_OF_SCOPE.\n"
        "- \"language\" = language of the CURRENT question: \"fr\" or \"en\".\n\n"
        "EXAMPLES:\n" + "\n".join(examples) + "\n"
    )


SYNTHESIS_PROMPT = (
    OWISMIND_PERSONA +
    "\n# TASK\n"
    "You are the ANSWER WRITER of OWIsMind. Write the final answer to the user's "
    "question, using ONLY the step results provided below.\n"
    "RULES:\n"
    "- Answer in the user's language ({language}).\n"
    "- Use ONLY figures and facts present in the results. NEVER invent or extrapolate.\n"
    "- Keep all figures EXACTLY as provided (amounts, units, currencies).\n"
    "- If a step failed or returned nothing, say so explicitly for that part.\n"
    "- If a step returned 'no data' / 'out of scope' / a capability gap, report "
    "that honestly for that part. NEVER replace a missing result with a guessed "
    "or zero figure.\n"
    "- Lead with the direct answer. No filler openings, no greetings (the user was already greeted).\n"
    "- Warm and human while professional: in French, address the user with 'vous'.\n"
    "- Use thousands separators and currency symbols for figures.\n"
    "- Do NOT add a sources section: it is appended automatically by the system.\n"
    "- Be concise and structured (markdown allowed). Mention which source each figure "
    "comes from when several sources are involved.\n"
)

# Réponse CAPABILITIES rédigée par le LLM, mais STRICTEMENT ancrée sur les faits
# du registre fournis dans le message user -> ton libre, zéro capacité inventée.
CAPABILITIES_PROMPT = (
    OWISMIND_PERSONA +
    "\n# TASK\n"
    "The user asked what you can do. Introduce your capabilities warmly, in {language}, "
    "using ONLY the capabilities listed in the user message below.\n"
    "RULES:\n"
    "- Use ONLY the listed capabilities. NEVER invent or imply a capability that is not listed.\n"
    "- Not a dry bullet dump: a short warm intro, the capabilities, then a light invitation to "
    "ask a question.\n"
    "- Keep it short. Markdown allowed. At most one emoji.\n"
)

# =============================================================================
# 6. HELPERS
# =============================================================================

def _ev(kind, data=None):
    return {"chunk": {"type": "event", "eventKind": kind, "eventData": data or {}}}


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def _ev_l(kind, lang="fr", data=None, **fmt):
    """Événement avec libellé humain prêt à afficher dans eventData['label']."""
    ed = dict(data or {})
    tmpl = (STEP_LABELS.get(kind) or {}).get(lang) or (STEP_LABELS.get(kind) or {}).get("fr") or kind
    ed["label"] = tmpl.format_map(_SafeDict(fmt))
    return {"chunk": {"type": "event", "eventKind": kind, "eventData": ed}}


_SKIPPED_SUB_KINDS = ("SUB_AGENT_AGENT_TURN_START", "SUB_AGENT_AGENT_BLOCK_DONE")


def _clean_tool_suffix(name):
    """'Drive_Revenues_resolve_filter_value__f547e0' -> 'Drive_Revenues_resolve_filter_value'"""
    return re.sub(r"__[0-9a-fA-F]{4,}$", "", name or "")


def _sub_event_label(kind, event_data, lang, cfg):
    """Libellé humain d'un événement relayé d'un sous-agent.
    Retourne None -> événement technique masqué de la timeline (le trace garde tout)."""
    if kind in _SKIPPED_SUB_KINDS:
        return None
    agent_label = cfg.get("label_%s" % lang) or cfg.get("label_fr") or ""

    if kind == "SUB_AGENT_AGENT_THINKING":
        return ("%s réfléchit…" if lang == "fr" else "%s is thinking…") % agent_label

    if kind == "SUB_AGENT_AGENT_TOOL_START":
        base = _clean_tool_suffix(event_data.get("toolName"))
        tl = (cfg.get("tool_labels") or {}).get(base) or {}
        tool_label = tl.get(lang) or tl.get("fr") or base.replace("_", " ")
        return "%s — %s…" % (agent_label, tool_label)

    if kind == "SUB_AGENT_AGENT_BLOCK_START":
        block_id = event_data.get("blockId")
        bl_map = cfg.get("block_labels") or {}
        if block_id in bl_map:
            bl = bl_map[block_id]
            if bl is None:
                return None                      # bloc technique explicitement masqué
            return "%s — %s…" % (agent_label, bl.get(lang) or bl.get("fr"))
        if lang == "fr":
            return "%s — étape « %s »…" % (agent_label, block_id)
        return "%s — step \"%s\"…" % (agent_label, block_id)

    # Kind inconnu : libellé générique lisible plutôt qu'un identifiant machine.
    return "%s — %s" % (agent_label,
                        kind.replace("SUB_AGENT_AGENT_", "").replace("_", " ").lower())


def _is_footer(chunk, data):
    """True when a streamed chunk is the final run footer (carries the trace).

    ORCH-07: recognised either by its ``type == "footer"`` payload or, when the
    SDK exposes the class, by isinstance — some SDK builds emit the footer chunk
    without a ``type`` field in ``data``, so payload sniffing alone can miss it.
    """
    if isinstance(data, dict) and data.get("type") == "footer":
        return True
    if DSSLLMStreamedCompletionFooter is not None:
        return isinstance(chunk, DSSLLMStreamedCompletionFooter)
    return False


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


def _find_usage_metadata(obj, _depth=0):
    """Collect every usageMetadata dict in the trace (depth-bounded, ORCH-06).

    Real traces nest a handful of levels; the guard turns a pathologically deep
    trace into a graceful partial extraction instead of a RecursionError.
    """
    found = []
    if _depth > _MAX_TRACE_DEPTH:
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


def _sum_usage(usages):
    total = {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "estimatedCost": 0.0}
    for u in usages:
        total["promptTokens"] += u.get("promptTokens", 0) or 0
        total["completionTokens"] += u.get("completionTokens", 0) or 0
        total["totalTokens"] += u.get("totalTokens", 0) or 0
        total["estimatedCost"] += u.get("estimatedCost", 0.0) or 0.0
    return total


def _acc_usage(total, usage):
    for k in ("promptTokens", "completionTokens", "totalTokens"):
        total[k] += (usage or {}).get(k, 0) or 0
    total["estimatedCost"] += (usage or {}).get("estimatedCost", 0.0) or 0.0


# Candidate keys for the result rows inside the SQL tool span outputs, tried in
# this exact order (FROZEN contract). The actual key is NOT confirmed on the
# instance — extraction is strictly best-effort; absence is honest downstream.
_RESULT_ROW_KEYS = ("rows", "records", "data", "result_rows", "values")
# Candidate keys for the column names when rows are a list of lists.
_RESULT_COLUMN_KEYS = ("columns", "column_names", "headers")


def _cap_cell(value):
    """Bound one result cell: keep JSON-safe primitives, stringify the rest.

    int/float/bool/None stay as-is (floats must be finite — NaN/Inf are not
    JSON-serializable and would corrupt the persisted payload). Everything else
    (strings included) goes through str()[:256].
    """
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return str(value)[:_RESULT_CELL_MAX_CHARS]


def _extract_result(outputs):
    """Best-effort capped result capture from a SQL tool span's ``outputs``.

    Accepted shapes (anything else -> None, no capture):
      - list of dicts: columns = first dict's keys (stable order);
      - list of lists/tuples + a separate columns/column_names/headers key.
    Caps applied LOCALLY (the file is standalone): MAX_RESULT_ROWS rows,
    MAX_RESULT_COLS columns, cells bounded by _cap_cell, and a serialized
    budget of _RESULT_JSON_MAX_CHARS beyond which rows are dropped entirely
    (columns kept, truncated flagged) — never an unbounded payload.
    """
    for key in _RESULT_ROW_KEYS:
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
            for col_key in _RESULT_COLUMN_KEYS:
                cand = outputs.get(col_key)
                if isinstance(cand, list) and cand:
                    columns = [str(c)[:_RESULT_CELL_MAX_CHARS] for c in cand[:MAX_RESULT_COLS]]
                    truncated_cols = len(cand) > MAX_RESULT_COLS
                    break
            if columns is None:
                continue  # list-of-lists without named columns -> unusable, skip
            rows = [[_cap_cell(c) for c in list(r)[:MAX_RESULT_COLS]]
                    for r in raw[:MAX_RESULT_ROWS]]
            truncated = (len(raw) > MAX_RESULT_ROWS or truncated_cols
                         or any(len(r) > MAX_RESULT_COLS for r in raw[:MAX_RESULT_ROWS]))
        else:
            continue  # mixed / unknown shape -> no capture (absence is honest)

        result = {"columns": columns, "rows": rows, "truncated": bool(truncated)}
        try:
            serialized = json.dumps(result, ensure_ascii=False, default=str)
        except Exception:
            return None  # unserializable despite capping -> safer not to capture
        if len(serialized) > _RESULT_JSON_MAX_CHARS:
            # Over budget even after row/col/cell caps: keep the shape honest
            # (columns only) rather than persisting a huge payload.
            result = {"columns": columns, "rows": [], "truncated": True}
        return result
    return None


def _find_generated_sql(obj, _depth=0):
    """Extract the SQL tool spans from the trace (depth-bounded, ORCH-06).

    Each item carries {name, success, row_count, sql} plus, when the span
    outputs expose the result rows in a recognised shape, a capped ``result``
    {columns, rows, truncated} (ORCH-02 — opportunistic, never required).
    """
    found = []
    if _depth > _MAX_TRACE_DEPTH:
        return found
    if isinstance(obj, dict):
        outputs = obj.get("outputs") or {}
        if obj.get("name") == "semantic-model-query" and isinstance(outputs, dict) and outputs.get("sql"):
            item = {"name": "semantic-model-query", "success": outputs.get("success"),
                    "row_count": outputs.get("row_count"), "sql": outputs.get("sql")}
            result = _extract_result(outputs)
            if result is not None:
                item["result"] = result
            found.append(item)
        for v in obj.values():
            found.extend(_find_generated_sql(v, _depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_generated_sql(item, _depth + 1))
    return found


def _build_capabilities_facts(caps, lang):
    """Faits ANCRÉS depuis le registre. Le LLM ne reçoit QUE ça -> ne peut rien inventer."""
    label_key = "label_%s" % lang
    lines = []
    for v in caps.values():
        kind = "AGENT" if v["kind"] == "agent" else "TOOL"
        lines.append("- %s (%s): %s" % (v.get(label_key, "?"), kind, v["planner_description"]))
    return "\n".join(lines) or "(none)"


def _build_capabilities_answer(caps, lang):
    """Réponse CAPABILITIES déterministe depuis le registre (zéro hallucination).
    Sert désormais de FALLBACK si l'appel LLM des capabilities échoue."""
    label_key = "label_%s" % lang
    agents = [v for v in caps.values() if v["kind"] == "agent"]
    tools = [v for v in caps.values() if v["kind"] == "tool"]
    if lang == "en":
        lines = ["With pleasure! Here is what I can do for you today:\n"]
        lines += ["- **%s** — %s" % (a.get(label_key, "?"), a["planner_description"]) for a in agents]
        if tools:
            lines.append("\nDirect tools: " + ", ".join(t.get(label_key, "?") for t in tools) + ".")
        lines.append("\nAsk me your question in French or English — I'll take care of the rest 🙂")
    else:
        lines = ["Avec plaisir ! Voici ce que je sais faire pour vous aujourd'hui :\n"]
        lines += ["- **%s** — %s" % (a.get(label_key, "?"), a["planner_description"]) for a in agents]
        if tools:
            lines.append("\nOutils directs : " + ", ".join(t.get(label_key, "?") for t in tools) + ".")
        lines.append("\nPosez-moi votre question en français ou en anglais, je m'occupe du reste 🙂")
    return "\n".join(lines)


def _available_domains_phrase(caps, lang):
    """Comma-joined labels of the staffed business domains (registry-sourced,
    deterministic). Falls back to the agent capability labels if no domain is
    declared. Pure — never emits a business value."""
    labels = []
    for dom in sorted(staffed_domains(caps)):
        lab = BUSINESS_DOMAINS.get(dom, {})
        text = lab.get(lang) or lab.get("fr")
        if text and text not in labels:
            labels.append(text)
    if not labels:
        for v in caps.values():
            if v.get("kind") == "agent":
                text = v.get("label_%s" % lang) or v.get("label_fr")
                if text and text not in labels:
                    labels.append(text)
    return ", ".join(labels)


def build_capability_gap_answer(domain, caps, lang):
    """Honest 'I have no agent for <domain>' message (R2), built from the
    registry — never an LLM free-text and never a figure."""
    available = _available_domains_phrase(caps, lang)
    dom = BUSINESS_DOMAINS.get(domain or "", {})
    dom_label = dom.get(lang) or dom.get("fr")
    if not dom_label:
        return CAPABILITY_GAP_GENERIC[lang].format(available=available)
    return CAPABILITY_GAP_TEXT[lang].format(domain=dom_label, available=available)


def build_out_of_scope_answer(caps, lang):
    """Deterministic out-of-scope redirect — no business assertion surface."""
    return OUT_OF_SCOPE_REDIRECT[lang].format(available=_available_domains_phrase(caps, lang))


def render_non_business_text(intent, plan, caps, lang):
    """Pure text for a non-BUSINESS, non-CAPABILITIES intent (CAPABILITIES streams
    via its own LLM path). CAPABILITY_GAP / OUT_OF_SCOPE -> deterministic registry
    templates (no business-fact surface, R1/R2). GREETING / CLARIFY / CONCEPT ->
    the bounded planner direct_answer, or the clarify fallback when empty."""
    if intent == "CAPABILITY_GAP":
        return build_capability_gap_answer(plan.get("domain"), caps, lang)
    if intent == "OUT_OF_SCOPE":
        return build_out_of_scope_answer(caps, lang)
    return (plan.get("direct_answer") or "").strip() or PLANNER_FALLBACK_CLARIFY[lang]


def _sources_block(results, caps, lang):
    """Sources section generated BY CODE from the registry — never by the LLM.

    ORCH-05: emits the BUSINESS dataset labels (dataset_label_fr/en) of the
    capabilities actually used with success, deduplicated. Intranet URLs
    (dataset_sources) stay server-only in the registry and never reach the
    answer text. Zero invented sources, by construction.
    """
    labels, seen = [], set()
    label_key = "dataset_label_%s" % lang
    for r in results:
        if r.get("status") != "ok":
            continue
        cfg = caps.get(r.get("capability"), {})
        label = cfg.get(label_key) or cfg.get("dataset_label_fr")
        if label and label not in seen:
            seen.add(label)
            labels.append(label)
    if not labels:
        return ""
    return "\n\n**Sources** : " + ", ".join(labels)


def build_subagent_context(history, last_q):
    """v2.3: compact conversation context forwarded to sub-agents that opt in
    (capability flag "pass_context"). Carries the PREVIOUS assistant message —
    e.g. a disambiguation question with its candidate list — plus the user's
    raw answer, so the sub-agent's own LLM can interpret replies like "the
    first one" / "le produit" against the candidates offered on the previous
    turn. Generic by design: no per-value logic anywhere."""
    last_assistant = ""
    for m in reversed(history or []):
        if m.get("role") == "assistant" and m.get("content"):
            last_assistant = m["content"]
            break
    if not last_assistant:
        return ""
    return ("CONVERSATION CONTEXT (continuity with the previous turn):\n"
            "PREVIOUS ASSISTANT MESSAGE:\n%s\n\n"
            "USER'S RAW CURRENT MESSAGE:\n%s"
            % (last_assistant[:2000], (last_q or "")[:500]))


# =============================================================================
# 7. AGENT
# =============================================================================

class MyLLM(BaseLLM):

    # ------------------------------------------------------------------ MAIN
    def process_stream(self, query, settings, trace):
        t0 = time.perf_counter()
        yield _ev_l("START")   # premier octet immédiat pour la webapp

        total_usage = {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "estimatedCost": 0.0}

        try:
            project = dataiku.api_client().get_default_project()
            caps = get_capabilities()
            history, last_q, session_context = self._extract_messages(query)

            # Contexte session GÉNÉRIQUE — aucun couplage à un mécanisme webapp :
            # 1) query["context"] si fourni ; 2) messages system injectés dans la
            # conversation (transmis verbatim au planificateur) ; 3) date serveur en
            # fallback. Le prénom est extrait par le planificateur (user_first_name).
            ctx = query.get("context") or {}
            user_display_name = (ctx.get("user_display_name") or "").strip()
            first_name = user_display_name.split()[0] if user_display_name else ""
            current_dt = ctx.get("current_datetime") or datetime.now().strftime("%A %d %B %Y, %H:%M")

            if not last_q:
                # ORCH-03: stable machine code only (no free-text diagnostics).
                yield _ev_l("ERROR", "fr", {"stage": "input", "message": ERROR_CODE_NO_USER_MESSAGE})
                yield {"chunk": {"text": INTERNAL_ERROR["fr"]}}
                return

            # ============ PHASE 1 : PLAN ============
            yield _ev_l("PLANNING")
            with trace.subspan("orchestrator:plan") as sp:
                sp.inputs["question"] = last_q
                plan = self._plan(project, caps, history, last_q, sp, total_usage,
                                  current_datetime=current_dt, user_display_name=user_display_name,
                                  session_context=session_context)
                sp.outputs["plan"] = plan

            lang = plan.get("language") if plan.get("language") in ("fr", "en") else "fr"
            intent = plan.get("intent", "")
            steps = plan.get("steps", [])
            # Prénom : priorité au contexte explicite, sinon extrait par le planificateur.
            first_name = first_name or (plan.get("user_first_name") or "").strip()

            # ORCH-10c: steps are SUMMARIZED — never echo the full instructions
            # into an event payload (they can carry user data; the trace keeps all).
            yield _ev_l("PLAN_READY", lang, {
                "intent": intent, "language": lang, "fallback": bool(plan.get("_fallback")),
                "stepCount": len(steps),
                "steps": [{"kind": s["kind"], "capability": s["capability"],
                           "instruction": s["instruction"][:120]} for s in steps],
            })

            # ============ BRANCHE NON-MÉTIER ============
            if intent != "BUSINESS":
                yield _ev_l("DIRECT_ANSWER", lang, {"kind": intent or "CLARIFY"})
                if intent == "CAPABILITIES":
                    # Rédaction LLM ancrée sur le registre, fallback déterministe interne.
                    yield from self._answer_capabilities(project, caps, lang, trace, total_usage)
                else:
                    # R1/R2 firewall: CAPABILITY_GAP / OUT_OF_SCOPE -> deterministic
                    # registry templates; GREETING / CLARIFY / CONCEPT -> bounded
                    # planner direct_answer. No business fact can be authored here.
                    yield {"chunk": {"text": render_non_business_text(intent, plan, caps, lang)}}
                yield _ev_l("DONE", lang, {"durationMs": int((time.perf_counter() - t0) * 1000),
                                                "totalUsage": total_usage})
                return

            # ============ PHASE 2 : EXECUTE ============
            # Mono-étape agent -> texte relayé verbatim (0 coût de synthèse).
            relay_text = (len(steps) == 1 and steps[0]["kind"] == "agent")
            step_count = len(steps)
            results = []

            # Accueil personnalisé : premier tour de conversation uniquement.
            greet = GREETING_PREFIX[lang].format(name=first_name) if (first_name and not history) else ""

            if not relay_text:
                labels = ", ".join(
                    caps[s["capability"]].get("label_%s" % lang, s["capability"]) for s in steps)
                yield {"chunk": {"text": greet + MULTI_INTRO[lang].format(n=step_count, labels=labels)}}
                greet = ""  # consommé

            # ORCH-10d: unconditional greet flush BEFORE the steps loop. The relay
            # path with ANNOUNCE_IN_CONTENT=False used to silently drop the greet.
            if greet:
                yield {"chunk": {"text": greet}}
                greet = ""

            # v2.3: conversation continuity for sub-agents that opt in
            # ("pass_context"): the previous assistant message (e.g. a pending
            # disambiguation question) + the user's raw answer.
            sub_context = build_subagent_context(history, last_q)

            for idx, step in enumerate(steps, start=1):
                cfg = caps[step["capability"]]
                label = cfg.get("label_%s" % lang, step["capability"])

                if step["kind"] == "agent":
                    if relay_text and ANNOUNCE_IN_CONTENT:
                        yield {"chunk": {"text": ANNOUNCE[lang].format(label=label, q=step["instruction"])}}
                    elif not relay_text:
                        yield {"chunk": {"text": STEP_PROGRESS[lang].format(label=label)}}
                    # ORCH-04: no agentId in eventData — the internal id stays in
                    # the step span attributes only (never surfaced to the client).
                    yield _ev_l("CALLING_AGENT", lang, {
                        "agentKey": step["capability"],
                        "question": step["instruction"], "stepIndex": idx, "stepCount": step_count},
                        label=label)
                    res = yield from self._execute_agent_step(
                        project, idx, step, cfg, trace, relay_text=relay_text, lang=lang,
                        context_msg=sub_context)
                    _acc_usage(total_usage, res.get("usage"))
                    yield _ev_l("AGENT_DONE", lang, {
                        "agentKey": step["capability"], "stepIndex": idx, "status": res["status"],
                        "durationMs": res["duration_ms"], "usage": res.get("usage"),
                        "generatedSql": res.get("generated_sql", []),
                        "agentResult": res.get("agent_result")},
                        label=label)

                else:  # tool
                    if not relay_text:
                        yield {"chunk": {"text": STEP_PROGRESS[lang].format(label=label)}}
                    yield _ev_l("RUNNING_TOOL", lang, {
                        "toolKey": step["capability"], "instruction": step["instruction"],
                        "stepIndex": idx, "stepCount": step_count}, label=label)
                    res = self._execute_tool_step(idx, step, cfg, trace)
                    yield _ev_l("TOOL_DONE", lang, {
                        "toolKey": step["capability"], "stepIndex": idx,
                        "status": res["status"], "durationMs": res["duration_ms"]}, label=label)

                if not relay_text:
                    tmpl = STEP_OK if res["status"] == "ok" else STEP_FAIL
                    yield {"chunk": {"text": tmpl[lang].format(
                        label=label, secs=round(res["duration_ms"] / 1000.0, 1))}}

                results.append(res)

            ok_results = [r for r in results if r["status"] == "ok"]

            # ============ PHASE 3 : SYNTHESIZE ============
            if relay_text:
                # Réponse déjà streamée verbatim par le sous-agent.
                if results and results[0]["status"] == "empty":
                    yield {"chunk": {"text": EMPTY_ANSWER[lang]}}
                elif not ok_results:
                    yield {"chunk": {"text": ALL_STEPS_FAILED[lang]}}
                else:
                    # v2.3: a clarification or an out-of-scope notice cites no
                    # dataset — the structured sub-agent status gates the block.
                    ar = results[0].get("agent_result") or {}
                    if ar.get("status") not in ("need_clarification", "out_of_scope"):
                        src = _sources_block(results, caps, lang)
                        if src:
                            yield {"chunk": {"text": src}}
            elif not ok_results:
                yield {"chunk": {"text": ALL_STEPS_FAILED[lang]}}
            else:
                yield {"chunk": {"text": SYNTH_INTRO[lang]}}
                yield _ev_l("WRITING_ANSWER", lang)
                yield from self._synthesize(project, last_q, lang, plan.get("synthesis_hint"),
                                            results, caps, trace, total_usage)
                src = _sources_block(results, caps, lang)
                if src:
                    yield {"chunk": {"text": src}}

            yield _ev_l("DONE", lang, {
                "durationMs": int((time.perf_counter() - t0) * 1000),
                "totalUsage": total_usage,
                "stepsOk": len(ok_results), "stepsFailed": len(results) - len(ok_results)})

        except Exception:
            # ORCH-03: str(e) stays in the logs; the event carries a stable code.
            logger.exception("Orchestrator failure")
            yield _ev_l("ERROR", "fr", {"stage": "unhandled", "message": ERROR_CODE_INTERNAL})
            yield {"chunk": {"text": INTERNAL_ERROR["fr"]}}

    # ------------------------------------------------------ STEP: capabilities
    def _answer_capabilities(self, project, caps, lang, trace, total_usage):
        """CAPABILITIES : faits ANCRÉS (registre), TON rédigé par le LLM (anti-hallu).
        Fallback déterministe si l'appel échoue (refuse-rather-than-hallucinate)."""
        facts = _build_capabilities_facts(caps, lang)
        system = CAPABILITIES_PROMPT.replace("{language}", lang)
        user_block = "AVAILABLE CAPABILITIES (use ONLY these, never invent any):\n" + facts
        llm = project.get_llm(SYNTH_LLM_ID or PLANNER_LLM_ID)
        cap_trace, streamed_any = None, False
        with trace.subspan("orchestrator:capabilities") as sp:
            try:
                completion = llm.new_completion() \
                    .with_message(system, role="system") \
                    .with_message(user_block, role="user")
                for chunk in completion.execute_streamed():
                    data = getattr(chunk, "data", {}) or {}
                    if _is_footer(chunk, data):           # ORCH-07
                        cap_trace = data.get("trace")
                        continue
                    ctype = data.get("type") or getattr(chunk, "type", None)
                    if ctype in ("content", "text"):
                        txt = data.get("text", "") or ""
                        if txt:
                            streamed_any = True
                            yield {"chunk": {"text": txt}}
            except Exception as e:
                logger.exception("Capabilities answer failed")
                sp.attributes["error"] = str(e)[:500]
            if cap_trace:
                try:
                    sp.append_trace(cap_trace)
                    _acc_usage(total_usage, _sum_usage(_find_usage_metadata(cap_trace)))
                except Exception:
                    pass
        if not streamed_any:
            # Dégradation propre : liste déterministe depuis le registre.
            yield {"chunk": {"text": _build_capabilities_answer(caps, lang)}}

    # ------------------------------------------------------- STEP: sous-agent
    def _execute_agent_step(self, project, step_index, step, cfg, trace, relay_text,
                            lang="fr", context_msg=""):
        """Appel streamé d'un sous-agent. Events relayés EN LIVE avec libellé humain
        (eventData['label']) ; les événements techniques sont masqués de la timeline
        (la trace conserve tout). Texte relayé seulement si relay_text (mono-étape)."""
        t0 = time.perf_counter()
        sub_trace, answer_parts, status = None, [], "ok"
        agent_result = None    # v2.3: structured AGENT_RESULT payload (code agents)

        with trace.subspan("step_%d:agent:%s" % (step_index, step["capability"])) as sp:
            sp.attributes["agentId"] = cfg["agent_id"]
            sp.inputs["question"] = step["instruction"]
            try:
                completion = project.get_llm(cfg["agent_id"]).new_completion()
                # v2.3: opt-in only (visual agents could be confused by an
                # unexpected system message — code agents read it explicitly).
                if context_msg and cfg.get("pass_context"):
                    completion.with_message(context_msg, role="system")
                completion.with_message(step["instruction"])
                for chunk in completion.execute_streamed():
                    data = getattr(chunk, "data", {}) or {}
                    if _is_footer(chunk, data):           # ORCH-07
                        sub_trace = data.get("trace")
                        continue
                    ctype = data.get("type") or getattr(chunk, "type", None)

                    if ctype == "event":
                        # v2.3: machine-readable status from a code sub-agent —
                        # captured for the step result, never relayed (the
                        # timeline shows human labels, not contract payloads).
                        if (data.get("eventKind") or "") == "AGENT_RESULT":
                            agent_result = dict(data.get("eventData") or {})
                            continue
                        sub_kind = "SUB_AGENT_" + (data.get("eventKind") or "UNKNOWN")
                        ed = dict(data.get("eventData") or {})
                        human_label = _sub_event_label(sub_kind, ed, lang, cfg)
                        if human_label is None:
                            continue            # événement technique -> masqué de la timeline
                        ed["agentKey"] = step["capability"]
                        ed["stepIndex"] = step_index
                        ed["label"] = human_label
                        yield {"chunk": {"type": "event", "eventKind": sub_kind, "eventData": ed}}
                    elif ctype in ("content", "text"):
                        txt = data.get("text", "") or ""
                        if txt:
                            answer_parts.append(txt)
                            if relay_text:
                                yield {"chunk": {"text": txt}}
            except Exception as e:
                logger.exception("Agent step %d failed (%s)", step_index, step["capability"])
                # ORCH-03: the raw error stays in the span + logs; the live event
                # only carries a stable machine code.
                sp.attributes["error"] = str(e)[:500]
                status = "error"
                yield _ev_l("ERROR", lang, {"stage": "agent_step", "stepIndex": step_index,
                                                 "agentKey": step["capability"],
                                                 "message": ERROR_CODE_AGENT_STEP_FAILED})

            if sub_trace:
                # Guarded like the other streamed loops (ORCHV22-02): a footer
                # trace shape append_trace rejects must not blow up the turn
                # AFTER the answer was already relayed — the merged cost is
                # degraded, but the answer, SQL tagging and AGENT_DONE survive.
                try:
                    sp.append_trace(sub_trace)
                except Exception as e:
                    logger.exception("append_trace failed for step %d", step_index)
                    sp.attributes["trace_append_error"] = str(e)[:300]
            answer = "".join(answer_parts)
            sp.outputs["answer"] = answer

        if status == "ok" and not answer.strip():
            status = "empty"

        # ORCH-02: tag each generated_sql item with its correlation keys BEFORE the
        # AGENT_DONE event is emitted (the webapp persists these items and Evidence
        # Studio correlates them back to the step / sub-agent that produced them).
        # sql_id format is part of the frozen contract: 's{stepIndex}q{n}'.
        generated_sql = _find_generated_sql(sub_trace) if sub_trace else []
        for n, item in enumerate(generated_sql, start=1):
            item["sql_id"] = "s%dq%d" % (step_index, n)
            item["step_index"] = step_index
            item["agent_key"] = step["capability"]

        return {
            "kind": "agent", "capability": step["capability"], "instruction": step["instruction"],
            "status": status, "output": answer,
            "duration_ms": int((time.perf_counter() - t0) * 1000),
            "usage": _sum_usage(_find_usage_metadata(sub_trace)) if sub_trace else {},
            "generated_sql": generated_sql,
            "agent_result": agent_result,
        }

    # ------------------------------------------------------------ STEP: tool
    def _execute_tool_step(self, step_index, step, cfg, trace):
        t0 = time.perf_counter()
        status, output = "ok", ""
        with trace.subspan("step_%d:tool:%s" % (step_index, step["capability"])) as sp:
            sp.inputs["instruction"] = step["instruction"]
            try:
                result = cfg["run"]({"instruction": step["instruction"]})
                output = json.dumps(result, ensure_ascii=False, default=str)
                sp.outputs["result"] = output[:2000]
            except Exception as e:
                logger.exception("Tool step %d failed (%s)", step_index, step["capability"])
                sp.attributes["error"] = str(e)[:500]
                status = "error"
        return {"kind": "tool", "capability": step["capability"], "instruction": step["instruction"],
                "status": status, "output": output,
                "duration_ms": int((time.perf_counter() - t0) * 1000), "usage": {}}

    # ------------------------------------------------------------- PLANNER
    def _plan(self, project, caps, history, last_q, span, total_usage,
              current_datetime="", user_display_name="", session_context=""):
        """2 tentatives (JSON mode natif puis prompt-only) + validation déterministe.
        Échec total -> CLARIFY (refuse plutôt qu'halluciner)."""
        system_prompt = build_planner_prompt(caps, current_datetime, user_display_name, session_context)
        llm = project.get_llm(PLANNER_LLM_ID)

        for attempt, use_json_mode in ((1, True), (2, False)):
            try:
                completion = llm.new_completion()
                if use_json_mode:
                    try:
                        completion.with_json_output(schema=PLANNER_JSON_SCHEMA)
                    except Exception:
                        pass
                completion.with_message(system_prompt, role="system")
                for m in history[-HISTORY_MAX_MESSAGES:]:
                    completion.with_message(m["content"][:HISTORY_MAX_CHARS], role=m["role"])
                completion.with_message(
                    'CURRENT QUESTION: "%s"\nReturn ONLY the JSON object.' % last_q, role="user")

                resp = completion.execute()
                try:
                    if resp.trace:
                        span.append_trace(resp.trace)
                        _acc_usage(total_usage, _sum_usage(_find_usage_metadata(resp.trace)))
                except Exception:
                    pass

                parsed = _safe_json_parse(getattr(resp, "text", None))
                validated = self._validate_plan(parsed, caps)
                if validated:
                    span.attributes["attempt"] = attempt
                    return validated
                span.attributes["attempt_%d_invalid" % attempt] = str(parsed)[:300]
            except Exception as e:
                logger.warning("Planner attempt %d failed: %s", attempt, e)
                span.attributes["attempt_%d_error" % attempt] = str(e)[:300]

        return {"intent": "CLARIFY", "language": "fr",
                "direct_answer": PLANNER_FALLBACK_CLARIFY["fr"], "steps": [], "_fallback": True}

    @staticmethod
    def _validate_plan(parsed, caps):
        """Validation déterministe : intents connus, étapes nettoyées, capacités réelles."""
        if not isinstance(parsed, dict):
            return None
        intent = parsed.get("intent")
        if intent not in ("BUSINESS", "GREETING", "CAPABILITIES", "CLARIFY",
                          "OUT_OF_SCOPE", "CAPABILITY_GAP", "CONCEPT"):
            return None

        steps, seen = [], set()
        # ORCH-10b: only BUSINESS plans may carry executable steps. Any steps a
        # non-business plan hallucinated are purged (never executed by accident).
        if intent == "BUSINESS":
            for s in (parsed.get("steps") or [])[:MAX_STEPS]:
                if not isinstance(s, dict):
                    continue
                cap_key, kind = s.get("capability"), s.get("kind")
                instruction = (s.get("instruction") or "").strip()
                if not instruction or cap_key not in caps or caps[cap_key]["kind"] != kind:
                    continue   # étape inventée ou incohérente -> ignorée
                sig = (kind, cap_key, instruction)
                if sig in seen:
                    continue
                seen.add(sig)
                steps.append({"kind": kind, "capability": cap_key, "instruction": instruction})

        if intent == "BUSINESS" and not steps:
            return None   # plan métier sans étape valide -> retry / fallback

        domain = parsed.get("domain")
        return {"intent": intent,
                "language": parsed.get("language", "fr"),
                "user_first_name": (parsed.get("user_first_name") or "").strip()[:40],
                "direct_answer": parsed.get("direct_answer"),
                "synthesis_hint": parsed.get("synthesis_hint"),
                "domain": domain if domain in BUSINESS_DOMAINS else None,
                "steps": steps}

    # ------------------------------------------------------------ SYNTHESIS
    def _synthesize(self, project, question, lang, hint, results, caps, trace, total_usage):
        """Rédige la réponse finale (streaming) à partir des résultats d'étapes."""
        label_key = "label_%s" % lang
        blocks = []
        for i, r in enumerate(results, start=1):
            label = caps.get(r["capability"], {}).get(label_key, r["capability"])
            output = r["output"] or "(empty)"
            if len(output) > STEP_RESULT_MAX_CHARS:
                # ORCH-09: never let the writer model present a silently truncated
                # result as complete — the marker instructs it to say so.
                output = output[:STEP_RESULT_MAX_CHARS] + STEP_RESULT_TRUNCATED_SUFFIX
            blocks.append("STEP %d — source: %s (%s) — status: %s\nInstruction: %s\nResult:\n%s"
                          % (i, label, r["kind"], r["status"], r["instruction"], output))
        user_block = ('USER QUESTION: "%s"\n%s\nSTEP RESULTS:\n\n%s'
                      % (question, ("SYNTHESIS HINT: %s\n" % hint) if hint else "",
                         "\n\n".join(blocks)))

        llm = project.get_llm(SYNTH_LLM_ID or PLANNER_LLM_ID)
        synth_trace = None
        with trace.subspan("orchestrator:synthesis") as sp:
            sp.inputs["question"] = question
            try:
                completion = llm.new_completion() \
                    .with_message(SYNTHESIS_PROMPT.replace("{language}", lang), role="system") \
                    .with_message(user_block, role="user")
                for chunk in completion.execute_streamed():
                    data = getattr(chunk, "data", {}) or {}
                    if _is_footer(chunk, data):           # ORCH-07
                        synth_trace = data.get("trace")
                        continue
                    ctype = data.get("type") or getattr(chunk, "type", None)
                    if ctype in ("content", "text"):
                        txt = data.get("text", "") or ""
                        if txt:
                            yield {"chunk": {"text": txt}}
            except Exception as e:
                logger.exception("Synthesis failed")
                # ORCH-03: str(e) stays in the span + logs; stable code in the event.
                sp.attributes["error"] = str(e)[:500]
                yield _ev_l("ERROR", lang, {"stage": "synthesis",
                                            "message": ERROR_CODE_SYNTHESIS_FAILED})
                # Dégradation propre : résultats bruts plutôt que rien.
                for i, r in enumerate(results, start=1):
                    if r["status"] == "ok":
                        yield {"chunk": {"text": "\n\n**Étape %d (%s)**\n%s"
                                         % (i, r["capability"], r["output"][:STEP_RESULT_MAX_CHARS])}}
            if synth_trace:
                try:
                    sp.append_trace(synth_trace)
                    _acc_usage(total_usage, _sum_usage(_find_usage_metadata(synth_trace)))
                except Exception:
                    pass

    # ---------------------------------------------------------------- INPUT
    @staticmethod
    def _extract_messages(query):
        """Historique user/assistant + dernière question + contexte system éventuel
        (messages role=system injectés par la webapp : identité, date, etc.)."""
        all_msgs = query.get("messages", []) or []
        system_context = "\n".join(
            m["content"] for m in all_msgs
            if m.get("role") == "system" and m.get("content"))
        msgs = [m for m in all_msgs
                if m.get("role") in ("user", "assistant") and m.get("content")]
        last_q = ""
        for m in reversed(msgs):
            if m["role"] == "user":
                last_q = m["content"]
                break
        history = msgs[:-1] if msgs and msgs[-1]["role"] == "user" else msgs
        return history, last_q, system_context
