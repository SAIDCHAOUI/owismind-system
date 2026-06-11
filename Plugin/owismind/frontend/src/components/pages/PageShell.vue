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
})
</script>

<template>
  <div class="page-scroll">
    <div :class="['page-wrap', { 'page-wrap--wide': wide }]">
      <slot name="header">
        <header v-if="eyebrow || title || desc" class="page-head">
          <p v-if="eyebrow" class="page-eyebrow">{{ eyebrow }}</p>
          <h1 v-if="title" class="page-title">{{ title }}</h1>
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
  max-width: 880px;
  margin: 0 auto;
  padding: var(--s-8) var(--s-7) var(--s-10);
}
.page-wrap--wide {
  max-width: 1080px;
}
.page-head {
  margin-bottom: var(--s-7);
}
.page-eyebrow {
  font-size: var(--fs-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--orange);
  margin: 0 0 var(--s-3);
}
.page-title {
  font-size: var(--fs-2xl);
  font-weight: 600;
  letter-spacing: -0.025em;
  color: var(--text);
  margin: 0;
}
.page-desc {
  margin: var(--s-4) 0 0;
  font-size: var(--fs-md);
  line-height: 1.6;
  color: var(--text-2);
  max-width: 640px;
}
</style>
