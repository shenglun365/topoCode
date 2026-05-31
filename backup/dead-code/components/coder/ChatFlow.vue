<template>
  <div class="chat-flow">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 消息列表 -->
    <div
      ref="messageListRef"
      class="message-list"
      @scroll="handleScroll"
    >
      <div
        v-if="messages.length === 0"
        class="empty-state"
      >
        <ChatBubbleLeftRightIcon class="w-16 h-16 empty-icon" />
        <p class="empty-text">
          {{ t('coder.noMessages') }}
        </p>
        <p class="empty-hint">
          {{ t('coder.startConversation') }}
        </p>
      </div>

      <div
        v-else
        class="message-container"
      >
        <div
          v-for="message in messages"
          :key="message.id"
          :class="['message-item', `message-${message.role}`]"
        >
          <ChatMessage
            :message="message"
            @view-context="viewContext"
            @view-spec="viewSpec"
          />
        </div>

        <!-- 加载指示器 -->
        <div
          v-if="loading"
          class="loading-indicator"
        >
          <div class="loading-dots">
            <span class="dot" />
            <span class="dot" />
            <span class="dot" />
          </div>
          <span class="loading-text">{{ t('coder.thinking') }}</span>
        </div>
      </div>
    </div>

    <!-- 模式切换 -->
    <div class="mode-switch">
      <button
        :class="['mode-btn', { active: mode === 'chat' }]"
        @click="switchMode('chat')"
      >
        <ChatBubbleBottomCenterTextIcon class="w-4 h-4" />
        {{ t('coder.modeChat') }}
      </button>
      <button
        :class="['mode-btn', { active: mode === 'design' }]"
        @click="switchMode('design')"
      >
        <WrenchScrewdriverIcon class="w-4 h-4" />
        {{ t('coder.modeDesign') }}
      </button>
    </div>

    <!-- 输入区 -->
    <div class="input-area">
      <textarea
        v-model="inputText"
        class="input-textarea"
        :placeholder="t('coder.inputPlaceholder')"
        rows="1"
        @keydown.enter.exact.prevent="sendMessage"
      />
      <div class="input-actions">
        <button
          class="action-btn"
          :title="t('coder.attachFile')"
        >
          <PaperClipIcon class="w-5 h-5" />
        </button>
        <button
          v-if="loading"
          class="action-btn stop-btn"
          :title="t('coder.stop')"
          @click="stopGeneration"
        >
          <StopIcon class="w-5 h-5" />
        </button>
        <button
          v-else
          class="action-btn send-btn"
          :disabled="!canSend"
          :title="t('coder.send')"
          @click="sendMessage"
        >
          <PaperAirplaneIcon class="w-5 h-5" />
        </button>
      </div>
      <div class="model-info">
        <span class="model-label">{{ t('coder.model') }}:</span>
        <span class="model-name">{{ currentModel }}</span>
        <button
          class="model-settings-btn"
          @click="openModelSettings"
        >
          <Cog6ToothIcon class="w-4 h-4" />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ChatBubbleLeftRightIcon,
  ChatBubbleBottomCenterTextIcon,
  WrenchScrewdriverIcon,
  PaperClipIcon,
  PaperAirplaneIcon,
  StopIcon,
  Cog6ToothIcon,
} from '@heroicons/vue/24/outline'
import ChatMessage from './ChatMessage.vue'
import type { ChatMessage as ChatMessageType } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('CD-001')
const { t } = useI18n()

const props = defineProps<{
  messages: ChatMessageType[]
  sessionId: string
  loading: boolean
  currentModel?: string
}>()

const emit = defineEmits<{
  send: [content: string]
  stop: []
  'scroll': [position: number]
  'view-context': [contextId: string]
  'view-spec': [specId: string]
  'model-settings': []
}>()

const mode = ref<'chat' | 'design'>('chat')
const inputText = ref('')
const messageListRef = ref<HTMLElement | null>(null)

const canSend = computed(() => {
  return inputText.value.trim().length > 0 && !props.loading
})

function sendMessage() {
  if (!canSend.value) return
  emit('send', inputText.value.trim())
  inputText.value = ''
  nextTick(() => {
    scrollToBottom()
  })
}

function stopGeneration() {
  emit('stop')
}

function switchMode(newMode: 'chat' | 'design') {
  mode.value = newMode
}

function handleScroll() {
  if (!messageListRef.value) return
  emit('scroll', messageListRef.value.scrollTop)
}

function scrollToBottom() {
  if (!messageListRef.value) return
  messageListRef.value.scrollTop = messageListRef.value.scrollHeight
}

function viewContext(contextId: string) {
  emit('view-context', contextId)
}

function viewSpec(specId: string) {
  emit('view-spec', specId)
}

function openModelSettings() {
  emit('model-settings')
}
</script>

<style scoped lang="scss">
.chat-flow {
  @apply flex flex-col h-full;
}

.message-list {
  @apply flex-1 overflow-y-auto p-4;
}

.empty-state {
  @apply flex flex-col items-center justify-center h-full text-center;
}

.empty-icon {
  @apply text-[--text-muted] mb-4;
}

.empty-text {
  @apply text-sm text-[--text-secondary] mb-1;
}

.empty-hint {
  @apply text-xs text-[--text-muted];
}

.message-container {
  @apply flex flex-col gap-4;
}

.message-item {
  @apply flex;

  &.message-user {
    @apply justify-end;
  }

  &.message-assistant {
    @apply justify-start;
  }
}

.loading-indicator {
  @apply flex items-center gap-2 px-4 py-2;
}

.loading-dots {
  @apply flex gap-1;
}

.dot {
  @apply w-2 h-2 rounded-full bg-[--accent] animate-pulse;

  &:nth-child(2) {
    animation-delay: 0.2s;
  }

  &:nth-child(3) {
    animation-delay: 0.4s;
  }
}

.loading-text {
  @apply text-xs text-[--text-muted];
}

.mode-switch {
  @apply flex gap-2 px-4 py-2 border-t border-b border-[--border] bg-[--bg-secondary];
}

.mode-btn {
  @apply flex items-center gap-1.5 px-3 py-1.5 text-xs rounded bg-[--bg-tertiary] text-[--text-secondary] hover:bg-[--bg-hover] hover:text-[--text-primary] transition-colors;

  &.active {
    @apply bg-[--accent]/20 text-[--accent];
  }
}

.input-area {
  @apply p-4 bg-[--bg-secondary];
}

.input-textarea {
  @apply w-full px-4 py-3 text-sm rounded-lg bg-[--bg-tertiary] border border-[--border] text-[--text-primary] focus:border-[--accent] focus:outline-none resize-none min-h-[60px] max-h-[200px];
}

.input-actions {
  @apply flex justify-between items-center mt-2;
}

.action-btn {
  @apply p-2 rounded text-[--text-muted] hover:text-[--text-primary] hover:bg-[--bg-hover] transition-colors;

  &.stop-btn {
    @apply text-red-400 hover:text-red-300 hover:bg-red-500/20;
  }

  &.send-btn {
    @apply text-[--accent] hover:text-[--accent-hover] hover:bg-[--accent]/20 disabled:opacity-50 disabled:cursor-not-allowed;
  }
}

.model-info {
  @apply flex items-center gap-2 mt-2 text-xs text-[--text-muted];
}

.model-label {
  @apply text-[--text-muted];
}

.model-name {
  @apply text-[--text-secondary];
}

.model-settings-btn {
  @apply p-1 text-[--text-muted] hover:text-[--text-primary] transition-colors ml-auto;
}
</style>
