# CONTEXT - OWIsMind (mémoire courte, chargée à CHAQUE session)

> Maintenue à jour à chaque `/log-session`. Détail complet → `PROJECT_STATE.md` (§13 = frontend) ; leçons → `LESSONS.md`.
> **OWIsMind** = plugin Dataiku DSS : WebApp **Vue 3 + Vite** (front buildé, servi par DSS) + backend **Flask** modulaire
> (`python-lib/owismind/`) qui parle aux agents via **LLM Mesh** et stocke en **SQL direct** (`SQLExecutor2`, PostgreSQL), **sans Flow** au runtime.

## 🎯 Focus courant
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

**🎫 SESSION 2026-06-19 Run 4 (2e sous-agent "tickets d'incidents" + factory repo) - ✅ TESTÉ DSS
(« marche plutôt bien »), à pofiner.** 2e expert sur `TroubleTickets_year` (83 738 l., 21 col.) à côté
des revenus. **Moteur ~95% générique** : `agents/TroubleTickets_expert.py` = copie revenus, corps
**byte-identique** (contrats gelés `KNOWN_*`/`AGENT_RESULT`/span/caps), seuls l'en-tête CONFIG + les
textes hiérarchie-offre (neutralisés) changent. Orchestrateur = **1 entrée `CAPABILITIES["tickets_expert"]`**
+ allowlist `lookup_search_columns` (recherche restreinte par domaine). **Modèle sémantique DÉDIÉ séparé**
(décision, question user : jamais ajouté au modèle revenus - "une table jamais de JOIN", instructions/golden
focalisées, binding tool 1:1) : scripts `tools/semantic_model/update_tickets_semantic_model.py` +
`dump_tickets_semantic_model.py`. **Recipes rendues génériques (auto-IO) + NA-safe** (fix
`infer_with_pandas=False` -> fallback `True` sur int nullable `Duration_ticket_total`, **L097**) ;
`build_value_catalog_recipe` **dataset-adaptatif** (revenus curé inchangé ; non-revenus = catalogue
générique `search_domain="value"`, exploité par `attribute_lookup`). **Factory repo** :
`dataiku-agents/registry.json` (source de vérité unique par domaine, dev-owned) + `DATASETS.md`
(inventaire colonnes) + `PLAYBOOK_ADD_AGENT.md` (runbook). 283 tests verts (anti-dérive **généralisé**),
revue adversariale 4-dim = **0 finding réel**. **À FINALISER (PLAYBOOK)** : override métrique COUNT
(jamais SUM durée), modèle sémantique DSS + `update_tickets_*`, tool `tickets_semantic_query` (Agent OFF,
Sonnet), Code Agent env 3.11 + **`agent_id` réel AVANT de re-coller l'orchestrateur** (sinon erreur
gracieuse). Voir **L097** (NA-safe) + **L098** (factory / 2e agent).

**🔐 SESSION 2026-06-19 Run 3 (auth gate + impersonation admin + plugin DEV/PROD) - ✅ VALIDÉ DSS
(user : « super tout fonctionne à merveille »).** 3 livrables via sous-agents + 3 revues adversariales
sécu ; zip DEV déployé. **(1) Auth gate** (`AuthGate.vue` + `session.authState` + `App.vue`) : `/me` 401
-> écran plein "non identifié" (EN/FR + thème + F5, vrai logo), AUCUNE navigation ; autres erreurs (hors
DSS) gardent le shell. Clés `authgate.*`. **(2) Impersonation admin "se mettre à la place d'un user"**
(TEMPORAIRE ; remplace l'idée abandonnée de "revue read-only") : Administration -> "Consulter les
conversations" -> liste users -> clic -> la webapp **recharge en s'identifiant à ce user**, **lecture
seule** (envoi off UI + serveur 403 `impersonation_read_only`), **admin-only**. Backend = chokepoint
`security/impersonation.py` (`effective_identity`, header `X-OWI-Impersonate`, honoré **seulement si le
caller RÉEL est admin**), câblé FENCÉ dans `routes.py` (READ swap : /me,/usage,/conversations,
/conversation,_evidence_guard ; WRITE bloqué : chat start/feedback/stop ; /me ne record PAS ;
/chat/poll,/agents,/admin = identité réelle). Front `features/admin-impersonate/` (header injecté dans
`services/backend.js`, picker, banner+Quitter, `canSend && !impersonating`). **Isolé/supprimable.** Revue
sécu dédiée = **0 crit / 0 high / 0 medium**. Voir **L095**. **(3) DEV/PROD = SOURCE UNIQUE + cible de
build** (L094) : `tools/build_dev_plugin.py` + skill `/package-plugin-dev` -> `owismind_dev-upload.zip`
(id `owismind_dev`, label "OWIsMind (DEV)", **webapp "OWIsMind - AI Agents (DEV)"**, package python
renommé, base Vite via `OWI_PLUGIN_ID`). **Prod 100% inchangée.** Tables = **create-if-not-exist** déjà
partout (rien à changer) : DEV **sans prefix** -> vraies données prod (impersonation des vrais users) ;
**`table_prefix=dev`** -> bac à sable. Promotion prod = rebuild prod + upload. **Ancienne feature
SUPPRIMÉE** (`admin_inspect.py`, `features/admin-inspect/`, route `/admin/inspect`, clés `inspect.*`) :
avait fait v1 (revue read-only) -> v2 (sélecteur de source), jetées sur recadrage user (**L096**).

**📚 DOCUMENTATION ULTRA-COMPLÈTE + PLATEFORME WEB "PARCOURS" (2026-06-19 Run 2, session autonome nuit) -
✅ LIVRÉ LOCAL (doc + site, commit de session).** Doc `project-documentation/` **corrigée + complétée** par
workflow Sonnet (11 clusters, ownership par fichier, vérif adversariale + intégration) : budget blocage = **codé**
(`/chat/start` 402 fail-open, plus "non implémenté") ; EN/FR de `CONVENTIONS.md` §1.3 corrigé (doc = **anglais**) ;
3 features 2026-06-18 ajoutées (fiches d'agent admin `validate_agent_meta`, budget/quota `storage/budget.py`+
`webapp_user_quota_v1`, charte/UI Orange + rail) ; **+5 fichiers** (user-guide `05-account-and-budget`/
`06-agents-and-administration`, ADR `0013`/`0014`/`0015`) ; **61 .md** propres (21 routes, build->fichiers->zip
détaillé + matrice). **Plateforme `project-documentation/site/`** = **HTML/CSS offline** (double-clic `index.html`),
**parcours descendant** 8 pages (niveau 0 accueil -> 7 ADR), chrome JS (rail+topbar+TOC scrollspy+pager+recherche+
thème persistant clé `owi-theme`), **~30 diagrammes SVG faits main** (4 couches, séquence chat 15 étapes, boucles
d'agent, pipeline build->zip...), **vrai logo** `assets/orange-logo.png`. **QA navigateur réel (Playwright + http
local)** = OK (2 thèmes + persistance, logo, diagrammes denses aérés). **Bonus** : 12 em-dash corrigés dans
`Plugin/owismind/resource/compute_available_connections.py`. **⚠️ L093 : `grep -P` échoue sur le BSD grep du Mac
-> auditer les em-dash en PYTHON.** Détail -> `sessions/2026-06-19.md` Run 2.

**🎨 REFONTE UI "MAQUETTE ORANGE" (multi-agents) + CHARTE DURABLE (2026-06-19 Run 1) - ⏳ CODÉ + build + zip,
NON validé DSS.** L'user a fourni une **maquette HTML** (Account & Admin) ; refonte du style des vraies pages
"comme la maquette" via **6 agents Sonnet en parallèle** (découpage **par ownership de fichier**, brief charte
commun, `Tabs.vue`/`tokens.css`/i18n intouchables) : `foundation` (chrome partagé + primitives ; ajout
`--fw-heavy:800`), `shell` (rail + top bar), `settings` (My account), `admin` (Administration + modale profil
agent), `agents` (bibliothèque + fiche), `modepicker` (Response mode). Géométrie **carrée** assumée -> `Button`/
`Modal` partagés deviennent carrés/plats (le chat hérite, on-charter ; corrige radius 16px+blur+ombre de la modale).
**Correctif logo (retour user)** : `shell` avait reconstruit le logo en **carré CSS** -> **rebranché la VRAIE
image** `frontend/src/assets/orange-logo.png` (`<img :src="logoUrl">`) rail + sidebar. Vérifs : périmètre = 12
fichiers, **0 tiret long**, **0 clé i18n manquante**, **0 color-mix/blur/hex en dur**, build Vite OK. Zip propre
**79 entrées, `index-BHeG2NRY.js`** (png bundlé). **Charte gravée** : `CHARTE_ORANGE_UI.md` + règle #10
(`CLAUDE.md` racine + `frontend/CLAUDE.md`) + mémoire `orange-charter-styling.md`. **À FAIRE DSS** : **upload zip**
(frontend only -> **PAS de redémarrage backend**, pas de recoll d'agent) + smoke-tests (vrai logo, pages carrées,
thème, modales à plat). Détail -> `sessions/2026-06-19.md`. Voir **L092** (+ L091 discipline de marque).

**🎨 REFONTE UI "CHARTÉ ORANGE" + FICHES D'AGENT RÉDIGÉES PAR L'ADMIN (2026-06-18, session design) -
⏳ CODÉ + revu (2 workflows) + corrigé, NON validé DSS.** Détail -> `memory/sessions/2026-06-18-design-ui.md`.
Session **design only** (frontend Vue + un seul ajout backend). **Descriptions d'agent hardcodées BANNIES** :
`agentMeta.js` **supprimé** ; accroche/description/capacités/outils/icône/badge **rédigés par l'admin**
(modale dans `AdminView`), validés/bornés serveur (`validate_agent_meta`, **pur, ne lève jamais**, whitelist
icônes = registre front, sanitize), stockés **dans le JSON `enabled_agents` de `webapp_settings_v1` (PAS de
nouvelle table)**, exposés via `/agents` **sans fuite** d'`agent_id`/projet. **Sidebar repliée = RAIL**
(carré de marque qui déplie, `+`, Agents, puis aide `?` au-dessus du profil ; liste `v-show` montée = zéro
re-fetch). `AgentsView` (recherche + fiche éditoriale) + `AdminView` (sélection + formulaire) refondus
charté. **Settings -> "My account"**, **anglais par défaut** (FR gardé). **⚠️ LEÇON L091 (discipline de
marque, exigence user)** : je m'étais permis des ajouts NON demandés (bouton New conversation orange, logo
centré sur l'accueil, titre passé en noir, **glows/grosses ombres**, **focus-ring orange global** = contour
sur la zone de saisie, puces carrées d'eyebrow) -> **tout remis comme avant** après 2 retours user + **bouton
de dépli restauré** (`MainTop`, `v-if collapsed`). **Charte Orange officielle fournie par l'user** (orange =
accent RARE sur actions/états actifs ; blanc/noir ; aplats ; ombre 1px ; carré-net ; Helvetica ; pas de
dégradé/blur/emoji) -> **à coller dans `CLAUDE.md`** (proposé, non fait). Audit sécurité final = **CLEAN**
(0 fuite, XSS sûr, pas de surcharge instance). **À FAIRE DSS** : upload zip (**79 entrées, `index-Bd4XhFvS.js`**)
+ **REDÉMARRER backend** (python-lib changé : `validation.py`+`routes.py`) + remplir les fiches dans
Administration > Agents. Pas de recoll d'agent.

