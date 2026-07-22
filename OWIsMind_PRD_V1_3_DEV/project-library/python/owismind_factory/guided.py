"""Guided run: the step-by-step assistant that drives one domain end to end.

One guided run walks an operator from "pick a dataset" to "the orchestrator has
the new ask_<domain>_expert tool enabled", as a persistent state machine:

- AUTO stages call the existing factory engine (pipeline / builders) and record
  a live journal;
- MANUAL stages show exact French instructions; the operator does the action in
  DSS, clicks "C'est fait", and the stage VERIFIES against DSS before advancing
  (an unverified claim never advances the run);
- the whole run state is a plain dict persisted by guided_store (SQL), so a
  webapp reload or a backend restart resumes exactly where the operator was.

This module owns the MACHINE (stages, transitions, verifications, instruction
texts). It performs no persistence and no HTTP: the console backend loads the
run, calls one of the three entry points (start_run / run_current_stage /
verify_current_stage), then saves the returned run.

Stage protocol:
- run(env, state, ctx)   -> (outcome, problems)   outcome in DONE/WAITING/FAILED
- check(env, state)      -> (ok, problems, notes)  used by verify AND by the
  advance walk (precheck stages auto-complete when already satisfied).
Statuses seen by the frontend: pending / ready / running / waiting_user /
done / failed (kind is only a display hint).
"""

import uuid

from . import agent_builder, flow_builder, hub, pipeline, registry, removal, semantic_builder
from . import tool_builder, wizard as wizard_module
from . import guided_store
from .fctx import BLOCKED, FAILED, FactoryContext
from .flow_builder import ExistenceCheckError
from .spec import DomainSpec

# Run statuses (row-level).
RUN_ACTIVE = "active"
RUN_DONE = "done"
RUN_ABANDONED = "abandoned"

# Stage statuses (frontend contract, FROZEN).
PENDING = "pending"
READY = "ready"
RUNNING = "running"
WAITING = "waiting_user"
DONE = "done"
STAGE_FAILED = "failed"

# run() outcomes.
_OUT_DONE = "done"
_OUT_WAITING = "waiting"
_OUT_FAILED = "failed"

STATE_VERSION = 1

_JOURNAL_MAX = 60
_DETAIL_MAX = 600

STAGE_ORDER = [
    "preflight", "plan", "infra", "first_build", "profile_review", "wizard",
    "brain", "template", "agent_code", "code_agent", "capability", "smoke",
    "enable",
]

_STAGE_META = {
    "preflight": ("auto", "Vérifications préalables",
                  "Contrôle du hub, du dataset (dont partitionnement) et des collisions de noms."),
    "plan": ("auto", "Plan d'ensemble (simulation)",
             "Simulation complète : liste tout ce qui sera créé, sans rien toucher."),
    "infra": ("auto", "Création de l'infrastructure Flow",
              "Zone, 3 datasets de connaissance, 3 recettes et scénario de refresh."),
    "first_build": ("auto", "Premier build des connaissances",
                    "Lance le scénario de build et attend son résultat "
                    "(plusieurs minutes : profil, index de valeurs, catalogue)."),
    "profile_review": ("manual", "Relecture du profil",
                       "Toi : relire le dataset profil généré (descriptions, énumérations)."),
    "wizard": ("wizard", "Cerveau sémantique (wizard IA)",
               "Rédiger le brouillon du modèle sémantique et répondre aux questions."),
    "brain": ("auto", "Application au modèle + tool",
              "Instructions, golden queries validées, indexation, création du tool."),
    "template": ("auto", "Moteur d'agent (template)",
                 "Vérifie que le moteur d'agent est disponible dans le hub."),
    "agent_code": ("auto", "Génération du code de l'agent",
                   "Génère le code du sous-agent avec les bons identifiants."),
    "code_agent": ("manual", "Création du Code Agent",
                   "Toi : créer le Code Agent (env 3.11) et coller le code généré."),
    "capability": ("auto", "Enregistrement de la capability",
                   "Ajoute le nouvel expert au registre du hub (désactivé)."),
    "smoke": ("manual", "Test de bout en bout",
              "Toi : poser les questions de test dans la webapp principale."),
    "enable": ("auto", "Activation dans l'orchestrateur",
               "Active la capability : l'orchestrateur gagne le nouvel outil."),
}

# ----------------------------------------------------------- REMOVAL run type
# A removal run walks the operator through deleting everything one capability
# owns, one CONFIRMED stage at a time (spec 2026-07-22). Safety order: detach
# first (disable), then leaves before trunks. The marker lives in
# state["removal"] because guided_store only persists the state_json.

REMOVAL_STAGE_ORDER = [
    "inventory", "disable", "delete_tool", "delete_agent", "delete_model",
    "delete_scenario", "delete_recipes", "delete_datasets", "delete_zone",
    "catalog_cleanup", "hub_cleanup", "final_check",
]

_REMOVAL_STAGE_META = {
    "inventory": ("auto", "Inventaire de la capacité",
                  "Sonde ce qui existe réellement (datasets, recettes, scénario, "
                  "modèle, tool, agent, hub). Rien n'est supprimé à cette étape."),
    "disable": ("auto", "Désactivation de la capability",
                "Coupe le routage de l'orchestrateur vers cet expert avant toute "
                "suppression."),
    "delete_tool": ("auto", "Suppression du tool",
                    "Supprime le tool Semantic Model Query du domaine."),
    "delete_agent": ("auto", "Suppression du Code Agent",
                     "Supprime le Code Agent du domaine."),
    "delete_model": ("auto", "Suppression du modèle sémantique",
                     "Supprime le modèle sémantique du domaine."),
    "delete_scenario": ("auto", "Suppression du scénario",
                        "Supprime le scénario de refresh du domaine."),
    "delete_recipes": ("auto", "Suppression des recettes",
                       "Supprime les recettes de connaissance du domaine."),
    "delete_datasets": ("auto", "Suppression des datasets de connaissance",
                        "Supprime les datasets dérivés et leurs tables SQL "
                        "(reconstructibles). Le dataset SOURCE n'est JAMAIS touché."),
    "delete_zone": ("auto", "Suppression de la zone Flow",
                    "Supprime la zone du domaine si elle est vide, sinon la "
                    "laisse en place."),
    "catalog_cleanup": ("auto", "Nettoyage du catalogue partagé",
                        "Supprime les lignes de cette capability dans le dataset "
                        "catalogue commun (SQL paramétré + COMMIT)."),
    "hub_cleanup": ("auto", "Nettoyage du hub",
                    "Supprime la config wizard, les prompts, le code généré, puis "
                    "l'entrée de capabilities.json (backup automatique)."),
    "final_check": ("auto", "Vérification finale",
                    "Re-sonde l'absence de tout et rappelle le re-save de "
                    "l'orchestrateur."),
}

_ALL_STAGE_META = dict(_STAGE_META)
_ALL_STAGE_META.update(_REMOVAL_STAGE_META)

