<template>
  <div
    v-if="items.length || loading"
    class="mt-1.5 rounded border border-ctp-surface1/60 bg-ctp-mantle/50 px-2 py-1"
  >
    <button
      class="flex w-full items-center gap-1 text-[9px] text-ctp-overlay0 hover:text-ctp-subtext1"
      @click="open = !open"
    >
      <ChevronRightIcon
        v-if="!open"
        class="w-2.5 h-2.5"
      />
      <ChevronDownIcon
        v-else
        class="w-2.5 h-2.5"
      />
      <span>执行流</span>
      <span class="font-mono">{{ items.length }}</span>
      <span class="flex-1" />
      <span class="text-[8px] text-ctp-overlay0">A6.2 item 投影</span>
    </button>
    <div
      v-if="open"
      class="mt-1 max-h-40 space-y-0.5 overflow-y-auto"
    >
      <div
        v-for="it in items"
        :key="it.id"
        class="flex items-start gap-1 text-[9px] leading-tight"
      >
        <span
          class="w-3 shrink-0 text-center font-mono"
          :class="typeCls(it)"
        >{{ typeIcon(it) }}</span>
        <span class="min-w-0 flex-1 truncate text-ctp-subtext0">{{ it.text || typeLabel(it) }}</span>
        <span class="shrink-0 text-ctp-overlay0">{{ fmtTime(it.createdAt) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ChevronDownIcon, ChevronRightIcon } from '@heroicons/vue/24/outline'
import { apiGet } from '@/services/api-client'

const props = defineProps<{ convId?: string; taskId: string }>()

const open = ref(false)
const loading = ref(false)
const items = ref<any[]>([])
let unlisten: (() => void) | null = null

const ICONS: Record<string, string> = {
  tool_call: '⚙', file_change: '✎', notice: 'ℹ', event: '·',
}
const LABELS: Record<string, string> = {
  tool_call: '工具调用', file_change: '文件变更', notice: '通知', event: '事件',
}

function typeIcon(it: any): string {
  if (it.type === 'tool_call') return it.status === 'error' ? '✗' : it.status === 'ok' ? '✓' : '▶'
  return ICONS[it.type] || '·'
}
function typeLabel(it: any): string {
  return LABELS[it.type] || it.type
}
function typeCls(it: any): string {
  if (it.type === 'tool_call') {
    if (it.status === 'error') return 'text-ctp-red'
    if (it.status === 'ok') return 'text-ctp-green'
    return 'text-ctp-yellow'
  }
  if (it.type === 'file_change') return 'text-ctp-blue'
  return 'text-ctp-overlay0'
}
function fmtTime(ts: any): string {
  const n = Number(ts)
  if (!n) return ''
  const d = new Date(n)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

async function load() {
  if (!props.convId || !props.taskId) return
  loading.value = true
  try {
    const res = await apiGet<{ items: any[] }>(
      `/sessions/${props.convId}/items?taskId=${encodeURIComponent(props.taskId)}&limit=100`)
    items.value = (res?.items || []).slice().reverse()   // 旧→新
  } catch { /* 静默(流面板非关键路径) */ } finally {
    loading.value = false
  }
}

function onLive(ev: Event) {
  const d = (ev as CustomEvent).detail || {}
  if (d.taskId !== props.taskId || !Array.isArray(d.items)) return
  const known = new Set(items.value.map((x) => x.id))
  for (const it of d.items) {
    if (!known.has(it.id)) items.value.push(it)   // SSE 事件 seq 有序, 追加即可
  }
}

onMounted(() => {
  void load()
  window.addEventListener('arch:stream-items', onLive as EventListener)
  unlisten = () => window.removeEventListener('arch:stream-items', onLive as EventListener)
})
onBeforeUnmount(() => unlisten?.())
</script>
