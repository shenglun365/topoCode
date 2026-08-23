<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { FolderIcon, MinusIcon } from '@heroicons/vue/24/outline'
import { useComponentId } from '@topo/web-core/composables/useComponentId'

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
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
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
  margin-bottom: calc(20px * var(--ui-scale, 1));
}

.section-header {
  display: flex;
  align-items: center;
  gap: calc(6px * var(--ui-scale, 1));
  font-size: calc(13px * var(--ui-scale, 1));
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: calc(10px * var(--ui-scale, 1));
  padding-bottom: calc(6px * var(--ui-scale, 1));
  border-bottom: 1px solid var(--border);
}

.summary-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: calc(12px * var(--ui-scale, 1)) calc(8px * var(--ui-scale, 1));
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: calc(2px * var(--ui-scale, 1));
  padding: calc(8px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: calc(6px * var(--ui-scale, 1));
}

.card-label {
  font-size: calc(10px * var(--ui-scale, 1));
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.card-value {
  font-size: calc(13px * var(--ui-scale, 1));
  font-weight: 500;
  color: var(--text-primary);
}

.card-path {
  font-size: calc(11px * var(--ui-scale, 1));
  font-family: var(--font-mono);
  word-break: break-all;
}

.header-spacer { flex: 1; }
.collapse-btn {
  display: flex; align-items: center; justify-content: center;
  width: calc(22px * var(--ui-scale, 1)); height: calc(22px * var(--ui-scale, 1)); padding: 0;
  background: transparent; border: 1px solid transparent; border-radius: 0.25rem;
  color: var(--text-muted); cursor: pointer; transition: all 0.15s; flex-shrink: 0;
}
.collapse-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); border-color: var(--border); }
</style>
