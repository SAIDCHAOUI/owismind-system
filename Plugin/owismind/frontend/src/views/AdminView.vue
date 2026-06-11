<script setup>
// Admin space (Phase 4) — dressed à la maquette admin console (tabbed) but HONEST:
// only the features with a real, validated backend are wired (storage view,
// agent whitelist, users + admin flag). The maquette's mock-driven tabs (org
// budget, per-user quotas, activity feed) have NO backend, so they are labeled
// empty states — never fake KPIs/spend/activity.
//
// The data + actions are ported verbatim from the validated AdminPanel.vue logic
// (same 7 endpoints, same error handling); only the UI is new. The route is
// already server-gated AND guarded client-side (router meta.requiresAdmin).
import { ref, computed, onMounted } from 'vue'
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
} from '../services/backend.js'
import { PageShell, SettingCard, EmptyState } from '../components/pages'
import { Tabs, Button, Icon } from '../components/ui'

const { t } = useI18n()
const session = useSessionStore()
const meId = computed(() => session.user?.user_id || '')

const activeTab = ref('overview')

const loading = ref(true)
const errorMsg = ref('')

const storage = ref(null) // { connection, project_key, table_prefix, namespace, tables }
const users = ref([]) // [{ user_id, display_name, user_groups, is_admin, ... }]
const busyUser = ref('')

// --- Agent whitelist config (ported from AdminPanel.vue) ----------------------
const projects = ref([]) // visible DSS project keys
const selectedProject = ref('') // currently inspected project
const projectAgents = ref([]) // [{ agent_id, description }] for the selected project
const loadingAgents = ref(false)
const enabled = ref([]) // working selection: [{ project_key, agent_id, label }]
const savingAgents = ref(false)
const agentsMsg = ref('')

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
    const [s, u, p, a] = await Promise.all([
      fetchAdminStorage(),
      fetchAdminUsers(),
      fetchAdminProjects(),
      fetchAdminAgents(),
    ])
    storage.value = s.storage
    users.value = u.users || []
    projects.value = p.projects || []
    // Keep only the fields we resend on save; labels come from the backend.
    enabled.value = (a.agents || []).map((e) => ({
      project_key: e.project_key,
      agent_id: e.agent_id,
      label: e.label,
    }))
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
    })
  }
}

function removeEnabled(entry) {
  const idx = enabled.value.findIndex(
    (e) => e.project_key === entry.project_key && e.agent_id === entry.agent_id,
  )
  if (idx >= 0) enabled.value.splice(idx, 1)
}

