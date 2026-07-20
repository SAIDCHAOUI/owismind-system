"""DomainSpec: the validated description of a new specialist domain.

One DomainSpec drives the whole pipeline. Everything else (dataset names, recipe
names, scenario name, capability key, tool name) is DERIVED here so the naming
conventions live in exactly one place.

Naming conventions (aligned with the live revenue/tickets domains):
- knowledge datasets: ``<base>_profile``, ``<base>_value_index``, ``<base>_value_catalog``
- recipes: ``compute_<output dataset>``
- scenario: ``Refresh_<Domain>``
- capability key: ``<domain>_expert`` and orchestrator tool ``ask_<domain>_expert``

PostgreSQL identifiers are capped at 63 bytes (lesson L110): validate() enforces
a conservative headroom on every derived physical-ish name.
"""

import re

# Conservative cap: project-key prefix + "_" + dataset name must fit PostgreSQL's
# 63-byte identifier limit. Project keys observed are ~20 chars, keep headroom.
MAX_DATASET_NAME = 40

_DOMAIN_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_DATASET_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class SpecError(ValueError):
    """Raised when a DomainSpec is invalid (message says exactly what to fix)."""


class DomainSpec(object):
    """Description of one new specialist domain.

    :param str domain: snake_case business domain key (e.g. ``satisfaction``).
    :param str base_dataset: name of the base dataset in the project. If it does
        not exist yet, provide ``source`` so the factory can import it.
    :param dict source: optional ``{"connection": ..., "schema": ..., "table": ...,
        "catalog": ...}`` describing the external SQL table to import as
        ``base_dataset`` (catalog optional).
    :param str label_fr / label_en: human labels for the capability.
    :param str zone_name: Flow zone (defaults to ``<Domain>_Expert``).
    :param str planner_description: routing description shown to the orchestrator
        model. Usually produced by the wizard; a safe generic fallback is derived.
    :param list lookup_search_columns: allowlist of text columns for the fast
        attribute_lookup (empty list = search every text column).
    """

    def __init__(self, domain, base_dataset, label_fr, label_en,
                 source=None, zone_name=None, planner_description=None,
                 lookup_search_columns=None):
        self.domain = (domain or "").strip()
        self.base_dataset = (base_dataset or "").strip()
        self.label_fr = (label_fr or "").strip()
        self.label_en = (label_en or "").strip()
        self.source = dict(source) if source else None
        self.zone_name = (zone_name or "").strip() or self._default_zone_name()
        self.planner_description = (planner_description or "").strip() or self._default_planner_description()
        self.lookup_search_columns = list(lookup_search_columns or [])
        self.validate()

    # ------------------------------------------------------------------ derived

    def _default_zone_name(self):
        return "%s_Expert" % self.domain.title().replace("_", "")

    def _default_planner_description(self):
        # Generic but honest routing text; the wizard replaces it with a rich one.
        return ("The OWI %s expert. Owns ALL figures of the %s dataset: totals, "
                "breakdowns, rankings, trends over time, distinct values, and "
                "'what does this data contain' questions. Route here ANY question "
                "about %s." % (self.domain, self.base_dataset, self.domain))

    @property
    def profile_dataset(self):
        return "%s_profile" % self.base_dataset

    @property
    def value_index_dataset(self):
        return "%s_value_index" % self.base_dataset

    @property
    def value_catalog_dataset(self):
        return "%s_value_catalog" % self.base_dataset

    @property
    def knowledge_datasets(self):
        return [self.profile_dataset, self.value_index_dataset, self.value_catalog_dataset]

    def recipe_name(self, output_dataset):
        return "compute_%s" % output_dataset

    @property
    def scenario_name(self):
        return "Refresh_%s" % self.domain.title().replace("_", "")

    @property
    def semantic_model_name(self):
        return "%s_Semantic_Model" % self.base_dataset

    @property
    def semantic_tool_name(self):
        return "%s_semantic_query" % self.domain

    @property
    def capability_key(self):
        return "%s_expert" % self.domain

    @property
    def orchestrator_tool_name(self):
        return "ask_%s_expert" % self.domain

    @property
    def agent_name(self):
        return "%s_expert" % self.domain.title().replace("_", "")

    # ------------------------------------------------------------------ validate

    def validate(self):
        if not _DOMAIN_RE.match(self.domain):
            raise SpecError("domain must be snake_case ([a-z][a-z0-9_]{1,30}), got %r" % self.domain)
        if not _DATASET_RE.match(self.base_dataset or ""):
            raise SpecError("base_dataset must be a valid dataset name, got %r" % self.base_dataset)
        if not self.label_fr or not self.label_en:
            raise SpecError("label_fr and label_en are required")
        for name in self.knowledge_datasets:
            if len(name) > MAX_DATASET_NAME:
                raise SpecError(
                    "derived dataset name %r is longer than %d chars: the physical "
                    "PostgreSQL table (project key prefix + name) would risk the 63-byte "
                    "identifier cap (L110). Use a shorter base_dataset." % (name, MAX_DATASET_NAME))
        if self.source is not None:
            for key in ("connection", "table"):
                if not self.source.get(key):
                    raise SpecError("source needs at least 'connection' and 'table', missing %r" % key)
        return True

    # ------------------------------------------------------------------ preflight

    def preflight(self, existing_capability_keys=None, existing_domains=None):
        """Return non-blocking WARNING strings about likely-suboptimal choices.

        Unlike :meth:`validate`, this NEVER raises: the spec is legal but some
        options will make the resulting agent slower, harder to route, or risk a
        name collision. The caller supplies the already-registered
        capability keys / domains (the factory knows them, the spec does not).

        :param existing_capability_keys: iterable of capability keys already
            registered (used to detect a collision on this spec's key).
        :param existing_domains: iterable of domain keys already registered.
        :returns: list of human-readable warning strings (empty = all clear).
        """
        warnings = []
        caps = set(existing_capability_keys or [])
        domains = set(existing_domains or [])

        if self.capability_key in caps:
            warnings.append(
                "capability_key %r already exists: creating this domain would "
                "collide with a registered capability (only one enabled capability "
                "per business domain is allowed)." % self.capability_key)
        if self.domain in domains:
            warnings.append(
                "domain %r already exists: pick a distinct domain key to avoid "
                "overwriting the existing specialist." % self.domain)

        if not self.lookup_search_columns:
            warnings.append(
                "lookup_search_columns is empty: attribute_lookup will scan EVERY "
                "text column of %r on each read, which is slower. List the few "
                "columns users actually search to speed it up." % self.base_dataset)

        for name in self.knowledge_datasets:
            headroom = MAX_DATASET_NAME - len(name)
            if 0 <= headroom <= 5:
                warnings.append(
                    "derived dataset name %r is %d char(s) from the %d cap: little "
                    "headroom before the PostgreSQL 63-byte identifier risk (L110). "
                    "Consider a shorter base_dataset." % (name, headroom, MAX_DATASET_NAME))

        if self.label_fr and self.label_fr == self.label_en:
            warnings.append(
                "label_fr and label_en are identical (%r): probable copy-paste, "
                "give each language its own label." % self.label_fr)

        if self.planner_description == self._default_planner_description():
            warnings.append(
                "planner_description is the generic derived fallback: it is a weak "
                "routing signal and the orchestrator model will route poorly. Use "
                "the wizard's planner_description instead.")

        return warnings

    # ------------------------------------------------------------------ (de)ser

    def to_dict(self):
        return {
            "domain": self.domain,
            "base_dataset": self.base_dataset,
            "label_fr": self.label_fr,
            "label_en": self.label_en,
            "source": dict(self.source) if self.source else None,
            "zone_name": self.zone_name,
            "planner_description": self.planner_description,
            "lookup_search_columns": list(self.lookup_search_columns),
        }

    @classmethod
    def from_dict(cls, data):
        data = dict(data or {})
        return cls(
            domain=data.get("domain"),
            base_dataset=data.get("base_dataset"),
            label_fr=data.get("label_fr"),
            label_en=data.get("label_en"),
            source=data.get("source"),
            zone_name=data.get("zone_name"),
            planner_description=data.get("planner_description"),
            lookup_search_columns=data.get("lookup_search_columns"),
        )
