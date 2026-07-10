"""Semantic wizard: LLM-assisted authoring of the semantic model configuration.

The wizard reads the domain's PROFILE dataset (the aggregated business brain the
Flow recipes already build: schema, stats, enum values, synonyms; NEVER raw
rows), then asks a strong LLM (Sonnet through the LLM Mesh, native completion
API with a forced JSON schema) to draft:

- entity + attribute descriptions and which columns are resolvable (groundable),
- candidate metrics / filters / glossary terms with synonyms,
- the SQL generation instructions,
- candidate golden queries (SQL against the __TABLE__ placeholder),
- profile override rows (the {key, field, value} contract of the profile recipe),
- and, crucially, CLARIFYING QUESTIONS for the human (default metric, distinct
  count key, time column, units, hierarchies): the exact traps met on the
  tickets domain (COUNT(DISTINCT id), minutes, creationDate).

The human answers, the wizard re-drafts with the answers embedded. The output
is applied by semantic_builder.apply_config(); auto-generation is a starting
point, the official docs themselves say it takes you about 80 percent of the
way, so the human reviews every section (Playground + repo dump) before the
capability is enabled.

Bounded cost: ONE completion per draft call, aggregated metadata only.
"""

import json

MAX_DIGEST_CHARS = 12000
MAX_PROFILE_ROWS = 400

# JSON schema forced on the completion (with_json_output). Keep it permissive
# on nested content (the model fills text) but strict on the envelope.
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "entity_name": {"type": "string"},
        "entity_description": {"type": "string"},
        "primary_key": {"type": "array", "items": {"type": "string"}},
        "attributes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "column": {"type": "string"},
                    "description": {"type": "string"},
                    "resolvable": {"type": "boolean"},
                },
                "required": ["column", "description"],
            },
        },
        "metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "pseudo_sql": {"type": "string"},
                    "llm_instructions": {"type": "string"},
                },
                "required": ["name", "pseudo_sql"],
            },
        },
        "filters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "pseudo_sql": {"type": "string"},
                },
                "required": ["name", "pseudo_sql"],
            },
        },
        "glossary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "synonyms": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["term"],
            },
        },
        "instructions": {"type": "string"},
        "golden_queries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "question": {"type": "string"},
                    "sql": {"type": "string"},
                },
                "required": ["question"],
            },
        },
        "planner_description": {"type": "string"},
        "profile_overrides": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "field": {"type": "string"},
                    "value": {"type": "string"},
                },
                "required": ["key", "field", "value"],
            },
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "question_fr": {"type": "string"},
                    "why": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "default": {"type": "string"},
                },
                "required": ["id", "question_fr", "why"],
            },
        },
    },
    "required": ["entity_description", "attributes", "metrics",
                 "instructions", "planner_description", "questions"],
}


# ---------------------------------------------------------------- profile input

def read_profile(profile_dataset, project_key=None):
    """Read the {key, payload} profile rows through the in-DSS Dataset API.

    Returns {key: payload_dict}. Never raises: an empty dict means the profile
    is missing or unreadable (the caller reports it).
    """
    try:
        import dataiku
        ds = dataiku.Dataset(profile_dataset, project_key=project_key) if project_key \
            else dataiku.Dataset(profile_dataset)
        out = {}
        count = 0
        schema_names = [c.get("name") for c in (ds.read_schema() or [])]
        for row in ds.iter_rows():
            values = dict(zip(schema_names, list(row))) if schema_names else {}
            key = values.get("key")
            payload = values.get("payload")
            if key is None:
                continue
            try:
                out[str(key)] = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except Exception:
                out[str(key)] = {"raw": str(payload)[:500]}
            count += 1
            if count >= MAX_PROFILE_ROWS:
                break
        return out
    except Exception:
        return {}


