# OWIsMind V2.0 : architecture et plan d'implementation de l'Espace de travail

> Spec de reference de la branche `OWIsMind_PRD_V2_0`. Prose FR, identifiants EN. Les regles non
> negociables de `CLAUDE.md` racine s'appliquent (SQL parametre + prefixe PROJECT_KEY + COMMIT, zero
> ALTER, whitelist agents serveur, aucun install, aucun tiret cadratin, artefacts generes jamais edites
> a la main). Contrat partage par les deux lots de travail :
> **`plugin/owismind/contracts/workspace_protocol.v1.json`** (JSON Schema, cree avec cette spec).
> Mock de design : `docs/design-v2/Espace de travail v4.dc.html` (outils du mock : script l. 2530-2780).

## 0. Resume en dix lignes

1. L'orchestrateur (Code Agent DSS, LangGraph, env 3.11) reste le cerveau : il boucle, appelle ses
   sous-agents et ses outils DSS, et pilote l'espace de travail par QUATRE outils : `write_plan`,
   `update_plan`, `write_note`, `publish_widget`. La boucle "navigateur" du mock n'est pas reprise.
2. Les operations d'espace de travail voyagent par le canal d'events LLM Mesh deja valide
   (`chunk.type == "event"`), sous UN nouveau `eventKind = "WORKSPACE"` dont `eventData` porte une
   operation versionnee (`v: 1`, `op: plan.set | plan.step | note.add | widget.add | prov.set`).
3. `agents/streaming.py` normalise ces operations en events `{type: "workspace", ...}` (validation
   stricte, caps), le worker les relaie en direct via `/chat/poll` ET les accumule par un reducer
   Python pur ; a la fin du run (ou au stop) l'etat complet est persiste en UNE ligne de la nouvelle
   table `webapp_workspaces_v1`. Zero ALTER, `chat_v5` et `webapp_artifacts_v1` intacts.
4. Provenance : chaque widget de donnees porte un `sql_id` OBLIGATOIRE (`s{step}q{n}`, format gele
   V1.3). Le sous-agent rend au modele un `result_id` = ce `sql_id` ; `publish_widget` l'exige.
   Plus jamais "le dernier SQL".
5. `GET /workspace?exchange_id=` rend plan + journal + widgets + provenance resolue (SQL joli, lignes
   capturees, run, filtres), SANS rien relancer. Le bouton "Ouvrir l'espace de travail" sous chaque
   reponse restaure l'ecran exactement.
6. Frontend : nouveau store `workspace.js` + reducer pur `workspaceModel.js`, panneau droit
   `WorkspacePanel.vue` a 4 onglets (Plan, Journal, Tableau de bord, Donnees = l'Evidence V1.3),
   tiroir `ProvenanceDrawer.vue`. Les composants Chart.js/Table/KPI V1.3 sont reutilises.
7. Style : la charte V2 suit le design (radius 4 a 12 px via les tokens existants, filets, aplats)
   plus l'aura orange du prompt (F26). Decision D1 a enteriner.
8. Phase 1 = livrable local cette session : protocole + backend + frontend alimente par le
   dev-harness ; Phase 2 = orchestrateur reel ; Phase 3 = retrait du legacy + validation DSS.
9. Deux implementeurs Opus en parallele par phase, proprietes de fichiers disjointes (section E).
10. Decisions ouvertes en section F, chacune avec une recommandation.

## A. Protocole d'events Espace de travail (aujourd'hui vs V2)

### A.1 Chaine V1.3 (constat)

```
Orchestrateur (writer(_ev(kind, eventData)))  --LLM Mesh stream-->  streaming.run_agent_streamed
  eventKinds geles : START, PLANNING, CALLING_AGENT, AGENT_DONE{generatedSql[]}, RUNNING_TOOL,
  TOOL_DONE, ARTIFACT{kind,title,chart|kpi,sql_id}, NARRATION, WRITING_ANSWER, DONE, SUB_AGENT_*
  -> events normalises : agent_event / answer_delta / narration / generated_sql / artifact /
     usage_summary / trace
  -> stream_manager._worker : relais live (/chat/poll, polling 500 ms) + accumulation
     (answer, sql_list, artifacts, usage, trace) + persistance phase 2 :
     chat_v5 (assistant_text, generated_sql JSON avec result capture 50 lignes),
     webapp_artifacts_v1 (specs, UPSERT), traces
  -> frontend useChatStream -> timelineModel.applyEvent (reducer pur) ; artefacts relus APRES le run
     via /evidence/meta (chart_payload construit cote serveur, results_by_sql par sql_id)
```

Limites V1.3 que V2 corrige : les artefacts ne sont pas visibles en direct (relus apres le run) ;
`show_*` rend "le DERNIER resultat" (`latest_sql_id`) donc plusieurs runs/SQL dans une reponse
melangent la preuve ; pas de plan visible ; un seul chart ou une seule table de fait ; Evidence ne
sait pas quel widget vient de quel SQL ; la reponse texte n'est pas un bilan structure.

### A.2 Canal V2 : eventKind `WORKSPACE`

Un seul nouveau genre d'event cote orchestrateur, additif (les genres geles restent emis tels quels,
le legacy `ARTIFACT` reste accepte pendant la transition, decision D3) :

