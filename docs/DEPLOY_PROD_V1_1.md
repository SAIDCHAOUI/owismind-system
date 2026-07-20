# Déploiement PROD v1.1 - runbook (2026-07-06)

> ⚠️ **RUNBOOK SUPERSÉDÉ (historique).** Ce document décrit la release **v1.1.0** et l'ancien modèle
> de promotion (projet DSS `OWISMIND_PROD_V1` + `tools/promote_agents_to_prod.py` : promotion fichier
> par fichier depuis DEV, ids PROD distincts). Ce modèle **n'existe plus** : la prod est désormais un
> **clone du projet DEV** (`OWISMIND_PRD_V1_2`, ids DEV conservés, `OWISMIND_PROD_V1` = legacy supprimé).
> Conservé **pour l'historique uniquement**. Runbook courant : **[DEPLOY_PROD_V1_2.md](DEPLOY_PROD_V1_2.md)**.

> Checklist de mise en production d'OWIsMind v1.1.0 dans le projet DSS de production
> (« OWIsMind prod v1 »). Tout ce qui est repo est DÉJÀ PRÊT (zip packagé, agents PROD
> promus depuis DEV) ; ce document liste les gestes DSS, dans l'ordre.
> Carte des ids agents : `dataiku-agents/OWISMIND/README.md`.

## 0. Ce que contient cette release

- **Plugin `owismind` v1.1.0** (`OWIsMind_PRD_V1_3_DEV/plugin/ready-for-dataiku/owismind-upload.zip`, bundle
  `index-DDxpe_gw.js`) : tout le travail validé en DSS sur dev_v2 jusqu'au 2026-07-06
  inclus : Source Data v1-v3 (agrégats DB, zone Calculer, plages de dates, cascade,
  persistance des vues, menu de colonne, tri 3 états, colonnes filtrées orange),
  contexte écran -> agent (consentement + transparence `screen_ctx`), analytics d'usage
  (`webapp_events_v1` + `/track`), mode éphémère + mode par réponse, benchmark view,
  budget, evidence trust layer, artefacts natifs.
- **Agents PROD promus** (`dataiku-agents/OWISMIND/OWISMIND_PROD_V1/`) : orchestrateur,
  expert revenus, tool `attribute_lookup`, script semantic model : à re-coller (voir §3).
  L'expert **tickets reste volontairement HORS PROD** (encore en construction en DEV ;
  l'orchestrateur PROD répond honnêtement « pas encore d'agent pour ce domaine »).

## 1. Plugin (instance)

1. Administration > Plugins : **supprimer les plugins dev** `owismind_dev` et
   `owismind_dev_v2` (ils dégagent : la prod les remplace).
2. Uploader `OWIsMind_PRD_V1_3_DEV/plugin/ready-for-dataiku/owismind-upload.zip` (plugin id `owismind`,
   version 1.1.0). Si une ancienne copie « Development » du même id existe, la
   supprimer d'abord (un plugin Development ne s'update pas par zip).
3. Le plugin est instance-wide : l'update suffit, la webapp se crée par projet (§2).

## 2. Projet DSS de production (« OWIsMind prod v1 »)

1. **Datasets** : importer/brancher `DRIVE_Revenues` (PostgreSQL, connexion `SQL_owi`),
   puis exécuter les 3 recettes du Flow (`profile`, `value_index`, `value_catalog` :
   fichiers dans `dataiku-agents/OWISMIND/OWISMIND_PROD_V1/recipes/`, identiques au DEV)
   pour matérialiser `DRIVE_Revenues_profile` / `_value_index` / `_Value_Catalog`.
   `DRIVE_Revenues_value_index` DOIT être sur la connexion SQL.
2. **Webapp** : créer la webapp du plugin (`OWIsMind AI agents`) dans le projet.
   Settings webapp : connexion SQL = `SQL_owi`. Les tables applicatives se créent
   toutes seules au premier démarrage, préfixées par la clé du projet
   (`<PROJECT_KEY>_owismind_...`) : la prod démarre avec des conversations/le budget
   à zéro, c'est voulu (aucune donnée dev ne migre).
3. **Permissions** : donner l'accès au projet/webapp aux utilisateurs de la bêta ;
   la webapp doit pouvoir lire la connexion SQL.

## 3. Agents : deux scénarios

### Scénario A : les Code Agents restent dans le projet `OWISMIND_PROD_V1` (recommandé, zéro id à changer)

Les ids PROD sont déjà bakés dans les fichiers du repo. Coller tel quel :

