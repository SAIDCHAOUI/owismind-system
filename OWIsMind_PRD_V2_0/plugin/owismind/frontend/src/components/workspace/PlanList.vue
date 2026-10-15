<script setup>
// Plan tab - the mission and its steps: a numbered marker per step (number while
// waiting, pulsing orange while running, check when done, "!" on error), the step
// label, the batch progress when the step counts units (done / total) and what the
// step produced (notes, widgets). Read-only view of the reduced state.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { stepsWithProgress } from '../../composables/workspaceModel.js'
import { useWorkspaceStore } from '../../stores/workspace.js'

const props = defineProps({
  state: { type: Object, required: true },
  running: { type: Boolean, default: false },
})
const { t } = useI18n()
const ws = useWorkspaceStore()

const plan = computed(() => props.state.plan)
const steps = computed(() => stepsWithProgress(props.state))

function marker(step) {
  if (step.status === 'done') return '✓'
  if (step.status === 'error') return '!'
  return String(step.index)
}
function batchText(step) {
  const done = step.done != null ? step.done : 0
  return step.unit
    ? t('ws.step.batch_unit', [done, step.total, step.unit])
    : t('ws.step.batch', [done, step.total])
}
</script>

<template>
  <div class="plan">
    <div v-if="!plan" class="empty">
      <div class="empty-t">{{ t('ws.plan.empty_t') }}</div>
      <p class="empty-b">{{ t('ws.plan.empty_b') }}</p>
    </div>
    <template v-else>
      <section class="mission">
        <div class="label">{{ t('ws.mission') }}</div>
        <p class="mission-text">{{ plan.mission }}</p>
        <p v-if="plan.origin === 'auto'" class="hint">{{ t('ws.plan.auto') }}</p>
        <p v-if="plan.version > 1" class="hint">{{ t('ws.plan.revised', [plan.version]) }}</p>
      </section>
      <ol class="steps">
        <li v-for="step in steps" :key="step.id" class="step" :class="step.status">
          <span class="marker" :aria-label="t('ws.step.' + step.status)">{{ marker(step) }}</span>
          <div class="step-main">
            <span class="step-label">{{ step.label }}</span>
            <div v-if="step.hasBatch" class="batch">
              <span class="batch-track"><span class="batch-fill" :style="{ width: step.batchPct + '%' }" /></span>
              <span class="batch-txt mono">{{ batchText(step) }}</span>
            </div>
            <div class="step-meta">
              <span class="status">{{ t('ws.step.' + step.status) }}</span>
              <template v-if="step.notes || step.widgets">
                <span aria-hidden="true">·</span>
                <button
                  type="button"
                  class="link"
                  @click="ws.setTab(step.widgets ? 'board' : 'journal')"
                >{{ t('ws.step.results', [step.notes, step.widgets]) }}</button>
              </template>
            </div>
          </div>
        </li>
      </ol>
    </template>
  </div>
</template>

<style scoped>
.plan { display: flex; flex-direction: column; gap: var(--s-5); }
.mission {
  padding-bottom: var(--s-5);
  border-bottom: 1px solid var(--border-strong);
}
.label {
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
  color: var(--text-2);
  padding-bottom: 7px;
}
.mission-text {
  margin: 0;
  font-size: var(--fs-base);
  line-height: var(--lh-text);
  text-wrap: pretty;
}
.hint {
  margin: var(--s-2) 0 0;
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.steps {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.step {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 9px 0;
  animation: step-in var(--dur) var(--ease-out) both;
}
@keyframes step-in { from { opacity: 0; transform: translateY(4px); } }
.marker {
  flex: 0 0 18px;
  width: 18px;
  height: 18px;
  margin-top: 1px;
  display: grid;
  place-items: center;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: var(--fw-bold);
  border: 1px solid var(--border-strong);
  color: var(--text-3);
  border-radius: var(--r-xs);
}
.step.done .marker { background: var(--text); border-color: var(--text); color: var(--bg); }
.step.running .marker {
  background: var(--orange);
  border-color: var(--orange);
  color: var(--on-orange);
  animation: marker-pulse 1.15s ease-in-out infinite;
}
.step.error .marker { border-color: var(--orange); color: var(--orange-text); }
@keyframes marker-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }
.step-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.step-label {
  font-size: var(--fs-sm);
  line-height: var(--lh-text);
  text-wrap: pretty;
  color: var(--text);
}
.step.done .step-label { color: var(--text-2); }
.step.running .step-label { font-weight: var(--fw-bold); }
.batch { display: flex; align-items: center; gap: 10px; }
.batch-track {
  flex: 0 1 200px;
  min-width: 0;
  height: 5px;
  background: var(--surface-2);
  display: block;
}
.batch-fill {
  display: block;
  height: 100%;
  background: var(--text);
  transition: width var(--dur-slow) var(--ease-out);
}
.batch-txt { font-size: 11px; color: var(--text-2); white-space: nowrap; }
.step-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.step.running .status { color: var(--orange-text); font-weight: var(--fw-bold); }
.step.error .status { color: var(--danger); }
.link {
  color: var(--text-2);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.link:hover { color: var(--text); }
.empty { max-width: 440px; padding: var(--s-6) 0; }
.empty-t { font-size: var(--fs-base); font-weight: var(--fw-bold); padding-bottom: 8px; }
.empty-b { margin: 0; font-size: var(--fs-sm); color: var(--text-2); line-height: var(--lh-text); }
@media (prefers-reduced-motion: reduce) {
  .step, .step.running .marker { animation: none; }
}
</style>
