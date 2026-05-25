<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useProjectStore } from '@/stores/project'
import { useSettingsStore } from '@/stores/settings'
import {
  PlayIcon,
  PauseIcon,
  ArrowPathIcon,
  CheckCircleIcon,
  XCircleIcon,
  ClockIcon,
  FunnelIcon,
} from '@heroicons/vue/24/outline'
import { usePipelineStore } from '@/stores/pipeline'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const projectStore = useProjectStore()
const settingsStore = useSettingsStore()
const pipelineStore = usePipelineStore()

const props = defineProps<{ taskId: string; projectId?: string }>()
const emit = defineEmits<{
  completed: [summaries: Array<{ communityId: string; level: string; edgeType: string; name: string; summary: string; mermaid?: string; plantuml?: string }>]
  error: [message: string]
  viewCommunityMD: [params: { communityId: string; name: string; summary: string; mermaid?: string; plantuml?: string }]
}>()

interface CommunitySummary {
  id: string
  communityId: string
  level: string
  edgeType: string
  nodeCount: number
  edgeCount: number
  qualityScore: number | null
  status: 'pending' | 'queued' | 'running' | 'completed' | 'error'
  name?: string
  summary?: string
  mermaid?: string
  plantuml?: string
  error?: string
  selected: boolean
  parentId?: string
  parentName?: string
}

const modelId = computed(() => settingsStore.models.find(m => m.isDefault)?.id)
const pid = computed(() => props.projectId || projectStore.selectedProjectId)

// 边缘类型配置
const edgeTypeOptions = [
  { type: 'INCLUDE', label: t('report.pipeline.edgeInclude') },
  { type: 'CALL', label: t('report.pipeline.edgeCall') },
] as const
const selectedEdgeType = ref('INCLUDE')
const selectedLevel = ref('L0')

// 层级可用性（该边缘类型有哪些层级）
interface LevelInfo {
  lv: string
  count: number
  analyzed: number
}
const availableLevels = ref<LevelInfo[]>([])
const allCommunities = ref<CommunitySummary[]>([])  // 缓存所有已加载的社区
const llmResults = ref<Map<string, any>>(new Map())  // comm_id → { name, summary }

const loading = ref(true)
const running = ref(false)
const paused = ref(false)
const batchSize = ref(3)
const loadError = ref<string | null>(null)
const runError = ref<string | null>(null)

const searchQuery = ref('')
const currentPage = ref(1)
const pageSize = 100

// 项目上下文（项目概要），在 loadAll 中加载一次
const projectContext = ref('')

const searchedCommunities = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  if (!q) return displayCommunities.value
  return displayCommunities.value.filter(c => {
    const id = fmtCommId(c.communityId).toLowerCase()
    const name = (c.name || '').toLowerCase()
    const pName = (c.parentName || '').toLowerCase()
    return id.includes(q) || name.includes(q) || pName.includes(q)
  })
})

const totalPages = computed(() => Math.max(1, Math.ceil(searchedCommunities.value.length / pageSize)))
const pagedCommunities = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return searchedCommunities.value.slice(start, start + pageSize)
})

watch(searchQuery, () => { currentPage.value = 1 })

const analyzedCommIds = computed(() => {
  const ids = new Set<string>()
  for (const [k, v] of llmResults.value) {
    if (v.name) ids.add(k)
  }
  return ids
})

// 排序状态
interface SortRule { field: string; desc: boolean }
const sortHistory = ref<SortRule[]>([])

// 加载项目概要（从库中读取，非 LLM 原始内容）
async function loadProjectContext() {
  const projectId = pid.value
  console.log('[CAP] loadProjectContext: projectId=', projectId, 'props.projectId=', props.projectId, 'store.selectedProjectId=', projectStore.selectedProjectId)
  if (!projectId) {
    console.warn('[CAP] loadProjectContext: pid is empty, skipping')
    return
  }
  try {
    const result = await window.api.report.getProjectSummary({ projectId })
    console.log('[CAP] loadProjectContext: result.summary_exists=', !!result?.summary, 'summary_len=', result?.summary?.length)
    if (result?.summary) {
      projectContext.value = `## 项目概要\n${result.summary}`
      console.log('[CAP] loadProjectContext: summary loaded, len=', result.summary.length)
    } else {
      projectContext.value = ''
      console.warn('[CAP] loadProjectContext: summary is empty in DB')
    }
  } catch (e) {
    console.warn('[CAP] loadProjectContext failed:', e)
  }
}

function hasAnalysis(commId: string): boolean {
  return analyzedCommIds.value.has(commId)
}

function lookupName(commId: string): string | undefined {
  return llmResults.value.get(commId)?.name || llmResults.value.get(commId)?.nameManual
}

