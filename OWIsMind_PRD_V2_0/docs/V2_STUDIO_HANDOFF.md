# Passation WP-B : refonte Studio (2026-10-15)

Etat : le brief en 7 points du lead est implémenté, rien n'est à moitié édité. Tests 486/486,
build Vite OK (scratchpad), zéro tiret cadratin. NON vu dans un navigateur (aucun navigateur sur la
machine) : vérifié par rendu SSR de AppLayout + vrais stores contre le simulateur. Rien n'est commité.

## Fichiers changés dans ce tour (frontend `plugin/owismind/frontend/src`)
- `styles/tokens.css` : nouveau token `--paper` (cartes flottantes : blanc ; sombre #0f0f0f). `--canvas` existait déjà.
- `stores/ui.js` : les clamps evidenceW et sourcesW autorisent un chat de 300 px (`innerWidth - 360`).
- `composables/teaserModel.js` : `studioWidth()` (80 % à côté du rail de 60 px, chat de 300 px min), `nextPlanOpen()`, `previewTable()`, `teaserState()`, `isNarrow()` (900 px).
- `composables/workspaceModel.js` : + `agentLabelKey()`, `resultLabel()`, `dataFocus()`, `filterParts()`.
- `stores/workspace.js` :
  - onglets `['board','data']` uniquement, `board` par défaut ;
  - ouverture auto au premier `widget.add` ;
  - `planOpen` + `planEvent()` ; `loadForExchange()` (chargement silencieux) ;
  - `openData()`, `clearDataFocus()`, `unseenExchangeId`.
- `stores/chat.js` : à l'entrée dans une conversation, chargement silencieux du workspace de la dernière réponse (aucun panneau imposé) ; `planEvent('restore')` sur ouverture/nouvelle conversation.
- `components/shell/AppLayout.vue` :
  - toile unique (sans filets entre colonnes, `--bg` de la sidebar et du main = toile, `.prompt` en paper) ;
  - `.right-host` = carte flottante à 12 px des bords ;
  - largeur 80 % appliquée à chaque ouverture du Studio et aux ouvertures depuis la balise ;
  - < 900 px : `.sheet` plein écran ;
  - colonne balise de 320 px.
- `components/chat/PlanCard.vue` (NOUVEAU) : plan repliable au-dessus du prompt, valeurs du design ; les notes s'ouvrent sous leur étape. Inséré dans `views/ChatView.vue` juste avant `<PromptBar>`.
- `components/workspace/WorkspacePanel.vue` : en-tête « Studio » + statut, onglets Tableau de bord / Données (barre de plan supprimée).
- `components/workspace/WidgetCard.vue` : titre + commentaire + contenu + UN lien « D'où viennent ces données ? ».
- `components/workspace/ProvenanceDrawer.vue` : provenance en langage clair (expert, conditions en phrases, nombre de lignes, « Voir les lignes ») ; outil / durée / id / tâche / SQL dans le `<details>` « Détails techniques ».
- `components/workspace/WorkspaceTeaser.vue` : la balise (markup de la maquette), style carte flottante.
- `components/workspace/DataFocus.vue` : identifiants masqués.
- `components/chat/WorkspaceSummary.vue` : un seul bouton « Ouvrir le Studio ».
- `components/evidence/EvidenceSqlPicker.vue` : libellés en clair (titre du widget, sinon étape, sinon « Résultat n ») + nombre de lignes.
- `i18n/extra.js` : textes Studio, `ws.plan.*`, `ws.prov.where/by/conditions/none/see_rows/tech/id`, `ws.agent.*`, `ev.sqlpick.*`.
- SUPPRIMÉS : `components/workspace/PlanList.vue`, `JournalList.vue`.
- Tests : `test/teaserModel.test.js` (studioWidth, nextPlanOpen, previewTable, teaser), `test/workspaceModel.test.js` (dataFocus, filterParts, agentLabelKey, resultLabel, fixtures), `test/sqlChoices.test.js`, `test/widgetData.test.js`.
- `docs/CHARTE_V2_UI.md` section 4 (règles Studio).

## Reste à faire / à vérifier (brief en 7 points)
- Validation VISUELLE par l'utilisateur (clair ET sombre). Points à surveiller :
  - PromptBar à 300 px (pickers Agent / Mode) ;
  - le contraste de `--paper` en sombre ;
  - les composants V1.3 qui posent leur propre fond `--bg` dans le chat (ils prennent désormais la couleur de la toile).
- Point 6 incomplet : l'onglet Données embarque encore l'Evidence V1.3, avec ses propres termes techniques. Restent visibles :
  - le pied « Requête SQL » (replié) ;
  - les noms de colonnes dans les phrases `ev.exp.*` (« Filtrer : Year = 2026 ») ;
  - les badges de confiance.
  À simplifier si l'utilisateur le demande.
- Libellés d'experts : `agentLabelKey` ne connaît que revenus / tickets (mapping par sous-chaîne) ; un nouveau domaine tombe sur « un expert ».
- Point 3 : la largeur 80 % est posée à chaque passage `workspace.open` false -> true (watch dans AppLayout). Un redimensionnement manuel reste actif jusqu'à la prochaine ouverture.

## Pièges
- Lancer le simulateur depuis la racine du repo :
  `OWIsMind_PRD_V2_0/plugin/owismind/frontend/node_modules/.bin/vite --config OWIsMind_PRD_V2_0/dev-harness/vite.config.mjs`
  (port 5199). Le mock (`dev-harness/mock/*.mjs`) n'est chargé qu'au démarrage : le RELANCER après toute modification du mock (le front se recharge à chaud).
- Le mock importe en lecture seule le réducteur et les builders du front (`workspaceModel.js`, `widgetData.js`).
  - Toute question métier joue le scénario multi-facettes ; « v1 ... » rejoue la V1.3.
  - La conversation `sess-seed-ws-1` sert à tester la restauration.
  - Il reproduit le contrat multi-SQL de WP-A (`sql_id`, 400 / 404 / 409).
- Carte des composants : `AppLayout` -> `WorkspacePanel` (BoardGrid -> WidgetCard -> ArtifactChart / Table / Kpi `bare`, WidgetText ; ProvenanceDrawer ; onglet Données = DataFocus si la vue n'est pas restreinte au sql_id, sinon EvidencePanel `embedded` + EvidenceSqlPicker) | EvidencePanel seul (réponses V1.3) | SourcePanel | WorkspaceTeaser (balise). `ChatView` -> PlanCard + PromptBar ; `MessageAgent` -> WorkspaceSummary.
- Une seule voie pour les lignes : `sqlById` (live) + `resolved` (serveur), fusionnés dans `sqlInfo()` -> `widgetData()`. Les lignes live par sql_id (phase 2 de WP-A) arriveront par les events `sqlId` + `result`, sans changement front.
- Le réducteur JS est le miroir de `python-lib/owismind/workspace/reducer.py`, épinglé par `contracts/fixtures/*` (lecture seule).
- Vérification sans navigateur : bundles Node du scratchpad (`hooks.mjs` + `reg.mjs` : compilation SFC SSR, stubs DOM), voir `layout.mjs`, `chatflow.mjs`. Lancer avec `node --import <scratchpad>/reg.mjs <script>` depuis `frontend/`.
- Gates : `cd frontend && node --test test/*.test.js` ; build `./node_modules/.bin/vite build --outDir <scratchpad>/owi_bc --emptyOutDir` puis `rm -rf` (jamais dans `resource/`).
