<script setup lang="ts">
/**
 * 报告 Tab 工具栏
 *
 * 左侧: 项目名 / 任务名 / 报告名 全名提示
 * 右侧: 全部关闭 + 预留扩展按钮
 */

import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'

const { t } = useI18n()
const projectStore = useProjectStore()

const props = defineProps<{
  /** 当前报告 tab */
  tab: {
    taskId: string
    reportType: string
    title: string
  }
}>()

const emit = defineEmits<{
  closeAll: []
}>()

// 报告类型映射
const typeMap: Record<string, string> = {
  dependency: t('project.reportType.dependency'),
  callChain: t('project.reportType.callChain'),
  dataFlow: t('project.reportType.dataFlow'),
  architecture: t('project.reportType.architecture'),
}

const reportTypeLabel = computed(() => {
  return typeMap[props.tab.reportType] || props.tab.reportType
})

// 全名: 项目名 / 任务名 / 报告名
const fullName = computed(() => {
  const projectName = projectStore.selectedProject?.name || ''
  return `${projectName} / ${props.tab.title} / ${reportTypeLabel.value}`
})
</script>

<template>
  <div class="report-tab-toolbar">
    <div class="toolbar-left">
      <span class="full-name" :title="fullName">{{ fullName }}</span>
    </div>
    <div class="toolbar-right">
      <button class="btn btn-ghost btn-sm" @click="emit('closeAll')">
        <XMarkIcon class="w-4 h-4" />
        <span>{{ t('common.closeAll') }}</span>
      </button>
      <!-- 预留扩展按钮位 -->
    </div>
  </div>
</template>

<style scoped>
.report-tab-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
  min-height: 36px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  overflow: hidden;
}

.full-name {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}
</style>
