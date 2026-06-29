# Benchmark - phase finale : juge contextuel, override humain, integration plugin

Date : 2026-06-29
Statut : design valide par l'utilisateur (go), pret pour le plan d'implementation.
Regle typographique : aucun tiret cadratin/demi-cadratin nulle part (regle #9).

## 1. Contexte et objectif

Le systeme de benchmark existe et tourne (capture complete depuis le footer trace,
matrice agent x mode, juge en deux etages, datasets `benchmark_runs_raw` -> `_scored`
-> `benchmark_summary` + `benchmark_breakdown`, 2 webapps LAB standard). Il vit dans un
projet DSS separe `OWIsMind_LAB`, miroir du repo `OWIsMind_LAB/`.

Objectif de cette phase : faire du benchmark une brique de premiere classe du produit,
applicable a N'IMPORTE QUEL agent Dataiku (visuel ou code), avec un juge plus juste, un
humain dans la boucle, et une integration directe dans la webapp plugin OWIsMind. Le MVP
le plus urgent : pouvoir ajouter un agent, discuter avec, et consulter son benchmark.

Cinq poles de travail (concus et livres en un seul lot coherent ; le MVP = poles A + C
consultation + cablage fiche d'agent reste deployable/testable en premier) :

- A. Juge plus strict mais contextuel + colonne commentaire.
- B. Humain dans la boucle : revoir et override le verdict du juge.
- C. Fiche d'agent : declarer qu'un agent a un benchmark + choisir la table + valider le schema.
- D. Onglet Benchmark dans le plugin : consultation des resultats pour TOUS les utilisateurs.
- E. Launcher (config + lancement + revue/override) embarque dans le plugin, ADMIN seulement.

Les 2 webapps LAB (`benchmark_launcher`, `benchmark_results`) restent en place et
fonctionnelles : on a donc trois surfaces qui coexistent (consultation plugin pour tous,
launcher plugin pour admin, + les 2 webapps LAB du projet).

## 2. Decisions actees (questions tranchees par l'utilisateur)

1. Juge = autorite contextuelle. Le juge LLM lit la note humaine + la valeur attendue comme
   contrat de severite et decide. L'ancre deterministe redevient un signal (un HIT confirme,
   un MISS ne force plus "faux"). + parsing des ordres de grandeur + tolerance assouplie +
   colonne commentaire.
2. Cablage : 1 table au schema `scored` par agent. Le plugin recalcule KPIs/resume/breakdown
   via `scoring.summarize` / `scoring.breakdown` (deja purs). Portable : toute table a ce
   schema se branche. La validation de schema verifie les colonnes `scored`.
3. Overrides : ecrits dans la table `scored` (colonnes `human_*`), lecture simple. Robuste
   au re-run car `scored` accumule l'historique par run_id (cf. section 5).
4. Livraison : un seul lot (design complet A->E), avec le MVP independamment shippable.

## 3. Architecture : ou vit quoi

### 3.1 Cote LAB (`OWIsMind_LAB/`, recolle en project-library + webapps)
- `project-library/python/benchmark/judge.py` : juge contextuel (pole A).
- `project-library/python/benchmark/schemas.py` : `notes` dans RAW, colonnes `human_*` +
  `judge_comment` dans SCORED ; helper pur `effective_row` (verdict effectif).
- `project-library/python/benchmark/scoring.py` : agregation tient compte du verdict effectif
  (override prime).
- `project-library/python/benchmark/dss_steps/step_run_matrix.py` : porte `notes` du golden
  vers RAW.
- `project-library/python/benchmark/dss_steps/step_judge.py` : passe `notes` au juge ;
  ecrit `judge_comment` + initialise les colonnes `human_*` vides.
- `project-library/python/benchmark_webapp/views.py` : surface `judge_comment` + verdict
  effectif + shaping de la revue ; helpers d'override (purs).
- `project-library/python/benchmark_webapp/dss.py` : write-back d'override (read-modify-write
  du dataset `scored`, verrou dedie).
- `webapps/benchmark_launcher/*` : onglet/section "Revue & override".

