<script setup>
// Admin console (tabbed) - HONEST: only features with a real, validated backend are
// wired (storage view, agent whitelist + authored profiles, users + admin flag,
// monthly budgets). The activity feed has no backend, so it is an explicit empty
// state (never fake KPIs/spend/activity). The route is server-gated AND guarded
// client-side (router meta.requiresAdmin).
//
// Agents tab: besides enabling agents, an admin authors each agent's PROFILE
// (tagline / description / capabilities / tools / icon / badge) in a modal editor.
// That profile is stored with the whitelist and is the single source of the
// agent-library cards (no hardcoded copy anywhere in the frontend).
import { ref, reactive, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSessionStore } from '../stores/session.js'
import {
  fetchAdminStorage,
  fetchAdminUsers,
  setUserAdmin,
  fetchAdminProjects,
  fetchAdminProjectAgents,
  fetchAdminAgents,
  saveAdminAgents,
  fetchAdminBudget,
  saveAdminBudget,
  saveAdminUserQuota,
} from '../services/backend.js'
import {
  formatMoney,
  formatShortDate,
  usagePct,
  gaugePct,
} from '../composables/budgetModel.js'
import { PageShell, SettingCard, EmptyState } from '../components/pages'
import { Tabs, Button, Icon, Modal } from '../components/ui'

const { t, locale } = useI18n()
const session = useSessionStore()
const meId = computed(() => session.user?.user_id || '')

const activeTab = ref('overview')

const loading = ref(true)
const errorMsg = ref('')

const storage = ref(null) // { connection, project_key, table_prefix, namespace, tables }
const users = ref([]) // [{ user_id, display_name, user_groups, is_admin, ... }]
const busyUser = ref('')

// --- Agent whitelist + authored profiles --------------------------------------
const projects = ref([]) // visible DSS project keys
const selectedProject = ref('') // currently inspected project
const projectAgents = ref([]) // [{ agent_id, description }] for the selected project
const loadingAgents = ref(false)
// Working selection: [{ project_key, agent_id, label, profile }].
const enabled = ref([])
const savingAgents = ref(false)
const agentsMsg = ref('')
const profilesDirty = ref(false)

// Icons an admin may assign to an agent (must match the server-side whitelist).
const AGENT_ICONS = [
  'robot', 'sparkle', 'sparkles', 'trendUp', 'chart', 'layers', 'database',
  'route', 'message', 'users', 'wallet', 'shield', 'globe', 'alert',
  'thumbsUp', 'sliders', 'bookOpen', 'tool', 'tag', 'grid',
]
const BADGES = ['', 'default', 'new', 'beta']
const TAGLINE_MAX = 120
const DESC_MAX = 700

function emptyProfile() {
  return { tagline: '', description: '', capabilities: [], tools: [], icon: 'robot', badge: '' }
}

// --- Profile editor (modal) ---------------------------------------------------
const editorOpen = ref(false)
const editingIndex = ref(-1)
const editForm = reactive({
  label: '',
  project_key: '',
  icon: 'robot',
  badge: '',
  tagline: '',
  description: '',
  capsText: '',
  toolsText: '',
})

function linesToList(text, max) {
  return String(text || '')
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
    .slice(0, max)
}

function openEditor(i) {
  const e = enabled.value[i]
  if (!e) return
  const p = e.profile || emptyProfile()
  editingIndex.value = i
  editForm.label = e.label
  editForm.project_key = e.project_key
  editForm.icon = p.icon || 'robot'
  editForm.badge = p.badge || ''
  editForm.tagline = p.tagline || ''
  editForm.description = p.description || ''
  editForm.capsText = (p.capabilities || []).join('\n')
  editForm.toolsText = (p.tools || []).join('\n')
  editorOpen.value = true
}

function applyEditor() {
  const e = enabled.value[editingIndex.value]
  if (e) {
    e.profile = {
      icon: editForm.icon || 'robot',
      badge: editForm.badge || '',
      tagline: editForm.tagline.trim().slice(0, TAGLINE_MAX),
      description: editForm.description.trim().slice(0, DESC_MAX),
      capabilities: linesToList(editForm.capsText, 8),
      tools: linesToList(editForm.toolsText, 16),
    }
    profilesDirty.value = true
  }
  editorOpen.value = false
}

// Live preview of how the agent card will read with the current form values.
const previewCaps = computed(() => linesToList(editForm.capsText, 8))
const previewTools = computed(() => linesToList(editForm.toolsText, 16))

// --- Monthly budgets / quotas (unchanged logic) -------------------------------
const budget = ref(null)
const budgetMsg = ref('')
const savingBudget = ref(false)
const applyingQuota = ref(false)
const budgetForm = reactive({ limit_usd: 50, enabled: true, temp_limit_usd: '', temp_days: '' })
const selected = reactive(new Set())
const applyForm = reactive({ limit_usd: '', duration: 'permanent', note: '' })
const DAY_DURATIONS = ['7', '30', '90']

const budgetUsers = computed(() => (budget.value && budget.value.users) || [])
const defaultLimit = computed(() => {
  const c = budget.value && budget.value.config
  return money((c && c.default_limit_usd) != null ? c.default_limit_usd : 50)
})
const selectedCount = computed(() => selected.size)
const allSelected = computed(
  () => budgetUsers.value.length > 0 && selected.size === budgetUsers.value.length,
)
const tempActive = computed(() => {
  const c = budget.value && budget.value.config
  return !!(c && c.global_source === 'global_temp')
})

function seedBudgetForm() {
  const c = budget.value && budget.value.config
  if (!c) return
  budgetForm.limit_usd = c.limit_usd
  budgetForm.enabled = c.enabled !== false
  budgetForm.temp_limit_usd = ''
  budgetForm.temp_days = ''
}

const money = (v) => formatMoney(v, locale.value)
const shortDate = (v) => formatShortDate(v, locale.value)

function rowPct(u) {
  return usagePct(u.spent_usd, u.limit_usd)
}
function rowFill(u) {
  return gaugePct(u.spent_usd, u.limit_usd)
}
function sourceKey(u) {
  return 'admin.quotas.src.' + (u.limit_source || 'default')
}
function sourceClass(u) {
  if (u.blocked) return 'src-over'
  if (u.limit_source === 'user_permanent' || u.limit_source === 'user_temp') return 'src-user'
  if (u.limit_source === 'global_temp') return 'src-temp'
  return 'src-default'
}

