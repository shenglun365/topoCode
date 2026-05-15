<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChartBarIcon } from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import HomeTabBar from '@/components/project/HomeTabBar.vue'
import ReportTabToolbar from '@/components/report/ReportTabToolbar.vue'
import CascadeCommunityQuery from '@/components/report/CascadeCommunityQuery.vue'
import LLMChatFlow from '@/components/report/LLMChatFlow.vue'
import SubDocViewer from '@/components/report/SubDocViewer.vue'
import type { CascadeQueryParams } from '@/components/report/CascadeCommunityQuery.vue'

const { t } = useI18n()
const projectStore = useProjectStore()

const activeTab = computed(() => projectStore.activeTab)
const reportTabs = computed(() => projectStore.tabs.filter(t => t.kind === 'report' || t.kind === 'subdoc'))

function onTabUpdate(tabId: string | null) {
  projectStore.setActiveTab(tabId)
}

function onTabClose(tabId: string) {
  projectStore.closeTab(tabId)
}
const isReportTab = computed(() => activeTab.value?.kind === 'report')
const isSubDocTab = computed(() => activeTab.value?.kind === 'subdoc')
const activeReportTab = computed(() => {
  const tab = activeTab.value
  return tab?.kind === 'report' ? tab : null
})

// 选中社区
const selectedCommIds = ref<string[]>([])

// refs
const chatFlowRef = ref<any>(null)

// 关闭所有报告
function handleCloseAllReports() {
  projectStore.closeAllReportTabs()
}

// 处理级联查询 — 只给统计, 不渲染图
async function handleCascadeQuery(params: CascadeQueryParams) {
  console.log('[AnalysisPage] cascade query:', JSON.stringify(params))
  selectedCommIds.value = params.selectedIds

  if (!activeReportTab.value) return

  const edgeType = activeReportTab.value.reportType === 'dependency' ? 'INCLUDE' : 'CALL'

  try {
    const stats = await window.api.analysis.getQueryStats({
      taskId: activeReportTab.value.taskId!,
      edgeType,
      commLv: 'L0',
      commIds: params.selectedIds,
      depth: 1,
    })

    // 在对话流中显示查询结果 + AI分析快捷tag
    chatFlowRef.value?.addQueryResultMessage({ selectedIds: params.selectedIds, stats })
  } catch (e) {
    console.error('[AnalysisPage] Query failed:', e)
  }
}

// 保存子文档
async function handleSaveSubdoc(params: { commId: string; title: string; content: string; templateId: string }) {
  if (!activeReportTab.value?.taskId) return

  try {
    const edgeType = activeReportTab.value.reportType === 'dependency' ? 'INCLUDE' : 'CALL'
    const result = await window.api.report.createSubDoc({
      taskId: activeReportTab.value.taskId,
      edgeType,
      commId: params.commId,
      title: params.title,
      content: params.content,
      templateId: params.templateId,
    })
    console.log('[AnalysisPage] SubDoc saved:', result.id)
  } catch (e) {
    console.error('[AnalysisPage] Save subdoc failed:', e)
  }
}

</script>

<template>
  <div class="page-analysis">
    <!-- Tab 栏 (报告/子文档) -->
    <HomeTabBar
      v-if="reportTabs.length > 0"
      :tabs="reportTabs"
      :active-tab-id="projectStore.activeTabId"
      @update:activeTabId="onTabUpdate"
      @close="onTabClose"
    />

    <!-- ===== 报告 Tab ===== -->
    <template v-if="isReportTab && activeReportTab">
      <!-- 工具栏 -->
      <ReportTabToolbar
        :tab="{
          taskId: activeReportTab.taskId!,
          reportType: activeReportTab.reportType!,
          title: activeReportTab.title,
        }"
        @close-all="handleCloseAllReports"
      />

      <!-- 级联查询 -->
      <CascadeCommunityQuery
        :task-id="activeReportTab.taskId!"
        :edge-type="activeReportTab.reportType === 'dependency' ? 'INCLUDE' : 'CALL'"
        @query="handleCascadeQuery"
      />

      <!-- 主内容: 对话流占满 -->
      <div class="report-main">
        <LLMChatFlow
          ref="chatFlowRef"
          :task-id="activeReportTab.taskId!"
          :edge-type="activeReportTab.reportType === 'dependency' ? 'INCLUDE' : 'CALL'"
          :selected-comm-ids="selectedCommIds"
          :graph-data="graphDataRef"
          @save-subdoc="handleSaveSubdoc"
        />
      </div>
    </template>

    <!-- ===== 子文档 Tab ===== -->
    <template v-else-if="isSubDocTab && activeTab">
      <SubDocViewer
        :sub-doc-id="activeTab.subDocId!"
        @close="projectStore.closeTab(activeTab.id)"
      />
    </template>

    <!-- ===== 空白状态 ===== -->
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

.report-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
