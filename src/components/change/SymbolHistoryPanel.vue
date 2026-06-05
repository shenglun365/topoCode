<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { DocumentTextIcon } from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
import { useChangeStore } from '@/stores/change-store'
import ChangeRiskBadge from './ChangeRiskBadge.vue'

const { showId, componentId } = useComponentId('CH-005')
const { t } = useI18n()
const store = useChangeStore()

const symbolName = ref('')
const filePath = ref('')

function search() {
  if (!symbolName.value.trim() || !filePath.value.trim()) return
  store.fetchSymbolHistory(symbolName.value.trim(), filePath.value.trim())
}

function formatCommit(hash: string): string {
  return hash.substring(0, 8)
}

function formatTimestamp(ts: string): string {
  const d = new Date(ts)
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div class="symbol-history-panel">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="panel-header">
      <span class="panel-title">{{ t('change.symbolHistory') }}</span>
    </div>
    <div class="panel-search">
      <input
        v-model="symbolName"
        class="search-input"
        :placeholder="t('change.symbolNamePlaceholder')"
        @keydown.enter="search"
      >
      <input
        v-model="filePath"
        class="search-input"
        :placeholder="t('change.filePathPlaceholder')"
        @keydown.enter="search"
      >
      <button
        class="btn btn-primary btn-sm"
        :disabled="store.loading || !symbolName.trim() || !filePath.trim()"
        @click="search"
      >
        {{ t('common.search') }}
      </button>
    </div>
    <div
      v-if="store.loading"
      class="panel-loading"
    >
      <span class="spinner" />
      <span>{{ t('common.loading') }}</span>
    </div>
    <div
      v-else-if="store.symbolHistory.length === 0 && (symbolName || filePath)"
      class="panel-empty"
    >
      {{ t('change.noHistoryFound') }}
    </div>
    <div
      v-else
      class="panel-list"
    >
      <div
        v-for="entry in store.symbolHistory"
        :key="entry.commit"
        class="history-entry"
      >
        <div class="entry-header">
          <span class="entry-commit">{{ formatCommit(entry.commit) }}</span>
          <span class="entry-date">{{ formatTimestamp(entry.timestamp) }}</span>
        </div>
        <div class="entry-details">
          <DocumentTextIcon class="w-3.5 h-3.5 text-muted" />
          <span class="entry-kind">{{ (entry.symbol.kind as string) || '?' }}</span>
          <span class="entry-separator">·</span>
          <span class="entry-line">{{ t('change.line') }} {{ entry.symbol.line as string }}</span>
          <ChangeRiskBadge
            v-if="(entry.symbol.risk as string)"
            :level="entry.symbol.risk as string"
            size="sm"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.symbol-history-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.panel-header {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}

.panel-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.panel-search {
  display: flex;
  gap: 6px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}

.search-input {
  flex: 1;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 12px;
  font-family: monospace;
  outline: none;
}

.search-input:focus {
  border-color: var(--accent);
}

.panel-loading,
.panel-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: var(--text-muted);
  font-size: 12px;
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.panel-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.history-entry {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
}

.history-entry:last-child {
  border-bottom: none;
}

.entry-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.entry-commit {
  font-family: monospace;
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
}

.entry-date {
  font-size: 10px;
  color: var(--text-muted);
}

.entry-details {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-secondary);
}

.entry-separator {
  color: var(--border);
}
</style>
