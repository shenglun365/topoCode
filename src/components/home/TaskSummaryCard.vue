<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ChartBarIcon } from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'

defineProps<{
  taskName: string
  taskType: string
  taskStatus: string
  createdAt: string
  extensions: string[]
  scopes: string[]
}>()

const { t } = useI18n()
const { showId, componentId } = useComponentId('TS-001')
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <section class="home-section">
    <div class="section-header">
      <ChartBarIcon class="w-4 h-4" />
      <span>{{ t('report.taskSummary') }}</span>
    </div>
    <div class="summary-cards">
      <div class="summary-card">
        <span class="card-label">{{ t('analysis.taskName') }}</span>
        <span class="card-value">{{ taskName }}</span>
      </div>
      <div class="summary-card">
        <span class="card-label">{{ t('analysis.taskType') }}</span>
        <span class="card-value">{{ taskType }}</span>
      </div>
      <div class="summary-card">
        <span class="card-label">{{ t('analysis.taskStatus') }}</span>
        <span
          class="card-value status-badge"
          :class="taskStatus"
        >{{ taskStatus }}</span>
      </div>
      <div class="summary-card">
        <span class="card-label">{{ t('analysis.createdAt') }}</span>
        <span class="card-value">{{ createdAt ? new Date(createdAt).toLocaleString() : '-' }}</span>
      </div>
    </div>
    <div class="file-distribution">
      <div class="dist-title">
        {{ t('report.analysisScope') }}
      </div>
      <div class="scope-content">
        <div class="scope-row">
          <span class="scope-label">{{ t('analysis.fileType') }}</span>
          <div class="scope-tags">
            <span
              v-if="!extensions.length"
              class="scope-tag scope-tag-all"
            >{{ t('analysis.allFiles') }}</span>
            <span
              v-for="ext in extensions"
              :key="ext"
              class="scope-tag"
            >{{ ext }}</span>
          </div>
        </div>
        <div class="scope-row">
          <span class="scope-label">{{ t('analysis.directoryScope') }}</span>
          <div class="scope-tags">
            <span
              v-if="!scopes.length"
              class="scope-tag scope-tag-all"
            >{{ t('analysis.allDirectories') }}</span>
            <span
              v-for="s in scopes"
              :key="s"
              class="scope-tag"
            >{{ s }}</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
