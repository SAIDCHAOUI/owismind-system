---
description: Routage multi-modeles - Claude orchestre, subagents Opus/Sonnet implementent, Codex (GPT-5.6) execute les taches bornees et les reviews croisees. Pointee depuis CLAUDE.md, valable pour toute la session.
---

# Routage multi-modeles (Claude = cerveau, Codex/GPT-5.6 = executant)

Deux abonnements (Claude Code + ChatGPT Plus) : repartir la consommation et donner chaque
tache au modele le plus adapte. Claude garde l'orchestration et le repo-level ; Codex CLI
(plugin `codex@openai-codex`, config projet `.codex/config.toml`, instructions `AGENTS.md`
racine) execute les taches bornees.

## Table de routage

| Tache | Modele | Comment |
|---|---|---|
| Orchestration, specs, architecture, integration | Fable/Opus (session principale) | direct |
| Implementation bien specifiee, fan-out, revues internes | Opus | subagents du projet (adversarial-reviewer, charte-orange-reviewer, dss-deployer, memory-curator) avec `model: opus` (jamais Fable en fan-out, decision user) |
| Recherche/exploration repo | Sonnet ou graphe | subagent Explore en sonnet, ou `graphify query` d'abord (18x moins de tokens) |
| 2e chantier en parallele | GPT-5.6 Terra (defaut) | `/codex:rescue --background "..."` |
| Debug coriace, refactor long, second avis | GPT-5.6 Sol | `/codex:rescue --model gpt-5.6-sol --effort high` |
| Mecanique en volume (renommages, boilerplate) | GPT-5.6 Luna | `/codex:rescue --model gpt-5.6-luna` |
| Review croisee avant commit | GPT-5.6 Terra | `/codex:review --base <branche version courante>` |
| Critique de conception | GPT-5.6 Sol | `/codex:adversarial-review` |

Suivi : `/codex:status`, `/codex:result [id]`, `/codex:cancel [id]`. Transfert de session :
`/codex:transfer`. Subagent utilisable par Claude directement : `codex:codex-rescue`.
NB : ce repo n'a pas de branche de base `main` active ; la base de review = la branche de
version courante (ex. `OWIsMind_PRD_V1_2` pour la branche `OWIsMind_PRD_V1_3-dev`).

## Regles non negociables

1. **Jamais deux agents** (Claude / Codex / subagents) **sur les memes fichiers en meme
   temps** : tache bornee, attendre le diff, integrer.
2. **Codex propose, Claude verifie** : tout diff Codex passe par les tests du repo
   (`unittest discover` cible + compile-check Vite) et la review cote Claude avant commit,
   comme n'importe quel subagent.
3. **Zones sensibles interdites a Codex seul** : securite SQL (whitelist, parametrage,
   PROJECT_KEY), artefacts generes (`resource/owismind-app/`, `ready-for-dataiku/`),
   `memory/`, toute action contre l'instance DSS, installations, git commit/push.
   Elles restent cote Claude (et les installs cote user).
4. **Economie** : Terra par defaut, Sol seulement quand c'est justifie (limites ChatGPT ~2x).
5. Les regles projet s'appliquent aussi a Codex via `AGENTS.md` (zero em dash, code en
   anglais, resume en francais, preuve de tests).

## Pieges verifies

1. `codex exec` lance depuis un script se bloque sur stdin : toujours `</dev/null`
   (le plugin le gere lui-meme).
2. La config projet `.codex/config.toml` n'est lue que si le projet est **trusted** dans
   `~/.codex/config.toml` (`[projects."<chemin>"] trust_level = "trusted"`). Sans trust,
   c'est le modele global (sol) qui part. Verifie le 2026-07-10 sur ce repo : sol avant
   trust, terra apres.
