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
  CursorArrowRippleIcon,
} from '@heroicons/vue/24/outline'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import { useSettingsStore } from '@/stores/settings-store'
import { useProjectStore } from '@/stores/project'
import { useAnalysisStore } from '@/stores/analysis'
import { useCommunityStore, type CommunityItem, pipelineSummary } from '@/stores/community-store'
import { useNavigationStore } from '@/stores/navigation'
import { isLLMConfigured, chat } from '@/services/llmClient'
import { useComponentSelectionStore } from '@/stores/component-selection-store'
import { useChatSession, type SessionPage } from '@/stores/chat-session-store'
import { useComponentId } from '@/composables/useComponentId'
import { ipc } from '@/services/ipc'

const { showId, componentId } = useComponentId('SH-004')
const { t } = useI18n()
const settingsStore = useSettingsStore()
const projectStore = useProjectStore()
const communityStore = useCommunityStore()
const navigationStore = useNavigationStore()
const selectionStore = useComponentSelectionStore()
const chatSession = useChatSession()

const DEFAULT_SYSTEM_PROMPT = [
  '你是 TopoCode 使用助手，仅回答关于 TopoCode 软件功能和使用方法的问题。',
  '用户可输入 /help 或 /帮助 查看全部可用命令和完整使用指南。',
  '对于用户关于所分析项目的架构/代码/设计等具体研究问题，请回复：',
  '> 这个问题需要结合您的项目上下文进行深入分析，',
  '> 请通过 **Web AI 助手** 进行探讨：',
  '> http://localhost:3456/chat',
  '',
  '对话使用中文回复。保持简洁。',
].join('\n')

const HELP_TEXT = [
  '## 可用命令',
  '',
  '### 对话指令（直接输入）',
  '| 指令 | 说明 |',
  '|------|------|',
  '| `/help` / `/帮助` | 显示本帮助 |',
  '| `/select [--all/--include/--call/--l0~/--l5/--clear/--unanalyzed]` | 无参数时切换选择模式；`--all` 全选所有社区；`--include`/`--call`/`--l0`~/`--l5` 按条件自动选取；`--clear` 清除已选；`--unanalyzed` 只选未分析组件 |',
  '| `/presummary [-j N] [--force]` | 文件预摘要（Agent 模式），按 P0→P1→P2 顺序执行。`--force` 强制覆盖已有缓存。`-j N` 并发数 1-5（默认 1） |',
  '| `/analyze [-j N] [--force] [-L zh/en]` | 组件分析（Agent 多轮模式），默认分析所有 L0~L5 组件。`--force` 强制覆盖已分析组件。`-j N` 并发数 1-5（默认 1） |',
  '| `/overview [--force] [-L zh/en]` | 生成整体架构概览文档。`--force` 强制覆盖已生成内容。不支持 -j 参数 |',
  '| `/pipeline [-j N] [--force] [-L zh/en]` | 流水线整体激活。顺序执行：项目摘要 → 预摘要(P0→P1→P2) → 组件分析(L0→L5) → 整体架构分析。`--force` 强制覆盖所有。`-j N` 并发数 1-5（默认 1）|',
  '',
  '### 模式',
  '- **自由对话**：输入 TopoCode 使用相关问题，AI 基于内置文档回复',
  '- **项目分析**：关于项目架构/代码的深入问题，请使用 **Web AI 助手** http://localhost:3456/chat',
  '- **组件选择模式**：输入 `/select` 或点击输入栏 📎 按钮切换。无参数时手动点选；支持 `/select --include --l0` 等参数自动选取。选中后输入 `/analyze` 启动分析',
  '- **流水线模式**：`/pipeline` 一键完成全部分析流程',
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
}

const messages = ref<Message[]>([])
const messagePageSize = ref(10)
const userInput = ref('')

/* ---- 指令联想 ---- */
const CMD_HISTORY_KEY = 'ai-command-history'
const USER_COMMANDS = ['/help', '/帮助', '/select', '/select --unanalyzed', '/select --l3',
  '/presummary', '/presummary --force',
  '/analyze', '/analyze --force', '/analyze_components', '/analyze_components --force',
  '/overview', '/overview --force',
  '/pipeline', '/pipeline --force']

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
  const filtered = messages.value.filter(m => m.content.length > 0 || m.isStreaming)
  const total = filtered.length
  if (total <= messagePageSize.value) return filtered
  return filtered.slice(total - messagePageSize.value)
})
const hasMoreMessages = computed(() => messages.value.length > messagePageSize.value)

function showMoreMessages() {
  messagePageSize.value += 10
}

const streaming = ref(false)
const scrollRef = ref<HTMLElement | null>(null)

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

