/* ============================================================
   OWIsMind — Benchmark Launcher · app logic
   ============================================================ */
(function(){
"use strict";

/* ---------- icons ---------- */
const I = {
  check:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><path d="M5 12l5 5 9-10"/></svg>',
  plus:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
  trash:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13"/></svg>',
  edit:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20h4L18 10l-4-4L4 16v4zM14 6l4 4"/></svg>',
  play:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 4l14 8-14 8z"/></svg>',
  save:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 4h11l3 3v13H5zM8 4v5h7M8 20v-6h8v6"/></svg>',
  logs:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 4h14v16H5zM8 9h8M8 13h8M8 17h5"/></svg>',
  gear:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3.2"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M18.4 5.6l-1.8 1.8M7.4 16.6l-1.8 1.8"/></svg>',
  info:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.5"/></svg>',
  rocket:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3c3 1 5 4 5 8l-2 4H9l-2-4c0-4 2-7 5-8zM9 15l-2 3M15 15l2 3M12 8.5v0"/><circle cx="12" cy="9" r="1.4"/></svg>',
  list:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 6h12M8 12h12M8 18h12M4 6h.5M4 12h.5M4 18h.5"/></svg>',
  bulb:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10c1 1 1.5 1.5 1.5 3h5c0-1.5.5-2 1.5-3a6 6 0 0 0-4-10z"/></svg>',
};

/* ---------- i18n ---------- */
const DICT = {
  "util.logs":        {en:"Logs", fr:"Journaux"},
  "util.settings":    {en:"Settings", fr:"Paramètres"},
  "status.idle":      {en:"Idle", fr:"En attente"},
  "status.running":   {en:"Running", fr:"En cours"},
  "status.done":      {en:"Completed", fr:"Terminé"},
  "hdr.eyebrow":      {en:"OWIsMind Benchmark", fr:"OWIsMind Benchmark"},
  "hdr.h1":           {en:"Launcher", fr:"Lanceur"},
  "hdr.sub":          {en:"Configure the benchmark, launch a run, and promote the questions your users suggested. Results are read in the separate Results app.", fr:"Configurez le benchmark, lancez une exécution et promouvez les questions suggérées par vos utilisateurs. Les résultats se consultent dans l'application Résultats."},

  "tab.config":       {en:"Configuration", fr:"Configuration"},
  "tab.golden":       {en:"Golden set", fr:"Jeu de référence"},
  "tab.suggest":      {en:"Suggestions", fr:"Suggestions"},

  "cfg.eyebrow":      {en:"Setup", fr:"Paramétrage"},
  "cfg.title":        {en:"Configuration", fr:"Configuration"},
  "cfg.note":         {en:"This is the live configuration. Saving only changes the agents, modes, question filter, concurrency and language. The preserved settings are kept untouched.", fr:"Ceci est la configuration active. L'enregistrement ne modifie que les agents, les modes, le filtre de questions, la concurrence et la langue. Les réglages préservés ne sont pas touchés."},

  "ag.label":         {en:"Agents under test", fr:"Agents testés"},
  "ag.help":          {en:"The agent id (like agent:038G7mlF) lives inside its own DSS project: do not prefix it. The project key tells the benchmark which project to call it in.", fr:"L'identifiant de l'agent (ex. agent:038G7mlF) vit dans son propre projet DSS : ne le préfixez pas. La clé de projet indique au benchmark dans quel projet l'appeler."},
  "ag.f.label":       {en:"Label", fr:"Libellé"},
  "ag.f.key":         {en:"Project key", fr:"Clé de projet"},
  "ag.f.id":          {en:"Agent id", fr:"Identifiant d'agent"},
  "ag.modes":         {en:"Supports response modes (Smart / Pro / Claude)", fr:"Gère les modes de réponse (Smart / Pro / Claude)"},
  "ag.remove":        {en:"Remove", fr:"Retirer"},
  "ag.add":           {en:"Add agent", fr:"Ajouter un agent"},

  "rm.title":         {en:"Response modes", fr:"Modes de réponse"},
  "rm.help":          {en:"Only mode-aware agents are tested across the checked modes. Other agents get a single default call.", fr:"Seuls les agents compatibles sont testés sur les modes cochés. Les autres reçoivent un appel par défaut."},

  "qt.title":         {en:"Questions to test", fr:"Questions à tester"},
  "qt.help":          {en:"Pick the categories to test. Empty selection = all {n} active questions.", fr:"Choisissez les catégories à tester. Aucune sélection = les {n} questions actives."},
  "qt.langfilter":    {en:"Language filter", fr:"Filtre de langue"},

  "rp.title":         {en:"Run parameters", fr:"Paramètres d'exécution"},
  "rp.conc":          {en:"Concurrency", fr:"Concurrence"},
  "rp.conc.help":     {en:"Questions run in parallel (1–8, kept low for instance safety). Out-of-range values are clamped.", fr:"Questions en parallèle (1–8, faible pour la sécurité de l'instance). Les valeurs hors plage sont bornées."},
  "rp.lang":          {en:"Benchmark language", fr:"Langue du benchmark"},
  "rp.lang.help":     {en:"Language used for the run report and the agent prompts. To choose which golden questions are tested, use the language filter.", fr:"Langue du rapport d'exécution et des prompts d'agent. Pour choisir les questions testées, utilisez le filtre de langue."},

  "opt.all":          {en:"All", fr:"Toutes"},
  "opt.en":           {en:"English (en)", fr:"Anglais (en)"},
  "opt.fr":           {en:"French (fr)", fr:"Français (fr)"},

  "save.btn":         {en:"Save configuration", fr:"Enregistrer la configuration"},
  "save.hint":        {en:"Live config — applies to the next run.", fr:"Config active — s'applique à la prochaine exécution."},

  "run.eyebrow":      {en:"Run", fr:"Exécution"},
  "run.title":        {en:"Launch", fr:"Lancer"},
  "run.note":         {en:"Launch the Run_Benchmark scenario asynchronously. Only one run can be in progress at a time.", fr:"Lance le scénario Run_Benchmark de façon asynchrone. Une seule exécution à la fois."},
  "run.btn":          {en:"Launch the benchmark", fr:"Lancer le benchmark"},
  "run.btn.running":  {en:"Run in progress…", fr:"Exécution en cours…"},
  "run.last":         {en:"Last run", fr:"Dernière exécution"},
  "run.never":        {en:"never", fr:"jamais"},
  "run.save1":        {en:"Launching runs the last saved configuration — save your edits first.", fr:"Le lancement utilise la dernière configuration enregistrée — enregistrez d'abord vos modifications."},
  "run.save2":        {en:"Launching may require scenario permissions. If unsupported, run Run_Benchmark from the DSS scenario UI.", fr:"Le lancement peut nécessiter des permissions de scénario. Si indisponible, lancez Run_Benchmark depuis l'UI scénario DSS."},

  "pr.eyebrow":       {en:"Preserved settings", fr:"Réglages préservés"},
  "pr.title":         {en:"Not editable here", fr:"Non modifiable ici"},
  "pr.golden":        {en:"Golden dataset", fr:"Jeu de référence"},
  "pr.judge":         {en:"Judge model", fr:"Modèle juge"},
  "pr.suggest":       {en:"Suggestions source", fr:"Source des suggestions"},
  "pr.na":            {en:"Not configured", fr:"Non configuré"},

  "gs.eyebrow":       {en:"Golden set", fr:"Jeu de référence"},
  "gs.title":         {en:"Questions", fr:"Questions"},
  "gs.note":          {en:"The reference questions the benchmark scores the agents against, with the answer you expect. Add, edit, enable/disable or remove them. Changes apply to the next run.", fr:"Les questions de référence sur lesquelles le benchmark évalue les agents, avec la réponse attendue. Ajoutez, modifiez, activez/désactivez ou retirez-les. Les changements s'appliquent à la prochaine exécution."},
  "gs.count":         {en:"{n} question(s), {a} active", fr:"{n} question(s), {a} active(s)"},
  "gs.add":           {en:"Add a question", fr:"Ajouter une question"},

  "th.status":        {en:"On", fr:"Actif"},
  "th.q":             {en:"Question", fr:"Question"},
  "th.a":             {en:"Expected answer", fr:"Réponse attendue"},
  "th.anchor":        {en:"Anchor", fr:"Ancre"},
  "th.cat":           {en:"Category", fr:"Catégorie"},
  "th.lang":          {en:"Lang", fr:"Langue"},
  "th.act":           {en:"Actions", fr:"Actions"},

  "sg.eyebrow":       {en:"Golden set", fr:"Jeu de référence"},
  "sg.title":         {en:"User suggestions", fr:"Suggestions utilisateurs"},
  "sg.note":          {en:"Questions your users suggested, pending review. Select the good ones and promote them into the golden set.", fr:"Questions suggérées par vos utilisateurs, en attente de revue. Sélectionnez les bonnes et promouvez-les dans le jeu de référence."},
  "sg.empty.h":       {en:"Suggestions source not configured", fr:"Source de suggestions non configurée"},
  "sg.empty.p":       {en:"Add the benchmark.suggestions block to the project variable to start collecting user suggestions.", fr:"Ajoutez le bloc benchmark.suggestions à la variable de projet pour collecter les suggestions."},

  "md.add":           {en:"Add a question", fr:"Ajouter une question"},
  "md.edit":          {en:"Edit question", fr:"Modifier la question"},
  "md.q":             {en:"Question", fr:"Question"},
  "md.a":             {en:"Expected answer", fr:"Réponse attendue"},
  "md.anchor":        {en:"Anchor (optional)", fr:"Ancre (optionnel)"},
  "md.cat":           {en:"Category", fr:"Catégorie"},
  "md.lang":          {en:"Language", fr:"Langue"},
  "md.active":        {en:"Active in the next run", fr:"Active à la prochaine exécution"},
  "md.cancel":        {en:"Cancel", fr:"Annuler"},
  "md.save":          {en:"Save question", fr:"Enregistrer"},

  "t.saved":          {en:"Configuration saved", fr:"Configuration enregistrée"},
  "t.launched":       {en:"Benchmark launched", fr:"Benchmark lancé"},
  "t.done":           {en:"Run completed", fr:"Exécution terminée"},
  "t.qadded":         {en:"Question added", fr:"Question ajoutée"},
  "t.qsaved":         {en:"Question updated", fr:"Question mise à jour"},
  "t.qremoved":       {en:"Question removed", fr:"Question retirée"},
  "t.agadded":        {en:"Agent added", fr:"Agent ajouté"},
  "t.agremoved":      {en:"Agent removed", fr:"Agent retiré"},
};
function t(key, vars){
  let s = (DICT[key] && DICT[key][S.lang]) || key;
  if(vars) for(const k in vars) s = s.replace("{"+k+"}", vars[k]);
  return s;
}

/* ---------- state ---------- */
const LS = "owismind_bench_v1";
const DEFAULTS = {
  lang:"en", theme:"light", tab:"config",
  agents:[ {label:"OWIsMind Orchestrator (DEV)", key:"OWISMIND_DEV", id:"agent:038G7mlF", modes:true} ],
  modes:{Smart:true, Pro:false, Claude:false},
  cats:{compare:false, revenus:false, top_n:false},
  langFilter:"all", concurrency:1, benchLang:"en",
  preserved:{ golden:"golden_questions_v1_prepared", judge:"openai:LLM-7064-revforecast:vertex_ai/claude-sonnet-4-6", suggest:null },
  lastRun:"2026-06-26T09:02:34.825175",
  questions:[
    {id:"q1", q:"what is the 2026 revenue budget, forecast and how they compare to actuals for Telesat LEO", a:"Période : 01/01/2026 → 31/12/2026 · BUDGET … · FORECAST … · Pas de Forecast saisi pour cette période…", anchor:"", cat:"compare", lang:"en", active:true},
    {id:"q2", q:"Quels sont les revenus actuals pour la BW en 2025 ?", a:"Février 2025 | 19 584,58 | | Mars 2025 | 107,71 | | Avril 2025 | 3 200,00 | | Mai 2025 | 3 200,00 | | Juin 2025 | 3…", anchor:"", cat:"revenus", lang:"fr", active:true},
    {id:"q3", q:"Give the Top 3 of customers for the roaming in January 2026", a:"Account_name · Somme de amount_eur · TELROAMING ADVANCED COMMUNICATION SOLUTION LTD. 2 196 769,55 · 1&1 MOBILFUNK GMBH 1 375…", anchor:"TELROAMING ADVANCED COMMUNICATION SOLUTION LTD.; 1&1 MOBILFUNK GMBH; SES ASTRA S.A.  · LIST", cat:"top_n", lang:"en", active:true},
  ],
};
let S;
try{ S = Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem(LS)||"{}")); }
catch(e){ S = Object.assign({}, DEFAULTS); }
function save(){ try{ localStorage.setItem(LS, JSON.stringify(S)); }catch(e){} }

