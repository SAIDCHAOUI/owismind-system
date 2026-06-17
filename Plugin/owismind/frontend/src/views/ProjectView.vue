<script setup>
// Project page (Phase 3) - deferred. There is NO project API (memory §13.4:
// rename/delete/projects are not persisted), so instead of the maquette's mock
// project workspace we show ONE honest "coming soon" state. The route still
// exists (/project/:projectId) so deep links resolve cleanly.
import { useI18n } from 'vue-i18n'
import { PageShell, EmptyState } from '../components/pages'

const { t } = useI18n()
</script>

<template>
  <PageShell :eyebrow="t('pj.eyebrow')" :title="t('sb.projects')" :desc="t('pj.desc')">
    <EmptyState bordered icon="folderPlus" :title="t('x.coming_soon')" :tag="t('x.soon')" :desc="t('pj.coming')" />
  </PageShell>
</template>
