# Charte UI V2 (OWIsMind V2.0)

> Décision user D1 (2026-10-15). S'applique aux écrans V2 (espace de travail, chat, panneaux) et,
> via les tokens, à toute l'app. Source des valeurs : `plugin/owismind/frontend/src/styles/tokens.css`
> (mêmes noms de tokens que V1.3, valeurs du design `docs/design-v2/theme.css`).
> Remplace pour la V2 la `CHARTE_ORANGE_UI.md` V1.3 : la title bar 52x4, le `border-radius: 0`
> global et les titres 800 sont abandonnés.

## 1. Les règles du design (base)

- **Couleurs : 80 % primaires.** Noir, blanc, gris (`--text`, `--text-2`, `--text-3`, `--border*`,
  `--surface*`) et UN orange `#FF7900`. Toujours les tokens sémantiques, jamais de hex en dur.
- **Couleurs secondaires (bleu, vert, rose, violet, jaune) : séries de graphiques et catégories
  uniquement** (`--series-1..8`, une variante par thème). Jamais pour le chrome (boutons, cadres, fonds).
- **Deux graisses : 400 et 700.** Les noms V1.3 (`--fw-medium`, `--fw-semibold`, `--fw-heavy`) sont
  mappés sur cette paire.
- **Rayons 2 à 8 px** (`--r-xs` 2, `--r-sm`/`--r`/`--r-btn` 4, `--r-lg`/`--r-xl` 8). **Pas de pilule** :
  `--r-pill` vaut 4 px. Seuls les avatars sont ronds (50 %).
- **Surfaces plates, filets 1 px.** Pas de dégradé décoratif, pas de blur, pas de `color-mix`, pas de
  glow. Ombres limitées : `--elev-1`, `--elev-2`, `--float`, `--float-strong` (couches flottantes).
- **Pas de barre d'accent décorative** (ni title bar sous les titres, ni filet orange en haut des cartes).
- **Focus clavier toujours visible** : contour orange 2 px (`base.css`, boutons/liens/onglets) ; les
  champs texte gardent leur propre état focus.
- **Dark** via `body[data-theme]` + tokens (fond `#000`, surfaces `#141414`/`#1c1c1c`).
- **Marque** : toujours la vraie image `orange-logo.png`, jamais un carré reconstruit en CSS.

## 2. Ce que la V2 ajoute au mock

1. **L'aura orange du prompt est conservée** (F26) : `--aura-orange` / `--aura-orange-strong`, nuage
   diffus à alpha < 0,15 autour de la carte de prompt, dans les deux états (arrivée et conversation).
2. **Un peu plus de couleur et de contraste que le mock, toujours comme SIGNAL** :
   - **état en cours** : carré orange pulsé 7-8 px (en-tête du panneau, étape running, widget en attente) ;
   - **sélection** : cadre orange + fond `--orange-soft-dark` (onglet actif, carte d'espace de travail affichée) ;
   - **action principale** : aplat orange, encre noire (`--on-orange`), survol `--orange-deep`
     (« Ouvrir l'espace de travail », « Ouvrir dans Données ») ;
   - **texte orange** : toujours `--orange-text` (AA sur blanc), réservé aux libellés de signal
     (« Nouveau », « Constat », lien « Voir la preuve »).
3. L'orange n'est **jamais** une décoration : pas de fond orange de section, pas de bordure orange au repos.

## 3. Recettes espace de travail

- **Panneau** : en-tête 56 px (aligné sur la barre du chat), titre 13/700, sous-titre 12/400 `--text-2`,
  filet de progression du plan 2 px orange, onglets = boutons 30 px rayon 4, filet 1 px.
- **Marqueurs d'étape** : carré 18 px rayon 2 : numéro gris (à faire), orange plein encre noire
  (en cours), encre pleine + coche (terminée), cadre orange + « ! » (échec).
- **Cartes** (widgets, carte de synthèse) : filet 1 px `--border-strong`, rayon 8, fond `--bg`,
  padding 16, titre 13/700, commentaire 13/400 `--text-2`.
- **KPI** : chiffre 28/700 chiffres tabulaires, libellé 12, delta teinté succès/danger (jamais la
  couleur seule : flèche + signe).
- **Graphiques** : séries `--series-*` résolues sur `<body>` au dessin (F25), re-rendu au changement
  de thème et de langue.
- **Tiroir de provenance** : panneau flottant `--float-strong`, filet gauche, SQL en mono 12 sur
  `--surface`, mots-clés `--orange-text`.
- **Mouvement** : entrées 180-280 ms (`--ease`), pulsation 1,15 s ; tout est coupé sous
  `prefers-reduced-motion`.
