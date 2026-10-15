<script setup>
// Agents library - list + detail in one view, switched on the optional :agentId
// route param (the backend's opaque logical key, never a raw agent_id).
//
// The list AND every profile come from the backend (session.agents): an admin
// authors each agent's tagline / description / capabilities / tools / icon / badge
// in the admin console, and it is stored with the enabled-agents whitelist. There is
// NO hardcoded copy here - an agent whose profile an admin has not filled in shows an
// honest, minimal card (never invented capabilities). The detail CTA preselects the
// agent and jumps to /chat.
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useSessionStore } from '../stores/session.js'
import { PageShell, EmptyState } from '../components/pages'
import { Icon, Button } from '../components/ui'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const session = useSessionStore()

const query = ref('')

// Backend agents (source of truth) shaped for display. Profiles are admin-authored;
// missing fields degrade to honest fallbacks, never invented content.
const cards = computed(() =>
  session.agents.map((a) => ({
    key: a.key,
    name: a.label,
    icon: a.icon || 'robot',
    badge: a.badge || '',
    tagline: a.tagline || '',
    desc: a.description || '',
    capabilities: Array.isArray(a.capabilities) ? a.capabilities : [],
    tools: Array.isArray(a.tools) ? a.tools : [],
    hasProfile: !!(a.tagline || a.description || (a.capabilities && a.capabilities.length)),
  })),
)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return cards.value
  return cards.value.filter((c) =>
    [c.name, c.tagline, c.desc].some((s) => (s || '').toLowerCase().includes(q)),
  )
})

const selectedId = computed(() => route.params.agentId || '')
const selected = computed(() => cards.value.find((c) => c.key === selectedId.value) || null)

function openAgent(key) {
  router.push('/agents/' + encodeURIComponent(key))
}
function backToList() {
  router.push('/agents')
}
function startConversation(card) {
  session.selectAgent(card.key)
  router.push('/chat')
}
// Entry point into the Help & Support hub's "Request an agent" tab (a new agent on
// data, guided form). See views/HelpSupportView.vue.
function requestAgent() {
  router.push('/support?tab=agent')
}
function badgeLabel(b) {
  return b ? t('ag.badge.' + b) : ''
}
</script>

