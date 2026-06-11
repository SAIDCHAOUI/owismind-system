<script setup>
// Per-message detailed feedback — ADAPTIVE to the rating it edits:
//   • rating === 0 (negative): pick one or more reasons + an optional comment.
//   • rating === 1 (positive): comment only (no reasons block) — "what did you like".
// Reasons reuse the maquette's i18n (fb.reason.*) + the new 'other'. The parent
// (MessageAgent) owns persistence; this component only collects + emits.
//
// Built on the shared `Modal` primitive (components/ui): visibility is bound one-way
// via :model-value (the parent owns the open flag) and it exposes a `#footer` slot for
// the actions. The Modal's intrinsic dismissals (Escape / scrim / × button) emit
// `close`, which we route to `cancel` so the parent closes the modal.
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Modal, Button } from '../ui'

const props = defineProps({
  open: { type: Boolean, default: false },
  // The rating this modal is collecting context for: 0 = negative, 1 = positive.
  rating: { type: Number, default: 0 },
  initialReasons: { type: Array, default: () => [] },
  initialComment: { type: String, default: '' },
})
const emit = defineEmits(['submit', 'cancel'])
const { t } = useI18n()

// Reasons only make sense for a negative rating; a positive one is comment-only.
const isNegative = computed(() => props.rating === 0)

const REASONS = ['incorrect', 'incomplete', 'off_topic', 'other']
const selected = ref([])
const comment = ref('')

// Re-seed the form whenever the modal (re)opens — supports editing an existing 👎.
watch(
  () => props.open,
  (open) => {
    if (open) {
      selected.value = Array.isArray(props.initialReasons) ? [...props.initialReasons] : []
      comment.value = props.initialComment || ''
    }
  },
  { immediate: true },
)

function toggle(code) {
  const i = selected.value.indexOf(code)
  if (i === -1) selected.value.push(code)
  else selected.value.splice(i, 1)
}
function submit() {
  // Positive feedback never carries reasons — force an empty list.
  emit('submit', isNegative.value ? [...selected.value] : [], comment.value.trim())
}
</script>

<template>
  <Modal
    :model-value="open"
    :title="isNegative ? t('msg.feedback_title') : t('msg.feedback_title_positive')"
    @close="emit('cancel')"
  >
    <p class="fb-eyebrow">{{ t('msg.feedback_eyebrow') }}</p>
    <!-- Reasons are negative-only; a positive rating is comment-only. -->
    <template v-if="isNegative">
      <p class="fb-label">{{ t('msg.feedback_reasons_label') }}</p>
      <div class="fb-reasons">
        <button
          v-for="code in REASONS"
          :key="code"
          type="button"
          class="fb-chip"
          :class="{ on: selected.includes(code) }"
          @click="toggle(code)"
        >
          {{ t('fb.reason.' + code) }}
        </button>
      </div>
    </template>
    <p class="fb-label">
      {{ isNegative ? t('msg.feedback_suggestion_label') : t('msg.feedback_suggestion_label_positive') }}
    </p>
    <textarea
      v-model="comment"
      class="fb-comment"
      rows="3"
      :placeholder="t('msg.feedback_suggestion_placeholder')"
    />
    <template #footer>
      <Button variant="ghost" @click="emit('cancel')">{{ t('msg.cancel') }}</Button>
      <Button variant="primary" @click="submit">{{ t('msg.feedback_submit') }}</Button>
    </template>
  </Modal>
</template>

<style scoped>
.fb-eyebrow { font-size: var(--fs-xs); color: var(--text-3); margin: 0 0 var(--s-3); }
.fb-label { font-size: var(--fs-sm); color: var(--text-2); margin: var(--s-3) 0 var(--s-2); }
.fb-reasons { display: flex; flex-wrap: wrap; gap: var(--s-2); }
.fb-chip {
  padding: 6px 12px; border: 1px solid var(--border); border-radius: 999px;
  font-size: var(--fs-sm); color: var(--text-2); transition: all var(--dur) var(--ease);
}
.fb-chip:hover { border-color: var(--orange); color: var(--text); }
.fb-chip.on { background: var(--orange-soft-dark); border-color: var(--orange); color: var(--orange); font-weight: 500; }
.fb-comment {
  width: 100%; margin-top: var(--s-2); padding: var(--s-3); border: 1px solid var(--border);
  border-radius: var(--r-sm); background: var(--surface); color: var(--text);
  font-family: inherit; font-size: var(--fs-sm); resize: vertical;
}
</style>