| Geste | Fichier repo | Objet DSS |
|---|---|---|
| Coller (Code Agent, env 3.11) | `OWISMIND_PROD_V1/agents/OWISMIND_PROD_V1_OWIsMind_orchestrator.py` | `Xrv7GvfG` |
| Coller (Code Agent, env 3.11) | `OWISMIND_PROD_V1/agents/OWISMIND_PROD_V1_SalesDrive_revenue_expert.py` | `uO5hEzAs` |
| Coller (Custom Python tool) | `OWISMIND_PROD_V1/tools/OWISMIND_PROD_V1_attribute_lookup_tool.py` | `szOZCoU` |
| Exécuter en notebook (projet PROD) | `OWISMIND_PROD_V1/semantic_model/update_aligned_semantic_model.py` | modèle `a7K9jYk` |
| Puis re-dump en notebook | `OWISMIND_PROD_V1/semantic_model/dump_semantic_model.py` | coller la sortie dans `Drive_Revenues_Model.v1.json` |

Dans la webapp (espace admin), ajouter l'orchestrateur : la whitelist est dynamique et
cross-projet, on choisit le projet `OWISMIND_PROD_V1` puis l'agent `OWIsMind_orchestrator`
depuis l'interface : aucun id à saisir.

### Scénario B : les Code Agents sont recréés dans le nouveau projet

Créer dans le nouveau projet : les 2 Code Agents (env 3.11), le Custom Python tool
`attribute_lookup`, le tool « Semantic Model Query » `revenue_semantic_query`
(Agent mode OFF, LLM Sonnet) et le modèle sémantique (le copier depuis DEV avec
`dataiku-agents/OWISMIND/migrate_semantic_model_to_project.py`, ou le recréer). Les
datasets du §2.1 doivent vivre dans CE projet. Puis remplacer les ids dans les fichiers
PROD (et reporter les nouveaux ids dans `OWISMIND/README.md`, `registry.json` et les
tables de substitution de `tools/promote_agents_to_prod.py`) :

| Fichier | Emplacements à éditer |
|---|---|
| `..._OWIsMind_orchestrator.py` | en-tête (l.2-3), `LOOKUP_TOOL_ID = "szOZCoU"`, `CAPABILITIES["revenue_expert"]["agent_id"] = "agent:uO5hEzAs"` (+ le commentaire l.24) |
| `..._SalesDrive_revenue_expert.py` | en-tête (l.2-3), `SEMANTIC_TOOL_ID = "sgk5pfln"` (+ le commentaire l.29) |
| `..._attribute_lookup_tool.py` | en-tête (l.2-3) |
| `semantic_model/update_aligned_semantic_model.py` | `NEW_MODEL_ID`, `PHYSICAL_TABLE` (table du nouveau projet), `get_project("...")` |

Ordre : créer le sous-agent revenus AVANT de coller l'orchestrateur (son id doit exister).

## 4. Promotions futures (une commande)

Le workflow reste : développer en DEV, valider, puis promouvoir. La promotion des
fichiers agents est désormais scriptée :

```bash
python3 tools/promote_agents_to_prod.py
```

(régénère les 4 fichiers PROD depuis les sources DEV, ids PROD bakés, bloc tickets
retiré, garde-fous id/tirets/py_compile + diffs résiduels affichés). Ensuite : re-coller
les fichiers en DSS et re-dater `registry.json`.

## 5. Smoke tests de mise en service

1. `/owismind-api/ping` répond ; la webapp charge (thème clair + sombre).
2. Question revenus simple (« billed revenue 2025 ») : réponse chiffrée + timeline live
   + Evidence panel avec le SQL + badge de confiance.
3. Onglet Source data : filtres (picker cherchable, plage de dates sur `year_month`),
   zone Calculer (Somme/Médiane), menu de colonne + tri 3 états, colonnes filtrées orange.
4. Contexte écran : filtres actifs + prompt -> bandeau de consentement -> Inclure ->
   la réponse exploite les chiffres à l'écran ; la ligne « Contexte écran joint »
   survit au rechargement.
5. Modes : Smart par défaut, Pro/Claude éphémères (reset à l'envoi), mode affiché dans
   la ligne tokens/coût ; budget 50 $ visible.
6. Question tickets (« combien de tickets ouverts ? ») : refus honnête « pas encore
   d'agent pour ce domaine » (PAS une invention, PAS un déni des données).
7. Admin : fiche d'agent (datasets sources), analytics `webapp_events_v1` qui se remplit,
   benchmark view (si la variable/les tables LAB sont branchées).

## 6. Après validation

- Étiqueter la release côté repo si souhaité (`git tag v1.1.0`, poussé par l'user).
- Les améliorations futures se développent depuis cette base : re-création d'un plugin
  dev coexistant possible à la demande via `OWIsMind_PRD_V1_3_DEV/plugin/tools/build_dev_plugin.py` (conservé).
