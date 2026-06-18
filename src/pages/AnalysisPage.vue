<script setup lang="ts">
import { computed, onDeactivated, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useProjectStore } from '@/stores/project'
import { useFuncGroupStore } from '@/stores/funcGroup'
import { useCommunityStore } from '@/stores/community-store'
import HomeTabBar from '@/components/project/HomeTabBar.vue'
import SubDocViewer from '@/components/report/SubDocViewer.vue'
import ReportHome from '@/components/report/ReportHome.vue'
import ChatView from '@/components/report/ChatView.vue'
import { usePanelStore } from '@/stores/panel'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PG-002')
const { t } = useI18n()
const showChatPanel = ref(false)

function toggleChatPanel() {
  showChatPanel.value = !showChatPanel.value
}
const projectStore = useProjectStore()
const funcGroup = useFuncGroupStore()
const panelStore = usePanelStore()

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
  funcGroup.cleanTabExtraState('analysis', tabId)
  funcGroup.closeTab('analysis', tabId)
}

const isReportHomeTab = computed(() => activeTab.value?.kind === 'reportHome')
const isSubDocTab = computed(() => activeTab.value?.kind === 'subdoc')

onMounted(() => {
  panelStore.setLeftCollapsed(false)
  panelStore.setRightCollapsed(false)
})

onDeactivated(() => {
  useCommunityStore().cancelAgentPolling()
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

async function openCommunityDetail(payload: { taskId: string; communityId: string; edgeType: string }) {
  const { taskId, communityId, edgeType } = payload
  const pid = projectStore.selectedProjectId
  if (!pid) return
  try {
    const allResp = await window.api!.analysis.listCommunityResults(taskId, edgeType)
      .catch(() => ({ results: [] }))
    const found: any = Array.isArray(allResp?.results)
      ? allResp.results.find((r: any) => (r.commId || r.comm_id) === communityId)
      : null
    const communityLevel = found?.commLv || found?.comm_lv || 'L0'

    const llmResult = found || await window.api!.analysis.getCommunityResult({
      taskId, edgeType, commLv: communityLevel, commId: communityId,
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
      const detail = await window.api!.report.getLevelCommunityDetail({
        projectId: pid, taskId,
        level: communityLevel, edgeType,
      })
      const community = detail.communities.find((c: any) => c.communityId === communityId)
      if (!community) return
      const nodeLines = community.nodes.map((n: any) => `- ${n.name} (${n.filePath})`).join('\n')
      const edgeLines = community.edges.map((e: any) => `- ${e.source} → ${e.target} [${e.type}]`).join('\n')
      parts.push(
        `# 社区: ${communityId}`,
        '',
        `**层级**: ${communityLevel} | **边缘类型**: ${edgeType}`,
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
      parentLevel: communityLevel,
      parentCommId: communityId,
      parentEdgeType: edgeType,
      regenerationType: 'community',
    })
  } catch (e: any) {
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
      :active-tab-id="analysisContext.activeTabId ?? null"
      @update:active-tab-id="onTabUpdate"
      @close="onTabClose"
    />

    <!-- ===== 报告首页（分析报告生成） / 子文档 / 空白状态 ===== -->
    <template v-if="isReportHomeTab && activeTab">
      <ReportHome
        :key="activeTab.id"
        :task-id="activeTab.taskId!"
        :tab-id="activeTab.id"
        @open-md="handleOpenMD"
      />
    </template>

    <!-- Agent 对话面板（浮动按钮触发） -->
    <div
      v-if="showChatPanel"
      class="chat-panel"
    >
      <ChatView />
    </div>

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
      />
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

.comp-analysis-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Chat panel (floating) */
.chat-panel {
  position: fixed;
  bottom: 1rem;
  right: 1rem;
  width: 420px;
  height: 520px;
  z-index: 100;
  border-radius: 0.75rem;
  box-shadow: 0 4px 24px rgba(0,0,0,0.4);
  overflow: hidden;
}
</style>
