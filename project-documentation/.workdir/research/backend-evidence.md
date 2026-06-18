# Pack de connaissances : Backend Evidence Studio + pipeline d'artefacts

> Zone assignee : backend Evidence Studio + pipeline d'artefacts (charts / tables / KPI).
> Toutes les references de code sont au format `chemin:ligne`. Code et identifiants restent
> en anglais (verbatim). Redige en francais technique.

## 0. Vue d'ensemble en une phrase

Evidence Studio est le panneau de "preuve" a droite du chat : il re-derive, de facon **purement
deterministe et sans aucun appel LLM**, comment une reponse d'agent a ete produite (badge de
confiance, sources, chips de filtre, explication metier, resultat exact capture, drill-down,
exploration de la table source paginee, SQL brut), puis ajoute les **artefacts** (chart / table /
KPI) que l'orchestrateur a demande d'afficher. Le SQL stocke par l'agent est la **source de
verite** ; rien de nouveau n'est ecrit au moment de la preuve (sauf les specs d'artefacts,
persistees une fois en fin de run).

Fichiers : `Plugin/owismind/python-lib/owismind/evidence/` (service, sql_parse, sql_explain,
capture, chart_payload, query_builders, whitelist, throttle) + `storage/artifacts.py` +
`docs/evidence-trust-layer.md`.

## 1. Separation signal vs donnee (principe central)

Le systeme separe rigoureusement le **signal** (ce que l'agent demande / declare) de la **donnee**
(les lignes reelles). Conse­quences concretes :

- L'orchestrateur emet un event `ARTIFACT` qui ne porte que la **SPEC** : `kind` (chart/table/kpi),
  `title`, et pour un chart `{type, x, y[]}`. **Jamais les lignes** : la donnee est le resultat
  `generated_sql` deja capture, reutilise via `/evidence/meta`. Un artefact coute "a few hundred
  bytes per exchange" (`storage/artifacts.py:1-13`).
- Le shaping Chart.js (`{labels, datasets}`) est fait **server-side en Python trusted**, pas par
  l'agent : "the agent only says x/y" (`evidence/chart_payload.py:1-14`). Une colonne mal tapee ou
  une cellule non numerique degrade vers un etat vide honnete au lieu d'un graphe casse.
- Le client n'envoie **jamais de SQL** : les chips editables voyagent en `{column, op, values}`,
  les chips verrouilles en ids re-derives server-side, et les colonnes de drill sont re-derivees
  du SQL stocke (`api/routes.py:643-651`, `evidence/service.py:1025-1058`).

## 2. Cycle de vie de la preuve (Run -> Capture -> Persist -> Prove -> Explore)

Decrit dans `docs/evidence-trust-layer.md:25-49`. Etapes :

1. **Run** : l'orchestrateur execute le plan ; chaque item SQL stocke est tague avec `sql_id`
   (`s{step}q{n}`), `step_index`, `agent_key`, `source_url`, `success`, `row_count`, et
   opportunistement un `result` capture.
2. **Capture** : `agents/streaming.py` normalise, puis `evidence/capture.py` re-borne tout au
   point d'ecriture (ne fait jamais confiance a l'amont).
3. **Persist** : le JSON borne est stocke dans la colonne TEXT `generated_sql` de
   `webapp_chat_v5` (**pas de migration**). La relecture `/conversation` **retire** le bloc
   `result` (le payload du thread reste leger) ; seul `/evidence/meta` le renvoie.
4. **Prove** : `GET /evidence/meta` re-derive tout du SQL stocke (parse, match dataset,
   explication, niveau de verification, resultat capture, disponibilite du drill).
5. **Explore / drill** : `POST /evidence/rows` re-interroge le dataset matche en read-only, par
   pages bornees ; le `drill` optionnel filtre vers les lignes contributrices d'un groupe apres
   re-validation server-side.

## 3. Les endpoints `/evidence/*`

Tous passent par `_evidence_guard()` (`api/routes.py:556-584`) : resolution d'identite (401 sinon),
storage configure (409 sinon), bootstrap de la table chat (500 sinon), puis **token-bucket par
user** (429 si flood). L'ordre place le gate apres le chemin auth/config bon marche.

### 3.1 `GET /evidence/meta?exchange_id=` (`routes.py:587-640`, `service.py:947-1022`)

