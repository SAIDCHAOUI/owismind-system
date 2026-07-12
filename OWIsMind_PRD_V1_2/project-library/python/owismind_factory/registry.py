"""Capability entry builder: DomainSpec + created ids -> orchestrator CAPABILITIES entry.

The entry shape mirrors agents/OWIsMind_orchestrator.py CAPABILITIES and
registry.json. block_labels / tool_labels carry the FROZEN keys of the sub-agent
collaboration dialect (KNOWN_BLOCK_IDS / KNOWN_TOOL_NAMES): the engine template
guarantees every generated sub-agent speaks the same dialect, so the labels are
constant per language and only the human wording of the domain changes.
"""

# Frozen sub-agent dialect (never rename, only add). Kept in sync with the
# engine template by tests/test_factory_registry.py.
KNOWN_BLOCK_IDS = ("resolve", "run_sql", "format_output",
                   "clarify_user", "out_of_scope_msg", "about_data")
KNOWN_TOOL_NAMES = ("resolve_filter_value", "dataset_sql_query")

# French labels carry their accents: they are user-visible timeline strings and
# MUST match the orchestrator's embedded CAPABILITIES labels byte for byte
# (agents/OWIsMind_orchestrator.py), otherwise factory-created domains would
# render degraded ASCII labels next to the accented live ones.
_BLOCK_LABELS = {
    "resolve": {"fr": "analyse de la question", "en": "understanding the question"},
    "run_sql": {"fr": "interrogation des données", "en": "querying the data"},
    "format_output": {"fr": "mise en forme du résultat", "en": "formatting the result"},
    "clarify_user": {"fr": "demande de précision", "en": "asking for clarification"},
    "out_of_scope_msg": None,
    "about_data": {"fr": "description des données", "en": "describing the data"},
}
_TOOL_LABELS = {
    "resolve_filter_value": {"fr": "résolution des noms exacts", "en": "resolving exact names"},
    "dataset_sql_query": {"fr": "génération et exécution du SQL", "en": "generating and running SQL"},
}


def capability_entry(spec, agent_id, source_url=""):
    """Build the CAPABILITIES entry for a new specialist.

    :param spec: :class:`owismind_factory.spec.DomainSpec`
    :param str agent_id: the live Code Agent id, ``agent:XXXX`` form.
    :param str source_url: optional deep link to the base dataset in DSS.
    """
    agent_id = str(agent_id or "")
    if agent_id and not agent_id.startswith("agent:"):
        agent_id = "agent:" + agent_id
    return {
        "kind": "agent",
        "agent_id": agent_id,
        "domain": spec.domain,
        "label_fr": spec.label_fr,
        "label_en": spec.label_en,
        "tool_name": spec.orchestrator_tool_name,
        "planner_description": spec.planner_description,
        "block_labels": {k: (dict(v) if isinstance(v, dict) else v) for k, v in _BLOCK_LABELS.items()},
        "tool_labels": {k: dict(v) for k, v in _TOOL_LABELS.items()},
        "dataset_label_fr": "Base %s (%s)" % (spec.label_fr, spec.base_dataset),
        "dataset_label_en": "%s base (%s)" % (spec.label_en, spec.base_dataset),
        "source_url": source_url or "",
        "lookup_dataset": spec.base_dataset,
        "lookup_catalog": spec.value_catalog_dataset,
        "lookup_search_columns": list(spec.lookup_search_columns),
        "pass_context": True,
        # New domains ship DISABLED: flip to True after the smoke tests pass.
        "enabled": False,
    }
