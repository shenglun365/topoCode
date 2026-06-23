<script setup lang="ts">
/**
 * AI 助手面板 — 右侧栏 SH-004
 *
 * 管理当前项目分析报告的对话 session。
 * 支持自由提问和报告上下文相关的分析对话。
 */

import { ref, computed, nextTick, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PaperAirplaneIcon, SparklesIcon, TrashIcon,
  DocumentTextIcon, ClockIcon,
  CursorArrowRippleIcon,
} from '@heroicons/vue/24/outline'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import { useSettingsStore } from '@/stores/settings-store'
import { useProjectStore } from '@/stores/project'
import { useAnalysisStore } from '@/stores/analysis'
import { useCommunityStore, type CommunityItem } from '@/stores/community-store'
import { useNavigationStore } from '@/stores/navigation'
import { isLLMConfigured, chat } from '@/services/llmClient'
import { useGraphCommandStore } from '@/stores/graph-command-store'
import { useComponentSelectionStore } from '@/stores/component-selection-store'
import { useChatSession, type SessionPage } from '@/stores/chat-session-store'
import { parseCommandTag, parseConfirmTag, parseSuggestTags, stripCommandTags } from '@/types/graph-commands'
import { useComponentId } from '@/composables/useComponentId'
import { ipc } from '@/services/ipc'

const { showId, componentId } = useComponentId('SH-004')
const { t } = useI18n()
const settingsStore = useSettingsStore()
const projectStore = useProjectStore()
const communityStore = useCommunityStore()
const navigationStore = useNavigationStore()
const cmdStore = useGraphCommandStore()
const selectionStore = useComponentSelectionStore()
const chatSession = useChatSession()

/* ---- 分析模式: 快速 (quick) vs 深入 (deep) ---- */
const analysisMode = ref<'quick' | 'deep'>('quick')
function toggleAnalysisMode() {
  analysisMode.value = analysisMode.value === 'quick' ? 'deep' : 'quick'
  const label = analysisMode.value === 'deep' ? '深入分析' : '快速分析'
  const range = analysisMode.value === 'deep' ? '500-2000字' : '100-300字'
  addMessage('system', `切换至「${label}」模式（${range}）`)
}

/* ---- 引导模式 vs 普通模式 ---- */
const guideMode = ref(false)

function startGuide() {
  const wasGuide = guideMode.value
  guideMode.value = true
  if (wasGuide) return
  const tourIntro = [
    '我来带你了解这个项目的架构。',
    '',
    '如果图数据已加载，我会先介绍项目概况，然后逐步引导你探索核心社区、低质量模块和外部依赖。',
    '',
    '你也可以直接问："帮我分析所有社区的结构" 或 "生成架构文档"。',
  ].join('\n')
  addMessage('assistant', tourIntro)
}

function exitGuide() {
  guideMode.value = false
}

const GUIDE_SYSTEM_PROMPT = [
  '你是 TopoCode 架构分析助手，当前处于引导模式，正在向用户介绍项目架构。',
  '',
  '引导流程（Tour 1）：逐步介绍项目，不要一次性输出所有内容，每次只讲一个主题，等待用户回应：',
  '1. 总览：项目有多少个 L0 社区，最大的社区，高/低质量统计 → 使用 [CMD: highlight ...] 高亮 top 社区',
  '2. 最大社区：深入介绍并 [CMD: focus ...] 定位到该节点',
  '3. 低质量诊断：介绍低质量社区，[CMD: filterByQuality max=0.2] 筛出来',
  '4. 核心组件：高核心度社区，[CMD: filterByCoreness min=3] 筛出来',
  '5. 外部依赖：介绍外部包情况',
  '6. 下一步：询问用户想看什么',
  '',
  '可用的 [CMD:] 命令：',
  '  [CMD: highlight nodeIds="id1,id2"]   — 隐藏其他节点，仅显示指定节点',
  '  [CMD: clearHighlight]                 — 取消所有隐藏',
  '  [CMD: focus nodeId="xxx"]             — 居中放大某个节点',
  '  [CMD: drill communityId="xxx"]        — 下钻到子社区',
  '  [CMD: rollUp]                         — 返回上一层级',
  '  [CMD: filterByQuality max=0.2]        — 筛选低质量社区（max<0.3 为低质量）',
  '  [CMD: filterByCoreness min=3]         — 筛选核心组件（min≥3 为高核心度）',
  '  [CMD: setViewMode mode="table"]       — 切换视图（force/table/heatmap）',
  '  [CMD: resetView]                      — 重置视图',
  '',
  '筛选阈值参考：quality 高质量≥0.5 低质量≤0.2 | coreness 核心≥3 | size 大型>30 小型≤5',
  '',
  '使用 [CMD:] 时要谨慎：每次最多发 1-2 个命令，用户观察图变化后再继续。',
  '对话中始终使用中文回复。',
].join('\n')

const DEFAULT_SYSTEM_PROMPT = [
  '你是 TopoCode 架构分析助手，帮助用户理解和分析项目代码架构。',
  '用户可输入 /help 或 /帮助 查看全部可用命令；当被问到"你能做什么"时主动提醒用户使用 /help。',
  '',
  '可用 [CMD:] 命令：highlight, clearHighlight, focus, drill, rollUp, filterByQuality, filterByCoreness, filterBySize, hideNodes, clearFilter, setViewMode, setEdgeType, resetView, openCommunityDetail, saveSnapshot, compareVersions, dispatchAgent',
  '参数格式：key="value"。阈值：quality≥0.5高 ≤0.2低 | coreness≥3核心 | size>30大 ≤5小',
  '',
  '对话使用中文回复，需要操作图时使用 [CMD:] 标签，每次最多 1-2 个命令。',
].join('\n')

