<script setup>
// Benchmark tab (ALL users) - three stacked areas on one page:
//
//   1. CONSULTATION (default, first): pick a benchmark-capable agent, read its latest
//      run as a confidence donut + hero verdict + KPI tiles + per-config table +
//      per-category bars + a question-by-question table with expandable rows. A run
//      selector switches between past runs. Plain-language, never crashes (configured
//      / read-error / empty states are explicit).
//   2. ADMIN REVIEW + OVERRIDE (admins only): the same per-question rows gain
//      "Mark correct / Mark incorrect / Clear override" + a comment, posted to the
//      admin override endpoint; the effective verdict updates on success.
//   3. SUGGEST (collapsible sub-section below): the existing from-chat + manual
//      golden-set intake, unchanged. Auto-opens when reached from a chat answer.
//
// No hardcoded benchmark data: results come from the backend, suggestions are user
// input, everything is validated + bounded server-side.
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useBenchmarkStore } from '../stores/benchmark.js'
import { useSessionStore } from '../stores/session.js'
import { useToasts } from '../composables/useToasts.js'
import { formatMoney, formatShortDate } from '../composables/budgetModel.js'
import {
  donutGeometry,
  bandToken,
  pctFromAccuracy,
  pctText,
  verdictKind,
  rowKey,
  hasScoredResults,
} from '../composables/benchmarkResults.js'
import { PageShell, EmptyState } from '../components/pages'
import { Icon, Button } from '../components/ui'

const { t, locale } = useI18n()
const bench = useBenchmarkStore()
const session = useSessionStore()
const { push } = useToasts()

const isAdmin = computed(() => session.isAdmin)

// =============================== CONSULTATION ================================
// Only enabled agents that the admin marked as having a benchmark (has_benchmark).
const benchmarkAgents = computed(() =>
  (session.agents || []).filter((a) => a && a.has_benchmark === true),
)

const results = computed(() => bench.results)
const kpis = computed(() => (results.value && results.value.kpis) || null)
const hasResults = computed(() => hasScoredResults(results.value))

// Donut: fill fraction from the 0..1 accuracy, color from the confidence band.
const donut = computed(() => {
  const acc = kpis.value ? kpis.value.accuracy : 0
  const g = donutGeometry(pctFromAccuracy(acc), 52)
  return {
    circumference: g.circumference,
    offset: g.offset,
    color: bandToken(kpis.value && kpis.value.band),
  }
})
const donutFillStyle = computed(() => ({
  // var() lives in CSS, never in an SVG presentation attribute (it would not resolve).
  stroke: donut.value.color,
  strokeDasharray: donut.value.circumference,
  strokeDashoffset: donut.value.offset,
}))
const centerText = computed(() => {
  if (!kpis.value) return '-'
  const fromPct = pctText(kpis.value.accuracy_pct)
  return fromPct !== '-' ? fromPct : Math.round(pctFromAccuracy(kpis.value.accuracy)) + '%'
})
const bandLabel = computed(() => {
  const b = String((kpis.value && kpis.value.band) || '').toLowerCase()
  if (b === 'high' || b === 'medium' || b === 'low') return t('bench.band.' + b)
  return t('bench.band.unknown')
})

function onAgentChange(e) {
  bench.selectConsultAgent(e.target.value)
}
function onRunChange(e) {
  bench.selectRun(e.target.value)
}

// Auto-select the first benchmark agent once the list is known (so results load
// without an extra click). Re-checks if the list changes (e.g. agents load late).
watch(
  benchmarkAgents,
  (list) => {
    if (list.length && !list.some((a) => a.key === bench.consultAgentKey)) {
      bench.selectConsultAgent(list[0].key)
    }
  },
  { immediate: true },
)

// --- Per-question review (expand state + admin override comments) ------------
const expanded = ref({})
const comments = ref({})

function toggleRow(k) {
  expanded.value[k] = !expanded.value[k]
}

