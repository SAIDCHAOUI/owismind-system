# OWIsMind - Script orateur (FR) - Dataiku Customer Day

> Le texte parlé, mot pour mot, que l'orateur (le porteur du projet) prononce sur scène.
> Format : 1 slide titre + 5 slides coeur + 1 slide de clôture (7 frames). Cible : environ 15 minutes.
> Ton : pitch de fondateur, accessible et vivant, professionnel et crédible, énergie de storytelling.
> Message central, le fil rouge de tout le talk : OWIsMind n'est NI une simple webapp, NI un simple
> agent. C'est un SYSTÈME (webapp + agents + recettes Flow + SQL direct), presque un produit SaaS,
> construit entièrement sur Dataiku. Le tout vaut plus que la somme des parties.
>
> Règle typographique non négociable : aucun tiret cadratin ni demi-cadratin nulle part. On utilise
> le trait d'union, les deux-points, la virgule ou les parenthèses.
>
> Convention de lecture : `[...]` = indication de jeu (pause, geste, clic), pas à prononcer.
> Budget temps par slide indiqué en tête de section. Total visé : environ 15 minutes.

---

## Slide 0 (titre) - "OWIsMind : l'analyste IA en self-service qui montre ses preuves"
**~1 min**

[Entrer calmement. Marquer une pause. Regarder la salle avant de parler.]

Bonjour à toutes et à tous. Merci d'être là.

Je vais vous raconter une histoire de quinze minutes. L'histoire d'un produit qu'on a construit
entièrement sur Dataiku, et qui s'appelle OWIsMind.

L'idée tient en une phrase : vous posez une question business en langage naturel, en français ou en
anglais, et vous recevez un chiffre, en euros, sans écrire une ligne de SQL. Et surtout, vous voyez la
preuve derrière chaque nombre. Le chiffre ET le reçu.

