# Durable Step Shell (couche agentique v1.3) - comprendre et deployer

> Le guide unique et complet de la nouvelle architecture agentique d'OWIsMind : d'abord ce qui a
> ete construit et comment ca marche dans le detail, puis un guide d'installation pas a pas.
> Redige le 2026-07-17. Complements techniques : `docs/superpowers/specs/2026-07-17-agentic-runtime-design.md`
> (la spec de conception), `SECURITY_AUDIT_2026-07-17_DURABLE.md` (l'audit). Rien n'est deploye tant
> que le flag n'est pas active : la partie 2 explique comment l'allumer sur DEV en toute securite.

## Sommaire

**Partie 1 - Comprendre**
1. En une page (TL;DR)
2. Le probleme que ca resout
3. La decision centrale (la pepite)
4. Le cycle de vie complet d'un run durable
5. Les composants nouveaux, fichier par fichier
6. Le modele de donnees (les tables)
7. La boucle plan / execute / verify pour petits modeles
8. Multi-datasets : catalogue + correlation SQL
9. Le protocole backend <-> agent (le token machine)
10. La memoire de travail (le ledger)
11. L'interface (UI)
12. La securite
13. Ce qui change et ce qui NE change PAS (dual-path)

**Partie 2 - Installer**
14. Vue d'ensemble du deploiement
15. Prerequis et gates de securite DSS
16. Le guide pas a pas
17. Ce que l'utilisateur voit une fois active
18. Rollback (revenir en arriere)
19. Depannage
20. Checklist finale

---

# PARTIE 1 - COMPRENDRE

## 1. En une page (TL;DR)

**Le but** : donner a l'orchestrateur un vrai comportement agentique sur les questions COMPLEXES
(corriger des donnees entre plusieurs datasets, plusieurs etapes), sur des modeles PAS CHERS, sans
exploser la fenetre de contexte, et sur des runs qui peuvent durer plusieurs minutes sans casser.
Inspire de Dataiku Cobuild (plan visible, narration, activite consultable).

**Le comment** : jusqu'ici, un message = un seul appel au modele qui fait tout d'un bloc (boucle
ReAct). Si l'appel est long, il est fragile (il meurt avec le kernel, avec un restart, avec un
timeout). La nouvelle architecture, le **Durable Step Shell**, casse ce bloc en deux :

- le **backend Flask (Python 3.9)** devient un **ordonnanceur durable** : il possede le run, son
  plan, son curseur, ses etapes, ses reprises, et il stocke tout ca en **PostgreSQL** ;
- l'**orchestrateur (Code Agent LangGraph, Python 3.11)** reste le **cerveau**, mais il est appele
  **une commande courte a la fois** (planifie / execute une etape / re-planifie / verifie / redige).

Un appel au modele n'execute plus jamais tout le run. Chaque etape validee est ecrite en base AVANT
la suivante. Resultat : un kill du backend, un OOM, un redemarrage de DSS ne perdent plus rien ; le
run reprend automatiquement a la derniere etape terminee.

**Ce qui est nouveau et visible pour vous** :
- le bug du mode Claude (timeout a 5 min qui coupe tout) est corrige (deadlines par mode) ;
- une carte "Plan d'analyse" s'affiche dans le chat et coche ses etapes en direct ;
- l'agent peut correler plusieurs datasets par une vraie requete SQL (en lecture seule) ;
- tout est desactive par defaut (feature flag) : le chat actuel ne change pas d'un iota tant que
  vous n'activez pas explicitement le mode durable sur un agent.

## 2. Le probleme que ca resout

Le chat actuel fonctionne par POLLING (valide en DSS, lecon L019) : `/chat/start` lance un worker
en arriere-plan, le front interroge `/chat/poll` toutes les 500 ms. Mais ce worker :

