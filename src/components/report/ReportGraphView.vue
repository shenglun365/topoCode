<script setup lang="ts">
/**
 * 报告图视图 — TopoScript 组装 + AnimationStage 嵌入
 *
 * 接收查询参数，请求后端获取图数据，组装 TopoScript，渲染图。
 * 支持节点/边点击事件，缓存 TopoScript 脚本。
 */

import { ref, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAnimation } from '@/composables/useAnimation'
import { computeCacheKey, getCachedTopoScript, cacheTopoScript } from '@/utils/graphCache'
import { getNodeStyle, getEdgeStyle, getCommunityStyle, applyUserStyle } from '@/utils/nodeStyleMap'
import type { QueryParams } from './ReportQueryPanel.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('RP-014')
const { t } = useI18n()

const props = defineProps<{
  taskId: string
  edgeType?: string  // CALL | INCLUDE
}>()

const emit = defineEmits<{
  'node-click': [nodeId: string, nodeData: any]
  'edge-click': [edgeId: string, edgeData: any]
  'community-click': [commId: string, commData: any]
  'community-dblclick': [commId: string]
}>()

const stageRef = ref<HTMLElement | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const currentQuery = ref<QueryParams | null>(null)

// 切换 tab 时重置
watch(() => props.taskId, (newId, oldId) => {
  console.log('[ReportGraphView] watch taskId changed:', oldId, '->', newId, 'resetting')
  currentQuery.value = null
  error.value = null
})

// 图数据（用于缓存 KEY 计算）
const graphDataRef = ref<any>({ nodes: [], edges: [], communities: [] })

// 用户自定义样式（从 task 的 node_style_map 读取）
const userStyleMap = ref<Record<string, any> | null>(null)

// Animation composable
const {
  load,
  onNodeClick,
  onEdgeClick,
  fitToScreen,
  switchLayout,
} = useAnimation({
  renderer: 'd3',
  width: 1200,
  height: 600,
  zoom: true,
  layout: 'force-directed',
})

// 绑定点击事件
onNodeClick.value = (nodeId: string) => {
  // 解析节点数据
  const nodeData = graphDataRef.value.nodes.find((n: any) => n.id === nodeId)
  if (nodeData) {
    emit('node-click', nodeId, nodeData)
  }
}

onEdgeClick.value = (edgeId: string) => {
  const edgeData = graphDataRef.value.edges.find((e: any) => e.id === edgeId)
  if (edgeData) {
    emit('edge-click', edgeId, edgeData)
  }
}

// ==================== TopoScript 组装 ====================

function assembleTopoScript(graphData: any, layout: string = 'force-directed'): string {
  const { nodes, edges, communities } = graphData
  let script = ''

  // 场景配置
  script += `topo.scene({ layout: "${layout}", width: 1200, height: 600 })\n`

  // 社区分组
  for (const comm of communities) {
    const style = getCommunityStyle(comm.nestingLevel || 0)
    const label = comm.description || comm.comm_id
    const nodeIds = (comm.nodeIds || []).map((id: string) => `n_${id}`)

    script += `topo.group({\n`
    script += `  id: "g_${comm.comm_id}",\n`
    script += `  label: "${label.replace(/"/g, '\\"')}",\n`
    script += `  nodeIds: [${nodeIds.join(', ')}],\n`
    script += `  style: { fillColor: "${style.fillColor}20", borderColor: "${style.strokeColor}", borderWidth: 2, cornerRadius: 8, padding: 20 }\n`
    script += `})\n`
  }

  // 节点
  for (const node of nodes) {
    const baseStyle = getNodeStyle(node.type || 'function')
    const style = applyUserStyle(baseStyle, userStyleMap.value, node.type || 'function')

    script += `topo.node({\n`
    script += `  id: "${node.id}",\n`
    script += `  label: "${(node.label || node.id).replace(/"/g, '\\"')}",\n`
    script += `  style: {\n`
    script += `    shape: "${style.shape}",\n`
    script += `    fillColor: "${style.fillColor}",\n`
    script += `    strokeColor: "${style.strokeColor}",\n`
    if (style.width) script += `    width: ${style.width},\n`
    if (style.height) script += `    height: ${style.height},\n`
    if (style.radius) script += `    radius: ${style.radius},\n`
    script += `    fontSize: ${style.fontSize || 10},\n`
    script += `    fontColor: "${style.fontColor || '#FFFFFF'}"\n`
    script += `  }\n`
    script += `})\n`
  }

  // 边（过滤 source/target 不在 nodes 中的无效边）
  const nodeIdSet = new Set(nodes.map((n: any) => n.id))
  for (const edge of edges) {
    if (!nodeIdSet.has(edge.source) || !nodeIdSet.has(edge.target)) {
      console.warn('[ReportGraphView] Skipping invalid edge:', edge.id, 'source:', edge.source, 'target:', edge.target)
      continue
    }
    const edgeStyle = getEdgeStyle(edge.type || 'CALL')

    script += `topo.edge({\n`
    script += `  id: "${edge.id}",\n`
    script += `  source: "${edge.source}",\n`
    script += `  target: "${edge.target}",\n`
    script += `  style: {\n`
    script += `    color: "${edgeStyle.color}",\n`
    script += `    strokeWidth: ${edgeStyle.strokeWidth},\n`
    script += `    markerEnd: "${edgeStyle.markerEnd}"\n`
    script += `  }\n`
    script += `})\n`
  }

  return script
}

