<script setup>
// Evidence Studio panel — the RIGHT column that opens after a generation: the
// trust surface (trust badge + sources + filter chips + calculation steps +
// captured agent result + live rows of the matched source table + the agent's
// raw SQL). All data lives in the evidence store; this component only renders
// its states (loading / error / degraded / interactive).
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEvidenceStore } from '../../stores/evidence.js'
import { Icon } from '../ui'
import EvidenceTrust from './EvidenceTrust.vue'
import EvidenceSources from './EvidenceSources.vue'
import EvidenceChips from './EvidenceChips.vue'
import EvidenceCalc from './EvidenceCalc.vue'
import EvidenceResult from './EvidenceResult.vue'
import EvidenceTable from './EvidenceTable.vue'
import EvidenceSql from './EvidenceSql.vue'

const { t } = useI18n()
const evidence = useEvidenceStore()
const meta = computed(() => evidence.meta)

// Marker of the ENRICHED trust-layer contract: a v1 meta (no verification
// block) must render pixel-identical to today — no badge, no extra labels.
// The proof sections gate themselves on their own optional meta fields.
const enriched = computed(() => !!(meta.value && meta.value.verification))

// Drill-down state lands with the store workstream (IMPL-5): guard every
// access so this panel keeps working against a store build without it.
const drill = computed(() => evidence.drill || null)
const drillLabels = computed(() => {
  const labels = drill.value && Array.isArray(drill.value.labels) ? drill.value.labels : []
  return labels
    .map((l) => l.column + ' = ' + (l.value == null ? '—' : String(l.value)))
    .join(', ')
})
function onExitDrill() {
  const fn = evidence.exitDrill
  if (typeof fn === 'function') fn()
}

// Degraded mode shows WHY the interactive view is unavailable. With best-effort
// SQL mapping the remaining reasons are "the agent's table maps to no SQL
// dataset in this project" or "no usable SQL"; anything rarer (unparseable
// text, multiple statements) falls back to the generic message.
const DEGRADED_KEYS = {
  no_matching_dataset: 'ev.degraded.no_dataset',
  no_sql: 'ev.degraded.no_sql',
  no_successful_sql: 'ev.degraded.no_sql',
}
const degradedMessage = computed(() => {
  const reason = meta.value && meta.value.reason
  const key = DEGRADED_KEYS[reason]
  return key ? t(key) : t('ev.degraded')
})
</script>

<template>
  <aside class="evidence">
    <header class="ev-head">
      <div class="ev-title">
        <Icon name="shield" />
        <span>{{ t('ev.title') }}</span>
        <span v-if="meta && meta.dataset" class="ev-dataset mono">{{ meta.dataset }}</span>
      </div>
      <div class="ev-actions">
        <button class="ev-close" :title="t('ev.close')" @click="evidence.close()">
          <Icon name="x" />
        </button>
      </div>
    </header>

    <div class="ev-body">
      <!-- Meta loading: shimmer skeleton shaped like the upcoming content
           (trust banner + chips row + table block) instead of a bare text line. -->
      <div v-if="evidence.loading" class="ev-skeleton" :aria-label="t('ev.loading')">
        <span class="sk sk-band" />
        <div class="sk-chips">
          <span v-for="n in 3" :key="n" class="sk sk-chip" />
        </div>
        <div class="sk sk-table" />
      </div>
      <div v-else-if="evidence.error" class="ev-state error">{{ t('ev.error') }}</div>
      <!-- Degraded: the honest "declared" badge ABOVE the reason — the claim
           level is exactly what a degraded panel is about. -->
      <template v-else-if="meta && !meta.available">
        <EvidenceTrust />
        <div class="ev-state">{{ degradedMessage }}</div>
      </template>
      <template v-else-if="meta">
        <!-- Proof sections, most business-readable first (spec §6). Each new
             section gates itself on its own OPTIONAL meta field, so a v1 meta
             renders exactly the v1 panel (chips + table only). -->
        <EvidenceTrust v-if="enriched" />
        <EvidenceSources />
        <EvidenceChips />
        <EvidenceCalc />
        <EvidenceResult />
        <!-- Drill banner: the rows table below is scoped to ONE result row. -->
        <div v-if="drill" class="ev-drill-band">
          <Icon name="filter" />
          <span class="ev-drill-text">{{ t('ev.proof.drill.banner', [drillLabels]) }}</span>
          <button class="ev-drill-exit" :title="t('ev.proof.drill.exit')" @click="onExitDrill">
            <Icon name="x" />
          </button>
        </div>
        <span v-if="enriched" class="ev-explore">{{ t('ev.proof.explore') }}</span>
        <EvidenceTable />
      </template>
    </div>

    <EvidenceSql v-if="meta && meta.sql" :sql="meta.sql" />
  </aside>
