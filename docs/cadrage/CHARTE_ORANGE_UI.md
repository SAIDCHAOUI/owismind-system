# Charte Orange - règle de style UI d'OWIsMind (source de vérité)

> **À appliquer SYSTÉMATIQUEMENT à tout travail de style frontend** (nouvelle page, nouveau composant,
> retouche). Ce document est **auto-suffisant** : il a été extrait d'une maquette HTML de référence
> (validée par l'user) que l'on a ensuite supprimée. Il n'y a plus de fichier maquette : **cette charte
> EST la maquette**. Décision user 2026-06-18 : « à chaque fois qu'on fait du style, ça doit être comme ça ».

## 0. Évolution « premium épuré » (décision user 2026-08-13, PRIME sur les sections suivantes)
L'user a fait évoluer la charte vers un rendu **plus épuré et premium** (références : interfaces Claude
et Gemini, sans les calquer). Les points ci-dessous **remplacent** les interdits correspondants de la
section 2 ; tout le reste de la charte (orange rare, blanc/noir, tokens, filets, typographie) reste en vigueur.

- **Arrondis AUTORISÉS et attendus** sur les surfaces interactives et flottantes : carte de prompt
  (`--r-xl` 18px), popovers/menus flottants (`--r-lg`), chips (`--r-pill`), boutons d'icône et action
  primaire (`--r-pill`), petits caps (`--r-xs`). La géométrie carrée reste par défaut pour les surfaces
  STRUCTURELLES (tables, panneaux, en-têtes, KPI).
- **Élévation douce AUTORISÉE** via les tokens `--elev-1` (repos) / `--elev-2` (hover, focus, flottant) :
  ombres diffuses en couches, jamais de halo coloré dur. `--shadow` (1px) reste pour les surfaces plates.
- **Flou teaser AUTORISÉ, cas unique** : le dock Source Data auto-amarré floute son contenu
  (`blur ~3px`) derrière une carte d'invite ; toute interaction lève le flou. Aucun autre usage de
  blur/backdrop-filter n'est permis.
- **Nuances** : jouer davantage sur les paliers de surface (`--bg` / `--surface` / `--surface-2`) et les
  tailles de texte pour la hiérarchie, plutôt que sur des bordures fortes. En sombre, une carte flottante
  prend un palier au-dessus du fond (ex. `--surface-2` sur `--bg`).
- **Focus des champs (recette unique, remplace la « bordure orange » de la section 5)** : tout champ
  (prompt, recherche, input, select, textarea) focalisé = **bordure `--text-3` + élévation** (`--elev-1`,
  `--elev-2` pour le prompt). L'orange reste réservé au `focus-visible` CLAVIER des boutons/contrôles.
- **Cartographie des rayons (entérinée 2026-08-13)** : contrôles compacts (chips, badges, segmenté,
  recherche) = `--r-pill` ; champs de formulaire et cartes = `--r-lg` ; tuiles d'icône = `--r` (héros
  56px = `--r-lg`) ; petits caps (kbd, checkbox) = `--r-xs` ; surfaces STRUCTURELLES (tables, panneaux,
  en-têtes, jauges, tuiles de stats) = carrées.
- **Micro-labels** : 11px / `--fw-heavy` / MAJUSCULES / `--tracking-eyebrow` (0.08em) - remplace le
  « .1em » cité plus bas.
- **Sorties plus vives que les entrées** : sorties = `--dur-fast` + `--ease-in` ; entrées = `--dur`
  (+ `--dur-slow` pour les entrées de page) + `--ease-out`. État appuyé = `--surface-press`.