```python
writer(_ev("WORKSPACE", {"v": 1, "op": "widget.add", "seq": 7, "ts": 12.4, ...payload}))
```

`seq` = compteur monotone par run (ordre total, dedoublonnage), `ts` = secondes depuis le debut du
run (chronometre backend fait foi si absent : le worker tamponne `elapsedSeconds`).

### A.3 Operations (v1), caps et regles

| op | payload (cle = type) | caps |
|---|---|---|
| `plan.set` | `mission: str`, `steps: [{id, label, total?: int, unit?: str}]`, `origin: "model"\|"auto"` | mission 240 ch, 1 a 10 etapes, label 140 ch |
| `plan.step` | `step_id`, `status: todo\|running\|done\|error`, `done?: int`, `add_step?: {id,label}` | idem |
| `note.add` | `id`, `step_id?`, `kind: plan\|find\|check\|note\|done`, `title`, `text`, `sql_id?` | title 140 ch, text 1200 ch, 30 notes/run |
| `widget.add` | `id`, `step_id?`, `kind: chart\|table\|kpi\|text`, `title`, `comment?`, `sql_id` (OBLIGATOIRE si kind != text), `chart?: {type: bar\|line\|pie\|donut, x, y[], style?, x_label?, y_label?, unit?}`, `kpi?: {label, value, delta?, delta_pct?, unit?}`, `text?: str` | 12 widgets/run, y <= 8 series, text 4000 ch |
| `prov.set` | `sql_id`, `agent_key`, `tool`, `task`, `step_id?`, `duration_ms`, `row_count?`, `success` | task 800 ch, 24 provenances/run |

