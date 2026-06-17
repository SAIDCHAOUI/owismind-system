<script setup>
// Sidebar - brand, primary nav, lazy conversation list, and the foot account/help
// menus. Visual spec ported from `.sidebar` / `.side-item` / `.conv-item` /
// `.user-chip` (components.css). Navigation via vue-router; conversations come from
// the session store, which pages names-only from /conversations (the full thread of
// one session is fetched from /conversation on click); menus reuse the <Menu> primitive.
import { computed, ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useSessionStore } from '../../stores/session.js'
import { useUiStore } from '../../stores/ui.js'
import { useChatStore } from '../../stores/chat.js'
import { Icon, Menu } from '../ui'
import logoUrl from '../../assets/orange-logo.png'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const session = useSessionStore()
const ui = useUiStore()
const chat = useChatStore()

const activeSession = computed(() => route.params.sessionId || '')
const isAgents = computed(() => route.name === 'agents')

function newConversation() {
  router.push('/chat')
}
function openConversation(c) {
  // Re-clicking the conversation already in the URL is a duplicated navigation
  // vue-router short-circuits (no param change, no watcher) - go through the
  // store directly so a previously FAILED open gets its retry (ensureSession
  // refetches on threadError; on a healthy thread it is a cheap no-op).
  if (route.params.sessionId === c.id) chat.ensureSession(c.id)
  else router.push('/chat/' + encodeURIComponent(c.id))
}

// --- Lazy conversation list: fill ~120% of the viewport, then infinite-scroll. -----
const listEl = ref(null)
const sentinel = ref(null)
let observer = null
const ITEM_PX = 40 // approx height of one .conv-item
const FILL_RATIO = 1.2 // load enough to fill ~120% of the viewport

async function fillViewport() {
  const el = listEl.value
  if (!el) return
  // Initial page sized to ~120% of the visible list height.
  const target = Math.min(60, Math.max(10, Math.ceil((el.clientHeight * FILL_RATIO) / ITEM_PX)))
  await session.loadFirstConversations(target)
  await nextTick()
  // Top up until the list overflows (so the scrollbar/sentinel is reachable).
  let guard = 0
  while (
    session.convHasMore &&
    !session.convLoading &&
    el.scrollHeight <= el.clientHeight * FILL_RATIO &&
    guard < 20
  ) {
    guard += 1
    await session.loadMoreConversations()
    await nextTick()
  }
}

onMounted(async () => {
  await fillViewport()
  observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((e) => e.isIntersecting)) session.loadMoreConversations()
    },
    { root: listEl.value, rootMargin: '120px' },
  )
  if (sentinel.value) observer.observe(sentinel.value)
})

onBeforeUnmount(() => {
  if (observer) observer.disconnect()
})

// Foot menus (open upward). Help targets map 1:1 to routes.
const helpItems = computed(() => [
  { key: 'faq', label: t('help.faq'), icon: 'help' },
  { key: 'support', label: t('help.support'), icon: 'messageCircle' },
  { key: 'releases', label: t('help.releases'), icon: 'document' },
  { key: 'accessibility', label: t('help.accessibility'), icon: 'accessibility' },
  { key: 'cgu', label: t('help.cgu'), icon: 'document' },
  { key: 'privacy', label: t('help.privacy'), icon: 'shield' },
  { key: 'about', label: t('help.about'), icon: 'info' },
])
function onHelp(key) {
  router.push(key === 'faq' ? '/faq' : '/' + key)
}

const userItems = computed(() => {
  const items = [
    { key: 'settings', label: t('sb.settings'), icon: 'settings' },
    { key: 'faq', label: t('sb.faq'), icon: 'help' },
  ]
  if (session.isAdmin) items.push({ key: 'admin', label: 'Admin', icon: 'shield' })
  return items
})
function onUser(key) {
  if (key === 'admin') router.push('/admin')
  else if (key === 'settings') router.push('/settings')
  else if (key === 'faq') router.push('/faq')
}
</script>

