<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ChartBarIcon,
  PlusIcon,
  ArrowPathIcon,
  BookOpenIcon,
  Squares2X2Icon,
  ListBulletIcon,
} from '@heroicons/vue/24/outline'
import { useAnalysisStore } from '@/stores/analysis'
import { useProjectStore } from '@/stores/project'
import TaskCard from '@/components/analysis/TaskCard.vue'
import TaskReport from '@/components/analysis/TaskReport.vue'
import ReportTabToolbar from '@/components/report/ReportTabToolbar.vue'
import ReportQueryPanel from '@/components/report/ReportQueryPanel.vue'
import ReportGraphView from '@/components/report/ReportGraphView.vue'

const { t } = useI18n()
const analysisStore = useAnalysisStore()
const projectStore = useProjectStore()
const statusFilter = ref<string[]>(['all'])
// 注意：任务列表由 LeftPanel 中的项目列表选择后加载，不再在 onMounted 中调用

// 当前激活的报告 tab
const activeReportTab = computed(() => {
  const tab = projectStore.activeTab
  return tab?.kind === 'report' ? tab : null
})

function toggleStatus(status: string) {
  if (status === 'all') {
    statusFilter.value = ['all']
  } else {
    statusFilter.value = statusFilter.value.filter(s => s !== 'all')
    if (statusFilter.value.includes(status)) {
      statusFilter.value = statusFilter.value.filter(s => s !== status)
    } else {
      statusFilter.value.push(status)
    }
    if (statusFilter.value.length === 0) {
      statusFilter.value = ['all']
    }
  }
}

// 关闭所有报告 tab
function handleCloseAllReports() {
  projectStore.closeAllReportTabs()
}

// 处理查询
const graphViewRef = ref<any>(null)
const currentQuery = ref<any>(null)

function handleQuery(params: { commLv: string; commIds: string[]; depth: number }) {
  currentQuery.value = params
  graphViewRef.value?.queryGraph(params)
}

// 节点/边/社区点击事件（对接右侧代码索引面板）
async function handleNodeClick(nodeId: string, nodeData: any) {
  // 请求后端获取符号详情
  try {
    const detail = await window.api.ipc.invoke('analysis.getSymbolDetail', {
      taskId: activeReportTab.value?.taskId,
      symbolId: nodeId,
    })
    if (detail) {
      // TODO: 通过 App.vue 获取 RightPanel ref，调用 codeIndexRef.addNodeMessage()
      console.log('[AnalysisPage] Node detail:', detail)
    }
  } catch (e) {
    console.error('[AnalysisPage] Failed to get symbol detail:', e)
  }
}

async function handleEdgeClick(edgeId: string, edgeData: any) {
  try {
    const detail = await window.api.ipc.invoke('analysis.getEdgeDetail', {
      taskId: activeReportTab.value?.taskId,
      edgeId: edgeId,
    })
    if (detail) {
      console.log('[AnalysisPage] Edge detail:', detail)
    }
  } catch (e) {
    console.error('[AnalysisPage] Failed to get edge detail:', e)
  }
}

function handleCommunityClick(commId: string, commData: any) {
  console.log('[AnalysisPage] Community clicked:', commId, commData)
  // TODO: 追加社区消息到代码索引面板
}

function handleCommunityDblClick(commId: string) {
  console.log('[AnalysisPage] Community double-clicked:', commId)
  // TODO: 深度 +1 重新查询
  if (graphViewRef.value && currentQuery.value) {
    const newQuery = { ...currentQuery.value, depth: Math.min(4, currentQuery.value.depth + 1) }
    graphViewRef.value.queryGraph(newQuery)
  }
}
</script>

