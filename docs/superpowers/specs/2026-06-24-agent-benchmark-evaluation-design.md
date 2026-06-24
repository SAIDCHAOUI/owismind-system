# Design spec - Systeme de benchmark et d'evaluation des agents OWIsMind

Date: 2026-06-24. Status: APPROVED (user, brainstorming). Ce fichier est le contrat
partage pour le plan d'implementation et les sous-agents. Les regles du CLAUDE.md racine
s'appliquent (code en anglais, communication FR, AUCUN tiret cadratin `-`/`:`/`,`/parentheses,
NO INSTALL, securite instance Dataiku, SQL-direct si stockage SQL, jamais editer a la main
les artefacts generes). La charte Orange ne s'applique pas ici (pas d'UI dans ce lot ;
restitution = Flow + dashboard DSS natif pour l'instant).

---

## 0. Objectif et probleme

Mesurer, proprement et de facon reproductible, la qualite et le cout de service des agents
OWIsMind : taux de bonnes reponses (precision), latence, cout, tokens, par agent ET par mode
de reponse, avec un detail par question lisible par n'importe qui ("voici mes agents, voici
le taux de bonnes reponses, voici les delais par modele, voici les questions et les reponses").

Le bricolage existant des stagiaires (projet `OWIsMind_LAB`) a deux defauts structurants :

1. **Capture incomplete.** Le step Python appelle
   `project.get_llm(agent_id).new_completion().with_message(q).execute()` et ne garde que
   `.text`. Cela perd le SQL genere, les **lignes de resultat** et les artefacts
   (tableaux/graphiques) : c'est-a-dire la **preuve** que les agents produisent. Sur une
   question dont la reponse vit dans un tableau, le juge note a l'aveugle. C'est le defaut
   numero 1 a corriger.
2. **Mesures pauvres.** Pas de latence, pas de cout/tokens, juge a un seul score 1-5 non
   structure, pas de decoupage par categorie, pas d'ancre objective.

La webapp de prod capture deja TOUT correctement par echange (`webapp_chat_v5` :
`assistant_text`, `generated_sql` avec SQL + lignes, latence via `created_at`/`answered_at`,
`input/output/total_tokens`, `estimated_cost`, et `webapp_artifacts_v1`). Un vrai benchmark
fait passer l'agent par **le meme chemin de capture** et relit la reponse complete + metriques,
au lieu de reinventer un appel qui jette la moitie de l'information.

## 1. Decisions de cadrage (brainstorming, validees)

- **Dimension de mesure** : agent x mode. On benchmarke chaque agent sur chaque mode
  (Smart/Pro/Claude = eco/medium/high = Gemini Flash-Lite / Gemini Flash / Sonnet). Repond
  directement au besoin "delais de reponse par modele".
- **Echelle** : petit golden set (~10-50 questions). Pas d'usine a parallelisme : une
  concurrence bornee faible suffit et reste douce pour l'instance.
- **Declenchement** : a la demande, run parametre (je choisis agents + modes + sous-ensemble
  de questions + langue). Pas de planification ni de hook sur recoll pour l'instant.
- **Scoring** : juge LLM structure + **ancre objective deterministe** (la valeur/fait de
  reference apparait-elle dans la reponse complete ?).
- **Golden set** : schema enrichi (categorie, type, difficulte, valeur exacte attendue, ...).
- **Alimentation golden** : intake Excel/CSV ET dataset editable DSS maintenant ; ecriture
  depuis une future section webapp prevue (schema compatible).
- **Architecture** : Option 1 = projet DSS + scenario + librairie partagee (repo = source de
  verite). L'agent est appele directement via Mesh, la reponse complete est reconstruite en
  lisant le footer trace via un module de capture unique.
- **Projet DSS** : reutiliser et assainir `OWIsMind_LAB` (pas de nouveau projet). On conserve
  l'idee du dashboard existant comme point de depart.
- **Stockage resultats** : datasets manages dans le Flow (natif Dataiku, dashboard direct),
  schemas concus pour mapper plus tard vers des tables SQL `benchmark_*_v1` lues par la webapp.

## 2. Architecture d'ensemble

Projet `OWIsMind_LAB` (assaini). Flow :

