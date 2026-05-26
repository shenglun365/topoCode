<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  CheckCircleIcon,
  ClockIcon,
  XCircleIcon,
  ArrowPathIcon,
  SparklesIcon,
} from '@heroicons/vue/24/outline'
import { useSettingsStore } from '@/stores/settings'
import { useProjectStore } from '@/stores/project'
import PipelineTaskTree from './PipelineTaskTree.vue'
import CommunityAnalysisPipeline from './CommunityAnalysisPipeline.vue'
import type { PipelineTaskNode } from '@/types/ipc'
import { usePipelineStore } from '@/stores/pipeline'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const settingsStore = useSettingsStore()
const projectStore = useProjectStore()
const pipelineStore = usePipelineStore()

const props = defineProps<{
  taskId: string
  projectId?: string
}>()

const emit = defineEmits<{
  generated: [content: string]
  close: []
  communityResults: [summaries: Array<{ communityId: string; level: string; edgeType: string; name: string; summary: string }>]
  viewCommunityMD: [params: { communityId: string; name: string; summary: string; mermaid?: string; plantuml?: string }]
}>()

function createInitialTree(): PipelineTaskNode {
  return {
    id: 'root',
    label: t('report.pipeline.generationPipeline'),
    type: 'group',
    status: 'pending',
    progress: 0,
    children: [
      {
        id: 'validation',
        label: t('report.pipeline.modelValidation'),
        type: 'step',
        status: 'pending',
        progress: 0,
      },
      {
        id: 'project_summary',
        label: t('report.pipeline.preprocessing'),
        type: 'step',
        status: 'pending',
        progress: 0,
      },
      {
        id: 'community_analysis',
        label: t('report.pipeline.communityAnalysis'),
        type: 'step',
        status: 'pending',
        progress: 0,
      },
      {
        id: 'step1', label: t('report.pipeline.projectSummary'), type: 'step', status: 'pending', progress: 0,
        templateId: 'report_project_summary', dependsOn: ['project_summary'],
      },
      {
        id: 'step2', label: t('report.pipeline.archDecomposition'), type: 'step', status: 'pending', progress: 0,
        templateId: 'report_arch_decomposition', dependsOn: ['community_analysis', 'step1'],
      },
      {
        id: 'step3', label: t('report.pipeline.coreModules'), type: 'step', status: 'pending', progress: 0,
        templateId: 'report_core_modules', dependsOn: ['step2'],
      },
      {
        id: 'step4', label: t('report.pipeline.dependencyAnalysis'), type: 'step', status: 'pending', progress: 0,
        templateId: 'report_dependency_analysis', dependsOn: ['step3'],
      },
      {
        id: 'step5', label: t('report.pipeline.finalAssembly'), type: 'step', status: 'pending', progress: 0,
        templateId: 'report_final_assembly', dependsOn: ['step4'],
      },
    ],
  }
}

function markOrphanRunningAsPending(node: PipelineTaskNode) {
  if ((node.status === 'running' || node.status === 'queued') && node.id !== 'root') {
    node.status = 'pending'
  }
  if (node.children) node.children.forEach(markOrphanRunningAsPending)
}

function buildTree(): PipelineTaskNode {
  const saved = pipelineStore.getTaskState(props.taskId)
  if (saved) {
    const tree = JSON.parse(JSON.stringify(saved.rootTask))
    markOrphanRunningAsPending(tree)
    return tree
  }
  return createInitialTree()
}

const rootTask = ref<PipelineTaskNode>(buildTree())

const saved = pipelineStore.getTaskState(props.taskId)
const running = ref(saved?.running ?? false)
const overallProgress = ref(saved?.progress ?? 0)
const isPaused = ref(saved?.paused ?? false)
const stepOutputs = ref<Record<string, string>>(saved?.stepOutputs || {})

// 项目摘要生成状态

const allCompleted = computed(() => {
  return rootTask.value.children?.every(n => n.status === 'completed' || n.status === 'skipped')
})
const hasError = computed(() => rootTask.value.children?.some(n => n.status === 'error'))