<template>
  <div class="page-analysis">
    <!-- 报告 Tab 视图 -->
    <template v-if="activeReportTab">
      <!-- 报告工具栏 -->
      <ReportTabToolbar
        :tab="{
          taskId: activeReportTab.taskId!,
          reportType: activeReportTab.reportType!,
          title: activeReportTab.title,
        }"
        @close-all="handleCloseAllReports"
      />
      <!-- 查询条件面板 -->
      <ReportQueryPanel
        :task-id="activeReportTab.taskId!"
        @query="handleQuery"
      />
      <!-- 图渲染区域 -->
      <div class="report-graph-area">
        <ReportGraphView
          ref="graphViewRef"
          :task-id="activeReportTab.taskId!"
          :edge-type="activeReportTab.reportType === 'dependency' ? 'INCLUDE' : 'CALL'"
          @node-click="handleNodeClick"
          @edge-click="handleEdgeClick"
          @community-click="handleCommunityClick"
          @community-dblclick="handleCommunityDblClick"
        />
      </div>
    </template>

    <!-- 任务列表视图 -->
    <template v-else>
      <!-- 工具栏 -->
      <div style="display:flex; align-items:center; padding:6px 12px; gap:8px; border-bottom:1px solid var(--border); background:var(--bg-secondary);">
        <button class="btn btn-primary btn-sm">
          <PlusIcon class="w-4 h-4" />
          <span>{{ t('analysis.newTask') }}</span>
        </button>
        <button class="btn btn-ghost btn-sm">
          <ArrowPathIcon class="w-4 h-4" />
          <span>{{ t('common.refresh') }}</span>
        </button>
        <div class="divider-vertical"></div>
        <button class="btn btn-ghost btn-sm" style="color:var(--accent);">
          <BookOpenIcon class="w-4 h-4" />
          <span>{{ t('knowledge.extractKnowledge') }}</span>
        </button>
        <span class="badge badge-green">{{ t('analysis.astReady') }}</span>
        <span class="badge badge-blue">{{ t('analysis.aiOnline') }}</span>
        <div style="flex:1;"></div>
        <span class="text-muted" style="font-size:11px;">
          {{ t('analysis.taskSummary', { total: analysisStore.taskStats.total, done: analysisStore.taskStats.done }) }}
        </span>
      </div>

      <!-- 内容区 -->
      <div style="flex:1; overflow:hidden; display:flex; flex-direction:column;">
        <!-- 任务列表 -->
        <div style="flex:1; overflow:auto; padding:12px;">
        <!-- 筛选栏 -->
        <div style="display:flex; align-items:center; gap:8px; margin-bottom:12px; flex-wrap:wrap;">
          <span style="font-size:11px; color:var(--text-muted);">{{ t('common.status') }}:</span>
          <label class="checkbox" style="font-size:11px;">
            <input type="checkbox" :checked="statusFilter.includes('all')" @change="toggleStatus('all')">
            <span>{{ t('common.all') }}</span>
          </label>
          <label class="checkbox" style="font-size:11px;">
            <input type="checkbox" :checked="statusFilter.includes('done')" @change="toggleStatus('done')">
            <span style="color:var(--success);">● {{ t('common.completed') }}</span>
          </label>
          <label class="checkbox" style="font-size:11px;">
            <input type="checkbox" :checked="statusFilter.includes('running')" @change="toggleStatus('running')">
            <span style="color:var(--warning);">● {{ t('analysis.inProgress') }}</span>
          </label>
          <label class="checkbox" style="font-size:11px;">
            <input type="checkbox" :checked="statusFilter.includes('pending')" @change="toggleStatus('pending')">
            <span style="color:var(--text-muted);">● {{ t('analysis.notStarted') }}</span>
          </label>
          <label class="checkbox" style="font-size:11px;">
            <input type="checkbox" :checked="statusFilter.includes('error')" @change="toggleStatus('error')">
            <span style="color:var(--error);">● {{ t('common.failed') }}</span>
          </label>
          <div class="divider-vertical"></div>
          <span style="font-size:11px; color:var(--text-muted);">{{ t('analysis.view') }}:</span>
          <button
            class="btn btn-ghost btn-sm"
            :class="{ active: analysisStore.filter.viewMode === 'card' }"
            @click="analysisStore.setViewMode('card')"
            :title="t('analysis.cardView')"
          >
            <Squares2X2Icon class="w-4 h-4" />
          </button>
          <button
            class="btn btn-ghost btn-sm"
            :class="{ active: analysisStore.filter.viewMode === 'list' }"
            @click="analysisStore.setViewMode('list')"
            :title="t('analysis.listView')"
          >
            <ListBulletIcon class="w-4 h-4" />
          </button>
        </div>

        <!-- 任务卡片网格 -->
        <div
          v-if="analysisStore.filteredTasks.length > 0"
          style="display:grid; grid-template-columns:repeat(auto-fill, minmax(300px, 1fr)); gap:10px;"
        >
          <TaskCard
            v-for="task in analysisStore.filteredTasks"
            :key="task.id"
            :task="task"
            @select="analysisStore.selectTask(task.id)"
            @run="analysisStore.runTask($event)"
            @toggle-favorite="analysisStore.toggleFavorite($event)"
            @toggle-pin="analysisStore.togglePin($event)"
          />
        </div>

        <!-- 空状态 -->
        <div v-else class="empty-state">
          <ChartBarIcon class="icon" />
          <div class="title">{{ t('analysis.noTasks') }}</div>
          <div class="desc">{{ t('analysis.clickNewTask') }}</div>
        </div>
      </div>
    </div>

    <!-- 选中的任务报告 -->
    <div
      v-if="analysisStore.selectedTask"
      class="report-panel"
    >
      <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 12px; border-bottom:1px solid var(--border);">
        <span style="font-size:12px; font-weight:600;">{{ analysisStore.selectedTask.name }} - {{ t('common.report') }}</span>
        <button class="btn btn-ghost btn-sm" @click="analysisStore.deselectTask()">
          ✕
        </button>
      </div>
      <TaskReport :task="analysisStore.selectedTask" />
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

.report-panel {
  height: 40%;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.report-graph-area {
  flex: 1;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
