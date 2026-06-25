// vue-router - replaces the maquette's STATE.page string + PAGES table.
//
// HASH history on purpose: the DSS webapp is served at a fixed URL with no
// server-side SPA rewrite, so path history would 404 on reload/deep-link. Hash
// routing keeps everything client-side and reload-safe.
//
// Extensibility: add a page = add one route entry (a module/view that registers
// here). The core secondary pages have dedicated views (Phase 3); the remaining
// help-menu targets share a single <PagePlaceholder> driven by i18n meta keys
// until their real content is built. Admin is a GUARDED route.
import { createRouter, createWebHashHistory } from 'vue-router'
import { useSessionStore } from '../stores/session.js'

const ChatView = () => import('../views/ChatView.vue')
const PagePlaceholder = () => import('../views/PagePlaceholder.vue')
// Phase-3 dedicated views (lazy - keep the initial chat bundle lean).
const SettingsView = () => import('../views/SettingsView.vue')
const FeedbackView = () => import('../views/FeedbackView.vue')
const FaqView = () => import('../views/FaqView.vue')
const AgentsView = () => import('../views/AgentsView.vue')
const ProjectView = () => import('../views/ProjectView.vue')
const AdminView = () => import('../views/AdminView.vue')
const BenchmarkSuggestView = () => import('../views/BenchmarkSuggestView.vue')

// Secondary pages still rendered as labeled placeholders (i18n meta keys).
// Only the help-menu targets remain generic placeholders now.
const placeholderPages = [
  // Help menu targets
  { path: '/support', name: 'support', meta: { eyebrow: 'support.eyebrow', title: 'support.title', desc: 'support.desc' } },
  { path: '/releases', name: 'releases', meta: { eyebrow: 'releases.eyebrow', title: 'releases.title', desc: 'releases.desc' } },
  { path: '/accessibility', name: 'accessibility', meta: { eyebrow: 'acc.eyebrow', title: 'acc.title', desc: 'acc.desc' } },
  { path: '/cgu', name: 'cgu', meta: { eyebrow: 'cgu.eyebrow', title: 'cgu.title', desc: 'cgu.desc' } },
  { path: '/privacy', name: 'privacy', meta: { eyebrow: 'priv.eyebrow', title: 'priv.title', desc: 'priv.desc' } },
  { path: '/about', name: 'about', meta: { eyebrow: 'about.eyebrow', title: 'about.title', desc: 'about.desc' } },
].map((r) => ({ ...r, component: PagePlaceholder }))

const routes = [
  { path: '/', redirect: '/chat' },
  { path: '/chat/:sessionId?', name: 'chat', component: ChatView },
  { path: '/settings', name: 'settings', component: SettingsView, meta: { eyebrow: 'set.eyebrow', title: 'set.title' } },
  { path: '/feedback', name: 'feedback', component: FeedbackView, meta: { eyebrow: 'fb.eyebrow', title: 'fb.title' } },
  { path: '/faq', name: 'faq', component: FaqView, meta: { eyebrow: 'faq.eyebrow', title: 'faq.title' } },
  { path: '/agents/:agentId?', name: 'agents', component: AgentsView, meta: { eyebrow: 'ag.eyebrow', title: 'ag.title' } },
  // Benchmark suggestions - ALL users (no admin guard): propose golden questions.
  { path: '/benchmark', name: 'benchmark', component: BenchmarkSuggestView, meta: { eyebrow: 'bench.eyebrow', title: 'bench.title' } },
  { path: '/project/:projectId', name: 'project', component: ProjectView, meta: { eyebrow: 'pj.eyebrow', title: 'sb.projects' } },
  ...placeholderPages,
  {
    path: '/admin',
    name: 'admin',
    component: AdminView,
    meta: { eyebrow: 'admin.eyebrow', title: 'admin.title', requiresAdmin: true },
  },
  { path: '/:pathMatch(.*)*', redirect: '/chat' },
]

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// Admin guard - resolve identity (memoized) then gate on is_admin.
router.beforeEach(async (to) => {
  if (!to.meta.requiresAdmin) return true
  const session = useSessionStore()
  await session.ensureLoaded()
  return session.isAdmin ? true : { name: 'chat' }
})
