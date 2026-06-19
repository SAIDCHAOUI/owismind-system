# PLAN AGENTS - Scaling OWIsMind (Mission 2)

> Plan d'amélioration step-by-step de l'**architecture des agents** : transformer l'orchestrateur + le sous-agent revenus qui marchent en **template/factory** pour ajouter des specialistes (tickets, facturation, opportunites, experience client...) par config + un prompt + un dataset, sans la longue calibration qu'a demandee l'agent revenus.
> Produit en session multi-agents (lecteurs du code reel + recherche etat de l'art + architectes + 5 critiques adversariales). **Aucune implementation, aucun commit.**
> Plan jumeau : `PLAN_WEBAPP.md`. Le socle de gouvernance (Phase 0) est transverse aux deux missions et reference des deux cotes.

---

## 0. Thèse et regle de lecture

Bonne nouvelle d'emblee : **l'orchestrateur est deja ~95% data-driven** (`CAPABILITIES` + `BUSINESS_DOMAINS` + `build_tool_specs` ; le commentaire du code dit litteralement "adding a sub-agent is one more entry here") et **le sous-agent est deja ~90% pilote par le `Profile`** (UNDERSTAND genere du profil, RESOLVE sur le value_index, RENDER formate du profil). La "factory" consiste surtout a **consolider ~7 constantes revenus derriere une config, exposer les fragments de prompt en blocs injectables, et batir un harnais de calibration** - pas une reecriture.

Le cout irreductible, c'est la **curation semantique humaine** (golden queries verifiees contre la vraie donnee, semantique de scenario/exclusion, hierarchies, alias jargon). La factory rend gratuit tout ce qui ENTOURE cette curation, et rend la curation elle-meme **rapide et verifiable**.

**Headline honnete** (correction adversariale majeure) : la factory rend le **code** gratuit (c'etait deja ~10% du cout) ; la **calibration semantique** reste chere mais devient test-gatee. On ne promet PAS "ajouter un agent en jours".

**Chaque chantier a 6 champs** : (a) quoi, (b) valeur persona, (c) approche technique avec fichiers/contrats reels, (d) effort + install, (e) risque / surete / securite / contrats geles, (f) dependances + phase. **Statuts VERIFIED / NEEDS-DSS-VALIDATION** comme dans le plan webapp.

---

## 1. Cinq verites transverses a graver (corrections de la revue adversariale)

1. **"Ajouter un agent en jours" est malhonnete.** La factory supprime le travail de CODE (deja minoritaire). La calibration intrinseque (golden queries, semantique de scenario non-sommable, hierarchies, alias) est **par-domaine et irreductible** : c'est exactement ce qui a coute ~4-5 sessions a l'agent revenus. Estimation realiste d'un domaine SIMPLE : **~2-3 sessions**, et **seulement apres** avoir confirme que le dataset est mono-table et que le chemin de metrique non-monetaire fonctionne. Headline a tenir : "la factory rend la partie pas chere gratuite ; la partie chere reste chere, juste test-gatee".

2. **La genericisation (codegen Path B) = 1-2 sessions de chirurgie risquee sur contrats geles, pas "un jour".** Les morceaux revenus sont **entrelaces dans le corps du moteur**, pas dans un en-tete propre : le bloc "MONEY/TRANSPARENCY" de la `PERSONA`, le fragment hierarchie d'offre dans `build_semantic_question`, `defer_multicolumn_offer_terms`, la derivation `metric_unit`. Les extraire proprement EST le refactor difficile, et chaque extraction risque les contrats geles (`KNOWN_*`, `AGENT_RESULT`, span `semantic-model-query`, Profile v1). Exiger un **test CI "corps de moteur identique"** + revue adversariale. L'invariant "moteur byte-identique" CASSE si un domaine a besoin d'un noeud different (ex. metrique de duree pour tickets -> `metric_unit`/`format_cell` derivent la devise du nom de colonne et n'ont jamais ete exerces en non-monetaire).

3. **Abandonner l'overlay runtime de `enabled_agents`.** `get_capabilities()` lit le **dict statique du module**, PAS la base. Une lecture DB dans le fichier d'agent (qui ne peut pas importer le plugin) violerait la contrainte de paste-standalone ET ajouterait une surface DB sur le hot-path. Donc : le registry est une **entree de codegen au BUILD** (Path B) ; `enabled_agents` ne porte que les champs **editoriaux** admin (label/desc/icone/badge/enabled/source_url). `allowed_tables`/`lookup_dataset`/ids semantiques restent dev-owned dans `registry.json`, jamais editables admin, jamais atteignables par `validate_agent_meta`.

4. **La concurrence reelle du 360 = `MAX_CONCURRENT_RUNS`(8) x `MAX_PARALLEL_AGENTS`(3) = 24 sous-agents simultanes**, pas 3. Soit jusqu'a 24 appels Sonnet + ~48 requetes PostgreSQL sur une connexion partagee, depuis un backend mono-process. Requis : un **semaphore GLOBAL sur le total de sous-agents en vol** (pas par-run) ; compter un 360 comme **N slots de run**, pas 1. **Ne PAS augmenter `MAX_PARALLEL_AGENTS`.**

5. **Les recipes `value_index` et `value_catalog` n'ont AUCUN cap de lignes** (table entiere -> pandas RAM, `get_dataframe` non garde ; seul le profiler cape a 2M). La factory onboarde des datasets plus gros/inconnus (tickets, facturation) -> risque OOM sur noeud DSS partage. Requis : (a) **caper uniformement les 3 recipes** + lecture chunked/`LIMIT` ; (b) recipes = **scenarios programmes off-peak UNIQUEMENT**, jamais declenches depuis l'UI webapp/admin ; (c) **precondition de taille max** par domaine ; (d) **valider mono-table-ness ET chemin metrique non-monetaire par dataset AVANT** de budgeter une session.

---

## 2. PHASE 0 - Socle de gouvernance (AVANT tout 2e agent)

Quand le nombre d'agents N croit, le blast radius croit en N (surface d'hallucination) et le cout en N (et 3N pour un 360). Ce socle est **prerequis, pas confort** : la ligne rouge utilisateur est "un faux chiffre revenu = desengagement permanent", et ce risque se multiplie par domaine.

