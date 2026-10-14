# OWIsMind - Brief de maquette fonctionnelle (pour Claude Design)

> **Ce document est le contexte complet dont tu as besoin pour maquetter l'interface OWIsMind.**
> Il décrit ce que fait l'interface aujourd'hui (code réel en production interne), écran par écran,
> état par état, avec les libellés exacts, les données réelles et le design system.
> Tout ce qui est marqué **[EXISTE]** est implémenté et validé. Tout ce qui est marqué
> **[À EXPLORER]** est un point ouvert sur lequel on attend ta proposition de design.
>
> **Ta mission** : produire une maquette HTML/CSS multi-écrans, fidèle au design system, qui couvre
> tous les écrans et tous les états listés ici. Cette maquette sera ensuite itérée visuellement,
> puis reportée dans l'application réelle (Vue 3 + Vite). Tu ne codes pas l'app : tu conçois
> la disposition, la hiérarchie, le comportement visuel et les états.

---

## 0. CE QU'IL FAUT PRODUIRE

### Format attendu
- **Un artboard par écran/état** listé en section 15 (checklist de livraison).
- HTML + CSS autonome. Pas de framework, pas de dépendance externe.
- **Les variables CSS doivent être celles de la section 3** (mêmes noms de tokens) : le portage vers
  l'app réelle consiste alors à copier la structure et à brancher les données.
- **Thème clair ET sombre** pour chaque écran (le thème est piloté par `body[data-theme="light"|"dark"]`).
- Densité **desktop-first** : cible 1440x900 à 1920x1080. Le 12 pouces doit rester utilisable.
  Le mobile n'est pas prioritaire.

### Ce qui compte le plus dans cette maquette
1. **La disposition des trois colonnes** et la façon dont elles se disputent l'espace (section 4).
2. **L'affichage du raisonnement de l'agent** (section 6) : c'est le coeur du produit et le point
   le plus difficile. On veut voir l'agent travailler sans que ça devienne du bruit technique.
3. **Evidence Studio** (section 7) : la surface qui prouve la réponse.
4. **Source Data / Analyze** (section 8) : l'exploration de données à côté du chat.

---

## 1. LE PRODUIT

**OWIsMind** est un portail d'agents IA métier pour les équipes d'un opérateur télécom (Orange).
Un utilisateur pose une question métier en langage naturel ("Compare les revenus réels et le budget
2026 par solution"), un orchestrateur d'agents interroge les données de l'entreprise (SQL sur un
entrepôt PostgreSQL via des modèles sémantiques), et répond avec **la preuve de ce qu'il avance**.

### Ce qui le distingue d'un chatbot
Trois surfaces, jamais mélangées :
1. **La conversation** : la réponse métier, lisible, en markdown.
2. **La timeline d'exécution live** : ce que l'agent est en train de faire, étape par étape.
3. **Evidence Studio** : d'où vient le chiffre, comment il a été calculé, sur quelles lignes,
   avec quel SQL, et à quel niveau de certitude.

**Le détail technique ne pollue jamais la réponse.** Le SQL, les traces, les coûts vivent dans des
panneaux dédiés que l'utilisateur ouvre s'il le veut.

### Qui l'utilise
Des profils métier (revenue managers, delivery, service client), pas des data engineers. Ils doivent
pouvoir vérifier un chiffre sans savoir lire du SQL. D'où le vocabulaire : "Comment ce résultat est
calculé" plutôt que "Query plan", "Source certifiée" plutôt que "Verification level".

### Règle d'honnêteté (structurante, non négociable)
**Zéro faux chiffre, zéro fonction simulée.** Si une donnée n'existe pas, l'écran le dit
explicitement ("Le résultat exact utilisé par l'agent n'a pas été conservé pour cette réponse")
plutôt que d'afficher un placeholder crédible. Tous les états vides de la maquette doivent être
des états vides **honnêtes**, jamais du faux contenu.

### Langues
FR + EN, tout est traduit. L'anglais est la langue par défaut. Les libellés cités dans ce document
sont donnés en anglais (la version FR existe en parallèle).

---

## 2. PRINCIPES UX NON NÉGOCIABLES

| Principe | Conséquence design |
|---|---|
| **Transparence par défaut** | L'utilisateur sait toujours quel agent agit, quelle étape tourne, quelle donnée a servi, combien ça a coûté. |
| **Preuve vs exploration** | Evidence = ce qui a réellement produit la réponse. Source Data = exploration libre. Deux surfaces distinctes, jamais confondues. |
| **Le détail technique dans des panneaux** | Jamais de SQL, d'ID technique ou de code d'erreur dans le fil de conversation. |
| **Agent-agnostique** | Ajouter un agent = un acte de configuration. Aucun contenu d'agent n'est codé en dur dans l'UI. |
| **Une seule façon de faire une chose** | On a supprimé un lien "Check this number" parce qu'il ouvrait le même panneau qu'un bouton déjà présent. Pas de deux chemins concurrents pour la même action. |
| **Jamais de vert pour la preuve** | Le vert dirait "validé/correct". Le niveau de preuve se lit en orange plein / orange pointillé / gris. |

---

## 3. DESIGN SYSTEM (charte Orange)

### 3.1 Esprit
Sobre, tranché, éditorial. **Blanc / noir (presque) / un seul orange `#FF7900` en accent RARE**.
Le blanc et le noir portent l'essentiel. Aplats, filets 1px, gros titres lourds, typo Helvetica Neue.
Références de niveau de finition : les interfaces Claude et Gemini (sans les calquer).

L'orange sert uniquement à : états actifs, eyebrows, title-bars, règle haute des cartes KPI,
action primaire, liens, et l'étape en cours d'un plan. Rien d'autre.

### 3.2 Tokens (à reprendre tels quels)

```css
:root {
  /* Marque (indépendante du thème) */
  --orange: #ff7900;
  --orange-deep: #cc6100;        /* hover du bouton primaire */
  --orange-soft: #fff5ec;        /* voile de focus de la carte de prompt */
  --orange-line: rgba(255,121,0,.22);

  /* Espacement, ancré 8px */
  --s-1:4px; --s-2:8px; --s-3:12px; --s-4:16px; --s-5:20px; --s-6:24px;
  --s-7:32px; --s-8:40px; --s-9:56px; --s-10:72px; --s-11:96px; --s-12:128px;

  /* Typo */
  --font-sans: "Helvetica Neue", Helvetica, Arial, sans-serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, "Roboto Mono", monospace;
  --fs-xs:12px; --fs-sm:13px; --fs-base:14px; --fs-md:15px;
  --fs-lg:17px; --fs-xl:22px; --fs-2xl:28px; --fs-3xl:36px;
  --fw-regular:400; --fw-medium:500; --fw-semibold:600; --fw-bold:700; --fw-heavy:800;
  --tracking-tight:-0.02em; --tracking-eyebrow:0.08em;

  /* Rayons */
  --r-xs:4px; --r-sm:6px; --r:10px; --r-lg:12px; --r-xl:18px; --r-pill:100px;
  --square:8px;

  /* Colonne de chat */
  --chat-col:90%; --chat-col-max:1200px;
  --rail-w:60px;                 /* sidebar repliée */

  /* Mouvement */
  --ease: cubic-bezier(.16,1,.3,1);
  --ease-out: cubic-bezier(.22,1,.36,1);
  --ease-in: cubic-bezier(.4,0,.7,.2);
  --dur-fast:130ms; --dur:200ms; --dur-slow:380ms;

  /* Z-index */
  --z-menu:60; --z-overlay:200; --z-modal:201; --z-toast:2100;

  /* Statuts (valeurs claires) */
  --success:#15803d; --danger:#b91c1c; --warn:#d97706; --info:#2563eb;
}

body[data-theme="light"] {
  --bg:#ffffff; --surface:#fafafa; --surface-2:#f5f5f5;
  --surface-hover:#f0f0f0; --surface-press:#e8e8e8;
  --border:#ececec; --border-strong:#d8d8d8;
  --text:#111111; --text-2:#5e5e5e; --text-3:#9a9a9a;
  --shadow: 0 1px 2px rgba(0,0,0,.04);
  --elev-1: 0 1px 2px rgba(0,0,0,.04), 0 4px 16px rgba(0,0,0,.06);
  --elev-2: 0 2px 6px rgba(0,0,0,.05), 0 12px 32px rgba(0,0,0,.10);
  --aura-orange: 0 0 22px rgba(255,121,0,.09), 0 12px 40px rgba(255,121,0,.10);
  --aura-orange-strong: 0 0 26px rgba(255,121,0,.13), 0 14px 48px rgba(255,121,0,.14);
  --orange-soft-dark: var(--orange-soft);
  --orange-on-dark: var(--orange-deep);
  --orange-text:#b85700;         /* orange TEXTE, AA sur blanc */
  --success-soft: rgba(34,197,94,.10);
  --danger-soft: rgba(239,68,68,.08);
  --warn-soft: rgba(217,119,6,.10);
}

body[data-theme="dark"] {
  --bg:#0d0d0d; --surface:#161616; --surface-2:#1c1c1c;
  --surface-hover:#222222; --surface-press:#2a2a2a;
  --border:#232323; --border-strong:#2e2e2e;
  --text:#f0f0f0; --text-2:#a0a0a0; --text-3:#6e6e6e;
  --shadow: 0 1px 2px rgba(0,0,0,.4);
  --elev-1: 0 1px 3px rgba(0,0,0,.5), 0 6px 20px rgba(0,0,0,.45);
  --elev-2: 0 2px 8px rgba(0,0,0,.55), 0 16px 40px rgba(0,0,0,.5);
  --aura-orange: 0 0 24px rgba(255,121,0,.08), 0 12px 44px rgba(255,121,0,.09);
  --aura-orange-strong: 0 0 28px rgba(255,121,0,.12), 0 16px 52px rgba(255,121,0,.13);
  --orange-soft-dark: rgba(255,121,0,.10);
  --orange-on-dark:#ffb066;
  --orange-text:#ffb066;
  --success:#4ade80; --danger:#f87171; --warn:#fb923c; --info:#93c5fd;
  --success-soft: rgba(74,222,128,.14);
  --danger-soft: rgba(248,113,113,.13);
  --warn-soft: rgba(251,146,60,.14);
}
```

