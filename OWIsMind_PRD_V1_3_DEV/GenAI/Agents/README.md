# Code Agents

Les 3 Code Agents LangGraph du projet : le fichier Python complet de chaque agent, colle tel quel dans son Code Agent DSS (env Python 3.11). Le repo est la source de verite, DSS n'est qu'une copie.

## Dans Dataiku

Projet `OWISMIND_PRD_V1_2` (clone de `OWISMIND_DEV`, ids DEV conserves), rubrique GenAI > Agents. Chaque fichier correspond a un Code Agent, environnement de code Python 3.11 (langchain/langgraph).

## Dans ce dossier

| Fichier | Code Agent DSS | Id |
|---|---|---|
| `OWIsMind_orchestrator.py` | OWIsMind_orchestrator | `038G7mlF` |
| `SalesDrive_revenue_expert.py` | SalesDrive_revenue_expert | `bHrWLyOL` |
| `CSSO_Trouble_Tickets_Expert.py` | CSSO_Trouble_Tickets_Expert | `NcE9LD2i` |

- **OWIsMind_orchestrator** : chatte, raisonne et route vers les sous-agents ("sub-agents as tools"). Il ne detient AUCUN chiffre metier : chaque valeur vient d'un sous-agent (SQL) ou du tool `attribute_lookup`, il ne peut donc pas en inventer.
- **SalesDrive_revenue_expert** : expert du dataset `DRIVE_Revenues` (moteur generique, configure par le CONFIG en tete de fichier).
- **CSSO_Trouble_Tickets_Expert** : expert du dataset `TroubleTickets_year`. Meme moteur que le sous-agent revenus, seul le CONFIG differe.

Les deux sous-agents suivent le pipeline UNDERSTAND -> RESOLVE -> QUERY -> RENDER : comprendre la question (1 appel LLM, JSON strict), ancrer les termes sur le value index (SQL inline read-only), deleguer le SQL au tool Semantic Model Query, puis rendre chiffres et tableau par code. Execution toujours read-only.

Garde-fous communs : fichiers autonomes (stdlib + `dataiku` + `langgraph` uniquement), aucune valeur metier en dur, contrats geles avec la webapp (event kinds, `AGENT_RESULT`, spans `semantic-model-query` : ne jamais renommer, seulement ajouter). Les agents lisent le Config & Prompt Hub `/owismind_hub/` (project library) a leur demarrage, avec repli sur leurs defauts embarques si le hub est absent.

## Deploiement

- Coller le fichier ENTIER dans le Code Agent DSS correspondant (env 3.11). Les ids sont inscrits dans le CONFIG de chaque fichier ; les verifier contre `../../README.md` / `../../registry.json`.
- Quand l'orchestrateur ET le sous-agent revenus changent, recoller LES DEUX ensemble (le contrat vit des deux cotes).
- Jamais d'edition directe dans DSS : elle serait ecrasee au prochain collage.
- Guide de deploiement complet : [`../../docs/DEPLOY_V1_3_DEV.md`](../../docs/DEPLOY_V1_3_DEV.md).
