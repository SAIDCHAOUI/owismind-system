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
  hasMultipleModes,
  heroVerdictKind,
  modeClass,
  modeColor,
  modeLabel,
  resultPillKind,
  rowAccentKind,
  meterWidth,
  catWidth,
  evolutionKind,
  evolutionClass,
  attemptCount,
  attemptHistory,
  attemptPillKind,
  actualToolsText,
  hasRefVsActual,
  expectedText,
  fmtScore,
  cellIsNumeric,
  formatCell,
} from '../composables/benchmarkResults.js'
import { PageShell, EmptyState } from '../components/pages'
import { Icon, Button, Tabs } from '../components/ui'

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

// Whether more than one mode is actually benchmarked. When false the whole mode
// apparatus (badges, aside legend, the "configurations" KPI) is noise and is hidden.
const multiMode = computed(() => hasMultipleModes(results.value))
// A single benchmark-capable agent needs no picker: show a static label instead.
const singleAgent = computed(() => benchmarkAgents.value.length === 1)
// Hero verdict pill kind (good / mid / bad / plaus) from the confidence band.
const heroPillKind = computed(() => heroVerdictKind(kpis.value && kpis.value.band))
// The KPI tiles, built so the "configurations" tile drops out in single-mode runs
// and the grid (auto-fit) simply reflows. Each tile is { key, label, value, flag? }.
const kpiTiles = computed(() => {
  const k = kpis.value
  if (!k) return []
  const tiles = [
    { key: 'accuracy', label: t('bench.kpi.accuracy'), value: centerText.value },
    { key: 'questions', label: t('bench.kpi.questions'), value: String(k.n_questions) },
  ]
  if (multiMode.value) {
    tiles.push({ key: 'configs', label: t('bench.kpi.configs'), value: String(k.n_configs) })
  }
  tiles.push({
    key: 'cost',
    label: t('bench.kpi.cost'),
    value: k.total_cost_str || formatMoney(k.total_cost, locale.value),
    small: true,
  })
  tiles.push({
    key: 'needs_review',
    label: t('bench.kpi.needs_review'),
    value: String(k.needs_review),
    flag: k.needs_review > 0,
  })
  return tiles
})

// --- Per-question review (expand state + active detail tab + override comments) ---
const expanded = ref({})
const comments = ref({})
// Active detail tab per row (keyed by rowKey, like `expanded`). Presentation state
// stays local to the view; the store only fetches / normalizes.
const activeTab = ref({})

// The available detail tabs for one row: full answer always, SQL & data always,
// reference only when there is reference material, history only for multi-attempt
// questions. Returns [{ key, label }] for Tabs.vue.
function tabItems(row) {
  const items = [
    { key: 'answer', label: t('bench.tab.answer') },
    { key: 'sql', label: t('bench.tab.sql') },
  ]
  if (hasRefVsActual(row)) items.push({ key: 'reference', label: t('bench.tab.reference') })
  if (attemptCount(row) > 1 && attemptHistory(row).length) {
    items.push({ key: 'history', label: t('bench.tab.history') })
  }
  return items
}
function currentTab(row) {
  return activeTab.value[rowKey(row)] || 'answer'
}
function setTab(row, key) {
  activeTab.value[rowKey(row)] = key
}

