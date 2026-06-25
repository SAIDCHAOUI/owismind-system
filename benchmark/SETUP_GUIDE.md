# Benchmark OWIsMind : prochaines etapes

Etat : code recolle en librairie, datasets crees (`golden_questions_v1_prepared` +
`benchmark_runs_raw` / `_scored` / `benchmark_summary` / `benchmark_breakdown`),
scenario `Run_Benchmark` (3 steps) et variable de projet `benchmark` en place.
Reference complete (schemas, modules) : `benchmark/README.md`. Il reste 4 etapes.

---

## Etape 1 : corriger la variable `benchmark` (modes Smart/Pro/Claude) + recoller 2 fichiers

Les modes s'ecrivent **Smart / Pro / Claude** (plus "eco"). En interne le token
envoye a l'orchestrateur reste `eco/medium/high` (renommage d'affichage cote
webapp, cles internes inchangees) : la traduction est faite par le code, tu ne vois
que Smart/Pro/Claude (config ET resultats).

Comme le code a evolue depuis ton dernier recoll, **recolle ces 2 fichiers** dans
`python/benchmark/` : `config.py` et `run_params.py` (les autres sont inchangies).

Puis, dans `OWIsMind_LAB` -> menu projet -> Variables -> **Local variables**,
remplace l'objet `benchmark` par :

```json
"benchmark": {
  "golden_dataset": "golden_questions_v1_prepared",
  "agents": [
    {"agent_key": "orchestrator",
     "agent_label": "OWIsMind Orchestrator (DEV)",
     "project_key": "OWISMIND_DEV",
     "agent_id": "agent:038G7mlF",
     "modes": true}
  ],
  "modes": ["Smart", "Pro", "Claude"],
  "language": "fr",
  "concurrency": 1,
  "question_filter": {}
}
```

A propos de l'agent dans un autre projet : c'est le `project_key` qui gere ca. Le
code fait `get_project("OWISMIND_DEV").get_llm("agent:038G7mlF")` : pas de prefixe a
mettre dans `agent_id`, juste le bon `project_key` (deja le cas). Seule condition :
l'utilisateur qui execute le scenario doit avoir acces a l'agent de `OWISMIND_DEV`
(droit de lecture sur le projet et sa connexion).

Le flag `"modes"` par agent : `true` = teste sur Smart/Pro/Claude (orchestrateur) ;
`false` ou absent = un seul appel simple, mode par defaut (un visual agent), la
ligne portera `mode = "default"`.

---

## Etape 2 : smoke run (1 question, Smart, concurrence 1)

But : prouver la capture COMPLETE avant de tout lancer.

1. Restreindre temporairement dans la variable `benchmark` :
   `"question_filter": {"question_ids": ["Q001"]}` (mets un vrai id de ton golden),
   `"modes": ["Smart"]`, `"concurrency": 1`.
2. Ouvrir le scenario `Run_Benchmark` -> **Run**. (Au depart tu peux ne lancer que
   le step `Run matrix` pour isoler la capture.)
3. En cas d'erreur : onglet **Last runs** -> le run -> log du step (message clair).
4. Ouvrir `benchmark_runs_raw` (Explore) et verifier la ou les lignes :
   - `status` = `ok`, `mode` = `Smart`.
   - `answer_text` non vide.
   - **`full_answer`** contient le texte ET un bloc `--- Data results ---` avec des
     lignes de tableau (preuve que le SQL est capture, pas juste le texte).
   - `generated_sql_json` n'est pas `[]` ; `n_sql` >= 1, `total_rows` > 0 pour une
     question chiffree ; `total_tokens` > 0 et `latency_total_s` renseigne.
5. Enchainer le juge + l'agregat (relancer le scenario complet sur ce meme 1 id) et
   verifier `benchmark_runs_scored` : `objective_match` = `hit` sur une question a
   valeur attendue, `judge_score` rempli, `correct` = true.

Si `generated_sql_json` reste `[]` sur une question chiffree : voir Depannage.

---

## Etape 3 : run complet + lecture

1. Dans la variable `benchmark` : `"question_filter": {}` (toutes les questions
   actives), `"modes": ["Smart", "Pro", "Claude"]`, `"concurrency": 3`.
