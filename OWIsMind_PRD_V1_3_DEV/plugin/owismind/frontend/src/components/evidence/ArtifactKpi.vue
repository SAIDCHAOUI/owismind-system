<script setup>
// ArtifactKpi.vue - a big "headline figure" card for an Evidence Studio KPI
// artifact. The figures are extracted SERVER-SIDE (chart_payload.build_kpi_payload)
// from the captured result, so the agent only named the value column; this
// component just formats and draws. Shows the value big, plus an optional
// delta / delta% with an up/down arrow (green up, red down).
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  // Server-built payload: { ok, label, value, value_raw, delta?, delta_pct?, reason }
  data: { type: Object, default: null },
  title: { type: String, default: '' },
  // Agent-provided unit of the figure (e.g. 'EUR', '%'), shown after the value.
  unit: { type: String, default: '' },
  // Agent-provided one-sentence caption (what the figure represents).
  description: { type: String, default: '' },
})

const ok = computed(() => !!(props.data && props.data.ok))

// Group-aware number formatting (locale-independent thousands separators).
function fmt(n) {
  if (n == null || !Number.isFinite(Number(n))) return '-'
  const v = Number(n)
  const abs = Math.abs(v)
  // Compact large numbers for readability (1.2M, 340k); keep small ones exact.
  if (abs >= 1e9) return (v / 1e9).toFixed(2).replace(/\.?0+$/, '') + ' Md'
  if (abs >= 1e6) return (v / 1e6).toFixed(2).replace(/\.?0+$/, '') + ' M'
  if (abs >= 1e4) return (v / 1e3).toFixed(1).replace(/\.?0+$/, '') + ' k'
  return v.toLocaleString()
}

const valueText = computed(() => (ok.value ? fmt(props.data.value) : '-'))
const label = computed(() => (props.data && props.data.label) || props.title || '')

const hasDelta = computed(
  () => ok.value && (props.data.delta != null || props.data.delta_pct != null),
)
const deltaSign = computed(() => {
  const d = props.data.delta != null ? props.data.delta : props.data.delta_pct
  return d > 0 ? 'up' : d < 0 ? 'down' : 'flat'
})
const deltaText = computed(() => {
  if (!hasDelta.value) return ''
  const parts = []
  if (props.data.delta_pct != null) {
    const p = Number(props.data.delta_pct)
    parts.push((p > 0 ? '+' : '') + p.toFixed(1) + '%')
  }
  if (props.data.delta != null) parts.push((props.data.delta > 0 ? '+' : '') + fmt(props.data.delta))
  return parts.join(' · ')
})
</script>

<template>
  <div class="art-kpi">
    <div v-if="!ok" class="art-empty">
      <span class="art-empty-icon">#</span>
      <span>{{ t('art.kpi.empty') }}</span>
    </div>
    <div v-else class="kpi-card">
      <span class="kpi-label">{{ label }}</span>
      <span class="kpi-value">
        {{ valueText }}<span v-if="unit" class="kpi-unit">{{ ' ' + unit }}</span>
      </span>
      <span v-if="hasDelta" class="kpi-delta" :class="deltaSign">
        <span class="kpi-arrow" aria-hidden="true">
          {{ deltaSign === 'up' ? '▲' : deltaSign === 'down' ? '▼' : '▬' }}
        </span>
        {{ deltaText }}
      </span>
      <span v-if="description" class="kpi-desc">{{ description }}</span>
    </div>
  </div>
</template>

<style scoped>
.art-kpi { display: flex; min-height: 0; }
.kpi-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--s-2);
  width: 100%;
  padding: var(--s-6) var(--s-5);
  border: 1px solid var(--border);
  border-radius: var(--r);
  background: var(--surface);
}
.kpi-label {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-3);
}
.kpi-value {
  font-size: 40px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
.kpi-delta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
  font-weight: 600;
  padding: 3px 10px;
  border-radius: var(--r-pill);
}
.kpi-arrow { font-size: 10px; }
.kpi-unit { font-size: 20px; font-weight: 600; color: var(--text-2); }
.kpi-desc { font-size: var(--fs-sm); color: var(--text-2); }
.kpi-delta.up { color: var(--success, #10b981); background: rgba(16, 185, 129, 0.12); }
.kpi-delta.down { color: var(--danger, #ef4444); background: rgba(239, 68, 68, 0.12); }
.kpi-delta.flat { color: var(--text-3); background: var(--surface-2); }
.art-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  width: 100%;
  padding: var(--s-8) var(--s-4);
  font-size: var(--fs-sm);
  color: var(--text-3);
  border: 1px dashed var(--border);
  border-radius: var(--r-sm);
  text-align: center;
}
.art-empty-icon { font-size: 28px; opacity: 0.4; font-weight: 700; }
</style>
