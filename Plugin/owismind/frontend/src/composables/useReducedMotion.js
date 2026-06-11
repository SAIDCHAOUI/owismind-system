// Reactive `prefers-reduced-motion` flag. The original mockup honored it almost
// nowhere; gating animations on this composable fixes that gap centrally.
// Components read `reduced.value` to skip/shorten non-essential motion.
import { ref, onMounted, onBeforeUnmount } from 'vue'

export function useReducedMotion() {
  const reduced = ref(false)
  let mql = null
  const update = () => {
    reduced.value = !!(mql && mql.matches)
  }
  onMounted(() => {
    if (typeof window.matchMedia !== 'function') return
    mql = window.matchMedia('(prefers-reduced-motion: reduce)')
    update()
    // addEventListener is the modern API; older Safari used addListener.
    if (mql.addEventListener) mql.addEventListener('change', update)
    else if (mql.addListener) mql.addListener(update)
  })
  onBeforeUnmount(() => {
    if (!mql) return
    if (mql.removeEventListener) mql.removeEventListener('change', update)
    else if (mql.removeListener) mql.removeListener(update)
  })
  return reduced
}
