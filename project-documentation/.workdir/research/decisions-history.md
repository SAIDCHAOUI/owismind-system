# OWIsMind - Décisions d'architecture et leçons durement acquises (matériel ADR + gotchas)

> Pack de connaissances, zone "Architecture decisions and hard-won lessons".
> Sources lues : `memory/LESSONS.md` (L001-L086), `memory/CONTEXT.md`, `memory/PROJECT_STATE.md`,
> `docs/superpowers/specs/` (specs gelées), code des 2 Code Agents (`dataiku-agents/agents/`).
> Chaque affirmation est ancrée sur un fichier:ligne ou une leçon (Lxxx) effectivement lue.
> Convention : "Lxxx" renvoie à `memory/LESSONS.md` ; "spec orchestrateur" =
> `docs/superpowers/specs/2026-06-11-orchestrator-expert-authority-design.md` ;
> "spec trust layer" = `docs/superpowers/specs/2026-06-10-evidence-trust-layer-design.md`.

---

## Partie A - Décisions d'architecture (matériel ADR)

Chaque décision : Contexte/Problème, Décision, Rationale, Conséquences (+/-), Alternatives rejetées.

### ADR-01 - SPA Vue 3 + Vite servie par DSS comme assets statiques (history HASH)

- **Contexte/Problème** : DSS sert une WebApp à une URL fixe (`/plugins/owismind/resource/owismind-app/`)
  sans réécriture SPA côté serveur. Un router en mode "history path" ferait un 404 au reload ou au
  deep-link (L023).
- **Décision** : frontend Vue 3 buildé par Vite vers `resource/owismind-app/` (base
  `/plugins/owismind/resource/owismind-app/`), router en **HASH history** obligatoire
  (`createWebHashHistory`), thème posé sur `body[data-theme]` AVANT le mount (L023, CONTEXT F3/F4).
  Build officiel = skill `/build-plugin` ; jamais builder dans `resource/` pendant le dev (compile-check
  vers `/tmp` puis `rm -rf`, L023, CONTEXT F1).
- **Rationale** : DSS impose le chemin et l'absence de réécriture ; le HASH survit au reload. Les versions
  de libs sont figées (`vue-router@5.1.0`, `vue-i18n@11` legacy:false, `pinia@3`) car NO INSTALL.
- **Conséquences (+)** : déploiement = upload d'un zip d'assets statiques, aucun serveur Node en prod ;
  archi modulaire à registres (primitives `components/ui/` mutualisées, stores Pinia par domaine,
  `registries/` extensibles, L023).
- **Conséquences (-)** : URLs en `#/route` (moins propres) ; `body.html` est un fichier **généré** qu'il
  faut recâbler après chaque build, et le `cp` vers `body.html` est REFUSÉ par les permissions -> recâbler
  via l'outil Write (L033, CONTEXT F10) ; en DEV pas de backend (`getWebAppBackendUrl` absent), les stores
  doivent dégrader proprement (L023).
- **Alternatives rejetées** : history path (404 au reload) ; servir via un serveur Node (pas le modèle DSS) ;
  garder la maquette HTML d'origine (convertie puis supprimée le 2026-06-11, CLAUDE.md).

### ADR-02 - Streaming par POLLING-via-thread, PAS par SSE (buffering du proxy DSS)

- **Contexte/Problème** : on voulait un live des étapes de l'agent. La 1re implémentation SSE
  (`Response(stream_with_context(...), text/event-stream)` + headers anti-buffering `X-Accel-Buffering: no`)
  a été testée en DSS : la réponse et tous les eventKind arrivaient **en un seul bloc à la fin** (L018, L019).
- **Décision** : abandonner le SSE pour le pattern **polling-via-thread**, copié du Dash de prod du client
  (`old_webapp_in_dash/`) qui tourne sur la MÊME instance. Le run agent s'exécute dans un
  `threading.Thread` daemon, la progression s'accumule dans un dict module-level `_RUNS` sous `_LOCK`
  (`agents/stream_manager.py`), routes `/chat/start` (POST -> `{run_id, exchange_id}`) + `/chat/poll`
  (GET `?run_id=&cursor=`), le front poll toutes les 500 ms jusqu'a `done` (L019, CONTEXT backend 2).
- **Rationale** : DSS place un nginx interne devant chaque backend de webapp -> le header anti-buffering
  n'est pas garanti honoré, et aucun exemple officiel de SSE depuis un backend de webapp standard.
  Le Dash de prod ne fait JAMAIS de réponse HTTP longue -> il contourne le buffering PAR DESIGN (L019).
