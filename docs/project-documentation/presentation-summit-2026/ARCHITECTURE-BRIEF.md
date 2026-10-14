# OWIsMind - Contexte de projet complet pour la préparation d'un talk Dataiku Summit 2026

> **Ce document est autoportant.** Il est destiné à être collé dans une conversation Claude qui n'a AUCUN
> accès au code du projet et qui devra produire des slides et aider à écrire un discours. Tout ce qu'il faut
> savoir pour comprendre le produit, son architecture, ses briques et leurs vrais noms est ici. Aucun renvoi
> vers un fichier, aucun lien interne.
>
> **Règle de rédaction non négociable, héritée du projet** : jamais de tiret cadratin ni de tiret
> demi-cadratin, nulle part, ni ici ni dans les livrables produits à partir d'ici. Trait d'union,
> deux-points, virgule ou parenthèses uniquement.
>
> **Règle de véracité** : tout ce qui suit est vérifié dans le code et la mémoire du projet. Aucune métrique
> business, aucun gain de productivité, aucun nom de client n'est avancé. Là où un chiffre manquait, un
> marqueur `[À CHIFFRER PAR SAÏD]` est laissé au lieu de combler.

---

# PARTIE A - LE PROJET

## A.1 En une phrase

**OWIsMind est l'assistant de données interne d'Orange Wholesale International : un analyste en
libre-service, construit de bout en bout sur Dataiku, qui répond à une question métier posée en langage
naturel et montre le reçu derrière chaque chiffre, parce que la confiance est câblée dans l'architecture et
non promise dans un prompt.**

Version anglaise : *OWIsMind is a self-serve AI data analyst, built end to end on Dataiku, that answers a
business question in plain language and shows the receipt behind every figure, because trust is wired into
the architecture, not promised in a prompt.*

## A.2 Le problème de départ

Un commercial demande combien un compte a facturé cette année. Le chiffre existe, il est dans la base. Il
n'est simplement pas accessible : écrire le SQL est une compétence rare côté métier, donc les gens attendent
un analyste, parfois des jours, pour un seul chiffre. Et quand une IA répond vite, on ne peut pas mettre
dans un comité de direction un chiffre qui a peut-être été inventé. Le recadrage qui structure tout le
projet : **le difficile n'est pas de générer la réponse, le difficile est la confiance.**

Le domaine est réellement piégé, et deux exemples le prouvent : on ne somme jamais à travers les scénarios
(additionner de l'actuel et du budget ne veut rien dire), et on ne retombe jamais par défaut sur le niveau
d'offre le plus technique, parce que les lignes de budget n'ont pas cette valeur et qu'un total basculerait
silencieusement à zéro. Un bug invisible, exactement le genre qui fait perdre confiance définitivement.

## A.3 Qui l'utilise, sur quelles données

Utilisateurs : responsables commerciaux, responsables de développement business, dirigeants. Des gens
pressés qui veulent une réponse nette et fiable, pas un cours.

Deux domaines de données sont aujourd'hui servis par un agent spécialiste :

| Domaine | Jeu de données | Volume | Ce qu'on y mesure |
|---|---|---|---|
| Revenus | `DRIVE_Revenues` | environ 175 800 lignes, 20 colonnes | le montant en euros (`amount_eur`), sommé avec un filtre de scénario |
| Tickets d'incidents | `TroubleTickets_year` | environ 83 700 lignes, 21 colonnes | le nombre de tickets (comptage distinct) et la durée de résolution en minutes |

Sur les revenus, la colonne `Phase` porte cinq scénarios (`ACTUALS` par défaut, plus `BUDGET`, `FORECAST`,
`Q3F`, `HLF`), la hiérarchie d'offre va du plus large au plus fin (`SolutionLine`, puis `Solution`, puis
`Product`, avec `sirano_product` comme code technique secondaire qui ne doit jamais servir de défaut),
l'axe de temps est `year_month`, on regroupe sur la clé client `diamond_id` mais on affiche `Account_name`.
Sur les tickets, il n'y a pas de colonne de scénario : chaque ligne est un incident réel.

Quatre autres domaines métier sont déclarés dans le registre sans être servis par un expert (satisfaction
client, opportunités commerciales, livraison, documents de facturation) ; la livraison a depuis été pourvue
par l'usine à agents décrite en partie D. Cette déclaration explicite n'est pas un oubli : c'est ce qui
permet à l'orchestrateur de répondre honnêtement "je n'ai pas encore d'agent pour ce domaine" plutôt que
d'inventer une réponse ou de nier que la donnée existe.

## A.4 État réel du projet, sans enjolivement

