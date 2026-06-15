# CONTEXT — OWIsMind (mémoire courte, chargée à CHAQUE session)

> Maintenue à jour à chaque `/log-session`. Détail complet → `PROJECT_STATE.md` (§13 = frontend) ; leçons → `LESSONS.md`.
> **OWIsMind** = plugin Dataiku DSS : WebApp **Vue 3 + Vite** (front buildé, servi par DSS) + backend **Flask** modulaire
> (`python-lib/owismind/`) qui parle aux agents via **LLM Mesh** et stocke en **SQL direct** (`SQLExecutor2`, PostgreSQL), **sans Flow** au runtime.

## 🎯 Focus courant
**🤖 AGENTS LANGGRAPH + ARTEFACTS WEBAPP (2026-06-15) — ✅ VALIDÉ DSS (« tout fonctionne comme sur
des roulettes »).** Orchestrateur + sous-agent refondus en **LangGraph** (Code Agents, code env
**3.11**), gpt-5.4-mini (reasoning=high réglé à la main sur le modèle Mesh), appels **natifs Mesh**
dans les nœuds (reasoning + tool-calling préservés ; jamais `as_langchain_chat_model`). Nouveaux
fichiers (à côté des originaux = rollback intact) : `dataiku-agents/agents/orchestrator_langgraph.py`
(boucle agentique **sous-agents-comme-outils** : tools `ask_revenue_expert` + `show_chart` +
`show_table` + `current_date` ; pare-feu d'honnêteté ; réponse dans la langue du dernier message ;
fan-out parallèle) et `dataiku-agents/agents/dataset_expert_langgraph.py` (pipeline en StateGraph,
**moteur SQL byte-identique**, UNDERSTAND force `with_json_output` = fiable, L056). **Feature
artefacts** : l'agent appelle `show_chart`/`show_table` → event gelé `ARTIFACT` → table
`webapp_artifacts_v1` → `/evidence/meta` → onglets **Evidence / Chart / Table** dans le panneau de
droite ; **graphiques Chart.js interactifs** (payload blindé construit côté **Python**
`evidence/chart_payload.py` ; `chart.js` bundlé, installé par l'user). L'agent **commente** au lieu
de reproduire le tableau. Détail → `sessions/2026-06-15.md`, **L055-L057**. Zip : **77 entrées,
`index-Bco4_3i5.js`** — upload + **REDÉMARRER backend** ; coller les 2 Code Agents en **env 3.11** ;
`reasoning=high` sur gpt-5.4-mini dans la connexion Mesh.
**📚 SKILL AGENTIQUE (2026-06-14) — ✅ CRÉÉ + VALIDÉ LOCAL.** Référence d'ingénierie réutilisable
`.claude/skills/agentique-python-dataiku/` (`SKILL.md` + 15 références, ~70k mots) sur LangChain /
LangGraph / Dataiku : choix d'abstraction, orchestration superviseur+sous-agents, design de tools,
mémoire/persistance, RAG, MCP, éval/gouvernance, anti-patterns. **Encart central = double chemin
Python 3.9/3.11** (L054). Construit par 3 workflows (recherche → fabrication → validation 6/6).
Claims DSS-réels marqués `UNVERIFIED` (import `DKUChatModel`, API semantic model) → à lever sur
l'instance. Corpus `agentic-research/` gitignoré (provenance). Détail → `sessions/2026-06-14.md`, L053-L054.
**0★★) SYSTÈME D'AGENTS v3 « dataiku-agents/ » — ✅ VALIDÉ DSS (2026-06-12, « ça marche super
bien »).** Architecture HYBRIDE tranchée par A/B user : **le Semantic Model Query tool garde le
SQL** (`SQL_ENGINE="semantic_tool"`, tool `v4oqA6R`, mode Agent), et le **Dataset Expert générique**
(`agent:AKQaQ0Am`) est sa tour de contrôle : UNDERSTAND généré du profil (recette Flow + overrides
humains) → RESOLVE sur `<ds>_value_index` (valeurs exactes) → COMPOSE (« la QUESTION USER MÈNE » +
intent hint + valeurs groupées `IN` par colonne + règle énumération→OR/une-ligne-par-item +
scénario/période + note destination) → QUERY (extraction mode-Agent : priorité de clés + DERNIER
texte/lignes) → RENDER vérifié. Moteur SQL direct (templates 9 intents + LLM gardé + read-only)
conservé en **fallback technique** (`FALLBACK_TO_DIRECT`). Orchestrateur v3 = v2.4 + fan-out
parallèle ; registre basculé `revenue_expert=True` / `salesdrive_v2=False`. 127+86+55 tests.
Résumé du dossier → `dataiku-agents/CLAUDE.md` ; détail → L051-L052 + `sessions/2026-06-12.md`.
**Prochaine session : le SEMANTIC MODEL lui-même** (id modèle `2O2KcHw`, config scriptable
`get_raw()`/`save()`) — corriger `Phase='ACTUAL'`→`'ACTUALS'` (description + filtre « Actual
Revenue Only ») et le synonyme « roaming hub » sur Roaming Sponsor (produit différent), versionner
le JSON au repo, golden queries depuis le corpus.
**0★) ORCHESTRATEUR « EXPERT AUTHORITY » v2.4 (Run 5 2026-06-11) — ⏳ CODÉ + TESTÉ LOCAL (86 unittest),
NON validé DSS.** Corrige le défaut CENTRAL (confirmé sur `docs/questions_asked.md`, 817 q. réelles,
~10 engueulades même cause) : l'orchestrateur **niait/inventait au lieu de router** (« budget 2026 » →
« I don't have budget data » sans appeler l'agent). Fix = il **n'émet jamais un fait métier** ; seul
« non » = « pas d'agent pour ce DOMAINE » (jamais « la donnée n'existe pas ») ; dans le doute → router.
`CAPABILITY_GAP`/`OUT_OF_SCOPE` = **templates déterministes** ; nouvel intent `CONCEPT` ; **registre =
manifeste** (`{id,label,description,domain}` + `BUSINESS_DOMAINS`) ; **manifeste revenus pleine-vérité**
(actuals/budget/forecast/Q3F/HLF) + **test anti-dérive** vs `salesdrive_agent.KNOWN_PHASES`. Coût LLM
inchangé. **Réconcilié** : registre repo bascule sur le Code Agent v2 `agent:MODpGFcC` (visuel `rNTZ781a`
désactivé) → **coller `orchestrator/orchestrator_agent.py` en DSS direct**, puis smoke-tests (budget→route,
tickets→gap honnête jamais 0, météo→hors-sujet, ellipse→route, SS7/LTE→concept). Niveaux 2 (refus→offres)
+ 3 (exploration) + parallélisme = DIFFÉRÉS. Détail → L050 + spec
`docs/superpowers/specs/2026-06-11-orchestrator-expert-authority-design.md`.
**0) SUIVI TOKENS & COÛTS (Run 4 2026-06-11) — ⏳ CODÉ + TESTÉ LOCAL, NON validé DSS.** Ligne
`↑ in · ↓ out tokens · ~$coût` sous chaque réponse (tous users) ; stockage 3 niveaux : `webapp_chat_v5`
(source de vérité par échange, 4 colonnes usage) + `users` ALTER (cumul lifetime) + `webapp_usage_monthly_v1`
(PK `(user_id, mois)`, UPSERT incrémental → quota mensuel = 1 lecture par clé). `storage/usage.record_usage`
(2 incréments en 1 transaction, best-effort). **Limite 50 $/mois PAS implémentée** (juste le stockage prêt :
hook `/chat/start` avant `start_run`). Détail → L049 + `sessions/2026-06-11.md` Run 4. Zip prêt : **75
entrées, `index-WWBrb0uj.js`** — upload + **REDÉMARRER backend** (tables/colonnes auto au 1er usage ;
anciennes convs v4 invisibles, assumé).
**1) MISSION « Evidence Studio v2 TRUST LAYER » — 🟡 ÇA MARCHE (retour user) MAIS PAS ENCORE COMME
IL VEUT : ajustements NON PRÉCISÉS, à recueillir EN PREMIER (badge ? wording ? résultat capturé ?
drill ? layout ?) AVANT de toucher au code.**
**2) SALESDRIVE v2 (Code Agent) — ✅ DÉPLOYÉ ET VALIDÉ USER (« tout marche », 2026-06-11)** :
le sous-agent visuel `agent:rNTZ781a` est porté en **Code Agent déterministe** `agent:MODpGFcC`
(`salesdrive/salesdrive_agent.py`, à coller dans DSS) piloté par l'**orchestrateur v2.3**
(`orchestrator/orchestrator_agent.py`). Pipeline UNDERSTAND (1 LLM JSON strict) → RESOLVE (tool
`aNxeOc4`, routing Python) → COMPOSE (semantic_question par **templates gelés**, jamais LLM) →
QUERY (tool `v4oqA6R` via `get_agent_tool().run()`, SQL+rows capturés du **retour**, input_key
auto-détecté) → RENDER (table/montants par code + accroche LLM **vérifiée chiffre par chiffre**).
Désambiguïsation générique 3 étages (L048) : continuité conversationnelle (`pass_context`) +
valeur-exacte/priorité-colonne + round-trip « VALEUR (Colonne) ». Visual v1 intact (bascule = 2
flags `enabled`, une seule capability revenue visible à la fois).
1. **Panneau preuve en 7 sections** : badge de vérification déterministe (plein=certifié / pointillé=
   partiel / gris=déclaré, JAMAIS vert) → sources → chips (F20 intact) → « Comment ce résultat est
   calculé » (steps métier i18n) → résultat EXACT capturé (mini-table + drill par ligne) → bandeau drill
   → exploration source (table F20) → SQL replié (« Détails techniques »).
