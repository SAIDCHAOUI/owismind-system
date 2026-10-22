<script setup>
// Text widget (decision D7): a written section of the analysis on the dashboard (what
// was analysed, what it shows, the takeaway), rendered through the app's ONLY markdown
// path (markdown-it with raw HTML disabled + DOMPurify, useMarkdown.js). The
// typography follows the chat answer (MessageAgent .body) so the Studio reads like the
// same answer, at a comfortable reading size. Figures are bound together first
// (numberText.js): a long section flows in columns, and "8 593 242,88 EUR" must never
// be cut by a line or column break.
import { computed } from 'vue'
import { renderMarkdown } from '../../composables/useMarkdown.js'
import { keepNumbersTogether } from '../../composables/numberText.js'

const props = defineProps({ text: { type: String, default: '' } })
const html = computed(() => renderMarkdown(keepNumbersTogether(props.text)))
</script>

<template>
  <div class="w-text" v-html="html" />
</template>

<style scoped>
.w-text {
  font-size: var(--fs-base);
  line-height: 1.65;
  color: var(--text);
  overflow-wrap: anywhere;
  text-wrap: pretty;
}
.w-text :deep(h1),
.w-text :deep(h2),
.w-text :deep(h3),
.w-text :deep(h4) {
  font-size: var(--fs-base);
  font-weight: var(--fw-bold);
  margin: var(--s-4) 0 var(--s-2);
}
.w-text :deep(h1:first-child),
.w-text :deep(h2:first-child),
.w-text :deep(h3:first-child),
.w-text :deep(h4:first-child) { margin-top: 0; }
.w-text :deep(p) { margin: 0 0 var(--s-3); }
.w-text :deep(p:last-child) { margin-bottom: 0; }
.w-text :deep(ul),
.w-text :deep(ol) { margin: var(--s-2) 0 var(--s-3); padding-left: var(--s-5); }
.w-text :deep(ul:last-child),
.w-text :deep(ol:last-child) { margin-bottom: 0; }
.w-text :deep(li) { margin-bottom: 4px; }
.w-text :deep(strong) { font-weight: var(--fw-bold); }
.w-text :deep(a) {
  color: var(--orange-text);
  text-decoration: underline;
  text-underline-offset: 2px;
  text-decoration-color: var(--orange-line);
}
.w-text :deep(a:hover) { text-decoration-color: currentColor; }
.w-text :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.92em;
  background: var(--surface-2);
  padding: 1px 5px;
}
.w-text :deep(pre) {
  background: var(--surface-2);
  border: 1px solid var(--border);
  padding: var(--s-3);
  overflow-x: auto;
  margin: 0 0 var(--s-3);
}
.w-text :deep(pre code) { background: none; padding: 0; }
/* A small markdown table inside the narrative: the chat's table recipe. */
.w-text :deep(table) {
  display: block;
  width: max-content;
  max-width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
  border: 1px solid var(--border-strong);
  margin: var(--s-2) 0 var(--s-3);
  font-size: var(--fs-sm);
  line-height: 1.5;
}
.w-text :deep(thead th) {
  background: var(--surface);
  border-bottom: 1px solid var(--border-strong);
  padding: 8px 12px;
  text-align: left;
  font-size: 11px;
  font-weight: var(--fw-heavy);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-2);
  white-space: nowrap;
}
.w-text :deep(tbody td) {
  padding: 7px 12px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
  font-variant-numeric: tabular-nums;
}
.w-text :deep(tbody tr:last-child td) { border-bottom: none; }
.w-text :deep(th[style*="text-align:right"]), .w-text :deep(td[style*="text-align:right"]),
.w-text :deep(th[style*="text-align: right"]), .w-text :deep(td[style*="text-align: right"]) { text-align: right; }
.w-text :deep(blockquote) {
  margin: 0 0 var(--s-3);
  padding: 2px 0 2px var(--s-4);
  border-left: 2px solid var(--border-strong);
  color: var(--text-2);
}
.w-text :deep(hr) { border: none; border-top: 1px solid var(--border-strong); margin: var(--s-4) 0; }
</style>
