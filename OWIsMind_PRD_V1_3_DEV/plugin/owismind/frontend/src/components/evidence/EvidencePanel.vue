<script setup>
// Evidence Studio panel - the RIGHT column that opens after a generation: the
// trust surface (trust badge + sources + filter chips + calculation steps +
// captured agent result + live rows of the matched source table + the agent's
// raw SQL). All data lives in the evidence store; this component only renders
// its states (loading / error / degraded / interactive).
//
// TABS: a tab bar is shown at the top of the body when the interactive view is
// available (an exchange-scoped "Sources" data explorer) and/or meta.artifacts
// carries chart / table / kpi artifacts. Switching tabs ONLY updates
// evidence.activeTab - it MUST NOT change evidence.open (the ChatThread scroll
// gate checks open, F13).
import { computed, defineAsyncComponent, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEvidenceStore } from '../../stores/evidence.js'
import { useChatStore } from '../../stores/chat.js'
import { useSessionStore } from '../../stores/session.js'
import { Icon } from '../ui'
import Tabs from '../ui/Tabs.vue'
import EvidenceTrust from './EvidenceTrust.vue'
import EvidenceSources from './EvidenceSources.vue'
import EvidenceCalc from './EvidenceCalc.vue'
import EvidenceResult from './EvidenceResult.vue'
import EvidenceSourcesTab from './EvidenceSourcesTab.vue'
import EvidenceSql from './EvidenceSql.vue'
// Async on purpose: ArtifactChart pulls in the whole chart.js library (~40% of the
// entry bundle), and its render is already gated behind the Chart tab v-else-if, so
// Vite splits it into a lazy chunk fetched on the first chart instead of at boot.
const ArtifactChart = defineAsyncComponent(() => import('./ArtifactChart.vue'))
import ArtifactTable from './ArtifactTable.vue'
import ArtifactKpi from './ArtifactKpi.vue'

const { t } = useI18n()
const evidence = useEvidenceStore()
const chat = useChatStore()
const session = useSessionStore()
const meta = computed(() => evidence.meta)

// The interactive view (rows table + chips + drill) is available: this gates both
// the "Sources" tab entry and its body, exactly like the pre-tab explore block.
const available = computed(() => !!(meta.value && meta.value.available))

// The agent's CONFIGURED source datasets for this exchange: they open the Source
// data tab even when the turn produced NO SQL (user ask 2026-08-13) - browsing the
// agent's datasets never needed a captured query. Same resolution as the tab itself.
const agentSources = computed(() => {
  const key = chat.agentKeyForExchange(evidence.exchangeId)
  if (!key) return []
  const a = session.agents.find((x) => x.key === key)
  return a && Array.isArray(a.sources) ? a.sources : []
})

// Marker of the ENRICHED trust-layer contract: a v1 meta (no verification
// block) must render pixel-identical to today - no badge, no extra labels.
// The proof sections gate themselves on their own optional meta fields.
const enriched = computed(() => !!(meta.value && meta.value.verification))

// Degraded mode shows WHY the interactive view is unavailable. With best-effort
// SQL mapping the remaining reasons are "the agent's table maps to no SQL
// dataset in this project" or "no usable SQL"; anything rarer (unparseable
// text, multiple statements) falls back to the generic message.
const DEGRADED_KEYS = {
  no_matching_dataset: 'ev.degraded.no_dataset',
  no_sql: 'ev.degraded.no_sql',
  no_successful_sql: 'ev.degraded.no_sql',
}
const degradedMessage = computed(() => {
  const reason = meta.value && meta.value.reason
  const key = DEGRADED_KEYS[reason]
  return key ? t(key) : t('ev.degraded')
})

// ── Artifact tab logic ────────────────────────────────────────────────────────
// Derive the visible tab list from meta.artifacts. 'evidence' is always present.
// 'chart' / 'table' tabs are added only when the corresponding artifact kind exists.
// Switching tabs MUST NOT touch `evidence.open` (F13: scroll gate).
const artifacts = computed(() => {
  const arts = meta.value && Array.isArray(meta.value.artifacts) ? meta.value.artifacts : []
  return arts
})