### 3.2 Cote plugin (`Plugin/owismind/`, packe dans le zip)
- `python-lib/owismind/benchmark_view/` : NOUVEAU package PUR, copie des modules stdlib du LAB
  (`scoring.py`, le shaping de `views.py`, les listes de colonnes de `schemas.py`, les
  normalizers de `judge.py` necessaires a la lecture) + un module `read.py` (lecture SQL
  cross-project bornee) + `agent_profile.py` (validation du bloc benchmark de la fiche d'agent).
- `python-lib/owismind/security/validation.py` : `validate_agent_meta` etendu (bloc `benchmark`).
- `python-lib/owismind/api/routes.py` : nouvelles routes (section 7).
- `frontend/src/views/BenchmarkSuggestView.vue` est restructure en conteneur de l'onglet Benchmark
  (consultation + sous-section suggest existante + launcher admin), renomme `BenchmarkView.vue` ;
  le routeur/sidebar pointent dessus.
- `frontend/src/views/AdminView.vue` : section Benchmark de l'editeur de profil d'agent.
- composants frontend : donut, verdict, KPIs, barres par categorie, table Q-par-Q, panneau de
  revue/override admin (charte Orange, regle #10).

### 3.3 Duplication PURE et point de sync
Les modules `scoring.py`, le shaping de `views.py` et les listes de colonnes de `schemas.py`
sont stdlib purs et stables. Ils sont DUPLIQUES dans `owismind/benchmark_view/` (le plugin ne
peut pas importer la project-library du LAB a l'execution : deploiements distincts). LAB reste
la source de verite ; chaque fichier copie porte un en-tete `# PORTED FROM OWIsMind_LAB/.../<f>.py
- keep in sync` + la liste exacte des fonctions copiees. Le fix du juge (`run_llm_judge`,
prompt, anchor) est LAB-only : le plugin ne juge JAMAIS, il ne fait que LIRE des verdicts.

## 4. Pole A - Juge plus strict mais contextuel

Fichiers : `benchmark/judge.py`, `benchmark/schemas.py`, `benchmark/config.py`,
`benchmark/dss_steps/step_run_matrix.py`, `benchmark/dss_steps/step_judge.py`.

### 4.1 Cause racine confirmee
`NUMERIC_TOLERANCE = 0.005` (0,5 %) et `normalize_number("36 millions")` qui IGNORE le mot
"millions" (parse 36, pas 36 000 000). L'ancre objective rate donc, et comme l'ancre PRIME
sur le juge dans `final_correctness`, la bonne reponse "36 456 876" est marquee fausse.

### 4.2 Parsing des ordres de grandeur (`normalize_number`)
Avant le nettoyage final, detecter un suffixe de magnitude (insensible accents/casse) et
multiplier :
- `k` / `K` -> 1e3
- `m` / `million` / `millions` / `mn` -> 1e6
- `md` / `mds` / `milliard` / `milliards` / `bn` / `b` (mot entier) -> 1e9

Regles : le multiplicateur s'applique au nombre parse devant le mot. Le mot doit etre un token
distinct ou un suffixe accole (`36m`, `36 millions`, `36M`). Ne PAS confondre avec une lettre
au milieu d'un identifiant. Fonction pure, ne leve jamais ; un texte sans magnitude se comporte
exactement comme aujourd'hui (non-regression). Tests dedies (section 10).

### 4.3 Ancre = signal, le juge tranche (`final_correctness`)
Nouvelle regle deterministe :
- Ancre HIT : confirme `correct = True` (le fait crisp est present). Si le juge dit "incorrect"
  -> `needs_review = True` (desaccord), mais `correct` reste True.
- Ancre MISS : NE force plus `correct = False`. On delegue au juge contextuel :
  `correct = (verdict == "correct" and score >= 4)`. Desaccord ancre-vs-juge ->
  `needs_review = True` (l'oeil humain reverra ces lignes en priorite).
- Ancre n/a : inchange (le juge decide, lacune de score -> needs_review).
- Erreur agent : inchange (jamais correct, toujours needs_review).

Consequence directe sur le cas cible : "36 millions" attendu, agent "36 456 876". Avec le
parsing de magnitude, l'ancre peut meme passer HIT (36.46M vs 36M = 1,27 % ; au-dela de la
tolerance 0,5 % donc MISS), puis le juge, voyant l'ordre de grandeur correct sans note
d'exactitude, repond "correct" -> `correct = True`, `needs_review = True` (desaccord ancre/juge,
sain). L'humain peut confirmer (pole B).

La tolerance de l'ancre reste serree (0,5 %) : l'ancre n'est plus qu'une confirmation bon
marche ; la nuance d'arrondi/contexte appartient au juge.

### 4.4 Note humaine comme contrat de severite (prompt du juge)
- `notes` (deja une colonne golden) est portee dans `RAW_COLUMNS` par `step_run_matrix`, puis
  passee a `run_llm_judge` / `build_judge_prompt`.
- Le prompt gagne une section "HUMAN NOTE (strictness contract)" : "When the human note demands
  an exact figure (mentions 'exact', 'precise', 'au centime', a precise count, etc.), require the
  exact value: a rounded or order-of-magnitude answer is INCORRECT. When there is no such demand,
  an answer that conveys the right magnitude / rounded value is CORRECT. Judge meaning and factual
  accuracy, never wording, language, or formatting."
- Le systeme reste strict et factuel ; la note module la severite sur l'exactitude numerique.

### 4.5 Commentaire concis du juge (`judge_comment`)
- `JUDGE_OUTPUT_SCHEMA` gagne `"comment": {"type": "string"}` (requis), le "tout petit
  commentaire" sur la DECISION (une phrase, pourquoi correct/incorrect). `justification` reste le
  champ plus long existant.
- `_coerce_judge_payload` borne `comment` a ~200 caracteres. `_safe_failure` renvoie `comment=""`.
- `SCORED_COLUMNS` gagne `judge_comment`. `step_judge` ecrit la valeur. Surface partout (LAB
  views + plugin views, colonne visible dans la table Q-par-Q).

## 5. Pole B - Override humain dans `scored`

### 5.1 Colonnes ajoutees a `SCORED_COLUMNS`
- `human_verdict` : "" / "correct" / "incorrect" (decision humaine, vide = pas de revue).
- `human_correct` : booleen nullable (miroir machine de `human_verdict`, None si pas de revue).
- `human_comment` : note libre du relecteur (bornee, ~500 car.).
- `reviewed_by` : user_id du relecteur.
- `reviewed_at` : timestamp ISO (passe en parametre depuis la couche DSS ; les modules purs ne
  generent jamais l'heure - regle scripts workflow).

`step_judge` initialise ces 5 colonnes vides/None sur chaque nouvelle ligne scored.

### 5.2 Verdict effectif (helper pur `effective_row`)
Dans `schemas.py` (LAB) et copie dans `benchmark_view` (plugin) :

    def effective_correct(row):
        """Final correctness once a human override is applied. Pure, never raises.
        human_verdict in {correct, incorrect} wins over the judge/anchor `correct`.
        """

Renvoie aussi un drapeau `overridden` (bool) et le `effective_verdict` ("correct"/"incorrect").
`scoring.summarize` / `scoring.breakdown` (LAB) et le shaping plugin utilisent le verdict
EFFECTIF (override prime) pour l'accuracy. Sans override, comportement identique a aujourd'hui.

### 5.3 Persistance robuste (write-back)
- `scored` ACCUMULE l'historique : `merge_run_history(existing, new)` garde les lignes des runs
  NON presents dans le nouveau batch et remplace celles du run courant. Donc un override pose sur
  une ligne de run X survit a chaque run futur (run Y != X) car ses lignes passent intactes dans
  le read-modify-write de `write_history_dataset`. Condition : les colonnes `human_*` font partie
  du schema `scored` (point 5.1), donc le `get_dataframe()` les relit et les reecrit.
- Ecriture d'un override : `benchmark_webapp/dss.py` lit le dataset `scored`, pose les 5 colonnes
  sur la ligne (run_id, question_id, agent_key, mode) ciblee, reecrit via `write_with_schema`,
  sous un VERROU dedie `OVERRIDE_LOCK` (serialise les ecritures concurrentes ; meme patron que
  `_PROMOTE_LOCK` / `RUN_LOCK`). Pas de SQL brut en ecriture (chokepoint append/rewrite-only).
- Reserve documentee : re-juger (re-scorer) le MEME run_id remplace ses lignes -> ses overrides
  sont perdus. Cas rare (on relance normalement un nouveau run). A signaler dans l'UI launcher.

### 5.4 UI de revue / override (launcher LAB + launcher admin plugin)
Liste, pour un run choisi, chaque ligne scored avec : question, reponse de reference, valeur
attendue + type, note humaine (le contrat de severite), categorie, agent + mode, reponse de
l'agent (apercu + detail depliable), verdict juge + score + `judge_comment`, ancre objective,
et le verdict effectif courant. Action : "marquer juste / faux" + zone de commentaire ->
POST d'override. Filtre "needs_review d'abord". Affichage du fait que la ligne a ete overridee
(par qui, quand).

## 6. Pole C - Fiche d'agent : declarer + cabler un benchmark

Fichiers : `security/validation.py`, `frontend/src/views/AdminView.vue`, routes API.

### 6.1 Bloc `benchmark` dans le profil d'agent
`validate_agent_meta` renvoie en plus `benchmark` :

    "benchmark": {
        "enabled": bool,            # defaut False
        "connection": str,          # nom de connexion SQL (defaut "SQL_owi"), borne
        "table": str,               # nom PHYSIQUE de table (identifiant valide ou "")
        "agent_key": str,           # filtre agent_key dans la table (optionnel ; "" = tout)
    }

Bornage/securite (jamais ne leve, clamp) :
- `connection` : chaine bornee, charset identifiant ; defaut "SQL_owi".
- `table` : passe par un validateur d'identifiant physique (regex `^[A-Za-z0-9_-]{1,200}$`,
  meme esprit que `views.safe_table_name`) ; toute autre forme -> "" (benchmark inactif).
- `agent_key` : chaine bornee, charset cle logique.
- Si `enabled` mais `table` vide/invalide -> le profil est conserve mais la consultation traite
  l'agent comme "benchmark non configure" (etat vide explicite).

Le bloc est stocke dans le JSON `enabled_agents` de `webapp_settings_v1` (pas de nouvelle table),
comme le reste du profil. `/agents` peut exposer un booleen leger `has_benchmark` (PAS la table
ni la connexion : pas de fuite d'infra cote front non-admin) ; le nom de table reste serveur-only
et n'est resolu qu'au moment de la lecture.

### 6.2 Routes admin pour le selecteur de table + validation de schema
- `GET /admin/benchmark/tables?connection=<name>` (admin-only) : liste les tables candidates de
  la connexion via `information_schema.tables` (SELECT borne, read-only, statement_timeout). Mirroir
  read-only du patron de `compute_available_connections.py` / `evidence/service.py`. Retourne
  `{tables: [..]}`. Degrade proprement (liste vide + message) si le listing est indisponible.
- `POST /admin/benchmark/validate-table` (admin-only) body `{connection, table}` : lit le schema
  de la table (information_schema.columns), compare aux colonnes `scored` REQUISES par la page de
  consultation, et renvoie `{ok, missing: [colnames], extra_ignored: [..]}`. Les colonnes
  REQUISES sont un sous-ensemble explicite de `SCORED_COLUMNS` (celles que le shaping consomme :
  run_id, run_timestamp, question_id, question, category, agent_key, agent_label, mode, status,
  reference_answer, answer_text, objective_match, judge_score, judge_verdict, judge_comment,
  correct, needs_review, latency_total_s, estimated_cost, human_verdict, human_correct,
  human_comment + celles utilisees par scoring.summarize/breakdown). Message en clair : "schema
  incompatible : colonnes manquantes : a, b, c".

Securite : connexion et table viennent d'un ADMIN, valides serveur (regex + presence reelle dans
le catalogue), stockes dans le profil. L'utilisateur final n'envoie jamais table/connexion. Pas de
route SQL generique : ces routes n'executent que des SELECT bornes sur `information_schema`, jamais
une requete fournie par le client.

### 6.3 UI editeur de profil (AdminView)
Section "Benchmark" dans la modale d'edition de profil d'agent : toggle "Cet agent a un
benchmark", select connexion (alimente par les connexions PostgreSQL), select table (alimente par
`/admin/benchmark/tables`), champ `agent_key` optionnel, bouton "Valider le schema" (appelle
`/admin/benchmark/validate-table` et affiche OK ou la liste des colonnes manquantes). Charte Orange.

## 7. Poles D + E - Onglet Benchmark dans le plugin

### 7.1 Vue par defaut : consultation pour TOUS (pole D)
- Premiere chose affichee dans l'onglet Benchmark : un DROPDOWN d'agent (les agents actives ayant
  `benchmark.enabled` et une table valide), puis la restitution : donut de confiance, hero verdict
  "X sur Y", KPIs (accuracy, nb questions, configs, cout, needs_review), barres par categorie,
  table Q-par-Q (avec `judge_comment` + verdict effectif), selecteur de run.
- Backend : `GET /benchmark/results?agent=<logical_key>&run_id=<optional>` (tout utilisateur
  authentifie). Resout la cle d'agent -> profil -> {connection, table, agent_key}. Lit la table
  `scored` en cross-project (SELECT borne : projection des colonnes utiles, cap lignes,
  statement_timeout + transaction_read_only), filtre `agent_key` si pose. Recalcule via le
  `scoring` porte (summarize/breakdown) + shaping (`views` porte), applique le verdict effectif.
  Renvoie le meme contrat que les vues LAB (reutilisation des composants).
- Etats : agent sans benchmark -> carte "pas de benchmark configure pour cet agent" ; table
  illisible -> message degrade (jamais de 500).

### 7.2 Launcher (pole E) - DECISION FINALE UTILISATEUR : AUCUN launch dans le plugin

Decision de l'utilisateur (2026-06-29, apres une premiere demo) : on garde le plugin SIMPLE -
**aucune interface de lancement dans la webapp owismind**. Le plugin n'integre QUE la
**consultation** ; tout le LANCEMENT (config + golden + suggestions + run) reste sur les webapps
LAB du projet `OWISMIND_LAB`. Pas de cross-project dataikuapi a configurer cote plugin.

- Le plugin reste fonctionnellement EN L'ETAT ("laisser tel quel") : consultation pour tous +
  l'override admin par question deja en place (pole B, via `lab_io.write_override`) + le formulaire
  de suggestion. On n'AJOUTE pas le launcher.
- La REVUE + OVERRIDE complete (avec config/golden/run) vit sur la webapp LAB `benchmark_launcher`
  (qui a recu sa propre UI de revue/override). C'est la surface admin de reference.
- Le seul travail restant cote plugin est du DESIGN : la consultation est restylee pour avoir
  exactement la meme disposition que la webapp LAB `benchmark_results` (hero donut + verdict, 5 KPIs,
  cartes par config avec barre + sous-metriques, lignes par sujet, table Q-par-Q + details, aside
  reference), avec les tokens semantiques du plugin (pas de hex en dur).

### 7.3 Le clic "suggerer pour le benchmark" depuis le chat
Conserve : l'action menu "..." ouvre l'onglet Benchmark sur la sous-section "suggerer une
question" prefillee (1 seule surface). Inchange par rapport a l'existant.

## 8. Securite et surete instance (synthese)

- Rule #3 preservee : aucune route SQL generique. L'utilisateur final n'envoie qu'une cle d'agent
  logique ; table/connexion sont resolues serveur depuis le profil pose par l'admin. Les SELECT
  cross-project sont bornes (liste de colonnes explicite, cap de lignes, statement_timeout 30s,
  transaction_read_only), le nom de table validee contre regex + presence reelle.
- Rule #4 preservee : whitelist agents serveur ; pas d'agent_id brut depuis le front.
- Admin-only : listing de tables, validation de schema, launcher (config/run/override/golden CRUD).
  Cloture impersonation : lecture seule en impersonation.
- Surete instance : lectures bornees et read-only ; le launcher single-flight ; pas de Flow au
  runtime cote plugin ; aucune ecriture SQL brute (overrides via Dataset API).

## 9. Contrats de donnees (recapitulatif des schemas)

- `GOLDEN_COLUMNS` : inchange (a deja `notes`).
- `RAW_COLUMNS` : + `notes`.
- `SCORED_COLUMNS` : + `judge_comment`, `human_verdict`, `human_correct`, `human_comment`,
  `reviewed_by`, `reviewed_at`.
- `JUDGE_OUTPUT_SCHEMA` : + `comment` (requis).
- Profil d'agent (`validate_agent_meta`) : + bloc `benchmark {enabled, connection, table, agent_key}`.
- `SUMMARY_COLUMNS` / `BREAKDOWN_COLUMNS` : inchanges (recalcules a partir du verdict effectif).

## 10. Tests (NO INSTALL : node:test + unittest stdlib)

LAB (`unittest`) :
- `normalize_number` magnitude : "36 millions" -> 36e6, "1,2 Md" -> 1.2e9, "500k" -> 5e5, non
  regression sur les nombres simples et les separateurs locaux.
- `objective_anchor` avec magnitude (HIT/MISS attendus).
- `final_correctness` ancre-signal : MISS + juge correct -> correct True + needs_review True ;
  HIT + juge incorrect -> correct True + needs_review True.
- `_coerce_judge_payload` : `comment` borne, defauts surs ; `build_judge_prompt` inclut la note.
- `effective_correct` : override correct/incorrect prime ; absence d'override = verdict machine.
- `scoring.summarize/breakdown` : accuracy calculee sur le verdict effectif.
- validation de schema (helper pur) : colonnes manquantes detectees et listees.
- `validate_agent_meta` : bloc benchmark borne/clamp (table invalide -> "", defauts).
- `validate_config` / `build_config_object` (porte) : inchange.

Plugin (`unittest` + `node:test`) :
- `benchmark_view.read` : construction du SELECT borne (colonnes, cap), resolution profil->table.
- shaping plugin = parite avec les vues LAB sur un jeu de lignes fixture.
- composants frontend (donut, verdict, table Q-par-Q, panneau override) : rendu + i18n + 0 tiret.

QA visuelle Playwright (comme les sessions precedentes) : onglet Benchmark consultation (EN/FR x
clair/sombre), editeur de profil (validation schema OK + colonnes manquantes), launcher admin
(run simule + override), 0 erreur console, 0 tiret.

## 11. Deploiement (a faire en DSS, ordre)

1. LAB : recoller `benchmark/{judge,schemas,scoring,config}.py` + les 3 corps de step
   (`step_run_matrix`, `step_judge`, `step_aggregate` si touche) + `benchmark_webapp/{views,dss}.py`
   + les panes du `benchmark_launcher` (section Revue & override). Relancer un run pour materialiser
   les nouvelles colonnes `scored`.
2. Plugin : `/build-plugin` + `/package-plugin-dev` (DEV d'abord, jamais la prod), upload DEV +
   redemarrer backend (python-lib change). Remplir le bloc Benchmark sur les fiches d'agent
   (Administration > Agents > profil) : activer, choisir la connexion + la table physique du LAB,
   valider le schema, poser `agent_key`.
3. Verifier : consultation (dropdown agent -> donut/verdict/KPIs/Q-par-Q), validation de schema
   (table OK vs table a colonnes manquantes), override admin (flip d'un verdict + survie au run
   suivant), launcher admin (run + degrade gracieux si LAB inaccessible).
4. Promotion prod quand DEV valide (rebuild + package prod + upload).

## 12. Hors scope / differe

- Gestion fine des droits d'acces (le launcher reste admin-only en attendant l'archi des droits).
- Mapping d'URL source multi-dataset, panel de juges, runs planifies (deja differes).
- Le launcher admin embarque peut etre reduit a "revue + override + lancer un run" si le
  cross-project d'edition de config lourde pose probleme : l'edition lourde reste alors sur la
  webapp LAB (degrade gracieux deja prevu, section 7.2).

## 13. Risques ouverts

- Cross-project depuis le plugin (lecture scored + ecriture override/config + run scenario) depend
  des droits de l'identite backend du plugin sur `OWIsMind_LAB`. Mitige par le degrade gracieux et
  par le fait que la CONSULTATION (pole D, lecture seule cross-project) est le coeur du MVP et le
  moins risque.
- Duplication des modules purs LAB -> plugin : point de sync explicite (en-tetes), modules stables.
- Re-juger le meme run_id efface ses overrides (documente, UI previent).
