# OWIsMind - Frontend : structure, bootstrap, routing, i18n, theming, pipeline de build

> Pack de connaissances code-sourcé pour la zone "Frontend app structure, bootstrap, routing, i18n,
> theming, build pipeline". Prose en français, identifiants (composants, stores, fichiers, tokens,
> clés i18n, ids de config) conservés VERBATIM en anglais. Tous les chemins sont absolus depuis la
> racine repo `/Users/saidchaoui/projects/owismind/`. Chaque affirmation est ancrée sur `fichier:ligne`.

---

## 1. Vue d'ensemble et stack exacte

Le frontend est une SPA **Vue 3 + Vite** sous `Plugin/owismind/frontend/`, buildée en assets statiques
servis par Dataiku DSS. Le `package.json` (`Plugin/owismind/frontend/package.json:12-24`) fige les versions :

| Dépendance | Version déclarée | Rôle |
|---|---|---|
| `vue` | `^3.5.34` | Framework (Composition API, `<script setup>`) |
| `pinia` | `^3.0.4` | State management (setup stores) |
| `vue-router` | `^5.1.0` | Routing en mode HASH |
| `vue-i18n` | `^11.4.4` | i18n FR/EN (`legacy:false`) |
| `chart.js` | `^4.5.1` | Graphiques interactifs Evidence (artefacts) |
| `markdown-it` | `^14.2.0` | Rendu markdown des réponses agent |
| `dompurify` | `^3.4.8` | Sanitisation du HTML markdown (seul chemin `v-html`) |
| devDeps | `@vitejs/plugin-vue ^6.0.6`, `vite ^8.0.12` | Plugin Vue + bundler |

`"type": "module"` (`package.json:5`). Scripts (`package.json:6-11`) : `dev` = `vite`, `build` =
`vite build`, `preview` = `vite preview`, `test` = `node --test test/*.test.js`. Note importante :
**aucun framework de test n'est installé** (pas de Vitest) ; les tests purs utilisent le runner natif
`node:test`. Règle repo non négociable : **NO INSTALL** (l'agent n'installe jamais ; `frontend/CLAUDE.md:13-14`).

L'arborescence `src/` (`Plugin/owismind/frontend/src/`) regroupe : `main.js`, `App.vue`, et les dossiers
`services/`, `router/`, `i18n/`, `styles/`, `stores/`, `composables/`, `registries/`, `components/`,
`views/`, `assets/`. Les tests vivent HORS de `src/` sous `Plugin/owismind/frontend/test/` (jamais
buildés/zippés ; `docs/frontend.md:102-105`).

---

## 2. Bootstrap et mount (`main.js`)

Fichier : `Plugin/owismind/frontend/src/main.js` (33 lignes). Séquence exacte :

1. Import des styles globaux **dans l'ordre** (`main.js:5-6`) : `./styles/tokens.css` PUIS `./styles/base.css`.
   L'ordre est load-bearing : `base.css` consomme les tokens définis dans `tokens.css` (couleurs, spacing,
   keyframes ; cf. §6).
2. **Thème posé sur `<body data-theme>` AVANT mount** (`main.js:14-21`) : lecture de
   `localStorage.getItem('owismind.theme')`, validée à `'dark'` ou `'light'`, défaut `'light'` ; en
   cas d'exception (localStorage indisponible) repli `'light'`. C'est l'invariant **F4** : les tokens
   sémantiques (`--bg`, `--surface`, `--text`...) n'existent QUE sous `body[data-theme="..."]`
   (`tokens.css:89/112`), donc une valeur doit être présente sur `<body>` avant le premier rendu, sinon
   flash de tokens non résolus. Le store `ui` réconcilie ensuite, de façon idempotente (`ui.js:107-108`).
3. Création de l'app : `createApp(App).use(pinia).use(i18n).use(router)` (`main.js:23-24`), avec
   `pinia = createPinia()`.
4. **Hook DEV-only** : `if (import.meta.env.DEV) { window.__pinia = pinia }` (`main.js:28-30`) - expose
   le store pour seeder une démo sans backend ; tree-shaké hors prod.
5. `app.mount('#app')` (`main.js:32`). La cible `#app` est dans `index.html:10`.

`App.vue` (`Plugin/owismind/frontend/src/App.vue`) est un shell mince : il rend `<AppLayout/>` +
`<ToastHost/>` (`App.vue:18-21`) et, au `onMounted`, appelle `session.ensureLoaded()` (`App.vue:13-15`)
pour résoudre l'identité une fois (best-effort : le shell s'affiche même hors DSS, backend absent).

