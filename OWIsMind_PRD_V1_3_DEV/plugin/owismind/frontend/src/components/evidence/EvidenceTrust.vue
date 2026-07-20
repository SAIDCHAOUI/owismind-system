<script setup>
// Trust badge - the FIRST thing a non-technical user reads in the Evidence
// panel: one pill (verification level × captured result) + one plain-language
// sentence, mapped deterministically by trustLevel() from the backend's own
// verification verdict (no LLM, no upgrade - honesty rules, spec §9).
// Visual grammar: solid orange = certified, dashed orange = partial, muted
// grey = agent claim only. NEVER green (Evidence no-green rule).
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEvidenceStore } from '../../stores/evidence.js'
import { trustLevel, droppedNote } from '../../composables/evidenceProof.js'

const { t } = useI18n()
const evidence = useEvidenceStore()

const trust = computed(() => trustLevel(evidence.meta))
// One sentence per badge: ev.proof.level.X -> ev.proof.level.desc.X.
const descKey = computed(() => trust.value.key.replace('ev.proof.level.', 'ev.proof.level.desc.'))
// Conditions the interactive view could NOT reproduce - listed, never hidden.
const dropped = computed(() => droppedNote(evidence.meta && evidence.meta.verification))
</script>

<template>
  <section class="ev-trust" :class="'tone-' + trust.tone">
    <div class="ev-trust-line">
      <span class="ev-trust-pill">{{ t(trust.key) }}</span>
      <span class="ev-trust-desc">{{ t(descKey) }}</span>
    </div>
    <div v-if="dropped > 0" class="ev-trust-note">
      {{ t('ev.proof.level.partial_note', [dropped]) }}
    </div>
  </section>
</template>

<style scoped>
/* No z-index here: the chips popover (z-index 5 on .ev-chips, L043) must stay
   on top of every proof section. */
.ev-trust { display: flex; flex-direction: column; gap: var(--s-1); }
.ev-trust-line { display: flex; align-items: baseline; gap: var(--s-2); flex-wrap: wrap; }
.ev-trust-pill {
  flex: none; padding: 2px 10px; border-radius: var(--r-pill);
  border: 1px solid var(--orange); background: var(--orange-soft);
  color: var(--orange-text); font-size: var(--fs-xs); font-weight: 600;
  white-space: nowrap;
}
/* Partial proof = dashed border (same grammar as the "modified" chip badge). */
.ev-trust.tone-dashed .ev-trust-pill { border-style: dashed; }
/* Declared = agent claim only: muted grey, no orange anywhere. */
.ev-trust.tone-muted .ev-trust-pill {
  border-color: var(--border); background: var(--surface-2); color: var(--text-3);
}
.ev-trust-desc { font-size: var(--fs-sm); color: var(--text-2); min-width: 0; }
/* Dashed sub-line: the honest "N conditions not reproduced" note. */
.ev-trust-note {
  padding-top: var(--s-1); border-top: 1px dashed var(--border);
  font-size: var(--fs-xs); color: var(--text-3);
}
/* Dark: the light tint would glow - swap to the translucent orange patch.
   Entire selector inside :global (scoped+theme rule F2/L022). The muted pill
   keeps --surface-2 (theme-adaptive), so only orange tones are overridden. */
:global(body[data-theme="dark"] .ev-trust.tone-solid .ev-trust-pill),
:global(body[data-theme="dark"] .ev-trust.tone-dashed .ev-trust-pill) {
  background: var(--orange-soft-dark);
}
</style>
