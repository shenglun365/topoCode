<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PaperAirplaneIcon,
  SparklesIcon,
  TrashIcon,
} from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import { useSettingsStore } from '@/stores/settings'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const projectStore = useProjectStore()
const settingsStore = useSettingsStore()

const props = defineProps<{
  taskId: string
  reportId?: string
}>()

interface AIChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system' | 'error'
  content: string
  timestamp: number
  isStreaming?: boolean
}

const messages = ref<AIChatMessage[]>([])
const userInput = ref('')
const streaming = ref(false)
const sessionId = ref<string | null>(null)
const templateOptions = ref<Array<{ id: string; name: string }>>([])
const selectedTemplateId = ref('')

const { showId, componentId } = useComponentId('RP-006')

async function initSession() {
  if (!projectStore.selectedProjectId || !props.taskId) return

  try {
    const pid = projectStore.selectedProjectId
    const result = await window.api.analysisSession.list({
      projectId: pid,
      taskId: props.taskId,
      reportId: props.reportId,
    })
    if (result.sessions.length > 0) {
      sessionId.value = result.sessions[0].session_id
      const msgResult = await window.api.session.getMessages({ sessionId: sessionId.value })
      messages.value = (msgResult.messages || []).map((m: any) => ({
        id: m.id,
        role: m.role === 'assistant' ? 'assistant' : 'user',
        content: m.content,
        timestamp: new Date(m.created_at).getTime(),
      }))
    } else {
      const sess = await window.api.session.create({
        moduleType: 'project_analysis',
        title: `报告分析 - ${props.taskId}`,
        projectId: pid,
        metadata: { taskId: props.taskId, reportId: props.reportId, source: 'report_analysis' },
      })
      sessionId.value = sess.id
      await window.api.analysisSession.create({
        projectId: pid,
        taskId: props.taskId,
        sessionId: sess.id,
        reportId: props.reportId,
      })
    }
  } catch (e) {
    console.error('[ReportAIPanel] init session error:', e)
    sessionId.value = `local-${Date.now()}`
  }

  try {
    const tmplResult = await window.api.promptTemplate.list({
      moduleType: 'project_analysis',
    })
    templateOptions.value = (tmplResult.templates || []).map((t: any) => ({
      id: t.id,
      name: t.name,
    }))
  } catch (e) {
    console.error('[ReportAIPanel] load templates error:', e)
  }
}

