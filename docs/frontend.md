# Frontend — architecture (Vue 3 + Vite)

> Guide d'onboarding pour le front du plugin **OWIsMind**. Toute la prose est en français ; les
> identifiants (composants, stores, composables, routes, fichiers) restent en anglais, tels qu'écrits
> dans le code. Chemins toujours relatifs à `Plugin/owismind/frontend/`.
>
> Doc map : [architecture.md](architecture.md) · [backend-api.md](backend-api.md) · **frontend.md** (ce doc) ·
> [data-model.md](data-model.md) · [security.md](security.md) · [build-test-deploy.md](build-test-deploy.md).
> Le *pourquoi* des décisions vit dans `memory/PROJECT_STATE.md` §13 et `memory/LESSONS.md` (L022→L045) ;
> ce guide décrit le *quoi* et renvoie à la mémoire pour le *pourquoi*.

---

## 1. Stack & vue d'ensemble

| Brique | Version | Rôle |
|---|---|---|
| `vue` | 3.5 | Framework (Composition API, `<script setup>`) |
| `vite` | 8 | Build → assets statiques |
| `pinia` | 3.0.4 | State management (stores `setup`) |
| `vue-router` | 5.1.0 | Routing **HASH** |
| `vue-i18n` | 11.4.4 | i18n FR/EN (mode `legacy:false`) |
| `markdown-it` | 14 | Rendu markdown des réponses agent |
| `dompurify` | 3.4.8 | Sanitisation du HTML markdown (seul chemin `v-html`) |

> **NO INSTALL** : les dépendances sont installées par l'utilisateur uniquement (règle non négociable du repo).
> Les tests purs utilisent `node:test` natif (pas de Vitest) — voir §4.

Le front est **buildé** par Vite vers `../resource/owismind-app/` (`outDir`), avec
`base: '/plugins/owismind/resource/owismind-app/'`. Ces noms sont **canoniques** : ne jamais les changer
(`memory/PROJECT_STATE.md` §3). DSS sert ces assets ; `webapps/.../body.html` est une copie de l'`index.html`
buildé (recâblage fait par `/build-plugin`, voir [build-test-deploy.md](build-test-deploy.md)).