```
golden_intake (Excel/CSV upload) --+
                                   +--> golden_questions (canonique, validee)
golden_editable (editable dataset)-+
                                       |
                                       v
                          [scenario step: run matrix]
                                       |
                                       v
                            benchmark_runs_raw   (capture complete + latence + tokens + cout)
                                       |
                                       v
                          [scenario step: judge]
                                       |
                                       v
                            benchmark_runs_scored (ancre objective + juge LLM + correctness)
                                       |
                                       v
                          [scenario step: aggregate]
                                       |
                        +--------------+--------------+
                        v                             v
                 benchmark_summary            benchmark_breakdown
              (KPI par run x agent x mode)  (precision par categorie/type/difficulte)
```

La logique vit au repo dans un nouveau package `benchmark/` (source de verite), **recolle en
project-library** du projet `OWIsMind_LAB` (meme discipline que les Code Agents : on developpe
au repo, on colle en DSS). Les steps de scenario sont de minces entrypoints qui importent ce
package.

Adressage des agents : par `project_key` explicite (`OWISMIND_DEV` ou `OWISMIND_PROD_V1`) +
`agent_id` (orchestrateur DEV `038G7mlF` / PROD `Xrv7GvfG`, ou un sous-agent precis si on veut
isoler). Le run cible par defaut l'**orchestrateur de bout en bout** (l'experience utilisateur
reelle).

## 3. Module de capture (cle de voute) : `benchmark/agent_capture.py`

Reprend la logique deja eprouvee de la webapp (references :
`Plugin/owismind/python-lib/owismind/agents/streaming.py` fonctions `_find_generated_sql`,
`_find_usage_metadata`, `_sum_usage_metadata` ; `evidence/capture.py` `extract_result`,
`cap_sql_list`). Fonctions :

- `extract_generated_sql(footer_trace) -> list[dict]` : marche recursive du footer, repere les
  sorties d'outil `name == "semantic-model-query"`, renvoie
  `[{sql, success, row_count, result:{columns, rows}}]`. Resultat best-effort, borne (memes
  caps que la webapp : MAX_RESULT_ROWS=200, MAX_RESULT_COLS=50, MAX_CELL_CHARS=256,
  MAX_SQL_ITEMS=20).
- `extract_usage(footer_trace) -> dict` : somme des `usageMetadata` ->
  `{promptTokens, completionTokens, totalTokens, estimatedCost}`.
- `extract_artifacts(stream_events) -> list[dict]` : specs d'artefacts (kind/title/chart/kpi)
  vus dans les events `ARTIFACT` (optionnel ; best-effort).
- `assemble_full_answer(text, sql_items, artifacts) -> str` : **la chaine unique que voit le
  juge**. = texte final de l'agent + serialisation lisible et bornee des tableaux SQL (entetes
  + lignes, tronques) + resume des artefacts. C'est la definition operationnelle de "la reponse
  de l'agent". Plus jamais le texte seul.

Anti-derive : implementation canonique au repo, verrouillee par des **tests sur fixtures de
footer trace reelles** (cf. section 9). On ne touche PAS la webapp validee dans ce lot ; un
refacto futur pourra la faire deleguer a ce module (note, non requis ici). Le package est
volontairement autonome car il tourne en project-library d'un projet DSS distinct ou le
python-lib de la webapp n'est pas sur le path.

Dependances : lazy `import` de tout ce qui est lourd (pas de `import pandas` top-level :
l'environnement de tests NO INSTALL n'a pas pandas ; cf. L089). Le parsing de footer est de la
logique pure sur dict/list.

## 4. Harnais de run : `benchmark/agent_runner.py`

Entree : un objet de config de run (issu des variables de scenario)
```
RunConfig = {
  run_id, run_timestamp,           # stampes par le step (Date.now interdit dans les workflows, pas ici)
  agents: [ {agent_key, agent_label, project_key, agent_id} ],
  modes:  ["eco","medium","high"], # sous-ensemble choisi
  language: "fr",
  question_filter: {...},          # categories / difficulte / actifs seulement
  concurrency: 3,                  # borne faible, defaut 2-3
  per_call_timeout_s: 120,
}
```

