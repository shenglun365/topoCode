/** Mermaid 渲染 Composable */

import { ref, watch, type Ref, onUnmounted } from 'vue'
import { renderManager } from '@/services/render-manager'
import type { MermaidData, MermaidResult } from '@/workers/types'

export interface UseMermaidOptions {
  theme?: 'dark' | 'light' | 'forest' | 'neutral'
  cache?: boolean
}

export function useMermaidRender(
  diagram: Ref<string | null>,
  options: UseMermaidOptions = {}
) {
  const svg = ref<string>('')
  const loading = ref(false)
  const error = ref<string | null>(null)
  const progress = ref(0)
  let cancelled = false

  watch(diagram, async (newCode) => {
    if (cancelled || !newCode) {
      svg.value = ''
      error.value = null
      return
    }

    loading.value = true
    error.value = null
    progress.value = 0

    try {
      const data: MermaidData = {
        diagram: newCode,
        theme: options.theme,
      }

      const result = await renderManager.render('mermaid', data, {
        cache: options.cache !== false,
        onProgress: (p) => { progress.value = p },
      }) as MermaidResult

      svg.value = result.svg
      progress.value = 100
    } catch (e: any) {
      error.value = e.message || 'Render failed'
      console.error('[useMermaidRender]', e)
    } finally {
      loading.value = false
    }
  }, { immediate: true })

  // 手动触发重新渲染
  async function refresh() {
    if (!diagram.value) return
    renderManager.clearCache('mermaid')
    // 触发 watch
    const code = diagram.value
    diagram.value = ''
    await nextTick()
    diagram.value = code
  }

  // 导出 SVG
  function exportSvg(filename: string = 'diagram.svg'): void {
    if (!svg.value) return
    const blob = new Blob([svg.value], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
  }

  // 导出 PNG
  async function exportPng(filename: string = 'diagram.png', scale: number = 2): Promise<void> {
    if (!svg.value) return

    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const img = new Image()
    const blob = new Blob([svg.value], { type: 'image/svg+xml' })
    const url = URL.createObjectURL(blob)

    await new Promise<void>((resolve) => {
      img.onload = () => {
        const rect = img.getBoundingClientRect()
        const w = rect.width || 800
        const h = rect.height || 600
        canvas.width = w * scale
        canvas.height = h * scale
        ctx.scale(scale, scale)
        ctx.drawImage(img, 0, 0, w, h)
        URL.revokeObjectURL(url)
        resolve()
      }
      img.src = url
    })

    canvas.toBlob((blob) => {
      if (!blob) return
      const pngUrl = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = pngUrl
      a.download = filename
      a.click()
      URL.revokeObjectURL(pngUrl)
    })
  }

  onUnmounted(() => {
    cancelled = true
  })

  return { svg, loading, error, progress, refresh, exportSvg, exportPng }
}

import { nextTick } from 'vue'