function toggleUser(id) {
  if (selected.has(id)) selected.delete(id)
  else selected.add(id)
}
function toggleAll() {
  if (allSelected.value) {
    selected.clear()
  } else {
    budgetUsers.value.forEach((u) => selected.add(u.user_id))
  }
}

async function postBudget(extra) {
  if (savingBudget.value) return
  savingBudget.value = true
  budgetMsg.value = ''
  try {
    const payload = { limit_usd: Number(budgetForm.limit_usd), enabled: !!budgetForm.enabled, ...extra }
    const data = await saveAdminBudget(payload)
    budget.value = { config: data.config, period_start: data.period_start, next_reset: data.next_reset, users: data.users || [] }
    seedBudgetForm()
    budgetMsg.value = t('admin.quotas.saved')
  } catch (e) {
    budgetMsg.value = t('admin.quotas.error')
  } finally {
    savingBudget.value = false
  }
}
function saveBudget() {
  return postBudget({})
}
function applyTempBoost() {
  if (budgetForm.temp_limit_usd === '' || budgetForm.temp_days === '') return
  return postBudget({
    temp_limit_usd: Number(budgetForm.temp_limit_usd),
    temp_days: Number(budgetForm.temp_days),
  })
}
function clearTempBoost() {
  return postBudget({ clear_temp: true })
}

async function applyQuota(clear) {
  if (applyingQuota.value) return
  if (selected.size === 0) {
    budgetMsg.value = t('admin.quotas.none_selected')
    return
  }
  applyingQuota.value = true
  budgetMsg.value = ''
  try {
    const userIds = Array.from(selected)
    let payload
    if (clear) {
      payload = { user_ids: userIds, clear: true }
    } else {
      const dur = applyForm.duration
      payload = {
        user_ids: userIds,
        limit_usd: Number(applyForm.limit_usd),
        expires_days: dur === 'permanent' ? null : Number(dur),
        note: applyForm.note || '',
      }
    }
    const data = await saveAdminUserQuota(payload)
    budget.value = { config: data.config, period_start: data.period_start, next_reset: data.next_reset, users: data.users || [] }
    seedBudgetForm()
    const n = userIds.length
    selected.clear()
    budgetMsg.value = t('admin.quotas.applied', [n])
  } catch (e) {
    budgetMsg.value = t('admin.quotas.error')
  } finally {
    applyingQuota.value = false
  }
}

const tabs = computed(() => [
  { key: 'overview', label: t('admin.tab.overview') },
  { key: 'agents', label: t('admin.tab.agents'), count: enabled.value.length },
  { key: 'users', label: t('admin.tab.users'), count: users.value.length },
  { key: 'quotas', label: t('admin.tab.quotas') },
  { key: 'activity', label: t('admin.tab.activity') },
])

async function loadAll() {
  loading.value = true
  errorMsg.value = ''
  try {
    const [s, u, p, a, b] = await Promise.all([
      fetchAdminStorage(),
      fetchAdminUsers(),
      fetchAdminProjects(),
      fetchAdminAgents(),
      fetchAdminBudget(),
    ])
    storage.value = s.storage
    users.value = u.users || []
    projects.value = p.projects || []
    // Keep the fields we resend on save (selection + authored profile); labels come from the backend.
    enabled.value = (a.agents || []).map((e) => ({
      project_key: e.project_key,
      agent_id: e.agent_id,
      label: e.label,
      profile: e.profile && typeof e.profile === 'object' ? { ...emptyProfile(), ...e.profile } : emptyProfile(),
    }))
    budget.value = { config: b.config, period_start: b.period_start, next_reset: b.next_reset, users: b.users || [] }
    seedBudgetForm()
  } catch (e) {
    errorMsg.value = t('admin.load_error')
  } finally {
    loading.value = false
  }
}

async function onProjectChange() {
  projectAgents.value = []
  agentsMsg.value = ''
  if (!selectedProject.value) return
  loadingAgents.value = true
  try {
    const res = await fetchAdminProjectAgents(selectedProject.value)
    projectAgents.value = res.agents || []
    if (projectAgents.value.length === 0) agentsMsg.value = t('admin.agents.none_in_project')
  } catch (e) {
    agentsMsg.value = t('admin.load_error')
  } finally {
    loadingAgents.value = false
  }
}

function isEnabled(agent) {
  return enabled.value.some(
    (e) => e.project_key === selectedProject.value && e.agent_id === agent.agent_id,
  )
}

function toggleAgent(agent) {
  const idx = enabled.value.findIndex(
    (e) => e.project_key === selectedProject.value && e.agent_id === agent.agent_id,
  )
  if (idx >= 0) {
    enabled.value.splice(idx, 1)
  } else {
    enabled.value.push({
      project_key: selectedProject.value,
      agent_id: agent.agent_id,
      label: agent.description,
      profile: emptyProfile(),
    })
  }
  profilesDirty.value = true
}

function removeEnabled(entry) {
  const idx = enabled.value.findIndex(
    (e) => e.project_key === entry.project_key && e.agent_id === entry.agent_id,
  )
  if (idx >= 0) enabled.value.splice(idx, 1)
  profilesDirty.value = true
}

function hasProfile(e) {
  const p = e.profile || {}
  return !!(p.tagline || p.description || (p.capabilities && p.capabilities.length))
}

async function saveAgents() {
  if (savingAgents.value) return
  savingAgents.value = true
  agentsMsg.value = ''
  try {
    const payload = enabled.value.map((e) => ({
      project_key: e.project_key,
      agent_id: e.agent_id,
      profile: e.profile || emptyProfile(),
    }))
    const res = await saveAdminAgents(payload)
    enabled.value = (res.agents || []).map((e) => ({
      project_key: e.project_key,
      agent_id: e.agent_id,
      label: e.label,
      profile: e.profile && typeof e.profile === 'object' ? { ...emptyProfile(), ...e.profile } : emptyProfile(),
    }))
    profilesDirty.value = false
    agentsMsg.value = t('admin.agents.saved', [res.count])
  } catch (e) {
    agentsMsg.value = t('admin.load_error')
  } finally {
    savingAgents.value = false
  }
}

