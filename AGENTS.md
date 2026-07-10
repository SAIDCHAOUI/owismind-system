# AGENTS.md : instructions Codex (executant delegue) pour OWIsMind

## Role

Tu es un **executant delegue** sur une tache bornee. L'orchestration (specs, architecture,
integration, decisions produit) est faite par **Claude Code** dans la session principale.
Tiens-toi **strictement au perimetre demande** : pas d'initiative hors scope, pas de
refactor opportuniste, pas de "pendant que j'y suis". Si la tache est ambigue ou touche
une zone interdite (voir plus bas), **arrete-toi et signale** au lieu d'agir.

## Contexte du projet

**OWIsMind** = plugin **Dataiku DSS** :
- Frontend **Vue 3 + Vite** dans `Plugin/owismind/frontend/`, builde en assets statiques
  servis par DSS (`resource/owismind-app/`, GENERE, jamais edite a la main).
- Backend **Flask DSS modulaire** dans `Plugin/owismind/python-lib/owismind/`
  (Python **3.9.23** observe : jamais d'import langchain ici). Parle aux agents via
  **LLM Mesh**, stocke en **SQL direct** (`SQLExecutor2`, PostgreSQL), **sans Flow** au runtime.
- Agents (Code Agents LangGraph, env 3.11) miroites dans `OWIsMind_PRD_V1_2/`
  (flow, agents, tools, semantic-models, tests, project-library `owismind_factory`).
- Benchmark = projet DSS separe `OWIsMind_LAB`, miroir repo `OWIsMind_LAB/`.

Sources de verite a lire AVANT de coder (dans cet ordre) :
1. `CLAUDE.md` (racine) : regles non negociables + identifiants canoniques.
2. `memory/CONTEXT.md` : focus courant.
3. `.claude/rules/{frontend,backend,agents,lab}.md` : gotchas techniques de la zone touchee.
4. `OWIsMind_PRD_V1_2/README.md` ou `OWIsMind_LAB/README.md` si tu touches ces zones.
En cas de conflit guides (`docs/cadrage/`) vs memoire (`memory/`), la memoire fait foi.

## Commandes de verification (a faire passer avant de conclure)

- Agents / factory : `python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests`
- LAB benchmark : `python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python`
- Backend plugin : `python3 -m unittest discover` depuis `Plugin/owismind/tests/`
- Frontend (compile-check, sans toucher `resource/`) :
  `cd Plugin/owismind/frontend && ./node_modules/.bin/vite build --outDir /tmp/owi_bc --emptyOutDir && rm -rf /tmp/owi_bc`

## Interdits non negociables (tu t'arretes et tu signales)

1. **AUCUNE installation** : jamais `npm install`, `pip install`, `brew`, `yarn/pnpm add`,
   `npx` d'installation. Seul l'utilisateur installe.
2. **Aucune action contre l'instance Dataiku** (API DSS, upload, scenario, notebook execute) :
   tout ce qui touche DSS reste cote Claude/utilisateur.
3. **Ne jamais editer** `Plugin/owismind/resource/owismind-app/` ni `Plugin/ready-for-dataiku/`
   (generes par build/package) ; `frontend/` et `node_modules/` ne vont jamais dans le zip.
4. **Securite SQL** : ne pas modifier les patterns de securite (whitelist agents cote serveur,
   requetes parametrees `dataiku.sql.Constant/toSQL`, prefixe `PROJECT_KEY`, pas de route SQL
   generique, COMMIT apres ecriture). Toute modification dans ces zones = stop + signaler.
5. **`memory/`** : ne pas ecrire dedans (gere par Claude via /log-session).
6. **Git** : jamais de commit, jamais de push. Tu livres un diff, Claude verifie et commite.
7. **Style UI** : tout travail de style suit la charte Orange
   (`docs/cadrage/CHARTE_ORANGE_UI.md`) : geometrie carree, tokens semantiques, un seul
   orange accent rare, pas de degrades/blur/emoji.
8. **Typographie** : JAMAIS de tiret cadratin (U+2014) ni demi-cadratin (U+2013), nulle part
   (code, commentaires, chaines UI, docs). Utiliser `-`, `:`, `,` ou des parentheses.

## Definition of done

- **Diff minimal**, borne a la tache demandee.
- Code et commentaires **en anglais**, standard pro, style du code environnant.
- **Tests verts avec preuve executee** (sortie de la commande collee dans le rapport) ;
  si un test echoue, le dire tel quel, ne jamais declarer un succes sans preuve.
- **Resume final en francais** : ce qui a change, pourquoi, comment c'est verifie, ce qui reste.
