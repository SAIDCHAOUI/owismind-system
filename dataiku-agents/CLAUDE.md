# CLAUDE.md - dataiku-agents/ (système d'agents v3)

> Résumé d'orientation pour ce dossier. Guide d'implémentation complet → `README.md`.
> Mémoire projet → `memory/CONTEXT.md` (L051-L052). **Repo = source de vérité** : toute
> modif se fait ici puis se RECOLLE dans les Code Agents DSS (jamais l'inverse).

## Ce que c'est

Le système agentique v3 d'OWIsMind : un **orchestrateur** + des **Dataset Experts
génériques** (1 Code Agent par dataset, même fichier, CONFIG différent). L'expertise
d'un dataset est **fabriquée dans le Flow** (2 recettes → profil JSON + index de
valeurs exactes), relue par l'humain (dataset éditable d'overrides), et consommée au
runtime. Décision clé (A/B testé en DSS le 2026-06-12) : **le Semantic Model Query
tool génère le meilleur SQL** - toutes nos couches (compréhension, grounding,
désambiguïsation) existent pour lui fournir le meilleur contexte possible.

> **Fichiers ACTIFS (Code Agents LangGraph, env 3.11)** : orchestrateur
> `agents/OWIsMind_orchestrator.py` · sous-agent revenus `agents/SalesDrive_revenue_expert.py`
> (`agent:bHrWLyOL`). Les anciennes versions linéaires (`*_agent.py`) et v2 (`orchestrator/`,
> `salesdrive/`) ont été retirées du repo (préservées dans l'historique git).

## Pipeline du Dataset Expert (`agents/SalesDrive_revenue_expert.py`)

```
UNDERSTAND  1 LLM JSON - prompt GÉNÉRÉ du profil (métriques, scénarios, axes, synonymes)
RESOLVE     grounding SQL sur <dataset>_value_index (exact → fuzzy) + politique
            d'ambiguïté + round-trip « VALEUR (Colonne) »
COMPOSE     question sémantique déterministe : la QUESTION USER MÈNE TOUJOURS +
            intent attendu + valeurs exactes groupées par colonne (IN, jamais de AND
            intra-colonne) + règle énumération→OR/une-ligne-par-item + scénario +
            période + note de destination (« ta table sera lue par un LLM »)
QUERY       SQL_ENGINE="semantic_tool" (défaut) → tool v4oqA6R, extraction mode-Agent
            safe (answer = priorité de clés + DERNIER texte ; rows = DERNIER jeu) ;
            panne technique → fallback "direct" (templates 9 intents + LLM gardé +
            EXPLAIN + 2 réparations, exécution SQLExecutor2 READ ONLY)
RENDER      table par code + headline LLM vérifiée chiffre par chiffre ;
            about_data = carte du profil, 0 SQL
```

Orchestrateur (`agents/OWIsMind_orchestrator.py`) = boucle agentique LangGraph
(le modèle appelle les outils PUIS rédige la réponse - pas de passe de synthèse
séparée) + pare-feu d'honnêteté + **fan-out parallèle** des sous-agents (pool ≤3,
events live via queue) + narration live (events `NARRATION`) + modes Éco/Medium/High
(`pick_loop_llm`) + registre `revenue_expert`.

## État (2026-06-12)

| Brique | État |
|---|---|
| Recettes profil + value index (Flow) | ✅ Exécutées en DSS sur DRIVE_Revenues |
| Sous-agent revenus `SalesDrive_revenue_expert` (`agent:bHrWLyOL`, moteur semantic_tool) | ✅ Validé DSS (« ça marche beaucoup mieux ») |
| Orchestrateur `OWIsMind_orchestrator` (LangGraph, narration live + modes) | ⏳ codé, en cours de validation DSS |
| Fan-out parallèle réel (≥2 domaines) | ⏳ Testable quand un 2ᵉ agent existera |
| Tests | `python3 -m unittest discover -s dataiku-agents/tests` (langgraph + dataset-expert + profiler) |

Bugs réels corrigés en route : `LEFT(date,10)` (profil string vs colonne date → prédicats
cast-safe + auto-fallback), préambule mode-Agent relayé comme réponse, AND impossible
sur énumérations multi-valeurs, fetch resolver plafonné à 51 lignes.

## Règles à respecter ici

1. **P3** : jamais de valeur métier en dur - tout vient du profil/index/overrides.
2. **Contrats gelés** : event kinds orchestrateur ; `KNOWN_BLOCK_IDS`/`KNOWN_TOOL_NAMES`
   de l'expert ↔ `block_labels`/`tool_labels` du registre (test anti-dérive) ; spans
   `semantic-model-query` `{sql, success, row_count, rows, columns}` ; `AGENT_RESULT`.
   La webapp/Evidence en dépendent - ne jamais renommer.
3. **Une seule capability revenue `enabled`** à la fois (rollback = re-flip des flags).
4. Norm de valeurs (minuscules/sans accents) FROZEN, partagée recettes ↔ agent.
5. Fichiers agents = STANDALONE (stdlib + dataiku) ; recettes = pandas OK (design-time).

## Prochaine session : le semantic model lui-même

Config scriptable (`project.get_semantic_model("2O2KcHw")` → `get_raw()`/`save()` +
versions). À faire : corriger `Phase = 'ACTUAL'` → `'ACTUALS'` (description entité +
filtre « Actual Revenue Only »), retirer le synonyme « roaming hub » du terme Roaming
Sponsor (produit différent), versionner le JSON dans le repo, enrichir golden queries
depuis `docs/questions_asked.md`, aligner glossaire ↔ profil. Ensuite : agent tickets
(2 recettes + 1 Code Agent + 1 entrée registre) → débloque le 360 parallèle.
