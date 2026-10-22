<script setup>
// Studio waiting state - fills the empty Studio body while the run works and no board
// widget is published yet: an abstract dashboard assembling itself from data. Square
// ink tiles land on a 4-column grid (cascade, once), then live: counters tick, bars
// rise at different rhythms, text lines write themselves, a line draws itself across
// the wide tile. ONE orange element at a time: a small square cursor hopping from
// tile to tile (each tile owns a mark, their opacity windows never overlap). CSS
// transforms / opacity only (the drawn line uses stroke-dashoffset on one path); under
// prefers-reduced-motion the composition is static. The line underneath reads the
// live plan step when known, else rotates a few plain sentences.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  // Label of the plan step running now (null: none known yet).
  step: { type: String, default: null },
})
const { t } = useI18n()

const PHRASES = 5
const ROTATE_MS = 3600
const phrase = ref(0)
let timer = null
onMounted(() => {
  timer = setInterval(() => { phrase.value = (phrase.value + 1) % PHRASES }, ROTATE_MS)
})
onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  timer = null
})
const line = computed(() => props.step || t('ws.wait.' + phrase.value))

// Counters: units and tens roll like an odometer (tens = 10x slower), per tile pace.
const KPIS = [2.4, 3, 3.6, 2.8]
// Bars: target height (scale) and rhythm (s) of each bar.
const BARS = [[0.55, 1.9], [0.8, 2.6], [0.4, 2.2], [0.95, 3], [0.65, 1.7], [0.75, 2.4], [0.5, 2.8], [0.9, 2], [0.6, 2.5]]
const TEXT = [0.55, 0.92, 0.86, 0.95, 0.7]
const POINTS = '0,78 40,70 80,74 120,52 160,58 200,40 240,46 280,28 320,34 360,18 400,22'
// Tiles in hop order (the orange cursor visits them one after the other).
const TILE_COUNT = KPIS.length + 3
</script>

<template>
  <div class="sw">
    <div class="sw-board" role="img" :aria-label="t('ws.wait.aria')" :style="{ '--tiles': TILE_COUNT }">
      <div v-for="(pace, i) in KPIS" :key="'k' + i" class="sw-tile sw-kpi" :style="{ '--i': i }">
        <span class="sw-mark" />
        <span class="sw-label" />
        <span class="sw-count mono">
          <span class="sw-digit">{{ i + 1 }}</span>
          <span class="sw-digit"><span class="sw-strip" :style="{ animationDuration: pace * 10 + 's' }"><span v-for="d in 10" :key="d">{{ d - 1 }}</span></span></span>
          <span class="sw-digit"><span class="sw-strip" :style="{ animationDuration: pace + 's' }"><span v-for="d in 10" :key="d">{{ d - 1 }}</span></span></span>
        </span>
        <span class="sw-rule" />
      </div>
      <div class="sw-tile sw-bars" :style="{ '--i': 4 }">
        <span class="sw-mark" />
        <span class="sw-label" />
        <div class="sw-bar-row">
          <span v-for="(b, i) in BARS" :key="i" class="sw-bar" :style="{ '--h': b[0], animationDuration: b[1] + 's', animationDelay: i * -0.37 + 's' }" />
        </div>
      </div>
      <div class="sw-tile sw-text" :style="{ '--i': 5 }">
        <span class="sw-mark" />
        <span class="sw-label" />
        <span v-for="(w, i) in TEXT" :key="i" class="sw-tline" :class="{ head: i === 0 }" :style="{ width: w * 100 + '%', animationDelay: i * 0.35 + 's' }" />
      </div>
      <div class="sw-tile sw-line" :style="{ '--i': 6 }">
        <span class="sw-mark" />
        <span class="sw-label" />
        <svg class="sw-plot" viewBox="0 0 400 100" preserveAspectRatio="none">
          <line v-for="y in [25, 50, 75]" :key="y" x1="0" x2="400" :y1="y" :y2="y" class="sw-grid" />
          <polyline :points="POINTS" pathLength="1" class="sw-path" />
        </svg>
      </div>
    </div>
    <Transition name="sw-fade" mode="out-in">
      <p :key="line" class="sw-status" :role="step ? 'status' : null">{{ line }}</p>
    </Transition>
  </div>
</template>

<style scoped>
/* Fills the Studio body (a flex column while waiting): a size container, so the
   composition can be bounded by the body height. */
