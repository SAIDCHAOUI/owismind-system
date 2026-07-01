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
function onBenchmarkChange(e) {
  bench.selectBenchmark(e.target.value)
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

function toggleRow(row) {
  const k = rowKey(row)
  const open = !expanded.value[k]
  expanded.value[k] = open
  // Lazily load the full detail (complete answer + generated SQL + result table) on first expand.
  if (open) bench.loadAttempt(row)
}

// --- On-demand attempt detail (full answer + generated SQL + result table) ---
// Reads the store's per-rowKey detail state ({ loading } | { data } | { error }).
function attemptState(row) {
  return bench.attemptDetail[rowKey(row)] || {}
}
function attemptSqlItems(row) {
  const st = attemptState(row)
  return st.data && Array.isArray(st.data.sql_items) ? st.data.sql_items : []
}
function itemRowCount(it) {
  if (it && it.row_count != null) return it.row_count
  return it && it.result && Array.isArray(it.result.rows) ? it.result.rows.length : 0
}
function itemHasTable(it) {
  const res = it && it.result
  return !!(res && Array.isArray(res.columns) && res.columns.length && Array.isArray(res.rows) && res.rows.length)
}
function cellText(cell) {
  return cell == null ? '' : String(cell)
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
// Localized date-time for a backend timestamp; falls back to the raw value.
function fmtTimestamp(stamp) {
  if (!stamp) return ''
  try {
    const d = new Date(stamp)
    if (!Number.isNaN(d.getTime())) return d.toLocaleString(locale.value)
  } catch (e) {
    /* fall through to the raw value */
  }
  return String(stamp)
}
// Benchmark selector option label: the name, plus its last-run date when known.
function fmtBenchmarkOption(b) {
  if (!b) return ''
  const name = b.benchmark_name || b.benchmark_id || ''
  const when = fmtTimestamp(b.last_run_timestamp)
  return when ? name + ' (' + when + ')' : String(name)
}
function catWidth(cat) {
  return pctFromAccuracy(cat && cat.accuracy) + '%'
}
function expectedText(row) {
  if (!row || !row.expected_value) return ''
  const ty = row.expected_value_type ? ' (' + row.expected_value_type + ')' : ''
  return String(row.expected_value) + ty
}

// --- LAB results parity helpers (verdict pill / mode badge / meter widths) ---
// Confidence band -> hero verdict pill class (good/mid/bad), like the LAB results hero.
function bandPill() {
  const b = String((kpis.value && kpis.value.band) || '').toLowerCase()
  if (b === 'high') return 'good'
  if (b === 'medium') return 'mid'
  if (b === 'low') return 'bad'
  return 'plaus'
}
// Mode name -> badge class (Smart green, Pro orange, Claude red, anything else standard grey).
function modeClass(mode) {
  const m = String(mode || '').toLowerCase()
  if (m === 'smart') return 'mode-smart'
  if (m === 'pro') return 'mode-pro'
  if (m === 'claude') return 'mode-claude'
  return 'mode-default'
}
// Mode name -> dot color token expression (used via :style, never an SVG/HTML color attribute).
function modeColor(mode) {
  const m = String(mode || '').toLowerCase()
  if (m === 'smart') return 'var(--success)'
  if (m === 'pro') return 'var(--orange)'
  if (m === 'claude') return 'var(--danger)'
  return 'var(--text-3)'
}
// Accuracy fraction -> meter bar width.
function meterWidth(acc) {
  return pctFromAccuracy(acc) + '%'
}
// Per-question result pill kind, from the EFFECTIVE verdict: ok / bad / plaus.
function resultPillKind(row) {
  const k = verdictKind(row)
  if (k === 'correct') return 'ok'
  if (k === 'incorrect') return 'bad'
  return 'plaus'
}

// --- Evolution (attempt history) ---------------------------------------------
// The benchmark grows question-by-question over many runs; a re-run of a question
// yields a new attempt. The backend stamps each detail row with `delta` (the trend of
// the latest attempt vs the previous one): improved | regressed | same | first.
const EVOLUTION_KINDS = ['improved', 'regressed', 'same', 'first']
function evolutionKind(row) {
  const d = String((row && row.delta) || '').toLowerCase()
  return EVOLUTION_KINDS.indexOf(d) >= 0 ? d : ''
}
function evolutionLabel(row) {
  const k = evolutionKind(row)
  return k ? t('bench.evo.' + k) : ''
}
// Trend -> pill class (improved = good, regressed = bad, same/first = neutral).
function evolutionClass(row) {
  const k = evolutionKind(row)
  if (k === 'improved') return 'evo-up'
  if (k === 'regressed') return 'evo-down'
  return 'evo-flat'
}
// How many attempts this question has accumulated in the benchmark.
function attemptCount(row) {
  const n = Number(row && row.n_attempts)
  return Number.isFinite(n) && n > 0 ? n : 1
}
// The ordered attempt history (oldest -> newest), defensive against a missing array.
function attemptHistory(row) {
  return row && Array.isArray(row.attempts) ? row.attempts : []
}
// One attempt's verdict pill kind (ok / bad / plaus), folding any override.
function attemptPillKind(att) {
  if (!att || typeof att !== 'object') return 'plaus'
  if (att.correct === true) return 'ok'
  if (att.correct === false) return 'bad'
  const v = String(att.verdict || '').toLowerCase()
  if (v === 'correct') return 'ok'
  if (v === 'incorrect') return 'bad'
  return 'plaus'
}
function attemptVerdictLabel(att) {
  const k = attemptPillKind(att)
  if (k === 'ok') return t('bench.verdict.correct')
  if (k === 'bad') return t('bench.verdict.incorrect')
  return t('bench.verdict.unknown')
}
// The agent's actual tools for one row -> a readable list (or empty).
function actualToolsText(row) {
  const v = row && row.actual_tools
  if (Array.isArray(v)) return v.filter((x) => x != null && String(x).trim()).join(', ')
  return v != null ? String(v).trim() : ''
}
// Whether a row carries any reference-vs-produced material worth a block.
function hasRefVsActual(row) {
  if (!row) return false
  return !!(row.expected_sql || row.expected_tool || actualToolsText(row))
}

async function applyOverride(row, verdict) {
  const k = rowKey(row)
  if (bench.overrideBusyKey) return
  try {
    await bench.submitOverride(
      {
        agent: bench.consultAgentKey,
        // A benchmark spans many runs; the override targets the SPECIFIC attempt, whose
        // run_id is carried on the detail row itself (not a single results-level run_id).
        run_id: row.run_id || '',
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
  <PageShell fluid :eyebrow="t('bench.eyebrow')" :title="t('bench.page_title')" :desc="t('bench.page_desc')">
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

          <div v-if="results && results.benchmarks.length > 1" class="cp-field">
            <label class="bench-label" for="bench-benchmark">{{ t('bench.consult.benchmark_label') }}</label>
            <div class="select-wrap">
              <select
                id="bench-benchmark"
                class="bench-select-ctl"
                :value="bench.selectedBenchmarkId"
                @change="onBenchmarkChange"
              >
                <option v-for="b in results.benchmarks" :key="b.benchmark_id" :value="b.benchmark_id">
                  {{ fmtBenchmarkOption(b) }}
                </option>
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

          <!-- content (1fr) + reference aside (360px), like the LAB results webapp -->
          <div class="consult-body">
            <div class="consult-content">
              <!-- HERO: donut + verdict pill + note + meta -->
              <div class="hero">
                <div class="donut-wrap">
                  <svg class="donut" viewBox="0 0 120 120" role="img" :aria-label="centerText">
                    <circle class="donut-track" cx="60" cy="60" r="52" />
                    <circle class="donut-fill" cx="60" cy="60" r="52" :style="donutFillStyle" />
                  </svg>
                  <div class="donut-center">
                    <span class="donut-pct">{{ centerText }}</span>
                    <span class="donut-band">{{ t('bench.consult.correct_label') }}</span>
                  </div>
                </div>
                <div class="hero-body">
                  <p v-if="results.benchmark_name" class="hero-bench">
                    {{ t('bench.consult.benchmark_caption', [results.benchmark_name]) }}
                  </p>
                  <p class="hero-head">{{ t('bench.consult.hero', [kpis.n_correct, kpis.n_scored]) }}</p>
                  <span class="verdict" :class="bandPill()"><span class="sq" /><span>{{ bandLabel }}</span></span>
                  <p class="hero-note">{{ t('bench.consult.hero_note') }}</p>
                  <p class="hero-meta">{{ t('bench.consult.hero_meta', [kpis.n_questions, kpis.n_configs]) }}</p>
                </div>
              </div>

              <!-- KPI row (5 tiles, orange top border) -->
              <div class="kpis">
                <div class="kpi">
                  <span class="k-lab">{{ t('bench.kpi.accuracy') }}</span>
                  <span class="k-val">{{ centerText }}</span>
                </div>
                <div class="kpi">
                  <span class="k-lab">{{ t('bench.kpi.questions') }}</span>
                  <span class="k-val">{{ kpis.n_questions }}</span>
                </div>
                <div class="kpi">
                  <span class="k-lab">{{ t('bench.kpi.configs') }}</span>
                  <span class="k-val">{{ kpis.n_configs }}</span>
                </div>
                <div class="kpi">
                  <span class="k-lab">{{ t('bench.kpi.cost') }}</span>
                  <span class="k-val sm">{{ kpis.total_cost_str || formatMoney(kpis.total_cost, locale) }}</span>
                </div>
                <div class="kpi">
                  <span class="k-lab">{{ t('bench.kpi.needs_review') }}</span>
                  <span class="k-val" :class="{ flag: kpis.needs_review > 0 }">{{ kpis.needs_review }}</span>
                </div>
              </div>

          <!-- Per agent x mode: one performance card each -->
          <div v-if="results.configs.length" class="section">
            <div class="section-h"><h3>{{ t('bench.cfg.title') }}</h3></div>
            <div v-for="(c, i) in results.configs" :key="i" class="cfg-card">
              <div class="cfg-top">
                <span class="cfg-name">{{ c.agent_label || c.agent_key }}</span>
                <span class="mode-badge" :class="modeClass(c.mode)"><span class="dot" />{{ c.mode }}</span>
                <span class="cfg-q">{{ t('bench.cfg.questions_n', [c.n_questions]) }}</span>
              </div>
              <div class="meter-row">
                <span class="meter-lab">{{ t('bench.cfg.col_accuracy') }}</span>
                <span class="meter"><i :style="{ width: meterWidth(c.accuracy) }" /></span>
                <span class="meter-val">{{ pctText(c.accuracy_pct) }}</span>
              </div>
              <div class="submetrics">
                <div class="submetric">
                  <div class="sl">{{ t('bench.cfg.col_score') }}</div>
                  <div class="sv">{{ fmtScore(c.mean_score) }}</div>
                </div>
                <div class="submetric">
                  <div class="sl">{{ t('bench.cfg.col_latency') }}</div>
                  <div class="sv">{{ c.avg_latency_str || '-' }}</div>
                </div>
                <div class="submetric">
                  <div class="sl">{{ t('bench.cfg.col_cost') }}</div>
                  <div class="sv">{{ c.avg_cost_str || '-' }}</div>
                </div>
                <div class="submetric">
                  <div class="sl">{{ t('bench.cfg.col_review') }}</div>
                  <div class="sv" :class="{ bad: c.needs_review > 0 }">{{ c.needs_review }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- Accuracy by topic -->
          <div v-if="results.categories.length" class="section">
            <div class="section-h"><h3>{{ t('bench.cat.title') }}</h3></div>
            <div class="topic">
              <div class="topic-h">{{ t('bench.cat.title') }}</div>
              <div v-for="(cat, i) in results.categories" :key="i" class="topic-row">
                <div class="topic-agent">{{ cat.bucket || t('bench.cat.uncategorized') }}</div>
                <span class="meter"><i :style="{ width: meterWidth(cat.accuracy) }" /></span>
                <span class="meter-val">{{ pctText(cat.accuracy_pct) }}</span>
                <span class="tq">{{ t('bench.cat.count', [cat.n]) }}</span>
              </div>
            </div>
          </div>

          <!-- Question by question (results table + expandable evidence) -->
          <div v-if="results.detail.length" class="section">
            <div class="section-h"><h3>{{ t('bench.detail.title') }}</h3></div>
            <p v-if="isAdmin" class="detail-admin-note">
              <Icon name="info" />{{ t('bench.review.reset_note') }}
            </p>
            <table class="rtable">
              <thead>
                <tr>
                  <th>{{ t('bench.detail.col_question') }}</th>
                  <th>{{ t('bench.detail.col_agent') }}</th>
                  <th>{{ t('bench.detail.col_result') }}</th>
                  <th class="num">{{ t('bench.detail.col_score') }}</th>
                </tr>
              </thead>
              <tbody>
                <template v-for="row in results.detail" :key="rowKey(row)">
                  <tr>
                    <td data-l="Question">
                      <div class="q-main">{{ row.question }}</div>
                      <div class="q-id">{{ row.question_id }}</div>
                      <button type="button" class="show-details" @click="toggleRow(row)">
                        <Icon :name="expanded[rowKey(row)] ? 'chevronUp' : 'chevronDown'" />
                        {{ expanded[rowKey(row)] ? t('bench.detail.hide') : t('bench.detail.show') }}
                      </button>
                    </td>
                    <td data-l="Agent">
                      <span class="cfg-cell">
                        <span class="dot" :style="{ background: modeColor(row.mode) }" />
                        {{ row.agent_label || row.agent_key }} . {{ row.mode }}
                      </span>
                    </td>
                    <td data-l="Result">
                      <span class="result-pill" :class="'result-' + resultPillKind(row)"><span class="sq" />{{ verdictLabel(row) }}</span>
                      <span v-if="row.overridden" class="v-over">{{ t('bench.verdict.overridden') }}</span>
                      <span v-if="evolutionKind(row)" class="evo-badge" :class="evolutionClass(row)">{{ evolutionLabel(row) }}</span>
                      <span v-if="attemptCount(row) > 1" class="attempt-count">{{ t('bench.evo.attempts_n', [attemptCount(row)]) }}</span>
                    </td>
                    <td class="num" data-l="Score">
                      <span class="score">{{ fmtScore(row.judge_score) }}<small>/ 5</small></span>
                    </td>
                  </tr>
                  <tr v-if="expanded[rowKey(row)]" class="detail-row">
                    <td colspan="4">
                      <div class="detail">
                        <div class="d-full">
                          <template v-if="row.category">
                            <dt>{{ t('bench.detail.col_category') }}</dt>
                            <dd>{{ row.category }}</dd>
                          </template>
                          <template v-if="row.expected_value">
                            <dt>{{ t('bench.detail.expected') }}</dt>
                            <dd class="mono">{{ expectedText(row) }}</dd>
                          </template>
                          <template v-if="row.notes">
                            <dt>{{ t('bench.detail.notes') }}</dt>
                            <dd>{{ row.notes }}</dd>
                          </template>
                          <template v-if="row.reviewed_by">
                            <dt>{{ t('bench.detail.reviewed') }}</dt>
                            <dd>{{ t('bench.review.reviewed_by', [row.reviewed_by, fmtDate(row.reviewed_at)]) }}</dd>
                          </template>
                        </div>
                        <div class="answers">
                          <div class="ans-box expected">
                            <div class="ans-l">{{ t('bench.detail.reference') }}</div>
                            <div class="ans-t">{{ row.reference_answer || '-' }}</div>
                          </div>
                          <div class="ans-box agent">
                            <div class="ans-l">{{ t('bench.detail.answer') }}</div>
                            <div class="ans-t">{{ row.answer_preview || '-' }}</div>
                          </div>
                        </div>
                        <p v-if="row.judge_comment" class="judge-note">
                          <b>{{ t('bench.detail.judge_comment') }} : </b>{{ row.judge_comment }}
                        </p>

                        <!-- On-demand full evidence: the COMPLETE agent answer + the SQL the agent
                             actually generated + each query's captured result table (loaded on expand,
                             one row at a time). Shows WHY a verdict is right or wrong, for good or bad. -->
                        <div class="agent-ev">
                          <div class="agent-ev-h">{{ t('bench.ev.title') }}</div>
                          <p v-if="attemptState(row).error" class="ev-msg ev-err">{{ t('bench.ev.error') }}</p>
                          <p v-else-if="!attemptState(row).data" class="ev-msg">{{ t('bench.ev.loading') }}</p>
                          <p v-else-if="!attemptState(row).data.found" class="ev-msg">{{ t('bench.ev.empty') }}</p>
                          <template v-else>
                            <div class="ev-answer">
                              <div class="ev-l">{{ t('bench.ev.answer') }}</div>
                              <pre class="ev-pre">{{ attemptState(row).data.answer_text || '-' }}</pre>
                            </div>
                            <template v-if="attemptSqlItems(row).length">
                              <div class="ev-l ev-sqlh">{{ t('bench.ev.sql') }}</div>
                              <div v-for="(it, i) in attemptSqlItems(row)" :key="i" class="ev-item">
                                <div class="ev-item-h">
                                  <span class="ev-qn">{{ t('bench.ev.query', [i + 1]) }}</span>
                                  <span class="ev-badge" :class="it.success ? 'ev-ok' : 'ev-bad'">{{ it.success ? t('bench.ev.ok') : t('bench.ev.failed') }}</span>
                                  <span class="ev-rc">{{ t('bench.ev.rows', [itemRowCount(it)]) }}</span>
                                </div>
                                <pre v-if="it.sql" class="ev-sql">{{ it.sql }}</pre>
                                <div class="ev-data">
                                  <div class="ev-l">{{ t('bench.ev.data') }}</div>
                                  <div v-if="itemHasTable(it)" class="ev-twrap">
                                    <table class="ev-table">
                                      <thead>
                                        <tr><th v-for="(c, ci) in it.result.columns" :key="ci">{{ c }}</th></tr>
                                      </thead>
                                      <tbody>
                                        <tr v-for="(r2, ri) in it.result.rows" :key="ri">
                                          <td v-for="(cell, cj) in r2" :key="cj">{{ cellText(cell) }}</td>
                                        </tr>
                                      </tbody>
                                    </table>
                                  </div>
                                  <p v-else class="ev-msg">{{ t('bench.ev.no_data') }}</p>
                                  <p v-if="it.result && it.result.truncated" class="ev-msg ev-trunc">{{ t('bench.ev.truncated') }}</p>
                                </div>
                              </div>
                            </template>
                            <p v-else class="ev-msg">{{ t('bench.ev.no_sql') }}</p>
                          </template>
                        </div>

                        <!-- Reference (golden) vs what the agent actually produced. The
                             references are a soft signal to the judge, not a hard metric. -->
                        <div v-if="hasRefVsActual(row)" class="refblock">
                          <div class="refblock-h">{{ t('bench.refprod.title') }}</div>
                          <div class="refprod">
                            <div class="rp-col">
                              <div class="rp-l">{{ t('bench.refprod.reference_sql') }}</div>
                              <pre v-if="row.expected_sql" class="rp-code">{{ row.expected_sql }}</pre>
                              <div v-else class="rp-empty">{{ t('bench.refprod.none') }}</div>
                            </div>
                            <div class="rp-col">
                              <div class="rp-l">{{ t('bench.refprod.suggested_tool') }}</div>
                              <div v-if="row.expected_tool" class="rp-tool mono">{{ row.expected_tool }}</div>
                              <div v-else class="rp-empty">{{ t('bench.refprod.none') }}</div>
                              <div class="rp-l rp-l--mt">{{ t('bench.refprod.tools_used') }}</div>
                              <div v-if="actualToolsText(row)" class="rp-tool mono">{{ actualToolsText(row) }}</div>
                              <div v-else class="rp-empty">{{ t('bench.refprod.none') }}</div>
                            </div>
                          </div>
                        </div>

                        <!-- Per-question evolution: the attempt history over the runs that
                             contributed to this benchmark (oldest first). -->
                        <div v-if="attemptCount(row) > 1 && attemptHistory(row).length" class="refblock">
                          <div class="refblock-h">
                            {{ t('bench.evo.history_title') }}
                            <span v-if="evolutionKind(row)" class="evo-badge" :class="evolutionClass(row)">{{ evolutionLabel(row) }}</span>
                          </div>
                          <ol class="attempts">
                            <li v-for="(att, ai) in attemptHistory(row)" :key="ai" class="attempt">
                              <span class="att-no">{{ t('bench.evo.attempt_n', [att.attempt_no != null ? att.attempt_no : ai + 1]) }}</span>
                              <span class="att-pill" :class="'result-' + attemptPillKind(att)"><span class="sq" />{{ attemptVerdictLabel(att) }}</span>
                              <span class="att-score">{{ fmtScore(att.judge_score) }}<small>/ 5</small></span>
                              <span v-if="att.overridden" class="v-over">{{ t('bench.verdict.overridden') }}</span>
                              <span class="att-when mono">{{ fmtTimestamp(att.run_timestamp) }}</span>
                            </li>
                          </ol>
                        </div>

                        <!-- Admin override controls -->
                        <div v-if="isAdmin" class="override">
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
                      </div>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
            </div>

            <!-- Reference aside (how it is measured + legends) -->
            <aside class="consult-aside">
              <div class="ref-block">
                <p class="ref-h">{{ t('bench.ref.measure_h') }}</p>
                <p class="ref-p">{{ t('bench.ref.measure_p') }}</p>
              </div>
              <div class="ref-block">
                <p class="ref-h">{{ t('bench.ref.score_h') }}</p>
                <dl class="ref-dl">
                  <div class="r"><dt>{{ t('bench.ref.judge_t') }}</dt><dd>{{ t('bench.ref.judge_d') }}</dd></div>
                  <div class="r"><dt>{{ t('bench.ref.dc_t') }}</dt><dd>{{ t('bench.ref.dc_d') }}</dd></div>
                </dl>
              </div>
              <div class="ref-block">
                <p class="ref-h">{{ t('bench.ref.modes_h') }}</p>
                <p class="ref-p">{{ t('bench.ref.modes_p') }}</p>
                <div class="legend">
                  <div class="l"><span class="dot" style="background:var(--success)" />Smart</div>
                  <div class="l"><span class="dot" style="background:var(--orange)" />Pro</div>
                  <div class="l"><span class="dot" style="background:var(--danger)" />Claude</div>
                  <div class="l"><span class="dot" style="background:var(--text-3)" />Standard</div>
                </div>
                <p class="ref-p" style="margin-top:12px">{{ t('bench.ref.modes_std') }}</p>
              </div>
            </aside>
          </div>
        </template>
      </template>
    </section>

    <!-- ============================ SUGGEST ============================ -->
    <section class="bench-section bench-section--narrow">
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
/* The page is full-width (fluid PageShell) so the consultation mirrors the LAB
   results webapp. The suggest forms below stay a readable left-aligned column. */
.bench-section--narrow {
  max-width: 880px;
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

/* --- Content + reference aside (LAB results two-column) --- */
.consult-body {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
}
.consult-content {
  flex: 1;
  min-width: 0;
}
.consult-aside {
  width: 360px;
  flex: 0 0 360px;
  border-left: 1px solid var(--border);
  padding-left: var(--s-6);
  margin-left: var(--s-6);
}

/* sections inside the consultation content */
.section {
  margin-top: var(--s-7);
}
.section:first-child {
  margin-top: 0;
}
.section-h {
  margin-bottom: var(--s-4);
}
.section-h h3 {
  font-size: var(--fs-lg);
  font-weight: var(--fw-heavy);
  color: var(--text);
  margin: 0;
}

/* --- Hero: donut + verdict + note + meta --- */
.hero {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--s-7);
  align-items: center;
  padding: var(--s-6);
  border: 1px solid var(--border-strong);
  border-top: 3px solid var(--orange);
  background: var(--bg);
  margin-bottom: var(--s-5);
}
.donut-wrap {
  position: relative;
  width: 160px;
  height: 160px;
  flex-shrink: 0;
}
.donut {
  width: 160px;
  height: 160px;
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
  font-size: 34px;
  font-weight: var(--fw-heavy);
  font-family: var(--font-mono);
  color: var(--text);
  line-height: 1;
}
.donut-band {
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-2);
  margin-top: 8px;
}
.hero-body {
  min-width: 0;
}
.hero-head {
  font-size: var(--fs-2xl);
  font-weight: var(--fw-heavy);
  color: var(--text);
  line-height: 1.2;
  margin: 0 0 var(--s-4);
}
.verdict {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  border: 1.5px solid;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.verdict .sq {
  width: 11px;
  height: 11px;
}
.verdict.good {
  border-color: var(--success);
  color: var(--success);
}
.verdict.good .sq {
  background: var(--success);
}
.verdict.mid {
  border-color: var(--orange);
  color: var(--orange-text);
}
.verdict.mid .sq {
  background: var(--orange);
}
.verdict.bad {
  border-color: var(--danger);
  color: var(--danger);
}
.verdict.bad .sq {
  background: var(--danger);
}
.verdict.plaus {
  border-color: var(--text-3);
  color: var(--text-2);
}
.verdict.plaus .sq {
  background: var(--text-3);
}
.hero-note {
  color: var(--text);
  font-size: var(--fs-base);
  margin: var(--s-4) 0 6px;
}
.hero-meta {
  color: var(--text-3);
  font-size: var(--fs-sm);
  font-family: var(--font-mono);
  margin: 0;
}

/* --- KPI row (5 tiles, orange top border) --- */
.kpis {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: var(--s-4);
}
.kpi {
  border: 1px solid var(--border);
  border-top: 3px solid var(--orange);
  background: var(--bg);
  padding: 16px;
}
.kpi .k-lab {
  display: block;
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-2);
  margin-bottom: 12px;
}
.kpi .k-val {
  display: block;
  font-size: 26px;
  font-weight: var(--fw-heavy);
  font-family: var(--font-mono);
  color: var(--text);
  line-height: 1;
}
.kpi .k-val.sm {
  font-size: 20px;
}
.kpi .k-val.flag {
  color: var(--danger);
}

/* --- Configuration performance cards --- */
.cfg-card {
  border: 1px solid var(--border-strong);
  background: var(--bg);
  padding: var(--s-5) var(--s-6);
}
.cfg-card + .cfg-card {
  margin-top: var(--s-3);
}
.cfg-top {
  display: flex;
  align-items: center;
  gap: var(--s-4);
  flex-wrap: wrap;
  margin-bottom: var(--s-4);
}
.cfg-name {
  font-size: var(--fs-md);
  font-weight: var(--fw-heavy);
  color: var(--text);
}
.cfg-q {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--text-3);
  font-family: var(--font-mono);
}
.mode-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1.5px solid var(--border-strong);
  padding: 3px 9px;
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-2);
}
.mode-badge .dot {
  width: 9px;
  height: 9px;
  background: var(--text-3);
}
.mode-badge.mode-smart {
  border-color: var(--success);
  color: var(--success);
}
.mode-badge.mode-smart .dot {
  background: var(--success);
}
.mode-badge.mode-pro {
  border-color: var(--orange);
  color: var(--orange-text);
}
.mode-badge.mode-pro .dot {
  background: var(--orange);
}
.mode-badge.mode-claude {
  border-color: var(--danger);
  color: var(--danger);
}
.mode-badge.mode-claude .dot {
  background: var(--danger);
}
.mode-badge.mode-default {
  border-color: var(--border-strong);
  color: var(--text-2);
}

/* meter bar (shared by cfg cards + topic rows) */
.meter-row {
  display: flex;
  align-items: center;
  gap: var(--s-4);
}
.meter-lab {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-2);
  white-space: nowrap;
  width: 110px;
  flex: 0 0 110px;
}
.meter {
  flex: 1;
  height: 12px;
  background: var(--surface-2);
  overflow: hidden;
}
.meter i {
  display: block;
  height: 100%;
  background: var(--orange);
}
.meter-val {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  white-space: nowrap;
  width: 54px;
  text-align: right;
  color: var(--text);
}

/* submetric mini-cards */
.submetrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--s-3);
  margin-top: var(--s-4);
}
.submetric {
  border: 1px solid var(--border);
  background: var(--surface);
  padding: 12px 14px;
}
.submetric .sl {
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-2);
  margin-bottom: 8px;
}
.submetric .sv {
  font-size: var(--fs-lg);
  font-weight: var(--fw-heavy);
  font-family: var(--font-mono);
  color: var(--text);
}
.submetric .sv.bad {
  color: var(--danger);
}

