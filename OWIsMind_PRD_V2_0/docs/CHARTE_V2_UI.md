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
- **Balise de droite (beacon)** : colonne pleine hauteur de 320 px, soeur de la colonne du chat (l'en-tête
  du chat n'est jamais recouvert), une grande carte cliquable fidèle au design (icône 44 px, eyebrow, titre,
  sous-titre, jeux de données, aperçu estompé de vraies lignes, appel orange en bas, animation `bcnRise`).
  Seule exception admise aux dégradés : le voile de l'aperçu (transparent vers `--veil`), repris du design.
  Sous 900 px : un bouton flottant sous l'en-tête.
- **Tiroir de provenance** : panneau flottant `--float-strong`, filet gauche, SQL en mono 12 sur
  `--surface`, mots-clés `--orange-text`.
- **Mouvement** : entrées 180-280 ms (`--ease`), pulsation 1,15 s ; tout est coupé sous
  `prefers-reduced-motion`.

## 4. Studio (refonte du 2026-10-15, retour utilisateur)

- **Nom** : toute la surface de droite s'appelle « Studio » (fr et en).
- **Toile** : `--canvas` derrière l'en-tête et le chat. La barre latérale s'en distingue : surface
  `--paper` + filet 1 px `--border` à droite, titre « Conversations » 14/700 en `--text`, lignes 38 px en
  `--text`, conversation active = `--surface-press` + gras + barre orange 3 px à gauche (retour user :
  les conversations doivent sauter aux yeux). Les cartes flottent dessus en `--paper` (blanc ; en sombre, un cran plus clair que la toile noire) :
  Studio, balise, carte de prompt, carte de plan. Studio = filet 1 px `--border`, rayon `--r-lg`,
  ombre `--float-strong`, retrait de 12 px du haut, de la droite et du bas.
- **Largeur** : le Studio s'ouvre à 70 % de la largeur disponible et ne peut jamais dépasser 70 % (le chat
  garde au moins 30 %, y compris pendant le redimensionnement) ; le chat est un conteneur (`@container`)
  qui se compacte en dessous de 560 px. Il s'ouvre seul
  quand l'agent commence un tableau de bord, ou depuis la balise / « Ouvrir le Studio ».
- **Plan** : carte repliable juste au-dessus du prompt (valeurs du design) ; les notes s'ouvrent sous
  leur étape. Le Studio n'a que deux onglets : « Tableau de bord » (toujours premier) et « Données ».
- **Rien de technique par défaut** : ni SQL, ni identifiant, ni clé d'agent, ni numéro d'étape. Un seul
  lien par carte, « D'où viennent ces données ? », en phrases simples ; le SQL et les identifiants
  restent derrière « Détails techniques ».
- **Écran étroit** (< 900 px) : le Studio couvre tout l'écran ; la carte de plan reste au-dessus du prompt.
