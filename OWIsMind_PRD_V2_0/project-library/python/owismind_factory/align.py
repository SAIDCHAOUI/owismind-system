"""align: generic clone aligner for semantic models.

Duplicating a DSS project does NOT rewrite the semantic models' dataset
references. Every copied model keeps pointing at the SOURCE project:
- the logical ``datasetRef`` inside each entity keeps the form
  ``"<OLDKEY>.<Dataset>"``,
- the physical table literals inside ``goldenQueries[*].generatedSql`` (and the
  SQL-generation instructions) keep the form ``"<OLDKEY>_<table>"``.

The UI gives no way to change that. Two validated one-off scripts already fixed
ONE model each with a hardcoded old key (now ACTION="repoint" in
``GenAI/semantic-models/<Model>/<Model>.py``, formerly scripts/*_prod_clone.py).
This module GENERALIZES that pure string remap to ALL models of the CURRENT
project, discovering the foreign key(s) automatically.

Design rules (same as the rest of ``owismind_factory``):
- stdlib only at import time (``re``); every DSS call comes from the ``project``
  handle the caller passes, so the pure remap logic is testable without DSS.
- the string-remap core is PURE and BOUNDARY-SAFE: a prefix is only rewritten at
  an identifier boundary (start-of-string, a quote, or any non-word char), so a
  larger token that merely CONTAINS the old key is never corrupted.
- read-only by default: every mutating call routes through a
  :class:`owismind_factory.fctx.FactoryContext`, so dry-run produces a PLAN and
  nothing touches DSS.
- remapping is ALLOWLIST-gated: a foreign key may be a clone residue OR a
  deliberate reference to another project's shared dataset, and the aligner
  cannot tell them apart. Without ``expected_source_keys`` it only DISCOVERS
  and reports the foreign keys; it never remaps a key the operator did not
  explicitly allowlist.
- a model with no foreign prefix is SKIPPED, never touched.
- NO deletion anywhere.
"""

import re

# The two forms a project key appears in inside a semantic-model config:
#   dataset ref   : "<KEY>.<Dataset>"   (entity datasetRef)
#   table literal : "<KEY>_<table>"     (golden-query / instruction SQL, table lowercased)
#
# A physical table literal is "<KEY>_<lowercased table>": the key is one or more
# UPPERCASE/digit segments joined by underscores, then "_" then a lowercase table
# name. Requiring at least one "_<SEGMENT>" (so the key itself carries a "_")
# keeps this from flagging an ordinary "Alias_column" as a project prefix. The
# authoritative discovery is still the datasetRef; this SQL scan is a safety net.
_TABLE_LITERAL_RE = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)_[a-z]")


# --------------------------------------------------------------------------- pure remap

def remap_dataset_ref(ref, old_key, new_key):
    """Rewrite a logical ``"<old_key>.<Dataset>"`` ref to ``"<new_key>.<Dataset>"``.

    Anchored at the start of the string (a datasetRef always leads with its
    project key). Any other ref is returned unchanged. Pure.
    """
    if not isinstance(ref, str) or not old_key:
        return ref
    prefix = old_key + "."
    if ref.startswith(prefix):
        return new_key + "." + ref[len(prefix):]
    return ref


def remap_sql(sql, old_key, new_key):
    """Rewrite ``<old_key>`` prefixes (followed by ``.`` or ``_``) to ``<new_key>``.

    Handles BOTH quoted (``"OLDKEY_tbl"``) and unquoted (``FROM OLDKEY_tbl``)
    forms, and the qualified ``OLDKEY.Dataset`` form. Boundary-safe: the match
    must not be preceded by a word char, so ``XOLDKEY_tbl`` is left intact. The
    separator (``.`` / ``_``) is a lookahead, so it is preserved. Pure.
    """
    if not isinstance(sql, str) or not old_key:
        return sql
    pattern = re.compile(r"(?<![A-Za-z0-9_])" + re.escape(old_key) + r"(?=[._])")
    return pattern.sub(new_key, sql)


