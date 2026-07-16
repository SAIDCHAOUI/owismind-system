# Déploiement PROD v1.2 - runbook (courant, 2026-07-10)

> Runbook de mise en production d'OWIsMind **v1.2.0**. Il remplace
> [DEPLOY_PROD_V1_1.md](DEPLOY_PROD_V1_1.md) (supersédé : ancien modèle de promotion fichier par fichier).
> Carte des ids agents/tools/modèles : `OWIsMind_PRD_V1_2/README.md` + `OWIsMind_PRD_V1_2/registry.json`.
>
> **Source de vérité = la mémoire** (`memory/`), pas ce document. Les commandes vivent dans les skills
> `/build-plugin`, `/package-plugin`. Ici : le *quoi* et le *dans quel ordre*.

## 0. Modèle de prod (à comprendre avant tout)

La production **n'est plus** une promotion fichier par fichier depuis DEV. Le projet DSS de prod
**`OWISMIND_PRD_V1_2`** (clé `OWISMIND_PRD_V1_2`) est une **DUPLICATION du projet DEV `OWISMIND_DEV`** :
tous les ids d'objets (agents, tools, modèles sémantiques, datasets) sont les **ids DEV conservés**, et
l'expert tickets est **inclus**. Il n'y a **aucun** id PROD distinct à baker, **aucun**
`promote_agents_to_prod.py`, **aucun** projet `OWISMIND_PROD_V1` (= legacy supprimé).

Conséquence : promouvoir = **dupliquer DEV** dans DSS une fois, puis, à chaque itération, **re-coller**
le code source du repo (agents, tool) et **re-uploader** le plugin. La source de vérité du code agentique
est `OWIsMind_PRD_V1_2/` (le vieux dossier `dataiku-agents/` n'existe plus).

## 1. Plugin (instance) - v1.2.0, id `owismind`

1. **Builder le frontend** via le skill **`/build-plugin`** (`npm run build` →
   `Plugin/owismind/resource/owismind-app/`, puis recopie `index.html` → `body.html`). NO-INSTALL : si
   `node_modules` manque, s'arrêter et demander à l'utilisateur (l'agent n'installe jamais).
2. **Packager** via le skill **`/package-plugin`** → `Plugin/ready-for-dataiku/owismind-v1_2-upload.zip`
   (nom dérivé de `plugin.json` : version `1.2.0` → `v1_2`, runtime seul, sans `frontend/`/`node_modules/`).
3. **Uploader dans DSS** : Administration > Plugins > Upload, plugin id `owismind`, version 1.2.0. Si une
   copie « Development » du même id existe, la supprimer d'abord (un plugin Development ne s'update pas par
   zip). Le plugin est instance-wide : l'update suffit.
4. **Webapp** : `webapp-owismind-ai-agents` vit **dans le projet de prod** `OWISMIND_PRD_V1_2`. Settings
   webapp : connexion SQL = `SQL_owi`. Les tables applicatives se créent au premier démarrage, préfixées
   par la clé du projet (`OWISMIND_PRD_V1_2_owismind_...`). Puis **Start/Restart backend** + refresh forcé
   du navigateur.

## 2. Agents (Code Agents DSS)

Source de vérité = **`OWIsMind_PRD_V1_2/genai/agents/*.py`** (miroir verbatim de ce qui est collé dans DSS) :

| Fichier repo | Objet DSS | id |
|---|---|---|
| `OWIsMind_PRD_V1_2/genai/agents/OWIsMind_orchestrator.py` | Code Agent orchestrateur | `038G7mlF` |
| `OWIsMind_PRD_V1_2/genai/agents/SalesDrive_revenue_expert.py` | Code Agent sous-agent revenus | `bHrWLyOL` (ref `agent:bHrWLyOL`) |
| `OWIsMind_PRD_V1_2/genai/agents/CSSO_Trouble_Tickets_Expert.py` | Code Agent sous-agent tickets | `NcE9LD2i` (ref `agent:NcE9LD2i`) |
| `OWIsMind_PRD_V1_2/genai/agent-tools/attribute_lookup_tool.py` | Custom Python tool `attribute_lookup_tool` | `UUoynaL` |

