<script setup>
// Sidebar - brand, primary nav, lazy conversation list, and the foot account/help
// menus. Two layouts, ONE mounted component (so the conversation list is never
// re-fetched on collapse/expand): the full sidebar, and a thin ICON RAIL when
// collapsed (an orange brand square that expands, New conversation, Agents, then Help and the
// account avatar pinned to the bottom). Navigation via vue-router; conversations come
// from the session store; menus reuse the <Menu> primitive.
import { computed, ref, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
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

const collapsed = computed(() => ui.sidebarCollapsed)
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

// Top up until the list overflows (so the scrollbar/sentinel is reachable). Guarded
// on a REAL layout box: when the sidebar mounts collapsed (rail), the list is
// display:none -> clientHeight 0; without this guard `scrollHeight <= clientHeight`
// would be `0 <= 0` = true and fire up to 20 needless /conversations queries against
// the instance for a list nobody can see. We top up on first expand instead.
async function topUp() {
  const el = listEl.value
  if (!el || el.clientHeight === 0) return
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

async function fillViewport() {
  const el = listEl.value
  if (!el) return
  const h = el.clientHeight // 0 when the sidebar mounts collapsed (list display:none)
  // Visible: size the first page to ~120% of the list height. Collapsed: just a small
  // first page so the list is ready (and not empty) the moment the rail is expanded.
  const target = h > 0 ? Math.min(60, Math.max(10, Math.ceil((h * FILL_RATIO) / ITEM_PX))) : 12
  await session.loadFirstConversations(target)
  await nextTick()
  await topUp()
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

// The list is hidden in the rail (v-show), so it cannot be filled to the viewport
// until the sidebar is expanded for the first time - top it up then (the already
// loaded first page is kept; no refetch).
let _filledOnExpand = false
watch(collapsed, async (isCollapsed) => {
  if (!isCollapsed && !_filledOnExpand) {
    _filledOnExpand = true
    await nextTick()
    await topUp()
  }
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
    { key: 'settings', label: t('sb.settings'), icon: 'user' },
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
  <aside class="sidebar" :class="{ rail: collapsed }">
    <!-- HEAD: brand (full) / expand control (rail) -->
    <div class="sidebar-head">
      <RouterLink v-if="!collapsed" to="/chat" class="brand">
        <img class="brand-mark" :src="logoUrl" alt="" width="30" height="30" />
        <span class="brand-name">{{ t('sb.brand') }}</span>
      </RouterLink>
      <button v-if="!collapsed" class="icon-btn" :title="t('sb.collapse')" @click="ui.toggleSidebar()">
        <Icon name="sidebar" />
      </button>
      <button v-else class="rail-brand" :title="t('sb.expand')" @click="ui.toggleSidebar()">
        <img class="brand-mark" :src="logoUrl" alt="OWIsMind" width="30" height="30" />
        <span class="rail-brand-hint"><Icon name="chevronsRight" /></span>
      </button>
    </div>

    <!-- PRIMARY: New conversation + Agents (neutral nav items) -->
    <nav class="sidebar-primary">
      <button class="side-item" :title="t('rail.new')" @click="newConversation">
        <Icon name="plus" /><span class="side-label">{{ t('sb.new_conversation') }}</span>
      </button>
      <RouterLink class="side-item" :class="{ active: isAgents }" to="/agents" :title="t('rail.agents')">
        <Icon name="agents" /><span class="side-label">{{ t('sb.agents') }}</span>
      </RouterLink>
    </nav>

    <!-- Section title + conversation list (hidden in the rail, kept mounted) -->
    <div class="sidebar-section" v-show="!collapsed">
      <span class="sidebar-section-title">{{ t('sb.conversations') }}</span>
    </div>

    <div class="conv-list" ref="listEl" v-show="!collapsed">
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

    <!-- In the rail there is no list; this filler pushes the foot to the bottom. -->
    <div class="rail-fill" v-show="collapsed" aria-hidden="true"></div>

    <!-- FOOT: Help (above) then the account avatar (bottom) -->
    <div class="sidebar-foot">
      <Menu placement="top" align="left" :items="helpItems" @select="onHelp">
        <template #trigger="{ toggle, open }">
          <button class="side-item" :class="{ open }" :title="t('rail.help')" @click="toggle">
            <Icon name="help" /><span class="side-label">{{ t('sb.help') }}</span>
          </button>
        </template>
      </Menu>
      <Menu placement="top" align="left" :items="userItems" @select="onUser">
        <template #trigger="{ toggle, open }">
          <button class="user-chip" :class="{ open }" :title="t('rail.account')" @click="toggle">
            <span class="avatar">{{ session.initials }}</span>
            <span class="user-name side-label">{{ session.displayName || '-' }}</span>
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

/* --- Head --------------------------------------------------------------- */
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
.brand-mark {
  width: 28px;
  height: 28px;
  border-radius: 3px;
  display: block;
  flex-shrink: 0;
  object-fit: cover;
}
.icon-btn {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  color: var(--text-2);
  border-radius: var(--r-sm);
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
  flex-shrink: 0;
}
.icon-btn:hover { background: var(--surface-hover); color: var(--text); }
.icon-btn :deep(.ui-icon) { width: 18px; height: 18px; }

/* Rail brand doubles as the expand control: the orange square + a hover chevron. */
.rail-brand {
  position: relative;
  width: 40px;
  height: 40px;
  display: grid;
  place-items: center;
  border-radius: var(--square);
  margin: 0 auto;
  transition: transform var(--dur) var(--ease);
}
.rail-brand:hover { transform: translateY(-1px); }
.rail-brand-hint {
  position: absolute;
  right: -3px;
  bottom: -3px;
  width: 16px;
  height: 16px;
  display: grid;
  place-items: center;
  border-radius: var(--r-xs);
  background: var(--bg);
  border: 1px solid var(--border);
  color: var(--text-3);
  opacity: 0;
  transform: scale(0.7);
  transition: all var(--dur) var(--ease);
}
.rail-brand:hover .rail-brand-hint { opacity: 1; transform: scale(1); }
.rail-brand-hint :deep(.ui-icon) { width: 11px; height: 11px; }

/* --- Primary nav -------------------------------------------------------- */
.sidebar-primary { padding: 0 var(--s-3); display: flex; flex-direction: column; gap: 3px; }

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
.side-item:hover, .side-item.open { background: var(--surface-hover); }
.side-item.active { background: var(--surface-hover); font-weight: 600; }
.side-item :deep(.ui-icon) { width: 16px; height: 16px; flex-shrink: 0; color: var(--text-2); }
.side-item.active :deep(.ui-icon) { color: var(--text); }

/* --- Conversations ------------------------------------------------------ */
.sidebar-section { margin-top: var(--s-7); padding: 0 var(--s-5) var(--s-3); }
.sidebar-section-title {
  font-size: var(--fs-xs);
  font-weight: var(--fw-semibold);
  color: var(--text-3);
  letter-spacing: var(--tracking-eyebrow);
  text-transform: uppercase;
}

.conv-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 0 var(--s-3) var(--s-3);
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
.rail-fill { flex: 1; }

/* --- Foot --------------------------------------------------------------- */
.sidebar-foot {
  padding: var(--s-3);
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.sidebar-foot .ui-menu-wrap { display: block; }
.user-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 10px;
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  font-weight: var(--fw-medium);
  color: var(--text);
  cursor: pointer;
  transition: background var(--dur) var(--ease);
  width: 100%;
  text-align: left;
}
.user-chip:hover, .user-chip.open { background: var(--surface-hover); }
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

/* =========================================================================
   RAIL (collapsed): icon-only, centered, labels hidden. The list is display:none
   (v-show) so it keeps its scroll state and is never re-fetched on expand.
   ========================================================================= */
/* The foot menus (Help / account) are 220px wide and NOT teleported; in the 60px
   rail they must escape the column. The list is hidden here (v-show) so the rail
   never needs its own scroll - overflow can safely be visible. */
.sidebar.rail { overflow: visible; }
.sidebar.rail .sidebar-head { padding: var(--s-4) 0 var(--s-5); justify-content: center; }
.sidebar.rail .sidebar-primary { padding: 0 10px; gap: 6px; }
.sidebar.rail .sidebar-foot { padding: 8px; gap: 6px; }

/* Icon-only square targets, centered, labels collapsed away. */
.sidebar.rail .side-label { display: none; }
.sidebar.rail .side-item,
.sidebar.rail .user-chip {
  width: 40px;
  height: 40px;
  padding: 0;
  justify-content: center;
  gap: 0;
  margin: 0 auto;
}
.sidebar.rail .user-chip .avatar { width: 26px; height: 26px; }

/* Reduced-motion: drop the positional hover movement (transitions stay). */
@media (prefers-reduced-motion: reduce) {
  .rail-brand:hover { transform: none; }
}
</style>
