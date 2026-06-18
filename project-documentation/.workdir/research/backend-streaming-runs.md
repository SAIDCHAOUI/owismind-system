# Knowledge pack - Backend streaming : thread worker, cycle de vie des runs, normalisation d'événements, contexte

> Domaine : couche de streaming du backend Flask d'OWIsMind (plugin Dataiku DSS).
> Tous les chemins sont absolus depuis la racine `/Users/saidchaoui/projects/owismind`.
> Fichiers principaux étudiés :
> - `Plugin/owismind/python-lib/owismind/agents/stream_manager.py`
> - `Plugin/owismind/python-lib/owismind/agents/streaming.py`
> - `Plugin/owismind/python-lib/owismind/agents/context.py`
> - `Plugin/owismind/python-lib/owismind/agents/discovery.py`
> Fichiers voisins consultés pour les connexions : `api/routes.py`, `storage/chat_v5.py`, `storage/artifacts.py`, `storage/usage.py`, `storage/chat_traces.py`, `evidence/capture.py`, `storage/settings.py`, `python-lib/CLAUDE.md`.

---

## 1. Vue d'ensemble : pourquoi du polling et pas du SSE

Le modèle de transport est un **polling via thread d'arrière-plan**, et non du Server-Sent Events. La raison est documentée en tête de `stream_manager.py` (lignes 1-29) : DSS place un nginx interne devant chaque backend Python de webapp. Une réponse HTTP longue de type `text/event-stream` peut être **bufferisée par ce proxy**, si bien que les événements de l'agent arriveraient au navigateur tous d'un coup à la fin, au lieu d'arriver en direct. La Dash WebApp de production sur la même instance contourne ce problème par conception : elle n'expose jamais une réponse longue au navigateur. Elle lance l'agent dans un thread d'arrière-plan, accumule la progression dans un dict de niveau module, et le front interroge ce dict à intervalle court. Chaque poll est une requête courte normale que le proxy ne bufferise jamais.

Ce module porte ce pattern éprouvé sur la pile Flask/Vue et **ajoute deux filets de sécurité que la version Dash n'a pas** (`stream_manager.py:13-16`) :
1. un plafond de concurrence (threads bornés),
2. une éviction TTL (pas de fuite mémoire de runs orphelins).

Le flux global (`stream_manager.py:17-23`) :
1. `start_run` enregistre un run, lance UN thread daemon worker, retourne un `run_id`.
2. Le worker itère `streaming.run_agent_streamed` (événements déjà normalisés), ajoute chaque événement à la liste `events` du run, accumule la réponse + tout SQL généré, puis persiste le message assistant (phase deux) et marque `done`.
3. `poll` retourne les événements ajoutés depuis le curseur de l'appelant, plus `done`/`error`.

Côté HTTP, trois routes pilotent ce cycle (`api/routes.py`) : `POST /owismind-api/chat/start` (ligne 190), `GET /owismind-api/chat/poll` (ligne 321), `POST /owismind-api/chat/stop` (ligne 356). Le préfixe d'URL `/owismind-api` est porté par le Blueprint Flask (voir `python-lib/CLAUDE.md`).

---

## 2. `stream_manager.py` : cycle de vie d'un run

### 2.1 État partagé et verrou

Tout l'état vit dans deux dicts de niveau module, **gardés par un unique `threading.Lock`** (`stream_manager.py:89-95`) :

```python
_LOCK = threading.Lock()
_RUNS = {}                 # run_id -> {events, done, error, user_id, started_at, finished_at, last_poll_at, stop_requested}
_LAST_START_BY_USER = {}   # user_id -> timestamp monotone du dernier start (pre-gate par utilisateur)
```

Chaque section critique est minuscule (append/slice de liste), d'où un verrou unique global et non un verrou par run. La forme exacte d'un run est posée dans `start_run` (`stream_manager.py:198-209`) :

```python
_RUNS[run_id] = {
    "events": [], "done": False, "error": None,
    "user_id": user_id, "started_at": now, "finished_at": None,
    "last_poll_at": None, "stop_requested": False,
}
```

### 2.2 Constantes de réglage (sécurité instance)

Toutes définies en tête (`stream_manager.py:42-87`) :

