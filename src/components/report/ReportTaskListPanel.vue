<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { PlayIcon, ArrowPathIcon, SparklesIcon } from '@heroicons/vue/24/outline'
import { usePipelineStore, type EdgeProgress } from '@/stores/pipeline'
import { useProjectStore } from '@/stores/project'
import { useFuncGroupStore } from '@/stores/funcGroup'
import PipelineTaskTree from './PipelineTaskTree.vue'
import type { PipelineTaskNode } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const store = usePipelineStore()
const projectStore = useProjectStore()
const funcGroup = useFuncGroupStore()

const props = defineProps<{ taskId: string; taskName?: string }>()

const projectId = computed(() => projectStore.selectedProjectId || '')

const state = computed(() => store.getTaskState(props.taskId))

const rootTask = computed<PipelineTaskNode | null>(() => state.value?.rootTask ?? null)
const progress = computed(() => state.value?.progress ?? 0)

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

const totalCount = computed(() => leaves.value.length)
const completedCount = computed(() => leaves.value.filter(n => n.status === 'completed' || n.status === 'skipped').length)

const ctrl = computed(() => store.controls)

const communityProgress = computed(() => store.getTaskState(props.taskId)?.communityProgress)

const includeProgress = computed(() => {
  const p = communityProgress.value?.INCLUDE
  if (!p || p.total === 0) return null
  return { ...p, pct: Math.round((p.completed / p.total) * 100) }
})

const callProgress = computed(() => {
  const p = communityProgress.value?.CALL
  if (!p || p.total === 0) return null
  return { ...p, pct: Math.round((p.completed / p.total) * 100) }
})

function handleRunNode(nodeId: string) {
  ctrl.value?.runNode(nodeId)
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
    <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <div v-if="!rootTask" class="tl-empty">
      <SparklesIcon class="w-8 h-8" />
      <span>{{ t('report.taskList.empty') }}</span>
    </div>

    <template v-else>
      <div class="tl-header">
        <div v-if="taskName" class="tl-task-name">{{ taskName }}</div>
        <div class="tl-progress-row">
          <span class="tl-progress-label">{{ t('report.taskList.progress') }}:</span>
          <span class="tl-progress-text">{{ completedCount }}/{{ totalCount }}</span>
        </div>
        <div class="tl-progress-bar">
          <div class="tl-progress-fill" :style="{ width: progress + '%' }"></div>
        </div>
      </div>

      <div class="tl-tree">
        <PipelineTaskTree
          :node="rootTask"
          @action="handleRunNode"
          @open-community-analysis="openCommunityAnalysis"
        >
          <template #actions="{ node }">
            <button
              v-if="(!node.children || node.children.length === 0) && !['community_analysis', 'validation'].includes(node.id)"
              class="btn btn-xs btn-ghost task-step-btn"
              :title="node.status === 'completed' ? t('common.retry') : t('common.start')"
              @click.stop="handleRunNode(node.id)"
            >
              <PlayIcon v-if="node.status !== 'completed' && node.status !== 'error'" class="w-2.5 h-2.5" />
              <ArrowPathIcon v-else class="w-2.5 h-2.5" />
            </button>
            <button
              v-if="node.id === 'validation'"
              class="btn btn-xs btn-ghost task-step-btn"
              :title="node.status === 'error' ? t('common.retry') : t('report.pipeline.testConnection')"
              @click.stop="handleRunNode(node.id)"
            >
              <PlayIcon v-if="node.status !== 'completed' && node.status !== 'error'" class="w-2.5 h-2.5" />
              <ArrowPathIcon v-else class="w-2.5 h-2.5" />
            </button>
          </template>
          <template #content="{ node }">
            <div v-if="node.id === 'community_analysis'" class="ca-monitor">
              <div v-if="includeProgress" class="ca-row">
                <span class="ca-label">依赖分组</span>
                <div class="ca-bar"><div class="ca-fill" :style="{ width: includeProgress.pct + '%' }"></div></div>
                <span class="ca-text">
                  <template v-if="includeProgress.running > 0">
                    {{ includeProgress.completed }}/{{ includeProgress.total }}
                    <span class="ca-running">+{{ includeProgress.running }}</span>
                  </template>
                  <template v-else>{{ includeProgress.completed }}/{{ includeProgress.total }}</template>
                </span>
              </div>
              <div v-if="callProgress" class="ca-row">
                <span class="ca-label">调用分组</span>
                <div class="ca-bar"><div class="ca-fill" :style="{ width: callProgress.pct + '%' }"></div></div>
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
