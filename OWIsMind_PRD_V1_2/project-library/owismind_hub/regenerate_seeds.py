"""Regenerate the repository seeds for the OWIsMind Config and Prompt Hub."""

import argparse
import ast
import importlib.util
import json
import os
import sys


_MIRROR_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REPO_ROOT = os.path.dirname(_MIRROR_DIR)


def _extract_constants(path, names):
    """Extract module-level literal assignments without importing the module."""
    with open(path, encoding="utf-8") as source_file:
        tree = ast.parse(source_file.read(), filename=path)
    found = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            name = node.targets[0].id
            if name in names:
                found[name] = ast.literal_eval(node.value)
    missing = set(names) - set(found)
    if missing:
        raise ValueError("Missing literal constants in %s: %s" %
                         (path, ", ".join(sorted(missing))))
    return found


def _has_module_level_dataiku_import(path):
    """Return whether a module imports dataiku at module level."""
    with open(path, encoding="utf-8") as source_file:
        tree = ast.parse(source_file.read(), filename=path)
    for node in tree.body:
        if isinstance(node, ast.Import):
            if any(alias.name == "dataiku" for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module == "dataiku":
            return True
    return False


def _load_default_settings(hub_module_path):
    """Load DEFAULT_SETTINGS directly, or use AST if Dataiku is imported."""
    if _has_module_level_dataiku_import(hub_module_path):
        return _extract_constants(hub_module_path, {"DEFAULT_SETTINGS"})[
            "DEFAULT_SETTINGS"
        ]

    module_name = "_owismind_factory_hub_seed_%s" % abs(hash(hub_module_path))
    spec = importlib.util.spec_from_file_location(module_name, hub_module_path)
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load %s" % hub_module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        return module.DEFAULT_SETTINGS
    finally:
        sys.modules.pop(module_name, None)


def _json_bytes(value):
    """Serialize a hub JSON seed using its existing canonical format."""
    content = json.dumps(
        value,
        indent=2,
        sort_keys=False,
        ensure_ascii=False,
        separators=(",", ": "),
    )
    return (content + "\n").encode("utf-8")


def build_canonical_files(repo_root) -> dict[str, bytes]:
    """Build canonical hub seed bytes keyed by absolute seed file path."""
    repo_root = os.path.abspath(repo_root)
    mirror_dir = os.path.join(repo_root, "OWIsMind_PRD_V1_2")
    orchestrator_path = os.path.join(
        mirror_dir, "genai", "agents", "OWIsMind_orchestrator.py"
    )
    hub_module_path = os.path.join(
        mirror_dir, "project-library", "python", "owismind_factory", "hub.py"
    )
    constants = _extract_constants(
        orchestrator_path, {"CAPABILITIES_DEFAULT", "PERSONA_DEFAULT"}
    )
    hub_dir = os.path.join(mirror_dir, "project-library", "owismind_hub")
    return {
        os.path.join(hub_dir, "capabilities.json"): _json_bytes(
            constants["CAPABILITIES_DEFAULT"]
        ),
        os.path.join(hub_dir, "prompts", "orchestrator_persona.md"):
            constants["PERSONA_DEFAULT"].encode("utf-8"),
        os.path.join(hub_dir, "factory_settings.json"): _json_bytes(
            _load_default_settings(hub_module_path)
        ),
    }


def diff_report(repo_root) -> list[str]:
    """Return relative seed paths whose current bytes differ from canonical bytes."""
    repo_root = os.path.abspath(repo_root)
    differences = []
    for path, expected in build_canonical_files(repo_root).items():
        try:
            with open(path, "rb") as seed_file:
                actual = seed_file.read()
        except FileNotFoundError:
            actual = None
        if actual != expected:
            differences.append(os.path.relpath(path, repo_root))
    return differences


def write_canonical_files(repo_root) -> list[str]:
    """Write only stale hub seed files and return their relative paths."""
    repo_root = os.path.abspath(repo_root)
    changed = []
    for path, expected in build_canonical_files(repo_root).items():
        try:
            with open(path, "rb") as seed_file:
                actual = seed_file.read()
        except FileNotFoundError:
            actual = None
        if actual != expected:
            with open(path, "wb") as seed_file:
                seed_file.write(expected)
            changed.append(os.path.relpath(path, repo_root))
    return changed


def main(argv=None):
    """Run the seed regenerator from any current working directory."""
    parser = argparse.ArgumentParser(
        description="Regenerate the OWIsMind Config and Prompt Hub seed files."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report seed drift without writing files",
    )
    args = parser.parse_args(argv)

    if args.check:
        differences = diff_report(_REPO_ROOT)
        if differences:
            for path in differences:
                print("DIFF: %s differs from its canonical seed." % path,
                      file=sys.stderr)
            return 1
        print("OK: all 3 hub seed files are up to date.")
        return 0

    changed = write_canonical_files(_REPO_ROOT)
    canonical_paths = build_canonical_files(_REPO_ROOT)
    changed_set = set(changed)
    for path in sorted(changed):
        print("UPDATED: %s" % path)
    for path in sorted(
            os.path.relpath(path, _REPO_ROOT) for path in canonical_paths
            if os.path.relpath(path, _REPO_ROOT) not in changed_set):
        print("UP TO DATE: %s" % path)
    print("OK: processed 3 hub seed files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
