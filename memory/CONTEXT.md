# CONTEXT - OWIsMind (mémoire courte, chargée à CHAQUE session)

> Maintenue à jour à chaque `/log-session`. Détail complet → `PROJECT_STATE.md` (§13 = frontend) ; leçons → `LESSONS.md`.
> **OWIsMind** = plugin Dataiku DSS : WebApp **Vue 3 + Vite** (front buildé, servi par DSS) + backend **Flask** modulaire
> (`python-lib/owismind/`) qui parle aux agents via **LLM Mesh** et stocke en **SQL direct** (`SQLExecutor2`, PostgreSQL), **sans Flow** au runtime.

## 🎯 Focus courant
**🚀 SESSION 2026-07-06 Run 5 (PASSAGE EN PRODUCTION v1.1 : promotion agents DEV -> PROD_V1 +
zip prod v1.1.0 + nettoyage dev) - ✅ repo PRÊT, RIEN encore déployé DSS (runbook :
`docs/DEPLOY_PROD_V1_1.md`).** Contexte : user très content (« tout fonctionne convenablement »),
nouveau projet DSS « OWIsMind prod v1 » créé par lui pour la webapp + datasets. Livré :
**(1)** agents promus DEV -> PROD_V1 par **régénération scriptée** (`tools/promote_agents_to_prod.py`,
idempotent : copie DEV + ids PROD + retrait bloc `tickets_expert`, BUSINESS_DOMAINS garde tickets =
refus honnête ; PROD rattrapé de 650 lignes de retard, contrat AMBIGUOUS TERM porté dans
`update_aligned_semantic_model.py` PROD) ; **(2)** plugin.json 0.0.1 -> **1.1.0**, build + package
prod : `owismind-upload.zip` 95 entrées, bundle `index-DDxpe_gw.js` ; **(3)** nettoyage : plugins dev
SUPPRIMÉS du disque (`owismind_dev`, `owismind_dev_v2` : zips + staging), `__pycache__`/.DS_Store ;
CONSERVÉS (choix user) : outillage dev, `project-documentation/`, mail relance, **impersonation
GARDÉE pour la bêta** ; **(4)** README semantic_model PROD réécrit (était une copie DEV avec ids DEV) ;
**(5)** vérification adversariale 3 Opus : exécutables 0 finding, 2 findings doc corrigés.
788 back + 352 node + 316 agents + 343 LAB verts, 0 tiret. La whitelist webapp est DYNAMIQUE
(admin, cross-projet) : zéro id côté plugin ; seuls ids par projet = câblage interne entre Code
Agents. Voir `sessions/2026-07-06.md` (Run 5) + **L139-L140**.

