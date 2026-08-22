<script setup lang="ts">
import './toolbar.css'
import { FONT_SIZES, setFontSize } from './useAppPrefs'
import type { FontSizeTarget } from './useAppPrefs'
import { tShell } from './i18n'

/**
 * 统一字号下拉（P2）：共享键 `topoone-font-size` 存单一 px，
 * 经 `targets` 应用各子模块声明的 CSS 落点（root / --content-font-size 等）。
 */
const props = withDefaults(defineProps<{
  modelValue: number
  targets?: FontSizeTarget[]
}>(), {
  targets: () => ['--content-font-size'] as FontSizeTarget[],
})

const emit = defineEmits<{
  (e: 'update:modelValue', v: number): void
}>()

function onChange(e: Event) {
  const v = Number((e.target as HTMLSelectElement).value)
  setFontSize(v, props.targets)
  emit('update:modelValue', v)
}
</script>

<template>
  <select class="toolbar-select" :value="modelValue" :title="tShell('font')" :aria-label="tShell('font')" @change="onChange">
    <option v-for="s in FONT_SIZES" :key="s" :value="s">{{ s }}px</option>
  </select>
</template>
