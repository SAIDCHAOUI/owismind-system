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
  adminListBenchmarkTables,
  adminValidateBenchmarkTable,
  adminListSourceDatasets,
} from '../services/backend.js'
import {
  formatMoney,
  formatShortDate,
  usagePct,
  gaugePct,
} from '../composables/budgetModel.js'
import { PageShell, SettingCard, EmptyState } from '../components/pages'
import { Tabs, Button, Icon, Modal } from '../components/ui'
// BEGIN impersonation (temporary) - admin "view as user" picker. Removable:
// delete this import + the openImpersonate handler + the <UserPicker> in the
// template + the impersonatePickerOpen ref, and the features/admin-impersonate folder.
import UserPicker from '../features/admin-impersonate/UserPicker.vue'
// END impersonation (temporary)

const { t, locale } = useI18n()
const session = useSessionStore()
const meId = computed(() => session.user?.user_id || '')

// BEGIN impersonation (temporary) - open the user picker; on pick it reloads the
// webapp as the chosen user (consultation only). Deleting this + its button + the
// modal removes the only AdminView coupling.
const impersonatePickerOpen = ref(false)
function openImpersonate() {
  impersonatePickerOpen.value = true
}
// END impersonation (temporary)

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
// Max source datasets an agent can expose (mirrors server MAX_AGENT_SOURCES).
const MAX_SOURCES = 8
const SOURCE_LABEL_MAX = 60

// Default benchmark block stored with the profile (enabled + where its results live).
function emptyBenchmark() {
  return { enabled: false, connection: 'SQL_owi', table: '', agent_key: '' }
}
function emptyProfile() {
  return {
    tagline: '',
    description: '',
    capabilities: [],
    tools: [],
    icon: 'robot',
    badge: '',
    modes: false,
    benchmark: emptyBenchmark(),
    // Raw project datasets this agent exposes to the Source Data Explorer.
    sources: [],
  }
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
  // Whether this agent supports the chat response-mode dial (Smart / Pro / Claude).
  modes: false,
  // Benchmark block (where this agent's evaluation results live, for the Benchmark tab).
  benchEnabled: false,
  benchConnection: 'SQL_owi',
  benchTable: '',
  benchAgentKey: '',
  // Source datasets the agent exposes: [{ dataset, label }] (edited in place below).
  sources: [],
})

// Benchmark table picker + schema check (loaded lazily inside the editor).
const benchTables = ref([])
const benchTablesLoading = ref(false)
const benchTablesError = ref('')
// { state: 'idle' | 'busy' | 'ok' | 'bad' | 'error', missing: [] }
const benchValidate = reactive({ state: 'idle', missing: [] })

// Source-dataset picker: the project's SQL dataset names, loaded lazily on first
// interaction (a datalist for the free-text dataset inputs). A listing failure
// leaves the inputs usable as free text (the name may still be valid).
const sourceDatasets = ref([])
const sourceDatasetsLoading = ref(false)
const sourceDatasetsError = ref('')
const sourceDatasetsLoaded = ref(false)

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
  const b = (p.benchmark && typeof p.benchmark === 'object') ? p.benchmark : emptyBenchmark()
  editingIndex.value = i
  editForm.label = e.label
  editForm.project_key = e.project_key
  editForm.icon = p.icon || 'robot'
  editForm.badge = p.badge || ''
  editForm.tagline = p.tagline || ''
  editForm.description = p.description || ''
  editForm.capsText = (p.capabilities || []).join('\n')
  editForm.toolsText = (p.tools || []).join('\n')
  editForm.modes = !!p.modes
  editForm.benchEnabled = !!b.enabled
  editForm.benchConnection = b.connection || 'SQL_owi'
  editForm.benchTable = b.table || ''
  editForm.benchAgentKey = b.agent_key || ''
  // Seed the source rows (deep copy, so edits never mutate the stored profile).
  editForm.sources = Array.isArray(p.sources)
    ? p.sources.map((s) => ({
        dataset: String((s && s.dataset) || ''),
        label: String((s && s.label) || ''),
      }))
    : []
  // Reset the table picker + schema check; load tables when a benchmark is on.
  benchTables.value = []
  benchTablesError.value = ''
  benchValidate.state = 'idle'
  benchValidate.missing = []
  if (editForm.benchEnabled) loadBenchTables()
  // Reset the source-dataset picker (loaded lazily on first interaction below).
  sourceDatasets.value = []
  sourceDatasetsError.value = ''
  sourceDatasetsLoaded.value = false
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
      modes: !!editForm.modes,
      benchmark: {
        enabled: !!editForm.benchEnabled,
        connection: editForm.benchConnection.trim() || 'SQL_owi',
        table: editForm.benchTable.trim(),
        agent_key: editForm.benchAgentKey.trim(),
      },
      sources: cleanSources(editForm.sources),
    }
    profilesDirty.value = true
  }
  editorOpen.value = false
}

