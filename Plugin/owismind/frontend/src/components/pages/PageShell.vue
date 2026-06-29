<script setup>
// Shared secondary-page shell: ONE internal scroll region + a centered, padded
// content column, with an OPTIONAL standard header (eyebrow / title / desc).
// Factored out of PagePlaceholder so every Phase-3 page shares the exact same
// outer layout (ported from the maquette's `.page` / `.page-inner`).
//
// Header strings are already-translated (pass via props). Pages needing a custom
// header (e.g. Settings prefs row, the agent hero) provide the #header slot
// instead; pages with no header at all just omit the props.
defineProps({
  eyebrow: { type: String, default: '' },
  title: { type: String, default: '' },
  desc: { type: String, default: '' },
  // Wider column for dense, two-column pages (Settings, Agents grid).
  wide: { type: Boolean, default: false },
  // Full-width (no centered cap), for pages that mirror a full-canvas webapp such
  // as the Benchmark consultation. Opt-in: pages that omit it keep the centered
  // 880 / 1080px column, so this never affects existing views.
  fluid: { type: Boolean, default: false },
})
</script>

<template>
  <div class="page-scroll">
    <div :class="['page-wrap', { 'page-wrap--wide': wide, 'page-wrap--fluid': fluid }]">
      <slot name="header">
        <header v-if="eyebrow || title || desc" class="page-head">
          <p v-if="eyebrow" class="page-eyebrow">{{ eyebrow }}</p>
          <h1 v-if="title" class="page-title">{{ title }}</h1>
          <div v-if="title" class="page-title-bar" aria-hidden="true"></div>
          <p v-if="desc" class="page-desc">{{ desc }}</p>
        </header>
      </slot>
      <slot />
    </div>
  </div>
</template>

<style scoped>
.page-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}
.page-wrap {
  max-width: 1080px;
  margin: 0 auto;
  padding: var(--s-8) var(--s-7) var(--s-10);
}
/* Narrow column for pages that don't need the full width. */
.page-wrap:not(.page-wrap--wide) {
  max-width: 880px;
}
.page-wrap--wide {
  max-width: 1080px;
}
/* Full-canvas pages (Benchmark consultation): span the whole main column, no
   centered cap, LAB-results-like edge padding. Overrides both rules above. */
.page-wrap.page-wrap--fluid {
  max-width: none;
  margin: 0;
  padding: var(--s-8) var(--s-8) var(--s-10);
}
.page-head {
  margin-bottom: var(--s-7);
}
/* Orange eyebrow: uppercase, tight tracking, brand orange. */
.page-eyebrow {
  font-size: var(--fs-xs);
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--orange);
  margin: 0 0 10px;
}
/* Heavy editorial h1. */
.page-title {
  font-size: var(--fs-3xl);
  font-weight: var(--fw-heavy);
  letter-spacing: -0.01em;
  line-height: 1.05;
  color: var(--text);
  margin: 0;
}
/* 52x4px orange bar directly under the title - brand signature element. */
.page-title-bar {
  width: 52px;
  height: 4px;
  background: var(--orange);
  margin: 16px 0 0;
}
.page-desc {
  margin: 14px 0 0;
  font-size: var(--fs-md);
  line-height: 1.6;
  color: var(--text-2);
  max-width: 640px;
}
</style>
