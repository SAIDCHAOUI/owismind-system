// Data translator - the maquette's `tr(value)`: a plain string passes through,
// a { fr, en } object resolves to the current locale (fallback fr → en → first).
// Use for DATA (e.g. agent metadata, fixtures), NOT for UI strings (use $t/t).
//
// Reactive: reads the vue-i18n locale ref, so templates re-render on language change.
import { useI18n } from 'vue-i18n'

export function useTr() {
  const { locale } = useI18n()
  return function tr(v) {
    if (v == null) return v
    if (typeof v !== 'object' || Array.isArray(v)) return v
    const cur = locale.value
    if (v[cur] != null) return v[cur]
    if (v.fr != null) return v.fr
    if (v.en != null) return v.en
    const vals = Object.values(v)
    return vals.length ? vals[0] : ''
  }
}
