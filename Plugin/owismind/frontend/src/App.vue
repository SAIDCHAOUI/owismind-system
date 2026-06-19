<script setup>
// Root component - thin shell: the app layout (sidebar + routed main) plus the
// single global ToastHost. Identity (and the enabled-agents list it triggers) is
// resolved once on mount via the session store; the conversation list loads lazily
// in the sidebar. Best-effort: the shell still renders outside DSS where the
// backend is unavailable.
//
// Auth gate: when /me returns a definitive 401, the session store flips authState
// to 'unauthenticated' and we render ONLY the AuthGate (no AppLayout/router tree, so
// navigation is impossible). While /me is still resolving we show a neutral splash
// to avoid flashing the shell before the answer arrives.
import { onMounted } from 'vue'
import AppLayout from './components/shell/AppLayout.vue'
import AuthGate from './components/shell/AuthGate.vue'
import { ToastHost } from './components/ui'
import { useSessionStore } from './stores/session.js'

const session = useSessionStore()
onMounted(() => {
  session.ensureLoaded()
})
</script>

<template>
  <AuthGate v-if="session.authState === 'unauthenticated'" />
  <div v-else-if="session.authState === 'pending'" class="app-splash" aria-hidden="true"></div>
  <template v-else>
    <AppLayout />
    <ToastHost />
  </template>
</template>

<style scoped>
/* Neutral pre-auth splash: a blank surface in the theme colours, no shell chrome,
   no spinner - just avoids flashing the layout before /me resolves. */
.app-splash {
  position: fixed;
  inset: 0;
  background: var(--bg);
}
</style>