<template>
  <!-- ============================== LIST ============================== -->
  <PageShell v-if="!selectedId" wide :eyebrow="t('ag.eyebrow')" :title="t('ag.title')" :desc="t('ag.desc')">
    <div class="ag-actions-row u-rise">
      <Button variant="ghost" icon="userPlus" @click="requestAgent">{{ t('ag.request_agent') }}</Button>
    </div>

    <EmptyState v-if="!cards.length" bordered icon="bookOpen" :title="t('ag.no_agents')" />

    <template v-else>
      <!-- Search + count -->
      <div class="ag-toolbar u-rise">
        <div class="ag-search">
          <Icon name="search" />
          <input v-model="query" type="text" :placeholder="t('ag.search')" :aria-label="t('ag.search')" />
        </div>
        <span class="ag-count mono">{{ t('ag.count', [filtered.length]) }}</span>
      </div>

      <p v-if="!filtered.length" class="ag-no-match">{{ t('ag.no_match', [query]) }}</p>

      <div v-else class="agents-grid">
        <button
          v-for="(c, i) in filtered"
          :key="c.key"
          class="agent-card u-rise"
          :style="{ animationDelay: Math.min(i * 45, 270) + 'ms' }"
          type="button"
          @click="openAgent(c.key)"
        >
          <div class="agent-card-top">
            <span class="ico-tile"><Icon :name="c.icon" :size="20" /></span>
            <span v-if="c.badge" class="bdg" :class="c.badge">{{ badgeLabel(c.badge) }}</span>
          </div>
          <div class="agent-card-name">{{ c.name }}</div>
          <div v-if="c.tagline" class="agent-card-tagline">{{ c.tagline }}</div>
          <div class="agent-card-desc">{{ c.desc || t('ag.meta_missing') }}</div>
          <div class="agent-card-foot">
            <span v-if="c.tools.length" class="foot-meta">
              <Icon name="tool" />{{ t('ag.tools_count', [c.tools.length]) }}
            </span>
            <span v-else class="foot-meta foot-meta--muted">{{ t('ag.open') }}</span>
            <span class="open-ico"><Icon name="chevronRight" /></span>
          </div>
        </button>
      </div>
    </template>
  </PageShell>

  <!-- ============================== DETAIL ============================== -->
  <PageShell v-else wide>
    <button class="back-link" type="button" @click="backToList">
      <Icon name="arrowLeft" /><span>{{ t('ag.back') }}</span>
    </button>

    <template v-if="selected">
      <header class="agent-hero u-rise">
        <span class="agent-hero-ico"><Icon :name="selected.icon" :size="28" /></span>
        <div class="agent-hero-text">
          <div class="agent-hero-row">
            <h1 class="agent-hero-name">{{ selected.name }}</h1>
            <span v-if="selected.badge" class="bdg" :class="selected.badge">{{ badgeLabel(selected.badge) }}</span>
          </div>
          <p v-if="selected.tagline" class="agent-hero-tagline">{{ selected.tagline }}</p>
        </div>
      </header>

      <p class="agent-lead u-rise">{{ selected.desc || t('ag.meta_missing') }}</p>

      <!-- Capabilities + tools: only what an admin actually authored (no invented copy) -->
      <div v-if="selected.capabilities.length || selected.tools.length" class="agent-doc-grid u-rise">
        <section v-if="selected.capabilities.length" class="agent-doc-col">
          <div class="agent-doc-title">{{ t('ag.capabilities') }}</div>
          <ul class="agent-bullets">
            <li v-for="(b, i) in selected.capabilities" :key="i">
              <span class="ic"><Icon name="check" /></span><span>{{ b }}</span>
            </li>
          </ul>
        </section>
        <section v-if="selected.tools.length" class="agent-doc-col">
          <div class="agent-doc-title">{{ t('ag.tools') }}</div>
          <div class="tool-chips">
            <span v-for="tname in selected.tools" :key="tname" class="tool-chip mono">{{ tname }}</span>
          </div>
        </section>
      </div>

      <div class="agent-cta-row">
        <Button variant="primary" icon="message" @click="startConversation(selected)">
          {{ t('ag.start') }}
        </Button>
      </div>
    </template>

    <EmptyState v-else bordered icon="bookOpen" :title="t('ag.no_agents')" />
  </PageShell>
</template>

<style scoped>
/* =============================================================================
 * AgentsView styles - Orange brand, premium pass (user decision 2026-08-13).
 *
 * Rules: soft radius on the interactive surfaces (cards --r-lg, search + chips
 * --r-pill, icon tiles --r), hairline borders carrying the structure, layered
 * elevation (--elev-1 at rest, --elev-2 on hover) instead of hard frames, orange
 * still a RARE accent. No gradients, no blur, no glow, no color-mix.
 * ============================================================================= */

/* --- Actions row (Request an agent CTA, above the toolbar/grid) ---------- */
.ag-actions-row {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--s-6);
  animation-delay: 40ms;
}

/* --- Toolbar (search + count) ------------------------------------------- */
.ag-toolbar {
  display: flex;
  align-items: center;
  gap: var(--s-4);
  margin: var(--s-7) 0 22px;
  animation-delay: 80ms;
}

/* Search bar: pill, hairline border. Focus lifts the field (elevation + a border
   step) rather than ringing it in orange - same language as the prompt card. */
.ag-search {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  padding: 12px 18px;
  border: 1px solid var(--border);
  border-radius: var(--r-pill);
  background: var(--bg);
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.ag-search:hover { border-color: var(--border-strong); }
.ag-search:focus-within {
  border-color: var(--text-3);
  box-shadow: var(--elev-1);
}
:global(body[data-theme="dark"] .ag-search) { background: var(--surface); }
.ag-search :deep(.ui-icon) { width: 16px; height: 16px; color: var(--text-3); flex-shrink: 0; }
.ag-search input {
  border: none;
  background: none;
  outline: none;
  width: 100%;
  font-size: var(--fs-base);
  font-family: var(--font-sans);
  color: var(--text);
}
.ag-search input::placeholder { color: var(--text-3); }

/* Count note: monospaced, muted. */
.ag-count {
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  color: var(--text-3);
  white-space: nowrap;
}
.ag-no-match { font-size: var(--fs-sm); color: var(--text-2); padding: var(--s-6) 0; }

/* --- Cards grid --------------------------------------------------------- */
/* Auto-fill so columns respond naturally without a fixed count. */
.agents-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--s-4);
}