function updateNodeStatus(nodeId: string, status: PipelineTaskNode['status'], error?: string) {
  const update = (node: PipelineTaskNode): boolean => {
    if (node.id === nodeId) {
      node.status = status
      if (error) node.error = error
      return true
    }
    if (node.children) {
      for (const c of node.children) {
        if (update(c)) return true
      }
    }
    return false
  }
  update(rootTask.value)
  recalcProgress()
}

const { showId, componentId } = useComponentId('RP-002')

function recalcProgress() {
  const flatten = (node: PipelineTaskNode): PipelineTaskNode[] => {
    if (!node.children) return [node]
    return [node, ...node.children.flatMap(flatten)]
  }
  const all = flatten(rootTask.value)
  const leaves = all.filter(n => !n.children || n.children.length === 0)
  const done = leaves.filter(n => n.status === 'completed' || n.status === 'skipped').length
  overallProgress.value = leaves.length > 0 ? Math.round((done / leaves.length) * 100) : 0
  syncStore()
}

function syncStore() {
  const existing = pipelineStore.getTaskState(props.taskId)
  pipelineStore.updateTaskState(props.taskId, {
    rootTask: JSON.parse(JSON.stringify(rootTask.value)),
    running: running.value,
    paused: isPaused.value,
    progress: overallProgress.value,
    stepOutputs: { ...stepOutputs.value },
    communityProgress: existing?.communityProgress,
  })
}

// ===== Step execution =====
async function prepareStepVariables(stepId: string): Promise<Record<string, string>> {
  const base: Record<string, string> = {}
  const pid = projectStore.selectedProjectId
  const stepOutput = stepOutputs.value

  if (stepId === 'step1') {
    try {
      const project = pid ? await window.api.project.get(pid) : null
      const task = await window.api.analysis.getTask(props.taskId)
      if (project) {
        base.projectName = project.name || ''
        base.language = project.language || ''
        base.fileCount = String(project.fileCount || 0)
        base.rootPath = project.rootPath || project.path || ''
      }
      const readme = pid ? await window.api.report.getReadmeContent({ projectId: pid }) : null
      if (readme?.content) base.readmeContent = readme.content
      const deps = pid ? await window.api.report.extractDependencyFiles({ projectId: pid }) : null
      if (deps && deps.count > 0) {
        base.dependencySummary = deps.dependencyFiles.map(
          (d: any) => `${d.file} (${d.type}): ${Object.keys(d.dependencies).slice(0, 8).join(', ')}`
        ).join('\n')
      }
    } catch (e) {
      base.projectName = t('report.pipeline.unknown')
    }
  }

  if (stepId === 'step2') {
    try {
      const pid = props.projectId || projectStore.selectedProjectId
      // 获取 LLM 结果为社区命名
      const [callResults, depResults] = await Promise.all([
        window.api.analysis.listCommunityResults(props.taskId, 'CALL').catch(() => ({ results: [] })),
        window.api.analysis.listCommunityResults(props.taskId, 'INCLUDE').catch(() => ({ results: [] })),
      ])
      const nameMap = new Map<string, string>()
      const statusMap = new Map<string, string>()
      for (const r of [...(callResults?.results || []), ...(depResults?.results || [])]) {
        if (r.name && r.name !== r.comm_id) {
          nameMap.set(r.comm_id, r.name)
          statusMap.set(r.comm_id, 'completed')
        }
      }
      const pid2 = pid
      const l0Detail = pid2 ? await window.api.report.getLevelCommunityDetail({ projectId: pid2, taskId: props.taskId, level: 'L0', edgeType: 'CALL' }) : null
      if (l0Detail && l0Detail.communities.length > 0) {
        const summaryLines = l0Detail.communities.map((c: any) => {
          const displayName = nameMap.get(c.communityId) || c.communityId
          const st = statusMap.get(c.communityId) || 'pending'
          const countLabel = `${c.nodeCount} nodes, ${c.edgeCount} edges`
          const nodeSamples = c.nodes.map((n: any) => n.name).join(', ').slice(0, 200)
          return `- [${st}] ${displayName}: ${countLabel} (${nodeSamples})`
        })
        base.communitySummary = summaryLines.join('\n')
      } else {
        const levels = await window.api.analysis.getCascadeLevels(props.taskId, 'CALL')
        base.communitySummary = JSON.stringify(levels?.levels || [], null, 2)
      }
    } catch (e) {
      base.communitySummary = t('report.pipeline.noData')
    }
  }

  if (stepId === 'step3') {
    try {
      const levels = await window.api.analysis.getCascadeLevels(props.taskId, 'CALL')
      const topComm = levels?.levels?.[0]?.items?.slice(0, 5) || []
      base.topCommunities = JSON.stringify(topComm, null, 2)
      base.count = String(topComm.length)
    } catch (e) {
      base.topCommunities = t('report.pipeline.noData')
      base.count = '0'
    }
  }

  if (stepId === 'step4') {
    try {
      const levels = await window.api.analysis.getCascadeLevels(props.taskId, 'CALL')
      base.crossCommunityEdges = JSON.stringify(levels?.levels?.slice(0, 2) || [], null, 2)
    } catch (e) {
      base.crossCommunityEdges = t('report.pipeline.noData')
    }
  }

  if (stepId === 'step5') {
    base.step1 = stepOutput.step1 || ''
    base.step2 = stepOutput.step2 || ''
    base.step3 = stepOutput.step3 || ''
    base.step4 = stepOutput.step4 || ''
  }

  return base
}

