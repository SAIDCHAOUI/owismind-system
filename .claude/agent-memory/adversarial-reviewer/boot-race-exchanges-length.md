---
name: boot-race-exchanges-length
description: Any watcher gating on chat.exchanges.length is racy at app boot - /agents and /conversation start together and either can win; replay watchers with the real vue in node_modules to prove it
metadata:
  type: project
---

`chat.exchanges.length === 0` does NOT mean "empty conversation" during app boot. Treat every
new watcher/guard built on it as racy until proven otherwise.

**Why:** `App.vue` renders `AppLayout` only once `session.authState !== 'pending'`, and
`authState` flips inside `loadMe()`. `session.init()` then fires `Promise.all([loadAgents(), ...])`
in the same microtask window in which `ChatView` mounts and its immediate route watcher calls
`chat.openSession(sid)`. So `/agents` and `/conversation` are issued CONCURRENTLY and either can
land first. `openSession` deliberately does NOT clear `exchanges` (no "new conversation" flash,
chat.js), so on a cold reload of `/chat/<sid>` the window between "agents loaded" and "rows
loaded" looks exactly like an empty conversation. `/conversation` is the heavier call
(`ensure_chat_table()` + a full messages SELECT with stored answers and generated_sql, routes.py)
while `/agents` is one settings read, so `/agents` usually wins. The codebase already documents
the reverse ordering at chat.js (`adoptAgentFromExchanges` is deferred through
`ensureLoaded().then(adopt)` precisely because the race exists) - cite that comment, it is the
authors' own admission.

Found this way on 2026-08-06: the Source Data auto-dock watch in `AppLayout.vue` opened the panel
over a fully loaded conversation and fired two rounds of dataset queries (first for the default
agent, then again for the adopted conversation agent). The accepted fix shape is to gate on the
ROUTE instead of on the loaded state: the auto-dock now also requires `route.params.sessionId` to
be empty (bare `/chat` = a genuinely new conversation), which is race-free because the URL is
stamped only once an exchange exists. Reuse that shape rather than adding timers or `open` deps.

**How to apply:**
- Whenever a diff adds a watcher keyed on `exchanges.length`, `hasMessages` or `turns.length`,
  walk the boot ordering above before accepting it. Also check `adoptAgentFromExchanges`, which
  changes `selectedAgentKey` AFTER rows land and can fire a second follow-the-agent watch.
- A watcher that omits the panel's own `open` ref from its deps cannot self-correct once the race
  put it in the wrong state - the guard only ever runs again when a listed dep changes.

**Proof technique that works here (no install needed):** `vue` 3.5 is already in
`frontend/node_modules`. Write a `.mjs` harness importing `ref/computed/watch/nextTick` from
`node_modules/vue/index.mjs`, transcribe the watcher verbatim, and drive the store sequence with
`await nextTick()` between each simulated response to test both race orders. Real scheduler, real
`flush: 'pre'` batching, runs in a second. Beware one artifact: a child component's watcher
(e.g. `SourcePanel`'s `selectedAgentKey` watch) only exists once the child is MOUNTED, so a
harness that registers it upfront reports one extra call.

See also [[owismind-frontend-review-patterns]], [[parallel-workstream-red-tests]].
