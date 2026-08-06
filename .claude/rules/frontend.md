---
paths: ["OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend/**"]
description: Gotchas frontend Vue 3 (F1-F22). Chargees quand on touche au frontend du plugin.
---

# Gotchas frontend (Vue 3 + Vite)

Regles apprises (refs lecons dans `memory/LESSONS.md`). NO INSTALL. Communication FR, code EN.

- **F1 - Validation locale** : compile-check = `./node_modules/.bin/vite build --outDir /tmp/owi_bc --emptyOutDir` puis `rm -rf` (jamais dans `resource/` avant `/build-plugin`). Tests = `node:test` + `unittest`.
- **F2 - `:global` theme (L022)** : selecteur ENTIER dans `:global(body[data-theme="dark"] .x)`. Pas de `color-mix` (L031) : `rgba` + tokens. Texte orange = `--orange-text` (AA, L039) ; fond teinte = `--orange-soft-dark`.
- **F3 - Router HASH** ; **F4 - theme** `body[data-theme]` avant mount ; **F5 - reactivite** version = `reactive()` mutee via `applyEvent`.
- **F6 - i18n** : interpolation LISTE `t('k',[a])` ; ajouts domaine dans `extra.js` (cle-plate par locale, fr+en) ; `messages.json` pristine.
- **F8 - Timeline (L029/L039)** : reducer pur `timelineModel.js` inchange ; affichage groupe/ticker = selecteurs purs read-only, ids stables, `timelineSignature` intacte.
- **F10 - Build : recabler `body.html`** via l'outil `Write` (le `cp` est refuse par les permissions, L033). Le `cp -R` du packaging passe.
- **F11 - Tests front purs** : reducer/clamp/arbre/agentPick/selecteurs timeline/evidencePick sans Vue -> `node:test`.
- **F12 - ARBRE (L032)** : editer/regenerer = echange FRERE ; `v-for` keye `uid` stable ; un changement de version REMOUNT MessageAgent.
- **F13 - Scroll (L032/L038)** : `ChatThread` ne scrolle que sur `activeSessionId`, `exchanges.length`, signature gated `sending`, et `evidence.open`. JAMAIS de watch sur `turns`.
- **F14 - Feedback (L031)** ; **F15 - Agent persistant (L032)** : inchanges.
- **F16 - Ticker live (L039)** : `TransitionGroup` avec `appear` ; UN `.stream` persistant ; reduced-motion via `content:none`.
- **F17 - Navigation (L040)** : URL stampee `/chat/<sid>` au 1er echange ; route->store via `chat.ensureSession` ; un run live survit a un aller-retour Settings ; `canSend` exige `!threadLoading && !threadError`.
- **F18 - Chrono etapes (L041)** : durees scellees = stamps backend ; interval gate `activityLive && chat.sending` ; markdown memoize.
- **F19 - Layout Evidence (L043)** : grille `sidebar | chat 1fr | Evidence droite` ; repli sidebar = `setSidebarCollapsed(true, false)` ; re-clamp `evidenceW` sur resize ; `.ev-chips { z-index:5 }`.
- **F20 - Chips (L043)** : TOUS editables ; preselection picker SEULEMENT pour `=`/`IN` ; `exclude_id` au distinct ; caps miroir backend ; reset/remove ferment le popover.
- **F21 - Trust layer (L045)** : meta v1 => rendu identique ; badge via `trustLevel(meta)` pur ; steps `t('ev.exp.'+kind, params)` kind inconnu -> opaque ; drill = `buildDrillLabels` (abort si >8 cles) ; aucune section nouvelle avec z-index >= 5.
- **F22 - Artefacts (L057, valide DSS)** : onglets Evidence/Chart/Table via `Tabs.vue` dans `EvidencePanel` ; `ArtifactChart.vue` = Chart.js (`chart.js/auto`, dep bundlee), couleurs resolues du theme + re-render au changement de theme ET de locale ; titre/labels d'axes derives des colonnes quand l'agent les omet (`art.chart.auto_title`) ; `ArtifactTable.vue` = resultat capture. Changer d'onglet ne touche PAS `evidence.open` (F13). Payload chart fourni par le backend (`data`).
- **F23 - Cellules numeriques + contexte ecran d'office (2026-08-06)** : formatage des cellules = `composables/cellFormat.js` UNIQUEMENT (inference par colonne, garde identifiants par nom ET par forme - serie d'entiers largeur constante >= 6 = identifiant ; total isole formate) ; AFFICHAGE seul, les flux clic/filtre/popover lisent toujours la valeur BRUTE ; valeur DB exacte au survol (title). Contexte ecran : inclusion PAR DEFAUT (`screenContext.effective` = 'accepted' sans decision), opt-out sticky par signature, plus de banniere ; `screen_context_offered` n'est plus emis.
- **F24 - Dock Source Data + prompt hero (2026-08-06 run 3)** : le panneau Source Data s'ancre TOUT SEUL a l'arrivee via le predicat pur `shouldAutoDock` (`composables/sourceModel.js`, teste node:test) - route chat SANS `:sessionId` (garde contre la course boot /agents vs /conversation), conversation vide, agent avec sources, Evidence fermee, pas d'opt-out. Deux etats en fractions CSS (`with-sources` 2fr/1fr, `src-wide` 1fr/2fr), PAS de drag (reserve a Evidence) ; X = `dismissPanel()` sticky session ; `openPanel(key, {auto:true})` = dock auto SANS event analytics (`source_explorer_opened` mesure une intention user) ; `chat.newConversation()` ne ferme PLUS le dock. Composants sources partages avec l'onglet Evidence : re-teinte via variables hote `--src-chip-bg`/`--src-chip-border` a fallback UNIQUEMENT (L180, jamais d'override :deep concurrent des etats actifs). Prompt = cadre encre 2px carre + barre orange 3px au focus-within (filet scaleX, pas de ring) ; l'agrandissement "arrivee" vit dans ChatView (`.in-empty :deep`).
- **F25 - Tokens en canvas + purge charte (L181/L182, 2026-08-07)** : toute couleur cuite dans un canvas (Chart.js) se resout via `getComputedStyle(document.body)` - JAMAIS `documentElement` : les tokens semantiques vivent sous `body[data-theme]` (F4), `<html>` ne les voit pas (symptome : dark qui dessine les couleurs claires). En remplacant un effet interdit par la charte (ombre, radius, hex), balayer AUSSI les overrides `:global(body[data-theme="dark"] ...)` du meme fichier ; si le token de remplacement a deja sa variante sombre (ex. `--shadow`), supprimer l'override. Micro-labels = 11px / `--fw-heavy` / `letter-spacing 0.08em` (= `--tracking-eyebrow`, decision 2026-08-07 ; la charte ecrit .1em, arbitrage user en attente) ; en-tetes de l'explorateur Source Data = casse REELLE des colonnes (identifiants triables, surface de preuve), MAJUSCULES seulement sur Table/Resultat.

CHARTE ORANGE obligatoire pour tout travail de style : voir `docs/cadrage/CHARTE_ORANGE_UI.md` (regle non negociable #10).
