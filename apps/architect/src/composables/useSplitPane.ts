import { onScopeDispose, ref } from 'vue'

/**
 * 左右分栏拖拽：返回左栏宽度百分比、拖拽态与 pointerdown 处理器。
 *
 * 拖拽期间把 pointermove/pointerup 挂到 window，而不是绑在细窄的分割线元素上——
 * 否则指针一移离分割线(或相邻面板在拖拽中重排、如 mermaid 主线程渲染即时撑开/收缩)
 * 就会因 pointerleave/捕获丢失而误判为结束，表现为「有时拖不动」。plantuml 走异步
 * 服务端、重排时机不同，故较少触发。window 监听可彻底规避该问题。
 *
 * 模板用法(仅需 @pointerdown)：
 *   const { splitPct, dragging, boxRef, onDown } = useSplitPane({ min: 38, max: 72 })
 *   <div ref="boxRef" class="flex">
 *     <div :style="{ width: splitPct + '%' }" />
 *     <div :class="dragging ? 'cursor-col-resize' : ''" @pointerdown="onDown" />
 *     <div class="flex-1 min-h-0" />
 *   </div>
 */
export function useSplitPane(opts: { initial?: number; min?: number; max?: number } = {}) {
  const { initial = 58, min = 38, max = 72 } = opts
  const splitPct = ref(initial)
  const dragging = ref(false)
  const boxRef = ref<HTMLElement | null>(null)
  let dragStartX = 0
  let dragStartSplit = 0

  function stop() {
    if (!dragging.value) return
    dragging.value = false
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', stop)
    window.removeEventListener('pointercancel', stop)
  }

  function onMove(e: PointerEvent) {
    if (!dragging.value) return
    const box = boxRef.value
    if (!box) return
    const w = box.getBoundingClientRect().width
    if (w <= 0) return
    const pct = dragStartSplit + ((e.clientX - dragStartX) / w) * 100
    splitPct.value = Math.min(max, Math.max(min, pct))
  }

  function onDown(e: PointerEvent) {
    e.preventDefault()
    dragging.value = true
    dragStartX = e.clientX
    dragStartSplit = splitPct.value
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
  }

  onScopeDispose(stop)

  return { splitPct, dragging, boxRef, onDown, onMove, onUp: stop }
}
