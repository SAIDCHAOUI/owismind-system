# Build / Test / Package / Deploy - OWIsMind DSS plugin

> Procédure de release du plugin Dataiku DSS **OWIsMind** (WebApp Vue 3 + Vite servie par DSS,
> backend Flask modulaire dans `python-lib/owismind/`).
>
> **Source de vérité = la mémoire**, pas ce document. Les commandes opérationnelles vivent dans les
> skills `/build-plugin`, `/package-plugin`, `/log-session` ; les invariants validés EN DSS vivent dans
> [`memory/PROJECT_STATE.md`](../memory/PROJECT_STATE.md) (§3 = noms canoniques, §5 = chaîne build) et
> [`memory/LESSONS.md`](../memory/LESSONS.md). En cas de conflit guides `cadrage/` ↔ mémoire, **la mémoire
> fait foi**. Ce fichier ne réimplémente aucune commande : il décrit *quand* et *pourquoi*, et renvoie aux skills.
>
> Doc voisine : [architecture.md](architecture.md) · [backend-api.md](backend-api.md) ·
> [frontend.md](frontend.md) · [data-model.md](data-model.md) · [security.md](security.md).

---

## 0. Politique NO-INSTALL (à lire avant tout)

**L'agent n'installe JAMAIS de dépendances.** Aucune commande `npm install` / `npm ci` / `npm i` /
`npm add` / `npm update`, aucun `yarn`/`pnpm add`, aucun `pip install` / `pip3 install` / `poetry` /
`pipenv` / `conda install` / `brew install`, aucun `npx` d'install. **Seul l'utilisateur installe**
(safety first). Si une dépendance manque, l'agent **s'arrête et demande à l'utilisateur** de l'installer
lui-même (p. ex. `! cd Plugin/owismind/frontend && npm install`).

Ce garde-fou n'est pas qu'une convention : il est **appliqué par la configuration du harness** -

- [`.claude/settings.json`](../.claude/settings.json) → `permissions.deny` liste explicitement toutes
  les commandes d'installation (et bloque aussi l'écriture directe dans
  `Plugin/owismind/resource/owismind-app/**` via `Edit`/`Write`).
- le hook **PreToolUse** [`.claude/hooks/guardrail.sh`](../.claude/hooks/guardrail.sh) intercepte
  `Bash|Edit|Write|MultiEdit|NotebookEdit` avant exécution.

Conséquence directe sur le repo : le frontend buildé (`resource/owismind-app/`) **est versionné** - un
clone frais ne pouvant pas réinstaller les outils, le payload doit voyager dans le repo pour rester
packageable (voir §9).

---

## 1. Noms canoniques (NE PAS inventer, NE PAS copier les exemples des guides)

Référence figée → [`memory/PROJECT_STATE.md` §3](../memory/PROJECT_STATE.md).

| Élément | Valeur réelle | Source |
|---|---|---|
| Plugin id | `owismind` | `Plugin/owismind/plugin.json` |
| WebApp component | `webapp-owismind-ai-agents` | `Plugin/owismind/webapps/` |
| Package python-lib | `owismind` (`python-lib/owismind/`) | repo |
| Dossier resource (assets buildés) | `owismind-app` | `vite.config.js`, `body.html` |
| Vite `base` | `/plugins/owismind/resource/owismind-app/` | `vite.config.js` |
| Vite `outDir` | `../resource/owismind-app` (+ `emptyOutDir: true`) | `vite.config.js` |
| Préfixe API | `/owismind-api` (santé `/owismind-api/ping`) | backend |
| Racine plugin (disque) | `Plugin/owismind/` (P majuscule) | repo |
| Frontend source | `Plugin/owismind/frontend/` | repo |
| Staging packaging | `Plugin/ready-for-dataiku/owismind-upload/` + `owismind-upload.zip` | repo |
| Connexion SQL | `SQL_owi` (PostgreSQL, schéma `public`) - sélectionnée dans les Settings de la webapp | guide SQL |
| Project key DSS | `OWISMIND_DEV` (résolu serveur via `dataiku.default_project_key()`) | guide SQL |
| Plateforme / Python | Dataiku DSS 14.4.x · backend **Python 3.9.23** (3.11/FastAPI NON validés) | `/ping` |

