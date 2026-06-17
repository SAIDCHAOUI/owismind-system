<script setup>
// Model-mode picker. A small pill in the prompt bar shows the current mode and
// opens a chooser modeled on the DSS "conversation settings" dialog: a sober
// two-pane layout (the three modes listed on the left, a detail panel on the
// right with cost + speed meters) rather than a flashy stack of cards. Eco is
// surfaced as the recommended default (best speed/cost, good quality). The choice
// is a per-turn preference (ui store); the backend defaults to eco.
//   eco = Gemini 3.1 Flash-Lite (default) . medium = Gemini 3.5 Flash . high = Claude Sonnet.
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useUiStore, MODEL_MODES } from '../../stores/ui.js'
import Modal from '../ui/Modal.vue'
import { Icon } from '../ui'

const { t } = useI18n()
const ui = useUiStore()

const open = ref(false)
const current = computed(() => ui.modelMode)
const modes = MODEL_MODES // ['eco', 'medium', 'high']

// Cost and speed on a 0..5 scale (mirrors the DSS dialog's "n/5" meters). Eco is
// the cheapest AND fastest, which is exactly why it is the recommended default;
// high trades speed/cost for depth of reasoning.
const COST = { eco: 1, medium: 3, high: 5 }
const SPEED = { eco: 5, medium: 3, high: 2 }
// Small trigger-pill dot: a calm cost cue (green = the safe recommended default).
const PILL_LEVEL = { eco: 1, medium: 2, high: 3 }

// Detail pane follows the hovered/focused row, falling back to the active mode.
const preview = ref('')
const detail = computed(() => preview.value || current.value)

function choose(m) {
  ui.setModelMode(m)
  open.value = false
}
function previewMode(m) {
  preview.value = m
}
function clearPreview() {
  preview.value = ''
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

    <Modal v-model="open" :title="t('mode.modal_title')" icon="sliders" max-width="660px">
      <p class="intro">{{ t('mode.modal_intro') }}</p>

      <div class="picker">
        <!-- Left: the three modes as a sober list (DSS model-list mood). -->
        <div class="mode-list" role="radiogroup" :aria-label="t('mode.label')" @mouseleave="clearPreview">
          <button
            v-for="m in modes"
            :key="m"
            type="button"
            class="mode-row"
            :class="{ active: current === m, reco: m === 'eco' }"
            role="radio"
            :aria-checked="current === m"
            @click="choose(m)"
            @mouseenter="previewMode(m)"
            @focus="previewMode(m)"
          >
            <span class="row-main">
              <span class="row-name">{{ t('mode.' + m) }}</span>
              <span v-if="m === 'eco'" class="reco-badge">{{ t('mode.recommended') }}</span>
            </span>
            <Icon v-if="current === m" name="check" :size="16" class="row-check" />
          </button>
        </div>

        <!-- Right: detail of the previewed/active mode (DSS detail-panel mood). -->
        <div class="mode-detail">
          <div class="detail-head">
            <span class="detail-name">{{ t('mode.' + detail) }}</span>
            <span v-if="detail === 'eco'" class="reco-badge">{{ t('mode.recommended') }}</span>
          </div>
          <p class="detail-desc">{{ t('mode.' + detail + '_desc') }}</p>
          <p v-if="detail === 'eco'" class="detail-reco">{{ t('mode.reco_line') }}</p>

          <div class="meters">
            <div class="meter-row">
              <span class="meter-label">{{ t('mode.cost_label') }}</span>
              <span class="meter5" aria-hidden="true">
                <i v-for="n in 5" :key="n" :class="{ on: n <= COST[detail] }" />
              </span>
              <span class="meter-val">{{ t('mode.' + detail + '_cost') }} ({{ COST[detail] }}/5)</span>
            </div>
            <div class="meter-row">
              <span class="meter-label">{{ t('mode.speed_label') }}</span>
              <span class="meter5" aria-hidden="true">
                <i v-for="n in 5" :key="n" :class="{ on: n <= SPEED[detail] }" />
              </span>
              <span class="meter-val">{{ t('mode.' + detail + '_speed') }} ({{ SPEED[detail] }}/5)</span>
            </div>
          </div>
        </div>
      </div>

      <p class="envelope">
        <Icon name="wallet" :size="15" class="envelope-ico" />
        <span>{{ t('mode.envelope_note') }}</span>
      </p>
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

/* Two-pane picker (list + detail), DSS "conversation settings" mood: sober,
   thin borders, square-ish corners, brand orange as the only accent. */
.picker { display: flex; gap: var(--s-4); align-items: stretch; }

.mode-list { flex: 0 0 200px; display: flex; flex-direction: column; gap: 6px; }
.mode-row {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  text-align: left; width: 100%; padding: 11px 12px;
  border: 1px solid var(--border); border-left: 3px solid transparent;
  border-radius: var(--r-sm); background: var(--surface);
  transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.mode-row:hover { background: var(--surface-hover); }
/* Recommended (eco) keeps a faint brand tint even when not selected. */
.mode-row.reco { border-color: var(--orange-soft-dark, var(--border)); }
/* Selected row: brand-orange left bar + tint (echoes the DSS selected item). */
.mode-row.active { border-color: var(--orange); border-left-color: var(--orange); background: var(--orange-soft-dark, var(--surface-2)); }
.row-main { display: inline-flex; align-items: center; gap: 8px; min-width: 0; }
.row-name { font-size: var(--fs-md); font-weight: 600; color: var(--text); }
.row-check { color: var(--orange-text); flex-shrink: 0; }
.reco-badge {
  font-size: 9px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  padding: 2px 7px; border-radius: var(--r-pill);
  background: var(--orange-soft-dark, rgba(255,121,0,0.12)); color: var(--orange-text);
  white-space: nowrap;
}

/* Detail panel */
.mode-detail {
  flex: 1; min-width: 0; padding: var(--s-4);
  border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--bg);
}
.detail-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.detail-name { font-size: var(--fs-lg); font-weight: 600; color: var(--text); letter-spacing: -0.01em; }
.detail-desc { font-size: var(--fs-sm); color: var(--text-2); line-height: 1.55; margin: 0; }
.detail-reco { font-size: var(--fs-sm); color: var(--orange-text); font-weight: 500; line-height: 1.5; margin: 8px 0 0; }

.meters { margin-top: 16px; display: flex; flex-direction: column; gap: 10px; }
.meter-row { display: flex; align-items: center; gap: 10px; }
.meter-label {
  flex: 0 0 54px; font-size: 11px; font-weight: 600; letter-spacing: 0.03em;
  text-transform: uppercase; color: var(--text-3);
}
.meter5 { display: inline-flex; gap: 4px; }
.meter5 i { width: 7px; height: 7px; border-radius: 50%; background: var(--border); }
.meter5 i.on { background: var(--text-2); }
.meter-val { font-size: var(--fs-xs); color: var(--text-2); }

/* Cost note: a quiet wallet cue, sober (no warning emoji). */
.envelope {
  display: flex; align-items: flex-start; gap: 8px;
  font-size: var(--fs-xs); color: var(--text-2); line-height: 1.5;
  margin: 18px 0 0; padding: 10px 12px; border-radius: var(--r-sm);
  background: var(--orange-soft-dark, rgba(255,121,0,0.10));
}
.envelope-ico { margin-top: 1px; color: var(--orange-text); }

@media (max-width: 560px) {
  .picker { flex-direction: column; }
  .mode-list { flex: 1 1 auto; }
}
</style>