2. **Backend** : `evidence/sql_explain.py` (explication structurée PURE) + `evidence/capture.py`
   (résultat exact opportuniste, caps miroir) ; meta enrichie ; `/evidence/rows` + `drill`
   (re-validé serveur, refus >8 clés) ; `SET LOCAL transaction_read_only` ; cap JSON à l'écriture ;
   `result` projeté HORS de `/conversation`. Spec gelée :
   `docs/superpowers/specs/2026-06-10-evidence-trust-layer-design.md` · doc : `docs/evidence-trust-layer.md`.
3. **Timeline** : labels humains du backend (eventData.label whitelisté) prioritaires sur le registre.
   Zip prêt : `ready-for-dataiku/owismind-upload.zip` (**75 entrées, `index-WWBrb0uj.js`** — Run 4 usage).
   ⚠️ **Backend modifié → REDÉMARRER le backend après upload.** Orchestrateur/SalesDrive modifiés →
   **recoller les 2 fichiers** dans leurs Code Agents DSS (repo = source de vérité, L047).
**Avant (Run 4 2026-06-10)** : layout droite + best-effort + chips ⏳ jamais validés DSS — le zip 74
entrées les INCLUT (tester ensemble). **Avant** : Evidence v1 ✅ DSS (L035-L037) ; V1+4 lots ✅ DSS ;
stockage = `webapp_chat_v5` (items generated_sql enrichis sql_id/step_index/agent_key/result + Run 4 :
4 colonnes usage input/output/total tokens + estimated_cost).

