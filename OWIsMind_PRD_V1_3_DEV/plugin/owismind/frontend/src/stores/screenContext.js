// Screen-context store - the SOURCE-DATA VIEW the user shaped (filters / search /
// DB figures) is attached to the next /chat/start BY DEFAULT: the agent must see
// what the user is doing on screen without an extra consent step. The store owns
// ONLY the opt-out decision; the live snapshot itself is derived on demand from
// the sources + evidence stores through the pure screenContextModel.
//
// State machine (auto-include, 2026-08-06 - replaces the consent banner):
//   liveSig   = signature of the current snapshot (null when none is eligible)
//   effective = liveSig == null ? null
//             : (decidedSig === liveSig && decision) ? decision : 'accepted'
//               -> INCLUDED by default; an explicit opt-out (decline) sticks to
//                  THIS signature only and dies on any filter/calc edit
//   chipVisible     = liveSig != null && effective === 'accepted'
//   excludedVisible = liveSig != null && effective === 'declined'  (re-include cue)
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

  const decision = ref(null) // 'accepted' | 'declined' | null (null = default include)
  const decidedSig = ref(null) // the signature the decision was made against

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
  // Default-include: with no sticky decision on the CURRENT signature, a live
  // snapshot is 'accepted'. An opt-out (or explicit re-accept) wins while the view
  // is unchanged; any filter/calc edit mints a new signature and re-includes.
  const effective = computed(() => {
    if (liveSig.value == null) return null
    if (decidedSig.value === liveSig.value && decision.value) return decision.value
    return 'accepted'
  })
  const chipVisible = computed(() => liveSig.value != null && effective.value === 'accepted')
  // Opted-out view still on screen: PromptBar shows a quiet re-include cue so the
  // user stays in control both ways (exclude AND bring back).
  const excludedVisible = computed(() => liveSig.value != null && effective.value === 'declined')

  // Re-include after an opt-out (the quiet cue), pinned to the current signature.
  function accept() {
    if (liveSig.value == null) return
    decision.value = 'accepted'
    decidedSig.value = liveSig.value
  }
  // Removing the chip parks an opt-out on THIS signature: the same view never
  // re-attaches on its own; a view change (new signature) re-includes by default.
  function decline() {
    if (liveSig.value == null) return
    decision.value = 'declined'
    decidedSig.value = liveSig.value
    track('screen_context_dismissed', { surface: offer.value ? offer.value.surface : null })
  }
  function reset() {
    decision.value = null
    decidedSig.value = null
  }
  // The LIVE snapshot to attach at send time (fresh figures), or null. Read by chat.js
  // in _runExchange: any live snapshot not opted out on the CURRENT signature attaches.
  function snapshotForSend() {
    return effective.value === 'accepted' ? offer.value : null
  }

  // Reset the opt-out on a conversation switch and on a PRE-conversation agent switch
  // (mirror of PromptBar's existing promptContext watchers). A panel close / store reset
  // just makes liveSig null, so the chip disappears on its own.
  watch(() => chat.activeSessionId, () => reset())
  watch(() => session.selectedAgentKey, () => {
    if (!chat.exchanges.length) reset()
  })

  return {
    decision,
    decidedSig,
    offer,
    liveSig,
    effective,
    chipVisible,
    excludedVisible,
    accept,
    decline,
    reset,
    snapshotForSend,
  }
})
