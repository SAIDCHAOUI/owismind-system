# Knowledge pack : comment le frontend dialogue avec le backend (transport polling, events)

> Zone : communication frontend <-> backend OWIsMind (transport, catalogue d'appels, boucle de
> streaming-par-polling, application des events au modele reactif, evidence/artifacts, stop, codes
> d'erreur). Toutes les affirmations sont ancrees dans le code lu (chemins absolus + lignes).
> Code et identifiants restes en anglais (verbatim). Redige en francais technique.

Racine repo : `/Users/saidchaoui/projects/owismind`
Racine frontend : `Plugin/owismind/frontend/src`
Racine backend : `Plugin/owismind/python-lib/owismind`

---

## 1. Le client HTTP : `getWebAppBackendUrl` + `request()`

Fichier : `Plugin/owismind/frontend/src/services/backend.js`

Tout le trafic passe par un client mince. DSS (la `standardWebAppLibrary` "dataiku") injecte
globalement `window.getWebAppBackendUrl`. Le frontend ne hardcode jamais d'URL : il resout le
resolver paresseusement.

```js
function backendUrl(path) {                                    // backend.js:8-14
  const resolver = window.getWebAppBackendUrl;
  if (typeof resolver !== 'function') {
    throw new Error('getWebAppBackendUrl unavailable (run inside the DSS webapp)');
  }
  return resolver(path);
}
```

- Si le resolver est absent (app lancee hors DSS), `backendUrl` jette immediatement : c'est un
  garde-fou explicite (`backend.js:11`). Cela impose que l'app tourne dans le contexte webapp DSS.
- Le prefixe de blueprint Flask `/owismind-api` est cable en dur dans chaque chemin passe a
  `request()` (cf. en-tete `backend.js:5-6`), sans slash final. Cote backend ce prefixe vient du
  Blueprint `url_prefix="/owismind-api"` (cf. CLAUDE.md python-lib + `api/routes.py`).

Le helper `request()` est le SEUL point de fetch (`backend.js:18-36`) :

```js
async function request(path, options) {
  const opts = options || {};
  const res = await fetch(backendUrl(path), {
    credentials: 'same-origin',                                // backend.js:21
    ...opts,
    headers: { Accept: 'application/json', ...(opts.headers || {}) },
  });
  if (!res.ok) {
    let code = 'http_' + res.status;                           // backend.js:26
    try {
      const data = await res.json();
      if (data && data.error) code = data.error;               // backend.js:29
    } catch (e) { /* ignore non-JSON error bodies */ }
    throw new Error(code);
  }
  return res.json();
}
```

Decisions de design (le POURQUOI) :

- **`credentials: 'same-origin'`** : fait voyager les cookies d'auth DSS avec chaque requete. C'est
  ainsi que le backend resout l'identite (`resolve_identity(request.headers)`, cf. `api/routes.py`),
  sans token applicatif separe. L'identite est toujours resolue cote serveur depuis les en-tetes.
- **`Accept: application/json`** systematique, `Content-Type: application/json` ajoute au cas par cas
  par chaque fonction POST (et JAMAIS sur les GET).
- **Codes d'erreur stables** : sur reponse non-2xx, `request()` tente de lire `{ error: "<code>" }`
  du corps JSON et leve un `Error` dont le `.message` EST ce code stable (ex. `agent_not_enabled`,
  `busy`, `run_not_found`). Si le corps n'est pas du JSON, fallback `http_<status>` (ex. `http_500`).
  C'est la surface d'erreur unique que toute la couche appelante consomme (les stores comparent
  `e.message` a des codes connus). Le backend renvoie ces codes en `{"status":"error","error":...}`
  avec un status HTTP coherent (cf. `chat_start` 400/401/404/409/429/500/503 dans `api/routes.py`).

---

## 2. Catalogue complet des appels backend

Toutes ces fonctions sont exportees depuis `backend.js`. Chemins = routes Flask sous `/owismind-api`.

| Fonction (export) | Methode + route | Corps / params | Reponse (shape) | Lignes |
|---|---|---|---|---|
| `fetchMe()` | POST `/me` | aucun | `{status, user_id, display_name, groups, needs_config, is_admin}` | 43-45 |
| `startChat(...)` | POST `/chat/start` | JSON (cf. ci-dessous) | `{status, run_id, exchange_id}` | 59-79 |
| `pollChat(runId, cursor)` | GET `/chat/poll?run_id=&cursor=` | query | `{status, events:[...], cursor, done, error}` | 87-90 |
| `stopChat(runId)` | POST `/chat/stop` | `{run_id}` | `{status:'ok'}` (404 `run_not_found` benin) | 97-103 |
| `fetchConversations(cursor, limit)` | GET `/conversations` | query opt. `cursor`/`limit` | `{status, conversations:[{session_id,title,last_at}], next_cursor, has_more}` | 108-114 |
| `fetchConversation(sessionId)` | GET `/conversation?session_id=` | query | `{status, session_id, count, rows:[...]}` | 119-121 |
| `submitFeedback(exchangeId, rating, reasons, comment)` | POST `/chat/feedback` | `{exchange_id, rating, reasons, comment}` | `{status:'ok'}` | 126-132 |
| `fetchEvidenceMeta(exchangeId)` | GET `/evidence/meta?exchange_id=` | query | meta interactive (cf. section 5) | 139-141 |
| `fetchEvidenceRows(payload)` | POST `/evidence/rows` | payload structure (cf. evidenceModel) | `{status, rows, page, has_more, ...}` | 145-151 |
| `fetchEvidenceDistinct(exchangeId, column, excludeId)` | GET `/evidence/distinct?exchange_id=&column=&exclude_id=` | query | `{status, values, truncated}` | 156-160 |
| `fetchAgents()` | GET `/agents` | aucun | `{status, count, agents:[{key,label}]}` | 164-166 |
| `fetchAdminStorage()` | GET `/admin/storage` | aucun | `{connection, project_key, table_prefix, namespace, tables}` | 171-173 |
| `fetchAdminUsers()` | GET `/admin/users` | aucun | `{users:[{user_id, is_admin, ...}]}` | 176-178 |
| `setUserAdmin(userId, isAdmin)` | POST `/admin/users/set-admin` | `{user_id, is_admin}` | liste users rafraichie | 181-187 |
| `fetchAdminProjects()` | GET `/admin/projects` | aucun | `{projects:["KEY",...]}` | 192-194 |
| `fetchAdminProjectAgents(projectKey)` | GET `/admin/projects/<key>/agents` | path | `{project_key, agents:[{agent_id, description}]}` | 197-201 |
| `fetchAdminAgents()` | GET `/admin/agents` | aucun | `{agents:[{logical_key, project_key, agent_id, label}]}` | 204-206 |
| `saveAdminAgents(agents)` | POST `/admin/agents` | `{agents:[{project_key, agent_id}]}` | selection stockee | 210-216 |

Notes transversales :

- **`fetchMe()` est en POST volontairement** (`backend.js:39-44`) : `/me` a un effet de bord (creer
  la ligne user + bootstrap du premier admin). En POST, un GET de prefetch/scanner ne peut ni creer
  un user ni gagner l'election d'admin. Appele une fois a l'init.
- **Endpoints admin "server-gated"** : 403 si l'appelant n'est pas admin (`backend.js:168`). Le front
  ne fait pas de gating de securite : il l'affiche selon `is_admin` mais le serveur tranche.
- **Whitelist agents** : le front n'envoie/recoit JAMAIS d'`agent_id` brut cote chat. `fetchAgents()`
  renvoie uniquement des cles logiques opaques `{key, label}` (`backend.js:162-166`) ; la resolution
  `agent_key -> (project_key, agent_id)` est cote serveur (`settings.resolve_enabled_agent`, cf.
  `api/routes.py:235`). Les `agent_id` ne sont visibles que dans les endpoints admin.
- **Encodage des query params** : melange `encodeURIComponent` (chat/poll, evidence) et
  `URLSearchParams` (conversations). Pas d'incidence fonctionnelle.

### Payload de `startChat` (le plus riche)

`backend.js:59-79`. Le front envoie SEULEMENT des donnees logiques ; aucune cle technique sensible :

```js
body: JSON.stringify({
  session_id: sessionId,
  message,
  agent_key: agentKey,                  // cle logique OPAQUE (resolue serveur)
  history_limit: historyLimit,          // re-clampe [10,50] serveur (defaut 20)
  parent_exchange_id: parentExchangeId || null,   // arete de l'arbre de conversation
  mode: mode || undefined,              // eco / medium / high (defaut serveur: medium)
  webapp_lang: webappLang || undefined, // fr / en (aide a choisir la langue de reponse)
  screen_context: screenContext || undefined,     // pointeur "ce qui est a l'ecran"
})
```

- `parent_exchange_id` : rattache le nouvel echange dans l'ARBRE de conversation (point de
  branchement) et borne le contexte de l'agent a la chaine d'ancetres de cette branche. `null` = une
  nouvelle branche a la racine (`backend.js:57-58`).
