<script setup lang="ts">
/**
 * LLM 对话流 — 报告 Tab 底部
 *
 * - 查询结果以系统消息显示, 附带快捷解析按钮
 * - AI 解析结果附带保存按钮
 * - 底部输入区: 仅追问 + 发送
 */

import { ref, computed, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PaperAirplaneIcon,
  DocumentArrowDownIcon,
  SparklesIcon,
  XMarkIcon,
  TrashIcon,
} from '@heroicons/vue/24/outline'
import { llmWorker } from '@/workers/llm.worker.instance'
import { useSettingsStore } from '@/stores/settings'
import { isLLMConfigured } from '@/services/llmClient'
import {
  getDefaultTemplate,
  getTemplateById,
  renderPrompt,
  type ParseMode,
} from '@/services/promptTemplates'

const { t } = useI18n()
const settingsStore = useSettingsStore()

const props = defineProps<{
  taskId: string
  edgeType?: string
  selectedCommIds?: string[]
  graphData?: any
}>()

const emit = defineEmits<{
  'save-subdoc': [params: { commId: string; title: string; content: string; templateId: string }]
}>()

// ===== 对话消息 =====
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system' | 'error' | 'query_result'
  content: string
  timestamp: number
  isStreaming?: boolean
  templateId?: string
  meta?: Record<string, any>
  /** 快捷操作 (系统消息附带) */
  quickActions?: QuickAction[]
}

export interface QuickAction {
  label: string
  icon?: string
  action: 'parse_community' | 'parse_source' | 'save'
  templateId?: string
}

const messages = ref<ChatMessage[]>([])
const userInput = ref('')
const streaming = ref(false)

// 当前解析模式 (社区/源码)
const parseMode = ref<ParseMode>('community')
const selectedTemplateId = ref<string>('')

// ===== 添加查询结果消息 =====
function addQueryResultMessage(params: { selectedIds: string[]; stats: any }) {
  const statsText = [
    `📊 **查询结果**`,
    ``,
    `- 选中社区: ${params.selectedIds.length} 个`,
    `- 社区数: ${params.stats?.communityCount || 0}`,
    `- 节点数: ${params.stats?.nodeCount || 0}`,
    `- 边数: ${params.stats?.edgeCount || 0}`,
  ].join('\n')

  const defaultTpl = getDefaultTemplate('community')

  const quickActions: QuickAction[] = [
    {
      label: 'AI分析',
      action: 'parse_community',
      templateId: defaultTpl?.id,
    },
  ]

  addMessage('query_result', statsText, { stats: params.stats }, quickActions)
}

// ===== 添加消息 =====
function addMessage(role: ChatMessage['role'], content: string, meta?: Record<string, any>, quickActions?: QuickAction[]) {
  messages.value.push({
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    role,
    content,
    timestamp: Date.now(),
    meta,
    quickActions,
  })
  scrollToBottom()
}

// ===== 滚动到底部 =====
async function scrollToBottom() {
  await nextTick()
  const container = document.querySelector('.chat-flow-messages') as HTMLElement
  if (container) {
    container.scrollTop = container.scrollHeight
  }
}

