# Evidence Studio v1 — Design validé (2026-06-09)

> **Objectif produit** : donner un maximum de confiance à l'utilisateur en lui montrant, à la fin
> d'une réponse, **ce que l'agent a réellement fait** : la table SQL source, avec les filtres de la
> requête de l'agent appliqués visuellement, modifiables, en lecture seule.
>
> Périmètre **v1 volontairement réduit** (décision user : step by step) — la maquette
> (`maquette/assets-v5/workspace.js|css`) sert de référence visuelle mais n'est **pas** implémentée
> telle quelle. On complexifiera ensuite (onglets trace/coût, comparateur, etc.).
>
> Décisions actées avec l'user pendant le brainstorming :
> 1. **Whitelist admin + parsing** — le backend re-requête uniquement un dataset whitelisté par
>    l'admin, jamais le SQL de l'agent tel quel.
> 2. **Ouverture automatique animée** en fin de génération (effet « wow » premium piloté par la webapp).
> 3. **Fidélité stricte** — les lignes affichées = exactement le périmètre de l'agent ; les conditions
>    non interprétables deviennent une chip « condition avancée » verrouillée (fragment re-validé
>    strictement), sinon mode dégradé (SQL brut seul).
> 4. **Édition v1 = picker =/IN + retrait** — les comparaisons numériques/dates sont affichées
>    fidèlement mais non éditables (retrait possible) ; édition complète en v2.

---

## 1. Comportement utilisateur (v1)

- **Auto-open** : quand un run se termine proprement (`done`) et que la réponse contient au moins un
  `generated_sql` réussi **exploitable** (table whitelistée + parsing OK), la webapp ouvre le panneau
  automatiquement avec une animation : la conversation glisse à droite (largeur `convpaneW`, 480 px par
  défaut, redimensionnable — déjà persisté dans `ui.js`), l'Evidence prend le centre.
  Layout cible (= maquette `components.css:32`) : `sidebar | evidence (1fr) | conversation (--convpane-w)`.
- **Pas d'auto-open dégradé** : si le SQL n'est pas exploitable (table non whitelistée, parsing KO,
  run `stopped`/`error`), le panneau ne s'ouvre pas tout seul. Un **bouton par message** (visible sur
  tout message assistant ayant du SQL) ouvre le panneau pour cet échange — y compris en mode dégradé
  (SQL brut + row_count, sans table interactive).
- **Contenu du panneau** :
  - En-tête : titre, dataset source (label), `row_count` vu par l'agent (« l'agent a vu N lignes »),
    bouton fermer.
  - **Chips de filtres** dérivées du `WHERE` de l'agent :
    - chips `=` / `IN` : valeurs **éditables** via picker de valeurs distinctes (bornées serveur) ;
    - chips comparaison (`>`, `>=`, `<`, `<=`, `BETWEEN`, `LIKE`, `IS [NOT] NULL`, `!=`) : affichées
      fidèlement, **non éditables**, mais **retirables** ;
    - chip « condition avancée » (fragment non interprété) : verrouillée, retirable en bloc ;
    - ajout d'un nouveau filtre `=` / `IN` sur n'importe quelle colonne ;
    - bouton **« Version agent »** : reset des chips à l'état dérivé du SQL stocké.
    - État « modifié » visuellement distinct (bordure pointillée orange, idiome maquette
      `is-work` — règle de marque : orange `#ff7900`, jamais de vert).
  - **Table** : les vraies lignes re-requêtées en lecture seule. En-tête sticky, tri par colonne
    (clic), pagination 50 lignes/page (`LIMIT 51` → `has_more`, **pas de `COUNT(*)`** global).
  - **SQL repliable** en bas : SQL brut de l'agent + bouton copier.