**Jamais de hex en dur** (sauf `#fff` sur un fond orange). Toujours les tokens sémantiques : le
thème sombre marche alors tout seul.

### 3.3 Géométrie : carré par défaut, arrondi sur l'interactif

| Élément | Rayon |
|---|---|
| Tables, panneaux, en-têtes, KPI, jauges, tuiles de stats (surfaces **structurelles**) | `0` (carré) |
| Chips, badges, contrôle segmenté, barre de recherche, boutons d'icône, action primaire | `--r-pill` |
| Champs de formulaire, cartes | `--r-lg` |
| Popovers et menus flottants | `--r-lg` |
| Carte de prompt (le sujet de l'écran) | `--r-xl` (18px) |
| Lignes de liste et de nav (sidebar) | `--r-sm` |
| Tuiles d'icône | `--r` (héros 56px = `--r-lg`) |
| Petits caps (kbd, checkbox) | `--r-xs` |
| Avatars | `50%` (les seuls ronds) |

### 3.4 Typographie

- **H1 de page** : 36px / 800 / `letter-spacing -0.01em` / `line-height 1.05`.
- **Eyebrow** (au-dessus du H1) : orange, MAJUSCULES, 12px, 700, `letter-spacing .1em`.
- **Title-bar** : bloc plein orange sous le titre. Décline à toutes les échelles :
  **52x4px** (H1 de page), **40x3px** (titre de l'écran d'arrivée), **18x2px** (ligne
  sélectionnée de la sidebar, tracée `scaleX 0 -> 1` depuis la gauche, 60ms après le
  remplissage de la ligne).
- **Micro-labels** (labels de carte, en-têtes de table) : 11px / 800 / MAJUSCULES /
  `letter-spacing .08em` / `--text-2`.
- **Mono** : ids, montants (`$0.0082`), codes, noms de dataset, compteurs, durées.

### 3.5 Recettes de composants

- **Carte** : `1px solid var(--border-strong)`, fond `--bg`.
- **Carte KPI** : carrée + **règle HAUTE 3px orange** + icône orange + label MAJ + grande valeur 800.
- **Onglets** : rangée à bordure basse, actif = `--text` + **soulignement 3px orange**,
  inactif `--text-2`, compteur mono optionnel.
- **Chips / tags** : 1px `--border-strong`. Chip accent = bordure orange + texte `--orange-text`.
  Chip "avancé" ou "ajouter" = bordure **pointillée**.
- **Boutons** : ghost = bordure 2px `--text`, fond transparent, **hover inversé**
  (fond `--text`, texte `--bg`). Primaire = plein orange + `#fff`, hover `--orange-deep`.
  Small = bordure 1px. Danger = plein `--danger`.
- **Contrôle segmenté** : rangée bordée 1px, segment actif = fond `--text`, texte `--bg`.
- **Checkbox carrée** : 18px, bordure 1.5px `--text`, cochée = fond orange + check blanc.
- **Modale** : scrim plat `rgba(0,0,0,.55)` **sans flou**, carte carrée 1px `--border-strong`,
  ombre minimale, titre 20px/800.
- **Tables** : en-tête MAJUSCULES au-dessus d'une règle 1px `--border-strong`, lignes séparées
  par 1px `--border`, en-tête collant (sticky).
- **Empty state** : cadre carré 1px `--border-strong` (pointillé quand rien n'est interactif),
  tuile d'icône carrée, tag "Soon" = carré orange plein.

### 3.6 Focus

- **Tout champ focalisé** (recherche, input, select, textarea) : bordure `--text-3` + `--elev-1`.
- **UNE exception, la carte de prompt** : bordure `--orange` + voile net 4px `--orange-soft`
  + `--elev-2`. Ne pas étendre cette recette ailleurs.
- L'orange reste réservé au `focus-visible` **clavier** des boutons et contrôles.
- **Interdit** : focus-ring orange global qui englobe toute une zone de saisie.

### 3.7 Élévation et effets

- `--elev-1` au repos, `--elev-2` au hover/focus/flottant. Ombres diffuses en couches,
  **jamais de halo coloré dur**.
- **Aura de marque : cas unique = la carte de PROMPT.** Un nuage orange très diffus
  (`--aura-orange` au repos, `--aura-orange-strong` au survol), sur l'écran d'arrivée ET en
  conversation. Contraintes : alpha <= 0.14, pas de contour dur, pas de dégradé, pas de flou,
  et l'aura est peinte **derrière** l'élévation neutre (en CSS : écrire `var(--elev-*)` AVANT
  `var(--aura-orange)` dans la liste de `box-shadow`). Au focus, l'aura reste à son intensité
  de repos (sinon trois cernes concentriques).
- **Flou : cas unique = le teaser du dock Source Data** (`blur ~3px` derrière une carte d'invite,
  levé dès la première interaction). Aucun autre usage de blur/backdrop-filter.

### 3.8 Interdits durs

- **Tiret cadratin (U+2014) et demi-cadratin (U+2013)** : bannis partout, UI comprise. Utiliser `-`, `:`, `,`
  ou des parenthèses.
- `color-mix` (utiliser `rgba()` + tokens).
- Dégradés (`linear-gradient`, `radial-gradient`).
- Glow, grosses ombres molles en dehors des tokens d'élévation.
- **Emoji dans l'UI.**
- Visuel de marque reconstruit en CSS : **toujours la vraie image du logo Orange** (un carré
  orange plein avec un rectangle blanc horizontal dans sa partie basse, fourni comme fichier
  `orange-logo.png`), jamais un carré généré en CSS.
- **Liseré vertical orange** (`border-left`, `inset 3px 0 0`) comme marqueur d'état : interdit
  partout, jugé générique. Une seule barre orange visible par colonne.
- Focus-ring orange global.

### 3.9 Mouvement (règles de goût)

- **Jamais de rebond ni d'overshoot.** Les courbes du projet sont des décélérations pures.
- **Jamais de texte mis à l'échelle** : on recompose une phrase dans sa typographie d'arrivée,
  on ne la zoome pas.
- **Un seul temps orange animé par séquence.**
- Cascades de 30 à 40ms maximum. Budget d'une séquence complète : sous 500ms.
- **Sorties plus vives que les entrées** : sorties `--dur-fast` + `--ease-in` ;
  entrées `--dur` (`--dur-slow` pour une entrée de page) + `--ease-out`.
- Respecter `prefers-reduced-motion`.

---

## 4. LE SHELL : ARCHITECTURE D'ÉCRAN

L'application est une grille CSS à colonnes variables.

```
┌──────────┬───────────────────────────────────┬──────────────────────┐
│          │  MainTop (barre de titre 56px)    │                      │
│ Sidebar  ├───────────────────────────────────┤  Panneau DROIT       │
│ (redim.) │                                   │  (exclusif :         │
│          │  Conversation (fil scrollable)    │   Evidence Studio    │
│          │                                   │   OU Source Data)    │
│          │                                   │                      │
│          ├───────────────────────────────────┤                      │
│          │  Barre de prompt (épinglée)       │                      │
└──────────┴───────────────────────────────────┴──────────────────────┘
```

### 4.1 Colonne de gauche : Sidebar **[EXISTE]**

Deux layouts, **un seul composant monté** (la liste de conversations n'est jamais rechargée
au repli/dépli).

**Sidebar dépliée** (largeur redimensionnable par poignée) :
- Haut : logo Orange (vraie image) + `OWIsMind` + bouton de repli.
- Nav primaire (lignes cliquables, rayon `--r-sm`) :
  - `+ New conversation`
  - `Agents` (icône agents)
  - `Benchmark` (icône livre)
- Section `CONVERSATIONS` (micro-label) : liste paginée des conversations de l'utilisateur,
  chargement paresseux au scroll. États : `Loading conversations…` / `No conversation yet.` /
  `Failed to load history.` / `Loading…` (page suivante).
- Bas : `Help & support` (ouvre un menu : My account, FAQ) + puce utilisateur (avatar rond +
  prénom, ouvre un menu compte).

**Ligne sélectionnée** : surface `--surface-press` (un cran au-dessus du `--surface-hover` du
survol, et **conservée au survol de la ligne active**) + **title-bar orange 18x2px** tracée
depuis la gauche. Jamais de liseré vertical.

**Sidebar repliée = rail d'icônes 60px** : logo orange cliquable, `+`, agents, benchmark, puis
help et avatar épinglés en bas. Sur le rail, l'état actif est porté par le **glyphe orange**
(la title-bar ne tient pas dans 38px de haut).

**Flyout au survol** : poser le pointeur sur le rail ouvre la sidebar complète en **overlay
flottant** (`position: fixed`, au-dessus du contenu) : la grille ne se recompose pas. Elle se
rétracte quand le pointeur sort.

### 4.2 MainTop : barre de titre **[EXISTE]**

Hauteur 56px, alignée avec les en-têtes des panneaux (la hairline doit être continue d'un bord
à l'autre de l'écran).
- Gauche : titre contextuel (`New conversation`, ou le nom de la conversation, ou le titre de page).
  Quand la sidebar est repliée, un bouton d'expansion s'y ajoute.
- Droite : bascule thème (icône lune/soleil) + bascule langue (`EN`/`FR` avec icône globe).

### 4.3 Colonne de droite : panneau exclusif **[EXISTE]**

**Un seul des deux panneaux à la fois.** Ouvrir l'un ferme l'autre.

- **Evidence Studio** : largeur en pixels, poignée de redimensionnement à gauche.
- **Source Data** : largeur fractionnelle (compact = ~1/3 de l'écran, étendu = ~2/3),
  bascule par bouton + redimensionnement libre à la poignée (min 340px, et le chat garde
  toujours au moins 560px).

**Auto-repli de la sidebar** : quand le panneau droit devient gourmand (Evidence ouvert, ou
Source Data au-delà de 45% de la largeur de fenêtre), la sidebar se replie automatiquement
en rail. L'utilisateur peut la rouvrir : on ne la force jamais à se refermer ensuite, et ce
repli automatique n'est pas persisté.

**Auto-amarrage de Source Data** : sur l'écran d'arrivée (conversation vide) et si l'agent
sélectionné expose des datasets, le panneau Source Data est **ouvert d'office**, en mode
teaser flouté. L'utilisateur n'a pas à découvrir un bouton. S'il le ferme (X), il reste fermé
pour cet écran d'arrivée, mais le prochain nouvel écran d'arrivée le rouvre.

---

## 5. ÉCRAN CHAT

### 5.1 État "arrivée" (conversation vide) **[EXISTE]**

Composition en deux moitiés optiques : le bloc titre est poussé au bas de la moitié haute,
la carte de prompt juste en dessous, et une zone tampon équilibre le tout dessous. L'ensemble
titre + prompt lit comme un groupe centré.

- Titre : `What would you like to analyse today?` en **22px / 700** avec une title-bar orange
  **40x3px** dessous. **Il ne doit jamais peser plus que la barre de prompt**, qui est le sujet
  de l'écran.
- Sous-titre : `OWIsMind suggests a selection of agents - click for details or `
  **`browse the full library`** (lien souligné) `.`
- La carte de prompt, avec son aura orange.
- Sous la carte, en `--text-3` petit : `Generative AI models can make mistakes or invent answers.
  Stay critical of the responses provided.`
- À droite, le dock Source Data en teaser flouté (section 8.1).

### 5.2 La barre de prompt **[EXISTE]**

C'est **le contrôle primaire de l'application**. Carte élevée, rayon `--r-xl`, bordure hairline,
aura orange diffuse derrière l'élévation neutre. Elle existe en **un seul exemplaire** dans le
DOM et voyage de l'écran d'arrivée au bas du fil (voir 11.1).

De haut en bas dans la carte :

1. **Chip de contexte d'écran** (si une vue Source Data est active) - voir section 9.
2. **Chips de valeurs piochées** (si l'utilisateur a cliqué des cellules) : micro-label
   `Values for your next question`, une chip par valeur `Colonne = Valeur` avec un `x`,
   plus un lien `Clear`.
3. **Le textarea**, auto-grandissant (max 200px de haut) :
   `Describe your request as precisely as possible…`
4. **La rangée de contrôles** :
   - Gauche : **sélecteur d'agent** (pilule avec l'icône de l'agent, son nom, un chevron
     haut/bas ; le menu s'ouvre vers le haut) + **sélecteur de mode de réponse** (pilule
     `● Smart`, avec une pastille de coût, uniquement si l'agent supporte les modes).
   - Droite : indice clavier `↵ Enter to send` (visible seulement quand le champ est focalisé
     ET contient du texte), bouton micro, **bouton d'envoi** rond orange (flèche).

**États du bouton d'envoi** :
- Inactif (pas de texte, ou envoi impossible) : désactivé.
- Actif : rond orange plein, flèche blanche.
- **Pendant un run : le bouton devient un bouton STOP** (carré dans un rond). Cliquer coupe la
  génération, la réponse partielle est conservée.

**Clavier** : `Enter` envoie, `Shift+Enter` saute une ligne.

**Le micro n'a pas de backend de transcription** : il affiche un toast honnête. À maquetter comme
présent mais discret.

**Bandeaux au-dessus de la carte de prompt** (empilés dans cet ordre quand ils s'appliquent) :
- Bandeau d'impersonation (un admin regarde en tant qu'utilisateur) : icône users + phrase
  en lecture seule.
- **Bandeau de budget épuisé** : icône portefeuille + `Monthly budget reached ($50.00 of $50.00).
  New requests will be possible on 1 September (monthly reset).` L'envoi est bloqué.
- Message d'erreur de chargement de conversation ou d'envoi.

### 5.3 Le sélecteur de mode de réponse **[EXISTE]**

Une pilule dans la barre de prompt ouvre une **modale à deux volets** (inspirée du dialogue
"conversation settings" de Dataiku) :
- Volet gauche : les trois modes en liste cliquable.
  - **`Smart`** - marqué `Recommended`. `Low` cost, `Very fast`.
  - **`Pro`** - `Moderate` cost, `Fast`.
  - **`Claude`** - `High` cost, `More deliberate`.
- Volet droit : détail du mode sélectionné + deux **jauges 0..5** (Cost, Speed).
- Une ligne de recommandation : `Always start with Smart: fast, economical and already very good
  quality for the vast majority of your questions.`
- Pied : `Cancel` / `Apply`.

Sélection au **clic** (pas de survol qui recompose le dialogue).

### 5.4 Le fil de conversation **[EXISTE]**

Colonne centrée, largeur `90%` plafonnée à `1200px`. Un tour = une bulle utilisateur + un
message agent.

**Auto-scroll collant** : on suit le bas tant que l'utilisateur y est déjà. S'il remonte pour
lire pendant que ça streame, on **arrête de suivre** et on le laisse lire. Envoyer un nouveau
message ré-épingle en bas.

**Overlay de chargement** lors d'un changement de conversation : spinner centré + `Loading
conversation…`, par-dessus le fil courant (l'écran ne doit jamais clignoter en "nouvelle
conversation" avant l'arrivée des lignes).

### 5.5 Bulle utilisateur **[EXISTE]**

Bulle asymétrique arrondie, alignée à droite. Au survol, deux actions apparaissent :
`Copy` et `Edit`.

**Édition** : un textarea inline remplace le texte, avec un indice
`Enter for a new line · Esc to cancel` et des boutons `Cancel` / `Send`. Valider **crée une
nouvelle branche** (rien n'est supprimé : l'ancienne version reste accessible par les flèches
de version du message agent).

Sous la bulle, s'il y avait un contexte d'écran partagé : une ligne dépliable
`On-screen context shared with this message` (section 9).

### 5.6 Message agent : structure complète **[EXISTE]**

De haut en bas :

1. **Tête** : icône étincelle + `OWIsMind`.
2. **Carte de plan d'analyse** (si le run est un workflow durable) - section 6.4.
3. **Le flux** (`.stream`) : timeline live OU bloc d'activité replié + réponse - section 6.
4. **État "en cours sans rien émis"** : `running…` en texte atténué.
5. **Bandeau "arrêt en cours"** : spinner + `Stopping…` clignotant (le backend coupe
   coopérativement, entre deux chunks).
6. **Placeholder d'interruption** : `Response interrupted` si l'arrêt est survenu avant tout texte.
7. **Marqueur d'arrêt** : icône stop + `Generation stopped` sous une réponse partielle.
8. **Panneau SQL repliable** : `SQL (2)` avec chevron. Déplié : par requête, une ligne meta mono
   (`#1 · Success: true · Rows: 6`) puis le SQL en `<pre>` mono.
9. **Ligne d'usage** (mono, discrète) :
   `↑ 6,420 · ↓ 812 tokens · ~$0.0142 · Smart`
   (tokens entrée / sortie, coût estimé, mode utilisé).
10. **Pied d'actions** (seulement quand le run est terminé) :
    - `Copy` (icône copie)
    - **`Evidence`** (icône bouclier) - devient l'état primaire quand le panneau est ouvert
    - `👍` / `👎` (icônes pouce, pas d'emoji : glyphes SVG)
    - `⋯` menu : `Give detailed feedback`, `Suggest for the benchmark`
    - `Regenerate` (icône refresh)
    - **Navigation de versions** (si le tour a plusieurs branches) : `‹ 2/3 ›` en mono.

**Feedback** : cliquer 👍 enregistre immédiatement (pas de popup). Cliquer 👎 enregistre
immédiatement **puis** ouvre une modale de raisons. Re-cliquer un pouce actif l'annule.
Raisons proposées : `Incomplete response`, `Incorrect response`, `Off topic`, `Too long`,
`Too short`, `Wrong tone`, `Other` + un commentaire libre.
La modale est **adaptative** : sur un 👍 elle ne montre que le champ commentaire
("qu'est-ce qui vous a plu"), sur un 👎 elle montre les raisons + commentaire.

**Erreurs de run** : jamais le code machine. Les codes connus sont traduits
(`deadline_reached`, `run_abandoned`, `agent_unavailable`, `run_lost`), le reste tombe sur un
message générique. Rendu : une ligne encadrée de tirets, en `--danger`, à la place où l'erreur
est arrivée dans le flux.

---

## 6. L'AFFICHAGE DU RAISONNEMENT DE L'AGENT **[LE POINT CLÉ]**

C'est la partie la plus importante à maquetter. Voici exactement ce qui arrive et comment
c'est rendu aujourd'hui.

### 6.1 Le modèle de données

Le backend streame (par polling, toutes les 500ms) une suite d'**événements normalisés**.
Le frontend les réduit en **une seule liste chronologique** où chaque élément apparaît
exactement là où il est arrivé, et où on n'ajoute jamais qu'en bas.

Types d'éléments dans cette liste :

| Type | Contenu | Rendu |
|---|---|---|
| `event` | une étape de raisonnement/outil : `eventKind`, `label` humain optionnel, `toolName`, `blockId`, `elapsedSeconds`, `status: running\|done` | une ligne d'étape |
| `text` | un morceau de réponse en markdown (les deltas consécutifs fusionnent en un seul bloc) | un bloc de réponse rendu |
| `narration` | un message transitoire "voilà ce que je fais" | **non affiché** (voir 6.5) |
| `error` | une erreur | une ligne d'erreur en place |

À côté de la liste, l'état porte aussi : `sql[]` (les requêtes capturées), `usage`
(tokens/coût), `status` (`running` / `done` / `stopped` / `error`), `plan` (le plan durable),
`mode`, et le contexte d'écran partagé.

**Point structurant** : le SQL et les traces techniques ne sont **jamais** dans la timeline.
Le SQL a son panneau repliable, la trace brute n'est jamais envoyée au front.

### 6.2 Les `eventKind` et leurs libellés humains

Le backend envoie un code technique. Le frontend le mappe sur un libellé humain + une icône.
**Si l'orchestrateur fournit un `label` métier, ce label gagne** (l'orchestrateur connaît mieux
la formulation métier qu'une table statique) : l'icône, elle, reste résolue depuis le code.

| eventKind | Libellé EN | Libellé FR | Icône |
|---|---|---|---|
| `START` | Starting | Démarrage | sparkles |
| `AGENT_TURN_START` | Parsing the request | Analyse de la demande | sparkles |
| `PLANNING` / `AGENT_PLANNING` | Planning | Planification | sliders |
| `PLAN_READY` | Plan ready | Plan établi | check |
| `AGENT_THINKING` | Reasoning | Raisonnement | sparkle |
| `AGENT_BLOCK_START` | Composing the answer | Composition de la réponse | layers |
| `AGENT_BLOCK_END` | Block complete | Bloc terminé | check |
| `CALLING_AGENT` | Calling an agent | Appel d'un agent | route |
| `AGENT_DONE` | Agent complete | Agent terminé | check |
| `RUNNING_TOOL` / `AGENT_TOOL_START` | Running a tool / Calling a tool | Exécution d'un outil | route |
| `TOOL_DONE` / `AGENT_TOOL_END` | Tool complete | Outil terminé | check |
| `DIRECT_ANSWER` | Direct answer | Réponse directe | sparkle |
| `WRITING_ANSWER` | Writing the answer | Rédaction de la réponse | sparkle |
| `ESCALATING` | Switching to a more powerful model | Passage à un modèle plus puissant | sparkles |
| `AGENT_TURN_END` | Turn complete | Tour terminé | check |
| `DONE` | Done | Terminé | check |

Codes inconnus : humanisés automatiquement (`AGENT_CUSTOM_PHASE` -> `Custom phase`), sinon
libellé générique `Step`. **L'UI ne doit jamais casser sur un code inconnu.**

**Sous-agents** : un `eventKind` préfixé `SUB_AGENT_*` signifie que l'orchestrateur est descendu
d'un niveau dans un agent spécialiste. Ces lignes sont rendues **indentées**, pour que la timeline
montre visuellement la descente.

**Exemple de séquence réelle** (question "compare revenus réels et budget 2026 par solution") :

```
0.2s  START            "Analyse de la demande"
1.1s  CALLING_AGENT    "Consultation de l'expert revenus"
2.4s  RUNNING_TOOL     "Génération du SQL par le modèle sémantique"  [tool: semantic-model-query]
3.8s  AGENT_DONE       "Expert revenus : résultat obtenu"
4.1s  ARTIFACT         "Graphique : Actuals vs Budget par solution"
4.3s  WRITING_ANSWER   "Rédaction de la réponse"
      -> deltas de réponse markdown (avec un tableau)
      -> usage_summary : 6420 prompt / 812 completion / $0.0142
      -> final_answer, run_done
```

### 6.3 Deux rendus : LIVE et TERMINAL **[EXISTE]**

C'est le mécanisme central. **La donnée reste chronologique** ; seul le regroupement à l'écran change.

**Pendant le run (LIVE)** : la timeline est découpée en **segments**. Les événements consécutifs
forment un groupe, et un bloc de texte reste **à sa place entre deux groupes**. Un orchestrateur
qui répond en cours de route montre donc sa réponse partielle **entre deux phases**, avec la
phase suivante qui tourne en dessous.

Chaque groupe d'événements est un **ticker borné** :
- **5 lignes maximum visibles**. Les lignes plus anciennes sont évincées et **s'effacent en fondu
  sous un masque en haut du groupe**.
- Ligne d'étape = un indicateur + le libellé + un sous-libellé optionnel (`toolName` ou `blockId`)
  + une **durée en mono à droite**.
- **L'étape en cours** : indicateur gris avec un **shimmer qui la traverse**, et un chronomètre
  qui tourne au centième de seconde (`4.28s`), largeur stable (mono, pas de tremblement).
- **Une étape terminée** : indicateur **orange**, durée figée.
- Une seule étape est "en cours" à la fois : dès que quoi que ce soit arrive après elle, elle est
  scellée.

**À la fin du run (TERMINAL)** : tous les événements se **regroupent en une seule ligne d'en-tête
repliée**, au-dessus de la réponse complète :

```
▸  ●  Steps                                     6 steps · 4.3s        ⌄
```

Cliquer déplie la liste complète des étapes (mêmes lignes, sans shimmer). Le repli est
CSS-only (`grid-template-rows: 0fr -> 1fr` + opacité). La durée totale = le **max** des stamps
`elapsedSeconds` (ce sont des stamps depuis le début du run, jamais une somme).

**Les durées** : quand le backend fournit des stamps, la durée d'une étape = l'écart avec le stamp
de l'étape suivante (c'est la vérité, immune à l'éviction du ticker et à la granularité du polling).
Sinon on retombe sur l'horloge client. Si on ne peut rien dire : **on n'affiche rien** plutôt
qu'inventer.

### 6.4 La carte de plan d'analyse (workflow durable) **[EXISTE]**

Quand le run est un workflow durable, un `PLAN_READY` fait apparaître une carte **au-dessus de
la timeline**, et ses étapes s'allument en direct :

```
┌────────────────────────────────────────────────┐
│ ANALYSIS PLAN                            2 / 5 │  (micro-label + compteur mono)
├────────────────────────────────────────────────┤
│ Comparer revenus réels et budget 2026          │  (le but, en --text-2)
│ ▪ Identifier le périmètre         Done         │
│ ▪ Interroger le modèle revenus    Done         │
│ ▪ Calculer les écarts             Running      │  <- SEULE ligne orange
│ ▫ Construire le graphique         Pending      │
│ ▫ Rédiger la synthèse             Pending      │
└────────────────────────────────────────────────┘
```

- Carte carrée, 1px `--border-strong`.
- Marqueur = un **carré plein 10x10**, jamais un rond ni un halo. Le remplissage est transitionné,
  pour qu'une étape qui bascule lise comme un état **qui change**, pas comme un repeint.
- Statuts : `Pending` / `Running` (**le seul accent orange de la carte**) / `Retrying` (warn) /
  `Done` (marqueur `--text`, titre en `--text-2`) / `Failed` (danger) / `Superseded` (barré, `--text-3`).
- Max 12 étapes.

### 6.5 Ce qu'on a retiré (à ne PAS réintroduire)

- **La narration** (`"Je confie la question à l'expert revenus…"`) est reçue mais **plus affichée** :
  elle doublonnait les libellés d'étapes (une ligne grise par phase EN PLUS d'une ligne orange),
  et surtout elle cassait le ticker en micro-groupes, ce qui neutralisait la fenêtre de 5 lignes.
  L'amorce du modèle apparaît quand même : elle arrive comme du **texte** de réponse, pas comme
  de la narration.
- **Le lien "Check this number"** sous une réponse : supprimé, doublon du bouton Evidence.

### 6.6 [À EXPLORER] Points ouverts sur la timeline

- Le ticker à 5 lignes avec masque de fondu est fonctionnel, mais la **densité visuelle**
  d'un run long (15+ étapes avec des sous-agents indentés) mériterait une passe.
- L'indentation des sous-agents est aujourd'hui un simple décalage. **Comment montrer une
  hiérarchie orchestrateur -> sous-agent -> outil de façon lisible sans faire un arbre lourd ?**
- Faut-il un mode "debug" qui montre les `eventKind` techniques (prévu au cadrage, jamais fait) ?
- Comment articuler visuellement **la carte de plan** (le prévu) et **la timeline** (le réalisé)
  quand les deux coexistent ? Aujourd'hui ils sont simplement empilés.

---

## 7. EVIDENCE STUDIO (panneau de droite)

### 7.1 Rôle

Répondre à "**pourquoi je peux faire confiance à cette réponse ?**". S'ouvre depuis le bouton
`Evidence` sous une réponse, ou automatiquement en fin de run quand une preuve est disponible.

En-tête : icône bouclier + `Evidence Studio` + le nom du dataset en mono + bouton de fermeture.

### 7.2 Les onglets **[EXISTE]**

Ordre de lecture : **la preuve d'abord, puis les artefacts rendus, puis l'exploration**.

| Onglet | Quand il apparaît |
|---|---|
| `Evidence` | toujours |
| `KPI` | si le tour a produit un artefact KPI |
| `Chart` | si le tour a produit un ou plusieurs graphiques |
| `Table` | si le tour a produit un artefact tableau |
| `Source data` | si la vue interactive est disponible OU si l'agent expose des datasets |

La barre d'onglets ne s'affiche que s'il y a plus d'un onglet.

### 7.3 Onglet `Evidence` : la preuve **[EXISTE]**

Sections empilées, dans cet ordre :

**a) Badge de confiance** - la première chose que lit un non-technicien : une pilule + une
phrase en langage courant. **Jamais de vert.**

| Niveau | Libellé | Style | Phrase |
|---|---|---|---|
| calcul décomposé + résultat capturé | `Certified result` | **orange plein** | `The computation is decomposed step by step and the exact result the agent used was kept.` |
| calcul décomposé, ou périmètre exact | `Certified source` | **orange plein** | `The exact dataset and filters behind this query are known. The rows below are read live from the database: if the data changed since the answer, they show today's state.` |
| périmètre partiel, ou source identifiée | `Partial proof` | **orange pointillé** | `Only part of the scope could be reproduced - anything not reproduced is listed, never hidden.` |
| rien de vérifiable | `Agent claim` | **gris atténué** | `Agent claim: this query could not be verified automatically.` |

Sur `Partial proof`, on liste explicitement ce qui n'a pas pu être reproduit :
`{n} element(s) not reproduced`. **On ne cache jamais un élément non reproduit.**

**b) `Data source`** : le dataset en question, avec un lien optionnel `Open the dataset in Dataiku`,
plus une mention honnête `+2 more quer(y/ies) run` si la réponse a exécuté plusieurs requêtes.

**c) `How this result is computed`** : le calcul décomposé en **liste numérotée de phrases métier**,
sans jargon SQL. Maximum 15 étapes. Exemples de phrases réelles :
```
1. Source: DRIVE Revenues
2. Filter: Year = 2026
3. Filter: Phase among ACTUAL, BUDGET (2 values)
4. Group by Solution
5. Sum Revenues
6. Compute the difference between actual_revenue and budget_revenue
7. Sort by actual_revenue (descending)
```
Opérations couvertes : filtres (=, ≠, >, ≥, <, ≤, IN, NOT IN, BETWEEN, IS NULL, LIKE), jointures,
group by, distinct, agrégations (sum/avg/min/max/count/count distinct/agrégat filtré),
ratios/pourcentages/différences/parts, fenêtres (rank, row_number, cumul, comparaison ligne
précédente), HAVING, tri, top N, limite arbitraire, étapes intermédiaires (CTE), union.
Ce qui n'est pas interprété tombe sur `Operation not interpreted: {…}`.
**Si le backend n'a produit aucune étape, la section entière disparaît** (une section "comment"
vide éroderait la confiance).

