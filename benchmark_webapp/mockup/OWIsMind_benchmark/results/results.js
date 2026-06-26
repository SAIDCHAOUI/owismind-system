/* ============================================================
   OWIsMind — Results · app logic
   ============================================================ */
(function(){
"use strict";

const I = {
  logs:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 4h14v16H5zM8 9h8M8 13h8M8 17h5"/></svg>',
  gear:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3.2"/><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M18.4 5.6l-1.8 1.8M7.4 16.6l-1.8 1.8"/></svg>',
  rocket:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3c3 1 5 4 5 8l-2 4H9l-2-4c0-4 2-7 5-8zM9 15l-2 3M15 15l2 3"/><circle cx="12" cy="9" r="1.4"/></svg>',
  chart:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-8"/></svg>',
  plus:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 5v14M5 12h14"/></svg>',
  minus:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M5 12h14"/></svg>',
  flag:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 21V4h12l-2 4 2 4H5"/></svg>',
};

/* ---------- i18n ---------- */
const DICT = {
  "util.logs":{en:"Logs",fr:"Journaux"},
  "util.settings":{en:"Settings",fr:"Paramètres"},
  "hdr.eyebrow":{en:"Agent benchmark",fr:"Benchmark des agents"},
  "hdr.h1":{en:"How well do the OWIsMind agents answer?",fr:"Quelle est la qualité des réponses des agents OWIsMind ?"},
  "hdr.sub":{en:"An independent, repeatable test of our AI agents. It measures, in plain language, how often they are right, how fast they answer, and what each answer costs.",fr:"Un test indépendant et reproductible de nos agents IA. Il mesure, en clair, à quelle fréquence ils ont raison, leur rapidité de réponse et le coût de chaque réponse."},
  "run.label":{en:"Test run",fr:"Exécution"},

  "hero.head":{en:"OWIsMind gave the right answer in {r} of {t} answers produced, across all configurations",fr:"OWIsMind a donné la bonne réponse {r} fois sur {t} réponses produites, toutes configurations confondues"},
  "hero.correct":{en:"Correct answers",fr:"Bonnes réponses"},
  "hero.note":{en:"How often the AI gives the right answer.",fr:"À quelle fréquence l'IA donne la bonne réponse."},
  "hero.meta":{en:"Each of the {q} validated question(s) is asked in {c} configuration(s), which is {a} attempts in total.",fr:"Chaque question validée ({q}) est posée dans {c} configuration(s), soit {a} tentatives au total."},
  "v.bad":{en:"Often incorrect",fr:"Souvent incorrect"},
  "v.mid":{en:"Mixed results",fr:"Résultats mitigés"},
  "v.good":{en:"Mostly correct",fr:"Majoritairement correct"},

  "kpi.correct":{en:"Correct answers",fr:"Bonnes réponses"},
  "kpi.questions":{en:"Questions tested",fr:"Questions testées"},
  "kpi.configs":{en:"Configurations tested",fr:"Configurations testées"},
  "kpi.cost":{en:"Total cost",fr:"Coût total"},
  "kpi.dc":{en:"To double-check",fr:"À revérifier"},

  "sec.cfg":{en:"By configuration",fr:"Par configuration"},
  "sec.cfg.sub":{en:"Each agent runs in one or more modes. Here is how each one performed.",fr:"Chaque agent s'exécute dans un ou plusieurs modes. Voici la performance de chacun."},
  "m.correct":{en:"Correct answers",fr:"Bonnes réponses"},
  "sm.typical":{en:"Typical response time",fr:"Temps de réponse typique"},
  "sm.slow":{en:"Slow-case response time",fr:"Temps de réponse pire cas"},
  "sm.costq":{en:"Cost per question",fr:"Coût par question"},
  "sm.tech":{en:"Technical failures",fr:"Échecs techniques"},

  "sec.topic":{en:"Correct answers by topic",fr:"Bonnes réponses par sujet"},

  "sec.qq":{en:"Question by question",fr:"Question par question"},
  "qq.filter":{en:"Show only items to double-check",fr:"Afficher seulement les éléments à revérifier"},
  "qq.shown":{en:"{n} answer(s) shown",fr:"{n} réponse(s) affichée(s)"},
  "th.q":{en:"Question",fr:"Question"},
  "th.topic":{en:"Topic",fr:"Sujet"},
  "th.cfg":{en:"Configuration",fr:"Configuration"},
  "th.result":{en:"Result",fr:"Résultat"},
  "th.judge":{en:"AI judge score",fr:"Score du juge IA"},
  "th.rt":{en:"Response time",fr:"Temps de réponse"},
  "th.cost":{en:"Cost",fr:"Coût"},
  "th.dc":{en:"To double-check",fr:"À revérifier"},
  "r.ok":{en:"OK",fr:"OK"},
  "r.bad":{en:"Not OK",fr:"Non OK"},
  "r.plaus":{en:"Plausible",fr:"Plausible"},
  "score.lab":{en:"AI judge score",fr:"Score juge IA"},
  "dc.clear":{en:"Clear",fr:"Aucun"},
  "dc.flag":{en:"Double-check",fr:"À revérifier"},
  "det.show":{en:"Show details",fr:"Voir le détail"},
  "det.hide":{en:"Hide details",fr:"Masquer le détail"},
  "det.judge":{en:"Judge note",fr:"Note du juge"},
  "det.expected":{en:"Expected answer",fr:"Réponse attendue"},
  "det.agent":{en:"Agent answer",fr:"Réponse de l'agent"},

  "ref.measure.h":{en:"How we measure this",fr:"Comment nous mesurons"},
  "ref.measure.p":{en:"We ask the agents a set of validated questions whose correct answers we already know. Each answer is checked automatically and by an independent AI judge. This page shows how often the agents are right, how fast they answer, and what a human should double-check.",fr:"Nous posons aux agents un ensemble de questions validées dont nous connaissons déjà les bonnes réponses. Chaque réponse est vérifiée automatiquement et par un juge IA indépendant. Cette page montre la justesse, la rapidité et ce qu'un humain doit revérifier."},
  "ref.score.h":{en:"How to read the scores",fr:"Comment lire les scores"},
  "ref.score.judge.t":{en:"AI judge score",fr:"Score du juge IA"},
  "ref.score.judge.d":{en:"5 is the closest match to the expected answer, 1 the furthest.",fr:"5 = le plus proche de la réponse attendue, 1 = le plus éloigné."},
  "ref.score.plaus.t":{en:"Plausible",fr:"Plausible"},
  "ref.score.plaus.d":{en:"The judge accepted the answer, but there is no known correct answer to compare against.",fr:"Le juge a accepté la réponse, mais il n'existe pas de réponse correcte connue pour comparer."},
  "ref.score.dc.t":{en:"To double-check",fr:"À revérifier"},
  "ref.score.dc.d":{en:"The automatic check and the AI judge disagreed, so a human should look.",fr:"La vérification automatique et le juge IA sont en désaccord : un humain doit regarder."},
  "ref.modes.h":{en:"What the modes mean",fr:"Que signifient les modes"},
  "ref.modes.p":{en:"Smart, Pro and Claude are AI model tiers, from cheaper and faster to stronger and more expensive.",fr:"Smart, Pro et Claude sont des niveaux de modèle IA, du plus économique et rapide au plus puissant et coûteux."},
  "ref.modes.std":{en:"Standard means the agent runs in a single mode, with no tier to choose.",fr:"Standard signifie que l'agent s'exécute en un seul mode, sans niveau à choisir."},
};
function t(k,v){let s=(DICT[k]&&DICT[k][S.lang])||k; if(v)for(const x in v)s=s.split("{"+x+"}").join(v[x]); return s;}

/* ---------- state ---------- */
const LS="owismind_results_v1";
const RUN = {
  id:"2026-06-26 09:02", 
  correctPct:0.0, right:0, produced:1, configs:1, validatedQ:1, attempts:1,
  totalCost:"$0.01", toDoubleCheck:0,
  configsData:[
    {name:"OWIsMind Orchestrator (DEV)", mode:"smart", questions:1, correctPct:0.0,
     typicalRt:"55.2 s", slowRt:"55.2 s", costPerQ:"$0.0071", techFailPct:"0.0 %"}
  ],
  topics:[
    {name:"revenus", rows:[{agent:"OWIsMind Orchestrator (DEV)", mode:"smart", correctPct:0.0, questions:1}]}
  ],
  questions:[
    {id:"Q001", q:"combien on a fait avec algerie telecom?", topic:"revenus",
     cfg:"OWIsMind Orchestrator (DEV)", mode:"smart", result:"bad",
     score:2, max:5, rt:"55.2 s", cost:"$0.0071", dc:false,
     judgeNote:"incorrect",
     expected:"cette année en 2026, on a fait [montant] EUR avec Algérie Telecom.\n\n**Sources** : Base des revenus clients OWI (DRIVE_Revenues).",
     agent:"Sur le périmètre ACTUALS, toutes périodes confondues, le compte ALGERIE TELECOM a généré un chiffre d'affaires total de [montant] €."}
  ],
};
let S;
try{ S=Object.assign({lang:"en",theme:"light",dcOnly:false}, JSON.parse(localStorage.getItem(LS)||"{}")); }
catch(e){ S={lang:"en",theme:"light",dcOnly:false}; }
function save(){ try{ localStorage.setItem(LS, JSON.stringify({lang:S.lang,theme:S.theme,dcOnly:S.dcOnly})); }catch(e){} }

const MODE_NAME={smart:"Smart",pro:"Pro",claude:"Claude",standard:"Standard"};
const $=(s,r)=>(r||document).querySelector(s);
const $$=(s,r)=>Array.from((r||document).querySelectorAll(s));
function el(t,c,h){const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e;}
function esc(s){return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
function pct(n){return (Math.round(n*10)/10).toFixed(1)+" %";}

function applyI18n(){
  $$("[data-i18n]").forEach(e=>e.textContent=t(e.dataset.i18n));
  document.documentElement.lang=S.lang;
}

/* ---------- donut ---------- */
function renderDonut(){
  const box=$("#donut"); const p=RUN.correctPct; const r=80; const C=2*Math.PI*r;
  const off=C*(1-p/100);
  box.innerHTML=`
    <svg width="188" height="188" viewBox="0 0 188 188">
      <circle cx="94" cy="94" r="${r}" fill="none" stroke="var(--soft-2)" stroke-width="16"/>
      <circle cx="94" cy="94" r="${r}" fill="none" stroke="var(--orange)" stroke-width="16"
        stroke-dasharray="${C}" stroke-dashoffset="${off}" stroke-linecap="butt"/>
    </svg>
    <div class="d-center"><div class="d-pct">${pct(p)}</div><div class="d-lab">${esc(t("hero.correct"))}</div></div>`;
}

/* ---------- hero ---------- */
function renderHero(){
  renderDonut();
  $("#heroHead").innerHTML = esc(t("hero.head",{r:RUN.right,t:RUN.produced}))
    .replace(esc(String(RUN.right)),`<span class="hl">${RUN.right}</span>`)
    .replace(esc(String(RUN.produced)),`<span class="hl">${RUN.produced}</span>`);
  const v=$("#verdict");
  let kind="bad",key="v.bad";
  if(RUN.correctPct>=80){kind="good";key="v.good";} else if(RUN.correctPct>=50){kind="mid";key="v.mid";}
  v.className="verdict "+kind;
  v.innerHTML=`<span class="sq"></span>${esc(t(key))}`;
  $("#heroNote").textContent=t("hero.note");
  $("#heroMeta").innerHTML=esc(t("hero.meta",{q:RUN.validatedQ,c:RUN.configs,a:RUN.attempts}))
    .replace(/(\d+)/g,'<b>$1</b>');
}

/* ---------- kpis ---------- */
function renderKpis(){
  const data=[
    {l:"kpi.correct",v:pct(RUN.correctPct)},
    {l:"kpi.questions",v:RUN.validatedQ},
    {l:"kpi.configs",v:RUN.configs},
    {l:"kpi.cost",v:RUN.totalCost,sm:true},
    {l:"kpi.dc",v:RUN.toDoubleCheck},
  ];
  const box=$("#kpis"); box.innerHTML="";
  data.forEach(d=>{
    box.appendChild(el("div","kpi",
      `<div class="k-top"><span class="k-lab">${esc(t(d.l))}</span><span class="info-i" title="${esc(t(d.l))}">i</span></div>
       <div class="k-val ${d.sm?"sm":""}">${esc(String(d.v))}</div>`));
  });
}

/* ---------- by configuration ---------- */
function renderConfigs(){
  const box=$("#configs"); box.innerHTML="";
  RUN.configsData.forEach(c=>{
    const card=el("div","cfg-card");
    card.innerHTML=`
      <div class="cfg-top">
        <span class="cfg-name">${esc(c.name)}</span>
        <span class="mode-badge mode-${c.mode}"><span class="dot"></span>${esc(MODE_NAME[c.mode])}</span>
        <span class="cfg-q">${c.questions} ${esc(t("th.q")).toLowerCase()}</span>
      </div>
      <div class="meter-row">
        <span class="meter-lab">${esc(t("m.correct"))}</span>
        <span class="meter"><i style="width:${c.correctPct}%"></i></span>
        <span class="meter-val">${pct(c.correctPct)}</span>
      </div>
      <div class="submetrics">
        ${sub("sm.typical",c.typicalRt)}${sub("sm.slow",c.slowRt)}${sub("sm.costq",c.costPerQ)}${sub("sm.tech",c.techFailPct)}
      </div>`;
    box.appendChild(card);
  });
  function sub(k,v){return `<div class="submetric"><div class="sl">${esc(t(k))}<span class="info-i" title="${esc(t(k))}">i</span></div><div class="sv">${esc(v)}</div></div>`;}
}

/* ---------- by topic ---------- */
function renderTopics(){
  const box=$("#topics"); box.innerHTML="";
  RUN.topics.forEach(tp=>{
    const g=el("div","topic");
    let rows="";
    tp.rows.forEach(r=>{
      rows+=`<div class="topic-row">
        <span class="topic-agent"><span class="dot mode-${r.mode}-dot" style="background:var(--m-${r.mode})"></span>${esc(r.agent)} — ${esc(MODE_NAME[r.mode])}</span>
        <span class="meter"><i style="width:${r.correctPct}%"></i></span>
        <span class="meter-val">${pct(r.correctPct)}</span>
        <span class="tq">${r.questions} ${esc(t("th.q")).toLowerCase()}</span>
      </div>`;
    });
    g.innerHTML=`<div class="topic-h">${esc(tp.name)}</div>${rows}`;
    box.appendChild(g);
  });
}

/* ---------- questions table ---------- */
function resultPill(r){
  const map={ok:["result-ok","r.ok"],bad:["result-bad","r.bad"],plaus:["result-plaus","r.plaus"]};
  const m=map[r]||map.plaus;
  return `<span class="result-pill ${m[0]}"><span class="sq"></span>${esc(t(m[1]))}</span>`;
}
function renderQuestions(){
  const tb=$("#qtbody"); tb.innerHTML="";
  let list=RUN.questions.slice();
  if(S.dcOnly) list=list.filter(q=>q.dc);
  $("#shownCount").textContent=t("qq.shown",{n:list.length});
  list.forEach(q=>{
    const tr=el("tr");
    tr.innerHTML=`
      <td data-l="${esc(t("th.q"))}">
        <div class="q-main">${esc(q.q)}</div><div class="q-id">${esc(q.id)}</div>
        <button class="show-details" data-toggle>${I.plus}<span data-det-label>${esc(t("det.show"))}</span></button>
      </td>
      <td data-l="${esc(t("th.topic"))}"><span class="lang-tag">${esc(q.topic)}</span></td>
      <td data-l="${esc(t("th.cfg"))}"><span class="cfg-cell"><span class="dot" style="background:var(--m-${q.mode})"></span>${esc(q.cfg)} ${esc(MODE_NAME[q.mode])}</span></td>
      <td data-l="${esc(t("th.result"))}">${resultPill(q.result)}</td>
      <td data-l="${esc(t("th.judge"))}"><span class="score">${q.score} / ${q.max}<small>${esc(t("score.lab"))}</small></span></td>
      <td class="num" data-l="${esc(t("th.rt"))}">${esc(q.rt)}</td>
      <td class="num" data-l="${esc(t("th.cost"))}">${esc(q.cost)}</td>
      <td data-l="${esc(t("th.dc"))}">${q.dc?`<span class="dc-flag">${I.flag}${esc(t("dc.flag"))}</span>`:`<span class="dc-clear">${esc(t("dc.clear"))}</span>`}</td>`;
    const detail=el("tr","detail-row");
    detail.style.display="none";
    const td=el("td"); td.colSpan=8;
    td.innerHTML=`<div class="detail">
      <div class="d-full"><dt>${esc(t("det.judge"))}</dt><div class="judge-note">${esc(q.judgeNote)}</div></div>
      <div class="answers">
        <div class="ans-box expected"><div class="ans-l">${esc(t("det.expected"))}</div><div class="ans-t">${esc(q.expected)}</div></div>
        <div class="ans-box agent"><div class="ans-l">${esc(t("det.agent"))}</div><div class="ans-t">${esc(q.agent)}</div></div>
      </div></div>`;
    detail.appendChild(td);
    tr.querySelector("[data-toggle]").addEventListener("click",function(){
      const open=detail.style.display==="none";
      detail.style.display=open?"":"none";
      this.querySelector("[data-det-label]").textContent=open?t("det.hide"):t("det.show");
      this.firstChild.outerHTML=open?I.minus:I.plus;
    });
    tb.appendChild(tr); tb.appendChild(detail);
  });
}

/* ---------- run selector ---------- */
function renderRun(){ $("#runId").textContent=RUN.id; }

/* ---------- render all ---------- */
function renderAll(){
  applyI18n();
  $$("#langSeg button").forEach(x=>x.classList.toggle("on",x.dataset.lang===S.lang));
  $$("#themeSeg button").forEach(x=>x.classList.toggle("on",x.dataset.theme===S.theme));
  $("#dcOnly").classList.toggle("on",S.dcOnly);
  renderHero(); renderKpis(); renderConfigs(); renderTopics(); renderQuestions(); renderRun();
  $("#icLogs").innerHTML=I.logs; $("#icSettings").innerHTML=I.gear;
  $$("[data-rail]").forEach(r=>r.innerHTML=I[r.dataset.rail]||"");
}

function init(){
  document.body.dataset.theme=S.theme;
  $$("#langSeg button").forEach(b=>b.addEventListener("click",()=>{S.lang=b.dataset.lang;save();renderAll();}));
  $$("#themeSeg button").forEach(b=>b.addEventListener("click",()=>{S.theme=b.dataset.theme;document.body.dataset.theme=S.theme;save();
    $$("#themeSeg button").forEach(x=>x.classList.toggle("on",x.dataset.theme===S.theme));}));
  $("#dcOnly").addEventListener("click",function(){S.dcOnly=!S.dcOnly;this.classList.toggle("on",S.dcOnly);save();renderQuestions();});
  renderAll();
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",init); else init();
})();
