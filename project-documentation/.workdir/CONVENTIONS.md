# OWIsMind - Conventions de redaction de la documentation

> Audience : les ~50 agents redacteurs (writers) qui produisent la documentation OWIsMind, plus tout
> mainteneur de la doc. Derniere mise a jour : 2026-06-18. Resume : ce fichier fixe les regles
> partagees (typographie, terminologie, structure, diagrammes, liens croises) pour que l'ensemble
> documentaire soit coherent, sans redondance et ancre dans le code reel.

Ce document est PRESCRIPTIF. Quand il dit "tu DOIS", c'est une contrainte de coherence du corpus, pas
une suggestion. Lis-le en entier avant d'ecrire ta premiere ligne.

Rappel de cadre : la documentation se trouve sous `project-documentation/`. Le code du depot est en
LECTURE SEULE pour les redacteurs ; un autre ingenieur edite le depot en direct (surtout
`dataiku-agents/`). Tu n'ecris QUE dans le ou les fichier(s) qui te sont assignes sous
`project-documentation/`.

---

## 1. Conventions de redaction (obligatoires)

### 1.1 En-tete et pied de page : le gabarit que CHAQUE fichier suit

Tout fichier de doc commence par un H1 puis un blockquote en 3 points (audience, date, resume d'une
phrase), et se termine par une section `## Voir aussi`. Gabarit a copier :

```markdown
# <Titre du document>

> Audience : <a qui s'adresse ce document>. Derniere mise a jour : 2026-06-18. Resume : <une seule
> phrase qui dit ce que le lecteur apprend ici>.

<contenu>

## Voir aussi
- [<Titre de la cible>](<chemin relatif>) - <pourquoi y aller>
- ...
```

Regles fermes :
- La date est `Derniere mise a jour: 2026-06-18` (sans tiret cadratin ; voir 1.2). Tous les fichiers
  de la passe initiale portent cette date.
- Le blockquote tient en 3 a 4 lignes maximum. Pas de table des matieres geante en tete.
- La section `## Voir aussi` est OBLIGATOIRE et ne contient que des liens MARKDOWN RELATIFS qui
  resolvent dans l'arborescence de la section 3. Voir 1.5 pour la mecanique des chemins relatifs.

### 1.2 Regle typographique #9 (NON NEGOCIABLE) : pas de tiret cadratin ni demi-cadratin

Le tiret cadratin `—` (U+2014) et le tiret demi-cadratin `–` (U+2013) sont BANNIS, partout, dans
chaque caractere que tu ecris (titres, prose, tableaux, commentaires de blocs de code, libelles de
diagrammes, messages, liens). C'est une regle absolue du projet, une signature d'IA que l'utilisateur
interdit.