**💳 WEBAPP - SUIVI CONSO + BUDGET MENSUEL $50/USER (2026-06-18, session webapp parallèle) - ⏳ CODÉ +
430 backend + 124 frontend + build + zip, NON validé DSS ; audit sécu + audit RENFORCÉ sûreté-instance =
0 danger.** Détail complet -> `memory/sessions/2026-06-18-webapp-budget.md`. Crédit mensuel **50 $/user**
(mois calendaire, reset le 1er, basé sur le coût Mesh `estimatedCost` déjà capté par échange). **Profil
(Settings)** : vraie carte Budget (jauge dépensé/limite, restant, date reset, ligne de transparence sur
l'origine de la limite) + carte Usage (tokens mois + lifetime). **Chat** : `canSend` bloqué + bannière
transparente quand épuisé (enforcement serveur dans `/chat/start` -> 402, fail-open). **Admin onglet
Quotas** : défaut global + boost temporaire global + table par user + override **un/plusieurs/tous**,
**permanent ou temporaire**. **NO ALTER** : nouvelle table **`webapp_user_quota_v1`** (overrides), défaut
global dans `webapp_settings_v1`, bucket `webapp_usage_monthly_v1` + lifetime `webapp_users_v1` inchangés.
Backend : `storage/budget.py` (résolution + gate + admin overview + set/clear) + routes `/usage` +
`/admin/budget(/users)` + enforcement. Durcissements sûreté (au-delà du requis) : **cache config en process**
(supprime le 2e aller-retour DB par envoi de chat) + `settings.get_setting/set_setting` bornés
`statement_timeout`+read-only ; budget reads/writes idem (calque `artifacts.py`). **À FAIRE DSS (user seul)** :
upload zip (**79 entrées, `index-DeS8HQfW.js`**) + **REDÉMARRER backend** (python-lib changé) ; **PAS de recoll
d'agents**. Table quota créée lazy. ⚠️ Coexiste avec les éditions concurrentes session-agents (feature agent
profile/meta : `validate_agent_meta`, `profile` dans la whitelist) - merge propre (parties de fichiers
distinctes). **AUCUN commit/push de ma part** (interdit cette session).

**🧹 NETTOYAGE + DOC REFLET-DSS de `dataiku-agents/` + SIMPLIFICATION recettes/tool + DEBUG Evidence
dégradé PROD (2026-06-18, session `dataiku-agents/`) - ✅ LOCAL (repo only, aucun DSS de ma part).** Doc
réécrite pour qu'un Claude sans contexte comprenne TOUT le mécanisme (audit 6 lecteurs -> réécriture ->
revue adversariale 3 lecteurs) : `CLAUDE.md` auto-suffisant + READMEs (`README`/`agents`/`tools`/`recipes`/
`semantic_model`) + **nouveaux** `MODEL.md` (vue lisible du modèle live) + `dump_semantic_model.py`.
Dérives corrigées : `Value_Catalog` = **utilisé** (fallback alias `attribute_lookup`, plus "roadmap") ;
`attribute_lookup` existe DSS + branché built-in orchestrateur ; `resolve_filter_value` à supprimer ;
tool sémantique = **mode Agent OFF (pipeline linéaire) Sonnet** ; intent fantôme `lookup` retiré.
**`/simplify`** du profiler (en-tête 51->14 l., `ENRICH_LLM_ID`->**`claude-opus-4-7`**) + des 2 autres
recettes + le tool (267 tests, 0 tiret, ref morte `dataset_expert_agent.py` retirée). **GOTCHA pandas
lazy** (env de test NO INSTALL sans pandas : ne jamais hoister `import pandas` top-level, L089). **DEBUG
Evidence "dégradé" PROD = RÉSOLU** : la requête de l'agent visait une table non remappée vers le projet
PROD (script de migration sémantique DEV->PROD qui avait **droppé `_PROD_V1`** -> `OWISMIND_drive_revenues`
au lieu de `OWISMIND_PROD_V1_drive_revenues`) ; c'est le **modèle sémantique** (entity `datasetRef` +
golden queries) qui décide la table, **pas le code agent** ; le backend Evidence matche la table du FROM
contre les datasets SQL du projet webapp (L090). 2 scripts versés dans `tools/semantic_model/` :
`migrate_semantic_model_to_project.py` (remapping **dérivé des clés de projet** = anti-bug, garde
anti-doublon) + `remap_semantic_model.py` (correction en place + ré-index). **DEV reste le projet de
référence du repo** ; `OWISMIND_PROD_V1` = entité PROD parallèle (table `OWISMIND_PROD_V1_drive_revenues`).

**📚 DOCUMENTATION COMPLÈTE DU PROJET + PITCH CUSTOMER DAY (2026-06-18, session doc parallèle) - ✅ LIVRÉ
(read-only sauf `project-documentation/`).** `project-documentation/` = doc d'ingénierie EN ANGLAIS, en
couches, **53 fichiers** markdown (~136k mots) : 00-overview ... 09-maintenance + portail README + 12 ADR
+ 24 docs à diagrammes Mermaid. Construite par 3 workflows (recherche 14 packs -> rédaction 53 -> vérif/
correction), **0 tiret cadratin** (byte-safe), **761 liens internes valides**. Packs bruts dans
`project-documentation/.workdir/` (scratch interne, supprimable). **Pitch** dans
`project-documentation/presentation-customer-day/` : `01-deck-structure-and-slides.md` (7 frames + prompt
prêt pour claude.ai + fact-check) + scripts orateur `02-...FR.md` (accents corrigés) et `03-...EN.md`,
~15 min, thèse « OWIsMind = un SYSTÈME (webapp + agents + recipes + SQL), pas une webapp ni un agent ».
Doc en anglais (choix user) ; coexiste avec `docs/` + `memory/` en français ; aucun code touché ; aucune
incidence DSS. Voir **L088**.