const CATS = ["compare","revenus","top_n"];
const MODES = ["Smart","Pro","Claude"];

/* ---------- dom helpers ---------- */
const $ = (s,r)=> (r||document).querySelector(s);
const $$ = (s,r)=> Array.from((r||document).querySelectorAll(s));
function el(tag, cls, html){ const e=document.createElement(tag); if(cls)e.className=cls; if(html!=null)e.innerHTML=html; return e; }
function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

/* ---------- i18n apply ---------- */
function applyI18n(){
  $$("[data-i18n]").forEach(e=> e.textContent = t(e.dataset.i18n));
  $$("[data-i18n-ph]").forEach(e=> e.placeholder = t(e.dataset.i18nPh));
  document.documentElement.lang = S.lang;
}

/* ---------- render: agents ---------- */
function renderAgents(){
  const box = $("#agentsList"); box.innerHTML="";
  S.agents.forEach((a,i)=>{
    const card = el("div","agent");
    card.innerHTML = `
      <div class="agent-grid">
        <label class="field"><span class="field-label">${esc(t("ag.f.label"))}</span>
          <input class="input" data-f="label" value="${esc(a.label)}"></label>
        <label class="field"><span class="field-label">${esc(t("ag.f.key"))}</span>
          <input class="input mono" data-f="key" value="${esc(a.key)}"></label>
        <label class="field"><span class="field-label">${esc(t("ag.f.id"))}</span>
          <input class="input mono" data-f="id" value="${esc(a.id)}"></label>
      </div>
      <div class="agent-foot">
        <button type="button" class="chk ${a.modes?"on":""}" data-modes>
          <span class="box">${I.check}</span><span class="chk-txt">${esc(t("ag.modes"))}</span>
        </button>
        <button type="button" class="btn btn-danger btn-sm" data-remove>${esc(t("ag.remove"))}</button>
      </div>`;
    card.querySelectorAll("input").forEach(inp=> inp.addEventListener("input", ()=>{
      a[inp.dataset.f]=inp.value; markDirty(); save();
    }));
    card.querySelector("[data-modes]").addEventListener("click", function(){
      a.modes=!a.modes; this.classList.toggle("on",a.modes); markDirty(); save();
    });
    card.querySelector("[data-remove]").addEventListener("click", ()=>{
      S.agents.splice(i,1); markDirty(); save(); renderAgents(); toast(t("t.agremoved"));
    });
    box.appendChild(card);
  });
}

