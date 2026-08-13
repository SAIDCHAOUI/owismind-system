<script setup>
// Scroll affordances overlaying a data table. A wide table cuts its columns at the
// viewport edge and a long one cuts its rows at the bottom, with nothing on screen saying
// so: a first-time user reads the visible slice as the whole dataset. These pills SAY it
// (how many columns are still on the right, that rows continue below) and DO it (one
// click scrolls there).
//
// Purely presentational: the host table owns the scroll container, measures it with
// composables/useScrollHints.js and calls the scroll steps on these events. Shared by
// SourceTable, EvidenceTable and ArtifactTable so the three tables speak one language.
//
// The layer is click-through (pointer-events: none) except on the pills themselves, so a
// row or cell click landing outside a pill is never intercepted. It stays BELOW --z-menu
// so any open popover / column menu paints over it, and it never sets a transform on the
// layer itself (that would make it a stacking context, the trap documented in
// SourceChips.vue).
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Icon } from '../ui'

const props = defineProps({
  // More columns to the left / right, more rows below (from useScrollHints).
  canLeft: { type: Boolean, default: false },
  canRight: { type: Boolean, default: false },
  canDown: { type: Boolean, default: false },
  // How many columns are still cut off past the right edge (0 hides the count).
  hiddenRight: { type: Number, default: 0 },
})
defineEmits(['left', 'right', 'down'])

const { t } = useI18n()

// The count is the message, but it can legitimately be 0 (the only thing left past the
// edge is the 1px column sentinel, not a column): say "more columns" rather than "0 more
// columns". Never announce a number the table cannot show.
const rightLabel = computed(() =>
  props.hiddenRight > 0 ? t('tbl.more_cols', [props.hiddenRight]) : t('tbl.more_cols_any'),
)
</script>

<template>
  <div class="sh-layer">
    <!-- Left: back to the first columns. No count - "how many are behind me" is not
         what the eye asks on the way back, only "take me home". -->
    <Transition name="sh">
      <button
        v-if="canLeft"
        type="button"
        class="sh-pill sh-left"
        :title="t('tbl.back_cols')"
        :aria-label="t('tbl.back_cols')"
        @click="$emit('left')"
      >
        <Icon name="chevronsLeft" />
      </button>
    </Transition>
    <!-- A 1px rule on the cut edge: the frame says "the table ends here", this hairline
         says "the DATA does not". Paired with the pill, never alone. -->
    <Transition name="sh">
      <span v-if="canLeft" class="sh-edge sh-edge-left" aria-hidden="true" />
    </Transition>

    <!-- Right: the count is the message. "3" is instantly readable as three more
         columns waiting, where a lone chevron only reads as "something, maybe". -->
    <Transition name="sh">
      <button
        v-if="canRight"
        type="button"
        class="sh-pill sh-right"
        :title="rightLabel"
        :aria-label="rightLabel"
        @click="$emit('right')"
      >
        <Icon name="chevronsRight" />
        <span v-if="hiddenRight > 0" class="sh-count mono">{{ hiddenRight }}</span>
      </button>
    </Transition>
    <Transition name="sh">
      <span v-if="canRight" class="sh-edge sh-edge-right" aria-hidden="true" />
    </Transition>

    <!-- Bottom: rows continue. Slim, centered, breathing - it invites without shouting
         over the data it sits on. -->
    <Transition name="sh">
      <button
        v-if="canDown"
        type="button"
        class="sh-pill sh-down"
        :title="t('tbl.more_rows')"
        :aria-label="t('tbl.more_rows')"
        @click="$emit('down')"
      >
        <Icon name="chevronDown" class="sh-beat" />
      </button>
    </Transition>
  </div>
</template>

<style scoped>
/* Above the sticky header (z-index 1) and the rows, below the chips block (z-index 5)
   and every floating menu (--z-menu): the affordance guides, it never blocks. */
.sh-layer { position: absolute; inset: 0; pointer-events: none; z-index: 3; }

/* Floating pill (premium 2026-08-13): rounded, flat fill, 1px filet, layered elevation.
   No gradient, no glow - the elevation alone lifts it off the rows. */
.sh-pill {
  position: absolute; pointer-events: auto;
  display: inline-flex; align-items: center; gap: 5px;
  padding: 6px 11px;
  border: 1px solid var(--text-3); border-radius: var(--r-pill);
  background: var(--bg); color: var(--text);
  box-shadow: var(--elev-2);
  transition: color var(--dur) var(--ease), border-color var(--dur) var(--ease),
    background var(--dur) var(--ease);
}
.sh-pill:hover { border-color: var(--text); background: var(--surface); }
.sh-pill:focus-visible { outline: none; border-color: var(--orange); }
.sh-pill :deep(.ui-icon) { width: 15px; height: 15px; display: block; flex: none; }
/* The count carries the message: ink, heavy, mono (a figure, charte). */
.sh-count { font-size: 12px; font-weight: var(--fw-heavy); color: var(--text); line-height: 1; }

.sh-left { left: 8px; top: 50%; transform: translateY(-50%); }
.sh-right { right: 8px; top: 50%; transform: translateY(-50%); }
.sh-down { left: 50%; bottom: 8px; transform: translateX(-50%); padding: 4px 14px; }

/* Cut-edge hairline - quiet, full height, purely decorative. */
.sh-edge { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--border-strong); }
.sh-edge-left { left: 0; }
.sh-edge-right { right: 0; }

/* The down chevron breathes so "there is more below" reads even out of the corner of
   the eye. Opacity only (no movement, no layout). */
.sh-beat { animation: sh-beat 1.8s ease-in-out infinite; }
@keyframes sh-beat {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}

/* Appear softly, leave fast: an affordance that vanishes must not linger in the way. */
.sh-enter-active { transition: opacity var(--dur) var(--ease); }
.sh-leave-active { transition: opacity var(--dur-fast) var(--ease); }
.sh-enter-from, .sh-leave-to { opacity: 0; }

@media (prefers-reduced-motion: reduce) {
  .sh-pill { transition: none; }
  .sh-beat { animation: none; }
  .sh-enter-active, .sh-leave-active { transition: none; }
}
</style>