/* --- Topic (accuracy by category) --- */
.topic {
  border: 1px solid var(--border-strong);
  background: var(--bg);
}
.topic-h {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text);
  padding: 14px var(--s-5);
  border-bottom: 1px solid var(--border);
}
.topic-row {
  display: flex;
  align-items: center;
  gap: var(--s-4);
  padding: 13px var(--s-5);
  border-bottom: 1px solid var(--border);
}
.topic-row:last-child {
  border-bottom: none;
}
.topic-agent {
  width: 200px;
  flex: 0 0 200px;
  font-size: var(--fs-sm);
  font-weight: var(--fw-semibold);
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.topic-row .meter-val {
  width: 48px;
}
.topic-row .tq {
  font-size: var(--fs-xs);
  color: var(--text-3);
  font-family: var(--font-mono);
  width: 90px;
  text-align: right;
  flex: 0 0 90px;
}

/* --- Results table (question by question) --- */
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
.rtable {
  width: 100%;
  border-collapse: collapse;
  background: var(--bg);
  border: 1px solid var(--border-strong);
}
.rtable thead th {
  text-align: left;
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-2);
  padding: 12px 14px;
  background: var(--surface);
  border-bottom: 1px solid var(--border-strong);
}
.rtable thead th.num {
  text-align: right;
}
.rtable td {
  padding: 14px;
  border-bottom: 1px solid var(--border);
  font-size: var(--fs-sm);
  vertical-align: top;
  color: var(--text-2);
}
.rtable tbody tr:last-child td {
  border-bottom: none;
}
.rtable td.num {
  text-align: right;
  font-family: var(--font-mono);
  white-space: nowrap;
}
.q-main {
  font-weight: var(--fw-bold);
  color: var(--text);
}
.q-id {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
  margin-top: 4px;
}
.cfg-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-sm);
  color: var(--text);
}
.cfg-cell .dot {
  width: 10px;
  height: 10px;
  flex: 0 0 10px;
}
.result-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1.5px solid;
  padding: 4px 9px;
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
}
.result-pill .sq {
  width: 10px;
  height: 10px;
}
.result-ok {
  border-color: var(--success);
  color: var(--success);
}
.result-ok .sq {
  background: var(--success);
}
.result-bad {
  border-color: var(--danger);
  color: var(--danger);
}
.result-bad .sq {
  background: var(--danger);
}
.result-plaus {
  border-color: var(--text-3);
  color: var(--text-2);
}
.result-plaus .sq {
  background: var(--text-3);
}
.score {
  font-family: var(--font-mono);
  font-weight: var(--fw-bold);
  font-size: var(--fs-md);
  color: var(--text);
}
.score small {
  font-size: 10px;
  color: var(--text-3);
  margin-left: 2px;
}
.show-details {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  padding: 0;
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
  color: var(--text-2);
  background: none;
  border: none;
  cursor: pointer;
}
.show-details:hover {
  color: var(--orange-text);
}
.show-details :deep(.ui-icon) {
  width: 13px;
  height: 13px;
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

/* --- Expanded detail panel (reference / agent answer / judge note) --- */
.detail-row td {
  background: var(--surface);
  padding: var(--s-5);
}
.detail {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
}
.d-full {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 8px 20px;
  margin: 0;
}
.d-full dt {
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-3);
}
.d-full dd {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--text);
  line-height: 1.5;
  overflow-wrap: anywhere;
}
.answers {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s-5);
}
.ans-box {
  padding-left: 14px;
  border-left: 3px solid var(--border-strong);
}
.ans-box.expected {
  border-left-color: var(--success);
}
.ans-box.agent {
  border-left-color: var(--danger);
}
.ans-box .ans-l {
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-2);
  margin-bottom: 8px;
}
.ans-box .ans-t {
  font-size: var(--fs-sm);
  color: var(--text);
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 220px;
  overflow-y: auto;
}
.judge-note {
  font-size: var(--fs-sm);
  color: var(--text);
  margin: 0;
}
.judge-note b {
  font-weight: var(--fw-bold);
}

