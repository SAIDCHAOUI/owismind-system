# Runbook de mise en place : benchmark des agents OWIsMind

Guide de bout en bout pour brancher le systeme de benchmark dans Dataiku DSS. Le
package Python (`benchmark/`) existe deja et est teste (136 tests verts en logique
pure). Ce guide ne contient PAS de code a ecrire de zero : il decrit les clics DSS,
les datasets a creer, le scenario a monter, et il vous dit exactement quel fichier
du package coller dans quel step. Vous (dev senior) faites les clics DSS vous-meme.

- Public : la personne qui realise la configuration dans DSS.
- Langue du guide : francais. Le code, les identifiants, les noms de dataset et de
  colonne restent en anglais (contrat repo).
- Contrat de conception (source de verite, a relire en cas de doute) :
  `docs/superpowers/specs/2026-06-24-agent-benchmark-evaluation-design.md`.
- Reference d'ingenierie DSS : `docs/cadrage/GUIDE_DATAIKU_DSS_PLUGIN_REFERENCE.md`.
- Carte des ids d'agents + discipline "le repo est la source de verite" :
  `dataiku-agents/OWISMIND/README.md`.

Temps estime : 60 a 90 minutes pour la premiere mise en place complete (recoll de
la librairie + assainissement + 5 datasets + 3 steps + 2 runs), puis quelques
minutes par run ensuite.

Regle de securite instance (non negociable, rappelee partout) : concurrence bornee
basse (defaut 3, plafonnee a 8), timeout par appel (120 s), appels agents en
lecture seule (SELECT via le semantic model), ecriture incrementale, petit golden
set. AUCUNE ecriture dans les tables de prod (`webapp_chat_v5`, etc.) : tous les
datasets du benchmark vivent dans le projet `OWIsMind_LAB`.

---

## 0. Vue d'ensemble : ce qu'on construit

Un benchmark mesure, par agent ET par mode de reponse (eco/medium/high =
Smart/Pro/Claude = Gemini Flash-Lite / Gemini Flash / Sonnet) : le taux de bonnes
reponses (precision), la latence (p50/p95), le cout, les tokens, le taux d'erreur,
avec une table de detail lisible par n'importe qui (question, reponse complete de
l'agent, verdict, justification).

Le defaut numero 1 du bricolage des stagiaires : leur step appelait
`get_llm(agent_id).new_completion().with_message(q).execute()` et ne gardait que
`.text`. Cela jetait le SQL genere et les LIGNES de resultat, donc une question
dont la reponse vit dans un tableau etait notee a l'aveugle. Le package corrige
cela : il relit le footer trace du run (comme la webapp de prod) et reconstruit la
reponse COMPLETE (texte + tables SQL serialisees + artefacts). C'est cette chaine
complete que voit le juge.

### Le Flow cible (dans OWIsMind_LAB)

```
  golden_questions_v1 (questions + reponses) --+
                                               |  (recette de preparation: validation / normalisation)
                                               v
                   golden_questions_v1_prepared   (le dataset que le benchmark LIT)
                                               |
                                               |  scenario Run_Benchmark
                                               |  (config = variable projet `benchmark`, section 5.3)
                                               v
   step 2  step_run_matrix.py  ->  benchmark_runs_raw
                                    (capture complete : answer_text, full_answer,
                                     generated_sql_json, latence, ttft, tokens, cout)
                                      |
                                      v
   step 3  step_judge.py       ->  benchmark_runs_scored
                                    (ancre objective deterministe + juge LLM Sonnet
                                     + regle de correctness + needs_review)
                                      |
                                      v
   step 4  step_aggregate.py   ->  benchmark_summary      benchmark_breakdown
                                    (KPI par run x         (precision par categorie)
                                     agent x mode)
                                      |
                                      v
                              Dashboard DSS (summary + detail + breakdown)
```

Les 3 steps sont de minces entrypoints : ils lisent UNE variable de projet
(`benchmark`, section 5.3), chargent les datasets, appellent la logique pure du
package recolle, et ecrivent les datasets de sortie via `write_with_schema`. Rien
n'est code en dur (pas meme les noms de datasets) : tu ne touches jamais au code.

### Les 3 prerequis DSS a verifier (detail pratique en section 9)

Tout cela est marque "verify on instance" dans le code : ne PAS l'affirmer sans
preuve.