def build_profile_digest(profile, base_dataset):
    """Compact, size-capped text digest of the profile for the LLM."""
    lines = ["DATASET: %s" % base_dataset]
    dataset_level = profile.get("__dataset__") or {}
    if dataset_level:
        lines.append("DATASET PROFILE: %s" % json.dumps(dataset_level, ensure_ascii=False)[:2500])
    for key, payload in profile.items():
        if key == "__dataset__":
            continue
        lines.append("COLUMN %s: %s" % (key, json.dumps(payload, ensure_ascii=False)[:900]))
    digest = "\n".join(lines)
    if len(digest) > MAX_DIGEST_CHARS:
        digest = digest[:MAX_DIGEST_CHARS] + "\n[digest truncated]"
    return digest


# --------------------------------------------------------------------- prompting

def build_draft_prompt(digest, base_dataset, domain, answers=None, extra_context=None):
    """PURE function building the single wizard prompt (unit-tested without DSS)."""
    parts = []
    parts.append(
        "You are a senior data engineer configuring a Dataiku SEMANTIC MODEL for a "
        "text-to-SQL agent tool. You receive an aggregated PROFILE of one dataset "
        "(schema, stats, enumerated values, synonyms). Draft the semantic model "
        "configuration as JSON following the imposed schema. Rules:\n"
        "- Use ONLY column names and values present in the profile. NEVER invent a "
        "column, a value or a business fact.\n"
        "- Descriptions: precise, business-oriented, in English, stating units and "
        "caveats when the profile shows them.\n"
        "- resolvable=true ONLY for columns whose exact values a user would name "
        "(customer names, categories, statuses, product names); false for ids used "
        "purely as keys, dates, amounts and free text.\n"
        "- Metrics: pseudo-SQL aggregations (e.g. SUM(amount), COUNT(DISTINCT id)). "
        "If row duplication or snapshots are plausible, PREFER asking a clarifying "
        "question over guessing the aggregation.\n"
        "- instructions: the model-level SQL generation guidance (markdown): one "
        "physical table never JOIN, default scenario and time semantics IF the "
        "profile supports them, display rules. State only what the profile proves; "
        "put open points into the clarifying questions instead.\n"
        "- golden_queries: 3 to 6 typical questions. Write the sql against the "
        "placeholder table __TABLE__ (it is substituted later); if unsure of exact "
        "values or semantics, provide the question WITHOUT sql.\n"
        "- planner_description: 3 to 5 sentences telling an orchestrator model when "
        "to route a user question to this dataset's expert. Follow this shape: what "
        "the expert owns, which figures it computes, which keywords route here.\n"
        "- profile_overrides: rows for the {key, field, value} overrides dataset "
        "(field in: metrics, default_metric, time, display_column, synonyms; value "
        "is the JSON or plain value as a string). Emit only what you are confident "
        "about; everything else becomes a question.\n"
        "- questions: 3 to 8 clarifying questions IN FRENCH for the human curator "
        "(id snake_case, why in French). ALWAYS cover: the default metric and its "
        "aggregation key (distinct or not), the default time column, units of "
        "numeric columns, and any suspected hierarchy between columns.\n"
        "- NEVER use em dashes or en dashes anywhere in any text you produce.\n")
    parts.append("BUSINESS DOMAIN: %s" % domain)
    parts.append("PROFILE DIGEST:\n%s" % digest)
    if extra_context:
        parts.append("EXTRA CONTEXT FROM THE TEAM:\n%s" % str(extra_context)[:2000])
    if answers:
        parts.append(
            "HUMAN ANSWERS to your previous clarifying questions (authoritative, "
            "integrate them and only ask NEW questions if something important "
            "remains):\n%s" % json.dumps(answers, ensure_ascii=False, indent=1)[:3000])
    return "\n\n".join(parts)


# -------------------------------------------------------------------- LLM call

def _parse_llm_json(resp):
    data = getattr(resp, "json", None)
    if isinstance(data, dict):
        return data
    text = getattr(resp, "text", None) or ""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned)
    except Exception:
        return None