async function runStep(step: PipelineTaskNode) {
  if (step.status === 'completed' || step.status === 'skipped') return
  if (step.children && step.children.length > 0) return

  step.status = 'running'

  const modelId = settingsStore.models.find(m => m.isDefault)?.id
  if (!modelId) {
    step.status = 'error'
    step.error = t('report.llmNotConfigured')
    return
  }

  try {
    const variables = await prepareStepVariables(step.id)
    variables.pipeline_step = step.id  // 用于日志追踪
    const sessionId = `pipeline-${props.taskId}-${step.id}-${Date.now()}`
    const result = await window.api.llm.chat({
      sessionId,
      modelId,
      templateId: step.templateId,
      variables,
      mode: 'chat',
    })

    let fullContent = ''
    await new Promise<void>((resolve, reject) => {
      const unsubscribe = window.api.llm.subscribe(result.requestId, {
        onChunk(data: { text: string }) { fullContent += data.text },
        onDone() {
          step.output = fullContent
          stepOutputs.value[step.id] = fullContent
          step.status = 'completed'
          unsubscribe()
          resolve()
        },
        onError(errData: { message: string }) {
          step.status = 'error'
          step.error = errData.message
          unsubscribe()
          reject(new Error(errData.message))
        },
      })
    })
  } catch (e: any) {
    step.status = 'error'
    step.error = e.message || String(e)
  }
  recalcProgress()
}