1. **Appel cross-projet `get_llm` + footer trace recu.** Un step Python de
   `OWIsMind_LAB` doit pouvoir appeler
   `dataiku.api_client().get_project("OWISMIND_DEV").get_llm("agent:038G7mlF").new_completion().execute_streamed()`
   et recevoir un chunk `type == "footer"` portant un `trace` qui contient les
   spans `semantic-model-query`. La webapp le fait deja dans SON projet ; ici on
   verifie le cross-projet + les permissions (le user d'execution du scenario doit
   avoir acces a l'agent et a la connexion sous-jacente).
2. **Capturer un vrai footer pour figer une fixture.** Un dump d'un footer reel,
   ajoute en fixture, verrouille la parite de capture (le package est teste sur des
   fixtures synthetiques en attendant ; un footer reel les confirme).
3. **Id exact du LLM juge (Sonnet).** `config.JUDGE_LLM_ID` vaut
   `openai:LLM-7064-revforecast:vertex_ai/claude-sonnet-4-6` (identique au
   `SONNET_ID` de l'orchestrateur DEV, ligne 104). A confirmer dans la connexion
   Mesh de l'instance.

---

## 1. Recoller le code en project-library DSS

Meme discipline que les Code Agents : on developpe au repo, on colle en DSS. On
edite TOUJOURS au repo (`benchmark/`), puis on recolle. Jamais l'inverse : une
edition directe dans la librairie DSS sera ecrasee au prochain recoll.

1. Ouvrir le projet `OWIsMind_LAB` dans DSS.
2. Menu projet (en haut a gauche, l'engrenage ou le nom du projet) -> **Libraries**
   -> onglet **Python** (l'editeur de la librairie projet `python/`).
3. Sous `python/`, creer un dossier **`benchmark`** (c'est le package importable).
4. Y recreer l'arbre EXACT du package et coller le contenu de chaque fichier
   depuis le repo :

```
python/
  benchmark/
    __init__.py
    agent_capture.py        (pur : footer -> reponse complete)
    config.py               (pur : ids LLM juge, modes, caps, tokens, build_message)
    schemas.py              (pur : colonnes + enums + validate/normalize golden)
    run_params.py           (pur : LA config de run, lue depuis la variable `benchmark`)
    agent_runner.py         (dataiku lazy : run matrice, capture, latence, concurrence)
    judge.py                (dataiku lazy : ancre objective + juge LLM + correctness)
    scoring.py              (pur : summarize + breakdown)
    dss_steps/
      __init__.py
      step_run_matrix.py    (entrypoint scenario step 2)
      step_judge.py         (entrypoint scenario step 3)
      step_aggregate.py     (entrypoint scenario step 4)
```

   Ne PAS recopier `tests/`, `__pycache__/` ni `SETUP_GUIDE.md` / `README.md` : la
   librairie n'a besoin que des modules importables et des entrypoints.

5. Verifier que la librairie projet est bien sur le PYTHONPATH des recipes / steps
   (par defaut elle l'est dans DSS : tout ce qui est sous `python/` est importable).

Une fois recolle, un step de scenario importe le package comme un module normal :

```python
from benchmark import config, schemas
from benchmark import agent_runner
```

Note de portabilite : le package est volontairement AUTONOME (il recopie la
logique de capture de la webapp au lieu de l'importer), parce qu'il tourne dans un
projet DSS distinct ou le `python-lib` de la webapp n'est pas sur le path.

Alternative (option avancee, non recommandee au depart) : pointer la librairie
vers le repo via un import externe / un git reference dans les settings de la
librairie projet. Au depart, le copier-coller direct est plus simple et plus
robuste ; on garde la discipline "edit au repo, recoll en DSS".

---

## 2. Assainir OWIsMind_LAB (prudemment, rien ne se supprime sans votre validation)

Le projet a deja le bricolage des stagiaires. On REUTILISE ce qui sert de graine,
on REMPLACE ce qui est casse. Important : ne rien supprimer avant d'avoir valide
que le nouveau pipeline marche. Renommer / desactiver d'abord, supprimer ensuite.

A GARDER (graine) :
- **Le golden Excel des stagiaires** : il sert de graine pour remplir
  `golden_questions_v1_prepared` (section 3, avec un mapping de colonnes).
- **Le dashboard existant** : on le RECABLE sur les nouveaux datasets (section 8),
  on ne le refait pas de zero.

A REMPLACER (casse / pauvre) :
- **L'ancien step Python `get_llm().execute()` texte-seul** : remplace par les 3
  steps du package (capture complete). Ne pas le reutiliser : c'est le defaut
  numero 1.
- **L'ancien dataset `benchmark_raw_results`** (capture texte-seul) : remplace par
  `benchmark_runs_raw` (capture complete). Le laisser de cote (renomme, par ex.
  `benchmark_raw_results_legacy`) jusqu'a validation, puis le supprimer une fois le
  nouveau pipeline confirme.
- **La recette / prompt visuelle du juge** (score 1-5 non structure) : remplacee
  par le step Python juge (`step_judge.py`), sortie JSON structuree fiable + cout
  du juge capte separement. Desactiver la recette visuelle, ne pas la cabler dans
  le nouveau scenario.

Procedure prudente : creer les nouveaux datasets et le nouveau scenario A COTE de
l'ancien ; valider un run complet ; PUIS, et seulement apres validation, archiver /
supprimer les anciens objets. Aucune suppression destructrice tant que le nouveau
n'est pas vert (lecon repo L087 : on conseille avant de supprimer).

---

## 3. Le dataset des questions (golden_questions_v1_prepared)

C'est le golden set : les questions, les bonnes reponses, et la valeur exacte
attendue pour l'ancre objective. Le dataset que le benchmark LIT est celui pointe
par `benchmark.golden_dataset` (defaut `golden_questions_v1_prepared`). Peu importe
comment tu le remplis (dataset editable, ou un brut `golden_questions_v1` + une
recette de preparation -> `golden_questions_v1_prepared`) : ce qui compte est que
le dataset lu porte les colonnes du schema 3.1.

### 3.1 Schema EXACT (depuis `benchmark/schemas.py`, `GOLDEN_COLUMNS`)

Schema volontairement LEAN : la question, la vraie reponse, et de quoi verifier
objectivement quand un fait net existe. Rien d'autre.

| colonne | type DSS | requis | role / enum |
|---|---|---|---|
| `question_id` | string | oui | identifiant stable (clef) |
| `question` | string | oui | la question posee a l'agent |
| `reference_answer` | string | oui | la bonne reponse validee par un humain |
| `expected_value` | string | non | valeur / fait exact pour l'ancre objective |
| `expected_value_type` | string (enum) | non* | numeric / currency / date / string / list |
| `category` | string | non | theme pour le decoupage (revenus, tickets, ...) |
| `language` | string (enum) | non | fr / en (defaut fr si vide) |
| `active` | boolean | non | inclure la question dans les runs (defaut true) |
| `notes` | string | non | commentaire libre |

*Regle de validation (depuis `validate_golden_row`) : seuls `question_id`,
`question` et `reference_answer` sont requis. Si `expected_value` est rempli,
alors `expected_value_type` DOIT l'etre aussi (l'ancre objective a besoin du type
pour normaliser). `category` est facultatif mais recommande (il alimente le
decoupage "precision par categorie") : le laisser vide met simplement la ligne
hors decoupage. Les enums exacts vivent dans `schemas.py` :
`EXPECTED_VALUE_TYPES`, `LANGUAGES`, `MODES`.

### 3.2 Initialiser depuis l'Excel des stagiaires (mapping de colonnes)

Leur Excel a des noms differents. Mapper vers le schema canonique. Exemple typique
a adapter aux vrais en-tetes du fichier :

| colonne stagiaire (exemple) | colonne canonique |
|---|---|
| `reference_answer_matben` | `reference_answer` |
| `question_text` | `question` |
| `id` ou ligne sans id | `question_id` (generer si absent, ex. `Q001`, `Q002`, ...) |
| `theme` | `category` |
| (absent) | `expected_value` + `expected_value_type` (a enrichir, voir 3.4) |
| (absent) | `language` (defaut `fr`) |
| (absent) | `active` (defaut `true`) |

La seule vraie valeur ajoutee a remplir est `expected_value` (+ son type) quand la
reponse contient un fait net (un nombre, un montant, une date, une courte liste).
Le reste se mappe ou se met par defaut. Le prompt d'import (section 3.5) fait ce
travail automatiquement.

### 3.3 Remplir / preparer le dataset

Deux mises en place possibles (au choix) ; le benchmark lit toujours le dataset
nomme dans `benchmark.golden_dataset` :

- **Dataset editable DSS** (simple) : un dataset editable nomme directement
  `golden_questions_v1_prepared`, colonnes du schema 3.1, edite en ligne.
- **Brut + recette de preparation** (ton montage actuel) : un dataset brut
  `golden_questions_v1` (upload Excel ou editable) -> une recette **Python** ->
  `golden_questions_v1_prepared`. La recette valide / normalise contre le schema
  via le package. Corps de recette (court) :

```python
import dataiku
import pandas as pd
from benchmark import schemas

df = dataiku.Dataset("golden_questions_v1").get_dataframe()
df = df.where(pd.notnull(df), None)

# Mapping des colonnes source -> canonique (adapter aux vrais en-tetes).
RENAME = {"reference_answer_matben": "reference_answer", "question_text": "question",
          "theme": "category"}
df = df.rename(columns=RENAME)

clean, errors = [], []
for i, record in enumerate(df.to_dict(orient="records")):
    norm = schemas.normalize_golden_row(record)
    ok, errs = schemas.validate_golden_row(norm)
    if ok:
        clean.append({c: norm.get(c) for c in schemas.GOLDEN_COLUMNS})
    else:
        errors.append("row {0}: {1}".format(i, "; ".join(errs)))

if errors:
    # Echec clair, jamais d'ecriture partielle silencieuse.
    raise ValueError("golden validation failed:\n" + "\n".join(errors))

out = pd.DataFrame(clean, columns=list(schemas.GOLDEN_COLUMNS))
dataiku.Dataset("golden_questions_v1_prepared").write_with_schema(out)
```

Le plus rapide : faire produire directement `golden_questions_v1_prepared` au bon
schema par le prompt d'import (section 3.5), et ne garder cette recette que si tu
veux revalider un import en lot.

### 3.4 Exemple de questions (revenus + tickets)

Regle simple : `expected_value` rempli quand la reponse contient UN fait net
(nombre, montant, date, courte liste) ; laisse-le vide pour une question
ouverte / explicative (le juge LLM tranche alors seul). Les valeurs ci-dessous
sont fictives, a remplacer par tes vraies reponses.

| question_id | question | reference_answer | expected_value | expected_value_type | category | language | active |
|---|---|---|---|---|---|---|---|
| `Q001` | Quel est le revenu actuals YTD du compte Airbus ? | Le revenu actuals YTD d'Airbus est de 1 234 567 EUR. | `1234567` | `currency` | `revenus` | `fr` | `true` |
| `Q002` | Combien de tickets ouverts pour le service X ? | Il y a 42 tickets actuellement ouverts pour le service X. | `42` | `numeric` | `tickets` | `fr` | `true` |
| `Q003` | Cite les 3 principales SolutionLine en revenu pour le client Z. | Les 3 principales sont IP, Voice et Roaming. | `IP; Voice; Roaming` | `list` | `revenus` | `fr` | `true` |
| `Q004` | Pourquoi le revenu du compte W a-t-il baisse au T3 ? | La baisse vient de la fin du contrat roaming et d'un churn sur la voix. | _(vide)_ | _(vide)_ | `revenus` | `fr` | `true` |

Comment l'ancre objective compare (sur la reponse COMPLETE : texte + lignes SQL) :
- `currency` / `numeric` : tolerent devise, separateurs de milliers et virgule
  decimale ; comparaison avec une tolerance relative de 0.5 % (`config.NUMERIC_TOLERANCE`).
  Donc `1234567` matche "1 234 567 EUR", meme si le chiffre n'est que dans le tableau.
- `date` : parse plusieurs formats usuels (`2025-12-31`, `31/12/2025`, ...).
- `list` : exige que CHAQUE item attendu soit present (match d'ensemble, insensible
  a la casse / aux accents). Delimiteur `;`, `,`, `|` ou retour ligne.
- `string` : contains normalise.
- Pas d'`expected_value` (Q004) : ancre = `n/a`, la ligne est notee par le juge LLM seul.

### 3.5 Remplir le golden automatiquement (prompt pour votre IA interne)

Pour eviter de transformer le dataset ground-truth a la main, utilisez le prompt
pret a l'emploi `benchmark/GOLDEN_IMPORT_PROMPT.md` : vous le collez dans votre IA
interne avec votre dataset existant (questions + bonnes reponses), elle produit le
CSV au schema 3.1 ci-dessus (y compris l'extraction de `expected_value` +
`expected_value_type` quand un fait net existe). Vous chargez ce CSV dans
`golden_questions_v1_prepared` (ou dans le brut `golden_questions_v1` + recette de
preparation, section 3.3).

---

## 4. Creer les datasets de sortie manages

Quatre datasets manages, ECRITS par les steps via `write_with_schema` (vous n'avez
PAS a definir leurs colonnes a la main : le step impose le schema canonique a
chaque ecriture). Vous pouvez soit les laisser DSS les creer au premier run du
step, soit les pre-creer en datasets manages vides dans le Flow (connexion par
defaut du projet). Les colonnes ci-dessous viennent de `benchmark/schemas.py`.

### 4.1 benchmark_runs_raw (ecrit par step_run_matrix, `RAW_COLUMNS`)

Une ligne par (run_id, question_id, agent_key, mode). Colonnes (30) :
`run_id`, `run_timestamp`, `config_json`, `question_id`, `question`, `category`,
`language`, `reference_answer`, `expected_value`,
`expected_value_type`, `agent_key`, `agent_label`, `project_key`, `agent_id`,
`mode`, `status` (ok/error/timeout), `error_type`, `error_message`, `answer_text`
(texte final seul), `full_answer` (texte + tables SQL + artefacts : l'entree du
juge), `generated_sql_json` (preuve / debug), `artifacts_json`, `n_sql`,
`total_rows`, `latency_total_s`, `time_to_first_token_s`, `prompt_tokens`,
`completion_tokens`, `total_tokens`, `estimated_cost`.

### 4.2 benchmark_runs_scored (ecrit par step_judge, `SCORED_COLUMNS`)

= toutes les colonnes de `benchmark_runs_raw` PLUS : `objective_match`
(hit/miss/n/a), `judge_score` (1..5), `judge_verdict` (correct/incorrect),
`judge_justification`, `judge_missing_facts_json`, `judge_hallucination`,
`judge_prompt_tokens`, `judge_completion_tokens`, `judge_total_tokens`,
`judge_estimated_cost`, `correct` (boolean, regle finale), `needs_review`
(boolean). C'est la table de DETAIL lisible.

### 4.3 benchmark_summary (ecrit par step_aggregate, `SUMMARY_COLUMNS`)

Une ligne par (run_id, agent_key, mode) :
`run_id`, `run_timestamp`, `agent_key`, `agent_label`, `mode`, `n_questions`,
`n_ok`, `n_error`, `error_rate`, `accuracy` (% correct), `mean_score`,
`score_dist_json` (comptes 1..5), `latency_p50_s`, `latency_p95_s`,
`latency_max_s`, `ttft_p50_s`, `avg_cost_per_q`, `total_cost`, `avg_input_tokens`,
`avg_output_tokens`, `needs_review_count`, `judge_total_cost`.

### 4.4 benchmark_breakdown (ecrit par step_aggregate, `BREAKDOWN_COLUMNS`)

Une ligne par (run_id, agent_key, mode, dimension, bucket) :
`run_id`, `run_timestamp`, `agent_key`, `agent_label`, `mode`, `dimension`
(category), `bucket`, `n`, `accuracy`, `mean_score`.

---

## 5. Creer le scenario Run_Benchmark

Flow / menu **Scenarios** -> **+ New scenario** -> nommer `Run_Benchmark`. Type :
sequence de steps. On y met 3 (ou 4) steps Python.

### 5.1 Choix du code env

Ces steps utilisent `dataiku` + `pandas` (au top des entrypoints) et appellent les
agents via Mesh. Ils n'ont PAS besoin de langchain / langgraph (ca, c'est pour les
Code Agents). Un code env Python 3.x avec acces DSS et `pandas` suffit. Choisir
l'env builtin du projet ou un env 3.x standard qui a `pandas`. (NB : la logique
pure du package est testee en stdlib seul ; pandas n'est requis que dans les
entrypoints `dss_steps/`, qui tournent dans DSS.)

### 5.2 Les 3 steps Python (quel fichier dans quel step)

Pour chaque step : type **"Execute Python code"** (Custom Python step), code env
ci-dessus, et coller le CORPS du fichier indique. Chaque fichier se termine deja
par un appel `run()` : c'est l'entrypoint, rien d'autre a ecrire.

| ordre | nom du step | coller le corps de | ecrit |
|---|---|---|---|
| step 2 | `Run matrix` | `benchmark/dss_steps/step_run_matrix.py` | `benchmark_runs_raw` |
| step 3 | `Judge` | `benchmark/dss_steps/step_judge.py` | `benchmark_runs_scored` |
| step 4 | `Aggregate` | `benchmark/dss_steps/step_aggregate.py` | `benchmark_summary` + `benchmark_breakdown` |

(Step 1 optionnel "build golden" : seulement si vous utilisez la recette d'intake
de la section 3.3 ; sinon le golden editable est deja a jour, pas de step 1.)

Chaque step importe le package recolle (`from benchmark import ...`). Les steps
sont sequentiels : step 3 lit ce que step 2 a ecrit (par defaut le dernier
`run_id`), step 4 lit ce que step 3 a ecrit.

### 5.3 LA configuration : une seule variable projet `benchmark`

IMPORTANT : selon les versions de DSS, le scenario n'a PAS d'onglet "Variables".
Toute la config vit donc dans les **variables de projet** (lues par le code via
`dataiku.get_custom_variables()`). Et tout est regroupe dans UN seul objet, pour
ne JAMAIS toucher au code : tu n'edites que le dataset des questions et cet objet.

Ou : `OWIsMind_LAB` -> menu projet (engrenage) -> **Variables**. Dans la section
**Local variables** (overrides, non exportes au bundle ; c'est la qu'on met la
config de run), AJOUTE une clef `benchmark` a l'objet JSON existant (ne remplace
PAS le reste, fusionne) :

```json
{
  "...tes variables existantes...": "...",
  "benchmark": {
    "golden_dataset": "golden_questions_v1_prepared",

    "agents": [
      {"agent_key": "orchestrator",
       "agent_label": "OWIsMind Orchestrator (DEV)",
       "project_key": "OWISMIND_DEV",
       "agent_id": "agent:038G7mlF",
       "modes": true}
    ],

    "modes": ["eco", "medium", "high"],
    "language": "fr",
    "concurrency": 3,
    "question_filter": {}
  }
}
```

Toutes les clefs de l'objet `benchmark` (defaut applique si absente) :

| clef | lue par | role | defaut |
|---|---|---|---|
| `agents` | step 2 (REQUISE) | liste des agents a benchmarker (voir plus bas) | aucun (erreur claire si vide) |
| `golden_dataset` | step 2 | dataset des questions | `golden_questions_v1_prepared` |
| `modes` | step 2 | modes testes sur les agents qui les supportent | `["eco","medium","high"]` |
| `language` | step 2 | `fr` ou `en` | `fr` |
| `concurrency` | step 2 | pool borne (clampe 1..8) | `3` |
| `question_filter` | step 2 | filtre optionnel (voir plus bas) | `{}` |
| `raw_dataset` | step 2 | dataset de sortie brut | `benchmark_runs_raw` |
| `scored_dataset` | step 3 | dataset de detail note | `benchmark_runs_scored` |
| `summary_dataset` | step 4 | dataset de synthese | `benchmark_summary` |
| `breakdown_dataset` | step 4 | dataset par categorie | `benchmark_breakdown` |
| `judge_llm_id` | step 3 | override du modele juge | `config.JUDGE_LLM_ID` (Sonnet) |
| `score_all_runs` | step 3 | `true` = re-juger tous les run_id | `false` (dernier run) |
| `aggregate_all_runs` | step 4 | `true` = agreger tous les run_id | `false` (dernier run) |

**Les agents (`agents`)** : une liste d'objets `{agent_key, agent_label,
project_key, agent_id, modes}`. La cible par defaut = l'orchestrateur DEV de bout
en bout (l'experience reelle). Tous les agents d'un meme run doivent partager le
MEME `project_key` (un melange leve une erreur claire qui dit de scinder le run).
Pour isoler un sous-agent (DEV) : revenue `agent:bHrWLyOL`, tickets `agent:NcE9LD2i`.

**Le flag `modes` PAR agent** (ta precision) :
- `"modes": true` : l'agent supporte le Smart/Pro/Claude (l'orchestrateur). Il est
  teste une fois par mode de la liste `modes`, avec le token de mode ajoute.
- `"modes": false` ou absent : l'agent ne les supporte pas (un visual agent
  simple). Un SEUL appel "nu" (sans token), l'agent repond dans son mode par
  defaut. C'est suffisant. La ligne de resultat porte `mode = "default"`.

Donc on melange sans souci des agents a modes et des agents simples dans la meme
liste : chacun est appele comme il faut.

**Le filtre (`question_filter`)**, optionnel (AND entre clefs, OR a l'interieur) :

```json
{"categories": ["revenus"], "question_ids": ["Q001", "Q002"], "languages": ["fr"]}
```

Il s'applique PAR-DESSUS `active=True` : une question doit etre active ET passer le
filtre. Filtre vide = toutes les questions actives.

Note : apres avoir change une variable de projet, relance simplement le scenario
(les steps relisent les variables a chaque run).

---

## 6. Premier smoke run (1-2 questions, mode eco, concurrence 1)

But : prouver la chaine de capture AVANT de lancer la matrice complete. On verifie
le point cle : `generated_sql` et les LIGNES de resultat sont bien captures, pas
juste le texte.

1. Reduire le perimetre dans la variable `benchmark` (section 5.3) :
   `"question_filter": {"question_ids": ["Q001"]}`, `"modes": ["eco"]`,
   `"concurrency": 1`, et `agents` = l'orchestrateur DEV (`modes: true`).
2. Lancer : ouvrir le scenario `Run_Benchmark`, bouton **Run** (Run now). Au depart
   on peut ne lancer QUE le step 2 (`Run matrix`) pour isoler la capture, puis
   ajouter juge + aggregate.
3. Lire les logs : onglet **Last runs** du scenario -> cliquer le run -> log du step
   `Run matrix`. Une exception y apparait en clair (permissions, agent injoignable,
   etc.).
4. Verifier `benchmark_runs_raw` (Explore) sur les 1-2 lignes attendues :
   - `status` = `ok` (pas error / timeout).
   - `answer_text` non vide.
   - `full_answer` contient le texte ET un bloc `--- Data results ---` avec des
     lignes de tableau (c'est la preuve que la capture du SQL marche).
   - `generated_sql_json` n'est pas `[]` : il porte le ou les `semantic-model-query`
     (sql + result.columns + result.rows).
   - `n_sql` >= 1, `total_rows` > 0 pour une question chiffree.
   - `latency_total_s` et `time_to_first_token_s` renseignes ; `total_tokens` > 0.
5. Si `generated_sql_json` est `[]` alors que la reponse vit dans un tableau :
   l'agent ne renvoie pas le span SQL attendu dans le footer -> voir Depannage
   (section 10), c'est le seul vrai point a sur-verifier au demarrage.
6. Quand la capture est bonne : ajouter / activer les steps `Judge` puis
   `Aggregate` et relancer le scenario complet sur ce meme petit perimetre.
   Verifier `benchmark_runs_scored` : `objective_match` = `hit` sur Q001 (la valeur
   attendue est dans la reponse), `judge_score` renseigne, `correct` = true.

---

## 7. Run complet + lecture des resultats

1. Elargir le perimetre dans la variable `benchmark` : `"question_filter": {}`
   (toutes les questions actives), `"modes": ["eco","medium","high"]`,
   `"concurrency": 3`, et `agents` = l'agent (ou les agents) voulu(s).
2. Lancer le scenario complet (Run now). Chaque run = un resultat complet identifie
   par un `run_id` unique (stampe par le step). Les 3 steps s'enchainent.

### Lire benchmark_summary (le tableau "parle a tout le monde")

Une ligne par (agent x mode). Colonnes a regarder en premier :
- `accuracy` : taux de bonnes reponses (fraction [0,1]).
- `latency_p50_s` / `latency_p95_s` / `latency_max_s` : delais ; p50 = mediane,
  p95 = queue lente. C'est la reponse directe au besoin "delais par modele".
- `ttft_p50_s` : temps jusqu'au premier token (reactivite percue).
- `avg_cost_per_q` / `total_cost` : cout. `judge_total_cost` = cout du juge a part.
- `error_rate` / `n_error` : robustesse de l'agent dans ce mode.
- `mean_score` + `score_dist_json` : note moyenne et distribution 1..5.
- `needs_review_count` : le nombre de lignes a relire en priorite (voir plus bas).

### Lire benchmark_runs_scored (le detail par question)

C'est la table "voici les questions, voici les reponses obtenues". Par ligne :
question, categorie, reference, valeur attendue, `full_answer` (reponse complete de
l'agent), `judge_score`, `judge_verdict`, `judge_justification`,
`judge_missing_facts_json`, `objective_match`, latence, ttft, cout, tokens,
`generated_sql_json` (preuve / debug), `error_*`, `needs_review`.

La colonne `needs_review` = la PILE A RELIRE EN PRIORITE. Elle vaut true quand
l'ancre objective deterministe et le juge LLM sont en DESACCORD (ancre hit mais
juge incorrect, ou ancre miss mais juge correct) ou quand l'agent a plante. Ce sont
les lignes les plus instructives : soit le golden est a corriger, soit le juge se
trompe, soit l'agent a un vrai bug. Filtrer `needs_review = true` et trier par la.

### Lire benchmark_breakdown (par categorie)

Une ligne par (agent x mode x categorie). Permet de dire "l'agent est bon en
revenus mais faible en tickets". Filtrer par `bucket` (la categorie).

### run_id : comparer des runs (regression)

Chaque run porte un `run_id` + `run_timestamp` + un snapshot de config
(`config_json`). Par defaut, step 3 et step 4 ne traitent QUE le dernier `run_id`.
Pour comparer plusieurs runs dans le temps (regression / evolution apres un recoll
d'agent) : mettre `score_all_runs` et `aggregate_all_runs` a `true` dans la variable
`benchmark`, et empiler les `benchmark_runs_raw` de plusieurs runs (union par `run_id`).
Le summary aura alors une ligne par (run_id x agent x mode) : on lit la difference
d'`accuracy` / latence / cout entre deux `run_id` pour mesurer une regression.

---

## 8. Le tableau de bord (le beau resultat)

Objectif : une page qui parle a n'importe qui en dix secondes. Voici mes agents,
voici le taux de bonnes reponses, voici les delais par modele, voici le cout, et le
detail des questions / reponses dessous. On recable le dashboard des stagiaires (ou
on en cree un neuf : Dashboard -> + New) sur les nouveaux datasets, en 3 bandes.

Regle d'or de lisibilite (a appliquer partout) :
- `accuracy` est une fraction [0, 1] : la formater en **pourcentage** (axe ou
  colonne en %, 0 decimale). C'est le chiffre que tout le monde regarde.
- Une **couleur fixe par mode** sur TOUS les graphiques (ex. Smart/eco, Pro/medium,
  Claude/high), pour que l'oeil compare les modes d'un coup.
- Si plusieurs runs sont empiles, ajouter un **filtre `run_id`** sur la page et le
  fixer au dernier run (sinon les chiffres se melangent entre runs).
- Titres en clair (pas de noms de colonnes bruts) ; trier les barres par valeur
  decroissante.

### Bande 1 : les chiffres cles (tuiles "metric", source `benchmark_summary`)

- **Taux de bonnes reponses global** : moyenne de `accuracy` (formatee en %). Le
  chiffre phare.
- **Questions testees** : `n_questions` (sur une ligne agent x mode), ou un compte
  distinct de `question_id` sur `benchmark_runs_scored`.
- **Configurations testees** : compte de lignes de `benchmark_summary` (= agents x
  modes).
- **Cout total** : somme de `total_cost` (+ a cote, somme de `judge_total_cost` pour
  le cout d'evaluation).

### Bande 2 : la comparaison agent x mode (le coeur)

Trois graphiques cote a cote, tous sur `benchmark_summary`, X = `agent_label`,
serie / couleur = `mode` :

- **Precision par agent et mode** : barres groupees, Y = `accuracy` (en %). La
  reponse directe a "quel agent / mode repond le mieux".
- **Latence par agent et mode** : barres, Y = `latency_p50_s` (mediane) et
  `latency_p95_s` (queue lente) cote a cote. La reponse a "les delais par modele".
- **Cout par question** : barres, Y = `avg_cost_per_q`. La reponse a "combien ca
  coute".

### Bande 3 : detail et qualite

- **Tableau de synthese** (`benchmark_summary`, trie par `accuracy` desc) :
  `agent_label`, `mode`, `accuracy` (%), `mean_score`, `latency_p50_s`,
  `latency_p95_s`, `avg_cost_per_q`, `error_rate` (%), `needs_review_count`. C'est
  la photo complete "agents x modes" sur une ligne chacun.
- **Precision par categorie** (`benchmark_breakdown`) : barres, X = `bucket`
  (la categorie), Y = `accuracy` (%), couleur = `mode`. Montre "bon en revenus,
  faible en tickets".
- **Tableau de detail** (`benchmark_runs_scored`) : `question`, `category`,
  `reference_answer`, `full_answer`, `judge_verdict`, `judge_score`,
  `objective_match`, `correct`, `latency_total_s`, `estimated_cost`,
  `needs_review`. Ajouter un **filtre `needs_review = true`** bien visible : c'est la
  pile a relire (desaccords ancre vs juge ou agent en erreur).
- (Quand plusieurs runs existent) **Evolution dans le temps** : courbe, X =
  `run_timestamp`, Y = `accuracy` (%), une serie par (`agent_label` x `mode`). Lit
  une regression d'un run a l'autre.

Pour chaque tuile : editer -> source -> choisir le dataset -> mapper les colonnes
ci-dessus -> regler l'agregation (les datasets summary / breakdown ont deja une
ligne par groupe, donc `MAX` ou `AVG` rendent la valeur telle quelle). Ce dashboard
DSS est la restitution immediate ; la version webapp grand public viendra plus tard
(les memes datasets la nourriront).

---

## 9. Verifier les 3 prerequis DSS en pratique

A faire une fois, dans un notebook Python de `OWIsMind_LAB` (env DSS standard).

### 9.1 Appel cross-projet + footer trace recu

```python
import dataiku
from benchmark import config

project = dataiku.api_client().get_project("OWISMIND_DEV")
completion = project.get_llm("agent:038G7mlF").new_completion()
completion.with_message(config.build_message("Revenu actuals YTD du compte Airbus ?",
                                             "eco", "fr"), "user")

# Footer detection mirrors production (streaming._is_footer_chunk) AND the runner:
# primarily data["type"] == "footer", with an isinstance fallback for SDKs that do
# not stamp that on .data. The runner does this for you ; here we reproduce it just
# to verify the trace arrives.
try:
    from dataikuapi.dss.llm import DSSLLMStreamedCompletionFooter
except Exception:
    DSSLLMStreamedCompletionFooter = None

footer_trace = None
text_parts = []
for chunk in completion.execute_streamed():
    data = getattr(chunk, "data", {}) or {}
    is_footer = (data.get("type") == "footer") or (
        DSSLLMStreamedCompletionFooter is not None
        and isinstance(chunk, DSSLLMStreamedCompletionFooter))
    if is_footer:
        footer_trace = data.get("trace") if isinstance(data, dict) else None
    elif data.get("type") in ("content", "text"):
        text_parts.append(data.get("text", "") or "")

print("got footer:", footer_trace is not None)
print("text length:", len("".join(text_parts)))
```

Attendu : `got footer: True`. Si KO -> permissions (le user du notebook / du
scenario doit avoir acces a l'agent `OWISMIND_DEV` ET a la connexion sous-jacente)
ou cross-projet bloque. Voir Depannage.

### 9.2 Capturer un vrai footer pour le figer en fixture

Une fois le footer obtenu, le passer dans le module de capture et verifier qu'il
extrait bien le SQL et les lignes :

```python
import json
from benchmark import agent_capture

sql_items = agent_capture.extract_generated_sql(footer_trace)
usage = agent_capture.extract_usage(footer_trace)
print("n_sql:", len(sql_items), "| usage:", usage)
print(json.dumps(sql_items[:1], indent=2, default=str)[:1500])
```

Si `n_sql >= 1` avec un `result.rows` non vide : la parite de capture est confirmee
sur un cas reel. Copier un footer reel (anonymise au besoin) dans
`benchmark/tests/fixtures/footer_traces.py` cote repo, ajouter un test de capture
dessus, relancer `python3 -m unittest discover -s benchmark/tests`. Cela fige la
parite (les fixtures actuelles sont synthetiques, calees sur la forme reelle).

### 9.3 Id exact du LLM juge (Sonnet)

```python
from benchmark import config
print(config.JUDGE_LLM_ID)
# Tester un appel juge reel sur une ligne fictive :
from benchmark import judge
proj = dataiku.api_client().get_project(dataiku.default_project_key())
out = judge.run_llm_judge(proj, "2+2 ?", "La reponse est 4.", "4", "Le resultat est 4.")
print(out)
```

Attendu : un dict avec `verdict` = `correct`, `score` >= 4, `error` = None. Si
`error` est rempli (`get_llm failed` / `json_mode_unavailable`) -> l'id n'est pas le
bon ou le mode JSON n'est pas dispo sur ce modele dans la connexion Mesh. Le plus
simple : poser `benchmark.judge_llm_id` (variable projet) sur un modele qui supporte
le JSON. Sinon corriger le defaut `config.JUDGE_LLM_ID` au repo et recoller `config.py`.

---

## 10. Depannage

- **Permissions / agent injoignable.** Le user qui execute le scenario doit avoir
  acces a l'agent `OWISMIND_DEV` (et a la connexion SQL sous-jacente que l'agent
  interroge). Symptome : `get_llm` ou `execute_streamed` leve dans le log du step.
  Le step transforme deja l'echec en ligne `status="error"` (un agent qui plante
  EST un resultat) ; lisez `error_type` / `error_message` dans `benchmark_runs_raw`.
  Verifier les droits du compte d'execution sur le projet `OWISMIND_DEV`.
- **L'agent ne renvoie pas de SQL dans le footer.** `generated_sql_json` = `[]`,
  `n_sql` = 0 sur une question chiffree. Causes possibles : la question n'a pas
  declenche d'appel `semantic-model-query` (l'orchestrateur a repondu de tete ou via
  `attribute_lookup` sans SQL), ou le nom du span differe. Le capteur cherche
  `name == "semantic-model-query"` (constante `_SQL_TOOL_NAME` dans
  `agent_capture.py`). Verifier le vrai nom du span dans le footer reel (section
  9.2) ; s'il differe, c'est la SEULE valeur a aligner. La capture reste best-effort
  et ne plante jamais (footer illisible -> `[]`).
- **Timeouts.** `status="timeout"` : l'appel a depasse `per_call_timeout_s` (120 s,
  `config.PER_CALL_TIMEOUT_S`). Le run continue (pas de retry, instance protegee).
  Si beaucoup de timeouts : baisser `benchmark.concurrency`, ou augmenter
  `benchmark.per_call_timeout_s` (en restant raisonnable pour l'instance).
- **Le juge renvoie un JSON invalide.** Le juge ne plante jamais le run : il rend un
  dict sur avec `verdict=None` et un `error` rempli, la ligne est marquee
  `needs_review`. Le code tente d'abord `with_json_output`, puis un parse tolerant
  (fence ```json, premier bloc `{...}`). Si l'`error` persiste : le modele juge ne
  supporte pas le JSON mode -> changer `benchmark.judge_llm_id` pour un modele qui
  le supporte (Sonnet le fait).
- **Le mode n'est pas pris en compte.** L'agent semble repondre pareil quel que soit
  le mode. Verifier le token : `config.build_message(q, "high", "fr")` doit finir par
  le token exact `⟦owi:mode=high⟧` (avec les vrais crochets U+27E6 / U+27E7). Le
  parseur cote orchestrateur (`parse_mode`, regex `_MODE_TOKEN_RE`) lit le DERNIER
  token, donc l'ajout en fin de message force le mode. En appel direct Mesh, le gate
  webapp `profile.modes` ne s'applique PAS : l'orchestrateur honore le token quoi
  qu'il arrive (c'est voulu pour forcer un mode au benchmark). Si rien ne change :
  comparer les crochets de `config.py` (`_LB` / `_RB`) avec ceux de l'orchestrateur.
