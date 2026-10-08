<script setup lang="ts">
/**
 * 组件资产卡：元数据 + 变更统计 + 变更文件/清单 + 依赖联动 + AI 语义解读 + 引用草稿。
 * 浮卡形态(选中组件节点弹出), 可拖动; AI 解读 arch_symbol_notes 缓存/可重生成。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, SparklesIcon, CubeTransparentIcon, ClipboardIcon, XMarkIcon, ArrowRightOnRectangleIcon } from '@heroicons/vue/24/outline'
import type { CompGraphNode } from '@/services/semantic-asset-service'
import { semanticAssetService } from '@/services/semantic-asset-service'
import { copyText } from '@/utils/clipboard'
import { requestDraftRef } from '@/pages/asset-workspace/draft-ref-bus'

const props = defineProps<{
  node: CompGraphNode
  /** 组件→变更文件清单(加载中可能为空)。 */
  changedFiles: Record<string, string[]>
  /** 全部组件(依赖名解析/点击跳转)。 */
  allNodes: CompGraphNode[]
  busy?: boolean
}>()
const emit = defineEmits<{
  close: []
  enter: [id: string]
  locate: [compId: string]
}>()

const { t } = useI18n()
const dragPos = ref<{ x: number; y: number } | null>(null)
const dragging = ref(false)
let dragOff = { dx: 0, dy: 0 }

function beginDrag(e: PointerEvent) {
  if (e.button !== 0) return
  // 交互元素(关闭钮等)不启动拖拽——否则 setPointerCapture 把 click 重定向到
  // 头部, 按钮 @click 永不触发(关不掉)且卡片切 absolute 定位(宽度跳变)
  if ((e.target as HTMLElement).closest("button, a, input, textarea, select")) return
  dragging.value = true
  // 指针捕获: 拖出元素仍持续收到 move/up——否则松开在元素外时 up 丢失, dragging 卡死
  try { (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId) } catch { /* ignore */ }
  const el = (e.currentTarget as HTMLElement).closest('.comp-card') as HTMLElement
  const r = el.getBoundingClientRect()
  dragOff = { dx: e.clientX - r.left, dy: e.clientY - r.top }
  dragPos.value = { x: r.left, y: r.top }
  console.debug('[comp-graph] comp-card drag begin (captured pid=%s)', e.pointerId)
}
function onDrag(e: PointerEvent) {
  if (!dragging.value) return
  dragPos.value = { x: e.clientX - dragOff.dx, y: e.clientY - dragOff.dy }
}
function endDrag(e: PointerEvent) {
  if (!dragging.value) return
  dragging.value = false
  try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId) } catch { /* ignore */ }
  console.debug('[comp-graph] comp-card drag end')
}

const deps = computed(() =>
  props.node.dependsOn
    .map((id) => props.allNodes.find((n) => n.id === id))
    .filter((n): n is CompGraphNode => !!n))

const changedAll = computed(() => {
  const out: { file: string; st: string }[] = []
  for (const st of ('added,modified,deleted').split(',')) {
    for (const f of props.node.changedFiles[st] || props.changedFiles[st] || []) {
      out.push({ file: f, st })
    }
  }
  return out
})

// ---- AI 语义解读 ----
const note = ref('')
const noteLoading = ref(false)
const noteCached = ref(false)
const noteError = ref('')
const noteElapsed = ref(0)
let noteTimer: ReturnType<typeof setInterval> | null = null

async function loadNote(force = false) {
  noteLoading.value = true
  noteError.value = ''
  noteElapsed.value = 0
  if (noteTimer) clearInterval(noteTimer)
  noteTimer = setInterval(() => { noteElapsed.value += 1 }, 1000)
  try {
    const r = await semanticAssetService.nodeNotes('component', props.node.id, force)
    note.value = r?.note || ''
    noteCached.value = !!r?.cached
    if (r?.error) noteError.value = r.error
  } catch (e: any) {
    noteError.value = e?.message || 'failed'
  } finally {
    if (noteTimer) { clearInterval(noteTimer); noteTimer = null }
    noteLoading.value = false
  }
}
loadNote()

function stCls(st: string): string {
  return st === 'added' ? 'text-ctp-green' : st === 'deleted' ? 'text-ctp-red' : 'text-ctp-blue'
}

async function quoteDraft() {
  const lines = [
    `> **引用** · 组件 \`${props.node.id}「${props.node.name}」\``,
    `> 来源：组件图谱 · ${props.node.fileCount} 文件 · 依赖 ${props.node.dependsOn.length} 项 · 变更 +${props.node.change.added} ~${props.node.change.modified} -${props.node.change.deleted}`,
    note.value ? `>\n> ${note.value.replace(/\n/g, '\n> ')}` : '',
  ].filter(Boolean)
  requestDraftRef({
    source: { compId: props.node.id, assetName: props.node.name },
    text: lines.join('\n'),
  })
}

const copied = ref(false)
async function copyLoc() {
  if (await copyText(`component:${props.node.id} ${props.node.name}`)) {
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  }
}
</script>