1. **execute tout le run dans UN seul appel a LLM Mesh** (la boucle ReAct de l'orchestrateur) ;
2. **garde son etat uniquement en memoire du process** (un dict `_RUNS`) ;
3. **est coupe a 300 secondes** par une constante `MAX_RUN_SECONDS` **identique pour tous les modes**.

Consequences concretes, toutes reelles :
- le **mode Claude** (le tier lent qui reflechit) depasse regulierement les 300 s et se fait couper :
  vous voyez apparaitre `- run_timeout -` brut a l'ecran, et tout s'arrete ;
- si le backend redemarre (mise a jour, OOM, action admin), **le run en cours est perdu** : son etat
  n'existait qu'en RAM ;
- il n'y a **pas de plan**, pas de memoire de travail, pas de moyen de correler plusieurs datasets :
  c'est une boucle plate bornee a 8 tours d'outils.

Or la vraie valeur, pour vous, ce ne sont pas les questions simples ("les revenus du client X",
que l'utilisateur sait faire seul), ce sont les **taches complexes multi-datasets** ("revenus du
client X croises avec ses tickets, correles avec le produit Y"). Ce sont justement celles qui
prennent du temps et qui cassaient.

## 3. La decision centrale (la pepite)

Issue d'un brainstorm a trois voix (Fable 5 + un second agent Fable 5 + GPT-5.6 Sol, deux
propositions independantes puis confrontation). La conclusion partagee :

> **Le backend est l'ordonnanceur durable ; l'orchestrateur est le cerveau, invoque par commande
> bornee et sans etat entre deux commandes. PostgreSQL est la source de verite du run.**

```
      Navigateur (Vue 3)
          |  POST /chat/start   +  GET /chat/poll (500 ms)
          v
  Backend Flask 3.9 : ORDONNANCEUR DURABLE
     |   possede : plan, curseur, lease, deadlines, retries, reprise
     +-- webapp_agent_runs_v1        (l'etat du run)
     +-- webapp_agent_run_steps_v1   (le plan + le resultat de chaque etape = le ledger)
     +-- webapp_agent_run_events_v1  (la narration persistee, pour l'UI)
          |
          |  UNE commande bornee par appel LLM Mesh :
          |  plan | execute <step> | replan | review | synthesize
          v
  Orchestrateur (Code Agent LangGraph 3.11) : LE CERVEAU (sans etat)
     +-- planner / replanner / reviewer / synthesizer  (JSON strict)
     +-- appel des sous-agents specialistes (revenus, tickets)
     +-- correlate : vrai JOIN SQL read-only entre datasets
```

**Pourquoi ce decoupage et pas un autre** (les trois options ecartees) :
- **Un seul appel Mesh long** (garder le modele actuel, juste plus permissif) : impossible de
  survivre a un kill, borne par la duree de vie du kernel d'agent DSS et par l'absence d'API
  d'annulation de LLM Mesh.
- **Un checkpointer LangGraph cote agent** (l'outil "officiel" de LangGraph pour la durabilite) :
  ne marche pas ici, parce que les noeuds de l'orchestrateur ne sont PAS idempotents (ils streament
  du texte, lancent des sous-agents, ecrivent une trace). Un replay dupliquerait ces effets. C'est
  ecrit noir sur blanc dans le code de l'orchestrateur : "NON-DURABLE by design".
- **Garder l'etat en RAM** : viole la regle d'or de Dataiku (un backend de webapp est UN process
  qui peut etre tue a tout moment par un OOM, un `stop_backend`, un redemarrage DSS).

Le seul point ou la durabilite peut etre garantie, dans les contraintes reelles, c'est une enveloppe
deterministe cote backend qui persiste chaque etape et ne donne au modele **qu'une decision locale a
la fois**. C'est exactement ce qui aide un PETIT modele : moins il a a decider d'un coup, plus il est
fiable (lecon L060 : la fiabilite vient de l'architecture, pas du prompt).

## 4. Le cycle de vie complet d'un run durable

Voici ce qui se passe, bout en bout, quand vous posez une question complexe a un agent en mode durable.

**Etape 0 - le tri (0 appel au modele).** `/chat/start` regarde si l'agent a le flag
`durable_workflow` ET si la question merite un plan. Ce second test est une **gate deterministe**
(`context.should_plan`) : elle ne consulte JAMAIS un modele. Elle declenche le mode durable seulement
si au moins deux domaines configures apparaissent dans la question, OU si la question contient une
formulation explicite de correlation ("correler", "croiser", "join the data"...). Tout le reste part
sur le chemin classique. **Consequence : une question simple ne paie jamais le cout d'un planner.**
Vous pouvez aussi forcer via un `analysis_mode` : `deep` force le mode durable, `direct` force le
chemin classique.

**Etape 1 - creation du run.** Le backend cree une ligne dans `webapp_agent_runs_v1` (statut
`queued`), calcule sa deadline selon le mode, prend un "lease" (un bail : la preuve qu'un worker
s'en occupe), et lance un thread worker. Il renvoie immediatement `{run_id, durable: true}` au front.

**Etape 2 - PLAN.** Le worker appelle l'orchestrateur avec la commande `plan`. L'orchestrateur
renvoie un plan structure (JSON strict) : une liste d'etapes, chacune avec un type (`specialist_query`,
`correlate`, `render`, `attribute_lookup`, `clarify`), un objectif, les capabilities logiques a
utiliser (jamais un id d'agent brut), et des dependances. Le backend valide ce plan (types dans une
enumeration fermee, maximum 12 etapes, pas de cycle, aucun nom de table/SQL dans le plan), puis le
persiste dans `webapp_agent_run_steps_v1`. Un event `PLAN_READY` part vers l'UI : la carte "Plan
d'analyse" apparait.

**Etape 3 - EXECUTE, etape par etape.** Le worker deroule les etapes dans l'ordre. Pour chacune :
il appelle l'orchestrateur avec la commande `execute` et l'etape courante, plus un bloc compact
`[WORKFLOW PROGRESS]` qui resume ce qui a deja ete fait (le ledger recite). L'orchestrateur execute
UNE etape (delegue a un sous-agent, fait une correlation SQL, ou rend un graphique), et renvoie un
resultat structure. Le backend applique des **gates deterministes** (le resultat est-il non vide ?
les colonnes attendues sont-elles la ?), puis ECRIT le resultat dans la base AVANT de passer a la
suite. Chaque transition emet un event (`STEP_STARTED`, `STEP_COMPLETED`...) : la carte de plan
coche l'etape.

**Etape 4 - REVIEW (seulement pour les plans multi-sources).** Une fois toutes les etapes finies,
si le plan croise plusieurs sources, un unique appel `review` demande au modele si la reponse couvre
bien la question. S'il manque quelque chose, un `replan` peut ajouter des etapes (borne a 2 replans).

**Etape 5 - SYNTHESIZE.** Un dernier appel `synthesize` demande au modele de rediger la reponse
finale a partir du ledger. Cette reponse est ecrite dans `webapp_chat_v5` (la meme table que le chat
classique), avec le SQL genere fusionne et l'usage additionne, en UNE transaction idempotente.

**En cas de pepin, a n'importe quelle etape** : le run rend TOUJOURS un resultat partiel honnete (les
etapes deja terminees), avec un message convivial (jamais un code technique brut). Les modes d'echec
sont geres proprement : rate-limit LLM (on attend et on retente), quota bloquant (on abandonne
proprement), specialiste indisponible, SQL refuse, deadline atteinte, stop utilisateur.

**Survie a un crash.** Si le backend meurt en plein run : le heartbeat s'arrete, le lease expire, et
au redemarrage un thread superviseur (un seul, qui reprend au maximum UN run par scan de 10 secondes
pour ne pas surcharger l'instance) reprend le run a sa premiere etape non terminee. Les etapes deja
terminees ne sont jamais rejouees. Une tentative "zombie" tardive ne peut pas ecraser une tentative
plus recente, grace a un jeton de "fencing" (`attempt_id`) verifie directement dans la requete SQL.

## 5. Les composants nouveaux, fichier par fichier

**Backend (Python 3.9, dans `Plugin/owismind/python-lib/owismind/`)**

| Fichier | Nouveau ? | Ce qu'il fait |
|---|---|---|
| `agents/durable_runner.py` | NOUVEAU | Le coeur : le superviseur, la machine d'etat (plan/execute/review/synthesize), le semaphore qui limite les appels Mesh simultanes, les deadlines par mode, les retries avec backoff, la finalisation idempotente. Zero langchain (c'est du 3.9). |
| `storage/run_state.py` | NOUVEAU | Toute la persistance durable : creation de run, prise/renouvellement de lease (compare-and-set atomique), fencing par attempt_id, sauvegarde du plan, avancement des etapes, feed d'events, finalisation de l'usage. Chaque valeur passe par le parametrage SQL, chaque lecture est owner-scoped. |
| `storage/migrations.py` | edite | +3 tables `_v1` (runs / steps / events), creees automatiquement a la premiere utilisation. |
| `agents/context.py` | edite | La gate deterministe (`should_plan`), les constructeurs du token machine et du bloc de progression (fonctions pures). |
| `agents/stream_manager.py` | edite | Deadlines par mode (le fix du bug Claude) + routage : un run durable est delegue au durable_runner ; le chemin classique est inchange. |
| `agents/streaming.py` | edite | Normalise le canal machine `OWI_WORKFLOW_CONTROL` en type interne, jamais renvoye au front. |
| `api/routes.py` | edite | La gate durable dans `/chat/start`, les nouvelles routes `/chat/active` (reconnexion) et `/chat/activity` (voir l'activite), le demarrage du superviseur. |
| `security/validation.py` | edite | Laisse passer les nouveaux champs de profil `durable_workflow` + `domain_keywords` (bornes), sinon le mode durable serait inactivable depuis l'admin. |

**Orchestrateur (Python 3.11, dans `OWIsMind_PRD_V1_2/genai/agents/`)**

| Fichier | Ce qui est ajoute |
|---|---|
| `OWIsMind_orchestrator.py` | Un second chemin dans `process_stream` : si le message porte le token `owi:workflow`, il execute UNE commande (plan/execute/replan/review/synthesize) via un mini-graphe LangGraph sans checkpointer, puis emet UN event `OWI_WORKFLOW_CONTROL`. Sans token, le chemin classique est **strictement identique** (verifie par un golden test). Inclut la nouvelle etape `correlate` (JOIN SQL read-only garde). |

**Hub de configuration (dans `OWIsMind_PRD_V1_2/project-library/owismind_hub/`)**

| Fichier | Ce qu'il porte |
|---|---|
| `run_settings.json` (NOUVEAU) | Les deadlines par mode, les caps, les flags. Charge au demarrage de l'agent, avec un repli embarque si le hub est absent. |
| `prompts/orchestrator_workflow.md` (NOUVEAU) | Les 4 prompts PLANNER / REPLANNER / REVIEWER / SYNTHESIZER, editables sans toucher au code. |

**Catalogue multi-datasets (factory, dans `OWIsMind_PRD_V1_2/project-library/python/owismind_factory/`)**

| Fichier | Ce qu'il fait |
|---|---|
| `catalog.py` (NOUVEAU) | Construit, a design-time, un dataset `OWIsMind_agent_catalog_v1` : les descriptions, colonnes et references physiques des datasets, par generation append-only. Les references physiques (nom de table, connexion) sont server-only : jamais montrees au modele. C'est ce catalogue qui alimente l'etape `correlate`. |

**Interface (Vue 3, dans `Plugin/owismind/frontend/src/`)**

| Fichier | Ce qu'il fait |
|---|---|
| `components/chat/RunPlan.vue` (NOUVEAU) | La carte "Plan d'analyse" : les etapes et leurs statuts, charte Orange (carre, filets 1px, orange uniquement sur l'etape active). |
| `composables/timelineModel.js` | +les events `plan` / `step_status`, +l'adaptateur du feed durable, +le mappage des erreurs conviviales. |
| `composables/useChatStream.js` | +`resumeChatStream` (reconnexion apres refresh). |
| `services/backend.js` | +`fetchActiveRun`, +`fetchRunActivity`. |
| `components/chat/MessageAgent.vue` | Affiche `RunPlan` + le bouton "Afficher l'activite". |
| `i18n/extra.js` | Les libelles FR/EN du plan et des erreurs conviviales. |

## 6. Le modele de donnees (les tables)

Trois nouvelles tables PostgreSQL, creees automatiquement a la premiere utilisation (idiome `_vN`,
prefixees par la cle de projet, comme toutes les tables du plugin) :

- **`webapp_agent_runs_v1`** : une ligne par run durable. Contient le statut, la phase, le curseur
  d'etape, le mode, la deadline, le lease (proprietaire + expiration + heartbeat), le compteur de
  replans, la reponse finale, l'usage. C'est l'etat du run.
- **`webapp_agent_run_steps_v1`** : une ligne par etape du plan. Contient le type, le titre, la tache,
  les dependances, le statut, la tentative courante (`attempt_id`, le jeton de fencing), le resume du
  resultat, le schema, le SQL genere, les artefacts, l'usage. C'est le **ledger** : la memoire de
  travail durable.
- **`webapp_agent_run_events_v1`** : la narration persistee (plan, transitions d'etapes, activite),
  ecrite par lots (flush toutes les secondes ou a chaque transition), retention 14 jours. C'est ce
  qui permet a l'UI de reconstruire l'activite apres un refresh ("Afficher l'activite").

Plus une table de catalogue possedee par la factory (design-time) : **`OWIsMind_agent_catalog_v1`**.

La table `webapp_chat_v5` (le chat classique) n'est PAS modifiee : la reponse finale d'un run durable
y est ecrite comme un echange normal.

## 7. La boucle plan / execute / verify pour petits modeles

Le principe : **le code porte la structure, le modele ne decide que localement**. La verification est
economique, dans cet ordre (du moins cher au plus cher) :

1. **Gates deterministes (0 token)** : validation JSON stricte de toute sortie machine, puis des
   checks par etape (non vide ? colonnes presentes ? cle de jointure la ?).
2. **Self-correction guidee par l'execution** (pour le SQL) : on execute, on capture l'erreur de la
   base, on la renvoie nettoyee au modele, on reessaie (2 fois max). C'est le pattern qui rend les
   petits modeles competitifs sur le SQL.
3. **Un seul appel `review` LLM**, et seulement en fin de plan multi-sources, jamais a chaque etape.

Un echec de check deterministe n'est PAS traite comme une erreur transitoire (pas de retry a
l'identique, ca ne guerirait rien) : il declenche le chemin de re-planification, avec l'erreur en
contexte. Les retries a backoff sont reserves aux vraies erreurs transitoires (reseau, rate-limit).
Un quota bloquant termine le run proprement, sans retry inutile.

## 8. Multi-datasets : catalogue + correlation SQL

Le vrai defi : correler 5, 10 datasets sans faire transiter les donnees par le contexte du modele.

**Le catalogue** (`OWIsMind_agent_catalog_v1`) est construit une fois, hors-ligne, par la factory. Il
contient pour chaque dataset ses descriptions metier, ses colonnes, ses synonymes, et - server-only -
sa table physique et sa connexion. Le modele ne voit JAMAIS ces references physiques ; il ne recoit
que des descriptions et des schemas. La recherche est lexicale (pas d'embeddings : a 5-10 domaines,
les descriptions suffisent, et ca evite une dependance).

**La correlation** (`correlate`) fonctionne ainsi : le modele ecrit une requete SQL uniquement contre
des **alias logiques** (`d1`, `d2`, ...) dont il voit le schema. Le CODE substitue ensuite les vraies
tables physiques (depuis le catalogue) sous forme de CTE, applique une garde SQL stricte, un EXPLAIN,
une previsualisation (LIMIT 10), des controles de coherence, puis l'execution finale en lecture seule
(transaction read-only + statement_timeout 30 s + LIMIT 500). Le modele ne voit jamais les noms
physiques, ne peut pas ecrire, ne peut pas sortir de la liste blanche des alias. La generation SQL
reste sur le modele le plus capable (Sonnet) meme en mode smart : la qualite du SQL ne degrade jamais.

## 9. Le protocole backend <-> agent (le token machine)

Le backend communique avec l'orchestrateur en ajoutant, EN FIN de message, un token machine :

```
⟦owi:workflow=v1;command=execute;run=<id>;step=<id>;attempt=<id>⟧
```

Regle de securite (anti-forge) plus stricte que les tokens existants : le token gagnant doit etre en
QUEUE du message (seuls d'autres tokens de controle peuvent le suivre). Comme le backend appose SON
token en dernier, un utilisateur qui taperait un faux token dans son message ne pourrait jamais le
placer en vraie queue : il serait ignore. Le modele ne voit jamais le contenu du token (l'agent le
parse puis le retire). Sans token, l'orchestrateur suit son chemin classique, byte-identique.

Le ledger (l'historique compact du run) est reconstruit par le backend et **injecte dans le prompt**
(bloc `[WORKFLOW PROGRESS]`), et non lu en SQL par l'agent : ce choix evite d'accorder a l'agent des
droits de lecture sur les tables `webapp_*` (moins de surface, decouplage plus propre).

Le resultat machine remonte via un event dedie `OWI_WORKFLOW_CONTROL`, consomme par le backend et
jamais renvoye au front.

## 10. La memoire de travail (le ledger)

La verite du run vit en SQL (les tables ci-dessus). A chaque commande, le backend reconstruit un bloc
compact `[WORKFLOW PROGRESS]` : l'objectif, l'etape courante, les statuts, un resume d'une ligne des
etapes faites avec leurs references (`#S1`, `#S2`...), et les schemas des dependances. Les LIGNES de
donnees brutes ne transitent JAMAIS par le contexte (previsualisation limitee a 15 lignes) : elles
restent en base, rechargeables par reference. Le bloc a un budget par mode et se degrade proprement
sous pression (on retire d'abord les schemas, puis on raccourcit les resumes ; les objectifs et les
references ne sont jamais perdus). C'est une compression restaurable : rien n'est detruit.

## 11. L'interface (UI)

- La **carte "Plan d'analyse"** (RunPlan.vue) : la liste des etapes, leur statut qui coche en direct,
  la progression N/M. Charte Orange stricte : geometrie carree, filets 1px, orange uniquement sur
  l'etape active, aucun degrade ni ombre ni emoji.
- La **narration** existante est gardee.
- **"Afficher l'activite"** (comme Cobuild) : recharge l'activite persistee d'un run termine.
- **Reconnexion** : si vous rafraichissez la page pendant un run, le front se rebranche dessus.
- **Erreurs conviviales** : fini `- run_timeout -` ; a la place, un message clair FR/EN par code
  (deadline atteinte, quota, capacite en attente, source indisponible, resultat partiel).

## 12. Ce qui change et ce qui NE change PAS (dual-path)

**Ne change PAS** (garanti par un golden test qui compare la sequence exacte d'events) : le chat
classique, pour tous les agents qui n'ont pas le flag `durable_workflow`, et pour toutes les questions
simples meme sur un agent flague. Meme comportement, meme latence, meme code.

**Change**, uniquement pour un agent explicitement flague ET sur une question complexe : le run passe
par la machine durable.

C'est un choix de securite : on n'active la nouveaute que la ou elle apporte de la valeur, et le
chemin valide en production reste la reference (rollback trivial : on retire le flag).

---

# PARTIE 2 - INSTALLER

## 13. Vue d'ensemble du deploiement

Le Durable Step Shell touche trois "endroits" de Dataiku, dans cet ordre :

1. **Le plugin** (backend + frontend) : il faut rebuilder le frontend, repackager le zip, l'uploader,
   redemarrer le backend de la webapp. Les 3 tables SQL se creent toutes seules a la premiere
   utilisation.
2. **L'orchestrateur** (Code Agent, env 3.11) : recoller le fichier
   `OWIsMind_orchestrator.py` dans l'objet Code Agent DSS.
3. **Le hub + le catalogue** (project library) : pousser les 2 seeds hub, et construire le catalogue
   pour les datasets a correler.

Puis : **activer le flag sur DEV**, valider avec la campagne de scenarios, et seulement apres,
activer sur le clone de prod.

**Regle d'or** : rien ne bouge pour personne tant que le flag `durable_workflow` n'est pas coche sur
un agent. Vous pouvez donc deployer le code (etapes 1-3) sans aucun risque, et n'allumer le mode
durable qu'ensuite, quand vous etes pret.

## 14. Prerequis et gates de securite DSS

Avant d'activer le mode durable (pas avant de deployer le code), verifiez cote administrateur DSS :

- [ ] **Webapp en Auto-start.** La reprise apres un redemarrage de DSS en depend (sinon la reprise
      attend la prochaine ouverture de la webapp). Webapp > Edit > Settings > Auto-start.
- [ ] **Compte SQL `SQL_owi` en lecture seule au niveau base.** Le read-only reel vient des GRANTS du
      compte PostgreSQL, pas d'une case DSS. Le compte doit pouvoir lire les tables de donnees ET les
      tables `webapp_*` du plugin, mais ne rien ecrire d'autre que via le backend.
- [ ] **`statement_timeout` au niveau connexion ou base.** Le code pose deja un `statement_timeout`
      de 30 s par requete, mais une borne au niveau base est une ceinture-bretelles.
- [ ] **Environnement Python 3.11** pour le Code Agent orchestrateur (langchain/langgraph installes),
      inchange par rapport a l'existant.

Ces gates sont les memes que celles de la Phase 0 de `DEPLOY_V1_3_DEV.md` (l'audit factory du
2026-07-16). Elles ne sont pas verifiables depuis le code : ce sont des reglages d'instance.

## 15. Le guide pas a pas

> Les commandes `npm` / build se font sur votre machine de dev (jamais d'install cote agent).
> Les actions "dans DSS" se font dans l'interface Dataiku. Toutes les etapes sont sur la branche
> `OWIsMind_PRD_V1_3-dev`.

### Etape A - Builder le frontend

Le nouveau composant `RunPlan.vue` et les changements de composables doivent etre compiles dans les
assets statiques que DSS sert.

```
/build-plugin
```

(le skill lance `npm run build` vers `resource/owismind-app/` puis recable `body.html`). Ne jamais
editer `resource/owismind-app/` a la main.

### Etape B - Packager le zip du plugin

```
/package-plugin
```

Le zip est nomme d'apres la version de `plugin.json` : ici **1.3.0**, donc
`Plugin/ready-for-dataiku/owismind-v1_3-upload.zip` (le frontend et `node_modules/` ne sont jamais
inclus). Note : l'ancien zip `owismind-v1_2-upload.zip` reste present, c'est normal.

### Etape C - Uploader le plugin et redemarrer le backend (dans DSS)

1. DSS > Plugins > owismind > Actions > Update from ZIP > choisir `owismind-v1_3-upload.zip`.
2. Redemarrer le backend de la webapp `webapp-owismind-ai-agents` (Webapp > le backend > Restart).

A la premiere requete durable, les 3 tables `webapp_agent_runs_v1` / `_run_steps_v1` / `_run_events_v1`
seront creees automatiquement. Rien a faire manuellement en SQL.

### Etape D - Recoller l'orchestrateur (dans DSS, env 3.11)

Copier le contenu de `OWIsMind_PRD_V1_2/genai/agents/OWIsMind_orchestrator.py` dans l'objet Code Agent
**OWIsMind_orchestrator** (`agent:038G7mlF`), environnement Python 3.11, et sauvegarder. Le chemin
classique reste identique : ce recollage est sans risque meme avant d'activer le flag.

(Les deux sous-agents `SalesDrive_revenue_expert` et `CSSO_Trouble_Tickets_Expert` ne changent PAS
pour cette fonctionnalite : ne les recollez que s'ils ont ete modifies par ailleurs.)

### Etape E - Pousser les seeds du hub (project library)

Dans la project library du projet DSS, sous `owismind_hub/`, deposer :
- `run_settings.json` (les deadlines par mode, les caps, les flags) ;
- `prompts/orchestrator_workflow.md` (les 4 prompts planner/replanner/reviewer/synthesizer).

Sources dans le repo : `OWIsMind_PRD_V1_2/project-library/owismind_hub/`. Un repli embarque existe
dans l'orchestrateur, donc un hub absent ne casse pas un run ; mais pour pouvoir editer les deadlines
et les prompts sans toucher au code, poussez ces seeds.

### Etape F - Construire le catalogue (seulement pour l'etape `correlate`)

Si vous voulez la correlation SQL multi-datasets, il faut publier une generation de catalogue pour
chaque domaine a correler. Cela passe par la factory (`owismind_factory/catalog.py`), via le pipeline
de creation de domaine ou un notebook dedie. La capability doit alors porter les champs
`catalog_generation` + `catalog_dataset`. Sans catalogue publie, un agent reste utilisable (plan,
specialistes, render) mais l'etape `correlate` refuse proprement.

> Si vous ne voulez PAS encore de correlation multi-datasets, sautez cette etape : tout le reste
> (plan, runs longs robustes, memoire de travail, UI) fonctionne sans catalogue.

### Etape G - Activer le mode durable sur un agent DEV

Dans la console d'administration de la webapp (la ou vous activez les agents et editez leur profil),
sur l'orchestrateur, ajouter au profil :

```json
{
  "durable_workflow": true,
  "domain_keywords": {
    "revenue": ["revenus", "revenue", "chiffre d'affaires", "ca"],
    "tickets": ["ticket", "incident", "panne"]
  }
}
```

- `durable_workflow: true` : allume le mode durable pour CET agent.
- `domain_keywords` : alimente la gate deterministe. Deux domaines ou plus reconnus dans une question
  la font passer en mode planifie. Sans ces mots-cles, seule la formulation explicite de correlation
  declenche le plan (la gate reste conservatrice : en cas de doute, elle prend le chemin classique).

**A activer d'abord sur l'orchestrateur DEV uniquement.** Sur tout autre agent (un agent visuel
simple), laissez le flag a false : lui ne comprend pas le protocole.

### Etape H - Valider (la campagne de scenarios)

Avant d'activer en prod, jouez ces scenarios sur DEV (detail dans `DEPLOY_V1_3_DEV.md` phase H) :

1. un run smart long (> 5 min) : il va au bout, plus de coupure a 300 s ;
2. un run claude long (> 10 min) : idem ;
3. `stop_backend` entre deux etapes, puis restart : le run reprend a la derniere etape finie ;
4. rafraichir le navigateur en plein run : le front se rebranche (route `/chat/active`) ;
5. fermer puis rouvrir la webapp : le run a continue tout seul ;
6. un silence LLM prolonge : l'UI affiche l'attente, le run ne meurt pas ;
7. un rate-limit : le run attend et retente ;
8. un quota bloquant : abandon propre avec message clair ;
9. un specialiste desactive en cours de run : l'etape echoue proprement ;
10. un SQL refuse par la garde : rejet propre ;
11. une correlation revenus x tickets : le JOIN SQL s'execute, le resultat remonte ;
12. un plan a 5 datasets ;
13. Stop pendant un appel bloque : arret honnete ("attente de la fin de l'appel en cours") ;
14. une capability desactivee en vol ;
15. un double poll / double reprise : pas de doublon ;
16. verifier qu'aucun SQL / id d'agent / table physique n'est accepte depuis le navigateur.

Plus **un smoke SQL** : lancez un run durable complet et verifiez dans `webapp_agent_runs_v1` que la
ligne atteint `completed` avec `usage_accounted = true` (c'est le seul motif SQL nouveau du plugin,
une CTE modifiante ; ce smoke le valide sur le vrai moteur).

### Etape I - Activer sur le clone de prod

Une fois 5-6 scenarios verts sur DEV (dont un run long et une reprise apres restart), reproduire les
etapes C, D, E (et F si correlation) sur le projet clone de prod, puis cocher `durable_workflow` sur
l'orchestrateur prod. Le chemin classique reste le defaut ; seules les questions complexes basculent.

## 16. Ce que l'utilisateur voit une fois active

- Sur une question simple : rien ne change (chemin classique).
- Sur une question complexe (deux domaines ou une formulation de correlation) : une carte "Plan
  d'analyse" apparait sous le message de l'agent, ses etapes se cochent au fur et a mesure, la
  narration defile, et la reponse finale arrive a la fin. Un bouton "Afficher l'activite" permet de
  revoir le detail. Si le run est long, il tient ; s'il est interrompu, un resultat partiel reste
  affiche avec un message clair.

## 17. Rollback (revenir en arriere)

Trois niveaux, du plus doux au plus radical :

1. **Desactiver le flag** : decocher `durable_workflow` sur l'agent. Effet immediat, tous les nouveaux
   runs repassent en classique. C'est le rollback normal.
2. **Recoller l'ancien orchestrateur** : le chemin classique est byte-identique, mais si besoin, la
   version precedente du fichier est dans l'historique git.
3. **Reuploader l'ancien zip** `owismind-v1_2-upload.zip` + redemarrer le backend. Les tables durables
   restent en base (sans effet, elles ne sont plus lues).

## 18. Depannage

| Symptome | Cause probable | Quoi verifier |
|---|---|---|
| Le mode durable ne s'active jamais (toujours classique) | Flag absent ou gate trop stricte | Le profil porte bien `durable_workflow: true` (sauvegarde) ; la question contient 2 domaines de `domain_keywords` ou une formulation de correlation ; sinon forcer via `analysis_mode: deep`. |
| Un run long est coupe | Deadline du mode | Les deadlines sont dans `run_settings.json` (hub) ; par defaut claude = 30 min. Ajustez si besoin. |
| Le run ne reprend pas apres un restart DSS | Auto-start desactive | Activer Auto-start sur la webapp. |
| `correlate` refuse toujours | Pas de catalogue publie | La capability doit porter `catalog_generation` + `catalog_dataset` (etape F). |
| Erreur SQL sur la premiere ecriture durable | Grants du compte SQL | `SQL_owi` doit pouvoir lire/ecrire les tables `webapp_*` du plugin (les tables durables). |

## 19. Checklist finale

Deploiement du code (sans risque, flag off) :
- [ ] A. `/build-plugin` (frontend compile)
- [ ] B. `/package-plugin` (zip 1.3.0)
- [ ] C. Upload du zip + restart backend (DSS)
- [ ] D. Recoller `OWIsMind_orchestrator.py` (Code Agent 3.11)
- [ ] E. Pousser les 2 seeds hub (`run_settings.json`, `prompts/orchestrator_workflow.md`)
- [ ] F. (Optionnel) Publier le catalogue pour la correlation

Activation et validation (quand vous etes pret) :
- [ ] Gates DSS (Auto-start, SQL read-only, statement_timeout) - section 14
- [ ] G. Cocher `durable_workflow` + `domain_keywords` sur l'orchestrateur DEV
- [ ] H. Jouer la campagne de scenarios + le smoke SQL
- [ ] I. Reproduire sur le clone de prod, cocher le flag prod

---

## Reference des fichiers (rappel rapide)

- Spec de conception : `docs/superpowers/specs/2026-07-17-agentic-runtime-design.md`
- Plan d'implementation : `docs/superpowers/plans/2026-07-17-durable-step-shell.md`
- Rapport d'audit securite : `OWIsMind_PRD_V1_2/docs/SECURITY_AUDIT_2026-07-17_DURABLE.md`
- Runbook de deploiement (phase H) : `OWIsMind_PRD_V1_2/docs/DEPLOY_V1_3_DEV.md`
- Carte des ids (agents, tools, datasets) : `OWIsMind_PRD_V1_2/README.md` + `registry.json`
