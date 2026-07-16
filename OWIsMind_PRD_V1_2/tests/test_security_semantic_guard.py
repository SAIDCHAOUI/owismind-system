"""Security tests: semantic model ownership marker + anti-overwrite guard.

Two independent audits (2026-07) converged on the same danger: apply_config
rewrote the ACTIVE version of any model matched by name, so (a) a name
collision with a model foreign to the factory got silently modified and (b) a
re-run with a stale wizard config erased human curation without any backup.
This suite locks the fix: seed_model stamps an ownership marker, apply_config
refuses to touch unmarked pre-existing models, and marked ones are only
mutated after a pre-apply version backup succeeded.

Everything runs on fakes: no dataiku import, no DSS. Reuses the fake-project
style and the sys.path bootstrap of test_factory_hardening.py.
"""

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "project-library", "python"))

from owismind_factory import pipeline, semantic_builder  # noqa: E402
from owismind_factory.fctx import FactoryContext, DONE, MANUAL, PLANNED, SKIPPED  # noqa: E402
from owismind_factory.spec import DomainSpec  # noqa: E402


def make_spec(**overrides):
    kwargs = dict(domain="satisfaction", base_dataset="CX_Surveys",
                  label_fr="Satisfaction", label_en="Customer satisfaction")
    kwargs.update(overrides)
    return DomainSpec(**kwargs)


def statuses(ctx):
    return {a["step"]: a["status"] for a in ctx.actions}


def detail_of(ctx, step):
    return next(a["detail"] for a in ctx.actions if a["step"] == step)


# ------------------------------------------------------------------ model fakes

class _VersionSettings(object):
    def __init__(self, raw):
        self._raw = raw
        self.saved = False

    def get_raw(self):
        return self._raw

    def save(self):
        self.saved = True


class _Version(object):
    def __init__(self, settings):
        self._settings = settings

    def get_settings(self):
        return self._settings


class _GuardModel(object):
    """Semantic model fake with a version store; new_version can be broken."""

    def __init__(self, active_raw, fail_backup=False):
        self.versions = {"v1": _VersionSettings(active_raw)}
        self.created_versions = []
        self.active_pins = []
        self._fail_backup = fail_backup

    def get_active_version_id(self):
        return "v1"

    def set_active_version_id(self, vid):
        # apply_config re-pins the original active version after the backup
        # (new_version MAY activate the new version on some DSS builds).
        self.active_pins.append(vid)

    def get_version(self, vid):
        return _Version(self.versions[vid])

    def list_versions(self):
        return [{"versionId": vid} for vid in self.versions]

    def new_version(self, vid):
        if self._fail_backup:
            raise RuntimeError("new_version exploded")
        settings = _VersionSettings({})
        self.versions[vid] = settings
        self.created_versions.append(vid)
        return settings


class _GuardProject(object):
    def __init__(self, model):
        self._model = model

    def get_semantic_model(self, model_id):
        return self._model


def curated_raw(marker=True):
    raw = {"entities": [{"name": "e", "attributes": [],
                         "metrics": [{"name": "old_metric"}],
                         "filters": [{"name": "old_filter"}]}],
           "goldenQueries": [{"name": "old_gq"}],
           "glossaryTerms": [{"term": "old"}],
           "sqlGenerationConfig": {"instructions": "OLD"}}
    if marker:
        raw["privateEditorData"] = {"owismindFactory": {"domain": "satisfaction"}}
    return raw


NEW_CONFIG = {"metrics": [{"name": "new_metric", "pseudo_sql": "SUM(x)"}]}


# ----------------------------------------------------------- apply_config guard