[Geste vers les quatre tuiles à l'écran.]

Mais je veux planter une chose tout de suite, parce que c'est le coeur de ce que je viens vous montrer.
OWIsMind, ce n'est pas juste une webapp. Ce n'est pas juste un agent. C'est un SYSTÈME. Une webapp Vue 3
servie par DSS, une couche d'agents sur le LLM Mesh, des recettes Flow qui fabriquent l'expertise, et du
SQL direct. Quatre briques Dataiku qui s'emboîtent. Le tout vaut plus que la somme des parties, et c'est
exactement cette histoire-là que je veux vous raconter.

Aujourd'hui, le domaine, c'est le revenu télécom d'Orange, sur un dataset qu'on appelle DRIVE_Revenues.

[Transition.]

Cinq temps : le problème, l'idée, le produit, une plongée technique, et où ça va ensuite. On commence
par le problème.

---

## Slide 1 (coeur 1) - "Le ping du vendredi : un chiffre qu'on attend, et qu'on n'ose pas croire"
**~2 min**

[Poser la scène comme un souvenir vécu.]

Imaginez. C'est vendredi, dix-sept heures. Un commercial vous ping : "dis, ce compte-là, il a facturé
combien cette année, en vrai ?"

Question simple. Le chiffre existe. Il est là, dans DRIVE_Revenues : environ 175 000 lignes, 20 colonnes,
cinq scénarios dans la colonne Phase. Le nombre est dans la base. Il n'est juste pas accessible.

[Premier obstacle. Lever un doigt.]

Premier obstacle : écrire le SQL pour aller le chercher, côté business, c'est une compétence rare. Donc
les gens attendent. Ils attendent un analyste, parfois des jours, pour un seul chiffre.

[Deuxième obstacle. Plus grave. Ralentir.]

Et là, deuxième obstacle, le vrai. Même quand une IA répond vite, vous ne pouvez pas mettre dans un comité
de direction un chiffre qui a peut-être été inventé. La vitesse sans la confiance, ça ne vaut rien. Un euro
halluciné dans un board deck, c'est un risque de carrière.

[Une preuve concrète que le domaine est dur. Ton un peu complice avec les techniciens.]

Et ce domaine est réellement piégé. Deux exemples. On ne somme jamais à travers les scénarios : additionner
de l'actuel avec du budget, ça ne veut rien dire. Et on ne retombe jamais par défaut sur le niveau d'offre
le plus fin, sirano_product : les lignes de budget n'ont pas cette valeur, donc un total bascule
silencieusement à zéro. Un bug invisible. Le genre de piège qui fait perdre confiance pour de bon.

[La bascule. Marquer un temps.]

Alors voilà le vrai recadrage. Le difficile, ce n'est pas de générer la réponse. Le difficile, c'est la
CONFIANCE.

[Transition.]

Et c'est en partant de là qu'on a eu l'intuition qui a tout réorienté.

---

## Slide 2 (coeur 2) - "L'intuition : ne pas promettre la confiance, l'inscrire dans la structure"
**~2 min 30**

[C'est le moment clé. Ralentir, c'est le pivot du talk.]

La plupart des outils d'IA cherchent la confiance avec un meilleur prompt. On écrit de belles instructions,
on croise les doigts, on espère que le modèle se tienne bien. Mais ça, c'est une promesse. Ce n'est pas une
garantie.

Notre pari avec OWIsMind, c'est l'inverse. On a décidé que la confiance serait une propriété STRUCTURELLE
de l'architecture. Pas un voeu dans un prompt, une contrainte dans la machine.

[Le firewall, en clair. C'est le point à faire passer absolument.]

Concrètement. L'orchestrateur, le cerveau qui dialogue avec vous, ne détient JAMAIS un chiffre business.
Jamais. Du coup, inventer un nombre, ce n'est pas interdit par une règle qu'il pourrait enfreindre : c'est
impossible par construction. Il ne peut pas inventer ce qu'il n'a pas.

Chaque chiffre vient d'un sous-agent qui l'a tiré d'un vrai résultat SQL. La réponse et la preuve naissent
ensemble, dans le même mouvement.

[Le "non" honnête. Important pour la crédibilité.]

On a aussi ce qu'on appelle un firewall d'honnêteté, dans la persona des agents. Il n'a le droit de dire
qu'une seule sorte de "non" : "je n'ai pas encore d'AGENT pour ce domaine". Ça, c'est un trou de capacité,
c'est honnête. Ce qu'il n'a jamais le droit de dire, c'est "la donnée n'existe pas". Seul un spécialiste,
après avoir vraiment regardé, peut affirmer qu'un chiffre manque. Pas de calcul mental non plus, et les
résultats des outils sont traités comme des entrées non fiables, à vérifier.

[Le tell produit. Geste vers le badge "never green".]

Et la discipline va jusque dans l'interface. Le badge de vérification dans Evidence n'est JAMAIS vert. Plein,
ça veut dire certifié. Pointillé, partiel. Gris, déclaré. Mais jamais ce vert rassurant qui ment. L'interface
elle-même refuse la fausse assurance.

[Transition.]

Voilà l'idée. Maintenant, laissez-moi vous montrer ce que ça donne, côté produit.

---

## Slide 3 (coeur 3) - "Le produit : un analyste presque SaaS, et le trio qui fait la différence"
**~2 min 30**

[Ton qui s'allège. C'est la démo racontée. Si screenshot à l'écran, le pointer.]

Vous arrivez, et vous tombez directement dans un chat. Vous posez votre question. L'orchestrateur vous
écrit l'analyse dans votre langue, en euros, avec le périmètre explicite : quel scénario, quelle période,
quelle entité. Vous savez exactement ce que le chiffre couvre.

[Le trio. C'est le payoff de la thèse "système, pas feature". Compter sur trois doigts.]

Et ce qui fait la différence, c'est un trio qui travaille ensemble.

Un : la Conversation. Le chiffre, plus une analyse rédigée.

Deux : la Timeline d'exécution en direct. Vous regardez l'agent travailler, en vrai, avec des étapes en
langage lisible par un humain. Ce n'est pas un spinner qui tourne dans le vide, c'est le raisonnement qui
se déroule sous vos yeux.

Trois : l'Evidence Studio. Le panneau de preuve, qui s'ouvre tout seul. Et c'est le plus beau : il re-dérive,
avec ZÉRO appel à un LLM, comment la réponse a été produite. Le badge, les sources, les filtres en chips
éditables, le résultat exact capturé, le SQL replié, et des graphiques Chart.js interactifs. La preuve, ce
n'est pas la parole du modèle, c'est le SQL stocké qu'on rejoue.

[La finition SaaS. Énumérer vite, pour montrer la maturité.]

Et ça se comporte déjà comme un produit. Français et anglais, thème clair et thème sombre, un feedback par
message, des branches de conversation, un bouton stop, et sous chaque réponse, une ligne tokens entrants,
tokens sortants, coût estimé. Transparence totale. L'utilisateur choisit même son mode de coût : éco, medium,
high. C'est le mode qui pilote le modèle, et éco est le défaut. Donc, par défaut, ça reste économique.

[Transition vers le coeur technique. Changement de posture.]

Bon. Maintenant, on va ouvrir le capot. Parce que vous êtes une salle technique, et que la magie, elle est
dans la mécanique.

---

## Slide 4 (coeur 4, LA PLONGÉE) - "Sous le capot : le système à quatre couches qui mérite la confiance"
**~4 min**

[C'est le morceau de bravoure. On prend son temps, c'est la salle qui se penche en avant.]

Quatre couches, chacune avec un contrat étroit. Une SPA Vue 3 plus un backend Flask en Python 3.9. Deux
Code Agents LangGraph sur le LLM Mesh, eux en Python 3.11. Du SQL direct sur PostgreSQL. Et pas de Flow à
l'exécution, sauf une trace en écriture seule.

Le point d'en-tête, celui que je veux que vous reteniez : chaque problème difficile est résolu par une
couche DIFFÉRENTE qui coopère. C'est précisément pour ça que le tout bat la somme des parties.

[Problème 1 : le grounding. Le plus contre-intuitif.]

Premier morceau, le plus subtil : le grounding. Quand vous dites "ce client", "cette offre", il faut ancrer
vos mots sur des valeurs exactes de cellules. Et le truc, c'est que le grounding n'est PAS un outil. C'est
du SQL inline, en lecture seule, sur un index de valeurs, DRIVE_Revenues_value_index, environ 3 600 valeurs.
Trois passes : match exact d'abord, puis fuzzy en LIKE, puis une dernière chance avec difflib. Et cette
expertise, elle est fabriquée à la conception, design-time, par des recettes Flow : un profil et un index de
valeurs, relisibles par un humain, jamais codés en dur. La connaissance métier vit dans les artefacts du Flow,
pas dans le code des agents.

[Problème 2 : qui écrit le SQL. La war story EVPL.]

Deuxième morceau : qui écrit le SQL analytique ? Le Semantic Model. Le seul vrai outil d'exécution,
revenue_semantic_query, l'identifiant v4oqA6R, ÉCRIT et EXÉCUTE le SQL sur un modèle Sonnet, dans tous les
modes. Et le sous-agent, lui, assiste avec des indices, mais il ne dicte JAMAIS la colonne. Pourquoi cette
règle ? À cause d'un vrai bug qu'on a vécu. Sur une offre nommée EVPL, le sous-agent épinglait de force une
colonne, sirano_product, et le budget tombait à zéro, parce que les lignes de budget n'ont pas cette valeur.
La leçon : le petit sous-agent aide, le gros modèle tranche. On a retiré l'autorité du mauvais endroit.

[Problème 3 : le streaming. LA war story que tout ingénieur Dataiku reconnaît.]

Troisième morceau, et là, vous allez sourire. Le streaming. On voulait du SSE, du mot à mot. Sauf que DSS
met un nginx devant le backend, et ce nginx bufferise le SSE. Donc rien ne s'affiche en direct. La solution :
l'agent tourne dans un worker thread borné, et le frontend va poller un dictionnaire de process toutes les
500 millisecondes environ. Le direct, le vrai, ce n'est pas le texte mot à mot, c'est la timeline. On a
arrêté de se battre contre le proxy, on a changé de stratégie.

[Problème 4 : signal contre donnée. La rigueur jusqu'au graphique.]

Quatrième morceau : signal contre donnée. Un événement artefact ne transporte qu'une spécification, le type,
le titre, la config du graphe. Jamais les lignes. Le payload Chart.js est reconstruit côté serveur, en Python
de confiance, à partir du résultat déjà capturé. Conclusion : une colonne mal tapée dégrade vers un état vide
honnête, jamais vers un faux graphique. On ne fabrique pas de visuel à partir de rien.

[Garde-fous instance. Important pour une salle Dataiku qui pense production.]

Et partout, des garde-fous pour l'instance : au plus 8 runs concurrents, une échéance à 300 secondes, du
lecture-seule avec un statement timeout. On respecte l'instance, c'est non négociable.

[Remonter à la surface. Ré-affirmer la thèse.]

Voilà les quatre problèmes. Quatre couches, quatre contrats étroits, chacune résolvant sa part. Aucune
couche, seule, ne suffirait. C'est l'assemblage qui rend un euro prouvable.

[Transition.]

Reste à savoir : est-ce que ça tourne vraiment ? Et qu'est-ce que ça devient ?

---

## Slide 5 (coeur 5) - "La preuve et le kicker : validé dans DSS, une plateforme, pas un coup unique"
**~2 min 30**

[Ton de traction. Honnête, posé, confiant.]

D'abord, c'est réel. C'est validé dans DSS sur le domaine du revenu. Un tour de chat complet, la timeline en
direct, le rejeu Evidence, les artefacts Chart.js : tout tourne de bout en bout sur l'instance.

Et le dépôt est la source de vérité. Les deux Code Agents sont collés à la main dans DSS, en environnement
3.11, mais l'ingénierie, les tests, la revue, tout vit dans le versioning. Pas dans des edits éparpillés
dans l'interface.

[Assumer le périmètre. La franchise EST le produit.]

Maintenant, je suis honnête sur le périmètre, et c'est volontaire. Aujourd'hui, un seul domaine est armé :
le revenu. Les autres, les tickets, la satisfaction, les opportunités, la livraison, la facturation, ils
répondent par un trou de capacité, jamais par une fausse réponse. Cette honnêteté-là, ce n'est pas une
limite gênante, c'est le produit. Et le plafond de budget mensuel, le stockage est prêt, l'application stricte
est l'étape suivante, assumée.

[Le kicker. C'est la promesse SaaS-sur-Dataiku. Le moment à faire claquer.]

Et voilà le kicker. Pour armer un nouveau domaine, qu'est-ce qu'on fait ? On câble les MÊMES recettes Flow
sur un nouveau dataset, on duplique le sous-agent en changeant deux noms de dataset, et on ajoute UNE seule
ligne dans le registre CAPABILITIES. Une ligne. Pas de réécriture. La webapp, les recettes, le stockage : on
n'y touche pas.

[La vision.]

Et cette extensibilité en une ligne, c'est exactement ce qui débloque la vraie ambition : l'analyse "360" en
multi-agents. Une question, plusieurs spécialistes en parallèle, une seule conversation, un espace Evidence
par agent. Le câblage est là. Il n'attend qu'un deuxième domaine.

[Transition vers la clôture.]

Alors, en une phrase, qu'est-ce qu'on a vraiment construit ?

---

## Slide 6 (clôture) - "Le tout vaut plus que la somme des parties"
**~1 min**

[Réassembler la thèse avec conviction. Les quatre tuiles se réemboîtent à l'écran. Ralentir.]

Récapitulons, d'un souffle. Une webapp servie par DSS. Des agents sur le LLM Mesh. Des recettes qui
fabriquent l'expertise. Du SQL direct. Quatre briques, reliées par des contrats étroits, en un seul produit
digne de confiance.

[Le coeur du message. Marquer chaque temps.]

Chaque brique, prise seule, était ordinaire. C'est la composition qui rend un nombre prouvable. Pas une
webapp, pas un agent, pas une recette. Le SYSTÈME que vous obtenez quand vous arrêtez d'empiler des features
et que vous commencez à composer des primitives.

Et le plus beau, pour vous, dans cette salle : sur Dataiku, ces primitives, vous les aviez déjà en main.

[La phrase de fondateur. Pause avant. La poser, ne pas la jeter.]

Alors je vais finir par ça. On n'a pas fait parler une IA du revenu. On l'a rendue responsable de chaque
euro qu'elle affiche.

OWIsMind. Un système. Construit sur Dataiku. Le tout vaut plus que la somme des parties.

Merci.

[Sourire. Attendre. Ouvrir aux questions.]

---

## Notes de minutage (récapitulatif)

| Slide | Titre court | Budget |
|---|---|---|
| 0 | Titre : l'analyste qui montre ses preuves | ~1 min |
| 1 | Le ping du vendredi | ~2 min |
| 2 | L'intuition : confiance structurelle | ~2 min 30 |
| 3 | Le produit et le trio | ~2 min 30 |
| 4 | La plongée : 4 couches | ~4 min |
| 5 | Preuve et kicker | ~2 min 30 |
| 6 | Clôture : le tout > les parties | ~1 min |
| **Total** | | **~15 min 30** (compressible) |

> Marges de compression si on déborde : raccourcir le 2e exemple de piège au slide 1, ou abréger la
> finition SaaS au slide 3. Ne jamais rogner la plongée technique (slide 4), c'est le moment où la salle
> technique adhère. Garder intacts le firewall d'honnêteté (slide 2) et le kicker une-ligne (slide 5) :
> ce sont les deux pivots.
>
> Pense-bête Q&A (honnêteté on-brand) : v3 arme un seul domaine (revenu) ; le plafond de coût est stocké
> mais pas encore appliqué strictement ; le 360 multi-agents est câblé mais attend un deuxième domaine.
