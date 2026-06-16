<script setup>
// Agent message — head, then the GROUPED activity block (the agent's reasoning/tool
// steps, ChatGPT-style: animated and expanded while running, auto-collapsed to one
// expandable header line on a terminal status), then the answer body items (text +
// errors, arrival order), then the collapsible generated-SQL panel and the action
// footer (copy / evidence / like / dislike / regenerate) + version navigation.
//
// The display model is the pure timeline reducer (composables/timelineModel.js); the
// activity/body split is done by its read-only selectors (timelineEvents /
// timelineBodyItems — the stored timeline stays chronological). Text blocks are the
// only v-html path (sanitized markdown, D7).
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '../../stores/chat.js'
import { useToasts } from '../../composables/useToasts.js'
import { renderMarkdown } from '../../composables/useMarkdown.js'
import {
  answerText,
  timelineEvents,
  timelineBodyItems,
  timelineSegments,
  activitySummary,
  stepStampDiff,
} from '../../composables/timelineModel.js'
import { resolveTimelineStep } from '../../registries/timelineSteps.js'
import { submitFeedback } from '../../services/backend.js'
import { useEvidenceStore } from '../../stores/evidence.js'
import { Icon, Menu } from '../ui'
import FeedbackModal from './FeedbackModal.vue'

const props = defineProps({
  turn: { type: Object, required: true },
})

const { t, locale } = useI18n()
const chat = useChatStore()
const { push } = useToasts()
const evidence = useEvidenceStore()

const showFeedback = ref(false)
// Which rating the detailed-feedback modal is editing (0 = negative, 1 = positive). Drives
// the modal's adaptive title/reasons/comment and the rating persisted on submit.
const feedbackMode = ref(0)

// The ⋯ "more options" menu — one entry that opens the detailed-feedback modal for the
// CURRENT rating (so a user can also add a comment to a 👍, not just a 👎).
const moreItems = computed(() => [{ key: 'feedback', label: t('msg.give_feedback'), icon: 'message' }])

// The active version of this turn = the version object on the turn's active exchange.
// Turn-level version navigation walks the exchange's SIBLINGS (branches), not in-memory
// answer versions: each sibling is one prompt version with its own answer.
const v = computed(() => props.turn.exchange.version)
const versionCount = computed(() => props.turn.siblings.length)
const versionIdx = computed(() => props.turn.versionIdx)

// Display model (pure selectors over the live timeline — items keep their ids, so
// v-for keys and the ChatThread scroll signature are unaffected, F13).
// LIVE: the timeline renders as chronological SEGMENTS — each phase of consecutive
// events is a bounded ticker (last LIVE_WINDOW lines, older ones fade out) and the
// agent's intermediate answers stay interleaved BETWEEN phases, exactly where they
// arrived. TERMINAL: all events regroup into one collapsed, expandable header line
// above the full answer (text blocks + errors in arrival order).
const LIVE_WINDOW = 5
const steps = computed(() => timelineEvents(v.value))
const bodyItems = computed(() => timelineBodyItems(v.value))
const segments = computed(() => timelineSegments(v.value))
const summary = computed(() => activitySummary(v.value))
const activityLive = computed(() => v.value.status === 'running')

// The bounded live window of one event phase (the fade-out of evicted lines is
// handled by the ticker's TransitionGroup + top mask).
function windowed(items) {
  return items.length > LIVE_WINDOW ? items.slice(-LIVE_WINDOW) : items
}

// The terminal dropdown starts collapsed; the watch force-collapses it when a LIVE
// run ends while this component is mounted. Sibling version switches REMOUNT the
// component (the v-for is keyed on exchange.uid, F12), so the fresh-mount initial
// value covers them.
const activityOpen = ref(false)
watch(activityLive, (live) => {
  if (!live) activityOpen.value = false
})

// Locale-aware duration ("0,4 s" in French, "0.4s" in English): durations are floats —
// raw `{{ x }}s` would leak the anglophone decimal dot. `fixed` pins 2 decimals so the
// live chronometer ticks with stable width (mono font, no jitter).
function fmtSeconds(s, fixed) {
  const opts = fixed ? { minimumFractionDigits: 2, maximumFractionDigits: 2 } : undefined
  return t('tl.seconds', [Number(s).toLocaleString(locale.value, opts)])
}