Remplacements autorises selon le sens :
- pause / incise : `-` (trait d'union simple), ou des parentheses ;
- enumeration / definition : `:` ;
- juxtaposition : `,`.

Auto-controle avant de rendre ton fichier : relis-le et verifie qu'aucun `—` ni `–` n'y figure. Le
seul cas tolere est le document `08-decisions/0012-regle-typographique-sans-tiret-cadratin.md`, qui DOIT
citer ces deux glyphes entre backticks pour les nommer (c'est l'exception assumee de l'ADR qui definit
la regle).

### 1.3 Langue : prose en FRANCAIS, code en anglais VERBATIM

- Toute la prose explicative est en francais professionnel, clair, concret.
- Tout identifiant de code reste en anglais d'origine, VERBATIM, sans traduction ni reformulation :
  noms de fichiers, chemins, noms de fonctions/classes/methodes, noms de tables et de colonnes SQL,
  cles i18n, ids de config (`agent:bHrWLyOL`, `v4oqA6R`, `GEMINI_FLASH_LITE_ID`), eventKinds, codes
  d'erreur HTTP applicatifs (`agent_not_enabled`, `storage_not_configured`), tokens de controle
  (`⟦owi:mode=…⟧`). On ne francise jamais un nom de code.
- Les extraits de code restent dans leur langue source. Tu ne reecris pas un commentaire de code en
  francais : si tu cites du code, tu le cites tel quel.

### 1.4 Altitude : prose d'abord, code seulement quand il porte le sens

- N'inonde pas la doc de code. Explique le COMPORTEMENT et le POURQUOI en prose ; cite un extrait
  uniquement quand le texte exact est porteur (une signature de fonction que le lecteur doit appeler,
  un contrat de payload, un gabarit de message). Ne recopie pas une fonction entiere que tu te
  contentes de paraphraser.
- Sois concret et precis : nomme la fonction/le fichier reels plutot que de rester vague. Mais
  reference, ne duplique pas : si un detail vit deja dans un autre document canonique, lie-le.
- Pas de chemin:ligne dans la doc finale. Les research packs (`.workdir/research/`) utilisent
  `fichier:ligne` comme carte de travail ; la doc livree cite le NOM du fichier/de la fonction (stable),
  jamais un numero de ligne (instable, le depot est edite en direct).

### 1.5 Diagrammes Mermaid, tableaux GitHub, liens relatifs

- Diagrammes : blocs Mermaid (` ```mermaid `). Voir la section 4 pour QUI possede QUEL diagramme : un
  diagramme majeur a UN seul foyer canonique ; les autres documents y renvoient au lieu de le redessiner.
- Tableaux : tableaux markdown GitHub standard (`| ... | ... |`).
- Liens croises : liens markdown RELATIFS qui matchent l'arborescence de la section 3. La mecanique :
  - depuis un fichier d'une sous-section vers un autre fichier de la MEME sous-section :
    `[texte](02-api-reference.md)` ;
  - vers une AUTRE sous-section : remonte d'un cran, ex. depuis `04-backend/02-api-reference.md` vers
    l'architecture : `[texte](../02-architecture/03-runtime-flows.md)` ;
  - vers le portail racine : `[texte](../README.md)`.
  Verifie mentalement que la cible existe BIEN dans l'arborescence de la section 3 (ne lie jamais un
  fichier qui n'y figure pas).

### 1.6 Ancrage dans la source reelle (anti-invention)

- Les research packs sont ta CARTE, pas ta source ultime. Avant d'affirmer un nom exact (fonction,
  fichier, table, colonne, id de config, signature, comportement), OUVRE le fichier reel pour le
  confirmer. N'invente jamais un nom ni un chemin.
- Si une affirmation depend d'un detail que tu n'as pas pu verifier dans le code, dis-le explicitement
  plutot que de l'affirmer.

### 1.7 Signaler ce qui est EN FLUX (obligatoire)

La couche agents (`dataiku-agents/`) est editee en direct. Plusieurs elements sont en transition. Tu
DOIS encadrer ces points avec une mention visible (un blockquote `> EN FLUX : ...` ou `> ROADMAP :
...`). Les principaux a flaguer systematiquement quand tu les touches :
- `attribute_lookup` (`tools/attribute_lookup_tool.py`) : CONSTRUIT et teste unitairement, mais PAS
  encore cable dans le sous-agent. Son predecesseur, le tool manage `dataset_lookup` (`9FEzVZk`) et
  l'intent `lookup`, ont ete RETIRES le 2026-06-18.
- `DRIVE_Revenues_Value_Catalog` + le resolver Python `Drive_Revenues_resolve_filter_value` : ROADMAP,
  PAS cables en v3.
- Ids LLM Mesh par mode (`GEMINI_FLASH_LITE_ID`, `GEMINI_FLASH_ID`, `SONNET_ID`) : doivent matcher la
  connexion LLM Mesh de l'instance ; un id faux casse le mode correspondant (a verifier en DSS).
- Quota mensuel de budget (50 EUR/user/mois) : le STOCKAGE est pret (`webapp_usage_monthly_v1`), le
  BLOCAGE n'est PAS implemente.
- Capture du `result` Evidence : la cle des lignes du span tool n'est pas confirmee sur l'instance ;
  la capture est best-effort (peut etre absente -> `result_captured: false`).
- Les docs de reference `docs/` sont parfois PERIMEES (`chat_v4` vs `chat_v5` reel, `CONV_TITLE_MAXLEN`
  140 vs 56 reel, comptes de tests/entrees zip). Le CODE prime ; ne recopie pas un chiffre perime.

---

## 2. Terminologie canonique

Utilise EXACTEMENT ces termes et ces orthographes partout, pour que les 50 redacteurs parlent d'une
seule voix. La colonne "Ne pas confondre avec" tue les ambiguites recurrentes.

| Terme | Definition courte | Ne pas confondre avec |
|---|---|---|
| OWIsMind | Le produit : plugin Dataiku DSS, portail de chat agentique metier (id `owismind`, version `0.0.1`). | "la webapp" (qui ne designe que la couche frontend+backend Flask, pas les agents). |
| orchestrateur (`OWIsMind_orchestrator`) | Code Agent LangGraph (env 3.11), point d'entree par defaut : dialogue, route vers un sous-agent, rend chart/table/kpi, ecrit l'analyse. Ne detient JAMAIS de chiffre metier. | le sous-agent (qui, lui, possede les chiffres) ; le backend Flask (qui ne raisonne pas). |
| sous-agent / sous-agent expert revenus (`SalesDrive_revenue_expert`) | Code Agent LangGraph (env 3.11, `agent:bHrWLyOL`) specialiste : pipeline UNDERSTAND -> RESOLVE -> QUERY -> RENDER ; possede tous les chiffres revenus. | l'orchestrateur ; le Semantic Model Query tool (qui ecrit le SQL, pas le sous-agent). |
| LLM Mesh | La couche DSS qui expose les modeles et agents ; appelee en NATIF (`new_completion()`, `get_agent_tool(id).run()`), jamais via `as_langchain_chat_model`. | LangGraph (le framework des Code Agents, distinct du transport Mesh). |
| Code Agent | Un agent DSS implemente en code Python (env 3.11), colle a la main depuis le repo (source de verite). Les deux Code Agents d'OWIsMind = orchestrateur + sous-agent. | le backend Flask (Python 3.9, jamais de langchain) ; un agent visuel DSS. |
| Evidence Studio | Le panneau de "preuve" a droite du chat : re-derive de facon DETERMINISTE (zero LLM) comment une reponse a ete produite (badge, sources, chips, calcul, resultat capture, drill, SQL) + artifacts. | Dataset Explorer (exploration libre, possiblement sur sample) ; un simple visualiseur de SQL. |
| artifact | Une SPEC d'affichage demandee par l'orchestrateur (`show_chart`/`show_table`/`show_kpi`) : `{kind, title, chart|kpi}`. Ne porte JAMAIS les lignes de donnees. | le `result` capture (la DONNEE) ; un graphique deja rendu. Toujours ecrit "artifact", pas "artefact" dans le code (mais "artefacts" reste acceptable en prose francaise courante). |
| grounding | L'ancrage des termes user sur des valeurs de cellule EXACTES, via SQL inline read-only sur le value index. Ce N'EST PAS un tool. | un appel de tool DSS ; le moteur SQL analytique (qui, lui, calcule la reponse). |
| value_index (`DRIVE_Revenues_value_index`) | Le dataset `{column_name, value, value_norm, occurrences}` (~3.6 k lignes) interroge en SQL pour le grounding. DOIT vivre sur la connexion SQL source. | le profil (`DRIVE_Revenues_profile`, le "cerveau metier") ; le Value_Catalog (roadmap). |
| Semantic Model Query tool / `revenue_semantic_query` (`v4oqA6R`) | Le SEUL vrai tool DSS appele au runtime en v3 : il ECRIT ET EXECUTE le SQL analytique sur un modele semantique (Sonnet) dans tous les modes. | le grounding (inline, pas un tool) ; `resolve_filter_value`/`dataset_sql_query` (qui sont des LABELS d'events, pas des tools). |
| run-as-user (identite backend) | L'identite DSS sous laquelle s'execute le backend de la webapp : c'est elle qui execute le SQL et appelle les agents. | l'utilisateur connecte (le caller, resolu des en-tetes), qui sert uniquement au scoping applicatif. |
| polling (streaming-par-polling) | Le transport : l'agent tourne dans un thread worker, le front interroge `/chat/poll` toutes les ~500 ms (pas de SSE, bufferise par le proxy DSS). | SSE (`text/event-stream`, abandonne) ; un streaming texte mot-a-mot (la reponse tombe souvent en bloc). |
| exchange (`exchange_id`) | Un echange de chat = une ligne de `webapp_chat_v5` (un tour user + reponse assistant), id `uuid4().hex` genere en Python. | session (`session_id`, qui regroupe plusieurs exchanges) ; run (le cycle de generation en vol). |
| run (`run_id`) | Un cycle de generation en vol cote backend (thread worker + etat `_RUNS`), handle opaque `uuid4().hex`. | exchange (la ligne persistee) ; session (la conversation). |
| session (`session_id`) | La conversation : regroupe les exchanges, estampillee dans l'URL `/chat/<sessionId>`. | exchange ; l'arbre de conversation (les exchanges relies par `parent_exchange_id`). |
| capability / whitelist | Le registre `CAPABILITIES` de l'orchestrateur (manifeste des sous-agents actifs) ET la whitelist serveur des agents activables (table `webapp_settings_v1`). Le front n'envoie qu'une cle logique OPAQUE (`ag_<hash>`). | un `agent_id` brut (jamais expose au front) ; `BUSINESS_DOMAINS` (la liste des domaines, staffes ou non). |
| mode (eco / medium / high) | La cle LOGIQUE choisie par l'utilisateur qui pilote le modele de boucle : eco=Gemini 3.1 Flash-Lite (defaut), medium=Gemini 3.5 Flash, high=Claude Sonnet 4.6. Un seul modele pilote tout le tour (pas d'escalade). | un id de modele brut (le front n'en envoie jamais) ; le modele du Semantic Model Query tool (Sonnet, dans TOUS les modes). |
| Flow | L'orchestration de datasets/recettes DSS. Au RUNTIME : zero Flow (sauf la trace write-only). Les recettes du Flow tournent DESIGN-TIME pour fabriquer profil + value index. | le runtime SQL direct (`SQLExecutor2`) ; le moteur SQL du Semantic Model. |
| SQLExecutor2 | L'API DSS de SQL direct utilisee par le backend (un executor FRAIS par appel, valeurs parametrees, COMMIT explicite). | le Flow ; une route SQL generique (il n'en existe aucune). |
| Phase / scenario | La colonne `Phase` de `DRIVE_Revenues` = la version de la mesure : `ACTUALS` (defaut), `BUDGET`, `FORECAST`, `Q3F`, `HLF`. On ne SOMME JAMAIS entre Phases. | le booking_type ; une periode temporelle (`year_month`). Toujours `ACTUALS` au PLURIEL, jamais `ACTUAL`. |
| sirano_product | Le niveau technique le plus bas de la hierarchie d'offre (`Product` > `Solution` > `SolutionLine` > `sirano_product`). JAMAIS le defaut (les lignes BUDGET peuvent ne pas le porter -> budget=0). | `Product` (le niveau granulaire par defaut) ; le nom de produit affichable. |
| honesty firewall (pare-feu d'honnetete) | La regle de l'orchestrateur : n'emettre aucun fait metier non source ; ne jamais dire qu'une donnee "n'existe pas" ; au plus dire "pas encore d'AGENT pour ce domaine" (capability gap). | une simple validation de payload ; un refus generique. |
| trust layer / niveau de verification | L'echelle deterministe d'Evidence : `declared` -> `source_identified` -> `scope_partial` -> `scope_exact` -> `calc_decomposed` (+ `result_captured` orthogonal). Le badge n'est JAMAIS vert. | un score de confiance LLM ; un statut de run. |
| profil (`DRIVE_Revenues_profile`) | Le "cerveau metier" fabrique design-time (schema, metriques, scenario, axes, synonymes), revisable via overrides humains qui gagnent toujours. | le value index (grounding) ; le Value_Catalog (roadmap). |
| capability gap | La seule forme de "non" autorisee par l'orchestrateur : "il n'y a pas encore d'AGENT pour ce domaine" (vs "la donnee n'existe pas", interdit). | une erreur technique ; un out-of-scope (hors-sujet metier). |

Conventions d'ecriture lexicale :
- On ecrit "le sous-agent" (avec trait d'union), "design-time" et "runtime" tels quels, "read-only",
  "owner-scoping", "fan-out".
- Les noms canoniques des deux Code Agents sont `OWIsMind_orchestrator` et `SalesDrive_revenue_expert`
  (ce dernier = `agent:bHrWLyOL`). N'utilise PAS les anciens noms `orchestrator_agent.py`,
  `dataset_expert_langgraph.py`, `agent:AKQaQ0Am` (renommages anterieurs, vestiges dans certaines docs).
- La table chat courante est `webapp_chat_v5` (jamais `webapp_chat_v4`).

---

## 3. Arborescence des livrables

Reproduis EXACTEMENT cette arborescence. Chaque fichier a un objet d'une ligne (sa raison d'etre) ;
n'ecris pas hors de ce perimetre, et ne cree pas de fichier non liste.

| Chemin | Objet (une ligne) |
|---|---|
| `project-documentation/README.md` | OWIsMind - Documentation du projet (portail d'entree, oriente vers les sections). |
| `project-documentation/00-overview/01-product-overview.md` | Vue d ensemble du produit (probleme resolu, trio differenciant, valeur). |
| `project-documentation/00-overview/02-scope-and-limitations.md` | Perimetre et limites (ce que le produit FAIT et NE FAIT PAS, points en flux). |
| `project-documentation/00-overview/03-glossary.md` | Glossaire (deroule la terminologie canonique de la section 2 pour le lecteur). |
| `project-documentation/01-user-guide/01-getting-started.md` | Prise en main (ouvrir l app, premiere question, reperes d ecran). |
| `project-documentation/01-user-guide/02-using-the-chat.md` | Utiliser le chat (prompt, agent picker, mode, timeline, versions, stop). |
| `project-documentation/01-user-guide/03-understanding-evidence.md` | Comprendre les resultats (Evidence Studio cote utilisateur : badge, chips, drill, chart). |
| `project-documentation/01-user-guide/04-faq-and-troubleshooting.md` | FAQ et depannage (utilisateur) : reponses pratiques + messages d erreur frequents. |
| `project-documentation/02-architecture/01-system-overview.md` | Vue d ensemble de l architecture (les 4 couches, une phrase chacune, contexte systeme). |
| `project-documentation/02-architecture/02-component-map.md` | Carte des composants (frontend / backend / agents / stockage et leurs modules). |
| `project-documentation/02-architecture/03-runtime-flows.md` | Flux d execution (runtime) : tour de chat complet, polling, artifact, ouverture Evidence. |
| `project-documentation/02-architecture/04-security-model.md` | Modele de securite (architecture) : trust boundary, run-as-user, owner-scoping, whitelist. |
| `project-documentation/02-architecture/05-technology-stack.md` | Stack technique et dependances (Vue/Vite, Flask 3.9, LangGraph 3.11, PostgreSQL, versions). |
| `project-documentation/03-frontend/01-overview-and-structure.md` | Frontend - vue d ensemble et structure (bootstrap, router hash, i18n, theme). |
| `project-documentation/03-frontend/02-state-and-stores.md` | Frontend - etat et stores Pinia (chat, session, evidence, ui + modules purs). |
| `project-documentation/03-frontend/03-components-and-views.md` | Frontend - composants et vues (arbre de composants, ChatThread, MessageAgent, EvidencePanel). |
| `project-documentation/03-frontend/04-backend-communication.md` | Frontend - communication avec le backend (client, catalogue d appels, boucle de polling, codes d erreur). |
| `project-documentation/03-frontend/05-build-and-assets.md` | Frontend - build et assets (Vite base/outDir, body.html, tokens, hashs). |
| `project-documentation/04-backend/01-overview-and-structure.md` | Backend - vue d ensemble et structure (blueprint, sous-packages, conventions transverses). |
| `project-documentation/04-backend/02-api-reference.md` | Backend - reference de l API (tous les endpoints `/owismind-api/*`, payloads, codes). |
| `project-documentation/04-backend/03-streaming-and-runs.md` | Backend - streaming et cycle de vie des runs (stream_manager, worker, poll, stop, caps). |
| `project-documentation/04-backend/04-storage-and-data-model.md` | Backend - stockage et modele de donnees (tables `_vN`, arbre de conversation, usage, naming SQL). |
| `project-documentation/04-backend/05-evidence-and-artifacts.md` | Backend - Evidence Studio et artifacts (capture, sql_parse/explain, niveaux, chart_payload). |
| `project-documentation/04-backend/06-security-and-validation.md` | Backend - securite et validation (validation des payloads, SQL surete, gardes read-only). |
| `project-documentation/05-agents/01-agent-system-overview.md` | Systeme d agents - vue d ensemble (orchestrateur + sous-agent, contrats geles, invariant central). |
| `project-documentation/05-agents/02-orchestrator.md` | L orchestrateur (`OWIsMind_orchestrator`) : boucle LangGraph, registre, tools, honesty firewall, modes. |
| `project-documentation/05-agents/03-revenue-expert-subagent.md` | Le sous-agent expert revenus (`SalesDrive_revenue_expert`) : pipeline UNDERSTAND/RESOLVE/QUERY/RENDER. |
| `project-documentation/05-agents/04-tools-and-semantic-model.md` | Outils d agents et Semantic Model (`revenue_semantic_query` `v4oqA6R`, `attribute_lookup`, modele aligne). |
| `project-documentation/05-agents/05-flow-recipes-and-grounding.md` | Recipes du Flow et fabrication de l expertise (profil, value index, value catalog, grounding inline). |
| `project-documentation/05-agents/06-models-prompts-and-llm-mesh.md` | Modeles, prompts et LLM Mesh (modes par mode, with_json_output, appels natifs, tokens de controle). |
| `project-documentation/05-agents/07-deploying-and-editing-agents.md` | Deployer et editer les agents (recoller les 2 Code Agents env 3.11, verifier les ids). |
| `project-documentation/06-operations/01-installation-and-configuration.md` | Installation et configuration (upload plugin, connexion SQL, params webapp, premier admin). |
| `project-documentation/06-operations/02-build-package-deploy.md` | Build, packaging et deploiement (`/build-plugin`, `/package-plugin`, matrice quoi-rebuilder-quand). |
| `project-documentation/06-operations/03-monitoring-and-logs.md` | Supervision et logs (logs de requete content-free, observabilite Evidence, storage_status). |
| `project-documentation/06-operations/04-runbooks.md` | Runbooks (procedures d incident) : backend redemarre, mode qui ne repond pas, storage not configured. |
| `project-documentation/07-testing/01-test-strategy.md` | Strategie de tests (suites pure-logic backend/frontend/agents, NO INSTALL, ce qui exige DSS). |
| `project-documentation/07-testing/02-agent-evaluation.md` | Evaluation des agents (test anti-drift registre, smoke tests, golden queries, ce qui reste a valider DSS). |
| `project-documentation/08-decisions/README.md` | Decisions d architecture (ADR) - index des ADR. |
| `project-documentation/08-decisions/0001-vue-spa-servie-par-dss.md` | ADR-0001 - SPA Vue servie par DSS en assets statiques (router hash). |
| `project-documentation/08-decisions/0002-streaming-par-polling.md` | ADR-0002 - Streaming par polling (pas de SSE, proxy DSS). |
| `project-documentation/08-decisions/0003-sql-direct-sans-flow.md` | ADR-0003 - SQL direct, pas de Flow au runtime (posture de surete). |
| `project-documentation/08-decisions/0004-whitelist-agents-serveur.md` | ADR-0004 - Whitelist d agents cote serveur (cle logique opaque). |
| `project-documentation/08-decisions/0005-langgraph-code-agents-python-311.md` | ADR-0005 - Code Agents LangGraph en Python 3.11 (double chemin 3.9/3.11). |
| `project-documentation/08-decisions/0006-appels-natifs-llm-mesh.md` | ADR-0006 - Appels natifs LLM Mesh dans les noeuds (pas `as_langchain_chat_model`). |
| `project-documentation/08-decisions/0007-json-output-force-sur-understand.md` | ADR-0007 - `with_json_output` force sur UNDERSTAND (reasoning reserve au routing/prose). |
| `project-documentation/08-decisions/0008-evidence-trust-layer-et-artifacts.md` | ADR-0008 - Evidence trust layer et artifacts (separer signal et donnee). |
| `project-documentation/08-decisions/0009-modeles-par-mode.md` | ADR-0009 - Modeles par mode et propagation du mode (architecture model-agnostic). |
| `project-documentation/08-decisions/0010-grounding-et-semantic-model.md` | ADR-0010 - Grounding via value_index, le Semantic Model possede le SQL (moteur hybride). |
| `project-documentation/08-decisions/0011-sous-agent-assistif.md` | ADR-0011 - Sous-agent assistif (n impose pas une colonne pour un terme ambigu). |
| `project-documentation/08-decisions/0012-regle-typographique-sans-tiret-cadratin.md` | ADR-0012 - Regle typographique : pas de tiret cadratin. |
| `project-documentation/09-maintenance/01-contributing-and-conventions.md` | Contribuer - conventions et regles (NO INSTALL, regles non negociables, ces conventions de doc). |
| `project-documentation/09-maintenance/02-repository-map.md` | Carte du depot (ou vit quoi : Plugin/, dataiku-agents/, docs/, memory/). |
| `project-documentation/09-maintenance/03-known-gotchas-and-lessons.md` | Pieges connus et lecons (synthese des gotchas transverses). |

Identifiants canoniques a citer tels quels dans les docs concernees : plugin id `owismind` (version
`0.0.1`), webapp `webapp-owismind-ai-agents`, package python-lib `owismind`, dossier resource
`owismind-app`, prefixe API `/owismind-api` (sante `/owismind-api/ping`), connexion SQL `SQL_owi`
(PostgreSQL, schema `public`), project key `OWISMIND_DEV` (resolu serveur), Vite `base`
`/plugins/owismind/resource/owismind-app/` -> `outDir ../resource/owismind-app`, backend Flask Python
3.9.23, Code Agents env Python 3.11, plateforme DSS 14.4.x.

---

## 4. Inventaire des diagrammes Mermaid (un seul foyer par diagramme)

Pour eviter la duplication, chaque diagramme MAJEUR a UN fichier proprietaire ("foyer canonique"). Si
ton document a besoin d un diagramme deja possede ailleurs, NE le redessine pas : decris le point en
prose et renvoie au foyer via un lien relatif. Tu peux toujours ajouter un MINI-schema local strictement
specifique a ta page (ex. un sous-arbre de composants) tant qu il ne reproduit pas un diagramme majeur.

| Diagramme majeur | Foyer canonique (le SEUL a le dessiner) | Qui y renvoie (sans le redessiner) |
|---|---|---|
| Contexte systeme (les 4 couches : frontend, backend Flask, Code Agents/LLM Mesh, PostgreSQL + Flow design-time) | `02-architecture/01-system-overview.md` | `00-overview/01-product-overview.md`, `02-architecture/02-component-map.md`, `05-agents/01-agent-system-overview.md` |
| Carte des composants (modules par couche : stores Pinia, sous-packages python-lib, recipes) | `02-architecture/02-component-map.md` | `03-frontend/01-overview-and-structure.md`, `04-backend/01-overview-and-structure.md` |
| Sequence complete d un tour de chat (front -> `/chat/start` -> worker -> agents -> `/chat/poll` -> persist -> auto-open Evidence) | `02-architecture/03-runtime-flows.md` | `04-backend/02-api-reference.md`, `04-backend/03-streaming-and-runs.md`, `03-frontend/04-backend-communication.md`, `05-agents/01-agent-system-overview.md` |
| Streaming-par-polling (thread worker + dict `_RUNS` + boucle `/chat/poll` 500 ms + curseur) | `04-backend/03-streaming-and-runs.md` | `02-architecture/03-runtime-flows.md`, `03-frontend/04-backend-communication.md`, `08-decisions/0002-streaming-par-polling.md` |
| Pipeline d artifact (event `ARTIFACT` -> normalisation -> `webapp_artifacts_v1` -> `/evidence/meta` -> onglets) | `04-backend/05-evidence-and-artifacts.md` | `05-agents/02-orchestrator.md`, `03-frontend/03-components-and-views.md`, `08-decisions/0008-evidence-trust-layer-et-artifacts.md` |
| Ouverture/preuve Evidence (Run -> Capture -> Persist -> Prove -> Explore, + niveaux de verification) | `04-backend/05-evidence-and-artifacts.md` | `01-user-guide/03-understanding-evidence.md`, `02-architecture/03-runtime-flows.md` |
| Modele de donnees SQL (tables `webapp_chat_v5` / `webapp_users_v1` / `webapp_settings_v1` / `webapp_usage_monthly_v1` / `webapp_artifacts_v1` + arbre `parent_exchange_id`) | `04-backend/04-storage-and-data-model.md` | `02-architecture/02-component-map.md`, `04-backend/02-api-reference.md` |
| Boucle de l agent (orchestrateur LangGraph : `agent` -> `tools` -> `agent` -> `finish` ; sous-agent UNDERSTAND -> RESOLVE -> QUERY -> RENDER) | `05-agents/01-agent-system-overview.md` | `05-agents/02-orchestrator.md`, `05-agents/03-revenue-expert-subagent.md` |
| Recipes du Flow (design-time : `DRIVE_Revenues` -> profil / value index / value catalog) | `05-agents/05-flow-recipes-and-grounding.md` | `05-agents/04-tools-and-semantic-model.md`, `02-architecture/02-component-map.md`, `08-decisions/0010-grounding-et-semantic-model.md` |

Regle d arbitrage : si deux documents pourraient legitimement heberger un diagramme, le foyer est
celui qui est cite ci-dessus, point. Les ADR de la section 08 illustrent une DECISION ; ils renvoient au
diagramme du flux concerne plutot que de le copier.

---

## 5. Carte des liens croises (principales relations "Voir aussi")

Ces relations sont le squelette des sections `## Voir aussi`. Mets au minimum les liens listes pour ton
fichier ; tu peux en ajouter d autres pertinents, mais toujours en chemin relatif valide.

- `README.md` (portail) -> pointe vers chaque section d entree : `00-overview/01-product-overview.md`,
  `01-user-guide/01-getting-started.md`, `02-architecture/01-system-overview.md`,
  `06-operations/01-installation-and-configuration.md`, `08-decisions/README.md`.
- `00-overview/01-product-overview.md` <-> `00-overview/02-scope-and-limitations.md` <->
  `00-overview/03-glossary.md` ; et -> `02-architecture/01-system-overview.md`.
- `00-overview/03-glossary.md` -> renvoie vers chaque document qui APPROFONDIT un terme (orchestrateur ->
  `05-agents/02-orchestrator.md`, Evidence -> `04-backend/05-evidence-and-artifacts.md`, grounding ->
  `05-agents/05-flow-recipes-and-grounding.md`, polling -> `04-backend/03-streaming-and-runs.md`).
- Guide utilisateur : `01-user-guide/02-using-the-chat.md` <-> `01-user-guide/03-understanding-evidence.md`
  <-> `01-user-guide/04-faq-and-troubleshooting.md` ; et `03-understanding-evidence.md` ->
  `04-backend/05-evidence-and-artifacts.md` (pour le lecteur technique).
- Architecture : `02-architecture/01-system-overview.md` -> `02-component-map.md` -> `03-runtime-flows.md`
  -> `04-security-model.md` -> `05-technology-stack.md` (chaine de lecture). Chacun renvoie vers la
  section approfondie correspondante (`03-frontend/*`, `04-backend/*`, `05-agents/*`).
- `02-architecture/04-security-model.md` <-> `04-backend/06-security-and-validation.md` (l un cadre,
  l autre detaille) ; et -> `08-decisions/0004-whitelist-agents-serveur.md`,
  `08-decisions/0003-sql-direct-sans-flow.md`.
- `02-architecture/03-runtime-flows.md` <-> `04-backend/03-streaming-and-runs.md` <->
  `03-frontend/04-backend-communication.md` (le meme flux vu de 3 angles) ; et ->
  `08-decisions/0002-streaming-par-polling.md`.
- Frontend : `03-frontend/01-overview-and-structure.md` -> `02-state-and-stores.md` ->
  `03-components-and-views.md` -> `04-backend-communication.md` -> `05-build-and-assets.md`.
  `04-backend-communication.md` <-> `04-backend/02-api-reference.md`. `05-build-and-assets.md` <->
  `06-operations/02-build-package-deploy.md`.
- Backend : `04-backend/01-overview-and-structure.md` -> `02-api-reference.md` / `03-streaming-and-runs.md`
  / `04-storage-and-data-model.md` / `05-evidence-and-artifacts.md` / `06-security-and-validation.md`.
  `02-api-reference.md` <-> `03-frontend/04-backend-communication.md`. `05-evidence-and-artifacts.md` <->
  `01-user-guide/03-understanding-evidence.md` et `08-decisions/0008-evidence-trust-layer-et-artifacts.md`.
- Agents : `05-agents/01-agent-system-overview.md` -> `02-orchestrator.md` / `03-revenue-expert-subagent.md`
  / `04-tools-and-semantic-model.md` / `05-flow-recipes-and-grounding.md` / `06-models-prompts-and-llm-mesh.md`
  / `07-deploying-and-editing-agents.md`. `02-orchestrator.md` <-> `03-revenue-expert-subagent.md` (contrat
  de collaboration). `04-tools-and-semantic-model.md` <-> `05-flow-recipes-and-grounding.md`.
  `06-models-prompts-and-llm-mesh.md` -> `08-decisions/0006-appels-natifs-llm-mesh.md`,
  `08-decisions/0007-json-output-force-sur-understand.md`, `08-decisions/0009-modeles-par-mode.md`.
  `07-deploying-and-editing-agents.md` <-> `06-operations/02-build-package-deploy.md`.
- Operations : `06-operations/01-installation-and-configuration.md` -> `02-build-package-deploy.md` ->
  `03-monitoring-and-logs.md` -> `04-runbooks.md`. `04-runbooks.md` -> `04-backend/03-streaming-and-runs.md`,
  `05-agents/07-deploying-and-editing-agents.md`.
- Testing : `07-testing/01-test-strategy.md` <-> `07-testing/02-agent-evaluation.md` ; et ->
  `06-operations/02-build-package-deploy.md` (NO INSTALL, compile-check).
- Decisions : `08-decisions/README.md` indexe les 12 ADR ; chaque ADR renvoie vers le(s) document(s) de
  reference qui detaille(nt) la decision (ex. ADR-0002 -> `04-backend/03-streaming-and-runs.md`, ADR-0010
  -> `05-agents/05-flow-recipes-and-grounding.md`).
- Maintenance : `09-maintenance/01-contributing-and-conventions.md` -> ce fichier de conventions et les
  regles non negociables ; `02-repository-map.md` -> `02-architecture/02-component-map.md` ;
  `03-known-gotchas-and-lessons.md` -> les ADR concernes et les runbooks.

---

## 6. Rappels de regles projet (a respecter dans la doc et a documenter fidelement)

Ces regles sont la realite du projet ; documente-les telles quelles et ne les contredis pas.

1. NO INSTALL : l agent n installe jamais de dependance ; seul l utilisateur installe. La doc ne propose
   jamais une commande d install comme etape "normale".
2. Surete instance Dataiku : SQL borne/read-only/parametre, COMMIT explicite, executor frais par appel,
   caps partout. Pas de route SQL generique, le front ne choisit jamais table/connexion/requete.
3. Whitelist agents serveur : le front envoie une cle logique opaque ; le backend resout l `agent_id`.
4. Frontend jamais dans le zip ; ne jamais editer a la main les sorties generees
   (`resource/owismind-app/`, `ready-for-dataiku/`, `body.html` se recable par build).
5. Code en anglais (dans le code) ; communication et prose de doc en francais.
6. Regle #9 : zero tiret cadratin/demi-cadratin (voir 1.2).
7. La memoire (`memory/PROJECT_STATE.md` + `memory/LESSONS.md`) prime sur les guides `docs/cadrage/` ;
   le code prime sur la doc periimee. Quand un research pack signale une divergence doc-vs-code, suis le
   code.

Bonne redaction. Reste ancre, reste concis, et lie au lieu de dupliquer.
