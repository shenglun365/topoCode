<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { PlayIcon, ArrowPathIcon, SparklesIcon } from '@heroicons/vue/24/outline'
import { useSettingsStore } from '@/stores/settings'
import { useReportStore } from '@/stores/report'
import { useProjectStore } from '@/stores/project'
import { useFuncGroupStore } from '@/stores/funcGroup'
import PipelineTaskTree from './PipelineTaskTree.vue'
import type { PipelineTaskNode } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const settingsStore = useSettingsStore()
const reportStore = useReportStore()
const projectStore = useProjectStore()
const funcGroup = useFuncGroupStore()

const props = defineProps<{ taskId: string; taskName?: string }>()

const projectId = computed(() => projectStore.selectedProjectId || '')

const taskState = computed(() => reportStore.tasks[props.taskId])

const rootTask = computed<PipelineTaskNode | null>(() => taskState.value?.pipelineRootTask ?? null)
const progress = computed(() => taskState.value?.pipelineProgress ?? 0)

const leaves = computed(() => {
  if (!rootTask.value) return []
  const result: PipelineTaskNode[] = []
  function walk(n: PipelineTaskNode) {
    if (n.children && n.children.length > 0) {
      n.children.forEach(walk)
    } else {
      result.push(n)
    }
  }
  walk(rootTask.value)
  return result
})

const totalCount = computed(() => {
  const n = leaves.value.length
  return n
})
const completedCount = computed(() => {
  const n = leaves.value.filter(n => n.status === 'completed' || n.status === 'skipped').length
  console.log(`[SH-004] pipeline progress total=${totalCount.value} completed=${n} pct=${totalCount.value > 0 ? Math.round(n / totalCount.value * 100) : 0}`)
  return n
})

// Community progress from reportStore (L0 only — LLM analysis targets root communities)
const communityList = computed(() => {
  const list = taskState.value?.communities || []
  console.log(`[SH-004] communityList total=${list.length}`)
  return list
})
const includeCommunities = computed(() => {
  const list = communityList.value.filter(c => c.edgeType === 'INCLUDE' && c.level === 'L0')
  return list
})
const callCommunities = computed(() => {
  const list = communityList.value.filter(c => c.edgeType === 'CALL' && c.level === 'L0')
  return list
})

interface CommProgress { total: number; completed: number; running: number }
const includeProgress = computed<CommProgress | null>(() => {
  const list = includeCommunities.value
  if (!list.length) return null
  const total = list.length
  const completed = list.filter(c => c.status === 'completed').length
  const running = list.filter(c => c.status === 'running' || c.status === 'queued').length
  console.log(`[SH-004] includeProgress total=${total} completed=${completed} running=${running}`)
  return { total, completed, running }
})
const callProgress = computed<CommProgress | null>(() => {
  const list = callCommunities.value
  if (!list.length) return null
  const total = list.length
  const completed = list.filter(c => c.status === 'completed').length
  const running = list.filter(c => c.status === 'running' || c.status === 'queued').length
  console.log(`[SH-004] callProgress total=${total} completed=${completed} running=${running}`)
  return { total, completed, running }
})

