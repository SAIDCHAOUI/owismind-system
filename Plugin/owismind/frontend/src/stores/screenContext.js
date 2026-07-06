// Screen-context consent store - the sticky-per-signature decision on whether to attach
// the SOURCE-DATA VIEW the user shaped (filters / search / DB figures) to the next
// /chat/start. It owns ONLY the decision; the live snapshot itself is derived on demand
// from the sources + evidence stores through the pure screenContextModel.
//
// State machine (see design-screen-context.md ux_flow):
//   liveSig   = signature of the current snapshot (null when none is eligible)
//   effective = (liveSig != null && decidedSig === liveSig) ? decision : null
//               -> the decision DIES when the signature changes (any filter/calc edit)
//   bannerEligible = liveSig != null && effective == null      (PromptBar adds `&& draft`)
//   chipVisible    = liveSig != null && effective === 'accepted'
import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import { useChatStore } from './chat.js'
import { useSessionStore } from './session.js'
import { useSourcesStore } from './sources.js'
import { useEvidenceStore } from './evidence.js'
import { pickSnapshot, snapshotSignature } from '../composables/screenContextModel.js'
import { track } from '../services/track.js'

export const useScreenContextStore = defineStore('screenContext', () => {
  const chat = useChatStore()
  const session = useSessionStore()
  const sources = useSourcesStore()
  const evidence = useEvidenceStore()

  const decision = ref(null) // 'accepted' | 'declined' | null
  const decidedSig = ref(null) // the signature the decision was made against
  const lastOfferedSig = ref(null) // guards the one-per-signature `offered` analytics

  // Agent label map { key -> label } from the session store (labels are purely
  // descriptive: the block never carries an agent_id, never resolved server-side).
  function _agentLabels() {
    const map = {}
    for (const a of session.agents || []) {
      if (a && a.key) map[a.key] = a.label || ''
    }
    return map
  }

  // Plain, already-unwrapped snapshot of the Source Data explorer store (the model stays
  // pure and node-testable, so the adapter does the unwrapping).
  function _sourcesState() {
    return {
      open: sources.open,
      agentKey: sources.agentKey,
      activeSourceLabel: sources.activeSourceLabel,
      columns: sources.columns,
      chips: sources.chips,
      q: sources.q,
      totalCount: sources.totalCount,
      totalLoading: sources.totalLoading,
      calcColumn: sources.calcColumn,
      calcFns: sources.calcFns,
      calcValues: sources.calcValues,
      calcLoading: sources.calcLoading,
      analyzeGroup: sources.analyzeGroup,
      analyzeBucket: sources.analyzeBucket,
      analyzeFn: sources.analyzeFn,
      analyzeMeasureColumn: sources.analyzeMeasureColumn,
      analyzeRows: sources.analyzeRows,
      analyzeTotals: sources.analyzeTotals,
      analyzeTruncated: sources.analyzeTruncated,
      analyzeLoading: sources.analyzeLoading,
    }
  }

  // Plain, already-unwrapped snapshot of the Evidence "Source data" store. `agentKey` is
  // the agent of the OPEN exchange (resolved through the chat store); `drill` carries the
  // drill labels; `columns` come from the exchange meta (temporal detection).
  function _evidenceState() {
    return {
      open: evidence.open,
      exchangeId: evidence.exchangeId,
      agentKey: chat.agentKeyForExchange(evidence.exchangeId),
      sourceTabKey: evidence.sourceTabKey,
      selectedTable: evidence.selectedTable,
      sources: evidence.sources,
      columns: (evidence.meta && evidence.meta.columns) || [],
      chips: evidence.chips,
      q: evidence.q,
      drill: evidence.drill && Array.isArray(evidence.drill.labels) ? evidence.drill.labels : null,
      totalCount: evidence.totalCount,
      totalLoading: evidence.totalLoading,
      calcColumn: evidence.calcColumn,
      calcFns: evidence.calcFns,
      calcValues: evidence.calcValues,
      calcLoading: evidence.calcLoading,
      analyzeGroup: evidence.analyzeGroup,
      analyzeBucket: evidence.analyzeBucket,
      analyzeFn: evidence.analyzeFn,
      analyzeMeasureColumn: evidence.analyzeMeasureColumn,
      analyzeRows: evidence.analyzeRows,
      analyzeTotals: evidence.analyzeTotals,
      analyzeTruncated: evidence.analyzeTruncated,
      analyzeLoading: evidence.analyzeLoading,
    }
  }

  // The live snapshot (or null). Recomputed reactively from both stores; O(small lists).
  const offer = computed(() =>
    pickSnapshot({
      sourcesState: _sourcesState(),
      evidenceState: _evidenceState(),
      agentLabels: _agentLabels(),
    }),
  )
  const liveSig = computed(() => (offer.value ? snapshotSignature(offer.value) : null))
  const effective = computed(() =>
    liveSig.value != null && decidedSig.value === liveSig.value ? decision.value : null,
  )
  // WITHOUT the draft condition on purpose: PromptBar ANDs `&& chat.draft.trim()` so the
  // banner only appears once the user starts typing (a decision on an empty box is noise).
  const bannerEligible = computed(() => liveSig.value != null && effective.value == null)
  const chipVisible = computed(() => liveSig.value != null && effective.value === 'accepted')

  function accept() {
    if (liveSig.value == null) return
    decision.value = 'accepted'
    decidedSig.value = liveSig.value
  }
  // Declining (or removing the accepted chip) parks the decision on THIS signature so the
  // banner never nags again for the same view; a view change re-offers.
  function decline() {
    if (liveSig.value == null) return
    decision.value = 'declined'
    decidedSig.value = liveSig.value
    track('screen_context_dismissed', { surface: offer.value ? offer.value.surface : null })
  }
  function reset() {
    decision.value = null
    decidedSig.value = null
    lastOfferedSig.value = null
  }
  // Fire the `offered` analytics ONCE per signature (guarded by lastOfferedSig). Called by
  // PromptBar at banner display time (it owns the draft condition). Defaults to the live
  // signature so callers can pass nothing.
  function markOffered(sig) {
    const s = sig != null ? sig : liveSig.value
    if (s == null || s === lastOfferedSig.value) return
    lastOfferedSig.value = s
    track('screen_context_offered', { surface: offer.value ? offer.value.surface : null })
  }
  // The LIVE snapshot to attach at send time (fresh figures), or null. Read by chat.js in
  // _runExchange: only an accepted decision on the CURRENT signature attaches anything.
  function snapshotForSend() {
    return effective.value === 'accepted' ? offer.value : null
  }

  // Reset the consent on a conversation switch and on a PRE-conversation agent switch
  // (mirror of PromptBar's existing promptContext watchers). A panel close / store reset
  // just makes liveSig null, so the banner and chip disappear on their own.
  watch(() => chat.activeSessionId, () => reset())
  watch(() => session.selectedAgentKey, () => {
    if (!chat.exchanges.length) reset()
  })

  return {
    decision,
    decidedSig,
    lastOfferedSig,
    offer,
    liveSig,
    effective,
    bannerEligible,
    chipVisible,
    accept,
    decline,
    reset,
    markOffered,
    snapshotForSend,
  }
})
