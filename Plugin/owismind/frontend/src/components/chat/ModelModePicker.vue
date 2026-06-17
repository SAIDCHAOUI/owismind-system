<script setup>
// Model-mode picker. A small pill in the prompt bar shows the current mode and
// opens a chooser modeled on the DSS "conversation settings" dialog: a sober
// two-pane layout (the three modes listed on the left, a detail panel on the
// right with cost + speed meters) plus an Annuler / Valider footer. Selection is
// click-based (no hover preview) so switching rows never reflows the dialog. Eco
// is surfaced as the recommended default. The choice is a per-turn preference (ui
// store) applied only on Valider; the backend defaults to eco.
//   eco = Gemini 3.1 Flash-Lite (default) . medium = Gemini 3.5 Flash . high = Claude Sonnet.
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useUiStore, MODEL_MODES } from '../../stores/ui.js'
import Modal from '../ui/Modal.vue'
import { Icon, Button } from '../ui'

const { t } = useI18n()
const ui = useUiStore()

const open = ref(false)
const current = computed(() => ui.modelMode)
const modes = MODEL_MODES // ['eco', 'medium', 'high']

// Cost and speed on a 0..5 scale (mirrors the DSS dialog's "n/5" meters). Eco is
// the cheapest AND fastest, which is why it is the recommended default; high trades
// speed/cost for depth of reasoning.
const COST = { eco: 1, medium: 3, high: 5 }
const SPEED = { eco: 5, medium: 3, high: 2 }
// Small trigger-pill dot: a calm cost cue (green = the safe recommended default).
const PILL_LEVEL = { eco: 1, medium: 2, high: 3 }

// Pending selection inside the dialog (applied only on Valider). Reset to the
// active mode every time the dialog opens.
const selected = ref(ui.modelMode)
watch(open, (isOpen) => {
  if (isOpen) selected.value = ui.modelMode
})

function validate() {
  ui.setModelMode(selected.value)
  open.value = false
}
function cancel() {
  open.value = false
}
</script>

<template>
  <div class="mode-wrap">
    <!-- Trigger pill: current mode + a hint that it opens the chooser. -->
    <button
      type="button"
      class="mode-trigger"
      :title="t('mode.' + current + '_hint')"
      :aria-label="t('mode.modal_title')"
      @click="open = true"
    >
      <span class="dot" :class="'lvl-' + PILL_LEVEL[current]" aria-hidden="true" />
      <span class="mode-name">{{ t('mode.' + current) }}</span>
    </button>

    <Modal v-model="open" :title="t('mode.modal_title')" max-width="640px">
      <p class="intro">{{ t('mode.modal_intro') }}</p>

      <div class="picker">
        <!-- Left: the three modes as a sober list (DSS model-list mood). -->
        <div class="mode-list" role="radiogroup" :aria-label="t('mode.label')">
          <button
            v-for="m in modes"
            :key="m"
            type="button"
            class="mode-row"
            :class="{ active: selected === m }"
            role="radio"
            :aria-checked="selected === m"
            @click="selected = m"
          >
            <span class="row-main">
              <span class="row-name">{{ t('mode.' + m) }}</span>
              <span v-if="m === 'eco'" class="reco-badge">{{ t('mode.recommended') }}</span>
            </span>
            <Icon v-if="selected === m" name="check" :size="16" class="row-check" />
          </button>
        </div>

        <!-- Right: detail of the selected mode (DSS detail-panel mood). -->
        <div class="mode-detail">
          <div class="detail-head">
            <span class="detail-name">{{ t('mode.' + selected) }}</span>
            <span v-if="selected === 'eco'" class="reco-badge">{{ t('mode.recommended') }}</span>
          </div>
          <p class="detail-desc">{{ t('mode.' + selected + '_desc') }}</p>
          <p v-if="selected === 'eco'" class="detail-reco">{{ t('mode.reco_line') }}</p>

          <div class="meters">
            <div class="meter-row">
              <span class="meter-label">{{ t('mode.cost_label') }}</span>
              <span class="meter5" aria-hidden="true">
                <i v-for="n in 5" :key="n" :class="{ on: n <= COST[selected] }" />
              </span>
              <span class="meter-val">{{ t('mode.' + selected + '_cost') }} ({{ COST[selected] }}/5)</span>
            </div>
            <div class="meter-row">
              <span class="meter-label">{{ t('mode.speed_label') }}</span>
              <span class="meter5" aria-hidden="true">
                <i v-for="n in 5" :key="n" :class="{ on: n <= SPEED[selected] }" />
              </span>
              <span class="meter-val">{{ t('mode.' + selected + '_speed') }} ({{ SPEED[selected] }}/5)</span>
            </div>
          </div>
        </div>
      </div>

      <p class="envelope">
        <Icon name="wallet" :size="15" class="envelope-ico" />
        <span>{{ t('mode.envelope_note') }}</span>
      </p>

      <template #footer>
        <Button variant="ghost" @click="cancel">{{ t('mode.cancel') }}</Button>
        <Button variant="primary" @click="validate">{{ t('mode.validate') }}</Button>
      </template>
    </Modal>
  </div>
