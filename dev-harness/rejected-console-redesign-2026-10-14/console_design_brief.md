# Brief de refonte UX/UI : Agent Factory Console (Standard webapp DSS)

Public : un ingénieur Opus qui implémente DIRECTEMENT dans `body.html` / `script.js` / `style.css`
(vanilla JS ES5, pas de build, pas de lib). Le backend (`backend.py`, routes `/api/*`) est GELÉ.
Zéro perte de fonctionnalité : la table de correspondance (section 7) fait foi.
Interdits absolus : tiret cadratin / demi-cadratin partout ; emoji ; `color-mix` ; blur ; dégradés ;
glow ; hex en dur hors tokens ; visuel de marque reconstruit en CSS.

---

## 1. Diagnostic (pourquoi « on ne sait pas ce qui se passe »)

| # | Problème concret | Où (script.js) |
|---|---|---|
| D1 | **5 onglets de même poids** (Assistant, Vue d'ensemble, Sonde, Nouveau domaine, Prompts) : l'admin ne sait pas lequel est « le » chemin. « Nouveau domaine » et « Assistant » font la même chose en apparence (créer un agent) avec deux UX différentes. | `body.html` nav ; `selectTab`, `renderActive` |
| D2 | **L'écran de run empile tout** : en-tête de run + stepper de 13 lignes + carte « étape courante » + journal (table 3 colonnes) + bouton Abandonner. Le stepper (13 lignes plein écran) relègue l'action sous la ligne de flottaison. | `renderGuided` l.357, `renderGuidedStepper` l.510, `renderGuidedStage` l.535 |
| D3 | **Pas de « ce qui va se passer »** : le bouton dit « Lancer cette étape » et la modale « L'étape X sera exécutée côté serveur ». L'utilisateur ne voit jamais la liste des objets (zone, datasets, recettes, scénario, modèle, tool, agent) avant de cliquer, alors que les noms sont dérivables du spec. | `confirmGuidedStageRun` l.663 |
| D4 | **Les titres sont techniques** (« Application au modèle + tool », « Moteur d'agent (template) », « Enregistrement de la capability ») et les `detail_fr` viennent du backend en paragraphe : pas de phrase d'action, pas de hiérarchie. | `_STAGE_META` (backend, non modifiable) rendu brut l.547 |
| D5 | **Le journal technique est toujours visible** (table `Statut / Étape / Détail` avec des clés comme `preflight_hub`) même quand tout va bien. C'est utile en cas d'échec seulement. | `actionsTable` l.200, utilisé l.577 |
| D6 | **Les instructions manuelles sont un bloc de texte** (`instructions_fr` avec `<br>`) : pas de checklist, pas de distinction « ce que VOUS faites » / « ce que JE vérifie ». | `renderGuidedStage` branche `waiting_user` l.556 |
| D7 | **Le wizard est une sous-carte dans une carte** avec deux boutons ghost et un « C'est fait » en bas : trois actions concurrentes, aucune primaire claire. | `renderGuidedWizard` l.583 |
| D8 | **Pas de notion de progression** (« étape 4 sur 13 », phases) ni de temps attendu (le build dure plusieurs minutes et l'écran dit « Étape en cours côté serveur... »). | `renderGuidedStage` branche `running` l.565 |
| D9 | **L'écran de succès est pauvre** : ids bruts, une note « Ouvrez une NOUVELLE conversation » sans le rappel de re-save de l'orchestrateur (piège L168 pourtant dans la modale de bascule). | `renderGuidedSuccess` l.622 |
| D10 | **La suppression** réutilise mot pour mot l'écran de création ; l'inventaire (objets à supprimer) est injecté dans `detail_fr` en texte « SUPPRIMER : ... » alors que l'état porte une structure propre (`state.removal.inventory`). | `confirmGuidedStageRun` l.670, `_apply_removal_inventory_cards` backend |
| D11 | **Vue d'ensemble = tableau de bord de réglages** (clé projet, hub, 6 réglages JSON) AVANT la liste des agents : l'objet métier (les agents) passe en troisième position. | `renderOverview` l.877 |
| D12 | **Abandonner** est un bouton danger pleine largeur toujours présent sous le run : il concurrence l'action principale. | `renderGuided` l.404 |

Ce qui est BON et à garder tel quel : la couche API (`callApi`, `pollJob` avec backoff), la machine
d'états côté front (`applyGuidedRun`, `runGuidedStage`, `verifyGuidedStage`, `startGuidedWizard`
avec `reqId`, `abandonGuidedRun`), les gardes anti-réponses périmées du mode expert
(`specFingerprint`, `wizardFingerprint`, `invalidateDomainPlan`), la modale `openConfirm`, le toast,
le thème sur `#afc`.

---

## 2. Architecture de l'information

```
Mes agents (accueil)                         Parcours en cours (visible seulement si run actif)
 ├─ CTA primaire : Ajouter un agent  ──────►   Création guidée (stepper 13 étapes, 4 phases)
 ├─ par agent : Activer / Désactiver           Suppression guidée (stepper 12 étapes, 4 phases)
 ├─ par agent : Retirer...  ────────────────►
 └─ Détails techniques (repliés) : projet, hub, réglages usine
Avancé
 ├─ Sonde de l'instance        (ex-onglet Sonde, inchangé fonctionnellement)
 ├─ Mode expert                (ex-onglet Nouveau domaine : plan dry-run, exécuter, wizard libre)
 └─ Fichiers du hub            (ex-onglet Prompts : prompt persona + capabilities.json)
```

Justification :
- **Un seul chemin nominal** (Mes agents -> Ajouter un agent) : la création guidée EST le produit ;
  le mode expert (plan/execute en un bloc) et la sonde sont des outils d'admin avancé. Les regrouper
  sous « Avancé » les garde à un clic sans polluer le parcours.
- **Le parcours est un écran focalisé, pas un onglet** : on y entre par un CTA ou par le bandeau de
  reprise, on en sort par « Retour à mes agents ». Quand un run est actif, un item de nav
  « Parcours en cours » apparaît (point orange) pour y revenir : l'admin ne peut jamais « perdre » le run.
- **La suppression a son propre habillage** (eyebrow « Retrait d'un agent », bouton danger, liste
  d'objets « sera supprimé ») tout en réutilisant le même moteur d'écran.

Navigation (`S.tab`) : `home` | `run` | `probe` | `expert` | `hub`. La nav affiche 2 entrées fixes
(« Mes agents », « Avancé ») + 1 entrée conditionnelle (« Parcours en cours »). « Avancé » déplie une
sous-rangée de 3 onglets (même recette d'onglet, 13px). Le thème reste dans le header.

---

## 3. Le parcours guidé, écran par écran

### 3.0 Principes de l'écran d'étape (valables création ET suppression)

Chaque étape est rendue par UN composant `renderStage(run, ux)` alimenté par une table de microcopie
front `STAGE_UX[stageKey]` (section 3.3 / 3.4) et par l'état serveur (`stage.status`, `problems`,
`instructions_fr`, `journal`, `state.captured`, `state.removal.inventory`). Anatomie fixe, de haut en bas :

1. **Eyebrow** orange : `ÉTAPE 4 SUR 13 · CONSTRUIRE` (numéro global + nom de phase).
2. **Titre** (20px/800) : titre humain de `STAGE_UX`, repli sur `stage.title_fr`.
3. **Chip d'état** à droite du titre : `À faire` / `En cours` / `À vous de jouer` / `Terminée` /
   `Échec` / `Déjà faite` (journal SKIPPED « déjà satisfait »).
4. **« Ce qui va se passer »** : UNE phrase (micro-label `CE QUI VA SE PASSER` + texte 15px).
   Sujet = « je » (la console) pour les étapes auto, « À vous » pour les manuelles.
5. **Liste d'objets** (micro-label `CE QUI SERA CRÉÉ` / `CE QUI SERA SUPPRIMÉ` / `CE QUE JE VÉRIFIE`) :
   lignes `kind` en gris + `name` en mono + lieu entre parenthèses. Création : dérivée du spec côté
   client (section 3.2). Suppression : `state.removal.inventory.stages[stageKey]` (+ `protected`
   affiché en ligne grise « Jamais touché : <dataset source> » sur `delete_datasets`). Étape sans
   objet : une ligne « Aucune création : lecture seule ».
6. **Zone de problèmes** (si `stage.problems`) : carte filet gauche 3px `--danger`, titre
   `À corriger avant de relancer`, liste. Les messages backend sont déjà en français actionnable : les
   afficher tels quels.
7. **Zone spécifique** : checklist manuelle (3.0.b), sous-flux wizard (3.3 étape 6), instructions de
   repli manuel (brain/template/delete_* en `waiting_user`).
8. **Barre d'actions** : UNE primaire (libellé de `STAGE_UX`), 0 ou 1 secondaire ghost, et à droite
   un lien discret `Abandonner le parcours` (texte 12.5px `--text-2`, souligné au survol, JAMAIS un
   bouton danger plein ; la modale d'abandon garde le style danger).
9. **`<details class="afc-details">` « Détails techniques »** (replié par défaut) : `detail_fr`
   brut du serveur, journal (table actuelle `actionsTable`), clé d'étape, `run_id`. En cas d'`Échec`
   le details est OUVERT par défaut (le journal explique l'échec).

Phrase de confirmation (modale) : reprend la phrase « Ce qui va se passer » + la liste d'objets
(mêmes données, pas une seconde rédaction) + une ligne de garantie :
- auto création : « Rien n'est supprimé. Chaque création est idempotente : relancer est sans risque. »
- manuel/vérif : « Je ne modifie rien : je lis DSS pour confirmer que c'est fait. »
- suppression : « Irréversible. Le dataset source <base> n'est jamais touché. »

États de l'étape (cf. `stage.status` serveur, contrat gelé) :
- `ready` : anatomie complète, primaire active.
- `running` (ou `S.guided.running`) : la primaire devient `En cours...` désactivée + barre de
  progression indéterminée 3px orange sous le titre (animation `translateX`, pas de dégradé :
  un bloc plein qui va et vient) + texte d'attente de `STAGE_UX.wait` (ex. « En général 2 à 10 min.
  Vous pouvez fermer cette page : le parcours reprend où il en est. ») + le journal live se déplie
  en « Avancement » sous forme de liste compacte (statut chip + libellé), pas la table.
- `waiting_user` : checklist + primaire « C'est fait, vérifier ».
- `failed` : chip Échec, problèmes, primaire « Relancer », details ouvert.
- `done` : ne s'affiche pas comme écran courant (le serveur avance), sauf fin de run -> écran succès.

**(b) Checklist manuelle** : `instructions_fr` arrive en texte numéroté « 1. ... \n2. ... ». Le front
découpe sur `/\n(?=\d+\.\s)/`, retire le préfixe numérique et rend une liste `<ol class="afc-todo">`
(numéro carré 22px bordé, texte 14px, les noms d'objets déjà en MAJ/exacts restent tels quels).
La dernière consigne « Clique sur C'est fait ... » est retirée de la liste et devient la légende sous
le bouton : « Quand c'est fait, je vérifie dans DSS avant de passer à la suite. » Si le découpage ne
donne qu'un seul item (texte non numéroté, cas des replis manuels), afficher le texte en paragraphe
dans une carte `--surface`. Le texte brut reste dans « Détails techniques ».

### 3.1 Écran 0 : « Décrire l'agent » (formulaire de démarrage)

Remplace `renderGuidedStartForm`. Mêmes 5 champs (clé de domaine, dataset de base, libellé FR,
libellé EN, colonnes lookup), MÊME payload `guided/start`. Ajout d'un panneau latéral droit
**« Ce qui sera créé »** mis à jour EN DIRECT à la saisie (noms dérivés, section 3.2) : c'est la
réponse au « que va-t-il se passer quand je clique ». Primaire : `Commencer le parcours`.
Modale : « Démarrer la création de l'expert <label_fr> ? » + phrase « Je crée un parcours persistant
pour le domaine <domain> sur le dataset <base>, puis je lance immédiatement les vérifications
préalables (lecture seule). » + liste des 12 objets.
Erreur `active_run_exists` : note + bouton ghost `Reprendre le parcours en cours` (existant).
Note : le serveur exécute `preflight` de façon synchrone au start : l'écran suivant est donc
directement l'étape 1 en état `done`->avancée (étape 2 ready) ou `failed` (problèmes affichés).

### 3.2 Noms dérivés côté client (miroir de `DomainSpec`, spec.py l.72-125)

`titleNoUnderscore(domain)` = chaque segment séparé par `_` avec initiale majuscule, le reste
en minuscules (équivalent `str.title().replace("_","")`), ex. `sales_ops` -> `SalesOps`.
Utiliser `run.state.spec.zone_name` quand il est renseigné (il l'est toujours dans l'état serveur).

| Objet (kind affiché) | Nom | Lieu |
|---|---|---|
| Zone Flow | `spec.zone_name` (défaut `<Title>_Expert`) | Flow |
| Dataset de connaissance x3 | `<base>_profile`, `<base>_value_index`, `<base>_value_catalog` | Flow, zone |
| Recette x3 | `compute_<dataset>` pour chacun des 3 | Flow, zone |
| Scénario | `Refresh_<Title>` | Scénarios |
| Modèle sémantique | `<base>_Semantic_Model` | Agents & GenAI |
| Outil Semantic Model Query | `<domain>_semantic_query` | Agents & GenAI, Tools |
| Code Agent | `<Title>_expert` | Agents & GenAI, Agents |
| Entrée de registre | `<domain>_expert` dans `capabilities.json` | Hub (project library) |
| Outil orchestrateur | `ask_<domain>_expert` | Orchestrateur (après activation) |

### 3.3 Création guidée : 13 étapes, 4 phases

Phases (rail) : **1 Préparer** (preflight, plan) · **2 Construire** (infra, first_build,
profile_review) · **3 Créer l'expert** (wizard, brain, template, agent_code, code_agent) ·
**4 Activer** (capability, smoke, enable). Dans la table, `[auto]` = primaire -> `guided/run`,
`[manuel]` = primaire -> `guided/verify`. `<...>` = valeurs du spec/dérivées.

| Clé | Titre | Ce qui va se passer | Objets listés | Primaire | Modale (titre) | Running (attente) | Succès / échec |
|---|---|---|---|---|---|---|---|
| preflight [auto] | Vérifier les prérequis | Je contrôle le hub, le dataset `<base>` (non partitionné) et l'absence de collision de noms. Rien n'est créé. | « Aucune création : lecture seule » | `Relancer la vérification` (seulement si failed, sinon l'étape est déjà passée) | Relancer les vérifications ? | quelques secondes | Échec : problèmes (déjà actionnables côté serveur) + details ouvert |
| plan [auto] | Simuler la création | Je simule toute la création et je liste ce qui sera créé, sans rien toucher à DSS. | les 12 objets (3.2) | `Simuler` | Simuler la création de `<label_fr>` ? | quelques secondes | Done : le serveur avance ; le journal de simulation reste lisible dans « Détails techniques » de l'étape suivante via le rail (clic sur une étape terminée ouvre un panneau lecture seule, voir 4.1) |
| infra [auto] | Créer la structure Flow | Je crée la zone `<zone>`, 3 datasets de connaissance, 3 recettes et le scénario de refresh. | zone, 3 datasets, 3 recettes, scénario (8) | `Créer la structure` | Créer 8 objets dans le Flow ? | « Environ une minute. » | Échec : liste `step : détail` du serveur |
| first_build [auto] | Construire les connaissances | Je lance le scénario `<Refresh_X>` et j'attends son résultat : profil, index de valeurs, catalogue. | 3 datasets « seront remplis » | `Lancer le build` | Lancer le build des connaissances ? (ligne : « Plusieurs minutes. Un run déjà en cours est repris, jamais doublé. ») | « En général 2 à 10 minutes. Vous pouvez fermer cette page : le parcours reprend où il en est. » | Échec : problèmes serveur (TIMEOUT = « relancer rattache le run », pas une erreur) ; chip `Déjà faite` si précheck l'a sautée |
| profile_review [manuel] | Relire le profil | À vous : relire le dataset `<base>_profile` et corriger ce qui est faux via les overrides. | « Ce que je vérifie : le dataset `<base>_profile` existe » | `C'est fait, vérifier` | Vérifier la relecture ? « Je vérifie que `<base>_profile` existe. Je ne modifie rien. » | « Vérification... » (1 à 2 s) | Échec : problèmes |
| wizard [manuel, sous-flux] | Décrire le modèle sémantique (IA) | L'IA rédige un brouillon de modèle sémantique à partir du profil (métadonnées seulement, aucune ligne de données), vous répondez à ses questions, puis je vérifie que le brouillon est enregistré dans le hub. | « Brouillon `wizard/<domain>-config.json` (hub) » | voir sous-flux | voir sous-flux | « Rédaction en cours (environ 30 s à 1 min). » | Échec vérif : problèmes (ex. brouillon d'un autre dataset) |
| brain [auto] | Créer le modèle et l'outil | Je crée le modèle sémantique `<base>_Semantic_Model`, j'y applique le brouillon, je l'indexe et je crée l'outil `<domain>_semantic_query`. | modèle, outil | `Créer le modèle et l'outil` | Créer le modèle et l'outil ? | « 1 à 3 minutes (indexation). » | `waiting_user` = création auto du tool refusée : checklist manuelle (instructions serveur) + `C'est fait, vérifier` |
| template [auto] | Vérifier le moteur d'agent | Je vérifie que le moteur d'agent (template) est présent dans le hub. | « Fichier `templates/dataset_expert.py` (hub) » | `Vérifier` | Vérifier le moteur ? | 1 s | `waiting_user` : checklist de collage + `C'est fait, vérifier` ; souvent `Déjà faite` |
| agent_code [auto] | Générer le code de l'agent | Je génère le code du sous-agent `<Title>_expert` avec les bons identifiants et je crée le Code Agent si l'instance le permet (sinon je dépose le fichier dans le hub pour un collage). | Code Agent `<Title>_expert` ou fichier `generated/<Title>_expert.py` | `Générer le code` | Générer le code de l'agent ? | quelques secondes | Échec : problèmes |
| code_agent [manuel] | Créer le Code Agent | À vous : créer le Code Agent `<Title>_expert` (env 3.11) et y coller le code généré. | « Ce que je vérifie : l'agent `<Title>_expert` existe » | `C'est fait, vérifier` | Vérifier le Code Agent ? « Je retrouve l'agent par son nom et je note son id. » | 1 à 2 s | souvent `Déjà faite` quand l'étape précédente a créé l'agent |
| capability [auto] | Enregistrer l'expert | J'ajoute l'expert `<domain>_expert` au registre du hub, DÉSACTIVÉ pour l'instant. | « Entrée `<domain>_expert` dans `capabilities.json` (sauvegarde auto du précédent) » | `Enregistrer` | Enregistrer l'expert dans le registre ? | 1 s | Échec : problèmes |
| smoke [manuel] | Tester l'expert | À vous : poser les 4 questions de test dans la webapp OWIsMind (NOUVELLE conversation) et vérifier timeline + Evidence. | « Ce que je vérifie : l'entrée `<domain>_expert` est toujours dans le registre » | `C'est fait, vérifier` | Passer à l'activation ? | 1 s | - |
| enable [auto] | Activer l'expert | J'active l'expert dans le registre : l'orchestrateur gagne l'outil `ask_<domain>_expert`. | « `enabled: true` sur `<domain>_expert` » | `Activer l'expert` | Activer l'expert `<label_fr>` ? (ligne : « Après activation : re-sauvegarder l'orchestrateur dans DSS puis ouvrir une NOUVELLE conversation. ») | 1 s | Écran de succès (3.5) |

**Sous-flux wizard (étape 6)**, états de `S.guided.wizard` :
- pas de `config` : primaire `Rédiger le brouillon (IA)` (-> `wizard/draft`, modale existante
  « Aucune ligne brute ne sera envoyée au modèle »), secondaire `C'est fait, vérifier` ghost
  (cas où un brouillon valide existe déjà dans le hub : le serveur le dira).
- `running` : barre indéterminée + « Rédaction en cours... ».
- `config` présente : questions rendues UNE par carte (`afc-q`, inchangé), puis barre d'actions :
  primaire `Vérifier et continuer` (-> `guided/verify`), secondaire ghost `Re-rédiger avec mes réponses`.
  Si `questions` vide : note « Le brouillon n'a besoin d'aucune précision. »
- `error` : note erreur + primaire redevient `Rédiger le brouillon (IA)`.
- Le JSON du brouillon va dans « Détails techniques » (pre + bouton Copier), pas en pleine page.

### 3.4 Suppression guidée : 12 étapes, 4 phases

Entrée : « Mes agents » -> ligne de l'agent -> bouton ghost `Retirer...` -> modale danger (existante,
texte réécrit) avec saisie du nom de domaine : titre « Retirer l'expert <label_fr> ? », corps :
« Je crée un parcours de retrait en 12 étapes. Rien n'est supprimé maintenant : je fais d'abord
l'inventaire, puis chaque suppression vous est présentée et confirmée une par une. Le dataset source
n'est jamais touché. » + champ « Pour confirmer, tapez le nom du domaine : <domain> ». Bouton danger
`Créer le parcours de retrait`. Erreurs `domain_mismatch` / `active_run_exists` : messages existants.

Phases : **1 Inventaire** (inventory, disable) · **2 Supprimer** (delete_tool, delete_agent,
delete_model, delete_scenario, delete_recipes, delete_datasets, delete_zone) · **3 Nettoyer**
(catalog_cleanup, hub_cleanup) · **4 Vérifier** (final_check). Eyebrow de l'écran : `RETRAIT D'UN
AGENT · <domain>`. Les primaires des étapes de suppression sont des boutons DANGER pleins (le seul
endroit où un plein rouge est permis) ; la modale est danger et répète la liste.

| Clé | Titre | Ce qui va se passer | Objets listés (source) | Primaire | Modale |
|---|---|---|---|---|---|
| inventory [auto, sync au start] | Inventorier | Je sonde ce qui existe réellement pour cet expert. Rien n'est supprimé. | « Aucune suppression : lecture seule » | (déjà exécutée au start) ; si `waiting_user` (templates en conflit) : avertissement orange + `J'ai compris, continuer` (-> verify) | Continuer malgré les templates ? (texte serveur) |
| disable [auto] | Couper le routage | Je désactive l'expert dans le registre : l'orchestrateur cesse de lui envoyer des questions. | « `enabled: false` sur `<key>` » | `Désactiver` | Désactiver l'expert ? |
| delete_tool [auto, danger] | Supprimer l'outil | Je supprime l'outil Semantic Model Query de ce domaine. | `inventory.stages.delete_tool` | `Supprimer l'outil` | Supprimer 1 objet dans DSS ? |
| delete_agent [auto, danger] | Supprimer le Code Agent | Je supprime le Code Agent de ce domaine. | `...delete_agent` | `Supprimer le Code Agent` | idem |
| delete_model [auto, danger] | Supprimer le modèle sémantique | Je supprime le modèle sémantique de ce domaine. | `...delete_model` | `Supprimer le modèle` | idem |
| delete_scenario [auto, danger] | Supprimer le scénario | Je supprime le scénario de refresh. | `...delete_scenario` | `Supprimer le scénario` | idem |
| delete_recipes [auto, danger] | Supprimer les recettes | Je supprime les recettes de connaissance. | `...delete_recipes` (3) | `Supprimer les recettes` | Supprimer 3 objets ? |
| delete_datasets [auto, danger] | Supprimer les datasets de connaissance | Je supprime les datasets dérivés et leurs tables SQL (reconstructibles). | `...delete_datasets` + ligne grise « Jamais touché : <source> » (`inventory.protected`) | `Supprimer les datasets` | idem |
| delete_zone [auto, danger] | Supprimer la zone Flow | Je supprime la zone si elle est vide, sinon je la laisse. | `...delete_zone` | `Supprimer la zone` | idem |
| catalog_cleanup [auto, danger] | Nettoyer le catalogue partagé | Je supprime les lignes de cet expert dans le catalogue commun (SQL paramétré). | « Lignes `capability_key = <key>` du catalogue partagé » | `Nettoyer` | Nettoyer le catalogue ? |
| hub_cleanup [auto, danger] | Nettoyer le hub | Je supprime la config wizard, les prompts, le code généré, puis l'entrée du registre (sauvegarde auto). | `inventory.hub_paths` (chemins) + « Entrée `<key>` de `capabilities.json` » | `Nettoyer le hub` | Nettoyer le hub ? |
| final_check [auto] | Vérifier que tout est parti | Je re-sonde l'absence de chaque objet. | « Aucune suppression : lecture seule » | `Vérifier` | Lancer la vérification finale ? |

Étapes vides (`items` = []) : la carte dit « Rien à supprimer : déjà absent » et la primaire devient
ghost `Passer` (même appel `guided/run` : le serveur skippe). Étape en `waiting_user` (suppression
refusée par l'API) : checklist serveur « Supprime ces objets à la main... » + `C'est fait, vérifier`.

Écran de succès suppression : « L'expert <domain> est retiré » + liste de ce qui a été supprimé
(inventaire) + encart « Et maintenant » : (1) re-sauvegarder l'orchestrateur dans DSS, (2) ouvrir
une NOUVELLE conversation (registre chargé au démarrage du process). Primaire `Retour à mes agents`.

### 3.5 Écran de succès création

Carte à règle haute 3px `--success`, eyebrow `PARCOURS TERMINÉ`, titre « L'expert <label_fr> est
actif », sous-titre « L'orchestrateur sait désormais router les questions <domain>. »
Bloc « Ce qui a été créé » : les 12 objets avec les ids capturés (`captured.model_id`, `tool_id`,
`agent_id`) en mono à droite. Encart « Et maintenant » (2 cases à cocher visuelles, non
persistées) : (1) « Re-sauvegarder l'orchestrateur dans DSS (le registre est chargé au démarrage du
process) » (2) « Ouvrir une NOUVELLE conversation dans OWIsMind et poser une question <domain> ».
Actions : primaire `Retour à mes agents` (-> `S.tab = "home"`, `S.overview.loaded = false`),
ghost `Ajouter un autre agent` (= `newGuidedDomain` existant).

---

## 4. Spécification composants et mise en page

Largeur utile max 1120px. Écran de parcours = grille `260px 1fr` (gap 32px) ; sous 820px le rail
passe au-dessus en rangée horizontale compacte (phases seules + « étape 4/13 »).

### 4.1 Rail (stepper vertical groupé) `.rail`
- Conteneur sans bordure (nuance par surfaces, pas par filets, charte section 0).
- Groupe de phase : micro-label `1 · PRÉPARER` (11px/800/MAJ/0.08em, `--text-2`) ; ligne de 2px
  `--border` au-dessus de chaque groupe sauf le premier.
- Ligne d'étape : grille `22px 1fr auto`, hauteur 36px, padding 6px 10px, `border-radius: var(--r-sm)`
  (ligne de nav = `--r-sm` autorisé). Pastille 18px carrée : numéro mono 11px bordé 1px (à faire),
  fond `--text` + numéro `--bg` (courante), fond `--success` + check blanc (faite), `--danger` + X
  (échec), bordure pointillée `--text-3` (déjà faite/sautée). Titre 13px ; courante = 700 + fond
  `--surface-press` (ajouter le token : clair `#e9e9e9`, sombre `#242424`) + **title-bar 18x2
  orange** sous le titre (signature d'état, recette charte ; AUCUN liseré vertical gauche : supprimer
  l'actuel `border-left: 3px solid var(--orange)` de `.gd-step--current`).
- Étape faite = cliquable : ouvre à droite un panneau LECTURE SEULE (titre, phrase, journal) avec un
  lien `Revenir à l'étape en cours`. Étapes à venir : non cliquables, `--text-3`.
- Pied du rail : `Étape 4 sur 13` mono 12px + barre de progression 2px (`--border` fond, `--text`
  rempli ; pas d'orange : l'orange est déjà sur la ligne courante).

### 4.2 Carte d'étape `.stage`
- Panneau structurel : carré, `border: 1px solid var(--border-strong)`, fond `--bg`, padding 28px 32px.
- Eyebrow 11px orange, titre 22px/800 (`letter-spacing -0.01em`), chip d'état alignée à droite.
- Phrase « Ce qui va se passer » : 15px `--text`, line-height 1.55, max 68ch.
- Liste d'objets `.objects` : grille `max-content 1fr`, lignes séparées par 1px `--border`, kind en
  12.5px `--text-2`, nom en mono 13px `--text`, lieu 12.5px `--text-3` à droite. En-tête = micro-label.
  Préfixe de ligne en suppression : petit carré 8px `--danger` ; en création : carré 8px `--text`.
- Barre de progression indéterminée (`running`) : piste 3px `--border`, curseur 96px `--orange`,
  `@keyframes afc-slide` translateX de -96px à 100% en 1.4s linéaire infini ; désactivée sous
  `prefers-reduced-motion` (curseur statique).
- Barre d'actions : `display:flex; gap:12px; align-items:center;` primaire à gauche, secondaire
  ensuite, `margin-left:auto` pour le lien Abandonner.
- `<details class="afc-details">` : `summary` = micro-label `DÉTAILS TECHNIQUES` + chevron SVG
  tournant (rotate 90deg, `--dur-fast`), `list-style:none`, 1px `--border` au-dessus, contenu padding
  16px 0 0. État d'ouverture persisté dans `S.ui.details[stageKey]` et réappliqué après chaque
  `setMain` (sinon le polling le referme).

### 4.3 Chips d'état (parcours)
`--r-pill`, 11px/700/MAJ, padding 3px 10px, 1px bordure. Mapping : `ready` -> « À faire »
(`--text`, bordure `--text`) ; `running` -> « En cours » (`--info`) ; `waiting_user` -> « À vous de
jouer » (`--orange-text`, bordure `--orange`) ; `done` -> « Terminée » (`--success`) ; `failed` ->
« Échec » (`--danger`) ; `pending` -> « À venir » (`--text-3`) ; done + journal SKIPPED « déjà
satisfait » -> « Déjà faite » (`--text-2`, bordure pointillée).
Chips de journal (`statusChip`) et d'agent (ACTIF/INACTIF) : même recette pill, libellés inchangés.

### 4.4 Boutons (hiérarchie : UNE primaire par écran)
- Primaire : plein `--orange`, texte `#fff`, `--r-pill`, 14px/700, padding 11px 20px, hover
  `--orange-deep`, focus-visible = anneau 2px `--orange` à 2px d'offset (clavier seulement).
- Danger (suppression) : plein `--danger`, `#fff`, pill. Réservé aux étapes `delete_*`/cleanup et
  aux modales de suppression/abandon.
- Secondaire (ghost) : 1px `--border-strong`, texte `--text`, pill, hover bordure `--text` +
  `--surface`. Small : padding 7px 14px, 12.5px.
- Lien texte (Abandonner, Revenir) : 12.5px `--text-2`, souligné au survol, pas de bordure.
- Désactivé : opacité .4, curseur not-allowed, pas d'effet hover (règles existantes).
- Les icônes existantes (`I.play`, `I.check`...) sont conservées ; ajouter `I.chevron`, `I.x`,
  `I.arrowLeft` (retour), `I.dot` inutile (CSS).

### 4.5 Accueil « Mes agents » (ex Vue d'ensemble)
- En-tête de page existant (eyebrow + H1 + title-bar 52x4) : H1 devient « Mes agents », eyebrow
  « OWIsMind · Usine à agents ». À droite du H1 : primaire `Ajouter un agent` (+ icône plus) ; si un
  run est actif, le CTA devient ghost et un **bandeau de reprise** s'affiche sous l'en-tête :
  carte `--surface`, filet gauche 3px orange (filet d'alerte autorisé sur une note, pas marqueur de
  nav), texte « Parcours en cours : création de l'expert <domain>, étape 4 sur 13 (Construire les
  connaissances). » + primaire `Reprendre`. Pour un retrait : « Parcours en cours : retrait de
  l'expert <domain>... ».
- Liste d'agents = **lignes** (pas de grille de cartes) : tableau sans en-tête visible, chaque ligne
  = tuile d'icône carrée 36px (glyphe SVG « agent » orange sur `--surface`) + nom `label_fr` 15px/700
  + sous-ligne `domain · ask_<x>_expert · agent:<id>` en mono 12px `--text-3` + chip ACTIF/INACTIF +
  actions à droite : ghost small `Désactiver`/`Activer`, ghost small `Retirer...`. Séparateur 1px
  `--border`. Hover ligne `--surface-hover`.
- Empty state (0 capability) : carte carrée 1px `--border-strong`, tuile d'icône, titre « Aucun
  agent enregistré », texte existant (hub non poussé / CAPABILITIES embarquées), CTA primaire
  `Ajouter un agent`.
- `HUB ABSENT` : note warn sous l'en-tête « Le hub n'est pas poussé dans la project library : la
  création est impossible tant qu'il manque. » (le preflight le redira).
- **Détails techniques** (`<details>` replié) en bas : clé de projet, statut hub (chip), les 6
  réglages `factory_settings.json` (dl existante), bouton ghost small `Actualiser`.
- Modale bascule (existante) : titre « Activer l'expert <label_fr> ? », phrase « Je passe
  `<key>` à ACTIF dans le registre (sauvegarde auto). Rien d'autre ne change. » + ligne « Ensuite :
  re-sauvegarder l'orchestrateur dans DSS, puis ouvrir une NOUVELLE conversation. »

### 4.6 Avancé
- Sous-rangée d'onglets `Sonde · Mode expert · Fichiers du hub` sous la nav principale (même
  recette : soulignement 3px orange, 13px).
- **Sonde** : inchangée (bouton primaire, note lecture seule, rapport `pre` + Copier). Le texte
  d'intro passe en 2 phrases max.
- **Mode expert** : bandeau info en tête « Pour les admins avancés : exécute la création d'un
  domaine en un seul bloc, sans accompagnement. Le parcours guidé (Mes agents > Ajouter un agent)
  reste la voie recommandée. » Puis le contenu actuel de `renderDomainNow` réorganisé en 3 cartes
  numérotées : `1. Décrire` (formulaire + segmenté source), `2. Simuler` (bouton `Simuler (dry-run)`,
  plan, avertissements, compteurs), `3. Exécuter` (bouton primaire visible seulement si plan valide,
  journal, checklist MANUEL, runbook). Le wizard sémantique devient une carte `Wizard sémantique
  (optionnel)` placée entre 1 et 2 (car un brouillon invalide le plan) avec la ligne d'état
  « Config du wizard : prête / absente ». Toute la logique (`domainField`, fingerprints,
  invalidation) est inchangée.
- **Fichiers du hub** : deux cartes `Prompt de persona` et `Registre capabilities.json`, inchangées
  fonctionnellement (chemin + Charger, textarea code, Enregistrer ; problèmes de validation en
  liste rouge). Ajouter une ligne d'aide sous chaque titre, pas de paragraphe.

### 4.7 Modale (anatomie)
Scrim plat `--scrim`, carte 560px max, `--r-lg` (flottante), 1px `--border-strong`, `--elev-1`
(ajouter le token : clair `0 1px 2px rgba(0,0,0,.06), 0 8px 24px rgba(0,0,0,.08)` ; sombre
`0 1px 2px rgba(0,0,0,.5), 0 8px 24px rgba(0,0,0,.45)`). Titre 20px/800. Corps : phrase « Ce qui va
se passer » (15px `--text`), liste d'objets (même composant `.objects`), ligne de garantie 12.5px
`--text-2`. Champ de saisie de confirmation (suppression) : input existant, focus = bordure
`--text-3` + `--elev-1` (recette charte section 0 ; retirer `border-color: var(--orange)` du focus
des champs). Pied : ghost `Annuler` + primaire/danger. Échap et clic scrim ferment (existant).

### 4.8 Toast
Inchangé (noir/blanc, check orange). Positionner en bas à droite (24px) plutôt que centré pour ne
pas couvrir la barre d'actions. Durée 2600 ms conservée.

### 4.9 Typographie et espacement (tokens existants dans `#afc`)
Échelle : H1 36/800 ; titre d'étape 22/800 ; titre de carte 20/800 ; corps 14 ; phrase d'action 15 ;
aide 12.5 `--text-2` ; micro-label 11/800/MAJ/0.08em ; mono 12.5 à 13. Espacement 8px : 8/12/16/24/32.
Ajouter dans `#afc` : `--r-xs: 4px; --r-sm: 6px; --r: 8px; --r-lg: 12px; --r-pill: 999px;
--surface-press; --elev-1; --dur-fast: 120ms; --dur: 200ms; --ease-out: cubic-bezier(.2,.7,.2,1)`.
Géométrie : carrée pour cartes, panneaux, rail, tables, tuiles d'icône, listes d'objets, notes,
checkbox ; `--r-pill` pour chips et boutons ; `--r-lg` pour la modale ; `--r-sm` pour les lignes du
rail et de la liste d'agents ; champs de formulaire `--r-sm` (lisibilité du focus, reste discret).

### 4.10 Thème sombre
Tokens déjà définis sur `#afc[data-theme="dark"]` ; ajouter `--surface-press`, `--elev-1` sombres.
Points d'attention : la ligne courante du rail en sombre = `--surface-press` (#242424) sur `--bg`
(#0d0d0d) ; la barre de progression garde `--orange` ; le panneau d'étape reste `--bg` (structurel),
la modale prend `--surface-2` (palier au-dessus du fond, charte section 0) ; les chips `--success` /
`--danger` sombres sont déjà AA sur `--bg`. Vérifier `.afc-pre` (fond `--surface`) et `.afc-manual`
(`--orange-soft` .16) en sombre : OK avec les tokens.

### 4.11 Wireframes ASCII

**Accueil (run actif)**
```
OWISMIND · USINE À AGENTS                                             [theme]
Mes agents
████                                                   [ Ajouter un agent ]
[Mes agents] [Parcours en cours ●] [Avancé]
──────────────────────────────────────────────────────────────────────────
▌ Parcours en cours : création de l'expert satisfaction, étape 4 sur 13
▌ (Construire les connaissances).                             [ Reprendre ]

[■] Expert revenus (Drive)                    ACTIF   [Désactiver] [Retirer...]
    revenue · ask_revenue_expert · agent:bHrWLyOL
──────────────────────────────────────────────────────────────────────────
[■] Expert tickets (incidents)                ACTIF   [Désactiver] [Retirer...]
    tickets · ask_tickets_expert · agent:NcE9LD2i
──────────────────────────────────────────────────────────────────────────
▸ DÉTAILS TECHNIQUES   (projet OWISMIND_DEV · HUB PRÊT · réglages usine)
```

**Écran 0 : Décrire l'agent**
```
← Mes agents
AJOUTER UN AGENT
Décrire l'agent
████
┌──────────────────────────────────────┐ ┌─────────────────────────────────┐
│ CLÉ DE DOMAINE          [satisfaction]│ │ CE QUI SERA CRÉÉ                │
│ DATASET DE BASE   [Satisfaction  ▾] ↻ │ │ Zone Flow      Satisfaction_Expert│
│ LIBELLÉ FR   [ ]   LIBELLÉ EN  [ ]    │ │ Dataset        Satisfaction_profile│
│ COLONNES LOOKUP (optionnel)  [ ]      │ │ Dataset        Satisfaction_value_index│
│                                        │ │ ... (12 lignes)                  │
│ [ Commencer le parcours ]              │ │ Rien n'est créé avant l'étape 3. │
└──────────────────────────────────────┘ └─────────────────────────────────┘
```

**Étape auto, à faire (infra)**
```
← Mes agents                       CRÉATION DE L'EXPERT · satisfaction
┌─ 1 · PRÉPARER ──────┐  ┌────────────────────────────────────────────────┐
│ ✓ Vérifier prérequis│  │ ÉTAPE 3 SUR 13 · CONSTRUIRE            [À FAIRE]│
│ ✓ Simuler           │  │ Créer la structure Flow                         │
│ 2 · CONSTRUIRE      │  │                                                 │
│ ■ Créer la structure│  │ CE QUI VA SE PASSER                             │
│   ▔▔                │  │ Je crée la zone Satisfaction_Expert, 3 datasets │
│ 4 Construire conn.  │  │ de connaissance, 3 recettes et le scénario de   │
│ 5 Relire le profil  │  │ refresh. Rien n'est supprimé.                   │
│ 3 · CRÉER L'EXPERT  │  │                                                 │
│ 6 Décrire le modèle │  │ CE QUI SERA CRÉÉ (8)                            │
│ ...                 │  │ ■ Zone Flow        Satisfaction_Expert     Flow │
│ 4 · ACTIVER         │  │ ■ Dataset          Satisfaction_profile    zone │
│ ...                 │  │ ■ Recette          compute_Satisfaction_profile │
│                     │  │ ■ Scénario         Refresh_Satisfaction         │
│ Étape 3 sur 13      │  │                                                 │
│ ▬▬▬░░░░░░░░░░░░░░   │  │ [ Créer la structure ]      Abandonner le parcours│
└─────────────────────┘  │ ─────────────────────────────────────────────── │
                         │ ▸ DÉTAILS TECHNIQUES                            │
                         └────────────────────────────────────────────────┘
```

**Étape en cours (first_build)**
```
│ ÉTAPE 4 SUR 13 · CONSTRUIRE                               [EN COURS]│
│ Construire les connaissances                                         │
│ ▬▬▬▬▬▬▬░░░░░░░░░░░░░░░░░░░░░░░░░░░░ (curseur orange qui va et vient) │
│ Je lance le scénario Refresh_Satisfaction et j'attends son résultat. │
│ En général 2 à 10 minutes. Vous pouvez fermer cette page : le        │
│ parcours reprend où il en est.                                       │
│ AVANCEMENT                                                           │
│ FAIT    scenario_run      run started (id ...)                       │
│ FAIT    build_profile     Satisfaction_profile built                 │
│ [ En cours... ]                                                      │
```

**Étape manuelle (code_agent)**
```
│ ÉTAPE 10 SUR 13 · CRÉER L'EXPERT                    [À VOUS DE JOUER]│
│ Créer le Code Agent                                                  │
│ CE QUI VA SE PASSER                                                  │
│ À vous : créer le Code Agent Satisfaction_expert (env 3.11) et y     │
│ coller le code généré. Ensuite je vérifie dans DSS.                  │
│ À FAIRE DANS DSS                                                     │
│ [1] Agents & GenAI Models puis New Agent puis Code Agent, nom EXACT  │
│     Satisfaction_expert.                                             │
│ [2] Onglet Settings : sélectionne l'environnement Python 3.11.       │
│ [3] Onglet Code : colle le contenu de generated/Satisfaction_expert.py│
│ [4] Vérifie SEMANTIC_TOOL_ID = v4oqA6R puis sauvegarde.              │
│ CE QUE JE VÉRIFIE : l'agent Satisfaction_expert existe (je note son id)│
│ [ C'est fait, vérifier ]                         Abandonner le parcours│
│ Quand c'est fait, je vérifie dans DSS avant de passer à la suite.    │
```

**Succès**
```
│ ▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔ (règle haute verte)                                  │
│ PARCOURS TERMINÉ                                                     │
│ L'expert Satisfaction client est actif                               │
│ L'orchestrateur sait désormais router les questions satisfaction.    │
│ CE QUI A ÉTÉ CRÉÉ                                                    │
│ Modèle sémantique   Satisfaction_Semantic_Model        AHUh9hb        │
│ Outil               satisfaction_semantic_query        v4oqA6R        │
│ Code Agent          Satisfaction_expert                agent:xxxx     │
│ ... (12 lignes)                                                       │
│ ET MAINTENANT                                                        │
│ [ ] Re-sauvegarder l'orchestrateur dans DSS                          │
│ [ ] Ouvrir une NOUVELLE conversation et poser une question           │
│ [ Retour à mes agents ]  [ Ajouter un autre agent ]                  │
```

**Suppression (delete_datasets)**
```
RETRAIT D'UN AGENT · tickets
│ ÉTAPE 8 SUR 12 · SUPPRIMER                                 [À FAIRE]│
│ Supprimer les datasets de connaissance                               │
│ Je supprime les datasets dérivés et leurs tables SQL (reconstructibles).│
│ CE QUI SERA SUPPRIMÉ (3)                                             │
│ ■ Dataset   TroubleTickets_year_profile   [id ...]   Flow, zone CSC  │
│ ■ Dataset   TroubleTickets_year_value_index          Flow, zone CSC  │
│ ■ Dataset   TroubleTickets_year_value_catalogue      Flow, zone CSC  │
│   Jamais touché : TroubleTickets_year (dataset source)               │
│ [ Supprimer les datasets ]  (danger)          Abandonner le parcours │
```

**Modale de confirmation (auto création)**
```
┌ Créer 8 objets dans le Flow ? ───────────────────────────┐
│ Je crée la zone Satisfaction_Expert, 3 datasets de        │
│ connaissance, 3 recettes et le scénario de refresh.       │
│ ■ Zone Flow   Satisfaction_Expert                          │
│ ■ ... (8)                                                  │
│ Rien n'est supprimé. Relancer est sans risque (idempotent).│
│                              [ Annuler ]  [ Créer ]        │
└────────────────────────────────────────────────────────────┘
```

---

## 5. Microcopie transverse (final, français)

- Nav : `Mes agents` · `Parcours en cours` · `Avancé` ; sous-onglets `Sonde` · `Mode expert` ·
  `Fichiers du hub`.
- Retour : `← Mes agents` (lien texte en haut de l'écran de parcours).
- Abandon (lien) : `Abandonner le parcours` ; modale titre « Abandonner ce parcours ? », corps « Le
  parcours est marqué abandonné. Rien n'est supprimé dans DSS : ce qui a déjà été créé reste en
  place. Vous pourrez en démarrer un nouveau. », danger `Abandonner`. Toast : « Parcours abandonné.
  Rien n'a été supprimé. »
- Toasts : « Parcours démarré. » / « Brouillon enregistré dans le hub. » / « Étape terminée. » (après
  un `done` d'étape auto ; UNE fois par étape) / « Expert activé. » / « L'étape a échoué : lisez les
  points à corriger. »
- Erreurs : conserver le mapping `guidedErrorText` tel quel (il est déjà actionnable). `busy` :
  « Une opération de l'usine est déjà en cours. Réessayez dans un instant. »
- Chargement : « Je cherche un parcours en cours... » ; « Chargement des agents... ».
- Backend absent : note warn existante inchangée.

---

## 6. Table de correspondance (zéro perte)

| Fonction / appel actuel | Avant | Après |
|---|---|---|
| `GET state` (projet, hub, réglages, capabilities) | Vue d'ensemble | Accueil Mes agents (liste) + « Détails techniques » (projet, hub, réglages) |
| `POST capability/enable` + modale rappel L168 | carte agent | ligne agent, bouton `Activer`/`Désactiver`, modale réécrite (rappel conservé) |
| `POST guided/start-removal` + nom tapé + erreurs `domain_mismatch`/`active_run_exists` | carte agent `Supprimer...` | ligne agent `Retirer...`, même modale (texte réécrit), mêmes erreurs |
| `GET guided/current` + `heal_interrupted` | onglet Assistant | bandeau de reprise + item nav `Parcours en cours` + écran parcours |
| Formulaire de démarrage (5 champs) + `GET datasets` + rafraîchir + `POST guided/start` + erreur `active_run_exists` + `Reprendre` | Assistant | Écran 0 « Décrire l'agent » + panneau « Ce qui sera créé » |
| Stepper 13/12 étapes, statuts `pending/ready/running/waiting_user/done/failed` | liste pleine largeur | rail gauche groupé par phases (+ panneau lecture seule des étapes faites) |
| `POST guided/run` + modale (danger sur `REMOVAL_DANGER_STAGES`) + `pollJob` + journal live + `refreshDatasetsAfterInfra` | « Lancer cette étape » | primaire de l'étape, modale « ce qui va se passer » + objets, barre de progression + « Avancement », journal dans Détails techniques ; `refreshDatasetsAfterInfra` inchangé |
| `POST guided/verify` + modale | « C'est fait, vérifier » | idem, checklist structurée + légende |
| `stage.problems` | note rouge | carte « À corriger avant de relancer » |
| `stage.instructions_fr` | bloc texte | checklist `<ol>` (repli paragraphe) + texte brut dans Détails techniques |
| `stage.journal` / `liveActions` (`actionsTable`) | toujours visible | « Avancement » (live, liste compacte) + table complète dans Détails techniques |
| Wizard guidé : `POST wizard/draft` (brouillon / re-rédaction avec réponses), `reqId`, questions, erreurs | sous-carte | sous-flux de l'étape 6, primaire contextuelle, JSON du brouillon dans Détails techniques (+ Copier) |
| `POST guided/abandon` + modale danger | bouton danger sous le run | lien texte dans la barre d'actions, modale danger conservée |
| Écran succès (domaine, agent_id, tool_id) + `Nouveau domaine guidé` | carte | écran succès 3.5 (ids + Et maintenant + 2 actions) |
| Bouton `Rafraîchir` quand `running` sans job local (reprise après reload) | ghost | ghost small `Actualiser l'état` dans la barre d'actions de l'état running sans job |
| `POST probe` + `pollJob` + rapport + Copier | onglet Sonde | Avancé > Sonde |
| `POST plan` (dry-run) + avertissements + compteurs + table d'actions | Nouveau domaine | Avancé > Mode expert, carte 2 |
| `POST execute` + modale (étapes PLANNED) + journal live + `manualChecklist` + runbook + toast échecs | Nouveau domaine | Avancé > Mode expert, carte 3 |
| Segmenté `Dataset existant / Table SQL à importer` + champs source | Nouveau domaine | carte 1 (inchangé) |
| Wizard libre : dataset de profil, `Générer`, questions (select/input), `Régénérer`, JSON + Copier, invalidations | section Wizard | carte « Wizard sémantique (optionnel) » entre 1 et 2 |
| `GET/POST hub/prompt` (chemin contraint, Charger, Enregistrer, erreurs) | Prompts | Avancé > Fichiers du hub, carte 1 |
| `GET/POST hub/capabilities` (Charger, JSON, `problems` de validation, Valider et enregistrer) | Prompts | Avancé > Fichiers du hub, carte 2 |
| Thème clair/sombre (`localStorage afc.theme`) | header | header (inchangé) |
| Bannière `no_backend` | toutes pages | toutes pages |
| Modale : Échap, clic scrim | shell | shell (inchangé) |

Aucune route n'est ajoutée ni retirée. Aucun payload ne change.

---

## 7. Guide d'implémentation (pour l'ingénieur)

### 7.1 À ne PAS toucher
`callApi`, `pollJob`, `toast`, `openConfirm`/`closeModal` (ajouter seulement un paramètre optionnel
`bodyHtml` déjà libre), `loadDatasets`, `datasetOptions`, `guidedErrorText`, `applyGuidedRun`,
`loadGuidedCurrent`, `startGuided`, `runGuidedStage`, `refreshDatasetsAfterInfra`,
`verifyGuidedStage`, `startGuidedWizard`, `gatherGuidedWizardAnswers`, `abandonGuidedRun`,
`confirmCapabilityToggle` (corps de modale réécrit seulement), `openCapabilityRemoval` (texte
seulement ; après succès : `S.tab = "run"` au lieu de `selectTab("guided")`), toute la section
Nouveau domaine (`invalidateDomainPlan`, `specFingerprint`, `wizardFingerprint`,
`invalidateWizardDraft`, `domainField`, `wireDomain`, `buildSpec`, `planDomain`, `confirmExecute`,
`executeDomain`, `startWizard`), toute la section Prompts, `startProbe`, `bindInput`, `field`,
`fieldRaw`, `inputEl`, `errorText`, `applyTheme`/`toggleTheme`, le guard `REMOVAL_DANGER_STAGES`.

### 7.2 À restructurer
1. **`body.html`** : nav -> `Mes agents` (`data-tab="home"`), `Parcours en cours`
   (`data-tab="run"`, `hidden` par défaut, id `afcTabRun`), `Avancé` (`data-tab="probe"` par
   défaut) ; ajouter `<nav class="afc-subtabs" id="afcSubtabs" hidden>` avec `probe`/`expert`/`hub`.
   Garder header, toast, modale. Supprimer le commentaire des 5 écrans, lister les nouveaux.
2. **Routage** : `selectTab(tab)` : `home` | `run` | `probe` | `expert` | `hub`. `renderActive`
   mappe `home -> loadOverview/renderHome`, `run -> loadGuidedCurrent/renderRun`,
   `probe -> renderProbe`, `expert -> renderDomain`, `hub -> renderPrompts`. La nav principale marque
   `Avancé` actif pour les 3 derniers et affiche la sous-rangée. `afcTabRun` est montré quand
   `S.guided.run && S.guided.run.status === "active"` (fonction `syncNav()` appelée après chaque
   `applyGuidedRun` et dans `selectTab`). Boot : `loadGuidedCurrent()` en premier (pour le bandeau et
   l'item de nav), puis `selectTab("home")`.
3. **`STAGE_UX`** : objet constant `{ stageKey: { phase, title, sentence(ctx), objects(ctx),
   primary, modalTitle(ctx), guarantee, wait } }` pour les 25 clés, où `ctx = { spec, names,
   captured, removal, stage }`. `PHASES_CREATE` / `PHASES_REMOVAL` = tableaux `{label, keys[]}`.
   Repli : si une clé manque (évolution backend), utiliser `stage.title_fr` / `detail_fr` et la
   primaire générique `Lancer`. Ne JAMAIS planter sur une clé inconnue.
4. **`derivedNames(spec)`** (section 3.2) : fonction pure, testable à la main dans la console du
   navigateur. Utiliser `spec.zone_name` si présent.
5. **`renderRun(run)`** remplace `renderGuided` : `run == null` -> `renderStartForm()` ;
   `run.status === "done"` -> `renderSuccess(run)` ; sinon `renderRail(run) + renderStage(run)`.
   `renderStage` applique l'anatomie 3.0 ; les branches d'état restent celles de
   `renderGuidedStage` (mêmes conditions `ready/failed/waiting_user/running/pending`, mêmes ids de
   boutons `gdRunStage`, `gdVerify`, `gdRefreshRun`, `gdAbandon`, `gdWizardDraft`, `gdWizardRedraft`,
   `.gd-wizard-answer`) pour que `wireGuidedRun` reste valide tel quel.
6. **`confirmGuidedStageRun`** : construire le corps de modale avec `STAGE_UX` (phrase + `.objects`
   + garantie). Pour les étapes de suppression, les objets viennent de
   `run.state.removal.inventory.stages[key]` (et `hub_paths` pour `hub_cleanup`), plus `protected`
   sur `delete_datasets` ; conserver `danger: dangerous` et les libellés `Supprimer` / `Relancer`.
7. **Objets « créés » sur l'écran de succès** : `derivedNames` + `captured` (`model_id`, `tool_id`,
   `agent_id`).
8. **Checklist** : `splitInstructions(text)` -> `{ items: [], footer: "" }` (regex
   `/\n(?=\d+\.\s)/`, dernier item commençant par « Clique sur C'est fait » ou contenant « C'est
   fait » déplacé en `footer`). Repli : `items.length <= 1` -> paragraphe.
9. **`<details>`** : `S.ui = { details: {} }` ; sur `toggle` (événement natif) on stocke
   `open` par `stageKey` ; après `setMain`, `restoreDetails()` relit la map. Échec -> ouvert si
   aucune valeur stockée.
10. **Écran 0 live preview** : NE PAS re-rendre tout le formulaire à chaque frappe (perte de focus,
    leçon du mode expert). `bindInput` met à jour `S.guided.form` puis appelle
    `updateNamesPreview()` qui écrit `textContent` dans des `<span data-name="zone">` etc.
11. **`renderHome`** remplace `renderOverview` : même chargement `GET state` ; lignes d'agents ;
    bandeau de reprise lu dans `S.guided.run` (déjà chargé au boot ; s'il n'est pas encore chargé,
    afficher sans bandeau puis re-rendre quand `loadGuidedCurrent` termine, si `S.tab === "home"`).
    Conserver les ids `data-cap-toggle`, `data-cap-remove`, `ovRefresh`, `ovRetry` et `S.overview.flash`.
12. **Mode expert** : `renderDomainNow` garde ses ids (`dmDomain`, `dmSeg`, `dmBaseSelect`, ...,
    `dmPlan`, `dmExec`, `wzProfile`, `wzDraft`, `wzRegen`, `wzCopy`) ; seul l'ordre des sections et
    les titres changent. Le bouton `Planifier (dry-run)` devient `Simuler (dry-run)`.
13. **`style.css`** : ajouter les tokens 4.9, les composants `.afc-nav-dot`, `.afc-subtabs`,
    `.rail*`, `.stage*`, `.objects`, `.afc-todo`, `.afc-progress`, `.afc-details`, `.agent-row`,
    `.resume-banner`, `.success*`. Retirer `.gd-step` (liseré gauche) et le focus orange des champs.
    Conserver le reste (`.afc-btn`, `.afc-chip`, `.afc-table`, `.afc-pre`, `.afc-note`, `.afc-q`,
    `.afc-manual`, `.afc-seg`, `.afc-chk`, `.afc-modal*`, `.afc-toast`). Responsive 820px : rail en
    rangée, grille 1 colonne, barre d'actions en colonne.

### 7.3 Pièges
- **ES5** : pas de template literals, `const/let`, fonctions fléchées, `Object.assign`, spread,
  `includes`. `NodeList.forEach` est déjà utilisé (OK dans les navigateurs ciblés) ; préférer
  `Array.prototype.forEach.call` pour les nouveaux appels.
- **Re-rendu par polling (1,5 s)** : tout état d'UI local (details ouverts, scroll du journal, champs
  de réponse wizard en cours de saisie) doit vivre dans `S` ou être restauré après `setMain`. Les
  réponses wizard sont déjà synchronisées à `oninput` dans `S.guided.wizard.answers` : rendre les
  inputs avec `answers[qid]` (déjà le cas).
- **`stage.status === "running"` sans job local** (reload pendant un build) : garder le bouton
  `Actualiser l'état` (`gdRefreshRun`) ; le serveur auto-guérit via `heal_interrupted` seulement
  au redémarrage du backend, sinon il faut recharger pour voir la fin.
- **Étapes sautées** : `status === "done"` avec `journal[-1].status === "SKIPPED"` et détail
  « déjà satisfait » -> chip `Déjà faite` dans le rail (ne pas inventer un statut serveur).
- **Suppression, `detail_fr` réécrit par le serveur** : ne plus parser le texte « SUPPRIMER : » ;
  lire `state.removal.inventory`. Garder `detail_fr` dans Détails techniques.
- **`openCapabilityRemoval`** lit `#capRemoveTyped` DANS la modale : conserver l'id et l'`input`
  dans `bodyHtml`.
- **Une seule primaire par écran** : sur l'écran de parcours, le CTA « Ajouter un agent » de
  l'accueil n'existe pas ; sur l'accueil avec run actif, `Reprendre` est la primaire et
  `Ajouter un agent` passe en ghost (le serveur refuserait de toute façon : `active_run_exists`).
- **Charte** : pas de liseré vertical orange comme marqueur d'état ; une seule title-bar visible
  par colonne du rail ; orange = eyebrow, title-bar, ligne courante (18x2), primaire, curseur de
  progression. Les chips ACTIF restent vertes, pas orange. Aucune ombre hors `--elev-1` de la modale.
- **Textes** : aucun tiret cadratin/demi-cadratin, y compris dans les `STAGE_UX` et les
  commentaires ; les apostrophes françaises `'` sont échappées dans les chaînes JS simples (style
  existant `\'`).
- **Vérification avant livraison** : (1) `node --check script.js` ; (2) simulateur
  `dev-harness/console_sim.py` : parcours création jusqu'à l'étape wizard, parcours suppression
  jusqu'à `delete_datasets`, mode expert plan + execute, prompts load/save, sonde ; (3) grep
  des points de code U+2013 et U+2014 (`grep -P "[\x{2013}\x{2014}]"`) sur les 3 fichiers = 0 ;
  (4) passage de `charte-orange-reviewer` sur `style.css`.