const HELP_TEXT = [
  '## 可用命令',
  '',
  '### 对话指令（直接输入）',
  '| 指令 | 说明 |',
  '|------|------|',
  '| `/help` / `/帮助` | 显示本帮助 |',
  '| `/select [--all/--include/--call/--l0/--l1/--l2/--clear]` | 无参数时切换选择模式；`--all` 全选所有社区；`--include`/`--call`/`--l0`/`--l1`/`--l2` 按条件自动选取；`--clear` 清除已选 |',
  '| `/arch all` | 启动 Agent 对全部社区执行架构分析 |',
  '| `/analyze all` | 同上 |',
  '| `/analyze_components` `[-L zh/en] [-j N] [-r N] [--agentic] [--summary-model <id>] [-c N] [--force] [--call/--include] [--l0/--l1/--l2]` | 对已选组件启动批量分析。「-L」语言，「-j」并发(1-5)，「-r」轮次(1-30)，「--agentic」自主分析，「--summary-model」摘要模型ID，「-c」摘要并发(1-10)，「--force」强制覆盖已分析组件，「--call/--include」边类型筛选，「--l0/--l1/--l2」层级筛选 |',
  '| `/presummary` | 查看文件预摘要概况（P0/P1/P2 文件数） |',
  '| `/presummary files P0/P1/P2 [页码]` | 分页查看某批次文件列表 |',
  '| `/presummary start <batch> [-n N] [-j N]` | 启动预摘要任务。`<batch>` 可为 `P2`、`P0,P1,P2` 或 `all`。「-n」限文件数，「-j」并发数（1-10） |',
  '| `/presummary get <文件路径>` | 查询单个文件摘要内容 |',
  '| `/presummary delete <文件路径>` | 删除单个文件摘要缓存 |',
  '| `/presummary rerun <文件路径>` | 单个文件重跑摘要 |',
  '| `/track [options]` | 跟踪项目变更 |',
  '| `/diff [options]` | 对比快照版本 |',
  '',
  '### 图操作命令（AI 回复中使用 [CMD:] 标签）',
  '| 命令 | 参数 | 说明 |',
  '|------|------|------|',
  '| `[CMD: highlight ...]` | `nodeIds="id1,id2"` | 仅显示指定节点 |',
  '| `[CMD: clearHighlight]` | — | 取消所有高亮 |',
  '| `[CMD: focus ...]` | `nodeId="xxx"` | 居中聚焦某节点 |',
  '| `[CMD: drill ...]` | `communityId="xxx"` | 下钻到子社区 |',
  '| `[CMD: rollUp]` | — | 返回上一层级 |',
  '| `[CMD: filterByQuality ...]` | `max=0.2` 或 `min=0.5` | 按质量分筛选 |',
  '| `[CMD: filterByCoreness ...]` | `min=3` | 筛选核心组件 |',
  '| `[CMD: filterBySize ...]` | `min=30` 或 `max=5` | 按节点数筛选 |',
  '| `[CMD: hideNodes ...]` | `nodeIds="id1,id2"` | 隐藏指定节点 |',
  '| `[CMD: clearFilter]` | — | 清除所有筛选 |',
  '| `[CMD: setViewMode ...]` | `mode="force\|table\|heatmap"` | 切换视图 |',
  '| `[CMD: setEdgeType ...]` | `edgeType="CALL"` | 切换边类型 |',
  '| `[CMD: resetView]` | — | 重置视图 |',
  '| `[CMD: saveSnapshot]` | — | 保存快照 |',
  '| `[CMD: compareVersions ...]` | `from="v1" to="v2"` | 对比版本 |',
  '| `[CMD: openCommunityDetail ...]` | `communityId="xxx"` | 打开社区详情 |',
  '| `[CMD: dispatchAgent ...]` | `action="analyze"` | 调度 Agent 任务 |',
  '',
  '### 筛选阈值参考',
  '- quality: 高质量 ≥0.5、低质量 ≤0.2',
  '- coreness: 高核心度 ≥3',
  '- size: 大型 >30 节点、小型 ≤5 节点',
  '',
  '### 模式',
  '- **普通模式**：自由问答，AI 根据上下文自动使用图操作命令',
  '- **引导模式**：点击图上 🎓 按钮启动，AI 带你逐步了解项目架构',
  '- **组件选择模式**：输入 `/select` 或点击输入栏 📎 按钮切换。无参数时手动点选；支持 `/select --include --l0` 等参数自动选取。选中后输入分析请求',
  '- **批量组件分析**：选择组件后，输入 `/analyze_components` 启动批量解析，结果写入 SQLite 并可在任务面板查看进度',
  '- **分析模式开关**：输入框下方 ⚡/🔬 按钮切换「快速模式」（单次 LLM 调用）和「深入分析」（Agent 多轮文件探索），',
  '  模式影响组件分析和整体架构分析的行为',
].join('\n')

const md = new MarkdownIt({
  html: true,
  linkify: true,
  typographer: true,
  breaks: true,
  highlight(str: string, lang: string) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(str, { language: lang }).value
      } catch { /* ignore highlight errors */ }
    }
    return escapeHtml(str)
  },
})

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function renderMarkdown(text: string): string {
  if (!text) return ''
  return md.render(text)
}

function formatMessageContent(msg: Message): string {
  if (msg.role === 'assistant') {
    return renderMarkdown(msg.content)
  }
  return msg.content
}

interface Message {
  id: string
  role: 'user' | 'assistant' | 'error' | 'system'
  content: string
  timestamp: number
  isStreaming?: boolean
  suggestions?: Array<{ label: string; command: string; args?: Record<string, string> }>
}

const messages = ref<Message[]>([])
const messagePageSize = ref(10)
const userInput = ref('')

/* ---- 指令联想 ---- */
const CMD_HISTORY_KEY = 'ai-command-history'
const USER_COMMANDS = ['/help', '/帮助', '/select', '/arch all', '/analyze all', '/analyze_components', '/analyze_components --agentic',
  '/presummary', '/presummary files', '/presummary start', '/presummary get', '/presummary delete', '/presummary rerun',
  '/track', '/diff']

function loadCommandHistory(): string[] {
  try { return JSON.parse(localStorage.getItem(CMD_HISTORY_KEY) || '[]') } catch { return [] }
}
function saveCommandHistory(cmds: string[]) {
  localStorage.setItem(CMD_HISTORY_KEY, JSON.stringify(cmds))
}

const commandHistory = ref<string[]>(loadCommandHistory())
function recordCommand(cmd: string) {
  const idx = commandHistory.value.indexOf(cmd)
  if (idx > -1) commandHistory.value.splice(idx, 1)
  commandHistory.value.unshift(cmd)
  if (commandHistory.value.length > 20) commandHistory.value.length = 20
  saveCommandHistory(commandHistory.value)
}

const showSuggestions = ref(false)
const suggestionIndex = ref(-1)

const suggestions = computed(() => {
  const input = userInput.value
  if (!input.startsWith('/')) return []
  const prefix = input.toLowerCase()
  if (prefix === '/') return commandHistory.value.slice(0, 5)
  const matched = USER_COMMANDS.filter(c => c.toLowerCase().startsWith(prefix))
  matched.sort((a, b) => {
    const ia = commandHistory.value.indexOf(a)
    const ib = commandHistory.value.indexOf(b)
    return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib)
  })
  return matched.slice(0, 5)
})

let _skipSuggestionWatch = false

watch(userInput, () => {
  if (_skipSuggestionWatch) { _skipSuggestionWatch = false; return }
  if (userInput.value.startsWith('/') && suggestions.value.length > 0) {
    showSuggestions.value = true
    suggestionIndex.value = -1
  } else {
    showSuggestions.value = false
  }
})

function applySuggestion(index: number) {
  const cmd = suggestions.value[index]
  if (!cmd) return
  _skipSuggestionWatch = true
  userInput.value = cmd
  showSuggestions.value = false
  suggestionIndex.value = -1
}

// 消息分页：默认显示最近 10 条，滚动到顶部可加载更多
const displayedMessages = computed(() => {
  const total = messages.value.length
  if (total <= messagePageSize.value) return messages.value
  return messages.value.slice(total - messagePageSize.value)
})
const hasMoreMessages = computed(() => messages.value.length > messagePageSize.value)

function showMoreMessages() {
  messagePageSize.value += 10
}

const streaming = ref(false)
const scrollRef = ref<HTMLElement | null>(null)