class TestApplyConfigOwnershipGuard(unittest.TestCase):
    def test_unmarked_preexisting_model_is_manual_and_untouched(self):
        raw = curated_raw(marker=False)
        before = copy.deepcopy(raw)
        model = _GuardModel(raw)
        ctx = FactoryContext(project=_GuardProject(model), dry_run=False)
        result = semantic_builder.apply_config(ctx, "m1", NEW_CONFIG)
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["semantic_config"], MANUAL)
        self.assertIn("NOT created by the factory", detail_of(ctx, "semantic_config"))
        # zero mutation: no save, no backup version, raw byte-identical.
        self.assertEqual(raw, before)
        self.assertFalse(model.versions["v1"].saved)
        self.assertEqual(model.created_versions, [])

    def test_marked_model_gets_backup_then_config(self):
        raw = curated_raw()
        model = _GuardModel(raw)
        ctx = FactoryContext(project=_GuardProject(model), dry_run=False)
        result = semantic_builder.apply_config(ctx, "m1", NEW_CONFIG)
        self.assertEqual(result, "m1")
        self.assertEqual(statuses(ctx)["semantic_config"], DONE)
        # the original active version was re-pinned right after the backup.
        self.assertEqual(model.active_pins, ["v1"])
        # the backup version holds the PRE-apply curation and was saved.
        self.assertEqual(model.created_versions, ["pre-apply-backup-1"])
        backup = model.versions["pre-apply-backup-1"]
        self.assertTrue(backup.saved)
        self.assertEqual(backup.get_raw()["entities"][0]["metrics"],
                         [{"name": "old_metric"}])
        # the active version received the new config.
        self.assertEqual(raw["entities"][0]["metrics"][0]["name"], "new_metric")

    def test_backup_counter_skips_taken_names(self):
        raw = curated_raw()
        model = _GuardModel(raw)
        model.versions["pre-apply-backup-1"] = _VersionSettings({"old": "backup"})
        ctx = FactoryContext(project=_GuardProject(model), dry_run=False)
        semantic_builder.apply_config(ctx, "m1", NEW_CONFIG)
        self.assertEqual(model.created_versions, ["pre-apply-backup-2"])
        # the previous backup was not overwritten.
        self.assertEqual(model.versions["pre-apply-backup-1"].get_raw(),
                         {"old": "backup"})

    def test_backup_failure_is_manual_and_untouched(self):
        raw = curated_raw()
        before = copy.deepcopy(raw)
        model = _GuardModel(raw, fail_backup=True)
        ctx = FactoryContext(project=_GuardProject(model), dry_run=False)
        result = semantic_builder.apply_config(ctx, "m1", NEW_CONFIG)
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["semantic_config"], MANUAL)
        self.assertIn("backup", detail_of(ctx, "semantic_config"))
        self.assertEqual(raw, before)
        self.assertFalse(model.versions["v1"].saved)

    def test_unreadable_model_is_manual_and_untouched(self):
        class _Raising(object):
            def get_semantic_model(self, model_id):
                raise RuntimeError("HTTP 500")

        ctx = FactoryContext(project=_Raising(), dry_run=False)
        result = semantic_builder.apply_config(ctx, "m1", NEW_CONFIG)
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["semantic_config"], MANUAL)
        self.assertIn("ownership", detail_of(ctx, "semantic_config"))

    def test_created_this_run_skips_guard_and_backup(self):
        # A model seeded by THIS run is empty: current behavior unchanged, no
        # marker check, no backup version.
        raw = curated_raw(marker=False)
        model = _GuardModel(raw)
        ctx = FactoryContext(project=_GuardProject(model), dry_run=False)
        result = semantic_builder.apply_config(ctx, "m1", NEW_CONFIG,
                                               created_this_run=True)
        self.assertEqual(result, "m1")
        self.assertEqual(statuses(ctx)["semantic_config"], DONE)
        self.assertEqual(model.created_versions, [])
        self.assertEqual(raw["entities"][0]["metrics"][0]["name"], "new_metric")

    def test_dry_run_plans_without_reading_dss(self):
        # The guard must not break dry-run: nothing is read, the step is planned.
        class _Untouchable(object):
            def get_semantic_model(self, model_id):
                raise AssertionError("dry-run must not read DSS")

        ctx = FactoryContext(project=_Untouchable(), dry_run=True)
        result = semantic_builder.apply_config(ctx, "m1", NEW_CONFIG)
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["semantic_config"], PLANNED)


# ------------------------------------------------------------ seed_model marker

class _Dataset(object):
    def get_schema(self):
        return {"columns": [{"name": "col_a", "type": "string"}]}


class _NewModel(object):
    def __init__(self):
        self.id = "new_model_1"
        self.settings = _VersionSettings({})
        self.active = None

    def new_version(self, name):
        return self.settings

    def set_active_version_id(self, vid):
        self.active = vid


class _SeedProject(object):
    project_key = "OWISMIND_TEST"

    def __init__(self, existing_model_id=None):
        self.new_model = _NewModel()
        self._existing_model_id = existing_model_id

    def list_semantic_models(self):
        if self._existing_model_id:
            return [_ListedModel(self._existing_model_id, "CX_Surveys_Semantic_Model")]
        return []

    def get_dataset(self, name):
        return _Dataset()

    def create_semantic_model(self, name):
        return self.new_model


class _ListedModel(object):
    def __init__(self, item_id, name):
        self.id = item_id
        self.name = name

    def to_semantic_model(self):
        return self


class TestSeedModelMarker(unittest.TestCase):
    def test_seed_model_stamps_ownership_marker(self):
        project = _SeedProject()
        ctx = FactoryContext(project=project, dry_run=False)
        result = semantic_builder.seed_model(ctx, make_spec(),
                                             {"template_semantic_model_id": ""})
        self.assertEqual(result, "new_model_1")
        raw = project.new_model.settings.get_raw()
        self.assertEqual(raw["privateEditorData"]["owismindFactory"],
                         {"domain": "satisfaction"})


# --------------------------------------------------- pipeline created_this_run

class TestPipelinePassesCreatedThisRun(unittest.TestCase):
    def _settings(self):
        return {"sql_connection": "SQL_owi", "code_env_311": "",
                "template_zone_recipes": {}, "template_semantic_model_id": ""}

    def _run(self, project):
        captured = {}
        original = pipeline.semantic_builder.apply_config

        def recorder(ctx, model_id, config, created_this_run=False, **kwargs):
            captured["model_id"] = model_id
            captured["created_this_run"] = created_this_run

        pipeline.semantic_builder.apply_config = recorder
        try:
            ctx = FactoryContext(project=project, dry_run=False)
            pipeline.create_domain(ctx, make_spec(),
                                   wizard_config={"entity_description": "d",
                                                  "attributes": [{"column": "col_a"}]},
                                   settings=self._settings(),
                                   steps=["semantic_model", "semantic_config"])
        finally:
            pipeline.semantic_builder.apply_config = original
        return ctx, captured

    def test_true_when_model_seeded_done_this_run(self):
        ctx, captured = self._run(_SeedProject())
        self.assertEqual(statuses(ctx)["semantic_model"], DONE)
        self.assertIs(captured["created_this_run"], True)
        self.assertEqual(captured["model_id"], "new_model_1")

    def test_false_when_seed_model_skipped_existing(self):
        ctx, captured = self._run(_SeedProject(existing_model_id="foreign_7"))
        self.assertEqual(statuses(ctx)["semantic_model"], SKIPPED)
        self.assertIs(captured["created_this_run"], False)
        self.assertEqual(captured["model_id"], "foreign_7")


if __name__ == "__main__":
    unittest.main()