// --- Live per-step chronometer (purely presentational — the reducer stays pure) ----
// The RUNNING step ticks from its client arrival (seconds + hundredths). A SEALED
// step shows the backend emission-stamp gap (stepStampDiff) whenever stamps exist:
// stamps are the truth — immune to live-window eviction (a step sealed AND pushed
// out of the 5-line window in one poll flush is never re-rendered live), to poll
// quantization (a witnessed seal lands ≥ one ~500ms poll late) and to mid-run
// remounts (Settings round-trip), and consistent with the header total (same stamp
// source). The witnessed client clock is only the no-stamps fallback.
// Ticking is gated on chat.sending too: a superseded run whose version is stuck
// 'running' (cancelled polling never finalizes it) must not keep a zombie interval
// counting up forever.
const nowTick = ref(0)
let tickTimer = null
const stepClock = new Map() // item.id -> { start, end } (running steps witnessed live)
function startTicking() {
  if (tickTimer != null) return
  nowTick.value = performance.now()
  tickTimer = window.setInterval(() => {
    nowTick.value = performance.now()
  }, 100)
}
function stopTicking() {
  if (tickTimer != null) {
    window.clearInterval(tickTimer)
    tickTimer = null
  }
}
const ticking = computed(() => activityLive.value && chat.sending)
watch(ticking, (on) => (on ? startTicking() : stopTicking()), { immediate: true })
onBeforeUnmount(stopTicking)

// The step's displayed duration in seconds (null = nothing to show). Reading
// `nowTick` in the running branch is what makes the counter reactive.
function stepSeconds(item) {
  if (item.status === 'running') {
    let clock = stepClock.get(item.id)
    if (!clock) {
      clock = { start: performance.now(), end: null }
      stepClock.set(item.id, clock)
    }
    return Math.max(0, nowTick.value - clock.start) / 1000
  }
  // Sealed: backend stamps first (see block comment).
  const events = steps.value
  const diff = stepStampDiff(events, events.indexOf(item))
  if (diff != null) return diff
  // No usable stamps: freeze the witnessed client clock. Null when the step was
  // never witnessed running — better hidden than invented.
  const clock = stepClock.get(item.id)
  if (!clock) return null
  if (clock.end == null) clock.end = performance.now()
  return (clock.end - clock.start) / 1000
}

// Markdown memoized per item (id + exact text): the 10Hz chronometer re-render must
// not re-parse multi-KB intermediate answers between ticking phases on every tick.
const mdCache = new Map() // item.id -> { text, html }
function renderItem(item) {
  const hit = mdCache.get(item.id)
  if (hit && hit.text === item.text) return hit.html
  const html = renderMarkdown(item.text || '')
  mdCache.set(item.id, { text: item.text, html })
  return html
}

// Per-message evidence entry point: manual open ALWAYS works (degraded view
// included) — only the end-of-run auto-open is gated on availability.
const isEvidenceOpen = computed(
  () => evidence.open && evidence.exchangeId === v.value.exchangeId,
)
function openEvidence() {
  if (v.value.exchangeId) evidence.openForExchange(v.value.exchangeId)
}

// Whether this version produced any answer text at all.
const hasAnswerText = computed(() => v.value.timeline.some((it) => it.kind === 'text' && (it.text || '').length > 0))
// Terminal answer with NO text: stopped before any delta, OR a reloaded conversation whose
// stored answer is empty. Rendered as an honest "interrupted" placeholder (not an empty bubble).
const interruptedEmpty = computed(() => (v.value.status === 'done' || v.value.status === 'stopped') && !hasAnswerText.value)
// A user-interrupted answer that DID produce partial text: show the partial + a discreet
// "generation stopped" marker. Live-session only (the stopped state is not persisted, so a
// reload shows the partial text with no marker — consistent with storing it "as-is").
const stoppedWithText = computed(() => v.value.status === 'stopped' && hasAnswerText.value)