> ⚠️ Les guides de `cadrage/` emploient des **noms d'exemple** (`owismind-vue`, `owismindvue`,
> `webapp-owismind-vue`) qui **ne sont pas** les vrais noms. Toujours utiliser le tableau ci-dessus.
> `vite.config.js` (`base` + `outDir`) est **canonique** : ne jamais le modifier sans rebuild + recâblage
> de `body.html` (voir §8).

---

## 2. Développement local

Travail dans `Plugin/owismind/frontend/`. Scripts disponibles (cf.
[`package.json`](../Plugin/owismind/frontend/package.json)) : `dev`, `build`, `preview`, `test`.

### 2.1 Voir le rendu (`npm run dev`)

```bash
npm --prefix Plugin/owismind/frontend run dev
```

Le serveur Vite écoute sur le **port 5173**, sous la **même base d'assets** que la prod :

```
http://localhost:5173/plugins/owismind/resource/owismind-app/        (+ #/route pour le router HASH)
```

En DEV il n'y a **pas de backend DSS** : injecter une démo via `window.__pinia.state.value.{chat,session}`
(exposé en DEV par `main.js`). Validation visuelle = screenshots **Chrome DevTools MCP**, écrits dans un
chemin **à l'intérieur du repo** (gotcha **F1**). Tester light/dark et FR/EN.

### 2.2 Compile-check (build jetable)

Pour vérifier qu'un changement compile **sans** toucher l'app déployée :

```bash
./node_modules/.bin/vite build --outDir /tmp/owi_buildcheck --emptyOutDir
rm -rf /tmp/owi_buildcheck
```

> ⚠️ **Ne JAMAIS builder dans `resource/` hors du skill `/build-plugin`** - `outDir` y pointe avec
> `emptyOutDir: true`, donc un build sauvage **écrase l'app déployée**. Le build officiel passe uniquement
> par `/build-plugin` (§5). Le dossier `resource/owismind-app/` ne s'édite jamais à la main (bloqué par hook).

---

## 3. Tests

Les deux suites sont **pure-logic, sans environnement DSS et sans install** (runners natifs). Elles ne
remplacent pas la validation EN DSS (voir matrice §11 de `PROJECT_STATE.md`) : elles verrouillent les
invariants testables hors instance.

### 3.1 Backend - `unittest` (65 tests, vérifié)

```bash
python3 -m unittest discover -s Plugin/owismind/tests -v
```

Hors `python-lib/`, donc **jamais packagé**. Les tests mettent `python-lib/` sur `sys.path` pour résoudre
`owismind.*`. Détail des modules couverts → [`Plugin/owismind/tests/README.md`](../Plugin/owismind/tests/README.md).

Couvert aujourd'hui (DSS-free) : `validation` (`/chat/start` shape+bornes), `validate_history_limit`/
`validate_optional_exchange_id`, `validate_conversations_limit`, `validate_feedback`, les SQL builders
purs (`build_conversation_list_query`, `build_session_messages_query`, `build_ancestor_chain_query` -
**user-scopés + bornés**), `pagination` (cursor round-trip), `agents.context` (assemblage multi-tours),
`security.identity.derive_full_name`.

### 3.2 Frontend - `node:test` (27 tests, vérifié)

```bash
npm --prefix Plugin/owismind/frontend test          # = node --test test/*.test.js
```

Tests **purs** sous `frontend/test/` (hors `src/`, jamais buildé/zippé) : `timeline` (reducer
`applyEvent`), `prefs` (clamps de préférences), `conversationList`, `conversationTree` (arbre pur),
`agentPick`. Garder ces unités **sans Vue ni dataiku** pour qu'elles restent testables par le runner natif
(gotcha **F11**).

### 3.3 Ce qui a besoin de DSS (non couvert) + reco TEST-01