| Constante | Valeur | Rôle |
|---|---|---|
| `MAX_CONCURRENT_RUNS` | `8` | Plafond dur de runs en vol simultanés sur tout le process (borne threads + connexions LLM Mesh). |
| `FINISHED_TTL_SECONDS` | `60.0` | Durée pendant laquelle un run terminé reste lisible (couvre un poll tardif/dupliqué : il voit les événements terminaux au lieu d'un 404). |
| `HARD_TTL_SECONDS` | `600.0` | Durée de vie absolue de tout run (même onglet fermé en cours), garantit que les orphelins ne s'accumulent pas. |
| `MAX_LIVE_EVENTS` | `5000` | Borne par run de la timeline live polled. |
| `MAX_ANSWER_CHARS` | `1_000_000` | Borne par run de la réponse accumulée. |
| `MAX_ARTIFACTS_ACCUM` | `8` | Borne du nombre de specs d'artefacts (chart/table) accumulés. |
| `MAX_RUN_SECONDS` | `300.0` | Deadline wall-clock dur : un run ne peut occuper indéfiniment un worker + slot. |
| `ABANDON_AFTER_SECONDS` | `30.0` | Si le navigateur a cessé de poller (onglet fermé) ce temps APRÈS avoir commencé à poller, le run est traité comme abandonné et coupé. |
| `MIN_START_INTERVAL_SECONDS` | `1.0` | Espacement minimal entre deux démarrages DU MÊME utilisateur (pre-gate anti-spam). |

Rationale clé (`stream_manager.py:71-82`) : `MAX_RUN_SECONDS` et `ABANDON_AFTER_SECONDS` sont **évalués entre les chunks streamés**. Limitation explicite et assumée : un appel amont totalement bloqué qui ne yield jamais reste borné uniquement par le TTL mémoire. Un thread watchdog serait nécessaire pour cela et n'est **volontairement pas ajouté** (risque plus élevé sur un chemin validé).

### 2.3 `can_accept(user_id)` : pre-check d'admission

Appelé par la route AVANT toute écriture DB (`stream_manager.py:102-124`, utilisé en `routes.py:256`). Retourne `(ok, reason)`. Il reflète le plafond dur de concurrence pour rejeter une requête saturée avant de persister un message utilisateur (évite un INSERT + aller-retour auth gaspillés), et ajoute une grille d'espacement légère par utilisateur. Raisons possibles : `"busy"` (cap atteint) ou `"rate_limited"`. Point important (`stream_manager.py:120-123`) : le timestamp d'espacement de l'utilisateur est **réservé MAINTENANT sous le même verrou**, pour que deux `/chat/start` concurrents du même user ne passent pas tous les deux la grille (la fenêtre de race antérieure est fermée). Côté route, `routes.py:256-261` mappe `rate_limited` -> HTTP 429 et `busy` -> HTTP 503.

### 2.4 `start_run(...)` : enregistrement + spawn

Signature (`stream_manager.py:179`) :
```python
start_run(project_key, agent_id, message, exchange_id, user_id,
          parent_exchange_id, history_limit, user_suffix, screen_context=None)
```

Mécanique (`stream_manager.py:189-229`) : génère `run_id = uuid4().hex`, évince les runs périmés sous verrou (`_evict_stale_locked`), recompte les runs actifs et lève `CapacityError` si `active >= MAX_CONCURRENT_RUNS` (double garde, en plus de `can_accept`). Il enregistre la forme du run, puis lance un `threading.Thread(target=_worker, ..., daemon=True)` nommé `owi-agent-run-<8 premiers hex>`. Détail subtil (`stream_manager.py:213-216`) : `started_at` (`now`) est passé **explicitement** au worker pour que la deadline wall-clock soit ancrée à l'enregistrement et jamais réinitialisée en relisant un état de run possiblement évincé.

`CapacityError` est une exception locale (`stream_manager.py:98-99`) ; la route la rattrape (`routes.py:311-313`) -> HTTP 503 `busy`.

### 2.5 `_stop_reason(run_id, started_at)` : pourquoi couper

(`stream_manager.py:127-146`) Retourne la raison de couper, sinon `None`, avec priorité : stop utilisateur explicite (`"stopped"`) > deadline wall-clock (`"timeout"`) > coupure abandon-par-navigateur (`"abandoned"`). Évalué entre chunks. Note importante du commentaire : **le stream officiel LLM Mesh n'expose aucune API de cancel**, donc un stop coopératif (cesser simplement d'itérer le générateur) est la seule voie supportée pour terminer tôt.

### 2.6 `_evict_stale_locked(now)` : éviction TTL

(`stream_manager.py:149-168`) À appeler en tenant `_LOCK`. Marque périmé : un run terminé dont `finished_at` dépasse `FINISHED_TTL_SECONDS`, OU tout run dont `started_at` dépasse `HARD_TTL_SECONDS`. Les pop puis log `evicted N stale run(s)`. Garde aussi `_LAST_START_BY_USER` borné en supprimant les timestamps plus vieux que `HARD_TTL_SECONDS`.

### 2.7 `_worker(...)` : le cœur

(`stream_manager.py:259-523`) Exécute une complétion d'agent, streame ses événements dans le run, puis persiste. Il reflète le corps de l'ancien générateur SSE mais écrit dans l'état partagé au lieu de yielder des frames HTTP. Séquence d'événements émise vers le front : `run_started`, puis les événements propres de l'agent (`agent_event` / `answer_delta` / `generated_sql` / `usage_summary`), puis `final_answer` + `run_done` - ou `error`.