// Re-seed the comment inputs from the rows whenever the results change (newest
// human_comment wins after an override; switching agent/run resets them).
watch(
  results,
  (r) => {
    const seed = {}
    const rows = (r && r.detail) || []
    rows.forEach((row) => {
      seed[rowKey(row)] = row.human_comment || ''
    })
    comments.value = seed
  },
  { immediate: true },
)

function verdictLabel(row) {
  return t('bench.verdict.' + verdictKind(row))
}
function fmtScore(v) {
  return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(2) : '-'
}
function fmtRun(run) {
  if (!run) return ''
  const stamp = run.run_timestamp
  if (stamp) {
    try {
      const d = new Date(stamp)
      if (!Number.isNaN(d.getTime())) return d.toLocaleString(locale.value)
    } catch (e) {
      /* fall through to the raw id */
    }
  }
  return String(run.run_id || '')
}
function catWidth(cat) {
  return pctFromAccuracy(cat && cat.accuracy) + '%'
}
function expectedText(row) {
  if (!row || !row.expected_value) return ''
  const ty = row.expected_value_type ? ' (' + row.expected_value_type + ')' : ''
  return String(row.expected_value) + ty
}

async function applyOverride(row, verdict) {
  const k = rowKey(row)
  if (bench.overrideBusyKey) return
  try {
    await bench.submitOverride(
      {
        agent: bench.consultAgentKey,
        run_id: (results.value && results.value.run_id) || bench.selectedRunId || '',
        question_id: row.question_id,
        agent_key: row.agent_key,
        mode: row.mode,
        verdict,
        comment: (comments.value[k] || '').trim(),
      },
      k,
    )
    push(t('bench.review.saved'), { icon: 'check', tone: 'ok' })
  } catch (e) {
    push(t('bench.review.failed'), { icon: 'alert', tone: 'warn' })
  }
}

// ============================= SUGGEST (existing) ===========================
const fromChat = computed(() => !!bench.prefill)

// The suggest sub-section is collapsed by default (consultation is the focus); it
// auto-opens when the page is reached from a chat answer (a fresh prefill).
const suggestOpen = ref(false)

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

// Reset the chat form whenever a new prefill arrives (a fresh "suggest" click), and
// open the suggest sub-section so the from-chat form is visible.
watch(
  () => bench.prefill,
  (p) => {
    verdict.value = null
    chatReference.value = ''
    chatMissing.value = ''
    chatCategory.value = ''
    if (p) suggestOpen.value = true
  },
)

// --- Submit gating (client side; the server re-validates everything) ----------
const canSubmitChat = computed(() => {
  if (verdict.value === null) return false
  if (verdict.value === false && !chatReference.value.trim()) return false
  return true
})
const canSubmitManual = computed(() => {
  if (!question.value.trim() || !reference.value.trim()) return false
  if (expectedValue.value.trim() && !expectedType.value) return false
  return true
})

function toastError() {
  push(t('bench.send_failed'), { icon: 'alert', tone: 'warn' })
}

async function submitChat() {
  if (!canSubmitChat.value || submitting.value) return
  submitting.value = true
  try {
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
    toastError()
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
    toastError()
  } finally {
    submitting.value = false
  }
}

function discardPrefill() {
  bench.clearPrefill()
}

// --- Lifecycle ---------------------------------------------------------------
onMounted(() => {
  // Identity + the enabled-agents list (memoized; cheap if already loaded).
  session.ensureLoaded()
  bench.loadMine()
  if (fromChat.value) suggestOpen.value = true
})

