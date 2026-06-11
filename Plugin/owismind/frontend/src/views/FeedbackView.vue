<script setup>
// Feedback page (Phase 3). Faithful to the maquette's `.fb-grid` two-column
// layout, but HONEST: there is NO feedback endpoint yet, so the submit button is
// disabled with a clear "coming soon" note, and the "your requests" column is an
// empty state (no mock request list). The form fields are interactive (local
// state only) so the page feels real without sending anything.
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSessionStore } from '../stores/session.js'
import { useTr } from '../composables/useTr.js'
import { PageShell, EmptyState } from '../components/pages'
import { Icon } from '../components/ui'

const { t } = useI18n()
const tr = useTr()
const session = useSessionStore()

// Category options (placeholder first, then the maquette's fb.cat.* set).
const CATEGORIES = ['bug', 'wrong', 'feature', 'ux', 'perf', 'data', 'routing']

const category = ref('')
const linkedConv = ref('')
const message = ref('')

const conversations = computed(() => session.conversations)
</script>

<template>
  <PageShell :eyebrow="t('fb.eyebrow')" :title="t('fb.title')" :desc="t('fb.desc')">
    <div class="fb-grid">
      <!-- Left: new request form (inert — no endpoint yet) -->
      <div class="fb-col">
        <h3 class="fb-col-title">{{ t('fb.new_request') }}</h3>
        <form class="fb-form" @submit.prevent>
          <div class="fb-field">
            <label class="lbl" for="fb-cat">{{ t('fb.category') }}</label>
            <div class="fb-select-wrap">
              <select id="fb-cat" v-model="category" class="fb-select">
                <option value="" disabled>{{ t('fb.cat.choose') }}</option>
                <option v-for="c in CATEGORIES" :key="c" :value="c">{{ t('fb.cat.' + c) }}</option>
              </select>
              <span class="fb-select-arr"><Icon name="chevronDown" /></span>
            </div>
          </div>

          <div class="fb-field">
            <label class="lbl" for="fb-conv">{{ t('fb.linked') }}</label>
            <div class="fb-select-wrap">
              <select id="fb-conv" v-model="linkedConv" class="fb-select" :disabled="!conversations.length">
                <option value="">—</option>
                <option v-for="c in conversations" :key="c.id" :value="c.id">{{ tr(c.title) }}</option>
              </select>
              <span class="fb-select-arr"><Icon name="chevronDown" /></span>
            </div>
          </div>

          <div class="fb-field">
            <label class="lbl" for="fb-msg">{{ t('fb.message') }}</label>
            <textarea
              id="fb-msg"
              v-model="message"
              class="fb-textarea"
              :placeholder="t('fb.placeholder')"
              rows="5"
            />
          </div>

          <div class="fb-submit-row">
            <button class="fb-submit" type="submit" disabled :title="t('x.soon')">
              {{ t('fb.submit') }}
            </button>
            <span class="fb-soon-note">
              <Icon name="info" />{{ t('fb.soon_note') }}
            </span>
          </div>
        </form>
      </div>

      <!-- Right: your requests — empty (no backend) -->
      <div class="fb-col">
        <h3 class="fb-col-title">{{ t('fb.your_requests') }}</h3>
        <EmptyState bordered icon="document" :title="t('fb.empty')" :tag="t('x.soon')" :desc="t('fb.soon_note')" />
      </div>
    </div>
  </PageShell>
</template>

<style scoped>
.fb-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s-7);
}
.fb-col-title {
  font-size: var(--fs-lg);
  font-weight: 600;
  letter-spacing: -0.015em;
  color: var(--text);
  margin: 0 0 var(--s-5);
}

.fb-form { display: flex; flex-direction: column; gap: var(--s-4); }
.fb-field { display: flex; flex-direction: column; gap: 8px; }
.lbl {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  color: var(--text-3);
}

.fb-select-wrap { position: relative; display: flex; }
.fb-select,
.fb-textarea {
  width: 100%;
  padding: 9px 12px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  color: var(--text);
  font-family: inherit;
  transition: border-color var(--dur) var(--ease);
}
.fb-select {
  appearance: none;
  -webkit-appearance: none;
  padding-right: 34px;
  cursor: pointer;
}
.fb-select:disabled { color: var(--text-3); cursor: not-allowed; }
.fb-select-arr {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
  color: var(--text-3);
}
.fb-select-arr :deep(.ui-icon) { width: 15px; height: 15px; }
.fb-textarea {
  min-height: 110px;
  max-height: 280px;
  resize: vertical;
  line-height: 1.5;
}
.fb-select:focus,
.fb-textarea:focus { outline: none; border-color: var(--text-3); }

.fb-submit-row { display: flex; align-items: center; gap: var(--s-3); flex-wrap: wrap; }
.fb-submit {
  align-self: flex-start;
  padding: 10px 18px;
  background: var(--orange);
  color: #fff;
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  font-weight: 600;
}
.fb-submit:disabled { opacity: 0.45; cursor: not-allowed; }
.fb-soon-note {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-xs);
  color: var(--text-3);
}
.fb-soon-note :deep(.ui-icon) { width: 13px; height: 13px; }

@media (max-width: 760px) {
  .fb-grid { grid-template-columns: 1fr; gap: var(--s-7); }
}
</style>
