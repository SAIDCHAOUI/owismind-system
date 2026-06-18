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
function badgeLabel(b) {
  return b ? t('ag.badge.' + b) : ''
}
</script>

<template>
  <!-- ============================== LIST ============================== -->
  <PageShell v-if="!selectedId" wide :eyebrow="t('ag.eyebrow')" :title="t('ag.title')" :desc="t('ag.desc')">
    <EmptyState v-if="!cards.length" bordered icon="bookOpen" :title="t('ag.no_agents')" />

    <template v-else>
      <!-- Search + count -->
      <div class="ag-toolbar">
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
            <span class="ico-square"><Icon :name="c.icon" :size="20" /></span>
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

      <p class="agent-lead">{{ selected.desc || t('ag.meta_missing') }}</p>

      <!-- Capabilities + tools: only what an admin actually authored (no invented copy) -->
      <div v-if="selected.capabilities.length || selected.tools.length" class="agent-doc-grid">
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
/* --- Toolbar (search + count) ------------------------------------------- */
.ag-toolbar {
  display: flex;
  align-items: center;
  gap: var(--s-4);
  margin-bottom: var(--s-5);
}
.ag-search {
  display: flex;
  align-items: center;
  gap: 9px;
  flex: 1;
  padding: 10px 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r);
  background: var(--bg);
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.ag-search:focus-within { border-color: var(--orange); box-shadow: 0 0 0 2px var(--orange-soft-dark); }
.ag-search :deep(.ui-icon) { width: 17px; height: 17px; color: var(--text-3); flex-shrink: 0; }
.ag-search input {
  border: none;
  background: none;
  outline: none;
  width: 100%;
  font-size: var(--fs-sm);
  color: var(--text);
}
.ag-search input::placeholder { color: var(--text-3); }
.ag-count { font-size: var(--fs-xs); color: var(--text-3); white-space: nowrap; }
.ag-no-match { font-size: var(--fs-sm); color: var(--text-2); padding: var(--s-6) 0; }

/* --- Cards grid --------------------------------------------------------- */
.agents-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--s-4);
}
.agent-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: var(--s-5);
  border: 1px solid var(--border);
  border-radius: var(--r);
  background: var(--bg);
  text-align: left;
  cursor: pointer;
  transition: border-color var(--dur) var(--ease), transform var(--dur) var(--ease),
    box-shadow var(--dur) var(--ease);
}
.agent-card:hover {
  border-color: var(--border-strong);
  transform: translateY(-1px);
  box-shadow: var(--shadow);
}
.agent-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
/* Square icon chip (a light orange-soft accent, squared per the brand). */
.ico-square {
  width: 38px;
  height: 38px;
  border-radius: var(--r-sm);
  display: grid;
  place-items: center;
  background: var(--orange-soft-dark);
  color: var(--orange);
}
.ico-square :deep(.ui-icon) { width: 19px; height: 19px; }
.agent-card-name {
  font-size: var(--fs-lg);
  font-weight: 600;
  letter-spacing: -0.015em;
  color: var(--text);
  line-height: 1.25;
}
.agent-card-tagline {
  font-size: var(--fs-xs);
  color: var(--orange);
  font-weight: 500;
  margin-top: -4px;
}
.agent-card-desc {
  font-size: var(--fs-sm);
  color: var(--text-2);
  line-height: 1.55;
  flex: 1;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.agent-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 12px;
  border-top: 1px solid var(--border);
  margin-top: 4px;
}
.foot-meta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-xs);
  color: var(--text-3);
  font-weight: var(--fw-medium);
}
.foot-meta :deep(.ui-icon) { width: 13px; height: 13px; }
.foot-meta--muted { font-weight: var(--fw-regular); }
.open-ico { color: var(--text-3); display: inline-flex; transition: transform var(--dur) var(--ease), color var(--dur) var(--ease); }
.agent-card:hover .open-ico { color: var(--orange); transform: translateX(2px); }
.open-ico :deep(.ui-icon) { width: 15px; height: 15px; }

/* --- Badges (shared list + detail) -------------------------------------- */
.bdg {
  font-size: 9.5px;
  letter-spacing: 0.06em;
  padding: 3px 8px;
  border-radius: var(--r-xs);
  font-weight: 700;
  text-transform: uppercase;
  white-space: nowrap;
}
.bdg.default { background: var(--orange-soft-dark); color: var(--orange); }
.bdg.new { background: var(--orange); color: #fff; }
.bdg.beta { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border); }

/* --- Detail ------------------------------------------------------------- */
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-sm);
  font-weight: var(--fw-medium);
  color: var(--text-2);
  margin-bottom: var(--s-6);
  padding: 5px 10px 5px 6px;
  border-radius: var(--r-sm);
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.back-link:hover { background: var(--surface-hover); color: var(--text); }
.back-link :deep(.ui-icon) { width: 16px; height: 16px; }

.agent-hero {
  display: flex;
  align-items: center;
  gap: var(--s-5);
  margin-bottom: var(--s-6);
}
/* Agent identity chip: a squared orange-soft accent (flat, no glow). */
.agent-hero-ico {
  width: 56px;
  height: 56px;
  flex-shrink: 0;
  border-radius: var(--r);
  display: grid;
  place-items: center;
  background: var(--orange-soft-dark);
  color: var(--orange);
}
.agent-hero-ico :deep(.ui-icon) { width: 26px; height: 26px; }
.agent-hero-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.agent-hero-name {
  font-size: var(--fs-3xl);
  font-weight: 700;
  letter-spacing: -0.03em;
  margin: 0;
  line-height: 1.05;
  color: var(--text);
}
.agent-hero-row .bdg { font-size: 10px; padding: 3px 9px; }
.agent-hero-tagline {
  font-size: var(--fs-md);
  color: var(--orange);
  font-weight: 500;
  margin: 8px 0 0;
}

.agent-lead {
  font-size: var(--fs-lg);
  color: var(--text);
  line-height: 1.6;
  margin: 0 0 var(--s-8);
  max-width: 760px;
  font-weight: var(--fw-regular);
}

.agent-doc-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s-5);
  margin-bottom: var(--s-8);
  align-items: start;
}
.agent-doc-col { padding: var(--s-5); border: 1px solid var(--border); border-radius: var(--r); background: var(--bg); }
.agent-doc-title {
  font-size: 11px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-3);
  font-weight: 600;
  margin-bottom: var(--s-3);
}
.agent-bullets { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 10px; }
.agent-bullets li { display: flex; align-items: flex-start; gap: 10px; font-size: var(--fs-sm); line-height: 1.5; color: var(--text); }
.agent-bullets .ic { color: var(--orange); flex-shrink: 0; margin-top: 1px; }
.agent-bullets .ic :deep(.ui-icon) { width: 15px; height: 15px; }
.tool-chips { display: flex; flex-wrap: wrap; gap: 7px; }
.tool-chip {
  font-size: 11.5px;
  padding: 5px 10px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  color: var(--text);
}
.agent-cta-row { display: flex; gap: var(--s-3); }

@media (max-width: 760px) {
  .agents-grid { grid-template-columns: 1fr; }
  .agent-doc-grid { grid-template-columns: 1fr; }
  .agent-hero-name { font-size: var(--fs-3xl); }
}
/* Honor reduced-motion for positional movement too (not just the entrance fade). */
@media (prefers-reduced-motion: reduce) {
  .agent-card:hover { transform: none; }
  .agent-card:hover .open-ico { transform: none; }
}
</style>