### `index.html` source vs index.html buildé

`Plugin/owismind/frontend/index.html` (source, 13 lignes) déclare `<html lang="fr">`, le favicon
`/favicon.svg`, le conteneur `<div id="app">` et `<script type="module" src="/src/main.js">`. Après
build, Vite réécrit ce fichier (voir §5) : le favicon et les assets passent sous le préfixe `base`, et le
`<script src="/src/main.js">` est remplacé par les bundles hashés.

---

## 3. Router HASH (`router/index.js`)

Fichier : `Plugin/owismind/frontend/src/router/index.js` (66 lignes). Le routeur utilise
**`createWebHashHistory()`** (`router/index.js:55`). RATIONALE explicite en tête de fichier
(`router/index.js:3-5`) et **F3** : la webapp DSS est servie à une URL fixe **sans réécriture SPA
côté serveur**, donc un historique par path donnerait un 404 au reload / deep-link. Le hash garde tout
client-side et reload-safe.

Table des routes (`router/index.js:36-52`) :

| `name` | path | view (lazy) | meta |
|---|---|---|---|
| (redirect) | `/` -> `/chat` | - | - |
| `chat` | `/chat/:sessionId?` | `ChatView` | - |
| `settings` | `/settings` | `SettingsView` | `{ eyebrow:'set.eyebrow', title:'set.title' }` |
| `feedback` | `/feedback` | `FeedbackView` | `{ eyebrow:'fb.eyebrow', title:'fb.title' }` |
| `faq` | `/faq` | `FaqView` | `{ eyebrow:'faq.eyebrow', title:'faq.title' }` |
| `agents` | `/agents/:agentId?` | `AgentsView` | `{ eyebrow:'ag.eyebrow', title:'ag.title' }` |
| `project` | `/project/:projectId` | `ProjectView` | `{ eyebrow:'pj.eyebrow', title:'sb.projects' }` |
| `support`/`releases`/`accessibility`/`cgu`/`privacy`/`about` | `/…` | `PagePlaceholder` | meta i18n keys (`router/index.js:26-34`) |
| `admin` | `/admin` | `AdminView` | `{ eyebrow:'admin.eyebrow', title:'admin.title', requiresAdmin:true }` |
| (catch-all) | `/:pathMatch(.*)*` -> `/chat` | - | - |

Points clés :

- **Lazy-loading** : toutes les views sont `() => import('../views/X.vue')` (`router/index.js:14-22`) pour
  garder le bundle chat initial léger.
- **Placeholders honnêtes** : les 6 cibles du menu d'aide partagent une seule `PagePlaceholder` pilotée par
  des clés meta i18n (`router/index.js:26-34`). Les `meta` portent `eyebrow`/`title`/`desc` qui sont des
  clés i18n, pas du texte.
- **Guard admin** (`router/index.js:60-65`) : `beforeEach` async ; si `to.meta.requiresAdmin`, il fait
  `await session.ensureLoaded()` (mémoïsé) puis gate sur `session.isAdmin`, redirigeant vers `{ name:'chat' }`
  sinon. La décision réelle reste SERVEUR (les routes admin renvoient 403) ; le guard n'est qu'un confort UX
  (`docs/frontend.md:342-344`).
- Le `:sessionId?` de la route `chat` est l'id de conversation estampillé dans l'URL au 1er échange (lien F17,
  hors scope de ce pack).

---

## 4. i18n : architecture messages.json pristine + extra.js + merges

Dossier : `Plugin/owismind/frontend/src/i18n/` (`index.js`, `messages.json` 660 lignes, `extra.js` 574
lignes, `langs.json`).

### 4.1 Setup (`i18n/index.js`)

`createI18n({ legacy:false, globalInjection:true, locale:detectLocale(), fallbackLocale:'fr', messages,
warnHtmlMessage:false, missingWarn:false, fallbackWarn:false })` (`i18n/index.js:29-38`).

- `legacy:false` = Composition API (`useI18n()` en scope global) ; `globalInjection:true` = `$t` dans
  les templates.
- `warnHtmlMessage:false` (`i18n/index.js:35`) car quelques clés portent du HTML canned de confiance (ex.
  `default.answer_html`).
