# Design - Édition de prompt + branches (arbre de conversation) · Feedback ⋯ · Agent persistant

> Date : 2026-06-09 (run 4) · OWIsMind (plugin Dataiku DSS, Vue 3 + Flask). Validé par l'utilisateur. Prime sur `docs/cadrage/`.

## Contexte (lecture du code)
- `MessageUser.vue` = bulle simple (pas de hover). Clés i18n `msg.edit/edit_hint/edit_placeholder` existent (maquette) mais l'édition→branche n'a jamais été portée.
- Versions actuelles (`regenerate`) = **UI-only en mémoire** (perdu au reload), arbre inexistant : `chat_v3` = 1 ligne = 1 échange linéaire.
- `AgentPicker` bind `session.selectedAgentKey` ; `selectAgent` en mémoire (non persistant) ; `chat_v3` stocke déjà `agent_key` par échange.
- Multi-tours (L030) : `history_messages_for_session(user_id, session_id, exclude, n)` = tous les échanges de la session. À remplacer par la **chaîne d'ancêtres** pour le branching.

## Décisions actées (user)
1. **Branches stockées dans une nouvelle table `webapp_chat_v4` = v3 + `parent_exchange_id`** (idiome v1→v2→v3 ; v3 abandonnée inerte ; vide au départ, données test v3 jetables).
2. **Modèle de versions « entre-deux solide »** : navigation **au niveau du tour**, **flèches sur le footer de la réponse (comme aujourd'hui)** ; la **bulle utilisateur reflète le prompt de la version active**. Éditer (survol prompt) ET Régénérer (réponse) créent une **version persistée** (échange frère, même parent).
3. **Reload = dernière branche affichée + flèches navigables** sur toutes les versions persistées (pas de stockage d'état de navigation par nœud).
4. **Feedback** : 👎 = note 0 **immédiate** + **popup** (raisons+commentaire optionnels) ; 👍 = note 1 immédiate, **pas de popup auto** ; menu **⋯** « Donner un retour détaillé » (popup adaptée, dispo 👍 et 👎) → on peut toujours mettre juste le pouce.
5. **Agent persistant par conversation** (dérivé du dernier échange + dernier-utilisé en localStorage).

---

## Feature 1 - Arbre de conversation (édition de prompt + branches)

### Modèle de données - `chat_v4`
`webapp_chat_v4` = colonnes `chat_v3` (incl. feedback) **+ `parent_exchange_id TEXT`** (nullable ; NULL = 1er tour de la session). Chaque envoi enregistre `parent_exchange_id` = l'échange actif qu'il prolonge. Rename `storage/chat_v3.py`→`chat_v4.py`, `CHAT_V3_LOGICAL`→`CHAT_V4_LOGICAL="webapp_chat_v4"`, `ensure_chat_v3_table`→`ensure_chat_v4_table`. v3 abandonnée inerte. Index inchangés (lookup ancêtres = par PK `exchange_id`).

### Contexte agent = chaîne d'ancêtres
`/chat/start` reçoit `parent_exchange_id` (optionnel, borné ≤128). Le worker assemble le contexte en **remontant les parents** depuis `parent_exchange_id` (CTE récursive **user-scopée + bornée en profondeur + LIMIT**), oldest→newest, aplati, trimé à `history_limit` messages (+ SQL annexé, L031). Pour une conv **linéaire**, c'est identique à L030. `parent_exchange_id=NULL` → contexte vide (1er tour). Remplace `history_messages_for_session` par **`history_messages_for_chain(user_id, parent_exchange_id, max_messages)`** ; nouveau builder pur **`build_ancestor_chain_query`**.

### Reconstruction (reload) + versions
`/conversation` renvoie `parent_exchange_id` par ligne (via `_COLUMNS`). Le front construit l'**arbre** (regroupement par `parent_exchange_id`), affiche le **chemin actif** = à chaque nœud l'**enfant le plus récent** (par `created_at`), sauf override de navigation. Un **tour** = un nœud du chemin actif ; ses **versions** = ses **frères** (mêmes parent). Flèches N/M (footer réponse) = naviguer les frères → l'override re-walk la suite (latest en dessous). Édition/régénération = nouvel échange frère (même `parent_exchange_id` que le tour) → devient le plus récent → actif.

### UI
- `MessageUser.vue` : au **survol**, boutons **Copier** + **Éditer** ; Éditer → textarea inline (`msg.edit_placeholder`, Envoyer/Annuler) → envoie un nouvel échange frère (parent = parent du tour) → branche.
- `MessageAgent.vue` : flèches de version restent au footer mais pilotent le **tour** (prompt+réponse+suite).
- Refactor front : `chat.js` `messages[]` (plat) → **`exchanges`** (tous les échanges chargés/live `{id, parentId, userText, version(reactive), createdAt}`) + **`turns`** computed (chemin actif). Module **pur** `stores/conversationTree.js` (`buildActivePath`) testé `node:test`.

### Envois (parent)
- Envoi normal : `parent = dernier tour.exchange.id` (ou NULL si conv vide).
- Édition/régénération du tour K : `parent = K.exchange.parentId`.
- `id` d'un échange live = `version.exchangeId` posé sur `run_started` (avant qu'il puisse avoir un enfant). Default actif = plus récent (`createdAt`), donc un nouvel échange est actif sans override.

---

## Feature 2 - Feedback : popup au 👎, ⋯ pour 👍
- **👎** : `submitFeedback(ex, 0, [], '')` **immédiat** (colorie rouge) **+ ouvre la popup** (raisons + commentaire **optionnels**) ; Envoyer → `submitFeedback(ex, 0, reasons, comment)` ; fermer/annuler → garde juste la note 0.
- **👍** : `submitFeedback(ex, 1)` immédiat (colorie) ; **pas de popup auto**.
- **⋯** (menu, primitive `Menu`) à côté des pouces : item « Donner un retour détaillé » → ouvre la popup pour la note **courante** (1 ou 0). Dispo après 👍 et 👎. Extensible (autres items plus tard).
- **Popup adaptative** (`FeedbackModal` prop `rating`) : note 0 → titre `msg.feedback_title` + **raisons** + commentaire ; note 1 → titre **`msg.feedback_title_positive`** (nouveau) + **commentaire seul** (pas de raisons négatives). Submit → `submitFeedback(ex, rating, reasons, comment)` (reasons=[] pour le positif).
- Toggle inchangé : re-clic sur pouce actif = annule (note null). i18n nouveaux : `msg.feedback_title_positive`, `msg.feedback_suggestion_label_positive`, `msg.more_options` (⋯ titre), `msg.give_feedback` (item menu).

---

## Feature 3 - Agent persistant par conversation
- `session.selectAgent(key)` : set `selectedAgentKey` **+ persiste** `owismind.lastAgentKey` (localStorage).
- `chat.openSession` : après chargement, si le **dernier échange** a un `agent_key` encore présent dans `session.agents` → `session.setSelectedAgent(thatKey)` ; sinon défaut. (rows `/conversation` incluent `agent_key`.)
- `newConversation` : `selectedAgentKey` = dernier-utilisé (localStorage) s'il est activé, sinon 1er agent.
- `loadAgents` : défaut initial = dernier-utilisé (localStorage) s'il est dans la liste, sinon 1er. Helper pur `pickDefaultAgent(agents, lastKey)` testable.

---

## Sûreté
- `parent_exchange_id` paramétré (`nullable_value`), borné ≤128, **user-scopé** dans la CTE (les 2 branches du UNION filtrent `user_id`) + **profondeur bornée** (`MAX_CHAIN_DEPTH`) + `LIMIT` → pas de boucle/scan. DDL additif (v4 `CREATE IF NOT EXISTS`). Write path feedback inchangé. Aucune nouvelle écriture hors `parent_exchange_id` (déjà via `save_user_message`). Rien supprimé en BDD (branches = échanges additionnels). Lectures bornées + user-scopées.

## Tests (NO INSTALL)
- **unittest** : `build_ancestor_chain_query` (user-scopé 2 clauses, profondeur+LIMIT bornés, pas d'OR/UNION élargissant hors keyset), `validate_*` (parent_exchange_id), feedback inchangé.
- **node:test** : `conversationTree.buildActivePath` (chemin actif latest, override de version, branches, frères, versionIdx), `pickDefaultAgent`.
- Composants (MessageUser édition, MessageAgent versions/⋯, FeedbackModal adaptatif, ChatThread tours) : `vite build` (temp) + revue + DSS.

## Hors-scope
- État de navigation persisté par nœud (on affiche la dernière branche). Versioning 2-niveaux strict ChatGPT. Suppression réelle d'échanges. Evidence Studio.