function addMessage(role: AIChatMessage['role'], content: string) {
  messages.value.push({
    id: `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    role,
    content,
    timestamp: Date.now(),
  })
  scrollToBottom()
}

async function scrollToBottom() {
  await nextTick()
  const container = document.querySelector('.ai-panel-messages') as HTMLElement
  if (container) {
    container.scrollTop = container.scrollHeight
  }
}

async function sendMessage() {
  if (!userInput.value.trim() || streaming.value) return
  if (!sessionId.value) return

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

  const modelId = settingsStore.models.find(m => m.isDefault)?.id
  if (!modelId) {
    const msg = messages.value.find(m => m.id === msgId)
    if (msg) {
      msg.content = t('report.llmNotConfigured')
      msg.isStreaming = false
    }
    streaming.value = false
    return
  }

  try {
    const history = messages.value
      .filter(m => !m.isStreaming && (m.role === 'user' || m.role === 'assistant'))
      .slice(-10)
      .map(m => ({ role: m.role, content: m.content }))

    const result = await window.api.llm.chat({
      sessionId: sessionId.value,
      modelId,
      messages: history,
      mode: 'chat',
    })

    let fullContent = ''

    await new Promise<void>((resolve, reject) => {
      const unsubscribe = window.api.llm.subscribe(result.requestId, {
        onChunk(data: { text: string }) {
          fullContent += data.text
          const msg = messages.value.find(m => m.id === msgId)
          if (msg) msg.content = fullContent
        },
        onDone() {
          const msg = messages.value.find(m => m.id === msgId)
          if (msg) msg.isStreaming = false
          window.api.session.addMessage({
            sessionId: sessionId.value!,
            role: 'user',
            content: question,
          })
          window.api.session.addMessage({
            sessionId: sessionId.value!,
            role: 'assistant',
            content: fullContent,
          })
          unsubscribe()
          resolve()
        },
        onError(errData: { message: string }) {
          const msg = messages.value.find(m => m.id === msgId)
          if (msg) {
            msg.content = `${t('report.parseError')}: ${errData.message}`
            msg.isStreaming = false
          }
          unsubscribe()
          reject(new Error(errData.message))
        },
      })
    })
  } catch (e: any) {
    const msg = messages.value.find(m => m.id === msgId)
    if (msg) {
      msg.content = `${t('report.parseError')}: ${e.message || e}`
      msg.isStreaming = false
    }
  } finally {
    streaming.value = false
  }
}

async function sendPresetAction(templateId: string) {
  const tmpl = templateOptions.value.find(t => t.id === templateId)
  if (!tmpl) return

  addMessage('user', `${t('report.analyzeWith')}: ${tmpl.name}`)
  streaming.value = true
  const msgId = `msg-${Date.now()}`

  messages.value.push({
    id: msgId,
    role: 'assistant',
    content: '',
    timestamp: Date.now(),
    isStreaming: true,
  })

  const modelId = settingsStore.models.find(m => m.isDefault)?.id
  if (!modelId) return

  try {
    const result = await window.api.llm.chat({
      sessionId: sessionId.value!,
      modelId,
      templateId,
      variables: {},
      mode: 'chat',
    })

    let fullContent = ''

    await new Promise<void>((resolve, reject) => {
      const unsubscribe = window.api.llm.subscribe(result.requestId, {
        onChunk(data: { text: string }) {
          fullContent += data.text
          const msg = messages.value.find(m => m.id === msgId)
          if (msg) msg.content = fullContent
        },
        onDone() {
          const msg = messages.value.find(m => m.id === msgId)
          if (msg) msg.isStreaming = false
          unsubscribe()
          resolve()
        },
        onError(errData: { message: string }) {
          const msg = messages.value.find(m => m.id === msgId)
          if (msg) {
            msg.content = `${t('report.parseError')}: ${errData.message}`
            msg.isStreaming = false
          }
          unsubscribe()
          reject(new Error(errData.message))
        },
      })
    })
  } catch (e: any) {
    const msg = messages.value.find(m => m.id === msgId)
    if (msg) {
      msg.content = `${t('report.parseError')}: ${e.message || e}`
      msg.isStreaming = false
    }
  } finally {
    streaming.value = false
  }
}

function clearChat() {
  messages.value = []
}

watch(() => props.taskId, () => {
  messages.value = []
  sessionId.value = null
  initSession()
})

initSession()
</script>

<template>
  <div class="report-ai-panel">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 预制指令 -->
    <div class="preset-bar">
      <span class="preset-label">{{ t('report.presetActions') }}</span>
      <div class="preset-actions">
        <button
          v-for="tpl in templateOptions.slice(0, 4)"
          :key="tpl.id"
          class="preset-btn"
          :disabled="streaming"
          @click="sendPresetAction(tpl.id)"
        >
          <SparklesIcon class="w-3 h-3" />
          <span>{{ tpl.name }}</span>
        </button>
      </div>
    </div>

    <!-- 消息列表 -->
    <div class="ai-panel-messages">
      <div
        v-if="messages.length === 0"
        class="empty-chat"
      >
        <div class="empty-title">
          {{ t('report.aiPanelHint') }}
        </div>
        <div class="empty-desc">
          {{ t('report.aiPanelHintDesc') }}
        </div>
      </div>

      <div
        v-for="msg in messages"
        :key="msg.id"
        :class="['chat-msg', `msg-${msg.role}`]"
      >
        <div class="msg-header">
          <span class="msg-role">
            <template v-if="msg.role === 'user'">{{ t('report.you') }}</template>
            <template v-else-if="msg.role === 'assistant'">{{ t('report.ai') }}</template>
            <template v-else>{{ t('report.system') }}</template>
          </span>
          <span class="msg-time">{{ new Date(msg.timestamp).toLocaleTimeString() }}</span>
        </div>
        <div class="msg-body">
          <template v-if="msg.isStreaming">
            <div
              v-if="msg.content"
              class="msg-text"
            >
              {{ msg.content }}
            </div>
            <div class="streaming-indicator">
              <span class="dot" /><span class="dot" /><span class="dot" />
            </div>
          </template>
          <div
            v-else
            class="msg-text"
          >
            {{ msg.content }}
          </div>
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="ai-input-bar">
      <div class="input-row">
        <textarea
          v-model="userInput"
          class="ai-textarea"
          :placeholder="t('report.followUpPlaceholder')"
          :disabled="streaming"
          rows="1"
          @keydown.enter.exact.prevent="sendMessage"
        />
        <button
          class="send-btn"
          :disabled="streaming || !userInput.trim()"
          @click="sendMessage"
        >
          <template v-if="streaming">
            <span class="send-spinner" />
          </template>
          <template v-else>
            <PaperAirplaneIcon class="w-4 h-4" />
          </template>
        </button>
        <button
          class="clear-btn"
          :title="t('common.clear')"
          @click="clearChat"
        >
          <TrashIcon class="w-4 h-4" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.report-ai-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.preset-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-tertiary);
  overflow-x: auto;
}

.preset-label {
  font-size: 10px;
  color: var(--text-muted);
  white-space: nowrap;
  flex-shrink: 0;
}

.preset-actions {
  display: flex;
  gap: 4px;
}

.preset-btn {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px 8px;
  font-size: 10px;
  border: none;
  border-radius: 8px;
  background: color-mix(in srgb, var(--accent) 12%, transparent);
  color: var(--accent);
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}

.preset-btn:hover {
  background: var(--accent);
  color: white;
}

.preset-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ai-panel-messages {
  flex: 1;
  overflow-y: auto;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
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
  max-width: 95%;
  animation: msgFadeIn 0.2s ease;
}

.msg-user { align-self: flex-end; }
.msg-assistant, .msg-system { align-self: flex-start; }

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

.msg-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.streaming-indicator {
  display: flex;
  gap: 4px;
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

.ai-input-bar {
  border-top: 1px solid var(--border);
  background: var(--bg-secondary);
  padding: 4px 8px;
}

.input-row {
  display: flex;
  gap: 4px;
  align-items: flex-end;
}

.ai-textarea {
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

.ai-textarea:focus { border-color: var(--accent); }
.ai-textarea:disabled { opacity: 0.5; }

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

.clear-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4px 6px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
  flex-shrink: 0;
}

.clear-btn:hover {
  background: color-mix(in srgb, var(--error) 10%, transparent);
  color: var(--error);
}

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