// Client mirror of the server's validate_sources_block: trim, drop empty-dataset rows,
// de-dup by dataset (case-insensitive, first wins), fall the label back to the dataset
// name, cap at MAX_SOURCES. The server revalidates on save regardless.
function cleanSources(rows) {
  const out = []
  const seen = new Set()
  for (const r of rows || []) {
    const dataset = String((r && r.dataset) || '').trim()
    if (!dataset) continue
    const low = dataset.toLowerCase()
    if (seen.has(low)) continue
    seen.add(low)
    out.push({ dataset, label: String((r && r.label) || '').trim().slice(0, SOURCE_LABEL_MAX) || dataset })
    if (out.length >= MAX_SOURCES) break
  }
  return out
}

// List the tables of the chosen SQL connection (best-effort; the input stays usable as
// free text when the listing is empty or fails - the table may be a physical name).
async function loadBenchTables() {
  benchTablesLoading.value = true
  benchTablesError.value = ''
  try {
    const res = await adminListBenchmarkTables(editForm.benchConnection.trim() || 'SQL_owi')
    benchTables.value = Array.isArray(res.tables) ? res.tables : []
    if (res.error) benchTablesError.value = t('bench.profile.tables_error')
  } catch (e) {
    benchTables.value = []
    benchTablesError.value = t('bench.profile.tables_error')
  } finally {
    benchTablesLoading.value = false
  }
}

// When the benchmark toggle flips on, load the tables once (idempotent).
function onBenchToggle() {
  benchValidate.state = 'idle'
  benchValidate.missing = []
  if (editForm.benchEnabled && !benchTables.value.length && !benchTablesLoading.value) {
    loadBenchTables()
  }
}

// Validate the picked table carries the columns a benchmark needs.
async function validateBenchSchema() {
  const table = editForm.benchTable.trim()
  if (!table) return
  benchValidate.state = 'busy'
  benchValidate.missing = []
  try {
    const res = await adminValidateBenchmarkTable(editForm.benchConnection.trim() || 'SQL_owi', table)
    if (res.error) {
      benchValidate.state = 'error'
    } else if (res.ok) {
      benchValidate.state = 'ok'
    } else {
      benchValidate.state = 'bad'
      benchValidate.missing = Array.isArray(res.missing) ? res.missing : []
    }
  } catch (e) {
    benchValidate.state = 'error'
  }
}

// List the project's SQL dataset names for the source picker datalist (best-effort;
// the inputs stay usable as free text when the listing is empty or fails). Loaded once
// per editor open, unless `force` (the refresh link) re-fetches.
async function loadSourceDatasets(force) {
  if (sourceDatasetsLoading.value) return
  if (sourceDatasetsLoaded.value && !force) return
  sourceDatasetsLoading.value = true
  sourceDatasetsError.value = ''
  try {
    const res = await adminListSourceDatasets()
    sourceDatasets.value = Array.isArray(res.datasets) ? res.datasets : []
    if (res.error) sourceDatasetsError.value = t('src.admin.load_error')
  } catch (e) {
    sourceDatasets.value = []
    sourceDatasetsError.value = t('src.admin.load_error')
  } finally {
    // Mark loaded so focusing another input does not re-fire; Refresh forces a retry.
    sourceDatasetsLoaded.value = true
    sourceDatasetsLoading.value = false
  }
}

function addSource() {
  if (editForm.sources.length >= MAX_SOURCES) return
  editForm.sources.push({ dataset: '', label: '' })
  loadSourceDatasets(false)
}