# Stages the advance walk may auto-complete, ONLY on a POSITIVE precheck (see
# _PRECHECKS below): "could not verify" must never be read as "already done".
# first_build is an AUTO stage but stays precheck-skippable: when the knowledge
# datasets provably have rows already, re-running the build scenario is waste.
_PRECHECK_STAGES = ("first_build", "wizard", "template", "code_agent")


class _Env(object):
    """Bundles what stage handlers need (no persistence, no HTTP)."""

    def __init__(self, project, settings, executor_factory=None):
        self.project = project
        self.settings = settings or {}
        self.executor_factory = executor_factory

    def store(self):
        return guided_store.GuidedStore(
            self.settings.get("sql_connection") or "SQL_owi",
            getattr(self.project, "project_key", "") or "",
            executor_factory=self.executor_factory)


# --------------------------------------------------------------------- helpers

def wizard_config_path(domain):
    """Hub path of a domain's wizard draft (same convention as notebook 04)."""
    return "%s/wizard/%s-config.json" % (hub.HUB_ROOT, domain)


def _spec(state):
    return DomainSpec.from_dict(state.get("spec") or {})


def _stage(state, key):
    return state["stages"][key]


def _wizard_config(env, state):
    config = hub.read_json(env.project, wizard_config_path(state["spec"]["domain"]))
    if isinstance(config, dict) and "error" not in config:
        return config
    return None


def _gates(env):
    """Probe gates from the hub (same policy as the console: hub only, and
    schema hints count only when the write probe confirmed them)."""
    probe = hub.read_json(env.project, hub.HUB_ROOT + "/probe_results.json") or {}
    discovery = probe.get("suggested_discovery")
    schema_hints = probe.get("suggested_schema_hints")
    if schema_hints and not schema_hints.get("confirmed"):
        schema_hints = None
    return discovery, schema_hints


def _dataset_is_partitioned(project, name):
    """True/False when readable, None when the settings cannot be read (callers
    must treat None as "unknown", never as a verdict)."""
    raw = None
    try:
        raw = project.get_dataset(name).get_settings().get_raw()
    except Exception:
        try:
            raw = project.get_dataset(name).get_definition()
        except Exception:
            return None
    if not isinstance(raw, dict):
        return None
    dims = (raw.get("partitioning") or {}).get("dimensions") or []
    return bool(dims)


def _journal_slice(ctx, start_index):
    out = []
    for action in ctx.actions[start_index:]:
        out.append({
            "step": str(action.get("step") or ""),
            "status": str(action.get("status") or ""),
            "detail": str(action.get("detail") or "")[:_DETAIL_MAX],
        })
    return out[-_JOURNAL_MAX:]


def _subset_failed(journal):
    return [a for a in journal if a.get("status") in (FAILED, BLOCKED)]


# --------------------------------------------------------- instruction builders
# French operator texts. NEVER use U+2014 / U+2013 here (project rule #9).

def _instr_profile_review(env, state):
    spec = _spec(state)
    return (
        "1. Ouvre le dataset %s (onglet Explore).\n"
        "2. Relis les descriptions de colonnes, les synonymes et les énumérations "
        "(la colonne d'origine won/open si tu as empilé deux tables, les statuts, "
        "les types).\n"
        "3. Corrige ce qui est faux via le dataset d'overrides (il gagne toujours), "
        "puis rebuilde le profil si tu as modifié un override.\n"
        "4. Clique sur C'est fait quand le profil te semble juste : c'est lui qui "
        "nourrit le wizard et l'agent." % spec.profile_dataset)


def _instr_wizard(env, state):
    spec = _spec(state)
    return (
        "1. Clique sur Rédiger le brouillon (IA) : le wizard lit le profil %s et "
        "propose un brouillon de modèle sémantique (1 appel LLM, aucune ligne de "
        "données envoyée).\n"
        "2. Lis ses questions de clarification (métrique par défaut, clé distincte, "
        "axe temps) et réponds dans les champs.\n"
        "3. Clique sur Re-rédiger avec mes réponses, puis relis le brouillon.\n"
        "4. Clique sur Vérifier et continuer : je vérifie que la config est bien "
        "enregistrée dans le hub." % spec.profile_dataset)


def _instr_tool_manual(env, state):
    spec = _spec(state)
    config = _wizard_config(env, state)
    description = tool_builder.build_tool_description(spec, config)
    return (
        "La création automatique du tool n'est pas possible sur cette instance "
        "(sonde non confirmée). Crée-le à la main (2 minutes) :\n"
        "1. Agents & GenAI Models puis Tools puis New tool : type Semantic Model "
        "Query, nom EXACT %s.\n"
        "2. Lie-le au modèle sémantique %s.\n"
        "3. Agent mode OFF (pipeline linéaire), LLM vertex_ai/claude-sonnet-4-6, "
        "accès aux datasets en tant qu'utilisateur appelant.\n"
        "4. Colle cette Description for LLM :\n%s\n"
        "5. Clique sur C'est fait : je retrouve le tool par son nom et je note son id."
        % (spec.semantic_tool_name, spec.semantic_model_name, description))


def _instr_template(env, state):
    return (
        "Le moteur d'agent (template) manque dans le hub. Un copier-coller :\n"
        "1. Ouvre la project library (icône </> puis Library) du projet.\n"
        "2. Sous python/owismind_hub, crée le dossier templates puis le fichier "
        "dataset_expert.py.\n"
        "3. Colle dedans le contenu du Code Agent revenus live (SalesDrive_revenue_expert, "
        "onglet Code) ou du fichier repo GenAI/Agents/SalesDrive_revenue_expert.py.\n"
        "4. Clique sur C'est fait : je vérifie la présence et la forme du template.")


def _instr_code_agent(env, state):
    spec = _spec(state)
    generated = (state.get("captured") or {}).get("generated_path") \
        or "%s/generated/%s.py" % (hub.HUB_ROOT, spec.agent_name)
    return (
        "Crée le Code Agent (LE collage manuel restant) :\n"
        "1. Agents & GenAI Models puis New Agent puis Code Agent, nom EXACT %s.\n"
        "2. Onglet Settings : sélectionne l'environnement Python 3.11.\n"
        "3. Onglet Code : colle le contenu du fichier généré %s "
        "(project library).\n"
        "4. Vérifie dans le CONFIG du code que SEMANTIC_TOOL_ID vaut %s "
        "(jamais FILL_ME_TOOL_ID), puis sauvegarde.\n"
        "5. Clique sur C'est fait : je retrouve l'agent par son nom et je note son id."
        % (spec.agent_name, generated,
           (state.get("captured") or {}).get("tool_id") or "l'id du tool créé"))