/* ---------- render: checkbox groups ---------- */
function chkBtn(label, on){
  const b = el("button","chk"+(on?" on":""));
  b.type="button";
  b.innerHTML = `<span class="box">${I.check}</span><span class="chk-txt"><b>${esc(label)}</b></span>`;
  return b;
}
function renderModes(){
  const box = $("#modesGroup"); box.innerHTML="";
  MODES.forEach(m=>{
    const b = chkBtn(m, !!S.modes[m]);
    b.addEventListener("click", ()=>{ S.modes[m]=!S.modes[m]; b.classList.toggle("on",S.modes[m]); markDirty(); save(); });
    box.appendChild(b);
  });
}
function renderCats(){
  const box = $("#catsGroup"); box.innerHTML="";
  CATS.forEach(c=>{
    const b = chkBtn(c, !!S.cats[c]);
    b.addEventListener("click", ()=>{ S.cats[c]=!S.cats[c]; b.classList.toggle("on",S.cats[c]); markDirty(); save(); });
    box.appendChild(b);
  });
}

/* ---------- render: questions table ---------- */
function renderQuestions(){
  const tb = $("#qtbody"); tb.innerHTML="";
  const active = S.questions.filter(q=>q.active).length;
  $("#qCount").innerHTML = t("gs.count",{n:S.questions.length, a:active}).replace(/(\d+)/g,'<b>$1</b>');
  $("#tabGoldenCount").textContent = S.questions.length;
  // questionsToTest help count = active
  $("#qtHelp").textContent = t("qt.help",{n:active});

  S.questions.forEach((q)=>{
    const tr = el("tr", q.active?"":"off");
    tr.innerHTML = `
      <td data-l="${esc(t("th.status"))}"><div class="tog ${q.active?"on":""}" role="switch" aria-checked="${q.active}"></div></td>
      <td data-l="${esc(t("th.q"))}"><div class="cell-q clamp">${esc(q.q)}</div></td>
      <td data-l="${esc(t("th.a"))}"><div class="cell-a clamp">${esc(q.a)}</div></td>
      <td data-l="${esc(t("th.anchor"))}"><div class="cell-mono clamp">${q.anchor?esc(q.anchor):"—"}</div></td>
      <td data-l="${esc(t("th.cat"))}"><span class="cat-tag">${esc(q.cat)}</span></td>
      <td data-l="${esc(t("th.lang"))}"><span class="lang-tag">${esc(q.lang)}</span></td>
      <td data-l="${esc(t("th.act"))}"><div class="row-act">
        <button class="icon-btn" data-edit title="${esc(t("md.edit"))}">${I.edit}</button>
        <button class="icon-btn danger" data-del title="${esc(t("ag.remove"))}">${I.trash}</button>
      </div></td>`;
    tr.querySelector(".tog").addEventListener("click", ()=>{ q.active=!q.active; save(); renderQuestions(); });
    tr.querySelector("[data-edit]").addEventListener("click", ()=> openModal(q));
    tr.querySelector("[data-del]").addEventListener("click", ()=>{
      S.questions = S.questions.filter(x=>x!==q); save(); renderQuestions(); toast(t("t.qremoved"));
    });
    tb.appendChild(tr);
  });
}

