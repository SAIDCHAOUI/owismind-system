# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projet
**OWIsMind** = plugin **Dataiku DSS** : WebApp **Vue 3 + Vite** (frontend buildé en assets statiques
servis par DSS) + backend **Flask DSS** (modulaire dans `python-lib/`). Le backend parle aux agents via
**LLM Mesh** et stocke conversations/messages/runs/events en **SQL direct** (`SQLExecutor2`, PostgreSQL),
**sans Flow** au runtime. Le frontend Vue 3 est **complet et validé en DSS** (la maquette d'origine,
convertie, a été supprimée du repo le 2026-06-11).

## Mémoire (protocole)
@memory/CONTEXT.md

- **`memory/` (versionné git) = source de vérité d'équipe.** La mémoire native de Claude Code (auto-memory)
  n'est qu'un **cache personnel** : ne jamais s'en servir comme référence partagée.
- **Au démarrage** : `memory/CONTEXT.md` (auto-importé ci-dessus) = focus courant + chaîne des sessions +
  pointeurs, tenu LEAN (< 120 lignes). Lire `memory/LESSONS.md` et `memory/PROJECT_STATE.md` **à la demande**
  pour le détail. Vérifier qu'un fichier/flag cité existe encore avant de t'y fier.
- **Gotchas techniques = `.claude/rules/*.md`** (path-scoped, frontmatter `paths:`) : chargées
  **automatiquement** selon les fichiers touchés (frontend / backend / agents / lab / memory), plus dans CONTEXT.md.
- **Source de vérité** : `memory/PROJECT_STATE.md` + `memory/LESSONS.md` **priment sur les guides** de
  `docs/cadrage/` (ceux-ci sont des points de départ). Les noms réels et les solutions qui marchent vivent en mémoire.
- **Apprentissage continu** : dès qu'une solution diverge des guides, ou qu'un truc échoue puis marche →
  **appende** une entrée dans `memory/LESSONS.md` (contexte / échec / solution / preuve / source / date). Un
  changement de gotcha va dans le bon fichier `.claude/rules/`, pas dans CONTEXT.md.
- **Fin de session** : exécuter `/log-session` (met à jour `CONTEXT.md` + `memory/sessions/` + graphe + commit).

## Identifiants canoniques (détail → `memory/PROJECT_STATE.md`)
- Plugin id `owismind` · WebApp `webapp-owismind-ai-agents` · package `python-lib/owismind` · resource `owismind-app`
- Racine plugin sur disque : `Plugin/owismind/` · staging zip **versionné** : `Plugin/ready-for-dataiku/owismind-v1_2-upload.zip` (nom dérivé de `plugin.json` 1.2.0)
- Vite `base` `/plugins/owismind/resource/owismind-app/` → `outDir ../resource/owismind-app`
- SQL : connexion `SQL_owi` (PostgreSQL, `public`) · project key **PROD `OWISMIND_PRD_V1_2`**, **DEV `OWISMIND_DEV`** (résolu au runtime via `dataiku.default_project_key()`)
- Agents (Code Agents LangGraph, env 3.11, repo = source de vérité, à recoller dans DSS) : le projet DSS
  PROD **`OWISMIND_PRD_V1_2` = CLONE du projet DEV `OWISMIND_DEV`** (ids DEV conservés), miroité dans le repo
  sous **`OWIsMind_PRD_V1_2/`** (`flow/`, `agents/`, `tools/`, `semantic-models/`, `tests/`). Carte des IDs :
  **`OWIsMind_PRD_V1_2/README.md`** + `OWIsMind_PRD_V1_2/registry.json`. Orchestrateur **OWIsMind_orchestrator**
  (`038G7mlF`) → sous-agents **SalesDrive_revenue_expert** (`agent:bHrWLyOL`) et **CSSO_Trouble_Tickets_Expert**
  (`agent:NcE9LD2i`) - mêmes ids en DEV et dans le clone.
- Git : **une branche par version**, nommée comme le projet DSS prod (`OWIsMind_PRD_V1_2` = prod courante,
  `OWIsMind_PRD_V1_3-dev` = dev en cours, suffixe `-dev` retiré à la validation ; `main` dépréciée).
