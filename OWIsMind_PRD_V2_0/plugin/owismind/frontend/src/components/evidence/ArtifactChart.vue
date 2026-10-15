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
  // Hosted inside a card that already shows the title + caption (V2 dashboard widget):
  // no figcaption, a shorter canvas.
  bare: { type: Boolean, default: false },
})

const canvasEl = ref(null)
let instance = null
let themeObserver = null

// Canvas cannot use CSS var() - resolve the active theme's colors at draw time.
// Read them from <body>: the semantic tokens live under body[data-theme] (F4),
// so <html> never sees the dark variants - reading documentElement would bake
// light-theme axis/grid colors into a dark-mode chart.
function cssVar(name, fallback) {
  try {
    const v = getComputedStyle(document.body).getPropertyValue(name).trim()
    return v || fallback
  } catch (e) {
    return fallback
  }
}

// Series palette: the theme's --series-1..8 tokens (V2 charter: the secondary palette
// lives in chart series only), with the former hues as fallbacks.
const SERIES_FALLBACK = ['#085ebd', '#50be87', '#a885d8', '#ffb400', '#4bb4e6', '#0a6e31', '#ff8ad4', '#492191']
function palette() {
  return SERIES_FALLBACK.map((hex, i) => cssVar('--series-' + (i + 1), hex))
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

// Single-series cartesian charts get NO Chart.js legend (it would be redundant
// noise for toggling one series) - but a chart must never ship without a named
// series (legends are non-negotiable). This HTML legend line names the series +
// its unit under the canvas; the swatch is the brand orange (first palette slot),
// painted in CSS so it follows theme flips for free.
const soloSeries = computed(() => {
  if (!isOk()) return null
  const spec = props.chart || {}
  if (spec.type === 'pie') return null
  const ds = props.data.datasets
  if (!Array.isArray(ds) || ds.length !== 1) return null
  const label = prettyLabel(ds[0] && ds[0].label) || effYLabel.value
  const unit = String(spec.unit || '')
  return label || unit ? { label, unit } : null
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
        // Square swatches (brand geometry) instead of point-style dots.
        labels: { color: text2, boxWidth: 10, boxHeight: 10 },
      },
      // The title lives in the HTML header above the canvas (selectable, theme-aware
      // without a redraw, and styled by the charte) - never drawn on the canvas.
      title: { display: false },
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
    <!-- Semantic figure: header (what the chart shows) BEFORE the drawing, so the
         reader gets title + scope first (guide: context before the number). -->
    <figure v-else class="art-fig" :class="{ bare }">
      <figcaption v-if="!bare" class="art-fig-head">
        <span class="art-fig-title">{{ effTitle || t('art.chart.title_fallback') }}</span>
        <span v-if="description" class="art-desc">{{ description }}</span>
      </figcaption>
      <div class="art-canvas-wrap">
        <canvas ref="canvasEl" role="img" :aria-label="effTitle || t('art.chart.title_fallback')" />
      </div>
      <!-- Series legend for single-series charts (Chart.js hides its own there). -->
      <div v-if="soloSeries" class="art-legend">
        <span class="art-legend-swatch" aria-hidden="true" />
        <span class="art-legend-label">{{ soloSeries.label }}</span>
        <span v-if="soloSeries.unit" class="art-legend-unit mono">({{ soloSeries.unit }})</span>
      </div>
      <div v-if="data.truncated" class="art-trunc">{{ t('art.chart.truncated') }}</div>
    </figure>
  </div>
</template>

<style scoped>
.art-chart {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  min-height: 0;
}
.art-fig {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  min-width: 0;
}
/* Header: an informative title (level-2 emphasis - the tab itself is level 1),
   then the agent's one-sentence caption. Reads BEFORE the drawing. */
.art-fig-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.art-fig-title {
  font-size: var(--fs-md);
  font-weight: var(--fw-bold);
  color: var(--text);
  line-height: 1.35;
}
/* Fixed-height canvas wrapper: Chart.js fills it (maintainAspectRatio: false). The
   drawing fades up once the payload is in: a chart that appears is read, one that
   blinks is skipped. Chart.js runs its own bar animation inside the canvas. */
.art-canvas-wrap {
  position: relative;
  width: 100%;
  height: 340px;
  animation: art-canvas-in var(--dur-slow) var(--ease-out) both;
}
@keyframes art-canvas-in {
  from { opacity: 0; transform: translateY(8px); }
}
@media (prefers-reduced-motion: reduce) { .art-canvas-wrap { animation: none; } }
/* Dashboard card: the card frame carries the title, the drawing gets a compact height. */
.art-fig.bare .art-canvas-wrap { height: 240px; }
/* Single-series legend: a self-contained pill (premium 2026-08-13) so the line reads as
   a legend and not as a stray caption - square brand-orange swatch (slot 0 of the
   palette) + series name + unit. Flat, theme-aware via tokens, sized to its content. */
.art-legend {
  display: inline-flex;
  align-self: flex-start;
  align-items: center;
  gap: 8px;
  padding: 4px 12px;
  border: 1px solid var(--border);
  border-radius: var(--r-pill);
  background: var(--surface);
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.art-legend-swatch {
  width: 10px;
  height: 10px;
  background: var(--series-1, var(--orange));
  flex-shrink: 0;
}
.art-legend-label { font-weight: var(--fw-medium); }
.art-legend-unit {
  font-size: var(--fs-xs);
  color: var(--text-3);
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
  border-radius: 0;
  text-align: center;
}
.art-empty-icon {
  font-size: 28px;
  opacity: 0.4;
}
</style>