**🖥️ SESSION 2026-07-06 Runs 2-4 (SOURCE DATA v3 : popover, mesures choisies, plages intelligentes,
cascade, persistance, CONTEXTE ÉCRAN -> AGENT + transparence, filtre depuis cellule partout, menu de
colonne + tri 3 états + colonnes orange) - ✅ VALIDÉ DSS PAR L'USER (« tout marche super », zip final
`index-DYvX83Tl.js` uploadé + orchestrateur DEV recollé) ; prod + dev stable INTACTS.**
Livré : **(1)** popover filtres = fermeture structurelle (backdrop invisible + `closeOnWindowBlur`
garde activeElement, SourceChips + EvidenceChips miroirs) ; **(2)** zone Calculer = mesures CHOISIES
(`calcFns`, défauts par type num=Somme, dropdown checkboxes bi-hôte) + cartes GRANDES sans ellipsis
(wrap + title) ; **(3)** plages de dates sur colonnes STRING à valeurs ISO (sniffing
`looksLikeIsoDateValues` -> mode plage auto + bascule liste/plage dans les 2 sens, bornes lexicales
`['YYYY-MM','YYYY-MM-99']` sûres sous les 2 familles de collation) ; **(4)** CASCADE : `/source/
distinct` + `/evidence/distinct` GET->POST avec `filters`/`scope_q` (+ evidence `kept_ids` honoré,
`drill`, `exclude_id`), mêmes conditions que rows, chip éditée exclue côté store ; **(4bis)**
persistance des vues par (agent, dataset) (`sourceViewMemory.js`, chips/q/sort/calc survivent
fermeture/réouverture + mode agent d'Evidence) ; **(5)** CONTEXTE ÉCRAN -> AGENT : extension du canal
EXISTANT `screen_context` -> bloc `[ON SCREEN NOW]` (section SOURCE-DATA VIEW budget 1200c, phrase de
permission verbatim TOUJOURS préservée, `sanitize_source_state` never-raises), bandeau de consentement
charte dans PromptBar (sticky par SIGNATURE de scope, chip retirable, jamais de lignes brutes, 3 events
whitelistés 41/41) + paragraphe prompt orchestrateur DEV (repo, À RECOLLER DSS env 3.11). Revue
adversariale 4 lentilles + réfutateurs : 7 confirmés / 3 réfutés, TOUS corrigés. Docs backend-api.md à
jour. Voir `sessions/2026-07-06.md` (Run 2) + **L134-L137**.

**🧮 SESSION 2026-07-06 Run 1 (MANIPULATION DE DONNÉES SANS IA : agrégats DB + zone Calculer + plages de
dates + unification Evidence, livrés dans le plugin coexistant `owismind_dev_v2`) - ✅ vague 1
VALIDÉE DSS par l'user, vagues 2+3 locales (QA runtime + revues), zip dev_v2 FINAL À UPLOADER.**
Brainstorm (4 scouts Sonnet + 3 experts Opus) puis 3 vagues d'implémentation (agents Opus //) :
**(1)** `POST /source/aggregate` (spec structuré, fns whitelistées count/count_distinct/sum/avg/
median/min/max, gate types du schéma live, LIMIT groupes 50 obligatoire, requête totals pour les %
exacts, read-only+timeout+throttle hérités) + barre de totaux + Analyser + lien « Vérifier ce
chiffre » ; **(2)** zone **CALCULER** en haut à droite (cartes KPI par TYPE de colonne, générique,
persistante, le dataset reste visible), filtre **plage de dates** (2 month-pickers + « Année
complète » -> chip `BETWEEN`, bornes `[YYYY-MM-01, dernier-jour T23:59:59.999999]`), médiane ;
**(3)** UNIFICATION Evidence : `evidence/aggregate_core.py` partagé + `POST /evidence/aggregate`
(agrège EXACTEMENT le périmètre pré-filtré par le SQL de la réponse : kept_ids + drill + filtres +
search, prouvé par QA payloads), factory front unique `composables/aggregateSurface.js` (2 hôtes),
`SourceCalc`/`SourceAnalyze` bi-hôtes, `RangePopoverFields` partagé, **surface paresseuse** (aucun
COUNT à l'ouverture du panneau de preuves ; calcul au 1er affichage de l'onglet Source data +
rattrapage). **RÈGLE PRODUIT : tout chiffre montré = calcul DB sur le jeu filtré COMPLET** (jamais
sur la fenêtre affichée). 3 revues adversariales (8+6+6 confirmés, 1 réfuté, TOUS traités) + QA
Playwright réelle (parcours Evidence complet stubbé) + re-checks post-fix (leçon bundle périmé,
L132). **694 back + 268 node verts, Vite OK, 0 tiret. Zip `owismind_dev_v2-upload.zip` (82 entrées,
`index-CRcrpMCq.js`) ; prod + dev stable INTACTS. `tools/build_dev_plugin.py --v2` = 3e plugin
coexistant.** Limitation documentée : colonnes des pickers = table par défaut après un switch
multi-table (convention pré-existante). Voir `sessions/2026-07-06.md` + **L132-L133**.

**📐 SESSION 2026-07-03 Run 3 (PAGE BENCHMARK PLUGIN : optimisation des espaces, retour user) -
✅ local (QA runtime harnais L129), NON recollé DSS.** Retour user : vide en haut à droite, vide
sous les tuiles KPI, Accuracy redondante avec le donut, aside "How this is measured" = une colonne
gâchée. Fix (2 fichiers, `BenchmarkSuggestView.vue` + `extra.js`) : **header custom** slot
`#header` PageShell (recette charte locale) avec **pickers Agent+Benchmark en haut à droite** ;
**hero fusionné** (les tuiles KPI deviennent une colonne de stats compacte à filets 1px DANS la
carte hero, calée sur sa hauteur = zéro vide) ; **tuile Accuracy SUPPRIMÉE** (affichait
`centerText`, la valeur du centre du donut ; clé `bench.kpi.accuracy` purgée fr+en, parité OK) ;
**aside sticky 320px SUPPRIMÉE** -> bande de référence horizontale discrète (`ref-strip` auto-fit,
légende modes horizontale) sous la liste des questions (pleine largeur récupérée). Skeleton aligné,
media queries 1080/760 refaites. **QA Playwright réelle** (mini-serveur mappant le préfixe assets
-> `qa-app/` + `qa-stub.js` injecté ; captures LUES clair/sombre 1680 + 1024 ; 0 erreur console) ;
**207 node verts, Vite OK, accolades 688/688, 0 tiret. Zip DEV `index-CZZt5we5.js` (81 entrées)
REMPLACE `index-B61pkfo9.js`** (contient Runs 2+3), PROD intacte. Gotcha guardrail scratchpad ->
**L131**. Voir `sessions/2026-07-03.md` (Run 3).

**🏗️ SESSION 2026-07-03 Run 2 (REFONTE BENCHMARK : launcher LAB reequilibre + fusion golden +
UI rename + page plugin refondue avec modes conditionnels) - ✅ local (QA runtime reelle), NON
recolle DSS.**
**Launcher LAB** : panes reequilibres (tpl-shell dans body.html 9->67 l., preview.html =
fetch(body.html), applyI18n 3 attributs, script.js 4177->**3917**) ; detail benchmark en 3 zones
+ cluster Manage avec **UI Rename** (route existante + mock miroir) ; "Review the results"
pre-filtre + Back restaure ; badge suggestions ; **panneau Golden legacy SUPPRIME** (devenu
inatteignable apres unification des destinations ; parite champs verifiee, datalist categories
migre sur golden-tag = /api/config garde un consommateur reel, L128) ; 46 cles DICT + 68 regles
CSS mortes purgees. Contrat API + MOCK intacts, backend.py intouche. **Page plugin**
(BenchmarkSuggestView 2618 l. + benchmarkResults.js 290 l. purs) : mono-mode = zero appareil de
modes (badges/KPI/legende/pickers), liste de questions en cartes scannables (rail 3px
danger/warn), detail par onglets Tabs.vue (Full answer / SQL & data / Reference / History
conditionnels), bande hero+KPI auto-fit, aside sticky contextuelle, skeletons ; formatCell
locale-aware ; +21 tests node dont parite i18n. **Quota subagents mort en pleine verif** ->
verification inline orchestrateur : checks statiques scriptes + QA Playwright reelle (launcher
MOCK + harnais stub plugin `getWebAppBackendUrl` injecte, L129) ; 1 bug CSS trouve/corrige
(qhead flex-wrap). **629+316+343+207+5 verts, 0 tiret, zip DEV `index-B61pkfo9.js` (81 entrees),
PROD intacte.** **Run 2b (matin) : hotfix CSS launcher** : la purge avait mange le `}` de
`@keyframes fade` -> tout le CSS apres l.202 avale par le navigateur (casse vue par l'user en
DSS) ; fix commite `a571474`, re-verif visuelle complete (L130 : equilibre d'accolades apres
toute chirurgie CSS + LIRE chaque screenshot pris). Email relance (beta 8 juillet) commite par
l'user (`a95efbd`/`7c5c3be`). Voir **L128-L130** + `sessions/2026-07-03.md` (Runs 2 + 2b).

**🧹 SESSION 2026-07-03 (GRAND NETTOYAGE pré-bêta : mémoire condensée + docs alignées + code mort +
fix `/api/config` LAB) - ✅ local (4 suites vertes), route LAB à recoller DSS.**
Audit Workflow 7 scouts Sonnet + vérif adversariale Opus par candidat : **code déjà sain** (0 mort
backend/frontend/agents, hygiène git parfaite), le gras = MÉMOIRE + DOCS. **Mémoire** : CONTEXT.md
**1546 -> 431 lignes (-72 %)** (gotchas byte-identiques, chaîne >= 2026-06-24 + bloc archive) ;
PROJECT_STATE.md §2b/§4/§11/§12 réparés (**§11 = matrice par sous-système**, §4 = snapshot arbo
2026-07-03, plus aucun chat_v4 « courant ») ; LESSONS.md **+5 marqueurs obsolète/reverté**
(L062/L067 partiel/L068/L073/L086). **Code mort supprimé (vérifié 0 réf)** : 14 clés `extra.js`
fr+en (`fb.reason.other` GARDÉE : usage dynamique) + entrée SRC_KEYS test ; `slug_agent_key()` LAB
+ test + import. **Bug L115 n°3 (validé user)** : `GET /api/config` absent du backend launcher (le
MOCK l'avait -> 404 silencieux DSS, compteurs golden périmés) -> route `@_safe` read-only +
`views.config_meta_view` pure (+2 tests = 343), contrat = miroir MOCK ; `/api/benchmark/rename`
GARDÉE (décision user, chaîne complète sans UI). **Docs** : chat_v4->v5 partout (6 docs vivants,
specs gelées intactes), `CONV_TITLE_MAXLEN` 56, backend-api.md **34/34 routes** (+13 dont /track,
/source/*, /usage, /admin/budget*, /benchmark/*), data-model.md **8/8 tables** (+5 : §2.4-2.8, +
colonnes usage/mode chat_v5), READMEs dataiku-agents réparés, notes « chemins historiques » au
skill agentique. **629 back + 316 agents + 343 LAB + 186 node verts, Vite OK, 0 tiret ajouté,
-767 lignes nettes (22 fichiers).** Voir **L127** + `sessions/2026-07-03.md`.

**🎚️ SESSION 2026-07-02 Run 6 (MODE ÉPHÉMÈRE : Smart par défaut + reset à l'envoi + mode
persisté/affiché par réponse) - ✅ VALIDÉ DSS (user : « super ça marche très bien »).**
**(1) Éphémère** : `ui.js` boot 'smart' inconditionnel, **persistance localStorage du mode
SUPPRIMÉE** (clé legacy purgée), `resetModelMode()` ; `chat.js` capture `rawMode`/`runMode`
AVANT le reset, **stamp `newVersion({mode})`**, reset SYNCHRONE avant l'await (picker revient
à Smart à l'instant de l'envoi ; edit/regenerate pareil) ; analytics `question_sent`/
`answer_received` lisent le STAMP (jamais le store resété). **(2) Persistance** : colonne
**`mode VARCHAR(16)` nullable sur `webapp_chat_v5` SANS bump _v6** (ALTER `ADD COLUMN IF NOT
EXISTS` idempotent, 2e usage du précédent users_v1 = **L126**) ; helper pur
`agents/context.resolve_effective_mode` ; `/chat/start` stampe le mode effectif AVANT le write
phase-1 ('smart'|'pro'|'claude', NULL si agent sans modes) ; `_COLUMNS` + `/conversation`
l'exposent NULL-safe ; `MessageAgent` affiche le mode dans la ligne tokens/coût (libellés
existants, tooltip `msg.usage_mode` fr+en) ; vieilles réponses NULL = rendu identique.
`timelineModel.js` : seulement `mode:null` au shape + `modeFromRow` pur (reducer/signature
INTOUCHÉS, vérifié par la revue). **Revue adversariale 3 lentilles + réfutateurs = 0 confirmé.**
**629 back (+15) + 186 node (+2), build OK, 0 tiret, zip DEV `index-CbbPsbRU.js` déployé,
PROD intacte.** Voir **L126** + `sessions/2026-07-02.md` (Run 6).

**📊 SESSION 2026-07-02 Run 5 (ANALYTICS D'USAGE : `webapp_events_v1` + `POST /track` + `track.js`)
- ✅ VALIDÉ DSS (user : « ça marche super bien » puis « parfait tout fonctionne all good »).**
Tracking GA4-like de l'usage webapp (fréquentation, features, parcours), distinct des logs
agentiques. **Décision (cadrage 3 scouts Sonnet)** : 1 table SQL brute unique (PAS le folder/S3
1-fichier-par-event de l'ancienne webapp Dash, faiblesse prouvée). **Backend** : DDL 13 colonnes
(`view_name` car VIEW réservé PG ; index `(app_session_id,seq)` pour les parcours) ;
`storage/events.py` = whitelist **38 events** source de vérité + `validate_events` pur (caps
batch 40 / props 2000c, dédup, client_ts py3.9) + `record_events` (1 INSERT multi-lignes ON
CONFLICT DO NOTHING, best-effort) ; route `POST /track` (sendBeacon text/plain via get_json
force+silent, **impersonation = drop avant write**, throttle 12/0.5 par s, jamais de 500).
**Frontend** : `trackModel.js` pur (queue 200, drain 40, limiteur 10 erreurs/session) +
`track.js` (app_session_id, seq, flush 5s/20, sendBeacon pagehide, no-op impersonation) + hooks
minces (router afterEach, 7 stores, feedback, cell popover, erreurs window/Vue/réseau).
**Taxonomie renommée sur retour user (38 noms auto-descriptifs)** : `question_sent`,
`answer_received {duration_ms}`, `webapp_opened`, `page_viewed`, et **onglets Evidence = events
de 1er rang** (`chart_viewed`/`table_viewed`/`kpi_viewed`/`source_data_viewed`/
`evidence_proof_viewed`) ; top features = GROUP BY event_name. **Privacy** : recherches = `{len}`
seul ; paths d'erreur SANS query string (fix HIGH de la revue adversariale 12 Opus, 1 confirmé/
7 réfutés = **L125**). Sessions = gap 30 min (pas de session_end). **614 back (+32) + 184 node
(+21), parité whitelist 38/38 par script, 0 tiret, zip DEV `index-D-NkcYpc.js`, PROD intacte
(build prod stoppé par réflexe dev-first).** Reste : dashboard d'adoption Dataiku (dataset SQL
+ rollups). Voir **L125** + `sessions/2026-07-02.md` (Run 5).

**⛔ RÈGLE NON NÉGOCIABLE #9 (2026-06-17) : tiret cadratin `—` (U+2014) et demi-cadratin `–` (U+2013)
BANNIS À TOUT JAMAIS, PARTOUT** (i18n/UI, code, commentaires, mémoire, commits, réponses chat). Signature
d'IA, interdiction user absolue. Utiliser `-`, `:`, `,`, parenthèses. Sweep byte-safe (`LC_ALL=C`, jamais
`perl -CSD` sur fichiers à glyphes multioctets type `⟦⟧`). Vérif = **scan Python** (`t.count('—')`/`('–')`) ;
⚠️ le `grep -rlP '\xe2\x80\x9[34]'` du protocole **échoue silencieusement sur le BSD grep** de ce Mac (faux
négatifs ; installer `ggrep` GNU sinon). Voir L084 + **L093**.

**🟠 RÈGLE NON NÉGOCIABLE #10 (2026-06-18/19) : CHARTE ORANGE = style UI obligatoire à CHAQUE travail de
style.** Source auto-suffisante : **`docs/cadrage/CHARTE_ORANGE_UI.md`** (à LIRE avant de styliser ; la maquette
HTML d'origine a été supprimée). Blanc/noir + **un orange #FF7900 en accent RARE** ; **carré** (`border-radius:0`,
avatars ronds) ; aplats/filets 1px ; **H1 36/800 + eyebrow orange + title-bar 52x4** ; **tokens sémantiques**
(`frontend/src/styles/tokens.css`, texte orange = `--orange-text`) ; bans : `color-mix`/blur/dégradé/glow/emoji/
focus-ring global **+ visuel de marque reconstruit en CSS (toujours la VRAIE image `orange-logo.png`)**. Voir **L092**.

## 🧭 Dernière session - 2026-07-06 Run 5 : passage en production v1.1 → détail `sessions/2026-07-06.md` (Run 5) + **L139-L140**
- **✅ Repo prêt, RIEN déployé DSS** : agents PROD_V1 promus (régénération scriptée, 3 revues Opus,
  2 findings doc corrigés), zip prod v1.1.0 (`index-DDxpe_gw.js`, 95 entrées), plugins dev supprimés.
- Déploiement = suivre **`docs/DEPLOY_PROD_V1_1.md`** (plugin §1, projet prod §2, agents A/B §3,
  smoke §5). Tickets expert volontairement HORS PROD ; impersonation gardée pour la bêta.
- **Test DSS reporté par l'user (pas le temps en fin de session) : la PROCHAINE session commence
  par le déploiement + smoke du runbook.**

## 🧭 Avant - 2026-07-06 Runs 2-4 : Source Data v3 complet → détail `sessions/2026-07-06.md` (Runs 2-4) + **L134-L138**
- **✅ VALIDÉ DSS par l'user (« tout marche super »)** : zip `index-DYvX83Tl.js` uploadé,
  orchestrateur DEV recollé. Tout le chantier des 5 retours + les 3 retours du matin + le menu de
  colonne est LIVE sur dev_v2.
- Reste à la demande : promotion DEV principal puis PROD (rebuild + orchestrateur PROD `Xrv7GvfG`) ;
  différés (refetch meta multi-table, export CSV d'agrégat, comparaison de périodes, profil de
  colonne, contexte évidence legacy enrichi).

## 🧭 Avant - 2026-07-06 Run 2 : Source Data v3 (popover, mesures, plages string, cascade, persistance, contexte écran -> agent) → détail `sessions/2026-07-06.md` (Run 2) + **L134-L137**
- **✅ Validé local (revue adversariale soldée + QA runtime 8/8 et re-checks 4/4), NON validé DSS.**
  Livré dans le zip dev_v2 (désormais `index-gYAOS4OQ.js`, Run 3 inclus) ; paragraphe
  orchestrateur DEV à recoller (env 3.11, sans lui la feature dégrade proprement).
- Gros smoke : popover se ferme au clic extérieur, Calculer 1 carte Somme + dropdown Mesures,
  `year_month` en mode plage auto, cascade Actuals->clients, réouverture = vue restaurée, bandeau
  Inclure -> l'agent exploite les chiffres écran, dark.

## 🧭 Avant - 2026-07-06 Run 1 : data tools sans IA (agrégats + Calculer + plages + unification Evidence) + plugin dev_v2 → détail `sessions/2026-07-06.md` + **L132-L133**
- **✅ Vague 1 validée DSS (user, sur dev_v2) ; vagues 2+3 validées en local** (QA runtime parcours
  Evidence stubbé, 3 revues adversariales soldées) ; **zip FINAL `owismind_dev_v2-upload.zip` à uploader**.
- Smoke DSS : CALCULER sur `amount_eur` (Médiane incluse), plage `year_month` + Année complète,
  Analyser (buckets chronologiques), Evidence -> Source data (chip agent verrouillé + zone + compte),
  ouverture du panneau de preuves SEUL = zéro appel aggregate (lazy), dark.

## 🧭 Avant - 2026-07-03 Run 3 : optimisation des espaces page benchmark plugin → détail `sessions/2026-07-03.md` (Run 3) + **L131**
- **✅ Local (QA runtime réelle), NON recollé DSS.** Pickers dans l'en-tête (vide haut-droit comblé),
  hero + stats fusionnés (Accuracy supprimée, redondante donut), aside -> bande de référence en pied.
- **Zip DEV `index-CZZt5we5.js` remplace `index-B61pkfo9.js`** (Runs 2+3) ; smoke DSS = layout
  (header/hero/bande, dark, ~1280px) + les smokes Run 2 ; revue adversariale des diffs à relancer.

## 🧭 Avant - 2026-07-03 Runs 2 + 2b : refonte benchmark + hotfix CSS → détail `sessions/2026-07-03.md` + **L128-L130**
- **✅ Local (QA runtime). Recoll DSS en cours par l'user** : HTML + JS launcher déjà collés
  (constaté sur son screenshot) ; **le pane CSS à coller = style.css POST-hotfix `a571474`**
  (la version du commit `98c06fc` est syntaxiquement cassée, L130). Route /api/config (Run 1)
  encore à coller ; plugin : zip DEV (désormais `index-CZZt5we5.js`, Run 3) + restart backend.
- Smoke DSS : rename, Review pré-filtré, badge suggestions, datalist catégories ; page plugin
  mono vs multi-mode, onglets détail, dark. Revue adversariale multi-agents à relancer (quota).

## 🧭 Avant - 2026-07-03 Run 1 : grand nettoyage pré-bêta (mémoire -72 %, docs 34/34 routes + 8/8 tables, code mort, /api/config LAB) → détail `sessions/2026-07-03.md` + **L127**
- **Repo only, 4 suites vertes (629+316+343+186), rien à redéployer côté plugin.** Reste DSS :
  recoller `benchmark_webapp/views.py` + pane Python `benchmark_launcher/backend.py` (route
  `/api/config`, batchable avec les recolls L115/L117 en attente).
- Mémoire : CONTEXT.md 431 lignes, PROJECT_STATE §11 = matrice par sous-système, 5 leçons marquées
  obsolètes/revertées ; docs/ redevenues exhaustives (routes + tables + contrat /evidence/rows).

## 🧭 Avant - 2026-07-02 Run 6 : mode éphémère + mode par réponse (chat_v5.mode) → détail `sessions/2026-07-02.md` (Run 6) + **L126**
- **✅ VALIDÉ DSS.** Smart par défaut permanent, Pro/Claude éphémères (reset synchrone à l'envoi,
  persistance localStorage supprimée) ; `mode` stampé serveur sur chaque échange (ADD COLUMN
  IF NOT EXISTS sur chat_v5, L126) et affiché dans la ligne tokens/coût. Revue 3 lentilles :
  0 confirmé. Zip DEV `index-CbbPsbRU.js`.

## 🧭 Avant - 2026-07-02 Run 5 : analytics d'usage webapp (events + /track + dashboard à venir) → détail `sessions/2026-07-02.md` (Run 5) + **L125**
- **✅ VALIDÉ DSS.** Table unique `webapp_events_v1` (38 events auto-descriptifs, onglets Evidence
  en events de 1er rang), route `/track` batch best-effort (impersonation drop, throttle, jamais 500),
  `track.js` (flush 5s/20 + sendBeacon), hooks minces dans 13 fichiers. Revue adversariale 12 Opus :
  1 HIGH corrigé (query string PII dans error_backend, L125). Zip DEV `index-D-NkcYpc.js`.
- Reste : dashboard d'adoption Dataiku (dataset SQL sur la table + rollups DAU/features/parcours).

## 🧭 Avant - 2026-07-02 Run 4 : Source Data filtres cherchables + cell-to-agent + popover/DataLoader → détail `sessions/2026-07-02.md` (Run 4) + **L123-L124**
- **✅ VALIDÉ DSS (« parfait all good » ; arc 1 commité user `a2754ca`).** Filtres 2 étapes cherchables
  (+ `q` serveur sur les 2 routes distinct), « Use this value for agent » (chips + bloc texte appendé
  au message à l'envoi, frontend-only), popover cellule Teleport body (fix ancêtres transform),
  DataLoader charté (bar-chart carré, 1 barre orange). Zip DEV `index-CY8CEJu8.js`.
- Revue adversariale 15 agents : 8 LOW confirmés corrigés. Reste : promotion PROD à la demande.

## 🧭 Avant - 2026-07-02 Run 3 : Source Data Explorer (v1+v2) → détail `sessions/2026-07-02.md` (Run 3) + **L121-L122**
- **✅ VALIDÉ DSS** (« tout fonctionne super bien »). Exploration des datasets bruts des agents :
  bloc admin `sources` par agent, CTA + panneau sur New Conversation, onglet Source data
  d'Evidence (sélecteur fusionné, agent de l'échange), recherche Entrée-only accent-insensible,
  limit/offset 100+20, colonnes 30+20, pleine hauteur. Zip DEV `index-Sd9XWyIM.js` déployé.
- Reste à la demande : promotion PROD ; leviers de charge (timeout court, sémaphore, throttle dédié).

## 🧭 Avant - 2026-07-02 Run 2 : artefacts natifs + narration + recall → détail `sessions/2026-07-02.md` (Run 2) + **L119-L120**
- **✅ VALIDÉ DSS, code commité par l'user (`0368dd7`, `0275ae9`).** Multi-charts + métadonnées +
  binding par artefact ; narration pro/claude + `tell_user` smart ; `recall_prior_result` (3 tours).
- 2 revues adversariales + vérif Opus finale ; consigne gravée : sous-agents/workflows en OPUS.

## 🧭 Avant - 2026-07-02 Run 1 : audit + durcissement orchestrateur & expert revenus & cerveau sémantique → détail `sessions/2026-07-02.md` + **L118**
- **Repo only (DEV), NON validé DSS.** 20 findings confirmés implémentés (5 orchestrateur, 9 expert
  revenus, 3 cerveau sémantique, 1 lookup, +2 filets de ma revue), 1 reverté après revue finale
  (param `source` multi-spécialistes : le plugin rend tous les artefacts depuis UN result_block ->
  chantier plugin à valider). 296 tests verts, PROD + moteur tickets intacts (à porter après DSS).
- **À FAIRE DSS** : recoller orchestrateur + revenue expert (env 3.11) + tool lookup, exécuter
  `update_aligned_semantic_model.py` + re-dump. Agent + modèle ENSEMBLE (contrat AMBIGUOUS TERM).

## 🧭 Avant - 2026-07-01 Run 3 : visibilité complète des résultats benchmark (réponse + SQL généré + tableau) + override + extension plugin → détail `sessions/2026-07-01.md` (Run 3) + **L117**
- **LAB commité `511e4bd`, plugin non commité (ce log), NON validé DSS.** Retour user : manque de visibilité.
- **Constat = la donnée était déjà stockée** (`generated_sql_json` = SQL réel + tableau, `answer_text` complet) ;
  trou à la **LECTURE** (colonnes lourdes droppées, preview 280c). **Aucun re-run.** Override juge **déjà là**
  (launcher) -> on a ajouté de quoi décider. Chargement **à la demande, 1 ligne** (LAB `iter_rows` streaming ;
  plugin `SELECT ... LIMIT 1` paramétré, colonnes intersectées au schéma live). Vue pure `full_detail_view`.
- **LAB** (`views.py`/`dss.py` + routes `/api/*/attempt` + rendu `benchmark_{results,launcher}/script.js`) ;
  **plugin** (`aggregate.py`/`lab_io.py` + route `GET /benchmark/attempt` + store `attemptDetail`/`loadAttempt`
  + `BenchmarkSuggestView.vue` + i18n `bench.ev.*`). Réponse complète + SQL généré + tableau, dépli lazy.
- **Filet** : LAB 342 + node 5/5 + **harnais headless 16 checks (XSS inclus)** ; plugin 513 + 134 node + Vite OK
  + **zip DEV** (78 entrées, `index-d58-B9PB.js`, PROD intacte) ; 0 tiret. **À FAIRE DSS** : LAB = recoller lib +
  panes 2 webapps ; plugin = upload zip DEV + **redémarrer backend**. Pas de re-run. Voir **L117**.

## 🧭 Avant - 2026-07-01 Run 2 (session //) : clarté benchmark detail + galerie d'agents + flux "ajouter un agent" + grand nettoyage ultracode → détail `sessions/2026-07-01.md` (Run 2) + **L116**
- **Repo only, NON validé DSS.** Menée en parallèle de la Run 1 (tree fusionné re-vérifié vert avant log).
- **Benchmark detail clarifié** (1 seule carte de statut + 1 bouton « Lancer en attente (N) », légende) ;
  **accueil = galerie de cartes d'agents** (rail latéral seulement à l'ouverture) ; **flux "ajouter un
  agent" sans code** (catalogue dans `benchmark.agents` ; `dss.list_projects`/`list_project_agents`/
  `connect_agents` read-only ; front projet -> agents id+nom -> cocher). **Grand nettoyage ultracode** :
  workflow 7 scouts + vérif adversariale (12 faux positifs écartés) -> junk + code mort symbol-level +
  fonctions v1 LAB + **vieux sous-système launcher (-945 l. script.js)** ; **gardé** (choix user) i18n
  `messages.json` plugin + `golden_view`. **LAB 335 + plugin 509+134, Vite OK, smoke navigateur 0 erreur.**
- **À FAIRE DSS** : recoller lib+webapps launcher + composables plugin (rebuild), redémarrer backend ;
  purger `benchmark.agents` (~40 agents auto-découverts) puis ré-ajouter via le flux. Voir **L116**.

## 🧭 Avant - 2026-07-01 Run 1 : LAB launcher, nettoyage + 4 fixes + 1 feature → détail `sessions/2026-07-01.md` (Run 1) + **L115**
- **Repo only (code commite par session concurrente), partiellement validé DSS.** Tout dans `OWIsMind_LAB/`.
- **✅ Validé DSS** : (a) questions golden s'affichent (fix contrat `/api/golden` : renvoie `questions`+`agents`
  scope `agent`, pas `rows`/`this`) ; (b) `agent_key = agent_id` partout (jamais le slug `orchestrator` ;
  derive dans `registry`+`run_params`, purge des hardcodes). User : "ça marche beaucoup mieux".
- **⏳ Non validé DSS (à recoller Launcher)** : (c) formulaire golden gagne `expected_value`/`expected_value_type`/
  `notes` (couvre les 12 col ; bonus : payload inline n'écrasait plus `notes`) ; (d) fix redo "nothing to run"
  (`/api/benchmark/redo` lisait `include_next`, front envoie `value`). **Défaut ouvert** : `reconcile_redo_after_run`
  nettoie le redo du dernier run existant sans vérifier qu'il l'a consommé (mord sur run échoué) - fix proposé.
- **Cause commune (fixes b/d) = dérive de contrat MOCK vs vrai backend** : le front launcher est QA contre son
  MOCK -> aligner le vrai backend sur le MOCK. **335 tests LAB + node 5/5, 0 tiret.** À FAIRE DSS : recoller
  Launcher onglet JS (`script.js`) + Python (`backend.py`), recharger la webapp.

## Avant - 2026-06-30 Run 2 : Mail de relance HTML (retour beta) → détail `sessions/2026-06-30.md` (Run 2) + **L114**
- **Asset only (hors code/DSS).** Cree `owismind-relaunch-email.html` (racine) : mail HTML autonome
  charte Orange, court et scannable, annonce le retour d'OWIsMind en **beta** + ameliorations (benchmark,
  garde-fous SQL, transparence, tableaux/graphiques, 3 modes) + **insistance forte sur la clarte du
  prompt** + CTA + appel feedback.
- 2 retours user appliques : coupe ~60% (grille 2x2 scannable) ; **hero orange aplat retire** au profit
  d'un hero blanc editorial (orange = accent rare) + ajout d'un petit paragraphe d'intro.
- Logo Orange reel en base64 + wordmark texte. **0 tiret, 1 placeholder lien** a remplir. **Caveat** :
  base64 souvent bloque Gmail/Outlook -> heberger le PNG si besoin. NON rendu live (Chrome occupe). Voir **L114**.

## Avant - 2026-06-30 Run 1 : Benchmark v2 (append mode + colonnes SQL/tool de référence) → détail `sessions/2026-06-30.md` + **L113**
- **Repo only, DEV repackagé, NON validé DSS.** (1) Golden +`expected_sql`/`expected_tool` (signal doux
  au juge + affichés vs `actual_tools`). (2) **Append mode** : benchmark nommé unique par agent, runs qui
  s'accumulent (score = dernière tentative), 3 boutons + drapeau « refaire » + évolution.
- **Archi : registre + appartenance + redo dans la VARIABLE `benchmark`** (0 dataset neuf) ; tables +
  `benchmark_id`/`benchmark_name`/`attempt_no` ; summary/breakdown **par benchmark** ; lecture plugin par
  intersection de colonnes (rétro-compat). NOUVEAU `benchmark/registry.py`.
- **Tests LAB 329 + plugin 509 + node 134 verts, 0 tiret, build Vite OK, zip DEV `index-DZ7yGIZO.js`
  (78 entrées), PROD intacte.** Revue adversariale = 0 crit/high, 1 medium corrigé (redo consommé avant
  le verrou). **À FAIRE DSS** : recoller lib+webapps LAB + variable (`benchmarks:{}`,`run_request:null`) ;
  upload DEV + redémarrer backend ; un run frais matérialise les colonnes. Voir **L113**.

## Avant - 2026-06-29 Run 2 : consultation benchmark en PLEINE LARGEUR (parité LAB results) → détail `sessions/2026-06-29.md` Run 2 + **L112**
- **Cause** : `PageShell` (wrapper partagé) plafonne à **880px centré** -> rendu "confiné" vs LAB pleine largeur.
- **Fix propre, scoped** : prop **opt-in `fluid`** sur `PageShell` (`.page-wrap--fluid` enlève le cap, padding LAB).
  Seule `BenchmarkSuggestView` le passe -> **aucune autre vue touchée** (garantie demandée par l'user). +
  aside 360px, KPIs 3-col dès 1280px (parité LAB), section "Suggérer" plafonnée 880px.
- **Zip DEV `index-CzZWTpbS.js` (78 entrées), PROD INTACTE, 0 tiret, build OK.** Frontend only -> **upload DEV
  suffit, PAS de redémarrage backend.** Q/R override admin (UPDATE cross-projet du scored LAB, table de la fiche
  d'agent) + taille benchmark (~100-150 questions stratifiées) répondues sans code. Voir **L112**.

## Avant - 2026-06-29 Run 1 : benchmark phase finale (juge contextuel + override humain + consultation native dans le plugin) → détail `sessions/2026-06-29.md` + **L111**
- **Juge contextuel** (`judge.py`, TDD) : magnitudes (« 36 millions » -> 36e6), **ancre = signal** (MISS ne
  force plus faux, le juge tranche), **note humaine = contrat de sévérité**, colonne `judge_comment`.
- **Override humain** : colonnes `human_*` dans `scored` (survivent aux runs, scored empile par run_id),
  `effective_correct` (override prime), KPIs recalculés dessus ; write-back verrouillé (`dss.write_override`) ;
  onglet Review/override sur le **launcher LAB**.
- **Plugin = CONSULTATION uniquement** (décision user, **aucun launcher** ; le launch reste sur les webapps
  LAB) : package pur `benchmark_view/` + routes (`/benchmark/results` tous, admin tables/validate/override) +
  fiche d'agent (bloc `benchmark` + **sélecteur de table + validation de schéma**) + onglet Benchmark Vue.
  Consultation **restylée en reproduction NATIVE (pas d'iframe) de la webapp LAB `results`**.
- **276 LAB + 508 plugin + 133 node verts, 0 tiret, build OK, zip DEV `index-BK29Kqtv.js` (78 entrées),
  PROD INTACTE. NON validé DSS.** À FAIRE : recoller lib+launcher LAB (+ relancer un run) ; upload DEV +
  redémarrer backend ; câbler le bloc benchmark sur une fiche d'agent ; smoke-tests.

## Avant - 2026-06-26 (RUN FINAL) : fix nom de table trop long (L110) + réorg archi benchmark sous `OWIsMind_LAB/` (L109) → détail `sessions/2026-06-26.md` (Run final)
- **Fix table-name (✅ VALIDÉ DSS)** : nom physique 65 octets > 63 (logique longue + préfixe DEV) -> `pg_identifier`
  levait -> 500. `sql_config._shorten_identifier` (via `physical_table`) : ≤63 inchangé (0 donnée orpheline), >63 =
  tête lisible + hash 10c. DEV re-packagé (`index-pktQ-ICh.js`) -> table créée + INSERT committé en DSS. Étend L103.
- **Réorg (✅ local)** : `git mv` (46 renommages) -> tout le benchmark sous **`OWIsMind_LAB/`** (miroir du projet DSS) :
  `project-library/python/{benchmark, benchmark_webapp}` + `webapps/{benchmark_launcher, benchmark_results}` +
  `local-variables.example.json` + **`README.md` maître**. **Packages inchangés = 0 recoll DSS.** CLAUDE.md +
  PROJECT_STATE.md + guides + commande de test (`-t` lib root) à jour. **726 tests Python verts, 0 tiret.** Voir **L109**.
- **À FAIRE DSS (LAB)** : créer les 2 webapps Standard + recoller la lib + bloc `suggestions` avec le nom de table
  **raccourci** (`benchmark.suggestions.table`) -> l'onglet Suggestions du Launcher verra la suggestion `pending`.

## Avant - 2026-06-26 (NETTOYAGE) : grand ménage du repo + doc sortie du contexte auto → détail `sessions/2026-06-26.md` (Run nettoyage) + **L108**
- **Recon multi-agents (Workflow ultracode, 7 scouts + vérif adversariale)** = **0 code mort** ; le gras = junk
  OS, scratch de workflows, maquettes consommées, doc EN périmée. **Code fonctionnel 100% conservé.**
- **Supprimé** : 16 `.DS_Store` + 31 `__pycache__` (junk) ; **56 fichiers suivis** docs/scratch/maquettes
  (les 2 `.workdir`, `style-reference/`, `benchmark_webapp/mockup/`, plan orphelin, `docs/screenshots/`,
  `docs/scaling/PLAN_*`). **Doc JAMAIS supprimée** (règle user) : `project-documentation/` + `docs/` gardés,
  juste `project-documentation/` exclue du graphe (`.graphifyignore`) + note `CLAUDE.md` -> hors contexte auto,
  lisible à la demande. **1132 tests verts**, 0 code touché, suppressions non-committées (revisables). Voir **L108**.

## Avant - 2026-06-26 (Run UI) : re-skin des 2 webapps LAB sur le mockup Orange (Launcher + Results, rail retiré) → détail `sessions/2026-06-26.md` + **L107**
- **Frontend SEUL** (repo only, NON déployé) : `launcher/{style.css,script.js}` + `results/{style.css,script.js,
  body.html,preview.html}` refaits « de cette manière » d'après `benchmark_webapp/mockup/OWIsMind_benchmark/`,
  **rail retiré**. Branchés au VRAI backend (routes `api/*` + formes `views.py` inchangées), MOCK conservé,
  justesse golden 9-col + nombres localisés FR préservés. **0 Python touché** (49 tests webapp verts, pas de
  build/zip). Gotcha `var()` en attribut SVG -> couleurs via `style="stroke:var()"`.
- **QA Playwright** des 2 preview (EN/FR x clair/sombre + interactions : save/toast, création golden, run
  simulé, table Results + détails + filtre + sélecteur de run) = **0 erreur console, 0 tiret (7 fichiers)**.
  **À FAIRE DSS** : au déploiement des 2 webapps Standard, coller les panes mis à jour (guide inchangé). Rail différé.

## Avant - 2026-06-26 (+ révision b) : intégration benchmark - capture utilisateur (plugin) + 2 webapps admin LAB
- **2 pôles** : capture utilisateur **dans le plugin Vue** (table `webapp_golden_suggestions_v1` + 3 routes
  `/benchmark/*` + action menu « ... » -> page `/benchmark` préremplie, tous users) ; admin/restitution =
  **DEUX webapps DSS standard SÉPARÉES dans `OWIsMind_LAB`** (révision b) : `benchmark_webapp/results/`
  (publique, lecture seule, **langage clair grand public**) + `benchmark_webapp/launcher/` (config **formulaire**
  + lancement + suggestions). **Bilingues EN/FR.** Lib partagée `views.py` (pur) + `dss.py` (chokepoint SQL
  read+append-only).
- **Vérifs** : **688 tests Python** (484 plugin + 174 benchmark + 30 webapp) + 124 node ; build Vite + **DEV
  re-packagé** (`index-BoETXxLb.js`, 72 entrées, **prod intacte**) ; **QA visuelle Playwright** des 2 webapps
  (EN/FR x clair/sombre) ; revues adversariales (4-dim + système + **sécurité/danger dédié avec vérif
  adversariale**) = **0 crit/0 high** (corrigés + tests) ; **0 tiret (31 fichiers)**. **L103 + L104**.
- **À FAIRE DSS** : (plugin) upload DEV + redémarrer backend ; (LAB) créer **2 webapps standard**
  (`benchmark_webapp/README.md` : project-library `views.py`+`dss.py` + 4 panes/webapp + permissions + bloc
  `suggestions` + **« Prevent concurrent executions »** sur le scénario). **golden_dataset = managé autonome.**

## Avant - 2026-06-25 (système de benchmark / évaluation des agents) → détail `sessions/2026-06-25.md`
- **Nouveau package `benchmark/`** (repo = source de vérité, recollé en project-library `OWIsMind_LAB`) : vrai système d'ingénieur de test des agents, **par agent ET par mode** (précision/latence/coût). Appel **direct** de l'orchestrateur via Mesh + reconstruction de la réponse **COMPLÈTE** (texte + SQL + lignes + artefacts) depuis le footer (`agent_capture.py`). Juge = **ancre objective déterministe + LLM structuré** (`needs_review` sur désaccord). **Config UNIQUE** = variable projet `benchmark` (zéro hardcode). **Modes Smart/Pro/Claude** (token interne eco/medium/high traduit), **flag `modes` par agent** (sinon 1 appel simple `default`). Datasets managés `golden_questions_v1_prepared` -> raw -> scored -> summary + breakdown. **173 tests, 0 tiret**, poussé origin/main (`6eb1cb4`..`b4b3816`).
- ✅ **DSS : step matrix tourne** (capture complète OK). ⏳ Judge corrigé (NaN, **L102**), run complet, dashboard = **NON re-validés DSS**.
- **À FAIRE DSS (prochaine session)** : re-coller `judge.py`+`schemas.py` + les 3 corps de step ; relancer **Judge + Aggregate** sur le raw existant ; vérifier scored/summary/breakdown ; run complet (3 modes) + dashboard. Livrables : `SETUP_GUIDE.md` (4 étapes), `GOLDEN_IMPORT_PROMPT.md`.

## Avant - 2026-06-24 (fix UI : pouces feedback + modes par agent Smart/Pro/Claude) → détail `sessions/2026-06-24.md`
- **Repo only ; DEV packagé.** Pouces 👍/👎 illisibles -> glyphes **pleins** (`icons.js`) + `MessageAgent` `:size=15`. Modes **par agent** : flag `modes` (profil), `/agents` l'expose, **`/chat/start` ne relaie le token que si l'agent le supporte** (plus de fuite), toggle admin (`AdminView`), picker masqué sinon (`session.selectedAgentSupportsModes` + `PromptBar v-if`). Renommage **Smart/Pro/Claude** (clés internes eco/medium/high gardées) + code couleur (vert RECOMMANDÉ Smart, rouge avertissement Claude « bien plus cher, épuise le quota 50 $ »).
- **456 back + 124 front + build OK, 0 tiret**, rendu vérifié navigateur (clair/sombre).
- **⚠️ Incident** : PROD packagée par erreur -> annulée, prod restaurée à `index-CApWkAm7.js`. Seul le **DEV** est packagé (`owismind_dev-upload.zip`, `index-BKICdg4x.js`). **Règle : en dev, packager UNIQUEMENT le DEV** (mémoire `dev-first-never-touch-prod-artifacts`). À FAIRE DSS : upload DEV (Uploaded) + redémarrer backend + cocher « gère les modes » sur OWIsMind.

## Avant - historique antérieur au 2026-06-24 (archivé)
- **Détail complet par date** : `memory/sessions/*.md` (un fichier par jour, 2026-06-11 -> 2026-06-22) ;
  **leçons** : `memory/LESSONS.md` (L001-L126) ; **état durable** : `PROJECT_STATE.md` (§8 backend, §11 agents).
- **Jalons de cette période** : Evidence trust layer (v1+v2, ✅ DSS) ; agents LangGraph orchestrateur +
  sous-agent revenus (✅ DSS) ; modèle sémantique aligné + sous-agent assistif (L058) ; refonte UI charte
  Orange + fiches d'agent admin ; budget 50 $/user/mois + suivi tokens/coûts ; benchmark v1 (package
  `benchmark/`, LAB) ; auth gate + impersonation admin ; 2e sous-agent tickets d'incidents.

## ⚠️ Top gotchas / règles actives
**Process :**
- **P0 - dataiku-agents v3 (L051/L052)** : l'expertise vient des ARTEFACTS du Flow (profil + value
  index, overrides humains jamais écrasés) - pas de valeur métier dans le repo. Le SQL appartient au
  SEMANTIC MODEL (tool mode Agent) : extraction = priorité de clés + DERNIER texte/lignes (jamais le
  premier = préambule) ; question sémantique = question user EN TÊTE + `IN` par colonne (jamais AND
  intra-colonne). UNE capability revenue `enabled` à la fois. Contrats gelés : `KNOWN_BLOCK_IDS`/
  `KNOWN_TOOL_NAMES` ↔ registre (test anti-dérive) ; norm partagée recettes↔agent. Tests :
  `python3 -m unittest discover -s dataiku-agents/tests`.
- **P0★ - Agents LangGraph (L055/L056, ✅ DSS)** : les Code Agents `*_langgraph.py` tournent en env
  **3.11** (langchain/langgraph installés). Appels LLM **natifs Mesh** dans les nœuds (jamais
  `as_langchain_chat_model`) ; `get_stream_writer()` en nœud SYNC OK ; `reasoning=high` réglé à la
  main sur le modèle Mesh. **`with_json_output` OBLIGATOIRE sur les extractions déterministes**
  (UNDERSTAND) - sinon le reasoning brûle le budget et casse le parse ; reasoning réservé au routing
  (orchestrateur tool-calling) et à la headline vérifiée. Originaux `*_agent.py` = rollback intact.
- **P0★★ - Sous-agent ASSISTE, ne DICTE pas (L058)** : `build_semantic_question` envoie au tool la
  **question user (source de vérité) + des HINTS** ; il **n'épingle PLUS de colonne pour un terme
  d'offre ambigu** (`alt_columns` non vide → `AMBIGUOUS OFFER TERM`, le **modèle Sonnet** tranche via
  ses instructions). Seules les valeurs **mono-colonne** (noms clients) sont suggérées (anti-typo).
  Le modèle (Sonnet+layer) résout mieux que le petit sous-agent. **Ne pas remettre le thinking au
  sous-agent** ; **ne pas hardcoder la hiérarchie d'offre dans le code** (elle vit dans les instructions
  du modèle, P3). Le tool « Semantic Model Query » pointe un modèle précis → **repointer après création
  d'un nouveau modèle** ; itérer le prompt = `update_aligned_semantic_model.py` (en place, sans re-index).
- **P1 - Graphe (L046)** : naviguer = `graphify query` D'ABORD (sous-agents aussi) ; exclusions corpus =
  `.graphifyignore` versionné. Tests front : `node --test test/*.test.js` depuis `Plugin/owismind/frontend/`.
- **P2 - Fin de session** : `/log-session` = mémoire + `/graphify --update` + **commit de session**
  (autorisation user permanente 2026-06-11) ; **JAMAIS de push** (l'user pushe).
- **P3 - Anti-« règles par bug » (L048, exigence user)** : jamais de valeur métier en dur dans la
  logique d'un agent. Cas inconnus → compréhension LLM contrainte (liste de candidats) ou refus
  honnête, pas de patch par valeur.
- **P4 - Hygiène mémoire (L127, 2026-07-03)** : CONTEXT.md reste LEAN (1-2 derniers runs pleins,
  chaîne ~2 semaines, le reste = pointeurs `sessions/*.md` + LESSONS) ; leçon revertée/supplantée =
  **marqueur sous son titre** (jamais de réécriture) ; sections datées de PROJECT_STATE = re-dater
  ou marquer « gelée » ; toute divergence MOCK vs backend LAB se règle en alignant le BACKEND sur le
  MOCK (L115, 3 instances).

**Frontend :**
- **F1 - Validation locale** : compile-check = `./node_modules/.bin/vite build --outDir /tmp/owi_bc --emptyOutDir` puis `rm -rf` (**jamais** dans `resource/` avant `/build-plugin`). **NO INSTALL** (tests = `node:test` + `unittest`).
- **F2 - `:global` thème (L022)** : sélecteur **entier** dans `:global(body[data-theme="dark"] .x)`. **Pas de `color-mix`** (L031) : `rgba` + tokens. Texte orange = **`--orange-text`** (AA, L039) ; fond teinté = `--orange-soft-dark`.
- **F3 - Router HASH** ; **F4 - thème** `body[data-theme]` avant mount ; **F5 - réactivité** version = `reactive()` mutée via `applyEvent`.
- **F6 - i18n** : interpolation **liste** `t('k',[a])` ; ajouts domaine dans `extra.js` (clé-plate par locale, fr+en) ; `messages.json` pristine.
- **F8 - Timeline (L029/L039)** : reducer pur `timelineModel.js` inchangé ; l'affichage groupé/ticker = **sélecteurs purs read-only** → ids stables, `timelineSignature` intacte.
- **F10 - Build : recâbler `body.html`** via l'outil **`Write`** (le `cp` est refusé par les permissions, L033). Le `cp -R` du packaging passe.
- **F11 - Tests front purs** : reducer/clamp/arbre/agentPick/sélecteurs timeline/evidencePick sans Vue → `node:test`.
- **F12 - ARBRE (L032)** : éditer/régénérer = échange FRÈRE ; `v-for` keyé `uid` stable ; un changement de version **REMOUNT** MessageAgent.
- **F13 - Scroll (L032/L038)** : `ChatThread` ne scrolle que sur `activeSessionId`, `exchanges.length`, signature gated `sending`, et **`evidence.open`**. **Jamais** de watch sur `turns`.
- **F19 - Layout Evidence (L043)** : grille `sidebar | chat 1fr | Evidence droite` ; repli sidebar = **`setSidebarCollapsed(true, false)`** ; re-clamp `evidenceW` sur resize ; `.ev-chips { z-index:5 }`.
- **F20 - Chips (L043)** : TOUS éditables ; présélection picker SEULEMENT pour `=`/`IN` ; `exclude_id` au distinct ; caps miroir backend ; reset/remove ferment le popover.
- **F14 - Feedback (L031)** ; **F15 - Agent persistant (L032)** : inchangés.
- **F16 - Ticker live (L039)** : `TransitionGroup` avec **`appear`** ; **UN** `.stream` persistant ; reduced-motion via `content:none`.
- **F17 - Navigation (L040)** : URL stampée `/chat/<sid>` au 1er échange ; route→store via **`chat.ensureSession`** ; un run live survit à un aller-retour Settings ; `canSend` exige `!threadLoading && !threadError`.
- **F18 - Chrono étapes (L041)** : durées scellées = stamps backend ; interval gaté `activityLive && chat.sending` ; markdown memoïzé.
- **F21 - Trust layer (L045)** : meta v1 ⇒ rendu identique ; badge via `trustLevel(meta)` pur ; steps `t('ev.exp.'+kind, params)` kind inconnu→opaque ; drill = `buildDrillLabels` (abort si >8 clés) ; aucune section nouvelle avec z-index ≥5.
- **F22 - Artefacts (L057, ✅ DSS)** : onglets Evidence/Chart/Table via `Tabs.vue` dans `EvidencePanel` ; `ArtifactChart.vue` = **Chart.js** (`chart.js/auto`, dep bundlée), couleurs résolues du thème + re-render au changement de thème ; `ArtifactTable.vue` = résultat capturé. Changer d'onglet ne touche PAS `evidence.open` (F13). Payload chart fourni par le backend (`data`).

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
   noms - pas ids - dans les events pour les labels). Span `semantic-model-query` recréé par le code
   au contrat gelé. `AGENT_RESULT` = statut machine (jamais affiché). UNE seule capability revenue
   `enabled` à la fois. Tests : `python3 -m unittest discover -s salesdrive/tests` (+ orchestrator/tests).
12. **Artefacts (L057 ✅ DSS)** : event gelé `ARTIFACT` (le whitelist timeline droppe les champs →
   event `artifact` normalisé dans `agents/streaming.py`) ; specs persistés dans **`webapp_artifacts_v1`**
   (table neuve `_v1`, UPSERT owner-stamped, lecture **read-only + statement_timeout**) ;
   `/evidence/meta` renvoie `artifacts` + pour chaque chart un `data` (payload Chart.js construit en
   **Python** `evidence/chart_payload.py`). Donnée = `generated_sql[].result` déjà capturé ; l'agent
   ne fournit que x/y/type/style. Best-effort (un échec de stockage ne casse jamais la réponse).

## 🔜 Prochaines étapes
0🚀NEW (2026-07-06 Run 5). **DÉPLOYER LA PROD v1.1 - suivre `docs/DEPLOY_PROD_V1_1.md`.**
   (1) Instance : supprimer les plugins dev `owismind_dev`/`owismind_dev_v2`, uploader
   `Plugin/ready-for-dataiku/owismind-upload.zip` (id `owismind`, v1.1.0). (2) Projet DSS prod :
   datasets DRIVE_Revenues + 3 recettes Flow, créer la webapp (connexion `SQL_owi`), permissions ;
   les tables se créent seules préfixées par la clé du projet (prod démarre à zéro, voulu).
   (3) Agents : scénario A (Code Agents restent dans `OWISMIND_PROD_V1`) = coller les 4 fichiers
   promus tels quels (`Xrv7GvfG`, `uO5hEzAs` env 3.11, tool `szOZCoU`, script semantic model en
   notebook puis re-dump) et ajouter l'orchestrateur via l'admin (whitelist dynamique cross-projet) ;
   scénario B (agents recréés dans le nouveau projet) = §3B du runbook (liste exacte des ids à
   remplacer). (4) Smoke §5 (dont refus honnête tickets). Promotions futures des agents =
   `python3 tools/promote_agents_to_prod.py` puis re-coller. Après validation : tag v1.1.0 possible.
0🖥️DONE (2026-07-06 Runs 2-4). **Source Data v3 ✅ VALIDÉ DSS** (« tout marche super », zip
   `index-DYvX83Tl.js` + orchestrateur DEV recollé). Reste à la demande : **promotion** vers le
   plugin DEV principal puis PROD (rebuild + package + orchestrateur PROD `Xrv7GvfG` avec le
   paragraphe SOURCE-DATA VIEW) ; différés : refetch meta par table (lève la limitation
   multi-table), export CSV d'agrégat, comparaison de périodes, profil de colonne, contexte
   évidence legacy enrichi, événement analytics pour le menu de colonne. Ancien smoke Run 2 : popover « Ajouter un filtre » se ferme au 1er clic extérieur
   (y compris clic sur le chrome DSS) et à Échap ; zone CALCULER = 1 carte Somme par défaut, dropdown
   « Mesures » (dernier choix non-décochable avec tooltip), gros chiffre complet jamais tronqué ;
   filtre `year_month` (colonne string à valeurs ISO) = mode plage AUTO + bascule « Choisir des
   valeurs précises » (chip BETWEEN bornes `YYYY-MM`..`YYYY-MM-99`) ; CASCADE : filtre
   `phase=ACTUALS` puis picker client = seuls les clients avec ACTUALS, éditer une chip = ses propres
   valeurs restent proposées ; fermer/rouvrir le panneau = filtres + recherche (visible dans le
   champ) + calc restaurés ; taper un prompt avec filtres actifs = bandeau -> Inclure -> chip
   « Données à l'écran » -> la réponse exploite/cite les chiffres de l'écran ; refus = plus de
   bandeau tant que la vue ne change pas ; dark. **PUIS recoller le prompt orchestrateur DEV**
   (`dataiku-agents/.../OWISMIND_DEV_OWIsMind_orchestrator.py`, Code Agent 038G7mlF env 3.11 :
   paragraphe SOURCE-DATA VIEW). Smoke Run 1 toujours valable (Analyser, Evidence lazy). Puis à la
   demande : port DEV principal / prod ; différés (refetch meta par table multi-source, export CSV
   d'agrégat, comparaison de périodes, profil de colonne, contexte évidence legacy enrichi). Voir
   `sessions/2026-07-06.md` (Run 2) + **L134-L137**.
0🏗️NEW (2026-07-03 Run 2). **RECOLLER + VALIDER la refonte benchmark.** LAB : coller les 3 panes
   launcher (`body.html` + `script.js` + `style.css` ; backend.py inchangé ce run mais la route
   `/api/config` du Run 1 reste à coller) et recharger. Plugin : uploader le zip DEV
   (`index-CZZt5we5.js`, inclut l'optimisation des espaces du Run 3) + redémarrer le backend.
   Smoke : layout benchmark (pickers dans l'en-tête, hero + colonne de stats sans vide, bande de
   référence en pied, dark) ; rename (vide/doublon/valide), carte fin
   de run -> Review pré-filtré -> Back, badge suggestions, golden-tag + datalist catégories ;
   page benchmark mono vs multi-mode (zéro appareil de modes en mono), onglets détail (SQL
   formaté, History si n>1), dark. Puis relancer la revue adversariale multi-agents sur les
   diffs (échouée au quota). Différés proposés : refonte nav launcher (onglets scopés agent),
   port du nouveau visuel plugin vers la webapp LAB results. Voir **L128-L129**.
0🧹NEW (2026-07-03). **Recoller la route LAB `/api/config`** : project-library `benchmark_webapp/views.py`
   + pane Python `benchmark_launcher/backend.py`, recharger le launcher (batchable avec les recolls
   L115/L117 déjà en attente ci-dessous). Smoke : éditer/supprimer une golden -> compteurs, catégories
   et dernier run se rafraîchissent (plus de 404 silencieux avalé par le best-effort). Voir **L127**.
0🎚️DONE (Run 6). **Mode éphémère + mode par réponse ✅ VALIDÉ DSS** (`index-CbbPsbRU.js`). Le mode
   par réponse est croisable chat_v5 x webapp_events_v1 pour le dashboard d'adoption. Voir **L126**.
0📊DONE (Run 5). **Analytics d'usage ✅ VALIDÉ DSS** (`index-D-NkcYpc.js`). Reste à la demande : dashboard
   d'adoption Dataiku (dataset SQL `webapp_events_v1` + rollups DAU/features/parcours), promo PROD, events v2 ; table DEV = DROP conseillé (vieille taxonomie). Voir **L125**.
0🧲DONE (Run 4). **Source Data ergonomie + cell-to-agent ✅ VALIDÉ DSS** (`index-CY8CEJu8.js`). Reste à la
   demande : promo PROD de l'arc Source Data (Runs 3+4) ; différés (messages DataLoader tournants, chips contexte éditables, envoi contexte seul). Voir **L123-L124**.
0🔎DONE (Run 3). **Source Data Explorer v1+v2 ✅ VALIDÉ DSS** (`index-Sd9XWyIM.js`). Reste à la demande :
   promo PROD ; leviers de charge (timeout 10s, sémaphore global, throttle dédié, cache TTL) ; remplir le bloc « Source datasets » des fiches d'agent. Voir **L121-L122**.
0🎨DONE (Run 2). **Artefacts + narration + recall ✅ VALIDÉS DSS + commités user.** Reste à la demande : promo
   PROD ; différés (artefacts INLINE reducer gelé F8/F12, recall > 3 tours, insight/warning cards, upgrade smart Flash-Lite->Flash) ; micro-polish. ⚠️ Process : **sous-agents en OPUS**. Voir **L119-L120**.
0🧠NEW (2026-07-02). **DÉPLOYER + VALIDER l'audit des agents (L118).** (Note Run 2 : l'orchestrateur
   DEV a été recollé et validé depuis ; reste à confirmer côté DSS le sous-agent revenus + le tool
   lookup + l'exécution `update_aligned_semantic_model.py` + re-dump.) Recoller en DEV DSS :
   les 2 Code Agents (`OWISMIND_DEV_OWIsMind_orchestrator.py` + `OWISMIND_DEV_SalesDrive_revenue_expert.py`,
   env 3.11) + le Custom Python tool `attribute_lookup` ; exécuter `update_aligned_semantic_model.py`
   en notebook (modèle `AHUh9hb`) puis `dump_semantic_model.py` (MODEL.md + .v1.json). **Agent +
   modèle ENSEMBLE** (marqueur `AMBIGUOUS TERM` = contrat sous-agent <-> instructions). PAS de
   zip/restart (python-lib intouché). Smoke : no-data avec [Périmètre] ; "billed revenue 2025"
   (ACTUALS + Bill%) ; "budget vs actuals YTD" (fenêtre alignée + divulguée) ; période farfelue
   (note) ; EVPL inchangé + ambiguïté d'identité divulguée ; 2 spécialistes 1 tour (plus de faux
   "indisponible"). PUIS : porter les fixes moteur au tickets expert DEV + promotion PROD.
   **Chantier plugin proposé (feu vert requis)** : binding par artefact (`agent_key` sur l'artefact,
   `/evidence/meta` par artefact) puis ré-introduire `source` (code dans l'historique git).
0🔬NEW (2026-07-01 Run 3). **DÉPLOYER + VALIDER la visibilité complète des résultats benchmark (L117).**
   **LAB** (commit `511e4bd`) : recoller project-library `benchmark_webapp/{views.py,dss.py}` + les panes des
   2 webapps (`backend.py`+`script.js`+`style.css` de `benchmark_results` ET `benchmark_launcher`), recharger.
   **Plugin** : uploader `owismind_dev-upload.zip` (DEV, 78 entrées) + **redémarrer le backend** (python-lib
   changé : `benchmark_view/{aggregate,lab_io}.py` + `api/routes.py` route `/benchmark/attempt`). **Pas de
   re-run** (donnée déjà stockée ; vieux runs d'avant la capture `generated_sql_json` = "aucun SQL capturé",
   normal). **Smoke** : déplier une question BONNE et une MAUVAISE -> réponse complète (non tronquée) + SQL
   RÉELLEMENT généré par l'agent + tableau de données ; dans le launcher, override le juge avec ce contexte
   visible au-dessus des boutons. Valider en DEV -> demander promotion prod (rebuild+package prod). Voir **L117**.
0🧪NEW (2026-07-01). **RECOLLER + VALIDER les 2 fixes LAB non validés.** Launcher webapp : onglet **JS =
   `OWIsMind_LAB/webapps/benchmark_launcher/script.js`** (les 3 champs du form golden : valeur attendue +
   type + notes) + onglet **Python = `.../backend.py`** (fix redo `value`). Recharger la webapp. Smoke :
   (a) éditer une question -> `expected_value`/`expected_value_type`/`notes` persistent (relire le row) ;
   (b) cocher "à refaire" sur une question testée -> "Run pending" -> la question repasse (2e tentative +
   evolution), plus de "nothing to run". Recoller aussi `views.py`/`registry.py`/`run_params.py` + MOCK
   results `script.js` s'ils ne sont pas déjà en DSS (le contrat golden `questions`+`agents` et
   `agent_key=id` en dépendent). **DÉCIDER** du durcissement de `reconcile_redo_after_run` (ne nettoyer le
   redo que pour les questions dont une ligne scored est plus récente que le launch : snapshot du dernier
   `run_timestamp` au launch). Voir **L115** + `sessions/2026-07-01.md`.
0🗂️NEW. **RÉORG FAITE (2026-06-26)** : tout le benchmark est sous **`OWIsMind_LAB/`** (carte = `OWIsMind_LAB/README.md`).
   Les chemins ci-dessous sont les NOUVEAUX : `OWIsMind_LAB/project-library/python/{benchmark, benchmark_webapp}` (lib),
   `OWIsMind_LAB/webapps/{benchmark_launcher, benchmark_results}` (panes), `OWIsMind_LAB/local-variables.example.json`
   (variable). Tests : `python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python`.
0🔬NEW. **DÉPLOYER + VALIDER l'intégration benchmark (2026-06-26).** **Lot 2 (plugin) ✅ FIX TABLE-NAME VALIDÉ DSS** :
   le 500 « nom de table trop long » est corrigé (L110) ; DEV uploadé (`index-pktQ-ICh.js`), suggestion écrite + relue.
   La table `webapp_golden_suggestions_v1` est créée sous son nom **RACCOURCI** (préfixe DEV) ; copier le nom EXACT via
   Admin > Storage (ligne `golden_suggestions`, ex. `OWISMIND_DEV_webapp_devtest-owismind_webapp_golden_s_90f625c2f8`).
   **Lot 1+3 (webapp LAB)** : suivre **`OWIsMind_LAB/project-library/python/benchmark_webapp/DEPLOY_GUIDE.md`** :
   recoller `views.py`+`dss.py` en project-library `python/benchmark_webapp/` ; créer les **2 webapps Standard** dans
   `OWIsMind_LAB` + coller les 4 panes de chaque (`OWIsMind_LAB/webapps/{benchmark_launcher, benchmark_results}/`) ;
   créer le dataset `benchmark_suggestions_promoted` ; ajouter le bloc `benchmark.suggestions` (connection `SQL_owi` +
   **table physique RACCOURCIE exacte** + promoted_dataset) à la variable ; permissions (LAB write + lecture connexion
   SQL). **Vérifier sur l'instance la méthode async de lancement de scénario** (dataikuapi `run_scenario`/`run` -
   best-effort, dégrade en `launch_unsupported`). Puis : lire le dernier run, lancer un run, promouvoir des suggestions.
   Voir **L103/L109/L110** + `sessions/2026-06-26.md` (Run final). **Promotion prod du fix sql_config** = rebuild + package prod + upload quand voulu.
0🧪NEW. **FINIR LE BENCHMARK EN DSS (2026-06-25) - suivre `benchmark/SETUP_GUIDE.md` (4 étapes).** (1) Re-coller
   `judge.py` + `schemas.py` (lib) + re-coller les 3 corps de step (`dss_steps/*` ont la lecture NaN-safe) ;
   (2) relancer **Judge + Aggregate** sur le `benchmark_runs_raw` déjà rempli (pas besoin de rappeler l'agent) ;
   (3) vérifier `benchmark_runs_scored` (objective_match/judge_score/correct/needs_review) + `benchmark_summary`
   (accuracy, latence p50/p95, coût, par agent×mode) + `benchmark_breakdown` ; (4) **run complet** (Smart/Pro/Claude,
   concurrency 3) + **recâbler le dashboard** (3 bandes). Config = variable projet `benchmark` (Local variables,
   modes `["Smart","Pro","Claude"]`, agent `agent:038G7mlF` `modes:true`). Prérequis : figer un **vrai footer**
   en fixture + confirmer l'id du LLM juge. Plus tard : section webapp, juge en panel, runs planifiés, promotion
   PROD (`agent:Xrv7GvfG`). Voir **L102** + `sessions/2026-06-25.md`. Le user a dit « on ira plus loin une autre session ».
0🎫NEW. **FINALISER + POFINER le 2e agent TICKETS (2026-06-19 Run 4) - suivre `dataiku-agents/PLAYBOOK_ADD_AGENT.md`.**
   Recipes (profil + value_index + value_catalogue) ✅ construites en DSS (NA-safe). Reste : (1) **override
   métrique COUNT** (`__dataset__/default_metric=ticket_count` + `avg_duration` AVG, JAMAIS SUM durée ni
   `format:"amount"`) via le dataset overrides ; (2) créer `TroubleTickets_Semantic_Model` (UI DSS sur le
   dataset) + `update_tickets_semantic_model.py` (cerveau, items `[CONFIRM]` : unité `Duration_ticket_total`,
   valeurs exactes `CurrentStatus`) ; (3) tool `tickets_semantic_query` (Agent OFF, Sonnet) -> id dans
   `TroubleTickets_expert.py` + registry ; (4) Code Agent env 3.11 -> `agent_id` réel dans l'orchestrateur
   **AVANT** re-coll (sinon erreur gracieuse, ou `enabled:False` en attendant) ; (5) re-coll orchestrateur (pas
   de zip, python-lib inchangé). Smoke-tests dans le PLAYBOOK. Débloque la **fiche client 360** (fan-out
   revenus+tickets, pont `Account_name`/`Customer_id`). Voir **L097** (NA-safe) + **L098** (factory).
0🔐DONE (2026-06-19 Run 3, ✅ VALIDÉ DSS + promu PROD). Auth gate + impersonation admin + plugin DEV `owismind_dev`.
   Workflow DEV->PROD en place. **Impersonation = TEMPORAIRE** (à retirer plus tard, blocs FENCÉS : `security/impersonation.py` + `features/admin-impersonate/` + routes.py/backend.js/session.js/chat.js/ChatView.vue/AppLayout.vue/AdminView.vue + clés `impersonate.*`). Voir **L094-L096**.
0📚DONE (2026-06-19 Run 2, livré local). Doc + plateforme web `project-documentation/site/index.html` (offline). Restes (décisions, sans DSS) :
   sort des em-dash PRÉEXISTANTS hors livrable ; remplacer `grep -P` par Python/`ggrep` dans le protocole règle #9. Voir **L093**.
0🎨DONE (2026-06-18 + 2026-06-19 Run 1). Refonte UI charte Orange + fiches d'agent admin (`validate_agent_meta` + `/agents`).
   Déployée, superseded par les rebuilds/déploiements ultérieurs (frontend live jusqu'à `index-CbbPsbRU.js`). Voir **L091-L092** + `sessions/2026-06-18-design-ui.md`.
0🔎DONE (resolver, 2026-06-18). `attribute_lookup` branché dans l'orchestrateur (built-in) + durci (multi-table, 1 ILIKE), RUN TEST OK.
   Grounding = SQL inline sur `value_index` (`_resolve_terms`) ; vrai tool DSS = `revenue_semantic_query` (v4oqA6R). Voir **L086-L087**.
0🧭DONE (Run 6 L080-L082 + Run 5 L071-L078). Agents recollés + validés depuis (voir 0🧠NEW) ; `GEMINI_FLASH_LITE_ID` = `flash-lite` confirmé.
   Différé (optionnel) : remplir `source_url` (capability `revenue_expert`) pour la source Evidence cliquable + mapping URL par-dataset multi-source. Voir **L080-L082**.
0🗣️DONE (2026-06-16 Run 3, ✅ VALIDÉ DSS). Narration live + Evidence lazy + modes + renommage. **Process permanent : à chaque
   modif repo des agents, recoller LES 2 Code Agents (env 3.11)** - OWIsMind_orchestrator + SalesDrive_revenue_expert (`agent:bHrWLyOL`) - et si backend change, upload zip + redémarrer.
0★DONE. Sous-agent assistif (L058) + agents LangGraph + artefacts + semantic model aligné = ✅ VALIDÉS DSS (le renfort
   `update_aligned_semantic_model.py` est repris par 0🧠NEW). Voir **L055-L059**.
0skill. **Skill agentique** : lever les `UNVERIFIED` sur l'instance (import `DKUChatModel`, API semantic model, ids modèles
   non-Anthropic) ; promotion globale `~/.claude/skills/` si réutilisation cross-projets.
0bis. Poursuivre les smoke tests README §5 (part du total, YoY, trend, ellipses, « IPL » ambigu) ; toute divergence ->
   profil/overrides/prompts, jamais de valeur en dur (P3).
0ter. **Agent tickets** (2 recettes + 1 Code Agent + 1 entrée registre) -> débloque le 360 parallèle (repris par 0🎫NEW).
1. **RECUEILLIR LES AJUSTEMENTS du user sur le trust layer** : « marche bien mais pas
   encore comme je veux » - faire préciser AVANT toute modification.
2. **SalesDrive v2 - consolidation** : tester un cas de vraie ambiguïté de valeur (ex. « IPL + ») et
   un plan multi-étapes (agent+tool) ; quand confiance OK → retirer l'entrée visual `salesdrive` du
   registre ; supprimer le CSV de traces local (`salesdrive/webapp_devtest-…csv`, hors repo).
3. Re-tester en DSS ce qui ne l'a jamais été : L040 (bouton New conversation) / L041 (chrono étapes).
4. **Evidence v3 (différé)** : restriction admin des datasets, keyset pagination, drill multi-requêtes,
   fraîcheur des sources ; fallback LLM seulement sur cas réel.
5. **2ᵉ task mentionnée par l'user le 2026-06-09** - toujours à clarifier.
