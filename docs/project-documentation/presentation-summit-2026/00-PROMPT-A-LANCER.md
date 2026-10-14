# Prompt à coller au démarrage d'une nouvelle conversation Claude Code (dans ce repo)

---

Tu travailles dans le repo OWIsMind, tu as accès à tout : la mémoire du projet (`memory/`), la
webapp Vue 3, le backend Flask, les Code Agents LangGraph, les recettes du Flow, les modèles
sémantiques et le plugin Dataiku. Sers-t'en.

## Ma mission pour toi

Produis UN SEUL fichier markdown, auto-suffisant :

`docs/project-documentation/presentation-summit-2026/ARCHITECTURE-BRIEF.md`

Ce fichier sera **copié-collé dans une autre conversation Claude qui n'a AUCUN accès à ce repo**.
Cette conversation-là générera mes slides PowerPoint et m'aidera à écrire mon speech. Donc :

- tout ce qui est nécessaire pour comprendre le projet doit être DANS le fichier ;
- aucun renvoi vers un chemin du repo que le lecteur ne pourra pas ouvrir ;
- aucun "voir tel fichier", aucun lien interne. Le fichier se suffit à lui-même.

Ce n'est pas une doc d'ingénierie de plus : c'est un brief de présentation. Il doit permettre à un
Claude qui découvre le projet de faire de bonnes slides et de me souffler un bon discours.

## Le contexte de la présentation

- **Événement** : Dataiku Summit. Public = clients et utilisateurs Dataiku d'autres entreprises
  (data scientists, data engineers, solution designers, décideurs data). Ils connaissent Dataiku,
  ils ne connaissent pas OWIsMind, et ils se demandent surtout "est-ce que je pourrais faire pareil
  chez moi".
- **20 minutes À DEUX** (ma collègue et moi). C'est très court, ça passe très vite. Pas de deck
  fleuve : sur ma partie, 3 slides maximum plus la clôture.
- **Déroulé arrêté** (ne le rediscute pas, construis dessus) :
  1. [Ma collègue] La donnée : le problème métier de départ.
  2. [Ma collègue] D'où vient l'idée : de Cooper, une solution que j'avais construite avant, à
     OWIsMind.
  3. [Ma collègue] Le périmètre : on a commencé par les revenus, uniquement les revenus.
  4. [Moi] La démonstration : une **vidéo enregistrée** du produit (je pose une question à
     OWIsMind, il répond), que je commente en direct pour expliquer ce qu'on voit à l'écran.
  5. [Moi] **3 slides maximum**, dans cet ordre exact :
     a. **How OWIsMind works** : comment ça fonctionne. C'est là que je parle de la webapp, de
        l'orchestrateur et des sous-agents spécialisés.
     b. **Est-ce qu'on peut faire confiance à ce que dit l'agent ?** C'est LA question qui revient
        toujours des utilisateurs. C'est là que je montre l'Evidence Studio et les données sources :
        l'utilisateur voit littéralement les filtres que l'agent a appliqués et peut aller vérifier
        lui-même d'où sortent les 20 millions. C'est une couche logicielle, pas une promesse.
     c. **Est-ce qu'on peut faire ça avec MES données ?** Le public est chez d'autres entreprises.
        Montrer ce qui est générique et réplicable : on implémente l'agent, on implémente le flow
        avec le profiling du dataset, etc. Bout à bout, on peut brancher n'importe quelle donnée
        métier, à condition d'expliquer correctement le métier, de décrire le dataset et de donner
        les bons outils à l'agent.
  6. [Moi] Clôture : un QR code vers mon site web.
- Ma collègue fait ses propres slides (1 à 3). Le fichier doit donc **se concentrer sur ma partie**
  (4, 5, 6), tout en donnant assez de contexte global pour que l'enchaînement tienne debout.

## L'altitude : le point le plus important

Ni pitch business creux, ni exposé technique jargonneux. Je veux **jongler entre les deux**.

La règle : chaque brique est nommée avec son **vrai nom**, et son rôle est expliqué en **une phrase
qu'un non-spécialiste comprend**, tout en restant crédible pour un ingénieur dans la salle. Un data
scientist doit se dire "d'accord, je vois exactement ce qu'ils ont fait" ; un décideur doit pouvoir
suivre du début à la fin sans décrocher.

Interdits : les tunnels de détails d'implémentation (noms de fonctions, chemins de fichiers,
signatures, numéros de version internes), et à l'inverse le vocabulaire marketing vide
("révolutionnaire", "puissant", "game changer").

## Ce que le fichier doit contenir