def _dataset_ref_key(ref):
    """The project-key prefix of a ``"<KEY>.<Dataset>"`` ref, else None."""
    if not isinstance(ref, str) or "." not in ref:
        return None
    return ref.split(".", 1)[0]


def _iter_field(node, field_name):
    """Every string value stored under ``field_name`` anywhere in ``node``."""
    out = []

    def walk(value):
        if isinstance(value, dict):
            for key, val in value.items():
                if key == field_name and isinstance(val, str):
                    out.append(val)
                walk(val)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(node)
    return out


def find_foreign_keys(raw, current_key):
    """List the project keys the config still points at, other than ``current_key``.

    Discovered from BOTH the authoritative logical ``datasetRef`` fields and the
    physical table literals in ``generatedSql``. Returns a sorted, de-duplicated
    list (empty = the model is already aligned to the current project). Pure.
    """
    keys = set()
    for ref in _iter_field(raw, "datasetRef"):
        key = _dataset_ref_key(ref)
        if key and key != current_key:
            keys.add(key)
    for sql in _iter_field(raw, "generatedSql"):
        for key in _TABLE_LITERAL_RE.findall(sql):
            if key and key != current_key:
                keys.add(key)
    return sorted(keys)


def remap_raw(raw, old_keys, new_key):
    """Deep copy of ``raw`` with every ``old_keys`` prefix remapped to ``new_key``.

    ``datasetRef`` fields go through :func:`remap_dataset_ref`; every other string
    goes through :func:`remap_sql` (which also catches table literals in the
    instructions and anywhere else). The input is NOT mutated. Pure.
    """
    active = [k for k in old_keys if k and k != new_key]

    def walk(value, field=None):
        if isinstance(value, dict):
            return {k: walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, field) for v in value]
        if isinstance(value, str):
            out = value
            for old_key in active:
                if field == "datasetRef":
                    out = remap_dataset_ref(out, old_key, new_key)
                else:
                    out = remap_sql(out, old_key, new_key)
            return out
        return value

    return walk(raw)


def _count_golden_sql_hits(raw, foreign_keys):
    """How many ``generatedSql`` strings reference a foreign table/ref."""
    if not foreign_keys:
        return 0
    hits = 0
    for sql in _iter_field(raw, "generatedSql"):
        if any((k + "_") in sql or (k + ".") in sql for k in foreign_keys):
            hits += 1
    return hits


# --------------------------------------------------------------------------- DSS glue

def _iter_models(project):
    """The project's semantic models as objects, robust to the client build.

    Prefers the documented ``as_type="objects"`` form; falls back to listing
    handles and fetching each object if the server build rejects the kwarg.
    """
    try:
        return list(project.list_semantic_models(as_type="objects"))
    except TypeError:
        out = []
        for handle in project.list_semantic_models():
            mid = handle.get("id") if isinstance(handle, dict) else getattr(handle, "id", None)
            if mid:
                out.append(project.get_semantic_model(mid))
        return out


def _model_name(model, raw=None):
    if isinstance(raw, dict) and raw.get("name"):
        return raw["name"]
    name = getattr(model, "name", None)
    return name or getattr(model, "id", None)


def _read_raw(model):
    """(version_id, settings, raw) for a model's active version."""
    version_id = model.get_active_version_id()
    settings = model.get_version(version_id).get_settings()
    return version_id, settings, settings.get_raw()