/* ---------- preserved ---------- */
function renderPreserved(){
  $("#prGolden").textContent = S.preserved.golden;
  $("#prJudge").textContent = S.preserved.judge;
  const sg = $("#prSuggest");
  if(S.preserved.suggest){ sg.textContent = S.preserved.suggest; sg.className=""; }
  else { sg.innerHTML = `<span class="tag-na">${esc(t("pr.na"))}</span>`; }
}

/* ---------- last run ---------- */
function renderLastRun(){
  $("#lastRunVal").textContent = S.lastRun ? S.lastRun : t("run.never");
}

/* ---------- modal ---------- */
let editing = null;
function openModal(q){
  editing = q || null;
  $("#mdTitle").textContent = q ? t("md.edit") : t("md.add");
  $("#mq").value = q?q.q:"";
  $("#ma").value = q?q.a:"";
  $("#manchor").value = q?q.anchor:"";
  $("#mcat").value = q?q.cat:"compare";
  $("#mlang").value = q?q.lang:"en";
  const at = $("#mActive"); const on = q? q.active : true;
  at.classList.toggle("on", on); at.dataset.on = on?"1":"0";
  $("#overlay").classList.add("on");
  setTimeout(()=>$("#mq").focus(),50);
}
function closeModal(){ $("#overlay").classList.remove("on"); editing=null; }
function submitModal(){
  const q = $("#mq").value.trim(); if(!q){ $("#mq").focus(); return; }
  const data = { q, a:$("#ma").value.trim(), anchor:$("#manchor").value.trim(),
    cat:$("#mcat").value, lang:$("#mlang").value, active:$("#mActive").dataset.on==="1" };
  if(editing){ Object.assign(editing, data); toast(t("t.qsaved")); }
  else { S.questions.push(Object.assign({id:"q"+Date.now()}, data)); toast(t("t.qadded")); }
  save(); renderQuestions(); closeModal();
}