Accumulateurs locaux (`stream_manager.py:273-290`) : `answer_parts`, `answer_chars`, `answer_truncated`, `live_events`, `sql_list`, `artifacts`, `sql_pos_by_index` (mapping `sqlIndex` -> position dans `sql_list`), `trace_raw`, `usage_totals`, `stop_reason`.

Étapes :
1. Émet `{"type": "run_started", "exchangeId": exchange_id}` (`stream_manager.py:291`).
2. Assemble l'historique multi-tour via `chat_v5.history_messages_for_chain(user_id, parent_exchange_id, history_limit)` (`stream_manager.py:299`). Best-effort : si la lecture échoue, dégrade au tour courant seul (`history = []`).
3. Construit le bloc « ON SCREEN NOW » via `_build_screen_block` (voir 2.8), placé AVANT le suffixe de langue.
4. `agent_messages = context.build_completion_messages(history, message, screen_block + (user_suffix or ""))` (`stream_manager.py:311-312`).
5. Boucle `for event in streaming.run_agent_streamed(project_key, agent_id, agent_messages):` (`stream_manager.py:314`). Entre chaque event, appelle `_stop_reason` et `break` si coupure demandée.

Traitement par type d'événement (`stream_manager.py:323-411`) :
- **`answer_delta`** : accumule `text` dans `answer_parts`, borné par `MAX_ANSWER_CHARS` (au-delà : flag `answer_truncated`, warn une seule fois). L'event tombe ensuite dans la timeline live.
- **`generated_sql`** : construit l'item de persistance `{sql, success, row_count}` + clés trust-layer optionnelles copiées seulement si présentes : mapping `("sqlId","sql_id")`, `("stepIndex","step_index")`, `("agentKey","agent_key")`, `("sourceUrl","source_url")`, `("result","result")` (`stream_manager.py:349-358`). Gère l'**enrichissement** via `sql_pos_by_index` : si le `sqlIndex` est déjà vu, ce n'est pas un nouvel item mais l'enrichissement post-boucle (autorité de la trace fusionnée dans un item d'abord relayé par AGENT_DONE) -> il remplit en place les champs manquants du stored item et `continue` SANS push live. Sinon il enregistre la position et append à `sql_list`. **La copie live polled reste légère** : la clé `result` (lignes capturées) est retirée de l'event live (`stream_manager.py:374`), elle n'est lue qu'en persistance via `/evidence/meta`.
- **`usage_summary`** : capture `{promptTokens, completionTokens, totalTokens, estimatedCost}` dans `usage_totals` pour la persistance ; **ne fait PAS `continue`** : l'event tombe aussi dans la timeline live pour que le front montre l'usage pendant le run.
- **`artifact`** : capture la spec `{kind, title, chart}` (+ `kpi` si présent) dans `artifacts`, borné par `MAX_ARTIFACTS_ACCUM`, puis `continue` (jamais ajouté à la liste live ; le label live a déjà été donné par l'agent_event ARTIFACT).
- **`trace`** : capture `trace_raw = event.get("trace")` puis `continue` - la trace RAW est pour la **persistance seulement**, jamais sur la timeline live (elle peut être volumineuse).
- Pour tout le reste, append à la liste live si `live_events < MAX_LIVE_EVENTS`.

Note d'architecture (event narration) : `run_agent_streamed` émet aussi un type `narration` (`streaming.py:363`). Le worker ne le traite par aucune branche `elif` dédiée ; il tombe donc dans l'append générique de la timeline live (`stream_manager.py:409-411`). C'est intentionnel : la narration est transitoire, montrée en flux mais jamais persistée dans la réponse (cf. `streaming.py:65-68`).

**Phase deux - persistance** (`stream_manager.py:413-458`), toute best-effort, un échec n'avorte jamais le run (l'utilisateur a déjà la réponse) :
- `answer = "".join(answer_parts).strip()`.
- `chat_v5.save_assistant_message(exchange_id, answer, sql_list or None, usage=usage_totals)` (`stream_manager.py:419`). C'est là que `chat_v5` applique `capture.cap_sql_list` juste avant `json.dumps` (caps miroir au point d'écriture).
- `usage.record_usage(user_id, usage_totals)` (`stream_manager.py:433`) : incrémente les agrégats lifetime + mois courant (no-op si `usage_totals` est `None`, run stoppé tôt).
- `chat_traces.save_trace(exchange_id, trace_raw)` (`stream_manager.py:443`) : persiste la trace RAW de footer.
- `artifacts_storage.save_artifacts(exchange_id, user_id, artifacts)` si `artifacts` (`stream_manager.py:453-454`).