const tabItems = computed(() => {
  // Reading order (user ask 2026-08-13): the proof first, then the rendered artifacts
  // (KPI / chart / table) when the turn produced any, and the Source data explorer LAST.
  const items = [{ key: 'evidence', label: t('art.tab.evidence') }]
  const seen = new Set()
  for (const art of artifacts.value) {
    if ((art.kind === 'kpi' || art.kind === 'chart' || art.kind === 'table') && !seen.has(art.kind)) {
      seen.add(art.kind)
      items.push({ key: art.kind, label: t('art.tab.' + art.kind) })
    }
  }
  // 'Sources' hosts the exchange-scoped rows explorer (chips + drill + table) AND the
  // agent-mode dataset explorer. It appears when the interactive view is available OR
  // the agent exposes configured datasets: a SQL-less answer still lets the user open
  // and browse the source data (user ask 2026-08-13).
  if (available.value || agentSources.value.length) items.push({ key: 'sources', label: t('ev.tab.sources') })
  return items
})

// Show the tab bar only when there are extra tabs beyond 'evidence'.
const showTabs = computed(() => tabItems.value.length > 1)

// ALL chart artifacts (the 'chart' tab stacks them: a turn may render one
// chart per scenario, each with its own server-built data payload).
const chartArtifacts = computed(() => artifacts.value.filter((a) => a.kind === 'chart'))

// ALL KPI artifacts (the 'kpi' tab stacks the cards).
const kpiArtifacts = computed(() => artifacts.value.filter((a) => a.kind === 'kpi'))

// The table artifact spec (first one): the table tab renders meta.result, the
// spec only contributes its optional title / description caption.
const tableArtifact = computed(() =>
  artifacts.value.find((a) => a.kind === 'table') || null,
)

// Active tab model - bound to the store so it resets correctly on exchange change.
const activeTab = computed({
  get: () => evidence.activeTab || 'evidence',
  set: (key) => evidence.setActiveTab(key),
})

// Tab guard: the active tab must always EXIST in the offered list (a caller may land
// the panel on 'sources' before meta proves the exchange degraded AND source-less).
// Falling back to 'evidence' keeps the panel honest instead of rendering a ghost tab.
watch([tabItems, activeTab], ([items, tab]) => {
  if (meta.value && !items.some((i) => i.key === tab)) activeTab.value = 'evidence'
})
</script>

