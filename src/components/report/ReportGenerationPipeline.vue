<script setup lang="ts">
import { computed, watch, onMounted } from 'vue'
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
import { useReportStore } from '@/stores/report'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const settingsStore = useSettingsStore()
const projectStore = useProjectStore()
const reportStore = useReportStore()

const props = defineProps<{
  taskId: string
  projectId?: string
}>()

const emit = defineEmits<{
  generated: [content: string]
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
        id: 'overall_architecture',
        label: t('report.pipeline.overallArchitecture'),
        type: 'step',
        status: 'pending',
        progress: 0,
        templateId: 'report_overall_architecture',
        dependsOn: ['project_summary', 'community_analysis'],
      },
    ],
  }
}

const taskState = computed(() => reportStore.tasks[props.taskId])
const rootTask = computed(() => taskState.value?.pipelineRootTask ?? createInitialTree())
const running = computed(() => taskState.value?.pipelineRunning ?? false)
const isPaused = computed(() => taskState.value?.pipelinePaused ?? false)
const overallProgress = computed(() => taskState.value?.pipelineProgress ?? 0)
const errorLogs = computed(() => taskState.value?.errorLogs ?? [])

const allCompleted = computed(() => reportStore.allPipelineStepsCompleted(props.taskId))
const hasError = computed(() => reportStore.hasPipelineError(props.taskId))

const { showId, componentId } = useComponentId('RP-002')

// ===== Step execution =====
async function prepareStepVariables(stepId: string): Promise<Record<string, string>> {
  const base: Record<string, string> = {}
  const pid = projectStore.selectedProjectId

  if (stepId === 'overall_architecture') {
    try {
      // 1. 项目基本信息
      const project = projectStore.selectedProject
      if (project) {
        base.projectName = project.name || ''
        base.language = project.language || ''
        base.fileCount = String(project.fileCount || 0)
        base.rootPath = project.rootPath || project.path || ''
      } else {
        base.projectName = t('report.pipeline.unknown')
      }

      // 2. README + 依赖信息
      const readme = pid ? await reportStore.getReadmeContent(pid) : null
      if (readme?.content) base.readmeContent = readme.content
      const deps = pid ? await reportStore.extractDependencyFiles(pid) : null
      if (deps && deps.count > 0) {
        base.dependencySummary = deps.dependencyFiles.map(
          (d: any) => `${d.file} (${d.type}): ${Object.keys(d.dependencies).slice(0, 8).join(', ')}`
        ).join('\n')
      }

      // 3. 社区命名映射 (合并 CALL + INCLUDE)
      const [callResults, depResults] = await Promise.all([
        reportStore.listCommunityResults(props.taskId, 'CALL').catch(() => ({ results: [] })),
        reportStore.listCommunityResults(props.taskId, 'INCLUDE').catch(() => ({ results: [] })),
      ])
      const nameMap = new Map<string, string>()
      for (const r of [...(callResults?.results || []), ...(depResults?.results || [])]) {
        if (r.name && r.name !== r.comm_id) {
          nameMap.set(r.comm_id, r.name)
        }
      }
      base.communityNameMap = nameMap.size > 0
        ? [...nameMap.entries()].map(([id, name]) => `- ${id} → ${name}`).join('\n')
        : '(无命名结果，将使用原始社区 ID)'

      // 4. L0 CALL 社区详情
      const callDetail = pid ? await reportStore.getLevelCommunityDetail({
        projectId: pid, taskId: props.taskId, level: 'L0', edgeType: 'CALL',
      }) : null
      if (callDetail?.communities?.length) {
        base.callCommunityDetail = callDetail.communities.map((c: any) => {
          const name = nameMap.get(c.communityId) || c.communityId
          const nodes = c.nodes.map((n: any) => `    - ${n.name} (${n.filePath})`).join('\n')
          const edges = c.edges.map((e: any) => `    - ${e.sourceDisplay} → ${e.targetDisplay}`).join('\n')
          return [
            `### ${name} (community: ${c.communityId})`,
            `- 节点数: ${c.nodeCount}, 边数: ${c.edgeCount}`,
            `- 节点列表:\n${nodes}`,
            `- 边列表:\n${edges}`,
          ].join('\n')
        }).join('\n\n')
      } else {
        base.callCommunityDetail = t('report.pipeline.noData')
      }

      // 5. L0 INCLUDE 社区详情
      const includeDetail = pid ? await reportStore.getLevelCommunityDetail({
        projectId: pid, taskId: props.taskId, level: 'L0', edgeType: 'INCLUDE',
      }) : null
      if (includeDetail?.communities?.length) {
        base.includeCommunityDetail = includeDetail.communities.map((c: any) => {
          const name = nameMap.get(c.communityId) || c.communityId
          const nodes = c.nodes.map((n: any) => `    - ${n.name} (${n.filePath})`).join('\n')
          const edges = c.edges.map((e: any) => `    - ${e.sourceDisplay} → ${e.targetDisplay}`).join('\n')
          return [
            `### ${name} (community: ${c.communityId})`,
            `- 节点数: ${c.nodeCount}, 边数: ${c.edgeCount}`,
            `- 节点列表:\n${nodes}`,
            `- 边列表:\n${edges}`,
          ].join('\n')
        }).join('\n\n')
      } else {
        base.includeCommunityDetail = t('report.pipeline.noData')
      }
    } catch (e) {
      base.projectName = t('report.pipeline.unknown')
      base.callCommunityDetail = t('report.pipeline.noData')
      base.includeCommunityDetail = t('report.pipeline.noData')
      base.communityNameMap = t('report.pipeline.noData')
    }
  }

  return base
}

