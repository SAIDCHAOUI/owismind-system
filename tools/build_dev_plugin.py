#!/usr/bin/env python3
"""Build a coexisting DEV copy of the OWIsMind DSS plugin from the single source.

There is ONE source of truth: ``Plugin/owismind/``. The PROD build/package
(``/build-plugin`` + ``/package-plugin``) is untouched. This tool emits a SECOND,
independent plugin (id ``owismind_dev``) that can be installed alongside the prod
one on the same DSS instance, for testing.

Two installed plugins on the same instance collide on three axes unless renamed:
  1. plugin id            -> must be globally unique          (``owismind`` -> ``owismind_dev``)
  2. Vite asset base      -> ``/plugins/<id>/resource/...``    (driven by env OWI_PLUGIN_ID)
  3. python package name  -> ``import owismind`` is process-global across plugins
                             on the same code env             (``owismind`` -> ``owismind_dev``)

What MUST NOT change (so DEV behaves like PROD, just isolated):
  - ``APP_NAMESPACE = "owismind"``  (SQL table namespace; data isolation is a
    deploy-time choice: a dedicated project or ``table_prefix="dev"``, NOT code).
  - the HTTP prefix ``/owismind-api`` and the Flask blueprint name ``owismind_api``.
  - the build outDir folder name ``owismind-app`` inside ``resource/`` (only the
    ``/plugins/<id>/`` segment of the asset base carries the plugin id).

The transform is deterministic and reviewed; it never edits the canonical source
nor ``Plugin/owismind/resource/owismind-app/``. It builds the frontend into a
scratch outDir with ``OWI_PLUGIN_ID=owismind_dev`` (no install: relies on the
existing ``node_modules``) and stages + zips everything under
``Plugin/ready-for-dataiku/``.

Usage:
  python3 tools/build_dev_plugin.py            # full DEV build + stage + zip
  python3 tools/build_dev_plugin.py --check    # validate the rewrite logic only,
                                               # on a /tmp copy of python-lib,
                                               # WITHOUT building or zipping

Python 3, standard library only. No installs of any kind.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

# --- Layout (resolved from this file, so cwd does not matter) ----------------
TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TOOLS_DIR)
PLUGIN_SRC = os.path.join(REPO_ROOT, "Plugin", "owismind")
FRONTEND_DIR = os.path.join(PLUGIN_SRC, "frontend")
NODE_MODULES = os.path.join(FRONTEND_DIR, "node_modules")
VITE_BIN = os.path.join(NODE_MODULES, ".bin", "vite")
READY_DIR = os.path.join(REPO_ROOT, "Plugin", "ready-for-dataiku")

WEBAPP_REL = os.path.join("webapps", "webapp-owismind-ai-agents")
BODY_HTML_REL = os.path.join(WEBAPP_REL, "body.html")
BACKEND_PY_REL = os.path.join(WEBAPP_REL, "backend.py")

# --- DEV identity ------------------------------------------------------------
PROD_ID = "owismind"
DEV_ID = "owismind_dev"
PROD_LABEL = "OWIsMind"
DEV_LABEL = "OWIsMind (DEV)"
# The webapp's OWN label/description (shown in the DSS webapp list, which displays the
# webapp meta.label, NOT the plugin label). Both plugins ship a webapp with the same id,
# so without marking this the two are indistinguishable in the list.
PROD_WEBAPP_LABEL = "OWIsMind - AI Agents"
DEV_WEBAPP_LABEL = "OWIsMind - AI Agents (DEV)"
_WEBAPP_DESC_HEAD = '"description": "Chat with Dataiku AI agents.'
_WEBAPP_DESC_HEAD_DEV = '"description": "[DEV] Chat with Dataiku AI agents.'

# Vite outDir folder name (unchanged across prod/dev; only the /plugins/<id>/ segment moves).
APP_DIR_NAME = "owismind-app"
PROD_BASE = "/plugins/{}/resource/{}/".format(PROD_ID, APP_DIR_NAME)
DEV_BASE = "/plugins/{}/resource/{}/".format(DEV_ID, APP_DIR_NAME)

# Staging + zip outputs (live under ready-for-dataiku/, never in the plugin source).
STAGE_DIR = os.path.join(READY_DIR, "{}-upload".format(DEV_ID))
ZIP_PATH = os.path.join(READY_DIR, "{}-upload.zip".format(DEV_ID))

# Files excluded from the runtime zip - identical to /package-plugin's list.
ZIP_EXCLUDE_BASENAMES = {"CLAUDE.md", "README.md", ".DS_Store"}
ZIP_EXCLUDE_DIRS = {"frontend", "node_modules", "__pycache__", "__MACOSX", "_"}


# --- The package + logger rewrite (the heart of the DEV transform) -----------
# Word-boundary so ``owismind_dev`` is never matched (``_`` is a word char, so
# ``\bowismind\b`` does not match inside ``owismind_dev``). We only rewrite the
# PACKAGE references and the explicit root logger name; APP_NAMESPACE / the
# /owismind-api prefix / the blueprint name are different syntactic shapes and
# are left intact by these precise patterns.
_RE_FROM_OWISMIND = re.compile(r"\bfrom owismind\b")
_RE_IMPORT_OWISMIND = re.compile(r"\bimport owismind\b")
# Match getLogger("owismind") / getLogger('owismind') (the root app logger only).
_RE_GETLOGGER_ROOT = re.compile(r'getLogger\((["\'])owismind\1\)')


def rewrite_python_source(text):
    """Return ``text`` with the PACKAGE + root-logger references retargeted to DEV.

    Deterministic and idempotent on this codebase:
      - ``from owismind``         -> ``from owismind_dev``
      - ``import owismind``       -> ``import owismind_dev``  (bare imports, if any)
      - ``getLogger("owismind")`` -> ``getLogger("owismind_dev")``  (quote style kept)

    Leaves untouched: ``APP_NAMESPACE = "owismind"``, the ``/owismind-api`` URL
    prefix, and ``Blueprint("owismind_api", ...)`` - none of those match the
    word-boundary ``\\bowismind\\b`` package patterns or the getLogger pattern.
    Note: ``getLogger(__name__)`` needs no rewrite - once the package directory is
    renamed to ``owismind_dev``, ``__name__`` resolves to ``owismind_dev.*`` on its own.
    """
    text = _RE_FROM_OWISMIND.sub("from {}".format(DEV_ID), text)
    text = _RE_IMPORT_OWISMIND.sub("import {}".format(DEV_ID), text)
    text = _RE_GETLOGGER_ROOT.sub('getLogger("{}")'.format(DEV_ID), text)
    return text


def _rewrite_py_file_in_place(path):
    """Apply ``rewrite_python_source`` to a single .py file on disk (UTF-8)."""
    with open(path, "r", encoding="utf-8") as fh:
        original = fh.read()
    rewritten = rewrite_python_source(original)
    if rewritten != original:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(rewritten)


def _iter_py_files(root):
    """Yield every ``.py`` file under ``root`` (skipping __pycache__)."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".py"):
                yield os.path.join(dirpath, name)


