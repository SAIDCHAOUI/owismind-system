"""Tests for the deterministic Config and Prompt Hub seed regenerator."""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_MIRROR_DIR = os.path.dirname(_TESTS_DIR)
_REPO_ROOT = os.path.dirname(_MIRROR_DIR)
_REGENERATOR = os.path.join(_MIRROR_DIR, "hub", "regenerate_seeds.py")


def _load_regenerator():
    spec = importlib.util.spec_from_file_location("hub_seeds_regenerator", _REGENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_regenerator = _load_regenerator()


def _copy_file(source, destination):
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    shutil.copy2(source, destination)


def _copy_fixture_repo(destination_root):
    """Copy only the source and seed files required by the regenerator."""
    relative_paths = (
        os.path.join("agents", "OWIsMind_orchestrator.py"),
        os.path.join("project-library", "python", "owismind_factory", "hub.py"),
        os.path.join("hub", "capabilities.json"),
        os.path.join("hub", "factory_settings.json"),
        os.path.join("hub", "prompts", "orchestrator_persona.md"),
    )
    for relative_path in relative_paths:
        _copy_file(
            os.path.join(_MIRROR_DIR, relative_path),
            os.path.join(destination_root, "OWIsMind_PRD_V1_2", relative_path),
        )


class TestHubSeedsRegenerator(unittest.TestCase):
    def test_check_mode_passes_against_repository_seeds(self):
        result = subprocess.run(
            [sys.executable, _REGENERATOR, "--check"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK: all 3 hub seed files are up to date.", result.stdout)

    def test_canonical_bytes_are_deterministic(self):
        first = _regenerator.build_canonical_files(_REPO_ROOT)
        second = _regenerator.build_canonical_files(_REPO_ROOT)
        self.assertEqual(first, second)

    def test_tampered_seed_is_detected_and_repaired(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            _copy_fixture_repo(temporary_root)
            seed_path = os.path.join(
                temporary_root,
                "OWIsMind_PRD_V1_2",
                "hub",
                "capabilities.json",
            )
            with open(seed_path, "wb") as seed_file:
                seed_file.write(b"{\"tampered\": true}\n")

            differences = _regenerator.diff_report(temporary_root)
            self.assertEqual(
                differences,
                [os.path.join("OWIsMind_PRD_V1_2", "hub", "capabilities.json")],
            )

            canonical = _regenerator.build_canonical_files(temporary_root)
            changed = _regenerator.write_canonical_files(temporary_root)
            self.assertEqual(
                changed,
                [os.path.join("OWIsMind_PRD_V1_2", "hub", "capabilities.json")],
            )
            with open(seed_path, "rb") as seed_file:
                self.assertEqual(seed_file.read(), canonical[seed_path])
            self.assertEqual(_regenerator.diff_report(temporary_root), [])
            self.assertEqual(_regenerator.write_canonical_files(temporary_root), [])


if __name__ == "__main__":
    unittest.main()
