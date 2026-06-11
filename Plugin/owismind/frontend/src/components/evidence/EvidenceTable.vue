<script setup>
// Evidence rows table — live rows of the matched source table under the
// agent's (or user-modified) filters. Sticky header, click-to-sort, bounded
// 50-rows pages driven by the store (LIMIT n+1 server-side -> has_more).
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEvidenceStore } from '../../stores/evidence.js'
import { Icon } from '../ui'

const { t } = useI18n()
const evidence = useEvidenceStore()
const columns = computed(() => (evidence.meta && evidence.meta.columns) || [])

function sortDir(name) {
  const s = evidence.sort
  return s && s.column === name ? s.dir : ''
}
function cell(row, name) {
  const v = row[name]
  return v == null ? '—' : String(v)
}
</script>

<template>
  <!-- `busy` (55% dim) only applies to refreshes with REAL rows on screen: the
       first-load skeleton must keep full opacity or its shimmer washes out. -->
  <div class="ev-table" :class="{ busy: evidence.rowsLoading && evidence.rows.length > 0 }">
    <div class="ev-table-scroll">
      <table>
        <thead>
          <tr>
            <th v-for="c in columns" :key="c.name" :class="{ sorted: sortDir(c.name) }">
              <button type="button" class="th-btn" @click="evidence.setSort(c.name)">
                <span class="th-label">{{ c.name }}</span>
                <span v-if="sortDir(c.name)" class="th-sort">
                  <Icon :name="sortDir(c.name) === 'asc' ? 'chevronUp' : 'chevronDown'" />
                </span>
              </button>
            </th>
          </tr>
        </thead>
        <!-- First load (no rows yet): shimmer skeleton rows instead of a blank area.
             Refreshes with rows on screen keep the lighter `.busy` opacity dim. -->
        <tbody v-if="evidence.rowsLoading && !evidence.rows.length" aria-hidden="true">
          <tr v-for="n in 8" :key="'sk-' + n" class="sk-row">
            <td v-for="c in columns" :key="c.name"><span class="sk-cell" /></td>
          </tr>
        </tbody>
        <tbody v-else>
          <tr v-for="(row, i) in evidence.rows" :key="evidence.page + '-' + i">
            <td v-for="c in columns" :key="c.name">{{ cell(row, c.name) }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!evidence.rows.length && !evidence.rowsLoading" class="ev-table-empty">
        {{ t('ev.table.empty') }}
      </div>
    </div>
    <!-- Recoverable rows-level error: the chips above stay mounted and usable. -->
    <div v-if="evidence.rowsError" class="ev-table-error">
      <span>{{ t('ev.error') }}</span>
      <button @click="evidence.refreshRows()">{{ t('ev.retry') }}</button>
    </div>
    <div class="ev-table-foot">
      <span class="mono page">{{ t('ev.table.page', [evidence.page + 1]) }}</span>
      <span class="spacer" />
      <button :disabled="evidence.page === 0 || evidence.rowsLoading"
              :title="t('ev.table.prev')" @click="evidence.prevPage()">
        <Icon name="chevronLeft" />
      </button>
      <button :disabled="!evidence.hasMore || evidence.rowsLoading"
              :title="t('ev.table.next')" @click="evidence.nextPage()">
        <Icon name="chevronRight" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.ev-table {
  display: flex; flex-direction: column; min-height: 0; flex: 1;
  border: 1px solid var(--border); border-radius: var(--r-sm); overflow: hidden;
  transition: opacity var(--dur) var(--ease);
}
.ev-table.busy { opacity: 0.55; }
/* Block stale row interactions while loading; the foot buttons are :disabled-gated. */
.ev-table.busy tbody { pointer-events: none; }
.ev-table-scroll { flex: 1; min-height: 0; overflow: auto; }
/* separate + spacing 0: with `collapse`, the th border scrolls away from a
   sticky header — paint the line as an inset shadow so it sticks with it. */
table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: var(--fs-sm); }
thead th {
  position: sticky; top: 0; z-index: 1; background: var(--surface);
  text-align: left; box-shadow: inset 0 -1px 0 var(--border);
  color: var(--text-2); font-weight: 500; white-space: nowrap;
  user-select: none;
}
thead th:hover { color: var(--text); }
thead th.sorted { color: var(--orange); }
.th-btn {
  display: flex; align-items: center; gap: 4px; width: 100%;
  padding: 8px 12px; color: inherit; text-align: left; cursor: pointer;
}
.th-sort :deep(.ui-icon) { width: 12px; height: 12px; vertical-align: -2px; }
tbody td {
  padding: 7px 12px; border-bottom: 1px solid var(--border);
  color: var(--text); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; max-width: 260px;
}
tbody tr:last-child td { border-bottom: none; }
/* First-load skeleton rows — gradient sweep, alternating widths for a natural look. */
.sk-cell {
  display: block; height: 12px; border-radius: 4px; width: 70%;
  background: linear-gradient(90deg, var(--surface-2) 25%, var(--surface-hover) 50%, var(--surface-2) 75%);
  background-size: 200% 100%;
  animation: shimmer-sweep 1.4s linear infinite;
}
.sk-row:nth-child(even) .sk-cell { width: 45%; }
@media (prefers-reduced-motion: reduce) {
  .sk-cell { animation: none; }
}
.ev-table-empty { padding: var(--s-5); color: var(--text-3); font-size: var(--fs-sm); }
.ev-table-error {
  display: flex; align-items: center; gap: var(--s-3);
  padding: 6px 12px; border-top: 1px solid var(--border);
  color: var(--danger); font-size: var(--fs-sm);
}
.ev-table-error button {
  padding: 2px 10px; border-radius: var(--r-sm); color: var(--text-2);
  transition: all var(--dur) var(--ease);
}
.ev-table-error button:hover { background: var(--surface-hover); color: var(--text); }
.ev-table-foot {
  display: flex; align-items: center; gap: var(--s-2);
  padding: 6px 12px; border-top: 1px solid var(--border); background: var(--surface);
}
.ev-table-foot .page { font-size: 11px; color: var(--text-3); }
.ev-table-foot .spacer { flex: 1; }
.ev-table-foot button {
  padding: 4px; border-radius: var(--r-sm); color: var(--text-2);
  transition: all var(--dur) var(--ease);
}
.ev-table-foot button:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
.ev-table-foot button:disabled { opacity: 0.35; cursor: not-allowed; }
.ev-table-foot button :deep(.ui-icon) { width: 14px; height: 14px; }
</style>