// ===== 快捷操作: 解析社区 =====
async function onQuickParseCommunity(templateId?: string) {
  if (!props.selectedCommIds?.length) {
    addMessage('system', t('report.noCommunitySelected'))
    return
  }
  if (!isLLMConfigured()) {
    addMessage('system', t('report.llmNotConfigured'))
    return
  }

  const tplId = templateId || selectedTemplateId.value
  const template = getTemplateById(tplId)
  if (!template) {
    addMessage('error', t('report.templateNotFound'))
    return
  }

  streaming.value = true
  const msgId = `msg-${Date.now()}`
  messages.value.push({
    id: msgId,
    role: 'assistant',
    content: '',
    timestamp: Date.now(),
    isStreaming: true,
    templateId: tplId,
  })

  try {
    // 如果 graphData 为空, 先获取社区图数据
    let graphData = props.graphData
    if (!graphData || !graphData.nodes?.length) {
      console.log('[LLMChatFlow] Fetching community graph...')
      // 提取纯值，避免 Vue 响应式对象无法克隆
      const commIds = Array.isArray(props.selectedCommIds) ? [...props.selectedCommIds] : []
      graphData = await window.api.analysis.getCommunityGraph({
        taskId: props.taskId,
        edgeType: props.edgeType || 'CALL',
        commLv: 'L0',
        commIds,
        depth: 1,
      })
      console.log('[LLMChatFlow] Graph fetched:', graphData)
    }

    const commData = buildCommunityData(graphData)
    const { systemPrompt, userPrompt } = renderPrompt(template, commData)

    addMessage('user', `${t('report.parseCommunity')} [${props.selectedCommIds.slice(0, 3).join(', ')}${props.selectedCommIds.length > 3 ? ` +${props.selectedCommIds.length - 3}` : ''}]`)

    const model = settingsStore.models.find(m => m.isDefault) || settingsStore.models[0]
    console.log('[LLMChatFlow] Using model:', model)
    if (model) {
      llmWorker.setConfig({
        url: model.url,
        apiKey: model.apiKey,
        provider: model.provider as 'ollama' | 'openai' | 'lm-studio' | 'custom',
        model: model.model,
        temperature: model.temperature,
        maxTokens: model.maxTokens,
      })
    }

    let fullContent = ''
    console.log('[LLMChatFlow] Starting LLM chat...')
    await llmWorker.chat(
      [
        { role: 'system', content: systemPrompt },
        { role: 'user', content: userPrompt },
      ],
      (chunk: string) => {
        fullContent += chunk
        const msg = messages.value.find(m => m.id === msgId)
        if (msg) msg.content = fullContent
        scrollToBottom()
      }
    )
    console.log('[LLMChatFlow] LLM chat complete')

    const msg = messages.value.find(m => m.id === msgId)
    if (msg) msg.isStreaming = false
  } catch (e: any) {
    console.error('[LLMChatFlow] Error:', e)
    console.error('[LLMChatFlow] Stack:', e.stack)
    addMessage('error', `${t('report.parseError')}: ${e.message || e}`)
    const msg = messages.value.find(m => m.id === msgId)
    if (msg) msg.isStreaming = false
  } finally {
    streaming.value = false
  }
}

// ===== 用户追问 =====
async function sendFollowUp() {
  if (!userInput.value.trim() || streaming.value) return
  if (!isLLMConfigured()) {
    addMessage('system', t('report.llmNotConfigured'))
    return
  }

  const question = userInput.value.trim()
  addMessage('user', question)
  userInput.value = ''

  streaming.value = true
  const msgId = `msg-${Date.now()}`
  messages.value.push({
    id: msgId,
    role: 'assistant',
    content: '',
    timestamp: Date.now(),
    isStreaming: true,
  })

  try {
    // 构建对话历史: 过滤非对话消息, 保留 user/assistant 交替
    const raw = messages.value
      .filter(m => !m.isStreaming && (m.role === 'user' || m.role === 'assistant'))
      .map(m => ({ role: m.role, content: m.content }))

    // 移除开头的 assistant (必须以 user 开头)
    while (raw.length > 0 && raw[0].role === 'assistant') {
      raw.shift()
    }

    // 合并连续的同角色消息 (LM-Studio 要求严格交替)
    const merged: Array<{ role: string; content: string }> = []
    for (const msg of raw) {
      if (merged.length > 0 && merged[merged.length - 1].role === msg.role) {
        merged[merged.length - 1].content += '\n\n' + msg.content
      } else {
        merged.push({ ...msg })
      }
    }

    // 确保以 user 结尾 (LM-Studio jinja 模板要求)
    while (merged.length > 0 && merged[merged.length - 1].role === 'assistant') {
      merged.pop()
    }

    // 取最近 5 轮 (10 条消息) + 当前问题
    const chatMessages = [...merged.slice(-10), { role: 'user', content: question }]

    const model = settingsStore.models.find(m => m.isDefault) || settingsStore.models[0]
    if (model) {
      llmWorker.setConfig({
        url: model.url,
        apiKey: model.apiKey,
        provider: model.provider as 'ollama' | 'openai' | 'lm-studio' | 'custom',
        model: model.model,
        temperature: model.temperature,
        maxTokens: model.maxTokens,
      })
    }

    let fullContent = ''
    await llmWorker.chat(
      chatMessages,
      (chunk: string) => {
        fullContent += chunk
        const msg = messages.value.find(m => m.id === msgId)
        if (msg) msg.content = fullContent
        scrollToBottom()
      }
    )

    const msg = messages.value.find(m => m.id === msgId)
    if (msg) msg.isStreaming = false
  } catch (e: any) {
    console.error('[LLMChatFlow] Error:', e)
    console.error('[LLMChatFlow] Stack:', e.stack)
    addMessage('error', `${t('report.parseError')}: ${e.message || e}`)
    const msg = messages.value.find(m => m.id === msgId)
    if (msg) msg.isStreaming = false
  } finally {
    streaming.value = false
  }
}

