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
    x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 6l-6 6 6 6M8 12h12"/></svg>',
    grid: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/></svg>',
    play: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 5l12 7-12 7z"/></svg>',
    gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3.2"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M18.4 5.6l-1.8 1.8M7.4 16.6l-1.8 1.8"/></svg>',
    theme: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 14a8 8 0 0 1-10-10 8 8 0 1 0 10 10z"/></svg>'
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

    "tab.bench": { en: "Benchmarks", fr: "Benchmarks" },
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
    "run.moved": {
      en: "Launching now happens per benchmark. Open a benchmark in the Benchmarks tab to run its pending questions or re-run it.",
      fr: "Le lancement se fait desormais par benchmark. Ouvrez un benchmark dans l'onglet Benchmarks pour lancer ses questions en attente ou le relancer."
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
    "common.retry": { en: "Retry", fr: "Reessayer" },

    /* --- benchmarks tab (v2: named per-agent benchmarks, append mode) --- */
    "bm.eyebrow": { en: "Benchmarks", fr: "Benchmarks" },
    "bm.title": { en: "Benchmarks", fr: "Benchmarks" },
    "bm.note": {
      en: "A benchmark is a named evaluation campaign pinned to one agent. Runs accumulate: launching tests only the not-yet-done questions, so the score grows question by question over time.",
      fr: "Un benchmark est une campagne d'evaluation nommee, rattachee a un seul agent. Les executions s'accumulent : un lancement ne teste que les questions pas encore faites, le score grandit donc question par question."
    },
    "bm.new": { en: "New benchmark", fr: "Nouveau benchmark" },
    "bm.count": { en: "{n} benchmark(s)", fr: "{n} benchmark(s)" },
    "bm.empty.h": { en: "No benchmark yet", fr: "Aucun benchmark" },
    "bm.empty.p": {
      en: "Create the first benchmark: pick an agent and seed it with your golden questions.",
      fr: "Creez le premier benchmark : choisissez un agent et amorcez-le avec vos questions de reference."
    },
    "bm.loadError": { en: "Could not load the benchmarks.", fr: "Impossible de charger les benchmarks." },
    "bm.open": { en: "Open", fr: "Ouvrir" },
    "bm.delete": { en: "Delete", fr: "Supprimer" },
    "bm.deleteConfirm": { en: "Delete \"{n}\"? This removes the benchmark from the registry. Past result rows stay in the dataset. This cannot be undone.", fr: "Supprimer \"{n}\" ? Le benchmark est retire du registre. Les lignes de resultats passees restent dans le dataset. Cette action est irreversible." },
    "bm.deleted": { en: "Benchmark deleted.", fr: "Benchmark supprime." },
    "bm.deleteError": { en: "Could not delete the benchmark.", fr: "Impossible de supprimer le benchmark." },
    "common.cancel": { en: "Cancel", fr: "Annuler" },
    "common.edit": { en: "Edit", fr: "Modifier" },
    "bm.badge.done": { en: "{n} done", fr: "{n} faites" },
    "bm.badge.pending": { en: "{n} pending", fr: "{n} en attente" },
    "bm.badge.redo": { en: "{n} redo", fr: "{n} a refaire" },
    "bm.lastRun": { en: "Last run", fr: "Derniere execution" },
    "bm.never": { en: "never", fr: "jamais" },
    "bm.accuracy": { en: "Accuracy", fr: "Justesse" },
    "bm.archived": { en: "Archived", fr: "Archive" },

    /* --- new-benchmark modal --- */
    "bn.title": { en: "New benchmark", fr: "Nouveau benchmark" },
    "bn.name": { en: "Benchmark name", fr: "Nom du benchmark" },
    "bn.namePh": { en: "e.g. orchestrator baseline", fr: "ex. reference orchestrateur" },
    "bn.agent": { en: "Agent under test", fr: "Agent teste" },
    "bn.agentNone": {
      en: "No agent in the catalog. Add one in the Configuration tab first.",
      fr: "Aucun agent dans le catalogue. Ajoutez-en un dans l'onglet Configuration."
    },
    "bn.seed": { en: "Questions", fr: "Questions" },
    "bn.seedAll": { en: "Seed with all active golden questions", fr: "Amorcer avec toutes les questions de reference actives" },
    "bn.seedEmpty": { en: "Start empty, add questions later", fr: "Commencer vide, ajouter des questions plus tard" },
    "bn.create": { en: "Create benchmark", fr: "Creer le benchmark" },
    "bn.cancel": { en: "Cancel", fr: "Annuler" },
    "bn.created": { en: "Benchmark created", fr: "Benchmark cree" },
    "bn.error": { en: "Could not create the benchmark.", fr: "Impossible de creer le benchmark." },

    /* --- benchmark detail --- */
    "bd.back": { en: "Back to list", fr: "Retour a la liste" },
    "bd.rename": { en: "Rename", fr: "Renommer" },
    "bd.renameSave": { en: "Save name", fr: "Enregistrer le nom" },
    "bd.renameCancel": { en: "Cancel", fr: "Annuler" },
    "bd.renamed": { en: "Benchmark renamed", fr: "Benchmark renomme" },
    "bd.renameError": { en: "Could not rename the benchmark.", fr: "Impossible de renommer le benchmark." },
    "bd.agent": { en: "Agent", fr: "Agent" },
    "bd.modes": { en: "Modes", fr: "Modes" },
    "bd.runPending": { en: "Run pending", fr: "Lancer les questions en attente" },
    "bd.runFull": { en: "Re-run entire benchmark", fr: "Relancer tout le benchmark" },
    "bd.runPendingHint": {
      en: "Nothing pending or flagged to redo. Add questions, flag some to redo, or re-run the entire benchmark.",
      fr: "Rien en attente ni a refaire. Ajoutez des questions, marquez-en a refaire, ou relancez tout le benchmark."
    },
    "bd.loadError": { en: "Could not load the benchmark.", fr: "Impossible de charger le benchmark." },
    "bd.qTitle": { en: "Questions", fr: "Questions" },
    "bd.empty": {
      en: "No question in this benchmark yet. Add some from the golden pool below.",
      fr: "Aucune question dans ce benchmark. Ajoutez-en depuis le jeu de reference ci-dessous."
    },
    "bd.addTitle": { en: "Add questions", fr: "Ajouter des questions" },
    "bd.addNote": {
      en: "Pick golden questions that are not already in this benchmark.",
      fr: "Choisissez des questions de reference pas encore presentes dans ce benchmark."
    },
    "bd.addToggle": { en: "Add questions", fr: "Ajouter des questions" },
    "bd.addNone": { en: "Every golden question is already a member of this benchmark.", fr: "Toutes les questions de reference sont deja membres de ce benchmark." },
    "bd.addSelected": { en: "Add selected", fr: "Ajouter la selection" },
    "bd.addCancel": { en: "Cancel", fr: "Annuler" },
    "bd.added": { en: "{n} question(s) added", fr: "{n} question(s) ajoutee(s)" },
    "bd.addError": { en: "Could not add the questions.", fr: "Impossible d'ajouter les questions." },
    "bd.remove": { en: "Remove", fr: "Retirer" },
    "bd.removed": { en: "Question removed from the benchmark", fr: "Question retiree du benchmark" },
    "bd.removeError": { en: "Could not remove the question.", fr: "Impossible de retirer la question." },
    "bd.redo": { en: "Redo at next run", fr: "Refaire au prochain lancement" },
    "bd.redoError": { en: "Could not update the redo flag.", fr: "Impossible de mettre a jour l'indicateur a refaire." },
    "bd.status.done": { en: "Done", fr: "Faite" },
    "bd.status.pending": { en: "Pending", fr: "En attente" },
    "bd.verdict.correct": { en: "Correct", fr: "Correcte" },
    "bd.verdict.incorrect": { en: "Incorrect", fr: "Incorrecte" },
    "bd.verdict.none": { en: "Not run", fr: "Non executee" },
    "bd.delta.improved": { en: "Improved", fr: "Amelioree" },
    "bd.delta.regressed": { en: "Regressed", fr: "Regression" },
    "bd.delta.same": { en: "Stable", fr: "Stable" },
    "bd.attempts": { en: "{n} attempt(s)", fr: "{n} tentative(s)" },
    "bd.refSql": { en: "Reference SQL", fr: "SQL de reference" },
    "bd.refTool": { en: "Suggested tool", fr: "Outil suggere" },
    "bd.refNone": { en: "No reference SQL or tool set.", fr: "Aucun SQL ni outil de reference." },
    "bd.evoShow": { en: "Show attempt history", fr: "Voir l'historique des tentatives" },
    "bd.evoHide": { en: "Hide attempt history", fr: "Masquer l'historique" },
    "bd.attempt": { en: "Attempt {n}", fr: "Tentative {n}" },

    /* --- golden: reference SQL / tool (soft judge signal) --- */
    "md.sql": { en: "Reference SQL (optional)", fr: "SQL de reference (optionnel)" },
    "md.sqlHelp": {
      en: "A SQL that could answer the question. A soft hint to the judge - a different but correct query is fine.",
      fr: "Un SQL qui pourrait repondre a la question. Un indice souple pour le juge - une requete differente mais correcte reste valable."
    },
    "md.tool": { en: "Suggested tool (optional)", fr: "Outil suggere (optionnel)" },
    "md.toolPh": { en: "show_chart / show_table / none", fr: "show_chart / show_table / none" },
    "th.ref": { en: "Reference SQL / tool", fr: "SQL / outil de reference" },

    /* --- review: benchmark selector + per-attempt override --- */
    "rv.bench": { en: "Benchmark", fr: "Benchmark" },
    "rv.attempt": { en: "Attempt {n}", fr: "Tentative {n}" },
    "rv.caption2": {
      en: "You review every attempt of the selected benchmark. An override targets that one attempt (its run) and survives future runs.",
      fr: "Vous revoyez chaque tentative du benchmark choisi. Une correction porte sur cette tentative (son execution) et survit aux executions suivantes."
    },

    /* --- agent-first shell --- */
    "hdr.link.golden":  { en: "Golden",      fr: "Jeu de ref." },
    "hdr.link.suggest": { en: "Suggestions", fr: "Suggestions" },
    "hdr.link.review":  { en: "Review",       fr: "Revue" },
    "hdr.back":         { en: "Back",         fr: "Retour" },

    "rail.title":       { en: "AGENTS",       fr: "AGENTS" },
    "rail.refresh":     { en: "Refresh",      fr: "Actualiser" },
    "rail.empty":       { en: "No agent yet. Refresh or add one manually.", fr: "Aucun agent. Actualisez ou ajoutez-en un manuellement." },
    "rail.discovering": { en: "Discovering agents...", fr: "Decouverte des agents..." },
    "rail.discovered":  { en: "{n} agent(s) found",   fr: "{n} agent(s) trouve(s)" },
    "rail.failed":      { en: "Discovery failed - known agents shown", fr: "Decouverte echouee - agents connus affiches" },
    "rail.nTagged":     { en: "{n} tagged",   fr: "{n} taguees" },

    "gs.step1": { en: "Connect an agent",    fr: "Connectez un agent" },
    "gs.step2": { en: "Tag questions to it", fr: "Taguez des questions" },
    "gs.step3": { en: "Create a benchmark",  fr: "Creez un benchmark" },
    "gs.step4": { en: "Run it",              fr: "Lancez-le" },

    "bcr.home": { en: "Agents", fr: "Agents" },

    "agv.new":      { en: "New benchmark",         fr: "Nouveau benchmark" },
    "agv.nTagged":  { en: "{n} tagged question(s)", fr: "{n} question(s) taguee(s)" },
    "agv.tagLink":  { en: "Tag questions to this agent", fr: "Taguer des questions pour cet agent" },
    "agv.loadError":{ en: "Could not load the benchmarks.", fr: "Impossible de charger les benchmarks." },
    "agv.2b.h":     { en: "No benchmark yet",      fr: "Aucun benchmark" },
    "agv.2b.p":     { en: "Create the first benchmark for this agent.", fr: "Creez le premier benchmark pour cet agent." },
    "agv.2c.h":     { en: "No benchmark yet",      fr: "Aucun benchmark" },
    "agv.2c.p":     { en: "Tag questions to this agent first, then create a benchmark.", fr: "Taguez d'abord des questions a cet agent, puis creez un benchmark." },
    "agv.2c.tag":   { en: "Tag questions",         fr: "Taguer des questions" },
    "agv.2c.locked":{ en: "No tagged question yet - tag some to enable benchmark creation.", fr: "Aucune question taguee - taguez-en pour creer un benchmark." },

    "cr.eyebrow":  { en: "New benchmark",     fr: "Nouveau benchmark" },
    "cr.title":    { en: "Create benchmark",  fr: "Creer un benchmark" },
    "cr.agent":    { en: "Agent",             fr: "Agent" },
    "cr.name":     { en: "Benchmark name",    fr: "Nom du benchmark" },
    "cr.namePh":   { en: "e.g. Q4 Baseline", fr: "ex. Reference Q4" },
    "cr.nameHint": { en: "Unique for this agent.", fr: "Unique pour cet agent." },
    "cr.modes":    { en: "Response modes",    fr: "Modes de reponse" },
    "cr.pending":  { en: "{n} question(s) will be queued on creation.", fr: "{n} question(s) seront en attente a la creation." },
    "cr.noTagged": { en: "0 tagged questions - tag some first to enable creation.", fr: "0 question taguee - taguez-en d'abord pour creer un benchmark." },
    "cr.create":   { en: "Create",            fr: "Creer" },
    "cr.tag":      { en: "Tag questions",     fr: "Taguer des questions" },
    "cr.cancel":   { en: "Cancel",            fr: "Annuler" },
    "cr.created":  { en: "Benchmark created.", fr: "Benchmark cree." },
    "cr.error":    { en: "Could not create the benchmark.", fr: "Impossible de creer le benchmark." },

    "footer.copy": {
      en: "Benchmarks and redo flags live in the project variable \"benchmark\". Questions and results live in Flow datasets (set their names in Settings).",
      fr: "Les benchmarks et les indicateurs a refaire vivent dans la variable de projet \"benchmark\". Les questions et resultats vivent dans les datasets Flow (noms a configurer dans Parametres)."
    },

    "bd4.col.q":      { en: "Question",            fr: "Question" },
    "bd4.col.cat":    { en: "Category",            fr: "Categorie" },
    "bd4.col.redo":   { en: "Redo",                fr: "A refaire" },
    "bd4.editModes":  { en: "Edit modes",          fr: "Modifier les modes" },
    "bd4.editSave":   { en: "Save",                fr: "Enregistrer" },
    "bd4.modesOk":    { en: "Modes updated.",      fr: "Modes mis a jour." },
    "bd4.modesError": { en: "Could not update modes.", fr: "Impossible de mettre a jour les modes." },
    "bd4.runDone":    { en: "Run complete.",        fr: "Execution terminee." },
    "bd4.runError":   { en: "Launch failed.",       fr: "Echec du lancement." },
    "bd4.tagQ":       { en: "Tag questions",        fr: "Taguer des questions" },
    "bd.newPending":  {
      en: "{n} pending cell(s) since the last run. Run pending to test them.",
      fr: "{n} cellule(s) en attente depuis le dernier run. Lancez les questions en attente pour les tester."
    },

    /* --- Screen 5: run lifecycle --- */
    "run.progress":     { en: "Running... {scored} / {total}", fr: "En cours... {scored} / {total}" },
    "run.elapsed":      { en: "Running... {s}s",               fr: "En cours... {s}s" },
    "run.singleFlight": { en: "Only one run at a time. You can leave; it keeps going.", fr: "Un seul run a la fois. Vous pouvez partir, il continue." },
    "run.viewRun":      { en: "View run",     fr: "Voir le run" },
    "run.complete.score":   { en: "Score: {pct}",    fr: "Score : {pct}" },
    "run.complete.mode":    { en: "{mode}: {pct}",   fr: "{mode} : {pct}" },
    "run.complete.results": { en: "Open full results in Results webapp", fr: "Voir les resultats complets dans la webapp Results" },
    "run.evo.title":    { en: "Changes vs previous run",  fr: "Changements par rapport au run precedent" },
    "run.evo.improved": { en: "Improved",   fr: "Ameliore" },
    "run.evo.regressed":{ en: "Regressed",  fr: "Regresse" },
    "run.evo.same":     { en: "Unchanged",  fr: "Inchange" },
    "run.evo.new":      { en: "New",        fr: "Nouveau" },
    "run.reset":        { en: "Reset run state", fr: "Reinitialiser l'etat du run" },
    "run.resetHint":    { en: "The scenario is idle but a run request is still set. Reset to unblock.", fr: "Le scenario est inactif mais une demande de run est encore definie. Reinitialiser pour debloquer." },
    "run.rerun.title":  { en: "Re-run entire benchmark",  fr: "Relancer tout le benchmark" },
    "run.rerun.scope":  { en: "Scope: {n} questions x {m} modes = {t} runs", fr: "Perimetre : {n} questions x {m} modes = {t} executions" },
    "run.rerun.go":     { en: "Re-run all", fr: "Tout relancer" },
    "run.locked":       { en: "Another benchmark is running.", fr: "Un autre benchmark est en cours d'execution." },

    /* --- Screen 6: golden agent-tagging --- */
    "gt.title":        { en: "Golden questions",  fr: "Questions golden" },
    "gt.eyebrow":      { en: "AGENT-FIRST",       fr: "PAR AGENT" },
    "gt.scope.agent":  { en: "This agent",        fr: "Cet agent" },
    "gt.scope.untagged":{ en: "Untagged",         fr: "Sans tag" },
    "gt.scope.all":    { en: "All",               fr: "Toutes" },
    "gt.searchPh":     { en: "Search...",          fr: "Rechercher..." },
    "gt.col.q":        { en: "Question",          fr: "Intitule" },
    "gt.col.active":   { en: "Active",            fr: "Actif" },
    "gt.col.agent":    { en: "Agent tag",         fr: "Tag agent" },
    "gt.noAgent":      { en: "(none)",            fr: "(aucun)" },
    "gt.add":          { en: "Add question",      fr: "Ajouter une question" },
    "gt.save":         { en: "Save",              fr: "Enregistrer" },
    "gt.cancel":       { en: "Cancel",            fr: "Annuler" },
    "gt.delete":       { en: "Delete",            fr: "Supprimer" },
    "gt.deleteConfirm":{ en: "Delete this question permanently?", fr: "Supprimer cette question definitivement ?" },
    "gt.deleted":      { en: "Question deleted.", fr: "Question supprimee." },
    "gt.loading":      { en: "Loading questions...", fr: "Chargement des questions..." },
    "gt.empty":        { en: "No questions match.", fr: "Aucune question correspondante." },
    "gt.agentRequired":{ en: "An agent tag is required.", fr: "Un tag agent est requis." },
    "gt.saved":        { en: "Question saved.",   fr: "Question enregistree." },
    "gt.loadError":    { en: "Could not load questions.", fr: "Impossible de charger les questions." },
    "gt.formQ":        { en: "Question",          fr: "Intitule" },
    "gt.formA":        { en: "Reference answer",  fr: "Reponse de reference" },
    "gt.formSql":      { en: "Expected SQL (optional)", fr: "SQL attendu (optionnel)" },
    "gt.formTool":     { en: "Expected tool (optional)", fr: "Outil attendu (optionnel)" },
    "gt.formAgent":    { en: "Agent tag",         fr: "Tag agent" },
    "gt.formCat":      { en: "Category",          fr: "Categorie" },
    "gt.formLang":     { en: "Language",          fr: "Langue" },
    "gt.formActive":   { en: "Active",            fr: "Actif" },

    /* --- Screen 7: settings panel --- */
    "st.title":         { en: "Settings",        fr: "Parametres" },
    "st.close":         { en: "Close",           fr: "Fermer" },
    "st.golden":        { en: "Golden dataset name", fr: "Nom du dataset golden" },
    "st.goldenHint":    { en: "Managed dataset containing the golden questions.", fr: "Dataset manage contenant les questions golden." },
    "st.judge":         { en: "Judge LLM id",    fr: "Identifiant du LLM juge" },
    "st.judgeHint":     { en: "Mesh connection id of the model used to judge answers.", fr: "Identifiant de connexion Mesh du modele utilise comme juge." },
    "st.concurrency":   { en: "Concurrency",     fr: "Concurrence" },
    "st.concurrencyHint":{ en: "Max parallel agent calls during a run (1-10).", fr: "Appels agents paralleles maximum pendant un run (1-10)." },
    "st.runLang":       { en: "Run language",    fr: "Langue des runs" },
    "st.runLangHint":   { en: "Language in which questions are sent to the agent (separate from the interface language).", fr: "Langue dans laquelle les questions sont envoyees a l'agent (independante de la langue d'interface)." },
    "st.langEn":        { en: "English (en)",    fr: "Anglais (en)" },
    "st.langFr":        { en: "French (fr)",     fr: "Francais (fr)" },
    "st.rawDs":         { en: "Raw results dataset",     fr: "Dataset des resultats bruts" },
    "st.scoredDs":      { en: "Scored results dataset",  fr: "Dataset des resultats scores" },
    "st.summaryDs":     { en: "Summary dataset",          fr: "Dataset de synthese" },
    "st.breakdownDs":   { en: "Breakdown dataset",        fr: "Dataset de repartition" },
    "st.whereData":     { en: "Benchmarks and redo flags live in the project variable 'benchmark'. Questions and results live in Flow datasets (named above).", fr: "Les benchmarks et les drapeaux 'a refaire' vivent dans la variable projet 'benchmark'. Les questions et les resultats vivent dans des datasets du Flow (nommes ci-dessus)." },
    "st.save":          { en: "Save settings",   fr: "Enregistrer les parametres" },
    "st.saved":         { en: "Settings saved.", fr: "Parametres enregistres." },
    "st.loading":       { en: "Loading settings...", fr: "Chargement des parametres..." },
    "st.loadError":     { en: "Could not load settings.", fr: "Impossible de charger les parametres." }
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
    tab: "benchmarks",
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
    // review (human-in-the-loop verdict override) - v2: a benchmark selector, every attempt listed
    review: { loaded: false, loadError: false, benchmarkId: "", onlyNeedsReview: false, benchmarks: [], rows: [], count: 0, expanded: {}, saving: {} },
    // benchmarks (v2): named per-agent campaigns, list + open one (detail)
    bench: {
      loaded: false, loadError: false,
      list: [], agents: [], modeOptions: [], golden: [],
      view: "list", detailId: "",
      detail: null, detailLoaded: false, detailError: false,
      addOpen: false, addSel: {},
      renaming: false,
      expanded: {},
      running: false, runMsg: null, busy: false
    },
    // new-benchmark modal
    benchNew: { open: false, error: null },
    // Agent-first routing (dispatch 1)
    route: { level: "home", agentKey: null, benchmarkId: null },
    agentCatalog: { loaded: false, loadError: false, discovering: false, agents: [], discovered_at: null, discoveryFailed: false },
    agentView: { loaded: false, loadError: false, agentKey: null, n_tagged: 0, benchmarks: [], creating: false, submitting: false, createError: null, createName: "", createModes: [], bmDeleteConfirmId: "" },
    // Screen 4: benchmark detail (dispatch 2)
    benchDetailState: { loaded: false, loadError: false, detail: null, editModes: false, editModesValue: [], deleteConfirm: false, running: false, runMsg: null, runScored: 0, runTotal: 0, runStartedAt: null, runComplete: null, rerunConfirm: false, resetNeeded: false },
    // Screen 6: golden agent-tagging panel
    goldenTag: { loaded: false, loadError: false, list: [], agents: [], scope: "agent", searchText: "", editRow: null, confirmDelete: null, saving: false, saveError: null },
    // Screen 7: settings panel
    settings: { open: false, loaded: false, loadError: false, data: {}, saving: false, saveError: null, fieldErrors: {} }
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
      { question_id: "a_revenue001", question: "Quel est le revenu reel du compte Maroc Telecom sur l'annee en cours ?", reference_answer: "Le revenu reel (ACTUALS) du compte Maroc Telecom sur l'annee en cours est de 4 218 540 euros, toutes periodes confondues.", expected_value: "4218540", expected_value_type: "currency", category: "revenue", language: "fr", active: true, notes: "", expected_sql: "SELECT SUM(amount_eur) FROM drive_revenues WHERE account_name = 'Maroc Telecom' AND phase = 'ACTUALS'", expected_tool: "show_table", agent_key: "orchestrator" },
      { question_id: "u_sug_d4e5f6", question: "How many distinct open trouble tickets does Algerie Telecom currently have?", reference_answer: "Algerie Telecom currently has 37 distinct open trouble tickets (counted on the latest snapshot per ticket id).", expected_value: "37", expected_value_type: "numeric", category: "tickets", language: "en", active: true, notes: "promoted from user suggestion sug_d4e5f6 (source=manual)", expected_sql: "SELECT COUNT(DISTINCT id) FROM trouble_tickets WHERE account = 'Algerie Telecom' AND CurrentStatus = 'OPEN'", expected_tool: "none", agent_key: "orchestrator" },
      { question_id: "a_offer002", question: "Quelle est la hierarchie d'offre pour le produit IPL ?", reference_answer: "IPL est un SolutionLine (niveau intermediaire de la hierarchie d'offre).", expected_value: "", expected_value_type: "", category: "offre", language: "fr", active: false, notes: "desactivee le temps de valider la reponse", expected_sql: "", expected_tool: "" }
    ],
    benchmarks: [
      { benchmark_id: "bm_said01", name: "said", agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", modes: ["Smart", "Claude"], status: "active", created_at: "2026-06-25T09:00:00Z", n_questions: 3, n_done: 2, n_pending: 1, n_redo: 1, n_scored: 2, n_runs: 2, last_run_timestamp: "2026-06-26 09:02:34", accuracy: 0.5, accuracy_pct: "50%", band: "low" },
      { benchmark_id: "bm_quick02", name: "tickets smoke", agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", modes: ["Smart"], status: "active", created_at: "2026-06-29T11:00:00Z", n_questions: 1, n_done: 0, n_pending: 1, n_redo: 0, n_scored: 0, n_runs: 0, last_run_timestamp: "", accuracy: 0, accuracy_pct: "-", band: "none" }
    ],
    bench_agents: [
      { agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", project_key: "OWISMIND_DEV", agent_id: "agent:038G7mlF", modes: true }
    ],
    suggestions: [
      { suggestion_id: "sug_a1b2c3", user_id: "marie.dupont", source: "chat", question: "Quel est le revenu reel du compte Maroc Telecom sur l'annee en cours ?", reference_answer: "Le revenu reel (ACTUALS) du compte Maroc Telecom sur l'annee en cours est de 4 218 540 euros, toutes periodes confondues.", answer_is_correct: true, missing_explanation: "", expected_value: "4218540", expected_value_type: "currency", category: "revenue", language: "fr", created_at: "2026-06-24 14:09:22" },
      { suggestion_id: "sug_g7h8i9", user_id: "sara.benali", source: "chat", question: "Quel est le budget 2026 du produit Roaming Hub pour le client Airbus ?", reference_answer: "Le budget 2026 du produit Roaming Hub pour Airbus est de 1 050 000 euros (scenario BUDGET, periode 2026).", answer_is_correct: null, missing_explanation: "L'agent a confondu Roaming Hub avec Roaming Sponsor.", expected_value: "1050000", expected_value_type: "currency", category: "revenue", language: "fr", created_at: "2026-06-23 17:30:05" }
    ],
    // v2 benchmark detail: new shape with cells[], ledger, runnable, redo flag per question.
    bench_detail: {
      bm_said01: {
        benchmark_id: "bm_said01", name: "said",
        agent: { agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", project_key: "OWISMIND_DEV", agent_id: "agent:038G7mlF" },
        modes: ["Smart", "Claude"],
        ledger: { tested: 1, pending: 2, redo: 1 },
        runnable: 4,
        accuracy_pct: "33%",
        questions: [
          {
            question_id: "a_revenue001",
            question: "Quel est le revenu reel du compte Maroc Telecom sur l'annee en cours ?",
            category: "revenue",
            expected_sql: "SELECT SUM(amount_eur) FROM drive_revenues WHERE account_name = 'Maroc Telecom' AND phase = 'ACTUALS'",
            expected_tool: "show_table",
            redo: false,
            cells: [
              { mode: "Smart", status: "tested", verdict: "OK" },
              { mode: "Claude", status: "tested", verdict: "MISS" }
            ]
          },
          {
            question_id: "u_sug_d4e5f6",
            question: "How many distinct open trouble tickets does Algerie Telecom currently have?",
            category: "tickets",
            expected_sql: "SELECT COUNT(DISTINCT id) FROM trouble_tickets WHERE account = 'Algerie Telecom' AND CurrentStatus = 'OPEN'",
            expected_tool: "none",
            redo: true,
            cells: [
              { mode: "Smart", status: "tested", verdict: "MISS" },
              { mode: "Claude", status: "pending", verdict: "" }
            ]
          },
          {
            question_id: "a_offer002",
            question: "Quelle est la hierarchie d'offre pour le produit IPL ?",
            category: "offre",
            expected_sql: "",
            expected_tool: "",
            redo: false,
            cells: [
              { mode: "Smart", status: "pending", verdict: "" },
              { mode: "Claude", status: "pending", verdict: "" }
            ]
          }
        ]
      },
      bm_quick02: {
        benchmark_id: "bm_quick02", name: "tickets smoke",
        agent: { agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", project_key: "OWISMIND_DEV", agent_id: "agent:038G7mlF" },
        modes: ["Smart"],
        ledger: { tested: 0, pending: 1, redo: 0 },
        runnable: 1,
        accuracy_pct: "-",
        questions: [
          {
            question_id: "u_sug_d4e5f6",
            question: "How many distinct open trouble tickets does Algerie Telecom currently have?",
            category: "tickets",
            expected_sql: "SELECT COUNT(DISTINCT id) FROM trouble_tickets WHERE account = 'Algerie Telecom' AND CurrentStatus = 'OPEN'",
            expected_tool: "none",
            redo: false,
            cells: [
              { mode: "Smart", status: "pending", verdict: "" }
            ]
          }
        ]
      }
    },
    // v2 review: the benchmark selector + every attempt of one benchmark (NOT reduced to latest).
    review_benchmarks: [
      { benchmark_id: "bm_said01", benchmark_name: "said", last_run_timestamp: "2026-06-26 09:02:34" }
    ],
    review: {
      bm_said01: [
        { question_id: "u_sug_d4e5f6", question: "How many distinct open trouble tickets does Algerie Telecom currently have?", category: "tickets", run_id: "run_20260626_0902", run_timestamp: "2026-06-26 09:02:34", agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", mode: "Smart", status: "ok", objective_match: false, judge_score: 0.4, judge_verdict: "incorrect", judge_comment: "The agent answered 41 tickets but the reference anchor is 37: it counted raw snapshot rows instead of distinct ticket ids.", reference_answer: "Algerie Telecom currently has 37 distinct open trouble tickets (counted on the latest snapshot per ticket id).", answer_preview: "Algerie Telecom currently has 41 open trouble tickets.\n\nSQL: SELECT COUNT(*) FROM trouble_tickets WHERE status = 'OPEN' AND account = 'Algerie Telecom'", notes: "Strictness: accept the distinct count on the latest snapshot per id. Raw row counts are wrong.", expected_value: "37", expected_value_type: "numeric", benchmark_id: "bm_said01", benchmark_name: "said", attempt_no: 1, expected_sql: "SELECT COUNT(DISTINCT id) FROM trouble_tickets WHERE account = 'Algerie Telecom' AND CurrentStatus = 'OPEN'", expected_tool: "none", actual_tools: "table", correct: false, needs_review: true, latency_str: "12.4s", estimated_cost: 0.0182 },
        { question_id: "a_revenue001", question: "Quel est le revenu reel du compte Maroc Telecom sur l'annee en cours ?", category: "revenue", run_id: "run_20260626_0902", run_timestamp: "2026-06-26 09:02:34", agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", mode: "Smart", status: "ok", objective_match: true, judge_score: 0.95, judge_verdict: "correct", judge_comment: "Matches the anchor value 4 218 540 and the expected scope (ACTUALS, all periods).", reference_answer: "Le revenu reel (ACTUALS) du compte Maroc Telecom sur l'annee en cours est de 4 218 540 euros, toutes periodes confondues.", answer_preview: "Le revenu reel (ACTUALS) du compte Maroc Telecom est de 4 218 540 EUR sur l'annee en cours, toutes periodes confondues.", notes: "", expected_value: "4218540", expected_value_type: "currency", benchmark_id: "bm_said01", benchmark_name: "said", attempt_no: 2, expected_sql: "SELECT SUM(amount_eur) FROM drive_revenues WHERE account_name = 'Maroc Telecom' AND phase = 'ACTUALS'", expected_tool: "show_table", actual_tools: "table", correct: true, needs_review: false, latency_str: "9.1s", estimated_cost: 0.0121 },
        { question_id: "a_revenue001", question: "Quel est le revenu reel du compte Maroc Telecom sur l'annee en cours ?", category: "revenue", run_id: "run_20260625_1740", run_timestamp: "2026-06-25 17:40:11", agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", mode: "Smart", status: "ok", objective_match: false, judge_score: 0.55, judge_verdict: "incorrect", judge_comment: "Right account but reported a budget figure, not the ACTUALS scope.", reference_answer: "Le revenu reel (ACTUALS) du compte Maroc Telecom sur l'annee en cours est de 4 218 540 euros, toutes periodes confondues.", answer_preview: "Le revenu du compte Maroc Telecom est d'environ 3 900 000 EUR.", notes: "", expected_value: "4218540", expected_value_type: "currency", benchmark_id: "bm_said01", benchmark_name: "said", attempt_no: 1, expected_sql: "SELECT SUM(amount_eur) FROM drive_revenues WHERE account_name = 'Maroc Telecom' AND phase = 'ACTUALS'", expected_tool: "show_table", actual_tools: "table", correct: false, needs_review: false, latency_str: "8.3s", estimated_cost: 0.0150 }
      ]
    },
    // Agent catalog (populated by GET /api/agents + POST /api/agents/discover)
    agent_catalog: {
      agents: [
        { agent_key: "orchestrator", agent_label: "OWIsMind Orchestrator (DEV)", project_key: "OWISMIND_DEV", agent_id: "agent:038G7mlF", modes: true }
      ],
      discovered_at: "2026-06-30T08:00:00Z"
    },
    // Number of active tagged golden questions per agent_key
    agent_tagged: { orchestrator: 2 },
    // Settings (Screen 7)
    settings: {
      golden_dataset: "golden_questions_v1_prepared",
      judge_llm_id: "anthropic:claude-sonnet-4-6",
      concurrency: 3,
      run_language: "fr",
      raw_dataset: "benchmark_runs_raw",
      scored_dataset: "benchmark_runs_scored",
      summary_dataset: "benchmark_summary",
      breakdown_dataset: "benchmark_breakdown"
    }
  };
  var mockRun = { remaining: 0, bid: null };
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
      var mockTotal = 3;
      var mockScored = running ? Math.max(0, mockTotal - mockRun.remaining - 1) : mockTotal;
      data = { status: "ok", running: running, scored: mockScored, total: mockTotal, last: running ? null : "SUCCESS", benchmark_id: mockRun.bid };
      if (running) {
        data.run_request = { benchmark_id: mockRun.bid };
      } else {
        // Completion payload: overall score, per-mode accuracy, and a sample re-run evolution
        // (one improved, one regressed, one unchanged) so the run-complete card has data.
        data.just_completed = true;
        data.run_request = null;
        data.result = {
          score_pct: "67%",
          by_mode: [{ mode: "Smart", pct: "100%" }, { mode: "Claude", pct: "33%" }],
          evolution: [
            { question: "Quel est le revenu reel du compte Maroc Telecom sur l'annee en cours ?", prev_verdict: "MISS", cur_verdict: "OK" },
            { question: "How many distinct open trouble tickets does Algerie Telecom currently have?", prev_verdict: "OK", cur_verdict: "MISS" },
            { question: "Quelle est la hierarchie d'offre pour le produit IPL ?", prev_verdict: "OK", cur_verdict: "OK" }
          ]
        };
      }
    } else if (method === "POST" && path === "run/reset") {
      mockRun.remaining = 0; mockRun.bid = null;
      data = { status: "ok", reset: true };
    } else if (method === "GET" && path === "suggestions") {
      var pending = MOCK.suggestions.filter(function (s) { return !mockPromoted[s.suggestion_id]; });
      data = { status: "ok", configured: true, suggestions: pending };
    } else if (method === "POST" && path === "suggestions/promote") {
      var ids = (body && body.suggestion_ids) || [];
      var promoted = 0;
      ids.forEach(function (id) { if (!mockPromoted[id]) { mockPromoted[id] = true; promoted += 1; } });
      data = { status: "ok", promoted: promoted, recorded: ids.length };
    } else if (method === "GET" && path0 === "golden" && !path.startsWith("golden/")) {
      var gtParams = parseQuery(path);
      var gtScope = gtParams.scope || "all";
      var gtAgKey = gtParams.agent_key || "";
      var gtList = MOCK.golden.slice();
      if (gtScope === "agent" && gtAgKey) { gtList = gtList.filter(function (g) { return g.agent_key === gtAgKey; }); }
      else if (gtScope === "untagged") { gtList = gtList.filter(function (g) { return !g.agent_key; }); }
      data = { status: "ok", questions: gtList, agents: MOCK.bench_agents.slice() };
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
        var nrow = { question_id: qid, question: q, reference_answer: ref, expected_value: (body.expected_value || ""), expected_value_type: (body.expected_value_type || ""), category: (body.category || ""), language: (body.language === "en") ? "en" : "fr", active: body.active !== false, notes: (body.notes || ""), expected_sql: (body.expected_sql || ""), expected_tool: (body.expected_tool || ""), agent_key: (body.agent_key || "") };
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
      var rvBid = params.benchmark_id || (MOCK.review_benchmarks[0] && MOCK.review_benchmarks[0].benchmark_id) || "";
      var base = (MOCK.review[rvBid] || []).map(deepCopy);
      var rows = base.map(function (r) { return mockEffectiveRow(r.run_id, r); });
      if (params.only_needs_review === "1") { rows = rows.filter(function (r) { return !!r.needs_review; }); }
      // needs-review first, then a question's attempts grouped newest-first (matches review_view).
      rows.sort(function (a, b) {
        if ((b.needs_review ? 1 : 0) !== (a.needs_review ? 1 : 0)) { return (b.needs_review ? 1 : 0) - (a.needs_review ? 1 : 0); }
        if (a.question_id !== b.question_id) { return a.question_id < b.question_id ? -1 : 1; }
        return (b.attempt_no || 0) - (a.attempt_no || 0);
      });
      data = { status: "ok", benchmark_id: rvBid, count: rows.length, benchmarks: MOCK.review_benchmarks.slice(), rows: rows };
    } else if (method === "GET" && path0 === "benchmarks") {
      data = { status: "ok", benchmarks: MOCK.benchmarks.slice(), agents: MOCK.bench_agents.slice(),
               modes: MOCK.mode_options.slice(), golden: MOCK.golden.slice() };
    } else if (method === "GET" && path0 === "benchmark/detail") {
      var dParams = parseQuery(path);
      var det = MOCK.bench_detail[dParams.benchmark_id || ""];
      if (det) { data = { status: "ok", ...deepCopy(det) }; }
      else { status = 404; data = { status: "error", error: "unknown_benchmark" }; }
    } else if (method === "POST" && path0 === "benchmark/create") {
      data = mockBenchCreate(body || {});
    } else if (method === "POST" && path0 === "benchmark/add-questions") {
      data = mockBenchMutate(body, function (d, b) {
        var have = {}; d.questions.forEach(function (q) { have[q.question_id] = true; });
        (b.question_ids || []).forEach(function (qid) {
          if (have[qid]) { return; }
          var g = MOCK.golden.filter(function (x) { return x.question_id === qid; })[0] || {};
          d.questions.push({ question_id: qid, question: g.question || qid, category: g.category || "",
            expected_sql: g.expected_sql || "", expected_tool: g.expected_tool || "",
            redo: false, cells: (d.modes || []).map(function (m) { return { mode: m, status: "pending", verdict: "" }; }) });
        });
        return { benchmark_id: d.benchmark_id, n_questions: d.questions.length };
      });
    } else if (method === "POST" && path0 === "benchmark/remove-question") {
      data = mockBenchMutate(body, function (d, b) {
        d.questions = d.questions.filter(function (q) { return q.question_id !== b.question_id; });
        return { benchmark_id: d.benchmark_id };
      });
    } else if (method === "POST" && path0 === "benchmark/redo") {
      data = mockBenchMutate(body, function (d, b) {
        d.questions.forEach(function (q) { if (q.question_id === b.question_id) { q.redo = !!b.value; } });
        return { benchmark_id: d.benchmark_id, question_id: b.question_id, redo: !!b.value };
      });
    } else if (method === "POST" && path0 === "benchmark/modes") {
      data = mockBenchMutate(body, function (d, b) {
        var newModes = (b.modes || []).filter(function (m) { return ["Smart", "Pro", "Claude", "default"].indexOf(m) !== -1; });
        if (!newModes.length) { return { _err: ["at least one mode is required"] }; }
        if (MOCK.benchmarks.some(function (bk) {
          return bk.benchmark_id !== d.benchmark_id && bk.agent_key === (d.agent && d.agent.agent_key) &&
                 bk.name.toLowerCase() === d.name.toLowerCase();
        })) { /* name uniqueness already satisfied */ }
        // Update cells: keep existing results, add new pending, drop removed modes
        d.questions.forEach(function (q) {
          var existing = {};
          (q.cells || []).forEach(function (c) { existing[c.mode] = c; });
          q.cells = newModes.map(function (m) { return existing[m] || { mode: m, status: "pending", verdict: "" }; });
        });
        d.modes = newModes;
        return { benchmark_id: d.benchmark_id, modes: newModes };
      });
    } else if (method === "POST" && path0 === "benchmark/rename") {
      data = mockBenchMutate(body, function (d, b) {
        var nm = (b.name || "").trim();
        if (!nm) { return { _err: ["name is required"] }; }
        if (MOCK.benchmarks.some(function (x) { return x.benchmark_id !== d.benchmark_id && x.name.toLowerCase() === nm.toLowerCase(); })) {
          return { _err: ["a benchmark named '" + nm + "' already exists"] };
        }
        d.name = nm;
        return { benchmark_id: d.benchmark_id, name: nm };
      });
    } else if (method === "POST" && path0 === "benchmark/delete") {
      var delBid2 = (body && body.benchmark_id) || "";
      if (!MOCK.bench_detail[delBid2]) { status = 404; data = { status: "error", error: "unknown_benchmark" }; }
      else {
        delete MOCK.bench_detail[delBid2];
        MOCK.benchmarks = MOCK.benchmarks.filter(function (b) { return b.benchmark_id !== delBid2; });
        data = { status: "ok", benchmark_id: delBid2 };
      }
    } else if (method === "POST" && path0 === "benchmark/archive") {
      data = mockBenchMutate(body, function (d) { d.status = "archived"; return { benchmark_id: d.benchmark_id, status: "archived" }; });
    } else if (method === "POST" && path0 === "benchmark/launch") {
      var lbid = (body && body.benchmark_id) || "";
      if (!MOCK.bench_detail[lbid]) { status = 404; data = { status: "error", error: "unknown_benchmark" }; }
      else if (mockRun.remaining > 0 && mockRun.bid !== lbid) { status = 409; data = { status: "error", error: "already_running" }; }
      else { mockRun.remaining = 3; mockRun.bid = lbid; data = { status: "ok", launched: true, launch_mode: (body && body.launch_mode) || "append" }; }
    } else if (method === "GET" && path0 === "agents") {
      data = { status: "ok", agents: MOCK.agent_catalog.agents.slice(), discovered_at: MOCK.agent_catalog.discovered_at };
    } else if (method === "POST" && path0 === "agents/discover") {
      MOCK.agent_catalog.discovered_at = new Date().toISOString();
      data = { status: "ok", agents: MOCK.agent_catalog.agents.slice(), discovered_at: MOCK.agent_catalog.discovered_at, discovery: "ok" };
    } else if (method === "GET" && path0 === "agent/benchmarks") {
      var agParams = parseQuery(path);
      var agKey = agParams.agent_key || "";
      var agBMs = MOCK.benchmarks.filter(function (b) { return b.agent_key === agKey; });
      var nTagged = MOCK.agent_tagged[agKey] || 0;
      data = { status: "ok", agent_key: agKey, n_tagged: nTagged, benchmarks: agBMs };
    } else if (method === "POST" && path0 === "override") {
      var ob = body || {};
      var okey = [ob.run_id, ob.question_id, ob.agent_key || "", ob.mode || ""].join("|");
      if (ob.verdict === "correct" || ob.verdict === "incorrect") {
        mockOverrides[okey] = { verdict: ob.verdict, comment: ob.comment || "", reviewed_by: "preview.admin", reviewed_at: "2026-06-26 10:15:00" };
      } else {
        delete mockOverrides[okey];
      }
      data = { status: "ok", matched: 1 };
    } else if (method === "GET" && path0 === "settings") {
      data = { status: "ok", settings: deepCopy(MOCK.settings) };
    } else if (method === "POST" && path0 === "settings") {
      var sBody = body || {};
      // Validation preview: an unknown golden dataset name fails with a field-level error,
      // mirroring the backend POST /api/settings that probes the dataset before saving.
      if ((sBody.golden_dataset || "").trim() === "badname") {
        status = 400;
        data = { status: "error", error: "invalid_settings", errors: { golden_dataset: "Dataset not found. Check the dataset name in OWIsMind_LAB." } };
      } else {
        if (sBody.golden_dataset) { MOCK.settings.golden_dataset = sBody.golden_dataset; }
        if (sBody.judge_llm_id) { MOCK.settings.judge_llm_id = sBody.judge_llm_id; }
        if (sBody.concurrency) { MOCK.settings.concurrency = parseInt(sBody.concurrency, 10) || MOCK.settings.concurrency; }
        if (sBody.run_language) { MOCK.settings.run_language = sBody.run_language; }
        data = { status: "ok", settings: deepCopy(MOCK.settings) };
      }
    } else {
      status = 404;
      data = { status: "error", error: "not_found" };
    }
    // A mock branch can carry an HTTP-ish status on the payload (_status); lift it onto the response.
    if (data && data._status) { status = data._status; delete data._status; }
    return new Promise(function (resolve) { setTimeout(function () { resolve({ status: status, data: data }); }, 120); });
  }

  function deepCopy(obj) { return JSON.parse(JSON.stringify(obj)); }

  // Recompute a benchmark's ledger/runnable (detail + list row) after a mock mutation.
  function mockSyncBench(bid) {
    var d = MOCK.bench_detail[bid];
    if (!d) { return; }
    var modes = d.modes || [];
    var qs = d.questions || [];
    var tested = 0, pending = 0, redo = 0, runnable = 0;
    qs.forEach(function (q) {
      var cells = q.cells || [];
      var allTested = cells.length === modes.length && cells.every(function (c) { return c.status === "tested"; });
      var hasPending = cells.some(function (c) { return c.status !== "tested"; });
      if (allTested && !q.redo) { tested += 1; }
      if (hasPending) { pending += 1; }
      if (q.redo) { redo += 1; }
      runnable += q.redo ? modes.length : cells.filter(function (c) { return c.status !== "tested"; }).length;
    });
    d.ledger = { tested: tested, pending: pending, redo: redo };
    d.runnable = runnable;
    MOCK.benchmarks.forEach(function (b) {
      if (b.benchmark_id === bid) {
        b.n_questions = qs.length; b.n_done = tested; b.n_pending = pending;
        b.n_redo = redo; b.name = d.name; b.modes = modes.slice();
      }
    });
  }

  function mockBenchCreate(body) {
    var name = (body.name || "").trim();
    var agKey = (body.agent_key || "").trim();
    if (!name) { return { _status: 400, status: "error", error: "invalid_benchmark", messages: ["name is required"] }; }
    var nTagged = MOCK.agent_tagged[agKey] || 0;
    if (nTagged === 0) { return { _status: 400, status: "error", error: "no_tagged_questions" }; }
    // Per-agent name uniqueness
    if (MOCK.benchmarks.some(function (b) { return b.agent_key === agKey && b.name.toLowerCase() === name.toLowerCase(); })) {
      return { _status: 400, status: "error", error: "invalid_benchmark", messages: ["a benchmark named '" + name + "' already exists for this agent"] };
    }
    var ag = MOCK.agent_catalog.agents.filter(function (a) { return a.agent_key === agKey; })[0];
    if (!ag) { return { _status: 400, status: "error", error: "unknown_agent" }; }
    var bid = "bm_" + Math.random().toString(36).slice(2, 8);
    var modes = body.modes && body.modes.length ? body.modes : (ag.modes ? ["Smart"] : ["default"]);
    // Auto-membership: active golden questions tagged to this agent
    var qids = MOCK.golden.filter(function (g) { return g.active && g.agent_key === agKey; }).map(function (g) { return g.question_id; });
    var questions = qids.map(function (qid) {
      var g = MOCK.golden.filter(function (x) { return x.question_id === qid; })[0] || {};
      return { question_id: qid, question: g.question || qid, category: g.category || "",
        expected_sql: g.expected_sql || "", expected_tool: g.expected_tool || "",
        redo: false, cells: modes.map(function (m) { return { mode: m, status: "pending", verdict: "" }; }) };
    });
    var agentInfo = { agent_key: ag.agent_key, agent_label: ag.agent_label, project_key: ag.project_key, agent_id: ag.agent_id };
    MOCK.bench_detail[bid] = { benchmark_id: bid, name: name, agent: agentInfo,
      modes: modes, ledger: { tested: 0, pending: questions.length, redo: 0 },
      runnable: questions.length * modes.length, accuracy_pct: "-", questions: questions };
    MOCK.benchmarks.unshift({ benchmark_id: bid, name: name, agent_key: ag.agent_key, agent_label: ag.agent_label,
      modes: modes, status: "active", created_at: new Date().toISOString(), n_questions: questions.length, n_done: 0,
      n_pending: questions.length, n_redo: 0, n_scored: 0, n_runs: 0, last_run_timestamp: "", accuracy: 0, accuracy_pct: "-", band: "none" });
    return { status: "ok", benchmark_id: bid, name: name, n_questions: questions.length };
  }

  // Run a mutation against one benchmark's mock detail, then resync counts. ``fn(detail, body)`` may
  // return ``{_err:[...]}`` to surface a validation error like the backend.
  function mockBenchMutate(body, fn) {
    var bid = (body && body.benchmark_id) || "";
    var d = MOCK.bench_detail[bid];
    if (!d) { return { _status: 404, status: "error", error: "unknown_benchmark" }; }
    var res = fn(d, body || {}) || {};
    if (res._err) { return { _status: 400, status: "error", error: "invalid_request", messages: res._err }; }
    mockSyncBench(bid);
    return { status: "ok", ...res };
  }

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
        '<header class="header">' +
          '<div class="header-brand">' +
            '<p class="eyebrow" data-i18n="hdr.eyebrow"></p>' +
            '<h1 data-i18n="hdr.h1"></h1>' +
            '<div class="title-bar"></div>' +
          '</div>' +
          '<nav class="hdr-links">' +
            '<button class="hdr-link" id="linkGolden" data-i18n="hdr.link.golden"></button>' +
            '<button class="hdr-link" id="linkSuggest" data-i18n="hdr.link.suggest"></button>' +
            '<button class="hdr-link" id="linkReview" data-i18n="hdr.link.review"></button>' +
          '</nav>' +
          '<div class="controls">' +
            '<div class="seg" id="langSeg"><button data-lang="en">EN</button><button data-lang="fr">FR</button></div>' +
            '<button class="btn-gear" id="themeBtn" title="Toggle theme" aria-label="Toggle theme">' + I.theme + '</button>' +
            '<button class="btn-gear" id="gearBtn" title="Settings" aria-label="Settings">' + I.gear + '</button>' +
          '</div>' +
        '</header>' +
        '<div id="gsStrip" class="gs-strip" style="display:none"></div>' +
        '<div class="body">' +
          '<section class="panel on" data-panel="benchmarks">' +
            '<nav class="rail" id="agentsRail"></nav>' +
            '<div class="detail-pane" id="detailPane">' +
              '<div class="breadcrumb" id="breadcrumb"></div>' +
              '<div id="detailContent"></div>' +
            '</div>' +
          '</section>' +
          '<section class="panel" data-panel="golden">' +
            '<div class="aux-back"><button class="btn btn-ghost btn-sm" id="goldenBack" data-i18n="hdr.back"></button></div>' +
            '<div id="goldenContent"></div>' +
          '</section>' +
          '<section class="panel" data-panel="suggest">' +
            '<div class="aux-back"><button class="btn btn-ghost btn-sm" id="suggestBack" data-i18n="hdr.back"></button></div>' +
            '<div id="suggestContent"></div>' +
          '</section>' +
          '<section class="panel" data-panel="review">' +
            '<div class="aux-back"><button class="btn btn-ghost btn-sm" id="reviewBack" data-i18n="hdr.back"></button></div>' +
            '<div id="reviewContent"></div>' +
          '</section>' +
        '</div>' +
        '<footer class="data-footer" id="dataFooter"></footer>' +
      '</div>' +
      modalHtml() +
      '<div class="toast" id="toast">' + I.check + '<span id="toastMsg"></span></div>' +
      '<div class="settings-panel" id="settingsPanel" aria-hidden="true">' +
        '<div class="settings-head">' +
          '<span class="settings-title" data-i18n="st.title"></span>' +
          '<button class="btn btn-ghost btn-sm" id="settingsClose" data-i18n="st.close"></button>' +
        '</div>' +
        '<div class="settings-body" id="settingsBody"></div>' +
      '</div>' +
      '<div class="settings-overlay" id="settingsOverlay"></div>';
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
          '<label class="field full"><span class="field-label" data-i18n="md.sql"></span><textarea class="input mono" id="msql"></textarea></label>' +
          '<p class="field-help" data-i18n="md.sqlHelp" style="grid-column:1 / -1;margin:0"></p>' +
          '<label class="field"><span class="field-label" data-i18n="md.tool"></span>' +
            '<input class="input mono" id="mtool" list="toolList" autocomplete="off"><datalist id="toolList">' +
              '<option value="show_chart"></option><option value="show_table"></option><option value="none"></option></datalist></label>' +
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

    ensureShell();
    applyI18n();
    syncSeg("langSeg", "data-lang", ui.lang);
    setTabUI(S.tab);

    // Agent-first master-detail (benchmarks panel)
    renderAgentsRail();
    renderBreadcrumb();
    renderDetailContent();
    renderGettingStarted();
    renderDataFooter();

    // Auxiliary panels (shown via header links)
    renderGolden();
    renderSuggestions();
    renderReview();
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
    // The global launch button is gone (launching is per benchmark): this block is run info only.
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
        '<col class="c-status"><col class="c-q"><col class="c-a"><col class="c-anchor"><col class="c-ref"><col class="c-cat"><col class="c-lang"><col class="c-act">' +
      '</colgroup><thead><tr>' +
        '<th>' + esc(t("th.status")) + '</th><th>' + esc(t("th.q")) + '</th><th>' + esc(t("th.a")) + '</th>' +
        '<th>' + esc(t("th.anchor")) + '</th><th>' + esc(t("th.ref")) + '</th><th>' + esc(t("th.cat")) + '</th><th>' + esc(t("th.lang")) + '</th><th>' + esc(t("th.act")) + '</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table>';
  }

  // The reference SQL / tool cell (soft judge signal): a truncated mono SQL + a tool tag, or a dash.
  function qRefHtml(g) {
    var sql = (g.expected_sql == null) ? "" : String(g.expected_sql).trim();
    var tool = (g.expected_tool == null) ? "" : String(g.expected_tool).trim();
    if (!sql && !tool) { return '<span class="anchor-none">' + esc(t("common.dash")) + '</span>'; }
    var html = "";
    if (sql) { html += '<code class="ref-sql">' + esc(truncate(sql, 90)) + '</code>'; }
    if (tool) { html += '<span class="ref-tool">' + esc(tool) + '</span>'; }
    return html;
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
      '<td data-l="' + esc(t("th.ref")) + '">' + qRefHtml(g) + '</td>' +
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
    byId("msql").value = g ? (g.expected_sql || "") : "";
    byId("mtool").value = g ? (g.expected_tool || "") : "";
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
      notes: editorNotes(),
      // v2: reference SQL / tool (soft judge signal + training data).
      expected_sql: byId("msql").value.trim(),
      expected_tool: byId("mtool").value.trim()
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
      active: !g.active, notes: g.notes || "",
      expected_sql: g.expected_sql || "", expected_tool: g.expected_tool || ""
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

  /* ============================ benchmarks (v2): list + detail + launch ============================ */

  function renderBenchmarks() {
    var box = byId("benchContent");
    if (!box) { return; }
    if (S.bench.view === "detail") {
      box.innerHTML = benchDetailWrapHtml();
    } else {
      var inner;
      if (S.bench.loadError) {
        inner = '<div class="note note-error" role="alert">' + esc(t("bm.loadError")) + '</div>' +
          '<div class="actions-row"><button type="button" class="btn" data-bm="retry">' + esc(t("common.retry")) + '</button></div>';
      } else if (!S.bench.loaded) {
        inner = '<p class="loading">' + esc(t("common.loading")) + '</p>';
      } else {
        inner = benchListHtml();
      }
      box.innerHTML = '' +
        '<div class="sec-head">' +
          '<p class="sec-eyebrow">' + esc(t("bm.eyebrow")) + '</p>' +
          '<h2 class="sec-title">' + esc(t("bm.title")) + '</h2>' +
          '<div class="title-bar"></div>' +
          '<p class="sec-note">' + esc(t("bm.note")) + '</p>' +
        '</div>' + inner;
    }
    wireBench(box);
  }

  function benchListHtml() {
    var list = S.bench.list;
    var head = '<div class="table-head">' +
      '<span class="count-line">' + t("bm.count", { n: "<b>" + fmtNum(list.length) + "</b>" }) + '</span>' +
      '<button class="btn btn-primary btn-sm" data-bm="new"><span class="ic-plus"></span>' + esc(t("bm.new")) + '</button>' +
      '</div>';
    if (!list.length) {
      return head + '<div class="empty"><div class="ei"><span class="ic-grid"></span></div>' +
        '<h4>' + esc(t("bm.empty.h")) + '</h4><p>' + esc(t("bm.empty.p")) + '</p></div>';
    }
    return head + '<div class="bm-list">' + list.map(benchCardHtml).join("") + '</div>';
  }

  function benchCardHtml(b) {
    var band = b.band || "none";
    var last = b.last_run_timestamp ? esc(b.last_run_timestamp) : esc(t("bm.never"));
    var redo = b.n_redo ? '<span class="bm-badge redo">' + esc(t("bm.badge.redo", { n: fmtNum(b.n_redo) })) + '</span>' : '';
    var modes = (b.modes && b.modes.length) ? '<span class="bm-modes">' + b.modes.map(esc).join(", ") + '</span>' : '';
    return '<div class="bm-card">' +
      '<div class="bm-card-main">' +
        '<div class="bm-card-head"><h3 class="bm-name">' + esc(b.name) + '</h3>' +
          (b.status === "archived" ? '<span class="bm-arch">' + esc(t("bm.archived")) + '</span>' : '') + '</div>' +
        '<p class="bm-agent">' + esc(b.agent_label) + ' ' + modes + '</p>' +
        '<div class="bm-badges">' +
          '<span class="bm-badge done">' + esc(t("bm.badge.done", { n: fmtNum(b.n_done) })) + '</span>' +
          '<span class="bm-badge pending">' + esc(t("bm.badge.pending", { n: fmtNum(b.n_pending) })) + '</span>' +
          redo +
        '</div>' +
      '</div>' +
      '<div class="bm-card-side">' +
        '<div class="bm-accwrap"><span class="bm-acclabel">' + esc(t("bm.accuracy")) + '</span>' +
          '<span class="bm-acc band-' + band + '">' + esc(b.accuracy_pct || "-") + '</span></div>' +
        '<div class="bm-last">' + esc(t("bm.lastRun")) + ': <b>' + last + '</b></div>' +
        '<button class="btn btn-sm" data-bm="open" data-id="' + esc(b.benchmark_id) + '">' + esc(t("bm.open")) + '</button>' +
      '</div>' +
    '</div>';
  }

  function benchDetailWrapHtml() {
    var top = '<div class="bd-top"><button class="btn btn-sm btn-ghost" data-bm="back"><span class="ic-back"></span>' + esc(t("bd.back")) + '</button></div>';
    if (S.bench.detailError) {
      return top + '<div class="note note-error" role="alert">' + esc(t("bd.loadError")) + '</div>' +
        '<div class="actions-row"><button type="button" class="btn" data-bm="detail-retry">' + esc(t("common.retry")) + '</button></div>';
    }
    if (!S.bench.detailLoaded || !S.bench.detail) {
      return top + '<p class="loading">' + esc(t("common.loading")) + '</p>';
    }
    return benchDetailHtml(S.bench.detail);
  }

  function benchDetailHtml(d) {
    var canPending = ((d.n_pending || 0) + (d.n_redo || 0)) > 0;
    var nameBlock;
    if (S.bench.renaming) {
      nameBlock = '<div class="bd-rename"><input class="input" id="bdRenameInput" value="' + esc(d.name) + '" aria-label="' + esc(t("bn.name")) + '">' +
        '<button class="btn btn-sm btn-primary" data-bm="rename-save">' + esc(t("bd.renameSave")) + '</button>' +
        '<button class="btn btn-sm" data-bm="rename-cancel">' + esc(t("bd.renameCancel")) + '</button></div>';
    } else {
      nameBlock = '<div class="bd-titlewrap"><h2 class="sec-title">' + esc(d.name) + '</h2>' +
        '<button class="btn btn-sm btn-ghost" data-bm="rename">' + esc(t("bd.rename")) + '</button></div>';
    }
    var modesLine = (d.modes && d.modes.length) ? ('  <b>' + esc(t("bd.modes")) + ':</b> ' + d.modes.map(esc).join(", ")) : "";
    var header = '<div class="sec-head">' +
      '<p class="sec-eyebrow">' + esc(t("bm.eyebrow")) + '</p>' + nameBlock +
      '<div class="title-bar"></div>' +
      '<p class="bd-agentline"><b>' + esc(t("bd.agent")) + ':</b> ' + esc(d.agent_label) + modesLine + '</p>' +
      '<div class="bm-badges" style="margin-top:12px">' +
        '<span class="bm-badge done">' + esc(t("bm.badge.done", { n: fmtNum(d.n_done) })) + '</span>' +
        '<span class="bm-badge pending">' + esc(t("bm.badge.pending", { n: fmtNum(d.n_pending) })) + '</span>' +
        (d.n_redo ? '<span class="bm-badge redo">' + esc(t("bm.badge.redo", { n: fmtNum(d.n_redo) })) + '</span>' : '') +
      '</div>' +
    '</div>';
    var launch = '<div class="bd-launch">' +
      '<button class="btn btn-primary" data-bm="run-pending"' + (canPending && !S.bench.running ? "" : " disabled") + '>' +
        '<span class="ic-play"></span>' + esc(t("bd.runPending")) + '</button>' +
      '<button class="btn" data-bm="run-full"' + (S.bench.running ? " disabled" : "") + '>' + esc(t("bd.runFull")) + '</button>' +
      (!canPending ? '<span class="bd-hint">' + esc(t("bd.runPendingHint")) + '</span>' : "") +
    '</div>';
    var qSection = (d.questions && d.questions.length)
      ? '<div class="bd-list">' + d.questions.map(benchQCardHtml).join("") + '</div>'
      : '<div class="note note-info" role="status">' + esc(t("bd.empty")) + '</div>';
    return '<div class="bd-top"><button class="btn btn-sm btn-ghost" data-bm="back"><span class="ic-back"></span>' + esc(t("bd.back")) + '</button></div>' +
      header + launch + benchRunStatusHtml() +
      '<div class="bd-qhead"><p class="glabel">' + esc(t("bd.qTitle")) + '</p></div>' +
      qSection + benchAddHtml(d);
  }

  function benchRunStatusHtml() {
    if (S.bench.running) {
      return '<div class="bd-run"><span class="dot"></span>' + esc(t("run.btn.running")) + '</div>';
    }
    if (S.bench.runMsg) {
      return '<div class="run-msg ' + (S.bench.runMsg.kind === "ok" ? "ok" : "err") + '" style="margin-top:14px">' + esc(S.bench.runMsg.text) + '</div>';
    }
    return "";
  }

  // The question-level evolution delta = the strongest signal across its modes (regressed wins,
  // then improved, then stable); 'first' when no mode has more than one attempt.
  function questionDelta(q) {
    var ds = (q.modes || []).filter(function (m) { return m.attempts && m.attempts.length > 1; })
      .map(function (m) { return m.delta; });
    if (ds.indexOf("regressed") !== -1) { return "regressed"; }
    if (ds.indexOf("improved") !== -1) { return "improved"; }
    if (ds.indexOf("same") !== -1) { return "same"; }
    return "first";
  }

  function qVerdictChip(q) {
    if (q.status !== "done" || !q.latest_verdict) {
      return '<span class="bd-vd none">' + esc(t("bd.verdict.none")) + '</span>';
    }
    var ok = !!q.latest_correct;
    return '<span class="bd-vd ' + (ok ? "correct" : "incorrect") + '">' +
      esc(t(ok ? "bd.verdict.correct" : "bd.verdict.incorrect")) + '</span>';
  }

  function attemptHistoryHtml(q) {
    var modes = q.modes || [];
    if (!modes.length) { return ""; }
    var blocks = modes.map(function (m) {
      var atts = (m.attempts || []).map(function (a) {
        var ok = !!a.correct;
        var score = (a.judge_score != null && a.judge_score !== "") ? (" · " + fmtNum(a.judge_score)) : "";
        var ovr = a.overridden ? (" · " + t("rv.effective")) : "";
        return '<span class="bd-att-chip ' + (ok ? "correct" : "incorrect") + '">' +
          esc(t("bd.attempt", { n: a.attempt_no })) + esc(score) + esc(ovr) + '</span>';
      }).join("");
      return '<div class="bd-evo-mode"><span class="bd-evo-modelabel">' + esc(m.mode || t("common.dash")) + '</span>' +
        '<div class="bd-att-row">' + atts + '</div></div>';
    }).join("");
    return '<div class="bd-evo-body">' + blocks + '</div>';
  }

  function benchQCardHtml(q) {
    var expanded = !!S.bench.expanded[q.question_id];
    var statusCls = (q.status === "done") ? "done" : "pending";
    var delta = questionDelta(q);
    var deltaBadge = (q.n_attempts > 1 && delta !== "first")
      ? '<span class="bd-delta ' + delta + '">' + esc(t("bd.delta." + delta)) + '</span>' : "";
    var attemptsLine = q.n_attempts ? '<span class="bd-att">' + esc(t("bd.attempts", { n: fmtNum(q.n_attempts) })) + '</span>' : "";

    var sql = (q.expected_sql == null) ? "" : String(q.expected_sql).trim();
    var tool = (q.expected_tool == null) ? "" : String(q.expected_tool).trim();
    var ref;
    if (sql || tool) {
      ref = '<div class="bd-ref">' +
        (sql ? '<div class="bd-ref-row"><span class="bd-ref-l">' + esc(t("bd.refSql")) + '</span><code class="bd-ref-sql">' + esc(sql) + '</code></div>' : "") +
        (tool ? '<div class="bd-ref-row"><span class="bd-ref-l">' + esc(t("bd.refTool")) + '</span><span class="ref-tool">' + esc(tool) + '</span></div>' : "") +
        '</div>';
    } else {
      ref = '<div class="bd-ref"><span class="bd-ref-none">' + esc(t("bd.refNone")) + '</span></div>';
    }

    var evo = "";
    if (q.n_attempts > 0) {
      evo = '<div class="bd-evo">' +
        '<button type="button" class="bd-evo-toggle" data-bm="evo" data-id="' + esc(q.question_id) + '">' +
          esc(expanded ? t("bd.evoHide") : t("bd.evoShow")) + '</button>' +
        (expanded ? attemptHistoryHtml(q) : "") + '</div>';
    }

    var redoOn = !!q.include_next;
    var controls = '<div class="bd-controls">' +
      '<button type="button" class="chk' + (redoOn ? " on" : "") + '" data-bm="redo" data-id="' + esc(q.question_id) + '" data-val="' + (redoOn ? "0" : "1") + '">' +
        '<span class="box">' + I.check + '</span><span class="chk-txt"><b>' + esc(t("bd.redo")) + '</b></span></button>' +
      '<button type="button" class="btn btn-sm btn-danger" data-bm="remove" data-id="' + esc(q.question_id) + '">' + esc(t("bd.remove")) + '</button>' +
    '</div>';

    return '<div class="bd-card">' +
      '<div class="bd-card-head"><p class="bd-q">' + esc(q.question || q.question_id) + '</p>' +
        '<div class="bd-badges"><span class="bd-status ' + statusCls + '">' + esc(t("bd.status." + statusCls)) + '</span>' +
          qVerdictChip(q) + deltaBadge + '</div></div>' +
      '<div class="bd-meta">' + (q.category ? '<span class="cat-tag">' + esc(q.category) + '</span>' : "") + attemptsLine + '</div>' +
      ref + evo + controls +
    '</div>';
  }

  function benchAddHtml(d) {
    var memberIds = {};
    (d.questions || []).forEach(function (q) { memberIds[q.question_id] = true; });
    var pool = (S.bench.golden || []).filter(function (g) { return g.question_id && !memberIds[g.question_id]; });
    var head = '<div class="bd-add-head"><div>' +
      '<p class="glabel">' + esc(t("bd.addTitle")) + '</p>' +
      '<p class="ghelp" style="margin:0">' + esc(t("bd.addNote")) + '</p></div>' +
      '<button type="button" class="btn btn-sm" data-bm="add-toggle">' + esc(t("bd.addToggle")) + '</button></div>';
    if (!S.bench.addOpen) {
      return '<div class="card bd-add"><div class="card-pad">' + head + '</div></div>';
    }
    var body;
    if (!pool.length) {
      body = '<div class="note note-info" role="status">' + esc(t("bd.addNone")) + '</div>';
    } else {
      var items = pool.map(function (g) {
        var checked = S.bench.addSel[g.question_id] ? " checked" : "";
        return '<label class="bd-add-item"><input type="checkbox" data-addq="' + esc(g.question_id) + '"' + checked + '>' +
          '<span class="bd-add-q">' + esc(truncate(g.question, 140)) + '</span>' +
          (g.category ? '<span class="cat-tag">' + esc(g.category) + '</span>' : "") + '</label>';
      }).join("");
      var hasSel = pool.some(function (g) { return !!S.bench.addSel[g.question_id]; });
      body = '<div class="bd-add-list">' + items + '</div>' +
        '<div class="actions-row"><button class="btn btn-primary btn-sm" id="benchAddGo" data-bm="add-go"' + (hasSel ? "" : " disabled") + '>' + esc(t("bd.addSelected")) + '</button>' +
        '<button class="btn btn-sm" data-bm="add-cancel">' + esc(t("bd.addCancel")) + '</button></div>';
    }
    return '<div class="card bd-add"><div class="card-pad">' + head + body + '</div></div>';
  }

  function wireBench(box) {
    if (!box) { return; }
    qsa(".ic-plus", box).forEach(function (e) { e.innerHTML = I.plus; });
    qsa(".ic-grid", box).forEach(function (e) { e.innerHTML = I.grid; });
    qsa(".ic-play", box).forEach(function (e) { e.innerHTML = I.play; });
    qsa(".ic-back", box).forEach(function (e) { e.innerHTML = I.back; });

    qsa("[data-addq]", box).forEach(function (cb) {
      cb.addEventListener("change", function () {
        S.bench.addSel[cb.getAttribute("data-addq")] = cb.checked;
        var go = byId("benchAddGo");
        if (go) {
          var any = Object.keys(S.bench.addSel).some(function (k) { return S.bench.addSel[k]; });
          go.disabled = !any;
        }
      });
    });

    qsa("[data-bm]", box).forEach(function (el) {
      var kind = el.getAttribute("data-bm");
      var id = el.getAttribute("data-id");
      el.addEventListener("click", function () {
        if (kind === "new") { openBenchModal(); }
        else if (kind === "open") { openBenchmark(id); }
        else if (kind === "retry") { loadBenchmarks(); }
        else if (kind === "back") { backToList(); }
        else if (kind === "detail-retry") { loadBenchDetail(); }
        else if (kind === "rename") { S.bench.renaming = true; renderBenchmarks(); setTimeout(function () { var i = byId("bdRenameInput"); if (i) { i.focus(); } }, 30); }
        else if (kind === "rename-cancel") { S.bench.renaming = false; renderBenchmarks(); }
        else if (kind === "rename-save") { var inp = byId("bdRenameInput"); benchRename(inp ? inp.value : ""); }
        else if (kind === "run-pending") { benchLaunch("append"); }
        else if (kind === "run-full") { benchLaunch("full"); }
        else if (kind === "evo") { S.bench.expanded[id] = !S.bench.expanded[id]; renderBenchmarks(); }
        else if (kind === "redo") { benchRedo(id, el.getAttribute("data-val")); }
        else if (kind === "remove") { benchRemove(id); }
        else if (kind === "add-toggle") { S.bench.addOpen = !S.bench.addOpen; S.bench.addSel = {}; renderBenchmarks(); }
        else if (kind === "add-cancel") { S.bench.addOpen = false; S.bench.addSel = {}; renderBenchmarks(); }
        else if (kind === "add-go") { benchAddSelected(); }
      });
    });
  }

  function loadBenchmarks() {
    S.bench.loadError = false;
    if (!S.bench.loaded) { renderBenchmarks(); }
    callApi("GET", "benchmarks").then(function (res) {
      var d = res.data || {};
      if (d.status === "ok") {
        S.bench.list = (d.benchmarks || []).slice();
        S.bench.agents = (d.agents || []).slice();
        S.bench.modeOptions = (d.modes || []).slice();
        S.bench.golden = (d.golden || []).slice();
        S.bench.loaded = true;
        S.bench.loadError = false;
      } else {
        S.bench.loadError = true;
      }
      setText("tabBenchCount", S.bench.loaded ? String(S.bench.list.length) : "");
      renderBenchmarks();
    }, function () { S.bench.loadError = true; renderBenchmarks(); });
  }

  function openBenchmark(bid) {
    S.bench.view = "detail";
    S.bench.detailId = bid;
    S.bench.detail = null;
    S.bench.detailLoaded = false;
    S.bench.detailError = false;
    S.bench.renaming = false;
    S.bench.addOpen = false;
    S.bench.addSel = {};
    S.bench.expanded = {};
    S.bench.runMsg = null;
    renderBenchmarks();
    loadBenchDetail();
  }

  function loadBenchDetail() {
    S.bench.detailError = false;
    callApi("GET", "benchmark/detail?benchmark_id=" + encodeURIComponent(S.bench.detailId)).then(function (res) {
      var d = res.data || {};
      // The detail response merges the benchmark entity, whose own ``status`` (active/archived)
      // shadows the envelope ``status``; so success = HTTP 200 + a benchmark_id + no error code.
      if (res.status === 200 && d.benchmark_id && !d.error) {
        S.bench.detail = d;
        S.bench.detailLoaded = true;
        S.bench.detailError = false;
      } else {
        S.bench.detailError = true;
      }
      renderBenchmarks();
    }, function () { S.bench.detailError = true; renderBenchmarks(); });
  }

  function backToList() {
    S.bench.view = "list";
    S.bench.detailId = "";
    S.bench.detail = null;
    S.bench.runMsg = null;
    renderBenchmarks();
    loadBenchmarks();  // refresh counts / accuracy after any launch
  }

  function benchLaunch(mode) {
    if (S.bench.running) { return; }
    S.bench.running = true;
    S.bench.runMsg = null;
    setStatus("running");
    renderBenchmarks();
    callApi("POST", "benchmark/launch", { benchmark_id: S.bench.detailId, launch_mode: mode }).then(function (res) {
      var d = res.data || {};
      if (d.status === "ok" && d.launched) {
        toast(t("run.launched"));
        benchPoll();
      } else if (res.status === 409 || d.error === "already_running") {
        S.bench.runMsg = { kind: "err", text: t("run.already") };
        renderBenchmarks();
        benchPoll();
      } else if (d.error === "launch_unsupported") {
        benchEndRun({ kind: "err", text: t("run.unsupported") });
      } else if (d.error === "unknown_benchmark") {
        benchEndRun({ kind: "err", text: t("bd.loadError") });
      } else {
        benchEndRun({ kind: "err", text: t("run.error") });
      }
    }, function () { benchEndRun({ kind: "err", text: t("run.error") }); });
  }

  var benchPollErrors = 0;
  function benchPoll() {
    if (!S.bench.running) { return; }
    setTimeout(function () {
      callApi("GET", "run/status").then(function (res) {
        benchPollErrors = 0;
        var d = res.data || {};
        if (d.running) {
          benchPoll();
        } else {
          benchEndRun({ kind: "ok", text: t("run.finished") });
          loadBenchDetail();
        }
      }, function () {
        benchPollErrors += 1;
        if (benchPollErrors >= 4) { benchEndRun({ kind: "err", text: t("run.lostContact") }); }
        else { benchPoll(); }
      });
    }, 2500);
  }

  function benchEndRun(msg) {
    S.bench.running = false;
    S.bench.runMsg = msg || null;
    setStatus("done");
    renderBenchmarks();
  }

  function benchRedo(id, val) {
    callApi("POST", "benchmark/redo", { benchmark_id: S.bench.detailId, question_id: id, include_next: (val === "1") }).then(function (res) {
      var d = res.data || {};
      if (d.status === "ok") { loadBenchDetail(); }
      else { toast(t("bd.redoError")); }
    }, function () { toast(t("bd.redoError")); });
  }

  function benchRemove(id) {
    callApi("POST", "benchmark/remove-question", { benchmark_id: S.bench.detailId, question_id: id }).then(function (res) {
      var d = res.data || {};
      if (d.status === "ok") { toast(t("bd.removed")); loadBenchDetail(); }
      else { toast(t("bd.removeError")); }
    }, function () { toast(t("bd.removeError")); });
  }

  function benchAddSelected() {
    var ids = (S.bench.golden || [])
      .filter(function (g) { return S.bench.addSel[g.question_id]; })
      .map(function (g) { return g.question_id; });
    if (!ids.length) { return; }
    callApi("POST", "benchmark/add-questions", { benchmark_id: S.bench.detailId, question_ids: ids }).then(function (res) {
      var d = res.data || {};
      if (d.status === "ok") {
        toast(t("bd.added", { n: fmtNum(ids.length) }));
        S.bench.addOpen = false;
        S.bench.addSel = {};
        loadBenchDetail();
      } else {
        toast(t("bd.addError"));
      }
    }, function () { toast(t("bd.addError")); });
  }

  function benchRename(name) {
    name = (name || "").trim();
    if (!name) { S.bench.renaming = false; renderBenchmarks(); return; }
    callApi("POST", "benchmark/rename", { benchmark_id: S.bench.detailId, name: name }).then(function (res) {
      var d = res.data || {};
      if (d.status === "ok") {
        S.bench.renaming = false;
        toast(t("bd.renamed"));
        loadBenchDetail();
      } else {
        var msg = (d.messages && d.messages.length) ? d.messages[0] : t("bd.renameError");
        toast(msg);
      }
    }, function () { toast(t("bd.renameError")); });
  }

  /* --- new-benchmark modal --- */

  function benchSeedAll() {
    var a = byId("bnSeedAll");
    return !a || a.getAttribute("data-on") === "1";
  }
  function setBenchSeed(all) {
    var a = byId("bnSeedAll");
    var e = byId("bnSeedEmpty");
    if (a) { a.classList.toggle("on", all); a.setAttribute("data-on", all ? "1" : "0"); }
    if (e) { e.classList.toggle("on", !all); e.setAttribute("data-on", !all ? "1" : "0"); }
  }

  function openBenchModal() {
    S.benchNew.open = true;
    S.benchNew.error = null;
    var sel = byId("bnAgent");
    sel.innerHTML = (S.bench.agents || []).map(function (a) {
      return '<option value="' + esc(a.agent_key) + '">' + esc(a.agent_label || a.agent_key) + '</option>';
    }).join("");
    byId("bnName").value = "";
    var noAgents = !(S.bench.agents && S.bench.agents.length);
    setHTML("bnErr", noAgents ? '<div class="note note-error" role="alert">' + esc(t("bn.agentNone")) + '</div>' : "");
    var create = byId("bnCreate");
    if (create) { create.disabled = noAgents; }
    setBenchSeed(true);
    byId("benchOverlay").classList.add("on");
    setTimeout(function () { byId("bnName").focus(); }, 50);
  }

  function closeBenchModal() {
    S.benchNew.open = false;
    byId("benchOverlay").classList.remove("on");
  }

  function submitBenchModal() {
    var name = byId("bnName").value.trim();
    var agentKey = byId("bnAgent").value;
    var seedAll = benchSeedAll();
    setHTML("bnErr", "");
    var btn = byId("bnCreate");
    if (btn) { btn.disabled = true; }
    callApi("POST", "benchmark/create", { name: name, agent_key: agentKey, seed_all: seedAll }).then(function (res) {
      if (btn) { btn.disabled = false; }
      var d = res.data || {};
      if (d.status === "ok") {
        closeBenchModal();
        toast(t("bn.created"));
        loadBenchmarks();
        if (d.benchmark_id) { openBenchmark(d.benchmark_id); }
      } else {
        var msgs = d.messages || [t("bn.error")];
        setHTML("bnErr", '<div class="note note-error" role="alert"><strong>' + esc(t("save.invalidTitle")) + '</strong><ul>' +
          msgs.map(function (m) { return '<li>' + esc(m) + '</li>'; }).join("") + '</ul></div>');
      }
    }, function () {
      if (btn) { btn.disabled = false; }
      setHTML("bnErr", '<div class="note note-error" role="alert">' + esc(t("bn.error")) + '</div>');
    });
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

  // Stable identity of a scored row (v2): the review lists EVERY attempt, so the key includes this
  // attempt's run_id (+ attempt_no for safety) on top of (question_id, agent_key, mode). The override
  // sent to the backend is exactly that row's (run_id, question_id, agent_key, mode).
  function reviewRowKey(r) {
    return [r.run_id || "", r.question_id, r.agent_key || "", r.mode || "", r.attempt_no || ""].join("\u0001");
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
    } else if (!S.review.benchmarks.length) {
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
    var benchOpts = S.review.benchmarks.map(function (b) {
      var label = b.benchmark_name || b.benchmark_id;
      if (b.last_run_timestamp) { label += " (" + b.last_run_timestamp + ")"; }
      var seld = (b.benchmark_id === S.review.benchmarkId) ? " selected" : "";
      return '<option value="' + esc(b.benchmark_id) + '"' + seld + '>' + esc(label) + '</option>';
    }).join("");
    var bar = '' +
      '<div class="rvw-bar">' +
        '<label class="field rvw-runsel"><span class="field-label">' + esc(t("rv.bench")) + '</span>' +
          '<select class="input" id="rvwBench">' + benchOpts + '</select></label>' +
        '<button type="button" class="chk' + (S.review.onlyNeedsReview ? " on" : "") + '" id="rvwOnly">' +
          '<span class="box">' + I.check + '</span><span class="chk-txt"><b>' + esc(t("rv.onlyNeeds")) + '</b></span></button>' +
      '</div>';
    var caption = '<div class="note note-info" role="note">' + esc(t("rv.caption2")) + '</div>';

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
      (r.attempt_no ? '<span class="rvw-mode">' + esc(t("rv.attempt", { n: r.attempt_no })) + '</span>' : '') +
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

    var benchSel = byId("rvwBench");
    if (benchSel) {
      benchSel.addEventListener("change", function () {
        S.review.benchmarkId = benchSel.value;
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
    if (S.review.benchmarkId) { path += "&benchmark_id=" + encodeURIComponent(S.review.benchmarkId); }
    callApi("GET", path).then(function (res) {
      var d = res.data || {};
      if (d.status === "ok") {
        S.review.benchmarks = (d.benchmarks || []).slice();
        S.review.rows = (d.rows || []).slice();
        S.review.count = (typeof d.count === "number") ? d.count : S.review.rows.length;
        if (d.benchmark_id) { S.review.benchmarkId = d.benchmark_id; }
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
    // v2: override the SPECIFIC attempt -> send THIS row's run_id (not a single global run id).
    var payload = {
      run_id: row.run_id || "",
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
    if (tab === "benchmarks") { renderAgentsRail(); renderBreadcrumb(); renderDetailContent(); }
    if (tab === "golden" && !S.golden.loaded && !S.golden.loadError) { loadGolden(); }
    if (tab === "suggest" && !S.suggestions.loaded && !S.suggestions.loadError) { loadSuggestions(); }
    if (tab === "review" && !S.review.loaded && !S.review.loadError) { loadReview(); }
  }

  /* ============================ agent-first (dispatch 1) ============================ */

  var _agentDiscoverFired = false;  // ensure discover fires only once per page load

  function loadAgents() {
    S.agentCatalog.loaded = false;
    S.agentCatalog.loadError = false;
    render();  // build the shell (ensureShell) before the targeted rail renders below
    callApi("GET", "agents").then(function (res) {
      var d = res.data || {};
      if (res.status === 200 && d.status === "ok") {
        S.agentCatalog.agents = d.agents || [];
        S.agentCatalog.discovered_at = d.discovered_at || null;
        S.agentCatalog.loaded = true;
        S.agentCatalog.loadError = false;
      } else {
        S.agentCatalog.loaded = true;
        S.agentCatalog.loadError = true;
      }
      renderAgentsRail();
      renderGettingStarted();
      if (!_agentDiscoverFired) { _agentDiscoverFired = true; discoverAgents(); }
    }, function () {
      S.agentCatalog.loaded = true;
      S.agentCatalog.loadError = true;
      renderAgentsRail();
      if (!_agentDiscoverFired) { _agentDiscoverFired = true; discoverAgents(); }
    });
  }

  function discoverAgents() {
    S.agentCatalog.discovering = true;
    S.agentCatalog.discoveryFailed = false;
    renderAgentsRail();
    callApi("POST", "agents/discover").then(function (res) {
      var d = res.data || {};
      S.agentCatalog.discovering = false;
      if (res.status === 200 && d.status === "ok") {
        S.agentCatalog.agents = d.agents || S.agentCatalog.agents;
        S.agentCatalog.discovered_at = d.discovered_at || null;
        S.agentCatalog.discoveryFailed = false;
      } else {
        S.agentCatalog.discoveryFailed = true;
      }
      renderAgentsRail();
      renderGettingStarted();
    }, function () {
      S.agentCatalog.discovering = false;
      S.agentCatalog.discoveryFailed = true;
      renderAgentsRail();
    });
  }

  function navigateTo(level, agentKey, benchmarkId) {
    S.route = { level: level, agentKey: agentKey || null, benchmarkId: benchmarkId || null };
    if (level === "agent" && agentKey) {
      S.agentView = { loaded: false, loadError: false, agentKey: agentKey, n_tagged: 0, benchmarks: [],
        creating: false, submitting: false, createError: null, createName: "", createModes: [], bmDeleteConfirmId: "" };
    }
    if (level === "benchmark" && benchmarkId) {
      S_bench4ActiveBid = null;  // Fix 1: clear stale lock so other benchmarks are not false-locked
      S.benchDetailState = { loaded: false, loadError: false, detail: null, editModes: false, editModesValue: [], deleteConfirm: false, running: false, runMsg: null, runScored: 0, runTotal: 0, runStartedAt: null, runComplete: null, rerunConfirm: false, resetNeeded: false };
    }
    renderBreadcrumb();
    renderDetailContent();
    if (level === "agent" && agentKey) { loadAgentBenchmarks(agentKey); }
    if (level === "benchmark" && benchmarkId) { loadBenchmarkDetail4(benchmarkId); }
  }

  function loadAgentBenchmarks(agentKey) {
    callApi("GET", "agent/benchmarks?agent_key=" + encodeURIComponent(agentKey)).then(function (res) {
      if (S.route.agentKey !== agentKey) { return; }  // stale response
      var d = res.data || {};
      if (res.status === 200 && d.status === "ok") {
        S.agentView.n_tagged = d.n_tagged || 0;
        S.agentView.benchmarks = d.benchmarks || [];
        S.agentView.loaded = true;
        S.agentView.loadError = false;
      } else {
        S.agentView.loaded = true;
        S.agentView.loadError = true;
      }
      if (S.route.level === "agent" && S.route.agentKey === agentKey) { renderDetailContent(); renderGettingStarted(); }
    }, function () {
      if (S.route.agentKey !== agentKey) { return; }
      S.agentView.loaded = true;
      S.agentView.loadError = true;
      if (S.route.level === "agent") { renderDetailContent(); }
    });
  }

  function submitCreate() {
    var name = (S.agentView.createName || "").trim();
    if (!name) {
      S.agentView.createError = { text: t("cr.error") };
      renderDetailContent();
      return;
    }
    var agKey = S.route.agentKey;
    var modes = S.agentView.createModes.slice();
    // ``submitting`` is the in-flight flag (disables the button); ``creating`` keeps the form open.
    S.agentView.submitting = true;
    S.agentView.createError = null;
    renderDetailContent();
    callApi("POST", "benchmark/create", { name: name, agent_key: agKey, modes: modes }).then(function (res) {
      var d = res.data || {};
      S.agentView.submitting = false;
      if (res.status === 200 && d.status === "ok") {
        toast(t("cr.created"));
        S.agentView.creating = false;  // close the form, return to the list
        S.agentView.loaded = false;
        renderDetailContent();
        loadAgentBenchmarks(agKey);
      } else if (res.status === 400 && d.error === "no_tagged_questions") {
        // gate triggered server-side: keep the form open, swap to the tag action
        S.agentView.n_tagged = 0;
        S.agentView.createError = { text: t("cr.noTagged") };
        renderDetailContent();
      } else {
        var msg = (d.messages && d.messages.length) ? d.messages[0] : t("cr.error");
        S.agentView.createError = { text: msg };
        renderDetailContent();
      }
    }, function () {
      S.agentView.submitting = false;
      S.agentView.createError = { text: t("cr.error") };
      renderDetailContent();
    });
  }

  /* --- render helpers --- */

  function renderAgentsRail() {
    var box = byId("agentsRail");
    if (!box) { return; }
    var html = '<div class="rail-head"><span class="rail-title">' + esc(t("rail.title")) + '</span>' +
      '<button class="rail-refresh" id="refreshAgents">' + esc(t("rail.refresh")) + '</button></div>';

    if (S.agentCatalog.discovering) {
      html += '<div class="rail-status">' + esc(t("rail.discovering")) + '</div>';
    } else if (S.agentCatalog.discoveryFailed) {
      html += '<div class="rail-status rail-status--warn">' + esc(t("rail.failed")) + '</div>';
    }

    if (S.agentCatalog.loaded && !S.agentCatalog.discovering && !S.agentCatalog.discoveryFailed && S.agentCatalog.agents.length > 0) {
      html += '<div class="rail-status">' + esc(t("rail.discovered", { n: S.agentCatalog.agents.length })) + '</div>';
    }

    if (S.agentCatalog.loaded && !S.agentCatalog.agents.length) {
      html += '<div class="rail-empty">' + esc(t("rail.empty")) + '</div>';
    }

    S.agentCatalog.agents.forEach(function (ag) {
      var active = (S.route.level === "agent" || S.route.level === "benchmark") && S.route.agentKey === ag.agent_key;
      html += '<button class="rail-row' + (active ? " rail-row--active" : "") + '" data-rail-key="' + esc(ag.agent_key) + '">' +
        '<span class="rail-row-lbl">' + esc(ag.agent_label) + '</span>' +
      '</button>';
    });

    box.innerHTML = html;

    var refreshBtn = byId("refreshAgents");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", function () {
        _agentDiscoverFired = true;  // prevent the double-fire guard; this IS the re-fire
        discoverAgents();
      });
    }
    qsa("[data-rail-key]", box).forEach(function (btn) {
      btn.addEventListener("click", function () {
        navigateTo("agent", btn.getAttribute("data-rail-key"), null);
        renderAgentsRail();  // refresh active state
      });
    });
  }

  function renderBreadcrumb() {
    var box = byId("breadcrumb");
    if (!box) { return; }
    if (S.route.level === "home") { box.innerHTML = ""; return; }
    var agKey = S.route.agentKey;
    var agLabel = "";
    S.agentCatalog.agents.forEach(function (a) { if (a.agent_key === agKey) { agLabel = a.agent_label; } });

    if (S.route.level === "benchmark") {
      // 3-part: Agents / AgentLabel / BenchmarkName
      var det = S.benchDetailState && S.benchDetailState.detail;
      var bmName = det ? det.name : (S.route.benchmarkId || "");
      var html = '<button class="bcr-btn" id="bcrHome">' + esc(t("bcr.home")) + '</button>' +
        '<span class="bcr-sep">/</span>' +
        '<button class="bcr-btn" id="bcrAgent">' + esc(agLabel || agKey) + '</button>' +
        '<span class="bcr-sep">/</span>' +
        '<span class="bcr-cur">' + esc(bmName) + '</span>';
      box.innerHTML = html;
      var homeBtn2 = byId("bcrHome");
      if (homeBtn2) { homeBtn2.addEventListener("click", function () { navigateTo("home", null, null); renderAgentsRail(); }); }
      var agentBtn = byId("bcrAgent");
      if (agentBtn) { agentBtn.addEventListener("click", function () { navigateTo("agent", agKey, null); renderAgentsRail(); }); }
      return;
    }

    if (S.route.level === "golden-tag") {
      // 3-part: Agents / AgentLabel / Golden questions
      var det2 = S.benchDetailState && S.benchDetailState.detail;
      var bmName2 = det2 ? det2.name : (S.route.benchmarkId || "");
      var html2 = '<button class="bcr-btn" id="bcrHome">' + esc(t("bcr.home")) + '</button>' +
        '<span class="bcr-sep">/</span>' +
        '<button class="bcr-btn" id="bcrAgent">' + esc(agLabel || agKey) + '</button>' +
        (bmName2 ? '<span class="bcr-sep">/</span><button class="bcr-btn" id="bcrBench">' + esc(bmName2) + '</button>' : '') +
        '<span class="bcr-sep">/</span>' +
        '<span class="bcr-cur">' + esc(t("gt.title")) + '</span>';
      box.innerHTML = html2;
      var bcrHome3 = byId("bcrHome");
      if (bcrHome3) { bcrHome3.addEventListener("click", function () { navigateTo("home", null, null); renderAgentsRail(); }); }
      var bcrAgent3 = byId("bcrAgent");
      if (bcrAgent3) { bcrAgent3.addEventListener("click", function () { navigateTo("agent", agKey, null); renderAgentsRail(); }); }
      var bcrBench3 = byId("bcrBench");
      if (bcrBench3) {
        var _bBid = S.route.benchmarkId;
        bcrBench3.addEventListener("click", function () { navigateTo("benchmark", agKey, _bBid); });
      }
      return;
    }

    var html = '<button class="bcr-btn" id="bcrHome">' + esc(t("bcr.home")) + '</button>' +
      '<span class="bcr-sep">/</span>' +
      '<span class="bcr-cur">' + esc(agLabel || agKey) + '</span>';
    box.innerHTML = html;
    var homeBtn = byId("bcrHome");
    if (homeBtn) {
      homeBtn.addEventListener("click", function () { navigateTo("home", null, null); renderAgentsRail(); });
    }
  }

  function renderDetailContent() {
    var box = byId("detailContent");
    if (!box) { return; }
    if (S.route.level === "home") { box.innerHTML = ""; return; }
    if (S.route.level === "agent") { box.innerHTML = buildAgentViewHtml(); wireAgentView(); return; }
    if (S.route.level === "benchmark") { renderBenchmarkDetail(); return; }
    if (S.route.level === "golden-tag") { box.innerHTML = buildGoldenTagHtml(); wireGoldenTag(); return; }
  }

  function buildAgentViewHtml() {
    var av = S.agentView;
    var agKey = S.route.agentKey;
    var agLabel = "";
    S.agentCatalog.agents.forEach(function (a) { if (a.agent_key === agKey) { agLabel = a.agent_label; } });

    var html = '<div class="agv-head">' +
      '<h2 class="agv-title">' + esc(agLabel || agKey) + '</h2>';
    if (av.loaded) {
      html += '<span class="agv-tagged">' + esc(t("agv.nTagged", { n: av.n_tagged })) + '</span>';
    }
    html += '</div>';

    // Screen 3: create form (inline)
    if (av.creating) { return html + buildCreateFormHtml(av, agLabel || agKey); }

    // Determine gate using Journey helper (fall back to simple check)
    var gate = (typeof Journey !== "undefined" && typeof Journey.createGate === "function")
      ? Journey.createGate(av.loaded ? av.n_tagged : 1)
      : { canCreate: av.n_tagged > 0, primaryAction: av.n_tagged > 0 ? "create" : "tag" };

    // Screen 2: action bar
    html += '<div class="agv-bar">';
    if (gate.canCreate) {
      html += '<button class="btn btn-primary" id="newBenchBtn">' + esc(t("agv.new")) + '</button>';
    } else {
      html += '<button class="btn btn-primary" id="tagQuestionsBtn">' + esc(t("agv.2c.tag")) + '</button>' +
        '<button class="btn btn-ghost" disabled title="' + esc(t("agv.2c.locked")) + '">' + esc(t("agv.new")) + '</button>';
    }
    html += '</div>';

    if (!av.loaded) {
      html += '<div class="agv-loading">' + esc(t("common.loading")) + '</div>';
      return html;
    }
    if (av.loadError) {
      html += '<div class="note note-error">' + esc(t("agv.loadError")) + '</div>';
      return html;
    }

    // Determine list state using Journey helper
    var listState = (typeof Journey !== "undefined" && typeof Journey.benchmarkListState === "function")
      ? Journey.benchmarkListState({ benchmarks: av.benchmarks, n_tagged: av.n_tagged })
      : (av.benchmarks.length > 0 ? "list" : (av.n_tagged > 0 ? "empty_has_questions" : "empty_no_questions"));

    if (listState === "list") {
      html += '<div class="bm-list">';
      av.benchmarks.forEach(function (bm) {
        var acc = (bm.accuracy_pct && bm.accuracy_pct !== "-") ? '<span class="bm-acc">' + esc(bm.accuracy_pct) + '</span>' : "";
        var chips = '<span class="bm-chip bm-chip--done">' + esc(t("bm.badge.done", { n: bm.n_done })) + '</span>';
        if (bm.n_pending > 0) { chips += '<span class="bm-chip bm-chip--pending">' + esc(t("bm.badge.pending", { n: bm.n_pending })) + '</span>'; }
        if (bm.n_redo > 0)    { chips += '<span class="bm-chip bm-chip--redo">' + esc(t("bm.badge.redo", { n: bm.n_redo })) + '</span>'; }
        var isDelConfirm = (av.bmDeleteConfirmId === bm.benchmark_id);
        var cardFoot;
        if (isDelConfirm) {
          cardFoot = '<div class="bm-card-foot bm-card-foot--confirm">' +
            '<div class="bm-delete-confirm">' +
              '<p class="bm-delete-confirm-msg">' + esc(t("bm.deleteConfirm", { n: bm.name })) + '</p>' +
              '<div class="bm-delete-confirm-btns">' +
                '<button class="btn btn-danger btn-sm" data-bm-delete-go="' + esc(bm.benchmark_id) + '">' + esc(t("bm.delete")) + '</button>' +
                '<button class="btn btn-ghost btn-sm" data-bm-delete-cancel>' + esc(t("common.cancel")) + '</button>' +
              '</div>' +
            '</div>' +
          '</div>';
        } else {
          cardFoot = '<div class="bm-card-foot">' +
            '<span class="bm-card-modes">' + esc((bm.modes || []).join(", ")) + '</span>' +
            '<div style="display:flex;gap:8px">' +
              '<button class="btn btn-ghost btn-sm" data-bm-delete="' + esc(bm.benchmark_id) + '">' + esc(t("bm.delete")) + '</button>' +
              '<button class="btn btn-sm" data-bm-open="' + esc(bm.benchmark_id) + '">' + esc(t("bm.open")) + '</button>' +
            '</div>' +
          '</div>';
        }
        html += '<div class="bm-card">' +
          '<div class="bm-card-head"><span class="bm-card-name">' + esc(bm.name) + '</span>' + acc + '</div>' +
          '<div class="bm-card-chips">' + chips + '</div>' +
          cardFoot +
        '</div>';
      });
      html += '</div>';
    } else if (listState === "empty_has_questions") {
      html += '<div class="agv-empty"><h3>' + esc(t("agv.2b.h")) + '</h3><p>' + esc(t("agv.2b.p")) + '</p></div>';
    } else {
      html += '<div class="agv-empty">' +
        '<h3>' + esc(t("agv.2c.h")) + '</h3>' +
        '<p>' + esc(t("agv.2c.p")) + '</p>' +
        '<p class="agv-locked-note">' + esc(t("agv.2c.locked")) + '</p>' +
      '</div>';
    }

    html += '<div class="agv-footer-link"><button class="btn-link" id="agvTagLink">' + esc(t("agv.tagLink")) + '</button></div>';
    return html;
  }

  function buildCreateFormHtml(av, agLabel) {
    var modeOpts = ["Smart", "Pro", "Claude"];
    var modesHtml = modeOpts.map(function (m) {
      var on = av.createModes.indexOf(m) !== -1;
      return '<button type="button" class="chk' + (on ? " on" : "") + '" data-cr-mode="' + esc(m) + '">' +
        '<span class="box">' + I.check + '</span><span class="chk-txt"><b>' + esc(m) + '</b></span></button>';
    }).join("");

    var pendLine = av.n_tagged > 0
      ? '<p class="cr-pending">' + esc(t("cr.pending", { n: av.n_tagged })) + '</p>'
      : '<p class="cr-pending cr-pending--warn">' + esc(t("cr.noTagged")) + '</p>';

    var errHtml = av.createError ? '<div class="note note-error">' + esc(av.createError.text) + '</div>' : "";
    var canCreate = av.n_tagged > 0;
    var submitHtml = canCreate
      ? '<button class="btn btn-primary" id="crSubmit"' + (av.submitting ? ' disabled' : '') + '>' + esc(av.submitting ? t("common.loading") : t("cr.create")) + '</button>'
      : '<button class="btn btn-primary" id="crTagBtn">' + esc(t("cr.tag")) + '</button>';

    return '<div class="cr-form">' +
      '<div class="sec-head">' +
        '<p class="sec-eyebrow">' + esc(t("cr.eyebrow")) + '</p>' +
        '<h2 class="sec-title">' + esc(t("cr.title")) + '</h2>' +
      '</div>' +
      errHtml +
      '<div class="cr-agent-row"><span class="cr-agent-lbl">' + esc(t("cr.agent")) + '</span><span class="cr-agent-val">' + esc(agLabel) + '</span></div>' +
      '<label class="field full">' +
        '<span class="field-label">' + esc(t("cr.name")) + '</span>' +
        '<input class="input" id="crName" value="' + esc(av.createName) + '" placeholder="' + esc(t("cr.namePh")) + '" autocomplete="off">' +
        '<span class="field-help">' + esc(t("cr.nameHint")) + '</span>' +
      '</label>' +
      '<div class="field">' +
        '<span class="field-label">' + esc(t("cr.modes")) + '</span>' +
        '<div class="chk-stack" id="crModesGroup">' + modesHtml + '</div>' +
      '</div>' +
      pendLine +
      '<div class="cr-actions">' + submitHtml + '<button class="btn btn-ghost" id="crCancel">' + esc(t("cr.cancel")) + '</button></div>' +
    '</div>';
  }

  function wireAgentView() {
    var av = S.agentView;
    var agKey = S.route.agentKey;

    function goTag() {
      S.agentView.creating = false;
      // Navigate to Screen 6: golden agent-tagging in the detail pane
      S.goldenTag = { loaded: false, loadError: false, list: [], agents: [], scope: "agent", searchText: "", editRow: null, confirmDelete: null, saving: false, saveError: null };
      navigateTo("golden-tag", agKey, null);
      renderAgentsRail();
      loadGoldenTag();
    }

    // Screen 2 wiring
    var newBtn = byId("newBenchBtn");
    if (newBtn) {
      newBtn.addEventListener("click", function () {
        av.creating = true; av.createName = ""; av.createModes = ["Smart"]; av.createError = null;
        renderDetailContent();
      });
    }
    var tagBtn = byId("tagQuestionsBtn");
    if (tagBtn) { tagBtn.addEventListener("click", goTag); }
    var tagLink = byId("agvTagLink");
    if (tagLink) { tagLink.addEventListener("click", goTag); }
    qsa("[data-bm-open]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var bid = btn.getAttribute("data-bm-open");
        navigateTo("benchmark", agKey, bid);
        renderAgentsRail();
      });
    });

    // Delete benchmark: show inline confirm, then DELETE on confirm
    qsa("[data-bm-delete]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        av.bmDeleteConfirmId = btn.getAttribute("data-bm-delete");
        renderDetailContent();
      });
    });
    qsa("[data-bm-delete-cancel]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        av.bmDeleteConfirmId = "";
        renderDetailContent();
      });
    });
    qsa("[data-bm-delete-go]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var bid = btn.getAttribute("data-bm-delete-go");
        callApi("POST", "benchmark/delete", { benchmark_id: bid }).then(function (res) {
          av.bmDeleteConfirmId = "";
          if (res.status === 200 && res.data && res.data.status === "ok") {
            av.benchmarks = av.benchmarks.filter(function (b) { return b.benchmark_id !== bid; });
            toast(t("bm.deleted"));
          } else {
            toast(t("bm.deleteError"));
          }
          renderDetailContent();
        }, function () {
          av.bmDeleteConfirmId = "";
          toast(t("bm.deleteError"));
          renderDetailContent();
        });
      });
    });

    // Screen 3 (create form) wiring
    if (av.creating) {
      var nameInput = byId("crName");
      if (nameInput) {
        nameInput.focus();
        nameInput.addEventListener("input", function () { av.createName = nameInput.value; });
      }
      qsa("[data-cr-mode]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var m = btn.getAttribute("data-cr-mode");
          var idx = av.createModes.indexOf(m);
          if (idx === -1) { av.createModes.push(m); } else { av.createModes.splice(idx, 1); }
          btn.classList.toggle("on", av.createModes.indexOf(m) !== -1);
        });
      });
      var submitBtn = byId("crSubmit");
      if (submitBtn) { submitBtn.addEventListener("click", submitCreate); }
      var cancelBtn = byId("crCancel");
      if (cancelBtn) { cancelBtn.addEventListener("click", function () { av.creating = false; av.createError = null; renderDetailContent(); }); }
      var crTagBtn = byId("crTagBtn");
      if (crTagBtn) { crTagBtn.addEventListener("click", function () { av.creating = false; setTab("golden"); }); }
    }
  }

  function renderGettingStarted() {
    var box = byId("gsStrip");
    if (!box) { return; }
    if (!S.agentCatalog.loaded) { box.style.display = "none"; return; }
    var hasAgent = S.agentCatalog.agents.length > 0;
    var av = S.agentView;
    var hasTags = hasAgent && av.loaded && av.n_tagged > 0;
    var hasBench = hasAgent && av.loaded && av.benchmarks.length > 0;
    // Step 4 (has runs): approximated by having at least one done question across benchmarks
    var hasRun = hasBench && av.benchmarks.some(function (b) { return b.n_done > 0; });

    var steps = [
      { key: "gs.step1", done: hasAgent },
      { key: "gs.step2", done: hasTags },
      { key: "gs.step3", done: hasBench },
      { key: "gs.step4", done: hasRun }
    ];
    if (steps.every(function (s) { return s.done; })) { box.style.display = "none"; return; }

    box.style.display = "";
    box.innerHTML = '<div class="gs-inner">' +
      steps.map(function (s, i) {
        return '<span class="gs-step' + (s.done ? " gs-step--done" : "") + '">' +
          (s.done ? I.check : '<span class="gs-num">' + (i + 1) + '</span>') +
          ' ' + esc(t(s.key)) + '</span>';
      }).join('<span class="gs-sep"> / </span>') +
    '</div>';
  }

  function renderDataFooter() {
    var box = byId("dataFooter");
    if (box) { box.textContent = t("footer.copy"); }
  }

  /* ============================ Screen 4: benchmark detail (dispatch 2) ============================ */

  function loadBenchmarkDetail4(bid) {
    var st = S.benchDetailState;
    st.loaded = false;
    st.loadError = false;
    st.detail = null;
    renderDetailContent();
    callApi("GET", "benchmark/detail?benchmark_id=" + encodeURIComponent(bid)).then(function (res) {
      if (S.route.benchmarkId !== bid) { return; }  // stale
      var d = res.data || {};
      if (res.status === 200 && d.benchmark_id && !d.error) {
        st.detail = d;
        st.loaded = true;
        st.loadError = false;
      } else {
        st.loaded = true;
        st.loadError = true;
      }
      if (S.route.level === "benchmark") { renderDetailContent(); renderBreadcrumb(); }
    }, function () {
      if (S.route.benchmarkId !== bid) { return; }
      st.loaded = true;
      st.loadError = true;
      if (S.route.level === "benchmark") { renderDetailContent(); }
    });
  }

  function renderBenchmarkDetail() {
    var box = byId("detailContent");
    if (!box) { return; }
    box.innerHTML = buildBenchmarkDetailHtml();
    wireBenchmarkDetail();
  }

  function buildBenchmarkDetailHtml() {
    var st = S.benchDetailState;
    if (!st.loaded) {
      return '<div class="bd4-loading">' + esc(t("common.loading")) + '</div>';
    }
    if (st.loadError) {
      return '<div class="note note-error">' + esc(t("bd.loadError")) + '</div>';
    }

    var det = st.detail;
    var modes = det.modes || [];
    var ledger = det.ledger || {};
    var qs = det.questions || [];
    var rl = (typeof Journey !== "undefined" && typeof Journey.runnableLabel === "function")
      ? Journey.runnableLabel(det)
      : { label: "Run pending (" + (det.runnable || 0) + ")", enabled: (det.runnable || 0) > 0, hint: "" };
    var allTested = !ledger.pending && !ledger.redo;

    var html = '<div class="bd4">';

    // Meta row
    var agLabel = (det.agent && det.agent.agent_label) || "";
    html += '<div class="bd4-meta">' +
      '<span class="bd4-meta-agent"><b>' + esc(t("bd.agent")) + '</b> ' + esc(agLabel) + '</span>' +
      '<span class="bd4-meta-modes"><b>' + esc(t("bd.modes")) + '</b> ' + esc(modes.join(", ")) + '</span>' +
      (det.accuracy_pct && det.accuracy_pct !== "-"
        ? '<span class="bd4-meta-acc"><b>' + esc(t("bm.accuracy")) + '</b> ' + esc(det.accuracy_pct) + '</span>'
        : '') +
    '</div>';

    // Fix I-1: state 4d - no active tagged questions in this benchmark
    if (qs.length === 0) {
      html += '<div class="note note-info" role="status">' + esc(t("bd.empty")) + '</div>';
      html += '<div class="bd4-actions">' +
        '<button class="btn btn-primary" id="bd4TagQBtn">' + esc(t("bd4.tagQ")) + '</button>' +
        '</div>';
      html += '</div>';  // bd4
      return html;
    }

    // Fix I-2: state 4e - pending cells exist AND benchmark has run before
    var hasPrevRun = det.accuracy_pct != null && det.accuracy_pct !== "-";
    var runnableCount = det.runnable || 0;
    if (hasPrevRun && runnableCount > 0) {
      html += '<div class="bd4-pending-strip">' +
        '<p>' + esc(t("bd.newPending", { n: runnableCount })) + '</p>' +
        '<button class="btn btn-primary btn-sm" id="bd4StripRunPending">' + esc(t("bd.runPending")) + '</button>' +
        '</div>';
    }

    // Ledger chips
    html += '<div class="bd4-ledger">' +
      '<span class="bm-chip bm-chip--done">' + esc(t("bm.badge.done", { n: ledger.tested || 0 })) + '</span>';
    if (ledger.pending) { html += '<span class="bm-chip bm-chip--pending">' + esc(t("bm.badge.pending", { n: ledger.pending })) + '</span>'; }
    if (ledger.redo)    { html += '<span class="bm-chip bm-chip--redo">' + esc(t("bm.badge.redo", { n: ledger.redo })) + '</span>'; }
    html += '</div>';

    // Another benchmark owns the live run: this one's controls are locked until it ends.
    var otherRunning = !st.running && !!S_bench4ActiveBid && S_bench4ActiveBid !== S.route.benchmarkId;

    // Run status: full Screen 5 lifecycle
    if (st.running) {
      // Progress bar
      var elapsed = st.runStartedAt ? Math.round((Date.now() - st.runStartedAt) / 1000) : 0;
      var pct = (st.runTotal > 0) ? Math.round((st.runScored / st.runTotal) * 100) : 0;
      var progLabel = (st.runTotal > 0)
        ? esc(t("run.progress", { scored: st.runScored, total: st.runTotal }))
        : esc(t("run.elapsed", { s: elapsed }));
      html += '<div class="bd4-run-status bd4-run-status--running">' +
        '<div class="run-progress-bar"><div class="run-progress-fill" style="width:' + pct + '%"></div></div>' +
        '<span class="run-progress-label">' + progLabel + '</span>' +
        '</div>';
      // Single-flight reassurance: leaving the page does not stop the run.
      html += '<p class="bd4-sflight">' + esc(t("run.singleFlight")) + '</p>';
      if (st.runMsg && st.runMsg.kind === "info") {
        html += '<div class="bd4-run-status bd4-run-status--info">' + esc(st.runMsg.text) + '</div>';
      }
    } else if (st.runMsg) {
      var msgCls2 = (st.runMsg.kind === "ok") ? "bd4-run-status--ok" : (st.runMsg.kind === "info" ? "bd4-run-status--info" : "bd4-run-status--err");
      html += '<div class="bd4-run-status ' + msgCls2 + '">' + esc(st.runMsg.text) + '</div>';
    }

    // Locked strip: jump to the benchmark that currently owns the run.
    if (otherRunning) {
      html += '<div class="bd4-locked-strip">' +
        '<span>' + esc(t("run.locked")) + '</span>' +
        '<button class="btn-link" id="bd4ViewRun">' + esc(t("run.viewRun")) + '</button>' +
        '</div>';
    }

    // Run-complete card: score, per-mode accuracy, optional re-run evolution, results link.
    if (!st.running && st.runComplete) {
      var rc = st.runComplete;
      html += '<div class="bd4-complete">';
      if (rc.score_pct) {
        html += '<p class="bd4-complete-score">' + esc(t("run.complete.score", { pct: rc.score_pct })) + '</p>';
      }
      if (rc.by_mode && rc.by_mode.length) {
        html += '<ul class="bd4-complete-modes">';
        rc.by_mode.forEach(function (bm2) {
          html += '<li>' + esc(t("run.complete.mode", { mode: bm2.mode, pct: bm2.pct })) + '</li>';
        });
        html += '</ul>';
      }
      // Evolution vs the previous run (regressions pinned to the top, heaviest weight).
      if (rc.evolution && rc.evolution.length) {
        var evoOrder = { regressed: 0, improved: 1, same: 2, "new": 3 };
        var evos = rc.evolution.map(function (e) {
          var tok = (typeof Journey !== "undefined" && typeof Journey.evolutionToken === "function")
            ? Journey.evolutionToken(e.prev_verdict, e.cur_verdict)
            : "same";
          return { q: e.question, tok: tok };
        }).sort(function (a, b) {
          var oa = evoOrder[a.tok] === undefined ? 9 : evoOrder[a.tok];
          var ob = evoOrder[b.tok] === undefined ? 9 : evoOrder[b.tok];
          return oa - ob;
        });
        html += '<div class="bd4-evo"><p class="bd4-evo-title">' + esc(t("run.evo.title")) + '</p><ul class="bd4-evo-list">';
        evos.forEach(function (e) {
          html += '<li class="bd4-evo-item bd4-evo-item--' + esc(e.tok) + '">' +
            '<span class="bd4-evo-token">' + esc(t("run.evo." + e.tok)) + '</span>' +
            '<span class="bd4-evo-q">' + esc(e.q) + '</span>' +
            '</li>';
        });
        html += '</ul></div>';
      }
      html += '<a class="bd4-results-link" href="#results" target="_blank" rel="noopener">' + esc(t("run.complete.results")) + '</a>';
      html += '</div>';
    }

    // Reset strip: scenario idle but run_request still set
    if (!st.running && st.resetNeeded) {
      html += '<div class="bd4-reset-strip">' +
        '<span>' + esc(t("run.resetHint")) + '</span>' +
        '<button class="btn btn-ghost btn-sm" id="bd4ResetBtn">' + esc(t("run.reset")) + '</button>' +
        '</div>';
    }

    // Action bar
    html += '<div class="bd4-actions">';

    // Primary run button (always visible, from Journey). Locked while another benchmark runs.
    if (!st.running) {
      var runDisabled = !rl.enabled || otherRunning;
      html += '<button class="btn' + (rl.enabled && !otherRunning ? " btn-primary" : "") + '" id="bd4RunPending"' + (runDisabled ? ' disabled' : '') + '>' + esc(rl.label) + '</button>';
    } else {
      html += '<button class="btn" disabled>' + esc(rl.label) + '</button>';
    }

    // Tag questions shortcut
    if (!st.running) {
      html += '<button class="btn btn-ghost btn-sm" id="bd4TagBtn">' + esc(t("bd4.tagQ")) + '</button>';
    }

    // Re-run entire (all-tested state only) - with inline confirm
    if (allTested && !st.running) {
      if (st.rerunConfirm) {
        var nQ = qs.length;
        var nM = modes.length;
        html += '<div class="bd4-rerun-confirm">' +
          '<span class="confirm-title">' + esc(t("run.rerun.title")) + '</span>' +
          '<span class="confirm-scope">' + esc(t("run.rerun.scope", { n: nQ, m: nM, t: nQ * nM })) + '</span>' +
          '<div class="confirm-btns">' +
            '<button class="btn btn-danger btn-sm" id="bd4RerunGo">' + esc(t("run.rerun.go")) + '</button>' +
            '<button class="btn btn-ghost btn-sm" id="bd4RerunCancel">' + esc(t("common.cancel")) + '</button>' +
          '</div>' +
        '</div>';
      } else {
        // Fix 3: disable Re-run when another benchmark is running (mirrors Run pending guard)
        html += '<button class="btn' + (!otherRunning ? ' btn-primary' : '') + '" id="bd4Rerun"' + (otherRunning ? ' disabled' : '') + '>' + esc(t("bd.runFull")) + '</button>';
      }
    }

    // Run hint
    if (!st.running && rl.hint) {
      html += '<span class="bd4-run-hint">' + esc(rl.hint) + '</span>';
    }

    html += '</div>';  // bd4-actions

    // Secondary action bar (edit / delete)
    if (!st.running) {
      html += '<div class="bd4-sec-actions">';
      if (!st.editModes && !st.deleteConfirm) {
        html += '<button class="btn btn-ghost btn-sm" id="bd4EditModesBtn">' + esc(t("bd4.editModes")) + '</button>';
        html += '<button class="btn btn-ghost btn-sm btn-danger" id="bd4DeleteBtn">' + esc(t("bm.delete")) + '</button>';
      }
      html += '</div>';
    }

    // Edit modes inline form (state 4f)
    if (st.editModes) {
      var modeOpts = ["Smart", "Pro", "Claude"];
      var modesHtml = modeOpts.map(function (m) {
        var on = st.editModesValue.indexOf(m) !== -1;
        return '<button type="button" class="chk' + (on ? " on" : "") + '" data-bd4-mode="' + esc(m) + '">' +
          '<span class="box">' + I.check + '</span><span class="chk-txt"><b>' + esc(m) + '</b></span></button>';
      }).join("");
      html += '<div class="bd4-edit-modes">' +
        '<span class="field-label">' + esc(t("bd4.editModes")) + '</span>' +
        '<div class="chk-stack">' + modesHtml + '</div>' +
        '<div class="bd4-edit-actions">' +
          '<button class="btn btn-primary btn-sm" id="bd4EditModesSave">' + esc(t("bd4.editSave")) + '</button>' +
          '<button class="btn btn-ghost btn-sm" id="bd4EditModesCancel">' + esc(t("common.cancel")) + '</button>' +
        '</div>' +
      '</div>';
    }

    // Delete confirm (state 4g) - named confirm, not window.confirm
    if (st.deleteConfirm) {
      html += '<div class="confirm-row">' +
        '<span class="confirm-msg">' + esc(t("bm.deleteConfirm", { n: det.name })) + '</span>' +
        '<div class="confirm-btns">' +
          '<button class="btn btn-danger btn-sm" id="bd4DeleteGo">' + esc(t("bm.delete")) + '</button>' +
          '<button class="btn btn-ghost btn-sm" id="bd4DeleteCancel">' + esc(t("common.cancel")) + '</button>' +
        '</div>' +
      '</div>';
    }

    // Questions table
    html += '<div class="bd4-table-wrap"><table class="bd4-table">';
    html += '<thead><tr>' +
      '<th class="bd4-th-q">' + esc(t("bd4.col.q")) + '</th>' +
      '<th class="bd4-th-cat">' + esc(t("bd4.col.cat")) + '</th>';
    modes.forEach(function (m) { html += '<th class="bd4-th-mode">' + esc(m) + '</th>'; });
    html += '<th class="bd4-th-redo">' + esc(t("bd4.col.redo")) + '</th>' +
      '</tr></thead>';

    html += '<tbody>';
    qs.forEach(function (q) {
      // Build cell map by mode for quick lookup
      var cellsMap = {};
      (q.cells || []).forEach(function (c) { cellsMap[c.mode] = c; });

      html += '<tr>';
      // Question text + expected refs
      var qInner = '<span class="bd4-q-text">' + esc(q.question) + '</span>';
      if (q.expected_sql) { qInner += '<code class="bd4-ref-sql clamp">' + esc(q.expected_sql) + '</code>'; }
      if (q.expected_tool && q.expected_tool !== "none" && q.expected_tool !== "") {
        qInner += '<span class="ref-tool bd4-ref-tool">' + esc(q.expected_tool) + '</span>';
      }
      html += '<td class="bd4-q-cell">' + qInner + '</td>';

      // Category
      html += '<td class="bd4-cat-cell">' + (q.category ? '<span class="cat-tag">' + esc(q.category) + '</span>' : '') + '</td>';

      // Per-mode chip cells
      modes.forEach(function (m) {
        var chip = (typeof Journey !== "undefined" && typeof Journey.cellChip === "function")
          ? Journey.cellChip(cellsMap[m])
          : (cellsMap[m] && cellsMap[m].status === "tested"
              ? (cellsMap[m].verdict === "OK" ? { text: "OK", kind: "ok" } : { text: "MISS", kind: "miss" })
              : { text: "Pending", kind: "pending" });
        html += '<td class="bd4-cell"><span class="bd4-chip bd4-chip--' + chip.kind + '">' + esc(chip.text) + '</span></td>';
      });

      // Redo toggle
      var redoOn = !!q.redo;
      html += '<td class="bd4-redo-cell"><button type="button" class="chk' + (redoOn ? " on" : "") +
        '" data-bd4-redo="' + esc(q.question_id) + '" data-bd4-redo-val="' + (redoOn ? "0" : "1") + '">' +
        '<span class="box">' + I.check + '</span></button></td>';

      html += '</tr>';
    });
    html += '</tbody></table></div>';

    html += '</div>';  // bd4
    return html;
  }

  function wireBenchmarkDetail() {
    var st = S.benchDetailState;

    // Fix I-1: state 4d "Tag questions" button
    var tagQBtn = byId("bd4TagQBtn");
    if (tagQBtn) {
      tagQBtn.addEventListener("click", function () { setTab("golden"); });
    }

    // Fix I-2: state 4e pending strip run button
    var stripRunBtn = byId("bd4StripRunPending");
    if (stripRunBtn) {
      stripRunBtn.addEventListener("click", function () { bench4Launch("append"); });
    }

    var runBtn = byId("bd4RunPending");
    if (runBtn && !runBtn.disabled) {
      runBtn.addEventListener("click", function () { bench4Launch("append"); });
    }
    var rerunBtn = byId("bd4Rerun");
    if (rerunBtn) {
      rerunBtn.addEventListener("click", function () { bench4Launch("full"); });
    }
    // Rerun confirm box
    var rerunGoBtn = byId("bd4RerunGo");
    if (rerunGoBtn) {
      rerunGoBtn.addEventListener("click", function () {
        // st.rerunConfirm is already true; calling bench4Launch("full") again will proceed
        bench4Launch("full");
      });
    }
    var rerunCancelBtn = byId("bd4RerunCancel");
    if (rerunCancelBtn) {
      rerunCancelBtn.addEventListener("click", function () {
        st.rerunConfirm = false;
        renderDetailContent();
      });
    }
    // Reset strip
    var resetBtn = byId("bd4ResetBtn");
    if (resetBtn) {
      resetBtn.addEventListener("click", function () {
        st.resetNeeded = false;
        renderDetailContent();
        callApi("POST", "run/reset", { benchmark_id: S.route.benchmarkId }).then(function (res) {
          if (S.route.level !== "benchmark") { return; }
          if (res.status === 200 && res.data && res.data.status === "ok") { toast(t("run.reset")); }
        }, function () { /* best-effort */ });
      });
    }
    // Jump to the benchmark that currently owns the live run.
    var viewRunBtn = byId("bd4ViewRun");
    if (viewRunBtn) {
      viewRunBtn.addEventListener("click", function () {
        if (S_bench4ActiveBid) { navigateTo("benchmark", S.route.agentKey, S_bench4ActiveBid); renderAgentsRail(); }
      });
    }
    // Tag questions shortcut from detail view - mirrors goTag() exactly (Fix 2)
    var bdTagBtn = byId("bd4TagBtn");
    if (bdTagBtn) {
      bdTagBtn.addEventListener("click", function () {
        S.goldenTag = { loaded: false, loadError: false, list: [], agents: [], scope: "agent", searchText: "", editRow: null, confirmDelete: null, saving: false, saveError: null };
        navigateTo("golden-tag", S.route.agentKey, S.route.benchmarkId);
        renderAgentsRail();
        loadGoldenTag();
      });
    }

    var editModesBtn = byId("bd4EditModesBtn");
    if (editModesBtn) {
      editModesBtn.addEventListener("click", function () {
        st.editModes = true;
        st.editModesValue = ((st.detail && st.detail.modes) || []).slice();
        renderDetailContent();
      });
    }

    qsa("[data-bd4-mode]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var m = btn.getAttribute("data-bd4-mode");
        var idx = st.editModesValue.indexOf(m);
        if (idx === -1) { st.editModesValue.push(m); } else { st.editModesValue.splice(idx, 1); }
        btn.classList.toggle("on", st.editModesValue.indexOf(m) !== -1);
      });
    });

    var editSaveBtn = byId("bd4EditModesSave");
    if (editSaveBtn) {
      editSaveBtn.addEventListener("click", function () {
        var modes = st.editModesValue.slice();
        editSaveBtn.disabled = true;
        var bid = S.route.benchmarkId;
        callApi("POST", "benchmark/modes", { benchmark_id: bid, modes: modes }).then(function (res) {
          st.editModes = false;
          if (res.status === 200 && res.data && res.data.status === "ok") {
            toast(t("bd4.modesOk"));
            loadBenchmarkDetail4(bid);
          } else {
            toast(t("bd4.modesError"));
            renderDetailContent();
          }
        }, function () {
          st.editModes = false;
          toast(t("bd4.modesError"));
          renderDetailContent();
        });
      });
    }

    var editCancelBtn = byId("bd4EditModesCancel");
    if (editCancelBtn) {
      editCancelBtn.addEventListener("click", function () {
        st.editModes = false;
        renderDetailContent();
      });
    }

    var delBtn = byId("bd4DeleteBtn");
    if (delBtn) {
      delBtn.addEventListener("click", function () {
        st.deleteConfirm = true;
        renderDetailContent();
      });
    }
    var delCancelBtn = byId("bd4DeleteCancel");
    if (delCancelBtn) {
      delCancelBtn.addEventListener("click", function () {
        st.deleteConfirm = false;
        renderDetailContent();
      });
    }
    var delGoBtn = byId("bd4DeleteGo");
    if (delGoBtn) {
      delGoBtn.addEventListener("click", function () { bench4Delete(); });
    }

    qsa("[data-bd4-redo]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var qid = btn.getAttribute("data-bd4-redo");
        var val = btn.getAttribute("data-bd4-redo-val") === "1";  // true = set redo ON
        bench4Redo(qid, val);
      });
    });
  }

  // Recompute ledger + runnable in-place on a detail object (for optimistic redo updates).
  // Fix M-1: count per (question, mode) CELL for tested/pending; redo stays per-question.
  function bench4RecomputeLedger(det) {
    var modes = det.modes || [];
    var qs = det.questions || [];
    var tested = 0, pending = 0, redo = 0, runnable = 0;
    qs.forEach(function (q) {
      var cells = q.cells || [];
      var cellMap = {};
      cells.forEach(function (c) { cellMap[c.mode] = c; });
      // Count each (question, mode) cell individually
      modes.forEach(function (m) {
        var c = cellMap[m];
        if (c && c.status === "tested") { tested += 1; }
        else { pending += 1; }
      });
      // redo is per-question
      if (q.redo) { redo += 1; }
      runnable += q.redo ? modes.length : modes.filter(function (m) {
        var c = cellMap[m];
        return !c || c.status !== "tested";
      }).length;
    });
    det.ledger = { tested: tested, pending: pending, redo: redo };
    det.runnable = runnable;
  }

  var bench4PollErrors = 0;
  var bench4LaunchedBid = null;  // Fix I-3: tracks which benchmark launched the current poll cycle
  var bench4LaunchMode = "append";  // "append" or "full"; flags the run-complete card as a re-run
  var S_bench4ActiveBid = null;  // tracks the bid that OWNS the current run (from run/status response)

  function bench4Launch(launchMode) {
    var st = S.benchDetailState;
    if (st.running) { return; }
    // Re-run entire: require confirmation first
    if (launchMode === "full" && !st.rerunConfirm) {
      st.rerunConfirm = true;
      renderDetailContent();
      return;
    }
    bench4PollErrors = 0;  // Fix I-4: reset error counter at launch
    bench4LaunchMode = launchMode;  // remembered so the run-complete card can flag a re-run
    st.running = true;
    st.rerunConfirm = false;
    st.runMsg = null;
    st.runScored = 0;
    st.runTotal = 0;
    st.runStartedAt = Date.now();
    st.runComplete = null;
    st.resetNeeded = false;
    renderDetailContent();
    var bid = S.route.benchmarkId;
    bench4LaunchedBid = bid;  // Fix I-3: capture bid for poll guard
    callApi("POST", "benchmark/launch", { benchmark_id: bid, launch_mode: launchMode }).then(function (res) {
      var d = res.data || {};
      if (d.status === "ok" && d.launched) {
        toast(t("run.launched"));
        bench4Poll();
      } else if (res.status === 409 || d.error === "already_running") {
        // Another benchmark is running - show single-flight notice and poll anyway
        st.runMsg = { kind: "info", text: t("run.singleFlight") };
        S_bench4ActiveBid = null;  // will be set from poll response
        renderDetailContent();
        bench4Poll();
      } else {
        bench4EndRun({ kind: "err", text: t("bd4.runError") });
      }
    }, function () { bench4EndRun({ kind: "err", text: t("bd4.runError") }); });
  }

  function bench4Poll() {
    var st = S.benchDetailState;
    if (!st.running) { return; }
    setTimeout(function () {
      callApi("GET", "run/status").then(function (res) {
        // Fix I-3 + M-2: stale-check BEFORE resetting error counter
        if (S.route.level !== "benchmark" || S.route.benchmarkId !== bench4LaunchedBid) { return; }
        bench4PollErrors = 0;
        var d = res.data || {};
        // Track which benchmark is actually running (may differ from the one we launched against)
        if (d.benchmark_id) { S_bench4ActiveBid = d.benchmark_id; }
        // Update progress counters
        if (d.total && d.total > 0) {
          st.runTotal = d.total;
          st.runScored = d.scored || 0;
        }
        if (d.running) {
          renderDetailContent();  // refresh progress bar
          bench4Poll();
        } else {
          // Completion: keep the result (score, per-mode, evolution) for the run-complete card.
          var result = d.result || {};
          st.runComplete = {
            scored: st.runScored, total: st.runTotal,
            score_pct: result.score_pct || null,
            by_mode: result.by_mode || [],
            evolution: result.evolution || [],
            rerun: (bench4LaunchMode === "full")
          };
          // The scenario went idle but a run request may still be set: offer a reset.
          st.resetNeeded = !!(d.run_request);
          S_bench4ActiveBid = null;  // run is over: no benchmark owns it anymore
          bench4EndRun({ kind: "ok", text: t("bd4.runDone") });
          loadBenchmarkDetail4(S.route.benchmarkId);
        }
      }, function () {
        bench4PollErrors += 1;
        if (bench4PollErrors >= 4) { bench4EndRun({ kind: "err", text: t("run.lostContact") }); }
        else { bench4Poll(); }
      });
    }, 2500);
  }

  function bench4EndRun(msg) {
    S.benchDetailState.running = false;
    S.benchDetailState.runMsg = msg || null;
    renderDetailContent();
  }

  function bench4Redo(questionId, value) {
    // Optimistic update: flip redo flag and recompute ledger/runnable immediately
    var st = S.benchDetailState;
    var det = st.detail;
    if (det && det.questions) {
      det.questions.forEach(function (q) { if (q.question_id === questionId) { q.redo = value; } });
      bench4RecomputeLedger(det);
    }
    renderDetailContent();
    callApi("POST", "benchmark/redo", { benchmark_id: S.route.benchmarkId, question_id: questionId, value: value }).then(function (res) {
      if (S.route.level !== "benchmark") { return; }
      if (!res.data || res.data.status !== "ok") {
        // Revert
        if (det && det.questions) {
          det.questions.forEach(function (q) { if (q.question_id === questionId) { q.redo = !value; } });
          bench4RecomputeLedger(det);
        }
        toast(t("bd.redoError"));
        renderDetailContent();
      }
    }, function () {
      if (S.route.level !== "benchmark") { return; }
      if (det && det.questions) {
        det.questions.forEach(function (q) { if (q.question_id === questionId) { q.redo = !value; } });
        bench4RecomputeLedger(det);
      }
      toast(t("bd.redoError"));
      renderDetailContent();
    });
  }

  function bench4Delete() {
    var bid = S.route.benchmarkId;
    var agKey = S.route.agentKey;
    var st = S.benchDetailState;
    callApi("POST", "benchmark/delete", { benchmark_id: bid }).then(function (res) {
      var d = res.data || {};
      if (d.status === "ok") {
        toast(t("bm.deleted"));
        navigateTo("agent", agKey, null);
        renderAgentsRail();
        loadAgentBenchmarks(agKey);
      } else {
        st.deleteConfirm = false;
        toast(t("bm.deleteError"));
        renderDetailContent();
      }
    }, function () {
      st.deleteConfirm = false;
      toast(t("bm.deleteError"));
      renderDetailContent();
    });
  }

  /* ============================ Screen 6: golden agent-tagging ============================ */

  function loadGoldenTag() {
    var gt = S.goldenTag;
    var agKey = S.route.agentKey;
    var qs = "scope=" + encodeURIComponent(gt.scope);
    if (agKey && gt.scope === "agent") { qs += "&agent_key=" + encodeURIComponent(agKey); }
    callApi("GET", "golden?" + qs).then(function (res) {
      if (S.route.level !== "golden-tag") { return; }
      var d = res.data || {};
      if (res.status === 200 && d.status === "ok") {
        gt.list = d.questions || [];
        gt.agents = d.agents || [];
        gt.loaded = true;
        gt.loadError = false;
      } else {
        gt.loadError = true;
        gt.loaded = true;
      }
      renderDetailContent();
    }, function () {
      if (S.route.level !== "golden-tag") { return; }
      gt.loadError = true;
      gt.loaded = true;
      renderDetailContent();
    });
  }

  function buildGoldenTagHtml() {
    var gt = S.goldenTag;
    var agKey = S.route.agentKey;
    var html = '<div class="gt-wrap">';
    html += '<div class="gt-head">';
    html += '<span class="eyebrow">' + esc(t("gt.eyebrow")) + '</span>';
    html += '<h2 class="gt-title">' + esc(t("gt.title")) + '</h2>';
    html += '</div>';

    if (!gt.loaded) {
      return html + '<div class="gt-loading">' + esc(t("gt.loading")) + '</div></div>';
    }
    if (gt.loadError) {
      return html + '<div class="note note-error">' + esc(t("gt.loadError")) + '</div></div>';
    }

    // Scope tabs
    html += '<div class="gt-scope-tabs">';
    ["agent", "untagged", "all"].forEach(function (sc) {
      var active = gt.scope === sc;
      html += '<button class="gt-scope-tab' + (active ? " active" : "") + '" data-gt-scope="' + esc(sc) + '">' +
        esc(t("gt.scope." + sc)) + '</button>';
    });
    html += '</div>';

    // Search bar + add button
    html += '<div class="gt-toolbar">' +
      '<input class="input gt-search" id="gtSearch" placeholder="' + esc(t("gt.searchPh")) + '" value="' + esc(gt.searchText) + '">' +
      '<button class="btn btn-primary btn-sm" id="gtAddBtn">' + esc(t("gt.add")) + '</button>' +
      '</div>';

    // Save error
    if (gt.saveError) {
      html += '<div class="note note-error">' + esc(gt.saveError) + '</div>';
    }

    // New-question form (inline at top)
    if (gt.editRow && gt.editRow._new) {
      html += buildGoldenTagForm(gt.editRow, gt.agents, agKey);
    }

    // Filter list
    var search = (gt.searchText || "").toLowerCase();
    var list = gt.list.filter(function (q) {
      if (!search) { return true; }
      return (q.question || "").toLowerCase().indexOf(search) !== -1 ||
             (q.category || "").toLowerCase().indexOf(search) !== -1;
    });

    if (list.length === 0 && !gt.editRow) {
      html += '<div class="gt-empty">' + esc(t("gt.empty")) + '</div>';
    } else {
      html += '<div class="gt-table-wrap"><table class="gt-table">';
      html += '<thead><tr>' +
        '<th>' + esc(t("gt.col.q")) + '</th>' +
        '<th>' + esc(t("gt.col.agent")) + '</th>' +
        '<th>' + esc(t("gt.col.active")) + '</th>' +
        '<th></th>' +
        '</tr></thead><tbody>';

      list.forEach(function (q) {
        var isEdit = gt.editRow && !gt.editRow._new && gt.editRow.question_id === q.question_id;
        var isConfirm = gt.confirmDelete === q.question_id;

        if (isEdit) {
          html += '<tr class="gt-row-edit"><td colspan="4">' + buildGoldenTagForm(gt.editRow, gt.agents, agKey) + '</td></tr>';
        } else if (isConfirm) {
          html += '<tr class="gt-row-confirm"><td colspan="4">' +
            '<span class="confirm-msg">' + esc(t("gt.deleteConfirm")) + '</span>' +
            '<button class="btn btn-danger btn-sm" data-gt-delete-go="' + esc(q.question_id) + '">' + esc(t("gt.delete")) + '</button>' +
            '<button class="btn btn-ghost btn-sm" data-gt-delete-cancel>' + esc(t("gt.cancel")) + '</button>' +
            '</td></tr>';
        } else {
          // Inline agent-tag dropdown: re-tag a question without opening the edit form.
          var agentOpts = '<option value="">' + esc(t("gt.noAgent")) + '</option>';
          (gt.agents || []).forEach(function (a) {
            agentOpts += '<option value="' + esc(a.agent_key) + '"' + (q.agent_key === a.agent_key ? ' selected' : '') + '>' + esc(a.agent_label) + '</option>';
          });
          html += '<tr class="gt-row">' +
            '<td class="gt-q-cell"><span class="gt-q-text">' + esc(q.question) + '</span>' +
              (q.category ? '<span class="cat-tag">' + esc(q.category) + '</span>' : '') +
            '</td>' +
            '<td class="gt-agent-cell"><select class="gt-agent-sel" data-gt-tag="' + esc(q.question_id) + '">' + agentOpts + '</select></td>' +
            '<td class="gt-active-cell">' +
              '<button type="button" class="chk gt-active-toggle' + (q.active ? " on" : "") + '" data-gt-toggle="' + esc(q.question_id) + '" data-on="' + (q.active ? "1" : "0") + '" aria-label="' + esc(t("gt.col.active")) + '">' +
                '<span class="box">' + I.check + '</span></button>' +
            '</td>' +
            '<td class="gt-actions-cell">' +
              '<button class="btn btn-ghost btn-sm" data-gt-edit="' + esc(q.question_id) + '">' + esc(t("common.edit")) + '</button>' +
              '<button class="btn btn-ghost btn-sm btn-danger" data-gt-delete="' + esc(q.question_id) + '">' + esc(t("gt.delete")) + '</button>' +
            '</td>' +
            '</tr>';
        }
      });

      html += '</tbody></table></div>';
    }

    html += '</div>';  // gt-wrap
    return html;
  }

  function buildGoldenTagForm(row, agents, agKey) {
    var agentsHtml = '<option value="">' + esc(t("gt.noAgent")) + '</option>';
    agents.forEach(function (a) {
      var sel = (row.agent_key === a.agent_key) || (!row.agent_key && a.agent_key === agKey);
      agentsHtml += '<option value="' + esc(a.agent_key) + '"' + (sel ? ' selected' : '') + '>' + esc(a.agent_label) + '</option>';
    });
    var activeOn = row.active !== false;
    return '<div class="gt-form">' +
      (row._new ? '' : '<input type="hidden" id="gtFormQid" value="' + esc(row.question_id || "") + '">') +
      '<label class="field full"><span class="field-label">' + esc(t("gt.formQ")) + '</span>' +
        '<textarea class="input" id="gtFormQ" rows="3">' + esc(row.question || "") + '</textarea></label>' +
      '<label class="field full"><span class="field-label">' + esc(t("gt.formA")) + '</span>' +
        '<textarea class="input" id="gtFormA" rows="3">' + esc(row.reference_answer || "") + '</textarea></label>' +
      '<label class="field full"><span class="field-label">' + esc(t("gt.formSql")) + '</span>' +
        '<textarea class="input mono" id="gtFormSql" rows="2">' + esc(row.expected_sql || "") + '</textarea></label>' +
      '<label class="field"><span class="field-label">' + esc(t("gt.formTool")) + '</span>' +
        '<input class="input mono" id="gtFormTool" value="' + esc(row.expected_tool || "") + '" list="gtToolList">' +
        '<datalist id="gtToolList"><option value="show_chart"></option><option value="show_table"></option><option value="none"></option></datalist>' +
      '</label>' +
      '<label class="field"><span class="field-label">' + esc(t("gt.formAgent")) + '</span>' +
        '<select class="input" id="gtFormAgent">' + agentsHtml + '</select></label>' +
      '<label class="field"><span class="field-label">' + esc(t("gt.formCat")) + '</span>' +
        '<input class="input" id="gtFormCat" value="' + esc(row.category || "") + '"></label>' +
      '<label class="field"><span class="field-label">' + esc(t("gt.formLang")) + '</span>' +
        '<select class="input" id="gtFormLang"><option value="en"' + (row.language === "en" ? " selected" : "") + '>en</option>' +
        '<option value="fr"' + (row.language !== "en" ? " selected" : "") + '>fr</option></select></label>' +
      '<div class="field full"><button type="button" class="chk' + (activeOn ? " on" : "") + '" id="gtFormActive" data-on="' + (activeOn ? "1" : "0") + '">' +
        '<span class="box">' + I.check + '</span><span class="chk-txt"><b>' + esc(t("gt.formActive")) + '</b></span></button></div>' +
      '<div class="gt-form-actions">' +
        '<button class="btn btn-primary btn-sm" id="gtFormSave">' + esc(t("gt.save")) + '</button>' +
        '<button class="btn btn-ghost btn-sm" id="gtFormCancel">' + esc(t("gt.cancel")) + '</button>' +
      '</div>' +
    '</div>';
  }

  function wireGoldenTag() {
    var gt = S.goldenTag;
    var agKey = S.route.agentKey;

    // Scope tabs
    qsa("[data-gt-scope]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        gt.scope = btn.getAttribute("data-gt-scope");
        gt.loaded = false;
        gt.editRow = null;
        gt.confirmDelete = null;
        renderDetailContent();
        loadGoldenTag();
      });
    });

    // Search
    var searchInput = byId("gtSearch");
    if (searchInput) {
      searchInput.addEventListener("input", function () {
        gt.searchText = this.value;
        renderDetailContent();
      });
    }

    // Add new question
    var addBtn = byId("gtAddBtn");
    if (addBtn) {
      addBtn.addEventListener("click", function () {
        gt.editRow = { _new: true, question: "", reference_answer: "", expected_sql: "", expected_tool: "", agent_key: agKey || "", category: "", language: "fr", active: true };
        gt.saveError = null;
        renderDetailContent();
      });
    }

    // Persist a single inline field change (agent tag or active flag) through golden/save.
    // Read-modify-write keeps every other column intact; optimistic, with revert on failure.
    function gtInlinePersist(qid, patch, revert) {
      var row = gt.list.filter(function (q) { return q.question_id === qid; })[0];
      if (!row) { return; }
      var payload = {
        question_id: row.question_id,
        question: row.question || "",
        reference_answer: row.reference_answer || "",
        expected_sql: row.expected_sql || "",
        expected_tool: row.expected_tool || "",
        agent_key: ("agent_key" in patch) ? patch.agent_key : (row.agent_key || ""),
        category: row.category || "",
        language: row.language || "fr",
        active: ("active" in patch) ? patch.active : (row.active !== false),
        expected_value: row.expected_value || "",
        expected_value_type: row.expected_value_type || ""
      };
      Object.keys(patch).forEach(function (k) { row[k] = patch[k]; });  // optimistic
      callApi("POST", "golden/save", payload).then(function (res) {
        if (S.route.level !== "golden-tag") { return; }
        var d = res.data || {};
        if (res.status === 200 && d.status === "ok") {
          toast(t("gt.saved"));
          // Re-tagging can move a row out of a scoped view: reload prunes it cleanly.
          if (("agent_key" in patch) && gt.scope !== "all") { gt.loaded = false; renderDetailContent(); loadGoldenTag(); }
        } else {
          revert();
          toast(t("gt.loadError"));
          renderDetailContent();
        }
      }, function () {
        if (S.route.level !== "golden-tag") { return; }
        revert();
        toast(t("gt.loadError"));
        renderDetailContent();
      });
    }

    // Inline agent-tag dropdown
    qsa("[data-gt-tag]").forEach(function (sel) {
      sel.addEventListener("change", function () {
        var qid = sel.getAttribute("data-gt-tag");
        var row = gt.list.filter(function (q) { return q.question_id === qid; })[0];
        if (!row) { return; }
        var prev = row.agent_key || "";
        gtInlinePersist(qid, { agent_key: sel.value }, function () { row.agent_key = prev; });
      });
    });

    // Inline active toggle
    qsa("[data-gt-toggle]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var qid = btn.getAttribute("data-gt-toggle");
        var row = gt.list.filter(function (q) { return q.question_id === qid; })[0];
        if (!row) { return; }
        var prev = row.active !== false;
        var next = !prev;
        btn.classList.toggle("on", next);
        btn.setAttribute("data-on", next ? "1" : "0");
        gtInlinePersist(qid, { active: next }, function () { row.active = prev; });
      });
    });

    // Edit existing
    qsa("[data-gt-edit]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var qid = btn.getAttribute("data-gt-edit");
        var row = gt.list.filter(function (q) { return q.question_id === qid; })[0];
        if (row) {
          gt.editRow = Object.assign({}, row);
          gt.saveError = null;
          gt.confirmDelete = null;
          renderDetailContent();
        }
      });
    });

    // Delete (show confirm)
    qsa("[data-gt-delete]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        gt.confirmDelete = btn.getAttribute("data-gt-delete");
        gt.editRow = null;
        renderDetailContent();
      });
    });
    qsa("[data-gt-delete-cancel]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        gt.confirmDelete = null;
        renderDetailContent();
      });
    });
    qsa("[data-gt-delete-go]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var qid = btn.getAttribute("data-gt-delete-go");
        callApi("POST", "golden/delete", { question_id: qid }).then(function (res) {
          if (S.route.level !== "golden-tag") { return; }
          var d = res.data || {};
          if (res.status === 200 && d.status === "ok") {
            gt.list = gt.list.filter(function (q) { return q.question_id !== qid; });
            gt.confirmDelete = null;
            toast(t("gt.deleted"));
          } else {
            gt.confirmDelete = null;
            toast(t("gt.loadError"));
          }
          renderDetailContent();
        }, function () {
          if (S.route.level !== "golden-tag") { return; }
          gt.confirmDelete = null;
          toast(t("gt.loadError"));
          renderDetailContent();
        });
      });
    });

    // Form: active toggle
    var formActive = byId("gtFormActive");
    if (formActive) {
      formActive.addEventListener("click", function () {
        var on = this.getAttribute("data-on") !== "1";
        this.setAttribute("data-on", on ? "1" : "0");
        this.classList.toggle("on", on);
        if (gt.editRow) { gt.editRow.active = on; }
      });
    }

    // Form: save
    var formSave = byId("gtFormSave");
    if (formSave) {
      formSave.addEventListener("click", function () {
        var q = (byId("gtFormQ") && byId("gtFormQ").value || "").trim();
        var a = (byId("gtFormA") && byId("gtFormA").value || "").trim();
        var agentKey = (byId("gtFormAgent") && byId("gtFormAgent").value || "").trim();
        if (!agentKey) {
          gt.saveError = t("gt.agentRequired");
          renderDetailContent();
          return;
        }
        var payload = {
          question_id: gt.editRow && !gt.editRow._new ? gt.editRow.question_id : "",
          question: q,
          reference_answer: a,
          expected_sql: (byId("gtFormSql") && byId("gtFormSql").value || "").trim(),
          expected_tool: (byId("gtFormTool") && byId("gtFormTool").value || "").trim(),
          agent_key: agentKey,
          category: (byId("gtFormCat") && byId("gtFormCat").value || "").trim(),
          language: (byId("gtFormLang") && byId("gtFormLang").value) || "fr",
          active: (byId("gtFormActive") && byId("gtFormActive").getAttribute("data-on") === "1")
        };
        gt.saving = true;
        gt.saveError = null;
        callApi("POST", "golden/save", payload).then(function (res) {
          if (S.route.level !== "golden-tag") { return; }
          gt.saving = false;
          var d = res.data || {};
          if (res.status === 200 && d.status === "ok") {
            toast(t("gt.saved"));
            gt.editRow = null;
            gt.saveError = null;
            // Reload the list to reflect the new/updated row
            gt.loaded = false;
            renderDetailContent();
            loadGoldenTag();
          } else {
            var msg = (d.messages && d.messages[0]) || t("gt.loadError");
            gt.saveError = msg;
            renderDetailContent();
          }
        }, function () {
          if (S.route.level !== "golden-tag") { return; }
          gt.saving = false;
          gt.saveError = t("gt.loadError");
          renderDetailContent();
        });
      });
    }

    // Form: cancel
    var formCancel = byId("gtFormCancel");
    if (formCancel) {
      formCancel.addEventListener("click", function () {
        gt.editRow = null;
        gt.saveError = null;
        renderDetailContent();
      });
    }
  }

  /* ============================ Screen 7: settings panel ============================ */

  function openSettings() {
    var st = S.settings;
    st.open = true;
    var panel = byId("settingsPanel");
    var overlay = byId("settingsOverlay");
    if (panel) { panel.classList.add("open"); panel.setAttribute("aria-hidden", "false"); }
    if (overlay) { overlay.classList.add("open"); }
    if (!st.loaded && !st.loading) { loadSettings(); }
    else { renderSettingsBody(); }
  }

  function closeSettings() {
    S.settings.open = false;
    var panel = byId("settingsPanel");
    var overlay = byId("settingsOverlay");
    if (panel) { panel.classList.remove("open"); panel.setAttribute("aria-hidden", "true"); }
    if (overlay) { overlay.classList.remove("open"); }
  }

  function loadSettings() {
    var st = S.settings;
    st.loading = true;
    callApi("GET", "settings").then(function (res) {
      st.loading = false;
      var d = res.data || {};
      if (res.status === 200 && d.status === "ok") {
        st.data = d.settings || {};
        st.loaded = true;
        st.loadError = false;
      } else {
        st.loadError = true;
        st.loaded = true;
      }
      renderSettingsBody();
    }, function () {
      st.loading = false;
      st.loadError = true;
      st.loaded = true;
      renderSettingsBody();
    });
  }

  function renderSettingsBody() {
    var box = byId("settingsBody");
    if (!box) { return; }
    box.innerHTML = buildSettingsHtml();
    // Wire save button
    var saveBtn = byId("stSaveBtn");
    if (saveBtn) {
      saveBtn.addEventListener("click", function () { saveSettings(); });
    }
    // Wire run_language select live update
    var runLangSel = byId("stRunLang");
    if (runLangSel) {
      runLangSel.addEventListener("change", function () { S.settings.data.run_language = this.value; });
    }
    applyI18n(box);
  }

  function buildSettingsHtml() {
    var st = S.settings;
    if (!st.loaded) {
      return '<div class="st-loading">' + esc(t("st.loading")) + '</div>';
    }
    if (st.loadError) {
      return '<div class="note note-error">' + esc(t("st.loadError")) + '</div>';
    }
    var d = st.data;
    var fe = st.fieldErrors || {};
    function fieldErr(k) {
      return fe[k] ? '<span class="st-field-err">' + esc(fe[k]) + '</span>' : '';
    }
    var html = '<div class="st-form">';

    // Golden dataset
    html += '<label class="field full"><span class="field-label">' + esc(t("st.golden")) + '</span>' +
      '<input class="input mono" id="stGolden" value="' + esc(d.golden_dataset || "") + '">' +
      '<span class="field-help">' + esc(t("st.goldenHint")) + '</span>' + fieldErr("golden_dataset") + '</label>';

    // Judge LLM
    html += '<label class="field full"><span class="field-label">' + esc(t("st.judge")) + '</span>' +
      '<input class="input mono" id="stJudge" value="' + esc(d.judge_llm_id || "") + '">' +
      '<span class="field-help">' + esc(t("st.judgeHint")) + '</span>' + fieldErr("judge_llm_id") + '</label>';

    // Concurrency
    html += '<label class="field"><span class="field-label">' + esc(t("st.concurrency")) + '</span>' +
      '<input class="input" id="stConcurrency" type="number" min="1" max="10" value="' + esc(String(d.concurrency || 3)) + '">' +
      '<span class="field-help">' + esc(t("st.concurrencyHint")) + '</span>' + fieldErr("concurrency") + '</label>';

    // Run language
    var langEn = d.run_language === "en";
    html += '<label class="field"><span class="field-label">' + esc(t("st.runLang")) + '</span>' +
      '<select class="input" id="stRunLang">' +
        '<option value="en"' + (langEn ? " selected" : "") + '>' + esc(t("st.langEn")) + '</option>' +
        '<option value="fr"' + (!langEn ? " selected" : "") + '>' + esc(t("st.langFr")) + '</option>' +
      '</select>' +
      '<span class="field-help">' + esc(t("st.runLangHint")) + '</span>' + fieldErr("run_language") + '</label>';

    // Read-only dataset names
    html += '<div class="st-section-title">' + esc(t("st.whereData")) + '</div>';
    html += '<div class="st-ds-grid">';
    [
      { key: "st.rawDs", val: d.raw_dataset },
      { key: "st.scoredDs", val: d.scored_dataset },
      { key: "st.summaryDs", val: d.summary_dataset },
      { key: "st.breakdownDs", val: d.breakdown_dataset }
    ].forEach(function (row) {
      html += '<span class="st-ds-label">' + esc(t(row.key)) + '</span>' +
        '<span class="st-ds-val mono">' + esc(row.val || "-") + '</span>';
    });
    html += '</div>';

    // Save error
    if (st.saveError) {
      html += '<div class="note note-error">' + esc(st.saveError) + '</div>';
    }

    // Save button
    html += '<div class="st-actions">' +
      '<button class="btn btn-primary" id="stSaveBtn"' + (st.saving ? ' disabled' : '') + '>' +
        esc(t("st.save")) + '</button>' +
    '</div>';

    html += '</div>';  // st-form
    return html;
  }

  function saveSettings() {
    var st = S.settings;
    if (st.saving) { return; }
    var payload = {
      golden_dataset: (byId("stGolden") && byId("stGolden").value || "").trim(),
      judge_llm_id: (byId("stJudge") && byId("stJudge").value || "").trim(),
      concurrency: parseInt((byId("stConcurrency") && byId("stConcurrency").value) || "3", 10),
      run_language: (byId("stRunLang") && byId("stRunLang").value) || "fr"
    };
    st.saving = true;
    st.saveError = null;
    st.fieldErrors = {};
    // Keep the form reflecting what the user typed so a rejected save never wipes their input.
    st.data = Object.assign({}, st.data, {
      golden_dataset: payload.golden_dataset,
      judge_llm_id: payload.judge_llm_id,
      concurrency: payload.concurrency,
      run_language: payload.run_language
    });
    renderSettingsBody();
    callApi("POST", "settings", payload).then(function (res) {
      st.saving = false;
      var d = res.data || {};
      if (res.status === 200 && d.status === "ok") {
        st.data = d.settings || st.data;
        st.fieldErrors = {};
        st.saveError = null;
        toast(t("st.saved"));
        renderSettingsBody();
      } else {
        // Field-level errors render under the relevant field; fall back to a banner otherwise.
        var fe = (d && d.errors) || {};
        st.fieldErrors = fe;
        st.saveError = Object.keys(fe).length ? null : t("st.loadError");
        renderSettingsBody();
      }
    }, function () {
      st.saving = false;
      st.fieldErrors = {};
      st.saveError = t("st.loadError");
      renderSettingsBody();
    });
  }

  /* ============================ static wiring ============================ */

  function wireStatic() {
    // Language toggle
    qsa("#langSeg button").forEach(function (b) {
      b.addEventListener("click", function () {
        ui.lang = b.getAttribute("data-lang");
        try { localStorage.setItem("bench-lang", ui.lang); } catch (e) { /* */ }
        render();
      });
    });
    // Header links (Golden / Suggestions / Review)
    byId("linkGolden").addEventListener("click", function () {
      // Navigate to golden-tag in the detail pane (agent-first context if one is selected)
      S.goldenTag = { loaded: false, loadError: false, list: [], agents: [], scope: S.route.agentKey ? "agent" : "all", searchText: "", editRow: null, confirmDelete: null, saving: false, saveError: null };
      navigateTo("golden-tag", S.route.agentKey || null, null);
      renderAgentsRail();
      loadGoldenTag();
    });
    byId("linkSuggest").addEventListener("click", function () { setTab("suggest"); });
    byId("linkReview").addEventListener("click", function () { setTab("review"); });
    // Back from golden / suggest / review panels
    var goldenBack = byId("goldenBack");
    if (goldenBack) { goldenBack.addEventListener("click", function () { setTab("benchmarks"); }); }
    var suggestBack = byId("suggestBack");
    if (suggestBack) { suggestBack.addEventListener("click", function () { setTab("benchmarks"); }); }
    var reviewBack = byId("reviewBack");
    if (reviewBack) { reviewBack.addEventListener("click", function () { setTab("benchmarks"); }); }
    // Gear: settings panel (Screen 7)
    var gearBtn = byId("gearBtn");
    if (gearBtn) { gearBtn.addEventListener("click", function () { openSettings(); }); }
    var themeBtn = byId("themeBtn");
    if (themeBtn) {
      themeBtn.addEventListener("click", function () {
        ui.theme = (ui.theme === "dark") ? "light" : "dark";
        try { localStorage.setItem("bench-theme", ui.theme); } catch (e) { /* */ }
        applyTheme();
      });
    }
    var settingsClose = byId("settingsClose");
    if (settingsClose) { settingsClose.addEventListener("click", function () { closeSettings(); }); }
    var settingsOverlay = byId("settingsOverlay");
    if (settingsOverlay) { settingsOverlay.addEventListener("click", function () { closeSettings(); }); }
    // Golden editor modal
    byId("mdClose").addEventListener("click", closeModal);
    byId("mdCancel").addEventListener("click", closeModal);
    byId("mdSave").addEventListener("click", submitModal);
    byId("mActive").addEventListener("click", function () {
      var on = this.getAttribute("data-on") !== "1";
      this.setAttribute("data-on", on ? "1" : "0");
      this.classList.toggle("on", on);
    });
    byId("overlay").addEventListener("click", function (e) { if (e.target === byId("overlay")) { closeModal(); } });
    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape") { return; }
      if (S.editor.open) { closeModal(); }
    });
  }

  /* ============================ init ============================ */

  function init() {
    loadPrefs();
    applyTheme();
    applyLang();
    loadAgents();  // GET /api/agents + fire discover once
  }

  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", init); }
  else { init(); }
})();