function handleRunNode(nodeId: string) {
  console.log(`[SH-004] handleRunNode ENTER nodeId=${nodeId}`)
  if (nodeId === 'overall_architecture') {
    const ctx = funcGroup.context.analysis
    const homeTab = ctx.tabs.find(t => t.kind === 'reportHome' && (t as any).taskId === props.taskId)
    if (homeTab) {
      funcGroup.setActiveTab('analysis', homeTab.id)
    }
    reportStore.setPendingStepRun(props.taskId, nodeId)
    console.log(`[SH-004] handleRunNode overall_architecture: navigating to reportHome`)
    return
  }
  const root = reportStore.tasks[props.taskId]?.pipelineRootTask
  const find = (node: PipelineTaskNode): PipelineTaskNode | undefined => {
    if (node.id === nodeId) return node
    if (node.children) for (const c of node.children) { const r = find(c); if (r) return r }
    return undefined
  }
  const node = root ? find(root) : undefined
  if (!node) {
    console.log(`[SH-004] handleRunNode node not found: ${nodeId}`)
    return
  }

  reportStore.setPipelineRunning(props.taskId, true)
  reportStore.setPipelinePaused(props.taskId, false)

  if (nodeId === 'validation') {
    node.status = 'running'
    const mid = settingsStore.models.find(m => m.isDefault)?.id
    if (!mid) { node.status = 'error'; node.error = t('report.llmNotConfigured') }
    else {
      settingsStore.testModel(mid).then(() => { node.status = 'completed' }).catch((e: any) => { node.status = 'error'; node.error = e.message })
    }
  } else if (nodeId === 'project_summary') {
    const pid = projectStore.selectedProjectId
    if (!pid) { node.status = 'skipped'; reportStore.recalcProgress(props.taskId); return }
    node.status = 'running'
    Promise.all([
      reportStore.getReadmeContent(pid).catch(() => null),
      reportStore.extractDependencyFiles(pid).catch(() => null),
    ]).then(() => {
      reportStore.generateProjectSummary(pid).then(r => {
        node.status = r?.summary ? 'completed' : 'error'
        if (!r?.summary) node.error = 'Empty summary'
      }).catch((e: any) => { node.status = 'error'; node.error = e.message })
    })
  } else if (nodeId === 'community_analysis') {
    node.status = 'running'
    reportStore.getCascadeLevels(props.taskId, 'CALL').then(levels => {
      node.status = (levels?.levels?.length) ? 'completed' : 'skipped'
    }).catch(() => { node.status = 'skipped' })
  }

  reportStore.setPipelineRunning(props.taskId, false)
  reportStore.recalcProgress(props.taskId)
}

function openCommunityAnalysis() {
  const ctx = funcGroup.context.analysis
  const existing = ctx.tabs.find(
    t => t.kind === 'componentAnalysis' && (t as any).taskId === props.taskId
  )
  if (existing) {
    funcGroup.setActiveTab('analysis', existing.id)
    return
  }
  funcGroup.openTab('analysis', {
    id: `comp-analysis-${props.taskId}-${Date.now()}`,
    kind: 'componentAnalysis',
    title: t('report.pipeline.communityAnalysis'),
    taskId: props.taskId,
    projectId: projectId.value,
  })
}

const { showId, componentId } = useComponentId('RP-005')
</script>