const showCmdConfirm = ref(false)
const cmdConfirmData = ref<{
  text: string
  action: string
  args: Record<string, string>
  confirmMeta?: { communities?: number; time?: string; tokens?: string; cost?: string }
}>({ text: '', action: '', args: {} })

const llmConfigured = computed(() => isLLMConfigured())

// Session management — auto-bound to current page + project + task
const currentPage = computed<SessionPage>(() => navigationStore.currentPage as SessionPage || 'home')
const sessionProjectId = computed(() => projectStore.selectedProjectId || '')
const sessionTaskId = computed(() => projectStore.activeTab?.taskId || '')

const sessionKey = computed(() =>
  chatSession.buildKey(currentPage.value, sessionProjectId.value, sessionTaskId.value)
)

function resolveTaskId(): string | null {
  return projectStore.activeTab?.taskId || null
}
const hasAnalysisContext = computed(() => !!resolveTaskId())

// 会话 key 变化 → 自动保存旧会话 + 加载新会话
watch(sessionKey, (newKey, oldKey) => {
  if (!newKey) return
  if (oldKey && oldKey !== newKey) {
    chatSession.saveSession(oldKey, messages.value as any)
  }
  messages.value = []
  const saved = chatSession.loadSession(newKey)
  if (saved.length > 0) {
    messages.value = saved as Message[]
  } else {
    addMessage('system', t('ai.assistantWelcome'))
    addMessage('system', '输入 /help 或 /帮助 查看全部可用命令和模式')
  }
})

let _saveTimer: ReturnType<typeof setTimeout> | null = null
watch(messages, () => {
  if (_saveTimer) clearTimeout(_saveTimer)
  _saveTimer = setTimeout(() => {
    const key = sessionKey.value
    if (key) chatSession.saveSession(key, messages.value as any)
  }, 1000)
}, { deep: true })

function scrollToBottom() {
  nextTick(() => {
    if (scrollRef.value) {
      scrollRef.value.scrollTop = scrollRef.value.scrollHeight
    }
  })
}

function addMessage(role: Message['role'], content: string): Message {
  const msg: Message = {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    role,
    content,
    timestamp: Date.now(),
    isStreaming: role === 'assistant',
  }
  messages.value.push(msg)
  scrollToBottom()
  return msg
}

function handleCmdConfirm() {
  showCmdConfirm.value = false
  const cd = cmdConfirmData.value

  // 如果确认的是 agent 调度任务 → 直接调用后端
  if (cd.action === 'analyze' && cd.args.all === 'true') {
    addMessage('user', cd.text)
    addMessage('system', 'Agent 分析任务已启动，请稍后查看结果...')
    if (activeTaskId.value) {
      communityStore.triggerArchAnalysis(activeTaskId.value, 'INCLUDE', cd.args.level || 'L0', undefined, undefined, cd.args.force === 'true')
        .catch(e => addMessage('error', String(e)))
    }
    return
  }

  addMessage('user', cd.text)
  streaming.value = true
  const assistantMsg = addMessage('assistant', '')

  const sendMessages: Array<{ role: string; content: string }> = []
  const gs = cmdStore.graphState
  if (gs.nodeCount > 0) {
    sendMessages.push({ role: 'system', content: `当前图状态:\n${JSON.stringify(gs, null, 0)}` })
  }
  sendMessages.push(...messages.value
    .filter(m => m.role !== 'system' && m !== assistantMsg)
    .map(m => ({ role: m.role, content: m.content })))

  chat({
    messages: sendMessages,
    onChunk(chunk: string) {
      assistantMsg.content += chunk
      scrollToBottom()
    },
  }).then(async full => {
    const display = stripCommandTags(full || assistantMsg.content)
    assistantMsg.content = display
    const cmds = parseCommandTag(full || display)
    for (const cmd of cmds) {
      await cmdStore.executeCommand({ type: cmd.type, ...cmd.args } as any)
    }
    assistantMsg.isStreaming = false
  }).catch((err: any) => {
    assistantMsg.content = err.message || 'unknown error'
    assistantMsg.role = 'error'
    assistantMsg.isStreaming = false
  }).finally(() => { streaming.value = false })
}