const selectedCount = computed(() => searchedCommunities.value.filter(t => t.selected).length)
const completedCount = computed(() => allCommunities.value.filter(t => t.status === 'completed').length)
const errorCount = computed(() => allCommunities.value.filter(t => t.status === 'error').length)
const totalCount = computed(() => allCommunities.value.length)
const overallProgress = computed(() => {
  const done = completedCount.value + errorCount.value
  return totalCount.value > 0 ? Math.round((done / totalCount.value) * 100) : 0
})

// 当前显示的组件（含排序 + L1/L2 过滤）
const displayCommunities = computed(() => {
  let list = allCommunities.value.filter(c => c.edgeType === selectedEdgeType.value && c.level === selectedLevel.value)
  // L1: 只显示父 L0 有分析结果的; L2: 只显示父 L1 有分析结果的
  if (selectedLevel.value === 'L1') {
    list = list.filter(c => hasAnalysis(c.parentId || ''))
  } else if (selectedLevel.value === 'L2') {
    list = list.filter(c => hasAnalysis(c.parentId || ''))
  }
  // 更新 parentName
  for (const c of list) {
    if (c.parentId) c.parentName = lookupName(c.parentId)
  }
  // 排序
  if (sortHistory.value.length > 0) {
    list = [...list].sort((a, b) => {
      for (const rule of sortHistory.value) {
        const va = String(a[rule.field as keyof CommunitySummary] ?? '')
        const vb = String(b[rule.field as keyof CommunitySummary] ?? '')
        const na = parseFloat(va)
        const nb = parseFloat(vb)
        const cmp = !isNaN(na) && !isNaN(nb) ? na - nb : va.localeCompare(vb)
        if (cmp !== 0) return rule.desc ? -cmp : cmp
      }
      return 0
    })
  }
  return list
})

const { showId, componentId } = useComponentId('RP-008')

function sortBy(field: string) {
  const idx = sortHistory.value.findIndex(s => s.field === field)
  if (idx >= 0) {
    const existing = sortHistory.value[idx]
    // 如果已经在最高优先级，翻转排序方向
    if (idx === 0) {
      existing.desc = !existing.desc
    } else {
      // 移到最高优先级，保持原有方向
      sortHistory.value.splice(idx, 1)
      sortHistory.value.unshift(existing)
    }
  } else {
    sortHistory.value.unshift({ field, desc: true })
  }
}

function sortIcon(field: string): string {
  const s = sortHistory.value.find(r => r.field === field)
  if (!s) return ''
  const idx = sortHistory.value.indexOf(s)
  return s.desc ? `▼${idx + 1}` : `▲${idx + 1}`
}

/** 截短 communityId：去掉 comm-{hash}- 前缀 */
function fmtCommId(id: string): string {
  return id.replace(/^comm-[^-]+-/, '')
}

// 当边缘类型或层级变化时，刷新显示
watch([selectedEdgeType, selectedLevel], () => {
  refreshDisplay()
})

