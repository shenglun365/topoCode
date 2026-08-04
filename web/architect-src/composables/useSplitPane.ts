import { ref } from 'vue'

/**
 * 左右分栏拖拽：返回左栏宽度百分比、拖拽态与指针事件处理器。
 *
 * 模板用法：
 *   const { splitPct, dragging, boxRef, onDown, onMove, onUp } = useSplitPane({ min: 38, max: 72 })
 *   <div ref="boxRef" class="flex">
 *     <div :style="{ width: splitPct + '%' }" />
 *     <div :class="dragging ? 'cursor-col-resize' : ''" @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @pointercancel="onUp" @pointerleave="onUp" />
 *     <div :style="{ width: splitPct + '%' }" />
 *   </div>
 */
export function useSplitPane(opts: { initial?: number; min?: number; max?: number } = {}) {
  const { initial = 58, min = 38, max = 72 } = opts
  const splitPct = ref(initial)
  const dragging = ref(false)
  const boxRef = ref<HTMLElement | null>(null)
  let dragStartX = 0
  let dragStartSplit = 0

  function onDown(e: PointerEvent) {
    dragging.value = true
    dragStartX = e.clientX
    dragStartSplit = splitPct.value
    ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
  }

  function onMove(e: PointerEvent) {
    if (!dragging.value) return
    const box = boxRef.value
    if (!box) return
    const pct = dragStartSplit + ((e.clientX - dragStartX) / box.getBoundingClientRect().width) * 100
    splitPct.value = Math.min(max, Math.max(min, pct))
  }

  function onUp() {
    dragging.value = false
  }

  return { splitPct, dragging, boxRef, onDown, onMove, onUp }
}
