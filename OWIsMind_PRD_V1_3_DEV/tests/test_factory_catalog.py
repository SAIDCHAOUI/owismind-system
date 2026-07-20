"""DSS-free contract tests for the append-only factory catalog.

The write path is exercised against a stubbed in-process ``dataiku.Dataset``
(same sys.modules technique as test_factory_doctor.py) plus a minimal ``pandas``
stand-in, because the real publish path follows the proven plugin append
pattern: dataiku.Dataset(..., ignore_flow=True) + spec_item["appendMode"] +
write_with_schema(DataFrame). The fake reproduces the real writer semantics
(a fresh session TRUNCATES unless appendMode is True), so these tests fail if
append mode is ever dropped.
"""

import json
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(os.path.dirname(_HERE), "project-library", "python")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from owismind_factory import catalog, hub, pipeline, registry  # noqa: E402
from owismind_factory.fctx import FactoryContext, PLANNED  # noqa: E402
from owismind_factory.spec import DomainSpec  # noqa: E402


def make_spec():
    return DomainSpec(
        domain="satisfaction",
        base_dataset="CX_Surveys",
        label_fr="Expert satisfaction",
        label_en="Satisfaction expert",
        planner_description="Owns satisfaction figures and survey trends.",
    )


def schema():
    return {"columns": [
        {"name": "survey_date", "type": "date"},
        {"name": "csat_score", "type": "double"},
    ]}


def wizard_config(description="Customer satisfaction score"):
    return {
        "entity_description": "Customer satisfaction survey responses.",
        "connection_key": "SQL_owi",
        "attributes": [
            {
                "column": "csat_score",
                "description": description,
                "synonyms": ["CSAT", "satisfaction rating"],
                "sample_values": ["SECRET_BUSINESS_VALUE"],
            },
        ],
        "join_hints": [{"column": "survey_date", "hint": "Date used for trends."}],
    }


class _ApiDataset(object):
    """Design-time dataikuapi DSSDataset stand-in.

    Deliberately WITHOUT write_schema / get_writer: the real dataikuapi handle
    has no in-process write method, so any code that tries to write through it
    fails here exactly like it would in DSS.
    """

    def __init__(self, name):
        self.name = name


class _CatalogProject(object):
    def __init__(self):
        self.datasets = {}
        self.create_calls = []

    def list_datasets(self):
        return [{"name": name} for name in self.datasets]

    def new_managed_dataset(self, name):
        project = self
        project.create_calls.append(name)

        class _Builder(object):
            def with_store_into(self, connection):
                self.connection = connection
                return self

            def create(self):
                dataset = _ApiDataset(name)
                project.datasets[name] = dataset
                return dataset

        return _Builder()

    def get_dataset(self, name):
        return self.datasets[name]


class _CatalogTableStore(object):
    """The physical catalog table shared by every fake dataiku.Dataset handle."""

    def __init__(self):
        self.rows = []
        self.schema = None
        self.write_calls = []


class _FakeWritableDataset(object):
    """In-process dataiku.Dataset stand-in with REAL writer semantics.

    Each handle starts with an empty spec_item, and write_with_schema on a
    handle whose spec_item lacks appendMode=True TRUNCATES the table first,
    exactly like a fresh DSS writer session. Dropping the append-mode line in
    the production code therefore loses the first generation here too.
    """

    def __init__(self, store):
        self._store = store
        self.spec_item = {}

    def write_schema(self, columns):
        self._store.schema = [dict(column) for column in columns]

    def write_with_schema(self, frame):
        append = self.spec_item.get("appendMode") is True
        self._store.write_calls.append({
            "append_mode": append,
            "columns": list(frame.columns),
            "row_count": len(frame.records),
        })
        if not append:
            self._store.rows = []
        self._store.rows.extend(dict(record) for record in frame.records)


class _FakeDataFrame(object):
    """Minimal pandas.DataFrame(records, columns=...) stand-in."""

    def __init__(self, data, columns=None):
        self.columns = list(columns or [])
        self.records = [{column: record.get(column, "") for column in self.columns}
                        for record in data]


def _make_fake_dataiku(store):
    module = types.ModuleType("dataiku")
    module.dataset_calls = []

    def _dataset(name, ignore_flow=False):
        module.dataset_calls.append({"name": name, "ignore_flow": ignore_flow})
        return _FakeWritableDataset(store)

    module.Dataset = _dataset
    return module


def _make_fake_pandas():
    module = types.ModuleType("pandas")
    module.DataFrame = _FakeDataFrame
    return module