function removeSource(i) {
  editForm.sources.splice(i, 1)
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
          <!-- BEGIN impersonation (temporary) - "view as user" entry. Opens the user
               picker modal; on pick the webapp reloads as that user (read-only
               consultation). Deleting this button + the modal below + the script
               fences + the features/admin-impersonate folder removes the feature. -->
          <button type="button" class="inspect-link" @click="openImpersonate">
            <Icon name="users" />{{ t('impersonate.open') }}
          </button>
          <!-- END impersonation entry -->
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
            <span class="kpi-ico"><Icon name="users" :size="26" /></span>
            <span class="kpi-label">{{ t('admin.kpi.users') }}</span>
            <!-- Integer count - no mono -->
            <span class="kpi-value">{{ users.length }}</span>
          </div>
          <div class="kpi">
            <span class="kpi-ico"><Icon name="robot" :size="26" /></span>
            <span class="kpi-label">{{ t('admin.kpi.agents') }}</span>
            <!-- Integer count - no mono -->
            <span class="kpi-value">{{ enabled.length }}</span>
          </div>
          <div class="kpi">
            <span class="kpi-ico"><Icon name="database" :size="26" /></span>
            <span class="kpi-label">{{ t('admin.kpi.connection') }}</span>
            <!-- Connection name uses mono per mockup k-val.mono -->
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
            <label class="field-label">{{ t('admin.agents.f_modes') }}</label>
            <label class="ed-check">
              <input type="checkbox" v-model="editForm.modes" />
              <span>{{ t('admin.agents.f_modes_opt') }}</span>
            </label>
            <p class="ed-hint">{{ t('admin.agents.f_modes_hint') }}</p>
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

          <!-- Benchmark: whether this agent has a benchmark + where its results live -->
          <div class="ed-section">
            <div class="ed-section-title">{{ t('bench.profile.section') }}</div>

            <div class="ed-field">
              <label class="ed-check">
                <input type="checkbox" v-model="editForm.benchEnabled" @change="onBenchToggle" />
                <span>{{ t('bench.profile.enabled') }}</span>
              </label>
              <p class="ed-hint">{{ t('bench.profile.enabled_hint') }}</p>
            </div>

            <template v-if="editForm.benchEnabled">
              <div class="ed-field">
                <label class="field-label" for="ed-bench-conn">{{ t('bench.profile.connection') }}</label>
                <input
                  id="ed-bench-conn"
                  v-model="editForm.benchConnection"
                  type="text"
                  class="ed-input"
                  @change="loadBenchTables"
                />
              </div>

              <div class="ed-field">
                <label class="field-label" for="ed-bench-table">{{ t('bench.profile.table') }}</label>
                <input
                  id="ed-bench-table"
                  v-model="editForm.benchTable"
                  type="text"
                  class="ed-input"
                  list="bench-table-list"
                  :placeholder="t('bench.profile.table_ph')"
                />
                <datalist id="bench-table-list">
                  <option v-for="tb in benchTables" :key="tb" :value="tb" />
                </datalist>
                <p v-if="benchTablesLoading" class="ed-hint">{{ t('bench.profile.tables_loading') }}</p>
                <p v-else-if="benchTablesError" class="ed-hint ed-hint--bad">{{ benchTablesError }}</p>
                <button v-else type="button" class="ed-link" @click="loadBenchTables">
                  {{ t('bench.profile.refresh_tables') }}
                </button>
              </div>

              <div class="ed-field">
                <label class="field-label" for="ed-bench-key">{{ t('bench.profile.agent_key') }}</label>
                <input
                  id="ed-bench-key"
                  v-model="editForm.benchAgentKey"
                  type="text"
                  class="ed-input"
                  :placeholder="t('bench.profile.agent_key_ph')"
                />
                <p class="ed-hint">{{ t('bench.profile.agent_key_hint') }}</p>
              </div>

              <div class="ed-field">
                <div class="bench-validate-row">
                  <Button
                    variant="ghost"
                    :disabled="!editForm.benchTable.trim() || benchValidate.state === 'busy'"
                    @click="validateBenchSchema"
                  >
                    {{ benchValidate.state === 'busy' ? t('bench.profile.validating') : t('bench.profile.validate') }}
                  </Button>
                  <span v-if="benchValidate.state === 'ok'" class="bench-vd bench-vd--ok">
                    <Icon name="check" />{{ t('bench.profile.ok') }}
                  </span>
                  <span v-else-if="benchValidate.state === 'bad'" class="bench-vd bench-vd--bad">
                    <Icon name="alert" />{{ t('bench.profile.missing', [benchValidate.missing.join(', ')]) }}
                  </span>
                  <span v-else-if="benchValidate.state === 'error'" class="bench-vd bench-vd--bad">
                    <Icon name="alert" />{{ t('bench.profile.error') }}
                  </span>
                </div>
              </div>
            </template>
          </div>

          <!-- Source datasets: the RAW project datasets this agent exposes to the
               Source Data Explorer (users browse them without writing a query). -->
          <div class="ed-section">
            <div class="ed-section-title">{{ t('src.admin.section') }}</div>
            <p class="ed-hint">{{ t('src.admin.hint') }}</p>

            <div v-for="(s, i) in editForm.sources" :key="i" class="src-row">
              <input
                v-model="s.dataset"
                type="text"
                class="ed-input src-dataset"
                list="src-dataset-list"
                :placeholder="t('src.admin.dataset_ph')"
                @focus="loadSourceDatasets(false)"
              />
              <input
                v-model="s.label"
                type="text"
                class="ed-input src-label"
                :maxlength="SOURCE_LABEL_MAX"
                :placeholder="s.dataset.trim() || t('src.admin.label_ph')"
              />
              <button
                type="button"
                class="src-remove"
                :aria-label="t('src.admin.remove')"
                :title="t('src.admin.remove')"
                @click="removeSource(i)"
              >
                <Icon name="x" :size="14" />
              </button>
            </div>

            <datalist id="src-dataset-list">
              <option v-for="d in sourceDatasets" :key="d" :value="d" />
            </datalist>

            <div class="src-actions">
              <Button variant="ghost" :disabled="editForm.sources.length >= MAX_SOURCES" @click="addSource">
                {{ t('src.admin.add') }}
              </Button>
              <span v-if="sourceDatasetsLoading" class="ed-hint">{{ t('src.loading') }}</span>
              <template v-else-if="sourceDatasetsError">
                <span class="ed-hint ed-hint--bad">{{ sourceDatasetsError }}</span>
                <button type="button" class="ed-link" @click="loadSourceDatasets(true)">
                  {{ t('src.admin.refresh') }}
                </button>
              </template>
            </div>
          </div>
        </div>

        <!-- Live preview of the user-facing agent card (per mockup .pf-card) -->
        <aside class="editor-preview">
          <span class="preview-label">{{ t('admin.agents.preview') }}</span>
          <div class="preview-card">
            <!-- Icon tile above name, per mockup -->
            <span class="preview-ico"><Icon :name="editForm.icon || 'robot'" :size="20" /></span>
            <!-- Name + optional badge on same line, per mockup h5 -->
            <div class="preview-name-row">
              <span class="preview-name">{{ editForm.label }}</span>
              <span v-if="editForm.badge" class="bdg" :class="editForm.badge">{{ t('ag.badge.' + editForm.badge) }}</span>
            </div>
            <div v-if="editForm.tagline" class="preview-tagline">{{ editForm.tagline }}</div>
            <div class="preview-desc">{{ editForm.description || t('ag.meta_missing') }}</div>
            <ul v-if="previewCaps.length" class="preview-caps">
              <li v-for="(c, i) in previewCaps" :key="i"><Icon name="check" />{{ c }}</li>
            </ul>
            <div v-if="previewTools.length" class="preview-tools">
              <span v-for="tn in previewTools" :key="tn" class="preview-tool">{{ tn }}</span>
            </div>
          </div>
        </aside>
      </div>

      <template #footer>
        <Button variant="ghost" @click="editorOpen = false">{{ t('mode.cancel') }}</Button>
        <Button variant="primary" @click="applyEditor">{{ t('admin.agents.editor_done') }}</Button>
      </template>
    </Modal>

    <!-- BEGIN impersonation (temporary) - "view as user" picker modal. -->
    <UserPicker v-model="impersonatePickerOpen" />
    <!-- END impersonation -->
  </PageShell>
</template>

<style scoped>
/* ============================================================
   AdminView - Orange brand restyle
   Design language: white/near-black, orange as RARE accent,
   SHARP/SQUARE geometry (border-radius: 0), flat 1px borders,
   Helvetica Neue heavy typography.
   ============================================================ */

/* --- Header --- */
.admin-head { margin-bottom: var(--s-5); }

.admin-eyebrow {
  /* Orange uppercase eyebrow per mockup */
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--orange);
  margin: 0 0 10px;
}