async function handleSend() {
  const text = userInput.value.trim()
  if (!text || streaming.value) return

  // /cmd 指令检测
  if (text.startsWith('/')) {
    recordCommand(text)
    // /select — 切换组件选择模式 或 按条件自动选取
    const selectRe = /^\/select(?:\s+(.+))?$/i
    const selectMatch = text.match(selectRe)
    if (selectMatch) {
      addMessage('user', text)
      userInput.value = ''
      const args = (selectMatch[1] || '').trim()
      if (!args) {
        // 无参数：切换选择模式（原行为）
        selectionStore.toggleSelecting()
        const status = selectionStore.selecting ? '已激活' : '已退出'
        addMessage('system', `组件选择模式 ${status}。在左侧结构图或标签视图中点选组件，选中后输入分析请求。`)
        return
      }
      if (/^--clear$/i.test(args)) {
        selectionStore.clearAll()
        addMessage('system', '已清除所有组件选择。')
        return
      }
      // 校验未知参数
      const VALID_SELECT_FLAGS = ['--include','--call','--all','--clear','--l0','--l1','--l2']
      const unknownFlags = args.split(/\s+/).filter(f => f.startsWith('--') && !VALID_SELECT_FLAGS.includes(f.toLowerCase()))
      if (unknownFlags.length > 0) {
        addMessage('system', `未知参数: ${unknownFlags.join('、')}。可用参数: ${VALID_SELECT_FLAGS.join(' ')}`)
        return
      }
      // 按条件自动选取社区
      const taskId = resolveTaskId()
      if (!taskId) { addMessage('system', '未找到激活的任务。'); return }
      const taskComs = communityStore.tasks[taskId]?.communities || []
      if (taskComs.length === 0) { addMessage('system', '社区列表尚未加载，请先打开左侧结构图。'); return }
      const edgeFilter = args.match(/--(include|call)/i)?.[1]?.toUpperCase()
      const levelFilters = [...args.matchAll(/--l([012])/gi)].map(m => 'L' + m[1])
      const wantAll = /--all/i.test(args)
      const matching = taskComs.filter(c => {
        if (!wantAll) {
          if (edgeFilter && c.edgeType?.toUpperCase() !== edgeFilter) return false
          if (levelFilters.length > 0 && !levelFilters.includes(c.level?.toUpperCase())) return false
        }
        return true
      })
      if (matching.length === 0) { addMessage('system', '未找到匹配的社区。'); return }
      if (!selectionStore.selecting) selectionStore.toggleSelecting()
      selectionStore.clearAll()
      selectionStore.selectMany(matching.map(c => ({
        id: c.communityId,
        type: 'community' as const,
        name: c.name || c.communityId,
        taskId,
        metadata: { nodeCount: c.nodeCount, fileCount: c.fileCount, qualityScore: c.qualityScore ?? undefined },
      })))
      addMessage('system', `已选中 ${matching.length} 个组件。可输入 /analyze_components 启动批量分析，或点选加减组件后发送消息。`)
      return
    }
    // /analyze_components — 批量分析已选中的组件
    // 新增过滤: --call / --include / --l0 / --l1 / --l2 (不指定则不过滤)
    const acRe = /^\/analyze_components(?:\s+--force)?(?:\s+-L\s+(zh|en))?(?:\s+-j\s+(\d+))?(?:\s+-r\s+(\d+))?(?:\s+--agentic)?(?:\s+--summary-model\s+(\S+))?(?:\s+-c\s+(\d+))?(?:\s+(--call|--include))?(?:\s+(--l[012]))?(?:\s+(--l[012]))?(?:\s+(--l[012]))?$/i
    const acMatch = text.match(acRe)
    if (acMatch) {
      const force = text.includes('--force')
      const language = acMatch[1] || ''
      const concurrency = Math.max(1, Math.min(5, parseInt(acMatch[2] || '1')))
      const rawTurns = parseInt(acMatch[3] || '30')
      const maxTurns = Math.max(1, Math.min(30, rawTurns))
      const agentic = analysisMode.value === 'deep' || text.includes('--agentic')
      const summaryModel = acMatch[4] || ''
      const rawSubConc = parseInt(acMatch[5] || '1')
      const subagentConcurrency = Math.max(1, Math.min(10, rawSubConc))
      const rawFlags = text.match(/--(call|include|l[012])/gi) || []
      const edgeTypeFilter = rawFlags.find(f => f === '--call' || f === '--include')
      const levelFilter = rawFlags.filter(f => /^--l[012]$/i.test(f)).map(f => f.toUpperCase().slice(2))

      if (selectionStore.selectedCount === 0) {
        addMessage('user', text)
        userInput.value = ''
        addMessage('system', '尚未选择任何组件。请先用 /select 激活选择模式，然后在左侧点选组件，或使用 /select --include/--call/--l0 等参数自动选取。')
        return
      }
      // 限制单次提交组件数
      const MAX_COMPONENTS = 100
      let selectedComps = [...selectionStore.selectedList]
      // 应用过滤
      if (edgeTypeFilter || levelFilter.length > 0) {
        selectedComps = selectedComps.filter(c => {
          const et = c.edgeType?.toUpperCase?.() || ''
          const lv = c.level?.toUpperCase?.() || ''
          if (edgeTypeFilter && et !== edgeTypeFilter.replace('--', '').toUpperCase()) return false
          if (levelFilter.length > 0 && !levelFilter.includes(lv)) return false
          return true
        })
      }
      if (selectedComps.length > MAX_COMPONENTS) selectedComps.length = MAX_COMPONENTS
      // 将选中组件转为对话消息
      const compNames = selectedComps.map(r => r.name).join('、')
      const taskId = resolveTaskId() || selectionStore.selectedList[0]?.taskId || null
      addMessage('user', `分析组件: ${compNames}`)
      userInput.value = ''
      const langHint = language === 'zh' ? '（中文）' : language === 'en' ? '（English）' : ''
      const concHint = concurrency > 1 ? `（并发 ${concurrency}）` : ''
      const modeLabel = analysisMode.value === 'deep' ? '深入分析' : '快速分析'
      const modeHint = agentic ? `（${modeLabel}` : ''
      const turnHint = agentic && maxTurns !== 30 ? `，轮次 ${maxTurns}` : ''
      const modelHint = agentic && summaryModel ? `，摘要模型 ${summaryModel}` : ''
      const subConcHint = agentic && subagentConcurrency > 1 ? `，摘要并发 ${subagentConcurrency}` : ''
      const forceHint = force ? '，强制覆盖' : '（跳过已分析）'
      const extraHint = modeHint + turnHint + modelHint + subConcHint + (modeHint ? '）' : '')
      addMessage('system', `已提交 ${selectedComps.length} 个组件的批量分析任务${extraHint}${langHint}${concHint}${forceHint}，请到「任务」面板查看进度。`)
      // 退出选择模式（自动清空已选）
      if (selectionStore.selecting) selectionStore.toggleSelecting()
      if (taskId) {
        communityStore.triggerComponentAnalysis(taskId, selectedComps, language, concurrency, agentic, maxTurns, summaryModel, subagentConcurrency, analysisMode.value, force)
          .catch(e => addMessage('error', String(e)))
      }
      return
    }
    // ── 预摘要命令 ──
    // /presummary — 查看文件分级概况
    const psStatusRe = /^\/presummary$/
    if (psStatusRe.test(text)) {
      addMessage('user', text)
      userInput.value = ''
      const taskId = resolveTaskId()
      if (!taskId) { addMessage('system', '未找到激活的任务。'); return }
      try {
        const status = await communityStore.getPreSummaryStatus(taskId)
        let msg = `## 文件预摘要 — 项目缓存\n`
        msg += `- 总计: ${status.total_files} 文件, 已缓存: ${status.cached_count}\n`
        msg += `- **P0** (核心): ${status.counts.P0} 文件\n`
        msg += `- **P1** (重要): ${status.counts.P1} 文件\n`
        msg += `- **P2** (普通): ${status.counts.P2} 文件 (不预摘要)\n\n`
        msg += `可用命令:\n- \`/presummary files P0\` 查看 P0 文件列表\n`
        msg += `- \`/presummary start P0 -n 5\` 启动预摘要 P0 批次 (限 5 个)`
        addMessage('assistant', msg)
      } catch (e: any) {
        addMessage('system', `查询失败: ${e.message || e}`)
      }
      return
    }
    // /presummary files <batch> [page]
    const psFilesRe = /^\/presummary\s+files\s+(P[012])(?:\s+(\d+))?/i
    const psFilesMatch = text.match(psFilesRe)
    if (psFilesMatch) {
      addMessage('user', text)
      userInput.value = ''
      const taskId = resolveTaskId()
      if (!taskId) { addMessage('system', '未找到激活的任务。'); return }
      const batch = psFilesMatch[1].toUpperCase()
      const page = parseInt(psFilesMatch[2] || '1')
      try {
        const result = await communityStore.listPreSummaryFiles(taskId, batch, page, 20)
        let msg = `## ${batch} 批次文件 (共 ${result.total} 个)\n`
        for (const f of result.files) {
          msg += `- \`${f.file_path}\` score=${f.score} cross=${f.cross} edges=${f.edges} size=${f.size}\n`
        }
        if (result.page * result.page_size < result.total) {
          msg += `\n下一页: /presummary files ${batch} ${page + 1}`
        }
        addMessage('assistant', msg)
      } catch (e: any) {
        addMessage('system', `查询失败: ${e.message || e}`)
      }
      return
    }
    // /presummary start <batch> [-n N] [-j N]
    // batch: P0 / P0,P1 / P0, P1, P2 / all
    const psStartRe = /^\/presummary\s+start\s+(P[012](?:\s*,\s*P[012])*|ALL|all)\s*(.*)$/i
    const psStartMatch = text.match(psStartRe)
    if (psStartMatch) {
      addMessage('user', text)
      userInput.value = ''
      const taskId = resolveTaskId()
      if (!taskId) { addMessage('system', '未找到激活的任务。'); return }

      const batchRaw = psStartMatch[1]
      const rest = psStartMatch[2]
      // 校验 rest 中是否有不认识的 - 前缀参数
      const restTokens = rest.match(/-[a-z]\s+\S+/gi) || []
      const unknownRest = restTokens.filter(t => !/^-(n|j)\s+\d+$/i.test(t.trim()))
      if (unknownRest.length > 0) {
        addMessage('system', `未知参数: ${unknownRest.join('、')}。可用: -n N（限文件数）, -j N（并发数）`)
        return
      }
      const limit = parseInt(rest.match(/-n\s+(\d+)/i)?.[1] || '0')
      const rawConc = parseInt(rest.match(/-j\s+(\d+)/i)?.[1] || '1')
      const subagentConcurrency = Math.max(1, Math.min(10, rawConc))

      // 解析批次列表
      let batches: string[]
      if (batchRaw.toUpperCase() === 'ALL') {
        batches = ['P0', 'P1', 'P2']
      } else {
        batches = batchRaw.split(',').map(b => b.trim().toUpperCase())
      }

      if (batches.length > 1) {
        // 多批次：调用社区 store 统一入口，与单批次路径一致
        communityStore.startPreSummaryPipeline(taskId, batches, limit, subagentConcurrency)
          .then((r: any) => {
            addMessage('system', `预摘要已启动 (${batches.join(' → ')}，共 ${batches.length} 批次)。请到「解析任务」面板查看进度。`)
          })
          .catch((e: any) => {
            addMessage('system', `启动失败: ${e.message || e}`)
          })
      } else {
        // 单批次，走原有逻辑
        communityStore.startPreSummary(taskId, batches[0], limit, subagentConcurrency)
          .then((result: any) => {
            if (result.allCached) {
              addMessage('system', `预摘要 ${batches[0]} 跳过: 全部 ${result.fileCount} 个文件已缓存，无需处理`)
            } else if (result.success && result.agentTaskId) {
              addMessage('system', `预摘要 ${batches[0]} 已启动 (${result.fileCount} 文件${subagentConcurrency > 1 ? `，并发 ${subagentConcurrency}` : ''})。请到「解析任务」面板查看进度。`)
            } else {
              addMessage('system', `启动失败: ${result.error || '未知错误'}`)
            }
          })
          .catch((e: any) => {
            addMessage('system', `启动失败: ${e.message || e}`)
          })
      }
      return
    }
    // /presummary get <file_path>
    const psGetRe = /^\/presummary\s+get\s+(.+)$/i
    const psGetMatch = text.match(psGetRe)
    if (psGetMatch) {
      addMessage('user', text)
      userInput.value = ''
      const taskId = resolveTaskId()
      if (!taskId) { addMessage('system', '未找到激活的任务。'); return }
      const filePath = psGetMatch[1].trim()
      try {
        const detail = await communityStore.getFileSummary(taskId, filePath)
        if (detail.found) {
          let msg = `## 文件摘要 — ${filePath}\n`
          msg += `- 缓存时间: ${detail.created_at || '?'}\n`
          msg += `- 长度: ${detail.summary_len} 字符\n`
          msg += `\`\`\`\n${(detail.summary || '').slice(0, 1000)}\n\`\`\``
          addMessage('assistant', msg)
        } else {
          addMessage('system', `未找到 ${filePath} 的摘要缓存。可用 /presummary start 启动预摘要。`)
        }
      } catch (e: any) {
        addMessage('system', `查询失败: ${e.message || e}`)
      }
      return
    }
    // /presummary delete <file_path>
    const psDeleteRe = /^\/presummary\s+delete\s+(.+)$/i
    const psDeleteMatch = text.match(psDeleteRe)
    if (psDeleteMatch) {
      addMessage('user', text)
      userInput.value = ''
      const taskId = resolveTaskId()
      if (!taskId) { addMessage('system', '未找到激活的任务。'); return }
      const filePath = psDeleteMatch[1].trim()
      try {
        const result = await communityStore.deleteFileSummary(taskId, filePath)
        addMessage('system', `已删除 ${filePath} 的摘要缓存 (${result.deleted || 0} 条)。`)
      } catch (e: any) {
        addMessage('system', `删除失败: ${e.message || e}`)
      }
      return
    }
    // /presummary rerun <file_path>
    const psRerunRe = /^\/presummary\s+rerun\s+(.+)$/i
    const psRerunMatch = text.match(psRerunRe)
    if (psRerunMatch) {
      addMessage('user', text)
      userInput.value = ''
      const taskId = resolveTaskId()
      if (!taskId) { addMessage('system', '未找到激活的任务。'); return }
      const filePath = psRerunMatch[1].trim()
      try {
        const result = await communityStore.rerunFileSummary(taskId, filePath)
        if (result.success && result.agentTaskId) {
          addMessage('system', `重摘要任务已启动。请到「解析任务」面板查看进度。`)
        } else {
          addMessage('system', `启动失败`)
        }
      } catch (e: any) {
        addMessage('system', `启动失败: ${e.message || e}`)
      }
      return
    }
    // 未识别的 /presummary 子命令 → 显示提示
    if (/^\/presummary\s+.+/i.test(text)) {
      addMessage('user', text)
      userInput.value = ''
      addMessage('system',
        '未识别的 /presummary 命令。可用命令:\n'
        + '- `/presummary` 查看概况\n'
        + '- `/presummary files P0/P1/P2 [页码]` 查看文件列表\n'
        + '- `/presummary start P0/P1/P2 (-n N)` 启动预摘要\n'
        + '- `/presummary get/delete/rerun <文件路径>` 操作单文件')
      return
    }
    if (/^\/help$/i.test(text) || text === '/帮助') {
      addMessage('user', text)
      userInput.value = ''
      addMessage('assistant', HELP_TEXT)
      return
    }
    const parsed = communityStore.parseArchCommand(text)
    if (parsed) {
      showCmdConfirm.value = true
      cmdConfirmData.value = { text, action: parsed.action, args: parsed.args }
      return
    }
    // /arch/analyze/track/diff 命令解析失败 → 提示参数错误
    if (/^\/(arch|analyze|track|diff)\s/.test(text)) {
      addMessage('user', text)
      userInput.value = ''
      addMessage('system', '命令参数无法识别。可用参数: /arch all --level L0, /track --tag <名称>, /diff --from <v1> --to <v2>。详情输入 /help 查看。')
      return
    }
  }

  addMessage('user', text)
  userInput.value = ''
  streaming.value = true

  const assistantMsg = addMessage('assistant', '')

  // 构建发送消息：system prompts + 对话历史（不含 system）
  const sendMessages: Array<{ role: string; content: string }> = []
  const gs = cmdStore.graphState
  if (gs.nodeCount > 0) {
    sendMessages.push({ role: 'system', content: `当前图状态:\n${JSON.stringify(gs, null, 0)}` })
  }
  const selCtx = selectionStore.getContextForAI()
  if (selCtx) {
    sendMessages.push({ role: 'system', content: selCtx })
  }
  if (guideMode.value) {
    sendMessages.push({ role: 'system', content: GUIDE_SYSTEM_PROMPT })
  } else if (gs.nodeCount > 0) {
    sendMessages.push({ role: 'system', content: DEFAULT_SYSTEM_PROMPT })
  }
  // 对话历史（不含已有 system 消息）
  const history = messages.value.filter(m => m.role !== 'system' && m !== assistantMsg).map(m => ({ role: m.role, content: m.content }))
  sendMessages.push(...history)

  try {
    let rawContent = ''
    const fullContent = await chat({
      messages: sendMessages,
      onChunk(chunk: string) {
        assistantMsg.content += chunk
        rawContent += chunk
        scrollToBottom()
      },
    })

    // 流式完成后：
    // 1. 移除标签 → 纯净展示文本
    const displayContent = stripCommandTags(fullContent || assistantMsg.content)
    assistantMsg.content = displayContent

    // 2. 解析 [CMD:] → 串行执行命令
    const cmds = parseCommandTag(fullContent || rawContent)
    if (cmds.length > 0) {
      for (const cmd of cmds) {
        await cmdStore.executeCommand({ type: cmd.type, ...cmd.args } as any)
      }
    }

    // 3. 解析 [SUGGEST:] → 渲染为可点击芯片
    const suggs = parseSuggestTags(fullContent || rawContent)
    if (suggs.length > 0) {
      assistantMsg.suggestions = suggs
    }

    // 4. 解析 [CONFIRM:] → 渲染确认卡片
    const conf = parseConfirmTag(fullContent || rawContent)
    if (conf) {
      showCmdConfirm.value = true
      cmdConfirmData.value = {
        text: conf.cmd,
        action: conf.communities ? 'analyze' : 'diff',
        args: { all: 'true', level: 'L0' },
        confirmMeta: { communities: conf.communities, time: conf.time, tokens: conf.tokens, cost: conf.cost },
      }
    }

    assistantMsg.isStreaming = false
  } catch (err: any) {
    assistantMsg.content = err.message || '请求失败'
    assistantMsg.role = 'error'
    assistantMsg.isStreaming = false
  } finally {
    streaming.value = false
    scrollToBottom()
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (showSuggestions.value) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      suggestionIndex.value = suggestionIndex.value < suggestions.value.length - 1 ? suggestionIndex.value + 1 : 0
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      suggestionIndex.value = suggestionIndex.value > 0 ? suggestionIndex.value - 1 : suggestions.value.length - 1
      return
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (suggestionIndex.value >= 0) {
        applySuggestion(suggestionIndex.value)
        return
      }
    }
    if (e.key === 'Escape') {
      showSuggestions.value = false
      suggestionIndex.value = -1
      return
    }
  }
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function clearChat() {
  const key = sessionKey.value
  if (key) chatSession.clearSession(key)
  messages.value = []
}