## 🧭 Dernière session — 2026-06-15 → détail `sessions/2026-06-15.md`, leçons **L055-L057**
- **Agents en LangGraph (orchestrateur + sous-agent) ✅ VALIDÉ DSS** : nœuds **sync** +
  `get_stream_writer` + `graph.stream(custom)` + appels **natifs Mesh** ; le log DSS prouve que
  LangGraph tourne sur le Code Agent 3.11 (lève les 2 `UNVERIFIED` de la revue) (L055).
- **Bug clé corrigé** : reasoning=high + extraction JSON sans `with_json_output` → ~15 s puis parse
  cassé → erreur interne. Fix = **forcer le JSON sur UNDERSTAND**, garder le reasoning pour
  routing/headline (L056). Fallback UNDERSTAND : claude-sonnet-4-6.
- **Artefacts webapp** : tool `show_chart`/`show_table` → event `ARTIFACT` → `webapp_artifacts_v1` →
  `/evidence/meta` → onglets + **Chart.js** (payload Python blindé `chart_payload.py`) ; l'agent
  commente (L057). Build+zip refaits (Chart.js bundlé) ; revue sécurité Opus sans bloqueur.

## Avant — 2026-06-14 → détail `sessions/2026-06-14.md`, leçons **L053-L054**
- **Skill d'agentique créé** : `.claude/skills/agentique-python-dataiku/` (`SKILL.md` + 15 références)
  via 3 workflows (recherche 24 agents → corpus 23 briefs `agentic-research/` ; fabrication 36 agents
  draft→revue→fix ; validation 13 agents **6/6, 0 piège**). Réconciliation corpus + source ChatGPT.
