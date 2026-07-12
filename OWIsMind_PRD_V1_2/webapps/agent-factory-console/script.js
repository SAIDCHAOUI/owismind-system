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
    tab: "overview",
    theme: "light",
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
      path: "/owismind_hub/prompts/orchestrator_persona.md",
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
    return '<span class="afc-chip afc-chip--' + m.cls + '">' + m.txt + '</span>';
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

  function loadDatasets(cb) {
    if (S.datasets.loaded || S.datasets.loading) { if (cb) { cb(); } return; }
    S.datasets.loading = true;
    callApi("GET", "datasets").then(function (r) {
      S.datasets.loading = false;
      if (r.data && r.data.status === "ok") {
        S.datasets.loaded = true;
        S.datasets.list = r.data.datasets || [];
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
      '<p class="afc-sec-note">État du projet DSS et du Config &amp; Prompt Hub (/owismind_hub). ' +
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
          '</div>';
      });
      html += '</div>';
    }
    html += '</div>';

    html += '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="ovRefresh">' + I.refresh + 'Actualiser</button></div>';
    html += '</div>';
    setMain(html);
    if (byId("ovRefresh")) {
      byId("ovRefresh").onclick = function () { S.overview.loaded = false; loadOverview(); };
    }
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
    if (!d.plan && !d.planError && !d.execResult && !d.execError &&
        !(d.execActions && d.execActions.length)) {
      return false;
    }
    d.plan = null; d.planError = null;
    d.execResult = null; d.execError = null; d.execActions = [];
    return true;
  }

  /* bindInput for a domain-form field: update the form, then invalidate any stale
   * plan. Re-render only when the plan was actually cleared, restoring focus to the
   * field being edited so typing is never interrupted. */
  function domainField(id, cb, isChange) {
    bindInput(id, function (v) {
      cb(v);
      if (invalidateDomainPlan()) {
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
    domainField("dmDomain", function (v) { f.domain = v; });
    domainField("dmBaseSelect", function (v) { f.base_dataset = v; }, true);
    domainField("dmBaseName", function (v) { f.base_dataset = v; });
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
    bindInput("wzProfile", function (v) { w.profileDataset = v; }, true);
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
    callApi("POST", "plan", { spec: buildSpec(), wizard_config: wizardConfigForSend() }).then(function (r) {
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
        toast("Exécution terminée.");
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
    var payload = { confirm: true, profile_dataset: w.profileDataset,
                    base_dataset: S.domain.form.base_dataset || "",
                    domain: (S.domain.form.domain || "").trim() };
    if (withAnswers) { payload.answers = w.answers; }
    callApi("POST", "wizard/draft", payload).then(function (r) {
      if (!r.data || r.data.status !== "ok" || !r.data.job_id) {
        w.running = false; w.regenerating = false;
        w.error = errorText(r.data);
        renderDomainNow();
        return;
      }
      w.jobId = r.data.job_id;
      pollJob(w.jobId, null, function (result) {
        w.running = false; w.regenerating = false;
        w.config = result || {};
        // A usable new draft changes what Execute would apply, so any plan computed
        // before it is now stale: drop it (the Execute button hides until re-planned).
        // An error draft sends nothing, so it leaves an existing plan valid.
        if (wizardConfigForSend() !== undefined) { invalidateDomainPlan(); }
        renderDomainNow();
        toast("Brouillon généré.");
      }, function (err) {
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
      '<p class="afc-sec-note">Éditez un fichier de prompt du hub (/owismind_hub/prompts/...). ' +
      'L\'orchestrateur charge sa persona depuis orchestrator_persona.md ; les sous-agents peuvent charger ' +
      'un ajout prompts/&lt;domaine&gt;/understand_extra.md. Le chemin doit commencer par /owismind_hub/prompts/.</p>' +
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
    if (!/^\/owismind_hub\/prompts\//.test(pr.path)) {
      pr.loadError = "Le chemin doit commencer par /owismind_hub/prompts/";
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
    if (S.tab === "overview") { if (!S.overview.loaded) { loadOverview(); } else { renderOverview(); } }
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

    selectTab("overview");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
