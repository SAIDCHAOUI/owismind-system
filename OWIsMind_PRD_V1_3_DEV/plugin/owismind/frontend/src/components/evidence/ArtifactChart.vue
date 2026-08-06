<script setup>
// ArtifactChart.vue - interactive chart for an Evidence Studio artifact, rendered
// with Chart.js. The DATA is built server-side in Python (chart_payload.py) and
// arrives ready as { labels, datasets } in `data`; this component only chooses the
// visual style/options and draws. Chart.js gives real interactivity: hover
// tooltips, clickable legend (toggle series), animated draw-in, responsive resize.
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import Chart from 'chart.js/auto'
import { formatStatNumber } from '../../composables/sourceModel.js'

const { t, locale } = useI18n()

const props = defineProps({
  // Artifact chart spec: { type: 'line'|'bar'|'pie', x, y[], style?, x_label?, y_label?, unit? }
  chart: { type: Object, required: true },
  // Server-built Chart.js payload: { ok, labels, datasets, truncated, reason }
  data: { type: Object, default: null },
  // Title for the chart + aria-label
  title: { type: String, default: '' },
  // Agent-provided one-sentence caption (what the chart shows), shown below it.
  description: { type: String, default: '' },
})

const canvasEl = ref(null)
let instance = null
let themeObserver = null

// Canvas cannot use CSS var() - resolve the active theme's colors at draw time.
function cssVar(name, fallback) {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
    return v || fallback
  } catch (e) {
    return fallback
  }
}

// Series palette: the brand orange first, then distinct, color-blind-friendly hues.
function palette() {
  return [
    cssVar('--orange', '#ff7a00'),
    '#5b8dee', '#40c9a2', '#e87d5e', '#a78bfa', '#f59e0b', '#10b981', '#ef4444',
  ]
}

