---
name: recurring-charter-traps
description: Pieges de charte qui reviennent dans ce frontend Vue (orange AA sur petit texte, hover inverse en dark, fichiers jumeaux SourceTable/EvidenceTable qui derivent)
metadata:
  type: project
---

Trois pieges reviennent a chaque revue de charte dans `frontend/src`.

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

**Why:** ces trois points ont ete releves lors de la revue du 2026-08-06 (alignement
numerique des tables + retrait de la banniere de consentement) et decoulent de la structure
du code, pas d'une erreur ponctuelle : ils reapparaitront.

**How to apply:** au debut de chaque revue, grep `--orange-deep` et `var(--orange)` dans les
fichiers touches (hors fonds/barres), puis verifier que le jumeau du fichier modifie a recu
le meme traitement.
