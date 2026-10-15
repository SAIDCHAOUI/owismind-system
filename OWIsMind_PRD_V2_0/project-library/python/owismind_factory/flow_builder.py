"""Flow construction: source dataset, zone, knowledge datasets, recipes, scenario.

Every function is an idempotent ``ensure_*``: it reuses existing objects and only
creates what is missing, through ctx.act() so dry-run planning works.

API surface used (all official, verified against the Dataiku client source):
- project.list_datasets / get_dataset / new_managed_dataset(...).with_store_into(...).create()
- TablesImportDefinition.add_sql_table(...).prepare().execute()  (external table import)
- project.get_flow().create_zone / list_zones ; zone.add_item / add_shared
- project.new_recipe("python", name).with_input(...).with_output(...).with_script(...).create()
- recipe.get_settings().get_payload() / set_code_env / save
- project.create_scenario(name, "step_based", definition) + add_daily_trigger
- scenario.run / get_current_run ; DSSTriggerFire.wait_for_scenario_run ;
  DSSScenarioRun.refresh / running / outcome / get_details (first_error_details)
"""

import time

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

# Build mode of each refresh step. The allowed values are documented on the
# in-scenario helper dataiku.scenario.BuildFlowItemsStepDefHelper:
# RECURSIVE_BUILD (its default), NON_RECURSIVE_FORCED_BUILD,
# RECURSIVE_FORCED_BUILD, RECURSIVE_MISSING_ONLY_BUILD. RECURSIVE_BUILD keeps
# the semantics of the previous custom-python scenario (build_dataset default).
_SCENARIO_BUILD_MODE = "RECURSIVE_BUILD"

# Bounded wait on a scenario run: the recipes profile the whole base dataset,
# so minutes are normal; beyond the cap the DSS run continues on its own and a
# later re-run of the stage re-attaches to it (get_current_run).
_SCENARIO_WAIT_TIMEOUT_S = 1800
_SCENARIO_POLL_S = 10
_SCENARIO_PROGRESS_EVERY_S = 300


def build_scenario_steps(spec):
    """Steps of the step-based refresh scenario: ONE visual build step per
    knowledge dataset, run sequentially by the scenario engine.

    'build_flowitem' is a documented step type (get_raw_steps); the params
    mirror what the documented in-scenario helper (BuildFlowItemsStepDefHelper
    .add_dataset) produces: a builds list of {type DATASET, itemId,
    partitionsSpec} plus the jobType build mode. One dataset per step so the
    scenario UI shows progress dataset by dataset and a failure names its
    dataset in the run report.
    """
    steps = []
    for name in spec.knowledge_datasets:
        steps.append({
            "id": "build_%s" % name,
            "name": "Build %s" % name,
            "type": "build_flowitem",
            "params": {
                "builds": [{"type": "DATASET", "itemId": name, "partitionsSpec": ""}],
                "jobType": _SCENARIO_BUILD_MODE,
            },
        })
    return steps


def _scenario_item_ids(item):
    """(id, name) of one list_scenarios item, robust to dict or listitem shape."""
    if isinstance(item, dict):
        return item.get("id"), item.get("name")
    return getattr(item, "id", None), getattr(item, "name", None)


def scenario_exists(project, name):
    try:
        for s in project.list_scenarios():
            if name in _scenario_item_ids(s):
                return True
        return False
    except Exception as exc:
        raise ExistenceCheckError("could not list scenarios: %s" % exc)


def scenario_id_by_name(project, name):
    """Id of the scenario whose name (or id) is ``name``, or None.

    Goes through the documented list API (both item shapes) then get_scenario,
    because create_scenario derives the id from the name server-side.
    """
    try:
        for s in project.list_scenarios():
            s_id, s_name = _scenario_item_ids(s)
            if name in (s_id, s_name):
                return s_id
        return None
    except Exception as exc:
        raise ExistenceCheckError("could not list scenarios: %s" % exc)


