<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { FolderIcon } from '@heroicons/vue/24/outline'

defineProps<{
  projectName: string
  language: string
  fileCount: number
  rootPath: string
}>()

const { t } = useI18n()

function truncatePath(p: string): string {
  if (p.length <= 60) return p
  return '...' + p.slice(-57)
}
</script>

<template>
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
