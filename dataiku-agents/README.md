# OWIsMind - Système d'agents Dataiku v3 (Dataset Expert générique)

> **Le but** : un orchestrateur + des sous-agents **experts de n'importe quel dataset**.
> L'expertise est **fabriquée dans le Flow** (profil du dataset + index de valeurs), relue
> par un humain, et consommée au runtime par un agent qui comprend, ground les valeurs
> exactes, puis **délègue le SQL au Semantic Model Query tool** en lui donnant le meilleur
> contexte possible (moteur par défaut - A/B testé le 2026-06-12 : le semantic model génère
> le meilleur SQL, nos couches le rendent précis). Un moteur **SQL direct read-only**
> (templates + LLM gardé) sert de repli technique. Ajouter un dataset = 2 recettes +
> 1 Code Agent + 1 entrée de registre.

---

## 1. Architecture en une image

```
DESIGN TIME (Flow, une fois + scénario de refresh)
  DRIVE_Revenues ──► [recette profile_dataset]    ──► DRIVE_Revenues_profile      (le "cerveau métier")
                 ──► [recette build_value_index]  ──► DRIVE_Revenues_value_index  (le "catalogue exact")
  (+ dataset éditable DRIVE_Revenues_profile_overrides : tes corrections humaines, optionnel)

RUNTIME (chat)
  WebApp ──► Orchestrateur v3 (Code Agent, inchangé côté webapp)
                │  PLAN (1 LLM JSON) → EXECUTE (PARALLÈLE si multi-étapes) → SYNTHESIZE
                ▼
            Dataset Expert (Code Agent générique, 1 par dataset)
                │ 1. UNDERSTAND   1 LLM JSON - prompt GÉNÉRÉ depuis le profil
                │ 2. RESOLVE      grounding des termes sur value_index (SQL, exact→fuzzy)
                │ 3. COMPOSE      question sémantique DÉTERMINISTE par intent : valeurs
                │                 exactes + scénarios + périodes + règle d'axe + contexte
                │                 de destination ("ta table sera lue par un LLM")
                │ 4. QUERY        ► Semantic Model Query tool (MOTEUR PAR DÉFAUT)
                │                 ► repli technique : SQL direct read-only (templates
                │                   déterministes + LLM gardé + EXPLAIN + réparations)
                │ 5. RENDER       table par code + headline LLM vérifiée chiffre par chiffre
                ▼
            Semantic Model (SQL) → PostgreSQL (transaction READ ONLY en mode direct)
```

**Ce qui ne change pas** (contrats gelés - la webapp, la timeline et Evidence Studio
fonctionnent sans modification) : event kinds de l'orchestrateur, spans
`semantic-model-query` `{sql, success, row_count, rows, columns}` (le `success` devient
enfin **véridique**), event `AGENT_RESULT`, format `sql_id`, caps 50×50×256×64k.

---

## 2. Contenu du dossier

| Fichier | Rôle | Où ça va dans DSS |
|---|---|---|
| `recipes/profile_dataset_recipe.py` | Profil du dataset : stats déterministes + enrichissement LLM (descriptions, rôles, métriques, scénarios, synonymes) | Recette Python dans le Flow |
| `recipes/build_value_index_recipe.py` | Index de toutes les valeurs distinctes des colonnes "groundables" (+ forme normalisée) | Recette Python dans le Flow |
| `agents/SalesDrive_revenue_expert.py` | Le sous-agent générique LangGraph (UNDERSTAND→RESOLVE→SQL→EXECUTE→RENDER), `agent:bHrWLyOL` | Code Agent **SalesDrive_revenue_expert** (env 3.11) |
| `agents/OWIsMind_orchestrator.py` | Orchestrateur LangGraph (boucle agentique + narration live + modes Éco/Medium/High + fan-out parallèle) | Code Agent **OWIsMind_orchestrator** (env 3.11) |
| `tests/` | Tests unitaires DSS-free (`python3 -m unittest discover -s dataiku-agents/tests`) | Repo uniquement |

**Rollback** : les versions linéaires (`*_agent.py`) et v2 (`orchestrator/`, `salesdrive/`) ont
été retirées du repo mais restent dans l'historique git (`git show <commit>:<path>`).