- API `/owismind-api/*` (santé `/owismind-api/ping`)
- **Benchmark / éval des agents = projet DSS SÉPARÉ `OWIsMind_LAB`** (≠ le plugin), miroir repo
  **`OWIsMind_LAB/`** : `project-library/python/{benchmark, benchmark_webapp}` (recollés en project-library,
  packages importés `from benchmark ...` / `from benchmark_webapp ...`), `webapps/{benchmark_launcher,
  benchmark_results}` (2 webapps Standard), `local-variables.example.json` (la variable `benchmark`),
  scénario `Run_Benchmark` (3 steps = `benchmark/dss_steps/step_*.py`). **Carte repo↔DSS : `OWIsMind_LAB/README.md`.**
  Tests : `python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python`.
- ⚠️ Les guides de `docs/cadrage/` utilisent des **noms d'exemple** (`owismind-vue`, `owismindvue`, …) - **ne pas les recopier**.

## Commandes clés (→ skills, ne pas recopier les commandes ici)
- `/build-plugin` : `npm run build` (frontend) → `resource/owismind-app/`, puis `index.html` → `body.html`.
- `/package-plugin` : stage runtime → zip versionné `ready-for-dataiku/owismind-v1_2-upload.zip` (sans frontend/node_modules).
- `/log-session` : log de fin de session + refresh mémoire courte + `/graphify --update` + commit de session.

