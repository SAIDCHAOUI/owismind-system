<script setup>
// Benchmark suggestions (ALL users) - the collaborative golden-set intake.
//
// Two modes, ONE page:
//   - FROM CHAT: reached from the "..." menu under an agent answer. The benchmark store
//     carries a transient prefill { exchangeId, question, agentAnswer }; the form shows the
//     question + agent answer read-only, a Yes/No verdict, and (when No) the correct answer +
//     what was wrong. Submit sends only the exchange_id + verdict + correction; the backend
//     reconstructs the authoritative Q/A.
//   - MANUAL: a brand-new Q/A from scratch (question + the answer the user vouches for, an
//     optional crisp value to anchor on, a category).
// Below either form: the user's own past suggestions with their review status.
//
// No hardcoded benchmark data: everything is user input, validated + bounded server-side.
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useBenchmarkStore } from '../stores/benchmark.js'
import { useToasts } from '../composables/useToasts.js'
import { PageShell } from '../components/pages'
import { Icon, Button } from '../components/ui'

const { t, locale } = useI18n()
const bench = useBenchmarkStore()
const { push } = useToasts()

const fromChat = computed(() => !!bench.prefill)

// --- From-chat form state ----------------------------------------------------
const verdict = ref(null) // null | true | false (null = not chosen yet)
const chatReference = ref('')
const chatMissing = ref('')
const chatCategory = ref('')

// --- Manual form state -------------------------------------------------------
const question = ref('')
const reference = ref('')
const expectedValue = ref('')
const expectedType = ref('')
const category = ref('')

const EXPECTED_TYPES = ['numeric', 'currency', 'date', 'string', 'list']

const submitting = ref(false)

// Reset the chat form whenever a new prefill arrives (a fresh "suggest" click).
watch(
  () => bench.prefill,
  () => {
    verdict.value = null
    chatReference.value = ''
    chatMissing.value = ''
    chatCategory.value = ''
  },
)

// --- Submit gating (client side; the server re-validates everything) ----------
const canSubmitChat = computed(() => {
  if (verdict.value === null) return false
  // A "No" verdict must carry the correct answer; a "Yes" needs nothing more.
  if (verdict.value === false && !chatReference.value.trim()) return false
  return true
})
const canSubmitManual = computed(() => {
  if (!question.value.trim() || !reference.value.trim()) return false
  // A crisp value requires its type (the objective anchor needs it).
  if (expectedValue.value.trim() && !expectedType.value) return false
  return true
})

function toastError(code) {
  // The backend returns a stable code; we keep the message generic + actionable.
  push(t('bench.send_failed'), { icon: 'alert', tone: 'warn' })
}

async function submitChat() {
  if (!canSubmitChat.value || submitting.value) return
  submitting.value = true
  try {
    // The correction fields are hidden on a "Yes" verdict but their refs are not auto-cleared,
    // so gate them by the verdict here: a "Yes" must never carry stale correction text (the
    // server would otherwise store it as the reference instead of the agent's own answer).
    const isNo = verdict.value === false
    await bench.submitFromChat({
      exchange_id: bench.prefill.exchangeId,
      answer_is_correct: verdict.value,
      reference_answer: isNo ? chatReference.value.trim() || undefined : undefined,
      missing_explanation: isNo ? chatMissing.value.trim() || undefined : undefined,
      category: chatCategory.value.trim() || undefined,
    })
    push(t('bench.sent'), { icon: 'check', tone: 'ok' })
  } catch (e) {
    toastError(e && e.message)
  } finally {
    submitting.value = false
  }
}

async function submitManual() {
  if (!canSubmitManual.value || submitting.value) return
  submitting.value = true
  try {
    await bench.submitManual({
      question: question.value.trim(),
      reference_answer: reference.value.trim(),
      expected_value: expectedValue.value.trim() || undefined,
      expected_value_type: expectedValue.value.trim() ? expectedType.value : undefined,
      category: category.value.trim() || undefined,
      language: locale.value === 'en' ? 'en' : 'fr',
    })
    push(t('bench.sent'), { icon: 'check', tone: 'ok' })
    question.value = ''
    reference.value = ''
    expectedValue.value = ''
    expectedType.value = ''
    category.value = ''
  } catch (e) {
    toastError(e && e.message)
  } finally {
    submitting.value = false
  }
}