/* --- On-demand full evidence: complete answer + generated SQL + result table --- */
.agent-ev {
  border: 1px solid var(--border);
  background: var(--bg);
  padding: var(--s-4) var(--s-5);
}
.agent-ev-h {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--orange-text);
  margin-bottom: var(--s-4);
}
.ev-l {
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-3);
  margin-bottom: 6px;
}
.ev-answer {
  margin-bottom: var(--s-4);
}
.ev-pre {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-left: 3px solid var(--text-3);
  background: var(--surface);
  font-size: var(--fs-sm);
  color: var(--text);
  line-height: 1.6;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 260px;
  overflow-y: auto;
}
.ev-sqlh {
  margin-top: 2px;
}
.ev-item {
  border: 1px solid var(--border);
  background: var(--surface);
  margin-bottom: var(--s-3);
}
.ev-item-h {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg);
}
.ev-qn {
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-2);
}
.ev-badge {
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 2px 7px;
  border: 1px solid var(--border-strong);
  color: var(--text-2);
}
.ev-badge.ev-ok {
  border-color: var(--success);
  color: var(--success);
}
.ev-badge.ev-bad {
  border-color: var(--danger);
  color: var(--danger);
}
.ev-rc {
  margin-left: auto;
  font-size: var(--fs-xs);
  font-family: var(--font-mono);
  color: var(--text-3);
}
.ev-sql {
  margin: 0;
  padding: 10px 12px;
  border: none;
  border-left: 3px solid var(--orange);
  background: var(--surface);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--text);
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  overflow-x: auto;
}
.ev-data {
  padding: 10px 12px;
  border-top: 1px solid var(--border);
}
.ev-twrap {
  max-height: 320px;
  overflow: auto;
  border: 1px solid var(--border-strong);
}
.ev-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--bg);
  font-size: var(--fs-sm);
}
.ev-table th {
  position: sticky;
  top: 0;
  text-align: left;
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-3);
  padding: 7px 12px;
  background: var(--surface);
  border-bottom: 1px solid var(--border-strong);
  white-space: nowrap;
}
.ev-table td {
  padding: 6px 12px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  font-family: var(--font-mono);
  white-space: nowrap;
}
.ev-table tbody tr:last-child td {
  border-bottom: none;
}
.ev-msg {
  font-size: var(--fs-sm);
  color: var(--text-3);
  margin: 6px 0 0;
}
.ev-msg.ev-err {
  color: var(--danger);
}
.ev-msg.ev-trunc {
  margin-top: 8px;
  font-style: italic;
}

