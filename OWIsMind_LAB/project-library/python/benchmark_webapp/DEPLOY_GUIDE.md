# Guide de deploiement pas a pas - Benchmark OWIsMind + modes Smart/Pro/Claude

Ce guide te prend par la main pour mettre en place, sur ton instance Dataiku DSS, TOUT ce qu'on
a change autour du benchmark ET du renommage des modes de reponse. Chaque etape explique QUOI
faire, POURQUOI, et COMMENT verifier. Tu ne codes rien : tu copies/colles des fichiers du repo
dans DSS, tu coches des permissions, tu remplis une variable.

Suis les parties DANS L'ORDRE (A -> B -> C -> D). A la fin, tout fonctionne.

---

## v2 (2026-06-30) : benchmarks nommes par agent + mode append - A LIRE D'ABORD

Le benchmark est passe en **mode append** : un benchmark est une campagne NOMMEE et unique attachee a
UN agent ; relancer ne rejoue que les questions PAS ENCORE faites et ACCUMULE dans le meme benchmark
(score global sur la derniere tentative de chaque question). Detail + modele : section "v2" du
`OWIsMind_LAB/README.md` et la spec `docs/superpowers/specs/2026-06-29-benchmark-v2-append-mode-design.md`.

Ce que ce guide implique EN PLUS, pour la v2 (le reste des parties A-D reste valable) :
- **Re-coller la librairie `benchmark/`** : fichier NEUF `registry.py` + fichiers changes
  `schemas.py`, `run_params.py`, `scoring.py`, `judge.py`, `agent_runner.py`, et les 3 corps de step
  `dss_steps/step_run_matrix.py` / `step_judge.py` / `step_aggregate.py`.
- **Re-coller `benchmark_webapp/`** : `views.py` + `dss.py` (registre dans la variable + lancement par
  benchmark + selecteurs benchmark).
- **Re-coller les panes** des 2 webapps : le launcher gagne un onglet **Benchmarks** (creer / ouvrir /
  lancer un benchmark, membership + evolution + "refaire au prochain") et l'onglet Golden gagne 2 champs
  `expected_sql` / `expected_tool` ; le results passe son selecteur de RUN en selecteur de BENCHMARK.