function toggleRow(row) {
  const k = rowKey(row)
  const open = !expanded.value[k]
  expanded.value[k] = open
  // Default the detail to the full-answer tab on first open.
  if (open) {
    if (!activeTab.value[k]) activeTab.value[k] = 'answer'
    // Lazily load the full detail (complete answer + generated SQL + result table).
    bench.loadAttempt(row)
  }
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
// Format one captured result cell (numbers grouped by locale, text left literal).
function fmtCell(cell) {
  return formatCell(cell, locale.value)
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

// Evolution + attempt labels (need i18n; the pure kinds come from the module).
function evolutionLabel(row) {
  const k = evolutionKind(row)
  return k ? t('bench.evo.' + k) : ''
}
function attemptVerdictLabel(att) {
  const k = attemptPillKind(att)
  if (k === 'ok') return t('bench.verdict.correct')
  if (k === 'bad') return t('bench.verdict.incorrect')
  return t('bench.verdict.unknown')
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
            <!-- A single benchmark-capable agent needs no picker: show a static label. -->
            <div v-if="singleAgent" class="cp-static">{{ benchmarkAgents[0].label }}</div>
            <div v-else class="select-wrap">
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

        <!-- States: flat charter skeleton while loading, framed cards otherwise -->
        <div
          v-if="bench.resultsLoading && !results"
          class="skeleton"
          role="status"
          :aria-label="t('bench.consult.loading')"
        >
          <div class="sk-band">
            <div class="sk-box sk-donut" />
            <div class="sk-kpis">
              <div v-for="n in 4" :key="n" class="sk-box sk-kpi" />
            </div>
          </div>
          <div class="sk-list">
            <div v-for="n in 6" :key="n" class="sk-box sk-row" />
          </div>
        </div>
        <div v-else-if="!bench.resultsConfigured" class="consult-card-state">
          <Icon name="info" />
          <span>{{ t('bench.consult.not_configured') }}</span>
        </div>
        <div v-else-if="bench.resultsError" class="consult-card-state">
          <Icon name="alert" />
          <span>{{ t('bench.consult.load_error') }}</span>
        </div>
        <div v-else-if="!hasResults" class="consult-card-state">
          <Icon name="chart" />
          <span>{{ t('bench.consult.no_results') }}</span>
        </div>

        <!-- Results -->
        <template v-else-if="results && kpis">
          <div v-if="bench.resultsReadError" class="consult-note consult-note--soft">
            <Icon name="info" />
            <span>{{ t('bench.consult.read_error') }}</span>
          </div>

          <!-- content (1fr) + reference aside (360px), like the LAB results webapp -->
          <div class="consult-body">
            <div class="consult-content">
              <!-- TOP BAND: hero (donut + verdict) left, KPI tiles right, one row on
                   wide screens so the questions surface sooner. -->
              <div class="top-band">
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
                    <span class="verdict" :class="heroPillKind"><span class="sq" /><span>{{ bandLabel }}</span></span>
                    <p class="hero-note">{{ t('bench.consult.hero_note') }}</p>
                  </div>
                </div>

                <!-- KPI tiles (auto-fit; the "configurations" tile drops in single-mode). -->
                <div class="kpis">
                  <div v-for="tile in kpiTiles" :key="tile.key" class="kpi">
                    <span class="k-lab">{{ tile.label }}</span>
                    <span class="k-val" :class="{ sm: tile.small, flag: tile.flag }">{{ tile.value }}</span>
                  </div>
                </div>
              </div>

          <!-- Per agent x mode: one performance card each -->
          <div v-if="results.configs.length" class="section">
            <div class="section-h"><h3>{{ t('bench.cfg.title') }}</h3></div>
            <div v-for="(c, i) in results.configs" :key="i" class="cfg-card">
              <div class="cfg-top">
                <span class="cfg-name">{{ c.agent_label || c.agent_key }}</span>
                <span v-if="multiMode" class="mode-badge" :class="modeClass(c.mode)"><span class="dot" />{{ modeLabel(c.mode) }}</span>
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
            <!-- Scannable question list: one framed card-line per question, a left rail
                 accent when incorrect (danger) or awaiting review (warn), the detail
                 panel expands inline with lazy-loaded tabs. Backend sort is preserved
                 (needs_review, then incorrect, then id). -->
            <ul class="qlist">
              <li
                v-for="row in results.detail"
                :key="rowKey(row)"
                class="qitem"
                :class="'accent-' + (rowAccentKind(row) || 'none')"
              >
                <button
                  type="button"
                  class="qhead"
                  :aria-expanded="!!expanded[rowKey(row)]"
                  @click="toggleRow(row)"
                >
                  <span class="qmain">
                    <span class="qtext">{{ row.question }}</span>
                    <span class="qchips">
                      <span v-if="row.category" class="chip">{{ row.category }}</span>
                      <span v-if="multiMode" class="chip chip-mode" :class="modeClass(row.mode)">
                        <span class="dot" :style="{ background: modeColor(row.mode) }" />{{ modeLabel(row.mode) }}
                      </span>
                      <span v-if="attemptCount(row) > 1" class="chip">{{ t('bench.evo.attempts_n', [attemptCount(row)]) }}</span>
                      <span v-if="evolutionKind(row)" class="chip evo-badge" :class="evolutionClass(row)">{{ evolutionLabel(row) }}</span>
                    </span>
                  </span>
                  <span class="qside">
                    <span v-if="row.needs_review" class="flag-review"><span class="sq" />{{ t('bench.detail.flag_review') }}</span>
                    <span class="result-pill" :class="'result-' + resultPillKind(row)"><span class="sq" />{{ verdictLabel(row) }}</span>
                    <span v-if="row.overridden" class="v-over">{{ t('bench.verdict.overridden') }}</span>
                    <span class="score">{{ fmtScore(row.judge_score) }}<small>/ 5</small></span>
                    <Icon class="qchev" :name="expanded[rowKey(row)] ? 'chevronUp' : 'chevronDown'" />
                  </span>
                </button>

                <div v-if="expanded[rowKey(row)]" class="qdetail">
                  <!-- Compact meta banner (always visible: category, key value, notes,
                       judge verdict + comment, human override). -->
                  <dl class="meta-banner">
                    <div class="mb"><dt>{{ t('bench.detail.col_question') }}</dt><dd class="mono">{{ row.question_id }}</dd></div>
                    <div v-if="row.category" class="mb"><dt>{{ t('bench.detail.col_category') }}</dt><dd>{{ row.category }}</dd></div>
                    <div v-if="expectedText(row)" class="mb"><dt>{{ t('bench.detail.expected') }}</dt><dd class="mono">{{ expectedText(row) }}</dd></div>
                    <div v-if="row.notes" class="mb mb-wide"><dt>{{ t('bench.detail.notes') }}</dt><dd>{{ row.notes }}</dd></div>
                    <div v-if="row.judge_comment" class="mb mb-wide"><dt>{{ t('bench.detail.judge_label') }}</dt><dd>{{ row.judge_comment }}</dd></div>
                    <div v-if="row.reviewed_by" class="mb mb-wide"><dt>{{ t('bench.detail.reviewed') }}</dt><dd>{{ t('bench.review.reviewed_by', [row.reviewed_by, fmtDate(row.reviewed_at)]) }}</dd></div>
                  </dl>

                  <!-- Expected vs produced answer (light previews, side by side). -->
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

                  <!-- Tabs (shared Tabs.vue, styled locally): full answer / SQL & data /
                       reference / history. The heavy answer + SQL load lazily on expand;
                       loading / error / empty states live inside the tab body. -->
                  <div class="detail-tabs">
                    <Tabs
                      :items="tabItems(row)"
                      :model-value="currentTab(row)"
                      @update:model-value="(k) => setTab(row, k)"
                    />
                    <div class="tab-panel">
                      <!-- Full answer -->
                      <template v-if="currentTab(row) === 'answer'">
                        <p v-if="attemptState(row).error" class="ev-msg ev-err">{{ t('bench.ev.error') }}</p>
                        <p v-else-if="!attemptState(row).data" class="ev-msg">{{ t('bench.ev.loading') }}</p>
                        <p v-else-if="!attemptState(row).data.found" class="ev-msg">{{ t('bench.ev.empty') }}</p>
                        <pre v-else class="ev-pre">{{ attemptState(row).data.answer_text || '-' }}</pre>
                      </template>

                      <!-- SQL & data -->
                      <template v-else-if="currentTab(row) === 'sql'">
                        <p v-if="attemptState(row).error" class="ev-msg ev-err">{{ t('bench.ev.error') }}</p>
                        <p v-else-if="!attemptState(row).data" class="ev-msg">{{ t('bench.ev.loading') }}</p>
                        <p v-else-if="!attemptState(row).data.found" class="ev-msg">{{ t('bench.ev.empty') }}</p>
                        <template v-else-if="attemptSqlItems(row).length">
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
                                      <td v-for="(cell, cj) in r2" :key="cj" :class="{ num: cellIsNumeric(cell) }">{{ fmtCell(cell) }}</td>
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

                      <!-- Reference (golden SQL / suggested tool vs tools actually used) -->
                      <template v-else-if="currentTab(row) === 'reference'">
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
                        <p class="rp-note">{{ t('bench.refprod.note') }}</p>
                      </template>

                      <!-- History (attempt trail over the runs, oldest first). -->
                      <template v-else-if="currentTab(row) === 'history'">
                        <div class="hist-wrap">
                          <table class="hist-table">
                            <thead>
                              <tr>
                                <th>{{ t('bench.hist.col_attempt') }}</th>
                                <th>{{ t('bench.hist.col_date') }}</th>
                                <th>{{ t('bench.hist.col_result') }}</th>
                                <th class="num">{{ t('bench.hist.col_score') }}</th>
                              </tr>
                            </thead>
                            <tbody>
                              <tr v-for="(att, ai) in attemptHistory(row)" :key="ai">
                                <td class="mono">{{ att.attempt_no != null ? att.attempt_no : ai + 1 }}</td>
                                <td class="mono">{{ fmtTimestamp(att.run_timestamp) }}</td>
                                <td class="hist-result">
                                  <span class="att-pill" :class="'result-' + attemptPillKind(att)"><span class="sq" />{{ attemptVerdictLabel(att) }}</span>
                                  <span v-if="att.overridden" class="v-over">{{ t('bench.verdict.overridden') }}</span>
                                  <span v-if="ai === attemptHistory(row).length - 1" class="latest-tag">{{ t('bench.hist.latest') }}</span>
                                </td>
                                <td class="num"><span class="score">{{ fmtScore(att.judge_score) }}<small>/ 5</small></span></td>
                              </tr>
                            </tbody>
                          </table>
                        </div>
                      </template>
                    </div>
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
              </li>
            </ul>
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
              <!-- The modes legend is contextual: only shown when several modes ran. -->
              <div v-if="multiMode" class="ref-block">
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
/* Single-agent static label (replaces the agent picker when only one exists). */
.cp-static {
  padding: 11px 14px;
  border: 1px solid var(--border);
  background: var(--surface);
  font-size: 14px;
  font-weight: var(--fw-bold);
  color: var(--text);
}
/* Empty / not-configured / error, presented as a framed charter card. */
.consult-card-state {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 16px 18px;
  border: 1px solid var(--border-strong);
  background: var(--bg);
  font-size: var(--fs-sm);
  color: var(--text-2);
  margin-bottom: var(--s-5);
}
.consult-card-state :deep(.ui-icon) {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  color: var(--text-3);
}

/* Loading skeleton: flat charter rectangles, a discreet opacity pulse (disabled
   under prefers-reduced-motion). */
.skeleton {
  margin-bottom: var(--s-5);
}
.sk-band {
  display: flex;
  gap: var(--s-5);
  flex-wrap: wrap;
  margin-bottom: var(--s-5);
}
.sk-kpis {
  flex: 1;
  min-width: 240px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--s-4);
}
.sk-list {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}
.sk-box {
  background: var(--surface-2);
  border: 1px solid var(--border);
  animation: sk-pulse 1.2s ease-in-out infinite;
}
.sk-donut {
  width: 200px;
  height: 132px;
  flex: 0 0 200px;
}
.sk-kpi {
  height: 92px;
  border-top: 3px solid var(--border-strong);
}
.sk-row {
  height: 56px;
}
@keyframes sk-pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.55;
  }
}
@media (prefers-reduced-motion: reduce) {
  .sk-box {
    animation: none;
  }
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
  width: 320px;
  flex: 0 0 320px;
  border-left: 1px solid var(--border);
  padding-left: var(--s-6);
  margin-left: var(--s-6);
  /* Stay useful while the question list scrolls. */
  position: sticky;
  top: var(--s-5);
  align-self: flex-start;
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

/* --- Top band: hero (left) + KPI tiles (right) on one horizontal row --- */
.top-band {
  display: grid;
  grid-template-columns: minmax(340px, 1.1fr) 2fr;
  gap: var(--s-5);
  align-items: stretch;
  margin-bottom: var(--s-6);
}

/* --- Hero: donut + verdict + note --- */
.hero {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--s-6);
  align-items: center;
  padding: var(--s-6);
  border: 1px solid var(--border-strong);
  border-top: 3px solid var(--orange);
  background: var(--bg);
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
  color: var(--text-2);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin: var(--s-4) 0 0;
}