function withAlpha(color, a) {
  const m = /^#([0-9a-f]{6})$/i.exec(color)
  if (m) {
    const n = parseInt(m[1], 16)
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`
  }
  return color
}

function isOk() {
  return !!(props.data && props.data.ok && Array.isArray(props.data.datasets))
}

// Column name -> readable label ('Revenue_EUR' -> 'Revenue EUR'). Used everywhere
// the agent did not provide a human label, so a chart NEVER ships raw snake_case.
function prettyLabel(name) {
  return String(name == null ? '' : name).replace(/_/g, ' ').trim()
}

// Effective, always-present labels: the agent's explicit labels win; otherwise
// they are derived from the column names, so title / axes / legend never miss.
const effXLabel = computed(() => {
  const spec = props.chart || {}
  return String(spec.x_label || '') || prettyLabel(spec.x)
})
const effYLabel = computed(() => {
  const spec = props.chart || {}
  if (spec.y_label) return String(spec.y_label)
  const ys = Array.isArray(spec.y) ? spec.y : []
  // A single series names the axis after its column; several series leave the
  // axis to the unit alone (the legend already names each series).
  return ys.length === 1 ? prettyLabel(ys[0]) : ''
})
const effTitle = computed(() => {
  if (props.title) return String(props.title)
  const spec = props.chart || {}
  const ys = (Array.isArray(spec.y) ? spec.y : []).map(prettyLabel).filter(Boolean)
  const yPart = ys.join(', ')
  const xPart = effXLabel.value
  if (!yPart || !xPart) return ''
  return t('art.chart.auto_title', [yPart, xPart])
})

// Human tick formatting on the VALUE axis: compact notation for large magnitudes
// (1.2M, 340k - axis room is scarce), exact locale grouping below.
function fmtTick(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return value
  if (Math.abs(n) >= 10000) {
    try {
      return new Intl.NumberFormat(locale.value, {
        notation: 'compact',
        maximumFractionDigits: 1,
      }).format(n)
    } catch (e) {
      /* older runtime without compact notation: fall through to exact */
    }
  }
  return formatStatNumber(n, locale.value)
}

// Tooltip value: exact locale-formatted figure + the agent-provided unit.
function fmtTooltipValue(v) {
  const unit = String((props.chart && props.chart.unit) || '')
  return formatStatNumber(v, locale.value) + (unit ? ' ' + unit : '')
}

// Cartesian axes, always titled: the agent's labels when provided, otherwise
// derived from the column names - swapped for horizontal bars.
function buildScales(spec, horizontal, stacked, text3, grid) {
  const xLabel = effXLabel.value
  const unit = String(spec.unit || '')
  let yLabel = effYLabel.value
  if (unit) yLabel = yLabel ? yLabel + ' (' + unit + ')' : unit
  const catAxis = {
    stacked,
    ticks: { color: text3 },
    grid: { color: grid },
    title: { display: !!xLabel, text: xLabel, color: text3 },
  }
  const valAxis = {
    stacked,
    ticks: { color: text3, callback: fmtTick },
    grid: { color: grid },
    beginAtZero: true,
    title: { display: !!yLabel, text: yLabel, color: text3 },
  }
  return horizontal ? { x: valAxis, y: catAxis } : { x: catAxis, y: valAxis }
}

function buildConfig() {
  const spec = props.chart || {}
  const style = String(spec.style || '').toLowerCase()
  const pal = palette()
  const text2 = cssVar('--text-2', '#333')
  const text3 = cssVar('--text-3', '#888')
  const grid = cssVar('--border', 'rgba(0,0,0,0.1)')
  const surface = cssVar('--surface', '#ffffff')

  const isPie = spec.type === 'pie'
  const chartType = isPie
    ? (style === 'donut' || style === 'doughnut' ? 'doughnut' : 'pie')
    : (spec.type === 'bar' ? 'bar' : 'line')
  const horizontal = chartType === 'bar' && style === 'horizontal'
  // 'grouped' (default for several series) vs 'stacked' bars / area.
  const stacked = style === 'stacked'

  const datasets = props.data.datasets.map((ds, i) => {
    if (isPie) {
      return {
        label: prettyLabel(ds.label),
        data: ds.data,
        backgroundColor: ds.data.map((_, j) => pal[j % pal.length]),
        borderColor: surface,
        borderWidth: 2,
        hoverOffset: 6,
      }
    }
    const c = pal[i % pal.length]
    const base = {
      label: prettyLabel(ds.label),
      data: ds.data,
      borderColor: c,
      backgroundColor: chartType === 'bar' ? c : withAlpha(c, 0.18),
      borderWidth: 2,
      borderRadius: chartType === 'bar' ? 3 : 0,
      pointRadius: 3,
      pointHoverRadius: 5,
      pointBackgroundColor: c,
      spanGaps: true,
    }
    if (chartType === 'line') {
      base.tension = style === 'smooth' ? 0.4 : 0
      base.stepped = style === 'stepped'
      base.fill = style === 'area'
    }
    return base
  })

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 500 },
    interaction: { mode: isPie ? 'nearest' : 'index', intersect: false },
    indexAxis: horizontal ? 'y' : 'x',
    plugins: {
      legend: {
        display: isPie || datasets.length > 1,
        position: isPie ? 'right' : 'top',
        labels: { color: text2, usePointStyle: true, boxWidth: 8 },
      },
      title: { display: !!effTitle.value, text: effTitle.value, color: text2 },
      tooltip: isPie
        ? {
            callbacks: {
              label(ctx) {
                const arr = ctx.dataset.data || []
                const total = arr.reduce((s, v) => s + (Number(v) || 0), 0) || 1
                const v = Number(ctx.parsed) || 0
                return ` ${ctx.label}: ${fmtTooltipValue(v)} (${((100 * v) / total).toFixed(1)}%)`
              },
            },
          }
        : {
            callbacks: {
              // Exact locale-formatted figure + unit (the axis shows compact ticks;
              // the tooltip is where the precise number lives).
              label(ctx) {
                const v = horizontal ? ctx.parsed.x : ctx.parsed.y
                const name = ctx.dataset.label ? ctx.dataset.label + ': ' : ''
                return ` ${name}${fmtTooltipValue(v)}`
              },
            },
          },
    },
    scales: isPie ? {} : buildScales(spec, horizontal, stacked, text3, grid),
  }

  return { type: chartType, data: { labels: props.data.labels, datasets }, options }
}

function render() {
  if (instance) {
    instance.destroy()
    instance = null
  }
  if (!isOk() || !canvasEl.value) return
  instance = new Chart(canvasEl.value, buildConfig())
}

onMounted(() => {
  render()
  // Canvas colors are baked at draw time, so re-render when the theme flips.
  try {
    themeObserver = new MutationObserver(() => render())
    themeObserver.observe(document.body, { attributes: true, attributeFilter: ['data-theme'] })
  } catch (e) {
    /* MutationObserver unavailable: charts simply keep their initial theme. */
  }
})

watch(() => [props.data, props.chart], () => nextTick(render), { deep: true })
// Tick/tooltip formats and the derived title are locale-baked at draw time.
watch(locale, () => nextTick(render))

onBeforeUnmount(() => {
  if (instance) {
    instance.destroy()
    instance = null
  }
  if (themeObserver) {
    themeObserver.disconnect()
    themeObserver = null
  }
})
</script>

<template>
  <div class="art-chart">
    <!-- Honest empty state: the server could not build a chart (no data, unknown
         column, no numeric series). -->
    <div v-if="!isOk()" class="art-empty">
      <span class="art-empty-icon">&#9649;</span>
      <span>{{ t('art.chart.empty') }}</span>
    </div>
    <template v-else>
      <div class="art-canvas-wrap">
        <canvas ref="canvasEl" role="img" :aria-label="effTitle || t('art.chart.title_fallback')" />
      </div>
      <p v-if="description" class="art-desc">{{ description }}</p>
      <div v-if="data.truncated" class="art-trunc">{{ t('art.chart.truncated') }}</div>
    </template>
  </div>
</template>

<style scoped>
.art-chart {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  min-height: 0;
}
/* Fixed-height canvas wrapper: Chart.js fills it (maintainAspectRatio: false). */
.art-canvas-wrap {
  position: relative;
  width: 100%;
  height: 340px;
}
.art-trunc {
  font-size: var(--fs-xs);
  color: var(--orange-text);
}
/* Agent-provided caption: what the chart shows (scope, period, scenario). */
.art-desc {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.art-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  padding: var(--s-8) var(--s-4);
  font-size: var(--fs-sm);
  color: var(--text-3);
  border: 1px dashed var(--border);
  border-radius: var(--r-sm);
  text-align: center;
}
.art-empty-icon {
  font-size: 28px;
  opacity: 0.4;
}
</style>