- **pandas / dataiku manquant en project-library.** Si un IMPORT echoue au chargement
  d'un module pur (`agent_capture`, `schemas`, `config`, `judge`, `scoring`), c'est
  qu'un import lourd a fuite au top-level. Par contrat, ces modules sont stdlib-only
  (pandas / dataiku importes LAZY dans les fonctions, ou seulement dans les
  entrypoints `dss_steps/`). Verifier au repo
  (`python3 -m unittest discover -s benchmark/tests` doit passer en stdlib seul) puis
  recoller. Les steps `dss_steps/` importent dataiku / pandas au top : c'est normal,
  ils ne tournent QUE dans DSS.

---

## 11. Promotion DEV -> PROD + evolutions (pointeurs, hors scope maintenant)

- **Promotion.** Une fois le benchmark valide sur DEV (orchestrateur
  `agent:038G7mlF`), benchmarker la PROD = changer `benchmark.agents` pour
  l'orchestrateur PROD :
  `{"agent_key":"orchestrator","agent_label":"OWIsMind Orchestrator (PROD)",
  "project_key":"OWISMIND_PROD_V1","agent_id":"agent:Xrv7GvfG"}`. Meme discipline
  que les agents : on valide en DEV, puis on benchmarke la PROD. Le golden set et
  les datasets de sortie restent dans `OWIsMind_LAB` ; seul l'agent cible change.