Regles de validation (backend, fail-closed par operation : une operation invalide est IGNOREE et
journalisee, jamais une 500, le run continue) :
- `op`, `kind`, `status`, `chart.type` par liste blanche ; toute cle inconnue est supprimee.
- `widget.add` de donnees sans `sql_id` ou avec un `sql_id` qui ne matche pas `^s\d+(q|lk|qc)\d+$`
  est rejete. Le worker verifie au moment de la persistance que chaque `sql_id` reference existe dans
  `sql_list` ; sinon le widget est conserve avec `binding: "orphan"` (affiche en etat vide honnete,
  jamais les lignes d'un autre SQL : regle deja appliquee par `/evidence/meta`).
- `plan.set` apres un premier `plan.set` = remplacement complet (`plan_version += 1`) ; les notes et
  widgets gardent leur `step_id` (affiches "etape retiree" si l'id a disparu).
- Les ids (`steps[].id`, `note.id`, `widget.id`) sont des slugs `^[a-z0-9_-]{1,32}$` generes par
  l'orchestrateur (`p1`, `n3`, `w2`), jamais par le modele.

### A.4 Events normalises vers le frontend

`streaming.py` emet `{type: "workspace", v: 1, op, seq, ts, ...payload}` (payload deja projete sur le
schema). Le frontend recoit la MEME forme en live (`/chat/poll`) et dans le document restaure
(`GET /workspace` renvoie `events: [...]` + l'etat reduit) : un seul reducer pour les deux chemins.

### A.5 Etat reduit (forme stockee et servie)

```json
{
  "v": 1, "status": "done|stopped|error|running", "exchange_id": "...",
  "plan": {"version": 1, "origin": "model", "mission": "...",
           "steps": [{"id": "p1", "label": "...", "status": "done", "done": 3, "total": 3, "unit": "comptes"}]},
  "notes": [{"id": "n1", "step_id": "p1", "kind": "find", "title": "...", "text": "...", "ts": 4.2, "sql_id": "s1q1"}],
  "widgets": [{"id": "w1", "step_id": "p1", "kind": "chart", "title": "...", "comment": "...",
               "sql_id": "s1q1", "chart": {...}, "binding": "explicit", "ts": 9.8}],
  "provenance": {"s1q1": {"agent_key": "revenue", "tool": "semantic-model-query", "task": "...",
                          "step_id": "p1", "duration_ms": 8120, "row_count": 12, "success": true}},
  "summary": {"widget_ids_by_step": {"p1": ["w1"]}, "sql_ids": ["s1q1", "s2q1"]}
}
```

Les LIGNES ne sont jamais dans ce document : elles vivent deja dans `chat_v5.generated_sql[].result`
(extrait 50 lignes, L190) et le total/la suite viennent de `/evidence/result-rows`. `GET /workspace`
joint tout cela par `sql_id` au moment de la lecture (voir C.3).

## B. Adaptations de l'orchestrateur et des sous-agents (Phase 2)

Fichier : `GenAI/Agents/OWIsMind_orchestrator.py` (+ `project-library/python/owismind_hub/prompts`
pour la persona). Sous-agents : `GenAI/Agents/*_expert.py` (changement minimal, B.4).

### B.1 Outils exposes au modele

Remplacent `show_chart` / `show_table` / `show_kpi` (noms conserves comme ALIAS internes de
`publish_widget` pendant la transition, non exposes) :

- `write_plan(mission, steps[{label, total?, unit?}], say?)` : A APPELER EN PREMIER pour toute
  question a plus d'une facette. Emet `plan.set`.
- `update_plan(step, status, done?, add_step?)` : emet `plan.step`.
- `write_note(title, text, kind?, step?, result_id?)` : emet `note.add` (memoire de travail du
  modele, relue pour rediger le bilan).
- `publish_widget(kind, title, result_id?, step?, comment?, chart_type?, x?, y[]?, style?, x_label?,
  y_label?, unit?, kpi_value?, kpi_delta?, kpi_delta_pct?, text?)` : emet `widget.add`. Pour
  `chart|table|kpi`, `result_id` est OBLIGATOIRE et doit etre un `result_id` recu d'un sous-agent dans
  ce run (sinon message d'erreur au modele, pas d'event). Pour `text`, `text` obligatoire.
- `tell_user`, `attribute_lookup`, `current_date`, `recall_prior_result`, `ask_*_expert` : inchanges.

### B.2 Politique "plan d'abord" et decomposition multi-facettes

- Persona (hub `prompts/`) : "Tu ecris ton plan AVANT toute requete quand la question a plusieurs
  facettes ; une facette = une etape ; chaque etape finit par une note ET, si elle produit des
  chiffres, par un widget ; ta reponse finale est un BILAN : un paragraphe par etape, chiffres cles,
  limites, sans tableau markdown."
- Garde-fou deterministe (decision D4) : si le premier lot d'appels contient un sous-agent sans
  `write_plan` prealable, `node_tools` fabrique un plan implicite (une etape par appel specialiste,
  `origin: "auto"`) et emet `plan.set` AVANT d'executer, puis ecrit au modele "plan auto-cree, mets-le
  a jour". L'utilisateur voit toujours un plan.
- Mise a jour automatique : a chaque `CALLING_AGENT` d'une etape connue -> `plan.step running` ; a
  `AGENT_DONE` -> `done` (ou `error`). Le modele peut affiner (lots `done/total`) mais ne peut pas
  "oublier" de fermer une etape : `node_finish` passe toute etape `running` en `done` si un widget ou
  une note lui est rattache, sinon en `error` avec une note `kind: done` honnete.

### B.3 Du resultat sous-agent au widget, sans lignes brutes vers le LLM

- `_consume_subagent` tague deja chaque span `semantic-model-query` d'un `sql_id` `s{step}q{n}` et
  attache les lignes capturees (50 max) au DERNIER item. V2 : la sortie d'outil rendue au modele
  (`_subagent_tool_output`) ajoute une ligne `result_id: s2q1 (12 rows, columns: ...)`. Le modele ne
  voit que le headline + colonnes + l'echantillon structure deja borne (inchange).
- `publish_widget(result_id=...)` : l'orchestrateur resout `state.captured[sql_id]` (dict par id,
  nouveau champ `captured_by_id` dans `OrchState`), valide les colonnes `x`/`y`/`value` contre ce
  resultat precis (comme `_record_artifact` le fait contre `latest`), puis emet `widget.add`
  `binding: "explicit"`. `result_id` absent sur un chart = refus avec la liste des `result_id`
  disponibles (jamais de repli sur "latest" : decision D2).
- `prov.set` est emis par `node_tools` juste apres `AGENT_DONE`, pour CHAQUE `sql_item` du
  sous-agent : `{sql_id, agent_key, tool: "semantic-model-query"|"attribute_lookup", task (tache
  envoyee au sous-agent, 800 ch), step_id, duration_ms, row_count, success}`.
- Chart `donut` = `pie` + `style: "donut"` (deja supporte par `chart_payload.py`).

### B.4 Limites, runtime, modeles

- `MAX_TOOL_LOOPS` 8 -> 10 (decision D8), `MAX_PARALLEL_AGENTS` 3 inchange, `MAX_PLAN_STEPS` 10,
  `MAX_WIDGETS` 12, `MAX_NOTES` 30, `MAX_PROVENANCE` 24. Deadline par mode inchangee
  (`stream_manager.resolve_run_deadline`).
- Env Python 3.11, stdlib + dataiku + langgraph, aucun import plugin (regle 5 de `CLAUDE.md` V2).
- Modeles : `/python/owismind_hub/models.json` reste la SEULE source (L195, test gardien
  `tests/test_models_hub.py` inchange). Aucun id dans le code de l'orchestrateur V2.
- Sous-agents : inchanges fonctionnellement ; seule evolution Phase 2 : `AGENT_RESULT` porte
  `row_count` reel (total COUNT) quand le tool le fournit (L190, backlog existant).
- Moteur natif (`native_orchestrator.py`, flag `profile.native_engine`) : gele en V2.0, n'emet pas
  d'operations workspace (decision D5).

## C. Backend (python-lib/owismind, Python 3.9)

### C.1 Normalisation et validation : `agents/streaming.py` + nouveau paquet `workspace/`

- `owismind/workspace/__init__.py`, `workspace/protocol.py` : charge
  `contracts/workspace_protocol.v1.json` au premier import (fichier package dans le zip) ; expose
  `OPS`, `WIDGET_KINDS`, `CHART_TYPES`, `STEP_STATUSES`, les caps et `normalize_op(event_data) ->
  dict | None` (pur, never-raises, projection stricte sur le schema, troncature aux caps).
- `workspace/reducer.py` : `empty_state()`, `apply(state, event) -> state` (pur, Python 3.9,
  meme semantique que le reducer JS ; teste par les MEMES fixtures JSON que le front, voir E).
- `streaming.py` : branche `eventKind == "WORKSPACE"` -> `normalize_op` -> `yield {"type":
  "workspace", ...}` ; `_normalized_artifact_event` (legacy) conserve.

### C.2 Worker : `agents/stream_manager.py`

- Accumule `ws_state = reducer.empty_state()` ; chaque event `workspace` est applique ET relaye en
  live (compte dans `MAX_LIVE_EVENTS`, borne separee `MAX_WORKSPACE_EVENTS = 80`).
- A la fin (normal, stop utilisateur, erreur) : `ws_state["status"]` positionne, verification des
  `sql_id` contre `sql_list` (`binding: "orphan"` sinon), puis
  `workspaces_storage.save_workspace(exchange_id, user_id, session_id, ws_state)` best-effort, UNE
  ecriture par run. Si le run n'a emis AUCUNE operation workspace : pas de ligne (le front affiche
  alors le mode V1.3 : reponse seule).
- Compat : les events `artifact` legacy continuent d'alimenter `webapp_artifacts_v1` (D3).

### C.3 Stockage : `storage/workspaces.py` + `storage/migrations.py`

Nouvelle table (CREATE TABLE IF NOT EXISTS, nom logique `webapp_workspaces_v1`, prefixe PROJECT_KEY
par `physical_table`, zero ALTER, zero DROP) :

```sql
CREATE TABLE IF NOT EXISTS {full_table} (
    exchange_id       TEXT      PRIMARY KEY,
    user_id           TEXT,
    session_id        TEXT,
    protocol_version  SMALLINT  NOT NULL DEFAULT 1,
    status            TEXT,
    workspace         TEXT,
    created_at        TIMESTAMP NOT NULL DEFAULT now()
)
```

- `save_workspace` : UPSERT owner-stamped, `sql_value` partout, `SET LOCAL statement_timeout 30000`,
  `COMMIT`, cap `MAX_WORKSPACE_JSON_CHARS = 200_000` (sinon ecriture sautee + warning).
- `read_workspace(user_id, exchange_id)` : owner-scope dans le WHERE, pre-queries read-only, JSON
  reprojete par `reducer.sanitize` a la lecture (defense en profondeur). Never-raises -> `None`.
- `sql_config.managed_tables()` enregistre la table (ecran admin stockage).

### C.4 Routes : `api/routes.py`

- `GET /owismind-api/workspace?exchange_id=` : `validate_required_exchange_id` ; lit le document ;
  joint par `sql_id` : `sql` (brut ; le front formate avec `sqlPretty.js`), `filters` (deja derives par
  `evidence/sql_explain.py`, best-effort), `result` (bloc capture 50 lignes, `results_by_sql` de
  `evidence_service.evidence_meta`), `data` Chart.js par widget chart/kpi (`chart_payload`). Reponse
  `{status, workspace, events?: null, resolved: {sql_id: {sql, filters, result, source_url}},
  widgets_data: {widget_id: {...}}}`. 404 `workspace_not_found` si aucune ligne (le front retombe
  sur `/evidence/meta` V1.3).
- `/conversation` : ajoute par ligne un booleen `has_workspace` (sous-requete EXISTS sur la table,
  owner-scope) pour afficher le bouton sans N appels.
- Aucune route d'ecriture exposee ; le front ne choisit jamais table/connexion/requete.

### C.5 Surete instance

Une ecriture par run ; lectures read-only + timeout ; aucune relance SQL sur `/workspace` (les
lignes completes passent par `/evidence/result-rows`, deja doublement garde) ; caps a l'ecriture et a
la lecture ; aucun thread/timer nouveau.

## D. Frontend (Vue 3 + Vite, `plugin/owismind/frontend/src`)

### D.1 Nouveaux modules

| Fichier | Role |
|---|---|
| `composables/workspaceModel.js` | Reducer PUR (`emptyWorkspace`, `applyWorkspaceEvent`, selecteurs `stepsWithProgress`, `widgetsByStep`, `provenanceFor(widget)`), constantes miroir du schema, teste `node:test` avec les fixtures partagees |
| `stores/workspace.js` | Etat par exchange : `{ live: reactive(state) par run, restored: {exchangeId, state, resolved, widgetsData}, open, activeTab, drawer }` ; `openForExchange(id)` via `fetchWorkspace` ; garde `seq` anti-reponse perime (idiome evidence.js) |
| `services/backend.js` | + `fetchWorkspace(exchangeId)` |
| `components/workspace/WorkspacePanel.vue` | Hote colonne droite, en-tete (titre run, sous-titre mission), 4 onglets : Plan, Journal, Tableau de bord, Donnees |
| `components/workspace/PlanList.vue` | Etapes, statuts, barres `done/total`, pastille orange "nouveau" |
| `components/workspace/JournalList.vue` | Notes horodatees groupees par etape, lien "voir la preuve" -> tiroir |
| `components/workspace/BoardGrid.vue` | Grille responsive de `WidgetCard` (1 colonne < 900 px, 2 au-dela, KPI en rangee) |
| `components/workspace/WidgetCard.vue` | Cadre commun (titre, commentaire, etape, bouton provenance) ; rend `ArtifactChart` / `ArtifactTable` / `ArtifactKpi` (reutilises tels quels) ou `WidgetText.vue` |
| `components/workspace/ProvenanceDrawer.vue` | Tiroir : sous-agent, outil, tache, duree, filtres (chips lecture seule), SQL joli (`sqlPretty.js`, bouton copier), `N sur T lignes` (`resultCountLabel`), lien "ouvrir dans Donnees" (drill Evidence sur ce `sql_id`) |
| `components/chat/WorkspaceSummary.vue` | Carte sous la reponse : mission, etapes (compteur), vignettes des widgets, bouton "Ouvrir l'espace de travail" |

### D.2 Branchement du flux live

- `useChatStream.runChatStream` gagne un parametre optionnel `onEvent(evt)` appele pour CHAQUE event
  avant `applyEvent` ; `applyEvent` continue d'ignorer `workspace` (reducer timeline intact, F8).
- `stores/chat.js` : `_runExchange` passe `onEvent` qui route `evt.type === 'workspace'` vers
  `workspace.applyLive(exch.id, evt)` ; au premier `plan.set` le panneau s'ouvre sur Plan (comme le
  dock Source Data, `openPanel({auto: true})` sans event analytics) ; a `run_done` l'onglet bascule sur
  Tableau de bord si des widgets existent.