- Le produit tourne **en production** depuis mi-2026, dans une instance Dataiku, utilisé par de vrais
  utilisateurs métier. [À CHIFFRER PAR SAÏD : nombre d'utilisateurs, volume de questions]
- Deux domaines sont servis par un agent spécialiste dans le projet de production. Un troisième a été créé
  de bout en bout dans l'instance Dataiku par l'assistant guidé de l'usine à agents, par un utilisateur,
  sans écrire une ligne de code : c'est la preuve terrain de la réplicabilité.
- Le dépôt Git est la source de vérité du code des agents : on édite dans le dépôt, on colle dans les objets
  Dataiku. Ce n'est pas encore un déploiement automatisé, et c'est assumé.
- Le suivi de coût par réponse est en service. Le plafond de budget mensuel par utilisateur existe dans le
  code mais n'est pas le garde-fou actif aujourd'hui : ne pas le présenter comme tel.

---

# PARTIE B - L'ARCHITECTURE, COUCHE PAR COUCHE

## B.1 Le schéma d'ensemble, décrit pour être redessiné

Quatre bandes horizontales empilées, reliées par une flèche descendante épaisse, plus une bande détachée en
pointillés à droite pour ce qui se passe **hors conversation**.

```
  [ BANDE 1 - CE QUE VOIT L'UTILISATEUR ]
      Webapp Vue 3 servie par Dataiku   (chat + timeline live + Evidence Studio)
          |  la question + une CLE LOGIQUE d'agent (jamais un identifiant brut)
          v
  [ BANDE 2 - LE GARDIEN ]
      Backend Flask du plugin Dataiku : resout la cle contre une whitelist
      serveur, lance le run dans un worker, stocke tout en SQL direct
          |  appel de l'agent via le LLM Mesh
          v
  [ BANDE 3 - LE CHEF D'ORCHESTRE ]
      OWIsMind_orchestrator (Code Agent LangGraph) : il RAISONNE et ROUTE.
      Il ne detient AUCUNE donnee metier.
          |                        |                          |
          | lecture rapide         | chiffre calcule          | rendu
          v                        v                          v
     attribute_lookup      sous-agents specialistes     show_chart /
     (valeur exacte,       SalesDrive_revenue_expert     show_table /
      1 seconde)           CSSO_Trouble_Tickets_Expert   show_kpi
                                   |  une question naturelle, deja ANCREE
                                   v
  [ BANDE 4 - LE CERVEAU SQL ]
      Semantic Model Query tool -> le modele semantique du domaine :
      c'est LUI qui ECRIT et EXECUTE le SQL, en lecture seule  ->  PostgreSQL

  [ BANDE DETACHEE, EN POINTILLES - DESIGN TIME, HORS CONVERSATION ]
      Flow Dataiku, 3 recettes Python par domaine qui FABRIQUENT la connaissance :
        profile       = le sens metier de chaque colonne
        value index   = toutes les valeurs exactes, pour ancrer les mots tapes
        value catalog = les alias et suggestions
```

Trois idées à faire ressortir sur le dessin : **l'orchestrateur ne détient aucun chiffre**, **c'est le
modèle sémantique qui écrit le SQL**, **la connaissance du domaine est fabriquée en amont, pas improvisée
en direct**.

## B.2 La webapp (ce que l'utilisateur touche)

Application **Vue 3 compilée avec Vite** en fichiers statiques que Dataiku sert directement, packagée dans
un **plugin Dataiku** avec son backend. Aucune infrastructure web à côté, aucun serveur à exploiter.

Ce qu'elle offre, et qui compte pour le récit :

- **Un chat multi-tours** : l'historique de la branche courante est réassemblé côté serveur et transmis à
  l'agent, donc la conversation a une vraie continuité.
- **Un arbre de conversation** : éditer une question passée crée une branche, les versions d'un tour sont
  conservées, et le contexte envoyé à l'agent est tronqué à la branche active.
- **Une timeline d'exécution live**, avec des libellés humains ("analyse de la question", "interrogation
  des données", "mise en forme du résultat"), et pas un simple spinner.
- **Un panneau Evidence Studio** à droite, avec des onglets : la preuve d'abord, puis les artefacts produits
  (indicateur, graphique, tableau), puis l'exploration de la donnée source.
- **Un explorateur de données source** : l'utilisateur ouvre le jeu de données brut de l'agent, le filtre
  avec des puces, le trie, le cherche (recherche insensible à la casse et aux accents), et calcule ses
  propres agrégats, exécutés par la base.
- **Le contexte d'écran** : ce qui est affiché à l'écran (le graphique courant, ou une vue filtrée que
  l'utilisateur a façonnée) peut être transmis à l'agent, avec bandeau de consentement et une trace
  persistée sous le message, pour que "explique-moi ce graphique" ou "ajoute le forecast" fonctionne.
- **Le confort produit** : français et anglais, thème clair et sombre, un pouce en haut ou en bas par
  message avec motifs et commentaire, arrêt de génération, sélecteur de mode de qualité par réponse, et une
  ligne sous chaque réponse indiquant les jetons d'entrée, les jetons de sortie et le coût estimé.
- **Un espace d'administration** : sélection des agents autorisés, fiche d'affichage de chaque agent
  rédigée par l'administrateur, choix des jeux de données que l'agent expose à l'exploration.

## B.3 Le backend (le gardien)

Backend **Flask fourni par le plugin**, monté sous un préfixe d'API unique. Ses responsabilités :

- **L'identité** est toujours résolue à partir des en-têtes du navigateur authentifié par Dataiku, jamais
  depuis le corps de la requête.
- **La whitelist d'agents est côté serveur.** Le frontend ne reçoit et n'envoie que des **clés logiques
  opaques** avec un libellé : jamais un identifiant d'agent, jamais un nom de projet, jamais une table,
  jamais une requête. La résolution clé vers agent se fait côté serveur et est revalidée contre la liste
  vivante des agents du projet.
- **Le lancement de l'exécution** : l'agent tourne dans un worker en arrière-plan, avec un plafond
  d'exécutions simultanées (huit) et une échéance par mode.
- **Le transport est du polling, pas du streaming par flux d'événements.** Le proxy interne de Dataiku met
  en tampon un flux long, donc les événements arriveraient tous d'un coup. Le frontend interroge donc le
  serveur toutes les demi-secondes avec des requêtes courtes que le proxy ne bufferise jamais. C'est le
  même contournement que l'application de production qui a précédé OWIsMind.
- **Le stockage est du SQL direct** sur PostgreSQL, sans Flow au runtime : conversations et messages,
  SQL généré, artefacts rendus, événements d'usage, consommation mensuelle, retours utilisateurs, traces
  d'exécution. Requêtes paramétrées, préfixe de projet sur les tables, aucune route SQL générique exposée.
- **Les routes de preuve et d'exploration** (`evidence` et `source`) sont en lecture seule, limitées par un
  délai maximum d'exécution, plafonnées en lignes, et cadrées sur le propriétaire de la conversation.

## B.4 L'orchestrateur

`OWIsMind_orchestrator` est un **Code Agent Dataiku écrit en LangGraph**, avec le motif "les sous-agents
sont des outils". C'est le seul composant qui rédige le texte lu par l'utilisateur.

**Ce qu'il fait dans un tour** : il raisonne, puis, dans le même tour, soit il appelle l'outil de lecture
rapide pour aller chercher une valeur, soit il délègue à un spécialiste pour obtenir un chiffre calculé,
soit il rend le dernier résultat (graphique, tableau, indicateur) et écrit l'analyse.

**Ses outils** : `ask_revenue_expert` et `ask_tickets_expert` (les spécialistes), `attribute_lookup` (la
lecture rapide de valeur), `show_chart`, `show_table` et `show_kpi` (le rendu dans le panneau),
`current_date`, une note de progression pour prévenir l'utilisateur avant un appel lent, et le rappel d'un
résultat déjà obtenu plus tôt dans la conversation (instantané, là où un appel de spécialiste prend trente
secondes à une minute).

**Sa persona** est un prompt système explicite, versionné, qui porte quatre choses : le ton (un collègue
net et concis, jamais un robot d'entreprise), la langue (répondre toujours dans la langue du dernier
message), **le pare-feu d'honnêteté** (section C.3), et le contrat de sortie (les données vont dans le
panneau, le texte est une analyse ; jamais de tableau markdown dans la bulle de chat ; tout montant formaté
avec séparateurs de milliers et symbole euro ; jamais un nombre nu, toujours précédé de son périmètre).

**Son registre de capacités** décrit, pour chaque domaine servi : l'agent spécialiste à appeler, le domaine
métier couvert, une description destinée au raisonnement de routage, les libellés humains des étapes qui
apparaîtront sur la timeline, le jeu de données que la recherche rapide doit interroger, et un drapeau
d'activation. Ce registre est lu au démarrage depuis un magasin de configuration partagé (la project
library de Dataiku), avec un repli embarqué dans le code si la lecture échoue. **Ajouter un domaine validé,
c'est une entrée de plus dans ce registre.**

