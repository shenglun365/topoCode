<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ChevronDownIcon } from '@heroicons/vue/24/outline'

export interface DropdownOption<V extends string = string> {
  value: V
  label: string
}

const props = defineProps<{
  modelValue: string
  options: DropdownOption[]
  fullscreen?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const open = ref(false)
const rootRef = ref<HTMLDivElement>()

const currentLabel = computed(() =>
  props.options.find(o => o.value === props.modelValue)?.label ?? ''
)

function onDocClick(e: MouseEvent) {
  if (rootRef.value && !rootRef.value.contains(e.target as Node)) {
    open.value = false
  }
}

function select(value: string) {
  emit('update:modelValue', value)
  open.value = false
}

onMounted(() => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div
    ref="rootRef"
    class="td-root"
  >
    <button
      class="td-btn"
      @click.stop="open = !open"
    >
      <span class="td-label">{{ currentLabel }}</span>
      <ChevronDownIcon class="td-chevron" />
    </button>
    <div
      v-if="open"
      class="td-menu"
      :class="{ 'td-menu-up': props.fullscreen }"
    >
      <button
        v-for="opt in options"
        :key="opt.value"
        class="td-item"
        :class="{ active: props.modelValue === opt.value }"
        @click="select(opt.value)"
      >
        {{ opt.label }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.td-root { position: relative; flex-shrink: 0; }
.td-btn {
  display: flex; align-items: center; gap: 0.15rem;
  height: 24px; padding: 0.15rem 0.35rem;
  background: var(--bg-tertiary); border: 1px solid var(--border);
  border-radius: 0.25rem; color: var(--text-muted);
  cursor: pointer; font-size: 0.65rem; font-weight: 500;
  white-space: nowrap; transition: all 0.15s;
}
.td-btn:hover { color: var(--text-primary); border-color: var(--accent); }
.td-label { line-height: 1; }
.td-chevron { width: 10px; height: 10px; flex-shrink: 0; }

.td-menu {
  position: absolute; top: 100%; left: 0; margin-top: 4px;
  min-width: 100%; background: var(--bg-primary);
  border: 1px solid var(--border); border-radius: 0.35rem;
  box-shadow: 0 4px 16px rgba(0,0,0,0.35); z-index: 100;
  padding: 0.25rem; display: flex; flex-direction: column; gap: 1px;
}
.td-menu-up {
  top: auto; bottom: 100%; margin-top: 0; margin-bottom: 4px;
}
.td-item {
  display: flex; align-items: center;
  padding: 0.3rem 0.5rem; font-size: 0.7rem;
  background: transparent; border: none; border-radius: 0.2rem;
  color: var(--text-primary); cursor: pointer;
  white-space: nowrap; transition: background 0.1s;
}
.td-item:hover { background: var(--bg-tertiary); }
.td-item.active { color: var(--accent, #7c3aed); }
</style>
