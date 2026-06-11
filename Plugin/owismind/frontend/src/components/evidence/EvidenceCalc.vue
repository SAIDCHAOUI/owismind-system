<script setup>
// Calculation section — HOW the number was computed, as a numbered list of
// business-language steps (no SQL jargon: the i18n ev.exp.* wording carries
// the translation; column names stay verbatim). Steps come straight from the
// backend's deterministic explanation; an unknown kind degrades to the
// ev.exp.opaque fallback (calcStepArgs). Entirely hidden when the backend
// produced no steps (v1 meta included) — an empty "how" section would only
// erode trust.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEvidenceStore } from '../../stores/evidence.js'
import { calcStepArgs, MAX_CALC_STEPS } from '../../composables/evidenceProof.js'

const { t } = useI18n()
const evidence = useEvidenceStore()

// Bounded projection: contract says ≤ 15 steps, the slice makes it a hard cap.
const steps = computed(() => {
  const e = evidence.meta && evidence.meta.explanation
  const raw = e && Array.isArray(e.steps) ? e.steps : []
  return raw.slice(0, MAX_CALC_STEPS).map((s) => calcStepArgs(s))
})
</script>

<template>
  <section v-if="steps.length" class="ev-calc">
    <span class="ev-sec-title">{{ t('ev.proof.calc') }}</span>
    <ol class="ev-calc-steps">
      <li v-for="(s, i) in steps" :key="i" class="ev-calc-step">
        <span class="num mono">{{ i + 1 }}</span>
        <span class="txt">{{ t(s.key, s.args) }}</span>
      </li>
    </ol>
  </section>
</template>

<style scoped>
/* No z-index: the chips popover (z-index 5, L043) must stay above. */
.ev-calc { display: flex; flex-direction: column; gap: var(--s-2); }
/* Section label — same pattern as .ev-chips-title (EvidenceChips). */
.ev-sec-title {
  font-size: var(--fs-xs); color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.04em;
}
.ev-calc-steps {
  margin: 0; padding: 0; list-style: none;
  display: flex; flex-direction: column; gap: var(--s-1);
}
.ev-calc-step { display: flex; align-items: baseline; gap: var(--s-2); min-width: 0; }
/* Discreet step number — fixed width keeps the texts left-aligned. */
.ev-calc-step .num {
  flex: none; min-width: 16px; text-align: right;
  font-size: 11px; color: var(--text-3);
}
.ev-calc-step .txt { font-size: var(--fs-sm); color: var(--text); min-width: 0; overflow-wrap: anywhere; }
</style>