// ==================== 查询图数据 ====================

async function queryGraph(params: QueryParams): Promise<void> {
  console.log('[ReportGraphView] queryGraph called, params:', JSON.stringify(params), 'props.taskId=', props.taskId, 'props.edgeType=', props.edgeType)
  loading.value = true
  error.value = null
  currentQuery.value = params

  try {
    // 计算缓存 KEY
    const cacheKey = await computeCacheKey({
      taskId: props.taskId,
      edgeType: props.edgeType || 'CALL',
      commLv: params.commLv,
      commIds: params.commIds,
      depth: params.depth,
    })
    console.log('[ReportGraphView] cacheKey:', cacheKey)

    // 尝试从缓存读取
    const cached = await getCachedTopoScript(cacheKey)
    if (cached) {
      console.log('[ReportGraphView] cache HIT, rendering')
      await renderTopoScript(cached)
      loading.value = false
      return
    }
    console.log('[ReportGraphView] cache MISS, calling backend')
    
    // 序列化参数（防 Vue Proxy 导致 Electron IPC 克隆错误）
    const callParams = JSON.parse(JSON.stringify({
      taskId: props.taskId,
      edgeType: props.edgeType || 'CALL',
      commLv: params.commLv,
      commIds: params.commIds,
      depth: params.depth,
    }))
    console.log('[ReportGraphView] calling window.api.analysis.getCommunityGraph with:', JSON.stringify(callParams))

    // 请求后端获取图数据
    let graphData
    try {
      graphData = await window.api.analysis.getCommunityGraph(callParams)
      console.log('[ReportGraphView] IPC call succeeded')
    } catch (ipcErr: any) {
      console.error('[ReportGraphView] IPC call failed:', ipcErr.message, ipcErr)
      throw ipcErr
    }

    console.log('[ReportGraphView] backend response: nodes=', graphData?.nodes?.length, 'edges=', graphData?.edges?.length, 'communities=', graphData?.communities?.length)

    if (!graphData || !graphData.nodes) {
      error.value = t('report.noData')
      loading.value = false
      return
    }

    graphDataRef.value = graphData

    // 组装 TopoScript
    const topoScript = assembleTopoScript(graphData)
    console.log('[ReportGraphView] assembled TopoScript (first 500 chars):', topoScript.substring(0, 500))
    console.log('[ReportGraphView] assembled TopoScript total length:', topoScript.length)

    // 缓存
    const dataHash = JSON.stringify(graphData)
    await cacheTopoScript(cacheKey, topoScript, dataHash)

    // 渲染
    await renderTopoScript(topoScript)
  } catch (e: any) {
    error.value = e.message || String(e)
    console.error('[ReportGraphView] Query failed:', e)
  } finally {
    loading.value = false
  }
}

async function renderTopoScript(topoScript: string): Promise<void> {
  if (!stageRef.value) {
    console.warn('[ReportGraphView] renderTopoScript: stageRef is null, skipping')
    return
  }

  await nextTick()
  console.log('[ReportGraphView] renderTopoScript: calling load(), stageRef exists:', !!stageRef.value)

  const success = load(stageRef.value, topoScript)
  console.log('[ReportGraphView] renderTopoScript: load() returned:', success)
  if (!success) {
    error.value = 'TopoScript compilation failed'
    console.error('[ReportGraphView] renderTopoScript FAILED — TopoScript length:', topoScript.length)
    // 输出失败脚本的前 300 字符便于调试
    console.error('[ReportGraphView] TopoScript preview:', topoScript.substring(0, 300))
    return
  }
  // 渲染完成后适配屏幕
  await nextTick()
  fitToScreen(40)
  console.log('[ReportGraphView] renderTopoScript: fitToScreen done')
}

// ==================== 暴露 API ====================

defineExpose({
  queryGraph,
  switchLayout: (layout: string) => switchLayout(layout as any),
  fitToScreen: () => fitToScreen(40),
})
</script>

<template>
  <div class="report-graph-view">
  <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <!-- 加载状态 -->
    <div v-if="loading" class="loading-overlay">
      <div class="loading-spinner"></div>
      <span>{{ t('report.rendering') }}</span>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="error" class="error-state">
      <span>{{ error }}</span>
    </div>

    <!-- 空状态 -->
    <div v-else-if="!currentQuery" class="empty-state">
      <span>{{ t('report.noData') }}</span>
    </div>

    <!-- 渲染容器 -->
    <div ref="stageRef" class="graph-container"></div>
  </div>
</template>

<style scoped>
.report-graph-view {
  flex: 1;
  min-height: 0;
  position: relative;
  overflow: hidden;
  background: var(--bg-primary);
}

.graph-container {
  width: 100%;
  height: 100%;
}

.loading-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: var(--bg-primary);
  z-index: 10;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.error-state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--error);
  font-size: 13px;
}

.empty-state {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  font-size: 13px;
}
</style>
