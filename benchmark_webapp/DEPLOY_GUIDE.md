# Guide de deploiement pas a pas - Benchmark OWIsMind (integration dans le systeme)

Ce guide te prend par la main pour mettre en place, sur ton instance Dataiku DSS, tout ce qu'on
a construit autour du benchmark. Il est volontairement detaille : chaque etape explique QUOI
faire, POURQUOI, et COMMENT verifier que ca marche.

Tu n'as RIEN a coder. Tu copies/colles des fichiers du repo dans DSS, tu coches des permissions,
et tu remplis une variable. Le code est la source de verite dans le repo (comme pour les agents).

---

## 0. Vue d'ensemble : ce qu'on deploie et pourquoi

Le benchmark mesure, en grandeur reelle, si les agents OWIsMind repondent bien (taux de bonnes
reponses, vitesse, cout). On l'integre au systeme via **deux poles** qui vivent a deux endroits :

- **Pole utilisateur (dans la webapp OWIsMind = le plugin)** : n'importe quel utilisateur peut
  **suggerer une question de test avec la bonne reponse**, soit depuis une reponse de chat (menu
  "..." sous la reponse), soit depuis une page dediee. Ces suggestions alimentent le golden
  (le jeu de questions/reponses de reference) au fil du temps.

- **Pole admin (dans le projet `OWIsMind_LAB` = DEUX petites webapps DSS standard)** :
  - **Results** : page **publique, lecture seule**, qui affiche le resultat du benchmark en
    langage clair (pour inspirer confiance, comprehensible par tout le monde).
  - **Launcher** : outil interne pour **configurer + lancer** un benchmark (vrai formulaire,
    pas de JSON a editer) et **relire + promouvoir** les questions suggerees par les utilisateurs
    dans le golden.

Pourquoi deux webapps separees plutot qu'une ? Pour que la page de lancement ne soit pas
accessible aux gens qui consultent juste les resultats : on partage l'URL de Results a tout le
monde, et on garde l'URL de Launcher pour ceux qui pilotent le benchmark.

Tableau de ce qui se trouve ou :

| Fichier du repo | Va dans DSS |
| --- | --- |
| Le zip `Plugin/ready-for-dataiku/owismind_dev-upload.zip` | Plugin DSS (capture des suggestions) |
| `benchmark_webapp/views.py` + `dss.py` + `__init__.py` | Librairie du projet `OWIsMind_LAB` (sous `python/benchmark_webapp/`) |
| `benchmark_webapp/results/{body.html, style.css, script.js, backend.py}` | Webapp standard "Benchmark - Results" |
| `benchmark_webapp/launcher/{body.html, style.css, script.js, backend.py}` | Webapp standard "Benchmark - Launcher" |
| `benchmark_webapp/*/preview.html` | NE PAS coller dans DSS (sert juste a la previsualisation locale) |

---

## 1. Prerequis (a faire AVANT ce guide)

Le moteur du benchmark (datasets, scenario, variable) doit deja exister dans `OWIsMind_LAB`.
Si ce n'est pas encore fait, suis d'abord **`benchmark/SETUP_GUIDE.md`** (etapes 1 a 3), qui met
en place :

- les datasets manages : `golden_questions_v1_prepared`, `benchmark_runs_raw`,
  `benchmark_runs_scored`, `benchmark_summary`, `benchmark_breakdown` ;
- la librairie partagee `benchmark/` (recollee sous `python/benchmark/`) ;
- le scenario `Run_Benchmark` (3 steps Python) ;
- la variable de projet `benchmark` (Local variables).

Verification rapide que le prerequis est bon : dans `OWIsMind_LAB`, ouvre `benchmark_summary` ;
s'il contient au moins une ligne (un run deja passe), le moteur tourne. Sinon, lance d'abord un
run via le scenario (ou via le Launcher une fois ce guide termine).

