// Prompt context store - the queue of data values a user picked from Source Data
// tables to hand the agent with their next question. Thin reactive wrapper over the
// pure promptContextModel: the store owns only the list; all rules (normalize, dedup,
// cap, block rendering) live in the model. Cleared by the prompt bar right after send.
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  addContextValue,
  buildContextBlock,
  contextKey,
} from '../composables/promptContextModel.js'
import { track } from '../services/track.js'

export const usePromptContextStore = defineStore('promptContext', () => {
  const items = ref([])

  // Queue one picked value. Returns the model status ('added' | 'exists' | 'full' |
  // 'invalid') so the caller can surface the right toast.
  function add(item) {
    const result = addContextValue(items.value, item)
    items.value = result.items
    // Record only a genuine addition (not a dedup 'exists' / 'full' / 'invalid' no-op).
    if (result.status === 'added') track('cell_value_added_to_prompt', { column: (item && item.column) || null })
    return result.status
  }
  function remove(key) {
    items.value = items.value.filter((it) => contextKey(it) !== key)
    track('cell_value_removed_from_prompt', {})
  }
  function clear() {
    items.value = []
  }

  const count = computed(() => items.value.length)
  const hasItems = computed(() => items.value.length > 0)

  // Render the trailing message block for the given UI language ('' when empty).
  function block(lang) {
    return buildContextBlock(items.value, lang)
  }

  return { items, add, remove, clear, count, hasItems, block }
})
