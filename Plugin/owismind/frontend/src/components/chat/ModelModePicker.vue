<script setup>
// Model-mode picker. A small pill in the prompt bar shows the current mode and
// opens a chooser modeled on the DSS "conversation settings" dialog: a sober
// two-pane layout (the three modes listed on the left, a detail panel on the
// right with cost + speed meters) plus an Annuler / Valider footer. Selection is
// click-based (no hover preview) so switching rows never reflows the dialog. Smart
// is surfaced as the recommended default. The choice is a per-turn preference (ui
// store) applied only on Valider; the backend defaults to smart.
//   smart = Gemini 3.1 Flash-Lite (default) . pro = Gemini 3.5 Flash . claude = Claude Sonnet.
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useUiStore, MODEL_MODES } from '../../stores/ui.js'
import Modal from '../ui/Modal.vue'
import { Icon, Button } from '../ui'

const { t } = useI18n()
const ui = useUiStore()

const open = ref(false)
const current = computed(() => ui.modelMode)
const modes = MODEL_MODES // ['smart', 'pro', 'claude']

// Cost and speed on a 0..5 scale (mirrors the DSS dialog's "n/5" meters). Smart is
// the cheapest AND fastest, which is why it is the recommended default; Claude trades
// speed/cost for depth of reasoning.
const COST = { smart: 1, pro: 3, claude: 5 }
const SPEED = { smart: 5, pro: 3, claude: 2 }
// Small trigger-pill dot: a calm cost cue (green = the safe recommended default).
const PILL_LEVEL = { smart: 1, pro: 2, claude: 3 }

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
              <span v-if="m === 'smart'" class="reco-badge">{{ t('mode.recommended') }}</span>
            </span>
            <Icon v-if="selected === m" name="check" :size="16" class="row-check" />
          </button>
        </div>

        <!-- Right: detail of the selected mode (DSS detail-panel mood). -->
        <div class="mode-detail">
          <div class="detail-head">
            <span class="detail-name">{{ t('mode.' + selected) }}</span>
            <span v-if="selected === 'smart'" class="reco-badge">{{ t('mode.recommended') }}</span>
          </div>
          <p class="detail-desc">{{ t('mode.' + selected + '_desc') }}</p>

          <!-- Smart: strong green "recommended" callout - push the safe default hard. -->
          <p v-if="selected === 'smart'" class="callout callout-reco">
            <Icon name="check" :size="15" class="callout-ico" />
            <span>{{ t('mode.reco_line') }}</span>
          </p>
          <!-- Claude: red cost warning - expensive, reserved for complex analysis. -->
          <p v-else-if="selected === 'claude'" class="callout callout-warn">
            <Icon name="alert" :size="15" class="callout-ico" />
            <span>{{ t('mode.claude_warning') }}</span>
          </p>

          <div class="meters">
            <div class="meter-row">
              <span class="meter-label">{{ t('mode.cost_label') }}</span>
              <!-- Cost gauge tinted by severity: green (Smart) -> orange (Pro) -> red
                   (Claude), reinforcing that the higher modes cost much more. -->
              <span class="meter5" :class="'cost-' + selected" aria-hidden="true">
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

/* Trigger pill: compact inline control that opens the chooser. */
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

/* ---- Modal inner content (the frame comes from Modal.vue) ---- */

/* Two-column grid: bordered option list (left) + bordered detail panel (right).
   Square geometry throughout - no card radius. */
.picker {
  display: grid;
  grid-template-columns: 210px 1fr;
  gap: var(--s-4);
  align-items: start;
}

/* Option list: a single bordered block; rows separated by inner bottom borders. */
.mode-list {
  border: 1px solid var(--border-strong);
  display: flex;
  flex-direction: column;
}
.mode-row {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  text-align: left; width: 100%; padding: 16px;
  border-bottom: 1px solid var(--border);
  border-left: 3px solid transparent;
  background: var(--bg);
  transition: background var(--dur) var(--ease);
}
.mode-row:last-child { border-bottom: none; }
.mode-row:hover { background: var(--surface); }
/* Active row: orange left bar + soft fill (Orange 80/20 accent rule). */
.mode-row.active { border-left-color: var(--orange); background: var(--surface); }

