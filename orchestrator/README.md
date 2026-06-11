# OWIsMind orchestrator (Code Agent Dataiku) — repo copy

## Role

`orchestrator_agent.py` is the source of truth for the **"Le Cerveau" Code Agent** running
inside Dataiku DSS. It plans (1 small LLM call → strict JSON), executes the plan
deterministically (sub-agents via LLM Mesh streaming + direct Python tools), then
synthesizes (verbatim relay when single-agent, small LLM otherwise). It streams the event
protocol consumed by the OWIsMind webapp (`python-lib/owismind/agents/streaming.py`).

The eventKind list (START, PLANNING, PLAN_READY, DIRECT_ANSWER, CALLING_AGENT, AGENT_DONE,
RUNNING_TOOL, TOOL_DONE, WRITING_ANSWER, DONE, ERROR, SUB_AGENT_*) is a **frozen contract**
since v2.2: kinds are never renamed, only added. See `AUDIT.md` for the v2.2 changes
(ORCH-01..11) and the residual risks.

The file is **standalone**: it depends only on the stdlib + `dataiku` (and optionally
`dataikuapi` for footer class detection). It must never import from the plugin.

## Deployment

1. In DSS, open the orchestrator **Code Agent** (Agents > the orchestrator entry).
2. Paste the FULL content of `orchestrator_agent.py` into the code editor (replace all).
3. Save. No build step, no dependency to install. Re-run a test question from the
   agent's quick-test or from the OWIsMind webapp.

Always edit the repo copy first, test, then paste — never the other way around.

## Testing (DSS-free)

From the repo root:

```bash
python3 -m py_compile orchestrator/orchestrator_agent.py
python3 -m unittest discover -s orchestrator/tests -v
```

The tests stub the `dataiku` module before import and cover only the pure functions
(plan validation, trace walkers + capture caps, labels, sources block, helpers).
Anything touching LLM Mesh / streaming must be validated on the DSS instance.