**Événements terminaux** (`stream_manager.py:460-503`) :
- Toujours d'abord `{"type": "final_answer", "exchangeId": exchange_id, "text": answer}`.
- Si `stop_reason == "stopped"` : émet `{"type": "stopped", "exchangeId": exchange_id}` (PAS une erreur : la réponse partielle a été persistée, le front rend un marqueur discret « génération arrêtée »).
- Si autre `stop_reason` (timeout/abandoned) : émet `{"type": "error", "message": "run_" + stop_reason}` et écrit `state["error"]`.
- Sinon : `{"type": "run_done", "status": "success"}`.

**Gestion d'exception** (`stream_manager.py:504-515`) : ne fuite jamais d'internes agent/SQL/connexion au client ; émet `{"type": "error", "message": "agent_unavailable"}` et pose `state["error"]`.

**`finally`** (`stream_manager.py:516-523`) : marque `done = True` et `finished_at` APRÈS avoir ajouté les événements terminaux, **garantie d'ordonnancement** : un poll qui voit `done == True` voit forcément aussi `final_answer`/`run_done` (ou `error`). Pas de race « frame finale perdue ».

### 2.8 `_build_screen_block(...)` : conscience écran

(`stream_manager.py:232-256`) Best-effort, ne lève jamais. Gaté sur le pointeur live du frontend : on ne décrit QUE ce qui est RÉELLEMENT à l'écran - l'exchange + l'onglet que l'utilisateur regarde avec le panneau Evidence OUVERT. Aucune lecture (et aucun bloc) si le panneau est fermé. Lecture d'artefacts **owner-scoped** : `artifacts_storage.read_artifacts(user_id, exchange_id)`. Le dernier `answer` de l'historique est tronqué au premier `\n\n[SQL` (`stream_manager.py:251`). Délègue ensuite à `context.build_screen_state(arts, last_answer, active_tab)`.

### 2.9 `poll(run_id, user_id, cursor)`

(`stream_manager.py:526-550`) Retourne `{events, cursor, done, error}` ou `None` si run inconnu ou non détenu par `user_id` (la route mappe `None` -> 404 sans révéler lequel). Le **slice d'événements et le flag `done` sont lus sous une seule prise de verrou** (pas de race de frame finale). Pose `state["last_poll_at"] = now` : c'est le **heartbeat** qu'utilise le worker pour détecter un abandon. Le curseur est l'index de fin : `start = cursor` (sanitisé `int >= 0`, sinon 0), `new_events = events[start:]`, et le nouveau curseur retourné est `len(events)`.

Protocole de curseur côté route (`routes.py:339-353`) : `run_id` et `cursor` (défaut 0) en query params ; `run_id` borné par `_MAX_RUN_ID_LENGTH` ; cursor négatif ramené à 0.

### 2.10 `request_stop(run_id, user_id)`

(`stream_manager.py:553-569`) Owner-scoped. Pose `stop_requested = True` sur le run en vol de l'appelant ; le worker le voit entre deux chunks (`_stop_reason` -> `"stopped"`), cesse d'itérer, persiste la réponse partielle accumulée, termine proprement avec un `stopped`. Retourne `False` si run inconnu/évincé/détenu par un autre (route -> 404). **Idempotent**. Route `/chat/stop` : `routes.py:379-380`.

---

## 3. `streaming.py` : `run_agent_streamed` et la normalisation

### 3.1 Contrat

(`streaming.py:288-318`) Générateur qui exécute UNE complétion d'agent et yield des dicts d'événements normalisés et JSON-safe (un `type` par dict). `messages` est la liste ordonnée `{role, content}` assemblée par l'appelant. Le pattern officiel LLM Mesh multi-tour : rejouer chaque tour via `completion.with_message(content, role)` (`streaming.py:330-331`).

Mécanique d'appel (`streaming.py:326-343`) :
```python
project = dataiku.api_client().get_project(project_key)
completion = project.get_llm(agent_id).new_completion()
for m in messages:
    completion.with_message(m["content"], m["role"])
...
for chunk in completion.execute_streamed():
    data = getattr(chunk, "data", {}) or {}
```

Sécurité instance (`streaming.py:18-22`) : exactement UN run d'agent pour un message validé, **pas de boucle, pas de retry**. L'`agent_id` est résolu côté serveur depuis la whitelist avant tout appel ; rien ici n'accepte un id brut du front.

### 3.2 Constantes et reconnaissance de chunks

