<script setup>
// Tabs primitive — ported from `.ev-tab` (components.css): underline-on-active
// (orange), optional monospace count. v-model carries the active tab key.
//
// Extensibility: `items` is a plain array of { key, label, count? } so callers
// (Evidence Studio tabs, settings sections, admin tabs) drive it from a registry.
defineProps({
  // [{ key: string, label: string, count?: number|string }]
  items: { type: Array, required: true },
  modelValue: { type: [String, Number], default: '' },
})
defineEmits(['update:modelValue'])
</script>

<template>
  <div class="ui-tabs" role="tablist">
    <button
      v-for="t in items"
      :key="t.key"
      type="button"
      role="tab"
      :aria-selected="modelValue === t.key"
      :class="['ui-tab', { 'is-active': modelValue === t.key }]"
      @click="$emit('update:modelValue', t.key)"
    >
      {{ t.label }}
      <span v-if="t.count != null" class="ui-tab__ct">{{ t.count }}</span>
    </button>
  </div>
</template>

<style scoped>
.ui-tabs {
  display: flex;
  align-items: center;
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
}
.ui-tab {
  padding: var(--s-3) var(--s-4) var(--s-3) 0;
  margin-right: var(--s-5);
  font-size: var(--fs-sm);
  color: var(--text-2);
  position: relative;
  font-weight: 500;
  transition: color var(--dur) var(--ease);
  white-space: nowrap;
}
.ui-tab:hover { color: var(--text); }
.ui-tab.is-active { color: var(--text); }
.ui-tab.is-active::after {
  content: "";
  position: absolute;
  left: 0;
  right: var(--s-4);
  bottom: -1px;
  height: 1.5px;
  background: var(--orange);
}
.ui-tab__ct {
  margin-left: 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
}
</style>