.sw {
  flex: 1 1 0;
  min-height: 0;
  container-type: size;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s-5);
}
/* The composition grows with the Studio, bounded by its height (16:10). */
.sw-board {
  width: min(100%, 960px);
  width: min(100%, 960px, calc((100cqh - 72px) * 1.6));
  aspect-ratio: 16 / 10;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  grid-template-rows: 1fr 1.7fr 1.7fr;
  gap: 12px;
}
.sw-tile {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  min-height: 0;
  padding: 12px;
  border: 1px solid var(--border);
  background: var(--bg);
  overflow: hidden;
  animation: sw-in var(--dur-slow) var(--ease-out) both;
  animation-delay: calc(var(--i) * 40ms);
}
.sw-bars,
.sw-text { grid-column: span 2; }
.sw-line { grid-column: span 4; }
@keyframes sw-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}
/* The ONE orange element: a square cursor hopping tile to tile (window = 1 / tiles). */
.sw-mark {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 8px;
  height: 8px;
  background: var(--orange);
  opacity: 0;
  animation: sw-hop calc(var(--tiles) * 0.9s) linear infinite;
  animation-delay: calc(var(--i) * 0.9s);
}
@keyframes sw-hop {
  0% { opacity: 0; transform: scale(0.4); }
  3% { opacity: 1; transform: none; }
  11% { opacity: 1; transform: none; }
  14%, 100% { opacity: 0; transform: none; }
}
.sw-label { width: 42%; height: 6px; flex: 0 0 auto; background: var(--surface-2); }
.sw-count {
  display: flex;
  font-size: clamp(16px, 4cqh, 28px);
  font-weight: var(--fw-bold);
  line-height: 1;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}
.sw-digit { display: block; height: 1em; overflow: hidden; }
.sw-strip {
  display: flex;
  flex-direction: column;
  animation: sw-roll 3s steps(10, end) infinite;
}
.sw-strip > span { height: 1em; }
@keyframes sw-roll { to { transform: translateY(-100%); } }
.sw-rule { margin-top: auto; height: 1px; background: var(--border-strong); }
.sw-bar-row {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: flex-end;
  gap: 8%;
  padding: 0 2px;
  border-bottom: 1px solid var(--border-strong);
}
.sw-bar {
  flex: 1;
  height: 100%;
  background: var(--text);
  transform-origin: bottom;
  transform: scaleY(var(--h));
  animation: sw-rise 2s ease-in-out infinite alternate;
}
.sw-bar:nth-child(3n + 2) { background: var(--text-3); }
@keyframes sw-rise {
  from { transform: scaleY(calc(var(--h) * 0.35)); }
  to { transform: scaleY(var(--h)); }
}
.sw-tline {
  height: 6px;
  flex: 0 0 auto;
  background: var(--text-3);
  transform-origin: left;
  animation: sw-type 5s var(--ease-out) infinite both;
}
.sw-tline.head { height: 9px; background: var(--text); }
@keyframes sw-type {
  0% { transform: scaleX(0); opacity: 1; }
  22% { transform: scaleX(1); }
  82% { transform: scaleX(1); opacity: 1; }
  92%, 100% { transform: scaleX(1); opacity: 0; }
}
.sw-plot { flex: 1; min-height: 0; width: 100%; overflow: visible; }
.sw-grid { stroke: var(--border); stroke-width: 1; vector-effect: non-scaling-stroke; }
.sw-path {
  fill: none;
  stroke: var(--text);
  stroke-width: 2;
  stroke-linejoin: round;
  vector-effect: non-scaling-stroke;
  stroke-dasharray: 1;
  stroke-dashoffset: 1;
  animation: sw-draw 6s var(--ease-out) infinite;
}
@keyframes sw-draw {
  0% { stroke-dashoffset: 1; opacity: 1; }
  55% { stroke-dashoffset: 0; }
  88% { stroke-dashoffset: 0; opacity: 1; }
  100% { stroke-dashoffset: 0; opacity: 0; }
}
.sw-status {
  margin: 0;
  max-width: 60ch;
  text-align: center;
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.sw-fade-enter-active { transition: opacity var(--dur) var(--ease-out); }
.sw-fade-leave-active { transition: opacity var(--dur-fast) var(--ease-in); }
.sw-fade-enter-from,
.sw-fade-leave-to { opacity: 0; }
/* Narrow Studio: tighter tiles. */
@container (max-width: 520px) {
  .sw-board { gap: 8px; }
  .sw-tile { padding: 8px; gap: 6px; }
  .sw-mark { top: 8px; right: 8px; }
}
/* Static composition: everything in place, the first tile marked. */
@media (prefers-reduced-motion: reduce) {
  .sw-tile,
  .sw-strip,
  .sw-bar,
  .sw-tline,
  .sw-path,
  .sw-mark { animation: none; }
  .sw-path { stroke-dashoffset: 0; }
  .sw-kpi:first-child .sw-mark { opacity: 1; }
  .sw-fade-enter-active,
  .sw-fade-leave-active { transition: none; }
}
</style>