def _instr_smoke(env, state):
    spec = _spec(state)
    return (
        "Teste le nouvel expert de bout en bout dans la webapp principale OWIsMind "
        "(ouvre une NOUVELLE conversation) :\n"
        "1. Une question simple du domaine, par exemple : combien de lignes par "
        "catégorie dans %s ?\n"
        "2. Un classement : top 10 par la métrique principale.\n"
        "3. Que contient la donnée %s ? (réponse descriptive, zéro SQL).\n"
        "4. Une question REVENUS pour vérifier que le routage existant n'a pas bougé.\n"
        "Vérifie que la timeline montre le sous-agent au travail et que le panneau "
        "Evidence affiche le SQL exécuté. NB : la capability est encore désactivée "
        "à ce stade, le routage direct se teste après activation ; ici tu valides "
        "que l'existant ne régresse pas et que les objets créés répondent (tu peux "
        "tester le tool dans son écran DSS, bouton Test). Clique sur C'est fait "
        "pour passer à l'activation." % (spec.base_dataset, spec.base_dataset))


# ------------------------------------------------------------------ stage: runs

def _run_preflight(env, state, ctx):
    spec = _spec(state)
    problems = []

    caps = hub.read_capabilities(env.project)
    if caps is None:
        problems.append("Hub absent ou illisible (/python/owismind_hub/capabilities.json) : "
                        "pousse le hub (notebook 01) avant de continuer.")
        ctx.fail("preflight_hub", "capabilities.json unreadable")
        caps = {}
    else:
        ctx.done("preflight_hub", "hub ready (%d capabilities)" % len(caps))

    if not (env.settings.get("sql_connection") or "").strip():
        problems.append("Aucune connexion SQL dans factory_settings.json (clé sql_connection).")
        ctx.fail("preflight_settings", "sql_connection missing")
    elif not (env.settings.get("code_env_311") or "").strip():
        ctx.skip("preflight_settings",
                 "code_env_311 vide dans factory_settings.json : les recettes et le Code "
                 "Agent utiliseront l'env par défaut du projet (renseigne-le de préférence)")
    else:
        ctx.done("preflight_settings", "sql_connection + code_env_311 configured")

    try:
        if flow_builder.dataset_exists(env.project, spec.base_dataset):
            ctx.done("preflight_dataset", "base dataset %s found" % spec.base_dataset)
            partitioned = _dataset_is_partitioned(env.project, spec.base_dataset)
            if partitioned is True:
                problems.append(
                    "Le dataset %s est PARTITIONNÉ : le scénario de build échouera "
                    "(erreur de partition). Ouvre le dataset, Settings puis Partitioning, "
                    "mets Not partitioned (ou choisis un autre dataset), puis relance "
                    "cette étape." % spec.base_dataset)
                ctx.fail("preflight_partitioning", "dataset %s is partitioned" % spec.base_dataset)
            elif partitioned is None:
                ctx.skip("preflight_partitioning",
                         "partitionnement illisible : vérifie à la main Settings > Partitioning")
            else:
                ctx.done("preflight_partitioning", "dataset not partitioned")
        else:
            problems.append("Dataset %s introuvable dans le projet : choisis un dataset "
                            "existant (ou importe la table d'abord)." % spec.base_dataset)
            ctx.fail("preflight_dataset", "base dataset %s not found" % spec.base_dataset)
    except ExistenceCheckError as exc:
        problems.append("Impossible de lister les datasets (%s) : réessaie." % exc)
        ctx.fail("preflight_dataset", str(exc))

    if spec.capability_key in caps:
        problems.append("La capability %s existe déjà dans le hub : choisis une autre clé "
                        "de domaine (une capability activée par domaine)." % spec.capability_key)
        ctx.fail("preflight_names", "capability key collision")
    else:
        for warning in spec.preflight(existing_capability_keys=list(caps.keys()),
                                      existing_domains=[c.get("domain") for c in caps.values()
                                                        if isinstance(c, dict)]):
            ctx.skip("preflight_names", warning)
        ctx.done("preflight_names", "no blocking name collision")

    probe = hub.read_json(env.project, hub.HUB_ROOT + "/probe_results.json")
    if not probe:
        ctx.skip("preflight_probe",
                 "sonde (notebook 00) non exécutée : les étapes tool et Code Agent "
                 "se feront en manuel guidé")
    else:
        ctx.done("preflight_probe", "probe results present")

    # Hub-awareness of the LIVE orchestrator (best-effort, needs confirmed probe
    # hints to read its code). A v1.2 orchestrator has its CAPABILITIES embedded
    # and ignores capabilities.json entirely: the whole run would end with an
    # enabled expert that stays INVISIBLE (field failure 2026-07-21).
    _discovery, schema_hints = _gates(env)
    orchestrator_id = str(env.settings.get("orchestrator_agent_id") or "").strip()
    if orchestrator_id and schema_hints \
            and schema_hints.get("internal_key") and schema_hints.get("code_key"):
        try:
            raw = agent_builder.read_agent_raw(env.project, orchestrator_id)
            versions = raw.get("versions") or []
            version = versions[-1] if versions else {}
            for candidate in versions:
                if candidate.get("versionId") == raw.get("activeVersion"):
                    version = candidate
            code = (version.get(schema_hints["internal_key"]) or {}).get(
                schema_hints["code_key"]) or ""
            if code and "owismind_hub" not in code:
                ctx.skip("preflight_orchestrator",
                         "l'orchestrateur live (id %s) ne charge PAS le hub (code v1.2 ?) : "
                         "re-colle GenAI/Agents/OWIsMind_orchestrator.py (env 3.11) AVANT "
                         "l'activation finale, sinon le nouvel expert restera invisible"
                         % orchestrator_id)
            elif code:
                ctx.done("preflight_orchestrator", "live orchestrator is hub-aware")
        except Exception:
            pass  # best-effort: never block preflight on this read

    template = hub.read_text(env.project, hub.TEMPLATE_AGENT_PATH)
    if not template:
        ctx.skip("preflight_template",
                 "template moteur d'agent absent du hub : l'étape Moteur d'agent te "
                 "guidera pour le coller (un copier-coller)")
    else:
        ctx.done("preflight_template", "engine template present in the hub")

    return (_OUT_DONE, []) if not problems else (_OUT_FAILED, problems)


def _run_plan(env, state, ctx):
    spec = _spec(state)
    discovery, schema_hints = _gates(env)
    inner = FactoryContext(project=env.project, dry_run=True, abort_on_failure=False)
    pipeline.create_domain(inner, spec,
                           wizard_config=_wizard_config(env, state),
                           discovery=discovery, schema_hints=schema_hints)
    ctx.actions.extend(inner.actions)
    if inner.has_failures():
        return _OUT_FAILED, ["La simulation a rencontré une erreur (voir le journal)."]
    return _OUT_DONE, []


_INFRA_STEPS = ["source_dataset", "zone", "knowledge_datasets", "recipes", "scenario"]


def _run_infra(env, state, ctx):
    spec = _spec(state)
    start = len(ctx.actions)
    pipeline.create_domain(ctx, spec,
                           wizard_config=None, discovery=None, schema_hints=None,
                           steps=_INFRA_STEPS)
    bad = _subset_failed(ctx.actions[start:])
    if bad:
        return _OUT_FAILED, ["%s : %s" % (a["step"], a["detail"][:200]) for a in bad]
    return _OUT_DONE, []


