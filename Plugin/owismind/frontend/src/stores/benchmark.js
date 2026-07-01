// Benchmark suggestions store - the collaborative golden-set intake (user pole).
//
// Holds the TRANSIENT prefill set when a user clicks "Suggest for the benchmark" under a chat
// answer (the message "..." menu): { exchangeId, question, agentAnswer }. The Benchmark page
// consumes it to pre-fill the from-chat form, then clears it. Also owns the caller's own
// suggestions list (status feedback). Submission wraps the thin backend service; the
// component surfaces success/error toasts.
import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  suggestBenchmarkManual,
  suggestBenchmarkFromChat,
  fetchMySuggestions,
  fetchBenchmarkResults,
  fetchBenchmarkAttempt,
  adminBenchmarkOverride,
} from '../services/backend.js'
import { normalizeResults, rowKey } from '../composables/benchmarkResults.js'

export const useBenchmarkStore = defineStore('benchmark', () => {
  // Prefill from a chat answer. null = the Benchmark page shows the blank manual form.
  const prefill = ref(null)
  const mySuggestions = ref([])
  const loadingMine = ref(false)

  // --- Consultation (benchmark results, ALL users) ----------------------------
  // The agent whose results are on screen (its logical key), the normalized RESULTS
  // (or null), the selected benchmark id, and the read state. A benchmark is a named
  // campaign that accumulates runs; the score is over the latest attempt of each
  // question. configured:false = no benchmark wired for the agent; readError = a soft
  // degraded read; resultsError = a hard failure.
  const consultAgentKey = ref('')
  const results = ref(null)
  const selectedBenchmarkId = ref('')
  const resultsConfigured = ref(true)
  const resultsReadError = ref('')
  const resultsLoading = ref(false)
  const resultsError = ref('')
  // The override currently in flight (row key), so the per-row admin buttons can disable.
  const overrideBusyKey = ref('')
  // On-demand FULL detail per expanded question, keyed by rowKey: { loading } | { data } | { error }.
  // The data is { found, answer_text, sql_items:[{sql, success, row_count, result}] } - the complete
  // answer + the SQL the agent actually generated + the captured result table. Reset when results reload.
  const attemptDetail = ref({})

  function setPrefill(data) {
    prefill.value = data
  }
  function clearPrefill() {
    prefill.value = null
  }

  // The caller's own suggestions (newest first). Never throws: a failure leaves an empty list.
  async function loadMine() {
    loadingMine.value = true
    try {
      const r = await fetchMySuggestions()
      mySuggestions.value = Array.isArray(r.suggestions) ? r.suggestions : []
    } catch (e) {
      mySuggestions.value = []
    } finally {
      loadingMine.value = false
    }
  }

  // Submit a manual (from-scratch) suggestion. Throws the backend error code on failure so the
  // caller can toast it; on success the "my suggestions" list is refreshed.
  async function submitManual(fields) {
    await suggestBenchmarkManual(fields)
    await loadMine()
  }

  // Submit a from-chat suggestion. Throws on failure; on success clears the prefill and
  // refreshes the list.
  async function submitFromChat(payload) {
    await suggestBenchmarkFromChat(payload)
    clearPrefill()
    await loadMine()
  }

  // Load the benchmark results for one agent (+ optional benchmark id). Never throws: a
  // failure leaves a soft error state the view renders (the consultation must never crash).
  async function loadResults(agentKey, benchmarkId) {
    if (!agentKey) {
      results.value = null
      resultsConfigured.value = true
      resultsReadError.value = ''
      resultsError.value = ''
      return
    }
    resultsLoading.value = true
    resultsError.value = ''
    attemptDetail.value = {}  // drop any per-question detail cached for the previous agent/benchmark
    try {
      const r = await fetchBenchmarkResults(agentKey, benchmarkId)
      resultsConfigured.value = r.configured !== false
      resultsReadError.value = r.read_error || ''
      results.value = r.results ? normalizeResults(r.results) : null
      selectedBenchmarkId.value = (results.value && results.value.benchmark_id) || benchmarkId || ''
    } catch (e) {
      results.value = null
      resultsConfigured.value = true
      resultsReadError.value = ''
      resultsError.value = (e && e.message) || 'load_failed'
    } finally {
      resultsLoading.value = false
    }
  }

  // Pick an agent for the consultation: reset the benchmark and (re)load its newest one.
  function selectConsultAgent(agentKey) {
    consultAgentKey.value = agentKey || ''
    selectedBenchmarkId.value = ''
    return loadResults(consultAgentKey.value, '')
  }

  // Pick a specific benchmark of the current agent.
  function selectBenchmark(benchmarkId) {
    selectedBenchmarkId.value = benchmarkId || ''
    return loadResults(consultAgentKey.value, selectedBenchmarkId.value)
  }

  // Load the FULL detail of ONE attempt on demand (when a user expands its question row): the complete
  // answer + the SQL the agent actually generated + the captured result table. Fetched once per rowKey,
  // never throws (a failure leaves an { error } state the view renders). The heavy blob loads one row at
  // a time so the list read stays light.
  async function loadAttempt(row) {
    const k = rowKey(row)
    if (!k || attemptDetail.value[k]) return
    attemptDetail.value[k] = { loading: true }
    try {
      const r = await fetchBenchmarkAttempt(consultAgentKey.value, {
        run_id: row.run_id,
        question_id: row.question_id,
        agent_key: row.agent_key,
        mode: row.mode,
      })
      attemptDetail.value[k] = { data: (r && r.detail) ? r.detail : { found: false } }
    } catch (e) {
      attemptDetail.value[k] = { error: true }
    }
  }

  // Admin: set / clear an override on one scored question, then re-fetch the same agent
  // + benchmark so the effective verdict updates. The payload's run_id targets the
  // SPECIFIC attempt being overridden (each detail row carries its own run_id). Throws
  // the backend code on failure (the caller toasts it); the busy key disables the row's
  // buttons while in flight.
  async function submitOverride(payload, busyKey) {
    overrideBusyKey.value = busyKey || ''
    try {
      await adminBenchmarkOverride(payload)
      await loadResults(consultAgentKey.value, selectedBenchmarkId.value)
    } finally {
      overrideBusyKey.value = ''
    }
  }

  return {
    prefill,
    mySuggestions,
    loadingMine,
    setPrefill,
    clearPrefill,
    loadMine,
    submitManual,
    submitFromChat,
    // consultation
    consultAgentKey,
    results,
    selectedBenchmarkId,
    resultsConfigured,
    resultsReadError,
    resultsLoading,
    resultsError,
    overrideBusyKey,
    attemptDetail,
    loadResults,
    selectConsultAgent,
    selectBenchmark,
    submitOverride,
    loadAttempt,
  }
})
