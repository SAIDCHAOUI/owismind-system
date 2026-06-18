<script setup>
// A settings card: a bordered surface with an optional uppercase eyebrow row
// (label on the left, optional action on the right) and a content slot.
// Mutualizes the maquette's `.set-card` + `.set-card-eyebrow-row` so Settings,
// Feedback and Project reuse one card instead of re-implementing the chrome.
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
/* Square card: sharp corners, strong border, flat white surface. */
.set-card {
  padding: var(--s-5);
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--bg);
}
.set-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  margin-bottom: var(--s-4);
}
/* Uppercase micro-label: heavier weight, tighter tracking than before. */
.set-card-eyebrow {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-2);
}
.set-card-action { display: inline-flex; align-items: center; }
</style>