def _run_first_build(env, state, ctx):
    """AUTO first build: run the refresh scenario, wait for its outcome, then
    prove the knowledge datasets landed. A failed run surfaces the DSS error
    with the exact fix path; the operator fixes in DSS and re-runs the stage
    (a still-running DSS run is re-attached, never doubled)."""
    spec = _spec(state)
    result = flow_builder.run_scenario_and_wait(ctx, spec)
    outcome = (result or {}).get("outcome") or "UNKNOWN"
    error = (result or {}).get("error")

    if outcome == "TIMEOUT":
        return _OUT_FAILED, [
            "Le build tourne toujours côté DSS après le délai d'attente : ce n'est pas "
            "forcément une erreur. Ouvre le scénario %s (onglet Last runs) pour suivre "
            "le run, puis relance cette étape : elle se rattachera au run en cours."
            % spec.scenario_name]
    if outcome not in ("SUCCESS", "WARNING"):
        problems = ["Le scénario %s a terminé en %s%s."
                    % (spec.scenario_name, outcome, (" : %s" % error) if error else "")]
        problems.append(
            "Ouvre le scénario %s dans DSS (onglet Last runs) pour lire le log complet, "
            "corrige la cause, puis relance cette étape." % spec.scenario_name)
        problems.append(
            "Si l'erreur parle de partition : ouvre le dataset %s (et ses sources), "
            "Settings puis Partitioning, mets Not partitioned, puis relance cette étape."
            % spec.base_dataset)
        return _OUT_FAILED, problems

    # The run finished green: now PROVE the knowledge landed. Row counts that
    # cannot be verified are tolerated (the scenario outcome is the positive
    # signal); a provably absent or EMPTY dataset still fails loudly.
    problems = []
    for dataset, verdict in _first_build_status(env, state):
        if verdict == "absent":
            problems.append("Dataset %s introuvable après le build : relance l'étape de "
                            "création de l'infrastructure." % dataset)
        elif isinstance(verdict, str) and verdict.startswith("list_error:"):
            problems.append("Impossible de lister les datasets (%s) : réessaie."
                            % verdict.split(":", 1)[1])
        elif verdict is False:
            problems.append("Le scénario a réussi mais le dataset %s est VIDE : ouvre la "
                            "recette %s dans DSS et regarde son log de job."
                            % (dataset, spec.recipe_name(dataset)))
    return (_OUT_DONE, []) if not problems else (_OUT_FAILED, problems)


_BRAIN_STEPS = ["semantic_model", "semantic_config", "semantic_index", "semantic_tool"]


def _run_brain(env, state, ctx):
    spec = _spec(state)
    config = _wizard_config(env, state)
    if config is None:
        return _OUT_FAILED, ["Config du wizard introuvable dans le hub : refais l'étape wizard."]
    discovery, schema_hints = _gates(env)
    start = len(ctx.actions)
    pipeline.create_domain(ctx, spec,
                           wizard_config=config, discovery=discovery,
                           schema_hints=schema_hints, steps=_BRAIN_STEPS)
    bad = _subset_failed(ctx.actions[start:])

    model = semantic_builder.find_model_by_name(env.project, spec.semantic_model_name)
    model_id = getattr(model, "id", None) if model is not None else None
    if model_id:
        state["captured"]["model_id"] = model_id
    else:
        return _OUT_FAILED, (["Modèle sémantique %s introuvable après l'exécution."
                              % spec.semantic_model_name]
                             + ["%s : %s" % (a["step"], a["detail"][:200]) for a in bad])

    if bad:
        return _OUT_FAILED, ["%s : %s" % (a["step"], a["detail"][:200]) for a in bad]

    try:
        tool_id = tool_builder.tool_exists(env.project, spec.semantic_tool_name)
    except ExistenceCheckError:
        tool_id = None
    if tool_id:
        state["captured"]["tool_id"] = tool_id
        return _OUT_DONE, []
    return _OUT_WAITING, []


def _check_brain(env, state):
    spec = _spec(state)
    try:
        tool_id = tool_builder.tool_exists(env.project, spec.semantic_tool_name)
    except ExistenceCheckError as exc:
        return False, ["Impossible de lister les tools (%s) : réessaie." % exc]
    if not tool_id:
        return False, ["Tool %s introuvable : vérifie le nom EXACT (copie-le depuis "
                       "les instructions)." % spec.semantic_tool_name]
    state["captured"]["tool_id"] = tool_id
    return True, []


def _template_ok(env):
    text = hub.read_text(env.project, hub.TEMPLATE_AGENT_PATH)
    return bool(text) and 'PROFILE_DATASET = "' in text


def _run_template(env, state, ctx):
    if _template_ok(env):
        ctx.done("template", "engine template present (%s)" % hub.TEMPLATE_AGENT_PATH)
        return _OUT_DONE, []
    ctx.manual("template", "engine template missing in the hub: paste it (see instructions)")
    return _OUT_WAITING, []


def _check_template(env, state):
    if _template_ok(env):
        return True, []
    return False, ["Template toujours absent ou invalide : le fichier %s doit exister et "
                   "contenir le CONFIG du moteur (constante PROFILE_DATASET)."
                   % hub.TEMPLATE_AGENT_PATH]


def _run_agent_code(env, state, ctx):
    spec = _spec(state)
    template = agent_builder.load_engine_template(env.project)
    if not template:
        return _OUT_FAILED, ["Template moteur absent : refais l'étape Moteur d'agent."]
    tool_id = (state.get("captured") or {}).get("tool_id") or ""
    if not tool_id:
        return _OUT_FAILED, ["Aucun id de tool capturé : refais l'étape Application au "
                             "modèle + tool."]
    _, schema_hints = _gates(env)
    try:
        code = agent_builder.generate_subagent_code(
            template, spec, tool_id,
            deploy_project=getattr(env.project, "project_key", None))
    except agent_builder.TemplateDriftError as exc:
        return _OUT_FAILED, [str(exc)]
    agent_ref = agent_builder.create_code_agent(
        ctx, spec, code, schema_hints,
        code_env=env.settings.get("code_env_311") or "")
    if agent_ref:
        state["captured"]["agent_id"] = agent_ref
    else:
        state["captured"]["generated_path"] = "%s/generated/%s.py" % (hub.HUB_ROOT,
                                                                      spec.agent_name)
    start_failed = [a for a in ctx.actions if a["status"] == FAILED and a["step"] == "code_agent"]
    if not agent_ref and start_failed:
        return _OUT_FAILED, [a["detail"][:200] for a in start_failed]
    return _OUT_DONE, []


def _check_code_agent(env, state):
    spec = _spec(state)
    try:
        agent_id = agent_builder.agent_exists(env.project, spec.agent_name)
    except ExistenceCheckError as exc:
        return False, ["Impossible de lister les agents (%s) : réessaie." % exc]
    if not agent_id:
        return False, ["Code Agent %s introuvable : vérifie le nom EXACT (copie-le depuis "
                       "les instructions) et sauvegarde l'agent." % spec.agent_name]
    state["captured"]["agent_id"] = "agent:%s" % agent_id
    return True, []


