<script setup lang="ts">
/**
 * ChatView — 统一的 Agent 对话界面。
 *
 * 替代旧的 ReportAIPanel + ReportGenerationPipeline。
 * 用户通过自然语言与 Agent 交互，Agent 自主使用 Skills/Tools 返回结果。
 */
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PaperAirplaneIcon, SparklesIcon, TrashIcon,
  StopIcon, CubeIcon, DocumentTextIcon,
} from '@heroicons/vue/24/outline'
import { isLLMConfigured, chat, type ChatOptions } from '@/services/llmClient'
import { useComponentId } from '@/composables/useComponentId'

const props = defineProps<{
  taskId?: string
  projectId?: string
}>()

const emit = defineEmits<{
  (e: 'open-doc', docId: string): void
}>()

const { showId, componentId } = useComponentId('OT-003')
const { t } = useI18n()

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system' | 'error'
  content: string
  timestamp: number
  isStreaming?: boolean
  toolCalls?: { name: string; args?: Record<string, any>; result?: string }[]
}

const messages = ref<Message[]>([])
const userInput = ref('')
const streaming = ref(false)
const scrollRef = ref<HTMLElement | null>(null)
const abortController = ref<AbortController | null>(null)

const llmConfigured = computed(() => isLLMConfigured())

// Quick actions
const quickActions = [
  { key: 'overview', label: t('report.quickAction.overview'), prompt: t('report.quickAction.overviewPrompt') },
  { key: 'quality', label: t('report.quickAction.quality'), prompt: t('report.quickAction.qualityPrompt') },
  { key: 'doc', label: t('report.quickAction.doc'), prompt: t('report.quickAction.docPrompt') },
]

function scrollToBottom() {
  nextTick(() => {
    if (scrollRef.value) {
      scrollRef.value.scrollTop = scrollRef.value.scrollHeight
    }
  })
}

function addMessage(role: Message['role'], content: string, toolCalls?: Message['toolCalls']): Message {
  const msg: Message = {
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    role,
    content,
    timestamp: Date.now(),
    isStreaming: role === 'assistant',
    toolCalls,
  }
  messages.value.push(msg)
  scrollToBottom()
  return msg
}

async function handleSend() {
  const text = userInput.value.trim()
  if (!text || streaming.value) return

  addMessage('user', text)
  userInput.value = ''
  streaming.value = true

  const ac = new AbortController()
  abortController.value = ac
  const assistantMsg = addMessage('assistant', '')

  try {
    // 注入系统提示词定义角色和范围
    const sendMessages = [
      { role: 'system', content: t('ai.chatSystemPrompt') },
      ...messages.value
        .filter(m => m.role !== 'system' && !m.toolCalls)
        .slice(-20)
        .map(m => ({ role: m.role, content: m.content })),
    ]
    const fullContent = await chat({
      messages: sendMessages,
      onChunk(chunk: string) {
        assistantMsg.content += chunk
        // Basic Markdown rendering — convert ```mermaid / ```plantuml blocks
        if (chunk.includes('```mermaid') || chunk.includes('```plantuml')) {
          assistantMsg.content = _renderMarkdownInline(assistantMsg.content)
        }
        scrollToBottom()
      },
      signal: ac.signal,
    })
    assistantMsg.content = _renderMarkdownInline(fullContent || assistantMsg.content)
    assistantMsg.isStreaming = false
  } catch (err: any) {
    if (err.name === 'AbortError') {
      assistantMsg.content = assistantMsg.content || t('report.agent.cancelled')
    } else {
      assistantMsg.content = err.message || t('chat.requestFailed', '请求失败')
      assistantMsg.role = 'error'
    }
    assistantMsg.isStreaming = false
  } finally {
    streaming.value = false
    abortController.value = null
    scrollToBottom()
  }
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  }
}

function handleQuickAction(prompt: string) {
  userInput.value = prompt
  handleSend()
}

function clearChat() {
  messages.value = []
  if (llmConfigured.value) {
    addMessage('system', t('ai.chatWelcome'))
  }
}

function stopStreaming() {
  abortController.value?.abort()
}