// Per-message token/cost usage line. Live: filled from the usage_summary event; reloaded:
// rebuilt from the persisted columns (usageFromRow). Shown only on a terminal version that
// actually carries usage — an early-stopped run (no footer) or a pre-usage exchange has
// none, so it shows no line rather than a misleading zero/empty one.
const usage = computed(() => v.value.usage)
const showUsage = computed(
  () =>
    v.value.status !== 'running' &&
    !!usage.value &&
    (usage.value.promptTokens != null ||
      usage.value.completionTokens != null ||
      usage.value.estimatedCost != null),
)
function fmtTokens(n) {
  return n == null ? '—' : Number(n).toLocaleString(locale.value)
}
function fmtCost(c) {
  // DSS-estimated cost; the user reasons in dollars. 2–4 decimals keeps the small
  // per-message amounts readable without collapsing to a misleading "$0.00".
  return (
    '$' +
    Number(c).toLocaleString(locale.value, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    })
  )
}

function stepLabel(item) {
  // Prefer the backend-provided human label (orchestrator pass-through) when present.
  const r = resolveTimelineStep(item.eventKind, item.label)
  return r.key ? t(r.key) : r.fallback
}
function stepSub(item) {
  return item.toolName || item.blockId || ''
}

async function copy() {
  const text = answerText(v.value)
  try {
    await navigator.clipboard.writeText(text)
    push(t('msg.copied'), { icon: 'check', tone: 'ok' })
  } catch (e) {
    push(t('msg.copy_failed'), { icon: 'alert', tone: 'warn' })
  }
}
// 👍/👎 are persisted server-side per exchange (owner-scoped) and colored from
// v.feedbackRating, so they survive a reload (unlike the UI-only version nav).
const isUp = computed(() => v.value.feedbackRating === 1)
const isDown = computed(() => v.value.feedbackRating === 0)

// Returns true only when the feedback was actually persisted, so callers can gate a
// success toast (it never rejects — failures surface here as a warn toast + false).
async function persistFeedback(rating, reasons, comment) {
  const ex = v.value.exchangeId
  if (!ex) return false // no exchange id yet (still running / not persisted)
  try {
    await submitFeedback(ex, rating, reasons, comment)
    v.value.feedbackRating = rating
    // Reasons only apply to a negative rating; the comment is kept for either rating (a 👍
    // can carry a "what you liked" note from the ⋯ modal). Clearing (null) wipes both.
    v.value.feedbackReasons = rating === 0 ? reasons : []
    v.value.feedbackComment = rating == null ? '' : comment
    return true
  } catch (e) {
    push(t('msg.feedback_failed'), { icon: 'alert', tone: 'warn' })
    return false
  }
}
function like() {
  // Re-click the active 👍 clears it; otherwise commit rating=1 IMMEDIATELY, no popup.
  if (isUp.value) {
    persistFeedback(null, [], '')
    return
  }
  persistFeedback(1, [], '')
}
function dislike() {
  // Re-click the active 👎 clears it; otherwise commit rating=0 IMMEDIATELY, then open the
  // reasons/comment popup (only once the commit succeeded, so we never prompt on a failure).
  if (isDown.value) {
    persistFeedback(null, [], '')
    return
  }
  persistFeedback(0, [], '').then((ok) => {
    if (ok) {
      feedbackMode.value = 0
      showFeedback.value = true
    }
  })
}
// ⋯ menu entry — open the detailed-feedback modal for the CURRENT rating (defaults to the
// positive/comment variant when no rating is set yet, so a 👍 can also gather a comment).
function openDetailedFeedback() {
  feedbackMode.value = v.value.feedbackRating === 0 ? 0 : 1
  showFeedback.value = true
}
function onMoreSelect(key) {
  if (key === 'feedback') openDetailedFeedback()
}
function onFeedbackSubmit(reasons, comment) {
  showFeedback.value = false
  // Persist with the rating the modal was opened for; the gated toast avoids a double toast
  // on failure (persistFeedback already surfaces the error toast and returns false — L031).
  persistFeedback(feedbackMode.value, reasons, comment).then((ok) => {
    if (ok) push(t('msg.feedback_sent'), { icon: 'check', tone: 'ok' })
  })
}
function regenerate() {
  chat.regenerateTurn(props.turn)
}
function prevVersion() {
  chat.setTurnVersion(props.turn, versionIdx.value - 1)
}
function nextVersion() {
  chat.setTurnVersion(props.turn, versionIdx.value + 1)
}
</script>