Owner-scoped (l'echange d'un autre user = 404). Le client envoie **uniquement** `exchange_id` ;
table, connexion, SQL et matching dataset sont resolus server-side. La forme retournee (status `ok`
plus les cles ci-dessous) :

- `available` (bool), et en mode degrade : `reason` (code stable), `sql` (brut, best-effort),
  `verification: {level: "declared", result_captured: false}` (`service.py:958-968`).
- v1 (inchange) : `dataset`, `columns` ([{name, type}]), `chips` ([{id, column, op, values,
  editable}], la casing `column` est la casing LIVE du schema), `advanced: {present, display}`,
  `sql`.
- Trust layer (additif §2) : `source: {dataset, schema, table, url}` ; `sources` (liste des datasets
  distincts lus, le front rend un selecteur seulement si > 1 entree) ; `queries` (un resume par item
  stocke) ; `verification` (bloc deterministe) ; `explanation: {ok, steps}` ; `result` (bloc capture)
  ; `drilldown: {available, columns, reason}`.
- `artifacts` : ajoute par la route (`routes.py:617-632`). Pour chaque chart, `a["data"] =
  build_chart_payload(result_block, a["chart"])` ; pour chaque KPI, `build_kpi_payload(...)`. Best
  effort : un echec de lecture degrade vers `artifacts: []`, jamais un 500.

