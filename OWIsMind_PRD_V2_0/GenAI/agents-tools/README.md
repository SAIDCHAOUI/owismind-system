# agent-tools/ - les Agent tools DSS

Miroir des Agent tools de l'ecran GenAI du projet DSS `OWISMIND_PRD_V1_2`.
Un seul tool a du code Python a versionner ici ; les autres sont des objets
de configuration DSS, sans code a stocker.

## Dans Dataiku

Ecran **GenAI > Agent tools** du projet. Trois tools actifs :

| Tool | Id | Type | Appele par |
|---|---|---|---|
| `attribute_lookup_tool` | `UUoynaL` | Custom Python tool | l'orchestrateur (`OWIsMind_orchestrator`, `038G7mlF`), les deux domaines |
| `revenue_semantic_query` | `v4oqA6R` | Semantic Model Query (Custom_agent_tool) | le sous-agent revenus (`SalesDrive_revenue_expert`) |
| `tickets_semantic_query` | `nEirlso` | Semantic Model Query (Custom_agent_tool) | le sous-agent tickets (`CSSO_Trouble_Tickets_Expert`) |

`Drive_Revenues_resolve_filter_value` (`aNxeOc4`) est un ancien tool legacy,
appele par personne, en attente de suppression dans DSS ; son code n'est pas
miroite ici (code mort).

## Dans ce dossier

| Fichier | Role |
|---|---|
| [`attribute_lookup_tool.py`](attribute_lookup_tool.py) | Code du Custom Python tool `attribute_lookup` (`UUoynaL`) : lecture rapide de valeurs pour l'orchestrateur. Une recherche `ILIKE` (insensible casse et accents) sur les colonnes texte du dataset, puis repli sur le Value_Catalog pour suggerer des alias proches. Lecture seule (statement_timeout + transaction_read_only), resultats bornes par LIMIT, aucun nom de colonne en dur. |

Les deux tools "Semantic Model Query" (`revenue_semantic_query`,
`tickets_semantic_query`) sont configures dans l'UI DSS, PAS du code : ils
pointent chacun un modele semantique. Leur texte "Description for LLM" a
coller vit dans [`../semantic-models/TOOL_DESCRIPTIONS.md`](../semantic-models/TOOL_DESCRIPTIONS.md) ;
les modeles eux-memes sont documentes dans [`../semantic-models/`](../semantic-models/README.md).

## Deploiement

Editer `attribute_lookup_tool.py` ICI, puis coller le fichier entier dans le
Custom Python tool DSS (`UUoynaL`). Le repo est la source de verite : toute
edition directe dans DSS est ecrasee au prochain collage. Rappel de deploiement
general : [`../../CLAUDE.md`](../../CLAUDE.md) ; guide de deploiement v1.3 :
[`../../docs/DEPLOY_V1_3_DEV.md`](../../docs/DEPLOY_V1_3_DEV.md).