- **Idees d'evolution (differees, YAGNI maintenant)** :
  - Section / UI benchmark dans la webapp (les schemas sont concus compatibles SQL
    `benchmark_*_v1`).
  - Juge en panel (N votes / self-consistency) : prevu dans le design, OFF par
    defaut.
  - Runs planifies (declencheur de scenario sur cron) ou sur recoll d'agent.
  - Refacto de la webapp pour qu'elle delegue au module de capture partage (nice to
    have).

---

## Checklist de mise en place

- [ ] Librairie projet recollee : `python/benchmark/...` (modules + `dss_steps/`),
      edition au repo seulement.
- [ ] OWIsMind_LAB assaini : golden Excel garde comme graine, dashboard garde, vieux
      step texte-seul + `benchmark_raw_results` + recette juge visuelle desactives
      (pas supprimes avant validation).
- [ ] Dataset des questions pret : `golden_questions_v1_prepared` (schema
      `GOLDEN_COLUMNS`), avec `expected_value` + `expected_value_type` remplis quand
      un fait net existe (via le prompt d'import section 3.5).
- [ ] Datasets de sortie prets : `benchmark_runs_raw`, `benchmark_runs_scored`,
      `benchmark_summary`, `benchmark_breakdown` (crees / ecrits par les steps).
- [ ] Scenario `Run_Benchmark` : step 2 (`step_run_matrix.py`), step 3
      (`step_judge.py`), step 4 (`step_aggregate.py`), code env 3.x avec pandas.
- [ ] Variable projet `benchmark` reglee (section 5.3) : `agents` (REQUISE, avec le
      flag `modes` par agent), `golden_dataset`, `modes`, `language`, `concurrency`.
- [ ] Prerequis DSS verifies : footer trace cross-projet recu, footer reel fige en
      fixture, id du LLM juge confirme.
- [ ] Smoke run OK (1-2 questions, eco, concurrence 1) : `generated_sql_json` et les
      lignes de resultat sont captures, pas juste le texte.
- [ ] Run complet OK : `benchmark_summary` lit accuracy / latence p50-p95 / cout /
      error_rate par agent x mode ; `needs_review` exploite ; `run_id` permet de
      comparer des runs.
- [ ] Dashboard recable sur summary + detail + breakdown.
- [ ] Tests repo verts : `python3 -m unittest discover -s benchmark/tests`.
