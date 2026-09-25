/**
 * useChat · input 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { apiGet, apiPut } from '@/services/api-client'

import type { ChatDeps } from './chatTypes'

export function useChatInput(D: ChatDeps) {
  const props = D.props
  const emit = D.emit

const { t } = useI18n()
const input = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)

// ---- 工具轨迹浮层（防信息过载：默认收起，点击展开；回合结束/busy 清空自动关闭）----
const trailOpen = ref(false)
watch(() => props.busy, (b) => { if (!b) trailOpen.value = false })

// ---- 外部引用预填：nonce 变化 → 追加进输入框并聚焦(用户可补充问题后再发送) ----
watch(() => props.insertDraft?.nonce ?? 0, (n) => {
  if (!n) return
  const text = props.insertDraft?.text ?? ''
  if (!text) return
  input.value = input.value ? `${input.value} ${text}` : text
  void nextTick(() => {
    inputRef.value?.focus()
    manualHeight = false
    autoResize()
    const el = inputRef.value
    if (el) el.selectionStart = el.selectionEnd = el.value.length
  })
})
const scrollRef = ref<HTMLElement | null>(null)
const answers = reactive<Record<string, string>>({})
// cv-247 问询卡已答态(本地): 卡内回复或输入区自由回复后均置已答(防重复)
const choicesAnswered = reactive(new Set<string>())
// 已答态零写点派生(cv-254): 协议保证问询卡与答复交替(cv-247——卡内回复
// 与输入区自由回复同答语义)——卡之后的首条 user 消息即其答复, 刷新后
// 由会话流时间序派生, 不回退不丢真
const answeredByFlow = computed(() => {
  const set = new Set<string>()
  let pending = ''
  for (const m of (props.turns || []) as any[]) {
    if (m.item?.type === 'choices') pending = String(m.id || '')
    else if (m.role === 'user' && pending) { set.add(pending); pending = '' }
  }
  return set
})
// 问询卡填写草稿(cv-254): 用户输入=工作产物, 随会话落库——刷新/断线/
// 前端重启后原样恢复(specDraft 同类 conv.meta 草稿, 非事实写点)
const choiceDrafts = ref<Record<string, any>>({})
const draftTimers = new Map<string, ReturnType<typeof setTimeout>>()
async function loadChoiceDrafts() {
  if (!props.convId) return
  try {
    const r: any = await apiGet(`/sessions/${props.convId}/choices-draft`)
    choiceDrafts.value = (r as any)?.drafts || (r as any)?.data?.drafts || {}
  } catch { /* fail-soft: 草稿不可得=空白填写 */ }
}
function scheduleDraftSave(cardId: string, draft: any) {
  if (!props.convId || answeredByFlow.value.has(cardId)
      || choicesAnswered.has(cardId)) return
  clearTimeout(draftTimers.get(cardId))
  draftTimers.set(cardId, setTimeout(() => {
    void apiPut(`/sessions/${props.convId}/choices-draft`,
                { cardId, draft }).catch(() => {})
  }, 800))
}
function clearChoiceDraft(cardId: string) {
  clearTimeout(draftTimers.get(cardId))
  draftTimers.delete(cardId)
  if (!props.convId) return
  void apiPut(`/sessions/${props.convId}/choices-draft`,
              { cardId, draft: null }).catch(() => {})
}
watch(() => props.turns.length, () => {
  if ((props.turns || []).some((m: any) => m.item?.type === 'choices')
      && !Object.keys(choiceDrafts.value).length) void loadChoiceDrafts()
}, { immediate: true })
const choicesCards = computed(() =>
  (props.turns || []).filter((m: any) => m.item?.type === 'choices'))

watch(
  () => props.turns.length,
  async () => {
    await nextTick()
    scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' })
  },
)
watch(
  () => props.turns,
  (turns) => {
    const q = turns[turns.length - 1]?.questions
    if (q) q.forEach((item) => { if (!(item.key in answers)) answers[item.key] = item.answer ?? '' })
  },
  { deep: true },
)