1. **La phrase unique** : ce qu'est OWIsMind en une phrase, dite au début et redite à la fin.
2. **Ce que voit l'utilisateur** : le produit en cinq lignes, du point de vue métier.
3. **L'architecture bout en bout** : un schéma en texte (reproductible dans PowerPoint : décris-le
   assez précisément pour qu'on puisse le redessiner) plus un paragraphe court par brique, chacun
   répondant à "à quoi ça sert" avant "comment c'est fait".
4. **Le trajet d'une question**, de la question tapée jusqu'au chiffre affiché. C'est le meilleur
   outil pédagogique du talk : c'est ce qui rend l'architecture concrète. Numérote les étapes.
5. **La couche de confiance** : pourquoi l'agent ne PEUT pas inventer un chiffre. C'est un argument
   d'architecture, pas une promesse de prompt : explique le mécanisme (qui détient les données, qui
   écrit le SQL, ce qui est capturé, ce que l'utilisateur peut rouvrir et vérifier lui-même).
6. **Ce qui est générique et réplicable** : la recette pour brancher un nouveau domaine de données
   chez quelqu'un d'autre, et ce qu'il faut fournir pour que ça marche (le métier expliqué, le
   dataset décrit, les bons outils). Dis aussi honnêtement ce qui demande du travail.
7. **Ce que Dataiku apporte concrètement** : ce qu'on n'a PAS eu à construire parce que la
   plateforme le fournissait. C'est le point qui intéresse le plus ce public précis.
8. **Un mini-glossaire** : les dix termes que je vais prononcer, avec pour chacun la version courte
   à dire à l'oral.
9. **Deux ou trois analogies** utilisables au micro pour faire passer les idées difficiles.
10. **Slide par slide, pour ma partie** : le message unique de la slide, ce qu'il faut afficher
    (texte minimal, schéma), les trois points à dire, et ce qu'il ne faut surtout PAS dire.
11. **Les questions probables du public**, avec une réponse courte et honnête pour chacune.
12. **Les pièges** : ce qu'il ne faut pas promettre sur scène.

## Comment travailler

- **Vérifie dans le code et dans la mémoire du projet avant d'affirmer quoi que ce soit.** Ce
  fichier alimente un talk public : une brique inventée ou mal nommée se paierait devant la salle.
- Sources de vérité à lire en priorité : `OWIsMind_PRD_V1_3_DEV/CLAUDE.md` (le mécanisme bout en
  bout d'un tour de chat, c'est la meilleure porte d'entrée), `OWIsMind_PRD_V1_3_DEV/README.md`,
  `memory/PROJECT_STATE.md`, puis le code lui-même : `GenAI/Agents/`, `GenAI/semantic-models/`,
  `flow/`, `python-lib/owismind/`, `frontend/src/`.
- **Il existe déjà de la matière narrative** : `docs/project-documentation/presentation-customer-day/`
  contient un deck et des scripts orateur FR et EN écrits en juin pour un événement Dataiku
  comparable. Sers-t'en comme base de récit et de formulations, mais **revérifie chaque fait
  technique** dans la mémoire et le code : ce dossier est signalé comme potentiellement périmé.
- Le graphe de connaissances du repo est à jour : une requête `graphify query "..."` coûte environ
  18 fois moins de tokens qu'une relecture de docs pour répondre à "où est géré X".
- **Zéro chiffre inventé** : aucune métrique business, aucun gain de productivité, aucun nom de
  client qui ne serait pas déjà écrit noir sur blanc dans le repo. Si une donnée manque, laisse un
  marqueur explicite `[À CHIFFRER PAR SAÏD]` plutôt que de combler.

## Contraintes de forme

- Fichier en français. Propose les titres de slides en français ET en anglais (le titre "How
  OWIsMind works" est déjà arrêté en anglais, le deck peut partir dans cette langue).
- **Zéro tiret cadratin et zéro tiret demi-cadratin**, nulle part : règle non négociable du projet.
  Utilise le trait d'union, les deux-points, la virgule ou les parenthèses.
- Vise 250 à 400 lignes : assez dense pour être auto-suffisant, assez court pour tenir dans une
  conversation Claude sans être tronqué.
- Termine le fichier par une section "Comment utiliser ce document" qui explique au Claude
  destinataire ce qu'on attend de lui : générer les slides PowerPoint de ma partie et m'aider à
  écrire le speech, en respectant le format 3 slides plus clôture.

Quand tu as fini, dis-moi en trois lignes ce que le fichier couvre et ce qu'il laisse volontairement
de côté, et signale-moi les endroits où tu as dû trancher.