/* ---------- toast ---------- */
let toastT;
function toast(msg){
  const el2 = $("#toast"); $("#toastMsg").textContent = msg;
  el2.classList.add("on"); clearTimeout(toastT);
  toastT = setTimeout(()=>el2.classList.remove("on"), 2200);
}

/* ---------- dirty / status ---------- */
function markDirty(){ document.body.classList.add("dirty"); }
function clearDirty(){ document.body.classList.remove("dirty"); }
function setStatus(kind){
  const p = $("#runPill"); p.className = "run-pill "+kind;
  $("#runStatusTxt").textContent = t("status."+kind);
}

/* ---------- launch (simulated) ---------- */
let running = false;
function launch(){
  if(running) return;
  running = true;
  const btn = $("#launchBtn");
  btn.disabled = true; btn.querySelector("span").textContent = t("run.btn.running");
  setStatus("running");
  const pr = $("#progress"); pr.classList.add("on");
  const bar = $("#progressBar"); const meta = $("#progressMeta");
  toast(t("t.launched"));
  let p = 0;
  const iv = setInterval(()=>{
    p += Math.random()*16+6; if(p>100)p=100;
    bar.style.width = p+"%"; meta.textContent = Math.round(p)+"%";
    if(p>=100){
      clearInterval(iv);
      setTimeout(()=>{
        running=false; btn.disabled=false; btn.querySelector("span").textContent=t("run.btn");
        S.lastRun = new Date().toISOString().replace("Z","000"); save(); renderLastRun();
        setStatus("done"); pr.classList.remove("on"); bar.style.width="0";
        toast(t("t.done"));
      }, 500);
    }
  }, 380);
}