<template>
  <div class="msg agent u-no-shrink">
    <div class="head">
      <span class="ico"><Icon name="sparkle" /></span>
      <span class="author">{{ t('msg.author') }}</span>
    </div>

    <!-- ONE persistent .stream wrapper for both phases (swapping two sibling divs
         would replay its slide-up on the FULL answer at end of run).
         LIVE: chronological segments — each event phase is a bounded ticker (last
         LIVE_WINDOW lines, evicted lines fade out under the top mask) and the agent's
         intermediate answers render in place BETWEEN phases. Running step = grey with
         a traversing shimmer; finished steps = brand orange.
         TERMINAL: all events regroup into ONE collapsed, expandable header line above
         the full answer (count + total duration); text/errors keep arrival order. -->
    <div v-if="v.timeline.length" class="stream">
      <template v-if="activityLive">
        <template v-for="seg in segments" :key="seg.key">
          <div
            v-if="seg.kind === 'events'"
            class="ticker"
            :class="{ masked: seg.items.length > LIVE_WINDOW }"
          >
            <!-- `appear` so the FIRST line of a freshly mounted phase fades in too -->
            <TransitionGroup name="tick" appear>
              <div v-for="item in windowed(seg.items)" :key="item.id" class="step" :class="item.status">
                <span class="ind" />
                <span class="label">
                  <span class="title">{{ stepLabel(item) }}</span>
                  <span v-if="stepSub(item)" class="sub">{{ stepSub(item) }}</span>
                </span>
                <span v-if="stepSeconds(item) != null" class="dur">{{ fmtSeconds(stepSeconds(item), true) }}</span>
              </div>
            </TransitionGroup>
          </div>
          <!-- Live "what I'm doing now" narration (transient — only shown during
               the run; hidden in the terminal view below, never persisted). -->
          <div v-else-if="seg.kind === 'narration'" class="narration">
            <span class="narr-dot" aria-hidden="true" />
            <span class="narr-text">{{ seg.item.text }}</span>
          </div>
          <!-- Intermediate agent answer, exactly where it arrived (sanitized markdown) -->
          <div v-else-if="seg.kind === 'text'" class="body" v-html="renderItem(seg.item)" />
          <div v-else-if="seg.kind === 'error'" class="body error">— {{ seg.item.message }} —</div>
        </template>
      </template>
      <template v-else>
      <div v-if="steps.length" class="activity" :class="{ collapsed: !activityOpen }">
        <button
          type="button"
          class="act-head"
          :aria-expanded="activityOpen"
          @click="activityOpen = !activityOpen"
        >
          <span class="act-ind" />
          <span class="act-title">{{ t('tl.steps') }}</span>
          <span class="act-meta mono">
            {{ t('tl.steps_count', [summary.count]) }}<template v-if="summary.seconds != null"> · {{ fmtSeconds(summary.seconds) }}</template>
          </span>
          <span class="act-chev"><Icon :name="activityOpen ? 'chevronUp' : 'chevronDown'" /></span>
        </button>
        <!-- aria-hidden mirrors aria-expanded: the collapse is CSS-only (0fr + opacity),
             which never removes the rows from the accessibility tree by itself. -->
        <div class="act-steps-wrap" :aria-hidden="!activityOpen">
          <div class="act-steps">
            <div v-for="item in steps" :key="item.id" class="step" :class="item.status">
              <span class="ind" />
              <span class="label">
                <span class="title">{{ stepLabel(item) }}</span>
                <span v-if="stepSub(item)" class="sub">{{ stepSub(item) }}</span>
              </span>
              <span v-if="stepSeconds(item) != null" class="dur">{{ fmtSeconds(stepSeconds(item), true) }}</span>
            </div>
          </div>
        </div>
      </div>
      <template v-for="item in bodyItems" :key="item.id">
        <!-- Agent text block (sanitized markdown) -->
        <div v-if="item.kind === 'text'" class="body" v-html="renderItem(item)" />
        <!-- Error surfaced in place -->
        <div v-else-if="item.kind === 'error'" class="body error">— {{ item.message }} —</div>
      </template>
      </template>
    </div>

    <!-- Running with nothing emitted yet -->
    <div v-if="v.status === 'running' && !v.timeline.length" class="body thinking">
      {{ t('msg.executing') }}…
    </div>

    <!-- Stopped before any text: honest placeholder rather than an empty bubble (also
         covers reloading a conversation whose stored answer is empty). -->
    <div v-if="interruptedEmpty" class="body interrupted">{{ t('chat.interrupted_empty') }}</div>

    <!-- Discreet marker under a user-interrupted partial answer (live session only). -->
    <div v-else-if="stoppedWithText" class="stopped-marker">
      <Icon name="stop" /><span>{{ t('chat.stopped') }}</span>
    </div>

    <!-- Generated SQL (collapsible) -->
    <div v-if="v.sql.length" class="sql-panel">
      <button type="button" class="sql-toggle" @click="v.showSql = !v.showSql">
        <Icon :name="v.showSql ? 'chevronDown' : 'chevronRight'" />
        <span>{{ t('ev.tab.sql') }} ({{ v.sql.length }})</span>
      </button>
      <div v-if="v.showSql" class="sql-body">
        <div v-for="(q, k) in v.sql" :key="k" class="sql-item">
          <div class="sql-meta mono">
            <span>#{{ k + 1 }}</span>
            <span v-if="q.success != null">{{ t('ev.success') }}: {{ q.success }}</span>
            <span v-if="q.row_count != null">{{ t('ev.chip.rows') }}: {{ q.row_count }}</span>
          </div>
          <pre class="sql-code mono">{{ q.sql }}</pre>
        </div>
      </div>
    </div>

    <!-- Per-message token/cost usage (discreet, mono). Live + reloaded; shown to all. -->
    <div v-if="showUsage" class="usage-line mono">
      <span class="u-seg" :title="t('msg.usage_in')">↑ {{ fmtTokens(usage.promptTokens) }}</span>
      <span class="u-sep">·</span>
      <span class="u-seg" :title="t('msg.usage_out')">↓ {{ fmtTokens(usage.completionTokens) }}</span>
      <span class="u-unit">{{ t('msg.usage_tokens') }}</span>
      <template v-if="usage.estimatedCost != null">
        <span class="u-sep">·</span>
        <span class="u-seg" :title="t('msg.usage_cost')">~{{ fmtCost(usage.estimatedCost) }}</span>
      </template>
    </div>

    <!-- Actions + version nav -->
    <div v-if="v.status !== 'running'" class="msg-foot">
      <button @click="copy"><Icon name="copy" />{{ t('msg.copy') }}</button>
      <button
        v-if="v.sql.length && v.exchangeId"
        :class="{ primary: isEvidenceOpen }"
        :title="t('ev.open')"
        @click="openEvidence"
      ><Icon name="shield" />{{ t('ev.open') }}</button>
      <button :class="{ primary: isUp }" :title="t('msg.like')" @click="like"><Icon name="thumbsUp" /></button>
      <button :class="{ danger: isDown }" :title="t('msg.dislike')" @click="dislike"><Icon name="thumbsDown" /></button>
      <!-- ⋯ detailed feedback — works for either rating (comment a 👍 or a 👎). -->
      <Menu align="left" placement="top" :items="moreItems" @select="onMoreSelect">
        <template #trigger="{ toggle }">
          <button :title="t('msg.more_options')" @click="toggle"><Icon name="dots" /></button>
        </template>
      </Menu>
      <button :disabled="!chat.canSend" @click="regenerate"><Icon name="refresh" />{{ t('msg.regenerate') }}</button>

      <span v-if="versionCount > 1" class="ver-nav">
        <button :disabled="versionIdx === 0" :title="t('msg.prev_branch')" @click="prevVersion">
          <Icon name="chevronLeft" />
        </button>
        <span class="ver-count mono">{{ versionIdx + 1 }}/{{ versionCount }}</span>
        <button :disabled="versionIdx === versionCount - 1" :title="t('msg.next_branch')" @click="nextVersion">
          <Icon name="chevronRight" />
        </button>
      </span>
    </div>

    <!-- Adaptive feedback collector (reasons for 👎, comment-only for 👍). Persistence is
         handled by onFeedbackSubmit; the modal switches on the rating it was opened for. -->
    <FeedbackModal
      :open="showFeedback"
      :rating="feedbackMode"
      :initial-reasons="v.feedbackReasons"
      :initial-comment="v.feedbackComment"
      @submit="onFeedbackSubmit"
      @cancel="showFeedback = false"
    />
  </div>
