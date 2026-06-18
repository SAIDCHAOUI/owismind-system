# Knowledge pack : sous-agent revenus + tools + modèle sémantique

> Aire couverte : le sous-agent revenus (`SalesDrive_revenue_expert.py`), les
> tools DSS qu'il appelle, et le modèle sémantique aligné qui possède le SQL.
> Tout est ancré dans le code lu (chemins absolus + numéros de ligne).
>
> AVERTISSEMENT : le dossier `dataiku-agents/` est en cours d'édition par un autre
> ingénieur pendant la rédaction. Les chemins/contrats ci-dessous reflètent l'état
> lu le 2026-06-18. Les points marqués IN-FLUX peuvent bouger.

Fichiers sources principaux :
- `/Users/saidchaoui/projects/owismind/dataiku-agents/agents/SalesDrive_revenue_expert.py` (2913 lignes)
- `/Users/saidchaoui/projects/owismind/dataiku-agents/agents/README.md`
- `/Users/saidchaoui/projects/owismind/dataiku-agents/tools/attribute_lookup_tool.py` (464 lignes)
- `/Users/saidchaoui/projects/owismind/dataiku-agents/tools/README.md`
- `/Users/saidchaoui/projects/owismind/dataiku-agents/tools/semantic_model/build_aligned_semantic_model.py`
- `/Users/saidchaoui/projects/owismind/dataiku-agents/tools/semantic_model/update_aligned_semantic_model.py`
- `/Users/saidchaoui/projects/owismind/dataiku-agents/tools/semantic_model/README.md`
- `/Users/saidchaoui/projects/owismind/dataiku-agents/recipes/README.md`
- `/Users/saidchaoui/projects/owismind/dataiku-agents/tests/test_attribute_lookup.py`

---

## 1. Vue d'ensemble et identifiants canoniques

Le sous-agent revenus est un **Dataiku Code Agent** (env Python 3.11), pasté depuis
le repo (source de vérité). Identité :

- Fichier repo : `agents/SalesDrive_revenue_expert.py` ; nom DSS
  `SalesDrive_revenue_expert` ; id `agent:bHrWLyOL` (agents/README.md:11).
- Classe d'entrée DSS : `class MyLLM(BaseLLM)` ; point d'entrée
  `process_stream(self, query, settings, trace)` (ligne 2454). NB : la classe
  s'appelle bien `MyLLM` (contrat DSS du Code Agent, à ne pas renommer).
- Dépendances importées : stdlib + `dataiku` + `langgraph` uniquement (lignes
  57-73). Pas d'import du plugin. `from dataiku.llm.python import BaseLLM`.

Le sous-agent est **dataset-agnostique** : on le pointe sur un dataset PROFILE et
un dataset VALUE INDEX et il devient l'expert de ce dataset. CONFIG (section 1 du
fichier, lignes 77-153) :

- `PROFILE_DATASET = "DRIVE_Revenues_profile"` (le « cerveau métier », contrat v1).
- `VALUE_INDEX_DATASET = "DRIVE_Revenues_value_index"` (grounding de valeurs).
- `TARGET_DATASET = ""` (override optionnel ; défaut = `dataset_name` du profil).

Modèles LLM (LLM Mesh, lignes 91-98) :

- `GEMINI_FLASH_LITE_ID = "openai:LLM-7064-revforecast:vertex_ai/gemini-3.1-flash-lite"` (eco)
- `GEMINI_FLASH_ID = "openai:LLM-7064-revforecast:vertex_ai/gemini-3.5-flash"` (medium)
- `SONNET_ID = "openai:LLM-7064-revforecast:vertex_ai/claude-sonnet-4-6"` (high)
- `LLM_BY_MODE = {"eco": GEMINI_FLASH_LITE_ID, "medium": GEMINI_FLASH_ID, "high": SONNET_ID}`
- `DEFAULT_MODE = "eco"` (ligne 99).

Le **mode** (eco/medium/high) est propagé par l'orchestrateur via un token
`MODE:` injecté dans le contexte système, parsé par `forced_mode()` (ligne 485,
regex `\bMODE:\s*(eco|medium|high)\b`). En high, toute la pile est Sonnet.

---

## 2. Le pipeline du sous-agent : UNDERSTAND -> RESOLVE -> QUERY -> RENDER

Implémenté en **LangGraph `StateGraph`** (lignes 2884-2897). État typé
`ExpertState(TypedDict)` (ligne 2135). Le graphe est **linéaire** (pas d'écritures
parallèles, donc pas de reducers) : `START -> understand -> resolve -> query ->
render -> END`, avec des **arêtes conditionnelles** vers `END` à chaque étape via
le helper `route(next_node)` (ligne 2879) qui teste `state.get("done")`.