- Restauration : `WorkspaceSummary` -> `workspace.openForExchange(id)` -> `GET /workspace` -> etat
  reduit + `resolved` + `widgetsData` ; rendu identique au live (meme composants, meme reducer).

### D.3 Colonne droite et cohabitation avec V1.3

- `AppLayout.vue` : la colonne droite accueille `WorkspacePanel` OU `SourcePanel` (exclusifs, meme
  regle que Evidence/Source aujourd'hui) ; `EvidencePanel` devient le contenu de l'onglet Donnees
  (chips, Table, Calcul, Sources : tout conserve, `evidence.open` est pilote par l'onglet actif pour
  ne pas casser le gate de scroll F13).
- Les onglets Chart/Table/KPI de `EvidencePanel` (F22) restent pour un exchange SANS workspace
  (historique V1.3, 404 sur `/workspace`) ; retires en Phase 3.
- Conserve tel quel : Source Data (dock, explorateur, Analyze), conversations (arbre, versions),
  admin, feedback, budget, benchmark, i18n (`extra.js`, cles `ws.*` fr+en).
- Retire en Phase 3 : `evidence.activeTab` artefacts, `_defaultTab`, `MessageAgent` "voir le chart".

### D.4 Style et tokens (decision D1)

Le mock utilise les MEMES noms de tokens que `styles/tokens.css` (`--r-xs/--r-sm/--r/--r-lg/--r-pill`,
`--fw-*`, `--orange`, `--orange-text`, `--surface-*`, `--border-strong`, `--elev-1`). Migration =
aucune renommage ; la charte V2 (`docs/CHARTE_V2_UI.md`, ecrite par WP-B a partir de
`docs/cadrage/CHARTE_ORANGE_UI.md`) acte : radius via tokens (4 a 12 px, pill pour chips et boutons
icone), un seul orange rare (pastilles 6 a 8 px, texte `--orange-text`), filets 1 px, aplats, pas de
degrade ni blur ni `color-mix`, titre d'ecran sous-dimensionne, ET l'aura orange du prompt conservee
(`--aura-orange`, F26, dans les deux etats). La "title bar 52x4" et le `border-radius: 0` global de
la charte V1.3 sont abandonnes sur les ecrans V2.

## E. Plan par phases, deux lots disjoints par phase

Regles communes : jamais deux agents sur le meme fichier ; contrat = `contracts/workspace_protocol.v1.json`
(lecture seule pour les deux ; toute evolution = nouvelle version `v2` proposee au lead) ; fixtures
d'events partagees `contracts/fixtures/*.json` (ecrites par WP-A en Phase 1, lues par WP-B) ; aucun
install ; pas de push.

Commandes de verification (depuis la racine du repo) :
- Backend : `python3 -m unittest discover -s OWIsMind_PRD_V2_0/plugin/owismind/tests -t OWIsMind_PRD_V2_0/plugin/owismind`
- Agents : `python3 -m unittest discover -s OWIsMind_PRD_V2_0/tests`
- Front tests : `cd OWIsMind_PRD_V2_0/plugin/owismind/frontend && node --test test/*.test.js`
- Front compile : `OWIsMind_PRD_V2_0/plugin/owismind/frontend/node_modules/.bin/vite build --outDir /tmp/owi_bc --emptyOutDir` puis `rm -rf /tmp/owi_bc` (jamais dans `resource/`)
- Harness visuel : `OWIsMind_PRD_V2_0/plugin/owismind/frontend/node_modules/.bin/vite --config dev-harness/vite.config.mjs` (port 5199) ; si le harness racine reste pointe sur V1_3, WP-B cree `OWIsMind_PRD_V2_0/dev-harness/` (copie) et y pointe le root frontend V2.

### Phase 1 : protocole, stockage, backend, board alimente localement (cette session)

**WP-A (backend + fixtures)**, fichiers (tous sous `OWIsMind_PRD_V2_0/plugin/owismind/`) :
- `contracts/fixtures/workspace_run_multi_facet.json` (chunks bruts orchestrateur : 2 sous-agents, 3
  SQL, plan 3 etapes, 1 chart + 1 table + 1 texte + 1 kpi, 4 notes), `workspace_run_stopped.json`,
  `workspace_run_orphan_widget.json`, et `contracts/fixtures/reduced/*.json` (etats attendus).
- `python-lib/owismind/workspace/{__init__,protocol,reducer}.py`
- `python-lib/owismind/agents/streaming.py` (branche WORKSPACE), `agents/stream_manager.py`
- `python-lib/owismind/storage/workspaces.py`, `storage/migrations.py`, `storage/sql_config.py`
- `python-lib/owismind/api/routes.py` (`/workspace`, `has_workspace` sur `/conversation`)
- `tests/test_workspace_protocol.py`, `test_workspace_reducer.py` (fixtures -> etats attendus),
  `test_workspace_storage.py` (stub DSS `_dss_stub.py`), `test_streaming_workspace.py`,
  `test_routes_workspace.py` (owner-scope, 404, orphan)
Gate : les 4 suites ci-dessus + la suite backend complete verte, sortie lue.

**WP-B (frontend + simulateur + charte)**, fichiers :
- `frontend/src/composables/workspaceModel.js`, `stores/workspace.js`, `services/backend.js`
  (ajout `fetchWorkspace` seulement), `composables/useChatStream.js` (`onEvent`), `stores/chat.js`
  (routage + ouverture auto), `components/workspace/*.vue` (D.1), `components/chat/WorkspaceSummary.vue`,
  `components/chat/MessageAgent.vue` (insertion de la carte), `components/shell/AppLayout.vue`,
  `components/evidence/EvidencePanel.vue` (mode "onglet Donnees"), `i18n/extra.js`, `styles/tokens.css`
  (si tokens manquants), `frontend/test/workspaceModel.test.js` (fixtures partagees + parite des
  constantes avec le schema lu sur disque), `test/i18nExtraParity.test.js`.
- `OWIsMind_PRD_V2_0/dev-harness/` (copie du harness racine pointee sur le frontend V2) :
  `mock/scenario.mjs` (scenario multi-facettes cadence emettant les events `workspace` conformes),
  `mock/api.mjs` (`/workspace`, `has_workspace`).
- `OWIsMind_PRD_V2_0/docs/CHARTE_V2_UI.md`.
Gate : `node --test` vert, compile Vite verte, captures harness (Playwright `dev-harness/tools/browse.mjs`)
des 4 onglets + tiroir + restauration ; revue `charte-orange-reviewer` avec la charte V2 en reference.

### Phase 2 : orchestrateur reel et finitions

**WP-A (agents)** : `GenAI/Agents/OWIsMind_orchestrator.py` (B.1 a B.4), `project-library/python/
owismind_hub/prompts/*` (persona plan-first), `owismind_hub/regenerate_seeds.py`, `registry.json`
(nouveaux `tool_labels`), `GenAI/Agents/*_expert.py` (row_count reel seulement),
`tests/test_orchestrator_workspace.py` (simulation du graphe avec faux Mesh : plan auto, refus
`result_id` inconnu, `prov.set` par sql_item, caps), `docs/DEPLOY_V2_0.md` (recoll DSS : 3 Code
Agents + hub + zip DEV `owismind_dev`).
**WP-B (frontend)** : reponsive mobile de la colonne droite (plein ecran < 900 px), onglet Donnees
pre-filtre sur le `sql_id` du widget, sidebar conversations (icone "espace de travail" si
`has_workspace`), accessibilite (focus, aria des onglets), analytics `webapp_events_v1` (events
`workspace_opened`, `provenance_opened`, whitelist cote `services/trackModel.js` ; cote backend le
whitelist `storage/events.py` est ajoute par WP-A Phase 2 dans sa liste de fichiers).
Gate : suites agents + backend + front vertes ; smoke DSS DEV par l'utilisateur (zip + recoll) avec
checklist `dss-deployer`.

### Phase 3 : retrait du legacy et validation prod

WP-A : retrait des alias `show_*`, de l'accumulation `artifact` legacy (table `webapp_artifacts_v1`
laissee inerte, jamais droppee), parite moteur natif si D5 l'exige. WP-B : retrait des onglets
artefacts de `EvidencePanel`, nettoyage `evidence.activeTab`. Gate : validation terrain clair ET sombre,
`/log-session`, promotion de branche (suffixe `-dev` : cette branche s'appelle deja `OWIsMind_PRD_V2_0`,
decision de nommage a confirmer, D9).

