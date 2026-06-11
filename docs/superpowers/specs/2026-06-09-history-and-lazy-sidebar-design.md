# Design — Historique multi-tours vers l'agent + Sidebar lazy-loading

> Date : 2026-06-09 · Projet : OWIsMind (plugin Dataiku DSS, Vue 3 + Flask).
> Statut : **validé par l'utilisateur** (design approuvé, `/history` backend conservé intact).
> Référence : ce spec prime sur les guides `cadrage/` ; il sera consigné en mémoire (`LESSONS.md`) après validation DSS.

## Contexte & constat (vérifié dans le code + doc Dataiku officielle + ancien Dash)

- **Aujourd'hui**, `/chat/start` n'envoie à l'agent **que le message courant** : `get_llm(agent_id).new_completion().with_message(message).execute_streamed()` (`agents/streaming.py:163-172`). **Aucun historique, aucun rôle**, `session_id` non transmis jusqu'à l'agent.
- La BDD `chat_v2` stocke pourtant tout : 1 ligne = 1 échange (`user_text` + `assistant_text`), lié par `session_id`. Colonnes : `exchange_id` (PK), `session_id`, `user_id`, `user_display_name`, `user_groups`, `user_text`, `assistant_text`, `generated_sql`, `agent_key`, `created_at`, `answered_at` (`migrations.py:41-55`). **Pas de colonne `role`.**
- **Doc Dataiku officielle** (`developer.dataiku.com` + `doc.dataiku.com` uniquement) : multi-tours = `with_message(message, role='user')` appelé **plusieurs fois** (rôles `system`/`user`/`assistant`/`tool`), puis `execute()` / `execute_streamed()`. Pour un agent conversationnel : *« iterate over `query['messages']` and replay each into the completion to provide the whole context »*. **Aucune limite de contexte documentée.**
- **Ancien Dash de prod** (même instance, référence prouvée) : vrai multi-tours (`with_message(content, role)` par message), cap **10 derniers messages**, préfixe `[User: {nom} | The NOW Date is: {date}]` sur chaque message `user` (date = `datetime.now()`). **Pas de prompt système** (l'agent est déjà prompté à sa création).
- **Identité** : DSS ne renvoie que le **login** (`authIdentifier`, ex. `said.chaoui`) — pas de `displayName`/`fullName` (L011). **Les logins suivent `prenom.nom` pour tous** (confirmé user) → dériver « Prénom Nom » est fiable.
- **Sidebar actuelle** : un seul `GET /history?max_conversations=N` ramène **tous les corps de message** des N sessions récentes ; la liste ET le contenu sont dérivés client-side de ce blob mémoire ; cliquer ne refetch pas (filtre mémoire). Pas d'endpoint « noms seuls », pas de pagination.

## Décisions actées (réponses utilisateur)

1. **Format prompt** = **multi-tours natif** (rôles `user`/`assistant`), pas un bloc texte à sections.
2. **Assemblage** = **backend** (SQL serveur ; le front ne falsifie pas l'historique).
3. **Infos utilisateur (nom + date)** = injectées **à chaque tour** (préfixe sur le message courant ; date serveur courante).
4. **Nom** = **dérivé du login** (`said.chaoui → Said Chaoui`, title-case par segment ; login `prenom.nom` garanti dans l'org).
5. **`/history` backend** = **conservé intact** (validé DSS, sûr), simplement **plus appelé** par le front.
6. **« 20 messages »** = **20 messages individuels** (user/assistant), ≈10 échanges ; borne **[10,50] défaut 20**, clampée serveur ET front.

---

## Item 1 — Historique multi-tours envoyé à l'agent (assemblé backend)

### Comportement cible (ce qui part à l'agent)
```
completion = get_llm(agent_id).new_completion()
for m in history:                       # N derniers messages de CETTE session, oldest→newest, verbatim
    completion.with_message(m.content, m.role)        # role ∈ {user, assistant}
completion.with_message(user_prefix + current_message, "user")   # préfixe nom+date sur le tour courant
completion.execute_streamed()
```
- **Stockage inchangé** : `save_user_message` écrit le `message` **brut**. Le préfixe + l'historique sont **build-time only**, jamais persistés.
- **Préfixe** (chaque tour) : `"[User: {full_name} — Date: {%A, %B %d, %Y at %H:%M}] "` construit serveur depuis l'identité + date courante. Messages d'historique rejoués **verbatim** (pas de re-préfixe → pas de date du jour sur un vieux message).
- **Comptage** : `history_limit` = nombre de **messages**. On fetch `ceil(history_limit/2)` échanges, on aplatit (user, assistant) oldest→newest, on garde les **derniers `history_limit`** messages.

### Changements backend
- `security/validation.py` : **+`validate_history_limit(value)`** → clamp `[10,50]`, défaut `20`, ne lève jamais (constantes `MIN/MAX/DEFAULT_HISTORY_LIMIT`).
- `security/identity.py` : **+`derive_full_name(login)`** → title-case par segment de `prenom.nom` (`said.chaoui→Said Chaoui` ; sans point → title-case du tout ; vide → None). `derive_display_name` (prénom) **inchangé**.
- `agents/context.py` (**nouveau, pur, testable, sans dataiku/Vue**) :
  - `build_user_prefix(full_name, now_dt)` → la chaîne préfixe.
  - `flatten_exchanges_to_messages(rows, max_messages)` → `[{role, content}]` chronologique aplati + trimé (pur ; `rows` = échanges oldest→newest).
  - `build_completion_messages(history_messages, current_message, user_prefix)` → liste ordonnée `[{role, content}]` finale (historique verbatim + tour courant préfixé).
- `storage/sql_builders.py` (pur, testé) : **+`build_session_history_query(table_ref, columns, user_value_sql, session_value_sql, exclude_exchange_sql, limit)`** :
  ```sql
  SELECT {columns} FROM {table}
  WHERE user_id = {user} AND session_id = {session} AND exchange_id <> {exclude}
  ORDER BY created_at DESC, exchange_id DESC
  LIMIT {n}
  ```
  (exclut l'échange courant déjà inséré ; newest-first → reverse Python pour chronologique).
- `storage/chat_v2.py` : **+`history_messages_for_session(user_id, session_id, exclude_exchange_id, max_messages)`** → résout `full_table`/`sql_value`, lance `build_session_history_query` avec `LIMIT ceil(max_messages/2)`, décode, reverse, aplatit via `context.flatten_exchanges_to_messages`. Renvoie `[{role, content}]`.
- `agents/streaming.py` : `run_agent_streamed` **nouvelle signature** `(project_key, agent_id, messages)` (au lieu de `message`) → boucle `completion.with_message(m["content"], m["role"])` puis `execute_streamed()`. **Tout le reste (footer/usage/SQL/trace/bornes) inchangé.**
- `agents/stream_manager.py` : `start_run` et `_worker` reçoivent en plus `session_id`, `history_limit`, `user_prefix`. Le **worker** (thread) : fetch `chat_v2.history_messages_for_session(...)`, assemble via `context.build_completion_messages(history, current_message, user_prefix)`, appelle `run_agent_streamed(project_key, agent_id, messages)`. (SQL depuis le worker = déjà prouvé, L019.) Best-effort : si le fetch historique échoue, **fallback = juste le tour courant** (jamais casser le chat).
- `api/routes.py` `/chat/start` (161-244) : lire `history_limit` du payload → `validate_history_limit` ; construire `user_prefix` = `context.build_user_prefix(derive_full_name(identity["user_id"]), now)` ; passer `session_id`, `history_limit`, `user_prefix` à `start_run`.
- `storage/migrations.py` : **+index additif** `CREATE INDEX IF NOT EXISTS …_usc_idx ON {chat_v2} (user_id, session_id, created_at DESC)` (non destructif ; accélère lectures par session). Nom borné ≤63 octets.

### Changements frontend
- `services/backend.js` : `startChat(sessionId, message, agentKey, historyLimit)` → ajoute `history_limit` au body.
- `composables/useChatStream.js` + `stores/chat.js` : threader `ui.contextMessages` jusqu'à `startChat` (depuis `send()` **et** `regenerate()`).

---

## Item 2 — Sidebar lazy-loading (noms seuls, contenu au clic)

### Nouveaux endpoints backend (READ-only, owner-scopés, bornés)
1. **`GET /conversations?cursor=&limit=`** → `{conversations:[{session_id, title, last_at}], next_cursor, has_more}`.
   - **Aucun corps de message.** Tri `last_at DESC`. Pagination **keyset** : `cursor` opaque encode `(last_at, session_id)`.
   - Builder pur **`build_conversation_list_query(table_ref, user_value_sql, cursor_clause, limit, title_maxlen)`** :
     ```sql
     SELECT session_id, title, last_at FROM (
       SELECT session_id,
              COALESCE(LEFT((ARRAY_AGG(user_text ORDER BY created_at ASC, exchange_id ASC))[1], {tlen}), '') AS title,
              MAX(created_at) AS last_at
       FROM {table} WHERE user_id = {user} GROUP BY session_id
     ) s
     {cursor_clause}                          -- '' ou: WHERE (last_at < {c_last}) OR (last_at = {c_last} AND session_id < {c_sid})
     ORDER BY last_at DESC, session_id DESC
     LIMIT {n}
     ```
   - `limit` clampé `[1,60]` ; on demande `limit+1` pour calculer `has_more` ; `title` tronqué serveur (`title_maxlen` ~140). Cursor parsé/validé défensivement (last_at = timestamp, session_id ≤128) puis **paramétré** via `sql_value`.
   - `chat_v2.list_conversations(user_id, cursor, limit)` + `validate_conversations_query(args)` (validation.py).
2. **`GET /conversation?session_id=`** → `{session_id, rows:[…échanges…]}` chronologiques, bornés (`LIMIT 500`).
   - Builder pur **`build_session_messages_query(table_ref, columns, user_value_sql, session_value_sql, cap)`** (user+session scopé, `ORDER BY created_at ASC`).
   - `chat_v2.messages_for_session(user_id, session_id, cap)`.

### Changements frontend
- `services/backend.js` : `fetchConversations(cursor, limit)` + `fetchConversation(sessionId)`. (`fetchHistory` **retiré du front** ; endpoint backend conservé.)
- `stores/session.js` : retirer `historyRows`/`loadHistory`/`deriveConversations` → **liste paginée** :
  - state : `conversations` (`[{id, title, lastAt}]`), `convCursor`, `convHasMore`, `convLoading`, `convError`.
  - `loadFirstConversations(count)` (1ʳᵉ page, `limit=count`), `loadMoreConversations()` (page suivante, dedupe par `session_id`), `bumpCurrentConversation({id,title,lastAt})` (upsert + remonte en tête après envoi).
  - `init()` → `Promise.all([loadAgents(), loadFirstConversations()])` ; `ensureLoaded()` inchangé.
- `components/shell/Sidebar.vue` : au mount, calculer `count` pour remplir **~120 %** de la hauteur (`ceil(1.2*clientHeight/itemHeight)`, clamp `[10,60]`) → `loadFirstConversations(count)` ; si après rendu `scrollHeight ≤ 1.2*clientHeight && convHasMore`, charger encore (boucle gardée). **IntersectionObserver** sur sentinelle bas → `loadMoreConversations()` (si `convHasMore && !convLoading`). Spinner « chargement… » bas ; états loading/empty/error conservés. `openConversation(c)` inchangé (router push).
- `stores/chat.js` `openSession(sessionId)` → **async** : `fetchConversation(sessionId)` (lazy) ; états `threadLoading`/`threadError` ; reconstruit `messages` via `rowsToMessages`. `send()` : remplacer `session.loadHistory()` par `session.bumpCurrentConversation(...)` (le thread actif est déjà en mémoire). `newConversation()` inchangé.
- `views/ChatView.vue` : `/chat/:sessionId` → `openSession` async (état chargement thread) ; **supprimer** le `watch(session.historyRows)` (n'existe plus).

---

## Réglages (Settings)
- Contrôle **10–50** existant repurposé : « Conversations affichées » → **« Messages d'historique inclus comme contexte »**. Store : `ui.maxConversations` → **`ui.contextMessages`** (clamp `[10,50]` défaut `20`, nouvelle clé localStorage `owismind.contextMessages`). `prefs.js` : `clampMaxConversations` → `clampContextMessages` (mêmes bornes). **Pas de refetch** au changement (n'affecte que le prochain `/chat/start`). i18n : nouvelles clés via `i18n/extra.js` (merge ; `messages.json` reste pristine).

## Sûreté (non négociable)
- **Net positif instance** : on cesse de charger TOUS les messages au démarrage ; lectures **bornées + indexées + owner-scopées 2 clauses** ; SQL **paramétré** (`sql_value`/`pg_identifier`) ; **aucun nouveau chemin d'écriture** ; `chat_v2` write + trace dataset **non touchés** ; API DSS lecture seule.
- L'assemblage historique **ne lit que les messages de l'utilisateur** (user+session scopé). Fallback best-effort (jamais casser le chat).
- Mono-process toujours supposé (inchangé).

## Tests (NO INSTALL)
- **`unittest`** (`Plugin/owismind/tests/`, hors `python-lib`, non packagé) : `build_session_history_query`, `build_conversation_list_query`, `build_session_messages_query`, cursor encode/parse, `validate_history_limit`, `validate_conversations_query`, `derive_full_name`, `build_user_prefix`, `flatten_exchanges_to_messages` (aplatissement + trim + null-assistant), `build_completion_messages`.
- **`node:test`** (`frontend/test/`) : pagination/dedup/bump conversations (helpers purs extraits), `clampContextMessages`.
- `py_compile` complet + `vite build` (temp) + revue adversariale multi-agents avant build officiel.

## Hors-scope (différé)
- Suppression de `/history` backend + `history_for_user`/`build_history_query`/`validate_max_conversations` (nettoyage après validation DSS des nouveaux endpoints).
- Evidence Studio (différé, décision user antérieure).
- Lookup `client.get_user()` pour le vrai displayName DSS (dérivation login suffit).