**Les modes de qualité.** L'utilisateur choisit par réponse : `smart` (le défaut, économique et rapide,
Gemini 3.1 Flash-Lite), `pro` (Gemini 3.5 Flash), `claude` (Claude Sonnet 5). Un seul modèle pilote tout le
tour, sans escalade ni bascule en cours de route, et le mode est propagé au sous-agent. Détail important :
**l'outil qui écrit réellement le SQL reste sur le modèle fort dans tous les modes**, pour que la résolution
des colonnes et des niveaux d'offre soit constante quel que soit le mode choisi. Les trois modèles sont
exposés par une seule connexion LLM Mesh.

## B.5 Les sous-agents spécialistes

Un expert par domaine de données. Ils sont eux aussi des **Code Agents LangGraph**. Point clé pour le talk :
**le deuxième expert est le même moteur que le premier**, corps de code identique ; seuls l'en-tête de
configuration et quelques textes métier changent.

Chaque spécialiste suit toujours la même séquence en quatre temps :

1. **COMPRENDRE** : un appel de modèle, contraint à répondre en JSON strict, transforme la phrase en
   intention structurée (quelle mesure, quelle période, quels filtres). Le prompt de cette étape est
   **généré à partir du profile du jeu de données**, donc il parle le vocabulaire réel des colonnes.
2. **ANCRER** : le spécialiste interroge en SQL, en lecture seule, l'index de valeurs du domaine pour
   transformer les mots tapés par l'humain en valeurs exactes de la base. Trois passes : correspondance
   exacte, puis approchée, puis en dernier recours une comparaison de similarité. Cette étape n'est **pas**
   un outil externe : c'est du SQL en ligne, c'est délibéré, et c'est la brique la plus sous-estimée du
   système.
3. **INTERROGER** : il ne rédige pas le SQL final. Il transmet une question en langage naturel, désormais
   parfaitement ancrée (valeurs exactes, scénario, période), à l'outil de requête sémantique. Un repli
   déterministe existe pour l'échec **technique** uniquement, jamais pour un résultat vide.
4. **METTRE EN FORME** : les chiffres sont formatés par du code, pas par un modèle, chaque nombre cité est
   vérifié, et la réponse commence obligatoirement par une ligne de périmètre. Les questions du type "que
   contiennent ces données" sont répondues à partir du profile, avec zéro requête SQL.

Le spécialiste renvoie un statut machine unique (prêt, besoin de précision, hors périmètre, pas de donnée,
erreur) que l'utilisateur ne voit jamais mais dont dépend le comportement de l'orchestrateur. Et **chaque
requête réellement exécutée laisse une trace** contenant le texte SQL, un indicateur de succès **observé**
(et non déclaré), le nombre de lignes, et pour la requête retenue les colonnes et les lignes.

## B.6 L'outil de lecture rapide

Pour "quel est le code de tel compte" ou "qui gère ce client", pas besoin d'un calcul. L'orchestrateur
dispose d'un **outil Python personnalisé** qui fait une recherche sur tout le jeu de données, insensible à
la casse et aux accents, sur les colonnes texte, et renvoie les valeurs correspondantes. Quand rien ne
correspond, il propose des alias proches à partir du catalogue de valeurs. Lecture seule, borné, avec un
cache court. Résultat en une seconde plutôt qu'en une minute, et le modèle ne passe jamais un nom de table :
il passe un **domaine logique** que l'orchestrateur résout côté serveur.

## B.7 Le modèle sémantique, le vrai cerveau SQL

