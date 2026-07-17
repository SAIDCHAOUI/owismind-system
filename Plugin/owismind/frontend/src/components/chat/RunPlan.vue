<script setup>
// Durable analysis plan card (v1.3 Durable Step Shell) - the CoBuild-like visible
// plan: goal, N/M progression, one row per step whose status ticks live. Pure
// display over `plan` ({ goal, steps:[{id,title,status,durationS}] }); the reducer
// (timelineModel.js) owns every mutation. Orange charter: square geometry, 1px
// rules, semantic tokens, orange ONLY on the running step, zero decorative effect.
import { computed } from 'vue'
import { useTr } from '../../composables/useTr.js'

const props = defineProps({
  plan: { type: Object, required: true },
})
const { t } = useTr()

const doneCount = computed(
  () => (props.plan.steps || []).filter((s) => s.status === 'completed').length,
)
const total = computed(() => (props.plan.steps || []).length)

// Stable status -> i18n key + visual class. Unknown statuses render as pending
// (a forward-compatible fallback, never a crash).
const STATUS_KEYS = {
  pending: 'runplan.pending',
  running: 'runplan.running',
  retrying: 'runplan.retrying',
  completed: 'runplan.completed',
  failed: 'runplan.failed',
  superseded: 'runplan.superseded',
}
function statusKey(s) {
  return STATUS_KEYS[s] || STATUS_KEYS.pending
}
function statusClass(s) {
  return STATUS_KEYS[s] ? 'st-' + s : 'st-pending'
}
</script>

<template>
  <section class="run-plan" :aria-label="t('runplan.title')">
    <header class="rp-head">
      <span class="rp-title">{{ t('runplan.title') }}</span>
      <span class="rp-count">{{ doneCount }} / {{ total }}</span>
    </header>
    <p v-if="plan.goal" class="rp-goal">{{ plan.goal }}</p>
    <ol class="rp-steps">
      <li v-for="step in plan.steps" :key="step.id" class="rp-step" :class="statusClass(step.status)">
        <span class="rp-marker" aria-hidden="true"></span>
        <span class="rp-step-title">{{ step.title || step.id }}</span>
        <span class="rp-status">{{ t(statusKey(step.status)) }}</span>
      </li>
    </ol>
  </section>
</template>

<style scoped>
/* Square, flat, 1px rules - Orange charter. Orange appears ONLY on the running
   step's marker + status; everything else is ink on surface. */
.run-plan {
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--bg);
  padding: var(--s-3) var(--s-4);
  margin-bottom: var(--s-3);
}
.rp-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  padding-bottom: var(--s-2);
  margin-bottom: var(--s-2);
}
.rp-title {
  font-size: 12px;
  font-weight: var(--fw-bold);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-2);
}
.rp-count {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text-2);
}
.rp-goal {
  margin: 0 0 var(--s-2);
  font-size: 13px;
  color: var(--text-2);
}
.rp-steps {
  list-style: none;
  margin: 0;
  padding: 0;
}
.rp-step {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  padding: var(--s-1) 0;
  font-size: 13px;
  color: var(--text);
}
/* Square status marker: a 10x10 flat square, never a dot/halo. */
.rp-marker {
  width: 10px;
  height: 10px;
  flex-shrink: 0;
  border: 1px solid var(--border-strong);
  background: transparent;
}
.rp-step-title {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rp-status {
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-3);
}
/* Running: THE single orange accent of the card. */
.st-running .rp-marker { background: var(--orange); border-color: var(--orange); }
.st-running .rp-status { color: var(--orange-text); font-weight: var(--fw-semibold); }
.st-retrying .rp-marker { background: var(--warn); border-color: var(--warn); }
.st-completed .rp-marker { background: var(--text); border-color: var(--text); }
.st-completed .rp-step-title { color: var(--text-2); }
.st-failed .rp-marker { background: var(--danger); border-color: var(--danger); }
.st-failed .rp-status { color: var(--danger); }
.st-superseded .rp-step-title { text-decoration: line-through; color: var(--text-3); }
</style>
