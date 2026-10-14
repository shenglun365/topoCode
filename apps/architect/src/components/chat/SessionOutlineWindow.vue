<script setup lang="ts">
/**
 * 会话大纲浮窗(K3 布局调整) —— 原 SessionsPage 左栏大纲区块改为可拖动/可拉伸浮窗。
 *
 *  - 开合: 由宿主(ConversationDock 输入框上侧工具栏大纲按钮)控制; 关闭/最小化即缩回按钮。
 *  - 几何: 拖动标题栏移动, 右下角把手拉伸(限定范围内), 尺寸/位置 LS 持久化。
 *  - 标题: 显示回合用户输入; 超过阈值经 LLM 语义缩略(outline-cache 缓存,
 *    随会话/消息删除清理, 见 conversation-store 失效挂钩)。
 *  - 联动: 点击条目滚动定位右栏对话区对应回合(msg-{id} 锚点)。
 */
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ListBulletIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import { apiGet } from '@/services/api-client'
import { sessionService } from '@/services/session-service'
import { outlineAbbrCache } from '@/services/outline-cache'
import { useConversationStore } from '@/stores/conversation-store'

const { t } = useI18n()
const conv = useConversationStore()

const emit = defineEmits<{ (e: 'close'): void }>()

// ── 大纲数据(回合对颗粒度, 同原 SessionsPage K3 区块口径) ──
interface OutlineTurn { id: string; ts: number; prompt: string; response: string; msgCount: number }
interface OutlineCard { id: string; kind: string; ts: number; preview: string }
const outlineTurns = ref<OutlineTurn[]>([])
const outlineCards = ref<OutlineCard[]>([])
const outlineLoading = ref(false)

async function loadOutline(id: string) {
  outlineLoading.value = true
  try {
    const d = await apiGet<{ turns: OutlineTurn[]; cards: OutlineCard[] }>(`/sessions/${id}/outline`)
    outlineTurns.value = d?.turns || []
    outlineCards.value = (d?.cards || []).slice(-20)
  } catch { outlineTurns.value = []; outlineCards.value = [] } finally {
    outlineLoading.value = false
  }
  void abbreviateMissing()
}

watch(() => conv.activeId, (id) => { if (id) void loadOutline(id) }, { immediate: true })

// ── 语义缩略: 阈值以上且回调缺失的条目批量补算 → LS 缓存 → 版本号驱动重渲染 ──
const ABBR_THRESHOLD = 20
const ABBR_MAX_PER_OPEN = 40
const abbrVer = ref(0)

async function abbreviateMissing() {
  const convId = conv.activeId
  if (!convId) return
  const missing = outlineTurns.value
    .filter((ot) => ot.prompt.length > ABBR_THRESHOLD && !outlineAbbrCache.get(convId, ot.id))
    .slice(0, ABBR_MAX_PER_OPEN)
  for (let i = 0; i < missing.length; i += 20) {
    const chunk = missing.slice(i, i + 20)
    try {
      const r = await sessionService.abbreviateOutline(chunk.map((ot) => ({ id: ot.id, text: ot.prompt })))
      for (const it of r.items ?? []) {
        if (it.id && it.short) outlineAbbrCache.put(convId, it.id, it.short)
      }
      abbrVer.value++
    } catch { /* 静默: 保持原文截断显示 */ }
  }
}

/** 条目标题: 缩略缓存命中显示短标题; 否则原文(模板内长文 CSS 截断)。 */
function titleOf(ot: OutlineTurn): string {
  void abbrVer.value
  const convId = conv.activeId
  if (convId && ot.prompt.length > ABBR_THRESHOLD) {
    const c = outlineAbbrCache.get(convId, ot.id)
    if (c) return c
  }
  return ot.prompt || t('session.outline.noPrompt')
}

