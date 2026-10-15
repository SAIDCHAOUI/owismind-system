<script setup>
// A settings card: a bordered surface with an optional uppercase eyebrow row
// (label on the left, optional action on the right) and a content slot.
// Mutualizes the settings-card chrome (surface + eyebrow row) so Settings,
// Feedback and Project reuse one card instead of re-implementing it.
defineProps({
  eyebrow: { type: String, default: '' },
})
</script>

<template>
  <section class="set-card">
    <header v-if="eyebrow || $slots.action" class="set-card-head">
      <span v-if="eyebrow" class="set-card-eyebrow">{{ eyebrow }}</span>
      <div v-if="$slots.action" class="set-card-action"><slot name="action" /></div>
    </header>
    <slot />
  </section>
</template>

<style scoped>
/* Premium card: soft radius, hairline border, a resting layered shadow. The page
   reads as a stack of light panels instead of boxed-in rectangles (premium
   direction, user decision 2026-08-13). */
.set-card {
  padding: var(--s-5);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  background: var(--bg);
  box-shadow: var(--elev-1);
}
/* Dark canvas: a card painted the page color disappears - step it one surface
   level above the background (same recipe as the prompt card). */
:global(body[data-theme="dark"] .set-card) {
  background: var(--surface-2);
  border-color: var(--border-strong);
}
.set-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  margin-bottom: var(--s-4);
}
/* Uppercase micro-label: shared 11px / 800 / 0.08em recipe. */
.set-card-eyebrow {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: var(--tracking-eyebrow);
  text-transform: uppercase;
  color: var(--text-2);
}
.set-card-action { display: inline-flex; align-items: center; }
</style>
