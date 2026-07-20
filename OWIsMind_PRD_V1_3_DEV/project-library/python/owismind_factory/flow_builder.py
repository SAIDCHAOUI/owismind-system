"""Flow construction: source dataset, zone, knowledge datasets, recipes, scenario.

Every function is an idempotent ``ensure_*``: it reuses existing objects and only
creates what is missing, through ctx.act() so dry-run planning works.

API surface used (all official, verified against the Dataiku client source):
- project.list_datasets / get_dataset / new_managed_dataset(...).with_store_into(...).create()
- TablesImportDefinition.add_sql_table(...).prepare().execute()  (external table import)
- project.get_flow().create_zone / list_zones ; zone.add_item / add_shared
- project.new_recipe("python", name).with_input(...).with_output(...).with_script(...).create()
- recipe.get_settings().get_payload() / set_code_env / save
- project.create_scenario(name, "custom_python", definition) + add_daily_trigger
"""

from .fctx import FactoryContext  # noqa: F401 (documentation import)


# ---------------------------------------------------------------------- helpers

class ExistenceCheckError(Exception):
    """The listing API itself failed: 'absent' can NOT be concluded.

    A permission error or timeout during list_* must never be read as "the
    object does not exist" (that would trigger a duplicate-creation attempt and
    defeat idempotency). Callers catch this, record a FAILED action and skip
    the creation instead of guessing.
    """


def dataset_exists(project, name):
    try:
        return any(d.get("name", None) == name if isinstance(d, dict) else getattr(d, "name", None) == name
                   for d in project.list_datasets())
    except Exception as exc:
        raise ExistenceCheckError("could not list datasets: %s" % exc)


def recipe_exists(project, name):
    try:
        for r in project.list_recipes():
            r_name = r.get("name") if isinstance(r, dict) else getattr(r, "name", None)
            if r_name == name:
                return True
        return False
    except Exception as exc:
        raise ExistenceCheckError("could not list recipes: %s" % exc)


def _zone_by_name(flow, name):
    for zone in flow.list_zones():
        if getattr(zone, "name", None) == name:
            return zone
    return None


# ---------------------------------------------------------------- source dataset

def ensure_source_dataset(ctx, spec):
    """Make sure the base dataset exists; import the external SQL table if needed.

    The import runs as a DSS background job (DSSFuture): we wait through the
    documented ``wait_for_result()`` rather than polling.
    """
    try:
        if dataset_exists(ctx.project, spec.base_dataset):
            ctx.skip("source_dataset", "dataset %s already exists" % spec.base_dataset)
            return spec.base_dataset
    except ExistenceCheckError as exc:
        # Planning creates nothing: an unverifiable existence only blocks real runs.
        if not ctx.dry_run:
            ctx.fail("source_dataset", "existence check failed, NOT creating anything: %s" % exc)
            return None
    if not spec.source:
        ctx.manual("source_dataset",
                   "dataset %s does not exist and no source table was given: create or "
                   "import it in DSS first (or add 'source' to the spec)" % spec.base_dataset)
        return None

    source = spec.source

    def _import():
        definition = ctx.project.init_tables_import()
        definition.add_sql_table(source["connection"],
                                 source.get("schema") or "",
                                 source["table"],
                                 catalog=source.get("catalog"))
        prepared = definition.prepare()
        # Best-effort rename of the candidate dataset to the spec's base name.
        # prepare() returns server candidates whose exact shape is not documented:
        # handle a bare list and ANY dict envelope key ("tables",
        # "sqlImportCandidates", ...), defensively.
        try:
            candidates = prepared.candidates
            if isinstance(candidates, dict):
                table_lists = [v for v in candidates.values() if isinstance(v, list)]
            else:
                table_lists = [candidates]
            for table_list in table_lists:
                for candidate in (table_list or []):
                    if isinstance(candidate, dict) and "datasetName" in candidate:
                        candidate["datasetName"] = spec.base_dataset
        except Exception:
            pass
        future = prepared.execute()
        future.wait_for_result()
        # The rename above is best-effort: PROVE the dataset landed under the
        # expected name, otherwise downstream steps would silently reference a
        # dataset that does not exist (the import may have used the table name).
        try:
            imported = dataset_exists(ctx.project, spec.base_dataset)
        except ExistenceCheckError as exc:
            raise RuntimeError("import ran but the verification listing failed: %s" % exc)
        if not imported:
            raise RuntimeError(
                "import finished but no dataset named %r exists: the candidate "
                "rename did not take. Find the imported dataset in the Flow and "
                "rename it to %r by hand, then re-run."
                % (spec.base_dataset, spec.base_dataset))
        return spec.base_dataset

    return ctx.act("source_dataset",
                   "import %s.%s (connection %s) as dataset %s"
                   % (source.get("schema") or "", source["table"], source["connection"], spec.base_dataset),
                   _import)


