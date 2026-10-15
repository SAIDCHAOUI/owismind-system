<script setup>
// Journal tab - the agent's working notes, grouped by plan step (plan order), each
// stamped with its run time (mm:ss since the run started). A note bound to a result
// (sql_id) opens the provenance drawer; notes without a step (or whose step was
// removed by a plan revision) land in a trailing "off plan" group.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { journalGroups } from '../../composables/workspaceModel.js'
import { useWorkspaceStore } from '../../stores/workspace.js'

const props = defineProps({
  state: { type: Object, required: true },
  running: { type: Boolean, default: false },
})
const { t } = useI18n()
const ws = useWorkspaceStore()

const groups = computed(() => journalGroups(props.state))
const empty = computed(() => !props.state.plan && !props.state.notes.length)

function clock(ts) {
  if (typeof ts !== 'number' || !Number.isFinite(ts)) return ''
  const s = Math.max(0, Math.round(ts))
  return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0')
}
function marker(g) {
  if (!g.index) return '·'
  if (g.status === 'done') return '✓'
  if (g.status === 'error') return '!'
  return String(g.index)
}
function groupTitle(g) {
  if (!g.index) return g.removed ? t('ws.journal.removed') : t('ws.journal.other')
  return t('ws.step.label', [g.index]) + ' : ' + g.label
}
function emptyText(g) {
  if (g.status === 'running' && props.running) return t('ws.journal.running')
  if (g.status === 'todo' && props.running) return t('ws.journal.waiting')
  return t('ws.journal.no_note')
}
</script>

<template>
  <div class="journal">
    <div v-if="empty" class="empty">
      <div class="empty-t">{{ t('ws.journal.empty_t') }}</div>
      <p class="empty-b">{{ t('ws.journal.empty_b') }}</p>
    </div>
    <template v-else>
      <section v-if="state.plan && state.plan.mission" class="mission">
        <div class="label">{{ t('ws.mission') }}</div>
        <p class="mission-text">{{ state.plan.mission }}</p>
      </section>
      <section v-for="g in groups" :key="g.key" class="group" :class="g.status">
        <div class="group-head">
          <span class="marker">{{ marker(g) }}</span>
          <span class="group-title">{{ groupTitle(g) }}</span>
          <button
            v-if="g.widgets"
            type="button"
            class="group-meta"
            @click="ws.setTab('board')"
          >{{ t('ws.journal.see_board', [g.widgets]) }}</button>
        </div>
        <div v-if="g.notes.length" class="notes">
          <article v-for="n in g.notes" :key="n.id" class="note" :class="n.kind">
            <div class="note-head">
              <span v-if="clock(n.ts)" class="ts mono">{{ clock(n.ts) }}</span>
              <span class="kind mono">{{ t('ws.note.kind.' + n.kind) }}</span>
              <span class="note-title">{{ n.title }}</span>
            </div>
            <p v-if="n.text" class="note-text">{{ n.text }}</p>
            <button
              v-if="n.sql_id"
              type="button"
              class="proof"
              @click="ws.openProvenance(n.sql_id)"
            >{{ t('ws.note.proof') }}</button>
          </article>
        </div>
        <div v-else class="group-empty">
          <span v-if="g.status === 'running' && running" class="live" aria-hidden="true" />
          {{ emptyText(g) }}
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.journal { display: flex; flex-direction: column; }
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
.mission-text { margin: 0; font-size: var(--fs-base); line-height: var(--lh-text); text-wrap: pretty; }
.group { padding: var(--s-5) 0; }
.group + .group { border-top: 1px solid var(--border); }
.group-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding-bottom: var(--s-4);
}
.marker {
  flex: 0 0 18px;
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  align-self: center;
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: var(--fw-bold);
  border: 1px solid var(--border-strong);
  color: var(--text-3);
  border-radius: var(--r-xs);
}
.group.done .marker { background: var(--text); border-color: var(--text); color: var(--bg); }
.group.running .marker { background: var(--orange); border-color: var(--orange); color: var(--on-orange); }
.group.error .marker { border-color: var(--orange); color: var(--orange-text); }
.group-title {
  flex: 1 1 auto;
  min-width: 0;
  font-size: var(--fs-base);
  font-weight: var(--fw-bold);
  line-height: var(--lh-text);
  text-wrap: pretty;
}
.group-meta {
  flex: 0 0 auto;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.group-meta:hover { color: var(--text); }
.notes { display: flex; flex-direction: column; gap: var(--s-4); }
.note { animation: note-in var(--dur) var(--ease-out) both; }
@keyframes note-in { from { opacity: 0; transform: translateY(4px); } }
.note-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}
.ts { font-size: 11px; color: var(--text-3); }
.kind { font-size: 11px; font-weight: var(--fw-bold); color: var(--text-3); white-space: nowrap; }
/* A finding is what the user came for: its kind label takes the orange signal. */
.note.find .kind { color: var(--orange-text); }
.note-title {
  flex: 1 1 auto;
  min-width: 0;
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  line-height: var(--lh-text);
  text-wrap: pretty;
}
.note-text {
  margin: 7px 0 0;
  font-size: var(--fs-sm);
  color: var(--text);
  line-height: var(--lh-text);
  text-wrap: pretty;
  white-space: pre-line;
}
.note.done {
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--surface);
}
.proof {
  margin-top: 8px;
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
  color: var(--orange-text);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.proof:hover { color: var(--text); }
.group-empty {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--fs-sm);
  color: var(--text-3);
}
.live {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  background: var(--orange);
  animation: live-pulse 1.15s ease-in-out infinite;
}
@keyframes live-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
.empty { max-width: 440px; padding: var(--s-6) 0; }
.empty-t { font-size: var(--fs-base); font-weight: var(--fw-bold); padding-bottom: 8px; }
.empty-b { margin: 0; font-size: var(--fs-sm); color: var(--text-2); line-height: var(--lh-text); }
@media (prefers-reduced-motion: reduce) {
  .note, .live { animation: none; }
}
</style>