// ===== 组装社区数据 =====
function buildCommunityData(graphData?: any): Record<string, string> {
  const commIds = props.selectedCommIds || []
  const gd = graphData || props.graphData || { nodes: [], edges: [] }

  const nodeList = gd.nodes
    .slice(0, 50)
    .map((n: any) => `- ${n.label || n.id} (${n.type || 'node'})`)
    .join('\n')

  const edgeList = gd.edges
    .slice(0, 50)
    .map((e: any) => {
      const source = e.source || e.from
      const target = e.target || e.to
      const type = e.type || (props.edgeType === 'CALL' ? '调用' : '依赖')
      return `- ${source} → ${target} [${type}]`
    })
    .join('\n')

  return {
    commId: commIds.join(', '),
    nodeCount: String(gd.nodes.length),
    edgeCount: String(gd.edges.length),
    qualityScore: '0.8',
    nodeList: nodeList || t('report.noNodes'),
    edgeList: edgeList || t('report.noEdges'),
    detailNodes: '',
  }
}

// ===== 保存为子文档 =====
function saveAsSubdoc(msgId: string) {
  const msg = messages.value.find(m => m.id === msgId)
  if (!msg || msg.role !== 'assistant') return

  const commId = props.selectedCommIds?.[0] || ''
  const title = `${t('report.parseResult')} - ${new Date(msg.timestamp).toLocaleString()}`

  emit('save-subdoc', {
    commId,
    title,
    content: msg.content,
    templateId: msg.templateId || '',
  })
}

// ===== 删除单条消息 =====
function deleteMessage(msgId: string) {
  messages.value = messages.value.filter(m => m.id !== msgId)
}

// ===== 清空对话 =====
function clearChat() {
  messages.value = []
}

// ===== 初始化 =====
function init() {
  const defaultTpl = getDefaultTemplate('community')
  if (defaultTpl) selectedTemplateId.value = defaultTpl.id
}

watch(() => props.taskId, () => {
  clearChat()
  init()
})

init()

defineExpose({ addQueryResultMessage, clearChat })
</script>

<template>
  <div class="llm-chat-flow">
    <!-- 对话消息区 -->
    <div class="chat-flow-messages">
      <div v-if="messages.length === 0" class="empty-chat">
        <div class="empty-title">{{ t('report.parserHint') }}</div>
        <div class="empty-desc">{{ t('report.parserHintDesc') }}</div>
      </div>

      <div
        v-for="msg in messages"
        :key="msg.id"
        :class="['chat-msg', `msg-${msg.role}`]"
      >
        <!-- 消息头部 -->
        <div class="msg-header">
          <span class="msg-role">
            <template v-if="msg.role === 'user'">{{ t('report.you') }}</template>
            <template v-else-if="msg.role === 'assistant'">{{ t('report.ai') }}</template>
            <template v-else-if="msg.role === 'error'">{{ t('common.error') }}</template>
            <template v-else-if="msg.role === 'query_result'">{{ t('report.queryResult') }}</template>
            <template v-else>{{ t('report.system') }}</template>
          </span>
          <span class="msg-time">{{ new Date(msg.timestamp).toLocaleTimeString() }}</span>
          <button
            class="msg-delete-btn"
            :title="t('common.delete')"
            @click="deleteMessage(msg.id)"
          >
            <TrashIcon class="w-3 h-3" />
          </button>
        </div>

        <!-- 消息内容 -->
        <div class="msg-body">
          <template v-if="msg.isStreaming">
            <div v-if="msg.content" class="msg-text">{{ msg.content }}</div>
            <div class="streaming-indicator">
              <span class="dot"></span><span class="dot"></span><span class="dot"></span>
              <span class="streaming-count">{{ msg.content.length }} 字符</span>
            </div>
          </template>
          <div v-else class="msg-text">{{ msg.content }}</div>
        </div>

        <!-- 快捷操作 (系统消息/查询结果附带) -->
        <div v-if="msg.quickActions && msg.quickActions.length > 0" class="msg-quick-actions">
          <button
            v-for="(qa, idx) in msg.quickActions"
            :key="idx"
            class="quick-action-btn"
            @click="onQuickParseCommunity(qa.templateId)"
          >
            <SparklesIcon class="w-3.5 h-3.5" />
            <span>{{ qa.label }}</span>
          </button>
        </div>

        <!-- 保存按钮 (AI 消息) -->
        <div v-if="msg.role === 'assistant' && !msg.isStreaming && msg.content" class="msg-actions">
          <button class="btn btn-ghost btn-xs" @click="saveAsSubdoc(msg.id)">
            <DocumentArrowDownIcon class="w-3 h-3" />
            <span>{{ t('report.saveAsDoc') }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 底部输入区 -->
    <div class="chat-input-bar">
      <div class="input-row">
        <textarea
          v-model="userInput"
          class="chat-textarea"
          :placeholder="t('report.followUpPlaceholder')"
          :disabled="streaming"
          rows="1"
          @keydown.enter.exact.prevent="sendFollowUp"
        />
        <button
          class="send-btn"
          @click="sendFollowUp"
          :disabled="streaming || !userInput.trim()"
        >
          <template v-if="streaming">
            <span class="send-spinner"></span>
          </template>
          <template v-else>
            <PaperAirplaneIcon class="w-4 h-4" />
          </template>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.llm-chat-flow {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: var(--bg-primary);
}

.chat-flow-messages {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.empty-chat {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--text-muted);
}

.empty-title {
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
}

.empty-desc {
  font-size: 10px;
}

.chat-msg {
  max-width: 85%;
  animation: msgFadeIn 0.2s ease;
}

.msg-user { align-self: flex-end; }
.msg-assistant, .msg-system, .msg-error, .msg-query_result { align-self: flex-start; }

.msg-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 2px;
}