<template>
  <aside class="evidence">
    <header class="ev-head">
      <div class="ev-title">
        <Icon name="shield" />
        <span>{{ t('ev.title') }}</span>
        <span v-if="meta && meta.dataset" class="ev-dataset mono">{{ meta.dataset }}</span>
      </div>
      <div class="ev-actions">
        <button class="ev-close" :title="t('ev.close')" @click="evidence.close()">
          <Icon name="x" />
        </button>
      </div>
    </header>

    <!-- Tab bar - shown only when the backend returned chart / table artifacts.
         Switching tabs MUST NOT change `evidence.open` (F13 scroll gate):
         v-model is wired to evidence.activeTab via the computed setter above. -->
    <Tabs
      v-if="showTabs && meta && !evidence.loading && !evidence.error"
      v-model="activeTab"
      :items="tabItems"
      class="ev-tabs"
    />

    <div class="ev-body" :class="{ 'ev-body--fill': activeTab === 'sources' }">
      <!-- Meta loading: shimmer skeleton shaped like the upcoming content
           (trust banner + chips row + table block) instead of a bare text line. -->
      <div v-if="evidence.loading" class="ev-skeleton" :aria-label="t('ev.loading')">
        <span class="sk sk-band" />
        <div class="sk-chips">
          <span v-for="n in 3" :key="n" class="sk sk-chip" />
        </div>
        <div class="sk sk-table" />
      </div>
      <div v-else-if="evidence.error" class="ev-state error">{{ t('ev.error') }}</div>
      <!-- Degraded (no captured SQL): the proof tab shows the honest "declared" badge
           above the reason - but the SOURCE DATA tab stays reachable whenever the
           agent exposes configured datasets (user ask 2026-08-13): browsing the data
           never needed a captured query. -->
      <template v-else-if="meta && !meta.available">
        <template v-if="activeTab === 'sources' && agentSources.length">
          <EvidenceSourcesTab />
        </template>
        <template v-else>
          <EvidenceTrust />
          <div class="ev-state">{{ degradedMessage }}</div>
        </template>
      </template>
      <template v-else-if="meta">
        <!-- ── KPI TAB ────────────────────────────────────────────────────── -->
        <template v-if="activeTab === 'kpi' && kpiArtifacts.length">
          <div class="art-stack">
            <ArtifactKpi
              v-for="(art, i) in kpiArtifacts"
              :key="'kpi-' + i"
              :data="art.data || null"
              :title="art.title || ''"
              :unit="(art.kpi && art.kpi.unit) || ''"
              :description="art.description || ''"
            />
          </div>
        </template>

        <!-- ── CHART TAB ──────────────────────────────────────────────────── -->
        <template v-else-if="activeTab === 'chart' && chartArtifacts.length">
          <div class="art-stack">
            <ArtifactChart
              v-for="(art, i) in chartArtifacts"
              :key="'chart-' + i"
              :chart="art.chart"
              :data="art.data || null"
              :title="art.title || ''"
              :description="art.description || ''"
            />
          </div>
        </template>

        <!-- ── TABLE TAB ──────────────────────────────────────────────────── -->
        <!-- A bound table artifact carries its own result block (data); the
             legacy/unbound case falls back to the exchange-level meta.result. -->
        <template v-else-if="activeTab === 'table'">
          <ArtifactTable
            :result="(tableArtifact && tableArtifact.data) || meta.result || null"
            :title="(tableArtifact && tableArtifact.title) || ''"
            :description="(tableArtifact && tableArtifact.description) || ''"
          />
        </template>

        <!-- ── SOURCES TAB ───────────────────────────────────────────────── -->
        <!-- The unified "Source data" explorer: a single selector merging the
             exchange's detected tables (legacy: agent chips + drill + search + the
             live rows table) with the agent's extra configured datasets (the
             standalone explorer). Drilling a result row on the Evidence tab lands
             here (evidence.drillIntoResultRow switches the tab). -->
        <template v-else-if="activeTab === 'sources'">
          <EvidenceSourcesTab />
        </template>

        <!-- ── EVIDENCE TAB (default) ────────────────────────────────────── -->
        <!-- Proof sections, most business-readable first (spec §6). Each section
             gates itself on its own OPTIONAL meta field, so a v1 meta renders the
             same proof stack. The filter chips + live rows table live in the
             Sources tab; EvidenceResult's drill chevrons switch to it on click. -->
        <template v-else>
          <EvidenceTrust v-if="enriched" />
          <EvidenceSources />
          <EvidenceCalc />
          <EvidenceResult />
        </template>
      </template>
    </div>

    <EvidenceSql v-if="meta && meta.sql" :sql="meta.sql" />
  </aside>
</template>

<style scoped>
.evidence {
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  background: var(--bg);
  animation: ev-slide-in var(--dur-slow) var(--ease) both;
}
/* The panel docks on the RIGHT - it slides in from the right edge. */
@keyframes ev-slide-in {
  from { opacity: 0; transform: translateX(28px); }
  to { opacity: 1; transform: none; }
}
/* Staggered content reveal: the header rises first, then each body block (the
   skeleton while loading, then chips and table when the meta lands - the v-if
   swap re-runs the animation, so loaded content fades in over the skeleton). */
/* Tab bar - flush to the header border, inheriting the panel's horizontal padding.
   The Tabs primitive draws its own border-bottom; no extra border here. */
.ev-tabs {
  padding: 0 var(--s-5);
  flex: none;
}
/* The shared Tabs.vue primitive draws a plain orange rule under the active tab; the
   panel restyles it HERE (charte rule: never touch Tabs.vue). Every tab owns a
   collapsed underline that SCALES OUT from the left when it becomes active - the
   indicator draws itself in instead of blinking. */
.ev-tabs :deep(.ui-tab)::after {
  content: "";
  position: absolute;
  left: 0;
  right: var(--s-4);
  bottom: -1px;
  height: 2px;
  background: var(--orange);
  transform: scaleX(0);
  transform-origin: left center;
  transition: transform var(--dur) var(--ease-out), background var(--dur) var(--ease);
}
/* The active state restates the geometry it shares with the primitive (height,
   background) so the outcome never depends on stylesheet order. */