</template>

<style scoped>
.msg { animation: slide-up var(--dur) var(--ease); }
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: var(--s-2);
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.head .ico { width: 18px; height: 18px; color: var(--orange); }
.head .ico :deep(.ui-icon) { width: 18px; height: 18px; }
.head .author { color: var(--text); font-weight: 500; font-size: var(--fs-sm); }

/* Body — typography for sanitized markdown (children are not scoped → :deep). */
.body { font-size: var(--fs-md); line-height: 1.7; color: var(--text); overflow-wrap: anywhere; }
/* Live narration — a muted "what I'm doing now" status line in the flow. Shown
   only during the run (the terminal view drops narration items entirely). */
.narration {
  display: flex; align-items: baseline; gap: 8px;
  font-size: var(--fs-sm); color: var(--text-3); line-height: 1.5;
  padding: 1px 0;
}
.narr-dot {
  flex: none; width: 6px; height: 6px; margin-top: 6px; border-radius: 50%;
  background: var(--orange); animation: narr-pulse 1.1s ease-in-out infinite;
}
.narr-text { overflow-wrap: anywhere; }
@keyframes narr-pulse { 0%, 100% { opacity: 0.35; } 50% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .narr-dot { animation: none; opacity: 0.7; } }
/* Waiting placeholder — same shimmer sweep as the live activity title. */
.body.thinking {
  color: var(--text-3);
  background: linear-gradient(90deg, var(--text-3) 25%, var(--text) 50%, var(--text-3) 75%);
  background-size: 200% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: shimmer-sweep 1.8s linear infinite;
}
.body.error { color: var(--danger); }
.body.interrupted { color: var(--text-3); font-style: italic; }
/* Discreet "generation stopped" marker under a partial answer. */
.stopped-marker { display: flex; align-items: center; gap: 6px; margin-top: var(--s-2); font-size: var(--fs-xs); color: var(--text-3); }
.stopped-marker :deep(.ui-icon) { width: 12px; height: 12px; }
.body :deep(h1), .body :deep(h2), .body :deep(h3) {
  font-size: var(--fs-lg); font-weight: 600; letter-spacing: -0.01em; margin: 0 0 var(--s-3);
}
.body :deep(h4) { font-size: var(--fs-md); font-weight: 600; margin: var(--s-5) 0 var(--s-2); }
.body :deep(h4:first-child) { margin-top: 0; }
.body :deep(p) { margin: 0 0 var(--s-3); }
.body :deep(p:last-child) { margin-bottom: 0; }
.body :deep(ul), .body :deep(ol) { margin: var(--s-2) 0 var(--s-3); padding-left: var(--s-5); }
.body :deep(li) { margin-bottom: 4px; }
.body :deep(strong) { font-weight: 600; }
.body :deep(a) { color: var(--orange); text-decoration: underline; text-underline-offset: 2px; }
.body :deep(code) {
  font-family: var(--font-mono); font-size: 0.92em;
  background: var(--surface-2); padding: 1px 5px; border-radius: 4px;
}
.body :deep(pre) {
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: var(--r-sm); padding: var(--s-3); overflow-x: auto; margin: 0 0 var(--s-3);
}
.body :deep(pre code) { background: none; padding: 0; }

