<script setup>
// Help & Support hub (route /support) - two tabs on one page:
//   - General feedback: category + optional linked conversation + message, plus a
//     "my feedback" history (status pill + the admin's response once set).
//   - Request an agent: a guided form (DSS project -> that project's SQL tables ->
//     business case / use cases / importance), plus a "my requests" history. The
//     project and table pickers are LIVE (backend catalog, resolved server-side via
//     impersonation) and automatically fall back to manual text entry when the
//     catalog is unavailable or empty - the pure state-machine deciding that lives
//     in composables/catalogFallback.js (unit-tested with node:test, no Vue).
//
// Deep-link: ?tab=feedback|agent (default feedback). AgentsView's "Request an
// agent" button lands here with ?tab=agent. Catalog + history reads are lazy - on
// demand only when the relevant tab is actually opened (instance-safety rule: one
// impersonated call per request, never on mount regardless of the active tab).
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useSessionStore } from '../stores/session.js'
import { useToasts } from '../composables/useToasts.js'
import { useTr } from '../composables/useTr.js'
import { CATALOG_MODE, projectCatalogMode, datasetCatalogMode } from '../composables/catalogFallback.js'
import {
  getCatalogProjects,
  getCatalogDatasets,
  submitGeneralFeedback,
  getMyFeedback,
  submitAgentRequest,
  getMyAgentRequests,
} from '../services/backend.js'
import { PageShell, EmptyState } from '../components/pages'
import { Icon, Button, Tabs } from '../components/ui'

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const session = useSessionStore()
const tr = useTr()
const { push } = useToasts()

// --- Tabs + deep-link (?tab=feedback|agent) -----------------------------------
const VALID_TABS = ['feedback', 'agent']
function tabFromQuery() {
  const q = String(route.query.tab || '')
  return VALID_TABS.includes(q) ? q : 'feedback'
}
const activeTab = ref(tabFromQuery())
const tabItems = computed(() => [
  { key: 'feedback', label: t('sup.tab.feedback') },
  { key: 'agent', label: t('sup.tab.agent') },
])
function onTabChange(key) {
  activeTab.value = key
  router.replace({ query: { ...route.query, tab: key } })
}
// A direct navigation (AgentsView's CTA, browser back/forward) changes the route's
// query without going through onTabChange - stay in sync either way.
watch(
  () => route.query.tab,
  () => {
    activeTab.value = tabFromQuery()
  },
)

// --- Impersonation write fence (an admin viewing as a user is read-only) -------
// Same proactive gate as the chat prompt (stores/chat.js canSend): the server also
// 403s ('impersonation_read_only') every WRITE route while impersonating; this just
// disables the UI ahead of time and explains why (mirrors ChatView's .imp-note).
const impersonateNote = computed(() => {
  if (!session.impersonating) return ''
  const u = session.user
  const label = (u && (u.display_name || u.user_id)) || '-'
  return t('impersonate.readonly_note', [label])
})

// --- Shared helpers (both tabs) -------------------------------------------------

// Feedback and agent requests share the same open / in_progress / resolved enum
// (messages.json's fb.status.* set - reused rather than duplicated per-domain).
function statusLabel(status) {
  if (status === 'in_progress') return t('fb.status.progress')
  if (status === 'resolved') return t('fb.status.resolved')
  return t('fb.status.pending') // 'open' (the write-time default) or unknown
}
function fmtDate(value) {
  if (!value) return ''
  try {
    return new Date(value).toLocaleDateString(locale.value)
  } catch (e) {
    return String(value)
  }
}
function excerpt(text, max) {
  const s = (text || '').trim()
  const cap = max || 160
  return s.length > cap ? s.slice(0, cap).trimEnd() + '…' : s
}
// i18n lookup that degrades to the raw value (instead of vue-i18n's "missing key"
// placeholder) for values the client does not have a label for.
function labelOr(key, fallback) {
  const label = t(key)
  return label === key ? fallback : label
}