# ------------------------------------------------------------------------- zone

def ensure_zone(ctx, spec):
    flow = ctx.project.get_flow()
    existing = _zone_by_name(flow, spec.zone_name)
    if existing is not None:
        ctx.skip("zone", "zone %s already exists" % spec.zone_name)
        return existing
    return ctx.act("zone", "create Flow zone %s" % spec.zone_name,
                   lambda: flow.create_zone(spec.zone_name))


def move_into_zone(ctx, zone, obj, label):
    """Move a dataset/recipe into the zone (cosmetic; failures are non-fatal)."""
    if zone is None:
        ctx.skip("zone_item", "no zone handle (dry run): would move %s" % label)
        return
    ctx.act("zone_item", "move %s into zone %s" % (label, getattr(zone, "name", "?")),
            lambda: zone.add_item(obj))


def share_into_zone(ctx, zone, obj, label):
    """Pre-share an item into the zone WITHOUT moving it (used for the base dataset)."""
    if zone is None:
        ctx.skip("zone_share", "no zone handle (dry run): would share %s" % label)
        return
    ctx.act("zone_share", "share %s into zone %s" % (label, getattr(zone, "name", "?")),
            lambda: zone.add_shared(obj))


# ------------------------------------------------------------ knowledge datasets

def ensure_knowledge_datasets(ctx, spec, connection, zone=None):
    """Create the profile / value_index / value_catalog managed datasets.

    All three are stored on the SQL connection: value_index MUST be there (the
    sub-agent grounds by live SQL on it) and keeping the trio together mirrors
    the validated revenue/tickets zones.
    """
    created = []
    for name in spec.knowledge_datasets:
        try:
            if dataset_exists(ctx.project, name):
                ctx.skip("dataset:%s" % name, "already exists")
                continue
        except ExistenceCheckError as exc:
            if not ctx.dry_run:
                ctx.fail("dataset:%s" % name, "existence check failed, NOT creating: %s" % exc)
                continue

        def _create(dataset_name=name):
            builder = ctx.project.new_managed_dataset(dataset_name)
            builder.with_store_into(connection)
            dataset = builder.create()
            return dataset

        dataset = ctx.act("dataset:%s" % name,
                          "create managed dataset %s on connection %s" % (name, connection),
                          _create)
        if dataset is not None:
            created.append(name)
            move_into_zone(ctx, zone, dataset, "dataset %s" % name)
    return created


# ---------------------------------------------------------------------- recipes

def read_recipe_code(project, recipe_name):
    """Return the Python code payload of an existing recipe (the living template)."""
    recipe = project.get_recipe(recipe_name)
    settings = recipe.get_settings()
    return settings.get_payload()


def ensure_recipes(ctx, spec, template_recipes, code_env="", zone=None):
    """Create the 3 knowledge recipes by CLONING the validated generic recipes.

    The generic recipes are dataset-adaptive by design (they read their IO from
    the Flow wiring via dataiku.recipe.get_inputs_as_datasets()), so the exact
    code of the validated revenue recipes works unchanged for any dataset: the
    factory copies each template's code payload verbatim.

    :param dict template_recipes: {"profile": recipe_name, "value_index": ...,
        "value_catalog": ...} names of the template recipes in this project.
    """
    plan = [
        ("profile", spec.profile_dataset),
        ("value_index", spec.value_index_dataset),
        ("value_catalog", spec.value_catalog_dataset),
    ]
    created = []
    for kind, output_dataset in plan:
        recipe_name = spec.recipe_name(output_dataset)
        try:
            if recipe_exists(ctx.project, recipe_name):
                ctx.skip("recipe:%s" % recipe_name, "already exists")
                continue
        except ExistenceCheckError as exc:
            if not ctx.dry_run:
                ctx.fail("recipe:%s" % recipe_name, "existence check failed, NOT creating: %s" % exc)
                continue
        template_name = (template_recipes or {}).get(kind)
        if not template_name:
            ctx.manual("recipe:%s" % recipe_name,
                       "no template recipe configured for kind %r: create the recipe in "
                       "DSS and paste the generic %s recipe code" % (kind, kind))
            continue

        def _create(rname=recipe_name, out=output_dataset, tmpl=template_name):
            code = read_recipe_code(ctx.project, tmpl)
            creator = ctx.project.new_recipe("python", rname)
            creator.with_input(spec.base_dataset)
            creator.with_output(out)
            creator.with_script(code)
            recipe = creator.create()
            if code_env:
                settings = recipe.get_settings()
                settings.set_code_env(code_env=code_env)
                settings.save()
            return recipe

        recipe = ctx.act("recipe:%s" % recipe_name,
                         "create python recipe %s (%s -> %s), code cloned from %s%s"
                         % (recipe_name, spec.base_dataset, output_dataset, template_name,
                            (", code env %s" % code_env) if code_env else ""),
                         _create)
        if recipe is not None:
            created.append(recipe_name)
            move_into_zone(ctx, zone, recipe, "recipe %s" % recipe_name)
    return created


