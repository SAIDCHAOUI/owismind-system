# Spec - Arrêt de la génération en cours (« stop generation »)

> Date : 2026-06-09 · Statut : **validé (design)** · Suite : plan d'implémentation (writing-plans).
> Source de vérité : ce repo + `memory/`. Code & identifiants en anglais ; prose en français.

## 1. Objectif

Permettre à l'utilisateur d'**arrêter la génération d'une réponse en cours**. Cas d'usage :
j'envoie un message, je vois défiler les étapes (event-kinds), je réalise que mon prompt est
mauvais → je **stoppe** au lieu d'attendre la fin, puis je reformule.

Comportement attendu :
1. Le prompt envoyé est **déjà stocké** (phase 1 du write `/chat/start`, inchangé).
2. À l'arrêt, la réponse **partielle est stockée telle quelle** (éventuellement vide).
3. Le tour arrêté est un **échange normal** : le message suivant est un nouvel échange ; éditer
   le prompt suit le **schéma de branches actuel** (`parent_exchange_id`).

## 2. Décisions actées (utilisateur)

- **D1 - Contexte du tour arrêté** : un tour arrêté est **inclus comme un tour normal** dans la
  chaîne d'ancêtres envoyée à l'agent au tour suivant. Pour l'exclure, l'utilisateur édite le
  prompt → branche (mécanisme existant). Pas de règle d'exclusion spécifique.
- **D2 - Rendu** : la réponse partielle s'affiche telle quelle suivie d'un marqueur discret
  « ⏹ Génération arrêtée » ; si **aucun texte** n'a encore été produit (seules des étapes
  event-kind sont passées), la bulle agent affiche le placeholder « Réponse interrompue »
  (jamais de bulle vide).

## 3. Constat technique (doc Dataiku officielle)

L'API LLM Mesh expose `completion.execute_streamed()` qui renvoie **un itérateur** de chunks
(`DSSLLMStreamedCompletionChunk` puis `DSSLLMStreamedCompletionFooter`). Le pattern documenté
est uniquement `for chunk in completion.execute_streamed(): …`. **Aucune méthode officielle
`stop()`/`cancel()`/`close()`/`abort()`** n'existe sur ce flux.

⇒ La façon supportée d'arrêter une génération est de **cesser d'itérer** (sortir de la boucle) :
abandonner l'itérateur libère la connexion ; les tokens d'après l'arrêt sont ignorés (ni
affichés, ni stockés). C'est exactement le mécanisme **déjà** présent dans
`agents/stream_manager.py` pour les cas `timeout`/`abandoned` (`break` entre deux chunks +
persistance du partiel via `save_assistant_message`).

Sources officielles : developer.dataiku.com `/latest/api-reference/python/llm-mesh.html`,
`/latest/concepts-and-examples/agents.html` ; doc.dataiku.com `/dss/latest/generative-ai/`.

## 4. Approche

**A (retenue)** - Arrêt **explicite et immédiat** : nouvel endpoint `POST /chat/stop` qui pose un
flag coopératif owner-scopé dans `stream_manager` ; le worker le voit entre deux chunks, `break`,
persiste le partiel (existant) et émet un event terminal `stopped`.

**B (rejetée)** - Aucun changement backend, s'appuyer sur l'auto-coupure `abandoned` (30 s sans
poll). Refusée : l'agent tourne (et facture) jusqu'à 30 s après le clic ; le partiel stocké ≠ ce
qui était à l'écran ; ressenti non réactif.

## 5. Conception détaillée

### 5.1 Backend - `agents/stream_manager.py`
- `start_run` : initialiser `"stop_requested": False` dans le dict du run.
- `request_stop(run_id, user_id) -> bool` : sous `_LOCK`, **owner-scopé** (`state["user_id"] ==
  user_id`) ; pose `state["stop_requested"] = True` ; renvoie `True` si trouvé+possédé, sinon
  `False`. Idempotent (re-stop = no-op). Tolère un run déjà terminé (flag sans effet).
