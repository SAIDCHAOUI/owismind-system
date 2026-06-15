<script setup>
// ArtifactChart.vue — hand-rolled SVG chart renderer for Evidence Studio artifact charts.
// No charting library dependency. Reads geometry from chartGeometry.js (pure module).
// Supports line, bar, and pie charts. Theme-aware via CSS custom properties.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { buildChartGeometry } from './chartGeometry.js'

const { t } = useI18n()

const props = defineProps({
  // Artifact spec from meta.artifacts[n].chart: { type, x, y }
  chart: { type: Object, required: true },
  // meta.result: { captured, columns, rows, row_count, truncated }
  result: { type: Object, default: null },
  // Display title for aria-label and legend header
  title: { type: String, default: '' },
})

// A small palette using existing orange tokens + safe grays / blues from CSS custom properties.
// Defined as CSS var references so they follow the active theme without extra logic.
// Index 0 = primary (orange accent), then neutral complements.
const SERIES_COLORS = [
  'var(--orange)',
  'var(--orange-text)',
  '#5b8dee',
  '#40c9a2',
  '#e87d5e',
  '#a78bfa',
  '#f59e0b',
  '#10b981',
]

function seriesColor(i) {
  return SERIES_COLORS[i % SERIES_COLORS.length]
}

const geometry = computed(() => {
  const r = props.result
  if (!r || !r.captured || !Array.isArray(r.columns) || !Array.isArray(r.rows)) {
    return { ok: false, reason: 'no_data' }
  }
  const { type, x, y } = props.chart
  if (!type || !Array.isArray(y) || y.length === 0) {
    return { ok: false, reason: 'invalid_spec' }
  }
  return buildChartGeometry({ type, columns: r.columns, rows: r.rows, x, y })
})

const ariaLabel = computed(() => {
  const title = props.title || t('art.chart.title_fallback')
  return title + (geometry.value.ok ? '' : ' — ' + t('art.chart.empty'))
})

// Whether multiple series need a legend (single series pie already uses wedge labels)
const showLegend = computed(() => {
  const g = geometry.value
  if (!g.ok) return false
  if (g.type === 'pie') return false // pie labels are on the wedges
  return g.series && g.series.length > 1
})
</script>

