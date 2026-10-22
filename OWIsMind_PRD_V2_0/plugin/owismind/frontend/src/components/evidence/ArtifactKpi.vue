<script setup>
// ArtifactKpi.vue - a big "headline figure" card for an Evidence Studio KPI
// artifact. The figures are extracted SERVER-SIDE (chart_payload.build_kpi_payload)
// from the captured result, so the agent only named the value column; this
// component just formats and draws. Shows the value big, plus an optional
// delta / delta% with an up/down arrow (green up, red down).
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatStatNumber } from '../../composables/sourceModel.js'

const { t, locale } = useI18n()

const props = defineProps({
  // Server-built payload: { ok, label, value, value_raw, delta?, delta_pct?, reason }
  data: { type: Object, default: null },
  title: { type: String, default: '' },
  // Agent-provided unit of the figure (e.g. 'EUR', '%'), shown after the value.
  unit: { type: String, default: '' },
  // Agent-provided one-sentence caption (what the figure represents).
  description: { type: String, default: '' },
  // Hosted inside a dashboard card (V2): flat figure, no frame of its own.
  bare: { type: Boolean, default: false },
})

const ok = computed(() => !!(props.data && props.data.ok))

// Locale-aware number formatting: compact for large magnitudes (1.2M / 1,2 M -
// the card must stay readable at a glance), exact grouping below.
function fmt(n) {
  if (n == null || !Number.isFinite(Number(n))) return '-'
  const v = Number(n)
  if (Math.abs(v) >= 1e4) {
    try {
      return new Intl.NumberFormat(locale.value, {
        notation: 'compact',
        maximumFractionDigits: 2,
      }).format(v)
    } catch (e) {
      /* older runtime without compact notation: fall through to exact */
    }
  }
  return formatStatNumber(v, locale.value)
}

const valueText = computed(() => (ok.value ? fmt(props.data.value) : '-'))
// Trust layer: the compact display rounds - the EXACT figure stays reachable on
// hover of the big value (locale-grouped, full precision).
const valueTitle = computed(() =>
  (ok.value && props.data.value != null
    ? formatStatNumber(props.data.value, locale.value)
    : ''),
)
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
    <div v-else class="kpi-card" :class="{ bare }">
      <span class="kpi-label">{{ label }}</span>
      <span class="kpi-value" :title="valueTitle || null">
        {{ valueText }}<span v-if="unit" class="kpi-unit">{{ '\u00A0' + unit }}</span>
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
/* Charte KPI recipe: square card, 1px visible frame, 3px orange TOP rule, upper-
   case micro-label, big heavy figure. The headline figure is the focal element
   of this tab - everything else is subordinate. */
.kpi-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--s-2);
  width: 100%;
  padding: var(--s-6) var(--s-5);
  border: 1px solid var(--border-strong);
  border-top: 3px solid var(--orange);
  border-radius: 0;
  background: var(--bg);
}
/* V2 dashboard: the widget card is the frame - no second border, no accent rule. */
.kpi-card.bare {
  padding: 0;
  border: 0;
  background: transparent;
  gap: var(--s-1);
}
.kpi-card.bare .kpi-value { font-size: var(--fs-2xl); }
.kpi-card.bare .kpi-label { text-transform: none; letter-spacing: 0; font-size: var(--fs-xs); }
.kpi-label {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-2);
}
.kpi-value {
  font-size: 40px;
  font-weight: var(--fw-heavy);
  line-height: 1.1;
  letter-spacing: var(--tracking-tight);
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
/* Delta chip: square, tinted, arrow + sign + figure (color is never the only
   signal). */
.kpi-delta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 0;
}
.kpi-arrow { font-size: 10px; }
.kpi-unit { font-size: 20px; font-weight: 600; color: var(--text-2); }
.kpi-desc { font-size: var(--fs-sm); color: var(--text-2); }
.kpi-delta.up { color: var(--success); background: var(--success-soft); }
.kpi-delta.down { color: var(--danger); background: var(--danger-soft); }
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
  border-radius: 0;
  text-align: center;
}
.art-empty-icon { font-size: 28px; opacity: 0.4; font-weight: 700; }
</style>