---

## 3. Implémentation pas à pas

### Étape 1 - Flow : les deux recettes (≈ 15 min)

1. **Recette de profil** : dans le Flow, `+ Recipe → Code → Python`.
   - Input : `DRIVE_Revenues`.
   - Output : **créer** le dataset `DRIVE_Revenues_profile` - *recommandé sur la
     connexion `SQL_owi`* (schema `{key, payload}`, écrit par la recette).
   - Remplacer tout le code généré par `recipes/profile_dataset_recipe.py`.
   - Dans le bloc CONFIG : vérifier `ENRICH_LLM_ID` (par défaut le Gemini 2.5 Pro
     connu de l'instance ; mets le **plus fort** dispo - Opus 4.7 si présent dans
     le Mesh : ça ne tourne qu'au profilage, le coût est unique).
   - **Run**. (~22 colonnes × 170 k lignes = quelques secondes + 1 appel LLM.)
2. **Recette d'index de valeurs** : pareil.
   - Input : `DRIVE_Revenues`. Output : `DRIVE_Revenues_value_index` -
     ⚠️ **obligatoirement sur la connexion SQL du dataset source** (`SQL_owi`) :
     l'agent l'interroge en SQL au runtime.
   - Code : `recipes/build_value_index_recipe.py`. **Run**.
3. **Scénario de fraîcheur** (recommandé) : un scénario DSS qui rebuild les 2 outputs
   chaque semaine (ou après chaque refresh de Drive). L'agent lit toujours du frais,
   rien à recoller.

> La recette de profil n'envoie au LLM **que des métadonnées agrégées** (schéma, stats,
> valeurs distinctes des colonnes ≤ 50 valeurs, 12 échantillons) - jamais les lignes.
> Les colonnes à forte cardinalité (clients…) ne mettent **pas** leur liste dans le profil ;
> elles vivent dans l'index de valeurs, interrogé à la demande.

### Étape 2 - Relecture humaine du profil (l'étape qui fait la qualité)

Ouvre `DRIVE_Revenues_profile` et lis les payloads (ou via un notebook). Tout ce que le
LLM a écrit est flaggé `"llm_generated": true`. Pour corriger **sans que tes corrections
soient écrasées au prochain run** :

1. `+ Dataset → Editable` → `DRIVE_Revenues_profile_overrides`, 3 colonnes :
   `key`, `field`, `value`.
2. L'ajouter comme **2ᵉ input** de la recette de profil, re-run.

Exemples de lignes d'override (la `value` est parsée en JSON si possible) :

| key | field | value |
|---|---|---|
| `__dataset__` | `description_fr` | `Revenus OWI par mois, client, produit et phase` |
| `sales_entity` | `description_fr` | `Entité commerciale : GCS = clients externes, GCP = clients internes (filiales Orange)` |
| `customer_id` | `synonyms` | `["client", "customer", "compte", "carrier"]` |
| `Phase` | `description_en` | `Revenue scenario: ACTUALS=billed, BUDGET=sales plan, FORECAST=ML projection, Q3F/HLF=mid-year re-forecasts` |
| `__dataset__` | `scenario` | `{"column": "Phase", "values": ["ACTUALS","BUDGET","FORECAST","Q3F","HLF"], "default_values": ["ACTUALS"]}` |

**À vérifier en priorité** dans le payload `__dataset__` : `metrics` (le revenu =
`SUM(amount_eur)`, format `amount`, `unit` `EUR`), `scenario` (colonne Phase + les 5
valeurs + défaut ACTUALS), `time` (colonne + format détecté), et les `display_column`
(ex. `diamond_id` → `Account_name`). C'est le pendant code du « semantic model », sauf
que c'est versionnable, diffable et testé.

### Étape 3 - Le Code Agent « Dataset Expert » (≈ 10 min)

1. GenAI → Agents → **New → Code agent** (env Python 3.11, langchain/langgraph
   installés). Nom du Code Agent : **`SalesDrive_revenue_expert`** (`agent:bHrWLyOL`).