- **Détection de locale** (`detectLocale`, `i18n/index.js:18-27`) : d'abord `localStorage.getItem('owismind.lang')`
  si supportée, sinon `navigator.language` tronquée à 2 lettres et minusculée, sinon `'fr'`. La constante
  `STORAGE_KEY = 'owismind.lang'` (`i18n/index.js:14`) est la clé que la maquette utilisait déjà.
- `SUPPORTED = langs.map(l => l.id)` (`i18n/index.js:16`), `AVAILABLE_LOCALES = langs` exporté.

### 4.2 `messages.json` PRISTINE + `extra.js` (override par locale)

Décision d'architecture centrale (invariant **F6** / L023) : `messages.json` est un **port 1:1** de
`window.OWI_I18N` de la maquette d'origine (supprimée du repo après conversion) ; il reste PRISTINE,
jamais édité (`i18n/index.js:1-3`, `docs/frontend.md:360-363`). Tout ajout de chaîne va dans
`i18n/extra.js`, en **clé-plate par locale** : `export const extraMessages = { fr:{...}, en:{...} }`
(`extra.js:12`), mergé via `i18n.global.mergeLocaleMessage('fr'|'en', ...)` (`i18n/index.js:47-50`).

Deux catalogues domaine sont mergés au setup (`i18n/index.js:47-50`) :
1. `timelineMessages.fr/en` depuis `registries/timelineSteps.js` (labels des `eventKind` de la timeline).
2. `extraMessages.fr/en` depuis `i18n/extra.js` (chaînes Phase 3/4).

`extra.js` peut **surcharger** des clés de `messages.json` : ex. `'prompt.placeholder'` y est redéfini
(`extra.js:21`/`302`) pour le guidage "le plus précisément possible", et `'empty.tip'` ajouté
(`extra.js:22`/`303`). Le merge est appliqué APRÈS le chargement de `messages` donc l'override gagne.

Familles de clés dans `extra.js` : générique `x.*` (`x.close`, `extra.js:17`), `set.*`, `sb.*`, `chat.*`,
`fb.*`, `msg.*`, `faq.*`, `ag.*`, `pj.*`, `admin.*`, `ev.*` (Evidence Studio), `art.*` (onglets artefacts),
`mode.*` (sélecteur de mode modèle), et `ev.exp.*` (étapes de calcul du trust layer, enum `kind` figé). La
philosophie : **états vides honnêtes** ("bientôt disponible", jamais de faux chiffres ; `extra.js:5-7`).

### 4.3 Interpolation en LISTE

Les placeholders positionnels `{0}`/`{1}`/`{2}` de la maquette mappent directement sur la list
interpolation vue-i18n : `t('key', [arg0, arg1])` (`i18n/index.js:5-6`, `docs/frontend.md:358-359`).
Exemples : `'tl.steps_count': '{0} étape(s)'` (`extra.js:54`), `'ev.exp.filter_in': 'Filtrer : {0} parmi
{2} ({1} valeur(s))'` (`extra.js:260`). Les noms de colonnes passés en params restent verbatim.

### 4.4 `langs.json` et bascule de langue

`langs.json` (`Plugin/owismind/frontend/src/i18n/langs.json`) = liste d'objets locale :
`[{id, label, short, flag, htmlLang}]` - `fr` (`Français`/`FR`/`🇫🇷`/`fr`) et `en`
(`English`/`EN`/`🇬🇧`/`en`).

- `htmlLangFor(id)` (`i18n/index.js:40-42`) mappe id -> attribut `<html lang>` ; appliqué au boot
  (`i18n/index.js:53`) et à chaque `setLocale`.
- `setLocale(id)` (`i18n/index.js:56-65`) : valide l'id, met `i18n.global.locale.value`, persiste
  (`owismind.lang`) et pose `document.documentElement.lang`. `currentLocale()` lit la locale active.
- Le store `ui` garde un **miroir réactif** : `setLang(id)` (`ui.js:122-125`) appelle `setLocale` puis
  `lang.value = currentLocale()`. Le store **ne persiste jamais** la langue lui-même : `setLocale` possède
  la clé `owismind.lang` (évite un second système de persistance ; `ui.js:66-68`).
- **Données** `{fr,en}` (métadonnées agents, FAQ) -> rendues via `useTr()` (`composables/useTr.js`), PAS
  `$t` : `tr(v)` passe une string telle quelle, résout un objet `{fr,en}` sur la locale courante avec
  fallback `cur -> fr -> en -> première valeur` (`useTr.js:8-20`). Réactif sur le ref de locale.

