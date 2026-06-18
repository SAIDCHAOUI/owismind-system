# Knowledge pack : les recettes Flow qui fabriquent l'expertise du sous-agent

> Zone : `dataiku-agents/recipes/` (la couche DESIGN-TIME de l'agent revenus).
> Sources lues VERBATIM : `profile_dataset_recipe.py`, `build_value_index_recipe.py`,
> `build_value_catalog_recipe.py`, `recipes/README.md`, plus le code de consommation
> dans `agents/SalesDrive_revenue_expert.py` et les READMEs `dataiku-agents/README.md`,
> `agents/README.md`, `tools/README.md`, `CLAUDE.md`. Toute affirmation est
> citée `fichier:ligne`. Les identifiants, noms de tables et de fonctions restent
> en anglais d'origine.

---

## 1. Vue d'ensemble : pourquoi des recettes, et pourquoi DESIGN-TIME

Le sous-agent revenus `SalesDrive_revenue_expert` (`agent:bHrWLyOL`) est
**dataset-agnostique** : on le pointe vers un dataset de PROFILE et un dataset de
VALUE INDEX, et il devient expert de ce dataset
(`agents/README.md:80-82`). Cette expertise n'est PAS codée en dur dans l'agent
(règle P3, `CLAUDE.md` dataiku-agents, rule 1 ; `dataiku-agents/README.md:228`).
Elle est **fabriquée dans le Flow Dataiku** par trois recettes Python qui tournent
**design-time** (pandas autorisé), jamais au runtime du chat
(`recipes/README.md:3-6`).

Le schéma de fabrication (`recipes/README.md:8-12`, `dataiku-agents/README.md:35-39`) :

```
DESIGN TIME (Flow - construit une fois, rafraichi par un scenario)
  DRIVE_Revenues ──► [profile_dataset_recipe]    ──► DRIVE_Revenues_profile        (le "cerveau metier")        USED BY v3
                 ──► [build_value_index_recipe]  ──► DRIVE_Revenues_value_index    (grounding valeur exacte)    USED BY v3
                 ──► [build_value_catalog_recipe]──► DRIVE_Revenues_Value_Catalog  (catalogue d'alias riche)    ROADMAP only
  (+ dataset editable optionnel DRIVE_Revenues_profile_overrides : corrections humaines au profil)
```

**Le WHY du design-time.** Le profil LLM coute cher une fois mais s'amortit sur
chaque question future (`profile_dataset_recipe.py:67-70`). Au runtime le sous-agent
n'a plus qu'a LIRE ces artefacts (profil en mémoire, value index en SQL), donc
aucun cout LLM de profilage par requête, et aucune donnée brute n'est envoyée au
modèle au chat. Les recettes peuvent utiliser pandas et charger le dataset en
mémoire (design-time), alors que le runtime reste en SQL direct read-only.
C'est l'opposition explicite **design-time pandas vs runtime SQL** posée dans
`agents/SalesDrive_revenue_expert.py:5-6,25-26` et `recipes/README.md:3-6`.

**Le contrat fondamental données privées.** Les recettes envoient au modèle Mesh
UNIQUEMENT des métadonnées AGRÉGÉES (schéma, stats, valeurs énumérées de faible
cardinalité, quelques échantillons), JAMAIS les lignes brutes
(`profile_dataset_recipe.py:6-8,454-455` ; `dataiku-agents/README.md:94-96`).

---

## 2. Recette 1 : `profile_dataset_recipe.py` - le cerveau métier

### 2.1 Câblage Flow et entrées/sorties

(`profile_dataset_recipe.py:10-16`)
- INPUT 1 (requis) : le dataset a profiler (ex. `DRIVE_Revenues`).
- INPUT 2 (optionnel) : un dataset EDITABLE d'overrides humains, schéma
  `{key, field, value}`.
- OUTPUT 1 (requis) : le dataset profil, schéma `{key, payload}` (ex.
  `DRIVE_Revenues_profile`).

Point d'entrée DSS : `main()` (`profile_dataset_recipe.py:587-657`), via
`from dataiku import recipe` ; `recipe.get_inputs_as_datasets()` puis
`recipe.get_outputs_as_datasets()[0]` (`:590-593`). Le 2e input n'est lu que s'il
existe : `overrides_ds = inputs[1] if len(inputs) > 1 else None` (`:593`).

### 2.2 Deux passes : PASS A déterministe, PASS B LLM

**PASS A (zéro LLM, pandas)** : `profile_dataframe(df, schema_columns)`
(`:332-450`). Calcule pour chaque colonne : type DSS, `null_pct`, `distinct_count`,
valeurs énumérées verbatim si faible cardinalité, échantillons sinon, stats
numériques/temporelles, détection de format temporel
(`profile_dataset_recipe.py:17-24`). Tout est déterministe et testé.

Détails marquants de PASS A :
- **Énumération vs échantillons** : si `0 < distinct <= ENUM_MAX_VALUES (50)` et
  pas de format temps, la colonne devient `is_enum=True` et garde la liste
  complète `{v, n}` triée par `value_counts()` (`:419-428`). Sinon, on garde
  `SAMPLES_N=12` échantillons tronqués (`:429-431`). Une colonne TEMPS n'est
  jamais une énumération : lister 30 mois comme "valeurs autorisées" pollue le
  prompt UNDERSTAND et la carte SQL pour rien (`:417-419`).
- **Détection de date PHYSIQUE prioritaire** (`:373-396`) : un vrai datetime pandas
  ou un objet `datetime.date`/`Timestamp` est profilé `format="date"` MEME si le
  type DSS ou les échantillons string disent autre chose. Le commentaire
  (`:374-378`) explique le WHY : en DSS, une colonne PostgreSQL `date` profilée
  comme string cassait `LEFT(col, 10)` ; l'agent est désormais cast-safe (voir
  `period_predicate`, `SalesDrive_revenue_expert.py:1046-1059`) mais le profil
  doit "dire la vérité" sur le type.
