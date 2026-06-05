<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon,
  DocumentTextIcon,
  ExclamationTriangleIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
import { useChangeStore } from '@/stores/change-store'
import ChangeRiskBadge from './ChangeRiskBadge.vue'

const { showId, componentId } = useComponentId('CH-004')
const { t } = useI18n()
const store = useChangeStore()

onMounted(() => {
  if (store.selectedFromCommit && store.selectedToCommit) {
    store.fetchChangeReport(undefined, undefined, 'full')
  }
})

watch([() => store.selectedFromCommit, () => store.selectedToCommit], () => {
  if (store.selectedFromCommit && store.selectedToCommit) {
    store.fetchChangeReport(undefined, undefined, 'full')
  }
})

function formatFileCount(n: number): string {
  return n.toLocaleString()
}
</script>

<template>
  <div class="change-dashboard">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>

    <div class="dashboard-header">
      <span class="dashboard-title">{{ t('change.changeDashboard') }}</span>
      <button
        class="btn btn-ghost btn-icon btn-sm"
        :disabled="store.loading"
        :title="t('common.refresh')"
        @click="store.fetchChangeReport(undefined, undefined, 'full')"
      >
        <ArrowPathIcon
          class="w-4 h-4"
          :class="{ 'spin': store.loading }"
        />
      </button>
    </div>

    <div
      v-if="store.loading"
      class="dashboard-loading"
    >
      <span class="spinner" />
      <span>{{ t('common.loading') }}</span>
    </div>

    <div
      v-else-if="store.error"
      class="dashboard-error"
    >
      <ExclamationTriangleIcon class="w-5 h-5" />
      <span>{{ store.error }}</span>
    </div>

    <template v-else-if="store.changeReport">
      <div class="dashboard-summary-cards">
        <div class="summary-card">
          <div class="summary-card-icon summary-card-files">
            <DocumentTextIcon class="w-5 h-5" />
          </div>
          <div class="summary-card-body">
            <span class="summary-card-value">{{ formatFileCount(store.changeReport.summary.filesChanged) }}</span>
            <span class="summary-card-label">{{ t('change.filesChanged') }}</span>
          </div>
        </div>
        <div class="summary-card">
          <div class="summary-card-icon summary-card-added">
            <span class="summary-card-emoji">+</span>
          </div>
          <div class="summary-card-body">
            <span class="summary-card-value summary-card-added-value">{{ formatFileCount(store.changeReport.summary.symbolsAdded) }}</span>
            <span class="summary-card-label">{{ t('change.symbolsAdded') }}</span>
          </div>
        </div>
        <div class="summary-card">
          <div class="summary-card-icon summary-card-modified">
            <span class="summary-card-emoji">~</span>
          </div>
          <div class="summary-card-body">
            <span class="summary-card-value">{{ formatFileCount(store.changeReport.summary.symbolsModified) }}</span>
            <span class="summary-card-label">{{ t('change.symbolsModified') }}</span>
          </div>
        </div>
        <div class="summary-card">
          <div class="summary-card-icon summary-card-removed">
            <span class="summary-card-emoji">−</span>
          </div>
          <div class="summary-card-body">
            <span class="summary-card-value summary-card-removed-value">{{ formatFileCount(store.changeReport.summary.symbolsRemoved) }}</span>
            <span class="summary-card-label">{{ t('change.symbolsRemoved') }}</span>
          </div>
        </div>
        <div class="summary-card summary-card-risk">
          <div class="summary-card-body">
            <ChangeRiskBadge
              :level="store.changeReport.summary.riskLevel"
              size="lg"
              :show-label="true"
            />
            <span class="summary-card-label">{{ t('change.riskScore') }}: {{ store.changeReport.summary.riskScore }}</span>
          </div>
        </div>
      </div>

      <div
        v-if="store.changeReport.impact"
        class="dashboard-impact"
      >
        <div class="impact-header">
          {{ t('change.impactAnalysis') }}
        </div>
        <div class="impact-stats">
          <div class="impact-stat">
            <span class="impact-stat-value">{{ store.changeReport.impact.impactCount }}</span>
            <span class="impact-stat-label">{{ t('change.filesImpacted') }}</span>
          </div>
          <div class="impact-stat">
            <span class="impact-stat-value">{{ store.changeReport.impact.testImpactCount }}</span>
            <span class="impact-stat-label">{{ t('change.testsImpacted') }}</span>
          </div>
        </div>
      </div>

      <div
        v-if="store.changeReport.files && store.changeReport.files.length"
        class="dashboard-files"
      >
        <div class="files-header">
          {{ t('change.changedFiles') }} ({{ store.changeReport.files.length }})
        </div>
        <div class="files-list">
          <div
            v-for="f in store.changeReport.files"
            :key="f.filePath"
            class="file-item"
          >
            <span
              class="file-change-type"
              :class="`file-type-${f.changeType}`"
            >{{ f.changeType === 'added' ? '+' : f.changeType === 'removed' ? '−' : '~' }}</span>
            <span class="file-path">{{ f.filePath }}</span>
            <div class="file-symbols">
              <span
                v-for="s in f.symbols"
                :key="s.name"
                class="file-symbol-tag"
              >
                {{ s.name }}
                <ChangeRiskBadge
                  :level="s.risk"
                  size="sm"
                  :show-label="false"
                />
              </span>
            </div>
          </div>
        </div>
      </div>
    </template>

    <div
      v-else
      class="dashboard-empty"
    >
      <span>{{ t('change.selectCommitsHint') }}</span>
    </div>
  </div>