## 1. Esprit
Sobre, tranché, éditorial. **Blanc / noir (presque) / une seule couleur Orange (#FF7900)**, l'orange étant
un accent **rare** (états actifs, eyebrows, title-bars, règle haute des KPI, action primaire, liens).
Le blanc et le noir portent l'essentiel. **Aplats, filets 1px, géométrie carrée nette, gros titres lourds.**
Pas d'effet décoratif. Typo Helvetica Neue.

## 2. Interdits durs (jamais, partout)
- **Tiret cadratin (U+2014) / demi-cadratin (U+2013)** : bannis (règle #9, y compris en citation littérale). Utiliser `-`, `:`, `,`, parenthèses.
- **`color-mix`** (L031) : utiliser `rgba()` + tokens.
- **`blur` / `backdrop-filter`** : aucun flou.
- **Dégradés** (`linear/radial-gradient`) : aucun.
- **Glow / grosses ombres molles** : aucune. Ombre maximale = niveau 1px (`var(--shadow)`). Les accents
  orange sont des **barres nettes**, pas des halos.
- **Emoji** dans l'UI.
- **Focus-ring orange global** (contour qui englobe toute la zone de saisie) : interdit. Le focus = **bordure
  orange sur l'élément focalisé** uniquement.
- **Visuel de marque reconstruit en CSS** : interdit. **Toujours utiliser la vraie image de marque** (logo
  `frontend/src/assets/orange-logo.png`, importée), **jamais** un carré orange + barre généré en CSS. (Leçon L092.)
- **Radius arrondi** sur les surfaces de marque (cartes, chips, boutons, inputs, modales, KPI, badges,
  checkbox, onglets, barre de recherche, tuiles d'icône) : géométrie **carrée** (`border-radius: 0`). Seuls
  les **avatars** sont ronds (`border-radius: 50%`). Les tokens `--r*` existent mais ne servent PAS ici.

## 3. Tokens (source unique : `frontend/src/styles/tokens.css`)
Toujours passer par les **tokens sémantiques** (jamais de hex en dur, sauf `#fff` sur fond orange). Le thème
clair/sombre est piloté par `body[data-theme]` ; en utilisant les tokens, le dark mode marche tout seul.

- **Orange** : `--orange` (#ff7900), `--orange-deep` (#cc6100, hover du primaire). **Texte orange sur fond
  clair = `--orange-text`** (AA-safe ; **jamais** `--orange-deep` pour du petit texte).
- **Encre** : `--text` (≈ noir), `--text-2` (gris moyen), `--text-3` (gris clair).
- **Surfaces** : `--bg` (fond carte/page), `--surface`, `--surface-2`, `--surface-hover`.
- **Filets** : `--border-strong` (filet VISIBLE : contour de carte, règle d'en-tête de table, onglets,
  segmenté) ; `--border` (filet doux : séparateurs internes).
- **Statut** : `--success`, `--danger`, `--warn`, `--info` (+ `*-soft`).
- **Poids** : `--fw-regular` 400, `--fw-medium` 500, `--fw-semibold` 600, `--fw-bold` 700,
  **`--fw-heavy` 800** (titres d'affichage).
- **Typo** : `--font-sans` (Helvetica Neue), `--font-mono` (ids / montants / codes / noms de dataset / tokens).
- **Espacement** : échelle `--s-1`..`--s-12` (ancrée 8px).

### Correspondance « langage design » -> tokens (mémo)
| Intention | Token |
|---|---|
| Orange accent (fonds, barres, règles, primaire) | `var(--orange)` |
| Orange TEXTE (AA) | `var(--orange-text)` |
| Noir / encre | `var(--text)` ; gris `var(--text-2)` ; gris clair `var(--text-3)` |
| Filet visible | `var(--border-strong)` |
| Filet doux | `var(--border)` |
| Fond carte | `var(--bg)` ; doux `var(--surface)` / `var(--surface-2)` |
| Vert / rouge | `var(--success)` / `var(--danger)` |
| Poids titre | `var(--fw-heavy)` (800) |

## 4. Typographie
- **H1 de page** : `--fs-3xl` (36px) / `--fw-heavy` / `letter-spacing -0.01em` / `line-height 1.05`.
- **Eyebrow** (au-dessus du H1) : `var(--orange)`, MAJUSCULES, 12px, 700, `letter-spacing .1em`.
- **Title-bar** (sous le H1) : bloc plein **52px x 4px** `var(--orange)`, `margin: 16px 0 0`.
- **Micro-labels** (labels de carte, en-têtes de table) : MAJUSCULES, 11px, 800, `letter-spacing .1em`, `var(--text-2)`.
- **Mono** : ids, montants (`$x.xx`), codes, clés de projet, noms de table/dataset, compteurs.

## 5. Recettes de composants (le « comme la maquette »)
- **En-tête de page** (`PageShell`) : eyebrow + H1 + title-bar orange + desc (`--text-2`, ~15px). Pour un
  en-tête custom (slot `#header`), reproduire eyebrow + H1 + title-bar à la main.
- **Carte** : `border: 1px solid var(--border-strong)`, `border-radius: 0`, `background: var(--bg)`.
- **Carte KPI** : carte carrée + **règle HAUTE 3px `var(--orange)`** + icône orange + label MAJ + grande valeur 800.
- **Onglets** : rangée à bordure basse ; actif = `var(--text)` + **soulignement 3px orange** ; inactif `var(--text-2)` ; compteur mono optionnel.
- **Chips / tags** : carrés, 1px `var(--border-strong)`. Chip accent = bordure orange + texte `var(--orange-text)`.
- **Boutons** : carrés. Défaut (ghost) = bordure **2px** `var(--text)`, fond transparent ; **hover inverse**
  (fond `var(--text)`, texte `var(--bg)`). Primaire = plein `var(--orange)` + `#fff`, hover `var(--orange-deep)`.
  Small = bordure 1px. Danger = plein `var(--danger)`.
- **Contrôle segmenté** : rangée bordée 1px `var(--border-strong)` ; segment actif = fond `var(--text)`, texte `var(--bg)`.
- **Checkbox carrée** : 18px, bordure 1.5px `var(--text)` ; cochée = fond `var(--orange)` + check blanc.
- **Modale** (`Modal`) : scrim plat `rgba(0,0,0,.55)` **sans blur** ; carte carrée 1px `var(--border-strong)`,
  `border-radius 0`, ombre minimale/aucune ; titre 20px/800 ; bouton fermer + tuile d'icône carrés.
- **Tables** : en-tête MAJUSCULES au-dessus d'une règle 1px `var(--border-strong)` ; lignes séparées par 1px `var(--border)`.
- **Barre de recherche** : 1px `var(--border)`, focus = bordure orange ; note de compte en mono.
- **Carte d'agent** (bibliothèque) : carte carrée, hover bordure `var(--text)` ; tuile d'icône carrée à glyphe
  orange ; accroche en `var(--orange-text)` ; pied = compteur d'outils + chevron.
- **Empty state** : carré, 1px `var(--border-strong)`, tuile d'icône carrée ; tag « Soon » = carré orange plein.
- **Rail / logo** : sidebar repliée = rail d'icônes ; **le logo de marque est la VRAIE image**
  (`import logoUrl from '../../assets/orange-logo.png'` + `<img :src="logoUrl">`), au rail comme à la sidebar
  dépliée. Jamais de carré CSS.

## 6. Light/Dark, scope, build
- Tokens sémantiques uniquement -> dark automatique. Override spécifique thème :
  `:global(body[data-theme="dark"] .x)` avec le **sélecteur ENTIER** dans `:global` (F2).
- Styles **scoped** par composant. Le chrome partagé vit dans `components/pages/` (PageShell, SettingCard,
  EmptyState) et `components/ui/` (Button, Modal). **Primitives partagées avec le chat** (Button, Modal, Tabs) :
  un restyle préserve l'API (props/slots/variants) ; **`Tabs.vue` est partagé avec l'Evidence panel validé** ->
  styliser les onglets Admin **localement** (`:deep()` dans la vue), ne pas toucher `Tabs.vue`.
- **Mouvement** : entrées discrètes (`u-rise` / léger translate) ; respecter `prefers-reduced-motion`.
- Ne jamais éditer à la main `resource/owismind-app/` ni `ready-for-dataiku/` (générés). Build via `/build-plugin`.
