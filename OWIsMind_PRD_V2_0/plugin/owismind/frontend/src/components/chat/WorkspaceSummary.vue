<script setup>
// "Open the Studio" under an answer that built a Studio (dashboard + data). One plain
// button, nothing else: the plan lives above the prompt, the dashboard in the Studio.
// A stored answer whose document is not loaded yet fetches it on click (never N
// documents up front). An answer without a Studio after all falls back to Evidence.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '../../stores/workspace.js'
import { useEvidenceStore } from '../../stores/evidence.js'
import { Icon } from '../ui'

const props = defineProps({
  exchange: { type: Object, required: true },
})
const { t } = useI18n()
const ws = useWorkspaceStore()
const evidence = useEvidenceStore()

const entry = computed(() => ws.entryFor(props.exchange.id, props.exchange.uid))
const running = computed(() => !!(entry.value && entry.value.running))
const shown = computed(() => ws.open && !!entry.value && ws.shown === entry.value)
// This answer continued the Studio of an earlier one (studio.carry): its button says
// so. The earlier answer's button is unchanged and opens its own snapshot.
const continued = computed(() => !!(entry.value && entry.value.state && entry.value.state.base_exchange_id))
const label = computed(() => {
  if (shown.value) return t('ws.summary.shown')
  return continued.value ? t('ws.summary.continued') : t('ws.summary.open')
})

async function openStudio() {
  const id = props.exchange.id
  if (!id) return
  const ok = await ws.openForExchange(id, { uid: props.exchange.uid, tab: 'board' })
  if (!ok && !ws.open) evidence.openForExchange(id)
}
</script>

<template>
  <div class="studio-link">
    <button
      type="button"
      class="studio-open"
      :class="{ on: shown }"
      :disabled="!exchange.id || shown"
      @click="openStudio"
    >
      <Icon :name="shown ? 'check' : 'layers'" />
      {{ label }}
    </button>
    <span v-if="running" class="studio-live"><span class="dot" aria-hidden="true" />{{ t('ws.status.running') }}</span>
  </div>
</template>

<style scoped>
.studio-link { margin-top: var(--s-3); display: flex; align-items: center; gap: var(--s-3); }
/* Primary action = orange fill, black ink; once shown it settles to an outline. */
.studio-open {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 0 14px;
  border: 1px solid var(--orange);
  border-radius: var(--r-btn);
  background: var(--orange);
  color: var(--on-orange);
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  transition: background var(--dur) var(--ease);
}
.studio-open:hover:not(:disabled) { background: var(--orange-deep); border-color: var(--orange-deep); }
.studio-open.on { background: transparent; color: var(--text); cursor: default; }
.studio-open:disabled:not(.on) { opacity: 0.5; cursor: default; }
.studio-open :deep(.ui-icon) { width: 15px; height: 15px; }
.studio-live { display: inline-flex; align-items: center; gap: 6px; font-size: var(--fs-xs); color: var(--orange-text); font-weight: var(--fw-bold); }
.dot { width: 7px; height: 7px; background: var(--orange); animation: sl-pulse 1.15s ease-in-out infinite; }
@keyframes sl-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) { .dot { animation: none; } }
/* Narrow chat column: the button and the live mark wrap instead of overflowing. */
@container chat (max-width: 560px) {
  .studio-link { flex-wrap: wrap; gap: var(--s-2); }
  .studio-open { max-width: 100%; }
}
</style>
