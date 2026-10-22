<script setup>
// Analysis scope in the Studio header: the text widget the agent published with
// role "scope" (what this Studio session covers), shown beside the "Studio" title
// instead of on the board. Its title is a small label, its markdown (the app's ONLY
// markdown path, useMarkdown.js) is clamped to two lines with a "more" / "less"
// toggle that only appears when the text overflows. It updates live during a run.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { renderMarkdown } from '../../composables/useMarkdown.js'

const props = defineProps({ widget: { type: Object, required: true } })
const { t } = useI18n()

const html = computed(() => renderMarkdown(props.widget.text || ''))
const open = ref(false)
const overflows = ref(false)
const body = ref(null)

// Measured while clamped only (an open body shows everything by definition).
function measure() {
  const el = body.value
  if (!el || open.value) return
  overflows.value = el.scrollHeight > el.clientHeight + 1
}
let ro = null
onMounted(() => {
  measure()
  if (body.value && typeof ResizeObserver === 'function') {
    ro = new ResizeObserver(measure)
    ro.observe(body.value)
  }
})
onBeforeUnmount(() => {
  if (ro) ro.disconnect()
  ro = null
})
watch(() => props.widget.id, () => { open.value = false })
watch([html, open], () => nextTick(measure))
</script>

<template>
  <section class="scope" :aria-label="t('ws.scope.aria')">
    <span class="scope-label">{{ widget.title }}</span>
    <div ref="body" class="scope-body" :class="{ open }" v-html="html" />
    <button
      v-if="overflows || open"
      type="button"
      class="scope-more"
      :aria-expanded="open"
      @click="open = !open"
    >{{ t(open ? 'ws.scope.less' : 'ws.scope.more') }}</button>
  </section>
</template>

<style scoped>
.scope {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  min-width: 0;
  padding-left: var(--s-4);
  border-left: 1px solid var(--border);
}
.scope-label {
  max-width: 100%;
  font-size: 11px;
  font-weight: var(--fw-heavy);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* Two lines at rest; paragraphs and list items run inline so the clamp counts lines. */
.scope-body {
  width: 100%;
  font-size: var(--fs-xs);
  line-height: var(--lh-text);
  color: var(--text);
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
}
.scope-body :deep(p),
.scope-body :deep(ul),
.scope-body :deep(ol),
.scope-body :deep(li),
.scope-body :deep(h1),
.scope-body :deep(h2),
.scope-body :deep(h3),
.scope-body :deep(h4) {
  display: inline;
  margin: 0;
  padding: 0;
  font-size: inherit;
}
.scope-body :deep(h1),
.scope-body :deep(h2),
.scope-body :deep(h3),
.scope-body :deep(h4),
.scope-body :deep(strong) { font-weight: var(--fw-bold); }
.scope-body :deep(p + p)::before,
.scope-body :deep(li + li)::before { content: ' '; }
.scope-body :deep(li)::after { content: ';'; }
.scope-body :deep(li:last-child)::after { content: ''; }
.scope-body :deep(a) {
  color: var(--orange-text);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.scope-body :deep(code) { font-family: var(--font-mono); font-size: 0.92em; }
.scope-body :deep(table),
.scope-body :deep(pre),
.scope-body :deep(blockquote),
.scope-body :deep(hr) { display: none; }
/* Open: the full text as written (blocks back), bounded so the board stays in view. */
.scope-body.open {
  display: block;
  -webkit-line-clamp: unset;
  line-clamp: unset;
  max-height: 14em;
  overflow-y: auto;
}
.scope-body.open :deep(p),
.scope-body.open :deep(ul),
.scope-body.open :deep(ol),
.scope-body.open :deep(h1),
.scope-body.open :deep(h2),
.scope-body.open :deep(h3),
.scope-body.open :deep(h4) { display: block; margin: 0 0 4px; }
.scope-body.open :deep(ul),
.scope-body.open :deep(ol) { padding-left: var(--s-4); }
.scope-body.open :deep(pre),
.scope-body.open :deep(blockquote),
.scope-body.open :deep(hr) { display: block; margin: 0 0 4px; }
.scope-body.open :deep(table) { display: table; margin: 0 0 4px; }
.scope-body.open :deep(li) { display: list-item; }
.scope-body.open :deep(li)::after,
.scope-body.open :deep(p + p)::before,
.scope-body.open :deep(li + li)::before { content: none; }
.scope-more {
  font-size: 11px;
  color: var(--text-2);
  text-decoration: underline;
  text-decoration-color: var(--border-strong);
  text-underline-offset: 3px;
  transition: color var(--dur) var(--ease);
}
.scope-more:hover { color: var(--text); text-decoration-color: var(--text); }
</style>
