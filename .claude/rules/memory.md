---
paths: ["memory/**"]
description: Protocole d'hygiene de la memoire (P4). Chargee quand on edite les fichiers memory/.
---

# Hygiene memoire (P4, L127)

`memory/` (versionne git) = source de verite d'equipe. La memoire native de Claude Code (`~/.claude/projects/.../memory/`) n'est qu'un cache personnel : ne jamais l'utiliser comme reference partagee.

Ordre de lecture : `CONTEXT.md` (focus + pointeurs) -> `LESSONS.md` (au besoin) -> `PROJECT_STATE.md` (etat durable). Les gotchas actives vivent desormais dans `.claude/rules/*.md` (path-scoped), plus dans CONTEXT.md.

- **CONTEXT.md reste LEAN (< 120 lignes)** : header (3 lignes) + Focus courant (les 1-2 derniers runs en clair) + Chaine des sessions (UNE ligne par run, pointeur `sessions/<date>.md` + numeros de lecon) + Regles (2 lignes pointant CLAUDE.md + `.claude/rules/`) + Prochaines etapes (SEULEMENT les items encore actifs, une ligne chacun). Un nouveau bloc plein REMPLACE le precedent, qui redescend a une ligne de la chaine.
- **Ne jamais reciter les gotchas dans CONTEXT.md** : tout changement de gotcha va dans `.claude/rules/` (le bon fichier selon le path concerne), pas dans CONTEXT.md.
- **LESSONS.md est APPEND-ONLY** : nouvelle entree = prochain `L0xx` (Contexte / Ce qui a echoue / Solution qui marche / Preuve / Source / Date). Une lecon revertee ou supplantee recoit un MARQUEUR sous son titre ; on ne reecrit jamais son corps. Le statut par lecon est HISTORIQUE : `PROJECT_STATE.md` section 11 fait foi sur ce qui est deploye.
- **PROJECT_STATE.md** : mettre a jour seulement pour un etat durable (nouvel id canonique, changement de structure, matrice de validation). Les sections datees se re-datent ou se marquent "gelee".
- **sessions/** : un fichier par jour (append d'une section `## run N` si le fichier existe). Ne pas supprimer une session citee par chemin ailleurs ; avant toute suppression, verifier que son contenu est condense dans PROJECT_STATE / LESSONS et qu'aucune reference par chemin ne subsiste.
- **Zero tiret cadratin/demi-cadratin** dans tout `memory/` (regle non negociable #9).

Fin de session = skill `/log-session` (refresh CONTEXT + append LESSONS + `/graphify --update` + commit ; jamais de push).