def _run_capability(env, state, ctx):
    spec = _spec(state)
    agent_id = (state.get("captured") or {}).get("agent_id")
    if not agent_id:
        return _OUT_FAILED, ["Aucun id d'agent capturé : refais l'étape Création du Code Agent."]
    entry = registry.capability_entry(spec, agent_id)
    config = _wizard_config(env, state)
    if config and config.get("planner_description"):
        entry["planner_description"] = config["planner_description"]

    def _append():
        hub.append_capability(env.project, spec.capability_key, entry)
        return True

    try:
        result = ctx.act("capability",
                         "append capability %s (agent %s, enabled=false jusqu'au smoke test)"
                         % (spec.capability_key, agent_id), _append)
    except ValueError as exc:
        return _OUT_FAILED, [str(exc)]
    if not result:
        failures = [a for a in ctx.actions if a["status"] == FAILED and a["step"] == "capability"]
        return _OUT_FAILED, [a["detail"][:300] for a in failures] or \
            ["Écriture de la capability impossible (voir le journal)."]
    return _OUT_DONE, []


def _check_smoke(env, state):
    spec = _spec(state)
    caps = hub.read_capabilities(env.project) or {}
    if spec.capability_key not in caps:
        return False, ["La capability %s a disparu du hub : refais l'étape précédente."
                       % spec.capability_key]
    return True, []


def _run_enable(env, state, ctx):
    spec = _spec(state)
    caps = hub.read_capabilities(env.project)
    if not caps or spec.capability_key not in caps:
        return _OUT_FAILED, ["Capability %s introuvable dans le hub." % spec.capability_key]
    caps[spec.capability_key]["enabled"] = True

    def _write():
        hub.write_capabilities(env.project, caps)
        return True

    try:
        result = ctx.act("enable",
                         "enable capability %s : l'orchestrateur charge le hub au démarrage "
                         "de chaque agent, le tool %s devient actif à la prochaine "
                         "conversation" % (spec.capability_key, spec.orchestrator_tool_name),
                         _write)
    except ValueError as exc:
        return _OUT_FAILED, [str(exc)]
    if not result:
        failures = [a for a in ctx.actions if a["status"] == FAILED and a["step"] == "enable"]
        return _OUT_FAILED, [a["detail"][:300] for a in failures] or \
            ["Activation impossible (voir le journal)."]
    return _OUT_DONE, []


# ---------------------------------------------------------------- stage: checks

def _first_build_status(env, state):
    """Per-dataset build verdicts: list of (dataset, verdict) with verdict in
    True (has rows) / False (provably empty) / None (cannot verify)."""
    spec = _spec(state)
    verdicts = []
    store = None
    try:
        store = env.store()
    except guided_store.GuidedStoreError:
        store = None
    for dataset in (spec.profile_dataset, spec.value_index_dataset):
        try:
            if not flow_builder.dataset_exists(env.project, dataset):
                verdicts.append((dataset, "absent"))
                continue
        except ExistenceCheckError as exc:
            verdicts.append((dataset, "list_error:%s" % exc))
            continue
        table = None
        try:
            table = wizard_module.get_physical_table(env.project, dataset)
        except Exception:
            table = None
        if not table or store is None:
            verdicts.append((dataset, None))
            continue
        verdicts.append((dataset, store.table_has_rows(table)))
    return verdicts


def _precheck_first_build(env, state):
    """Advance-walk precheck: skip the stage ONLY when every dataset PROVABLY
    has rows. Unknown is never good enough to skip a human step."""
    verdicts = _first_build_status(env, state)
    ok = bool(verdicts) and all(v is True for _d, v in verdicts)
    return ok, []


def _check_profile_review(env, state):
    spec = _spec(state)
    try:
        if flow_builder.dataset_exists(env.project, spec.profile_dataset):
            return True, []
    except ExistenceCheckError as exc:
        return False, ["Impossible de lister les datasets (%s) : réessaie." % exc]
    return False, ["Dataset %s introuvable." % spec.profile_dataset]


def _check_wizard(env, state):
    config = _wizard_config(env, state)
    if config is None:
        return False, ["Aucun brouillon valide dans le hub : clique d'abord sur Rédiger le "
                       "brouillon (IA), puis re-vérifie."]
    problems = []
    spec = _spec(state)
    drafted_for = (config.get("base_dataset") or "").strip()
    if drafted_for and drafted_for != spec.base_dataset:
        problems.append("Le brouillon du hub a été rédigé pour le dataset %s, pas pour %s "
                        "(reste d'un ancien run) : clique sur Rédiger le brouillon (IA) "
                        "pour le refaire sur le bon dataset." % (drafted_for, spec.base_dataset))
    if not (config.get("planner_description") or "").strip():
        problems.append("Le brouillon n'a pas de planner_description : re-rédige avec tes "
                        "réponses (c'est le texte de routage de l'orchestrateur).")
    if not config.get("attributes"):
        problems.append("Le brouillon n'a aucun attribut de colonne : le profil est-il "
                        "buildé et relu ? Re-rédige le brouillon.")
    return (len(problems) == 0), problems


def _precheck_wizard(env, state):
    """Advance-walk precheck: skip the wizard ONLY when a valid draft is PROVEN
    to target this run's dataset (missing provenance stamp = no skip)."""
    ok, problems = _check_wizard(env, state)
    if not ok:
        return False, problems
    config = _wizard_config(env, state) or {}
    return (config.get("base_dataset") or "").strip() == _spec(state).base_dataset, []


# ------------------------------------------------------------ removal stages

def _removal_info(state):
    return state.get("removal") or {}


def _removal_items(state, stage_key):
    inventory = _removal_info(state).get("inventory") or {}
    return (inventory.get("stages") or {}).get(stage_key) or []


def _apply_removal_inventory_cards(state):
    """Rewrite each deletion stage's card so the operator sees EXACTLY what a
    confirmed click will delete (kind, name, id, location) BEFORE launching."""
    inventory = _removal_info(state).get("inventory") or {}
    for stage_key in removal.DELETE_STAGE_KEYS:
        entry = state["stages"].get(stage_key)
        if not entry:
            continue
        _kind, _title, base_detail = _REMOVAL_STAGE_META[stage_key]
        items = (inventory.get("stages") or {}).get(stage_key) or []
        if not items:
            entry["detail_fr"] = base_detail + "\nRien à supprimer : déjà absent."
            continue
        lines = [base_detail]
        for item in items:
            line = "SUPPRIMER : %s %s" % (item["kind_fr"], item["name"])
            if item.get("id"):
                line += " [id %s]" % item["id"]
            line += " (%s)" % item["where_fr"]
            lines.append(line)
            if item.get("note_fr"):
                lines.append("  " + item["note_fr"])
        entry["detail_fr"] = "\n".join(lines)
    protected = inventory.get("protected") or []
    if protected and state["stages"].get("delete_datasets"):
        for item in protected:
            state["stages"]["delete_datasets"]["detail_fr"] += (
                "\nPROTÉGÉ (jamais supprimé) : %s" % item["name"])