async function saveAgents() {
  if (savingAgents.value) return
  savingAgents.value = true
  agentsMsg.value = ''
  try {
    const payload = enabled.value.map((e) => ({ project_key: e.project_key, agent_id: e.agent_id }))
    const res = await saveAdminAgents(payload)
    enabled.value = (res.agents || []).map((e) => ({
      project_key: e.project_key,
      agent_id: e.agent_id,
      label: e.label,
    }))
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

// DEV-only: expose the local refs so local visual validation can seed admin data
// without a backend (mirrors main.js window.__pinia). Tree-shaken from prod.
if (import.meta.env.DEV) {
  window.__adminRefs = {
    loading,
    errorMsg,
    storage,
    users,
    projects,
    selectedProject,
    projectAgents,
    enabled,
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
      <!-- OVERVIEW: real KPIs only + storage config -->
      <div v-show="activeTab === 'overview'" class="admin-panel">
        <div class="kpi-grid">
          <div class="kpi">
            <span class="kpi-ico"><Icon name="users" /></span>
            <span class="kpi-label">{{ t('admin.kpi.users') }}</span>
            <span class="kpi-value mono">{{ users.length }}</span>
          </div>
          <div class="kpi">
            <span class="kpi-ico"><Icon name="sparkle" /></span>
            <span class="kpi-label">{{ t('admin.kpi.agents') }}</span>
            <span class="kpi-value mono">{{ enabled.length }}</span>
          </div>
          <div class="kpi">
            <span class="kpi-ico"><Icon name="database" /></span>
            <span class="kpi-label">{{ t('admin.kpi.connection') }}</span>
            <span class="kpi-value mono">{{ storage?.connection || '—' }}</span>
          </div>
        </div>

        <SettingCard v-if="storage" :eyebrow="t('admin.storage.title')">
          <dl class="kv">
            <dt>{{ t('admin.storage.connection') }}</dt>
            <dd><code>{{ storage.connection || '—' }}</code></dd>
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

      <!-- AGENTS: real whitelist config -->
      <div v-show="activeTab === 'agents'" class="admin-panel">
        <SettingCard :eyebrow="t('admin.agents.title')">
          <p class="card-desc muted">{{ t('admin.agents.desc') }}</p>

          <div class="agent-pick">
            <label class="field-label" for="admin-project">{{ t('admin.agents.project') }}</label>
            <div class="select-wrap">
              <select id="admin-project" v-model="selectedProject" class="admin-select" @change="onProjectChange">
                <option value="">{{ t('admin.agents.project_choose') }}</option>
                <option v-for="pk in projects" :key="pk" :value="pk">{{ pk }}</option>
              </select>
              <span class="select-arr"><Icon name="chevronDown" /></span>
            </div>
          </div>

          <p v-if="loadingAgents" class="muted card-desc">{{ t('admin.agents.loading') }}</p>
          <ul v-else-if="projectAgents.length" class="agent-list">
            <li v-for="a in projectAgents" :key="a.agent_id">
              <label class="agent-row">
                <input type="checkbox" :checked="isEnabled(a)" @change="toggleAgent(a)" />
                <span class="agent-label">{{ a.description }}</span>
                <code class="agent-id">{{ a.agent_id }}</code>
              </label>
            </li>
          </ul>
          <p v-else-if="selectedProject" class="muted card-desc">{{ t('admin.agents.none_in_project') }}</p>

          <div v-if="enabled.length" class="enabled-box">
            <p class="field-label">{{ t('admin.agents.enabled_title') }}</p>
            <ul class="tags">
              <li v-for="e in enabled" :key="e.project_key + '::' + e.agent_id" class="tag">
                <span class="tag-label">{{ e.label }}</span>
                <span class="tag-project mono">{{ e.project_key }}</span>
                <button class="tag-x" type="button" :title="t('admin.agents.remove')" @click="removeEnabled(e)">
                  <Icon name="x" />
                </button>
              </li>
            </ul>
          </div>

          <div class="agent-actions">
            <Button variant="primary" :disabled="savingAgents" @click="saveAgents">
              {{ savingAgents ? t('admin.agents.saving') : t('admin.agents.save') }}
            </Button>
            <span v-if="agentsMsg" class="muted card-desc">{{ agentsMsg }}</span>
          </div>
        </SettingCard>
      </div>

      <!-- USERS: real list + admin flag -->
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
                    <Icon v-if="u.is_admin" name="check" class="admin-yes" /><span v-else class="muted">—</span>
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

      <!-- QUOTAS: no budget backend → honest empty state -->
      <div v-show="activeTab === 'quotas'" class="admin-panel">
        <EmptyState bordered icon="wallet" :title="t('admin.tab.quotas')" :tag="t('x.soon')" :desc="t('admin.quotas.empty')" />
      </div>

      <!-- ACTIVITY: no activity backend → honest empty state -->
      <div v-show="activeTab === 'activity'" class="admin-panel">
        <EmptyState bordered icon="clock" :title="t('admin.tab.activity')" :tag="t('x.soon')" :desc="t('admin.activity.empty')" />
      </div>
    </template>
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
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 3px 9px;
  border-radius: var(--r-pill);
  background: var(--orange);
  color: #fff;
}
.admin-badge :deep(.ui-icon) { width: 11px; height: 11px; }
.admin-desc {
  margin: var(--s-4) 0 0;
  font-size: var(--fs-md);
  line-height: 1.6;
  color: var(--text-2);
  max-width: 640px;
}
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
  gap: 6px;
  padding: var(--s-5);
  border: 1px solid var(--border);
  border-radius: var(--r);
  background: var(--bg);
}
.kpi-ico {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--orange-soft-dark);
  color: var(--orange);
  margin-bottom: 4px;
}
.kpi-ico :deep(.ui-icon) { width: 16px; height: 16px; }
.kpi-label { font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-3); }
.kpi-value { font-size: var(--fs-xl); font-weight: 600; color: var(--text); letter-spacing: -0.02em; }