Droits : tu dois etre administrateur (ou avoir les droits d'ecriture) sur `OWIsMind_LAB`, et avoir
acces a la connexion SQL `SQL_owi`.

---

## 2. PARTIE A - Le plugin (capture des suggestions par les utilisateurs)

C'est la partie "produit" : on met a jour la webapp OWIsMind (le plugin) pour ajouter la page de
suggestion et le bouton dans le menu "...".

### A1. Recuperer le zip DEV
Le zip est deja construit dans le repo :

    Plugin/ready-for-dataiku/owismind_dev-upload.zip

C'est le plugin **DEV** (id `owismind_dev`), qui s'installe A COTE du plugin de prod sans
l'ecraser. On deploie toujours en DEV d'abord, on valide, puis on promeut en prod.

### A2. Uploader le plugin dans DSS
1. Menu DSS (en haut a gauche) -> **Plugins** -> onglet **Installed** (ou **Store**) ->
   **Add plugin** -> **Upload**.
2. Choisis le fichier `owismind_dev-upload.zip`. Installe-le comme plugin **Uploaded**
   (PAS "Development").
3. Si une version `owismind_dev` existe deja en "Development", supprime-la d'abord (un plugin
   Development ne se met pas a jour par simple re-upload : il faut le supprimer puis re-uploader).
4. A l'installation, DSS peut demander de construire/choisir un code environnement pour le plugin :
   prends celui que la prod utilise deja (meme version Python). On n'installe jamais de dependance
   ici ; si DSS reclame un paquet manquant, c'est a toi de l'ajouter au code env (cote DSS).

### A3. Redemarrer le backend de la webapp
Le backend Python a change (nouvelles routes de suggestion). Apres l'upload :
- Va sur la webapp OWIsMind du plugin DEV (Administration de la webapp ou la liste des webapps).
- **Stop puis Start** (ou "Restart backend") du backend de la webapp.

Pourquoi : le backend ne recharge pas le code Python a chaud ; sans redemarrage, les nouvelles
routes `/owismind-api/benchmark/*` n'existent pas encore.

### A4. Smoke-test cote utilisateur
Ouvre la webapp OWIsMind (DEV) et verifie :
1. **Depuis une conversation** : pose une question, attends la reponse de l'agent. Sous la
   reponse, clique le menu **"..."** -> tu dois voir **"Suggerer pour le benchmark"**. Clique :
   ca ouvre la page **Benchmark** prereremplie (la question, la reponse de l'agent, et un choix
   **Oui / Non** "la reponse de l'agent est-elle correcte ?"). Si Non, tu donnes la bonne reponse.
   Envoie : un message de remerciement s'affiche.
2. **Page grand public** : dans le menu lateral, l'entree **"Benchmark"** ouvre la meme page. Sans
   pre-remplissage, tu peux proposer une nouvelle question de zero (question + bonne reponse +
   eventuellement une valeur clef a verifier + categorie).
