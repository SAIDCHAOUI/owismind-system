---
paths: ["dataiku-agents/**"]
description: Gotchas Code Agents LangGraph (P0, P0-star, P0-star-star, P3) + process de recoll DSS. Chargees quand on touche aux agents.
---

# Gotchas agents (Code Agents LangGraph, env 3.11)

Le repo est la source de verite ; les agents se RECOLLENT dans DSS a la main. Refs lecons dans `memory/LESSONS.md`. Skill de conception : `agentique-python-dataiku`.

- **P0 - dataiku-agents v3 (L051/L052)** : l'expertise vient des ARTEFACTS du Flow (profil + value index, overrides humains jamais ecrases), pas de valeur metier dans le repo. Le SQL appartient au SEMANTIC MODEL (tool mode Agent) : extraction = priorite de cles + DERNIER texte/lignes (jamais le premier = preambule) ; question semantique = question user EN TETE + `IN` par colonne (jamais AND intra-colonne). UNE capability revenue `enabled` a la fois. Contrats geles : `KNOWN_BLOCK_IDS`/`KNOWN_TOOL_NAMES` <-> registre (test anti-derive) ; norm partagee recettes<->agent. Tests : `python3 -m unittest discover -s dataiku-agents/tests`.
- **P0-star - Agents LangGraph (L055/L056, DSS)** : les Code Agents `*_langgraph.py` tournent en env 3.11 (langchain/langgraph installes). Appels LLM NATIFS Mesh dans les noeuds (jamais `as_langchain_chat_model`) ; `get_stream_writer()` en noeud SYNC OK ; `reasoning=high` regle a la main sur le modele Mesh. `with_json_output` OBLIGATOIRE sur les extractions deterministes (UNDERSTAND) : sinon le reasoning brule le budget et casse le parse ; reasoning reserve au routing (orchestrateur tool-calling) et a la headline verifiee. Originaux `*_agent.py` = rollback intact.
- **P0-star-star - Sous-agent ASSISTE, ne DICTE pas (L058)** : `build_semantic_question` envoie au tool la question user (source de verite) + des HINTS ; il n'epingle PLUS de colonne pour un terme d'offre ambigu (`alt_columns` non vide -> `AMBIGUOUS OFFER TERM`, le modele Sonnet tranche via ses instructions). Seules les valeurs mono-colonne (noms clients) sont suggerees (anti-typo). Ne pas remettre le thinking au sous-agent ; ne pas hardcoder la hierarchie d'offre dans le code (elle vit dans les instructions du modele). Le tool "Semantic Model Query" pointe un modele precis -> repointer apres creation d'un nouveau modele ; iterer le prompt = `tools/semantic_model/update_aligned_semantic_model.py` (en place, sans re-index).
- **P3 - Anti "regles par bug" (L048, exigence user)** : jamais de valeur metier en dur dans la logique d'un agent. Cas inconnus -> comprehension LLM contrainte (liste de candidats) ou refus honnete, pas de patch par valeur.

## Process de recoll DSS (a chaque modif repo des agents)
- Recoller LES DEUX Code Agents ENSEMBLE (env 3.11) : `OWIsMind_orchestrator` + `SalesDrive_revenue_expert`. Le fix de desambiguisation vit des deux cotes (`pass_context` orchestrateur + UNDERSTAND agent).
- Agent + modele semantique ENSEMBLE (marqueur `AMBIGUOUS TERM` = contrat sous-agent <-> instructions du modele) : executer `update_aligned_semantic_model.py` en notebook puis re-dump.
- Carte des ids (DEV/PROD) : `dataiku-agents/OWISMIND/README.md` + chaque `registry.json`.
- **Promotion DEV -> PROD (L139)** : `python3 tools/promote_agents_to_prod.py` (regenere depuis DEV par script, idempotent) puis recoller les fichiers PROD. JAMAIS editer un fichier PROD a la main.
- **Sous-agents background (L140)** : le texte final n'est PAS relaye a la session principale ; exiger un `SendMessage to="main"` dans leur prompt.
