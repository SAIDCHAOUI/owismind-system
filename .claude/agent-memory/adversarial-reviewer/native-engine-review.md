---
name: native-engine-review
description: Review map for the in-backend native orchestrator engine (profile.native_engine, chantier B) - the contracts it must mirror and where it diverged
metadata:
  type: project
---

The native engine (`agents/native_orchestrator.py`, flag `profile.native_engine`, added
2026-08-06) runs the orchestration loop in the Flask backend and delegates to the Code Agent
specialists via `streaming.run_agent_streamed`. When reviewing it, check it against the
contracts the LEGACY path owns, because they live in files it does not import:

1. **Control tokens.** `OWIsMind_orchestrator.parse_mode` / `parse_lang` deliberately read the
   LAST `⟦owi:…⟧` token (`findall` + `reversed`), documented as anti-forgery: the backend
   appends its authoritative token at the END of the user turn, so a user typing a fake token
   earlier cannot win. Any engine using `re.search` (first match) reopens that hole. The route
   only neutralizes it for `mode` (it passes an explicit value when the agent has `modes`);
   `lang` has no explicit override at all.
2. **Prior-recall block.** `routes.chat_start` gates `prior_recall_enabled` on `supports_modes`,
   NOT on the engine. So any native agent with `modes: true` receives the VISIBLE
   `[PRIOR DATA ... recallable INSTANTLY with recall_prior_result ...]` block
   (`agents/context.build_prior_data_block`) even though only the Code Agent implements that
   tool. Stripping the `⟦owi:prior=…⟧` machine token does not remove the instruction text.
3. **Sub-agent context.** Legacy `pass_context` sends MODE + USER LANGUAGE **plus** a
   "CONVERSATION CONTEXT / PREVIOUS ASSISTANT MESSAGE / USER'S RAW CURRENT MESSAGE" section for
   disambiguation (the fix that lives on both sides, see `.claude/rules/agents.md`).
4. **Timeline events.** Legacy relays specialist lifecycle events prefixed `SUB_AGENT_*`
   (see `frontend/src/registries/timelineSteps.js`); forwarding them raw puts a mid-run
   AGENT_DONE on the public timeline. Harmless (frontend `pushEvent` seals prior events) but a
   contract deviation.
5. **Durable path wins.** `routes.chat_start` takes the `durable_workflow` branch BEFORE the
   engine selection, so an agent with both flags silently uses the Code Agent for planned turns
   and the native engine for simple ones.
6. **Worker wiring.** The engine-selection block in `stream_manager._worker` sits OUTSIDE the
   worker's `try/except/finally`. Anything raising there (a deferred import of a module missing
   from a partial paste) kills the thread with NO terminal event: the run stays `done=False`,
   holds a concurrency slot until `HARD_TTL_SECONDS` (1500s) and the browser polls forever.
   Reproduce by calling `_worker(...)` directly with a `run_native_streamed` that raises at
   CALL time and inspecting `_RUNS[run_id]`.

See also [[captured-result-shape-contract]] (the CRITICAL of this review) and
[[repo-review-pitfalls]].
