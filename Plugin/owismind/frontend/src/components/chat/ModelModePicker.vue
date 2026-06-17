<script setup>
// Model-mode picker — a small pill showing the current mode that opens an
// EXPLANATORY popup (Modal) where the user picks Éco / Medium / High. The popup
// spells out what each mode is and what it implies: more powerful = better
// understanding/analysis but higher cost, which burns the €50/month envelope
// faster. Goal: make the cost trade-off conscious so High is used only on complex
// queries. The choice is a per-turn preference (ui store); backend defaults to eco.
//   eco = Gemini 3.1 Flash-Lite (default) · medium = Gemini 3.5 Flash · high = Claude Sonnet.
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useUiStore, MODEL_MODES } from '../../stores/ui.js'
import Modal from '../ui/Modal.vue'

const { t } = useI18n()
const ui = useUiStore()

const open = ref(false)
const current = computed(() => ui.modelMode)
const modes = MODEL_MODES // ['eco', 'medium', 'high']
// Visual cost meter per mode (1..3 filled marks).
const COST_LEVEL = { eco: 1, medium: 2, high: 3 }

function choose(m) {
  ui.setModelMode(m)
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
      <span class="dot" :class="'lvl-' + COST_LEVEL[current]" aria-hidden="true" />
      <span class="mode-name">{{ t('mode.' + current) }}</span>
    </button>

    <Modal v-model="open" :title="t('mode.modal_title')" icon="sparkles" max-width="520px">
      <p class="intro">{{ t('mode.modal_intro') }}</p>
      <div class="cards" role="radiogroup" :aria-label="t('mode.label')">
        <button
          v-for="m in modes"
          :key="m"
          type="button"
          class="card"
          :class="{ active: current === m }"
          role="radio"
          :aria-checked="current === m"
          @click="choose(m)"
        >
          <div class="card-head">
            <span class="card-name">{{ t('mode.' + m) }}</span>
            <span v-if="m === 'eco'" class="badge">{{ t('mode.recommended') }}</span>
            <span v-if="current === m" class="badge current">{{ t('mode.current') }}</span>
          </div>
          <p class="card-desc">{{ t('mode.' + m + '_desc') }}</p>
          <div class="card-cost">
            <span class="meter" aria-hidden="true">
              <i v-for="n in 3" :key="n" :class="{ on: n <= COST_LEVEL[m], hi: m === 'high' }" />
            </span>
            <span class="cost-label">{{ t('mode.' + m + '_cost') }}</span>
          </div>
        </button>
      </div>
      <p class="envelope">{{ t('mode.envelope_note') }}</p>
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
.mode-trigger .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.dot.lvl-1 { background: var(--text-3); }
.dot.lvl-2 { background: var(--orange); }
.dot.lvl-3 { background: #ef4444; }

/* Modal body */
.intro { font-size: var(--fs-sm); color: var(--text-2); margin: 0 0 16px; line-height: 1.5; }
.cards { display: flex; flex-direction: column; gap: 10px; }
.card {
  text-align: left; padding: 12px 14px; border-radius: var(--r-md, 12px);
  border: 1.5px solid var(--border); background: var(--surface);
  transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.card:hover { border-color: var(--border-strong); background: var(--surface-hover); }
.card.active { border-color: var(--orange); background: var(--orange-soft, var(--surface-2)); }
.card-head { display: flex; align-items: center; gap: 8px; }
.card-name { font-size: var(--fs-md); font-weight: 600; color: var(--text); }
.badge {
  font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: var(--r-pill);
  background: var(--orange-soft-dark, rgba(255,122,0,0.14)); color: var(--orange-text);
}
.badge.current { background: var(--surface-2); color: var(--text-3); }
.card-desc { font-size: var(--fs-sm); color: var(--text-2); margin: 6px 0 10px; line-height: 1.45; }
.card-cost { display: flex; align-items: center; gap: 8px; }
.meter { display: inline-flex; gap: 3px; }
.meter i { width: 14px; height: 5px; border-radius: 2px; background: var(--border); }
.meter i.on { background: var(--orange); }
.meter i.on.hi { background: #ef4444; }
.cost-label { font-size: var(--fs-xs); color: var(--text-3); }
.envelope {
  font-size: var(--fs-xs); color: var(--text-2); line-height: 1.5;
  margin: 18px 0 0; padding: 10px 12px; border-radius: var(--r-sm);
  background: var(--orange-soft-dark, rgba(255,122,0,0.10));
}
</style>