<template>
  <div class="task-list-panel">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div
      v-if="!rootTask"
      class="tl-empty"
    >
      <SparklesIcon class="w-8 h-8" />
      <span>{{ t('report.taskList.empty') }}</span>
    </div>

    <template v-else>
      <div class="tl-header">
        <div
          v-if="taskName"
          class="tl-task-name"
        >
          {{ taskName }}
        </div>
        <div class="tl-progress-row">
          <span class="tl-progress-label">{{ t('report.taskList.progress') }}:</span>
          <span class="tl-progress-text">{{ completedCount }}/{{ totalCount }}</span>
        </div>
        <div class="tl-progress-bar">
          <div
            class="tl-progress-fill"
            :style="{ width: progress + '%' }"
          />
        </div>
      </div>

      <div class="tl-tree">
        <PipelineTaskTree
          :node="rootTask"
          @open-community-analysis="openCommunityAnalysis"
        >
          <template #actions="{ node }">
            <button
              v-if="(!node.children || node.children.length === 0) && !['community_analysis', 'validation'].includes(node.id)"
              class="btn btn-xs btn-ghost task-step-btn"
              :title="node.status === 'completed' ? t('common.retry') : t('common.start')"
              @click.stop="handleRunNode(node.id)"
            >
              <PlayIcon
                v-if="node.status !== 'completed' && node.status !== 'error'"
                class="w-2.5 h-2.5"
              />
              <ArrowPathIcon
                v-else
                class="w-2.5 h-2.5"
              />
            </button>
            <button
              v-if="node.id === 'validation'"
              class="btn btn-xs btn-ghost task-step-btn"
              :title="node.status === 'error' ? t('common.retry') : t('report.pipeline.testConnection')"
              @click.stop="handleRunNode(node.id)"
            >
              <PlayIcon
                v-if="node.status !== 'completed' && node.status !== 'error'"
                class="w-2.5 h-2.5"
              />
              <ArrowPathIcon
                v-else
                class="w-2.5 h-2.5"
              />
            </button>
          </template>
          <template #content="{ node }">
            <div
              v-if="node.id === 'community_analysis'"
              class="ca-monitor"
            >
              <div
                v-if="includeProgress"
                class="ca-row"
              >
                <span class="ca-label">{{ t('report.pipeline.groupInclude') }}</span>
                <div class="ca-bar">
                  <div
                    class="ca-fill"
                    :style="{ width: Math.round((includeProgress.completed / includeProgress.total) * 100) + '%' }"
                  />
                </div>
                <span class="ca-text">
                  <template v-if="includeProgress.running > 0">
                    {{ includeProgress.completed }}/{{ includeProgress.total }}
                    <span class="ca-running">+{{ includeProgress.running }}</span>
                  </template>
                  <template v-else>{{ includeProgress.completed }}/{{ includeProgress.total }}</template>
                </span>
              </div>
              <div
                v-if="callProgress"
                class="ca-row"
              >
                <span class="ca-label">{{ t('report.pipeline.groupCall') }}</span>
                <div class="ca-bar">
                  <div
                    class="ca-fill"
                    :style="{ width: Math.round((callProgress.completed / callProgress.total) * 100) + '%' }"
                  />
                </div>
                <span class="ca-text">
                  <template v-if="callProgress.running > 0">
                    {{ callProgress.completed }}/{{ callProgress.total }}
                    <span class="ca-running">+{{ callProgress.running }}</span>
                  </template>
                  <template v-else>{{ callProgress.completed }}/{{ callProgress.total }}</template>
                </span>
              </div>
            </div>
          </template>
        </PipelineTaskTree>
      </div>
    </template>
  </div>
</template>

<style scoped>
.task-list-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  font-size: 11px;
  overflow: hidden;
}

.tl-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 11px;
}

.tl-header {
  padding: 8px 10px 4px;
  border-bottom: 1px solid var(--border);
}

.tl-task-name {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
  padding-bottom: 4px;
  border-bottom: 1px dashed var(--border);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tl-progress-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.tl-progress-label { color: var(--text-muted); font-size: 10px; white-space: nowrap; }
.tl-progress-text { color: var(--text-secondary); font-family: var(--font-mono); font-size: 10px; white-space: nowrap; }

.tl-progress-bar {
  height: 4px;
  background: var(--bg-primary);
  border-radius: 2px;
  overflow: hidden;
}

.tl-progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 0.3s;
}

.tl-tree {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.task-step-btn {
  padding: 1px 4px;
  opacity: 0.5;
}
.task-step-btn:hover { opacity: 1; }

.ca-monitor {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 3px 0 2px;
}
.ca-row {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 9px;
}
.ca-label {
  color: var(--text-muted);
  white-space: nowrap;
  width: 52px;
  flex-shrink: 0;
}
.ca-bar {
  flex: 1;
  height: 4px;
  background: var(--bg-primary);
  border-radius: 2px;
  overflow: hidden;
}
.ca-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 0.3s;
}
.ca-text {
  color: var(--text-secondary);
  font-family: var(--font-mono);
  white-space: nowrap;
  min-width: 36px;
  text-align: right;
}
.ca-running {
  color: var(--accent);
}
</style>