2. Coller `agents/SalesDrive_revenue_expert.py`, puis remplir le bloc CONFIG :
   - `PROFILE_DATASET = "DRIVE_Revenues_profile"`
   - `VALUE_INDEX_DATASET = "DRIVE_Revenues_value_index"`
   - `SQL_ENGINE = "semantic_tool"` (défaut) + `SEMANTIC_TOOL_ID` / `SEMANTIC_TOOL_NAME`
     (le tool Semantic Model Query du dataset - `v4oqA6R` / `revenue_semantic_query`
     pour les revenus). `FALLBACK_TO_DIRECT = True` : si le tool tombe en panne
     technique, l'agent bascule sur son moteur SQL direct au lieu d'échouer.
   - `UNDERSTAND_LLM_ID` : démarre avec le Gemini 2.5 Pro connu ; passe à
     **Gemini 2.5 Flash** une fois validé (2 appels/question, c'est lui le coût).
   - `SQLGEN_LLM_ID` : le meilleur modèle SQL dispo (Claude Sonnet configuré). Ne sert
     **que** sur le moteur direct (intent `custom` ou fallback).
3. Tester direct dans le playground de l'agent (voir §5), noter son id `agent:XXXXXXX`.

### Étape 4 - L'orchestrateur (≈ 5 min)

1. Dans `agents/OWIsMind_orchestrator.py` (repo), l'entrée `revenue_expert` pointe
   déjà `"agent_id": "agent:bHrWLyOL"` - mettre à jour si l'id du sous-agent change.
2. Coller le fichier dans le Code Agent **OWIsMind_orchestrator** (env 3.11). La
   webapp le résout par whitelist → zéro redéploiement du plugin.
3. Commit côté repo : le repo reste la source de vérité (toute modif DSS directe sera
   écrasée au prochain collage).

### Étape 5 - Rien d'autre

La webapp parle déjà à l'orchestrateur par son id ; les events, labels de timeline,
Evidence et suivi de coûts fonctionnent tels quels (contrats gelés respectés, et le
panneau Evidence affichera désormais des `success` réels et des résultats capturés
déterministes).

---

## 4. Quel modèle où (et pourquoi)

| Appel | Fréquence | Reco | Pourquoi |
|---|---|---|---|
| Profiler - enrichissement | 1×/dataset (+ refresh) | **Le plus fort dispo** (Opus 4.7 / Gemini 2.5 Pro) | Coût unique, qualité des descriptions = qualité de tout le reste |
| Orchestrateur - planner | 1×/question | Gemini 2.5 Pro → **tester Flash** | JSON strict + routage ; la recherche montre que bien contextualisé, un petit modèle suffit |
| Expert - UNDERSTAND | 1×/question | **Gemini 2.5 Flash** (ou GPT-5.4-mini) | Extraction JSON contrainte par enums du profil |
| Expert - SQLGEN (`custom` seulement) | ~10-20 % des questions | **Gemini 2.5 Pro / Claude** | Le seul endroit où le LLM écrit du SQL |
| Expert - headline | 1×/question avec résultat | **Flash / mini** | Une phrase, vérifiée chiffre par chiffre de toute façon |
| Orchestrateur - synthèse | multi-étapes seulement | = planner | Rédaction contrainte aux résultats |

Coût typique d'une question structurée : **2 petits appels LLM + 1-2 requêtes SQL** -
moins cher que la chaîne actuelle (le tool semantic faisait ses propres appels cachés).

---

## 5. Smoke tests (dans le playground de l'expert, puis via l'orchestrateur)

Tirés du corpus réel (`docs/questions_asked.md`) - coche au fur et à mesure :

1. `combien on a fait avec halys l'année dernière ?` → grounding typo→`HALYS`, phase
   ACTUALS par défaut, total + headline vérifiée.
2. `Give me the budget 2026 for the Roaming Hub` → route + SQL filtré BUDGET (plus
   jamais de « I don't have budget data »).
3. `top 5 clients EVPL en 2025` → top_n groupé client avec display name.
4. `écart vs budget sur le Roaming Sponsor en janvier 2026` → compare_scenarios :
   pivot ACTUALS/BUDGET + delta + delta_pct.
5. `compare le CA H1 2026 vs H1 2025` → compare_periods.
6. `évolution mensuelle des revenus depuis juillet 2025` → trend.
7. `quelle est la part du top 20 clients IP Transit ?` → share_of_total.
8. `quelles sont les SolutionLine ?` → list_values (réponse = vraies valeurs en base).
9. `qu'est-ce que tu connais comme données ?` → about_data (card 100 % profil, 0 SQL).
10. `ipl` (terme ambigu) → clarification listant `IPL (Product)` / `IPL (sirano_product)`…
    puis répondre `IPL (Product)` → round-trip résolu sans boucle.
11. `météo à Paris ?` → out_of_scope.
12. Via l'orchestrateur : `et en 2024 ?` après une question → ellipse réécrite ;
    `tickets 1&1 2025` → CAPABILITY_GAP honnête (jamais un faux 0) ;
    `SS7 vs LTE` → CONCEPT.
13. Multi-étapes (quand un 2ᵉ domaine existera) : vérifier que les deux agents
    progressent **en même temps** dans la timeline.

Si un smoke test diverge : corriger via le **profil/overrides** (vocabulaire, rôles,
défauts) ou le prompt UNDERSTAND - jamais de valeur métier en dur dans le code (règle P3).

---

## 6. Ajouter un nouveau dataset (tickets, CSAT, opportunités…)

1. Flow : brancher les **2 mêmes recettes** sur le dataset → `X_profile` + `X_value_index`.
2. Relire le profil (overrides éditables).
3. Dupliquer le Code Agent Dataset Expert → changer les 2 noms de datasets du CONFIG.
4. Orchestrateur : **1 entrée** registre (copier `revenue_expert`, adapter id/labels/
   `domain` - `tickets` et `satisfaction` existent déjà dans `BUSINESS_DOMAINS`, le
   CAPABILITY_GAP se referme tout seul).
5. Dès 2 domaines actifs : les questions 360 (`analyse complète de 1&1`) fan-out en
   parallèle et la synthèse cite chaque source.

---

## 7. Garde-fous & limites assumées

- **Sécurité SQL** : transaction `READ ONLY` + `statement_timeout 30s` (pattern validé
  DSS), garde-fou sur le SQL LLM (un seul SELECT, table whitelistée, mots-clés DML/DDL
  interdits, LIMIT forcé ≤ 500, EXPLAIN à blanc avant exécution), identifiants quotés
  validés, littéraux échappés et issus du catalogue.
- **Honnêteté** : tout chiffre affiché vient du résultat SQL (table par code, headline
  vérifiée, sinon fallback déterministe) ; 0 ligne → message honnête + scénarios/période
  réellement disponibles (métadonnées du profil) ; terme introuvable → clarification, pas
  de devinette.
- **Deux moteurs SQL** : `semantic_tool` (défaut - le Semantic Model génère et exécute,
  nos couches lui fournissent valeurs exactes/scénarios/périodes/contexte de destination)
  et `direct` (templates déterministes + LLM gardé, exécution read-only). Le repli
  technique semantic→direct est automatique ; un résultat vide légitime n'est PAS un
  repli (honnêteté).
- **Limites v1** : pas encore de jointures cross-datasets dans UNE requête (le 360 passe
  par l'orchestrateur, un agent par dataset) ; la qualité du routage d'ambiguïté dépend
  de l'index (re-run du scénario après refresh).
- **Prochaine session - le semantic model lui-même** : sa config est désormais accessible
  par code (`project.get_semantic_model(id)` → versions → `get_settings().get_raw()` →
  JSON complet entities/metrics/filters/goldenQueries/glossary → `save()` + nouvelle
  version active). Pistes : versionner ce JSON dans le repo, enrichir les golden queries
  depuis le corpus, aligner son glossaire avec le profil, corriger `Phase = 'ACTUAL'`
  (la valeur réelle est `ACTUALS`) dans les descriptions/filtres.
- **Plugin-isation (ensuite)** : ce code est déjà 100 % paramétré par les noms de
  datasets + ids tools/LLM → transformable en plugin avec params no-code une fois
  validé en réel.