> Ajouter une langue (`i18n/index.js:5-7`, `docs/frontend.md:374-376`) : ajouter son bloc dans
> `langs.json` + un bloc locale dans `messages.json` + le champ sur tout objet data `{fr,en}`.

---

## 5. Vite config et pipeline de build

### 5.1 `vite.config.js`

Fichier : `Plugin/owismind/frontend/vite.config.js` (13 lignes). Contenu intégral significatif :

```js
export default defineConfig({
  plugins: [vue()],
  base: '/plugins/owismind/resource/owismind-app/',
  build: { outDir: '../resource/owismind-app', emptyOutDir: true },
})
```

- **`base`** = `/plugins/owismind/resource/owismind-app/` (`vite.config.js:7`) : c'est l'URL publique sous
  laquelle DSS sert les assets statiques du plugin. Tous les chemins d'assets (script, css, modulepreload,
  favicon) sont préfixés par cette base dans l'`index.html` buildé.
- **`outDir`** = `../resource/owismind-app` (`vite.config.js:10`) : le build écrit dans
  `Plugin/owismind/resource/owismind-app/` (frère de `frontend/`). `emptyOutDir:true` purge la sortie.
- Ces deux noms sont **CANONIQUES** : ne jamais les changer (`frontend/CLAUDE.md:6-8`,
  `build-plugin/SKILL.md:49`, `memory/PROJECT_STATE.md` §3). Un changement de `base` impose de refaire build
  + recopie de `body.html`.

### 5.2 Sortie du build (constatée)

Dans `Plugin/owismind/resource/owismind-app/` (tracké git, PAS gitignore - vérifié via `git check-ignore`) :
un `index.html` réécrit + un dossier `assets/` de fichiers **hashés** par contenu. Constaté au moment de
l'étude :
- entrée principale `assets/index-DCY_crmu.js` (341 197 octets) + `assets/index-D7fJBFZD.css` (35 333 octets) ;
- chunks lazy par view : `ChatView-BIDRZ8fG.js` (149 317 o, le plus gros - inclut Chart.js, Evidence...),
  `AdminView-*`, `AgentsView-*`, `FaqView-*`, `FeedbackView-*`, `SettingsView-*`, `PagePlaceholder-*`,
  `ProjectView-*`, avec leurs `.css` jumeaux ;