- `mode` : inconnu/absent -> `medium` cote serveur (`api/routes.py:277-279`, `context.MODEL_MODES`).
- `webapp_lang` : la langue de l'UI sert seulement de tie-break ; la langue du message lui-meme gagne
  cote serveur (`api/routes.py:286-288`, `context.detect_prompt_language`).
- `screen_context` : `{open, exchange_id, active_tab}` construit dans le store seulement quand le
  panneau Evidence est ouvert (cf. section 6 / `chat.js:263-265`). Owner-scoped serveur (un id forge
  ne revele rien : lecture des artifacts toujours scopee a l'appelant).

---

## 3. Le transport : streaming-par-polling (le coeur)

Fichier : `Plugin/owismind/frontend/src/composables/useChatStream.js`

### 3.1 Pourquoi du POLLING et pas du SSE

Documente en-tete des deux cotes (`useChatStream.js:1-9`, `backend.js:48-54`, et surtout
`stream_manager.py:4-16`). DSS place un nginx interne devant chaque backend webapp ; une reponse
longue `text/event-stream` peut etre BUFFERISEE par ce proxy, donc les events arriveraient tous d'un
coup a la fin au lieu d'arriver live. Le pattern retenu (deja en production dans l'app Dash du projet)
est : l'agent tourne dans un THREAD worker de fond, accumule sa progression dans un dict en memoire
process, et le front POLL ce dict sur un intervalle court. Chaque poll est une requete courte que le
proxy ne bufferise jamais.