- `_stop_reason(run_id, started_at)` : vérifier `stop_requested` **en premier** (sous le lock déjà
  pris pour `last_poll_at`) → renvoyer `"stopped"` avant les bornes `timeout`/`abandoned`.
- Worker (`_worker`) : à la sortie de boucle, distinguer le motif :
  - `stop_reason == "stopped"` (arrêt utilisateur) → émettre `final_answer` (le partiel) **puis un
    nouvel event terminal `{"type": "stopped", "exchangeId": …}`** ; **ne pas** poser
    `state["error"]` (ce n'est pas une erreur).
  - `timeout` / `abandoned` → comportement **inchangé** (`final_answer` + `error` `run_<reason>`).
  - La persistance phase 2 (`save_assistant_message(exchange_id, partial, sql or None)` +
    `save_trace`) est **déjà** exécutée pour tout arrêt - inchangée.

### 5.2 Backend - `api/routes.py`
- `POST /chat/stop` :
  - `resolve_identity` (401 si échec).
  - Valider `run_id` (str non vide, borné - **réutiliser la garde de longueur de `/chat/poll`**).
  - `ok = stream_manager.request_stop(run_id, identity["user_id"])` → `200 {"status":"ok"}` si
    `True`, sinon `404 {"status":"error","error":"run_not_found"}` (même opacité que `/chat/poll`).
  - Ajouter `/chat/stop` à l'inventaire des routes dans le docstring du module.

### 5.3 Frontend
- `services/backend.js` : `stopChat(runId)` → `POST /owismind-api/chat/stop { run_id }`.
- `composables/useChatStream.js` : ajouter un callback `onRunId(runId)` appelé juste après
  `startChat`. **La boucle de polling continue** après un stop (pour rendre `final_answer` +
  `stopped`), puis s'arrête sur `done`. Le `token.cancelled` reste réservé à la navigation/supersede
  (inchangé).
- `stores/chat.js` :
  - `activeRunId` (let, miroir d'`activeToken`) + `stopPending` (bool).
  - `_runExchange` : passer `onRunId: (id) => { activeRunId = id; if (stopPending) { stopPending=false; stopChat(id)… } }` ; reset `activeRunId=null`/`stopPending=false` en `finally`.
  - `stopGeneration()` : si `!sending` → no-op ; si `activeRunId` → `stopChat(activeRunId)`
    best-effort (catch et **ignorer** `run_not_found` = run déjà fini) ; sinon `stopPending = true`
    (course : stop cliqué avant la résolution de `startChat`). Exposer dans le store.
- `composables/timelineModel.js` : nouveau `case 'stopped'` dans `applyEvent` → `sealEvents` +
  `closeText` + `if (state.status === 'running') state.status = 'stopped'`. (Pur, testable.)
- `components/chat/PromptBar.vue` : pendant `chat.sending`, remplacer le bouton **send** (↑) par un
  bouton **stop** (■, `:title="t('prompt.stop')"`) appelant `chat.stopGeneration()` (toujours
  cliquable pendant l'envoi). Ajouter une icône `stop` (carré plein) dans `components/ui/icons.js`
  si absente.
- `components/chat/MessageAgent.vue` :
  - si `version.status === 'stopped'` → marqueur discret « ⏹ {{ t('chat.stopped') }} » sous la
    réponse ;
  - si l'état est **terminal** (`done`/`stopped`) **et** la timeline ne contient aucun bloc texte →
    placeholder « {{ t('chat.interrupted_empty') }} » (couvre aussi le rechargement d'un partiel
    vide, sans dépendre du statut live).
- `i18n/extra.js` : clés **fr/en** `prompt.stop` (« Arrêter »/« Stop »), `chat.stopped`
  (« Génération arrêtée »/« Generation stopped »), `chat.interrupted_empty` (« Réponse
  interrompue »/« Response interrupted »). (`messages.json` reste pristine - F6/L023.)

### 5.4 Données / persistance
- **Aucun changement de schéma** (idiome `_vN`, pas d'ALTER → pas de table v5 pour un marqueur).
- Le partiel est stocké dans `chat_v4.assistant_text` existant via le chemin d'arrêt déjà présent.
- Le marqueur « interrompu » est **live-only**. Au rechargement (`/conversation`) : un
  `assistant_text` non vide s'affiche tel quel (pas de marqueur) ; un `assistant_text` vide rend le
  placeholder « Réponse interrompue » (règle de rendu sur texte vide, pas sur un flag persisté).

## 6. Flux (envoi → étapes → stop)

1. `send` → `_runExchange` : exchange créé (prompt déjà persisté par `/chat/start`),
   `sending=true`, `onRunId` mémorise `activeRunId`, polling démarre.
2. L'utilisateur clique **■** → `stopGeneration()` → `POST /chat/stop`.
3. Worker : `_stop_reason` renvoie `"stopped"` au prochain chunk → `break` → persiste le partiel →
   émet `final_answer` + `stopped` → marque `done`.
4. Le polling rend `final_answer` (texte partiel) puis `stopped` (`status='stopped'`) puis voit
   `done` → boucle finie → `sending=false`. UI : marqueur « ⏹ Génération arrêtée » (ou placeholder
   si vide).
5. Message suivant = nouvel échange (enfant du dernier tour). Édition du prompt = nouvelle branche.

## 7. Cas limites

- **Stop avant que `run_id` soit connu** (fenêtre avant résolution de `startChat`) → `stopPending`,
  déclenché par `onRunId`.
- **Stop après fin du run** (course) → `stopChat` → `404 run_not_found` → ignoré (réponse déjà
  complète à l'écran).
- **Stop sans aucun texte** → partiel vide persisté → placeholder « Réponse interrompue ».
- **Owner-scope** : `request_stop` refuse un `run_id` d'un autre utilisateur (404, pas de fuite).
- **Sûreté instance** : un arrêt **libère plus tôt** thread/slot/connexion LLM Mesh ; aucun nouveau
  travail non borné ; `/chat/stop` est une écriture O(1) en mémoire sous lock.

## 8. Tests

- `frontend/test/timeline.test.js` : cas `stopped` → `status` passe à `stopped` ; n'écrase pas un
  texte déjà streamé ; cas « stopped sans texte » (placeholder côté composant). **Pur, node:test.**
- Backend : test DSS-free de `request_stop` (owner match/mismatch/inconnu) + `_stop_reason`
  renvoyant `"stopped"` quand le flag est posé, via un stub minimal `dataiku`/`pandas` (avance
  TEST-01 pour `stream_manager`). Si le stub s'avère fragile, repli sur validation DSS.
- **Preuve réelle = DSS** : envoi → étapes visibles → stop → partiel stocké → message suivant =
  nouvel échange → édition du prompt = branche.

## 9. Périmètre (fichiers touchés)

Backend : `agents/stream_manager.py`, `api/routes.py`.
Frontend : `services/backend.js`, `composables/useChatStream.js`, `stores/chat.js`,
`composables/timelineModel.js`, `components/chat/PromptBar.vue`, `components/chat/MessageAgent.vue`,
`components/ui/icons.js` (si icône absente), `i18n/extra.js`.
Tests : `frontend/test/timeline.test.js` (+ test backend `stream_manager` si stub).
Finalisation : `/build-plugin` (rebuild + recâblage `body.html` via Write - F10/L033) puis
`/package-plugin` (zip propre) ; re-test en DSS.

## 10. Hors périmètre (YAGNI)

- Pas de persistance d'un flag « interrompu » (donc pas de table v5).
- Pas d'annulation côté provider au-delà de l'arrêt d'itération (non exposé par Dataiku).
- Pas de raccourci clavier (Échap) pour cette itération (peut s'ajouter trivialement plus tard).
- Pas de reprise/continuation d'une réponse interrompue.
