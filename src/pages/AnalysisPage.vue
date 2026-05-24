<script setup lang="ts">
import { computed, onActivated, onDeactivated } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChartBarIcon } from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import { useFuncGroupStore } from '@/stores/funcGroup'
import HomeTabBar from '@/components/project/HomeTabBar.vue'
import SubDocViewer from '@/components/report/SubDocViewer.vue'
import ReportHome from '@/components/report/ReportHome.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PG-002')
const { t } = useI18n()
const projectStore = useProjectStore()
const funcGroup = useFuncGroupStore()

/* ===== 分析功能组上下文 ===== */
const analysisContext = computed(() => funcGroup.context.analysis)
const activeTab = computed(() => {
  const ctx = analysisContext.value;
  return ctx.tabs.find(t => t.id === ctx.activeTabId) || null;
})
const reportTabs = computed(() => {
  return analysisContext.value.tabs.filter(t => t.kind === 'subdoc' || t.kind === 'reportHome');
})

function onTabUpdate(tabId: string | null) {
  funcGroup.setActiveTab('analysis', tabId)
}

function onTabClose(tabId: string) {
  funcGroup.closeTab('analysis', tabId)
}

const isReportHomeTab = computed(() => activeTab.value?.kind === 'reportHome')
const isSubDocTab = computed(() => activeTab.value?.kind === 'subdoc')

/* ===== 状态持久化 ===== */
function saveAnalysisState() {
  funcGroup.saveExtraState('analysis', {})
}

function restoreAnalysisState() {
  const extra = funcGroup.getExtraState('analysis');
}

onActivated(() => {
  restoreAnalysisState();
})

onDeactivated(() => {
  saveAnalysisState();
})

// 子文档“返回报告”按钮：切换到所属报告的 reportHome tab
function goToReportHome() {
  const tab = activeTab.value
  if (!tab) return
  const taskId = (tab as any).taskId
  if (!taskId) {
    onTabClose(tab.id)
    return
  }
  const homeTab = analysisContext.value.tabs.find(t => t.kind === 'reportHome' && (t as any).taskId === taskId)
  if (homeTab) {
    funcGroup.setActiveTab('analysis', homeTab.id)
  } else {
    onTabClose(tab.id)
  }
}

// 处理报告首页的 open-md 事件（在 analysis 上下文中打开 inline 子文档 tab）
function handleOpenMD(params: { taskId: string; content: string; title: string }) {
  const hash = params.title.slice(0, 20).replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_')
  const id = `tab-subdoc-inline-${params.taskId}-${hash}`
  funcGroup.openTab('analysis', {
    id,
    kind: 'subdoc',
    title: params.title,
    content: params.content,
    taskId: params.taskId,
    projectId: projectStore.selectedProjectId || undefined,
    hasUnsavedChanges: false,
  })
}

</script>

<template>
  <div class="page-analysis">
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <!-- ===== 公共 Tab 栏 — 显示所有报告类型 ===== -->
    <HomeTabBar
      :tabs="reportTabs"
      :active-tab-id="analysisContext.activeTabId"
      @update:activeTabId="onTabUpdate"
      @close="onTabClose"
    />

    <!-- ===== 报告首页（分析报告生成） / 子文档 / 空白状态 ===== -->
    <template v-if="isReportHomeTab && activeTab">
      <ReportHome
        :key="activeTab.id"
        :task-id="activeTab.taskId!"
        @open-md="handleOpenMD"
      />
    </template>

    <template v-else-if="isSubDocTab && activeTab">
      <SubDocViewer
        :key="activeTab.id"
        :sub-doc-id="activeTab.subDocId"
        :initial-content="activeTab.content"
        :initial-title="activeTab.title"
        @close="goToReportHome"
      />
    </template>

    <template v-else>
      <div class="analysis-empty">
        <ChartBarIcon class="w-16 h-16" />
        <div class="title">{{ t('analysis.selectReportHint') }}</div>
        <div class="desc">{{ t('analysis.selectReportHintDesc') }}</div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page-analysis {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.analysis-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-muted);
}

.analysis-empty .title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-secondary);
}

.analysis-empty .desc {
  font-size: 12px;
}

</style>
