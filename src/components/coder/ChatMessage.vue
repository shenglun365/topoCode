<script setup lang="ts">
import {
  UserCircleIcon,
  CpuChipIcon,
  DocumentTextIcon,
  CodeBracketIcon,
  ChartBarIcon,
} from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import type { ChatMessage } from '@/utils/mock'
import ContextCards from './ContextCards.vue'
import TaskStatusCard from './TaskStatusCard.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('CD-002')
const { t } = useI18n()

defineProps<{
  message: ChatMessage
}>()

const emit = defineEmits<{
  action: [action: string]
}>()

function formatTime(timestamp: string): string {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function getContextIcon(type: string): any {
  switch (type) {
    case 'knowledge': return DocumentTextIcon
    case 'code': return CodeBracketIcon
    case 'analysis': return ChartBarIcon
    default: return DocumentTextIcon
  }
}
</script>

<template>
  <div
    class="chat-message"
    :class="message.role"
  >
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 头像 -->
    <div class="msg-avatar">
      <UserCircleIcon
        v-if="message.role === 'user'"
        class="w-6 h-6 text-blue-400"
      />
      <CpuChipIcon
        v-else
        class="w-6 h-6 text-accent"
      />
    </div>

    <!-- 消息体 -->
    <div class="msg-body">
      <!-- 消息气泡 -->
      <div class="msg-bubble">
        <!-- 文本内容 -->
        <div
          class="msg-content"
          v-html="message.content.replace(/\n/g, '<br>')"
        />

        <!-- 上下文检索卡片 -->
        <ContextCards
          v-if="message.contextCards"
          :cards="message.contextCards"
        />

        <!-- Spec 摘要卡片 -->
        <div
          v-if="message.specSummary"
          class="spec-summary-card"
        >
          <div class="spec-meta">
            <span class="badge badge-green">{{ t('coder.draft') }}</span>
            <span style="font-size:10px; color:var(--text-muted);">
              {{ new Date(message.specSummary.createdAt).toLocaleString('zh-CN') }}
            </span>
          </div>
          <div class="spec-section">
            <div class="spec-label">
              📁 {{ t('coder.targetFile') }}
            </div>
            <div class="spec-value font-mono">
              {{ message.specSummary.targetFile }}
            </div>
          </div>
          <div class="spec-section">
            <div class="spec-label">
              🔧 {{ t('coder.dependencies') }}
            </div>
            <div
              v-for="dep in message.specSummary.dependencies"
              :key="dep"
              class="spec-value font-mono"
            >
              {{ dep }}
            </div>
          </div>
          <div class="spec-section">
            <div class="spec-label">
              🔒 {{ t('coder.constraints') }}
            </div>
            <div
              v-for="constraint in message.specSummary.constraints"
              :key="constraint"
              class="spec-value"
            >
              {{ constraint }}
            </div>
          </div>
          <div class="spec-section">
            <div class="spec-label">
              📐 {{ t('coder.functionSignature') }}
            </div>
            <div
              v-for="sig in message.specSummary.functionSignatures"
              :key="sig"
              class="spec-value font-mono"
            >
              {{ sig }}
            </div>
          </div>
        </div>

        <!-- 任务状态卡片 -->
        <TaskStatusCard
          v-if="message.taskStatus"
          :task="message.taskStatus"
        />
      </div>

      <!-- 操作按钮 -->
      <div
        v-if="message.actions && message.actions.length > 0"
        class="msg-actions"
      >
        <button
          v-for="action in message.actions"
          :key="action"
          class="btn btn-primary btn-sm"
          @click="emit('action', action)"
        >
          {{ action }}
        </button>
      </div>

      <!-- 时间戳 -->
      <div class="msg-time">
        <span v-if="message.role === 'assistant'">Ollama / qwen2.5-coder:7b</span>
        <span v-else>{{ formatTime(message.timestamp) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-message {
  display: flex;
  gap: 12px;
  padding: 16px 20px;
  animation: fadeIn 0.3s ease;
}

.chat-message.user {
  flex-direction: row-reverse;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.msg-avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.msg-body {
  flex: 1;
  min-width: 0;
}

.msg-bubble {
  background: var(--bg-secondary);
  padding: 12px 16px;
  border-radius: var(--radius-md);
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
}

.chat-message.user .msg-bubble {
  background: var(--accent);
  color: white;
}

.msg-content {
  white-space: pre-wrap;
}

.msg-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.msg-time {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 4px;
}

.spec-summary-card {
  margin-top: 12px;
  padding: 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}

.spec-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.spec-section {
  margin-bottom: 8px;
}

.spec-label {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.spec-value {
  font-size: 12px;
  color: var(--text-primary);
}
</style>