// =============================== FEEDBACK TAB ===================================
const FEEDBACK_CATEGORIES = ['bug', 'wrong', 'feature', 'ux', 'perf', 'data', 'routing', 'other']

const category = ref('')
const linkedConv = ref('')
const message = ref('')
const submittingFeedback = ref(false)
const myFeedback = ref([])
const loadingMyFeedback = ref(false)
let feedbackLoadedOnce = false

const conversations = computed(() => session.conversations)
const canSubmitFeedback = computed(
  () => message.value.trim().length > 0 && !session.impersonating && !submittingFeedback.value,
)

async function loadMyFeedback() {
  loadingMyFeedback.value = true
  try {
    const data = await getMyFeedback()
    myFeedback.value = (data && data.items) || []
  } catch (e) {
    myFeedback.value = []
  } finally {
    loadingMyFeedback.value = false
  }
}

async function submitFeedbackForm() {
  if (!canSubmitFeedback.value) return
  submittingFeedback.value = true
  try {
    await submitGeneralFeedback({
      category: category.value || undefined,
      message: message.value.trim(),
      linked_session_id: linkedConv.value || undefined,
    })
    push(t('fb.sent'), { icon: 'check', tone: 'ok' })
    category.value = ''
    linkedConv.value = ''
    message.value = ''
    await loadMyFeedback()
  } catch (e) {
    const code = e && e.message
    push(code === 'impersonation_read_only' ? impersonateNote.value || t('fb.send_failed') : t('fb.send_failed'), {
      icon: 'alert',
      tone: 'warn',
    })
  } finally {
    submittingFeedback.value = false
  }
}

// ============================ REQUEST-AN-AGENT TAB ==============================
const MAX_DATASETS = 25

// --- Step 1: project - dropdown fed by /catalog/projects, or manual key entry. ---
const projectsResponse = ref(null)
const projectsLoading = ref(false)
const selectedProjectKey = ref('')
const manualProjectKey = ref('')

const projectMode = computed(() => projectCatalogMode(projectsResponse.value))
const projects = computed(() =>
  projectsResponse.value && projectsResponse.value.ok && Array.isArray(projectsResponse.value.projects)
    ? projectsResponse.value.projects
    : [],
)
const selectedProjectLabel = computed(() => {
  const p = projects.value.find((x) => x.key === selectedProjectKey.value)
  return p ? p.label || p.key : ''
})

async function loadProjects() {
  projectsLoading.value = true
  try {
    projectsResponse.value = await getCatalogProjects()
  } catch (e) {
    projectsResponse.value = { ok: false, reason: 'error' }
  } finally {
    projectsLoading.value = false
  }
}

// --- Step 2: SQL tables of the chosen project, or a manual fallback. ---
const datasetsResponse = ref(null)
const datasetsLoading = ref(false)
const selectedDatasets = ref([]) // [{dataset, table, connection}]
const manualTablesText = ref('')

const datasetMode = computed(() => datasetCatalogMode(datasetsResponse.value))
const datasetsList = computed(() =>
  datasetsResponse.value && datasetsResponse.value.ok && Array.isArray(datasetsResponse.value.datasets)
    ? datasetsResponse.value.datasets
    : [],
)
function datasetKey(ds) {
  return [ds.connection || '', ds.dataset || '', ds.table || ''].join('::')
}
function isDatasetSelected(ds) {
  const k = datasetKey(ds)
  return selectedDatasets.value.some((d) => datasetKey(d) === k)
}
function toggleDataset(ds) {
  const k = datasetKey(ds)
  if (isDatasetSelected(ds)) {
    selectedDatasets.value = selectedDatasets.value.filter((d) => datasetKey(d) !== k)
    return
  }
  if (selectedDatasets.value.length >= MAX_DATASETS) return
  selectedDatasets.value = [
    ...selectedDatasets.value,
    { dataset: ds.dataset, table: ds.table, connection: ds.connection },
  ]
}

async function loadDatasets(projectKey) {
  datasetsLoading.value = true
  try {
    datasetsResponse.value = await getCatalogDatasets(projectKey)
  } catch (e) {
    datasetsResponse.value = { ok: false, reason: 'error' }
  } finally {
    datasetsLoading.value = false
  }
}

