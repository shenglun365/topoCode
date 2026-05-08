<script setup lang="ts">
import { onMounted, ref } from 'vue'
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
import TaskCard from '@/components/analysis/TaskCard.vue'
import TaskReport from '@/components/analysis/TaskReport.vue'

const { t } = useI18n()
const analysisStore = useAnalysisStore()
const statusFilter = ref<string[]>(['all'])

onMounted(async () => {
  await analysisStore.loadTasks()
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
</script>

<template>
  <div class="page-analysis">
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
</style>
