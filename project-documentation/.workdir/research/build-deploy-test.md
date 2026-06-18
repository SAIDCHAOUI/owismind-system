# OWIsMind - Build, Package, Deploy, Code environments, Tests, Hooks

> Pack de connaissance code-grounded sur la chaine de release du plugin Dataiku DSS **OWIsMind**.
> Toutes les affirmations sont sourcees `fichier:ligne`. Identifiants, chemins, noms de tables et
> ids de config gardes VERBATIM. Redige en francais technique ; code en anglais d'origine.
>
> Sources principales : `docs/build-test-deploy.md`, les skills `/build-plugin` `/package-plugin`
> `/log-session`, `Plugin/owismind/plugin.json`, `Plugin/owismind/webapps/`, `.claude/settings.json`,
> `.claude/hooks/`, `.git/hooks/`, `Plugin/owismind/tests/`, `Plugin/owismind/frontend/test/`,
> `dataiku-agents/tests/`, `dataiku-agents/README.md`, `dataiku-agents/CLAUDE.md`.

---

## 1. Vue d'ensemble de l'architecture de release

OWIsMind est un plugin Dataiku DSS compose de trois couches independantes au niveau du build et du
deploiement :

1. **Frontend Vue 3 + Vite** (`Plugin/owismind/frontend/`) : builde en assets statiques hashes, servis
   par DSS. Sortie versionnee dans le repo (exception, voir section 9).
2. **Backend Flask modulaire** (`Plugin/owismind/python-lib/owismind/`) : parle a LLM Mesh et stocke
   tout en SQL direct (PostgreSQL via `SQLExecutor2`). Embarque dans le zip.
3. **Agents LangGraph** (`dataiku-agents/agents/`) : orchestrateur + sous-agent revenus, deployes
   separement comme **Code Agents** colles a la main dans DSS (env Python 3.11). **Hors du zip.**

Le pipeline de release a deux etapes distinctes (`docs/build-test-deploy.md:151-158`) :

```
[edit frontend/src]──► /build-plugin ──► resource/owismind-app/ + body.html ──┐
                                                                              ├─► /package-plugin ──► owismind-upload.zip ──► upload MANUEL DSS
[edit python-lib / webapps]───────────────────────────────────────────────────┘
```

Regle cardinale : **builder ne package pas, packager n'uploade pas, et l'agent n'uploade jamais**
(`docs/build-test-deploy.md:157-159`, `275`). Les Code Agents sont une troisieme voie : un changement
agent-seul ne touche pas le zip (`dataiku-agents/README.md:179-180`).

---

## 2. La politique NO-INSTALL (le pourquoi de tout)

C'est la regle structurante #1 du projet. **L'agent n'installe JAMAIS de dependance** : aucun
`npm install/ci/i/add/update`, `yarn`, `pnpm`, `pip/pip3 install`, `pipenv`, `poetry`, `conda`, `brew`,
ni `npx` d'install (`docs/build-test-deploy.md:19-23`). Seul l'utilisateur installe (safety first).

Ce garde-fou est applique a **trois niveaux** (defense en profondeur) :

- **Permissions du harness** : `.claude/settings.json:28-50` liste explicitement chaque commande
  d'install dans `permissions.deny` (lignes 29-47) et bloque l'ecriture directe dans le frontend
  builde via `Edit`/`Write` sur `Plugin/owismind/resource/owismind-app/**` (lignes 48-49).
- **Hook PreToolUse** : `.claude/hooks/guardrail.sh:21-23` intercepte tout `Bash` dont le champ
  `"command"` matche un install (regex large couvrant npm/yarn/pnpm/pip/pipenv/poetry/conda/brew/npx)
  et BLOQUE (exit 2, stderr renvoye au modele). Pure bash + grep sur le JSON brut, **aucune dependance
  jq/python** pour ne jamais casser une session (`guardrail.sh:4`).
- **Documentation** : la regle est rappelee au SessionStart (`session-start.sh:21`) et dans tous les
  skills.

**Consequence directe et non triviale** : le frontend builde (`resource/owismind-app/`) **est
versionne** dans le repo (`docs/build-test-deploy.md:33-35`, `.gitignore:1-8`). Logique : un clone frais
ne pouvant pas reinstaller la toolchain (NO-INSTALL), le payload du plugin doit voyager dans le repo
pour rester packageable. C'est l'unique exception a la philosophie "outputs regenerables = ignores".

---

## 3. Le build - skill `/build-plugin`

Skill : `.claude/skills/build-plugin/SKILL.md`. Pipeline exact (`SKILL.md:18-46`,
`docs/build-test-deploy.md:166-199`) :

**Etape 1 - Preflight, jamais d'install** (`SKILL.md:20-24`) :
```bash
test -d Plugin/owismind/frontend/node_modules && echo "node_modules OK" || echo "MISSING"
```
Si MISSING -> STOP et demander a l'utilisateur d'installer (la commande serait de toute facon refusee).