/* --- Benchmark name caption in the hero --- */
.hero-bench {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--orange-text);
  margin: 0 0 8px;
}

/* --- Evolution (delta badge + attempt history) --- */
.evo-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 2px 7px;
  border: 1px solid var(--border-strong);
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-2);
  vertical-align: middle;
}
.evo-badge.evo-up {
  border-color: var(--success);
  color: var(--success);
}
.evo-badge.evo-down {
  border-color: var(--danger);
  color: var(--danger);
}
.evo-badge.evo-flat {
  border-color: var(--border-strong);
  color: var(--text-3);
}
.attempt-count {
  display: inline-block;
  margin-left: 6px;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-3);
  vertical-align: middle;
}

/* shared block frame for ref-vs-produced + attempt history */
.refblock {
  border: 1px solid var(--border);
  background: var(--bg);
  padding: var(--s-4) var(--s-5);
}
.refblock-h {
  display: flex;
  align-items: center;
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-2);
  margin-bottom: var(--s-3);
}

/* reference SQL / suggested tool vs tools used */
.refprod {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s-5);
}
.rp-l {
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-3);
  margin-bottom: 6px;
}
.rp-l--mt {
  margin-top: var(--s-4);
}
.rp-code {
  margin: 0;
  padding: 10px 12px;
  border: 1px solid var(--border);
  background: var(--surface);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--text);
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 220px;
  overflow-y: auto;
}
.rp-tool {
  font-size: var(--fs-sm);
  color: var(--text);
  overflow-wrap: anywhere;
}
.rp-empty {
  font-size: var(--fs-sm);
  color: var(--text-3);
}