### 3.2 Constantes de la boucle

`useChatStream.js:13-20` :

```js
const POLL_INTERVAL_MS = 500            // cadence nominale du polling
const MAX_POLL_FAILURES = 5             // tolerance aux blips transitoires du proxy
const MAX_BACKOFF_MS = 5000             // plafond du backoff exponentiel
const TERMINAL_CODES = new Set(['run_not_found', 'invalid_run_id', 'unauthenticated'])
```

### 3.3 La boucle `runChatStream`

`useChatStream.js:43-84`. Signature (objet destructure) :
`{ sessionId, message, agentKey, historyLimit, parentExchangeId, mode, webappLang, screenContext,
target, token, onExchangeId, onRunId }`.

Sequence :

1. **Start** (`useChatStream.js:44`) : `await startChat(...)` -> `{ run_id, exchange_id }`.
2. **Callbacks de reconciliation** (`:45-47`) :
   - `onRunId(runId)` : remonte l'id de run au store pour pouvoir demander un stop (POST `/chat/stop`)
     sur CE run.
   - `onExchangeId(exchange_id)` : remonte le vrai id d'echange backend pour que le store reconcilie
     la cle d'arbre temporaire (`null`) avant que cet echange puisse devenir parent d'un suivant.
3. **Boucle infinie** (`:50-81`), `cursor` initialise a 0, `failures` a 0 :
   - Garde d'annulation AVANT le poll (`:51`) : si `token.cancelled`, on sort sans toucher la version
     stale.
   - `res = await pollChat(runId, cursor)` (`:54`), reset `failures = 0` au succes.
   - **Gestion d'erreur de poll** (`:56-75`) :
     - Re-verifie `token.cancelled` apres le `await` (course "supersede en plein poll" :
       conversation changee / run plus recent demarre).
     - Si le code est **TERMINAL** (`run_not_found` / `invalid_run_id` / `unauthenticated`) : le run
       a disparu (ex. backend redemarre en plein run). On applique un event `error` au target (avec
       `message: 'run_lost'` quand c'est `run_not_found`, sinon le code), MAIS seulement si
       `target.status === 'running'`. C'est traite comme RECUPERABLE, pas un crash (`:61-69`).
     - Sinon : erreur transitoire. `failures += 1`. Si `> MAX_POLL_FAILURES` -> on relance l'erreur
       (echec dur). Sinon backoff exponentiel `min(500 * 2**failures, 5000) ms` puis `continue`
       (`:71-74`).
   - **Application des events** (`:76-79`) : re-garde `token.cancelled` ; puis
     `for (const evt of res.events || []) applyEvent(target, evt)`. On adopte `cursor = res.cursor`
     (le serveur renvoie `len(events)` comme prochain curseur, cf. `stream_manager.py:547`). Si
     `res.done` -> `break`.
   - Sinon `await sleep(POLL_INTERVAL_MS)` (`:80`) avant le prochain tour.
4. **Filet defensif** (`:83`) : si la boucle sort sans event terminal et que `target.status` est
   encore `running`, on applique `{ type: 'run_done' }` pour stopper le spinner.

Le `cursor` est purement cote serveur : c'est le NOMBRE d'events deja consommes. Le serveur renvoie la
tranche `events[cursor:]` et le nouveau curseur `len(events)` (`stream_manager.py:543-548`). Le client
ne fait que reposter ce que le serveur lui a donne -> pas de doublon, pas de perte.

### 3.4 Pourquoi le `token` d'annulation

`token` est un objet `{ cancelled }` (`useChatStream.js:33-37`). L'appelant (le store) le passe a
`true` pour stopper la boucle (navigation, run plus recent, switch de conversation) : un run abandonne
n'est alors plus polle cote client. Important : annuler le POLLING cote client n'arrete PAS le worker
cote backend ; le backend a sa propre detection d'abandon (`ABANDON_AFTER_SECONDS = 30`, cf.
`stream_manager.py:82,144`) pour liberer le slot quand plus personne ne polle.