.admin-title-row { display: flex; align-items: center; gap: 14px; }

.admin-title {
  font-size: 36px;
  font-weight: var(--fw-heavy);
  letter-spacing: -0.01em;
  color: var(--text);
  margin: 0;
  line-height: 1.05;
}

/* Orange title-bar underline (52x4px) */
.admin-head::after {
  content: '';
  display: block;
  width: 52px;
  height: 4px;
  background: var(--orange);
  margin-top: 16px;
}

/* Admin badge: solid orange, white text, square, shield icon */
.admin-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: var(--orange);
  color: #fff;
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 5px 10px;
  /* Square: no border-radius */
}
.admin-badge :deep(.ui-icon) { width: 12px; height: 12px; }

/* Impersonation ("view as user") entry - removable feature. Square ghost button,
   1px border, hover inverts (charter). */
.inspect-link {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-left: auto;
  padding: 8px 14px;
  border: 1px solid var(--border-strong);
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
  background: var(--bg);
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.inspect-link:hover { background: var(--text); border-color: var(--text); color: var(--bg); }
.inspect-link :deep(.ui-icon) { width: 14px; height: 14px; }

.admin-desc {
  margin: 14px 0 0;
  font-size: 15px;
  line-height: 1.6;
  color: var(--text-2);
  max-width: 640px;
}

/* Tabs: :deep() override so Tabs.vue is NOT edited */
.admin-tabs { margin-top: 0; }
.admin-tabs :deep(.tabs-bar) {
  display: flex;
  gap: 28px;
  border-bottom: 1px solid var(--border-strong);
  margin: 34px 0 28px;
}
.admin-tabs :deep(.tab-btn) {
  padding: 0 0 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-2);
  border-bottom: 3px solid transparent;
  margin-bottom: -1px;
  border-radius: 0;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  transition: color var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.admin-tabs :deep(.tab-btn:hover) { color: var(--text); }
.admin-tabs :deep(.tab-btn.active) {
  color: var(--text);
  font-weight: 700;
  border-bottom-color: var(--orange);
}
/* Count chip in tab */
.admin-tabs :deep(.tab-count) {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-3);
}
.admin-tabs :deep(.tab-btn.active .tab-count) { color: var(--orange); }

.admin-status { padding: var(--s-6) 0; }
.admin-error { color: var(--danger); }
.admin-panel { padding-top: var(--s-6); display: flex; flex-direction: column; gap: 16px; }
.card-desc { font-size: 14px; line-height: 1.6; margin: 0 0 18px; color: var(--text-2); }

/* --- Overview KPIs --- */
/* Sharp 3-column grid, orange top rule, orange icon (no tinted square bg) */
.kpi-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }

