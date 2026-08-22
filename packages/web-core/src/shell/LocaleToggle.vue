<script setup lang="ts">
import { ref } from 'vue'
import './toolbar.css'
import { localeNames } from '../i18n/setup'
import type { SupportedLocale } from '../i18n/setup'
import { readLocale, writeLocale } from './useAppPrefs'
import { tShell } from './i18n'

/**
 * 统一语言切换（P2）：写入共享键 `topoone-locale`（读兼容旧键 `locale`），
 * 经 `update:locale` 事件由宿主 app 同步其 vue-i18n 实例。
 */
const emit = defineEmits<{
  (e: 'update:locale', locale: SupportedLocale): void
}>()

const locale = ref<SupportedLocale>(readLocale())

function onChange(e: Event) {
  const l = (e.target as HTMLSelectElement).value as SupportedLocale
  locale.value = l
  writeLocale(l)
  emit('update:locale', l)
}
</script>

<template>
  <select class="toolbar-select" :value="locale" :title="tShell('language')" :aria-label="tShell('language')" @change="onChange">
    <option v-for="(name, code) in localeNames" :key="code" :value="code">{{ name }}</option>
  </select>
</template>
