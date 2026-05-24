<script setup lang="ts">
import { XMarkIcon, DocumentTextIcon, ListBulletIcon, PlusCircleIcon, ChartBarIcon, DocumentDuplicateIcon } from '@heroicons/vue/24/outline'
import type { HomeTab } from '@/stores/project'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PR-007')
defineProps<{
  tabs: HomeTab[]
  activeTabId: string | null
}>()

const emit = defineEmits<{
  'update:activeTabId': [tabId: string | null]
  'close': [tabId: string]
}>()

function getTabIcon(tab: HomeTab) {
  switch (tab.kind) {
    case 'taskList': return ListBulletIcon
    case 'taskCreate': return PlusCircleIcon
    case 'report': return ChartBarIcon
    case 'reportHome': return DocumentTextIcon
    case 'subdoc': return DocumentDuplicateIcon
    default: return DocumentTextIcon
  }
}
</script>

<template>
  <div class="home-tab-bar">
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <div
      v-for="tab in tabs"
      :key="tab.id"
      class="home-tab"
      :class="{ active: activeTabId === tab.id }"
      @click="emit('update:activeTabId', tab.id)"
    >
      <component :is="getTabIcon(tab)" class="w-3.5 h-3.5 tab-icon" />
      <span class="tab-title">{{ tab.title }}</span>
      <button
        class="tab-close-btn"
        @click.stop="emit('close', tab.id)"
      >
        <XMarkIcon class="w-3 h-3" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.home-tab-bar {
  display: flex;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
  overflow-x: auto;
  min-height: 36px;
}

.home-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  border-right: 1px solid var(--border);
  white-space: nowrap;
  transition: all 0.15s;
  flex-shrink: 0;
}

.home-tab:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.home-tab.active {
  background: var(--bg-primary);
  color: var(--text-primary);
  border-bottom: 2px solid var(--accent);
}

.tab-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.home-tab.active .tab-icon {
  color: var(--accent);
}

.tab-title {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tab-close-btn {
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  opacity: 0;
  transition: all 0.1s;
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
}

.home-tab:hover .tab-close-btn {
  opacity: 1;
}

.tab-close-btn:hover {
  background: var(--bg-active);
}
</style>