- **Plusieurs SQL dans un échange** : v1 prend la **dernière requête réussie** (la requête finale de
  l'agent). Sélecteur multi-requêtes = v2.
- **Fraîcheur des données** : la re-requête est **live** — si la table a été rafraîchie depuis la
  réponse, les lignes peuvent différer. Le `row_count` d'origine de l'agent est affiché en référence
  pour rendre l'écart visible.

## 2. Backend — nouveau package `python-lib/owismind/evidence/`

Aucun changement de schéma SQL : tout est **stateless**, re-dérivé à la demande du `generated_sql`
déjà stocké dans `webapp_chat_v4` (liste JSON `{sql, success, row_count}`, décodée par
`parse_json_list`).

### 2.1 `evidence/sql_parse.py` — parseur pur (zéro import `dataiku` → testable `unittest`)

- **Tokenizer** simple (pas de regex naïve) : chaînes `'...'` avec échappement `''`, identifiants
  `"..."`, parenthèses, mots-clés insensibles à la casse.
- `extract_statement(sql)` : exactement **un** statement `SELECT` ; sinon → dégradé.
- `extract_table(sql)` : table du `FROM` (qualifiée schéma ou non, quotée ou non).
  **`JOIN` / plusieurs tables / sous-requête dans le FROM → mode dégradé** (v1 = requêtes mono-table).
- `parse_where(sql)` : décompose le `WHERE` en conjonctions **top-level jointes par `AND`**.
  Chaque conjonction est tentée comme prédicat simple :
  `{column, op, values}` avec `op ∈ {=, !=, >, >=, <, <=, IN, NOT IN, BETWEEN, LIKE, ILIKE, IS NULL, IS NOT NULL}`
  et valeurs littérales (chaîne, nombre, `NULL`). Tout le reste (fonctions, casts, sous-requêtes,
  arithmétique…) → **fragment avancé**. Un `OR` top-level → tout le `WHERE` devient un seul fragment avancé.
- `validate_fragment(text)` — validation stricte du fragment avancé avant toute ré-utilisation :
  refus de `;`, `--`, `/* */`, backslash, déséquilibre de quotes/parenthèses, longueur > 2000,
  et de tout mot-clé (frontière de mot, insensible à la casse) :
  `SELECT, UNION, INSERT, UPDATE, DELETE, DROP, ALTER, GRANT, REVOKE, COPY, CREATE, TRUNCATE, EXECUTE, CALL, DO, PG_, SET, INTO`.
  Fragment invalide → **mode dégradé** (jamais d'application partielle : fidélité stricte).
- `GROUP BY` / `ORDER BY` / `LIMIT` / agrégats du SELECT de l'agent : **ignorés** par conception —
  Evidence montre le *périmètre* (la table filtrée), pas l'agrégat.
- Sortie : `ParseResult {ok, table, schema, predicates[], advanced_fragment|None, degraded_reason|None}`.
  Chaque prédicat porte un `id` déterministe (index de conjonction) utilisé par le front pour
  référencer les chips verrouillées **sans jamais renvoyer de SQL**.

### 2.2 `evidence/service.py` — opérations owner-scopées

Toutes chargent d'abord l'échange **owner-scopé** (`WHERE exchange_id = … AND user_id = …`,
valeurs via `sql_value`) depuis `webapp_chat_v4`, puis re-parsent le dernier item `success` de
`generated_sql`.

- `evidence_meta(user_id, exchange_id)` →
  ```json
  {"available": true, "dataset": "<name>", "columns": [{"name": "...", "type": "..."}],
   "chips": [{"id": 0, "column": "...", "op": "IN", "values": ["..."], "editable": true}],
   "advanced": {"present": false, "display": null},
   "sql": "<sql brut>", "agent_row_count": 123}
  ```
  ou `{"available": false, "reason": "not_whitelisted|no_sql|parse_failed|join_unsupported|...", "sql": "...", "agent_row_count": ...}`.
  - **Whitelist** : pour chaque dataset du param `evidence_datasets`, résoudre la table physique via
    `dataiku.Dataset(name).get_location_info()` (+ schéma, variables projet résolues) et comparer au
    nom parsé (insensible à la casse, avec/sans schéma). Pas de correspondance → `not_whitelisted`.
  - **Colonnes** : `Dataset.read_schema()` (métadonnées seulement, pas de lecture de données).
- `evidence_rows(user_id, exchange_id, filters, kept_ids, include_advanced, page, sort)` →
  `{"rows": [...], "has_more": true, "page": 0}`.
  - Le front n'envoie **jamais** de SQL : seulement
    `filters = [{column, op ∈ {"=", "IN"}, values}]` (chips éditables, modifiées ou ajoutées),
    `kept_ids = [ids des chips verrouillées conservées]`, `include_advanced` (bool),
    `page`, `sort = {column, dir ∈ {"asc","desc"}}`.
  - Le serveur **re-dérive** les prédicats verrouillés et le fragment avancé depuis le SQL stocké
    (par `id`), ne garde que ceux listés, re-valide **tout** : colonnes ∈ schéma réel, ops
    whitelistés, valeurs via `sql_value`, fragment re-validé par `validate_fragment`.
  - Requête générée :
    `SELECT <colonnes du schéma, chacune pg_identifier> FROM <table> WHERE <conjonctions> [AND (<fragment>)] ORDER BY <col validée> <ASC|DESC> LIMIT 51 OFFSET <page*50>`.
  - **Bornes** : `page ∈ [0, 200]` · ≤ 20 filtres · ≤ 50 valeurs par `IN` · valeur chaîne ≤ 500 car.
    Tri par défaut : première colonne du schéma ASC (pagination déterministe).
  - Sérialisation : `rows_to_json_safe` (NaN→None, leçon L013).
- `evidence_distinct(user_id, exchange_id, column)` →
  `SELECT DISTINCT <col> FROM <table> WHERE <col> IS NOT NULL ORDER BY <col> LIMIT 100`
  (colonne validée contre le schéma) → `{"values": [...], "truncated": bool}`.

### 2.3 Exécution SQL — lecture seule

- `SQLExecutor2(dataset=dataiku.Dataset(<evidence_dataset>))` → la connexion du **dataset whitelisté**
  (pas la connexion de stockage chat). Zéro écriture, zéro `COMMIT`, zéro `pre_queries`.
- Sécurité instance : toutes les requêtes sont bornées (`LIMIT` systématique), une seule requête par
  appel HTTP, pas de cache mémoire non borné (le parse est trivial, `read_schema` = appel métadonnées).

### 2.4 Routes (`api/routes.py`)

- `GET  /owismind-api/evidence/meta?exchange_id=`
- `POST /owismind-api/evidence/rows` (body : exchange_id + spec ci-dessus)
- `GET  /owismind-api/evidence/distinct?exchange_id=&column=`
- Toutes via `resolve_identity(request.headers)` puis owner-scoping. Erreurs structurées
  `{"error": "<code>"}` (idiome existant). **Pas de route SQL générique** (règle non négociable n°3).

### 2.5 Paramètre webapp (`webapp.json`)

- `evidence_datasets`, type `MULTISELECT`, `getChoicesFromPython: true` (choix servis par
  `compute_available_connections.py` étendu — datasets SQL du projet uniquement, même filtre que
  `traces_dataset`). Liste vide = Evidence Studio désactivé (mode dégradé partout, pas d'auto-open).
  Optionnel, ne casse jamais le chat.

## 3. Frontend (Vue 3)

### 3.1 Store `stores/evidence.js`

État : `{open, exchangeId, meta, chips (état local éditable), rows, page, hasMore, sort, loading, loadingRows, error, modified (computed)}`.
Actions : `openForExchange(exchangeId, {auto})`, `close()`, `setChipValues(id, values)`,
`removeChip(id)`, `addFilter(column, values)`, `resetToAgent()`, `loadRows()`, `loadDistinct(column)`,
`setSort(column)`, `nextPage()/prevPage()`.

- `openForExchange` appelle `GET /evidence/meta` ; en mode `auto`, n'ouvre le panneau **que si
  `available`**. En mode manuel (bouton), ouvre aussi le mode dégradé.
- La logique pure (dérivation chips→payload `rows`, réconciliation meta→chips locales, état
  `modified`) vit dans `composables/evidenceModel.js` — **pur, sans Vue ni dataiku** → testable
  `node:test` (gotcha F11).

### 3.2 Composants `components/evidence/`

- `EvidencePanel.vue` — l'aside centre : en-tête, chips, table, SQL repliable, états
  loading/vide/erreur/dégradé.
- `EvidenceChips.vue` — chips + picker de valeurs distinctes (menu au clic, chargé via
  `loadDistinct`, les valeurs originales de l'agent restent sélectionnables même hors du top-100).
- `EvidenceTable.vue` — table sticky header, tri, pagination.
- `EvidenceSql.vue` — bloc SQL repliable + copier.

### 3.3 Intégration layout & animation

- `AppLayout.vue` : classe `with-evidence` → `grid-template-columns: var(--sidebar-w) 1fr var(--convpane-w)`
  (+ variante `sidebar-collapsed`), poignée de resize réutilisant `ui.convpaneW` (déjà persisté).
- Animation d'ouverture : transition de la grille si le navigateur anime `grid-template-columns`,
  sinon fallback : slide/fade du panneau (`transform` + `opacity`) et transition de la colonne
  conversation. **`prefers-reduced-motion` respecté** (comme la maquette).
- Thème : idiome `:global(body[data-theme="dark"] .x)` (gotcha F2), pas de `color-mix`.

### 3.4 Auto-open & bouton par message

- `chat.js` : au passage du run à `done`, si la version a au moins un item `sql.success` →
  `evidence.openForExchange(exchangeId, {auto: true})`. Jamais sur `stopped`/`error`.
- `MessageAgent.vue` : action « Voir les preuves » dans le footer des messages avec `v.sql.length > 0`
  → `openForExchange(v.exchangeId)` (manuel).
- Changement de conversation / suppression : `close()`.

### 3.5 i18n & styles

- Clés `ev.*` ajoutées dans `i18n/extra.js` (fr + en, clé-plate par locale — gotcha F6).
- Tokens existants (`tokens.css`), z-index : panneau dans la grille (pas d'overlay) ; menus du picker
  à `--z-menu`.

## 4. Sécurité & instance (invariants)

1. Le front n'envoie **jamais** table / connexion / SQL — uniquement `exchange_id`, des filtres
   structurés, des ids de chips, page/tri.
2. **Owner-scoping** systématique : l'échange est rechargé `WHERE user_id = <moi>` à chaque appel.
3. **Whitelist admin** : seuls les datasets du param `evidence_datasets` sont re-requêtables.
4. Re-validation serveur complète à chaque appel (colonnes ∈ schéma réel, ops whitelistés, valeurs
   `sql_value`, fragment `validate_fragment`).
5. **Lecture seule** : `SELECT` uniquement, aucune écriture, aucun `COMMIT`, aucune DDL.
6. **Bornes partout** : 50 lignes/page (+1 pour `has_more`), distinct ≤ 100, page ≤ 200,
   filtres ≤ 20, `IN` ≤ 50 valeurs, valeur ≤ 500 car., fragment ≤ 2000 car.
7. Pas de `COUNT(*)` global, pas de cache non borné, `read_schema` = métadonnées.
8. Aucune nouvelle table, aucun `ALTER` (idiome `_vN` non sollicité).
9. Python 3.9, mono-process supposé (inchangé).

## 5. Hors périmètre v1 (différé, ne pas implémenter)

Onglets Trace/Coût · graphiques · comparateur agent/utilisateur · barre de vérification animée ·
« Continuer avec l'IA » · recherche plein-texte · édition des bornes numériques/dates · sélecteur
multi-requêtes · totaux exacts (`COUNT(*)`) · seuil sémantique · Evidence pour réponses sans SQL.

## 6. Plan d'implémentation (étapes validées, chacune testée avant la suivante)

1. **Parseur pur** `sql_parse.py` + tests `unittest` TDD exhaustifs (quotes, `IN`, `BETWEEN`,
   `OR` top-level → avancé, `JOIN` → dégradé, injections, multi-statements, commentaires).
2. **Endpoints** meta/rows/distinct + param webapp + tests avec stub `dataiku`.
3. **Panneau statique** : layout 3 colonnes + animation + chips read-only + table paginée + SQL repliable.
4. **Édition des filtres** : picker distinct, retrait, ajout, « Version agent », état modifié.
5. **Auto-open animé** + bouton par message + i18n fr/en + dark + polish premium.

Validation : `py_compile` + `unittest` + `node:test` + `vite build` à chaque étape ;
`npm run dev` + screenshots pour les étapes visuelles ; validation finale en DSS par l'user
(upload via `/build-plugin` + `/package-plugin`).

## 7. Risques connus & réponses

| Risque | Réponse v1 |
|---|---|
| SQL LLM non parsable (formes imprévues) | Dégradé gracieux : SQL brut + row_count, jamais d'application partielle silencieuse |
| Table de l'agent non whitelistée | `not_whitelisted` → mode dégradé, message clair à l'admin dans la description du param |
| Données rafraîchies depuis la réponse | `row_count` agent affiché en référence ; écart visible |
| Fragment avancé = SQL généré par LLM ré-exécuté | Déjà exécuté une fois par le sous-agent ; re-validé strictement ; appliqué uniquement sur table whitelistée, en SELECT borné |
| Charge instance | Toutes requêtes bornées, lecture seule, pas d'agrégats coûteux, 1 requête/appel |