.ev-tabs :deep(.ui-tab.is-active)::after {
  height: 2px;
  background: var(--orange);
  transform: scaleX(1);
}
/* Hovering an inactive tab previews the underline in ink, never in orange (the orange
   rule stays the mark of the ACTIVE tab). */
.ev-tabs :deep(.ui-tab:not(.is-active):hover)::after {
  background: var(--text-3);
  transform: scaleX(1);
}
@media (prefers-reduced-motion: reduce) {
  .ev-tabs :deep(.ui-tab)::after { transition: none; }
}
/* Vertical stack of artifacts of one kind (several charts / KPI cards). */
.art-stack {
  display: flex;
  flex-direction: column;
  gap: var(--s-6);
}
.ev-head { animation: ev-rise var(--dur-slow) var(--ease) both; }
/* True stagger: each proof section arrives a beat after the one above it, so the panel
   reads top-down instead of landing as one block. Capped past the 5th child - a longer
   ladder would make the last section feel late. */
.ev-body > * { animation: ev-rise var(--dur-slow) var(--ease-out) both; }
.ev-body > *:nth-child(2) { animation-delay: 60ms; }
.ev-body > *:nth-child(3) { animation-delay: 120ms; }
.ev-body > *:nth-child(4) { animation-delay: 180ms; }
.ev-body > *:nth-child(n + 5) { animation-delay: 240ms; }
@keyframes ev-rise {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: none; }
}
/* Meta-loading skeleton - flat surface blocks with an opacity pulse. No gradient
   (charte), and the same idiom as every other data skeleton in the app. */
.ev-skeleton { display: flex; flex-direction: column; gap: var(--s-4); flex: 1; min-height: 0; }
/* The placeholders preview the SHAPE the content will take, so the loaded blocks land
   exactly where the skeleton stood: pill chips, square bands and table. */
.sk {
  display: block; border-radius: 0;
  background: var(--surface-2);
  animation: ev-sk-pulse 1.4s ease-in-out infinite;
}
@keyframes ev-sk-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
.sk-chips { display: flex; gap: var(--s-2); }
.sk-band { width: 65%; height: 24px; }
.sk-chip { width: 110px; height: 28px; border-radius: var(--r-pill); }
.sk-table { flex: 1; min-height: 220px; }
@media (prefers-reduced-motion: reduce) {
  .evidence, .ev-head, .ev-body > *, .sk { animation: none; }
}
.ev-head {
  display: flex; align-items: center; justify-content: space-between;
  /* Same fixed height as the chat topbar (.main-top: 56px) so the two bottom
     hairlines meet as ONE continuous line across the whole app (user ask). */
  height: 56px; flex-shrink: 0;
  padding: 0 var(--s-5); border-bottom: 1px solid var(--border);
}
.ev-title { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: var(--fs-md); }
.ev-title :deep(.ui-icon) { width: 16px; height: 16px; color: var(--orange); }
.ev-dataset { font-size: 11px; color: var(--text-3); font-weight: 400; }
.ev-actions { display: flex; align-items: center; gap: var(--s-3); }
/* Rounded icon button (premium 2026-08-13), matching the Source Data dock header. */
.ev-close {
  display: inline-flex; padding: 6px; border-radius: var(--r-pill);
  color: var(--text-3); transition: all var(--dur) var(--ease);
}
.ev-close:hover { background: var(--surface-hover); color: var(--text); }
.ev-close :deep(.ui-icon) { width: 16px; height: 16px; }
.ev-body {
  flex: 1; min-height: 0; overflow-y: auto;
  display: flex; flex-direction: column; gap: var(--s-4); padding: var(--s-5);
}
/* Sources tab: the tab content fills the panel and the rows table owns the only
   scroll (no double scrollbar). The body itself stops scrolling; its single flex
   child (EvidenceSourcesTab) grows to fill and manages its own overflow. */
.ev-body--fill { overflow: hidden; }
.ev-state { color: var(--text-3); font-size: var(--fs-sm); }
.ev-state.error { color: var(--danger); }
</style>
