<script setup>
// "Go further" under an answer: the 2 or 3 next analyses the agent proposed
// (workspace op suggest.set, live from the run or restored with the answer's
// document). Each chip is a ready-to-send request: a click sends its text as the next
// user message, exactly like typing it + Enter. While a run is in progress the chips
// stay focusable but inert (aria-disabled), so the keyboard position is never lost.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '../../stores/chat.js'
import { canPickSuggestion, sendSuggestion } from '../../composables/suggestionChips.js'

const props = defineProps({
  items: { type: Array, default: () => [] },
})
const { t } = useI18n()
const chat = useChatStore()

const inert = computed(() => !canPickSuggestion(chat))

function pick(text) {
  sendSuggestion(chat, text)
}
</script>

<template>
  <div v-if="items.length" class="next" role="group" :aria-label="t('msg.next.aria')">
    <div class="next-label">{{ t('msg.next.label') }}</div>
    <div class="next-chips">
      <button
        v-for="item in props.items"
        :key="item"
        type="button"
        class="next-chip"
        :aria-disabled="inert ? 'true' : 'false'"
        :title="inert ? t('msg.next.busy') : undefined"
        @click="pick(item)"
      >{{ item }}</button>
    </div>
  </div>
</template>

<style scoped>
.next { margin-top: var(--s-3); display: flex; flex-direction: column; gap: var(--s-2); }
.next-label {
  font-size: 11px;
  font-weight: var(--fw-bold);
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--text-2);
}
/* Chips wrap on as many lines as the column needs; a long request wraps inside its
   own chip instead of overflowing the chat column. */
.next-chips { display: flex; flex-wrap: wrap; gap: var(--s-2); }
.next-chip {
  max-width: 100%;
  padding: 6px 12px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-pill);
  background: transparent;
  color: var(--text);
  font-size: var(--fs-sm);
  line-height: 1.4;
  text-align: left;
  overflow-wrap: anywhere;
  cursor: pointer;
  transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.next-chip:hover:not([aria-disabled='true']) { background: var(--surface-2); border-color: var(--text-3); }
.next-chip:active:not([aria-disabled='true']) { background: var(--surface-press); }
.next-chip[aria-disabled='true'] { color: var(--text-3); cursor: not-allowed; }
</style>
