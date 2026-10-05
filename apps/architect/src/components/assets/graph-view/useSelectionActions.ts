/**
 * 卡片内容选区动作(引用/复制)可组合：mouseup 检测容器内文本选区 →
 * 浮动工具条(定位选区下方) → 复制到剪贴板 / 组装引用 payload 发草稿总线。
 * 代码资产卡与逻辑资产卡共用；行列范围由行元素 [data-line] 推导(代码卡)。
 */
import { nextTick, onBeforeUnmount, onMounted, ref, type Ref } from 'vue'
import { copyText } from '@/utils/clipboard'
import { requestDraftRef, type DraftRefSource } from '@/pages/asset-workspace/draft-ref-bus'

export function useSelectionActions(
  container: Ref<HTMLElement | null>,
  buildSource: () => DraftRefSource,
  opts?: { lang?: () => string | undefined },
) {
  const barVisible = ref(false)
  const barPos = ref({ x: 0, y: 0 })
  const copied = ref(false)
  let copiedTimer: ReturnType<typeof setTimeout> | null = null
  let selText = ''

  /** 选区起止行(向上找最近 [data-line]; 无行元素 → null)。 */
  function selLines(): { start?: number; end?: number } {
    const sel = window.getSelection()
    if (!sel || sel.rangeCount === 0) return {}
    const r = sel.getRangeAt(0)
    const lineOf = (node: Node | null): number | undefined => {
      let el: HTMLElement | null = node instanceof HTMLElement ? node : node?.parentElement ?? null
      while (el && el !== container.value) {
        const dl = (el as HTMLElement).dataset?.line ?? el.getAttribute?.('data-line')
        if (dl) return Number(dl)
        el = el.parentElement
      }
      return undefined
    }
    let start = lineOf(r.startContainer)
    let end = lineOf(r.endContainer)
    if (start !== undefined && end !== undefined && end < start) [start, end] = [end, start]
    return { start, end }
  }

  function onUp(): void {
    void nextTick(() => {
      const sel = window.getSelection()
      const text = (sel?.toString() ?? '').trim()
      const host = container.value
      if (!sel || sel.isCollapsed || !text || !host || sel.rangeCount === 0) {
        barVisible.value = false
        return
      }
      // 选区起点须在容器内
      const anchorEl = sel.getRangeAt(0).startContainer instanceof HTMLElement
        ? (sel.getRangeAt(0).startContainer as HTMLElement)
        : sel.getRangeAt(0).startContainer.parentElement
      if (!anchorEl || !host.contains(anchorEl)) { barVisible.value = false; return }
      selText = sel.toString()
      const rect = sel.getRangeAt(0).getBoundingClientRect()
      const hostRect = host.getBoundingClientRect()
      barPos.value = {
        x: Math.max(4, rect.left - hostRect.left),
        y: rect.bottom - hostRect.top + 4,
      }
      copied.value = false
      barVisible.value = true
    })
  }

  function onDown(e: MouseEvent): void {
    // 容器内按下即隐藏(选区变化后 mouseup 重新评估); 工具条自身点击除外
    if ((e.target as HTMLElement).closest('[data-sel-actions]')) return
    barVisible.value = false
  }

  async function copySel(): Promise<void> {
    if (!selText) return
    if (await copyText(selText)) {
      copied.value = true
      if (copiedTimer) clearTimeout(copiedTimer)
      copiedTimer = setTimeout(() => { copied.value = false; barVisible.value = false }, 1200)
    }
  }

  function refSel(): void {
    if (!selText) return
    const lines = selLines()
    requestDraftRef({
      text: selText,
      lang: opts?.lang?.(),
      source: { ...buildSource(), lineStart: lines.start, lineEnd: lines.end },
    })
    barVisible.value = false
    window.getSelection()?.removeAllRanges()
  }

  onMounted(() => {
    document.addEventListener('mouseup', onUp)
    document.addEventListener('mousedown', onDown)
  })
  onBeforeUnmount(() => {
    document.removeEventListener('mouseup', onUp)
    document.removeEventListener('mousedown', onDown)
    if (copiedTimer) clearTimeout(copiedTimer)
  })

  return { barVisible, barPos, copied, copySel, refSel }
}

/** 文件路径 → fence 语言标记。 */
export function langOf(file: string): string | undefined {
  const ext = (file.split('.').pop() ?? '').toLowerCase()
  const MAP: Record<string, string> = {
    ts: 'ts', tsx: 'tsx', js: 'js', jsx: 'jsx', vue: 'vue', py: 'python',
    c: 'c', h: 'c', cpp: 'cpp', hpp: 'cpp', go: 'go', rs: 'rust', java: 'java',
    md: 'md', json: 'json', yaml: 'yaml', yml: 'yaml', sh: 'bash', sql: 'sql',
  }
  return MAP[ext]
}