Pour chaque triplet (question x agent x mode) :
1. Construire le message = `question` + token de mode `owi:mode=<mode>` (le delimiteur exact
   est celui de l'orchestrateur ; voir `parse_mode` dans
   `OWISMIND_DEV_OWIsMind_orchestrator.py`) + token de langue eventuel (parite avec
   `agents/context.py`). NB : en appel direct via Mesh, le gate de profil
   (`profile.modes`) de la webapp ne s'applique pas ; l'orchestrateur lit le token quoi qu'il
   arrive, ce qui est exactement ce qu'on veut pour forcer un mode.
2. `t0 = perf_counter()`, `completion = project.get_llm(agent_id).new_completion()`,
   `.with_message(...)`, `for chunk in completion.execute_streamed(): ...` : accumuler les
   deltas de texte, capter le **time-to-first-token** (premier delta de contenu), collecter le
   footer/trace final ; `t1` au footer/DONE.
3. Capture via le module section 3 : `answer_text`, `sql_items`, `usage`, `artifacts`,
   `full_answer`.
4. Erreurs/timeouts : capturer l'exception en ligne mesuree (`status="error"`/`"timeout"`,
   `error_type`, `error_message`). Un agent qui plante EST un resultat, pas un trou.
5. Metriques : `latency_total_s = t1-t0`, `time_to_first_token_s`, `n_sql`, `total_rows`,
   tokens, cout.
6. Emettre une ligne dans `benchmark_runs_raw`, clef logique (run_id, question_id, agent_key,
   mode).

Execution : **concurrence bornee faible** (pool de threads borne, defaut 2-3), **timeout par
appel**, **ecriture incrementale** (append au fur et a mesure, pas tout en RAM ; un crash en
cours de run ne perd pas le travail deja fait ; `run_id` relie le tout). Securite instance
(regle non negociable) : petit set + concurrence basse + timeouts + appels agent = lectures
read-only (SELECT via semantic model). Pas de boucle non bornee, pas de retry agressif.

## 5. Golden set enrichi : dataset `golden_questions`

Colonnes (schema canonique) :

| colonne | type | role |
|---|---|---|
| `question_id` | string | identifiant stable (clef) |
| `question` | string | la question posee a l'agent |
| `reference_answer` | string | la bonne reponse validee par un humain |
| `expected_value` | string (nullable) | valeur/fait exact pour l'ancre objective |
| `expected_value_type` | enum (nullable) | numeric / currency / date / string / list |
| `category` | string | theme (revenus, tickets, ...) |
| `answer_type` | enum | number / fact / list / explanation |
| `difficulty` | enum | easy / medium / hard |
| `expected_mode` | enum (nullable) | mode vise par la question (eco/medium/high) |
| `target_agent` | string (nullable) | clef logique de l'agent cible (metadonnee) |
| `language` | enum | fr / en |
| `active` | boolean | inclure dans les runs |
| `notes` | string (nullable) | commentaire libre |

Alimentation (les deux convergent vers `golden_questions`) :
- **Intake Excel/CSV** : un dataset d'upload + une recette (prepare ou Python) qui valide et
  normalise vers le schema canonique (colonnes requises presentes, enums valides, ids uniques,
  trim, dedup). Echec de validation = message clair, jamais d'ecriture partielle silencieuse.
- **Dataset editable DSS** : edition en ligne, versionnable, initialise depuis l'Excel.
Le merge des deux sources est explicite et deterministe (la spec d'implementation precisera la
regle de priorite ; defaut propose : union par `question_id`, l'editable l'emporte sur l'upload
en cas de collision). Schema concu pour qu'une future section webapp y ecrive aussi.

## 6. Le juge : `benchmark/judge.py` (ancre objective + LLM structure)

Deux etages par ligne de `benchmark_runs_raw` :

1. **Ancre objective (deterministe, sans LLM).** Si `expected_value` present : normaliser la
   valeur attendue ET la **reponse complete** (`full_answer`, donc texte + cellules SQL
   aplaties) selon `expected_value_type` :
   - `numeric`/`currency` : retirer symboles devise, separateurs de milliers, normaliser la
     virgule decimale, parser en nombre, comparer avec tolerance relative (defaut 0.5%
     configurable) ; couvre le cas "la valeur est dans le tableau".
   - `date` : parser quelques formats usuels, comparer la date.
   - `string` : contains normalise (casse, accents, espaces).
   - `list` : match d'ensemble (toutes les valeurs attendues presentes).
   Sortie `objective_match in {hit, miss, n/a}` (`n/a` si pas de `expected_value`).