// Re-fetch the dataset catalog whenever the chosen project changes; reset the
// selection (a table picked for a previous project makes no sense for a new one).
watch(selectedProjectKey, (key) => {
  datasetsResponse.value = null
  selectedDatasets.value = []
  if (projectMode.value === CATALOG_MODE.CATALOG && key) loadDatasets(key)
})

// Manual table names -> the same {dataset, table, connection} shape the backend
// expects (no connection known in manual mode). One name per line or comma,
// de-duplicated, capped client-side to mirror the server bound.
function parseManualTables(text) {
  const seen = new Set()
  const out = []
  for (const raw of (text || '').split(/[\n,]/)) {
    const name = raw.trim()
    if (!name || seen.has(name)) continue
    seen.add(name)
    out.push({ dataset: name, table: name, connection: '' })
    if (out.length >= MAX_DATASETS) break
  }
  return out
}

// --- Step 3: business case / use cases / importance. ---
const businessCase = ref('')
const useCases = ref('')
const importance = ref('')
const submittingRequest = ref(false)
const myRequests = ref([])
const loadingMyRequests = ref(false)
let requestsLoadedOnce = false

const effectiveProjectKey = computed(() =>
  projectMode.value === CATALOG_MODE.MANUAL ? manualProjectKey.value.trim() : selectedProjectKey.value,
)
const effectiveProjectLabel = computed(() =>
  projectMode.value === CATALOG_MODE.MANUAL ? manualProjectKey.value.trim() : selectedProjectLabel.value,
)
const effectiveDatasets = computed(() => {
  const manual = projectMode.value === CATALOG_MODE.MANUAL || datasetMode.value === CATALOG_MODE.MANUAL
  return manual ? parseManualTables(manualTablesText.value) : selectedDatasets.value
})
const canSubmitAgentRequest = computed(
  () =>
    effectiveProjectKey.value.length > 0 &&
    businessCase.value.trim().length > 0 &&
    !session.impersonating &&
    !submittingRequest.value,
)

async function loadMyRequests() {
  loadingMyRequests.value = true
  try {
    const data = await getMyAgentRequests()
    myRequests.value = (data && data.items) || []
  } catch (e) {
    myRequests.value = []
  } finally {
    loadingMyRequests.value = false
  }
}

async function submitAgentRequestForm() {
  if (!canSubmitAgentRequest.value) return
  submittingRequest.value = true
  try {
    await submitAgentRequest({
      project_key: effectiveProjectKey.value,
      project_label: effectiveProjectLabel.value || effectiveProjectKey.value,
      datasets: effectiveDatasets.value,
      business_case: businessCase.value.trim(),
      use_cases: useCases.value.trim() || undefined,
      importance: importance.value.trim() || undefined,
    })
    push(t('ar.sent'), { icon: 'check', tone: 'ok' })
    selectedProjectKey.value = ''
    manualProjectKey.value = ''
    datasetsResponse.value = null
    selectedDatasets.value = []
    manualTablesText.value = ''
    businessCase.value = ''
    useCases.value = ''
    importance.value = ''
    await loadMyRequests()
  } catch (e) {
    const code = e && e.message
    push(code === 'impersonation_read_only' ? impersonateNote.value || t('ar.send_failed') : t('ar.send_failed'), {
      icon: 'alert',
      tone: 'warn',
    })
  } finally {
    submittingRequest.value = false
  }
}

// The stored request's datasets (re-parsed by the backend from JSON), as a compact
// mono line for the history card.
function requestDatasetsText(item) {
  const list = Array.isArray(item.datasets) ? item.datasets : []
  if (!list.length) return ''
  return list
    .map((d) => (d && (d.table || d.dataset)) || '')
    .filter(Boolean)
    .join(', ')
}