/* Stream: the grouped activity block above, then answer text blocks in arrival order. */
.stream { display: flex; flex-direction: column; gap: 6px; animation: slide-up var(--dur) var(--ease); }
.stream .body { margin: 2px 0; }

/* --- Live ticker: one bounded window per event phase (max LIVE_WINDOW lines). --- */
.ticker { position: relative; display: flex; flex-direction: column; gap: 6px; padding: 2px 0; }
/* Once the phase overflows the window, the oldest visible line fades out under a
   top mask — the "older steps slip away" effect. */
.ticker.masked {
  -webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 26px);
  mask-image: linear-gradient(to bottom, transparent 0, #000 26px);
}
/* Window churn: new lines fade in from below, evicted lines fade out upward while
   the remaining ones glide up (leave-active is absolute so the column closes up). */
.tick-enter-from { opacity: 0; transform: translateY(6px); }
.tick-leave-to { opacity: 0; transform: translateY(-8px); }
.tick-enter-active, .tick-leave-active {
  transition: opacity var(--dur) var(--ease), transform var(--dur) var(--ease);
}
.tick-leave-active { position: absolute; left: 0; right: 0; }
/* A poll batch can evict SEVERAL head rows in one flush; absolutely-positioned flex
   children all resolve to the same static spot, so only the first one gets the fade —
   the extras vanish instantly instead of stacking as superposed text. */