<template>
  <aside class="sidebar">
    <div class="sidebar-head">
      <RouterLink to="/chat" class="brand">
        <img class="brand-mark" :src="logoUrl" alt="" width="28" height="28" />
        <span class="brand-name">{{ t('sb.brand') }}</span>
      </RouterLink>
      <button class="sidebar-toggle" :title="t('sb.collapse')" @click="ui.toggleSidebar()">
        <Icon name="sidebar" />
      </button>
    </div>

    <nav class="sidebar-primary">
      <button class="side-item" @click="newConversation">
        <Icon name="plus" /><span>{{ t('sb.new_conversation') }}</span>
      </button>
      <RouterLink class="side-item" :class="{ active: isAgents }" to="/agents">
        <Icon name="agents" /><span>{{ t('sb.agents') }}</span>
      </RouterLink>
    </nav>

    <div class="sidebar-section">
      <div class="sidebar-section-head">
        <span class="sidebar-section-title">{{ t('sb.conversations') }}</span>
        <div class="sidebar-section-icons">
          <button :title="t('sb.new_conversation')" @click="newConversation"><Icon name="plus" /></button>
        </div>
      </div>
    </div>

    <div class="conv-list" ref="listEl">
      <!-- Loading / error / empty states, then the list. We keep showing the list
           while a refresh is in flight (only show "loading" when there is nothing yet). -->
      <p v-if="session.convLoading && !session.conversations.length" class="conv-state">
        {{ t('sb.conv_loading') }}
      </p>
      <p
        v-else-if="session.convError && !session.conversations.length"
        class="conv-state conv-state--error"
      >
        {{ t('sb.conv_error') }}
      </p>
      <p v-else-if="!session.conversations.length" class="conv-state">
        {{ t('sb.conv_empty') }}
      </p>
      <template v-else>
        <button
          v-for="c in session.conversations"
          :key="c.id"
          class="conv-item"
          :class="{ active: c.id === activeSession }"
          :title="c.title"
          @click="openConversation(c)"
        >
          {{ c.title }}
        </button>
        <p v-if="session.convLoading && session.conversations.length" class="conv-state">
          {{ t('sb.loadingMore') }}
        </p>
      </template>
      <div ref="sentinel" class="conv-sentinel" aria-hidden="true"></div>
    </div>

    <div class="sidebar-foot">
      <Menu placement="top" align="left" :items="helpItems" @select="onHelp">
        <template #trigger="{ toggle }">
          <button class="side-item" @click="toggle"><Icon name="help" /><span>{{ t('sb.help') }}</span></button>
        </template>
      </Menu>
      <Menu placement="top" align="left" :items="userItems" @select="onUser">
        <template #trigger="{ toggle }">
          <button class="user-chip" @click="toggle">
            <span class="avatar">{{ session.initials }}</span>
            <span class="user-name">{{ session.displayName || '-' }}</span>
          </button>
        </template>
      </Menu>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  border-right: 1px solid var(--border);
  background: var(--surface);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  height: 100%;
}
.sidebar-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--s-5) var(--s-5) var(--s-6);
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: var(--fs-lg);
  font-weight: 600;
  letter-spacing: -0.025em;
  color: var(--text);
  text-decoration: none;
}
.brand-mark { width: 28px; height: 28px; border-radius: 3px; display: block; flex-shrink: 0; object-fit: cover; }
.sidebar-toggle {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  color: var(--text-2);
  border-radius: var(--r-sm);
  transition: all var(--dur) var(--ease);
  flex-shrink: 0;
}
.sidebar-toggle:hover { background: var(--surface-hover); color: var(--text); }
.sidebar-toggle :deep(.ui-icon) { width: 18px; height: 18px; }

.sidebar-primary { padding: 0 var(--s-3); display: flex; flex-direction: column; gap: 2px; }
.side-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 12px;
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--text);
  cursor: pointer;
  transition: background var(--dur) var(--ease);
  text-decoration: none;
  width: 100%;
  text-align: left;
}
.side-item:hover { background: var(--surface-hover); }
.side-item.active { background: var(--surface-hover); font-weight: 600; }
.side-item :deep(.ui-icon) { width: 16px; height: 16px; flex-shrink: 0; color: var(--text-2); }
.side-item.active :deep(.ui-icon) { color: var(--text); }

.sidebar-section { margin-top: var(--s-7); padding: 0 var(--s-5); }
.sidebar-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: var(--s-3);
}
.sidebar-section-title { font-size: var(--fs-xs); font-weight: 600; color: var(--text-3); letter-spacing: 0.02em; }
.sidebar-section-icons { display: flex; gap: 2px; color: var(--text-3); }
.sidebar-section-icons button {
  width: 22px;
  height: 22px;
  display: grid;
  place-items: center;
  border-radius: 4px;
  transition: all var(--dur) var(--ease);
}
.sidebar-section-icons button:hover { background: var(--surface-hover); color: var(--text); }
.sidebar-section-icons :deep(.ui-icon) { width: 14px; height: 14px; }

.conv-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 0 var(--s-3) var(--s-3);
  margin-top: var(--s-2);
}
.conv-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 7px 12px;
  border-radius: var(--r-sm);
  font-size: 13px;
  color: var(--text-2);
  cursor: pointer;
  transition: background var(--dur) var(--ease);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: var(--font-sans);
}
.conv-item:hover { background: var(--surface-hover); color: var(--text); }
.conv-item.active { background: var(--surface-hover); color: var(--text); }
.conv-state {
  padding: 8px 12px;
  margin: 0;
  font-size: 12px;
  line-height: 1.4;
  color: var(--text-3);
}
.conv-state--error { color: var(--danger); }
.conv-sentinel { height: 1px; }

.sidebar-foot {
  padding: var(--s-3);
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sidebar-foot .ui-menu-wrap { display: block; }
.user-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  font-weight: 500;
  color: var(--text);
  cursor: pointer;
  transition: background var(--dur) var(--ease);
  width: 100%;
  text-align: left;
}
.user-chip:hover { background: var(--surface-hover); }
.user-chip .avatar {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #d4d4d4;
  display: grid;
  place-items: center;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-2);
  flex-shrink: 0;
}
:global(body[data-theme="dark"] .user-chip .avatar) { background: var(--surface-2); }
.user-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
