/* OWIsMind - Agent Factory Console (framework-free vanilla JS, no build, no CDN).
 *
 * Admin design-time webapp that adds and removes the orchestrator's sub-agents
 * (one capability per business domain) in the DSS project, and edits the
 * orchestrator persona of the Config & Prompt Hub. It is SEPARATE from the public
 * OWIsMind Vue plugin webapp. English-only UI.
 *
 * Three screens, one idea each:
 *   - Overview : an org chart (orchestrator -> sub-agents) with Enable / Disable /
 *     Remove on each node, the "Add a sub-agent" button and a "Resume" banner.
 *   - Run : the server-persisted guided run, creation (14 stages) or removal
 *     (12 stages). Left column = the stage to act on (what the click does, the
 *     objects it creates / deletes, the button); right column = the sticky tracker.
 *   - Settings : the central LLM per mode (models.json) for all agents, the hub
 *     prompt files (editable) and the factory settings (read-only).
 *   - Agent settings (button on every node): that agent's LLM per mode, system
 *     prompt layers, routing description and tools.
 *
 * Manual stages (the operator acts in DSS): the steps are written here, front-side,
 * as a numbered checklist; the "Done, check it" button stays disabled until every
 * step is ticked, then the backend VERIFIES in DSS before the run advances.
 * The engine's own French instruction text is never shown (it is replaced by the
 * STAGE_UX steps); server problem messages are shown verbatim, labelled as such.
 *
 * Safety model (mirrors the backend contract, unchanged): read calls are plain
 * GETs; every mutating call carries {confirm: true} behind a confirm modal; the
 * ONLY deletion path is the guided removal run (typed domain name, one confirmed
 * stage at a time, source dataset never touched).
 *
 * Long backend actions (stage runs / wizard draft / probe) run as background JOBS:
 * the POST returns a job_id, then we poll GET api/job/<id> until done or error.
 * The shell in body.html (<template id="afc-shell">) is cloned once into #afc;
 * each screen renders into #afcMain. Orange charter in style.css. */