/* attempt history list */
.attempts {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}
.attempt {
  display: flex;
  align-items: center;
  gap: var(--s-4);
  flex-wrap: wrap;
}
.att-no {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-2);
  width: 96px;
  flex: 0 0 96px;
}
.att-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1.5px solid;
  padding: 3px 8px;
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
}
.att-pill .sq {
  width: 9px;
  height: 9px;
}
.att-score {
  font-family: var(--font-mono);
  font-weight: var(--fw-bold);
  font-size: var(--fs-sm);
  color: var(--text);
}
.att-score small {
  font-size: 10px;
  color: var(--text-3);
  margin-left: 2px;
}
.att-when {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--text-3);
}

@media (max-width: 760px) {
  .refprod {
    grid-template-columns: 1fr;
  }
  .att-when {
    margin-left: 0;
  }
}

/* --- Reference aside --- */
.ref-block + .ref-block {
  margin-top: var(--s-5);
  padding-top: var(--s-5);
  border-top: 1px solid var(--border);
}
.ref-h {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--orange-text);
  margin: 0 0 10px;
}
.ref-p {
  font-size: var(--fs-sm);
  color: var(--text-2);
  line-height: 1.6;
  margin: 0 0 10px;
}
.ref-dl {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 0;
}
.ref-dl .r {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.ref-dl dt {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text);
}
.ref-dl dd {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--text-2);
  line-height: 1.5;
}
.legend {
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.legend .l {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--fs-sm);
  font-weight: var(--fw-semibold);
  color: var(--text);
}
.legend .dot {
  width: 12px;
  height: 12px;
  flex: 0 0 12px;
}

/* suggest table cell truncation (kept for the my-suggestions table) */
.cell-question {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text);
}

/* --- consultation responsive (mirrors the LAB results breakpoints) --- */
@media (max-width: 1280px) {
  .kpis {
    grid-template-columns: repeat(3, 1fr);
  }
}
@media (max-width: 1080px) {
  .consult-aside {
    width: auto;
    flex: none;
    border-left: none;
    border-top: 1px solid var(--border);
    padding-left: 0;
    margin-left: 0;
    margin-top: var(--s-6);
    padding-top: var(--s-6);
  }
}
@media (max-width: 760px) {
  .hero {
    grid-template-columns: 1fr;
    justify-items: center;
    text-align: center;
  }
  .kpis {
    grid-template-columns: repeat(2, 1fr);
  }
  .submetrics {
    grid-template-columns: 1fr 1fr;
  }
  .answers {
    grid-template-columns: 1fr;
  }
  .topic-agent {
    width: auto;
    flex: 1;
  }
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