# --- Invariant checks --------------------------------------------------------
def _grep_count(root, pattern):
    """Count ``.py`` lines under ``root`` matching the compiled ``pattern``."""
    rx = re.compile(pattern)
    count = 0
    for path in _iter_py_files(root):
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                if rx.search(line):
                    count += 1
    return count


def _any_file_contains(root, needle):
    """True if any ``.py`` file under ``root`` contains the literal ``needle``."""
    for path in _iter_py_files(root):
        with open(path, "r", encoding="utf-8") as fh:
            if needle in fh.read():
                return True
    return False


def assert_python_invariants(pkg_root, label):
    """Assert the DEV rewrite invariants on a staged ``owismind_dev`` package tree.

    ``pkg_root`` is the directory that should now be the ``owismind_dev`` package.
    Raises AssertionError (loud) if any invariant is violated; returns a list of
    human-readable "OK" lines for printing.
    """
    lines = []

    # 1. No surviving PACKAGE references to the prod package (word-boundary).
    n_from = _grep_count(pkg_root, r"\bfrom owismind\b")
    n_import = _grep_count(pkg_root, r"\bimport owismind\b")
    assert n_from == 0, "{}: {} surviving 'from owismind\\b' references".format(label, n_from)
    assert n_import == 0, "{}: {} surviving 'import owismind\\b' references".format(label, n_import)
    lines.append("OK  [{}] 0 'from owismind' / 0 'import owismind' (word-boundary)".format(label))

    # 2. The DEV package references are present (sanity: the rewrite actually ran).
    n_dev = _grep_count(pkg_root, r"\bfrom owismind_dev\b") + _grep_count(pkg_root, r"\bimport owismind_dev\b")
    assert n_dev > 0, "{}: rewrite produced no 'owismind_dev' references".format(label)
    lines.append("OK  [{}] {} 'owismind_dev' package references present".format(label, n_dev))

    # 3. Untouched literals: SQL namespace, API prefix, blueprint name.
    assert _any_file_contains(pkg_root, 'APP_NAMESPACE = "owismind"'), \
        "{}: APP_NAMESPACE = \"owismind\" missing".format(label)
    assert _any_file_contains(pkg_root, "/owismind-api"), \
        "{}: /owismind-api missing".format(label)
    assert _any_file_contains(pkg_root, 'Blueprint("owismind_api"'), \
        "{}: Blueprint(\"owismind_api\" missing".format(label)
    lines.append('OK  [{}] APP_NAMESPACE = "owismind" / /owismind-api / Blueprint("owismind_api") intact'.format(label))

    # 4. The root app logger was retargeted to DEV (and the prod one is gone).
    assert _any_file_contains(pkg_root, 'getLogger("{}")'.format(DEV_ID)), \
        "{}: getLogger(\"owismind_dev\") missing".format(label)
    assert _grep_count(pkg_root, r'getLogger\((["\'])owismind\1\)') == 0, \
        "{}: getLogger(\"owismind\") still present".format(label)
    lines.append('OK  [{}] getLogger("owismind") -> getLogger("owismind_dev")'.format(label))

    # 5. The DEV package is importable (has its __init__.py at the root).
    assert os.path.isfile(os.path.join(pkg_root, "__init__.py")), \
        "{}: {}/__init__.py missing".format(label, os.path.basename(pkg_root))
    lines.append("OK  [{}] {}/__init__.py present".format(label, os.path.basename(pkg_root)))

    return lines


