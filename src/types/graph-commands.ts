/**
 * GraphCommand / GraphState — AI 助手 ↔ 架构图 通信协议
 *
 * 使用 Pinia store（useGraphCommandStore）通信，非 provide/inject。
 * 参见 docs/AI助手架构分析引导.md §5, §10。
 */

// ──────────────────── GraphCommand ────────────────────

/** 所有可由 AI 发出的图操作命令 */
export type GraphCommand =
  // 导航
  | { type: 'highlight'; nodeIds: string[] }
  | { type: 'clearHighlight' }
  | { type: 'focus'; nodeId: string; animate?: boolean }
  | { type: 'drill'; communityId: string }
  | { type: 'rollUp' }
  // 筛选
  | { type: 'filterByQuality'; min?: number; max?: number }
  | { type: 'filterByCoreness'; min?: number }
  | { type: 'filterBySize'; min?: number; max?: number }
  | { type: 'hideNodes'; nodeIds: string[] }
  | { type: 'clearFilter' }
  // 视图
  | { type: 'setViewMode'; mode: 'force' | 'table' | 'heatmap' }
  | { type: 'setEdgeType'; edgeType: string }
  | { type: 'resetView' }
  // 快照/对比
  | { type: 'saveSnapshot' }
  | { type: 'compareVersions'; from: string; to: string }
  // 分析
  | { type: 'openCommunityDetail'; communityId: string }
  // Agent 调度
  | { type: 'dispatchAgent'; action: string; params: Record<string, any> }

/** 命令执行结果 */
export interface CommandResult {
  success: boolean
  error?: string
}

// ──────────────────── GraphState ────────────────────

/** 每次 AI 请求前自动注入的图状态快照 */
export interface GraphState {
  edgeType: string
  viewMode: string
  drillLevel: string
  drillCommId: string | null
  selectedCommunityId: string | null
  nodeCount: number
  visibleNodeIds: string[]
  stats: {
    totalL0: number
    avgQuality: number
    lowQualityCount: number
    highCorenessCount: number
    maxDepth: number
    topCommunities: Array<{
      id: string
      name: string
      nodeCount: number
      qualityScore?: number
      avgCoreness?: number
    }>
    lowQualityCommunities: Array<{
      id: string
      name: string
      qualityScore: number
    }>
  }
}

// ──────────────────── 标签解析 ────────────────────

const KNOWN_COMMANDS = new Set<string>([
  'highlight', 'clearHighlight', 'focus', 'drill', 'rollUp',
  'filterByQuality', 'filterByCoreness', 'filterBySize',
  'hideNodes', 'clearFilter',
  'setViewMode', 'setEdgeType', 'resetView',
  'saveSnapshot', 'compareVersions',
  'openCommunityDetail',
  'dispatchAgent',
])

/** 参数解析：key="val" → { key: val }，逗号分隔的列表值转为数组 */
function parseArgs(raw: string): Record<string, any> {
  const args: Record<string, any> = {}
  const re = /(\w+)\s*=\s*"([^"]*?)"/g
  let m: RegExpExecArray | null
  while ((m = re.exec(raw)) !== null) {
    const val = m[2]
    if (val.includes(',')) {
      args[m[1]] = val.split(',').map(v => v.trim()).filter(Boolean)
    } else if (val === 'true') {
      args[m[1]] = true
    } else if (val === 'false') {
      args[m[1]] = false
    } else if (/^\d+$/.test(val)) {
      args[m[1]] = parseInt(val, 10)
    } else if (/^\d+\.\d+$/.test(val)) {
      args[m[1]] = parseFloat(val)
    } else {
      args[m[1]] = val
    }
  }
  return args
}

export interface ParsedCommand {
  type: string
  args: Record<string, any>
}

/**
 * 解析 AI 回复中的 `[CMD: ...]` 标签。
 * 示例：`[CMD: highlight nodeIds="L0-1,L0-2"]` → { type: 'highlight', args: { nodeIds: ['L0-1', 'L0-2'] } }
 * 未知命令返回 null。
 */
export function parseCommandTag(text: string): ParsedCommand[] {
  const results: ParsedCommand[] = []
  const re = /\[CMD:\s*(\w+)\s*(.*?)\]/gi
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const type = m[1]
    if (!KNOWN_COMMANDS.has(type)) continue
    results.push({ type, args: parseArgs(m[2] || '') })
  }
  return results
}

/** AI 回复中的 [CONFIRM:] 确认标签 */
export interface ParsedConfirm {
  cmd: string
  communities?: number
  time?: string
  tokens?: string
  cost?: string
}

export function parseConfirmTag(text: string): ParsedConfirm | null {
  const re = /\[CONFIRM:\s*cmd="([^"]*?)"(?:\s+communities="?(\d+)"?)?(?:\s+time="([^"]*?)")?(?:\s+tokens="([^"]*?)")?(?:\s+cost="([^"]*?)")?\]/i
  const m = re.exec(text)
  if (!m) return null
  return {
    cmd: m[1],
    communities: m[2] ? parseInt(m[2]) : undefined,
    time: m[3],
    tokens: m[4],
    cost: m[5],
  }
}

/** AI 回复中的 [SUGGEST:] 建议标签 */
export interface ParsedSuggest {
  label: string
  command: string
  args?: Record<string, string>
}

export function parseSuggestTags(text: string): ParsedSuggest[] {
  const results: ParsedSuggest[] = []
  const re = /\[SUGGEST:\s*label="([^"]*?)"\s+command="(\w+)"(?:\s+args="([^"]*?)")?\]/gi
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const args: Record<string, string> = {}
    const rawArgs = m[3]
    if (rawArgs) {
      rawArgs.split(',').forEach(pair => {
        const [k, v] = pair.split('=').map(s => s.trim())
        if (k && v) args[k] = v
      })
    }
    results.push({ label: m[1], command: m[2], args: Object.keys(args).length ? args : undefined })
  }
  return results
}

/** 从 AI 回复文本中移除所有 [CMD:], [CONFIRM:], [SUGGEST:] 标签，返回纯展示文本 */
export function stripCommandTags(text: string): string {
  return text
    .replace(/\[CMD:\s*\w+\s*[^\]]*\]/gi, '')
    .replace(/\[CONFIRM:\s*[^\]]*\]/gi, '')
    .replace(/\[SUGGEST:\s*[^\]]*\]/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}