.kpi {
  display: flex;
  flex-direction: column;
  gap: 0;
  /* Orange top rule, sharp borders, no border-radius */
  border-top: 3px solid var(--orange);
  border: 1px solid var(--border);
  border-top: 3px solid var(--orange);
  background: var(--bg);
  padding: 22px 22px 24px;
}
.kpi-ico {
  /* Orange icon, no background square, just the icon itself */
  width: 26px;
  height: 26px;
  color: var(--orange);
  margin-bottom: 18px;
}
.kpi-ico :deep(.ui-icon) { width: 26px; height: 26px; }
.kpi-label {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-2);
  margin-bottom: 6px;
}
.kpi-value {
  font-size: 30px;
  font-weight: var(--fw-heavy);
  color: var(--text);
  line-height: 1;
}
/* mono for connection name */
.kpi-value.mono { font-family: var(--font-mono); font-size: 24px; }

/* --- Storage key-value --- */
/* Per mockup: 180px label column, mono values */
.kv { display: grid; grid-template-columns: 180px 1fr; gap: 10px 24px; margin: 0 0 18px; }
.kv dt { font-size: 13px; color: var(--text-2); }
.kv dd { margin: 0; font-family: var(--font-mono); font-size: 13px; color: var(--text); }
.kv code, .tables code, .pick-id { font-family: var(--font-mono); font-size: 12.5px; color: var(--text); }
.kv-note { font-size: 13px; color: var(--text-2); margin: 18px 0 10px; }
.prefix-warn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-left: 8px;
  font-size: var(--fs-xs);
  color: var(--danger);
}
.prefix-warn :deep(.ui-icon) { width: 13px; height: 13px; flex-shrink: 0; }
.tables { list-style: none; padding: 0; margin: 0 0 var(--s-3); display: flex; flex-direction: column; gap: 7px; }
.tables code { color: var(--text); }

/* --- Agent whitelist + profiles --- */
/* Field label: uppercase 11px/800, var(--text-2) */
.field-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-2);
  margin-bottom: 8px;
}

.agent-pick { display: flex; flex-direction: column; gap: 8px; margin-bottom: 18px; max-width: 380px; }
.select-wrap { position: relative; display: flex; }
.admin-select {
  width: 100%;
  appearance: none;
  -webkit-appearance: none;
  padding: 11px 34px 11px 14px;
  background: var(--bg);
  /* Sharp: no border-radius, 1px border */
  border: 1px solid var(--border-strong);
  font-size: 14px;
  font-family: var(--font-sans);
  color: var(--text);
  cursor: pointer;
  transition: border-color var(--dur) var(--ease);
}
.admin-select:hover { border-color: var(--text-3); }
.admin-select:focus { outline: none; border-color: var(--orange); }
.select-arr { position: absolute; right: 11px; top: 50%; transform: translateY(-50%); pointer-events: none; color: var(--text-3); }
.select-arr :deep(.ui-icon) { width: 14px; height: 14px; }

/* Pickable project agents */
.pick-list { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 6px; }
.pick-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-3);
  padding: 10px 12px;
  /* Sharp: no border-radius */
  border: 1px solid var(--border);
  transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.pick-row.on { border-color: var(--orange); background: var(--orange-soft-dark); }
.pick-info { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.pick-label { font-size: var(--fs-sm); color: var(--text); font-weight: var(--fw-semibold); }
.pick-id { color: var(--text-3); }
.pick-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding: 7px 13px;
  /* Sharp: no border-radius */
  border: 1px solid var(--border-strong);
  font-size: var(--fs-xs);
  font-weight: var(--fw-semibold);
  color: var(--text-2);
  background: var(--bg);
  transition: all var(--dur) var(--ease);
}
.pick-btn:hover { border-color: var(--orange); color: var(--orange-text); }
.pick-btn.on { background: var(--orange); border-color: var(--orange); color: #fff; }
.pick-btn :deep(.ui-icon) { width: 13px; height: 13px; }

/* Exposed agents list - per mockup: square icon tile with orange border + glyph */
.exposed-list { list-style: none; padding: 0; margin: 0 0 var(--s-5); display: flex; flex-direction: column; gap: 8px; }
.exposed-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  /* Sharp border per mockup */
  border: 1px solid var(--border);
  background: var(--bg);
  transition: border-color var(--dur) var(--ease);
}
.exposed-row:hover { border-color: var(--border-strong); }

/* Square icon tile with orange border + orange glyph (per mockup .agent-ic) */
.exposed-ico {
  width: 40px;
  height: 40px;
  flex: 0 0 40px;
  /* Square: no border-radius */
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--orange);
}
.exposed-ico :deep(.ui-icon) { width: 20px; height: 20px; }
.exposed-info { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1; }
.exposed-label { font-size: 14px; font-weight: var(--fw-heavy); color: var(--text); }
.exposed-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 4px; font-size: 12px; color: var(--text-2); }
.exposed-project { font-family: var(--font-mono); }
.profile-state {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: var(--fw-semibold);
  color: var(--text-2);
}
/* Status icon color only (AA-safe), label stays --text-2 */
.profile-state :deep(.ui-icon) { width: 13px; height: 13px; color: var(--warn); }
.profile-state.ok :deep(.ui-icon) { color: var(--success); }

