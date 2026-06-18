# OWIsMind - Etat frontend (stores Pinia), composables, arbre de composants et vues

Pack de connaissances code-grounded. Tous les chemins sont relatifs a la racine du frontend :
`/Users/saidchaoui/projects/owismind/Plugin/owismind/frontend/`. Stack : Vue 3 (Composition API,
`<script setup>`), Pinia 3, vue-router 5 (hash history), vue-i18n 11, markdown-it + dompurify,
chart.js 4. Build Vite vers `../resource/owismind-app/`. Aucune dependance hors `package.json`
(regle NO INSTALL). Tests purs : `node --test test/*.test.js` (pas de vitest).

## 1. Vue d'ensemble de l'architecture frontend

Le frontend est organise en couches strictes :

- **services/backend.js** : client transport unique (via `getWebAppBackendUrl('/owismind-api/...')`).
  Tous les appels reseau passent par la (jamais d'URL en dur, CLAUDE.md frontend).
- **stores/** (Pinia, defineStore "setup style") : etat reactif + actions. 5 stores reactifs
  (`chat`, `session`, `evidence`, `ui`, plus l'absent `prefs` qui est pur) et 3 modules de
  helpers PURS sans Vue (`conversationTree.js`, `conversationList.js`, `agentPick.js`, `prefs.js`).
- **composables/** : fonctions reutilisables. Deux familles : (a) PURES sans import Vue, testees
  par `node:test` (`timelineModel`, `evidenceModel`, `evidenceProof`, `sqlPretty`) ; (b) avec cycle
  de vie Vue (`useChatStream`, `useClickOutside`, `useReducedMotion`, `useToasts`, `useTr`, `useMarkdown`).
- **registries/** : tables statiques de metadonnees (`agentMeta`, `timelineSteps`, `faqContent`).
- **components/** : 4 familles (`shell/`, `chat/`, `evidence/`, `ui/`, plus `pages/`).
- **views/** : pages routees.

**Pattern de reactivite central** (memoire L020, repete dans plusieurs en-tetes de fichier) :
l'objet "version de reponse" est cree avec `reactive(createAnswerState())` (chat.js:41-43) et le
reducer pur `applyEvent` (timelineModel.js:180) le **mute en place** (`timeline.push`, `text +=`).
Comme c'est un proxy reactif, ces mutations imbriquees declenchent un re-render fin et live. Le
reducer reste pur (aucun import Vue) donc testable par `node:test`, mais ses effets pilotent un
proxy Vue. C'est la cle de tout le streaming live.

## 2. Stores Pinia

### 2.1 chat.js (stores/chat.js, 390 lignes) - le store central

Responsabilite : la conversation active comme **ARBRE d'echanges**, l'etat d'envoi, le brouillon
de prompt. Encapsule `useChatStream` (transport) et `session` (agent, historique).

**State (refs)** : `activeSessionId` (UUID via `crypto.randomUUID()`, fallback `sess-...`,
chat.js:33-38), `exchanges` (liste plate d'echanges reactifs), `overrides` (map `parentKey -> id
d'enfant choisi` pour la navigation de versions), `draft`, `sending`, `errorMsg`,
`threadLoading`, `threadError`.

**Forme d'un exchange** (chat.js:14-20, 238) :
```
reactive({ uid, id, parentId, userText, version, createdAt })
```
- `uid` : cle de rendu STABLE assignee une fois et JAMAIS modifiee (le `v-for` est keye dessus,
  pas sur `id`, pour eviter un remount mid-stream, chat.js:235-238).
- `id` : null pendant le run live, reconcilie a l'id backend via `onExchangeId` (chat.js:278).
- `createdAt` : horloge client monotone `nextStamp()` = ISO + `#` + compteur (chat.js:66-68) pour
  trier les echanges frais APRES les anciens (et apres les lignes d'historique au timestamp serveur).
- `version` : `reactive(createAnswerState(...))`, la timeline d'affichage (voir timelineModel).

**Chemin actif (turns)** : `turns = computed(() => buildActivePath(exchanges.value, overrides.value))`
(chat.js:61). C'est la lecture pure de l'arbre (conversationTree.js).

**Mecaniques cles** :
- Token d'annulation `activeToken = { cancelled }` : changer de conversation ou lancer un run plus
  recent met `cancelled = true` pour stopper la boucle de poll abandonnee (chat.js:71-88).
- `activeRunId` + `stopPending` : couvrent la course ou l'user clique stop AVANT que `/chat/start`
  renvoie le run id (`onRunId` declenche alors le stop, chat.js:279-283).
- `activeVersion` : permet a un stop explicite de finaliser le partiel a l'ecran (chat.js:81).
- `canSend` (chat.js:95-103) : `!sending && !threadLoading && !threadError && !session.needsConfig
  && session.hasAgents && !!session.selectedAgentKey`. Le garde-fou `threadLoading/threadError` est
  critique : apres un switch de conversation echoue/en vol, `exchanges` tient encore l'ANCIEN thread ;
  un envoi persisterait sous le NOUVEAU session id avec un parent de l'ANCIEN (corruption croisee).
- `_runExchange(userText, parentId)` (chat.js:232-317) : SEUL endroit ou un exchange est cree + run.
  Pousse un nouvel exchange, supprime l'override au parent (la branche fraiche reste active),
  capture `runSessionId`/`runTitle` AU DEBUT du run (pas a la fin, car le `finally` peut tourner
  une boucle de poll APRES annulation quand le store tient deja une autre conversation), construit
  `screenContext` (conscience d'ecran Evidence) quand le panneau est ouvert, appelle `runChatStream`.
  A la fin d'un run propre avec au moins un SQL reussi, auto-ouvre Evidence
  (`evidence.openForExchange(exch.id, { auto: true })`, chat.js:290-294).
- `send(text)` : enfant du dernier turn (chat.js:320-325).
- `editTurn(turn, newText)` : NOUVEAU FRERE meme parent (rien n'est supprime, chat.js:329-333).
- `regenerateTurn(turn)` : NOUVEAU FRERE meme prompt (chat.js:336-339).
- `setTurnVersion(turn, idx)` : epingle un frere via `overrides`, ignore un frere encore live
  (`id === null`, chat.js:344-349).
- `stopGeneration()` (chat.js:358-368) : stop cooperatif. POST `/chat/stop`, garde le polling, pose
  `activeVersion.stopping = true` (le banner "Stopping..."). Ne finalise PAS - l'event terminal
  `stopped` le fait.
- `openSession(sessionId)` (chat.js:193-226) : fetch paresseux des lignes via `fetchConversation`,
  reconstruit l'arbre. NE VIDE PAS `exchanges` (pas de flash "nouvelle conversation"). Adopte
  l'agent de la conversation seulement APRES chargement de la liste d'agents (`ensureLoaded().then(adopt)`).
- `ensureSession(sessionId)` (chat.js:172-185) : route -> store. Skip le refetch si deja en memoire
  et propre ; sinon `openSession`. Relance la continuite Evidence (`_autoOpenEvidence`).
- `_autoOpenEvidence` (chat.js:155-161) : a l'entree d'une conversation, rouvre Evidence sur le
  DERNIER exchange porteur de SQL de la branche active (`lastEvidenceExchangeId(turns)`).
- `rowToExchange(r)` (chat.js:108-133) : mappe une ligne `/conversation` -> exchange "done". La
  reponse persistee devient UN bloc texte unique (la timeline live n'est pas persistee). Recharge
  l'usage tokens (`usageFromRow`) et le feedback (rating 0/1, reasons, comment).

### 2.2 session.js (stores/session.js, 212 lignes)

Responsabilite : identite, liste d'agents actives (picker), liste paginee des conversations (noms
seuls). Tout degrade gracieusement hors DSS (`getWebAppBackendUrl` absent).

**State** : `user` ({user_id, groups, display_name}), `isAdmin`, `needsConfig`, `agents`
([{key,label}] depuis `/agents`), `selectedAgentKey`, `loading`, `error`, plus la liste paginee :
`conversations` ([{id,title,lastAt}]), `convCursor`, `convHasMore`, `convLoading`, `convError`.

**Mecaniques** :
- `LAST_AGENT_KEY = 'owismind.lastAgentKey'` (localStorage) : une conversation FRAICHE defaut sur le
  dernier agent choisi (session.js:13).
- `ensureLoaded()` : `init()` memoise (un seul promise) - sur (session.js:153-156). `init()` charge
  l'identite d'abord, puis agents + 1re page seulement si configure (session.js:142-150).
- `loadFirstConversations(count)` : promise partage `_firstConvPromise` qui de-duplique l'appel
  declenche EN PARALLELE par `init()` et la Sidebar (session.js:96-117).
- `bumpCurrentConversation(item)` -> `upsertAndBump` (remonte en tete apres un envoi).
- `adoptAgentFromExchanges(rows)` : ouvrir une conversation adopte l'agent du PLUS RECENT echange
  (si encore active), sans persister (session.js:173-183).
- `displayName`/`initials` : derives (initiales = 2 premieres lettres des parties du nom,
  session.js:53-59).

### 2.3 evidence.js (stores/evidence.js, 381 lignes) - le panneau de preuve

Responsabilite : l'etat du panneau Evidence Studio : quel exchange, le meta serveur
(colonnes/chips/sql), l'etat LOCAL editable des chips, la page de lignes. Chaque requete est gardee
par des numeros de sequence (meme idiome que le token d'annulation de chat).

**State** : `open`, `exchangeId`, `meta` (derniere reponse `/evidence/meta`), `activeTab`
('evidence'|'chart'|'table'|'kpi'), `chips` (etat local editable), `includeAdvanced`, `rows`
(accumulees paresseusement, capees a `MAX_ROWS = 500`), `page`, `hasMore`, `sort`,
`selectedTable` (selecteur multi-table), `drill` (drill-down trust layer v2), `loading`,
`rowsLoading`, `error` (niveau meta = blanc tout le panneau), `rowsError` (niveau rows = chips
restent montees, recuperables).

**Gardes de sequence** (evidence.js:65-67) : `seq` (transitions open/close), `rowsSeq`
(reponses rows desordonnees : le dernier REQUETE gagne, pas la derniere reponse), `userChipSeq`
(cles des chips ajoutees par l'user). `MAX_PAGE = 20` (miroir backend `MAX_EVIDENCE_PAGE`).

**Mecaniques** :
- `openForExchange(id, opts)` (evidence.js:112-159) : deux chemins. `auto:true` (revele de fin de
  generation) = staged : fetch meta SANS toucher le panneau courant, commit seulement si
  `m.available` et qu'aucun open/close user n'a eu lieu (garde `seqAtStart`). Manuel = ouvre
  immediatement, vue degradee incluse.
- `_loadRows(mySeq, opts)` (evidence.js:170-203) : charge UNE page. `append:false` = reset page 0,
  `append:true` = page suivante concatenee (infinite scroll, cape MAX_ROWS). Tri-etat : true
  (succes), false (echec), null (supersede). Adopte la page echo-ee par le serveur (le backend clamp
  les pages profondes).
- `drillIntoResultRow(rowIndex)` (evidence.js:283-312) : pivote vers les LIGNES SOURCES derriere une
  ligne de resultat capture. Labels via `buildDrillLabels` (abort si une colonne non mappable - ne
  ment jamais sur le scope). Snapshot pre-drill conserve pour `exitDrill`.
- `setTable(name)` (evidence.js:340-353) : bascule vers un autre dataset source matche. Reset des
  filtres (schema different).
- `chips` editing : `removeChip`, `setChipValues`, `addFilter`, `removeAdvanced`, `resetToAgent`
  (evidence.js:229-275). Chaque modif refait page 0 + `refreshRows()`.
- `setActiveTab(key)` : NE TOUCHE PAS `open` (regle F13 : le scroll gate de ChatThread est garde sur
  `evidence.open`, pas `activeTab`, evidence.js:366-369).

### 2.4 ui.js (stores/ui.js, 173 lignes) - preferences

Source de verite UNIQUE des preferences (remplace `window.STATE` de la maquette). Lu/ecrit par
MainTop ET SettingsView. Chaque pref persistee en localStorage avec UNE cle.

**State + cles localStorage** : `theme` (`owismind.theme`, defaut 'light'), `sidebarCollapsed`
(`owismind.sidebarCollapsed`), `sidebarW` (`owi.sidebarW`, clamp 200-420, defaut 260), `evidenceW`
(`owi.evidenceW`, clamp min 360 / max `innerWidth-520`, defaut 480), `lang` (miroir du locale i18n,
JAMAIS persiste ici - `setLocale` possede `owismind.lang`), `contextMessages`
(`owismind.contextMessages`, clamp 10-50 via prefs.js), `modelMode` (`owismind.modelMode`).

**MODEL_MODES** (ui.js:23) = `['eco', 'medium', 'high']`, defaut `eco`. Commentaire ui.js:21-22 :
eco = Gemini 3.1 Flash-Lite (defaut), medium = Gemini 3.5 Flash, high = Claude Sonnet (le backend
defaut aussi sur eco). Le frontend n'envoie QUE la cle logique `mode`, jamais un id de modele.

**Mecaniques** : `applyTheme(t)` ecrit `document.body.dataset.theme` (ui.js:103-108, applique
immediatement, idempotent avec main.js pre-mount). `setSidebarCollapsed(v, persistChoice=true)` :
`persistChoice=false` = collapse AUTOMATIQUE (Evidence qui s'ouvre) qui n'ecrase pas la pref user
(ui.js:139-142). `setLang(id)` delegue a `setLocale` puis miroir local.

### 2.5 Modules purs (sans Vue)

- **conversationTree.js** (36 lignes) : `childrenOf`, `activeChildOf`, `buildActivePath`. Le chemin
  actif suit a chaque noeud l'enfant override si pose, sinon le DERNIER par `createdAt` (tiebreak
  id, conversationTree.js:7-21). `buildActivePath` retourne `[{exchange, siblings, versionIdx}]` avec
  garde anti-cycle (`exchanges.length + 1` iterations, conversationTree.js:26).
- **conversationList.js** (21 lignes) : `mergeConversations` (dedup par id, l'existant gagne),
  `upsertAndBump` (remonte en tete).
- **agentPick.js** (8 lignes) : `pickDefaultAgent(agents, lastKey)` = dernier utilise si encore
  active, sinon le premier.
- **prefs.js** (23 lignes) : `clampContextMessages` (10-50, defaut 20). En-tete prefs.js:1-4 : ces
  bornes MIROIR de `security/validation.py` backend - frontend et backend partagent UN contrat
  (la pref persistee et le LIMIT SQL serveur ne peuvent jamais diverger).

## 3. Composables

### 3.1 timelineModel.js (368 lignes) - le reducer pur, coeur du streaming

Reducer pur sans import Vue qui transforme le flux d'events normalises du backend en UNE liste
ordonnee incrementale. Mute l'etat EN PLACE pour piloter le proxy `reactive()` (memoire L020).

**Forme de la version-reponse** (`createAnswerState`, timelineModel.js:32-51) :
```
{ timeline:[item], sql:[{sql,success,row_count}], usage, status, stopping, error,
  showSql, exchangeId, feedbackRating, feedbackReasons, feedbackComment, _seq }
```
Les champs feedback sont HORS-BANDE (persistes serveur par exchange) : `applyEvent` n'y touche
jamais (timelineModel.js:17-19).

**Formes d'items timeline** (discrimines par `kind`, chacun a un `id` stable + `seq` d'arrivee) :
- `event` : `{ id, seq, kind:'event', eventKind, toolName, blockId, elapsedSeconds, label, status }`
- `text` : `{ id, seq, kind:'text', text, open }` (open = encore en fusion de deltas)
- `error` : `{ id, seq, kind:'error', message }`
- `narration` : `{ id, seq, kind:'narration', text }` (transient, live-only, jamais persiste)

**`applyEvent(state, evt)`** (timelineModel.js:180-238) traite chaque type d'event backend :
`run_started`, `agent_event` (-> `pushEvent`), `answer_delta` (-> `appendText`, fusion des deltas
consecutifs du meme bloc), `narration` (-> `pushNarration`), `generated_sql` (pousse dans
`state.sql`, hors timeline), `usage_summary` (-> `state.usage`), `final_answer`
(-> `pushFinalAnswer` qui ne duplique PAS le texte deja streame, memoire L019), `run_done`,
`stopped` (status 'stopped', PAS error), `error`. Tout type INCONNU est SILENCIEUSEMENT ignore
(timelineModel.js:233-235) - un nouvel event ne peut jamais casser l'UI.

`sealEvents` (timelineModel.js:66-70) : un seul event est jamais "running" a la fois ; des qu'un
item suit, l'event precedent passe `done`.

**Selecteurs read-only** (groupage d'affichage, PAS une mutation de timeline) :
- `answerText(state)` : concatenation des blocs texte (pour le copy).
- `timelineSignature(state)` : signature de changement bon marche `length|textLen|status`, pilote
  les re-checks d'auto-scroll (timelineModel.js:276-281).
- `timelineEvents` / `timelineBodyItems` : split activite vs corps (le corps whiteliste text+error,
  EXCLUT narration transient, timelineModel.js:296-302).
- `timelineSegments` (timelineModel.js:319-333) : timeline en SEGMENTS chronologiques pour la vue
  LIVE - events consecutifs groupes, text/error en place. SKIP la narration (sinon elle dupliquait
  les labels et cassait le LIVE_WINDOW de 5).
- `stepStampDiff` / `activitySummary` : durees derivees des stamps backend (`elapsedSeconds` =
  ecoule-depuis-debut-run ; le total est le MAX, pas une somme).
- `usageFromRow(row)` (timelineModel.js:247-264) : reconstruit `usage` d'une ligne persistee
  (`input_tokens`/`output_tokens`/`total_tokens`/`estimated_cost` -> promptTokens/completionTokens/
  totalTokens/estimatedCost), null si rien stocke.

### 3.2 useChatStream.js (84 lignes) - le transport polling

Boucle de polling validee, portee VERBATIM du comportement de la maquette (L019/L020). Transport =
POLLING (pas SSE) : le proxy interne DSS buffer les streams longs, donc le run tourne dans un worker
background et on poll `/chat/poll`. `POLL_INTERVAL_MS = 500`, `MAX_POLL_FAILURES = 5` (backoff),
`TERMINAL_CODES = {run_not_found, invalid_run_id, unauthenticated}`.

`runChatStream({...})` (useChatStream.js:43-84) : appelle `startChat`, recoit `run_id` +
`exchange_id` (-> `onRunId`/`onExchangeId`), boucle `pollChat(runId, cursor)`. Chaque event ->
`applyEvent(target, evt)` (target = la version reactive). Le `token.cancelled` est verifie AVANT et
APRES chaque await (anti race au switch de conversation). Un `run_not_found` apres redemarrage
backend = recuperable (`run_lost`), pas un crash.

### 3.3 evidenceModel.js (140 lignes) - modele Evidence pur

Helpers purs (testes node:test, F11). Forme du chip local :
`{ key, id, column, op, values, editable, source }`. `key` = 'a<id>' (chips agent) ou 'u<n>'
(user-added). Le payload `/evidence/rows` ne porte JAMAIS de SQL : les chips editables voyagent en
filtres structures `{column, op, values}`, les chips agent verrouilles en `kept_ids` seulement (le
backend les re-derive du SQL stocke par id). `buildDrillLabels` retourne null si une colonne est non
mappable (abort silencieux plutot que mentir sur le scope, evidenceModel.js:79-106).
`lastEvidenceExchangeId(turns)` : dernier turn de la branche active dont la reponse a un SQL reussi.

### 3.4 useMarkdown.js (32 lignes) - le SEUL chemin v-html

`renderMarkdown(text)` (useMarkdown.js:24-28) : markdown-it avec `html: false` (jamais d'HTML brut
du modele) + passe DOMPurify (defense en profondeur). Un hook durcit les liens : `target=_blank` +
`rel=noopener noreferrer` (useMarkdown.js:16-21). C'est le SEUL endroit ou du texte LLM (non
fiable) devient du HTML. MessageAgent memoize le rendu par item (id+texte) pour ne pas re-parser a
chaque tick du chronometre 10Hz (MessageAgent.vue:149-156).

### 3.5 Autres composables

- **sqlPretty.js** (88 lignes) : `formatSql` (sauts de ligne par clause), `tokenizeSql`
  (classification kw/str/num/text pour coloration SAFE - chaque token rendu en texte echappe,
  jamais v-html), `highlightSqlLines`. Ne throw jamais (degrade en un token texte).
- **evidenceProof.js** (129 lignes) : trust layer. `trustLevel(meta)` -> {key, tone}
  (solid/dashed/muted, JAMAIS green, evidenceProof.js:57-73). `calcStepArgs`, `resultPreview`,
  `droppedNote`. Tout champ meta est OPTIONNEL : un meta v1 retombe sur le plancher honnete
  "declared".
- **useToasts.js** : file reactive module-level (`reactive([])`), `push(message, opts)` + auto-dismiss.
- **useTr.js** : resout un objet `{fr, en}` vers le locale courant (fallback fr -> en -> premier).
  Pour la DATA (metadonnees agent, fixtures), pas pour l'UI (qui utilise `$t`/`t`).
- **useClickOutside.js** : listener bind au cycle de vie (capture phase), remplace les listeners
  globaux one-time de la maquette.
- **useReducedMotion.js** : flag reactif `prefers-reduced-motion`.

## 4. Arbre de composants

```
App.vue (shell mince : AppLayout + ToastHost, ensureLoaded() onMounted)
 |
 +- AppLayout.vue (grille CSS : sidebar | main | evidence ; poignees de resize)
     +- Sidebar.vue (brand, nav, liste convs lazy + IntersectionObserver, menus pied)
     +- main
     |   +- MainTop.vue (titre contextuel, theme + langue rapides)
     |   +- RouterView -> une des views
     +- (v-if evidence.open) resize-handle.ev + EvidencePanel.vue
```

**ChatView.vue** (la view chat, 160 lignes) wire la route au store :
- watch `route.params.sessionId` -> `chat.ensureSession(sid)` ou `chat.newConversation()`
  (ChatView.vue:25-32, immediate).
- watch `chat.exchanges.length` -> stampe l'URL `/chat/<sid>` au 1er echange (ChatView.vue:40-47).
  Corrige le bug "bouton mort" : pousser `/chat` alors qu'on y est deja est un no-op.
- 3 etats : `needsConfig` (carte admin), `hasMessages` (ChatThread + PromptBar), sinon empty stage
  (ChatEmpty + PromptBar). Overlay de chargement centre pendant un switch (pas de flash).

**chat/** :
```
ChatThread.vue (rend turns ; auto-scroll sticky-aware)
 +- (v-for turn, :key turn.exchange.uid)
     +- MessageUser.vue (bulle user, hover copy/edit ; editTurn -> nouveau frere)
     +- MessageAgent.vue (activite + corps + SQL + usage + footer actions + nav versions)
PromptBar.vue (textarea auto-grow, AgentPicker, ModelModePicker, mic, send/stop)
 +- AgentPicker.vue (Menu, bind session.selectedAgentKey)
 +- ModelModePicker.vue (Modal 2-panes : liste modes + detail cout/vitesse)
ChatEmpty.vue / FeedbackModal.vue
```

**ChatThread.vue** (104 lignes) - auto-scroll sticky. `signature` (computed,
ChatThread.vue:33-41) = `turns.length | timelineSignature(derniere version) | versionIdx`.
4 watchers de scroll (ChatThread.vue:62-74) :
- watch `signature` mais GATE sur `chat.sending` (sinon la nav de version recalculerait la signature
  et tirerait la vue au fond, enterrant les fleches de version).
- watch `chat.exchanges.length` -> `repin` (un nouvel echange).
- watch `chat.activeSessionId` -> `repin` (switch).
- watch `evidence.open` -> `toBottom` (l'ouverture/fermeture du panneau redimensionne la colonne
  centrale, le pin du fond est perdu) ; F13-safe : ne watch PAS `turns`, et un user qui a scrolle
  n'est jamais tire (`stick=false`). `NEAR_BOTTOM_PX = 120`.

**MessageAgent.vue** (713 lignes) - le composant chat le plus complexe :
- `v = computed(() => props.turn.exchange.version)` (MessageAgent.vue:52) : la version active.
- Modele d'affichage via selecteurs purs : `steps` (timelineEvents), `bodyItems`
  (timelineBodyItems), `segments` (timelineSegments), `summary` (activitySummary). `LIVE_WINDOW = 5`.
- LIVE : segments chronologiques, chaque phase d'events = ticker borne (5 dernieres lignes,
  `TransitionGroup` avec `appear`, anciennes lignes fade-out sous un masque), reponses
  intermediaires interleavees. TERMINAL : tous les events se regroupent en UNE ligne d'en-tete
  collapsable (`activityOpen`).
- Chronometre live par etape (MessageAgent.vue:104-145) : la step RUNNING tique depuis son arrivee
  client ; une step SEALED montre `stepStampDiff` (les stamps backend sont la verite). Tick gate sur
  `activityLive && chat.sending` (anti zombie interval).
- Feedback : `like()`/`dislike()` persistent immediatement (`submitFeedback`, mutent
  `v.feedbackRating`), `dislike` ouvre ensuite la `FeedbackModal`. Le `⋯` menu ouvre le modal detaille.
- Usage : ligne `↑ in · ↓ out tokens · ~$cout` (MessageAgent.vue:423-432), live ou rebuild persiste.
- `openEvidence()` : ouverture manuelle TOUJOURS possible (vue degradee incluse), seul l'auto-open de
  fin de run est gate sur disponibilite.
- Etats honnetes : `interruptedEmpty` (stop avant tout texte), `stoppedWithText` (partiel + marqueur),
  banner "Stopping..." (MessageAgent.vue:383-402).
- Nav de versions : `versionCount = siblings.length`, `prevVersion`/`nextVersion` ->
  `chat.setTurnVersion`. Un switch de frere REMOUNT le composant (v-for keye sur `uid`, regle F12).

**ModelModePicker.vue** (209 lignes) - pilule -> `Modal` 2-panes. `selected` = ref pending appliquee
seulement sur Valider (`ui.setModelMode`). `COST = {eco:1,medium:3,high:5}`, `SPEED = {eco:5,medium:3,
high:2}`, `PILL_LEVEL` (dot vert/orange/rouge). Eco badge "recommande". Selection au CLIC (pas hover)
+ footer Annuler/Valider (pattern DSS, fini la vibration au hover - L084). Encart enveloppe 50 EUR/mois.

**evidence/** :
```
EvidencePanel.vue (header + Tabs + corps : etats loading/error/degrade/interactif)
 +- Tabs.vue (barre d'onglets, montree si artifacts chart/table/kpi)
 +- onglet 'kpi'    -> ArtifactKpi.vue
 +- onglet 'chart'  -> ArtifactChart.vue (Chart.js, payload Python pret)
 +- onglet 'table'  -> ArtifactTable.vue (resultat capture)
 +- onglet 'evidence' (defaut) :
     +- EvidenceTrust.vue (badge de confiance, si enriched)
     +- EvidenceSources.vue (dataset + lien cliquable si source.url)
     +- EvidenceChips.vue (filtres editables : =/IN picker, add, reset)
     +- EvidenceCalc.vue (steps de calcul i18n)
     +- EvidenceResult.vue (resultat exact capture + drill par ligne)
     +- (drill band) + EvidenceTable.vue (lignes lazy de la table source)
 +- EvidenceSql.vue (SQL agent, replie ; coloration via sqlPretty)
```

**EvidencePanel.vue** (293 lignes) : `enriched = !!meta.verification` (un meta v1 rend identique a
avant). `tabItems` derive de `meta.artifacts` ; 'evidence' toujours present. `activeTab` est un
computed `get/set` lie au store (set -> `evidence.setActiveTab`, NE touche PAS `open`, F13).
Etats : skeleton shimmer (loading), error, degraded (badge "declared" + raison), interactif.

**EvidenceSources.vue** (69 lignes) : gate sur `meta.source` (v1 = rien). Le nom du dataset devient
un `<a target="_blank" rel="noopener noreferrer">` quand `source.url` est present (lien Dataiku
configure sur l'agent, classe `--orange-text` AA). Feature recente L082.

**shell/AppLayout.vue** (210 lignes) : grille CSS `--sidebar-w | 1fr | --evidence-w`. Poignees de
resize a pointer-capture (un release hors iframe DSS fire quand meme pointerup). watch
`[route.name, evidence.open]` ferme le panneau hors route chat (ferme les fuites async d'auto-open).
watch `evidence.open` -> `ui.setSidebarCollapsed(true, false)` (collapse non persiste).

**ui/** (primitives mutualisees, barrel `index.js`) : `Icon`, `Button`, `Tabs`, `Menu`, `Modal`,
`ToastHost`. `Menu` reutilise par AgentPicker, Sidebar (help/user), MessageAgent (⋯). `Modal` par
ModelModePicker + FeedbackModal.

## 5. Vues et routes (router/index.js)

Hash history (`createWebHashHistory`) - choix deliberate : la webapp DSS est servie a une URL fixe
sans rewrite SPA cote serveur, donc le path history 404 au reload/deep-link. Routes :
- `/` -> redirect `/chat`
- `/chat/:sessionId?` (name chat) -> ChatView
- `/settings`, `/feedback`, `/faq`, `/agents/:agentId?`, `/project/:projectId` -> views dediees (lazy)
- placeholders help-menu : `/support`, `/releases`, `/accessibility`, `/cgu`, `/privacy`, `/about`
  -> PagePlaceholder (drive par i18n meta keys)
- `/admin` (name admin, `meta.requiresAdmin`) -> AdminView, garde `beforeEach` qui resout l'identite
  (memoise) puis gate sur `isAdmin` (router/index.js:60-65)
- catch-all -> redirect `/chat`

Toutes les views dediees sont lazy-importees (`() => import(...)`) pour garder le bundle chat leger.

## 6. Registries

- **agentMeta.js** (149 lignes) : cartes descriptives OPTIONNELLES (icon/tagline/badge/desc/bullets/
  tools), tout en `{fr,en}` (rendu via `useTr`). N'est PAS la source de la LISTE d'agents (toujours
  `/agents`, cles logiques opaques, confidentialite F7). `resolveAgentMeta(label)`
  (agentMeta.js:143-149) : match normalise exact d'abord, puis repli SUBSTRING (cle de registre la
  plus longue contenue dans le label) - permet a un label decore "Agent - OWIsMind_orchestrator" de
  resoudre la carte owismind via "owismind" embarque (L084). 6 entrees : owismind, cooper, revenues,
  tickets, cx, opps.
- **timelineSteps.js** (114 lignes) : mappe `agent_event.eventKind` -> {key i18n, icon}. Table `KNOWN`
  (AGENT_TURN_START, AGENT_TOOL_START, START, PLANNING, CALLING_AGENT...). `timelineMessages` (fr/en)
  MERGE dans vue-i18n (i18n/index.js:47-48). `resolveTimelineStep(eventKind, label)` : le label
  backend GAGNE sur le registre quand present (l'orchestrateur connait le phrasing metier mieux qu'une
  table statique). `humanize` strip `SUB_AGENT_AGENT_`/`SUB_AGENT_`/`AGENT_` puis humanise les kinds
  inconnus.
- **faqContent.js** (64 lignes) : Q/A bilingues statiques (pas de backend FAQ). 4 groupes : General,
  Donnees & Evidence, Budget (50 EUR/mois, alertes 50/80/100%), Depannage.

## 7. i18n (i18n/index.js)

vue-i18n legacy:false (Composition API), `globalInjection` ($t), `messages.json` (extraction maquette
PRISTINE) + merges modulaires `timelineMessages` + `extraMessages` (extra.js, override des messages
domaine pour ne pas toucher messages.json). `detectLocale` : localStorage `owismind.lang` -> navigator
-> 'fr'. Interpolation positionnelle LISTE : `t('key', [arg0, arg1])` (F6).

## 8. Connexions au reste du systeme et gotchas

**Contrats partages frontend <-> backend** :
- `prefs.clampContextMessages` (10-50) MIROIR de `security/validation.py` -> la pref et le LIMIT SQL
  ne divergent jamais.
- `evidence.MAX_PAGE = 20` MIROIR de `MAX_EVIDENCE_PAGE`. `buildDrillLabels` cap 8 MIROIR du backend
  (refuse >8 cles).
- `pushEvent` cap label 300 chars MIROIR de `streaming.py`.
- Le front envoie seulement `{sessionId, message, agentKey, historyLimit, mode, webappLang,
  screenContext, parentExchangeId}` ; `agentKey` et `mode` sont des cles LOGIQUES, l'`agent_id` reel
  et le modele sont resolus serveur (whitelist, regle #4).

**Conscience d'ecran** (chat.js:263-265) : `screenContext = { open, exchange_id, active_tab }` envoye
seulement quand Evidence est ouvert, pour que l'agent sache ce qui est a l'ecran ("explique ce
graphique").

**Gotchas notables** :
- Keyer le `v-for` sur `exchange.uid` (jamais `id`) - sinon remount mid-stream a la reconciliation
  de l'id backend (chat.js:235-238 ; F12).
- Le scroll de ChatThread NE doit JAMAIS watcher `turns` (regle F13) - seulement
  `activeSessionId`/`exchanges.length`/signature gated `sending`/`evidence.open`.
- `setActiveTab` ne touche PAS `evidence.open` (sinon il declenche le scroll gate F13).
- Le reducer mute en place pour la reactivite mais reste pur (testable) - ne pas y mettre d'import Vue.
- La narration est transient (kind 'narration') : exclue du corps terminal ET des segments (sinon
  double labels + casse du LIVE_WINDOW).
- L'auto-open Evidence est fire-and-forget, garde par `seq` - ne doit jamais affecter le flux d'envoi.
- Capture des donnees de bump (runSessionId/runTitle) AU DEBUT du run, pas dans le `finally` (le store
  peut tenir une autre conversation a ce moment).
- Anti tiret cadratin/demi-cadratin partout (regle #9) - utiliser `-`, `:`, `,`, parentheses.

**Tests purs** (test/, 8 fichiers `node:test`) : agentPick, conversationList, conversationTree,
evidenceModel, evidenceProof, prefs, sqlPretty, timeline. Couvrent exactement les modules PURS
listes (pas de Vue). C'est la garantie de non-regression sans installer vitest (NO INSTALL).

## 9. Points incertains / en flux

- **dataiku-agents/ est en cours d'edition LIVE par un autre ingenieur** : les eventKinds reels
  emis par les agents (donc les labels timeline effectivement affiches) peuvent diverger du registre
  `KNOWN` ; le code gere ce cas (repli `humanize`/label backend), mais la liste exacte des kinds n'est
  pas figee.
- Les modeles par mode (eco/medium/high) sont documentes dans les commentaires ui.js mais resolus
  serveur ; la memoire signale des ajustements recents (Flash-Lite vs flash-light) cote agents - le
  frontend ne porte que la cle `mode`, donc insensible a ce detail.
- `ESCALATING` existe encore dans le registre timelineSteps (cle `tl.kind.escalating`) alors que la
  memoire indique l'escalade SUPPRIMEE cote agents (Run 5, L071) ; c'est un vestige inoffensif (un
  eventKind jamais emis tombe juste inutilise).
- Le tab 'kpi' est cable cote frontend (EvidencePanel + ArtifactKpi) ; sa presence depend du backend
  emettant un artifact kind 'kpi' (non confirme dans ce pack, hors zone frontend).