.row-main { display: inline-flex; align-items: center; gap: 8px; min-width: 0; flex-wrap: wrap; }
.row-name { font-size: 15px; font-weight: 800; color: var(--text); font-family: var(--font-sans); }
/* RECOMMENDED tag: a green chip (status colour) so Smart visibly stands out as the
   safe default - separate from the orange "selected" accent. Square, theme-safe
   (soft green fill + green border/text, AA in light and dark). */
.reco-badge {
  font-size: 10px; font-weight: 800; letter-spacing: 0.04em; text-transform: uppercase;
  color: var(--success); background: var(--success-soft);
  border: 1px solid var(--success); padding: 2px 6px; white-space: nowrap;
}
/* Check shown only when active; orange. */
.row-check { color: var(--orange); flex-shrink: 0; }

/* Detail panel: flat border, square, fixed min-height so switching rows never
   reflowing the dialog. */
.mode-detail {
  border: 1px solid var(--border-strong);
  padding: 20px;
  min-height: 220px;
}
.detail-head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.detail-name { font-size: 16px; font-weight: 800; color: var(--text); font-family: var(--font-sans); }
.detail-desc { font-size: 14px; color: var(--text-2); line-height: 1.55; margin: 0 0 12px; }

/* Callouts: a flat tinted box with a 3px status bar (no glow/gradient, charter-safe).
   Smart = green "recommended", Claude = red "expensive" warning. */
.callout {
  display: flex; align-items: flex-start; gap: 8px;
  font-size: 13px; line-height: 1.5; color: var(--text);
  margin: 0; padding: 10px 12px; border-left: 3px solid transparent;
}
.callout-ico { flex-shrink: 0; margin-top: 1px; }
.callout-reco { background: var(--success-soft); border-left-color: var(--success); }
.callout-reco .callout-ico { color: var(--success); }
.callout-warn { background: var(--danger-soft); border-left-color: var(--danger); }
.callout-warn .callout-ico { color: var(--danger); }

/* Cost / Speed meter rows with 5-dot gauges. */
.meters { margin-top: 16px; display: flex; flex-direction: column; gap: 10px; }
.meter-row { display: flex; align-items: center; gap: 12px; font-size: 13px; }
.meter-label {
  width: 54px; flex-shrink: 0;
  font-size: 11px; font-weight: 800; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--text-2);
  font-family: var(--font-sans);
}
/* Dots: circles by nature (not affected by the square-geometry rule). */
.meter5 { display: inline-flex; gap: 5px; }
.meter5 i { width: 8px; height: 8px; border-radius: 50%; background: var(--border-strong); }
.meter5 i.on { background: var(--text); }
/* Cost gauge tinted by severity (the speed gauge stays neutral). */
.meter5.cost-smart i.on { background: var(--success); }
.meter5.cost-pro i.on { background: var(--orange); }
.meter5.cost-claude i.on { background: var(--danger); }
.meter-val { font-size: var(--fs-xs); color: var(--text-2); }

/* Envelope note: flat surface, thin border, square, wallet icon + quiet text. */
.envelope {
  display: flex; align-items: flex-start; gap: 10px;
  font-size: 13px; color: var(--text-2); line-height: 1.5;
  margin-top: 18px; padding: 14px 16px;
  background: var(--surface); border: 1px solid var(--border);
}
.envelope-ico { flex-shrink: 0; margin-top: 1px; color: var(--text-3); }

@media (max-width: 560px) {
  .picker { grid-template-columns: 1fr; }
  .mode-detail { min-height: 0; }
}

/* Respect user motion preference for the trigger transition. */
@media (prefers-reduced-motion: reduce) {
  .mode-trigger, .mode-row { transition: none; }
}
</style>
