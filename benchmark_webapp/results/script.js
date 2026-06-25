/* OWIsMind Benchmark - PUBLIC RESULTS webapp logic (framework-free vanilla JS).
 *
 * Audience: a non-technical finance reader. Every visible string goes through t() and exists in
 * both English (default) and French. Numbers are formatted client-side per the active locale.
 *
 * Data comes from the read-only Python backend via getWebAppBackendUrl('api/...'). When that
 * helper is absent (offline preview), MOCK serves representative sample data for every endpoint.
 */
(function () {
  "use strict";

  /* ------------------------------------------------------------ i18n dict */

  var I18N = {
    en: {
      "wordmark.a": "OWIsMind",
      "wordmark.b": "Benchmark",
      "run.label": "Test run",
      "theme.toDark": "Dark",
      "theme.toLight": "Light",
      "theme.ariaToDark": "Switch to dark theme",
      "theme.ariaToLight": "Switch to light theme",
      "lang.toFr": "FR",
      "lang.toEn": "EN",
      "lang.aria": "Switch language",

      "page.eyebrow": "Agent benchmark",
      "page.h1": "How well do the OWIsMind agents answer?",
      "page.desc": "An independent, repeatable test of our AI agents. It measures, in plain language, how often they are right, how fast they answer, and what each answer costs.",

      "hero.lead": "OWIsMind gave the right answer in {correct} of {total} answers produced, across all configurations",
      "hero.scoreCap": "Correct answers",
      "hero.meaning": "How often the AI gives the right answer.",
      "hero.note": "Each of the {n} validated questions is asked in {c} configurations, which is {attempted} attempts in total.",
      "hero.note.failures": "{e} of these attempts failed for technical reasons and are not counted in the score above.",
      "band.high": "Usually correct",
      "band.medium": "Sometimes incorrect",
      "band.low": "Often incorrect",

      "measure.title": "How we measure this",
      "measure.body": "We ask the agents a set of validated questions whose correct answers we already know. Each answer is then checked automatically and by an independent AI judge. This page shows how often the agents are right, how fast they answer, and what a human should double-check.",

      "kpi.accuracy.label": "Correct answers",
      "kpi.accuracy.info": "How often the AI gives the right answer, across every question and configuration tested.",
      "kpi.questions.label": "Questions tested",
      "kpi.questions.info": "The number of validated questions asked to the agents in this test run.",
      "kpi.configs.label": "Configurations tested",
      "kpi.configs.info": "A configuration is one agent running in one mode. We compare several side by side.",
      "kpi.cost.label": "Total cost",
      "kpi.cost.info": "What the agents' answers cost to produce, in US dollars (the AI provider's billing). The AI judge cost is shown separately in the footer.",
      "kpi.review.label": "To double-check",
      "kpi.review.info": "Answers where our automatic check and the AI judge disagreed, so a human should look.",

      "config.title": "By configuration",
      "config.sub": "Each agent runs in one or more modes. Here is how each one performed.",
      "config.legend.title": "What the modes mean",
      "config.legend.body": "Smart, Pro and Claude are AI model tiers, from cheaper and faster to stronger and more expensive.",
      "config.legend.standard": "Standard means the agent runs in a single mode, with no tier to choose.",
      "config.qcount": "{n} questions",
      "m.accuracy": "Correct answers",
      "m.p50": "Typical response time",
      "m.p50.info": "Half of the answers are faster than this.",
      "m.p95": "Slow-case response time",
      "m.p95.info": "95% of the answers are faster than this.",
      "m.cost": "Cost per question",
      "m.errors": "Technical failures",
      "m.errors.info": "The agent could not answer at all (for example a connection error). This is NOT a wrong answer.",

      "topic.title": "Correct answers by topic",
      "topic.info": "How often the AI is right on each kind of question.",
      "topic.qcount": "{n} questions",

      "detail.title": "Question by question",
      "detail.onlyReview": "Show only items to double-check",
      "detail.count": "{n} answers shown",
      "detail.empty": "Nothing to double-check here. Every answer passed both checks.",
      "detail.emptyNeutral": "No question-by-question results are available for this run.",
      "detail.evidence": "Show details",
      "detail.legend.intro": "How to read the columns below",
      "detail.legend.judge": "5 is the closest match to the expected answer, 1 the furthest.",
      "detail.legend.plausible": "the judge accepted the answer, but there is no known correct answer to compare against.",
      "detail.legend.review": "the automatic check and the AI judge disagreed, so a human should look.",
      "ev.judge": "Judge note",
      "ev.reference": "Expected answer",
      "ev.answer": "Agent answer",
      "ev.noReference": "No known correct answer to compare against for this question.",
      "ev.noAnswer": "No answer was returned.",
      "h.question": "Question",
      "h.topic": "Topic",
      "h.config": "Configuration",
      "h.result": "Result",
      "h.judge": "AI judge score",
      "h.judge.info": "5 = best match with the reference answer, 1 = worst.",
      "h.speed": "Response time",
      "h.cost": "Cost",
      "h.review": "To double-check",
      "result.ok": "OK",
      "result.notok": "Not OK",
      "result.error": "No answer",
      "result.plausible": "Plausible",
      "result.plausible.info": "The judge found this answer plausible, but there is no known correct answer to compare it against.",
      "judge.cap": "AI judge score",
      "judge.score": "{x} / 5",
      "review.tag": "To double-check",
      "review.info": "Our automatic check and the AI judge disagreed, so a human should look.",
      "review.none": "Clear",
      "mode.default": "Standard",
      "mode.smart": "Smart",
      "mode.pro": "Pro",
      "mode.claude": "Claude",

      "footer.judge": "AI judge cost in this run: {x}",
      "footer.currency": "Costs shown in US dollars (AI provider billing).",
      "footer.run": "Test run: {ts}",

      "state.loading": "Loading the results...",
      "state.error": "The results could not be loaded right now. Please try again later.",
      "state.empty": "No test run is available yet."
    },
    fr: {
      "wordmark.a": "OWIsMind",
      "wordmark.b": "Benchmark",
      "run.label": "Serie de test",
      "theme.toDark": "Sombre",
      "theme.toLight": "Clair",
      "theme.ariaToDark": "Passer au theme sombre",
      "theme.ariaToLight": "Passer au theme clair",
      "lang.toFr": "FR",
      "lang.toEn": "EN",
      "lang.aria": "Changer de langue",

      "page.eyebrow": "Benchmark des agents",
      "page.h1": "Les agents OWIsMind repondent-ils bien ?",
      "page.desc": "Un test independant et reproductible de nos agents IA. Il mesure, en clair, a quelle frequence ils ont raison, a quelle vitesse ils repondent, et ce que coute chaque reponse.",

      "hero.lead": "OWIsMind a donne la bonne reponse dans {correct} des {total} reponses produites, toutes configurations confondues",
      "hero.scoreCap": "Reponses correctes",
      "hero.meaning": "A quelle frequence l'IA donne la bonne reponse.",
      "hero.note": "Chacune des {n} questions validees est posee dans {c} configurations, soit {attempted} tentatives au total.",
      "hero.note.failures": "{e} de ces tentatives ont echoue pour raisons techniques et ne sont pas comptees dans le score ci-dessus.",
      "band.high": "Habituellement correct",
      "band.medium": "Parfois incorrect",
      "band.low": "Souvent incorrect",

      "measure.title": "Comment nous mesurons cela",
      "measure.body": "Nous posons aux agents une serie de questions validees dont nous connaissons deja les bonnes reponses. Chaque reponse est ensuite verifiee automatiquement et par un juge IA independant. Cette page montre a quelle frequence les agents ont raison, a quelle vitesse ils repondent, et ce qu'un humain devrait revoir.",

      "kpi.accuracy.label": "Reponses correctes",
      "kpi.accuracy.info": "A quelle frequence l'IA donne la bonne reponse, sur toutes les questions et configurations testees.",
      "kpi.questions.label": "Questions testees",
      "kpi.questions.info": "Le nombre de questions validees posees aux agents lors de cette serie de test.",
      "kpi.configs.label": "Configurations testees",
      "kpi.configs.info": "Une configuration, c'est un agent dans un mode donne. Nous en comparons plusieurs.",
      "kpi.cost.label": "Cout total",
      "kpi.cost.info": "Ce qu'ont coute les reponses des agents, en dollars US (la facturation du fournisseur IA). Le cout du juge IA est indique separement dans le pied de page.",
      "kpi.review.label": "A verifier",
      "kpi.review.info": "Reponses pour lesquelles notre controle automatique et le juge IA ne sont pas d'accord : un humain doit regarder.",

      "config.title": "Par configuration",
      "config.sub": "Chaque agent tourne dans un ou plusieurs modes. Voici comment chacun s'est comporte.",
      "config.legend.title": "Ce que signifient les modes",
      "config.legend.body": "Smart, Pro et Claude sont des niveaux de modele IA, du moins cher et plus rapide au plus puissant et plus cher.",
      "config.legend.standard": "Standard signifie que l'agent fonctionne dans un seul mode, sans niveau a choisir.",
      "config.qcount": "{n} questions",
      "m.accuracy": "Reponses correctes",
      "m.p50": "Temps de reponse habituel",
      "m.p50.info": "La moitie des reponses sont plus rapides que cela.",
      "m.p95": "Temps de reponse defavorable",
      "m.p95.info": "95 % des reponses sont plus rapides que cela.",
      "m.cost": "Cout par question",
      "m.errors": "Echecs techniques",
      "m.errors.info": "L'agent n'a pas pu repondre du tout (par exemple une erreur de connexion). Ce n'est PAS une mauvaise reponse.",

      "topic.title": "Reponses correctes par sujet",
      "topic.info": "A quelle frequence l'IA a raison sur chaque type de question.",
      "topic.qcount": "{n} questions",

      "detail.title": "Question par question",
      "detail.onlyReview": "Afficher seulement les elements a verifier",
      "detail.count": "{n} reponses affichees",
      "detail.empty": "Rien a verifier ici. Toutes les reponses ont passe les deux controles.",
      "detail.emptyNeutral": "Aucun resultat question par question n'est disponible pour cette serie.",
      "detail.evidence": "Voir le detail",
      "detail.legend.intro": "Comment lire les colonnes ci-dessous",
      "detail.legend.judge": "5 correspond le mieux a la reponse attendue, 1 le moins bien.",
      "detail.legend.plausible": "le juge a accepte la reponse, mais il n'y a pas de bonne reponse connue pour comparer.",
      "detail.legend.review": "le controle automatique et le juge IA ne sont pas d'accord : un humain doit regarder.",
      "ev.judge": "Note du juge",
      "ev.reference": "Reponse attendue",
      "ev.answer": "Reponse de l'agent",
      "ev.noReference": "Aucune bonne reponse connue pour comparer sur cette question.",
      "ev.noAnswer": "Aucune reponse n'a ete renvoyee.",
      "h.question": "Question",
      "h.topic": "Sujet",
      "h.config": "Configuration",
      "h.result": "Resultat",
      "h.judge": "Note du juge IA",
      "h.judge.info": "5 = meilleure correspondance avec la reponse de reference, 1 = la moins bonne.",
      "h.speed": "Temps de reponse",
      "h.cost": "Cout",
      "h.review": "A verifier",
      "result.ok": "OK",
      "result.notok": "Non OK",
      "result.error": "Sans reponse",
      "result.plausible": "Plausible",
      "result.plausible.info": "Le juge a trouve cette reponse plausible, mais il n'y a pas de bonne reponse connue pour la confirmer.",
      "judge.cap": "Note du juge IA",
      "judge.score": "{x} / 5",
      "review.tag": "A verifier",
      "review.info": "Notre controle automatique et le juge IA ne sont pas d'accord : un humain doit regarder.",
      "review.none": "OK",
      "mode.default": "Standard",
      "mode.smart": "Smart",
      "mode.pro": "Pro",
      "mode.claude": "Claude",

      "footer.judge": "Cout du juge IA pour cette serie : {x}",
      "footer.currency": "Couts en dollars US (facturation du fournisseur IA).",
      "footer.run": "Serie de test : {ts}",

      "state.loading": "Chargement des resultats...",
      "state.error": "Les resultats n'ont pas pu etre charges pour le moment. Reessayez plus tard.",
      "state.empty": "Aucune serie de test n'est encore disponible."
    }
  };

  /* ------------------------------------------------------------- state */

  var state = {
    lang: "en",
    theme: "light",
    runs: [],
    runId: null,
    summary: null,
    breakdown: null,
    detail: null,
    onlyReview: false,
    status: "loading", // loading | ok | error | empty
  };

  function readStored(key, fallback, allowed) {
    try {
      var v = window.localStorage.getItem(key);
      if (v && allowed.indexOf(v) !== -1) return v;
    } catch (e) { /* storage may be unavailable */ }
    return fallback;
  }
  function store(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) { /* ignore */ }
  }

  /* -------------------------------------------------------- translation */

  function t(key, vars) {
    var dict = I18N[state.lang] || I18N.en;
    var s = dict[key];
    if (s == null) s = (I18N.en[key] != null ? I18N.en[key] : key);
    if (vars) {
      Object.keys(vars).forEach(function (k) {
        s = s.replace(new RegExp("\\{" + k + "\\}", "g"), String(vars[k]));
      });
    }
    return s;
  }

  function locale() { return state.lang === "fr" ? "fr-FR" : "en-US"; }

  /* ------------------------------------------------ number formatting */

  function fmtPct(frac) {
    var f = toNum(frac);
    if (f == null) return "-";
    return (f * 100).toLocaleString(locale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " %";
  }
  function fmtSecs(v) {
    var f = toNum(v);
    if (f == null) return "-";
    return f.toLocaleString(locale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " s";
  }
  function fmtMoney(v, dec) {
    var f = toNum(v);
    if (f == null) return "-";
    var d = dec == null ? 4 : dec;
    return f.toLocaleString(locale(), { style: "currency", currency: "USD", minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function fmtInt(v) {
    var f = toNum(v);
    if (f == null) return "0";
    return Math.round(f).toLocaleString(locale());
  }
  function toNum(v) {
    if (v === null || v === undefined || v === "") return null;
    var f = typeof v === "number" ? v : parseFloat(v);
    if (isNaN(f) || !isFinite(f)) return null;
    return f;
  }
  // Backend money strings are emitted in US format (e.g. "$0.18", "$2,345.67"). Pull the numeric
  // value out so the value can be re-formatted client-side per locale; null if it is not parseable.
  function parseUsdStr(s) {
    if (s === null || s === undefined) return null;
    var cleaned = String(s).replace(/,/g, "").replace(/[^0-9.\-]/g, "");
    if (cleaned === "" || cleaned === "-" || cleaned === ".") return null;
    return toNum(cleaned);
  }

  /* ------------------------------------------------------- safety / dom */

  function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
  function el(id) { return document.getElementById(id); }

  function infoDot(text) {
    var tx = escapeHtml(text);
    return '<span class="info" tabindex="0" role="note" aria-label="' + tx + '">' +
      '<span aria-hidden="true">i</span>' +
      '<span class="info-bubble">' + tx + "</span></span>";
  }

  // Map an internal mode value to its display name + color class.
  function modeClass(mode) {
    var m = String(mode || "").toLowerCase();
    if (m === "smart") return "mode-smart";
    if (m === "pro") return "mode-pro";
    if (m === "claude") return "mode-claude";
    return "mode-default";
  }
  function modeLabel(mode) {
    var m = String(mode || "");
    if (m === "Smart" || m === "Pro" || m === "Claude") return m;
    if (!m || m.toLowerCase() === "default") return t("mode.default");
    return m;
  }

  /* ------------------------------------------------------------- backend */

  function api(path) {
    if (typeof getWebAppBackendUrl !== "function") {
      return Promise.resolve(MOCK(path));
    }
    return fetch(getWebAppBackendUrl(path), { headers: { Accept: "application/json" } })
      .then(function (res) {
        if (!res.ok) throw new Error("http " + res.status);
        return res.json();
      })
      .then(function (data) {
        if (!data || data.status !== "ok") throw new Error((data && data.error) || "error");
        return data;
      });
  }

  /* ------------------------------------------------------------- render */

  function renderTopbar() {
    var top = el("bench-topbar");
    var runOptions = state.runs.map(function (r) {
      var sel = r.run_id === state.runId ? " selected" : "";
      // Show the human timestamp as the visible label; keep the machine run_id in the title.
      var label = r.run_timestamp || r.run_id;
      return '<option value="' + escapeHtml(r.run_id) + '"' + sel +
        ' title="' + escapeHtml(r.run_id) + '">' + escapeHtml(label) + "</option>";
    }).join("");

    var themeNext = state.theme === "light" ? "toDark" : "toLight";
    var themeAria = state.theme === "light" ? t("theme.ariaToDark") : t("theme.ariaToLight");
    var langNext = state.lang === "en" ? "toFr" : "toEn";

    top.innerHTML =
      '<div class="topbar-left">' +
        '<span class="wordmark">' + escapeHtml(t("wordmark.a")) +
        ' <span class="wm-orange">' + escapeHtml(t("wordmark.b")) + "</span></span>" +
      "</div>" +
      '<div class="topbar-right">' +
        '<div class="field">' +
          '<label class="field-label" for="run-select">' + escapeHtml(t("run.label")) + "</label>" +
          '<select id="run-select" class="run-select" aria-label="' + escapeHtml(t("run.label")) + '">' +
            (runOptions || "") +
          "</select>" +
        "</div>" +
        '<button type="button" id="theme-toggle" class="toggle-btn" aria-label="' + escapeHtml(themeAria) + '">' +
          escapeHtml(t("theme." + themeNext)) + "</button>" +
        '<button type="button" id="lang-toggle" class="toggle-btn" aria-label="' + escapeHtml(t("lang.aria")) + '">' +
          escapeHtml(t("lang." + langNext)) + "</button>" +
      "</div>";

    el("run-select").addEventListener("change", function (e) { selectRun(e.target.value); });
    el("theme-toggle").addEventListener("click", toggleTheme);
    el("lang-toggle").addEventListener("click", toggleLang);
  }

  function renderHeader() {
    return '<p class="eyebrow">' + escapeHtml(t("page.eyebrow")) + "</p>" +
      '<h1 class="page-h1">' + escapeHtml(t("page.h1")) + "</h1>" +
      '<div class="title-bar"></div>' +
      '<p class="page-desc">' + escapeHtml(t("page.desc")) + "</p>";
  }

  function gaugeSvg(accuracy, band, pctLabel) {
    var r = 80, c = 2 * Math.PI * r;
    var frac = Math.max(0, Math.min(1, toNum(accuracy) || 0));
    var dash = (frac * c).toFixed(2) + " " + c.toFixed(2);
    return '<div class="gauge-wrap">' +
      '<svg class="gauge-svg" viewBox="0 0 200 200" role="img" aria-label="' + escapeHtml(pctLabel) + '">' +
        '<circle class="gauge-track" cx="100" cy="100" r="80" fill="none" stroke-width="18"></circle>' +
        '<circle class="gauge-arc band-' + escapeHtml(band) + '" cx="100" cy="100" r="80" fill="none" ' +
          'stroke-width="18" stroke-linecap="butt" stroke-dasharray="' + dash + '" ' +
          'transform="rotate(-90 100 100)"></circle>' +
      "</svg>" +
      '<div class="gauge-center">' +
        '<span class="gauge-pct">' + escapeHtml(pctLabel) + "</span>" +
        '<span class="gauge-cap">' + escapeHtml(t("hero.scoreCap")) + "</span>" +
      "</div>" +
    "</div>";
  }

  function renderHero(kpis) {
    var band = kpis.band || "low";
    var pct = fmtPct(kpis.accuracy);
    var lead = t("hero.lead", { correct: "{C}", total: "{T}" });
    // Inject the numbers wrapped in a mono span (escape the surrounding text, not the markup).
    lead = escapeHtml(lead)
      .replace("{C}", '<span class="hl-num">' + escapeHtml(fmtInt(kpis.n_correct)) + "</span>")
      .replace("{T}", '<span class="hl-num">' + escapeHtml(fmtInt(kpis.n_ok_total)) + "</span>");
    // Reconcile the headline base: there are n_questions x n_configs attempts, but accuracy is
    // computed over answers actually produced (n_ok_total). Disclose any technical failures so the
    // arithmetic (e.g. 18 x 3 = 54, but 53 answered) is explainable in the hero, where scrutiny is highest.
    var nq = toNum(kpis.n_questions) || 0;
    var nc = toNum(kpis.n_configs) || 0;
    var attempted = nq * nc;
    var okTotal = toNum(kpis.n_ok_total) || 0;
    var errors = Math.max(0, attempted - okTotal);
    var note = t("hero.note", { n: fmtInt(kpis.n_questions), c: fmtInt(kpis.n_configs), attempted: fmtInt(attempted) });
    if (errors > 0) note += " " + t("hero.note.failures", { e: fmtInt(errors) });

    return '<section class="hero">' +
      gaugeSvg(kpis.accuracy, band, pct) +
      '<div class="hero-verdict">' +
        '<p class="hero-lead">' + lead + "</p>" +
        '<span class="band-pill band-' + escapeHtml(band) + '"><span class="dot"></span>' +
          escapeHtml(t("band." + band)) + "</span>" +
        '<p class="hero-meaning">' + escapeHtml(t("hero.meaning")) + "</p>" +
        '<p class="hero-note">' + escapeHtml(note) + "</p>" +
      "</div>" +
    "</section>";
  }

  function renderExplainer() {
    return '<section class="explainer">' +
      "<h3>" + escapeHtml(t("measure.title")) + "</h3>" +
      "<p>" + escapeHtml(t("measure.body")) + "</p>" +
    "</section>";
  }

  function kpiTile(label, infoText, value, isWarn) {
    return '<div class="kpi">' +
      '<div class="kpi-label">' + escapeHtml(label) + infoDot(infoText) + "</div>" +
      '<div class="kpi-value' + (isWarn ? " warn" : "") + '">' + escapeHtml(value) + "</div>" +
    "</div>";
  }

  function renderKpis(kpis) {
    return '<section class="kpi-grid">' +
      kpiTile(t("kpi.accuracy.label"), t("kpi.accuracy.info"), fmtPct(kpis.accuracy), false) +
      kpiTile(t("kpi.questions.label"), t("kpi.questions.info"), fmtInt(kpis.n_questions), false) +
      kpiTile(t("kpi.configs.label"), t("kpi.configs.info"), fmtInt(kpis.n_configs), false) +
      kpiTile(t("kpi.cost.label"), t("kpi.cost.info"), fmtMoney(kpis.total_cost, 2), false) +
      kpiTile(t("kpi.review.label"), t("kpi.review.info"), fmtInt(kpis.needs_review), kpis.needs_review > 0) +
    "</section>";
  }

  function metricCell(label, value, infoText, bad) {
    var info = infoText ? infoDot(infoText) : "";
    return '<div class="metric">' +
      '<div class="metric-label">' + escapeHtml(label) + info + "</div>" +
      '<div class="metric-value' + (bad ? " bad" : "") + '">' + escapeHtml(value) + "</div>" +
    "</div>";
  }

  function renderConfigSection(rows) {
    var legend =
      '<div class="legend">' +
        '<div class="legend-title">' + escapeHtml(t("config.legend.title")) + "</div>" +
        '<p class="legend-body">' + escapeHtml(t("config.legend.body")) + "</p>" +
        '<div class="legend-swatches">' +
          '<span class="legend-item"><span class="sw mode-smart"></span>' + escapeHtml(t("mode.smart")) + "</span>" +
          '<span class="legend-item"><span class="sw mode-pro"></span>' + escapeHtml(t("mode.pro")) + "</span>" +
          '<span class="legend-item"><span class="sw mode-claude"></span>' + escapeHtml(t("mode.claude")) + "</span>" +
          '<span class="legend-item"><span class="sw mode-default"></span>' + escapeHtml(t("mode.default")) + "</span>" +
        "</div>" +
        '<p class="legend-note">' + escapeHtml(t("config.legend.standard")) + "</p>" +
      "</div>";

    var cards = rows.map(function (r) {
      var mc = modeClass(r.mode);
      var accPctNum = (Math.max(0, Math.min(1, toNum(r.accuracy) || 0)) * 100).toFixed(1);
      var errBad = (toNum(r.error_rate) || 0) > 0;
      return '<div class="config-card">' +
        '<div class="config-head">' +
          '<span class="config-name">' + escapeHtml(r.agent_label) + "</span>" +
          '<span class="mode-tag ' + mc + '">' + escapeHtml(modeLabel(r.mode)) + "</span>" +
          '<span class="config-qcount">' + escapeHtml(t("config.qcount", { n: fmtInt(r.n_questions) })) + "</span>" +
        "</div>" +
        '<div class="conf-bar-row">' +
          '<span class="conf-bar-label">' + escapeHtml(t("m.accuracy")) + "</span>" +
          '<div class="bar-track"><div class="bar-fill" style="width:' + accPctNum + '%"></div></div>' +
          '<span class="bar-pct">' + escapeHtml(fmtPct(r.accuracy)) + "</span>" +
        "</div>" +
        '<div class="metric-grid">' +
          metricCell(t("m.p50"), fmtSecs(r.latency_p50_s), t("m.p50.info"), false) +
          metricCell(t("m.p95"), fmtSecs(r.latency_p95_s), t("m.p95.info"), false) +
          metricCell(t("m.cost"), fmtMoney(r.avg_cost_per_q, 4), null, false) +
          metricCell(t("m.errors"), fmtPct(r.error_rate), t("m.errors.info"), errBad) +
        "</div>" +
      "</div>";
    }).join("");

    return '<section class="section">' +
      '<div class="section-head"><h2 class="section-title">' + escapeHtml(t("config.title")) + "</h2></div>" +
      '<p class="section-sub">' + escapeHtml(t("config.sub")) + "</p>" +
      legend +
      '<div class="config-list">' + cards + "</div>" +
    "</section>";
  }

  function renderTopicSection(breakdownRows) {
    // This section is the "by topic" view, which maps to the category dimension only. Keep just the
    // category rows so that if the backend ever ships another dimension (e.g. difficulty), its
    // buckets are not silently mislabeled as topics. Rows without a dimension are treated as category.
    var catRows = breakdownRows.filter(function (r) {
      return r.dimension == null || r.dimension === "category";
    });
    // Group by bucket (topic). Within each topic, one bar per agent x mode configuration.
    var byBucket = {};
    var order = [];
    catRows.forEach(function (r) {
      var b = r.bucket || "-";
      if (!byBucket[b]) { byBucket[b] = []; order.push(b); }
      byBucket[b].push(r);
    });

    var blocks = order.map(function (b) {
      var rowsHtml = byBucket[b].map(function (r) {
        var mc = modeClass(r.mode);
        var accPctNum = (Math.max(0, Math.min(1, toNum(r.accuracy) || 0)) * 100).toFixed(1);
        return '<div class="topic-row">' +
          '<span class="topic-config"><span class="sw ' + mc + '"></span>' +
            escapeHtml(r.agent_label) + " - " + escapeHtml(modeLabel(r.mode)) + "</span>" +
          '<div class="bar-track"><div class="bar-fill" style="width:' + accPctNum + '%"></div></div>' +
          '<span class="bar-pct">' + escapeHtml(fmtPct(r.accuracy)) + "</span>" +
          '<span class="topic-n">' + escapeHtml(t("topic.qcount", { n: fmtInt(r.n) })) + "</span>" +
        "</div>";
      }).join("");
      return '<div class="topic-block">' +
        '<div class="topic-name">' + escapeHtml(b) + "</div>" +
        rowsHtml +
      "</div>";
    }).join("");

    return '<section class="section">' +
      '<div class="section-head"><h2 class="section-title">' + escapeHtml(t("topic.title")) + "</h2>" +
        infoDot(t("topic.info")) + "</div>" +
      '<div class="card" style="padding:24px;">' + (blocks || "") + "</div>" +
    "</section>";
  }

  function resultTag(row) {
    if (row.objective_match === "error" || row.status === "error") {
      return '<span class="result-tag notok"><span class="dot"></span>' + escapeHtml(t("result.error")) + "</span>";
    }
    // No objective reference: the judge may accept the answer, but it cannot be confirmed against a
    // known value, so it is shown as a neutral "Plausible" tag rather than a confident green "OK".
    if (row.objective_match === "n/a") {
      if (row.correct) {
        return '<span class="result-tag plausible"><span class="dot"></span>' + escapeHtml(t("result.plausible")) + "</span>" +
          infoDot(t("result.plausible.info"));
      }
      return '<span class="result-tag notok"><span class="dot"></span>' + escapeHtml(t("result.notok")) + "</span>";
    }
    if (row.correct) {
      return '<span class="result-tag ok"><span class="dot"></span>' + escapeHtml(t("result.ok")) + "</span>";
    }
    return '<span class="result-tag notok"><span class="dot"></span>' + escapeHtml(t("result.notok")) + "</span>";
  }

  // Expose the evidence already shipped with each row (judge rationale, expected answer, agent
  // answer) inside a native collapsed disclosure, so a human can actually perform the double-check.
  function evidenceBlock(r) {
    var verdict = r.judge_verdict ? escapeHtml(r.judge_verdict) : "-";
    var ref = r.reference_answer ? escapeHtml(r.reference_answer) : escapeHtml(t("ev.noReference"));
    var ans = r.answer_preview ? escapeHtml(r.answer_preview) : escapeHtml(t("ev.noAnswer"));
    return '<details class="q-evidence">' +
      "<summary>" + escapeHtml(t("detail.evidence")) + "</summary>" +
      '<dl class="ev-list">' +
        "<dt>" + escapeHtml(t("ev.judge")) + "</dt><dd>" + verdict + "</dd>" +
        "<dt>" + escapeHtml(t("ev.reference")) + "</dt><dd>" + ref + "</dd>" +
        "<dt>" + escapeHtml(t("ev.answer")) + "</dt><dd>" + ans + "</dd>" +
      "</dl>" +
    "</details>";
  }

  // A visible caption that explains the trust-bearing columns (judge score scale, Plausible,
  // To double-check). It lives OUTSIDE the horizontally scrolling table wrapper so it is never
  // clipped, unlike the in-cell info bubbles.
  function detailLegend() {
    return '<div class="detail-legend">' +
      '<p class="detail-legend-intro">' + escapeHtml(t("detail.legend.intro")) + "</p>" +
      '<dl class="detail-legend-list">' +
        "<dt>" + escapeHtml(t("h.judge")) + "</dt><dd>" + escapeHtml(t("detail.legend.judge")) + "</dd>" +
        "<dt>" + escapeHtml(t("result.plausible")) + "</dt><dd>" + escapeHtml(t("detail.legend.plausible")) + "</dd>" +
        "<dt>" + escapeHtml(t("review.tag")) + "</dt><dd>" + escapeHtml(t("detail.legend.review")) + "</dd>" +
      "</dl>" +
    "</div>";
  }

  function renderDetailSection(detail) {
    var rows = (detail && detail.rows) || [];
    var hasRows = rows.length > 0;
    var shown = state.onlyReview ? rows.filter(function (r) { return r.needs_review; }) : rows;

    // The legend and the filter toolbar only make sense when there is question-by-question data.
    var legend = hasRows ? detailLegend() : "";
    var toolbar = hasRows
      ? '<div class="detail-toolbar">' +
          '<label class="checkbox-field">' +
            '<input type="checkbox" id="only-review"' + (state.onlyReview ? " checked" : "") + ">" +
            '<span class="checkbox-box" aria-hidden="true"></span>' +
            "<span>" + escapeHtml(t("detail.onlyReview")) + "</span>" +
          "</label>" +
          '<span class="detail-count">' + escapeHtml(t("detail.count", { n: fmtInt(shown.length) })) + "</span>" +
        "</div>"
      : "";

    var body;
    if (!shown.length) {
      // Only claim "everything passed the double-check" when there genuinely were rows and the
      // filter is on; if the dataset itself is empty, use the neutral message instead.
      var emptyMsg = (hasRows && state.onlyReview) ? t("detail.empty") : t("detail.emptyNeutral");
      body = '<div class="state-block">' + escapeHtml(emptyMsg) + "</div>";
    } else {
      var head =
        "<thead><tr>" +
          '<th scope="col">' + escapeHtml(t("h.question")) + "</th>" +
          '<th scope="col">' + escapeHtml(t("h.topic")) + "</th>" +
          '<th scope="col">' + escapeHtml(t("h.config")) + "</th>" +
          '<th scope="col">' + escapeHtml(t("h.result")) + "</th>" +
          '<th scope="col">' + escapeHtml(t("h.judge")) + infoDot(t("h.judge.info")) + "</th>" +
          '<th scope="col">' + escapeHtml(t("h.speed")) + "</th>" +
          '<th scope="col">' + escapeHtml(t("h.cost")) + "</th>" +
          '<th scope="col">' + escapeHtml(t("h.review")) + "</th>" +
        "</tr></thead>";

      var trs = shown.map(function (r) {
        var mc = modeClass(r.mode);
        var review = r.needs_review
          ? '<span class="review-tag"><span class="dot"></span>' + escapeHtml(t("review.tag")) + "</span>" + infoDot(t("review.info"))
          : '<span class="review-none">' + escapeHtml(t("review.none")) + "</span>";
        // An absent/NaN judge score, or a row that never produced an answer, must not be shown as a
        // confident "0 / 5" worst-case. Show "-" (no score) instead.
        var js = toNum(r.judge_score);
        var noScore = js == null || r.status === "error" || r.objective_match === "error";
        var judgeText = noScore ? "-" : t("judge.score", { x: fmtInt(js) });
        var judge =
          '<div class="judge">' +
            '<span class="judge-score">' + escapeHtml(judgeText) + "</span>" +
            '<span class="judge-cap">' + escapeHtml(t("judge.cap")) + "</span>" +
          "</div>";
        return "<tr>" +
          '<td class="td-question"><div class="q-text">' + escapeHtml(r.question) + "</div>" +
            '<div class="q-id">' + escapeHtml(r.question_id) + "</div>" +
            evidenceBlock(r) + "</td>" +
          "<td>" + escapeHtml(r.category) + "</td>" +
          '<td class="cell-config"><span class="sw ' + mc + '"></span>' +
            escapeHtml(r.agent_label) + " " + escapeHtml(modeLabel(r.mode)) + "</td>" +
          "<td>" + resultTag(r) + "</td>" +
          "<td>" + judge + "</td>" +
          '<td class="cell-mono">' + escapeHtml(fmtSecs(r.latency_total_s)) + "</td>" +
          '<td class="cell-mono">' + escapeHtml(fmtMoney(r.estimated_cost, 4)) + "</td>" +
          "<td>" + review + "</td>" +
        "</tr>";
      }).join("");

      body = '<div class="table-wrap"><table class="detail">' + head + "<tbody>" + trs + "</tbody></table></div>";
    }

    return '<section class="section" id="detail-section">' +
      '<div class="section-head"><h2 class="section-title">' + escapeHtml(t("detail.title")) + "</h2></div>" +
      legend + toolbar + body +
    "</section>";
  }

  // Re-render the detail section in place when the "only items to double-check" toggle changes.
  // The full detail set is kept client-side, so this is a pure filter (no extra backend call).
  function bindDetailToggle() {
    var only = el("only-review");
    if (!only) return;
    only.addEventListener("change", function (e) {
      state.onlyReview = e.target.checked;
      var section = el("detail-section");
      if (!section) return;
      var holder = document.createElement("div");
      holder.innerHTML = renderDetailSection(state.detail);
      section.parentNode.replaceChild(holder.firstChild, section);
      bindDetailToggle();
      // The checkbox was destroyed and recreated; return focus to it for keyboard users.
      var nc = el("only-review");
      if (nc) nc.focus();
    });
  }

  function renderFooter() {
    var foot = el("bench-footer");
    if (state.status !== "ok" || !state.summary) { foot.innerHTML = ""; return; }
    var k = state.summary.kpis || {};
    // Show the human timestamp as the primary run label; keep the machine run_id in the title.
    var runObj = (state.runs || []).filter(function (r) { return r.run_id === state.runId; })[0];
    var ts = (runObj && runObj.run_timestamp) || state.runId || "-";
    // The judge cost ships pre-formatted (judge_cost_str, US format). Re-format it client-side per
    // locale so it matches the other costs on the page (e.g. FR "0,18 $US" rather than a raw "$0.18");
    // fall back to the verbatim string if it cannot be parsed.
    var judgeNum = parseUsdStr(k.judge_cost_str);
    var judgeStr = judgeNum == null ? (k.judge_cost_str || "-") : fmtMoney(judgeNum, 2);
    foot.innerHTML =
      '<span title="' + escapeHtml(state.runId || "") + '">' + escapeHtml(t("footer.run", { ts: ts })) + "</span>" +
      "<span>" + escapeHtml(t("footer.judge", { x: judgeStr })) + "</span>" +
      "<span>" + escapeHtml(t("footer.currency")) + "</span>";
  }

  function render() {
    renderTopbar();
    renderFooter();
    var content = el("bench-content");

    if (state.status === "loading") {
      content.innerHTML = renderHeader() + '<div class="state-block">' + escapeHtml(t("state.loading")) + "</div>";
      return;
    }
    if (state.status === "error") {
      content.innerHTML = renderHeader() + '<div class="state-block error">' + escapeHtml(t("state.error")) + "</div>";
      return;
    }
    if (state.status === "empty" || !state.summary) {
      content.innerHTML = renderHeader() + '<div class="state-block">' + escapeHtml(t("state.empty")) + "</div>";
      return;
    }

    var kpis = state.summary.kpis || {};
    content.innerHTML =
      renderHeader() +
      renderHero(kpis) +
      renderExplainer() +
      renderKpis(kpis) +
      renderConfigSection(state.summary.rows || []) +
      renderTopicSection((state.breakdown && state.breakdown.rows) || []) +
      renderDetailSection(state.detail);

    bindDetailToggle();
  }

  /* ----------------------------------------------------------- behavior */

  function applyTheme() {
    document.documentElement.setAttribute("data-theme", state.theme === "dark" ? "dark" : "light");
  }
  function toggleTheme() {
    state.theme = state.theme === "dark" ? "light" : "dark";
    store("bench-theme", state.theme);
    applyTheme();
    renderTopbar();
  }
  function toggleLang() {
    state.lang = state.lang === "en" ? "fr" : "en";
    store("bench-lang", state.lang);
    document.documentElement.setAttribute("lang", state.lang);
    render();
  }

  function selectRun(runId) {
    if (!runId || runId === state.runId) return;
    state.runId = runId;
    state.status = "loading";
    render();
    loadRun(runId);
  }

  function loadRun(runId) {
    var q = "?run_id=" + encodeURIComponent(runId);
    // Load the three sections independently: a transient failure of a secondary section
    // (breakdown / detail) must not blank out a valid summary headline and KPIs.
    Promise.allSettled([
      api("api/results/summary" + q),
      api("api/results/breakdown" + q),
      api("api/results/detail" + q),
    ]).then(function (res) {
      var summary = res[0].status === "fulfilled" ? res[0].value : null;
      if (!summary) {
        // eslint-disable-next-line no-console
        if (window.console) console.error("loadRun summary failed", res[0].reason);
        state.summary = null;
        state.breakdown = null;
        state.detail = null;
        state.status = "error";
        render();
        return;
      }
      state.summary = summary;
      state.breakdown = res[1].status === "fulfilled" ? res[1].value : null;
      state.detail = res[2].status === "fulfilled" ? res[2].value : null;
      if (window.console) {
        if (res[1].status !== "fulfilled") console.error("loadRun breakdown failed", res[1].reason);
        if (res[2].status !== "fulfilled") console.error("loadRun detail failed", res[2].reason);
      }
      var k = summary.kpis || {};
      state.status = (k.n_ok_total || k.n_configs) ? "ok" : "empty";
      render();
    });
  }

  function init() {
    state.lang = readStored("bench-lang", "en", ["en", "fr"]);
    state.theme = readStored("bench-theme", "light", ["light", "dark"]);
    applyTheme();
    document.documentElement.setAttribute("lang", state.lang);
    render();

    api("api/results/runs").then(function (data) {
      state.runs = (data && data.runs) || [];
      if (!state.runs.length) { state.status = "empty"; render(); return; }
      state.runId = state.runs[0].run_id;
      loadRun(state.runId);
    }).catch(function (err) {
      if (window.console) console.error("runs failed", err);
      state.status = "error";
      render();
    });
  }

  /* ----------------------------------------------------- MOCK (offline) */

  function MOCK(path) {
    var clean = path.split("?")[0];
    if (clean === "api/results/runs") return MOCK_RUNS;
    if (clean === "api/results/summary") return MOCK_SUMMARY;
    if (clean === "api/results/breakdown") return MOCK_BREAKDOWN;
    if (clean === "api/results/detail") return MOCK_DETAIL;
    return { status: "ok" };
  }

  var MOCK_RUN_ID = "run_2026-06-25_22-14";

  var MOCK_RUNS = {
    status: "ok",
    runs: [
      { run_id: MOCK_RUN_ID, run_timestamp: "2026-06-25 22:14:03" },
      { run_id: "run_2026-06-24_18-02", run_timestamp: "2026-06-24 18:02:41" }
    ]
  };

  var MOCK_SUMMARY = {
    status: "ok",
    run_id: MOCK_RUN_ID,
    kpis: {
      accuracy: 0.8868,
      accuracy_pct: "88.7 %",
      n_correct: 47,
      n_ok_total: 53,
      band: "high",
      n_questions: 18,
      n_configs: 3,
      total_cost: 2.34,
      total_cost_str: "$2.34",
      judge_cost_str: "$0.18",
      needs_review: 4
    },
    rows: [
      {
        agent_label: "OWIsMind orchestrator", mode: "Claude", n_questions: 18, n_ok: 18, n_error: 0,
        error_rate: 0.0, error_rate_str: "0.0 %", accuracy: 0.9444, accuracy_pct: "94.4 %", mean_score: 4.6,
        latency_p50_s: 12.4, latency_p50_str: "12.4 s", latency_p95_s: 28.9, latency_p95_str: "28.9 s",
        avg_cost_per_q: 0.0892, avg_cost_per_q_str: "$0.0892", total_cost: 1.53, needs_review_count: 1
      },
      {
        agent_label: "OWIsMind orchestrator", mode: "Pro", n_questions: 18, n_ok: 17, n_error: 1,
        error_rate: 0.0556, error_rate_str: "5.6 %", accuracy: 0.8824, accuracy_pct: "88.2 %", mean_score: 4.1,
        latency_p50_s: 6.8, latency_p50_str: "6.8 s", latency_p95_s: 18.4, latency_p95_str: "18.4 s",
        avg_cost_per_q: 0.0345, avg_cost_per_q_str: "$0.0345", total_cost: 0.59, needs_review_count: 1
      },
      {
        agent_label: "OWIsMind orchestrator", mode: "Smart", n_questions: 18, n_ok: 18, n_error: 0,
        error_rate: 0.0, error_rate_str: "0.0 %", accuracy: 0.8333, accuracy_pct: "83.3 %", mean_score: 3.9,
        latency_p50_s: 4.2, latency_p50_str: "4.2 s", latency_p95_s: 11.8, latency_p95_str: "11.8 s",
        avg_cost_per_q: 0.0123, avg_cost_per_q_str: "$0.0123", total_cost: 0.22, needs_review_count: 2
      }
    ]
  };

  var MOCK_BREAKDOWN = {
    status: "ok",
    run_id: MOCK_RUN_ID,
    rows: [
      { agent_label: "OWIsMind orchestrator", mode: "Smart", dimension: "category", bucket: "Revenue", n: 10, accuracy: 0.90, accuracy_pct: "90.0 %", mean_score: 4.2 },
      { agent_label: "OWIsMind orchestrator", mode: "Smart", dimension: "category", bucket: "Trouble tickets", n: 8, accuracy: 0.75, accuracy_pct: "75.0 %", mean_score: 3.5 },
      { agent_label: "OWIsMind orchestrator", mode: "Pro", dimension: "category", bucket: "Revenue", n: 10, accuracy: 0.90, accuracy_pct: "90.0 %", mean_score: 4.3 },
      { agent_label: "OWIsMind orchestrator", mode: "Pro", dimension: "category", bucket: "Trouble tickets", n: 7, accuracy: 0.857, accuracy_pct: "85.7 %", mean_score: 3.9 },
      { agent_label: "OWIsMind orchestrator", mode: "Claude", dimension: "category", bucket: "Revenue", n: 10, accuracy: 1.0, accuracy_pct: "100.0 %", mean_score: 4.8 },
      { agent_label: "OWIsMind orchestrator", mode: "Claude", dimension: "category", bucket: "Trouble tickets", n: 8, accuracy: 0.875, accuracy_pct: "87.5 %", mean_score: 4.4 }
    ]
  };

  var MOCK_DETAIL = {
    status: "ok",
    run_id: MOCK_RUN_ID,
    count: 7,
    rows: [
      {
        question_id: "q_rev_01", question: "What was the total actual revenue in 2025?", category: "Revenue",
        agent_label: "OWIsMind orchestrator", mode: "Claude", status: "ok", objective_match: "hit",
        judge_score: 5, judge_verdict: "Exact match with the reference figure.", correct: true, needs_review: false,
        reference_answer: "EUR 1,284,300,000", answer_preview: "The total actual revenue for 2025 was EUR 1.28 billion (1,284,300,000), all scenarios actuals.",
        latency_total_s: 11.2, latency_str: "11.2 s", estimated_cost: 0.0812
      },
      {
        question_id: "q_rev_02", question: "Which are the top 5 customers by revenue year to date?", category: "Revenue",
        agent_label: "OWIsMind orchestrator", mode: "Smart", status: "ok", objective_match: "hit",
        judge_score: 4, judge_verdict: "Correct ranking, minor rounding on amounts.", correct: true, needs_review: false,
        reference_answer: "Airbus, Maroc Telecom, Orange, Vodafone, MTN", answer_preview: "The top 5 customers year to date are Airbus, Maroc Telecom, Orange, Vodafone and MTN.",
        latency_total_s: 4.6, latency_str: "4.6 s", estimated_cost: 0.0121
      },
      {
        question_id: "q_tic_01", question: "How many open trouble tickets does customer Airbus have?", category: "Trouble tickets",
        agent_label: "OWIsMind orchestrator", mode: "Pro", status: "ok", objective_match: "miss",
        judge_score: 2, judge_verdict: "Wrong count: the agent used all snapshots, not the latest state.", correct: false, needs_review: false,
        reference_answer: "12 open tickets", answer_preview: "Airbus currently has 47 open trouble tickets across all services.",
        latency_total_s: 7.1, latency_str: "7.1 s", estimated_cost: 0.0301
      },
      {
        question_id: "q_tic_02", question: "What was the average resolution time last quarter?", category: "Trouble tickets",
        agent_label: "OWIsMind orchestrator", mode: "Smart", status: "ok", objective_match: "hit",
        judge_score: 3, judge_verdict: "Right number but the agent mixed minutes and hours in the wording.", correct: true, needs_review: true,
        reference_answer: "318 minutes", answer_preview: "The average resolution time last quarter was about 318 minutes (5.3 hours).",
        latency_total_s: 5.3, latency_str: "5.3 s", estimated_cost: 0.0114
      },
      {
        question_id: "q_rev_03", question: "What was the revenue from the Roaming Sponsor offer in Q3?", category: "Revenue",
        agent_label: "OWIsMind orchestrator", mode: "Claude", status: "ok", objective_match: "n/a",
        judge_score: 4, judge_verdict: "Plausible and well sourced, but no objective reference to compare against.", correct: true, needs_review: true,
        reference_answer: "", answer_preview: "Q3 revenue from the Roaming Sponsor offer was EUR 18.4 million, actuals scenario.",
        latency_total_s: 13.8, latency_str: "13.8 s", estimated_cost: 0.0903
      },
      {
        question_id: "q_tic_03", question: "Which account has had the most incidents this year?", category: "Trouble tickets",
        agent_label: "OWIsMind orchestrator", mode: "Pro", status: "error", objective_match: "error",
        judge_score: 1, judge_verdict: "The agent returned a connection error and produced no answer.", correct: false, needs_review: false,
        reference_answer: "Maroc Telecom", answer_preview: "",
        latency_total_s: 30.0, latency_str: "30.0 s", estimated_cost: 0.0
      },
      {
        question_id: "q_rev_04", question: "What is the budget versus actual for the EVPL product?", category: "Revenue",
        agent_label: "OWIsMind orchestrator", mode: "Smart", status: "ok", objective_match: "miss",
        judge_score: 2, judge_verdict: "Budget reported as zero: the agent pinned the wrong offer column.", correct: false, needs_review: false,
        reference_answer: "Budget EUR 42.0M, Actual EUR 39.7M", answer_preview: "EVPL shows an actual of EUR 39.7M and a budget of EUR 0, so it is fully over budget.",
        latency_total_s: 6.2, latency_str: "6.2 s", estimated_cost: 0.0131
      }
    ]
  };

  /* --------------------------------------------------------------- boot */

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
