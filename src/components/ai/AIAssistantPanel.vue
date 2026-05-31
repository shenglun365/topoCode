<script setup lang="ts">
/**
 * AI 助手面板 — 右侧栏独立组件
 *
 * 轻量级对话界面，支持自由提问，不绑定报告 tab。
 */

import { ref, computed, nextTick, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PaperAirplaneIcon,
  SparklesIcon,
  TrashIcon,
} from '@heroicons/vue/24/outline'
import { useSettingsStore } from '@/stores/settings'
import { isLLMConfigured, chat } from '@/services/llmClient'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('OT-001')
const { t } = useI18n()
const settingsStore = useSettingsStore()

interface Message {
  id: string
  role: 'user' | 'assistant' | 'error' | 'system'
  content: string
  timestamp: number
  isStreaming?: boolean
}

const messages = ref<Message[]>([])
const userInput = ref('')
const streaming = ref(false)
const scrollRef = ref<HTMLElement | null>(null)

const llmConfigured = computed(() => isLLMConfigured())

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

async function handleSend() {
  const text = userInput.value.trim()
  if (!text || streaming.value) return

  // 添加用户消息
  addMessage('user', text)
  userInput.value = ''
  streaming.value = true

  // 添加流式占位
  const assistantMsg = addMessage('assistant', '')

  try {
    const fullContent = await chat({
      messages: messages.value
        .filter(m => m.role !== 'system')
        .map(m => ({ role: m.role, content: m.content })),
      onChunk(chunk: string) {
        assistantMsg.content += chunk
        scrollToBottom()
      },
    })
    assistantMsg.content = fullContent
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
</style>
