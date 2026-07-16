# semantic-models/ : les cerveaux SQL des sous-agents

Un modele semantique est l'objet Dataiku qui traduit une question en langage
naturel en requete SQL. Chaque sous-agent a le sien et l'interroge via son tool
"Semantic Model Query" (voir [`../agent-tools/README.md`](../agent-tools/README.md)).
Les modeles vivent dans DSS (source de verite) ; ce dossier en garde le miroir :
snapshots de reference, textes a coller et scripts d'iteration.

## Dans Dataiku

Projet DSS `OWISMIND_PRD_V1_2`, section GenAI de l'UI (que ce dossier `genai/`
miroite). Deux modeles, un par domaine :

| Modele | Id | Tool | Sous-agent | Etat |
|---|---|---|---|---|
| `Drive_Revenues_Semantic_Model` | `AHUh9hb` | `revenue_semantic_query` (`v4oqA6R`) | `SalesDrive_revenue_expert` (`agent:bHrWLyOL`) | Repointe vers le dataset du clone + colonne `Solution` re-ajoutee le 2026-07-08. VALIDE en DSS. |
| `TroubleTickets_Semantic_Model` | `dM4jA4G` | `tickets_semantic_query` (`nEirlso`) | `CSSO_Trouble_Tickets_Expert` (`agent:NcE9LD2i`) | Script de repoint vers le clone PRET (simule 4/4), PAS ENCORE lance. |

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
| `Drive_Revenues_Semantic_Model/Drive_Revenues_Semantic_Model.v1.json` | Dump de reference (`get_raw()`) du modele revenus. |
| `TroubleTickets_Semantic_Model/TroubleTickets_Semantic_Model.v1.json` | Dump de reference du modele tickets. |
| [`scripts/`](scripts/) | Les scripts de build / iteration / dump / repoint (index ci-dessous). |

Les `.v1.json` sont des photos a un instant donne, jamais importees au runtime :
le modele live dans DSS fait foi. Le dump revenus date du 2026-06-22 et precede
le re-ajout de `Solution` du 2026-07-08 : un re-dump est a faire.

### scripts/ : index

| Script | Usage |
|---|---|
| `build_aligned_semantic_model.py` | Creation one-shot du modele revenus aligne `AHUh9hb` (fait, historique). |
| `update_aligned_semantic_model.py` | Modif en place du modele revenus : instructions + golden queries (le chemin d'iteration revenus). |
| `update_tickets_semantic_model.py` | Modif en place du modele tickets : instructions, golden queries, descriptions, metriques. |
| `dump_semantic_model.py` | Export `get_raw()` d'un modele live vers son `.v1.json` (a lancer apres chaque modif). |
| `drop_column_and_reindex.py` | Retrait d'une colonne du modele + re-index (utilitaire generique, historique). |
| `migrate_semantic_model_to_project.py` | Copie d'un modele vers un autre projet avec remap (legacy, remplace par les `*_prod_clone.py`). |
| `remap_semantic_model.py` | Reecriture en place des refs dataset / tables d'un modele existant, puis re-index (legacy). |
| `repoint_tickets_prod_clone.py` | Repoint du modele tickets vers le dataset du clone + re-index (PRET, simule 4/4, pas encore lance). |
| `add_solution_and_repoint_prod_clone.py` | Re-ajout de la colonne `Solution` + repoint du modele revenus vers le clone (execute et valide en DSS le 2026-07-08). |

Pourquoi les scripts de repoint : dupliquer un projet DSS ne reecrit PAS les
refs dataset des modeles semantiques (le `datasetRef` et les tables des golden
queries restent sur la cle du projet source). Les `*_prod_clone.py` corrigent
cela depuis le clone.

## Deploiement

Un modele ne se "colle" pas : on modifie le modele live par script.

1. Lancer le script depuis un notebook DU projet DSS vise (jamais ailleurs).
2. DRY_RUN d'abord, lire la sortie, puis executer pour de vrai.
3. Re-indexer apres une modif de structure ou de dataset (les mises a jour
   d'instructions en place s'en passent).
4. Re-dumper le `.v1.json` dans le repo (`dump_semantic_model.py`) et committer.

Le texte "Description for LLM" de chaque tool se met a jour a la main dans DSS
depuis [`TOOL_DESCRIPTIONS.md`](TOOL_DESCRIPTIONS.md). Une modif de modele seul
ne demande aucun re-collage d'agent (les agents referencent le tool par id).

Runbook pour ajouter un domaine : [`../../docs/PLAYBOOK_ADD_AGENT.md`](../../docs/PLAYBOOK_ADD_AGENT.md).
Deploiement de la v1.3 (agent factory) : [`../../docs/DEPLOY_V1_3_DEV.md`](../../docs/DEPLOY_V1_3_DEV.md).