C'est un **objet Dataiku**, pas du code maison, et c'est la brique que ce public connaît le moins. Il est
interrogé par un **outil Dataiku de type Semantic Model Query**, un par domaine, lié à un modèle par
domaine (on n'ajoute jamais une source à un modèle existant).

Ce que contient le modèle des revenus :

- **Trois entités logiques** (l'enregistrement de revenu, le compte client, l'offre commerciale) qui
  pointent toutes vers **une seule table physique** : les relations déclarées documentent des clés
  partagées, mais les instructions de génération SQL **interdisent toute jointure**.
- **Une mesure principale** (le revenu total en euros), des **filtres nommés**, des **requêtes de
  référence**, un **glossaire métier**.
- **Les règles SQL du domaine**, qui sont exactement les garde-fous métier : le scénario `ACTUALS` par
  défaut, la priorité des niveaux d'offre, l'interdiction de retomber sur le code technique secondaire, le
  regroupement sur la clé client avec affichage du nom lisible.

La configuration de l'outil compte aussi pour le récit : le mode agent est **désactivé**, donc c'est un
pipeline SQL linéaire et rapide, pas un agent multi-étapes ; la génération SQL tourne sur un modèle fort ;
un modèle d'embedding sert à la correspondance de valeurs ; et surtout, **les jeux de données sont lus au
nom de l'utilisateur qui pose la question**, donc les permissions Dataiku s'appliquent telles quelles, sans
couche d'autorisation parallèle à maintenir.

Le modèle des tickets a sa propre configuration : mesure par défaut en comptage distinct, durée moyenne de
résolution en minutes.

## B.8 Le Flow : la connaissance est fabriquée en amont

Trois recettes Python par domaine, exécutées **en design-time** dans le Flow Dataiku, jamais pendant une
conversation. Un scénario de rafraîchissement les rejoue ; les agents lisent toujours la version vivante,
donc il n'y a aucun cache à invalider et aucun recollage de code à faire quand la donnée bouge.

| Ce que la recette produit | Ce que c'est | Qui le lit au runtime |
|---|---|---|
| **profile** | la fiche d'identité métier du jeu de données : le sens de chaque colonne, son rôle (mesure, dimension, axe de temps, identifiant, texte libre), ses synonymes, la mesure et l'axe de temps élus | le sous-agent, pour comprendre la question et pour répondre aux questions sur les données elles-mêmes |
| **value index** | toutes les valeurs distinctes des colonnes texte groupables, avec leur forme normalisée (minuscules, accents retirés, espaces normalisés) et leur nombre d'occurrences | le sous-agent, pour l'ancrage, en SQL |
| **value catalog** | un catalogue plus riche d'alias et de suggestions | l'outil de lecture rapide, en repli |

Deux détails qui font la crédibilité technique :

- Le profile se construit en **deux passes** : une passe déterministe sans aucun modèle (schéma,
  statistiques, valeurs à faible cardinalité), puis une passe d'enrichissement par un modèle fort qui
  rédige les descriptions et propose les rôles. **Les corrections humaines sont appliquées en dernier et
  gagnent toujours.** Et seules des métadonnées agrégées atteignent le modèle, jamais des lignes brutes.
- Les trois recettes sont **agnostiques du jeu de données** : elles lisent leur entrée et leur sortie du
  câblage du Flow, pas de constantes dans le code. Le même code sert les deux domaines, à l'octet près.

---

# PARTIE C - LES MÉCANISMES CLÉS

## C.1 Le trajet complet d'une question

C'est le meilleur outil pédagogique du talk. Question : *"Quel chiffre d'affaires ce compte a-t-il réalisé
cette année ?"*

1. **L'utilisateur tape sa question** et choisit éventuellement un mode de qualité.
2. **Le backend identifie l'utilisateur** via sa session Dataiku, vérifie que l'agent demandé est autorisé,
   enregistre le message, lance l'exécution dans un worker en arrière-plan.
3. **L'orchestrateur raisonne** : aucun chiffre en sa possession, seulement un catalogue de ce que ses
   spécialistes savent faire. C'est du revenu, il délègue à l'expert revenus.
4. **Le spécialiste COMPREND** : la phrase devient une intention structurée, via un appel de modèle
   contraint en JSON, avec un prompt généré depuis le profile.
5. **Le spécialiste ANCRE** : le nom tapé par l'humain devient la valeur exacte de la base, par une
   interrogation en lecture seule de l'index de valeurs. Sans cette étape, la requête serait
   syntaxiquement parfaite et rendrait zéro ligne, **silencieusement**.
6. **Le spécialiste INTERROGE** : il passe une question naturelle déjà ancrée à l'outil de requête
   sémantique. Le modèle sémantique écrit le SQL et l'exécute en lecture seule.
7. **Le spécialiste MET EN FORME** : chiffres formatés par du code, réponse ouverte par une ligne de
   périmètre (scénario, période, entité, devise).
8. **L'orchestrateur rend et rédige** : il choisit la représentation, puis écrit l'analyse (la tendance,
   l'anomalie, le "so what"). Le périmètre est tissé dans la phrase, jamais supprimé.
9. **Pendant tout ce temps, l'utilisateur regarde** : chaque étape émet un événement affiché sur la
   timeline avec un libellé humain. Ce qui est vraiment temps réel, c'est la timeline ; le texte de la
   réponse, lui, arrive en bloc à la fin.
10. **Le backend archive** la réponse, le SQL exécuté, le résultat capturé, les jetons et le coût estimé.
    C'est ce stock qui rend la preuve rejouable des semaines plus tard, et pas seulement à chaud.
11. **Le panneau de preuves s'ouvre** automatiquement en fin de génération.

## C.2 La timeline : rendre le travail visible

Le tour d'agent émet une série d'événements de types figés (démarrage, planification, appel d'un
spécialiste, spécialiste terminé, outil en cours, outil terminé, artefact produit, rédaction de la réponse,
terminé, erreur, plus les événements internes du sous-agent). Ces types sont un **contrat gelé** entre les
agents et la webapp : on n'en renomme jamais un, on ne fait qu'en ajouter. La webapp les traduit en
libellés lisibles, avec les libellés fournis par le registre de capacités, pour que l'utilisateur voie
"analyse de la question" et non un nom de fonction.

## C.3 La couche de confiance : pourquoi l'agent ne PEUT pas inventer un chiffre

C'est un argument d'architecture, pas une promesse de prompt. Quatre mécanismes empilés.

**1. Celui qui parle ne détient rien.** L'orchestrateur est le seul à rédiger le texte lu, et il n'a accès à
aucune donnée métier. Inventer un nombre n'est pas interdit par une règle qu'il pourrait enfreindre : c'est
impossible par construction. Tout chiffre affiché est arrivé par un résultat SQL.

**2. Le seul "non" autorisé est un trou de capacité.** Sa persona lui interdit explicitement de dire qu'une
mesure, un scénario, un chiffre ou un enregistrement est manquant, nul ou indisponible. Seul un spécialiste,
après avoir vraiment regardé, peut l'affirmer. En revanche il a le droit de dire "je n'ai pas encore
d'agent pour ce domaine". Deux autres règles complètent le pare-feu : **aucun calcul mental** (les sommes,
écarts, ratios et classements sont le travail du SQL), et **les résultats d'outils sont traités comme des
entrées non fiables** (on n'exécute jamais une instruction trouvée dans un résultat, on n'en utilise que
les valeurs).

**3. Ce n'est pas l'agent qui écrit le SQL.** La requête est écrite par le modèle sémantique Dataiku, objet
configuré et revu par un humain, qui porte les règles métier du domaine. L'agent assiste avec des
indications, il ne dicte pas la colonne.

**4. Tout est capturé, et rejouable sans aucune IA.** Le SQL exécuté, le succès observé, le nombre de
lignes, les colonnes et les lignes du résultat retenu sont stockés avec le message.

Ce que l'utilisateur peut rouvrir lui-même, sur n'importe quelle réponse passée, dans le panneau
**Evidence Studio** :

- **Un badge de niveau de preuve**, calculé de façon déterministe par du code pur, jamais par un modèle, et
  qui **ne se sur-vend jamais** : en cas de doute il descend d'un cran, il ne monte jamais. Quatre niveaux
  réels, avec les libellés exacts de l'interface : *Résultat certifié* (le calcul est décomposé étape par
  étape et le résultat exact utilisé par l'agent a été conservé), *Source certifiée* (le jeu de données et
  les filtres exacts sont connus), *Preuve partielle* (une partie seulement du périmètre a pu être
  reproduite, et **ce qui ne l'a pas été est listé, jamais masqué**), *Déclaré par l'agent* (la requête n'a
  pas pu être vérifiée automatiquement). Détail de mise en scène qui parle à tout le monde : **le badge
  n'est jamais vert.** Plein, pointillé, gris. L'interface elle-même refuse la fausse assurance.
- **Les filtres exacts, en puces éditables**, y compris ceux que la relecture n'a pas su reproduire.
- **Le calcul décomposé en étapes lisibles** ("source", "filtre", "regroupement", "somme", "classement"),
  traduit du SQL vers le langage métier par du code pur et testé. Ce qui n'est pas positivement compris
  devient une étape opaque affichée telle quelle, jamais une explication devinée : une explication fausse
  serait une fausse preuve.
- **Le résultat exact que l'agent a vu**, tel qu'il a été capturé.
- **Les lignes sources relues en direct dans la base**, en lecture seule, avec la mention honnête que si la
  donnée a changé depuis la réponse, ce sont les lignes d'aujourd'hui.
- **Le jeu de données brut lui-même**, filtrable, triable, cherchable, sur lequel l'utilisateur calcule ses
  propres agrégats (somme, moyenne, médiane, minimum, maximum, comptage de valeurs distinctes) exécutés par
  la base de données, **sans aucune IA**.

C'est la réponse à "d'où sortent ces vingt millions ?" : l'utilisateur ne demande pas à l'agent de se
justifier, il ouvre le panneau et va voir.

## C.4 Sûreté et gouvernance (à avoir en poche pour les questions)

Lecture seule partout sur les chemins de preuve et d'exploration (transaction en lecture seule et délai
maximum d'exécution), limites de lignes systématiques, jamais de comptage non borné, plafond d'exécutions
simultanées, échéance par exécution, requêtes paramétrées, accès aux données au nom de l'utilisateur
appelant, whitelist d'agents côté serveur, aucune valeur métier codée en dur dans la logique des agents
(tout vient du profile, de l'index de valeurs, du catalogue ou d'un correctif humain explicite).

---

# PARTIE D - CE QUI EST GÉNÉRIQUE ET RÉPLICABLE

Le système n'est pas spécifique aux revenus, et il y a deux preuves concrètes : le second domaine tourne sur
le **même moteur de sous-agent** (deux noms de jeux de données changés), et un troisième domaine a été créé
de bout en bout dans l'instance Dataiku par l'assistant guidé, par un utilisateur, sans écrire de code.

**La recette pour brancher un nouveau domaine de données :**

1. Une table source sur une connexion SQL.
2. Les trois recettes de connaissance appliquées à cette table (profile, index de valeurs, catalogue). Elles
   sont agnostiques du jeu de données : le même code sert tous les domaines.
3. Un modèle sémantique dédié : entités, mesure par défaut, filtres nommés, glossaire, règles SQL du métier.
4. Un outil de requête sémantique lié à ce modèle.
5. Un Code Agent spécialiste : une copie du moteur existant, deux noms de jeux de données changés.
6. Une entrée dans le registre de capacités que l'orchestrateur lit au démarrage.

**Industrialisé**, cet enchaînement est piloté par une console : un **assistant guidé de treize étapes**,
dont chaque étape est **vérifiée contre Dataiku avant de passer à la suivante** (une étape qui ne peut pas
être prouvée ne fait jamais avancer le compteur, et un run interrompu reprend là où il s'était arrêté). La
machinerie est prudente par conception : simulation par défaut, opérations idempotentes, jamais de
supposition qu'un objet est absent quand l'appel de vérification lui-même a échoué. Ce qui ne peut pas être
confirmé par une sonde de capacités sur l'instance **dégrade en checklist manuelle de deux minutes** plutôt
que de deviner un schéma non documenté. Et c'est **réversible** : la console sait désactiver une capacité en
un clic, ou la supprimer proprement, avec inventaire préalable, vérification d'identité avant chaque
suppression, et vérification d'absence après.

**Ce qu'il faut fournir pour que ça marche, et c'est là qu'est le vrai travail :**

- **Le métier expliqué** : que représente une ligne, ce qu'il ne faut jamais additionner, le scénario par
  défaut, les colonnes qu'on affiche par opposition aux clés techniques sur lesquelles on regroupe.
- **Le jeu de données décrit** : le rôle de chaque colonne, ses synonymes métier. Le profil automatique
  donne un premier jet, un humain le corrige, et la correction humaine gagne toujours.
- **Les bons outils donnés à l'agent** : un modèle sémantique par domaine, un outil de requête lié à ce
  modèle, et la liste des colonnes que la recherche rapide a le droit de parcourir.

**Ce qui demande du travail, honnêtement** : la curation du modèle sémantique est le poste principal, c'est
là que se jouent les pièges métier et une règle manquante produit un chiffre plausible mais faux ; l'index
de valeurs doit vivre sur la même connexion SQL que la source, sinon l'ancrage ne peut pas se faire en SQL ;
le texte vers SQL est sensible à la casse et aux accents, donc l'étape d'ancrage n'est pas optionnelle ; le
code des agents vit dans un dépôt Git et se recolle dans les objets Dataiku ; deux environnements Python
cohabitent, celui du backend de la webapp et celui des Code Agents.

---

# PARTIE E - CE QUE DATAIKU APPORTE CONCRÈTEMENT

Formulation utile sur scène : **la question n'est pas "qu'est-ce qu'on a construit", c'est "qu'est-ce qu'on
n'a PAS eu à construire".**

| Ce qu'on n'a pas construit | Ce que Dataiku fournit |
|---|---|
| Une passerelle vers les fournisseurs de modèles | Le **LLM Mesh** : une connexion, plusieurs modèles (Gemini et Claude ici), aucune clé d'API dans notre code, et la comptabilité des jetons remontée avec la réponse |
| Un runtime d'agents | Les **Code Agents** : nos agents LangGraph sont des objets Dataiku, appelés comme on appellerait un modèle, avec leur environnement Python dédié |
| Un moteur de texte vers SQL | Le **modèle sémantique** et l'outil de requête associé : la génération SQL est un objet configuré et gouverné, pas une bibliothèque à maintenir |
| Un catalogue d'outils pour agents | Les **agent tools** : outils Python personnalisés et outils de requête sémantique, déclarés comme objets du projet |
| Un pipeline de préparation de la connaissance | Le **Flow** : recettes Python ordinaires, scénario de rafraîchissement, lignée visible |
| Une couche d'accès aux données | Les **connexions et jeux de données** : exécution en lecture seule, aucun identifiant dans le code, et lecture **au nom de l'utilisateur qui pose la question** |
| Un hébergement web et une authentification | Le **plugin et la webapp** : Dataiku sert les fichiers statiques, héberge le backend, fournit l'identité authentifiée |
| Un magasin de configuration partagé | La **project library** : prompts et registre de capacités vivent hors du code des agents, avec un repli embarqué si la lecture échoue |

Le seul contournement à assumer devant des ingénieurs : le streaming par flux d'événements était mis en
tampon par le proxy interne, donc l'agent tourne dans un worker et le frontend interroge le serveur toutes
les demi-secondes. Ce qui est réellement live, c'est la timeline, pas le texte mot à mot.

---

# PARTIE F - MATÉRIEL POUR LE TALK

## F.1 Le cadre imposé de la présentation

- **Événement** : Dataiku Summit. Public = clients et utilisateurs Dataiku d'autres entreprises (data
  scientists, data engineers, solution designers, décideurs data). Ils connaissent Dataiku, ils ne
  connaissent pas OWIsMind, et leur vraie question est "est-ce que je pourrais faire pareil chez moi ?".
- **20 minutes à deux**, très court. Déroulé arrêté, à ne pas rediscuter : (1) la collègue présente la
  donnée et le problème métier ; (2) elle raconte d'où vient l'idée, de Cooper, une solution construite
  avant, à OWIsMind ; (3) elle pose le périmètre, on a commencé par les revenus, uniquement les revenus ;
  (4) Saïd commente en direct une **vidéo enregistrée** du produit ; (5) Saïd enchaîne sur **3 slides
  maximum**, dans cet ordre : *How OWIsMind works*, puis "peut-on faire confiance à ce que dit l'agent ?",
  puis "peut-on faire ça avec MES données ?" ; (6) clôture sur un QR code vers son site.
- **L'altitude** : ni pitch business creux, ni exposé jargonneux. Chaque brique nommée avec son vrai nom,
  son rôle expliqué en une phrase qu'un non-spécialiste comprend, tout en restant crédible pour un ingénieur
  dans la salle. Interdits : les tunnels d'implémentation (noms de fonctions, chemins, signatures, numéros
  de version internes) et le vocabulaire marketing vide.
