<script setup lang="ts">
/**
 * 卡片收起/展开 chevron 图标(纯视觉, 无交互) — 全部信息卡统一单源。
 * 视觉契约(与需求卡 cv-248 一致): 收起=灰(overlay0) ▶; 展开=蓝(blue) 旋转90° ▼。
 * 交互封装见 CollapseChevron(按钮); 头部整体是按钮的卡(问询卡/digest)直接内联本图标。
 */
import { computed } from 'vue'

const props = defineProps<{ collapsed: boolean }>()

const cls = computed(() =>
  props.collapsed ? 'text-ctp-overlay0' : 'text-ctp-blue rotate-90')
</script>

<template>
  <svg
    class="w-3.5 h-3.5 transition-transform shrink-0"
    :class="cls"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
  ><path d="m9 18 6-6-6-6" /></svg>
</template>