Certains modules importent `dataiku`/`pandas` au chargement → besoin du Python DSS (ou d'un stub) :
`sql_config.pg_identifier`, `serialization.rows_to_json_safe`, `settings.resolve_enabled_agent`,
`agents.stream_manager`, `security.identity.derive_display_name`.

**TEST-01 (recommandé, NON fait - prochaine étape)** : ajouter des tests DSS-free (stub `dataiku`/`pandas`)
pour ces invariants **déjà durcis mais non couverts** (rejet d'injection sur `pg_identifier`, NaN→None,
clé d'agent forgée → `None`, cap/TTL/poll-owner/`_stop_reason` du `stream_manager`, no-op/troncature de
`save_trace`), et brancher `py_compile`/`compileall` sur `python-lib/owismind/**` comme CI minimale. Il
n'y a **pas de CI** aujourd'hui. Détail → [`tests/README.md`](../Plugin/owismind/tests/README.md) (§ « To add » + « CI »)
et `PROJECT_STATE.md` §12.4.

---

## 4. Vue d'ensemble du pipeline de release

```
[edit frontend/src]──► /build-plugin ──► resource/owismind-app/ + body.html ──┐
                                                                              ├─► /package-plugin ──► owismind-upload.zip ──► upload MANUEL DSS
[edit python-lib / webapps]───────────────────────────────────────────────────┘
```

`/build-plugin` et `/package-plugin` sont **deux étapes distinctes** : builder ne package pas, packager
n'uploade pas, et **rien n'est jamais uploadé par l'agent** (§7).

---

## 5. Build - skill `/build-plugin`

Skill : [`.claude/skills/build-plugin/SKILL.md`](../.claude/skills/build-plugin/SKILL.md). Pipeline exact :

1. **Préflight - jamais d'install.** Vérifier `Plugin/owismind/frontend/node_modules`. Absent → **STOP** et
   demander à l'utilisateur d'installer (la commande d'install est de toute façon refusée par policy, §0).

2. **Build** depuis la racine du repo :
   ```bash
   npm --prefix Plugin/owismind/frontend run build
   ```
   Sortie attendue dans `Plugin/owismind/resource/owismind-app/` (assets **hashés** `assets/index-*.js` /
   `*.css`, `emptyOutDir: true` purge les anciens hashs).

3. **Câbler `body.html`** - recopier l'entrée buildée (ce `cp` Bash est autorisé ; `Edit`/`Write` sur la
   sortie est **bloqué** par le hook) :
   ```bash
   cp Plugin/owismind/resource/owismind-app/index.html \
      Plugin/owismind/webapps/webapp-owismind-ai-agents/body.html
   ```

4. **Vérifier** que la base d'assets est présente dans `body.html` :
   ```bash
   grep -q '/plugins/owismind/resource/owismind-app/' \
      Plugin/owismind/webapps/webapp-owismind-ai-agents/body.html \
      && echo "body.html OK" || echo "ERROR: asset base missing in body.html"
   ```

5. **Reporter** (en français) : ce qui a été buildé, les fichiers de sortie, l'état de `body.html`, et
   rappeler que le packaging (`/package-plugin`) est une étape séparée - rien n'est uploadé.

### Pourquoi recâbler `body.html` à CHAQUE build (gotcha F10)

L'entrée DSS de la webapp est `body.html` ; or l'`index.html` buildé référence un bundle **hashé**
(`index-<hash>.js/.css`) et **ce hash change à chaque build**. Si on ne recopie pas `index.html` →
`body.html`, DSS sert un `body.html` qui pointe vers un ancien hash → assets 404. Après recopie, le
`diff body.html ↔ index.html` doit être **identique**. (Note F10 : le `cp` peut être refusé par le hook
selon le contexte → écrire le fichier à la place ; le skill décrit le `cp` comme autorisé.)

---

## 6. Package - skill `/package-plugin`

Skill : [`.claude/skills/package-plugin/SKILL.md`](../.claude/skills/package-plugin/SKILL.md).
**Précondition** : frontend déjà buildé + `body.html` câblé (lancer `/build-plugin` en cas de doute).
**On ne stage que le runtime.**

1. **Reset staging** (`rm -rf` → peut demander une approbation, attendu) :
   ```bash
   rm -rf Plugin/ready-for-dataiku/owismind-upload Plugin/ready-for-dataiku/owismind-upload.zip
   mkdir -p Plugin/ready-for-dataiku/owismind-upload
   ```

2. **Stager le runtime uniquement** (`plugin.json` à la **racine** du staging - pas de `_/plugin.json`
   dans ce repo, cf. [LESSONS L002](../memory/LESSONS.md)) :
   ```bash
   cp Plugin/owismind/plugin.json Plugin/ready-for-dataiku/owismind-upload/
   cp -R Plugin/owismind/python-lib Plugin/owismind/resource Plugin/owismind/webapps \
         Plugin/ready-for-dataiku/owismind-upload/
   ```

3. **Zipper depuis le staging** (pour que `plugin.json` soit à la racine de l'archive), en excluant les
   docs dev et les caches Python - **par nom, jamais par glob large** :
   ```bash
   ( cd Plugin/ready-for-dataiku/owismind-upload && \
     zip -r ../owismind-upload.zip . \
       -x "*.DS_Store" "__MACOSX/*" \
          "*/CLAUDE.md" "CLAUDE.md" "*/README.md" "README.md" \
          "*/__pycache__/*" "__pycache__/*" "*.pyc" )
   ```

   > ⚠️ **Le piège `__init__.py` (L002).** Exclure `CLAUDE.md`/`README.md`/`__pycache__`/`*.pyc` **par
   > nom**, jamais via un `*.py`/`*.md` global - un tel glob raflerait les `python-lib/owismind/**/__init__.py`
   > et casserait `from owismind.api.routes import register_routes` au runtime. Ne jamais zipper depuis la
   > racine source (`zip -r ... .` aspirerait `frontend/` + `node_modules/`).

   **Inclus** : `plugin.json` (racine) + `python-lib/` + `resource/` + `webapps/`.
   **Exclus** : `frontend/`, `node_modules/`, tout `_/`, `.DS_Store`, `__MACOSX/`, `CLAUDE.md`/`README.md`,
   `__pycache__/`, `*.pyc`.

4. **Vérifier que l'archive est propre** (doit afficher « ZIP clean ») :
   ```bash
   unzip -Z1 Plugin/ready-for-dataiku/owismind-upload.zip \
     | grep -Eq '(^|/)(frontend|node_modules)(/|$)|(^|/)_/|(^|/)CLAUDE\.md$|(^|/)README\.md$|__pycache__|\.pyc$' \
     && echo "ERROR: zip polluted" || echo "ZIP clean"
   ```

5. **Vérifier les fichiers requis** (`plugin.json`, `webapp.json`, `body.html`, `backend.py`,
   `python-lib/owismind/__init__.py`) :
   ```bash
   for f in plugin.json \
            webapps/webapp-owismind-ai-agents/webapp.json \
            webapps/webapp-owismind-ai-agents/body.html \
            webapps/webapp-owismind-ai-agents/backend.py \
            python-lib/owismind/__init__.py; do
     unzip -Z1 Plugin/ready-for-dataiku/owismind-upload.zip | grep -qx "$f" \
       && echo "OK  $f" || echo "MISSING  $f"
   done
   ```

6. **Reporter** (en français) : chemin du zip, nombre de fichiers, verdict propre/pollué, check des
   fichiers requis. Rappeler que **l'upload DSS est manuel** (le skill n'uploade pas).

### Taille attendue

Le zip courant contient **64 entrées au total** (= **53 fichiers** + 11 dossiers + `plugin.json` à la
racine). C'est ce que la mémoire désigne par « ~64 fichiers ». Un écart franc (p. ex. réapparition de
`frontend/`/`node_modules/`, ou chute des `__init__.py`) signale un bug de packaging à corriger avant upload.

