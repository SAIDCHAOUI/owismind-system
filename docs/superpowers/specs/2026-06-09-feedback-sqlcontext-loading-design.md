# Design - Feedback par message + SQL dans le contexte agent + chargement sans flash

> Date : 2026-06-09 (run 2) · Projet : OWIsMind (plugin Dataiku DSS, Vue 3 + Flask).
> Statut : **validé par l'utilisateur**. Peaufinage de l'existant avant Evidence Studio. Prime sur les guides `docs/cadrage/`.

## Contexte
Suite de la session multi-tours + lazy sidebar (L030). 3 finitions demandées. Faits établis (lecture du code) :
- `MessageAgent.vue` a déjà les pouces 👍/👎 mais **UI-only en mémoire** (toggle local `liked`/`disliked`, perdu au reload).
- La maquette avait un **popup feedback par message** (`{reasons:Set, suggestion}`) ; les clés i18n existent déjà dans `messages.json` :
  `msg.feedback_eyebrow/title/reasons_label/suggestion_label/suggestion_placeholder/submit/sent`, `msg.cancel`, `msg.like/dislike`,
  et 6 raisons `fb.reason.incomplete/incorrect/off_topic/too_long/too_short/tone`.
- Le **flash « nouvelle conversation »** au changement de conv vient de `chat.js openSession` qui fait `messages.value=[]` AVANT le fetch
  (→ `hasMessages` faux → `ChatEmpty`).
- `chat_v2` a déjà `generated_sql` (TEXT JSON) ; l'answer-state (`timelineModel.createAnswerState`) a déjà `exchangeId` ; `applyEvent` le pose sur `run_started`.

## Décisions actées (user)
1. **Feedback DANS la table chat** (pas de table dédiée). On crée **`webapp_chat_v3` = schéma `chat_v2` + colonnes feedback** ; table **vide au départ** (phase de test, données v2 jetables). Même idiome que v1→v2 (L018) : nouvelle table `_vN`, l'ancienne abandonnée **inerte** (jamais droppée).
2. **Popup au pouce-bas = raisons (multi) + commentaire**, raisons = **3 + « Autre »** : `incorrect` · `incomplete` · `off_topic` · **`other` (nouveau)**.
3. 👎 enregistré **au submit** (pas au clic) → toujours du contexte ; **re-clic sur un pouce actif = annule** (rating→null) ; SQL annexé **borné** ; overlay de chargement **garde l'écran courant**.

---

## Feature 1 - Feedback par message (persisté dans `chat_v3`)

### Backend
- **`migrations.py`** : `CHAT_V2_LOGICAL`→**`CHAT_V3_LOGICAL = "webapp_chat_v3"`** ; DDL = colonnes v2 **+** `feedback_rating SMALLINT`, `feedback_reasons TEXT` (JSON liste), `feedback_comment TEXT`, `feedback_at TIMESTAMP` (toutes nullable). Mêmes index (`uc_idx` `(user_id, created_at DESC)`, `usc_idx` `(user_id, session_id, created_at DESC)`). `ensure_chat_v2_table`→`ensure_chat_v3_table`.
- **Renommer `storage/chat_v2.py`→`storage/chat_v3.py`** (idiome v1→v2) ; mettre à jour tous les importeurs (`api/routes.py`, `agents/stream_manager.py`). `_COLUMNS` **+= `feedback_rating, feedback_reasons, feedback_comment`** → les reads (`history_for_user`, `messages_for_session`) renvoient le feedback ; décoder `feedback_reasons` via `parse_json_list`. `save_user_message`/`save_assistant_message` **inchangés** (écrivent dans v3 via le logical ; feedback posé séparément).
- **`chat_v3.save_feedback(user_id, exchange_id, rating, reasons, comment)`** : `UPDATE {v3} SET feedback_rating={rating}, feedback_reasons={reasons_json}, feedback_comment={comment}, feedback_at=now() WHERE exchange_id={ex} AND user_id={user}` - **owner-scopé** (WHERE user_id → on ne note que SES échanges), valeurs via `nullable_value`/`sql_value`, commentaire **borné** (`MAX_PERSISTED_TEXT_CHARS`), COMMIT. `rating` ∈ {0,1,NULL}.
- **`security/validation.py` `validate_feedback(payload)`** : `exchange_id` non-vide ≤128 ; `rating` ∈ {0,1,None} (sinon 400) ; `reasons` = liste filtrée sur `ALLOWED_FEEDBACK_REASONS={"incorrect","incomplete","off_topic","other"}` (inconnus ignorés, cap ≤8) ; `comment` str borné (≤2000). Ne lève que sur payload structurellement invalide.
- **`api/routes.py` `POST /chat/feedback`** : identité (401) + `is_configured` (409) + `validate_feedback` (400) + `ensure_chat_v3_table()` + `chat_v3.save_feedback(...)` → `{status:"ok"}`. Erreurs au format existant (`{"status":"error","error":code}`).