/* --- Storage key-value --- */
.kv { display: grid; grid-template-columns: auto 1fr; gap: 8px var(--s-5); margin: 0 0 var(--s-4); }
.kv dt { font-size: var(--fs-sm); color: var(--text-3); }
.kv dd { font-size: var(--fs-sm); color: var(--text); margin: 0; }
.kv code, .tables code, .agent-id { font-family: var(--font-mono); font-size: 12px; }
.kv-note { font-size: var(--fs-xs); margin: var(--s-3) 0 var(--s-2); }
.prefix-warn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  margin-left: 8px;
  font-size: var(--fs-xs);
  color: var(--danger);
}
.prefix-warn :deep(.ui-icon) { width: 13px; height: 13px; flex-shrink: 0; }
.tables { list-style: none; padding: 0; margin: 0 0 var(--s-3); display: flex; flex-direction: column; gap: 4px; }
.tables code { color: var(--text-2); }

/* --- Agent whitelist --- */
.field-label { font-size: 11px; font-weight: 600; letter-spacing: 0.02em; text-transform: uppercase; color: var(--text-3); }
.agent-pick { display: flex; flex-direction: column; gap: 8px; margin-bottom: var(--s-4); max-width: 360px; }
.select-wrap { position: relative; display: flex; }
.admin-select {
  width: 100%;
  appearance: none;
  -webkit-appearance: none;
  padding: 9px 34px 9px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  color: var(--text);
  cursor: pointer;
}
.admin-select:focus { outline: none; border-color: var(--text-3); }
.select-arr { position: absolute; right: 10px; top: 50%; transform: translateY(-50%); pointer-events: none; color: var(--text-3); }
.select-arr :deep(.ui-icon) { width: 15px; height: 15px; }

.agent-list { list-style: none; padding: 0; margin: 0 0 var(--s-4); display: flex; flex-direction: column; gap: 2px; }
.agent-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: background var(--dur) var(--ease);
}
.agent-row:hover { background: var(--surface-hover); }
.agent-row input { accent-color: var(--orange); width: 15px; height: 15px; flex-shrink: 0; }
.agent-label { font-size: var(--fs-sm); color: var(--text); }
.agent-id { color: var(--text-3); margin-left: auto; }

.enabled-box { margin-bottom: var(--s-4); display: flex; flex-direction: column; gap: 8px; }
.tags { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 8px; }
.tag {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 6px 5px 12px;
  border-radius: var(--r-pill);
  background: var(--orange-soft-dark);
  border: 1px solid var(--border);
}
.tag-label { font-size: var(--fs-sm); color: var(--text); font-weight: 500; }
.tag-project { font-size: 10px; color: var(--text-3); }
.tag-x {
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  color: var(--text-3);
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.tag-x:hover { background: var(--surface-hover); color: var(--text); }
.tag-x :deep(.ui-icon) { width: 12px; height: 12px; }
.agent-actions { display: flex; align-items: center; gap: var(--s-3); flex-wrap: wrap; }

/* --- Users table --- */
.table-scroll { overflow-x: auto; }
.admin-table { width: 100%; border-collapse: collapse; font-size: var(--fs-sm); }
.admin-table th {
  text-align: left;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: var(--text-3);
  padding: 0 var(--s-4) var(--s-3);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
.admin-table td { padding: var(--s-3) var(--s-4); border-bottom: 1px solid var(--border); vertical-align: middle; }
.user-id { color: var(--text); font-weight: 500; }
.you { color: var(--orange); font-size: var(--fs-xs); margin-left: 6px; }
.admin-yes { color: var(--success); }
.admin-yes :deep(.ui-icon), .admin-yes { width: 16px; height: 16px; }
.row-action { text-align: right; }

@media (max-width: 760px) {
  .kpi-grid { grid-template-columns: 1fr; }
}
</style>
