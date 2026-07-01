# Benchmark OWIsMind : prochaines etapes

Etat : code recolle en librairie, datasets crees (`golden_questions_v1_prepared` +
`benchmark_runs_raw` / `_scored` / `benchmark_summary` / `benchmark_breakdown`),
scenario `Run_Benchmark` (3 steps) et variable de projet `benchmark` en place.
Reference complete (schemas, modules) : `benchmark/README.md`. Il reste 4 etapes.

---

## Etape 1 : corriger la variable `benchmark` (modes Smart/Pro/Claude) + recoller 2 fichiers

Les modes s'ecrivent **Smart / Pro / Claude** PARTOUT. Le token envoye a
l'orchestrateur est la forme minuscule du meme nom (`smart` / `pro` / `claude`) :
plus aucun `eco/medium/high` nulle part. Smart = Gemini 3.1 Flash-Lite (defaut),
Pro = Gemini 3.5 Flash, Claude = Sonnet (les modeles sont inchanges, seul le nom du
token a change). **IMPORTANT** : ce renommage touche AUSSI l'orchestrateur et les
sous-agents (qui parsent ce token), donc il faut **recoller les Code Agents** (voir
`benchmark_webapp/DEPLOY_GUIDE.md` qui liste tout ce qu'il faut redeployer).

Comme le code a evolue depuis ton dernier recoll, **recolle ces 2 fichiers** dans
`python/benchmark/` : `config.py` et `run_params.py` (les autres sont inchangies).

Puis, dans `OWIsMind_LAB` -> menu projet -> Variables -> **Local variables**,
remplace l'objet `benchmark` par :

```json
"benchmark": {
  "golden_dataset": "golden_questions_v1_prepared",
  "agents": [
    {"agent_key": "038G7mlF",
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
4. **Historique (par defaut).** Chaque run **s'ajoute** aux 4 datasets de resultats au lieu
   d'ecraser le precedent : le summary a deja une ligne par (run_id x agent x mode), et la webapp
   Results liste tous les runs passes. Re-jouer Judge/Aggregate sur un meme `run_id` remplace ses
   lignes (idempotent), sans toucher aux autres runs. (Requiert d'avoir recolle les 3 steps + les
   nouveaux `history.py` / `dss_steps/history_io.py`, cf. `benchmark_webapp/DEPLOY_GUIDE.md`.)
   - **Borne par defaut** : les tables LOURDES (`benchmark_runs_raw` + `benchmark_runs_scored`)
     gardent les **50 runs** les plus recents (`history_keep_runs: 50`) ; les tables LEGERES
     (`benchmark_summary` + `benchmark_breakdown`) gardent **tout** (c'est l'historique que lit
     Results). Mettre `"history_keep_runs": 0` pour ne rien borner ; un entier pour une autre borne.
   - `"score_all_runs"` / `"aggregate_all_runs"` (defaut `false`) re-traitent TOUS les `run_id`
     d'un coup au lieu du dernier (rarement utile maintenant que l'historique est conserve).

---

## Etape 4 : la restitution (le beau resultat)

**Recommande : les webapps benchmark** (`benchmark_webapp/`). DEUX webapps DSS Standard dans
`OWIsMind_LAB` (pas de plugin, pas de build : on colle 4 panes par webapp dans le navigateur) :
- **Results** (publique, lecture seule) : restitution en langage clair (verdict de confiance,
  taux de bonnes reponses, temps de reponse, cout, a relire, par agent x mode / par theme /
  par question). Bilingue EN/FR.
- **Launcher** (interne) : **vrai formulaire** de configuration (agents/modes/filtre/concurrence/
  langue) + bouton Lancer + revue/promotion des questions suggerees par les utilisateurs.
**Guide de deploiement pas a pas (le plugin + les 2 webapps + config + tests) :
`benchmark_webapp/DEPLOY_GUIDE.md`** (reference courte : `benchmark_webapp/README.md`).

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
  dataiku au top-level. `python3 -m unittest discover -s OWIsMind_LAB/project-library/python/benchmark/tests -t OWIsMind_LAB/project-library/python`
  doit passer en stdlib seul ; si oui, re-coller. Les `dss_steps/` importent dataiku /
  pandas au top : normal, ils ne tournent que dans DSS.

---

## Plus tard (hors scope maintenant)

Promotion PROD : changer `benchmark.agents` pour l'orchestrateur PROD
(`project_key: "OWISMIND_PROD_V1"`, `agent_id: "agent:Xrv7GvfG"`). Section webapp
de benchmark, juge en panel, runs planifies : differes (les schemas restent
compatibles).
