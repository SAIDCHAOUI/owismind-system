/* OWIsMind Benchmark - frontend logic for a DSS standard webapp.
   No framework, no build, no external libraries. Talks to the Flask backend through
   the DSS-injected helper getWebAppBackendUrl('api/...'). When that helper is absent
   (offline preview), the module runs in MOCK mode and serves embedded sample data so
   preview.html renders a full, representative page. Visible strings are in French,
   code and comments are in English. No em dash or en dash anywhere. */

(function () {
  "use strict";

  // Mock mode is on when the DSS backend helper is not available.
  var IS_MOCK = (typeof getWebAppBackendUrl !== "function");

  /* ------------------------------------------------------------------ */
  /* Small DOM and formatting helpers                                    */
  /* ------------------------------------------------------------------ */

  function $(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function escapeHtml(s) {
    if (s === null || s === undefined) return "";
    return String(s).replace(/[&<>"']/g, function (c) {
      return ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      })[c];
    });
  }

  function truncate(s, n) {
    s = (s === null || s === undefined) ? "" : String(s);
    if (s.length <= n) return s;
    return s.slice(0, n - 3) + "...";
  }

  function clampPct(x) {
    x = Number(x);
    if (!isFinite(x)) return 0;
    if (x < 0) return 0;
    if (x > 100) return 100;
    return Math.round(x * 10) / 10;
  }

  function modeClass(mode) {
    var m = (mode || "").toLowerCase();
    if (m === "smart") return "smart";
    if (m === "pro") return "pro";
    if (m === "claude") return "claude";
    return "default";
  }

  function chip(mode) {
    return '<span class="chip mode-' + modeClass(mode) + '">' +
      escapeHtml(mode == null ? "-" : mode) + "</span>";
  }

  function barRow(label, pct, cls) {
    return '<div class="bar-row"><span class="bar-val">' +
      escapeHtml(label == null ? "-" : label) + "</span>" +
      '<span class="bar"><span class="bar-fill mode-' + cls +
      '" style="width:' + pct + '%"></span></span></div>';
  }

  function box(kind, title, list) {
    var cls = kind === "error" ? "box-error" : (kind === "success" ? "box-success" : "box-info");
    var h = '<div class="box ' + cls + '">' + escapeHtml(title);
    if (list && list.length) {
      h += "<ul>" + list.map(function (m) {
        return "<li>" + escapeHtml(m) + "</li>";
      }).join("") + "</ul>";
    }
    h += "</div>";
    return h;
  }

  function emptyNote(txt) { return '<div class="empty">' + escapeHtml(txt) + "</div>"; }

  function setBusy(btn, busy) { if (btn) btn.disabled = !!busy; }

  /* ------------------------------------------------------------------ */
  /* API layer                                                           */
  /* ------------------------------------------------------------------ */

  // Resolves to { http: number, ok: boolean, json: object }.
  function api(path, opts) {
    opts = opts || {};
    if (IS_MOCK) {
      return Promise.resolve(mockApi(path, opts));
    }
    var url = getWebAppBackendUrl(path);
    var init = { method: opts.method || (opts.body ? "POST" : "GET"), headers: {} };
    if (opts.body) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    return fetch(url, init).then(function (resp) {
      return resp.text().then(function (txt) {
        var json;
        try { json = txt ? JSON.parse(txt) : {}; }
        catch (e) { json = { status: "error", error: "bad_json" }; }
        return { http: resp.status, ok: resp.ok, json: json };
      });
    }).catch(function () {
      return { http: 0, ok: false, json: { status: "error", error: "network_error" } };
    });
  }

  /* ------------------------------------------------------------------ */
  /* Mock data and router (offline preview only)                         */
  /* ------------------------------------------------------------------ */

  var MOCK = {
    raw: {
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
      judge_llm_id: "anthropic:claude-sonnet-4-6",
      question_filter: { categories: ["revenus", "tickets"], languages: ["fr"] },
      suggestions: {
        connection: "SQL_owi",
        table: "OWISMIND_DEV_webapp_chat_v5",
        promoted_dataset: "golden_questions_v1"
      }
    },
    runs: [
      { run_id: "run_2026-06-25_1430", run_timestamp: "2026-06-25 14:30" },
      { run_id: "run_2026-06-24_0900", run_timestamp: "2026-06-24 09:00" }
    ],
    kpis: {
      accuracy: 0.847,
      accuracy_pct: "84.7%",
      n_questions: 24,
      n_configs: 3,
      total_cost: 2.61,
      total_cost_str: "$2.61",
      judge_cost_str: "$0.14",
      needs_review: 6
    },
    summaryRows: [
      {
        agent_label: "OWIsMind Orchestrator", mode: "Claude", n_questions: 24, n_ok: 22, n_error: 0,
        error_rate: 0.0, error_rate_str: "0.0%", accuracy: 0.9167, accuracy_pct: "91.7%", mean_score: 4.6,
        latency_p50_s: 22.5, latency_p50_str: "22.5s", latency_p95_s: 48.0, latency_p95_str: "48.0s",
        avg_cost_per_q: 0.085, avg_cost_per_q_str: "$0.085", total_cost: 2.04, needs_review_count: 1
      },
      {
        agent_label: "OWIsMind Orchestrator", mode: "Smart", n_questions: 24, n_ok: 21, n_error: 1,
        error_rate: 0.0417, error_rate_str: "4.2%", accuracy: 0.875, accuracy_pct: "87.5%", mean_score: 4.3,
        latency_p50_s: 8.2, latency_p50_str: "8.2s", latency_p95_s: 19.4, latency_p95_str: "19.4s",
        avg_cost_per_q: 0.011, avg_cost_per_q_str: "$0.011", total_cost: 0.26, needs_review_count: 2
      },
      {
        agent_label: "Tickets Expert", mode: "Smart", n_questions: 24, n_ok: 18, n_error: 2,
        error_rate: 0.0833, error_rate_str: "8.3%", accuracy: 0.75, accuracy_pct: "75.0%", mean_score: 3.9,
        latency_p50_s: 9.0, latency_p50_str: "9.0s", latency_p95_s: 21.0, latency_p95_str: "21.0s",
        avg_cost_per_q: 0.013, avg_cost_per_q_str: "$0.013", total_cost: 0.31, needs_review_count: 3
      }
    ],
    breakdownRows: [
      { agent_label: "OWIsMind Orchestrator", mode: "Claude", dimension: "category", bucket: "revenus", n: 12, accuracy: 0.9167, accuracy_pct: "91.7%", mean_score: 4.6 },
      { agent_label: "OWIsMind Orchestrator", mode: "Claude", dimension: "category", bucket: "tickets", n: 12, accuracy: 0.9167, accuracy_pct: "91.7%", mean_score: 4.5 },
      { agent_label: "OWIsMind Orchestrator", mode: "Smart", dimension: "category", bucket: "revenus", n: 12, accuracy: 0.9167, accuracy_pct: "91.7%", mean_score: 4.4 },
      { agent_label: "OWIsMind Orchestrator", mode: "Smart", dimension: "category", bucket: "tickets", n: 12, accuracy: 0.8333, accuracy_pct: "83.3%", mean_score: 4.1 },
      { agent_label: "Tickets Expert", mode: "Smart", dimension: "category", bucket: "revenus", n: 4, accuracy: 0.5, accuracy_pct: "50.0%", mean_score: 3.0 },
      { agent_label: "Tickets Expert", mode: "Smart", dimension: "category", bucket: "tickets", n: 20, accuracy: 0.8, accuracy_pct: "80.0%", mean_score: 4.0 }
    ],
    detailRows: [
      {
        question_id: "q001", question: "Quel est le revenu reel (ACTUALS) du compte Airbus en 2026 ?",
        category: "revenus", agent_label: "OWIsMind Orchestrator", mode: "Smart", status: "ok",
        objective_match: "match", judge_score: 5, judge_verdict: "correct", correct: true, needs_review: false,
        reference_answer: "1 234 567 EUR", answer_preview: "Le revenu reel du compte Airbus en 2026 est de 1 234 567 EUR (scenario ACTUALS).",
        latency_total_s: 7.8, latency_str: "7.8s", estimated_cost: 0.012
      },
      {
        question_id: "q002", question: "Combien de tickets ouverts pour Maroc Telecom le mois dernier ?",
        category: "tickets", agent_label: "Tickets Expert", mode: "Smart", status: "ok",
        objective_match: "mismatch", judge_score: 2, judge_verdict: "partiel", correct: false, needs_review: true,
        reference_answer: "42 tickets", answer_preview: "Il y a environ 40 tickets ouverts pour Maroc Telecom.",
        latency_total_s: 9.1, latency_str: "9.1s", estimated_cost: 0.013
      },
      {
        question_id: "q003", question: "Budget 2026 Roaming pour le groupe Orange France ?",
        category: "revenus", agent_label: "OWIsMind Orchestrator", mode: "Claude", status: "ok",
        objective_match: "match", judge_score: 4, judge_verdict: "correct", correct: true, needs_review: true,
        reference_answer: "987 654 EUR (budget Roaming 2026)", answer_preview: "Le budget Roaming 2026 du groupe Orange France est de 987 654 EUR.",
        latency_total_s: 24.0, latency_str: "24.0s", estimated_cost: 0.088
      },
      {
        question_id: "q004", question: "Liste des comptes sans aucune activite sur 12 mois ?",
        category: "revenus", agent_label: "OWIsMind Orchestrator", mode: "Smart", status: "error",
        objective_match: "n/a", judge_score: 0, judge_verdict: "erreur", correct: false, needs_review: false,
        reference_answer: "12 comptes inactifs", answer_preview: "Erreur: depassement du delai de l'agent (timeout).",
        latency_total_s: 31.0, latency_str: "31.0s", estimated_cost: 0.004
      },
      {
        question_id: "q005", question: "Duree moyenne de resolution des tickets P2 ?",
        category: "tickets", agent_label: "Tickets Expert", mode: "Smart", status: "ok",
        objective_match: "match", judge_score: 5, judge_verdict: "correct", correct: true, needs_review: false,
        reference_answer: "186 minutes", answer_preview: "La duree moyenne de resolution des tickets P2 est de 186 minutes.",
        latency_total_s: 8.5, latency_str: "8.5s", estimated_cost: 0.012
      }
    ],
    suggestions: [
      {
        suggestion_id: "s1", user_id: "alice", source: "chat",
        question: "Quel est le taux de churn par region au T2 2026 ?",
        reference_answer: "Le churn T2 est de 3.2% en moyenne, plus eleve dans la region Sud.",
        answer_is_correct: false, missing_explanation: "L'agent n'a pas filtre par region.",
        expected_value: "3.2%", expected_value_type: "percent", category: "revenus", language: "fr",
        created_at: "2026-06-24 11:05"
      },
      {
        suggestion_id: "s2", user_id: "bob", source: "manual",
        question: "Top 5 des comptes par revenu budget 2026.",
        reference_answer: "1. Airbus 2. Maroc Telecom 3. Orange France 4. Vodafone 5. Telefonica",
        answer_is_correct: null, missing_explanation: "",
        expected_value: "", expected_value_type: "", category: "revenus", language: "fr",
        created_at: "2026-06-23 16:40"
      },
      {
        suggestion_id: "s3", user_id: "carol", source: "chat",
        question: "Nombre de tickets P1 ouverts cette semaine ?",
        reference_answer: "7 tickets P1",
        answer_is_correct: true, missing_explanation: "",
        expected_value: "7", expected_value_type: "number", category: "tickets", language: "fr",
        created_at: "2026-06-25 08:12"
      }
    ],
    run: { running: false, polls: 0 }
  };

  function mockResult(json, http) {
    http = http || 200;
    return { http: http, ok: http >= 200 && http < 300, json: json };
  }

  function configFromRaw(raw) {
    raw = raw || {};
    return {
      agents: (raw.agents || []).map(function (a) {
        return {
          agent_key: a.agent_key, agent_label: a.agent_label, project_key: a.project_key,
          agent_id: a.agent_id, modes: !!a.modes
        };
      }),
      modes: raw.modes || [],
      language: raw.language || "",
      concurrency: raw.concurrency == null ? 1 : raw.concurrency,
      golden_dataset: raw.golden_dataset || "",
      question_filter: raw.question_filter || {},
      judge_llm_id: raw.judge_llm_id || "",
      suggestions: raw.suggestions || {}
    };
  }

  function mockConfigResponse() {
    var cfg = configFromRaw(MOCK.raw);
    return {
      status: "ok",
      config: cfg,
      raw: MOCK.raw,
      categories: ["revenus", "tickets"],
      question_count: 24,
      runs: MOCK.runs.slice()
    };
  }

  function parseQuery(q) {
    var out = {};
    if (!q) return out;
    q.split("&").forEach(function (pair) {
      if (!pair) return;
      var i = pair.indexOf("=");
      var k = i === -1 ? pair : pair.slice(0, i);
      var v = i === -1 ? "" : pair.slice(i + 1);
      out[decodeURIComponent(k)] = decodeURIComponent(v);
    });
    return out;
  }

  function mockApi(path, opts) {
    var method = opts.method || (opts.body ? "POST" : "GET");
    var qi = path.indexOf("?");
    var base = qi === -1 ? path : path.slice(0, qi);
    var params = parseQuery(qi === -1 ? "" : path.slice(qi + 1));

    if (base === "api/config" && method === "GET") return mockResult(mockConfigResponse());
    if (base === "api/config" && method === "POST") return mockSaveConfig(opts.body);
    if (base === "api/results/runs") return mockResult({ status: "ok", runs: MOCK.runs.slice() });
    if (base === "api/results/summary") {
      return mockResult({ status: "ok", run_id: params.run_id || "", kpis: MOCK.kpis, rows: MOCK.summaryRows });
    }
    if (base === "api/results/breakdown") {
      return mockResult({ status: "ok", run_id: params.run_id || "", rows: MOCK.breakdownRows });
    }
    if (base === "api/results/detail") {
      var rows = MOCK.detailRows;
      if (params.needs_review === "1") {
        rows = rows.filter(function (r) { return r.needs_review; });
      }
      return mockResult({ status: "ok", run_id: params.run_id || "", count: rows.length, rows: rows });
    }
    if (base === "api/run" && method === "POST") return mockRun();
    if (base === "api/run/status") return mockResult(mockRunStatus());
    if (base === "api/suggestions" && method === "GET") {
      return mockResult({ status: "ok", configured: true, suggestions: MOCK.suggestions.slice() });
    }
    if (base === "api/suggestions/promote") return mockPromote(opts.body);
    return mockResult({ status: "error", error: "not_found" }, 404);
  }

  function mockSaveConfig(body) {
    var b = body && body.benchmark;
    var msgs = [];
    if (!b || typeof b !== "object") {
      msgs.push("Le bloc 'benchmark' est manquant ou invalide.");
    } else {
      if (!Array.isArray(b.agents) || b.agents.length === 0) {
        msgs.push("Au moins un agent est requis (champ 'agents').");
      }
      if (!Array.isArray(b.modes) || b.modes.length === 0) {
        msgs.push("Au moins un mode est requis (champ 'modes').");
      }
    }
    if (msgs.length) {
      return mockResult({ status: "error", error: "invalid_config", messages: msgs }, 400);
    }
    MOCK.raw = b;
    return mockResult({ status: "ok", config: configFromRaw(b) });
  }

  function mockRun() {
    if (MOCK.run.running) return mockResult({ status: "error", error: "already_running" }, 409);
    MOCK.run.running = true;
    MOCK.run.polls = 0;
    return mockResult({ status: "ok", launched: true });
  }

  function mockRunStatus() {
    if (MOCK.run.running) {
      MOCK.run.polls += 1;
      if (MOCK.run.polls >= 2) MOCK.run.running = false;
    }
    return {
      status: "ok",
      running: MOCK.run.running,
      last: { state: MOCK.run.running ? "RUNNING" : "SUCCESS", scenario: "Run_Benchmark" }
    };
  }

  function mockPromote(body) {
    var ids = (body && body.suggestion_ids) || [];
    var before = MOCK.suggestions.length;
    MOCK.suggestions = MOCK.suggestions.filter(function (s) {
      return ids.indexOf(s.suggestion_id) === -1;
    });
    var promoted = before - MOCK.suggestions.length;
    return mockResult({ status: "ok", promoted: promoted, recorded: promoted });
  }

  /* ------------------------------------------------------------------ */
  /* Application state                                                   */
  /* ------------------------------------------------------------------ */

  var activeTab = "results";
  var currentRunId = "";
  var configCache = null;
  var resultsLoadedFor = null;
  var launchLoaded = false;
  var suggestionsLoaded = false;
  var runPollTimer = null;

  /* ------------------------------------------------------------------ */
  /* Theme                                                               */
  /* ------------------------------------------------------------------ */

  function applyTheme(theme) {
    var root = $("#benchRoot");
    root.setAttribute("data-theme", theme);
    var btn = $("#themeToggle");
    if (btn) btn.textContent = (theme === "dark") ? "Mode clair" : "Mode sombre";
  }

  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem("bench-theme"); } catch (e) { saved = null; }
    applyTheme(saved === "dark" ? "dark" : "light");
  }

  function toggleTheme() {
    var root = $("#benchRoot");
    var next = (root.getAttribute("data-theme") === "dark") ? "light" : "dark";
    applyTheme(next);
    try { localStorage.setItem("bench-theme", next); } catch (e) { /* ignore */ }
  }

  /* ------------------------------------------------------------------ */
  /* Tabs                                                                */
  /* ------------------------------------------------------------------ */

  function switchTab(name) {
    activeTab = name;
    qsa(".tab").forEach(function (t) {
      var on = t.getAttribute("data-tab") === name;
      t.classList.toggle("is-active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    qsa(".tabpanel").forEach(function (p) {
      p.classList.toggle("is-active", p.id === "tab-" + name);
    });
    loadTab(name);
  }

  function loadTab(name) {
    if (name === "results") {
      if (resultsLoadedFor !== currentRunId) loadResults();
    } else if (name === "launch") {
      if (!launchLoaded) loadLaunch();
    } else if (name === "suggestions") {
      if (!suggestionsLoaded) { suggestionsLoaded = true; renderSuggestions(); }
    }
  }

  /* ------------------------------------------------------------------ */
  /* Config load and run selector                                        */
  /* ------------------------------------------------------------------ */

  function loadConfig() {
    return api("api/config").then(function (res) {
      var j = res.json || {};
      if (j.status !== "ok") return;
      configCache = j;
      populateRuns(j.runs || []);
    });
  }

  function populateRuns(runs) {
    var sel = $("#runSelect");
    if (!runs.length) {
      sel.innerHTML = '<option value="">(aucun run)</option>';
      currentRunId = "";
      return;
    }
    sel.innerHTML = runs.map(function (r) {
      return '<option value="' + escapeHtml(r.run_id) + '">' +
        escapeHtml(r.run_timestamp || r.run_id) + "</option>";
    }).join("");
    var stillThere = runs.some(function (r) { return r.run_id === currentRunId; });
    if (!currentRunId || !stillThere) currentRunId = runs[0].run_id;
    sel.value = currentRunId;
  }

  /* ------------------------------------------------------------------ */
  /* Tab 1: Results                                                      */
  /* ------------------------------------------------------------------ */

  function loadResults() {
    if (!currentRunId) {
      $("#resultsStatus").textContent = "Aucun run disponible.";
      clearResults();
      return Promise.resolve();
    }
    $("#resultsStatus").textContent = "Chargement du run " + currentRunId + "...";
    var ok = true;
    return api("api/results/summary?run_id=" + encodeURIComponent(currentRunId))
      .then(function (s) {
        var sj = s.json || {};
        if (sj.status !== "ok") {
          ok = false;
          $("#resultsStatus").textContent = "Erreur de chargement du resume.";
          return null;
        }
        renderKpis(sj.kpis || {});
        renderSummary(sj.rows || []);
        return api("api/results/breakdown?run_id=" + encodeURIComponent(currentRunId));
      })
      .then(function (b) {
        if (b) renderBreakdown((b.json || {}).rows || []);
        return ok ? loadDetail() : null;
      })
      .then(function () {
        // Only clear the status + mark the run loaded on SUCCESS: on a transient error the
        // message stays visible AND a tab re-entry / run-select change retries (loadTab guards
        // on resultsLoadedFor !== currentRunId).
        if (ok) {
          $("#resultsStatus").textContent = "";
          resultsLoadedFor = currentRunId;
        }
      })
      .catch(function (e) {
        $("#resultsStatus").textContent = "Erreur : " + e.message;
      });
  }

  function loadDetail() {
    var nr = $("#needsReviewOnly").checked ? "1" : "";
    return api("api/results/detail?run_id=" + encodeURIComponent(currentRunId) + "&needs_review=" + nr)
      .then(function (r) {
        renderDetail((r.json || {}).rows || []);
      });
  }

  function clearResults() {
    $("#kpis").innerHTML = "";
    $("#summaryTableWrap").innerHTML = "";
    $("#breakdownWrap").innerHTML = "";
    $("#detailWrap").innerHTML = "";
  }

  function renderKpis(k) {
    var tiles = [
      { v: k.accuracy_pct, l: "Precision", headline: true, accent: true },
      { v: String(k.n_questions == null ? "-" : k.n_questions), l: "Questions" },
      { v: String(k.n_configs == null ? "-" : k.n_configs), l: "Configurations testees" },
      { v: k.total_cost_str, l: "Cout total" },
      { v: String(k.needs_review == null ? "-" : k.needs_review), l: "A relire" }
    ];
    $("#kpis").innerHTML = tiles.map(function (t) {
      return '<div class="kpi' + (t.headline ? " headline" : "") + '">' +
        '<div class="kpi-value' + (t.accent ? " accent" : "") + '">' +
        escapeHtml(t.v == null ? "-" : t.v) + "</div>" +
        '<div class="kpi-label">' + escapeHtml(t.l) + "</div></div>";
    }).join("");
  }

  function renderSummary(rows) {
    if (!rows || !rows.length) {
      $("#summaryTableWrap").innerHTML = emptyNote("Aucune configuration pour ce run.");
      return;
    }
    var head = '<div class="table-wrap"><table class="tbl"><thead><tr>' +
      "<th>Configuration</th>" +
      "<th>Precision</th>" +
      '<th class="num">Latence p50</th>' +
      '<th class="num">Latence p95</th>' +
      '<th class="num">Cout / question</th>' +
      '<th class="num">Taux d\'erreur</th>' +
      '<th class="num">A relire</th>' +
      "</tr></thead><tbody>";
    var body = rows.map(function (r) {
      var cls = modeClass(r.mode);
      var pct = clampPct(r.accuracy * 100);
      return "<tr>" +
        '<td><span class="agent-name">' + escapeHtml(r.agent_label) + "</span> " + chip(r.mode) + "</td>" +
        "<td>" + barRow(r.accuracy_pct, pct, cls) + "</td>" +
        '<td class="num">' + escapeHtml(r.latency_p50_str) + "</td>" +
        '<td class="num">' + escapeHtml(r.latency_p95_str) + "</td>" +
        '<td class="num">' + escapeHtml(r.avg_cost_per_q_str) + "</td>" +
        '<td class="num">' + escapeHtml(r.error_rate_str) + "</td>" +
        '<td class="num">' + escapeHtml(String(r.needs_review_count == null ? "-" : r.needs_review_count)) + "</td>" +
        "</tr>";
    }).join("");
    $("#summaryTableWrap").innerHTML = head + body + "</tbody></table></div>";
  }

  function renderBreakdown(rows) {
    var wrap = $("#breakdownWrap");
    if (!rows || !rows.length) {
      wrap.innerHTML = emptyNote("Aucune donnee de categorie pour ce run.");
      return;
    }
    var groups = {};
    var order = [];
    rows.forEach(function (r) {
      var key = r.agent_label + "||" + r.mode;
      if (!groups[key]) {
        groups[key] = { agent_label: r.agent_label, mode: r.mode, rows: [] };
        order.push(key);
      }
      groups[key].rows.push(r);
    });
    wrap.innerHTML = order.map(function (key) {
      var g = groups[key];
      var cls = modeClass(g.mode);
      var rws = g.rows.map(function (r) {
        var pct = clampPct(r.accuracy * 100);
        return '<div class="bd-row">' +
          '<div class="bd-bucket">' + escapeHtml(r.bucket) +
          ' <span class="bd-n">n=' + escapeHtml(String(r.n)) + "</span></div>" +
          '<span class="bar"><span class="bar-fill mode-' + cls +
          '" style="width:' + pct + '%"></span></span>' +
          '<div class="bd-pct">' + escapeHtml(r.accuracy_pct == null ? "-" : r.accuracy_pct) + "</div>" +
          "</div>";
      }).join("");
      return '<div class="bd-group"><div class="bd-head">' +
        escapeHtml(g.agent_label) + " " + chip(g.mode) + "</div>" +
        '<div class="bd-rows">' + rws + "</div></div>";
    }).join("");
  }

  function objMatchLabel(m) {
    if (m === "match") return "ancre: ok";
    if (m === "mismatch") return "ancre: ko";
    if (m === "n/a" || m == null || m === "") return "ancre: n/a";
    return String(m);
  }

  function renderDetail(rows) {
    var wrap = $("#detailWrap");
    if (!rows || !rows.length) {
      wrap.innerHTML = emptyNote("Aucune question a afficher.");
      return;
    }
    var head = '<div class="table-wrap"><table class="tbl"><thead><tr>' +
      "<th>Question</th><th>Categorie</th><th>Agent</th><th>Mode</th><th>Verdict</th>" +
      '<th class="num">Score</th><th class="num">Correct</th><th>A relire</th>' +
      '<th class="num">Latence</th><th class="num">Cout</th></tr></thead><tbody>';
    var body = rows.map(function (r) {
      var flagged = r.needs_review ? ' class="flagged"' : "";
      var verdict = escapeHtml(objMatchLabel(r.objective_match));
      if (r.judge_verdict) verdict += " / " + escapeHtml(String(r.judge_verdict));
      var score = (r.judge_score == null) ? "-" : (escapeHtml(String(r.judge_score)) + " / 5");
      var mark = r.correct ? '<span class="mark ok">OK</span>' : '<span class="mark ko">KO</span>';
      var review = r.needs_review ? '<span class="tag-review">A relire</span>' : "";
      var cost = (r.estimated_cost == null) ? "-" : ("$" + Number(r.estimated_cost).toFixed(3));
      return "<tr" + flagged + ">" +
        '<td class="cell-q" title="' + escapeHtml(r.question) + '">' + escapeHtml(truncate(r.question, 90)) + "</td>" +
        "<td>" + escapeHtml(r.category || "-") + "</td>" +
        "<td>" + escapeHtml(r.agent_label || "-") + "</td>" +
        "<td>" + chip(r.mode) + "</td>" +
        "<td>" + verdict + "</td>" +
        '<td class="num">' + score + "</td>" +
        '<td class="num">' + mark + "</td>" +
        "<td>" + review + "</td>" +
        '<td class="num">' + escapeHtml(r.latency_str || "-") + "</td>" +
        '<td class="num">' + escapeHtml(cost) + "</td>" +
        "</tr>";
    }).join("");
    wrap.innerHTML = head + body + "</tbody></table></div>";
  }

  /* ------------------------------------------------------------------ */
  /* Tab 2: Launch                                                       */
  /* ------------------------------------------------------------------ */

  function loadLaunch() {
    var p = configCache ? Promise.resolve() : loadConfig();
    return p.then(function () {
      if (configCache) {
        renderLaunch(configCache);
        launchLoaded = true;
      }
    });
  }

  function renderLaunch(cfg) {
    renderConfigSummary(cfg.config || {});
    $("#configEditor").value = JSON.stringify(cfg.raw || {}, null, 2);
  }

  function kv(k, v) {
    return "<dt>" + escapeHtml(k) + "</dt><dd>" + escapeHtml(v) + "</dd>";
  }

  function renderConfigSummary(c) {
    var agents = (c.agents || []).map(function (a) {
      return '<div class="agent-line">' +
        '<span class="agent-name">' + escapeHtml(a.agent_label || "-") + "</span>" +
        '<span class="mono-faint">' + escapeHtml(a.project_key || "") + "</span>" +
        '<span class="mono-faint">' + escapeHtml(a.agent_id || "") + "</span>" +
        (a.modes ? '<span class="chip-modes">modes</span>' : "") +
        "</div>";
    }).join("");
    if (!agents) agents = '<div class="note">Aucun agent configure.</div>';

    var qf = c.question_filter || {};
    var bits = [];
    if (qf.categories && qf.categories.length) bits.push("categories: " + qf.categories.join(", "));
    if (qf.question_ids && qf.question_ids.length) bits.push("question_ids: " + qf.question_ids.length + " id(s)");
    if (qf.languages && qf.languages.length) bits.push("langues: " + qf.languages.join(", "));
    var qfStr = bits.length ? bits.join("  |  ") : "aucun filtre";

    $("#configSummary").innerHTML =
      '<div class="agents">' + agents + "</div>" +
      '<dl class="kv">' +
      kv("Modes", (c.modes || []).join(", ") || "-") +
      kv("Langue", c.language || "-") +
      kv("Concurrence", String(c.concurrency == null ? "-" : c.concurrency)) +
      kv("Golden dataset", c.golden_dataset || "-") +
      kv("LLM juge", c.judge_llm_id || "-") +
      kv("Filtre de questions", qfStr) +
      "</dl>";
  }

  function onSaveConfig() {
    var msg = $("#configMsg");
    var txt = $("#configEditor").value;
    var parsed;
    try {
      parsed = JSON.parse(txt);
    } catch (e) {
      msg.innerHTML = box("error", "JSON invalide : " + e.message);
      return;
    }
    setBusy($("#saveConfig"), true);
    api("api/config", { method: "POST", body: { benchmark: parsed } }).then(function (res) {
      setBusy($("#saveConfig"), false);
      var j = res.json || {};
      if (j.status === "error") {
        var msgs = (j.messages && j.messages.length) ? j.messages : [j.error || "Erreur inconnue"];
        msg.innerHTML = box("error", "Configuration refusee :", msgs);
        return;
      }
      if (configCache) {
        configCache.config = j.config;
        configCache.raw = parsed;
      }
      renderConfigSummary(j.config || {});
      msg.innerHTML = box("success", "Configuration enregistree.");
    });
  }

  function runningHtml() {
    return '<div class="box box-info"><span class="running">En cours' +
      '<span class="dots"><span>.</span><span>.</span><span>.</span></span></span></div>';
  }

  function onRun() {
    var msg = $("#runMsg");
    setBusy($("#runBtn"), true);
    api("api/run", { method: "POST" }).then(function (res) {
      var j = res.json || {};
      if (res.http === 409 || j.error === "already_running") {
        msg.innerHTML = box("info", "Un run est deja en cours.");
        startPolling();
        return;
      }
      if (j.status === "error") {
        setBusy($("#runBtn"), false);
        msg.innerHTML = box("error", "Echec du lancement (" + (j.error || "launch_failed") + ").");
        return;
      }
      msg.innerHTML = runningHtml();
      startPolling();
    });
  }

  function startPolling() {
    stopPolling();
    runPollTimer = setInterval(pollStatus, 5000);
    pollStatus();
  }

  function stopPolling() {
    if (runPollTimer) { clearInterval(runPollTimer); runPollTimer = null; }
  }

  function pollStatus() {
    api("api/run/status").then(function (res) {
      var j = res.json || {};
      if (j.running === false) {
        stopPolling();
        setBusy($("#runBtn"), false);
        $("#runMsg").innerHTML =
          '<div class="box box-success">Termine. Rechargez l\'onglet Resultats.' +
          '<button type="button" class="btn" id="reloadResultsBtn">Recharger les resultats</button></div>';
        var b = $("#reloadResultsBtn");
        if (b) b.addEventListener("click", function () {
          // Re-fetch the run list so the just-finished run is added AND selected (clearing
          // currentRunId makes populateRuns pick the newest), then show the Results tab. Without
          // this, results would reload for the OLD run and the new one would be invisible.
          currentRunId = "";
          resultsLoadedFor = null;
          loadConfig().then(function () { switchTab("results"); });
        });
      } else {
        $("#runMsg").innerHTML = runningHtml();
      }
    });
  }

  /* ------------------------------------------------------------------ */
  /* Tab 3: Suggestions                                                  */
  /* ------------------------------------------------------------------ */

  function sourceLabel(s) {
    if (s === "chat") return "Conversation";
    if (s === "manual") return "Manuelle";
    return s || "-";
  }

  function shortDate(d) {
    if (!d) return "-";
    return String(d).slice(0, 10);
  }

  function renderSuggestions() {
    var wrap = $("#suggestionsWrap");
    wrap.innerHTML = '<div class="status">Chargement...</div>';
    return api("api/suggestions").then(function (res) {
      var j = res.json || {};
      if (j.status === "error") {
        wrap.innerHTML = box("error", "Erreur : " + (j.error || "inconnue"));
        return;
      }
      if (!j.configured) {
        wrap.innerHTML = box("info",
          "Source des suggestions non configuree (ajoutez le bloc benchmark.suggestions dans la variable projet).");
        return;
      }
      var rows = j.suggestions || [];
      if (!rows.length) {
        wrap.innerHTML = emptyNote("Aucune suggestion en attente.");
        return;
      }
      var head =
        '<div class="actions"><button type="button" class="btn btn-primary" id="promoteBtn" disabled>' +
        "Promouvoir la selection</button></div>" +
        '<div id="promoteMsg" class="msg"></div>' +
        '<div class="table-wrap"><table class="tbl"><thead><tr>' +
        '<th><input type="checkbox" id="selAll" aria-label="Tout selectionner"></th>' +
        "<th>Question</th><th>Reponse attendue</th><th>Origine</th><th>Categorie</th>" +
        '<th class="num">Date</th></tr></thead><tbody>';
      var body = rows.map(function (s) {
        return "<tr>" +
          '<td><input type="checkbox" class="sel-row" value="' + escapeHtml(s.suggestion_id) +
          '" aria-label="Selectionner la suggestion"></td>' +
          '<td class="cell-q" title="' + escapeHtml(s.question) + '">' + escapeHtml(truncate(s.question, 80)) + "</td>" +
          '<td class="cell-q" title="' + escapeHtml(s.reference_answer) + '">' +
          escapeHtml(truncate(s.reference_answer, 80)) + "</td>" +
          "<td>" + escapeHtml(sourceLabel(s.source)) + "</td>" +
          "<td>" + escapeHtml(s.category || "-") + "</td>" +
          '<td class="num">' + escapeHtml(shortDate(s.created_at)) + "</td>" +
          "</tr>";
      }).join("");
      wrap.innerHTML = head + body + "</tbody></table></div>";
      bindSuggestionEvents();
    });
  }

  function suggestionBoxes() {
    return qsa("#tab-suggestions .sel-row");
  }

  function bindSuggestionEvents() {
    var selAll = $("#selAll");
    var btn = $("#promoteBtn");
    function refresh() {
      var any = suggestionBoxes().some(function (c) { return c.checked; });
      if (btn) btn.disabled = !any;
    }
    if (selAll) {
      selAll.addEventListener("change", function () {
        suggestionBoxes().forEach(function (c) { c.checked = selAll.checked; });
        refresh();
      });
    }
    suggestionBoxes().forEach(function (c) {
      c.addEventListener("change", function () {
        if (!c.checked && selAll) selAll.checked = false;
        refresh();
      });
    });
    if (btn) btn.addEventListener("click", onPromote);
    refresh();
  }

  function onPromote() {
    var ids = suggestionBoxes()
      .filter(function (c) { return c.checked; })
      .map(function (c) { return c.value; });
    if (!ids.length) return;
    var btn = $("#promoteBtn");
    setBusy(btn, true);
    api("api/suggestions/promote", { method: "POST", body: { suggestion_ids: ids } }).then(function (res) {
      var j = res.json || {};
      if (j.status === "error") {
        var pm = $("#promoteMsg");
        if (pm) pm.innerHTML = box("error", "Erreur : " + (j.error || "inconnue"));
        setBusy(btn, false);
        return;
      }
      var promoted = j.promoted || 0;
      renderSuggestions().then(function () {
        var note = box("success", promoted + " question(s) ajoutee(s) au golden.");
        var pm = $("#promoteMsg");
        if (pm) {
          pm.innerHTML = note;
        } else {
          var w = $("#suggestionsWrap");
          w.innerHTML = note + w.innerHTML;
        }
      });
    });
  }

  /* ------------------------------------------------------------------ */
  /* Wiring                                                              */
  /* ------------------------------------------------------------------ */

  function bindStatic() {
    qsa(".tab").forEach(function (t) {
      t.addEventListener("click", function () { switchTab(t.getAttribute("data-tab")); });
    });
    $("#runSelect").addEventListener("change", function () {
      currentRunId = this.value;
      resultsLoadedFor = null;
      if (activeTab === "results") loadResults();
    });
    $("#needsReviewOnly").addEventListener("change", function () { loadDetail(); });
    $("#themeToggle").addEventListener("click", toggleTheme);
    $("#saveConfig").addEventListener("click", onSaveConfig);
    $("#runBtn").addEventListener("click", onRun);
  }

  function init() {
    initTheme();
    bindStatic();
    loadConfig().then(function () {
      switchTab("results");
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