**d) `Result used by the agent`** : les **lignes exactes** que l'agent a reçues, en mini-table
sobre et bornée (pas de tri, pas de pagination : c'est une preuve, pas un navigateur de données),
avec le nombre total de lignes `{n} row(s)`.
- Si le backend a certifié le drill-down fiable, chaque ligne porte un **chevron**
  `See the source rows behind this result`. Cliquer bascule sur un bandeau
  `Source rows: Solution = Roaming Sponsor` avec un retour `Back to the result`.
- Si rien n'a été capturé, une seule ligne honnête :
  `The exact result the agent used was not kept for this answer.`
- Si tronqué : `Result truncated - first rows only.`

**e) Chips de filtres** : le `WHERE` de la requête décomposé en chips.
- **Toute chip de valeur est éditable** via un sélecteur de valeurs distinctes. Éditer une chip
  de comparaison (`period >= '2025-01'`) la convertit en `=` / `IN` des valeurs choisies.
- Toute chip est supprimable. Le fragment "condition avancée" est **une chip supprimable en bloc**.
- Une chip `+ Add a filter` (bordure **pointillée**) ouvre un flux en deux temps :
  liste de colonnes recherchable -> sélecteur de valeurs.
- Un bouton `Agent version` remet l'état d'origine de l'agent.
- Grammaire visuelle : chip de valeur = bordure pleine ; avancé/ajout = **pointillé** ;
  état modifié = **badge orange pointillé** + une mention `Filters modified`.

