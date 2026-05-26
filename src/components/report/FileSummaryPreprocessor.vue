<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useProjectStore } from '@/stores/project'
import { useReportStore } from '@/stores/report'
import PipelineTaskTree from './PipelineTaskTree.vue'
import type { PipelineTaskNode } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const projectStore = useProjectStore()
const reportStore = useReportStore()

const props = defineProps<{
  taskId: string
  projectId?: string
}>()

const emit = defineEmits<{
  completed: [summaries: Array<{ filePath: string; summary: string; source: string }>]
  error: [message: string]
}>()

const running = ref(false)
const rootNode = ref<PipelineTaskNode>({
  id: 'preprocess',
  label: t('report.pipeline.preprocessing'),
  type: 'group',
  status: 'pending',
  progress: 0,
  children: [
    { id: 'readme', label: t('report.pipeline.extractReadme'), type: 'subtask', status: 'pending', progress: 0 },
    { id: 'deps', label: t('report.pipeline.extractDeps'), type: 'subtask', status: 'pending', progress: 0 },
  ],
})

const { showId, componentId } = useComponentId('RP-007')

function resolveProjectId(): string {
  return props.projectId || projectStore.selectedProjectId || ''
}

function updateNodeStatus(id: string, status: PipelineTaskNode['status'], error?: string) {
  const update = (node: PipelineTaskNode): boolean => {
    if (node.id === id) {
      node.status = status
      if (error) node.error = error
      return true
    }
    if (node.children) {
      for (const c of node.children) if (update(c)) return true
    }
    return false
  }
  update(rootNode.value)
  updateProgress()
}

function updateProgress() {
  const children = rootNode.value.children || []
  const done = children.filter(c => c.status === 'completed' || c.status === 'skipped').length
  rootNode.value.progress = children.length > 0 ? Math.round((done / children.length) * 100) : 0
  if (done === children.length) {
    rootNode.value.status = children.some(c => c.status === 'error') ? 'error' : 'completed'
  }
}

async function run() {
  running.value = true
  rootNode.value.status = 'running'
  rootNode.value.progress = 0

  const pid = resolveProjectId()
  if (!pid) {
    const msg = t('report.pipeline.noProject')
    emit('error', msg)
    rootNode.value.status = 'error'
    rootNode.value.error = msg
    running.value = false
    return
  }

  // Check if preprocessing results already exist → skip
  updateNodeStatus('readme', 'running')
  updateNodeStatus('deps', 'running')
  try {
    const existing = await reportStore.getFileSummaries({ projectId: pid, taskId: props.taskId })
    if (existing.count > 0) {
      updateNodeStatus('readme', 'completed')
      updateNodeStatus('deps', 'completed')
      running.value = false
      rootNode.value.status = 'completed'
      emit('completed', existing.summaries)
      return
    }
  } catch {
    // if check fails, just proceed
  }

  const summaries: Array<{ filePath: string; summary: string; source: string }> = []

  // Step A: Extract README
  updateNodeStatus('readme', 'running')
  updateNodeStatus('deps', 'pending')
  try {
    const readmeResult = await reportStore.getReadmeContent(pid)
    if (readmeResult.content) {
      summaries.push({ filePath: 'README.md', summary: readmeResult.content, source: 'readme' })
    }
    updateNodeStatus('readme', 'completed')
  } catch (e: any) {
    updateNodeStatus('readme', 'skipped', e.message)
  }
  updateProgress()

  // Step B: Extract dependency files (package.json, Cargo.toml, etc.)
  updateNodeStatus('deps', 'running')
  try {
    const depResult = await reportStore.extractDependencyFiles(pid)
    for (const df of depResult.dependencyFiles) {
      const depSummary = `${df.type} (${df.count} packages)`
      summaries.push({ filePath: df.file, summary: depSummary, source: 'dep_file' })
    }
    updateNodeStatus('deps', 'completed')
  } catch (e: any) {
    updateNodeStatus('deps', 'skipped', e.message)
  }
  updateProgress()

  // Save summaries for project-level info
  if (summaries.length > 0) {
    try {
      await reportStore.saveFileSummaries({ projectId: pid, taskId: props.taskId, summaries })
    } catch (e) {
      console.warn('[FileSummaryPreprocessor] save failed:', e)
    }
  }

  running.value = false
  emit('completed', summaries)
}

function handleRun() { if (!running.value) run() }
</script>

<template>
  <div class="file-summary-preprocessor">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <PipelineTaskTree :node="rootNode" />
    <div
      v-if="rootNode.error && !running"
      class="preproc-error"
    >
      {{ rootNode.error }}
    </div>
    <div
      v-if="!running"
      class="preproc-actions"
    >
      <button
        v-if="rootNode.status === 'pending' || rootNode.status === 'completed' || rootNode.status === 'error'"
        class="btn btn-primary btn-xs"
        @click="handleRun"
      >
        {{ rootNode.status === 'pending' ? t('report.pipeline.startPreprocessing') : t('common.retry') }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.file-summary-preprocessor {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  background: var(--bg-secondary);
}
.preproc-actions { margin-top: 8px; display: flex; gap: 6px; }
.preproc-error { margin-top: 6px; font-size: 10px; color: var(--error); padding: 4px 8px; background: color-mix(in srgb, var(--error) 8%, transparent); border-radius: 4px; }
</style>
