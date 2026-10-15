<script setup>
// ImpersonateBanner - the persistent top strip shown while an admin is viewing the
// app as another user (read-only consultation). It is the ONLY way out of the
// impersonated session: while impersonating, /me reports the target user (is_admin
// false) so the Admin nav hides - the admin exits here.
//
// Orange charter: flat, square, white/near-black with a single thin orange accent
// strip on the left. No glow / gradient / blur. The displayed name is the EFFECTIVE
// (impersonated) user from the session store; real_user_id is the admin behind it.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSessionStore } from '../../stores/session.js'
import { Icon } from '../../components/ui'
import { clearImpersonate } from './impersonation.js'

const { t } = useI18n()
const session = useSessionStore()

// The impersonated user's display label (the session identity already reflects the
// target while impersonating). Falls back to the raw user id, then a neutral dash.
const targetLabel = computed(() => {
  const u = session.user
  return (u && (u.display_name || u.user_id)) || '-'
})

function exit() {
  // Drop the impersonation target, then reload so /me + all requests revert to the
  // real admin identity (full reset; no half-impersonated state survives).
  clearImpersonate()
  location.reload()
}
</script>

<template>
  <div class="imp-banner" role="status">
    <span class="imp-banner__msg">
      <Icon name="users" :size="15" />
      <span>{{ t('impersonate.banner', [targetLabel]) }}</span>
    </span>
    <button type="button" class="imp-banner__exit" @click="exit">
      <Icon name="x" :size="14" />
      <span>{{ t('impersonate.exit') }}</span>
    </button>
  </div>
</template>

<style scoped>
/* Flat, square strip. A thin orange accent on the left marks the special state
   without flooding the bar with colour (charter: orange is a RARE accent). */
.imp-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-4);
  padding: 9px 16px;
  background: var(--surface);
  border-bottom: 1px solid var(--border-strong);
  border-left: 4px solid var(--orange);
  color: var(--text);
  font-size: var(--fs-sm);
  flex-shrink: 0;
}
.imp-banner__msg {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
  font-weight: var(--fw-bold);
}
.imp-banner__msg :deep(.ui-icon) { color: var(--orange); flex-shrink: 0; }
.imp-banner__msg span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* Square ghost button, 1px border, hover inverts (charter). */
.imp-banner__exit {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
  padding: 7px 13px;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--bg);
  color: var(--text);
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
  font-family: inherit;
  cursor: pointer;
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.imp-banner__exit:hover {
  background: var(--text);
  border-color: var(--text);
  color: var(--bg);
}
.imp-banner__exit :deep(.ui-icon) { flex-shrink: 0; }
</style>