</template>

<style scoped>
.change-dashboard {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  overflow-y: auto;
  padding: 12px;
}

.dashboard-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.dashboard-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.dashboard-loading,
.dashboard-error,
.dashboard-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px;
  color: var(--text-muted);
  font-size: 13px;
}

.dashboard-error {
  color: #ef4444;
}

.spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.dashboard-summary-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 8px;
}

.summary-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.summary-card-risk {
  grid-column: span 2;
  display: flex;
  align-items: center;
  justify-content: center;
}

.summary-card-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.summary-card-icon {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.summary-card-files {
  background: color-mix(in srgb, #3b82f6 15%, transparent);
  color: #3b82f6;
}

.summary-card-added {
  background: color-mix(in srgb, #22c55e 15%, transparent);
  color: #22c55e;
}

.summary-card-modified {
  background: color-mix(in srgb, #f59e0b 15%, transparent);
  color: #f59e0b;
}

.summary-card-removed {
  background: color-mix(in srgb, #ef4444 15%, transparent);
  color: #ef4444;
}

.summary-card-emoji {
  font-size: 18px;
  font-weight: 700;
}

.summary-card-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
}

.summary-card-added-value {
  color: #22c55e;
}

.summary-card-removed-value {
  color: #ef4444;
}

.summary-card-label {
  font-size: 10px;
  color: var(--text-muted);
}

.dashboard-impact {
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
}

.impact-header {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}

.impact-stats {
  display: flex;
  gap: 16px;
}

.impact-stat {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.impact-stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--accent);
}

.impact-stat-label {
  font-size: 10px;
  color: var(--text-muted);
}

.dashboard-files {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.files-header {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
  padding: 4px 0;
}

.files-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-radius: 6px;
  font-size: 12px;
  transition: background 0.1s;
}

.file-item:hover {
  background: var(--bg-hover);
}

.file-change-type {
  font-weight: 700;
  font-family: monospace;
  width: 16px;
  text-align: center;
  flex-shrink: 0;
}

.file-type-added { color: #22c55e; }
.file-type-removed { color: #ef4444; }
.file-type-modified { color: #f59e0b; }

.file-path {
  font-family: monospace;
  font-size: 11px;
  color: var(--text-primary);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-symbols {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.file-symbol-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 1px 6px;
  font-size: 10px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-secondary);
}
</style>
