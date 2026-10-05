<script setup lang="ts">
/**
 * 递归链节点行：资产名粗体/符号弱化 + 边类型/行号 + 剪枝徽标；
 * hover 高亮、点击资产节点驱动图面选中联动(locate)。
 */
import { useI18n } from 'vue-i18n'
import { useSgvWs } from '../key'
import type { SemanticTraceNode } from '@/services/semantic-asset-service'
// 递归自引用(模板门禁要求显式导入; ESM 自循环合法)
import TraceNodeRow from './TraceNodeRow.vue'

const props = defineProps<{ node: SemanticTraceNode; depth: number }>()
const { t } = useI18n()
const { expanded, traceExpanding, collapsed, highlightId, toggleCollapse, expandNode, locate } = useSgvWs()

function kidsOf(node: SemanticTraceNode): SemanticTraceNode[] {
  return expanded.value?.[node.symbol] ?? node.children ?? []
}
function canExpandMore(node: SemanticTraceNode): boolean {
  return !!(node.truncated || node.seenElsewhere) && !expanded.value?.[node.symbol]
}
function label(n: SemanticTraceNode): string {
  const f = n.file ? ` · ${n.file.split('/').pop()}` : ''
  return n.assetId ? `${n.assetName ?? n.name}${f}` : `${n.name}${f}`
}
function edgeCls(k?: string): string {
  switch (k) {
    case 'calls': return 'text-ctp-red'
    case 'instantiates': return 'text-ctp-peach'
    case 'contains': return 'text-ctp-green'
    default: return 'text-ctp-overlay0'
  }
}
</script>

<template>
  <div>
    <div
      class="group flex cursor-pointer items-center gap-1 rounded px-1 py-0.5 text-[10px] hover:bg-ctp-surface0/60"
      :class="highlightId === node.symbol ? 'bg-ctp-surface0' : ''"
      :style="{ paddingLeft: `${depth * 12 + 4}px` }"
      @mouseenter="highlightId = node.symbol"
      @mouseleave="highlightId === node.symbol && (highlightId = '')"
      @click="locate(node)"
    >
      <span
        class="w-3 shrink-0 text-center text-ctp-overlay0 hover:text-ctp-text"
        @click.stop="kidsOf(node).length && toggleCollapse(node)"
      >{{ kidsOf(node).length ? (collapsed.has(node.symbol) ? '▸' : '▾') : '' }}</span>
      <span class="shrink-0 font-mono text-[9px]" :class="edgeCls(node.edgeKind)">
        {{ node.depth ? (node.edgeKind || '→') : '◎' }}
      </span>
      <span
        class="min-w-0 flex-1 truncate"
        :class="node.assetId ? 'font-medium text-ctp-text' : 'text-ctp-subtext0'"
        :title="label(node)"
      >{{ node.assetId ? (node.assetName || node.name) : node.name }}</span>
      <span v-if="node.line" class="shrink-0 font-mono text-[9px] text-ctp-overlay0">:{{ node.line }}</span>
      <span v-if="node.cycle" class="shrink-0 text-[9px] text-ctp-peach" :title="t('assetMgmt.graph.trace.cycle')">↻</span>
      <span v-if="node.seenElsewhere" class="shrink-0 text-[9px] text-ctp-overlay0" :title="t('assetMgmt.graph.trace.seenElsewhere')">…</span>
      <span v-if="node.truncated" class="shrink-0 font-mono text-[9px] text-ctp-overlay0" :title="t('assetMgmt.graph.trace.truncatedHint')">+{{ node.truncated }}</span>
    </div>
    <div v-if="canExpandMore(node)" class="flex" :style="{ paddingLeft: `${(depth + 1) * 12 + 4}px` }">
      <button
        class="text-[9px] text-ctp-blue hover:underline"
        :disabled="traceExpanding.has(node.symbol)"
        @click.stop="expandNode(node)"
      >{{ traceExpanding.has(node.symbol) ? t('assetMgmt.graph.trace.expanding') : t('assetMgmt.graph.trace.expandMore') }}</button>
    </div>
    <template v-if="kidsOf(node).length && !collapsed.has(node.symbol)">
      <TraceNodeRow v-for="k in kidsOf(node)" :key="`${k.id}:${k.depth}`" :node="k" :depth="depth + 1" />
    </template>
  </div>
</template>
