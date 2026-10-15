<script setup>
// Plan card (V2, design "Espace de travail v4"): the agent's plan for the LAST answer
// of the conversation, directly above the prompt. A fold-out: the header row (chevron
// + "Plan", a thin orange progress bar, "n / N étapes") folds / unfolds the step list.
// Unfolded while a run builds the plan, collapsed when it ends and on a reopened
// conversation (workspace store `planOpen`). A step with notes opens them in place
// (the agent's findings for that step) - no separate journal.
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '../../stores/chat.js'
import { useWorkspaceStore } from '../../stores/workspace.js'
import { stepsWithProgress, planProgress } from '../../composables/workspaceModel.js'

const { t } = useI18n()
const chat = useChatStore()
const ws = useWorkspaceStore()

const entry = computed(() => {
  const turns = chat.turns
  const last = turns.length ? turns[turns.length - 1].exchange : null
  return last ? ws.entryFor(last.id, last.uid) : null
})
const state = computed(() => (entry.value ? entry.value.state : null))
const plan = computed(() => (state.value ? state.value.plan : null))
const steps = computed(() => (plan.value ? stepsWithProgress(state.value) : []))
const progress = computed(() => planProgress(state.value))
const running = computed(() => !!(entry.value && entry.value.running))

const openStep = ref(null)
function notesOf(stepId) {
  return (state.value ? state.value.notes : []).filter((n) => n.step_id === stepId)
}
function toggleStep(step) {
  if (!step.notes) return
  openStep.value = openStep.value === step.id ? null : step.id
}
function marker(step) {
  if (step.status === 'done') return '✓'
  if (step.status === 'error') return '!'
  return String(step.index)
}
function batchText(step) {
  const done = step.done != null ? step.done : 0
  return step.unit ? t('ws.step.batch_unit', [done, step.total, step.unit]) : t('ws.step.batch', [done, step.total])
}
</script>

<template>
  <div v-if="plan" class="plan-card">
    <div class="pc-head">
      <button type="button" class="pc-fold" :aria-expanded="ws.planOpen" @click="ws.planEvent('toggle')">
        <span class="pc-chev" :class="{ open: ws.planOpen }" aria-hidden="true">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="9 6 15 12 9 18" /></svg>
        </span>
        {{ t('ws.plan.label') }}
      </button>
      <span class="pc-bar" aria-hidden="true"><span class="pc-bar-fill" :style="{ width: progress.pct + '%' }" /></span>
      <span class="pc-count mono">{{ t('ws.plan.steps', [progress.done, progress.total]) }}</span>
    </div>
    <div v-if="ws.planOpen" class="pc-body">
      <ol class="pc-list">
        <li v-for="step in steps" :key="step.id" class="pc-step" :class="step.status">
          <span class="pc-marker" :class="{ live: step.status === 'running' && running }" :aria-label="t('ws.step.' + step.status)">{{ marker(step) }}</span>
          <div class="pc-main">
            <button
              type="button"
              class="pc-label"
              :class="{ clickable: step.notes > 0 }"
              :aria-expanded="step.notes > 0 ? openStep === step.id : undefined"
              @click="toggleStep(step)"
            >{{ step.label }}</button>
            <div v-if="step.hasBatch" class="pc-batch">
              <span class="pc-batch-track"><span class="pc-batch-fill" :style="{ width: step.batchPct + '%' }" /></span>
              <span class="pc-batch-txt mono">{{ batchText(step) }}</span>
            </div>
            <div v-if="openStep === step.id" class="pc-notes">
              <div v-for="n in notesOf(step.id)" :key="n.id" class="pc-note">
                <span class="pc-note-title">{{ n.title }}</span>
                <span v-if="n.text" class="pc-note-text">{{ n.text }}</span>
              </div>
            </div>
          </div>
        </li>
      </ol>
    </div>
  </div>
</template>

