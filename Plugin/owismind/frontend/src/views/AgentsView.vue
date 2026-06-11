<script setup>
// Agents page (Phase 3) — list + detail in one view, switched on the optional
// :agentId route param (the backend's opaque logical key, never an agent_id).
//
// The LIST is always the backend's enabled agents (session.agents, source of
// truth). Each is ENRICHED by the local agentMeta registry when its label
// matches; unknown agents get a generic, honest card with NO invented
// capabilities/tools. The detail CTA preselects the agent and jumps to /chat.
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useSessionStore } from '../stores/session.js'
import { useTr } from '../composables/useTr.js'
import { resolveAgentMeta } from '../registries/agentMeta.js'
import { PageShell, EmptyState } from '../components/pages'
import { Icon, Button } from '../components/ui'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const tr = useTr()
const session = useSessionStore()

// Backend agents (source of truth) merged with optional registry metadata.
const cards = computed(() =>
  session.agents.map((a) => {
    const meta = resolveAgentMeta(a.label)
    return {
      key: a.key,
      name: a.label,
      icon: meta?.icon || 'robot',
      badge: meta?.badge || '',
      tagline: meta ? tr(meta.tagline) : t('ag.generic_tagline'),
      desc: meta ? tr(meta.desc) : t('ag.generic_desc'),
      bullets: meta ? meta.bullets.map((b) => tr(b)) : [],
      tools: meta?.tools || [],
      hasMeta: !!meta,
    }
  }),
)

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
</script>

<template>
  <!-- LIST -->
  <PageShell v-if="!selectedId" wide :eyebrow="t('ag.eyebrow')" :title="t('ag.title')" :desc="t('ag.desc')">
    <EmptyState v-if="!cards.length" bordered icon="agents" :title="t('ag.no_agents')" />
    <div v-else class="agents-grid">
      <button v-for="c in cards" :key="c.key" class="agent-card" type="button" @click="openAgent(c.key)">
        <div class="agent-card-top">
          <span class="ico-circle"><Icon :name="c.icon" /></span>
          <span v-if="c.badge" class="bdg" :class="c.badge">{{ c.badge }}</span>
        </div>
        <div class="agent-card-name">{{ c.name }}</div>
        <div class="agent-card-tagline">{{ c.tagline }}</div>
        <div class="agent-card-desc">{{ c.desc }}</div>
        <div class="agent-card-foot">
          <span class="tools-ct mono">{{ t('ag.tools_count', [c.tools.length]) }}</span>
          <span class="open-ico"><Icon name="chevronRight" /></span>
        </div>
      </button>
    </div>
  </PageShell>

  <!-- DETAIL -->
  <PageShell v-else wide>
    <button class="back-link" type="button" @click="backToList">
      <Icon name="arrowLeft" /><span>{{ t('ag.back') }}</span>
    </button>

    <template v-if="selected">
      <div class="agent-hero">
        <span class="agent-hero-ico"><Icon :name="selected.icon" /></span>
        <div class="agent-hero-text">
          <div class="agent-hero-row">
            <h1 class="agent-hero-name">{{ selected.name }}</h1>
            <span v-if="selected.badge" class="bdg" :class="selected.badge">{{ selected.badge }}</span>
          </div>
          <p class="agent-hero-tagline">{{ selected.tagline }}</p>
        </div>
      </div>

      <p class="agent-desc-block">{{ selected.desc }}</p>

      <!-- Capabilities + tools only for documented agents (no invented content) -->
      <div v-if="selected.hasMeta" class="agent-doc-grid">
        <section class="agent-doc-col">
          <div class="agent-doc-title">{{ t('ag.capabilities') }}</div>
          <ul class="agent-bullets">
            <li v-for="(b, i) in selected.bullets" :key="i">
              <span class="ic"><Icon name="check" /></span><span>{{ b }}</span>
            </li>
          </ul>
        </section>
        <section class="agent-doc-col">
          <div class="agent-doc-title">{{ t('ag.tools') }}</div>
          <div v-if="selected.tools.length" class="tool-chips">
            <span v-for="tname in selected.tools" :key="tname" class="tool-chip mono">{{ tname }}</span>
          </div>
          <p v-else class="doc-empty">{{ t('ag.tools_section_empty') }}</p>
        </section>
      </div>

      <div class="agent-cta-row">
        <Button variant="primary" icon="message" @click="startConversation(selected)">
          {{ t('ag.new_conv_with', [selected.name]) }}
        </Button>
      </div>
    </template>

    <EmptyState v-else bordered icon="agents" :title="t('ag.no_agents')" />
  </PageShell>