/* Each card is ONE pressable object: soft radius, hairline frame, a resting
   shadow that deepens as the card lifts under the pointer. */
.agent-card {
  display: flex;
  flex-direction: column;
  padding: 22px;
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  background: var(--bg);
  box-shadow: var(--elev-1);
  text-align: left;
  cursor: pointer;
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease),
    transform var(--dur) var(--ease);
}
.agent-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--elev-2);
  transform: translateY(-2px);
}
.agent-card:active { transform: translateY(0); }
/* Card-level hover choreography: the icon tile warms up with the card and the foot
   chevron slides forward - every part answers the same pointer. */
.agent-card:hover .ico-tile { border-color: var(--border-strong); background: var(--surface); }
.agent-card:hover .open-ico { transform: translateX(3px); color: var(--text); }
.agent-card:focus-visible { outline: 2px solid var(--orange); outline-offset: 2px; }
/* Dark canvas: the card steps one surface level above the page (a same-color card
   would vanish, and a shadow alone does not read on black). */
:global(body[data-theme="dark"] .agent-card) {
  background: var(--surface-2);
  border-color: var(--border-strong);
}
:global(body[data-theme="dark"] .agent-card:hover) { border-color: var(--text-3); }

.agent-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

/* Icon tile: softly rounded, hairline frame, orange glyph, no tinted fill. */
.ico-tile {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: var(--r);
  display: grid;
  place-items: center;
  background: var(--bg);
  color: var(--orange);
  transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.ico-tile :deep(.ui-icon) { width: 20px; height: 20px; }
:global(body[data-theme="dark"] .ico-tile) { background: var(--surface); border-color: var(--border-strong); }
:global(body[data-theme="dark"] .agent-card:hover .ico-tile) { background: var(--surface-hover); }

/* Agent name: 16px/800 - editorial weight. */
.agent-card-name {
  font-size: 16px;
  font-weight: var(--fw-heavy);
  color: var(--text);
  line-height: 1.25;
  display: block;
  margin-top: 14px;
}

/* Tagline: orange accent text (AA-safe token), bold. */
.agent-card-tagline {
  font-size: var(--fs-sm);
  color: var(--orange-text);
  font-weight: var(--fw-bold);
  margin-top: 8px;
}

.agent-card-desc {
  font-size: var(--fs-base);
  color: var(--text-2);
  line-height: 1.55;
  flex: 1;
  margin-top: 6px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* Card foot: tools count + chevron. Square, 1px top border. */
.agent-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.foot-meta {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.foot-meta :deep(.ui-icon) { width: 15px; height: 15px; }
.foot-meta--muted { color: var(--text-3); }
.open-ico {
  display: inline-flex;
  color: var(--text-3);
  transition: transform var(--dur) var(--ease), color var(--dur) var(--ease);
}
.open-ico :deep(.ui-icon) { width: 15px; height: 15px; }

/* --- Badges (shared list + detail) -------------------------------------- */
/* Pill caps: a badge is a chip, and chips are pills in the premium language. */
.bdg {
  font-size: 10px;
  letter-spacing: var(--tracking-eyebrow);
  padding: 3px 9px;
  border-radius: var(--r-pill);
  font-weight: var(--fw-heavy);
  text-transform: uppercase;
  white-space: nowrap;
}
.bdg.default { background: var(--orange); color: #fff; }
.bdg.new { background: var(--orange); color: #fff; }
.bdg.beta { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border-strong); }

/* --- Detail ------------------------------------------------------------- */
/* Back link: quiet pill target; the arrow steps back on hover. */
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 14px 6px 10px;
  border-radius: var(--r-pill);
  font-size: var(--fs-base);
  font-weight: var(--fw-semibold);
  color: var(--text-2);
  margin-bottom: 24px;
  transition: color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.back-link:hover { color: var(--text); background: var(--surface-hover); }
.back-link:focus-visible { outline: 2px solid var(--orange); outline-offset: 2px; }
.back-link :deep(.ui-icon) {
  width: 16px;
  height: 16px;
  transition: transform var(--dur) var(--ease);
}
.back-link:hover :deep(.ui-icon) { transform: translateX(-2px); }

/* Detail header: large icon tile + name + tagline. */
.agent-hero {
  display: flex;
  align-items: center;
  gap: 18px;
  margin-bottom: var(--s-6);
}

/* Large icon tile: 56px, softly rounded, orange glyph. */
.agent-hero-ico {
  width: 56px;
  height: 56px;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  display: grid;
  place-items: center;
  background: var(--bg);
  box-shadow: var(--elev-1);
  color: var(--orange);
}
:global(body[data-theme="dark"] .agent-hero-ico) {
  background: var(--surface-2);
  border-color: var(--border-strong);
}
.agent-hero-ico :deep(.ui-icon) { width: 28px; height: 28px; }

.agent-hero-text { flex: 1; min-width: 0; }
.agent-hero-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 0; }

/* Detail h1: large heavy. */
.agent-hero-name {
  font-size: var(--fs-2xl);
  font-weight: var(--fw-heavy);
  letter-spacing: var(--tracking-tight);
  margin: 0;
  line-height: 1.1;
  color: var(--text);
}
.agent-hero-row .bdg { font-size: 10px; padding: 2px 6px; }

/* Tagline under name: orange accent text. */
.agent-hero-tagline {
  font-size: var(--fs-base);
  color: var(--orange-text);
  font-weight: var(--fw-bold);
  margin: 6px 0 0;
}

/* Description paragraph under the hero. Staggered behind the hero on entry. */
.agent-lead {
  font-size: var(--fs-md);
  color: var(--text);
  line-height: 1.6;
  margin: 22px 0 28px;
  max-width: 760px;
  animation-delay: 60ms;
}

/* Two-column doc grid (capabilities + tools). */
.agent-doc-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s-5);
  margin-bottom: var(--s-8);
  align-items: start;
  animation-delay: 120ms;
}

/* Each section card: soft radius, hairline frame, resting elevation. */
.agent-doc-col {
  padding: var(--s-5);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  background: var(--bg);
  box-shadow: var(--elev-1);
}
:global(body[data-theme="dark"] .agent-doc-col) {
  background: var(--surface-2);
  border-color: var(--border-strong);
}

/* Section title: uppercase micro-label, muted. */
.agent-doc-title {
  font-size: 11px;
  letter-spacing: var(--tracking-eyebrow);
  text-transform: uppercase;
  color: var(--text-2);
  font-weight: var(--fw-heavy);
  margin-bottom: var(--s-4);
}

/* Capability list: orange check icon per item. */
.agent-bullets { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 10px; }
.agent-bullets li { display: flex; align-items: flex-start; gap: 10px; font-size: var(--fs-base); line-height: 1.5; color: var(--text); }
.agent-bullets .ic { color: var(--orange); flex-shrink: 0; margin-top: 2px; }
.agent-bullets .ic :deep(.ui-icon) { width: 16px; height: 16px; }

/* Tool chips: pill caps, hairline frame, monospaced. */
.tool-chips { display: flex; flex-wrap: wrap; gap: 8px; }
.tool-chip {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: var(--fw-semibold);
  padding: 5px 12px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-pill);
  color: var(--text);
}
:global(body[data-theme="dark"] .tool-chip) { border-color: var(--border-strong); }

.agent-cta-row { display: flex; gap: var(--s-3); margin-top: var(--s-4); }

@media (max-width: 760px) {
  .agents-grid { grid-template-columns: 1fr; }
  .agent-doc-grid { grid-template-columns: 1fr; }
  .agent-hero-name { font-size: var(--fs-xl); }
}

/* Honor reduced-motion: colors and elevation still respond, nothing MOVES. */
@media (prefers-reduced-motion: reduce) {
  .agent-card {
    transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
  }
  .agent-card:hover, .agent-card:active { transform: none; }
  .open-ico { transition: color var(--dur) var(--ease); }
  .agent-card:hover .open-ico { transform: none; }
  .back-link :deep(.ui-icon) { transition: none; }
  .back-link:hover :deep(.ui-icon) { transform: none; }
}
</style>