**A0.1 - Journal d'audit `webapp_audit_v1` (le prerequis le moins cher, a front-loader)** [VERIFIED]
- (a) Append-only : `run_id, user_id, model, tokens, cost, tools[], sql[], quota_state, trust_level, reconcile_flag, action_type`.
- (b) Tous (debug, conformite, decisions data-driven sur cache/quota).
- (c) Nouveau `storage/audit.py` calque sur `storage/usage.py` (parametrise + COMMIT + `statement_timeout`, no-ALTER `_vN`), ecrit depuis `agents/streaming.py` a l'evenement terminal. **Couvre runs + exports + brouillons/envois + invocations de tools** (pas seulement le chat - corrige une lacune des propositions). Write-once par convention (documenter ; idealement REVOKE UPDATE/DELETE), admin-readable, **note de retention/rotation** (croissance non bornee sinon).
- (d) **S, aucune install.**
- (e) Insert append-only borne. C'est aussi la **donnee qui rend data-driven** les decisions cache (A taux de repetition) et quota.
- (f) Prerequis transverse. Premier.

**A0.2 - Detecteur de reconciliation claim-vs-result (mode SHADOW)** [VERIFIED, correction adversariale]
- (a) Chaque nombre du recit verifie present dans le resultat capture ; flag **ecrit au journal d'abord, pas affiche**.
- (b) Garde anti-hallucination #1.
- (c) `evidence/reconcile.py` pur (modele `sql_explain.py`), appele la ou `generated_sql[].result` est deja joint (`evidence/service.py`). **Correction** : `==` naif echoue sur les formats (`1,2 M€` vs `1199847.3`) -> extracteur numerique robuste + tolerance (reutiliser `format_number` en matcher). **Livrer en shadow** (ecrire dans `webapp_audit_v1`), **mesurer le taux de faux positifs**, n'exposer un badge qu'apres fiabilite prouvee. Renommer "verifie/non verifie vs source" (prouve la tracabilite, pas la justesse).
- (d) **M, aucune install.** Surface UI cote webapp (cf. `PLAN_WEBAPP.md` W1.1).
- (e) Charge nulle (regex). Devient un **GATE** pour les livrables (bloquer un nombre non verifie dans un PDF/email, abstention > hallucination) une fois fiable.
- (f) Prerequis a tout 2e agent (le seul garde mecanique anti-hallucination).

