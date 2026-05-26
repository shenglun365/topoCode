<script setup lang="ts">
import {
  PaperClipIcon,
  PaperAirplaneIcon,
  Cog6ToothIcon,
  ChatBubbleLeftRightIcon,
  BuildingOffice2Icon,
} from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('CD-003')
const { t } = useI18n()

const props = defineProps<{
  mode: 'chat' | 'design'
  modelText: string
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:mode': ['chat' | 'design']
  input: [text: string]
  send: []
  settings: []
}>()

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && e.ctrlKey) {
    e.preventDefault()
    emit('send')
  }
}
</script>

<template>
  <div class="chat-input-area">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 模式切换 -->
    <div class="coder-mode-switch">
      <div
        class="mode-btn"
        :class="{ active: mode === 'chat' }"
        @click="emit('update:mode', 'chat')"
      >
        <ChatBubbleLeftRightIcon class="w-4 h-4" />
        <span>{{ t('coder.chatMode') }}</span>
      </div>
      <div
        class="mode-btn"
        :class="{ active: mode === 'design' }"
        @click="emit('update:mode', 'design')"
      >
        <BuildingOffice2Icon class="w-4 h-4" />
        <span>{{ t('coder.designMode') }}</span>
      </div>
    </div>

    <!-- 输入框 -->
    <div class="coder-input-wrapper">
      <textarea
        class="coder-textarea"
        :placeholder="t('coder.placeholder')"
        :disabled="disabled"
        rows="3"
        @input="emit('input', ($event.target as HTMLTextAreaElement).value)"
        @keydown="handleKeydown"
      />
      <div class="coder-input-actions">
        <button
          class="btn btn-ghost btn-sm icon-btn"
          :title="t('coder.attachFile')"
        >
          <PaperClipIcon class="w-4 h-4" />
        </button>
        <button
          class="btn btn-primary btn-sm"
          :disabled="disabled"
          @click="emit('send')"
        >
          <PaperAirplaneIcon class="w-4 h-4" />
          <span>{{ t('common.send') }}</span>
        </button>
      </div>
    </div>

    <!-- 底部信息 -->
    <div class="coder-input-footer">
      <span>{{ t('coder.modelLabel') }} {{ modelText }}</span>
      <div class="coder-footer-actions">
        <button
          class="btn btn-ghost btn-sm icon-btn"
          :title="t('coder.modelSettings')"
          @click="emit('settings')"
        >
          <Cog6ToothIcon class="w-4 h-4" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-input-area {
  border-top: 1px solid var(--border);
  background: var(--bg-secondary);
  padding: 12px 16px;
}

.coder-mode-switch {
  display: flex;
  gap: 4px;
  margin-bottom: 8px;
}

.mode-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  font-size: 11px;
  color: var(--text-muted);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: all 0.15s;
}

.mode-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.mode-btn.active {
  background: var(--accent);
  color: white;
}

.coder-input-wrapper {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}

.coder-textarea {
  flex: 1;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--bg-primary);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: 13px;
  line-height: 1.5;
  resize: none;
  outline: none;
  transition: border-color 0.15s;
}

.coder-textarea:focus {
  border-color: var(--accent);
}

.coder-textarea:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.coder-input-actions {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.coder-input-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10px;
  color: var(--text-muted);
}

.coder-footer-actions {
  display: flex;
  gap: 4px;
}
</style>