/* --- KPI tiles (auto-fit; the "configurations" tile drops in single-mode) --- */
.kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--s-4);
  align-content: start;
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
/* Question list: framed card-lines, left rail accent by effective verdict. */
.qlist {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--border-strong);
  background: var(--bg);
}
.qitem {
  border-bottom: 1px solid var(--border);
  border-left: 3px solid transparent;
}
.qitem:last-child {
  border-bottom: none;
}
.qitem.accent-danger {
  border-left-color: var(--danger);
}
.qitem.accent-warn {
  border-left-color: var(--warn);
}
.qhead {
  width: 100%;
  display: flex;
  /* The side cluster (pills, score) never shrinks: let it wrap under the question
     instead of crushing the title when the content column is narrow. */
  flex-wrap: wrap;
  align-items: center;
  gap: var(--s-5);
  padding: 13px var(--s-5);
  background: none;
  border: none;
  text-align: left;
  cursor: pointer;
  transition: background var(--dur) var(--ease);
}
.qhead:hover {
  background: var(--surface-hover);
}
.qmain {
  flex: 1;
  min-width: min(240px, 100%);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.qtext {
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  color: var(--text);
  line-height: 1.4;
  /* Two lines max, ellipsed. */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.qchips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px 8px;
  border: 1px solid var(--border-strong);
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-2);
  white-space: nowrap;
}
.chip .dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
}
.chip-mode.mode-smart {
  border-color: var(--success);
  color: var(--success);
}
.chip-mode.mode-pro {
  border-color: var(--orange);
  color: var(--orange-text);
}
.chip-mode.mode-claude {
  border-color: var(--danger);
  color: var(--danger);
}
.qside {
  display: flex;
  align-items: center;
  gap: var(--s-4);
  flex-shrink: 0;
}
.flag-review {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border: 1.5px solid var(--warn);
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--warn);
  white-space: nowrap;
}
.flag-review .sq {
  width: 9px;
  height: 9px;
  background: var(--warn);
}
.qchev {
  color: var(--text-3);
  flex-shrink: 0;
}
.qchev :deep(svg),
.qside :deep(.qchev) {
  width: 16px;
  height: 16px;
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
.v-over {
  display: inline-block;
  margin-left: 6px;
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--orange-text);
}