.exposed-actions { margin-left: auto; display: flex; align-items: center; gap: 6px; flex-shrink: 0; }

/* Ghost button: square, 1px border per mockup .btn.btn-sm */
.ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 13px;
  /* Square: no border-radius */
  border: 1px solid var(--border-strong);
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
  background: var(--bg);
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.ghost-btn:hover { background: var(--text); border-color: var(--text); color: var(--bg); }
.ghost-btn :deep(.ui-icon) { width: 14px; height: 14px; }

/* X button: square, 1px border per mockup */
.x-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  /* Square: no border-radius */
  border: 1px solid var(--border);
  color: var(--text-2);
  transition: border-color var(--dur) var(--ease), color var(--dur) var(--ease);
}
.x-btn:hover { border-color: var(--text); color: var(--text); }
.x-btn :deep(.ui-icon) { width: 14px; height: 14px; }

.agent-actions { display: flex; align-items: center; gap: var(--s-3); flex-wrap: wrap; }
.unsaved {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-xs);
  color: var(--warn);
  font-weight: var(--fw-semibold);
}
.unsaved :deep(.ui-icon) { width: 13px; height: 13px; }

/* --- Users table --- */
/* Per mockup: uppercase thead, 1px var(--border-strong) rule under header, rows divided by 1px var(--border) */
.table-scroll { overflow-x: auto; }
.admin-table { width: 100%; border-collapse: collapse; font-size: 14px; }
.admin-table th {
  text-align: left;
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-2);
  padding: 0 14px 14px;
  border-bottom: 1px solid var(--border-strong);
  white-space: nowrap;
}
.admin-table td { padding: 16px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }
.admin-table tbody tr:last-child td { border-bottom: none; }
.user-id { font-weight: 700; color: var(--text); }
/* (you) in orange-deep per mockup */
.you { color: var(--orange-text); font-size: 13px; font-weight: 600; margin-left: 6px; }
.admin-yes { color: var(--success); }
.admin-yes :deep(.ui-icon) { width: 16px; height: 16px; }
.row-action { text-align: right; }

/* --- Quotas tab --- */
.q-form { display: flex; align-items: flex-end; gap: var(--s-5); flex-wrap: wrap; margin-bottom: var(--s-2); }
.q-form--row { align-items: flex-end; margin-top: var(--s-3); }
.q-field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.q-field--grow { flex: 1; min-width: 160px; }

.q-input {
  padding: 11px 14px;
  background: var(--bg);
  /* Sharp: no border-radius */
  border: 1px solid var(--border-strong);
  font-size: 14px;
  font-family: var(--font-sans);
  color: var(--text);
  width: 180px;
  max-width: 100%;
}
.q-input:focus { outline: none; border-color: var(--orange); }
.q-field--grow .q-input { width: 100%; }

/* Square checkbox - per mockup .chk (18px, 1.5px border, checked=orange fill + white check) */
.q-check {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: var(--text);
  cursor: pointer;
  padding-bottom: 9px;
}
/* Hide the native checkbox, render the square via ::before + ::after */
.q-check input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 18px;
  height: 18px;
  border: 1.5px solid var(--text);
  background: var(--bg);
  flex-shrink: 0;
  cursor: pointer;
  position: relative;
  transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.q-check input[type="checkbox"]:checked {
  background: var(--orange);
  border-color: var(--orange);
}
.q-check input[type="checkbox"]::after {
  content: '';
  position: absolute;
  display: none;
  left: 4px;
  top: 1px;
  width: 5px;
  height: 9px;
  border: 2px solid #fff;
  border-top: none;
  border-left: none;
  transform: rotate(45deg);
}
.q-check input[type="checkbox"]:checked::after { display: block; }

.q-hint { font-size: 13px; color: var(--text-2); margin: 0 0 var(--s-4); }
.q-subhead {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-2);
  margin: var(--s-4) 0 var(--s-3);
  padding-top: var(--s-4);
  border-top: 1px solid var(--border);
}
.q-temp-active { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: var(--fs-sm); color: var(--text-2); margin: 0 0 var(--s-3); }
.q-temp-active :deep(.ui-icon) { width: 14px; height: 14px; color: var(--orange); flex-shrink: 0; }
.q-link { color: var(--orange-text); font-size: var(--fs-xs); text-decoration: underline; text-underline-offset: 2px; }
.q-link:hover { opacity: 0.8; }

.q-table th, .q-table td { vertical-align: middle; }
.q-check-col { width: 36px; }

/* Square checkboxes in quota table (same custom style) */
.q-table input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 18px;
  height: 18px;
  border: 1.5px solid var(--text);
  background: var(--bg);
  flex-shrink: 0;
  cursor: pointer;
  position: relative;
  transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.q-table input[type="checkbox"]:checked { background: var(--orange); border-color: var(--orange); }
