# CONTEXT - OWIsMind (memoire courte, chargee a CHAQUE session)

> Focus + pointeurs seulement. Etat durable : `PROJECT_STATE.md` ; lecons (L001-L196, historique v1.x
> inclus, encore valables pour DSS/agents) : `LESSONS.md` ; logs par jour : `sessions/*.md`.
> Gotchas actives (frontend/backend/agents/memoire) : `.claude/rules/*.md`, chargees AUTO.

## Focus courant

**2026-10-16 : branche `OWIsMind_PRD_V2_0` nettoyee au minimum (V2 seule).**
- Retires de la branche : `OWIsMind_PRD_V1_3_DEV/`, `OWIsMind_LAB/`, `dev-harness/` racine, `docs/`
  racine (sauf `docs/cadrage/`), docs V1.3 de `OWIsMind_PRD_V2_0/docs/` (deploy v1.3, audits juillet,
  durable, capability matrix), `memory/sessions/` (historique dans git + branche `OWIsMind_PRD_V1_3-dev`).
- Garde : le Benchmark AFFICHE dans le plugin (decision user : le benchmark continue d'exister).
- Ouvert : Agent Factory (console + `owismind_factory` + notebooks 00-06) a garder ou non, a trancher.

**V2.0 phase 2 livree (commit 91bdbef, 2026-10-15)** : Studio (espace de travail), plan au-dessus du
prompt, Evidence multi-SQL par `sql_id`, outils workspace de l'orchestrateur. Detail et reste a faire :
`OWIsMind_PRD_V2_0/docs/V2_STUDIO_HANDOFF.md`. Spec : `OWIsMind_PRD_V2_0/docs/V2_ARCHITECTURE.md`.

## Prochaines etapes
- Validation VISUELLE V2 par l'user (clair ET sombre) sur le simulateur puis en DSS.
- Phase 3 (spec section E) : retrait du legacy V1.3 dans le code + validation DSS.
- Trancher l'Agent Factory (garder / retirer).

## Regles
- 10 regles non negociables + identifiants canoniques : `CLAUDE.md`. Rappel : #9 = ZERO tiret
  cadratin/demi-cadratin PARTOUT ; #10 = charte (`docs/cadrage/CHARTE_ORANGE_UI.md` + `CHARTE_V2_UI.md`).
