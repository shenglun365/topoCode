<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ListBulletIcon,
  ChevronDownIcon,
} from '@heroicons/vue/24/outline'

/**
 * 解析任务下拉（架构分析 tab 栏内）：
 * - 点选任务 → emit select（打开/切换/关闭 reportHome tab，由宿主决定）
 * - 列表状态与 tab 状态联动：openTaskIds / activeTaskId 由宿主从 tab 计算
 */
const { t } = useI18n()

const props = defineProps<{
  tasks: Array<{ id: string; name: string }>
  openTaskIds: string[]
  activeTaskId: string | null
}>()

const emit = defineEmits<{
  select: [taskId: string]
  toggle: [open: boolean]
}>()

const root = ref<HTMLElement | null>(null)
const open = ref(false)

function toggle() {
  open.value = !open.value
  emit('toggle', open.value)
}

function onItemClick(taskId: string) {
  open.value = false
  emit('select', taskId)
}

function itemState(taskId: string): 'active' | 'open' | 'closed' {
  if (props.activeTaskId === taskId) return 'active'
  if (props.openTaskIds.includes(taskId)) return 'open'
  return 'closed'
}

function onDocClick(e: MouseEvent) {
  if (open.value && root.value && !root.value.contains(e.target as Node)) {
    open.value = false
  }
}
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') open.value = false
}
onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKeydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <div
    ref="root"
    class="task-select"
  >
    <button
      type="button"
      class="task-select-btn"
      :class="{ open }"
      :title="t('analysis.taskSelect')"
      @click.stop="toggle"
    >
      <ListBulletIcon class="task-select-icon" />
      <span class="task-select-label">{{ t('analysis.taskSelect') }}</span>
      <ChevronDownIcon
        class="task-select-chevron"
        :class="{ rotated: open }"
      />
    </button>

    <div
      v-if="open"
      class="task-select-panel"
      @click.stop
    >
      <div
        v-if="tasks.length === 0"
        class="task-select-empty"
      >{{ t('analysis.taskSelectEmpty') }}</div>
      <button
        v-for="task in tasks"
        :key="task.id"
        type="button"
        class="task-select-item"
        :class="[`state-${itemState(task.id)}`]"
        @click="onItemClick(task.id)"
      >
        <span class="task-dot" />
        <span class="task-name">{{ task.name }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.task-select {
  position: relative;
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.task-select-btn {
  display: flex;
  align-items: center;
  gap: calc(6px * var(--ui-scale, 1));
  height: calc(30px * var(--ui-scale, 1));
  margin-left: calc(8px * var(--ui-scale, 1));
  padding: 0 calc(10px * var(--ui-scale, 1));
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, calc(4px * var(--ui-scale, 1)));
  background: transparent;
  color: var(--text-secondary);
  font-size: calc(12px * var(--ui-scale, 1));
  cursor: pointer;
  transition: all 0.15s;
}
.task-select-btn:hover,
.task-select-btn.open {
  border-color: var(--accent);
  color: var(--accent);
}

.task-select-icon {
  width: calc(15px * var(--ui-scale, 1));
  height: calc(15px * var(--ui-scale, 1));
  flex-shrink: 0;
}

.task-select-label {
  white-space: nowrap;
}

.task-select-chevron {
  width: calc(13px * var(--ui-scale, 1));
  height: calc(13px * var(--ui-scale, 1));
  flex-shrink: 0;
  transition: transform 0.15s;
}
.task-select-chevron.rotated {
  transform: rotate(180deg);
}

.task-select-panel {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: 1000;
  min-width: calc(240px * var(--ui-scale, 1));
  max-width: calc(320px * var(--ui-scale, 1));
  max-height: calc(320px * var(--ui-scale, 1));
  overflow-y: auto;
  padding: calc(4px * var(--ui-scale, 1));
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md, calc(6px * var(--ui-scale, 1)));
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.25);
}

.task-select-empty {
  padding: calc(10px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-muted);
}

.task-select-item {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
  width: 100%;
  padding: calc(7px * var(--ui-scale, 1)) calc(10px * var(--ui-scale, 1));
  border: none;
  border-radius: var(--radius-sm, calc(4px * var(--ui-scale, 1)));
  background: transparent;
  color: var(--text-secondary);
  font-size: calc(12px * var(--ui-scale, 1));
  text-align: left;
  cursor: pointer;
  transition: background 0.1s;
}
.task-select-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.task-dot {
  width: calc(6px * var(--ui-scale, 1));
  height: calc(6px * var(--ui-scale, 1));
  border-radius: 50%;
  background: var(--border);
  flex-shrink: 0;
}
.task-select-item.state-open .task-dot {
  background: var(--accent);
}
.task-select-item.state-active {
  background: var(--bg-tertiary);
  color: var(--accent);
}
.task-select-item.state-active .task-dot {
  background: var(--accent);
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent);
}

.task-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
