<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronDownIcon, ChevronRightIcon } from '@heroicons/vue/24/solid'
import type { TaskNode } from '@/types'

const props = defineProps<{ task: TaskNode; depth?: number; selectedId?: string }>()
const emit = defineEmits<{ select: [id: string] }>()

const { t } = useI18n()
const depth = props.depth ?? 0
const expanded = ref(depth < 2)

const statusColor: Record<string, string> = {
  pending: 'text-ctp-overlay0',
  'in-progress': 'text-ctp-blue',
  reviewing: 'text-ctp-yellow',
  done: 'text-ctp-green',
  blocked: 'text-ctp-red',
}

const kindColor: Record<string, string> = {
  epic: 'bg-ctp-mauve/15 text-ctp-mauve',
  story: 'bg-ctp-sky/15 text-ctp-sky',
  task: 'bg-ctp-surface0 text-ctp-subtext1',
  check: 'bg-ctp-peach/15 text-ctp-peach',
}

const isSelected = computed(() => props.selectedId === props.task.id)
const hasChildren = computed(() => (props.task.children?.length ?? 0) > 0)
const children = computed(() => props.task.children ?? [])
</script>

<template>
  <div>
    <div
      class="flex items-center gap-1.5 py-1 px-1 rounded cursor-pointer transition-colors"
      :class="[isSelected ? 'bg-ctp-blue/10 ring-1 ring-ctp-blue/30' : 'hover:bg-ctp-surface0', { 'pl-3': depth > 0 }]"
      @click="emit('select', task.id)"
    >
      <button
        v-if="hasChildren"
        class="shrink-0 text-ctp-overlay0 hover:text-ctp-text"
        @click.stop="expanded = !expanded"
      >
        <component
          :is="expanded ? ChevronDownIcon : ChevronRightIcon"
          class="w-3.5 h-3.5"
        />
      </button>
      <span
        v-else
        class="w-3.5 shrink-0"
      />
      <span
        class="chip"
        :class="kindColor[task.kind]"
      >{{ t(`coding.kind.${task.kind}`) }}</span>
      <span
        class="flex-1 truncate text-xs"
        :class="statusColor[task.status]"
      >{{ task.title }}</span>
      <span class="text-[10px] text-ctp-overlay1">{{ task.estMin }}m</span>
    </div>
    <div
      v-if="expanded && hasChildren"
      class="border-l border-ctp-surface0 ml-2 pl-1.5"
    >
      <TaskTree
        v-for="child in children"
        :key="child.id"
        :task="child"
        :depth="depth + 1"
        :selected-id="selectedId"
        @select="(id) => emit('select', id)"
      />
    </div>
  </div>
</template>