## F. Decisions ouvertes (recommandation en gras)

- **D1 Charte V2** : suivre le design (radius par tokens, deux a trois graisses, pas de title bar) +
  aura orange du prompt, formalise dans `docs/CHARTE_V2_UI.md` ; `CHARTE_ORANGE_UI.md` reste la
  charte des ecrans non refaits. **Oui.**
- **D2 Liaison widget -> SQL** : `result_id` obligatoire pour chart/table/kpi, aucun repli "dernier
  resultat". **Oui (c'est le bug V1.3 a tuer).**
- **D3 Transition legacy** : `ARTIFACT`/`show_*` acceptes en V2.0 (phases 1 et 2), retires en
  Phase 3. **Oui, pour pouvoir deployer le backend avant le recoll des agents.**
- **D4 Plan auto** : plan implicite `origin: auto` quand le modele saute `write_plan`. **Oui.**
- **D5 Moteur natif** : gele en V2.0 (pas d'operations workspace), flag conserve. **Oui.**
- **D6 Donnees de widget stockees** : jamais de lignes dans `webapp_workspaces_v1`, tout joint par
  `sql_id` a la lecture (extrait 50 lignes de `chat_v5`, suite via `/evidence/result-rows`).
  **Oui ; alternative rejetee : snapshot Chart.js dans le document (doublon).**
- **D7 Widget texte** : autorise sur le tableau de bord (facette "reponse textuelle"). **Oui.**
- **D8 Bornes** : `MAX_TOOL_LOOPS` 10, 12 widgets, 30 notes, 10 etapes, 200 Ko de document.
  **Oui, deadline par mode inchangee.**
- **D9 Nommage de branche** : `OWIsMind_PRD_V2_0` sans suffixe `-dev` deroge a la regle
  "une branche `-dev` puis promotion". **Renommer en `OWIsMind_PRD_V2_0-dev` jusqu'a validation.**
- **D10 Cohabitation `/workspace` et `/evidence/meta`** : deux routes en V2.0 (compat), fusion
  envisagee en V2.1. **Deux routes.**