- **Variable `benchmark`** : ajouter `"benchmarks": {}` et `"run_request": null` (les deux vides ; le
  launcher les remplit, tu n'y touches pas a la main). Voir `local-variables.example.json`.
- **Colonnes neuves** : `benchmark_id` / `benchmark_name` / `attempt_no` (raw+scored), `expected_sql` /
  `expected_tool` (golden+raw+scored), `actual_tools` (scored). Elles se materialisent toutes seules au
  PROCHAIN run (les datasets manages font evoluer leur schema a l'ecriture). `benchmark_summary` /
  `benchmark_breakdown` deviennent **par benchmark** (plus par run) : un run frais les recree proprement.
- **Lancement** : il ne se fait PLUS globalement. On cree/ouvre un benchmark dans l'onglet Benchmarks du
  launcher et on clique "Run pending" (append) / "Re-run entire benchmark" (full). L'ancien bouton de
  lancement global a ete retire.

---

## 0. Vue d'ensemble : ce qu'on deploie

Trois blocs, qui doivent etre coherents entre eux :

1. **Les Code Agents** (orchestrateur + sous-agents) - PARTIE A. On a renomme les modes de
   reponse : avant le token interne etait `eco/medium/high`, maintenant c'est **`smart/pro/claude`**
   PARTOUT. Ce token circule entre la webapp, l'orchestrateur, les sous-agents et le benchmark,
   donc il faut redeployer tous ces morceaux ENSEMBLE (sinon le selecteur de mode n'a plus d'effet).
2. **Le plugin (webapp OWIsMind)** - PARTIE B. Capture des suggestions par les utilisateurs +
   le selecteur de mode renomme Smart/Pro/Claude.
3. **Les deux webapps du projet `OWIsMind_LAB`** - PARTIE C : `results/` (consultation publique,
   langage clair) et `launcher/` (configurer + lancer + promouvoir les suggestions).

Important sur les modes : Smart = Gemini 3.1 Flash-Lite (le defaut, rapide et economique),
Pro = Gemini 3.5 Flash, Claude = Sonnet. Les MODELES n'ont pas change ; seul le NOM du mode a
change (plus de "eco"). Le selecteur affiche deja Smart/Pro/Claude ; desormais c'est aussi ce que
le code envoie de bout en bout.

Tableau "quel fichier du repo va ou dans DSS" :

| Fichier du repo | Va dans DSS |
| --- | --- |
| `dataiku-agents/OWISMIND/OWISMIND_DEV/agents/OWISMIND_DEV_OWIsMind_orchestrator.py` | Code Agent "OWIsMind_orchestrator" (DEV, env 3.11) |
| `..._SalesDrive_revenue_expert.py` | Code Agent "SalesDrive_revenue_expert" (DEV, env 3.11) |
| `..._CSSO_Trouble_Tickets_Expert.py` | Code Agent "CSSO_Trouble_Tickets_Expert" (DEV, env 3.11) si deploye |
| `Plugin/ready-for-dataiku/owismind_dev-upload.zip` | Plugin DSS `owismind_dev` |
| `OWIsMind_LAB/project-library/python/benchmark/` (dont `config.py`, `run_params.py`) | Librairie du projet `OWIsMind_LAB` (`python/benchmark/`) |
| `OWIsMind_LAB/project-library/python/benchmark_webapp/views.py` + `dss.py` + `__init__.py` | Librairie du projet `OWIsMind_LAB` (`python/benchmark_webapp/`) |
| `OWIsMind_LAB/webapps/benchmark_results/{body.html,style.css,script.js,backend.py}` | Webapp standard "Benchmark - Results" |
| `OWIsMind_LAB/webapps/benchmark_launcher/{body.html,style.css,script.js,backend.py}` | Webapp standard "Benchmark - Launcher" |
| `OWIsMind_LAB/webapps/*/preview.html` | NE PAS coller dans DSS (previsualisation locale seulement) |

---

## 1. Prerequis

Le moteur du benchmark (datasets, scenario, variable) doit deja exister dans `OWIsMind_LAB`. Si
ce n'est pas le cas, fais d'abord **`benchmark/SETUP_GUIDE.md`** (etapes 1 a 3), qui cree les 5
datasets (`golden_questions_v1_prepared`, `benchmark_runs_raw`, `_scored`, `benchmark_summary`,
`benchmark_breakdown`), le scenario `Run_Benchmark` et la variable de projet `benchmark`.

Droits : etre administrateur (ou avoir l'ecriture) sur `OWIsMind_LAB`, acces a la connexion SQL
`SQL_owi`, et droit de modifier les Code Agents (DEV).

---

## 2. PARTIE A - Re-coller les Code Agents (renommage des modes Smart/Pro/Claude)

POURQUOI : le selecteur de mode (Smart/Pro/Claude) envoie un petit token a l'orchestrateur, qui
le lit pour choisir le modele et le transmet au sous-agent. On a renomme ce token de `eco/medium/
high` vers `smart/pro/claude`. Si tu deploies la webapp (qui envoie `smart`) sans recoller les
agents (qui attendent encore `eco`), le mode est ignore et l'agent retombe sur son modele par
defaut. Donc on recolle les agents EN MEME TEMPS que le plugin (Partie B).

Ce qui a change dans les agents (tu n'as qu'a coller, c'est deja fait dans le repo) :
`ORCH_MODES`, `DEFAULT_MODE`, `LOOP_LLM_BY_MODE`, `narration_enabled` (orchestrateur), et
`LLM_BY_MODE`, `_MODE_RE`, `pick_subagent_llm`, `SEMANTIC_TOOL_ID_BY_MODE` (sous-agents) parlent
maintenant `smart/pro/claude`. Les MODELES sont identiques.

### A1. Re-coller l'orchestrateur (DEV)
1. Ouvre le fichier repo
   `dataiku-agents/OWISMIND/OWISMIND_DEV/agents/OWISMIND_DEV_OWIsMind_orchestrator.py`.
2. Dans DSS, projet `OWISMIND_DEV` -> le Code Agent **OWIsMind_orchestrator** (id `038G7mlF`,
   code env **3.11**) -> remplace tout son code par le contenu du fichier repo -> Save.

### A2. Re-coller le sous-agent revenus (DEV)
Pareil avec `OWISMIND_DEV_SalesDrive_revenue_expert.py` -> Code Agent **SalesDrive_revenue_expert**
(id `bHrWLyOL`, env 3.11).

### A3. Re-coller le sous-agent tickets (DEV), s'il est deploye
Si le Code Agent **CSSO_Trouble_Tickets_Expert** (id `NcE9LD2i`) existe deja dans `OWISMIND_DEV`,
recolle aussi `OWISMIND_DEV_CSSO_Trouble_Tickets_Expert.py`. (S'il n'est pas encore deploye, ignore
cette etape.)

Pas de zip ni de redemarrage backend pour les agents : un Code Agent prend effet des qu'il est
sauvegarde. (PROD : les fichiers `OWISMIND_PROD_V1_*` du repo sont deja a jour ; on promeut en PROD
plus tard, une fois le DEV valide.)

Verification : ouvre une conversation dans la webapp (apres la Partie B), ouvre le selecteur de
mode, choisis Claude sur une vraie question complexe ; la reponse doit etre traitee par Sonnet
(plus lente, plus posee). En Smart (defaut), c'est rapide.

---

## 3. PARTIE B - Le plugin (capture des suggestions + selecteur de mode)

### B1. Recuperer le zip DEV
`Plugin/ready-for-dataiku/owismind_dev-upload.zip` (deja construit dans le repo). C'est le plugin
**DEV** (id `owismind_dev`), qui s'installe a cote de la prod sans l'ecraser.

### B2. Uploader le plugin
1. Menu DSS -> **Plugins** -> **Add plugin** -> **Upload** -> choisis `owismind_dev-upload.zip`,
   installe-le comme plugin **Uploaded** (PAS "Development").
2. Si une version `owismind_dev` existe deja en "Development", supprime-la d'abord puis re-uploade.
3. Si DSS demande un code env pour le plugin, prends celui de la prod (meme version Python). On
   n'installe jamais de dependance ; si un paquet manque, c'est a toi de l'ajouter cote DSS.

### B3. Redemarrer le backend de la webapp
Le backend Python a change (nouvelles routes de suggestion + le defaut de mode passe a `smart`).
Va sur la webapp OWIsMind (DEV) -> **Stop** puis **Start** (ou "Restart backend"). Sans ca, les
nouvelles routes `/owismind-api/benchmark/*` n'existent pas et le mode reste sur l'ancien defaut.

### B4. Smoke-test
1. Sous une reponse d'agent, le menu **"..."** -> **"Suggerer pour le benchmark"** -> ouvre la
   page **Benchmark** prereremplie (question + reponse de l'agent + Oui/Non).
2. Le menu lateral **"Benchmark"** ouvre la meme page (suggestion manuelle + "Mes suggestions").
3. Le selecteur de mode affiche Smart (recommande) / Pro / Claude.

### B5. La table se cree toute seule
La table SQL des suggestions est creee a la 1ere suggestion envoyee. Fais-en au moins une.

### B6. Noter le nom physique exact de la table (pour la Partie C)
Webapp OWIsMind (DEV) -> **Administration** -> onglet **Storage** -> ligne **`golden_suggestions`**.
Copie la valeur (ex. `OWISMIND_DEV_owismind_webapp_golden_suggestions_v1`). Garde-la pour C6.

---

## 4. PARTIE C - Les deux webapps dans `OWIsMind_LAB`

### C1. Re-coller la librairie partagee
1. `OWIsMind_LAB` -> menu **"</> "** (Code) -> **Libraries**, partie **python/**.
2. Le package `benchmark/` doit etre present et A JOUR. Recolle ce qui a change :
   - `config.py` + `run_params.py` (renommage des modes + le nouveau cap `history_keep_runs`) ;
   - **`history.py`** (NOUVEAU) + **`dss_steps/history_io.py`** (NOUVEAU) : la brique qui fait que les
     runs s'ACCUMULENT au lieu de s'ecraser (voir le bloc Historique plus bas) ;
   - les **3 corps de step** `dss_steps/step_run_matrix.py` / `step_judge.py` / `step_aggregate.py`
     (ils appellent maintenant l'append au lieu de l'overwrite) -> re-colle-les aussi dans les steps
     du scenario `Run_Benchmark`.
3. Cree `python/benchmark_webapp/` et place-y `__init__.py`, `views.py`, `dss.py` (depuis
   `OWIsMind_LAB/project-library/python/benchmark_webapp/`).
   (`views.py` + `dss.py` ont gagne la gestion des questions golden, voir C3.)

Verification (en local sur le repo, jamais sur l'instance), depuis la racine du repo :
`python3 -m unittest discover -s OWIsMind_LAB/project-library/python/benchmark_webapp/tests -t OWIsMind_LAB/project-library/python`
doit passer.

### C2. Creer la webapp "Benchmark - Results"
1. `OWIsMind_LAB` -> **"</> "** (Code) -> **Webapps** -> **+ New webapp** -> **Code webapp** ->
   **Standard**.
2. Nomme-la **"Benchmark - Results"** ; active le backend Python (Settings de la webapp).
3. Colle, depuis `OWIsMind_LAB/webapps/benchmark_results/` : `body.html` -> onglet **HTML**,
   `style.css` -> **CSS**, `script.js` -> **JS**, `backend.py` -> **Python**. Save, puis ouvre (View).

Ce que tu vois : "How well do the OWIsMind agents answer?", un score de confiance (donut), des
chiffres cles, par configuration / par sujet / par question. En haut a droite : toggle **theme** et
**langue EN/FR** (anglais par defaut). Sans run encore : "Aucun run disponible" (normal).

### C3. Creer la webapp "Benchmark - Launcher"
Recommence C2 mais nomme-la **"Benchmark - Launcher"** et colle les 4 panes depuis
`OWIsMind_LAB/webapps/benchmark_launcher/` : `body.html` -> **HTML**, `style.css` -> **CSS**,
`script.js` -> **JS**, `backend.py` -> **Python**. Tu vois un formulaire de Configuration, un bouton
Lancer, une carte **Questions** (gerer le golden : ajouter / modifier / activer-desactiver / supprimer
une question avec sa reponse attendue) et une section Suggestions.

> **Carte Questions (gestion du golden).** C'est la pour editer directement le jeu de questions de
> reference sans passer par un dataset : un formulaire (question, reponse attendue, valeur attendue +
> type, categorie, langue, active) ecrit dans le dataset golden via l'API Dataset (jamais de SQL brut).
> Desactiver une question (decocher "Active") la retire des prochains runs sans la perdre ; la supprimer
> l'enleve du golden mais laisse intacts les resultats des runs passes. Les permissions C4 (ecriture
> projet LAB) suffisent ; aucune permission supplementaire.

### C4. Permissions
- **Results** : lecture sur les datasets de resultats (automatique, meme projet). Rien d'autre.
- **Launcher** : ecriture sur le projet `OWIsMind_LAB` (enregistrer la config + lancer le scenario)
  + lecture sur la connexion `SQL_owi` (lire les suggestions) + acces a l'agent teste si tu relances.

### C5. Creer le dataset de log des promotions
Cree un dataset manage VIDE nomme **`benchmark_suggestions_promoted`** (sans schema ; il se remplit
a la 1ere promotion). Note : ce n'est qu'un journal d'audit ; la source de verite de "deja promu",
c'est le golden lui-meme (une suggestion promue y apparait sous un `question_id` en `u_...`).

### C6. Configurer le bloc `suggestions` dans la variable `benchmark`
`OWIsMind_LAB` -> menu projet -> **Variables** -> **Local variables**. Dans l'objet `benchmark`,
ajoute (sans toucher au reste) :

```json
"suggestions": {
  "connection": "SQL_owi",
  "table": "OWISMIND_DEV_owismind_webapp_golden_suggestions_v1",
  "promoted_dataset": "benchmark_suggestions_promoted"
}
```

`table` = le nom physique EXACT note en B6 (adapte-le a ton instance). Sans ce bloc, l'onglet
Suggestions affiche "Source des suggestions non configuree" (aucune erreur).

### C7. Deux reglages de securite / donnees a ne PAS oublier
- **`golden_dataset` doit etre un dataset manage AUTONOME** (sans recette en amont). La promotion ET
  la carte Questions ecrivent dedans ; si c'etait la sortie d'une recette, un rebuild effacerait les
  questions ajoutees/modifiees.
- **Active "Prevent concurrent executions"** sur le scenario `Run_Benchmark` (Scenario -> Settings) :
  le garde-fou autoritaire contre un double lancement.

### C8. Historique des runs (ils s'accumulent maintenant)
Depuis cette version, chaque run **s'ajoute** aux datasets de resultats au lieu d'ecraser le precedent
(chaque ligne porte deja son `run_id` / `run_timestamp`). Tu n'as RIEN a configurer pour ca : c'est le
comportement par defaut une fois les 3 steps + les 2 nouveaux fichiers recolles (C1). Concretement, le
selecteur de run de **Results** liste desormais tous les runs passes et tu peux les comparer.
- **Re-lancer un meme run est idempotent** : re-jouer Judge/Aggregate sur un `run_id` deja present
  remplace ses lignes au lieu de les dupliquer (les autres runs sont preserves).
- **Borne par defaut (securite instance)** : les 2 tables LOURDES (`benchmark_runs_raw` et
  `benchmark_runs_scored`, qui portent les reponses completes + SQL) ne gardent que les **50 runs
  les plus recents** par defaut (`history_keep_runs: 50`). Les tables LEGERES (`benchmark_summary`
  et `benchmark_breakdown`, une mini-ligne par run x agent x mode) gardent **TOUS** les runs : c'est
  elles que lit le selecteur de run de Results, donc l'historique complet reste consultable.
  - Pour changer la borne : `"history_keep_runs": 100` (par ex.) dans la variable `benchmark` ;
    `"history_keep_runs": 0` = ne rien borner (garder tout, meme les tables lourdes).

---

## 5. PARTIE D - Tester de bout en bout

### D1. Lire un resultat (Results)
Ouvre **Results** : le dernier run en langage clair. Teste le selecteur de run, le bouton **FR**
(la page passe en francais, les nombres aussi : "88,7 %"), et le **theme**.

### D2. Configurer et lancer (Launcher)
1. Ouvre **Launcher** (formulaire pre-rempli). Ajuste modes/categories/concurrence/agents.
2. **Enregistrer la configuration** (ecrit la variable, en preservant datasets/juge/suggestions).
3. **Lancer le benchmark** -> statut "En cours..." puis "Termine" -> retourne sur **Results** et
   recharge : le nouveau run apparait.

Astuce premier test : restreins a une categorie + mode Smart seulement (rapide, peu couteux).

### D3. Promouvoir une suggestion (boucle collaborative)
1. Un utilisateur suggere une question depuis la webapp OWIsMind (B4).
2. Dans **Launcher** -> section **Suggestions** -> elle apparait.
3. Coche-la, **Promouvoir la selection** -> ajoutee au golden (et disparait de la liste).

Verifie : ouvre `golden_questions_v1_prepared` ; la question promue y est, `question_id` en `u_...`.

### D4. Gerer les questions (carte Questions du Launcher)
1. Dans **Launcher** -> carte **Questions** -> **Ajouter une question** : remplis le formulaire
   (question + reponse attendue obligatoires ; valeur attendue + type optionnels pour l'ancre du juge ;
   categorie, langue, active) -> **Enregistrer**. Elle apparait dans la liste (id en `a_...`).
2. **Modifier** une ligne -> change la reponse attendue -> Enregistrer.
3. **Decocher "Active"** sur une question -> elle reste listee mais ne sera plus testee au prochain run.
4. **Supprimer** -> confirmation -> elle quitte le golden (les resultats des runs passes la gardent).

Verifie : `golden_questions_v1_prepared` reflete tes ajouts/modifs ; et apres un nouveau run, **Results**
montre PLUSIEURS runs dans le selecteur (l'historique s'accumule, cf. C8).

---

## 6. Depannage (cas frequents)

- **Le selecteur de mode "n'a aucun effet" / Claude se comporte comme Smart** : tu as deploye le
  plugin sans recoller les agents (Partie A), ou l'inverse. Recolle les Code Agents ET re-uploade le
  plugin + redemarre le backend, ensemble.
- **La webapp LAB s'ouvre blanche / erreur backend** : la librairie `python/benchmark_webapp/` (ou
  `python/benchmark/`) n'est pas recollee. Recolle C1 + recharge le backend de la webapp.
- **Onglet Suggestions : "non configuree"** : bloc `benchmark.suggestions` manquant ou `table` faux
  (B6 + C6).
- **Suggestions : aucune ligne** : nom de table faux, ou pas de droit de lire `SQL_owi` (C4 + C6).
- **Le bouton Lancer echoue** : pas le droit de lancer le scenario, ou methode dataikuapi differente
  selon la version DSS (le code degrade proprement). Lance alors `Run_Benchmark` depuis l'interface
  des scenarios DSS.
- **Results : page vide / "get_dataframe" en erreur** : aucun run passe (lance-en un, D2).
- **Le menu "..." n'a pas "Suggerer pour le benchmark"** : backend du plugin pas redemarre (B3), ou
  reponse en cours / sans texte.
- **Carte Questions : "Impossible d'enregistrer/supprimer la question"** : l'identite de la webapp n'a
  pas le droit d'ecrire sur le projet LAB (C4), ou le `golden_dataset` n'est pas un dataset manage
  autonome (C7). Une erreur de lecture transitoire fait echouer proprement (500) sans toucher au golden.
- **Results ne montre qu'UN run** alors que tu en as lance plusieurs : les 3 steps + les 2 fichiers
  d'historique ne sont pas recolles (C1), donc les steps ecrasent encore. Re-colle-les.

---

## 7. Rappels de securite (pourquoi c'est sur)

- **SQL = lecture + append uniquement.** Sur la connexion partagee, le code ne fait que des SELECT
  (lecture seule, bornee, timeout) ; les seules ecritures sont des ajouts a des datasets Flow (le
  golden, le journal des promus) via l'API Dataset, jamais de UPDATE/DELETE/DROP/INSERT brut. Tout
  cet acces est concentre dans `benchmark_webapp/dss.py`.
- **Results n'a aucune capacite d'ecriture** (aucune route d'ecriture).
- **La promotion ET la gestion des questions ne peuvent pas ecraser le golden par accident** :
  lecture qui LEVE en cas d'echec (abort propre, jamais d'ecriture tronquee), meme verrou que la
  promotion (pas de perte d'update concurrent), edition qui preserve les colonnes existantes.
- **L'historique ne peut pas etre tronque par un blip** : les steps lisent l'existant avec une lecture
  qui leve (gardee par le schema) ; une erreur de lecture sur un dataset deja construit fait echouer le
  step au lieu d'ecraser l'historique avec le seul run courant.
- **Le lancement est single-flight** (verrou interne + "Prevent concurrent executions" cote scenario).

---

## 8. Plus tard (hors de ce guide)

- Promotion en PROD : recoller les `OWISMIND_PROD_V1_*` (agents) une fois le DEV valide, refaire la
  Partie B avec le zip de prod (`/build-plugin` + `/package-plugin`), pointer le benchmark sur
  l'orchestrateur PROD.
- Synchroniser le statut "acceptee/refusee" vers la table du plugin (l'utilisateur voit "en attente").
- Garde-fou programmatique anti-recette sur `golden_dataset`.

Reference technique courte (mapping fichiers, permissions, caveats) : `benchmark_webapp/README.md`.
Reference du moteur benchmark : `benchmark/SETUP_GUIDE.md`. Carte des ids d'agents :
`dataiku-agents/OWISMIND/README.md`.