- **Double chemin Python 3.9/3.11** (correction autorité user, L054) = encart central ; vérité des versions
  (`create_agent` pas `create_react_agent`, `recursion_limit=25`, `astream_events` v2…) intégrée.
- 5 cross-références frères cassées (noms ChatGPT vs slugs réels) → corrigées + vérifiées (L053).
  ⏳ Skill = **référence**, pas du code déployé ; claims DSS marqués `UNVERIFIED`.

## Avant — 2026-06-12 (2 runs) → détail `sessions/2026-06-12.md`, leçons **L051-L052**
- **Run 1 (nuit)** : construction complète du système v3 (2 recettes Flow, Dataset Expert, orchestrateur
  parallèle, README) après recherche 6 agents (SOTA NL2SQL, semantic model 14.4 scriptable, corpus).
- **Run 2 (jour)** : validation DSS avec l'user + bascule moteur HYBRIDE semantic-tool (A/B) ; fixes
  réels : LEFT(date) cast-safe, extraction mode-Agent dernier-gagnant, énumérations IN/OR. ✅ VALIDÉ.

## Avant — 2026-06-11 (5 runs) → détail `sessions/2026-06-11.md`, leçons **L044-L050**
- **Run 1-2** : trust layer v2 déployé (revue 26 agents, 17/17 corrigés) ; nettoyage repo + git init +
  knowledge graph 2 494 nœuds + fraîcheur auto (L044-L046).
- **Run 3 — SalesDrive v2** : Code Agent complet + orchestrateur v2.3 (AGENT_RESULT structuré, skip
  Sources sur clarification, `pass_context`) ; incident boucle IPL diagnostiqué sur traces CSV réelles
  → fix générique (L048) ; capture Evidence déterministe via retour de tool (L047). 55+62 unittest · validé DSS.
- **Run 4 — Suivi tokens & coûts** : `chat_v4`→`chat_v5` (+4 colonnes usage), `users` ALTER cumul,
  `webapp_usage_monthly_v1` (quota mensuel O(1)), `storage/usage.py`, ligne front `MessageAgent`. 322
  unittest + 102 node:test + Vite OK ; **non validé DSS** (L049).
- **Run 5 — Orchestrateur « Expert Authority » v2.4** : pare-feu d'honnêteté (jamais de fait métier ;
  router pas nier ; `CAPABILITY_GAP`/`OUT_OF_SCOPE` déterministes ; intent `CONCEPT`), registre=manifeste
  + `BUSINESS_DOMAINS`, manifeste revenus pleine-vérité + test anti-dérive, bascule registre sur v2
  `agent:MODpGFcC`. 86 unittest verts ; **non validé DSS** (routing LLM) (L050). Feedback : **plans
  verbeux interdits** (exécuter direct).

