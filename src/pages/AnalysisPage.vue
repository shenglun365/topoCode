<script setup lang="ts">
import { computed, onActivated, onDeactivated, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChartBarIcon, ArrowLeftIcon } from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import { useFuncGroupStore } from '@/stores/funcGroup'
import HomeTabBar from '@/components/project/HomeTabBar.vue'
import SubDocViewer from '@/components/report/SubDocViewer.vue'
import ReportHome from '@/components/report/ReportHome.vue'
import CommunityAnalysisPipeline from '@/components/report/CommunityAnalysisPipeline.vue'
import ChildAnalysisPanel from '@/components/report/ChildAnalysisPanel.vue'
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
  return analysisContext.value.tabs.filter(t => t.kind === 'subdoc' || t.kind === 'reportHome' || t.kind === 'componentAnalysis' || t.kind === 'childAnalysis');
})

function onTabUpdate(tabId: string | null) {
  funcGroup.setActiveTab('analysis', tabId)
}

function onTabClose(tabId: string) {
  funcGroup.closeTab('analysis', tabId)
}

const isReportHomeTab = computed(() => activeTab.value?.kind === 'reportHome')
const isSubDocTab = computed(() => activeTab.value?.kind === 'subdoc')
const isComponentAnalysisTab = computed(() => activeTab.value?.kind === 'componentAnalysis')
const isChildAnalysisTab = computed(() => activeTab.value?.kind === 'childAnalysis')

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

// 子文档“返回报告”按钮：切换到所属报告的 reportHome/reportTree tab
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

// 组件 AI 分析“返回”按钮：切换到对应的 reportHome tab
function goBackFromCompAnalysis() {
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

// 子层级分析“返回”按钮
function goBackFromChildAnalysis() {
  const tab = activeTab.value
  if (!tab) return
  const taskId = tab.taskId
  const parentCommId = tab.parentCommId
  if (!taskId || !parentCommId) {
    onTabClose(tab.id)
    return
  }
  const parentTab = analysisContext.value.tabs.find(t =>
    (t.kind === 'subdoc' && t.parentCommId === parentCommId && t.taskId === taskId) ||
    (t.kind === 'reportHome' && t.taskId === taskId)
  )
  if (parentTab) {
    funcGroup.setActiveTab('analysis', parentTab.id)
  } else {
    onTabClose(tab.id)
  }
}

// 处理报告首页的 open-md 事件（在 analysis 上下文中打开 inline 子文档 tab）
function handleOpenMD(params: { taskId: string; content: string; title: string; parentLevel?: string; parentCommId?: string; parentEdgeType?: string; regenerationType?: 'community' | 'overall' }) {
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
    parentLevel: params.parentLevel,
    parentCommId: params.parentCommId,
    parentEdgeType: params.parentEdgeType,
    regenerationType: params.regenerationType,
  })
}

function handleViewChildCommunityMD(params: { taskId?: string; communityId: string; level: string; edgeType: string; parentLevel?: string; parentCommId?: string; name: string; summary: string; mermaid?: string; plantuml?: string }) {
  console.log(`[AnalysisPage] handleViewChildCommunityMD`, params)
  const parts: string[] = [
    `# 社区: ${params.name}`,
    '',
    `**ID**: ${params.communityId}`,
    '',
    params.summary,
  ]
  if (params.mermaid) {
    parts.push('', '```mermaid', params.mermaid, '```')
  }
  if (params.plantuml) {
    parts.push('', '```plantuml', params.plantuml, '```')
  }
  handleOpenMD({
    taskId: params.taskId || activeTab.value?.taskId || '',
    content: parts.join('\n'),
    title: params.name,
    parentLevel: params.parentLevel,
    parentCommId: params.parentCommId,
    parentEdgeType: params.edgeType,
    regenerationType: 'community',
  })
}

function handleOpenChildAnalysis(params: { taskId: string; parentLevel: string; parentCommId: string; edgeType: string; projectId?: string }) {
  const tabId = `child-analysis|${params.taskId}|${params.parentLevel}|${params.parentCommId}|${params.edgeType}`
  const childLevel = `L${parseInt(params.parentLevel[1]) + 1}`
  funcGroup.openTab('analysis', {
    id: tabId,
    kind: 'childAnalysis',
    title: `${childLevel} ${t('report.pipeline.communityAnalysis')} - ${params.parentCommId}`,
    taskId: params.taskId,
    projectId: params.projectId || projectStore.selectedProjectId || undefined,
    parentLevel: params.parentLevel,
    parentCommId: params.parentCommId,
    parentEdgeType: params.edgeType,
  })
}