---

## 7. Déploiement DSS (manuel)

**L'agent n'uploade jamais.** L'upload du zip dans DSS est une **opération manuelle** de l'utilisateur.
Référence : [`cadrage/GUIDE_DATAIKU_DSS_PLUGIN_REFERENCE.md`](../cadrage/GUIDE_DATAIKU_DSS_PLUGIN_REFERENCE.md) §3.

- Un plugin **Development** du même id **ne peut pas** être mis à jour par upload ZIP
  (« you cannot update it »).
- Pour conserver le **même id** `owismind` (donc les chemins Vite déjà buildés dans `body.html`) :
  **supprimer** le plugin Development, puis **uploader le ZIP** avec **Origin = Uploaded**, puis
  créer/recharger la webapp.
- Après upload : **Start/Restart backend** de la webapp + **refresh forcé** du navigateur (cache d'assets).
- Sélectionner la **connexion SQL** (`SQL_owi`) dans les *Settings* de la webapp (et, optionnel, le préfixe
  de table, le dataset de trace, le niveau de log) - tant qu'aucune connexion n'est choisie, l'app reporte
  « storage not configured » (cf. [`webapp.json`](../Plugin/owismind/webapps/webapp-owismind-ai-agents/webapp.json)).

> Rappel d'identité runtime : la webapp s'exécute sous **Run backend as** (≠ utilisateur final) ;
> l'identité réelle de l'appelant vient des en-têtes navigateur. Détail → [security.md](security.md).

---

## 8. Matrice « quoi rebuilder quand »

| Changement | `/build-plugin` (build + body.html) | `/package-plugin` (zip) | Action DSS après upload |
|---|:--:|:--:|---|
| `frontend/src/**` (Vue, CSS, registres, i18n…) | **oui** | oui | upload + refresh |
| `frontend/public/**` | **oui** | oui | upload + refresh |
| `python-lib/owismind/**` ou `webapps/.../backend.py` | non | **oui** | upload + **Restart backend** |
| `webapps/.../webapp.json` / `app.js` / `style.css` seuls | non | **oui** | upload (+ Restart backend si `webapp.json` change le backend) |
| `vite.config.js` `base` ou `outDir` | **oui** + recâbler `body.html` | oui | upload + refresh |
| `plugin.json` (version/meta) | non | **oui** | upload |

Notes :
- **Slots STANDARD** `app.js` / `style.css` : vidés (commentaire) mais **jamais supprimés** - DSS les exige.
- Changer `vite.config.js` `base` impose impérativement build + recopie de `body.html` (assets 404 sinon).
- Référence : matrice rebuild de
  [`cadrage/GUIDE_DATAIKU_DSS_PLUGIN_REFERENCE.md`](../cadrage/GUIDE_DATAIKU_DSS_PLUGIN_REFERENCE.md) §3
  et `PROJECT_STATE.md` §5.

---

## 9. Tracké vs généré

Philosophie du [`.gitignore`](../.gitignore) racine : la **source** est versionnée ; les **inputs**
réinstallables et les **outputs** régénérables ne le sont pas - **avec une exception délibérée**.

| Chemin | Statut Git | Pourquoi |
|---|---|---|
| `Plugin/owismind/frontend/src/**`, `webapps/**`, `python-lib/**`, `plugin.json` | **tracké** | source du plugin |
| `Plugin/owismind/resource/owismind-app/**` (frontend buildé) | **tracké** (exception) | c'est le payload du plugin ; NO-INSTALL ⇒ un clone frais ne peut pas le rebuilder ⇒ il doit rester dans le repo pour rester packageable. **Ne jamais éditer à la main** (rebuild via `/build-plugin`). |
| `node_modules/`, `dist/`, `dist-ssr/`, `.vite/`, `*.local` | **ignoré** | toolchain réinstallable / scratch |
| `__pycache__/`, `*.py[cod]` | **ignoré** | bytecode Python |
| `Plugin/ready-for-dataiku/**` (le zip livrable) | **ignoré** | régénéré par `/package-plugin` |
| `*-screens/`, `/tmp_build/`, `.DS_Store`, logs | **ignoré** | scratch / bruit OS |
| `.claude/settings.local.json` | **ignoré** | override local (le `settings.json` + les skills restent trackés) |

---

## 10. Protocole mémoire / fin de session

Skill : [`.claude/skills/log-session/SKILL.md`](../.claude/skills/log-session/SKILL.md). À exécuter en
**fin de session** (`/log-session`) - il **n'écrit que des fichiers mémoire** (pas de build, pas de
package, pas d'upload). Il :

1. écrit/append le log de session dans `memory/sessions/<YYYY-MM-DD>.md` (Objectif / Fait / Décisions /
   Validé-non validé / Prochaines étapes) ;
2. rafraîchit [`memory/CONTEXT.md`](../memory/CONTEXT.md) (mémoire courte chargée à chaque session :
   Focus / Dernière session / gotchas / Prochaines étapes) ;
3. **appende** une leçon `L0xx` à [`memory/LESSONS.md`](../memory/LESSONS.md) dès qu'une solution diverge
   des guides ou qu'un truc échoue puis marche (Contexte / Échec / Solution / Preuve / Source / Date) ;
4. met à jour [`memory/PROJECT_STATE.md`](../memory/PROJECT_STATE.md) pour tout changement d'état durable.

> **La mémoire prime sur les guides de `cadrage/`** (ceux-ci sont des points de départ). Les noms réels et
> les solutions validées EN DSS vivent en mémoire. Au démarrage d'une session : lire `CONTEXT.md`, puis
> `LESSONS.md` et `PROJECT_STATE.md` pour le détail.