<template>
  <div
    class="comp-card fixed z-50 w-[min(560px,92vw)] max-h-[80vh] flex flex-col rounded-lg bg-ctp-mantle border border-ctp-surface1 shadow-xl overflow-hidden"
    :style="dragPos ? { left: `${dragPos.x}px`, top: `${dragPos.y}px` } : {}"
  >
    <div
      class="flex items-center gap-2 px-3 pt-2.5 pb-1.5 border-b border-ctp-surface0 shrink-0 cursor-move"
      @pointerdown="beginDrag"
      @pointermove="onDrag"
      @pointerup="endDrag"
      @pointercancel="endDrag"
    >
      <CubeTransparentIcon class="w-4 h-4 text-ctp-mauve shrink-0" />
      <span class="text-sm font-medium text-ctp-text truncate">{{ node.name }}</span>
      <span v-if="node.kind" class="chip bg-ctp-surface0 text-ctp-subtext0 !text-[9px]">{{ node.kind }}</span>
      <span class="chip bg-ctp-surface0 text-ctp-overlay0 !text-[9px]">{{ node.level }}</span>
      <span class="flex-1" />
      <button class="p-0.5 rounded hover:bg-ctp-surface0 text-ctp-overlay1 hover:text-ctp-text" :title="t('common.close')" @click="emit('close')">
        <XMarkIcon class="w-4 h-4" />
      </button>
    </div>

    <div class="flex-1 min-h-0 overflow-y-auto p-3 space-y-3 text-xs">
      <p v-if="node.desc" class="text-ctp-subtext0 leading-relaxed">{{ node.desc }}</p>

      <div class="flex items-center gap-2 flex-wrap">
        <span class="chip bg-ctp-surface0 text-ctp-subtext0">{{ t('compGraph.files') }} {{ node.fileCount }}</span>
        <span class="chip" :class="node.change.added ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-surface0 text-ctp-overlay0'">+{{ node.change.added }}</span>
        <span class="chip" :class="node.change.modified ? 'bg-ctp-blue/15 text-ctp-blue' : 'bg-ctp-surface0 text-ctp-overlay0'">~{{ node.change.modified }}</span>
        <span class="chip" :class="node.change.deleted ? 'bg-ctp-red/15 text-ctp-red' : 'bg-ctp-surface0 text-ctp-overlay0'">-{{ node.change.deleted }}</span>
        <span class="flex-1" />
        <button class="btn !py-1 !px-2.5 !text-[10px] btn-mauve" @click="emit('enter', node.id)">
          <ArrowRightOnRectangleIcon class="w-3.5 h-3.5" />{{ t('compGraph.enter') }}
        </button>
      </div>

      <div v-if="deps.length">
        <p class="text-[10px] text-ctp-overlay1 mb-1">{{ t('compGraph.dependsOn') }}</p>
        <div class="flex flex-wrap gap-1">
          <button
            v-for="d in deps" :key="d.id"
            class="chip bg-ctp-surface0 text-ctp-subtext0 hover:bg-ctp-surface1 hover:text-ctp-text"
            :title="t('compGraph.locateDep')"
            @click="emit('locate', d.id)"
          >{{ d.name }}</button>
        </div>
      </div>

      <div v-if="changedAll.length">
        <p class="text-[10px] text-ctp-overlay1 mb-1">{{ t('compGraph.changedFiles', { n: changedAll.length }) }}</p>
        <div class="space-y-0.5 max-h-28 overflow-y-auto">
          <div v-for="(c, i) in changedAll" :key="c.file + i" class="flex items-center gap-2 text-[11px]">
            <span :class="stCls(c.st)" class="w-3 shrink-0 text-center font-mono">
              {{ c.st === 'added' ? '+' : c.st === 'deleted' ? '−' : '~' }}
            </span>
            <span class="font-mono text-ctp-subtext1 truncate">{{ c.file }}</span>
          </div>
        </div>
      </div>

      <div class="border-t border-ctp-surface0 pt-2">
        <div class="flex items-center gap-1.5 mb-1.5">
          <SparklesIcon class="w-3.5 h-3.5 text-ctp-mauve" />
          <span class="text-[10px] text-ctp-overlay1">{{ t('compGraph.aiNote') }}</span>
          <span v-if="noteCached && note" class="text-[9px] text-ctp-overlay0">{{ t('compGraph.cached') }}</span>
          <span class="flex-1" />
          <button
            class="p-0.5 rounded hover:bg-ctp-surface0 text-ctp-overlay1 hover:text-ctp-mauve"
            :title="t('compGraph.regenerate')" :disabled="noteLoading"
            @click="loadNote(true)"
          ><ArrowPathIcon class="w-3.5 h-3.5" :class="noteLoading ? 'animate-spin' : ''" /></button>
        </div>
        <p v-if="noteLoading" class="text-[11px] text-ctp-overlay0 animate-pulse">
          {{ t('app.loading') }} {{ noteElapsed }}s
        </p>
        <p v-else-if="noteError" class="text-[11px] text-ctp-peach">{{ noteError }}</p>
        <p v-else-if="note" class="text-[11px] text-ctp-subtext1 leading-relaxed whitespace-pre-wrap">{{ note }}</p>
        <button v-else class="btn !py-1 !px-2.5 !text-[10px]" @click="loadNote(false)">
          <SparklesIcon class="w-3.5 h-3.5" />{{ t('compGraph.genNote') }}
        </button>
      </div>
    </div>

    <div class="shrink-0 flex items-center gap-2 px-3 py-1.5 border-t border-ctp-surface0">
      <button class="text-[10px] text-ctp-mauve hover:underline flex items-center gap-1" @click="quoteDraft">
        <ClipboardIcon class="w-3 h-3" />{{ t('compGraph.quoteDraft') }}
      </button>
      <button class="text-[10px] text-ctp-overlay1 hover:text-ctp-text hover:underline" @click="copyLoc">
        {{ copied ? t('compGraph.copied') : t('compGraph.copyLoc') }}
      </button>
    </div>
  </div>
</template>