</template>

<style scoped>
/* --- List grid --- */
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
.ico-circle {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--orange-soft-dark);
  color: var(--orange);
}
.ico-circle :deep(.ui-icon) { width: 16px; height: 16px; }
.agent-card-name { font-size: var(--fs-lg); font-weight: 600; letter-spacing: -0.015em; color: var(--text); }
.agent-card-tagline { font-size: var(--fs-xs); color: var(--orange); font-weight: 500; margin-top: -6px; }
.agent-card-desc { font-size: var(--fs-sm); color: var(--text-2); line-height: 1.55; flex: 1; }
.agent-card-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  margin-top: 4px;
}
.tools-ct { font-size: 11px; color: var(--text-3); }
.open-ico { color: var(--text-3); }
.open-ico :deep(.ui-icon) { width: 14px; height: 14px; }

/* --- Badges (shared list + detail) --- */
.bdg {
  font-size: 9px;
  letter-spacing: 0.06em;
  padding: 2px 8px;
  border-radius: var(--r-pill);
  font-weight: 700;
  text-transform: uppercase;
}
.bdg.default { background: var(--orange-soft-dark); color: var(--orange); }
.bdg.new { background: var(--orange); color: #fff; }
.bdg.beta { background: var(--surface-2); color: var(--text-2); }

/* --- Detail --- */
.back-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--fs-xs);
  color: var(--text-2);
  margin-bottom: var(--s-5);
  padding: 4px 8px 4px 4px;
  border-radius: var(--r-sm);
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.back-link:hover { background: var(--surface-hover); color: var(--text); }
.back-link :deep(.ui-icon) { width: 15px; height: 15px; }

.agent-hero {
  display: flex;
  align-items: center;
  gap: var(--s-4);
  margin-bottom: var(--s-4);
}
.agent-hero-ico {
  width: 56px;
  height: 56px;
  flex-shrink: 0;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--orange-soft-dark);
  color: var(--orange);
}
.agent-hero-ico :deep(.ui-icon) { width: 22px; height: 22px; }
.agent-hero-row { display: flex; align-items: center; gap: 10px; }
.agent-hero-name { font-size: var(--fs-3xl); font-weight: 600; letter-spacing: -0.03em; margin: 0; line-height: 1.1; }
.agent-hero-row .bdg { font-size: 10px; padding: 3px 9px; }
.agent-hero-tagline { font-size: var(--fs-md); color: var(--text-2); margin: 4px 0 0; }

.agent-desc-block {
  font-size: var(--fs-md);
  color: var(--text);
  line-height: 1.65;
  margin: 0 0 var(--s-7);
  padding: var(--s-5);
  background: var(--surface);
  border-radius: var(--r);
  border-left: 3px solid var(--orange);
}

.agent-doc-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s-5);
  margin-bottom: var(--s-7);
}
.agent-doc-col { padding: var(--s-5); border: 1px solid var(--border); border-radius: var(--r); }
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
.tool-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.tool-chip {
  font-size: 11.5px;
  padding: 4px 9px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
}
.doc-empty { font-size: var(--fs-sm); color: var(--text-3); margin: 0; }
.agent-cta-row { display: flex; gap: var(--s-3); }

@media (max-width: 760px) {
  .agents-grid { grid-template-columns: 1fr; }
  .agent-doc-grid { grid-template-columns: 1fr; }
}
</style>
