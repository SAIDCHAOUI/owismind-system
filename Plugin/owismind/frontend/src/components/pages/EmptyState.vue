<script setup>
// Honest empty state - used wherever a feature has NO backend yet (budget,
// usage history, feedback list, projects). It states plainly that the data or
// feature is not available; it NEVER renders fake numbers (memory rule: zéro
// faux chiffre). Optional "soon" tag + an extra actions slot.
//
// `bordered` adds the dashed placeholder frame for STANDALONE use; inside a
// SettingCard (which already has a border) leave it off to avoid a double frame.
import Icon from '../ui/Icon.vue'

defineProps({
  icon: { type: String, default: '' },
  title: { type: String, default: '' },
  desc: { type: String, default: '' },
  tag: { type: String, default: '' },
  bordered: { type: Boolean, default: false },
})
</script>

<template>
  <div :class="['empty-state', { 'empty-state--bordered': bordered }]">
    <span v-if="icon" class="empty-state__icon"><Icon :name="icon" :size="20" /></span>
    <div class="empty-state__head">
      <span v-if="title" class="empty-state__title">{{ title }}</span>
      <span v-if="tag" class="empty-state__tag">{{ tag }}</span>
    </div>
    <p v-if="desc" class="empty-state__desc">{{ desc }}</p>
    <div v-if="$slots.default" class="empty-state__actions"><slot /></div>
  </div>
</template>

<style scoped>
/* Square empty state: flat surface, solid border, no pill radius. */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: var(--s-3);
  padding: 64px var(--s-5);
  color: var(--text-2);
}
.empty-state--bordered {
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--surface);
}
/* 46x46 square icon box - matches mockup .empty .ei. */
.empty-state__icon {
  width: 46px;
  height: 46px;
  display: grid;
  place-items: center;
  border-radius: 0;
  background: transparent;
  border: 1px solid var(--border-strong);
  color: var(--text-3);
  margin-bottom: var(--s-1);
}
.empty-state__icon :deep(.ui-icon) { width: 22px; height: 22px; }
.empty-state__head {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
}
.empty-state__title {
  font-size: var(--fs-md);
  font-weight: 700;
  color: var(--text);
}
/* Orange "soon" tag: square, solid orange, white text - matches mockup .soon. */
.empty-state__tag {
  display: inline-block;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 2px 6px;
  border-radius: 0;
  background: var(--orange);
  color: #fff;
}
.empty-state__desc {
  margin: 0;
  font-size: var(--fs-sm);
  line-height: 1.6;
  max-width: 420px;
}
.empty-state__actions { margin-top: var(--s-2); }
</style>
