"""DSS-free contract tests for the append-only factory catalog."""

import json
import os
import sys
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


class _Writer(object):
    def __init__(self, dataset):
        self.dataset = dataset
        self.closed = False

    def write_row_dict(self, row):
        self.dataset.rows.append(dict(row))

    def close(self):
        self.closed = True


class _Dataset(object):
    def __init__(self, name):
        self.name = name
        self.rows = []
        self.schema = None

    def write_schema(self, schema_value):
        self.schema = schema_value

    def get_writer(self):
        return _Writer(self)


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
                dataset = _Dataset(name)
                project.datasets[name] = dataset
                return dataset

        return _Builder()

    def get_dataset(self, name):
        return self.datasets[name]


class TestCatalogDataset(unittest.TestCase):
    def test_dry_run_plans_without_any_write(self):
        project = _CatalogProject()
        ctx = FactoryContext(project=project, dry_run=True)

        catalog.ensure_catalog_dataset(ctx, "SQL_owi")

        self.assertEqual(project.create_calls, [])
        self.assertNotIn(catalog.CATALOG_DATASET_NAME, project.datasets)
        self.assertEqual(ctx.actions[0]["status"], PLANNED)

    def test_publication_is_append_only_for_two_generations(self):
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

        stored = project.datasets[catalog.CATALOG_DATASET_NAME].rows
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

    def test_prompt_rows_keep_search_text_but_strip_server_only_references(self):
        generation = catalog.build_catalog_generation(
            make_spec(), wizard_config(), schema(), '"OWISMIND_DEV_cx_surveys"')

        base_row = generation["rows"][0]
        prompt_rows = catalog.searchable_catalog_rows(generation)

        self.assertIn("physical_table", base_row)
        self.assertIn("connection_name", base_row)
        self.assertTrue(prompt_rows[0]["search_text"])
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
