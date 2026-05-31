<script setup lang="ts">
import {
  XMarkIcon,
  PlusIcon,
  BuildingOffice2Icon,
  ChatBubbleLeftRightIcon,
} from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import type { ChatSession } from '@/utils/mock'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('CD-007')
const { t } = useI18n()

defineProps<{
  sessions: ChatSession[]
  activeSessionId: string | null
}>()

const emit = defineEmits<{
  switch: [sessionId: string]
  close: [sessionId: string]
  create: []
}>()

function getModeIcon(mode: string): any {
  return mode === 'design' ? BuildingOffice2Icon : ChatBubbleLeftRightIcon
}

function getModeColor(mode: string): string {
  return mode === 'design' ? 'text-accent' : 'text-blue-400'
}
</script>

<template>
  <div class="session-tabs-bar">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- Tab 列表 -->
    <div class="session-tabs">
      <div
        v-for="session in sessions"
        :key="session.id"
        class="session-tab"
        :class="{ active: activeSessionId === session.id }"
        @click="emit('switch', session.id)"
      >
        <!-- 模式图标 -->
        <component
          :is="getModeIcon(session.mode)"
          :class="['w-3.5 h-3.5', getModeColor(session.mode)]"
        />

        <!-- 标题 -->
        <span class="tab-title">{{ session.title }}</span>

        <!-- 状态徽章 -->
        <span
          v-if="session.status === 'running'"
          class="badge badge-yellow"
          style="font-size:8px;"
        >
          {{ t('common.running') }}
        </span>

        <!-- 关闭按钮 -->
        <button
          class="tab-close"
          @click.stop="emit('close', session.id)"
        >
          <XMarkIcon class="w-3 h-3" />
        </button>
      </div>
    </div>

    <!-- 新建按钮 -->
    <div class="session-tabs-actions">
      <button
        class="btn btn-ghost btn-sm icon-btn"
        :title="t('coder.newSession')"
        @click="emit('create')"
      >
        <PlusIcon class="w-4 h-4" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.session-tabs-bar {
  display: flex;
  align-items: center;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
  padding: 0 8px;
}

.session-tabs {
  display: flex;
  overflow-x: auto;
  flex: 1;
}

.session-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--text-muted);
  cursor: pointer;
  border-right: 1px solid var(--border);
  white-space: nowrap;
  transition: all 0.15s;
  flex-shrink: 0;
}

.session-tab:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.session-tab.active {
  background: var(--bg-primary);
  color: var(--text-primary);
  border-bottom: 2px solid var(--accent);
}

.tab-title {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tab-close {
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 3px;
  opacity: 0;
  transition: all 0.1s;
  background: transparent;
  border: none;
  color: inherit;
  cursor: pointer;
}

.session-tab:hover .tab-close {
  opacity: 1;
}

.tab-close:hover {
  background: var(--bg-active);
}

.session-tabs-actions {
  flex-shrink: 0;
  padding: 0 4px;
}
</style>
