# CONTEXT — OWIsMind (mémoire courte, chargée à CHAQUE session)

> Maintenue à jour à chaque `/log-session`. Détail complet → `PROJECT_STATE.md` (§13 = frontend) ; leçons → `LESSONS.md`.
> **OWIsMind** = plugin Dataiku DSS : WebApp **Vue 3 + Vite** (front buildé, servi par DSS) + backend **Flask** modulaire
> (`python-lib/owismind/`) qui parle aux agents via **LLM Mesh** et stocke en **SQL direct** (`SQLExecutor2`, PostgreSQL), **sans Flow** au runtime.

## 🎯 Focus courant
**MISSION 2026-06-11 « Evidence Studio v2 TRUST LAYER » — 🟡 ÇA MARCHE (retour user) MAIS PAS ENCORE
COMME IL VEUT : ajustements NON PRÉCISÉS, à recueillir EN PREMIER à la prochaine session (badge ?
wording des étapes ? résultat capturé ? drill ? layout ?) AVANT de toucher au code.**
1. **Panneau preuve en 7 sections** : badge de vérification déterministe (plein=certifié / pointillé=
   partiel / gris=déclaré, JAMAIS vert) → sources → chips (F20 intact) → « Comment ce résultat est
   calculé » (steps métier i18n) → résultat EXACT capturé (mini-table + drill par ligne) → bandeau drill
   → exploration source (table F20) → SQL replié (« Détails techniques »).
2. **Backend** : `evidence/sql_explain.py` (explication structurée PURE : steps {kind,params} enum gelé,
   flags, group_keys à lineage NOM-SOURCE) + `evidence/capture.py` (résultat exact opportuniste, caps
   miroir) ; meta enrichie (`source/queries/verification/explanation/result/drilldown`) ; `/evidence/rows`
   + `drill` (re-validé serveur, refus >8 clés) ; `SET LOCAL transaction_read_only` ; cap JSON à l'écriture ;
   `result` projeté HORS de `/conversation`. Niveaux : declared→source_identified→scope_partial→
   scope_exact→calc_decomposed + result_captured (orthogonal). Spec gelée :
   `docs/superpowers/specs/2026-06-10-evidence-trust-layer-design.md` · doc : `docs/evidence-trust-layer.md`.
3. **Orchestrateur v2.2** (`orchestrator/orchestrator_agent.py` — à COLLER dans le Code Agent DSS) :
   tags sql_id/step_index/agent_key + capture result capée dans AGENT_DONE ; fuites corrigées (agentId,
   str(e), URL intranet→labels métier) ; depth-guards ; audit `orchestrator/AUDIT.md`.
4. **Timeline** : labels humains du backend (eventData.label whitelisté) prioritaires sur le registre.
   Zip prêt : `ready-for-dataiku/owismind-upload.zip` (**74 entrées, `index-DF9WrJFi.js`**).
   ⚠️ **Backend modifié → REDÉMARRER le backend après upload + coller l'orchestrateur v2.2.**
   ⚠️ La clé des LIGNES dans outputs du tool semantic-model-query N'EST PAS confirmée sur l'instance →
   vérifier sur une trace réelle (dataset traces) ; sinon `result_captured:false` partout (dégradé honnête).
**Avant (Run 4 2026-06-10)** : layout droite + best-effort + chips ⏳ jamais validés DSS — le zip 74
entrées les INCLUT (tester ensemble). **Avant** : Evidence v1 ✅ DSS (L035-L037) ; V1+4 lots ✅ DSS ;
stockage = `webapp_chat_v4` (items generated_sql désormais enrichis sql_id/step_index/agent_key/result).