// --- Lazy per-tab loads: on demand only, when the relevant tab is actually open. -
watch(
  activeTab,
  (tab) => {
    if (tab === 'feedback' && !feedbackLoadedOnce) {
      feedbackLoadedOnce = true
      loadMyFeedback()
    }
    if (tab === 'agent') {
      if (!requestsLoadedOnce) {
        requestsLoadedOnce = true
        loadMyRequests()
      }
      if (projectsResponse.value === null && !projectsLoading.value) loadProjects()
    }
  },
  { immediate: true },
)
</script>

<template>
  <PageShell :eyebrow="t('sup.eyebrow')" :title="t('sup.title')" :desc="t('sup.desc')">
    <Tabs :items="tabItems" :model-value="activeTab" @update:model-value="onTabChange" />

    <div class="sup-tab-body">
      <!-- ============================ FEEDBACK TAB ============================ -->
      <div v-if="activeTab === 'feedback'" class="sup-grid">
        <div class="sup-col">
          <h3 class="sup-col-title">{{ t('fb.new_request') }}</h3>

          <div v-if="impersonateNote" class="imp-note">
            <Icon name="users" /><span>{{ impersonateNote }}</span>
          </div>

          <form class="sup-form" @submit.prevent="submitFeedbackForm">
            <div class="sup-field">
              <label class="sup-label" for="fb-cat">{{ t('fb.category') }}</label>
              <div class="sup-select-wrap">
                <select id="fb-cat" v-model="category" class="sup-input sup-select">
                  <option value="" disabled>{{ t('fb.cat.choose') }}</option>
                  <option v-for="c in FEEDBACK_CATEGORIES" :key="c" :value="c">{{ t('fb.cat.' + c) }}</option>
                </select>
                <span class="sup-select-arr"><Icon name="chevronDown" /></span>
              </div>
            </div>

            <div class="sup-field">
              <label class="sup-label" for="fb-conv">{{ t('fb.linked') }}</label>
              <div class="sup-select-wrap">
                <select id="fb-conv" v-model="linkedConv" class="sup-input sup-select" :disabled="!conversations.length">
                  <option value="">-</option>
                  <option v-for="c in conversations" :key="c.id" :value="c.id">{{ tr(c.title) }}</option>
                </select>
                <span class="sup-select-arr"><Icon name="chevronDown" /></span>
              </div>
            </div>

            <div class="sup-field">
              <label class="sup-label" for="fb-msg">{{ t('fb.message') }}</label>
              <textarea
                id="fb-msg"
                v-model="message"
                class="sup-input sup-textarea"
                :placeholder="t('fb.placeholder')"
                rows="5"
                maxlength="8000"
              />
            </div>

            <div class="sup-submit-row">
              <Button type="submit" variant="primary" :disabled="!canSubmitFeedback">
                {{ submittingFeedback ? t('bench.form.submitting') : t('fb.submit') }}
              </Button>
            </div>
          </form>
        </div>

        <div class="sup-col">
          <h3 class="sup-col-title">{{ t('fb.your_requests') }}</h3>
          <p v-if="loadingMyFeedback && !myFeedback.length" class="sup-mine-state">{{ t('fb.mine.loading') }}</p>
          <EmptyState v-else-if="!myFeedback.length" bordered icon="document" :title="t('fb.mine.empty')" />
          <div v-else class="sup-mine-list">
            <div v-for="item in myFeedback" :key="item.feedback_id" class="sup-mine-item">
              <div class="sup-mine-top">
                <span v-if="item.category" class="sup-chip">{{ labelOr('fb.cat.' + item.category, item.category) }}</span>
                <span class="status-pill" :class="item.status">{{ statusLabel(item.status) }}</span>
                <span class="sup-mine-date mono">{{ fmtDate(item.created_at) }}</span>
              </div>
              <p class="sup-mine-message">{{ excerpt(item.message) }}</p>
              <div v-if="item.admin_response" class="sup-mine-response">
                <span class="sup-mine-response-label">{{ t('fb.admin_response') }}</span>
                <p>{{ item.admin_response }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- =========================== REQUEST AN AGENT ========================= -->
      <div v-else class="sup-grid">
        <div class="sup-col">
          <h3 class="sup-col-title">{{ t('sup.tab.agent') }}</h3>

          <div v-if="impersonateNote" class="imp-note">
            <Icon name="users" /><span>{{ impersonateNote }}</span>
          </div>

          <form class="sup-form" @submit.prevent="submitAgentRequestForm">
            <!-- Step 1: project -->
            <div class="sup-step">
              <div class="sup-step-label">1. {{ t('ar.step_project') }}</div>
              <p v-if="projectMode === 'loading'" class="sup-hint">{{ t('ar.loading_projects') }}</p>
              <div v-else-if="projectMode === 'catalog'" class="sup-select-wrap">
                <select v-model="selectedProjectKey" class="sup-input sup-select">
                  <option value="" disabled>{{ t('ar.choose_project') }}</option>
                  <option v-for="p in projects" :key="p.key" :value="p.key">{{ p.label || p.key }}</option>
                </select>
                <span class="sup-select-arr"><Icon name="chevronDown" /></span>
              </div>
              <template v-else>
                <label class="sup-label" for="ar-project-key">{{ t('ar.project_key_label') }}</label>
                <input
                  id="ar-project-key"
                  v-model="manualProjectKey"
                  type="text"
                  class="sup-input"
                  maxlength="200"
                  :placeholder="t('ar.project_key_placeholder')"
                />
                <p class="sup-manual-note"><Icon name="info" />{{ t('ar.manual_note') }}</p>
              </template>
            </div>

            <!-- Step 2: SQL tables -->
            <div class="sup-step">
              <div class="sup-step-label">2. {{ t('ar.step_tables') }}</div>
              <textarea
                v-if="projectMode === 'manual'"
                v-model="manualTablesText"
                class="sup-input sup-textarea"
                rows="3"
                maxlength="4000"
                :placeholder="t('ar.manual_tables_placeholder')"
              />
              <p v-else-if="!selectedProjectKey" class="sup-hint">{{ t('ar.select_project_first') }}</p>
              <p v-else-if="datasetMode === 'loading'" class="sup-hint">{{ t('ar.loading_datasets') }}</p>
              <template v-else-if="datasetMode === 'catalog'">
                <p class="sup-selected-count mono">{{ t('ar.selected_count', [selectedDatasets.length]) }}</p>
                <div v-if="datasetsList.length" class="sup-dataset-list">
                  <button
                    v-for="ds in datasetsList"
                    :key="datasetKey(ds)"
                    type="button"
                    class="sup-check-row"
                    role="checkbox"
                    :aria-checked="isDatasetSelected(ds)"
                    @click="toggleDataset(ds)"
                  >
                    <span class="sup-checkbox" :class="{ on: isDatasetSelected(ds) }">
                      <Icon v-if="isDatasetSelected(ds)" name="check" :size="12" />
                    </span>
                    <span class="sup-check-text">
                      <span class="sup-check-name mono">{{ ds.dataset }}</span>
                      <span class="sup-check-meta">{{ ds.table }} &middot; {{ ds.connection }}</span>
                    </span>
                  </button>
                </div>
                <p v-else class="sup-hint">{{ t('ar.no_datasets') }}</p>
              </template>
              <template v-else>
                <textarea
                  v-model="manualTablesText"
                  class="sup-input sup-textarea"
                  rows="3"
                  maxlength="4000"
                  :placeholder="t('ar.manual_tables_placeholder')"
                />
                <p class="sup-manual-note"><Icon name="info" />{{ t('ar.manual_tables_note') }}</p>
              </template>
            </div>

            <!-- Step 3: business case -->
            <div class="sup-step">
              <div class="sup-step-label">3. {{ t('ar.step_details') }}</div>
              <div class="sup-field">
                <label class="sup-label" for="ar-case">{{ t('ar.business_case_label') }}</label>
                <textarea
                  id="ar-case"
                  v-model="businessCase"
                  class="sup-input sup-textarea"
                  rows="4"
                  maxlength="4000"
                  :placeholder="t('ar.business_case_placeholder')"
                />
              </div>
              <div class="sup-field">
                <label class="sup-label" for="ar-uc">{{ t('ar.use_cases_label') }}</label>
                <textarea
                  id="ar-uc"
                  v-model="useCases"
                  class="sup-input sup-textarea"
                  rows="3"
                  maxlength="4000"
                  :placeholder="t('ar.use_cases_placeholder')"
                />
              </div>
              <div class="sup-field">
                <label class="sup-label" for="ar-imp">{{ t('ar.importance_label') }}</label>
                <textarea
                  id="ar-imp"
                  v-model="importance"
                  class="sup-input sup-textarea"
                  rows="2"
                  maxlength="2000"
                  :placeholder="t('ar.importance_placeholder')"
                />
              </div>
            </div>

            <div class="sup-submit-row">
              <Button type="submit" variant="primary" :disabled="!canSubmitAgentRequest">
                {{ submittingRequest ? t('bench.form.submitting') : t('ar.submit') }}
              </Button>
            </div>
          </form>
        </div>

        <div class="sup-col">
          <h3 class="sup-col-title">{{ t('ar.mine.title') }}</h3>
          <p v-if="loadingMyRequests && !myRequests.length" class="sup-mine-state">{{ t('ar.mine.loading') }}</p>
          <EmptyState v-else-if="!myRequests.length" bordered icon="database" :title="t('ar.mine.empty')" />
          <div v-else class="sup-mine-list">
            <div v-for="item in myRequests" :key="item.request_id" class="sup-mine-item">
              <div class="sup-mine-top">
                <span class="sup-chip mono">{{ item.project_label || item.project_key }}</span>
                <span class="status-pill" :class="item.status">{{ statusLabel(item.status) }}</span>
                <span class="sup-mine-date mono">{{ fmtDate(item.created_at) }}</span>
              </div>
              <p class="sup-mine-message">{{ excerpt(item.business_case) }}</p>
              <p v-if="requestDatasetsText(item)" class="sup-mine-tables mono">{{ requestDatasetsText(item) }}</p>
              <div v-if="item.admin_response" class="sup-mine-response">
                <span class="sup-mine-response-label">{{ t('ar.admin_response') }}</span>
                <p>{{ item.admin_response }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </PageShell>
</template>

<style scoped>
/* Orange charter: square geometry (border-radius 0), 1px borders, flat surfaces,
   orange a RARE accent. Semantic tokens only - no gradient/blur/glow/color-mix. */

.sup-tab-body {
  margin-top: var(--s-6);
}

.sup-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s-7);
  align-items: start;
}
.sup-col-title {
  font-size: var(--fs-lg);
  font-weight: var(--fw-heavy);
  letter-spacing: -0.01em;
  color: var(--text);
  margin: 0 0 var(--s-5);
}

