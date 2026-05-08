/** PlantUML 渲染 Composable - 通过 Python 后端渲染 */

import { ref, watch, type Ref, onUnmounted } from 'vue'

export interface UsePlantUmlOptions {
  format?: 'svg' | 'png'
  useRemote?: boolean
}

export function usePlantUmlRender(
  diagram: Ref<string | null>,
  options: UsePlantUmlOptions = {}
) {
  const imageData = ref<string>('') // base64 data URL
  const loading = ref(false)
  const error = ref<string | null>(null)
  let cancelled = false

  watch(diagram, async (code) => {
    if (cancelled || !code) {
      imageData.value = ''
      error.value = null
      return
    }

    loading.value = true
    error.value = null

    try {
      // 通过 IPC 调用 Python 后端
      if (typeof window !== 'undefined' && window.api) {
        const result = await window.api.backend.renderPlantuml({
          code,
          format: options.format || 'svg',
          useRemote: options.useRemote !== false,
        })

        const mimeType = result.format === 'svg' ? 'image/svg+xml' : 'image/png'
        imageData.value = `data:${mimeType};base64,${result.data}`
      } else {
        // 浏览器环境: 使用远程 PlantUML 服务器
        const encoded = await encodePlantUml(code)
        const server = 'http://www.plantuml.com/plantuml'
        const format = options.format || 'svg'
        const url = `${server}/${format}/${encoded}`

        // 创建 data URL
        const response = await fetch(url)
        if (!response.ok) throw new Error(`PlantUML server error: ${response.status}`)

        const blob = await response.blob()
        const reader = new FileReader()
        imageData.value = await new Promise<string>((resolve) => {
          reader.onload = () => resolve(reader.result as string)
          reader.readAsDataURL(blob)
        })
      }
    } catch (e: any) {
      error.value = e.message || 'Render failed'
      console.error('[usePlantUmlRender]', e)
    } finally {
      loading.value = false
    }
  }, { immediate: true })

  function exportImage(filename: string = 'diagram.png'): void {
    if (!imageData.value) return
    const a = document.createElement('a')
    a.href = imageData.value
    a.download = filename
    a.click()
  }

  onUnmounted(() => {
    cancelled = true
  })

  return { imageData, loading, error, exportImage }
}

// PlantUML 编码 (deflate + modified base64)
async function encodePlantUml(code: string): Promise<string> {
  // 尝试使用 plantuml-encoder
  try {
    const mod = await import('plantuml-encoder')
    return mod.encode(code)
  } catch {
    // 手动编码
    const encoder = new TextEncoder()
    const data = encoder.encode(code)
    const compressed = new Uint8Array(pako?.deflate(data) || deflateManual(data))
    return base64Encode(compressed)
  }
}

function base64Encode(data: Uint8Array): string {
  let binary = ''
  data.forEach(b => binary += String.fromCharCode(b))
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function deflateManual(data: Uint8Array): Uint8Array {
  // 简化的 deflate，实际应使用 pako 或 zlib
  // 这里回退到远程编码
  return data
}