<style scoped>
/* Design values: planCardStyle, header row, bar track/fill, list area, step row. */
.plan-card {
  margin-bottom: 8px;
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  background: var(--paper, var(--bg));
  box-shadow: var(--shadow);
  animation: pc-in var(--dur) var(--ease-out);
}
@keyframes pc-in { from { opacity: 0; transform: translateY(4px); } }
.pc-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px var(--s-5);
}
.pc-fold {
  display: flex;
  align-items: center;
  gap: 9px;
  flex: 0 0 auto;
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
  color: var(--text-2);
  white-space: nowrap;
}
.pc-fold:hover { color: var(--text); }
.pc-chev {
  display: grid;
  place-items: center;
  color: var(--text-3);
  transition: transform var(--dur) var(--ease-out);
}
.pc-chev.open { transform: rotate(90deg); }
.pc-bar {
  flex: 1;
  min-width: 30px;
  height: 4px;
  background: var(--surface-2);
  display: block;
}
.pc-bar-fill {
  display: block;
  height: 4px;
  background: var(--orange);
  transition: width var(--dur-slow) var(--ease-out);
}
.pc-count { font-size: var(--fs-xs); color: var(--text-2); white-space: nowrap; }
.pc-body {
  border-top: 1px solid var(--border);
  padding: 4px var(--s-5) var(--s-4);
}
.pc-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 1px;
  max-height: 186px;
  overflow-y: auto;
  overflow-x: hidden;
}
.pc-step {
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 7px 0;
}
.pc-marker {
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
}
.pc-step.done .pc-marker { background: var(--text); border-color: var(--text); color: var(--bg); }
.pc-step.running .pc-marker { background: var(--orange); border-color: var(--orange); color: var(--on-orange); }
.pc-marker.live { animation: pc-pulse 1.15s ease-in-out infinite; }
.pc-step.error .pc-marker { border-color: var(--orange); color: var(--orange-text); }
@keyframes pc-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }
.pc-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 7px; }
.pc-label {
  text-align: left;
  font-size: var(--fs-sm);
  line-height: var(--lh-text);
  text-wrap: pretty;
  color: var(--text);
  cursor: default;
}
.pc-label.clickable { cursor: pointer; text-decoration: underline; text-decoration-color: var(--border-strong); text-underline-offset: 3px; }
.pc-label.clickable:hover { text-decoration-color: var(--text); }
.pc-step.done .pc-label { color: var(--text-2); }
.pc-step.running .pc-label { font-weight: var(--fw-bold); }
.pc-batch { display: flex; align-items: center; gap: 10px; }
.pc-batch-track { flex: 0 1 200px; min-width: 0; height: 5px; background: var(--surface-2); display: block; }
.pc-batch-fill { display: block; height: 5px; background: var(--text); transition: width var(--dur-slow) var(--ease-out); }
.pc-batch-txt { font-size: 11px; color: var(--text-2); white-space: nowrap; }
.pc-notes { display: flex; flex-direction: column; gap: 8px; padding: 2px 0 4px; }
.pc-note { display: flex; flex-direction: column; gap: 2px; }
.pc-note-title { font-size: var(--fs-sm); font-weight: var(--fw-bold); color: var(--text); }
.pc-note-text { font-size: var(--fs-sm); color: var(--text-2); line-height: var(--lh-text); }
@media (prefers-reduced-motion: reduce) {
  .plan-card, .pc-marker.live { animation: none; }
  .pc-chev, .pc-bar-fill, .pc-batch-fill { transition: none; }
}
/* Narrow chat column: tighter gutters; the steps counter never wraps the header. */
@container chat (max-width: 560px) {
  .pc-head { gap: 8px; padding: 8px var(--s-3); }
  .pc-body { padding: 4px var(--s-3) var(--s-3); }
  .pc-step { gap: 9px; }
  .pc-batch { flex-wrap: wrap; gap: 4px 10px; }
}
</style>