## ⚠️ Top gotchas / règles actives
**Process :**
- **P0 — dataiku-agents v3 (L051/L052)** : l'expertise vient des ARTEFACTS du Flow (profil + value
  index, overrides humains jamais écrasés) — pas de valeur métier dans le repo. Le SQL appartient au
  SEMANTIC MODEL (tool mode Agent) : extraction = priorité de clés + DERNIER texte/lignes (jamais le
  premier = préambule) ; question sémantique = question user EN TÊTE + `IN` par colonne (jamais AND
  intra-colonne). UNE capability revenue `enabled` à la fois. Contrats gelés : `KNOWN_BLOCK_IDS`/
  `KNOWN_TOOL_NAMES` ↔ registre (test anti-dérive) ; norm partagée recettes↔agent. Tests :
  `python3 -m unittest discover -s dataiku-agents/tests`.
- **P0★ — Agents LangGraph (L055/L056, ✅ DSS)** : les Code Agents `*_langgraph.py` tournent en env
  **3.11** (langchain/langgraph installés). Appels LLM **natifs Mesh** dans les nœuds (jamais
  `as_langchain_chat_model`) ; `get_stream_writer()` en nœud SYNC OK ; `reasoning=high` réglé à la
  main sur le modèle Mesh. **`with_json_output` OBLIGATOIRE sur les extractions déterministes**
  (UNDERSTAND) — sinon le reasoning brûle le budget et casse le parse ; reasoning réservé au routing
  (orchestrateur tool-calling) et à la headline vérifiée. Originaux `*_agent.py` = rollback intact.
- **P1 — Graphe (L046)** : naviguer = `graphify query` D'ABORD (sous-agents aussi) ; exclusions corpus =
  `.graphifyignore` versionné. Tests front : `node --test test/*.test.js` depuis `Plugin/owismind/frontend/`.