**Tous les appels backend passent par `services/backend.js`**, qui résout l'URL **paresseusement** via
`window.getWebAppBackendUrl(path)` (injecté par la `standardWebAppLibrary` « dataiku »). On **ne code jamais
une URL en dur** ; le préfixe Blueprint est `/owismind-api` sans slash final. `fetch` avec
`credentials: 'same-origin'` (les cookies d'auth DSS voyagent), JSON in/out, et le code d'erreur stable du
backend est remonté comme `Error(code)` (ex. `agent_not_enabled`, `busy`, `run_not_found`). Détail des routes :
[backend-api.md](backend-api.md).

Hors DSS (ex. `npm run dev`), `getWebAppBackendUrl` est absent : chaque appel échoue proprement et les stores
**dégradent gracieusement** (le shell s'affiche toujours). En DEV on injecte une démo via
`window.__pinia.state.value.{chat,session}` (`main.js` expose `window.__pinia` derrière `import.meta.env.DEV`).

---

## 2. Arborescence `src/`

```
main.js                       # createApp + pinia + i18n + router ; pose body[data-theme] AVANT mount ;
                              #   expose window.__pinia en DEV (tree-shaké en prod)
App.vue                       # shell racine : <AppLayout/> + <ToastHost/> ; session.ensureLoaded() au mount

services/
  backend.js                  # client backend (fetch via getWebAppBackendUrl) — 1 fn par route, jamais d'URL en dur

router/
  index.js                    # vue-router HASH ; routes + guard admin (beforeEach)

i18n/
  index.js                    # createI18n(legacy:false) ; merge des catalogues domaine ; setLocale/currentLocale
  messages.json               # port 1:1 de la maquette d'origine (window.OWI_I18N) — PRISTINE, jamais édité
  extra.js                    # ajouts Phase 3/4 (clé-plate par locale), mergés dans vue-i18n
  langs.json                  # liste des locales [{id,label,short,flag,htmlLang}]

styles/
  tokens.css                  # design tokens (theme.css verbatim + ajouts no-op) ; switch body[data-theme]
  base.css                    # reset + scrollbar + keyframes + utilitaires (importé APRÈS tokens)

stores/                       # Pinia (setup stores) — voir §3
  ui.js  session.js  chat.js  conversationList.js  conversationTree.js  agentPick.js  prefs.js
  evidence.js                 # panneau Evidence Studio — voir §6

composables/                  # logique réutilisable — voir §4
  timelineModel.js  useChatStream.js  useMarkdown.js  useToasts.js
  useClickOutside.js  useReducedMotion.js  useTr.js
  evidenceModel.js            # modèle PUR Evidence (chips/payload/modified) — voir §6

registries/                   # données statiques enregistrées (extensible = ajouter une entrée)
  agentMeta.js  timelineSteps.js  faqContent.js

components/
  ui/                         # primitives mutualisées + barrel index.js
    Icon.vue (+icons.js)  Button.vue  Tabs.vue  Menu.vue  Modal.vue  ToastHost.vue
  shell/                      # ossature de l'app
    AppLayout.vue  Sidebar.vue  MainTop.vue
  chat/                       # surface de chat
    AgentPicker.vue  PromptBar.vue  MessageUser.vue  MessageAgent.vue
    ChatThread.vue  ChatEmpty.vue  FeedbackModal.vue
  evidence/                   # Evidence Studio (panneau de preuve) — voir §6
    EvidencePanel.vue  EvidenceChips.vue  EvidenceTable.vue  EvidenceSql.vue
  pages/                      # fondations des pages secondaires + barrel index.js
    PageShell.vue  EmptyState.vue  SettingCard.vue

views/                        # une vue par route (lazy-loadées par le router)
  ChatView.vue  SettingsView.vue  FeedbackView.vue  FaqView.vue
  AgentsView.vue  ProjectView.vue  AdminView.vue  PagePlaceholder.vue

assets/
  orange-logo.png

test/                         # HORS src/ (jamais buildé/zippé) — node:test pur (`npm test`)
  timeline.test.js  prefs.test.js  conversationTree.test.js
  conversationList.test.js  agentPick.test.js  evidenceModel.test.js
```

---

## 3. Stores Pinia

Tous des **setup stores** (`defineStore('id', () => { … })`).

| Store | `path` | Responsabilité | État clé |
|---|---|---|---|
| `ui` | `stores/ui.js` | **Source unique des préférences** : thème, langue (miroir de l'i18n), largeurs sidebar/convpane, fenêtre de contexte. Persistance localStorage **une clé par préf**. | `theme`, `lang`, `contextMessages`, `sidebarCollapsed`, `sidebarW`, `convpaneW` |
| `prefs` | `stores/prefs.js` | **PUR** (pas de Vue) : bornes + coercition de la fenêtre de contexte (`clampContextMessages`, défaut 20, `[10,50]`). Miroir front du `validate_history_limit` backend. | `CONTEXT_MESSAGES_{MIN,MAX,DEFAULT}` |
| `session` | `stores/session.js` | Identité (`/me`), liste des agents activés (`/agents`), liste **paginée** des conversations (noms seuls). Tout dégrade gracieusement hors DSS. | `user`, `isAdmin`, `needsConfig`, `agents`, `selectedAgentKey`, `conversations`, `convCursor`, `convHasMore` |
| `chat` | `stores/chat.js` | Conversation active comme **arbre d'échanges** + état d'envoi + brouillon. Enveloppe le transport (`useChatStream`) et la session. | `activeSessionId`, `exchanges` (plat), `turns` (computed = chemin actif), `overrides`, `draft`, `sending`, `threadLoading/Error` |
| `evidence` | `stores/evidence.js` | État du panneau Evidence Studio : échange affiché, meta serveur, chips éditables locales, page de lignes. Gardé par numéros de séquence anti-réponses périmées. Voir §6. | `open`, `exchangeId`, `meta`, `chips`, `includeAdvanced`, `rows`, `page`, `hasMore`, `sort`, `error`, `rowsError`, `modified` |
| `conversationList` | `stores/conversationList.js` | **PUR** : helpers de la liste sidebar paginée (`mergeConversations` dédup, `upsertAndBump` remonte en tête). | — (fonctions pures) |
| `conversationTree` | `stores/conversationTree.js` | **PUR** : reconstruction de l'arbre (`childrenOf`, `activeChildOf`, `buildActivePath`). | — (fonctions pures) |
| `agentPick` | `stores/agentPick.js` | **PUR** : `pickDefaultAgent(agents, lastKey)` = dernier agent utilisé s'il est encore activé, sinon le premier. | — (fonction pure) |

### 3.1 Le store `chat` : `exchanges` (plat) + `turns` (arbre computed)

Une conversation est un **arbre**. Chaque `exchange` porte son `parentId` ; le store garde une **liste plate**
`exchanges` et dérive le **chemin actif** `turns` (computed) via `buildActivePath` du store pur
`conversationTree` (`stores/chat.js:58`). Forme d'un échange :

```
exchange: reactive({ uid, id, parentId, userText, version, createdAt })
```

- `uid` : **clé de rendu stable**, fixée une fois et **jamais modifiée** → le `v-for` est keyé dessus
  (`ChatThread.vue:75`). C'est l'invariant **F12** : ne pas keyer sur `id` (réconcilié en cours de run →
  remount/flicker).
- `id` : `null` tant que le run est live, **réconcilié** vers l'`exchange_id` backend via le callback
  `onExchangeId` de `runChatStream` (`stores/chat.js:195`).
- `version` : un `reactive(createAnswerState())` — la timeline d'affichage + SQL/usage + feedback persisté
  (voir §4/§5).
- `createdAt` : horloge cliente monotone (`nextStamp`) pour que les échanges frais trient **après** les lignes
  d'historique (dont le `createdAt` est un timestamp serveur), gardant la branche la plus récente active.

**Création / édition / régénération** (le seul endroit où un échange est créé = `_runExchange`) :
- `send(text)` → enfant du dernier `turn` (bas du chemin actif).
- `editTurn(turn, newText)` → **frère** de l'échange édité (`parent = turn.exchange.parentId`), pas son enfant.
- `regenerateTurn(turn)` → **frère** avec le même prompt (nouvelle branche/version).

Rien n'est jamais supprimé : l'ancienne version reste atteignable via les flèches de version (siblings). Le
nouveau frère étant le dernier enfant, il devient la branche active par défaut (et on retire tout `override`
épinglé à ce parent). `setTurnVersion(turn, idx)` épingle un sibling précis (ignore un sibling encore live,
`id===null`) puis re-walk le chemin en dessous. Rationale → **L032** / `memory/CONTEXT.md` F12.

### 3.2 Reconstruction d'arbre : `buildActivePath` (pur, testé)

`stores/conversationTree.js` (≈37 lignes, aucune dépendance Vue) :

- `childrenOf(exchanges, parentId)` : enfants triés par `createdAt` (tiebreak `id`) ; la racine = `parentId` null
  (clé interne `'__root__'`).
- `activeChildOf(exchanges, parentId, overrides)` : l'enfant **override** s'il est épinglé, **sinon le plus récent**.
- `buildActivePath(exchanges, overrides)` : descend de la racine en suivant `activeChildOf` ; chaque entrée du
  chemin = `{ exchange, siblings, versionIdx }`. Garde anti-cycle (`exchanges.length + 1`) ; une feuille live
  (`id===null`) n'a pas d'enfants → arrêt du walk.

### 3.3 `session` : agent persistant par conversation (F15)

- Seul `selectAgent(key)` **persiste** dans `localStorage` (`owismind.lastAgentKey`).
- `useDefaultAgent()` (conversation neuve) et `adoptAgentFromExchanges(rows)` (ouverture d'une conversation)
  **ne persistent pas** ; `adopt` choisit l'agent du **dernier échange** s'il est encore activé, sinon le défaut.
- L'adoption est **différée** via `session.ensureLoaded().then(adopt)` (`stores/chat.js:153`) pour éviter la
  course `/conversation` (1 aller-retour rapide) vs `/me`+`/agents` (2 allers-retours) qui laisserait
  `session.agents` vide. Rationale → **L032** / `memory/CONTEXT.md` F15.
- `init()` est **mémoïsé** par `ensureLoaded()` (appelé depuis `App.vue` au mount et depuis le guard router).
  `loadFirstConversations` partage un `_firstConvPromise` pour dédupliquer le double déclenchement (init + Sidebar).

---

## 4. Composables

| Composable | `path` | Rôle |
|---|---|---|
| `timelineModel` | `composables/timelineModel.js` | **PUR** (réducteur) : `createAnswerState`, `applyEvent`, `answerText`, `timelineSignature`. Voir §5. |
| `evidenceModel` | `composables/evidenceModel.js` | **PUR** (sans Vue) : `chipsFromMeta`, `buildRowsPayload` (jamais de SQL dans le payload), `normalizeEditableOp`, `isModified` (signature d'état de chips). Voir §6. |
| `useChatStream` | `composables/useChatStream.js` | Transport **polling** : `runChatStream(...)` démarre un run puis poll `/chat/poll` (500 ms) et passe chaque event à `applyEvent`. |
| `useMarkdown` | `composables/useMarkdown.js` | `renderMarkdown(text)` → HTML **sanitisé** (markdown-it `html:false` + DOMPurify, liens `target=_blank rel=noopener`). |
| `useToasts` | `composables/useToasts.js` | File de toasts réactive au niveau module ; `push/dismiss` ; rendue par un seul `<ToastHost>` (monté dans `App.vue`). |
| `useTr` | `composables/useTr.js` | Traducteur de **données** `{fr,en}` (≠ strings UI) ; réactif sur la locale i18n ; fallback `cur → fr → en → première valeur`. |
| `useClickOutside` | `composables/useClickOutside.js` | Listener clic-dehors lié au cycle de vie (mount/unmount), capture phase, accepte un ref ou un tableau. |
| `useReducedMotion` | `composables/useReducedMotion.js` | Flag réactif `prefers-reduced-motion` (les composants lisent `reduced.value` pour couper l'animation non essentielle). |

### 4.1 Unités PURES testées (F11)

Réducteur, clamps, arbre et sélection d'agent sont **purs** (aucun import Vue/dataiku), donc testables avec
`node:test` natif (`npm test` = `node --test test/*.test.js`). Fichiers de test sous `test/` (**hors `src/`** →
jamais buildé/zippé) :

| Test | Unité couverte |
|---|---|
| `test/timeline.test.js` | `timelineModel` (réducteur `applyEvent`, ordre, fusion des deltas, SQL/usage hors timeline, events inconnus ignorés) |
| `test/prefs.test.js` | `clampContextMessages` (`[10,50]`, défaut 20, non-fini → défaut) |
| `test/conversationTree.test.js` | `buildActivePath` (dernier enfant par défaut, override, feuille `id===null` termine le walk) |
| `test/conversationList.test.js` | `mergeConversations` (dédup), `upsertAndBump` |
| `test/agentPick.test.js` | `pickDefaultAgent` (dernier utilisé si activé, sinon premier) |
| `test/evidenceModel.test.js` | `evidenceModel` (chips depuis la meta, payload `/evidence/rows` sans SQL, `isModified`, normalisation `=`/`IN`) |

> Le réducteur est volontairement pur **et** mute son état en place : les mêmes appels pilotent un proxy
> `reactive()` Vue (re-render fin live, **F5**/L020), le store étant responsable du wrapping `reactive()`.

---

## 5. Timeline live

Le réducteur `timelineModel.applyEvent(state, evt)` (`composables/timelineModel.js:153`) construit **une seule
liste ordonnée** à partir du flux d'events normalisés que le backend renvoie au poll. Chaque élément apparaît
exactement là où il a été reçu ; les nouveaux ne s'ajoutent qu'**en dessous** — un event d'activité, un bout de
texte intermédiaire, un appel d'outil, encore du texte, la réponse finale, une erreur, tout s'entrelace dans
l'ordre d'arrivée réel.

- Formes d'items (discriminées par `kind`, chacune avec un `id` stable + `seq` d'arrivée) :
  `event` `{ eventKind, toolName, blockId, elapsedSeconds, status:'running'|'done' }`,
  `text` `{ text, open }` (`open` = deltas encore en cours de fusion), `error` `{ message }`.
- Events gérés : `run_started` (pose `exchangeId`), `agent_event` (push event), `answer_delta` (fusionne dans le
  bloc texte ouvert), `generated_sql`, `usage_summary`, `final_answer`, `run_done`, `error`. Tout type **inconnu
  est ignoré silencieusement** (jamais d'exception).
- **`generated_sql` et `usage` sont HORS timeline** (**F8**/L029) : le SQL va dans `state.sql` (panneau
  collapsible dédié), l'usage dans `state.usage`. La **trace** brute n'est jamais envoyée au front.
- Les champs **feedback** (`feedbackRating/Reasons/Comment`) sont **hors-bande** : `applyEvent` n'y touche
  jamais ; ils sont posés par le store / `MessageAgent` depuis les lignes `/conversation` ou après
  `/chat/feedback`.
- `answerText(state)` concatène les blocs texte (pour le copier) ; `timelineSignature(state)` = signature de
  changement bon marché (`nb items | longueur texte | status`) qui pilote la ré-évaluation du scroll.

**Transport** (`useChatStream.runChatStream`) : `startChat` renvoie `{ run_id, exchange_id }` (le `exchange_id`
réconcilie immédiatement la clé d'arbre via `onExchangeId`), puis boucle de poll à 500 ms ; une erreur de poll
transitoire est **retentée avec backoff** (jusqu'à 5 échecs), un code **terminal** (`run_not_found`,
`invalid_run_id`, `unauthenticated`) clôt proprement le run. Un `token.cancelled` (flippé sur switch de
conversation / run plus récent) arrête la boucle. **POLLING et non SSE** : le proxy interne DSS bufferise les
flux longs (L019).

---

## 6. Evidence Studio

Le panneau de **preuve** : pour un message agent ayant produit du SQL, il montre les **filtres de l'agent
décomposés en chips** + les **lignes live** de la table source whitelistée + le **SQL brut**. Le front
n'envoie **jamais de SQL** : seulement un `exchange_id`, des filtres structurés `{column, op, values}` et des
ids de chips verrouillées — tout le reste (table, connexion, requête, whitelist) est résolu serveur
(routes `/evidence/*` → [backend-api.md](backend-api.md) §3.5). Spec validée :
`docs/superpowers/specs/2026-06-09-evidence-studio-v1-design.md`.

### 6.1 Le store `evidence` (`stores/evidence.js`)

État du panneau : `open`, `exchangeId`, `meta` (dernière réponse `/evidence/meta`), `chips` (état éditable
**local**), `includeAdvanced`, `rows`/`page`/`hasMore`/`sort`, et deux niveaux d'erreur — `error`
(niveau meta : blanke le panneau) vs `rowsError` (niveau lignes : les chips **restent montées** et
interactives, retry possible).

- **Gardes de séquence anti-réponses périmées** : `seq` (transitions open/close — toute réponse d'une
  ouverture supersédée est jetée) et `rowsSeq` (réponses `/evidence/rows` hors d'ordre — la dernière
  **requête** gagne, pas la dernière réponse). Même idiome que le cancel token de `chat.js`.
- **Auto-open « staged »** (`openForExchange(id, { auto: true })`) : fetch la meta **sans toucher** l'état
  courant du panneau, et ne committe (reset + open + chargement des lignes) **que si** la vue interactive est
  confirmée (`meta.available`) et qu'aucun open/close utilisateur n'est survenu entre-temps — un auto-reveal
  dégradé ou échoué ne peut jamais effacer/fermer ce que l'utilisateur regarde. L'**ouverture manuelle**
  (bouton par message) ouvre immédiatement, vue dégradée incluse.
- **Pagination avec rollback ciblé** : `_loadRows` retourne un tri-état (`true` succès / `false` échec réel /
  `null` supersédé) ; `nextPage`/`prevPage` ne rollbackent `page` **que** sur `false` (un `null` signifie
  qu'une autre action possède l'état désormais).
- Édition des filtres (scope v1) : `removeChip`, `setChipValues` (picker, chips `=`/`IN`), `addFilter`
  (chip user sur n'importe quelle colonne), `removeAdvanced`, `resetToAgent` ; chaque mutation remet
  `page = 0` puis `refreshRows()`. `setSort(column)` bascule asc/desc. `loadDistinct(column)` retourne la
  promesse au caller (le popover possède son état transitoire, rien n'est stocké ici).

### 6.2 Modèle pur `evidenceModel.js` (testé `node:test`)

Helpers **purs** (aucun import Vue — F11), testés dans `test/evidenceModel.test.js` :

- Forme d'une chip locale : `{ key, id, column, op, values, editable, source }` — `key` stable pour le
  `v-for` (`'a<id>'` chips agent, `'u<n>'` chips user), `source: 'agent' | 'user'`.
- `chipsFromMeta(meta)` : chips serveur → état éditable local (copies des `values`).
- `buildRowsPayload(...)` : chips éditables/user → `filters` structurés ; chips verrouillées → `kept_ids`
  seulement (re-dérivées serveur depuis le SQL stocké). **Jamais de SQL dans le payload.**
- `normalizeEditableOp(values)` : op cosmétique (`=` à 1 valeur, `IN` sinon) ; contrat : `values` non vide
  (le store **retire** la chip plutôt que de laisser sa dernière valeur se désélectionner).
- `isModified(meta, chips, includeAdvanced)` : signature positionnelle ordre-stable de l'état des chips vs
  l'état agent — pilote le badge « modifié » + le bouton « Version agent ».

### 6.3 Les composants (`components/evidence/`)

| Composant | Rôle |
|---|---|
| `EvidencePanel.vue` | La colonne **centrale** : header (dataset + « L'agent a vu N ligne(s) » + fermer) et rendu des états du store — loading / erreur meta / **dégradé** (`ev.degraded` + SQL brut) / interactif (chips + table). |
| `EvidenceChips.vue` | Le WHERE de l'agent en chips : `=`/`IN` **éditables** (picker de valeurs distinctes), comparaisons **verrouillées** mais retirables, fragment avancé = une chip verrouillée retirable en bloc, + « Ajouter un filtre » et reset « Version agent ». Un seul popover à la fois ; garde `pickerSeq` contre les réponses distinct périmées ; les valeurs d'origine de l'agent restent sélectionnables même hors du top-100 (dédup sur `String(v)` — valeurs parsées du SQL = strings vs valeurs live typées). |
| `EvidenceTable.vue` | Lignes live : header sticky, **tri au clic**, pages de 50 lignes (`LIMIT n+1` serveur → `has_more`), état vide honnête, erreur lignes **récupérable** (retry sans perdre les chips). |
| `EvidenceSql.vue` | Footer repliable : le SQL exact de l'agent + bouton copier (toast) — transparence totale sous la preuve visuelle. |

### 6.4 Intégration shell, chat & i18n

- **Grille `with-evidence`** (`AppLayout.vue`) : panneau ouvert → la grille `.app` passe de
  `sidebar | 1fr` à `sidebar | evidence (1fr, flexible) | conversation (--convpane-w, fixe)` ; la
  conversation devient la colonne de **droite**, redimensionnable par une 2ᵉ poignée (`startConvResize`,
  largeur = `window.innerWidth - e.clientX` car elle grandit vers la gauche). `ui.setConvpaneWidth` clampe
  via `clampConvpane` (persisté `owi.convpaneW`, **clampé aussi à la lecture** : une largeur persistée sur
  un grand écran ne doit pas briquer la mise en page ailleurs) — au moins ~520 px restent réservés à
  sidebar + evidence pour que le panneau et sa poignée restent atteignables.
- **Auto-open** (`stores/chat.js`, fin de `_runExchange`) : une réponse terminée **proprement**
  (`status === 'done'`, ni stop ni erreur ni cancel) avec **au moins un SQL `success`** déclenche
  `evidence.openForExchange(exch.id, { auto: true })` en **fire-and-forget** (le reveal ne peut jamais
  affecter le flux d'envoi). Jamais d'auto-open dégradé (décision user — gate `meta.available` dans le
  store). `newConversation()` et `openSession()` appellent `evidence.close()` (le panneau ne survit pas à
  un switch de conversation).
- **Bouton « Preuves »** (`MessageAgent.vue`) : affiché si `v.sql.length && v.exchangeId`, ouvre
  manuellement le panneau pour **ce** message (vue dégradée incluse) ; style `primary` quand le panneau
  montre déjà cet échange (`isEvidenceOpen`).
- **i18n** : les strings du panneau vivent sous les clés `ev.*` ajoutées dans `i18n/extra.js` (FR/EN,
  clé-plate par locale — F6) : titre/fermeture (`ev.title`, `ev.open`, `ev.close`), compteur
  (`ev.agent_rows`), chips (`ev.filters.*`, `ev.modified`), table (`ev.table.*`), SQL (`ev.sql.*`),
  picker (`ev.picker.*`, `ev.column`), états (`ev.degraded`, `ev.error`, `ev.retry`, `ev.loading`).
  (Les `ev.chip.*` du footer SQL par message préexistent dans `messages.json` — pristine, inchangé.)

---

## 7. Routing & shell

`router/index.js` — **`createWebHashHistory()`** : la webapp DSS est servie à une URL fixe sans réécriture SPA,
donc l'historique par path 404 au reload/deep-link ; le hash garde tout client-side et reload-safe (**F3**).

| Route (`name`) | Path | Vue | Notes |
|---|---|---|---|
| (redirect) | `/` → `/chat` | — | |
| `chat` | `/chat/:sessionId?` | `ChatView` | surface principale |
| `settings` | `/settings` | `SettingsView` | préférences (lit/écrit le store `ui`) |
| `feedback` | `/feedback` | `FeedbackView` | état vide honnête (pas d'API) |
| `faq` | `/faq` | `FaqView` | contenu statique `faqContent` + recherche client |
| `agents` | `/agents/:agentId?` | `AgentsView` | liste + fiche (enrichie par `agentMeta`) |
| `project` | `/project/:projectId` | `ProjectView` | |
| `admin` | `/admin` | `AdminView` | **route gardée** (`meta.requiresAdmin`) |
| `support`/`releases`/`accessibility`/`cgu`/`privacy`/`about` | `/…` | `PagePlaceholder` | placeholders honnêtes pilotés par meta i18n |
| (catch-all) | `/:pathMatch(.*)*` → `/chat` | — | |

- Les vues sont **lazy-loadées** (`() => import(...)`) pour garder le bundle chat initial léger.
- **Guard admin** (`beforeEach`) : si `to.meta.requiresAdmin`, `await session.ensureLoaded()` (mémoïsé) puis
  gate sur `session.isAdmin` (sinon redirige vers `chat`). La décision réelle reste **serveur** (les routes
  admin renvoient 403) ; le guard n'est qu'un confort UX.
- **Shell** = `AppLayout.vue` : grille `.app` 2 colonnes (`--sidebar-w` | `1fr`) avec poignée de resize draggable
  (`Sidebar` | handle | `<main>` = `MainTop` + `<RouterView/>`). Panneau Evidence ouvert → classe
  `with-evidence` et grille **3 colonnes** `sidebar | evidence | conversation` avec une 2ᵉ poignée de resize
  (voir §6.4).
- **Hooks DEV-only** derrière `import.meta.env.DEV` : `window.__pinia` (`main.js`) pour injecter une démo sans
  backend. Tree-shaké hors prod.

---

## 8. i18n

`i18n/index.js` — `createI18n({ legacy: false, globalInjection: true, fallbackLocale: 'fr' })` ; locale détectée
depuis `localStorage('owismind.lang')` puis `navigator.language`. `useI18n()` est utilisé en **scope global**.

- **Interpolation en LISTE** : `t('key', [arg0, arg1])` (les `{0}`/`{1}` positionnels de la maquette mappent
  directement).
- **`messages.json` reste PRISTINE** : c'est un port 1:1 de `window.OWI_I18N` de la maquette d'origine,
  supprimée du repo après conversion (ne pas l'éditer,
  **F6**/L023). Les ajouts vont dans **`i18n/extra.js`** sous forme **clé-plate par locale** (`{ fr: {...}, en: {...} }`),
  mergés via `mergeLocaleMessage`. Le catalogue de timeline (`registries/timelineSteps.js → timelineMessages`)
  est mergé de la même façon.
- `extra.js` contient surtout des états vides/« bientôt disponible » **honnêtes** (préfixes `x.`, `set.`, `fb.`,
  `faq.`, `ag.`, `pj.`, `sb.`, `chat.`, `msg.`) — jamais de faux chiffres.
- **Données** `{fr,en}` (agents, FAQ) → rendues via `useTr()`, pas `$t` (§4).
- `setLocale(id)` valide l'id, applique à vue-i18n, persiste (`owismind.lang`) et pose `<html lang>` ;
  `currentLocale()` lit la locale active. Le store `ui` (`setLang`) en garde un miroir réactif.
- Les clés `ev.*` du panneau Evidence Studio vivent dans `extra.js` (voir §6.4) ; les `ev.chip.*` du footer
  SQL par message viennent du port maquette (`messages.json`).

> Ajouter une langue : ajouter son bloc dans `langs.json` + un bloc locale dans `messages.json`, et le champ sur
> tout objet data `{fr,en}`.

---

## 9. Thème & design system

- **Thème posé sur `<body data-theme>` AVANT mount** (`main.js:14`, **F4**) pour éviter le flash de tokens non
  stylés : les tokens sémantiques (surface/text/border) vivent **uniquement** sous `body[data-theme="…"]` dans
  `tokens.css`. Le store `ui` réconcilie ensuite (idempotent) et expose `setTheme`/`toggleTheme`. Défaut `light`.
- **`tokens.css`** : palette **Orange** (`--orange:#ff7900`), spacing 8px, type, radius, motion — port verbatim
  de la maquette d'origine. Les tokens neufs sont des **ajouts no-op** (valeur = littéral déjà hard-codé → 0 pixel changé).
- **`base.css`** : reset, scrollbar, sélection, keyframes, utilitaires (`.u-no-shrink`). Importé **après**
  `tokens.css` (l'ordre compte, `main.js:5-6`). `body { overflow: hidden }` (shell viewport fixe, scroll dans
  les régions internes).
- **Gotcha thème `:global` (F2/L022)** : dans un `<style scoped>`, un override de thème doit mettre le **sélecteur
  entier** dans `:global(body[data-theme="dark"] .x)` (sinon le descendant scopé est perdu). Utilisé dans
  `Modal.vue`, `Menu.vue`, `Sidebar.vue`, `ChatView.vue`. Pour les **teintes orange douces**, préférer le token
  `--orange-soft-dark` (`tokens.css:95/111`) plutôt qu'un patch `:global` (raffinement L024). **Pas de
  `color-mix`** (support navigateur, L031) : `rgba` + override `:global` dark.
- **Reduced-motion** : `useReducedMotion` centralise le respect de la préférence système.

---

## 10. Conventions & gotchas clés (pointeurs mémoire)

Détail complet : `memory/CONTEXT.md` (F1–F21) et `memory/LESSONS.md` (L022–L045).

- **F3 — Router HASH** : `createWebHashHistory()` obligatoire (DSS sans réécriture SPA) — §7.
- **F4 — Thème pré-mount** : `body[data-theme]` posé dans `main.js` avant `mount` — §9.
- **F5 — Proxy réactif** : la `version`-réponse est un `reactive()` mué **en place** par `applyEvent` à travers le
  proxy (re-render fin live) — §4.1/§5.
- **F6 — i18n** : `useI18n()` global, interpolation liste, `messages.json` pristine + ajouts `extra.js` — §8.
- **F8 — Timeline** : réducteur pur `timelineModel.js` = une timeline unique ordonnée ; `generated_sql`/`usage`
  hors timeline — §5.
- **F10 — Build : recâbler `body.html`** : après build, `index.html` → `body.html` ; l'entrée hash change à
  chaque build (fait par `/build-plugin`) — [build-test-deploy.md](build-test-deploy.md).
- **F11 — Tests purs** : réducteur/clamp/SQL-builder/arbre/agentPick purs → testables `node:test` — §4.1.
- **F12 — Arbre keyé sur `uid`** : `v-for` keyé sur `uid` **stable** (pas l'`id` réconcilié → sinon
  remount/flicker) ; éditer/régénérer = échange **frère** (parent = `parentId` du tour) — §3.1.
- **F13 — Scroll vs navigation** : `ChatThread` ne scrolle en bas QUE sur `chat.activeSessionId` (switch),
  `chat.exchanges.length` (nouvel échange) et le streaming **gaté sur `chat.sending`** — **jamais** sur `turns`
  (computed = nouveau tableau à chaque navigation → scroll parasite qui enterre les flèches de version)
  (`ChatThread.vue:60-65`).
- **F14 — Feedback** : `persistFeedback` met à jour l'état **après** l'await (un échec ne colorie pas) et retourne
  un bool → toast succès **gaté** (pas de double) ; 👎 commit **avant** la popup ; re-clic = clear ;
  `FeedbackModal` adaptatif via `feedbackMode` (raisons si rating 0) (`MessageAgent.vue:75-129`).
- **F15 — Agent persistant** : seul `selectAgent` persiste (`owismind.lastAgentKey`) ; adoption **différée** via
  `ensureLoaded().then(adopt)` — §3.3.
- **F1 — Validation locale** : `npm run dev` (port 5173, base `/plugins/owismind/resource/owismind-app/`) +
  screenshots Chrome DevTools ; compile-check via `vite build --outDir /tmp/...` (jamais builder dans
  `resource/` avant `/build-plugin`) — [build-test-deploy.md](build-test-deploy.md).
- **NO INSTALL** + `frontend/` & `node_modules/` jamais zippés ; ne pas éditer à la main `resource/owismind-app/`
  (généré).