def ensure_refresh_scenario(ctx, spec, hour=3):
    """Create the refresh scenario (STEP-BASED, INACTIVE by default).

    One visual 'Build' step per knowledge dataset (readable and editable in the
    scenario UI), the daily trigger defined but the scenario NOT activated: the
    guided assistant runs the first build itself, then a human flips the
    scenario on in DSS to keep the data fresh (and may add a 'dataset modified'
    trigger in the scenario UI). The trigger is its OWN action: a trigger
    failure must show as FAILED in the report (a silently missing trigger would
    never be repaired, since reruns skip the scenario by name).
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
        definition = {"params": {"steps": build_scenario_steps(spec)}}
        scenario = ctx.project.create_scenario(spec.scenario_name, "step_based",
                                               definition=definition)
        # PROVE the steps landed (documented raw_steps read-back): an empty
        # step list would make a scenario that runs green while building
        # nothing, and the guided first build would then chase a no-op.
        raw_steps = getattr(scenario.get_settings(), "raw_steps", None) or []
        if len(raw_steps) != len(spec.knowledge_datasets):
            raise RuntimeError(
                "scenario %s was created but holds %d step(s) instead of %d: "
                "delete it in DSS, then re-run this step"
                % (spec.scenario_name, len(raw_steps), len(spec.knowledge_datasets)))
        return scenario

    scenario = ctx.act("scenario",
                       "create INACTIVE step-based scenario %s (one build step per "
                       "knowledge dataset: %s; enable it in DSS after review to keep "
                       "the data fresh)"
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


def _first_error(details_or_step):
    """The first_error_details dict of a run/step details object, or None.

    The property is documented but raises when the run holds no serialized
    error, so it is read defensively (a missing message must never mask the
    outcome itself).
    """
    try:
        error = details_or_step.first_error_details
    except Exception:
        return None
    return error if isinstance(error, dict) else None


def scenario_run_error_message(run):
    """Readable error of a finished failed run, from the documented details
    (DSSScenarioRunDetails.first_error_details, then per-step), or None."""
    try:
        details = run.get_details()
    except Exception:
        return None
    error = _first_error(details)
    if error is None:
        for step in (getattr(details, "steps", None) or []):
            error = _first_error(step)
            if error is not None:
                break
    if not error:
        return None
    message = error.get("message") or error.get("title") or ""
    return str(message)[:500] or None


def run_scenario_and_wait(ctx, spec, timeout_seconds=_SCENARIO_WAIT_TIMEOUT_S,
                          poll_seconds=_SCENARIO_POLL_S):
    """Run the refresh scenario and wait (bounded) for its outcome.

    Called by the guided assistant's first-build stage (an explicit operator
    click, executed in a console background job). If a run of this scenario is
    already in progress (backend restart, double click), it ATTACHES to it
    instead of firing a second one. Journals the lifecycle on ctx (start,
    periodic progress, final outcome) so the console shows the build live.

    Returns {"outcome": ..., "error": ...} where outcome is a documented run
    outcome (SUCCESS / WARNING / FAILED / ABORTED) or one of the synthetic
    NOT_FOUND / NOT_STARTED / TIMEOUT / UNKNOWN when no outcome was observed.
    """
    name = spec.scenario_name
    try:
        scenario_id = scenario_id_by_name(ctx.project, name)
    except ExistenceCheckError as exc:
        ctx.fail("scenario_run", str(exc))
        return {"outcome": "NOT_FOUND", "error": str(exc)}
    if not scenario_id:
        detail = "scenario %s not found in the project" % name
        ctx.fail("scenario_run", detail)
        return {"outcome": "NOT_FOUND", "error": detail}
    scenario = ctx.project.get_scenario(scenario_id)

    try:
        run = scenario.get_current_run()
    except Exception:
        run = None
    if run is not None:
        ctx.done("scenario_run_start",
                 "a run of scenario %s is already in progress: attaching to it" % name)
    else:
        try:
            trigger_fire = scenario.run()
            run = trigger_fire.wait_for_scenario_run(no_fail=True)
        except Exception as exc:
            ctx.fail("scenario_run_start", "could not start scenario %s: %s" % (name, exc))
            return {"outcome": "NOT_STARTED", "error": str(exc)}
        if run is None:
            detail = ("the trigger fire was cancelled before a run started "
                      "(another run may be pending): check the scenario screen in DSS")
            ctx.fail("scenario_run_start", detail)
            return {"outcome": "NOT_STARTED", "error": detail}
        ctx.done("scenario_run_start", "scenario %s run started" % name)

    waited = 0
    last_progress = 0
    step = poll_seconds if poll_seconds > 0 else 1
    while True:
        try:
            if not run.running:
                break
        except Exception as exc:
            ctx.fail("scenario_run", "lost the run state while polling: %s" % exc)
            return {"outcome": "UNKNOWN", "error": str(exc)}
        if waited >= timeout_seconds:
            detail = ("still running after %d min: giving up the WAIT (the DSS run "
                      "continues on its own; re-run this stage later to re-attach)"
                      % max(1, timeout_seconds // 60))
            ctx.fail("scenario_run", detail)
            return {"outcome": "TIMEOUT", "error": detail}
        if waited - last_progress >= _SCENARIO_PROGRESS_EVERY_S:
            last_progress = waited
            ctx.done("scenario_run_progress",
                     "build still running (%d min elapsed)" % (waited // 60))
        if poll_seconds > 0:
            time.sleep(poll_seconds)
        waited += step
        try:
            run.refresh()
        except Exception as exc:
            ctx.fail("scenario_run", "lost the run while polling: %s" % exc)
            return {"outcome": "UNKNOWN", "error": str(exc)}

    try:
        outcome = str(run.outcome or "UNKNOWN")
    except Exception:
        outcome = "UNKNOWN"
    if outcome in ("SUCCESS", "WARNING"):
        ctx.done("scenario_run", "scenario %s finished: %s" % (name, outcome))
        return {"outcome": outcome, "error": None}
    error = scenario_run_error_message(run)
    ctx.fail("scenario_run", "scenario %s finished: %s%s"
             % (name, outcome, (" :: " + error) if error else ""))
    return {"outcome": outcome, "error": error}
