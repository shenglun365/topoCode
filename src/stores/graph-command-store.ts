/**
 * useGraphCommandStore — AI 助手与架构图之间的命令/状态通信通道
 *
 * 替代 provide/inject 方案（因 CGV 和 AIAssistantPanel 不在同一 Vue 子树）。
 * 使用 Pinia store 实现跨子树共享状态。
 *
 * 参见 docs/AI助手架构分析引导.md §10
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { GraphCommand, GraphState, CommandResult } from '@/types/graph-commands'

type CommandExecutor = (cmd: GraphCommand) => Promise<CommandResult>

export const useGraphCommandStore = defineStore('graph-command', () => {
  /* ---- 图状态（CGV 写入，AIAssistantPanel 读取） ---- */
  const graphState = ref<GraphState>({
    edgeType: '',
    viewMode: 'force',
    drillLevel: 'root',
    drillCommId: null,
    selectedCommunityId: null,
    nodeCount: 0,
    visibleNodeIds: [],
    stats: {
      totalL0: 0,
      avgQuality: 0,
      lowQualityCount: 0,
      highCorenessCount: 0,
      maxDepth: 0,
      topCommunities: [],
      lowQualityCommunities: [],
    },
  })

  function updateGraphState(patch: Partial<GraphState>) {
    Object.assign(graphState.value, patch)
  }

  function resetGraphState() {
    graphState.value = {
      edgeType: '', viewMode: 'force', drillLevel: 'root',
      drillCommId: null, selectedCommunityId: null,
      nodeCount: 0, visibleNodeIds: [],
      stats: { totalL0: 0, avgQuality: 0, lowQualityCount: 0, highCorenessCount: 0, maxDepth: 0, topCommunities: [], lowQualityCommunities: [] },
    }
  }

  /* ---- 命令执行（AIAssistantPanel 调用 → CGV 执行） ---- */
  const executorRef = ref<CommandExecutor | null>(null)
  const lastResult = ref<CommandResult | null>(null)

  /** CGV 在 onMounted 时注册其 executeCommand 实现 */
  function registerExecutor(fn: CommandExecutor) {
    executorRef.value = fn
  }

  /** AIAssistantPanel 调用此函数执行命令（串行，await 等待完成） */
  async function executeCommand(cmd: GraphCommand): Promise<CommandResult> {
    if (!executorRef.value) {
      const r: CommandResult = { success: false, error: 'CGV executor not registered yet' }
      lastResult.value = r
      return r
    }
    const result = await executorRef.value(cmd)
    lastResult.value = result
    return result
  }

  /* ---- 事件通道（CGV → AIAssistantPanel） ---- */
  interface GraphEvent {
    type: string
    data: Record<string, any>
  }

  const events = ref<GraphEvent[]>([])
  const eventSeq = ref(0)

  function pushEvent(type: string, data: Record<string, any> = {}) {
    events.value.push({ type, data })
    eventSeq.value++
  }

  function popEvent(): GraphEvent | null {
    return events.value.shift() ?? null
  }

  function drainEvents(): GraphEvent[] {
    const all = [...events.value]
    events.value = []
    return all
  }

  return {
    graphState,
    updateGraphState,
    resetGraphState,
    lastResult,
    registerExecutor,
    executeCommand,
    events,
    eventSeq,
    pushEvent,
    popEvent,
    drainEvents,
  }
})
