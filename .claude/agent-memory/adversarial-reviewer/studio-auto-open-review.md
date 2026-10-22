---
name: studio-auto-open-review
description: Studio auto-open (workspace store autoOpen/deferred/setOtherPanel + AppLayout watchers) - where it breaks and how to prove it under node:test
metadata:
  type: project
---

Studio auto-open (2026-10-20 WP2): `autoOpen(e)` in stores/workspace.js, `setOtherPanel` fed by an AppLayout watcher on `(sources.open && !sources.teaser) || evStandalone`.

Weak points found (verify they are still there before re-reporting):
- `setOtherPanel(false)` replays ANY deferred entry without checking that the Studio is now showing ANOTHER entry: user opens Studio B ("Open the workspace") while Source Data is engaged and run A is deferred -> watcher closes Source Data -> busy false -> A replaces B.
- `closeRight()` (narrow sheet backdrop) calls `workspace.close({byUser:true})` even when the open panel is Source Data: `close()` acts on `shown` (shownKey survives close) -> dismisses the live run.
- Programmatic close re-arms; on a non-chat route each widget does show -> route watcher close, and the `workspace.open` watcher (registered first) collapses the sidebar every time.

**Why:** these are cross-component races the unit tests (which call store actions directly) never exercise.
**How to apply:** reproduce with a throwaway `test/zz_*.test.js` importing the real store under pinia (copy the setInterval/window stubs from test/workspaceStudio.test.js), drive the AppLayout watcher sequence by hand, then delete the file. Vue 3.5 pre-flush watchers of ONE component run in TRIGGER order, not registration order (scheduler findInsertionIndex keeps same-id PRE jobs FIFO). Registration order only holds when one ref triggers both. So "registered first, runs first" comments are wrong when different refs change: openSession does `sources.closePanel()` BEFORE `activeSessionId = ...`, so the panel-context replay ran before clearDeferred and reopened the old run's Studio in the new conversation (confirmed 2026-10-20 after the fix round). See [[native-engine-review]], [[boot-race-exchanges-length]].