async function loadAll() {
  loading.value = true
  loadError.value = null
  try {
    const [callLevels, depLevels, callResults, depResults] = await Promise.all([
      window.api.analysis.getCascadeLevels(props.taskId, 'CALL')
        .catch((e: any) => { console.warn('[CAP] getCascadeLevels CALL failed:', e); return null }),
      window.api.analysis.getCascadeLevels(props.taskId, 'INCLUDE')
        .catch((e: any) => { console.warn('[CAP] getCascadeLevels INCLUDE failed:', e); return null }),
      window.api.analysis.listCommunityResults(props.taskId, 'CALL')
        .catch((e: any) => { console.warn('[CAP] listCommunityResults CALL failed:', e); return { results: [] } }),
      window.api.analysis.listCommunityResults(props.taskId, 'INCLUDE')
        .catch((e: any) => { console.warn('[CAP] listCommunityResults INCLUDE failed:', e); return { results: [] } }),
    ])

    // 加载项目上下文（README + 依赖摘要）
    loadProjectContext()

    // 合并 LLM 结果到 map (后端返回 snake_case)
    for (const r of [...(callResults?.results || []), ...(depResults?.results || [])]) {
      llmResults.value.set(r.comm_id, r)
    }

    // 处理 CALL 层级
    if (callLevels?.levels) {
      for (const lv of callLevels.levels) {
        if (!lv.items) continue
        for (const item of lv.items) {
          const comm: CommunitySummary = {
            id: `CALL-${item.id}`,
            communityId: item.id,
            level: lv.lv,
            edgeType: 'CALL',
            nodeCount: item.nodeCount || 0,
            edgeCount: item.edgeCount || 0,
            qualityScore: item.qualityScore ?? null,
            status: 'pending',
            selected: false,
            parentId: item.parentCommId ?? undefined,
          }
          // 如果已有持久化结果且 name 是真正的 AI 名称（不是 communityId fallback），恢复状态
          const saved = llmResults.value.get(item.id)
          if (saved && saved.name && saved.name !== item.id) {
            comm.name = saved.name
            comm.summary = saved.summary || undefined
            comm.status = 'completed'
          }
          allCommunities.value.push(comm)
        }
      }
    }

    // 处理 INCLUDE 层级
    if (depLevels?.levels) {
      for (const lv of depLevels.levels) {
        if (!lv.items) continue
        for (const item of lv.items) {
          const comm: CommunitySummary = {
            id: `INCLUDE-${item.id}`,
            communityId: item.id,
            level: lv.lv,
            edgeType: 'INCLUDE',
            nodeCount: item.nodeCount || 0,
            edgeCount: item.edgeCount || 0,
            qualityScore: item.qualityScore ?? null,
            status: 'pending',
            selected: false,
            parentId: item.parentCommId ?? undefined,
          }
          const saved = llmResults.value.get(item.id)
          if (saved && saved.name && saved.name !== item.id) {
            comm.name = saved.name
            comm.summary = saved.summary || undefined
            comm.status = 'completed'
          }
          allCommunities.value.push(comm)
        }
      }
    }

    // 更新层级可用性
    updateAvailableLevels()
    // 初始显示：INCLUDE + L0
    selectedEdgeType.value = 'INCLUDE'
    selectedLevel.value = 'L0'
    if (allCommunities.value.length === 0) {
      console.log('[CAP] no communities loaded — community_hierarchy may be empty for this task')
      loadError.value = t('report.pipeline.noCommunityData')
    }
  } catch (e: any) {
    console.error('[CommunityAnalysisPipeline] load error:', e)
    loadError.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

function updateAvailableLevels() {
  const edge = selectedEdgeType.value
  const lvSet = new Set<string>()
  for (const c of allCommunities.value) {
    if (c.edgeType === edge) lvSet.add(c.level)
  }
  availableLevels.value = ['L0', 'L1', 'L2']
    .filter(lv => lvSet.has(lv))
    .map(lv => {
      const items = allCommunities.value.filter(c => c.edgeType === edge && c.level === lv)
      return {
        lv,
        count: items.length,
        analyzed: items.filter(c => c.status === 'completed').length,
      }
    })
  // 如果当前层级不可用，切到第一个可用层级
  if (!lvSet.has(selectedLevel.value) && availableLevels.value.length > 0) {
    selectedLevel.value = availableLevels.value[0].lv
  }
}

function refreshDisplay() {
  updateAvailableLevels()
}

function switchEdgeType(type: string) {
  if (type === selectedEdgeType.value) return
  selectedEdgeType.value = type
  updateAvailableLevels()
  // 重置为首个可用层级
  if (availableLevels.value.length > 0) {
    selectedLevel.value = availableLevels.value[0].lv
  }
}

function toggleSelect(id: string) {
  const task = allCommunities.value.find(t => t.id === id)
  if (task) task.selected = !task.selected
}

function selectAllInCurrentView(sel: boolean) {
  for (const t of searchedCommunities.value) {
    t.selected = sel
  }
}

function selectAllCompletedErrors() {
  for (const t of allCommunities.value) {
    if (t.status === 'error') {
      t.status = 'pending'
      t.error = undefined
      t.selected = true
    }
  }
}

function statusBadgeClass(status: string): string {
  switch (status) {
    case 'completed': return 'badge-success'
    case 'running': case 'queued': return 'badge-info'
    case 'error': return 'badge-error'
    default: return 'badge-muted'
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case 'completed': return t('common.completed')
    case 'running': return t('common.running')
    case 'queued': return t('common.queued')
    case 'error': return t('common.error')
    default: return t('common.pending')
  }
}

async function runTask(task: CommunitySummary): Promise<boolean> {
  // 清除旧结果，支持重复执行
  task.name = undefined
  task.summary = undefined
  task.error = undefined
  task.status = 'running'

  try {
    if (!pid.value) {
      console.warn('[CAP] pid is empty, cannot get level detail')
      task.status = 'skipped'
      return false
    }
    const result = await window.api.report.getLevelCommunityDetail({
      projectId: pid.value,
      taskId: props.taskId,
      level: task.level,
      edgeType: task.edgeType,
    })
    const commList = result?.communities
    if (!Array.isArray(commList) || commList.length === 0) {
      console.warn('[CAP] getLevelCommunityDetail returned no communities for level=', task.level, 'edgeType=', task.edgeType, 'result=', result)
      task.status = 'skipped'
      return false
    }
    const community = commList.find(c => c.communityId === task.communityId)
    if (!community) {
      console.warn('[CAP] community id mismatch; looking for', task.communityId, 'available ids:', commList.map(c => c.communityId))
      task.status = 'skipped'
      return false
    }

    const nodeListText = community.nodes.map((n: any) => {
      const ext = n.filePath && n.filePath !== '?' ? n.filePath.split('.').pop() : ''
      const label = ext ? `${n.name}.${ext}` : n.name
      return `- ${label}  (${n.filePath})`
    }).slice(0, 100).join('\n')
    const edgeListText = community.edges.map((e: any) => {
      const src = e.sourceDisplay || e.source
      const tgt = e.targetDisplay || e.target
      return `- ${src} → ${tgt}`
    }).slice(0, 100).join('\n')

    const sessionId = `comm-${props.taskId}-${task.communityId}-${Date.now()}`
    const chatResult = await window.api.llm.chat({
      sessionId,
      modelId: modelId.value!,
      templateId: 'community_analyze',
      variables: {
        communityId: task.communityId,
        level: task.level,
        nodeCount: String(community.nodeCount),
        edgeCount: String(community.edgeCount),
        nodeListWithPaths: nodeListText,
        edgeListWithDetails: edgeListText,
        parentSummaries: projectContext.value,
        source: 'community_analysis',
        community_id: task.communityId,
        community_level: task.level,
        edge_type: task.edgeType,
        batch_id: `batch-${Date.now()}`,
      },
      mode: 'structured',
      outputSchema: {
        type: 'object',
        properties: {
          name: { type: 'string', maxLength: 20 },
          summary: { type: 'string' },
          mermaid: { type: 'string' },
          plantuml: { type: 'string' },
        },
        required: ['name', 'summary', 'mermaid'],
      },
    })

    let fullContent = ''
    await new Promise<void>((resolve, reject) => {
      const unsubscribe = window.api.llm.subscribe(chatResult.requestId, {
        onChunk(data: { text: string }) { fullContent += data.text },
        onDone(data: { content: string; structured?: Record<string, any> }) {
          if (data.structured) {
            task.name = data.structured.name?.slice(0, 20) || task.communityId
            task.summary = data.structured.summary || ''
            task.mermaid = data.structured.mermaid || ''
            task.plantuml = data.structured.plantuml || ''
          } else {
            task.name = task.communityId
            task.summary = fullContent
          }
          task.status = 'completed'
          unsubscribe()
          resolve()
        },
        onError(errData: { message: string }) {
          task.status = 'error'
          task.error = errData.message
          unsubscribe()
          reject(new Error(errData.message))
        },
      })
    })
    return true
  } catch (e: any) {
    task.status = 'error'
    task.error = e.message || String(e)
    return false
  }
}

async function analyzeSelected() {
  runError.value = null
  if (!modelId.value) {
    runError.value = t('report.llmNotConfigured')
    emit('error', t('report.llmNotConfigured'))
    return
  }
  const selected = allCommunities.value.filter(t => t.selected)
  if (selected.length === 0) return
  if (running.value) return

  running.value = true
  paused.value = false

  for (let i = 0; i < selected.length; i += batchSize.value) {
    if (paused.value) break
    const batch = selected.slice(i, i + batchSize.value)
    batch.forEach(t => { t.status = 'queued' })
    const results = await Promise.allSettled(batch.map(t => runTask(t)))
    for (let idx = 0; idx < batch.length; idx++) {
      const t = batch[idx]
      const r = results[idx]
      if (r.status === 'rejected') {
        t.status = 'error'
        t.error = r.reason?.message || String(r.reason)
      }
      // 只持久化成功的结果，避免失败 tasks 以 communityId 为 name 误判为已完成
      if (t.status === 'completed') {
        try {
          await window.api.analysis.saveCommunityResult({
            taskId: props.taskId,
            edgeType: t.edgeType,
            commLv: t.level,
            commId: t.communityId,
            name: t.name || t.communityId,
            summary: t.summary || '',
            mermaid: t.mermaid || '',
            plantuml: t.plantuml || '',
            modelId: modelId.value,
            templateId: 'community_analyze',
          })
        } catch (e) {
          console.warn('[CommunityAnalysisPipeline] save failed:', e)
        }
      }
    }
    saveState()
    syncProgress()
  }

  running.value = false
  emit('completed', allCommunities.value
    .filter(t => t.status === 'completed' && t.name)
    .map(t => ({ communityId: t.communityId, level: t.level, edgeType: t.edgeType, name: t.name!, summary: t.summary!, mermaid: t.mermaid, plantuml: t.plantuml })))
}

function pauseResume() {
  paused.value = !paused.value
}

async function retryTask(id: string) {
  const task = allCommunities.value.find(t => t.id === id)
  if (!task) return
  task.status = 'pending'
  task.error = undefined
  task.selected = false
  if (!modelId.value) {
    emit('error', t('report.llmNotConfigured'))
    return
  }
  task.status = 'running'
  try {
    await runTask(task)
    if (task.status === 'completed') {
      await window.api.analysis.saveCommunityResult({
        taskId: props.taskId,
        edgeType: task.edgeType,
        commLv: task.level,
        commId: task.communityId,
        name: task.name || task.communityId,
        summary: task.summary || '',
        mermaid: task.mermaid || '',
        plantuml: task.plantuml || '',
        modelId: modelId.value,
        templateId: 'community_analyze',
      })
      emit('completed', [{
        communityId: task.communityId,
        level: task.level,
        edgeType: task.edgeType,
        name: task.name || task.communityId,
        summary: task.summary || '',
        mermaid: task.mermaid || '',
        plantuml: task.plantuml || '',
      }])
    }
  } catch (e: any) {
    task.status = 'error'
    task.error = e.message || String(e)
  }
  saveState()
  syncProgress()
}

function syncProgress() {
  const calc = (edgeType: 'INCLUDE' | 'CALL') => {
    const items = allCommunities.value.filter(c => c.edgeType === edgeType && c.level === 'L0')
    return {
      total: items.length,
      completed: items.filter(c => c.status === 'completed').length,
      running: items.filter(c => c.status === 'running' || c.status === 'queued').length,
    }
  }
  pipelineStore.updateCommunityProgress(props.taskId, 'INCLUDE', calc('INCLUDE'))
  pipelineStore.updateCommunityProgress(props.taskId, 'CALL', calc('CALL'))
}

const CAP_STATE_KEY = 'cap_communities'

function saveState() {
  const state = pipelineStore.getTaskState(props.taskId)
  if (!state) return
  const snapshot = allCommunities.value.map(c => ({
    id: c.id, communityId: c.communityId, level: c.level, edgeType: c.edgeType,
    nodeCount: c.nodeCount, edgeCount: c.edgeCount, qualityScore: c.qualityScore,
    status: c.status, selected: c.selected, parentId: c.parentId,
    name: c.name, summary: c.summary, error: c.error, mermaid: c.mermaid, plantuml: c.plantuml,
  }))
  state.stepOutputs[CAP_STATE_KEY] = JSON.stringify(snapshot)
  state.communityProgress = {
    INCLUDE: { total: 0, completed: 0, running: 0 },
    CALL: { total: 0, completed: 0, running: 0 },
  }
  syncProgress()
}

function restoreState() {
  const state = pipelineStore.getTaskState(props.taskId)
  if (!state?.stepOutputs?.[CAP_STATE_KEY]) return false
  try {
    const snapshot = JSON.parse(state.stepOutputs[CAP_STATE_KEY]) as CommunitySummary[]
    if (!Array.isArray(snapshot) || snapshot.length === 0) return false
    allCommunities.value = snapshot
    return true
  } catch { return false }
}

function afterLoadMergePending() {
  const state = pipelineStore.getTaskState(props.taskId)
  if (!state?.stepOutputs?.[CAP_STATE_KEY]) return
  try {
    const saved = JSON.parse(state.stepOutputs[CAP_STATE_KEY]) as CommunitySummary[]
    if (!Array.isArray(saved)) return
    const pendingMap = new Map(saved.filter(c => c.status === 'running' || c.status === 'queued').map(c => [c.communityId, c.status]))
    for (const c of allCommunities.value) {
      const s = pendingMap.get(c.communityId)
      if (s && c.status === 'pending') c.status = s
    }
  } catch {}
}

onMounted(async () => {
  pipelineStore.ensureTaskState(props.taskId, {
    id: 'root', label: '报告生成流水线', type: 'group', status: 'pending', progress: 0, children: [],
  } as PipelineTaskNode)
  await loadAll()
  afterLoadMergePending()
  syncProgress()
})

onUnmounted(() => {
  saveState()
  syncProgress()
})
</script>

<template>
  <div class="community-analysis-pipeline">
    <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <!-- Header -->
    <div class="cap-header">
      <div class="cap-title-row">
        <FunnelIcon class="w-3.5 h-3.5 icon-funnel" />
        <span class="cap-title">{{ t('report.pipeline.communityAnalysis') }}</span>
        <span class="cap-stats">{{ completedCount }}/{{ totalCount }}</span>
      </div>
      <div class="cap-progress">
        <div class="progress-bar"><div class="progress-fill" :style="{ width: overallProgress + '%' }"></div></div>
        <span class="progress-text">{{ overallProgress }}%</span>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="cap-loading">{{ t('common.loading') }}...</div>

    <!-- Error -->
    <div v-else-if="loadError" class="cap-error">{{ loadError }}</div>

    <template v-else>
      <!-- 边缘类型切换 -->
      <div class="et-tabs">
        <button
          v-for="et in edgeTypeOptions"
          :key="et.type"
          :class="['et-tab', { active: selectedEdgeType === et.type }]"
          @click="switchEdgeType(et.type)"
        >
          {{ et.label }}
        </button>
      </div>

      <!-- 层级选择（固定 L0） -->
      <div class="lv-selector">
        <span class="lv-label">{{ t('report.pipeline.granularity') }}:</span>
        <div class="lv-radio-group">
          <label class="lv-radio active">
            <span class="lv-text">L0</span>
          </label>
        </div>
      </div>

      <!-- 组件搜索 -->
      <div class="clist-search">
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索组件名称/ID..."
          class="search-input"
        />
      </div>

      <!-- 组件列表 -->
      <div class="cap-tasklist">
        <div v-if="searchedCommunities.length === 0" class="cap-empty">
          {{ t('report.pipeline.noCommunities') }}
        </div>

        <template v-else>
          <div class="clist-header">
            <span class="clist-title">
              {{ selectedLevel }} ({{ searchedCommunities.length }})
              <span class="clist-edge-tag">{{ selectedEdgeType }}</span>
            </span>
            <div class="clist-actions">
              <button class="btn btn-ghost btn-xs" @click="selectAllInCurrentView(true)">{{ t('common.selectAll') }}</button>
              <button class="btn btn-ghost btn-xs" @click="selectAllInCurrentView(false)">{{ t('common.deselectAll') }}</button>
            </div>
          </div>

          <div class="clist-table">
            <!-- 表头 -->
            <div class="clist-row clist-th">
              <span class="clist-check"></span>
              <span class="clist-id sortable" @click="sortBy('name')">
                {{ t('report.pipeline.communityId') }}
                <span class="sort-icon">{{ sortIcon('name') }}</span>
              </span>
              <span class="clist-nodes sortable" @click="sortBy('nodeCount')">
                {{ t('report.pipeline.nodes') }}
                <span class="sort-icon">{{ sortIcon('nodeCount') }}</span>
              </span>
              <span class="clist-edges sortable" @click="sortBy('edgeCount')">
                {{ t('report.pipeline.edges') }}
                <span class="sort-icon">{{ sortIcon('edgeCount') }}</span>
              </span>
              <span class="clist-score sortable" @click="sortBy('qualityScore')">
                {{ t('report.pipeline.quality') }}
                <span class="sort-icon">{{ sortIcon('qualityScore') }}</span>
              </span>
              <span class="clist-parent sortable" @click="sortBy('parentName')">
                {{ t('report.pipeline.parentComm') }}
                <span class="sort-icon">{{ sortIcon('parentName') }}</span>
              </span>
              <span class="clist-status sortable" @click="sortBy('status')">
                {{ t('common.status') }}
                <span class="sort-icon">{{ sortIcon('status') }}</span>
              </span>
              <span class="clist-actions-col"></span>
            </div>

            <!-- 行 -->
            <div
              v-for="task in pagedCommunities"
              :key="task.id"
              :class="['clist-row', `clist-${task.status}`]"
              @click="toggleSelect(task.id)"
            >
              <span class="clist-check" @click.stop="toggleSelect(task.id)">
                <input type="checkbox" :checked="task.selected" class="clist-cb" />
              </span>
              <span class="clist-id" :title="task.communityId">
                <span class="id-text">{{ fmtCommId(task.communityId) }}</span>
                <span
                  v-if="task.name && task.status === 'completed'"
                  class="id-name clickable"
                  @click.stop="emit('viewCommunityMD', { communityId: task.communityId, name: task.name, summary: task.summary || '', mermaid: task.mermaid, plantuml: task.plantuml })"
                >{{ task.name }}</span>
                <span v-else-if="task.name" class="id-name">{{ task.name }}</span>
              </span>
              <span class="clist-nodes">{{ task.nodeCount }}</span>
              <span class="clist-edges">{{ task.edgeCount }}</span>
              <span class="clist-score">
                <span v-if="task.qualityScore != null" class="score-val">{{ task.qualityScore.toFixed(3) }}</span>
                <span v-else class="score-na">—</span>
              </span>
              <span class="clist-parent" :title="task.parentName || task.parentId">
                <span v-if="task.parentName" class="parent-name">{{ task.parentName }}</span>
                <span v-else-if="task.parentId" class="parent-id">{{ task.parentId.length > 12 ? task.parentId.slice(0,12)+'…' : task.parentId }}</span>
                <span v-else class="parent-na">—</span>
              </span>
              <span class="clist-status">
                <span :class="['badge', statusBadgeClass(task.status)]">{{ statusLabel(task.status) }}</span>
              </span>
              <span class="clist-actions-col" @click.stop>
                <button
                  v-if="task.status === 'error'"
                  class="btn btn-ghost btn-xs"
                  @click="retryTask(task.id)"
                  :title="t('common.retry')"
                >
                  <ArrowPathIcon class="w-3 h-3" />
                </button>
              </span>
            </div>
          </div>

          <!-- 分页 -->
          <div v-if="totalPages > 1" class="clist-pagination">
            <button class="btn btn-ghost btn-xs" :disabled="currentPage <= 1" @click="currentPage--">
              上一页
            </button>
            <span class="page-info">{{ currentPage }} / {{ totalPages }}</span>
            <button class="btn btn-ghost btn-xs" :disabled="currentPage >= totalPages" @click="currentPage++">
              下一页
            </button>
          </div>
        </template>
      </div>

      <!-- 错误提示 -->
      <div v-if="runError" class="cap-run-error">{{ runError }}</div>

      <!-- 组件批操作 -->
      <div class="cap-bottom">
        <div class="cap-batch">
          <span class="batch-label">{{ t('report.pipeline.batchSize') }}:</span>
          <select v-model.number="batchSize" class="batch-select" :disabled="running">
            <option v-for="n in [1,2,3,5,10]" :key="n" :value="n">{{ n }}</option>
          </select>
        </div>
        <div class="cap-bottom-actions">
          <button
            class="btn btn-primary btn-sm"
            @click="analyzeSelected"
            :disabled="selectedCount === 0 || running"
          >
            <PlayIcon class="w-3 h-3" />
            {{ t('report.pipeline.analyzeSelected', { n: selectedCount }) }}
          </button>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.community-analysis-pipeline {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-secondary);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  font-size: 12px;
}

/* Header */
.cap-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; border-bottom: 1px solid var(--border); background: var(--bg-tertiary);
}
.cap-title-row { display: flex; align-items: center; gap: 6px; }
.icon-funnel { color: var(--text-muted); }
.cap-title { font-weight: 600; color: var(--text-primary); }
.cap-stats { font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); }
.cap-progress { display: flex; align-items: center; gap: 6px; }
.progress-bar { width: 80px; height: 5px; background: var(--bg-primary); border-radius: 3px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }
.progress-text { font-size: 9px; color: var(--text-muted); font-family: var(--font-mono); min-width: 24px; }
.cap-loading { padding: 20px; text-align: center; color: var(--text-muted); }
.cap-error { padding: 20px; text-align: center; color: var(--error); font-size: 11px; }
.cap-run-error { padding: 6px 12px; background: color-mix(in srgb, var(--error) 10%, transparent); color: var(--error); font-size: 11px; border-bottom: 1px solid var(--border); }