Ces fichiers étant un clone de DEV, **les ids sont déjà bons** : quand le code change, il suffit de le
**re-coller** dans le Code Agent / tool DSS correspondant (env 3.11). Aucun id à réécrire. Dans la webapp
(espace admin), la whitelist est dynamique et cross-projet : choisir le projet `OWISMIND_PRD_V1_2` puis
l'agent `OWIsMind_orchestrator` (aucun id saisi à la main). Détail des ids et du workflow d'ajout d'agent :
`OWIsMind_PRD_V1_2/README.md` + `registry.json` + `PLAYBOOK_ADD_AGENT.md`.

## 3. Modèles sémantiques

Dupliquer un projet DSS **ne repointe pas** les modèles sémantiques (`datasetRef` + table des golden
queries restent sur DEV) ; l'UI ne le corrige pas. Il faut des scripts de repoint lancés **depuis un
notebook du clone** (`OWIsMind_PRD_V1_2/genai/semantic-models/scripts/`).

- **Revenus** (`Drive_Revenues_Semantic_Model` = `AHUh9hb`) : **FAIT et VALIDÉ en DSS (2026-07-08)**.
  Repointé sur le dataset du clone (`datasetRef OWISMIND_PRD_V1_2.DRIVE_Revenues`, table physique
  `"OWISMIND_PRD_V1_2_drive_revenues"`) et colonne d'offre **`Solution` re-ajoutée**
  (script `add_solution_and_repoint_prod_clone.py`). Hiérarchie d'offre restaurée
  `SolutionLine > Solution > Product` ; ordre de préférence de grounding : 1.Product 2.Solution
  3.SolutionLine 4.sirano_product. **Rien à refaire.**
- **Tickets** (`TroubleTickets_Semantic_Model` = `dM4jA4G`) : **repoint EN ATTENTE**. Script prêt et
  simulé (4/4) : `OWIsMind_PRD_V1_2/genai/semantic-models/scripts/repoint_tickets_prod_clone.py`. À lancer
  **depuis un notebook du clone** : d'abord `DRY_RUN` (vérifier le remap `<KEY>.` + `<KEY>_`), puis
  exécution réelle, puis **re-index** du modèle et **re-dump** (mettre à jour le `.v1.json` du repo).

## 4. Smoke tests de mise en service

1. `/owismind-api/ping` répond ; la webapp charge (thème clair + sombre).
2. **Revenus (end-to-end)** : une question revenus simple (« billed revenue 2025 ») → réponse chiffrée +
   timeline live + Evidence panel avec le SQL généré + badge de confiance. Vérifier le grounding `Solution`
   dans le Playground revenus.
3. **Tickets (après le repoint §3)** : une question tickets (« combien de tickets ouverts ? ») → réponse
   chiffrée via le sous-agent tickets (plus de refus « pas d'agent pour ce domaine »).
4. **Datasets webapp** : `OWISMIND_PRD_V1_2_beta_owismind_webapp_events_v1` (analytics d'usage) et
   `beta-owismind_webapp_traces_v2` (traces d'agent) reçoivent bien des lignes après quelques échanges.

## 5. Versioning (prochaine version)

- Une **branche git par version**, nommée d'après le projet DSS de prod. `OWIsMind_PRD_V1_2` = branche de
  prod courante (source de vérité). La prochaine version se développe sur **`OWIsMind_PRD_V1_3-dev`** (hub
  de feedback utilisateur, WIP), avec le **plugin dev coexistant** `owismind_dev` (via
  `tools/build_dev_plugin.py`, zip `owismind-v1_3-dev-upload.zip` une fois son `plugin.json` en `1.3.x`).
- À la **validation** d'une version dev : on **retire le suffixe `-dev`** (la branche devient la nouvelle
  branche de prod) et on **supprime l'ancien zip**. La branche `main` est dépréciée.
