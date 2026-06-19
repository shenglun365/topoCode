<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import {
  EllipsisVerticalIcon,
  ArrowPathIcon,
  DocumentArrowDownIcon,
} from '@heroicons/vue/24/outline'
import ToolbarDropdown from './ToolbarDropdown.vue'
import type { DropdownOption } from './ToolbarDropdown.vue'

const props = defineProps<{
  mode: 'force' | 'table' | 'heatmap'
  fullscreen?: boolean
}>()

const emit = defineEmits<{
  'update:mode': [mode: 'force' | 'table' | 'heatmap']
  'reset-view': []
  'export-arch': []
  'fullscreen': []
  'compare': []
}>()

const openMore = ref(false)
const moreRef = ref<HTMLDivElement>()

const modeOptions: DropdownOption[] = [
  { value: 'force', label: '力导向图' },
  { value: 'table', label: '表格' },
  { value: 'heatmap', label: '热力图' },
]

const internalMode = computed({
  get: () => props.mode,
  set: (v) => emit('update:mode', v as 'force' | 'table' | 'heatmap'),
})

function onDocClick(e: MouseEvent) {
  if (moreRef.value && !moreRef.value.contains(e.target as Node)) {
    openMore.value = false
  }
}

onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div class="gt-container">
    <ToolbarDropdown
      v-model="internalMode"
      :options="modeOptions"
      :fullscreen="props.fullscreen"
    />

    <div
      ref="moreRef"
      class="gt-more"
    >
      <button
        class="gt-more-btn"
        @click.stop="openMore = !openMore"
      >
        <EllipsisVerticalIcon class="w-3.5 h-3.5" />
      </button>
      <div
        v-if="openMore"
        class="gt-more-dropdown"
        :class="{ 'gt-more-up': props.fullscreen }"
      >
        <button
          class="gt-more-item"
          @click="emit('reset-view'); openMore = false"
        >
          <ArrowPathIcon class="w-3 h-3" />
          <span>重置视图</span>
        </button>
        <button
          class="gt-more-item"
          @click="emit('export-arch'); openMore = false"
        >
          <DocumentArrowDownIcon class="w-3 h-3" />
          <span>导出架构</span>
        </button>
        <button
          class="gt-more-item"
          @click="emit('compare'); openMore = false"
        >
          <span class="gt-more-item-icon">📊</span>
          <span>对比架构</span>
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gt-container { display: flex; align-items: center; gap: 0.25rem; flex-shrink: 0; }

.gt-more { position: relative; }
.gt-more-btn {
  display: flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; padding: 0;
  background: transparent; border: 1px solid transparent;
  border-radius: 0.25rem; color: var(--text-muted); cursor: pointer;
  transition: all 0.15s;
}
.gt-more-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); border-color: var(--border); }

.gt-more-dropdown {
  position: absolute; top: 100%; right: 0; margin-top: 4px;
  min-width: 120px; background: var(--bg-primary);
  border: 1px solid var(--border); border-radius: 0.35rem;
  box-shadow: 0 4px 16px rgba(0,0,0,0.35); z-index: 100;
  padding: 0.25rem; display: flex; flex-direction: column; gap: 1px;
}
.gt-more-up {
  top: auto; bottom: 100%; margin-top: 0; margin-bottom: 4px;
}
.gt-more-item {
  display: flex; align-items: center; gap: 0.4rem;
  padding: 0.3rem 0.5rem; font-size: 0.7rem;
  background: transparent; border: none; border-radius: 0.2rem;
  color: var(--text-primary); cursor: pointer;
  white-space: nowrap; transition: background 0.1s;
}
.gt-more-item:hover { background: var(--bg-tertiary); }
.gt-more-item-icon { font-size: 0.7rem; }
</style>