// The prefill is transient: clear it when leaving the page so the standalone
// "Benchmark" nav link always opens the blank manual form.
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
  <PageShell :eyebrow="t('bench.eyebrow')" :title="t('bench.page_title')" :desc="t('bench.page_desc')">
    <!-- ========================= CONSULTATION ========================= -->
    <section class="bench-section">
      <div class="bench-section-head">
        <span class="ico-square"><Icon name="chart" :size="18" /></span>
        <div>
          <h2 class="bench-section-title">{{ t('bench.consult.title') }}</h2>
          <p class="bench-section-desc">{{ t('bench.consult.desc') }}</p>
        </div>
      </div>

      <!-- No benchmark-capable agent at all -->
      <EmptyState
        v-if="!benchmarkAgents.length"
        bordered
        icon="chart"
        :title="t('bench.consult.no_agents_title')"
        :desc="t('bench.consult.no_agents')"
      />

      <template v-else>
        <!-- Agent + run pickers -->
        <div class="consult-pickers">
          <div class="cp-field">
            <label class="bench-label" for="bench-agent">{{ t('bench.consult.agent_label') }}</label>
            <div class="select-wrap">
              <select
                id="bench-agent"
                class="bench-select-ctl"
                :value="bench.consultAgentKey"
                @change="onAgentChange"
              >
                <option v-for="a in benchmarkAgents" :key="a.key" :value="a.key">{{ a.label }}</option>
              </select>
              <span class="select-arr"><Icon name="chevronDown" /></span>
            </div>
          </div>

          <div v-if="results && results.runs.length > 1" class="cp-field">
            <label class="bench-label" for="bench-run">{{ t('bench.consult.run_label') }}</label>
            <div class="select-wrap">
              <select id="bench-run" class="bench-select-ctl" :value="bench.selectedRunId" @change="onRunChange">
                <option v-for="r in results.runs" :key="r.run_id" :value="r.run_id">{{ fmtRun(r) }}</option>
              </select>
              <span class="select-arr"><Icon name="chevronDown" /></span>
            </div>
          </div>
        </div>

        <!-- States -->
        <p v-if="bench.resultsLoading && !results" class="consult-state">{{ t('bench.consult.loading') }}</p>
        <div v-else-if="!bench.resultsConfigured" class="consult-note">
          <Icon name="info" />
          <span>{{ t('bench.consult.not_configured') }}</span>
        </div>
        <div v-else-if="bench.resultsError" class="consult-note">
          <Icon name="alert" />
          <span>{{ t('bench.consult.load_error') }}</span>
        </div>
        <p v-else-if="!hasResults" class="consult-state">{{ t('bench.consult.no_results') }}</p>

        <!-- Results -->
        <template v-else-if="results && kpis">
          <div v-if="bench.resultsReadError" class="consult-note consult-note--soft">
            <Icon name="info" />
            <span>{{ t('bench.consult.read_error') }}</span>
          </div>

          <!-- Hero: donut + verdict + KPI tiles -->
          <div class="hero">
            <div class="donut-wrap">
              <svg class="donut" viewBox="0 0 120 120" role="img" :aria-label="centerText">
                <circle class="donut-track" cx="60" cy="60" r="52" />
                <circle class="donut-fill" cx="60" cy="60" r="52" :style="donutFillStyle" />
              </svg>
              <div class="donut-center">
                <span class="donut-pct">{{ centerText }}</span>
                <span class="donut-band">{{ bandLabel }}</span>
              </div>
            </div>

            <div class="hero-body">
              <p class="hero-verdict">{{ t('bench.consult.hero', [kpis.n_correct, kpis.n_scored]) }}</p>
              <div class="kpi-row">
                <div class="kpi-tile">
                  <span class="kpi-k">{{ t('bench.kpi.accuracy') }}</span>
                  <span class="kpi-v">{{ centerText }}</span>
                </div>
                <div class="kpi-tile">
                  <span class="kpi-k">{{ t('bench.kpi.questions') }}</span>
                  <span class="kpi-v">{{ kpis.n_questions }}</span>
                </div>
                <div class="kpi-tile">
                  <span class="kpi-k">{{ t('bench.kpi.configs') }}</span>
                  <span class="kpi-v">{{ kpis.n_configs }}</span>
                </div>
                <div class="kpi-tile">
                  <span class="kpi-k">{{ t('bench.kpi.cost') }}</span>
                  <span class="kpi-v mono">{{ kpis.total_cost_str || formatMoney(kpis.total_cost, locale) }}</span>
                </div>
                <div class="kpi-tile" :class="{ 'kpi-tile--warn': kpis.needs_review > 0 }">
                  <span class="kpi-k">{{ t('bench.kpi.needs_review') }}</span>
                  <span class="kpi-v">{{ kpis.needs_review }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- Per agent x mode -->
          <div v-if="results.configs.length" class="block">
            <h3 class="block-title">{{ t('bench.cfg.title') }}</h3>
            <div class="table-scroll">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>{{ t('bench.cfg.col_config') }}</th>
                    <th class="num">{{ t('bench.cfg.col_questions') }}</th>
                    <th class="num">{{ t('bench.cfg.col_ok') }}</th>
                    <th class="num">{{ t('bench.cfg.col_error') }}</th>
                    <th class="num">{{ t('bench.cfg.col_accuracy') }}</th>
                    <th class="num">{{ t('bench.cfg.col_score') }}</th>
                    <th class="num">{{ t('bench.cfg.col_latency') }}</th>
                    <th class="num">{{ t('bench.cfg.col_cost') }}</th>
                    <th class="num">{{ t('bench.cfg.col_review') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(c, i) in results.configs" :key="i">
                    <td>
                      <span class="cfg-agent">{{ c.agent_label || c.agent_key }}</span>
                      <span class="cfg-mode">{{ c.mode }}</span>
                    </td>
                    <td class="num">{{ c.n_questions }}</td>
                    <td class="num">{{ c.n_ok }}</td>
                    <td class="num" :class="{ 'cell-bad': c.n_error > 0 }">{{ c.n_error }}</td>
                    <td class="num strong">{{ pctText(c.accuracy_pct) }}</td>
                    <td class="num mono">{{ fmtScore(c.mean_score) }}</td>
                    <td class="num mono">{{ c.avg_latency_str || '-' }}</td>
                    <td class="num mono">{{ c.avg_cost_str || '-' }}</td>
                    <td class="num" :class="{ 'cell-warn': c.needs_review > 0 }">{{ c.needs_review }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Per category -->
          <div v-if="results.categories.length" class="block">
            <h3 class="block-title">{{ t('bench.cat.title') }}</h3>
            <ul class="cat-list">
              <li v-for="(cat, i) in results.categories" :key="i" class="cat-row">
                <span class="cat-name">{{ cat.bucket || t('bench.cat.uncategorized') }}</span>
                <span class="cat-bar"><span class="cat-fill" :style="{ width: catWidth(cat) }" /></span>
                <span class="cat-val">
                  <span class="strong">{{ pctText(cat.accuracy_pct) }}</span>
                  <span class="cat-n">{{ t('bench.cat.count', [cat.n]) }}</span>
                </span>
              </li>
            </ul>
          </div>

          <!-- Per question -->
          <div v-if="results.detail.length" class="block">
            <h3 class="block-title">{{ t('bench.detail.title') }}</h3>
            <p v-if="isAdmin" class="detail-admin-note">
              <Icon name="info" />{{ t('bench.review.reset_note') }}
            </p>
            <div class="table-scroll">
              <table class="data-table detail-table">
                <thead>
                  <tr>
                    <th class="th-expand"></th>
                    <th>{{ t('bench.detail.col_question') }}</th>
                    <th>{{ t('bench.detail.col_category') }}</th>
                    <th>{{ t('bench.detail.col_agent') }}</th>
                    <th>{{ t('bench.detail.col_judge') }}</th>
                    <th>{{ t('bench.detail.col_verdict') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <template v-for="row in results.detail" :key="rowKey(row)">
                    <tr class="detail-row" :class="{ open: expanded[rowKey(row)] }" @click="toggleRow(rowKey(row))">
                      <td class="th-expand">
                        <Icon :name="expanded[rowKey(row)] ? 'chevronDown' : 'chevronRight'" />
                      </td>
                      <td class="cell-question" :title="row.question">{{ row.question }}</td>
                      <td class="cell-cat">{{ row.category || '-' }}</td>
                      <td>
                        <span class="cfg-agent">{{ row.agent_label || row.agent_key }}</span>
                        <span class="cfg-mode">{{ row.mode }}</span>
                      </td>
                      <td>
                        <span class="judge-verdict">{{ row.judge_verdict || '-' }}</span>
                        <span v-if="row.judge_score != null" class="judge-score mono">{{ fmtScore(row.judge_score) }}</span>
                      </td>
                      <td>
                        <span class="vbadge" :class="'v-' + verdictKind(row)">{{ verdictLabel(row) }}</span>
                        <span v-if="row.overridden" class="v-over">{{ t('bench.verdict.overridden') }}</span>
                      </td>
                    </tr>
                    <tr v-if="expanded[rowKey(row)]" class="detail-expand">
                      <td></td>
                      <td colspan="5">
                        <dl class="exp-grid">
                          <template v-if="row.reference_answer">
                            <dt>{{ t('bench.detail.reference') }}</dt>
                            <dd>{{ row.reference_answer }}</dd>
                          </template>
                          <template v-if="row.expected_value">
                            <dt>{{ t('bench.detail.expected') }}</dt>
                            <dd class="mono">{{ expectedText(row) }}</dd>
                          </template>
                          <template v-if="row.answer_preview">
                            <dt>{{ t('bench.detail.answer') }}</dt>
                            <dd class="exp-answer">{{ row.answer_preview }}</dd>
                          </template>
                          <template v-if="row.judge_comment">
                            <dt>{{ t('bench.detail.judge_comment') }}</dt>
                            <dd>{{ row.judge_comment }}</dd>
                          </template>
                          <template v-if="row.notes">
                            <dt>{{ t('bench.detail.notes') }}</dt>
                            <dd>{{ row.notes }}</dd>
                          </template>
                          <template v-if="row.objective_match != null">
                            <dt>{{ t('bench.detail.objective') }}</dt>
                            <dd>{{ row.objective_match ? t('bench.detail.objective_yes') : t('bench.detail.objective_no') }}</dd>
                          </template>
                          <template v-if="row.reviewed_by">
                            <dt>{{ t('bench.detail.reviewed') }}</dt>
                            <dd>{{ t('bench.review.reviewed_by', [row.reviewed_by, fmtDate(row.reviewed_at)]) }}</dd>
                          </template>
                        </dl>

                        <!-- Admin override controls -->
                        <div v-if="isAdmin" class="override" @click.stop>
                          <div class="override-head">{{ t('bench.review.title') }}</div>
                          <input
                            v-model="comments[rowKey(row)]"
                            class="override-comment"
                            type="text"
                            maxlength="280"
                            :placeholder="t('bench.review.comment_ph')"
                          />
                          <div class="override-actions">
                            <button
                              type="button"
                              class="ov-btn ov-ok"
                              :disabled="bench.overrideBusyKey === rowKey(row)"
                              @click="applyOverride(row, 'correct')"
                            >
                              <Icon name="check" />{{ t('bench.review.mark_correct') }}
                            </button>
                            <button
                              type="button"
                              class="ov-btn ov-no"
                              :disabled="bench.overrideBusyKey === rowKey(row)"
                              @click="applyOverride(row, 'incorrect')"
                            >
                              <Icon name="alert" />{{ t('bench.review.mark_incorrect') }}
                            </button>
                            <button
                              type="button"
                              class="ov-btn"
                              :disabled="bench.overrideBusyKey === rowKey(row) || !row.overridden"
                              @click="applyOverride(row, '')"
                            >
                              <Icon name="refresh" />{{ t('bench.review.clear') }}
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </template>
    </section>

    <!-- ============================ SUGGEST ============================ -->
    <section class="bench-section">
      <button type="button" class="accordion-head" :aria-expanded="suggestOpen" @click="suggestOpen = !suggestOpen">
        <span class="ico-square"><Icon name="bookOpen" :size="18" /></span>
        <span class="accordion-text">
          <span class="bench-section-title">{{ t('bench.section.suggest_title') }}</span>
          <span class="bench-section-desc">{{ t('bench.section.suggest_desc') }}</span>
        </span>
        <Icon class="accordion-chev" :name="suggestOpen ? 'chevronUp' : 'chevronDown'" />
      </button>

      <div v-if="suggestOpen" class="accordion-body">
        <!-- FROM CHAT -->
        <div v-if="fromChat" class="bench-card">
          <div class="bench-card-head">
            <span class="ico-square"><Icon name="message" :size="18" /></span>
            <h3 class="bench-card-title">{{ t('bench.modal.title') }}</h3>
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
        </div>

        <!-- MANUAL -->
        <div v-else class="bench-card">
          <div class="bench-card-head">
            <span class="ico-square"><Icon name="bookOpen" :size="18" /></span>
            <h3 class="bench-card-title">{{ t('bench.form.title') }}</h3>
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
        </div>

        <!-- MY SUGGESTIONS -->
        <div class="bench-mine">
          <h3 class="bench-mine-title">{{ t('bench.mine.title') }}</h3>
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
        </div>
      </div>
    </section>
  </PageShell>
</template>

<style scoped>
/* Orange charter: square geometry (border-radius 0), 1px borders, flat surfaces, orange
   a RARE accent. Semantic tokens only; no gradient/blur/glow/color-mix. */

/* --- Section wrapper --- */
.bench-section {
  margin-bottom: var(--s-7);
}
.bench-section-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: var(--s-5);
}
.bench-section-title {
  font-size: var(--fs-lg);
  font-weight: var(--fw-heavy);
  color: var(--text);
  margin: 0;
  display: block;
}
.bench-section-desc {
  font-size: var(--fs-sm);
  color: var(--text-2);
  line-height: 1.6;
  margin: 4px 0 0;
  display: block;
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

/* --- Pickers --- */
.consult-pickers {
  display: flex;
  gap: var(--s-5);
  flex-wrap: wrap;
  margin-bottom: var(--s-5);
}
.cp-field {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 220px;
}
.select-wrap {
  position: relative;
  display: flex;
}
.bench-select-ctl {
  width: 100%;
  appearance: none;
  -webkit-appearance: none;
  padding: 11px 34px 11px 14px;
  background: var(--bg);
  border: 1px solid var(--border-strong);
  border-radius: 0;
  font-size: 14px;
  font-family: var(--font-sans);
  color: var(--text);
  cursor: pointer;
  transition: border-color var(--dur) var(--ease);
}
.bench-select-ctl:hover {
  border-color: var(--text-3);
}
.bench-select-ctl:focus {
  outline: none;
  border-color: var(--orange);
}
.select-arr {
  position: absolute;
  right: 11px;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
  color: var(--text-3);
}
.select-arr :deep(.ui-icon) {
  width: 14px;
  height: 14px;
}

/* --- States / notes --- */
.consult-state {
  font-size: var(--fs-sm);
  color: var(--text-3);
  margin: var(--s-4) 0;
}
.consult-note {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--surface);
  font-size: var(--fs-sm);
  color: var(--text-2);
  margin-bottom: var(--s-5);
}
.consult-note :deep(.ui-icon) {
  width: 16px;
  height: 16px;
  flex-shrink: 0;
  color: var(--text-3);
}
.consult-note--soft {
  border-color: var(--border);
}

/* --- Hero: donut + verdict + KPI tiles --- */
.hero {
  display: flex;
  align-items: center;
  gap: var(--s-7);
  flex-wrap: wrap;
  padding: var(--s-6);
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--bg);
  margin-bottom: var(--s-6);
}
.donut-wrap {
  position: relative;
  width: 140px;
  height: 140px;
  flex-shrink: 0;
}
.donut {
  width: 140px;
  height: 140px;
}
/* Track + fill colored via CSS / inline style (never via SVG presentation attribute). */
.donut-track {
  fill: none;
  stroke: var(--border);
  stroke-width: 12;
}
.donut-fill {
  fill: none;
  stroke-width: 12;
  stroke-linecap: butt;
  transform: rotate(-90deg);
  transform-origin: 50% 50%;
  transition: stroke-dashoffset var(--dur-slow) var(--ease);
}
.donut-center {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}
.donut-pct {
  font-size: 30px;
  font-weight: var(--fw-heavy);
  color: var(--text);
  line-height: 1;
}
.donut-band {
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-2);
  margin-top: 6px;
}
.hero-body {
  flex: 1;
  min-width: 260px;
}
.hero-verdict {
  font-size: var(--fs-xl);
  font-weight: var(--fw-heavy);
  color: var(--text);
  line-height: 1.2;
  margin: 0 0 var(--s-4);
}
.kpi-row {
  display: flex;
  gap: var(--s-3);
  flex-wrap: wrap;
}
.kpi-tile {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 96px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-top: 3px solid var(--orange);
  background: var(--bg);
}
.kpi-tile--warn {
  border-top-color: var(--warn);
}
.kpi-k {
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-2);
}
.kpi-v {
  font-size: 22px;
  font-weight: var(--fw-heavy);
  color: var(--text);
  line-height: 1;
}
.kpi-v.mono {
  font-family: var(--font-mono);
  font-size: 18px;
}

/* --- Generic block --- */
.block {
  margin-bottom: var(--s-6);
}
.block-title {
  font-size: var(--fs-md);
  font-weight: var(--fw-heavy);
  color: var(--text);
  margin: 0 0 var(--s-4);
}

/* --- Tables --- */
.table-scroll {
  overflow-x: auto;
  border: 1px solid var(--border-strong);
}
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-sm);
}
.data-table th {
  text-align: left;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-3);
  font-weight: 700;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-strong);
  background: var(--surface);
  white-space: nowrap;
}
.data-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  color: var(--text-2);
  vertical-align: middle;
}
.data-table tbody tr:last-child td {
  border-bottom: none;
}
.data-table .num {
  text-align: right;
  white-space: nowrap;
}
.data-table .strong {
  color: var(--text);
  font-weight: 700;
}
.cell-bad {
  color: var(--danger);
  font-weight: 700;
}
.cell-warn {
  color: var(--warn);
  font-weight: 700;
}
.cfg-agent {
  color: var(--text);
  font-weight: var(--fw-semibold);
}
.cfg-mode {
  display: inline-block;
  margin-left: 8px;
  padding: 1px 7px;
  border: 1px solid var(--border-strong);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-2);
}

