<script setup>
// Full-transparency detail of the on-screen SOURCE-DATA context (nothing hidden). Shared
// by the user bubble (inline expand, MessageUser) and the prompt chip (popover, PromptBar).
// Purely presentational: it takes a sanitized source_state `snap` and renders every present
// field as a compact dl-like list via the pure model (describeSnapshot). A CALC row prefixes
// the translated function label (fnKey); an ANALYZE row appends the translated "top 50 shown"
// flag when truncated. Locale-neutral values are shown verbatim; only labels are translated.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { describeSnapshot } from '../../composables/screenContextModel.js'

const props = defineProps({
  snap: { type: Object, default: null },
})

const { t } = useI18n()
const rows = computed(() => describeSnapshot(props.snap))

// The value column text. Every connector word is TRANSLATED here (the pure model returns
// keys + raw identifiers only, never English prose):
//   - ANALYZE row (has `group`): "<Fn> <of> <measure|rows> <by> <group> (<bucket>) : <top>"
//   - CALC row (fnKey + text):   "<Fn>(<column>) = <value>"
//   - FILTER row with `more`:    "<predicate> (+N more)" via the prompt.screen.d.more key
//   - anything else:             raw verbatim text
function valueText(row) {
  let out
  if (row.group) {
    out = t(row.fnKey) + ' ' + t('prompt.screen.d.of') + ' '
      + (row.measureText || t('prompt.screen.d.rowsWord'))
      + ' ' + t('prompt.screen.d.by') + ' ' + row.group
      + (row.bucketKey ? ' (' + t(row.bucketKey) + ')' : '')
    if (row.topText) out += ' : ' + row.topText
  } else {
    out = row.fnKey ? t(row.fnKey) + row.text : row.text
    if (row.more) out += ' ' + t('prompt.screen.d.more', [row.more])
  }
  if (row.truncated) out += ' (' + t('prompt.screen.d.truncated') + ')'
  return out
}
</script>

<template>
  <div class="sc-detail">
    <div class="sc-title">{{ t('prompt.screen.d.title') }}</div>
    <dl class="sc-rows">
      <div v-for="row in rows" :key="row.key" class="sc-row">
        <dt class="sc-label">{{ t(row.labelKey) }}</dt>
        <dd class="sc-value">{{ valueText(row) }}</dd>
      </div>
    </dl>
  </div>
</template>

<style scoped>
/* Flat, square, sober (charte). Ink-on-surface, 1px borders, no fill accent. */
.sc-detail {
  max-width: 420px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 0;
}
.sc-title {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: var(--fw-bold);
  color: var(--text-2);
  padding: var(--s-2) var(--s-3);
  border-bottom: 1px solid var(--border);
}
.sc-rows { display: block; }
.sc-row {
  display: grid;
  grid-template-columns: 92px 1fr;
  gap: var(--s-3);
  padding: 6px var(--s-3);
  border-bottom: 1px solid var(--border);
}
.sc-row:last-child { border-bottom: none; }
.sc-label {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-3);
  overflow-wrap: anywhere;
}
.sc-value {
  font-size: var(--fs-xs);
  font-family: var(--font-mono);
  color: var(--text);
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
</style>