### Frontend
- **`services/backend.js`** : `submitFeedback(exchangeId, rating, reasons, comment)` → `POST /chat/feedback`.
- **`composables/timelineModel.js`** : `createAnswerState` += `feedbackRating:null, feedbackReasons:[], feedbackComment:''` (données portées par la version ; `applyEvent` n'y touche pas). `exchangeId` déjà présent.
- **`stores/chat.js` `rowsToMessages`** : passer `exchangeId:r.exchange_id`, `feedbackRating` (0|1|null), `feedbackReasons` (liste), `feedbackComment` dans le `over` de `newVersion`.
- **`components/chat/MessageAgent.vue`** : remplacer `liked`/`disliked` locaux par des computed sur `v.feedbackRating`. **👍** : si rating===1 → clear (`submitFeedback(ex,null)`, rating=null) ; sinon `submitFeedback(ex,1)`, rating=1 (reasons/comment vidés). **👎** : si rating===0 → clear ; sinon **ouvrir `FeedbackModal`** (préremplie si déjà 0) → submit → `submitFeedback(ex,0,reasons,comment)` + maj version + toast `msg.feedback_sent`. No-op si pas d'`exchangeId`.
- **`components/chat/FeedbackModal.vue`** (nouveau) : primitive `Modal` ; titre `msg.feedback_title`, eyebrow `msg.feedback_eyebrow`, label raisons `msg.feedback_reasons_label`, chips multi-select (4 raisons), commentaire `msg.feedback_suggestion_label`/`_placeholder`, boutons `msg.feedback_submit`/`msg.cancel`. Émet `submit(reasons, comment)` / `cancel`.
- **`i18n/extra.js`** : ajouter `fb.reason.other` (fr « Autre » / en « Other »). Le reste réutilise `messages.json` (pristine).

---

## Feature 2 - `generated_sql` inclus dans le contexte agent
- **`agents/context.py` `flatten_exchanges_to_messages`** : pour le tour assistant, si `row["generated_sql"]` (liste `{sql,...}`) présent, **annexer un bloc SQL borné** au contenu : `…\n\n[SQL généré pour cette réponse :\n<sql1>\n<sql2>]` (cap `MAX_SQL_CONTEXT_CHARS`, ex. 4000). Nouvelle fn pure `_format_sql_context(generated_sql)` (→ "" si vide). Param optionnel ; rows sans `generated_sql` → inchangé (tests existants OK).
- **`storage/chat_v3.history_messages_for_session`** : ajouter `generated_sql` aux colonnes lues + le décoder (`parse_json_list`) avant `flatten_exchanges_to_messages` → l'agent voit le SQL des tours précédents.

---

## Feature 3 - Chargement sans flash + posture lazy
- **`stores/chat.js openSession`** : **supprimer `messages.value = []`** au début → l'écran courant reste affiché pendant le fetch ; sur succès, remplacer `messages.value`. (`newConversation` continue de vider → écran vide voulu.) Garde anti-écrasement (`activeSessionId`) conservée.
- **`views/ChatView.vue`** : overlay de chargement **centré** (spinner) quand `chat.threadLoading`, par-dessus le contenu courant (thread **ou** écran vide) ; `.chat` en `position:relative`. Retirer la ligne texte `chat.loadingThread` de l'`empty-stage` (garder `threadError`). Spinner CSS léger.
- **Lazy/RAM** : déjà en place (routes en chunks lazy ; sidebar noms-seuls paginée ; **une seule conversation en mémoire** car `openSession` remplace). On **confirme** la posture ; pas de virtualisation du fil (hors-scope sauf demande).

## Sûreté
- `save_feedback` = `UPDATE … WHERE exchange_id AND user_id` (**owner-scopé**, paramétré, commentaire borné, raisons **whitelistées serveur**). Aucun nouveau read non borné. `chat_v3` = même posture que v2 (CREATE IF NOT EXISTS, INSERT/UPDATE WHERE pk/user, COMMIT, SELECT bornés). v2 **abandonnée inerte** (jamais droppée). SQL-contexte borné. Trace dataset + write path = mêmes patterns, juste sur v3.

## Tests (NO INSTALL)
- **`unittest`** : `validate_feedback` (rating 0/1/None, raisons whitelist+cap, commentaire borné, exchange_id) ; `_format_sql_context` + `flatten_exchanges_to_messages` avec SQL annexé (cap, vide, présent).
- **`node:test`** : `createAnswerState` défauts feedback ; (option) helper pur de toggle raisons s'il est extrait.
- Composants (MessageAgent/FeedbackModal/ChatView overlay) vérifiés par `vite build` (temp) + revue.

## Hors-scope (différé)
- Vue admin du feedback (donnée stockée, surfaçable plus tard). Evidence Studio. Virtualisation du fil.
- Migration des données `chat_v2` (jetables, phase test).