async function runStep(step: PipelineTaskNode) {
  if (!running.value) return
  if (step.children && step.children.length > 0) return

  step.status = 'running'

  const modelId = settingsStore.models.find(m => m.isDefault)?.id
  if (!modelId) {
    step.status = 'error'
    step.error = t('report.llmNotConfigured')
    reportStore.pushError(props.taskId, `${step.label || step.id}: ${t('report.llmNotConfigured')}`)
    return
  }

  try {
    const variables = await prepareStepVariables(step.id)
    variables.pipeline_step = step.id
    const sessionId = `pipeline-${props.taskId}-${step.id}-${Date.now()}`
    const result = await window.api.llm.chat({
      sessionId,
      modelId,
      templateId: step.templateId,
      variables,
      mode: 'chat',
    })

    if (result.status === 'error') {
      step.status = 'error'
      step.error = result.error || 'LLM request failed'
      reportStore.pushError(props.taskId, `${step.label || step.id}: ${step.error}`)
      reportStore.recalcProgress(props.taskId)
      return
    }

    let fullContent = ''
    await new Promise<void>((resolve, reject) => {
      const unsubscribe = window.api.llm.subscribe(result.requestId, {
        onChunk(data: { text: string }) { fullContent += data.text },
        onDone() {
          const trimmed = fullContent.trim()
          const isError = !trimmed || trimmed.length < 20 ||
            /^(error|错误|failed|失败|\[error\]|\[ERROR\])/i.test(trimmed)
          if (isError) {
            step.status = 'error'
            step.error = trimmed || (result as any).error || 'LLM returned empty response'
            reportStore.pushError(props.taskId, `${step.label || step.id}: ${step.error}`)
          } else {
            step.status = 'completed'
            if (step.id === 'overall_architecture') {
              reportStore.setGeneratedReport(props.taskId, fullContent)
            }
          }
          unsubscribe()
          resolve()
        },
        onError(errData: { message: string }) {
          step.status = 'error'
          step.error = errData.message
          reportStore.pushError(props.taskId, `${step.label || step.id}: ${errData.message}`)
          unsubscribe()
          reject(new Error(errData.message))
        },
      })
    })
  } catch (e: any) {
    step.status = 'error'
    const msg = e.message || String(e)
    step.error = msg
    reportStore.pushError(props.taskId, `${step.label || step.id}: ${msg}`)
  }
  reportStore.recalcProgress(props.taskId)
}

