<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { FolderIcon, MinusIcon } from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'

defineProps<{
  projectName: string
  language: string
  fileCount: number
  rootPath: string
  showMinimize?: boolean
}>()

defineEmits<{
  minimize: []
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
      <button
        v-if="showMinimize"
        class="collapse-btn"
        :title="t('common.minimize', '最小化')"
        @click="$emit('minimize')"
      >
        <MinusIcon class="w-3.5 h-3.5" />
      </button>
      <div class="header-spacer" />
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

.header-spacer { flex: 1; }
.collapse-btn {
  display: flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; padding: 0;
  background: transparent; border: 1px solid transparent; border-radius: 0.25rem;
  color: var(--text-muted); cursor: pointer; transition: all 0.15s; flex-shrink: 0;
}
.collapse-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); border-color: var(--border); }
</style>