.q-table input[type="checkbox"]::after {
  content: '';
  position: absolute;
  display: none;
  left: 4px;
  top: 1px;
  width: 5px;
  height: 9px;
  border: 2px solid #fff;
  border-top: none;
  border-left: none;
  transform: rotate(45deg);
}
.q-table input[type="checkbox"]:checked::after { display: block; }
@media (prefers-reduced-motion: reduce) {
  .q-check input[type="checkbox"],
  .q-table input[type="checkbox"] { transition: none; }
}

.q-row-sel { background: var(--orange-soft-dark); }
.q-user { display: flex; align-items: center; gap: 6px; }
.q-uid { display: block; font-family: var(--font-mono); font-size: 12px; color: var(--text-3); margin-top: 3px; }
.q-usage { min-width: 150px; }

/* Mini progress bar: sharp, no border-radius */
.q-mini-bar { height: 6px; background: var(--surface-2); overflow: hidden; margin-bottom: 4px; max-width: 130px; }
.q-mini-fill { display: block; height: 100%; background: var(--orange); }
.q-mini-fill.over { background: var(--danger); }
.q-usage-amt { font-size: 12px; }

/* Source tag: square bordered chip per mockup .src-tag */
.q-src {
  display: inline-block;
  border: 1px solid var(--border);
  padding: 3px 8px;
  font-size: 11px;
  font-weight: 700;
  color: var(--text-2);
}
/* Differentiate source types with minimal color */
.q-src.src-user { border-color: var(--orange); color: var(--orange-text); }
.q-src.src-temp { color: var(--text-2); }
.q-src.src-over { border-color: var(--danger); color: var(--danger); }
.q-blocked { margin-left: 6px; font-size: 10px; font-weight: var(--fw-heavy); letter-spacing: 0.04em; text-transform: uppercase; color: var(--danger); }

.q-apply {
  margin-top: var(--s-5);
  padding: var(--s-5);
  /* Sharp border, surface bg */
  border: 1px solid var(--border-strong);
  background: var(--surface);
}
.q-apply-head { font-size: var(--fs-sm); font-weight: var(--fw-semibold); color: var(--text); margin-bottom: var(--s-3); }
.q-apply-row { display: flex; align-items: flex-end; gap: var(--s-4); flex-wrap: wrap; margin-bottom: var(--s-4); }
.q-apply .admin-select { min-width: 160px; }

/* --- Profile editor modal --- */
.editor-desc { font-size: 14px; color: var(--text-2); line-height: 1.6; margin: 0 0 var(--s-5); }

/* Two-column grid: form left, sticky preview right */
.editor-grid { display: grid; grid-template-columns: 1fr 270px; gap: 30px; align-items: start; }
.editor-form { display: flex; flex-direction: column; gap: 18px; min-width: 0; }
.ed-field { display: flex; flex-direction: column; gap: 7px; }
.ed-field--grow { flex: 1; }
.ed-row { display: flex; gap: var(--s-4); }

/* Read-only agent row: square, surface bg */
.ed-readonly {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 11px 14px;
  border: 1px solid var(--border);
  background: var(--surface);
  font-size: var(--fs-sm);
  color: var(--text);
  font-weight: var(--fw-semibold);
}
.ed-readonly code { font-family: var(--font-mono); font-size: 12px; color: var(--text-3); }

/* Char counter in label */
.ed-count {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0;
  text-transform: none;
}

/* Input / textarea: square, 1px border */
.ed-input {
  padding: 11px 14px;
  background: var(--bg);
  border: 1px solid var(--border-strong);
  font-size: 14px;
  font-family: var(--font-sans);
  color: var(--text);
  width: 100%;
}
.ed-input:focus { outline: none; border-color: var(--orange); }
.ed-input::placeholder { color: var(--text-3); }
.ed-textarea { resize: vertical; line-height: 1.5; min-height: 78px; }
.ed-hint { font-size: 13px; color: var(--text-2); margin: 0; }
.ed-hint--bad { color: var(--danger); }

/* Benchmark sub-section inside the profile editor: a labeled block divided by a
   1px rule (square/flat, charter). */
.ed-section {
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--border);
}
.ed-section-title {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-2);
}
.ed-link {
  align-self: flex-start;
  font-size: 12px;
  font-weight: 600;
  color: var(--orange-text);
  text-decoration: underline;
  text-underline-offset: 2px;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
}
.ed-link:hover { opacity: 0.8; }
.bench-validate-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.bench-vd { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; font-weight: 600; }
.bench-vd :deep(.ui-icon) { width: 14px; height: 14px; flex-shrink: 0; }
.bench-vd--ok { color: var(--success); }
.bench-vd--bad { color: var(--danger); }