function gotoTurn(id: string) {
  const el = document.getElementById(`msg-${id}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function fmtOutlineTs(ts: unknown): string {
  const n = Number(ts)
  if (!n) return ''
  const d = new Date(n)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// ── 浮窗几何: LS 持久化(arch.session.outline.win), 拖动/拉伸限定在视口内 ──
const WIN_KEY = 'arch.session.outline.win'
const WIN_MIN_W = 320
const WIN_MIN_H = 220
interface WinGeo { x: number; y: number; w: number; h: number }
const win = ref<WinGeo>(defaultGeo())

function defaultGeo(): WinGeo {
  const w = 380
  const h = 340
  return {
    x: Math.max(8, window.innerWidth - w - 24),
    y: Math.max(8, window.innerHeight - h - 96),
    w, h,
  }
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

/**
 * 标题栏按下(拖动把手): 交互元素(关闭按钮等)不启动拖动——
 * setPointerCapture 会把后续 click 重定向到标题栏, 按钮点击将永远失效。
 */
function onHeaderPointerDown(e: PointerEvent) {
  if ((e.target as HTMLElement | null)?.closest('button, input, textarea, select, a')) return
  startPointer('move', e)
}

function onWindowResize() {
  win.value = clampGeo(win.value)
}

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
      <!-- 标题栏(拖动把手; 关闭按钮等交互元素不触发拖动) -->
      <div
        class="flex shrink-0 cursor-move touch-none select-none items-center gap-1.5 border-b border-ctp-surface0 bg-ctp-mantle px-3 py-2"
        @pointerdown="onHeaderPointerDown"
      >
        <ListBulletIcon class="h-3.5 w-3.5 shrink-0 text-ctp-sky" />
        <span class="text-xs font-semibold text-ctp-text">{{ t('session.outline.title') }}</span>
        <span class="chip shrink-0 bg-ctp-surface0 font-mono text-ctp-overlay1 !text-[9px]">{{ outlineTurns.length }}</span>
        <span class="flex-1" />
        <button
          class="rounded p-0.5 text-ctp-overlay1 hover:bg-ctp-surface1 hover:text-ctp-text"
          :title="t('session.outline.close')"
          @click.stop="emit('close')"
        >
          <XMarkIcon class="h-4 w-4" />
        </button>
      </div>

      <!-- 内容: 回合对条目(点击滚动定位) + 回执卡 chips -->
      <div class="min-h-0 flex-1 space-y-1 overflow-y-auto p-2">
        <p v-if="outlineLoading" class="py-6 text-center text-[10px] text-ctp-overlay0">
          {{ t('app.loading') }}
        </p>
        <p v-else-if="!outlineTurns.length" class="py-6 text-center text-[10px] text-ctp-overlay0">
          {{ t('session.outline.empty') }}
        </p>
        <button
          v-for="(ot, i) in outlineTurns"
          :key="ot.id || i"
          class="block w-full rounded border border-ctp-surface1/60 bg-ctp-mantle/60 px-2 py-1 text-left transition-colors hover:border-ctp-blue/40 hover:bg-ctp-surface0/60"
          :title="ot.prompt"
          @click="gotoTurn(ot.id)"
        >
          <div class="flex items-center gap-1.5">
            <span class="shrink-0 font-mono text-[9px] text-ctp-sky">{{ String(i + 1).padStart(2, '0') }}</span>
            <span class="min-w-0 flex-1 truncate text-[10px] text-ctp-subtext1">{{ titleOf(ot) }}</span>
            <span class="shrink-0 font-mono text-[8px] text-ctp-overlay0">{{ fmtOutlineTs(ot.ts) }}</span>
          </div>
          <div v-if="ot.response" class="mt-0.5 truncate text-[9px] text-ctp-overlay0">{{ ot.response }}</div>
        </button>
        <div v-if="outlineCards.length" class="flex flex-wrap gap-1 pt-1">
          <button
            v-for="cd in outlineCards"
            :key="cd.id"
            class="chip bg-ctp-surface0/70 text-ctp-overlay1 !text-[8px] hover:text-ctp-subtext1"
            :title="cd.preview"
            @click="gotoTurn(cd.id)"
          >{{ cd.kind }}</button>
        </div>
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