</template>

<style scoped>
.mode-wrap { display: inline-flex; }
/* Trigger pill */
.mode-trigger {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: var(--r-pill);
  background: var(--surface-2); border: 1px solid var(--border);
  font-size: 11px; font-weight: 600; color: var(--text-2);
  transition: all var(--dur) var(--ease); white-space: nowrap;
}
.mode-trigger:hover { color: var(--text); border-color: var(--border-strong); }
.dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot.lvl-1 { background: var(--success); }
.dot.lvl-2 { background: var(--orange); }
.dot.lvl-3 { background: var(--danger); }

/* Modal body */
.intro { font-size: var(--fs-sm); color: var(--text-2); margin: 0 0 16px; line-height: 1.5; }

/* Two-pane picker (list + detail), DSS "conversation settings" mood: flat, white,
   thin borders, near-square corners, brand orange used only as an accent (Orange
   80/20 rule). */
.picker { display: flex; gap: var(--s-4); align-items: stretch; }

.mode-list { flex: 0 0 196px; display: flex; flex-direction: column; gap: 4px; }
.mode-row {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  text-align: left; width: 100%; padding: 11px 12px;
  border: 1px solid var(--border); border-left: 3px solid transparent;
  border-radius: 4px; background: var(--bg);
  transition: background var(--dur) var(--ease);
}
.mode-row:hover { background: var(--surface-hover); }
/* Selected row: light grey fill + brand-orange left bar (mirrors the DSS list). */
.mode-row.active { background: var(--surface-2); border-color: var(--border-strong); border-left-color: var(--orange); }
.row-main { display: inline-flex; align-items: center; gap: 8px; min-width: 0; }
.row-name { font-size: var(--fs-md); font-weight: 600; color: var(--text); }
.row-check { color: var(--orange); flex-shrink: 0; }
/* Recommended tag: small orange label (the brand accent), no fill. */
.reco-badge {
  font-size: 9px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;
  color: var(--orange-text); white-space: nowrap;
}

/* Detail panel. Fixed min-height so selecting a different mode never changes the
   dialog height (no reflow / jump). */
.mode-detail {
  flex: 1; min-width: 0; min-height: 200px; padding: var(--s-4);
  border: 1px solid var(--border); border-radius: 4px; background: var(--bg);
}
.detail-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.detail-name { font-size: var(--fs-lg); font-weight: 600; color: var(--text); letter-spacing: -0.01em; }
.detail-desc { font-size: var(--fs-sm); color: var(--text-2); line-height: 1.55; margin: 0; }
/* Recommendation note: sober text (not an orange paragraph), slightly emphasised. */
.detail-reco { font-size: var(--fs-sm); color: var(--text); font-weight: 500; line-height: 1.5; margin: 8px 0 0; }

.meters { margin-top: 18px; display: flex; flex-direction: column; gap: 10px; }
.meter-row { display: flex; align-items: center; gap: 10px; }
.meter-label {
  flex: 0 0 56px; font-size: 11px; font-weight: 600; letter-spacing: 0.03em;
  text-transform: uppercase; color: var(--text-3);
}
.meter5 { display: inline-flex; gap: 4px; }
.meter5 i { width: 7px; height: 7px; border-radius: 50%; background: var(--border); }
/* Dark filled dots, like the DSS cost/eCO2 meters. */
.meter5 i.on { background: var(--text); }
.meter-val { font-size: var(--fs-xs); color: var(--text-2); }

/* Cost note: a quiet, neutral hint (grey, no orange fill) with a small wallet cue. */
.envelope {
  display: flex; align-items: flex-start; gap: 8px;
  font-size: var(--fs-xs); color: var(--text-2); line-height: 1.5;
  margin: 18px 0 0; padding: 10px 12px; border-radius: 4px;
  background: var(--surface-2);
}
.envelope-ico { margin-top: 1px; color: var(--text-3); }

@media (max-width: 560px) {
  .picker { flex-direction: column; }
  .mode-list { flex: 1 1 auto; }
  .mode-detail { min-height: 0; }
}
</style>
