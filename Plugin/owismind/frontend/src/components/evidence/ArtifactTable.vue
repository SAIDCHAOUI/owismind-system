<script setup>
// ArtifactTable.vue - full captured result table for Evidence Studio artifact tab.
// Renders meta.result.columns / rows as a scrollable table - the complete data the
// agent received, not the filtered EvidenceTable (which re-queries the source).
// Cell styling deliberately mirrors EvidenceResult.vue's conventions.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  // meta.result: { captured, columns, rows, row_count, truncated }
  result: { type: Object, default: null },
})

const captured = computed(() => !!(props.result && props.result.captured))
const columns = computed(() => (props.result && Array.isArray(props.result.columns) ? props.result.columns : []))
const rows = computed(() => (props.result && Array.isArray(props.result.rows) ? props.result.rows : []))
const rowCount = computed(() => {
  const rc = props.result && props.result.row_count
  if (typeof rc === 'number' && Number.isFinite(rc) && rc >= 0) return rc
  return rows.value.length
})
const truncated = computed(() => !!(props.result && props.result.truncated))

function cell(row, j) {
  const v = Array.isArray(row) ? row[j] : undefined
  return v == null ? '-' : String(v)
}
</script>

<template>
  <div class="art-table">
    <!-- Not captured: honest empty state (we never pretend to have data we don't). -->
    <div v-if="!captured" class="art-empty">
      <span>{{ t('art.table.empty') }}</span>
    </div>

    <template v-else>
      <div class="art-table-box">
        <div class="art-table-scroll">
          <table>
            <thead>
              <tr>
                <th v-for="(col, j) in columns" :key="j">{{ col }}</th>
              </tr>
            </thead>
            <tbody>
              <!-- Cells indexed by column so a short row never shifts the grid -->
              <tr v-for="(row, i) in rows" :key="i">
                <td v-for="(col, j) in columns" :key="j">{{ cell(row, j) }}</td>
              </tr>
              <!-- Empty rows guard -->
              <tr v-if="rows.length === 0">
                <td :colspan="columns.length || 1" class="art-table-none">{{ t('art.table.empty') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="art-table-info">
        <span>{{ t('ev.proof.result.rows', [rowCount]) }}</span>
        <span v-if="truncated" class="art-trunc">{{ t('art.table.truncated') }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* No z-index ≥ 5: chips popover (z-index 5, L043) must stay above. */
.art-table {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  min-height: 0;
}

/* Scrollable viewport - taller than EvidenceResult's mini-table since this IS
   the data browser tab, not a secondary proof section. */
.art-table-box {
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  overflow: hidden;
}
.art-table-scroll {
  max-height: 480px;
  overflow-y: auto;
  overflow-x: auto;
}

/* Replicates EvidenceResult.vue cell styling exactly */
table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: var(--fs-sm);
}
thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--surface);
  padding: 6px 12px;
  text-align: left;
  box-shadow: inset 0 -1px 0 var(--border);
  color: var(--text-2);
  font-weight: 500;
  white-space: nowrap;
  user-select: none;
}
tbody td {
  padding: 5px 12px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 320px;
}
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover td { background: var(--surface-hover); }

.art-table-none {
  color: var(--text-3);
  text-align: center;
  padding: var(--s-5) !important;
}

.art-table-info {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  font-size: var(--fs-xs);
  color: var(--text-3);
}
/* Truncation = caveat on proof - orange text (AA token) matching EvidenceResult.vue */
.art-trunc { color: var(--orange-text); }

/* Empty state when result was not captured */
.art-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--s-8) var(--s-4);
  font-size: var(--fs-sm);
  color: var(--text-3);
  border: 1px dashed var(--border);
  border-radius: var(--r-sm);
  text-align: center;
}
</style>