onMounted(() => {
  if (llmConfigured.value) {
    const key = sessionKey.value
    if (key) {
      const saved = chatSession.loadSession(key)
      if (saved.length > 0) {
        messages.value = saved as Message[]
      }
    }
    if (messages.value.length === 0) {
      addMessage('system', t('ai.assistantWelcome'))
      addMessage('system', '输入 /help 或 /帮助 查看全部可用命令和模式')
    }
  }
})

// 监听 GraphCommandStore 事件 — 响应用户在图上的操作
watch(() => cmdStore.eventSeq, () => {
  const ev = cmdStore.popEvent()
  if (!ev) return
  if (ev.type === 'guide-start') {
    startGuide()
  }
  if (ev.type === 'drill-event') {
    const commId = ev.data.communityId as string
    if (commId && guideMode.value) {
      addMessage('system', `用户双击了社区: ${commId}`)
    }
  }
})
</script>

<template>
  <div class="ai-assistant-panel">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 未配置状态 -->
    <div
      v-if="!llmConfigured"
      class="ai-empty-state"
    >
      <SparklesIcon class="w-10 h-10 text-accent" />
      <div class="ai-empty-title">
        {{ t('ai.assistantTitle') }}
      </div>
      <div class="ai-empty-desc">
        {{ t('ai.assistantNotConfigured') }}
      </div>
      <router-link
        to="/user#llm"
        class="ai-config-link"
      >
        {{ t('ai.goConfigure') }}
      </router-link>
    </div>

    <!-- 对话区域 -->
    <template v-else>
      <!-- 消息列表 -->
      <div
        ref="scrollRef"
        class="ai-messages"
      >
        <div
          v-if="hasMoreMessages"
          class="ai-messages-more"
          @click="showMoreMessages"
        >
          显示更早消息 ({{ messages.length - messagePageSize }} 条)
        </div>
        <div
          v-for="msg in displayedMessages"
          :key="msg.id"
          :class="['ai-message', `ai-message-${msg.role}`]"
        >
          <div
            class="ai-message-bubble"
            v-html="formatMessageContent(msg)"
          />
          <!-- Suggestion Chips -->
          <div
            v-if="msg.suggestions && msg.suggestions.length > 0 && !msg.isStreaming"
            class="ai-suggest-chips"
          >
            <button
              v-for="(sug, si) in msg.suggestions"
              :key="si"
              class="ai-suggest-chip"
              @click="userInput = sug.command; handleSend()"
            >
              {{ sug.label }}
            </button>
          </div>
        </div>
      </div>

      <!-- /cmd 确认卡片 -->
      <div
        v-if="showCmdConfirm"
        class="ai-cmd-confirm"
      >
        <div class="ai-cmd-title">
          🔧 即将执行指令
        </div>
        <code class="ai-cmd-text">{{ cmdConfirmData.text }}</code>
        <div class="ai-cmd-args">
          <span
            v-for="(v, k) in cmdConfirmData.args"
            :key="k"
            class="ai-cmd-arg"
          >--{{ k }} {{ v }}</span>
        </div>
        <!-- 成本预估（解析自 [CONFIRM:] 标签） -->
        <div
          v-if="cmdConfirmData.confirmMeta"
          class="ai-cmd-meta"
        >
          <span v-if="cmdConfirmData.confirmMeta.communities">📊 {{ cmdConfirmData.confirmMeta.communities }} 个社区</span>
          <span v-if="cmdConfirmData.confirmMeta.time">⏱ {{ cmdConfirmData.confirmMeta.time }}</span>
          <span v-if="cmdConfirmData.confirmMeta.tokens">💬 {{ cmdConfirmData.confirmMeta.tokens }}</span>
          <span v-if="cmdConfirmData.confirmMeta.cost">💰 {{ cmdConfirmData.confirmMeta.cost }}</span>
        </div>
        <div class="ai-cmd-actions">
          <button
            class="ai-cmd-btn primary"
            @click="handleCmdConfirm"
          >
            确认执行
          </button>
          <button
            class="ai-cmd-btn"
            @click="showCmdConfirm = false"
          >
            取消
          </button>
        </div>
      </div>

      <!-- 组件引用区 -->
      <div
        v-if="selectionStore.selectedCount > 0"
        class="ai-selection-refs"
      >
        <span class="ai-selection-label">📎 {{ selectionStore.selectedCount }}个</span>
        <div class="ai-selection-chips">
          <span
            v-for="ref in selectionStore.selectedList.slice(0, 20)"
            :key="ref.id"
            class="ai-selection-chip"
            :title="`${ref.type === 'community' ? '社区' : '外部包'}: ${ref.id}`"
          >
            <span class="ai-selection-chip-type">{{ ref.type === 'community' ? '▣' : '▨' }}</span>
            <span class="ai-selection-chip-name">{{ ref.name }}</span>
            <button
              class="ai-selection-chip-remove"
              title="移除引用"
              @click="selectionStore.deselect(ref.id)"
            >×</button>
          </span>
          <span
            v-if="selectionStore.selectedCount > 20"
            class="ai-selection-more"
          >+{{ selectionStore.selectedCount - 20 }}...</span>
        </div>
        <button
          class="ai-selection-clear"
          @click="selectionStore.clearAll()"
        >
          清空
        </button>
      </div>

      <!-- 输入区 -->
      <div class="ai-input-area">
        <textarea
          v-model="userInput"
          class="ai-textarea"
          :placeholder="streaming ? t('ai.typing') : t('ai.inputPlaceholder')"
          :disabled="streaming"
          rows="2"
          @keydown="handleKeydown"
        />
        <!-- 指令联想 -->
        <div
          v-if="showSuggestions"
          class="ai-suggest-dropdown"
        >
          <div
            v-for="(cmd, i) in suggestions"
            :key="cmd"
            class="ai-suggest-item"
            :class="{ 'ai-suggest-item-active': i === suggestionIndex }"
            @click="applySuggestion(i)"
            @mouseenter="suggestionIndex = i"
          >
            <span class="ai-suggest-cmd">{{ cmd }}</span>
          </div>
        </div>
          <div class="ai-input-actions">
            <div class="ai-actions-left">
              <button
                class="ai-action-btn"
                :class="{ 'ai-btn-hidden': messages.length === 0 }"
                :title="t('ai.clearChat')"
                @click="clearChat"
              >
                <TrashIcon class="w-4 h-4" />
              </button>
              <button
                class="ai-action-btn"
                :class="{ 'ai-select-active': selectionStore.selecting }"
                :title="selectionStore.selecting ? '退出组件选择模式' : '选择组件'"
                @click="selectionStore.toggleSelecting()"
              >
                <CursorArrowRippleIcon class="w-4 h-4" />
              </button>
              <button
                class="ai-mode-btn"
                :class="{ 'ai-mode-deep': analysisMode === 'deep', 'ai-mode-quick': analysisMode === 'quick' }"
                :title="analysisMode === 'deep' ? '当前: 深入分析 (点击切换为快速)' : '当前: 快速分析 (点击切换为深入)'"
                @click="toggleAnalysisMode"
              >
                <span v-if="analysisMode === 'quick'" class="w-3.5 h-3.5 text-center">⚡</span>
                <SparklesIcon v-else class="w-3.5 h-3.5" />
                <span class="ai-mode-label">{{ analysisMode === 'deep' ? '深入' : '快速' }}</span>
              </button>
            </div>
            <button
              class="ai-send-btn"
              :disabled="!userInput.trim() || streaming"
              @click="handleSend"
            >
              <PaperAirplaneIcon class="w-4 h-4" />
            </button>
          </div>

      </div>
    </template>
  </div>
