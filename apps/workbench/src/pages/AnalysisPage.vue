<script setup lang="ts">
import { computed, onActivated, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { useProjectStore } from '@/stores/project'
import { useFuncGroupStore } from '@/stores/funcGroup'
import { useCommunityStore } from '@/stores/community-store'
import { useAnalysisStore } from '@/stores/analysis'
import HomeTabBar from '@/components/project/HomeTabBar.vue'
import TaskSelect from '@/components/project/TaskSelect.vue'
import SubDocViewer from '@/components/report/SubDocViewer.vue'
import ReportHome from '@/components/report/ReportHome.vue'
import ChatView from '@/components/report/ChatView.vue'
import PreSummaryFileList from '@/components/report/PreSummaryFileList.vue'
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
const communityStore = useCommunityStore()
const analysisStore = useAnalysisStore()
const route = useRoute()

/* ===== 分析功能组上下文 ===== */
const analysisContext = computed(() => funcGroup.context.analysis)
const activeTab = computed(() => {
  const ctx = analysisContext.value;
  return ctx.tabs.find(t => t.id === ctx.activeTabId) || null;
})
const reportTabs = computed(() => {
  return analysisContext.value.tabs.filter(t =>
    t.kind === 'subdoc' || t.kind === 'reportHome' || t.kind === 'preSummaryFiles');
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
const isPreSummaryTab = computed(() => activeTab.value?.kind === 'preSummaryFiles')

/* ===== 解析任务下拉（与 reportHome tab 状态联动） ===== */
const currentAnalysisProjectId = computed(
  () => analysisContext.value.projectId || projectStore.selectedProjectId || '',
)

let loadedTaskProjectId = ''
watch(
  currentAnalysisProjectId,
  async (pid) => {
    if (!pid || pid === loadedTaskProjectId) return
    loadedTaskProjectId = pid
    try {
      await analysisStore.loadTasks(pid)
    } catch { /* 任务列表加载失败时下拉显示为空 */ }
  },
  { immediate: true },
)

const projectTasks = computed(() => {
  const pid = currentAnalysisProjectId.value
  return analysisStore.tasks
    .filter((t) => t.projectId === pid)
    .sort((a, b) => ((b.createdAt || '') > (a.createdAt || '') ? 1 : -1))
    .map((t) => ({ id: t.id, name: t.name }))
})

/** 已打开 reportHome tab 的任务 ID 列表（tab 增删自动联动） */
const openTaskIds = computed(() =>
  analysisContext.value.tabs
    .filter((t) => t.kind === 'reportHome' && t.taskId)
    .map((t) => t.taskId as string),
)

/** 当前激活 reportHome tab 对应的任务 ID（非 reportHome tab 时为 null） */
const activeReportTaskId = computed(() => {
  const a = activeTab.value
  return a && a.kind === 'reportHome' ? (a.taskId ?? null) : null
})

async function refreshTasks() {
  const pid = currentAnalysisProjectId.value
  if (!pid) return
  try {
    await analysisStore.loadTasks(pid)
  } catch { /* ignore */ }
}

/** 点选任务：未打开 → 开 tab；已打开未激活 → 切换；已激活 → 关闭 */
function onTaskSelect(taskId: string) {
  const taskTab = analysisContext.value.tabs.find(
    (t) => t.kind === 'reportHome' && t.taskId === taskId,
  )
  if (!taskTab) {
    const pid = currentAnalysisProjectId.value
    const task = analysisStore.tasks.find((x) => x.id === taskId)
    projectStore.openReportHomeTab({
      taskId,
      taskName: task?.name || taskId,
      projectId: pid || undefined,
      projectName: projectStore.selectedProject?.name,
    })
    return
  }
  if (analysisContext.value.activeTabId === taskTab.id) {
    onTabClose(taskTab.id)
    return
  }
  funcGroup.setActiveTab('analysis', taskTab.id)
}

onMounted(() => {
  panelStore.setLeftCollapsed(false)
  panelStore.setRightCollapsed(false)
})

// P5: URL 驱动分析任务（/analysis?project=&task=）——确保项目上下文并打开对应报告 tab
watch(
  () => [route.query.project, route.query.task] as const,
  async ([projectId, taskId]) => {
    if (typeof taskId !== 'string' || !taskId) return
    const pid = typeof projectId === 'string' ? projectId : (projectStore.selectedProjectId || '')
    if (pid && funcGroup.context.analysis.projectId !== pid) {
      funcGroup.selectProject('analysis', pid)
      // 该路径绕过 projectStore.selectProject，同步最近项目键
      try { localStorage.setItem('topoone-last-project', pid) } catch { /* ignore */ }
    }
    const project = projectStore.projects.find((p) => p.id === pid)
    let taskName = taskId
    try {
      if (pid) {
        const loaded = analysisStore.tasks.find((x: any) => x.projectId === pid)
        if (!loaded) await analysisStore.loadTasks(pid)
        const t = analysisStore.tasks.find((x: any) => x.id === taskId)
        if (t) taskName = t.name || taskName
      }
    } catch { /* 任务名解析失败则回退 taskId */ }
    projectStore.openReportHomeTab({
      taskId,
      taskName,
      projectId: pid,
      projectName: project?.name,
    })
  },
  { immediate: true },
)

// 页面激活时重连 agent 轮询（切回本页时 polling 可能中断）
onActivated(() => {
  const tid = projectStore.activeTab?.taskId
  if (tid) communityStore.ensureAgentPolling(tid)
})

// 任务切换时清理旧轮询 + 启动新轮询
let lastPollTaskId = ''
watch(() => projectStore.activeTab?.taskId, (newTaskId) => {
  if (newTaskId && newTaskId !== lastPollTaskId) {
    if (lastPollTaskId) communityStore.cancelAgentPolling(lastPollTaskId)
    lastPollTaskId = newTaskId
    communityStore.ensureAgentPolling(newTaskId)
  }
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

// 处理报告首页的 open-presummary 事件
function handleOpenPreSummary(taskId: string) {
  const id = `tab-presummary-${taskId}`
  funcGroup.openTab('analysis', {
    id,
    kind: 'preSummaryFiles',
    title: t('analysis.presummary'),
    taskId,
    projectId: projectStore.selectedProjectId || undefined,
  } as any)
}

// 处理报告首页的 open-md 事件（在 analysis 上下文中打开 inline 子文档 tab）
function handleOpenMD(params: { taskId: string; content: string; title: string; subDocId?: string; parentLevel?: string; parentCommId?: string; parentEdgeType?: string }) {
  const hash = params.title.slice(0, 20).replace(/[^a-zA-Z0-9\u4e00-\u9fff]/g, '_')
  const id = `tab-subdoc-inline-${params.taskId}-${hash}`
  funcGroup.openTab('analysis', {
    id,
    kind: 'subdoc',
    subDocId: params.subDocId,
    title: params.title,
    content: params.content,
    taskId: params.taskId,
    projectId: projectStore.selectedProjectId || undefined,
    hasUnsavedChanges: false,
    parentLevel: params.parentLevel,
    parentCommId: params.parentCommId,
    parentEdgeType: params.parentEdgeType,
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
      parts.push(t('report.communityHeading', { name: llmResult.name || communityId }))
      parts.push('')
      parts.push(`**ID**: ${communityId}`)
      parts.push('')
      parts.push(llmResult.summary || '')
    }
    // 无 LLM 结果 → 不传 content，由 SubDocViewer 显示引导提示
    handleOpenMD({
      taskId,
      content: parts.join('\n'),
      title: communityId,
      parentLevel: communityLevel,
      parentCommId: communityId,
      parentEdgeType: edgeType,
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
    >
      <template #actions>
        <TaskSelect
          :tasks="projectTasks"
          :open-task-ids="openTaskIds"
          :active-task-id="activeReportTaskId"
          @select="onTaskSelect"
          @toggle="(o: boolean) => { if (o) refreshTasks() }"
        />
      </template>
    </HomeTabBar>

    <!-- ===== 报告首页（分析报告生成） / 子文档 / 空白状态 ===== -->
    <template v-if="isReportHomeTab && activeTab">
      <ReportHome
        :key="activeTab.id"
        :task-id="activeTab.taskId!"
        :tab-id="activeTab.id"
        @open-md="handleOpenMD"
        @open-presummary="handleOpenPreSummary"
      />
    </template>
    <template v-else-if="isPreSummaryTab && activeTab">
      <PreSummaryFileList
        :key="activeTab.id"
        :task-id="activeTab.taskId!"
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
        @close="goToReportHome"
        @navigate-community="openCommunityDetail"
      />
    </template>

    <!-- Agent 对话面板（浮动按钮触发） -->
    <div
      v-if="showChatPanel"
      class="chat-panel"
    >
      <ChatView />
    </div>
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
  width: calc(420px * var(--ui-scale, 1));
  height: calc(520px * var(--ui-scale, 1));
  z-index: 100;
  border-radius: 0.75rem;
  box-shadow: 0 4px 24px rgba(0,0,0,0.4);
  overflow: hidden;
}
</style>