def _run_removal_inventory(env, state, ctx):
    info = state["removal"]
    key = info.get("capability_key")
    caps = hub.read_capabilities(env.project) or {}
    entry = caps.get(key) or info.get("entry") or {}
    info["entry"] = entry
    orchestrator_id = str(env.settings.get("orchestrator_agent_id") or "").strip()
    if orchestrator_id and str(entry.get("agent_id") or "") == "agent:%s" % orchestrator_id:
        return _OUT_FAILED, ["Cette capability pointe l'orchestrateur lui-même : "
                             "suppression refusée."]
    inventory, problems = removal.build_inventory(env.project, key, entry,
                                                  env.settings)
    info["inventory"] = inventory
    _apply_removal_inventory_cards(state)
    for note in inventory.get("notes") or []:
        ctx.skip("inventory", note)
    for stage_key in removal.DELETE_STAGE_KEYS:
        for item in (inventory.get("stages") or {}).get(stage_key) or []:
            ctx.done("inventory", "à supprimer (%s) : %s %s"
                     % (stage_key, item["kind_fr"], item["name"]))
    # Spec safety rail: never start a removal over a live refresh run.
    for item in (inventory.get("stages") or {}).get("delete_scenario") or []:
        if removal.scenario_is_running(env.project, item["id"]) is True:
            problems.append("Le scénario %s est en cours d'exécution : attends "
                            "la fin de son run puis relance cette étape."
                            % item["name"])
    if problems:
        return _OUT_FAILED, problems
    if inventory.get("template_conflicts"):
        return _OUT_WAITING, []
    return _OUT_DONE, []


def _check_removal_inventory(env, state):
    # The "C'est fait" click IS the acknowledgment of the template conflicts.
    return True, []


def _instr_removal_inventory(env, state):
    conflicts = (_removal_info(state).get("inventory") or {}) \
        .get("template_conflicts") or []
    lines = ["ATTENTION : des objets de ce domaine servent de TEMPLATES à l'usine :"]
    lines += ["- %s" % c for c in conflicts]
    lines.append(
        "Tant que ces templates ne seront pas repointés dans factory_settings.json "
        "(project library), l'usine ne pourra PLUS créer de nouveau domaine. La "
        "suppression reste possible : clique sur C'est fait pour acquitter et "
        "continuer.")
    return "\n".join(lines)


def _run_removal_disable(env, state, ctx):
    key = _removal_info(state).get("capability_key")
    caps = hub.read_capabilities(env.project) or {}
    entry = caps.get(key)
    if entry is None:
        ctx.skip("disable", "capability %s already gone from the hub" % key)
        return _OUT_DONE, []
    if not entry.get("enabled"):
        ctx.skip("disable", "capability %s already disabled" % key)
        return _OUT_DONE, []

    def _write():
        hub.set_capability_enabled(env.project, key, False)
        return True

    try:
        result = ctx.act("disable",
                         "disable capability %s (the orchestrator stops routing "
                         "to this expert)" % key, _write)
    except (KeyError, ValueError) as exc:
        return _OUT_FAILED, [str(exc)]
    if not result:
        failures = [a for a in ctx.actions
                    if a["status"] == FAILED and a["step"] == "disable"]
        return _OUT_FAILED, [a["detail"][:300] for a in failures] or \
            ["Désactivation impossible (voir le journal)."]
    return _OUT_DONE, []


def _make_removal_delete_runner(stage_key):
    def _run(env, state, ctx):
        items = _removal_items(state, stage_key)
        if not items:
            ctx.skip(stage_key, "rien à supprimer pour cette étape")
            return _OUT_DONE, []
        manual, problems = removal.execute_delete_stage(
            env.project, stage_key, items, ctx)
        _removal_info(state).setdefault("manual", {})[stage_key] = manual
        if problems:
            return _OUT_FAILED, problems
        if manual:
            return _OUT_WAITING, []
        return _OUT_DONE, []
    return _run


def _make_removal_absent_checker(stage_key):
    def _check(env, state):
        items = _removal_items(state, stage_key)
        leftovers, problems = removal.verify_stage_absent(
            env.project, stage_key, items)
        if problems:
            return False, problems
        if leftovers:
            return False, ["Toujours présent dans DSS : %s. Supprime puis "
                           "re-vérifie." % ", ".join(i["name"] for i in leftovers)]
        return True, []
    return _check


def _make_instr_removal_manual(stage_key):
    def _instr(env, state):
        manual = (_removal_info(state).get("manual") or {}).get(stage_key) or []
        lines = ["La suppression automatique a été refusée pour :"]
        for item in manual:
            line = "- %s %s (%s)" % (item.get("kind_fr", "objet"),
                                     item.get("name", "?"),
                                     item.get("where_fr", "DSS"))
            if item.get("reason_fr"):
                line += " : " + item["reason_fr"]
            lines.append(line)
        lines.append("Supprime ces objets à la main dans DSS, puis clique sur "
                     "C'est fait : je vérifie leur absence avant de continuer.")
        return "\n".join(lines)
    return _instr


def _run_removal_catalog(env, state, ctx):
    key = _removal_info(state).get("capability_key")
    connection = env.settings.get("sql_connection") or "SQL_owi"

    def _clean():
        return removal.delete_catalog_rows(
            env.project, connection, key, executor_factory=env.executor_factory)

    status = ctx.act("catalog_cleanup",
                     "delete shared-catalog rows of capability %s "
                     "(parametrized SQL + COMMIT)" % key, _clean)
    if status is None:
        failures = [a for a in ctx.actions
                    if a["status"] == FAILED and a["step"] == "catalog_cleanup"]
        return _OUT_FAILED, [a["detail"][:300] for a in failures] or \
            ["Nettoyage du catalogue impossible (voir le journal)."]
    if status == "no_dataset":
        ctx.skip("catalog_cleanup", "no shared catalog dataset: nothing to clean")
    elif status == "unknown_table":
        ctx.skip("catalog_cleanup",
                 "table physique du catalogue illisible : supprime les lignes "
                 "capability_key=%s à la main si besoin" % key)
    return _OUT_DONE, []


def _run_removal_hub(env, state, ctx):
    info = _removal_info(state)
    key = info.get("capability_key")
    paths = (info.get("inventory") or {}).get("hub_paths") or []
    try:
        manual, status = removal.cleanup_hub(env.project, key, paths, ctx)
    except ValueError as exc:
        return _OUT_FAILED, [str(exc)]
    info.setdefault("manual", {})["hub_cleanup"] = [
        {"kind_fr": "Fichier du hub", "name": m["path"],
         "where_fr": "project library", "reason_fr": m.get("reason_fr", ""),
         "id": "", "note_fr": ""}
        for m in manual]
    info["capability_entry_status"] = status
    if status == "kept_disabled":
        ctx.skip("hub_cleanup",
                 "dernière capability du registre : l'entrée est conservée "
                 "DÉSACTIVÉE (un capabilities.json vide ferait retomber "
                 "l'orchestrateur sur ses valeurs embarquées)")
    if manual:
        return _OUT_WAITING, []
    return _OUT_DONE, []