- **Détection de format temporel** : `detect_time_format(dss_type, sample_values)`
  (`:140-163`) rend l'un de `TIME_FORMATS = (date, yyyy_mm_dd_str, yyyy_mm_str,
  yyyymm_int, year_int)` (`:84-85`), pure et défensive.
- **Election déterministe de la colonne temps** (`:441-449`) : candidats nommés
  d'abord (rang 0 si nom temporel via `looks_like_time_name`, rang 1 sinon), tri,
  le premier gagne ; la PASS B peut écraser cette élection.
- **Rôle par défaut** : `default_role(...)` (`:311-325`) = fallback déterministe
  quand le LLM est absent/silencieux (time / measure pour numérique / free_text si
  long / identifier si quasi-unique ou nom en `_id` / dimension sinon).

**PASS B (LLM via Mesh)** : `run_enrichment(...)` (`:521-580`). Appelle le modèle
`ENRICH_LLM_ID` (par défaut `openai:LLM-7064-revforecast:vertex_ai/gemini-2.5-pro`,
`:71`) avec 2 tentatives (`:530`), via l'API native de complétion Mesh :
`project.get_llm(ENRICH_LLM_ID).new_completion()` + `with_message(..., role=...)`
+ `execute()` (`:528-535`). Le prompt système `ENRICH_PROMPT` (`:457-495`) impose un
SEUL objet JSON, sans fences markdown, de forme exacte (descriptions EN/FR, grain,
metrics, default_metric, scenario, time, colonnes avec role/synonyms/display_column).
L'input utilisateur est COMPACT et agrégé : `build_enrichment_input(...)`
(`:498-518`) liste le row count, la colonne temps détectée, et par colonne :
type/distinct/nulls + (toutes les valeurs si enum, sinon 8 échantillons) + stats.
Aucune ligne brute.

**Validation déterministe de la sortie LLM** : `validate_enrichment(parsed,
column_names)` (`:183-259`) ne lève JAMAIS et dégrade champ par champ : colonnes
inconnues rejetées, `agg` doit etre dans `KNOWN_AGGS` (`:82`), `role` dans
`KNOWN_ROLES` (`:80-81`), `format` dans `KNOWN_FORMATS` (`:83`), metrics qui
référencent une colonne absente rejetées (`:209-210`), etc. Le `default_metric`
retombe sur le premier metric valide si le nom donné n'existe pas (`:224-226`).
C'est la garantie "le LLM ne peut pas casser le contrat" : tout ce que le LLM a
écrit est marqué `llm_generated: true` (`:577`) pour signaler aux humains qu'il
faut relire (`:24`).

Le scénario (au sens versions de la même mesure : actuals/budget/forecast) est
spécialement géré : `ENRICH_PROMPT` explique (`:480-485`) que mélanger ses valeurs
dans un SUM double-compte, donc si une telle colonne existe il faut la déclarer et
choisir la/les valeur(s) la/les plus factuelle(s) en `default_values`. A la fusion
(`:553-561`), `scenario` reçoit `{column, values (toutes les valeurs réelles de la
colonne), default_values (intersection validée ou la 1ere)}` et la colonne reçoit
`role="scenario"`.

### 2.3 Le principe NON NÉGOCIABLE : les overrides humains gagnent toujours

`apply_overrides(dataset_payload, column_payloads, override_rows)` (`:273-291`)
applique les lignes `{key, field, value}` EN PLACE, **après** la passe LLM
(`profile_dataset_recipe.py:635`, "Human overrides ALWAYS win (applied last)").
- `key == "__dataset__"` -> écrit au niveau table (`:283-286`).
- `key` = nom de colonne connu -> écrit le champ ET marque
  `human_override = True` (`:287-289`).
- Clés/champs inconnus ignorés, jamais fatals (`:275`).
- `parse_override_value(raw)` (`:262-270`) parse en JSON si possible
  (`'["a","b"]'`), sinon string brute trimée.

C'est le mécanisme qui fait la QUALITÉ (`recipes/README.md:49-54`) : on crée un
dataset editable `DRIVE_Revenues_profile_overrides` `{key, field, value}`, on
l'ajoute comme 2e input, on re-run. On y règle le scenario default (ACTUALS), la
devise du metric, les paires d'affichage, les synonymes. Comme les overrides sont
appliqués EN DERNIER, ils **survivent aux re-runs** : un re-profilage régénère
PASS A + PASS B mais les corrections humaines sont ré-appliquées par-dessus a
chaque fois. C'est ce qui rend le rafraichissement sans peur (voir §5).

Signal gratuit supplémentaire (`:611-616`) : les descriptions de colonnes déjà
saisies dans l'UI DSS (`comment`) sont récupérées comme `description_en` si vide.

### 2.4 Le contrat de sortie : PROFILE CONTRACT v1 (GELÉ)

(`profile_dataset_recipe.py:34-51`, `dataiku-agents/README.md:154-155`,
`CLAUDE.md` dataiku-agents rule 2)

Le dataset profil = des lignes `{key: str, payload: str(JSON)}`. `PROFILE_VERSION
= 1` (`:78`). Écriture finale (`:649-655`) : une ligne `__dataset__` + une ligne
par colonne, `payload = json.dumps(..., ensure_ascii=False, default=str)`.

**Ligne `__dataset__` (table-level)** (`:34-43,337-344`) :
```
{profile_version, dataset_name, generated_at, row_count,
 description_en, description_fr, grain,
 default_metric, metrics: [{name, agg, column, format, unit?, label_fr, label_en, description}],
 scenario: {column, values, default_values} | null,
 time: {column, format, min, max} | null,
 notes: [str]}