/* --- Expanded detail panel (meta banner + answers + tabs + override) --- */
.qdetail {
  background: var(--surface);
  padding: var(--s-5);
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: var(--s-5);
}
/* Compact meta banner: dt/dd pairs, always visible above the tabs. */
.meta-banner {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--s-3) var(--s-5);
  margin: 0;
  padding: var(--s-4) var(--s-5);
  border: 1px solid var(--border);
  background: var(--bg);
}
.meta-banner .mb {
  min-width: 0;
}
.meta-banner .mb-wide {
  grid-column: 1 / -1;
}
.meta-banner dt {
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-3);
  margin-bottom: 4px;
}
.meta-banner dd {
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
/* --- Detail tabs (shared Tabs.vue styled locally; active = 3px orange rule) --- */
.detail-tabs {
  border: 1px solid var(--border);
  background: var(--bg);
}
/* Charter: the active tab carries a 3px orange underline (Tabs.vue defaults to
   1.5px); restyle locally via :deep without touching the shared component. */
.detail-tabs :deep(.ui-tabs) {
  padding: 0 var(--s-5);
  border-bottom: 1px solid var(--border-strong);
}
.detail-tabs :deep(.ui-tab) {
  padding-top: var(--s-4);
  padding-bottom: var(--s-4);
  font-weight: var(--fw-bold);
}
.detail-tabs :deep(.ui-tab.is-active) {
  color: var(--text);
}
.detail-tabs :deep(.ui-tab.is-active)::after {
  height: 3px;
  background: var(--orange);
}
.tab-panel {
  padding: var(--s-5);
}
/* Reference tab: the non-binding-hint caption. */
.rp-note {
  font-size: var(--fs-xs);
  color: var(--text-3);
  line-height: 1.5;
  margin: var(--s-4) 0 0;
}
.ev-l {
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-3);
  margin-bottom: 6px;
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
.ev-table td.num {
  text-align: right;
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

/* --- Evolution badge (rendered as a question chip) --- */
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

/* attempt history mini-table (History tab) */
.hist-wrap {
  overflow-x: auto;
  border: 1px solid var(--border-strong);
}
.hist-table {
  width: 100%;
  border-collapse: collapse;
  background: var(--bg);
  font-size: var(--fs-sm);
}
.hist-table th {
  text-align: left;
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-2);
  padding: 9px 12px;
  background: var(--surface);
  border-bottom: 1px solid var(--border-strong);
  white-space: nowrap;
}
.hist-table th.num {
  text-align: right;
}
.hist-table td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  vertical-align: middle;
}
.hist-table td.num {
  text-align: right;
}
.hist-table tbody tr:last-child td {
  border-bottom: none;
}
.hist-result {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  flex-wrap: wrap;
}
.latest-tag {
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--orange-text);
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

@media (max-width: 760px) {
  .refprod {
    grid-template-columns: 1fr;
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

/* --- consultation responsive --- */
@media (max-width: 1080px) {
  /* Hero + KPIs stack, and the aside drops below the content (no longer sticky). */
  .top-band {
    grid-template-columns: 1fr;
  }
  .consult-aside {
    width: auto;
    flex: none;
    border-left: none;
    border-top: 1px solid var(--border);
    padding-left: 0;
    margin-left: 0;
    margin-top: var(--s-6);
    padding-top: var(--s-6);
    position: static;
  }
}
@media (max-width: 760px) {
  .hero {
    grid-template-columns: 1fr;
    justify-items: center;
    text-align: center;
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
  /* Question head stacks so chips + verdict never crush on narrow screens. */
  .qhead {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--s-3);
  }
  .qside {
    flex-wrap: wrap;
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