class TestCatalogDataset(unittest.TestCase):
    def setUp(self):
        self.store = _CatalogTableStore()
        self._saved = {name: sys.modules.get(name) for name in ("dataiku", "pandas")}
        sys.modules["dataiku"] = _make_fake_dataiku(self.store)
        sys.modules["pandas"] = _make_fake_pandas()

    def tearDown(self):
        for name, saved in self._saved.items():
            if saved is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = saved

    def test_dry_run_plans_without_any_write(self):
        project = _CatalogProject()
        ctx = FactoryContext(project=project, dry_run=True)

        catalog.ensure_catalog_dataset(ctx, "SQL_owi")

        self.assertEqual(project.create_calls, [])
        self.assertNotIn(catalog.CATALOG_DATASET_NAME, project.datasets)
        self.assertEqual(sys.modules["dataiku"].dataset_calls, [])
        self.assertEqual(ctx.actions[0]["status"], PLANNED)

    def test_publication_appends_in_append_mode_and_keeps_both_generations(self):
        project = _CatalogProject()
        ctx = FactoryContext(project=project, dry_run=False)
        catalog.ensure_catalog_dataset(ctx, "SQL_owi")
        first = catalog.build_catalog_generation(
            make_spec(), wizard_config(), schema(), '"OWISMIND_DEV_cx_surveys"')
        second = catalog.build_catalog_generation(
            make_spec(), wizard_config("CSAT score for survey response"), schema(),
            '"OWISMIND_DEV_cx_surveys"')

        catalog.publish_catalog_generation(ctx, "satisfaction_expert", first)
        catalog.publish_catalog_generation(ctx, "satisfaction_expert", second)

        self.assertFalse(ctx.has_failures(),
                         "write path failed: %s" % json.dumps(ctx.actions))
        # Schema creation went through the in-process handle.
        self.assertEqual(self.store.schema, catalog.CATALOG_SCHEMA)
        # Every in-process handle is opened outside any recipe context.
        self.assertTrue(all(call["ignore_flow"] is True
                            for call in sys.modules["dataiku"].dataset_calls))

        calls = self.store.write_calls
        self.assertEqual(len(calls), 2)
        # appendMode must be set on spec_item BEFORE write_with_schema on EVERY
        # publication: the fake truncates otherwise, like a real writer session.
        self.assertTrue(all(call["append_mode"] for call in calls))
        expected_columns = [field["name"] for field in catalog.CATALOG_SCHEMA]
        self.assertTrue(all(call["columns"] == expected_columns for call in calls))

        stored = self.store.rows
        generation_ids = {row["generation_id"] for row in stored}
        self.assertEqual(generation_ids, {first["generation_id"], second["generation_id"]})
        self.assertEqual(len(stored), len(first["rows"]) + len(second["rows"]))
        self.assertTrue(all(row["physical_table"] == '"OWISMIND_DEV_cx_surveys"'
                            for row in stored))
        self.assertTrue(all(row["connection_name"] == "SQL_owi" for row in stored))


class TestCatalogGeneration(unittest.TestCase):
    def test_generation_id_is_deterministic_and_rows_exclude_business_values(self):
        original_today = catalog._generation_date
        catalog._generation_date = lambda: "20260717"
        try:
            first = catalog.build_catalog_generation(
                make_spec(), wizard_config(), schema(), '"OWISMIND_DEV_cx_surveys"')
            second = catalog.build_catalog_generation(
                make_spec(), wizard_config(), schema(), '"OWISMIND_DEV_cx_surveys"')
        finally:
            catalog._generation_date = original_today

        self.assertEqual(first["generation_id"], second["generation_id"])
        self.assertRegex(first["generation_id"], r"^satisfaction-20260717-\d{3}$")
        serialized = json.dumps(first, sort_keys=True)
        self.assertNotIn("SECRET_BUSINESS_VALUE", serialized)
        self.assertNotIn("sample_values", serialized)

    def test_generation_sequence_stays_three_digits_on_hash_edge(self):
        # This physical_table makes sha256(payload)[:8] % 1000 == 999, the highest
        # possible sequence: the id must stay exactly three digits (the old
        # "% 1000 + 1" formula emitted 1000 here and broke the NNN contract).
        original_today = catalog._generation_date
        catalog._generation_date = lambda: "20260717"
        try:
            generation = catalog.build_catalog_generation(
                make_spec(), wizard_config(), schema(),
                '"OWISMIND_DEV_cx_surveys_1200"')
        finally:
            catalog._generation_date = original_today

        self.assertEqual(generation["generation_id"], "satisfaction-20260717-999")

    def test_prompt_rows_keep_search_text_but_strip_server_only_references(self):
        generation = catalog.build_catalog_generation(
            make_spec(), wizard_config(), schema(), '"OWISMIND_DEV_cx_surveys"')

        base_row = generation["rows"][0]
        prompt_rows = catalog.searchable_catalog_rows(generation)

        self.assertIn("physical_table", base_row)
        self.assertIn("connection_name", base_row)
        self.assertTrue(prompt_rows[0]["search_text"])
        # search_text is normalized once at build time and passes through as-is.
        self.assertEqual(prompt_rows[0]["search_text"], base_row["search_text"])
        self.assertNotIn("physical_table", prompt_rows[0])
        self.assertNotIn("connection_name", prompt_rows[0])
        self.assertNotIn("OWISMIND_DEV", json.dumps(prompt_rows))
        self.assertNotIn("SQL_owi", json.dumps(prompt_rows))


class TestCatalogRegistryAndPipeline(unittest.TestCase):
    def test_legacy_registry_entry_stays_valid_and_catalog_fields_are_optional(self):
        legacy = registry.capability_entry(make_spec(), "agent:AbCd1234")
        self.assertNotIn("catalog_generation", legacy)
        self.assertEqual(hub.validate_capabilities({"satisfaction_expert": legacy}), [])

        enriched = registry.capability_entry(
            make_spec(), "agent:AbCd1234", catalog_generation="satisfaction-20260717-001",
            catalog_dataset=catalog.CATALOG_DATASET_NAME, connection_key="SQL_owi")
        self.assertEqual(enriched["catalog_generation"], "satisfaction-20260717-001")
        self.assertEqual(enriched["catalog_dataset"], catalog.CATALOG_DATASET_NAME)
        self.assertEqual(enriched["connection_key"], "SQL_owi")

    def test_pipeline_exposes_catalog_step_after_capability_before_smoke(self):
        self.assertLess(pipeline.STEP_NAMES.index("capability"),
                        pipeline.STEP_NAMES.index("catalog"))
        self.assertLess(pipeline.STEP_NAMES.index("catalog"),
                        pipeline.STEP_NAMES.index("smoke"))


if __name__ == "__main__":
    unittest.main()