- **Conséquences (+)** : prouvé en DSS (`/chat/poll` en 3-4 ms, curseur qui avance `0->1->3->5->...`,
  multi-agents OK, L019). Garde-fous ajoutés (absents du Dash) : `MAX_CONCURRENT_RUNS=8` (503 `busy`),
  éviction TTL (`FINISHED_TTL=60s`, `HARD_TTL=600s`, zéro fuite de run orphelin), scope `user_id`
  (un run n'est pollable que par son owner, 404 sinon), `done` posé sous le même lock que la lecture de
  slice (pas de perte de frame finale), `time.monotonic()` (L019).
- **Conséquences (-)** : pas de typing mot-à-mot pour la réponse texte (l'agent est structuré, la réponse
  tombe en bloc) -> le live exploitable = la **timeline**, pas la prose (L019). L'arrêt coopératif ne peut
  couper qu'entre deux chunks (ADR-12).
- **Alternatives rejetées** : SSE (bufferisé, L018/L019) ; EventSource (GET only, message trop long pour
  l'URL -> on lit via `fetch` POST + `res.body.getReader()`, L018).

### ADR-03 - SQL direct (SQLExecutor2), zéro Flow au runtime, posture de sûreté non négociable

- **Contexte/Problème** : stocker conversations/messages/runs/events de façon performante et SÛRE pour une
  instance Dataiku partagée (exigence user "rien qui puisse nuire / ralentir / surcharger l'instance",
  L015, CLAUDE.md règle 2).
- **Décision** : tout passe en SQL direct via `SQLExecutor2` (PostgreSQL, connexion `SQL_owi`, schéma
  `public`, project key `OWISMIND_DEV`), **sans Flow** au runtime. Posture de sûreté auditée (L015) :
  aucune DDL destructive (DROP/ALTER/TRUNCATE/DELETE/GRANT/REVOKE/VACUUM) - seulement
  `CREATE TABLE IF NOT EXISTS`, `INSERT`, `UPDATE ... WHERE clé`, `SELECT` bornés ; API DSS lecture seule
  uniquement (jamais `set_*`/`save`/`delete`/`set_variables`) ; valeurs paramétrées (`sql_value`/
  `nullable_value`), identifiants via `full_table`/`pg_identifier` (regex), `COMMIT` systématique,
  `SQLExecutor2` fraîche par appel, `new_executor()` lève si aucune connexion (jamais de connexion implicite).
- **Rationale** : le Flow est lourd, lent et touche l'orchestration de l'instance ; le SQL direct borné
  est prévisible et auditable. Idiome "INSERT + relecture en UN aller-retour" (`pre_queries=[INSERT]`,
  requête SELECT, `post_queries=["COMMIT"]` : read-your-own-writes PostgreSQL avant COMMIT, L009).
- **Conséquences (+)** : pas de route SQL générique exposée, le front ne choisit JAMAIS
  table/connexion/requête (CLAUDE.md règle 3) ; sûreté re-confirmée par audits adversariaux (greps vides,
  L015/L026).
- **Conséquences (-)** : convention de nommage stricte obligatoire (ADR-04) ; pas d'ALTER -> tout
  changement de schéma = nouvelle table `_vN` (ADR-04), donc les anciennes convs deviennent invisibles à
  la bascule (assumé, L049).
- **Alternatives rejetées** : datasets/recettes Flow au runtime (lourd, touche l'instance) ; ORM (overkill,
  surface) ; `ALTER TABLE` (jugé destructif/risqué, ADR-04). Exception unique tracée : un `ADD COLUMN
  IF NOT EXISTS` sur `users` pour le cumul lifetime, jugé non destructif (L049).

### ADR-04 - Nommage des tables `{PROJECT_KEY}_owismind_{logical}` + versionnage `_vN` (jamais d'ALTER)

- **Contexte/Problème** : éviter toute collision et tout ALTER risqué ; règle user explicite "toujours le
  namespace `owismind_` après le project key" (L008).
- **Décision** : centraliser dans `storage/sql_config.py` :
  `physical_table(logical)=f"{PROJECT_KEY}_{APP_NAMESPACE}_{logical}"` (`APP_NAMESPACE="owismind"`),
  `full_table()` cite `public."..."` (L008/L014). Tout changement de schéma = **nouvelle table `_vN`**
  via `CREATE TABLE IF NOT EXISTS`, jamais d'ALTER (L008/L018). Exemples réels : `webapp_chat_v2`
  (ajout colonne `generated_sql`, L018), puis `webapp_chat_v3` (feedback), `webapp_chat_v4`,
  `webapp_chat_v5` (+4 colonnes usage tokens/coût, L049) ; tables annexes `webapp_settings_v1` (agents),
  `webapp_chat_traces_v1` (footer brut), `webapp_artifacts_v1` (artefacts), `webapp_usage_monthly_v1`
  (quota mensuel).
- **Rationale** : le namespace hérité automatiquement -> aucune table à renommer à la main ; les `_vN`
  rendent les migrations 100% non destructives (la vieille table reste inerte, jamais droppée, L015/L018).
- **Conséquences (+)** : `resolve_project_key()` en cascade (env -> param webapp -> `default_project_key()`
  -> constante `OWISMIND_DEV`), résolu une fois à l'import (L007).
- **Conséquences (-)** : bascule `_vN` = changer le `*_LOGICAL` actif partout (chat ET evidence) + `git mv`
  du module ; anciennes convs invisibles (L049).
- **Alternatives rejetées** : `ALTER TABLE ADD COLUMN` (risque DDL, sauf l'exception `users` tracée L049) ;
  préfixe sans namespace (montré par les guides, divergé, L008/L069 historique).

### ADR-05 - Whitelist d'agents côté serveur via clé logique OPAQUE (jamais d'agent_id au front)

- **Contexte/Problème** : un admin choisit des projets+agents DSS ; l'utilisateur ne voit que les agents
  activés ; un id forgé depuis le front ne doit JAMAIS pouvoir être exécuté (L017, CLAUDE.md règle 4).
- **Décision** : persistance dans `webapp_settings_v1` (key-value JSON). Découverte DSS lecture seule
  (`agents/discovery.py`, filtre `id.startswith("agent:")` sur `project.list_llms()`, bornes
  `MAX_PROJECTS=500`/`MAX_AGENTS=200`). La POST admin **re-valide** chaque agent contre le listing DSS
  live et le projet contre `list_project_keys` (un id forgé ne peut jamais être persisté). La route user
  `/agents` renvoie SEULEMENT `{key, label}` - jamais `agent_id`/`project_key`. Clé logique opaque+stable :
  `_logical_key = "ag_" + sha1(f"{pk}:{agent_id}")[:12]`. `/chat/start` reçoit `agent_key`,
  `settings.resolve_enabled_agent(key)` résout `(project_key, agent_id)` côté serveur (404
  `agent_not_enabled` si forgée/obsolète). `MAX_ENABLED_AGENTS=50` (L017/L018).
- **Rationale** : la résolution clé->id est la seule frontière de confiance ; en gardant l'`agent_id`
  uniquement serveur, aucune table (chat/history/agents) ne l'expose, donc aucune surface de forge.
- **Conséquences (+)** : validé DSS ("marche comme sur des roulettes", L017) ; le picker frontend est
  TOUJOURS repeuplé depuis `/agents` (jamais codé en dur, sinon 404, L023).
- **Conséquences (-)** : un agent désactivé/déplacé rend ses anciennes convs orphelines (clé non
  résolvable) - assumé.
- **Alternatives rejetées** : envoyer l'`agent_id` brut depuis le front (interdit, règle 4) ;
  type de param DSS `CONNECTION`/`MULTISELECT` (ne se rend pas dans les Settings, L012/L037).

### ADR-06 - Agents = Code Agents LangGraph en Python 3.11, appels LLM Mesh NATIFS (pas as_langchain_chat_model)

- **Contexte/Problème** : besoin d'un orchestrateur + sous-agent revenus robustes, avec reasoning ET
  tool-calling, sur l'instance DSS. Le backend webapp est Python 3.9.23 (sans langchain), mais l'instance
  a AUSSI un code env 3.11 (double chemin, L054, mémoire auto `dataiku-python-39-311-dual-path.md`).
- **Décision** : orchestrateur (`dataiku-agents/agents/OWIsMind_orchestrator.py`) et sous-agent revenus
  (`SalesDrive_revenue_expert.py`, `agent:bHrWLyOL`) en **LangGraph**, Code Agents env 3.11. Dans les
  nœuds (synchrones), les appels LLM/sous-agents/tools se font en **natif Mesh** (`new_completion()` /
  `execute_streamed()` / `get_agent_tool(id).run()`) - JAMAIS via `as_langchain_chat_model` - ce qui
  préserve reasoning ET tool-calling. `process_stream` pilote `graph.stream(initial, stream_mode="custom")`
  et re-yield chaque chunk émis par `get_stream_writer()` dans des nœuds sync. Graphe construit+compilé
  PAR requête (closures bindant project/trace/chat). Repo = source de vérité, à recoller dans DSS à chaque
  modif (L055, CONTEXT P0★).
- **Rationale** : `as_langchain_chat_model` perd reasoning/tool-calling ; les appels natifs Mesh les
  gardent ; `get_stream_writer()` est cassé en async < 3.11 mais OK en SYNC 3.11 (prouvé par log DSS,
  L055). Le double-chemin évite de croire à tort "tout est 3.9 -> jamais de langchain" (L054).
- **Conséquences (+)** : validé DSS (le log prouve que LangGraph tourne sur le Code Agent 3.11, lève les
  2 UNVERIFIED de la revue, L055). `reasoning effort=high` se règle à la main sur le modèle Mesh (non
  pilotable par code, L055).
- **Conséquences (-)** : 2 processus distincts (Code Agents vs backend python-lib) -> une config de l'un
  n'atteint pas l'autre sans la faire voyager (cas source Evidence, ADR-13/L082) ; recoller manuellement
  les 2 agents à chaque changement (process permanent, CONTEXT).
- **Alternatives rejetées** : `as_langchain_chat_model` (perte reasoning/tools) ; agents visuels boîte
  noire ; tout en Python 3.9 dans le backend (pas de langchain dispo, L054).

### ADR-07 - with_json_output FORCÉ sur l'extraction déterministe (UNDERSTAND) ; reasoning réservé au routing/prose

- **Contexte/Problème** : l'étape UNDERSTAND du sous-agent (extraction scope/intent/terms en JSON) tournait
  en reasoning=high SANS `with_json_output` -> ~15 s de "réflexion" puis un texte que le parser ne sait pas
  lire -> `validate_understanding` renvoie None -> erreur interne avant tout SQL (L056).
- **Décision** : forcer `with_json_output(schema=...)` en tentative 1 sur UNDERSTAND (JSON propre, parse
  fiable ; en DSS 14 ça désactive le reasoning pour CET appel - voulu) ; tentative 2 = prompt-only en
  secours (`SalesDrive_revenue_expert.py:2394` "2 attempts: native JSON mode then prompt-only",
  `with_json_output` ligne 2409, schéma construit ligne 632 "JSON schema for with_json_output, with enums
  anchored on the profile"). Fallback id `UNDERSTAND_LLM_ID = vertex_ai/claude-sonnet-4-6` (L056).
- **Rationale** : la vraie règle = `with_json_output` pour TOUTE sortie consommée par du code (déterministe,
  rapide, fiable) ; le reasoning ne sert que pour les vraies décisions (routing tool-calling de
  l'orchestrateur) et la prose vérifiée (headline) (L056).
- **Conséquences (+)** : validé DSS ("tout fonctionne", L056).
- **Conséquences (-)** : l'extraction ne "réfléchit" plus (voulu : l'extraction n'a pas besoin de penser).
- **Alternatives rejetées** : garder le reasoning partout (brûle le budget et casse le parse, L056).

### ADR-08 - Moteur de données HYBRIDE : le Semantic Model garde le SQL, nos couches le nourrissent

- **Contexte/Problème** : le sous-agent doit être expert d'un dataset (revenus aujourd'hui, tickets demain)
  et générer le bon SQL. Un premier design (v3) avait le SQL 100% code-owned (templates 9 intents, L051) ;
  l'A/B user en DSS a montré que le Semantic Model (tool `v4oqA6R`, mode Agent) "répond et comprend
  beaucoup mieux" (L052).
- **Décision** : `SQL_ENGINE="semantic_tool"` par défaut - **le Semantic Model écrit et exécute le SQL
  analytique** (tool `revenue_semantic_query`, id `v4oqA6R`, `SalesDrive_revenue_expert.py:127`) ; nos
  couches (profil, grounding, désambiguïsation) le NOURRISSENT via `build_semantic_question` (la question
  user mène toujours, intent en hint, valeurs exactes groupées `IN` par colonne, scénario/période
  explicites). Le moteur SQL direct (templates) reste un **fallback technique** (`FALLBACK_TO_DIRECT`,
  panne technique seulement - un résultat vide légitime reste `no_data` honnête) (L052).
- **Rationale** : la SOTA prod (dbt/Snowflake Cortex) mesure couche sémantique + templates >> SQL libre LLM
  (98-100% vs 84-90%, L051) ; le Semantic Model résout mieux que nos templates en pratique (L052).
- **Conséquences (+)** : validé DSS ("ça marche super bien", L052). Extraction mode-Agent robuste : réponse
  par priorité de clés (`answer`/`output_text` > `completion` > `text` > `result`) et DERNIÈRE occurrence
  gagnante ; lignes = dernier jeu (les requêtes sondes intermédiaires ne polluent plus, L052).
- **Conséquences (-)** : le MOTEUR du Semantic Model reste opaque (prompts internes non contrôlables,
  L051) ; ses anomalies se corrigent dans sa config, pas dans le code (`Phase='ACTUAL'` -> `'ACTUALS'`,
  L052/L058). En multi-SQL, "Result used by the agent" = résultat du DERNIER SQL (L064).
- **Alternatives rejetées** : SQL 100% libre LLM (84-90% en SOTA, L051) ; SQL 100% code-owned templates
  (moins bon que le Semantic Model en réel, L052) ; API semantic model boîte noire instanciée à la main
  (interdit par la doc -> passer par `create_semantic_model` + versions, L059).

### ADR-09 - Grounding par SQL inline sur le value_index (PAS un tool) ; 2 vrais tools DSS

- **Contexte/Problème** : il faut résoudre des valeurs (noms de clients, termes d'offre) en valeurs exactes
  AVANT de poser la question au Semantic Model, sans config par dataset (L051, L085).
- **Décision (archi v3 = le code)** : le **grounding n'est PAS un tool** = SQL inline `dataiku.SQLExecutor2`
  sur `DRIVE_Revenues_value_index` (`SalesDrive_revenue_expert.py:83 VALUE_INDEX_DATASET`, `_resolve_terms`
  ligne 2259) : exact `value_norm IN` -> fuzzy `LIKE` -> tranche top-5000 + `difflib`, read-only
  (`transaction_read_only` + `statement_timeout`). Les **vrais tools DSS** (`get_agent_tool(id).run()`)
  sont 2 : `revenue_semantic_query` (`v4oqA6R`, écrit+exécute le SQL analytique) et historiquement
  `dataset_lookup` (`9FEzVZk`, lecture d'attribut). `resolve_filter_value`/`dataset_sql_query` = labels
  d'EVENTS, pas des tools (L085, CONTEXT).
- **Rationale** : "tool vs inline n'est PAS un débat de charge SQL" (un tool qui requête fait le même SQL) ;
  le vrai levier = OÙ se fait le matching -> dans la BASE (SQL), pas en RAM (L086). Le value_index est
  fabriqué dans le Flow (recette) avec une norm FROZEN partagée code<->recette (L051).
- **Conséquences (+)** : grounding rapide, read-only, borné, zéro nom de colonne en dur (P3-safe) ; capture
  Evidence déterministe car les tools managés s'appellent via `get_agent_tool(id).run()` et SQL+rows sont
  lus dans la valeur de RETOUR (L047).
- **Conséquences (-)** : le value_index peut être PÉRIMÉ après un changement de dataset (l'agent ne "voit"
  pas les nouvelles colonnes) -> conscience du schéma LIVE nécessaire (L072), et un value-catalog plus riche
  (`Value_Catalog` + resolver Python `Drive_Revenues_resolve_filter_value`) = ROADMAP, PAS câblé en v3,
  recâblage DÉFÉRÉ (L085).
- **Évolution en cours (NON branché)** : L086 - resolver full-text `ILIKE` sur TOUTES les colonnes texte du
  fact (read-only, rien en RAM), tool autonome `tools/attribute_lookup_tool.py` ; `dataset_lookup`
  ENTIÈREMENT supprimé du code (intent `lookup`, `KNOWN_TOOL_NAMES`, des DEUX agents - contrat gelé).
  RUN TEST DSS OK mais NON branché, perf 50 users non mesurée (L086). **Statut in-flux : à confirmer.**

### ADR-10 - Le sous-agent ASSISTE, il ne DICTE pas : ne jamais épingler une colonne pour un terme d'offre ambigu

- **Contexte/Problème** : "revenus YTD EVPL, actuals vs budget" - EVPL existe en `Product`, `Solution` ET
  `sirano_product`. Le sous-agent déterministe épinglait `sirano_product` (153 distincts bat Product 42 via
  le fallback `column_priority` `-distinct_count`) -> budget=0 (les lignes BUDGET n'ont pas de
  sirano_product). Le Playground (modèle seul) résolvait `Product='EVPL'` parfaitement (L058).
- **Décision** : `build_semantic_question` refondu ASSISTIF ("HINTS to ASSIST you, NOT orders ; you keep
  the final say"). Un terme d'offre ambigu (valeur dans >=2 colonnes, `alt_columns` non vide) n'est PLUS
  épinglé : on émet `AMBIGUOUS OFFER TERM` (`SalesDrive_revenue_expert.py:1589` et 1609) et le MODÈLE
  (Sonnet + instructions "never default an offer term to sirano_product") tranche. Les valeurs
  mono-colonne (noms clients) restent suggérées (anti-typo). `defer_multicolumn_offer_terms` (ligne 883) :
  candidats sur >=2 colonnes distinctes -> statut `deferred`, déférés au modèle au lieu d'interroger
  l'utilisateur (cas "Roaming Hub", L081). `build_disclosure_notes` divulgue les alternatives (L079/L081).
- **Rationale** : le raisonnement vit dans le gros modèle (Sonnet), pas dans le petit sous-agent ;
  la hiérarchie d'offre (`Product > Solution > sirano_product`) vit dans les INSTRUCTIONS du modèle
  sémantique, pas dans le code (P3 : aucune valeur métier en dur, L058). Décision par NOMBRE de colonnes,
  jamais de nom de colonne en dur (P3-clean, L081).
- **Conséquences (+)** : 157+ tests verts ; corrige le piège budget=0 (L058). Cas client : préférer la
  colonne dominante (account_name) + divulguer au lieu de demander (L079).
- **Conséquences (-)** : il faut re-tester EVPL via l'orchestrateur en DSS (NON re-validé à l'écriture de
  L058) ; lever déterministe = poser `ambiguity_priority` dans le profil pour garantir le gagnant (L079).
- **Alternatives rejetées** : remettre le thinking au sous-agent (UNDERSTAND est une extraction, ADR-07) ;
  hardcoder la hiérarchie d'offre dans le code (P3) ; demander systématiquement à l'utilisateur (UX
  pénible, L081).

### ADR-11 - L'orchestrateur ne doit JAMAIS affirmer un fait métier : router, pas nier

- **Contexte/Problème** : sur "budget 2026 Roaming Hub", l'orchestrateur répondait "I don't have budget
  data" SANS appeler l'agent revenus, qui lit pourtant la colonne `Phase`
  (`ACTUALS/BUDGET/FORECAST/Q3F/HLF`). `docs/questions_asked.md` (817 lignes réelles) montre ~10
  occurrences de la MÊME cause (spec orchestrateur §0, L050).
- **Décision (contrat gelé)** : 3 règles d'honnêteté (spec orchestrateur §1) : R1 zéro fait métier authoré
  par l'orchestrateur (tout fait vient d'un sous-agent, verbatim ou synthèse stricte) ; R2 le seul "non"
  autorisé = "je n'ai pas d'AGENT pour ce domaine" (auto-connaissance du roster), jamais "la donnée
  n'existe pas" ; R3 dans le doute, ROUTER. Pare-feu structurel : `CAPABILITY_GAP` + `OUT_OF_SCOPE` =
  templates DÉTERMINISTES (plus de prose libre = plus d'hallucination) ; nouvel intent `CONCEPT`
  (notions générales étiquetées, zéro chiffre OWI) ; `CLARIFY` borné "demande seulement". Registre =
  manifeste `{key, agent_id, label, description, domain}` + `BUSINESS_DOMAINS` ; manifeste revenus
  pleine-vérité + test anti-dérive qui importe `KNOWN_PHASES` et casse si la description re-rétrécit
  (spec orchestrateur §2-§3, L050).
- **Rationale** : la fuite naissait du texte LIBRE écrit après une mauvaise classification ; rendre les
  refus déterministes supprime la surface d'hallucination. Coût LLM inchangé (1 plan + 0|1 synthèse, §0).
- **Conséquences (+)** : ajouter un agent = 1 entrée registre (extensible) ; le test anti-dérive protège le
  contrat (P3 : pas de valeur métier en dur, juste un test, L050).
- **Conséquences (-)** : le routing est une décision LLM -> NON validé DSS au moment de L050 (à
  smoke-tester : budget->route, tickets->gap honnête, météo->hors-sujet, ellipse->route, concept).
- **Alternatives rejetées** : laisser l'orchestrateur classer en CLARIFY/OUT_OF_SCOPE puis écrire un
  `direct_answer` libre (il hallucine une frontière, L050). Niveaux 2 (refus->offres) et 3 (exploration)
  DIFFÉRÉS (spec §9).

### ADR-12 - Modèles par mode + propagation du mode + stop optimiste (architecture MODEL-AGNOSTIC)

- **Contexte/Problème** : le test DSS de l'escalade pilotée (hand-over Sonnet en cours de tour) a échoué
  sur gpt-5.4-mini (escalade quasi systématique + message hardcodé, ou narrate-and-stop). User : "stop les
  hacks mono-modèle", archi qui marche MÊME sur les petits modèles (L071).
- **Décision** : suppression TOTALE de l'escalade ; UN modèle pilote tout le tour, choisi par mode.
  `LOOP_LLM_BY_MODE` (`OWIsMind_orchestrator.py:112`) = {eco:`GEMINI_FLASH_LITE_ID`,
  medium:`GEMINI_FLASH_ID`, high:`SONNET_ID`}, `DEFAULT_MODE="eco"` (ligne 111), `pick_loop_llm(mode)`
  (ligne 803) rend le modèle (gpt-5.4-mini supprimé, L080). Ids réels (ligne 91-93) :
  `gemini-3.1-flash-lite` (eco), `gemini-3.5-flash` (medium), `claude-sonnet-4-6` (high). Le mode se
  PROPAGE au sous-agent (token `MODE:` dans le contexte -> `forced_mode` -> `pick_subagent_llm`, threadé
  dans l'état) -> High = Sonnet partout (L075). Tokens `⟦owi:mode=…⟧`/`⟦owi:lang=…⟧` parse+strip, défense
  sur chaque message (L071). Narration "NARRATE AS YOU GO" détachée et conditionnelle (OFF en eco pour
  éviter le narrate-and-stop, L075). Stop = arrêt OPTIMISTE côté frontend (`stopGeneration` applique
  `stopped` tout de suite + POST `/chat/stop` best-effort) + "Stopping…" clignotant (L073/L075).
- **Rationale** : l'escalade était un band-aid gpt-5.4-mini qui CAUSAIT le bug ; un seul modèle/mode est
  prévisible et model-agnostic. Le stop coopératif ne peut couper qu'entre 2 chunks (~5-6 s de latence
  perçue pendant un appel bloquant) -> l'optimisme rend le ressenti instantané, le backend persiste son
  propre partiel (L073).
- **Conséquences (+)** : argent € dérivé du NOM de colonne (`metric_unit`,
  `SalesDrive_revenue_expert.py:1030`, `amount_eur -> €`) sans config profil ; ligne `[Périmètre]`
  préfixée par le sous-agent (`build_scope_note` ligne 1933) (L080). 227 tests agents verts.
- **Conséquences (-)** : ids Gemini = best-effort au format observé, à VÉRIFIER dans la connexion Mesh
  (sinon Éco/défaut ne répond pas) ; comportement live des modèles NON validé DSS (L071/L080).
- **Alternatives rejetées** : escalade en cours de tour (L067/L068, supprimée) ; hacks mono-modèle (L071) ;
  unité de devise via config profil (l'user refuse, la colonne porte déjà la devise, L080).

### ADR-13 - Evidence trust layer + artefacts pilotés par l'agent (séparer SIGNAL et DONNÉE)

- **Contexte/Problème** : donner aux commerciaux non techniques la confiance dans un chiffre : d'où vient
  la donnée, le scope/filtres exacts, COMMENT le nombre est calculé (langage métier, pas de SQL), le
  résultat EXACT utilisé, un niveau de vérification HONNÊTE, un drill-down quand c'est prouvablement fiable
  (spec trust layer §0).
- **Décision** : Evidence v1 rejoue le SELECT de l'agent en lecture seule SANS nouveau schéma - tout est
  re-dérivé du `generated_sql` déjà en base (L035). Découverte AUTO des datasets PostgreSQL du projet (la
  whitelist admin MULTISELECT ne se rend pas dans les Settings DSS -> abandonnée, L037). Trust layer v2 :
  données stockées en enrichissement JSON de `generated_sql` (pas de migration), caps au point d'écriture
  (`MAX_RESULT_ROWS=200`, `MAX_RESULT_COLS=50`, JSON <= 100k chars, budget global <= 262144 chars,
  préservant TOUJOURS le dernier item réussi), capture best-effort, badge déterministe (jamais vert),
  drill re-validé serveur (spec trust layer §1, L045). Artefacts : tools LLM `show_chart`/`show_table` ->
  event GELÉ `ARTIFACT` (`_normalized_artifact_event` car le whitelist timeline droppe les champs) ->
  `webapp_artifacts_v1` -> `/evidence/meta` (avec un payload Chart.js construit en PYTHON
  `evidence/chart_payload.py`) -> onglets Evidence/Chart/Table (L057).
- **Rationale** : ne JAMAIS mettre de LLM dans le chemin de preuve (spec §0) ; les fausses preuves
  naissent des RÈGLES re-dérivées, pas du parsing -> niveaux déterministes (L045). La DONNÉE reste celle
  déjà capturée (`generated_sql[].result`) ; l'agent ne fournit que x/y/type/style -> zéro risque d'erreur
  de données (séparation signal/donnée, L057). Le rendu interactif est forcément JS (Python ne sort qu'une
  image figée), donc Python construit le payload BLINDÉ et Chart.js rend (L057).
- **Conséquences (+)** : validé DSS ("comme sur des roulettes", L057 ; "suuuper ça marche très bien",
  L037). Sécurité d'un endpoint qui rejoue du SQL : les vrais risques sont DoS/perf, pas l'injection
  (audit 6 lentilles : 0 injection/0 IDOR/0 XSS confirmés ; les 5 findings = instance-safety/perf,
  L036) -> cache TTL hors lock, token-bucket per-user, `SET LOCAL statement_timeout`, DISTINCT scopé,
  `MAX_EVIDENCE_PAGE=20`.
- **Conséquences (-)** : compromis acté (sans whitelist, tout dataset SQL du projet dont un agent met la
  table dans son SELECT est visible en lignes brutes pour SA propre conversation, lecture seule, borné sur
  4 axes, L037) ; la trace BRUTE de fin de stream est stockée (`webapp_chat_traces_v1`) - divergence
  assumée du cadrage car décision produit user alignée sur le Dash de prod (L021).
- **Alternatives rejetées** : whitelist admin MULTISELECT (ne se rend pas, L037) ; persister les lignes
  dans un nouveau schéma chat_v5 dédié (duplication de données sensibles, évité, L035) ; rendu graphique en
  SVG fait main (Chart.js bundlé > SVG, L057) ; LLM dans le chemin de preuve (interdit, §0).

### ADR-14 - Règle typographique : tiret cadratin/demi-cadratin bannis partout (signature IA)

- **Contexte/Problème** : le tiret cadratin `—` (U+2014) et le demi-cadratin `–` (U+2013) sont perçus comme
  une SIGNATURE d'IA (L084, CLAUDE.md règle 9).
- **Décision** : règle NON NÉGOCIABLE #9 - bannis À TOUT JAMAIS, PARTOUT (i18n/UI, code, commentaires,
  mémoire, messages de commit ET réponses chat). Remplacer par `-`, `:`, `,` ou parenthèses (L084).
- **Rationale** : décision user absolue, identité du projet. Le sweep doit être byte-safe (`LC_ALL=C` /
  sed octet, JAMAIS `perl -CSD` sur des fichiers à glyphes multioctets type `⟦owi:mode⟧`/`⊥`/`⇒` -> risque
  U+FFFD). Vérif : `grep -rlP '\xe2\x80\x9[34]'` (vide) + `grep -rlP '\xef\xbf\xbd'` (0 corruption) (L084).
- **Conséquences (+)** : validé DSS, 0 résiduel, tokens spéciaux intacts (L084).
- **Conséquences (-)** : tout outil/agent doit respecter la règle ; les fichiers qui DÉFINISSENT la règle
  citent forcément `—`/`–` entre backticks (exception assumée, L084).
- **Alternatives rejetées** : `perl -CSD` (corruption multioctet, L084) ; tolérer le cadratin en code/commit
  (refusé).

---

## Partie B - TOP gotchas / pièges (chacun : le piège, le fix)

1. **SSE bufferisé par DSS** (L018/L019). Piège : `text/event-stream` + `X-Accel-Buffering: no` ->
   tout arrive en bloc (nginx interne DSS). Fix : polling-via-thread (`/chat/start` + `/chat/poll`),
   dict `_RUNS` + `_LOCK`, jamais de réponse HTTP longue.

2. **Réactivité Vue 3 sur l'objet streamé** (L020). Piège : pousser l'objet `assistant` brut dans
   `messages.value` puis le muter via la référence locale -> hors proxy réactif -> 0 re-render, timeline
   d'un coup à la fin. Fix : `const assistant = reactive({...})` AVANT le push.

3. **Flexbox scroll qui cache les bulles** (L020). Piège : les `.msg` ont `flex-shrink:1` -> compressés à
   ~0 et recouverts. Fix : `.msg { flex-shrink: 0 }` ; dans toute colonne flex scrollable, enfants
   non-compressibles.

4. **`:global` thème qui perd le descendant** (L022, CONTEXT F2). Piège :
   `:global(body[data-theme="dark"]) .x` compile en `body[data-theme="dark"]` SEUL -> peint tout le body.
   Fix : envelopper le sélecteur ENTIER : `:global(body[data-theme="dark"] .x)`. Mieux : token sémantique
   thème-aware (`--orange-soft-dark`, `--success-soft`/`--danger-soft`) ; PAS de couleur en dur (invisible
   en dark, L083) ; pas de `color-mix` (L031).

5. **`rows_to_json_safe` NaN->None** (L013). Piège : `df.where(notna, None)` re-coerce `None` en `NaN` sur
   une colonne TEXT toute-NULL (typée float64) -> token `NaN` invalide en JSON. Fix :
   `df.astype(object).where(mask, None)` (cast objet d'abord).

6. **Param webapp non SET = absent** (L037). Piège : `get_webapp_config()` ne contient un param que s'il
   est SET ; MULTISELECT/`getChoicesFromPython` ne se rend pas dans les Settings DSS ; un nouveau param ne
   se rend qu'en ROUVRANT les Settings (plugin Development : supprimer + ré-uploader). Fix : éviter
   MULTISELECT ; découverte auto côté backend.

7. **`cp` vers body.html refusé** (L033, CONTEXT F10). Piège : le `cp` vers `webapps/.../body.html` est
   refusé par les permissions. Fix : recâbler via l'outil Write (remplacer les 2 hash). Le `cp` vers le
   staging `ready-for-dataiku/` passe.

8. **Reasoning + extraction JSON** (L056). Piège : reasoning=high sans `with_json_output` sur une
   extraction -> ~15 s puis parse cassé -> erreur avant tout SQL. Fix : `with_json_output` forcé sur les
   sorties consommées par du code ; reasoning réservé au routing/prose.

9. **`get_stream_writer` cassé en async** (L055). Piège : le caveat "get_stream_writer cassé" vaut pour
   async < 3.11. Fix : nœuds SYNC en 3.11 (OK, prouvé DSS) ; appels Mesh natifs (jamais
   `as_langchain_chat_model`).

10. **2 processus séparés (Code Agent vs backend)** (L082). Piège : une URL configurée dans le registre
    orchestrateur n'atteint pas `/evidence/meta` (backend) ; le backend FILTRE les champs des items SQL
    (`_CORE_ITEM_KEYS`). Fix : faire VOYAGER l'URL via les items SQL (qui portent déjà `agent_key`), de
    façon ADDITIVE sur le pipeline de capture gelé.

11. **Graphique vide en multi-SQL** (L064). Piège : le résultat était attaché au PREMIER span SQL, Evidence
    prend le DERNIER. Fix : attacher au DERNIER span (`i==last_i`) ; Evidence préfère le dernier item
    réussi AVEC résultat.

12. **"Narrate FIRST" casse les petits modèles** (L063). Piège : "narre d'abord" -> le petit modèle écrit
    la narration et S'ARRÊTE (pas de tool-call). Fix : ACT-FIRST (tool-call obligatoire même tour) ;
    narration OFF en eco (L075) ; nudge narrate-and-stop (`_looks_like_premature_stop` + 1 re-ask, L071).

13. **`column_priority` fallback `-distinct_count`** (L058). Piège : sur un terme multi-colonnes, la colonne
    au plus de distincts gagne (`sirano_product` 153 bat `Product` 42) -> budget=0. Fix : ne plus épingler
    un terme d'offre ambigu, déférer au modèle (ADR-10) ; lever déterministe = `ambiguity_priority` dans le
    profil.

14. **Capture Evidence par fouille de trace** (L047). Piège : deviner les clés de rows dans la trace
    (`_ROW_KEYS`) -> `result_captured:false`. Fix : appeler les tools managés via `get_agent_tool(id).run()`
    et lire SQL+rows dans la valeur de RETOUR.

15. **Boucles de clarification** (L048). Piège : patcher valeur par valeur (anti-pattern user). Vrai
    problème = mémoire conversationnelle. Fix : continuité (`pass_context`), politiques génériques (valeur
    exacte, priorité de colonne), round-trip parseable "VALEUR (Colonne)".

16. **Panneau hors RouterView ne se ferme pas** (L038, CONTEXT F13). Piège : Evidence monté hors
    `RouterView` reste à l'ouverture des Settings ; fuites async (auto-open + reveal fin de run dans le
    store Pinia qui survit à l'unmount). Fix : `watch([route.name, evidence.open])` -> close idempotent dès
    `name !== 'chat'`.

17. **Graphify ingère les artefacts générés** (L046). Piège : le graphe avale les bundles
    `resource/owismind-app/assets/*.js` + staging -> graphe pollué. Fix : `.graphifyignore` versionné ;
    découverte = graphe, exhaustivité = grep.

18. **TTL/locks du stream_manager** (L019). Piège : runs orphelins, perte de frame finale, run pollable par
    un autre user. Fix : éviction TTL, lecture slice+done sous UN lock, scope `user_id`,
    `MAX_CONCURRENT_RUNS=8`.

19. **Garde SQL Evidence bypassée par `FROM"table"` espace-less** (L077). Piège : audit à l'aveugle - un
    `FROM"table"` sans espace passait la garde. Fix : garde durcie (littéraux blanchis, tables système
    rejetées, `WITH RECURSIVE` non faux-rejeté, identifiants nus ET quotés testés, L036/L077).

20. **`zsh` ne fait pas de word-splitting** (L085). Piège : `for f in $FILES` passe toute la liste comme un
    seul nom. Fix : `for f in ${=FILES}`. Et déplacer un dossier référencé partout : utiliser la barre
    oblique (`s|cadrage/|docs/cadrage/|`) pour ne pas matcher le nom commun.

---

## Partie C - Connexions au reste du système

- **Flux d'un message** : front (Vue/Pinia) -> `/chat/start` -> `stream_manager` (thread daemon) ->
  `run_agent_streamed` (Code Agent orchestrateur, Mesh) -> sous-agent revenus (grounding value_index +
  Semantic Model `v4oqA6R`) -> events normalisés pollés par `/chat/poll` -> stockage `webapp_chat_v5` +
  `webapp_chat_traces_v1` + `webapp_artifacts_v1` -> `/evidence/meta` -> panneau Evidence/Chart/Table.
- **Frontières de confiance** : whitelist agents (ADR-05, clé opaque) ; SQL paramétré + bornes + read-only
  (ADR-03) ; Evidence re-valide tout côté serveur (ADR-13) ; le front n'envoie jamais SQL/table/connexion.
- **Source de vérité** : `memory/PROJECT_STATE.md` + `memory/LESSONS.md` PRIMENT sur les guides
  `docs/cadrage/` ; les noms réels et les solutions qui marchent vivent en mémoire (CLAUDE.md).
- **Statut in-flux explicite** : ADR-09 (resolver full-text L086, NON branché) ; ADR-11 (routing LLM NON
  validé DSS, L050) ; ADR-12 (ids Gemini à vérifier + comportement live NON validé, L071/L080) ; ADR-10
  (EVPL à re-tester via l'orchestrateur, L058) ; `dataiku-agents/` est édité EN DIRECT pendant la rédaction
  de ce pack -> certaines lignes peuvent avoir bougé (ancres validées au moment de la lecture).
