<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import {
  SparklesIcon, ExclamationTriangleIcon, ListBulletIcon, DocumentTextIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'

defineProps<{
  hasModel: boolean
  communityAnalysisProgress: number
  hasArchitectureReport: boolean
}>()

const emit = defineEmits<{
  'open-task-list': []
  'open-community-analysis': []
  'open-overall-architecture': []
}>()

const { t } = useI18n()
const { showId, componentId } = useComponentId('AC-001')
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <section class="home-section actions-section">
    <div class="section-header">
      <SparklesIcon class="w-4 h-4" />
      <span>{{ t('report.generateReport') }}</span>
    </div>

    <div
      v-if="!hasModel"
      class="model-warning"
    >
      <ExclamationTriangleIcon class="w-4 h-4" />
      <span>{{ t('report.llmNotConfigured') }}</span>
    </div>

    <div class="actions-row">
      <button
        class="btn btn-primary"
        @click="emit('open-task-list')"
      >
        <ListBulletIcon class="w-4 h-4" />
        <span>{{ t('report.openTaskList') }}</span>
      </button>
      <button
        class="btn btn-secondary comp-analysis-btn"
        @click="emit('open-community-analysis')"
      >
        <span
          class="comp-analysis-progress"
          :style="{ width: communityAnalysisProgress + '%' }"
        />
        <SparklesIcon class="w-4 h-4" />
        <span>{{ t('report.pipeline.communityAnalysis') }}</span>
        <span
          v-if="communityAnalysisProgress > 0"
          class="comp-analysis-pct"
        >{{ communityAnalysisProgress }}%</span>
      </button>
      <button
        :class="['btn', hasArchitectureReport ? 'btn-has-result' : 'btn-secondary']"
        @click="emit('open-overall-architecture')"
      >
        <DocumentTextIcon class="w-4 h-4" />
        <span>{{ t('report.viewOverallArchitecture') }}</span>
      </button>
    </div>
  </section>
</template>