async function runAll() {
  running.value = true
  isPaused.value = false
  overallProgress.value = 0
  rootTask.value.status = 'running'

  // Phase 0: Model validation
  updateNodeStatus('validation', 'running')
  const modelId = settingsStore.models.find(m => m.isDefault)?.id
  if (!modelId) {
    updateNodeStatus('validation', 'error', t('report.llmNotConfigured'))
    running.value = false
    rootTask.value.status = 'error'
    return
  }
  updateNodeStatus('validation', 'completed')

  // Phase 1: Project summary (read README, extract deps, generate summary)
  updateNodeStatus('project_summary', 'running')
  const pid = projectStore.selectedProjectId
  if (pid) {
    try {
      await window.api.report.getReadmeContent({ projectId: pid })
      await window.api.report.extractDependencyFiles({ projectId: pid })
      const result = await window.api.report.generateProjectSummary({ projectId: pid })
      updateNodeStatus('project_summary', result?.summary ? 'completed' : 'error')
    } catch (e: any) {
      updateNodeStatus('project_summary', 'error', e.message)
    }
  } else {
    updateNodeStatus('project_summary', 'skipped')
  }
  recalcProgress()

  // Phase 2: Community analysis — mark as offering (user runs via separate UI)
  // We just check the data exists
  updateNodeStatus('community_analysis', 'running')
  try {
    const levels = await window.api.analysis.getCascadeLevels(props.taskId, 'CALL')
    if (levels?.levels?.length) {
      updateNodeStatus('community_analysis', 'completed')
    } else {
      updateNodeStatus('community_analysis', 'skipped', 'No community data')
    }
  } catch (e) {
    updateNodeStatus('community_analysis', 'skipped')
  }
  recalcProgress()

  // Phase 3-7: 5 pipeline steps
  const pipelineSteps = ['step1', 'step2', 'step3', 'step4', 'step5']
  for (const stepId of pipelineSteps) {
    if (isPaused.value) break
    const step = rootTask.value.children?.find(n => n.id === stepId)
    if (!step) continue
    await runStep(step)
  }

  running.value = false
  rootTask.value.status = allCompleted.value ? 'completed' : 'error'
  recalcProgress()

  if (allCompleted.value && stepOutputs.value.step5) {
    emit('generated', stepOutputs.value.step5)
  }
}

function pause() {
  isPaused.value = true
  running.value = false
  syncStore()
}

function resume() {
  isPaused.value = false
  running.value = true
  syncStore()
}

function stop() {
  isPaused.value = true
  running.value = false
  const markSkipped = (node: PipelineTaskNode) => {
    if (node.status === 'running' || node.status === 'queued') node.status = 'skipped'
    if (node.children) node.children.forEach(markSkipped)
  }
  rootTask.value.children?.forEach(markSkipped)
  rootTask.value.status = 'skipped'
  recalcProgress()
}

function reset() {
  const resetNode = (node: PipelineTaskNode) => {
    node.status = 'pending'
    node.progress = 0
    node.error = undefined
    if (node.children) node.children.forEach(resetNode)
  }
  rootTask.value = createInitialTree()
  overallProgress.value = 0
  stepOutputs.value = {}
  syncStore()
}

// 进入任务列表时校验项目摘要是否已存在
async function checkExistingSummary() {
  const pid = props.projectId || projectStore.selectedProjectId
  if (!pid) return
  try {
    const result = await window.api.report.getProjectSummary({ projectId: pid })
    if (result?.summary) {
      const node = rootTask.value.children?.find(n => n.id === 'project_summary')
      if (node && node.status === 'pending') {
        node.status = 'completed'
        recalcProgress()
        syncStore()
      }
    }
  } catch (e) {
    // 摘要不存在，保持 pending 状态
  }
}

async function runNode(nodeId: string) {
  const find = (node: PipelineTaskNode): PipelineTaskNode | undefined => {
    if (node.id === nodeId) return node
    if (node.children) for (const c of node.children) { const r = find(c); if (r) return r }
    return undefined
  }
  const node = find(rootTask.value)
  if (!node) return

  running.value = true
  isPaused.value = false

  if (nodeId === 'validation') {
    const mid = settingsStore.models.find(m => m.isDefault)?.id
    if (!mid) {
      node.status = 'error'
      node.error = t('report.llmNotConfigured')
    } else {
      try {
        node.status = 'running'
        await window.api.settings.testModel(mid)
        node.status = 'completed'
      } catch (e: any) {
        node.status = 'error'
        node.error = e.message || 'Connection failed'
      }
    }
    recalcProgress()
  } else if (nodeId === 'project_summary') {
    const pid = projectStore.selectedProjectId
    if (!pid) { node.status = 'skipped'; recalcProgress(); syncStore(); return }
    try {
      node.status = 'running'
      await window.api.report.getReadmeContent({ projectId: pid })
      await window.api.report.extractDependencyFiles({ projectId: pid })
      const result = await window.api.report.generateProjectSummary({ projectId: pid })
      node.status = result?.summary ? 'completed' : 'error'
      if (!result?.summary) node.error = 'Empty summary'
    } catch (e: any) { node.status = 'error'; node.error = e.message }
    recalcProgress()
  } else if (nodeId === 'community_analysis') {
    node.status = 'running'
    try {
      const levels = await window.api.analysis.getCascadeLevels(props.taskId, 'CALL')
      node.status = (levels?.levels?.length) ? 'completed' : 'skipped'
    } catch { node.status = 'skipped' }
    recalcProgress()
  } else if (['step1','step2','step3','step4','step5'].includes(nodeId)) {
    node.status = 'pending'
    node.error = undefined
    await runStep(node)
  }

  running.value = false
  recalcProgress()
  syncStore()
}

