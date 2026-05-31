<script setup lang="ts">
import { onMounted, nextTick, ref } from 'vue'

defineOptions({
    name: 'CoderPage',
})
import { useI18n } from 'vue-i18n'
import {
  ChatBubbleLeftRightIcon,
} from '@heroicons/vue/24/outline'
import { useChatStore } from '@/stores/chat'
import SessionTabBar from '@/components/coder/SessionTabBar.vue'
import ChatMessage from '@/components/coder/ChatMessage.vue'
import ChatInput from '@/components/coder/ChatInput.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PG-003')
const { t } = useI18n()
const chatStore = useChatStore()
const messagesContainer = ref<HTMLElement | null>(null)

onMounted(async () => {
  await chatStore.loadSessions()
})

async function handleSend() {
  await chatStore.sendMessage()
  await nextTick()
  scrollToBottom()
}

function handleAction(action: string) {
  chatStore.handleAction(action)
  nextTick(() => scrollToBottom())
}

function scrollToBottom() {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

function clearSessions() {
  if (confirm('确认清除所有历史会话？此操作不可恢复。')) {
    chatStore.clearAllSessions()
  }
}
</script>

<template>
  <div class="page-coder">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- Session Tab 栏 -->
    <SessionTabBar
      :sessions="chatStore.sessions"
      :active-session-id="chatStore.activeSessionId"
      @switch="chatStore.switchSession"
      @close="chatStore.closeSession"
      @create="chatStore.createSession"
    />
    <div
      v-if="chatStore.sessions.length > 0"
      class="clear-sessions-bar"
    >
      <button
        class="btn btn-ghost btn-xs"
        style="color:var(--text-muted);font-size:11px;"
        @click="clearSessions"
      >清除所有历史会话</button>
    </div>

    <!-- 对话流 -->
    <div
      ref="messagesContainer"
      class="coder-messages"
    >
      <!-- 消息列表 -->
      <template v-if="chatStore.activeSession">
        <ChatMessage
          v-for="message in chatStore.activeSession.messages"
          :key="message.id"
          :message="message"
          @action="handleAction"
        />

        <!-- 正在输入 -->
        <div
          v-if="chatStore.isTyping"
          class="chat-message assistant"
        >
          <div class="msg-avatar">
            <ChatBubbleLeftRightIcon class="w-6 h-6 text-accent" />
          </div>
          <div class="msg-body">
            <div class="msg-bubble typing-indicator">
              <span />
              <span />
              <span />
            </div>
          </div>
        </div>

        <!-- 空状态 -->
        <div
          v-if="chatStore.activeSession.messages.length === 0"
          class="empty-state"
        >
          <ChatBubbleLeftRightIcon class="icon" />
          <div class="title">
            {{ t('coder.newChat') }}
          </div>
          <div class="desc">
            {{ t('coder.startDescribe') }}
          </div>
        </div>
      </template>

      <!-- 无会话 -->
      <div
        v-else
        class="empty-state"
      >
        <ChatBubbleLeftRightIcon class="icon" />
        <div class="title">
          {{ t('coder.noChat') }}
        </div>
        <div class="desc">
          {{ t('coder.clickPlusNewChat') }}
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <ChatInput
      :mode="chatStore.inputMode"
      :model-text="chatStore.modelConfig ? `${chatStore.modelConfig.provider} / ${chatStore.modelConfig.model}` : ''"
      :disabled="!chatStore.activeSessionId"
      @update:mode="chatStore.setMode"
      @input="chatStore.setInputText"
      @send="handleSend"
      @settings=""
    />
  </div>
</template>

<style scoped>
.page-coder {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.coder-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 0;
}

.clear-sessions-bar {
  display: flex;
  justify-content: flex-end;
  padding: 2px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 8px 0;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
  animation: typing 1.4s infinite;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.3;
  }
  30% {
    transform: translateY(-8px);
    opacity: 1;
  }
}
</style>