/* ---------- tabs ---------- */
function setTab(tab){
  S.tab = tab; save();
  $$(".tab").forEach(b=> b.classList.toggle("on", b.dataset.tab===tab));
  $$(".panel").forEach(p=> p.classList.toggle("on", p.dataset.panel===tab));
}

/* ---------- wire up ---------- */
function init(){
  document.body.dataset.theme = S.theme;

  // header / seg controls
  $$("#langSeg button").forEach(b=> b.addEventListener("click", ()=>{
    S.lang = b.dataset.lang; save();
    $$("#langSeg button").forEach(x=>x.classList.toggle("on", x.dataset.lang===S.lang));
    renderAll();
  }));
  $$("#themeSeg button").forEach(b=> b.addEventListener("click", ()=>{
    S.theme = b.dataset.theme; document.body.dataset.theme=S.theme; save();
    $$("#themeSeg button").forEach(x=>x.classList.toggle("on", x.dataset.theme===S.theme));
  }));

  // tabs
  $$(".tab").forEach(b=> b.addEventListener("click", ()=> setTab(b.dataset.tab)));

  // add agent
  $("#addAgent").addEventListener("click", ()=>{
    S.agents.push({label:"New agent", key:"PROJECT_KEY", id:"agent:", modes:false});
    markDirty(); save(); renderAgents(); toast(t("t.agadded"));
  });

  // selects + concurrency
  $("#langFilter").addEventListener("change", e=>{ S.langFilter=e.target.value; markDirty(); save(); });
  $("#benchLang").addEventListener("change", e=>{ S.benchLang=e.target.value; markDirty(); save(); });
  $("#concurrency").addEventListener("change", e=>{
    let v = parseInt(e.target.value,10); if(isNaN(v))v=1; v=Math.max(1,Math.min(8,v));
    S.concurrency=v; e.target.value=v; markDirty(); save();
  });

  // save config
  $("#saveBtn").addEventListener("click", ()=>{ save(); clearDirty(); toast(t("t.saved")); });

  // launch
  $("#launchBtn").addEventListener("click", launch);

  // golden add
  $("#addQ").addEventListener("click", ()=> openModal(null));

  // modal
  $("#mdClose").addEventListener("click", closeModal);
  $("#mdCancel").addEventListener("click", closeModal);
  $("#mdSave").addEventListener("click", submitModal);
  $("#mActive").addEventListener("click", function(){
    const on = this.dataset.on!=="1"; this.dataset.on=on?"1":"0"; this.classList.toggle("on",on);
  });
  $("#overlay").addEventListener("click", e=>{ if(e.target===$("#overlay")) closeModal(); });
  document.addEventListener("keydown", e=>{ if(e.key==="Escape") closeModal(); });

  renderAll();
}

function renderAll(){
  applyI18n();
  // sync seg states
  $$("#langSeg button").forEach(x=>x.classList.toggle("on", x.dataset.lang===S.lang));
  $$("#themeSeg button").forEach(x=>x.classList.toggle("on", x.dataset.theme===S.theme));
  // selects values
  $("#langFilter").value = S.langFilter;
  $("#benchLang").value = S.benchLang;
  $("#concurrency").value = S.concurrency;
  setTab(S.tab);
  renderAgents();
  renderModes();
  renderCats();
  renderQuestions();
  renderPreserved();
  renderLastRun();
  setStatus(running ? "running" : "idle");
  // static icons
  $("#icLogs").innerHTML = I.logs;
  $("#icSettings").innerHTML = I.gear;
  $("#icRun").innerHTML = I.rocket;
  $("#icAddAgent").innerHTML = I.plus;
  $("#icAddQ").innerHTML = I.plus;
  $("#icSave").innerHTML = I.save;
  $("#icNotice").innerHTML = I.info;
  $("#icEmpty").innerHTML = I.bulb;
  $$("[data-rail]").forEach(r=> r.innerHTML = I[r.dataset.rail]||"");
}

if(document.readyState==="loading") document.addEventListener("DOMContentLoaded", init);
else init();
})();