**🔎 `attribute_lookup` BRANCHÉ (ORCHESTRATEUR built-in) + durci + multi-table (2026-06-18 Run 2) -
⏳ CODÉ + 267 tests verts + RUN TEST DSS validé (lookup rapide ~14s + descente expert), À RECOLLER
+ MAJ tool DSS.** Conseil multi-agents (Workflow, moi=PDG + 4 conseillers + 2 contradicteurs) = **4/4
brancher dans l'ORCHESTRATEUR** (built-in, comme `show_table`/`current_date`) : **zéro contrat `KNOWN_*`
touché, SOUS-AGENT INCHANGÉ** (1 seul agent à recoller). Branche sous-agent dominée (latence + recoût
contrat). Provenance Evidence via subspan `semantic-model-query` (canal réel ; `state['captured']`
vestigial). **Multi-table générique** (exigence user) : le modèle passe un **domaine logique**,
l'orchestrateur résout la table via le registre (`lookup_domains()` lit `lookup_dataset`/`lookup_catalog`
par capability) - rule #3/#4 OK. **SQL lisible** : `build_search_sql` = **UN seul `ILIKE`** sur
`concat_ws` (au lieu de 18 `OR`), accents par **`translate` à la requête, données intactes** (user
REFUSE de toucher la base de prod -> pas d'extension `unaccent` ; flag/branche unaccent retiré, fonction
`accent_fold_sql`). Durcissement : flags `rows_capped`/`multi_column`, garde needle court, cache TTL
(clé inclut dataset), `not_found` adouci (jamais "absent"), garde found-vide->not_found, pliage accents
symétrique. **Value_Catalog + fallback alias/`suggestions` GARDÉS** (décision user finale, après une
suppression annulée). Revue adversariale du diff = **0 critical/0 high, 2 LOW corrigés**. Commentaires =
zéro empreinte IA (demande user). **DSS à faire** : (1) MAJ le Custom Python tool `attribute_lookup` ;
(2) recoller l'ORCHESTRATEUR (env 3.11) ; (3) **SUPPRIMER l'objet tool `Drive_Revenues_resolve_filter_value`**
(jamais appelé, charge 170K en pandas-RAM ; `resolve_filter_value` reste un label timeline, pas un tool) ;
(4) optionnel `LOOKUP_TOOL_ID` (sinon fallback par nom). Pas de zip/redémarrage (python-lib inchangé).
**Leçon process** : ne JAMAIS exécuter une suppression de feature/dataset sans feu vert explicite
(conseiller d'abord) - une tentative de suppression Value_Catalog non validée a dû être restaurée. Voir **L087**.

**🧹 NETTOYAGE / RÉORGANISATION REPO + DOC `dataiku-agents/` (2026-06-17, après Run 7c) - ✅ local
(nettoyage + structure + doc only, pas de DSS).** Vestiges v2 `orchestrator/`+`salesdrive/` **supprimés** ;
`cadrage/` -> **`docs/cadrage/`** (git mv), `agentic-research/` -> **`docs/agentic-research/`** (gitignored),
refs mises à jour partout (CLAUDE.md, mémoire, skill, docs, ignore files). **`dataiku-agents/` = mini-repo
documenté** : README maître + CLAUDE.md réécrits, nouveaux `agents/`+`recipes/`+`tools/` READMEs, recette
`Value_Catalog` versée en STATUS roadmap. **Archi v3 CLARIFIÉE** : grounding **SQL inline sur `value_index`**
+ **2 tools** (`revenue_semantic_query` v4oqA6R + `dataset_lookup` 9FEzVZk) ; `Value_Catalog` + tool Python
`Drive_Revenues_resolve_filter_value` = **roadmap, PAS câblés en v3** (labels `resolve_filter_value`/
`dataset_sql_query` = events, pas des tools). **Recâblage lookup->resolver Python = DÉFÉRÉ** à une session
dédiée (décision user). Fix vérifié `flash-light`->**`flash-lite`** (2 agents, preuve = code déployé collé).
227 tests verts + revue adversariale doc-vs-code (5 agents) = 0 lien cassé, 2 LOW corrigées. Voir **L085**.

**🎨 RUN 7 / 7b / 7c (2026-06-17) - POLISH UI CHAT - ✅ VALIDÉ DSS (user : « super tout fonctionne à
merveille », 2026-06-17). Zip déployé `index-DCY_crmu.js` (77 entrées), backend redémarré.**

**🎨 RUN 7c - correctif pop-up de mode : la VIBRATION au survol (hover→reflow→recentrage modale→boucle
mouseenter/leave) corrigée à la racine = passage en **clic-pour-sélectionner + footer Annuler/Valider**
(pattern DSS, plus de hover) + `min-height` détail. Restyle charte Orange 80/20 : ligne sélectionnée gris
+ barre orange (plus de teinte), descriptions en noir, dots de coût sombres, coins quasi carrés, icône
d'en-tête retirée. Clés `mode.cancel/validate`. (L084.) ✅ VALIDÉ DSS.**

**🎨 RUN 7b - ban `—`/`–` partout (règle #9) + pop-up de mode refondu (mood DSS, liste/détail, jauges
Coût+Vitesse, Éco recommandé) + écran d'agent rempli (`agentMeta.resolveAgentMeta` repli substring → le
label « Agent - OWIsMind_orchestrator » résout la carte owismind). ✅ VALIDÉ DSS (L084).**

**🎨 RUN 7 - POLISH UI CHAT (frontend + 1 point backend titres ; agents NON touchés) - 2 revues
adversariales (qualité+sécurité = 0 défaut). ✅ VALIDÉ DSS.**
- **Largeur** : token partagé `--chat-col: 90%` / `--chat-col-max: 1200px` → `.conv-inner` (était 760px),
  `.prompt-wrap` (était 920px) et `.empty` partagent la **même mesure** (+padding `--s-7`) = texte aligné
  bord-à-bord avec la zone de saisie. **Écran vide** : `.prompt-wrap.in-empty` plafonné à **760px**.
- **Mode picker** : feu tricolore - **Éco vert** (`--success`), Medium orange, High rouge (`--danger`) ;
  pop-up dé-IA (icône `sparkles`→`sliders`, badge « Mode actuel »→coche `check`, ⚠️ emoji→icône `wallet`,
  copie FR/EN réécrite, clé morte `mode.current` retirée). **Tokens `--success-soft`/`--danger-soft`**
  (clair+sombre) corrigent des rgba codées en dur **invisibles en dark** (bug revue R1).