.tick-leave-active + .tick-leave-active { transition: none; opacity: 0; }
.tick-move { transition: transform var(--dur) var(--ease); }
/* The TransitionGroup owns enter/leave — the mount keyframe would fight it. */
.ticker .step { animation: none; }

/* --- Terminal activity dropdown — one expandable header line. --- */
.activity { margin: 0 0 2px; }
.act-head {
  display: flex; align-items: center; gap: 8px; width: 100%; padding: 3px 0;
  font-size: var(--fs-sm); color: var(--text-2); text-align: left;
  transition: color var(--dur) var(--ease);
}
.act-head:hover { color: var(--text); }
.act-head:hover .act-chev { color: var(--text); }
.act-ind { width: 14px; height: 14px; position: relative; flex-shrink: 0; display: grid; place-items: center; }
/* Terminal state: brand-orange dot (the run finished — matches the done steps). */
.act-ind::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--orange); opacity: 0.9; }
.act-title {
  min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  color: var(--text-2); font-weight: 500;
}
.act-meta { font-size: 11px; color: var(--text-3); flex-shrink: 0; }
.act-chev { color: var(--text-3); display: grid; place-items: center; transition: color var(--dur) var(--ease); }
.act-chev :deep(.ui-icon) { width: 14px; height: 14px; }

/* Collapse/expand: the 0fr->1fr grid-row trick animates height without magic numbers
   (browsers without fr-row transitions just snap — the final state is identical). */
.act-steps-wrap {
  display: grid; grid-template-rows: 1fr;
  transition: grid-template-rows var(--dur-slow) var(--ease);
}
.activity.collapsed .act-steps-wrap { grid-template-rows: 0fr; }
.act-steps {
  overflow: hidden; min-height: 0;
  display: flex; flex-direction: column; gap: 6px;
  padding: 4px 0 2px 22px; /* indented under the header indicator */
  transition: opacity var(--dur-slow) var(--ease);
}
.activity.collapsed .act-steps { opacity: 0; }

/* Individual steps (live ticker + terminal dropdown).
   RUNNING = grey, with a shimmer traversing the label ("we are here").
   DONE = brand orange ("this is finished"). */
.step {
  display: flex; align-items: center; gap: 10px; font-size: var(--fs-sm);
  color: var(--text-2); padding: 2px 0;
  animation: step-in var(--dur-slow) var(--ease) both;
}
@keyframes step-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: none; }
}
.step .ind { width: 12px; height: 12px; position: relative; flex-shrink: 0; display: grid; place-items: center; }
/* --text-2 (not --text-3): the grey dot/ring must clear the 3:1 non-text contrast
   guideline on a white background in light theme. */