async function runAll() {
  if (running.value) return
  if (allCompleted.value) {
    reportStore.initPipeline(props.taskId, createInitialTree())
  }
  reportStore.setPipelineRunning(props.taskId, true)
  reportStore.setPipelinePaused(props.taskId, false)
  const root = reportStore.tasks[props.taskId].pipelineRootTask!
  root.status = 'running'
  reportStore.recalcProgress(props.taskId)

  // Phase 0: Model validation
  reportStore.updateNodeStatus(props.taskId, 'validation', 'running')
  const modelId = settingsStore.models.find(m => m.isDefault)?.id
  if (!modelId) {
    reportStore.updateNodeStatus(props.taskId, 'validation', 'error', t('report.llmNotConfigured'))
    reportStore.setPipelineRunning(props.taskId, false)
    root.status = 'error'
    return
  }
  reportStore.updateNodeStatus(props.taskId, 'validation', 'completed')

  // Phase 1: Project summary
  reportStore.updateNodeStatus(props.taskId, 'project_summary', 'running')
  const pid = projectStore.selectedProjectId
  if (pid) {
    try {
      await reportStore.getReadmeContent(pid)
      await reportStore.extractDependencyFiles(pid)
      const result = await reportStore.generateProjectSummary(pid)
      reportStore.updateNodeStatus(props.taskId, 'project_summary', result?.summary ? 'completed' : 'error')
    } catch (e: any) {
      reportStore.updateNodeStatus(props.taskId, 'project_summary', 'error', e.message)
      reportStore.pushError(props.taskId, `project_summary: ${e.message}`)
    }
  } else {
    reportStore.updateNodeStatus(props.taskId, 'project_summary', 'skipped')
  }

  // Phase 2: Community analysis
  reportStore.updateNodeStatus(props.taskId, 'community_analysis', 'running')
  try {
    const levels = await reportStore.getCascadeLevels(props.taskId, 'CALL')
    if (levels?.levels?.length) {
      reportStore.updateNodeStatus(props.taskId, 'community_analysis', 'completed')
    } else {
      reportStore.updateNodeStatus(props.taskId, 'community_analysis', 'skipped', 'No community data')
    }
  } catch (e) {
    reportStore.updateNodeStatus(props.taskId, 'community_analysis', 'skipped')
  }

  // Phase 3: 整体架构分析（单次 LLM 调用）
  const archStep = root.children?.find(n => n.id === 'overall_architecture')
  if (archStep && !reportStore.tasks[props.taskId]?.pipelinePaused) {
    await runStep(archStep)
  }

  reportStore.setPipelineRunning(props.taskId, false)
  root.status = allCompleted.value ? 'completed' : 'error'
  reportStore.recalcProgress(props.taskId)

  if (allCompleted.value && reportStore.generatedReports[props.taskId]) {
    emit('generated', reportStore.generatedReports[props.taskId])
  }
}

function pause() {
  reportStore.setPipelinePaused(props.taskId, true)
  reportStore.setPipelineRunning(props.taskId, false)
}

function stop() {
  reportStore.stopPipeline(props.taskId)
  const root = reportStore.tasks[props.taskId]?.pipelineRootTask
  if (root) {
    const markSkipped = (node: PipelineTaskNode) => {
      if (node.status === 'running' || node.status === 'queued') node.status = 'skipped'
      if (node.children) node.children.forEach(markSkipped)
    }
    root.children?.forEach(markSkipped)
    root.status = 'skipped'
  }
  reportStore.recalcProgress(props.taskId)
}

function reset() {
  reportStore.resetPipeline(props.taskId)
}

function clearErrorLogs() {
  reportStore.clearErrorLogs(props.taskId)
}

// 进入任务列表时校验项目摘要是否已存在
async function checkExistingSummary() {
  const pid = props.projectId || projectStore.selectedProjectId
  if (!pid) return
  try {
    const result = await reportStore.getProjectSummary(pid)
    if (result?.summary) {
      const node = reportStore.tasks[props.taskId]?.pipelineRootTask?.children?.find(n => n.id === 'project_summary')
      if (node && node.status === 'pending') {
        node.status = 'completed'
        reportStore.recalcProgress(props.taskId)
      }
    }
  } catch (e) {
  }
}

