/* OWIsMind Benchmark - PUBLIC RESULTS webapp (framework-free vanilla JS, no build).
 *
 * A plain-language, read-only report of how the OWIsMind agents answered a benchmark run: a
 * headline correct-answer rate (donut + verdict), KPIs, per-configuration performance, accuracy by
 * topic, and a question-by-question table with expandable evidence. Data comes from the read-only
 * Python backend via getWebAppBackendUrl('api/results/...'). When that helper is absent (offline
 * preview) MOCK serves representative sample data so preview.html renders a full page.
 *
 * UI ported from the OWIsMind Results mockup (hero, KPIs, configuration cards, topic bars, results
 * table, reference aside), minus the left rail. The whole interface is rendered by this script into
 * #bench-app, so the run / language / theme controls re-render in place. Bilingual: English default,
 * French via the top-right toggle (persisted). Numbers are formatted client-side per the active
 * locale. Orange charter styling lives in style.css. */

(function () {
  "use strict";

  /* ============================ icons ============================ */

  var I = {
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 5v14M5 12h14"/></svg>',
    minus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M5 12h14"/></svg>',
    flag: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 21V4h12l-2 4 2 4H5"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M5 12l5 5 9-10"/></svg>',
    up: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
    down: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M12 5v14M5 12l7 7 7-7"/></svg>',
    eq: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"><path d="M5 9h14M5 15h14"/></svg>'
  };

  /* ============================ i18n ============================ */

  var DICT = {
    "wm.a": { en: "OWIsMind", fr: "OWIsMind" },
    "wm.b": { en: "Benchmark", fr: "Benchmark" },

    "hdr.eyebrow": { en: "Agent benchmark", fr: "Benchmark des agents" },
    "hdr.h1": { en: "How well do the OWIsMind agents answer?", fr: "Quelle est la qualite des reponses des agents OWIsMind ?" },
    "hdr.sub": {
      en: "An independent, repeatable test of our AI agents. It measures, in plain language, how often they are right, how fast they answer, and what each answer costs.",
      fr: "Un test independant et reproductible de nos agents IA. Il mesure, en clair, a quelle frequence ils ont raison, leur rapidite de reponse et le cout de chaque reponse."
    },
    "bench.label": { en: "Benchmark", fr: "Benchmark" },

    "state.loading": { en: "Loading the benchmark...", fr: "Chargement du benchmark..." },
    "state.error": { en: "Could not load the benchmark results. Check your access to the LAB project.", fr: "Impossible de charger les resultats. Verifiez votre acces au projet LAB." },
    "state.empty": { en: "No benchmark has been recorded yet. Create one from the Launcher app.", fr: "Aucun benchmark n'a encore ete enregistre. Creez-en un depuis l'application Lanceur." },

    "hero.head": {
      en: "OWIsMind gave the right answer in {r} of {t} answers produced, across all configurations",
      fr: "OWIsMind a donne la bonne reponse {r} fois sur {t} reponses produites, toutes configurations confondues"
    },
    "hero.bench": { en: "Benchmark: {n}", fr: "Benchmark : {n}" },
    "hero.correct": { en: "Correct answers", fr: "Bonnes reponses" },
    "hero.note": { en: "How often the AI gives the right answer.", fr: "A quelle frequence l'IA donne la bonne reponse." },
    "hero.meta": {
      en: "Each of the {q} validated question(s) is asked in {c} configuration(s), which is {a} attempts in total.",
      fr: "Chaque question validee ({q}) est posee dans {c} configuration(s), soit {a} tentatives au total."
    },
    "v.bad": { en: "Often incorrect", fr: "Souvent incorrect" },
    "v.mid": { en: "Mixed results", fr: "Resultats mitiges" },
    "v.good": { en: "Mostly correct", fr: "Majoritairement correct" },

    "kpi.correct": { en: "Correct answers", fr: "Bonnes reponses" },
    "kpi.correct.i": { en: "Share of answers that matched the expected result.", fr: "Part des reponses conformes au resultat attendu." },
    "kpi.questions": { en: "Questions tested", fr: "Questions testees" },
    "kpi.questions.i": { en: "How many validated reference questions were asked.", fr: "Nombre de questions de reference validees posees." },
    "kpi.configs": { en: "Configurations tested", fr: "Configurations testees" },
    "kpi.configs.i": { en: "Each agent runs in one or more modes; each is one configuration.", fr: "Chaque agent s'execute dans un ou plusieurs modes ; chacun est une configuration." },
    "kpi.cost": { en: "Total cost", fr: "Cout total" },
    "kpi.cost.i": { en: "Total model cost of producing every answer in this run.", fr: "Cout total des modeles pour produire toutes les reponses de cette execution." },
    "kpi.dc": { en: "To double-check", fr: "A reverifier" },
    "kpi.dc.i": { en: "Answers where the automatic check and the AI judge disagreed.", fr: "Reponses ou le controle automatique et le juge IA sont en desaccord." },

    "sec.cfg": { en: "By configuration", fr: "Par configuration" },
    "sec.cfg.sub": { en: "Each agent runs in one or more modes. Here is how each one performed.", fr: "Chaque agent s'execute dans un ou plusieurs modes. Voici la performance de chacun." },
    "m.correct": { en: "Correct answers", fr: "Bonnes reponses" },
    "sm.typical": { en: "Typical response time", fr: "Temps de reponse typique" },
    "sm.typical.i": { en: "Median response time (half the answers were faster).", fr: "Temps de reponse median (la moitie des reponses ont ete plus rapides)." },
    "sm.slow": { en: "Slow-case response time", fr: "Temps de reponse pire cas" },
    "sm.slow.i": { en: "95th percentile: only the slowest answers exceed this.", fr: "95e centile : seules les reponses les plus lentes le depassent." },
    "sm.costq": { en: "Cost per question", fr: "Cout par question" },
    "sm.tech": { en: "Technical failures", fr: "Echecs techniques" },
    "sm.tech.i": { en: "Share of questions where the agent errored and produced no answer.", fr: "Part des questions ou l'agent a echoue sans produire de reponse." },

    "sec.topic": { en: "Correct answers by topic", fr: "Bonnes reponses par sujet" },
    "sec.topic.i": { en: "The correct-answer rate split by question topic.", fr: "Le taux de bonnes reponses ventile par sujet de question." },

    "sec.qq": { en: "Question by question", fr: "Question par question" },
    "qq.filter": { en: "Show only items to double-check", fr: "Afficher seulement les elements a reverifier" },
    "qq.shown": { en: "{n} answer(s) shown", fr: "{n} reponse(s) affichee(s)" },
    "qq.empty": { en: "No question-by-question results are available for this benchmark.", fr: "Aucun resultat question par question pour ce benchmark." },
    "qq.emptyFilter": { en: "Nothing to double-check here. Every answer passed both checks.", fr: "Rien a reverifier ici. Toutes les reponses ont passe les deux controles." },

    "th.q": { en: "Question", fr: "Question" },
    "th.topic": { en: "Topic", fr: "Sujet" },
    "th.cfg": { en: "Configuration", fr: "Configuration" },
    "th.result": { en: "Result", fr: "Resultat" },
    "th.judge": { en: "AI judge score", fr: "Score du juge IA" },
    "th.judge.i": { en: "5 is the closest match to the expected answer, 1 the furthest.", fr: "5 = le plus proche de la reponse attendue, 1 = le plus eloigne." },
    "th.rt": { en: "Response time", fr: "Temps de reponse" },
    "th.cost": { en: "Cost", fr: "Cout" },
    "th.dc": { en: "To double-check", fr: "A reverifier" },
    "r.ok": { en: "OK", fr: "OK" },
    "r.bad": { en: "Not OK", fr: "Non OK" },
    "r.plaus": { en: "Plausible", fr: "Plausible" },
    "score.lab": { en: "AI judge score", fr: "Score juge IA" },
    "mode.default": { en: "Standard", fr: "Standard" },
    "dc.clear": { en: "Clear", fr: "Aucun" },
    "dc.flag": { en: "Double-check", fr: "A reverifier" },
    "det.show": { en: "Show details", fr: "Voir le detail" },
    "det.hide": { en: "Hide details", fr: "Masquer le detail" },
    "det.judge": { en: "Judge note", fr: "Note du juge" },
    "det.expected": { en: "Expected answer", fr: "Reponse attendue" },
    "det.agent": { en: "Agent answer", fr: "Reponse de l'agent" },
    "det.noRef": { en: "(no expected answer for this question)", fr: "(pas de reponse attendue pour cette question)" },
    "det.noAns": { en: "(the agent produced no answer)", fr: "(l'agent n'a produit aucune reponse)" },

    "th.evo": { en: "Evolution", fr: "Evolution" },
    "th.evo.i": { en: "How this question's latest result compares to its previous attempt.", fr: "Comparaison du dernier resultat de cette question avec la tentative precedente." },
    "evo.up": { en: "Improved", fr: "Amelioration" },
    "evo.down": { en: "Regressed", fr: "Regression" },
    "evo.flat": { en: "Stable", fr: "Stable" },
    "evo.first": { en: "First attempt", fr: "1re tentative" },
    "evo.attempts": { en: "{n} attempts", fr: "{n} tentatives" },
    "evo.h": { en: "Attempt history", fr: "Historique des tentatives" },
    "evo.th.no": { en: "Attempt", fr: "Tentative" },
    "evo.th.when": { en: "When", fr: "Date" },
    "evo.th.cfg": { en: "Mode", fr: "Mode" },
    "evo.th.result": { en: "Result", fr: "Resultat" },
    "evo.th.score": { en: "Score", fr: "Score" },
    "evo.latest": { en: "Latest", fr: "Dernier" },

    "ref.vs.h": { en: "Reference vs produced", fr: "Reference et production" },
    "ref.vs.note": { en: "The reference is a soft hint for the judge, not a requirement. A different but correct query or tool is fully valid.", fr: "La reference est un indice non contraignant pour le juge, pas une obligation. Une requete ou un outil different mais correct reste pleinement valide." },
    "ref.sql": { en: "Reference SQL", fr: "SQL de reference" },
    "ref.tool": { en: "Suggested tool", fr: "Outil suggere" },
    "act.tools": { en: "Tools used by the agent", fr: "Outils utilises par l'agent" },
    "ref.none": { en: "(none)", fr: "(aucun)" },

    "det.human": { en: "Reviewer adjustment", fr: "Ajustement du relecteur" },

    "ref.measure.h": { en: "How we measure this", fr: "Comment nous mesurons" },
    "ref.measure.p": {
      en: "We ask the agents a set of validated questions whose correct answers we already know. Each answer is checked automatically and by an independent AI judge. This page shows how often the agents are right, how fast they answer, and what a human should double-check.",
      fr: "Nous posons aux agents un ensemble de questions validees dont nous connaissons deja les bonnes reponses. Chaque reponse est verifiee automatiquement et par un juge IA independant. Cette page montre la justesse, la rapidite et ce qu'un humain doit reverifier."
    },
    "ref.score.h": { en: "How to read the scores", fr: "Comment lire les scores" },
    "ref.score.judge.t": { en: "AI judge score", fr: "Score du juge IA" },
    "ref.score.judge.d": { en: "5 is the closest match to the expected answer, 1 the furthest.", fr: "5 = le plus proche de la reponse attendue, 1 = le plus eloigne." },
    "ref.score.plaus.t": { en: "Plausible", fr: "Plausible" },
    "ref.score.plaus.d": { en: "The judge accepted the answer, but there is no known correct answer to compare against.", fr: "Le juge a accepte la reponse, mais il n'existe pas de reponse correcte connue pour comparer." },
    "ref.score.dc.t": { en: "To double-check", fr: "A reverifier" },
    "ref.score.dc.d": { en: "The automatic check and the AI judge disagreed, so a human should look.", fr: "La verification automatique et le juge IA sont en desaccord : un humain doit regarder." },
    "ref.modes.h": { en: "What the modes mean", fr: "Que signifient les modes" },
    "ref.modes.p": { en: "Smart, Pro and Claude are AI model tiers, from cheaper and faster to stronger and more expensive.", fr: "Smart, Pro et Claude sont des niveaux de modele IA, du plus economique et rapide au plus puissant et couteux." },
    "ref.modes.std": { en: "Standard means the agent runs in a single mode, with no tier to choose.", fr: "Standard signifie que l'agent s'execute en un seul mode, sans niveau a choisir." }
  };

  function t(key, vars) {
    var entry = DICT[key];
    var s = entry ? (entry[ui.lang] || entry.en) : key;
    if (vars) {
      for (var k in vars) {
        if (Object.prototype.hasOwnProperty.call(vars, k)) {
          s = s.split("{" + k + "}").join(vars[k]);
        }
      }
    }
    return s;
  }

  /* ============================ state ============================ */

  var ui = { theme: "light", lang: "en" };
  var state = {
    benchmarks: [],
    benchmarkId: null,
    benchmarkName: "",
    summary: null,
    breakdown: null,
    detail: null,
    dcOnly: false,
    status: "loading" // loading | ok | error | empty
  };

  /* ============================ helpers ============================ */

  function byId(id) { return document.getElementById(id); }
  function qsa(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function locale() { return ui.lang === "fr" ? "fr-FR" : "en-US"; }
  function toNum(v) {
    if (v === null || v === undefined || v === "") { return null; }
    var f = typeof v === "number" ? v : parseFloat(v);
    if (isNaN(f) || !isFinite(f)) { return null; }
    return f;
  }
  function fmtPct(frac) {
    var f = toNum(frac);
    if (f == null) { return "-"; }
    return (f * 100).toLocaleString(locale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " %";
  }
  function fmtSecs(v) {
    var f = toNum(v);
    if (f == null) { return "-"; }
    return f.toLocaleString(locale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + " s";
  }
  function fmtMoney(v, dec) {
    var f = toNum(v);
    if (f == null) { return "-"; }
    var d = (dec == null) ? 4 : dec;
    try {
      return f.toLocaleString(locale(), { style: "currency", currency: "USD", minimumFractionDigits: d, maximumFractionDigits: d });
    } catch (e) {
      return "$" + f.toFixed(d);
    }
  }
  function fmtInt(v) {
    var f = toNum(v);
    if (f == null) { return "0"; }
    return Math.round(f).toLocaleString(locale());
  }
  function modeClass(mode) {
    var m = String(mode || "").toLowerCase();
    if (m === "smart") { return "mode-smart"; }
    if (m === "pro") { return "mode-pro"; }
    if (m === "claude") { return "mode-claude"; }
    return "mode-default";
  }
  function modeColor(mode) {
    var m = String(mode || "").toLowerCase();
    if (m === "smart") { return "var(--m-smart)"; }
    if (m === "pro") { return "var(--m-pro)"; }
    if (m === "claude") { return "var(--m-claude)"; }
    return "var(--m-std)";
  }
  function modeLabel(mode) {
    var m = String(mode || "");
    if (m === "Smart" || m === "Pro" || m === "Claude") { return m; }
    if (!m || m.toLowerCase() === "default") { return t("mode.default"); }
    return m;
  }

  /* ============================ API + MOCK ============================ */

  function api(path) {
    if (typeof getWebAppBackendUrl !== "function") {
      return new Promise(function (resolve) { setTimeout(function () { resolve(MOCK(path)); }, 100); });
    }
    return fetch(getWebAppBackendUrl(path), { headers: { Accept: "application/json" } })
      .then(function (res) { if (!res.ok) { throw new Error("http " + res.status); } return res.json(); })
      .then(function (data) {
        if (!data || data.status !== "ok") { throw new Error((data && data.error) || "error"); }
        return data;
      });
  }

  function MOCK(path) {
    var clean = path.split("?")[0];
    if (clean === "api/results/benchmarks") { return MOCK_BENCHMARKS; }
    if (clean === "api/results/summary") { return MOCK_SUMMARY; }
    if (clean === "api/results/breakdown") { return MOCK_BREAKDOWN; }
    if (clean === "api/results/detail") { return MOCK_DETAIL; }
    return { status: "ok" };
  }

  var MOCK_BID = "bm_3f1a9c2e";
  var MOCK_BENCHMARKS = {
    status: "ok",
    benchmarks: [
      { benchmark_id: MOCK_BID, benchmark_name: "said", last_run_timestamp: "2026-06-29 22:14:03" },
      { benchmark_id: "bm_8b07d551", benchmark_name: "tickets-deep-dive", last_run_timestamp: "2026-06-27 09:41:17" }
    ]
  };
  var MOCK_SUMMARY = {
    status: "ok", benchmark_id: MOCK_BID, benchmark_name: "said",
    kpis: { accuracy: 0.8868, accuracy_pct: "88.7 %", n_correct: 47, n_ok_total: 53, band: "high", n_questions: 18, n_configs: 3, total_cost: 2.34, total_cost_str: "$2.34", judge_cost_str: "$0.18", needs_review: 4 },
    rows: [
      { agent_label: "OWIsMind orchestrator", mode: "Claude", n_questions: 18, n_ok: 18, n_error: 0, error_rate: 0.0, error_rate_str: "0.0 %", accuracy: 0.9444, accuracy_pct: "94.4 %", mean_score: 4.6, latency_p50_s: 12.4, latency_p50_str: "12.4 s", latency_p95_s: 28.9, latency_p95_str: "28.9 s", avg_cost_per_q: 0.0892, avg_cost_per_q_str: "$0.0892", total_cost: 1.53, needs_review_count: 1 },
      { agent_label: "OWIsMind orchestrator", mode: "Pro", n_questions: 18, n_ok: 17, n_error: 1, error_rate: 0.0556, error_rate_str: "5.6 %", accuracy: 0.8824, accuracy_pct: "88.2 %", mean_score: 4.1, latency_p50_s: 6.8, latency_p50_str: "6.8 s", latency_p95_s: 18.4, latency_p95_str: "18.4 s", avg_cost_per_q: 0.0345, avg_cost_per_q_str: "$0.0345", total_cost: 0.59, needs_review_count: 1 },
      { agent_label: "OWIsMind orchestrator", mode: "Smart", n_questions: 18, n_ok: 18, n_error: 0, error_rate: 0.0, error_rate_str: "0.0 %", accuracy: 0.8333, accuracy_pct: "83.3 %", mean_score: 3.9, latency_p50_s: 4.2, latency_p50_str: "4.2 s", latency_p95_s: 11.8, latency_p95_str: "11.8 s", avg_cost_per_q: 0.0123, avg_cost_per_q_str: "$0.0123", total_cost: 0.22, needs_review_count: 2 }
    ]
  };
  var MOCK_BREAKDOWN = {
    status: "ok", benchmark_id: MOCK_BID,
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
    status: "ok", benchmark_id: MOCK_BID, count: 7,
    rows: [
      { question_id: "q_rev_01", question: "What was the total actual revenue in 2025?", category: "Revenue", run_id: "run_2026-06-29_22-14", run_timestamp: "2026-06-29 22:14", agent_key: "038G7mlF", agent_label: "OWIsMind orchestrator", mode: "Claude", status: "ok", objective_match: "hit", judge_score: 5, judge_verdict: "Exact match with the reference figure.", judge_comment: "Figure and scenario both correct.", correct: true, needs_review: false, reference_answer: "EUR 1,284,300,000", answer_preview: "The total actual revenue for 2025 was EUR 1.28 billion (1,284,300,000), all scenarios actuals.", latency_str: "11.2 s", estimated_cost: 0.0812, notes: "", expected_value: "1284300000", expected_value_type: "amount", benchmark_id: MOCK_BID, benchmark_name: "said", attempt_no: 2, expected_sql: "SELECT SUM(amount_eur) FROM drive_revenues WHERE phase='ACTUALS' AND year=2025", expected_tool: "show_table", actual_tools: "table", effective_correct: true, effective_verdict: "OK", overridden: false, n_attempts: 2, delta: "improved",
        attempts: [
          { attempt_no: 1, run_timestamp: "2026-06-28 17:02", mode: "Claude", status: "ok", judge_score: 3, judge_verdict: "Right total but wrong scenario wording.", verdict: "OK", correct: true, overridden: false },
          { attempt_no: 2, run_timestamp: "2026-06-29 22:14", mode: "Claude", status: "ok", judge_score: 5, judge_verdict: "Exact match with the reference figure.", verdict: "OK", correct: true, overridden: false }
        ] },
      { question_id: "q_rev_02", question: "Which are the top 5 customers by revenue year to date?", category: "Revenue", run_id: "run_2026-06-29_22-14", run_timestamp: "2026-06-29 22:14", agent_key: "038G7mlF", agent_label: "OWIsMind orchestrator", mode: "Smart", status: "ok", objective_match: "hit", judge_score: 4, judge_verdict: "Correct ranking, minor rounding on amounts.", judge_comment: "", correct: true, needs_review: false, reference_answer: "Airbus, Maroc Telecom, Orange, Vodafone, MTN", answer_preview: "The top 5 customers year to date are Airbus, Maroc Telecom, Orange, Vodafone and MTN.", latency_str: "4.6 s", estimated_cost: 0.0121, notes: "", expected_value: "", expected_value_type: "", benchmark_id: MOCK_BID, benchmark_name: "said", attempt_no: 1, expected_sql: "SELECT customer, SUM(amount_eur) AS rev FROM drive_revenues GROUP BY customer ORDER BY rev DESC LIMIT 5", expected_tool: "show_chart", actual_tools: "chart,table", effective_correct: true, effective_verdict: "OK", overridden: false, n_attempts: 1, delta: "first",
        attempts: [
          { attempt_no: 1, run_timestamp: "2026-06-29 22:14", mode: "Smart", status: "ok", judge_score: 4, judge_verdict: "Correct ranking, minor rounding on amounts.", verdict: "OK", correct: true, overridden: false }
        ] },
      { question_id: "q_tic_01", question: "How many open trouble tickets does customer Airbus have?", category: "Trouble tickets", run_id: "run_2026-06-29_22-14", run_timestamp: "2026-06-29 22:14", agent_key: "038G7mlF", agent_label: "OWIsMind orchestrator", mode: "Pro", status: "ok", objective_match: "miss", judge_score: 2, judge_verdict: "Wrong count: the agent used all snapshots, not the latest state.", judge_comment: "Did not deduplicate snapshots.", correct: false, needs_review: false, reference_answer: "12 open tickets", answer_preview: "Airbus currently has 47 open trouble tickets across all services.", latency_str: "7.1 s", estimated_cost: 0.0301, notes: "", expected_value: "12", expected_value_type: "count", benchmark_id: MOCK_BID, benchmark_name: "said", attempt_no: 2, expected_sql: "SELECT COUNT(DISTINCT id) FROM (SELECT DISTINCT ON (id) id, CurrentStatus FROM trouble_tickets ORDER BY id, lastUpdate DESC) s WHERE CurrentStatus='OPEN'", expected_tool: "none", actual_tools: "", effective_correct: false, effective_verdict: "Not OK", overridden: false, n_attempts: 2, delta: "regressed",
        attempts: [
          { attempt_no: 1, run_timestamp: "2026-06-28 17:02", mode: "Pro", status: "ok", judge_score: 4, judge_verdict: "Right count from the latest snapshot.", verdict: "OK", correct: true, overridden: false },
          { attempt_no: 2, run_timestamp: "2026-06-29 22:14", mode: "Pro", status: "ok", judge_score: 2, judge_verdict: "Wrong count: used all snapshots.", verdict: "Not OK", correct: false, overridden: false }
        ] },
      { question_id: "q_tic_02", question: "What was the average resolution time last quarter?", category: "Trouble tickets", run_id: "run_2026-06-29_22-14", run_timestamp: "2026-06-29 22:14", agent_key: "038G7mlF", agent_label: "OWIsMind orchestrator", mode: "Smart", status: "ok", objective_match: "hit", judge_score: 3, judge_verdict: "Right number but the agent mixed minutes and hours in the wording.", judge_comment: "", correct: true, needs_review: true, reference_answer: "318 minutes", answer_preview: "The average resolution time last quarter was about 318 minutes (5.3 hours).", latency_str: "5.3 s", estimated_cost: 0.0114, notes: "", expected_value: "318", expected_value_type: "duration", benchmark_id: MOCK_BID, benchmark_name: "said", attempt_no: 1, expected_sql: "", expected_tool: "", actual_tools: "table", effective_correct: true, effective_verdict: "OK", overridden: false, n_attempts: 1, delta: "first",
        attempts: [
          { attempt_no: 1, run_timestamp: "2026-06-29 22:14", mode: "Smart", status: "ok", judge_score: 3, judge_verdict: "Right number, mixed units in wording.", verdict: "OK", correct: true, overridden: false }
        ] },
      { question_id: "q_rev_03", question: "What was the revenue from the Roaming Sponsor offer in Q3?", category: "Revenue", run_id: "run_2026-06-29_22-14", run_timestamp: "2026-06-29 22:14", agent_key: "038G7mlF", agent_label: "OWIsMind orchestrator", mode: "Claude", status: "ok", objective_match: "n/a", judge_score: 4, judge_verdict: "Plausible and well sourced, but no objective reference to compare against.", judge_comment: "", correct: true, needs_review: true, reference_answer: "", answer_preview: "Q3 revenue from the Roaming Sponsor offer was EUR 18.4 million, actuals scenario.", latency_str: "13.8 s", estimated_cost: 0.0903, notes: "", expected_value: "", expected_value_type: "", benchmark_id: MOCK_BID, benchmark_name: "said", attempt_no: 1, expected_sql: "", expected_tool: "show_chart", actual_tools: "chart", effective_correct: true, effective_verdict: "OK", overridden: false, n_attempts: 1, delta: "first",
        attempts: [
          { attempt_no: 1, run_timestamp: "2026-06-29 22:14", mode: "Claude", status: "ok", judge_score: 4, judge_verdict: "Plausible, no objective reference.", verdict: "Plausible", correct: true, overridden: false }
        ] },
      { question_id: "q_tic_03", question: "Which account has had the most incidents this year?", category: "Trouble tickets", run_id: "run_2026-06-29_22-14", run_timestamp: "2026-06-29 22:14", agent_key: "038G7mlF", agent_label: "OWIsMind orchestrator", mode: "Pro", status: "error", objective_match: "error", judge_score: 1, judge_verdict: "The agent returned a connection error and produced no answer.", judge_comment: "", correct: false, needs_review: false, reference_answer: "Maroc Telecom", answer_preview: "", latency_str: "30.0 s", estimated_cost: 0.0, notes: "connection timeout", expected_value: "", expected_value_type: "", benchmark_id: MOCK_BID, benchmark_name: "said", attempt_no: 1, expected_sql: "", expected_tool: "", actual_tools: "", effective_correct: false, effective_verdict: "Not OK", overridden: false, n_attempts: 1, delta: "first",
        attempts: [
          { attempt_no: 1, run_timestamp: "2026-06-29 22:14", mode: "Pro", status: "error", judge_score: 1, judge_verdict: "Connection error, no answer.", verdict: "Not OK", correct: false, overridden: false }
        ] },
      { question_id: "q_rev_04", question: "What is the budget versus actual for the EVPL product?", category: "Revenue", run_id: "run_2026-06-29_22-14", run_timestamp: "2026-06-29 22:14", agent_key: "038G7mlF", agent_label: "OWIsMind orchestrator", mode: "Smart", status: "ok", objective_match: "miss", judge_score: 2, judge_verdict: "Budget reported as zero: the agent pinned the wrong offer column.", judge_comment: "", correct: false, needs_review: false, reference_answer: "Budget EUR 42.0M, Actual EUR 39.7M", answer_preview: "EVPL shows an actual of EUR 39.7M and a budget of EUR 0, so it is fully over budget.", latency_str: "6.2 s", estimated_cost: 0.0131, notes: "", expected_value: "42000000", expected_value_type: "amount", benchmark_id: MOCK_BID, benchmark_name: "said", attempt_no: 3, expected_sql: "SELECT phase, SUM(amount_eur) FROM drive_revenues WHERE product='EVPL' GROUP BY phase", expected_tool: "show_table", actual_tools: "table", human_verdict: "Not OK", human_comment: "Confirmed wrong: budget column was misread.", reviewed_by: "admin", reviewed_at: "2026-06-29 23:01", effective_correct: false, effective_verdict: "Not OK", overridden: true, n_attempts: 3, delta: "same",
        attempts: [
          { attempt_no: 1, run_timestamp: "2026-06-27 10:00", mode: "Smart", status: "ok", judge_score: 2, judge_verdict: "Budget zero.", verdict: "Not OK", correct: false, overridden: false },
          { attempt_no: 2, run_timestamp: "2026-06-28 17:02", mode: "Smart", status: "ok", judge_score: 2, judge_verdict: "Budget zero again.", verdict: "Not OK", correct: false, overridden: false },
          { attempt_no: 3, run_timestamp: "2026-06-29 22:14", mode: "Smart", status: "ok", judge_score: 2, judge_verdict: "Budget zero, wrong column.", verdict: "Not OK", correct: false, overridden: true }
        ] }
    ]
  };

  /* ============================ prefs ============================ */

  function loadPrefs() {
    try { var th = localStorage.getItem("bench-res-theme"); if (th === "light" || th === "dark") { ui.theme = th; } } catch (e) { /* */ }
    try { var lg = localStorage.getItem("bench-res-lang"); if (lg === "en" || lg === "fr") { ui.lang = lg; } } catch (e2) { /* */ }
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
        '<div class="util"><span class="wm">' + esc(t("wm.a")) + ' <b>' + esc(t("wm.b")) + '</b></span><span class="util-sp"></span></div>' +
        '<header class="header">' +
          '<div>' +
            '<p class="eyebrow" data-i18n="hdr.eyebrow"></p>' +
            '<h1 data-i18n="hdr.h1"></h1>' +
            '<div class="title-bar"></div>' +
            '<p class="header-sub" data-i18n="hdr.sub"></p>' +
          '</div>' +
          '<div class="controls">' +
            '<div class="run-select"><span class="lbl" data-i18n="bench.label"></span><select id="benchSelect"></select></div>' +
            '<div class="seg" id="langSeg"><button data-lang="en">EN</button><button data-lang="fr">FR</button></div>' +
            '<div class="seg" id="themeSeg"><button data-theme="light">LIGHT</button><button data-theme="dark">DARK</button></div>' +
          '</div>' +
        '</header>' +
        '<div class="body">' +
          '<main class="content"><div id="resContent"></div></main>' +
          asideHtml() +
        '</div>' +
      '</div>';
  }

  function asideHtml() {
    return '' +
      '<aside class="aside">' +
        '<div class="ref-block">' +
          '<p class="ref-h" data-i18n="ref.measure.h"></p>' +
          '<p class="ref-p" data-i18n="ref.measure.p"></p>' +
        '</div>' +
        '<div class="ref-block">' +
          '<p class="ref-h" data-i18n="ref.score.h"></p>' +
          '<dl class="ref-dl">' +
            '<div class="r"><dt data-i18n="ref.score.judge.t"></dt><dd data-i18n="ref.score.judge.d"></dd></div>' +
            '<div class="r"><dt data-i18n="ref.score.plaus.t"></dt><dd data-i18n="ref.score.plaus.d"></dd></div>' +
            '<div class="r"><dt data-i18n="ref.score.dc.t"></dt><dd data-i18n="ref.score.dc.d"></dd></div>' +
          '</dl>' +
        '</div>' +
        '<div class="ref-block">' +
          '<p class="ref-h" data-i18n="ref.modes.h"></p>' +
          '<p class="ref-p" data-i18n="ref.modes.p"></p>' +
          '<div class="legend">' +
            '<div class="l"><span class="dot" style="background:var(--m-smart)"></span>Smart</div>' +
            '<div class="l"><span class="dot" style="background:var(--m-pro)"></span>Pro</div>' +
            '<div class="l"><span class="dot" style="background:var(--m-claude)"></span>Claude</div>' +
            '<div class="l"><span class="dot" style="background:var(--m-std)"></span>Standard</div>' +
          '</div>' +
          '<p class="ref-p" style="margin-top:12px" data-i18n="ref.modes.std"></p>' +
        '</div>' +
      '</aside>';
  }

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
    syncSeg("themeSeg", "data-theme", ui.theme);
    renderBenchSelect();
    renderContent();
  }

  function syncSeg(segId, attr, value) {
    qsa("#" + segId + " button").forEach(function (b) { b.classList.toggle("on", b.getAttribute(attr) === value); });
  }

  function renderBenchSelect() {
    var sel = byId("benchSelect");
    if (!sel) { return; }
    sel.innerHTML = state.benchmarks.map(function (b) {
      var on = b.benchmark_id === state.benchmarkId ? " selected" : "";
      var name = b.benchmark_name || b.benchmark_id;
      var label = name + (b.last_run_timestamp ? " - " + b.last_run_timestamp : "");
      return '<option value="' + esc(b.benchmark_id) + '"' + on + ' title="' + esc(b.benchmark_id) + '">' + esc(label) + '</option>';
    }).join("");
  }

  function stateBlock(msg, cls) {
    return '<div class="state-block' + (cls ? " " + cls : "") + '">' + esc(msg) + '</div>';
  }

  function renderContent() {
    var c = byId("resContent");
    if (!c) { return; }
    if (state.status === "loading") { c.innerHTML = stateBlock(t("state.loading")); return; }
    if (state.status === "error") { c.innerHTML = stateBlock(t("state.error"), "error"); return; }
    if (state.status === "empty") { c.innerHTML = stateBlock(t("state.empty")); return; }
    c.innerHTML = heroSection() + configSection() + topicSection() + qqSection();
    wireContent();
  }

  /* --- hero + kpis --- */

  function heroSection() {
    var k = (state.summary && state.summary.kpis) || {};
    var frac = toNum(k.accuracy) || 0;
    var band = k.band || (frac >= 0.85 ? "high" : (frac >= 0.6 ? "medium" : "low"));
    var vkind = band === "high" ? "good" : (band === "medium" ? "mid" : "bad");
    var vkey = band === "high" ? "v.good" : (band === "medium" ? "v.mid" : "v.bad");

    var r = 80, C = 2 * Math.PI * r, off = C * (1 - frac);
    var donut = '<div class="donut">' +
      '<svg width="188" height="188" viewBox="0 0 188 188">' +
        '<circle cx="94" cy="94" r="80" fill="none" style="stroke:var(--soft-2)" stroke-width="16"/>' +
        '<circle cx="94" cy="94" r="80" fill="none" style="stroke:var(--orange)" stroke-width="16" stroke-dasharray="' + C + '" stroke-dashoffset="' + off + '" stroke-linecap="butt"/>' +
      '</svg>' +
      '<div class="d-center"><div class="d-pct">' + esc(fmtPct(frac)) + '</div><div class="d-lab">' + esc(t("hero.correct")) + '</div></div>' +
    '</div>';

    var head = esc(t("hero.head", { r: "@@R@@", t: "@@T@@" }))
      .replace("@@R@@", '<span class="hl">' + esc(fmtInt(k.n_correct)) + '</span>')
      .replace("@@T@@", '<span class="hl">' + esc(fmtInt(k.n_ok_total)) + '</span>');

    var attempts = (toNum(k.n_questions) || 0) * (toNum(k.n_configs) || 0);
    var meta = esc(t("hero.meta", { q: "@@Q@@", c: "@@C@@", a: "@@A@@" }))
      .replace("@@Q@@", '<b>' + esc(fmtInt(k.n_questions)) + '</b>')
      .replace("@@C@@", '<b>' + esc(fmtInt(k.n_configs)) + '</b>')
      .replace("@@A@@", '<b>' + esc(fmtInt(attempts)) + '</b>');

    var benchName = state.benchmarkName || (state.summary && state.summary.benchmark_name) || "";
    var benchLine = benchName
      ? '<p class="hero-bench">' + esc(t("hero.bench", { n: benchName })) + '</p>'
      : "";

    var hero = '<div class="hero">' + donut +
      '<div>' +
        benchLine +
        '<h2 class="hero-head">' + head + '</h2>' +
        '<span class="verdict ' + vkind + '"><span class="sq"></span>' + esc(t(vkey)) + '</span>' +
        '<p class="hero-note">' + esc(t("hero.note")) + '</p>' +
        '<p class="hero-meta">' + meta + '</p>' +
      '</div>' +
    '</div>';

    var kpis = [
      { l: "kpi.correct", i: "kpi.correct.i", v: fmtPct(k.accuracy) },
      { l: "kpi.questions", i: "kpi.questions.i", v: fmtInt(k.n_questions) },
      { l: "kpi.configs", i: "kpi.configs.i", v: fmtInt(k.n_configs) },
      { l: "kpi.cost", i: "kpi.cost.i", v: fmtMoney(k.total_cost, 2), sm: true },
      { l: "kpi.dc", i: "kpi.dc.i", v: fmtInt(k.needs_review), flag: (toNum(k.needs_review) || 0) > 0 }
    ].map(function (d) {
      return '<div class="kpi">' +
        '<div class="k-top"><span class="k-lab">' + esc(t(d.l)) + '</span><span class="info-i" title="' + esc(t(d.i)) + '">i</span></div>' +
        '<div class="k-val' + (d.sm ? " sm" : "") + (d.flag ? " flag" : "") + '">' + esc(String(d.v)) + '</div>' +
      '</div>';
    }).join("");

    return '<section class="section">' + hero + '<div class="kpis">' + kpis + '</div></section>';
  }

  /* --- by configuration --- */

  function configSection() {
    var rows = (state.summary && state.summary.rows) || [];
    var cards = rows.map(function (r) {
      var acc = (toNum(r.accuracy) || 0) * 100;
      var errBad = (toNum(r.error_rate) || 0) > 0;
      function sub(k, v, info, bad) {
        var ic = info ? '<span class="info-i" title="' + esc(t(info)) + '">i</span>' : "";
        return '<div class="submetric"><div class="sl">' + esc(t(k)) + ic + '</div><div class="sv' + (bad ? " bad" : "") + '">' + esc(v) + '</div></div>';
      }
      return '<div class="cfg-card">' +
        '<div class="cfg-top">' +
          '<span class="cfg-name">' + esc(r.agent_label) + '</span>' +
          '<span class="mode-badge ' + modeClass(r.mode) + '"><span class="dot"></span>' + esc(modeLabel(r.mode)) + '</span>' +
          '<span class="cfg-q">' + esc(fmtInt(r.n_questions)) + ' ' + esc(t("th.q").toLowerCase()) + '</span>' +
        '</div>' +
        '<div class="meter-row">' +
          '<span class="meter-lab">' + esc(t("m.correct")) + '</span>' +
          '<span class="meter"><i style="width:' + acc + '%"></i></span>' +
          '<span class="meter-val">' + esc(fmtPct(r.accuracy)) + '</span>' +
        '</div>' +
        '<div class="submetrics">' +
          sub("sm.typical", fmtSecs(r.latency_p50_s), "sm.typical.i") +
          sub("sm.slow", fmtSecs(r.latency_p95_s), "sm.slow.i") +
          sub("sm.costq", fmtMoney(r.avg_cost_per_q, 4), null) +
          sub("sm.tech", fmtPct(r.error_rate), "sm.tech.i", errBad) +
        '</div>' +
      '</div>';
    }).join("");
    return '<section class="section">' +
      '<div class="section-h"><h2>' + esc(t("sec.cfg")) + '</h2></div>' +
      '<p class="section-sub">' + esc(t("sec.cfg.sub")) + '</p>' + cards +
    '</section>';
  }

  /* --- by topic --- */

  function topicSection() {
    var rows = ((state.breakdown && state.breakdown.rows) || []).filter(function (r) {
      return r.dimension == null || r.dimension === "category";
    });
    if (!rows.length) { return ""; }
    var groups = [];
    var byBucket = {};
    rows.forEach(function (r) {
      var b = r.bucket || "-";
      if (!byBucket[b]) { byBucket[b] = []; groups.push(b); }
      byBucket[b].push(r);
    });
    var blocks = groups.map(function (b) {
      var inner = byBucket[b].map(function (r) {
        var acc = (toNum(r.accuracy) || 0) * 100;
        return '<div class="topic-row">' +
          '<span class="topic-agent"><span class="dot" style="background:' + modeColor(r.mode) + '"></span>' +
            esc(r.agent_label) + ' ' + esc(modeLabel(r.mode)) + '</span>' +
          '<span class="meter"><i style="width:' + acc + '%"></i></span>' +
          '<span class="meter-val">' + esc(fmtPct(r.accuracy)) + '</span>' +
          '<span class="tq">' + esc(fmtInt(r.n)) + ' ' + esc(t("th.q").toLowerCase()) + '</span>' +
        '</div>';
      }).join("");
      return '<div class="topic"><div class="topic-h">' + esc(b) + '</div>' + inner + '</div>';
    }).join("");
    return '<section class="section">' +
      '<div class="section-h"><h2>' + esc(t("sec.topic")) + '</h2><span class="info-i" title="' + esc(t("sec.topic.i")) + '">i</span></div>' +
      '<div style="margin-top:14px">' + blocks + '</div>' +
    '</section>';
  }

  /* --- question by question --- */

  /* The effective verdict prefers a human override when present. */
  function isCorrect(r) {
    if (r && r.overridden && r.effective_correct != null) { return !!r.effective_correct; }
    return !!(r && r.correct);
  }

  function classifyResult(r) {
    var ok = isCorrect(r);
    if (r.objective_match === "error" || r.status === "error") { return ["result-bad", "r.bad"]; }
    if (r.objective_match === "n/a") { return ok ? ["result-plaus", "r.plaus"] : ["result-bad", "r.bad"]; }
    return ok ? ["result-ok", "r.ok"] : ["result-bad", "r.bad"];
  }

  /* Evolution delta badge: improved (green) / regressed (red) / stable or first (neutral). */
  function evoBadge(r) {
    var d = String(r.delta || "first");
    var map = {
      improved: ["evo-up", I.up, "evo.up"],
      regressed: ["evo-down", I.down, "evo.down"],
      same: ["evo-flat", I.eq, "evo.flat"],
      first: ["evo-flat", I.eq, "evo.first"]
    };
    var m = map[d] || map.first;
    var n = toNum(r.n_attempts) || 1;
    var count = n > 1 ? '<span class="evo-n">' + esc(t("evo.attempts", { n: fmtInt(n) })) + '</span>' : "";
    return '<span class="evo ' + m[0] + '">' + m[1] + '<span>' + esc(t(m[2])) + '</span></span>' + count;
  }

  function qqSection() {
    var all = (state.detail && state.detail.rows) || [];
    var list = state.dcOnly ? all.filter(function (r) { return r.needs_review; }) : all;
    var controls = '<div class="qq-controls">' +
      '<button type="button" class="chk' + (state.dcOnly ? " on" : "") + '" data-r="dconly">' +
        '<span class="box">' + I.check + '</span><span class="chk-txt"><b>' + esc(t("qq.filter")) + '</b></span></button>' +
      '<span class="shown">' + esc(t("qq.shown", { n: fmtInt(list.length) })) + '</span>' +
    '</div>';

    var body;
    if (!all.length) {
      body = stateBlock(t("qq.empty"));
    } else if (!list.length) {
      body = stateBlock(t("qq.emptyFilter"));
    } else {
      var head = '<thead><tr>' +
        '<th>' + esc(t("th.q")) + '</th><th>' + esc(t("th.topic")) + '</th><th>' + esc(t("th.cfg")) + '</th>' +
        '<th>' + esc(t("th.result")) + '</th>' +
        '<th>' + esc(t("th.evo")) + ' <span class="info-i" title="' + esc(t("th.evo.i")) + '">i</span></th>' +
        '<th>' + esc(t("th.judge")) + ' <span class="info-i" title="' + esc(t("th.judge.i")) + '">i</span></th>' +
        '<th class="num">' + esc(t("th.rt")) + '</th><th class="num">' + esc(t("th.cost")) + '</th><th>' + esc(t("th.dc")) + '</th>' +
      '</tr></thead>';
      var rows = list.map(qRowHtml).join("");
      body = '<table class="rtable">' + head + '<tbody>' + rows + '</tbody></table>';
    }
    return '<section class="section">' +
      '<div class="section-h"><h2>' + esc(t("sec.qq")) + '</h2></div>' + controls + body +
    '</section>';
  }

  function qRowHtml(r) {
    var cls = classifyResult(r);
    var pill = '<span class="result-pill ' + cls[0] + '"><span class="sq"></span>' + esc(t(cls[1])) + '</span>';
    var js = toNum(r.judge_score);
    var noScore = js == null || r.status === "error" || r.objective_match === "error";
    var judge = '<span class="score">' + (noScore ? "-" : (esc(fmtInt(js)) + " / 5")) + '<small>' + esc(t("score.lab")) + '</small></span>';
    var dc = r.needs_review
      ? '<span class="dc-flag">' + I.flag + esc(t("dc.flag")) + '</span>'
      : '<span class="dc-clear">' + esc(t("dc.clear")) + '</span>';

    var latency = r.latency_str ? esc(r.latency_str) : esc(fmtSecs(r.latency_total_s));

    var main = '<tr>' +
      '<td data-l="' + esc(t("th.q")) + '">' +
        '<div class="q-main">' + esc(r.question) + '</div><div class="q-id">' + esc(r.question_id) + '</div>' +
        '<button type="button" class="show-details" data-r="toggle">' + I.plus + '<span data-det-label>' + esc(t("det.show")) + '</span></button>' +
      '</td>' +
      '<td data-l="' + esc(t("th.topic")) + '"><span class="lang-tag">' + esc(r.category) + '</span></td>' +
      '<td data-l="' + esc(t("th.cfg")) + '"><span class="cfg-cell"><span class="dot" style="background:' + modeColor(r.mode) + '"></span>' + esc(r.agent_label) + ' ' + esc(modeLabel(r.mode)) + '</span></td>' +
      '<td data-l="' + esc(t("th.result")) + '">' + pill + '</td>' +
      '<td data-l="' + esc(t("th.evo")) + '">' + evoBadge(r) + '</td>' +
      '<td data-l="' + esc(t("th.judge")) + '">' + judge + '</td>' +
      '<td class="num" data-l="' + esc(t("th.rt")) + '">' + latency + '</td>' +
      '<td class="num" data-l="' + esc(t("th.cost")) + '">' + esc(fmtMoney(r.estimated_cost, 4)) + '</td>' +
      '<td data-l="' + esc(t("th.dc")) + '">' + dc + '</td>' +
    '</tr>';

    var ref = r.reference_answer ? esc(r.reference_answer) : esc(t("det.noRef"));
    var ans = r.answer_preview ? esc(r.answer_preview) : esc(t("det.noAns"));
    var detail = '<tr class="detail-row" style="display:none"><td colspan="9">' +
      '<div class="detail">' +
        '<div class="d-full"><dt>' + esc(t("det.judge")) + '</dt><div class="judge-note">' + esc(r.judge_verdict || "-") + '</div></div>' +
        humanBlock(r) +
        '<div class="answers">' +
          '<div class="ans-box expected"><div class="ans-l">' + esc(t("det.expected")) + '</div><div class="ans-t">' + ref + '</div></div>' +
          '<div class="ans-box agent"><div class="ans-l">' + esc(t("det.agent")) + '</div><div class="ans-t">' + ans + '</div></div>' +
        '</div>' +
        refVsProduced(r) +
        attemptsBlock(r) +
      '</div>' +
    '</td></tr>';
    return main + detail;
  }

  /* Reviewer override note, only when a human adjusted the verdict. */
  function humanBlock(r) {
    if (!r.overridden) { return ""; }
    var v = r.human_verdict || r.effective_verdict || "-";
    var note = r.human_comment ? '<div class="judge-note">' + esc(r.human_comment) + '</div>' : "";
    return '<div class="d-full human"><dt>' + esc(t("det.human")) + '</dt>' +
      '<div><b>' + esc(v) + '</b>' + note + '</div></div>';
  }

  /* Reference SQL / suggested tool (a soft judge hint) beside the tools the agent actually used. */
  function refVsProduced(r) {
    var hasSql = r.expected_sql && String(r.expected_sql).trim() !== "";
    var hasTool = r.expected_tool && String(r.expected_tool).trim() !== "" && String(r.expected_tool).toLowerCase() !== "none";
    var hasActual = r.actual_tools && String(r.actual_tools).trim() !== "";
    if (!hasSql && !hasTool && !hasActual) { return ""; }
    var refSql = hasSql
      ? '<div class="rv-l">' + esc(t("ref.sql")) + '</div><pre class="rv-sql">' + esc(r.expected_sql) + '</pre>'
      : "";
    var refTool = '<div class="rv-pair"><span class="rv-k">' + esc(t("ref.tool")) + '</span>' +
      '<span class="rv-v">' + (hasTool ? '<code>' + esc(r.expected_tool) + '</code>' : esc(t("ref.none"))) + '</span></div>';
    var actTool = '<div class="rv-pair"><span class="rv-k">' + esc(t("act.tools")) + '</span>' +
      '<span class="rv-v">' + (hasActual ? '<code>' + esc(r.actual_tools) + '</code>' : esc(t("ref.none"))) + '</span></div>';
    return '<div class="refvs">' +
      '<div class="rv-h">' + esc(t("ref.vs.h")) + '</div>' +
      '<p class="rv-note">' + esc(t("ref.vs.note")) + '</p>' +
      refSql +
      '<div class="rv-tools">' + refTool + actTool + '</div>' +
    '</div>';
  }

  /* Attempt history table, only when the question has been run more than once. */
  function attemptsBlock(r) {
    var att = (r.attempts || []).slice();
    if (att.length < 2) { return ""; }
    var rows = att.map(function (a, i) {
      var ok = (a.overridden && a.correct != null) ? !!a.correct : !!a.correct;
      var cls = a.status === "error" ? "result-bad" : (ok ? "result-ok" : "result-bad");
      var key = a.status === "error" ? "r.bad" : (ok ? "r.ok" : "r.bad");
      var vk = a.verdict ? esc(a.verdict) : esc(t(key));
      var sc = toNum(a.judge_score);
      var score = sc == null ? "-" : (esc(fmtInt(sc)) + " / 5");
      var latest = (i === att.length - 1) ? ' <span class="evo-latest">' + esc(t("evo.latest")) + '</span>' : "";
      return '<tr>' +
        '<td>#' + esc(fmtInt(a.attempt_no)) + latest + '</td>' +
        '<td class="mono">' + esc(a.run_timestamp || "-") + '</td>' +
        '<td><span class="cfg-cell"><span class="dot" style="background:' + modeColor(a.mode) + '"></span>' + esc(modeLabel(a.mode)) + '</span></td>' +
        '<td><span class="result-pill ' + cls + '"><span class="sq"></span>' + vk + '</span></td>' +
        '<td class="mono">' + score + '</td>' +
      '</tr>';
    }).join("");
    return '<div class="attempts">' +
      '<div class="att-h">' + esc(t("evo.h")) + '</div>' +
      '<table class="att-table"><thead><tr>' +
        '<th>' + esc(t("evo.th.no")) + '</th><th>' + esc(t("evo.th.when")) + '</th>' +
        '<th>' + esc(t("evo.th.cfg")) + '</th><th>' + esc(t("evo.th.result")) + '</th><th>' + esc(t("evo.th.score")) + '</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table>' +
    '</div>';
  }

  function wireContent() {
    var c = byId("resContent");
    if (!c) { return; }
    qsa('[data-r="dconly"]', c).forEach(function (b) {
      b.addEventListener("click", function () {
        state.dcOnly = !state.dcOnly;
        try { localStorage.setItem("bench-res-dconly", state.dcOnly ? "1" : "0"); } catch (e) { /* */ }
        renderContent();
      });
    });
    qsa('[data-r="toggle"]', c).forEach(function (btn) {
      btn.addEventListener("click", function () {
        var tr = btn.closest("tr");
        var detail = tr && tr.nextElementSibling;
        if (!detail) { return; }
        var open = detail.style.display === "none";
        detail.style.display = open ? "" : "none";
        var label = btn.querySelector("[data-det-label]");
        if (label) { label.textContent = open ? t("det.hide") : t("det.show"); }
        var icon = btn.firstChild;
        if (icon && icon.outerHTML !== undefined) { icon.outerHTML = open ? I.minus : I.plus; }
      });
    });
  }

  /* ============================ data load ============================ */

  function loadAll() {
    state.status = "loading";
    render();
    api("api/results/benchmarks").then(function (d) {
      state.benchmarks = (d.benchmarks || []).slice();
      if (!state.benchmarks.length) { state.status = "empty"; render(); return; }
      state.benchmarkId = state.benchmarks[0].benchmark_id;
      state.benchmarkName = state.benchmarks[0].benchmark_name || "";
      loadBenchmark(state.benchmarkId);
    }, function () { state.status = "error"; render(); });
  }

  function loadBenchmark(benchmarkId) {
    state.status = "loading";
    render();
    var q = "?benchmark_id=" + encodeURIComponent(benchmarkId);
    Promise.all([
      api("api/results/summary" + q),
      api("api/results/breakdown" + q),
      api("api/results/detail" + q)
    ]).then(function (res) {
      state.summary = res[0];
      state.breakdown = res[1];
      state.detail = res[2];
      if (state.summary && state.summary.benchmark_name) { state.benchmarkName = state.summary.benchmark_name; }
      var hasRows = state.summary && state.summary.rows && state.summary.rows.length;
      state.status = hasRows ? "ok" : "empty";
      render();
    }, function () { state.status = "error"; render(); });
  }

  /* ============================ static wiring ============================ */

  function wireStatic() {
    qsa("#langSeg button").forEach(function (b) {
      b.addEventListener("click", function () {
        ui.lang = b.getAttribute("data-lang");
        try { localStorage.setItem("bench-res-lang", ui.lang); } catch (e) { /* */ }
        render();
      });
    });
    qsa("#themeSeg button").forEach(function (b) {
      b.addEventListener("click", function () {
        ui.theme = b.getAttribute("data-theme");
        applyTheme();
        try { localStorage.setItem("bench-res-theme", ui.theme); } catch (e) { /* */ }
        syncSeg("themeSeg", "data-theme", ui.theme);
      });
    });
    var sel = byId("benchSelect");
    if (sel) {
      sel.addEventListener("change", function () {
        if (sel.value && sel.value !== state.benchmarkId) {
          state.benchmarkId = sel.value;
          var found = state.benchmarks.filter(function (b) { return b.benchmark_id === sel.value; })[0];
          state.benchmarkName = (found && found.benchmark_name) || "";
          loadBenchmark(state.benchmarkId);
        }
      });
    }
  }

  /* ============================ init ============================ */

  function init() {
    loadPrefs();
    try { state.dcOnly = localStorage.getItem("bench-res-dconly") === "1"; } catch (e) { /* */ }
    applyTheme();
    applyLang();
    loadAll();
  }

  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", init); }
  else { init(); }
})();