(function () {
  "use strict";

  /* ============================ icons ============================ */

  var I = {
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M5 12l5 5 9-10"/></svg>',
    play: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 5l12 7-12 7z"/></svg>',
    copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="11" height="11"/><path d="M5 15V5h10"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4v6h6M20 20v-6h-6"/><path d="M20 10a8 8 0 0 0-14-4M4 14a8 8 0 0 0 14 4"/></svg>',
    save: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 4h11l3 3v13H5zM8 4v5h7M8 20v-6h8v6"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
    back: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 5l-7 7 7 7"/></svg>',
    chevron: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 6l6 6-6 6"/></svg>',
    hub: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 3v6M12 15v6M3 12h6M15 12h6"/></svg>'
  };

  /* ============================ state ============================ */

  var S = {
    view: "overview",          // overview | run | settings | agent
    theme: "light",
    overview: { loaded: false, loading: false, error: null, data: null, flash: null, notice: null },
    guided: {
      loaded: false, loading: false, error: null, run: null,
      starting: false, startError: null, startErrorCode: null, running: false, verifying: false,
      abandoning: false, actionError: null, verifyFailed: false, liveActions: [], lastDone: null,
      form: { domain: "", base_dataset: "", label_fr: "", label_en: "", lookup: "" },
      wizard: { running: false, jobId: null, config: null, answers: {}, drafted: null, error: null, reqId: 0 },
      probe: { running: false, report: null, error: null },
      review: null,            // see resetReviewUi()
      ticks: {}                // "<run_id>:<stage>" -> {stepIndex: true}
    },
    datasets: { loaded: false, loading: false, error: null, list: [] },
    models: { loaded: false, loading: false, error: null, data: null, draft: null },
    agent: { key: null, loadedKey: null, loading: false, error: null, data: null, draft: {}, notice: null,
             ai: { running: false, error: null, instr: "", drafted: false } },
    prompts: {
      path: "/python/owismind_hub/prompts/orchestrator_persona.md",
      loading: false, loaded: false, content: "", saving: false, loadError: null
    },
    // Open state of the collapsible blocks (survives the 1.5s job-polling re-renders).
    ui: { details: {} }
  };

  var PERSONA_PATH = "/python/owismind_hub/prompts/orchestrator_persona.md";
  var ORCHESTRATOR_NAME = "OWIsMind_orchestrator";

  /* ============================ dom helpers ============================ */

  function byId(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function mono(text) { return '<span class="mono">' + esc(text) + '</span>'; }
  /* A name the operator must type or paste in DSS: mono + a copy button. */
  function copyable(text) {
    return '<span class="mono copyable">' + esc(text) + '</span>' +
      '<button class="afc-copy" data-copy="' + esc(text) + '" title="Copy">' + I.copy + '</button>';
  }
  function setMain(html) {
    var m = byId("afcMain");
    if (m) { m.innerHTML = html; wireDetails(); wireCopyButtons(); }
  }

  /* ============================ API ============================ */

  function hasBackend() { return typeof getWebAppBackendUrl === "function"; }

  function callApi(method, path, body) {
    if (!hasBackend()) {
      return Promise.resolve({ http: 0, data: { status: "error", error: "no_backend" } });
    }
    var opts = { method: method, headers: { "Content-Type": "application/json" } };
    if (body !== undefined) { opts.body = JSON.stringify(body); }
    return fetch(getWebAppBackendUrl("api/" + path), opts).then(function (res) {
      return res.json().then(
        function (data) { return { http: res.status, data: data }; },
        function () { return { http: res.status, data: {} }; }
      );
    }, function () {
      return { http: 0, data: { status: "error", error: "network_error" } };
    });
  }

  /* Poll a background job until it is done or error.
   * onTick(actions) is called on every running poll; onDone(result, actions) once. */
  function pollJob(jobId, onTick, onDone, onError) {
    var stopped = false;
    var transientFails = 0;
    var MAX_TRANSIENT = 5;
    function tick() {
      if (stopped) { return; }
      callApi("GET", "job/" + encodeURIComponent(jobId)).then(function (r) {
        if (stopped) { return; }
        var d = r.data || {};
        // A real job response is an HTTP 200 carrying an explicit status. Anything
        // else (network error http:0, 5xx, 404, empty/invalid body) is a transport
        // hiccup, NOT a job failure.
        var st = (r.http === 200) ? d.status : null;
        if (st === "running" || st === "done" || st === "error") {
          transientFails = 0;
          if (st === "running") {
            if (onTick) { onTick(d.actions || []); }
            setTimeout(tick, 1500);
          } else if (st === "done") {
            stopped = true;
            if (onDone) { onDone(d.result, d.actions || []); }
          } else {
            stopped = true;
            if (onError) { onError(d.error || "job_error", d.actions || []); }
          }
          return;
        }
        // Transient transport failure: retry with growing backoff (2s, 4s, 8s,
        // capped) before declaring the job lost.
        transientFails += 1;
        if (transientFails > MAX_TRANSIENT) {
          stopped = true;
          if (onError) { onError("poll_failed", []); }
          return;
        }
        var delay = Math.min(1000 * Math.pow(2, transientFails), 8000);
        setTimeout(tick, delay);
      });
    }
    tick();
    return function () { stopped = true; };
  }

  /* ============================ toast ============================ */

  var _toastTimer = null;
  function toast(msg) {
    var t = byId("afcToast"); var m = byId("afcToastMsg");
    if (!t || !m) { return; }
    m.textContent = msg;
    t.classList.add("on");
    if (_toastTimer) { clearTimeout(_toastTimer); }
    _toastTimer = setTimeout(function () { t.classList.remove("on"); }, 2600);
  }

  /* ============================ confirm modal ============================ */

  /* opts: {title, bodyHtml, confirmLabel, danger, onConfirm} */
  function openConfirm(opts) {
    var scrim = byId("afcModalScrim");
    byId("afcModalTitle").textContent = opts.title || "Confirm";
    byId("afcModalBody").innerHTML = opts.bodyHtml || "";
    var foot = byId("afcModalFoot");
    var confirmCls = opts.danger ? "afc-btn afc-btn--danger-solid" : "afc-btn afc-btn--primary";
    foot.innerHTML =
      '<button class="afc-btn afc-btn--ghost afc-btn--sm" id="afcModalCancel">Cancel</button>' +
      '<button class="' + confirmCls + '" id="afcModalOk">' + esc(opts.confirmLabel || "Confirm") + '</button>';
    scrim.classList.add("on");
    scrim.setAttribute("aria-hidden", "false");
    byId("afcModalCancel").onclick = closeModal;
    byId("afcModalOk").onclick = function () {
      closeModal();
      if (opts.onConfirm) { opts.onConfirm(); }
    };
    var first = byId("afcModalBody").querySelector("input");
    if (first) { first.focus(); }
  }
  function closeModal() {
    var scrim = byId("afcModalScrim");
    scrim.classList.remove("on");
    scrim.setAttribute("aria-hidden", "true");
  }

  /* ============================ engine strings -> English ============================ */

  /* The frozen engine labels inventory items in French. Known labels are mapped
   * to English; anything unknown is shown as-is. */
  var EN = {
    "Tool Semantic Model Query": "Semantic Model Query tool",
    "Code Agent": "Code Agent",
    "Modèle sémantique": "Semantic model",
    "Scénario": "Scenario",
    "Recette Python": "Python recipe",
    "Dataset de connaissance": "Knowledge dataset",
    "Zone du Flow": "Flow zone",
    "Fichier du hub": "Hub file",
    "Dataset SOURCE (protégé)": "Source dataset (protected)",
    "Dataset PROTÉGÉ (autre capability)": "Protected dataset (used by another capability)",
    "project library": "project library",
    "Scenarios": "Scenarios",
    "Agents & GenAI Models > Tools": "Agents & GenAI Models > Tools",
    "Agents & GenAI Models > Agents": "Agents & GenAI Models > Agents",
    "Agents & GenAI Models > Semantic models": "Agents & GenAI Models > Semantic models",
    "sa table SQL dérivée sera supprimée (reconstructible)": "its derived SQL table is deleted too (can be rebuilt)",
    "supprimée SEULEMENT si vide (le dataset source, jamais touché, peut la garder en vie)":
      "deleted ONLY if empty (the source dataset, never touched, may keep it alive)",
    "JAMAIS supprimé par ce run": "NEVER deleted by this run",
    "appartient aussi à une autre capability du registre : JAMAIS supprimé par ce run":
      "also belongs to another capability: NEVER deleted by this run"
  };
  function en(s) {
    var t = String(s == null ? "" : s);
    if (EN[t]) { return EN[t]; }
    var m = t.match(/^Flow, zone (.+)$/);
    if (m) { return "Flow, zone " + m[1]; }
    return t;
  }

  /* ============================ shared render bits ============================ */

  function statusChip(status) {
    var map = {
      PLANNED: { cls: "planned", txt: "PLANNED" },
      DONE: { cls: "done", txt: "DONE" },
      SKIPPED: { cls: "skipped", txt: "SKIPPED" },
      FAILED: { cls: "failed", txt: "FAILED" },
      MANUAL: { cls: "planned", txt: "LATER STEP" },
      BLOCKED: { cls: "blocked", txt: "BLOCKED" }
    };
    var m = map[status] || { cls: "planned", txt: String(status || "") };
    return '<span class="afc-chip afc-chip--' + m.cls + '">' + esc(m.txt) + '</span>';
  }

  function actionsTable(actions) {
    if (!actions || !actions.length) {
      return '<p class="afc-muted">No action yet.</p>';
    }
    var rows = actions.map(function (a) {
      return '<tr>' +
        '<td class="col-status">' + statusChip(a.status) + '</td>' +
        '<td class="col-step"><span class="afc-cell-step">' + esc(a.step) + '</span></td>' +
        '<td class="afc-cell-detail">' + esc(a.detail || "") + '</td>' +
        '</tr>';
    }).join("");
    return '<div class="afc-table-wrap"><table class="afc-table">' +
      '<thead><tr><th class="col-status">Status</th><th class="col-step">Action</th><th>Detail</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>';
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () { toast("Copied to the clipboard."); },
        function () { toast("Copy blocked by the browser: select the text instead."); }
      );
    } else {
      toast("Copy not supported by the browser: select the text instead.");
    }
  }
  function copyButton(id, label) {
    return '<button class="afc-btn afc-btn--ghost afc-btn--sm" id="' + id + '">' + I.copy + (label || "Copy") + '</button>';
  }
  function wireCopy(id, getText) {
    var b = byId(id);
    if (b) { b.onclick = function () { copyText(getText()); }; }
  }
  function wireCopyButtons() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-copy]"), function (b) {
      b.onclick = function () { copyText(b.getAttribute("data-copy")); };
    });
  }

  function backendBanner() {
    if (hasBackend()) { return ""; }
    return '<div class="afc-note afc-note--warn">Backend unavailable: this page is open outside DSS. ' +
      'Factory calls only work once the webapp runs inside DSS.</div>';
  }

  /* A collapsible block whose open state survives re-renders (S.ui.details). */
  function detailsBlock(key, summary, innerHtml, defaultOpen) {
    var stored = S.ui.details[key];
    var open = (stored === undefined) ? !!defaultOpen : !!stored;
    return '<details class="afc-details" data-details-key="' + esc(key) + '"' + (open ? " open" : "") + '>' +
      '<summary><span class="afc-details-chev">' + I.chevron + '</span>' +
      '<span>' + esc(summary) + '</span></summary>' +
      '<div class="afc-details-body">' + innerHtml + '</div></details>';
  }
  function wireDetails() {
    Array.prototype.forEach.call(document.querySelectorAll("#afcMain details[data-details-key]"), function (d) {
      d.addEventListener("toggle", function () {
        S.ui.details[d.getAttribute("data-details-key")] = d.open;
      });
    });
  }

  /* The compact shell header carries the page identity: back link (every screen
   * but the overview), eyebrow, title, one subtitle line and an optional action. */
  function setHeader(o) {
    o = o || {};
    var back = byId("afcBack");
    if (back) { back.style.display = o.back ? "" : "none"; }
    if (byId("afcEyebrow")) { byId("afcEyebrow").textContent = o.eyebrow || "OWIsMind agent factory"; }
    if (byId("afcTitle")) { byId("afcTitle").textContent = o.title || ""; }
    if (byId("afcSub")) { byId("afcSub").innerHTML = o.sub || ""; }
    if (byId("afcHeaderAction")) { byId("afcHeaderAction").innerHTML = o.action || ""; }
  }
  function backLink() { return ""; }
  function wireBack() {}

  /* "Reload the orchestrator" explained step by step: the registry of sub-agents
   * is read when the orchestrator process starts (lesson L168). */
  function reloadSteps() {
    return '<ol class="howto howto--strong">' +
      '<li>In DSS, open <b>Agents &amp; GenAI Models</b> &gt; <b>Agents</b> &gt; ' + copyable(ORCHESTRATOR_NAME) + '.</li>' +
      '<li>Click <b>Save</b> (no edit needed). Saving restarts the orchestrator, which then re-reads its list of sub-agents.</li>' +
      '<li>In the OWIsMind webapp, start a <b>new conversation</b> (an existing conversation keeps the old list).</li>' +
      '</ol>';
  }
  function reloadBlock(title) {
    return '<div class="nextstep"><p class="afc-mlabel">' + esc(title || "Last step: reload the orchestrator") + '</p>' +
      reloadSteps() + '</div>';
  }

  /* ============================ datasets (picker source) ============================ */

  function loadDatasets(cb, force) {
    if (force && !S.datasets.loading) {
      S.datasets.loaded = false;
      S.datasets.error = null;
    }
    if (S.datasets.loaded || S.datasets.loading) { if (cb) { cb(); } return; }
    S.datasets.loading = true;
    callApi("GET", "datasets").then(function (r) {
      S.datasets.loading = false;
      if (r.data && r.data.status === "ok") {
        S.datasets.loaded = true;
        S.datasets.list = r.data.datasets || [];
        S.datasets.error = null;
      } else {
        S.datasets.error = (r.data && r.data.error) || "load_error";
      }
      if (cb) { cb(); }
    });
  }

  function datasetOptions(selected) {
    var opts = ['<option value="">Choose a dataset</option>'];
    S.datasets.list.forEach(function (d) {
      var sel = d.name === selected ? " selected" : "";
      opts.push('<option value="' + esc(d.name) + '"' + sel + '>' + esc(d.name) + '</option>');
    });
    return opts.join("");
  }

  /* ============================ derived names (mirror of spec.py DomainSpec) ============================ */

  /* Mirror of Python str.title().replace("_", ""): a letter is upper-cased when it
   * starts the string or follows a non-letter; every other letter is lower-cased.
   * Example: "sales_ops" -> "SalesOps". */
  function titleNoUnderscore(domain) {
    var s = String(domain || "").toLowerCase();
    var out = "";
    var prevLetter = false;
    for (var i = 0; i < s.length; i++) {
      var ch = s.charAt(i);
      var isLetter = ch.toLowerCase() !== ch.toUpperCase();
      out += (isLetter && !prevLetter) ? ch.toUpperCase() : ch;
      prevLetter = isLetter;
    }
    return out.replace(/_/g, "");
  }

  /* Every DSS / hub name the factory derives from a spec. Pure function:
   * placeholders stand in for empty fields so the live preview always reads. */
  function derivedNames(spec) {
    spec = spec || {};
    var domain = String(spec.domain || "").trim();
    var base = String(spec.base_dataset || "").trim();
    var title = titleNoUnderscore(domain);
    var d = domain || "<domain>";
    var b = base || "<dataset>";
    var t = title || "<Domain>";
    return {
      domain: d, base: b, title: t,
      zone: (spec.zone_name && String(spec.zone_name).trim()) || (t + "_Expert"),
      profile: b + "_profile",
      valueIndex: b + "_value_index",
      valueCatalog: b + "_value_catalog",
      scenario: "Refresh_" + t,
      model: b + "_Semantic_Model",
      tool: d + "_semantic_query",
      agent: t + "_expert",
      capability: d + "_expert",
      orchestratorTool: "ask_" + d + "_expert",
      wizardConfig: "wizard/" + d + "-config.json",
      generated: "/python/owismind_hub/generated/" + t + "_expert.py"
    };
  }

  function obj(kind, name, where, id, note) {
    return { kind: kind, name: name, where: where || "", id: id || "", note: note || "" };
  }

  /* The 12 objects a creation run produces, in Flow order. `captured` (optional)
   * adds the ids the server recorded (model, tool, agent). */
  function createdObjects(n, captured) {
    var c = captured || {};
    return [
      obj("Flow zone", n.zone, "Flow"),
      obj("Dataset", n.profile, "Flow, in the zone"),
      obj("Dataset", n.valueIndex, "Flow, in the zone"),
      obj("Dataset", n.valueCatalog, "Flow, in the zone"),
      obj("Recipe", "compute_" + n.profile, "Flow, in the zone"),
      obj("Recipe", "compute_" + n.valueIndex, "Flow, in the zone"),
      obj("Recipe", "compute_" + n.valueCatalog, "Flow, in the zone"),
      obj("Scenario", n.scenario, "Scenarios"),
      obj("Semantic model", n.model, "Agents & GenAI", c.model_id),
      obj("Semantic Model Query tool", n.tool, "Agents & GenAI", c.tool_id),
      obj("Code Agent", n.agent, "Agents & GenAI", c.agent_id),
      obj("Capability", n.capability, "capabilities.json (hub)")
    ];
  }

  function objectsList(items, removalStyle, protectedItems) {
    var rows = items.map(function (o) {
      return '<li class="obj">' +
        '<span class="obj-mark' + (removalStyle ? " obj-mark--remove" : "") + '"></span>' +
        '<span class="obj-kind">' + esc(o.kind) + '</span>' +
        '<span class="obj-name"><span class="mono">' + esc(o.name) + '</span>' +
        (o.id ? ' <span class="obj-id mono">' + esc(o.id) + '</span>' : "") +
        (o.note ? '<span class="obj-note">' + esc(o.note) + '</span>' : "") + '</span>' +
        '<span class="obj-where">' + esc(o.where) + '</span></li>';
    }).join("");
    return '<ul class="objects">' + rows + '</ul>' + protectedList(protectedItems);
  }

  /* "Never touched" list (removal): the source dataset and any dataset shared
   * with another capability. */
  function protectedList(items) {
    if (!items || !items.length) { return ""; }
    return '<div class="protected"><p class="afc-mlabel">Never touched</p><ul class="objects">' +
      items.map(function (p) {
        return '<li class="obj obj--protected"><span class="obj-mark obj-mark--keep"></span>' +
          '<span class="obj-kind">' + esc(en(p.kind_fr || "Dataset")) + '</span>' +
          '<span class="obj-name"><span class="mono">' + esc(p.name || "") + '</span>' +
          (p.note_fr ? '<span class="obj-note">' + esc(en(p.note_fr)) + '</span>' : "") + '</span>' +
          '<span class="obj-where">' + esc(en(p.where_fr || "Flow")) + '</span></li>';
      }).join("") + '</ul></div>';
  }

  /* ============================ stage microcopy (front-only) ============================ */

  var GUARANTEE = {
    create: "Nothing is deleted. Running this step again is safe.",
    read: "Read-only: nothing is created or deleted in DSS.",
    verify: "I only read DSS to confirm it is done. I change nothing.",
    detach: "Nothing is deleted at this step."
  };

  function codeEnvName() {
    var s = ((S.overview.data || {}).settings || {}).code_env_311;
    return s || "DSS Agentic Python 3.11";
  }

  /* One entry per server stage key. ctx = {spec, names, captured, removal,
   * inventory, key, label, stage}. sentence() returns HTML (values escaped);
   * objects() returns obj() rows; removalItems=true reads the server inventory;
   * steps(ctx) returns the numbered checklist (HTML strings) of a MANUAL stage.
   * A key missing here falls back on the server title / detail (future stages). */
  var STAGE_UX = {
    /* ---- creation ---- */
    preflight: {
      title: "Check the project is compatible", guarantee: "read",
      sentence: function (c) {
        return "I check the hub, the source dataset " + mono(c.names.base) +
          " (must not be partitioned), name collisions and the orchestrator version. Read-only, nothing is created.";
      },
      primary: "Check", retry: "Check again"
    },
    plan: {
      title: "Verify the plan (dry run)", guarantee: "read",
      sentence: function () {
        return "A dry run: I go through the whole creation WITHOUT changing anything in DSS, to confirm it can " +
          "succeed and to list exactly what will be created. Every later step is then done for you, one click at a time.";
      },
      objectsLabel: "What will be created during the run",
      objects: function (c) { return createdObjects(c.names, c.captured); },
      primary: "Verify the plan"
    },
    infra: {
      title: "Create the zone, datasets and recipes", guarantee: "create",
      sentence: function (c) {
        return "I create the Flow zone " + mono(c.names.zone) +
          ", 3 knowledge datasets, their 3 recipes and the refresh scenario.";
      },
      objects: function (c) { return createdObjects(c.names).slice(0, 8); },
      primary: "Create these 8 objects",
      wait: "About one minute."
    },
    first_build: {
      title: "Build the knowledge datasets", guarantee: "create",
      sentence: function (c) {
        return "I run the scenario " + mono(c.names.scenario) +
          " for you and wait for its result: profile, value index, value catalog.";
      },
      objectsLabel: "What will be filled",
      objects: function (c) {
        return [obj("Dataset", c.names.profile, "Flow"),
                obj("Dataset", c.names.valueIndex, "Flow"),
                obj("Dataset", c.names.valueCatalog, "Flow")];
      },
      primary: "Run the build",
      wait: "Usually 2 to 10 minutes. You can close the page: the run resumes where it is."
    },
    profile_review: {
      title: "Review the profile", guarantee: "verify",
      sentence: function () {
        return "The profile describes the data to the sub-agent. Have a quick look before going on.";
      },
      steps: function (c) {
        return [
          "In the Flow, open the dataset " + copyable(c.names.profile) + " (tab <b>Explore</b>).",
          "Read the column descriptions, synonyms and listed values (statuses, types, categories).",
          "If something is wrong, fix it in the overrides dataset (it always wins), then rebuild the profile. " +
            "If everything looks right, there is nothing to change."
        ];
      }
    },
    wizard: {
      title: "Describe the semantic model (AI)", guarantee: "verify",
      sentence: function () {
        return "The AI writes a draft of the semantic model from the profile (aggregated metadata only, " +
          "no data rows) and may ask you a few questions.";
      }
    },
    brain: {
      title: "Create the semantic model and its tool", guarantee: "create",
      sentence: function (c) {
        return "I create the semantic model " + mono(c.names.model) +
          ", apply the draft, index it and create the tool " + mono(c.names.tool) + ".";
      },
      objects: function (c) { return createdObjects(c.names, c.captured).slice(8, 10); },
      primary: "Create the model and the tool",
      wait: "1 to 3 minutes (indexing).",
      // Manual fallback (the instance did not allow the automatic tool creation).
      steps: function (c, stage) {
        var desc = "";
        var m = String((stage && stage.instructions_fr) || "").match(/Description for LLM :\n([\s\S]*?)\n5\./);
        if (m) { desc = m[1]; }
        var list = [
          "In DSS, open <b>Agents &amp; GenAI Models</b> &gt; <b>Tools</b> &gt; <b>+ New tool</b>, type <b>Semantic Model Query</b>, name " + copyable(c.names.tool) + ".",
          "Link it to the semantic model " + copyable(c.names.model) + ".",
          "Set <b>Agent mode</b> to OFF, LLM = the factory default model (Settings &gt; models), dataset access <b>as the calling user</b>."
        ];
        if (desc) {
          list.push("Paste this text into <b>Description for LLM</b>:<pre class=\"afc-pre\">" + esc(desc) + "</pre>" +
            '<button class="afc-btn afc-btn--ghost afc-btn--sm" data-copy="' + esc(desc) + '">' + I.copy + 'Copy the description</button>');
        }
        list.push("Click <b>Save</b>.");
        return list;
      }
    },
    template: {
      title: "Check the sub-agent engine", guarantee: "read",
      sentence: function () {
        return "I check that the shared sub-agent engine (template file) is present in the hub.";
      },
      primary: "Check",
      steps: function () {
        return [
          "Open <b>&lt;/&gt; Code</b> &gt; <b>Libraries</b> in this project.",
          "Under " + mono("python/owismind_hub") + ", create the folder " + copyable("templates") +
            " and in it the file " + copyable("dataset_expert.py") + ".",
          "Paste into it the code of the Code Agent " + copyable("SalesDrive_revenue_expert") +
            " (open it, tab <b>Code</b>, select all, copy). Click <b>Save</b>."
        ];
      }
    },
    agent_code: {
      title: "Generate the sub-agent code", guarantee: "create",
      sentence: function (c) {
        return "I generate the code of the sub-agent " + mono(c.names.agent) +
          " with the right ids. If the instance allows it I also create the Code Agent; otherwise the next step tells you exactly how.";
      },
      objects: function (c) {
        return [obj("Code Agent", c.names.agent, "Agents & GenAI (if the instance allows it)"),
                obj("File", c.names.generated, "project library")];
      },
      primary: "Generate the code"
    },
    code_agent: {
      title: "Create the Code Agent", guarantee: "verify",
      sentence: function () {
        return "This is the only copy-paste of the run. Follow the steps in order.";
      },
      steps: function (c) {
        var tool = c.captured.tool_id;
        return [
          "In DSS, open <b>Agents &amp; GenAI Models</b> &gt; <b>Agents</b> and click <b>+ New agent</b> &gt; <b>Code Agent</b>.",
          "Name it exactly " + copyable(c.names.agent) + ".",
          "In <b>Select code template</b>, choose <b>LangGraph routing agent</b>, then click <b>Create</b>.",
          "Open the agent's <b>Settings</b> tab &gt; <b>Code</b> section &gt; <b>Code environment</b>: select " +
            copyable(codeEnvName()) + ". Click <b>Save</b>.",
          "In another tab, open <b>&lt;/&gt; Code</b> &gt; <b>Libraries</b>, then the file " + copyable(c.names.generated) +
            ". Select all its content and copy it.",
          "Back in the agent, open the <b>Code</b> tab, delete all the existing code and paste the copied code." +
            (tool ? " Check that the line " + mono("SEMANTIC_TOOL_ID") + " says " + mono(tool) + "." : ""),
          "Click <b>Save</b>."
        ];
      }
    },
    capability: {
      title: "Register the capability", guarantee: "create",
      sentence: function (c) {
        return "I add the capability " + mono(c.names.capability) +
          " to the orchestrator registry, DISABLED for now.";
      },
      objects: function (c) {
        return [obj("Capability", c.names.capability, "capabilities.json (previous file backed up)")];
      },
      primary: "Register"
    },
    business_prompt: {
      title: "Write the business prompt", guarantee: "create",
      sentence: function (c) {
        return "The factory AI writes a first business prompt for " + mono(c.names.capability) +
          " (vocabulary, rules, worked examples) from the dataset profile and the semantic model. " +
          "It is saved as an UNREVIEWED draft that the agent does not use: you read it in the agent Settings and click Save to make it live. A live prompt is never touched.";
      },
      objects: function (c) {
        return [obj("Business prompt", "business_prompt.md", "hub: prompts/" + c.domain + "/business_prompt.draft.md (not read by the agent)")];
      },
      primary: "Write the prompt"
    },
    smoke: {
      title: "Test the sub-agent", guarantee: "verify",
      sentence: function () {
        return "The sub-agent is not enabled in the orchestrator yet: test it on its own, in DSS.";
      },
      steps: function (c) {
        return [
          "Open <b>Agents &amp; GenAI Models</b> &gt; <b>Agents</b> &gt; " + copyable(c.names.agent) + " and open its test chat.",
          "Ask " + mono("What does this data contain?") + ": you should get a description of " + mono(c.names.base) + ".",
          "Ask a simple figure, for example " + mono("How many rows per category?") + ": you should get a table."
        ];
      }
    },
    enable: {
      title: "Enable the sub-agent", guarantee: "create",
      sentence: function (c) {
        return "I enable the capability: the orchestrator gains the tool " +
          mono(c.names.orchestratorTool) + ".";
      },
      objectsLabel: "What changes",
      objects: function (c) {
        return [obj("Capability", c.names.capability, "enabled: true"),
                obj("Orchestrator tool", c.names.orchestratorTool, "orchestrator")];
      },
      primary: "Enable"
    },

    /* ---- removal ---- */
    inventory: {
      title: "Take the inventory", guarantee: "read",
      sentence: function () {
        return "I list what really exists for this sub-agent in the project. Nothing is deleted.";
      },
      primary: "Take the inventory",
      steps: function (c) {
        var conflicts = (c.inventory && c.inventory.template_conflicts) || [];
        return [
          "Some objects of this domain are used as TEMPLATES by the factory: " +
            conflicts.map(function (x) { return mono(x); }).join(", ") + ".",
          "I understand that until they are re-pointed in " + mono("factory_settings.json") +
            ", the factory cannot create new sub-agents. The removal can still go on."
        ];
      }
    },
    disable: {
      title: "Disable the capability", guarantee: "detach",
      sentence: function () {
        return "I disable the capability: the orchestrator stops sending questions to this sub-agent.";
      },
      objectsLabel: "What changes",
      objects: function (c) { return [obj("Capability", c.key, "enabled: false")]; },
      primary: "Disable"
    },
    delete_tool: {
      title: "Delete the Semantic Model Query tool", removalItems: true,
      sentence: function () { return "I delete the Semantic Model Query tool of this domain."; },
      primary: "Delete the tool"
    },
    delete_agent: {
      title: "Delete the Code Agent", removalItems: true,
      sentence: function () { return "I delete the Code Agent of this domain."; },
      primary: "Delete the Code Agent"
    },
    delete_model: {
      title: "Delete the semantic model", removalItems: true,
      sentence: function () { return "I delete the semantic model of this domain."; },
      primary: "Delete the model"
    },
    delete_scenario: {
      title: "Delete the scenario", removalItems: true,
      sentence: function () { return "I delete the refresh scenario of this domain."; },
      primary: "Delete the scenario"
    },
    delete_recipes: {
      title: "Delete the recipes", removalItems: true,
      sentence: function () { return "I delete the knowledge recipes of this domain."; },
      primary: "Delete the recipes"
    },
    delete_datasets: {
      title: "Delete the knowledge datasets", removalItems: true,
      sentence: function () {
        return "I delete the derived datasets and their SQL tables (they can be rebuilt).";
      },
      primary: "Delete the datasets"
    },
    delete_zone: {
      title: "Delete the Flow zone", removalItems: true,
      sentence: function () { return "I delete the domain's Flow zone if it is empty, otherwise I keep it."; },
      primary: "Delete the zone"
    },
    catalog_cleanup: {
      title: "Clean the shared catalog",
      sentence: function () {
        return "I delete this sub-agent's rows in the shared value catalog (parameterized SQL).";
      },
      objects: function (c) { return [obj("Rows", "capability_key = " + c.key, "shared catalog")]; },
      primary: "Clean the catalog"
    },
    hub_cleanup: {
      title: "Clean the hub",
      sentence: function () {
        return "I delete this domain's wizard config, prompts and generated code, then its capability " +
          "(capabilities.json is backed up first).";
      },
      objects: function (c) {
        var paths = (c.inventory && c.inventory.hub_paths) || [];
        var rows = paths.map(function (p) { return obj("File", p, "hub"); });
        rows.push(obj("Capability", c.key, "capabilities.json"));
        return rows;
      },
      primary: "Clean the hub"
    },
    final_check: {
      title: "Check everything is gone", guarantee: "read",
      sentence: function () { return "I check that every inventoried object is really gone."; },
      primary: "Check"
    },

    /* ---- review (improve an existing sub-agent) ---- */
    review_load: {
      title: "Read what it knows today", guarantee: "read",
      sentence: function () { return "I read what the expert knows about its data today. Nothing is changed."; },
      primary: "Read", retry: "Read again"
    },
    review_feedback: {
      title: "Explain what to fix",
      sentence: function () { return "You explain what went wrong, the AI proposes changes, you choose which ones to keep."; }
    },
    review_apply: {
      title: "Save the changes",
      sentence: function () {
        return "I save the changes you kept. The current version is kept as a backup, so it can always be restored.";
      },
      primary: "Save the changes", retry: "Try again",
      wait: "About one minute."
    }
  };

  /* Removal stages whose launch actually deletes DSS objects (danger style, the
   * confirm modal repeats the exact deletion list). */
  var REMOVAL_DANGER_STAGES = {
    delete_tool: 1, delete_agent: 1, delete_model: 1, delete_scenario: 1,
    delete_recipes: 1, delete_datasets: 1, delete_zone: 1,
    catalog_cleanup: 1, hub_cleanup: 1
  };

  function isRemovalRun(run) { return !!(run && run.state && run.state.removal); }
  function isReviewRun(run) { return !!(run && run.state && run.state.review); }

  /* Everything the stage renderers need, for a creation OR a removal run. */
  function stageCtx(run) {
    var state = (run && run.state) || {};
    var removal = state.removal || null;
    var spec = state.spec || {};
    var label;
    if (removal || state.review) {
      var entry = (removal || state.review).entry || {};
      spec = { domain: entry.domain || run.domain || "", base_dataset: entry.lookup_dataset || "" };
      label = entry.label_en || entry.label_fr || spec.domain;
    } else {
      label = spec.label_en || spec.label_fr || spec.domain || run.domain || "";
    }
    var names = derivedNames(spec);
    return {
      run: run, spec: spec, names: names, captured: state.captured || {},
      removal: removal, inventory: (removal && removal.inventory) || null,
      key: removal ? (removal.capability_key || names.capability) : names.capability,
      label: label || names.domain
    };
  }

  function stageTitle(key, stage) {
    var ux = STAGE_UX[key];
    return (ux && ux.title) || (stage && stage.title_fr) || key;
  }

  function stageObjects(key, ctx) {
    var ux = STAGE_UX[key];
    if (!ux) { return []; }
    if (ux.removalItems) {
      var items = ((ctx.inventory && ctx.inventory.stages) || {})[key] || [];
      return items.map(function (it) {
        return obj(en(it.kind_fr), it.name || "", en(it.where_fr), it.id || "", en(it.note_fr));
      });
    }
    return ux.objects ? (ux.objects(ctx) || []) : [];
  }

  /* The numbered checklist of a manual (waiting_user) stage. Removal deletion
   * stages refused by the API list the objects to delete by hand. */
  function manualSteps(key, ctx, stage) {
    var ux = STAGE_UX[key] || {};
    if (ctx.removal && REMOVAL_DANGER_STAGES[key] === 1) {
      var manual = ((ctx.removal.manual || {})[key]) || [];
      var list = manual.map(function (it) {
        return "Delete by hand in DSS: " + esc(en(it.kind_fr || "object")) + " " + copyable(it.name || "?") +
          " (" + esc(en(it.where_fr || "DSS")) + ").";
      });
      if (!list.length) { list.push("Delete by hand in DSS the objects listed above."); }
      return list;
    }
    if (ux.steps) { return ux.steps(ctx, stage) || []; }
    return null;
  }

  /* "What will happen": the sentence, then the object list (created / deleted /
   * checked), then the never-touched list for the removal. */
  function stageWhatBlock(key, ctx, stage) {
    var ux = STAGE_UX[key];
    var html = '<p class="stage-sentence">' +
      ((ux && ux.sentence) ? ux.sentence(ctx) : esc((stage && stage.detail_fr) || "").replace(/\n/g, "<br>")) +
      '</p>';
    if (!ux) { return html; }
    var items = stageObjects(key, ctx);
    var prot = (ctx.removal && key === "delete_datasets" && ctx.inventory) ? (ctx.inventory.protected || []) : [];
    if (ux.removalItems && ctx.inventory && !items.length) {
      html += '<p class="afc-muted">Nothing to delete: already gone. The step will simply be validated.</p>' +
        protectedList(prot);
    } else if (items.length) {
      var removalStyle = !!(ctx.removal && REMOVAL_DANGER_STAGES[key] === 1);
      var label = ux.objectsLabel || (ctx.removal ? "What will be deleted" : "What will be created");
      html += '<p class="afc-mlabel">' + esc(label) + ' (' + items.length + ')</p>' +
        objectsList(items, removalStyle, prot);
    }
    return html;
  }

  function guaranteeLine(key, ctx) {
    var ux = STAGE_UX[key] || {};
    if (ctx.removal && REMOVAL_DANGER_STAGES[key] === 1) {
      return "Irreversible. The source dataset " + ctx.names.base + " is never touched.";
    }
    return GUARANTEE[ux.guarantee] || "";
  }

  function isSkippedStage(stage) {
    var j = (stage && stage.journal) || [];
    var last = j[j.length - 1];
    return !!(last && last.status === "SKIPPED" && /déjà satisfait/.test(last.detail || ""));
  }
  function stageDisplayStatus(run, key) {
    var stage = ((run.state || {}).stages || {})[key] || {};
    if (key === run.current_stage && S.guided.running) { return "running"; }
    if (stage.status === "done" && isSkippedStage(stage)) { return "skipped"; }
    return stage.status || "pending";
  }

  function stageChip(status) {
    var map = {
      pending: { cls: "pending", txt: "To come" },
      ready: { cls: "ready", txt: "To run" },
      running: { cls: "running", txt: "Running" },
      waiting_user: { cls: "waiting", txt: "Your turn" },
      done: { cls: "done", txt: "Done" },
      skipped: { cls: "done", txt: "Already done" },
      failed: { cls: "failed", txt: "Failed" }
    };
    var m = map[status] || map.pending;
    return '<span class="afc-chip st st--' + m.cls + '">' + esc(m.txt) + '</span>';
  }

  /* The preflight journal says whether the compatibility probe (notebook 00)
   * ever ran: a SKIPPED preflight_probe action means probe_results.json is absent. */
  function probeMissing(run) {
    var pre = ((run.state || {}).stages || {}).preflight;
    var j = (pre && pre.journal) || [];
    for (var i = 0; i < j.length; i++) {
      if (j[i].step === "preflight_probe" && j[i].status === "SKIPPED") { return true; }
    }
    return false;
  }

  /* ============================ guided run: load / apply ============================ */

  function guidedErrorText(data) {
    var map = {
      confirmation_required: "Confirmation is required.",
      invalid_spec: "The sub-agent information is invalid.",
      active_run_exists: "A run is already in progress: finish it or abandon it first.",
      busy: "Another factory operation is running. Try again in a moment.",
      server_error: "The server could not finish the operation.",
      unknown_run: "This run cannot be found.",
      run_not_active: "This run is no longer active.",
      stage_not_runnable: "This step cannot be run in its current state.",
      stage_not_verifiable: "This step cannot be checked in its current state.",
      too_many_jobs: "Too many jobs are registered on the server. Try again later.",
      storage_not_configured: "The SQL storage of the runs is not configured.",
      domain_mismatch: "The typed name does not match the domain: nothing was created.",
      unknown_capability: "This capability no longer exists in the registry.",
      review_not_supported: "This sub-agent was set up by hand, before this console existed: it cannot be improved here yet. Ask the technical team.",
      feedback_required: "Write at least one sentence first.",
      invalid_path: "Invalid prompt path.",
      network_error: "The connection to the backend failed.",
      no_backend: "The DSS backend is unavailable.",
      poll_failed: "Following the job failed after several attempts.",
      job_error: "The server job failed."
    };
    if (data && data.messages && data.messages.length) { return data.messages.join(" ; "); }
    return map[data && data.error] || (data && data.error) || "unknown error";
  }

  function resetGuidedWizard() {
    S.guided.wizard = { running: false, jobId: null, config: null,
                        answers: {}, drafted: null, redrafted: false, error: null, reqId: 0 };
  }

  function applyGuidedRun(run) {
    var g = S.guided;
    var previous = g.run;
    var previousId = previous && previous.run_id;
    // Remember which stage just finished, to show it above the next one.
    g.lastDone = null;
    if (run && previous && run.run_id === previousId && previous.current_stage &&
        previous.current_stage !== run.current_stage) {
      var st = ((run.state || {}).stages || {})[previous.current_stage];
      if (st && st.status === "done") { g.lastDone = previous.current_stage; }
    }
    g.run = run || null;
    g.liveActions = [];
    g.actionError = null;
    g.verifyFailed = false;
    if (!run || run.run_id !== previousId) {
      resetGuidedWizard();
      g.probe = { running: false, report: null, error: null };
      g.review = null;
    }
    if (isReviewRun(run)) { syncReviewUi(run); }
  }

  /* Callers arriving while a load is in flight are queued, so a screen switch
   * during the overview's load still gets its render callback. */
  var _guidedLoadCbs = [];
  function loadGuidedCurrent(cb) {
    var g = S.guided;
    if (cb) { _guidedLoadCbs.push(cb); }
    if (g.loading) { return; }
    g.loading = true;
    g.error = null;
    callApi("GET", "guided/current").then(function (r) {
      g.loading = false;
      var cbs = _guidedLoadCbs;
      _guidedLoadCbs = [];
      if (r.data && r.data.status === "ok") {
        g.loaded = true;
        var run = r.data.run && r.data.run.status !== "abandoned" ? r.data.run : null;
        // A finished run stays on screen (success card) until the user leaves it.
        if (!run && g.run && g.run.status === "done") { run = g.run; }
        applyGuidedRun(run);
      } else {
        g.error = guidedErrorText(r.data);
      }
      cbs.forEach(function (fn) { fn(); });
    });
  }

  /* A run's first stage executes synchronously at creation (preflight / inventory):
   * surface it as "Step done" above the next stage. */
  function markFirstStageDone(run) {
    var order = (run && run.state && run.state.stage_order) || [];
    var first = order[0];
    var st = first && run.state.stages && run.state.stages[first];
    if (st && st.status === "done" && run.current_stage !== first) { S.guided.lastDone = first; }
  }

  function hasActiveRun() {
    return !!(S.guided.run && S.guided.run.status === "active");
  }

  /* ============================ screen: Overview ============================ */

  function loadOverview() {
    var o = S.overview;
    if (o.loading) { return; }
    o.loading = true;
    o.error = null;
    renderOverview();
    var pending = 2;
    function oneDone() { pending -= 1; if (pending === 0) { renderOverview(); } }
    callApi("GET", "state").then(function (r) {
      o.loading = false;
      if (r.data && r.data.status === "ok") {
        o.loaded = true;
        o.data = r.data;
      } else {
        o.error = (r.data && r.data.error) || "load_error";
      }
      oneDone();
    });
    S.guided.loaded = false;
    loadGuidedCurrent(oneDone);
  }

  function renderOverview() {
    if (S.view !== "overview") { return; }
    var o = S.overview;
    var html = backendBanner();

    if (o.loading && !o.loaded) {
      setHeader({ title: "Orchestrator and sub-agents", sub: "Loading the project..." });
      setMain(html + '<p class="afc-muted afc-pad">Loading the project...</p>');
      return;
    }
    if (o.error && !o.loaded) {
      html += '<div class="afc-note afc-note--error">Cannot read the project (' + esc(o.error) + ').</div>' +
        '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="ovRetry">' +
        I.refresh + 'Retry</button></div>';
      setMain(html);
      if (byId("ovRetry")) { byId("ovRetry").onclick = loadOverview; }
      return;
    }

    var d = o.data || {};
    var settings = d.settings || {};
    var caps = d.capabilities || {};
    var keys = Object.keys(caps);
    var active = keys.filter(function (k) { return caps[k] && caps[k].enabled; }).length;
    var runActive = hasActiveRun();

    setHeader({
      title: "Orchestrator and sub-agents",
      sub: "Each sub-agent is the expert of one domain (one source dataset). When enabled, the orchestrator sends it the questions of that domain.",
      action: '<button class="afc-btn afc-btn--primary" id="ovAdd"' + (runActive ? " disabled" : "") + '>' +
        I.plus + 'Add a sub-agent</button>'
    });

    html += resumeBanner();

    if (o.flash) {
      html += '<div class="afc-note afc-note--error">' + esc(o.flash) + '</div>';
      o.flash = null;
    }
    if (o.notice) {
      html += '<div class="nextstep nextstep--top"><p class="afc-mlabel">' + esc(o.notice) +
        ' Last step: reload the orchestrator</p>' + reloadSteps() + '</div>';
      o.notice = null;
    }

    // Org chart (root on top, sub-agents side by side) up to 4 sub-agents; beyond,
    // a vertical trunk keeps every node readable.
    var org = d.hub_ready && keys.length > 0 && keys.length <= 4;
    html += '<div class="tree' + (org ? " tree--org" : "") + '"' +
      (org ? ' style="--cols:' + keys.length + '"' : "") + '>';
    html += '<div class="node node--root">' +
      '<span class="node-icon">' + I.hub + '</span>' +
      '<div class="node-main"><p class="node-eyebrow">Orchestrator</p>' +
      '<p class="node-title">OWIsMind</p>' +
      '<p class="node-meta">' +
      (settings.orchestrator_agent_id ? 'Code Agent ' + mono(settings.orchestrator_agent_id) + ' · ' : "") +
      esc(keys.length) + ' sub-agent' + (keys.length > 1 ? "s" : "") + ', ' +
      esc(active) + ' enabled</p></div>' +
      '<div class="node-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" data-cap-settings="' + ORCH_KEY + '">Settings</button></div></div>';

    if (!d.hub_ready) {
      html += '<div class="branches"><div class="branch"><div class="afc-note afc-note--warn branch-note">' +
        'The hub (capabilities.json) is missing from the project library: the orchestrator uses its ' +
        'built-in list of sub-agents. Push the hub (notebook 01) to manage the sub-agents here.' +
        '</div></div></div>';
    } else if (!keys.length) {
      html += '<div class="branches"><div class="branch"><div class="afc-note afc-note--info branch-note">' +
        'No sub-agent registered yet.</div></div></div>';
    } else {
      html += (org ? '<span class="stem"></span>' : "") + '<div class="branches">';
      keys.forEach(function (k) { html += subAgentNode(k, caps[k] || {}, runActive); });
      html += '</div>';
    }
    html += '</div>';

    html += '<div class="afc-actions ov-foot"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="ovRefresh">' +
      I.refresh + 'Refresh</button>' +
      '<span class="afc-muted">Project ' + mono(d.project_key || "-") + '</span></div>';

    setMain(html);
    if (byId("ovAdd")) { byId("ovAdd").onclick = openAddScreen; }
    if (byId("ovResume")) { byId("ovResume").onclick = function () { go("run"); }; }
    if (byId("ovRefresh")) { byId("ovRefresh").onclick = function () { S.overview.loaded = false; loadOverview(); }; }
    Array.prototype.forEach.call(document.querySelectorAll("[data-cap-settings]"), function (btn) {
      btn.onclick = function () { openAgentSettings(btn.getAttribute("data-cap-settings")); };
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-cap-toggle]"), function (btn) {
      btn.onclick = function () { confirmCapabilityToggle(btn.getAttribute("data-cap-toggle")); };
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-cap-remove]"), function (btn) {
      btn.onclick = function () { openCapabilityRemoval(btn.getAttribute("data-cap-remove")); };
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-cap-review]"), function (btn) {
      btn.onclick = function () { startReview(btn.getAttribute("data-cap-review")); };
    });
  }

  function subAgentNode(key, c, runActive) {
    var on = !!c.enabled;
    var lockTitle = runActive ? ' title="A run is in progress: finish it or abandon it first."' : "";
    return '<div class="branch"><div class="node' + (on ? "" : " node--off") + '">' +
      '<div class="node-main">' +
      '<div class="node-titleline"><p class="node-title">' + esc(c.label_en || c.label_fr || c.domain || key) + '</p>' +
      (on ? '<span class="afc-chip afc-chip--on">Enabled</span>' : '<span class="afc-chip afc-chip--off">Disabled</span>') +
      '</div>' +
      '<dl class="node-facts">' +
      '<div><dt>Domain</dt><dd class="mono">' + esc(c.domain || "-") + '</dd></div>' +
      '<div><dt>Source dataset</dt><dd class="mono">' + esc(c.lookup_dataset || "-") + '</dd></div>' +
      '<div><dt>Capability</dt><dd class="mono">' + esc(key) + '</dd></div>' +
      '<div><dt>Code Agent</dt><dd class="mono">' + esc(c.agent_id || "-") + '</dd></div>' +
      '</dl></div>' +
      '<div class="node-actions">' +
      '<button class="afc-btn afc-btn--primary afc-btn--sm" data-cap-review="' + esc(key) + '"' +
      (runActive ? " disabled" : "") + lockTitle + '>Improve</button>' +
      '<button class="afc-btn afc-btn--ghost afc-btn--sm" data-cap-settings="' + esc(key) + '">Settings</button>' +
      '<button class="afc-btn afc-btn--ghost afc-btn--sm" data-cap-toggle="' + esc(key) + '">' +
      (on ? "Disable" : "Enable") + '</button>' +
      '<button class="afc-btn afc-btn--danger afc-btn--sm" data-cap-remove="' + esc(key) + '"' +
      (runActive ? " disabled" : "") + lockTitle + '>Remove</button>' +
      '</div></div></div>';
  }

  function resumeBanner() {
    if (!hasActiveRun()) {
      if (S.guided.error) {
        return '<div class="afc-note afc-note--error">Cannot read the run in progress: ' +
          esc(S.guided.error) + '</div>';
      }
      return "";
    }
    var run = S.guided.run;
    var ctx = stageCtx(run);
    var order = (run.state && run.state.stage_order) || [];
    var stage = ((run.state || {}).stages || {})[run.current_stage];
    var kind = isRemovalRun(run) ? "Removal" : (isReviewRun(run) ? "Improvement" : "Addition");
    return '<div class="resume">' +
      '<div><p class="afc-mlabel">Run in progress</p>' +
      '<p class="resume-text">' + esc(kind) + ' of the sub-agent <b>' + esc(ctx.label) + '</b>: step ' +
      esc(order.indexOf(run.current_stage) + 1) + ' of ' + esc(order.length) + ', ' +
      esc(stageTitle(run.current_stage, stage)) + '.</p></div>' +
      '<button class="afc-btn afc-btn--primary" id="ovResume">Resume</button></div>';
  }

  function confirmCapabilityToggle(key) {
    var caps = (S.overview.data || {}).capabilities || {};
    var c = caps[key] || {};
    var next = !c.enabled;
    openConfirm({
      title: next ? "Enable this sub-agent?" : "Disable this sub-agent?",
      bodyHtml: "<p>The capability <b class=\"mono\">" + esc(key) + "</b> becomes <b>" +
        (next ? "ENABLED" : "DISABLED") + "</b> in capabilities.json (the previous file is backed up). " +
        "Nothing else changes: the Code Agent, the semantic model and the datasets stay in place.</p>" +
        "<p>Afterwards, reload the orchestrator so it sees the change:</p>" + reloadSteps(),
      confirmLabel: next ? "Enable" : "Disable",
      onConfirm: function () {
        callApi("POST", "capability/enable", {
          confirm: true, capability_key: key, enabled: next
        }).then(function (r) {
          if (!r.data || r.data.status !== "ok") {
            S.overview.flash = "Change refused (" + guidedErrorText(r.data) + ").";
            renderOverview();
            return;
          }
          S.overview.notice = next ? "Sub-agent enabled." : "Sub-agent disabled.";
          S.overview.loaded = false;
          loadOverview();
        });
      }
    });
  }

  function openCapabilityRemoval(key) {
    var caps = (S.overview.data || {}).capabilities || {};
    var c = caps[key] || {};
    var domain = c.domain || key;
    openConfirm({
      title: "Remove the sub-agent " + (c.label_en || c.label_fr || domain) + "?",
      danger: true,
      bodyHtml: "<p>Nothing is deleted now. A removal run is created: it first takes the inventory, " +
        "then shows you each deletion and asks you to confirm it, ONE AT A TIME.</p>" +
        "<p>The source dataset <b class=\"mono\">" + esc(c.lookup_dataset || "-") + "</b> is NEVER touched.</p>" +
        "<p>To confirm, type the exact domain name (<b class=\"mono\">" + esc(domain) + "</b>):</p>" +
        "<input class=\"afc-input mono afc-modal-input\" type=\"text\" id=\"capRemoveTyped\" autocomplete=\"off\">",
      confirmLabel: "Create the removal run",
      onConfirm: function () {
        var field = byId("capRemoveTyped");
        var typed = (field ? field.value : "").trim();
        callApi("POST", "guided/start-removal", {
          confirm: true, capability_key: key, domain_typed: typed
        }).then(function (r) {
          if (!r.data || r.data.status !== "ok") {
            S.overview.flash = guidedErrorText(r.data);
            renderOverview();
            return;
          }
          applyGuidedRun(r.data.run || null);
          markFirstStageDone(r.data.run);
          S.guided.loaded = !!r.data.run;
          go("run");
        });
      }
    });
  }

  /* Improve: starting a review only READS the expert's current setup (nothing is
   * changed in DSS), so it opens directly, without a confirm modal. */
  function startReview(key) {
    callApi("POST", "guided/start-review", { confirm: true, capability_key: key }).then(function (r) {
      if (!r.data || r.data.status !== "ok") {
        S.overview.flash = guidedErrorText(r.data);
        renderOverview();
        return;
      }
      applyGuidedRun(r.data.run || null);
      markFirstStageDone(r.data.run);
      S.guided.loaded = !!r.data.run;
      go("run");
    });
  }

  /* ============================ screen: Run ============================ */

  function openAddScreen() {
    if (S.guided.run && S.guided.run.status === "done") { applyGuidedRun(null); }
    go("run");
  }

  function renderRun() {
    if (S.view !== "run") { return; }
    var g = S.guided;
    var html = '<div>' + backendBanner();
    setHeader({ back: true, eyebrow: "Add a sub-agent", title: "Run", sub: "" });

    if (g.loading && !g.loaded) {
      setMain(html + '<p class="afc-muted afc-pad">Looking for a run in progress...</p></div>');
      wireBack();
      return;
    }
    if (g.error && !g.loaded) {
      html += '<div class="afc-note afc-note--error">Cannot read the run: ' + esc(g.error) + '</div>' +
        '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="gdRetry">' +
        I.refresh + 'Retry</button></div></div>';
      setMain(html);
      wireBack();
      if (byId("gdRetry")) { byId("gdRetry").onclick = function () { loadGuidedCurrent(renderRun); }; }
      return;
    }

    if (!g.run) {
      if (!S.datasets.loaded && !S.datasets.loading) {
        loadDatasets(function () { if (S.view === "run" && !S.guided.run) { renderRun(); } });
      }
      html += renderStartForm() + '</div>';
      setMain(html);
      wireBack();
      wireStartForm();
      return;
    }

    if (g.run.status === "done") {
      headerForRun(g.run);
      html += '<div class="layout"><div class="layout-main">' + renderRunDone(g.run) +
        '</div><aside class="layout-aside">' + renderTracker(g.run) + '</aside></div></div>';
      setMain(html);
      wireBack();
      if (byId("gdHome")) { byId("gdHome").onclick = function () { applyGuidedRun(null); go("overview"); }; }
      return;
    }

    // Two columns: the stage to act on (left) and the always-visible tracker (right).
    html += '<div class="layout"><div class="layout-main">' +
      headerForRun(g.run) + renderLastDone(g.run) + renderCurrentStage(g.run) + renderAbandon(g.run) +
      '</div><aside class="layout-aside">' + renderTracker(g.run) + '</aside></div>';
    html += '</div>';
    setMain(html);
    wireBack();
    wireRun();
  }

  /* ---------- start form (creation) ---------- */

  function guidedStartSpec() {
    var f = S.guided.form;
    return {
      domain: (f.domain || "").trim(),
      base_dataset: (f.base_dataset || "").trim(),
      label_fr: (f.label_fr || "").trim(),
      label_en: (f.label_en || "").trim(),
      lookup_search_columns: (f.lookup || "").split(",").map(function (v) {
        return v.trim();
      }).filter(Boolean)
    };
  }

  function renderStartForm() {
    var g = S.guided;
    var f = g.form;
    var picker = S.datasets.loading
      ? '<p class="afc-muted">Loading the datasets...</p>'
      : '<select class="afc-select" id="gdBaseDataset">' + datasetOptions(f.base_dataset) + '</select>';
    setHeader({
      back: true, eyebrow: "Add a sub-agent", title: "New sub-agent",
      sub: "13 steps, one at a time: each step shows what it will create before doing it. Nothing is deleted, and the run resumes if you close the page."
    });
    var html = "";

    html += '<section class="card">' +
      field("Domain", inputEl("gdDomain", f.domain, "e.g. opportunities"),
        "Short key in lower case (letters, digits, underscores). It names every object created.") +
      '<div class="afc-field"><span class="afc-field-label">Source dataset</span>' +
      '<div class="picker-row">' + picker +
      '<button class="afc-btn afc-btn--ghost afc-btn--sm" id="gdRefreshDatasets"' +
      (S.datasets.loading ? " disabled" : "") + '>' + I.refresh + 'Refresh</button></div>' +
      '<p class="afc-field-help">The project dataset the sub-agent will be the expert of. It is never modified.</p></div>' +
      field("Label", inputEl("gdLabel", f.label_en, "e.g. Sales opportunities"),
        "The name shown for this sub-agent (same label in every language).") +
      field("Search columns (optional)",
        inputEl("gdLookup", f.lookup, "e.g. Account_name, Opportunity_name"),
        "Text columns where the orchestrator looks up exact names, separated by commas. Empty = every text column.");
    if (S.datasets.error) {
      html += '<div class="afc-note afc-note--error">Dataset list unavailable: ' + esc(S.datasets.error) + '</div>';
    }
    html += '</section>';

    if (g.startError) {
      html += '<div class="afc-note afc-note--error">Cannot start: ' + esc(g.startError) + '</div>';
    }
    html += '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="gdStart"' +
      (g.starting ? " disabled" : "") + '>' + I.play +
      (g.starting ? "Starting..." : "Start the run") + '</button>' +
      '<span class="afc-muted">Step 1 checks the project is compatible, read-only.</span></div>';
    var aside = '<section class="card tracker"><p class="afc-mlabel">What will be created during the run (12)</p>' +
      '<div id="gdPreview">' + objectsList(createdObjects(derivedNames(guidedStartSpec()))) + '</div>' +
      '<p class="afc-mlabel tracker-sub">How it goes</p><ol class="howto">' +
      '<li>Check the project is compatible (read-only).</li>' +
      '<li>Create the zone, the knowledge datasets, their recipes and the scenario, then build them.</li>' +
      '<li>Describe the semantic model with the AI, then create the model and its tool.</li>' +
      '<li>Create the sub-agent\'s Code Agent (one copy-paste, guided), register it, test it, enable it.</li></ol></section>';
    return '<div class="layout"><div class="layout-main">' + html + '</div>' +
      '<aside class="layout-aside">' + aside + '</aside></div>';
  }

  function refreshPreview() {
    var p = byId("gdPreview");
    if (p) { p.innerHTML = objectsList(createdObjects(derivedNames(guidedStartSpec()))); }
  }

  function wireStartForm() {
    var f = S.guided.form;
    bindInput("gdDomain", function (v) { f.domain = v; refreshPreview(); });
    bindInput("gdBaseDataset", function (v) { f.base_dataset = v; refreshPreview(); }, true);
    // One technical label, sent as both label_en and label_fr (the engine keeps two keys).
    bindInput("gdLabel", function (v) { f.label_en = v; f.label_fr = v; });
    bindInput("gdLookup", function (v) { f.lookup = v; });
    if (byId("gdRefreshDatasets")) {
      byId("gdRefreshDatasets").onclick = function () {
        loadDatasets(function () { renderRun(); }, true);
        renderRun();
      };
    }
    if (byId("gdStart")) { byId("gdStart").onclick = confirmGuidedStart; }
  }

  function confirmGuidedStart() {
    var spec = guidedStartSpec();
    openConfirm({
      title: "Start the run?",
      bodyHtml: "<p>A run is saved for the domain <b class=\"mono\">" +
        esc(spec.domain || "(no name)") + "</b> on the source dataset <b class=\"mono\">" +
        esc(spec.base_dataset || "(not chosen)") + "</b>.</p><p>Step 1 (compatibility check, " +
        "read-only) runs right away. Nothing else is created without your click.</p>",
      confirmLabel: "Start",
      onConfirm: startGuided
    });
  }

  function startGuided() {
    var g = S.guided;
    g.starting = true;
    g.startError = null;
    g.startErrorCode = null;
    renderRun();
    callApi("POST", "guided/start", { confirm: true, spec: guidedStartSpec() }).then(function (r) {
      g.starting = false;
      if (r.data && r.data.status === "ok" && r.data.run) {
        applyGuidedRun(r.data.run);
        markFirstStageDone(r.data.run);
        toast("Run started.");
      } else {
        g.startErrorCode = r.data && r.data.error;
        g.startError = guidedErrorText(r.data);
      }
      renderRun();
    });
  }

  /* ---------- run head + tracker ---------- */

  /* Header of a run: which sub-agent, and which step is being done right now. */
  function headerForRun(run) {
    var ctx = stageCtx(run);
    var order = (run.state && run.state.stage_order) || [];
    var stages = (run.state && run.state.stages) || {};
    var idx = order.indexOf(run.current_stage);
    var where = run.status === "done" ? "All " + order.length + " steps done"
      : "Step " + (idx + 1) + " of " + order.length + ": " + stageTitle(run.current_stage, stages[run.current_stage]);
    setHeader({
      back: true,
      eyebrow: isRemovalRun(run) ? "Remove a sub-agent" : (isReviewRun(run) ? "Improve a sub-agent" : "Add a sub-agent"),
      title: ctx.label,
      sub: '<b>' + esc(where) + '</b> · domain ' + mono(ctx.names.domain) + ' · source dataset ' + mono(ctx.names.base)
    });
    return "";
  }

  /* Right column of the run screen: progress + every stage with its status,
   * always visible (sticky), so nobody scrolls to know where the run is. */
  function renderTracker(run) {
    var order = (run.state && run.state.stage_order) || [];
    var stages = (run.state && run.state.stages) || {};
    var idx = order.indexOf(run.current_stage);
    var done = run.status === "done";
    var cells = order.map(function (key, i) {
      var st = stageDisplayStatus(run, key);
      var cls = (done || st === "done" || st === "skipped") ? " seg--done" : (i === idx ? " seg--current" : "");
      return '<span class="seg' + cls + '"></span>';
    }).join("");
    var rows = order.map(function (key, i) {
      var cur = !done && key === run.current_stage;
      return '<li class="step' + (cur ? " step--current" : "") + '">' +
        '<span class="step-n mono">' + esc(i + 1) + '</span>' +
        '<span class="step-title">' + esc(stageTitle(key, stages[key])) + '</span>' +
        stageChip(done ? "done" : stageDisplayStatus(run, key)) + '</li>';
    }).join("");
    return '<section class="card tracker"><p class="afc-mlabel">Progress</p>' +
      '<p class="afc-progress-label">' + (done ? "All " + esc(order.length) + " steps done"
        : "Step " + esc(idx + 1) + " of " + esc(order.length)) + '</p>' +
      '<div class="segs">' + cells + '</div>' +
      '<ol class="steps">' + rows + '</ol></section>';
  }

  function renderLastDone(run) {
    var key = S.guided.lastDone;
    if (!key) { return ""; }
    var stage = ((run.state || {}).stages || {})[key];
    if (!stage) { return ""; }
    return '<div class="lastdone"><span class="lastdone-mark">' + I.check + '</span>' +
      '<p>Step done: <b>' + esc(stageTitle(key, stage)) + '</b></p></div>';
  }

  /* ---------- current stage ---------- */

  function tickKey(run) { return run.run_id + ":" + run.current_stage; }
  function ticksOf(run) {
    var k = tickKey(run);
    if (!S.guided.ticks[k]) { S.guided.ticks[k] = {}; }
    return S.guided.ticks[k];
  }

  function renderChecklist(run, steps) {
    var ticks = ticksOf(run);
    return '<ol class="checklist">' + steps.map(function (html, i) {
      var on = !!ticks[i];
      return '<li class="check' + (on ? " check--on" : "") + '">' +
        '<button class="check-box" data-tick="' + i + '" aria-pressed="' + (on ? "true" : "false") +
        '" title="Mark this step as done">' + I.check + '</button>' +
        '<span class="check-n mono">' + (i + 1) + '</span>' +
        '<div class="check-text">' + html + '</div></li>';
    }).join("") + '</ol>';
  }

  function allTicked(run, count) {
    var ticks = ticksOf(run);
    for (var i = 0; i < count; i++) { if (!ticks[i]) { return false; } }
    return true;
  }

  function renderCurrentStage(run) {
    var g = S.guided;
    var key = run.current_stage;
    var stage = ((run.state || {}).stages || {})[key] || null;
    if (!stage) {
      return '<div class="afc-note afc-note--error">The current step is missing from the run.</div>';
    }
    var ctx = stageCtx(run);
    var ux = STAGE_UX[key] || {};
    var status = g.running ? "running" : stage.status;
    var dangerous = !!(ctx.removal && REMOVAL_DANGER_STAGES[key] === 1);
    var manual = status === "waiting_user";

    var html = '<section class="card stage' + (dangerous && !manual ? " stage--danger" : "") + '">' +
      '<p class="stage-eyebrow">Step ' + esc(((run.state && run.state.stage_order) || []).indexOf(key) + 1) +
      ' of ' + esc(((run.state && run.state.stage_order) || []).length) + '</p>' +
      '<div class="stage-head"><h3>' + esc(stageTitle(key, stage)) + '</h3>' + stageChip(status) + '</div>';

    if (manual && key === "review_feedback") {
      html += renderReview(run, stage);
    } else if (manual && key === "wizard") {
      html += '<div class="stage-block"><p class="stage-sentence">' + ux.sentence(ctx) + '</p></div>';
      html += renderWizard(run, stage);
    } else if (manual) {
      // A manual stage: numbered checklist, button locked until every step is ticked.
      var steps = manualSteps(key, ctx, stage);
      html += '<div class="stage-block"><p class="afc-mlabel">Your turn: do these steps in DSS</p>' +
        (ux.sentence && !dangerous ? '<p class="stage-sentence">' + ux.sentence(ctx) + '</p>' : "");
      if (steps && steps.length) {
        html += renderChecklist(run, steps) + '</div>';
        var ready = allTicked(run, steps.length);
        html += verifyFailedNote(stage);
        html += '<div class="stage-cta"><button class="afc-btn afc-btn--primary" id="gdVerify"' +
          (!ready || g.verifying ? " disabled" : "") + '>' + I.check +
          (g.verifying ? "Checking..." : "Done, check it") + '</button>' +
          '<p class="afc-muted" id="gdVerifyHint">' + (ready ? esc(GUARANTEE.verify)
            : "Tick every step once it is done to unlock the check.") + '</p></div>';
      } else {
        // Unknown future manual stage: the server text is the only source.
        html += '<div class="instructions">' + esc(stage.instructions_fr || stage.detail_fr || "").replace(/\n/g, "<br>") +
          '</div></div>' + verifyFailedNote(stage) +
          '<div class="stage-cta"><button class="afc-btn afc-btn--primary" id="gdVerify"' +
          (g.verifying ? " disabled" : "") + '>' + I.check + (g.verifying ? "Checking..." : "Done, check it") + '</button></div>';
      }
    } else {
      // 1. What will happen (and what gets created / deleted / checked)
      html += '<div class="stage-block"><p class="afc-mlabel">What will happen</p>' +
        stageWhatBlock(key, ctx, stage) + '</div>';
      if (stage.problems && stage.problems.length) {
        html += '<div class="afc-note afc-note--error"><b>This step reported a problem.</b> Fix it in DSS, then run the step again.' +
          detailsBlock("srv:" + run.run_id + ":" + key, "Server message (technical)",
            '<ul class="srv">' + stage.problems.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join("") + '</ul>',
            true) + '</div>';
      }
      // 2. The button and its guarantee line
      var guarantee = guaranteeLine(key, ctx);
      if (status === "ready" || status === "failed") {
        var label = status === "failed" ? (ux.retry || "Run again") : (ux.primary || "Run this step");
        html += '<div class="stage-cta"><button class="afc-btn ' + (dangerous ? "afc-btn--danger-solid" : "afc-btn--primary") +
          '" id="gdRunStage"' + (g.running ? " disabled" : "") + '>' + I.play + esc(label) + '</button>' +
          (guarantee ? '<p class="afc-muted">' + esc(guarantee) + '</p>' : "") + '</div>';
      } else if (status === "running") {
        var last = g.liveActions.length ? g.liveActions[g.liveActions.length - 1] : null;
        html += '<div class="running"><span class="running-dot"></span><div>' +
          '<p><b>Running...</b>' + (ux.wait ? " " + esc(ux.wait) : "") + '</p>' +
          (last ? '<p class="afc-muted mono">' + esc(last.step) + ': ' + esc(last.detail || "") + '</p>' : "") +
          '</div></div>';
        if (!g.running) {
          html += '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="gdRefreshRun">' +
            I.refresh + 'Refresh</button></div>';
        }
      } else if (status === "pending") {
        html += '<div class="afc-note afc-note--info">This step waits for the previous one.</div>';
      }
      if (key === "enable" && (status === "ready" || status === "failed")) {
        html += '<p class="afc-muted stage-after">After this step you will reload the orchestrator (explained on the next screen).</p>';
      }
    }

    if (g.actionError) {
      html += '<div class="afc-note afc-note--error">Operation refused: ' + esc(g.actionError) + '</div>';
    }

    // Compatibility probe never recorded: explained in the first steps.
    if (key === "preflight" || key === "plan") { html += renderProbeHint(run); }

    // Technical journal, collapsed unless the stage failed.
    var journal = (g.running && g.liveActions.length) ? g.liveActions : (stage.journal || []);
    if (journal.length) {
      html += detailsBlock("journal:" + run.run_id + ":" + key,
        "Technical details (server log, " + journal.length + " lines)",
        actionsTable(journal), status === "failed");
    }
    html += '</section>';
    return html;
  }

  /* What a failed check means, per manual stage, in plain English (the frozen
   * engine words its problems in French: they go to a collapsed technical block). */
  var NOT_DONE = {
    profile_review: function (c) { return "The dataset " + mono(c.names.profile) + " was not found in the Flow."; },
    wizard: function () { return "The draft saved in the hub is missing or incomplete. Click 'Draft again from scratch' (step 1)."; },
    brain: function (c) { return "No tool named " + mono(c.names.tool) + " was found. Check the exact name and that you clicked Save."; },
    template: function () { return "The file " + mono("python/owismind_hub/templates/dataset_expert.py") + " is missing or does not contain the engine code."; },
    code_agent: function (c) { return "No Code Agent named " + mono(c.names.agent) + " was found. Check the exact name (use the copy button) and that you clicked Save."; },
    smoke: function (c) { return "The capability " + mono(c.names.capability) + " is no longer in the registry."; }
  };

  /* After a failed "Done, check it": what is missing, in plain words. */
  function verifyFailedNote(stage) {
    if (!S.guided.verifyFailed && !(stage.problems && stage.problems.length)) { return ""; }
    var run = S.guided.run;
    var ctx = stageCtx(run);
    var key = run.current_stage;
    var why = NOT_DONE[key] ? NOT_DONE[key](ctx)
      : (ctx.removal ? "Some objects are still in DSS: delete them, then check again." : "");
    var probs = stage.problems || [];
    return '<div class="afc-note afc-note--error"><b>Not done yet.</b> ' + why +
      ' Go through the steps again, then click "Done, check it" once more.' +
      (probs.length ? detailsBlock("srv:" + run.run_id + ":" + key, "Server message (technical)",
        '<ul class="srv">' + probs.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join("") + '</ul>', false) : "") +
      '</div>';
  }

  function renderProbeHint(run) {
    if (!probeMissing(run)) { return ""; }
    var p = S.guided.probe;
    var html = '<div class="probe"><p class="afc-mlabel">Project compatibility never recorded</p>' +
      '<p>The compatibility result (notebook ' + mono("00_probe_capabilities") + ') is missing from the hub. ' +
      'This does not block you: the "tool" and "Code Agent" steps will then be guided manual steps. ' +
      'To automate them, run that notebook in DSS, then run step 1 again.</p>';
    if (p.running) {
      html += '<p class="afc-muted">Reading the project (read-only)...</p>';
    } else {
      html += '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="gdProbe">' +
        'See what the project allows (read-only)</button></div>';
    }
    if (p.error) { html += '<div class="afc-note afc-note--error">Cannot read: ' + esc(p.error) + '</div>'; }
    if (p.report) {
      html += detailsBlock("probe:" + run.run_id, "Compatibility report",
        '<div class="afc-actions afc-actions--tight">' + copyButton("gdProbeCopy", "Copy the report") + '</div>' +
        '<pre class="afc-pre">' + esc(p.report) + '</pre>', true);
    }
    return html + '</div>';
  }

  function renderAbandon(run) {
    var g = S.guided;
    var stage = ((run.state || {}).stages || {})[run.current_stage];
    var disabled = g.abandoning || g.running || g.verifying || g.wizard.running ||
      (stage && stage.status === "running");
    disabled = disabled || !!(g.review && (g.review.running || g.review.saving));
    if (isReviewRun(run)) {
      return '<div class="abandon"><p class="afc-muted">Stopping here changes nothing: the expert keeps what it knows today.</p>' +
        '<button class="afc-btn afc-btn--ghost afc-btn--sm" id="gdAbandon"' +
        (disabled ? " disabled" : "") + '>Stop without saving</button></div>';
    }
    return '<div class="abandon"><p class="afc-muted">Abandoning stops the run without deleting anything: ' +
      (isRemovalRun(run) ? "what was already deleted stays deleted, the rest stays in place." : "what was already created stays in place.") +
      '</p><button class="afc-btn afc-btn--danger afc-btn--sm" id="gdAbandon"' +
      (disabled ? " disabled" : "") + '>Abandon this run</button></div>';
  }

  function renderRunDone(run) {
    var ctx = stageCtx(run);
    if (isReviewRun(run)) {
      var applied = (run.state.review && run.state.review.applied) || {};
      var n = applied.count || 0;
      return '<section class="card done">' +
        '<p class="afc-eyebrow">Improvement saved</p>' +
        '<h2 class="afc-h2">' + esc(ctx.label) + ' knows more about its data</h2>' +
        '<p class="afc-lead">' + esc(n) + ' change' + (n > 1 ? "s" : "") + ' saved. ' +
        'The previous version is kept as a backup.</p>' +
        '<div class="nextstep"><p class="afc-mlabel">Now check it</p><ol class="steps-plain">' +
        (applied.routing ? '<li>Reload the orchestrator (steps below): you changed which questions it sends to this expert.</li>' : "") +
        '<li>Open OWIsMind and start a <b>new conversation</b>.</li>' +
        '<li>Ask the same questions again.</li>' +
        '<li>Still not right? Come back and click <b>Improve</b> again.</li></ol></div>' +
        (applied.routing ? reloadBlock("Reload the orchestrator") : "") +
        '<div class="nextstep"><p class="afc-mlabel">Same lesson for the agent prompt?</p>' +
        '<p class="afc-field-help">This improvement changed how the data is described for the SQL. ' +
        'The agent\'s own business prompt (how it understands questions) is separate: you can update it with the same feedback.</p>' +
        '<div class="afc-actions"><button class="afc-btn afc-btn--ghost" id="rvToPrompt">Update the business prompt too</button></div></div>' +
        '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="gdHome">Back to the overview</button></div>' +
        '</section>';
    }
    if (isRemovalRun(run)) {
      return '<section class="card done">' +
        '<p class="afc-eyebrow">Removal finished</p>' +
        '<h2 class="afc-h2">The sub-agent ' + esc(ctx.label) + ' is removed</h2>' +
        '<p class="afc-lead">Its objects were deleted one by one. The source dataset ' +
        mono(ctx.names.base) + ' is intact.</p>' +
        reloadBlock() +
        '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="gdHome">Back to the overview</button></div>' +
        '</section>';
    }
    var captured = (run.state && run.state.captured) || {};
    return '<section class="card done">' +
      '<p class="afc-eyebrow">Addition finished</p>' +
      '<h2 class="afc-h2">The sub-agent ' + esc(ctx.label) + ' is enabled</h2>' +
      '<dl class="afc-kv">' +
      '<dt>Domain</dt><dd>' + esc(run.domain || "-") + '</dd>' +
      '<dt>Code Agent</dt><dd>' + esc(captured.agent_id || "-") + '</dd>' +
      '<dt>Tool</dt><dd>' + esc(captured.tool_id || "-") + '</dd></dl>' +
      reloadBlock("Last step: reload the orchestrator to use the new sub-agent") +
      '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="gdHome">Back to the overview</button></div>' +
      '</section>';
  }

  /* ---------- semantic wizard (stage "wizard"): a strict 3-step sequence ----------
   * 1. Draft with AI (the only enabled action). 2. Answer the AI's questions;
   * changing an answer requires "Redraft" (the check stays locked while answers
   * differ from the last draft). 3. "Done, check it". */

  /* True when an answer ON SCREEN differs from the answers the current draft was
   * built with. Only the CURRENT questions count: a redraft may return brand new
   * questions (new ids), and answers to questions that are gone must never keep
   * the check locked (field bug 2026-10-14). */
  function answersDirty() {
    var w = S.guided.wizard;
    if (!w.config || !w.drafted) { return false; }
    var questions = w.config.questions || [];
    for (var i = 0; i < questions.length; i++) {
      var qid = String(questions[i].id || "");
      var shown = w.answers[qid] == null ? "" : String(w.answers[qid]);
      var drafted = w.drafted[qid] == null ? "" : String(w.drafted[qid]);
      if (shown !== drafted) { return true; }
    }
    return false;
  }

  function renderWizard(run, stage) {
    var g = S.guided;
    var w = g.wizard;
    var spec = (run.state && run.state.spec) || {};
    var profile = (spec.base_dataset || "") + "_profile";
    var hasDraft = !!w.config;
    var dirty = answersDirty();
    var questions = (w.config && w.config.questions) || [];

    var html = '<ol class="seq">';
    // Step 1: draft
    html += '<li class="seq-item' + (hasDraft ? " seq-item--done" : " seq-item--current") + '">' +
      '<p class="seq-title"><span class="seq-n mono">1</span>Draft the model with the AI</p>' +
      '<p class="afc-muted">The AI reads the profile ' + mono(profile) + ' and writes the draft (about 30 s to 1 min). It is saved in the hub automatically.</p>';
    if (w.running) {
      html += '<div class="running running--inline"><span class="running-dot"></span><p>Writing the draft...</p></div>';
    } else if (!hasDraft) {
      html += '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="gdWizardDraft">' +
        I.play + 'Draft with AI</button></div>';
    } else {
      // Always offer a clean restart: a draft the check refuses must never strand the user.
      html += '<p class="seq-ok">' + I.check + 'Draft saved.</p>' +
        '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="gdWizardRestart">' +
        I.refresh + 'Draft again from scratch</button></div>';
    }
    if (w.error) {
      html += '<div class="afc-note afc-note--error">Draft failed: ' + esc(w.error) + '</div>';
    }
    html += '</li>';

    // Step 2: answer the questions
    html += '<li class="seq-item' + (!hasDraft ? " seq-item--todo" : (dirty ? " seq-item--current" : " seq-item--done")) + '">' +
      '<p class="seq-title"><span class="seq-n mono">2</span>Answer the AI\'s questions</p>';
    if (!hasDraft) {
      html += '<p class="afc-muted">Available after the draft.</p>';
    } else if (!questions.length) {
      html += '<p class="seq-ok">' + I.check + (w.redrafted ? "Your answers were applied. The AI has no further question."
        : "The AI has no question.") + '</p>';
    } else {
      html += '<p class="afc-muted">' + (w.redrafted ? "Your answers were applied. The AI has a few follow-up questions: " : "") +
        'The suggested answers are already applied to the draft. Change one only if it is wrong, then click "Redraft". ' +
        'If they are fine, go straight to step 3.</p>';
      questions.forEach(function (q) {
        var qid = String(q.id || "");
        var answer = w.answers[qid] != null ? w.answers[qid] : (q.default != null ? q.default : "");
        html += '<div class="question"><p class="question-title">' + esc(q.question_en || q.question_fr || qid) + '</p>' +
          (q.why ? '<p class="question-why">' + esc(q.why) + '</p>' : "") +
          (q.options && q.options.length ? '<p class="question-why">Suggestions: ' + esc(q.options.join(", ")) + '</p>' : "") +
          '<input class="afc-input gd-wizard-answer" data-qid="' + esc(qid) + '" value="' + esc(answer) + '"></div>';
      });
      html += '<div class="afc-actions"><button class="afc-btn afc-btn--ghost" id="gdWizardRedraft"' +
        (dirty && !w.running ? "" : " disabled") + '>' + I.refresh + 'Redraft with my answers</button>' +
        '<button class="afc-btn afc-btn--ghost afc-btn--sm" id="gdWizardDiscard"' + (dirty && !w.running ? "" : " disabled") +
        '>Discard my changes</button>' +
        '<span class="afc-muted" id="gdWizardHint">' + (dirty ? "You changed an answer: click Redraft to apply it."
          : "Answers applied.") + '</span></div>';
    }
    html += '</li>';

    // Step 3: check
    var ready = hasDraft && !dirty && !w.running;
    html += '<li class="seq-item' + (ready ? " seq-item--current" : " seq-item--todo") + '">' +
      '<p class="seq-title"><span class="seq-n mono">3</span>Check and continue</p>' +
      verifyFailedNote(stage) +
      '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="gdVerify"' +
      (ready && !g.verifying ? "" : " disabled") + '>' + I.check +
      (g.verifying ? "Checking..." : "Done, check it") + '</button>' +
      '<span class="afc-muted">' + (ready ? "I check that the draft is saved in the hub."
        : (dirty ? "Redraft first." : "Draft with AI first.")) + '</span></div></li>';
    return html + '</ol>';
  }

  /* Live answer edits: refresh only the two buttons (no re-render, keeps focus). */
  function updateWizardButtons() {
    var dirty = answersDirty();
    var re = byId("gdWizardRedraft");
    var ver = byId("gdVerify");
    var hint = byId("gdWizardHint");
    if (re) { re.disabled = !dirty; }
    if (byId("gdWizardDiscard")) { byId("gdWizardDiscard").disabled = !dirty; }
    if (ver) { ver.disabled = dirty; }
    if (hint) { hint.textContent = dirty ? "You changed an answer: click Redraft to apply it." : "Answers applied."; }
  }

  /* ---------- review (stage "review_feedback"): explain, then choose ----------
   * Phase 1: the expert writes, in their own words, what went wrong and what the
   * agent must know. Phase 2: the AI's proposed changes, one card each, all kept
   * by default; untick what is wrong, then save (one confirm). Every word here is
   * for a business person: no technical vocabulary. */

  var REVIEW_ACTION = { added: "New", changed: "Changed", removed: "Removed" };
  var REVIEW_AREA = { entity: "row description", column: "column meaning", search: "value recognition",
    metric: "calculation", filter: "ready-made filter", term: "word list", example: "example question",
    rules: "general rules", routing: "routing text" };

  /* Word-level diff (LCS) as safe HTML: removed words struck, added words highlighted.
   * Returns null when the texts are too long to diff cheaply (caller shows both sides). */
  function wordDiff(before, after) {
    var a = String(before || "").split(/(\s+)/).filter(function (t) { return t !== ""; });
    var b = String(after || "").split(/(\s+)/).filter(function (t) { return t !== ""; });
    if (a.length > 1600 || b.length > 1600) { return null; }
    var n = a.length, m = b.length, i, j;
    var dp = [];
    for (i = 0; i <= n; i++) { dp.push(new Array(m + 1).fill(0)); }
    for (i = n - 1; i >= 0; i--) {
      for (j = m - 1; j >= 0; j--) {
        dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    var out = [];
    i = 0; j = 0;
    while (i < n && j < m) {
      if (a[i] === b[j]) { out.push(esc(a[i])); i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push('<del class="df-del">' + esc(a[i]) + '</del>'); i++; }
      else { out.push('<ins class="df-add">' + esc(b[j]) + '</ins>'); j++; }
    }
    while (i < n) { out.push('<del class="df-del">' + esc(a[i++]) + '</del>'); }
    while (j < m) { out.push('<ins class="df-add">' + esc(b[j++]) + '</ins>'); }
    return out.join("").replace(/<\/(del|ins)>(\s+)<(del|ins) class="df-(del|add)">/g, function (all, c1, sp, c2, k) {
      return (c1 === c2) ? sp : all;
    });
  }

  /* The text shown on the "after" side, following the operator's own rewrite. */
  function reviewAfterText(c, r) {
    var v = r.edits[c.id];
    if (v === undefined) { return c.after; }
    if (c.area === "metric" || c.area === "filter") {
      var k = String(c.after || "").indexOf("\nComputed as:");
      return v + (k >= 0 ? String(c.after).slice(k) : "");
    }
    return v;
  }

  function reviewDiffBlock(c, r) {
    var after = reviewAfterText(c, r);
    if (c.action === "added") {
      return '<div class="rv-diff"><ins class="df-add">' + esc(after) + '</ins></div>';
    }
    if (c.action === "removed") {
      return '<div class="rv-diff"><del class="df-del">' + esc(c.before) + '</del></div>';
    }
    var html = wordDiff(c.before, after);
    if (html === null) {
      return '<div class="rv-compare">' + reviewTextBlock("Today", c.before) + reviewTextBlock("After", after) + '</div>';
    }
    return '<div class="rv-diff">' + html + '</div>';
  }

  function reviewSummary(changes) {
    var counts = {};
    changes.forEach(function (c) { counts[c.area] = (counts[c.area] || 0) + 1; });
    return Object.keys(counts).map(function (a) {
      return counts[a] + " " + (REVIEW_AREA[a] || a) + (counts[a] > 1 && a !== "rules" ? "s" : "");
    }).join(", ");
  }

  function syncReviewUi(run) {
    var info = run.state.review || {};
    var r = S.guided.review;
    var proposalId = info.proposal ? JSON.stringify(info.changes || []).length + ":" + (info.changes || []).length : "";
    if (!r) {
      r = S.guided.review = { wrong: "", know: "", answers: {}, keep: {}, edits: {}, editOpen: {}, proposalId: "",
                              editing: false, running: false, saving: false, error: null, reqId: 0 };
      r.wrong = (info.feedback && info.feedback.wrong) || "";
      r.know = (info.feedback && info.feedback.know) || "";
    }
    if (proposalId && proposalId !== r.proposalId) {
      // A new proposal: every change starts kept, the questions start on their suggestion.
      r.proposalId = proposalId;
      r.keep = {};
      r.edits = {};
      r.editOpen = {};
      (info.keep || []).forEach(function (id) { r.keep[id] = true; });
      r.answers = {};
      (info.questions || []).forEach(function (q) { r.answers[q.id] = q["default"] || ""; });
      r.editing = false;
    }
  }

  function keptCount() {
    var r = S.guided.review;
    var info = (S.guided.run && S.guided.run.state.review) || {};
    return (info.changes || []).filter(function (c) { return r && r.keep[c.id]; }).length;
  }

  function reviewTextBlock(title, text) {
    return '<div class="rv-side"><p class="rv-side-label">' + esc(title) + '</p>' +
      (text ? '<p class="rv-text">' + esc(text) + '</p>' : '<p class="rv-text rv-text--empty">Nothing</p>') + '</div>';
  }

  function renderReview(run, stage) {
    var r = S.guided.review;
    var info = run.state.review || {};
    var ctx = stageCtx(run);
    var hasProposal = !!info.proposal && !r.editing;
    var html = "";

    if (!hasProposal) {
      // Phase 1: explain.
      html += '<div class="stage-block">' +
        '<p class="stage-sentence">First test <b>' + esc(ctx.label) + '</b> in OWIsMind. Then write here, in your own words, ' +
        'what went wrong and what it should know. Write as if you were explaining your data to a new colleague. Any language is fine.</p>' +
        '<label class="rv-field"><span class="rv-label">Questions it got wrong</span>' +
        '<span class="rv-help">Copy the question you asked, then say what was wrong in the answer.</span>' +
        '<textarea class="afc-textarea" id="rvWrong" placeholder="I asked: total amount for Orange Belgium in 2025. The figure was twice too high.">' +
        esc(r.wrong) + '</textarea></label>' +
        '<label class="rv-field"><span class="rv-label">What it should know about this data</span>' +
        '<span class="rv-help">What words mean for your team, how to count, which column to use, what to leave out.</span>' +
        '<textarea class="afc-textarea" id="rvKnow" placeholder="Closed means the stage is Won. Each deal appears once per month: count each deal only once.">' +
        esc(r.know) + '</textarea></label></div>';
      if (r.running) {
        html += '<div class="running"><span class="running-dot"></span><div><p><b>The AI is preparing the changes...</b> About one minute.</p></div></div>';
      } else {
        var empty = !(r.wrong.trim() || r.know.trim());
        html += '<div class="stage-cta"><button class="afc-btn afc-btn--primary" id="rvPropose"' + (empty ? " disabled" : "") + '>' +
          I.play + 'Prepare the changes</button>' +
          (info.proposal ? '<button class="afc-btn afc-btn--ghost" id="rvBackToChanges">Back to the proposed changes</button>' : "") +
          '<p class="afc-muted" id="rvHint">' + (empty ? "Write at least one sentence to continue."
            : "The AI reads what the expert knows today, the description of the data and 20 example rows. Nothing is changed yet.") +
          '</p></div>';
      }
      if (r.error) { html += '<div class="afc-note afc-note--error">The AI could not prepare the changes: ' + esc(r.error) + '</div>'; }
      return html;
    }

    // Phase 2: choose.
    var changes = info.changes || [];
    var questions = info.questions || [];
    var kept = keptCount();
    if (!changes.length) {
      html += '<div class="afc-note afc-note--info"><b>The AI found nothing to change.</b> Try to be more precise: ' +
        'give the exact question you asked and the answer you expected.</div>';
    } else {
      html += '<div class="stage-block"><p class="stage-sentence">The AI proposes <b>' + esc(changes.length) + ' change' +
        (changes.length > 1 ? "s" : "") + '</b>: ' + esc(reviewSummary(changes)) + '. ' +
        '<b>Struck words</b> are removed, <b>highlighted words</b> are added. Untick what is wrong, ' +
        '<b>edit any text you want to word differently</b>, then save. You have the last word.</p></div>';
    }
    if (questions.length) {
      html += '<div class="rv-questions"><p class="afc-mlabel">The AI has a question' + (questions.length > 1 ? "s" : "") + ' for you</p>';
      questions.forEach(function (q) {
        html += '<label class="rv-field"><span class="rv-label">' + esc(q.question) + '</span>' +
          '<input class="afc-input rv-answer" data-qid="' + esc(q.id) + '" value="' + esc(r.answers[q.id] || "") + '"></label>';
      });
      html += '<div class="afc-actions">' + (r.running
        ? '<div class="running running--inline"><span class="running-dot"></span><p>The AI is preparing the changes again...</p></div>'
        : '<button class="afc-btn afc-btn--ghost" id="rvReprepare">' + I.refresh + 'Prepare again with my answers</button>' +
          '<span class="afc-muted">Or keep the changes below as they are.</span>') + '</div></div>';
    }
    if (changes.length) {
      html += '<ul class="rv-changes">' + changes.map(function (c) {
        var on = !!r.keep[c.id];
        var canEdit = c.edit !== null && c.edit !== undefined && c.action !== "removed";
        var changedByMe = r.edits[c.id] !== undefined && r.edits[c.id] !== c.edit;
        var editing = !!r.editOpen[c.id];
        return '<li class="rv-change' + (on ? "" : " rv-change--off") + '">' +
          '<button class="check-box" data-keep="' + esc(c.id) + '" aria-pressed="' + (on ? "true" : "false") +
          '" title="' + (on ? "Kept: click to ignore" : "Ignored: click to keep") + '">' + I.check + '</button>' +
          '<div class="rv-body"><div class="rv-head"><p class="rv-title">' + esc(c.label) + '</p>' +
          '<span>' + (changedByMe ? '<span class="afc-chip afc-chip--manual">Edited by you</span> ' : "") +
          '<span class="afc-chip">' + esc(REVIEW_ACTION[c.action] || c.action) + '</span></span></div>' +
          (c.why ? '<p class="rv-why">' + esc(c.why) + '</p>' : "") +
          findingsBlock(c.flags, "Looks like an injection: ignored by default, tick it only if you checked") +
          reviewDiffBlock(c, r) +
          (editing
            ? '<label class="rv-field"><span class="rv-help">Your wording replaces the AI text when you save.</span>' +
              '<textarea class="afc-textarea rv-edit" data-edit="' + esc(c.id) + '">' +
              esc(r.edits[c.id] !== undefined ? r.edits[c.id] : c.edit) + '</textarea></label>' +
              '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" data-edit-done="' + esc(c.id) + '">Done</button>' +
              '<button class="afc-btn afc-btn--ghost afc-btn--sm" data-edit-reset="' + esc(c.id) + '">Back to the AI text</button></div>'
            : (canEdit ? '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" data-edit-open="' + esc(c.id) + '">Edit the text</button></div>'
                       : '<p class="afc-field-help">Keep or ignore only.</p>')) +
          '</div></li>';
      }).join("") + '</ul>';
    }
    html += '<div class="stage-cta">' +
      (changes.length ? '<button class="afc-btn afc-btn--primary" id="rvSave"' + (!kept || r.saving || r.running ? " disabled" : "") + '>' +
        I.save + (r.saving ? "Saving..." : 'Save ' + kept + ' change' + (kept > 1 ? "s" : "")) + '</button>' : "") +
      '<button class="afc-btn afc-btn--ghost" id="rvEdit"' + (r.saving || r.running ? " disabled" : "") + '>Change my explanation</button>' +
      '<p class="afc-muted">' + (changes.length && !kept ? "Tick at least one change to save." : "The current version is kept as a backup, so it can always be restored.") + '</p></div>';
    if (r.error) { html += '<div class="afc-note afc-note--error">' + esc(r.error) + '</div>'; }
    return html;
  }

  function updateReviewButtons() {
    var r = S.guided.review;
    var btn = byId("rvPropose");
    var hint = byId("rvHint");
    var empty = !(r.wrong.trim() || r.know.trim());
    if (btn) { btn.disabled = empty; }
    if (hint) {
      hint.textContent = empty ? "Write at least one sentence to continue."
        : "The AI reads what the expert knows today, the description of the data and 20 example rows. Nothing is changed yet.";
    }
  }

  function wireReview() {
    var r = S.guided.review;
    if (!r) { return; }
    if (byId("rvWrong")) { byId("rvWrong").oninput = function () { r.wrong = this.value; updateReviewButtons(); }; }
    if (byId("rvKnow")) { byId("rvKnow").oninput = function () { r.know = this.value; updateReviewButtons(); }; }
    if (byId("rvPropose")) { byId("rvPropose").onclick = function () { proposeReview(false); }; }
    if (byId("rvReprepare")) { byId("rvReprepare").onclick = function () { proposeReview(true); }; }
    if (byId("rvBackToChanges")) { byId("rvBackToChanges").onclick = function () { r.editing = false; renderRun(); }; }
    if (byId("rvEdit")) { byId("rvEdit").onclick = function () { r.editing = true; r.error = null; renderRun(); }; }
    if (byId("rvSave")) { byId("rvSave").onclick = confirmReviewSave; }
    Array.prototype.forEach.call(document.querySelectorAll(".rv-answer"), function (elm) {
      elm.oninput = function () { r.answers[elm.getAttribute("data-qid")] = elm.value; };
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-edit-open]"), function (b) {
      b.onclick = function () { r.editOpen[b.getAttribute("data-edit-open")] = true; renderRun(); };
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-edit-done]"), function (b) {
      b.onclick = function () { r.editOpen[b.getAttribute("data-edit-done")] = false; renderRun(); };
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-edit-reset]"), function (b) {
      b.onclick = function () {
        var id = b.getAttribute("data-edit-reset");
        delete r.edits[id]; r.editOpen[id] = false; renderRun();
      };
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-edit]"), function (t) {
      t.oninput = function () { r.edits[t.getAttribute("data-edit")] = t.value; };
    });
    if (byId("rvToPrompt")) { byId("rvToPrompt").onclick = reviewToBusinessPrompt; }
    Array.prototype.forEach.call(document.querySelectorAll("[data-keep]"), function (b) {
      b.onclick = function () {
        var id = b.getAttribute("data-keep");
        r.keep[id] = !r.keep[id];
        renderRun();
      };
    });
  }

  /* After an Improve: open the agent Settings with the same feedback as AI instructions. */
  function reviewToBusinessPrompt() {
    var run = S.guided.run || {};
    var info = (run.state && run.state.review) || {};
    var fb = info.feedback || {};
    var text = [];
    if (fb.wrong) { text.push("What the agent got wrong:\n" + fb.wrong); }
    if (fb.know) { text.push("What it must know about this data:\n" + fb.know); }
    var key = info.capability_key;
    if (!key) { return; }
    openAgentSettings(key);
    S.agent.ai.instr = text.join("\n\n");
  }

  function proposeReview(withAnswers) {
    var g = S.guided;
    var r = g.review;
    var run = g.run || {};
    r.running = true;
    r.error = null;
    r.reqId += 1;
    var reqId = r.reqId;
    renderRun();
    callApi("POST", "review/propose", {
      confirm: true, run_id: run.run_id,
      feedback: { wrong: r.wrong, know: r.know },
      answers: withAnswers ? r.answers : {}
    }).then(function (res) {
      if (reqId !== r.reqId) { return; }
      if (!res.data || res.data.status !== "ok" || !res.data.job_id) {
        r.running = false;
        r.error = guidedErrorText(res.data);
        renderRun();
        return;
      }
      pollJob(res.data.job_id, null, function (result) {
        if (reqId !== r.reqId) { return; }
        r.running = false;
        if (!result || result.error || !result.run) {
          r.error = String((result && result.error) || "no answer");
        } else {
          r.editing = false;
          applyGuidedRun(result.run);
        }
        renderRun();
      }, function (err) {
        if (reqId !== r.reqId) { return; }
        r.running = false;
        r.error = guidedErrorText({ error: err });
        renderRun();
      });
    });
  }

  function confirmReviewSave() {
    var n = keptCount();
    var info = S.guided.run.state.review || {};
    var routing = (info.changes || []).some(function (c) { return c.area === "routing" && S.guided.review.keep[c.id]; });
    openConfirm({
      title: "Save " + n + " change" + (n > 1 ? "s" : "") + "?",
      bodyHtml: "<p>The expert will use these changes from its next answer. The current version is kept as a backup, " +
        "so it can always be restored. It takes about one minute.</p>" +
        (routing ? "<p>You changed which questions OWIsMind sends to this expert: you will reload the orchestrator at the end.</p>" : ""),
      confirmLabel: "Save",
      onConfirm: saveReview
    });
  }

  /* Keep the ticked changes (the server checks them), then save right away. */
  function saveReview(ack) {
    var g = S.guided;
    var r = g.review;
    var run = g.run || {};
    var info = run.state.review || {};
    var keep = (info.changes || []).filter(function (c) { return r.keep[c.id]; }).map(function (c) { return c.id; });
    r.saving = true;
    r.error = null;
    renderRun();
    var edits = {};
    (info.changes || []).forEach(function (c) {
      if (r.keep[c.id] && r.edits[c.id] !== undefined && r.edits[c.id] !== c.edit) { edits[c.id] = r.edits[c.id]; }
    });
    callApi("POST", "review/keep", { confirm: true, run_id: run.run_id, keep: keep, edits: edits,
                                     acknowledge_risks: ack === true }).then(function (res) {
      r.saving = false;
      if (res.data && res.data.error === "suspicious_content" && ack !== true) {
        renderRun();
        openConfirm({ title: "Suspicious content: save anyway?", danger: true,
          bodyHtml: findingsBlock(res.data.findings) + "<p>A change you kept (or edited) looks like a prompt injection. Save only if you checked it.</p>",
          confirmLabel: "I read it, save anyway", onConfirm: function () { saveReview(true); } });
        return;
      }
      if (!res.data || res.data.status !== "ok" || !res.data.run) {
        r.error = "Not saved: " + guidedErrorText(res.data);
        renderRun();
        return;
      }
      applyGuidedRun(res.data.run);
      if (res.data.run.current_stage === "review_apply" && reviewCanRun(res.data.run)) {
        runGuidedStage();
      } else {
        r.error = "Not saved: no change was kept.";
        renderRun();
      }
    });
  }

  function reviewCanRun(run) {
    var st = ((run.state || {}).stages || {})[run.current_stage] || {};
    return st.status === "ready" || st.status === "failed";
  }

  /* ---------- run wiring + actions ---------- */

  function wireRun() {
    wireReview();
    if (byId("gdRunStage")) { byId("gdRunStage").onclick = confirmGuidedStageRun; }
    if (byId("gdVerify")) { byId("gdVerify").onclick = verifyGuidedStage; }
    if (byId("gdRefreshRun")) { byId("gdRefreshRun").onclick = function () { S.guided.loaded = false; loadGuidedCurrent(renderRun); }; }
    if (byId("gdAbandon")) { byId("gdAbandon").onclick = confirmGuidedAbandon; }
    if (byId("gdProbe")) { byId("gdProbe").onclick = confirmProbe; }
    if (S.guided.probe.report) { wireCopy("gdProbeCopy", function () { return S.guided.probe.report; }); }
    if (byId("gdWizardDraft")) {
      byId("gdWizardDraft").onclick = function () { confirmGuidedWizardDraft(false); };
    }
    if (byId("gdWizardRestart")) {
      byId("gdWizardRestart").onclick = function () { confirmGuidedWizardDraft(false); };
    }
    if (byId("gdWizardDiscard")) {
      byId("gdWizardDiscard").onclick = function () {
        var w = S.guided.wizard;
        w.answers = JSON.parse(JSON.stringify(w.drafted || {}));
        renderRun();
      };
    }
    if (byId("gdWizardRedraft")) {
      byId("gdWizardRedraft").onclick = function () {
        gatherGuidedWizardAnswers();
        confirmGuidedWizardDraft(true);
      };
    }
    Array.prototype.forEach.call(document.querySelectorAll(".gd-wizard-answer"), function (elm) {
      elm.oninput = function () {
        S.guided.wizard.answers[elm.getAttribute("data-qid")] = elm.value;
        updateWizardButtons();
      };
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-tick]"), function (b) {
      b.onclick = function () {
        var run = S.guided.run;
        if (!run) { return; }
        var t = ticksOf(run);
        var i = b.getAttribute("data-tick");
        t[i] = !t[i];
        renderRun();
      };
    });
  }

  function confirmGuidedStageRun() {
    var run = S.guided.run || {};
    var key = run.current_stage;
    var stage = run.state && run.state.stages && run.state.stages[key];
    var ctx = stageCtx(run);
    var ux = STAGE_UX[key] || {};
    var dangerous = !!(ctx.removal && REMOVAL_DANGER_STAGES[key] === 1);
    var body;
    if (dangerous) {
      var items = stageObjects(key, ctx);
      body = "<p>This step will <b>DELETE in DSS</b>:</p>" +
        (items.length ? objectsList(items, true) : "<p>Nothing listed: already gone.</p>") +
        "<p>Irreversible. The source dataset <b class=\"mono\">" + esc(ctx.names.base) +
        "</b> is never touched.</p>";
    } else {
      body = '<p>' + ((ux.sentence) ? ux.sentence(ctx) : esc((stage && stage.detail_fr) || "")) + '</p>' +
        '<p>' + esc(guaranteeLine(key, ctx) || "Its log is shown live.") + '</p>';
    }
    openConfirm({
      title: stage && stage.status === "failed" ? "Run again: " + stageTitle(key, stage) + "?"
        : (dangerous ? "Confirm the deletion?" : stageTitle(key, stage) + "?"),
      bodyHtml: body,
      danger: dangerous,
      confirmLabel: stage && stage.status === "failed" ? "Run again" : (dangerous ? "Delete" : (ux.primary || "Run")),
      onConfirm: runGuidedStage
    });
  }

  function runGuidedStage() {
    var g = S.guided;
    var run = g.run || {};
    var stageKey = run.current_stage;
    g.running = true;
    g.actionError = null;
    g.liveActions = [];
    renderRun();
    callApi("POST", "guided/run", { confirm: true, run_id: run.run_id }).then(function (r) {
      if (!r.data || r.data.status !== "ok" || !r.data.job_id) {
        g.running = false;
        g.actionError = guidedErrorText(r.data);
        renderRun();
        return;
      }
      pollJob(r.data.job_id, function (actions) {
        g.liveActions = actions || [];
        renderRun();
      }, function (result, actions) {
        g.running = false;
        g.liveActions = actions || [];
        if (result && result.run) {
          applyGuidedRun(result.run);
          refreshDatasetsAfterInfra(stageKey, result.run);
        } else {
          g.actionError = "The server result does not contain the updated run.";
        }
        renderRun();
      }, function () {
        g.running = false;
        toast("The step failed. Reloading its state...");
        g.loaded = false;
        loadGuidedCurrent(renderRun);
      });
    });
  }

  function refreshDatasetsAfterInfra(stageKey, run) {
    var infra = run && run.state && run.state.stages && run.state.stages.infra;
    if (stageKey === "infra" && infra && infra.status === "done") {
      loadDatasets(null, true);
    }
  }

  /* "Done, check it": the operator already confirmed each step by ticking it, so
   * the check runs directly (read-only on the server). */
  function verifyGuidedStage() {
    var g = S.guided;
    var run = g.run || {};
    var before = run.current_stage;
    g.verifying = true;
    g.actionError = null;
    g.verifyFailed = false;
    renderRun();
    callApi("POST", "guided/verify", { confirm: true, run_id: run.run_id }).then(function (r) {
      g.verifying = false;
      if (r.data && r.data.status === "ok" && r.data.run) {
        applyGuidedRun(r.data.run);
        if (r.data.run.current_stage === before && r.data.run.status === "active") {
          g.verifyFailed = true;
        } else {
          toast("Checked: done.");
        }
      } else {
        g.actionError = guidedErrorText(r.data);
      }
      renderRun();
    });
  }

  function gatherGuidedWizardAnswers() {
    Array.prototype.forEach.call(document.querySelectorAll(".gd-wizard-answer"), function (elm) {
      S.guided.wizard.answers[elm.getAttribute("data-qid")] = elm.value;
    });
  }

  function confirmGuidedWizardDraft(withAnswers) {
    openConfirm({
      title: withAnswers ? "Redraft with your answers?" : "Draft with AI?",
      bodyHtml: "<p>The AI reads the aggregated metadata of the profile. No data row is sent to the model.</p>",
      confirmLabel: withAnswers ? "Redraft" : "Draft",
      onConfirm: function () { startGuidedWizard(withAnswers); }
    });
  }

  function startGuidedWizard(withAnswers) {
    var g = S.guided;
    var w = g.wizard;
    var run = g.run || {};
    var spec = (run.state && run.state.spec) || {};
    w.running = true;
    w.error = null;
    if (!withAnswers) { w.config = null; w.answers = {}; w.drafted = null; }
    var sent = withAnswers ? JSON.parse(JSON.stringify(w.answers)) : null;
    w.reqId += 1;
    var reqId = w.reqId;
    renderRun();
    callApi("POST", "wizard/draft", {
      confirm: true,
      profile_dataset: (spec.base_dataset || "") + "_profile",
      base_dataset: spec.base_dataset || "",
      domain: run.domain || spec.domain || "",
      answers: sent
    }).then(function (r) {
      if (reqId !== w.reqId) { return; }
      if (!r.data || r.data.status !== "ok" || !r.data.job_id) {
        w.running = false;
        w.error = guidedErrorText(r.data);
        renderRun();
        return;
      }
      w.jobId = r.data.job_id;
      pollJob(w.jobId, null, function (result) {
        if (reqId !== w.reqId) { return; }
        w.running = false;
        if (result && result.error) {
          w.error = String(result.error);
          if (!withAnswers) { w.config = null; }
        } else {
          w.config = result || {};
          w.config.questions = w.config.questions || [];
          // The new draft already integrates the answers sent: start clean from ITS
          // questions (new ids on a redraft), each pre-filled with its suggestion,
          // so nothing stale can keep the check locked.
          var drafted = {};
          w.config.questions.forEach(function (q) {
            var qid = String(q.id || "");
            drafted[qid] = (sent && sent[qid] != null) ? sent[qid] : (q.default != null ? q.default : "");
          });
          w.drafted = drafted;
          w.answers = JSON.parse(JSON.stringify(drafted));
          w.redrafted = !!withAnswers;
          toast(withAnswers ? "Draft rewritten with your answers." : "Semantic draft saved.");
        }
        renderRun();
      }, function (err) {
        if (reqId !== w.reqId) { return; }
        w.running = false;
        w.error = guidedErrorText({ error: err });
        renderRun();
      });
    });
  }

  function confirmGuidedAbandon() {
    var removal = isRemovalRun(S.guided.run);
    if (isReviewRun(S.guided.run)) {
      openConfirm({
        title: "Stop without saving?",
        bodyHtml: "<p>Nothing is changed: the expert keeps what it knows today. Your explanation is not kept.</p>",
        confirmLabel: "Stop",
        onConfirm: abandonGuidedRun
      });
      return;
    }
    openConfirm({
      title: "Abandon this run?",
      bodyHtml: "<p>The run stops. Nothing is deleted in DSS: " +
        (removal ? "what was already deleted stays deleted, everything else stays in place."
          : "the objects already created stay in place.") + "</p>",
      confirmLabel: "Abandon",
      danger: true,
      onConfirm: abandonGuidedRun
    });
  }

  function abandonGuidedRun() {
    var g = S.guided;
    var runId = g.run && g.run.run_id;
    g.abandoning = true;
    g.actionError = null;
    renderRun();
    callApi("POST", "guided/abandon", { confirm: true, run_id: runId }).then(function (r) {
      g.abandoning = false;
      if (r.data && r.data.status === "ok") {
        applyGuidedRun(null);
        toast("Run abandoned. Nothing was deleted in DSS.");
        go("overview");
        return;
      }
      g.actionError = guidedErrorText(r.data);
      renderRun();
    });
  }

  /* ---------- compatibility probe (read-only, report only) ---------- */

  function confirmProbe() {
    openConfirm({
      title: "Read what the project allows?",
      bodyHtml: "<p>Read-only look at the current project (Code Agent API, template Semantic Model Query tool, " +
        "semantic models). Nothing is created, changed or deleted.</p><p>The report is shown here; it is not saved " +
        "in the hub (only notebook 00 saves it).</p>",
      confirmLabel: "Read the project",
      onConfirm: startProbe
    });
  }

  function startProbe() {
    var p = S.guided.probe;
    p.running = true; p.error = null; p.report = null;
    renderRun();
    callApi("POST", "probe", { confirm: true }).then(function (r) {
      if (!r.data || r.data.status !== "ok" || !r.data.job_id) {
        p.running = false;
        p.error = guidedErrorText(r.data);
        renderRun();
        return;
      }
      pollJob(r.data.job_id, null, function (result) {
        p.running = false;
        p.report = (result && (result.report || result.markdown)) || "(empty report)";
        renderRun();
      }, function (err) {
        p.running = false;
        p.error = guidedErrorText({ error: err });
        renderRun();
      });
    });
  }

  /* ============================ screen: Settings ============================ */

  function promptChoices() {
    var caps = (S.overview.data || {}).capabilities || {};
    var list = [{ path: PERSONA_PATH, label: "Orchestrator personality (orchestrator_persona.md)" }];
    Object.keys(caps).forEach(function (k) {
      var c = caps[k] || {};
      if (!c.domain) { return; }
      list.push({
        path: "/python/owismind_hub/prompts/" + c.domain + "/understand_extra.md",
        label: "Extra understanding rules of the sub-agent " + (c.label_en || c.label_fr || c.domain) + " (understand_extra.md)"
      });
    });
    return list;
  }

  function renderSettings() {
    if (S.view !== "settings") { return; }
    if (!S.overview.loaded && !S.overview.loading) {
      S.overview.loading = true;
      callApi("GET", "state").then(function (r) {
        S.overview.loading = false;
        if (r.data && r.data.status === "ok") { S.overview.loaded = true; S.overview.data = r.data; }
        renderSettings();
      });
    }
    if (!S.models.loaded && !S.models.loading && !S.models.error) { loadModels(renderSettings); }
    if (!S.prompts.loaded && !S.prompts.loading && !S.prompts.loadError) { loadPrompt(); return; }

    var pr = S.prompts;
    var d = S.overview.data || {};
    var settings = d.settings || {};
    var options = promptChoices().map(function (c) {
      return '<option value="' + esc(c.path) + '"' + (c.path === pr.path ? " selected" : "") + '>' + esc(c.label) + '</option>';
    }).join("");

    setHeader({
      back: true, eyebrow: "Settings", title: "Models and prompts",
      sub: "The LLM of every mode for all agents, then the prompt files of the hub. Each agent also has its own Settings button on the overview."
    });
    var html = backendBanner() +
      '<div class="layout"><div class="layout-main">' + modelsCard() +
      '<section class="card">' +
      '<div class="afc-field"><span class="afc-field-label">File</span>' +
      '<select class="afc-select" id="prPath">' + options + '</select></div>';
    if (pr.loadError) {
      html += '<div class="afc-note afc-note--error">Cannot read: ' + esc(pr.loadError) + '</div>';
    }
    html += '<div class="afc-field"><span class="afc-field-label">Content</span>' +
      '<textarea class="afc-textarea code" id="prContent"' + (pr.loading ? " disabled" : "") + '>' +
      esc(pr.loading ? "Loading..." : pr.content) + '</textarea>' +
      '<p class="afc-field-help mono">' + esc(pr.path) + '</p></div>' +
      '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="prSave"' +
      (pr.saving || !pr.loaded ? " disabled" : "") + '>' + I.save + 'Save</button>' +
      '<button class="afc-btn afc-btn--ghost afc-btn--sm" id="prLoad"' + (pr.loading ? " disabled" : "") + '>' +
      I.refresh + 'Reload</button></div></section></div>';

    html += '<aside class="layout-aside"><section class="card tracker">' +
      '<p class="afc-mlabel">Technical settings (read-only)</p><dl class="afc-kv afc-kv--stack">' +
      '<dt>Project</dt><dd>' + esc(d.project_key || "-") + '</dd>' +
      '<dt>Hub</dt><dd>' + (d.hub_ready ? "present (/python/owismind_hub)" : "missing") + '</dd>' +
      '<dt>Orchestrator (Code Agent)</dt><dd>' + esc(settings.orchestrator_agent_id || "-") + '</dd>' +
      '<dt>SQL connection</dt><dd>' + esc(settings.sql_connection || "-") + '</dd>' +
      '<dt>Code env 3.11</dt><dd>' + esc(settings.code_env_311 || "(project default)") + '</dd>' +
      '<dt>Template semantic model</dt><dd>' + esc(settings.template_semantic_model_id || "-") + '</dd>' +
      '<dt>Template Semantic Model Query tool</dt><dd>' + esc(settings.template_semantic_tool_id || "-") + '</dd>' +
      '</dl><p class="afc-field-help">Source: factory_settings.json in the hub. Edit it from the project library.</p>' +
      '<p class="afc-mlabel tracker-sub">After saving a prompt</p>' + reloadSteps() +
      '</section></aside></div>';
    setMain(html);
    wireBack();
    wireModelsCard();
    wireSettings();
  }

  function wireSettings() {
    var pr = S.prompts;
    bindInput("prPath", function (v) {
      pr.path = v; pr.loaded = false; pr.loadError = null; pr.content = "";
      loadPrompt();
    }, true);
    bindInput("prContent", function (v) { pr.content = v; });
    if (byId("prLoad")) { byId("prLoad").onclick = function () { pr.loadError = null; loadPrompt(); }; }
    if (byId("prSave")) { byId("prSave").onclick = confirmSavePrompt; }
  }

  function loadPrompt() {
    var pr = S.prompts;
    if (!/^\/python\/owismind_hub\/prompts\//.test(pr.path)) {
      pr.loadError = "The path must start with /python/owismind_hub/prompts/";
      renderSettings(); return;
    }
    pr.loading = true; pr.loadError = null;
    renderSettings();
    callApi("GET", "hub/prompt?path=" + encodeURIComponent(pr.path)).then(function (r) {
      pr.loading = false;
      if (r.data && r.data.status === "ok") {
        pr.loaded = true;
        pr.content = r.data.content || "";
      } else {
        pr.loadError = guidedErrorText(r.data);
      }
      renderSettings();
    });
  }

  function confirmSavePrompt() {
    var pr = S.prompts;
    openConfirm({
      title: "Save the prompt?",
      bodyHtml: "<p>The file <span class=\"mono\">" + esc(pr.path) + "</span> is written to the project library " +
        "(the previous version is backed up). Reload the orchestrator afterwards so it reads it.</p>",
      confirmLabel: "Save",
      onConfirm: savePrompt
    });
  }

  function savePrompt() {
    var pr = S.prompts;
    pr.saving = true;
    renderSettings();
    callApi("POST", "hub/prompt", { confirm: true, path: pr.path, content: pr.content }).then(function (r) {
      pr.saving = false;
      if (r.data && r.data.status === "ok") {
        toast("Prompt saved.");
      } else {
        toast("Save failed.");
        pr.loadError = guidedErrorText(r.data);
      }
      renderSettings();
    });
  }

  /* ============================ models + agent settings ============================ */

  /* One central map (models.json in the hub) is the ONLY source of every LLM id; an
   * agent can override a mode for itself. Resolution: own setting > central > the agent
   * refuses to run (no built-in id). */
  var MODE_LABELS = { smart: "Smart", pro: "Pro", claude: "Claude" };
  var MODES = ["smart", "pro", "claude"];
  var ORCH_KEY = "orchestrator";
  var SOURCE_CHIP = {
    agent: '<span class="afc-chip afc-chip--manual">Own setting</span>',
    mode: '<span class="afc-chip afc-chip--on">Central</span>',
    missing: '<span class="afc-chip afc-chip--failed">Missing</span>'
  };

  /* LLM picker: a full-width <select> listing every model of the project with its
   * complete id (a datalist truncated long ids), plus the chosen id written in full
   * under it so nothing is ever cut. The current value is kept as an option even
   * when it is no longer in the project's list. With no list (API failure), a plain
   * text input takes over. */
  function llmPicker(id, value, list, emptyLabel) {
    value = value || "";
    if (!(list && list.length)) {
      return '<input class="afc-input mono" id="' + id + '" value="' + esc(value) + '" placeholder="' + esc(emptyLabel || "") + '">';
    }
    var known = false;
    var options = '<option value=""' + (value ? "" : " selected") + '>' + esc(emptyLabel || "Choose a model") + '</option>';
    list.forEach(function (m) {
      var selected = m.id === value;
      known = known || selected;
      var label = m.id + (m.name && m.name !== m.id ? "   (" + m.name + ")" : "");
      options += '<option value="' + esc(m.id) + '"' + (selected ? " selected" : "") + '>' + esc(label) + '</option>';
    });
    if (value && !known) {
      options += '<option value="' + esc(value) + '" selected>' + esc(value) + '   (not in the project list)</option>';
    }
    return '<select class="afc-select mono afc-llm-select" id="' + id + '">' + options + '</select>' +
      '<p class="afc-field-help mono afc-llm-full" id="' + id + '_full">' + (value ? esc(value) : "") + '</p>';
  }

  function bindLlmPicker(id, cb) {
    bindInput(id, function (v) {
      v = v.trim();
      var full = byId(id + "_full");
      if (full) { full.textContent = v; }
      cb(v);
    }, true);
    bindInput(id, function (v) { cb(v.trim()); });
  }

  function loadModels(cb) {
    var m = S.models;
    if (m.loading) { return; }
    m.loading = true; m.error = null;
    callApi("GET", "models").then(function (r) {
      m.loading = false;
      if (r.data && r.data.status === "ok") {
        m.loaded = true; m.data = r.data;
        m.draft = JSON.parse(JSON.stringify(r.data.models));
      } else {
        m.error = guidedErrorText(r.data);
      }
      if (cb) { cb(); }
    });
  }

  function saveModels(models, done) {
    callApi("POST", "models", { confirm: true, models: models }).then(function (r) {
      if (r.data && r.data.status === "ok") {
        toast("Models saved.");
        S.models.loaded = false;
        S.agent.loadedKey = null;
        done(true);
      } else {
        var probs = (r.data && r.data.problems) ? " " + r.data.problems.join("; ") : "";
        toast("Save refused: " + guidedErrorText(r.data) + probs);
        done(false);
      }
    });
  }

  /* ---- central models card (Settings screen) ---- */

  function modelsCard() {
    var m = S.models;
    if (m.error) { return '<section class="card"><div class="afc-note afc-note--error">Cannot read the models: ' + esc(m.error) + '</div></section>'; }
    if (!m.loaded) { return '<section class="card"><p class="afc-muted">Loading the models...</p></section>'; }
    var d = m.draft;
    var html = '<section class="card"><p class="afc-mlabel">LLM per mode (all agents)</p>' +
      '<p class="afc-field-help">The model every agent uses in each mode. An agent can override a mode in its own Settings. ' +
      'This file is the only source of the model ids: agents, native engine, factory and recipes all read it, ' +
      'and apply a change within about 30 seconds without a restart.</p>' +
      (m.data.from_file ? "" : '<div class="afc-note afc-note--error"><b>models.json is missing or invalid: every agent refuses to run until it is saved.</b>' +
        ((m.data.problems || []).length ? '<ul class="fd-list">' + m.data.problems.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join("") + '</ul>' : "") + '</div>') +
      "";
    var llms = m.data.available_llms;
    MODES.forEach(function (mode) {
      html += field(MODE_LABELS[mode], llmPicker("mdMode_" + mode, d.modes[mode], llms, "Choose a model (required)"));
    });
    html += '<p class="afc-mlabel tracker-sub">Agent factory</p>' +
      field("Factory default model", llmPicker("mdFactoryDefault", (d.factory || {}).default, llms, "Choose a model (required)"),
        "Used by the factory wizard, the Improve review and the prompt doctor.") +
      field("Wizard model (optional)", llmPicker("mdFactoryWizard", (d.factory || {}).wizard, llms, "Same as the factory default model"),
        "Empty = use the factory default model.") +
      field("Profile enrichment model", llmPicker("mdFactoryEnrich", (d.factory || {}).profile_enrich, llms, "Skip the LLM pass"),
        "LLM pass of the profile recipes (column descriptions). Empty = skip that pass.");
    var overrides = Object.keys(d.agents || {}).filter(function (k) { return Object.keys(d.agents[k] || {}).length; });
    if (overrides.length) {
      html += '<p class="afc-mlabel tracker-sub">Agents with their own setting</p><dl class="afc-kv">';
      overrides.forEach(function (k) {
        html += '<dt>' + esc(k) + '</dt><dd>' + Object.keys(d.agents[k]).map(function (mode) {
          return esc(MODE_LABELS[mode]) + ': ' + esc(d.agents[k][mode]);
        }).join("<br>") + '</dd>';
      });
      html += '</dl>';
    }
    html += '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="mdSave">' + I.save + 'Save the models</button></div></section>';
    return html;
  }

  function wireModelsCard() {
    var m = S.models;
    if (!m.loaded || !byId("mdSave")) { return; }
    m.draft.factory = m.draft.factory || {};
    MODES.forEach(function (mode) {
      bindLlmPicker("mdMode_" + mode, function (v) { m.draft.modes[mode] = v; });
    });
    bindLlmPicker("mdFactoryDefault", function (v) { m.draft.factory.default = v; });
    bindLlmPicker("mdFactoryWizard", function (v) { m.draft.factory.wizard = v; });
    bindLlmPicker("mdFactoryEnrich", function (v) { m.draft.factory.profile_enrich = v; });
    byId("mdSave").onclick = function () {
      openConfirm({
        title: "Save the central models?",
        bodyHtml: "<p>models.json is written to the hub (the previous file is backed up). " +
          "Agents, native engine, factory and recipes apply it within about 30 seconds.</p>",
        confirmLabel: "Save",
        onConfirm: function () { saveModels(m.draft, function () { loadModels(renderSettings); }); }
      });
    };
  }

  /* ---- per-agent Settings screen ---- */

  function openAgentSettings(key) {
    S.agent.key = key;
    S.agent.loadedKey = null;
    S.agent.data = null;
    S.agent.error = null;
    S.agent.draft = {};
    S.agent.ai = { running: false, error: null, instr: "", drafted: false };
    go("agent");
  }

  function loadAgent() {
    var a = S.agent;
    if (a.loading || a.loadedKey === a.key) { return; }
    a.loading = true; a.error = null;
    var pending = 2;
    function oneDone() { pending -= 1; if (pending === 0) { a.loading = false; renderAgent(); } }
    callApi("GET", "agent/settings?key=" + encodeURIComponent(a.key)).then(function (r) {
      if (r.data && r.data.status === "ok") {
        a.data = r.data.settings; a.loadedKey = a.key;
        a.draft = { models: {}, prompts: {}, description: null };
        MODES.forEach(function (mode) { a.draft.models[mode] = (a.data.own_overrides || {})[mode] || ""; });
        a.data.prompts.forEach(function (p) { a.draft.prompts[p.id] = p.content; });
        a.draft.description = a.data.routing_description;
      } else {
        a.error = guidedErrorText(r.data);
      }
      oneDone();
    });
    S.models.loaded = false;
    S.models.loading = false;
    loadModels(oneDone);
  }

  /* ---- prompt-injection findings (guardrails) ---- */
  function findingsBlock(findings, title) {
    if (!findings || !findings.length) { return ""; }
    var high = findings.some(function (f) { return f.severity === "high"; });
    return '<div class="afc-note ' + (high ? "afc-note--error" : "afc-note--warn") + '"><b>' +
      esc(title || (high ? "Suspicious content" : "Worth a look")) + '</b><ul class="fd-list">' +
      findings.slice(0, 8).map(function (f) {
        return '<li><span class="afc-chip ' + (f.severity === "high" ? "afc-chip--failed" : "afc-chip--manual") + '">' +
          esc(f.severity) + '</span> ' + esc(f.why) + (f.line ? ' (line ' + esc(f.line) + ')' : "") +
          (f.excerpt ? ': <span class="mono">' + esc(f.excerpt) + '</span>' : "") + '</li>';
      }).join("") + '</ul></div>';
  }

  function agentModelsSection(a) {
    var d = a.data;
    var html = '<section class="card"><p class="afc-mlabel">LLM used by this agent</p>' +
      '<p class="afc-field-help">One model per mode. Leave a field on the central model of that mode ' +
      '(Settings screen); pick one to give this agent its own.</p>';
    if ((d.models_problems || []).length) {
      html += '<div class="afc-note afc-note--error"><b>models.json is missing or invalid: this agent refuses to run until it is fixed in Settings.</b><ul class="fd-list">' +
        d.models_problems.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join("") + '</ul></div>';
    }
    MODES.forEach(function (mode) {
      var eff = d.models[mode] || {};
      var central = (d.central_models || {})[mode] || "";
      html += '<div class="afc-field"><span class="afc-field-label">' + esc(MODE_LABELS[mode]) + ' ' +
        (SOURCE_CHIP[eff.source] || "") + '</span>' +
        llmPicker("agMode_" + mode, a.draft.models[mode], d.available_llms,
                  central ? "Central model: " + central : "Central model (none set yet)") +
        '<p class="afc-field-help">Currently resolves to <span class="mono">' + esc(eff.llm || "nothing: the agent refuses this mode") + '</span></p></div>';
    });
    html += '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="agModelsSave">' + I.save + 'Save the LLMs</button></div></section>';
    return html;
  }

  function agentPromptSection(a, p) {
    var text = a.draft.prompts[p.id];
    var tooShort = p.min && text.trim().length < p.min;
    var ai = "";
    if (p.ai) {
      var has = text.trim().length > 0;
      ai = '<div class="afc-field"><span class="afc-field-label">Ask the AI</span>' +
        '<textarea class="afc-textarea" id="agAiInstr" spellcheck="false" placeholder="' +
        (has ? "What to fix or add (e.g. the agent confuses X with Y; add the meaning of these acronyms...)"
             : "Optional: what the AI must know (business definitions, terms users use, rules, traps...)") +
        '"' + (a.ai.running ? " disabled" : "") + '>' + esc(a.ai.instr) + '</textarea>' +
        '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="agAiGo"' + (a.ai.running ? " disabled" : "") + '>' +
        I.play + (a.ai.running ? "Writing... (up to 2 minutes)" : (has ? "Improve with AI" : "Write with AI")) + '</button></div>' +
        (a.ai.error ? '<div class="afc-note afc-note--error">' + esc(a.ai.error) + '</div>' : "") +
        (a.ai.drafted ? '<div class="afc-note afc-note--warn">AI draft: read it, correct it, then click Save. Nothing is saved yet.</div>' : "") +
        '<p class="afc-field-help">The AI sees the dataset profile, the semantic model, the column descriptions and a few masked sample rows. ' +
        'It is told not to invent anything: unknown points are marked TO CONFIRM for you to fill in.</p></div>';
    }
    return '<section class="card"><p class="afc-mlabel">' + esc(p.label) + '</p>' +
      '<p class="afc-field-help">' + esc(p.help) + '</p>' + ai +
      findingsBlock(p.findings, "Flagged in the saved text") +
      (p.ai && a.ai.warnings && a.ai.warnings.length ? findingsBlock(a.ai.warnings, "Flagged in the AI draft: read it with care") : "") +
      (p.is_draft ? '<div class="afc-note afc-note--warn"><b>Unreviewed AI draft, NOT active yet.</b> The factory AI wrote it at creation from the dataset. Read it, correct it, then click Save to make it live.</div>' : "") +
      (p.exists || p.is_draft ? "" : '<div class="afc-note afc-note--warn">This file is not in the hub: the agent uses its built-in text. ' +
        'Saving creates the file and it then replaces the built-in text.</div>') +
      '<textarea class="afc-textarea code" id="agPrompt_' + esc(p.id) + '" spellcheck="false">' + esc(text) + '</textarea>' +
      (p.ai && a.ai.drafted && p.content && p.content !== text
        ? detailsBlock("agdiff_" + p.id, "What changed compared with the saved version",
            (function () {
              var d = wordDiff(p.content, text);
              return d === null ? '<p class="afc-muted">Too long to compare word by word.</p>'
                                : '<p class="afc-field-help">Struck words are removed, highlighted words are added. Edit the text above to change anything.</p><div class="rv-diff">' + d + '</div>';
            })(), true)
        : "") +
      '<p class="afc-field-help mono">' + esc(p.path) + ' &middot; <span id="agCount_' + esc(p.id) + '">' + text.length + '</span> / ' + p.max + ' characters' +
      (p.min ? ' (min ' + p.min + ')' : "") + '</p>' +
      '<div class="afc-actions"><button class="afc-btn afc-btn--primary" data-ag-prompt="' + esc(p.id) + '"' +
      (tooShort ? " disabled" : "") + '>' + I.save + 'Save this prompt</button></div></section>';
  }

  function agentDescriptionSection(a) {
    var lim = a.data.description_limits;
    return '<section class="card"><p class="afc-mlabel">Routing description</p>' +
      '<p class="afc-field-help">What the orchestrator reads to decide when to send a question to this sub-agent. ' +
      'Describe the domain precisely: it is the routing rule.</p>' +
      '<textarea class="afc-textarea" id="agDescription" spellcheck="false">' + esc(a.draft.description || "") + '</textarea>' +
      '<p class="afc-field-help">' + lim.min + ' to ' + lim.max + ' characters.</p>' +
      '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="agDescSave">' + I.save + 'Save the description</button></div></section>';
  }

  function agentToolsSection(a) {
    var html = '<section class="card"><p class="afc-mlabel">Tools</p><dl class="afc-kv">';
    a.data.tools.forEach(function (t) {
      var extra = "";
      if (t.kind === "semantic tool") {
        extra = '<br>LLM of this tool: <span class="mono">' + esc(t.llm || "not readable here, see the tool in DSS") + '</span>' +
          (t.id ? ' (tool ' + esc(t.id) + ')' : "");
      } else if (t.kind === "sub-agent") {
        extra = '<br>' + (t.enabled ? "Enabled" : "Disabled") + ' (capability ' + esc(t.capability) + ')';
      }
      var role = t.kind === "sub-agent" ? (String(t.role).length > 160 ? String(t.role).slice(0, 160) + "..." : t.role) : t.role;
      html += '<dt>' + esc(t.name) + '</dt><dd>' + esc(t.kind) + ' - ' + esc(role) + extra + '</dd>';
    });
    return html + '</dl><p class="afc-field-help">Read-only. The tools are part of the agent code; the LLM of a Semantic Model Query tool is set on the tool in DSS.</p></section>';
  }

  function renderAgent() {
    if (S.view !== "agent") { return; }
    var a = S.agent;
    if (!a.loadedKey && !a.loading && !a.error) { loadAgent(); }
    setHeader({ back: true, eyebrow: "Agent settings", title: (a.data && a.data.label) || "Loading...",
      sub: a.data ? 'Code Agent ' + mono(a.data.agent_id || "-") + ' &middot; everything this agent is configured with, in one place.' : "" });
    if (a.error) {
      setMain(backendBanner() + '<div class="afc-note afc-note--error">Cannot read the settings (' + esc(a.error) + ').</div>');
      return;
    }
    if (!a.data || !S.models.loaded) { setMain(backendBanner() + '<p class="afc-muted afc-pad">Loading...</p>'); return; }
    var html = backendBanner();
    if (a.notice) {
      html += '<div class="nextstep nextstep--top"><p class="afc-mlabel">' + esc(a.notice) + ' Last step: restart the agent</p>' +
        '<ol class="howto howto--strong"><li>In DSS, open <b>Agents &amp; GenAI Models</b> &gt; <b>Agents</b> &gt; ' +
        copyable(a.key === ORCH_KEY ? ORCHESTRATOR_NAME : (a.data.label || a.key)) + '.</li>' +
        '<li>Click <b>Save</b> (no edit needed): the agent restarts and reads the new settings.</li>' +
        '<li>Start a <b>new conversation</b> in the OWIsMind webapp.</li></ol></div>';
      a.notice = null;
    }
    html += agentModelsSection(a);
    a.data.prompts.forEach(function (p) { html += agentPromptSection(a, p); });
    if (a.data.routing_description != null) { html += agentDescriptionSection(a); }
    html += agentToolsSection(a);
    setMain(html);
    wireAgent();
  }

  function wireAgent() {
    var a = S.agent;
    MODES.forEach(function (mode) {
      bindLlmPicker("agMode_" + mode, function (v) { a.draft.models[mode] = v; });
    });
    if (byId("agModelsSave")) { byId("agModelsSave").onclick = confirmAgentModels; }
    Array.prototype.forEach.call(document.querySelectorAll("[data-ag-prompt]"), function (btn) {
      var id = btn.getAttribute("data-ag-prompt");
      bindInput("agPrompt_" + id, function (v) {
        a.draft.prompts[id] = v;
        var spec = a.data.prompts.filter(function (p) { return p.id === id; })[0];
        if (byId("agCount_" + id)) { byId("agCount_" + id).textContent = v.length; }
        btn.disabled = !!(spec && spec.min && v.trim().length < spec.min);
      });
      btn.onclick = function () { confirmAgentPrompt(id); };
    });
    bindInput("agAiInstr", function (v) { a.ai.instr = v; });
    if (byId("agAiGo")) { byId("agAiGo").onclick = confirmAgentAi; }
    bindInput("agDescription", function (v) { a.draft.description = v; });
    if (byId("agDescSave")) { byId("agDescSave").onclick = confirmAgentDescription; }
  }

  function confirmAgentAi() {
    var a = S.agent;
    openConfirm({
      title: "Write the business prompt with the AI?",
      bodyHtml: "<p>The factory AI reads the dataset profile, the semantic model, the column descriptions and a few " +
        "<b>masked sample rows</b>, then writes the prompt. It takes up to 2 minutes. " +
        "The result is only a <b>draft in the box below</b>: nothing is saved until you click Save.</p>",
      confirmLabel: "Write it",
      onConfirm: runAgentAi
    });
  }

  function runAgentAi() {
    var a = S.agent;
    var current = a.draft.prompts.business_prompt || "";
    a.ai.running = true; a.ai.error = null;
    renderAgent();
    callApi("POST", "agent/prompt-draft", {
      confirm: true, capability_key: a.key, current: current, instructions: a.ai.instr
    }).then(function (r) {
      if (!r.data || r.data.status !== "ok" || !r.data.job_id) {
        a.ai.running = false; a.ai.error = guidedErrorText(r.data);
        renderAgent();
        return;
      }
      pollJob(r.data.job_id, null, function (result) {
        a.ai.running = false;
        if (result && result.prompt) {
          a.draft.prompts.business_prompt = result.prompt;
          a.ai.drafted = true;
          a.ai.warnings = result.warnings || [];
        } else {
          a.ai.error = (result && result.error) || "The AI returned nothing.";
        }
        renderAgent();
      }, function (code) {
        a.ai.running = false; a.ai.error = "The AI job failed (" + code + ").";
        renderAgent();
      });
    });
  }

  function confirmAgentModels() {
    var a = S.agent;
    openConfirm({
      title: "Save the LLMs of this agent?",
      bodyHtml: "<p>Only the filled fields become this agent's own setting; empty fields follow the central model. " +
        "models.json is written to the hub (previous file backed up).</p>",
      confirmLabel: "Save",
      onConfirm: function () {
        // Start from the stored file so other agents' overrides are never lost.
        var models = JSON.parse(JSON.stringify(S.models.data.models));
        models.agents = models.agents || {};
        var own = {};
        MODES.forEach(function (mode) { if (a.draft.models[mode]) { own[mode] = a.draft.models[mode]; } });
        if (Object.keys(own).length) { models.agents[a.data.model_key] = own; }
        else { delete models.agents[a.data.model_key]; }
        saveModels(models, function (ok) {
          if (ok) { a.notice = "LLMs saved."; }
          renderAgent();
        });
      }
    });
  }

  function confirmAgentPrompt(id) {
    var a = S.agent;
    var spec = a.data.prompts.filter(function (p) { return p.id === id; })[0];
    callApi("POST", "guardrails/scan", { text: a.draft.prompts[id] }).then(function (r) {
      var findings = (r.data && r.data.findings) || [];
      var high = !!(r.data && r.data.high);
      openConfirm({
        title: high ? "Suspicious content: save anyway?" : "Save this prompt?",
        danger: high,
        bodyHtml: (findings.length ? findingsBlock(findings) : "") +
          (high ? "<p>This text contains instructions that look like a prompt injection. " +
            "Read it again. Save it only if you wrote it on purpose.</p>" : "") +
          "<p>The file <span class=\"mono\">" + esc(spec.path) + "</span> is written to the project library " +
          "(the previous version is backed up).</p>",
        confirmLabel: high ? "I read it, save anyway" : "Save",
        onConfirm: function () { savePromptNow(spec, id, high); }
      });
    });
  }

  function savePromptNow(spec, id, acknowledge) {
    var a = S.agent;
    callApi("POST", "hub/prompt", { confirm: true, path: spec.path, content: a.draft.prompts[id],
                                    acknowledge_risks: !!acknowledge }).then(function (r) {
      if (r.data && r.data.status === "ok") {
        toast("Prompt saved.");
        a.notice = "Prompt saved.";
        a.ai.drafted = false;
        a.ai.warnings = [];
        a.loadedKey = null;
        renderAgent();
      } else {
        toast("Save refused: " + guidedErrorText(r.data));
      }
    });
  }

  function confirmAgentDescription() {
    var a = S.agent;
    openConfirm({
      title: "Save the routing description?",
      bodyHtml: "<p>capabilities.json is updated (the previous file is backed up). The orchestrator reads it when it starts.</p>",
      confirmLabel: "Save",
      onConfirm: function () { saveDescription(false); }
    });
  }

  function saveDescription(ack) {
    var a = S.agent;
    callApi("POST", "capability/description", { confirm: true, capability_key: a.key, description: a.draft.description,
                                                acknowledge_risks: !!ack }).then(function (r) {
      if (r.data && r.data.error === "suspicious_content" && !ack) {
        openConfirm({ title: "Suspicious content: save anyway?", danger: true,
          bodyHtml: findingsBlock(r.data.findings) + "<p>The orchestrator reads this text on every question. Save it only if you wrote it on purpose.</p>",
          confirmLabel: "I read it, save anyway", onConfirm: function () { saveDescription(true); } });
        return;
      }
      if (r.data && r.data.status === "ok") {
        a.notice = "Description saved.";
        a.loadedKey = null;
        S.overview.loaded = false;
        renderAgent();
      } else {
        toast("Save refused: " + guidedErrorText(r.data));
      }
    });
  }

  /* ============================ small builders ============================ */

  function inputEl(id, value, ph) {
    return '<input class="afc-input" id="' + id + '" value="' + esc(value) + '" placeholder="' + esc(ph || "") + '">';
  }
  function field(label, controlHtml, help) {
    return '<div class="afc-field"><span class="afc-field-label">' + esc(label) + '</span>' + controlHtml +
      (help ? '<p class="afc-field-help">' + esc(help) + '</p>' : "") + '</div>';
  }
  function bindInput(id, cb, isChange) {
    var e = byId(id);
    if (!e) { return; }
    if (isChange) { e.onchange = function () { cb(this.value); }; }
    else { e.oninput = function () { cb(this.value); }; }
  }

  /* ============================ navigation + theme + boot ============================ */

  function go(view) {
    S.view = view;
    var nav = byId("afcNav");
    if (nav) {
      Array.prototype.forEach.call(nav.querySelectorAll("[data-view]"), function (b) {
        b.classList.toggle("on", b.getAttribute("data-view") === view);
      });
    }
    if (view === "overview") {
      loadOverview();
    } else if (view === "run") {
      if (!S.guided.loaded) { loadGuidedCurrent(renderRun); }
      renderRun();
    } else if (view === "settings") {
      renderSettings();
    } else if (view === "agent") {
      renderAgent();
    }
    window.scrollTo(0, 0);
  }

  function applyTheme() {
    var root = byId("afc");
    if (root) { root.setAttribute("data-theme", S.theme); }
  }
  function toggleTheme() {
    S.theme = (S.theme === "light") ? "dark" : "light";
    applyTheme();
    try { window.localStorage.setItem("afc.theme", S.theme); } catch (e) { /* ignore */ }
  }

  function boot() {
    try {
      var saved = window.localStorage.getItem("afc.theme");
      if (saved === "dark" || saved === "light") { S.theme = saved; }
    } catch (e) { /* ignore */ }

    var root = byId("afc");
    var shell = byId("afc-shell");
    if (!root || !shell) { return; }
    root.innerHTML = "";
    root.appendChild(shell.content.cloneNode(true));
    applyTheme();

    byId("afcTheme").onclick = toggleTheme;
    byId("afcBack").onclick = function () { go("overview"); };
    Array.prototype.forEach.call(byId("afcNav").querySelectorAll("[data-view]"), function (b) {
      b.onclick = function () { go(b.getAttribute("data-view")); };
    });
    var scrim = byId("afcModalScrim");
    if (scrim) { scrim.onclick = function (ev) { if (ev.target === scrim) { closeModal(); } }; }
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") { closeModal(); }
    });

    go("overview");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
