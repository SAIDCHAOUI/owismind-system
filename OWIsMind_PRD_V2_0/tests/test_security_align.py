"""DSS-free security tests for the align() allowlist (expected_source_keys).

Audit finding (Sol P1): the aligner used to remap EVERY foreign project key it
discovered, so a model deliberately referencing another project's shared dataset
would be silently broken. The fix gates remapping behind an explicit allowlist:
- expected_source_keys None/empty -> DISCOVERY mode: zero remap, MANUAL report
  listing the foreign keys per model with the re-run instruction;
- expected_source_keys non-empty  -> only the allowlisted keys are remapped, any
  other foreign key is reported (MANUAL) but left untouched;
- the dry-run mechanics (ctx.act plans the save) are unchanged.

Run from the repo root:
    python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -v
"""

import copy
import os
import sys
import unittest

_PKG_PARENT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "project-library", "python"))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)

from owismind_factory import align                       # noqa: E402
from owismind_factory.fctx import (FactoryContext,       # noqa: E402
                                   DONE, MANUAL, PLANNED)

NEW = "NEW_KEY"


# --------------------------------------------------------------------------- fakes

class _FakeSettings(object):
    def __init__(self, raw, saved):
        self._raw = raw
        self._saved = saved  # shared list recording a deep copy at each save()

    def get_raw(self):
        return self._raw

    def save(self):
        self._saved.append(copy.deepcopy(self._raw))


class _FakeVersion(object):
    def __init__(self, settings):
        self._settings = settings

    def get_settings(self):
        return self._settings

    def start_update_distinct_values(self):
        raise AssertionError("reindex must not be requested by these tests")


class _FakeModel(object):
    def __init__(self, model_id, raw, saved):
        self.id = model_id
        self._version = _FakeVersion(_FakeSettings(raw, saved))

    def get_active_version_id(self):
        return "v1"

    def get_version(self, version_id):
        return self._version


class _FakeProject(object):
    project_key = NEW

    def __init__(self, models):
        self._models = models

    def list_semantic_models(self, as_type=None):
        return list(self._models)


def _raw_two_foreign_keys():
    """A model config carrying one clone residue (OLD_KEY) and one deliberate
    shared-dataset reference (OTHER_KEY)."""
    return {
        "name": "Model_A",
        "entities": [
            {"name": "main", "datasetRef": "OLD_KEY.Data", "attributes": []},
            {"name": "shared", "datasetRef": "OTHER_KEY.SharedData", "attributes": []},
        ],
        "goldenQueries": [
            {"question": "how many", "generatedSql": 'SELECT count(*) FROM "OLD_KEY_data"'},
        ],
    }


def _run(raw, dry_run, expected_source_keys=None):
    saved = []
    project = _FakeProject([_FakeModel("m1", raw, saved)])
    ctx = FactoryContext(project=project, dry_run=dry_run)
    align.align(project, ctx, expected_source_keys=expected_source_keys)
    return ctx, saved


# --------------------------------------------------------------------------- tests

class TestDiscoveryMode(unittest.TestCase):
    def test_default_none_remaps_nothing_and_reports_keys(self):
        raw = _raw_two_foreign_keys()
        pristine = copy.deepcopy(raw)
        ctx, saved = _run(raw, dry_run=False, expected_source_keys=None)
        self.assertEqual(saved, [])
        self.assertEqual(raw, pristine)
        manuals = [a for a in ctx.actions if a["status"] == MANUAL]
        self.assertEqual(len(manuals), 1)
        self.assertIn("OLD_KEY", manuals[0]["detail"])
        self.assertIn("OTHER_KEY", manuals[0]["detail"])
        self.assertIn("expected_source_keys", manuals[0]["detail"])
        # No save was even planned or done.
        self.assertEqual([a for a in ctx.actions
                          if a["status"] in (PLANNED, DONE)], [])

    def test_empty_list_behaves_like_none(self):
        raw = _raw_two_foreign_keys()
        pristine = copy.deepcopy(raw)
        ctx, saved = _run(raw, dry_run=False, expected_source_keys=[])
        self.assertEqual(saved, [])
        self.assertEqual(raw, pristine)
        self.assertEqual(len([a for a in ctx.actions if a["status"] == MANUAL]), 1)


class TestAllowlistMode(unittest.TestCase):
    def test_only_allowlisted_key_remapped_other_reported_untouched(self):
        raw = _raw_two_foreign_keys()
        ctx, saved = _run(raw, dry_run=False, expected_source_keys=["OLD_KEY"])
        # OLD_KEY refs remapped in place and saved once.
        self.assertEqual(len(saved), 1)
        self.assertEqual(raw["entities"][0]["datasetRef"], "%s.Data" % NEW)
        self.assertIn("%s_data" % NEW, raw["goldenQueries"][0]["generatedSql"])
        # OTHER_KEY ref untouched, reported as MANUAL.
        self.assertEqual(raw["entities"][1]["datasetRef"], "OTHER_KEY.SharedData")
        manuals = [a for a in ctx.actions if a["status"] == MANUAL]
        self.assertEqual(len(manuals), 1)
        self.assertIn("OTHER_KEY", manuals[0]["detail"])
        self.assertNotIn("OLD_KEY", manuals[0]["detail"])
        saves = [a for a in ctx.actions if a["step"].endswith(".save")]
        self.assertEqual([a["status"] for a in saves], [DONE])
        self.assertIn("OLD_KEY", saves[0]["detail"])
        self.assertNotIn("OTHER_KEY", saves[0]["detail"])

    def test_no_allowlisted_key_present_saves_nothing(self):
        raw = _raw_two_foreign_keys()
        pristine = copy.deepcopy(raw)
        ctx, saved = _run(raw, dry_run=False, expected_source_keys=["UNRELATED_KEY"])
        self.assertEqual(saved, [])
        self.assertEqual(raw, pristine)
        manuals = [a for a in ctx.actions if a["status"] == MANUAL]
        self.assertEqual(len(manuals), 1)
        self.assertIn("OLD_KEY", manuals[0]["detail"])
        self.assertIn("OTHER_KEY", manuals[0]["detail"])


class TestDryRunPreserved(unittest.TestCase):
    def test_dry_run_plans_save_without_touching_model(self):
        raw = _raw_two_foreign_keys()
        pristine = copy.deepcopy(raw)
        ctx, saved = _run(raw, dry_run=True, expected_source_keys=["OLD_KEY"])
        self.assertEqual(saved, [])
        self.assertEqual(raw, pristine)
        saves = [a for a in ctx.actions if a["step"].endswith(".save")]
        self.assertEqual([a["status"] for a in saves], [PLANNED])
        # The out-of-allowlist key is still reported in dry-run.
        manuals = [a for a in ctx.actions if a["status"] == MANUAL]
        self.assertEqual(len(manuals), 1)
        self.assertIn("OTHER_KEY", manuals[0]["detail"])


if __name__ == "__main__":
    unittest.main()
