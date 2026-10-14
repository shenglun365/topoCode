<script setup lang="ts">
/**
 * 链路跟踪侧栏(trace tab 常驻)：上/下游链树逐层呈现——整链一次到位(受限 DFS)，
 * 被剪枝/跨分支引用的节点懒加载补全；点击资产节点驱动图面选中联动(不重算链路)。
 * 浮窗可拖动(位置态本地持久化)。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSgvWs } from '../key'
import TraceNodeRow from './TraceNodeRow.vue'

const { t } = useI18n()
const {
  traceMode, direction, traceLoading, degraded, tree, extraRoots, error,
  setDirection, close, refresh,
} = useSgvWs()

// ---- 浮窗拖动(参照工具栏拖动模式; 位置持久化) ----
const POS_KEY = 'arch.graph.tracePanelPos'
const pos = ref<{ x: number; y: number } | null>((() => {
  try {
    const raw = localStorage.getItem(POS_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
})())
const el = ref<HTMLElement | null>(null)
let dragging = false
let start = { x: 0, y: 0 }

function onDown(e: PointerEvent): void {
  if (e.button !== 0) return
  if ((e.target as HTMLElement).closest('button, input')) return
  const host = el.value
  if (!host) return
  if (!pos.value) {
    const r = host.getBoundingClientRect()
    pos.value = { x: r.left, y: r.top }
  }
  dragging = true
  start = { x: e.clientX - pos.value.x, y: e.clientY - pos.value.y }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}
function onMove(e: PointerEvent): void {
  if (!dragging || !pos.value) return
  pos.value = {
    x: Math.max(8, Math.min(window.innerWidth - 120, e.clientX - start.x)),
    y: Math.max(8, Math.min(window.innerHeight - 60, e.clientY - start.y)),
  }
}
function onUp(): void {
  dragging = false
  window.removeEventListener('pointermove', onMove)
  window.removeEventListener('pointerup', onUp)
  try { localStorage.setItem(POS_KEY, JSON.stringify(pos.value)) } catch { /* ignore */ }
}
onMounted(() => window.addEventListener('resize', onUp))
onBeforeUnmount(() => { onUp(); window.removeEventListener('resize', onUp) })
</script>

<template>
  <div
    v-if="traceMode"
    ref="el"
    class="fixed z-30 flex w-72 flex-col overflow-hidden rounded-lg border border-ctp-surface1 bg-ctp-mantle/95 shadow-xl"
    :style="pos
      ? { left: pos.x + 'px', top: pos.y + 'px', height: 'calc(100vh - 10rem)' }
      : { right: '1rem', top: '4rem', bottom: '4rem' }"
  >
    <div
      class="flex shrink-0 cursor-move items-center gap-1 border-b border-ctp-surface0 px-2 py-1.5"
      @pointerdown="onDown"
    >
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
      <button
        class="rounded px-1.5 py-0.5 text-[10px] text-ctp-overlay1 hover:text-ctp-text"
        :title="t('assetMgmt.graph.trace.refresh')"
        @click="refresh()"
      >⟳</button>
      <button class="ml-1 text-ctp-overlay0 hover:text-ctp-red" :title="t('common.close')" @click="close">✕</button>
    </div>

    <div v-if="degraded" class="shrink-0 bg-ctp-yellow/10 px-2 py-1 text-[10px] text-ctp-yellow">
      {{ t('assetMgmt.graph.trace.degraded') }}
    </div>
    <div v-if="error" class="shrink-0 bg-ctp-red/10 px-2 py-1 text-[10px] text-ctp-red">{{ error }}</div>

    <div class="min-h-0 flex-1 overflow-y-auto p-1.5">
      <div v-if="traceLoading" class="py-6 text-center text-[11px] text-ctp-overlay1">{{ t('assetMgmt.graph.trace.loading') }}</div>
      <div v-else-if="!tree" class="py-6 text-center text-[11px] text-ctp-overlay0">{{ t('assetMgmt.graph.trace.empty') }}</div>
      <template v-else>
        <TraceNodeRow :node="tree" :depth="0" />
        <TraceNodeRow v-for="er in extraRoots" :key="er.id" :node="er" :depth="0" />
      </template>
    </div>
  </div>
</template>