// Basic inline markdown rendering (for mermaid/plantuml blocks)
function _renderMarkdownInline(text: string): string {
  // Wrap mermaid blocks for rendering
  return text
    .replace(/```mermaid\n([\s\S]*?)```/g, '<div class="mermaid-block">$1</div>')
    .replace(/```plantuml\n([\s\S]*?)```/g, '<div class="plantuml-block" data-code="$1">PlantUML</div>')
    .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="code-block"><code>$2</code></pre>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/\n\n/g, '<br><br>')
    .replace(/\n/g, '<br>')
}

onMounted(() => {
  if (llmConfigured.value) {
    addMessage('system', t('ai.chatWelcome'))
  }
})

watch(llmConfigured, (val) => {
  if (val && messages.value.length === 0) {
    addMessage('system', t('ai.chatWelcome'))
  }
})
</script>

<template>
  <div class="chat-view">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>

    <!-- 未配置 -->
    <div
      v-if="!llmConfigured"
      class="chat-empty"
    >
      <SparklesIcon class="icon-lg" />
      <div class="text-lg font-semibold">
        {{ t('chat.title', 'Agent 对话') }}
      </div>
      <div class="text-sm text-gray-500">
        {{ t('chat.notConfigured', '请先在设置中配置 LLM 模型') }}
      </div>
      <router-link
        to="/user#llm"
        class="config-link"
      >
        {{ t('chat.goConfig', '去配置') }}
      </router-link>
    </div>

    <template v-else>
      <!-- 消息列表 -->
      <div
        ref="scrollRef"
        class="chat-messages"
      >
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="chat-msg"
          :class="`msg-${msg.role}`"
        >
          <div class="msg-avatar">
            <SparklesIcon
              v-if="msg.role === 'assistant'"
              class="av-icon"
            />
            <CubeIcon
              v-else-if="msg.role === 'system'"
              class="av-icon"
            />
            <span
              v-else
              class="av-text"
            >U</span>
          </div>
          <div class="msg-body">
            <div
              class="msg-html"
              v-html="msg.content"
            />

            <!-- Tool calls display -->
            <div
              v-if="msg.toolCalls?.length"
              class="tool-calls"
            >
              <div
                v-for="tc in msg.toolCalls"
                :key="tc.name"
                class="tool-call-item"
              >
                <span class="tool-name">{{ tc.name }}</span>
                <span
                  v-if="tc.result"
                  class="tool-result"
                >{{ tc.result.slice(0, 200) }}</span>
              </div>
            </div>

            <div
              v-show="msg.isStreaming"
              class="stream-dot"
            >
              ●
            </div>
          </div>
        </div>
      </div>

      <!-- 快捷操作 -->
      <div
        v-if="messages.length <= 1"
        class="quick-actions"
      >
        <button
          v-for="qa in quickActions"
          :key="qa.key"
          class="qa-btn"
          @click="handleQuickAction(qa.prompt)"
        >
          <DocumentTextIcon class="qa-icon" />
          {{ qa.label }}
        </button>
      </div>

      <!-- 输入区 -->
      <div class="chat-footer">
        <textarea
          v-model="userInput"
          class="chat-input"
          :placeholder="t('chat.placeholder', '输入问题或架构分析需求...')"
          rows="1"
          :disabled="streaming"
          @keydown="handleKeydown"
        />
        <button
          v-show="streaming"
          class="btn-stop"
          @click="stopStreaming"
        >
          <StopIcon class="btn-icon" />
        </button>
        <button
          v-show="!streaming"
          class="btn-send"
          :disabled="!userInput.trim()"
          @click="handleSend"
        >
          <PaperAirplaneIcon class="btn-icon" />
        </button>
        <button
          v-if="messages.length > 1"
          class="btn-clear"
          @click="clearChat"
        >
          <TrashIcon class="btn-icon" />
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.chat-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary, #1a1a2e);
  border-radius: 0.5rem;
  overflow: hidden;
}

