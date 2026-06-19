<script setup>
// UserPicker - the admin-only modal that lists every user and, on a row click, starts
// impersonating that user ("view as"). It is opened from AdminView's "Review
// conversations" button. Reuses the shared Modal primitive; lists users via the
// existing admin client (fetchAdminUsers - no new admin endpoint).
//
// On pick: persist the target in sessionStorage then reload, so /me resolves the
// impersonated identity and every request carries the header from the next load on.
// The banner then offers the only exit. The backend ignores the header for non-admins,
// so this is safe even though it lives behind the admin-gated AdminView.
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { fetchAdminUsers } from '../../services/backend.js'
import { Modal, Icon } from '../../components/ui'
import { setImpersonateTarget } from './impersonation.js'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const { t } = useI18n()

const open = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const users = ref([]) // [{ user_id, display_name, is_admin, ... }]
const loading = ref(false)
const errorMsg = ref('')
const query = ref('')

// Case-insensitive filter over the display name and the user id.
const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return users.value
  return users.value.filter((u) => {
    const name = (u.display_name || '').toLowerCase()
    const id = (u.user_id || '').toLowerCase()
    return name.includes(q) || id.includes(q)
  })
})

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const data = await fetchAdminUsers()
    users.value = data.users || []
  } catch (e) {
    errorMsg.value = t('impersonate.error')
    users.value = []
  } finally {
    loading.value = false
  }
}

// Lazy-load the list each time the modal opens; reset the search on open.
watch(
  () => props.modelValue,
  (isOpen) => {
    if (isOpen) {
      query.value = ''
      load()
    }
  },
)

// Two-letter avatar initials from the user's display label.
function initials(u) {
  const n = (u.display_name || u.user_id || '').trim()
  if (!n) return '?'
  const parts = n.split(/[.\s_-]+/).filter(Boolean)
  const s = (parts[0]?.[0] || '') + (parts[1]?.[0] || '')
  return (s || n[0]).toUpperCase()
}

function pick(u) {
  if (!u || !u.user_id) return
  // Persist then reload: from the next load on, /me + every request impersonate u.
  setImpersonateTarget(u.user_id)
  location.reload()
}
</script>

<template>
  <Modal v-model="open" :title="t('impersonate.picker_title')" maxWidth="520px">
    <div class="up-search">
      <Icon name="search" :size="15" class="up-search__ico" />
      <input
        v-model="query"
        type="text"
        class="up-search__input"
        :placeholder="t('impersonate.search')"
        autocomplete="off"
      />
    </div>

    <p v-if="loading" class="up-state muted">{{ t('impersonate.loading') }}</p>
    <p v-else-if="errorMsg" class="up-state up-error">{{ errorMsg }}</p>
    <p v-else-if="!filtered.length" class="up-state muted">{{ t('impersonate.empty') }}</p>

    <ul v-else class="up-list">
      <li v-for="u in filtered" :key="u.user_id">
        <button type="button" class="up-row" @click="pick(u)">
          <span class="up-avatar">{{ initials(u) }}</span>
          <span class="up-info">
            <span class="up-name">{{ u.display_name || u.user_id }}</span>
            <span class="up-id">{{ u.user_id }}</span>
          </span>
          <span v-if="u.is_admin" class="up-admin">ADMIN</span>
          <Icon name="chevronRight" :size="15" class="up-go" />
        </button>
      </li>
    </ul>
  </Modal>
</template>

<style scoped>
/* Search field: square, 1px border, orange focus (charter). */
.up-search {
  position: relative;
  display: flex;
  align-items: center;
  margin-bottom: 16px;
}
.up-search__ico {
  position: absolute;
  left: 12px;
  color: var(--text-3);
  pointer-events: none;
}
.up-search__input {
  width: 100%;
  padding: 11px 14px 11px 36px;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--bg);
  font-size: 14px;
  font-family: var(--font-sans);
  color: var(--text);
}
.up-search__input:focus { outline: none; border-color: var(--orange); }
.up-search__input::placeholder { color: var(--text-3); }

.up-state { padding: 14px 2px; font-size: var(--fs-sm); }
.up-error { color: var(--danger); }

/* Bounded scroll list (square rows, 1px separators). */
.up-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 50vh;
  overflow-y: auto;
  border: 1px solid var(--border);
}
.up-list li + li { border-top: 1px solid var(--border); }

.up-row {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 12px 14px;
  background: var(--bg);
  border: 0;
  text-align: left;
  cursor: pointer;
  transition: background var(--dur) var(--ease);
}
.up-row:hover { background: var(--surface-hover); }

/* Avatar may be round (the single charter exception to square geometry). */
.up-avatar {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--surface-2);
  color: var(--text-2);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: var(--fw-bold);
}
.up-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.up-name { font-size: 14px; font-weight: var(--fw-bold); color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.up-id { font-size: 12px; font-family: var(--font-mono); color: var(--text-3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Square admin tag, 1px border. */
.up-admin {
  flex-shrink: 0;
  padding: 2px 7px;
  border: 1px solid var(--border);
  font-size: 10px;
  font-weight: var(--fw-heavy);
  letter-spacing: 0.06em;
  color: var(--text-2);
}
.up-go { flex-shrink: 0; color: var(--text-3); }
.up-row:hover .up-go { color: var(--text); }
</style>