async function openCommunityDetail(payload: { taskId: string; communityId: string; edgeType: string }) {
  const { taskId, communityId, edgeType } = payload
  const pid = projectStore.selectedProjectId
  if (!pid) return
  try {
    const llmResult = await window.api.analysis.getCommunityResult({
      taskId, edgeType, commLv: 'L0', commId: communityId,
    }).catch(() => null)
    const parts: string[] = []
    if (llmResult?.name || llmResult?.summary) {
      parts.push(`# 社区: ${llmResult.name || communityId}`)
      parts.push('')
      parts.push(`**ID**: ${communityId}`)
      parts.push('')
      parts.push(llmResult.summary || '')
      if (llmResult.mermaid) {
        parts.push('', '```mermaid', llmResult.mermaid, '```')
      }
      if (llmResult.plantuml) {
        parts.push('', '```plantuml', llmResult.plantuml, '```')
      }
    } else {
      const detail = await window.api.report.getLevelCommunityDetail({
        projectId: pid, taskId,
        level: 'L0', edgeType,
      })
      const community = detail.communities.find((c: any) => c.communityId === communityId)
      if (!community) return
      const nodeLines = community.nodes.map((n: any) => `- ${n.name} (${n.filePath})`).join('\n')
      const edgeLines = community.edges.map((e: any) => `- ${e.source} → ${e.target} [${e.type}]`).join('\n')
      parts.push(
        `# 社区: ${communityId}`,
        '',
        `**层级**: L0 | **边缘类型**: ${edgeType}`,
        `**节点数**: ${community.nodeCount} | **边数**: ${community.edgeCount} | **质量分**: ${community.qualityScore ?? '-'}`,
        '',
        '## 节点列表',
        nodeLines || '（空）',
        '',
        '## 边列表',
        edgeLines || '（空）',
      )
    }
    handleOpenMD({
      taskId,
      content: parts.join('\n'),
      title: communityId,
    })
  } catch (e) {
    console.error('[AnalysisPage] openCommunityDetail error:', e)
  }
}

</script>

<template>
  <div class="page-analysis">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- ===== 公共 Tab 栏 — 显示所有报告类型 ===== -->
    <HomeTabBar
      :tabs="reportTabs"
      :active-tab-id="analysisContext.activeTabId"
      @update:active-tab-id="onTabUpdate"
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
        :task-id="activeTab.taskId"
        :parent-level="activeTab.parentLevel"
        :parent-comm-id="activeTab.parentCommId"
        :parent-edge-type="activeTab.parentEdgeType"
        :project-id="activeTab.projectId"
        :regeneration-type="activeTab.regenerationType as 'community' | 'overall' | undefined"
        @close="goToReportHome"
        @navigate-community="openCommunityDetail"
        @open-child-analysis="handleOpenChildAnalysis"
        @view-child-md="handleViewChildCommunityMD"
      />
    </template>

    <template v-else-if="isComponentAnalysisTab && activeTab">
      <div class="comp-analysis-container">
        <div class="comp-analysis-header">
          <button
            class="btn btn-ghost btn-sm"
            @click="goBackFromCompAnalysis"
          >
            <ArrowLeftIcon class="w-3.5 h-3.5" />
            <span>{{ t('common.back') }}</span>
          </button>
          <span class="comp-analysis-title">{{ activeTab.title }}</span>
        </div>
        <div class="comp-analysis-body">
          <CommunityAnalysisPipeline
            :task-id="activeTab.taskId!"
            :project-id="activeTab.projectId || projectStore.selectedProjectId || ''"
          />
        </div>
      </div>
    </template>

    <template v-else-if="isChildAnalysisTab && activeTab">
      <div class="comp-analysis-container">
        <div class="comp-analysis-header">
          <button
            class="btn btn-ghost btn-sm"
            @click="goBackFromChildAnalysis"
          >
            <ArrowLeftIcon class="w-3.5 h-3.5" />
            <span>{{ t('common.back') }}</span>
          </button>
          <span class="comp-analysis-title">{{ activeTab.title }}</span>
        </div>
        <div class="comp-analysis-body">
          <ChildAnalysisPanel
            :task-id="activeTab.taskId!"
            :parent-level="activeTab.parentLevel || 'L0'"
            :parent-comm-id="activeTab.parentCommId || ''"
            :edge-type="activeTab.parentEdgeType || 'CALL'"
            :project-id="activeTab.projectId || projectStore.selectedProjectId || ''"
            @view-community-md="handleViewChildCommunityMD"
          />
        </div>
      </div>
    </template>

    <template v-else>
      <div class="analysis-empty">
        <ChartBarIcon class="w-16 h-16" />
        <div class="title">
          {{ t('analysis.selectReportHint') }}
        </div>
        <div class="desc">
          {{ t('analysis.selectReportHintDesc') }}
        </div>
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

.comp-analysis-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.comp-analysis-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-tertiary);
}

.comp-analysis-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.comp-analysis-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

</style>