/* --- Impersonation read-only note (mirrors ChatView's .imp-note exactly). --- */
.imp-note {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0 0 var(--s-4);
  padding: 10px 14px;
  border: 1px solid var(--border-strong);
  border-left: 4px solid var(--orange);
  border-radius: 0;
  background: var(--surface);
  color: var(--text);
  font-size: var(--fs-sm);
  line-height: 1.5;
}
.imp-note :deep(.ui-icon) { width: 16px; height: 16px; flex-shrink: 0; color: var(--orange); }

/* --- Form ------------------------------------------------------------------- */
.sup-form { display: flex; flex-direction: column; gap: var(--s-5); }
.sup-step { display: flex; flex-direction: column; gap: var(--s-3); }
.sup-step-label {
  font-size: 11px;
  font-weight: var(--fw-heavy);
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--text-2);
}
.sup-field { display: flex; flex-direction: column; gap: 8px; }
.sup-label {
  font-size: var(--fs-sm);
  font-weight: var(--fw-semibold, 600);
  color: var(--text-2);
}

.sup-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  font-size: var(--fs-base);
  transition: border-color var(--dur) var(--ease);
}
.sup-input:focus { outline: none; border-color: var(--orange); }
.sup-input::placeholder { color: var(--text-3); }
.sup-input:disabled { color: var(--text-3); cursor: not-allowed; }
.sup-textarea { resize: vertical; line-height: 1.55; }