async function runNode(nodeId: string) {
  if (running.value) return
  const root = reportStore.tasks[props.taskId]?.pipelineRootTask
  if (!root) return
  const find = (node: PipelineTaskNode): PipelineTaskNode | undefined => {
    if (node.id === nodeId) return node
    if (node.children) for (const c of node.children) { const r = find(c); if (r) return r }
    return undefined
  }
  const node = find(root)
  if (!node) return

  reportStore.setPipelineRunning(props.taskId, true)
  reportStore.setPipelinePaused(props.taskId, false)

  if (nodeId === 'validation') {
    const mid = settingsStore.models.find(m => m.isDefault)?.id
    if (!mid) {
      node.status = 'error'
      node.error = t('report.llmNotConfigured')
    } else {
      try {
        node.status = 'running'
        await settingsStore.testModel(mid)
        node.status = 'completed'
      } catch (e: any) {
        node.status = 'error'
        node.error = e.message || 'Connection failed'
      }
    }
    reportStore.recalcProgress(props.taskId)
  } else if (nodeId === 'project_summary') {
    const pid = projectStore.selectedProjectId
    if (!pid) { node.status = 'skipped'; reportStore.recalcProgress(props.taskId); return }
    try {
      node.status = 'running'
      await reportStore.getReadmeContent(pid)
      await reportStore.extractDependencyFiles(pid)
      const result = await reportStore.generateProjectSummary(pid)
      node.status = result?.summary ? 'completed' : 'error'
      if (!result?.summary) node.error = 'Empty summary'
    } catch (e: any) { node.status = 'error'; node.error = e.message }
    reportStore.recalcProgress(props.taskId)
  } else if (nodeId === 'community_analysis') {
    node.status = 'running'
    try {
      const levels = await reportStore.getCascadeLevels(props.taskId, 'CALL')
      node.status = (levels?.levels?.length) ? 'completed' : 'skipped'
    } catch { node.status = 'skipped' }
    reportStore.recalcProgress(props.taskId)
  } else if (nodeId === 'overall_architecture') {
    node.status = 'pending'
    node.error = undefined
    await runStep(node)
  }

  reportStore.setPipelineRunning(props.taskId, false)
  reportStore.recalcProgress(props.taskId)
}

watch(() => reportStore.tasks[props.taskId]?.pendingStepRun, (nodeId) => {
  if (nodeId && !running.value) {
    runNode(nodeId)
    reportStore.setPendingStepRun(props.taskId, null)
  }
}, { immediate: true })

onMounted(() => {
  if (!reportStore.tasks[props.taskId]?.pipelineRootTask) {
    reportStore.initPipeline(props.taskId, createInitialTree())
  }
  checkExistingSummary()
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
      <PipelineTaskTree :node="rootTask">
        <template #actions="{ node }">
          <button
            v-if="node.type === 'step' && !running && (node.status === 'pending' || node.status === 'error' || node.status === 'completed')"
            class="btn btn-ghost btn-xs"
            @click.stop="runNode(node.id)"
          >
            {{ node.status === 'completed' ? t('report.pipeline.reRun') : t('report.pipeline.run') }}
          </button>
        </template>
      </PipelineTaskTree>
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
        v-if="!running"
        class="btn btn-primary btn-xs"
        :disabled="rootTask.status === 'running'"
        @click="runAll"
      >
        <SparklesIcon class="w-3 h-3" />
        <span>{{ allCompleted ? t('report.pipeline.reRun') : t('report.pipeline.startAll') }}</span>
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

    <!-- 错误日志 -->
    <div
      v-if="errorLogs.length > 0"
      class="pipeline-error-logs"
    >
      <div class="error-log-header">
        <span class="error-log-title">错误日志</span>
        <button
          class="btn btn-ghost btn-xs"
          @click="clearErrorLogs"
        >
          清除
        </button>
      </div>
      <div class="error-log-list">
        <div
          v-for="(msg, i) in errorLogs"
          :key="i"
          class="error-log-item"
        >{{ msg }}</div>
      </div>
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

.pipeline-error-logs {
  border-top: 1px solid var(--border);
  background: var(--bg-primary);
  max-height: 200px;
  overflow-y: auto;
}
.error-log-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 4px 12px; font-size: 10px; color: var(--text-muted);
  background: var(--bg-tertiary);
}
.error-log-title { font-weight: 600; }
.error-log-list { padding: 4px 0; }
.error-log-item {
  padding: 3px 12px;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--error);
  line-height: 1.4;
  word-break: break-all;
  border-bottom: 1px solid var(--border);
}
.error-log-item:last-child { border-bottom: none; }
</style>