`process_stream` (ligne 2454) : récupère le projet, extrait l'instruction +
contexte (`_extract_input`, ligne 2900), charge le profil (cache TTL), résout le
mode, compile le graphe et streame en `stream_mode="custom"` avec
`config={"recursion_limit": 12}` (ligne 2486). Les events live passent par le
`get_stream_writer()` de LangGraph (appelé dans chaque noeud SYNC, ligne 2498).

### Étape 1 - UNDERSTAND (noeud `n_understand`, ligne 2497)

Responsabilité : transformer la question en UN objet JSON décrivant l'intent, sans
répondre et sans écrire de SQL.

- Un seul appel LLM, **`with_json_output` FORCÉ** (`_call_json_llm`, ligne 2392).
  Le schéma JSON (`build_understand_schema`, ligne 631) ancre les enums sur le
  profil (intents, valeurs de scénario...). Le prompt système
  (`build_understand_prompt`, ligne 660) est **GÉNÉRÉ depuis le profil** : métriques,
  scénarios, axes, synonymes, colonnes indexées.
- RATIONALE (ligne 2396-2402) : UNDERSTAND est une extraction déterministe, pas une
  tâche de raisonnement. Forcer le JSON désactive le reasoning pour CET appel, ce qui
  donne un parse propre et rapide au lieu d'une longue passe « thinking » que le
  parseur ne sait pas lire. Le reasoning reste actif là où il aide (routing
  orchestrateur, headline vérifiée). 2 tentatives : JSON natif puis prompt-only.
- Le résultat est validé/dégradé **déterministiquement contre le profil** par
  `validate_understanding` (ligne 494) - jamais contre des valeurs métier en dur.
  Champs de sortie : `scope` (data/out_of_scope), `language`, `intent`,
  `original_intent`, `metric`, `scenarios`, `period`, `periods`, `group_by`,
  `list_column`, `top_n`, `order`, `terms`, `clarification`.
- Intents connus (`KNOWN_INTENTS`, ligne 166) : `total`, `breakdown`, `top_n`,
  `share_of_total`, `compare_scenarios`, `compare_periods`, `trend`, `list_values`,
  `count_distinct`, `about_data`, `custom`. NB : l'intent `lookup` a été RETIRÉ
  (voir section 5) ; le code de `KNOWN_INTENTS` ne le contient plus, mais
  `agents/README.md:89` le liste encore (doc IN-FLUX/périmée).
- `original_intent` (ligne 518) garde l'intent classifié AVANT dégradation, pour
  l'observabilité et la note de transparence si une comparaison demandée n'a pas pu
  être construite.
- La **langue** est imposée par l'orchestrateur (`forced_language`, ligne 477, regex
  `USER LANGUAGE:\s*(fr|en)`) qui est autoritaire : il connaît la vraie langue du
  message user, alors que le sous-agent ne voit que la tâche auto-contenue (souvent
  en anglais).
- Branches terminales gérées dans le noeud : `out_of_scope` (texte déterministe),
  `clarification` (question courte), `about_data` (réponse depuis le profil, ZÉRO
  SQL, ZÉRO LLM via `build_about_answer`, ligne 2052).

### Étape 2 - RESOLVE / grounding (noeud `n_resolve`, ligne 2544)

Responsabilité : ancrer (« grounder ») les termes métier du user contre le catalogue
de valeurs réelles, et appliquer la politique de désambiguïsation.

**Le grounding n'est PAS un tool** : c'est du SQL inline read-only sur
`DRIVE_Revenues_value_index`, via la méthode `_resolve_terms` (ligne 2259). Détail
en section 3.

Flux du noeud :
1. Pour chaque terme, `parse_qualified_term` (ligne 780) détecte la forme qualifiée
   `VALUE (Column)` (ex. `IPL (Product)`) et mémorise la colonne préférée.
2. Émet l'event `_tool_start("resolve_filter_value")` (label d'event, PAS un vrai
   tool - ligne 2557) puis appelle `_resolve_terms`.
3. Applique `refine_ambiguous` (ligne 825) sur les statuts `ambiguous`.
4. Applique `defer_multicolumn_offer_terms` (ligne 883) : un terme d'offre ambigu sur
   >= 2 colonnes distinctes est reclassé `deferred` (déféré au modèle sémantique) ;
   une ambiguïté mono-colonne (deux entités distinctes) reste `ambiguous` -> demande.
