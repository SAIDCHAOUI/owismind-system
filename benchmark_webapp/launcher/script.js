/* OWIsMind Benchmark - Launcher webapp (framework-free vanilla JS, no build).
 *
 * A REAL configuration FORM (never a raw JSON editor): edit agents, response modes, the
 * question filter, concurrency and the benchmark language, then save (POST api/config) and
 * launch the Run_Benchmark scenario (POST api/run + poll api/run/status). It also reviews and
 * promotes user-suggested questions. Talks to the Python backend via getWebAppBackendUrl.
 *
 * Bilingual: English is the default, French via the top-right toggle (persisted). Every visible
 * string goes through t(). Numbers are formatted client-side per the active locale. Orange
 * charter styling lives in style.css. MOCK mode (no getWebAppBackendUrl) serves sample data so
 * preview.html renders a full representative page offline. */

(function () {
  "use strict";

  /* ============================ i18n ============================ */

  var I18N = {
    en: {
      "brand.eyebrow": "OWIsMind Benchmark",
      "brand.h1": "Launcher",
      "brand.desc": "Configure the benchmark, launch a run, and promote the questions your users suggested. Results are read in the separate Results app.",
      "toggle.theme.aria": "Toggle light or dark theme",
      "toggle.theme.toLight": "Light",
      "toggle.theme.toDark": "Dark",
      "toggle.lang.aria": "Switch language",

      "cfg.eyebrow": "Setup",
      "cfg.title": "Configuration",
      "cfg.desc": "This is the live configuration. Saving only changes the agents, modes, question filter, concurrency and language. The preserved settings below are kept untouched.",

      "cfg.agents.label": "Agents under test",
      "cfg.agents.helper": "The agent id (like agent:038G7mlF) lives inside its own DSS project: do not prefix it. The project key tells the benchmark which project to call it in.",
      "cfg.agents.col.label": "Label",
      "cfg.agents.col.project": "Project key",
      "cfg.agents.col.agentid": "Agent id",
      "cfg.agents.modesShort": "Supports response modes (Smart / Pro / Claude)",
      "cfg.agents.add": "Add agent",
      "cfg.agents.remove": "Remove",
      "cfg.agents.removeAria": "Remove agent {name}",
      "cfg.agents.ph.label": "e.g. OWIsMind Orchestrator",
      "cfg.agents.ph.project": "e.g. OWISMIND_DEV",
      "cfg.agents.ph.agentid": "e.g. agent:038G7mlF",
      "cfg.agents.empty": "No agent yet. Add at least one to run the benchmark.",

      "cfg.modes.label": "Response modes",
      "cfg.modes.helper": "Only mode-aware agents are tested across the checked modes. Other agents get a single default call.",

      "cfg.questions.label": "Questions to test",
      "cfg.questions.helper": "Pick the categories to test. Empty selection = all {count} active questions.",
      "cfg.questions.nocats": "No category found in the golden set yet.",
      "cfg.questions.langfilter": "Language filter",
      "cfg.questions.lang.all": "All",
      "cfg.questions.lang.fr": "French",
      "cfg.questions.lang.en": "English",

      "cfg.concurrency.label": "Concurrency",
      "cfg.concurrency.helper": "How many questions run in parallel (1-8, kept low for instance safety). Values outside the range are clamped.",

      "cfg.benchlang.label": "Benchmark language",
      "cfg.benchlang.helper": "Language used for the run report and the agent prompts. To choose which golden questions are tested, use the Language filter above.",
      "cfg.benchlang.fr": "French (fr)",
      "cfg.benchlang.en": "English (en)",

      "cfg.preserved.label": "Preserved settings",
      "cfg.preserved.note": "These are not editable here and are kept untouched when you save.",
      "cfg.preserved.golden": "Golden dataset",
      "cfg.preserved.judge": "Judge model",
      "cfg.preserved.suggestions": "Suggestions source",
      "cfg.preserved.configured": "Configured",
      "cfg.preserved.notConfigured": "Not configured",
      "cfg.preserved.none": "(none)",

      "cfg.save": "Save configuration",
      "cfg.saving": "Saving...",
      "cfg.saved": "Configuration saved.",
      "cfg.invalidTitle": "The configuration could not be saved:",
      "cfg.saveError": "Could not save the configuration. Check your write access to the LAB project.",
      "cfg.loadError": "Could not load the configuration. Check your access to the LAB project.",
      "cfg.modesRequired": "Select at least one response mode, or turn off mode support on the mode-aware agents.",

      "launch.eyebrow": "Run",
      "launch.title": "Launch",
      "launch.desc": "Launch the Run_Benchmark scenario asynchronously. Only one run can be in progress at a time.",
      "launch.btn": "Launch the benchmark",
      "launch.caveat": "Launching may require scenario permissions. If it is unsupported, run the Run_Benchmark scenario from the DSS scenario UI.",
      "launch.runsLast": "Launching runs the last saved configuration. Save your edits first.",
      "launch.dirty": "Unsaved changes - save the configuration before launching.",
      "launch.lastRun": "Last run: {when}",
      "launch.confirm": "This will run {combos} agent/mode combination(s) across up to {questions} question(s). Launch now?",
      "launch.go": "Confirm launch",
      "launch.cancel": "Cancel",
      "launch.starting": "Starting the run...",
      "launch.running": "Running",
      "launch.finished": "Finished - open the Results app to read it.",
      "launch.already": "A run is already in progress.",
      "launch.unsupported": "Launch is not supported here. Run the Run_Benchmark scenario from the DSS scenario UI.",
      "launch.error": "Could not launch the run.",
      "launch.failed": "The run did not finish successfully. Check the DSS scenario log.",
      "launch.lostContact": "Lost contact with the run. Check the DSS scenario log.",

      "sug.eyebrow": "Golden set",
      "sug.title": "User suggestions",
      "sug.desc": "Questions your users suggested, pending review. Select the good ones and promote them into the golden set.",
      "sug.notConfigured": "Suggestion source not configured (add the benchmark.suggestions block to the project variable).",
      "sug.empty": "No pending suggestion right now.",
      "sug.col.question": "Question",
      "sug.col.expected": "Expected answer",
      "sug.col.anchor": "Anchor",
      "sug.col.review": "Review",
      "sug.col.source": "Source",
      "sug.col.category": "Category",
      "sug.col.date": "Date",
      "sug.answer.correct": "Correct",
      "sug.answer.incorrect": "Incorrect",
      "sug.answer.unverified": "Unverified",
      "sug.selectAll": "Select all suggestions",
      "sug.selectOne": "Select this suggestion",
      "sug.source.chat": "Conversation",
      "sug.source.manual": "Manual",
      "sug.promote": "Promote selection",
      "sug.promoting": "Promoting...",
      "sug.promoted": "{count} question(s) added to the golden set.",
      "sug.promotedNone": "No new question added (already in the golden set).",
      "sug.promoteError": "Could not promote the selection.",
      "sug.loadError": "Could not load the suggestions.",
      "sug.confirm": "Promote {count} suggestion(s) into the golden set? This change is permanent.",
      "sug.go": "Confirm promotion",
      "sug.cancel": "Cancel",

      "common.loading": "Loading...",
      "common.retry": "Retry",
      "common.dash": "-"
    },
    fr: {
      "brand.eyebrow": "OWIsMind Benchmark",
      "brand.h1": "Lanceur",
      "brand.desc": "Configurez le benchmark, lancez un run, et promouvez les questions suggerees par vos utilisateurs. Les resultats se lisent dans l'application Resultats separee.",
      "toggle.theme.aria": "Basculer le theme clair ou sombre",
      "toggle.theme.toLight": "Clair",
      "toggle.theme.toDark": "Sombre",
      "toggle.lang.aria": "Changer de langue",

      "cfg.eyebrow": "Reglage",
      "cfg.title": "Configuration",
      "cfg.desc": "Voici la configuration en vigueur. L'enregistrement ne modifie que les agents, les modes, le filtre de questions, la concurrence et la langue. Les reglages preserves ci-dessous restent intacts.",

      "cfg.agents.label": "Agents testes",
      "cfg.agents.helper": "L'identifiant d'agent (comme agent:038G7mlF) vit dans son propre projet DSS : ne le prefixez pas. La cle de projet indique au benchmark dans quel projet l'appeler.",
      "cfg.agents.col.label": "Libelle",
      "cfg.agents.col.project": "Cle de projet",
      "cfg.agents.col.agentid": "Identifiant d'agent",
      "cfg.agents.modesShort": "Gere les modes de reponse (Smart / Pro / Claude)",
      "cfg.agents.add": "Ajouter un agent",
      "cfg.agents.remove": "Retirer",
      "cfg.agents.removeAria": "Retirer l'agent {name}",
      "cfg.agents.ph.label": "ex. OWIsMind Orchestrator",
      "cfg.agents.ph.project": "ex. OWISMIND_DEV",
      "cfg.agents.ph.agentid": "ex. agent:038G7mlF",
      "cfg.agents.empty": "Aucun agent pour l'instant. Ajoutez-en au moins un pour lancer le benchmark.",

      "cfg.modes.label": "Modes de reponse",
      "cfg.modes.helper": "Seuls les agents qui gerent les modes sont testes sur les modes coches. Les autres recoivent un seul appel par defaut.",

      "cfg.questions.label": "Questions a tester",
      "cfg.questions.helper": "Choisissez les categories a tester. Selection vide = les {count} questions actives.",
      "cfg.questions.nocats": "Aucune categorie trouvee dans le golden set pour l'instant.",
      "cfg.questions.langfilter": "Filtre de langue",
      "cfg.questions.lang.all": "Toutes",
      "cfg.questions.lang.fr": "Francais",
      "cfg.questions.lang.en": "Anglais",

      "cfg.concurrency.label": "Concurrence",
      "cfg.concurrency.helper": "Combien de questions tournent en parallele (1-8, volontairement bas pour la securite de l'instance). Les valeurs hors plage sont ramenees dans les bornes.",

      "cfg.benchlang.label": "Langue du benchmark",
      "cfg.benchlang.helper": "Langue utilisee pour le rapport du run et les prompts des agents. Pour choisir quelles questions golden sont testees, utilisez le filtre de langue ci-dessus.",
      "cfg.benchlang.fr": "Francais (fr)",
      "cfg.benchlang.en": "Anglais (en)",

      "cfg.preserved.label": "Reglages preserves",
      "cfg.preserved.note": "Non modifiables ici, et gardes intacts lors de l'enregistrement.",
      "cfg.preserved.golden": "Dataset golden",
      "cfg.preserved.judge": "Modele juge",
      "cfg.preserved.suggestions": "Source des suggestions",
      "cfg.preserved.configured": "Configuree",
      "cfg.preserved.notConfigured": "Non configuree",
      "cfg.preserved.none": "(aucun)",

      "cfg.save": "Enregistrer la configuration",
      "cfg.saving": "Enregistrement...",
      "cfg.saved": "Configuration enregistree.",
      "cfg.invalidTitle": "La configuration n'a pas pu etre enregistree :",
      "cfg.saveError": "Impossible d'enregistrer la configuration. Verifiez votre acces en ecriture au projet LAB.",
      "cfg.loadError": "Impossible de charger la configuration. Verifiez votre acces au projet LAB.",
      "cfg.modesRequired": "Selectionnez au moins un mode de reponse, ou desactivez la gestion des modes sur les agents concernes.",

      "launch.eyebrow": "Run",
      "launch.title": "Lancer",
      "launch.desc": "Lance le scenario Run_Benchmark de maniere asynchrone. Un seul run peut etre en cours a la fois.",
      "launch.btn": "Lancer le benchmark",
      "launch.caveat": "Le lancement peut necessiter des permissions de scenario. Si ce n'est pas supporte, lancez le scenario Run_Benchmark depuis l'interface des scenarios DSS.",
      "launch.runsLast": "Le lancement utilise la derniere configuration enregistree. Enregistrez d'abord vos modifications.",
      "launch.dirty": "Modifications non enregistrees - enregistrez la configuration avant de lancer.",
      "launch.lastRun": "Dernier run : {when}",
      "launch.confirm": "Ceci lancera {combos} combinaison(s) agent/mode sur jusqu'a {questions} question(s). Lancer maintenant ?",
      "launch.go": "Confirmer le lancement",
      "launch.cancel": "Annuler",
      "launch.starting": "Demarrage du run...",
      "launch.running": "En cours",
      "launch.finished": "Termine - ouvrez l'application Resultats pour le lire.",
      "launch.already": "Un run est deja en cours.",
      "launch.unsupported": "Le lancement n'est pas supporte ici. Lancez le scenario Run_Benchmark depuis l'interface des scenarios DSS.",
      "launch.error": "Impossible de lancer le run.",
      "launch.failed": "Le run ne s'est pas termine correctement. Consultez le journal du scenario DSS.",
      "launch.lostContact": "Contact perdu avec le run. Consultez le journal du scenario DSS.",

      "sug.eyebrow": "Golden set",
      "sug.title": "Suggestions des utilisateurs",
      "sug.desc": "Questions suggerees par vos utilisateurs, en attente de revue. Selectionnez les bonnes et promouvez-les dans le golden set.",
      "sug.notConfigured": "Source des suggestions non configuree (ajoutez le bloc benchmark.suggestions a la variable de projet).",
      "sug.empty": "Aucune suggestion en attente pour l'instant.",
      "sug.col.question": "Question",
      "sug.col.expected": "Reponse attendue",
      "sug.col.anchor": "Ancre",
      "sug.col.review": "Revue",
      "sug.col.source": "Source",
      "sug.col.category": "Categorie",
      "sug.col.date": "Date",
      "sug.answer.correct": "Correct",
      "sug.answer.incorrect": "Incorrect",
      "sug.answer.unverified": "Non verifie",
      "sug.selectAll": "Tout selectionner",
      "sug.selectOne": "Selectionner cette suggestion",
      "sug.source.chat": "Conversation",
      "sug.source.manual": "Manuelle",
      "sug.promote": "Promouvoir la selection",
      "sug.promoting": "Promotion...",
      "sug.promoted": "{count} question(s) ajoutee(s) au golden set.",
      "sug.promotedNone": "Aucune nouvelle question ajoutee (deja dans le golden set).",
      "sug.promoteError": "Impossible de promouvoir la selection.",
      "sug.loadError": "Impossible de charger les suggestions.",
      "sug.confirm": "Promouvoir {count} suggestion(s) dans le golden set ? Ce changement est definitif.",
      "sug.go": "Confirmer la promotion",
      "sug.cancel": "Annuler",

      "common.loading": "Chargement...",
      "common.retry": "Reessayer",
      "common.dash": "-"
    }
  };

  function t(key, vars) {
    var table = I18N[ui.lang] || I18N.en;
    var s = table[key];
    if (s == null) {
      s = (I18N.en[key] != null) ? I18N.en[key] : key;
    }
    if (vars) {
      Object.keys(vars).forEach(function (k) {
        s = s.split("{" + k + "}").join(String(vars[k]));
      });
    }
    return s;
  }

  function locale() {
    return ui.lang === "fr" ? "fr-FR" : "en-US";
  }

  function fmtNum(n) {
    var v = Number(n);
    if (!isFinite(v)) {
      return t("common.dash");
    }
    try {
      return v.toLocaleString(locale());
    } catch (e) {
      return String(v);
    }
  }

  /* ============================ utils ============================ */

  function esc(value) {
    var s = (value == null) ? "" : String(value);
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function truncate(value, max) {
    var s = (value == null) ? "" : String(value);
    if (s.length <= max) {
      return s;
    }
    return s.slice(0, max).replace(/\s+\S*$/, "") + "...";
  }

  function clampInt(value, lo, hi, fallback) {
    var n = parseInt(value, 10);
    if (isNaN(n)) {
      return fallback;
    }
    return Math.max(lo, Math.min(hi, n));
  }

  function slugify(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
  }

  /* ============================ state ============================ */

  var ui = {
    lang: "en",
    theme: "light"
  };

  var state = {
    loaded: false,
    // True when GET api/config failed and we have nothing to show yet (the config form
    // renders a retry note instead of an endless "Loading..." line).
    loadError: false,
    // True when the on-screen config diverges from the last saved config. Launch runs the
    // SAVED config, so while dirty the launch button is disabled with an explicit hint.
    dirty: false,
    form: {
      agents: [],
      modes: [],
      language: "fr",
      concurrency: 3,
      filterCategories: [],
      // The categories the server last returned in question_filter: preserved across saves
      // even when a configured category has no checkbox (drift vs the dataset categories).
      filterCategoriesLoaded: [],
      filterLanguage: "all",
      // Opaque server-configured question id filter: never edited in the UI, but
      // preserved verbatim across saves so saving does not wipe it.
      filterQuestionIds: []
    },
    meta: {
      categories: [],
      questionCount: 0,
      modeOptions: ["Smart", "Pro", "Claude"],
      goldenDataset: "",
      judgeLlmId: "",
      suggestions: {},
      // Most recent runs (run_id, run_timestamp) from GET api/config: used to surface the
      // "Last run" line in the Launch section (no Results URL in the contract).
      runs: []
    },
    suggestions: {
      loaded: false,
      loadError: false,
      configured: false,
      list: [],
      // Reviewer selection kept in state (map of suggestion_id -> true) so a full
      // re-render (theme/language toggle, save, add/remove agent) preserves it.
      selected: {},
      // Inline (no-modal) promotion confirm: a permanent write to the golden set.
      confirm: false,
      confirmCount: 0
    },
    msg: {
      save: null,
      promote: null
    },
    run: {
      stateName: "idle",
      key: null,
      // Inline (no-modal) launch confirm: a benchmark run is costly and instance-loading.
      confirm: false
    }
  };

  var pollTimer = null;
  // Consecutive failed status polls. After a few in a row we stop polling and surface a
  // "lost contact" message instead of leaving the UI stuck on "Running" forever.
  var pollErrors = 0;
  // Last run state the targeted updater wrote, so polling does not re-announce an
  // unchanged "Running" line to assistive tech every few seconds (aria-live).
  var lastRunRendered = null;

  /* ============================ API ============================ */

  function hasBackend() {
    return typeof getWebAppBackendUrl === "function";
  }

  // Returns a Promise of { status: <httpCode>, data: <parsedJson> }.
  function callApi(method, path, body) {
    if (!hasBackend()) {
      return mockApi(method, path, body);
    }
    var opts = { method: method, headers: { "Content-Type": "application/json" } };
    if (body !== undefined) {
      opts.body = JSON.stringify(body);
    }
    return fetch(getWebAppBackendUrl("api/" + path), opts).then(function (res) {
      return res.json().then(
        function (data) { return { status: res.status, data: data }; },
        function () { return { status: res.status, data: {} }; }
      );
    });
  }

  /* ============================ MOCK (offline preview) ============================ */

  var MOCK = {
    config: {
      agents: [
        {
          agent_key: "orchestrator",
          agent_label: "OWIsMind Orchestrator",
          project_key: "OWISMIND_DEV",
          agent_id: "agent:038G7mlF",
          modes: true
        }
      ],
      modes: ["Smart", "Claude"],
      language: "fr",
      concurrency: 3,
      golden_dataset: "golden_questions_v1_prepared",
      question_filter: { categories: ["revenue"], question_ids: [], languages: [] },
      judge_llm_id: "anthropic:claude-sonnet-4-6",
      suggestions: {
        connection: "SQL_owi",
        table: "OWISMIND_DEV_owismind_webapp_golden_suggestions_v1",
        promoted_dataset: "benchmark_suggestions_promoted"
      }
    },
    categories: ["revenue", "tickets"],
    question_count: 42,
    mode_options: ["Smart", "Pro", "Claude"],
    runs: [{ run_id: "run_20260625_2241", run_timestamp: "2026-06-25 22:41:03" }],
    suggestions: [
      {
        suggestion_id: "sug_a1b2c3",
        user_id: "marie.dupont",
        source: "chat",
        question: "Quel est le revenu reel du compte Maroc Telecom sur l'annee en cours ?",
        reference_answer: "Le revenu reel (ACTUALS) du compte Maroc Telecom sur l'annee en cours est de 4 218 540 euros, toutes periodes confondues.",
        answer_is_correct: true,
        missing_explanation: "",
        expected_value: "4218540",
        expected_value_type: "currency",
        category: "revenue",
        language: "fr",
        created_at: "2026-06-24 14:09:22"
      },
      {
        suggestion_id: "sug_d4e5f6",
        user_id: "john.smith",
        source: "manual",
        question: "How many distinct open trouble tickets does Algerie Telecom currently have?",
        reference_answer: "Algerie Telecom currently has 37 distinct open trouble tickets (counted on the latest snapshot per ticket id).",
        answer_is_correct: true,
        missing_explanation: "",
        expected_value: "37",
        expected_value_type: "numeric",
        category: "tickets",
        language: "en",
        created_at: "2026-06-24 11:51:40"
      },
      {
        suggestion_id: "sug_g7h8i9",
        user_id: "sara.benali",
        source: "chat",
        question: "Quel est le budget 2026 du produit Roaming Hub pour le client Airbus ?",
        reference_answer: "Le budget 2026 du produit Roaming Hub pour Airbus est de 1 050 000 euros (scenario BUDGET, periode 2026).",
        answer_is_correct: null,
        missing_explanation: "L'agent a confondu Roaming Hub avec Roaming Sponsor.",
        expected_value: "1050000",
        expected_value_type: "currency",
        category: "revenue",
        language: "fr",
        created_at: "2026-06-23 17:30:05"
      }
    ]
  };

  // A mutable mock run that finishes after ~2 status polls.
  var mockRun = { remaining: 0 };
  // Mock promotion log (so promoted suggestions drop out of the pending list).
  var mockPromoted = {};

  function mockApi(method, path, body) {
    var status = 200;
    var data = {};

    if (method === "GET" && path === "config") {
      data = {
        status: "ok",
        config: deepCopy(MOCK.config),
        categories: MOCK.categories.slice(),
        question_count: MOCK.question_count,
        mode_options: MOCK.mode_options.slice(),
        runs: MOCK.runs.slice()
      };
    } else if (method === "POST" && path === "config") {
      // Echo back a resolved-looking config (mirrors the server preserving the rest).
      var merged = deepCopy(MOCK.config);
      if (body) {
        if (body.agents) { merged.agents = body.agents; }
        if (body.modes) { merged.modes = body.modes; }
        if (body.language) { merged.language = body.language; }
        if (body.concurrency) { merged.concurrency = body.concurrency; }
        if (body.question_filter) { merged.question_filter = body.question_filter; }
      }
      if (!merged.agents || !merged.agents.length) {
        data = {
          status: "error",
          error: "invalid_config",
          messages: ["no valid agent: 'agents' must list at least one {agent_key, project_key, agent_id}"]
        };
        status = 400;
      } else {
        MOCK.config = merged;
        data = { status: "ok", config: deepCopy(merged) };
      }
    } else if (method === "POST" && path === "run") {
      mockRun.remaining = 2;
      data = { status: "ok", launched: true };
    } else if (method === "GET" && path === "run/status") {
      var running = mockRun.remaining > 0;
      if (running) {
        mockRun.remaining -= 1;
      }
      data = { status: "ok", running: running, last: running ? null : "SUCCESS" };
    } else if (method === "GET" && path === "suggestions") {
      var pending = MOCK.suggestions.filter(function (s) {
        return !mockPromoted[s.suggestion_id];
      });
      data = { status: "ok", configured: true, suggestions: pending };
    } else if (method === "POST" && path === "suggestions/promote") {
      var ids = (body && body.suggestion_ids) || [];
      var promoted = 0;
      ids.forEach(function (id) {
        if (!mockPromoted[id]) {
          mockPromoted[id] = true;
          promoted += 1;
        }
      });
      data = { status: "ok", promoted: promoted, recorded: ids.length };
    } else {
      status = 404;
      data = { status: "error", error: "not_found" };
    }

    return new Promise(function (resolve) {
      setTimeout(function () { resolve({ status: status, data: data }); }, 120);
    });
  }

  function deepCopy(obj) {
    return JSON.parse(JSON.stringify(obj));
  }

  /* ============================ theme + language ============================ */

  function loadPrefs() {
    try {
      var th = localStorage.getItem("bench-theme");
      if (th === "light" || th === "dark") {
        ui.theme = th;
      }
    } catch (e) { /* storage unavailable */ }
    try {
      var lg = localStorage.getItem("bench-lang");
      if (lg === "en" || lg === "fr") {
        ui.lang = lg;
      }
    } catch (e2) { /* storage unavailable */ }
  }

  function applyTheme() {
    document.documentElement.setAttribute("data-theme", ui.theme);
  }

  // Keep the document language in sync so assistive tech pronounces the UI correctly.
  function applyLang() {
    document.documentElement.setAttribute("lang", ui.lang);
  }

  function toggleTheme() {
    ui.theme = (ui.theme === "light") ? "dark" : "light";
    applyTheme();
    try { localStorage.setItem("bench-theme", ui.theme); } catch (e) { /* ignore */ }
    render();
  }

  function toggleLang() {
    syncFormFromDom();
    ui.lang = (ui.lang === "en") ? "fr" : "en";
    applyLang();
    try { localStorage.setItem("bench-lang", ui.lang); } catch (e) { /* ignore */ }
    render();
  }

  /* ============================ DOM -> state sync ============================ */

  // Read the current form inputs back into state so a re-render never loses typed values.
  function syncFormFromDom() {
    var root = byId("bench-app");
    if (!root || !state.loaded) {
      return;
    }
    var rows = root.querySelectorAll("[data-agent-row]");
    if (rows.length) {
      var agents = [];
      rows.forEach(function (r) {
        agents.push({
          agent_key: r.getAttribute("data-agent-key") || "",
          agent_label: fieldVal(r, "agent_label"),
          project_key: fieldVal(r, "project_key"),
          agent_id: fieldVal(r, "agent_id"),
          modes: !!(r.querySelector('[data-af="modes"]') || {}).checked
        });
      });
      state.form.agents = agents;
    }

    var modeBoxes = root.querySelectorAll("[data-mode-cb]");
    if (modeBoxes.length) {
      state.form.modes = toArray(modeBoxes)
        .filter(function (c) { return c.checked; })
        .map(function (c) { return c.value; });
    }

    var catBoxes = root.querySelectorAll("[data-cat-cb]");
    if (catBoxes.length) {
      state.form.filterCategories = toArray(catBoxes)
        .filter(function (c) { return c.checked; })
        .map(function (c) { return c.value; });
    }

    var fl = root.querySelector('[data-field="filter_language"]');
    if (fl) { state.form.filterLanguage = fl.value; }

    var cc = root.querySelector('[data-field="concurrency"]');
    if (cc) { state.form.concurrency = clampInt(cc.value, 1, 8, state.form.concurrency); }

    var lg = root.querySelector('[data-field="language"]');
    if (lg) { state.form.language = lg.value; }

    // Capture the reviewer's suggestion selection (the whole pending list is always
    // rendered, so the checked boxes are the complete, authoritative selection).
    var sugBoxes = root.querySelectorAll("[data-sug-cb]");
    if (sugBoxes.length) {
      var sel = {};
      toArray(sugBoxes).forEach(function (c) {
        if (c.checked) { sel[c.value] = true; }
      });
      state.suggestions.selected = sel;
    }
  }

  function fieldVal(rowEl, name) {
    var el = rowEl.querySelector('[data-af="' + name + '"]');
    return el ? el.value : "";
  }

  function toArray(nodeList) {
    return Array.prototype.slice.call(nodeList);
  }

  /* ============================ render ============================ */

  function render() {
    syncFormFromDom();
    var root = byId("bench-app");
    if (!root) {
      return;
    }
    root.innerHTML =
      topbarHtml() +
      configHtml() +
      launchHtml() +
      suggestionsHtml();
    // A full render writes the run line inline (via runMsgHtml), so the targeted
    // updater is now in sync with the current state.
    lastRunRendered = state.run.stateName;
    // The "select all" indeterminate state cannot be expressed as an HTML attribute,
    // so reflect a partial selection right after the table is (re)built.
    syncSelectAllState();
  }

  function topbarHtml() {
    var themeLabel = (ui.theme === "light")
      ? t("toggle.theme.toDark")
      : t("toggle.theme.toLight");
    var langLabel = (ui.lang === "en") ? "FR" : "EN";
    return '' +
      '<header class="topbar">' +
        '<div class="brand">' +
          '<span class="eyebrow">' + esc(t("brand.eyebrow")) + '</span>' +
          '<h1 class="h1">' + esc(t("brand.h1")) + '</h1>' +
          '<span class="title-bar"></span>' +
          '<p class="brand-desc">' + esc(t("brand.desc")) + '</p>' +
        '</div>' +
        '<div class="toggles">' +
          '<button type="button" class="toggle" id="langToggle" ' +
            'aria-label="' + esc(t("toggle.lang.aria")) + '">' + esc(langLabel) + '</button>' +
          '<button type="button" class="toggle" id="themeToggle" ' +
            'aria-label="' + esc(t("toggle.theme.aria")) + '">' + esc(themeLabel) + '</button>' +
        '</div>' +
      '</header>';
  }

  /* --- configuration form --- */

  function configHtml() {
    // A failed load with nothing to show yet: an explicit error + retry, never an
    // endless "Loading...". A transient refresh error after a good load keeps the form.
    if (state.loadError && !state.loaded) {
      return '' +
        '<section class="card">' +
          '<div class="note note-error" role="alert">' + esc(t("cfg.loadError")) + '</div>' +
          '<div class="actions-row">' +
            '<button type="button" class="btn" data-action="retry-load">' +
              esc(t("common.retry")) + '</button>' +
          '</div>' +
        '</section>';
    }
    if (!state.loaded) {
      return '<section class="card"><p class="loading">' + esc(t("common.loading")) + '</p></section>';
    }
    return '' +
      '<section class="card">' +
        '<span class="sec-eyebrow">' + esc(t("cfg.eyebrow")) + '</span>' +
        '<h2 class="sec-title">' + esc(t("cfg.title")) + '</h2>' +
        '<span class="sec-bar"></span>' +
        '<p class="sec-desc">' + esc(t("cfg.desc")) + '</p>' +
        agentsField() +
        modesField() +
        questionsField() +
        concurrencyField() +
        benchLangField() +
        preservedField() +
        saveBlock() +
      '</section>';
  }

  function agentsField() {
    var rows;
    if (!state.form.agents.length) {
      rows = '<p class="field-help">' + esc(t("cfg.agents.empty")) + '</p>';
    } else {
      rows = state.form.agents.map(agentRowHtml).join("");
    }
    return '' +
      '<div class="field">' +
        '<span class="field-label">' + esc(t("cfg.agents.label")) + '</span>' +
        '<p class="field-help">' + esc(t("cfg.agents.helper")) + '</p>' +
        rows +
        '<div class="actions-row">' +
          '<button type="button" class="btn btn-sm" data-action="add-agent">' +
            esc(t("cfg.agents.add")) + '</button>' +
        '</div>' +
      '</div>';
  }

  function agentRowHtml(a, idx) {
    var nameForAria = (a.agent_label && a.agent_label.trim())
      || a.agent_key || String(idx + 1);
    return '' +
      '<div class="agent-row" data-agent-row data-agent-key="' + esc(a.agent_key) + '">' +
        '<div class="af">' +
          '<label class="af-lab" for="ag-label-' + idx + '">' + esc(t("cfg.agents.col.label")) + '</label>' +
          '<input class="inp" id="ag-label-' + idx + '" type="text" data-af="agent_label" ' +
            'value="' + esc(a.agent_label) + '" placeholder="' + esc(t("cfg.agents.ph.label")) + '">' +
        '</div>' +
        '<div class="af">' +
          '<label class="af-lab" for="ag-proj-' + idx + '">' + esc(t("cfg.agents.col.project")) + '</label>' +
          '<input class="inp mono" id="ag-proj-' + idx + '" type="text" data-af="project_key" ' +
            'value="' + esc(a.project_key) + '" placeholder="' + esc(t("cfg.agents.ph.project")) + '">' +
        '</div>' +
        '<div class="af">' +
          '<label class="af-lab" for="ag-id-' + idx + '">' + esc(t("cfg.agents.col.agentid")) + '</label>' +
          '<input class="inp mono" id="ag-id-' + idx + '" type="text" data-af="agent_id" ' +
            'value="' + esc(a.agent_id) + '" placeholder="' + esc(t("cfg.agents.ph.agentid")) + '">' +
        '</div>' +
        '<div class="af af-actions">' +
          '<button type="button" class="btn btn-sm btn-danger" data-action="remove-agent" ' +
            'data-idx="' + idx + '" ' +
            'aria-label="' + esc(t("cfg.agents.removeAria", { name: nameForAria })) + '">' +
            esc(t("cfg.agents.remove")) + '</button>' +
        '</div>' +
        '<div class="af af-modes">' +
          '<label class="cb"><input type="checkbox" data-af="modes"' +
            (a.modes ? " checked" : "") + '>' +
            '<span class="cb-text">' + esc(t("cfg.agents.modesShort")) + '</span></label>' +
        '</div>' +
      '</div>';
  }

  function modesField() {
    var boxes = state.meta.modeOptions.map(function (m) {
      var on = state.form.modes.indexOf(m) !== -1;
      return '<label class="cb"><input type="checkbox" data-mode-cb value="' + esc(m) + '"' +
        (on ? " checked" : "") + '><span class="cb-text">' + esc(m) + '</span></label>';
    }).join("");
    return '' +
      '<div class="field">' +
        '<span class="field-label">' + esc(t("cfg.modes.label")) + '</span>' +
        '<p class="field-help">' + esc(t("cfg.modes.helper")) + '</p>' +
        '<div class="check-grid">' + boxes + '</div>' +
      '</div>';
  }

  function questionsField() {
    var cats;
    if (!state.meta.categories.length) {
      cats = '<p class="field-help">' + esc(t("cfg.questions.nocats")) + '</p>';
    } else {
      cats = '<div class="check-grid">' + state.meta.categories.map(function (c) {
        var on = state.form.filterCategories.indexOf(c) !== -1;
        return '<label class="cb"><input type="checkbox" data-cat-cb value="' + esc(c) + '"' +
          (on ? " checked" : "") + '><span class="cb-text">' + esc(c) + '</span></label>';
      }).join("") + '</div>';
    }
    var langSel = '' +
      '<div class="af" style="max-width:240px;margin-top:' + 'var(--s-4)' + '">' +
        '<label class="af-lab" for="filter-lang">' + esc(t("cfg.questions.langfilter")) + '</label>' +
        '<select class="sel" id="filter-lang" data-field="filter_language">' +
          langOpt("all", t("cfg.questions.lang.all")) +
          langOpt("fr", t("cfg.questions.lang.fr")) +
          langOpt("en", t("cfg.questions.lang.en")) +
        '</select>' +
      '</div>';
    var help = t("cfg.questions.helper", { count: fmtNum(state.meta.questionCount) });
    return '' +
      '<div class="field">' +
        '<span class="field-label">' + esc(t("cfg.questions.label")) + '</span>' +
        '<p class="field-help">' + escWithCount(help) + '</p>' +
        cats +
        langSel +
      '</div>';
  }

  // The helper has a {count} number we want to render in the mono accent style; everything
  // else is escaped. The count value came from fmtNum (digits + locale separators only).
  function escWithCount(text) {
    var parts = String(text).split(fmtNum(state.meta.questionCount));
    if (parts.length === 2) {
      return esc(parts[0]) + '<span class="count">' + esc(fmtNum(state.meta.questionCount)) +
        '</span>' + esc(parts[1]);
    }
    return esc(text);
  }

  function langOpt(value, label) {
    var sel = (state.form.filterLanguage === value) ? " selected" : "";
    return '<option value="' + esc(value) + '"' + sel + '>' + esc(label) + '</option>';
  }

  function concurrencyField() {
    return '' +
      '<div class="field">' +
        '<span class="field-label">' + esc(t("cfg.concurrency.label")) + '</span>' +
        '<p class="field-help">' + esc(t("cfg.concurrency.helper")) + '</p>' +
        '<input class="inp inp-num mono" type="number" min="1" max="8" step="1" ' +
          'data-field="concurrency" value="' + esc(state.form.concurrency) + '" ' +
          'aria-label="' + esc(t("cfg.concurrency.label")) + '">' +
      '</div>';
  }

  function benchLangField() {
    return '' +
      '<div class="field">' +
        '<span class="field-label">' + esc(t("cfg.benchlang.label")) + '</span>' +
        '<p class="field-help">' + esc(t("cfg.benchlang.helper")) + '</p>' +
        '<div class="af" style="max-width:240px">' +
          '<select class="sel" data-field="language" aria-label="' +
            esc(t("cfg.benchlang.label")) + '">' +
            benchLangOpt("fr", t("cfg.benchlang.fr")) +
            benchLangOpt("en", t("cfg.benchlang.en")) +
          '</select>' +
        '</div>' +
      '</div>';
  }

  function benchLangOpt(value, label) {
    var sel = (state.form.language === value) ? " selected" : "";
    return '<option value="' + esc(value) + '"' + sel + '>' + esc(label) + '</option>';
  }

  function preservedField() {
    var sug = state.meta.suggestions || {};
    var configured = !!sug.table;
    var sugTag = configured
      ? '<span class="tag-on">' + esc(t("cfg.preserved.configured")) + '</span>'
      : '<span class="tag-off">' + esc(t("cfg.preserved.notConfigured")) + '</span>';
    var none = t("cfg.preserved.none");
    return '' +
      '<div class="field">' +
        '<span class="field-label">' + esc(t("cfg.preserved.label")) + '</span>' +
        '<div class="preserved">' +
          '<p class="preserved-note">' + esc(t("cfg.preserved.note")) + '</p>' +
          '<dl class="kv">' +
            '<dt>' + esc(t("cfg.preserved.golden")) + '</dt>' +
            '<dd>' + esc(state.meta.goldenDataset || none) + '</dd>' +
            '<dt>' + esc(t("cfg.preserved.judge")) + '</dt>' +
            '<dd>' + esc(state.meta.judgeLlmId || none) + '</dd>' +
            '<dt>' + esc(t("cfg.preserved.suggestions")) + '</dt>' +
            '<dd>' + sugTag + '</dd>' +
          '</dl>' +
        '</div>' +
      '</div>';
  }

  function saveBlock() {
    var msg = state.msg.save;
    var note = "";
    if (msg) {
      if (msg.kind === "ok") {
        note = '<div class="note note-ok" role="status">' + esc(msg.text) + '</div>';
      } else if (msg.kind === "invalid") {
        note = '<div class="note note-error" role="alert"><strong>' +
          esc(t("cfg.invalidTitle")) + '</strong><ul>' +
          (msg.messages || []).map(function (m) {
            return '<li>' + esc(m) + '</li>';
          }).join("") + '</ul></div>';
      } else {
        note = '<div class="note note-error" role="alert">' + esc(msg.text) + '</div>';
      }
    }
    return '' +
      '<div class="actions-row">' +
        '<button type="button" class="btn btn-primary" data-action="save-config" id="saveBtn">' +
          esc(t("cfg.save")) + '</button>' +
      '</div>' +
      note;
  }

  /* --- launch --- */

  // Launch is disabled while a run is starting/in progress, and while the form is dirty
  // (a save must land first, since launching uses the last SAVED config, not the screen).
  function launchDisabled() {
    var s = state.run.stateName;
    return state.dirty || s === "starting" || s === "running";
  }

  // Approximate scope of the next run, from the last saved form: agent x mode combinations
  // and the active question count (an upper bound, before the category/language filter).
  function launchScope() {
    var agents = state.form.agents.filter(function (a) {
      return (a.agent_id && a.agent_id.trim()) ||
        (a.agent_key && a.agent_key.trim()) ||
        (a.agent_label && a.agent_label.trim());
    });
    var modeCount = state.form.modes.length;
    var combos = 0;
    agents.forEach(function (a) {
      combos += a.modes ? Math.max(1, modeCount) : 1;
    });
    if (combos === 0) { combos = agents.length; }
    return { combos: combos, questions: state.meta.questionCount };
  }

  function launchHtml() {
    var primary;
    if (state.run.confirm) {
      // Inline (no-modal) confirm: a benchmark run is costly and loads the instance.
      var sc = launchScope();
      primary = '' +
        '<div class="confirm-row" role="group">' +
          '<p class="confirm-msg">' +
            esc(t("launch.confirm", {
              combos: fmtNum(sc.combos),
              questions: fmtNum(sc.questions)
            })) + '</p>' +
          '<div class="actions-row">' +
            '<button type="button" class="btn btn-primary" data-action="launch-go">' +
              esc(t("launch.go")) + '</button>' +
            '<button type="button" class="btn" data-action="launch-cancel">' +
              esc(t("launch.cancel")) + '</button>' +
          '</div>' +
        '</div>';
    } else {
      primary = '' +
        '<div class="actions-row">' +
          '<button type="button" class="btn btn-primary" data-action="launch" id="launchBtn"' +
            (launchDisabled() ? " disabled" : "") + '>' +
            esc(t("launch.btn")) + '</button>' +
        '</div>';
    }
    var dirtyHint = '<p class="launch-hint" id="benchDirtyHint" role="status"' +
      (state.dirty ? "" : " hidden") + '>' + esc(t("launch.dirty")) + '</p>';
    var lastRun = "";
    var runs = state.meta.runs || [];
    if (runs.length && runs[0] && runs[0].run_timestamp) {
      lastRun = '<p class="last-run">' +
        esc(t("launch.lastRun", { when: runs[0].run_timestamp })) + '</p>';
    }
    return '' +
      '<section class="card">' +
        '<span class="sec-eyebrow">' + esc(t("launch.eyebrow")) + '</span>' +
        '<h2 class="sec-title">' + esc(t("launch.title")) + '</h2>' +
        '<span class="sec-bar"></span>' +
        '<p class="sec-desc">' + esc(t("launch.desc")) + '</p>' +
        primary +
        dirtyHint +
        '<p class="run-msg ' + runMsgClass() + '" id="benchRunMsg" aria-live="polite">' +
          runMsgHtml() + '</p>' +
        lastRun +
        '<p class="caveat">' + esc(t("launch.runsLast")) + '</p>' +
        '<p class="caveat">' + esc(t("launch.caveat")) + '</p>' +
      '</section>';
  }

  // Targeted refresh of just the launch button + dirty hint (no full re-render, so typing
  // in the config form keeps focus while the launch availability updates live).
  function refreshLaunchAvail() {
    var btn = byId("launchBtn");
    if (btn) { btn.disabled = launchDisabled(); }
    var hint = byId("benchDirtyHint");
    if (hint) { hint.hidden = !state.dirty; }
  }

  function runMsgClass() {
    var s = state.run.stateName;
    if (s === "running" || s === "starting") { return "is-running"; }
    if (s === "done") { return "is-done"; }
    if (s === "error") { return "is-error"; }
    return "";
  }

  function runMsgHtml() {
    var s = state.run.stateName;
    if (s === "starting") {
      return esc(t("launch.starting"));
    }
    if (s === "running") {
      return esc(t("launch.running")) +
        '<span class="dots"><span>.</span><span>.</span><span>.</span></span>';
    }
    if (s === "done") {
      return esc(t("launch.finished"));
    }
    if (s === "error") {
      return esc(state.run.key ? t(state.run.key) : t("launch.error"));
    }
    return "";
  }

  // Targeted update of just the run line (used during polling, to keep form focus).
  // Skips the rewrite when the run state is unchanged, so an aria-live region is not
  // re-announced on every poll (the "Running" dots keep animating via CSS regardless).
  function updateRunMsg() {
    var el = byId("benchRunMsg");
    if (!el) {
      lastRunRendered = null;
      return;
    }
    if (state.run.stateName === lastRunRendered) {
      return;
    }
    lastRunRendered = state.run.stateName;
    el.className = "run-msg " + runMsgClass();
    el.innerHTML = runMsgHtml();
  }

  /* --- suggestions --- */

  function suggestionsHtml() {
    var inner;
    if (state.suggestions.loadError) {
      inner = '' +
        '<div class="note note-error" role="alert">' + esc(t("sug.loadError")) + '</div>' +
        '<div class="actions-row">' +
          '<button type="button" class="btn" data-action="retry-suggestions">' +
            esc(t("common.retry")) + '</button>' +
        '</div>';
    } else if (!state.suggestions.loaded) {
      inner = '<p class="loading">' + esc(t("common.loading")) + '</p>';
    } else if (!state.suggestions.configured) {
      inner = '<div class="note note-info" role="status">' +
        esc(t("sug.notConfigured")) + '</div>';
    } else if (!state.suggestions.list.length) {
      inner = '<div class="note note-info" role="status">' + esc(t("sug.empty")) + '</div>';
    } else {
      inner = suggestionsTableHtml();
    }
    var note = "";
    if (state.msg.promote) {
      var m = state.msg.promote;
      var cls = (m.kind === "ok") ? "note-ok" : "note-error";
      // Success is announced politely (status); a failure is announced assertively (alert).
      var role = (m.kind === "ok") ? "status" : "alert";
      note = '<div class="note ' + cls + '" role="' + role + '">' + esc(m.text) + '</div>';
    }
    return '' +
      '<section class="card">' +
        '<span class="sec-eyebrow">' + esc(t("sug.eyebrow")) + '</span>' +
        '<h2 class="sec-title">' + esc(t("sug.title")) + '</h2>' +
        '<span class="sec-bar"></span>' +
        '<p class="sec-desc">' + esc(t("sug.desc")) + '</p>' +
        inner +
        note +
      '</section>';
  }

  // Render the verification verdict the backend supplies (answer_is_correct), plus the
  // reviewer note (missing_explanation) when present. Text only, no emoji (charter).
  function reviewCellHtml(s) {
    var ic = s.answer_is_correct;
    var key;
    var cls;
    if (ic === true) {
      key = "sug.answer.correct";
      cls = "rev-correct";
    } else if (ic === false) {
      key = "sug.answer.incorrect";
      cls = "rev-incorrect";
    } else {
      key = "sug.answer.unverified";
      cls = "rev-unverified";
    }
    var html = '<span class="rev ' + cls + '">' + esc(t(key)) + '</span>';
    var note = (s.missing_explanation == null) ? "" : String(s.missing_explanation).trim();
    if (note) {
      html += '<span class="rev-note">' + esc(truncate(note, 160)) + '</span>';
    }
    return html;
  }

  // The deterministic anchor the judge uses to gate correctness (expected_value plus its
  // type). Surfaced so a reviewer can sanity-check it before the question joins the golden set.
  function anchorCellHtml(s) {
    var v = (s.expected_value == null) ? "" : String(s.expected_value).trim();
    if (!v) {
      return '<span class="anchor-none">' + esc(t("common.dash")) + '</span>';
    }
    var ty = (s.expected_value_type == null) ? "" : String(s.expected_value_type).trim();
    var html = '<span class="anchor-val mono">' + esc(v) + '</span>';
    if (ty) {
      html += '<span class="anchor-type">' + esc(ty) + '</span>';
    }
    return html;
  }

  function suggestionsTableHtml() {
    var selected = state.suggestions.selected || {};
    var list = state.suggestions.list;
    var hasSelection = list.some(function (s) { return !!selected[s.suggestion_id]; });
    var allSelected = list.length > 0 && list.every(function (s) {
      return !!selected[s.suggestion_id];
    });
    var head = '' +
      '<thead><tr>' +
        '<th class="col-check" scope="col"><input type="checkbox" id="sugSelectAll" ' +
          'aria-label="' + esc(t("sug.selectAll")) + '"' + (allSelected ? " checked" : "") + '></th>' +
        '<th scope="col">' + esc(t("sug.col.question")) + '</th>' +
        '<th scope="col">' + esc(t("sug.col.expected")) + '</th>' +
        '<th scope="col">' + esc(t("sug.col.anchor")) + '</th>' +
        '<th scope="col">' + esc(t("sug.col.review")) + '</th>' +
        '<th scope="col">' + esc(t("sug.col.source")) + '</th>' +
        '<th scope="col">' + esc(t("sug.col.category")) + '</th>' +
        '<th scope="col">' + esc(t("sug.col.date")) + '</th>' +
      '</tr></thead>';
    var body = list.map(function (s) {
      var srcKey = (s.source === "chat") ? "sug.source.chat" : "sug.source.manual";
      var checked = selected[s.suggestion_id] ? " checked" : "";
      return '<tr>' +
        '<td class="col-check"><input type="checkbox" data-sug-cb ' +
          'value="' + esc(s.suggestion_id) + '"' + checked + ' ' +
          'aria-label="' + esc(t("sug.selectOne")) + '"></td>' +
        '<td class="cell-q">' + esc(s.question) + '</td>' +
        '<td class="cell-expected">' + esc(truncate(s.reference_answer, 140)) + '</td>' +
        '<td class="cell-anchor">' + anchorCellHtml(s) + '</td>' +
        '<td class="cell-review">' + reviewCellHtml(s) + '</td>' +
        '<td><span class="src">' + esc(t(srcKey)) + '</span></td>' +
        '<td>' + esc(s.category || t("common.dash")) + '</td>' +
        '<td class="cell-date">' + esc(s.created_at) + '</td>' +
      '</tr>';
    }).join("");
    var actions;
    if (state.suggestions.confirm) {
      // Inline (no-modal) confirm: promotion permanently writes into the golden set.
      actions = '' +
        '<div class="confirm-row" role="group">' +
          '<p class="confirm-msg">' +
            esc(t("sug.confirm", { count: fmtNum(state.suggestions.confirmCount) })) + '</p>' +
          '<div class="actions-row">' +
            '<button type="button" class="btn btn-primary" data-action="promote-go">' +
              esc(t("sug.go")) + '</button>' +
            '<button type="button" class="btn" data-action="promote-cancel">' +
              esc(t("sug.cancel")) + '</button>' +
          '</div>' +
        '</div>';
    } else {
      actions = '' +
        '<div class="actions-row">' +
          '<button type="button" class="btn btn-primary" data-action="promote" id="promoteBtn"' +
            (hasSelection ? "" : " disabled") + '>' +
            esc(t("sug.promote")) + '</button>' +
        '</div>';
    }
    return '' +
      '<div class="tbl-wrap"><table class="tbl">' + head + '<tbody>' + body + '</tbody></table></div>' +
      actions;
  }

  // Reflect a partial suggestion selection on the header "select all" box. The
  // indeterminate flag cannot be set via an HTML attribute, so it is set here in JS.
  function syncSelectAllState() {
    var box = byId("sugSelectAll");
    if (!box) {
      return;
    }
    var boxes = toArray(document.querySelectorAll("[data-sug-cb]"));
    var total = boxes.length;
    var checked = boxes.filter(function (c) { return c.checked; }).length;
    box.checked = total > 0 && checked === total;
    box.indeterminate = checked > 0 && checked < total;
  }

  /* ============================ actions ============================ */

  function loadConfig() {
    return callApi("GET", "config").then(function (res) {
      var d = res.data || {};
      if (d.status !== "ok") {
        state.loadError = true;
        render();
        return;
      }
      var cfg = d.config || {};
      state.form.agents = (cfg.agents || []).map(function (a) {
        return {
          agent_key: a.agent_key || "",
          agent_label: a.agent_label || "",
          project_key: a.project_key || "",
          agent_id: a.agent_id || "",
          modes: !!a.modes
        };
      });
      state.form.modes = (cfg.modes || []).slice();
      state.form.language = (cfg.language === "en") ? "en" : "fr";
      state.form.concurrency = clampInt(cfg.concurrency, 1, 8, 3);
      var qf = cfg.question_filter || {};
      state.form.filterCategories = (qf.categories || []).slice();
      // Remember the saved categories so a configured one with no checkbox (drift vs the
      // dataset categories) is not silently wiped on the next save.
      state.form.filterCategoriesLoaded = (qf.categories || []).slice();
      state.form.filterQuestionIds = (qf.question_ids || []).slice();
      var langs = qf.languages || [];
      state.form.filterLanguage = (langs.length === 1 && (langs[0] === "fr" || langs[0] === "en"))
        ? langs[0] : "all";

      state.meta.categories = (d.categories || []).slice();
      state.meta.questionCount = Number(d.question_count) || 0;
      state.meta.modeOptions = (d.mode_options && d.mode_options.length)
        ? d.mode_options.slice() : ["Smart", "Pro", "Claude"];
      state.meta.goldenDataset = cfg.golden_dataset || "";
      state.meta.judgeLlmId = cfg.judge_llm_id || "";
      state.meta.suggestions = cfg.suggestions || {};
      state.meta.runs = (d.runs || []).slice();
      state.loaded = true;
      state.loadError = false;
      // The form now mirrors the saved config: clear the dirty flag (re-enables launch).
      state.dirty = false;
      render();
    }).catch(function () {
      state.loadError = true;
      render();
    });
  }

  function loadSuggestions() {
    return callApi("GET", "suggestions").then(function (res) {
      var d = res.data || {};
      if (d.status && d.status !== "ok") {
        state.suggestions.loaded = true;
        state.suggestions.loadError = true;
        render();
        return;
      }
      state.suggestions.loaded = true;
      state.suggestions.loadError = false;
      state.suggestions.configured = !!d.configured;
      state.suggestions.list = (d.suggestions || []);
      // Keep only selections that still exist in the freshly loaded list (promoted or
      // removed suggestions drop out instead of lingering as stale ids).
      var present = {};
      state.suggestions.list.forEach(function (s) { present[s.suggestion_id] = true; });
      var pruned = {};
      Object.keys(state.suggestions.selected || {}).forEach(function (id) {
        if (present[id]) { pruned[id] = true; }
      });
      state.suggestions.selected = pruned;
      render();
    }).catch(function () {
      state.suggestions.loaded = true;
      state.suggestions.loadError = true;
      render();
    });
  }

  function buildConfigPayload() {
    syncFormFromDom();
    var agents = state.form.agents
      .filter(function (a) {
        return (a.agent_label || a.agent_id || a.project_key || a.agent_key);
      })
      .map(function (a, i) {
        var key = (a.agent_key || "").trim();
        if (!key) {
          key = slugify(a.agent_label) || ("agent_" + (i + 1));
        }
        return {
          agent_key: key,
          agent_label: (a.agent_label || "").trim() || key,
          project_key: (a.project_key || "").trim(),
          agent_id: (a.agent_id || "").trim(),
          modes: !!a.modes
        };
      });
    // Benchmark results are keyed by agent_key, so collisions (two agents with the same
    // label, or a derived key that clashes) would merge distinct agents into one bucket.
    // Disambiguate by suffixing later duplicates (_2, _3, ...).
    var seenKeys = {};
    agents.forEach(function (a) {
      var base = a.agent_key;
      if (seenKeys[a.agent_key]) {
        var n = 2;
        while (seenKeys[base + "_" + n]) { n += 1; }
        a.agent_key = base + "_" + n;
      }
      seenKeys[a.agent_key] = true;
    });
    var languages = [];
    if (state.form.filterLanguage === "fr" || state.form.filterLanguage === "en") {
      languages = [state.form.filterLanguage];
    }
    // Union the checkbox-derived categories with any saved category that has no checkbox
    // (not in the current dataset categories), so a save never silently drops it.
    var categories = state.form.filterCategories.slice();
    (state.form.filterCategoriesLoaded || []).forEach(function (c) {
      if (state.meta.categories.indexOf(c) === -1 && categories.indexOf(c) === -1) {
        categories.push(c);
      }
    });
    return {
      agents: agents,
      modes: state.form.modes.slice(),
      language: state.form.language,
      concurrency: clampInt(state.form.concurrency, 1, 8, 3),
      question_filter: {
        categories: categories,
        // Preserved verbatim: the UI never edits question ids, so re-send what the
        // server gave us instead of wiping a configured id filter.
        question_ids: state.form.filterQuestionIds.slice(),
        languages: languages
      }
    };
  }

  function saveConfig() {
    var payload = buildConfigPayload();
    // A mode-aware agent with no checked mode would run on zero mode variants (an empty
    // matrix). Block the save with a clear message rather than persist a useless config.
    var modeAware = payload.agents.some(function (a) { return a.modes === true; });
    if (modeAware && payload.modes.length === 0) {
      state.msg.save = { kind: "invalid", messages: [t("cfg.modesRequired")] };
      render();
      return;
    }
    var btn = byId("saveBtn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = t("cfg.saving");
    }
    callApi("POST", "config", payload).then(function (res) {
      var d = res.data || {};
      if (res.status === 200 && d.status === "ok") {
        state.msg.save = { kind: "ok", text: t("cfg.saved") };
        // Refresh from the server so the form mirrors the saved (resolved) config.
        return loadConfig();
      }
      if (d.error === "invalid_config") {
        state.msg.save = { kind: "invalid", messages: d.messages || [] };
      } else {
        state.msg.save = { kind: "error", text: t("cfg.saveError") };
      }
      render();
    }).catch(function () {
      state.msg.save = { kind: "error", text: t("cfg.saveError") };
      render();
    });
  }

  function launchRun() {
    // Swap the confirm panel back to the (now disabled) launch button via a full render,
    // then keep the run line in sync with targeted updates while polling.
    state.run.confirm = false;
    state.run.stateName = "starting";
    state.run.key = null;
    render();
    callApi("POST", "run").then(function (res) {
      var d = res.data || {};
      if (res.status === 200 && d.status === "ok") {
        state.run.stateName = "running";
        updateRunMsg();
        startPolling();
        return;
      }
      if (res.status === 409 || d.error === "already_running") {
        state.run.stateName = "error";
        state.run.key = "launch.already";
      } else if (d.error === "launch_unsupported") {
        state.run.stateName = "error";
        state.run.key = "launch.unsupported";
      } else {
        state.run.stateName = "error";
        state.run.key = "launch.error";
      }
      // Re-render so the launch button reappears enabled (an error state is not disabled).
      render();
    }).catch(function () {
      state.run.stateName = "error";
      state.run.key = "launch.error";
      render();
    });
  }

  function startPolling() {
    stopPolling();
    pollErrors = 0;
    pollTimer = setInterval(pollStatus, 5000);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // Decide from the opaque `last` outcome whether a finished run actually failed, so a
  // FAILED/ABORTED scenario is not reported with success styling. Empty/clear success
  // (e.g. "SUCCESS") stays "done".
  function runFailed(last) {
    if (!last) {
      return false;
    }
    var s;
    if (typeof last === "string") {
      s = last;
    } else if (typeof last === "object") {
      s = String(last.outcome || last.result || last.status || "");
    } else {
      s = String(last);
    }
    return /FAIL|ABORT|ERROR/i.test(s);
  }

  // A poll that failed (non-ok body or a rejected fetch). A transient blip is retried on
  // the next tick; after a few in a row we give up and surface a "lost contact" message
  // (so the UI never stays stuck on "Running" with launch permanently disabled).
  function handlePollError() {
    pollErrors += 1;
    if (pollErrors < 3) {
      return;
    }
    stopPolling();
    state.run.stateName = "error";
    state.run.key = "launch.lostContact";
    render();
  }

  function pollStatus() {
    callApi("GET", "run/status").then(function (res) {
      var d = res.data || {};
      if (d.status !== "ok") {
        handlePollError();
        return;
      }
      pollErrors = 0;
      if (d.running) {
        state.run.stateName = "running";
        updateRunMsg();
      } else {
        stopPolling();
        if (runFailed(d.last)) {
          state.run.stateName = "error";
          state.run.key = "launch.failed";
        } else {
          state.run.stateName = "done";
          state.run.key = null;
        }
        // Re-render so the launch button reappears enabled now the run is over.
        render();
      }
    }).catch(function () {
      handlePollError();
    });
  }

  function refreshPromoteEnabled() {
    var root = byId("bench-app");
    if (!root) { return; }
    var any = root.querySelector("[data-sug-cb]:checked");
    var btn = byId("promoteBtn");
    if (btn) {
      btn.disabled = !any;
    }
  }

  function promoteSelection() {
    var root = byId("bench-app");
    if (!root) { return; }
    var ids = toArray(root.querySelectorAll("[data-sug-cb]:checked"))
      .map(function (c) { return c.value; });
    if (!ids.length) {
      return;
    }
    var btn = byId("promoteBtn");
    if (btn) {
      btn.disabled = true;
      btn.textContent = t("sug.promoting");
    }
    callApi("POST", "suggestions/promote", { suggestion_ids: ids }).then(function (res) {
      var d = res.data || {};
      if (res.status === 200 && d.status === "ok") {
        var promoted = Number(d.promoted) || 0;
        state.msg.promote = (promoted > 0)
          ? { kind: "ok", text: t("sug.promoted", { count: fmtNum(promoted) }) }
          : { kind: "ok", text: t("sug.promotedNone") };
        return loadSuggestions();
      }
      state.msg.promote = { kind: "error", text: t("sug.promoteError") };
      render();
    }).catch(function () {
      state.msg.promote = { kind: "error", text: t("sug.promoteError") };
      render();
    });
  }

  /* ============================ events ============================ */

  function onClick(e) {
    var target = e.target;
    if (target.id === "themeToggle") { toggleTheme(); return; }
    if (target.id === "langToggle") { toggleLang(); return; }

    var actionEl = closestAttr(target, "data-action");
    if (!actionEl) { return; }
    var action = actionEl.getAttribute("data-action");

    if (action === "add-agent") {
      syncFormFromDom();
      state.form.agents.push({
        agent_key: "", agent_label: "", project_key: "", agent_id: "", modes: false
      });
      state.msg.save = null;
      state.dirty = true;
      state.run.confirm = false;
      render();
    } else if (action === "remove-agent") {
      syncFormFromDom();
      var idx = parseInt(actionEl.getAttribute("data-idx"), 10);
      if (!isNaN(idx)) {
        state.form.agents.splice(idx, 1);
      }
      state.msg.save = null;
      state.dirty = true;
      state.run.confirm = false;
      render();
    } else if (action === "save-config") {
      saveConfig();
    } else if (action === "retry-load") {
      state.loadError = false;
      render();
      loadConfig();
    } else if (action === "retry-suggestions") {
      state.suggestions.loadError = false;
      render();
      loadSuggestions();
    } else if (action === "launch") {
      // First click asks for confirmation (scope + cost); the second click launches.
      state.run.confirm = true;
      render();
    } else if (action === "launch-go") {
      launchRun();
    } else if (action === "launch-cancel") {
      state.run.confirm = false;
      render();
    } else if (action === "promote") {
      // First click asks for confirmation (count + permanence); the second promotes.
      syncFormFromDom();
      var sel = state.suggestions.selected || {};
      var cnt = Object.keys(sel).length;
      if (!cnt) {
        return;
      }
      state.suggestions.confirm = true;
      state.suggestions.confirmCount = cnt;
      render();
    } else if (action === "promote-go") {
      state.suggestions.confirm = false;
      render();
      promoteSelection();
    } else if (action === "promote-cancel") {
      state.suggestions.confirm = false;
      render();
    }
  }

  // A config control is anything whose change should mark the form dirty (and so disable
  // launch until saved). Suggestion checkboxes are deliberately excluded.
  function isConfigControl(el) {
    if (!el || el.nodeType !== 1) {
      return false;
    }
    return el.hasAttribute("data-af") ||
      el.hasAttribute("data-mode-cb") ||
      el.hasAttribute("data-cat-cb") ||
      el.hasAttribute("data-field");
  }

  // Flag the form as diverged from the saved config and refresh launch availability
  // without a full re-render (so a text field keeps focus while typing).
  function markDirty() {
    if (state.dirty) {
      return;
    }
    state.dirty = true;
    state.run.confirm = false;
    refreshLaunchAvail();
  }

  function onInput(e) {
    if (isConfigControl(e.target)) {
      markDirty();
    }
  }

  function onChange(e) {
    var target = e.target;
    if (target.id === "sugSelectAll") {
      var root = byId("bench-app");
      var checked = target.checked;
      toArray(root.querySelectorAll("[data-sug-cb]")).forEach(function (c) {
        c.checked = checked;
      });
      target.indeterminate = false;
      refreshPromoteEnabled();
      return;
    }
    if (target.hasAttribute("data-sug-cb")) {
      refreshPromoteEnabled();
      syncSelectAllState();
      return;
    }
    if (isConfigControl(target)) {
      // Give immediate feedback that out-of-range concurrency is clamped to 1-8.
      if (target.getAttribute("data-field") === "concurrency") {
        target.value = String(clampInt(target.value, 1, 8, state.form.concurrency));
      }
      markDirty();
    }
  }

  function closestAttr(el, attr) {
    while (el && el.nodeType === 1) {
      if (el.hasAttribute(attr)) {
        return el;
      }
      el = el.parentNode;
    }
    return null;
  }

  // Reflect an already-running benchmark on load (started in another tab, by another
  // operator, or from the DSS scenario UI), so the page is not misleadingly idle.
  function checkRunStatus() {
    return callApi("GET", "run/status").then(function (res) {
      var d = res.data || {};
      if (d.status === "ok" && d.running) {
        state.run.stateName = "running";
        state.run.key = null;
        render();
        startPolling();
      }
    }).catch(function () { /* a failed probe just leaves the launcher idle */ });
  }

  /* ============================ init ============================ */

  function init() {
    loadPrefs();
    applyTheme();
    applyLang();
    var root = byId("bench-app");
    if (!root) {
      return;
    }
    root.addEventListener("click", onClick);
    root.addEventListener("change", onChange);
    root.addEventListener("input", onInput);
    render();
    loadConfig();
    loadSuggestions();
    checkRunStatus();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