```

**Ligne `<column>` (column-level)** (`:44-48,356-363`) :
```
{name, dss_type, role, description_en, description_fr, synonyms,
 null_pct, distinct_count, is_enum, values: [{v, n}], samples,
 stats, display_column, groupable, indexed, llm_generated, human_override?}
```
`time.format` est l'un de `date | yyyy_mm_dd_str | yyyy_mm_str | yyyymm_int |
year_int` (`:49-51`).

### 2.5 Comment ce profil est consommé au runtime

Le sous-agent lit ce contrat via la classe `Profile`
(`SalesDrive_revenue_expert.py:304-389`), "In-memory view of the profile dataset
(contract v1)". Chargement : `_get_profile()` (`:2197-2209`) lit
`PROFILE_DATASET = "DRIVE_Revenues_profile"` (`:82`) via `_read_dataset_rows`
(`:412-425`, iter_tuples sans pandas, fallback get_dataframe), puis
`parse_profile_rows(rows)` (`:391-409`) reconstruit le `__dataset__` + les colonnes
(lignes JSON invalides ignorées ; None si `__dataset__` manquant = profil
inutilisable). Cache TTL en process : `PROFILE_TTL_SECONDS = 600` (`:140,2201`).

Usages clés des accesseurs `Profile` :
- `metrics` / `metric(name)` / `default_metric` (`:316-330`) - alimentent
  UNDERSTAND et le RENDER.
- `scenario` / `time` (`:332-344`) - pilotent les filtres SQL (period_predicate).
- `groupable_columns()` (`:355-361`) - les axes de breakdown valides.
- `match_column(raw)` (`:366-381`) - résout une désignation user/LLM en nom de
  colonne canonique via exact / insensible casse-espace / synonymes.
- `column_priority(name)` (`:383-389`) - priorité de désambiguisation : override
  explicite `ambiguity_priority` d'abord, sinon colonne la plus SPÉCIFIQUE
  (`distinct_count` élevé) gagne.

**Devise dérivée du nom de colonne (pas de config profil)** :
`metric_unit(metric)` (`:1030-1043`) rend l'unité d'affichage du metric : son
`unit` explicite, sinon un symbole de devise INFÉRÉ du nom de la colonne montant
via `_CURRENCY_BY_CODE = {"eur": "€", "usd": "$", "gbp": "£", "jpy": "¥", "chf":
"CHF"}` (`:1027`) et une regex frontière `(^|[_-])eur($|[_-])` (`:1040-1042`).
Donc `amount_eur -> €` sans aucune config profil (`recipes/README.md:34` confirme :
"the `metric_unit` derives the `EUR` currency from this column name"). PASS B peut
aussi proposer `unit` directement dans le prompt (`:469`,`:215-218`), qui prime.

**Gotcha important : le flag `indexed`.** Le profil écrit toujours
`indexed=False` (`profile_dataset_recipe.py:361`) et AUCUNE des trois recettes ne le
passe a `True` (grep : seules occurrences = la valeur par défaut). Cote runtime,
`Profile.indexed_columns()` (`:363-364`) filtre sur `c.get("indexed")` et
`_resolve_terms` log un WARNING explicite quand il n'y a aucune colonne indexée :
"profile has NO indexed columns; candidate filtering disabled"
(`:2266-2272`). Le code dégrade alors gracieusement (toutes les colonnes
deviennent candidates : `:2354-2355`). Pour activer le filtrage par colonne
indexée, il faut donc poser `indexed=true` via un OVERRIDE humain sur les colonnes
voulues (le seul chemin documenté pour mettre un champ a true en dehors du LLM).
C'est un point a confirmer/expliciter (voir §7 gaps).

---

## 3. Recette 2 : `build_value_index_recipe.py` - le grounding par valeur exacte

### 3.1 Le rôle et le câblage

(`build_value_index_recipe.py:1-26`) Construit le "value index" : chaque valeur
distincte de chaque colonne texte groundable, avec sa forme normalisée. Le
sous-agent l'interroge au runtime (SQL read-only) pour résoudre les termes métier
que les users tapent ("algerie telecom", "halys", "ipl") en valeurs de cellule
EXACTES et leur colonne. Le WHY (`:6-9`) : le text-to-SQL est sensible a la
casse/aux accents, le grounding est ce qui empeche les résultats vides silencieux.

Câblage (`:11-15`) :
- INPUT 1 (requis) : le dataset a indexer (ex. `DRIVE_Revenues`).
- OUTPUT 1 (requis) : le dataset index (ex. `DRIVE_Revenues_value_index`).
  ***** créer l'output SUR LA CONNEXION SQL du dataset source ***** pour que
  l'agent puisse l'interroger en SQL (`:12-15`, répété `recipes/README.md:61-62`,
  `dataiku-agents/README.md:91`). Connexion : `SQL_owi` (`recipes/README.md:62`).

Point d'entrée DSS : `main()` (`:129-150`).

### 3.2 Le schéma de sortie (GELÉ v1)

(`build_value_index_recipe.py:17-23`, consommé par le sous-agent) :
```
column_name  STRING   la colonne source de cette valeur
value        STRING   la valeur de cellule EXACTE, verbatim
value_norm   STRING   forme normalisee (minuscule, accents enleves, espaces collapses) = cle de match
occurrences  BIGINT   nombre de lignes de cette valeur dans la source
```
Ordre d'écriture explicite (`:146-148`) :
`pd.DataFrame(rows, columns=["column_name", "value", "value_norm", "occurrences"])`.
Volume observé : ~3.6 k lignes (`recipes/README.md:56`).

### 3.3 Sélection déterministe des colonnes a indexer

`should_index_column(name, dss_type, distinct_count, row_count, avg_len)`
(`:67-85`) : indexe les colonnes dont un user pourrait NOMMER une valeur. Skips :
numériques/dates (`:74`), distinct=0 ou > `MAX_VALUES_PER_COLUMN=20000` (`:76`),
free text si `avg_len > FREE_TEXT_AVG_LEN=120` (`:78`), ids quasi-uniques longs
(`distinct/rows >= ID_UNIQUENESS_RATIO=0.95` ET `row_count>1000` ET `avg_len>24` :
`:80-84`). Overrides manuels : `INCLUDE_COLUMNS` / `EXCLUDE_COLUMNS` (`:40-41`,
appliqués en tete `:70-73`).

`build_index_rows(df, dss_types)` (`:88-122`) : par colonne retenue, fait
`value_counts()` sur la version string nettoyée et émet une ligne par valeur, en
sautant `occurrences < MIN_OCCURRENCES=1` ou `len(value) > MAX_VALUE_CHARS=200`
(`:113`), borné a `MAX_VALUES_PER_COLUMN` (`:119-120`).

### 3.4 La normalisation PARTAGÉE et GELÉE (la clé de match)

`norm_value(value)` est IDENTIQUE dans les deux recettes
(`profile_dataset_recipe.py:99-104` ; `build_value_index_recipe.py:60-64`) et dans
le resolver de l'agent (`_norm`, `SalesDrive_revenue_expert.py:449`). Algorithme :
NFKD -> encode ascii ignore -> decode -> `re.sub(r"\s+", " ", strip().lower())`.
C'est testé que les deux recettes produisent la MEME sortie
(`tests/test_profiler.py:69-75`, "FROZEN contract shared by both recipes + the
agent"). Si on change cette normalisation d'un cote sans l'autre, le grounding
casse silencieusement : c'est pour ca qu'elle est GELÉE.

> NOTE : `build_value_catalog_recipe.py` a une normalisation DIFFÉRENTE
> (`norm`, `:170-177`) qui ENLÈVE aussi la ponctuation (`[^a-z0-9]+ -> espace`).
> C'est cohérent car le catalogue est un artefact séparé (roadmap) avec sa propre
> logique de match ; ne pas confondre avec le `norm_value` gelé du value index.

### 3.5 Comment le value index est consommé au runtime (RESOLVE)

Le grounding n'est **PAS un tool** : c'est du SQL inline read-only sur le value
index (`CLAUDE.md` dataiku-agents ; `agents/README.md:91-93`). Méthode
`_resolve_terms(profile, base_terms, trace)`
(`SalesDrive_revenue_expert.py:2259-...`). Mécanique :
1. Résout la table SQL de l'index via `get_location_info().info.quotedResolvedTableName`
   (`:2262-2265`) - lève si l'index n'est pas SQL (d'ou l'obligation de le créer
   sur la connexion SQL).
2. **Pass 1 (exact normalisé, une requete pour tous les termes)** : `SELECT
   column_name, value, value_norm, occurrences FROM <index> WHERE value_norm IN
   (...) LIMIT N` (`:2282-2287`), littéraux quotés via `_sql_quote_literal`.
3. **Pass 2 (fuzzy/substring, séquentielle)** pour les termes non matchés :
   `... WHERE value_norm LIKE %s ESCAPE '\' ORDER BY occurrences DESC LIMIT
   FUZZY_CANDIDATES_LIMIT (40)` (`:2313-2321`). Séquentiel par sécurité instance :
   `SQLExecutor2` concurrent non garanti thread-safe, gain marginal (`:2306-2310`).
4. **Last chance** : une tranche TERM-INDÉPENDANTE `ORDER BY occurrences DESC LIMIT
   LAST_CHANCE_SCAN_LIMIT (5000)` récupérée AU PLUS UNE FOIS par requete et
   réutilisée (`:2329-2345`), pour les termes a grosses fautes de frappe.
5. Classement `rank_candidates(term_norm, rows)` (`:802`) par similarité difflib,
   puis politique de désambiguisation (`refine_ambiguous`, `agents/README.md:91-100`).

L'exécution SQL passe par `_run_sql` (`:2229-2253`) en read-only strict :
`SQL_PRE_QUERIES = ["SET LOCAL statement_timeout TO '30000'", "SET LOCAL
transaction_read_only TO on"]` (`:156-157`).

---

## 4. Recette 3 : `build_value_catalog_recipe.py` - le catalogue riche (ROADMAP)

### 4.1 Statut : construit mais NON câblé en v3

Le header de la recette est explicite (`build_value_catalog_recipe.py:4-16`) : ce
catalogue alimente le Custom Python tool `Drive_Revenues_resolve_filter_value`, qui
n'est PAS câblé dans le sous-agent v3 actuel (`agents/SalesDrive_revenue_expert.py`),
lequel grounde via SQL inline sur `DRIVE_Revenues_value_index`. L'adoption du
catalogue + resolver Python comme chemin de grounding est la PROCHAINE étape
PLANIFIÉE, déférée a une session dédiée
(`recipes/README.md:64-77` ; `tools/README.md:74-88` ;
`dataiku-agents/README.md:202-212`). Lancer la recette est inoffensif (elle écrit
seulement son propre output, utilisé par rien en v3 : `:14-16`).

> ATTENTION VERSION : `CLAUDE.md` (racine dataiku-agents) et `tools/README.md:61-70`
> indiquent que depuis le 2026-06-18 le tool managé `dataset_lookup` (`9FEzVZk`) ET
> son intent `lookup` ont été RETIRÉS, et que le remplacant prévu n'est PLUS
> `Drive_Revenues_resolve_filter_value` mais un nouveau Custom Python tool
> `attribute_lookup` (`tools/attribute_lookup_tool.py`, construit + testé mais pas
> encore câblé). Le catalogue Value_Catalog reste donc roadmap, mais sa place exacte
> dans la cible (catalogue comme fallback de suggestions plutot que chemin
> principal) a bougé : `dataiku-agents/README.md:204-212` décrit le catalogue
> comme "optional catalog fallback ... offers suggestions when nothing matches".
> Point en mouvement, a vérifier au moment d'écrire la doc finale.

### 4.2 Ce que le catalogue ajoute vs le value index

(`build_value_catalog_recipe.py:18-28,64-77` ; `recipes/README.md:64-72`)
- Un mécanisme `variants` : une valeur canonique atteignable par plusieurs phrases
  user ("indirect", "reseller", "vente indirecte" -> `Indirect_distribution/Resseler`).
- Des alias courts pour les `Account_name` longs (taper "Telesat" au lieu du nom
  complet).
- Des alias de concepts métier maintenus DANS la recette (en code, pas en YAML),
  via `BUSINESS_ALIASES` (`:82-136`) : indirect/direct -> `distribution_type`,
  gcp/gcs -> `sales_entity`, roaming hub -> `Product`.
- Un flag propre `is_alias` au lieu d'une complexité Python aval.

### 4.3 Le schéma de sortie (12 colonnes, ~4.9 k lignes)

(`build_value_catalog_recipe.py:29-42`, écriture `:434-453`,
`dataiku-agents/README.md:92` pour le volume) :
```
search_domain         : account | account_group | offer | business | alias
source_column         : colonne du variant dans DRIVE_Revenues (ou "alias")
target_column         : colonne a filtrer au moment SQL
target_value          : valeur a filtrer au moment SQL
matched_value         : le texte variant (ce que les users peuvent taper)
display_value         : le label canonique lisible
normalized_value      : matched_value normalise (cle de match)
frequency             : nb de lignes pour ce target (ou 99999 = ALIAS_FREQUENCY pour les alias)
canonical_account_name, canonical_carrier_code, parent_group : pour les lignes account
is_alias              : 1 si alias hand-crafted, 0 sinon
```
Output : `DRIVE_Revenues_Value_Catalog` (`:55`), source `DRIVE_Revenues` (`:54`).

Construction (sections numérotées) : 1. ACCOUNT RESOLVER avec alias courts
(`:238-354`), 2. OFFER RESOLVER sur `Product/Solution/SolutionLine/sirano_product`
(`:357-380`), 3. BUSINESS/SCENARIO RESOLVER sur
`Phase/booking_type/distribution_type/sales_entity/sales_zone` (`:383-406`), 4.
BUSINESS CONCEPT ALIASES (`:409-427`), 5. dédup + tri (`:430-453`). Décision
honnêteté notable (`:132-135`) : Voice et Messaging ne sont PAS ajoutés en alias
car ils n'existent pas comme catégories directes ; le resolver renverra
`unresolved_known_term` pour éviter une hallucination silencieuse sur des totaux.

`ALIAS_FREQUENCY = 99999` (`:58`) booste les alias hand-crafted pour qu'ils gagnent
sur les matchs fuzzy.

---

## 5. Le scénario de rafraichissement : régénérer les artefacts

(`build_value_index_recipe.py:25-26` ; `recipes/README.md:5-6,86-89` ;
`dataiku-agents/README.md:182-184`)

- Re-run les recettes (scénario : hebdomadaire ou après chaque refresh source) pour
  garder profil + index frais. L'agent lit TOUJOURS en live, donc **pas
  d'invalidation de cache nécessaire** ("the agent always queries live, no cache
  invalidation needed", `build_value_index_recipe.py:25-26`).
- Déploiement d'une recette (`recipes/README.md:82-89`) : Flow `+ Recipe -> Code ->
  Python` ; input `DRIVE_Revenues` (+ overrides optionnel pour le profil) ; output =
  dataset cible (le value index DOIT etre sur la connexion SQL) ; coller le code,
  revoir le bloc CONFIG ; Run ; ajouter un refresh scenario.
- **Idempotence + survie des overrides** : un re-profilage régénère PASS A + PASS B,
  puis ré-applique les overrides humains EN DERNIER (`profile_dataset_recipe.py:635`).
  Donc le rafraichissement ne détruit jamais les corrections métier : c'est le
  pilier de la confiance dans le cycle de refresh.
- Le cache runtime côté agent est un simple TTL en process (`PROFILE_TTL_SECONDS =
  600`, `SalesDrive_revenue_expert.py:140`) ; après un re-run de recette, le nouveau
  profil est repris au plus tard 10 min après (ou au prochain démarrage de
  process). Pas de couplage fort recette <-> agent.

---

## 6. Tests et garde-fous

Helpers PURS testés dans `dataiku-agents/tests/test_profiler.py`
(`profile_dataset_recipe.py:96`, `build_value_index_recipe.py:57`,
`recipes/README.md:92-96`) :
- `norm_value` partagé et identique entre recettes (`tests:65-75`).
- `detect_time_format` (`tests:79-109`).
- `validate_enrichment` : non-dict -> vide, colonnes/aggs/roles inconnus rejetés,
  default_metric fallback, count sans colonne, scenario/time colonnes doivent
  exister, paires d'affichage (`tests:114-167+`).
- `should_index_column` (sélection des colonnes a indexer).

Commande : `python3 -m unittest discover -s dataiku-agents/tests`
(`recipes/README.md:95-96`). NO INSTALL : ne PAS lancer ces commandes ici (mode
read-only) - elles sont citées comme contrat de test.

---

## 7. Connexions au reste du système, gotchas, et incertitudes

### 7.1 Comment cette zone se branche au reste

- **Sous-agent** (`agents/SalesDrive_revenue_expert.py`) : consomme le profil
  (UNDERSTAND + about_data + RENDER, `agents/README.md:84-123`) et le value index
  (RESOLVE, grounding inline SQL). CONFIG a régler en DSS : `PROFILE_DATASET`,
  `VALUE_INDEX_DATASET` (`:82-83`).
- **Tool SQL** : `revenue_semantic_query` (`v4oqA6R`) écrit ET exécute le SQL
  analytique ; le sous-agent lui passe une question maximalement groundée GRACE au
  profil + au value index (`tools/README.md:35-57`). Le profil/index ne contiennent
  jamais le SQL : le SQL appartient au semantic model (`dataiku-agents/CLAUDE.md`).
- **Orchestrateur** : ne détient jamais de donnée métier ; il route vers le
  sous-agent (`dataiku-agents/README.md:59-62`).
- **Webapp / Evidence** : dépend de contrats GELÉS, dont le PROFILE CONTRACT v1
  (`dataiku-agents/README.md:154-155`, `CLAUDE.md` dataiku-agents rule 2). Ne jamais
  renommer un champ du contrat, seulement ajouter.

### 7.2 Gotchas a documenter

1. **Le value index DOIT vivre sur la connexion SQL source** (`SQL_owi`), sinon
   `_resolve_terms` lève "value index dataset is not SQL"
   (`SalesDrive_revenue_expert.py:2262-2265`). C'est le piège de déploiement #1.
2. **Le flag `indexed` est toujours False** en sortie de recette
   (`profile_dataset_recipe.py:361`) ; aucune recette ne le passe a True. Le
   filtrage par colonne indexée est donc inactif par défaut (warning runtime,
   `:2266-2272`) jusqu'a ce qu'un override humain pose `indexed=true`. A clarifier
   dans la doc dev : est-ce voulu (filtrage opt-in via overrides) ou un trou ?
3. **Deux normalisations différentes** : `norm_value` (value index + profil + agent,
   GELÉ, garde la ponctuation) vs `norm` du catalogue (enlève la ponctuation). Ne
   pas les confondre.
4. **`ENRICH_LLM_ID` vide = pas de PASS B** : le profil reste déterministe,
   descriptions vides a remplir a la main (`profile_dataset_recipe.py:70,524-525`).
   Le default pointe `gemini-2.5-pro` (`:71`) ; a vérifier qu'il existe sur le Mesh.
5. **Cap mémoire** : `MAX_ROWS_IN_MEMORY = 2_000_000` (`:76`) tronque
   `get_dataframe()` ; sur un dataset plus gros, le profil est calculé sur un
   échantillon de tete (`:604-606`).
6. **Devise sans config** : `amount_eur -> €` dérive du NOM de colonne
   (`metric_unit`, `:1030-1043`). Renommer la colonne montant change la devise
   affichée.

### 7.3 Incertitudes / éléments en mouvement (a re-vérifier)

- **Roadmap du catalogue en flux** : les docs divergent légèrement. La recette
  (`:4-16`) et `tools/README.md:74-88` parlent du resolver
  `Drive_Revenues_resolve_filter_value` comme cible ; mais `CLAUDE.md`
  (dataiku-agents) et `dataiku-agents/README.md:204-212` indiquent que depuis
  2026-06-18 le remplacant est `attribute_lookup` et que le catalogue devient un
  fallback de suggestions. La cible exacte du grounding v.next est donc a confirmer
  avant d'écrire la doc utilisateur. (Cela ne touche PAS la zone recettes elle-meme,
  qui reste : profile + value_index câblés v3, value_catalog roadmap.)
- **Volumes** (~175 k lignes source, ~3.6 k value index, ~4.9 k catalogue) viennent
  des READMEs (`recipes/README.md:18,56,64`), pas mesurés ici.
- **`indexed=true` via override** : le mécanisme (`apply_overrides` peut écrire
  n'importe quel champ) le permet, mais aucun exemple d'override `indexed` n'est
  documenté ; a confirmer comme pratique recommandée.