function discardPrefill() {
  bench.clearPrefill()
}

// --- My suggestions ----------------------------------------------------------
onMounted(() => {
  bench.loadMine()
})

// The prefill is transient: clear it when leaving the page so the standalone "Benchmark" nav
// link always opens the blank manual form (the from-chat flow sets it again right before it
// navigates here, so it still survives this mount).
onBeforeUnmount(() => {
  bench.clearPrefill()
})

function statusLabel(s) {
  if (s === 'accepted') return t('bench.status.accepted')
  if (s === 'rejected') return t('bench.status.rejected')
  return t('bench.status.pending')
}
function fmtDate(value) {
  if (!value) return ''
  try {
    return new Date(value).toLocaleDateString(locale.value)
  } catch (e) {
    return String(value)
  }
}
</script>

<template>
  <PageShell :eyebrow="t('bench.eyebrow')" :title="t('bench.title')" :desc="t('bench.desc')">
    <!-- ============================ FROM CHAT ============================ -->
    <section v-if="fromChat" class="bench-card">
      <div class="bench-card-head">
        <span class="ico-square"><Icon name="message" :size="18" /></span>
        <h2 class="bench-card-title">{{ t('bench.modal.title') }}</h2>
      </div>
      <p class="bench-card-intro">{{ t('bench.modal.intro') }}</p>

      <div class="bench-field">
        <label class="bench-label">{{ t('bench.modal.question_label') }}</label>
        <div class="bench-readonly">{{ bench.prefill.question }}</div>
      </div>
      <div class="bench-field">
        <label class="bench-label">{{ t('bench.modal.answer_label') }}</label>
        <div class="bench-readonly bench-readonly--answer">{{ bench.prefill.agentAnswer }}</div>
      </div>

      <div class="bench-field">
        <label class="bench-label">{{ t('bench.modal.verdict_label') }}</label>
        <div class="bench-verdict">
          <button
            type="button"
            class="verdict-btn"
            :class="{ on: verdict === true, ok: verdict === true }"
            @click="verdict = true"
          >
            <Icon name="check" :size="15" /><span>{{ t('bench.modal.verdict_yes') }}</span>
          </button>
          <button
            type="button"
            class="verdict-btn"
            :class="{ on: verdict === false, no: verdict === false }"
            @click="verdict = false"
          >
            <Icon name="alert" :size="15" /><span>{{ t('bench.modal.verdict_no') }}</span>
          </button>
        </div>
      </div>

      <template v-if="verdict === false">
        <div class="bench-field">
          <label class="bench-label">{{ t('bench.modal.reference_label') }}</label>
          <textarea
            v-model="chatReference"
            class="bench-input"
            rows="3"
            :placeholder="t('bench.modal.reference_ph')"
          />
        </div>
        <div class="bench-field">
          <label class="bench-label">{{ t('bench.modal.missing_label') }}</label>
          <textarea
            v-model="chatMissing"
            class="bench-input"
            rows="2"
            :placeholder="t('bench.modal.missing_ph')"
          />
        </div>
      </template>

      <div class="bench-field">
        <label class="bench-label">{{ t('bench.modal.category_label') }}</label>
        <input v-model="chatCategory" class="bench-input" type="text" :placeholder="t('bench.modal.category_ph')" />
      </div>

      <div class="bench-actions">
        <Button variant="ghost" @click="discardPrefill">{{ t('bench.modal.cancel') }}</Button>
        <Button variant="primary" :disabled="!canSubmitChat || submitting" @click="submitChat">
          {{ submitting ? t('bench.form.submitting') : t('bench.modal.submit') }}
        </Button>
      </div>
    </section>

    <!-- ============================= MANUAL ============================= -->
    <section v-else class="bench-card">
      <div class="bench-card-head">
        <span class="ico-square"><Icon name="bookOpen" :size="18" /></span>
        <h2 class="bench-card-title">{{ t('bench.form.title') }}</h2>
      </div>

      <div class="bench-field">
        <label class="bench-label">{{ t('bench.form.question_label') }}</label>
        <textarea v-model="question" class="bench-input" rows="2" :placeholder="t('bench.form.question_ph')" />
      </div>
      <div class="bench-field">
        <label class="bench-label">{{ t('bench.form.reference_label') }}</label>
        <textarea v-model="reference" class="bench-input" rows="3" :placeholder="t('bench.form.reference_ph')" />
      </div>

      <div class="bench-field-row">
        <div class="bench-field bench-field--grow">
          <label class="bench-label">{{ t('bench.form.expected_label') }}</label>
          <input v-model="expectedValue" class="bench-input" type="text" :placeholder="t('bench.form.expected_ph')" />
        </div>
        <div class="bench-field">
          <label class="bench-label">{{ t('bench.form.expected_type_label') }}</label>
          <select v-model="expectedType" class="bench-input bench-select">
            <option value="">{{ t('bench.form.type.none') }}</option>
            <option v-for="ty in EXPECTED_TYPES" :key="ty" :value="ty">{{ t('bench.form.type.' + ty) }}</option>
          </select>
        </div>
      </div>
      <p class="bench-help">{{ t('bench.form.expected_help') }}</p>

      <div class="bench-field">
        <label class="bench-label">{{ t('bench.form.category_label') }}</label>
        <input v-model="category" class="bench-input" type="text" :placeholder="t('bench.form.category_ph')" />
      </div>

      <div class="bench-actions">
        <Button variant="primary" :disabled="!canSubmitManual || submitting" @click="submitManual">
          {{ submitting ? t('bench.form.submitting') : t('bench.form.submit') }}
        </Button>
      </div>
    </section>

    <!-- ========================= MY SUGGESTIONS ========================= -->
    <section class="bench-mine">
      <h2 class="bench-mine-title">{{ t('bench.mine.title') }}</h2>
      <p v-if="bench.loadingMine && !bench.mySuggestions.length" class="bench-mine-state">
        {{ t('bench.mine.loading') }}
      </p>
      <p v-else-if="!bench.mySuggestions.length" class="bench-mine-state">{{ t('bench.mine.empty') }}</p>
      <table v-else class="bench-table">
        <thead>
          <tr>
            <th>{{ t('bench.mine.col_question') }}</th>
            <th class="col-narrow">{{ t('bench.mine.col_source') }}</th>
            <th class="col-narrow">{{ t('bench.mine.col_status') }}</th>
            <th class="col-narrow">{{ t('bench.mine.col_date') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="s in bench.mySuggestions" :key="s.suggestion_id">
            <td class="cell-question" :title="s.question">{{ s.question }}</td>
            <td class="col-narrow">{{ s.source === 'chat' ? t('bench.source.chat') : t('bench.source.manual') }}</td>
            <td class="col-narrow">
              <span class="status-pill" :class="s.status">{{ statusLabel(s.status) }}</span>
            </td>
            <td class="col-narrow mono">{{ fmtDate(s.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </PageShell>
</template>

<style scoped>
/* Orange charter: square geometry (border-radius 0), 1px borders, flat surfaces, orange a
   RARE accent. Semantic tokens only; no gradient/blur/glow/color-mix. */
.bench-card {
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--bg);
  padding: var(--s-6);
  margin-bottom: var(--s-7);
}
.bench-card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: var(--s-3);
}
.ico-square {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  display: grid;
  place-items: center;
  background: var(--bg);
  color: var(--orange);
}
.bench-card-title {
  font-size: var(--fs-lg);
  font-weight: var(--fw-heavy);
  color: var(--text);
  margin: 0;
}
.bench-card-intro {
  font-size: var(--fs-sm);
  color: var(--text-2);
  line-height: 1.6;
  margin: 0 0 var(--s-5);
}

/* Fields */
.bench-field {
  margin-bottom: var(--s-4);
}
.bench-field-row {
  display: flex;
  gap: var(--s-4);
  align-items: flex-end;
}
.bench-field--grow {
  flex: 1;
  margin-bottom: 0;
}
.bench-field-row .bench-field {
  margin-bottom: 0;
}
.bench-label {
  display: block;
  font-size: var(--fs-sm);
  font-weight: var(--fw-semibold, 600);
  color: var(--text-2);
  margin-bottom: 7px;
}
.bench-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  font-size: var(--fs-base);
  transition: border-color var(--dur) var(--ease);
  resize: vertical;
}
.bench-input:focus {
  outline: none;
  border-color: var(--orange);
}
.bench-input::placeholder {
  color: var(--text-3);
}
.bench-select {
  min-width: 150px;
  resize: none;
  cursor: pointer;
}

/* Read-only prefilled blocks (question + agent answer from chat). */
.bench-readonly {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 0;
  background: var(--surface);
  color: var(--text);
  font-size: var(--fs-base);
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.bench-readonly--answer {
  max-height: 240px;
  overflow-y: auto;
}

/* Verdict dial: two square buttons; selected state borrows success/danger sparingly. */
.bench-verdict {
  display: flex;
  gap: var(--s-3);
  flex-wrap: wrap;
}
.verdict-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--bg);
  color: var(--text-2);
  font-size: var(--fs-sm);
  font-weight: var(--fw-semibold, 600);
  cursor: pointer;
  transition: border-color var(--dur) var(--ease), color var(--dur) var(--ease);
}
.verdict-btn:hover {
  border-color: var(--text);
  color: var(--text);
}
.verdict-btn :deep(.ui-icon) {
  width: 15px;
  height: 15px;
}
.verdict-btn.on.ok {
  border-color: var(--success);
  color: var(--success);
}
.verdict-btn.on.no {
  border-color: var(--danger);
  color: var(--danger);
}

.bench-help {
  font-size: var(--fs-xs);
  color: var(--text-3);
  line-height: 1.5;
  margin: -2px 0 var(--s-4);
}
.bench-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--s-3);
  margin-top: var(--s-5);
}