- **P2 — Fin de session** : `/log-session` = mémoire + `/graphify --update` + **commit de session**
  (autorisation user permanente 2026-06-11) ; **JAMAIS de push** (l'user pushe).
- **P3 — Anti-« règles par bug » (L048, exigence user)** : jamais de valeur métier en dur dans la
  logique d'un agent. Cas inconnus → compréhension LLM contrainte (liste de candidats) ou refus
  honnête, pas de patch par valeur.

**Frontend :**
- **F1 — Validation locale** : compile-check = `./node_modules/.bin/vite build --outDir /tmp/owi_bc --emptyOutDir` puis `rm -rf` (**jamais** dans `resource/` avant `/build-plugin`). **NO INSTALL** (tests = `node:test` + `unittest`).
- **F2 — `:global` thème (L022)** : sélecteur **entier** dans `:global(body[data-theme="dark"] .x)`. **Pas de `color-mix`** (L031) : `rgba` + tokens. Texte orange = **`--orange-text`** (AA, L039) ; fond teinté = `--orange-soft-dark`.
- **F3 — Router HASH** ; **F4 — thème** `body[data-theme]` avant mount ; **F5 — réactivité** version = `reactive()` mutée via `applyEvent`.
- **F6 — i18n** : interpolation **liste** `t('k',[a])` ; ajouts domaine dans `extra.js` (clé-plate par locale, fr+en) ; `messages.json` pristine.
- **F8 — Timeline (L029/L039)** : reducer pur `timelineModel.js` inchangé ; l'affichage groupé/ticker = **sélecteurs purs read-only** → ids stables, `timelineSignature` intacte.
- **F10 — Build : recâbler `body.html`** via l'outil **`Write`** (le `cp` est refusé par les permissions, L033). Le `cp -R` du packaging passe.
- **F11 — Tests front purs** : reducer/clamp/arbre/agentPick/sélecteurs timeline/evidencePick sans Vue → `node:test`.
- **F12 — ARBRE (L032)** : éditer/régénérer = échange FRÈRE ; `v-for` keyé `uid` stable ; un changement de version **REMOUNT** MessageAgent.
- **F13 — Scroll (L032/L038)** : `ChatThread` ne scrolle que sur `activeSessionId`, `exchanges.length`, signature gated `sending`, et **`evidence.open`**. **Jamais** de watch sur `turns`.
- **F19 — Layout Evidence (L043)** : grille `sidebar | chat 1fr | Evidence droite` ; repli sidebar = **`setSidebarCollapsed(true, false)`** ; re-clamp `evidenceW` sur resize ; `.ev-chips { z-index:5 }`.
- **F20 — Chips (L043)** : TOUS éditables ; présélection picker SEULEMENT pour `=`/`IN` ; `exclude_id` au distinct ; caps miroir backend ; reset/remove ferment le popover.
- **F14 — Feedback (L031)** ; **F15 — Agent persistant (L032)** : inchangés.
- **F16 — Ticker live (L039)** : `TransitionGroup` avec **`appear`** ; **UN** `.stream` persistant ; reduced-motion via `content:none`.
- **F17 — Navigation (L040)** : URL stampée `/chat/<sid>` au 1er échange ; route→store via **`chat.ensureSession`** ; un run live survit à un aller-retour Settings ; `canSend` exige `!threadLoading && !threadError`.
- **F18 — Chrono étapes (L041)** : durées scellées = stamps backend ; interval gaté `activityLive && chat.sending` ; markdown memoïzé.
- **F21 — Trust layer (L045)** : meta v1 ⇒ rendu identique ; badge via `trustLevel(meta)` pur ; steps `t('ev.exp.'+kind, params)` kind inconnu→opaque ; drill = `buildDrillLabels` (abort si >8 clés) ; aucune section nouvelle avec z-index ≥5.
- **F22 — Artefacts (L057, ✅ DSS)** : onglets Evidence/Chart/Table via `Tabs.vue` dans `EvidencePanel` ; `ArtifactChart.vue` = **Chart.js** (`chart.js/auto`, dep bundlée), couleurs résolues du thème + re-render au changement de thème ; `ArtifactTable.vue` = résultat capturé. Changer d'onglet ne touche PAS `evidence.open` (F13). Payload chart fourni par le backend (`data`).

**Backend (validé DSS sauf mention) :**
1. **Whitelist agents** (L017/L018) : front = `{key,label}` ; résolution serveur.
2. **Streaming = POLLING-via-thread** (L019) : `/chat/start`→`/chat/poll` 500 ms ; stop coopératif (L034).
3. **Contexte agent** (L032) : préfixe user construit à CHAQUE `/chat/start`, collé au message COURANT seulement ; historique rejoué brut ; message stocké **brut**.
4. **Feedback** (L031) : UPDATE owner-scopé. 5. **Trace** = dataset Flow append (L027/L028).
6. **Nommage tables** (L008/L014) : `_vN` jamais d'ALTER ; `rows_to_json_safe` (L013).
7. **Sûreté** : SQL paramétré + COMMIT + bornes ; pas de Flow/route SQL générique ; **Python 3.9**.
8. **Ne pas éditer** `resource/owismind-app/` ni `ready-for-dataiku/` (générés).
9. **Evidence (L035-L037 ✅ DSS / L042 ⏳ / L045 ⏳)** : découverte auto des datasets PostgreSQL ;
   parseur BEST-EFFORT (L042) ; `statement_timeout 30s` + `transaction_read_only` (L045).
   ⚠️ MULTISELECT ne se rend pas dans les Settings DSS (L037).
10. **Trust layer (L045 ⏳)** : `sql_explain` PUR never-raises ; niveaux déterministes ; drill
   re-dérivé du SQL stocké ; capture = enrichissement JSON `generated_sql`, caps au point d'écriture ;
   fusion footer↔relay ONE-SHOT.
11. **SalesDrive v2 + orchestrateur v2.3 (L047/L048 ✅ DSS)** : repo = source de vérité, coller les
   2 fichiers ENSEMBLE (le fix désambiguïsation vit des 2 côtés : `pass_context` orchestrateur +
   UNDERSTAND agent). Tools : resolver `aNxeOc4`, semantic `v4oqA6R` (`get_agent_tool(id).run()`,
   noms — pas ids — dans les events pour les labels). Span `semantic-model-query` recréé par le code
   au contrat gelé. `AGENT_RESULT` = statut machine (jamais affiché). UNE seule capability revenue
   `enabled` à la fois. Tests : `python3 -m unittest discover -s salesdrive/tests` (+ orchestrator/tests).
12. **Artefacts (L057 ✅ DSS)** : event gelé `ARTIFACT` (le whitelist timeline droppe les champs →
   event `artifact` normalisé dans `agents/streaming.py`) ; specs persistés dans **`webapp_artifacts_v1`**
   (table neuve `_v1`, UPSERT owner-stamped, lecture **read-only + statement_timeout**) ;
   `/evidence/meta` renvoie `artifacts` + pour chaque chart un `data` (payload Chart.js construit en
   **Python** `evidence/chart_payload.py`). Donnée = `generated_sql[].result` déjà capturé ; l'agent
   ne fournit que x/y/type/style. Best-effort (un échec de stockage ne casse jamais la réponse).

## 🔜 Prochaines étapes
0★. **Agents LangGraph + artefacts ✅ FAITS & validés DSS** (L055-L057) — surveiller le fan-out
   parallèle réel au 2ᵉ sous-agent ; affiner le prompt orchestrateur s'il recopie un tableau au lieu
   d'appeler `show_table` ; envisager d'autres types de graph (style) au fil de l'usage.
0skill. **Skill agentique** : lever les `UNVERIFIED` en confirmant sur l'instance (import `DKUChatModel` vs
   `as_langchain_chat_model()`, API `project.get_semantic_model`, ids de modèles non-Anthropic) ; promotion
   en global (`~/.claude/skills/`) si réutilisation cross-projets souhaitée (simple copie).