**A0.3 - Semaphore global de concurrence des sous-agents** [VERIFIED, correction BLOCKER]
- (a) Un semaphore process-wide sur le total de sous-agents en vol, toutes sessions confondues.
- (b) Indirect (empeche le 360 de devenir la feature qui sature l'instance).
- (c) `MAX_CONCURRENT_RUNS=8` (stream_manager) x `MAX_PARALLEL_AGENTS=3` (orchestrateur) = 24 multiplicatif. Ajouter un semaphore global (ex. cap total ~6-8 sous-agents en vol) dans le chemin `_run_subagents` / `stream_manager`, et compter un 360 comme plusieurs slots de run. **Ne pas toucher `MAX_PARALLEL_AGENTS`.**
- (d) **S-M, aucune install.**
- (e) Protege la connexion `SQL_owi` partagee et le budget Mesh sous charge (plusieurs AM demandant un 360).
- (f) **Prerequis du 360** (Phase D). A poser avant d'activer le fan-out multi-domaine.

**A0.4 - Bandeau soft-quota 80% + budget gate sur routes LLM** [VERIFIED]
- (a) Avertissement non bloquant avant le 402 ; gate budget sur toute route declenchant un LLM.
- (c) `storage/budget.py` calcule deja ; ajouter le seuil 80% a `/usage` (front cote webapp W0.3). **Toute route export/tool pouvant declencher un appel LLM-backed re-applique `budget.has_budget(user_id)`** comme `/chat/start` ; distinguer les routes purement deterministes.
- (d) **S.** (e) Lecture seule + gate. (f) Avant que les 360 (3x) ne fassent flamber la depense par utilisateur.

**A0.5 - Harnais golden-query EX (squelette, palier no-LLM)** [VERIFIED]
- (a) Une suite `unittest` de regression execution-accuracy (30-50 questions/domaine), palier **sans LLM** d'abord.
- (b) Confiance ; compresse la calibration (un domaine ne ship que si sa suite est verte).
- (c) Un `seed_golden_queries.py` lit `<ds>_profile` (metriques, scenario, axes+enums) et emet ~30-50 candidats `(question, expected_filters, expected_intent)`. **Le test no-LLM** lance UNDERSTAND (`with_json_output`, deterministe) + RESOLVE (SQL pur sur value_index) **offline** et asserte `intent` + filtres resolus : c'est le 80% **CI-able, sans LLM, sans charge instance** qui attrape la derive profil/value_index (la classe de bug EVPL=budget-0). Le palier valeur (20%) = flag `--live` opt-in contre le tool semantique, **off-peak, gate** (les recipes scannent en pandas). Lazy-import pandas (L089).
- (d) **M, aucune install** (`unittest` + stdlib). (e) Palier no-LLM = gratuit ; palier live = off-peak. (f) Squelette en Phase 0, seede sur revenus, puis sur chaque nouveau domaine.

---

## 3. PHASE 1 - Fondations de la factory

**A1.1 - Le SPEC d'agent declaratif + le registry build-time** [VERIFIED design, correction overlay]
- (a) Un objet par specialiste qui decrit le domaine pour que l'orchestrateur route et que le sous-agent s'auto-configure.
- (b) Un nouveau domaine apparait en jours cote CODE (la calibration reste a part) ; l'orchestrateur dit honnetement "pas d'agent encore" en attendant (deja cable via `BUSINESS_DOMAINS`).
- (c) `CAPABILITIES` (orchestrateur) est **deja le spec cote orchestrateur**. **Correction (abandon de l'overlay runtime)** : source de verite = un `dataiku-agents/registry.json` versionne (dev-owned), **entree de CODEGEN au build**, pas une lecture DB a l'execution. `enabled_agents` ne porte que les champs editoriaux admin. Champs du spec :
  ```
  key, domain, kind:"agent", agent_id, label_fr/en, tool_name,
  planner_description,                      # SEUL signal de routage du superviseur
  block_labels{}, tool_labels{},           # timeline (DOIVENT refleter KNOWN_* - test anti-derive)
  dataset_label_fr/en, source_url, lookup_dataset, lookup_catalog, pass_context, enabled,
  profile_dataset, value_index_dataset, target_dataset,
  semantic_model_id, semantic_tool_id, semantic_tool_name,
  persona_block{fr,en},                    # paragraphe PERSONA par-domaine (cf. A2.2)
  currency_default, scope_language{scenario_label, period_label},
  resolution_hierarchy[],                  # priorite de colonnes pour termes ambigus (hierarchie d'offre generalisee)
  golden_queries_dataset, guardrails{max_rows, read_only:true, allowed_tables[]}
  ```
- (d) **S-M, aucune install** (registry + `gen_capabilities.py` codegen).
- (e) **Invariant whitelist** : le front envoie une cle logique, jamais `agent_id`/table. `allowed_tables`/`lookup_dataset` restent dev-owned dans `registry.json`. Re-passer le test anti-derive (`block_labels`/`tool_labels` <-> `KNOWN_*`) par agent.
- (f) Fondation. Phase 1.

**A1.2 - Surete + discipline des recipes de grounding** [VERIFIED, correction BLOCKER B2]
- (a) Caper et programmer off-peak les 3 recipes ; precondition de taille par domaine.
- (c) `build_value_index_recipe.py` et `build_value_catalog_recipe.py` font `get_dataframe` **sans cap** (verifie). Ajouter un cap uniforme + lecture chunked/`LIMIT`-pushed ; **runs = scenarios programmes off-peak, jamais declenches depuis l'UI** ; documenter une **taille max de dataset** dans le playbook d'onboarding ; valider mono-table par dataset.
- (d) **S, aucune install.** (e) Empeche l'OOM sur noeud partage quand on onboarde un gros dataset. (f) Prerequis de tout nouveau domaine (Phase B+).

---

## 4. PHASE 2 - Template partagé + génericisation

**A2.1 - Le template specialiste partage (codegen Path B)** [VERIFIED design, correction effort]
- (a) Un moteur unique (UNDERSTAND->RESOLVE->QUERY->RENDER) ; chaque fichier d'agent = moteur identique + en-tete de config stampe.
- (c) **Deux chemins :**
  - *Path A - lib packagee dans l'env 3.11* : chaque agent devient un shim `from owismind_specialist import build_specialist`. **Cout** : requiert une install user dans l'env 3.11, casse partiellement la propriete "paste standalone", surface de versioning. **Defere** (YAGNI tant que < 5 agents).
  - *Path B - codegen + duplication marquee (RECOMMANDE)* : garder `SalesDrive_revenue_expert.py` comme **moteur canonique** ; `gen_specialist.py` lit `registry.json` + le moteur et emet `agents/<Agent>.py` avec les ~7 constantes + `persona_block` + `resolution_hierarchy` + les blocs geles injectes dans un en-tete `# === GENERATED CONFIG (do not edit) ===`. Corps de moteur **identique** entre fichiers ; un test CI asserte `engine-body(generated) == engine-body(canonical)`.
- (d) **Correction effort** : ce n'est PAS "un jour". Les morceaux revenus sont entrelaces dans le corps (cf. verite #2) ; les extraire = 1-2 sessions de chirurgie + revue adversariale. **Aucune install** (Path B). 
- (e) **Contrats geles identiques dans chaque fichier genere** (`KNOWN_BLOCK_IDS`, `KNOWN_TOOL_NAMES`, `AGENT_RESULT`, span `semantic-model-query` `{sql,success,row_count,rows,columns,source_url}`, Profile v1) : ils font partie du corps, jamais varies par codegen. **Tension a resoudre** : si un domaine a besoin d'un noeud different (metrique de duree tickets), l'invariant "byte-identique" casse -> le codegen doit alors templater DANS le moteur (variation par type de metrique), pas seulement l'en-tete. Valider le chemin `metric_unit`/`format_cell` non-monetaire (NEEDS-DSS-VALIDATION).
- (f) Depend de A1.1. Phase 2.

**A2.2 - Génericiser les morceaux revenus** [VERIFIED, surgical]
- (c) Cibles exactes :
  - **PERSONA** : scinder en epine dorsale domaine-neutre (WHO/VOICE/LANGUAGE/HONESTY/OUTPUT/SCREEN, deja generiques) + un **bloc injecte par-domaine** assemble de `scope_language` + `currency_default` de chaque cap. Le bloc "MONEY/TRANSPARENCY" hardcode `€`/ACTUALS/BUDGET -> devient des exemples dans le spec. Le mecanisme de transparence (`[Scope]/[Périmètre]`) est deja neutre, le garder.
  - **Fragment hierarchie d'offre** (`build_semantic_question` + `defer_multicolumn_offer_terms`) : la machinerie ("terme sur >=2 colonnes = defere") est deja generique ; seule la **guidance** ("Product, then Solution... never sirano_product") est revenus. La remplacer par `SPEC.resolution_hierarchy` (liste ordonnee + note "never default to <last>"). Liste vide (la plupart des domaines) -> la deferral tire generiquement, le prompt dit "resous via tes regles semantic-model".
  - **`LOOKUP_SOURCE_CAP="revenue_expert"`** : deja a moitie generique via `lookup_domains()` ; supprimer la constante, le built-in resout dataset/catalog/source_url par domaine depuis le registry ; le fallback `agent_key` devient le `cap_key` resolu.
  - **Devise/scope** : `metric_unit` derive deja la devise du nom de colonne (generique) ; deplacer le defaut "EUR sauf indication" vers `SPEC.currency_default`.
- (d) **S-M, aucune install** (deplacements string-vers-spec). (e) Aucun risque structurel (les mecanismes existent), mais c'est la chirurgie de la verite #2. (f) Avec A2.1, Phase 2.

---

## 5. PHASE 3 - Harnais de calibration (compresser ~5 -> ~2-3 sessions)

**A3.1 - Suite golden-query complete + noeud critic** [VERIFIED]
- (a) La suite EX (A0.5) etendue + un noeud d'auto-verification dans le pipeline.
- (c) Le palier no-LLM (UNDERSTAND+RESOLVE offline) est le ratchet de qualite, **sans charge, CI-able**. Ajouter un `node_critic` optionnel apres QUERY (LangGraph `should_continue`, **zero LLM sur le happy path**) : si `rowcount==0`/all-null sur un intent structure, re-RESOLVE une fois en relache avant de repondre (garde Python pur ; vide reste une reponse valide, jamais invente). La reconciliation (A0.2) sert aussi de signal de calibration dans le harnais.
- (d) **M, aucune install.** (e) Palier no-LLM gratuit ; palier `--live` off-peak.
- (f) **Ce qui compresse la calibration** : la suite auto-seede fait surgir immediatement et de facon reproductible les modes d'echec (somme inter-scenarios, defaut sirano, alias jargon) ; l'humain ne passe ses 2 sessions que sur (a) confirmer les valeurs attendues contre la vraie donnee et (b) ecrire les 5-10 alias + regles d'exclusion - la curation irreductible. Depend de A1-A2.

**A3.2 - Le playbook "AJOUTER UN AGENT" (automatable vs humain)** [VERIFIED]
Pour un domaine `tickets` (dataset `OWISMIND_DEV_support_tickets`) :
1. **3 recipes** (profiler -> value_index -> value_catalog), config = INPUT/OUTPUT en tete. *Automatable* (off-peak, A1.2). Humain : seulement les alias jargon `BUSINESS_ALIASES`.
2. **Modele semantique DSS** (entites sur la table unique, filtres nommes, glossaire). *Semi-automatable* (scaffold du profil) ; **humain** : golden queries, semantique scenario/exclusion, scope language. **La partie lente** - le harnais (A3.1) la rend verifiable.
3. **Entree `registry.json`** (A1.1), `enabled:false` jusqu'au vert. *Automatable*.
4. **`gen_specialist.py`** -> `agents/Tickets_expert.py` (moteur identique, en-tete stampe) ; **`gen_capabilities.py`** -> `CAPABILITIES` mis a jour. *Automatable*.
5. **Seed + curation golden queries** (A0.5/A3.1) : `seed_golden_queries.py` emet les candidats ; **humain confirme les valeurs attendues**. Suite no-LLM verte requise.
6. **Paster les 2 fichiers en DSS** (nouveau Code Agent env 3.11 + re-paste orchestrateur avec le nouveau `CAPABILITIES`), `enabled:true`. *Action humaine* (la contrainte standalone est respectee). Pas de zip/restart sauf python-lib change.
7. **Smoke-test** via l'orchestrateur (route par `planner_description` automatiquement, aucun code de routage touche).

**Net** : steps 1,3,4,7 automatables ; 2 et 5 portent la curation humaine irreductible ; 6 = paste mecanique. La factory supprime tout le travail de code ; reste la **curation semantique**, desormais bornee et test-gatee.

---

## 6. PHASE 4 - Domaines + 360 + livrable

**Ordre des domaines** (par (valeur x simplicite) / risque-de-calibration ; **valider mono-table-ness + metrique non-monetaire AVANT de budgeter**, verite #1/#5) :

| # | Domaine | Effort | Risque calibration | Note |
|---|---|---|---|---|
| 1 | **Tickets / incidents** | S/M, ~2-3 sessions | **Le plus bas** (statut = enum propre, pas de "ne jamais sommer", peu d'alias) | **FIRST.** Tous les personas le demandent ; partenaire naturel du 360. **NEEDS-DSS-VALIDATION** : dataset existe-t-il ? mono-table ? metrique count/duree (chemin non-monetaire de `metric_unit`/`format_cell` non exerce) ? |
| 2 | **Opportunites / pipeline** | M, ~3 sessions | Moyen (stage = hierarchie ; "pondere vs non pondere" = piege type non-sommable) | Apres tickets. Paire avec revenus pour "gagne vs forecast". |
| 3 | **Experience client / satisfaction** | S/M, ~2 sessions | Bas (scores numeriques) mais **valeur standalone plus faible** | Sa vraie valeur est DANS le 360. |
| 4 | **Facturation detaillee** | M, ~2-3 sessions | Moyen, **chevauche le domaine revenus** | **Defere** jusqu'a un vrai dataset facture-ligne distinct (YAGNI). |
| 5 | **Delivery / deploiement** | M, ~3 sessions | Eleve, **souvent multi-table** (collision ONE-TABLE) | **Last.** Necessite un dataset pre-aplati en amont du Flow. |

Cumul tickets+opportunites+satisfaction (~7 sessions) amene le 360 a une vraie valeur. Facturation/delivery = pilotes par la demande.

**A4.1 - Fiche client 360 (orchestrateur)** [VERIFIED machinerie, corrections concurrence + provenance]
- (a) Une question ("360 sur le compte X") -> l'orchestrateur fan-out `ask_revenue_expert` + `ask_tickets_expert` + `ask_opportunities_expert` en parallele pour le MEME compte resolu, puis synthese + un livrable.
- (b) Le produit phare pour **account managers** (brief pre-reunion) et **dirigeants** (sante de compte).
- (c) **Aucune nouvelle primitive d'orchestration** : `_run_subagents` fan-out existe deja. (i) **Resoudre le compte UNE fois en amont** via `attribute_lookup` (le #1 risque de justesse : chaque agent resolvant "Airbus" differemment). **Correction** : l'orchestrateur resout aujourd'hui les lookups par sous-appel, pas une fois en amont - c'est un vrai (petit) changement orchestrateur a budgeter. (ii) Le LLM emet 3 `sub_calls` en un tour -> `_run_subagents`. (iii) Chaque sous-agent renvoie son `AGENT_RESULT` gele + Evidence (provenance par-domaine intacte). PK `webapp_artifacts_v1 = exchange_id` -> **une reponse synthetisee, un livrable**.
- **Discipline de synthese (propriete de surete)** : un fragment PERSONA dit verbatim : *"Tu ne peux enoncer QUE des faits renvoyes par un sous-agent CE tour. Attribue chaque nombre a son domaine. N'INFERE JAMAIS un fait d'un domaine depuis un autre. Si un sous-agent n'a rien renvoye, dis 'pas de donnee <domaine>', ne fabrique jamais."* Extension cross-domaine du firewall d'honnetete + reconciliation (A0.2) : chaque nombre du recit 360 doit tracer a un resultat capture de sous-agent.
- **Correction provenance (charte/trust)** : un 360 a 3 domaines sans Evidence drillable par-domaine = regression de confiance au pic de blast radius. Resoudre : **re-ouvrir l'Evidence multi-agent SEULEMENT pour le 360** (drop par ailleurs, cf. `PLAN_WEBAPP.md`) OU inliner des citations taggees par domaine liant chaque nombre au resultat capture de son sous-agent.
- (d) **M, aucune install.** (e) **Surete (correction BLOCKER)** : fan-out deja cape a 3 MAIS multiplicatif 8x3=24 -> **le semaphore global A0.3 est PREREQUIS**. **Cout** : un 360 = 3x une requete -> **le quota soft (A0.4) et eventuellement le cache (A4.2) doivent PRECEDER le 360**, pas suivre.
- (f) Depend de >=2 domaines live + Phase 0 (A0.3 surtout). Le livrable synthetise est le **premier template PDF** (jonction `PLAN_WEBAPP.md` W2.1).

**A4.2 - Cache semantique** [demote a metrics-gated]
- Cf. `PLAN_WEBAPP.md` W3.1. **Correction** : la cascade route deja 85-90% petit-modele ; un 360 (3 petits appels) reste peu cher en absolu. Le cache ne paie que si repetition > ~25% (a mesurer via le journal d'audit A0.1). Risques memoire (LRU borne), peremption sur refresh (cle a timestamp + divulgation "depuis le cache"), fuite cross-user (cle owner/entitlement-aware). Cle POST-resolution dans `_run_subagents`. **Pas un prerequis du 360** ; decision data-driven.

**A4.3 - LLM-as-judge batch** [defere]
- Echantillon 10% des runs/nuit pour scorer la qualite, lit `webapp_audit_v1`, off-peak. **YAGNI jusqu'a N>=3 agents** - le harnais EX (A0.5/A3.1) couvre la regression plus cheaprement d'abord.

---

## 7. Récapitulatif de séquencement (agents)

| Phase | Chantiers | Install | Statut |
|---|---|---|---|
| **0 - Socle (avant tout 2e agent)** | audit log (A0.1), reconciliation shadow (A0.2), semaphore concurrence (A0.3), soft-quota+budget gate (A0.4), harnais EX no-LLM (A0.5) | **zero** | VERIFIED |
| **1 - Fondations factory** | registry build-time (A1.1), surete recipes off-peak (A1.2) | zero | VERIFIED |
| **2 - Template + genericisation** | codegen Path B + test engine-identite (A2.1), genericiser PERSONA/offre/lookup/devise (A2.2) | zero | VERIFIED design, 1-2 sessions chirurgie |
| **3 - Harnais calibration** | golden EX complet + node_critic (A3.1), playbook add-agent (A3.2) | zero | VERIFIED |
| **4 - Domaines + 360** | tickets (valider dataset!), opportunites, satisfaction ; 360 fiche client (A4.1) | zero | VERIFIED + NEEDS-VALIDATION par dataset |
| **defere** | cache (A4.2, metrics-gated), facturation/delivery (demande), LLM-judge (A4.3, N>=3) | - | - |

**Decision la plus tranchee** : livrer A0.2 (reconciliation) + A0.3 (semaphore) + (si construit) le cache AVANT le 360, pas apres. Le fan-out 3x du 360 est l'endroit ou le cout non-gouverne ET l'hallucination cross-domaine detonnent tous deux.

---

## 8. Exposer / consommer les tools cote agents

L'orchestrateur appelle deja des tools nativement de deux facons (VERIFIED) :
- **Built-ins in-process** : `show_chart`/`show_table`/`show_kpi`/`current_date`/`attribute_lookup`, dispatchés inline dans `node_tools`. C'est ainsi qu'on ajoutera `build_report`/`draft_email` natifs (cf. `PLAN_WEBAPP.md` W2.5) : le tool emet un spec `deliverable`, ne rend pas les bytes.
- **Managed tools DSS** : `get_agent_tool(id).run()` pour `attribute_lookup` (objet projet) et `v4oqA6R` (semantic query). C'est le pattern `BaseAgentTool` a copier pour tout nouveau tool de domaine.

Pour qu'un sous-agent d'un nouveau domaine consomme son semantic query : un objet tool DSS par domaine (comme `v4oqA6R`), reference par `semantic_tool_id` dans le spec (A1.1). Pour exposer les capacites de la webapp a des agents ETRANGERS/visuels (plugin agent tools, Track A/B/C) : c'est la section 5 de `PLAN_WEBAPP.md` (cote webapp), dont le spike S1-S4 conditionne l'architecture.

---

## 9. Contrats GELÉS (ne jamais renommer, seulement etendre)

- **Event kinds** orchestrateur/sous-agent : `START, PLANNING, CALLING_AGENT, AGENT_DONE, RUNNING_TOOL, TOOL_DONE, ARTIFACT, WRITING_ANSWER, DONE, ERROR, NARRATION, SUB_AGENT_*` (consommes par `agents/streaming.py` + reducer timeline front).
- **`KNOWN_BLOCK_IDS`** : `resolve, run_sql, format_output, clarify_user, out_of_scope_msg, about_data` (= cles de `block_labels` du registry ; test anti-derive).
- **`KNOWN_TOOL_NAMES`** : `resolve_filter_value, dataset_sql_query` (labels d'evenements).
- **`AGENT_RESULT`** : `{status, language, intent, resolvedFilters, sqlCount, rowCount, attempts}`.
- **Span `semantic-model-query`** : `{sql, success, row_count, rows, columns, source_url}` + format `sql_id` `s{step}q{n}` / `s{step}lk{n}`.
- **Profile contract v1** : `{key, payload}`, sentinelle `__dataset__`, schema payload.
- **Cles `CAPABILITIES` + `tool_name`** (`ask_revenue_expert`...) : le front envoie une cle logique, le backend resout.

Tout ajout de kind/type d'artefact = **bump coordonne** (cf. `PLAN_WEBAPP.md` verite #3) + recoll des 2 Code Agents (env 3.11) + mise a jour du test anti-derive.

---

## 10. Ce qu'on DROP / défère (YAGNI)

- **Path A (lib `owismind_specialist` packagee)** : install + casse le paste standalone + drift de version. Path B (codegen) jusqu'a 5+ agents.
- **MCP server** : DSS 14 + Python 3.10+, hors backend 3.9. Parquer.
- **Hot-reload dynamique / routing par similarite semantique** : le paste-literal + routing par `planner_description` scale a ~15 agents. Inutile maintenant.
- **LLM-as-judge** : jusqu'a N>=3 (le harnais EX couvre la regression d'abord).
- **Facturation/delivery** : pilotes par la demande et par l'existence d'un dataset mono-table reel.

---

## 11. Checklist non-négociables (par chantier)

- [ ] **#1 NO INSTALL agent** : Path B codegen = aucune install ; Path A defere. Tout dep = ASK explicite.
- [ ] **#2 Surete instance** : semaphore global concurrence (A0.3) ; recipes capees + off-peak + jamais depuis l'UI (A1.2) ; precondition taille dataset ; palier golden no-LLM gratuit, live off-peak.
- [ ] **#3 SQL direct** : grounding = SQL parametre sur value_index ; pas de Flow runtime ; pas de route SQL generique ; `guard_custom_sql` (read-only/mono-table/LIMIT) conserve.
- [ ] **#4 Whitelist agents** : `registry.json` dev-owned (`agent_id`/tables) ; `enabled_agents` editorial seulement ; `validate_agent_meta` ne touche pas les ids techniques ; front envoie une cle logique.
- [ ] **#6 No-ALTER** : `webapp_audit_v1`/cache = nouvelles tables `_vN`.
- [ ] **#7 Code anglais** ; **#8 Code Agents env 3.11** (backend reste 3.9, ne rien y mettre de langgraph) ; **#9 zero tiret long** (prose + prompts + slots LLM) ; **#10 charte** (surfaces cote webapp).
- [ ] **Contrats geles** (section 9) jamais renommes ; test anti-derive vert par agent.
- [ ] **Headline honnete** : ne jamais promettre "agent en jours" ; valider mono-table + metrique non-monetaire AVANT de budgeter un domaine.
- [ ] **Gouvernance d'abord** : A0 (audit + reconciliation + semaphore) AVANT le 2e agent ; A0.3 + quota AVANT le 360.