- Le deck peut partir en anglais. Saïd précisera lui-même ce qu'il veut sur chaque slide : la valeur de ce
  document est le **contexte**, pas la mise en page.

## F.2 Mini-glossaire (les termes qui seront prononcés)

| Terme | La version courte à dire au micro |
|---|---|
| **LLM Mesh** | La prise unique de Dataiku vers les modèles d'IA : on change de modèle sans changer le code. |
| **Code Agent** | Un agent écrit en Python, hébergé par Dataiku, qu'on appelle comme on appellerait un modèle. |
| **Orchestrateur** | Le chef d'orchestre : il comprend la question et distribue le travail. Il ne détient aucun chiffre. |
| **Sous-agent spécialiste** | Un expert d'un seul jeu de données. Il ne sait qu'une chose, mais il la sait vraiment. |
| **Modèle sémantique** | La carte du domaine donnée à la machine : ce que veulent dire les colonnes, et ce qu'on n'a pas le droit de calculer. C'est lui qui écrit le SQL. |
| **Ancrage (grounding)** | Traduire les mots de l'utilisateur en valeurs exactes de la base. Sans ça, la requête est parfaite et le résultat est vide. |
| **Index de valeurs** | La liste de toutes les valeurs réelles des colonnes texte, fabriquée en amont. Le dictionnaire de l'ancrage. |
| **Profile de jeu de données** | La fiche d'identité métier des données : le sens de chaque colonne, généré puis corrigé à la main. |
| **Evidence Studio** | Le panneau de preuves : filtres, calcul décomposé, résultat exact, donnée source. Zéro IA dedans. |
| **Timeline d'exécution** | Le fil en direct de ce que l'agent est en train de faire, en langage humain. |
| **Registre de capacités** | La liste des domaines servis. Ajouter un expert, c'est une ligne de plus. |

