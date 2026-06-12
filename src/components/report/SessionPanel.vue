<script setup lang="ts">
/**
 * SessionPanel — AI 会话历史列表。
 *
 * 显示历史 AI 分析会话，支持查看变更摘要。
 * 数据源: ai_sessions 表 (通过 IPC 加载)。
 */
import { ref, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ClockIcon, CheckCircleIcon, ExclamationTriangleIcon } from '@heroicons/vue/24/outline'

const props = defineProps<{
  taskId?: string
  projectId?: string
}>()

const emit = defineEmits<{
  (e: 'select-session', sessionId: string): void
}>()

const { t } = useI18n()

interface SessionItem {
  id: string
  tag: string
  started_at: string
  status: string
  quality_score: number | null
}

const sessions = ref<SessionItem[]>([])

async function loadSessions() {
  // TODO: ipc.analysis.listSessions(taskId)
  // 当前为占位数据，后端 ai_sessions 表就绪后接入
  sessions.value = []
}

function selectSession(id: string) {
  emit('select-session', id)
}

onMounted(() => loadSessions())
watch(() => props.taskId, () => loadSessions())
</script>

<template>
  <div class="session-panel">
    <div class="panel-header">
      <ClockIcon class="hdr-icon" />
      <span>{{ t('session.history', '会话') }}</span>
    </div>
    <div class="panel-body">
      <div
        v-if="sessions.length === 0"
        class="empty"
      >
        <p>{{ t('session.empty', 'AI 会话记录将在分析运行时自动生成') }}</p>
      </div>
      <div
        v-for="s in sessions"
        :key="s.id"
        class="session-item"
        @click="selectSession(s.id)"
      >
        <div class="session-tag">
          {{ s.tag || s.id.slice(0, 12) }}
        </div>
        <div class="session-meta">
          <span class="meta-time">{{ s.started_at?.slice(0, 16) || '' }}</span>
          <CheckCircleIcon
            v-if="s.quality_score && s.quality_score > 0.7"
            class="meta-icon text-green"
          />
          <ExclamationTriangleIcon
            v-else
            class="meta-icon text-amber"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.session-panel { height: 100%; display: flex; flex-direction: column; background: var(--bg-primary, #1a1a2e); }
.panel-header { display: flex; align-items: center; gap: 0.5rem; padding: 0.75rem 1rem; border-bottom: 1px solid var(--border, #374151); font-size: 0.85rem; font-weight: 600; color: var(--text-primary, #e5e7eb); }
.hdr-icon { width: 1rem; height: 1rem; }
.panel-body { flex: 1; overflow-y: auto; padding: 0.25rem; }
.empty { padding: 2rem 1rem; text-align: center; color: var(--text-secondary, #9ca3af); font-size: 0.8rem; }
.session-item { padding: 0.5rem 0.75rem; border-radius: 0.375rem; cursor: pointer; margin-bottom: 0.15rem; }
.session-item:hover { background: var(--bg-secondary, #2d2d44); }
.session-tag { font-size: 0.8rem; color: var(--text-primary, #e5e7eb); font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-meta { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.15rem; }
.meta-time { font-size: 0.7rem; color: var(--text-muted, #6b7280); }
.meta-icon { width: 0.75rem; height: 0.75rem; }
.text-green { color: #22c55e; }
.text-amber { color: #f59e0b; }
</style>