</template>

<style scoped>
.evidence {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  background: var(--bg);
  animation: ev-slide-in var(--dur-slow) var(--ease) both;
}
/* The panel docks on the RIGHT — it slides in from the right edge. */
@keyframes ev-slide-in {
  from { opacity: 0; transform: translateX(28px); }
  to { opacity: 1; transform: none; }
}
/* Staggered content reveal: the header rises first, then each body block (the
   skeleton while loading, then chips and table when the meta lands — the v-if
   swap re-runs the animation, so loaded content fades in over the skeleton). */
.ev-head { animation: ev-rise var(--dur-slow) var(--ease) both; }
.ev-body > * { animation: ev-rise var(--dur-slow) var(--ease) both; }
.ev-body > * + * { animation-delay: 90ms; }
@keyframes ev-rise {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: none; }
}
/* Meta-loading skeleton — gradient sweep over content-shaped placeholders. */
.ev-skeleton { display: flex; flex-direction: column; gap: var(--s-4); flex: 1; min-height: 0; }
.sk {
  display: block; border-radius: var(--r-sm);
  background: linear-gradient(90deg, var(--surface-2) 25%, var(--surface-hover) 50%, var(--surface-2) 75%);
  background-size: 200% 100%;
  animation: shimmer-sweep 1.4s linear infinite;
}
.sk-chips { display: flex; gap: var(--s-2); }
.sk-band { width: 65%; height: 24px; border-radius: var(--r-pill); }
.sk-chip { width: 110px; height: 28px; border-radius: var(--r-pill); }
.sk-table { flex: 1; min-height: 220px; }
@media (prefers-reduced-motion: reduce) {
  .evidence, .ev-head, .ev-body > *, .sk { animation: none; }
}
.ev-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: var(--s-4) var(--s-5); border-bottom: 1px solid var(--border);
}
.ev-title { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: var(--fs-md); }
.ev-title :deep(.ui-icon) { width: 16px; height: 16px; color: var(--orange); }
.ev-dataset { font-size: 11px; color: var(--text-3); font-weight: 400; }
.ev-actions { display: flex; align-items: center; gap: var(--s-3); }
.ev-close { padding: 4px; border-radius: var(--r-sm); color: var(--text-3); transition: all var(--dur) var(--ease); }
.ev-close:hover { background: var(--surface-hover); color: var(--text); }
.ev-close :deep(.ui-icon) { width: 16px; height: 16px; }
.ev-body {
  flex: 1; min-height: 0; overflow-y: auto;
  display: flex; flex-direction: column; gap: var(--s-4); padding: var(--s-5);
}
.ev-state { color: var(--text-3); font-size: var(--fs-sm); }
.ev-state.error { color: var(--danger); }

/* Drill banner — discreet dashed-orange band (same grammar as the "modified"
   badge: the table scope was narrowed by the user). NO z-index: the chips
   popover (z-index 5, L043) must stay above every proof section. */
.ev-drill-band {
  display: flex; align-items: center; gap: var(--s-2);
  padding: 4px 10px; border: 1px dashed var(--orange); border-radius: var(--r-sm);
  background: var(--orange-soft);
}
.ev-drill-band :deep(.ui-icon) { flex: none; width: 12px; height: 12px; color: var(--orange-text); }
.ev-drill-text {
  flex: 1; min-width: 0; font-size: var(--fs-xs); color: var(--orange-text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ev-drill-exit {
  flex: none; padding: 2px; border-radius: var(--r-sm); color: var(--orange-text);
  transition: all var(--dur) var(--ease);
}
.ev-drill-exit:hover { background: var(--surface-hover); color: var(--text); }
.ev-drill-exit :deep(.ui-icon) { width: 12px; height: 12px; }
/* Dark: swap the light tint for the translucent orange patch — entire
   selector inside :global (scoped+theme rule F2/L022). */
:global(body[data-theme="dark"] .ev-drill-band) { background: var(--orange-soft-dark); }

/* "Explore source data" label over the live table (same pattern as
   .ev-chips-title) — only rendered for the enriched contract. */
.ev-explore {
  font-size: var(--fs-xs); color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.04em;
  /* Pull the table visually under its label without changing the table flex. */
  margin-bottom: calc(-1 * var(--s-2));
}
</style>
