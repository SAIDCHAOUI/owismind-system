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
 *   - Creation flows have no deletion step. The ONLY deletion path is the guided
 *     capability-removal run: server-side typed-domain confirmation, safe_delete
 *     identity gate, protected source dataset, one confirmed stage at a time.
 *
 * Long backend actions (probe / execute / wizard draft) run as background JOBS: the
 * POST returns a job_id, then we poll GET api/job/<id> until status is done or error.
 * The shell in body.html (<template id="afc-shell">) is cloned once into #afc; each
 * screen renders into #afcMain. Screens (S.tab): home ("Mes agents", the nominal
 * entry), run (the guided creation / removal journey: start form, rail + stage
 * card, success), and under "Avance": probe, expert (one-shot plan/execute), hub
 * (prompt + capabilities editors). French-only UI. Orange charter in style.css. */

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
    chevron: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 6l6 6-6 6"/></svg>',
    x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    arrowLeft: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 12H5M11 6l-6 6 6 6"/></svg>'
  };

  /* ============================ state ============================ */

  var S = {
    tab: "home",
    theme: "light",
    // UI-only state that must survive the polling re-renders of #afcMain:
    // open <details> per key, the past stage viewed from the rail, last Avance tab.
    ui: { details: {}, viewStage: null, lastAdvanced: "probe" },
    // Guided run screen ("Parcours", server-persisted run)
    guided: {
      loaded: false, loading: false, error: null, run: null,
      starting: false, startError: null, startErrorCode: null, running: false, verifying: false,
      abandoning: false, actionError: null, liveActions: [],
      form: { domain: "", base_dataset: "", label_fr: "", label_en: "", lookup: "" },
      wizard: { running: false, jobId: null, config: null, answers: {}, error: null, reqId: 0 }
    },
    // Home screen ("Mes agents"): GET state (project, hub, settings, capabilities)
    overview: { loaded: false, loading: false, error: null, data: null },
    // shared: datasets list (fed to the pickers)
    datasets: { loaded: false, loading: false, error: null, list: [] },
    // Probe screen ("Sonde", Phase 0)
    probe: { running: false, jobId: null, report: null, error: null },
    // Expert mode ("Avance > Mode expert"): one-shot plan / execute
    domain: {
      form: { domain: "", sourceMode: "existing", base_dataset: "",
              connection: "SQL_owi", schema: "", table: "", catalog: "",
              label_fr: "", label_en: "", lookup: "" },
      planning: false, plan: null, planError: null,
      executing: false, execJobId: null, execActions: [], execResult: null, execError: null,
      wizard: { profileDataset: "", running: false, jobId: null, config: null,
                answers: {}, error: null, regenerating: false }
    },
    // Hub files ("Avance > Fichiers du hub"): prompt + capabilities editors
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
  function setMain(html) { var m = byId("afcMain"); if (m) { m.innerHTML = html; wireDetails(); } }

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
  /* ============================ technical details (persisted open state) ============================ */

  /* A collapsible "Details techniques" block. Its open state lives in S.ui.details
   * (keyed per screen/stage) because the job polling re-renders #afcMain every
   * 1.5s and would otherwise close it under the user's eyes. */
  function detailsBlock(key, summary, innerHtml, defaultOpen) {
    var stored = S.ui.details[key];
    var open = (stored === undefined) ? !!defaultOpen : !!stored;
    return '<details class="afc-details" data-details-key="' + esc(key) + '"' + (open ? " open" : "") + '>' +
      '<summary><span class="afc-details-chev">' + I.chevron + '</span>' +
      '<span class="afc-mlabel">' + esc(summary || "Détails techniques") + '</span></summary>' +
      '<div class="afc-details-body">' + innerHtml + '</div></details>';
  }

  function wireDetails() {
    Array.prototype.forEach.call(document.querySelectorAll("#afcMain details[data-details-key]"), function (d) {
      d.addEventListener("toggle", function () {
        S.ui.details[d.getAttribute("data-details-key")] = d.open;
      });
    });
  }

  /* ============================ page header ============================ */

  /* The shell header (eyebrow + H1 + title-bar) names the current screen; the
   * optional action slot (right of the H1) only carries the home CTA. */
  function setHeader(eyebrow, title, actionHtml) {
    var e = byId("afcEyebrow"); var t = byId("afcTitle"); var a = byId("afcHeaderAction");
    if (e) { e.textContent = eyebrow || ""; }
    if (t) { t.textContent = title || ""; }
    if (a) { a.innerHTML = actionHtml || ""; }
  }

  /* ============================ derived names (mirror of DomainSpec) ============================ */

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

  /* Every DSS / hub name the factory derives from a spec (spec.py DomainSpec).
   * Pure function: placeholders stand in for empty fields so the live preview of
   * the start form always reads as a sentence. */
  function derivedNames(spec) {
    spec = spec || {};
    var domain = String(spec.domain || "").trim();
    var base = String(spec.base_dataset || "").trim();
    var title = titleNoUnderscore(domain);
    var d = domain || "<domaine>";
    var b = base || "<dataset>";
    var t = title || "<Domaine>";
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
      generated: "generated/" + t + "_expert.py"
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
      obj("Zone Flow", n.zone, "Flow"),
      obj("Dataset", n.profile, "Flow, zone"),
      obj("Dataset", n.valueIndex, "Flow, zone"),
      obj("Dataset", n.valueCatalog, "Flow, zone"),
      obj("Recette", "compute_" + n.profile, "Flow, zone"),
      obj("Recette", "compute_" + n.valueIndex, "Flow, zone"),
      obj("Recette", "compute_" + n.valueCatalog, "Flow, zone"),
      obj("Scénario", n.scenario, "Scénarios"),
      obj("Modèle sémantique", n.model, "Agents & GenAI", c.model_id),
      obj("Outil", n.tool, "Agents & GenAI, Tools", c.tool_id),
      obj("Code Agent", n.agent, "Agents & GenAI, Agents", c.agent_id),
      obj("Entrée de registre", n.capability, "Hub, capabilities.json")
    ];
  }

  function mono(text) { return '<span class="mono">' + esc(text) + '</span>'; }

  /* ============================ stage microcopy (front-only, STAGE_UX) ============================ */

  var PHASES_CREATE = [
    { label: "Préparer", keys: ["preflight", "plan"] },
    { label: "Construire", keys: ["infra", "first_build", "profile_review"] },
    { label: "Créer l'expert", keys: ["wizard", "brain", "template", "agent_code", "code_agent"] },
    { label: "Activer", keys: ["capability", "smoke", "enable"] }
  ];
  var PHASES_REMOVAL = [
    { label: "Inventaire", keys: ["inventory", "disable"] },
    { label: "Supprimer", keys: ["delete_tool", "delete_agent", "delete_model", "delete_scenario",
                                 "delete_recipes", "delete_datasets", "delete_zone"] },
    { label: "Nettoyer", keys: ["catalog_cleanup", "hub_cleanup"] },
    { label: "Vérifier", keys: ["final_check"] }
  ];

  var GUARANTEE = {
    create: "Rien n'est supprimé. Chaque création est idempotente : relancer est sans risque.",
    read: "Lecture seule : rien n'est créé ni supprimé dans DSS.",
    verify: "Je ne modifie rien : je lis DSS pour confirmer que c'est fait.",
    detach: "Rien n'est supprimé à cette étape."
  };

  /* One entry per server stage key. ctx = {spec, names, captured, removal,
   * inventory, key, label, stage}. sentence() returns HTML (values escaped);
   * objects() returns obj() rows; removalItems=true reads the server inventory
   * instead. A key missing here falls back on the server title/detail. */
  var STAGE_UX = {
    /* ---- creation ---- */
    preflight: {
      title: "Vérifier les prérequis", guarantee: "read", readOnly: true,
      sentence: function (c) {
        return "Je contrôle le hub, le dataset " + mono(c.names.base) +
          " (non partitionné) et l'absence de collision de noms. Rien n'est créé.";
      },
      primary: "Lancer la vérification", retry: "Relancer la vérification",
      modalTitle: function () { return "Relancer les vérifications ?"; },
      wait: "Quelques secondes."
    },
    plan: {
      title: "Simuler la création", guarantee: "read",
      sentence: function () {
        return "Je simule toute la création et je liste ce qui sera créé, sans rien toucher à DSS.";
      },
      objectsLabel: "Ce qui sera créé au fil du parcours",
      objects: function (c) { return createdObjects(c.names); },
      primary: "Simuler",
      modalTitle: function (c) { return "Simuler la création de " + c.label + " ?"; },
      wait: "Quelques secondes."
    },
    infra: {
      title: "Créer la structure Flow", guarantee: "create",
      sentence: function (c) {
        return "Je crée la zone " + mono(c.names.zone) +
          ", 3 datasets de connaissance, 3 recettes et le scénario de refresh.";
      },
      objects: function (c) { return createdObjects(c.names).slice(0, 8); },
      primary: "Créer la structure",
      modalTitle: function () { return "Créer 8 objets dans le Flow ?"; },
      wait: "Environ une minute."
    },
    first_build: {
      title: "Construire les connaissances", guarantee: "create",
      sentence: function (c) {
        return "Je lance le scénario " + mono(c.names.scenario) +
          " et j'attends son résultat : profil, index de valeurs, catalogue.";
      },
      objectsLabel: "Ce qui sera rempli",
      objects: function (c) {
        return [obj("Dataset", c.names.profile, "sera rempli"),
                obj("Dataset", c.names.valueIndex, "sera rempli"),
                obj("Dataset", c.names.valueCatalog, "sera rempli")];
      },
      primary: "Lancer le build",
      modalTitle: function () { return "Lancer le build des connaissances ?"; },
      modalNote: "Plusieurs minutes. Un run déjà en cours est repris, jamais doublé.",
      wait: "En général 2 à 10 minutes. Vous pouvez fermer cette page : le parcours reprend où il en est."
    },
    profile_review: {
      title: "Relire le profil", guarantee: "verify",
      sentence: function (c) {
        return "À vous : relire le dataset " + mono(c.names.profile) +
          " et corriger ce qui est faux via les overrides.";
      },
      objectsLabel: "Ce que je vérifie",
      objects: function (c) { return [obj("Dataset", c.names.profile, "existe")]; },
      modalTitle: function () { return "Vérifier la relecture ?"; },
      modalSentence: function (c) {
        return "Je vérifie que " + mono(c.names.profile) + " existe. Je ne modifie rien.";
      },
      wait: "Vérification..."
    },
    wizard: {
      title: "Décrire le modèle sémantique (IA)", guarantee: "verify",
      sentence: function () {
        return "L'IA rédige un brouillon de modèle sémantique à partir du profil (métadonnées " +
          "seulement, aucune ligne de données), vous répondez à ses questions, puis je vérifie " +
          "que le brouillon est enregistré dans le hub.";
      },
      objectsLabel: "Ce que je vérifie",
      objects: function (c) { return [obj("Brouillon", c.names.wizardConfig, "Hub")]; },
      modalTitle: function () { return "Vérifier le brouillon ?"; },
      modalSentence: function (c) {
        return "Je vérifie que le brouillon " + mono(c.names.wizardConfig) +
          " est enregistré dans le hub pour le dataset " + mono(c.names.base) + ".";
      },
      wait: "Rédaction en cours (environ 30 s à 1 min)."
    },
    brain: {
      title: "Créer le modèle et l'outil", guarantee: "create",
      sentence: function (c) {
        return "Je crée le modèle sémantique " + mono(c.names.model) +
          ", j'y applique le brouillon, je l'indexe et je crée l'outil " + mono(c.names.tool) + ".";
      },
      objects: function (c) { return createdObjects(c.names).slice(8, 10); },
      primary: "Créer le modèle et l'outil",
      modalTitle: function () { return "Créer le modèle et l'outil ?"; },
      wait: "1 à 3 minutes (indexation)."
    },
    template: {
      title: "Vérifier le moteur d'agent", guarantee: "read",
      sentence: function () { return "Je vérifie que le moteur d'agent (template) est présent dans le hub."; },
      objectsLabel: "Ce que je vérifie",
      objects: function () { return [obj("Fichier", "templates/dataset_expert.py", "Hub")]; },
      primary: "Vérifier",
      modalTitle: function () { return "Vérifier le moteur ?"; },
      wait: "Une seconde."
    },
    agent_code: {
      title: "Générer le code de l'agent", guarantee: "create",
      sentence: function (c) {
        return "Je génère le code du sous-agent " + mono(c.names.agent) +
          " avec les bons identifiants et je crée le Code Agent si l'instance le permet " +
          "(sinon je dépose le fichier dans le hub pour un collage).";
      },
      objects: function (c) {
        return [obj("Code Agent", c.names.agent, "Agents & GenAI, Agents (si l'instance le permet)"),
                obj("Fichier", c.names.generated, "Hub (sinon)")];
      },
      primary: "Générer le code",
      modalTitle: function () { return "Générer le code de l'agent ?"; },
      wait: "Quelques secondes."
    },
    code_agent: {
      title: "Créer le Code Agent", guarantee: "verify",
      sentence: function (c) {
        return "À vous : créer le Code Agent " + mono(c.names.agent) +
          " (env 3.11) et y coller le code généré. Ensuite je vérifie dans DSS.";
      },
      objectsLabel: "Ce que je vérifie",
      objects: function (c) { return [obj("Code Agent", c.names.agent, "existe (je note son id)")]; },
      modalTitle: function () { return "Vérifier le Code Agent ?"; },
      modalSentence: function () { return "Je retrouve l'agent par son nom et je note son id."; },
      wait: "Une à deux secondes."
    },
    capability: {
      title: "Enregistrer l'expert", guarantee: "create",
      sentence: function (c) {
        return "J'ajoute l'expert " + mono(c.names.capability) +
          " au registre du hub, DÉSACTIVÉ pour l'instant.";
      },
      objects: function (c) {
        return [obj("Entrée de registre", c.names.capability, "capabilities.json (sauvegarde auto du précédent)")];
      },
      primary: "Enregistrer",
      modalTitle: function () { return "Enregistrer l'expert dans le registre ?"; },
      wait: "Une seconde."
    },
    smoke: {
      title: "Tester l'expert", guarantee: "verify",
      sentence: function () {
        return "À vous : poser les 4 questions de test dans la webapp OWIsMind (NOUVELLE " +
          "conversation) et vérifier la timeline et le panneau Evidence.";
      },
      objectsLabel: "Ce que je vérifie",
      objects: function (c) {
        return [obj("Entrée de registre", c.names.capability, "toujours dans le registre")];
      },
      modalTitle: function () { return "Passer à l'activation ?"; },
      modalSentence: function (c) {
        return "Je vérifie que l'entrée " + mono(c.names.capability) + " est toujours dans le registre.";
      },
      wait: "Une seconde."
    },
    enable: {
      title: "Activer l'expert", guarantee: "create",
      sentence: function (c) {
        return "J'active l'expert dans le registre : l'orchestrateur gagne l'outil " +
          mono(c.names.orchestratorTool) + ".";
      },
      objectsLabel: "Ce qui change",
      objects: function (c) {
        return [obj("Registre", "enabled: true", c.names.capability),
                obj("Outil orchestrateur", c.names.orchestratorTool, "Orchestrateur")];
      },
      primary: "Activer l'expert",
      modalTitle: function (c) { return "Activer l'expert " + c.label + " ?"; },
      modalNote: "Après activation : re-sauvegarder l'orchestrateur dans DSS puis ouvrir une NOUVELLE conversation.",
      wait: "Une seconde."
    },

    /* ---- removal ---- */
    inventory: {
      title: "Inventorier", guarantee: "read", readOnly: true, readOnlyText: "Aucune suppression : lecture seule",
      sentence: function () { return "Je sonde ce qui existe réellement pour cet expert. Rien n'est supprimé."; },
      primary: "Inventorier", verifyLabel: "J'ai compris, continuer",
      modalTitle: function () { return "Continuer malgré les templates ?"; },
      wait: "Quelques secondes."
    },
    disable: {
      title: "Couper le routage", guarantee: "detach",
      sentence: function () {
        return "Je désactive l'expert dans le registre : l'orchestrateur cesse de lui envoyer des questions.";
      },
      objectsLabel: "Ce qui change",
      objects: function (c) { return [obj("Registre", "enabled: false", c.key)]; },
      primary: "Désactiver",
      modalTitle: function () { return "Désactiver l'expert ?"; },
      wait: "Une seconde."
    },
    delete_tool: {
      title: "Supprimer l'outil", removalItems: true,
      sentence: function () { return "Je supprime l'outil Semantic Model Query de ce domaine."; },
      primary: "Supprimer l'outil", wait: "Quelques secondes."
    },
    delete_agent: {
      title: "Supprimer le Code Agent", removalItems: true,
      sentence: function () { return "Je supprime le Code Agent de ce domaine."; },
      primary: "Supprimer le Code Agent", wait: "Quelques secondes."
    },
    delete_model: {
      title: "Supprimer le modèle sémantique", removalItems: true,
      sentence: function () { return "Je supprime le modèle sémantique de ce domaine."; },
      primary: "Supprimer le modèle", wait: "Quelques secondes."
    },
    delete_scenario: {
      title: "Supprimer le scénario", removalItems: true,
      sentence: function () { return "Je supprime le scénario de refresh."; },
      primary: "Supprimer le scénario", wait: "Quelques secondes."
    },
    delete_recipes: {
      title: "Supprimer les recettes", removalItems: true,
      sentence: function () { return "Je supprime les recettes de connaissance."; },
      primary: "Supprimer les recettes", wait: "Quelques secondes."
    },
    delete_datasets: {
      title: "Supprimer les datasets de connaissance", removalItems: true, showProtected: true,
      sentence: function () { return "Je supprime les datasets dérivés et leurs tables SQL (reconstructibles)."; },
      primary: "Supprimer les datasets", wait: "Quelques secondes."
    },
    delete_zone: {
      title: "Supprimer la zone Flow", removalItems: true,
      sentence: function () { return "Je supprime la zone si elle est vide, sinon je la laisse."; },
      primary: "Supprimer la zone", wait: "Quelques secondes."
    },
    catalog_cleanup: {
      title: "Nettoyer le catalogue partagé",
      sentence: function () {
        return "Je supprime les lignes de cet expert dans le catalogue commun (SQL paramétré).";
      },
      objects: function (c) { return [obj("Lignes", "capability_key = " + c.key, "Catalogue partagé")]; },
      primary: "Nettoyer",
      modalTitle: function () { return "Nettoyer le catalogue ?"; },
      wait: "Quelques secondes."
    },
    hub_cleanup: {
      title: "Nettoyer le hub",
      sentence: function () {
        return "Je supprime la config wizard, les prompts, le code généré, puis l'entrée du registre (sauvegarde auto).";
      },
      objects: function (c) {
        var paths = (c.inventory && c.inventory.hub_paths) || [];
        var rows = paths.map(function (p) { return obj("Fichier du hub", p, "Hub"); });
        rows.push(obj("Entrée de registre", c.key, "capabilities.json"));
        return rows;
      },
      primary: "Nettoyer le hub",
      modalTitle: function () { return "Nettoyer le hub ?"; },
      wait: "Quelques secondes."
    },
    final_check: {
      title: "Vérifier que tout est parti", guarantee: "read", readOnly: true,
      readOnlyText: "Aucune suppression : lecture seule",
      sentence: function () { return "Je re-sonde l'absence de chaque objet."; },
      primary: "Vérifier",
      modalTitle: function () { return "Lancer la vérification finale ?"; },
      wait: "Quelques secondes."
    }
  };

  /* Removal stages whose launch actually deletes DSS objects: their confirm
     modal repeats the exact deletion list and uses the danger style, so the
     operator validates WHAT will be deleted, not just "run the stage". */
  var REMOVAL_DANGER_STAGES = {
    delete_tool: 1, delete_agent: 1, delete_model: 1, delete_scenario: 1,
    delete_recipes: 1, delete_datasets: 1, delete_zone: 1,
    catalog_cleanup: 1, hub_cleanup: 1
  };

  /* Everything the stage renderers need, for a creation OR a removal run. */
  function stageCtx(run) {
    var state = (run && run.state) || {};
    var removal = state.removal || null;
    var spec = state.spec || {};
    var label;
    if (removal) {
      var entry = removal.entry || {};
      spec = { domain: entry.domain || run.domain || "", base_dataset: entry.lookup_dataset || "" };
      label = entry.label_fr || spec.domain;
    } else {
      label = spec.label_fr || spec.domain || run.domain || "";
    }
    var names = derivedNames(spec);
    return {
      run: run, spec: spec, names: names, captured: state.captured || {},
      removal: removal, inventory: (removal && removal.inventory) || null,
      key: removal ? (removal.capability_key || names.capability) : names.capability,
      label: label || names.domain
    };
  }

  function isRemovalRun(run) { return !!(run && run.state && run.state.removal); }

  function stageTitle(key, stage) {
    var ux = STAGE_UX[key];
    return (ux && ux.title) || (stage && stage.title_fr) || key;
  }

  /* The object rows of a stage: the server inventory for a removal deletion
   * stage, the client-derived names otherwise. */
  function stageObjects(key, ctx) {
    var ux = STAGE_UX[key];
    if (!ux) { return []; }
    if (ux.removalItems) {
      var items = ((ctx.inventory && ctx.inventory.stages) || {})[key] || [];
      return items.map(function (it) {
        return obj(it.kind_fr || "", it.name || "", it.where_fr || "", it.id || "", it.note_fr || "");
      });
    }
    return ux.objects ? (ux.objects(ctx) || []) : [];
  }

  function stageObjectsLabel(key, ctx) {
    var ux = STAGE_UX[key] || {};
    if (ux.objectsLabel) { return ux.objectsLabel; }
    return ctx.removal ? "Ce qui sera supprimé" : "Ce qui sera créé";
  }

  /* A removal deletion stage whose inventory is empty: the server will skip it. */
  function isEmptyRemovalStage(key, ctx) {
    var ux = STAGE_UX[key];
    return !!(ctx.removal && ux && ux.removalItems && ctx.inventory && !stageObjects(key, ctx).length);
  }

  function objectsList(items, removalStyle, protectedItems) {
    var rows = items.map(function (o) {
      return '<li class="obj">' +
        '<span class="obj-mark' + (removalStyle ? " obj-mark--remove" : "") + '"></span>' +
        '<span class="obj-kind">' + esc(o.kind) + '</span>' +
        '<span class="obj-name mono">' + esc(o.name) +
        (o.id ? ' <span class="obj-id">' + esc(o.id) + '</span>' : "") +
        (o.note ? '<span class="obj-note">' + esc(o.note) + '</span>' : "") + '</span>' +
        '<span class="obj-where">' + esc(o.where) + '</span></li>';
    }).join("");
    (protectedItems || []).forEach(function (p) {
      rows += '<li class="obj obj--protected"><span class="obj-mark obj-mark--none"></span>' +
        '<span class="obj-protected">Jamais touché : <span class="mono">' + esc(p.name || "") + '</span>' +
        (p.kind_fr ? " (" + esc(p.kind_fr) + ")" : "") + '</span></li>';
    });
    return '<ul class="objects">' + rows + '</ul>';
  }

  /* Objects block with its micro-label, or the read-only line when there is
   * nothing to create / delete. */
  function stageObjectsBlock(key, ctx) {
    var ux = STAGE_UX[key];
    if (!ux) { return ""; }
    var items = stageObjects(key, ctx);
    var prot = (ux.showProtected && ctx.inventory) ? (ctx.inventory.protected || []) : [];
    if (ux.readOnly) {
      return '<div class="stage-block"><p class="objects-empty">' +
        esc(ux.readOnlyText || "Aucune création : lecture seule") + '</p></div>';
    }
    if (ux.removalItems && ctx.inventory && !items.length) {
      return '<div class="stage-block"><p class="objects-empty">Rien à supprimer : déjà absent.</p>' +
        (prot.length ? objectsList([], true, prot) : "") + '</div>';
    }
    if (!items.length && !prot.length) { return ""; }
    var removalStyle = !!(ctx.removal && REMOVAL_DANGER_STAGES[key] === 1);
    return '<div class="stage-block"><p class="afc-mlabel">' + esc(stageObjectsLabel(key, ctx)) +
      (items.length ? " (" + items.length + ")" : "") + '</p>' + objectsList(items, removalStyle, prot) + '</div>';
  }

  function stageSentence(key, ctx, stage) {
    var ux = STAGE_UX[key];
    if (ux && ux.sentence) { return ux.sentence(ctx); }
    return esc((stage && stage.detail_fr) || "");
  }

  function guaranteeLine(key, ctx) {
    var ux = STAGE_UX[key] || {};
    if (ctx.removal && REMOVAL_DANGER_STAGES[key] === 1) {
      var base = ctx.names.base;
      return "Irréversible. Le dataset source " + base + " n'est jamais touché.";
    }
    return GUARANTEE[ux.guarantee] || "";
  }

  /* Display status of a stage (front-only "skipped" = done by precheck). */
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

  function guidedStageChip(status) {
    var map = {
      pending: { cls: "pending", txt: "À venir" },
      ready: { cls: "ready", txt: "À faire" },
      running: { cls: "running", txt: "En cours" },
      waiting_user: { cls: "waiting", txt: "À vous de jouer" },
      done: { cls: "done", txt: "Terminée" },
      skipped: { cls: "skipped", txt: "Déjà faite" },
      failed: { cls: "failed", txt: "Échec" }
    };
    var m = map[status] || map.pending;
    return '<span class="afc-chip gd-status gd-status--' + m.cls + '">' + esc(m.txt) + '</span>';
  }

  /* Phases of a run, built from its stage_order so an unknown (future) stage key
   * still renders, grouped under "Autres". */
  function runPhases(run) {
    var order = (run.state && run.state.stage_order) || [];
    var model = isRemovalRun(run) ? PHASES_REMOVAL : PHASES_CREATE;
    var seen = {};
    var phases = [];
    model.forEach(function (p) {
      var keys = p.keys.filter(function (k) { return order.indexOf(k) !== -1; });
      keys.forEach(function (k) { seen[k] = 1; });
      if (keys.length) { phases.push({ label: p.label, keys: keys }); }
    });
    var rest = order.filter(function (k) { return !seen[k]; });
    if (rest.length) { phases.push({ label: "Autres", keys: rest }); }
    return phases;
  }

  function stagePosition(run, key) {
    var order = (run.state && run.state.stage_order) || [];
    var phases = runPhases(run);
    var phaseLabel = "";
    phases.forEach(function (p) { if (p.keys.indexOf(key) !== -1) { phaseLabel = p.label; } });
    return { index: order.indexOf(key) + 1, total: order.length, phase: phaseLabel };
  }

  function stageEyebrow(run, key) {
    var pos = stagePosition(run, key);
    return "Étape " + pos.index + " sur " + pos.total + (pos.phase ? " · " + pos.phase : "");
  }

  /* ============================ screen: parcours (guided run) ============================ */

  function guidedErrorText(data) {
    var map = {
      confirmation_required: "La confirmation est requise.",
      invalid_spec: "Les informations du domaine sont invalides.",
      active_run_exists: "Un parcours est déjà en cours.",
      busy: "Une opération de l'usine est déjà en cours. Réessayez dans un instant.",
      server_error: "Le serveur n'a pas pu terminer l'opération.",
      unknown_run: "Ce parcours est introuvable.",
      run_not_active: "Ce parcours n'est plus actif.",
      stage_not_runnable: "Cette étape ne peut pas être lancée dans son état actuel.",
      stage_not_verifiable: "Cette étape ne peut pas être vérifiée dans son état actuel.",
      too_many_jobs: "Trop de tâches sont enregistrées côté serveur. Réessayez plus tard.",
      storage_not_configured: "Le stockage SQL du parcours guidé n'est pas configuré.",
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
    S.ui.viewStage = null;
    if (!run || run.run_id !== previousId) { resetGuidedWizard(); }
  }

  function isActiveRun() {
    return !!(S.guided.run && S.guided.run.status === "active");
  }

  /* Re-render whichever screen shows guided state: the run screen itself, or
   * the home screen (its resume banner and CTA depend on the active run). */
  function renderGuided() {
    syncNav();
    if (S.tab === "run") { renderRun(); }
    else if (S.tab === "home") { renderHome(); }
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

  function backToHome() {
    S.overview.loaded = false;
    selectTab("home");
  }

  function backLink() {
    return '<button class="afc-link afc-back" id="gdBackHome">' + I.arrowLeft + 'Mes agents</button>';
  }

  function renderRun() {
    if (S.tab !== "run") { return; }
    var g = S.guided;
    var html = '<div class="afc-panel afc-panel--wide">' + backendBanner();

    if (g.loading && !g.loaded) {
      setHeader("OWIsMind · Usine à agents", "Parcours");
      html += '<p class="afc-loading">Je cherche un parcours en cours...</p></div>';
      setMain(html);
      return;
    }
    if (g.error && !g.loaded) {
      setHeader("OWIsMind · Usine à agents", "Parcours");
      html += backLink() +
        '<div class="afc-note afc-note--error">Impossible de charger le parcours : ' + esc(g.error) + '</div>' +
        '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="gdRetry">' +
        I.refresh + 'Réessayer</button></div></div>';
      setMain(html);
      if (byId("gdRetry")) { byId("gdRetry").onclick = refreshGuidedCurrent; }
      wireBackHome();
      return;
    }

    if (!g.run) {
      if (!S.datasets.loaded && !S.datasets.loading) {
        loadDatasets(function () { if (S.tab === "run" && !S.guided.run) { renderRun(); } });
      }
      setHeader("Ajouter un agent", "Décrire l'agent");
      html += backLink() + renderStartForm() + '</div>';
      setMain(html);
      wireGuidedStartForm();
      wireBackHome();
      return;
    }

    var ctx = stageCtx(g.run);
    var removal = !!ctx.removal;
    setHeader(removal ? "Retrait d'un agent · " + ctx.names.domain : "Création de l'expert · " + ctx.names.domain,
      ctx.label);

    if (g.run.status === "done") {
      html += backLink() + (removal ? renderRemovalSuccess(g.run, ctx) : renderSuccess(g.run, ctx)) + '</div>';
      setMain(html);
      if (byId("gdHome")) { byId("gdHome").onclick = backToHome; }
      if (byId("gdNew")) { byId("gdNew").onclick = function () { newGuidedDomain(); }; }
      Array.prototype.forEach.call(document.querySelectorAll("#afcMain .afc-chk"), function (c) {
        c.onclick = function () { c.classList.toggle("on"); };
      });
      wireBackHome();
      return;
    }

    var viewKey = S.ui.viewStage;
    var viewStage = viewKey && g.run.state && g.run.state.stages && g.run.state.stages[viewKey];
    html += backLink() + '<div class="run-grid">' + renderRail(g.run) +
      '<div class="run-main">' +
      (viewStage && viewKey !== g.run.current_stage ? renderStageReadonly(g.run, viewKey) : renderStage(g.run)) +
      '</div></div></div>';
    setMain(html);
    wireGuidedRun();
    wireBackHome();
  }

  function wireBackHome() {
    if (byId("gdBackHome")) { byId("gdBackHome").onclick = backToHome; }
  }

  /* ---------- screen 0: describe the agent (start form + live preview) ---------- */

  function renderStartForm() {
    var g = S.guided;
    var f = g.form;
    var picker = S.datasets.loading
      ? '<p class="afc-loading gd-dataset-loading">Chargement des datasets...</p>'
      : '<select class="afc-select" id="gdBaseDataset">' + datasetOptions(f.base_dataset) + '</select>';
    var html = '<div class="start-grid"><div class="afc-card gd-start">' +
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
      field("Colonnes lookup (optionnel, séparées par des virgules)",
        inputEl("gdLookup", f.lookup, "ex. Account_name, Opportunity_name"),
        "Laissez vide pour utiliser toutes les colonnes texte autorisées.");

    if (S.datasets.error) {
      html += '<div class="afc-note afc-note--error">Liste des datasets indisponible : ' + esc(S.datasets.error) + '</div>';
    }
    if (g.startError) {
      html += '<div class="afc-note afc-note--error">Démarrage impossible : ' + esc(g.startError) + '</div>';
    }
    html += '<div class="afc-actions"><button class="afc-btn afc-btn--primary" id="gdStart"' +
      (g.starting ? " disabled" : "") + '>' + I.play +
      (g.starting ? "Démarrage..." : "Commencer le parcours") + '</button>';
    if (g.startError && g.startErrorCode === "active_run_exists") {
      html += '<button class="afc-btn afc-btn--ghost" id="gdResume">' +
        I.refresh + 'Reprendre le parcours en cours</button>';
    }
    html += '</div></div>';

    // Live preview of every name the run will create (updated in place on input).
    var n = derivedNames({ domain: f.domain, base_dataset: f.base_dataset });
    var keys = ["zone", "profile", "valueIndex", "valueCatalog", "recipeProfile", "recipeValueIndex",
                "recipeValueCatalog", "scenario", "model", "tool", "agent", "capability"];
    var rows = createdObjects(n).map(function (o, i) {
      return '<li class="obj"><span class="obj-mark"></span><span class="obj-kind">' + esc(o.kind) + '</span>' +
        '<span class="obj-name mono" data-name="' + keys[i] + '">' + esc(o.name) + '</span>' +
        '<span class="obj-where">' + esc(o.where) + '</span></li>';
    }).join("");
    html += '<aside class="start-preview"><p class="afc-mlabel">Ce qui sera créé (12)</p>' +
      '<ul class="objects objects--compact">' + rows + '</ul>' +
      '<p class="start-preview-foot">Rien n\'est créé avant l\'étape 3. Les noms se mettent à jour pendant la saisie.</p>' +
      '</aside></div>';
    return html;
  }

  /* Write the derived names into the preview WITHOUT re-rendering the form
   * (a re-render would steal the focus of the field being typed in). */
  function updateNamesPreview() {
    var f = S.guided.form;
    var n = derivedNames({ domain: f.domain, base_dataset: f.base_dataset });
    var values = {
      zone: n.zone, profile: n.profile, valueIndex: n.valueIndex, valueCatalog: n.valueCatalog,
      recipeProfile: "compute_" + n.profile, recipeValueIndex: "compute_" + n.valueIndex,
      recipeValueCatalog: "compute_" + n.valueCatalog, scenario: n.scenario, model: n.model,
      tool: n.tool, agent: n.agent, capability: n.capability
    };
    Array.prototype.forEach.call(document.querySelectorAll("#afcMain [data-name]"), function (el) {
      var v = values[el.getAttribute("data-name")];
      if (v !== undefined) { el.textContent = v; }
    });
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
    bindInput("gdDomain", function (v) { f.domain = v; updateNamesPreview(); });
    bindInput("gdBaseDataset", function (v) { f.base_dataset = v; updateNamesPreview(); }, true);
    bindInput("gdLabelFr", function (v) { f.label_fr = v; });
    bindInput("gdLabelEn", function (v) { f.label_en = v; });
    bindInput("gdLookup", function (v) { f.lookup = v; });
    if (byId("gdRefreshDatasets")) {
      byId("gdRefreshDatasets").onclick = function () {
        loadDatasets(function () { renderRun(); }, true);
        renderRun();
      };
    }
    if (byId("gdStart")) { byId("gdStart").onclick = confirmGuidedStart; }
    if (byId("gdResume")) { byId("gdResume").onclick = refreshGuidedCurrent; }
  }

  function confirmGuidedStart() {
    var spec = guidedStartSpec();
    var n = derivedNames(spec);
    openConfirm({
      title: "Démarrer la création de l'expert " + (spec.label_fr || spec.domain || "(sans nom)") + " ?",
      bodyHtml: '<p class="modal-sentence">Je crée un parcours persistant pour le domaine ' +
        mono(spec.domain || "(sans nom)") + ' sur le dataset ' + mono(spec.base_dataset || "(non choisi)") +
        ', puis je lance immédiatement les vérifications préalables (lecture seule).</p>' +
        '<p class="afc-mlabel modal-label">Ce qui sera créé au fil du parcours (12)</p>' +
        objectsList(createdObjects(n), false) +
        '<p class="modal-guarantee">Rien n\'est créé maintenant : chaque création vous sera présentée et confirmée étape par étape.</p>',
      confirmLabel: "Commencer le parcours",
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
        toast("Parcours démarré.");
      } else {
        g.startErrorCode = r.data && r.data.error;
        g.startError = guidedErrorText(r.data);
      }
      renderGuided();
    });
  }

  /* ---------- rail (vertical stepper grouped by phase) ---------- */

  function railMark(status, number) {
    if (status === "done") { return '<span class="rail-mark rail-mark--done">' + I.check + '</span>'; }
    if (status === "failed") { return '<span class="rail-mark rail-mark--failed">' + I.x + '</span>'; }
    return '<span class="rail-mark rail-mark--' + esc(status) + '">' + esc(number) + '</span>';
  }

  function renderRail(run) {
    var state = run.state || {};
    var stages = state.stages || {};
    var order = state.stage_order || [];
    var doneCount = 0;
    order.forEach(function (k) { if ((stages[k] || {}).status === "done") { doneCount += 1; } });
    var groups = runPhases(run).map(function (p, pi) {
      var rows = p.keys.map(function (key) {
        var stage = stages[key] || {};
        var status = stageDisplayStatus(run, key);
        var isCurrent = key === run.current_stage;
        var isPast = status === "done" || status === "skipped";
        var viewing = S.ui.viewStage === key && !isCurrent;
        var cls = "rail-step rail-step--" + status + (isCurrent ? " is-current" : "") + (viewing ? " is-viewing" : "");
        var clickable = isPast || isCurrent;
        return '<li><button class="' + cls + '"' + (clickable ? ' data-rail-key="' + esc(key) + '"' : " disabled") +
          (isCurrent ? ' aria-current="step"' : "") + '>' +
          railMark(isCurrent && status !== "failed" && status !== "running" ? "current" : status, order.indexOf(key) + 1) +
          '<span class="rail-title">' + esc(stageTitle(key, stage)) + '</span></button></li>';
      }).join("");
      return '<div class="rail-group"><p class="rail-phase">' + (pi + 1) + ' · ' + esc(p.label) + '</p>' +
        '<ol class="rail-steps">' + rows + '</ol></div>';
    }).join("");
    var pos = stagePosition(run, run.current_stage);
    var pct = order.length ? Math.round(doneCount * 100 / order.length) : 0;
    return '<nav class="rail" aria-label="Étapes du parcours">' + groups +
      '<div class="rail-foot"><span class="rail-count mono">Étape ' + pos.index + ' sur ' + pos.total + '</span>' +
      '<span class="rail-progress"><span style="width:' + pct + '%"></span></span></div></nav>';
  }

  /* ---------- stage card (current stage) ---------- */

  function problemsCard(problems) {
    if (!problems || !problems.length) { return ""; }
    return '<div class="stage-problems"><p class="stage-problems-title">À corriger avant de relancer</p><ul>' +
      problems.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join("") + '</ul></div>';
  }

  /* Split numbered server instructions ("1. ...\n2. ...") into a checklist. The
   * "C'est fait" line becomes the legend under the button. */
  function splitInstructions(text) {
    var raw = String(text || "").trim();
    var res = { intro: "", items: [], footer: "", raw: raw };
    if (!raw) { return res; }
    var parts = raw.split(/\n(?=\d+\.\s)/);
    if (parts.length <= 1) { return res; }
    parts.forEach(function (p, i) {
      if (i === 0 && !/^\d+\.\s/.test(p)) { res.intro = p.trim(); return; }
      var t = p.replace(/^\d+\.\s+/, "").trim();
      if (!t) { return; }
      if (/^Clique sur C'est fait/i.test(t) || t.indexOf("C'est fait") !== -1) { res.footer = t; return; }
      res.items.push(t);
    });
    return res;
  }

  function nl2br(text) { return esc(text).replace(/\n/g, "<br>"); }

  function checklistBlock(text) {
    var sp = splitInstructions(text);
    if (!sp.raw) { return ""; }
    if (sp.items.length <= 1) {
      return '<div class="stage-block"><p class="afc-mlabel">À faire dans DSS</p>' +
        '<div class="stage-manual-text">' + nl2br(sp.raw) + '</div></div>';
    }
    return '<div class="stage-block"><p class="afc-mlabel">À faire dans DSS</p>' +
      (sp.intro ? '<p class="stage-intro">' + nl2br(sp.intro) + '</p>' : "") +
      '<ol class="afc-todo">' + sp.items.map(function (t, i) {
        return '<li><span class="afc-todo-n mono">' + (i + 1) + '</span><span class="afc-todo-t">' + nl2br(t) + '</span></li>';
      }).join("") + '</ol></div>';
  }

  function progressBar() {
    return '<div class="afc-progress" role="progressbar" aria-label="En cours"><span></span></div>';
  }

  function progressList(actions) {
    if (!actions || !actions.length) { return ""; }
    return '<div class="stage-block"><p class="afc-mlabel">Avancement</p><ul class="afc-steps">' +
      actions.map(function (a) {
        return '<li>' + statusChip(a.status) + '<span class="afc-steps-step mono">' + esc(a.step) + '</span>' +
          '<span class="afc-steps-detail">' + esc(a.detail || "") + '</span></li>';
      }).join("") + '</ul></div>';
  }

  /* Technical details of a stage: raw server texts, full journal, ids. */
  function stageTechDetails(run, key, stage, journal, extraHtml) {
    var inner = '<dl class="afc-kv afc-kv--tight"><dt>Clé d\'étape</dt><dd>' + esc(key) + '</dd>' +
      '<dt>Run</dt><dd>' + esc(run.run_id || "") + '</dd>' +
      '<dt>Titre serveur</dt><dd>' + esc((stage && stage.title_fr) || "-") + '</dd></dl>';
    if (stage && stage.detail_fr) {
      inner += '<p class="afc-mlabel tech-label">Détail serveur</p><div class="tech-text">' + nl2br(stage.detail_fr) + '</div>';
    }
    if (stage && stage.instructions_fr) {
      inner += '<p class="afc-mlabel tech-label">Consignes serveur (texte brut)</p><div class="tech-text">' +
        nl2br(stage.instructions_fr) + '</div>';
    }
    inner += '<p class="afc-mlabel tech-label">Journal de l\'étape</p>' + actionsTable(journal);
    inner += extraHtml || "";
    return inner;
  }

  function abandonLink() {
    var g = S.guided;
    var run = g.run || {};
    var currentStage = run.state && run.state.stages && run.state.stages[run.current_stage];
    var disabled = g.abandoning || g.running || g.verifying || g.wizard.running ||
      (currentStage && currentStage.status === "running");
    return '<button class="afc-link afc-link--abandon" id="gdAbandon"' + (disabled ? " disabled" : "") + '>' +
      (g.abandoning ? "Abandon..." : "Abandonner le parcours") + '</button>';
  }

  function renderStage(run) {
    var g = S.guided;
    var w = g.wizard;
    var state = run.state || {};
    var stages = state.stages || {};
    var key = run.current_stage;
    var stage = stages[key] || null;
    if (!stage) {
      return '<div class="afc-note afc-note--error">L\'étape courante est absente du run.</div>' +
        '<div class="stage-actions">' + abandonLink() + '</div>';
    }
    var ctx = stageCtx(run);
    var ux = STAGE_UX[key] || null;
    var status = g.running ? "running" : stage.status;
    var chipStatus = (status === "done" && isSkippedStage(stage)) ? "skipped" : status;
    var removal = !!ctx.removal;
    var dangerous = removal && REMOVAL_DANGER_STAGES[key] === 1;
    var emptyRemoval = isEmptyRemovalStage(key, ctx);
    var isWizard = key === "wizard" && status === "waiting_user";

    var html = '<section class="stage' + (removal ? " stage--removal" : "") + '">' +
      '<div class="stage-head"><div class="stage-head-text">' +
      '<p class="stage-eyebrow">' + esc(stageEyebrow(run, key)) + '</p>' +
      '<h2 class="stage-title">' + esc(stageTitle(key, stage)) + '</h2></div>' +
      guidedStageChip(chipStatus) + '</div>';

    var showBar = status === "running" || (isWizard && w.running);
    if (showBar) { html += progressBar(); }

    // An empty removal stage would otherwise announce a deletion it will not do.
    var sentence = emptyRemoval
      ? "Rien à supprimer pour cette étape : déjà absent, je la passe."
      : stageSentence(key, ctx, stage);
    html += '<div class="stage-block"><p class="afc-mlabel">Ce qui va se passer</p>' +
      '<p class="stage-sentence">' + sentence + '</p>';
    if (status === "running" && ux && ux.wait) {
      html += '<p class="stage-wait">' + esc(ux.wait) + '</p>';
    }
    if (isWizard && w.running && ux && ux.wait) {
      html += '<p class="stage-wait">' + esc(ux.wait) + '</p>';
    }
    html += '</div>';

    if (g.actionError) {
      html += '<div class="afc-note afc-note--error">Opération impossible : ' + esc(g.actionError) + '</div>';
    }

    // Removal inventory with template conflicts: explicit orange warning.
    if (key === "inventory" && status === "waiting_user") {
      html += '<div class="afc-note afc-note--warn">Certains objets de cet expert servent de modèles à l\'usine. ' +
        'Lisez l\'avertissement ci-dessous avant de continuer.</div>';
    }

    if (status !== "running") { html += stageObjectsBlock(key, ctx); }
    html += problemsCard(stage.problems);

    var journal = (g.running && g.liveActions.length) ? g.liveActions : (stage.journal || []);
    var techExtra = "";
    var actions = "";
    var legend = "";

    if (status === "ready" || status === "failed") {
      var label = status === "failed" ? ((ux && ux.retry) || "Relancer")
        : (emptyRemoval ? "Passer" : ((ux && ux.primary) || "Lancer"));
      var cls = emptyRemoval ? "afc-btn afc-btn--ghost"
        : (dangerous ? "afc-btn afc-btn--danger-solid" : "afc-btn afc-btn--primary");
      actions = '<button class="' + cls + '" id="gdRunStage"' + (g.running ? " disabled" : "") + '>' +
        (dangerous && !emptyRemoval ? "" : I.play) + esc(label) + '</button>';
    } else if (status === "waiting_user" && isWizard) {
      html += renderGuidedWizard(run);
      if (w.config && !w.running) {
        techExtra = '<p class="afc-mlabel tech-label">Brouillon du modèle (JSON)</p>' +
          '<div class="afc-actions afc-actions--tight">' + copyButton("gdWizardCopy", "Copier le JSON") + '</div>' +
          '<pre class="afc-pre">' + esc(JSON.stringify(w.config, null, 2)) + '</pre>';
      }
      if (w.running) {
        actions = '<button class="afc-btn afc-btn--primary" disabled>Rédaction...</button>';
      } else if (!w.config) {
        actions = '<button class="afc-btn afc-btn--primary" id="gdWizardDraft">' + I.play + 'Rédiger le brouillon (IA)</button>' +
          '<button class="afc-btn afc-btn--ghost" id="gdVerify"' + (g.verifying ? " disabled" : "") + '>' +
          (g.verifying ? "Vérification..." : "C'est fait, vérifier") + '</button>';
      } else {
        actions = '<button class="afc-btn afc-btn--primary" id="gdVerify"' + (g.verifying ? " disabled" : "") + '>' +
          I.check + (g.verifying ? "Vérification..." : "Vérifier et continuer") + '</button>' +
          '<button class="afc-btn afc-btn--ghost" id="gdWizardRedraft">Re-rédiger avec mes réponses</button>';
      }
      legend = "Quand c'est fait, je vérifie dans DSS avant de passer à la suite.";
    } else if (status === "waiting_user") {
      html += checklistBlock(stage.instructions_fr);
      actions = '<button class="afc-btn afc-btn--primary" id="gdVerify"' +
        (g.verifying || w.running ? " disabled" : "") + '>' + I.check +
        (g.verifying ? "Vérification..." : ((ux && ux.verifyLabel) || "C'est fait, vérifier")) + '</button>';
      legend = splitInstructions(stage.instructions_fr).footer
        ? "Quand c'est fait, je vérifie dans DSS avant de passer à la suite."
        : (key === "inventory" ? "" : "Quand c'est fait, je vérifie dans DSS avant de passer à la suite.");
    } else if (status === "running") {
      html += progressList(journal);
      actions = '<button class="afc-btn afc-btn--primary" disabled>En cours...</button>';
      if (!g.running) {
        actions += '<button class="afc-btn afc-btn--ghost afc-btn--sm" id="gdRefreshRun">' +
          I.refresh + 'Actualiser l\'état</button>';
      }
    } else if (status === "pending") {
      html += '<div class="afc-note afc-note--info">Cette étape attend la fin de l\'étape courante.</div>';
    }

    html += '<div class="stage-actions">' + actions + abandonLink() + '</div>';
    if (legend) { html += '<p class="stage-legend">' + esc(legend) + '</p>'; }

    html += detailsBlock("stage:" + (run.run_id || "") + ":" + key, "Détails techniques",
      stageTechDetails(run, key, stage, journal, techExtra), status === "failed");
    html += '</section>';
    return html;
  }

  /* Read-only panel of a past stage (opened from the rail). */
  function renderStageReadonly(run, key) {
    var stage = ((run.state || {}).stages || {})[key] || {};
    var ctx = stageCtx(run);
    var status = stageDisplayStatus(run, key);
    var html = '<section class="stage stage--readonly">' +
      '<div class="stage-head"><div class="stage-head-text">' +
      '<p class="stage-eyebrow">' + esc(stageEyebrow(run, key)) + '</p>' +
      '<h2 class="stage-title">' + esc(stageTitle(key, stage)) + '</h2></div>' +
      guidedStageChip(status) + '</div>' +
      '<div class="stage-block"><p class="afc-mlabel">Ce qui s\'est passé</p>' +
      '<p class="stage-sentence">' + stageSentence(key, ctx, stage) + '</p></div>' +
      stageObjectsBlock(key, ctx) +
      '<div class="stage-block"><p class="afc-mlabel">Journal</p>' + actionsTable(stage.journal || []) + '</div>' +
      '<div class="stage-actions"><button class="afc-link" id="gdBackCurrent">' + I.arrowLeft +
      'Revenir à l\'étape en cours</button></div>' +
      detailsBlock("view:" + (run.run_id || "") + ":" + key, "Détails techniques",
        stageTechDetails(run, key, stage, stage.journal || [], ""), false) +
      '</section>';
    return html;
  }

  /* ---------- wizard sub-flow (stage "wizard") ---------- */

  function renderGuidedWizard(run) {
    var w = S.guided.wizard;
    var spec = (run.state && run.state.spec) || {};
    var profile = (spec.base_dataset || "") + "_profile";
    var html = '<div class="stage-block gd-wizard"><p class="afc-mlabel">Brouillon IA</p>' +
      '<p class="stage-help">Le brouillon est rédigé à partir du profil ' + mono(profile) +
      ' et enregistré automatiquement dans le hub.</p>';
    if (w.error) {
      html += '<div class="afc-note afc-note--error">Brouillon impossible : ' + esc(w.error) + '</div>';
    }
    if (w.config && !w.running) {
      var questions = w.config.questions || [];
      if (questions.length) {
        html += '<div class="gd-questions"><p class="afc-mlabel">Questions de clarification (' + questions.length + ')</p>';
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
        html += '<div class="afc-note afc-note--info">Le brouillon n\'a besoin d\'aucune précision.</div>';
      }
    } else if (!w.running && !w.config) {
      html += '<p class="stage-help">Un brouillon valide existe déjà dans le hub ? Cliquez directement sur « C\'est fait, vérifier ».</p>';
    }
    html += '</div>';
    return html;
  }

  /* ---------- success screens ---------- */

  function nextSteps(domainLabel) {
    return '<div class="stage-block success-next"><p class="afc-mlabel">Et maintenant</p>' +
      '<div class="success-checks">' +
      '<span class="afc-chk"><span class="box">' + I.check + '</span>Re-sauvegarder l\'orchestrateur dans DSS ' +
      '(le registre est chargé au démarrage du process)</span>' +
      '<span class="afc-chk"><span class="box">' + I.check + '</span>' + esc(domainLabel) + '</span>' +
      '</div></div>';
  }

  function renderSuccess(run, ctx) {
    return '<section class="stage success">' +
      '<p class="stage-eyebrow">Parcours terminé</p>' +
      '<h2 class="success-title">L\'expert ' + esc(ctx.label) + ' est actif</h2>' +
      '<p class="stage-sentence">L\'orchestrateur sait désormais router les questions ' + mono(ctx.names.domain) + '.</p>' +
      '<div class="stage-block"><p class="afc-mlabel">Ce qui a été créé</p>' +
      objectsList(createdObjects(ctx.names, ctx.captured), false) + '</div>' +
      nextSteps("Ouvrir une NOUVELLE conversation dans OWIsMind et poser une question " + ctx.names.domain) +
      '<div class="stage-actions"><button class="afc-btn afc-btn--primary" id="gdHome">Retour à mes agents</button>' +
      '<button class="afc-btn afc-btn--ghost" id="gdNew">' + I.plus + 'Ajouter un autre agent</button></div>' +
      '</section>';
  }

  function renderRemovalSuccess(run, ctx) {
    var inv = ctx.inventory || {};
    var items = [];
    PHASES_REMOVAL[1].keys.forEach(function (k) { items = items.concat(stageObjects(k, ctx)); });
    (inv.hub_paths || []).forEach(function (p) { items.push(obj("Fichier du hub", p, "Hub")); });
    items.push(obj("Entrée de registre", ctx.key, "capabilities.json"));
    return '<section class="stage success">' +
      '<p class="stage-eyebrow">Parcours terminé</p>' +
      '<h2 class="success-title">L\'expert ' + esc(ctx.names.domain) + ' est retiré</h2>' +
      '<p class="stage-sentence">L\'orchestrateur ne lui envoie plus de questions. Le dataset source ' +
      mono(ctx.names.base) + ' est intact.</p>' +
      '<div class="stage-block"><p class="afc-mlabel">Ce qui a été supprimé (inventaire)</p>' +
      objectsList(items, true, inv.protected || []) + '</div>' +
      nextSteps("Ouvrir une NOUVELLE conversation dans OWIsMind") +
      '<div class="stage-actions"><button class="afc-btn afc-btn--primary" id="gdHome">Retour à mes agents</button></div>' +
      '</section>';
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
    if (byId("gdWizardCopy")) {
      wireCopy("gdWizardCopy", function () { return JSON.stringify(S.guided.wizard.config, null, 2); });
    }
    if (byId("gdBackCurrent")) {
      byId("gdBackCurrent").onclick = function () { S.ui.viewStage = null; renderRun(); };
    }
    Array.prototype.forEach.call(document.querySelectorAll("#afcMain [data-rail-key]"), function (b) {
      b.onclick = function () {
        var k = b.getAttribute("data-rail-key");
        S.ui.viewStage = (S.guided.run && k === S.guided.run.current_stage) ? null : k;
        renderRun();
      };
    });
    Array.prototype.forEach.call(document.querySelectorAll(".gd-wizard-answer"), function (elm) {
      elm.oninput = function () {
        S.guided.wizard.answers[elm.getAttribute("data-qid")] = elm.value;
      };
    });
  }

  /* Confirm body shared by run/verify modals: the "what will happen" sentence,
   * the same object rows as the stage card, and a guarantee line. */
  function stageModalBody(run, key, sentenceHtml) {
    var ctx = stageCtx(run);
    var ux = STAGE_UX[key] || {};
    var html = '<p class="modal-sentence">' + sentenceHtml + '</p>';
    if (ux.modalNote) { html += '<p class="modal-note">' + esc(ux.modalNote) + '</p>'; }
    var items = stageObjects(key, ctx);
    var prot = (ux.showProtected && ctx.inventory) ? (ctx.inventory.protected || []) : [];
    if (!ux.readOnly && (items.length || prot.length)) {
      html += '<p class="afc-mlabel modal-label">' + esc(stageObjectsLabel(key, ctx)) +
        (items.length ? " (" + items.length + ")" : "") + '</p>' +
        objectsList(items, !!(ctx.removal && REMOVAL_DANGER_STAGES[key] === 1), prot);
    } else if (ux.removalItems && ctx.inventory && !items.length) {
      html += '<p class="objects-empty">Rien à supprimer : déjà absent. Le serveur passera l\'étape.</p>';
    }
    var g = guaranteeLine(key, ctx);
    if (g) { html += '<p class="modal-guarantee">' + esc(g) + '</p>'; }
    return html;
  }

  function confirmGuidedStageRun() {
    var run = S.guided.run || {};
    var key = run.current_stage;
    var stage = run.state && run.state.stages && run.state.stages[key];
    var isRemoval = !!(run.state && run.state.removal);
    var dangerous = isRemoval && REMOVAL_DANGER_STAGES[key] === 1;
    var ctx = stageCtx(run);
    var ux = STAGE_UX[key] || null;
    var failed = !!(stage && stage.status === "failed");
    var count = stageObjects(key, ctx).length;
    var title;
    if (failed) {
      title = "Relancer : " + stageTitle(key, stage) + " ?";
    } else if (dangerous) {
      title = (ux && ux.modalTitle) ? ux.modalTitle(ctx)
        : (count ? "Supprimer " + count + (count > 1 ? " objets" : " objet") + " dans DSS ?" : "Passer cette étape ?");
    } else {
      title = (ux && ux.modalTitle) ? ux.modalTitle(ctx) : "Lancer cette étape ?";
    }
    var emptyRemoval = isEmptyRemovalStage(key, ctx);
    openConfirm({
      title: title,
      bodyHtml: stageModalBody(run, key, emptyRemoval
        ? "Rien à supprimer pour cette étape : déjà absent, je la passe."
        : stageSentence(key, ctx, stage)),
      danger: dangerous,
      confirmLabel: failed ? "Relancer" : (dangerous ? (count ? "Supprimer" : "Passer") : ((ux && ux.primary) || "Lancer")),
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
          stageOutcomeToast(stageKey, result.run);
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

  /* One toast per finished auto stage: success, activation, or failure. */
  function stageOutcomeToast(stageKey, run) {
    var st = run && run.state && run.state.stages && run.state.stages[stageKey];
    if (!st) { return; }
    if (st.status === "done") {
      toast(stageKey === "enable" ? "Expert activé." : "Étape terminée.");
    } else if (st.status === "failed") {
      toast("L'étape a échoué : lisez les points à corriger.");
    }
  }

  function refreshDatasetsAfterInfra(stageKey, run) {
    var infra = run && run.state && run.state.stages && run.state.stages.infra;
    if (stageKey === "infra" && infra && infra.status === "done") {
      loadDatasets(null, true);
    }
  }

  function confirmGuidedVerify() {
    var run = S.guided.run || {};
    var key = run.current_stage;
    var stage = run.state && run.state.stages && run.state.stages[key];
    var ctx = stageCtx(run);
    var ux = STAGE_UX[key] || null;
    var sentence = (ux && ux.modalSentence) ? ux.modalSentence(ctx)
      : "Je contrôle dans DSS que l'étape <b>" + esc(stageTitle(key, stage)) + "</b> est réellement terminée.";
    var body;
    if (key === "inventory") {
      body = '<p class="modal-sentence">' + nl2br((stage && stage.instructions_fr) || "") + '</p>' +
        '<p class="modal-guarantee">Rien n\'est supprimé en continuant : chaque suppression sera confirmée une par une.</p>';
    } else {
      body = '<p class="modal-sentence">' + sentence + '</p>' +
        '<p class="modal-guarantee">' + esc(GUARANTEE.verify) + '</p>';
    }
    openConfirm({
      title: (ux && ux.modalTitle) ? ux.modalTitle(ctx) : "Vérifier cette étape ?",
      bodyHtml: body,
      confirmLabel: key === "inventory" ? "Continuer" : "Vérifier",
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
    Array.prototype.forEach.call(document.querySelectorAll(".gd-wizard-answer"), function (elm) {
      S.guided.wizard.answers[elm.getAttribute("data-qid")] = elm.value;
    });
  }

  function confirmGuidedWizardDraft(withAnswers) {
    openConfirm({
      title: withAnswers ? "Re-rédiger le brouillon ?" : "Rédiger le brouillon ?",
      bodyHtml: '<p class="modal-sentence">L\'IA analyse les métadonnées agrégées du profil et rédige un brouillon ' +
        'de modèle sémantique' + (withAnswers ? " en tenant compte de vos réponses" : "") + '.</p>' +
        '<p class="modal-guarantee">Aucune ligne brute ne sera envoyée au modèle.</p>',
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
        if (w.config) { toast("Brouillon enregistré dans le hub."); }
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
      title: "Abandonner ce parcours ?",
      bodyHtml: '<p class="modal-sentence">Le parcours est marqué abandonné. Rien n\'est supprimé dans DSS : ' +
        'ce qui a déjà été créé reste en place. Vous pourrez en démarrer un nouveau.</p>',
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
        toast("Parcours abandonné. Rien n'a été supprimé.");
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
    if (S.tab !== "run") { selectTab("run"); } else { renderGuided(); }
  }

  /* ============================ screen: Mes agents (home) ============================ */

  function loadOverview() {
    if (S.overview.loading) { return; }
    S.overview.loading = true;
    S.overview.error = null;
    renderHome();
    callApi("GET", "state").then(function (r) {
      S.overview.loading = false;
      if (r.data && r.data.status === "ok") {
        S.overview.loaded = true;
        S.overview.data = r.data;
      } else {
        S.overview.error = (r.data && r.data.error) || "load_error";
      }
      renderHome();
    });
  }

  /* Home CTA: resume the active run, or open a fresh start form (a finished run
   * is cleared first so the form shows instead of its success screen). */
  function openAddAgent() {
    if (isActiveRun()) { selectTab("run"); return; }
    newGuidedDomain();
  }

  function resumeBanner() {
    var last = S.guided.run;
    if (last && last.status === "done") {
      // A finished run stays reachable (recap with the captured ids) until a new one starts.
      var dctx = stageCtx(last);
      return '<div class="resume-banner resume-banner--done"><p class="resume-text">Dernier parcours terminé : ' +
        (dctx.removal ? "retrait de l'expert " : "création de l'expert ") + mono(dctx.names.domain) + '.</p>' +
        '<button class="afc-btn afc-btn--ghost afc-btn--sm" id="homeRecap">Voir le récapitulatif</button></div>';
    }
    if (!isActiveRun()) { return ""; }
    var run = S.guided.run;
    var ctx = stageCtx(run);
    var stage = ((run.state || {}).stages || {})[run.current_stage] || {};
    var pos = stagePosition(run, run.current_stage);
    var what = ctx.removal ? "retrait de l'expert " : "création de l'expert ";
    return '<div class="resume-banner"><p class="resume-text">Parcours en cours : ' + what +
      mono(ctx.names.domain) + ', étape ' + pos.index + ' sur ' + pos.total +
      ' (' + esc(stageTitle(run.current_stage, stage)) + ').</p>' +
      '<button class="afc-btn afc-btn--primary" id="homeResume">Reprendre</button></div>';
  }

  var AGENT_GLYPH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
    '<rect x="5" y="8" width="14" height="11"/><path d="M12 4v4M9 13h.01M15 13h.01M9 16h6"/></svg>';

  function renderHome() {
    if (S.tab !== "home") { return; }
    var active = isActiveRun();
    var html = '<div class="afc-panel">' + backendBanner();

    if (!S.overview.loaded && !S.overview.error) {
      setHeader("OWIsMind · Usine à agents", "Mes agents");
      html += '<p class="afc-loading">Chargement des agents...</p></div>';
      setMain(html); return;
    }
    if (S.overview.error && !S.overview.loaded) {
      setHeader("OWIsMind · Usine à agents", "Mes agents");
      html += '<div class="afc-note afc-note--error">Impossible de charger les agents (' + esc(S.overview.error) + ').</div>' +
        '<div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="ovRetry">' + I.refresh + 'Réessayer</button></div></div>';
      setMain(html);
      if (byId("ovRetry")) { byId("ovRetry").onclick = loadOverview; }
      return;
    }

    var d = S.overview.data || {};
    var settings = d.settings || {};
    var caps = d.capabilities || {};
    var capKeys = Object.keys(caps);
    var hubChip = d.hub_ready
      ? '<span class="afc-chip afc-chip--on">HUB PRÊT</span>'
      : '<span class="afc-chip afc-chip--off">HUB ABSENT</span>';

    // Header CTA: ghost while a run is active (Reprendre is the primary), hidden
    // on the empty state (which carries its own primary).
    var cta = "";
    if (capKeys.length) {
      cta = '<button class="afc-btn ' + (active ? "afc-btn--ghost" : "afc-btn--primary") + '" id="homeAdd">' +
        I.plus + 'Ajouter un agent</button>';
    }
    setHeader("OWIsMind · Usine à agents", "Mes agents", cta);

    html += resumeBanner();
    if (S.overview.flash) {
      html += '<div class="afc-note afc-note--error">' + esc(S.overview.flash) + '</div>';
      S.overview.flash = null;
    }
    if (!d.hub_ready) {
      html += '<div class="afc-note afc-note--warn">Le hub n\'est pas poussé dans la project library : ' +
        'la création est impossible tant qu\'il manque.</div>';
    }

    if (!capKeys.length) {
      html += '<div class="home-empty"><span class="agent-tile">' + AGENT_GLYPH + '</span>' +
        '<h2 class="home-empty-title">Aucun agent enregistré</h2>' +
        '<p class="home-empty-text">Soit le hub n\'est pas encore poussé dans la project library, ' +
        'soit l\'orchestrateur utilise ses CAPABILITIES embarquées par défaut.</p>' +
        '<div class="afc-actions"><button class="afc-btn ' + (active ? "afc-btn--ghost" : "afc-btn--primary") +
        '" id="homeAdd">' + I.plus + 'Ajouter un agent</button></div></div>';
    } else {
      html += '<p class="afc-mlabel home-count">Agents enregistrés (' + capKeys.length + ')</p><ul class="agent-list">';
      capKeys.forEach(function (k) {
        var c = caps[k] || {};
        var enChip = c.enabled
          ? '<span class="afc-chip afc-chip--on">ACTIF</span>'
          : '<span class="afc-chip afc-chip--off">INACTIF</span>';
        var sub = [c.domain || k, c.tool_name || "", c.agent_id || "-"].filter(Boolean).join(" · ");
        html += '<li class="agent-row">' +
          '<span class="agent-tile">' + AGENT_GLYPH + '</span>' +
          '<span class="agent-main"><span class="agent-name">' + esc(c.label_fr || c.domain || k) + '</span>' +
          '<span class="agent-sub mono">' + esc(sub) + '</span></span>' +
          '<span class="agent-state">' + enChip + '</span>' +
          '<span class="agent-actions">' +
          '<button class="afc-btn afc-btn--ghost afc-btn--sm" data-cap-toggle="' + esc(k) + '">' +
          (c.enabled ? "Désactiver" : "Activer") + '</button>' +
          '<button class="afc-btn afc-btn--ghost afc-btn--sm" data-cap-remove="' + esc(k) + '">' +
          'Retirer...</button></span></li>';
      });
      html += '</ul>';
    }

    var tech = '<dl class="afc-kv">' +
      '<dt>Clé de projet</dt><dd>' + esc(d.project_key || "-") + '</dd>' +
      '<dt>Hub</dt><dd>' + hubChip + '</dd></dl>' +
      '<p class="afc-mlabel tech-label">Réglages de l\'usine (factory_settings.json)</p>' +
      '<dl class="afc-kv">' +
      '<dt>Connexion SQL</dt><dd>' + esc(settings.sql_connection || "-") + '</dd>' +
      '<dt>Code env 3.11</dt><dd>' + esc(settings.code_env_311 || "(défaut projet)") + '</dd>' +
      '<dt>LLM sonnet</dt><dd>' + esc(settings.llm_sonnet || "-") + '</dd>' +
      '<dt>Modèle sémantique modèle</dt><dd>' + esc(settings.template_semantic_model_id || "-") + '</dd>' +
      '<dt>Outil sémantique modèle</dt><dd>' + esc(settings.template_semantic_tool_id || "-") + '</dd>' +
      '<dt>Orchestrateur</dt><dd>' + esc(settings.orchestrator_agent_id || "-") + '</dd>' +
      '</dl><div class="afc-actions"><button class="afc-btn afc-btn--ghost afc-btn--sm" id="ovRefresh">' +
      I.refresh + 'Actualiser</button></div>';
    html += '<div class="home-tech">' +
      detailsBlock("home:tech", "Détails techniques : projet " + (d.project_key || "-") + ", hub, réglages usine", tech, false) +
      '</div>';
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
    if (byId("homeAdd")) { byId("homeAdd").onclick = openAddAgent; }
    if (byId("homeResume")) { byId("homeResume").onclick = function () { selectTab("run"); }; }
    if (byId("homeRecap")) { byId("homeRecap").onclick = function () { selectTab("run"); }; }
  }

  function confirmCapabilityToggle(key) {
    var caps = (S.overview.data || {}).capabilities || {};
    var c = caps[key] || {};
    var next = !c.enabled;
    var label = c.label_fr || c.domain || key;
    openConfirm({
      title: (next ? "Activer l'expert " : "Désactiver l'expert ") + label + " ?",
      bodyHtml: '<p class="modal-sentence">Je passe ' + mono(key) + ' à <b>' + (next ? "ACTIF" : "INACTIF") +
        '</b> dans le registre (sauvegarde auto). Rien d\'autre ne change.</p>' +
        '<p class="modal-note">Ensuite : re-sauvegarder l\'orchestrateur dans DSS, puis ouvrir une NOUVELLE ' +
        'conversation (le registre est lu au démarrage du process).</p>',
      confirmLabel: next ? "Activer" : "Désactiver",
      onConfirm: function () {
        callApi("POST", "capability/enable", {
          confirm: true, capability_key: key, enabled: next
        }).then(function (r) {
          if (!r.data || r.data.status !== "ok") {
            S.overview.flash = "Bascule impossible (" +
              ((r.data && r.data.error) || "erreur") + ").";
            renderHome();
            return;
          }
          toast(next ? "Expert activé." : "Expert désactivé.");
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
      title: "Retirer l'expert " + (c.label_fr || domain) + " ?",
      danger: true,
      bodyHtml: '<p class="modal-sentence">Je crée un parcours de retrait en 12 étapes pour ' + mono(key) +
        '. Rien n\'est supprimé maintenant : je fais d\'abord l\'inventaire, puis chaque suppression vous est ' +
        'présentée et confirmée une par une. Le dataset source n\'est jamais touché.</p>' +
        '<label class="afc-field modal-field"><span class="afc-field-label">Pour confirmer, tapez le nom du domaine : ' +
        mono(domain) + '</span>' +
        '<input class="afc-input" type="text" id="capRemoveTyped" autocomplete="off"></label>',
      confirmLabel: "Créer le parcours de retrait",
      onConfirm: function () {
        var field = byId("capRemoveTyped");
        var typed = (field ? field.value : "").trim();
        callApi("POST", "guided/start-removal", {
          confirm: true, capability_key: key, domain_typed: typed
        }).then(function (r) {
          if (!r.data || r.data.status !== "ok") {
            var code = (r.data && r.data.error) || "erreur";
            S.overview.flash = code === "domain_mismatch"
              ? "Le nom tapé ne correspond pas au domaine : aucun parcours créé."
              : (code === "active_run_exists"
                ? "Un parcours est déjà en cours : terminez-le ou abandonnez-le d'abord."
                : "Création impossible (" + code + ").");
            renderHome();
            return;
          }
          S.guided.loaded = false;
          selectTab("run");
        });
      }
    });
  }

  /* ============================ screen: Avance > Sonde ============================ */

  function renderProbe() {
    if (S.tab !== "probe") { return; }
    var p = S.probe;
    var html = '<div class="afc-panel">' + backendBanner() +
      '<div class="afc-sec">' +
      '<p class="afc-sec-note afc-sec-note--lead">Les sondes inspectent l\'instance DSS (API des Code Agents, ' +
      'outils Semantic Model Query, create_agent) pour savoir ce que l\'usine peut automatiser. ' +
      'Lecture seule : elles ne créent, ne modifient et ne suppriment rien.</p>';

    if (p.running) {
      html += progressBar() + '<div class="afc-note afc-note--info">Sondes en cours... (lecture seule)</div>';
    } else {
      html += '<div class="afc-actions">' +
        '<button class="afc-btn afc-btn--primary" id="probeRun">' + I.play + 'Lancer les sondes lecture seule</button>' +
        '</div>';
    }

    if (p.error) {
      html += '<div class="afc-note afc-note--error">Échec de la sonde : ' + esc(p.error) + '</div>';
    }
    if (p.report) {
      html += '<div class="afc-sec afc-sec--report">' +
        '<div class="afc-actions afc-actions--tight">' + copyButton("probeCopy", "Copier le rapport") + '</div>' +
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

  /* ============================ screen: Avance > Mode expert ============================ */

  function renderDomain() {
    if (S.tab !== "expert") { return; }
    loadDatasets(function () { if (S.tab === "expert") { renderDomainNow(); } });
    renderDomainNow();
  }

  function cardHead(number, title, help) {
    return '<div class="card-head"><span class="card-num mono">' + esc(number) + '</span>' +
      '<div><h2 class="card-title">' + esc(title) + '</h2>' +
      (help ? '<p class="card-help">' + esc(help) + '</p>' : "") + '</div></div>';
  }

  /* Expert mode: the one-shot plan / execute flow, as 3 numbered cards (Describe,
   * Simulate, Execute) with the optional semantic wizard between 1 and 2 (a new
   * draft invalidates the plan). Element ids and all guards are unchanged. */
  function renderDomainNow() {
    if (S.tab !== "expert") { return; }
    var f = S.domain.form;
    var html = '<div class="afc-panel">' + backendBanner();

    html += '<div class="afc-note afc-note--info afc-note--lead">Pour les admins avancés : exécute la création ' +
      'd\'un domaine en un seul bloc, sans accompagnement. Le parcours guidé (Mes agents &gt; Ajouter un agent) ' +
      'reste la voie recommandée.</div>';

    // --- 1. Describe ---
    html += '<div class="afc-card afc-card--titled">' +
      cardHead("1", "Décrire", "Le domaine et sa source de données. Toute modification invalide le plan.");

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
    html += '</div>'; // card 1

    // --- optional semantic wizard (between 1 and 2: a draft invalidates the plan) ---
    html += renderWizardSection();

    // --- 2. Simulate ---
    html += '<div class="afc-card afc-card--titled">' +
      cardHead("2", "Simuler", "Dry-run : liste tout ce qui serait créé, sans rien écrire dans DSS.");
    html += '<div class="afc-actions afc-actions--tight">' +
      '<button class="afc-btn ' + (S.domain.plan ? "afc-btn--ghost" : "afc-btn--primary") + '" id="dmPlan"' +
      (S.domain.planning ? " disabled" : "") + '>' +
      (S.domain.planning ? "Simulation..." : "Simuler (dry-run)") + '</button></div>';
    if (S.domain.planning) { html += progressBar(); }
    if (S.domain.planError) {
      html += '<div class="afc-note afc-note--error">Plan impossible : ' + esc(S.domain.planError) + '</div>';
    }
    if (S.domain.plan) {
      var pl = S.domain.plan;
      var counts = pl.counts || {};
      html += '<p class="afc-mlabel tech-label">Plan (dry-run) : ' +
        (pl.actions ? pl.actions.length : 0) + ' étapes</p>' +
        '<p class="afc-count">' + countsLine(counts) + '</p>';
      // Non-blocking preflight warnings returned by the backend (collisions,
      // weak routing signal, name headroom): shown BEFORE the actions table.
      if (pl.warnings && pl.warnings.length) {
        html += '<div class="afc-note afc-note--info"><b>Avertissements (non bloquants) :</b><ul>' +
          pl.warnings.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join("") +
          '</ul></div>';
      }
      html += actionsTable(pl.actions);
    }
    html += '</div>'; // card 2

    // --- 3. Execute ---
    html += '<div class="afc-card afc-card--titled">' +
      cardHead("3", "Exécuter", "Création réelle dans le projet DSS, à partir du plan simulé. Aucune suppression.");
    if (S.domain.plan) {
      html += '<div class="afc-actions afc-actions--tight">' +
        '<button class="afc-btn afc-btn--primary" id="dmExec"' + (S.domain.executing ? " disabled" : "") + '>' + I.play +
        (S.domain.executing ? "Exécution..." : "Exécuter") + '</button></div>';
    } else if (!S.domain.executing && !S.domain.execResult && !S.domain.execError) {
      html += '<p class="card-empty">Simulez d\'abord : le bouton Exécuter apparaît quand le plan est prêt.</p>';
    }

    // --- execution journal ---
    if (S.domain.executing || S.domain.execResult || S.domain.execError) {
      html += '<p class="afc-mlabel tech-label">Journal d\'exécution</p>';
      if (S.domain.executing) {
        html += progressBar() + '<div class="afc-note afc-note--info">Exécution en cours...</div>';
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
        html += '<p class="afc-mlabel tech-label">Runbook opérateur (copiable)</p>' +
          '<pre class="afc-pre">' + esc(S.domain.execResult.runbook) + '</pre>';
      }
    }
    html += '</div>'; // card 3

    html += '</div>';
    setMain(html);
    wireDomain();
  }

  function renderWizardSection() {
    var w = S.domain.wizard;
    // Status of the semantic wizard draft: tells the user whether Plan/Execute will
    // carry a semantic-model config, or leave the model to configure by hand later.
    var wizardReady = wizardConfigForSend() !== undefined;
    var html = '<div class="afc-card afc-card--titled">' +
      '<div class="card-head"><span class="card-num card-num--opt mono">+</span><div>' +
      '<h2 class="card-title">Wizard sémantique (optionnel)</h2>' +
      '<p class="card-help">Brouillon du modèle sémantique à partir du dataset de profil. ' +
      'Seules des métadonnées agrégées sont envoyées au LLM, jamais des lignes brutes.</p></div></div>' +
      '<p class="card-status">' + (wizardReady
        ? 'Config du wizard : prête (sera appliquée)'
        : 'Config du wizard : absente (le modèle sémantique restera à configurer)') + '</p>';

    var dsField = S.datasets.loading
      ? '<p class="afc-loading">Chargement des datasets...</p>'
      : '<select class="afc-select" id="wzProfile">' + datasetOptions(w.profileDataset) + '</select>';
    html += field("Dataset de profil", dsField,
      "En général <base>_profile. Sa métadonnée agrégée alimente le brouillon.");

    html += '<div class="afc-actions">' +
      '<button class="afc-btn afc-btn--ghost" id="wzDraft"' + (w.running ? " disabled" : "") + '>' +
      (w.running ? "Génération..." : "Générer le brouillon") + '</button></div>';
    if (w.running) { html += progressBar(); }

    if (w.error) {
      html += '<div class="afc-note afc-note--error">Wizard impossible : ' + esc(w.error) + '</div>';
    }

    if (w.config) {
      var cfg = w.config;
      var questions = cfg.questions || [];
      if (questions.length) {
        html += '<p class="afc-mlabel tech-label">Questions de clarification</p>';
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
          (w.regenerating ? "Régénération..." : "Régénérer avec mes réponses") + '</button></div>';
      }

      html += detailsBlock("expert:wizard-json", "Configuration du modèle (brouillon JSON)",
        '<div class="afc-actions afc-actions--tight">' + copyButton("wzCopy", "Copier le JSON") + '</div>' +
        '<pre class="afc-pre" id="wzJson">' + esc(JSON.stringify(cfg, null, 2)) + '</pre>', true);
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
    var planned = (pl.actions || [])
      .filter(function (a) { return a.status === "PLANNED"; })
      .map(function (a) { return obj("Étape", a.step, "", "", a.detail || ""); });
    var body = '<p class="modal-sentence">J\'exécute pour de vrai la création du domaine ' +
      mono(spec.domain || "(sans nom)") + ' dans le projet DSS. Les étapes MANUEL restent à faire à la main.</p>';
    if (planned.length) {
      body += '<p class="afc-mlabel modal-label">Étapes planifiées (' + planned.length + ')</p>' +
        objectsList(planned, false);
    }
    body += '<p class="modal-guarantee">Rien n\'est supprimé. Le journal détaille chaque étape.</p>';
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

  /* ============================ screen: Avance > Fichiers du hub ============================ */

  function renderPrompts() {
    if (S.tab !== "hub") { return; }
    var pr = S.prompts;
    var html = '<div class="afc-panel">' + backendBanner();

    // --- persona / prompt editor ---
    html += '<div class="afc-card afc-card--titled">' +
      '<div class="card-head"><h2 class="card-title">Prompt de persona</h2>' +
      '<p class="card-help">Un fichier sous /python/owismind_hub/prompts/ (persona de l\'orchestrateur, ou ' +
      'prompts/&lt;domaine&gt;/understand_extra.md pour un sous-agent).</p></div>';

    html += '<div class="afc-field"><span class="afc-field-label">Chemin du fichier</span>' +
      '<div class="afc-inline">' +
      '<input class="afc-input mono" id="prPath" value="' + esc(pr.path) + '">' +
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
    html += '</div>';

    // --- capabilities editor ---
    var caps = pr.caps;
    html += '<div class="afc-card afc-card--titled">' +
      '<div class="card-head"><h2 class="card-title">Registre capabilities.json</h2>' +
      '<p class="card-help">Validé côté serveur avant écriture (une seule capacité active par domaine), ' +
      'avec sauvegarde automatique du fichier précédent.</p></div>';

    html += '<div class="afc-actions afc-actions--tight">' +
      '<button class="afc-btn afc-btn--ghost afc-btn--sm" id="capLoad"' + (caps.loading ? " disabled" : "") + '>' + I.refresh +
      (caps.loading ? "Chargement..." : "Charger") + '</button></div>';

    if (caps.loadError) {
      html += '<div class="afc-note afc-note--error">Chargement impossible : ' + esc(caps.loadError) + '</div>';
    }

    html += '<div class="afc-field afc-field--spaced"><span class="afc-field-label">capabilities.json</span>' +
      '<textarea class="afc-textarea code" id="capContent" placeholder="' +
      (caps.loaded ? "" : "Cliquez sur Charger pour récupérer le JSON.") + '">' + esc(caps.text) + '</textarea></div>';

    if (caps.problems && caps.problems.length) {
      html += '<div class="afc-note afc-note--error"><b>Validation refusée :</b><ul>' +
        caps.problems.map(function (p) { return '<li>' + esc(p) + '</li>'; }).join("") + '</ul></div>';
    }

    html += '<div class="afc-actions">' +
      '<button class="afc-btn afc-btn--primary" id="capSave"' + (caps.saving || !caps.loaded ? " disabled" : "") + '>' + I.save +
      'Valider et enregistrer</button></div>';
    html += '</div></div>';

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


  /* ============================ navigation + theme + boot ============================ */

  var ADVANCED_TABS = { probe: 1, expert: 1, hub: 1 };

  function renderActive() {
    if (S.tab === "home") { if (!S.overview.loaded) { loadOverview(); } else { renderHome(); } }
    else if (S.tab === "run") {
      if (!S.guided.loaded && !S.guided.loading) { loadGuidedCurrent(); } else { renderRun(); }
    }
    else if (S.tab === "probe") { setHeader("OWIsMind · Avancé", "Sonde de l'instance"); renderProbe(); }
    else if (S.tab === "expert") { setHeader("OWIsMind · Avancé", "Mode expert"); renderDomain(); }
    else if (S.tab === "hub") { setHeader("OWIsMind · Avancé", "Fichiers du hub"); renderPrompts(); }
  }

  /* Main nav state: "Parcours en cours" is shown only while a run is active;
   * "Avancé" is on for its 3 sub-tabs (and reveals the sub-row); the start form
   * (run tab without an active run) keeps "Mes agents" on. */
  function syncNav() {
    var active = isActiveRun();
    var runTab = byId("afcTabRun");
    if (runTab) { runTab.hidden = !active; }
    var mainKey = ADVANCED_TABS[S.tab] ? "advanced" : (S.tab === "run" && active ? "run" : "home");
    var tabs = byId("afcTabs");
    if (tabs) {
      Array.prototype.forEach.call(tabs.querySelectorAll(".afc-tab"), function (b) {
        var on = b.getAttribute("data-nav") === mainKey;
        b.classList.toggle("afc-tab--on", on);
        if (on) { b.setAttribute("aria-current", "page"); } else { b.removeAttribute("aria-current"); }
      });
    }
    var sub = byId("afcSubtabs");
    if (sub) {
      sub.hidden = !ADVANCED_TABS[S.tab];
      Array.prototype.forEach.call(sub.querySelectorAll(".afc-subtab"), function (b) {
        b.classList.toggle("afc-subtab--on", b.getAttribute("data-tab") === S.tab);
      });
    }
  }

  function selectTab(tab) {
    S.tab = tab;
    if (ADVANCED_TABS[tab]) { S.ui.lastAdvanced = tab; }
    var a = byId("afcHeaderAction");
    if (a) { a.innerHTML = ""; }
    syncNav();
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
    Array.prototype.forEach.call(byId("afcTabs").querySelectorAll(".afc-tab"), function (b) {
      b.onclick = function () {
        var tab = b.getAttribute("data-tab");
        if (tab === "advanced") { tab = S.ui.lastAdvanced || "probe"; }
        selectTab(tab);
      };
    });
    Array.prototype.forEach.call(byId("afcSubtabs").querySelectorAll(".afc-subtab"), function (b) {
      b.onclick = function () { selectTab(b.getAttribute("data-tab")); };
    });
    // close modal on scrim click (outside the card)
    var scrim = byId("afcModalScrim");
    if (scrim) { scrim.onclick = function (ev) { if (ev.target === scrim) { closeModal(); } }; }
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") { closeModal(); }
    });

    // Load the active run FIRST (resume banner + "Parcours en cours" nav item),
    // then land on the home screen; it re-renders when the run arrives.
    S.tab = "home";
    loadGuidedCurrent();
    selectTab("home");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