(`streaming.py:41-76`) :
- `_TEXT_CHUNK_TYPES = ("content", "text")` : chunks portant un delta de texte de réponse.
- `_SQL_TOOL_NAME = "semantic-model-query"` : le tool dont l'output porte le SQL généré.
- `_MAX_TRACE_DEPTH = 200` : borne de récursion défensive pour marcher la trace footer (la trace vient de DSS LLM Mesh, trustée ; transforme une trace pathologiquement profonde en « no extraction » au lieu d'un RecursionError).
- `_AGENT_DONE_KIND = "AGENT_DONE"` : event de l'orchestrateur dont `eventData` peut relayer mid-stream la liste de SQL généré des sous-agents (orchestrateur v2.2) - émis À CE MOMENT pour qu'un run stoppé ensuite persiste quand même son SQL.
- `_ARTIFACT_KIND = "ARTIFACT"` ; `_ARTIFACT_CHART_TYPES = ("line", "bar", "pie")`.
- `_NARRATION_KIND = "NARRATION"` ; `_NARRATION_MAX_CHARS = 280`.
- `_EVENT_PASSTHROUGH_KEYS = ("label", "stepIndex", "stepCount", "agentKey", "status")` : whitelist STRICTE des clés `eventData` relayées telles quelles sur l'`agent_event`. JAMAIS le dict entier : les payloads orchestrateur portent aussi `agentId / message / instruction / steps / generatedSql`, qui ne doivent jamais atteindre la timeline polled. `_EVENT_VALUE_MAX_CHARS = 300` borne chaque string relayée.

Le détecteur de footer `_is_footer_chunk` (`streaming.py:194-204`) reconnaît le chunk final soit par `data.get("type") == "footer"`, soit par `isinstance(chunk, DSSLLMStreamedCompletionFooter)` quand le SDK expose la classe (import optionnel et tolérant, `streaming.py:36-39`).

### 3.3 Boucle de stream : types d'événements émis

(`streaming.py:343-419`) Pour chaque chunk, `elapsed = round(time.perf_counter() - t0, 2)`. Si footer -> garde `footer_data` et `continue`. Sinon `chunk_type = data.get("type")` :

- **`chunk_type == "event"`** :
  - garde `event_data` dans `seen_event_data` (pour le fallback SQL relayé).
  - Si `eventKind == NARRATION` et `text` non vide -> yield `{"type": "narration", "text": text[:280]}` puis `continue`.
  - Sinon construit l'`agent_event` :
    ```python
    {"type": "agent_event", "eventKind": ..., "blockId": ..., "nextBlockId": ...,
     "toolName": event_data.get("toolName") or event_data.get("name") or event_data.get("tool"),
     "elapsedSeconds": elapsed}
    ```
    puis `agent_event.update(_whitelisted_event_fields(event_data))` (whitelist bornée, `streaming.py:79-97`) et yield.
  - Si `eventKind == AGENT_DONE` : relaie le SQL des sous-agents (`eventData.generatedSql`), dédupliqué par texte SQL via `emitted_by_sql`, en yieldant un `generated_sql` normalisé NOW (`streaming.py:385-397`).
  - Sinon si `eventKind == ARTIFACT` : yield `_normalized_artifact_event(event_data)` si non `None`.
- **`chunk_type in ("content", "text")`** : yield `{"type": "answer_delta", "text": text}` si `text`.
- **sinon** (forme inconnue) : log debug + yield un `agent_event` avec `eventKind = "UNKNOWN_CHUNK_TYPE:<type>"` (jamais casser le stream).

### 3.4 Forme d'un `generated_sql` normalisé

`_normalized_sql_event(item, sql_index)` (`streaming.py:106-139`). Clés obligatoires (forme historique) : `type, sqlIndex, success, rowCount, sql`. Clés trust-layer optionnelles ajoutées SEULEMENT si présentes : `sqlId, stepIndex, agentKey, sourceUrl, result` (ce dernier seulement si c'est un dict). Les tags de corrélation sont acceptés en snake_case OU camelCase via `_tag` (`streaming.py:100-103`) : l'orchestrateur v2.2 tague en snake_case (`sql_id/step_index/agent_key`) et les items issus du walker de trace n'ont aucune clé de corrélation - les deux orthographes restent acceptées (forward compat ORCHV22-01).

### 3.5 Normalisation ARTIFACT

`_normalized_artifact_event(event_data)` (`streaming.py:142-191`). Forme stricte, pure, ne lève jamais. `kind` doit être dans `{chart, table, kpi}`, `title` borné à 200 chars. La **DATA n'est PAS là** : le front réutilise le résultat `generated_sql` capturé via `/evidence/meta` ; seule la SPEC voyage.
- `chart` : `chart` doit être un dict avec `type` dans `("line","bar","pie")` et `x` string ; `y` normalisé en liste de strings non vides (max 8, chacune <= 128 chars) ; `style` optionnel <= 24 chars.
- `kpi` : `kpi.value` string obligatoire ; produit `{label, value[, delta, delta_pct]}` ; `out["chart"] = None`.
- `table` : `out["chart"] = None`.

### 3.6 Footer : extraction post-boucle

(`streaming.py:421-477`) Après la boucle : `trace = footer_data.get("trace")`.
- **SQL** : `_find_generated_sql(trace)` (`streaming.py:239-270`) marche la trace nichée et extrait `{success, row_count, sql[, result]}` par output du tool `semantic-model-query` ; `result` est optionnel et best-effort via `capture.extract_result(outputs)` (la clé des lignes n'est pas confirmée sur l'instance -> capture honnête ou absente). Si rien, fallback `_find_relayed_sql_from_events(seen_event_data)` (`streaming.py:273-285`) qui lit `eventData.generatedSql` des events de sous-agent dispatcher.
- **MERGE one-shot** (`streaming.py:428-458`) : on fusionne strictement contre les émissions mid-stream d'AGENT_DONE (les seules entrées de `emitted_by_sql`), consommées via `pop()`. Deux spans de trace DISTINCTS avec le même texte SQL (un échec transitoire puis un retry identique) doivent chacun émettre leur propre event exactement comme le flow validé pré-trust-layer (CHAT-REG-01) ; seul un doublon de relais est fusionné. Si un item a déjà été yieldé mid-stream et que la trace apporte l'autorité que le relais n'avait pas (`success` / `rowCount` / `result`), **un seul event d'enrichissement est re-yieldé avec le MÊME `sqlIndex`** -> le consommateur remplit en place et ne duplique jamais la timeline.
- **Usage** : `_find_usage_metadata(trace)` collecte tous les dicts `usageMetadata` nichés (`streaming.py:207-220`), `_sum_usage_metadata` les somme en `{promptTokens, completionTokens, totalTokens, estimatedCost}` (`streaming.py:223-236`). Yield `{"type": "usage_summary", **totals}`.
- **Trace RAW** : yield `{"type": "trace", "trace": trace}` en TOUT DERNIER, seulement si une trace existe - pour la persistance uniquement, jamais sur la timeline live.

### 3.7 Point sur `sqlIndex` (gotcha de corrélation)

`sql_index` numérote de façon monotone à travers les émissions mid-stream et post-boucle (`streaming.py:339-341, 393-394, 438-439`). Côté worker, `sql_pos_by_index` (`stream_manager.py:282`) corrèle ce `sqlIndex` à la position dans `sql_list` : un `generated_sql` re-réutilisant un `sqlIndex` déjà vu est l'enrichissement et met à jour le stored item en place, **jamais** un second push live. C'est le mécanisme central qui évite les doublons quand la trace footer enrichit un SQL déjà relayé mid-stream.

---

## 4. `context.py` : assemblage du payload multi-tour

Module **pur** (pas d'import `dataiku`, testable hors runtime DSS). Stratégie centrale (`context.py:1-13`) : on construit une liste ordonnée `{role, content}` - messages antérieurs verbatim, puis le tour utilisateur courant portant un **bloc de contexte compact APPENDÉ À LA FIN**. Le **WHY du suffixe** (`context.py:9-13`) : les petits modèles honorent bien mieux une instruction placée dans le slot de plus haute récence (la toute fin du message courant). Enfouir le nom/date/langue au début laisse le modèle l'oublier.

### 4.1 `MODEL_MODES`

(`context.py:29`) `("eco", "medium", "high")`. Relayé à l'agent comme token de contrôle compact appendé au tour courant ; l'orchestrateur le parse et le STRIP, il n'atteint donc jamais le modèle comme partie de la question. Absent/inconnu -> l'orchestrateur défaute à `"medium"`. Côté route (`routes.py:277-279`), un `mode` non reconnu est ramené à `"medium"`.

### 4.2 `detect_prompt_language(message, default="fr")`

(`context.py:55-73`) Devine de façon déterministe la langue (`"fr"`/`"en"`) du message brut. Tourne sur le message courant brut (pas de préfixe date qui polluerait l'heuristique). Logique :
- `_FR_ACCENT_RE` (`[éèêàùçâîôœ]`) présent -> `"fr"`.
- sinon compte les marqueurs FR (`_FR_RE`) vs EN (`_EN_RE`), **matchés sur frontières de mots** (`\b`) pour éviter les collisions de sous-chaîne (le FR `revenu` ne matche pas dans l'EN `revenue`, `add` pas dans `address`, `context.py:38-52`).
- égalité ou message neutre (« 42 ») -> `default` (la langue webapp quand connue, sinon `"fr"`).

C'est un miroir du `_detect_lang` de l'agent, porté côté backend 3.9 stdlib-only, pour calculer la langue UNE fois sur le message propre et la passer en token autoritaire.

### 4.3 `build_user_suffix(...)`

(`context.py:76-108`) Bloc de contexte compact appendé à la FIN du message courant. Porte : qui demande, la date (`_DATE_FMT = "%A, %B %d, %Y at %H:%M"`, locale C -> anglais non ambigu), la langue webapp configurée, et la règle porteuse : la langue de CE message, que l'agent doit suivre (elle gagne toujours sur les tours antérieurs et la langue webapp). Les tokens de contrôle sont **machine-only** :
- `⟦owi:mode=<mode>⟧` si `mode in MODEL_MODES`,
- `⟦owi:lang=<lang>⟧` si `prompt_lang in _LANG_LABEL`.

Forme produite (`context.py:96-108`) :
```
\n\n[Context - User: <name> · Today: <date> · Web app language: <label>] ⟦owi:mode=…⟧⟦owi:lang=…⟧
IMPORTANT - reply in <plabel>: the SAME language as my message above. The language of my current
message ALWAYS takes priority over earlier turns and over the web-app language.
```
L'agent parse puis STRIP les tokens `⟦…⟧`, donc ils n'atteignent jamais le modèle en texte visible, tandis que l'impératif de langue humain reste la dernière ligne du tour (récence). `_LANG_LABEL = {"fr": "French", "en": "English"}` (`context.py:22`).

> GOTCHA TYPOGRAPHIE : ces chaînes contiennent un caractère middot `·` et les délimiteurs `⟦` `⟧` (U+27E6/U+27E7) - PAS des tirets cadratin. Le projet bannit `—`/`–`. Toute manipulation byte-level de `context.py` doit être LC_ALL=C-safe (cf. mémoire L084).

### 4.4 Contexte écran : `build_screen_state(...)`

(`context.py:210-237`) Description compacte et bornée de ce qui est ACTUELLEMENT à l'écran : les artefacts rendus (chart/table/KPI du panneau Evidence) + les colonnes de données qu'ils exposent + le gist de la réponse précédente. Appendé au tour courant pour que l'agent réponde « explique ce graphique » / « ajoute le forecast » au lieu de répondre hors-sujet. Caps : `MAX_SCREEN_ARTIFACTS = 4`, `MAX_SCREEN_COLS = 24`, `SCREEN_ANSWER_EXCERPT_CHARS = 300` (`context.py:164-166`). Le bloc est cadré comme DONNÉE ANTÉRIEURE GROUNDÉE pour ne jamais déclencher le pare-feu d'honnêteté (un nouveau chiffre exige toujours un appel spécialiste). Helpers : `_artifact_phrase` (`context.py:169-190`), `_screen_columns` (`context.py:193-207`).

### 4.5 Historique multi-tour et SQL grounding

- `build_completion_messages(history_messages, current_message, user_suffix)` (`context.py:240-249`) : `history` verbatim + `{"role":"user","content": current_message + (user_suffix or "")}`.
- `flatten_exchanges_to_messages(rows, max_messages)` (`context.py:136-155`) : aplatit les rows d'exchange chronologiques en messages (user puis assistant), en appendant un bloc SQL borné (`_format_sql_context`, `context.py:116-133`, cap `MAX_SQL_CONTEXT_CHARS = 4000`) au tour assistant quand l'exchange porte un `generated_sql` décodé. Le bloc SQL est en français : `[SQL généré pour cette réponse :\n…]`.
- `exchanges_to_fetch(max_messages)` (`context.py:158-160`) : nombre d'EXCHANGES à lire (2 messages par exchange).

Ces helpers sont consommés par `chat_v5.history_messages_for_chain` (`storage/chat_v5.py:297-325`), qui marche la **chaîne d'ancêtres** de l'exchange via une CTE récursive user-scoped, bornée en profondeur (`MAX_CHAIN_DEPTH`) et en lignes, retourne newest-first, inverse en chronologique, parse le `generated_sql`, puis appelle `flatten_exchanges_to_messages`. C'est ce qui exclut les autres branches de l'arbre de conversation et tout ce qui suit le point de branchement.

---

## 5. `discovery.py` : lister les agents activables

(`discovery.py:1-77`) Module STRICTEMENT READ-ONLY : seulement des appels de listing, jamais create/modify/delete. Sert l'espace admin pour construire la whitelist d'agents activés.

- `AGENT_ID_PREFIX = "agent:"` : un LLM DSS est un agent quand son id commence par ce préfixe (ex. `agent:rNTZ781a`).
- `MAX_PROJECTS = 500`, `MAX_AGENTS = 200` : bornes défensives.
- `list_project_keys()` (`discovery.py:34-43`) : projets que l'identité de la webapp peut voir, triés, bornés. Reflète les permissions de l'identité courante.
- `list_project_agents(project_key)` (`discovery.py:46-76`) : retourne `[{agent_id, description}]` pour les agents d'un projet, en filtrant `project.list_llms()` sur les ids préfixés `agent:`. `description` = label humain, fallback sur l'id. Borné par `MAX_AGENTS`.

Connexion : ces listings alimentent l'écran admin (routes `routes.py:811` et `routes.py:879`). L'admin choisit les agents, persistés dans `webapp_settings_v1`. Au runtime, le front envoie une clé logique OPAQUE (ex. `ag_<hash>`) que `storage.settings.resolve_enabled_agent` (`storage/settings.py:103`) résout en `(project_key, agent_id)` ; une clé forgée ou désactivée résout à `None`. **Le front n'envoie jamais d'`agent_id` brut** (règle non négociable #4 du projet). C'est exactement ce que vérifie `chat_start` (`routes.py:235-240`) avant `start_run`.

---

## 6. Formes de données (JSON) - récapitulatif

### Événements normalisés sur la timeline live (poll `events[]`)
- `{type:"run_started", exchangeId}`
- `{type:"agent_event", eventKind, blockId, nextBlockId, toolName, elapsedSeconds[, label, stepIndex, stepCount, agentKey, status]}`
- `{type:"answer_delta", text}`
- `{type:"narration", text}` (transitoire, non persisté)
- `{type:"generated_sql", sqlIndex, success, rowCount, sql[, sqlId, stepIndex, agentKey, sourceUrl]}` (sans `result` en live)
- `{type:"usage_summary", promptTokens, completionTokens, totalTokens, estimatedCost}`
- `{type:"final_answer", exchangeId, text}`
- `{type:"run_done", status:"success"}` OU `{type:"stopped", exchangeId}` OU `{type:"error", message}`

### Réponse de `/chat/poll`
`{status:"ok", events:[…], cursor:<int>, done:<bool>, error:<str|null>}`

### Item de persistance `generated_sql` (vers chat_v5)
`{sql, success, row_count[, sql_id, step_index, agent_key, source_url, result]}`

### Spec d'artefact persistée
`{kind, title, chart[, kpi]}`

### Codes d'erreur HTTP de la route start
`429 rate_limited`, `503 busy`, `404 agent_not_enabled`/`run_not_found`, `409 storage_not_configured`, `500 storage_unavailable`/`agent_unavailable`, `401 unauthenticated`, `400 <ValidationError.code>`.

---

## 7. Connexions au reste du système

- **Routes HTTP** (`api/routes.py`) : `/chat/start` (190), `/chat/poll` (321), `/chat/stop` (356) ; Blueprint préfixe `/owismind-api`.
- **Persistance** : `storage/chat_v5.py` (messages user/assistant, chaîne d'ancêtres), `storage/chat_traces.py` (trace RAW), `storage/usage.py` (agrégats lifetime + mensuel), `storage/artifacts.py` (specs chart/table, owner-scoped).
- **Evidence** : `evidence/capture.py` (`extract_result`, `cap_sql_list`) ; le `result` capturé est surfacé après le run via `/evidence/meta`, jamais via `/chat/poll`.
- **Whitelist** : `storage/settings.py:resolve_enabled_agent` + `webapp_settings_v1` ; `discovery.py` alimente la config admin.
- **Agents LangGraph** (hors zip backend, env Python 3.11) : `dataiku-agents/agents/OWIsMind_orchestrator.py` et `SalesDrive_revenue_expert.py` (`agent:bHrWLyOL`). Ce sont eux qui émettent les `eventKind` NARRATION / AGENT_DONE / ARTIFACT et taguent le SQL (`sql_id/step_index/agent_key/source_url`) que `streaming.py` normalise. Le backend python-lib (3.9.23, Flask) reste agnostique du modèle : il consomme un flux LLM Mesh générique.

---

## 8. Gotchas et points en flux / incertains

1. **Pas de cancel LLM Mesh** : le stop est purement coopératif (cesser d'itérer le générateur), évalué entre chunks. Un appel amont totalement bloqué n'est borné que par le TTL mémoire (`stream_manager.py:71-82`). Pas de watchdog par conception.
2. **`result` (lignes capturées) non confirmé sur l'instance** : `capture.extract_result` est best-effort ; la clé `result` est simplement absente quand rien de reconnaissable n'est trouvé (`streaming.py:240-247`). Marqué incertain dans le code lui-même.
3. **`_SQL_TOOL_NAME = "semantic-model-query"`** est un span gelé recréé par le code agent au contrat figé. Toute renommage côté agents casserait l'extraction de trace (cf. mémoire).
4. **Race finale fermée par ordre** : `done` est posé APRÈS les événements terminaux (`stream_manager.py:516-523`), et `poll` lit slice+done sous un seul verrou (`stream_manager.py:535-550`).
5. **TOCTOU bénin** sur `can_accept` vs cap dur dans `start_run` : assumé et documenté (`stream_manager.py:107-109`) ; `start_run` reste le vrai gate (double comptage + `CapacityError`).
6. **Le worker n'a pas de branche dédiée pour `narration`** : il passe par l'append générique de la timeline live. Comportement correct mais implicite (à documenter pour un mainteneur).
7. **Edition concurrente en cours** : le dossier `dataiku-agents/` est édité en direct par un autre ingénieur (hors périmètre des 4 fichiers de ce pack) ; les `eventKind` côté agents pourraient évoluer. Les 4 fichiers backend étudiés ici (`stream_manager.py`, `streaming.py`, `context.py`, `discovery.py`) ont été lus tels quels au moment de la rédaction.
8. **Versions** : backend observé = Python 3.9.23 (pas de FastAPI, pas de langchain), per `python-lib/CLAUDE.md` et mémoire projet. Ne pas supposer 3.11 ici.