## F.3 Analogies utilisables au micro

- **Le porte-parole et le comptable.** L'orchestrateur parle mais n'a pas les livres de comptes. Quand on
  lui demande un chiffre, il ne peut pas improviser : il est obligé d'aller chercher le comptable. Le
  mensonge n'est pas interdit, il est impossible.
- **Le ticket de caisse.** Un reçu ne vous demande pas de faire confiance au commerçant : il liste les
  lignes. Evidence Studio est le ticket de caisse du chiffre, et vous pouvez même retourner en rayon
  vérifier le prix.
- **Le traducteur et l'annuaire.** Quand vous tapez le nom d'un client à votre façon, la base ne connaît
  qu'une seule orthographe exacte. L'index de valeurs est l'annuaire qui fait la correspondance avant de
  décrocher le téléphone. Sans lui, vous appelez un numéro qui ne sonne nulle part, et personne ne vous dit
  que vous vous êtes trompé.

## F.4 Repères pour les trois slides

**Slide 1, "How OWIsMind works" / "Comment OWIsMind fonctionne".** Message unique : ce n'est pas un chatbot
branché sur une base, c'est une chaîne de responsabilités où chaque brique fait une seule chose. Support : le
schéma de la partie B.1, simplifié. Les trois idées : le frontend n'envoie qu'une clé logique et tout est
résolu côté serveur ; l'orchestrateur raisonne et route vers des spécialistes et **ne détient aucun chiffre**
(ce qui prépare la slide suivante) ; le SQL est écrit par le modèle sémantique, et la connaissance du domaine
a été fabriquée en amont par des recettes du Flow.

