<script setup lang="ts">
defineProps<{
  visible: boolean
  pos: { x: number; y: number }
  nodeId: string
  graphCommId: string
  isExternal: boolean
  hasChildren: boolean
  centerNodes: string[]
}>()
const emit = defineEmits<{
  copy: []
  drilldown: []
  center: []
  openDoc: []
  saveNote: []
}>()
</script>

<template>
  <div v-if="visible" class="ctx-menu" :style="{ left: pos.x + 'px', top: pos.y + 'px' }">
    <div class="ctx-item" @click.stop="emit('copy')">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>
      <span>复制节点信息</span>
    </div>
    <div class="ctx-divider"></div>
    <div v-if="!isExternal && nodeId !== graphCommId && hasChildren" class="ctx-item" @click.stop="emit('drilldown')">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/><path d="M11 8v6M8 11h6"/></svg>
      <span>下钻 (查看下级)</span>
    </div>
    <div class="ctx-item" @click.stop="emit('openDoc')">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
      <span>打开文档</span>
    </div>
    <div class="ctx-divider"></div>
    <div class="ctx-item" @click.stop="emit('center')">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="8"/><line x1="12" y1="1" x2="12" y2="4"/><line x1="12" y1="20" x2="12" y2="23"/><line x1="1" y1="12" x2="4" y2="12"/><line x1="20" y1="12" x2="23" y2="12"/></svg>
      <span>{{ centerNodes.includes(nodeId) ? '取消居中' : '中心视图' }}</span>
    </div>
    <div class="ctx-divider"></div>
    <div class="ctx-item" @click.stop="emit('saveNote')">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
      <span>存入便签</span>
    </div>
  </div>
</template>