/* Edge type tabs */
.et-tabs {
  display: flex; border-bottom: 1px solid var(--border); padding: 0 12px; gap: 0;
}
.et-tab {
  flex: 1; padding: 6px 12px; text-align: center; font-size: 11px; font-weight: 500;
  color: var(--text-muted); background: transparent; border: none; cursor: pointer;
  border-bottom: 2px solid transparent; transition: all 0.15s;
}
.et-tab:hover { color: var(--text-primary); background: var(--bg-tertiary); }
.et-tab.active { color: var(--accent); border-bottom-color: var(--accent); }

/* Level selector */
.lv-selector {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 12px; border-bottom: 1px solid var(--border); background: var(--bg-tertiary);
}
.lv-label { font-size: 10px; color: var(--text-muted); white-space: nowrap; }
.lv-radio-group { display: flex; gap: 4px; }
.lv-radio {
  display: flex; align-items: center; gap: 4px;
  padding: 2px 8px; border-radius: 4px; cursor: pointer;
  border: 1px solid var(--border); background: var(--bg-primary);
  transition: all 0.15s;
}
.lv-radio:hover { border-color: var(--accent); }
.lv-radio.active { border-color: var(--accent); background: color-mix(in srgb, var(--accent) 10%, transparent); }
.lv-radio input { display: none; }
.lv-text { font-size: 11px; font-weight: 600; color: var(--text-primary); }
.lv-count { font-size: 9px; color: var(--text-muted); font-family: var(--font-mono); }
.lv-empty { font-size: 10px; color: var(--text-muted); font-style: italic; }