---

## 4. Application des events au modele reactif (le reducer pur)

Fichier : `Plugin/owismind/frontend/src/composables/timelineModel.js`

`applyEvent(state, evt)` (`timelineModel.js:180-238`) est un reducer PUR (aucun import Vue) qui mute
l'objet d'etat EN PLACE. Le store enveloppe cet etat dans `reactive()` (`chat.js:41-43`), donc les
mutations imbriquees (`timeline.push`, `text +=`) re-rendent live (memoire L020). `useChatStream`
applique chaque event polle via ce reducer (`useChatStream.js:24-26, 77`).

### 4.1 Shape de l'etat (la "version" de reponse)

`createAnswerState` (`timelineModel.js:32-51`) :

```
{ timeline:[item], sql:[{sql,success,row_count}], usage, status:'running'|'done'|'stopped'|'error',
  stopping:false, error:'', showSql:false, exchangeId,
  feedbackRating, feedbackReasons, feedbackComment, _seq:0 }
```

Items de timeline (discrimines par `kind`, chacun avec `id` stable + `seq` d'arrivee) :
- `event` : `{ id, seq, kind:'event', eventKind, toolName, blockId, elapsedSeconds, label, status }`
- `text` : `{ id, seq, kind:'text', text, open }` (`open` = bloc encore en cours de merge de deltas)
- `error` : `{ id, seq, kind:'error', message }`
- `narration` : `{ id, seq, kind:'narration', text }` (TRANSIENT, live-only)

### 4.2 Catalogue des events normalises consommes

`applyEvent` (`timelineModel.js:180-238`) gere chaque `evt.type` et **IGNORE silencieusement** tout
type inconnu (un nouvel event ne peut jamais casser l'UI, `:233-235`) :

| `evt.type` | Effet sur l'etat | Lignes |
|---|---|---|
| `run_started` | `status='running'` ; si `exchangeId != null` -> `state.exchangeId` | 182-185 |
| `agent_event` | `pushEvent` : un item `event` (scelle les events precedents, ferme le texte) | 186-187 |
| `answer_delta` | `appendText(evt.text)` : merge dans le bloc texte ouvert, sinon nouveau bloc | 188-189 |
| `narration` | `pushNarration` : item transient (jamais persiste comme reponse) | 190-193 |
| `generated_sql` | `state.sql.push({sql, success, row_count})` (hors timeline, panneau SQL dedie) | 195-199 |
| `usage_summary` | `state.usage = {promptTokens, completionTokens, totalTokens, estimatedCost}` | 200-207 |
| `final_answer` | `pushFinalAnswer` : ne materialise le texte QUE si rien n'a deja streame | 208-209 |
| `run_done` | scelle events + ferme texte ; `stopping=false` ; running -> `done` | 211-216 |
| `stopped` | idem run_done mais running -> `stopped` (stop user, pas une erreur) | 217-226 |
| `error` | `status='error'`, `error=message`, `pushError` (item error) | 227-232 |

Details fins importants :

- **`sealEvents`** (`:66-70`) : a chaque nouvel item, tout event encore `running` passe `done`. Un
  seul event est jamais affiche "running" (le plus recent) ; tout ce qui suit le finalise.
- **`appendText`** (`:104-122`) : des deltas consecutifs du meme bloc sont fusionnes (`last.text +=`)
  pour eviter fragmentation/doublons. La mutation passe a travers l'element du tableau pour declencher
  le proxy reactif.
- **`pushFinalAnswer`** (`:124-143`) : si du texte a deja streame (`hasStreamedText`), `final_answer`
  ne fait que confirmer/fermer le bloc (pas de doublon). Il ne materialise le texte final QUE pour les
  agents structures qui emettent toute la reponse a la fin (memoire L019).
- **`stopped`** (`:217-226`) : la reponse partielle a deja ete materialisee par le `final_answer`
  precedent (cote worker, `final_answer` est emis AVANT `stopped`, cf. `stream_manager.py:460-469`).
  L'event `stopped` ne fait que marquer la version comme interrompue (pas d'item error, pas de toast
  rouge). Comme `run_done`, il ne flippe qu'une version encore `running` -> un stop tardif/duplique
  est un no-op.

### 4.3 Selecteurs read-only (regroupement d'affichage)

Plusieurs selecteurs PURS lisent la timeline sans la muter (ids stables, donc le gating d'auto-scroll
F8/F13 et la `timelineSignature` ne bougent pas) :
- `answerText(state)` (`:267-273`) : concatenation des blocs `text` (pour le copier).
- `timelineSignature(state)` (`:276-281`) : signature de changement bon marche (drive les re-checks
  d'auto-scroll) = `length|textLen|status`.
- `timelineEvents` / `timelineBodyItems` / `timelineSegments` (`:290-333`) : pour le rendu groupe
  (bloc d'activite collapsable + corps de reponse). La narration est volontairement EXCLUE du corps
  persiste et des segments (`:300-301, 323`).
- `stepStampDiff` / `activitySummary` (`:343-368`) : durees derivees des stamps `elapsedSeconds`
  poses par le backend (`streaming.py:376`, elapsed-since-run-start). Le total = MAX des stamps
  (robuste a l'ordre/au manque), jamais une somme.
- `usageFromRow(row)` (`:247-264`) : reconstruit `usage` depuis une ligne `/conversation` rechargee
  (le chemin live remplit `usage` via l'event `usage_summary`). Renvoie `null` si rien n'a ete stocke
  (run early-stopped ou ligne pre-feature) pour ne pas afficher une ligne d'usage vide/zero.

### 4.4 Cote backend : d'ou viennent ces events normalises

`Plugin/owismind/python-lib/owismind/agents/streaming.py` (`run_agent_streamed`,
`streaming.py:288-477`) consomme le stream brut LLM Mesh et YIELD des dicts JSON-safe a UN `type` :
`agent_event` / `answer_delta` / `generated_sql` / `usage_summary` / `narration` / `artifact` /
`trace`. Le worker (`stream_manager.py:_worker`, `:259-523`) :
- emet `run_started` AU DEBUT (`:291`),
- relaie les events live (cap `MAX_LIVE_EVENTS = 5000`, `:65, 409-411`),
- capte `usage_summary` (persistance) tout en le laissant passer au timeline live (`:375-384`),
- detourne `artifact` et `trace` de la timeline live (persistance seulement, `:385-405`),
- a la fin emet `final_answer` puis l'event TERMINAL : `stopped` (stop user), `error` (timeout/
  abandoned/echec), ou `run_done` (succes) (`:460-503`).

Sur `agent_event`, seules des cles whitelistees de `eventData` passent (`label`, `stepIndex`,
`stepCount`, `agentKey`, `status`), bornees a 300 chars (`streaming.py:74-97`). Le reducer recopie le
`label` (cape 300) pour les libelles humains de timeline (`timelineModel.js:90`). Les payloads
sensibles (agentId / message / instruction / generatedSql) ne touchent JAMAIS la timeline pollee.

> Note de casse : les events utilisent du camelCase (`exchangeId`, `promptTokens`, `rowCount`,
> `sqlIndex`) que le reducer lit tel quel. Le stockage SQL utilise du snake_case (`row_count`,
> `input_tokens`). `usageFromRow` fait le pont snake -> camel pour le rechargement.

---

## 5. Evidence et artifacts : un appel SEPARE `/evidence/meta`

Les donnees de preuve ne transitent PAS par `/chat/poll`. La timeline live ne porte que des `event`,
des deltas de texte, et la LISTE des SQL (texte + success + row_count). Les RESULTATS captures (lignes)
et les SPECS d'artifacts sont persistes cote backend et relus apres coup via `/evidence/meta`.

Cote worker (`stream_manager.py`) : les `generated_sql` envoyes au timeline live restent LEGERS - la
cle `result` (lignes capturees) est retiree de la copie pollee (`stream_manager.py:372-374`) ; elle
n'est lue qu'au point de persistance. Les `artifact` (chart/table/kpi specs) sont accumules (cap
`MAX_ARTIFACTS_ACCUM = 8`, `:69, 385-399`) et persistes en fin de run (`:452-454`), pas pollees.

Stores et modeles :
- `Plugin/owismind/frontend/src/stores/evidence.js` orchestre `fetchEvidenceMeta` / `fetchEvidenceRows`
  / `fetchEvidenceDistinct` avec gardes de staleness (`seq` pour open/close, `rowsSeq` pour les rows -
  meme idiome que le token d'annulation de chat.js, `evidence.js:65-66, 181, 197`).
- `Plugin/owismind/frontend/src/composables/evidenceModel.js` construit le payload `/evidence/rows`
  qui NE PORTE JAMAIS de SQL : les chips editables voyagent en filtres structures `{column, op,
  values}` et les chips agent verrouillees voyagent en `kept_ids` (le backend les re-derive de son SQL
  stocke par id) (`evidenceModel.js:36-69`).

Meta `/evidence/meta` (shape consommee, `evidence.js`) :
- `available:bool` (+ `reason` quand degradee = SQL brut seulement, `backend.js:139`).
- `chips:[{id, column, op, values, editable}]`, `advanced:{present}`, `sources:[{dataset}]`,
  `artifacts:[{kind, title, chart|kpi}]`, `result:{captured, columns, rows}`,
  `drilldown:{available, columns}`.
- L'onglet par defaut est calcule depuis `artifacts` (`_defaultTab`, `evidence.js:84-89`) :
  `chart`/`table` si un artifact existe, sinon `evidence`. Changer d'onglet NE TOUCHE PAS `open`
  (le gate de scroll F13 est gate sur `evidence.open`, pas sur `activeTab`, `evidence.js:366-369`).

Pagination des rows : `_loadRows` (`evidence.js:170-203`) adopte la page ECHOEE par le serveur (le
backend clampe les pages profondes, `MAX_EVIDENCE_PAGE` mirroir cote front `MAX_PAGE = 20`,
`evidence.js:21-23`). Accumulation lazy bornee a `MAX_ROWS = 500` (`:24-28`), infinite-scroll via
`loadMoreRows` borne par `hasMore` (serveur) ET le cap client.

---

## 6. Le flux de STOP ("Stopping...") et la reconciliation cote store

Fichier : `Plugin/owismind/frontend/src/stores/chat.js`

Le store `chat` enveloppe `useChatStream` et possede l'arbre d'echanges. Il detient :
- `activeToken` (`chat.js:72`) : le token d'annulation de la boucle en vol.
- `activeRunId` (`:76`) : l'id de run serveur, pour un stop explicite.
- `stopPending` (`:77`) : couvre la course "user appuie sur stop AVANT que `/chat/start` ait renvoye
  le run_id" (`onRunId` declenche alors le stop des que l'id arrive, `chat.js:279-283`).
- `activeVersion` (`:81`) : la version en vol, pour finaliser le partiel a l'ecran.

`stopGeneration()` (`chat.js:358-368`) :

```js
function stopGeneration() {
  if (!sending.value) return
  if (activeRunId) stopChat(activeRunId).catch(() => {})   // POST /chat/stop
  else stopPending = true                                  // run_id pas encore connu
  if (activeVersion && activeVersion.status === 'running') {
    activeVersion.stopping = true                          // affiche "Stopping..."
  }
}
```

Decision-cle (le POURQUOI, memoire L073/L075) : le stop backend est COOPERATIF. Le stream LLM Mesh
n'a PAS d'API de cancel (cf. `stream_manager.py:131-133`) ; le worker ne peut couper qu'ENTRE deux
chunks streames (un appel LLM / SQL en vol le tient occupe quelques secondes). Plutot que faux-stop
instantane, le front **CONTINUE de poller** et affiche un indicateur "Stopping..." clignotant
(`stopping=true` + spinner) jusqu'a ce que l'event terminal `stopped` arrive et finalise le partiel.
`stopping` est remis a `false` par tout event terminal (`timelineModel.js:214, 225, 229`).

Cote backend, `request_stop` (`stream_manager.py:553-569`) pose `stop_requested=true` (owner-scoped) ;
le worker le voit via `_stop_reason` -> `"stopped"` (`:127-146`), arrete d'iterer, persiste le partiel,
emet `final_answer` PUIS `stopped` (`:463-469`). 404 `run_not_found` si le run est deja fini/inconnu :
le front traite ce 404 comme un no-op benin ("deja fini", `backend.js:96`, `chat.js:361` via `.catch`).

`cancelActive()` (`chat.js:82-88`) annule le token (stoppe le polling) et remet a zero
`activeToken/activeRunId/activeVersion/stopPending`. Appele au debut de tout nouveau run, ainsi qu'a
`newConversation`/`openSession` (switch de conversation).

### 6.1 Cycle de vie d'un envoi : `_runExchange`

`chat.js:232-317`, le seul endroit ou un echange est cree + run :
1. `cancelActive()` puis cree une nouvelle version reactive et un echange (`id:null`, `uid` stable).
2. Construit `screenContext` SEULEMENT si le panneau Evidence est ouvert (`chat.js:263-265`).
3. `await runChatStream({...})` avec `target: version`, `token`, `onExchangeId` (reconcilie `id`),
   `onRunId` (pose `activeRunId`, declenche un `stopPending` differe).
4. Auto-open Evidence (reveal premium) si la reponse a fini PROPREMENT et a produit au moins un SQL
   reussi (`version.sql.some(q => q && q.success)`, `chat.js:290-294`) - jamais sur stopped/error.
5. `catch` : si pas annule -> `version.status='error'` + `errorMsg`. `finally` : `sending=false`,
   bump de la conversation en tete de sidebar (donnees capturees a l'entree du run, `:309-315`).

`canSend` (`chat.js:95-103`) bloque tout envoi tant que le thread a l'ecran n'est pas celui de la
session active (`!sending && !threadLoading && !threadError && ...`) - evite une corruption
cross-conversation (un envoi qui persisterait sous la nouvelle session avec un parent de l'ancienne).

---

## 7. Surface des codes d'erreur (vue d'ensemble)

Codes stables emis par le backend et consommes via `e.message` cote front :

- **`/chat/start`** : `unauthenticated` (401), `<validation>` (400, ex. payload invalide),
  `storage_not_configured` (409), `agent_not_enabled` (404), `rate_limited` (429), `busy` (503),
  `storage_unavailable` (500), `agent_unavailable` (500). (`api/routes.py:203-318`).
- **`/chat/poll`** : `unauthenticated` (401), `invalid_run_id` (400), `run_not_found` (404).
  (`api/routes.py:333-353`). Cote front, `run_not_found` est mappe en `run_lost` quand le run a
  disparu en plein vol (`useChatStream.js:65-67`).
- **`/chat/stop`** : `unauthenticated` (401), `invalid_run_id` (400), `run_not_found` (404 = no-op
  benin). (`api/routes.py:356-384`).
- **Events TERMINAUX d'erreur dans le stream** (pas des codes HTTP) : `run_timeout`, `run_abandoned`
  (bornes de securite, `stream_manager.py:477-482`), `agent_unavailable` (echec interne du run,
  `:511`). Ils arrivent comme `{type:'error', message:...}` et passent par `applyEvent` -> item
  error + `status='error'`.
- **Fallback generique** : `http_<status>` quand le corps n'est pas du JSON (`backend.js:26`).

Cote `useChatStream`, `TERMINAL_CODES = {run_not_found, invalid_run_id, unauthenticated}` distingue
les erreurs de poll IRRECUPERABLES (le run est mort, on sort proprement) des blips transitoires
(retry avec backoff jusqu'a 5 echecs) (`useChatStream.js:19, 61-74`).

---

## 8. Connexions au reste du systeme

- **Securite / whitelist** : le front n'a aucune autorite. `agent_key` opaque, identite serveur via
  cookies same-origin, endpoints admin gates 403, evidence owner-scoped, screen_context sanitize.
  Le frontend ne choisit jamais table/connexion/requete (regle non negociable #3/#4 du projet).
- **Arbre de conversation** : `parent_exchange_id` (front) + reconciliation `onExchangeId` (store)
  alimentent `conversationTree.js` (`buildActivePath`) ; editer/regenerer cree un nouveau SIBLING
  (`chat.js:329-339`).
- **Persistance** : tout est stocke en SQL direct (PostgreSQL via SQLExecutor2). Le worker fait une
  ecriture en deux phases : phase 1 = message user a `/chat/start` (avant le run, dans le thread de
  requete, `api/routes.py:263-272`) ; phase 2 = reponse + SQL + usage + trace + artifacts en fin de
  worker (best-effort, un echec n'avorte jamais le run, `stream_manager.py:413-458`). Tables citees :
  `webapp_chat_v5` (chat_v5), `webapp_artifacts_v1` (artifacts_storage), traces (chat_traces),
  agregats usage (usage). Les noms physiques suivent `f"{PROJECT_KEY}_owismind_{logical}"`.
- **i18n / UI** : `webapp_lang` (front `ui.lang`) -> tie-break de langue serveur ; `mode` (front
  `ui.modelMode`) -> choix du modele par mode cote orchestrateur.
- **Evidence Studio** : `/evidence/meta` (et rows/distinct) est un canal SEPARE du chat, declenche
  apres le run (auto-open premium) ou en re-entrant une conversation (`lastEvidenceExchangeId`,
  `evidenceModel.js:131-140`).

---

## 9. Gotchas et points subtils

1. **Curseur = compteur serveur, pas un timestamp.** Le front reposte aveuglement `res.cursor`. Toute
   tentative de calculer le curseur cote client casserait le contrat (`stream_manager.py:547`).
2. **Annuler le polling cote client n'arrete pas le worker.** Le backend a sa propre detection
   d'abandon (`ABANDON_AFTER_SECONDS = 30`) via le heartbeat `last_poll_at` mis a jour a chaque poll
   (`stream_manager.py:540-541`). Si le front cesse de poller sans stop explicite, le worker coupe au
   bout de ~30 s pour liberer le slot (et arreter de bruler des tokens).
3. **Le filet `run_done` defensif** (`useChatStream.js:83`) ne s'applique que si `status==='running'` -
   pour ne pas ecraser un terminal `stopped`/`error` deja recu.
4. **`final_answer` n'ajoute du texte que si rien n'a streame.** Pour les agents qui streament des
   deltas (cas normal), `final_answer` ne fait que fermer le bloc - jamais de duplication
   (`timelineModel.js:124-143`).
5. **`stopping` vs `stopped`** : `stopping` est un drapeau LOCAL optimiste (l'UI "Stopping...") pose
   par le store ; `stopped` est l'event TERMINAL serveur qui finalise. Les deux sont distincts ; tout
   terminal remet `stopping=false`.
6. **Le merge mid-stream/footer du SQL** (`streaming.py:428-458`) : un `generated_sql` peut etre emis
   mid-stream (relay AGENT_DONE) puis ENRICHI par le footer (meme `sqlIndex`) ; le worker met a jour
   l'item stocke en place sans le re-pousser dans la timeline live (`stream_manager.py:359-374`). Le
   front, lui, ne fait que `state.sql.push` a chaque `generated_sql` polle - mais la copie pollee a
   deja ete dedupliquee/allegee cote worker.
7. **Types d'event inconnus ignores** des deux cotes (`timelineModel.js:233-235`, chunk inconnu cote
   `streaming.py:408-419`) : ajout d'un nouveau type d'event = retro-compatible.
8. **`narration` est transient** : jamais dans le corps persiste ni dans `answerText` (copie), seulement
   live (`timelineModel.js:296-301`).

---

## 10. Incertitudes / en-cours (a marquer explicitement)

- **Edition LIVE en cours** : un autre ingenieur edite le repo (surtout `dataiku-agents/`). Le present
  pack decrit le code lu le 2026-06-18 sous `Plugin/owismind/frontend/src` et `python-lib/owismind`.
  Les agents LangGraph (qui PRODUISENT les events bruts cote `streaming.py`) peuvent evoluer ; les
  shapes d'events normalises decrits ici sont le contrat backend->front, plus stable.
- **`result` dans `/evidence/meta`** : la cle `result.rows` (resultat capture) est qualifiee de
  best-effort cote backend (`streaming.py:240-264`, "rows key is not confirmed on this instance"). La
  capture peut etre absente (no-capture honnete) sans casser le rendu.
- **Versions backend** : observe Python 3.9.23 / Flask (cf. regles projet). Les Code Agents tournent en
  env 3.11 (LangGraph). Non re-verifie sur l'instance dans cette session (lecture seule).
- **`final_answer` / `run_started` exposent `exchangeId`** dans le stream (worker, `stream_manager.py:
  291, 461`) ; le reducer ne lit `exchangeId` que sur `run_started` (`timelineModel.js:184`). Le store,
  lui, reconcilie l'id via `onExchangeId` (retour direct de `/chat/start`), pas via l'event - les deux
  chemins convergent mais le chemin `/chat/start` est l'autorite.
