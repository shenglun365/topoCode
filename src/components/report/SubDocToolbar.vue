<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ArrowLeftIcon, ArrowPathIcon, GlobeAltIcon, SparklesIcon } from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'

defineProps<{
  title: string
  canOpenInBrowser: boolean
  canRegenerate: boolean
}>()

const emit = defineEmits<{
  close: []
  refresh: []
  'open-browser': []
  'open-regen-dialog': [mode?: 'full' | 'mermaid' | 'plantuml']
}>()

const { t } = useI18n()
const { showId, componentId } = useComponentId('ST-001')
</script>

<template>
  <span
    v-if="showId"
    class="cmp-id"
  >{{ componentId }}</span>
  <div class="subdoc-toolbar">
    <div class="toolbar-left">
      <button
        class="btn btn-ghost btn-sm"
        @click="emit('close')"
      >
        <ArrowLeftIcon class="w-4 h-4" />
        <span>{{ t('report.backToReport') }}</span>
      </button>
      <span class="doc-title">{{ title }}</span>
    </div>
    <div class="toolbar-right">
      <button
        class="btn btn-ghost btn-sm"
        @click="emit('refresh')"
      >
        <ArrowPathIcon class="w-3.5 h-3.5" />
        <span>{{ t('common.refresh') }}</span>
      </button>
      <button
        v-if="canOpenInBrowser"
        class="btn btn-ghost btn-sm"
        @click="emit('open-browser')"
      >
        <GlobeAltIcon class="w-4 h-4" />
        <span>{{ t('settings.openInBrowser') }}</span>
      </button>
      <button
        v-if="canRegenerate"
        class="btn btn-ghost btn-sm"
        @click="emit('open-regen-dialog')"
      >
        <SparklesIcon class="w-3.5 h-3.5" />
        <span>{{ t('report.regenerate') }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.subdoc-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 12px; border-bottom: 1px solid var(--border);
  background: var(--bg-secondary); gap: 8px;
}
.toolbar-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.toolbar-right { display: flex; align-items: center; gap: 4px; }
.doc-title { font-size: 13px; font-weight: 600; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
