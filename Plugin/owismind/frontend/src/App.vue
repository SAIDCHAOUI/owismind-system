<script setup>
// Root component - thin shell: the app layout (sidebar + routed main) plus the
// single global ToastHost. Identity (and the enabled-agents list it triggers) is
// resolved once on mount via the session store; the conversation list loads lazily
// in the sidebar. Best-effort: the shell still renders outside DSS where the
// backend is unavailable.
import { onMounted } from 'vue'
import AppLayout from './components/shell/AppLayout.vue'
import { ToastHost } from './components/ui'
import { useSessionStore } from './stores/session.js'

const session = useSessionStore()
onMounted(() => {
  session.ensureLoaded()
})
</script>

<template>
  <AppLayout />
  <ToastHost />
</template>
