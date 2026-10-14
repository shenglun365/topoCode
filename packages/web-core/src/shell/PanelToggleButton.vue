<script setup lang="ts">
import './toolbar.css'
import { tShell } from './i18n'

/** 右面板切换（P2）：/app 左面板与文件树已移除，仅保留右面板（AI 助手/分析明细）。 */
const props = withDefaults(defineProps<{
  modelValue: boolean
  label?: string
}>(), {
  label: '',
})

const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
}>()

function toggle() {
  emit('update:modelValue', !props.modelValue)
}
</script>

<template>
  <button
    class="toolbar-btn"
    :class="{ active: modelValue }"
    type="button"
    :title="label || tShell('rightPanel')"
    :aria-pressed="modelValue"
    @click="toggle"
  >
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M15 3v18" />
    </svg>
  </button>
</template>