// 监听流水线完成统计，注入汇总消息
watch(pipelineSummary, (summary) => {
  if (!summary) return
  const tid = resolveTaskId()
  if (!tid || summary.taskId !== tid) return

  const s = summary.stats
  const lines: string[] = [
    '📊 流水线执行完成',
    '──────────────────',
    `✅ 首次成功:     ${s.completed} 步`,
  ]
  if (s.retried_completed > 0) {
    lines.push(`⚠️ 重试后成功:   ${s.retried_completed} 步（累计重试 ${s.total_retries} 次）`)
  }
  if (s.failed > 0) {
    lines.push(`❌ 执行失败:     ${s.failed} 步（内容未写入）`)
    lines.push('')
    for (const fs of (s.step_details || [])) {
      if (fs.status !== 'failed') continue
      lines.push(`  • ${fs.description}`)
      if (fs.last_error) lines.push(`    → ${fs.last_error.slice(0, 80)}`)
      if (fs.retries_used > 0) lines.push(`    (重试 ${fs.retries_used} 次)`)
    }
  }
  lines.push('', '使用 /retry 命令重新执行（默认跳过成功任务，--force 强制覆盖）。')

  addMessage('system', lines.join('\n'))
  pipelineSummary.value = null  // 清除，避免重复
})

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