/* --- Category bars --- */
.cat-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.cat-row {
  display: grid;
  grid-template-columns: 180px 1fr 130px;
  align-items: center;
  gap: var(--s-4);
}
.cat-name {
  font-size: var(--fs-sm);
  color: var(--text);
  font-weight: var(--fw-semibold);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cat-bar {
  height: 8px;
  background: var(--surface-2);
  overflow: hidden;
}
.cat-fill {
  display: block;
  height: 100%;
  background: var(--orange);
}
.cat-val {
  display: flex;
  align-items: baseline;
  gap: 8px;
  justify-content: flex-end;
  font-size: var(--fs-sm);
}
.cat-n {
  font-size: var(--fs-xs);
  color: var(--text-3);
}

/* --- Detail table --- */
.detail-admin-note {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-xs);
  color: var(--text-2);
  margin: 0 0 var(--s-3);
}
.detail-admin-note :deep(.ui-icon) {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  color: var(--text-3);
}
.th-expand {
  width: 30px;
}
.detail-row {
  cursor: pointer;
  transition: background var(--dur) var(--ease);
}
.detail-row:hover {
  background: var(--surface);
}
.detail-row.open {
  background: var(--surface);
}
.detail-row .th-expand :deep(.ui-icon) {
  width: 14px;
  height: 14px;
  color: var(--text-3);
}
.cell-question {
  color: var(--text);
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cell-cat {
  white-space: nowrap;
}
.judge-verdict {
  color: var(--text-2);
}
.judge-score {
  margin-left: 8px;
  color: var(--text-3);
}
.vbadge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 0;
  font-size: 11px;
  font-weight: 700;
  border: 1px solid var(--border-strong);
  color: var(--text-2);
  background: var(--bg);
  white-space: nowrap;
}
.vbadge.v-correct {
  border-color: var(--success);
  color: var(--success);
}
.vbadge.v-incorrect {
  border-color: var(--danger);
  color: var(--danger);
}
.vbadge.v-review {
  border-color: var(--warn);
  color: var(--warn);
}
.v-over {
  display: inline-block;
  margin-left: 6px;
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--orange-text);
}