**f) Table de lignes live** : les lignes réelles de la table source sous les filtres (ceux de
l'agent, ou modifiés par l'utilisateur). En-tête collant, tri au clic, scroll vertical **et**
horizontal, **chargement paresseux infini** (une fenêtre, puis la suivante quand la sentinelle
du bas entre dans le viewport). Fenêtrage des colonnes côté client (on rend les N premières,
puis on en révèle plus au scroll horizontal). Compteurs : `{n} row(s) loaded`,
`{visible} / {total} columns`, `Scroll to load more`.

**g) Pied SQL repliable** : `Technical details (SQL)` - la requête exacte de l'agent,
**pretty-printée avec une coloration syntaxique légère**, plus un bouton `Copy SQL` (qui copie
la requête exécutée verbatim, pas la version reformatée).

### 7.4 Mode dégradé **[EXISTE]**

Quand aucune requête n'a pu être capturée, l'onglet Evidence montre le badge `Agent claim` puis
la raison, formulée honnêtement :
- `The table the agent queried maps to no SQL dataset in this project - the interactive view is
  unavailable. Here is the exact query the agent ran.`
- `This answer produced no usable SQL query - nothing to visualize.`

**Mais l'onglet `Source data` reste accessible** dès que l'agent expose des datasets : explorer
la donnée n'a jamais eu besoin d'une requête capturée.