async function toggleAdmin(u) {
  if (busyUser.value) return
  busyUser.value = u.user_id
  errorMsg.value = ''
  try {
    const res = await setUserAdmin(u.user_id, !u.is_admin)
    users.value = res.users || users.value
  } catch (e) {
    const code = e && e.message ? e.message : ''
    errorMsg.value = code === 'cannot_remove_last_admin' ? t('admin.users.last_admin_error') : t('admin.load_error')
  } finally {
    busyUser.value = ''
  }
}

onMounted(loadAll)

if (import.meta.env.DEV) {
  window.__adminRefs = {
    loading, errorMsg, storage, users, projects, selectedProject, projectAgents, enabled,
  }
}
</script>

<template>
  <PageShell wide>
    <template #header>
      <div class="admin-head">
        <p class="admin-eyebrow">{{ t('admin.eyebrow') }}</p>
        <div class="admin-title-row">
          <h1 class="admin-title">{{ t('admin.title') }}</h1>
          <span class="admin-badge"><Icon name="shield" />ADMIN</span>
        </div>
        <p class="admin-desc">{{ t('admin.desc') }}</p>
      </div>
      <Tabs v-model="activeTab" :items="tabs" class="admin-tabs" />
    </template>

    <p v-if="loading" class="admin-status muted">{{ t('admin.loading') }}</p>
    <p v-else-if="errorMsg" class="admin-status admin-error">{{ errorMsg }}</p>

    <template v-else>
      <!-- ===================== OVERVIEW ===================== -->
      <div v-show="activeTab === 'overview'" class="admin-panel">
        <div class="kpi-grid">
          <div class="kpi">
            <span class="kpi-ico"><Icon name="users" :size="18" /></span>
            <span class="kpi-label">{{ t('admin.kpi.users') }}</span>
            <span class="kpi-value mono">{{ users.length }}</span>
          </div>
          <div class="kpi">
            <span class="kpi-ico"><Icon name="robot" :size="18" /></span>
            <span class="kpi-label">{{ t('admin.kpi.agents') }}</span>
            <span class="kpi-value mono">{{ enabled.length }}</span>
          </div>
          <div class="kpi">
            <span class="kpi-ico"><Icon name="database" :size="18" /></span>
            <span class="kpi-label">{{ t('admin.kpi.connection') }}</span>
            <span class="kpi-value mono">{{ storage?.connection || '-' }}</span>
          </div>
        </div>

        <SettingCard v-if="storage" :eyebrow="t('admin.storage.title')">
          <dl class="kv">
            <dt>{{ t('admin.storage.connection') }}</dt>
            <dd><code>{{ storage.connection || '-' }}</code></dd>
            <dt>{{ t('admin.storage.project_key') }}</dt>
            <dd><code>{{ storage.project_key }}</code></dd>
            <dt>{{ t('admin.storage.prefix') }}</dt>
            <dd>
              {{ storage.table_prefix || t('admin.storage.none') }}
              <span v-if="storage.table_prefix_ignored" class="prefix-warn">
                <Icon name="alert" />
                {{ t('admin.storage.prefix_ignored', [storage.table_prefix_input]) }}
              </span>
            </dd>
            <dt>{{ t('admin.storage.traces') }}</dt>
            <dd>
              <code v-if="storage.traces_dataset">{{ storage.traces_dataset }}</code>
              <span v-else class="muted">{{ t('admin.storage.traces_off') }}</span>
            </dd>
            <dt>{{ t('admin.storage.namespace') }}</dt>
            <dd><code>{{ storage.namespace }}</code></dd>
          </dl>
          <p class="kv-note muted">{{ t('admin.storage.tables') }}</p>
          <ul class="tables">
            <li v-for="(name, key) in storage.tables" :key="key"><code>{{ name }}</code></li>
          </ul>
          <p class="kv-note muted">{{ t('admin.storage.note') }}</p>
        </SettingCard>
      </div>

      <!-- ===================== AGENTS ===================== -->
      <div v-show="activeTab === 'agents'" class="admin-panel">
        <SettingCard :eyebrow="t('admin.agents.title')">
          <p class="card-desc muted">{{ t('admin.agents.desc') }}</p>

          <!-- 1. Pick a project, then add its agents ------------------------------ -->
          <div class="agent-pick">
            <label class="field-label" for="admin-project">{{ t('admin.agents.pick_project') }}</label>
            <div class="select-wrap">
              <select id="admin-project" v-model="selectedProject" class="admin-select" @change="onProjectChange">
                <option value="">{{ t('admin.agents.project_choose') }}</option>
                <option v-for="pk in projects" :key="pk" :value="pk">{{ pk }}</option>
              </select>
              <span class="select-arr"><Icon name="chevronDown" /></span>
            </div>
          </div>

          <p v-if="loadingAgents" class="muted card-desc">{{ t('admin.agents.loading') }}</p>
          <ul v-else-if="projectAgents.length" class="pick-list">
            <li v-for="a in projectAgents" :key="a.agent_id" class="pick-row" :class="{ on: isEnabled(a) }">
              <span class="pick-info">
                <span class="pick-label">{{ a.description }}</span>
                <code class="pick-id">{{ a.agent_id }}</code>
              </span>
              <button
                type="button"
                class="pick-btn"
                :class="{ on: isEnabled(a) }"
                @click="toggleAgent(a)"
              >
                <Icon :name="isEnabled(a) ? 'check' : 'plus'" />
                {{ isEnabled(a) ? t('admin.agents.added') : t('admin.agents.add') }}
              </button>
            </li>
          </ul>
          <p v-else-if="selectedProject" class="muted card-desc">{{ t('admin.agents.none_in_project') }}</p>
        </SettingCard>

        <!-- 2. Exposed agents + their authored profiles --------------------------- -->
        <SettingCard :eyebrow="t('admin.agents.enabled_count', [enabled.length])">
          <EmptyState v-if="!enabled.length" icon="robot" :desc="t('admin.agents.enabled_empty')" />
          <ul v-else class="exposed-list">
            <li v-for="(e, i) in enabled" :key="e.project_key + '::' + e.agent_id" class="exposed-row">
              <span class="exposed-ico"><Icon :name="(e.profile && e.profile.icon) || 'robot'" :size="20" /></span>
              <span class="exposed-info">
                <span class="exposed-label">{{ e.label }}</span>
                <span class="exposed-meta">
                  <span class="exposed-project mono">{{ e.project_key }}</span>
                  <span class="profile-state" :class="{ ok: hasProfile(e) }">
                    <Icon :name="hasProfile(e) ? 'check' : 'alert'" />
                    {{ hasProfile(e) ? t('admin.agents.has_profile') : t('admin.agents.no_profile') }}
                  </span>
                </span>
              </span>
              <span class="exposed-actions">
                <button type="button" class="ghost-btn" @click="openEditor(i)">
                  <Icon name="pencil" />{{ t('admin.agents.configure') }}
                </button>
                <button type="button" class="x-btn" :title="t('admin.agents.remove')" @click="removeEnabled(e)">
                  <Icon name="x" />
                </button>
              </span>
            </li>
          </ul>

          <div class="agent-actions">
            <Button variant="primary" :disabled="savingAgents" @click="saveAgents">
              {{ savingAgents ? t('admin.agents.saving') : t('admin.agents.save') }}
            </Button>
            <span v-if="profilesDirty && !agentsMsg" class="unsaved">
              <Icon name="alert" />{{ t('admin.agents.unsaved', [t('admin.agents.save')]) }}
            </span>
            <span v-if="agentsMsg" class="muted card-desc">{{ agentsMsg }}</span>
          </div>
        </SettingCard>
      </div>

      <!-- ===================== USERS ===================== -->
      <div v-show="activeTab === 'users'" class="admin-panel">
        <SettingCard :eyebrow="t('admin.users.title')">
          <p class="card-desc muted">{{ t('admin.users.desc') }}</p>
          <div class="table-scroll">
            <table class="admin-table">
              <thead>
                <tr>
                  <th>{{ t('admin.users.col_user') }}</th>
                  <th>{{ t('admin.users.col_groups') }}</th>
                  <th>{{ t('admin.users.col_admin') }}</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="u in users" :key="u.user_id">
                  <td>
                    <span class="user-id">{{ u.user_id }}</span>
                    <span v-if="u.user_id === meId" class="you">{{ t('admin.users.you') }}</span>
                  </td>
                  <td class="muted">{{ (u.user_groups || []).join(', ') }}</td>
                  <td>
                    <Icon v-if="u.is_admin" name="check" class="admin-yes" /><span v-else class="muted">-</span>
                  </td>
                  <td class="row-action">
                    <Button variant="ghost" :disabled="busyUser === u.user_id" @click="toggleAdmin(u)">
                      {{ u.is_admin ? t('admin.users.revoke_admin') : t('admin.users.make_admin') }}
                    </Button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </SettingCard>
      </div>

      <!-- ===================== QUOTAS ===================== -->
      <div v-show="activeTab === 'quotas'" class="admin-panel">
        <SettingCard :eyebrow="t('admin.quotas.title')">
          <p class="card-desc muted">{{ t('admin.quotas.desc', [defaultLimit]) }}</p>

          <div class="q-form">
            <div class="q-field">
              <label class="field-label" for="q-default">{{ t('admin.quotas.default_limit') }}</label>
              <input id="q-default" v-model="budgetForm.limit_usd" type="number" min="0" step="1" class="q-input" />
            </div>
            <label class="q-check">
              <input type="checkbox" v-model="budgetForm.enabled" />
              <span>{{ t('admin.quotas.enabled') }}</span>
            </label>
          </div>
          <p class="q-hint muted">{{ t('admin.quotas.enabled_hint') }}</p>

          <div class="q-subhead">{{ t('admin.quotas.temp_title') }}</div>
          <p v-if="tempActive" class="q-temp-active">
            <Icon name="clock" />
            <span>{{ t('admin.quotas.temp_active', [money(budget.config.temp_limit_usd), shortDate(budget.config.temp_expires_at)]) }}</span>
            <button class="q-link" type="button" @click="clearTempBoost">{{ t('admin.quotas.temp_clear') }}</button>
          </p>
          <div class="q-form q-form--row">
            <div class="q-field">
              <label class="field-label" for="q-temp-amt">{{ t('admin.quotas.temp_amount') }}</label>
              <input id="q-temp-amt" v-model="budgetForm.temp_limit_usd" type="number" min="0" step="1" class="q-input" />
            </div>
            <div class="q-field">
              <label class="field-label" for="q-temp-days">{{ t('admin.quotas.temp_days') }}</label>
              <input id="q-temp-days" v-model="budgetForm.temp_days" type="number" min="1" step="1" class="q-input" />
            </div>
            <Button
              variant="ghost"
              :disabled="savingBudget || budgetForm.temp_limit_usd === '' || budgetForm.temp_days === ''"
              @click="applyTempBoost"
            >
              {{ t('admin.quotas.temp_apply') }}
            </Button>
          </div>

          <div class="agent-actions">
            <Button variant="primary" :disabled="savingBudget" @click="saveBudget">
              {{ savingBudget ? t('admin.quotas.saving') : t('admin.quotas.save') }}
            </Button>
            <span v-if="budgetMsg" class="muted card-desc">{{ budgetMsg }}</span>
          </div>
        </SettingCard>

        <SettingCard :eyebrow="t('admin.quotas.users_title')">
          <p class="card-desc muted">{{ t('admin.quotas.users_desc') }}</p>

          <div class="table-scroll">
            <table class="admin-table q-table">
              <thead>
                <tr>
                  <th class="q-check-col">
                    <input type="checkbox" :checked="allSelected" :title="t('admin.quotas.select_all')" @change="toggleAll" />
                  </th>
                  <th>{{ t('admin.quotas.col_user') }}</th>
                  <th>{{ t('admin.quotas.col_usage') }}</th>
                  <th>{{ t('admin.quotas.col_limit') }}</th>
                  <th>{{ t('admin.quotas.col_remaining') }}</th>
                  <th>{{ t('admin.quotas.col_source') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="u in budgetUsers" :key="u.user_id" :class="{ 'q-row-sel': selected.has(u.user_id) }">
                  <td>
                    <input type="checkbox" :checked="selected.has(u.user_id)" @change="toggleUser(u.user_id)" />
                  </td>
                  <td>
                    <div class="q-user">
                      <span class="user-id">{{ u.display_name || u.user_id }}</span>
                      <span v-if="u.user_id === meId" class="you">{{ t('admin.users.you') }}</span>
                    </div>
                    <span class="q-uid mono">{{ u.user_id }}</span>
                  </td>
                  <td class="q-usage">
                    <div class="q-mini-bar">
                      <span class="q-mini-fill" :class="{ over: u.blocked }" :style="{ width: rowFill(u) + '%' }" />
                    </div>
                    <span class="mono q-usage-amt">{{ money(u.spent_usd) }} <span class="muted">({{ rowPct(u) }}%)</span></span>
                  </td>
                  <td class="mono">{{ money(u.limit_usd) }}</td>
                  <td class="mono">{{ money(u.remaining_usd) }}</td>
                  <td>
                    <span class="q-src" :class="sourceClass(u)">{{ t(sourceKey(u)) }}</span>
                    <span v-if="u.blocked" class="q-blocked">{{ t('admin.quotas.blocked_tag') }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div v-if="selectedCount" class="q-apply">
            <div class="q-apply-head">{{ t('admin.quotas.apply_title', [selectedCount]) }}</div>
            <div class="q-apply-row">
              <div class="q-field">
                <label class="field-label" for="q-apply-amt">{{ t('admin.quotas.limit_amount') }}</label>
                <input id="q-apply-amt" v-model="applyForm.limit_usd" type="number" min="0" step="1" class="q-input" />
              </div>
              <div class="q-field">
                <label class="field-label" for="q-apply-dur">{{ t('admin.quotas.duration') }}</label>
                <div class="select-wrap">
                  <select id="q-apply-dur" v-model="applyForm.duration" class="admin-select">
                    <option value="permanent">{{ t('admin.quotas.permanent') }}</option>
                    <option v-for="d in DAY_DURATIONS" :key="d" :value="d">{{ t('admin.quotas.temp_days_opt', [d]) }}</option>
                  </select>
                  <span class="select-arr"><Icon name="chevronDown" /></span>
                </div>
              </div>
              <div class="q-field q-field--grow">
                <label class="field-label" for="q-apply-note">{{ t('admin.quotas.note') }}</label>
                <input id="q-apply-note" v-model="applyForm.note" type="text" maxlength="280" class="q-input" />
              </div>
            </div>
            <div class="agent-actions">
              <Button variant="primary" :disabled="applyingQuota || applyForm.limit_usd === ''" @click="applyQuota(false)">
                {{ applyingQuota ? t('admin.quotas.applying') : t('admin.quotas.apply') }}
              </Button>
              <Button variant="ghost" :disabled="applyingQuota" @click="applyQuota(true)">
                {{ t('admin.quotas.clear') }}
              </Button>
            </div>
          </div>
        </SettingCard>
      </div>

      <!-- ===================== ACTIVITY ===================== -->
      <div v-show="activeTab === 'activity'" class="admin-panel">
        <EmptyState bordered icon="clock" :title="t('admin.tab.activity')" :tag="t('x.soon')" :desc="t('admin.activity.empty')" />
      </div>
    </template>

    <!-- ===================== AGENT PROFILE EDITOR ===================== -->
    <Modal v-model="editorOpen" :title="t('admin.agents.editor_title')" maxWidth="720px">
      <p class="editor-desc">{{ t('admin.agents.editor_desc') }}</p>

      <div class="editor-grid">
        <div class="editor-form">
          <div class="ed-field">
            <label class="field-label">{{ t('admin.agents.f_label') }}</label>
            <div class="ed-readonly">{{ editForm.label }} <code class="mono">{{ editForm.project_key }}</code></div>
          </div>

          <div class="ed-row">
            <div class="ed-field ed-field--grow">
              <label class="field-label">{{ t('admin.agents.f_icon') }}</label>
              <div class="icon-picker">
                <button
                  v-for="ic in AGENT_ICONS"
                  :key="ic"
                  type="button"
                  class="icon-opt"
                  :class="{ on: editForm.icon === ic }"
                  :aria-pressed="editForm.icon === ic"
                  @click="editForm.icon = ic"
                >
                  <Icon :name="ic" :size="18" />
                </button>
              </div>
            </div>
          </div>

          <div class="ed-row">
            <div class="ed-field">
              <label class="field-label">{{ t('admin.agents.f_badge') }}</label>
              <div class="badge-picker">
                <button
                  v-for="b in BADGES"
                  :key="b || 'none'"
                  type="button"
                  class="badge-opt"
                  :class="{ on: editForm.badge === b }"
                  @click="editForm.badge = b"
                >
                  {{ t('admin.agents.badge.' + (b || 'none')) }}
                </button>
              </div>
            </div>
          </div>

          <div class="ed-field">
            <label class="field-label" for="ed-tagline">
              {{ t('admin.agents.f_tagline') }}
              <span class="ed-count">{{ t('admin.agents.char_count', [editForm.tagline.length, TAGLINE_MAX]) }}</span>
            </label>
            <input
              id="ed-tagline"
              v-model="editForm.tagline"
              type="text"
              :maxlength="TAGLINE_MAX"
              class="ed-input"
              :placeholder="t('admin.agents.f_tagline_ph')"
            />
          </div>

          <div class="ed-field">
            <label class="field-label" for="ed-desc">
              {{ t('admin.agents.f_desc') }}
              <span class="ed-count">{{ t('admin.agents.char_count', [editForm.description.length, DESC_MAX]) }}</span>
            </label>
            <textarea
              id="ed-desc"
              v-model="editForm.description"
              :maxlength="DESC_MAX"
              rows="4"
              class="ed-input ed-textarea"
              :placeholder="t('admin.agents.f_desc_ph')"
            />
          </div>

          <div class="ed-field">
            <label class="field-label" for="ed-caps">{{ t('admin.agents.f_caps') }}</label>
            <textarea
              id="ed-caps"
              v-model="editForm.capsText"
              rows="4"
              class="ed-input ed-textarea"
              :placeholder="t('admin.agents.f_caps_ph')"
            />
            <p class="ed-hint">{{ t('admin.agents.f_caps_hint') }}</p>
          </div>

          <div class="ed-field">
            <label class="field-label" for="ed-tools">{{ t('admin.agents.f_tools') }}</label>
            <textarea
              id="ed-tools"
              v-model="editForm.toolsText"
              rows="3"
              class="ed-input ed-textarea"
              :placeholder="t('admin.agents.f_tools_ph')"
            />
            <p class="ed-hint">{{ t('admin.agents.f_tools_hint') }}</p>
          </div>
        </div>

        <!-- Live preview of the user-facing card -->
        <aside class="editor-preview">
          <span class="preview-label">{{ t('admin.agents.preview') }}</span>
          <div class="preview-card">
            <div class="preview-top">
              <span class="preview-ico"><Icon :name="editForm.icon || 'robot'" :size="18" /></span>
              <span v-if="editForm.badge" class="bdg" :class="editForm.badge">{{ t('ag.badge.' + editForm.badge) }}</span>
            </div>
            <div class="preview-name">{{ editForm.label }}</div>
            <div v-if="editForm.tagline" class="preview-tagline">{{ editForm.tagline }}</div>
            <div class="preview-desc">{{ editForm.description || t('ag.meta_missing') }}</div>
            <ul v-if="previewCaps.length" class="preview-caps">
              <li v-for="(c, i) in previewCaps" :key="i"><Icon name="check" />{{ c }}</li>
            </ul>
            <div v-if="previewTools.length" class="preview-tools">
              <span v-for="tn in previewTools" :key="tn" class="preview-tool mono">{{ tn }}</span>
            </div>
          </div>
        </aside>
      </div>

      <template #footer>
        <Button variant="ghost" @click="editorOpen = false">{{ t('mode.cancel') }}</Button>
        <Button variant="primary" @click="applyEditor">{{ t('admin.agents.editor_done') }}</Button>
      </template>
    </Modal>
  </PageShell>
</template>

<style scoped>
/* --- Header --- */
.admin-head { margin-bottom: var(--s-5); }
.admin-eyebrow {
  font-size: var(--fs-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--orange);
  margin: 0 0 var(--s-3);
}
.admin-title-row { display: flex; align-items: center; gap: var(--s-3); }
.admin-title {
  font-size: var(--fs-2xl);
  font-weight: 600;
  letter-spacing: -0.025em;
  color: var(--text);
  margin: 0;
}
.admin-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 9.5px;
  font-weight: var(--fw-bold);
  letter-spacing: 0.08em;
  padding: 4px 10px;
  border-radius: var(--r-pill);
  background: var(--orange);
  color: #fff;
}
.admin-badge :deep(.ui-icon) { width: 11px; height: 11px; }
.admin-desc { margin: var(--s-4) 0 0; font-size: var(--fs-md); line-height: 1.6; color: var(--text-2); max-width: 640px; }
.admin-tabs { margin-top: var(--s-6); }

.admin-status { padding: var(--s-6) 0; }
.admin-error { color: var(--danger); }
.admin-panel { padding-top: var(--s-6); display: flex; flex-direction: column; gap: var(--s-4); }
.card-desc { font-size: var(--fs-sm); line-height: 1.6; margin: 0 0 var(--s-4); }

/* --- Overview KPIs --- */
.kpi-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: var(--s-4); }
.kpi {
  display: flex;
  flex-direction: column;
  gap: 7px;
  padding: var(--s-5);
  border: 1px solid var(--border);
  border-radius: var(--r);
  background: var(--bg);
}
.kpi-ico {
  width: 36px;
  height: 36px;
  display: grid;
  place-items: center;
  border-radius: var(--square);
  background: var(--orange-soft-dark);
  color: var(--orange);
  margin-bottom: 4px;
}
.kpi-ico :deep(.ui-icon) { width: 18px; height: 18px; }
.kpi-label { font-size: 11px; font-weight: var(--fw-semibold); letter-spacing: var(--tracking-eyebrow); text-transform: uppercase; color: var(--text-3); }
.kpi-value { font-size: var(--fs-xl); font-weight: 600; color: var(--text); letter-spacing: -0.02em; }

/* --- Storage key-value --- */
.kv { display: grid; grid-template-columns: auto 1fr; gap: 9px var(--s-5); margin: 0 0 var(--s-4); }
.kv dt { font-size: var(--fs-sm); color: var(--text-3); }
.kv dd { font-size: var(--fs-sm); color: var(--text); margin: 0; }
.kv code, .tables code, .pick-id { font-family: var(--font-mono); font-size: 12px; }
.kv-note { font-size: var(--fs-xs); margin: var(--s-3) 0 var(--s-2); }
.prefix-warn { display: inline-flex; align-items: center; gap: 5px; margin-left: 8px; font-size: var(--fs-xs); color: var(--danger); }
.prefix-warn :deep(.ui-icon) { width: 13px; height: 13px; flex-shrink: 0; }
.tables { list-style: none; padding: 0; margin: 0 0 var(--s-3); display: flex; flex-direction: column; gap: 4px; }
.tables code { color: var(--text-2); }

/* --- Agent whitelist + profiles --- */
.field-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  font-weight: var(--fw-semibold);
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: var(--text-3);
}
.agent-pick { display: flex; flex-direction: column; gap: 8px; margin-bottom: var(--s-4); max-width: 380px; }
.select-wrap { position: relative; display: flex; }
.admin-select {
  width: 100%;
  appearance: none;
  -webkit-appearance: none;
  padding: 10px 34px 10px 13px;
  background: var(--bg);
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  color: var(--text);
  cursor: pointer;
  transition: border-color var(--dur) var(--ease);
}
.admin-select:hover { border-color: var(--text-3); }
.admin-select:focus { outline: none; border-color: var(--orange); }
.select-arr { position: absolute; right: 11px; top: 50%; transform: translateY(-50%); pointer-events: none; color: var(--text-3); }
.select-arr :deep(.ui-icon) { width: 15px; height: 15px; }

