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

- **Au démarrage** : lire `memory/CONTEXT.md` (auto-importé ci-dessus), puis `memory/LESSONS.md` et
  `memory/PROJECT_STATE.md` pour le détail. Vérifier qu'un fichier/flag cité existe encore avant de t'y fier.
- **Source de vérité** : `memory/PROJECT_STATE.md` + `memory/LESSONS.md` **priment sur les guides** de
  `docs/cadrage/` (ceux-ci sont des points de départ). Les noms réels et les solutions qui marchent vivent en mémoire.
- **Apprentissage continu** : dès qu'une solution diverge des guides, ou qu'un truc échoue puis marche →
  **appende** une entrée dans `memory/LESSONS.md` (contexte / échec / solution / preuve / source / date).
- **Fin de session** : exécuter `/log-session` (met à jour `CONTEXT.md` + `memory/sessions/`).

## Identifiants canoniques (détail → `memory/PROJECT_STATE.md`)
- Plugin id `owismind` · WebApp `webapp-owismind-ai-agents` · package `python-lib/owismind` · resource `owismind-app`
- Racine plugin sur disque : `Plugin/owismind/` · staging zip : `Plugin/ready-for-dataiku/owismind-upload/`
- Vite `base` `/plugins/owismind/resource/owismind-app/` → `outDir ../resource/owismind-app`
- SQL : connexion `SQL_owi` (PostgreSQL, `public`) · project key `OWISMIND_DEV` (via `default_project_key()`)
- Agents (Code Agents LangGraph, env 3.11, repo = source de vérité, à recoller dans DSS) **dupliqués
  par projet DSS** sous `dataiku-agents/OWISMIND/{OWISMIND_DEV, OWISMIND_PROD_V1}/` (fichiers préfixés
  par le projet ; **on développe en DEV puis on promeut en PROD**). Carte des IDs + workflow :
  **`dataiku-agents/OWISMIND/README.md`** (et chaque `registry.json`). Orchestrateur **OWIsMind_orchestrator**
  (DEV `038G7mlF` / PROD `Xrv7GvfG`) → sous-agent revenus **SalesDrive_revenue_expert** (DEV `agent:bHrWLyOL`
  / PROD `agent:uO5hEzAs`) ; 2e sous-agent **CSSO_Trouble_Tickets_Expert** (DEV `agent:NcE9LD2i`, en cours,
  pas encore en PROD).
- API `/owismind-api/*` (santé `/owismind-api/ping`)
- ⚠️ Les guides de `docs/cadrage/` utilisent des **noms d'exemple** (`owismind-vue`, `owismindvue`, …) - **ne pas les recopier**.

## Commandes clés (→ skills, ne pas recopier les commandes ici)
- `/build-plugin` : `npm run build` (frontend) → `resource/owismind-app/`, puis `index.html` → `body.html`.
- `/package-plugin` : stage runtime → zip `ready-for-dataiku/owismind-upload.zip` (sans frontend/node_modules).
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
9. **JAMAIS de tiret cadratin `—` (U+2014) ni de tiret demi-cadratin `–` (U+2013)** - bannis à tout jamais,
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

## Référence
- `docs/cadrage/CHARTE_ORANGE_UI.md` - **charte de style UI (règle #10), auto-suffisante** : tokens, géométrie carrée, recettes de composants, interdits. À lire avant tout travail de style (la maquette HTML d'origine a été supprimée, cette charte la remplace).
- `docs/cadrage/owismind_webapp_v3_cahier_des_charges_fonctionnel.md` - cahier des charges fonctionnel (produit ; Evidence Studio = intention future différée).
- `docs/cadrage/GUIDE_DATAIKU_DSS_PLUGIN_REFERENCE.md` - référence d'ingénierie unique : build/package/zip, SQL direct, agents LLM Mesh + streaming, gotchas Dataiku.
- `docs/cadrage/code_samples_dataiku.md` - snippets notebook validés (appel agent streamé + extraction SQL/usage, table SQL directe).
- `docs/` - référence d'ingénierie (architecture, API, frontend, data model, sécurité, build/deploy) ; `docs/superpowers/specs/` = specs de conception gelées.

> À lire **à la demande** (ne pas recopier leur contenu ici). En cas de conflit guides ↔ mémoire : la mémoire fait foi.