### 7.5 Onglets d'artefacts **[EXISTE]**

- **`KPI`** : une ou plusieurs cartes "chiffre héros". Grande valeur formatée selon la locale
  (compacte au-delà du million : `1.2M` / `1,2 M`), plus un delta optionnel avec flèche
  (haut vert / bas rouge) et un pourcentage. Les valeurs sont extraites **côté serveur** :
  la carte ne fait que formater.
- **`Chart`** : graphiques interactifs (Chart.js). Types : barres, barres groupées, lignes,
  empilé. Tooltips au survol, **légende cliquable** (masquer/afficher une série), animation
  d'entrée, redimensionnement responsive. Les données arrivent prêtes du serveur
  (`{labels, datasets}`). Plusieurs graphiques s'empilent dans l'onglet.
  Titre auto : `{mesure} by {dimension}`. Vide : `Cannot render the chart for this data.`
  Tronqué : `Data truncated - first values only.`
  **Attention** : un canvas ne peut pas lire les variables CSS. Les couleurs d'axes et de grille
  doivent être résolues au moment du dessin depuis `<body>` (sinon un graphique en thème sombre
  garde des axes de thème clair).
- **`Table`** : la table complète du résultat capturé, scrollable. C'est **la donnée exacte reçue
  par l'agent**, distincte de la table de lignes live (qui, elle, re-requête la source).

### 7.6 Onglet `Source data` **[EXISTE]**

Fusionne dans **un seul sélecteur** :
- les tables **détectées** dans l'échange (portée exacte du SQL, chips de l'agent, drill),
- les datasets **configurés** sur l'agent qui ne sont pas déjà détectés (exploration libre).

Les entrées détectées viennent en premier. Le sélecteur disparaît s'il n'y a qu'une entrée.
Le corps est exactement le même workspace que la section 8 (une seule structure à maintenir).

### 7.7 États du panneau **[EXISTE]**

- **Chargement** : squelette shimmer **de la forme du contenu à venir** (bandeau de confiance,
  rangée de chips, bloc de table), pas une ligne de texte.
- **Erreur** : `Could not load the evidence.` + `Retry`.
- **Vide** : voir mode dégradé.

---

## 8. SOURCE DATA (exploration de données)

C'est le deuxième grand panneau droit. Il donne accès aux **datasets configurés sur l'agent**,
à côté du chat, avant même d'avoir posé une question.

### 8.1 Le teaser auto-amarré **[EXISTE]**

Sur l'écran d'arrivée, le dock est ouvert d'office et son contenu (une vraie table de données)
est **flouté (~3px)** derrière une carte d'invite centrée :

```
        ┌──────────────────────────────┐
        │            ▤                 │
        │      Explore the data        │
        │  Click to expand and work    │
        │  with this agent's source    │
        │            data.             │
        └──────────────────────────────┘
```