function _validateFlags(tokens: string[], validFlags: string[]): string[] {
  return tokens.filter(t => t.startsWith('-') && !validFlags.includes(t.toLowerCase()))
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
      const VALID_SELECT_FLAGS = ['--include','--call','--all','--clear','--l0','--l1','--l2','--l3','--l4','--l5','--unanalyzed']
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
      const levelFilters = [...args.matchAll(/--l(\d+)/gi)].map(m => 'L' + m[1])
      const wantAll = /--all/i.test(args)
      const wantUnanalyzed = /--unanalyzed/i.test(args)
      const matching = taskComs.filter(c => {
        if (wantUnanalyzed && c.status === 'completed') return false
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
      addMessage('system', `已选中 ${matching.length} 个组件。可输入 /analyze 启动批量分析，或点选加减组件后发送消息。`)
      return
    }
    // /analyze — 批量分析组件（Agent 多轮模式，默认全量 L0~L5）
    if (/^\/analyze(?:_components)?\b/i.test(text)) {
      const VALID_AC_FLAGS = ['--force', '-L', '-j', '--concurrency']
      const tokens = text.split(/\s+/).slice(1)
      const unknown = _validateFlags(tokens, VALID_AC_FLAGS)
      if (unknown.length > 0) {
        addMessage('user', text)
        userInput.value = ''
        addMessage('system', `未知参数: ${unknown.join('、')}。可用参数: ${VALID_AC_FLAGS.join(' ')}`)
        return
      }
      const force = text.includes('--force')
      const language = text.match(/-L\s+(zh|en)/i)?.[1] || ''
      const concurrency = Math.max(1, Math.min(5, parseInt(text.match(/(?:^|\s)(?:-j|--concurrency)\s+(\d+)/i)?.[1] || '1', 10)))
      const taskId = resolveTaskId()
      if (!taskId) { addMessage('system', '未找到激活的任务。'); return }

      // 获取组件：用户已选择或默认全量 L0~L5
      let selectedComps: any[] = []
      if (selectionStore.selectedCount > 0) {
        selectedComps = [...selectionStore.selectedList]
      } else {
        const taskComs = communityStore.tasks[taskId]?.communities || []
        selectedComps = taskComs.map(c => ({
          id: c.communityId, type: 'community' as const,
          name: c.name || c.communityId, taskId,
          edgeType: c.edgeType, level: c.level,
          metadata: { nodeCount: c.nodeCount, fileCount: c.fileCount, qualityScore: c.qualityScore ?? undefined },
        }))
      }
      if (selectedComps.length === 0) {
        addMessage('user', text)
        userInput.value = ''
        addMessage('system', '未找到组件。请先打开左侧结构图加载社区列表。')
        return
      }
      const MAX_COMPONENTS = 100
      if (selectedComps.length > MAX_COMPONENTS) selectedComps.length = MAX_COMPONENTS

      const compNames = selectedComps.slice(0, 5).map(r => r.name).join('、') + (selectedComps.length > 5 ? `等${selectedComps.length}个` : '')
      addMessage('user', text)
      userInput.value = ''
      const langHint = language === 'zh' ? '（中文）' : language === 'en' ? '（English）' : ''
      const forceHint = force ? '，强制覆盖' : '（跳过已分析）'
      addMessage('system', `已提交 ${selectedComps.length} 个组件的 Agent 多轮分析任务${langHint}${forceHint}${concurrency > 1 ? `（并发 ${concurrency}）` : ''}：${compNames}。请到「任务」面板查看进度。`)
      if (selectionStore.selecting) selectionStore.toggleSelecting()
      communityStore.triggerComponentAnalysis(taskId, selectedComps, language, concurrency, true, 30, '', concurrency, 'deep', force)
        .catch(e => addMessage('error', String(e)))
      return
    }
    // /presummary [-j N] [--force] — 预摘要 P0→P1→P2（Agent 模式）
    if (/^\/presummary\b/i.test(text)) {
      const VALID_PS_FLAGS = ['--force', '-j', '--concurrency']
      const tokens = text.split(/\s+/).slice(1)
      const unknown = _validateFlags(tokens, VALID_PS_FLAGS)
      const force = text.includes('--force')
      const concurrency = Math.max(1, Math.min(5, parseInt(text.match(/(?:^|\s)(?:-j|--concurrency)\s+(\d+)/i)?.[1] || '1', 10)))
      if (unknown.length > 0) {
        addMessage('user', text)
        userInput.value = ''
        addMessage('system', `未知参数: ${unknown.join('、')}。可用参数: -j N (并发1-5), --force`)
        return
      }
      addMessage('user', text)
      userInput.value = ''
      const taskId = resolveTaskId()
      if (!taskId) { addMessage('system', '未找到激活的任务。'); return }
      const hint = concurrency > 1 ? `（并发 ${concurrency}）` : ''
      addMessage('system', `预摘要 P0→P1→P2 已启动${hint}。请到「任务」面板查看进度。`)
      communityStore.startPreSummaryPipeline(taskId, ['P0', 'P1', 'P2'], 0, concurrency)
        .catch((e: any) => addMessage('system', `启动失败: ${e.message || e}`))
      return
    }
    if (/^\/help$/i.test(text) || text === '/帮助') {
      addMessage('user', text)
      userInput.value = ''
      addMessage('assistant', HELP_TEXT)
      return
    }
    // /overview — 生成整体架构概览
    if (/^\/overview\b/i.test(text)) {
      const VALID_OVERVIEW_FLAGS = ['--force', '-L']
      const tokens = text.split(/\s+/).slice(1)
      const unknown = _validateFlags(tokens, VALID_OVERVIEW_FLAGS)
      if (unknown.length > 0) {
        addMessage('user', text)
        userInput.value = ''
        addMessage('system', `未知参数: ${unknown.join('、')}。可用: --force, -L zh/en`)
        return
      }
      addMessage('user', text)
      userInput.value = ''
      const tid = resolveTaskId()
      if (!tid) { addMessage('system', '未找到激活的任务。'); return }
      addMessage('system', '架构概览生成任务已启动，请稍后查看结果...')
      communityStore.triggerOverview(tid, text.includes('--force'))
        .catch(e => addMessage('error', String(e)))
      return
    }
    // /pipeline [-j N] [--force] — 流水线整体激活
    if (/^\/pipeline\b/i.test(text)) {
      const VALID_PIPE_FLAGS = ['--force', '-L', '-j', '--concurrency']
      const tokens = text.split(/\s+/).slice(1)
      const unknown = _validateFlags(tokens, VALID_PIPE_FLAGS)
      if (unknown.length > 0) {
        addMessage('user', text)
        userInput.value = ''
        addMessage('system', `未知参数: ${unknown.join('、')}。可用: -j N (并发1-5), --force, -L zh/en`)
        return
      }
      const force = text.includes('--force')
      const language = text.match(/-L\s+(zh|en)/i)?.[1] || ''
      const concurrency = Math.max(1, Math.min(5, parseInt(text.match(/(?:^|\s)(?:-j|--concurrency)\s+(\d+)/i)?.[1] || '1', 10)))
      addMessage('user', text)
      userInput.value = ''
      const tid = resolveTaskId()
      if (!tid) { addMessage('system', '未找到激活的任务。'); return }
      const forceHint = force ? '（强制覆盖所有）' : '（跳过已完成）'
      const langHint = language === 'zh' ? '中文' : language === 'en' ? 'English' : ''
      const concHint = concurrency > 1 ? `（并发 ${concurrency}）` : ''
      addMessage('system', `流水线已启动${forceHint}${langHint ? ` | ${langHint}` : ''}${concHint}。顺序执行：项目摘要 → 预摘要 P0→P1→P2 → 组件分析 L0→L5 → 整体架构分析。请到「任务」面板查看进度。`)
      communityStore.startPipeline(tid, force, language, concurrency)
        .catch(e => addMessage('error', String(e)))
      return
    }
    if (/^\/retry\b/i.test(text)) {
      const force = text.includes('--force')
      addMessage('user', text)
      userInput.value = ''
      const tid = resolveTaskId()
      if (!tid) { addMessage('system', '未找到激活的任务。'); return }
      const hint = force ? '（强制覆盖所有）' : '（跳过成功步骤）'
      addMessage('system', `重新执行已启动${hint}。请到「任务」面板查看进度。`)
      communityStore.startPipeline(tid, force)
        .catch(e => addMessage('error', String(e)))
      return
    }
  }

  addMessage('user', text)
  userInput.value = ''
  streaming.value = true

  const assistantMsg = addMessage('assistant', '')

  // 构建发送消息：system prompts + 对话历史（不含 system）
  const sendMessages: Array<{ role: string; content: string }> = []
  sendMessages.push({ role: 'system', content: DEFAULT_SYSTEM_PROMPT })
  const selCtx = selectionStore.getContextForAI()
  if (selCtx) {
    sendMessages.push({ role: 'system', content: selCtx })
  }
  // 对话历史（不含已有 system 消息）
  const history = messages.value.filter(m => m.role !== 'system' && m !== assistantMsg).map(m => ({ role: m.role, content: m.content }))
  sendMessages.push(...history)

  try {
    await chat({
      messages: sendMessages,
      onChunk(chunk: string) {
        assistantMsg.content += chunk
        scrollToBottom()
      },
    })
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