2. Lancer `Run_Benchmark` (Run). Les 3 steps s'enchainent ; chaque run a un `run_id`.
3. Lire les sorties :
   - **`benchmark_summary`** (1 ligne par agent x mode) : `accuracy` (taux de bonnes
     reponses), `latency_p50_s` / `latency_p95_s` (delais par modele), `avg_cost_per_q`
     / `total_cost`, `error_rate`, `mean_score`, `needs_review_count`.
   - **`benchmark_runs_scored`** (detail par question) : question, reference,
     `full_answer`, `judge_verdict`, `judge_score`, `objective_match`, `correct`,
     latence, cout, `generated_sql_json` (preuve). Filtrer `needs_review = true` =
     la pile a relire en priorite (desaccord ancre vs juge, ou agent en erreur).
   - **`benchmark_breakdown`** : `accuracy` par categorie (bon en revenus / faible en
     tickets).
4. Regression : pour comparer plusieurs runs, mettre `"score_all_runs": true` et
   `"aggregate_all_runs": true` dans la variable ; le summary aura une ligne par
   (run_id x agent x mode).

---

## Etape 4 : la restitution (le beau resultat)

**Recommande : la webapp benchmark** (`benchmark_webapp/`). Une webapp DSS Standard dans
`OWIsMind_LAB` qui fait les 3 pages : **Resultats** (taux de bonnes reponses, latence,
cout par agent x mode + detail par question + filtre `needs_review`), **Lancer** (editer la
variable `benchmark` + lancer `Run_Benchmark`) et **Suggestions** (promouvoir les questions
suggerees par les utilisateurs dans le golden). Pas de plugin, pas de build : on colle 4
panes dans le navigateur DSS. Montage complet : **`benchmark_webapp/README.md`**.

**Alternative (zero code)** : un dashboard DSS natif sur les memes datasets, en 3 bandes.
Regles de lisibilite : formater `accuracy` en **pourcentage**, une **couleur fixe par mode**,
un filtre `run_id` fixe au dernier run.

- **Chiffres cles** (tuiles metric, `benchmark_summary`) : taux de bonnes reponses
  global, nombre de questions, configurations testees, cout total.
- **Comparaison agent x mode** (`benchmark_summary`, X = `agent_label`, couleur =
  `mode`) : 3 barres -> `accuracy` (%), `latency_p50_s` + `latency_p95_s`,
  `avg_cost_per_q`.
- **Detail + qualite** : tableau `benchmark_summary` trie par `accuracy` ; bar chart
  `benchmark_breakdown` (`accuracy` par categorie) ; tableau `benchmark_runs_scored`
  (question, `full_answer`, `judge_verdict`, `judge_score`, `needs_review`) avec un
  filtre `needs_review = true` en evidence.

---

## Depannage (les cas frequents)

- **Permissions / agent injoignable** (`get_llm` ou `execute_streamed` leve dans le
  log) : l'utilisateur d'execution du scenario doit avoir acces a l'agent
  `OWISMIND_DEV` et a sa connexion. Le step transforme l'echec en ligne
  `status="error"` (lire `error_type` / `error_message` dans `benchmark_runs_raw`).
- **`generated_sql_json` = `[]` sur une question chiffree** : l'orchestrateur n'a pas
  emis de span `semantic-model-query` (il a repondu de tete, ou le nom du span
  differe). Le capteur cherche `name == "semantic-model-query"` (`_SQL_TOOL_NAME`
  dans `agent_capture.py`). Verifier le vrai nom dans un footer reel (notebook :
  `agent_capture.extract_generated_sql(footer_trace)`), aligner si besoin.
- **Le juge renvoie un JSON invalide** : la ligne est marquee `needs_review` et ne
  casse pas le run. Si ca persiste, poser `"judge_llm_id"` (dans la variable
  `benchmark`) sur un modele qui supporte le JSON mode (Sonnet le fait).
- **Le mode semble ignore** : `config.build_message(q, "Claude", "fr")` doit finir
  par `⟦owi:mode=high⟧` (Claude -> high). En appel direct Mesh il n'y a pas de gate
  `profile.modes` : l'orchestrateur honore le token. Verifier que l'agent a bien
  `"modes": true`.
- **Import qui echoue en librairie** : un module pur ne doit pas importer pandas /
  dataiku au top-level. `python3 -m unittest discover -s benchmark/tests` doit
  passer en stdlib seul ; si oui, re-coller. Les `dss_steps/` importent dataiku /
  pandas au top : normal, ils ne tournent que dans DSS.

---

## Plus tard (hors scope maintenant)

Promotion PROD : changer `benchmark.agents` pour l'orchestrateur PROD
(`project_key: "OWISMIND_PROD_V1"`, `agent_id: "agent:Xrv7GvfG"`). Section webapp
de benchmark, juge en panel, runs planifies : differes (les schemas restent
compatibles).