/* Source datasets: one editable row = dataset input + label input + remove (square). */
.src-row { display: flex; align-items: center; gap: var(--s-3); }
.src-dataset { flex: 1 1 55%; min-width: 0; }
.src-label { flex: 1 1 45%; min-width: 0; }
.src-remove {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  padding: 0;
  background: var(--bg);
  border: 1px solid var(--border-strong);
  color: var(--text-2);
  cursor: pointer;
}
.src-remove:hover { border-color: var(--danger); color: var(--danger); }
.src-remove:focus-visible { outline: none; border-color: var(--orange); }
.src-actions { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }

/* Square checkbox toggle (response-mode support) - same flat/square treatment as the
   quota checkboxes (18px box, 1.5px border, checked = orange fill + white check). */
.ed-check { display: inline-flex; align-items: center; gap: 10px; font-size: 14px; color: var(--text); cursor: pointer; }
.ed-check input[type="checkbox"] {
  appearance: none;
  -webkit-appearance: none;
  width: 18px;
  height: 18px;
  border: 1.5px solid var(--text);
  background: var(--bg);
  flex-shrink: 0;
  cursor: pointer;
  position: relative;
  transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.ed-check input[type="checkbox"]:checked { background: var(--orange); border-color: var(--orange); }
.ed-check input[type="checkbox"]::after {
  content: '';
  position: absolute;
  display: none;
  left: 4px;
  top: 1px;
  width: 5px;
  height: 9px;
  border: 2px solid #fff;
  border-top: none;
  border-left: none;
  transform: rotate(45deg);
}
.ed-check input[type="checkbox"]:checked::after { display: block; }
@media (prefers-reduced-motion: reduce) {
  .ed-check input[type="checkbox"] { transition: none; }
}

/* Icon picker: square grid buttons, selected = orange fill */
.pf-lab {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-2);
  margin-bottom: 8px;
}
.icon-picker { display: grid; grid-template-columns: repeat(10, 1fr); gap: 8px; }
.icon-opt {
  aspect-ratio: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border);
  color: var(--text);
  background: var(--bg);
  transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.icon-opt:hover { border-color: var(--text); }
.icon-opt.on { background: var(--orange); border-color: var(--orange); color: #fff; }
.icon-opt :deep(.ui-icon) { width: 18px; height: 18px; }

/* Badge pills: square bordered pills per mockup */
.badge-picker { display: flex; flex-wrap: wrap; gap: 8px; }
.badge-opt {
  border: 1px solid var(--border);
  padding: 9px 18px;
  font-weight: 700;
  font-size: 13px;
  color: var(--text-2);
  background: var(--bg);
  transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.badge-opt:hover { border-color: var(--text); }
.badge-opt.on { background: var(--text); border-color: var(--text); color: var(--bg); }

/* Editor live preview: sticky right column */
.editor-preview { position: sticky; top: 0; align-self: start; display: flex; flex-direction: column; gap: 12px; }
.preview-label {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-2);
}

/* Preview card: square border per mockup .pf-card */
.preview-card {
  border: 1px solid var(--border);
  padding: 20px;
  background: var(--bg);
  display: flex;
  flex-direction: column;
  gap: 0;
}

/* Preview icon tile: square with orange border + glyph, above the name */
.preview-ico {
  width: 40px;
  height: 40px;
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--orange);
  margin-bottom: 14px;
}
.preview-ico :deep(.ui-icon) { width: 20px; height: 20px; }

/* Name + badge on same line (per mockup h5 with src-tag) */
.preview-name-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0;
}
.preview-name {
  font-size: 16px;
  font-weight: var(--fw-heavy);
  color: var(--text);
  line-height: 1.25;
}
/* Tagline in orange-deep (AA-safe on white/near-black) */
.preview-tagline { font-size: 13px; color: var(--orange-text); font-weight: 700; margin-top: 8px; }
.preview-desc { font-size: 13px; color: var(--text-2); line-height: 1.5; margin-top: 6px; display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
.preview-caps { list-style: none; padding: 0; margin: 14px 0 0; display: flex; flex-direction: column; gap: 6px; }
.preview-caps li { display: flex; align-items: flex-start; gap: 8px; font-size: 13px; color: var(--text); line-height: 1.4; }
.preview-caps :deep(.ui-icon) { width: 15px; height: 15px; color: var(--orange); flex-shrink: 0; margin-top: 1px; }

/* Tool chips: square border per mockup .chip */
.preview-tools { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
.preview-tool {
  border: 1px solid var(--border);
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--text);
  background: var(--bg);
}

/* Badges in preview - square per design (no border-radius) */
.bdg {
  font-size: 9px;
  letter-spacing: 0.06em;
  padding: 2px 8px;
  font-weight: var(--fw-heavy);
  text-transform: uppercase;
}
.bdg.default { background: var(--orange-soft-dark); color: var(--orange-text); }
.bdg.new { background: var(--orange); color: #fff; }
.bdg.beta { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border); }

@media (max-width: 760px) {
  .kpi-grid { grid-template-columns: 1fr; }
  .q-input { width: 140px; }
  .editor-grid { grid-template-columns: 1fr; }
  .editor-preview { position: static; }
  .icon-picker { grid-template-columns: repeat(8, 1fr); }
}
</style>