def _check_removal_hub(env, state):
    info = _removal_info(state)
    paths = (info.get("inventory") or {}).get("hub_paths") or []
    leftovers = [p for p in paths if hub.path_exists(env.project, p) is True]
    if leftovers:
        return False, ["Toujours présent dans la project library : %s"
                       % ", ".join(leftovers)]
    return True, []


def _run_removal_final(env, state, ctx):
    info = _removal_info(state)
    problems = []
    for stage_key in removal.DELETE_STAGE_KEYS:
        items = _removal_items(state, stage_key)
        if not items:
            continue
        leftovers, check_problems = removal.verify_stage_absent(
            env.project, stage_key, items)
        problems.extend(check_problems)
        for item in leftovers:
            problems.append("%s %s existe toujours (étape %s) : supprime-le "
                            "puis relance cette vérification."
                            % (item["kind_fr"], item["name"], stage_key))
    key = info.get("capability_key")
    caps = hub.read_capabilities(env.project) or {}
    if key in caps and info.get("capability_entry_status") != "kept_disabled":
        problems.append("L'entrée %s existe encore dans capabilities.json." % key)
    if problems:
        return _OUT_FAILED, problems
    ctx.done("final_check", "tout est supprimé côté DSS (inventaire re-sondé)")
    ctx.done("final_check",
             "RAPPEL : re-sauvegarde l'orchestrateur dans DSS puis ouvre une "
             "NOUVELLE conversation (le registre des capabilities est chargé au "
             "démarrage du process, piège L168)")
    ctx.done("final_check",
             "l'historique de ce run de suppression reste consultable dans le "
             "store SQL de l'assistant")
    return _OUT_DONE, []


# ------------------------------------------------------------- stage registry

_RUNNERS = {
    "preflight": _run_preflight,
    "plan": _run_plan,
    "infra": _run_infra,
    "first_build": _run_first_build,
    "brain": _run_brain,
    "template": _run_template,
    "agent_code": _run_agent_code,
    "capability": _run_capability,
    "enable": _run_enable,
}

_CHECKERS = {
    "profile_review": _check_profile_review,
    "wizard": _check_wizard,
    "brain": _check_brain,
    "template": _check_template,
    "code_agent": _check_code_agent,
    "smoke": _check_smoke,
}

_INSTRUCTIONS = {
    "profile_review": _instr_profile_review,
    "wizard": _instr_wizard,
    "brain": _instr_tool_manual,
    "template": _instr_template,
    "code_agent": _instr_code_agent,
    "smoke": _instr_smoke,
}

# Advance-walk prechecks: POSITIVE-ONLY variants (a stage is auto-skipped only
# when its outcome is PROVEN, never when it merely could not be verified).
_PRECHECKS = {
    "first_build": _precheck_first_build,
    "wizard": _precheck_wizard,
    "template": _check_template,
    "code_agent": _check_code_agent,
}

_RUNNERS.update({
    "inventory": _run_removal_inventory,
    "disable": _run_removal_disable,
    "delete_tool": _make_removal_delete_runner("delete_tool"),
    "delete_agent": _make_removal_delete_runner("delete_agent"),
    "delete_model": _make_removal_delete_runner("delete_model"),
    "delete_scenario": _make_removal_delete_runner("delete_scenario"),
    "delete_recipes": _make_removal_delete_runner("delete_recipes"),
    "delete_datasets": _make_removal_delete_runner("delete_datasets"),
    "delete_zone": _make_removal_delete_runner("delete_zone"),
    "catalog_cleanup": _run_removal_catalog,
    "hub_cleanup": _run_removal_hub,
    "final_check": _run_removal_final,
})
_CHECKERS.update({
    "inventory": _check_removal_inventory,
    "delete_tool": _make_removal_absent_checker("delete_tool"),
    "delete_agent": _make_removal_absent_checker("delete_agent"),
    "delete_model": _make_removal_absent_checker("delete_model"),
    "delete_scenario": _make_removal_absent_checker("delete_scenario"),
    "delete_recipes": _make_removal_absent_checker("delete_recipes"),
    "delete_datasets": _make_removal_absent_checker("delete_datasets"),
    "delete_zone": _make_removal_absent_checker("delete_zone"),
    "hub_cleanup": _check_removal_hub,
})
_INSTRUCTIONS.update({
    "inventory": _instr_removal_inventory,
    "delete_tool": _make_instr_removal_manual("delete_tool"),
    "delete_agent": _make_instr_removal_manual("delete_agent"),
    "delete_model": _make_instr_removal_manual("delete_model"),
    "delete_scenario": _make_instr_removal_manual("delete_scenario"),
    "delete_recipes": _make_instr_removal_manual("delete_recipes"),
    "delete_datasets": _make_instr_removal_manual("delete_datasets"),
    "delete_zone": _make_instr_removal_manual("delete_zone"),
    "hub_cleanup": _make_instr_removal_manual("hub_cleanup"),
})


# ------------------------------------------------------------------ the machine

def new_state(spec):
    stages = {}
    for key in STAGE_ORDER:
        kind, title_fr, detail_fr = _STAGE_META[key]
        stages[key] = {
            "kind": kind,
            "title_fr": title_fr,
            "detail_fr": detail_fr,
            "status": PENDING,
            "journal": [],
            "problems": [],
            "instructions_fr": "",
        }
    stages[STAGE_ORDER[0]]["status"] = READY
    return {
        "version": STATE_VERSION,
        "spec": spec.to_dict(),
        "stage_order": list(STAGE_ORDER),
        "stages": stages,
        "captured": {"model_id": None, "tool_id": None,
                     "agent_id": None, "generated_path": None},
    }


def new_removal_state(capability_key, entry):
    stages = {}
    for key in REMOVAL_STAGE_ORDER:
        kind, title_fr, detail_fr = _REMOVAL_STAGE_META[key]
        stages[key] = {"kind": kind, "title_fr": title_fr, "detail_fr": detail_fr,
                       "status": PENDING, "journal": [], "problems": [],
                       "instructions_fr": ""}
    stages[REMOVAL_STAGE_ORDER[0]]["status"] = READY
    return {
        "version": STATE_VERSION,
        "removal": {"capability_key": capability_key, "entry": entry,
                    "inventory": None},
        "stage_order": list(REMOVAL_STAGE_ORDER),
        "stages": stages,
        "captured": {},
    }


def is_removal(run):
    """True for a REMOVAL run. The marker lives in the persisted state (the
    store only persists run_id/domain/status/current_stage/state_json)."""
    return bool((run.get("state") or {}).get("removal"))


