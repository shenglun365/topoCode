<script setup lang="ts">
/**
 * 链路跟踪侧栏(深度探索)：上/下游链树逐层呈现——整链一次到位(受限 DFS)，
 * 被剪枝/跨分支引用的节点懒加载补全；点击资产节点驱动图面选中联动。
 * 与邻域聚焦互补不交叉(工具栏互斥开启)。
 */
import { useI18n } from 'vue-i18n'
import { useSgvWs } from '../key'
import TraceNodeRow from './TraceNodeRow.vue'

const { t } = useI18n()
const {
  traceMode, direction, loading, degraded, tree, extraRoots, error,
  setDirection, close,
} = useSgvWs()
</script>

<template>
  <div
    v-if="traceMode"
    class="absolute bottom-2 right-2 top-2 z-30 flex w-72 flex-col overflow-hidden rounded-lg border border-ctp-surface1 bg-ctp-mantle/95 shadow-xl"
  >
    <div class="flex shrink-0 items-center gap-1 border-b border-ctp-surface0 px-2 py-1.5">
      <span class="text-[12px] font-semibold text-ctp-text">{{ t('assetMgmt.graph.trace.title') }}</span>
      <span class="flex-1" />
      <button
        class="rounded px-1.5 py-0.5 text-[10px]"
        :class="direction === 'down' ? 'bg-ctp-surface0 text-ctp-text' : 'text-ctp-overlay1 hover:text-ctp-text'"
        @click="setDirection('down')"
      >{{ t('assetMgmt.graph.trace.down') }}</button>
      <button
        class="rounded px-1.5 py-0.5 text-[10px]"
        :class="direction === 'up' ? 'bg-ctp-surface0 text-ctp-text' : 'text-ctp-overlay1 hover:text-ctp-text'"
        @click="setDirection('up')"
      >{{ t('assetMgmt.graph.trace.up') }}</button>
      <button class="ml-1 text-ctp-overlay0 hover:text-ctp-red" :title="t('common.close')" @click="close">✕</button>
    </div>

    <div v-if="degraded" class="shrink-0 bg-ctp-yellow/10 px-2 py-1 text-[10px] text-ctp-yellow">
      {{ t('assetMgmt.graph.trace.degraded') }}
    </div>
    <div v-if="error" class="shrink-0 bg-ctp-red/10 px-2 py-1 text-[10px] text-ctp-red">{{ error }}</div>

    <div class="min-h-0 flex-1 overflow-y-auto p-1.5">
      <div v-if="loading" class="py-6 text-center text-[11px] text-ctp-overlay1">{{ t('assetMgmt.graph.trace.loading') }}</div>
      <div v-else-if="!tree" class="py-6 text-center text-[11px] text-ctp-overlay0">{{ t('assetMgmt.graph.trace.empty') }}</div>
      <template v-else>
        <TraceNodeRow :node="tree" :depth="0" />
        <TraceNodeRow v-for="er in extraRoots" :key="er.id" :node="er" :depth="0" />
      </template>
    </div>
  </div>
</template>