<template>
  <div class="art-chart" role="img" :aria-label="ariaLabel">
    <!-- Empty state: geometry could not be built (no numeric data, column not found, etc.) -->
    <div v-if="!geometry.ok" class="art-empty">
      <span class="art-empty-icon">&#9636;</span>
      <span>{{ t('art.chart.empty') }}</span>
      <span v-if="geometry.reason" class="art-empty-reason">{{ geometry.reason }}</span>
    </div>

    <template v-else>
      <!-- Multi-series legend (line / grouped-bar) -->
      <div v-if="showLegend" class="art-legend">
        <span v-for="(key, i) in geometry.series" :key="key" class="art-legend-item">
          <span class="art-legend-dot" :style="{ background: seriesColor(i) }" />
          {{ key }}
        </span>
      </div>

      <!-- LINE CHART -->
      <svg
        v-if="geometry.type === 'line'"
        class="art-svg"
        :viewBox="geometry.viewBox"
        aria-hidden="true"
        preserveAspectRatio="xMidYMid meet"
      >
        <!-- Y-axis gridlines and labels -->
        <g class="art-grid">
          <line
            v-for="tick in geometry.yTicks"
            :key="tick.v"
            :x1="geometry.pad.left"
            :y1="tick.y"
            :x2="geometry.pad.left + geometry.plotW"
            :y2="tick.y"
            class="art-gridline"
          />
          <text
            v-for="tick in geometry.yTicks"
            :key="'yl-' + tick.v"
            :x="geometry.pad.left - 6"
            :y="tick.y"
            class="art-axis-label"
            text-anchor="end"
            dominant-baseline="middle"
          >{{ tick.label }}</text>
        </g>

        <!-- Zero line (only when chart crosses zero) -->
        <line
          v-if="geometry.zeroY != null"
          :x1="geometry.pad.left"
          :y1="geometry.zeroY"
          :x2="geometry.pad.left + geometry.plotW"
          :y2="geometry.zeroY"
          class="art-zero-line"
        />

        <!-- X-axis labels -->
        <g class="art-xaxis">
          <text
            v-for="tick in geometry.xTicks"
            :key="'xl-' + tick.i"
            :x="tick.x"
            :y="geometry.pad.top + geometry.plotH + 16"
            class="art-axis-label"
            text-anchor="middle"
          >{{ tick.label }}</text>
        </g>

        <!-- Polylines per series -->
        <g v-for="(pl, i) in geometry.polylines" :key="pl.key" class="art-series">
          <polyline
            :points="pl.points"
            :stroke="seriesColor(i)"
            fill="none"
            stroke-width="2"
            stroke-linejoin="round"
            stroke-linecap="round"
          />
          <!-- Data dots -->
          <circle
            v-for="(dot, di) in pl.dots"
            :key="di"
            :cx="dot.cx"
            :cy="dot.cy"
            r="3"
            :fill="seriesColor(i)"
            class="art-dot"
          >
            <title>{{ pl.key }}: {{ dot.value }}</title>
          </circle>
        </g>

        <!-- Axis borders -->
        <line
          :x1="geometry.pad.left" :y1="geometry.pad.top"
          :x2="geometry.pad.left" :y2="geometry.pad.top + geometry.plotH"
          class="art-axis-border"
        />
        <line
          :x1="geometry.pad.left" :y1="geometry.pad.top + geometry.plotH"
          :x2="geometry.pad.left + geometry.plotW" :y2="geometry.pad.top + geometry.plotH"
          class="art-axis-border"
        />
      </svg>

      <!-- BAR CHART -->
      <svg
        v-else-if="geometry.type === 'bar'"
        class="art-svg"
        :viewBox="geometry.viewBox"
        aria-hidden="true"
        preserveAspectRatio="xMidYMid meet"
      >
        <!-- Y-axis gridlines -->
        <g class="art-grid">
          <line
            v-for="tick in geometry.yTicks"
            :key="tick.v"
            :x1="geometry.pad.left"
            :y1="tick.y"
            :x2="geometry.pad.left + geometry.plotW"
            :y2="tick.y"
            class="art-gridline"
          />
          <text
            v-for="tick in geometry.yTicks"
            :key="'yl-' + tick.v"
            :x="geometry.pad.left - 6"
            :y="tick.y"
            class="art-axis-label"
            text-anchor="end"
            dominant-baseline="middle"
          >{{ tick.label }}</text>
        </g>

        <!-- Zero line -->
        <line
          v-if="geometry.zeroY != null"
          :x1="geometry.pad.left"
          :y1="geometry.zeroY"
          :x2="geometry.pad.left + geometry.plotW"
          :y2="geometry.zeroY"
          class="art-zero-line"
        />

        <!-- X-axis labels -->
        <g class="art-xaxis">
          <text
            v-for="tick in geometry.xTicks"
            :key="'xl-' + tick.i"
            :x="tick.x"
            :y="geometry.pad.top + geometry.plotH + 16"
            class="art-axis-label"
            text-anchor="middle"
          >{{ tick.label }}</text>
        </g>

        <!-- Bars grouped per series -->
        <g v-for="(bars, i) in geometry.bars" :key="bars.key" class="art-bar-series">
          <rect
            v-for="(rect, ri) in bars.rects"
            :key="ri"
            :x="rect.x"
            :y="rect.y"
            :width="rect.width"
            :height="rect.height"
            :fill="seriesColor(i)"
            rx="1"
            class="art-bar"
          >
            <title>{{ bars.key }}: {{ rect.value }}</title>
          </rect>
        </g>

        <!-- Axis borders -->
        <line
          :x1="geometry.pad.left" :y1="geometry.pad.top"
          :x2="geometry.pad.left" :y2="geometry.pad.top + geometry.plotH"
          class="art-axis-border"
        />
        <line
          :x1="geometry.pad.left" :y1="geometry.pad.top + geometry.plotH"
          :x2="geometry.pad.left + geometry.plotW" :y2="geometry.pad.top + geometry.plotH"
          class="art-axis-border"
        />
      </svg>

      <!-- PIE CHART -->
      <svg
        v-else-if="geometry.type === 'pie'"
        class="art-svg"
        :viewBox="geometry.viewBox"
        aria-hidden="true"
        preserveAspectRatio="xMidYMid meet"
      >
        <g class="art-pie">
          <path
            v-for="(wedge, i) in geometry.wedges"
            :key="i"
            :d="wedge.path"
            :fill="seriesColor(i)"
            stroke="var(--bg)"
            stroke-width="1.5"
            class="art-wedge"
          >
            <title>{{ wedge.label }}: {{ wedge.value }} ({{ wedge.pct.toFixed(1) }}%)</title>
          </path>
        </g>
        <!-- Pie legend (since labels inside the SVG can overlap for small slices) -->
        <g class="art-pie-legend">
          <g
            v-for="(wedge, i) in geometry.wedges"
            :key="'leg-' + i"
            :transform="`translate(${geometry.pad.left - 8}, ${geometry.pad.top + i * 22})`"
          >
            <rect width="12" height="12" :fill="seriesColor(i)" rx="2" />
            <text x="16" y="10" class="art-axis-label" text-anchor="start">
              {{ wedge.label }} ({{ wedge.pct.toFixed(1) }}%)
            </text>
          </g>
        </g>
      </svg>

      <!-- Truncation notice -->
      <div v-if="geometry.truncated" class="art-trunc">
        {{ t('art.chart.truncated') }}
      </div>
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

/* Legend row for multi-series line/bar */
.art-legend {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-2) var(--s-4);
  font-size: var(--fs-xs);
  color: var(--text-2);
}
.art-legend-item {
  display: flex;
  align-items: center;
  gap: var(--s-1);
}
.art-legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex: none;
}

/* The SVG fills the container width, height auto from aspect ratio. */
.art-svg {
  width: 100%;
  height: auto;
  display: block;
  border-radius: var(--r-sm);
  background: var(--surface);
  border: 1px solid var(--border);
}

/* SVG text elements */
.art-axis-label {
  font-size: 10px;
  fill: var(--text-3);
  font-family: var(--font-sans);
}
.art-gridline {
  stroke: var(--border);
  stroke-width: 1;
}
.art-zero-line {
  stroke: var(--text-3);
  stroke-width: 1;
  stroke-dasharray: none;
}
.art-axis-border {
  stroke: var(--border);
  stroke-width: 1.5;
}
.art-dot {
  /* Dots render by fill=seriesColor(i) inline; no override needed. */
}
.art-bar {
  opacity: 0.88;
  transition: opacity var(--dur) var(--ease);
}
.art-bar:hover { opacity: 1; }
.art-wedge {
  opacity: 0.9;
  transition: opacity var(--dur) var(--ease);
}
.art-wedge:hover { opacity: 1; }

/* Truncation note */
.art-trunc {
  font-size: var(--fs-xs);
  color: var(--orange-text);
}

/* Empty state */
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
.art-empty-reason {
  font-size: var(--fs-xs);
  font-family: var(--font-mono);
  opacity: 0.6;
}

/* Dark mode: SVG background matches the panel surface */
:global(body[data-theme="dark"] .art-svg) {
  background: var(--surface);
  border-color: var(--border);
}
</style>
