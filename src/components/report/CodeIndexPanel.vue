<script setup lang="ts">
/**
 * 代码索引面板 — 右侧面板对话消息流
 *
 * - 点击节点/边/社区 → 追加消息卡片
 * - 重复内容定位到已有锚点
 * - checkbox 批量删除 + 清空全部
 * - 随项目自动切换上下文
 */

import { ref, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  TrashIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import SymbolDetailCard from './SymbolDetailCard.vue'
import EdgeDetailCard from './EdgeDetailCard.vue'
import CommunityNodeCard from './CommunityNodeCard.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('RP-012')
const { t } = useI18n()
const projectStore = useProjectStore()

// 消息类型
export interface IndexMessage {
  id: string
  type: 'node' | 'edge' | 'community'
  timestamp: number
  // node 类型
  symbolData?: {
    symbolId: string
    symbolType: string
    name: string
    className?: string
    filePath: string
    startLine: number
    endLine: number
    codeSnippet: string
    needsSummarize?: boolean
  }
  // edge 类型
  edgeData?: {
    edgeId: string
    edgeType: 'CALL' | 'DEPENDENCE'
    source: { name: string; file_id?: string }
    target: { name: string; file_id?: string }
    callSiteNode?: string
    includePath?: string
    isSystem?: boolean
  }
  // community 类型
  communityData?: {
    commId: string
    nodeCount: number
    edgeCount: number
    qualityScore: number
    description?: string
  }
  // AI 解释结果
  aiContent?: string
}

const messages = ref<IndexMessage[]>([])
const selectedIds = ref<Set<string>>(new Set())

// 当前项目上下文
const currentProjectId = ref(projectStore.selectedProjectId)

// 监听项目切换
watch(() => projectStore.selectedProjectId, (newId) => {
  if (newId !== currentProjectId.value) {
    currentProjectId.value = newId
    // TODO: 从 SQLite 加载新项目历史
    messages.value = []
    selectedIds.value.clear()
  }
})

// 添加节点消息
function addNodeMessage(data: NonNullable<IndexMessage['symbolData']>) {
  // 检查重复
  const existing = messages.value.find(
    m => m.type === 'node' && m.symbolData?.symbolId === data.symbolId
  )
  if (existing) {
    scrollToMessage(existing.id)
    return
  }

  const msg: IndexMessage = {
    id: `msg-${Date.now()}-node-${data.symbolId}`,
    type: 'node',
    timestamp: Date.now(),
    symbolData: data,
  }
  messages.value.push(msg)
  nextTick(() => scrollToBottom())
}

// 添加边消息
function addEdgeMessage(data: NonNullable<IndexMessage['edgeData']>) {
  const existing = messages.value.find(
    m => m.type === 'edge' && m.edgeData?.edgeId === data.edgeId
  )
  if (existing) {
    scrollToMessage(existing.id)
    return
  }

  const msg: IndexMessage = {
    id: `msg-${Date.now()}-edge-${data.edgeId}`,
    type: 'edge',
    timestamp: Date.now(),
    edgeData: data,
  }
  messages.value.push(msg)
  nextTick(() => scrollToBottom())
}

// 添加社区消息
function addCommunityMessage(data: NonNullable<IndexMessage['communityData']>) {
  const existing = messages.value.find(
    m => m.type === 'community' && m.communityData?.commId === data.commId
  )
  if (existing) {
    scrollToMessage(existing.id)
    return
  }

  const msg: IndexMessage = {
    id: `msg-${Date.now()}-comm-${data.commId}`,
    type: 'community',
    timestamp: Date.now(),
    communityData: data,
  }
  messages.value.push(msg)
  nextTick(() => scrollToBottom())
}

// 滚动到指定消息
function scrollToMessage(msgId: string) {
  const el = document.getElementById(`msg-${msgId}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    // 高亮闪烁
    el.classList.add('msg-highlight')
    setTimeout(() => el.classList.remove('msg-highlight'), 1500)
  }
}

function scrollToBottom() {
  const container = document.querySelector('.code-index-messages')
  if (container) {
    container.scrollTop = container.scrollHeight
  }
}

// 删除
function toggleSelect(msgId: string) {
  if (selectedIds.value.has(msgId)) {
    selectedIds.value.delete(msgId)
  } else {
    selectedIds.value.add(msgId)
  }
}

function deleteSelected() {
  messages.value = messages.value.filter(m => !selectedIds.value.has(m.id))
  selectedIds.value.clear()
}

function clearAll() {
  messages.value = []
  selectedIds.value.clear()
}

// AI 结果回调
function handleAIResult(msgId: string, content: string) {
  const msg = messages.value.find(m => m.id === msgId)
  if (msg) {
    msg.aiContent = content
  }
}

// 打开源码
function handleOpenSource(filePath: string, line: number) {
  // TODO: 新开源码 tab 定位到行
  console.log('[CodeIndexPanel] Open source:', filePath, line)
}

defineExpose({
  addNodeMessage,
  addEdgeMessage,
  addCommunityMessage,
  clearAll,
})
</script>

<template>
  <div class="code-index-panel">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 操作按钮（标题由 RightPanel 的 panel-header 渲染） -->
    <div class="panel-actions">
      <div class="header-actions">
        <button
          v-if="selectedIds.size > 0"
          class="btn btn-ghost btn-sm delete-btn"
          @click="deleteSelected"
        >
          <TrashIcon class="w-3.5 h-3.5" />
          <span>{{ selectedIds.size }}</span>
        </button>
        <button
          v-if="messages.length > 0"
          class="btn btn-ghost btn-sm clear-btn"
          @click="clearAll"
        >
          <XMarkIcon class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- 消息列表 -->
    <div class="code-index-messages">
      <div
        v-if="messages.length === 0"
        class="empty-state"
      >
        <span>{{ t('report.noSelectedNode') }}</span>
      </div>

      <div
        v-for="msg in messages"
        :id="msg.id"
        :key="msg.id"
        class="index-message"
        :class="{ selected: selectedIds.has(msg.id) }"
      >
        <!-- 选择框 -->
        <input
          type="checkbox"
          :checked="selectedIds.has(msg.id)"
          class="msg-checkbox"
          @change="toggleSelect(msg.id)"
        >

        <!-- 消息内容 -->
        <div class="msg-content">
          <!-- 时间戳 -->
          <div class="msg-time">
            {{ new Date(msg.timestamp).toLocaleTimeString() }}
          </div>

          <!-- 节点详情 -->
          <SymbolDetailCard
            v-if="msg.type === 'node' && msg.symbolData"
            v-bind="msg.symbolData"
            @ai-result="(content: string) => handleAIResult(msg.id, content)"
            @open-source="handleOpenSource"
          />

          <!-- 边详情 -->
          <EdgeDetailCard
            v-if="msg.type === 'edge' && msg.edgeData"
            v-bind="msg.edgeData"
            @ai-result="(content: string) => handleAIResult(msg.id, content)"
          />

          <!-- 社区详情 -->
          <CommunityNodeCard
            v-if="msg.type === 'community' && msg.communityData"
            v-bind="msg.communityData"
            @ai-result="(content: string) => handleAIResult(msg.id, content)"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.code-index-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.panel-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  padding: 4px 8px;
  gap: 4px;
}

.panel-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.header-actions {
  display: flex;
  gap: 2px;
}

.delete-btn {
  color: var(--error);
}

.clear-btn {
  color: var(--text-muted);
}

.code-index-messages {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-muted);
  font-size: 12px;
}

.index-message {
  display: flex;
  gap: 6px;
  padding: 6px;
  margin-bottom: 4px;
  border-radius: 4px;
  transition: background 0.15s;
}

.index-message:hover {
  background: var(--bg-hover);
}

.index-message.selected {
  background: color-mix(in srgb, var(--error) 8%, transparent);
}

.index-message.msg-highlight {
  animation: highlight-flash 1.5s ease;
}

@keyframes highlight-flash {
  0%, 100% { background: transparent; }
  30%, 60% { background: color-mix(in srgb, var(--accent) 15%, transparent); }
}

.msg-checkbox {
  margin-top: 4px;
  accent-color: var(--accent);
  flex-shrink: 0;
}

.msg-content {
  flex: 1;
  min-width: 0;
}

.msg-time {
  font-size: 10px;
  color: var(--text-muted);
  margin-bottom: 4px;
}
</style>