def scan(project):
    """Report, per semantic model, which foreign project keys it still points at.

    Read-only. Returns a list of dicts:
    ``{model_id, model_name, version_id, dataset_refs, foreign_keys_found,
    golden_query_hits}`` (or ``{model_id, model_name, error}`` if a model could
    not be read).
    """
    current_key = project.project_key
    reports = []
    for model in _iter_models(project):
        model_id = getattr(model, "id", None)
        try:
            version_id, _settings, raw = _read_raw(model)
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            reports.append({"model_id": model_id,
                            "model_name": _model_name(model),
                            "error": str(exc)})
            continue
        reports.append({
            "model_id": model_id,
            "model_name": _model_name(model, raw),
            "version_id": version_id,
            "dataset_refs": sorted(set(_iter_field(raw, "datasetRef"))),
            "foreign_keys_found": find_foreign_keys(raw, current_key),
            "golden_query_hits": _count_golden_sql_hits(
                raw, find_foreign_keys(raw, current_key)),
        })
    return reports


def align(project, ctx, reindex=False, expected_source_keys=None):
    """Remap the ALLOWLISTED foreign project-key prefixes in every model.

    Each model is handled through ``ctx.act`` so dry-run only PLANS. A model with
    no foreign prefix is skipped (never touched).

    ``expected_source_keys`` is the explicit allowlist of project keys to remap
    (typically the clone's old project key). When None or empty, the aligner runs
    in DISCOVERY mode: nothing is remapped, and each model's foreign keys are
    reported as a MANUAL action telling the operator to re-run with
    ``expected_source_keys=[...]``. When non-empty, ONLY those keys are remapped;
    any other foreign key (e.g. a deliberate reference to another project's
    shared dataset) is reported but left UNTOUCHED. When ``reindex`` is True, the
    distinct-value index is rebuilt on the new table after a successful save.
    Returns ``ctx``.
    """
    current_key = project.project_key
    allowed = set(k for k in (expected_source_keys or []) if k)
    for model in _iter_models(project):
        model_id = getattr(model, "id", None)
        try:
            version_id, settings, raw = _read_raw(model)
        except Exception as exc:  # noqa: BLE001
            ctx.fail("align.%s" % (model_id or "model"),
                     "could not read settings: %s" % exc)
            continue
        name = _model_name(model, raw)
        step = "align.%s" % (name or model_id or "model")
        foreign = find_foreign_keys(raw, current_key)
        if not foreign:
            ctx.skip(step, "no foreign project-key prefix (already aligned to %s)" % current_key)
            continue
        if not allowed:
            # Discovery mode: a foreign key may be a clone residue OR a deliberate
            # shared-dataset reference. Never guess: report the keys and let the
            # operator allowlist the ones that must be remapped.
            ctx.manual(step + ".discover",
                       "foreign project key(s) found: %s; nothing remapped; "
                       "re-run with expected_source_keys=%r to remap"
                       % (", ".join(foreign), foreign))
            continue
        to_remap = [k for k in foreign if k in allowed]
        untouched = [k for k in foreign if k not in allowed]
        if untouched:
            ctx.manual(step + ".unexpected",
                       "foreign project key(s) NOT in expected_source_keys, left "
                       "untouched: %s; add them to expected_source_keys to remap"
                       % ", ".join(untouched))
        if not to_remap:
            continue
        fixed = remap_raw(raw, to_remap, current_key)
        detail = "remap %s -> %s" % (", ".join(to_remap), current_key)

        def _save(settings=settings, raw=raw, fixed=fixed):
            raw.clear()
            raw.update(fixed)
            settings.save()
            return True

        saved = ctx.act(step + ".save", detail, _save)

        # Reindex only after a CONFIRMED save (act returns None on failure):
        # rebuilding the distinct-value index against a half-remapped model
        # would burn embedding calls for nothing. Dry-run still PLANS it.
        if reindex and (ctx.dry_run or saved):
            def _reindex(model=model, version_id=version_id):
                return model.get_version(version_id).start_update_distinct_values().wait_for_result()

            ctx.act(step + ".reindex",
                    "re-index distinct values on the %s table" % current_key, _reindex)
        elif reindex:
            ctx.block(step + ".reindex", "settings save failed: reindex not attempted")
    return ctx
