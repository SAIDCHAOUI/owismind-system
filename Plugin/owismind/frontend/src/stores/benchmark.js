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
} from '../services/backend.js'

export const useBenchmarkStore = defineStore('benchmark', () => {
  // Prefill from a chat answer. null = the Benchmark page shows the blank manual form.
  const prefill = ref(null)
  const mySuggestions = ref([])
  const loadingMine = ref(false)

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

  return {
    prefill,
    mySuggestions,
    loadingMine,
    setPrefill,
    clearPrefill,
    loadMine,
    submitManual,
    submitFromChat,
  }
})
