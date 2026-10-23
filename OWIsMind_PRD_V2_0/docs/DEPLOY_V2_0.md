# Mise a jour de la V2 en DSS (version du 2026-10-22)

> Point de depart : la V2 deployee et validee le 2026-10-15 (plugin `owismind_v2_0`).
> Inventaire verifie par diff git entre cette version (commit 91bdbef) et la version actuelle.
> Tous les chemins partent de `OWIsMind_PRD_V2_0/`.
> Regle pour chaque fichier : dans DSS, tout selectionner, supprimer, coller le fichier ENTIER, Save.

## 1. Ce qui change (6 elements, dans cet ordre)

| # | Ou dans DSS | Fichier a coller | Ce que ca apporte |
|---|---|---|---|
| 1 | Plugins > `OWIsMind v2.0` > Upload a new version | `plugin/ready-for-dataiku/owismind_v2_0-upload.zip` | Studio (cartes deplacables et elargissables, ecran d'attente, focus d'une carte), boutons de suggestion, continuite du Studio, backend associe |
| 2 | Projet > `</>` Libraries > `python/owismind_hub/prompts/orchestrator_persona.md` | `project-library/python/owismind_hub/prompts/orchestrator_persona.md` | LE prompt de l'orchestrateur : construction du Studio, suggestions, continuer ou nouveau Studio, langue de reponse, periodes comparees |
| 3 | Projet > `</>` Libraries > `python/owismind_hub/prompts/orchestrator_workflow.md` | `project-library/python/owismind_hub/prompts/orchestrator_workflow.md` | Langue de reponse dans le mode workflow (1 ligne) |
| 4 | GenAI > Agents > `SalesDrive_revenue_expert` > Code | `GenAI/Agents/SalesDrive_revenue_expert.py` | Periodes comparees sur les memes mois (ex. janvier a aout 2026 vs janvier a aout 2025, jamais une annee pleine) |
| 5 | GenAI > Agents > `CSSO_Trouble_Tickets_Expert` > Code | `GenAI/Agents/CSSO_Trouble_Tickets_Expert.py` | Meme correctif des periodes comparees |
| 6 | GenAI > Agents > `OWIsMind_orchestrator` > Code | `GenAI/Agents/OWIsMind_orchestrator.py` | Outils du Studio (continuer, remplacer, retirer une carte), suggestions de suite, detection de la langue |

## 2. Ce qui NE change PAS (ne rien toucher)

- `attribute_lookup_tool` et les tools Semantic Model Query (`revenue_semantic_query`, `tickets_semantic_query`).
- Les autres fichiers du hub : `capabilities.json`, `models.json`, `run_settings.json`, `factory_settings.json`.
- Les modeles semantiques, le Flow, les recettes, les notebooks, les experts `Invoices_expert` et
  `DeliverySnapshot_expert` (non modifies, et non actives dans `capabilities.json`).
- Les reglages de la webapp (`sql_connection`, `table_prefix`, `traces_dataset`, `log_level`) : identiques.
- Les tables SQL : aucune nouvelle table, aucune nouvelle colonne. Les Studios deja enregistres restent lisibles.
- Les identifiants dans le code : inchanges (`agent:bHrWLyOL`, `agent:NcE9LD2i`, `UUoynaL`, `v4oqA6R`, `nEirlso`).
  L'en-tete des fichiers d'agents mentionne `OWISMIND_DEV` : c'est un ancien commentaire, sans effet.

## 3. Pas a pas

**Etape 1 : le plugin.**
1. Plugins > Installed > `OWIsMind v2.0` > Settings > Upload a new version > `owismind_v2_0-upload.zip`.
   Le nom compte : ce zip porte l'id `owismind_v2_0`, celui de ta webapp. Un zip `owismind_dev` ou
   `owismind-v2_0-dev-upload.zip` installe un AUTRE plugin et ne change rien a ta webapp.
2. Si DSS propose de creer ou modifier un code env : refuser, rien de nouveau n'est requis.
3. Webapp `OWIsMind AI Agents v2.0` > Actions > **Restart backend**, attendre le statut vert.
4. Ouvrir la webapp avec Cmd+Shift+R. Controle : dans le Studio, une carte se deplace avec sa poignee
   et s'elargit avec son bouton (bascule largeur normale / pleine largeur).

**Etapes 2 et 3 : les prompts.** Le prompt de l'orchestrateur est dans la library, PAS dans l'agent,
et c'est lui qui gagne sur le prompt ecrit dans le code. Sans cette etape, l'orchestrateur garde son
comportement du 15 octobre meme avec le nouveau code. Controle : `orchestrator_persona.md` fait environ
16 500 caracteres (l'agent l'ignore en dessous de 500 ou au dessus de 20 000).

**Etapes 4 et 5 : les deux experts.** Coller, verifier que le code env est celui en Python 3.11, Save.

**Etape 6 : l'orchestrateur, toujours en dernier.** Coller, Save. Ce Save redemarre l'agent et lui fait
relire les prompts des etapes 2 et 3. Sans lui, l'ancien prompt reste en memoire, meme dans une
nouvelle conversation.

## 4. Controle (une NOUVELLE conversation par test)

1. "Bonjour" : reponse simple, pas de Studio, pas de boutons de suggestion.
2. "Revenus 2026 YTD par produit, actuals vs budget" : plan au-dessus du prompt, Studio qui s'ouvre seul,
   cartes deplacables, 2 ou 3 boutons de suggestion sous la reponse.
3. Dans la meme conversation, "Garde ce graphique et ajoute en dessous le meme sur 2025" : le Studio
   garde ce qui existe et ajoute la nouvelle carte.
4. "Revenus janvier a aout 2026 vs la meme periode 2025" : les deux chiffres couvrent les memes mois.
5. Une question en anglais : reponse en anglais.
6. Theme sombre : le Studio reste lisible.

## 5. Si quelque chose ne marche pas

| Symptome | Cause probable | Quoi faire |
|---|---|---|
| Cartes du Studio fixes | mauvais zip, ou cache navigateur | verifier le nom du zip (etape 1), Cmd+Shift+R |
| Pas de boutons de suggestion, Studio qui repart de zero | ancien prompt actif | refaire les etapes 2, 3 puis le Save de l'etape 6 |
| "The agent is temporarily unavailable" | erreur d'un agent | Quick test de l'agent concerne, log du backend de la webapp |
| Erreur au demarrage du backend | upload incomplet | re-uploader le zip, Restart backend, lire l'onglet Log |

## 6. Simulateur et DSS

Le simulateur fait tourner une copie des agents ecrite en JavaScript, avec les memes regles de prompt, sur
des donnees synthetiques. En DSS tournent les vrais agents Python, les vrais modeles semantiques et le
modele Mesh de chaque mode. L'interface et les regles sont identiques ; les formulations et les chiffres
peuvent differer.
