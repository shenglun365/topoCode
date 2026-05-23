<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  CodeBracketIcon,
  CpuChipIcon,
  CubeIcon,
  CircleStackIcon,
  DocumentTextIcon,
  BookOpenIcon,
  ArrowDownTrayIcon,
} from '@heroicons/vue/24/outline'
import type { AnalysisTask } from '@/types'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('AN-008')
const { t } = useI18n()

const props = defineProps<{
  task: AnalysisTask
}>()

const activeTab = ref<'ast' | 'call-chain' | 'dependency' | 'dataflow' | 'log'>('ast')

const tabs = [
  { id: 'ast' as const, label: 'AST', icon: CodeBracketIcon },
  { id: 'call-chain' as const, label: computed(() => t('analysis.callGraph')), icon: CpuChipIcon },
  { id: 'dependency' as const, label: computed(() => t('visualization.dependency')), icon: CubeIcon },
  { id: 'dataflow' as const, label: computed(() => t('analysis.dataFlow')), icon: CircleStackIcon },
  { id: 'log' as const, label: computed(() => t('common.log')), icon: DocumentTextIcon },
]

const tabLabels = computed(() => {
  const map: Record<string, string> = {
    ast: t('analysis.astAnalysis'),
    'call-chain': t('analysis.callGraph'),
    dependency: t('analysis.dependencyAnalysis'),
    dataflow: t('analysis.dataFlow'),
    log: t('analysis.taskLog'),
  }
  return map
})
</script>

<template>
  <div class="task-report">
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <!-- 报告头部 -->
    <div class="report-header">
      <div class="flex items-center gap-2">
        <h3 style="font-size:14px; font-weight:600;">{{ task.name }}</h3>
        <span class="badge badge-green" style="font-size:8px;">{{ t('common.completed') }}</span>
      </div>
      <div class="flex gap-2">
        <button class="btn btn-ghost btn-sm">
          <BookOpenIcon class="w-4 h-4" />
          <span>{{ t('knowledge.extractKnowledge') }}</span>
        </button>
        <button class="btn btn-ghost btn-sm">
          <ArrowDownTrayIcon class="w-4 h-4" />
          <span>{{ t('common.export') }}</span>
        </button>
      </div>
    </div>

    <!-- Tab 栏 -->
    <div class="report-tabs">
      <div
        v-for="tab in tabs"
        :key="tab.id"
        class="report-tab"
        :class="{ active: activeTab === tab.id }"
        @click="activeTab = tab.id"
      >
        <component :is="tab.icon" class="w-4 h-4" />
        <span>{{ tab.label }}</span>
      </div>
    </div>

    <!-- Tab 内容 -->
    <div class="report-content">
      <!-- AST 视图 -->
      <div v-if="activeTab === 'ast'" class="empty-state">
        <CodeBracketIcon class="icon" />
        <div class="title">{{ t('analysis.astAnalysis') }}</div>
        <div class="desc">{{ t('analysis.resultsDisplayHere') }}</div>
      </div>

      <!-- 调用链视图 -->
      <div v-else-if="activeTab === 'call-chain'" class="empty-state">
        <CpuChipIcon class="icon" />
        <div class="title">{{ t('analysis.callGraph') }}</div>
        <div class="desc">{{ t('analysis.resultsDisplayHere') }}</div>
      </div>

      <!-- 依赖视图 -->
      <div v-else-if="activeTab === 'dependency'" class="empty-state">
        <CubeIcon class="icon" />
        <div class="title">{{ t('analysis.dependencyAnalysis') }}</div>
        <div class="desc">{{ t('analysis.resultsDisplayHere') }}</div>
      </div>

      <!-- 数据流视图 -->
      <div v-else-if="activeTab === 'dataflow'" class="empty-state">
        <CircleStackIcon class="icon" />
        <div class="title">{{ t('analysis.dataFlow') }}</div>
        <div class="desc">{{ t('analysis.resultsDisplayHere') }}</div>
      </div>

      <div v-else-if="activeTab === 'log'" class="log-view">
        <div class="log-line">[INFO] 2026-05-01 09:00:00 - {{ t('analysis.startParsing') }}</div>
        <div class="log-line">[INFO] 2026-05-01 09:00:01 - {{ t('analysis.scanningDir') }}: /home/cuser/topoCodeProj/topoOne-ui</div>
        <div class="log-line">[INFO] 2026-05-01 09:00:02 - {{ t('analysis.filesFound') }} 128, {{ t('analysis.languagesFound') }} 3</div>
        <div class="log-line">[INFO] 2026-05-01 09:00:05 - {{ t('analysis.parsingComplete') }}: 128/128</div>
        <div class="log-line success">[SUCCESS] 2026-05-01 09:30:00 - {{ t('analysis.analysisComplete') }}, {{ t('analysis.timeElapsed') }} 30s</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-report {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.report-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.report-tabs {
  display: flex;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
  padding: 0 8px;
}

.report-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
}

.report-tab:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.report-tab.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.report-content {
  flex: 1;
  overflow: auto;
  padding: 16px;
}

.log-view {
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.6;
}

.log-line {
  color: var(--text-muted);
  padding: 2px 0;
}

.log-line.success {
  color: var(--success);
}
</style>