**Etape 2 - Build** depuis la racine repo (`SKILL.md:26-30`) :
```bash
npm --prefix Plugin/owismind/frontend run build
```
Le script `build` = `vite build` (`Plugin/owismind/frontend/package.json:9`). La config Vite
(`frontend/vite.config.js`) est **canonique** et ne se modifie jamais sans rebuild + recablage de
`body.html` :
- `base: '/plugins/owismind/resource/owismind-app/'` (`vite.config.js:7`) - prefixe d'URL des assets.
- `outDir: '../resource/owismind-app'` (`vite.config.js:11`) - relatif a `frontend/`, donc pointe sur
  `Plugin/owismind/resource/owismind-app`.
- `emptyOutDir: true` (`vite.config.js:12`) - **purge** le dossier avant d'ecrire, donc les anciens
  hashs disparaissent (mais aussi : un build sauvage ECRASE l'app deployee, voir gotcha section 11).
- `plugins: [vue()]` (`vite.config.js:5`).

Sortie : assets hashes dans `resource/owismind-app/assets/index-*.js` / `*.css` + un `index.html` +
`favicon.svg`. Etat reel observe : 24 fichiers sous `assets/`, `index.html` (917 octets),
`favicon.svg`.

**Etape 3 - Cabler `body.html`** (`SKILL.md:32-36`) :
```bash
cp Plugin/owismind/resource/owismind-app/index.html \
   Plugin/owismind/webapps/webapp-owismind-ai-agents/body.html
```
Ce `cp` Bash est autorise (`settings.json:23` `Bash(cp:*)`) ; l'`Edit`/`Write` sur la sortie est bloque
par le hook.

**Etape 4 - Verifier** la base d'assets dans `body.html` (`SKILL.md:38-43`) :
```bash
grep -q '/plugins/owismind/resource/owismind-app/' \
   Plugin/owismind/webapps/webapp-owismind-ai-agents/body.html \
   && echo "body.html OK" || echo "ERROR: asset base missing in body.html"
```

**Etape 5 - Reporter** en francais ; rappeler que `/package-plugin` est une etape separee.

### 3.1 Pourquoi recabler `body.html` a CHAQUE build (gotcha F10)

`body.html` est l'**entree DSS** de la webapp (baseType STANDARD). Or l'`index.html` builde reference
un bundle **hashe** (`index-<hash>.js/.css`) et **ce hash change a chaque build**
(`docs/build-test-deploy.md:193-199`). Sans recopie `index.html` -> `body.html`, DSS sert un `body.html`
qui pointe sur un ancien hash -> assets 404. Apres recopie, `diff body.html ↔ index.html` doit etre
identique. Etat reel observe dans `body.html` (`webapps/.../body.html:8-12`) : entree
`assets/index-DCY_crmu.js`, modulepreload `Icon-R0zNmMF0.js` et `session-lX0dumx_.js`, CSS
`Icon-xzaNi_GI.css` et `index-D7fJBFZD.css`.

> NOTE F10 : selon le contexte le `cp` peut etre refuse par le hook ; le fallback documente est d'ECRIRE
> le fichier `body.html` via l'outil `Write` (`docs/build-test-deploy.md:198-199`, gotcha memoire F10).
> Le skill decrit toutefois le `cp` comme la voie nominale autorisee.

---

## 4. Le packaging - skill `/package-plugin`

Skill : `.claude/skills/package-plugin/SKILL.md`. **Precondition** : frontend deja builde + `body.html`
cable (`SKILL.md:20-22`). **On ne stage que le runtime.** Le skill **n'uploade jamais**.

**Etape 1 - Reset staging** (`SKILL.md:26-30`) - le `rm -rf` peut demander approbation (attendu) :
```bash
rm -rf Plugin/ready-for-dataiku/owismind-upload Plugin/ready-for-dataiku/owismind-upload.zip
mkdir -p Plugin/ready-for-dataiku/owismind-upload
```

**Etape 2 - Stager le runtime uniquement** (`SKILL.md:32-37`) - `plugin.json` va a la RACINE du staging :
```bash
cp Plugin/owismind/plugin.json Plugin/ready-for-dataiku/owismind-upload/
cp -R Plugin/owismind/python-lib Plugin/owismind/resource Plugin/owismind/webapps \
      Plugin/ready-for-dataiku/owismind-upload/
```
Note importante (`SKILL.md:22`, LESSONS L002) : `plugin.json` vit a `Plugin/owismind/plugin.json` ; il
n'y a **pas** de `_/plugin.json` dans ce repo.

**Etape 3 - Zipper depuis le staging** pour que `plugin.json` soit a la racine de l'archive
(`SKILL.md:39-47`) :
```bash
( cd Plugin/ready-for-dataiku/owismind-upload && \
  zip -r ../owismind-upload.zip . \
    -x "*.DS_Store" "__MACOSX/*" \
       "*/CLAUDE.md" "CLAUDE.md" "*/README.md" "README.md" \
       "*/__pycache__/*" "__pycache__/*" "*.pyc" )
```

> **Le piege `__init__.py` (LESSONS L002)** (`SKILL.md:16-18`, `package-plugin SKILL` etape 3) : exclure
> `CLAUDE.md`/`README.md`/`__pycache__`/`*.pyc` **par nom uniquement, jamais via un glob `*.py`/`*.md`
> large**. Un tel glob raflerait les `python-lib/owismind/**/__init__.py` et casserait au runtime
> `from owismind.api.routes import register_routes` (l'import du blueprint dans `backend.py:8`). Ne jamais
> zipper depuis la racine source (un `zip -r ... .` aspirerait `frontend/` + `node_modules/`).

**Etape 4 - Verifier que l'archive est propre** (`SKILL.md:49-54`) - doit afficher "ZIP clean" :
```bash
unzip -Z1 Plugin/ready-for-dataiku/owismind-upload.zip \
  | grep -Eq '(^|/)(frontend|node_modules)(/|$)|(^|/)_/|(^|/)CLAUDE\.md$|(^|/)README\.md$|__pycache__|\.pyc$' \
  && echo "ERROR: zip polluted" || echo "ZIP clean"
```

**Etape 5 - Verifier les fichiers requis** (`SKILL.md:56-65`) : `plugin.json`,
`webapps/webapp-owismind-ai-agents/webapp.json`, `body.html`, `backend.py`,
`python-lib/owismind/__init__.py`.

### 4.1 Etat reel de l'archive courante (verifie ce pack)

- Total : **77 entrees** (12 dossiers + 65 fichiers, dont `plugin.json` a la racine). La taille du zip
  reel = ~417 Ko. NOTE : `docs/build-test-deploy.md:267-269` documente "64 entrees" - **doc perimee** ;
  la memoire `CONTEXT.md` confirme la valeur courante de **77 entrees** (Runs 6/7).
- Top niveau verifie : `plugin.json`, `python-lib/`, `resource/`, `webapps/`. **Aucune pollution**
  (grep frontend/node_modules/CLAUDE/README/pycache/pyc = 0 hit).
- `__init__.py` preserves : **6** dans le zip (le glob par-nom a bien protege les `__init__.py`).
- L'archive inclut aussi `resource/compute_available_connections.py` (le `paramsPythonSetup` de la
  webapp, voir section 6.3), pas seulement `resource/owismind-app/`.

Le contenu canonique du zip est donc : `plugin.json` (racine) + `python-lib/` + `resource/` +
`webapps/`. **Exclus** : `frontend/`, `node_modules/`, tout `_/`, `.DS_Store`, `__MACOSX/`,
`CLAUDE.md`/`README.md`, `__pycache__/`, `*.pyc` (`SKILL.md:15-18`, `docs/build-test-deploy.md:238-240`).

---

## 5. La matrice "quoi rebuilder quand"

`docs/build-test-deploy.md:295-309` (source de verite operationnelle) :

| Changement | `/build-plugin` | `/package-plugin` | Action DSS apres upload |
|---|:--:|:--:|---|
| `frontend/src/**` (Vue, CSS, registres, i18n) | **oui** | oui | upload + refresh navigateur |
| `frontend/public/**` | **oui** | oui | upload + refresh |
| `python-lib/owismind/**` ou `webapps/.../backend.py` | non | **oui** | upload + **Restart backend** |
| `webapps/.../webapp.json` / `app.js` / `style.css` seuls | non | **oui** | upload (+ Restart si `webapp.json` change le backend) |
| `vite.config.js` `base` ou `outDir` | **oui** + recabler `body.html` | oui | upload + refresh |
| `plugin.json` (version/meta) | non | **oui** | upload |

Notes critiques (`docs/build-test-deploy.md:304-306`) :
- Les slots STANDARD `app.js` / `style.css` sont **vides mais jamais supprimes** - DSS les exige.
  Etat reel : `app.js` = commentaire seul ("Vue/Vite application is loaded from body.html") ; `style.css`
  = commentaire seul ("DSS STANDARD-webapp CSS slot - intentionally empty"). Tout le styling part dans le
  bundle Vite scope sur App.vue.
- Changer `vite.config.js` `base` impose imperativement build + recopie de `body.html` (assets 404 sinon).

**Regle pratique a retenir** : un changement **frontend-seul** = build + package + upload + refresh (pas
de restart backend). Un changement **python-lib/backend** = package + upload + **restart backend
obligatoire**. Un changement **agent-seul** = recoller les Code Agents, **aucun zip** (section 8).

---

## 6. Le composant webapp DSS

### 6.1 `webapp.json` (descripteur de la webapp)

`Plugin/owismind/webapps/webapp-owismind-ai-agents/webapp.json` :
- `"baseType": "STANDARD"` avec un commentaire `WARNING: do not change` (ligne 12).
- `"hasBackend": "true"` (ligne 13) - active le `backend.py`.
- `"noJSSecurity": "false"` (ligne 14), `"standardWebAppLibraries": ["jquery","dataiku"]` (ligne 15).
- `"paramsPythonSetup": "compute_available_connections.py"` (ligne 26) - script Python lance pour
  remplir dynamiquement les dropdowns des Settings.
- 4 params (lignes 28-64) : `sql_connection` (SELECT dynamique, non mandatory), `table_prefix` (STRING,
  prefixe optionnel, max 16 chars), `traces_dataset` (SELECT dynamique, dataset de trace optionnel),
  `log_level` (SELECT DEBUG/INFO/WARNING, defaut INFO).

> Gotcha memoire (CONTEXT.md, gotcha backend #9) : un param **MULTISELECT ne se rend pas** dans les
> Settings DSS - a ne pas utiliser.

### 6.2 `backend.py` (bootstrap mince)

`Plugin/owismind/webapps/webapp-owismind-ai-agents/backend.py` (12 lignes, toute la logique est dans
`python-lib/`) :
```python
from dataiku.customwebapp import *   # fournit l'objet Flask `app`
from owismind.api.routes import register_routes
register_routes(app)
```
DSS injecte l'objet Flask `app` via le star-import `customwebapp` (`backend.py:6`) ; le fichier ne fait
que brancher le blueprint API OWIsMind. **C'est cet import `from owismind.api.routes`** qui exige que
les `__init__.py` survivent au packaging (section 4, piege L002).

### 6.3 `compute_available_connections.py` (paramsPythonSetup)

`Plugin/owismind/resource/compute_available_connections.py` : DSS appelle `do()` pour peupler les
dropdowns des Settings, en routant chaque param via `payload['parameterName']`. `sql_connection` derive
de `client.list_connections()` (PostgreSQL only) ; `traces_dataset` des datasets SQL du projet + une
entree explicite `(none)`. Module **strictement READ-ONLY** : il ne fait que LISTER, jamais creer/modifier
/supprimer, et ne tourne que pendant le rendu du formulaire Settings. Si `list_connections()` est
admin-restreint ou indisponible, il affiche un fallback CLAIREMENT LABELLISE plutot qu'un faux silencieux
(`compute_available_connections.py:11-18`). Ce fichier vit sous `resource/` donc **part dans le zip**.

---

## 7. Deploiement DSS (manuel)

`docs/build-test-deploy.md:273-289`. **L'agent n'uploade jamais** ; l'upload est une operation manuelle
de l'utilisateur. Procedure (reference `docs/cadrage/GUIDE_DATAIKU_DSS_PLUGIN_REFERENCE.md` §3) :

- Un plugin **Development** du meme id ne peut PAS etre mis a jour par upload ZIP ("you cannot update
  it"). Pour garder le **meme id** `owismind` (et donc les chemins Vite deja cables dans `body.html`) :
  **supprimer** le plugin Development, puis **uploader le ZIP** avec **Origin = Uploaded**, puis
  creer/recharger la webapp (`docs/build-test-deploy.md:278-282`).
- Apres upload : **Start/Restart backend** de la webapp + **refresh force** du navigateur (cache
  d'assets) (`docs/build-test-deploy.md:283`).
- Selectionner la **connexion SQL** (`SQL_owi`) dans les Settings de la webapp (+ optionnel : prefixe de
  table, dataset de trace, log level). Tant qu'aucune connexion n'est choisie, l'app reporte "storage not
  configured" (`docs/build-test-deploy.md:284-286`).
- Identite runtime : la webapp s'execute sous **Run backend as** (≠ utilisateur final) ; l'identite reelle
  de l'appelant vient des en-tetes navigateur (`docs/build-test-deploy.md:288-289`).

Identifiants canoniques (`docs/build-test-deploy.md:43-57`) : plugin id `owismind`, webapp
`webapp-owismind-ai-agents`, package python-lib `owismind`, dossier resource `owismind-app`, prefixe API
`/owismind-api` (sante `/owismind-api/ping`), connexion `SQL_owi` (PostgreSQL, schema `public`), project
key `OWISMIND_DEV` (resolu serveur via `dataiku.default_project_key()`), plateforme DSS 14.4.x, **backend
Python 3.9.23** (3.11/FastAPI NON valides). `plugin.json:3` confirme `"id": "owismind"`, `:6`
`"version": "0.0.1"`.

---

## 8. Les Code Agents - deploiement separe (le double chemin Python 3.9/3.11)

Les agents LangGraph vivent dans `dataiku-agents/agents/` (le repo = source de verite) et sont **colles a
la main** dans les Code Agents DSS, sur le **code env Python 3.11** (`dataiku-agents/README.md:73-78`,
`CLAUDE.md:19-20`). Ils ne passent **jamais par le zip**.

### 8.1 Pourquoi deux environnements Python (rationale)

- **Backend Flask = Python 3.9.23** : c'est l'env observe en DSS (`/ping`), **sans langchain**
  (`docs/build-test-deploy.md:57`, regle #8 CLAUDE.md). Il ne fait que du Flask + SQL direct.
- **Agents = Python 3.11** : LangGraph/LangChain v1 exigent >= 3.10 (`README.md:74-75`,
  `MEMORY.md` "Dataiku Python 3.9 & 3.11 dual-path"). Les Code Agents tournent sur un code env 3.11 ou
  langchain/langgraph sont installes.

C'est le "double chemin" : on ne peut pas mettre langgraph dans le backend 3.9 ; les agents doivent donc
vivre dans un env 3.11 distinct, d'ou leur deploiement par coller-coller plutot que par le zip. Les
agents sont des **fichiers standalone** : ils importent uniquement stdlib + `dataiku` + `langgraph`,
**aucun import du plugin** (`CLAUDE.md:52`, `README.md:73`).

### 8.2 Procedure de deploiement des agents

`dataiku-agents/README.md:162-184`, `CLAUDE.md:62-67` :
1. Editer le(s) fichier(s) ici, lancer les tests (`python3 -m unittest discover -s dataiku-agents/tests`).
2. **Recoller LES DEUX Code Agents** quand l'un change (l'orchestrateur resout le sous-agent par id ;
   certains fixes vivent des deux cotes) : `agents/OWIsMind_orchestrator.py` -> Code Agent
   **OWIsMind_orchestrator** ; `agents/SalesDrive_revenue_expert.py` -> Code Agent
   **SalesDrive_revenue_expert** ; sur l'env **Python 3.11**.
3. **Verifier les ids de config** contre l'instance (voir 8.3).
4. Optionnel : renseigner `source_url` sur la capability `revenue_expert` (registre orchestrateur) =
   l'URL du dataset Dataiku -> Evidence rend la source cliquable.
5. Si **python-lib a change aussi** -> rebuild + upload zip + **restart backend**. Un changement
   **agent-seul ne necessite AUCUN upload zip** (la webapp resout l'orchestrateur par id via la
   whitelist) (`README.md:178-180`).

Les recettes Flow se deploient comme recettes Python dans le Flow ; un scenario de refresh garde le
profil + l'index frais, sans recoller (`README.md:182-184`).

### 8.3 Ids de config a verifier (VERBATIM, observes dans le code)

Orchestrateur `dataiku-agents/agents/OWIsMind_orchestrator.py` :
- `GEMINI_FLASH_LITE_ID = "openai:LLM-7064-revforecast:vertex_ai/gemini-3.1-flash-lite"` (ligne 91, eco)
- `GEMINI_FLASH_ID = "openai:LLM-7064-revforecast:vertex_ai/gemini-3.5-flash"` (ligne 92, medium)
- `SONNET_ID = "openai:LLM-7064-revforecast:vertex_ai/claude-sonnet-4-6"` (ligne 93, high)
- `LOOP_LLM_BY_MODE` mappe eco/medium/high vers ces ids (lignes 112-114)
- `"agent_id": "agent:bHrWLyOL"` = SalesDrive_revenue_expert (ligne 170, resolution par id)

Sous-agent `dataiku-agents/agents/SalesDrive_revenue_expert.py` :
- memes trois ids modeles (lignes 91-93), `LLM_BY_MODE = {"eco": ..., "medium": ..., "high": SONNET_ID}`
  (ligne 98)
- `SEMANTIC_TOOL_ID = "v4oqA6R"` = Semantic Model Query tool (ligne 127), avec
  `SEMANTIC_TOOL_ID_BY_MODE` constant sur les 3 modes (lignes 133-134)
- `SUBAGENT_LLM_HEADLINE = False` (ligne 113, perf : coupe un appel LLM de headline)
- `SUBAGENT_MAX_PARALLEL = 4` (ligne 153, fan-out borne)

> A JOUR (verifie ce pack) : `CONTEXT.md` mentionnait un fix `flash-light` -> `flash-lite` ; le code
> reel affiche bien `gemini-3.1-flash-lite`. Les ids ont aussi migre vers `gemini-3.1` / `gemini-3.5` /
> `claude-sonnet-4-6` (Run 6). **A reverifier sur l'instance** : ces ids doivent matcher un id expose par
> la connexion LLM Mesh ; sinon le mode concerne ne repond pas.

> EN FLUX (lu ce pack, dossier `dataiku-agents/` edite en LIVE) : le tool managed `dataset_lookup`
> (`9FEzVZk`) et son intent `lookup` ont ete **RETIRES le 2026-06-18** (`CLAUDE.md:26`, `README.md:108`).
> Son remplacant `attribute_lookup` (Custom Python, `tools/attribute_lookup_tool.py`) est construit +
> teste mais **pas encore branche** (`CLAUDE.md:26`, `README.md:107`, `204-212`). Le `CONTEXT.md` charge
> en contexte (date 2026-06-17) est donc en retard d'un jour sur cet etat.

---

## 9. Tracke vs genere (`.gitignore`)

`.gitignore:1-8` + `docs/build-test-deploy.md:315-326`. Philosophie : la **source** est versionnee ; les
**inputs reinstallables** et **outputs regenerables** ne le sont pas, **avec une exception deliberee**.

| Chemin | Statut Git | Pourquoi |
|---|---|---|
| `frontend/src/**`, `webapps/**`, `python-lib/**`, `plugin.json` | **tracke** | source du plugin |
| `resource/owismind-app/**` (frontend builde) | **tracke (exception)** | payload du plugin ; NO-INSTALL => un clone frais ne peut pas le rebuilder => doit rester dans le repo (`.gitignore:1-8`). Ne JAMAIS editer a la main. |
| `node_modules/`, `dist/`, `dist-ssr/`, `.vite/`, `*.local` | **ignore** | toolchain reinstallable / scratch (`.gitignore:10-14`) |
| `__pycache__/`, `*.py[cod]`, `*$py.class` | **ignore** | bytecode Python (`.gitignore:16-18`) |
| `Plugin/ready-for-dataiku/**` (le zip livrable) | **ignore** | regenere par `/package-plugin` (`.gitignore:20-21`) |
| `*-screens/`, `/tmp_build/`, `.DS_Store`, logs | **ignore** | scratch / bruit OS (`.gitignore:23-40`) |
| `.claude/settings.local.json` | **ignore** | override local (le `settings.json` + skills restent trackes) (`.gitignore:43`) |
| `graphify-out/` | **ignore** | graphe regenere par `/graphify` (`.gitignore:46`) |
| `docs/agentic-research/` | **ignore** | corpus de recherche, garde sur disque (`.gitignore:49`) |

---

## 10. Les suites de tests

Les suites sont **pure-logic, sans environnement DSS et sans install** (runners natifs)
(`docs/build-test-deploy.md:104-106`). Elles verrouillent les invariants testables hors instance, **ne
remplacent pas la validation EN DSS**.

### 10.1 Backend - `unittest`

```bash
python3 -m unittest discover -s Plugin/owismind/tests -v
```
(`docs/build-test-deploy.md:110-112`, `tests/README.md:8-11`). Le dossier `Plugin/owismind/tests/` est
**hors `python-lib/`**, donc **jamais package** (`tests/README.md:3-5`). Les tests mettent `python-lib/`
sur `sys.path` pour resoudre `owismind.*`.

Couverture reelle : **385 fonctions `test_`** dans 21 fichiers (compte verifie ce pack ; la doc
`build-test-deploy.md:108` dit "65 tests", **perimee** ; CONTEXT.md confirme ~385). Modules couverts
(`tests/README.md:16-48`) : `validation` (`/chat/start` shape+bornes), `validate_history_limit`
[10,50]/defaut 20, `validate_optional_exchange_id`, `validate_conversations_limit` [1,60]/defaut 30,
`validate_feedback` (rating {0,1,None}), les SQL builders purs (`build_conversation_list_query`,
`build_session_messages_query`, `build_ancestor_chain_query` - user-scopes + bornes), `pagination`
(cursor round-trip), `agents.context` (assemblage multi-tours), `security.identity.derive_full_name`
(stub `dataiku` minimal), plus toute la suite Evidence (`evidence.sql_parse`, `query_builders`,
`whitelist`, `validation`, `throttle`, `capture`, `service_proof`, `sql_explain`), `artifacts`,
`chart_payload`, `usage_accounting`.

### 10.2 Frontend - `node:test`

```bash
npm --prefix Plugin/owismind/frontend test     # = node --test test/*.test.js
```
(`docs/build-test-deploy.md:124-126`, `frontend/package.json:10`). Tests **purs** sous `frontend/test/`
(hors `src/`, jamais builde/zippe). Couverture reelle : **~117 tests** dans 8 fichiers (compte verifie ;
CONTEXT.md dit "116 frontend") : `timeline.test.js` (reducer `applyEvent`), `prefs.test.js` (clamps de
preferences), `conversationList.test.js`, `conversationTree.test.js` (arbre pur), `agentPick.test.js`,
`evidenceModel.test.js` (chips/payload/modified), `evidenceProof.test.js`, `sqlPretty.test.js`. Ces
unites restent **sans Vue ni dataiku** pour etre testables par le runner natif (gotcha F11).

### 10.3 Agents - `unittest`

```bash
python3 -m unittest discover -s dataiku-agents/tests
```
(`dataiku-agents/README.md:166`, `249-251`, `CLAUDE.md:38`). DSS-free. Couverture reelle : **242
fonctions `test_`** dans 4 fichiers : `test_profiler.py`, `test_dataset_expert.py` (50 Ko),
`test_langgraph_agents.py` (40 Ko, contient le test anti-drift registre <-> sous-agent), et le nouveau
`test_attribute_lookup.py` (14 Ko, 2026-06-18, pour le tool `attribute_lookup` en cours de wiring).
CONTEXT.md mentionnait "227 tests" (Run 7c) ; le compte est passe a 242 (suite attribute_lookup ajoutee).

### 10.4 Ce qui a besoin de DSS (non couvert) + reco TEST-01

Certains modules importent `dataiku`/`pandas` au chargement -> besoin du Python DSS ou d'un stub
(`docs/build-test-deploy.md:134-145`, `tests/README.md:55-67`) : `sql_config.pg_identifier` (rejet
d'injection), `serialization.rows_to_json_safe` (NaN/NaT -> None), `settings.resolve_enabled_agent` (cle
forgee -> None), `agents.stream_manager` (machine d'etat des runs : cursor, TTL, cap concurrence,
`_stop_reason`), `security.identity.derive_display_name`. **TEST-01 (recommande, NON fait)** : tests
DSS-free a stub + brancher `py_compile`/`compileall` sur `python-lib/owismind/**` comme CI minimale.
**Il n'y a PAS de CI aujourd'hui** (`docs/build-test-deploy.md:144`, `tests/README.md:69-71`). Pipeline
minimal recommande : lint + `python3 -m py_compile` sur `python-lib/owismind/**` + `unittest` + `vite
build` (compile check).

### 10.5 Compile-check jetable (build sans toucher l'app)

`docs/build-test-deploy.md:88-98` :
```bash
./node_modules/.bin/vite build --outDir /tmp/owi_buildcheck --emptyOutDir
rm -rf /tmp/owi_buildcheck
```
**Ne JAMAIS builder dans `resource/` hors du skill `/build-plugin`** : `outDir` y pointe avec
`emptyOutDir: true`, donc un build sauvage ECRASE l'app deployee (`docs/build-test-deploy.md:96-98`).

---

## 11. Les hooks

### 11.1 Hooks Claude Code (`.claude/hooks/`, cables dans `.claude/settings.json:52-75`)

- **`guardrail.sh`** (PreToolUse, matcher `Bash|Edit|Write|MultiEdit|NotebookEdit`,
  `settings.json:54-62`) : filet de securite deterministe, pur bash + grep sur le JSON brut du payload
  (aucune dependance jq/python pour ne jamais casser une session, `guardrail.sh:4`). Trois regles :
  - **Regle 1** (`guardrail.sh:21-23`) : BLOQUE (exit 2) tout `"command"` Bash matchant un install
    (npm/yarn/pnpm/pip/pipenv/poetry/conda/brew/npx). Message renvoye au modele.
  - **Regle 2** (`guardrail.sh:26-28`) : BLOQUE tout `"file_path"` sous `resource/owismind-app` ou
    `ready-for-dataiku` (outputs generes, jamais edites a la main).
  - **Regle 3** (`guardrail.sh:31-33`, non-bloquante) : RAPPEL de securite instance Dataiku quand on
    touche `python-lib` ou `backend.py` (SQL direct, PROJECT_KEY, COMMIT, parametrise, whitelist agents).
- **`session-start.sh`** (SessionStart, matcher `*`, `settings.json:64-74`) : injecte dans le contexte
  de session un rappel de lire la memoire (`CONTEXT.md`, `LESSONS.md`, `PROJECT_STATE.md`), le graphe de
  connaissance, et les regles non-negociables (NO INSTALL, safety instance, SQL direct, ne pas editer les
  outputs generes, frontend jamais dans le zip, noms canoniques, finir par `/log-session`)
  (`session-start.sh:6-30`).

### 11.2 Hooks git (`.git/hooks/`, installes par `graphify hook install`)

- **`post-commit`** : reconstruit le graphe de connaissance (code only, AST, sans LLM) en tache de fond
  apres chaque commit (`post-commit:3-4`). Skippe pendant rebase/merge/cherry-pick (`post-commit:6-11`).
  Lance `graphify.watch._rebuild_code` en `nohup ... &` detache pour que le commit rende la main
  immediatement (`post-commit:51-77`) - un rebuild complet peut prendre des heures. Detecte
  l'interpreteur Python correct via le shebang du binaire graphify, avec une allowlist de caracteres
  anti-injection (`post-commit:30-33`). Si graphify est introuvable -> `exit 0` (no-op silencieux).
- **`post-checkout`** : meme reconstruction code-only au changement de **branche** uniquement
  (`post-checkout:11-12`, `$BRANCH_SWITCH != 1` -> exit), et seulement si `graphify-out/` existe deja
  (`post-checkout:16-18`).

> NO-INSTALL s'applique aussi a graphify : ne jamais `pip install graphify`, demander a l'utilisateur
> (`log-session SKILL.md:42`).

---

## 12. Protocole de fin de session - skill `/log-session`

Skill : `.claude/skills/log-session/SKILL.md`. A executer en fin de session ; il **n'ecrit que des
fichiers memoire** (pas de build, pas de package, pas d'upload, pas de push). Etapes
(`log-session SKILL.md:11-50`) :
1. Determiner la date (`YYYY-MM-DD`).
2. Ecrire/append le log dans `memory/sessions/<YYYY-MM-DD>.md` (Objectif / Fait / Decisions / Valide-non
   valide / Prochaines etapes).
3. Rafraichir `memory/CONTEXT.md` (memoire courte, court).
4. Appender une lecon `L0xx` a `memory/LESSONS.md` des qu'une solution diverge des guides ou echoue puis
   marche (Contexte / Echec / Solution / Preuve / Source / Date).
5. Mettre a jour `memory/PROJECT_STATE.md` pour tout changement d'etat durable.
6. `/graphify --update` incremental (code -> AST-only gratuit ; docs/memoire -> re-extraction semantique
   des fichiers changes seulement).
7. **Commit de session** (autorisation user permanente 2026-06-11) : `git add -A` puis commit
   `session <YYYY-MM-DD>: <resume>` + trailer Co-Authored-By. Le post-commit hook rafraichit le graphe.
   **JAMAIS de push** (l'user pushe) (`log-session SKILL.md:44-47`).

> La memoire prime sur les guides `docs/cadrage/` (`docs/build-test-deploy.md:344-346`). En cas de
> conflit guides <-> memoire, la memoire fait foi.

---

## 13. Connexions au reste du systeme

- **Frontend -> backend** : tous les appels passent par `getWebAppBackendUrl('/owismind-api/...')`
  (jamais d'URL hardcodee, `frontend/CLAUDE.md`). Le backend Flask est branche par `backend.py:8`
  (`register_routes(app)`).
- **Backend -> storage** : SQL direct PostgreSQL (`SQLExecutor2`), tables prefixees `OWISMIND_DEV_...`,
  COMMIT apres ecriture, requetes parametrees. Le `python-lib/owismind/` a 6 sous-packages : `agents`,
  `api`, `evidence`, `security`, `storage` (+ racine). Changement ici = restart backend obligatoire.
- **Backend -> agents** : whitelist serveur (le front envoie une cle logique, le backend resout
  l'`agent_id`, jamais d'`agent_id` brut depuis le front). L'orchestrateur tourne en Code Agent 3.11,
  resolu par id `agent:bHrWLyOL` pour le sous-agent.
- **Agents -> Flow** : les recettes design-time (`dataiku-agents/recipes/`) construisent
  `DRIVE_Revenues_profile` + `DRIVE_Revenues_value_index` ; rafraichies par scenario, pas par recoller.

---

## 14. Gotchas a retenir (synthese)

1. **`body.html` doit etre recopie a CHAQUE build** (hash change), sinon assets 404 (F10).
2. **Ne JAMAIS builder dans `resource/` hors `/build-plugin`** (`emptyOutDir: true` ecrase l'app).
3. **Exclure du zip par NOM, jamais par glob `*.py`/`*.md`** (sinon les `__init__.py` sautent et l'import
   `owismind.api.routes` casse - L002).
4. **Plugin Development non updatable par ZIP** : supprimer puis re-uploader en Origin=Uploaded.
5. **Restart backend obligatoire** quand `python-lib`/`backend.py` change ; pas pour un changement
   frontend-seul.
6. **Recoller LES DEUX Code Agents** ensemble (certains fixes vivent des 2 cotes), env 3.11.
7. **Verifier les ids LLM Mesh** (`GEMINI_*_ID`, `SONNET_ID`, `v4oqA6R`, `agent:bHrWLyOL`) apres chaque
   recoller ; un id faux = le mode ne repond pas.
8. **Pas de CI** aujourd'hui ; les suites pure-logic ne couvrent pas les modules qui importent
   `dataiku`/`pandas`.
9. **NO INSTALL absolu** : applique par settings.json (deny) + guardrail.sh (hook) + doc.
10. **Doc `docs/build-test-deploy.md` partiellement perimee sur les COMPTES** (64 entrees zip / 65 tests
    backend / 27 tests frontend) - la memoire et le code reel donnent 77 entrees / 385 backend / ~117
    frontend / 242 agents. La doc reste fiable sur le POURQUOI et la procedure.