- chunks partagés : `Icon-R0zNmMF0.js` (182 921 o, set d'icônes), `session-lX0dumx_.js`, `useTr-Ceqttkgc.js`,
  `pages-*.js`, plus l'asset `orange-logo-C6rK4N-7.png` (depuis `src/assets/orange-logo.png`).

L'`index.html` buildé (`Plugin/owismind/resource/owismind-app/index.html`) :
- favicon réécrit vers `/plugins/owismind/resource/owismind-app/favicon.svg` (le `public/favicon.svg`
  source est copié tel quel) ;
- `<script type="module" crossorigin src="/plugins/owismind/resource/owismind-app/assets/index-DCY_crmu.js">` ;
- `<link rel="modulepreload">` pour `Icon-*.js` et `session-*.js` ; 2 `<link rel="stylesheet">`
  (`Icon-*.css`, `index-*.css`). Tous préfixés par `base`.

> NOTE : le hash de l'entrée (`index-DCY_crmu.js` ici) CHANGE à chaque build (invariant **F10/F40**). Les
> notes mémoire citent des hashes plus récents (ex. `index-CrvKHGTt.js` au Run 7c) ; le hash exact n'est
> pas un identifiant stable et ne doit pas être traité comme tel.

### 5.3 De `index.html` à `body.html`

DSS sert la webapp via un fichier `body.html`, pas via `index.html`. Le pipeline (skill
`/build-plugin`, `.claude/skills/build-plugin/SKILL.md`) :

1. **Preflight - jamais d'install** : `test -d .../node_modules` ; si absent, STOP et demander à l'user
   (`build-plugin/SKILL.md:20-24`).
2. **Build** : `npm --prefix Plugin/owismind/frontend run build` (`build-plugin/SKILL.md:26-30`) ->
   produit `resource/owismind-app/` (assets hashés).
3. **Wire body.html** : `cp Plugin/owismind/resource/owismind-app/index.html
   Plugin/owismind/webapps/webapp-owismind-ai-agents/body.html` (`build-plugin/SKILL.md:32-36`). Le `cp`
   Bash est autorisé ; Edit/Write sur la sortie est bloqué. (Gotcha L033 : si `cp` est refusé par les
   permissions, recâbler via l'outil `Write` ; le `cp -R` du packaging passe.)
4. **Verify** : grep que `/plugins/owismind/resource/owismind-app/` est présent dans `body.html`
   (`build-plugin/SKILL.md:38-43`).

Constaté : `body.html` (`Plugin/owismind/webapps/webapp-owismind-ai-agents/body.html`, 917 octets) est une
copie **byte-identique** de l'`index.html` buildé (mêmes hashes `index-DCY_crmu.js` etc.). Le `app.js` du
webapp (`webapps/.../app.js`) est un commentaire vide : "Vue/Vite application is loaded from body.html.
Legacy DSS template JavaScript has been removed intentionally."

### 5.4 Packaging (zip)

Le frontend N'ENTRE JAMAIS dans le zip (règle #5). Le skill `/package-plugin`
(`.claude/skills/package-plugin/SKILL.md`) stage **seulement le runtime** : `plugin.json` (racine zip),
`python-lib/`, `resource/`, `webapps/` (`package-plugin/SKILL.md:14`). Exclus explicitement par NOM :
`frontend/`, `node_modules/`, `_/`, `.DS_Store`, `__MACOSX/`, `CLAUDE.md`/`README.md` dev, `__pycache__/`,
`*.pyc` (`package-plugin/SKILL.md:15-18`). Donc le **build artefact** (`resource/owismind-app/`) est ce qui
voyage dans le zip, pas les sources Vue. Sortie : `Plugin/ready-for-dataiku/owismind-upload.zip`.

### 5.5 Comment DSS sert la SPA

Descripteur webapp `Plugin/owismind/webapps/webapp-owismind-ai-agents/webapp.json` :
`"baseType": "STANDARD"`, `"hasBackend": "true"`, `"standardWebAppLibraries": ["jquery","dataiku"]`. La lib
`dataiku` injecte globalement `window.getWebAppBackendUrl(path)`, que le client backend résout
**paresseusement** (`services/backend.js:9-14`) - on ne code jamais d'URL en dur. Le préfixe Blueprint Flask
est `/owismind-api` sans slash final ; appels en `credentials: 'same-origin'` (cookies d'auth DSS ;
`services/backend.js:20-23`, `docs/frontend.md:34-39`). Hors DSS (`npm run dev`), `getWebAppBackendUrl` est
absent : chaque appel jette proprement et les stores dégradent gracieusement (le shell s'affiche toujours).
Le `webapp.json` expose aussi les params Settings (`sql_connection`, `table_prefix`, `traces_dataset`,
`log_level`) - hors scope frontend, mais c'est le lien runtime.

---

## 6. Thème et design system (tokens)

### 6.1 `tokens.css` - source unique de la couche thème

Fichier : `Plugin/owismind/frontend/src/styles/tokens.css` (139 lignes). Port VERBATIM du `theme.css` de la
maquette validée (`tokens.css:1-17`). Structure :

- **`:root`** (théme-indépendant, `tokens.css:19-86`) :
  - Marque Orange : `--orange:#ff7900`, `--orange-deep:#cc6100`, `--orange-soft:#fff5ec` (`tokens.css:21-23`).
  - Spacing ancré 8px : `--s-1`..`--s-12` (4px -> 128px ; `tokens.css:26-37`).
  - Type : `--font-sans` ("Helvetica Neue"...), `--font-mono` ; échelle `--fs-xs`..`--fs-3xl`
    (12px -> 36px ; `tokens.css:40-49`).
  - Radius : `--r-sm:6px`, `--r:10px`, `--r-lg:12px`, `--r-pill:100px` (`tokens.css:52-56`).
  - **Mesure colonne chat** : `--chat-col:90%` + `--chat-col-max:1200px` (`tokens.css:62-63`) - le thread
    de messages et la prompt bar partagent UNE largeur (texte aligné edge-to-edge avec la saisie, à la
    ChatGPT/Claude). Token partagé clé du Run 7.
  - Motion : `--ease` cubic-bezier, `--dur:200ms`, `--dur-slow:380ms` (`tokens.css:66-68`).
  - Z-index : `--z-menu:60 < --z-overlay:200 < --z-modal:201 < --z-toast:2100` (`tokens.css:73-76`).
  - Status colors LIGHT defaults : `--success:#15803d`, `--danger:#b91c1c`, `--warn:#d97706`,
    `--info:#2563eb` (`tokens.css:82-85`). Note : Evidence Studio **évite le vert** (règle no-green) ;
    ces couleurs sont pour le statut générique (toasts, admin, feedback), pas les verdicts Evidence.

- **Thèmes sémantiques** swappés sur `<body>` :
  - `body[data-theme="light"]` (`tokens.css:89-111`) : `--bg:#fff`, `--surface`, `--surface-2`,
    `--surface-hover`, `--border`, `--border-strong`, `--text:#111`, `--text-2`, `--text-3`, `--shadow`,
    plus tints orange (`--orange-soft-dark`, `--orange-on-dark`, `--orange-text:#b85700` darkenée pour AA
    4.5:1 sur blanc), `--success-soft`/`--danger-soft` (rgba faibles).
  - `body[data-theme="dark"]` (`tokens.css:112-139`) : `--bg:#0d0d0d`... `--text:#f0f0f0` ; variantes dark
    des statuts + tints orange (`--orange-soft-dark: rgba(255,121,0,.10)`, `--orange-text:#ffb066`
    10.8:1) ; `--success-soft`/`--danger-soft` plus opaques (sinon invisibles sur surface dark - bug
    corrigé au Run 7, `tokens.css:135-138`).

RATIONALE des ajouts de tokens : ce sont des **ajouts no-op** dont la valeur égale le littéral déjà
hard-codé dans la maquette - 0 pixel changé ; ils existent pour rendre possible une passe dark-first/status
propre sans toucher aux visuels validés (`tokens.css:5-12`).

### 6.2 `base.css` - reset et utilitaires

Fichier : `Plugin/owismind/frontend/src/styles/base.css` (54 lignes). Importé APRÈS `tokens.css`
(`main.js:5-6`). Contient : reset `box-sizing` + `html,body { height:100% }` ; `body { overflow:hidden }`
(shell viewport fixe, scroll dans les régions internes ; `base.css:13-21`) ; reset des contrôles de form/boutons ;
`::selection { background: var(--orange) }` + scrollbar custom (`base.css:27-31`) ; keyframes partagés
`slide-up`, `pulse-dot`, `shimmer-sweep` (`base.css:34-45`) ; utilitaires `.mono`, `.muted`,
`.u-no-shrink` (L020 : enfants de colonne flex scrollable ne doivent pas shrink ; `base.css:48-54`).

### 6.3 Application et réconciliation du thème

`main.js:14-21` pose `body[data-theme]` avant mount (cf. §2). Le store `ui`
(`Plugin/owismind/frontend/src/stores/ui.js`) est ensuite la **source unique des préférences** (thème,
langue miroir, largeurs sidebar/evidence, fenêtre de contexte, mode modèle). Au setup il réapplique le
thème de façon idempotente (`applyTheme(theme.value)`, `ui.js:107-108`). `setTheme(t)` valide
`'light'|'dark'`, persiste `owismind.theme`, et écrit `document.body.dataset.theme` (`ui.js:110-115`) ;
`toggleTheme()` bascule (`ui.js:116-118`). Défaut `'light'`, fidèle à la maquette (`ui.js:48`).

**Gotcha thème `:global`** (F2/L022, `docs/frontend.md:389-393`) : dans un `<style scoped>`, un override de
thème doit placer le SÉLECTEUR ENTIER dans `:global(body[data-theme="dark"] .x)` (sinon le descendant scopé
est perdu). Pas de `color-mix` (support navigateur, L031) : utiliser `rgba` + override `:global` ou le token
`--orange-soft-dark`.

Clés localStorage gérées par `ui.js` (`ui.js:13-18`) : `owismind.theme` (THEME_KEY), `owismind.sidebarCollapsed`
(COLLAPSE_KEY), `owi.sidebarW` (SIDEBAR_W_KEY, clé maquette), `owi.evidenceW` (EVIDENCE_W_KEY),
`owismind.contextMessages` (CTXMSG_KEY), `owismind.modelMode` (MODELMODE_KEY). Le mode modèle :
`MODEL_MODES = ['eco','medium','high']`, défaut `'eco'` (`ui.js:23-24`) - eco = Gemini 3.1 Flash-Lite (cheap,
DEFAULT), medium = Gemini 3.5 Flash, high = Claude Sonnet (`ui.js:20-22`).

---

## 7. Connexions au reste du système

- **Backend** : tout passe par `services/backend.js` (1 fonction par route, jamais d'URL en dur), via
  `window.getWebAppBackendUrl('/owismind-api/...')` injecté par la lib DSS `dataiku`. Le front envoie une
  **clé logique d'agent** (`agent_key` opaque), jamais un `agent_id` brut (whitelist serveur ; règle #4 +
  `services/backend.js` startChat). Transport chat = POLLING (`/chat/start` -> `/chat/poll` 500ms), pas SSE
  (proxy DSS bufferise les flux longs ; `services/backend.js`, L019).
- **Stores** (`stores/`) : `ui` (préfs), `session` (identité `/me`, agents `/agents`, conversations
  paginées), `chat` (arbre d'échanges + transport), `evidence` (panneau Evidence Studio), + stores purs
  `prefs`/`conversationList`/`conversationTree`/`agentPick`. La route admin et le shell consomment
  `session.isAdmin`/`ensureLoaded()`.
- **Registries** (`registries/`) : `timelineSteps.js` (mappe `eventKind` -> label i18n + icône ; merge i18n),
  `agentMeta.js`, `faqContent.js`. Extensibles par ajout d'entrée.
- **Composables** (`composables/`) : `useTr` (data `{fr,en}`), `useMarkdown` (markdown-it `html:false` +
  DOMPurify, seul chemin `v-html`), `timelineModel`/`useChatStream` (timeline live), `useToasts`,
  `useReducedMotion`, `useClickOutside`.
- **Shell** : `App.vue` -> `AppLayout.vue` (grille `.app` ; sidebar + main = `MainTop` + `<RouterView/>` ;
  panneau Evidence ouvert => grille 3 colonnes). Le `MainTop`/`SettingsView` lisent/écrivent le store `ui`.

---

## 8. Gotchas et points en flux

- **Hash exact des assets non stable** : il change à chaque build ; les notes mémoire citent des hashes
  historiques différents de ceux actuellement sur disque. Ne pas documenter un hash précis comme stable.
- **`messages.json` jamais édité** : toute chaîne nouvelle/override va dans `extra.js` (F6/L023). Le merge
  `extra.js` peut shadow une clé de `messages.json` (cf. `prompt.placeholder`).
- **Thème pré-mount obligatoire** : oublier `body[data-theme]` => flash de tokens non résolus (les tokens
  sémantiques n'existent QUE sous `body[data-theme]`).
- **`base.css` après `tokens.css`** : ordre d'import load-bearing (`main.js:5-6`).
- **Tokens "no-op"** : la majorité des tokens ajoutés valent le littéral déjà hard-codé ; certains ne sont
  référencés par personne (`tokens.css:11-12` "Nothing references the new tokens yet").
- **Ban tiret cadratin/demi-cadratin** (règle #9) : présent dans tout le code/i18n ; vérifié, ce pack n'en
  contient aucun.
- **En flux** : l'autre ingénieur édite live `dataiku-agents/` (couche agents, hors scope frontend) ; aucun
  fichier frontend n'a été modifié par ce pack (read-only).
- **`art.tab.kpi`/`mode.*`/`ev.proof.*`** : familles i18n récentes (artefacts, sélecteur de mode, trust
  layer) ; le détail métier de leur rendu vit dans les composants `evidence/` et `chat/` (autre zone).

---

## 9. Fichiers sources étudiés (ancrage)

`Plugin/owismind/frontend/package.json`, `vite.config.js`, `index.html` ;
`Plugin/owismind/frontend/src/main.js`, `App.vue`, `router/index.js` ;
`src/i18n/index.js`, `extra.js`, `messages.json`, `langs.json` ; `src/composables/useTr.js` ;
`src/registries/timelineSteps.js` ; `src/stores/ui.js` ; `src/services/backend.js` (tête) ;
`src/styles/tokens.css`, `base.css` ;
`Plugin/owismind/resource/owismind-app/index.html` (buildé) + `assets/` ;
`Plugin/owismind/webapps/webapp-owismind-ai-agents/{body.html, webapp.json, app.js}` ;
`docs/frontend.md` ; `Plugin/owismind/frontend/CLAUDE.md` ;
`.claude/skills/build-plugin/SKILL.md`, `.claude/skills/package-plugin/SKILL.md`.
