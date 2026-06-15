<template>
  <Teleport to="body">
    <div v-if="visible" class="dialog-overlay" @click.self="close">
      <div class="timeline-dialog">
        <div class="timeline-dialog-header">
          <h3>{{ taskName }} - {{ t('analysis.timeline', '历史快照') }}</h3>
          <button class="btn btn-ghost btn-sm" @click="close">✕</button>
        </div>

        <div class="timeline-dialog-tabs">
          <button
            :class="['btn btn-xs', filterType === 'all' ? 'btn-active' : 'btn-ghost']"
            @click="filterType = 'all'"
          >全部</button>
          <button
            :class="['btn btn-xs', filterType === 'manual' ? 'btn-active' : 'btn-ghost']"
            @click="filterType = 'manual'"
          >🔖 手动</button>
          <button
            :class="['btn btn-xs', filterType === 'archtrack' ? 'btn-active' : 'btn-ghost']"
            @click="filterType = 'archtrack'"
          >🤖 追踪</button>
        </div>

        <div class="timeline-dialog-body">
          <div v-if="loading" class="timeline-loading">
            <span class="spinner"></span> 加载中...
          </div>

          <div v-else-if="filteredEntries.length === 0" class="timeline-empty">
            暂无记录
          </div>

          <div v-else class="timeline-list">
            <div
              v-for="entry in filteredEntries"
              :key="entry.id"
              :class="['timeline-entry', { 'is-active': entry.isActive }]"
            >
              <div class="timeline-entry-main">
                <span class="timeline-entry-type">{{ entry.type === 'archtrack' ? '🤖' : '🔖' }}</span>
                <span class="timeline-entry-label">{{ entry.alias || entry.versionTag || entry.id.slice(0, 8) }}</span>
                <span v-if="entry.isActive" class="timeline-active-badge">当前</span>
                <span class="timeline-entry-meta">
                  {{ entry.timestamp?.slice(0, 16) }}
                  · {{ entry.communityCount }} 社区
                </span>
              </div>
              <div class="timeline-entry-actions">
                <label class="tl-compare-check" v-if="compareMode">
                  <input
                    type="checkbox"
                    :checked="compareSelection.includes(entry.id)"
                    @change="toggleCompareSelect(entry.id)"
                  />
                </label>
                <button
                  class="btn btn-ghost btn-xs"
                  :title="'设为当前活跃'"
                  :disabled="entry.isActive"
                  @click="setActive(entry.id)"
                >★</button>
                <button
                  v-if="entry.type === 'archtrack'"
                  class="btn btn-ghost btn-xs"
                  title="升格为手动快照"
                  @click="promote(entry.id)"
                >⬆</button>
                <button
                  class="btn btn-ghost btn-xs"
                  title="归档到文件"
                  :disabled="saving.has(entry.id)"
                  @click="archiveEntry(entry)"
                >📦</button>
                <button
                  class="btn btn-ghost btn-xs btn-danger"
                  title="删除"
                  @click="deleteEntry(entry.id)"
                >🗑</button>
              </div>
            </div>
          </div>
        </div>

        <div class="timeline-dialog-footer">
          <button class="btn btn-primary btn-sm" @click="createSnapshot">+ 创建新快照</button>
          <button
            v-if="compareMode && compareSelection.length === 2"
            class="btn btn-primary btn-sm"
            @click="doCompare"
          >对比所选</button>
          <button
            :class="['btn btn-sm', compareMode ? 'btn-primary' : 'btn-ghost']"
            @click="compareMode = !compareMode"
          >{{ compareMode ? '取消对比' : '选择对比' }}</button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ipc } from '@/services/ipc'
import { useI18n } from 'vue-i18n'
import type { TimelineEntry } from '@/types/ipc'

const { t } = useI18n()

const props = defineProps<{
  visible: boolean
  taskId: string
  taskName: string
  projectId: string
}>()

const emit = defineEmits<{
  'close': []
  'compare': [fromId: string, toId: string]
}>()