def draft_model_config(project, profile_dataset, answers=None, llm_id=None,
                       base_dataset=None, domain=None, extra_context=None):
    """One bounded LLM call: profile digest -> draft config + questions.

    Returns the config dict (DRAFT_SCHEMA shape) or {"error": ...}.
    """
    from . import hub
    if llm_id is None:
        llm_id = hub.get_settings(project).get("llm_sonnet")
    base_dataset = base_dataset or (profile_dataset or "").replace("_profile", "")
    domain = domain or base_dataset

    profile = read_profile(profile_dataset, project_key=getattr(project, "project_key", None))
    if not profile:
        return {"error": "profile dataset %r is empty or unreadable: run the profile "
                         "recipe first (the wizard needs the business brain)" % profile_dataset}

    digest = build_profile_digest(profile, base_dataset)
    prompt = build_draft_prompt(digest, base_dataset, domain,
                                answers=answers, extra_context=extra_context)

    completion = project.get_llm(llm_id).new_completion()
    completion.with_message(prompt)
    try:
        completion.settings["temperature"] = 0
    except Exception:
        pass
    try:
        completion.with_json_output(schema=DRAFT_SCHEMA)
    except Exception:
        # Older Mesh builds: fall back to free text + defensive parse below.
        pass
    resp = completion.execute()
    config = _parse_llm_json(resp)
    if not isinstance(config, dict):
        return {"error": "the LLM did not return parseable JSON (llm_id %s)" % llm_id}
    config.setdefault("questions", [])
    if answers:
        config = merge_answers(config, answers)
    return config


# ------------------------------------------------------------- deterministic ops

def merge_answers(config, answers):
    """Deterministically fold well-known answer ids into the config.

    Free-form answers are kept under config['answers'] (they were already fed to
    the re-draft prompt); a few structured ids are applied directly so a purely
    deterministic pass works even without a second LLM call.
    """
    config = dict(config or {})
    answers = dict(answers or {})
    config["answers"] = answers

    time_column = answers.get("time_column") or answers.get("default_time_column")
    if time_column:
        overrides = list(config.get("profile_overrides") or [])
        overrides = [o for o in overrides if not (o.get("key") == "__dataset__" and o.get("field") == "time")]
        overrides.append({"key": "__dataset__", "field": "time",
                          "value": json.dumps({"column": time_column, "format": "date"})})
        config["profile_overrides"] = overrides

    default_metric = answers.get("default_metric")
    if default_metric:
        overrides = list(config.get("profile_overrides") or [])
        overrides = [o for o in overrides if not (o.get("key") == "__dataset__" and o.get("field") == "default_metric")]
        overrides.append({"key": "__dataset__", "field": "default_metric", "value": str(default_metric)})
        config["profile_overrides"] = overrides

    primary_key = answers.get("primary_key") or answers.get("distinct_key")
    if primary_key:
        config["primary_key"] = [primary_key] if isinstance(primary_key, str) else list(primary_key)

    return config


def substitute_golden_tables(config, physical_table):
    """Replace the __TABLE__ placeholder in golden query SQL with the real table.

    :param str physical_table: fully quoted literal, e.g. '"PROJ_key_table"'.
    Golden queries left without SQL are returned separately as curation TODOs.
    """
    ready, todo = [], []
    for gq in (config or {}).get("golden_queries") or []:
        sql = gq.get("sql") or gq.get("generatedSql") or ""
        if sql and "__TABLE__" in sql and physical_table:
            ready.append({"name": gq.get("name") or "", "question": gq.get("question") or "",
                          "generatedSql": sql.replace("__TABLE__", physical_table)})
        elif sql and physical_table is None:
            todo.append(gq)
        elif sql:
            ready.append({"name": gq.get("name") or "", "question": gq.get("question") or "",
                          "generatedSql": sql})
        else:
            todo.append(gq)
    return ready, todo


def get_physical_table(project, dataset_name):
    """Best-effort quoted physical table literal of a dataset (None if unknown)."""
    try:
        settings = project.get_dataset(dataset_name).get_settings()
        raw = settings.get_raw() if hasattr(settings, "get_raw") else {}
        params = raw.get("params") or {}
        table = params.get("table") or ""
        if not table:
            return None
        table = table.replace("${projectKey}", getattr(project, "project_key", ""))
        return '"%s"' % table
    except Exception:
        return None
