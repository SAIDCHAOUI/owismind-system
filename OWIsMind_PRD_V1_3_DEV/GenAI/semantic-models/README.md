# semantic-models/ : les cerveaux SQL des sous-agents

Un modele semantique est l'objet Dataiku qui traduit une question en langage
naturel en requete SQL. Chaque sous-agent a le sien et l'interroge via son tool
"Semantic Model Query" (voir [`../agent-tools/README.md`](../agent-tools/README.md)).
Les modeles vivent dans DSS (source de verite) ; ce dossier en garde le miroir :
UN dossier par modele avec UN SEUL fichier Python de maintenance + le snapshot
`.v1.json` (decision user 2026-07-20 : un fichier Python par modele, ni plus ni moins).

## Dans Dataiku

Projet DSS `OWISMIND_PRD_V1_2`, section GenAI de l'UI (que ce dossier `GenAI/`
miroite). Deux modeles, un par domaine :

| Modele | Id | Tool | Sous-agent | Etat |
|---|---|---|---|---|
| `Drive_Revenues_Semantic_Model` | `AHUh9hb` | `revenue_semantic_query` (`v4oqA6R`) | `SalesDrive_revenue_expert` (`agent:bHrWLyOL`) | Repointe vers le dataset du clone + colonne `Solution` re-ajoutee le 2026-07-08. VALIDE en DSS. |
| `TroubleTickets_Semantic_Model` | `dM4jA4G` | `tickets_semantic_query` (`nEirlso`) | `CSSO_Trouble_Tickets_Expert` (`agent:NcE9LD2i`) | Repoint vers le clone PRET (`ACTION = "repoint"`, simule 4/4), PAS ENCORE lance. |

Chaque tool tourne en Agent mode OFF (pipeline SQL lineaire), LLM
`vertex_ai/claude-sonnet-4-6`, embedding `vertex_ai/text-embedding-005`, acces
aux datasets en tant qu'utilisateur appelant. Le SQL genere est en lecture seule.

Garde-fous : un modele = UNE table physique (jamais de JOIN) ; un modele par
domaine, jamais partage (liaison tool <-> modele 1:1). Les regles metier
(hierarchie d'offre, affichage client) vivent dans les instructions du modele,
pas dans le code des agents.

## Dans ce dossier

| Fichier | Role |
|---|---|
| [`MODEL.md`](MODEL.md) | Snapshot lisible du modele revenus live (entites, metrique, filtres, golden queries, glossaire, instructions). A lire en premier. |
| [`TOOL_DESCRIPTIONS.md`](TOOL_DESCRIPTIONS.md) | Texte pret a coller dans "Description for LLM" de chaque tool (revenus + tickets). |
| `Drive_Revenues_Semantic_Model/Drive_Revenues_Semantic_Model.py` | LE fichier de maintenance du modele revenus : `ACTION = "dump"` (export du live vers le `.v1.json`), `"update"` (pousse instructions + golden queries canoniques), `"repoint"` (remap apres clone + re-index). |
| `Drive_Revenues_Semantic_Model/Drive_Revenues_Semantic_Model.v1.json` | Dump de reference (`get_raw()`) du modele revenus. |
| `TroubleTickets_Semantic_Model/TroubleTickets_Semantic_Model.py` | LE fichier de maintenance du modele tickets : memes actions (`update` pousse en plus les descriptions d'attributs + les metriques). |
| `TroubleTickets_Semantic_Model/TroubleTickets_Semantic_Model.v1.json` | Dump de reference du modele tickets. |

Les anciens scripts (`scripts/` : build / update / dump / repoint / add_solution /
drop_column / migrate / remap) sont CONSOLIDES dans ces deux fichiers depuis le
2026-07-20 ; l'historique git les conserve. Le texte canonique revenus embarque =
la derniere iteration `update_aligned` composee avec la restauration de la
hierarchie `Solution` validee en DSS le 2026-07-08.

Les `.v1.json` sont des photos a un instant donne, jamais importees au runtime :
le modele live dans DSS fait foi. Le dump revenus date du 2026-06-22 et precede
le re-ajout de `Solution` du 2026-07-08 : un re-dump est a faire (`ACTION = "dump"`).

Pourquoi une action repoint : dupliquer un projet DSS ne reecrit PAS les refs
dataset des modeles semantiques (le `datasetRef` et les tables des golden queries
restent sur la cle du projet source). `ACTION = "repoint"` corrige cela depuis le
clone, modele par modele ; le notebook `02_align_clone.py` de la factory fait la
meme chose pour TOUS les modeles d'un coup.

## Deploiement

Un modele ne se "colle" pas : on modifie le modele live via SON fichier Python.

1. Coller le fichier du modele dans un notebook DU projet DSS vise (jamais ailleurs).
2. Choisir l'ACTION dans le CONFIG ; DRY_RUN d'abord, lire la sortie, puis
   repasser DRY_RUN = False et re-executer.
3. Re-indexer apres une modif de structure ou de dataset (`repoint` le fait ;
   les mises a jour d'instructions en place s'en passent).
4. Re-dumper le `.v1.json` dans le repo (`ACTION = "dump"`) et committer.

Le texte "Description for LLM" de chaque tool se met a jour a la main dans DSS
depuis [`TOOL_DESCRIPTIONS.md`](TOOL_DESCRIPTIONS.md). Une modif de modele seul
ne demande aucun re-collage d'agent (les agents referencent le tool par id).

Runbook pour ajouter un domaine : [`../../docs/PLAYBOOK_ADD_AGENT.md`](../../docs/PLAYBOOK_ADD_AGENT.md).
Deploiement de la v1.3 (agent factory) : [`../../docs/DEPLOY_V1_3_DEV.md`](../../docs/DEPLOY_V1_3_DEV.md).