</template>

<style scoped>
.ai-assistant-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.ai-empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px 16px;
  text-align: center;
}

.ai-empty-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.ai-empty-desc {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}

.ai-config-link {
  font-size: 11px;
  color: var(--accent);
  text-decoration: underline;
  cursor: pointer;
  margin-top: 4px;
}

.ai-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ai-message {
  display: flex;
}

.ai-message-user {
  justify-content: flex-end;
}

.ai-message-assistant,
.ai-message-system {
  justify-content: flex-start;
}

.ai-message-error {
  justify-content: flex-start;
}

.ai-message-bubble {
  max-width: 90%;
  padding: 8px 12px;
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.6;
  word-break: break-word;
}

.ai-message-user .ai-message-bubble {
  background: var(--accent);
  color: white;
  border-bottom-right-radius: 2px;
}

.ai-message-assistant .ai-message-bubble {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-bottom-left-radius: 2px;
}

.ai-messages-more {
  text-align: center;
  padding: 6px;
  font-size: 11px;
  color: var(--accent);
  cursor: pointer;
}
.ai-messages-more:hover {
  text-decoration: underline;
}

.ai-message-system .ai-message-bubble {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
  font-size: 11px;
}

.ai-message-error .ai-message-bubble {
  background: color-mix(in srgb, #ef4444 10%, transparent);
  border: 1px solid color-mix(in srgb, #ef4444 30%, transparent);
  color: #fca5a5;
}

/* ---- 指令联想下拉 ---- */
.ai-suggest-dropdown {
  position: absolute;
  bottom: 100%;
  left: 0;
  right: 0;
  margin: 0 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: 0 -4px 12px rgba(0,0,0,0.15);
  overflow: hidden;
  z-index: 10;
}
.ai-suggest-item {
  padding: 6px 12px;
  font-size: 12px;
  cursor: pointer;
  color: var(--text-primary);
  transition: background 0.1s;
}
.ai-suggest-item:hover,
.ai-suggest-item-active {
  background: var(--bg-accent-subtle, #2d1f5e);
  color: var(--accent);
}
.ai-suggest-cmd {
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
}

.ai-input-area {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border-top: 1px solid var(--border);
  background: var(--bg-secondary);
}

.ai-textarea {
  width: 100%;
  resize: none;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 12px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s;
}

.ai-textarea:focus {
  border-color: var(--accent);
}

.ai-textarea:disabled {
  opacity: 0.5;
}

.ai-input-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 8px;
}
.ai-actions-left {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-right: auto;
}

.ai-action-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  cursor: pointer;
  color: var(--text-muted);
  background: transparent;
  border: none;
  transition: background 0.15s, color 0.15s;
}

.ai-action-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.ai-btn-hidden {
  visibility: hidden;
  pointer-events: none;
}

.ai-send-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  cursor: pointer;
  background: var(--accent);
  color: white;
  border: none;
  transition: opacity 0.15s;
}

