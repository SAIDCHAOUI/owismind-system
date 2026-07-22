/* OWIsMind - Agent Factory Console (framework-free vanilla JS, no build, no CDN).
 *
 * Admin design-time webapp that drives the "agent factory": it plans and runs the
 * creation of a new dataset-specialist sub-agent chain in the DSS project, and edits
 * the Config & Prompt Hub. It is SEPARATE from the public OWIsMind Vue plugin webapp.
 *
 * Safety model (mirrors the backend contract):
 *   - Read screens (state / datasets / capabilities / prompt) are plain GETs.
 *   - Every mutating call carries {confirm: true} and is gated behind a confirm modal.
 *   - "Planifier" is a dry-run (nothing touches DSS); "Executer" runs for real.
 *   - No deletion feature of any kind.
 *
 * Long backend actions (probe / execute / wizard draft) run as background JOBS: the
 * POST returns a job_id, then we poll GET api/job/<id> until status is done or error.
 * The shell in body.html (<template id="afc-shell">) is cloned once into #afc; each
 * screen renders into #afcMain. French-only UI. Orange charter styling in style.css. */

(function () {
  "use strict";

  /* ============================ icons ============================ */

  var I = {
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M5 12l5 5 9-10"/></svg>',
    play: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 5l12 7-12 7z"/></svg>',
    copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="11" height="11"/><path d="M5 15V5h10"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4v6h6M20 20v-6h-6"/><path d="M20 10a8 8 0 0 0-14-4M4 14a8 8 0 0 0 14 4"/></svg>',
    save: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 4h11l3 3v13H5zM8 4v5h7M8 20v-6h8v6"/></svg>',
    plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>'
  };

  /* ============================ state ============================ */

  var S = {
    tab: "guided",
    theme: "light",
    // Guided assistant screen (server-persisted run)
    guided: {
      loaded: false, loading: false, error: null, run: null,
      starting: false, startError: null, startErrorCode: null, running: false, verifying: false,
      abandoning: false, actionError: null, liveActions: [],
      form: { domain: "", base_dataset: "", label_fr: "", label_en: "", lookup: "" },
      wizard: { running: false, jobId: null, config: null, answers: {}, error: null, reqId: 0 }
    },
    // Overview screen ("Vue d'ensemble")
    overview: { loaded: false, loading: false, error: null, data: null },
    // shared: datasets list (fed to the pickers)
    datasets: { loaded: false, loading: false, error: null, list: [] },
    // Probe screen ("Sonde", Phase 0)
    probe: { running: false, jobId: null, report: null, error: null },
    // New-domain screen ("Nouveau domaine")
    domain: {
      form: { domain: "", sourceMode: "existing", base_dataset: "",
              connection: "SQL_owi", schema: "", table: "", catalog: "",
              label_fr: "", label_en: "", lookup: "" },
      planning: false, plan: null, planError: null,
      executing: false, execJobId: null, execActions: [], execResult: null, execError: null,
      wizard: { profileDataset: "", running: false, jobId: null, config: null,
                answers: {}, error: null, regenerating: false }
    },
    // Prompts screen (hub editor)
    prompts: {
      path: "/python/owismind_hub/prompts/orchestrator_persona.md",
      loading: false, loaded: false, content: "", saving: false, loadError: null,
      caps: { loading: false, loaded: false, text: "", saving: false, problems: [], loadError: null }
    }
  };

  /* ============================ dom helpers ============================ */

  function byId(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function setMain(html) { var m = byId("afcMain"); if (m) { m.innerHTML = html; } }

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
          transientFails = 0; // a real answer clears the transient streak
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
        // Transient transport failure: retry a few times with growing backoff
        // (2s, 4s, 8s, capped) before declaring the job lost, so one flaky poll
        // does not abort a job that is still running for real.
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
    byId("afcModalTitle").textContent = opts.title || "Confirmer";
    byId("afcModalBody").innerHTML = opts.bodyHtml || "";
    var foot = byId("afcModalFoot");
    var confirmCls = opts.danger ? "afc-btn afc-btn--danger" : "afc-btn afc-btn--primary";
    foot.innerHTML =
      '<button class="afc-btn afc-btn--ghost afc-btn--sm" id="afcModalCancel">Annuler</button>' +
      '<button class="' + confirmCls + '" id="afcModalOk">' + esc(opts.confirmLabel || "Confirmer") + '</button>';
    scrim.classList.add("on");
    scrim.setAttribute("aria-hidden", "false");
    byId("afcModalCancel").onclick = closeModal;
    byId("afcModalOk").onclick = function () {
      closeModal();
      if (opts.onConfirm) { opts.onConfirm(); }
    };
  }
  function closeModal() {
    var scrim = byId("afcModalScrim");
    scrim.classList.remove("on");
    scrim.setAttribute("aria-hidden", "true");
  }

  /* ============================ shared render bits ============================ */

  function statusChip(status) {
    var map = {
      PLANNED: { cls: "planned", txt: "PLANIFIÉ" },
      DONE: { cls: "done", txt: "FAIT" },
      SKIPPED: { cls: "skipped", txt: "IGNORÉ" },
      FAILED: { cls: "failed", txt: "ÉCHEC" },
      MANUAL: { cls: "manual", txt: "MANUEL" },
      BLOCKED: { cls: "blocked", txt: "BLOQUÉ" }
    };
    var m = map[status] || { cls: "planned", txt: String(status || "") };
    return '<span class="afc-chip afc-chip--' + m.cls + '">' + esc(m.txt) + '</span>';
  }

  function actionsTable(actions) {
    if (!actions || !actions.length) {
      return '<p class="afc-loading">Aucune action pour le moment.</p>';
    }
    var rows = actions.map(function (a) {
      return '<tr>' +
        '<td class="col-status">' + statusChip(a.status) + '</td>' +
        '<td class="col-step"><span class="afc-cell-step">' + esc(a.step) + '</span></td>' +
        '<td class="afc-cell-detail">' + esc(a.detail || "") + '</td>' +
        '</tr>';
    }).join("");
    return '<div class="afc-table-wrap"><table class="afc-table">' +
      '<thead><tr><th class="col-status">Statut</th><th class="col-step">Étape</th><th>Détail</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table></div>';
  }

  function manualChecklist(actions) {
    var manuals = (actions || []).filter(function (a) { return a.status === "MANUAL"; });
    if (!manuals.length) { return ""; }
    var items = manuals.map(function (a) {
      return '<li><span class="step">' + esc(a.step) + '</span> : ' + esc(a.detail || "") + '</li>';
    }).join("");
    return '<div class="afc-manual"><h4>Étapes manuelles restantes (' + manuals.length + ')</h4>' +
      '<ol>' + items + '</ol></div>';
  }

  function copyButton(id, label) {
    return '<button class="afc-btn afc-btn--ghost afc-btn--sm" id="' + id + '">' + I.copy + (label || "Copier") + '</button>';
  }
  function wireCopy(id, getText) {
    var b = byId(id);
    if (!b) { return; }
    b.onclick = function () {
      var text = getText();
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(
          function () { toast("Copié dans le presse-papiers."); },
          function () { toast("Copie impossible."); }
        );
      } else {
        toast("Copie non supportée par le navigateur.");
      }
    };
  }

  function backendBanner() {
    if (hasBackend()) { return ""; }
    return '<div class="afc-note afc-note--warn">Backend indisponible : cette page est ouverte hors du contexte DSS. ' +
      'Les appels au moteur d\'usine ne fonctionneront qu\'une fois la webapp déployée dans DSS.</div>';
  }

  /* ============================ datasets (shared picker source) ============================ */

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
    var opts = ['<option value="">- Choisir un dataset -</option>'];
    S.datasets.list.forEach(function (d) {
      var sel = d.name === selected ? " selected" : "";
      opts.push('<option value="' + esc(d.name) + '"' + sel + '>' + esc(d.name) + '</option>');
    });
    return opts.join("");
  }

  /* ============================ screen: Assistant ============================ */

  function guidedErrorText(data) {
    var map = {
      confirmation_required: "La confirmation est requise.",
      invalid_spec: "Les informations du domaine sont invalides.",
      active_run_exists: "Un assistant est déjà en cours.",
      busy: "Une opération de l'usine est déjà en cours. Réessayez dans un instant.",
      server_error: "Le serveur n'a pas pu terminer l'opération.",
      unknown_run: "Ce run est introuvable.",
      run_not_active: "Ce run n'est plus actif.",
      stage_not_runnable: "Cette étape ne peut pas être lancée dans son état actuel.",
      stage_not_verifiable: "Cette étape ne peut pas être vérifiée dans son état actuel.",
      too_many_jobs: "Trop de tâches sont enregistrées côté serveur. Réessayez plus tard.",
      storage_not_configured: "Le stockage SQL de l'assistant n'est pas configuré.",
      network_error: "La connexion au backend a échoué.",
      no_backend: "Le backend DSS est indisponible.",
      poll_failed: "Le suivi de la tâche a échoué après plusieurs tentatives.",
      job_error: "La tâche serveur a échoué."
    };
    if (data && data.messages && data.messages.length) { return data.messages.join(" ; "); }
    return map[data && data.error] || (data && data.error) || "erreur inconnue";
  }

  function resetGuidedWizard() {
    S.guided.wizard = { running: false, jobId: null, config: null,
                        answers: {}, error: null, reqId: 0 };
  }

  function applyGuidedRun(run) {
    var previousId = S.guided.run && S.guided.run.run_id;
    S.guided.run = run || null;
    S.guided.liveActions = [];
    S.guided.actionError = null;
    if (!run || run.run_id !== previousId) { resetGuidedWizard(); }
  }

  function loadGuidedCurrent() {
    var g = S.guided;
    if (g.loading) { return; }
    g.loading = true;
    g.error = null;
    renderGuided();
    callApi("GET", "guided/current").then(function (r) {
      g.loading = false;
      if (r.data && r.data.status === "ok") {
        g.loaded = true;
        g.startError = null;
        g.startErrorCode = null;
        applyGuidedRun(r.data.run && r.data.run.status !== "abandoned" ? r.data.run : null);
      } else {
        g.error = guidedErrorText(r.data);
      }
      renderGuided();
    });
  }

  function refreshGuidedCurrent() {
    S.guided.loaded = false;
    loadGuidedCurrent();
  }

  function guidedStageChip(status) {
    var map = {
      pending: { cls: "pending", txt: "A venir" },
      ready: { cls: "ready", txt: "Prête" },
      running: { cls: "running", txt: "En cours" },
      waiting_user: { cls: "waiting", txt: "Action requise" },
      done: { cls: "done", txt: "Faite" },
      failed: { cls: "failed", txt: "Échec" }
    };
    var m = map[status] || map.pending;
    return '<span class="afc-chip gd-status gd-status--' + m.cls + '">' + esc(m.txt) + '</span>';
  }

  function renderGuided() {
    if (S.tab !== "guided") { return; }
    var g = S.guided;
    var html = '<div class="afc-panel gd-panel">' + backendBanner() +
      '<div class="afc-sec">' +
      '<p class="afc-sec-eyebrow">Création guidée</p>' +
      '<h2 class="afc-sec-title">Assistant de nouveau domaine</h2>' +
      '<p class="afc-sec-note">Suivez chaque étape jusqu\'à l\'activation du nouvel expert dans l\'orchestrateur. ' +
      'L\'avancement est conservé côté serveur et reprend après un rechargement de la page.</p></div>';

    if (g.loading && !g.loaded) {
      html += '<p class="afc-loading">Recherche d\'un run en cours...</p></div>';
      setMain(html);
      return;
    }
    if (g.error && !g.loaded) {
      html += '<div class="afc-note afc-note--error">Impossible de charger l\'assistant : ' + esc(g.error) + '</div>' +
        '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="gdRetry">' +
        I.refresh + 'Réessayer</button></div></div>';
      setMain(html);
      if (byId("gdRetry")) { byId("gdRetry").onclick = refreshGuidedCurrent; }
      return;
    }

    if (!g.run) {
      if (!S.datasets.loaded && !S.datasets.loading) {
        loadDatasets(function () { if (S.tab === "guided") { renderGuided(); } });
      }
      html += renderGuidedStartForm();
      html += '</div>';
      setMain(html);
      wireGuidedStartForm();
      return;
    }

    if (g.run.status === "done") {
      html += renderGuidedSuccess(g.run) + '</div>';
      setMain(html);
      if (byId("gdNew")) { byId("gdNew").onclick = newGuidedDomain; }
      return;
    }

    html += renderGuidedStepper(g.run);
    html += renderGuidedStage(g.run);
    var currentStage = g.run.state && g.run.state.stages && g.run.state.stages[g.run.current_stage];
    var abandonDisabled = g.abandoning || g.running || g.verifying || g.wizard.running ||
      (currentStage && currentStage.status === "running");
    html += '<div class="gd-abandon"><button class="afc-btn afc-btn--danger afc-btn--sm" id="gdAbandon"' +
      (abandonDisabled ? " disabled" : "") + '>Abandonner ce run</button></div>';
    html += '</div>';
    setMain(html);
    wireGuidedRun();
  }

  function renderGuidedStartForm() {
    var g = S.guided;
    var f = g.form;
    var picker = S.datasets.loading
      ? '<p class="afc-loading gd-dataset-loading">Chargement des datasets...</p>'
      : '<select class="afc-select" id="gdBaseDataset">' + datasetOptions(f.base_dataset) + '</select>';
    var html = '<div class="afc-card gd-start">' +
      field("Clé de domaine (snake_case)", inputEl("gdDomain", f.domain, "ex. opportunities"),
        "Minuscules, chiffres et underscores.") +
      '<div class="gd-dataset-row"><div class="gd-dataset-field">' +
      field("Dataset de base", picker, "Le dataset dont le nouvel expert sera spécialiste.") +
      '</div><button class="afc-btn afc-btn--ghost afc-btn--sm" id="gdRefreshDatasets"' +
      (S.datasets.loading ? " disabled" : "") + '>' + I.refresh + 'Rafraîchir la liste</button></div>' +
      '<div class="afc-grid-2">' +
      fieldRaw("Libellé FR", inputEl("gdLabelFr", f.label_fr, "ex. Opportunités commerciales")) +
      fieldRaw("Libellé EN", inputEl("gdLabelEn", f.label_en, "ex. Sales opportunities")) +
      '</div>' +
      field("Colonnes lookup (séparées par des virgules)",
        inputEl("gdLookup", f.lookup, "ex. Account_name, Opportunity_name"),
        "Laissez vide pour utiliser toutes les colonnes texte autorisées.") +
      '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="gdStart"' +
      (g.starting ? " disabled" : "") + '>' + I.play +
      (g.starting ? "Démarrage..." : "Démarrer l'assistant") + '</button></div>';

    if (S.datasets.error) {
      html += '<div class="afc-note afc-note--error">Liste des datasets indisponible : ' + esc(S.datasets.error) + '</div>';
    }
    if (g.startError) {
      html += '<div class="afc-note afc-note--error">Démarrage impossible : ' + esc(g.startError) + '</div>';
      if (g.startErrorCode === "active_run_exists") {
        html += '<div class="afc-actions"><button class="afc-btn afc-btn--ghost" id="gdResume">' +
          I.refresh + 'Reprendre le run en cours</button></div>';
      }
    }
    html += '</div>';
    return html;
  }

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

  function wireGuidedStartForm() {
    var f = S.guided.form;
    bindInput("gdDomain", function (v) { f.domain = v; });
    bindInput("gdBaseDataset", function (v) { f.base_dataset = v; }, true);
    bindInput("gdLabelFr", function (v) { f.label_fr = v; });
    bindInput("gdLabelEn", function (v) { f.label_en = v; });
    bindInput("gdLookup", function (v) { f.lookup = v; });
    if (byId("gdRefreshDatasets")) {
      byId("gdRefreshDatasets").onclick = function () {
        loadDatasets(function () { renderGuided(); }, true);
        renderGuided();
      };
    }
    if (byId("gdStart")) { byId("gdStart").onclick = confirmGuidedStart; }
    if (byId("gdResume")) { byId("gdResume").onclick = refreshGuidedCurrent; }
  }

  function confirmGuidedStart() {
    var spec = guidedStartSpec();
    openConfirm({
      title: "Démarrer l'assistant ?",
      bodyHtml: "Un run guidé persistant sera créé pour le domaine <b class=\"mono\">" +
        esc(spec.domain || "(sans nom)") + "</b> et le dataset <b class=\"mono\">" +
        esc(spec.base_dataset || "(non choisi)") + "</b>.",
      confirmLabel: "Démarrer",
      onConfirm: startGuided
    });
  }

  function startGuided() {
    var g = S.guided;
    g.starting = true;
    g.startError = null;
    g.startErrorCode = null;
    renderGuided();
    callApi("POST", "guided/start", { confirm: true, spec: guidedStartSpec() }).then(function (r) {
      g.starting = false;
      if (r.data && r.data.status === "ok" && r.data.run) {
        applyGuidedRun(r.data.run);
        toast("Assistant démarré.");
      } else {
        g.startErrorCode = r.data && r.data.error;
        g.startError = guidedErrorText(r.data);
      }
      renderGuided();
    });
  }

  function renderGuidedStepper(run) {
    var state = run.state || {};
    var stages = state.stages || {};
    var order = state.stage_order || [];
    var rows = order.map(function (key, index) {
      var stage = stages[key] || {};
      var status = key === run.current_stage && S.guided.running ? "running" : stage.status;
      var current = key === run.current_stage ? " gd-step--current" : "";
      return '<li class="gd-step' + current + '">' +
        '<span class="gd-step-number">' + esc(index + 1) + '</span>' +
        '<span class="gd-step-title">' + esc(stage.title_fr || key) + '</span>' +
        guidedStageChip(status) + '</li>';
    }).join("");
    return '<div class="afc-sec gd-run-head"><div>' +
      '<p class="afc-mlabel">Run actif</p><p class="gd-run-domain mono">' + esc(run.domain || "-") + '</p>' +
      '</div><span class="gd-run-id mono">' + esc(run.run_id || "") + '</span></div>' +
      '<ol class="gd-stepper">' + rows + '</ol>';
  }

  function renderGuidedProblems(problems) {
    if (!problems || !problems.length) { return ""; }
    return '<div class="afc-note afc-note--error gd-problems"><b>Points à corriger :</b><ul>' +
      problems.map(function (problem) { return '<li>' + esc(problem) + '</li>'; }).join("") + '</ul></div>';
  }

  function renderGuidedStage(run) {
    var g = S.guided;
    var state = run.state || {};
    var stages = state.stages || {};
    var stage = stages[run.current_stage] || null;
    if (!stage) {
      return '<div class="afc-note afc-note--error">L\'étape courante est absente du run.</div>';
    }
    var status = g.running ? "running" : stage.status;
    var html = '<section class="afc-card gd-current"><p class="afc-sec-eyebrow">Étape courante</p>' +
      '<div class="gd-current-title"><h3>' + esc(stage.title_fr || run.current_stage) + '</h3>' +
      guidedStageChip(status) + '</div>';
    if (stage.detail_fr) { html += '<p class="gd-detail">' + esc(stage.detail_fr).replace(/\n/g, "<br>") + '</p>'; }
    if (g.actionError) {
      html += '<div class="afc-note afc-note--error">Opération impossible : ' + esc(g.actionError) + '</div>';
    }

    if (status === "ready" || status === "failed") {
      html += renderGuidedProblems(stage.problems) + '<div class="afc-actions">' +
        '<button class="afc-btn afc-btn--primary" id="gdRunStage"' + (g.running ? " disabled" : "") + '>' +
        I.play + (status === "failed" ? "Relancer" : "Lancer cette étape") + '</button></div>';
    } else if (status === "waiting_user") {
      if (stage.instructions_fr) {
        html += '<div class="gd-instructions">' + esc(stage.instructions_fr).replace(/\n/g, "<br>") + '</div>';
      }
      html += renderGuidedProblems(stage.problems);
      if (run.current_stage === "wizard") { html += renderGuidedWizard(run); }
      html += '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="gdVerify"' +
        (g.verifying || g.wizard.running ? " disabled" : "") + '>' + I.check +
        (g.verifying ? "Vérification..." : "C'est fait, vérifier") + '</button></div>';
    } else if (status === "running") {
      html += '<div class="afc-note afc-note--info">Étape en cours d\'exécution côté serveur...</div>';
      if (!g.running) {
        html += '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="gdRefreshRun">' +
          I.refresh + 'Rafraîchir</button></div>';
      }
    } else if (status === "pending") {
      html += '<div class="afc-note afc-note--info">Cette étape attend la fin de l\'étape courante.</div>';
    }

    var journal = (g.running && g.liveActions.length) ? g.liveActions : (stage.journal || []);
    if (journal.length) {
      html += '<div class="gd-journal"><p class="afc-mlabel">Journal de l\'étape</p>' + actionsTable(journal) + '</div>';
    }
    html += '</section>';
    return html;
  }

  function renderGuidedWizard(run) {
    var w = S.guided.wizard;
    var spec = (run.state && run.state.spec) || {};
    var profile = (spec.base_dataset || "") + "_profile";
    var html = '<div class="gd-wizard"><p class="afc-mlabel">Wizard sémantique</p>' +
      '<p class="gd-detail">Le brouillon utilise le profil <span class="mono">' + esc(profile) + '</span>. ' +
      'Il est enregistré automatiquement dans le hub.</p>';
    if (w.running) {
      html += '<div class="afc-note afc-note--info">Rédaction du brouillon en cours...</div>';
    } else if (!w.config) {
      html += '<div class="afc-actions"><button class="afc-btn afc-btn--ghost" id="gdWizardDraft">' +
        'Rédiger le brouillon (IA)</button></div>';
    }
    if (w.error) {
      html += '<div class="afc-note afc-note--error">Brouillon impossible : ' + esc(w.error) + '</div>';
    }
    if (w.config) {
      var questions = w.config.questions || [];
      if (questions.length) {
        html += '<div class="gd-questions"><p class="afc-mlabel">Questions de clarification</p>';
        questions.forEach(function (q) {
          var qid = String(q.id || "");
          var answer = w.answers[qid] != null ? w.answers[qid] : (q.default != null ? q.default : "");
          html += '<div class="afc-q gd-question"><p class="afc-q-title">' + esc(q.question_fr || qid) + '</p>' +
            (q.why ? '<p class="afc-q-why">' + esc(q.why) + '</p>' : "") +
            (q.options && q.options.length ? '<p class="gd-options">Options suggérées : ' + esc(q.options.join(", ")) + '</p>' : "") +
            '<input class="afc-input gd-wizard-answer" data-qid="' + esc(qid) + '" value="' + esc(answer) + '"></div>';
        });
        html += '</div>';
      } else {
        html += '<div class="afc-note afc-note--info">Le brouillon ne demande aucune précision supplémentaire.</div>';
      }
      html += '<div class="afc-actions"><button class="afc-btn afc-btn--ghost" id="gdWizardRedraft">' +
        'Re-rédiger avec mes réponses</button></div>';
    }
    html += '</div>';
    return html;
  }

  function renderGuidedSuccess(run) {
    var captured = (run.state && run.state.captured) || {};
    return '<div class="afc-card gd-success"><p class="afc-sec-eyebrow">Assistant terminé</p>' +
      '<h3>Le nouvel expert est actif</h3><dl class="afc-kv">' +
      '<dt>Domaine</dt><dd>' + esc(run.domain || "-") + '</dd>' +
      '<dt>Agent</dt><dd>' + esc(captured.agent_id || "-") + '</dd>' +
      '<dt>Outil</dt><dd>' + esc(captured.tool_id || "-") + '</dd></dl>' +
      '<div class="afc-note afc-note--info">Ouvrez une NOUVELLE conversation dans la webapp principale pour voir le nouvel expert.</div>' +
      '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="gdNew">Nouveau domaine guidé</button></div></div>';
  }

  function wireGuidedRun() {
    if (byId("gdRunStage")) { byId("gdRunStage").onclick = confirmGuidedStageRun; }
    if (byId("gdVerify")) { byId("gdVerify").onclick = confirmGuidedVerify; }
    if (byId("gdRefreshRun")) { byId("gdRefreshRun").onclick = refreshGuidedCurrent; }
    if (byId("gdAbandon")) { byId("gdAbandon").onclick = confirmGuidedAbandon; }
    if (byId("gdWizardDraft")) {
      byId("gdWizardDraft").onclick = function () { confirmGuidedWizardDraft(false); };
    }
    if (byId("gdWizardRedraft")) {
      byId("gdWizardRedraft").onclick = function () {
        gatherGuidedWizardAnswers();
        confirmGuidedWizardDraft(true);
      };
    }
    document.querySelectorAll(".gd-wizard-answer").forEach(function (elm) {
      elm.oninput = function () {
        S.guided.wizard.answers[elm.getAttribute("data-qid")] = elm.value;
      };
    });
  }

  function confirmGuidedStageRun() {
    var run = S.guided.run || {};
    var stage = run.state && run.state.stages && run.state.stages[run.current_stage];
    openConfirm({
      title: stage && stage.status === "failed" ? "Relancer cette étape ?" : "Lancer cette étape ?",
      bodyHtml: "L'étape <b>" + esc((stage && stage.title_fr) || run.current_stage || "") +
        "</b> sera exécutée côté serveur. Son journal sera affiché en direct.",
      confirmLabel: stage && stage.status === "failed" ? "Relancer" : "Lancer",
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
    renderGuided();
    callApi("POST", "guided/run", { confirm: true, run_id: run.run_id }).then(function (r) {
      if (!r.data || r.data.status !== "ok" || !r.data.job_id) {
        g.running = false;
        g.actionError = guidedErrorText(r.data);
        renderGuided();
        return;
      }
      pollJob(r.data.job_id, function (actions) {
        g.liveActions = actions || [];
        renderGuided();
      }, function (result, actions) {
        g.running = false;
        g.liveActions = actions || [];
        if (result && result.run) {
          applyGuidedRun(result.run);
          refreshDatasetsAfterInfra(stageKey, result.run);
        } else {
          g.actionError = "Le résultat serveur ne contient pas le run mis à jour.";
        }
        renderGuided();
      }, function (err, actions) {
        g.running = false;
        g.liveActions = actions || [];
        toast("L'étape a échoué. Rechargement de son état...");
        g.loaded = false;
        loadGuidedCurrent();
      });
    });
  }

  function refreshDatasetsAfterInfra(stageKey, run) {
    var infra = run && run.state && run.state.stages && run.state.stages.infra;
    if (stageKey === "infra" && infra && infra.status === "done") {
      loadDatasets(null, true);
    }
  }

  function confirmGuidedVerify() {
    var run = S.guided.run || {};
    var stage = run.state && run.state.stages && run.state.stages[run.current_stage];
    openConfirm({
      title: "Vérifier cette étape ?",
      bodyHtml: "Le serveur va contrôler dans DSS que l'étape <b>" +
        esc((stage && stage.title_fr) || run.current_stage || "") + "</b> est réellement terminée.",
      confirmLabel: "Vérifier",
      onConfirm: verifyGuidedStage
    });
  }

  function verifyGuidedStage() {
    var g = S.guided;
    var run = g.run || {};
    g.verifying = true;
    g.actionError = null;
    renderGuided();
    callApi("POST", "guided/verify", { confirm: true, run_id: run.run_id }).then(function (r) {
      g.verifying = false;
      if (r.data && r.data.status === "ok" && r.data.run) {
        applyGuidedRun(r.data.run);
      } else {
        g.actionError = guidedErrorText(r.data);
      }
      renderGuided();
    });
  }

  function gatherGuidedWizardAnswers() {
    document.querySelectorAll(".gd-wizard-answer").forEach(function (elm) {
      S.guided.wizard.answers[elm.getAttribute("data-qid")] = elm.value;
    });
  }

  function confirmGuidedWizardDraft(withAnswers) {
    openConfirm({
      title: withAnswers ? "Re-rédiger le brouillon ?" : "Rédiger le brouillon ?",
      bodyHtml: "Le wizard IA va analyser les métadonnées agrégées du profil. Aucune ligne brute ne sera envoyée au modèle.",
      confirmLabel: withAnswers ? "Re-rédiger" : "Rédiger",
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
    if (!withAnswers) { w.config = null; w.answers = {}; }
    w.reqId += 1;
    var reqId = w.reqId;
    renderGuided();
    callApi("POST", "wizard/draft", {
      confirm: true,
      profile_dataset: (spec.base_dataset || "") + "_profile",
      base_dataset: spec.base_dataset || "",
      domain: run.domain || spec.domain || "",
      answers: withAnswers ? w.answers : null
    }).then(function (r) {
      if (reqId !== w.reqId) { return; }
      if (!r.data || r.data.status !== "ok" || !r.data.job_id) {
        w.running = false;
        w.error = guidedErrorText(r.data);
        renderGuided();
        return;
      }
      w.jobId = r.data.job_id;
      pollJob(w.jobId, null, function (result) {
        if (reqId !== w.reqId) { return; }
        w.running = false;
        if (result && result.error) {
          w.config = null;
          w.error = String(result.error);
        } else {
          w.config = result || {};
        }
        renderGuided();
        if (w.config) { toast("Brouillon sémantique enregistré."); }
      }, function (err) {
        if (reqId !== w.reqId) { return; }
        w.running = false;
        w.error = guidedErrorText({ error: err });
        renderGuided();
      });
    });
  }

  function confirmGuidedAbandon() {
    openConfirm({
      title: "Abandonner ce run ?",
      bodyHtml: "Le run sera marqué comme abandonné. Rien ne sera supprimé dans DSS et les éléments déjà créés resteront en place.",
      confirmLabel: "Abandonner",
      danger: true,
      onConfirm: abandonGuidedRun
    });
  }

  function abandonGuidedRun() {
    var g = S.guided;
    var runId = g.run && g.run.run_id;
    g.abandoning = true;
    g.actionError = null;
    renderGuided();
    callApi("POST", "guided/abandon", { confirm: true, run_id: runId }).then(function (r) {
      g.abandoning = false;
      if (r.data && r.data.status === "ok") {
        applyGuidedRun(null);
        toast("Run abandonné. Rien n'a été supprimé dans DSS.");
      } else {
        g.actionError = guidedErrorText(r.data);
      }
      renderGuided();
    });
  }

  function newGuidedDomain() {
    S.guided.form = { domain: "", base_dataset: "", label_fr: "", label_en: "", lookup: "" };
    S.guided.startError = null;
    S.guided.startErrorCode = null;
    applyGuidedRun(null);
    renderGuided();
  }

  /* ============================ screen: Vue d'ensemble ============================ */

  function loadOverview() {
    if (S.overview.loading) { return; }
    S.overview.loading = true;
    S.overview.error = null;
    renderOverview();
    callApi("GET", "state").then(function (r) {
      S.overview.loading = false;
      if (r.data && r.data.status === "ok") {
        S.overview.loaded = true;
        S.overview.data = r.data;
      } else {
        S.overview.error = (r.data && r.data.error) || "load_error";
      }
      renderOverview();
    });
  }

  function renderOverview() {
    if (S.tab !== "overview") { return; }
    var html = '<div class="afc-panel">' + backendBanner();

    if (S.overview.loading && !S.overview.loaded) {
      html += '<p class="afc-loading">Chargement de l\'état du projet...</p></div>';
      setMain(html); return;
    }
    if (S.overview.error && !S.overview.loaded) {
      html += '<div class="afc-note afc-note--error">Impossible de charger l\'état du projet (' + esc(S.overview.error) + ').</div>' +
        '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="ovRetry">' + I.refresh + 'Réessayer</button></div></div>';
      setMain(html);
      if (byId("ovRetry")) { byId("ovRetry").onclick = loadOverview; }
      return;
    }

    var d = S.overview.data || {};
    var settings = d.settings || {};
    var caps = d.capabilities || {};
    var hubChip = d.hub_ready
      ? '<span class="afc-chip afc-chip--on">HUB PRÊT</span>'
      : '<span class="afc-chip afc-chip--off">HUB ABSENT</span>';

    // Project + hub status
    html += '<div class="afc-sec">' +
      '<p class="afc-sec-eyebrow">Projet</p>' +
      '<h2 class="afc-sec-title">Vue d\'ensemble</h2>' +
      '<p class="afc-sec-note">État du projet DSS et du Config &amp; Prompt Hub (/python/owismind_hub). ' +
      'C\'est le tableau de bord de l\'usine à agents : rien n\'est modifié ici.</p>' +
      '<div class="afc-card"><dl class="afc-kv">' +
      '<dt>Clé de projet</dt><dd>' + esc(d.project_key || "-") + '</dd>' +
      '<dt>Hub</dt><dd>' + hubChip + '</dd>' +
      '</dl></div></div>';

    // Settings summary
    html += '<div class="afc-sec"><p class="afc-mlabel">Réglages de l\'usine (factory_settings.json)</p>' +
      '<div class="afc-card"><dl class="afc-kv">' +
      '<dt>Connexion SQL</dt><dd>' + esc(settings.sql_connection || "-") + '</dd>' +
      '<dt>Code env 3.11</dt><dd>' + esc(settings.code_env_311 || "(défaut projet)") + '</dd>' +
      '<dt>LLM sonnet</dt><dd>' + esc(settings.llm_sonnet || "-") + '</dd>' +
      '<dt>Modèle sémantique modèle</dt><dd>' + esc(settings.template_semantic_model_id || "-") + '</dd>' +
      '<dt>Outil sémantique modèle</dt><dd>' + esc(settings.template_semantic_tool_id || "-") + '</dd>' +
      '<dt>Orchestrateur</dt><dd>' + esc(settings.orchestrator_agent_id || "-") + '</dd>' +
      '</dl></div></div>';

    // Capabilities cards
    var capKeys = Object.keys(caps);
    html += '<div class="afc-sec"><p class="afc-mlabel">Capacités enregistrées (' + capKeys.length + ')</p>';
    if (S.overview.flash) {
      html += '<div class="afc-note afc-note--error">' + esc(S.overview.flash) + '</div>';
      S.overview.flash = null;
    }
    if (!capKeys.length) {
      html += '<div class="afc-note afc-note--info">Aucune capacité dans le hub. ' +
        'Soit le hub n\'est pas encore poussé dans la project library, soit l\'orchestrateur utilise ses CAPABILITIES embarquées par défaut.</div>';
    } else {
      html += '<div class="afc-cap-grid">';
      capKeys.forEach(function (k) {
        var c = caps[k] || {};
        var enChip = c.enabled
          ? '<span class="afc-chip afc-chip--on">ACTIF</span>'
          : '<span class="afc-chip afc-chip--off">INACTIF</span>';
        html += '<div class="afc-cap-card">' +
          '<span class="afc-cap-domain">' + esc(c.domain || k) + '</span>' +
          '<span class="afc-cap-label">' + esc(c.label_fr || "") + '</span>' +
          '<span class="afc-cap-id">' + esc(c.agent_id || "-") + '</span>' +
          '<div class="afc-cap-foot">' + enChip +
          '<span class="afc-cap-label mono">' + esc(c.tool_name || "") + '</span></div>' +
          '<div class="afc-cap-actions">' +
          '<button class="afc-btn afc-btn--ghost afc-btn--sm" data-cap-toggle="' + esc(k) + '">' +
          (c.enabled ? "Désactiver" : "Activer") + '</button>' +
          '<button class="afc-btn afc-btn--ghost afc-btn--sm" data-cap-remove="' + esc(k) + '">' +
          'Supprimer...</button>' +
          '</div></div>';
      });
      html += '</div>';
    }
    html += '</div>';

    html += '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="ovRefresh">' + I.refresh + 'Actualiser</button></div>';
    html += '</div>';
    setMain(html);
    Array.prototype.forEach.call(document.querySelectorAll("[data-cap-toggle]"), function (btn) {
      btn.onclick = function () { confirmCapabilityToggle(btn.getAttribute("data-cap-toggle")); };
    });
    Array.prototype.forEach.call(document.querySelectorAll("[data-cap-remove]"), function (btn) {
      btn.onclick = function () { openCapabilityRemoval(btn.getAttribute("data-cap-remove")); };
    });
    if (byId("ovRefresh")) {
      byId("ovRefresh").onclick = function () { S.overview.loaded = false; loadOverview(); };
    }
  }

  function confirmCapabilityToggle(key) {
    var caps = (S.overview.data || {}).capabilities || {};
    var c = caps[key] || {};
    var next = !c.enabled;
    openConfirm({
      title: next ? "Activer cette capacité ?" : "Désactiver cette capacité ?",
      bodyHtml: "La capacité <b class=\"mono\">" + esc(key) + "</b> passera à <b>" +
        (next ? "ACTIF" : "INACTIF") + "</b> dans capabilities.json (sauvegarde " +
        "automatique du fichier précédent). L'architecture du domaine n'est pas modifiée." +
        "<br><br>RAPPEL : re-sauvegarde l'orchestrateur dans DSS puis ouvre une " +
        "NOUVELLE conversation pour que le registre soit rechargé (il est lu au " +
        "démarrage du process).",
      confirmLabel: next ? "Activer" : "Désactiver",
      onConfirm: function () {
        callApi("POST", "capability/enable", {
          confirm: true, capability_key: key, enabled: next
        }).then(function (r) {
          if (!r.data || r.data.status !== "ok") {
            S.overview.flash = "Bascule impossible (" +
              ((r.data && r.data.error) || "erreur") + ").";
            renderOverview();
            return;
          }
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
      title: "Supprimer le domaine " + domain + " ?",
      danger: true,
      bodyHtml: "Un run guidé de SUPPRESSION sera créé pour <b class=\"mono\">" +
        esc(key) + "</b>. Rien n'est supprimé maintenant : l'assistant fait " +
        "d'abord l'inventaire, puis chaque suppression est affichée et confirmée " +
        "UNE PAR UNE. Le dataset source n'est JAMAIS touché." +
        "<br><br>Pour confirmer, tape le nom exact du domaine " +
        "(<b class=\"mono\">" + esc(domain) + "</b>) :" +
        "<br><input class=\"afc-input\" type=\"text\" id=\"capRemoveTyped\" autocomplete=\"off\">",
      confirmLabel: "Créer le run de suppression",
      onConfirm: function () {
        var field = byId("capRemoveTyped");
        var typed = (field ? field.value : "").trim();
        callApi("POST", "guided/start-removal", {
          confirm: true, capability_key: key, domain_typed: typed
        }).then(function (r) {
          if (!r.data || r.data.status !== "ok") {
            var code = (r.data && r.data.error) || "erreur";
            S.overview.flash = code === "domain_mismatch"
              ? "Le nom tapé ne correspond pas au domaine : run NON créé."
              : (code === "active_run_exists"
                ? "Un run guidé est déjà actif : termine-le ou abandonne-le d'abord."
                : "Création impossible (" + code + ").");
            renderOverview();
            return;
          }
          S.guided.loaded = false;
          selectTab("guided");
        });
      }
    });
  }

  /* ============================ screen: Sonde (Phase 0) ============================ */

  function renderProbe() {
    if (S.tab !== "probe") { return; }
    var p = S.probe;
    var html = '<div class="afc-panel">' + backendBanner() +
      '<div class="afc-sec">' +
      '<p class="afc-sec-eyebrow">Phase 0</p>' +
      '<h2 class="afc-sec-title">Sonde de l\'instance</h2>' +
      '<p class="afc-sec-note">Les sondes lecture seule inspectent l\'instance DSS (API des Code Agents, ' +
      'schéma des outils Semantic Model Query, disponibilité de create_agent) pour savoir ce que l\'usine ' +
      'peut automatiser en toute sécurité. Elles ne créent, ne modifient et ne suppriment rien. Lancez-les ' +
      'une fois, puis collez le rapport dans le repo.</p>';

    if (p.running) {
      html += '<div class="afc-note afc-note--info">Sondes en cours... (lecture seule)</div>';
    } else {
      html += '<div class="afc-actions">' +
        '<button class="afc-btn afc-btn--primary" id="probeRun">' + I.play + 'Lancer les sondes lecture seule</button>' +
        '</div>';
    }

    if (p.error) {
      html += '<div class="afc-note afc-note--error">Échec de la sonde : ' + esc(p.error) + '</div>';
    }
    if (p.report) {
      html += '<div class="afc-sec" style="margin-top:24px;">' +
        '<div class="afc-actions" style="margin-top:0;">' + copyButton("probeCopy", "Copier le rapport") + '</div>' +
        '<pre class="afc-pre" id="probeReport">' + esc(p.report) + '</pre></div>';
    }
    html += '</div></div>';
    setMain(html);

    if (byId("probeRun")) {
      byId("probeRun").onclick = function () {
        openConfirm({
          title: "Lancer les sondes ?",
          bodyHtml: "Les sondes sont en <b>lecture seule</b> : elles inspectent l\'instance et ne modifient rien. " +
            "Le rapport apparaîtra ci-dessous une fois terminé.",
          confirmLabel: "Lancer",
          onConfirm: startProbe
        });
      };
    }
    if (p.report) { wireCopy("probeCopy", function () { return p.report; }); }
  }

  function startProbe() {
    var p = S.probe;
    p.running = true; p.error = null; p.report = null;
    renderProbe();
    callApi("POST", "probe", { confirm: true }).then(function (r) {
      if (!r.data || r.data.status !== "ok" || !r.data.job_id) {
        p.running = false;
        p.error = (r.data && r.data.error) || "start_failed";
        renderProbe();
        return;
      }
      p.jobId = r.data.job_id;
      pollJob(p.jobId, null, function (result) {
        p.running = false;
        p.report = (result && (result.report || result.markdown)) || "(rapport vide)";
        renderProbe();
        toast("Sondes terminées.");
      }, function (err) {
        p.running = false;
        p.error = err;
        renderProbe();
      });
    });
  }

  /* ============================ screen: Nouveau domaine ============================ */

  function renderDomain() {
    if (S.tab !== "domain") { return; }
    loadDatasets(function () { if (S.tab === "domain") { renderDomainNow(); } });
    renderDomainNow();
  }

  function renderDomainNow() {
    if (S.tab !== "domain") { return; }
    var f = S.domain.form;
    var html = '<div class="afc-panel">' + backendBanner();

    // --- creation form ---
    html += '<div class="afc-sec">' +
      '<p class="afc-sec-eyebrow">Usine</p>' +
      '<h2 class="afc-sec-title">Nouveau domaine spécialiste</h2>' +
      '<p class="afc-sec-note">Décrivez le domaine, planifiez en dry-run (aucune écriture DSS), vérifiez le plan, ' +
      'puis exécutez. Les étapes que l\'usine ne peut pas automatiser en sécurité apparaissent en MANUEL avec la marche à suivre.</p>' +
      '<div class="afc-card">';

    html += field("Clé de domaine (snake_case)", inputEl("dmDomain", f.domain, "ex. satisfaction"),
      "Minuscules, chiffres et underscores. Sert à nommer la capacité, l\'outil et le scénario.");

    // source mode segmented
    html += '<div class="afc-field"><span class="afc-field-label">Source des données</span>' +
      '<div class="afc-seg" id="dmSeg">' +
      '<button data-mode="existing"' + (f.sourceMode === "existing" ? ' class="on"' : "") + '>Dataset existant</button>' +
      '<button data-mode="source"' + (f.sourceMode === "source" ? ' class="on"' : "") + '>Table SQL à importer</button>' +
      '</div></div>';

    if (f.sourceMode === "existing") {
      var dsField = S.datasets.loading
        ? '<p class="afc-loading">Chargement des datasets...</p>'
        : '<select class="afc-select" id="dmBaseSelect">' + datasetOptions(f.base_dataset) + '</select>';
      html += field("Dataset de base", dsField,
        "Le dataset déjà présent dans le projet dont ce spécialiste sera l\'expert.");
    } else {
      html += '<div class="afc-grid-2">' +
        fieldRaw("Nom du dataset de base à créer", inputEl("dmBaseName", f.base_dataset, "ex. Satisfaction")) +
        fieldRaw("Connexion SQL", inputEl("dmConn", f.connection, "SQL_owi")) +
        fieldRaw("Schéma (optionnel)", inputEl("dmSchema", f.schema, "public")) +
        fieldRaw("Table source", inputEl("dmTable", f.table, "ex. Satisfaction")) +
        '</div>' +
        field("Catalogue (optionnel)", inputEl("dmCatalog", f.catalog, ""), "");
    }

    html += '<div class="afc-grid-2">' +
      fieldRaw("Libellé FR", inputEl("dmLabelFr", f.label_fr, "ex. Satisfaction client")) +
      fieldRaw("Libellé EN", inputEl("dmLabelEn", f.label_en, "ex. Customer satisfaction")) +
      '</div>';

    html += field("Colonnes de recherche du lookup (une par ligne, optionnel)",
      '<textarea class="afc-textarea mono" id="dmLookup" placeholder="Account_name&#10;carrier_code">' + esc(f.lookup) + '</textarea>',
      "Liste blanche des colonnes texte utilisées par attribute_lookup. Vide = toutes les colonnes texte.");

    html += '<div class="afc-actions">' +
      '<button class="afc-btn afc-btn--ghost" id="dmPlan"' + (S.domain.planning ? " disabled" : "") + '>' +
      (S.domain.planning ? "Planification..." : "Planifier (dry-run)") + '</button>';
    if (S.domain.plan) {
      html += '<button class="afc-btn afc-btn--primary" id="dmExec"' + (S.domain.executing ? " disabled" : "") + '>' + I.play +
        (S.domain.executing ? "Exécution..." : "Exécuter") + '</button>';
    }
    html += '</div>';

    // Status of the semantic wizard draft: tells the user whether Plan/Execute will
    // carry a semantic-model config, or leave the model to configure by hand later.
    var wizardReady = wizardConfigForSend() !== undefined;
    html += '<p class="afc-field-help">' + (wizardReady
      ? 'Config du wizard : prête (sera appliquée)'
      : 'Config du wizard : absente (le modèle sémantique restera à configurer)') + '</p>';

    if (S.domain.planError) {
      html += '<div class="afc-note afc-note--error">Plan impossible : ' + esc(S.domain.planError) + '</div>';
    }
    html += '</div>'; // card

    // --- plan result ---
    if (S.domain.plan) {
      var pl = S.domain.plan;
      var counts = pl.counts || {};
      html += '<div class="afc-sec"><p class="afc-mlabel">Plan (dry-run) - ' +
        (pl.actions ? pl.actions.length : 0) + ' étapes</p>' +
        '<p class="afc-count">' + countsLine(counts) + '</p>';
      // Non-blocking preflight warnings returned by the backend (collisions,
      // weak routing signal, name headroom): shown BEFORE the actions table.
      if (pl.warnings && pl.warnings.length) {
        html += '<div class="afc-note afc-note--info"><b>Avertissements (non bloquants) :</b><ul>' +
          pl.warnings.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join("") +
          '</ul></div>';
      }
      html += actionsTable(pl.actions) + '</div>';
    }

    // --- execution journal ---
    if (S.domain.executing || S.domain.execResult || S.domain.execError) {
      html += '<div class="afc-sec"><p class="afc-mlabel">Journal d\'exécution</p>';
      if (S.domain.executing) {
        html += '<div class="afc-note afc-note--info">Exécution en cours...</div>';
      }
      if (S.domain.execError) {
        html += '<div class="afc-note afc-note--error">Échec de l\'exécution : ' + esc(S.domain.execError) + '</div>';
      }
      // Honest completion: FAILED/BLOCKED steps mean the creation is incomplete.
      if (S.domain.execResult) {
        var xc = S.domain.execResult.counts || {};
        var xbad = (xc.FAILED || 0) + (xc.BLOCKED || 0);
        if (xbad) {
          html += '<div class="afc-note afc-note--error">' + xbad +
            ' étape(s) en échec ou bloquée(s) : la création n\'est pas complète, lisez le runbook ci-dessous.</div>';
        }
      }
      var execActions = (S.domain.execResult && S.domain.execResult.actions) || S.domain.execActions || [];
      html += actionsTable(execActions);
      html += manualChecklist(execActions);
      // Copy-pastable ordered runbook rendered by the backend after a real run.
      if (S.domain.execResult && S.domain.execResult.runbook) {
        html += '<p class="afc-mlabel">Runbook opérateur (copiable)</p>' +
          '<pre class="afc-pre">' + esc(S.domain.execResult.runbook) + '</pre>';
      }
      html += '</div>';
    }

    // --- semantic wizard ---
    html += renderWizardSection();

    html += '</div>';
    setMain(html);
    wireDomain();
  }

  function renderWizardSection() {
    var w = S.domain.wizard;
    var html = '<div class="afc-sec">' +
      '<p class="afc-sec-eyebrow">Assistant</p>' +
      '<h2 class="afc-sec-title">Wizard sémantique</h2>' +
      '<p class="afc-sec-note">Génère un brouillon de configuration du modèle sémantique (entités, attributs, ' +
      'métriques, filtres, glossaire, instructions SQL, requêtes golden) à partir du dataset de profil. ' +
      'Seules des métadonnées agrégées sont envoyées au LLM, jamais des lignes brutes.</p>' +
      '<div class="afc-card">';

    var dsField = S.datasets.loading
      ? '<p class="afc-loading">Chargement des datasets...</p>'
      : '<select class="afc-select" id="wzProfile">' + datasetOptions(w.profileDataset) + '</select>';
    html += field("Dataset de profil", dsField,
      "En général <base>_profile. Sa métadonnée agrégée alimente le brouillon.");

    html += '<div class="afc-actions">' +
      '<button class="afc-btn afc-btn--ghost" id="wzDraft"' + (w.running ? " disabled" : "") + '>' +
      (w.running ? "Génération..." : "Générer le brouillon") + '</button></div>';

    if (w.error) {
      html += '<div class="afc-note afc-note--error">Wizard impossible : ' + esc(w.error) + '</div>';
    }
    html += '</div>'; // card

    if (w.config) {
      var cfg = w.config;
      var questions = cfg.questions || [];
      if (questions.length) {
        html += '<div class="afc-sec" style="margin-top:20px;"><p class="afc-mlabel">Questions de clarification</p>';
        questions.forEach(function (q) {
          var qid = q.id;
          var val = (w.answers[qid] != null) ? w.answers[qid] : (q.default != null ? q.default : "");
          var control;
          if (q.options && q.options.length) {
            var opts = q.options.map(function (o) {
              return '<option value="' + esc(o) + '"' + (String(o) === String(val) ? " selected" : "") + '>' + esc(o) + '</option>';
            }).join("");
            control = '<select class="afc-select wz-answer" data-qid="' + esc(qid) + '">' + opts + '</select>';
          } else {
            control = '<input class="afc-input wz-answer" data-qid="' + esc(qid) + '" value="' + esc(val) + '">';
          }
          html += '<div class="afc-q"><p class="afc-q-title">' + esc(q.question_fr || q.id) + '</p>' +
            (q.why ? '<p class="afc-q-why">' + esc(q.why) + '</p>' : "") + control + '</div>';
        });
        html += '<div class="afc-actions">' +
          '<button class="afc-btn afc-btn--ghost" id="wzRegen"' + (w.regenerating ? " disabled" : "") + '>' +
          (w.regenerating ? "Régénération..." : "Régénérer avec mes réponses") + '</button></div></div>';
      }

      html += '<div class="afc-sec" style="margin-top:20px;"><p class="afc-mlabel">Configuration du modèle (brouillon)</p>' +
        '<div class="afc-actions" style="margin-top:0;">' + copyButton("wzCopy", "Copier le JSON") + '</div>' +
        '<pre class="afc-pre" id="wzJson">' + esc(JSON.stringify(cfg, null, 2)) + '</pre></div>';
    }

    html += '</div>';
    return html;
  }

  /* Any domain-form edit makes a previously computed plan (and its execution
   * result) stale, because Execute rebuilds the spec from the LIVE form. Drop the
   * plan so the Execute button disappears and the user must re-plan. Returns true
   * when something was actually cleared (so the caller knows a re-render is due). */
  function invalidateDomainPlan() {
    var d = S.domain;
    if (!d.plan && !d.planError && !d.planning && !d.execResult && !d.execError &&
        !(d.execActions && d.execActions.length)) {
      return false;
    }
    d.plan = null; d.planError = null;
    // An edit also cancels interest in any in-flight plan request: its response
    // will be dropped by the fingerprint guard, so stop the spinner here.
    d.planning = false;
    d.execResult = null; d.execError = null; d.execActions = [];
    return true;
  }

  /* Identity of the spec a plan or wizard draft was computed FOR. A response
   * coming back for a different fingerprint than the current form is stale and
   * must be dropped (in-flight race: plan for A, edit to B, response A arrives). */
  function specFingerprint() {
    var f = S.domain.form;
    return [f.domain || "", f.base_dataset || "", f.sourceMode || "",
            f.connection || "", f.schema || "", f.table || "", f.catalog || "",
            f.label_fr || "", f.label_en || "", f.lookup || ""].join("");
  }

  /* Identity fields a wizard draft is bound to (narrower than the full form:
   * label edits do not orphan a draft, but domain/dataset changes do). */
  function wizardFingerprint() {
    var f = S.domain.form;
    return [(f.domain || "").trim(), (f.base_dataset || "").trim(),
            S.domain.wizard.profileDataset || ""].join("");
  }

  /* Drop the wizard draft when the domain identity changes: a draft for Sales
   * must never be applied to Tickets. Bumping reqId also makes any in-flight
   * draft job completion stale (it is ignored on arrival). */
  function invalidateWizardDraft() {
    var w = S.domain.wizard;
    w.reqId = (w.reqId || 0) + 1;
    if (w.config === null && !w.running && !w.regenerating) { return false; }
    w.config = null; w.answers = {}; w.running = false; w.regenerating = false;
    return true;
  }

  /* bindInput for a domain-form field: update the form, then invalidate any stale
   * plan. Re-render only when the plan was actually cleared, restoring focus to the
   * field being edited so typing is never interrupted. */
  function domainField(id, cb, isChange, isIdentity) {
    bindInput(id, function (v) {
      cb(v);
      var cleared = invalidateDomainPlan();
      // Identity fields (domain / base dataset) also orphan the wizard draft.
      if (isIdentity) { cleared = invalidateWizardDraft() || cleared; }
      if (cleared) {
        renderDomainNow();
        var e = byId(id);
        if (e) {
          e.focus();
          if (e.setSelectionRange && typeof e.value === "string") {
            try { e.setSelectionRange(e.value.length, e.value.length); } catch (err) { /* ignore */ }
          }
        }
      }
    }, isChange);
  }

  function wireDomain() {
    var f = S.domain.form;

    var seg = byId("dmSeg");
    if (seg) {
      seg.querySelectorAll("button").forEach(function (b) {
        b.onclick = function () {
          f.sourceMode = this.getAttribute("data-mode");
          invalidateDomainPlan(); // changing the source shape invalidates the plan too
          renderDomainNow();
        };
      });
    }
    domainField("dmDomain", function (v) { f.domain = v; }, false, true);
    domainField("dmBaseSelect", function (v) { f.base_dataset = v; }, true, true);
    domainField("dmBaseName", function (v) { f.base_dataset = v; }, false, true);
    domainField("dmConn", function (v) { f.connection = v; });
    domainField("dmSchema", function (v) { f.schema = v; });
    domainField("dmTable", function (v) { f.table = v; });
    domainField("dmCatalog", function (v) { f.catalog = v; });
    domainField("dmLabelFr", function (v) { f.label_fr = v; });
    domainField("dmLabelEn", function (v) { f.label_en = v; });
    domainField("dmLookup", function (v) { f.lookup = v; });

    if (byId("dmPlan")) { byId("dmPlan").onclick = planDomain; }
    if (byId("dmExec")) { byId("dmExec").onclick = confirmExecute; }

    // wizard
    var w = S.domain.wizard;
    bindInput("wzProfile", function (v) {
      if (v !== w.profileDataset) {
        w.profileDataset = v;
        // A draft is bound to its profile dataset: switching it orphans the draft.
        if (invalidateWizardDraft()) { invalidateDomainPlan(); renderDomainNow(); }
      }
    }, true);
    if (byId("wzDraft")) { byId("wzDraft").onclick = function () { startWizard(false); }; }
    if (byId("wzRegen")) {
      byId("wzRegen").onclick = function () {
        // gather answers first
        document.querySelectorAll(".wz-answer").forEach(function (elm) {
          w.answers[elm.getAttribute("data-qid")] = elm.value;
        });
        startWizard(true);
      };
    }
    if (w.config) { wireCopy("wzCopy", function () { return JSON.stringify(w.config, null, 2); }); }
  }

  /* The wizard draft config to attach to a plan/execute call, or undefined. Only a
   * non-null object without an .error key is a usable draft; anything else means the
   * semantic model stays unconfigured and we send nothing. */
  function wizardConfigForSend() {
    var c = S.domain.wizard.config;
    if (c && typeof c === "object" && !c.error) { return c; }
    return undefined;
  }

  function buildSpec() {
    var f = S.domain.form;
    var lookup = (f.lookup || "").split("\n").map(function (s) { return s.trim(); }).filter(Boolean);
    var spec = {
      domain: (f.domain || "").trim(),
      base_dataset: (f.base_dataset || "").trim(),
      label_fr: (f.label_fr || "").trim(),
      label_en: (f.label_en || "").trim(),
      lookup_search_columns: lookup
    };
    if (f.sourceMode === "source") {
      spec.source = { connection: (f.connection || "").trim(), table: (f.table || "").trim() };
      if (f.schema) { spec.source.schema = f.schema.trim(); }
      if (f.catalog) { spec.source.catalog = f.catalog.trim(); }
    }
    return spec;
  }

  function planDomain() {
    S.domain.planning = true; S.domain.planError = null; S.domain.plan = null;
    // reset any prior execution when re-planning
    S.domain.execResult = null; S.domain.execError = null; S.domain.execActions = [];
    renderDomainNow();
    // Capture what this plan is FOR: if the form changed while the request was in
    // flight, the response is stale and must not resurrect an Execute button for
    // a spec the user never planned.
    var sentFor = specFingerprint();
    callApi("POST", "plan", { spec: buildSpec(), wizard_config: wizardConfigForSend() }).then(function (r) {
      if (sentFor !== specFingerprint()) { return; } // stale response: drop it
      S.domain.planning = false;
      if (r.data && r.data.status === "ok") {
        S.domain.plan = { counts: r.data.counts || {}, actions: r.data.actions || [],
                          dry_run: r.data.dry_run, warnings: r.data.warnings || [] };
      } else {
        S.domain.planError = errorText(r.data);
      }
      renderDomainNow();
    });
  }

  function confirmExecute() {
    var spec = buildSpec();
    var pl = S.domain.plan || {};
    var willCreate = (pl.actions || [])
      .filter(function (a) { return a.status === "PLANNED"; })
      .map(function (a) { return '<li><span class="mono">' + esc(a.step) + '</span> : ' + esc(a.detail || "") + '</li>'; })
      .join("");
    var body = '<p>Vous allez exécuter la création du domaine <b class="mono">' + esc(spec.domain || "(sans nom)") + '</b> ' +
      'réellement sur le projet DSS. Les étapes marquées MANUEL ne seront pas automatisées.</p>';
    if (willCreate) {
      body += '<p style="margin-top:10px;">Étapes planifiées :</p><ul>' + willCreate + '</ul>';
    }
    body += '<p style="margin-top:10px;">Aucune suppression n\'est effectuée. Vous pourrez revoir le journal étape par étape.</p>';
    openConfirm({
      title: "Exécuter la création ?",
      bodyHtml: body,
      confirmLabel: "Exécuter",
      onConfirm: executeDomain
    });
  }

  function executeDomain() {
    S.domain.executing = true; S.domain.execError = null; S.domain.execResult = null; S.domain.execActions = [];
    renderDomainNow();
    callApi("POST", "execute", { spec: buildSpec(), wizard_config: wizardConfigForSend(), confirm: true }).then(function (r) {
      if (!r.data || r.data.status !== "ok" || !r.data.job_id) {
        S.domain.executing = false;
        S.domain.execError = errorText(r.data);
        renderDomainNow();
        return;
      }
      S.domain.execJobId = r.data.job_id;
      pollJob(S.domain.execJobId, function (actions) {
        S.domain.execActions = actions;
        renderDomainNow();
      }, function (result, actions) {
        S.domain.executing = false;
        S.domain.execResult = result || { actions: actions };
        renderDomainNow();
        // A job that finished is not a job that succeeded: FAILED/BLOCKED steps
        // mean the creation is incomplete and the journal must be read.
        var c = (S.domain.execResult && S.domain.execResult.counts) || {};
        var bad = (c.FAILED || 0) + (c.BLOCKED || 0);
        if (bad) {
          toast("Exécution terminée avec " + bad + " étape(s) en échec ou bloquée(s) : lisez le journal.");
        } else {
          toast("Exécution terminée.");
        }
      }, function (err, actions) {
        S.domain.executing = false;
        S.domain.execError = err;
        S.domain.execActions = actions;
        renderDomainNow();
      });
    });
  }

  function startWizard(withAnswers) {
    var w = S.domain.wizard;
    if (!w.profileDataset) { toast("Choisissez d\'abord un dataset de profil."); return; }
    if (withAnswers) { w.regenerating = true; } else { w.running = true; w.config = null; w.answers = {}; }
    w.error = null;
    renderDomainNow();
    // Bind this draft to the current identity + request id: if the user changes
    // domain/dataset (or launches another draft) while the job runs, the late
    // completion is stale and must be ignored, never re-applied.
    w.reqId = (w.reqId || 0) + 1;
    var myReq = w.reqId;
    var draftFor = wizardFingerprint();
    var payload = { confirm: true, profile_dataset: w.profileDataset,
                    base_dataset: S.domain.form.base_dataset || "",
                    domain: (S.domain.form.domain || "").trim() };
    if (withAnswers) { payload.answers = w.answers; }
    callApi("POST", "wizard/draft", payload).then(function (r) {
      if (myReq !== w.reqId) { return; } // superseded while the POST was in flight
      if (!r.data || r.data.status !== "ok" || !r.data.job_id) {
        w.running = false; w.regenerating = false;
        w.error = errorText(r.data);
        renderDomainNow();
        return;
      }
      w.jobId = r.data.job_id;
      pollJob(w.jobId, null, function (result) {
        if (myReq !== w.reqId || draftFor !== wizardFingerprint()) { return; } // stale draft
        w.running = false; w.regenerating = false;
        w.config = result || {};
        // A usable new draft changes what Execute would apply, so any plan computed
        // before it is now stale: drop it (the Execute button hides until re-planned).
        // An error draft sends nothing, so it leaves an existing plan valid.
        if (wizardConfigForSend() !== undefined) { invalidateDomainPlan(); }
        renderDomainNow();
        toast("Brouillon généré.");
      }, function (err) {
        if (myReq !== w.reqId) { return; }
        w.running = false; w.regenerating = false;
        w.error = err;
        renderDomainNow();
      });
    });
  }

  /* ============================ screen: Prompts ============================ */

  function renderPrompts() {
    if (S.tab !== "prompts") { return; }
    var pr = S.prompts;
    var html = '<div class="afc-panel">' + backendBanner();

    // --- persona / prompt editor ---
    html += '<div class="afc-sec">' +
      '<p class="afc-sec-eyebrow">Hub</p>' +
      '<h2 class="afc-sec-title">Prompts de persona</h2>' +
      '<p class="afc-sec-note">Éditez un fichier de prompt du hub (/python/owismind_hub/prompts/...). ' +
      'L\'orchestrateur charge sa persona depuis orchestrator_persona.md ; les sous-agents peuvent charger ' +
      'un ajout prompts/&lt;domaine&gt;/understand_extra.md. Le chemin doit commencer par /python/owismind_hub/prompts/.</p>' +
      '<div class="afc-card">';

    html += '<div class="afc-field"><span class="afc-field-label">Chemin du fichier</span>' +
      '<div style="display:flex;gap:10px;flex-wrap:wrap;">' +
      '<input class="afc-input mono" id="prPath" value="' + esc(pr.path) + '" style="flex:1 1 320px;">' +
      '<button class="afc-btn afc-btn--ghost afc-btn--sm" id="prLoad"' + (pr.loading ? " disabled" : "") + '>' + I.refresh +
      (pr.loading ? "Chargement..." : "Charger") + '</button></div></div>';

    if (pr.loadError) {
      html += '<div class="afc-note afc-note--error">Chargement impossible : ' + esc(pr.loadError) + '</div>';
    }

    html += '<div class="afc-field"><span class="afc-field-label">Contenu</span>' +
      '<textarea class="afc-textarea code" id="prContent" placeholder="' +
      (pr.loaded ? "" : "Cliquez sur Charger pour récupérer le contenu du fichier.") + '">' + esc(pr.content) + '</textarea></div>';

    html += '<div class="afc-actions">' +
      '<button class="afc-btn afc-btn--primary" id="prSave"' + (pr.saving || !pr.loaded ? " disabled" : "") + '>' + I.save +
      'Enregistrer</button></div>';
    html += '</div></div>';

    // --- capabilities editor ---
    var caps = pr.caps;
    html += '<div class="afc-sec"><p class="afc-sec-eyebrow">Hub</p>' +
      '<h2 class="afc-sec-title">Capacités (capabilities.json)</h2>' +
      '<p class="afc-sec-note">Le registre runtime des capacités de l\'orchestrateur. Il est validé côté serveur ' +
      '(clés requises, dictionnaires de libellés, une seule capacité active par domaine) avant écriture ; ' +
      'une sauvegarde du fichier précédent est faite automatiquement.</p>' +
      '<div class="afc-card">';

    html += '<div class="afc-actions" style="margin-top:0;">' +
      '<button class="afc-btn afc-btn--ghost afc-btn--sm" id="capLoad"' + (caps.loading ? " disabled" : "") + '>' + I.refresh +
      (caps.loading ? "Chargement..." : "Charger") + '</button></div>';

    if (caps.loadError) {
      html += '<div class="afc-note afc-note--error">Chargement impossible : ' + esc(caps.loadError) + '</div>';
    }

    html += '<div class="afc-field" style="margin-top:16px;"><span class="afc-field-label">capabilities.json</span>' +
      '<textarea class="afc-textarea code" id="capContent" placeholder="' +
      (caps.loaded ? "" : "Cliquez sur Charger pour récupérer le JSON.") + '">' + esc(caps.text) + '</textarea></div>';

    if (caps.problems && caps.problems.length) {
      html += '<div class="afc-note afc-note--error"><b>Validation refusée :</b><ul>' +
        caps.problems.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join("") + '</ul></div>';
    }

    html += '<div class="afc-actions">' +
      '<button class="afc-btn afc-btn--primary" id="capSave"' + (caps.saving || !caps.loaded ? " disabled" : "") + '>' + I.save +
      'Valider et enregistrer</button></div>';
    html += '</div></div></div>';

    setMain(html);
    wirePrompts();
  }

  function wirePrompts() {
    var pr = S.prompts;
    bindInput("prPath", function (v) { pr.path = v; });
    bindInput("prContent", function (v) { pr.content = v; });
    if (byId("prLoad")) { byId("prLoad").onclick = loadPrompt; }
    if (byId("prSave")) { byId("prSave").onclick = confirmSavePrompt; }

    bindInput("capContent", function (v) { pr.caps.text = v; });
    if (byId("capLoad")) { byId("capLoad").onclick = loadCaps; }
    if (byId("capSave")) { byId("capSave").onclick = confirmSaveCaps; }
  }

  function loadPrompt() {
    var pr = S.prompts;
    if (!/^\/python\/owismind_hub\/prompts\//.test(pr.path)) {
      pr.loadError = "Le chemin doit commencer par /python/owismind_hub/prompts/";
      renderPrompts(); return;
    }
    pr.loading = true; pr.loadError = null;
    renderPrompts();
    callApi("GET", "hub/prompt?path=" + encodeURIComponent(pr.path)).then(function (r) {
      pr.loading = false;
      if (r.data && r.data.status === "ok") {
        pr.loaded = true;
        pr.content = r.data.content || "";
      } else {
        pr.loadError = errorText(r.data);
      }
      renderPrompts();
    });
  }

  function confirmSavePrompt() {
    var pr = S.prompts;
    openConfirm({
      title: "Enregistrer le prompt ?",
      bodyHtml: "Le fichier <span class=\"mono\">" + esc(pr.path) + "</span> sera écrit dans la project library du projet. " +
        "Les agents rechargeront ce prompt à leur prochain démarrage.",
      confirmLabel: "Enregistrer",
      onConfirm: savePrompt
    });
  }

  function savePrompt() {
    var pr = S.prompts;
    pr.saving = true;
    renderPrompts();
    callApi("POST", "hub/prompt", { confirm: true, path: pr.path, content: pr.content }).then(function (r) {
      pr.saving = false;
      if (r.data && r.data.status === "ok") {
        toast("Prompt enregistré.");
      } else {
        toast("Enregistrement impossible.");
        pr.loadError = errorText(r.data);
      }
      renderPrompts();
    });
  }

  function loadCaps() {
    var caps = S.prompts.caps;
    caps.loading = true; caps.loadError = null; caps.problems = [];
    renderPrompts();
    callApi("GET", "hub/capabilities").then(function (r) {
      caps.loading = false;
      if (r.data && r.data.status === "ok") {
        caps.loaded = true;
        caps.text = JSON.stringify(r.data.capabilities || {}, null, 2);
      } else {
        caps.loadError = errorText(r.data);
      }
      renderPrompts();
    });
  }

  function confirmSaveCaps() {
    var caps = S.prompts.caps;
    var parsed;
    try {
      parsed = JSON.parse(caps.text);
    } catch (e) {
      caps.problems = ["JSON invalide : " + e.message];
      renderPrompts();
      return;
    }
    caps._parsed = parsed;
    openConfirm({
      title: "Enregistrer les capacités ?",
      bodyHtml: "Le fichier <span class=\"mono\">capabilities.json</span> sera validé puis écrit (avec sauvegarde du précédent). " +
        "Une validation refusée n\'écrit rien et affiche les problèmes.",
      confirmLabel: "Valider et enregistrer",
      onConfirm: saveCaps
    });
  }

  function saveCaps() {
    var caps = S.prompts.caps;
    caps.saving = true; caps.problems = [];
    renderPrompts();
    callApi("POST", "hub/capabilities", { confirm: true, capabilities: caps._parsed }).then(function (r) {
      caps.saving = false;
      if (r.data && r.data.status === "ok") {
        toast("Capacités enregistrées.");
      } else if (r.data && r.data.problems) {
        caps.problems = r.data.problems;
      } else {
        caps.problems = [errorText(r.data)];
      }
      renderPrompts();
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
  function fieldRaw(label, controlHtml) {
    return '<div class="afc-field"><span class="afc-field-label">' + esc(label) + '</span>' + controlHtml + '</div>';
  }
  function bindInput(id, cb, isChange) {
    var e = byId(id);
    if (!e) { return; }
    if (isChange) { e.onchange = function () { cb(this.value); }; }
    else { e.oninput = function () { cb(this.value); }; }
  }
  function countsLine(counts) {
    var order = ["PLANNED", "DONE", "SKIPPED", "MANUAL", "FAILED"];
    var parts = [];
    order.forEach(function (k) { if (counts[k]) { parts.push(counts[k] + " " + k); } });
    return parts.join("  -  ") || "aucune action";
  }
  function errorText(data) {
    if (!data) { return "erreur inconnue"; }
    if (data.messages && data.messages.length) { return data.messages.join(" ; "); }
    return data.error || "erreur inconnue";
  }

  /* ============================ tabs + theme + boot ============================ */

  function renderActive() {
    if (S.tab === "guided") { if (!S.guided.loaded) { loadGuidedCurrent(); } else { renderGuided(); } }
    else if (S.tab === "overview") { if (!S.overview.loaded) { loadOverview(); } else { renderOverview(); } }
    else if (S.tab === "probe") { renderProbe(); }
    else if (S.tab === "domain") { renderDomain(); }
    else if (S.tab === "prompts") { renderPrompts(); }
  }

  function selectTab(tab) {
    S.tab = tab;
    var tabs = byId("afcTabs");
    if (tabs) {
      tabs.querySelectorAll(".afc-tab").forEach(function (b) {
        b.classList.toggle("afc-tab--on", b.getAttribute("data-tab") === tab);
      });
    }
    renderActive();
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
    byId("afcTabs").querySelectorAll(".afc-tab").forEach(function (b) {
      b.onclick = function () { selectTab(b.getAttribute("data-tab")); };
    });
    // close modal on scrim click (outside the card)
    var scrim = byId("afcModalScrim");
    if (scrim) { scrim.onclick = function (ev) { if (ev.target === scrim) { closeModal(); } }; }
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") { closeModal(); }
    });

    selectTab("guided");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