## 🧭 Dernière session — 2026-06-10→11 Trust layer → détail `sessions/2026-06-11.md`, leçons **L044-L045**
- Mission complète : exploration (4 spécialistes) → contrat gelé → implémentation (6 chantiers ;
  sql_explain écrit EN DIRECT après 2 morts d'agents à 64k output tokens — L044) → revue adversariale
  (26 agents) : **17 findings confirmés → 17 corrigés** (FP-01/02 high : where_complete divergent du
  fragment réel, self-join via CTE ; lineage nom-source ; caps drill refus-pas-troncature… — L045).
- Preuve : **304 unittest** + **59 orchestrateur** + **97 node:test** · compileall + py3.9 ast · vite
  build · zip 74 entrées · visuel Chrome DevTools light+dark (captures purgées au nettoyage), console 0 erreur.
- **Retour user post-déploiement : « ça marche bien mais pas encore comme je veux »** — fonctionnel,
  ajustements attendus non détaillés (à clarifier avant tout code).
- **Nettoyage repo (2026-06-11)** : `maquette/` (~12 k lignes), `docs/superpowers/plans/`, `.demo-screens/`,
  `.DS_Store` **supprimés** ; specs gelées conservées ; refs recousues (CLAUDE.md ×2, docs, PROJECT_STATE §9,
  note LESSONS) ; 13 fichiers source purgés des citations mortes (docs/0X §, assets-v5) — 97/97 node:test, vite OK.
- **Git + graphe (2026-06-11)** : `git init` + commit initial `3bd804f` (211 fichiers, main) ; knowledge graph
  `graphify-out/` construit (1 969 nœuds / 3 443 arêtes, **18,4× moins de tokens/requête**, git-ignoré) —
  l'interroger D'ABORD pour naviguer (`graphify query "…"`). Fraîcheur câblée : hook git **post-commit**
  (rebuild AST auto, sans LLM) + `/log-session` enrichi (`/graphify --update` + **commit de session** —
  autorisation user permanente ; JAMAIS de push).

## ⚠️ Top gotchas / règles actives
**Frontend :**
- **F1 — Validation locale** : compile-check = `./node_modules/.bin/vite build --outDir /tmp/owi_bc --emptyOutDir` puis `rm -rf` (**jamais** dans `resource/` avant `/build-plugin`). **NO INSTALL** (tests = `node:test` + `unittest`).
- **F2 — `:global` thème (L022)** : sélecteur **entier** dans `:global(body[data-theme="dark"] .x)`. **Pas de `color-mix`** (L031) : `rgba` + tokens. Texte orange = **`--orange-text`** (AA, L039) ; fond teinté = `--orange-soft-dark`.
- **F3 — Router HASH** ; **F4 — thème** `body[data-theme]` avant mount ; **F5 — réactivité** version = `reactive()` mutée via `applyEvent`.
- **F6 — i18n** : interpolation **liste** `t('k',[a])` ; ajouts domaine dans `extra.js` (clé-plate par locale, fr+en) ; `messages.json` pristine.
- **F8 — Timeline (L029/L039)** : reducer pur `timelineModel.js` inchangé ; l'affichage groupé/ticker = **sélecteurs purs read-only** (`timelineEvents/BodyItems/Segments/activitySummary/stepStampDiff`) → ids stables, `timelineSignature` intacte.
- **F10 — Build : recâbler `body.html`** via l'outil **`Write`** (le `cp` est refusé par les permissions, L033). Le `cp -R` du packaging passe.
- **F11 — Tests front purs** : reducer/clamp/arbre/agentPick/**sélecteurs timeline**/**evidencePick** sans Vue → `node:test`.
- **F12 — ARBRE (L032)** : éditer/régénérer = échange FRÈRE ; `v-for` keyé `uid` stable ; un changement de version **REMOUNT** MessageAgent (état local réinitialisé — ne jamais compter sur un watch pour les switches de siblings).
- **F13 — Scroll (L032/L038)** : `ChatThread` ne scrolle que sur `activeSessionId`, `exchanges.length`, signature gated `sending`, et **`evidence.open`** (post-flush, stick-gated — le snap 2↔3 colonnes invalide le bas). **Jamais** de watch sur `turns`.
- **F19 — Layout Evidence (Run 4, L043)** : grille `sidebar | chat 1fr | Evidence droite (--evidence-w, store `evidenceW`)` ; repli auto sidebar à l'ouverture = **`setSidebarCollapsed(true, false)`** (jamais persisté) ; re-clamp `evidenceW` sur resize ; popover chips au-dessus de la table via `.ev-chips { z-index:5 }` (stacking contexts des animations `ev-rise`).
- **F20 — Chips (L043)** : TOUS éditables (conversion `=`/`IN`) ; présélection picker SEULEMENT pour `=`/`IN` (anti-inversion des ops négatifs) ; `exclude_id` au distinct ; caps miroir backend (50 valeurs `ev.picker.max`, 20 filtres, page 20 + écho `data.page`) ; reset/remove ferment le popover.
- **F14 — Feedback (L031)** ; **F15 — Agent persistant (L032)** : inchangés.
- **F16 — Ticker live (L039)** : `TransitionGroup` avec **`appear`** ; `.tick-leave-active + .tick-leave-active { transition:none; opacity:0 }` (évictions en batch superposées) ; **UN** `.stream` persistant (deux branches v-if = remount + replay d'animation) ; reduced-motion : un pseudo-élément 100 % keyframes → `content:none` (pas `animation:none`).
- **F17 — Navigation (L040)** : route param-less + `push` même route = **navigation dupliquée invisible** au watcher. L'URL est **stampée** `/chat/<sid>` au 1er échange ; route→store passe par **`chat.ensureSession`** (skip refetch si fil sain : gardes `threadLoading/threadError`) ; un run live **survit** à un aller-retour Settings ; bump sidebar = données **capturées à l'entrée du run** ; `canSend` exige `!threadLoading && !threadError`.
- **F18 — Chrono étapes (L041)** : durées scellées = **stamps backend** (`stepStampDiff`), horloge cliente = tick live seulement ; interval gaté `activityLive && chat.sending` ; markdown **memoïzé** par item (10 Hz).
- **F21 — Trust layer (L045)** : nouveaux champs meta TOUS optionnels (meta v1 ⇒ rendu identique) ; badge via `trustLevel(meta)` pur (`evidenceProof.js`) ; steps rendus `t('ev.exp.'+kind, params)` kind inconnu→opaque ; drill = `buildDrillLabels` (abort null si >8 clés ou colonne non mappée — JAMAIS tronquer) ; re-drill préserve le snapshot d'origine ; aucune section nouvelle avec z-index ≥5 (popover chips) ; le drill voyage en `{column, value}` re-validés serveur.

**Backend (validé DSS sauf mention) :**
1. **Whitelist agents** (L017/L018) : front = `{key,label}` ; résolution serveur.
2. **Streaming = POLLING-via-thread** (L019) : `/chat/start`→`/chat/poll` 500 ms ; stop coopératif (L034).
3. **Contexte agent** (L032) : chaîne d'ancêtres CTE bornée ; préfixe `[User: Prénom Nom — Date: …]`
   construit à CHAQUE `/chat/start` (`derive_full_name` + `build_user_prefix`), collé au message COURANT
   seulement ; historique rejoué brut ; message stocké **brut**.
4. **Feedback** (L031) : UPDATE owner-scopé. 5. **Trace** = dataset Flow append (L027/L028).
6. **Nommage tables** (L008/L014) : `_vN` jamais d'ALTER ; `rows_to_json_safe` (L013).
7. **Sûreté** : SQL paramétré + COMMIT + bornes ; pas de Flow/route SQL générique ; **Python 3.9**.
8. **Ne pas éditer** `resource/owismind-app/` ni `ready-for-dataiku/` (générés).
9. **Evidence (L035-L037 ✅ DSS / L042 ⏳ / L045 ⏳)** : découverte auto des datasets PostgreSQL du projet ;
   front n'envoie jamais de SQL. **Parseur BEST-EFFORT (L042)** : scopes SELECT, `tables[]` matchées en
   ordre, prédicats droppés si non mappables (jamais de blocage) ; fragment avancé = mono-table only ;
   `statement_timeout 30s` + `transaction_read_only` (L045), guard+throttle communs. **`/evidence/agent-view`
   SUPPRIMÉ** (Run 4). ⚠️ MULTISELECT ne se rend pas dans les Settings DSS (L037) — utiliser SELECT/STRINGS.
10. **Trust layer (L045 ⏳)** : `sql_explain` PUR (never-raises, sous-revendique toujours — l'adaptateur
   `normalize_explain` du service ne peut qu'abaisser le niveau) ; niveaux déterministes, JAMAIS de
   « vérifié » sans critère mécanique ; drill re-dérivé du SQL stocké (jamais de confiance client, refus
   >8 clés) ; capture du résultat = enrichissement JSON `generated_sql` (zéro migration), caps au point
   d'écriture via `capture.cap_sql_list` (JAMAIS `_bounded()` sur du JSON), `result` exclu de `/conversation` ;
   fusion footer↔relay ONE-SHOT (pop) — jamais de dédup trace↔trace par texte (L045 §6).

## 🔜 Prochaines étapes
1. **RECUEILLIR LES AJUSTEMENTS du user (priorité 1)** : le trust layer déployé « marche bien mais pas
   encore comme il veut » — faire préciser CE qui ne va pas (badge ? wording « Comment ce résultat est
   calculé » ? section résultat capturé ? drill ? densité/layout du panneau ?) AVANT toute modification.
2. **Vérifier la clé des ROWS** dans les outputs du tool semantic-model-query sur une trace réelle
   (dataset traces) — si différente de rows/records/data/result_rows/values, l'ajouter à
   `capture._ROW_KEYS` + au walker de l'orchestrateur (append-only).
3. Re-tester en DSS ce qui ne l'a jamais été : L040 (bouton New conversation) / L041 (chrono étapes).
4. **Evidence v3 (différé)** : restriction admin des datasets (champ qui SE REND), keyset pagination,
   drill multi-requêtes, fraîcheur des sources (last build) ; fallback LLM seulement sur cas réel.
6. **2ᵉ task mentionnée par l'user le 2026-06-09** — toujours à clarifier.