def start_removal_run(project, capability_key, settings=None,
                      executor_factory=None, run_id=None, ctx=None):
    """Create a removal run and execute its inventory synchronously.
    Caller persists. Raises ValueError on an unknown capability."""
    settings = settings if settings is not None else hub.get_settings(project)
    caps = hub.read_capabilities(project) or {}
    entry = caps.get(capability_key)
    if not isinstance(entry, dict):
        raise ValueError("unknown capability: %s" % capability_key)
    env = _Env(project, settings, executor_factory)
    run = {
        "run_id": run_id or uuid.uuid4().hex,
        "domain": str(entry.get("domain") or capability_key),
        "status": RUN_ACTIVE,
        "current_stage": REMOVAL_STAGE_ORDER[0],
        "state": new_removal_state(capability_key, entry),
    }
    ctx = ctx or FactoryContext(project=project, dry_run=False,
                                abort_on_failure=False)
    return _execute_current(env, run, ctx)


def can_run(run):
    """True when the CURRENT stage is executable server-side (auto stage)."""
    key = run.get("current_stage")
    entry = (run.get("state") or {}).get("stages", {}).get(key) or {}
    return key in _RUNNERS and entry.get("status") in (READY, STAGE_FAILED)


def can_verify(run):
    """True when the CURRENT stage awaits a human confirmation + verification."""
    key = run.get("current_stage")
    entry = (run.get("state") or {}).get("stages", {}).get(key) or {}
    return key in _CHECKERS and entry.get("status") == WAITING


def _advance(env, run):
    """Move past the (done) current stage: auto-complete precheck-satisfied
    stages, then arm the next actionable one (ready / waiting_user)."""
    state = run["state"]
    order = state["stage_order"]
    index = order.index(run["current_stage"])
    for key in order[index + 1:]:
        entry = _stage(state, key)
        if key in _PRECHECK_STAGES and key in _PRECHECKS:
            try:
                ok, _problems = _PRECHECKS[key](env, state)
            except Exception:
                ok = False
            if ok:
                entry["status"] = DONE
                entry["journal"].append({"step": key, "status": "SKIPPED",
                                         "detail": "déjà satisfait : étape sautée"})
                continue
        run["current_stage"] = key
        if key in _RUNNERS:
            entry["status"] = READY
        else:
            entry["status"] = WAITING
            builder = _INSTRUCTIONS.get(key)
            if builder:
                entry["instructions_fr"] = builder(env, state)
        return run
    # Walked past the last stage: the run is complete.
    run["status"] = RUN_DONE
    return run


def _execute_current(env, run, ctx):
    state = run["state"]
    key = run["current_stage"]
    entry = _stage(state, key)
    entry["status"] = RUNNING
    entry["problems"] = []
    start = len(ctx.actions)
    try:
        outcome, problems = _RUNNERS[key](env, state, ctx)
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator, never lost
        outcome, problems = _OUT_FAILED, ["Erreur inattendue : %s" % exc]
    entry["journal"] = (entry["journal"] + _journal_slice(ctx, start))[-_JOURNAL_MAX:]
    entry["problems"] = list(problems)
    if outcome == _OUT_DONE:
        entry["status"] = DONE
        _advance(env, run)
    elif outcome == _OUT_WAITING:
        entry["status"] = WAITING
        builder = _INSTRUCTIONS.get(key)
        if builder:
            entry["instructions_fr"] = builder(env, state)
    else:
        entry["status"] = STAGE_FAILED
    return run


# ------------------------------------------------------------------ entry points

def start_run(project, spec, settings=None, executor_factory=None, run_id=None, ctx=None):
    """Create a run and execute its preflight synchronously. Caller persists."""
    settings = settings if settings is not None else hub.get_settings(project)
    env = _Env(project, settings, executor_factory)
    run = {
        "run_id": run_id or uuid.uuid4().hex,
        "domain": spec.domain,
        "status": RUN_ACTIVE,
        "current_stage": STAGE_ORDER[0],
        "state": new_state(spec),
    }
    ctx = ctx or FactoryContext(project=project, dry_run=False, abort_on_failure=False)
    return _execute_current(env, run, ctx)


def run_current_stage(project, run, settings=None, executor_factory=None, ctx=None):
    """Execute the current AUTO stage (the console runs this in a background job,
    sharing ``ctx`` so the journal streams live). Caller persists."""
    if run.get("status") != RUN_ACTIVE:
        raise ValueError("run is not active")
    if not can_run(run):
        raise ValueError("current stage is not runnable")
    settings = settings if settings is not None else hub.get_settings(project)
    env = _Env(project, settings, executor_factory)
    ctx = ctx or FactoryContext(project=project, dry_run=False, abort_on_failure=False)
    return _execute_current(env, run, ctx)


def verify_current_stage(project, run, settings=None, executor_factory=None):
    """Verify a WAITING stage against DSS ("C'est fait"). Advances only when the
    check passes; otherwise the stage keeps its problems. Caller persists."""
    if run.get("status") != RUN_ACTIVE:
        raise ValueError("run is not active")
    if not can_verify(run):
        raise ValueError("current stage is not verifiable")
    settings = settings if settings is not None else hub.get_settings(project)
    env = _Env(project, settings, executor_factory)
    state = run["state"]
    key = run["current_stage"]
    entry = _stage(state, key)
    try:
        ok, problems = _CHECKERS[key](env, state)
    except Exception as exc:  # noqa: BLE001 - surfaced, never lost
        ok, problems = False, ["Erreur inattendue pendant la vérification : %s" % exc]
    if ok:
        entry["problems"] = []
        entry["status"] = DONE
        _advance(env, run)
    else:
        entry["problems"] = list(problems)
        entry["status"] = WAITING
    return run


def abandon_run(run):
    """Mark the run abandoned. NOTHING is deleted in DSS (no deletion path)."""
    run["status"] = RUN_ABANDONED
    return run


def heal_interrupted(run):
    """Self-heal a run stuck in a state the machine can no longer act on:

    - a stage left RUNNING by a backend restart is demoted to a re-runnable
      state with an explicit note;
    - a stage persisted WAITING under an OLDER contract that is now auto-only
      (e.g. first_build was MANUAL before 2026-07-22) is realigned on the
      current stage meta and made runnable, otherwise the run would be stuck
      (neither runnable nor verifiable).

    Returns True when the run was changed (caller persists).
    """
    if run.get("status") != RUN_ACTIVE:
        return False
    key = run.get("current_stage")
    entry = (run.get("state") or {}).get("stages", {}).get(key)
    if not entry:
        return False
    if entry.get("status") == WAITING and key in _RUNNERS and key not in _CHECKERS:
        kind, title_fr, detail_fr = _ALL_STAGE_META[key]
        entry["kind"] = kind
        entry["title_fr"] = title_fr
        entry["detail_fr"] = detail_fr
        entry["instructions_fr"] = ""
        entry["status"] = READY
        entry["problems"] = []
        entry.setdefault("journal", []).append(
            {"step": key, "status": "SKIPPED",
             "detail": "étape migrée : elle s'exécute désormais automatiquement "
                       "(clique sur Lancer cette étape)"})
        return True
    if entry.get("status") != RUNNING:
        return False
    entry["status"] = STAGE_FAILED if key in _RUNNERS else WAITING
    entry.setdefault("problems", [])
    entry["problems"] = ["Étape interrompue (redémarrage du backend pendant l'exécution) : "
                         "relance-la."]
    return True