**Slide 2, "Can you trust what the agent says?" / "Peut-on faire confiance à ce que dit l'agent ?"** Message
unique : la confiance est une couche logicielle vérifiable, pas une promesse. Support : le panneau de
preuves annoté (le badge, les filtres en puces, le résultat exact, le lien vers la donnée source). Les trois
idées : l'agent qui parle ne détient aucune donnée et le seul "non" qu'il a le droit de dire est un trou de
capacité ; tout ce qui a été exécuté est capturé et rejoué **sans aucune IA**, avec un badge qui ne monte
jamais d'un cran par optimisme ; et surtout l'utilisateur peut ouvrir la donnée source et refaire le total
lui-même. C'est la différence entre "faites-moi confiance" et "allez voir".

**Slide 3, "Can you do this with YOUR data?" / "Peut-on faire ça avec VOS données ?"** Message unique : le
moteur est générique, l'expertise est un livrable qu'on fabrique, et brancher un domaine c'est suivre une
recette, pas réécrire un produit. Support : la recette en six étapes de la partie D, en distinguant ce qui
est générique (les recettes, l'outil, le registre) de ce qui demande du métier (le modèle sémantique, le
profil). Les trois idées : le moteur du spécialiste est le même d'un domaine à l'autre ; la recette est
industrialisée par un assistant guidé qui vérifie chaque étape contre Dataiku et qui sait aussi désinstaller
proprement ; ce que vous devez apporter, c'est le métier expliqué et le jeu de données décrit, et c'est un
travail de data engineer et de data steward, pas de prompt engineer.

**Clôture.** QR code, la phrase unique répétée, un merci. Dernière phrase possible : "on n'a pas fait parler
une IA de données, on l'a rendue redevable de chaque chiffre qu'elle affiche."

**Le commentaire de la vidéo** (avant les slides) : pointer, dans l'ordre, la question posée en français
comme à un collègue ; la timeline à gauche, qui n'est pas une barre de chargement mais ce que l'agent est en
train de faire ; la réponse qui commence par son périmètre et jamais par un nombre nu ; le panneau qui
s'ouvre tout seul avec les filtres exacts, le calcul étape par étape et le résultat exact ; et enfin
l'ouverture de la donnée source pour refaire le total soi-même. Commenter l'intention, pas le pixel.

## F.5 Questions probables du public, avec une réponse courte et honnête

- **"Et si le modèle sémantique génère du mauvais SQL ?"** Ça arrive, et c'est exactement pour ça que le SQL
  exécuté est exposé et que le calcul est décomposé en clair. Les règles métier vivent dans le modèle, revues
  par un humain, pas dans un prompt jetable.
