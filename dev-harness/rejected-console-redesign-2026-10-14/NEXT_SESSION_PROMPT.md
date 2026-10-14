Tu travailles seul, sans sous-agent ni workflow. Lis d'abord `CLAUDE.md` et `docs/cadrage/CHARTE_ORANGE_UI.md` (règles #9 et #10).

# Mission : refaire la mise en page de l'Agent Factory Console (Standard webapp DSS)

## Contexte
- Fichiers : `OWIsMind_PRD_V1_3_DEV/Standard-webapps/agent-factory-console/{body.html, script.js, style.css}` (+ README.md).
  JS vanilla style ES5 (var, function, pas de flèches, pas de template literals), sans lib, sans CDN, sans build :
  c'est collé dans les panneaux HTML / JS / CSS d'une Standard webapp DSS.
- **Le moteur MARCHE en DSS** (l'user a ajouté ET retiré des agents 2 fois avec succès). Gelés, NE PAS
  modifier : `backend.py` (contrat des routes) et `project-library/python/owismind_factory/`. Toute
  fonction de création / retrait (13 étapes de création, 12 de retrait, confirmations, nom tapé pour
  le retrait, vérification « C'est fait », abandon, wizard IA + réponses, suivi des jobs) doit rester.
- **État du working tree** : il contient une refonte REJETÉE par l'user (non commitée), copiée ici :
  `dev-harness/rejected-console-redesign-2026-10-14/` (+ `console_design_brief.md`).
  La version de référence fonctionnelle = celle de git HEAD (`git show HEAD:<chemin>`). Tu peux
  repartir de HEAD, ou réutiliser des morceaux utiles de la refonte rejetée (par ex. `STAGE_UX` =
  microcopie par étape, `derivedNames` = aperçu des noms qui seront créés), mais PAS sa mise en page.
  Si git répond par un message de licence Xcode, demande à l'user de lancer `! sudo xcodebuild -license`.
- Simulateur local (sans DSS, sans install) : `python3 dev-harness/console_sim.py` puis
  http://127.0.0.1:5198/ (vrais fichiers de la console, re-lus à chaque chargement, + vrai backend.py
  sur un faux projet). Aucun navigateur headless n'est installé : si tu veux des captures, demande à
  l'user d'installer Chromium pour Playwright (règle NO INSTALL : c'est lui qui installe).

## Ce que l'user reproche (citations reformulées)
- Le problème n'est PAS le nombre d'étapes (13 c'est OK), c'est la DISPOSITION des éléments : éléments
  positionnés partout, des choses cachées, mélange confus. Ultra confus pour un humain.
- Les libellés « Avancé », « Sonde », « Lancer la sonde (lecture seule) », « Analyser l'instance »,
  « Mode expert », « Création d'un domaine dans un seul bloc », « Fichiers du hub » ne veulent rien dire.
  « Analyser l'instance » est FAUX et inquiétant : la sonde ne lit que le projet courant, en lecture seule.
  « Ajouter un agent » ne doit pas apparaître dans une zone « Avancé ».
- **Vocabulaire à GARDER** (l'user le préfère) : orchestrateur, sous-agent, capability, domaine,
  dataset source, modèle sémantique, Code Agent, zone, recette. Ne PAS remplacer par « expertise ».

## Cible : 3 écrans, mise en page simple et évidente
1. **Vue d'ensemble = un SCHÉMA** : l'orchestrateur OWIsMind au centre ou en haut, relié par des traits
   à chacun de ses sous-agents (capabilities lues via `GET api/hub/capabilities`, ex. revenue_expert,
   tickets_expert). Chaque nœud de sous-agent montre : libellé, domaine, dataset source, état
   actif/inactif, et les actions Activer/Désactiver et Retirer directement dessus (routes existantes
   `api/capability/enable` et `api/guided/start-removal` avec saisie du nom de domaine). Un bouton
   principal clair « Ajouter un sous-agent ». Si un parcours est en cours : un bandeau « Reprendre ».
   Schéma en HTML/CSS ou SVG inline, charte Orange (carré, filets 1px, orange rare, tokens, clair et sombre).
2. **Ajouter un sous-agent** : le parcours guidé existant (13 étapes, routes `api/guided/*`), en UNE
   colonne lisible : où on en est, ce qui va se passer concrètement au clic (et ce qui sera créé), le
   bouton, puis le résultat. Les détails techniques (journal) dans un repli discret, ouvert en cas d'échec.
3. **Retirer un sous-agent** : le parcours de retrait existant (12 étapes), même mise en page, avec
   « ce qui sera supprimé » et « ce qui ne sera JAMAIS touché » (dataset source).

## Fonctions secondaires (décisions par défaut, à confirmer en UNE question à l'user au début)
- **Sonde** : ne plus l'exposer comme un écran. Son résultat (`probe_results.json` du hub) est un
  prérequis de la création (`guided.probe_gates`). Proposition : l'expliquer dans la 1re étape de
  création (« Vérifier la compatibilité du projet : lecture seule, rien n'est créé ») et ne la proposer
  que si elle n'a jamais tourné. Vérifier dans `guided.py` comment le prérequis est contrôlé.
- **Mode expert** (= créer un domaine d'un seul coup, simulation puis exécution, sans pas à pas : outil
  de dev d'avant l'assistant, doublon des notebooks) : le retirer de l'interface (route backend inchangée).
- **Éditeur JSON brut de `capabilities.json`** (la liste des sous-agents en texte brut) : le retirer de
  l'interface (Activer / Désactiver / Retirer suffisent).
- **Prompt de personnalité de l'orchestrateur** (`orchestrator_persona.md`) : l'user trouve ça utile,
  le garder dans une petite page « Réglages » avec les réglages techniques en lecture seule.

## Gates avant de dire « fini »
`node --check` sur script.js ; `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests` (765 OK
attendus) ; grep U+2013 / U+2014 = 0 ; grep `color-mix|backdrop-filter|gradient` = 0 dans style.css ;
parcours création + retrait + activer/désactiver exercés sur le simulateur ; liste écrite de chaque
fonction conservée / retirée de l'UI. Puis demander à l'user de regarder http://127.0.0.1:5198/ en
clair ET sombre. Pas de commit sans son accord (fin de session = `/log-session`).