.sup-select-wrap { position: relative; display: flex; }
.sup-select { appearance: none; -webkit-appearance: none; padding-right: 34px; cursor: pointer; }
.sup-select-arr {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
  color: var(--text-3);
}
.sup-select-arr :deep(.ui-icon) { width: 15px; height: 15px; }

.sup-hint { margin: 0; font-size: var(--fs-sm); color: var(--text-3); }
.sup-manual-note {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin: 2px 0 0;
  font-size: var(--fs-xs);
  color: var(--text-3);
  line-height: 1.5;
}
.sup-manual-note :deep(.ui-icon) { width: 13px; height: 13px; flex-shrink: 0; margin-top: 2px; }

.sup-submit-row { display: flex; align-items: center; gap: var(--s-3); }

/* --- SQL dataset multi-select (square checkbox rows, charter recipe) -------- */
.sup-selected-count { font-size: var(--fs-xs); color: var(--text-3); margin: -2px 0 0; }
.sup-dataset-list {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border-strong);
  max-height: 280px;
  overflow-y: auto;
}
.sup-check-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  padding: 9px 12px;
  border: none;
  border-bottom: 1px solid var(--border);
  background: transparent;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: background var(--dur) var(--ease);
}
.sup-check-row:last-child { border-bottom: none; }
.sup-check-row:hover { background: var(--surface); }
.sup-check-row:focus-visible { outline: 2px solid var(--orange); outline-offset: -2px; }
.sup-checkbox {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  margin-top: 2px;
  border: 1.5px solid var(--text);
  border-radius: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #fff;
}
.sup-checkbox.on { background: var(--orange); border-color: var(--orange); }
.sup-checkbox :deep(.ui-icon) { width: 12px; height: 12px; }
.sup-check-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.sup-check-name { font-size: var(--fs-sm); color: var(--text); word-break: break-word; }
.sup-check-meta { font-size: var(--fs-xs); color: var(--text-3); }

