<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowsRightLeftIcon } from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
import { useChangeStore } from '@/stores/change-store'
import type { CommitInfo } from '@/stores/change-store'

const { showId, componentId } = useComponentId('CH-002')
const { t } = useI18n()
const store = useChangeStore()

onMounted(() => {
  if (!store.hasData) {
    store.fetchCommits()
  }
})

const fromOptions = computed(() => store.commits)
const toOptions = computed(() => store.commits)

function onFromChange(event: Event) {
  const target = event.target as HTMLSelectElement
  store.selectCommits(target.value, store.selectedToCommit)
}

function onToChange(event: Event) {
  const target = event.target as HTMLSelectElement
  store.selectCommits(store.selectedFromCommit, target.value)
}

function swapCommits() {
  store.selectCommits(store.selectedToCommit, store.selectedFromCommit)
}

function formatCommit(c: CommitInfo): string {
  const short = c.hash.substring(0, 8)
  const msg = c.message.length > 40 ? c.message.substring(0, 40) + '…' : c.message
  return `${short} — ${msg}`
}
</script>

<template>
  <div class="commit-selector">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="selector-group">
      <label class="selector-label">{{ t('change.from') }}</label>
      <select
        class="selector-select"
        :value="store.selectedFromCommit"
        @change="onFromChange"
      >
        <option
          v-for="c in fromOptions"
          :key="c.hash"
          :value="c.hash"
        >
          {{ formatCommit(c) }}
        </option>
      </select>
    </div>
    <button
      class="btn btn-ghost btn-icon swap-btn"
      :title="t('change.swapCommits')"
      @click="swapCommits"
    >
      <ArrowsRightLeftIcon class="w-4 h-4" />
    </button>
    <div class="selector-group">
      <label class="selector-label">{{ t('change.to') }}</label>
      <select
        class="selector-select"
        :value="store.selectedToCommit"
        @change="onToChange"
      >
        <option
          v-for="c in toOptions"
          :key="c.hash"
          :value="c.hash"
        >
          {{ formatCommit(c) }}
        </option>
      </select>
    </div>
  </div>
</template>

<style scoped>
.commit-selector {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.selector-group {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.selector-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-muted);
}

.selector-select {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 12px;
  font-family: monospace;
  outline: none;
  cursor: pointer;
}

.selector-select:focus {
  border-color: var(--accent);
}

.swap-btn {
  flex-shrink: 0;
  margin-bottom: 2px;
}
</style>