.chat-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 2rem;
  color: var(--text-secondary, #9ca3af);
}
.icon-lg { width: 2.5rem; height: 2.5rem; color: var(--accent, #7c3aed); }
.config-link { color: var(--accent, #7c3aed); text-decoration: underline; font-size: 0.875rem; }

/* Messages */
.chat-messages { flex: 1; overflow-y: auto; padding: 1rem; }
.chat-msg { display: flex; gap: 0.75rem; margin-bottom: 1.2rem; }
.msg-avatar {
  width: 2rem; height: 2rem; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
}
.msg-assistant .msg-avatar { background: var(--accent, #7c3aed); color: #fff; }
.msg-system .msg-avatar { background: var(--info, #3b82f6); color: #fff; }
.msg-user .msg-avatar { background: var(--secondary, #374151); color: #fff; }
.msg-error .msg-avatar { background: #ef4444; color: #fff; }
.av-icon { width: 1.1rem; height: 1.1rem; }
.av-text { font-size: 0.8rem; font-weight: 600; }
.msg-body { flex: 1; min-width: 0; }
.msg-html {
  padding: 0.6rem 1rem; border-radius: 0.5rem; line-height: 1.55; font-size: 0.875rem;
  overflow-wrap: break-word;
}
.msg-assistant .msg-html { background: var(--bg-secondary, #2d2d44); color: var(--text-primary, #e5e7eb); }
.msg-system .msg-html { background: var(--bg-info, #1e3a5f); color: var(--text-primary, #e5e7eb); font-style: italic; }
.msg-user .msg-html { background: var(--accent, #7c3aed); color: #fff; }
.msg-error .msg-html { background: #7f1d1d; color: #fca5a5; }

.stream-dot { color: var(--accent); animation: pulse 0.8s infinite; padding: 0.25rem 1rem; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

/* Tool calls */
.tool-calls { margin-top: 0.25rem; padding: 0 1rem; }
.tool-call-item {
  background: var(--bg-tool, #1e293b); border-radius: 0.375rem; padding: 0.35rem 0.6rem;
  margin-top: 0.25rem; font-size: 0.75rem; color: var(--text-muted, #6b7280);
}
.tool-name { font-weight: 600; color: var(--accent, #7c3aed); }

/* Code / diagram blocks */
.msg-html :deep(.mermaid-block) { background: #fff; border-radius: 0.375rem; padding: 0.5rem; margin: 0.5rem 0; }
.msg-html :deep(.plantuml-block) { background: #f0fdf4; border-radius: 0.375rem; padding: 0.5rem; margin: 0.5rem 0; font-size: 0.75rem; }
.msg-html :deep(.code-block) { background: #1e293b; color: #e2e8f0; border-radius: 0.375rem; padding: 0.5rem 0.75rem; margin: 0.5rem 0; font-size: 0.8rem; overflow-x: auto; line-height: 1.4; }
.msg-html :deep(li) { margin-left: 1rem; }
.msg-html :deep(strong) { font-weight: 600; }

/* Quick actions */
.quick-actions { display: flex; gap: 0.5rem; padding: 0.75rem 1rem; flex-wrap: wrap; border-top: 1px solid var(--border, #374151); }
.qa-btn {
  display: flex; align-items: center; gap: 0.35rem;
  background: var(--bg-secondary, #2d2d44); border: 1px solid var(--border, #374151);
  border-radius: 1rem; padding: 0.35rem 0.75rem; font-size: 0.8rem;
  color: var(--text-secondary, #9ca3af); cursor: pointer; transition: all 0.15s;
}
.qa-btn:hover { border-color: var(--accent, #7c3aed); color: var(--text-primary, #e5e7eb); }
.qa-icon { width: 0.9rem; height: 0.9rem; }

/* Footer */
.chat-footer { display: flex; gap: 0.5rem; padding: 0.75rem 1rem; border-top: 1px solid var(--border, #374151); }
.chat-input {
  flex: 1; background: var(--bg-secondary, #2d2d44); border: 1px solid var(--border, #374151);
  border-radius: 0.5rem; padding: 0.55rem 0.75rem; color: var(--text-primary, #e5e7eb);
  resize: none; font-size: 0.875rem; min-height: 2.25rem;
}
.chat-input:focus { outline: none; border-color: var(--accent, #7c3aed); }
.chat-input:disabled { opacity: 0.5; }
.btn-send, .btn-stop, .btn-clear {
  padding: 0.5rem; border: none; border-radius: 0.5rem; cursor: pointer;
  display: flex; align-items: center; transition: background 0.15s;
}
.btn-send { background: var(--accent, #7c3aed); color: #fff; }
.btn-send:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-stop { background: #ef4444; color: #fff; }
.btn-clear { background: transparent; color: var(--text-muted, #6b7280); }
.btn-icon { width: 1.2rem; height: 1.2rem; }
</style>