Le survol éclaircit légèrement le voile. **Le clic engage** : le flou disparaît, le panneau
devient pleinement interactif. Un `X` referme le dock (pour cet écran d'arrivée seulement).

C'est le **seul** usage autorisé du flou dans toute l'application.

### 8.2 En-tête et topbar **[EXISTE]**

En-tête du panneau (56px, aligné avec MainTop) :
`▤ SOURCE DATA` (micro-label) · nom de l'agent tronqué · **bascule `Data | Analyze`**
(contrôle segmenté) · bouton étendre/rétrécir (`«` / `»`) · fermer (`X`).

Sous l'en-tête, **une seule ligne** :
- Pilule `DATASET [▤] <select natif>` (composant partagé avec l'onglet Evidence).
  Select natif volontairement : il ne peut jamais être coupé par un panneau qui scrolle,
  il lit avec l'OS de l'utilisateur, et il passe à l'échelle. **Encre neutre** : le contrôle
  affiche toujours le dataset actif, un orange permanent casserait la règle de l'accent rare.
- Champ de recherche **qui nomme le dataset qu'il cherche** : `Search in DRIVE Revenues…`,
  avec un bouton loupe. Validation à `Enter` ou au bouton.
  Indice : `Type at least 2 characters to search.`

Puis **une seule ligne de filtres** : micro-label `FILTERS` + les chips + `+ Add a filter`
+ `Clear all` (pilule bordée). Les éléments glissent ensemble.

### 8.3 Vue `Data` : parcourir les lignes **[EXISTE]**

Une table pleine largeur. En-tête collant, **tri au clic** (3 états : asc / desc / aucun),
scroll vertical et horizontal, **chargement paresseux infini**.

**Menu de colonne** (icône au survol de l'en-tête) : `Sort ascending` / `Sort descending` /
`Remove sort` (coche sur la direction active) + `Filter values...` qui ouvre le sélecteur
pré-réglé sur cette colonne.

**Clic sur une cellule** -> un petit popover ancré :
```
┌────────────────────────────────┐
│ SOLUTION                       │  (micro-label = la colonne)
│ Roaming Sponsor                │  (la valeur complète)
│ ─────────────────────────────  │
│ ▸ Use for my next question     │  (action primaire)
│ ▸ Filter on this value         │
└────────────────────────────────┘
```
- `Use for my next question` empile la valeur en chip dans la barre de prompt.
- `Filter on this value` ajoute un filtre d'égalité et **recalcule toute la portée**.
- Retours possibles : `Value added to your next question`, `Value already selected`,
  `Limit of {n} values reached`, `Value too long to send to the agent`, `Filter applied`,
  `Value already filtered`, `Filter full ({n} values max)`.

**Ces actions de cellule existent AUSSI dans la vue Analyze** (sur la table d'aperçu sous les
chiffres) : l'analyse et les lignes en dessous partagent un seul état de filtres, donc un filtre
posé sur une cellule recalcule les chiffres au-dessus.

**Affordances de scroll** (`ScrollHints`) : une table large coupe ses colonnes au bord et une
table longue coupe ses lignes en bas, sans que rien à l'écran ne le dise. Des pilules
superposées **le disent** (`+7 columns →`, `more rows ↓`) et **le font** (un clic scrolle
jusque-là). La couche est click-through sauf sur les pilules, et passe sous les menus ouverts.
Ces pilules sont partagées par les trois tables (source, evidence, artefact) : une seule langue.

**États** : `Loading…` / `Could not load the data.` + `Retry` / `No row matches.` /
`{n} row(s) loaded` / `Scroll to load more` / `{visible} / {total} columns`.
Pendant un calcul lourd : `Digging through the data…`.

### 8.4 Vue `Analyze` : le workspace de calcul **[EXISTE]**

**Une seule place, un seul modèle, pour tout calcul sur le dataset actif.** (Cette vue a
remplacé deux systèmes concurrents qui coexistaient : une zone "Calculate" et un pivot.)

Le constructeur se lit **comme une phrase** :

```
Measure [Sum of Revenues ×] [Row count ×] (+ Add)     by  [Solution ▾]
        └─── chips de mesures, 1 à 8 ────┘                └ groupe ┘
```
ou, sans groupement :
```
Measure [Sum of Revenues ×] (+ Add)                    for [All filtered rows]
```

- **La mesure par défaut n'est jamais vide** : c'est la **somme de la première colonne numérique
  de quantité** du dataset. Pas un nombre de lignes : le compte est déjà affiché sous le dataset
  et re-affirmé par chaque filtre, une mesure "row count" par défaut passerait toute la surface
  de résultat à répéter ce qui est déjà à l'écran. Les numériques en forme d'identifiant
  (un id de compte, une année) sont exclus : les sommer n'a aucun sens. Seul un dataset
  purement textuel retombe sur `Row count`.
  La mesure par défaut est marquée "pristine" tant que l'utilisateur n'y a pas touché.
- `+ Add` ouvre un **sélecteur de mesures** listant chaque paire (fonction, colonne) calculable :
  numérique -> `Sum of X` / `Average of X` / `Median of X` / `Min of X` / `Max of X` ;
  temporel -> `Min of X` / `Max of X` ; identifiant ou autre -> `Distinct values of X` ;
  plus `Row count` qui ne demande aucune colonne.
  Une paire déjà présente est affichée **désactivée, pas masquée** : la réponse à "pourquoi je
  ne peux pas la rajouter" doit être à l'écran.
- Le groupement accepte une colonne, et pour une colonne temporelle un **bucket** :
  `Month` / `Calendar quarter` / `Year`.

**Surface de résultat, adaptative** :
- **Sans groupement** -> des **cartes KPI**, une par mesure.
- **Avec groupement** -> une **table à barres**, une colonne par mesure.
  L'échelle des barres est calculée **par mesure** (jamais une échelle commune qui écraserait
  une mesure petite), et les **valeurs négatives sont honnêtes** (barre dans l'autre sens).

**Troncature honnête** : `Top 50 by Sum of Revenues` ou `Last 50 periods`, jamais un silence.
`Groups ranked by this measure` indique quelle mesure ordonne le classement.
Valeur manquante d'un groupe : `Missing value` (pas une case vide).

**Sous le résultat, pleine largeur : les lignes d'où viennent les chiffres.**
`The data being analyzed` + `{n} shown / {total} filtered`, avec les **colonnes analysées
épinglées en premier** (badge `Analyzed column`). Aperçu borné à 50 lignes, en-têtes statiques,
pas de chargement paresseux (ce serait déclencher une requête depuis une surface qui ne répond
qu'à une question : "qu'est-ce que j'analyse ?"). Repliable / dépliable.

**Tout est calculé en base**, sur l'ensemble filtré complet - jamais sur la fenêtre visible.

Le même workspace sert dans **deux hôtes** : le panneau autonome et l'onglet Evidence
`Source data`. Une seule structure à maintenir.

### 8.5 Le sélecteur de valeurs (partagé Evidence + Source) **[EXISTE]**

Flux en deux temps :
1. **Liste de colonnes** recherchable (`Search columns…`, `No matching column.`).
2. **Liste de valeurs** avec cases à cocher (`Filter values…`), recherche côté client sur la
   fenêtre chargée, qui **escalade en recherche serveur sur `Enter`** quand la liste est tronquée.
   Indices : `Enter: search all values`, `Values filtered by your search. Enter (empty field):
   show all again`, `First {n} distinct values`, `At most {n} values per filter`,
   `{n} selected`, `No matching value.`
   Pied : `Cancel` / `Apply`. Retour : `Columns`.
   Erreur : `Search is unavailable right now. Try again.`

Pour une colonne temporelle, une bascule `Pick exact values` / `Filter by range` donne deux
champs `YYYY-MM` (`From` / `To`) + un remplissage `Full year` en un clic. La chip résultante
se lit `2026-01 to 2026-12`.

**Piège technique à connaître** : ces popovers sont "téléportés" dans le body en
`position: fixed`, parce que les panneaux clippent leur propre overflow. Ils se ferment au clic
extérieur, à `Escape`, **et au scroll de n'importe quel ancêtre**. Leurs coordonnées sont
bornées pour ne jamais déborder du viewport.

### 8.6 [À EXPLORER] Points ouverts sur Source Data

- Le **bloc de contexte de la vue Analyze est mono-mesure** : quand plusieurs mesures sont
  affichées, le contexte envoyé à l'agent n'en décrit qu'une. Le rendre multi-mesures demande
  une évolution du backend. **Comment l'exprimer visuellement en attendant ?**
- La bascule `Data | Analyze` vit dans l'en-tête du panneau autonome mais **inline** dans
  l'onglet Evidence (qui n'a pas cet en-tête). Deux positions pour un même contrôle.
- L'export (CSV, presse-papier) n'existe pas et est régulièrement demandé.

---

## 9. LE CONTEXTE D'ÉCRAN PARTAGÉ **[EXISTE]**

Fonction inhabituelle et importante : **l'agent voit ce que l'utilisateur regarde**.

Quand l'utilisateur a façonné une vue Source Data (un dataset, des filtres, une recherche, des
chiffres calculés en base, un découpage), cette vue est **attachée par défaut** au prochain
message. Il n'y a pas d'étape de consentement.

**Dans la barre de prompt** : une chip vivante
```
[ ▤ Context: DRIVE Revenues  ⌄ ]  [ × ]
```
- Cliquer ouvre un **popover d'aperçu qui montre EXACTEMENT ce qui partira** (rien de caché).
- Le `×` retire le contexte. L'opt-out est **collant pour cette vue précise** : dès que
  l'utilisateur change un filtre, le contexte est ré-inclus automatiquement.
- Après un opt-out, une ligne discrète propose de ré-inclure :
  `On-screen context excluded` + bouton `Include`.

**Contenu du détail** (liste de type `dl`, libellés traduits, valeurs verbatim) :
```
Dataset      DRIVE Revenues
Agent        OWIsMind
Filter       Year = 2026
Filter       Phase among ACTUAL, BUDGET (+2 more)
Search       roaming
Rows (DB count)  1,284
Breakdown    Sum of Revenues by Solution (top 50 shown)
Calculation  Sum(Revenues) = 25,148,302
Drill        Solution = Roaming Sponsor
```

**Sous la bulle utilisateur** : une fois le message envoyé, la même liste est consultable via
`On-screen context shared with this message` (dépliable). Transparence totale, avant et après.

---

## 10. PAGES SECONDAIRES

Toutes partagent un **shell de page** : une seule zone de scroll interne, une colonne de contenu
centrée, et un en-tête standard **eyebrow (orange, MAJ) + H1 36px/800 + title-bar orange 52x4px
+ description** en `--text-2` ~15px.

### 10.1 `Agents` - bibliothèque **[EXISTE]**

Liste + détail dans une seule vue, commutée par un paramètre d'URL.

- En-tête : eyebrow `LIBRARY`, H1 `Available agents`, description
  `The OWI agents deployed on Dataiku DSS. Click an agent to see its documentation and start a
  conversation.`
- **Grille de cartes d'agent** : carte carrée, hover = bordure `--text` ; tuile d'icône carrée
  à glyphe orange ; nom ; accroche en `--orange-text` ; badge optionnel
  (`default` / `beta` / `restricted` / `offline`) ; pied = compteur `{n} tools` + chevron.
- **Vue détail** : retour `Back to agents`, héros (tuile d'icône 56px + nom + accroche),
  description, section `Capabilities` (liste), section `Exposed tools` (liste),
  CTA primaire `New conversation with {agent}`.
- **Zéro contenu codé en dur** : tout vient du profil rédigé par un admin. Un agent dont le
  profil n'est pas rempli montre une carte **minimale et honnête**, jamais des capacités inventées.
- Un bouton renvoie vers `Request an agent` (page Help & Support).

### 10.2 `My account` (Settings) **[EXISTE]**

Cartes empilées, **uniquement ce que le backend fournit réellement** :
- **Profile** : nom d'affichage, identifiant Dataiku, groupes réels. Le bouton "modifier le
  profil" est **désactivé avec la mention `Soon`** (il n'y a pas de route pour ça).
  Pas d'email inventé, pas de rôle inventé.
- **Theme** : contrôle segmenté clair / sombre.
- **Language** : select natif.
- **Monthly budget** (données réelles) : dépensé / limite / restant / date de réinitialisation,
  avec la **provenance de la limite** énoncée : `Monthly limit: $50.00 (default).` ou
  `(temporary increase until 30 September).` ou `(allocated by an administrator).`
  Seuils au cadrage : 50% info, 80% warning, 100% blocage.
  Sans limite : `Usage tracking active. No monthly limit currently enforced.`
- **Usage** : tokens et dépense du mois + compteurs cumulés.
- **Agent context window** : combien de messages passés sont rejoués à l'agent
  (min 10, max 50, défaut 20).

### 10.3 `Help & Support` **[EXISTE]**

Deux onglets sur une page (lien profond par `?tab=`) :

**a) `General feedback`** : catégorie + conversation liée (optionnelle) + message, plus un
historique `Your requests` avec pastille de statut et la réponse de l'admin quand elle existe.
- Catégories : `Bug`, `Wrong answer`, `Feature request`, `UI / UX issue`, `Performance issue`,
  `Data issue`, `Agent routing issue`.
- Statuts : `Pending`, `Reviewed`, `In progress`, `Resolved`, `Need more info`.

**b) `Request an agent`** : formulaire guidé en trois étapes -
`DSS project` -> `SQL tables` (de ce projet) -> `Your need`
(`Business case (required)`, `Use cases (optional)`, `Importance / urgency (optional)`).
Les sélecteurs de projet et de tables sont **live** (catalogue backend) et **retombent
automatiquement en saisie manuelle** quand le catalogue est indisponible ou vide
(`No project detected automatically. Enter the DSS project key.` /
`Catalog unavailable. Enter table names (one per line).`).
Historique `My requests` avec `Team response`.

### 10.4 `FAQ` **[EXISTE]**

Contenu statique bilingue en accordéons natifs (`<details>`), plus une **recherche client**
qui filtre sur la question ET la réponse dans la langue courante.
Catégories prévues : General, Agents, Data & Evidence, Charts, SQL & Trace, Budget,
Privacy & Usage, Troubleshooting.

### 10.5 `Benchmark` (tous les utilisateurs) **[EXISTE]**

Trois zones empilées sur une page :
1. **Consultation** (par défaut) : choisir un agent, lire son dernier run sous forme de
   **donut de confiance** + verdict héros + tuiles KPI + table par configuration + barres par
   catégorie + table question par question avec lignes dépliables. Un sélecteur permet de
   naviguer entre les runs passés. États explicites : non configuré / erreur de lecture / vide.
2. **Revue admin** (admins seulement) : les mêmes lignes gagnent
   `Mark correct` / `Mark incorrect` / `Clear override` + un commentaire.
3. **Suggérer** (sous-section repliable) : proposer une "golden question" au benchmark,
   soit manuellement, soit **pré-remplie depuis une réponse de chat** (via le menu `⋯` d'un
   message). S'ouvre automatiquement quand on arrive depuis le chat.

C'est la vue la plus dense de l'app (2800 lignes de code) et **elle mérite une passe de design
à part entière**.

### 10.6 `Admin` (route gardée) **[EXISTE]**

Console à onglets, **seulement ce qui a un backend réel** :
- **Storage** : état de la connexion SQL.
- **Agents** : whitelist d'agents activés + **éditeur de profil** en modale
  (accroche / description / capacités / outils / icône / badge / datasets sources).
  Ce profil est la source unique des cartes de la bibliothèque d'agents.
- **Users** : liste + drapeau admin.
- **Budgets** : budget global et par utilisateur.
- Le **flux d'activité n'a pas de backend** : état vide explicite, **jamais de faux KPI**.

### 10.7 `AuthGate` - non connecté **[EXISTE]**

Écran plein, seule chose rendue quand l'identité renvoie un 401. Pas de navigation, pas de shell.
Vrai logo, eyebrow + H1 lourd + title-bar orange, géométrie carrée, surfaces plates.
Garde une bascule langue (EN/FR) et une bascule thème, pour que l'utilisateur puisse lire le
message dans sa langue avant de recharger.

### 10.8 Pages "à venir" **[EXISTE]**

`Release notes`, `Accessibility`, `Terms of use`, `Personal data`, `About OWIsMind`, et la page
Projet : un état honnête `Coming soon` dans un cadre **pointillé** (rien n'y est interactif),
avec tuile d'icône carrée. Jamais de faux contenu.

---

## 11. MICRO-INTERACTIONS

### 11.1 "La passation" : l'envoi du premier message **[EXISTE, à raffiner]**

Quand l'écran d'arrivée devient un fil de travail, **l'écran ne coupe pas, il passe la main** :
- Le titre part (sorti du flux et animé, ce qui permet à la carte de prompt de mesurer sa
  position d'arrivée réelle).
- La phrase tapée **se recompose dans sa bulle** (jamais mise à l'échelle).
- La carte de prompt **descend et se pose** au pied du fil. C'est **le même noeud DOM** qui
  voyage (une duplication détruirait le focus et rendrait l'animation impossible).
- Un seul temps orange animé : la title-bar qui se referme.
- **Au premier message seulement.** À partir du deuxième, l'entrée de message standard suffit.
- L'animation est jouée **après** l'envoi, ne bloque jamais la saisie ni la requête, et est
  annulable à tout moment (changement de conversation, quota refusé, départ de la vue).
- Budget total sous 500ms.

### 11.2 Toasts **[EXISTE]**

Coin d'écran, carrés, avec icône + ton (`ok`, `warn`, `alert`). Exemples : `Copied`,
`Couldn't copy`, `Feedback sent, thank you!`, `SQL copied`, `Filter applied`.
Fallback de copie quand le presse-papier est inaccessible : on sélectionne le texte et on dit
`The clipboard isn't accessible here. The text is selected - press Ctrl/⌘ + C to copy.`

### 11.3 Menus et popovers **[EXISTE]**

Fermeture au clic extérieur et à `Escape`. Les popovers ancrés (cellule, colonne, mesures)
sont bornés au viewport et **se ferment au scroll de tout ancêtre**.

### 11.4 Squelettes de chargement **[EXISTE]**

Toujours **de la forme du contenu à venir**, jamais une ligne de texte générique.

---

## 12. DONNÉES POUR LA MAQUETTE

Utilise ces données : elles sont réalistes, synthétiques et cohérentes avec l'app.

### Dataset 1 : `DRIVE Revenues` (~640 lignes)

| Colonne | Type |
|---|---|
| `diamond_id` | bigint |
| `Account_name` | string |
| `carrier_code` | string |
| `Country` | string |
| `Product` | string |
| `Solution` | string |
| `SolutionLine` | string |
| `Phase` | string |
| `Year` | bigint |
| `Month` | bigint |
| `Snapshot_date` | date |
| `Revenues` | double |

Comptes : `Global Telecom Partners` (GTP, Germany), `Nordic Carrier AB` (NCA, Sweden),
`Iberia Connect SA` (IBC, Spain), `Pacific Wholesale Ltd` (PWL, Australia),
`Atlantic Networks Inc` (ANI, United States), `Sahara Telecom Group` (STG, Morocco),
`Danube Mobile Kft` (DMK, Hungary), `Levant Communications` (LVC, Jordan).
`Phase` : `ACTUAL`, `BUDGET`, `FORECAST`. `Solution` : par exemple `Roaming Sponsor`,
`IPX Voice`, `Signalling`, `SMS Hub`, `Data Transit`.

### Dataset 2 : `Trouble Tickets` (~130 lignes)

| Colonne | Type |
|---|---|
| `id` | bigint |
| `Account_name` | string |
| `Severity` | string |
| `Status` | string |
| `Category` | string |
| `creationDate` | date |
| `Duration_ticket_total` | double |

### Agent

Un orchestrateur, `OWIsMind`, accroche `Your business data, answered`, description :
`Orchestrated access to the revenue and trouble-ticket domains: ask a business question, get a
grounded answer with its SQL, source data and charts.`
Capacités : `Revenues: actuals, budget and forecast by account, solution or country`,
`Trouble tickets: volumes, severity, SLA and durations`.
Deux sous-agents : **expert revenus** et **expert trouble tickets**.

### Question et réponse de démonstration

Question : `Compare les revenus réels et le budget 2026 par solution.`
Chiffres cohérents : total réel ~25.1M EUR, budget ~22.4M EUR, écart +12.1%.
Usage : `↑ 6,420 · ↓ 812 tokens · ~$0.0142 · Smart`.

### Icônes disponibles (jeu SVG maison, 56 glyphes)

`send stop mic plus search message chevronUp chevronDown chevronRight chevronLeft chevronsLeft
chevronsRight chevronsUpDown sparkle sparkles trendUp alert check x copy refresh thumbsUp
thumbsDown sun moon help database chart layers globe route sidebar agents dots robot pencil
folderPlus clock accessibility document info messageCircle filter edit lock shield users wallet
grid userPlus arrowLeft sliders user tool bookOpen tag`

**Pas d'emoji.** Si tu as besoin d'un glyphe absent de cette liste, signale-le.

---

## 13. CE QU'ON VEUT EXPLORER AVEC TOI **[À EXPLORER]**

Au-delà de reproduire l'existant, voici les questions ouvertes sur lesquelles on attend
une proposition :

1. **La lisibilité du raisonnement long.** Un run avec 15+ étapes et des sous-agents imbriqués :
   comment garder ça lisible et calme, sans arbre lourd ni mur de texte ? (section 6.6)
2. **Plan prévu vs exécution réelle.** Aujourd'hui la carte de plan et la timeline sont
   simplement empilées. Y a-t-il une forme qui les unifie ?
3. **La transition entre les deux panneaux droits.** Evidence et Source Data sont exclusifs et
   se remplacent brutalement. Faut-il une continuité visuelle ?
4. **La densité de la vue Analyze** quand il y a 8 mesures et un groupement : la table à barres
   tient-elle ? Les cartes KPI ?
5. **La page Benchmark**, la plus dense de l'app, n'a jamais eu de vraie passe de design.
6. **L'export** (CSV, image de graphique, rapport) : pas de surface prévue aujourd'hui.
7. **Les micro-labels à 0.08em** ont été introduits récemment et ne sont pas encore entérinés
   partout dans la charte : à trancher.
8. **La bascule `Data | Analyze`** est à deux endroits différents selon l'hôte : à unifier.

---

## 14. CONTRAINTES POUR QUE LA MAQUETTE SOIT REPORTABLE

L'application cible est **Vue 3 + Vite**, servie comme webapp dans Dataiku DSS. Pour que ta
maquette se reporte proprement :

- **Utilise les noms de tokens de la section 3 tels quels.** C'est le point le plus important :
  si les variables portent les mêmes noms, le report est mécanique.
- **Un écran = une structure de blocs identifiables.** Nomme tes classes par rôle
  (`.prompt`, `.msg.agent`, `.ticker`, `.step`, `.activity`, `.run-plan`, `.evidence`,
  `.ev-head`, `.ev-tabs`, `.src-panel`, `.ws-builder`…), ça correspond aux composants réels.
- **Pas de dépendance externe** (pas de CDN, pas de police distante, pas d'icon font).
  Helvetica Neue avec repli Helvetica / Arial. Les icônes en SVG inline.
- **Le thème se pilote par `body[data-theme]`**, pas par une classe sur un conteneur.
- **Pas de `color-mix`, pas de dégradé, pas de flou** (sauf le teaser du dock).
- **Chaque écran doit avoir ses états vides, de chargement et d'erreur** maquettés, pas seulement
  l'état nominal.
- Prévois le **scroll interne** : le shell ne scrolle jamais globalement, chaque zone
  (fil, panneau, page) a sa propre zone de scroll.

---

## 15. CHECKLIST DE LIVRAISON

Écrans et états à maquetter (chacun en clair **et** en sombre) :

**Shell**
- [ ] Sidebar dépliée / repliée en rail / flyout au survol
- [ ] MainTop avec bascules thème + langue

**Chat**
- [ ] Écran d'arrivée avec dock Source Data en teaser flouté
- [ ] Barre de prompt : repos / focus / avec chips de valeurs / avec chip de contexte /
      opt-out du contexte / bouton stop pendant un run / bloquée par le budget
- [ ] Modale de mode de réponse (deux volets + jauges)
- [ ] Menu de sélection d'agent (ouvert vers le haut)
- [ ] Fil : bulle utilisateur (repos / survol / en édition)
- [ ] Message agent **pendant** le run : ticker de 5 lignes, étape en cours avec shimmer +
      chronomètre, réponse partielle intercalée entre deux phases
- [ ] Message agent **terminé** : bloc d'activité replié, puis déplié
- [ ] Carte de plan d'analyse avec une étape `Running`
- [ ] Panneau SQL déplié + ligne d'usage + pied d'actions complet + navigation de versions
- [ ] États : arrêt en cours / réponse interrompue vide / réponse partielle arrêtée / erreur de run
- [ ] Modale de feedback (variante 👎 avec raisons, variante 👍 commentaire seul)
- [ ] Overlay de chargement de conversation

**Evidence Studio**
- [ ] Onglet Evidence complet : badge `Certified result`, source, calcul décomposé,
      résultat capturé, chips de filtres (dont une modifiée et une pointillée), table live, pied SQL
- [ ] Variantes du badge : `Certified source`, `Partial proof`, `Agent claim`
- [ ] Mode drill-down (bandeau + retour)
- [ ] Onglets `KPI`, `Chart` (barres groupées), `Table`
- [ ] Mode dégradé
- [ ] Squelette de chargement + état d'erreur
- [ ] Sélecteur de valeurs (étape colonnes, étape valeurs, mode plage temporelle)

**Source Data**
- [ ] Teaser flouté / panneau engagé
- [ ] Vue `Data` : table + tri + menu de colonne + popover de cellule + affordances de scroll
- [ ] Vue `Analyze` : sans groupement (cartes KPI) et avec groupement (table à barres)
- [ ] Sélecteur de mesures (avec une entrée désactivée)
- [ ] Ligne de filtres avec chips + `Add` + `Clear all`
- [ ] Aperçu des lignes analysées avec colonnes épinglées
- [ ] États vide / chargement / erreur

**Contexte d'écran**
- [ ] Chip dans la barre de prompt + popover d'aperçu
- [ ] Ligne dépliable sous la bulle utilisateur

**Pages**
- [ ] Agents : grille de cartes + vue détail
- [ ] My account (Settings)
- [ ] Help & Support (deux onglets, formulaire agent en trois étapes, historique)
- [ ] FAQ avec recherche
- [ ] Benchmark (consultation + suggestion)
- [ ] Admin (onglets, éditeur de profil d'agent en modale)
- [ ] AuthGate
- [ ] Page "Coming soon"

---

## 16. RAPPEL DES INTERDITS (à relire avant de livrer)

1. Aucun tiret cadratin (U+2014) ni demi-cadratin (U+2013), nulle part, UI comprise.
2. Aucun emoji dans l'interface.
3. Orange **rare** : états actifs, eyebrows, title-bars, règle haute des KPI, action primaire,
   liens, étape en cours. Rien d'autre.
4. Jamais de vert pour signifier "preuve validée".
5. Pas de dégradé, pas de `color-mix`, pas de flou (sauf le teaser du dock).
6. Pas de liseré vertical orange comme marqueur d'état.
7. Pas de logo reconstruit en CSS : la vraie image.
8. Pas de faux contenu, pas de faux chiffre : les états vides sont honnêtes et explicites.
9. Pas de rebond, pas d'overshoot, pas de texte mis à l'échelle.
10. Aucun détail technique (SQL, id, code d'erreur) dans le fil de conversation.
