<script setup lang="ts">
/**
 * AI 助手面板 — 右侧栏 SH-004
 *
 * 管理当前项目分析报告的对话 session。
 * 支持自由提问和报告上下文相关的分析对话。
 */

import { ref, computed, nextTick, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PaperAirplaneIcon, SparklesIcon, TrashIcon,
  DocumentTextIcon, ClockIcon,
} from '@heroicons/vue/24/outline'
import { useSettingsStore } from '@/stores/settings-store'
import { useProjectStore } from '@/stores/project'
import { useAnalysisStore } from '@/stores/analysis'
import { useCommunityStore } from '@/stores/community-store'
import { isLLMConfigured, chat } from '@/services/llmClient'
import { useGraphCommandStore } from '@/stores/graph-command-store'
import { parseCommandTag, parseConfirmTag, parseSuggestTags, stripCommandTags } from '@/types/graph-commands'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('SH-004')
const { t } = useI18n()
const settingsStore = useSettingsStore()
const communityStore = useCommunityStore()
const cmdStore = useGraphCommandStore()

/* ---- 引导模式 vs 普通模式 ---- */
const guideMode = ref(false)

function startGuide() {
  guideMode.value = true
  clearChat()
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

interface Message {
  id: string
  role: 'user' | 'assistant' | 'error' | 'system'
  content: string
  timestamp: number
  isStreaming?: boolean
  suggestions?: Array<{ label: string; command: string; args?: Record<string, string> }>
}

const messages = ref<Message[]>([])
const userInput = ref('')
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

// Session management — bound to current analysis task
const activeTaskId = ref<string | null>(null)
const activeTaskName = ref<string>('')
const hasAnalysisContext = computed(() => !!activeTaskId.value)

function bindToTask(taskId: string | null, taskName: string = '') {
  activeTaskId.value = taskId
  activeTaskName.value = taskName
  if (taskId) {
    addMessage('system', t('ai.analysisSession', '当前分析会话: {name}', { name: taskName || taskId }))
  }
}

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
      communityStore.triggerArchAnalysis(activeTaskId.value, 'INCLUDE', cd.args.level || 'L0')
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
    const parsed = communityStore.parseArchCommand(text)
    if (parsed) {
      showCmdConfirm.value = true
      cmdConfirmData.value = { text, action: parsed.action, args: parsed.args }
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
  if (guideMode.value) {
    sendMessages.push({ role: 'system', content: GUIDE_SYSTEM_PROMPT })
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
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function clearChat() {
  messages.value = []
}

onMounted(() => {
  if (llmConfigured.value && messages.value.length === 0) {
    addMessage('system', t('ai.assistantWelcome'))
  }
})

watch(llmConfigured, (val) => {
  if (val && messages.value.length === 0) {
    addMessage('system', t('ai.assistantWelcome'))
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
          v-for="msg in messages"
          :key="msg.id"
          :class="['ai-message', `ai-message-${msg.role}`]"
        >
          <div
            class="ai-message-bubble"
            v-html="msg.content"
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
            >{{ sug.label }}</button>
          </div>
        </div>
      </div>

      <!-- /cmd 确认卡片 -->
      <div
        v-if="showCmdConfirm"
        class="ai-cmd-confirm"
      >
        <div class="ai-cmd-title">🔧 即将执行指令</div>
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
          >确认执行</button>
          <button
            class="ai-cmd-btn"
            @click="showCmdConfirm = false"
          >取消</button>
        </div>
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
        <div class="ai-input-actions">
          <button
            v-if="messages.length > 0"
            class="ai-action-btn"
            :title="t('ai.clearChat')"
            @click="clearChat"
          >
            <TrashIcon class="w-4 h-4" />
          </button>
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

.ai-input-area {
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
  justify-content: space-between;
  align-items: center;
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
</style>