/* --- "My submissions" history (both tabs) ----------------------------------- */
.sup-mine-state { font-size: var(--fs-sm); color: var(--text-3); margin: 0; }
.sup-mine-list { display: flex; flex-direction: column; gap: var(--s-4); }
.sup-mine-item {
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--bg);
  padding: var(--s-4) var(--s-5);
}
.sup-mine-top { display: flex; align-items: center; gap: var(--s-3); flex-wrap: wrap; margin-bottom: 8px; }
.sup-mine-date { margin-left: auto; font-size: var(--fs-xs); color: var(--text-3); }
.sup-mine-message { margin: 0; font-size: var(--fs-sm); color: var(--text); line-height: 1.55; }
.sup-mine-tables { margin: 6px 0 0; font-size: var(--fs-xs); color: var(--text-2); }

.sup-chip {
  display: inline-block;
  padding: 2px 8px;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-2);
}

.status-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 0;
  font-size: 11px;
  font-weight: 700;
  border: 1px solid var(--border-strong);
  color: var(--text-2);
  background: var(--surface);
}
.status-pill.in_progress { border-color: var(--orange); color: var(--orange-text); }
.status-pill.resolved { border-color: var(--success); color: var(--success); }

.sup-mine-response {
  margin-top: 10px;
  padding: 9px 12px;
  border-left: 3px solid var(--orange);
  background: var(--surface);
}
.sup-mine-response-label {
  display: block;
  font-size: 10px;
  font-weight: var(--fw-heavy);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-3);
  margin-bottom: 4px;
}
.sup-mine-response p { margin: 0; font-size: var(--fs-sm); color: var(--text); line-height: 1.5; }

.mono { font-family: var(--font-mono); }

@media (max-width: 760px) {
  .sup-grid { grid-template-columns: 1fr; }
}
</style>