.step.running .ind::before {
  content: ""; width: 6px; height: 6px; background: var(--text-2); border-radius: 50%;
  animation: pulse-dot 1.2s ease-in-out infinite;
}
/* Expanding ripple ring around the running step's dot (intensity up/down). */
.step.running .ind::after {
  content: ""; position: absolute; inset: 0; border-radius: 50%;
  border: 1.5px solid var(--text-2);
  animation: act-ripple 1.5s ease-out infinite;
}
@keyframes act-ripple {
  from { transform: scale(0.4); opacity: 0.7; }
  to { transform: scale(1.5); opacity: 0; }
}
.step.done .ind::before { content: ""; width: 5px; height: 5px; background: var(--orange); border-radius: 50%; opacity: 0.9; }
.step .label { flex: 1; min-width: 0; display: flex; align-items: baseline; gap: 8px; }
.step .label .title { color: var(--text); }
/* Grey running label with the traversing shimmer sweep. */
.step.running .label .title {
  font-weight: 500;
  color: var(--text-3);
  background: linear-gradient(90deg, var(--text-3) 25%, var(--text) 50%, var(--text-3) 75%);
  background-size: 200% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: shimmer-sweep 1.8s linear infinite;
}
/* Finished: brand orange in the live ticker (--orange-text is the AA-contrast text
   variant per theme); the terminal dropdown keeps neutral titles (orange dots carry
   the state) so a long expanded list stays readable. */
.ticker .step.done .label .title { color: var(--orange-text); }
.act-steps .step.done .label .title { color: var(--text-2); }
.step .label .sub { color: var(--text-3); font-family: var(--font-mono); font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.step .dur { font-family: var(--font-mono); font-size: 11px; color: var(--text-3); }

@media (prefers-reduced-motion: reduce) {
  .msg, .stream,
  .step.running .ind::before,
  .step.running .label .title,
  .body.thinking,
  .step { animation: none; }
  /* The ripple ring has NO resting state (its whole look lives in the keyframes):
     animation:none would freeze it as a permanent opaque ring — remove it instead. */
  .step.running .ind::after { content: none; }
  .act-steps-wrap, .act-steps,
  .tick-enter-active, .tick-leave-active, .tick-move { transition: none; }
}

/* SQL panel */
.sql-panel { margin-top: var(--s-4); border: 1px solid var(--border); border-radius: var(--r-sm); overflow: hidden; }
.sql-toggle {
  display: flex; align-items: center; gap: 6px; width: 100%; padding: 8px 12px;
  font-size: var(--fs-sm); color: var(--text-2); background: var(--surface);
  transition: color var(--dur) var(--ease);
}
.sql-toggle:hover { color: var(--text); }
.sql-toggle :deep(.ui-icon) { width: 14px; height: 14px; }
.sql-body { padding: var(--s-3); display: flex; flex-direction: column; gap: var(--s-3); }
.sql-meta { display: flex; gap: var(--s-3); font-size: 11px; color: var(--text-3); }
.sql-code {
  margin: 6px 0 0; padding: var(--s-3); background: var(--surface-2); border-radius: var(--r-sm);
  font-size: 12.5px; line-height: 1.65; color: var(--text); overflow-x: auto; white-space: pre;
}

/* Per-message token/cost usage line — discreet, neutral, mono (like the activity meta). */
.usage-line {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  margin-top: var(--s-3); font-size: 11px; color: var(--text-3);
}
.usage-line .u-sep { opacity: 0.55; }
.usage-line .u-unit { color: var(--text-3); }

/* Footer actions */
.msg-foot { display: flex; align-items: center; gap: var(--s-2); margin-top: var(--s-4); font-size: var(--fs-xs); color: var(--text-3); }
.msg-foot button {
  display: inline-flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: var(--r-sm);
  font-size: var(--fs-xs); color: var(--text-2); transition: all var(--dur) var(--ease);
}
.msg-foot button:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
.msg-foot button:disabled { opacity: 0.4; cursor: not-allowed; }
.msg-foot button :deep(.ui-icon) { width: 13px; height: 13px; }
.msg-foot button.primary { color: var(--orange); font-weight: 500; }
.msg-foot button.danger { color: var(--danger); font-weight: 500; }
.ver-nav { display: inline-flex; align-items: center; gap: 2px; margin-left: var(--s-2); }
.ver-count { font-size: 11px; color: var(--text-3); padding: 0 2px; }
</style>