/* My suggestions */
.bench-mine {
  margin-top: var(--s-6);
}
.bench-mine-title {
  font-size: var(--fs-md);
  font-weight: var(--fw-heavy);
  color: var(--text);
  margin: 0 0 var(--s-4);
}
.bench-mine-state {
  font-size: var(--fs-sm);
  color: var(--text-3);
  margin: 0;
}
.bench-table {
  width: 100%;
  border-collapse: collapse;
  border: 1px solid var(--border-strong);
  font-size: var(--fs-sm);
}
.bench-table th,
.bench-table td {
  text-align: left;
  padding: 9px 12px;
  border-bottom: 1px solid var(--border);
  color: var(--text-2);
}
.bench-table th {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-3);
  font-weight: 700;
  background: var(--surface);
}
.bench-table tbody tr:last-child td {
  border-bottom: none;
}
.cell-question {
  color: var(--text);
  max-width: 0;
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.col-narrow {
  white-space: nowrap;
  width: 1%;
}
.status-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 0;
  font-size: 11px;
  font-weight: 700;
  border: 1px solid var(--border-strong);
  color: var(--text-2);
  background: var(--surface);
}
.status-pill.accepted {
  border-color: var(--success);
  color: var(--success);
}
.status-pill.rejected {
  border-color: var(--danger);
  color: var(--danger);
}

@media (max-width: 640px) {
  .bench-field-row {
    flex-direction: column;
    align-items: stretch;
  }
  .bench-field-row .bench-field {
    margin-bottom: var(--s-4);
  }
}
</style>
