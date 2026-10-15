<script setup>
// Text widget (decision D7): a textual facet of the answer on the dashboard, rendered
// through the app's ONLY markdown path (markdown-it + DOMPurify, useMarkdown.js).
import { computed } from 'vue'
import { renderMarkdown } from '../../composables/useMarkdown.js'

const props = defineProps({ text: { type: String, default: '' } })
const html = computed(() => renderMarkdown(props.text))
</script>

<template>
  <div class="w-text" v-html="html" />
</template>

<style scoped>
.w-text {
  font-size: var(--fs-sm);
  line-height: var(--lh-text);
  color: var(--text);
  overflow-wrap: anywhere;
}
.w-text :deep(p) { margin: 0 0 var(--s-2); }
.w-text :deep(p:last-child) { margin-bottom: 0; }
.w-text :deep(ul), .w-text :deep(ol) { margin: 0 0 var(--s-2); padding-left: 20px; }
.w-text :deep(strong) { font-weight: var(--fw-bold); }
.w-text :deep(code) { font-family: var(--font-mono); font-size: 12px; }
</style>
