---
name: recurring-charter-traps
description: Pieges de charte qui reviennent dans ce frontend Vue (orange AA sur petit texte, hover inverse en dark, jumeaux SourceTable/EvidenceTable, th en flex, conteneur bascule en --surface)
metadata:
  type: project
---

Quatre pieges reviennent a chaque revue de charte dans `frontend/src`.

1. **Petit texte orange en `--orange` ou `--orange-deep`.** La charte n'autorise que
   `--orange-text` (AA). Recurrent sur les etats de table (`thead th.sorted`) et sur les
   hovers de boutons texte. Piege dark en plus : `--orange-text` vaut `#ffb066` (clair) en
   dark, donc un hover vers `--orange-deep` (#cc6100) ASSOMBRIT le texte et fait chuter le
   contraste - le hover part dans le mauvais sens selon le theme. Verifier les deux themes,
   pas seulement le clair.
2. **Fichiers jumeaux `components/sources/SourceTable.vue` et
   `components/evidence/EvidenceTable.vue`.** Meme table, deux copies : une correction de
   charte appliquee a l'un est reguliement oubliee sur l'autre (exemple observe : le
   squelette de chargement `.sk-cell` est conforme dans SourceTable, encore en
   `linear-gradient` + `border-radius: 4px` dans EvidenceTable). Toujours grep les deux.
   Meme reflexe pour la paire `ArtifactTable.vue` / `EvidenceResult.vue`.
3. **`th` structure en flex.** Dans SourceTable / EvidenceTable, le `<th>` contient un
   `.th-inner` flex (bouton de tri + menu de colonne) : un `text-align: right` sur le `th`
   n'a aucun effet. Le fix reel = `justify-content: flex-end` sur `.th-inner` +
   `text-align: right` sur `.th-btn`. Ne pas proposer le `text-align` seul.

4. **Basculer le fond d'un conteneur de `--bg` vers `--surface`** (effet "hierarchie par
   nuances de gris" demande par l'user). Tous les enfants dessines pour un fond `--bg`
   cassent d'un coup : les remplissages `background: var(--surface)` (chips de dataset,
   chips de filtre, zone Calculer) deviennent INVISIBLES (meme tonalite que leur fond)
   et les filets `1px var(--border)` tombent a ~1.1:1 sur `--surface` (#ececec sur
   #fafafa). Le systeme aplat + filet s'evapore. Fix : dans le conteneur, forcer les
   surfaces de contenu en `--bg` + filets `--border-strong` via `:deep()`, ou renoncer
   au fond ambiant. Pareil en dark (#161616 sur #161616). Releve sur `SourcePanel.vue`
   le 2026-08-06.

**Why:** ces points ont ete releves lors des revues du 2026-08-06 (alignement
numerique des tables + retrait de la banniere de consentement) et decoulent de la structure
du code, pas d'une erreur ponctuelle : ils reapparaitront.

**How to apply:** au debut de chaque revue, grep `--orange-deep` et `var(--orange)` dans les
fichiers touches (hors fonds/barres), puis verifier que le jumeau du fichier modifie a recu
le meme traitement.