onMounted(() => {
  syncStore()
  pipelineStore.registerControls({ runAll, runNode, pause, resume, reset, stop })
  checkExistingSummary()
})

onUnmounted(() => {
  syncStore()
  pipelineStore.unregisterControls()
})
</script>

<template>
  <div class="report-pipeline">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="pipeline-header">
      <div class="pipeline-title-row">
        <span class="pipeline-title">{{ t('report.generationPipeline') }}</span>
        <span
          v-if="running"
          class="pipeline-badge running"
        >{{ t('common.running') }}</span>
        <span
          v-else-if="allCompleted"
          class="pipeline-badge completed"
        >{{ t('common.completed') }}</span>
      </div>
      <div class="pipeline-progress">
        <div class="progress-bar">
          <div
            class="progress-fill"
            :style="{ width: overallProgress + '%' }"
          />
        </div>
        <span class="progress-text">{{ overallProgress }}%</span>
      </div>
    </div>

    <div class="pipeline-tree">
      <PipelineTaskTree :node="rootTask" />
    </div>

    <!-- Side sub-components: Community Analysis -->
    <div class="pipeline-sub">
      <CommunityAnalysisPipeline
        :task-id="taskId"
        :project-id="projectId"
        @completed="(s: any) => emit('communityResults', s)"
        @view-community-md="(p: any) => emit('viewCommunityMD', p)"
      />
    </div>

    <div class="pipeline-actions">
      <button
        v-if="!running && !allCompleted"
        class="btn btn-primary btn-xs"
        :disabled="rootTask.status === 'running'"
        @click="runAll"
      >
        <SparklesIcon class="w-3 h-3" />
        <span>{{ t('report.pipeline.startAll') }}</span>
      </button>
      <button
        v-if="running"
        class="btn btn-warning btn-xs"
        @click="pause"
      >
        {{ t('report.pipeline.pause') }}
      </button>
      <button
        v-if="allCompleted"
        class="btn btn-secondary btn-xs"
        @click="reset"
      >
        <ArrowPathIcon class="w-3 h-3" />
        <span>{{ t('report.pipeline.reset') }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.report-pipeline {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-secondary);
  overflow: hidden;
}

.pipeline-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; border-bottom: 1px solid var(--border); background: var(--bg-tertiary);
}

.pipeline-title-row { display: flex; align-items: center; gap: 6px; }
.pipeline-title { font-size: 12px; font-weight: 600; color: var(--text-primary); }

.pipeline-badge { font-size: 9px; padding: 1px 5px; border-radius: 6px; text-transform: uppercase; }
.pipeline-badge.running { background: color-mix(in srgb, var(--accent) 15%, transparent); color: var(--accent); }
.pipeline-badge.completed { background: color-mix(in srgb, var(--success) 15%, transparent); color: var(--success); }

.pipeline-progress { display: flex; align-items: center; gap: 6px; }
.progress-bar { width: 100px; height: 6px; background: var(--bg-primary); border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }
.progress-text { font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); min-width: 28px; }

.pipeline-tree { padding: 8px 12px; max-height: 300px; overflow-y: auto; }

.pipeline-sub {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 0 12px 8px;
  max-height: 500px;
  overflow-y: auto;
}

.pipeline-actions {
  padding: 8px 12px; border-top: 1px solid var(--border); display: flex; gap: 6px;
}
</style>