- **Guidage** : `prompt.placeholder` surchargé (extra.js, override de messages.json pristine) + `empty.tip`
  (« soyez précis ») dans `ChatEmpty`. **AgentPicker** `max-width` 240→320px ; **micro déplacé à droite**
  (près d'Envoyer) ; **`Modal`** close `aria-label` en dur FR → `t('x.close')` (corrige tous les modals).
- **Titre conversation (backend)** : `sql_builders.build_conversation_list_query` nettoie le 1er message
  (`LEFT(BTRIM(regexp_replace(…,'[[:space:]]+',' ','g')), tlen)`) + `CONV_TITLE_MAXLEN` 140→**56**.
  **DÉRIVÉ** (pas de colonne DB) → rétroactif, sans migration. Colonne DB = différée à la feature titre-IA.
✅ **DÉPLOYÉ + VALIDÉ DSS** (zip `index-DCY_crmu.js` uploadé, backend redémarré). Colonne `title` en base =
toujours différée à la feature titre-résumé-IA. Hook pre-commit anti-`—` = proposé, non installé.

**Avant - 🎯 RUN 6 (2026-06-17) - modèles par mode revus + argent €/transparence + désambiguïsation DÉFÉRÉE +
source Evidence CLIQUABLE + nettoyage prod - ⏳ CODÉ + 227 agents + 384 backend + 116 frontend + build + zip,
NON validé DSS (L080-L082).**
- **Modèles (L080)** : eco=**Gemini 3.1 Flash-Lite** (DÉFAUT), medium=**Gemini 3.5 Flash**, high=**Sonnet** ;
  **gpt-5.4-mini supprimé**. Front : défaut Éco + badge « Recommandé » déplacé sur Éco. **⚠️ Vérifier
  `GEMINI_FLASH_LITE_ID`** (best-effort `…/gemini-3.1-flash-light` ; si Mesh=`flash-lite`, corriger les 2 fichiers).
- **Argent € + transparence (L080)** : `metric_unit` dérive la devise du **nom de colonne** (`amount_eur→€`,
  **aucune config profil**) ; le sous-agent préfixe `[Périmètre]/[Scope]` (scénario+« par défaut » / période+
  « aucun filtre d'année » / entité / devise) ; PERSONA orchestrateur impose `€` + séparateurs + restitution du
  périmètre + analyse rédigée.
- **Désambiguïsation (L081)** : `defer_multicolumn_offer_terms` - terme d'offre ambigu sur **≥2 colonnes** =
  **déféré** au modèle sémantique (Sonnet, « NEVER default to sirano_product ») + **divulgation**, plus de
  clarification ; mono-colonne (2 clients) demande encore. P3 (décision par **nombre de colonnes**). Affine L058.
- **Bloc « Sources » retiré** du chat (Evidence le porte déjà).
- **Source Evidence CLIQUABLE (L082)** : URL configurée dans le **registre orchestrateur** (champ `source_url`,
  capability `revenue_expert`, **VIDE → à remplir avec le lien Dataiku**), propagée **additif** via les items SQL
  (`_find_generated_sql`→streaming→stream_manager→capture→`service.py` `meta.source.url`) →
  `EvidenceSources.vue` rend un `<a target="_blank">` (orange AA, i18n `ev.proof.sources.open`). **Backend
  python-lib CHANGÉ → REDÉMARRER**.
- **Nettoyage prod** : commentaires agents réécrits en anglais simple, zéro empreinte IA (dates / refs
  session-leçons / « VERIFY/ACTION REQUIRED/<--/Flip after DSS test » / « root cause/proven/seen live/user
  decision/the #1/ported » / ⚠️ en commentaire / première personne). ⚠️ gardés dans les **chaînes utilisateur**.
  **Revue adversariale** (Workflow 26 agents, 4 dim × 2 sceptiques) = **0 bug de code** (3 commentaires périmés
  corrigés).
À DÉPLOYER : **recoller les 2 Code Agents** (env 3.11) + **remplir `source_url`** (si lien voulu) + **upload zip**
(**77 entrées, `index-8spQsYzC.js`**) + **REDÉMARRER backend** (python-lib changé Evidence/source). **NON validé DSS.**

**Avant - 🧭 MODEL-AGNOSTIC (fin escalade + Dataset Lookup + stop + popup mode) PUIS 3 AUDITS À L'AVEUGLE
- Run 5/5b/5c (2026-06-16) - ⏳ CODÉ + 217 tests agents + 116 frontend + build + zip, À VALIDER DSS (L071-L078).**
**🔒 État : audité à l'aveugle 3× (sous-agent « architecte » + skill agentique, copies /tmp, zéro contexte),
durci à chaque passe → 3ᵉ passe = VERDICT « production-ready côté archi agentique », 0 Critical / 0 High.**
À DÉPLOYER : **recoller les 2 Code Agents** (env 3.11) + **vérifier `GEMINI_FLASH_ID`** (2 fichiers) + upload zip
(**77 entrées `index-3FmqVbc1.js`**, backend python-lib inchangé → pas de redémarrage). Les audits n'ont
touché QUE les Code Agents (zip inchangé depuis Run 5b). **NON validé DSS** (comportement modèles + Dataset
Lookup réel + rendu = intestables hors instance). [Obsolète Run 6 : eco=mini retiré, défaut medium→eco,
zip `index-3FmqVbc1.js`→`index-8spQsYzC.js`, python-lib changé.]
Genèse - Test DSS du Run 4 = ÉCHEC sur gpt-5.4-mini (escalade **systématique** + message hardcodé ; sinon
**narre puis s'arrête**). User : abandonner gpt-5.4-mini en défaut, passer Gemini 2.5 Flash, **arrêter les
hacks mono-modèle**, archi optimale qui tourne **même sur les petits modèles**. 4 chantiers :
- **Modèles par mode (L071 + ajustés L075)** : **escalade SUPPRIMÉE en entier**. `LOOP_LLM_BY_MODE` =
  **{eco:gpt-5.4-mini, medium:Gemini Flash, high:Sonnet}** (gpt-5.4-mini GARDÉ en Éco - marche bien, ~gratuit).
  **1 modèle pilote tout le tour**. Le mode se **propage au sous-agent** (`MODE:` dans context → `forced_mode`
  → `pick_subagent_llm`, threadé dans l'état) : Éco=mini, Medium=Gemini, High=Sonnet (→ **High = Sonnet partout**).
  Hook `SEMANTIC_TOOL_ID_BY_MODE` pour le modèle sémantique (config DSS).
- **Narration séparée + conditionnelle (L075)** : section « NARRATE AS YOU GO » du prompt **détachée**,
  ajoutée **seulement si `narration_enabled(mode)` (≠ eco)**. En Éco (mini) : pas de demande de parler pendant
  le tool-call (anti narrate-and-stop) → ticker déterministe. ACT-FIRST dans tous les modes.
  **⚠️ VÉRIFIER `GEMINI_FLASH_ID`** (orchestrateur + sous-agent) = best-guess
  `…vertex_ai/gemini-2.5-flash` → corriger l'id exact (1 ligne/fichier).
- **Dataset Lookup (L072)** : tool Dataiku `9FEzVZk` ajouté au sous-agent ; intent **`lookup`** (récup
  d'attribut sans SQL, ex. account_manager de X) + champ `attributes` + **conscience schéma LIVE**
  (`Profile.live_columns`/`match_attribute`). Fallback SQL si échec/aucun filtre. Span gelé `semantic-model-query`.
- **Stop = attente + « Stopping… » (L073→ajusté L075)** : revert de l'optimiste. `stopGeneration` pose
  `activeVersion.stopping=true`, POST `/chat/stop`, **garde le polling** ; `MessageAgent` affiche un spinner +
  « Stopping… » clignotant jusqu'à l'event terminal. Flag `stopping` nettoyé sur tout terminal.
- **Popup de mode (L075)** : `ModelModePicker` réécrit = pilule → `Modal` (3 cartes : libellé, description,
  jauge coût €/€€/€€€, badge « Recommandé » Medium) + encart **enveloppe 50 €/mois**. Medium par défaut.
- **Hiérarchie timeline (L074)** : steps `SUB_AGENT_*` **indentés** (CSS `.sub-step`). Persistance events = différé.
- **Audit (L076-L078)** : 3 passes à l'aveugle → durci. Corrigés notamment : caches keyés stable (#1),
  appariement tool_call↔output garanti (#2), **bypass garde SQL `FROM"table"` fermé** + littéraux blanchis +
  rejet tables système (sécu), lookup OR sur `alt_columns` + fallback SQL si vide, repli honnête sur cap de
  boucle, nudge 1×/run, `WITH RECURSIVE` plus faux-rejeté, `u` non muté en place. `run_parallel` (borné) =
  helper pour futurs tools ; résolution fuzzy **séquentielle** (sécurité instance). Verdict 3ᵉ passe = prêt prod.
- **À RECOLLER LES 2 Code Agents** (env 3.11) + upload zip (**77 entrées, `index-3FmqVbc1.js`**). Backend
  python-lib **inchangé** → **pas de redémarrage**. Détail → `sessions/2026-06-16.md` Run 5/5b/5c, **L071-L078**.

**Avant - 🔬 AUDIT AGENTS Run 4 (2026-06-16 soir) - ⏳ codé mais escalade/auto-escalade REMPLACÉES par L071
(échec DSS gpt-5.4-mini).** Restent valides de Run 4 : langue (L066, fin-de-prompt + word-boundary + token
autoritaire), messages live = vrais (L067 answer_delta), conscience écran (L069 backend gaté panneau ouvert),
timeline max-5 (L070). **Obsolètes (retirés Run 5)** : escalade pilotée L068 + auto-escalade L067.

**Avant - 🗣️ NARRATION LIVE + EVIDENCE LAZY + RENOMMAGE/NETTOYAGE - Run 3 (2026-06-16) - ✅ VALIDÉ DSS
(user : « super all good ça marche pas mal »).** Tout l'arc 2026-06-16 (Run 2 + Run 3, L063-L065) est
validé en DSS. Synthèse :
- **Narration live (L065)** : events `NARRATION` **transients** (live only, non persistés), rendus en
  flux par `MessageAgent` (nettoyés en vue terminale). **C'est le MODÈLE qui narre** (retour user) : on
  streame son préambule (`resp.text` du tour avec tool-calls → `state.preamble`), le prompt l'invite
  doucement (étape 0, tool-call obligatoire même tour → pas de narrate-and-stop) ; texte déterministe
  `_NARR` = **filet** si le modèle se tait ; phases internes du sous-agent restent déterministes. 0 appel
  LLM en plus, marche sur tout modèle. (Oui, possible en LangGraph.)
- **Evidence « Explore source data »** (fait par sous-agent **Opus**) : « 2 lignes » corrigé (collapse
  flex → conteneur scroll borné) ; **lazy/infinite loading** (cap 500) ; toutes colonnes + scroll H/V +
  en-tête collant ; **sélecteur multi-tables** (`/evidence/meta.sources` + param `table`).
- **Renommage** Code Agents : `OWIsMind_orchestrator.py` + `SalesDrive_revenue_expert.py`
  (`agent:bHrWLyOL`). **Nettoyage** : `orchestrator/` + `salesdrive/` (v2) et `*_agent.py` (v3 linéaire) +
  `test_orchestrator_v3` supprimés (git history), entrée registre `salesdrive_v2` retirée.
- **À RECOLLER LES 2 Code Agents** + upload zip (**77 entrées, `index-BM3sFZCq.js`**) + **REDÉMARRER
  backend**. Note multi-SQL : « Result used by the agent » = résultat du DERNIER SQL (le 1er SQL est une
  forme intermédiaire ; la capture L064 attache le résultat au dernier). Détail → `sessions/2026-06-16.md`
  Run 3, **L065** (+ L063-L064 Run 2).

**Avant - Run 2 (2026-06-16) = correction du Run 1 cassé - ⏳ CODÉ + ZIP, validé « beaucoup mieux ».** Le **Run 1 (nuit) a CASSÉ le comportement DSS** (Éco/Medium :
le modèle narrait puis s'arrêtait ; bridé ; lent ; graphique vide). Run 2 = retour à une **boucle
agentique simple qui marche** + correction des vrais bugs :
- **Narration-first + synthèse séparée + indice forcé = SUPPRIMÉS** (L063) : c'était la cause du
  narrate-and-stop sur petit modèle, du bridage et de la lenteur. Le modèle **appelle les outils puis
  rédige lui-même** la réponse dans la boucle (pas de passe en plus). Invite de rendu **légère** (le
  modèle choisit chart/colonnes). Prompt = ROUTE → **tout demander d'un coup / parallèle jamais série** →
  PRESENT. Filet auto-tableau conservé.
- **Modes = choix du modèle de boucle** (`pick_loop_llm`) : Éco/Medium=mini, High ou Medium+complexe=
  Sonnet (heuristique question). Token `⟦owi:mode=…⟧` (parse+strip, défense sur chaque message).
- **Graphique vide CORRIGÉ** (L064) : sous-agent `n_query` attache le résultat au **dernier** span SQL
  (`i==last_i`, pas `i==0`) ; Evidence `_load_sql_item` préfère le dernier item réussi **avec résultat**.
  **Perf** : headline LLM du sous-agent coupé (`SUBAGENT_LLM_HEADLINE=False`, ~29 s) ; ~44 s gagnés/req.
- **Revue Opus** : aucun bloqueur (narrate-and-stop structurellement retiré, flux correct).
- **À RECOLLER LES 2 Code Agents** (env 3.11) : `orchestrator_langgraph.py` ET
  `dataset_expert_langgraph.py` + upload zip (**77 entrées, `index-B015Ius_.js`**, Evidence) + **REDÉMARRER
  backend**. Sélecteur SQL multi-SQL = **différé** (capture corrigée règle déjà « not kept »). KPI +
  sélecteur de mode + Evidence SQL coloré (Run 1) **conservés** (frontend inchangé Run 2).
  Détail → `sessions/2026-06-16.md` Run 2, **L063-L064**. (Garder de Run 1 : show_kpi, modes, `sqlPretty`.)

**🧠 MODÈLE SÉMANTIQUE ALIGNÉ + SOUS-AGENT ASSISTIF (2026-06-15 Run 2) - ✅ NOUVEAU MODÈLE CRÉÉ
(Sonnet 4.6, Playground OK) ; ⏳ FIX SOUS-AGENT codé+157 tests, à RE-COLLER + re-tester DSS.** On a
créé un **nouveau** modèle sémantique aligné (l'ancien `2O2KcHw` intact) via script notebook
doc-strict (`dataiku-agents/tools/semantic_model/build_aligned_semantic_model.py` = create+index ;
`update_aligned_semantic_model.py` = modif en place instructions+golden queries, sans re-index ;
`README.md`). Corrigé : `Phase 'ACTUAL'→'ACTUALS'` (dont le filtre « Actual Revenue Only » qui
matchait **0 ligne**) ; glossaire `diamond_id` bidon retiré ; « roaming hub » retiré de Roaming
Sponsor ; hiérarchie offre **Product › Solution › SolutionLine › sirano_product** + **« never default
to sirano_product »** + transparence ; affichage client **nom+carrier_code, diamond_id dernier** ;
Parent_Group sobre ; Account_partner (revendeur indirect, Airbus→Maroc Telecom) ; **une table, jamais
de JOIN** ; 9 golden queries. **Décision clé (L058)** : le sous-agent **AIDE, ne DICTE pas** - il
n'épingle **plus** la colonne d'un terme d'offre **ambigu** (`AMBIGUOUS OFFER TERM` → Sonnet tranche) ;
les valeurs mono-colonne (noms clients) restent suggérées. **Pas de thinking au sous-agent** (raisonnement
dans Sonnet) ; gpt-5.4-mini garde orchestrateur+sous-agent, Sonnet **seulement** sur le modèle → pas
besoin de payer plus. **Bug AVANT fix** : `column_priority` (fallback `-distinct_count`) épinglait
`sirano_product='EVPL'` → **budget=0**. **À FAIRE : recoller `dataset_expert_langgraph.py` (Code Agent
`agent:AKQaQ0Am`, env 3.11) + re-tester EVPL via l'orchestrateur** (doit matcher le Playground).
Détail → `sessions/2026-06-15.md` Run 2, **L058-L059**.

**🤖 AGENTS LANGGRAPH + ARTEFACTS WEBAPP (2026-06-15) - ✅ VALIDÉ DSS (« tout fonctionne comme sur
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
`index-Bco4_3i5.js`** - upload + **REDÉMARRER backend** ; coller les 2 Code Agents en **env 3.11** ;
`reasoning=high` sur gpt-5.4-mini dans la connexion Mesh.
**📚 SKILL AGENTIQUE (2026-06-14) - ✅ CRÉÉ + VALIDÉ LOCAL.** Référence d'ingénierie réutilisable
`.claude/skills/agentique-python-dataiku/` (`SKILL.md` + 15 références, ~70k mots) sur LangChain /
LangGraph / Dataiku : choix d'abstraction, orchestration superviseur+sous-agents, design de tools,
mémoire/persistance, RAG, MCP, éval/gouvernance, anti-patterns. **Encart central = double chemin
Python 3.9/3.11** (L054). Construit par 3 workflows (recherche → fabrication → validation 6/6).
Claims DSS-réels marqués `UNVERIFIED` (import `DKUChatModel`, API semantic model) → à lever sur
l'instance. Corpus `docs/agentic-research/` gitignoré (provenance). Détail → `sessions/2026-06-14.md`, L053-L054.
**0★★) SYSTÈME D'AGENTS v3 « dataiku-agents/ » - ✅ VALIDÉ DSS (2026-06-12, « ça marche super
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
`get_raw()`/`save()`) - corriger `Phase='ACTUAL'`→`'ACTUALS'` (description + filtre « Actual
Revenue Only ») et le synonyme « roaming hub » sur Roaming Sponsor (produit différent), versionner
le JSON au repo, golden queries depuis le corpus.
**0★) ORCHESTRATEUR « EXPERT AUTHORITY » v2.4 (Run 5 2026-06-11) - ⏳ CODÉ + TESTÉ LOCAL (86 unittest),
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
**0) SUIVI TOKENS & COÛTS (Run 4 2026-06-11) - ⏳ CODÉ + TESTÉ LOCAL, NON validé DSS.** Ligne
`↑ in · ↓ out tokens · ~$coût` sous chaque réponse (tous users) ; stockage 3 niveaux : `webapp_chat_v5`
(source de vérité par échange, 4 colonnes usage) + `users` ALTER (cumul lifetime) + `webapp_usage_monthly_v1`
(PK `(user_id, mois)`, UPSERT incrémental → quota mensuel = 1 lecture par clé). `storage/usage.record_usage`
(2 incréments en 1 transaction, best-effort). **Limite 50 $/mois PAS implémentée** (juste le stockage prêt :
hook `/chat/start` avant `start_run`). Détail → L049 + `sessions/2026-06-11.md` Run 4. Zip prêt : **75
entrées, `index-WWBrb0uj.js`** - upload + **REDÉMARRER backend** (tables/colonnes auto au 1er usage ;
anciennes convs v4 invisibles, assumé).
**1) MISSION « Evidence Studio v2 TRUST LAYER » - 🟡 ÇA MARCHE (retour user) MAIS PAS ENCORE COMME
IL VEUT : ajustements NON PRÉCISÉS, à recueillir EN PREMIER (badge ? wording ? résultat capturé ?
drill ? layout ?) AVANT de toucher au code.**
**2) SALESDRIVE v2 (Code Agent) - ✅ DÉPLOYÉ ET VALIDÉ USER (« tout marche », 2026-06-11)** :
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
   Zip prêt : `ready-for-dataiku/owismind-upload.zip` (**75 entrées, `index-WWBrb0uj.js`** - Run 4 usage).
   ⚠️ **Backend modifié → REDÉMARRER le backend après upload.** Orchestrateur/SalesDrive modifiés →
   **recoller les 2 fichiers** dans leurs Code Agents DSS (repo = source de vérité, L047).
**Avant (Run 4 2026-06-10)** : layout droite + best-effort + chips ⏳ jamais validés DSS - le zip 74
entrées les INCLUT (tester ensemble). **Avant** : Evidence v1 ✅ DSS (L035-L037) ; V1+4 lots ✅ DSS ;
stockage = `webapp_chat_v5` (items generated_sql enrichis sql_id/step_index/agent_key/result + Run 4 :
4 colonnes usage input/output/total tokens + estimated_cost).

## 🧭 Dernière session - 2026-06-19 Run 4 (2e sous-agent "tickets d'incidents" + factory repo) → détail `sessions/2026-06-19.md` Run 4
- **✅ TESTÉ DSS « marche plutôt bien »** (à pofiner plus tard). 2e expert `TroubleTickets_year` à côté des revenus : `agents/TroubleTickets_expert.py` (copie moteur, corps byte-identique, CONFIG + textes offre neutralisés) + 1 entrée `CAPABILITIES["tickets_expert"]` + allowlist `lookup_search_columns`.
- **Modèle sémantique DÉDIÉ séparé** (décision user) ; scripts `update_tickets_semantic_model.py`/`dump_tickets_semantic_model.py`. **Recipes auto-IO + NA-safe** (fix int nullable `Duration_ticket_total`, **L097**) ; `value_catalog` dataset-adaptatif (générique `value`). **Factory** : `registry.json` + `DATASETS.md` + `PLAYBOOK_ADD_AGENT.md`. 283 tests, revue 4-dim = 0 finding (**L098**).
- **À finaliser (PLAYBOOK)** : override COUNT, modèle sémantique DSS, tool `tickets_semantic_query`, Code Agent + `agent_id` réel AVANT re-coll orchestrateur. Pas de zip (python-lib inchangé). **AUCUN commit de ma part avant `/log-session`.**

## Avant - 2026-06-19 Run 3 (auth gate + impersonation admin + plugin DEV/PROD) → détail `sessions/2026-06-19.md` Run 3
- **✅ VALIDÉ DSS** (« super tout fonctionne à merveille »). 3 features livrées via sous-agents + 3 revues sécu (0 crit/high/medium).
- **Auth gate** (`AuthGate.vue` + `session.authState` + `App.vue`, clés `authgate.*`) ; **impersonation admin** read-only & admin-only (`security/impersonation.py` + `features/admin-impersonate/`, header `X-OWI-Impersonate`, FENCÉ/supprimable, **L095**) qui REMPLACE l'ancienne "revue de convs" SUPPRIMÉE (**L096**) ; **plugin DEV** `owismind_dev` (source unique, `tools/build_dev_plugin.py` + skill `/package-plugin-dev`, **L094**), **prod intacte**, tables create-if-not-exist inchangées.
- **✅ PROMU EN PROD + DÉPLOYÉ** (user « super tout marche ») : zip prod `owismind-upload.zip` (id `owismind`, entry **`index-CApWkAm7.js`**, 80 entrées) uploadé + backend redémarré. Commits `f5b2976` (session) + `f967347` (build prod). Impersonation = **temporaire** (à retirer plus tard, blocs FENCÉS).

## Avant - 2026-06-19 Run 2 (doc ultra-complète + plateforme web "parcours") → détail `sessions/2026-06-19.md` Run 2
- **Doc `project-documentation/` corrigée + complétée** (workflow 23 agents Sonnet, ownership/fichier + vérif
  adversariale) : périmés corrigés (budget = **codé** ; doc = **anglais**), 3 features 2026-06-18 ajoutées,
  **+5 fichiers** (user-guide 05/06, ADR 0013/0014/0015), **61 .md** propres, 21 routes, build->zip détaillé.
- **Plateforme `project-documentation/site/`** (workflow 10 agents Sonnet) = **HTML/CSS offline** en **parcours**
  descendant (8 pages, niveau 0 -> 7), chrome JS, ~30 **diagrammes SVG**, **vrai logo**, thème persistant.
  **QA Playwright réel** OK (2 thèmes, diagrammes denses aérés). Ouvrir `site/index.html` au double-clic.
- **Bonus + leçon** : 12 em-dash corrigés dans `compute_available_connections.py` ; **L093** : `grep -P` faux
  négatif sur BSD grep (Mac) -> audit em-dash **en Python**. Em-dash **préexistants** hors livrable signalés à l'user.

## Avant - 2026-06-19 Run 1 (refonte UI "maquette Orange" multi-agents + charte durable) → détail `sessions/2026-06-19.md`
- **6 agents Sonnet en parallèle** (ownership par fichier, brief charte commun) ont restylé les pages "comme la
  maquette" fournie par l'user : `foundation` (chrome + primitives, `--fw-heavy:800`), `shell`, `settings`,
  `admin` (+ modale profil), `agents`, `modepicker`. Carré/aplat/orange rare ; `Button`/`Modal` partagés -> chat hérite.
- **Logo (retour user)** : `shell` l'avait reconstruit en carré CSS -> **rebranché la VRAIE image `orange-logo.png`**
  (rail + sidebar). **Charte gravée durablement** : `docs/cadrage/CHARTE_ORANGE_UI.md` + règle #10 (`CLAUDE.md` x2)
  + mémoire `orange-charter-styling.md` (la maquette HTML va être supprimée par l'user).
- **Vérifs** : périmètre 12 fichiers, 0 tiret/color-mix/blur/hex en dur, 0 clé i18n manquante, build OK, png bundlé,
  zip propre **79 entrées `index-BHeG2NRY.js`**. **NON validé DSS.** À faire : **upload zip** (frontend only ->
  **pas de redémarrage backend**, pas de recoll d'agent). Voir **L092**.

## Avant - 2026-06-18 (refonte UI charté Orange + fiches d'agent admin) → détail `sessions/2026-06-18-design-ui.md`
- **Design only** (frontend + 1 ajout backend). **Descriptions d'agent hardcodées BANNIES** (`agentMeta.js`
  supprimé) -> rédigées par l'admin (modale `AdminView`), validées/bornées serveur (`validate_agent_meta`,
  pur, ne lève jamais, whitelist icônes), stockées **dans le JSON `enabled_agents` (pas de nouvelle table)**,
  exposées via `/agents` sans fuite `agent_id`/projet.
- **Sidebar repliée = RAIL** (`+`, Agents, aide `?` au-dessus du profil) ; **`AgentsView`** (recherche +
  fiche éditoriale) + **`AdminView`** (sélection + formulaire) refondus charté ; **Settings -> "My account"** ;
  **anglais par défaut**. Petites animations (`u-rise`), `prefers-reduced-motion` respecté.
- **2 revues adversariales** (Workflow) : sécurité finale **CLEAN** (0 fuite, XSS sûr, instance OK) ; LOW/medium
  corrigés. **2 retours user -> reverts** d'ajouts non demandés (orange en trop, focus-ring global, logo
  centré, glows) + **bouton de dépli header restauré**. **Leçon L091 (discipline de marque)**.
- **Vérifs** : build OK, **124** frontend + **438** backend, zip propre (**79 entrées, `index-Bd4XhFvS.js`**),
  0 tiret, 0 dégradé/blur/glow ajouté. **NON validé DSS.** À faire : upload zip + **redémarrer backend** +
  remplir les fiches (Administration > Agents). Charte Orange officielle de l'user **à coller dans `CLAUDE.md`** (proposé).

## Avant - 2026-06-18 Run 4 (`dataiku-agents/` doc reflet-DSS + simplify recettes/tool + debug Evidence PROD) → détail `sessions/2026-06-18.md`
- **Doc `dataiku-agents/` réécrite reflet-DSS** (audit 6 lecteurs + revue adversariale 3) : `CLAUDE.md` auto-suffisant + READMEs + **`MODEL.md`** + **`dump_semantic_model.py`** ; dérives corrigées (Value_Catalog **utilisé**, attribute_lookup **branché** built-in, resolve_filter_value **à supprimer**, tool sémantique **linéaire Sonnet**, intent `lookup` fantôme retiré).
- **`/simplify`** profiler + 2 recettes + tool : en-têtes resserrés, `ENRICH_LLM_ID`->**`claude-opus-4-7`**, micro-optims ; **267 tests verts, 0 tiret**. **GOTCHA pandas lazy** (env test sans pandas, L089).
- **Evidence "dégradé" PROD RÉSOLU** : le **modèle sémantique** PROD pointait une table non remappée (`_PROD_V1` droppé par le script de migration) ; c'est le modèle (pas le code agent) qui décide la table, le backend matche le FROM vs les datasets du projet webapp (L090). 2 scripts versés : `migrate_semantic_model_to_project.py` + `remap_semantic_model.py`.

## Avant - 2026-06-18 Run 2/3 (`attribute_lookup` branché ORCHESTRATEUR + durci + multi-table ; doc projet parallèle) → détail `sessions/2026-06-18.md`
- **Conseil multi-agents (Workflow)** = **4/4 brancher dans l'ORCHESTRATEUR** (built-in, zéro contrat `KNOWN_*`, **sous-agent INCHANGÉ**). Câblé : spec `build_tool_specs` + dispatch inline `node_tools` + provenance via subspan `semantic-model-query`. **Multi-table** : domaine logique -> table via registre (`lookup_domains`).
- **SQL lisible** : **1 seul `ILIKE`** sur `concat_ws` (au lieu de 18 `OR`), accents par `translate` à la requête (user REFUSE de toucher la base prod -> pas d'`unaccent` ; `accent_fold_sql`). Durci : flags `rows_capped`/`multi_column`, garde needle court, cache TTL, garde found-vide->not_found. **Value_Catalog + suggestions GARDÉS** (décision user, après suppression annulée). **267 tests verts**, revue adversariale = 0 crit/0 high.
- **RUN TEST DSS validé** (lookup rapide ~14s + descente expert OK). **À faire DSS** : MAJ tool + recoller orchestrateur + **supprimer le vieux `Drive_Revenues_resolve_filter_value`**. **Leçon process** : conseiller avant d'exécuter une suppression (L087). Voir **L087**.

## Avant - 2026-06-17 (nettoyage repo + doc `dataiku-agents/`) → détail `sessions/2026-06-17.md`
- **Vestiges v2 supprimés** (`orchestrator/`+`salesdrive/`) ; `cadrage/`+`agentic-research/` -> `docs/` (refs à jour partout, logs datés intacts).
- **`dataiku-agents/` = mini-repo documenté** : README maître + CLAUDE.md réécrits + 3 sous-READMEs (`agents/`/`recipes/`/`tools/`) + recette `Value_Catalog` versée (STATUS roadmap). **Archi v3 clarifiée** : inline `value_index` + tools.
- `flash-light`->`flash-lite` (2 agents, preuve = code déployé). **227 tests** verts ; revue doc-vs-code (5 agents) = 2 LOW corrigées, 0 lien cassé. **Pas de DSS** (nettoyage/doc only). Voir **L085**.

## Avant - 2026-06-17 (Run 7/7b/7c = polish UI chat) ✅ VALIDÉ DSS (« super tout fonctionne à merveille ») → détail `sessions/2026-06-17.md`
- **Pop-up de mode (7c)** : clic-pour-sélectionner + footer Annuler/Valider (pattern DSS, plus de hover →
  fini la VIBRATION) + `min-height` détail ; style charte Orange 80/20 (gris + barre orange, dots sombres).
- **Ban `—`/`–` (7b, règle #9)** partout + écran d'agent rempli (`resolveAgentMeta` repli substring).
- **Largeur texte = zone de prompt (~90%)** : token partagé `--chat-col`/`--chat-col-max` sur `.conv-inner`
  (760→), `.prompt-wrap` (920→) et `.empty` ; écran vide = prompt plafonné 760px.
- **Mode picker** : Éco **vert** (feu tricolore vert/orange/rouge), pop-up dé-IA (sliders/coche/wallet, copie
  réécrite FR/EN, clé `mode.current` retirée) ; **tokens `--success-soft`/`--danger-soft`** clair+sombre (fix
  dark-mode invisible). **Guidage « soyez précis »** (placeholder + `empty.tip`). **AgentPicker** 240→320px ;
  **micro à droite** ; **`Modal`** close `aria-label`→`t('x.close')`.
- **Titre conversation** : nettoyage 1 ligne (`regexp_replace`/`BTRIM`) + `CONV_TITLE_MAXLEN` 140→56, **dérivé**
  (pas de colonne DB ; rétroactif, sans migration ; colonne DB différée à la feature titre-IA).
- **Vérifs** : **116 frontend + 385 backend** + build + zip (**77 entrées, `index-CrvKHGTt.js`**) ; **2 revues
  adversariales** (R1 → 4 défauts tous corrigés dont dark-mode invisible ; R2 qualité+sécurité = **0 défaut /
  0 sécurité**). Agents NON touchés.
- **À faire DSS** : **upload zip** + ⚠️ **redémarrer backend** (python-lib titres). Pas de recoll d'agents.

## Avant - 2026-06-17 (Run 6) → détail `sessions/2026-06-17.md`, leçons **L080-L082**
- **Modèles par mode revus (L080)** : eco=Gemini 3.1 Flash-Lite (défaut), medium=Gemini 3.5 Flash, high=Sonnet,
  **gpt-5.4-mini supprimé** ; front défaut Éco + badge Recommandé sur Éco. **Argent €** dérivé du nom de colonne
  `amount_eur` (`metric_unit`, **pas de config profil**). **Transparence** : sous-agent préfixe `[Périmètre]`,
  orchestrateur l'impose + `€` + analyse.
- **Désambiguïsation (L081)** : `defer_multicolumn_offer_terms` - terme d'offre ambigu ≥2 colonnes **déféré**
  à Sonnet + divulgation (plus de clarification) ; mono-colonne demande encore. P3 (par nombre de colonnes).
- **Bloc « Sources » retiré** du chat. **Source Evidence cliquable (L082)** : `source_url` dans le registre
  orchestrateur (vide), propagé additif via items SQL → `service.py` `meta.source.url` → `EvidenceSources.vue`
  `<a target="_blank">`. **Nettoyage prod** des commentaires agents (zéro empreinte IA).
- **Vérifs** : **227 agents + 384 backend + 116 frontend** + build (`index-8spQsYzC.js`) + zip (77 entrées) ;
  revue adversariale (26 agents) = **0 bug**. **Backend python-lib CHANGÉ → redémarrer.**
- **À faire DSS** : recoller les 2 Code Agents ; **vérifier `GEMINI_FLASH_LITE_ID`** ; **remplir `source_url`** ;
  upload zip + **redémarrer backend**. **NON validé DSS.**

## Avant - 2026-06-16 (Run 5/5b/5c) → détail `sessions/2026-06-16.md`, leçons **L071-L078**
- **Run 5/5b** : model-agnostic (fin escalade, 1 modèle/mode eco=mini/medium=Gemini/high=Sonnet propagé au
  sous-agent, narration off en eco, Dataset Lookup + intent `lookup` + schéma live, stop « Stopping… »,
  popup de mode coût/enveloppe 50 €). **Run 5c = 3 AUDITS À L'AVEUGLE** (sous-agent « architecte » + skill
  agentique, copies isolées /tmp, zéro contexte) → durci à chaque passe : P1 (2 Critical) → P2 (1 Critical
  = **bypass garde SQL `FROM"table"`** que j'avais laissé, fermé) → **P3 = 0 Critical/0 High, verdict
  « production-ready »**. Corrigés (L076-L078) : caches stables, appariement tool↔output, garde SQL
  (espace-less/littéraux/tables système/`WITH RECURSIVE`), lookup OR `alt_columns`+fallback, cap de boucle,
  nudge 1×/run, `original_intent`, `_cap_cell` NaN/inf, `u` non muté en place. `run_parallel` borné = helper
  futurs tools ; résolution fuzzy **séquentielle** (sécu instance). **217 tests agents + 116 frontend verts**.
  Zip **inchangé** depuis 5b → recoller les 2 Code Agents, pas de rebuild. NON faits (assumés) : rename
  `MyLLM` (contrat DSS), découpe `n_query` (différée), sonde id modèle (polish). **NON validé DSS.**
- **Déclencheur** : test DSS du Run 4 = gpt-5.4-mini **escalade systématiquement** (+ message hardcodé) ou
  **narre puis s'arrête**. User : abandonner gpt-5.4-mini → Gemini 2.5 Flash + Sonnet, **stop les hacks
  mono-modèle**, archi qui marche **même sur petits modèles**.
- **Chantiers (L071-L075)** : escalade **supprimée** (1 modèle/mode) ; **eco=gpt-5.4-mini gardé**, medium=Gemini,
  high=Sonnet ; narration « parle pendant le tool-call » **séparée et OFF en eco** ; **mode propagé au sous-agent**
  (high=Sonnet partout) ; **Dataset Lookup** `9FEzVZk` + intent `lookup` + schéma live (L072) ; **stop = attente +
  « Stopping… »** clignotant (L075, revert de l'optimiste) ; **popup de mode** (coût + enveloppe 50 €) ;
  hiérarchie timeline (steps `SUB_AGENT_*` indentés, L074).
- **Vérifs** : **199 tests agents + 116 frontend** verts + build Vite + zip (**77 entrées, `index-3FmqVbc1.js`**).
  Backend python-lib **inchangé**.
- **À faire DSS** : **VÉRIFIER l'id Gemini Flash** (orchestrateur + sous-agent) ; **recoller LES 2 Code Agents**
  (env 3.11) ; **upload zip** (pas de redémarrage backend, python-lib inchangé). **NON validé DSS**.

## Avant - 2026-06-15 (Run 2) → détail `sessions/2026-06-15.md`, leçons **L058-L059**
- **Modèle sémantique aligné (nouveau modèle, Sonnet 4.6) + sous-agent ASSISTIF** : le sous-agent
  n'épingle plus la colonne d'un terme d'offre **ambigu** (`AMBIGUOUS OFFER TERM` → Sonnet tranche) ;
  question user = source de vérité, indices = aide non contraignante. Codé + 157 tests, **à recoller +
  re-tester DSS** (L058). Pas de thinking au sous-agent ; pas besoin de payer plus.
- **API modèle sémantique scriptable** : `create_semantic_model` + workflow versions, **update en place
  sans re-index**, jamais instancier les classes ; **repointer le tool `v4oqA6R`** sur le nouveau modèle (L059).
- **Bug réglé** : pin déterministe `sirano_product='EVPL'` → **budget=0** (cause `column_priority`
  fallback `-distinct_count` ; les lignes BUDGET n'ont pas de sirano_product).

## Avant - 2026-06-15 (Run 1) → leçons **L055-L057**
- **Agents en LangGraph (orchestrateur + sous-agent) ✅ VALIDÉ DSS** : nœuds **sync** +
  `get_stream_writer` + `graph.stream(custom)` + appels **natifs Mesh** ; le log DSS prouve que
  LangGraph tourne sur le Code Agent 3.11 (lève les 2 `UNVERIFIED` de la revue) (L055).
- **Bug clé corrigé** : reasoning=high + extraction JSON sans `with_json_output` → ~15 s puis parse
  cassé → erreur interne. Fix = **forcer le JSON sur UNDERSTAND**, garder le reasoning pour
  routing/headline (L056). Fallback UNDERSTAND : claude-sonnet-4-6.
- **Artefacts webapp** : tool `show_chart`/`show_table` → event `ARTIFACT` → `webapp_artifacts_v1` →
  `/evidence/meta` → onglets + **Chart.js** (payload Python blindé `chart_payload.py`) ; l'agent
  commente (L057). Build+zip refaits (Chart.js bundlé) ; revue sécurité Opus sans bloqueur.

## Avant - 2026-06-14 → détail `sessions/2026-06-14.md`, leçons **L053-L054**
- **Skill d'agentique créé** : `.claude/skills/agentique-python-dataiku/` (`SKILL.md` + 15 références)
  via 3 workflows (recherche 24 agents → corpus 23 briefs `docs/agentic-research/` ; fabrication 36 agents
  draft→revue→fix ; validation 13 agents **6/6, 0 piège**). Réconciliation corpus + source ChatGPT.
- **Double chemin Python 3.9/3.11** (correction autorité user, L054) = encart central ; vérité des versions
  (`create_agent` pas `create_react_agent`, `recursion_limit=25`, `astream_events` v2…) intégrée.
- 5 cross-références frères cassées (noms ChatGPT vs slugs réels) → corrigées + vérifiées (L053).
  ⏳ Skill = **référence**, pas du code déployé ; claims DSS marqués `UNVERIFIED`.

## Avant - 2026-06-12 (2 runs) → détail `sessions/2026-06-12.md`, leçons **L051-L052**
- **Run 1 (nuit)** : construction complète du système v3 (2 recettes Flow, Dataset Expert, orchestrateur
  parallèle, README) après recherche 6 agents (SOTA NL2SQL, semantic model 14.4 scriptable, corpus).
- **Run 2 (jour)** : validation DSS avec l'user + bascule moteur HYBRIDE semantic-tool (A/B) ; fixes
  réels : LEFT(date) cast-safe, extraction mode-Agent dernier-gagnant, énumérations IN/OR. ✅ VALIDÉ.

## Avant - 2026-06-11 (5 runs) → détail `sessions/2026-06-11.md`, leçons **L044-L050**
- **Run 1-2** : trust layer v2 déployé (revue 26 agents, 17/17 corrigés) ; nettoyage repo + git init +
  knowledge graph 2 494 nœuds + fraîcheur auto (L044-L046).
- **Run 3 - SalesDrive v2** : Code Agent complet + orchestrateur v2.3 (AGENT_RESULT structuré, skip
  Sources sur clarification, `pass_context`) ; incident boucle IPL diagnostiqué sur traces CSV réelles
  → fix générique (L048) ; capture Evidence déterministe via retour de tool (L047). 55+62 unittest · validé DSS.
- **Run 4 - Suivi tokens & coûts** : `chat_v4`→`chat_v5` (+4 colonnes usage), `users` ALTER cumul,
  `webapp_usage_monthly_v1` (quota mensuel O(1)), `storage/usage.py`, ligne front `MessageAgent`. 322
  unittest + 102 node:test + Vite OK ; **non validé DSS** (L049).
- **Run 5 - Orchestrateur « Expert Authority » v2.4** : pare-feu d'honnêteté (jamais de fait métier ;
  router pas nier ; `CAPABILITY_GAP`/`OUT_OF_SCOPE` déterministes ; intent `CONCEPT`), registre=manifeste
  + `BUSINESS_DOMAINS`, manifeste revenus pleine-vérité + test anti-dérive, bascule registre sur v2
  `agent:MODpGFcC`. 86 unittest verts ; **non validé DSS** (routing LLM) (L050). Feedback : **plans
  verbeux interdits** (exécuter direct).

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
0🔐. **SESSION 2026-06-19 Run 3 = ✅ VALIDÉ DSS** (auth gate + impersonation admin + plugin DEV `owismind_dev`).
   **Workflow DEV->PROD en place** : promotion prod = `/build-plugin` + `/package-plugin` (prod) + upload quand le
   DEV est bon (idem agents : valider en DEV, puis promouvoir). **Impersonation = feature TEMPORAIRE** : suppression
   future = retirer `security/impersonation.py` + `features/admin-impersonate/` + les blocs FENCÉS (routes.py /
   backend.js / session.js / chat.js / ChatView.vue / AppLayout.vue / AdminView.vue) + clés `impersonate.*`. Détail
   -> `sessions/2026-06-19.md` Run 3, **L094-L096**.
0📚NEW. **DOC + PLATEFORME WEB (2026-06-19 Run 2) - ✅ livrées local.** (a) Ouvrir
   `project-documentation/site/index.html` (double-clic) pour parcourir la doc en parcours (offline, charté Orange).
   (b) **Décider du sort des em-dash PRÉEXISTANTS hors livrable** (NON introduits cette session) : surtout
   `Plugin/owismind/frontend/test/*.test.js` (13), `docs/cadrage/CHARTE_ORANGE_UI.md`, `docs/scaling/PLAN_WEBAPP.md`,
   `memory/*` (souvent citations de la règle), `.claude/skills/*` (exclus ADR-0012), `docs/agentic-research/*`
   (gitignoré), `style-reference/*` (à supprimer). (c) **Remplacer `grep -P` par Python** (ou `ggrep`) dans le
   protocole de vérif règle #9 (L093). `project-documentation/.workdir/` = scratch supprimable. Aucune incidence DSS.
0🎨NEW. **DÉPLOYER + VALIDER la refonte UI "maquette Orange" (2026-06-19)** : **upload zip** (**79 entrées,
   `index-BHeG2NRY.js`**, **vrai logo png bundlé**). ⚠️ **Ce zip embarque AUSSI le python-lib non encore
   déployé des sessions 2026-06-18 (fiches d'agent `validate_agent_meta`/`/agents` + budget `storage/budget.py`).
   Donc : si ces backends ne sont pas déjà live sur l'instance -> REDÉMARRER le backend après upload.** Pas de
   recoll d'agent (logique d'agents inchangée). Smoke-tests : vrai logo (rail + sidebar), pages carrées chartées,
   thème clair/sombre, modales à plat, fiche d'agent (Administration > Agents > Edit profile). Voir **L092**.
0🎨. **DÉPLOYER + VALIDER la refonte UI charté + fiches d'agent (2026-06-18, design)** [intégré dans le zip ci-dessus] : (1) **upload zip**
   (zip courant = **`index-BHeG2NRY.js`**) ; (2) ⚠️ **REDÉMARRER le backend** (python-lib changé :
   `validation.py` `validate_agent_meta` + `routes.py` `/agents`+`/admin/agents`) ; (3) **Administration >
   Agents** : « Edit profile » sur l'orchestrateur et **remplir la fiche** (accroche/desc/capacités/outils/
   icône/badge) - tant qu'elle est vide -> carte « profile to complete » (voulu, plus aucun hardcode).
   Pas de recoll d'agent (logique inchangée). Smoke-tests : fiche s'affiche dans la bibliothèque + carte
   honnête si vide ; rail (`+`/aide/profil) + **bouton de dépli header** OK ; zéro contour orange sur la
   zone de saisie. **Optionnel** : coller la **charte Orange** (fournie par l'user) dans `CLAUDE.md` +
   note mémoire. Voir **L091** + `sessions/2026-06-18-design-ui.md`.
0🔎. **PROCHAINE SESSION (demandée user, 2026-06-18) : WORKFLOW MULTI-AGENTS pour finir l'histoire du
   resolver.** L'user = PDG technique senior (dev + AI engineering) + conseillers experts, qui débattent
   et tranchent : (a) la **meilleure conception** du tool `attribute_lookup`
   (`dataiku-agents/tools/attribute_lookup_tool.py`, déjà construit : recherche full-text `ILIKE`, sortie
   `found_in` + attributs optionnels, fallback alias) ; (b) le **meilleur point de branchement** :
   dans le **sous-agent** (`SalesDrive_revenue_expert`, en amont du semantic model pour les questions
   simples) OU dans l'**orchestrateur** (`OWIsMind_orchestrator`, comme tool/route directe avant de
   déléguer). **Objectif : justesse d'abord, rapidité ensuite**, surtout les questions simples de
   recherche de valeurs. Puis créer le Custom Python tool en DSS, brancher, **recoller LES 2 agents**
   (env 3.11), re-tester. État : `dataset_lookup` supprimé partout, 242 tests verts, tool validé RUN
   TEST mais NON branché (questions simples repassent par le semantic lent en attendant). Voir **L086**.
   Note archi (rappel) : grounding = SQL inline sur `value_index` (`_resolve_terms`) ; vrai tool DSS
   restant = `revenue_semantic_query` (v4oqA6R). `resolve_filter_value`/`dataset_sql_query` = labels
   d'events, pas des tools.
0🧭. **VALIDER EN DSS le Run 6 (L080-L082)** - (0) **VÉRIFIER `GEMINI_FLASH_LITE_ID`** (best-effort
   `…/gemini-3.1-flash-light` ; ✅ FAIT cette session : `flash-lite` confirmé du code déployé collé par l'user, corrigé dans les 2 fichiers) ; (1) **recoller LES 2 Code
   Agents** (env 3.11) ; (2) **remplir `source_url`** (capability `revenue_expert`, orchestrateur) avec le lien
   Dataiku du dataset si le lien cliquable est voulu ; (3) **upload zip** (**77 entrées, `index-8spQsYzC.js`**)
   + ⚠️ **REDÉMARRER le backend** (python-lib changé : Evidence/source). Smoke-tests : (a) « revenu réel du compte
   X » en **Éco (Flash-Lite)** → réponse en **€** + ligne **périmètre** restituée (scénario ACTUALS par défaut,
   toutes périodes / aucun filtre d'année) ; (b) « budget 2026 Roaming Hub … » → **ne demande PAS**, Sonnet
   résout via la hiérarchie + **divulgue** (pas de sirano par défaut) ; (c) **source Evidence cliquable** (ouvre
   le dataset) une fois `source_url` rempli ; (d) Medium/High inchangés. Si l'id Flash-Lite est faux → Éco/défaut
   ne répond pas. Différé : mapping URL **par-dataset** multi-source (aujourd'hui mono-source seulement).
0🧭5. **VALIDÉ ? Run 5 (L071-L078)** - model-agnostic, Dataset Lookup, stop « Stopping… », popup mode, timeline
   indentée : codé+audité, à confirmer sur l'instance en même temps que Run 6 (mêmes Code Agents).
0🗣️. **✅ FAIT & VALIDÉ DSS (2026-06-16 Run 3)** - narration live (modèle), Evidence lazy, modes, renommage,
   nettoyage. **Process permanent** : à chaque modif repo des agents, **recoller LES 2 Code Agents** (env
   3.11) - **OWIsMind_orchestrator** + **SalesDrive_revenue_expert** (`agent:bHrWLyOL`) - et si le backend
   change, uploader le zip + redémarrer. **Reste optionnel (non urgent)** : sélecteur SQL multi-résultats
   dans Evidence ; durcir l'invite de narration sur le mini (ou mini-appel dédié) s'il narre trop peu.
0★★. **FINALISER le fix sous-agent assistif (L058)** : recoller `dataset_expert_langgraph.py` dans le
   Code Agent `agent:AKQaQ0Am` (env 3.11), puis **re-tester EVPL via l'orchestrateur** (« revenus YTD
   EVPL, actuals vs budget ») → doit matcher le Playground (Product, budget ≠ 0, note de transparence).
   (Optionnel) lancer `update_aligned_semantic_model.py` pour le renfort « never default sirano_product ».
   Consigner l'id du nouveau modèle dans `PROJECT_STATE.md`. Smoke-tests : « IP » (SolutionLine), top
   clients (nom+carrier, diamond_id dernier), indirects/par partenaire, nom client mal orthographié.
0★. **Agents LangGraph + artefacts ✅ FAITS & validés DSS** (L055-L057) - surveiller le fan-out
   parallèle réel au 2ᵉ sous-agent ; affiner le prompt orchestrateur s'il recopie un tableau au lieu
   d'appeler `show_table` ; envisager d'autres types de graph (style) au fil de l'usage.
0skill. **Skill agentique** : lever les `UNVERIFIED` en confirmant sur l'instance (import `DKUChatModel` vs
   `as_langchain_chat_model()`, API `project.get_semantic_model`, ids de modèles non-Anthropic) ; promotion
   en global (`~/.claude/skills/`) si réutilisation cross-projets souhaitée (simple copie).
0. **SESSION SEMANTIC MODEL - ✅ FAIT (2026-06-15 Run 2, L058-L059)** : nouveau modèle aligné créé
   (l'ancien `2O2KcHw` intact), Phase 'ACTUAL'→'ACTUALS' (dont filtre « Actual Revenue Only »),
   glossaire `diamond_id` bidon + synonyme « roaming hub » retirés, hiérarchie offre + transparence,
   affichage nom+carrier (diamond_id discret), Account_partner, 9 golden queries, instructions
   versionnées au repo (`dataiku-agents/tools/semantic_model/`). Reste = 0★★ (recoller le sous-agent + valider).
0bis. Poursuivre les smoke tests README §5 au fil de l'usage (part du total, YoY, trend, ellipses,
   « IPL » ambigu) ; toute divergence → profil/overrides/prompts, jamais de valeur en dur (P3).
0ter. **Agent tickets** (2 recettes + 1 Code Agent + 1 entrée registre) → débloque le 360 parallèle.
1. **RECUEILLIR LES AJUSTEMENTS du user sur le trust layer** : « marche bien mais pas
   encore comme je veux » - faire préciser AVANT toute modification.
2. **SalesDrive v2 - consolidation** : tester un cas de vraie ambiguïté de valeur (ex. « IPL + ») et
   un plan multi-étapes (agent+tool) ; quand confiance OK → retirer l'entrée visual `salesdrive` du
   registre ; supprimer le CSV de traces local (`salesdrive/webapp_devtest-…csv`, hors repo).
3. Re-tester en DSS ce qui ne l'a jamais été : L040 (bouton New conversation) / L041 (chrono étapes).
4. **Evidence v3 (différé)** : restriction admin des datasets, keyset pagination, drill multi-requêtes,
   fraîcheur des sources ; fallback LLM seulement sur cas réel.
5. **2ᵉ task mentionnée par l'user le 2026-06-09** - toujours à clarifier.