/* Community list */
.cap-tasklist { flex: 1; overflow-y: auto; max-height: 360px; }
.cap-empty { padding: 20px; text-align: center; color: var(--text-muted); font-size: 11px; }

.clist-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 6px 12px; border-bottom: 1px solid var(--border);
}
.clist-title { font-size: 11px; font-weight: 600; color: var(--text-secondary); display: flex; align-items: center; gap: 6px; }
.clist-edge-tag { font-size: 8px; padding: 0 4px; border-radius: 3px; background: var(--bg-tertiary); color: var(--text-muted); }

.clist-table { display: flex; flex-direction: column; gap: 1px; padding: 0 12px 4px; }

.clist-row {
  display: grid;
  grid-template-columns: 24px 1fr 48px 48px 52px 1fr 60px 28px;
  align-items: center;
  padding: 3px 4px;
  border-radius: 4px;
  cursor: pointer;
  gap: 4px;
  font-size: 10px;
  transition: background 0.1s;
}
.clist-row:hover { background: var(--bg-tertiary); }
.clist-th {
  font-weight: 600; color: var(--text-muted); font-size: 9px; cursor: default;
  padding: 4px; border-bottom: 1px solid var(--border); margin-bottom: 2px;
}
.clist-th:hover { background: transparent; }

.clist-check { display: flex; align-items: center; }
.clist-cb { accent-color: var(--accent); width: 12px; height: 12px; }