3. **Mes suggestions** : en bas de la page, la liste de tes propres suggestions avec leur statut
   ("en attente" tant qu'un admin ne les a pas promues).

### A5. La table se cree toute seule
La table SQL des suggestions (`webapp_golden_suggestions_v1`) est creee automatiquement a la
PREMIERE suggestion envoyee. Tu n'as rien a creer a la main. (Fais donc au moins une suggestion
en A4 pour qu'elle existe avant la Partie B.)

### A6. Noter le nom physique exact de la table (necessaire pour la Partie B)
Le Launcher (Partie B) lit cette table cross-projet, et il a besoin de son nom physique EXACT.
Pour l'obtenir : webapp OWIsMind (DEV) -> **Administration** -> onglet **Storage** -> dans la
liste des tables, repere la ligne **`golden_suggestions`** et copie sa valeur. Elle ressemble a :

    OWISMIND_DEV_owismind_webapp_golden_suggestions_v1

(le prefixe `OWISMIND_DEV` peut differer selon ton projet/prefixe ; copie ce que TON instance
affiche). Garde cette chaine sous la main pour l'etape B6.

---

## 3. PARTIE B - Les deux webapps dans `OWIsMind_LAB`

### B1. Recoller la librairie partagee (`views.py` + `dss.py`)
Les deux webapps partagent deux modules Python qui doivent vivre dans la **librairie du projet**
(comme le package `benchmark/`).

1. Dans `OWIsMind_LAB`, ouvre l'editeur de librairie du projet : menu **"</> "** (Code) ->
   **Libraries** (ou "Library"), partie **python/**.
2. Cree le dossier `python/benchmark_webapp/` et place-y, depuis le repo, les fichiers :
   - `benchmark_webapp/__init__.py`
   - `benchmark_webapp/views.py`
   - `benchmark_webapp/dss.py`
   (Tu peux copier/coller le contenu de chaque fichier dans un nouveau fichier du meme nom.)
3. Le package `benchmark/` doit deja etre la (prerequis). `views.py` importe `benchmark.run_params`
   et `benchmark.schemas` ; `dss.py` importe aussi `benchmark`. Si `benchmark/` est present, c'est bon.

Pourquoi une librairie et pas le code de la webapp : `views.py` est PUR (teste hors DSS) et `dss.py`
centralise tout l'acces dataiku/SQL en UN seul endroit (plus facile a auditer). Les deux webapps
les importent.

Verification (optionnel, en local sur le repo, jamais sur l'instance) :
`python3 -m unittest discover -s benchmark_webapp/tests` doit passer (30 tests verts).

### B2. Creer la webapp "Benchmark - Results" (publique, lecture seule)
1. Dans `OWIsMind_LAB` : menu **"</> "** (Code) -> **Webapps** -> **+ New webapp** ->
   **Code webapp** -> **Standard** (HTML / CSS / JS, avec backend Python).
2. Nomme-la **"Benchmark - Results"**.
3. Active le **backend Python** de la webapp (dans Settings de la webapp, si ce n'est pas deja le cas).
4. Colle, depuis `benchmark_webapp/results/`, chaque fichier dans son onglet :
   - `body.html` -> onglet **HTML**
   - `style.css` -> onglet **CSS**
   - `script.js` -> onglet **JS**
   - `backend.py` -> onglet **Python** (le backend)
5. **Save**, puis ouvre la webapp (View).

Ce que tu dois voir : un titre "How well do the OWIsMind agents answer?", un grand pourcentage de
confiance (donut), des chiffres cles, une comparaison par configuration, le detail par question.
En haut a droite, deux boutons : **theme clair/sombre** et **langue EN/FR** (anglais par defaut).
Si aucun run n'existe encore, la page affichera "Aucun run disponible" : c'est normal, lance un
run via le Launcher (B3 + Partie C).

### B3. Creer la webapp "Benchmark - Launcher" (config + lancement + suggestions)
Recommence exactement B2, mais :
- Nomme-la **"Benchmark - Launcher"**.
- Colle les 4 panes depuis `benchmark_webapp/launcher/` (et non `results/`).

Ce que tu dois voir : un formulaire de **Configuration** (agents, modes, questions a tester,
concurrence, langue, plus un bloc "Reglages preserves" en lecture seule), un bouton **Lancer**,
et une section **Suggestions des utilisateurs**.

### B4. Permissions (important)
Une webapp standard s'execute avec TON identite (l'utilisateur qui l'ouvre, ou l'identite
configuree). Verifie que cette identite a :
- **Results** : lecture sur les datasets de resultats (automatique, meme projet). Rien de plus.
- **Launcher** :
  - **ecriture sur le projet `OWIsMind_LAB`** (pour enregistrer la config dans la variable et
    lancer le scenario) ;
  - **lecture sur la connexion `SQL_owi`** (pour lire les suggestions des utilisateurs, qui vivent
    dans une table du projet de la webapp OWIsMind, sur cette meme connexion) ;
  - acces a l'agent teste (ex. l'orchestrateur DEV `agent:038G7mlF` dans `OWISMIND_DEV`) si tu
    relances un run depuis le Launcher.

### B5. Creer le dataset de log des promotions
Le Launcher tient un petit journal des suggestions deja promues (pour ne pas les re-proposer).
1. Dans `OWIsMind_LAB`, cree un **dataset manage vide** nomme **`benchmark_suggestions_promoted`**
   (laisse-le sans schema : il se remplira a la premiere promotion, une seule colonne
   `suggestion_id`).

Note : ce journal est seulement un "filet" d'audit. La source de verite de "deja promu", c'est le
golden lui-meme (une suggestion promue y apparait sous un `question_id` qui commence par `u_`). Donc
meme si ce journal est vide ou en retard, rien n'est casse.

### B6. Configurer le bloc `suggestions` dans la variable `benchmark`
Pour que le Launcher sache OU lire les suggestions, ajoute un bloc a la variable de projet.
1. `OWIsMind_LAB` -> menu projet -> **Variables** -> **Local variables**.
2. Dans l'objet `benchmark` existant, ajoute la cle `"suggestions"` (sans toucher au reste) :

```json
"suggestions": {
  "connection": "SQL_owi",
  "table": "OWISMIND_DEV_owismind_webapp_golden_suggestions_v1",
  "promoted_dataset": "benchmark_suggestions_promoted"
}
```

- `connection` : la connexion SQL ou vit la table des suggestions (la meme que la webapp OWIsMind,
  par defaut `SQL_owi`).
- `table` : le nom physique EXACT note en A6 (adapte-le a ton instance).
- `promoted_dataset` : le dataset cree en B5.

Si tu oublies ce bloc, le Launcher affichera simplement "Source des suggestions non configuree"
dans l'onglet Suggestions (aucune erreur). Une fois le bloc en place, recharge le Launcher.

### B7. Deux reglages de securite a ne PAS oublier
- **`golden_dataset` doit etre un dataset manage AUTONOME** (sans recette en amont). La promotion
  ecrit DANS ce dataset ; si c'etait la sortie d'une recette (ex. un `prepare`), un simple rebuild
  de la recette effacerait les questions promues. Verifie que `benchmark.golden_dataset` (par
  defaut `golden_questions_v1_prepared`) pointe sur le golden autonome que le benchmark LIT.
- **Active "Prevent concurrent executions"** sur le scenario `Run_Benchmark` (Scenario ->
  Settings). C'est le garde-fou autoritaire contre un double lancement (le Launcher a deja un
  verrou interne, mais il ne protege qu'un seul processus backend).

---

## 4. PARTIE C - Tester de bout en bout

### C1. Lire un resultat (Results)
Ouvre la webapp **Results**. Tu dois voir le dernier run en langage clair. Teste le selecteur de
run (en haut), le bouton **FR** (la page passe en francais, les nombres aussi : "88,7 %"), et le
bouton **theme**. Le filtre "A relire uniquement" en bas ne montre que les questions a re-verifier.

### C2. Configurer et lancer (Launcher)
1. Ouvre la webapp **Launcher**. Le formulaire est pre-rempli depuis la variable.
2. Ajuste si besoin : coche/decoche des modes, choisis les categories de questions (vide = toutes),
   ajoute/retire un agent, regle la concurrence (reste bas, 1 a 3, pour ne pas surcharger).
3. Clique **Enregistrer la configuration** (ca ecrit la variable `benchmark`, en preservant
   datasets/juge/suggestions).
4. Clique **Lancer le benchmark**. Le statut passe a "En cours...", puis "Termine". Quand c'est
   fini, retourne sur **Results** et recharge : le nouveau run apparait dans le selecteur.

Astuce : pour un premier test rapide, restreins a une categorie ou peu de questions, et lance en
mode Smart seulement (rapide et peu couteux).

### C3. Promouvoir une suggestion (la boucle collaborative)
1. Depuis la webapp OWIsMind (un utilisateur), suggere une question (Partie A4).
2. Dans le **Launcher**, section **Suggestions des utilisateurs**, la suggestion apparait.
3. Coche-la, clique **Promouvoir la selection** : elle est ajoutee au golden (et disparait de la
   liste). Au prochain run, cette question sera testee.

Verifie : ouvre le dataset `golden_questions_v1_prepared` ; la question promue y est, avec un
`question_id` commencant par `u_`.

---

## 5. Depannage (les cas frequents)

- **La webapp s'ouvre blanche / erreur backend au demarrage** : la librairie `python/benchmark_webapp/`
  n'a pas ete recollee (l'import `from benchmark_webapp import views, dss` echoue), ou le package
  `benchmark/` manque. Recolle B1, puis recharge le backend de la webapp.
- **Onglet Suggestions : "Source des suggestions non configuree"** : le bloc `benchmark.suggestions`
  manque dans la variable, ou le nom de `table` est faux. Re-verifie A6 + B6 (nom physique exact).
- **Suggestions : aucune ligne alors qu'il y en a** : le nom de table est faux, ou l'identite de la
  webapp n'a pas le droit de lire `SQL_owi`. Verifie B4 + B6.
- **Le bouton Lancer echoue** : l'identite n'a pas le droit de lancer le scenario, ou la methode
  d'API de lancement differe selon la version DSS (le code degrade proprement). Dans ce cas, lance
  `Run_Benchmark` directement depuis l'interface des scenarios DSS ; la lecture des resultats marche
  pareil.
- **Results : "get_dataframe" en erreur / page vide** : un dataset de resultat n'existe pas encore
  (aucun run passe). Lance un run d'abord (C2), ou suis `benchmark/SETUP_GUIDE.md`.
- **Le menu "..." ne montre pas "Suggerer pour le benchmark"** : tu n'as pas redemarre le backend du
  plugin (A3), ou tu testes sur une reponse encore en cours / sans texte (l'entree n'apparait que sur
  une reponse terminee avec du texte).

---

## 6. Rappels de securite (pourquoi c'est sur)

- **SQL = lecture + append uniquement.** Sur la connexion partagee, le code ne fait que des SELECT
  (lecture seule, bornee, avec timeout) ; les seules ecritures sont des ajouts a des datasets Flow
  (le golden, le journal des promus) via l'API Dataset, jamais de UPDATE/DELETE/DROP/INSERT brut.
  Tout cet acces est concentre dans `benchmark_webapp/dss.py`.
- **La page Results n'a aucune capacite d'ecriture** (aucune route d'ecriture cote backend).
- **La promotion ne peut pas ecraser le golden** : elle lit le golden avec une lecture qui LEVE en
  cas d'echec (donc elle s'interrompt proprement au lieu d'ecraser sur un incident), elle est
  serialisee par un verrou, et "deja promu" se deduit du golden lui-meme (pas d'un journal fragile).
- **Le lancement est single-flight** (verrou interne + "Prevent concurrent executions" cote scenario)
  pour ne jamais lancer deux fois la meme matrice et surcharger l'instance.

---

## 7. Plus tard (hors de ce guide)

- Promotion en PROD : refaire la Partie A avec le zip de prod (`/build-plugin` + `/package-plugin`)
  une fois le DEV valide, et pointer le benchmark sur l'orchestrateur PROD.
- Synchroniser le statut "acceptee/refusee" vers la table du plugin (aujourd'hui l'utilisateur voit
  "en attente" cote OWIsMind meme apres promotion).
- Garde-fou programmatique anti-recette sur `golden_dataset` (aujourd'hui c'est un prerequis
  documente, pas une verification automatique).

Reference technique courte (mapping fichiers, permissions, caveats) : `benchmark_webapp/README.md`.
Reference du moteur (datasets, scenario, variable) : `benchmark/SETUP_GUIDE.md`.
