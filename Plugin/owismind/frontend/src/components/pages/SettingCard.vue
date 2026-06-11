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
.set-card {
  padding: var(--s-5);
  border: 1px solid var(--border);
  border-radius: var(--r);
  background: var(--bg);
}
.set-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  margin-bottom: var(--s-4);
}
.set-card-eyebrow {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-3);
}
.set-card-action { display: inline-flex; align-items: center; }
</style>
