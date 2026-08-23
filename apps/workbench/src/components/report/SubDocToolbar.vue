<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { ArrowLeftIcon, ArrowPathIcon, GlobeAltIcon, PencilIcon } from '@heroicons/vue/24/outline'
import { useComponentId } from '@topo/web-core/composables/useComponentId'

defineProps<{
  title: string
  canOpenInBrowser: boolean
}>()

const emit = defineEmits<{
  close: []
  refresh: []
  'open-browser': []
  edit: []
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
        class="btn btn-ghost btn-sm"
        @click="emit('edit')"
      >
        <PencilIcon class="w-3.5 h-3.5" />
        <span>{{ t('common.edit') }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.subdoc-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  padding: calc(6px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1)); border-bottom: 1px solid var(--border);
  background: var(--bg-secondary); gap: calc(8px * var(--ui-scale, 1));
}
.toolbar-left { display: flex; align-items: center; gap: calc(8px * var(--ui-scale, 1)); min-width: 0; }
.toolbar-right { display: flex; align-items: center; gap: calc(4px * var(--ui-scale, 1)); }
.doc-title { font-size: calc(13px * var(--ui-scale, 1)); font-weight: 600; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
