// App-wide transient toast service. Module-level reactive queue so any component
// (or the ui store) can push a toast without prop-drilling — replaces the
// maquette's `showToast()` that appended straight to document.body.
//
//   import { useToasts } from '@/composables/useToasts'
//   useToasts().push('Copié', { tone: 'ok', icon: 'check' })
//
// A single <ToastHost> (mounted once in App.vue) renders `toasts`.
import { reactive, readonly } from 'vue'

const toasts = reactive([])
let seq = 0

function push(message, opts = {}) {
  const { tone = 'neutral', icon = '', duration = 2400 } = opts
  const id = ++seq
  toasts.push({ id, message, tone, icon })
  if (duration > 0) {
    setTimeout(() => dismiss(id), duration)
  }
  return id
}

function dismiss(id) {
  const i = toasts.findIndex((t) => t.id === id)
  if (i >= 0) toasts.splice(i, 1)
}

export function useToasts() {
  return { toasts: readonly(toasts), push, dismiss }
}
