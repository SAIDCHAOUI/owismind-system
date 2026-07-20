<script setup>
// DataLoader - the playful "data is coming" overlay shown while a table re-queries
// (search / filter / sort refresh). A tiny flat bar chart whose SQUARE bars dance in
// a staggered wave over a sharp ink baseline - four ink bars, ONE orange (the rare
// accent), on a square 1px-bordered card. Pure charte Orange: flat fills, no
// gradient/blur/glow, square geometry, semantic tokens only.
//
// The overlay fades in with a short DELAY so a fast query never flashes it; it is
// pointer-events: none (purely visual - the host keeps its own busy dimming).
// Reduced motion: the bars freeze into a static little chart.
defineProps({
  // Localized status line under the bars (micro-label, uppercased by CSS).
  label: { type: String, default: '' },
})
</script>

<template>
  <div class="dload" role="status" aria-live="polite">
    <div class="dload-card">
      <div class="dload-bars" aria-hidden="true">
        <span class="dload-bar b1" />
        <span class="dload-bar b2" />
        <span class="dload-bar b3" />
        <span class="dload-bar b4" />
        <span class="dload-bar b5" />
      </div>
      <span v-if="label" class="dload-label">{{ label }}</span>
    </div>
  </div>
</template>

<style scoped>
/* Overlay: centered on the host (which must be position: relative). Appears only
   after 150ms so quick refreshes stay flicker-free. */
.dload {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: grid;
  place-items: center;
  pointer-events: none;
  animation: dload-in 180ms var(--ease) 150ms both;
}
@keyframes dload-in {
  from { opacity: 0; transform: translateY(2px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Square flat card, 1px visible border, minimal shadow (charte level-1). */
.dload-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-3);
  padding: var(--s-4) var(--s-5);
  background: var(--bg);
  border: 1px solid var(--border-strong);
  border-radius: 0;
  box-shadow: var(--shadow);
}

/* The mini chart: bars grow from a sharp ink baseline (transform-origin bottom). */
.dload-bars {
  display: flex;
  align-items: flex-end;
  gap: 5px;
  height: 30px;
  border-bottom: 2px solid var(--text);
  padding: 0 2px;
}
.dload-bar {
  width: 9px;
  height: 100%;
  background: var(--text);
  border-radius: 0;
  transform: scaleY(0.25);
  transform-origin: bottom;
  animation: dload-bounce 1.05s cubic-bezier(0.45, 0, 0.35, 1) infinite;
}
/* ONE orange bar - the rare accent of the charte, never more. */
.dload-bar.b3 { background: var(--orange); }
.dload-bar.b1 { animation-delay: 0s; }
.dload-bar.b2 { animation-delay: 0.12s; }
.dload-bar.b3 { animation-delay: 0.24s; }
.dload-bar.b4 { animation-delay: 0.36s; }
.dload-bar.b5 { animation-delay: 0.48s; }
@keyframes dload-bounce {
  0%, 100% { transform: scaleY(0.25); }
  50% { transform: scaleY(1); }
}

/* Micro-label (charte): uppercase, 11px, heavy, wide tracking, mid ink. */
.dload-label {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-2);
  white-space: nowrap;
}

/* Reduced motion: no wave, no fade delay - a static little chart instead. */
@media (prefers-reduced-motion: reduce) {
  .dload { animation: none; }
  .dload-bar { animation: none; }
  .dload-bar.b1 { transform: scaleY(0.4); }
  .dload-bar.b2 { transform: scaleY(0.75); }
  .dload-bar.b3 { transform: scaleY(0.55); }
  .dload-bar.b4 { transform: scaleY(0.9); }
  .dload-bar.b5 { transform: scaleY(0.3); }
}
</style>
