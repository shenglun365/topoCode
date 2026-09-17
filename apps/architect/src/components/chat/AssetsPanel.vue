<template>
  <div class="border-t border-ctp-surface0 shrink-0">
    <!-- 折叠条 -->
    <button
      class="flex w-full items-center gap-1.5 px-2.5 py-1 text-[10px] text-ctp-overlay1 hover:text-ctp-subtext1"
      @click="toggle"
    >
      <ChevronRightIcon v-if="!open" class="w-3 h-3" />
      <ChevronDownIcon v-else class="w-3 h-3" />
      <CubeTransparentIcon class="w-3.5 h-3.5 text-ctp-teal" />
      <span class="font-medium">知识资产</span>
      <span
        v-if="total"
        class="chip !text-[9px] bg-ctp-teal/15 text-ctp-teal font-mono"
      >{{ total }}</span>
      <span class="flex-1" />
      <span
        v-if="open"
        class="text-[9px] text-ctp-overlay0"
      >任务回执/里程碑自动沉淀 · 供 agent 检索复用</span>
    </button>
    <!-- 面板体 -->
    <div
      v-if="open"
      class="max-h-56 overflow-y-auto px-2.5 pb-2"
    >
      <div class="mb-1.5 flex items-center gap-1 flex-wrap">
        <button
          v-for="k in KINDS"
          :key="k.v"
          class="chip !text-[9px] font-mono transition-colors"
          :class="kind === k.v
            ? 'bg-ctp-teal/20 text-ctp-teal'
            : 'bg-ctp-surface0/60 text-ctp-overlay0 hover:text-ctp-subtext1'"
          @click="kind = k.v; load()"
        >{{ k.label }}</button>
        <input
          v-model="q"
          class="input !py-0.5 !px-1.5 !text-[10px] w-36"
          placeholder="检索标题/正文…"
          @keydown.enter="load"
        />
        <ArrowPathIcon
          class="w-3.5 h-3.5 text-ctp-overlay0 hover:text-ctp-subtext1 cursor-pointer"
          :class="loading ? 'animate-spin' : ''"
          @click="load"
        />
      </div>
      <p
        v-if="!assets.length && !loading"
        class="py-2 text-center text-[10px] text-ctp-overlay0"
      >暂无资产——任务回执与里程碑报告完成后自动沉淀至此</p>
      <div
        v-for="a in assets"
        :key="a.id"
        class="group mb-1 flex items-start gap-1.5 rounded border border-ctp-surface1 bg-ctp-mantle/60 px-2 py-1"
      >
        <span
          class="chip !text-[9px] shrink-0 font-mono"
          :class="kindCls(a.type)"
        >{{ kindLabel(a.type) }}</span>
        <div class="min-w-0 flex-1">
          <div class="truncate text-[11px] text-ctp-subtext1">{{ a.title || '(无标题)' }}</div>
          <div class="truncate text-[9px] text-ctp-overlay0">
            <template v-if="nFiles(a)"> · {{ nFiles(a) }} 文件</template>
            <template v-if="a.importance"> · ★</template>
            · {{ fmtTime(a.createdAt) }}
          </div>
        </div>
        <button
          v-if="!readOnly"
          class="shrink-0 text-[9px] text-ctp-overlay0 opacity-0 transition-opacity hover:text-ctp-red group-hover:opacity-100"
          title="删除"
          @click="remove(a)"
        >✕</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ArrowPathIcon, ChevronDownIcon, ChevronRightIcon, CubeTransparentIcon } from '@heroicons/vue/24/outline'
import { apiDelete, apiGet } from '@/services/api-client'

const props = defineProps<{ convId?: string; readOnly?: boolean }>()

const open = ref(false)
const loading = ref(false)
const assets = ref<any[]>([])
const total = ref(0)
const kind = ref('')
const q = ref('')

const KINDS = [
  { v: '', label: '全部' },
  { v: 'execution_report', label: '回执' },
  { v: 'analysis', label: '分析' },
  { v: 'artifact', label: '产物' },
  { v: 'error', label: '错误' },
  { v: 'error_pattern', label: '模式' },
]

const KIND_CLS: Record<string, string> = {
  execution_report: 'bg-ctp-blue/15 text-ctp-blue',
  analysis: 'bg-ctp-teal/15 text-ctp-teal',
  artifact: 'bg-ctp-mauve/15 text-ctp-mauve',
  error: 'bg-ctp-red/15 text-ctp-red',
  error_pattern: 'bg-ctp-yellow/15 text-ctp-yellow',
}
const KIND_LABEL: Record<string, string> = {
  execution_report: '回执', analysis: '分析', artifact: '产物',
  error: '错误', error_pattern: '模式',
}

function kindCls(k: string): string {
  return KIND_CLS[k] || 'bg-ctp-surface1 text-ctp-overlay0'
}
function kindLabel(k: string): string {
  return KIND_LABEL[k] || k || '单元'
}
function nFiles(u: any): number {
  const f = u?.refs?.files
  return Array.isArray(f) ? f.length : 0
}
function fmtTime(ts: any): string {
  const n = Number(ts)
  return n ? new Date(n).toLocaleString() : ''
}

async function toggle() {
  open.value = !open.value
  if (open.value && !assets.value.length) await load()
}

async function load() {
  if (!props.convId) return
  loading.value = true
  try {
    const params = new URLSearchParams({ convId: props.convId, limit: '100' })
    if (kind.value) params.set('type', kind.value)
    if (q.value.trim()) params.set('q', q.value.trim())
    const res = await apiGet<{ units: any[] }>(`/units?${params.toString()}`)
    assets.value = res?.units || []
    if (!kind.value && !q.value.trim()) total.value = assets.value.length
  } catch { /* 保持现状 */ } finally {
    loading.value = false
  }
}

async function remove(u: any) {
  try {
    await apiDelete(`/units/${u.id}`)
    assets.value = assets.value.filter((x) => x.id !== u.id)
  } catch { /* 静默 */ }
}
</script>