// ── v2 语境路由(发起者感知): 回复永远面向「当前持球方」——单输入框, 零模式切换 ──
// 规则: ① 存在 waiting_input 任务 → 转达该任务(attachTo)
//       ② 存在活跃任务 且 最后 assistant 消息为 coding subagent 产出 → 转达(排队)
//       ③ 其余 → architect 外循环
// 覆盖: 内联 @执行器 前缀(一次性指派, 发送时剥离) > 菜单单次翻转(发送后复位)
const MIN_ROWS = 2
const MAX_ROWS = 6
/** 读取行高与上下 padding(用于行数↔像素换算)。 */
function inputMetrics(el: HTMLTextAreaElement) {
  const cs = getComputedStyle(el)
  return {
    lineH: parseFloat(cs.lineHeight) || 16,
    pad: (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0),
  }
}
/** 用户拖拽把手进入手动高度模式(暂停自动伸缩)，发送后恢复。 */
let manualHeight = false
/** autoResize 施加高度时抑制 RO 回调(避免把自己的改动误判为手动拖拽)。 */
let roSuppress = false
let lastAppliedHeight = ''
/** 自适应高度：随内容行数伸缩，默认/最矮 2 行、最高 6 行，超出滚动；手动拖拽后交由用户控制(仍限 2~6 行)。 */
function autoResize() {
  const el = inputRef.value
  if (!el) return
  if (manualHeight) {
    // 手动模式：不改动用户拖出的高度，只维护滚动条
    el.style.overflowY = el.scrollHeight > el.clientHeight + 1 ? 'auto' : 'hidden'
    return
  }
  roSuppress = true
  const { lineH, pad } = inputMetrics(el)
  const min = lineH * MIN_ROWS + pad
  const max = lineH * MAX_ROWS + pad
  el.style.height = 'auto'
  const h = Math.min(Math.max(el.scrollHeight, min), max)
  el.style.height = `${h}px`
  lastAppliedHeight = `${h}px`
  el.style.overflowY = el.scrollHeight > max + 1 ? 'auto' : 'hidden'
}
/** 手动拖拽检测：高度变化非 autoResize 所施加 → 进入手动模式(越界钳制回 2~6 行)。 */
const inputResizeObserver = new ResizeObserver(() => {
  const el = inputRef.value
  if (!el) return
  if (roSuppress) { roSuppress = false; return }
  if (el.style.height === lastAppliedHeight) return
  manualHeight = true
  const { lineH, pad } = inputMetrics(el)
  const min = lineH * MIN_ROWS + pad
  const max = lineH * MAX_ROWS + pad
  const h = parseFloat(el.style.height) || 0
  if (h && (h < min || h > max)) {
    roSuppress = true
    lastAppliedHeight = `${Math.min(Math.max(h, min), max)}px`
    el.style.height = lastAppliedHeight
  }
  el.style.overflowY = el.scrollHeight > el.clientHeight + 1 ? 'auto' : 'hidden'
})
onMounted(() => {
  if (inputRef.value) {
    inputResizeObserver.observe(inputRef.value)
    autoResize()
  }
})
onUnmounted(() => inputResizeObserver.disconnect())
/** 发送后清空并回到默认两行高度(同时退出手动模式)。 */
function resetInputHeight() {
  manualHeight = false
  autoResize()
}
/** Enter 换行(不拦截, textarea 原生插入且不干扰 IME)；Ctrl/Cmd+Enter 发送。 */
function onInputKeydown(e: KeyboardEvent) {
  D.send.onCmdMenuKeydown(e)
  if (e.key !== 'Enter') return
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault()
    D.send.send()
  }
}

function submitAnswers() {
  emit('answers', { ...answers })
  Object.keys(answers).forEach((k) => delete answers[k])
}

/** 单条消息删除：DOM 弹窗确认后移除本地 turn(持久化删除由 workspace 处理)。 */

  return {
    MAX_ROWS,
    MIN_ROWS,
    answeredByFlow,
    answers,
    autoResize,
    choiceDrafts,
    choicesAnswered,
    choicesCards,
    clearChoiceDraft,
    draftTimers,
    input,
    inputMetrics,
    inputRef,
    inputResizeObserver,
    lastAppliedHeight,
    loadChoiceDrafts,
    manualHeight,
    onInputKeydown,
    resetInputHeight,
    roSuppress,
    scheduleDraftSave,
    scrollRef,
    submitAnswers,
    trailOpen,
  }
}