.ai-send-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.ai-mode-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--bg-secondary);
  color: var(--text-muted);
  cursor: pointer;
  font-size: 10px;
  transition: all 0.15s;
  white-space: nowrap;
  height: 22px;
}
.ai-mode-btn:hover {
  border-color: var(--accent);
  color: var(--text-primary);
}
.ai-mode-quick {
  border-color: var(--border);
  color: var(--text-muted);
}
.ai-mode-deep {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  color: var(--accent);
}
.ai-mode-label {
  font-weight: 500;
}



.ai-cmd-confirm {
  margin: 0 12px 8px; padding: 0.5rem 0.75rem;
  background: var(--bg-accent-subtle, #2d1f5e); border: 1px solid var(--accent, #7c3aed);
  border-radius: 0.375rem;
}
.ai-cmd-title { font-size: 0.75rem; font-weight: 600; color: var(--accent, #7c3aed); margin-bottom: 0.25rem; }
.ai-cmd-text { display: block; font-size: 0.7rem; color: var(--text-primary); background: var(--bg-primary); padding: 0.2rem 0.4rem; border-radius: 0.2rem; margin-bottom: 0.25rem; font-family: var(--font-mono); }
.ai-cmd-args { display: flex; flex-wrap: wrap; gap: 0.25rem; margin-bottom: 0.35rem; }
.ai-cmd-arg { font-size: 0.6rem; color: var(--text-muted); background: var(--bg-secondary); padding: 0.05rem 0.3rem; border-radius: 0.15rem; }
.ai-cmd-actions { display: flex; gap: 0.35rem; }
.ai-cmd-btn { padding: 0.15rem 0.5rem; font-size: 0.7rem; border: 1px solid var(--border); border-radius: 0.25rem; background: var(--bg-secondary); color: var(--text-muted); cursor: pointer; }
.ai-cmd-btn:hover { border-color: var(--accent); color: var(--text-primary); }
.ai-cmd-btn.primary { background: var(--accent, #7c3aed); color: #fff; border-color: var(--accent); }

.ai-cmd-meta {
  display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.35rem;
}
.ai-cmd-meta span {
  font-size: 0.6rem; color: var(--text-muted);
}

.ai-suggest-chips {
  display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px;
}
.ai-suggest-chip {
  padding: 2px 8px; font-size: 10px; border: 1px solid var(--accent);
  border-radius: 10px; background: transparent; color: var(--accent);
  cursor: pointer; transition: all 0.15s;
}
.ai-suggest-chip:hover {
  background: var(--accent); color: #fff;
}

/* ---- 助手消息内 Markdown 渲染样式 ---- */
.ai-message-assistant .ai-message-bubble :deep(h1),
.ai-message-assistant .ai-message-bubble :deep(h2),
.ai-message-assistant .ai-message-bubble :deep(h3),
.ai-message-assistant .ai-message-bubble :deep(h4) {
  margin: 0.6em 0 0.3em; font-weight: 600; line-height: 1.3;
  color: var(--text-primary);
}
.ai-message-assistant .ai-message-bubble :deep(h1) { font-size: 1.1em; }
.ai-message-assistant .ai-message-bubble :deep(h2) { font-size: 1.05em; border-bottom: 1px solid var(--border); padding-bottom: 0.15em; }
.ai-message-assistant .ai-message-bubble :deep(h3) { font-size: 1em; }
.ai-message-assistant .ai-message-bubble :deep(h4) { font-size: 0.95em; }

.ai-message-assistant .ai-message-bubble :deep(p) {
  margin: 0.3em 0;
}

.ai-message-assistant .ai-message-bubble :deep(ul),
.ai-message-assistant .ai-message-bubble :deep(ol) {
  margin: 0.3em 0; padding-left: 1.3em;
}
.ai-message-assistant .ai-message-bubble :deep(li) { margin: 0.1em 0; }

.ai-message-assistant .ai-message-bubble :deep(code) {
  font-family: var(--font-mono, 'JetBrains Mono', monospace);
  font-size: 0.85em;
  background: var(--bg-tertiary);
  padding: 0.1em 0.3em; border-radius: 3px;
}
.ai-message-assistant .ai-message-bubble :deep(pre) {
  background: var(--bg-tertiary); border: 1px solid var(--border);
  border-radius: 4px; padding: 0.5em 0.7em; overflow-x: auto;
  margin: 0.4em 0; line-height: 1.4;
}
.ai-message-assistant .ai-message-bubble :deep(pre code) {
  background: none; padding: 0; font-size: 0.8em;
}

.ai-message-assistant .ai-message-bubble :deep(table) {
  border-collapse: collapse; width: 100%; margin: 0.4em 0; font-size: 0.85em;
}
.ai-message-assistant .ai-message-bubble :deep(th),
.ai-message-assistant .ai-message-bubble :deep(td) {
  border: 1px solid var(--border); padding: 0.25em 0.5em; text-align: left;
}
.ai-message-assistant .ai-message-bubble :deep(th) {
  background: var(--bg-tertiary); font-weight: 600;
}
.ai-message-assistant .ai-message-bubble :deep(tr:nth-child(even)) {
  background: var(--bg-secondary);
}

.ai-message-assistant .ai-message-bubble :deep(blockquote) {
  border-left: 3px solid var(--accent); margin: 0.4em 0; padding: 0.2em 0.6em;
  color: var(--text-muted); background: color-mix(in srgb, var(--accent) 5%, transparent);
  border-radius: 0 4px 4px 0;
}

.ai-message-assistant .ai-message-bubble :deep(a) {
  color: var(--accent); text-decoration: underline;
}

.ai-message-assistant .ai-message-bubble :deep(hr) {
  border: none; border-top: 1px solid var(--border); margin: 0.6em 0;
}

.ai-message-assistant .ai-message-bubble :deep(strong) {
  font-weight: 600; color: var(--text-primary);
}

.ai-message-assistant .ai-message-bubble :deep(em) {
  font-style: italic;
}

/* ---- 组件选择引用区 ---- */
.ai-selection-refs {
  margin: 0 12px 4px;
  padding: 0.35rem 0.5rem;
  background: var(--bg-secondary);
  border: 1px dashed var(--accent);
  border-radius: 0.375rem;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 0.2rem;
}
.ai-selection-label {
  font-size: 0.65rem;
  color: var(--text-muted);
  flex-shrink: 0;
  white-space: nowrap;
}
.ai-selection-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.2rem;
  min-width: 0;
  flex: 1;
  max-height: 4.2rem;
  overflow-y: auto;
}
.ai-selection-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.15rem;
  padding: 0.05rem 0.2rem 0.05rem 0.3rem;
  background: var(--bg-accent-subtle, #2d1f5e);
  border: 1px solid var(--accent);
  border-radius: 0.25rem;
  font-size: 0.65rem;
  line-height: 1.3;
  flex-shrink: 0;
}
.ai-selection-chip-type {
  color: var(--accent);
  font-size: 0.6rem;
}
.ai-selection-chip-name {
  color: var(--text-primary);
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ai-selection-chip-remove {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 0.75rem;
  cursor: pointer;
  padding: 0 0.1rem;
  line-height: 1;
}
.ai-selection-chip-remove:hover {
  color: var(--accent);
}
.ai-selection-clear {
  background: none;
  border: none;
  color: var(--text-muted);
  font-size: 0.6rem;
  cursor: pointer;
  padding: 0;
  flex-shrink: 0;
  white-space: nowrap;
}
.ai-selection-clear:hover {
  color: var(--accent);
}
.ai-selection-more {
  font-size: 0.6rem;
  color: var(--text-muted);
  padding: 0.05rem 0.2rem;
  flex-shrink: 0;
  align-self: center;
}
.ai-select-active {
  color: var(--accent);
  background: var(--bg-accent-subtle, #2d1f5e);
  border-color: var(--accent);
}
</style>