# --- --check mode: validate the rewrite on a /tmp copy, no build, no zip -----
def run_check():
    """Copy ``python-lib`` to /tmp, run the rewrite, assert invariants, clean up.

    This proves the deterministic transform without building the frontend or
    producing the real zip - safe to run in the shared tree during a parallel phase.
    """
    src_python_lib = os.path.join(PLUGIN_SRC, "python-lib")
    src_pkg = os.path.join(src_python_lib, PROD_ID)
    if not os.path.isdir(src_pkg):
        print("ERROR: source package not found: {}".format(src_pkg), file=sys.stderr)
        return 1

    tmp = tempfile.mkdtemp(prefix="owi_dev_check_")
    try:
        # Stage python-lib + a copy of backend.py (both carry package imports).
        staged_pkg = os.path.join(tmp, DEV_ID)
        shutil.copytree(src_pkg, staged_pkg, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        staged_backend = os.path.join(tmp, "backend.py")
        shutil.copy2(os.path.join(PLUGIN_SRC, BACKEND_PY_REL), staged_backend)

        # Before-state, for a visible diff in the report.
        before_from = _grep_count(staged_pkg, r"\bfrom owismind\b")
        before_import = _grep_count(staged_pkg, r"\bimport owismind\b")
        backend_before = open(staged_backend, encoding="utf-8").read()

        # Apply the rewrite to the package tree AND backend.py.
        for path in _iter_py_files(staged_pkg):
            _rewrite_py_file_in_place(path)
        _rewrite_py_file_in_place(staged_backend)

        print("=== --check: rewrite on /tmp copy of python-lib ===")
        print("    before: {} 'from owismind\\b', {} 'import owismind\\b'".format(before_from, before_import))
        for line in assert_python_invariants(staged_pkg, "check/python-lib"):
            print("    " + line)

        # backend.py is outside the package tree; check it explicitly.
        backend_after = open(staged_backend, encoding="utf-8").read()
        assert _RE_FROM_OWISMIND.search(backend_after) is None and _RE_IMPORT_OWISMIND.search(backend_after) is None, \
            "backend.py still references the prod package"
        assert "from {}.api.routes import register_routes".format(DEV_ID) in backend_after, \
            "backend.py import not retargeted to owismind_dev"
        assert backend_before != backend_after, "backend.py rewrite was a no-op"
        print("    OK  [check/backend.py] import retargeted to owismind_dev.api.routes")

        print("=== --check PASSED (no build, no zip; /tmp copy discarded) ===")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- Full build --------------------------------------------------------------
def _build_frontend(scratch_out):
    """Run ``vite build`` with OWI_PLUGIN_ID=owismind_dev into ``scratch_out``.

    Never installs: requires an existing ``node_modules`` (errors out otherwise),
    exactly like /build-plugin. Does NOT touch the canonical resource/owismind-app/.
    """
    if not os.path.isdir(NODE_MODULES):
        raise SystemExit(
            "ERROR: {} is missing. Install deps yourself first "
            "(cd Plugin/owismind/frontend && npm install) - this tool never installs.".format(NODE_MODULES)
        )
    if not os.path.isfile(VITE_BIN):
        raise SystemExit("ERROR: vite binary not found at {} (run npm install first).".format(VITE_BIN))

    env = dict(os.environ)
    env["OWI_PLUGIN_ID"] = DEV_ID
    cmd = [VITE_BIN, "build", "--outDir", scratch_out, "--emptyOutDir"]
    print("=== building frontend (OWI_PLUGIN_ID={}) -> {} ===".format(DEV_ID, scratch_out))
    proc = subprocess.run(cmd, cwd=FRONTEND_DIR, env=env)
    if proc.returncode != 0:
        raise SystemExit("ERROR: vite build failed (exit {}).".format(proc.returncode))


def _copy_tree(src, dst, ignore=None):
    """copytree wrapper that tolerates an existing (cleared) destination root."""
    shutil.copytree(src, dst, ignore=ignore)


def _stage_plugin_json():
    """Write the DEV plugin.json: id -> owismind_dev, label -> 'OWIsMind (DEV)'."""
    with open(os.path.join(PLUGIN_SRC, "plugin.json"), "r", encoding="utf-8") as fh:
        text = fh.read()
    # The plugin.json has comments (not strict JSON), so do targeted string edits
    # rather than json.load/dump (which would strip comments + reformat).
    text = text.replace('"id": "{}"'.format(PROD_ID), '"id": "{}"'.format(DEV_ID), 1)
    text = text.replace('"label": "{}"'.format(PROD_LABEL), '"label": "{}"'.format(DEV_LABEL), 1)
    if '"id": "{}"'.format(DEV_ID) not in text:
        raise SystemExit("ERROR: failed to rewrite plugin.json id.")
    if '"label": "{}"'.format(DEV_LABEL) not in text:
        raise SystemExit("ERROR: failed to rewrite plugin.json label.")
    with open(os.path.join(STAGE_DIR, "plugin.json"), "w", encoding="utf-8") as fh:
        fh.write(text)


def _stage_python_lib():
    """Copy python-lib/owismind -> staged python-lib/owismind_dev with rewrites."""
    src_pkg = os.path.join(PLUGIN_SRC, "python-lib", PROD_ID)
    dst_python_lib = os.path.join(STAGE_DIR, "python-lib")
    os.makedirs(dst_python_lib, exist_ok=True)
    dst_pkg = os.path.join(dst_python_lib, DEV_ID)
    _copy_tree(src_pkg, dst_pkg, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for path in _iter_py_files(dst_pkg):
        _rewrite_py_file_in_place(path)
    return dst_pkg


def _stage_resource(scratch_out):
    """Stage resource/: the DEV-base frontend build + compute_available_connections.py.

    The canonical resource/owismind-app/ is NEVER read here; the app dir comes from
    the scratch build output. compute_available_connections.py has no package import,
    so it is copied verbatim (any future import would be caught by the zip-time scan).
    """
    dst_resource = os.path.join(STAGE_DIR, "resource")
    os.makedirs(dst_resource, exist_ok=True)
    # 1. The freshly built app (DEV asset base baked into its index.html).
    _copy_tree(scratch_out, os.path.join(dst_resource, APP_DIR_NAME))
    # 2. The connection-listing helper (standalone DSS resource script).
    src_compute = os.path.join(PLUGIN_SRC, "resource", "compute_available_connections.py")
    if os.path.isfile(src_compute):
        shutil.copy2(src_compute, os.path.join(dst_resource, "compute_available_connections.py"))
    return dst_resource


def _patch_webapp_json(dst_webapp):
    """Mark the staged webapp.json as DEV so the two plugins' webapps are
    distinguishable in the DSS webapp list (which shows the webapp meta.label, not the
    plugin label - without this both read "OWIsMind - AI Agents"). webapp.json carries
    ``//`` comments (not strict JSON), so do targeted string edits, like plugin.json.
    """
    path = os.path.join(dst_webapp, "webapp.json")
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    text = text.replace(
        '"label": "{}"'.format(PROD_WEBAPP_LABEL),
        '"label": "{}"'.format(DEV_WEBAPP_LABEL), 1,
    )
    text = text.replace(_WEBAPP_DESC_HEAD, _WEBAPP_DESC_HEAD_DEV, 1)
    if '"label": "{}"'.format(DEV_WEBAPP_LABEL) not in text:
        raise SystemExit("ERROR: failed to rewrite webapp.json label.")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _stage_webapps(scratch_out):
    """Stage webapps/: backend.py with rewritten import, body.html = DEV-base index.html,
    webapp.json marked DEV (label + description).

    Every other webapp file (app.js, style.css) is copied as-is.
    """
    src_webapp = os.path.join(PLUGIN_SRC, WEBAPP_REL)
    dst_webapp = os.path.join(STAGE_DIR, WEBAPP_REL)
    _copy_tree(src_webapp, dst_webapp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # backend.py: retarget the package import.
    _rewrite_py_file_in_place(os.path.join(dst_webapp, "backend.py"))
    # webapp.json: mark the webapp itself as DEV (the DSS list shows meta.label).
    _patch_webapp_json(dst_webapp)
    # body.html: use the freshly built (DEV-base) index.html, not the prod-base one.
    built_index = os.path.join(scratch_out, "index.html")
    if not os.path.isfile(built_index):
        raise SystemExit("ERROR: built index.html not found at {}.".format(built_index))
    shutil.copy2(built_index, os.path.join(dst_webapp, "body.html"))
    return dst_webapp


def _zip_stage():
    """Zip STAGE_DIR -> ZIP_PATH, excluding the same dev-only files as /package-plugin."""
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(STAGE_DIR):
            # Prune excluded directories (frontend/node_modules/caches) in place.
            dirnames[:] = [d for d in dirnames if d not in ZIP_EXCLUDE_DIRS]
            for name in filenames:
                if name in ZIP_EXCLUDE_BASENAMES or name.endswith(".pyc"):
                    continue
                abs_path = os.path.join(dirpath, name)
                arcname = os.path.relpath(abs_path, STAGE_DIR)
                zf.write(abs_path, arcname)
    return ZIP_PATH


def _assert_zip_clean_and_complete():
    """Assert the DEV zip excludes dev-only files and carries the required runtime files."""
    with zipfile.ZipFile(ZIP_PATH, "r") as zf:
        names = zf.namelist()

    polluted = re.compile(
        r"(^|/)(frontend|node_modules)(/|$)|(^|/)_/|(^|/)CLAUDE\.md$|(^|/)README\.md$|__pycache__|\.pyc$"
    )
    bad = [n for n in names if polluted.search(n)]
    assert not bad, "DEV zip polluted: {}".format(bad[:5])

    required = [
        "plugin.json",
        os.path.join(WEBAPP_REL, "webapp.json"),
        os.path.join(WEBAPP_REL, "body.html"),
        os.path.join(WEBAPP_REL, "backend.py"),
        os.path.join("python-lib", DEV_ID, "__init__.py"),
    ]
    name_set = set(names)
    missing = [r for r in required if r not in name_set]
    assert not missing, "DEV zip missing required files: {}".format(missing)
    return len(names)


def _assert_dev_base(body_html_path):
    """Assert body.html carries the DEV asset base and not the prod one."""
    with open(body_html_path, "r", encoding="utf-8") as fh:
        body = fh.read()
    assert DEV_BASE in body, "body.html missing DEV base {}".format(DEV_BASE)
    assert PROD_BASE not in body, "body.html still carries PROD base {}".format(PROD_BASE)


def run_build():
    """Full DEV pipeline: build -> stage -> rewrite -> zip -> assert + print invariants."""
    os.makedirs(READY_DIR, exist_ok=True)

    # Fresh staging tree (never the canonical source; only under ready-for-dataiku/).
    if os.path.exists(STAGE_DIR):
        shutil.rmtree(STAGE_DIR)
    os.makedirs(STAGE_DIR)

    scratch_out = tempfile.mkdtemp(prefix="owi_dev_build_")
    try:
        _build_frontend(scratch_out)

        _stage_plugin_json()
        staged_pkg = _stage_python_lib()
        _stage_resource(scratch_out)
        staged_webapp = _stage_webapps(scratch_out)

        # --- Invariants (loud, fail-fast) ---
        print("=== DEV invariants ===")
        for line in assert_python_invariants(staged_pkg, "stage/python-lib"):
            print("    " + line)

        staged_backend = os.path.join(staged_webapp, "backend.py")
        backend_text = open(staged_backend, encoding="utf-8").read()
        assert "from {}.api.routes import register_routes".format(DEV_ID) in backend_text, \
            "staged backend.py import not retargeted"
        print("    OK  [stage/backend.py] import -> {}.api.routes".format(DEV_ID))

        body_path = os.path.join(staged_webapp, "body.html")
        _assert_dev_base(body_path)
        print("    OK  [stage/body.html] base = {}".format(DEV_BASE))

        webapp_json_text = open(os.path.join(staged_webapp, "webapp.json"), encoding="utf-8").read()
        assert '"label": "{}"'.format(DEV_WEBAPP_LABEL) in webapp_json_text, \
            "staged webapp.json label not marked DEV"
        print('    OK  [stage/webapp.json] label = "{}"'.format(DEV_WEBAPP_LABEL))

        zip_path = _zip_stage()
        n = _assert_zip_clean_and_complete()
        print("    OK  [zip] clean + required files present ({} entries)".format(n))

        # plugin.json identity check.
        plugin_json = open(os.path.join(STAGE_DIR, "plugin.json"), encoding="utf-8").read()
        assert '"id": "{}"'.format(DEV_ID) in plugin_json and '"label": "{}"'.format(DEV_LABEL) in plugin_json, \
            "plugin.json identity not staged"
        print('    OK  [plugin.json] id = "{}", label = "{}"'.format(DEV_ID, DEV_LABEL))

        print("=== DEV plugin built: {} ===".format(zip_path))
        print("Upload it to DSS as an *Uploaded* plugin (id {}, distinct from prod {}).".format(DEV_ID, PROD_ID))
        print("DEV data isolation is a DEPLOY-TIME choice: a dedicated project or table_prefix=\"dev\".")
        return 0
    finally:
        shutil.rmtree(scratch_out, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the coexisting DEV OWIsMind plugin (id owismind_dev).")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the package/logger rewrite on a /tmp copy of python-lib WITHOUT building or zipping.",
    )
    args = parser.parse_args(argv)
    if args.check:
        return run_check()
    return run_build()


if __name__ == "__main__":
    sys.exit(main())