## Graphe de connaissances (`graphify-out/`, git-ignoré)
- Pour naviguer (« où est géré X ? », « qu'est-ce qui touche Y ? ») : **interroger le graphe d'abord**
  (`graphify query "…"`) au lieu de relire les docs - ~18× moins de tokens. Visualisation : `graphify-out/graph.html`.
- Fraîcheur : hook git **post-commit** (rebuild AST auto, sans LLM) + `/log-session` (refresh sémantique
  incrémental + commit). Graphe périmé vs working tree → `/graphify --update`.
- Git : commit de session via `/log-session` (autorisation user 2026-06-11) ; **jamais de push** (l'user pushe).

## Règles NON NÉGOCIABLES
1. **NO INSTALL** - l'agent n'installe **jamais** de dépendances (`npm install`, `pip install`, `brew`,
   `yarn/pnpm add`, `npx` d'install…). Si besoin, **demander à l'utilisateur** : lui seul installe. Safety first.
2. **Safety instance Dataiku** - avant tout code, se demander : *est-ce risqué / lent / surchargeant pour
   l'instance ?* Éviter tout code qui peut nuire à l'instance, la ralentir ou la surcharger.
3. **SQL direct uniquement** : préfixe `PROJECT_KEY` sur les tables, `COMMIT` après écriture, requêtes
   **paramétrées** (`dataiku.sql.Constant/toSQL`), citation `public."OWISMIND_DEV_..."`. **Pas de Flow** au
   runtime, **pas de route SQL générique** exposée, le frontend ne choisit jamais table/connexion/requête.
4. **Whitelist agents côté serveur** : le front envoie une clé logique, le backend résout l'`agent_id`
   (jamais d'`agent_id` brut depuis le front).
5. **Frontend jamais dans le zip** : `frontend/` et `node_modules/` ne sont jamais packagés.
6. **Ne pas éditer à la main** `Plugin/owismind/resource/owismind-app/` ni `Plugin/ready-for-dataiku/`
   (générés par build/package - éditer `frontend/src` / `python-lib` / `webapps` puis rebuild).
7. **Code en anglais** (code + commentaires), optimisé, standard pro, bien commenté. La communication avec
   l'utilisateur reste en **français**.
8. Ne pas affirmer que Python 3.11 / FastAPI marchent sans preuve (backend observé = 3.9.23).
9. **JAMAIS de tiret cadratin (U+2014) ni de tiret demi-cadratin (U+2013)** - bannis à tout jamais,
   PARTOUT : chaînes i18n / texte UI, code, commentaires, mémoire, messages de commit ET réponses dans le chat.
   C'est une signature typographique d'IA, l'user l'interdit absolument. Utiliser `-`, `:`, `,` ou des
   parenthèses à la place. (Décision user 2026-06-17.)
10. **CHARTE ORANGE = style UI obligatoire, à CHAQUE travail de style** (page, composant, retouche). Source de
   vérité auto-suffisante : **`docs/cadrage/CHARTE_ORANGE_UI.md`** (lire AVANT de styliser). Essentiel :
   blanc / noir / **un seul orange `#FF7900` en accent RARE** ; **géométrie carrée** (`border-radius: 0`, seuls
   les avatars ronds) ; **aplats, filets 1px, gros titres lourds** (H1 36px/800, eyebrow orange MAJ, **title-bar
   orange 52x4px** sous le H1) ; toujours les **tokens sémantiques** de `frontend/src/styles/tokens.css` (jamais
   de hex en dur ; texte orange = `--orange-text` AA) ; **interdits** : `color-mix`, blur/backdrop-filter,
   dégradés, glow/grosses ombres, emoji, focus-ring orange global, **et visuel de marque reconstruit en CSS**
   (toujours la VRAIE image `frontend/src/assets/orange-logo.png`, jamais un carré généré). Dark via
   `body[data-theme]` + tokens. (Décision user 2026-06-18 : « à chaque fois qu'on fait du style, comme ça ».)

## Style de travail (tâches lourdes)
- **Monter l'effort** sur le travail difficile (conception, refactor, revue) ; ne pas sous-traiter le
  raisonnement à des appels d'outils prématurés.
- **Fan-out = sous-agents/workflows** quand plusieurs pistes indépendantes existent (Opus, pas Fable) ;
  l'instruire explicitement (Opus 4.8 spawn peu de sous-agents par défaut).
- **Gates de vérification avant de déclarer « fait »** : lancer les tests / le build et LIRE la sortie ;
  jamais d'affirmation de succès sans preuve.

## Référence
- `docs/cadrage/CHARTE_ORANGE_UI.md` - **charte de style UI (règle #10), auto-suffisante** : tokens, géométrie carrée, recettes de composants, interdits. À lire avant tout travail de style (la maquette HTML d'origine a été supprimée, cette charte la remplace).
- `docs/cadrage/owismind_webapp_v3_cahier_des_charges_fonctionnel.md` - cahier des charges fonctionnel (produit ; Evidence Studio = intention future différée).
- `docs/cadrage/GUIDE_DATAIKU_DSS_PLUGIN_REFERENCE.md` - référence d'ingénierie unique : build/package/zip, SQL direct, agents LLM Mesh + streaming, gotchas Dataiku.
- `docs/cadrage/code_samples_dataiku.md` - snippets notebook validés (appel agent streamé + extraction SQL/usage, table SQL directe).
- `OWIsMind_LAB/README.md` - **carte du projet benchmark** (projet DSS séparé `OWIsMind_LAB`) : layout repo↔DSS, mapping fichier→objet DSS, comment ça se connecte au plugin + aux agents, et les 2 guides de déploiement (`benchmark/SETUP_GUIDE.md` moteur, `benchmark_webapp/DEPLOY_GUIDE.md` complet). À lire pour tout travail sur le benchmark.
- `docs/` - référence d'ingénierie (architecture, API, frontend, data model, sécurité, build/deploy) ; `docs/superpowers/specs/` = specs de conception gelées.
- `project-documentation/` - doc d'ingénierie EN ultra-complète (arbre 00-09 + site HTML + pitch). **À lire UNIQUEMENT à la demande explicite** : exclue du graphe de connaissances (`.graphifyignore`) pour ne jamais entrer en contexte auto, et **potentiellement périmée** (à mettre à jour dans une future session). Source de vérité = `memory/` + `docs/cadrage/`, pas ce dossier. (Décision user 2026-06-26.)

> À lire **à la demande** (ne pas recopier leur contenu ici). En cas de conflit guides ↔ mémoire : la mémoire fait foi.
