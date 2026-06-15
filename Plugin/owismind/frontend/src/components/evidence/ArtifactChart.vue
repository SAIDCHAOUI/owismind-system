<script setup>
// ArtifactChart.vue — interactive chart for an Evidence Studio artifact, rendered
// with Chart.js. The DATA is built server-side in Python (chart_payload.py) and
// arrives ready as { labels, datasets } in `data`; this component only chooses the
// visual style/options and draws. Chart.js gives real interactivity: hover
// tooltips, clickable legend (toggle series), animated draw-in, responsive resize.
import { ref, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import Chart from 'chart.js/auto'

const { t } = useI18n()

const props = defineProps({
  // Artifact chart spec: { type: 'line'|'bar'|'pie', x, y[], style? }
  chart: { type: Object, required: true },
  // Server-built Chart.js payload: { ok, labels, datasets, truncated, reason }
  data: { type: Object, default: null },
  // Title for the chart + aria-label
  title: { type: String, default: '' },
})

const canvasEl = ref(null)
let instance = null
let themeObserver = null

// Canvas cannot use CSS var() — resolve the active theme's colors at draw time.
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

  const datasets = props.data.datasets.map((ds, i) => {
    if (isPie) {
      return {
        label: ds.label,
        data: ds.data,
        backgroundColor: ds.data.map((_, j) => pal[j % pal.length]),
        borderColor: surface,
        borderWidth: 2,
        hoverOffset: 6,
      }
    }
    const c = pal[i % pal.length]
    const base = {
      label: ds.label,
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
      title: { display: !!props.title, text: props.title, color: text2 },
      tooltip: isPie
        ? {
            callbacks: {
              label(ctx) {
                const arr = ctx.dataset.data || []
                const total = arr.reduce((s, v) => s + (Number(v) || 0), 0) || 1
                const v = Number(ctx.parsed) || 0
                return ` ${ctx.label}: ${v.toLocaleString()} (${((100 * v) / total).toFixed(1)}%)`
              },
            },
          }
        : {},
    },
    scales: isPie
      ? {}
      : {
          x: { ticks: { color: text3 }, grid: { color: grid } },
          y: { ticks: { color: text3 }, grid: { color: grid }, beginAtZero: true },
        },
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
        <canvas ref="canvasEl" role="img" :aria-label="title || t('art.chart.title_fallback')" />
      </div>
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
