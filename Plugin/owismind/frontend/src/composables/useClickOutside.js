// Detect clicks outside one or more elements and invoke a handler. Replaces the
// maquette's one-time global document listeners (e.g. _dhDdListenerAdded) with a
// lifecycle-bound listener that registers on mount and cleans up on unmount.
//
// Usage:
//   const panel = ref(null)
//   useClickOutside(panel, () => (open.value = false))
// Pass an array of refs to treat several elements (e.g. trigger + panel) as "inside".
//
// Option `closeOnWindowBlur` (default false): also fire the handler when our WINDOW loses
// focus. DSS hosts the app in an iframe, so a click on the surrounding DSS chrome never
// reaches our document and the pointer listeners below never fire - a window 'blur' is the
// only signal that focus left our surface. The blur handler is guarded: it does NOT fire
// while the still-focused element (document.activeElement) is inside a target, so opening a
// browser-native popup (e.g. an <input type="month"> calendar, which keeps its input
// focused) does not self-close the popover.
import { onMounted, onBeforeUnmount, unref } from 'vue'

export function useClickOutside(targets, handler, options = {}) {
  const { events = ['mousedown'], enabled = true, closeOnWindowBlur = false } = options
  const list = Array.isArray(targets) ? targets : [targets]

  function isInside(node) {
    return list.some((t) => {
      const el = unref(t)
      return el && (el === node || el.contains(node))
    })
  }

  function onEvent(e) {
    if (!enabled) return
    if (!isInside(e.target)) handler(e)
  }

  function onWindowBlur(e) {
    if (!enabled) return
    // Keep the popover open while focus stays inside it (native calendar opened);
    // close when focus has truly left our surface (DSS chrome, another tab/app).
    if (isInside(document.activeElement)) return
    handler(e)
  }

  onMounted(() => {
    // `true` (capture) so we still fire if inner handlers stop propagation.
    for (const ev of events) document.addEventListener(ev, onEvent, true)
    if (closeOnWindowBlur) window.addEventListener('blur', onWindowBlur)
  })
  onBeforeUnmount(() => {
    for (const ev of events) document.removeEventListener(ev, onEvent, true)
    if (closeOnWindowBlur) window.removeEventListener('blur', onWindowBlur)
  })
}