5. Construit les filtres (`build_filter_clauses`, ligne 929). Si reste de l'ambigu /
   non résolu -> émet une clarification (`build_clarification`, ligne 951) et termine.
6. Sinon, thread les `offer_terms_for_model` (les déférés) dans l'état (ligne 2610).

### Étape 3 - QUERY (noeud `n_query`, ligne 2615)

Responsabilité : produire le SQL et l'exécuter. Travaille sur une COPIE de
l'understanding (le noeud rétrograde l'intent structuré -> `custom` sur plusieurs
fallbacks). Émet `_block("run_sql")` + `_tool_start("dataset_sql_query")` (labels).

Deux moteurs (`SQL_ENGINE`, ligne 125) :

- **`"semantic_tool"` (DÉFAUT)** : COMPOSE une question NL maximalement groundée
  (`build_semantic_question`, ligne 1466) puis la passe au tool DSS
  `revenue_semantic_query` (`v4oqA6R`) qui ÉCRIT ET EXÉCUTE le SQL. Détail en
  section 4. Le résultat est extrait du retour du tool par `extract_semantic_payload`
  (ligne 1694).
- **`"direct"` (fallback technique)** : seulement si `FALLBACK_TO_DIRECT = True`
  (ligne 126) et sur échec TECHNIQUE (pas un résultat vide, qui est une réponse
  valide). Le sous-agent construit lui-même son SQL read-only : templates
  déterministes par intent (`build_sql`, ligne 1122) ou, pour le long-tail `custom`,
  un LLM gardé (`SQLGEN_PROMPT` ligne 1258, `guard_custom_sql` ligne 1345, EXPLAIN
  dry-run + jusqu'à 2 réparations, `MAX_CUSTOM_SQL_ATTEMPTS = 3`).

### Étape 4 - RENDER (noeud `n_render`, ligne 2798)

Responsabilité : formater la réponse. Tout est formaté PAR CODE.

- Préfixe `[Scope]` (`build_scope_note`, ligne 1933) : ligne explicite scénario /
  période / entité / devise - une réponse en argent ne doit jamais être un nombre nu.
  Déterministe, sans chiffre, donc n'affecte jamais la headline vérifiée.
- Table markdown (`build_table`, ligne 1885) ; formats par
  `format_cell`/`format_number` (lignes 1818-1882, pilotés par le profil).
- Headline déterministe par défaut (`build_fallback_headline`, ligne 1965). Le
  flag `SUBAGENT_LLM_HEADLINE = False` (ligne 113) : par défaut PAS de headline LLM
  (l'orchestrateur écrit l'analyse). Si activé, la headline LLM est **vérifiée chiffre
  par chiffre** (`verify_headline`, ligne 2023 + `allowed_number_set`, ligne 1993) :
  un seul nombre non vérifiable -> headline rejetée, repli déterministe.
- Notes de transparence : `build_disclosure_notes` (ligne 1438, offre multi-niveaux)
  et `DEGRADED_COMPARISON_NOTE` si une comparaison demandée n'a pas pu être construite.
- Émet l'`AGENT_RESULT` final.

---

## 3. Grounding inline (PAS un tool) : `_resolve_terms` sur `value_index`

Méthode `_resolve_terms(self, profile, base_terms, trace)` (ligne 2259). C'est le
coeur du grounding et il est crucial de comprendre que **ce n'est PAS un appel de
tool DSS** : c'est du SQL direct via `dataiku.SQLExecutor2` sur le dataset
`DRIVE_Revenues_value_index`.

Source de données : `DRIVE_Revenues_value_index` (recipes/README.md:56), schéma
`{column_name, value, value_norm, occurrences}`, ~3.6 k lignes - chaque valeur
distincte de chaque colonne texte groundable + sa forme normalisée. La normalisation
`value_norm` est GELÉE et partagée avec `_norm` du sous-agent (ligne 449 : NFKD,
ascii, minuscules, espaces collapsés). Le dataset DOIT être sur la connexion SQL
source (`SQL_owi`) pour que le grounding SQL fonctionne.

Algorithme à trois passes (ancré dans le code) :

1. **Passe 1 - exact `value_norm IN`** (lignes 2278-2297) : UNE requête batch
   `SELECT column_name, value, value_norm, occurrences FROM <index> WHERE value_norm
   IN (...) LIMIT <fetch_cap>` pour tous les termes normalisés d'un coup.
2. **Passe 2 - fuzzy `LIKE`** (lignes 2306-2327) : seulement pour les termes ratés en
   passe 1. Par terme : `WHERE value_norm LIKE '%term%' ESCAPE '\' ORDER BY
   occurrences DESC LIMIT FUZZY_CANDIDATES_LIMIT` (40). **Séquentielle** par choix de
   sécurité (commentaire ligne 2306) : l'accès concurrent à `SQLExecutor2` n'est pas
   garanti thread-safe et le gain est marginal -> instance safety.
3. **Passe 3 - « last chance »** (lignes 2329-2345) : tranche bornée
   `ORDER BY occurrences DESC LIMIT LAST_CHANCE_SCAN_LIMIT` (5000), récupérée AU PLUS
   UNE FOIS par requête et réutilisée (term-independent), puis classée par `difflib`
   (`rank_candidates`, ligne 802) pour les termes à grosses fautes de frappe.

Sécurité d'exécution : `SQL_PRE_QUERIES` (ligne 156) =
`["SET LOCAL statement_timeout TO '30000'", "SET LOCAL transaction_read_only TO on"]`.
Lecture via `query_to_iter` (streaming, sans pandas) avec repli `query_to_df`
(`_run_sql`, ligne 2229).

Classement / désambiguïsation (logique 100 % déterministe) :
- `rank_candidates` (ligne 802) : `difflib.SequenceMatcher` + bonus 0.8 si substring,
  trié par similarité puis occurrences. Seuils : `FUZZY_MIN_RATIO = 0.62` (ligne 148) ;
  un résolu fuzzy « fort » exige score >= 0.9 et un seul candidat (ligne 2374).
- `refine_ambiguous` (ligne 825) : (1) colonne préférée d'un terme qualifié filtre ;
  (2) préférence exact-value évince les collisions de normalisation ; (3) une seule
  valeur distincte -> auto-pick par `column_priority` (ligne 383 : override profil
  `ambiguity_priority`, sinon `-distinct_count` = colonne la plus spécifique gagne) ;
  (4) plusieurs valeurs distinctes mais une colonne strictement dominante -> on
  l'épingle ET on divulgue les autres (`alt_columns`).
- `defer_multicolumn_offer_terms` (ligne 883) : la décision « demander vs déférer »
  est prise PUREMENT depuis le nombre de colonnes distinctes candidates, jamais
  depuis des noms de colonnes en dur. >= 2 colonnes -> `deferred` (le modèle
  sémantique tranche la hiérarchie d'offre et divulgue) ; mono-colonne -> reste
  `ambiguous` (vraie question -> demande). Retour `(resolutions, deferred)` où
  `deferred = [{raw, columns, samples}]`.

RATIONALE central (semantic_model/README.md:36-41) : le sous-agent **ASSISTE, il ne
DICTE pas**. La régression qui a motivé ça : `column_priority` avec fallback
`-distinct_count` épinglait `sirano_product = 'EVPL'` - or les lignes BUDGET n'ont
pas de `sirano_product` -> budget = 0. D'où : pour un terme d'offre ambigu, le
sous-agent NE pin PLUS de colonne ; il marque `AMBIGUOUS OFFER TERM` et laisse le
modèle Sonnet (qui a la couche sémantique) résoudre.

---

## 4. Le tool exécuté au runtime : `revenue_semantic_query` (`v4oqA6R`)

C'est le SEUL tool DSS réellement appelé au runtime en v3 (CLAUDE.md
`dataiku-agents/`). CONFIG (lignes 127-138) :
- `SEMANTIC_TOOL_ID = "v4oqA6R"`, `SEMANTIC_TOOL_NAME = "revenue_semantic_query"`.
- `SEMANTIC_QUESTION_KEY = "question"` (premier candidat ; auto-détecté au runtime).
- `SEMANTIC_TOOL_ID_BY_MODE` : tous les modes partagent le même tool ; le LLM
  sous-jacent du tool est configuré dans DSS (Sonnet), pas depuis le code.

Appel : `tool.run({sem_key: semantic_question})` (ligne 2653). Le tool est résolu
par `_get_tool` (ligne 2171) : `project.get_agent_tool(tool_id)` avec un fallback
one-shot qui re-résout l'id par nom via `list_agent_tools()` (couvre un tool recréé
dont l'id a changé). La clé d'input est auto-détectée par `pick_semantic_input_key`
(ligne 1750) depuis le `inputSchema` du descripteur (candidats : `question`, `query`,
`user_question`, `input`, `text`), cachée par id de tool (`self._semantic_keys`).

**COMPOSE de la question** (`build_semantic_question`, ligne 1466) - 100 %
déterministe, le LLM n'écrit jamais cette question. Elle porte tout ce que les
couches amont ont gagné, structuré en parties :
- `USER QUESTION (this is the source of truth - answer THIS): "..."` (ligne 1480).
- `EXPECTED SHAPE (guidance, use your judgment): ...` (hint d'intent, ligne 1553).
- `HELPER FINDINGS - ... HINTS to ASSIST you, NOT orders ...` : valeurs confiantes
  groupées par colonne (`=` ou `IN`), spellings exacts du catalogue (ligne 1581).
- `AMBIGUOUS OFFER TERM - "..." is present in SEVERAL columns (...). Do NOT take a
  pinned column from the helper here: YOU resolve it` (ligne 1588) - pour les valeurs
  à `alt_columns` ET pour les termes déférés (`offer_terms_for_model`, ligne 1604)
  avec consigne « NEVER default to sirano_product ».
- `SCENARIO (guidance): ...` et `PERIOD: ...` (lignes 1617-1628).
- `SEMANTIC_DESTINATION_NOTE` (ligne 1413) : la consigne que le SQL produit une table
  résultat affichée à l'utilisateur ET lue par un autre LLM -> renvoyer un tabulaire
  propre avec alias explicites, jamais de prose.

**EXTRACTION du retour** (`extract_semantic_payload`, ligne 1694) - walker défensif
car le tool tourne en mode Agent (transcript multi-messages : reasoning -> exploration
de schéma -> requêtes sondes -> réponse finale). Deux conséquences gérées :
- La RÉPONSE est sélectionnée par PRIORITÉ DE CLÉ (`_SEM_ANSWER_KEY_PRIORITY`, ligne
  1647 : `answer`/`output_text`=0, `completion`=1, `text`=2, `result`=3) et, à
  priorité égale, la DERNIÈRE occurrence gagne (message final, jamais le préambule).
- Le RÉSULTAT tabulaire et `row_count` gardent aussi la DERNIÈRE occurrence
  (les résultats des requêtes sondes viennent avant le résultat final).
Sortie : `{"sqls": [str], "result": {...}|None, "answer": str|None, "row_count":
int|None, "shape_keys": [str]}`. Clés de lignes acceptées
(`_SEM_ROW_KEYS`, ligne 1643) : `rows`, `records`, `data`, `result_rows`, `values`.

---

## 5. Le nouveau tool `attribute_lookup` : construit, testé, PAS encore câblé

Fichier : `tools/attribute_lookup_tool.py`. C'est un **Custom Python agent tool**
autonome (`from dataiku.llm.agent_tools import BaseAgentTool`, classe `MyAgentTool`,
ligne 260). Il **remplace** le tool managé `dataset_lookup` (id `9FEzVZk`) RETIRÉ le
2026-06-18 (tools/README.md:12, 61-70).

STATUT (tools/README.md:28-31, agents/README.md:113-117) : **construit + testé
unitairement** (`tests/test_attribute_lookup.py`, 33 fonctions de test, validé par
RUN TEST), **PAS encore câblé** dans le sous-agent. Pour le câbler : créer le Custom
Python tool dans DSS, mettre son id dans le sous-agent, router les lectures simples
vers lui. L'id DSS est « (to create) » (tools/README.md:11).

Ce qu'il fait : le chemin RAPIDE pour les lectures simples sur un objet nommé, SANS
modèle sémantique, SANS dataframe en RAM. Il se comporte comme la boîte de recherche
« Whole data » de Dataiku : un filtre insensible à la casse sur CHAQUE colonne texte
du dataset, retournant les valeurs des autres colonnes (ou seulement la colonne
demandée). Exemples (< 1s) : « qui est l'account manager de X ? », « code carrier /
zone de vente de X ? ». CONFIG (lignes 41-55) : `FACT_DATASET = "DRIVE_Revenues"`,
`CATALOG_DATASET = "DRIVE_Revenues_Value_Catalog"` (fallback alias optionnel).

Flux (3 étapes) :
1. **SEARCH** (`build_search_sql`, ligne 126) : `SELECT * FROM <fact> WHERE (col1
   ILIKE %term% OR col2 ILIKE %term% ...) LIMIT <sample>` sur chaque colonne texte,
   needle accent-strippée + minuscule, ESCAPE `\`. Borné par `SEARCH_SAMPLE_ROWS`
   (1000).
2. **SUMMARIZE** : `find_matches` (ligne 136) renvoie `found_in` = où le terme
   apparaît + ses valeurs exactes ; `summarize_values` (ligne 166) renvoie les
   valeurs distinctes des colonnes demandées (`keep`).
3. **FALLBACK** : si rien ne matche, `_alias_fallback` (ligne 318) propose des alias
   du catalogue (jamais auto-pick). Optionnel : un catalogue absent/illisible ne donne
   aucune suggestion, jamais d'erreur.

Statuts de sortie : `found`, `suggestions`, `not_found`, `bad_input`,
`attribute_unknown`. Le descripteur (`get_descriptor`, ligne 344) précise « Do NOT
use it for sums, totals, rankings or comparisons - use the semantic model query tool
for those », et `status 'suggestions'`/`'not_found'` -> demander à l'utilisateur,
pas deviner.

Sécurité : read-only (`SQL_PRE_QUERIES` mêmes que le sous-agent, ligne 54), borné par
LIMIT, seuls de vrais noms de colonnes découverts du schéma live atteignent le SQL
(`_live_columns_typed`, ligne 282 ; `match_attribute_column`, ligne 95), rien en RAM.
`MAX_ATTRIBUTES = 12` (anti-abus). Réutilisable sur un autre dataset en changeant
`FACT_DATASET` ; aucun nom de colonne en dur.

Pourquoi `dataset_lookup` a été retiré (tools/README.md:61-70) : il ne trouvait pas
les valeurs dans des colonnes non indexées par le value catalog (ex.
`account_manager`), la gestion du résultat vide ajoutait de la complexité, et il
dupliquait du travail. Tout le code de l'intent `lookup` (`build_lookup_filter`,
`extract_lookup_rows`, `lookup_note`, `_lookup_rows`,
`Profile.match_attribute`/`attribute_columns`/`live_columns`) a été supprimé du
sous-agent.

### Tools listés mais non actifs en v3 (tools/README.md)

| Tool | Type | Id | Statut v3 |
|---|---|---|---|
| `revenue_semantic_query` | Semantic Model Query | `v4oqA6R` | OUI - moteur SQL par défaut |
| `attribute_lookup` | Custom Python | (à créer) | construit + testé, PAS câblé |
| `dataset_lookup` | Dataset Lookup (managé) | `9FEzVZk` | RETIRÉ 2026-06-18 |
| `Drive_Revenues_resolve_filter_value` | Custom Python | (instance) | roadmap, non câblé (supplanté par attribute_lookup) |

Les labels `resolve_filter_value` et `dataset_sql_query` (`KNOWN_TOOL_NAMES`, ligne
2102) sont des NOMS D'EVENT pour la timeline, PAS des appels de tool.

---

## 6. Le modèle sémantique aligné : build vs update-in-place

Le tool `revenue_semantic_query` (`v4oqA6R`) pointe sur un **modèle sémantique** qui
POSSÈDE le SQL. Le modèle est scripté sous `tools/semantic_model/`. Règle clef
(semantic_model/README.md:14-22) : le tool tourne sur un modèle FORT (Sonnet 4.6) AVEC
la couche sémantique, donc il comprend le dataset mieux que le petit modèle UNDERSTAND.
Le sous-agent envoie la question user (vérité) + des HINTS ; les hints aident, ne
commandent pas.

Deux scripts (à lancer dans un notebook Dataiku, projet OWISMIND_DEV) :

- **`build_aligned_semantic_model.py`** = CREATE unique. Lit l'ancien modèle
  (`OLD_SEMANTIC_MODEL_ID = "2O2KcHw"`, READ-ONLY via `get_raw()` sur deep copy,
  jamais de `save()` dessus), applique les corrections déterministes
  (`apply_corrections`, ligne 337) sur la copie, crée un NOUVEAU modèle
  (`create_semantic_model`, ligne 482) + version v1, puis **indexe** les valeurs
  distinctes (`start_update_distinct_values`, ligne 517). Table physique :
  `PHYSICAL_TABLE = '"OWISMIND_DEV_drive_revenues"'`. API publique uniquement, aucune
  classe instanciée directement.
- **`update_aligned_semantic_model.py`** = MODIFY en place. Rafraîchit les
  `sqlGenerationConfig.instructions` + `goldenQueries` sur la version active
  (`get_raw()`/`save()`), **SANS create, SANS re-index** (ni instructions ni golden
  queries ne touchent l'index de valeurs distinctes). Requiert
  `NEW_MODEL_ID` (l'id imprimé à la création). À utiliser pour chaque itération de
  prompt/golden-query une fois le modèle existant.

NB : `NEW_INSTRUCTIONS` et `GOLDEN_QUERIES` sont gardés byte-identiques dans les deux
fichiers ; les éditer dans `update_…` à l'avenir.

### Le contenu aligné (le coeur métier)

`sqlGenerationConfig.instructions` (`NEW_INSTRUCTIONS`, build:60-192) encode les
règles que le modèle applique :
- **Une table physique, JAMAIS de JOIN** : les 3 entités (revenue_record,
  customer_account, commercial_offer) mappent la MÊME table dénormalisée.
- **Scénario par défaut = `'ACTUALS'`** (pluriel, jamais `'ACTUAL'`). Valeurs Phase :
  ACTUALS, BUDGET, FORECAST, Q3F, HLF. `amount_eur` est additif par `booking_type`.
- **Hiérarchie d'offre, le plus granulaire d'abord** : Product > Solution >
  SolutionLine ; `sirano_product` = code technique secondaire, JAMAIS le défaut (les
  lignes BUDGET peuvent ne pas porter de sirano_product -> budget = 0). Transparence
  obligatoire quand la valeur existe à plusieurs niveaux.
- **Identité client** : GROUP BY `diamond_id` SEUL (stable), afficher
  `MAX(Account_name)` + `MAX(carrier_code)` en tête, `diamond_id` en dernier,
  de-emphasized.
- **Parent_Group** : ne pas l'utiliser sauf demande explicite.
- **distribution_type / Account_partner** : ventes indirectes (revendeur = Airbus
  -> client final = Maroc Telecom). `INDIRECT_VALUE = "Indirect_distribution/Resseler"`.
- **Hints du grounding helper = assistance, PAS ordres** : question user = vérité.
- **YTD** : pour ACTUALS, filtrer `EXTRACT(YEAR FROM year_month) = <year>` (pas de
  comparaison à « aujourd'hui » qui créerait un mois partiel/vide).

`GOLDEN_QUERIES` (build:204-311) : 9 requêtes-or, chacune enseignant une règle (pas de
self-join, name+carrier_code, diamond_id en dernier, priorité Product, client nommé,
indirect, par partenaire).

`apply_corrections` (build:337-446) localise les éléments par NOM (robuste à l'ordre)
et corrige : Phase `'ACTUAL'` -> `'ACTUALS'` partout (dont le filtre « Actual Revenue
Only » qui matchait ZÉRO ligne) ; description `commercial_offer` (hiérarchie +
transparence) ; `Parent_Group` (restreint) ; `Account_partner` (exemple indirect) ;
retrait du terme de glossaire bidon `diamond_id` (décrivait `original_dataset`) et du
synonyme « roaming hub » de Roaming Sponsor ; remplacement des golden queries ;
réécriture complète des instructions.

Le modèle est repointé en éditant les settings du tool `v4oqA6R` pour sélectionner le
NOUVEAU modèle (semantic_model/README.md:114-118) - aucune édition de code sous-agent
nécessaire si on réutilise le même tool. L'ancien modèle `2O2KcHw` reste comme
rollback (ne pas le supprimer). NB IN-FLUX : la README et le build script référencent
`dataset_expert_langgraph.py` comme fichier à recoller (README.md:120) ; le fichier
actuel du repo est `SalesDrive_revenue_expert.py` (renommage postérieur).

---

## 7. Contrats gelés et events (à ne jamais renommer)

Section 12 du sous-agent (lignes 2093-2128). Le webapp / Evidence en dépendent ;
un test anti-drift (`tests/test_langgraph_agents.py`, anciennement
`test_orchestrator_v3.py`) garde la cohérence registre orchestrateur <-> sous-agent.

- `KNOWN_BLOCK_IDS` (ligne 2100) : `resolve`, `run_sql`, `format_output`,
  `clarify_user`, `out_of_scope_msg`, `about_data`.
- `KNOWN_TOOL_NAMES` (ligne 2102) : `resolve_filter_value`, `dataset_sql_query`
  (labels d'events).
- **Le span `semantic-model-query`** (le contrat clef pour Evidence). Un span PAR SQL
  exécuté, avec `outputs = {sql, success, row_count}` + `{rows, columns}` sur le SQL
  réussi. Pour le moteur semantic_tool, le RÉSULTAT est attaché au DERNIER SQL
  (`i == last_i`, lignes 2682-2690) car le webapp/Evidence prennent le dernier SQL
  réussi - sinon le chart ne peut pas rendre (fix multi-SQL).
- **UN `AGENT_RESULT` final** (`_agent_result`, ligne 2117) : `{status, language,
  intent, originalIntent, resolvedFilters, sqlCount, rowCount, attempts}`. Statuts :
  `ready`, `need_clarification`, `out_of_scope`, `no_data`, `error`.

Forme d'un event (ligne 2105) : `{"chunk": {"type": "event", "eventKind": kind,
"eventData": data}}`. Texte streamé : `{"chunk": {"text": "..."}}`.

---

## 8. Connexion au reste du système

- **Orchestrateur** (`agents/OWIsMind_orchestrator.py`, `agent:` non lu ici en
  détail) : appelle le sous-agent comme un tool (`ask_revenue_expert`), injecte
  `USER LANGUAGE:` et `MODE:` dans le contexte, écrit l'analyse user-facing finale
  (d'où `SUBAGENT_LLM_HEADLINE = False`), et restitue la ligne `[Scope]` du
  sous-agent en prose (agents/README.md:64-65).
- **Evidence / webapp** : la trace du sous-agent est appendée à la trace
  orchestrateur ; `_find_generated_sql` transforme les spans `semantic-model-query`
  en items SQL Evidence (`sql_id` gelé `s{step}q{n}`, portant `source_url` si
  configuré), `_find_usage` somme les tokens (agents/README.md:67-70).
- **Flow design-time** (recipes/README.md) : `profile_dataset_recipe.py` ->
  `DRIVE_Revenues_profile` (cerveau, overrides humains jamais écrasés) ;
  `build_value_index_recipe.py` -> `DRIVE_Revenues_value_index` (grounding, SUR la
  connexion SQL) ; `build_value_catalog_recipe.py` -> `DRIVE_Revenues_Value_Catalog`
  (roadmap). Les recettes tournent design-time (pandas OK), jamais au runtime chat ;
  l'agent lit live, pas de re-paste quand une recette re-tourne.
- **Source `DRIVE_Revenues`** (~175 k lignes, 20 colonnes, recipes/README.md:18-39) :
  Phase (scénario), offre (SolutionLine/Solution/Product/sirano_product),
  Account_name/Account_partner/distribution_type/Parent_Group/carrier_code/diamond_id,
  year_month (time), amount_eur (mesure EUR), account_manager/area_manager/
  sales_director (cibles lookup typiques).

---

## 9. Gotchas et points en flux

- **`MyLLM`** (classe DSS) et **caches keyés stable** : le Code Agent instancie la
  classe UNE fois par process et peut appeler `process_stream` CONCURREMMENT ; tous
  les caches de `__init__` (ligne 2156) DOIVENT être keyés par identifiant stable
  (nom de dataset, id de tool), jamais d'état par-requête sur `self`. Le mode et l'id
  de tool sémantique voyagent dans l'ÉTAT du graphe, pas sur `self`.
- **L'intent `lookup` n'existe plus** dans le code (`KNOWN_INTENTS`) mais reste listé
  dans `agents/README.md:89` -> doc périmée (IN-FLUX).
- **Devise dérivée du nom de colonne** : `metric_unit` (ligne 1030) infère `€` depuis
  `amount_eur` (`_CURRENCY_BY_CODE`, ligne 1027) - aucune config profil requise.
- **`with_json_output` FORCÉ sur UNDERSTAND uniquement** ; NE JAMAIS le mettre sur
  l'orchestrateur (désactive le reasoning en DSS 14, CLAUDE.md règle 5).
- **Renommage de fichiers IN-FLUX** : les scripts semantic_model et le README
  référencent `dataset_expert_langgraph.py` (ancien nom) / Code Agent
  `agent:AKQaQ0Am` ; le fichier courant est `SalesDrive_revenue_expert.py` /
  `agent:bHrWLyOL`. Les originaux linéaires `*_agent.py` sont mentionnés comme
  rollback mais ne sont plus présents dans le repo (supprimés, voir mémoire).
- **`run_parallel`** (ligne 275) borné par `SUBAGENT_MAX_PARALLEL = 4` : helper
  pour tools indépendants futurs ; aujourd'hui le grounding reste séquentiel pour la
  sécurité de l'instance.
- **`guard_custom_sql`** (ligne 1345, moteur direct seulement) : défense en
  profondeur (single SELECT, table whitelistée, pas de DML/DDL, pas de tables
  système, LIMIT forcé). Les littéraux sont blanchis avant le scan de mots-clés ;
  `FROM"x"` sans espace est couvert ; `WITH RECURSIVE` toléré.
