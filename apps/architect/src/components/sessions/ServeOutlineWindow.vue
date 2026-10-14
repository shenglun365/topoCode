<script setup lang="ts">
/**
 * serve 直通会话大纲浮窗(2026-10)——与主会话 SessionOutlineWindow 交互一致:
 * 拖动/拉伸/LS 持久化几何; 数据源为宿主聚合回合(props 传入, 非会话 REST);
 * 增加关键字检索过滤; 点击条目滚动定位宿主消息流对应回合(锚点宿主持有)。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ListBulletIcon, XMarkIcon, MagnifyingGlassIcon } from '@heroicons/vue/24/outline'

export interface ServeOutlineItem {
  key: number
  kind: 'user' | 'assistant'
  ts: number
  summary: string
  chars: number
  idx: number
}

const props = defineProps<{ items: ServeOutlineItem[] }>()
const emit = defineEmits<{
  (e: 'close'): void
  (e: 'goto', key: number): void
}>()

const { t } = useI18n()

/* ── 检索: 关键字过滤(摘要/原文长度) ── */
const q = ref('')
const filtered = computed(() => {
  const kw = q.value.trim().toLowerCase()
  if (!kw) return props.items
  return props.items.filter((it) => it.summary.toLowerCase().includes(kw))
})

function fmtTs(ts: number): string {
  const d = new Date(ts < 1e12 ? ts * 1000 : ts)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/* ── 浮窗几何: LS 持久化, 拖动/拉伸限定视口(同主会话大纲浮窗) ── */
const WIN_KEY = 'arch.serve.outline.win'
const WIN_MIN_W = 300
const WIN_MIN_H = 200
interface WinGeo { x: number; y: number; w: number; h: number }
const win = ref<WinGeo>(defaultGeo())

function defaultGeo(): WinGeo {
  const w = 360
  const h = 380
  return { x: Math.max(8, window.innerWidth - w - 24), y: Math.max(8, 72), w, h }
}

function clampGeo(g: WinGeo): WinGeo {
  const maxW = Math.max(WIN_MIN_W, Math.floor(window.innerWidth * 0.9))
  const maxH = Math.max(WIN_MIN_H, Math.floor(window.innerHeight * 0.9))
  const w = Math.min(Math.max(g.w, WIN_MIN_W), maxW)
  const h = Math.min(Math.max(g.h, WIN_MIN_H), maxH)
  return {
    w, h,
    x: Math.min(Math.max(g.x, 0), Math.max(0, window.innerWidth - w)),
    y: Math.min(Math.max(g.y, 0), Math.max(0, window.innerHeight - h)),
  }
}

function persistWin() {
  try { localStorage.setItem(WIN_KEY, JSON.stringify(win.value)) } catch { /* 配额满静默 */ }
}

function restoreWin() {
  try {
    const raw = localStorage.getItem(WIN_KEY)
    if (raw) win.value = clampGeo({ ...defaultGeo(), ...JSON.parse(raw) })
  } catch { /* 损坏用默认 */ }
}

function startPointer(gesture: 'move' | 'resize', e: PointerEvent) {
  if (e.button !== 0) return
  const el = e.currentTarget as HTMLElement
  el.setPointerCapture(e.pointerId)
  const startX = e.clientX
  const startY = e.clientY
  const base = { ...win.value }
  const onMove = (ev: PointerEvent) => {
    const dx = ev.clientX - startX
    const dy = ev.clientY - startY
    win.value = clampGeo(gesture === 'move'
      ? { ...base, x: base.x + dx, y: base.y + dy }
      : { ...base, w: base.w + dx, h: base.h + dy })
  }
  const onUp = () => {
    el.removeEventListener('pointermove', onMove)
    el.removeEventListener('pointerup', onUp)
    el.removeEventListener('pointercancel', onUp)
    persistWin()
  }
  el.addEventListener('pointermove', onMove)
  el.addEventListener('pointerup', onUp)
  el.addEventListener('pointercancel', onUp)
}

/** 标题栏按下: 交互元素(检索框/关闭钮)不启动拖动(setPointerCapture 会吞 click)。 */
function onHeaderPointerDown(e: PointerEvent) {
  if ((e.target as HTMLElement | null)?.closest('button, input, textarea, select, a')) return
  startPointer('move', e)
}

function onWindowResize() { win.value = clampGeo(win.value) }

onMounted(() => {
  restoreWin()
  window.addEventListener('resize', onWindowResize)
})
onUnmounted(() => window.removeEventListener('resize', onWindowResize))
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed z-[45] flex flex-col overflow-hidden rounded-xl border border-ctp-surface1 bg-ctp-base shadow-2xl"
      :style="{ left: win.x + 'px', top: win.y + 'px', width: win.w + 'px', height: win.h + 'px' }"
    >
      <!-- 标题栏(拖动把手) -->
      <div
        class="flex shrink-0 cursor-move touch-none select-none items-center gap-1.5 border-b border-ctp-surface0 bg-ctp-mantle px-3 py-2"
        @pointerdown="onHeaderPointerDown"
      >
        <ListBulletIcon class="h-3.5 w-3.5 shrink-0 text-ctp-sky" />
        <span class="text-xs font-semibold text-ctp-text">{{ t('session.outline.title') }}</span>
        <span class="chip shrink-0 bg-ctp-surface0 font-mono text-ctp-overlay1 !text-[9px]">{{ items.length }}</span>
        <span class="flex-1" />
        <button
          class="rounded p-0.5 text-ctp-overlay1 hover:bg-ctp-surface1 hover:text-ctp-text"
          :title="t('session.outline.close')"
          @click.stop="emit('close')"
        >
          <XMarkIcon class="h-4 w-4" />
        </button>
      </div>

      <!-- 检索框 -->
      <div class="relative shrink-0 border-b border-ctp-surface0 px-2 py-1.5">
        <MagnifyingGlassIcon class="pointer-events-none absolute left-4 top-1/2 h-3 w-3 -translate-y-1/2 text-ctp-overlay0" />
        <input
          v-model="q"
          class="input w-full !py-1 !pl-6 text-[11px]"
          :placeholder="t('execSessionView.outlineSearch')"
        >
      </div>

      <!-- 条目: 点击定位宿主消息流回合 -->
      <div class="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
        <p v-if="!items.length" class="py-6 text-center text-[10px] text-ctp-overlay0">
          {{ t('session.outline.empty') }}
        </p>
        <p v-else-if="!filtered.length" class="py-6 text-center text-[10px] text-ctp-overlay0">
          {{ t('common.noResults') }}
        </p>
        <button
          v-for="it in filtered"
          :key="it.key"
          class="block w-full rounded border border-ctp-surface1/60 bg-ctp-mantle/60 px-2 py-1 text-left transition-colors hover:border-ctp-blue/40 hover:bg-ctp-surface0/60"
          :title="it.summary"
          @click="emit('goto', it.key)"
        >
          <div class="flex items-center gap-1.5">
            <span class="shrink-0 font-mono text-[9px]" :class="it.kind === 'user' ? 'text-ctp-sky' : 'text-ctp-peach'">
              {{ String(it.idx + 1).padStart(2, '0') }}·{{ it.kind === 'user' ? 'U' : 'E' }}
            </span>
            <span class="min-w-0 flex-1 truncate text-[10px] text-ctp-subtext1">{{ it.summary || '—' }}</span>
            <span class="shrink-0 font-mono text-[8px] text-ctp-overlay0">{{ fmtTs(it.ts) }}</span>
          </div>
          <div class="mt-0.5 truncate text-[9px] text-ctp-overlay0">
            {{ it.kind === 'assistant' ? t('execSessionView.charsN', { n: it.chars }) : '' }}
          </div>
        </button>
      </div>

      <!-- 右下角拉伸把手 -->
      <div
        class="absolute bottom-0 right-0 h-4 w-4 cursor-nwse-resize touch-none"
        :title="t('session.outline.resize')"
        @pointerdown="startPointer('resize', $event)"
      >
        <svg viewBox="0 0 16 16" class="h-full w-full text-ctp-overlay1/60">
          <path d="M14 6 L6 14 M14 10 L10 14" stroke="currentColor" stroke-width="1.5" fill="none" />
        </svg>
      </div>
    </div>
  </Teleport>
</template>