.clist-id { display: flex; flex-direction: column; overflow: hidden; min-width: 0; }
.id-text { color: var(--text-primary); font-family: var(--font-mono); font-size: 9px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.id-name { color: var(--text-secondary); font-size: 9px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.id-name.clickable { cursor: pointer; text-decoration: underline; text-decoration-style: dotted; text-underline-offset: 2px; }
.id-name.clickable:hover { color: var(--accent); }

.clist-nodes, .clist-edges, .clist-score { text-align: right; font-family: var(--font-mono); color: var(--text-primary); }
.score-val { color: var(--text-secondary); }
.score-na { color: var(--text-muted); }

.clist-parent { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 0 4px; }
.parent-name { color: var(--text-secondary); font-size: 9px; }
.parent-id { color: var(--text-muted); font-family: var(--font-mono); font-size: 8px; }
.parent-na { color: var(--text-muted); }

.clist-status { display: flex; justify-content: center; }
.sortable { cursor: pointer; user-select: none; display: flex; align-items: center; gap: 2px; }
.sortable:hover { color: var(--text-primary); }
.sort-icon { font-size: 7px; color: var(--accent); font-family: var(--font-mono); }
.clist-th .clist-nodes,
.clist-th .clist-edges,
.clist-th .clist-score { justify-content: flex-end; }

.badge {
  font-size: 8px; padding: 1px 5px; border-radius: 4px; font-weight: 500; white-space: nowrap;
}
.badge-success { background: color-mix(in srgb, var(--success) 15%, transparent); color: var(--success); }
.badge-info { background: color-mix(in srgb, var(--accent) 15%, transparent); color: var(--accent); }
.badge-error { background: color-mix(in srgb, var(--error) 15%, transparent); color: var(--error); }
.badge-muted { background: var(--bg-tertiary); color: var(--text-muted); }

.clist-actions-col { display: flex; justify-content: center; }

/* Search */
.clist-search { padding: 6px 12px; border-bottom: 1px solid var(--border); }
.search-input {
  width: 100%; padding: 4px 8px; font-size: 11px; border: 1px solid var(--border);
  border-radius: 4px; background: var(--bg-primary); color: var(--text-primary); outline: none;
  box-sizing: border-box;
}
.search-input:focus { border-color: var(--accent); }

/* Pagination */
.clist-pagination {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 6px 12px; border-top: 1px solid var(--border);
}
.page-info { font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); }

/* Bottom bar */
.cap-bottom {
  display: flex; align-items: center; justify-content: space-between;
  padding: 8px 12px; border-top: 1px solid var(--border); background: var(--bg-tertiary);
}
.cap-batch { display: flex; align-items: center; gap: 4px; }
.batch-label { font-size: 10px; color: var(--text-muted); }
.batch-select { font-size: 10px; padding: 2px 4px; border: 1px solid var(--border); border-radius: 4px; background: var(--bg-primary); color: var(--text-primary); }
.cap-bottom-actions { display: flex; gap: 4px; }
</style>