# --------------------------------------------------------------------- scenario

# The refresh scenario is a CUSTOM PYTHON scenario: the step API
# (dataiku.scenario.Scenario().build_dataset) is fully documented, whereas the
# raw dict shape of visual step-based steps is not. Sequential builds, off-peak.
_SCENARIO_CODE_TEMPLATE = '''\
# {scenario_name} - rebuild the {domain} knowledge datasets (generated by owismind_factory).
# Sequential, non-recursive builds: base -> profile -> value_index -> value_catalog.
# Runs off-peak via the daily trigger (kept INACTIVE until a human enables the scenario).
from dataiku.scenario import Scenario

scenario = Scenario()
{build_lines}
'''


def build_scenario_code(spec):
    lines = "\n".join('scenario.build_dataset("%s")' % name for name in spec.knowledge_datasets)
    return _SCENARIO_CODE_TEMPLATE.format(scenario_name=spec.scenario_name,
                                          domain=spec.domain,
                                          build_lines=lines)


def scenario_exists(project, name):
    try:
        for s in project.list_scenarios():
            s_name = s.get("name") if isinstance(s, dict) else getattr(s, "name", None)
            if s_name == name:
                return True
        return False
    except Exception as exc:
        raise ExistenceCheckError("could not list scenarios: %s" % exc)


def ensure_refresh_scenario(ctx, spec, hour=3):
    """Create the nightly refresh scenario (custom python, INACTIVE by default).

    The scenario is created with its daily trigger defined but the scenario NOT
    activated: a human reviews the first manual run, then flips it on in DSS.
    The trigger is its OWN action: a trigger failure must show as FAILED in the
    report (a silently missing trigger would never be repaired, since reruns
    skip the scenario by name).
    """
    try:
        if scenario_exists(ctx.project, spec.scenario_name):
            ctx.skip("scenario", "scenario %s already exists" % spec.scenario_name)
            return None
    except ExistenceCheckError as exc:
        if not ctx.dry_run:
            ctx.fail("scenario", "existence check failed, NOT creating: %s" % exc)
            return None

    def _create():
        definition = {"params": {"code": build_scenario_code(spec)}}
        return ctx.project.create_scenario(spec.scenario_name, "custom_python", definition=definition)

    scenario = ctx.act("scenario",
                       "create INACTIVE custom-python scenario %s (sequential builds of %s; "
                       "enable it by hand after review)"
                       % (spec.scenario_name, ", ".join(spec.knowledge_datasets)),
                       _create)

    def _trigger():
        settings = scenario.get_settings()
        # The INACTIVE promise must not rest on an undocumented creation
        # default: force it in the same save that defines the trigger. Without
        # a defined trigger an active scenario never fires, so forcing it here
        # (not at creation) still closes every auto-run path.
        settings.active = False
        settings.add_daily_trigger(hour=hour, minute=0)
        settings.save()
        return True

    if scenario is not None:
        ctx.act("scenario_trigger",
                "define the daily %02d:00 trigger on scenario %s (scenario stays inactive)"
                % (hour, spec.scenario_name), _trigger)
    elif ctx.dry_run:
        ctx.plan("scenario_trigger",
                 "define the daily %02d:00 trigger on scenario %s" % (hour, spec.scenario_name))
    return scenario


def run_scenario_now(ctx, spec):
    """EXPLICIT first build: run the refresh scenario once and wait for the outcome.

    Never called by the pipeline automatically: building datasets loads the
    instance, so a human decides when.
    """
    def _run():
        scenario = None
        for s in ctx.project.list_scenarios(as_type="objects"):
            if getattr(s, "id", None) == spec.scenario_name or getattr(s, "name", None) == spec.scenario_name:
                scenario = s
                break
        if scenario is None:
            # list_scenarios may return listitems without handles on old clients
            raise RuntimeError("scenario %s not found" % spec.scenario_name)
        run = scenario.run_and_wait(no_fail=True)
        return getattr(run, "outcome", "UNKNOWN")

    return ctx.act("scenario_run", "run scenario %s once and wait" % spec.scenario_name, _run)