const entries = ref<TimelineEntry[]>([])
const loading = ref(false)
const filterType = ref<'all' | 'manual' | 'archtrack'>('all')
const compareMode = ref(false)
const compareSelection = ref<string[]>([])
const saving = ref(new Set<string>())

const filteredEntries = computed(() => {
  if (filterType.value === 'all') return entries.value
  return entries.value.filter(e => e.type === filterType.value)
})

watch(() => props.visible, async (v) => {
  if (v) {
    loading.value = true
    try {
      const list = await ipc.analysis.listTimeline({ projectId: props.projectId })
      entries.value = list.filter((e: any) => e.taskId === props.taskId)
    } catch { /* */ }
    loading.value = false
  }
})

function close() {
  emit('close')
}

function toggleCompareSelect(id: string) {
  const idx = compareSelection.value.indexOf(id)
  if (idx >= 0) {
    compareSelection.value.splice(idx, 1)
  } else if (compareSelection.value.length < 2) {
    compareSelection.value.push(id)
  }
}

function doCompare() {
  if (compareSelection.value.length === 2) {
    emit('compare', compareSelection.value[0], compareSelection.value[1])
    compareMode.value = false
    compareSelection.value = []
    emit('close')
  }
}

async function setActive(id: string) {
  await ipc.graph.promoteTimelineEntry({ taskId: props.taskId, timelineId: id })
  entries.value = entries.value.map(e => ({ ...e, isActive: e.id === id }))
}

async function promote(id: string) {
  await ipc.graph.promoteTimelineEntry({ taskId: props.taskId, timelineId: id })
  entries.value = entries.value.map(e =>
    e.id === id ? { ...e, type: 'manual' as const, isActive: true } : { ...e, isActive: false }
  )
}

async function archiveEntry(entry: TimelineEntry) {
  saving.value.add(entry.id)
  try {
    await ipc.graph.exportSnapshots({ taskId: props.taskId })
  } finally {
    saving.value.delete(entry.id)
  }
}

async function createSnapshot() {
  await ipc.graph.saveSnapshot({ taskId: props.taskId, projectId: props.projectId })
  loading.value = true
  try {
    const list = await ipc.analysis.listTimeline({ projectId: props.projectId })
    entries.value = list.filter((e: any) => e.taskId === props.taskId)
  } catch { /* */ }
  loading.value = false
}

async function deleteEntry(id: string) {
  await ipc.graph.deleteSnapshot({ taskId: props.taskId, snapshotId: id })
  entries.value = entries.value.filter(e => e.id !== id)
}
</script>

<style scoped>
.timeline-dialog {
  background: var(--bg-primary);
  border-radius: 8px;
  width: 560px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0,0,0,.3);
}

.timeline-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.timeline-dialog-header h3 {
  margin: 0;
  font-size: 14px;
}

.timeline-dialog-tabs {
  display: flex;
  gap: 4px;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
}

.btn-active {
  background: var(--accent);
  color: #fff;
}

.timeline-dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
  min-height: 120px;
}

.timeline-loading,
.timeline-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px;
  color: var(--text-muted);
  font-size: 13px;
}

.timeline-list {
  padding: 0 8px;
}

.timeline-entry {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-light);
  gap: 8px;
}

.timeline-entry.is-active {
  background: var(--accent-bg, rgba(var(--accent-rgb), .06));
}

.timeline-entry-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.timeline-entry-type {
  font-size: 14px;
}

.timeline-entry-label {
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.timeline-active-badge {
  font-size: 10px;
  background: var(--accent);
  color: #fff;
  padding: 1px 6px;
  border-radius: 4px;
}

.timeline-entry-meta {
  font-size: 11px;
  color: var(--text-muted);
  white-space: nowrap;
}

.timeline-entry-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
}

.tl-compare-check {
  display: flex;
  align-items: center;
}

.timeline-dialog-footer {
  display: flex;
  gap: 8px;
  padding: 10px 16px;
  border-top: 1px solid var(--border);
}

.spinner {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin .6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
