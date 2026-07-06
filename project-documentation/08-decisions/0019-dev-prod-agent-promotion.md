# ADR-0019 - DEV / PROD_V1 agent split with scripted regeneration for promotion

> Audience: Agent developer, maintainer. Last updated: 2026-07-06. Summary: why the LangGraph agent
> files are duplicated per DSS project (`OWISMIND_DEV` / `OWISMIND_PROD_V1`) and why PROD is REGENERATED
> from DEV by a script (`tools/promote_agents_to_prod.py`) rather than edited by hand.

## Status

Accepted. Decision made on 2026-07-06 (Run 5), repo ready; DSS deployment follows the runbook
`docs/DEPLOY_PROD_V1_1.md`. Lesson L139.

## Context

The agents (orchestrator + revenue expert, and an in-progress tickets expert) run as Code Agents in a
specific DSS project, and their ids (agent ids, tool ids, semantic-model ids) are per-project: a PROD copy
cannot reuse the DEV ids. We develop in DEV and promote to PROD. Doing that promotion by hand-editing the
PROD files is error-prone (a surviving DEV id silently breaks resolution), and PROD had already drifted 650
lines behind DEV. PROD must also intentionally EXCLUDE the tickets expert (not yet validated) while still
answering honestly about tickets.

## Decision

- **The agent files are DUPLICATED per project** under
  `dataiku-agents/OWISMIND/{OWISMIND_DEV, OWISMIND_PROD_V1}/{agents,recipes,semantic_model,tools}/`, with
  project-prefixed filenames. The id map and workflow live in `dataiku-agents/OWISMIND/README.md` and each
  `registry.json`.
- **PROD is REGENERATED from DEV by `tools/promote_agents_to_prod.py`**, idempotent: it copies each DEV
  file, applies the per-project id substitutions (PROD ids baked in), and - orchestrator only - surgically
  removes the `tickets_expert` capability block while KEEPING `tickets` in `BUSINESS_DOMAINS` so PROD still
  gives the honest "no agent for this domain yet" answer (ADR-0004 honesty firewall). The script REFUSES to
  write on any unexpected state (marker missing, a DEV id surviving in a PROD file, em/en dash glyphs) and
  compile-checks the output. The only admissible DEV<->PROD diff is: deploy-target headers + id lines + the
  removed tickets block.
- **Parity by construction**: because PROD is generated, not authored, it cannot drift from DEV except by
  the intended substitutions. Future promotions are one command, then re-paste into DSS.

## Reasons

- Regeneration eliminates the class of bugs where PROD silently keeps a DEV id or falls behind DEV logic.
- The reviewable, bounded diff makes the adversarial verification cheap (three Opus reviews found 0
  executable findings at the diff level; the residual diff was exactly ids + headers + tickets block).
- Keeping `tickets` in `BUSINESS_DOMAINS` while dropping the capability preserves the honesty contract: PROD
  refuses honestly rather than pretending the data does not exist.

## Consequences

Positive:

- Promotion is one idempotent command; parity is guaranteed, not hoped for.
- The tickets expert can mature in DEV without leaking into PROD.
- The script's refusals (DEV id / dash / missing marker) are a built-in safety net.

Negative or watch points:

- Not everything is promoted by the script: `registry.json` (`last_reviewed` + capability changes), the
  per-project semantic-model README/MODEL.md, and helper scripts (`drop_column_and_reindex.py`,
  `dump_semantic_model.py`) are updated by hand; the script's docstring lists these.
- After regeneration the four PROD files still must be pasted into the DSS Code Agents (env 3.11) manually;
  the repo is the source of truth, the instance does not self-update.
- If an id ever changes in DSS, the substitution tables in the script (and `OWISMIND/README.md`) must be
  updated first.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Hand-edit the PROD files for each promotion | Error-prone (surviving DEV ids), and PROD had already drifted 650 lines; not reproducible. |
| A single shared file parameterized at runtime by project | Code Agents are standalone per project; a runtime indirection would fight the platform and obscure the frozen contracts. |
| Ship the tickets expert to PROD too | Not yet validated; keeping it DEV-only with an honest PROD refusal is the safe path. |

## See also

- [ADR-0004 - Server-side agent whitelist](0004-whitelist-agents-serveur.md) - the honesty firewall and the registry PROD keeps.
- [ADR-0005 - LangGraph Code Agents in Python 3.11](0005-langgraph-code-agents-python-311.md) - the env the pasted files run in.
- [Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md) - the re-paste procedure.
- [ADR index](README.md) - all architecture decisions.