Une ligne de log d'observabilite par meta (`routes.py:633-639`) surface `level`, `result_captured`,
`drill_available`, `artifacts` (le niveau de verification est tout l'interet du trust layer).

### 3.2 `POST /evidence/rows` (`routes.py:643-671`, `service.py:1025-1090`)

Une page bornee (`PAGE_SIZE = 50`, `service.py:68`) reconstruite a partir de filtres STRUCTURES.
Le body porte `{exchange_id, filters, kept_ids, include_advanced, page, sort, drill, table}` valides
par `validate_evidence_rows_request`. Mecanique (`service.py:1038-1090`) :

- Chips verrouilles (non editables ET dans `kept_ids`) : re-derives via `_locked_condition`.
- `filters` (chips editables) : la colonne doit resoudre sur le colmap LIVE sinon
  `invalid_filter_column` (400) ; op normalise a `=` (1 valeur) ou `IN`.
- `include_advanced` + fragment present : `_advanced_condition` re-gate le fragment.
- `drill` : `_drill_conditions` (gate server-side, voir §6).
- `sort` optionnel sinon ORDER BY deterministe sur la 1re colonne du schema (caveat documente :
  type non triable -> `query_failed` ; ties repetables entre pages OFFSET, `service.py:1066-1071`).
- `LIMIT PAGE_SIZE+1` -> `has_more` sans `COUNT(*)` (`service.py:1079`, `query_builders.py:21-41`).

Retour : `{rows, has_more, page}`.

### 3.3 `GET /evidence/distinct?exchange_id=&column=&exclude_id=` (`routes.py:674-707`, `service.py:1093-1128`)

Valeurs distinctes bornees d'une colonne (le picker de chips). `DISTINCT_LIMIT = 100`
(`service.py:69`). Le picker montre les valeurs **dans le scope restant de l'agent** : les
predicats verrouilles et le fragment avance s'appliquent, mais **le chip en cours d'edition**
(`exclude_id`) ne se filtre jamais lui-meme (un chip comparatif `>=`/`BETWEEN` doit pouvoir
elargir au-dela de sa propre borne, `service.py:1107-1114`). `LIMIT DISTINCT_LIMIT+1` ->
`truncated`. Le DISTINCT+LIMIT tourne dans une sous-requete et seul le resultat borne est trie
(evite un tri complet de toutes les valeurs distinctes sur une grosse table,
`query_builders.py:44-64`). Retour : `{values, truncated}`.

## 4. sql_parse + sql_explain : analyse pure, ne leve jamais

### 4.1 `sql_parse.parse_select(sql)` (`evidence/sql_parse.py:525-633`)

**Best-effort** (decision user qui supersede la regle v1 strict-fidelity, `sql_parse.py:18-25`) :
le parse n'echoue jamais parce que la requete est "trop complexe". JOIN, GROUP BY, sous-requetes,
CTE, set-ops parsent tous ; le but est de recuperer les **tables source** et chaque predicat WHERE
qui s'y mappe. `ok` est False uniquement quand le texte n'est pas UNE seule instruction analysable
(vide, > `MAX_SQL_CHARS = 20000`, caracteres inconnus, commentaires, multi-statement, pas un
SELECT/WITH, parentheses desequilibrees).

Forme retournee : `{ok, reason, schema, table, tables: [{schema, table}], predicates: [{id, column,
op, values, editable, binding, scope_tables}], advanced: str|None}`.

Points cles :
- Tokenizer maison (`tokenize`, `sql_parse.py:97-117`) : rejette commentaires (`comment_unsupported`)
  et tout caractere inconnu (`tokenize_failed`). Les offsets pointent dans le **texte original** pour
  garder l'orthographe exacte de l'agent.
- Scoping par "scopes" SELECT (`_scan_scopes`, `sql_parse.py:414-489`) : chaque predicat porte
  `binding` (la table que son qualifieur resout) et `scope_tables` ; `predicates_for_table`
  (`sql_parse.py:636-653`) ne garde que ceux qui s'appliquent a la table matchee (un self-join garde
  les deux cotes, le filtre d'une autre table jointe est drop).
- Set-op top-level : seul le **premier bras** est analyse (`sql_parse.py:558-568`).
- `advanced` (fragment WHERE re-executable) **uniquement** pour un SELECT mono-table simple
  (`single`, `sql_parse.py:586`) : un fragment sliced d'un join referencerait d'autres relations.
- `EDITABLE_OPS = ("=", "IN")` (`sql_parse.py:181`) : seuls ces ops sont value-editables tels que
  parses (l'UI laisse editer n'importe quel chip, ce qui le convertit en =/IN).

`validate_fragment(text)` (`sql_parse.py:120-165`) est le **gate defensif final** d'un fragment
avant re-execution : pas de 2e statement, pas de mot banni (`_BANNED_FRAGMENT_WORDS`,
`sql_parse.py:60-64` : select/union/insert/update/delete/drop/.../set/into/returning/lateral), pas
de fonction `pg_*` (verifie sur identifiants nus ET quotes), pas de backslash (semantique
config-dependante), parentheses equilibrees, longueur <= `MAX_FRAGMENT_CHARS = 2000`. Modele de
confiance explicite : la securite ne repose **pas** sur le nommage mais sur le fait que le fragment
est agent-authored, re-valide a chaque requete, et seulement appose a un SELECT read-only borne sur
un dataset decouvert (`sql_parse.py:127-134`).

### 4.2 `sql_explain.explain_select(sql)` (`evidence/sql_explain.py:940-1117`)

Explication metier structuree + flags de completude deterministes. **NE LEVE JAMAIS** : tout le
corps est guarde, et `explain_select` wrappe `_explain` dans un try/except renvoyant
`_failed("explain_failed")` (`sql_explain.py:940-945`). Principe d'honnete : tout ce qui n'est pas
positivement compris degrade un flag ou produit un step `opaque` ; une explication fausse serait une
fausse preuve, une explication sous-evaluee est juste moins utile (`sql_explain.py:22-24`).

Forme : `{ok, reason, steps: [{kind, params}], where_complete, dropped_where, group_keys,
single_source, select_understood, has_set_op, has_recursive_cte, calc_resolved}`
(`sql_explain.py:9-20`). Enum de `kind` gele (frozen). Bornes : `MAX_STEPS = 15`, `MAX_PARAM_CHARS
= 80`, `MAX_OPAQUE_CHARS = 120`.

Reutilise les briques de `sql_parse` (tokenizer, `_try_simple`, `_split_conjuncts`,
`_read_table_ref`, `validate_fragment`) **sans modifier** sql_parse (son contrat est verrouille par
ses tests). Masque les commentaires en espaces length-preserving pour que le SQL commente s'explique
quand meme (`_mask_comments`, `sql_explain.py:78-87`).

Subtilites notables (anti-fausse-preuve) :
- `single_source` exige exactement une occurrence de table reelle ET aucun scope multi-ref/join
  (un self-join via CTE compte, `sql_explain.py:994-1002`).
- `calc_share` (part du total) n'est emis que pour EXACTEMENT `SUM(x) / SUM(x) OVER ()` avec un OVER
  vraiment vide (`sql_explain.py:692-705`) ; sinon ratio honnete.
- `agg_filtered` (`SUM(CASE WHEN ... THEN x END)`) : `ELSE 0` n'est neutre que pour SUM, pas AVG/
  MIN/MAX (`sql_explain.py:749-758`, `_parse_simple_case` `allow_else_zero`).
- `topn` exige un ORDER BY resolu ; un LIMIT sans ORDER BY resolu = `limit_arbitrary` (un echantillon
  arbitraire, jamais worde comme top-N, `sql_explain.py:1088-1101`).
- `group_keys` : seules les cles GROUP BY a **lineage identite** vers la colonne source (fin de la
  chaine CTE) sont gardees ; renvoyer le nom SOURCE (pas l'alias outer) garantit que le drill filtre
  la bonne colonne physique (`_column_traces_to_source`, `sql_explain.py:909-937`). Aggregations
  empilees ou set-op -> `group_keys` vide (`sql_explain.py:1080-1081, 1103-1107`).

## 5. capture.py : extraction + caps miroir (pure, sans dataiku)

Module **pur** (pas d'import dataiku/pandas) pour que chaque borne soit testable hors DSS et que
`storage.chat_v5` puisse l'importer sans cycle (`capture.py:1-23`). Trois responsabilites :

- `extract_result(outputs)` (`capture.py:128-211`) : extraction **opportuniste** des lignes exactes
  d'un span tool. La cle des lignes n'est **pas confirmee sur cette instance** ; les cles candidates
  sont probees dans l'ordre `_ROW_KEYS = ("rows","records","data","result_rows","values")`. Accepte
  list-of-lists (colonnes via `_COLUMN_KEYS` ou synthetiques `col_1..col_n`) ou list-of-dicts
  (colonnes = cles du 1er dict, ordre d'insertion). **Toute** autre forme -> `None` (absence honnete,
  jamais une invention). Le downstream surface alors `result_captured: false`.
- `cap_result(result)` (`capture.py:214-252`) : re-cap MIROIR au point d'ecriture, ne fait **jamais**
  confiance a un cap amont. Re-borne lignes/colonnes/cellules + budget serialise. Une forme non
  positivement `{columns: list, rows: list-of-lists}` est droppee (None).
- `cap_sql_list(items)` (`capture.py:269-341`) : borne toute la liste `generated_sql` avant
  persistance, **NE LEVE JAMAIS**. Ordre : (1) re-cap de chaque `result` + bornes structurelles par
  item (sql tronque a `MAX_ITEM_SQL_CHARS = 20000` avec flag `sql_truncated`, tags tronques) ; (2)
  garde les `MAX_SQL_ITEMS = 20` plus recents ; (3) si > `MAX_PERSISTED_TEXT_CHARS = 262144`, retire
  `result` du plus ANCIEN d'abord en **preservant le plus longtemps le result du dernier item
  reussi** (c'est la preuve montree). Les cles core (`_CORE_ITEM_KEYS`, `capture.py:59-60` : sql,
  success, row_count, sql_id, step_index, agent_key, source_url) ne sont JAMAIS retirees.

Caps (contrat gele) : `MAX_RESULT_ROWS = 200`, `MAX_RESULT_COLS = 50`, `MAX_CELL_CHARS = 256`,
`MAX_RESULT_JSON_CHARS = 100000` (`capture.py:33-49`). Tous les caps sont **STRUCTURELS** (lignes
droppees, flag `truncated` leve), jamais un marqueur texte dans le JSON (qui corromprait le decodage,
`capture.py:20-23`). `_normalize_cell` preserve bool avant int (bool est sous-classe d'int) et
stringifie nan/inf (pas des nombres JSON valides, `capture.py:71-84`). Idempotent.

## 6. Niveaux de confiance, badge, drill : le pipeline pur du service

Helpers **purs** (sans dataiku, unit-testes) de `service.py:147-532`.

### 6.1 Echelle de verification (`verification_level`, `service.py:238-258`)

Echelle deterministe (contrat gele §2, `docs/evidence-trust-layer.md:51-67`) :

| Niveau | Critere mecanique |
|---|---|
| `declared` | parse echoue / aucun dataset matche (claim de l'agent seulement) |
| `source_identified` | matche mais WHERE non evaluable (explain pas ok), ou rien mappe sans completude |
| `scope_partial` | matche + >=1 predicat mappe, completude cassee (drops listes) |
| `scope_exact` | chaque conjonct WHERE decompose + source unique + pas de set-op |
| `calc_decomposed` | scope_exact + calcul SELECT totalement compris (rien d'opaque) |

`result_captured` est **orthogonal** (lignes stockees presentes). Le badge UI mappe niveau x capture.
Les elements drop/non-mappes sont **listes, jamais caches**. Un explainer absent/qui echoue ne peut
que FAIRE BAISSER le niveau (adaptateur defensif `normalize_explain`, `service.py:171-209`).

`effective_where_complete` (`service.py:228-235`) : formule gelee = `explain.where_complete AND
colmap_dropped == 0`. `colmap_dropped` compte les predicats qui s'appliquaient a la table matchee
mais **ne resolvent pas sur le schema LIVE** (chacun elargit silencieusement le scope reconstruit).

`compute_verification` (`service.py:290-317`) assemble le bloc final : `{level, result_captured,
dropped_predicates (count exact), dropped_display (borne a MAX_DROPPED_DISPLAY = 10),
single_source, where_complete, select_understood}`.

`safe_explain` (`service.py:212-225`) : appelle `_sql_explain.explain_select` quand le module est
disponible (import garde, `service.py:61-64` : si absent, degradation honnete au lieu de crash) ;
sinon shape not-ok honnete -> verification plafonne a `source_identified`, drill = `not_supported`.

### 6.2 Drill-down (`derive_drilldown`, `service.py:467-499` ; `build_drill_conditions`, `502-532`)

Offert UNIQUEMENT quand prouvablement fiable : explain ok, pas de CTE recursif, pas de set-op,
source unique (un self-join ne qualifie pas), WHERE reconstruit COMPLET, et >=1 cle GROUP BY identite
resolue sur le schema LIVE. `reason` est un code stable de refus : `not_supported`, `set_op`,
`multi_source`, `incomplete_where`, `no_group_keys`. Si > `MAX_DRILL_CONDITIONS = 8` cles, refus
(`not_supported`) plutot qu'une troncature silencieuse qui montrerait un sur-ensemble du groupe
(`service.py:494-498`).

Cote `/evidence/rows`, `_drill_conditions` (`service.py:908-924`) **re-derive** la liste drillable
du SQL stocke a chaque appel et ne fait que matcher la liste client contre cet ensemble server-side.
`build_drill_conditions` rejette toute colonne hors ensemble (`invalid_drill`, 400) ; `value None` ->
`IS NULL`, sinon egalite stricte. Le SQL de l'echange est aussi re-borne ici (mirror du validateur).

## 7. chart_payload.py : Chart.js + KPI depuis le resultat capture

`build_chart_payload(result, chart_spec)` (`chart_payload.py:86-162`). `result` = le bloc
`/evidence/meta` `result` ; `chart_spec` = le dict `chart` de l'artefact `{type, x, y[]}`.

Sortie succes : `{ok: True, labels: [...], datasets: [{label, data}], truncated: bool}` (+ `label`
pour un pie). Sortie vide honnete : `{ok: False, reason: ...}` avec `reason` dans `no_data`,
`bad_spec`, `x_not_found`, `y_not_found`, `no_numeric`. **Ne leve jamais** (stdlib only).

Mecanique :
- Garde l'etat vide si `result` non `captured`, ou pas de colonnes/lignes (`chart_payload.py:95-100`).
- Resolution de colonne **case-insensitive** par nom -> index (`_resolve`, `chart_payload.py:75-83`).
- `_to_number` (`chart_payload.py:29-66`) : coercition best-effort. Nombres passent ; strings
  formattees ('1 234,5', '12.5%', '€ 90', '1,234.56') parsees ; reconcilie virgule decimale vs
  separateur de milliers (le plus a DROITE de `,`/`.` est le decimal) ; nan/inf -> None. Les
  cellules sont d'habitude deja des nombres bruts (le formatage d'affichage est ailleurs), le chemin
  string est un filet.
- Bornes (securite instance + lisibilite) : `MAX_POINTS = 200` (x values), `MAX_SLICES = 12`
  (au-dela, queue regroupee en "Other"), `_LABEL_MAX_CHARS = 80`. `CHART_TYPES = ("line","bar","pie")`.
- Pie : une part par ligne sur la 1re colonne y resolue, seules les valeurs numeriques > 0 ;
  tri descendant, fold de la queue en "Other" (`chart_payload.py:124-146`).
- line/bar : un dataset par colonne y ; `None` laisse un trou ; si aucune valeur numerique ->
  `{ok: False, reason: "no_numeric"}` (`chart_payload.py:148-162`).

`build_kpi_payload(result, kpi_spec)` (`chart_payload.py:165-202`) : l'agent ne nomme que la colonne
`value` (+ `delta` / `delta_pct` optionnels) ; les chiffres sont lus de la **PREMIERE ligne** par du
code trusted. Sortie `{ok: True, label, value[, delta, delta_pct]}` ou `{ok: False, reason: ...}`.

Le tout est **construit dans la route** `/evidence/meta` (`routes.py:624-628`), pas par l'agent :
c'est tout l'interet de "the agent only says x/y".

## 8. query_builders, whitelist (auto-discovery), throttle, gardes read-only

### 8.1 query_builders (`evidence/query_builders.py`)

Constructeurs de texte SQL **purs** (sans dataiku). Contrat : les appelants passent des fragments
PRE-ECHAPPES (`sql_value` pour les valeurs, `pg_identifier` pour les identifiants) et des bornes
entieres - jamais d'input user brut (`query_builders.py:1-8`). `render_predicate` recoit les deux
fonctions de quoting en ARGUMENTS pour rester import-free et testable avec des stubs
(`query_builders.py:67-91`). `build_rows_query` impose un ORDER BY (la pagination OFFSET est non
deterministe sans), normalise la direction (tout sauf DESC -> ASC), et parenthese chaque condition
pour qu'un OR top-level dans un fragment ne change pas le sens de la conjonction AND
(`query_builders.py:21-41`).

### 8.2 whitelist (auto-discovery) (`evidence/whitelist.py`)

`match_whitelist(table, schema, candidates)` (`whitelist.py:12-32`) : renvoie le 1er candidat
matchant `(schema, table)`, ou None. **Aucun whitelist admin a configurer** : le service
auto-decouvre les datasets SQL du projet de la webapp et resout chacun a son `(schema, table)`
physique. Comparaison **case-insensitive** (les identifiants PostgreSQL non-quotes folds), un schema
manquant d'UN COTE est un wildcard (le SQL de l'agent ecrit souvent le nom de table nu). Regle de
securite : les appelants construisent la reference executee depuis le candidat RETOURNE (son schema/
table physique resolu), jamais depuis le `(schema, table)` parse - le match wildcard n'est sur que
sous cette regle (`whitelist.py:14-19`).

Cote service (`service.py:642-718`) : `_list_project_sql_datasets` ne garde que les datasets de type
`PostgreSQL` (`_SQL_DATASET_TYPES`, `service.py:90`), scope au projet propre. `_resolve_physical_table`
(`service.py:606-639`) prend la table de `get_location_info()['info']` (metadata, pas d'execution),
fallback sur l'API settings du dataset (`params.table`/`params.schema`), substitue `${projectKey}`,
LOG la forme reelle de `info` pour debug. Tout est **TTL-cache 300s** process-wide (`_dataset_candidates`
`service.py:705-718` ; `_dataset_columns` `service.py:745-766`) : le lock ne garde QUE l'acces dict,
jamais l'IO (round-trip metadata resolu HORS lock). DSS redemarre le backend au changement de config
webapp, ce qui cold-start le cache. Cap defensif `_MAX_EVIDENCE_DATASETS = 300`.

### 8.3 throttle (`evidence/throttle.py`)

Token-bucket par user pour les routes read-only. Coeur pur `take_token` (testable, deterministe en
`now`) ; `can_accept(user_id)` est le wrapper thread-safe process-wide appele par les routes.
`EVIDENCE_BUCKET_CAPACITY = 15`, `EVIDENCE_REFILL_PER_SEC = 10.0`, `_BUCKET_TTL_SECONDS = 300`
(buckets idle evinces pour borner le dict). Burst-tolerant (meta+rows = 2 tokens, un picker = 1, tous
human-paced) mais bloque un flood scripte soutenu qui pinnerait les worker threads du backend
mono-process polling (`throttle.py:1-7, 11-16`).

### 8.4 Gardes read-only + statement_timeout

Execution sur la connexion PROPRE du dataset matche (`SQLExecutor2(dataset=...)`, `_evidence_executor`
`service.py:769-771`), **pas** la connexion de stockage chat. `_EVIDENCE_TIMEOUT_PRE_QUERIES`
(`service.py:120-123`) : `SET LOCAL statement_timeout TO '30000'` + `SET LOCAL transaction_read_only
TO on`. `SET LOCAL` (pas `SET`) = TRANSACTION-scoped, une connexion JDBC poolee ne peut jamais les
reporter sur d'autres workloads. `transaction_read_only` est defense in depth : chaque requete batie
ici est deja un SELECT nu, mais une regression future echoue bruyamment au lieu d'ecrire. Identifiants
valides par `pg_identifier` (regex + cap d'octets, leve `ValueError`, `sql_config.py:210-227`) ;
valeurs par `sql_value` -> `toSQL(Constant(value), dialect=...)` ; bools routes vers les keywords nus
`true`/`false` (`_quote_value`, `service.py:126-135`, car `Constant(bool)` n'est pas un escaping
documente).

## 9. Pipeline d'artefacts : ARTIFACT event -> table -> /evidence/meta

### 9.1 De l'event a la persistance

1. L'orchestrateur appelle un tool `show_chart` / `show_table` / `show_kpi` -> un event DSS de
   `eventKind == "ARTIFACT"`. Le whitelist timeline droppe les champs, donc il est surface comme un
   event normalise dedie `artifact` par `agents/streaming.py` (`streaming.py:59-63, 398-403`).
2. `_normalized_artifact_event` (`streaming.py:142-191`) projette sur une forme STRICTE : `kind` in
   {chart, table, kpi}, `title` borne, chart `{type, x, y[]}` (y borne a 8), kpi `{value[, delta,
   delta_pct]}`. **La donnee n'est PAS la** : le front reutilise le result `generated_sql` via
   `/evidence/meta`, seul le SPEC voyage. Pure, ne leve jamais.
3. Le worker (`agents/stream_manager.py:385-399`) accumule au plus `MAX_ARTIFACTS_ACCUM = 8` specs
   (kind/title/chart/kpi) dans une liste, **pas ajoutee a la liste live** (le label timeline live a
   deja ete donne par l'`agent_event` ARTIFACT).
4. En fin de run (`stream_manager.py:449-457`), best-effort : `artifacts_storage.save_artifacts(
   exchange_id, user_id, artifacts)`. Un echec ne peut jamais affecter la reponse a l'ecran.

### 9.2 Stockage (`storage/artifacts.py`)

Table `webapp_artifacts_v1` (`ARTIFACTS_V1_LOGICAL`, `migrations.py:42`). DDL
(`migrations.py:149-156`) : `exchange_id TEXT PRIMARY KEY`, `user_id TEXT`, `artifacts TEXT`,
`created_at TIMESTAMP NOT NULL DEFAULT now()`.

`save_artifacts` (`storage/artifacts.py:101-137`) : `_sanitize` -> JSON -> UPSERT owner-stamped
(`INSERT ... ON CONFLICT (exchange_id) DO UPDATE`). Regles backend non-negociables
(`artifacts.py:9-14`) : SQL direct parametrise (`sql_value`, pas de f-string autour des valeurs),
`COMMIT` apres l'ecriture (`post_queries=["COMMIT"]`), owner-scoped a la lecture, best-effort partout
(un echec est logge une ligne et avale). L'UPSERT (write) ne peut pas etre read-only mais le meme
`statement_timeout 30000` borne le tiny single-row write (`artifacts.py:33-42`). Bornes :
`MAX_ARTIFACTS = 8`, `MAX_ARTIFACTS_JSON_CHARS = 16000`, `MAX_Y_SERIES = 8` (`artifacts.py:27-30`).

`read_artifacts` (`artifacts.py:140-166`) : owner-scoped (user_id dans le WHERE), read-only +
statement_timeout (`_READ_PRE_QUERIES`, `artifacts.py:38-41`). Le lookup est un hit PRIMARY KEY sur
`exchange_id` -> acces index O(1), jamais un full scan. Ne leve jamais : table absente, bad JSON,
erreur executor -> liste vide.

`_sanitize` (`artifacts.py:45-98`) est applique **a la fois en write ET en read** (defense in depth) :
droppe l'inconnu, borne les strings, garde au plus `MAX_ARTIFACTS` specs bien formees. Pure, ne leve
jamais.

### 9.3 Reshape final dans /evidence/meta

Comme vu en §3.1 (`routes.py:617-632`), la route lit les specs et y attache `a["data"]` calcule du
`result_block` de meta. Le front rend les onglets Evidence / Chart / Table (`ArtifactChart.vue` =
Chart.js, `ArtifactTable.vue` = resultat capture). C'est l'aboutissement de la separation signal/
donnee : le spec stocke (signal) + le result capture (donnee) sont recombines a la lecture.

## 10. Connexions au reste du systeme

- **Stockage chat** : la preuve lit `webapp_chat_v5.generated_sql` (`CHAT_V5_LOGICAL`) owner-scoped
  via `build_exchange_sql_query` (`query_builders.py:11-18`, toujours `user_id` dans le WHERE). La
  capture (`capture.cap_sql_list`) est appelee a l'ecriture par `storage.chat_v5`.
- **Agents / streaming** : `agents/streaming.py` (normalisation event ARTIFACT + merge des canaux
  trace/AGENT_DONE pour la capture) et `agents/stream_manager.py` (accumulation + persistance des
  specs, replay de `read_artifacts` dans le contexte d'ecran, `stream_manager.py:237-245`).
- **Conscience d'ecran** : `agents/context.py:164-221` (`build_screen_state`, `MAX_SCREEN_ARTIFACTS
  = 4`) construit un bloc "ON SCREEN NOW" depuis les artefacts rendus pour que l'agent sache ce que
  l'utilisateur voit (gate backend, panneau ouvert).
- **Source cliquable** : `source_url` est stampe par l'orchestrateur sur chaque item SQL capture
  (`capture._CORE_ITEM_KEYS`), propage additif jusqu'a `meta.source.url` via `source_url_for_run` /
  `with_source_urls` (`service.py:400-419`) -> rendu `<a target="_blank">` cote front. Le mapping
  par-dataset multi-source est differe (seul le cas mono-source attache l'url, `service.py:413-419`).
- **Validation / securite** : `security/validation.py:228` `MAX_EVIDENCE_DRILL = 8`, mirote par
  `service.MAX_DRILL_CONDITIONS = 8` (defense in depth si un futur appelant saute le validateur,
  `service.py:80-82`).

## 11. Gotchas / points incertains ou en flux

- **Cle des lignes du tool span non confirmee sur l'instance** (`docs/evidence-trust-layer.md:94-97`,
  `capture.py:11-12, 53-54`) : tant que non verifie sur une vraie trace stockee, les captures peuvent
  etre absentes -> `result_captured: false`, le panneau reste utile mais sans chart/result. C'est le
  point le plus incertain de toute la zone.
- **Multi-source** : seul le 1er bras d'un UNION/INTERSECT/EXCEPT est analyse ; les agregations sur
  joins (self-joins inclus) sont expliquees mais jamais drillables ; les valeurs window (rank,
  running totals) expliquees mais non re-verifiables (`docs/evidence-trust-layer.md:98-102`).
- **Re-execution = donnee d'aujourd'hui** : `/evidence/rows` montre les donnees actuelles ; seules
  les lignes capturees sont "ce que l'agent a utilise" (`docs/evidence-trust-layer.md:101`).
- **Echanges historiques (pre-v2)** : pas de tags/result -> la preuve degrade gracieusement.
- **Default ORDER BY** : sur la 1re colonne du schema ; type non triable -> `query_failed`, ties
  repetables entre pages OFFSET (trade-off v1 assume, `service.py:1066-1071`).
- **Memoire courte (CONTEXT.md)** : la zone agents (`dataiku-agents/`) est en cours d'edition LIVE
  par un autre ingenieur ; ce pack ne couvre QUE le backend python-lib Evidence et n'a pas inspecte
  le code agent cote `dataiku-agents/` (hors zone). Le label `show_kpi` apparait cote stockage/
  streaming/chart_payload mais l'emission cote agent n'a pas ete verifiee ici.
- **Doc legerement datee** : `docs/evidence-trust-layer.md` reference encore `webapp_chat_v4` /
  `orchestrator/orchestrator_agent.py` (chemins v2) alors que le code utilise `webapp_chat_v5`
  (`CHAT_V5_LOGICAL`) et que l'orchestrateur a ete renomme ; se fier au code pour les noms exacts.