- **"Combien ça coûte par question ?"** Chaque réponse affiche les jetons d'entrée et de sortie et un coût
  estimé. Le mode par défaut est le plus économique. [À CHIFFRER PAR SAÏD : coût moyen réel par question]
- **"Combien de temps pour une réponse ?"** Typiquement trente secondes à une minute quand un spécialiste
  doit calculer. La relecture d'un résultat déjà obtenu dans la conversation est instantanée.
- **"Qui voit quoi ?"** Chaque utilisateur ne voit que ses conversations et les agents que l'administrateur
  a autorisés. Le modèle sémantique lit les données au nom de l'utilisateur qui pose la question : les
  permissions Dataiku s'appliquent, sans couche parallèle à maintenir.
- **"Combien de temps pour brancher un domaine chez nous ?"** Le câblage technique est industrialisé par
  l'assistant guidé. Le temps réel se joue sur la curation du modèle sémantique. [À CHIFFRER PAR SAÏD :
  durée observée pour le domaine créé via l'assistant]
- **"Pourquoi pas simplement du texte vers SQL directement sur la base ?"** Parce que ça échoue en silence :
  les termes de l'utilisateur ne correspondent pas aux valeurs exactes de la base, et une requête valide sur
  des valeurs inexistantes rend zéro ligne sans erreur. L'ancrage préalable et les règles métier du modèle
  sémantique sont exactement ce qui manque à un texte vers SQL nu.
- **"Combien d'utilisateurs, quel gain de temps ?"** [À CHIFFRER PAR SAÏD : adoption, volume de questions,
  gain constaté. Ne rien avancer sans chiffre vérifié.]
- **"Est-ce disponible en produit ?"** C'est un plugin interne construit sur des briques Dataiku standard.
  La démarche est reproductible, le code n'est pas distribué.
- **"Vous faites du multi-agent en parallèle ?"** L'architecture le permet et l'orchestrateur sait appeler
  plusieurs spécialistes. La vue croisée entre domaines est la suite logique, ce n'est pas ce qui est montré
  aujourd'hui.

## F.6 Les pièges : ce qu'il ne faut pas promettre sur scène

1. **Ne pas promettre l'exactitude absolue.** Le produit lui-même se refuse un badge vert. Promettre "zéro
   erreur" détruirait l'argument central, qui est la vérifiabilité, pas l'infaillibilité.
2. **Ne pas promettre le "plug and play".** Sans curation du métier, ça produit des chiffres plausibles et
   faux. Le dire renforce la crédibilité au lieu de l'affaiblir.
3. **Ne pas promettre le streaming mot à mot.** Ce qui est live, c'est la timeline. Si quelqu'un le remarque
   dans la vidéo, l'assumer.
4. **Ne pas annoncer de fonctionnalité non éprouvée en conditions réelles**, quel que soit son avancement
   dans le code.
5. **Ne pas présenter le plafond de budget par utilisateur comme actif.** Le suivi de coût par réponse, oui.
   Le blocage automatique, non.
6. **Ne citer aucun chiffre d'adoption, de gain de productivité ou de retour sur investissement** qui ne
   soit pas mesuré. Les marqueurs [À CHIFFRER PAR SAÏD] sont là pour ça.
7. **Vérifier la vidéo avant de la projeter.** Elle affiche des noms de comptes clients réels et des
   montants. Devant d'autres entreprises, il faut un jeu anonymisé, un floutage, ou une validation
   explicite. C'est le risque le plus concret de toute la présentation.
8. **Ne pas dépasser le temps.** Trois slides, environ dix minutes pour la partie de Saïd, vidéo comprise.

---

# PARTIE G - COMMENT UTILISER CE DOCUMENT

Tu es la conversation Claude qui reçoit ce brief. Tu n'as pas accès au dépôt du projet : ce document est ta
seule source de vérité sur OWIsMind, et il est volontairement complet pour que tu comprennes réellement
l'architecture avant de dessiner quoi que ce soit.

1. **Commence par comprendre, pas par produire.** Les parties A à E sont le contexte réel du projet : les
   couches, les agents, les modèles sémantiques, la webapp, les outils, la donnée. Si une slide que tu
   proposes contredit ces parties, c'est la slide qui a tort.
2. **Ta mission** : produire les slides PowerPoint de la partie de Saïd (trois slides de contenu plus une
   clôture avec QR code) et l'aider à écrire son discours en français, minuté. Saïd te précisera ce qu'il
   veut voir sur chaque slide : traite la partie F comme un point de départ solide, pas comme un cahier des
   charges figé.
3. **Le registre** : une idée par slide, un visuel dominant par slide, quatre à six lignes courtes maximum
   sur la slide elle-même. L'orateur porte le récit, la slide porte la colonne vertébrale. Le schéma de la
   partie B.1 est décrit assez précisément pour être redessiné tel quel : simplifie-le plutôt que de
   l'enrichir.
4. **Le ton** : celui d'un ingénieur qui raconte ce qu'il a construit, pas celui d'un pitch commercial.
   Chaque brique nommée avec son vrai nom, chaque rôle expliqué en une phrase qu'un non-spécialiste
   comprend. Un data scientist dans la salle doit se dire "d'accord, je vois exactement ce qu'ils ont
   fait" ; un décideur doit pouvoir suivre du début à la fin sans décrocher. Si une phrase ne satisfait
   qu'un seul des deux, réécris-la.
5. **Les interdits absolus** : aucun tiret cadratin, aucun tiret demi-cadratin, nulle part, ni dans les
   slides ni dans le discours. Aucun chiffre qui ne figure pas dans ce document ; là où tu vois un marqueur
   [À CHIFFRER PAR SAÏD], laisse-le visible dans le livrable au lieu de combler. Aucune promesse listée à la
   partie F.6.