0. **SESSION SEMANTIC MODEL (priorité, demandée par l'user)** : modèle `2O2KcHw`, config scriptable
   (`project.get_semantic_model` → `get_raw()`/`save()` + versions). Corriger `Phase='ACTUAL'`→
   `'ACTUALS'` (description entité + filtre « Actual Revenue Only ») et le synonyme « roaming hub »
   sur le terme Roaming Sponsor ; versionner le JSON au repo ; enrichir les golden queries depuis
   `docs/questions_asked.md` ; aligner glossaire ↔ profil.
0bis. Poursuivre les smoke tests README §5 au fil de l'usage (part du total, YoY, trend, ellipses,
   « IPL » ambigu) ; toute divergence → profil/overrides/prompts, jamais de valeur en dur (P3).
0ter. **Agent tickets** (2 recettes + 1 Code Agent + 1 entrée registre) → débloque le 360 parallèle.
1. **RECUEILLIR LES AJUSTEMENTS du user sur le trust layer** : « marche bien mais pas
   encore comme je veux » — faire préciser AVANT toute modification.
2. **SalesDrive v2 — consolidation** : tester un cas de vraie ambiguïté de valeur (ex. « IPL + ») et
   un plan multi-étapes (agent+tool) ; quand confiance OK → retirer l'entrée visual `salesdrive` du
   registre ; supprimer le CSV de traces local (`salesdrive/webapp_devtest-…csv`, hors repo).
3. Re-tester en DSS ce qui ne l'a jamais été : L040 (bouton New conversation) / L041 (chrono étapes).
4. **Evidence v3 (différé)** : restriction admin des datasets, keyset pagination, drill multi-requêtes,
   fraîcheur des sources ; fallback LLM seulement sur cas réel.
5. **2ᵉ task mentionnée par l'user le 2026-06-09** — toujours à clarifier.
