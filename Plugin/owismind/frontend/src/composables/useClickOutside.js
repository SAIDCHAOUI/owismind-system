// Detect clicks outside one or more elements and invoke a handler. Replaces the
// maquette's one-time global document listeners (e.g. _dhDdListenerAdded) with a
// lifecycle-bound listener that registers on mount and cleans up on unmount.
//
// Usage:
//   const panel = ref(null)
//   useClickOutside(panel, () => (open.value = false))
// Pass an array of refs to treat several elements (e.g. trigger + panel) as "inside".
import { onMounted, onBeforeUnmount, unref } from 'vue'

export function useClickOutside(targets, handler, options = {}) {
  const { events = ['mousedown'], enabled = true } = options
  const list = Array.isArray(targets) ? targets : [targets]

  function onEvent(e) {
    if (!enabled) return
    const inside = list.some((t) => {
      const el = unref(t)
      return el && (el === e.target || el.contains(e.target))
    })
    if (!inside) handler(e)
  }

  onMounted(() => {
    // `true` (capture) so we still fire if inner handlers stop propagation.
    for (const ev of events) document.addEventListener(ev, onEvent, true)
  })
  onBeforeUnmount(() => {
    for (const ev of events) document.removeEventListener(ev, onEvent, true)
  })
}