2. **Juge LLM structure.** Appel Mesh natif, modele fort et constant (Sonnet ; id dans
   `benchmark/config.py`), `with_json_output(schema)`. Entree : `question`, `reference_answer`,
   `expected_value`, et la **reponse complete** (`full_answer`). Sortie JSON :
   `{score: 1..5, verdict: "correct"|"incorrect", justification, missing_facts: [], hallucination: bool}`.
   Rubrique durcie a partir de la grille 1-5 existante (1 contradiction totale ... 5 parfaite),
   avec consigne explicite : juger le sens et l'exactitude, pas la formulation. Implementation
   en **recette Python** (pas la prompt visuelle) pour la sortie structuree fiable + la capture
   du **cout du juge lui-meme** (tokens/cout du juge tracks separement).
3. **Regle de correctness (deterministe).**
   - Avec ancre (`objective_match != n/a`) : `correct = (objective_match == "hit")`. Le score
     LLM ajoute la nuance et la justification.
   - Sans ancre : `correct = (verdict == "correct" and score >= 4)`.
   - `needs_review = true` si desaccord ancre vs juge (ancre hit mais verdict incorrect, ou
     ancre miss mais verdict correct, ou erreur de l'agent). Ces lignes sont les plus
     instructives (a relire en priorite).

Panel multi-votes / self-consistency : prevu dans le design (le juge peut etre appele N fois),
**desactive par defaut** (YAGNI pour le petit set).

Sortie : `benchmark_runs_scored` (= la table de detail lisible).

## 7. Agregation et restitution : `benchmark/scoring.py`

- `benchmark_summary` (1 ligne par run_id x agent x mode) :
  `n_questions, n_ok, n_error, error_rate, accuracy (% correct), mean_score, score_dist (json
  des comptes 1..5), latency_p50_s, latency_p95_s, latency_max_s, ttft_p50_s, avg_cost_per_q,
  total_cost, avg_input_tokens, avg_output_tokens, needs_review_count, judge_total_cost`.
- `benchmark_breakdown` (1 ligne par run x agent x mode x dimension x bucket) :
  `dimension in {category, answer_type, difficulty}`, `bucket`, `n`, `accuracy`, `mean_score`.
- `benchmark_runs_scored` sert de **table de detail** : question, categorie, reference, valeur
  attendue, **reponse complete de l'agent**, score, verdict, justification, faits manquants,
  objective_match, latence, ttft, cout, tokens, **SQL genere (preuve/debug)**, erreur,
  needs_review.
- `run_id` + `run_timestamp` + snapshot de config (json) relient tout et permettent la
  **comparaison entre runs** (regression / evolution dans le temps), proprement cette fois.

Restitution "parle a tout le monde" : le summary donne le tableau par agent x mode (taux de
bonnes reponses, latence p50/p95, cout moyen/question, taux d'erreur) ; le detail donne
"voici les questions, voici les reponses obtenues". Tout est exportable (le "rends-moi le
resultat complet"). Le dashboard DSS existant est recable sur ces datasets (provisoire ;
restitution webapp differee).

## 8. Le scenario (autonomie, a la demande, parametre)

Scenario `Run_Benchmark` du projet `OWIsMind_LAB`, etapes :
1. (optionnel) Build/valide `golden_questions` depuis intake + editable.
2. Step Python : run matrice -> `benchmark_runs_raw` (lit les variables de scenario : agents,
   modes, project, langue, filtre questions, concurrency).
3. Step Python : juge -> `benchmark_runs_scored`.
4. Step Python (ou recettes visuelles) : agregat -> `benchmark_summary` + `benchmark_breakdown`.
5. (optionnel) export / notification.

Config via **variables de scenario** : `agents` (liste de {project_key, agent_id, label}),
`modes`, `question_filter`, `language`, `concurrency`. "Je determine le ou les agents, les
questions, les bonnes reponses" = regler les variables + bouton **Run now**. Chaque run = un
resultat complet, identifie par `run_id`.

## 9. Layout repo et tests

Repo (nouveau package, source de verite) :
```
benchmark/
  README.md            # ce que c'est, comment recoller en project-library DSS, runbook
  agent_capture.py     # footer -> {text, sql_items, usage, artifacts, full_answer}  (source unique)
  agent_runner.py      # invoque agent x mode, capture, latence, erreurs, concurrence bornee
  judge.py             # ancre objective + juge LLM structure + regle de correctness
  scoring.py           # agregation, KPI, decoupages (pur, testable)
  schemas.py           # schemas golden/raw/scored/summary/breakdown + validation (pur)
  config.py            # ids LLM (juge), modes, caps, tolerances
  dss_steps/
    step_run_matrix.py # entrypoint scenario step 2
    step_judge.py      # entrypoint scenario step 3
    step_aggregate.py  # entrypoint scenario step 4
  tests/
    fixtures/          # footer traces reels captures (anonymises au besoin)
    test_capture.py    # parsing SQL/usage/full_answer sur fixtures
    test_objective_anchor.py  # normalisation + match numeric/currency/date/string/list
    test_correctness_rule.py  # combinaison ancre + juge + needs_review
    test_scoring.py    # maths d'agregation, percentiles, decoupages
    test_schemas.py    # validation golden + caps
```

Tests **NO INSTALL, pure-logic** (stdlib `unittest`), aucun appel DSS, aucun pandas top-level
(lazy import). Commande : `python3 -m unittest discover -s benchmark/tests`. Les fixtures de
footer verrouillent la parite de capture avec la webapp (capture d'un vrai run a faire sur
l'instance lors de l'implementation).

## 10. Securite instance et prerequis a verifier en DSS (discipline UNVERIFIED)

A confirmer sur l'instance (ne pas affirmer sans preuve) :
- Un step Python du projet `OWIsMind_LAB` peut appeler
  `dataiku.api_client().get_project("OWISMIND_DEV").get_llm("agent:038G7mlF").new_completion()
  .execute_streamed()` et recevoir le footer trace avec les spans `semantic-model-query` (la
  webapp le fait deja dans son propre projet ; reste a verifier le cross-projet + permissions :
  le user d'execution du scenario doit avoir acces a l'agent et a la connexion sous-jacente).
- Le format exact du token de mode et du delimiteur (lire `parse_mode` cote orchestrateur ne
  pas le deviner).
- Les ids/labels de modeles et l'id du LLM juge (Sonnet) valides dans la connexion Mesh.

Securite (non negociable) : concurrence bornee basse, timeouts, pas de boucle non bornee,
appels = lectures, ecriture incrementale, golden set petit. Aucun ecrit dans les tables de chat
de prod (`webapp_chat_v5` etc.) ; les datasets benchmark vivent dans `OWIsMind_LAB`.

## 11. Hors scope maintenant (YAGNI)

- Section/UI benchmark dans la webapp (differee ; schemas concus compatibles SQL `benchmark_*_v1`).
- Panel du juge / self-consistency (prevu, off par defaut).
- Declencheurs planifies ou sur recoll d'agent (a la demande seulement).
- Benchmark multi-tours (single-turn Q->A maintenant ; l'orchestrateur supporte l'historique
  si besoin plus tard).
- Refacto de la webapp pour qu'elle delegue au module de capture partage (nice-to-have futur).

## 12. Criteres d'acceptation

- Un run a la demande sur un petit golden set produit `benchmark_runs_raw`,
  `benchmark_runs_scored`, `benchmark_summary`, `benchmark_breakdown` coherents, relies par un
  `run_id`.
- La reponse capturee inclut le SQL et les lignes de resultat (verifiable : une question dont
  la reponse est dans un tableau est correctement scoree, alors que la capture texte-seul
  echouerait).
- Le summary expose par agent x mode : taux de bonnes reponses, latence p50/p95, cout
  moyen/question, taux d'erreur ; les decoupages par categorie/type/difficulte sont presents.
- Tests pure-logic verts (`python3 -m unittest discover -s benchmark/tests`), 0 tiret cadratin.
- Aucune ecriture dans les tables de prod ; concurrence bornee respectee.
