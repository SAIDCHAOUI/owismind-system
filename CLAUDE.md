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
  **automatiquement** selon les fichiers touchés (frontend / backend / agents / memory), plus dans CONTEXT.md.
- **Source de vérité** : `memory/PROJECT_STATE.md` + `memory/LESSONS.md` **priment sur les guides** de
  `docs/cadrage/` (ceux-ci sont des points de départ). Les noms réels et les solutions qui marchent vivent en mémoire.
- **Apprentissage continu** : dès qu'une solution diverge des guides, ou qu'un truc échoue puis marche →
  **appende** une entrée dans `memory/LESSONS.md` (contexte / échec / solution / preuve / source / date). Un
  changement de gotcha va dans le bon fichier `.claude/rules/`, pas dans CONTEXT.md.
- **Fin de session** : exécuter `/log-session` (met à jour `CONTEXT.md` + commit).

## Identifiants canoniques (détail → `memory/PROJECT_STATE.md`)
- Plugin id `owismind` · WebApp `webapp-owismind-ai-agents` · package `python-lib/owismind` · resource `owismind-app`
- **Arborescence (2026-07-20)** : un dossier racine par projet DSS, même structure interne (`flow/<zone>_zone/python-recipes/`, `GenAI/{Agents, agents-tools, semantic-models}`, `Notebooks/`, `project-library/`, `Standard-webapps/`, `docs/`, `tests/`). Le plugin vit DANS le dossier du projet principal (`plugin/`) et suit sa version.
- Racine plugin sur disque : `OWIsMind_PRD_V2_0/plugin/owismind/` (version `2.0.0`) · zips d'upload : `OWIsMind_PRD_V2_0/plugin/ready-for-dataiku/` (git-ignorés, régénérés par les skills ; zip courant `owismind_v2_0-upload.zip`, coexiste avec les versions précédentes)
- Vite `base` `/plugins/owismind/resource/owismind-app/` → `outDir ../resource/owismind-app`
- SQL : connexion `SQL_owi` (PostgreSQL, `public`) · project key **PROD `OWISMIND_PRD_V1_2`**, **DEV `OWISMIND_DEV`** (résolu au runtime via `dataiku.default_project_key()`)
- Agents (Code Agents LangGraph, env 3.11, repo = source de vérité, à recoller dans DSS) : miroités sous
  **`OWIsMind_PRD_V2_0/`** (= le projet DSS V2.0, duplication du projet v1.3, ids conservés), organisé en
  miroir de l'UI DSS. Carte des IDs : **`OWIsMind_PRD_V2_0/README.md`** + `OWIsMind_PRD_V2_0/registry.json`.
  Orchestrateur **OWIsMind_orchestrator** (`038G7mlF`) -> sous-agents **SalesDrive_revenue_expert**
  (`agent:bHrWLyOL`) et **CSSO_Trouble_Tickets_Expert** (`agent:NcE9LD2i`).
- Git : **une branche par version**, nommée comme le projet DSS (`OWIsMind_PRD_V1_2` = prod,
  `OWIsMind_PRD_V1_3-dev` = v1.3, `OWIsMind_PRD_V2_0` = V2 en cours ; `main` dépréciée). Cette branche ne
  contient QUE la V2 : les anciennes versions et `OWIsMind_LAB` vivent sur leurs branches.
- API `/owismind-api/*` (santé `/owismind-api/ping`)
- **Benchmark** : produit par le projet DSS séparé `OWIsMind_LAB` (code hors de cette branche, voir la
  branche `OWIsMind_PRD_V1_3-dev`) ; le plugin V2 en AFFICHE les résultats (`benchmark_view`, vue Benchmark).
- ⚠️ Les guides de `docs/cadrage/` utilisent des **noms d'exemple** (`owismind-vue`, `owismindvue`, …) - **ne pas les recopier**.

## Commandes clés (→ skills, ne pas recopier les commandes ici)
- `/build-plugin` : `npm run build` (frontend) → `resource/owismind-app/`, puis `index.html` → `body.html`.
- `/package-plugin` : stage runtime → zip versionné dans `ready-for-dataiku/` (sans frontend/node_modules).
- `/log-session` : log de fin de session + refresh mémoire courte + commit de session.

## Git
- Commit de session via `/log-session` (autorisation user 2026-06-11) ; **jamais de push** (l'user pushe).

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
6. **Ne pas éditer à la main** `OWIsMind_PRD_V2_0/plugin/owismind/resource/owismind-app/` ni `OWIsMind_PRD_V2_0/plugin/ready-for-dataiku/`
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
- **Routage multi-modèles : `.claude/rules/model-routing.md`** - Claude orchestre, subagents Opus/Sonnet
  implémentent, Codex (GPT-5.6, plugin `codex@openai-codex`, instructions `AGENTS.md` racine) exécute les
  tâches bornées (`/codex:rescue`) et les reviews croisées (`/codex:review`). Jamais deux agents sur les
  mêmes fichiers ; tout diff Codex re-vérifié côté Claude ; zones sensibles (SQL sécurité, artefacts
  générés, `memory/`, instance DSS) interdites à Codex seul.

## Référence
- `docs/cadrage/CHARTE_ORANGE_UI.md` - **charte de style UI (règle #10), auto-suffisante** : tokens, géométrie carrée, recettes de composants, interdits. À lire avant tout travail de style (la maquette HTML d'origine a été supprimée, cette charte la remplace).
- `docs/cadrage/owismind_webapp_v3_cahier_des_charges_fonctionnel.md` - cahier des charges fonctionnel (produit ; Evidence Studio = intention future différée).
- `docs/cadrage/GUIDE_DATAIKU_DSS_PLUGIN_REFERENCE.md` - référence d'ingénierie unique : build/package/zip, SQL direct, agents LLM Mesh + streaming, gotchas Dataiku.
- `docs/cadrage/code_samples_dataiku.md` - snippets notebook validés (appel agent streamé + extraction SQL/usage, table SQL directe).
- `OWIsMind_PRD_V2_0/docs/` - spec V2 (`V2_ARCHITECTURE.md`), notes de phase, charte V2, Agent Factory.

> À lire **à la demande** (ne pas recopier leur contenu ici). En cas de conflit guides ↔ mémoire : la mémoire fait foi.
