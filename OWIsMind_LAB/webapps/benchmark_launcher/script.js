/* OWIsMind Benchmark - Launcher webapp (framework-free vanilla JS, no build).
 *
 * A REAL configuration FORM (never a raw JSON editor): edit the agents under test, the response
 * modes, the question filter, the concurrency and the benchmark language, then save (POST
 * api/config) and launch the Run_Benchmark scenario (POST api/run + poll api/run/status). It also
 * manages the golden set (add/edit/enable/delete) and reviews/promotes user-suggested questions.
 * Talks to the Python backend via getWebAppBackendUrl.
 *
 * UI ported from the OWIsMind benchmark mockup (tabs + aside + cards + golden table + modal +
 * toast), minus the left rail. The whole interface is rendered by this script into #bench-app, so
 * the language / theme toggles re-render in place. Bilingual: English default, French via the
 * top-right toggle (persisted). Orange charter styling lives in style.css. MOCK mode (no
 * getWebAppBackendUrl) serves sample data so preview.html renders a full page offline. */

(function () {
  "use strict";

  /* ============================ icons ============================ */

  var I = {
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M5 12l5 5 9-10"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/></svg>',
    edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20h4L18 10l-4-4L4 16v4zM14 6l4 4"/></svg>',
    save: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 4h11l3 3v13H5zM8 4v5h7M8 20v-6h8v6"/></svg>',
    info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.5"/></svg>',
    bulb: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10c1 1 1.5 1.5 1.5 3h5c0-1.5.5-2 1.5-3a6 6 0 0 0-4-10z"/></svg>',
    rocket: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3c3 1 5 4 5 8l-2 4H9l-2-4c0-4 2-7 5-8zM9 15l-2 3M15 15l2 3"/><circle cx="12" cy="9" r="1.4"/></svg>',
    x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6L6 18"/></svg>'
  };

  /* ============================ i18n ============================ */

  var DICT = {
    "hdr.eyebrow": { en: "OWIsMind Benchmark", fr: "OWIsMind Benchmark" },
    "hdr.h1": { en: "Launcher", fr: "Lanceur" },
    "hdr.sub": {
      en: "Configure the benchmark, launch a run, and promote the questions your users suggested. Results are read in the separate Results app.",
      fr: "Configurez le benchmark, lancez une execution et promouvez les questions suggerees par vos utilisateurs. Les resultats se consultent dans l'application Resultats."
    },

    "status.idle": { en: "Idle", fr: "En attente" },
    "status.running": { en: "Running", fr: "En cours" },
    "status.done": { en: "Completed", fr: "Termine" },

    "tab.config": { en: "Configuration", fr: "Configuration" },
    "tab.golden": { en: "Golden set", fr: "Jeu de reference" },
    "tab.suggest": { en: "Suggestions", fr: "Suggestions" },
    "tab.review": { en: "Review", fr: "Revue" },

    "cfg.eyebrow": { en: "Setup", fr: "Parametrage" },
    "cfg.title": { en: "Configuration", fr: "Configuration" },
    "cfg.note": {
      en: "This is the live configuration. Saving only changes the agents, modes, question filter, concurrency and language. The preserved settings are kept untouched.",
      fr: "Ceci est la configuration active. L'enregistrement ne modifie que les agents, les modes, le filtre de questions, la concurrence et la langue. Les reglages preserves ne sont pas touches."
    },

    "ag.label": { en: "Agents under test", fr: "Agents testes" },
    "ag.help": {
      en: "The agent id (like agent:038G7mlF) lives inside its own DSS project: do not prefix it. The project key tells the benchmark which project to call it in.",
      fr: "L'identifiant de l'agent (ex. agent:038G7mlF) vit dans son propre projet DSS : ne le prefixez pas. La cle de projet indique au benchmark dans quel projet l'appeler."
    },
    "ag.f.label": { en: "Label", fr: "Libelle" },
    "ag.f.key": { en: "Project key", fr: "Cle de projet" },
    "ag.f.id": { en: "Agent id", fr: "Identifiant d'agent" },
    "ag.modes": {
      en: "Supports response modes (Smart / Pro / Claude)",
      fr: "Gere les modes de reponse (Smart / Pro / Claude)"
    },
    "ag.remove": { en: "Remove", fr: "Retirer" },
    "ag.add": { en: "Add agent", fr: "Ajouter un agent" },
    "ag.empty": {
      en: "No agent yet. Add at least one to run the benchmark.",
      fr: "Aucun agent. Ajoutez-en au moins un pour lancer le benchmark."
    },

    "rm.title": { en: "Response modes", fr: "Modes de reponse" },
    "rm.help": {
      en: "Only mode-aware agents are tested across the checked modes. Other agents get a single default call.",
      fr: "Seuls les agents compatibles sont testes sur les modes coches. Les autres recoivent un appel par defaut."
    },

    "qt.title": { en: "Questions to test", fr: "Questions a tester" },
    "qt.help": {
      en: "Pick the categories to test. Empty selection = all {n} active questions.",
      fr: "Choisissez les categories a tester. Aucune selection = les {n} questions actives."
    },
    "qt.nocats": {
      en: "No category in the golden set yet.",
      fr: "Aucune categorie dans le jeu de reference pour l'instant."
    },
    "qt.langfilter": { en: "Language filter", fr: "Filtre de langue" },

    "rp.title": { en: "Run parameters", fr: "Parametres d'execution" },
    "rp.conc": { en: "Concurrency", fr: "Concurrence" },
    "rp.conc.help": {
      en: "Questions run in parallel (1-8, kept low for instance safety). Out-of-range values are clamped.",
      fr: "Questions en parallele (1-8, faible pour la securite de l'instance). Les valeurs hors plage sont bornees."
    },
    "rp.lang": { en: "Benchmark language", fr: "Langue du benchmark" },
    "rp.lang.help": {
      en: "Language used for the run report and the agent prompts. To choose which golden questions are tested, use the language filter.",
      fr: "Langue du rapport d'execution et des prompts d'agent. Pour choisir les questions testees, utilisez le filtre de langue."
    },

    "opt.all": { en: "All", fr: "Toutes" },
    "opt.en": { en: "English (en)", fr: "Anglais (en)" },
    "opt.fr": { en: "French (fr)", fr: "Francais (fr)" },

    "save.btn": { en: "Save configuration", fr: "Enregistrer la configuration" },
    "save.saving": { en: "Saving...", fr: "Enregistrement..." },
    "save.hint": {
      en: "Live config - applies to the next run.",
      fr: "Config active - s'applique a la prochaine execution."
    },
    "save.invalidTitle": { en: "The configuration could not be saved:", fr: "La configuration n'a pas pu etre enregistree :" },
    "save.error": {
      en: "Could not save the configuration. Check your write access to the LAB project.",
      fr: "Impossible d'enregistrer la configuration. Verifiez votre acces en ecriture au projet LAB."
    },
    "save.loadError": {
      en: "Could not load the configuration. Check your access to the LAB project.",
      fr: "Impossible de charger la configuration. Verifiez votre acces au projet LAB."
    },

    "run.eyebrow": { en: "Run", fr: "Execution" },
    "run.title": { en: "Launch", fr: "Lancer" },
    "run.note": {
      en: "Launch the Run_Benchmark scenario asynchronously. Only one run can be in progress at a time.",
      fr: "Lance le scenario Run_Benchmark de facon asynchrone. Une seule execution a la fois."
    },
    "run.btn": { en: "Launch the benchmark", fr: "Lancer le benchmark" },
    "run.btn.running": { en: "Run in progress...", fr: "Execution en cours..." },
    "run.last": { en: "Last run", fr: "Derniere execution" },
    "run.never": { en: "never", fr: "jamais" },
    "run.save1": {
      en: "Launching runs the last saved configuration - save your edits first.",
      fr: "Le lancement utilise la derniere configuration enregistree - enregistrez d'abord vos modifications."
    },
    "run.save2": {
      en: "Launching may require scenario permissions. If unsupported, run Run_Benchmark from the DSS scenario UI.",
      fr: "Le lancement peut necessiter des permissions de scenario. Si indisponible, lancez Run_Benchmark depuis l'UI scenario DSS."
    },
    "run.dirty": {
      en: "Unsaved changes - save the configuration before launching.",
      fr: "Modifications non enregistrees - enregistrez la configuration avant de lancer."
    },
    "run.launched": { en: "Benchmark launched.", fr: "Benchmark lance." },
    "run.already": { en: "A run is already in progress.", fr: "Une execution est deja en cours." },
    "run.unsupported": {
      en: "Launch is not supported here. Run the Run_Benchmark scenario from the DSS scenario UI.",
      fr: "Le lancement n'est pas supporte ici. Lancez le scenario Run_Benchmark depuis l'UI scenario DSS."
    },
    "run.error": { en: "Could not launch the run.", fr: "Impossible de lancer l'execution." },
    "run.finished": { en: "Run completed - open the Results app to read it.", fr: "Execution terminee - ouvrez l'application Resultats pour la consulter." },
    "run.lostContact": { en: "Lost contact with the run. Check the DSS scenario log.", fr: "Contact perdu avec l'execution. Consultez le log du scenario DSS." },

    "pr.eyebrow": { en: "Preserved settings", fr: "Reglages preserves" },
    "pr.title": { en: "Not editable here", fr: "Non modifiable ici" },
    "pr.golden": { en: "Golden dataset", fr: "Jeu de reference" },
    "pr.judge": { en: "Judge model", fr: "Modele juge" },
    "pr.suggest": { en: "Suggestions source", fr: "Source des suggestions" },
    "pr.na": { en: "Not configured", fr: "Non configuree" },

    "gs.eyebrow": { en: "Golden set", fr: "Jeu de reference" },
    "gs.title": { en: "Questions", fr: "Questions" },
    "gs.note": {
      en: "The reference questions the benchmark scores the agents against, with the answer you expect. Add, edit, enable/disable or remove them. Changes apply to the next run.",
      fr: "Les questions de reference sur lesquelles le benchmark evalue les agents, avec la reponse attendue. Ajoutez, modifiez, activez/desactivez ou retirez-les. Les changements s'appliquent a la prochaine execution."
    },
    "gs.count": { en: "{n} question(s), {a} active", fr: "{n} question(s), {a} active(s)" },
    "gs.add": { en: "Add a question", fr: "Ajouter une question" },
    "gs.empty": {
      en: "No question yet. Add the first one, or promote a user suggestion.",
      fr: "Aucune question pour l'instant. Ajoutez la premiere, ou promouvez une suggestion."
    },
    "gs.loadError": { en: "Could not load the golden questions.", fr: "Impossible de charger les questions de reference." },

    "th.status": { en: "On", fr: "Actif" },
    "th.q": { en: "Question", fr: "Question" },
    "th.a": { en: "Expected answer", fr: "Reponse attendue" },
    "th.anchor": { en: "Anchor", fr: "Ancre" },
    "th.cat": { en: "Category", fr: "Categorie" },
    "th.lang": { en: "Lang", fr: "Langue" },
    "th.act": { en: "Actions", fr: "Actions" },

    "q.status.active": { en: "Active", fr: "Active" },
    "q.status.inactive": { en: "Inactive", fr: "Inactive" },
    "q.edit": { en: "Edit", fr: "Modifier" },
    "q.delete": { en: "Delete", fr: "Supprimer" },
    "q.deleteConfirm": { en: "Delete this question?", fr: "Supprimer cette question ?" },
    "q.deleteGo": { en: "Delete", fr: "Supprimer" },
    "q.deleteCancel": { en: "Cancel", fr: "Annuler" },
    "q.saved": { en: "Question updated", fr: "Question mise a jour" },
    "q.added": { en: "Question added", fr: "Question ajoutee" },
    "q.removed": { en: "Question removed", fr: "Question retiree" },
    "q.toggled": { en: "Question updated", fr: "Question mise a jour" },
    "q.saveError": { en: "Could not save the question.", fr: "Impossible d'enregistrer la question." },
    "q.deleteError": { en: "Could not delete the question.", fr: "Impossible de supprimer la question." },

    "md.add": { en: "Add a question", fr: "Ajouter une question" },
    "md.edit": { en: "Edit question", fr: "Modifier la question" },
    "md.q": { en: "Question", fr: "Question" },
    "md.a": { en: "Expected answer", fr: "Reponse attendue" },
    "md.anchor": { en: "Anchor value (optional)", fr: "Valeur d'ancre (optionnel)" },
    "md.anchorType": { en: "Anchor type", fr: "Type d'ancre" },
    "md.valueHelp": {
      en: "The anchor is the exact value the judge checks against (a number, currency, date, or list). Leave it empty for an open answer.",
      fr: "L'ancre est la valeur exacte que le juge controle (un nombre, une devise, une date ou une liste). Laissez vide pour une reponse ouverte."
    },
    "md.cat": { en: "Category", fr: "Categorie" },
    "md.lang": { en: "Language", fr: "Langue" },
    "md.active": { en: "Active in the next run", fr: "Active a la prochaine execution" },
    "md.cancel": { en: "Cancel", fr: "Annuler" },
    "md.save": { en: "Save question", fr: "Enregistrer" },

    "vt.none": { en: "(none)", fr: "(aucun)" },
    "vt.numeric": { en: "Number", fr: "Nombre" },
    "vt.currency": { en: "Currency", fr: "Devise" },
    "vt.date": { en: "Date", fr: "Date" },
    "vt.string": { en: "Text", fr: "Texte" },
    "vt.list": { en: "List", fr: "Liste" },

    "sg.eyebrow": { en: "Golden set", fr: "Jeu de reference" },
    "sg.title": { en: "User suggestions", fr: "Suggestions utilisateurs" },
    "sg.note": {
      en: "Questions your users suggested, pending review. Select the good ones and promote them into the golden set.",
      fr: "Questions suggerees par vos utilisateurs, en attente de revue. Selectionnez les bonnes et promouvez-les dans le jeu de reference."
    },
    "sg.empty.h": { en: "Suggestions source not configured", fr: "Source de suggestions non configuree" },
    "sg.empty.p": {
      en: "Add the benchmark.suggestions block to the project variable to start collecting user suggestions.",
      fr: "Ajoutez le bloc benchmark.suggestions a la variable de projet pour collecter les suggestions."
    },
    "sg.none": { en: "No pending suggestion right now.", fr: "Aucune suggestion en attente pour l'instant." },
    "sg.loadError": { en: "Could not load the suggestions.", fr: "Impossible de charger les suggestions." },
    "sg.col.q": { en: "Question", fr: "Question" },
    "sg.col.a": { en: "Expected answer", fr: "Reponse attendue" },
    "sg.col.anchor": { en: "Anchor", fr: "Ancre" },
    "sg.col.review": { en: "Review", fr: "Revue" },
    "sg.col.source": { en: "Source", fr: "Source" },
    "sg.col.cat": { en: "Category", fr: "Categorie" },
    "sg.col.date": { en: "Date", fr: "Date" },
    "sg.review.correct": { en: "Correct", fr: "Correcte" },
    "sg.review.incorrect": { en: "Incorrect", fr: "Incorrecte" },
    "sg.review.unverified": { en: "Unverified", fr: "Non verifiee" },
    "sg.source.chat": { en: "Conversation", fr: "Conversation" },
    "sg.source.manual": { en: "Manual", fr: "Manuel" },
    "sg.selectAll": { en: "Select all suggestions", fr: "Tout selectionner" },
    "sg.selectOne": { en: "Select this suggestion", fr: "Selectionner cette suggestion" },
    "sg.promote": { en: "Promote selection", fr: "Promouvoir la selection" },
    "sg.confirm": { en: "Promote {n} question(s) into the golden set? This is permanent.", fr: "Promouvoir {n} question(s) dans le jeu de reference ? Cette action est definitive." },
    "sg.go": { en: "Confirm promotion", fr: "Confirmer la promotion" },
    "sg.cancel": { en: "Cancel", fr: "Annuler" },
    "sg.promoted": { en: "{n} question(s) added to the golden set.", fr: "{n} question(s) ajoutee(s) au jeu de reference." },
    "sg.promotedNone": { en: "No new question added (already in the golden set).", fr: "Aucune nouvelle question ajoutee (deja dans le jeu de reference)." },
    "sg.promoteError": { en: "Could not promote the selection.", fr: "Impossible de promouvoir la selection." },

    "ag.added": { en: "Agent added", fr: "Agent ajoute" },
    "ag.removed": { en: "Agent removed", fr: "Agent retire" },
    "cfg.saved": { en: "Configuration saved", fr: "Configuration enregistree" },

    "rv.eyebrow": { en: "Human review", fr: "Revue humaine" },
    "rv.title": { en: "Verdict review", fr: "Revue des verdicts" },
    "rv.note": {
      en: "Review the judge's verdicts for one run and override them when the judge got it wrong. Overrides are saved per run.",
      fr: "Revoyez les verdicts du juge pour une execution et corrigez-les quand le juge s'est trompe. Les corrections sont enregistrees par execution."
    },
    "rv.run": { en: "Run", fr: "Execution" },
    "rv.onlyNeeds": { en: "Only needs-review", fr: "Seulement a revoir" },
    "rv.caption": {
      en: "Re-running the SAME run id resets its overrides. Overrides on past runs survive new runs.",
      fr: "Relancer le MEME identifiant d'execution reinitialise ses corrections. Les corrections des executions passees survivent aux nouvelles."
    },
    "rv.count": { en: "{n} verdict(s), needs-review first", fr: "{n} verdict(s), a revoir d'abord" },
    "rv.loadError": { en: "Could not load the review.", fr: "Impossible de charger la revue." },
    "rv.noRuns.h": { en: "No benchmark run yet", fr: "Aucune execution de benchmark" },
    "rv.noRuns.p": {
      en: "Launch a run from the Configuration tab to review its verdicts here.",
      fr: "Lancez une execution depuis l'onglet Configuration pour en revoir les verdicts ici."
    },
    "rv.noRows": { en: "No row to review for this run.", fr: "Aucune ligne a revoir pour cette execution." },
    "rv.noNeeds": { en: "No row needs review in this run.", fr: "Aucune ligne a revoir dans cette execution." },
    "rv.agentMissing": {
      en: "Agent key missing on these rows: overrides cannot match until the backend includes agent_key.",
      fr: "Cle d'agent absente sur ces lignes : les corrections ne peuvent pas correspondre tant que le backend n'inclut pas agent_key."
    },

    "rv.effective": { en: "Effective", fr: "Effectif" },
    "rv.v.correct": { en: "Correct", fr: "Correcte" },
    "rv.v.incorrect": { en: "Incorrect", fr: "Incorrecte" },
    "rv.overriddenBy": { en: "Overridden by {who}", fr: "Corrige par {who}" },
    "rv.needsReview": { en: "Needs review", fr: "A revoir" },

    "rv.judge": { en: "Judge", fr: "Juge" },
    "rv.score": { en: "Score", fr: "Score" },
    "rv.obj.hit": { en: "Anchor hit", fr: "Ancre OK" },
    "rv.obj.miss": { en: "Anchor miss", fr: "Ancre KO" },
    "rv.obj.na": { en: "No anchor", fr: "Sans ancre" },
    "rv.judgeComment": { en: "Judge comment", fr: "Commentaire du juge" },
    "rv.reference": { en: "Reference answer", fr: "Reponse de reference" },
    "rv.expected": { en: "Expected value", fr: "Valeur attendue" },
    "rv.humanNote": { en: "Strictness note", fr: "Note de severite" },
    "rv.answer.show": { en: "Show agent answer", fr: "Voir la reponse de l'agent" },
    "rv.answer.hide": { en: "Hide agent answer", fr: "Masquer la reponse de l'agent" },
    "rv.answer.empty": { en: "(no answer captured)", fr: "(aucune reponse capturee)" },

    "rv.commentPh": { en: "Optional override reason", fr: "Raison de la correction (optionnel)" },
    "rv.markCorrect": { en: "Mark correct", fr: "Marquer correcte" },
    "rv.markIncorrect": { en: "Mark incorrect", fr: "Marquer incorrecte" },
    "rv.clear": { en: "Clear override", fr: "Annuler la correction" },
    "rv.reviewedBy": { en: "Reviewed by {who} on {when}", fr: "Revue par {who} le {when}" },
    "rv.humanComment": { en: "Reviewer note", fr: "Note du relecteur" },

    "rv.toast.set": { en: "Override saved", fr: "Correction enregistree" },
    "rv.toast.cleared": { en: "Override cleared", fr: "Correction annulee" },
    "rv.toast.nomatch": { en: "No matching row (agent key missing?)", fr: "Aucune ligne correspondante (cle d'agent absente ?)" },
    "rv.toast.error": { en: "Could not save the override.", fr: "Impossible d'enregistrer la correction." },

    "common.dash": { en: "-", fr: "-" },
    "common.loading": { en: "Loading...", fr: "Chargement..." },
    "common.retry": { en: "Retry", fr: "Reessayer" }
  };

  function t(key, vars) {
    var entry = DICT[key];
    var s = entry ? (entry[ui.lang] || entry.en) : key;
    if (vars) {
      for (var k in vars) {
        if (Object.prototype.hasOwnProperty.call(vars, k)) {
          s = s.replace("{" + k + "}", vars[k]);
        }
      }
    }
    return s;
  }

  var VALUE_TYPES = ["numeric", "currency", "date", "string", "list"];

  /* ============================ state ============================ */

  var ui = { theme: "light", lang: "en" };

  var S = {
    tab: "config",
    loaded: false,
    loadError: false,
    // config form
    agents: [],
    modes: [],
    modeOptions: ["Smart", "Pro", "Claude"],
    categories: [],
    filterCategories: [],
    filterCategoriesLoaded: [],
    filterQuestionIds: [],
    filterLanguage: "all",
    concurrency: 1,
    benchLang: "en",
    questionCount: 0,
    runs: [],
    preserved: { golden: "", judge: "", suggestions: {} },
    dirty: false,
    saving: false,
    saveError: null,
    // run
    running: false,
    runDone: false,
    progress: 0,
    runMsg: null,
    // golden
    golden: { loaded: false, loadError: false, list: [], confirmDelete: null },
    // modal editor
    editor: { open: false, isNew: false, qid: "", error: null },
    // suggestions
    suggestions: { loaded: false, loadError: false, configured: false, list: [], selected: {}, confirm: false, confirmCount: 0 },
    // review (human-in-the-loop verdict override)
    review: { loaded: false, loadError: false, runId: "", onlyNeedsReview: false, runs: [], rows: [], count: 0, expanded: {}, saving: {} }
  };

  var newAgentSeq = 0;
  function genKey() {
    newAgentSeq += 1;
    return "agent_" + newAgentSeq;
  }

  /* ============================ dom helpers ============================ */

  function byId(id) { return document.getElementById(id); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function setHTML(id, html) { var e = byId(id); if (e) { e.innerHTML = html; } }
  function setText(id, txt) { var e = byId(id); if (e) { e.textContent = txt; } }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function truncate(s, n) {
    s = String(s == null ? "" : s);
    return (s.length > n) ? (s.slice(0, n).replace(/\s+\S*$/, "") + "...") : s;
  }
  function clampInt(v, lo, hi, dflt) {
    var n = parseInt(v, 10);
    if (isNaN(n)) { return dflt; }
    return Math.max(lo, Math.min(hi, n));
  }
  function fmtNum(n) {
    var v = Number(n);
    if (isNaN(v)) { return String(n); }
    try { return v.toLocaleString(ui.lang === "fr" ? "fr-FR" : "en-US"); }
    catch (e) { return String(v); }
  }
  function fmtCost(n) {
    var v = Number(n);
    if (isNaN(v)) { return ""; }
    try { return v.toLocaleString(ui.lang === "fr" ? "fr-FR" : "en-US", { minimumFractionDigits: 2, maximumFractionDigits: 4 }); }
    catch (e) { return String(v); }
  }

  /* ============================ API ============================ */

  function hasBackend() { return typeof getWebAppBackendUrl === "function"; }

  function callApi(method, path, body) {
    if (!hasBackend()) { return mockApi(method, path, body); }
    var opts = { method: method, headers: { "Content-Type": "application/json" } };
    if (body !== undefined) { opts.body = JSON.stringify(body); }
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
      agents: [{ agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", project_key: "OWISMIND_DEV", agent_id: "agent:038G7mlF", modes: true }],
      modes: ["Smart", "Claude"],
      language: "fr",
      concurrency: 3,
      golden_dataset: "golden_questions_v1_prepared",
      question_filter: { categories: ["revenue"], question_ids: [], languages: [] },
      judge_llm_id: "anthropic:claude-sonnet-4-6",
      suggestions: { connection: "SQL_owi", table: "OWISMIND_DEV_owismind_webapp_golden_suggestions_v1", promoted_dataset: "benchmark_suggestions_promoted" }
    },
    categories: ["revenue", "tickets", "offre"],
    question_count: 42,
    mode_options: ["Smart", "Pro", "Claude"],
    runs: [{ run_id: "run_20260626_0902", run_timestamp: "2026-06-26 09:02:34" }],
    golden: [
      { question_id: "a_revenue001", question: "Quel est le revenu reel du compte Maroc Telecom sur l'annee en cours ?", reference_answer: "Le revenu reel (ACTUALS) du compte Maroc Telecom sur l'annee en cours est de 4 218 540 euros, toutes periodes confondues.", expected_value: "4218540", expected_value_type: "currency", category: "revenue", language: "fr", active: true, notes: "" },
      { question_id: "u_sug_d4e5f6", question: "How many distinct open trouble tickets does Algerie Telecom currently have?", reference_answer: "Algerie Telecom currently has 37 distinct open trouble tickets (counted on the latest snapshot per ticket id).", expected_value: "37", expected_value_type: "numeric", category: "tickets", language: "en", active: true, notes: "promoted from user suggestion sug_d4e5f6 (source=manual)" },
      { question_id: "a_offer002", question: "Quelle est la hierarchie d'offre pour le produit IPL ?", reference_answer: "IPL est un SolutionLine (niveau intermediaire de la hierarchie d'offre).", expected_value: "", expected_value_type: "", category: "offre", language: "fr", active: false, notes: "desactivee le temps de valider la reponse" }
    ],
    suggestions: [
      { suggestion_id: "sug_a1b2c3", user_id: "marie.dupont", source: "chat", question: "Quel est le revenu reel du compte Maroc Telecom sur l'annee en cours ?", reference_answer: "Le revenu reel (ACTUALS) du compte Maroc Telecom sur l'annee en cours est de 4 218 540 euros, toutes periodes confondues.", answer_is_correct: true, missing_explanation: "", expected_value: "4218540", expected_value_type: "currency", category: "revenue", language: "fr", created_at: "2026-06-24 14:09:22" },
      { suggestion_id: "sug_g7h8i9", user_id: "sara.benali", source: "chat", question: "Quel est le budget 2026 du produit Roaming Hub pour le client Airbus ?", reference_answer: "Le budget 2026 du produit Roaming Hub pour Airbus est de 1 050 000 euros (scenario BUDGET, periode 2026).", answer_is_correct: null, missing_explanation: "L'agent a confondu Roaming Hub avec Roaming Sponsor.", expected_value: "1050000", expected_value_type: "currency", category: "revenue", language: "fr", created_at: "2026-06-23 17:30:05" }
    ],
    review: {
      runs: [
        { run_id: "run_20260626_0902", run_timestamp: "2026-06-26 09:02:34" },
        { run_id: "run_20260625_1740", run_timestamp: "2026-06-25 17:40:11" }
      ],
      rows: {
        "run_20260626_0902": [
          { question_id: "u_sug_d4e5f6", question: "How many distinct open trouble tickets does Algerie Telecom currently have?", category: "tickets", agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", mode: "Smart", status: "ok", objective_match: false, judge_score: 0.4, judge_verdict: "incorrect", judge_comment: "The agent answered 41 tickets but the reference anchor is 37: it counted raw snapshot rows instead of distinct ticket ids.", reference_answer: "Algerie Telecom currently has 37 distinct open trouble tickets (counted on the latest snapshot per ticket id).", answer_preview: "Algerie Telecom currently has 41 open trouble tickets.\n\nSQL: SELECT COUNT(*) FROM trouble_tickets WHERE status = 'OPEN' AND account = 'Algerie Telecom'", notes: "Strictness: accept the distinct count on the latest snapshot per id. Raw row counts are wrong.", expected_value: "37", expected_value_type: "numeric", correct: false, needs_review: true, latency_str: "12.4s", estimated_cost: 0.0182 },
          { question_id: "a_offer002", question: "Quelle est la hierarchie d'offre pour le produit IPL ?", category: "offre", agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", mode: "Claude", status: "ok", objective_match: null, judge_score: 0.6, judge_verdict: "incorrect", judge_comment: "The agent called IPL a Product; the reference says SolutionLine.", reference_answer: "IPL est un SolutionLine (niveau intermediaire de la hierarchie d'offre).", answer_preview: "IPL est un Product dans la hierarchie d'offre.", notes: "Open answer: judge on the hierarchy level named (SolutionLine).", expected_value: "", expected_value_type: "", correct: false, needs_review: true, latency_str: "15.7s", estimated_cost: 0.0345 },
          { question_id: "a_revenue001", question: "Quel est le revenu reel du compte Maroc Telecom sur l'annee en cours ?", category: "revenue", agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", mode: "Smart", status: "ok", objective_match: true, judge_score: 0.95, judge_verdict: "correct", judge_comment: "Matches the anchor value 4 218 540 and the expected scope (ACTUALS, all periods).", reference_answer: "Le revenu reel (ACTUALS) du compte Maroc Telecom sur l'annee en cours est de 4 218 540 euros, toutes periodes confondues.", answer_preview: "Le revenu reel (ACTUALS) du compte Maroc Telecom est de 4 218 540 EUR sur l'annee en cours, toutes periodes confondues.", notes: "", expected_value: "4218540", expected_value_type: "currency", correct: true, needs_review: false, latency_str: "9.1s", estimated_cost: 0.0121 }
        ],
        "run_20260625_1740": [
          { question_id: "a_revenue001", question: "Quel est le revenu reel du compte Maroc Telecom sur l'annee en cours ?", category: "revenue", agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", mode: "Pro", status: "ok", objective_match: true, judge_score: 0.9, judge_verdict: "correct", judge_comment: "Anchor value matches.", reference_answer: "Le revenu reel (ACTUALS) du compte Maroc Telecom sur l'annee en cours est de 4 218 540 euros, toutes periodes confondues.", answer_preview: "Le revenu reel est de 4 218 540 EUR.", notes: "", expected_value: "4218540", expected_value_type: "currency", correct: true, needs_review: false, latency_str: "8.3s", estimated_cost: 0.0150 }
        ]
      }
    }
  };
  var mockRun = { remaining: 0 };
  var mockPromoted = {};
  var mockOverrides = {};

  function parseQuery(path) {
    var out = {};
    var qi = path.indexOf("?");
    if (qi === -1) { return out; }
    path.slice(qi + 1).split("&").forEach(function (pair) {
      if (!pair) { return; }
      var kv = pair.split("=");
      out[decodeURIComponent(kv[0])] = decodeURIComponent(kv[1] || "");
    });
    return out;
  }

  function mockEffectiveRow(runId, r) {
    var key = [runId, r.question_id, r.agent_key || "", r.mode || ""].join("|");
    var ov = mockOverrides[key];
    if (ov) {
      r.overridden = true;
      r.human_verdict = ov.verdict;
      r.human_comment = ov.comment;
      r.reviewed_by = ov.reviewed_by;
      r.reviewed_at = ov.reviewed_at;
      r.effective_verdict = ov.verdict;
      r.effective_correct = (ov.verdict === "correct");
    } else {
      r.overridden = false;
      r.human_verdict = "";
      r.human_comment = "";
      r.reviewed_by = "";
      r.reviewed_at = "";
      r.effective_correct = !!r.correct;
      r.effective_verdict = r.correct ? "correct" : "incorrect";
    }
    return r;
  }

  function mockApi(method, path, body) {
    var status = 200;
    var data = {};
    var path0 = path.split("?")[0];
    if (method === "GET" && path === "config") {
      data = { status: "ok", config: deepCopy(MOCK.config), categories: MOCK.categories.slice(), question_count: MOCK.question_count, mode_options: MOCK.mode_options.slice(), runs: MOCK.runs.slice() };
    } else if (method === "POST" && path === "config") {
      var merged = deepCopy(MOCK.config);
      if (body) {
        if (body.agents) { merged.agents = body.agents; }
        if (body.modes) { merged.modes = body.modes; }
        if (body.language) { merged.language = body.language; }
        if (body.concurrency) { merged.concurrency = body.concurrency; }
        if (body.question_filter) { merged.question_filter = body.question_filter; }
      }
      if (!merged.agents || !merged.agents.length) {
        status = 400;
        data = { status: "error", error: "invalid_config", messages: ["no valid agent: 'agents' must list at least one {agent_key, project_key, agent_id}"] };
      } else {
        MOCK.config = merged;
        data = { status: "ok", config: deepCopy(merged) };
      }
    } else if (method === "POST" && path === "run") {
      mockRun.remaining = 2;
      data = { status: "ok", launched: true };
    } else if (method === "GET" && path === "run/status") {
      var running = mockRun.remaining > 0;
      if (running) { mockRun.remaining -= 1; }
      data = { status: "ok", running: running, last: running ? null : "SUCCESS" };
    } else if (method === "GET" && path === "suggestions") {
      var pending = MOCK.suggestions.filter(function (s) { return !mockPromoted[s.suggestion_id]; });
      data = { status: "ok", configured: true, suggestions: pending };
    } else if (method === "POST" && path === "suggestions/promote") {
      var ids = (body && body.suggestion_ids) || [];
      var promoted = 0;
      ids.forEach(function (id) { if (!mockPromoted[id]) { mockPromoted[id] = true; promoted += 1; } });
      data = { status: "ok", promoted: promoted, recorded: ids.length };
    } else if (method === "GET" && path === "golden") {
      data = { status: "ok", questions: MOCK.golden.slice() };
    } else if (method === "POST" && path === "golden/save") {
      var q = (body && body.question || "").trim();
      var ref = (body && body.reference_answer || "").trim();
      if (!q || !ref) {
        status = 400;
        data = { status: "error", error: "invalid_question", messages: ["question and reference_answer are required"] };
      } else {
        var qid = (body && body.question_id || "").trim();
        var isNew = !qid;
        if (isNew) { qid = "a_mock_" + (MOCK.golden.length + 1); }
        var nrow = { question_id: qid, question: q, reference_answer: ref, expected_value: (body.expected_value || ""), expected_value_type: (body.expected_value_type || ""), category: (body.category || ""), language: (body.language === "en") ? "en" : "fr", active: body.active !== false, notes: (body.notes || "") };
        var found = false;
        MOCK.golden = MOCK.golden.map(function (g) { if (g.question_id === qid) { found = true; return nrow; } return g; });
        if (!found) { MOCK.golden.push(nrow); }
        data = { status: "ok", question_id: qid, created: isNew, count: MOCK.golden.length };
      }
    } else if (method === "POST" && path === "golden/delete") {
      var delId = (body && body.question_id || "").trim();
      var before = MOCK.golden.length;
      MOCK.golden = MOCK.golden.filter(function (g) { return g.question_id !== delId; });
      data = { status: "ok", deleted: MOCK.golden.length < before, count: MOCK.golden.length };
    } else if (method === "GET" && path0 === "review") {
      var params = parseQuery(path);
      var runId = params.run_id || (MOCK.review.runs[0] && MOCK.review.runs[0].run_id) || "";
      var base = (MOCK.review.rows[runId] || []).map(deepCopy);
      var rows = base.map(function (r) { return mockEffectiveRow(runId, r); });
      if (params.only_needs_review === "1") { rows = rows.filter(function (r) { return !!r.needs_review; }); }
      rows.sort(function (a, b) { return (b.needs_review ? 1 : 0) - (a.needs_review ? 1 : 0); });
      data = { status: "ok", run_id: runId, count: rows.length, runs: MOCK.review.runs.slice(), rows: rows };
    } else if (method === "POST" && path0 === "override") {
      var ob = body || {};
      var okey = [ob.run_id, ob.question_id, ob.agent_key || "", ob.mode || ""].join("|");
      if (ob.verdict === "correct" || ob.verdict === "incorrect") {
        mockOverrides[okey] = { verdict: ob.verdict, comment: ob.comment || "", reviewed_by: "preview.admin", reviewed_at: "2026-06-26 10:15:00" };
      } else {
        delete mockOverrides[okey];
      }
      data = { status: "ok", matched: 1 };
    } else {
      status = 404;
      data = { status: "error", error: "not_found" };
    }
    return new Promise(function (resolve) { setTimeout(function () { resolve({ status: status, data: data }); }, 120); });
  }

  function deepCopy(obj) { return JSON.parse(JSON.stringify(obj)); }

  /* ============================ theme + language ============================ */

  function loadPrefs() {
    try { var th = localStorage.getItem("bench-theme"); if (th === "light" || th === "dark") { ui.theme = th; } } catch (e) { /* */ }
    try { var lg = localStorage.getItem("bench-lang"); if (lg === "en" || lg === "fr") { ui.lang = lg; } } catch (e2) { /* */ }
  }
  function applyTheme() { document.documentElement.setAttribute("data-theme", ui.theme); }
  function applyLang() { document.documentElement.setAttribute("lang", ui.lang); }

  /* ============================ shell (built once) ============================ */

  var built = false;
  function ensureShell() {
    if (built) { return; }
    var root = byId("bench-app");
    if (!root) { return; }
    root.innerHTML = shellHtml();
    built = true;
    wireStatic();
  }

  function shellHtml() {
    return '' +
      '<div class="main">' +
        '<div class="util"><span class="util-sp"></span>' +
          '<span class="run-pill idle" id="runPill"><span class="dot"></span><span id="runStatusTxt"></span></span>' +
        '</div>' +
        '<header class="header">' +
          '<div>' +
            '<p class="eyebrow" data-i18n="hdr.eyebrow"></p>' +
            '<h1 data-i18n="hdr.h1"></h1>' +
            '<div class="title-bar"></div>' +
            '<p class="header-sub" data-i18n="hdr.sub"></p>' +
          '</div>' +
          '<div class="controls">' +
            '<div class="seg" id="langSeg"><button data-lang="en">EN</button><button data-lang="fr">FR</button></div>' +
            '<div class="seg" id="themeSeg"><button data-theme="light">LIGHT</button><button data-theme="dark">DARK</button></div>' +
          '</div>' +
        '</header>' +
        '<nav class="tabs">' +
          '<button class="tab" data-tab="config"><span data-i18n="tab.config"></span></button>' +
          '<button class="tab" data-tab="golden"><span data-i18n="tab.golden"></span><span class="count" id="tabGoldenCount"></span></button>' +
          '<button class="tab" data-tab="suggest"><span data-i18n="tab.suggest"></span></button>' +
          '<button class="tab" data-tab="review"><span data-i18n="tab.review"></span></button>' +
        '</nav>' +
        '<div class="body">' +
          '<main class="content">' +
            configPanelHtml() +
            '<section class="panel" data-panel="golden"><div id="goldenContent"></div></section>' +
            '<section class="panel" data-panel="suggest"><div id="suggestContent"></div></section>' +
            '<section class="panel" data-panel="review"><div id="reviewContent"></div></section>' +
          '</main>' +
          asideHtml() +
        '</div>' +
      '</div>' +
      modalHtml() +
      '<div class="toast" id="toast">' + I.check + '<span id="toastMsg"></span></div>';
  }

  function configPanelHtml() {
    return '' +
      '<section class="panel" data-panel="config">' +
        '<div class="sec-head">' +
          '<p class="sec-eyebrow" data-i18n="cfg.eyebrow"></p>' +
          '<h2 class="sec-title" data-i18n="cfg.title"></h2>' +
          '<p class="sec-note" data-i18n="cfg.note"></p>' +
        '</div>' +
        '<p class="glabel" data-i18n="ag.label"></p>' +
        '<p class="ghelp" data-i18n="ag.help"></p>' +
        '<div id="agentsList"></div>' +
        '<div style="margin-top:14px"><button class="btn btn-ghost" id="addAgent"><span data-i18n="ag.add"></span></button></div>' +
        '<div class="config-cols">' +
          '<div class="card"><div class="card-pad">' +
            '<p class="glabel" data-i18n="rm.title"></p>' +
            '<p class="ghelp" data-i18n="rm.help"></p>' +
            '<div class="chk-stack" id="modesGroup"></div>' +
          '</div></div>' +
          '<div class="card"><div class="card-pad">' +
            '<p class="glabel" data-i18n="qt.title"></p>' +
            '<p class="ghelp" id="qtHelp"></p>' +
            '<div class="chk-wrap" id="catsGroup"></div>' +
            '<div class="subgroup"><label class="field"><span class="field-label" data-i18n="qt.langfilter"></span>' +
              '<select class="input" id="langFilter">' +
                '<option value="all" data-i18n="opt.all"></option>' +
                '<option value="en" data-i18n="opt.en"></option>' +
                '<option value="fr" data-i18n="opt.fr"></option>' +
              '</select></label></div>' +
          '</div></div>' +
          '<div class="card"><div class="card-pad">' +
            '<p class="glabel" data-i18n="rp.title"></p>' +
            '<label class="field"><span class="field-label" data-i18n="rp.conc"></span>' +
              '<input class="input num" id="concurrency" type="number" min="1" max="8" value="1"></label>' +
            '<p class="ghelp" style="margin-top:10px" data-i18n="rp.conc.help"></p>' +
            '<div class="subgroup"><label class="field"><span class="field-label" data-i18n="rp.lang"></span>' +
              '<select class="input" id="benchLang">' +
                '<option value="en" data-i18n="opt.en"></option>' +
                '<option value="fr" data-i18n="opt.fr"></option>' +
              '</select></label>' +
              '<p class="ghelp" style="margin-top:10px" data-i18n="rp.lang.help"></p></div>' +
          '</div></div>' +
        '</div>' +
        '<div id="saveErr"></div>' +
        '<div class="save-bar">' +
          '<button class="btn btn-primary" id="saveBtn"><span id="icSave"></span><span id="saveBtnTxt" data-i18n="save.btn"></span></button>' +
          '<span class="dirty-dot"></span>' +
          '<span class="hint" data-i18n="save.hint"></span>' +
        '</div>' +
      '</section>';
  }

  function asideHtml() {
    return '' +
      '<aside class="aside">' +
        '<div class="aside-block">' +
          '<p class="aside-eyebrow" data-i18n="run.eyebrow"></p>' +
          '<h3 class="aside-h"><span id="icRun" style="display:inline-flex;vertical-align:-3px;margin-right:8px;color:var(--orange)"></span><span data-i18n="run.title"></span></h3>' +
          '<p class="aside-note" data-i18n="run.note"></p>' +
          '<div style="margin-top:18px"><button class="btn btn-primary btn-block" id="launchBtn"><span id="launchBtnTxt" data-i18n="run.btn"></span></button></div>' +
          '<div class="progress" id="progress"><i id="progressBar"></i></div>' +
          '<div class="progress-meta" id="progressMeta"></div>' +
          '<div id="runMsg"></div>' +
          '<div class="lastrun"><span data-i18n="run.last"></span>: <b id="lastRunVal"></b></div>' +
          '<p class="aside-note" data-i18n="run.save1"></p>' +
          '<p class="aside-note" data-i18n="run.save2"></p>' +
        '</div>' +
        '<div class="aside-block">' +
          '<p class="aside-eyebrow" data-i18n="pr.eyebrow"></p>' +
          '<h3 class="aside-h" data-i18n="pr.title"></h3>' +
          '<dl class="kv">' +
            '<div class="kv-row"><dt data-i18n="pr.golden"></dt><dd id="prGolden"></dd></div>' +
            '<div class="kv-row"><dt data-i18n="pr.judge"></dt><dd id="prJudge"></dd></div>' +
            '<div class="kv-row"><dt data-i18n="pr.suggest"></dt><dd id="prSuggest"></dd></div>' +
          '</dl>' +
        '</div>' +
      '</aside>';
  }

  function modalHtml() {
    return '' +
      '<div class="overlay" id="overlay"><div class="modal" role="dialog" aria-modal="true">' +
        '<div class="modal-head"><h3 class="modal-title" id="mdTitle"></h3>' +
          '<button class="modal-x" id="mdClose" aria-label="Close">' + I.x + '</button></div>' +
        '<div class="modal-err" id="mdErr"></div>' +
        '<div class="modal-body">' +
          '<label class="field full"><span class="field-label" data-i18n="md.q"></span><textarea class="input" id="mq"></textarea></label>' +
          '<label class="field full"><span class="field-label" data-i18n="md.a"></span><textarea class="input" id="ma"></textarea></label>' +
          '<label class="field"><span class="field-label" data-i18n="md.anchor"></span><input class="input mono" id="manchor"></label>' +
          '<label class="field"><span class="field-label" data-i18n="md.anchorType"></span><select class="input" id="mtype"></select></label>' +
          '<p class="field-help" data-i18n="md.valueHelp" style="grid-column:1 / -1;margin:0"></p>' +
          '<label class="field"><span class="field-label" data-i18n="md.cat"></span><input class="input" id="mcat" list="catList" autocomplete="off"><datalist id="catList"></datalist></label>' +
          '<label class="field"><span class="field-label" data-i18n="md.lang"></span><select class="input" id="mlang"><option value="en">en</option><option value="fr">fr</option></select></label>' +
          '<div class="field full"><button type="button" class="chk on" id="mActive" data-on="1">' +
            '<span class="box">' + I.check + '</span><span class="chk-txt"><b data-i18n="md.active"></b></span></button></div>' +
        '</div>' +
        '<div class="modal-foot"><button class="btn btn-ghost" id="mdCancel" data-i18n="md.cancel"></button>' +
          '<button class="btn btn-primary" id="mdSave" data-i18n="md.save"></button></div>' +
      '</div></div>';
  }

  /* ============================ i18n apply ============================ */

  function applyI18n() {
    qsa("[data-i18n]").forEach(function (e) { e.textContent = t(e.getAttribute("data-i18n")); });
  }

  /* ============================ render ============================ */

  function render() {
    applyTheme();
    applyLang();

    if (S.loadError && !S.loaded) {
      built = false;
      var root = byId("bench-app");
      if (root) {
        root.classList.remove("dirty");
        root.innerHTML = '' +
          '<div class="main"><div class="content">' +
          '<div class="note note-error" role="alert">' + esc(t("save.loadError")) + '</div>' +
          '<div class="actions-row"><button type="button" class="btn" id="retryConfig">' + esc(t("common.retry")) + '</button></div>' +
          '</div></div>';
        var rc = byId("retryConfig");
        if (rc) { rc.addEventListener("click", function () { loadConfig(); }); }
      }
      return;
    }

    ensureShell();
    applyI18n();
    syncSeg("langSeg", "data-lang", ui.lang);
    syncSeg("themeSeg", "data-theme", ui.theme);
    setTabUI(S.tab);

    renderAgents();
    renderModes();
    renderCats();
    byId("langFilter").value = S.filterLanguage;
    byId("benchLang").value = S.benchLang;
    byId("concurrency").value = S.concurrency;
    setText("qtHelp", t("qt.help", { n: fmtNum(S.questionCount) }));
    setDirtyUI();
    renderSaveError();

    renderAside();
    setText("tabGoldenCount", S.golden.loaded ? String(S.golden.list.length) : String(S.questionCount || 0));

    renderGolden();
    renderSuggestions();
    renderReview();

    setStatus(S.running ? "running" : (S.runDone ? "done" : "idle"));
    setHTML("icSave", I.save);
    setHTML("icRun", I.rocket);
  }

  function syncSeg(segId, attr, value) {
    qsa("#" + segId + " button").forEach(function (b) {
      b.classList.toggle("on", b.getAttribute(attr) === value);
    });
  }

  function setTabUI(tab) {
    qsa(".tab").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-tab") === tab); });
    qsa(".panel").forEach(function (p) { p.classList.toggle("on", p.getAttribute("data-panel") === tab); });
  }

  function setDirtyUI() {
    var root = byId("bench-app");
    if (root) { root.classList.toggle("dirty", !!S.dirty); }
  }

  function renderSaveError() {
    var box = byId("saveErr");
    if (!box) { return; }
    if (!S.saveError) { box.innerHTML = ""; return; }
    if (S.saveError.messages) {
      box.innerHTML = '<div class="note note-error" role="alert"><strong>' + esc(t("save.invalidTitle")) + '</strong><ul>' +
        S.saveError.messages.map(function (m) { return '<li>' + esc(m) + '</li>'; }).join("") + '</ul></div>';
    } else {
      box.innerHTML = '<div class="note note-error" role="alert">' + esc(S.saveError.text) + '</div>';
    }
  }

  /* --- agents --- */

  function renderAgents() {
    var box = byId("agentsList");
    if (!box) { return; }
    box.innerHTML = "";
    if (!S.agents.length) {
      box.innerHTML = '<div class="agent-empty">' + esc(t("ag.empty")) + '</div>';
      return;
    }
    S.agents.forEach(function (a, i) {
      var card = document.createElement("div");
      card.className = "agent";
      card.innerHTML = '' +
        '<div class="agent-grid">' +
          '<label class="field"><span class="field-label">' + esc(t("ag.f.label")) + '</span>' +
            '<input class="input" data-f="agent_label" value="' + esc(a.agent_label) + '"></label>' +
          '<label class="field"><span class="field-label">' + esc(t("ag.f.key")) + '</span>' +
            '<input class="input mono" data-f="project_key" value="' + esc(a.project_key) + '"></label>' +
          '<label class="field"><span class="field-label">' + esc(t("ag.f.id")) + '</span>' +
            '<input class="input mono" data-f="agent_id" value="' + esc(a.agent_id) + '"></label>' +
        '</div>' +
        '<div class="agent-foot">' +
          '<button type="button" class="chk ' + (a.modes ? "on" : "") + '" data-modes>' +
            '<span class="box">' + I.check + '</span><span class="chk-txt">' + esc(t("ag.modes")) + '</span></button>' +
          '<button type="button" class="btn btn-danger btn-sm" data-remove>' + esc(t("ag.remove")) + '</button>' +
        '</div>';
      qsa("input", card).forEach(function (inp) {
        inp.addEventListener("input", function () { a[inp.getAttribute("data-f")] = inp.value; markDirty(); });
      });
      card.querySelector("[data-modes]").addEventListener("click", function () {
        a.modes = !a.modes; this.classList.toggle("on", a.modes); markDirty();
      });
      card.querySelector("[data-remove]").addEventListener("click", function () {
        S.agents.splice(i, 1); markDirty(); renderAgents(); toast(t("ag.removed"));
      });
      box.appendChild(card);
    });
  }

  function chkBtn(label, on) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "chk" + (on ? " on" : "");
    b.innerHTML = '<span class="box">' + I.check + '</span><span class="chk-txt"><b>' + esc(label) + '</b></span>';
    return b;
  }

  function renderModes() {
    var box = byId("modesGroup");
    if (!box) { return; }
    box.innerHTML = "";
    S.modeOptions.forEach(function (m) {
      var on = S.modes.indexOf(m) !== -1;
      var b = chkBtn(m, on);
      b.addEventListener("click", function () {
        var idx = S.modes.indexOf(m);
        if (idx === -1) { S.modes.push(m); } else { S.modes.splice(idx, 1); }
        b.classList.toggle("on", S.modes.indexOf(m) !== -1);
        markDirty();
      });
      box.appendChild(b);
    });
  }

  function renderCats() {
    var box = byId("catsGroup");
    if (!box) { return; }
    box.innerHTML = "";
    if (!S.categories.length) {
      box.innerHTML = '<p class="field-help" style="margin:0">' + esc(t("qt.nocats")) + '</p>';
      return;
    }
    S.categories.forEach(function (c) {
      var on = S.filterCategories.indexOf(c) !== -1;
      var b = chkBtn(c, on);
      b.addEventListener("click", function () {
        var idx = S.filterCategories.indexOf(c);
        if (idx === -1) { S.filterCategories.push(c); } else { S.filterCategories.splice(idx, 1); }
        b.classList.toggle("on", S.filterCategories.indexOf(c) !== -1);
        markDirty();
      });
      box.appendChild(b);
    });
  }

  /* --- aside (run + preserved) --- */

  function renderAside() {
    var btn = byId("launchBtnTxt");
    if (btn) { btn.textContent = S.running ? t("run.btn.running") : t("run.btn"); }
    var lbtn = byId("launchBtn");
    if (lbtn) { lbtn.disabled = !!S.running; }

    var pr = byId("progress");
    var bar = byId("progressBar");
    var meta = byId("progressMeta");
    if (pr && bar && meta) {
      pr.classList.toggle("on", !!S.running);
      bar.style.width = (S.running ? S.progress : 0) + "%";
      meta.textContent = S.running ? (Math.round(S.progress) + "%") : "";
    }
    var rm = byId("runMsg");
    if (rm) {
      if (S.runMsg) {
        rm.innerHTML = '<div class="run-msg ' + (S.runMsg.kind === "ok" ? "ok" : "err") + '">' + esc(S.runMsg.text) + '</div>';
      } else if (S.dirty) {
        rm.innerHTML = '<div class="run-msg err">' + esc(t("run.dirty")) + '</div>';
      } else {
        rm.innerHTML = "";
      }
    }
    var last = (S.runs && S.runs.length) ? (S.runs[0].run_timestamp || S.runs[0].run_id) : "";
    setText("lastRunVal", last || t("run.never"));

    setText("prGolden", S.preserved.golden || t("pr.na"));
    setText("prJudge", S.preserved.judge || t("pr.na"));
    var sg = byId("prSuggest");
    if (sg) {
      var src = S.preserved.suggestions || {};
      var label = src.table || src.connection || "";
      if (label) { sg.textContent = label; sg.className = ""; }
      else { sg.innerHTML = '<span class="tag-na">' + esc(t("pr.na")) + '</span>'; }
    }
  }

  /* --- golden table --- */

  function renderGolden() {
    var box = byId("goldenContent");
    if (!box) { return; }
    var inner;
    if (S.golden.loadError) {
      inner = '<div class="note note-error" role="alert">' + esc(t("gs.loadError")) + '</div>' +
        '<div class="actions-row"><button type="button" class="btn" data-g="retry">' + esc(t("common.retry")) + '</button></div>';
    } else if (!S.golden.loaded) {
      inner = '<p class="loading">' + esc(t("common.loading")) + '</p>';
    } else {
      inner = goldenTableHtml();
    }
    box.innerHTML = '' +
      '<div class="sec-head">' +
        '<p class="sec-eyebrow">' + esc(t("gs.eyebrow")) + '</p>' +
        '<h2 class="sec-title">' + esc(t("gs.title")) + '</h2>' +
        '<div class="title-bar"></div>' +
        '<p class="sec-note">' + esc(t("gs.note")) + '</p>' +
      '</div>' + inner;
    wireGolden();
  }

  function goldenTableHtml() {
    var list = S.golden.list;
    var active = list.filter(function (g) { return g.active; }).length;
    var head = '<div class="table-head">' +
      '<span class="count-line">' + t("gs.count", { n: "<b>" + fmtNum(list.length) + "</b>", a: "<b>" + fmtNum(active) + "</b>" }) + '</span>' +
      '<button class="btn btn-primary btn-sm" data-g="add"><span class="ic-plus"></span>' + esc(t("gs.add")) + '</button>' +
      '</div>';
    if (!list.length) {
      return head + '<div class="note note-info" role="status">' + esc(t("gs.empty")) + '</div>';
    }
    var rows = list.map(qRowHtml).join("");
    return head +
      '<table class="gtable"><colgroup>' +
        '<col class="c-status"><col class="c-q"><col class="c-a"><col class="c-anchor"><col class="c-cat"><col class="c-lang"><col class="c-act">' +
      '</colgroup><thead><tr>' +
        '<th>' + esc(t("th.status")) + '</th><th>' + esc(t("th.q")) + '</th><th>' + esc(t("th.a")) + '</th>' +
        '<th>' + esc(t("th.anchor")) + '</th><th>' + esc(t("th.cat")) + '</th><th>' + esc(t("th.lang")) + '</th><th>' + esc(t("th.act")) + '</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table>';
  }

  function qRowHtml(g) {
    var confirming = S.golden.confirmDelete === g.question_id;
    var act;
    if (confirming) {
      act = '<div class="q-confirm"><span class="q-confirm-msg">' + esc(t("q.deleteConfirm")) + '</span>' +
        '<span class="q-confirm-btns">' +
          '<button class="btn btn-sm btn-danger" data-g="delete-go" data-id="' + esc(g.question_id) + '">' + esc(t("q.deleteGo")) + '</button>' +
          '<button class="btn btn-sm" data-g="delete-cancel">' + esc(t("q.deleteCancel")) + '</button>' +
        '</span></div>';
    } else {
      act = '<div class="row-act">' +
        '<button class="icon-btn" data-g="edit" data-id="' + esc(g.question_id) + '" title="' + esc(t("q.edit")) + '" aria-label="' + esc(t("q.edit")) + '">' + I.edit + '</button>' +
        '<button class="icon-btn danger" data-g="delete" data-id="' + esc(g.question_id) + '" title="' + esc(t("q.delete")) + '" aria-label="' + esc(t("q.delete")) + '">' + I.trash + '</button>' +
        '</div>';
    }
    return '<tr class="' + (g.active ? "" : "off") + '">' +
      '<td data-l="' + esc(t("th.status")) + '"><div class="tog ' + (g.active ? "on" : "") + '" role="switch" aria-checked="' + (g.active ? "true" : "false") + '" data-g="toggle" data-id="' + esc(g.question_id) + '"></div></td>' +
      '<td data-l="' + esc(t("th.q")) + '"><div class="cell-q clamp">' + esc(g.question) + '</div></td>' +
      '<td data-l="' + esc(t("th.a")) + '"><div class="cell-a clamp">' + esc(g.reference_answer) + '</div></td>' +
      '<td data-l="' + esc(t("th.anchor")) + '">' + qAnchorHtml(g) + '</td>' +
      '<td data-l="' + esc(t("th.cat")) + '">' + (g.category ? '<span class="cat-tag">' + esc(g.category) + '</span>' : '<span class="anchor-none">' + esc(t("common.dash")) + '</span>') + '</td>' +
      '<td data-l="' + esc(t("th.lang")) + '"><span class="lang-tag">' + esc(g.language) + '</span></td>' +
      '<td data-l="' + esc(t("th.act")) + '">' + act + '</td>' +
    '</tr>';
  }

  function qAnchorHtml(g) {
    var v = (g.expected_value == null) ? "" : String(g.expected_value).trim();
    if (!v) { return '<span class="anchor-none">' + esc(t("common.dash")) + '</span>'; }
    var html = '<span class="anchor-val">' + esc(truncate(v, 60)) + '</span>';
    var ty = (g.expected_value_type == null) ? "" : String(g.expected_value_type).trim();
    if (ty) { html += '<span class="anchor-type">' + esc(ty) + '</span>'; }
    return html;
  }

  function wireGolden() {
    var box = byId("goldenContent");
    if (!box) { return; }
    qsa(".ic-plus", box).forEach(function (e) { e.innerHTML = I.plus; });
    qsa("[data-g]", box).forEach(function (el) {
      var kind = el.getAttribute("data-g");
      var id = el.getAttribute("data-id");
      el.addEventListener("click", function () {
        if (kind === "add") { openModal(null); }
        else if (kind === "edit") { openModal(findGolden(id)); }
        else if (kind === "toggle") { toggleActive(id); }
        else if (kind === "delete") { S.golden.confirmDelete = id; renderGolden(); }
        else if (kind === "delete-cancel") { S.golden.confirmDelete = null; renderGolden(); }
        else if (kind === "delete-go") { deleteQuestion(id); }
        else if (kind === "retry") { loadGolden(); }
      });
    });
  }

  function findGolden(id) {
    var found = null;
    S.golden.list.forEach(function (g) { if (g.question_id === id) { found = g; } });
    return found;
  }

  /* --- suggestions --- */

  function renderSuggestions() {
    var box = byId("suggestContent");
    if (!box) { return; }
    var inner;
    if (S.suggestions.loadError) {
      inner = '<div class="note note-error" role="alert">' + esc(t("sg.loadError")) + '</div>' +
        '<div class="actions-row"><button type="button" class="btn" data-s="retry">' + esc(t("common.retry")) + '</button></div>';
    } else if (!S.suggestions.loaded) {
      inner = '<p class="loading">' + esc(t("common.loading")) + '</p>';
    } else if (!S.suggestions.configured) {
      inner = '<div class="empty"><div class="ei"><span class="ic-bulb"></span></div>' +
        '<h4>' + esc(t("sg.empty.h")) + '</h4><p>' + esc(t("sg.empty.p")) + '</p></div>';
    } else if (!S.suggestions.list.length) {
      inner = '<div class="empty"><div class="ei"><span class="ic-bulb"></span></div><h4>' + esc(t("sg.none")) + '</h4></div>';
    } else {
      inner = suggestionsTableHtml();
    }
    box.innerHTML = '' +
      '<div class="sec-head">' +
        '<p class="sec-eyebrow">' + esc(t("sg.eyebrow")) + '</p>' +
        '<h2 class="sec-title">' + esc(t("sg.title")) + '</h2>' +
        '<div class="title-bar"></div>' +
        '<p class="sec-note">' + esc(t("sg.note")) + '</p>' +
      '</div>' + inner;
    wireSuggestions();
  }

  function suggestionsTableHtml() {
    var sel = S.suggestions.selected || {};
    var list = S.suggestions.list;
    var hasSel = list.some(function (s) { return !!sel[s.suggestion_id]; });
    var allSel = list.length > 0 && list.every(function (s) { return !!sel[s.suggestion_id]; });
    var head = '<thead><tr>' +
      '<th><input type="checkbox" id="sugAll" aria-label="' + esc(t("sg.selectAll")) + '"' + (allSel ? " checked" : "") + '></th>' +
      '<th>' + esc(t("sg.col.q")) + '</th><th>' + esc(t("sg.col.a")) + '</th><th>' + esc(t("sg.col.anchor")) + '</th>' +
      '<th>' + esc(t("sg.col.review")) + '</th><th>' + esc(t("sg.col.cat")) + '</th><th>' + esc(t("sg.col.date")) + '</th>' +
    '</tr></thead>';
    var body = list.map(function (s) {
      var srcKey = (s.source === "chat") ? "sg.source.chat" : "sg.source.manual";
      var checked = sel[s.suggestion_id] ? " checked" : "";
      return '<tr>' +
        '<td data-l=""><input type="checkbox" data-sug="' + esc(s.suggestion_id) + '"' + checked + ' aria-label="' + esc(t("sg.selectOne")) + '"></td>' +
        '<td data-l="' + esc(t("sg.col.q")) + '"><div class="cell-q clamp">' + esc(s.question) + '</div></td>' +
        '<td data-l="' + esc(t("sg.col.a")) + '"><div class="cell-a clamp">' + esc(truncate(s.reference_answer, 160)) + '</div></td>' +
        '<td data-l="' + esc(t("sg.col.anchor")) + '">' + qAnchorHtml({ expected_value: s.expected_value, expected_value_type: s.expected_value_type }) + '</td>' +
        '<td data-l="' + esc(t("sg.col.review")) + '">' + reviewCellHtml(s) + '<span class="src">' + esc(t(srcKey)) + '</span></td>' +
        '<td data-l="' + esc(t("sg.col.cat")) + '">' + (s.category ? '<span class="cat-tag">' + esc(s.category) + '</span>' : '<span class="anchor-none">' + esc(t("common.dash")) + '</span>') + '</td>' +
        '<td data-l="' + esc(t("sg.col.date")) + '"><span class="cell-date">' + esc(s.created_at) + '</span></td>' +
      '</tr>';
    }).join("");
    var actions;
    if (S.suggestions.confirm) {
      actions = '<div class="confirm-row">' +
        '<p class="confirm-msg">' + esc(t("sg.confirm", { n: fmtNum(S.suggestions.confirmCount) })) + '</p>' +
        '<div class="actions-row" style="margin-top:0">' +
          '<button class="btn btn-primary" data-s="promote-go">' + esc(t("sg.go")) + '</button>' +
          '<button class="btn" data-s="promote-cancel">' + esc(t("sg.cancel")) + '</button>' +
        '</div></div>';
    } else {
      actions = '<div class="actions-row">' +
        '<button class="btn btn-primary" id="promoteBtn" data-s="promote"' + (hasSel ? "" : " disabled") + '>' + esc(t("sg.promote")) + '</button>' +
      '</div>';
    }
    return '<table class="gtable"><colgroup>' +
      '<col class="c-check"><col class="c-q"><col class="c-a"><col class="c-anchor"><col class="c-review"><col class="c-cat"><col class="c-date">' +
      '</colgroup>' + head + '<tbody>' + body + '</tbody></table>' + actions;
  }

  function reviewCellHtml(s) {
    var ic = s.answer_is_correct;
    var key, cls;
    if (ic === true) { key = "sg.review.correct"; cls = "rev-correct"; }
    else if (ic === false) { key = "sg.review.incorrect"; cls = "rev-incorrect"; }
    else { key = "sg.review.unverified"; cls = "rev-unverified"; }
    var html = '<span class="rev ' + cls + '">' + esc(t(key)) + '</span>';
    var note = (s.missing_explanation == null) ? "" : String(s.missing_explanation).trim();
    if (note) { html += '<span class="rev-note">' + esc(truncate(note, 160)) + '</span>'; }
    return html;
  }

  function wireSuggestions() {
    var box = byId("suggestContent");
    if (!box) { return; }
    qsa(".ic-bulb", box).forEach(function (e) { e.innerHTML = I.bulb; });
    qsa("[data-sug]", box).forEach(function (cb) {
      cb.addEventListener("change", function () {
        S.suggestions.selected[cb.getAttribute("data-sug")] = cb.checked;
        var pb = byId("promoteBtn");
        if (pb) { pb.disabled = !S.suggestions.list.some(function (s) { return !!S.suggestions.selected[s.suggestion_id]; }); }
        syncSelectAll();
      });
    });
    var all = byId("sugAll");
    if (all) {
      all.addEventListener("change", function () {
        S.suggestions.list.forEach(function (s) { S.suggestions.selected[s.suggestion_id] = all.checked; });
        renderSuggestions();
      });
      syncSelectAll();
    }
    qsa("[data-s]", box).forEach(function (el) {
      var kind = el.getAttribute("data-s");
      el.addEventListener("click", function () {
        if (kind === "promote") { startPromote(); }
        else if (kind === "promote-go") { doPromote(); }
        else if (kind === "promote-cancel") { S.suggestions.confirm = false; renderSuggestions(); }
        else if (kind === "retry") { loadSuggestions(); }
      });
    });
  }

  function syncSelectAll() {
    var all = byId("sugAll");
    if (!all) { return; }
    var boxes = qsa("[data-sug]");
    var total = boxes.length;
    var checked = boxes.filter(function (c) { return c.checked; }).length;
    all.checked = total > 0 && checked === total;
    all.indeterminate = checked > 0 && checked < total;
  }

  /* ============================ modal ============================ */

  function openModal(g) {
    S.editor.open = true;
    S.editor.isNew = !g;
    S.editor.qid = g ? g.question_id : "";
    S.editor.error = null;
    setText("mdTitle", g ? t("md.edit") : t("md.add"));
    setHTML("mdErr", "");
    byId("mq").value = g ? (g.question || "") : "";
    byId("ma").value = g ? (g.reference_answer || "") : "";
    byId("manchor").value = g ? (g.expected_value || "") : "";
    // anchor type select (rebuilt to apply the live language + selected value)
    var sel = byId("mtype");
    var cur = g ? (g.expected_value_type || "") : "";
    sel.innerHTML = '<option value="">' + esc(t("vt.none")) + '</option>' +
      VALUE_TYPES.map(function (vt) {
        return '<option value="' + vt + '"' + (cur === vt ? " selected" : "") + '>' + esc(t("vt." + vt)) + '</option>';
      }).join("");
    sel.value = cur;
    // category datalist (live categories)
    byId("catList").innerHTML = S.categories.map(function (c) { return '<option value="' + esc(c) + '"></option>'; }).join("");
    byId("mcat").value = g ? (g.category || "") : "";
    byId("mlang").value = (g && g.language === "en") ? "en" : (g ? "fr" : (ui.lang === "en" ? "en" : "fr"));
    var at = byId("mActive");
    var on = g ? (g.active !== false) : true;
    at.classList.toggle("on", on);
    at.setAttribute("data-on", on ? "1" : "0");
    byId("overlay").classList.add("on");
    setTimeout(function () { byId("mq").focus(); }, 50);
  }

  function closeModal() {
    S.editor.open = false;
    byId("overlay").classList.remove("on");
  }

  function submitModal() {
    var question = byId("mq").value.trim();
    var reference = byId("ma").value.trim();
    var payload = {
      question: question,
      reference_answer: reference,
      expected_value: byId("manchor").value.trim(),
      expected_value_type: byId("mtype").value,
      category: byId("mcat").value.trim(),
      language: (byId("mlang").value === "en") ? "en" : "fr",
      active: byId("mActive").getAttribute("data-on") === "1",
      notes: editorNotes()
    };
    if (!S.editor.isNew && S.editor.qid) { payload.question_id = S.editor.qid; }
    setHTML("mdErr", "");
    var btn = byId("mdSave");
    if (btn) { btn.disabled = true; }
    callApi("POST", "golden/save", payload).then(function (res) {
      if (btn) { btn.disabled = false; }
      var d = res.data || {};
      if (d.status === "ok") {
        var wasNew = S.editor.isNew;
        closeModal();
        toast(wasNew ? t("q.added") : t("q.saved"));
        loadGolden();
        refreshConfigMeta();
      } else {
        var msgs = d.messages || [t("q.saveError")];
        setHTML("mdErr", '<div class="note note-error" role="alert"><strong>' + esc(t("save.invalidTitle")) + '</strong><ul>' +
          msgs.map(function (m) { return '<li>' + esc(m) + '</li>'; }).join("") + '</ul></div>');
      }
    }, function () {
      if (btn) { btn.disabled = false; }
      setHTML("mdErr", '<div class="note note-error" role="alert">' + esc(t("q.saveError")) + '</div>');
    });
  }

  // Preserve the edited row's notes (the modal has no notes field, but the golden carries one).
  function editorNotes() {
    if (S.editor.isNew || !S.editor.qid) { return ""; }
    var g = findGolden(S.editor.qid);
    return (g && g.notes) ? g.notes : "";
  }

  function toggleActive(id) {
    var g = findGolden(id);
    if (!g) { return; }
    var payload = {
      question_id: g.question_id, question: g.question, reference_answer: g.reference_answer,
      expected_value: g.expected_value || "", expected_value_type: g.expected_value_type || "",
      category: g.category || "", language: (g.language === "en") ? "en" : "fr",
      active: !g.active, notes: g.notes || ""
    };
    callApi("POST", "golden/save", payload).then(function (res) {
      var d = res.data || {};
      if (d.status === "ok") {
        g.active = !g.active;
        renderGolden();
        refreshConfigMeta();
        toast(t("q.toggled"));
      } else {
        toast(t("q.saveError"));
      }
    }, function () { toast(t("q.saveError")); });
  }

  function deleteQuestion(id) {
    callApi("POST", "golden/delete", { question_id: id }).then(function (res) {
      var d = res.data || {};
      if (d.status === "ok") {
        S.golden.confirmDelete = null;
        S.golden.list = S.golden.list.filter(function (g) { return g.question_id !== id; });
        renderGolden();
        setText("tabGoldenCount", String(S.golden.list.length));
        refreshConfigMeta();
        toast(t("q.removed"));
      } else {
        toast(t("q.deleteError"));
      }
    }, function () { toast(t("q.deleteError")); });
  }

  /* ============================ toast / status / dirty ============================ */

  var toastT;
  function toast(msg) {
    var el = byId("toast");
    if (!el) { return; }
    setText("toastMsg", msg);
    el.classList.add("on");
    clearTimeout(toastT);
    toastT = setTimeout(function () { el.classList.remove("on"); }, 2200);
  }

  function setStatus(kind) {
    var p = byId("runPill");
    if (p) { p.className = "run-pill " + kind; }
    setText("runStatusTxt", t("status." + kind));
  }

  function markDirty() {
    S.dirty = true;
    S.saveError = null;
    setDirtyUI();
    renderSaveError();
    renderAside();
  }
  function clearDirty() {
    S.dirty = false;
    setDirtyUI();
    renderAside();
  }

  /* ============================ actions: config ============================ */

  function loadConfig() {
    S.loadError = false;
    render();
    callApi("GET", "config").then(function (res) {
      var d = res.data || {};
      if (d.status !== "ok") { S.loadError = true; render(); return; }
      var cfg = d.config || {};
      S.agents = (cfg.agents || []).map(function (a) {
        return {
          agent_key: a.agent_key || genKey(),
          agent_label: a.agent_label || "",
          project_key: a.project_key || "",
          agent_id: a.agent_id || "",
          modes: !!a.modes
        };
      });
      S.modes = (cfg.modes || []).slice();
      S.benchLang = (cfg.language === "en") ? "en" : "fr";
      S.concurrency = clampInt(cfg.concurrency, 1, 8, 1);
      var qf = cfg.question_filter || {};
      S.filterCategories = (qf.categories || []).slice();
      S.filterCategoriesLoaded = (qf.categories || []).slice();
      S.filterQuestionIds = (qf.question_ids || []).slice();
      var langs = qf.languages || [];
      S.filterLanguage = (langs.length === 1 && (langs[0] === "en" || langs[0] === "fr")) ? langs[0] : "all";
      S.categories = (d.categories || []).slice();
      S.modeOptions = (d.mode_options && d.mode_options.length) ? d.mode_options.slice() : ["Smart", "Pro", "Claude"];
      S.questionCount = d.question_count || 0;
      S.runs = (d.runs || []).slice();
      S.preserved = { golden: cfg.golden_dataset || "", judge: cfg.judge_llm_id || "", suggestions: cfg.suggestions || {} };
      S.loaded = true;
      S.loadError = false;
      S.dirty = false;
      render();
    }, function () { S.loadError = true; render(); });
  }

  // Refresh ONLY the config META (categories / question_count / runs / preserved) after a golden
  // change, WITHOUT touching the form state or the dirty flag (so an unsaved edit is not lost and
  // Launch is not silently re-enabled against a stale saved config).
  function refreshConfigMeta() {
    callApi("GET", "config").then(function (res) {
      var d = res.data || {};
      if (d.status !== "ok") { return; }
      var cfg = d.config || {};
      S.categories = (d.categories || []).slice();
      S.questionCount = d.question_count || 0;
      S.runs = (d.runs || []).slice();
      S.preserved = { golden: cfg.golden_dataset || "", judge: cfg.judge_llm_id || "", suggestions: cfg.suggestions || {} };
      renderCats();
      setText("qtHelp", t("qt.help", { n: fmtNum(S.questionCount) }));
      renderAside();
    }, function () { /* meta refresh is best-effort */ });
  }

  function saveConfig() {
    if (S.saving) { return; }
    var cats = S.filterCategories.slice();
    // Keep a configured category that has no checkbox (drift vs the live category list).
    S.filterCategoriesLoaded.forEach(function (c) {
      if (S.categories.indexOf(c) === -1 && cats.indexOf(c) === -1) { cats.push(c); }
    });
    var qf = {};
    if (cats.length) { qf.categories = cats; }
    if (S.filterQuestionIds.length) { qf.question_ids = S.filterQuestionIds.slice(); }
    if (S.filterLanguage === "en" || S.filterLanguage === "fr") { qf.languages = [S.filterLanguage]; }
    var payload = {
      agents: S.agents.map(function (a) {
        return { agent_key: a.agent_key || genKey(), agent_label: a.agent_label, project_key: a.project_key, agent_id: a.agent_id, modes: !!a.modes };
      }),
      modes: S.modes.slice(),
      language: S.benchLang,
      concurrency: S.concurrency,
      question_filter: qf
    };
    S.saving = true;
    S.saveError = null;
    setText("saveBtnTxt", t("save.saving"));
    var btn = byId("saveBtn");
    if (btn) { btn.disabled = true; }
    callApi("POST", "config", payload).then(function (res) {
      S.saving = false;
      if (btn) { btn.disabled = false; }
      setText("saveBtnTxt", t("save.btn"));
      var d = res.data || {};
      if (d.status === "ok") {
        clearDirty();
        S.saveError = null;
        renderSaveError();
        var cfg = d.config || {};
        if (cfg.suggestions || cfg.golden_dataset || cfg.judge_llm_id) {
          S.preserved = { golden: cfg.golden_dataset || S.preserved.golden, judge: cfg.judge_llm_id || S.preserved.judge, suggestions: cfg.suggestions || S.preserved.suggestions };
          renderAside();
        }
        toast(t("cfg.saved"));
      } else if (res.status === 400 && d.messages) {
        S.saveError = { messages: d.messages };
        renderSaveError();
      } else {
        S.saveError = { text: t("save.error") };
        renderSaveError();
      }
    }, function () {
      S.saving = false;
      if (btn) { btn.disabled = false; }
      setText("saveBtnTxt", t("save.btn"));
      S.saveError = { text: t("save.error") };
      renderSaveError();
    });
  }

  /* ============================ actions: run ============================ */

  function launch() {
    if (S.running) { return; }
    S.running = true;
    S.runDone = false;
    S.progress = 6;
    S.runMsg = null;
    setStatus("running");
    renderAside();
    callApi("POST", "run").then(function (res) {
      var d = res.data || {};
      if (d.status === "ok" && d.launched) {
        S.runMsg = { kind: "ok", text: t("run.launched") };
        renderAside();
        toast(t("run.launched"));
        pollStatus();
      } else if (res.status === 409 || d.error === "already_running") {
        S.runMsg = { kind: "err", text: t("run.already") };
        renderAside();
        pollStatus();
      } else if (d.error === "launch_unsupported") {
        endRun({ kind: "err", text: t("run.unsupported") });
      } else {
        endRun({ kind: "err", text: t("run.error") });
      }
    }, function () { endRun({ kind: "err", text: t("run.error") }); });
  }

  var pollErrors = 0;
  function pollStatus() {
    if (!S.running) { return; }
    setTimeout(function () {
      callApi("GET", "run/status").then(function (res) {
        pollErrors = 0;
        var d = res.data || {};
        if (d.running) {
          S.progress = Math.min(92, S.progress + 11);
          renderAside();
          pollStatus();
        } else {
          endRun({ kind: "ok", text: t("run.finished") });
          loadConfigQuiet();
        }
      }, function () {
        pollErrors += 1;
        if (pollErrors >= 4) { endRun({ kind: "err", text: t("run.lostContact") }); }
        else { pollStatus(); }
      });
    }, 2500);
  }

  function endRun(msg) {
    S.running = false;
    S.runDone = true;
    S.progress = 0;
    S.runMsg = msg || null;
    setStatus("done");
    renderAside();
  }

  // Refresh runs / last-run after a run finishes, without disrupting the form.
  function loadConfigQuiet() {
    callApi("GET", "config").then(function (res) {
      var d = res.data || {};
      if (d.status !== "ok") { return; }
      S.runs = (d.runs || []).slice();
      renderAside();
    }, function () { /* best-effort */ });
  }

  /* ============================ actions: golden / suggestions ============================ */

  function loadGolden() {
    S.golden.loadError = false;
    if (!S.golden.loaded) { renderGolden(); }
    callApi("GET", "golden").then(function (res) {
      var d = res.data || {};
      if (d.status === "ok") {
        S.golden.list = (d.questions || []).slice();
        S.golden.loaded = true;
        S.golden.loadError = false;
      } else {
        S.golden.loadError = true;
      }
      setText("tabGoldenCount", String(S.golden.loaded ? S.golden.list.length : (S.questionCount || 0)));
      renderGolden();
    }, function () { S.golden.loadError = true; renderGolden(); });
  }

  function loadSuggestions() {
    S.suggestions.loadError = false;
    if (!S.suggestions.loaded) { renderSuggestions(); }
    callApi("GET", "suggestions").then(function (res) {
      var d = res.data || {};
      if (d.status === "ok") {
        S.suggestions.configured = !!d.configured;
        S.suggestions.list = (d.suggestions || []).slice();
        S.suggestions.selected = {};
        S.suggestions.confirm = false;
        S.suggestions.loaded = true;
        S.suggestions.loadError = false;
      } else {
        S.suggestions.loadError = true;
      }
      renderSuggestions();
    }, function () { S.suggestions.loadError = true; renderSuggestions(); });
  }

  function startPromote() {
    var ids = S.suggestions.list.filter(function (s) { return !!S.suggestions.selected[s.suggestion_id]; });
    if (!ids.length) { return; }
    S.suggestions.confirm = true;
    S.suggestions.confirmCount = ids.length;
    renderSuggestions();
  }

  function doPromote() {
    var ids = S.suggestions.list
      .filter(function (s) { return !!S.suggestions.selected[s.suggestion_id]; })
      .map(function (s) { return s.suggestion_id; });
    if (!ids.length) { S.suggestions.confirm = false; renderSuggestions(); return; }
    callApi("POST", "suggestions/promote", { suggestion_ids: ids }).then(function (res) {
      var d = res.data || {};
      S.suggestions.confirm = false;
      if (d.status === "ok") {
        var n = d.promoted || 0;
        toast(n > 0 ? t("sg.promoted", { n: fmtNum(n) }) : t("sg.promotedNone"));
        loadSuggestions();
        if (S.golden.loaded) { loadGolden(); }
        refreshConfigMeta();
      } else {
        toast(t("sg.promoteError"));
        renderSuggestions();
      }
    }, function () { S.suggestions.confirm = false; toast(t("sg.promoteError")); renderSuggestions(); });
  }

  /* ============================ review (human-in-the-loop) ============================ */

  // Stable identity of a scored row: a run tests the same question across agents and modes, so the
  // override target is (question_id, agent_key, mode). agent_key comes from the api/review row.
  function reviewRowKey(r) {
    return [r.question_id, r.agent_key || "", r.mode || ""].join("\u0001");
  }
  function findReviewRow(rk) {
    var found = null;
    S.review.rows.forEach(function (r) { if (reviewRowKey(r) === rk) { found = r; } });
    return found;
  }

  // objective_match arrives stringified from the backend (str(True) -> "True"), or as a bool/null.
  function objChip(r) {
    var v = r.objective_match;
    var s = (v === true) ? "true" : (v === false ? "false" : String(v == null ? "" : v).trim().toLowerCase());
    var key, cls;
    if (s === "true" || s === "hit" || s === "match" || s === "1" || s === "yes") { key = "rv.obj.hit"; cls = "obj-hit"; }
    else if (s === "false" || s === "miss" || s === "0" || s === "no") { key = "rv.obj.miss"; cls = "obj-miss"; }
    else { key = "rv.obj.na"; cls = "obj-na"; }
    return '<span class="rvw-obj ' + cls + '">' + esc(t(key)) + '</span>';
  }

  function renderReview() {
    var box = byId("reviewContent");
    if (!box) { return; }
    var inner;
    if (S.review.loadError) {
      inner = '<div class="note note-error" role="alert">' + esc(t("rv.loadError")) + '</div>' +
        '<div class="actions-row"><button type="button" class="btn" data-rv="retry">' + esc(t("common.retry")) + '</button></div>';
    } else if (!S.review.loaded) {
      inner = '<p class="loading">' + esc(t("common.loading")) + '</p>';
    } else if (!S.review.runs.length) {
      inner = '<div class="empty"><div class="ei"><span class="ic-info"></span></div>' +
        '<h4>' + esc(t("rv.noRuns.h")) + '</h4><p>' + esc(t("rv.noRuns.p")) + '</p></div>';
    } else {
      inner = reviewBodyHtml();
    }
    box.innerHTML = '' +
      '<div class="sec-head">' +
        '<p class="sec-eyebrow">' + esc(t("rv.eyebrow")) + '</p>' +
        '<h2 class="sec-title">' + esc(t("rv.title")) + '</h2>' +
        '<div class="title-bar"></div>' +
        '<p class="sec-note">' + esc(t("rv.note")) + '</p>' +
      '</div>' + inner;
    wireReview();
  }

  function reviewBodyHtml() {
    var runOpts = S.review.runs.map(function (r) {
      var label = r.run_timestamp || r.run_id;
      var seld = (r.run_id === S.review.runId) ? " selected" : "";
      return '<option value="' + esc(r.run_id) + '"' + seld + '>' + esc(label) + '</option>';
    }).join("");
    var bar = '' +
      '<div class="rvw-bar">' +
        '<label class="field rvw-runsel"><span class="field-label">' + esc(t("rv.run")) + '</span>' +
          '<select class="input" id="rvwRun">' + runOpts + '</select></label>' +
        '<button type="button" class="chk' + (S.review.onlyNeedsReview ? " on" : "") + '" id="rvwOnly">' +
          '<span class="box">' + I.check + '</span><span class="chk-txt"><b>' + esc(t("rv.onlyNeeds")) + '</b></span></button>' +
      '</div>';
    var caption = '<div class="note note-info" role="note">' + esc(t("rv.caption")) + '</div>';

    // Defensive: if no row carries agent_key, the override POST cannot match server-side.
    var warn = "";
    if (S.review.rows.length && !S.review.rows.some(function (r) { return !!r.agent_key; })) {
      warn = '<div class="note note-error" role="alert">' + esc(t("rv.agentMissing")) + '</div>';
    }

    var list;
    if (!S.review.rows.length) {
      var emptyKey = S.review.onlyNeedsReview ? "rv.noNeeds" : "rv.noRows";
      list = '<div class="note note-info" role="status">' + esc(t(emptyKey)) + '</div>';
    } else {
      var countLine = '<div class="rvw-count">' + esc(t("rv.count", { n: fmtNum(S.review.count) })) + '</div>';
      list = countLine + '<div class="rvw-list">' + S.review.rows.map(reviewCardHtml).join("") + '</div>';
    }
    return bar + caption + warn + list;
  }

  function rvField(labelKey, value) {
    if (value == null || String(value).trim() === "") { return ""; }
    return '<div class="rvw-field"><span class="rvw-flabel">' + esc(t(labelKey)) + '</span>' +
      '<div class="rvw-fval">' + esc(value) + '</div></div>';
  }

  function reviewCardHtml(r) {
    var rk = reviewRowKey(r);
    var eff = (r.effective_verdict === "correct") ? "correct" : "incorrect";
    var effLabel = (eff === "correct") ? t("rv.v.correct") : t("rv.v.incorrect");

    var badges = '<span class="rvw-verdict ' + eff + '">' + esc(t("rv.effective")) + ': ' + esc(effLabel) + '</span>';
    if (r.overridden) {
      badges += '<span class="rvw-ovr">' + esc(t("rv.overriddenBy", { who: r.reviewed_by || "?" })) + '</span>';
    }
    if (r.needs_review) {
      badges += '<span class="rvw-flag">' + esc(t("rv.needsReview")) + '</span>';
    }

    var meta = '<div class="rvw-meta">' +
      (r.category ? '<span class="cat-tag">' + esc(r.category) + '</span>' : '') +
      (r.agent_label ? '<span class="rvw-agent">' + esc(r.agent_label) + '</span>' : '') +
      (r.mode ? '<span class="rvw-mode">' + esc(r.mode) + '</span>' : '') +
      (r.latency_str ? '<span class="rvw-kpi">' + esc(r.latency_str) + '</span>' : '') +
      ((r.estimated_cost != null && r.estimated_cost !== "") ? '<span class="rvw-kpi">$' + esc(fmtCost(r.estimated_cost)) + '</span>' : '') +
    '</div>';

    var jverdictCls = (r.judge_verdict === "correct") ? "correct" : ((r.judge_verdict === "incorrect") ? "incorrect" : "");
    var judge = '<div class="rvw-judge">' +
      '<span class="rvw-jlabel">' + esc(t("rv.judge")) + '</span>' +
      '<span class="rvw-jverdict ' + jverdictCls + '">' + esc(r.judge_verdict || t("common.dash")) + '</span>' +
      ((r.judge_score != null && r.judge_score !== "") ? '<span class="rvw-score">' + esc(t("rv.score")) + ' ' + esc(fmtNum(r.judge_score)) + '</span>' : '') +
      objChip(r) +
    '</div>';

    var fields = rvField("rv.judgeComment", r.judge_comment) +
      rvField("rv.reference", r.reference_answer);

    var expVal = (r.expected_value == null) ? "" : String(r.expected_value).trim();
    if (expVal) {
      fields += '<div class="rvw-field"><span class="rvw-flabel">' + esc(t("rv.expected")) + '</span>' +
        '<div class="rvw-fval"><span class="anchor-val">' + esc(expVal) + '</span>' +
        (r.expected_value_type ? '<span class="anchor-type">' + esc(r.expected_value_type) + '</span>' : '') + '</div></div>';
    }
    fields += rvField("rv.humanNote", r.notes);

    var expanded = !!S.review.expanded[rk];
    var ans = (r.answer_preview == null) ? "" : String(r.answer_preview);
    var answer = '<div class="rvw-answer">' +
      '<button type="button" class="rvw-toggle" data-rv="toggle" data-rk="' + esc(rk) + '">' +
        esc(expanded ? t("rv.answer.hide") : t("rv.answer.show")) + '</button>' +
      (expanded ? '<pre class="rvw-pre">' + esc(ans || t("rv.answer.empty")) + '</pre>' : '') +
    '</div>';

    var reviewed = "";
    if (r.overridden && r.reviewed_at) {
      reviewed = '<div class="rvw-reviewed">' + esc(t("rv.reviewedBy", { who: r.reviewed_by || "?", when: r.reviewed_at })) + '</div>';
    }

    var saving = !!S.review.saving[rk];
    var dis = saving ? " disabled" : "";
    var corActive = (r.human_verdict === "correct") ? " rvw-active" : "";
    var incActive = (r.human_verdict === "incorrect") ? " rvw-active" : "";
    var controls = '<div class="rvw-controls">' +
      '<input class="input rvw-comment" type="text" placeholder="' + esc(t("rv.commentPh")) + '" value="' + esc(r.human_comment || "") + '" aria-label="' + esc(t("rv.commentPh")) + '"' + dis + '>' +
      '<div class="rvw-btns">' +
        '<button type="button" class="btn btn-sm rvw-mc' + corActive + '" data-rv="correct" data-rk="' + esc(rk) + '"' + dis + '>' + esc(t("rv.markCorrect")) + '</button>' +
        '<button type="button" class="btn btn-sm btn-danger rvw-mi' + incActive + '" data-rv="incorrect" data-rk="' + esc(rk) + '"' + dis + '>' + esc(t("rv.markIncorrect")) + '</button>' +
        '<button type="button" class="btn btn-sm btn-ghost" data-rv="clear" data-rk="' + esc(rk) + '"' + (r.overridden && !saving ? "" : " disabled") + '>' + esc(t("rv.clear")) + '</button>' +
      '</div>' +
    '</div>';

    return '<div class="rvw-card" data-rk="' + esc(rk) + '">' +
      '<div class="rvw-head"><p class="rvw-q">' + esc(r.question) + '</p>' +
        '<div class="rvw-badges">' + badges + '</div></div>' +
      meta + judge + fields + answer + reviewed + controls +
    '</div>';
  }

  function wireReview() {
    var box = byId("reviewContent");
    if (!box) { return; }
    qsa(".ic-info", box).forEach(function (e) { e.innerHTML = I.info; });

    var runSel = byId("rvwRun");
    if (runSel) {
      runSel.addEventListener("change", function () {
        S.review.runId = runSel.value;
        S.review.expanded = {};
        loadReview();
      });
    }
    var only = byId("rvwOnly");
    if (only) {
      only.addEventListener("click", function () {
        S.review.onlyNeedsReview = !S.review.onlyNeedsReview;
        loadReview();
      });
    }
    qsa("[data-rv]", box).forEach(function (el) {
      var kind = el.getAttribute("data-rv");
      el.addEventListener("click", function () {
        if (kind === "retry") { loadReview(); return; }
        var rk = el.getAttribute("data-rk");
        if (kind === "toggle") {
          S.review.expanded[rk] = !S.review.expanded[rk];
          renderReview();
          return;
        }
        var row = findReviewRow(rk);
        if (!row) { return; }
        var comment = "";
        var card = el.closest ? el.closest(".rvw-card") : null;
        if (card) { var ci = card.querySelector(".rvw-comment"); if (ci) { comment = ci.value; } }
        if (kind === "correct") { doOverride(row, "correct", comment); }
        else if (kind === "incorrect") { doOverride(row, "incorrect", comment); }
        else if (kind === "clear") { doOverride(row, "", comment); }
      });
    });
  }


  function loadReview(opts) {
    opts = opts || {};
    S.review.loadError = false;
    if (!opts.quiet && !S.review.loaded) { renderReview(); }
    var path = "review?only_needs_review=" + (S.review.onlyNeedsReview ? "1" : "0");
    if (S.review.runId) { path += "&run_id=" + encodeURIComponent(S.review.runId); }
    callApi("GET", path).then(function (res) {
      var d = res.data || {};
      if (d.status === "ok") {
        S.review.runs = (d.runs || []).slice();
        S.review.rows = (d.rows || []).slice();
        S.review.count = (typeof d.count === "number") ? d.count : S.review.rows.length;
        if (d.run_id) { S.review.runId = d.run_id; }
        S.review.loaded = true;
        S.review.loadError = false;
        S.review.saving = {};
      } else {
        S.review.loadError = true;
      }
      renderReview();
    }, function () { S.review.loadError = true; renderReview(); });
  }

  function doOverride(row, verdict, comment) {
    var rk = reviewRowKey(row);
    if (S.review.saving[rk]) { return; }
    S.review.saving[rk] = true;
    renderReview();
    var payload = {
      run_id: S.review.runId,
      question_id: row.question_id,
      agent_key: row.agent_key || "",
      mode: row.mode || "",
      verdict: verdict,
      comment: comment || ""
    };
    callApi("POST", "override", payload).then(function (res) {
      S.review.saving[rk] = false;
      var d = res.data || {};
      if (d.status === "ok") {
        var matched = (typeof d.matched === "number") ? d.matched : 0;
        if (matched > 0) { toast(verdict ? t("rv.toast.set") : t("rv.toast.cleared")); }
        else { toast(t("rv.toast.nomatch")); }
        loadReview({ quiet: true });
      } else {
        var msg = (d.messages && d.messages.length) ? d.messages[0] : t("rv.toast.error");
        toast(msg);
        renderReview();
      }
    }, function () {
      S.review.saving[rk] = false;
      toast(t("rv.toast.error"));
      renderReview();
    });
  }

  /* ============================ tabs ============================ */

  function setTab(tab) {
    S.tab = tab;
    setTabUI(tab);
    if (tab === "golden" && !S.golden.loaded && !S.golden.loadError) { loadGolden(); }
    if (tab === "suggest" && !S.suggestions.loaded && !S.suggestions.loadError) { loadSuggestions(); }
    if (tab === "review" && !S.review.loaded && !S.review.loadError) { loadReview(); }
  }

  /* ============================ static wiring ============================ */

  function wireStatic() {
    qsa("#langSeg button").forEach(function (b) {
      b.addEventListener("click", function () {
        ui.lang = b.getAttribute("data-lang");
        try { localStorage.setItem("bench-lang", ui.lang); } catch (e) { /* */ }
        render();
      });
    });
    qsa("#themeSeg button").forEach(function (b) {
      b.addEventListener("click", function () {
        ui.theme = b.getAttribute("data-theme");
        applyTheme();
        try { localStorage.setItem("bench-theme", ui.theme); } catch (e) { /* */ }
        syncSeg("themeSeg", "data-theme", ui.theme);
      });
    });
    qsa(".tab").forEach(function (b) {
      b.addEventListener("click", function () { setTab(b.getAttribute("data-tab")); });
    });
    byId("addAgent").addEventListener("click", function () {
      S.agents.push({ agent_key: genKey(), agent_label: "", project_key: "", agent_id: "", modes: false });
      markDirty();
      renderAgents();
      toast(t("ag.added"));
    });
    byId("langFilter").addEventListener("change", function (e) { S.filterLanguage = e.target.value; markDirty(); });
    byId("benchLang").addEventListener("change", function (e) { S.benchLang = (e.target.value === "en") ? "en" : "fr"; markDirty(); });
    byId("concurrency").addEventListener("change", function (e) {
      var v = clampInt(e.target.value, 1, 8, S.concurrency);
      S.concurrency = v; e.target.value = v; markDirty();
    });
    byId("saveBtn").addEventListener("click", saveConfig);
    byId("launchBtn").addEventListener("click", launch);

    byId("mdClose").addEventListener("click", closeModal);
    byId("mdCancel").addEventListener("click", closeModal);
    byId("mdSave").addEventListener("click", submitModal);
    byId("mActive").addEventListener("click", function () {
      var on = this.getAttribute("data-on") !== "1";
      this.setAttribute("data-on", on ? "1" : "0");
      this.classList.toggle("on", on);
    });
    byId("overlay").addEventListener("click", function (e) { if (e.target === byId("overlay")) { closeModal(); } });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && S.editor.open) { closeModal(); } });
  }

  /* ============================ init ============================ */

  function init() {
    loadPrefs();
    applyTheme();
    applyLang();
    loadConfig();
  }

  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", init); }
  else { init(); }
})();