/* --- Expanded detail row --- */
.detail-expand td {
  background: var(--surface);
  padding: var(--s-5);
}
.exp-grid {
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: 8px 20px;
  margin: 0;
}
.exp-grid dt {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-3);
}
.exp-grid dd {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--text);
  line-height: 1.55;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.exp-answer {
  max-height: 200px;
  overflow-y: auto;
  border: 1px solid var(--border);
  padding: 10px 12px;
  background: var(--bg);
}

/* --- Admin override --- */
.override {
  margin-top: var(--s-5);
  padding-top: var(--s-4);
  border-top: 1px solid var(--border);
}
.override-head {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-2);
  margin-bottom: var(--s-3);
}
.override-comment {
  width: 100%;
  max-width: 520px;
  padding: 9px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--bg);
  color: var(--text);
  font-family: inherit;
  font-size: var(--fs-sm);
  margin-bottom: var(--s-3);
}
.override-comment:focus {
  outline: none;
  border-color: var(--orange);
}
.override-actions {
  display: flex;
  gap: var(--s-3);
  flex-wrap: wrap;
}
.ov-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 13px;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--bg);
  color: var(--text-2);
  font-size: var(--fs-xs);
  font-weight: 700;
  cursor: pointer;
  transition: border-color var(--dur) var(--ease), color var(--dur) var(--ease);
}
.ov-btn:hover:not(:disabled) {
  border-color: var(--text);
  color: var(--text);
}
.ov-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.ov-btn :deep(.ui-icon) {
  width: 14px;
  height: 14px;
}
.ov-ok:hover:not(:disabled) {
  border-color: var(--success);
  color: var(--success);
}
.ov-no:hover:not(:disabled) {
  border-color: var(--danger);
  color: var(--danger);
}

/* --- Suggest accordion --- */
.accordion-head {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--bg);
  text-align: left;
  cursor: pointer;
  transition: border-color var(--dur) var(--ease);
}
.accordion-head:hover {
  border-color: var(--text-3);
}
.accordion-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.accordion-chev {
  flex-shrink: 0;
  color: var(--text-3);
}
.accordion-chev :deep(.ui-icon),
.accordion-head :deep(.accordion-chev) {
  width: 18px;
  height: 18px;
}
.accordion-body {
  border: 1px solid var(--border-strong);
  border-top: none;
  border-radius: 0;
  padding: var(--s-6);
}

/* --- Suggest cards (ported from the original page) --- */
.bench-card {
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--bg);
  padding: var(--s-6);
  margin-bottom: var(--s-6);
}
.bench-card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: var(--s-3);
}
.bench-card-title {
  font-size: var(--fs-md);
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
  margin-top: var(--s-2);
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
.bench-table .cell-question {
  max-width: 0;
  width: 100%;
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

.mono {
  font-family: var(--font-mono);
}

@media (max-width: 760px) {
  .cat-row {
    grid-template-columns: 1fr;
    gap: 6px;
  }
  .cat-val {
    justify-content: flex-start;
  }
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
