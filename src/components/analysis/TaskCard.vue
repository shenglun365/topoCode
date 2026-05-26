<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { computed } from 'vue'
import {
  ChartBarIcon,
  StarIcon,
  PaperClipIcon,
  EllipsisVerticalIcon,
  PlayIcon,
  StopIcon,
  PencilIcon,
  TrashIcon,
  ArrowPathIcon,
  ClipboardDocumentIcon,
} from '@heroicons/vue/24/outline'
import { StarIcon as StarSolidIcon } from '@heroicons/vue/24/solid'
import type { AnalysisTask } from '@/types'
import { taskStatusBadge, taskStatusNames } from '@/utils/mock'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('AN-001')
const { t, locale } = useI18n()

const localeStr = computed(() => locale.value === 'zh-CN' ? 'zh-CN' : 'en-US')

const props = defineProps<{
  task: AnalysisTask
}>()

const emit = defineEmits<{
  select: [task: AnalysisTask]
  run: [taskId: string]
  stop: [taskId: string]
  retry: [taskId: string]
  toggleFavorite: [taskId: string]
  togglePin: [taskId: string]
  delete: [taskId: string]
}>()

const expanded = ref(false)

function getStatusIcon(status: string) {
  switch (status) {
    case 'done': return '✓'
    case 'running': return '⟳'
    case 'error': return '✕'
    default: return '○'
  }
}
</script>

<template>
  <div
    class="task-card card"
    :class="{ 'card-clickable': true }"
    @click="emit('select', task)"
  >
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 头部 -->
    <div class="task-card-header">
      <div class="flex items-center gap-2">
        <ChartBarIcon class="w-4 h-4 text-accent" />
        <span class="task-card-title">{{ task.name }}</span>
        <span
          :class="`badge ${taskStatusBadge[task.status]}`"
          style="font-size:8px;"
        >
          {{ taskStatusNames[task.status] }}
        </span>
      </div>
      <div class="flex gap-1">
        <button
          class="icon-btn task-action-btn"
          :class="{ active: task.favorite }"
          :title="task.favorite ? t('common.unfavorite') : t('common.favorite')"
          @click.stop="emit('toggleFavorite', task.id)"
        >
          <StarSolidIcon
            v-if="task.favorite"
            class="w-3.5 h-3.5 text-yellow-400"
          />
          <StarIcon
            v-else
            class="w-3.5 h-3.5"
          />
        </button>
        <button
          class="icon-btn task-action-btn"
          :class="{ active: task.pinned }"
          :title="task.pinned ? t('common.unpin') : t('common.pin')"
          @click.stop="emit('togglePin', task.id)"
        >
          <PaperClipIcon class="w-3.5 h-3.5" />
        </button>
        <button
          class="icon-btn task-action-btn"
          :title="t('common.more')"
          @click.stop="expanded = !expanded"
        >
          <EllipsisVerticalIcon class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- 主体 -->
    <div class="task-card-body">
      <!-- 标签 -->
      <div class="task-card-meta">
        <span
          v-for="tag in task.tags"
          :key="tag"
          class="badge badge-blue"
          style="font-size:8px;"
        >
          {{ tag }}
        </span>
      </div>

      <!-- 进度条 (进行中) -->
      <div
        v-if="task.status === 'running'"
        class="mt-2"
      >
        <div class="progress-bar">
          <div
            class="progress-bar-fill"
            :style="{ width: `${task.progress || 0}%` }"
          />
        </div>
        <div style="font-size:10px; color:var(--text-muted); margin-top:4px;">
          {{ task.current || 0 }}/{{ task.total || 0 }} {{ t('common.file') }}
        </div>
      </div>

      <!-- 错误信息 -->
      <div
        v-if="task.status === 'error'"
        class="text-error"
        style="font-size:10px; margin-top:4px;"
      >
        ⚠ {{ task.error }}
      </div>

      <!-- 完成信息 -->
      <div
        v-if="task.status === 'done'"
        style="font-size:10px; color:var(--text-muted); margin-top:4px;"
      >
        {{ t('common.completed') }} {{ new Date(task.updatedAt).toLocaleString(localeStr.value) }}
      </div>

      <!-- 依赖信息 -->
      <div
        v-if="task.status === 'pending'"
        style="font-size:10px; color:var(--text-muted); margin-top:4px;"
      >
        {{ t('common.pending') }}
      </div>
    </div>

    <!-- 展开详情 -->
    <div
      v-if="expanded"
      class="task-card-detail"
    >
      <div class="divider" />
      <div style="padding-top:8px; font-size:10px; color:var(--text-secondary);">
        <div style="margin-bottom:4px;">
          {{ t('common.type') }}: <code style="font-size:10px;">{{ task.type }}</code>
        </div>
        <div style="margin-bottom:8px;">
          {{ t('common.create') }}: {{ new Date(task.createdAt).toLocaleString(localeStr.value) }}
        </div>

        <!-- 操作按钮 -->
        <div class="flex gap-2">
          <button
            v-if="task.status === 'pending' || task.status === 'done'"
            class="btn btn-primary btn-sm"
            @click.stop="emit('run', task.id)"
          >
            <PlayIcon class="w-3 h-3" />
            <span>{{ task.status === 'done' ? t('common.retry') : t('common.start') }}</span>
          </button>
          <button
            v-if="task.status === 'running'"
            class="btn btn-secondary btn-sm"
            @click.stop="emit('stop', task.id)"
          >
            <StopIcon class="w-3 h-3" />
            <span>{{ t('common.stop') }}</span>
          </button>
          <button
            v-if="task.status === 'error'"
            class="btn btn-primary btn-sm"
            @click.stop="emit('retry', task.id)"
          >
            <ArrowPathIcon class="w-3 h-3" />
            <span>{{ t('common.retry') }}</span>
          </button>
          <button
            class="btn btn-ghost btn-sm"
            @click.stop=""
          >
            <PencilIcon class="w-3 h-3" />
            <span>{{ t('common.edit') }}</span>
          </button>
          <button
            class="btn btn-ghost btn-sm"
            style="color:var(--error);"
            @click.stop="emit('delete', task.id)"
          >
            <TrashIcon class="w-3 h-3" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-card {
  padding: 12px;
}

.task-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.task-card-title {
  font-size: 12px;
  font-weight: 600;
}

.task-action-btn {
  width: 24px;
  height: 24px;
}

.task-action-btn.active {
  color: var(--accent);
}

.task-card-meta {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.task-card-detail {
  animation: slideDown 0.2s ease;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