/* Pickable project agents */
.pick-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.pick-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--r);
  transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.pick-row.on { border-color: var(--orange-line); background: var(--orange-soft-dark); }
.pick-info { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.pick-label { font-size: var(--fs-sm); color: var(--text); font-weight: var(--fw-medium); }
.pick-id { color: var(--text-3); }
.pick-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding: 7px 13px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border-strong);
  font-size: var(--fs-xs);
  font-weight: var(--fw-semibold);
  color: var(--text-2);
  background: var(--bg);
  transition: all var(--dur) var(--ease);
}
.pick-btn:hover { border-color: var(--orange); color: var(--orange); }
.pick-btn.on { background: var(--orange); border-color: var(--orange); color: #fff; }
.pick-btn :deep(.ui-icon) { width: 13px; height: 13px; }

/* Exposed agents list */
.exposed-list { list-style: none; padding: 0; margin: 0 0 var(--s-5); display: flex; flex-direction: column; gap: 8px; }
.exposed-row {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--r);
  background: var(--bg);
  transition: border-color var(--dur) var(--ease);
}
.exposed-row:hover { border-color: var(--border-strong); }
.exposed-ico {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: var(--square);
  display: grid;
  place-items: center;
  background: var(--orange-soft-dark);
  color: var(--orange);
}
.exposed-ico :deep(.ui-icon) { width: 19px; height: 19px; }
.exposed-info { display: flex; flex-direction: column; gap: 5px; min-width: 0; flex: 1; }
.exposed-label { font-size: var(--fs-sm); font-weight: var(--fw-semibold); color: var(--text); }
.exposed-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.exposed-project { font-size: 10.5px; color: var(--text-2); }
.profile-state {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10.5px;
  font-weight: var(--fw-semibold);
  color: var(--text-2);
}
/* The status hue rides on the icon (AA-safe), the label stays readable --text-2. */
.profile-state :deep(.ui-icon) { width: 12px; height: 12px; color: var(--warn); }
.profile-state.ok :deep(.ui-icon) { color: var(--success); }
.exposed-actions { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border-strong);
  font-size: var(--fs-xs);
  font-weight: var(--fw-semibold);
  color: var(--text-2);
  background: var(--bg);
  transition: all var(--dur) var(--ease);
}
.ghost-btn:hover { border-color: var(--orange); color: var(--orange); }
.ghost-btn :deep(.ui-icon) { width: 13px; height: 13px; }
.x-btn {
  width: 30px;
  height: 30px;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--text-3);
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.x-btn:hover { background: var(--danger-soft); color: var(--danger); }
.x-btn :deep(.ui-icon) { width: 14px; height: 14px; }

