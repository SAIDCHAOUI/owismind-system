# CONTEXT - OWIsMind (memoire courte, chargee a CHAQUE session)

> Focus + pointeurs seulement. Etat durable : `PROJECT_STATE.md` ; lecons (L001-L198, historique v1.x
> inclus, encore valables pour DSS/agents) : `LESSONS.md` ; logs par jour : `sessions/*.md`.
> Gotchas actives (frontend/backend/agents/memoire) : `.claude/rules/*.md`, chargees AUTO.

## Focus courant

**2026-10-22 : chantier post-phase 2 (17 au 22 oct.) commite et logge** (`sessions/2026-10-22.md`).
- Continuite du Studio (continuer / nouveau : `studio.continue`, `studio.carry`, `widget.remove`,
  `replaces`, `origin`), suggestions de suite (`suggest.set`, `SuggestionChips.vue`), langue de
  reponse = langue du dernier message user, Studio UI (auto-open, `StudioWaiting`, `WidgetFocus`,
  ordre par glisser-deposer, en-tete ~90 px), simulateur en mode `live` (Haiku 5.5 + sqlite) / `stub`.
- Tests : front 606 OK, backend plugin 1101 OK, agents 889 OK. NON vu par l'user en clair / sombre.
- Derive doc : `CHARTE_V2_UI.md` section 3 (en-tete Studio 56 px -> ~90 px) a mettre a jour.

**V2.0 phase 2 livree (commit 91bdbef, 2026-10-15)** : Studio, plan au-dessus du prompt, Evidence
multi-SQL par `sql_id`, outils workspace de l'orchestrateur. Detail : `OWIsMind_PRD_V2_0/docs/V2_STUDIO_HANDOFF.md`.
Spec : `OWIsMind_PRD_V2_0/docs/V2_ARCHITECTURE.md`.

## Chaine des sessions
- 2026-10-16 : branche nettoyee au minimum (V2 seule), LESSONS condense, READMEs fondus (commits e28f752..0fe23ff).
- 2026-10-22 : bilan + commit du chantier 17-22 oct. (`sessions/2026-10-22.md`, L197-L198).

## Prochaines etapes
- Validation VISUELLE V2 par l'user (clair ET sombre) sur le simulateur puis en DSS (`sessions/2026-10-22.md`).
- Mettre a jour `CHARTE_V2_UI.md` section 3 (en-tete Studio) (`sessions/2026-10-22.md`).
- Trancher l'Agent Factory (garder / retirer).
- Phase 3 (spec section E) : retrait du legacy V1.3 dans le code + validation DSS.

## Regles
- 10 regles non negociables + identifiants canoniques : `CLAUDE.md`. Rappel : #9 = ZERO tiret
  cadratin/demi-cadratin PARTOUT ; #10 = charte (`docs/cadrage/CHARTE_ORANGE_UI.md`, et sur les ecrans
  V2 `OWIsMind_PRD_V2_0/docs/CHARTE_V2_UI.md` prime).
- Gotchas techniques : `.claude/rules/*.md` (chargees selon les fichiers touches).
