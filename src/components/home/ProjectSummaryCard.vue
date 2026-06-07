<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { FolderIcon } from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'

defineProps<{
  projectName: string
  language: string
  fileCount: number
  rootPath: string
}>()

const { t } = useI18n()
const { showId, componentId } = useComponentId('PS-001')

function truncatePath(p: string): string {
  if (p.length <= 60) return p
  return '...' + p.slice(-57)
}
</script>

<template>
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
  <section class="home-section">
    <div class="section-header">
      <FolderIcon class="w-4 h-4" />
      <span>{{ t('report.projectSummary') }}</span>
    </div>
    <div class="summary-cards">
      <div class="summary-card">
        <span class="card-label">{{ t('project.projectName') }}</span>
        <span class="card-value">{{ projectName }}</span>
      </div>
      <div class="summary-card">
        <span class="card-label">{{ t('project.projectLanguage') }}</span>
        <span class="card-value">{{ language }}</span>
      </div>
      <div class="summary-card">
        <span class="card-label">{{ t('project.fileCount') }}</span>
        <span class="card-value">{{ fileCount }}</span>
      </div>
      <div class="summary-card">
        <span class="card-label">{{ t('project.projectPath') }}</span>
        <span
          class="card-value card-path"
          :title="rootPath"
        >{{ truncatePath(rootPath) }}</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.home-section {
  margin-bottom: 20px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}

.summary-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px 8px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.card-label {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.card-value {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.card-path {
  font-size: 11px;
  font-family: var(--font-mono);
  word-break: break-all;
}
</style>