.agent-actions { display: flex; align-items: center; gap: var(--s-3); flex-wrap: wrap; }
.unsaved {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-xs);
  color: var(--warn);
  font-weight: var(--fw-medium);
}
.unsaved :deep(.ui-icon) { width: 13px; height: 13px; }

/* --- Users table --- */
.table-scroll { overflow-x: auto; }
.admin-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.admin-table th {
  text-align: left;
  font-size: 11px;
  font-weight: var(--fw-semibold);
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: var(--text-3);
  padding: 0 var(--s-4) var(--s-3);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.admin-table td { padding: var(--s-3) var(--s-4); border-bottom: 1px solid var(--border); vertical-align: middle; }
.user-id { color: var(--text); font-weight: var(--fw-medium); }
.you { color: var(--orange); font-size: var(--fs-xs); margin-left: 6px; }
.admin-yes { color: var(--success); }
.admin-yes :deep(.ui-icon), .admin-yes { width: 16px; height: 16px; }
.row-action { text-align: right; }

/* --- Quotas tab --- */
.q-form { display: flex; align-items: flex-end; gap: var(--s-5); flex-wrap: wrap; margin-bottom: var(--s-2); }
.q-form--row { align-items: flex-end; margin-top: var(--s-3); }
.q-field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.q-field--grow { flex: 1; min-width: 160px; }
.q-input {
  padding: 9px 12px; background: var(--bg); border: 1px solid var(--border-strong);
  border-radius: var(--r-sm); font-size: var(--fs-sm); color: var(--text); width: 180px; max-width: 100%;
}
.q-input:focus { outline: none; border-color: var(--orange); box-shadow: 0 0 0 2px var(--orange-soft-dark); }
.q-field--grow .q-input { width: 100%; }
.q-check { display: inline-flex; align-items: center; gap: 9px; font-size: var(--fs-sm); color: var(--text); cursor: pointer; padding-bottom: 9px; }
.q-check input { accent-color: var(--orange); width: 16px; height: 16px; }
.q-hint { font-size: var(--fs-xs); margin: 0 0 var(--s-4); }
.q-subhead { font-size: 11px; font-weight: var(--fw-semibold); letter-spacing: var(--tracking-eyebrow); text-transform: uppercase; color: var(--text-3); margin: var(--s-4) 0 var(--s-3); padding-top: var(--s-4); border-top: 1px solid var(--border); }
.q-temp-active { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: var(--fs-sm); color: var(--text-2); margin: 0 0 var(--s-3); }
.q-temp-active :deep(.ui-icon) { width: 14px; height: 14px; color: var(--orange); flex-shrink: 0; }
.q-link { color: var(--orange); font-size: var(--fs-xs); text-decoration: underline; text-underline-offset: 2px; }
.q-link:hover { color: var(--orange-deep); }

.q-table th, .q-table td { vertical-align: middle; }
.q-check-col { width: 36px; }
.q-table input[type="checkbox"] { accent-color: var(--orange); width: 15px; height: 15px; }
.q-row-sel { background: var(--orange-soft-dark); }
.q-user { display: flex; align-items: center; gap: 6px; }
.q-uid { display: block; font-size: 10.5px; color: var(--text-2); margin-top: 2px; }
.q-usage { min-width: 150px; }
.q-mini-bar { height: 6px; border-radius: var(--r-pill); background: var(--surface-2); overflow: hidden; margin-bottom: 4px; max-width: 130px; }
.q-mini-fill { display: block; height: 100%; background: var(--orange); border-radius: var(--r-pill); }
.q-mini-fill.over { background: var(--danger); }
.q-usage-amt { font-size: 12px; }
.q-src { display: inline-block; padding: 2px 8px; border-radius: var(--r-pill); font-size: 10.5px; font-weight: var(--fw-semibold); }
.q-src.src-default { background: var(--surface-2); color: var(--text-2); }
.q-src.src-user { background: var(--orange-soft-dark); color: var(--orange); }
.q-src.src-temp { background: var(--surface); color: var(--text-2); border: 1px solid var(--border); }
.q-src.src-over { background: var(--danger-soft); color: var(--danger); }
.q-blocked { margin-left: 6px; font-size: 10px; font-weight: var(--fw-bold); letter-spacing: 0.04em; text-transform: uppercase; color: var(--danger); }

.q-apply { margin-top: var(--s-5); padding: var(--s-5); border: 1px solid var(--border-strong); border-radius: var(--r); background: var(--surface); }
.q-apply-head { font-size: var(--fs-sm); font-weight: var(--fw-semibold); color: var(--text); margin-bottom: var(--s-3); }
.q-apply-row { display: flex; align-items: flex-end; gap: var(--s-4); flex-wrap: wrap; margin-bottom: var(--s-4); }
.q-apply .admin-select { min-width: 160px; }

/* --- Profile editor (modal) --- */
.editor-desc { font-size: var(--fs-sm); color: var(--text-2); line-height: 1.6; margin: 0 0 var(--s-5); }
.editor-grid { display: grid; grid-template-columns: 1fr 248px; gap: var(--s-6); align-items: start; }
.editor-form { display: flex; flex-direction: column; gap: var(--s-4); min-width: 0; }
.ed-field { display: flex; flex-direction: column; gap: 7px; }
.ed-field--grow { flex: 1; }
.ed-row { display: flex; gap: var(--s-4); }
.ed-readonly {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 9px 12px; border: 1px solid var(--border); border-radius: var(--r-sm);
  background: var(--surface); font-size: var(--fs-sm); color: var(--text); font-weight: var(--fw-medium);
}
.ed-readonly code { font-size: 11px; color: var(--text-3); }
.ed-count { margin-left: auto; font-size: 10px; font-weight: var(--fw-regular); color: var(--text-3); letter-spacing: 0; text-transform: none; }
.ed-input {
  padding: 9px 12px; background: var(--bg); border: 1px solid var(--border-strong);
  border-radius: var(--r-sm); font-size: var(--fs-sm); color: var(--text); width: 100%; font-family: inherit;
}
.ed-input:focus { outline: none; border-color: var(--orange); box-shadow: 0 0 0 2px var(--orange-soft-dark); }
.ed-input::placeholder { color: var(--text-3); }
.ed-textarea { resize: vertical; line-height: 1.5; min-height: 64px; }
.ed-hint { font-size: var(--fs-xs); color: var(--text-3); margin: 0; }

.icon-picker { display: flex; flex-wrap: wrap; gap: 6px; }
.icon-opt {
  width: 34px; height: 34px; display: grid; place-items: center;
  border: 1px solid var(--border); border-radius: var(--r-sm);
  color: var(--text-2); background: var(--bg);
  transition: all var(--dur) var(--ease);
}
.icon-opt:hover { border-color: var(--border-strong); color: var(--text); }
.icon-opt.on { background: var(--orange); border-color: var(--orange); color: #fff; }
.icon-opt :deep(.ui-icon) { width: 17px; height: 17px; }

.badge-picker { display: flex; flex-wrap: wrap; gap: 6px; }
.badge-opt {
  padding: 6px 12px; border: 1px solid var(--border); border-radius: var(--r-pill);
  font-size: var(--fs-xs); font-weight: var(--fw-medium); color: var(--text-2); background: var(--bg);
  transition: all var(--dur) var(--ease);
}
.badge-opt:hover { border-color: var(--border-strong); color: var(--text); }
.badge-opt.on { background: var(--text); border-color: var(--text); color: var(--bg); }

/* Editor preview card */
.editor-preview { position: sticky; top: 0; display: flex; flex-direction: column; gap: 8px; }
.preview-label { font-size: 10px; font-weight: var(--fw-semibold); letter-spacing: var(--tracking-eyebrow); text-transform: uppercase; color: var(--text-3); }
.preview-card {
  display: flex; flex-direction: column; gap: 9px;
  padding: var(--s-5); border: 1px solid var(--border); border-radius: var(--r); background: var(--bg);
}
.preview-top { display: flex; align-items: center; justify-content: space-between; }
.preview-ico { width: 38px; height: 38px; border-radius: var(--square); display: grid; place-items: center; background: var(--orange-soft-dark); color: var(--orange); }
.preview-ico :deep(.ui-icon) { width: 18px; height: 18px; }
.preview-name { font-size: var(--fs-md); font-weight: var(--fw-bold); color: var(--text); letter-spacing: var(--tracking-tight); line-height: 1.25; }
.preview-tagline { font-size: var(--fs-xs); color: var(--orange); font-weight: var(--fw-semibold); margin-top: -4px; }
.preview-desc { font-size: 12px; color: var(--text-2); line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
.preview-caps { list-style: none; padding: 0; margin: 2px 0 0; display: flex; flex-direction: column; gap: 6px; }
.preview-caps li { display: flex; align-items: flex-start; gap: 7px; font-size: 11.5px; color: var(--text); line-height: 1.4; }
.preview-caps :deep(.ui-icon) { width: 13px; height: 13px; color: var(--orange); flex-shrink: 0; margin-top: 1px; }
.preview-tools { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 2px; }
.preview-tool { font-size: 10.5px; padding: 3px 7px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-xs); color: var(--text-2); }

/* Badges reused in preview */
.bdg { font-size: 9px; letter-spacing: 0.06em; padding: 2px 8px; border-radius: var(--r-pill); font-weight: var(--fw-bold); text-transform: uppercase; }
.bdg.default { background: var(--orange-soft-dark); color: var(--orange); }
.bdg.new { background: var(--orange); color: #fff; }
.bdg.beta { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border); }

@media (max-width: 760px) {
  .kpi-grid { grid-template-columns: 1fr; }
  .q-input { width: 140px; }
  .editor-grid { grid-template-columns: 1fr; }
  .editor-preview { position: static; }
}
</style>