.msg-role {
  font-size: 9px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
}

.msg-time {
  font-size: 8px;
  color: var(--text-muted);
  opacity: 0.5;
}

.msg-delete-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2px;
  border: none;
  border-radius: 3px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  opacity: 0.3;
  transition: all 0.15s;
}

.msg-delete-btn:hover {
  opacity: 1;
  color: var(--error);
  background: color-mix(in srgb, var(--error) 10%, transparent);
}

.msg-body {
  padding: 5px 9px;
  border-radius: 6px;
  font-size: 11px;
  line-height: 1.5;
}

.msg-user .msg-body {
  background: var(--accent);
  color: white;
  border-bottom-right-radius: 2px;
}

.msg-assistant .msg-body {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-bottom-left-radius: 2px;
}

.msg-error .msg-body {
  background: color-mix(in srgb, var(--error) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--error) 25%, transparent);
  color: var(--error);
}

.msg-query_result .msg-body {
  background: color-mix(in srgb, var(--success) 6%, transparent);
  border: 1px solid color-mix(in srgb, var(--success) 20%, transparent);
  border-radius: 6px;
}

.msg-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.streaming-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 0;
}

.streaming-indicator .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent);
  animation: dotPulse 1.4s infinite;
}

.streaming-indicator .dot:nth-child(2) { animation-delay: 0.2s; }
.streaming-indicator .dot:nth-child(3) { animation-delay: 0.4s; }

.streaming-count {
  font-size: 9px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}

/* 快捷操作 tag */
.msg-quick-actions {
  display: flex;
  gap: 4px;
  margin-top: 4px;
  padding-left: 4px;
}

.quick-action-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 10px;
  font-size: 10px;
  font-weight: 600;
  border: none;
  border-radius: 10px;
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  color: var(--accent);
  cursor: pointer;
  transition: all 0.15s;
}

.quick-action-btn:hover {
  background: var(--accent);
  color: white;
}

.msg-actions {
  display: flex;
  gap: 4px;
  margin-top: 3px;
}

/* 底部输入区 */
.chat-input-bar {
  border-top: 1px solid var(--border);
  background: var(--bg-secondary);
  padding: 4px 8px;
}

.input-row {
  display: flex;
  gap: 6px;
  align-items: flex-end;
}

.chat-textarea {
  flex: 1;
  padding: 4px 8px;
  font-size: 11px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
  outline: none;
  resize: none;
  font-family: inherit;
  min-height: 24px;
  max-height: 60px;
}

.chat-textarea:focus { border-color: var(--accent); }
.chat-textarea:disabled { opacity: 0.5; }

.send-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px 8px;
  border: none;
  border-radius: 6px;
  background: var(--accent);
  color: white;
  cursor: pointer;
  transition: opacity 0.15s;
  flex-shrink: 0;
}

.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.send-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes msgFadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes dotPulse {
  0%, 80%, 100% { opacity: 0.4; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
