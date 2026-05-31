/** D3 力导向图 Composable - Worker 计算布局 + 主线程渲染 */

import { ref, watch, type Ref, onUnmounted, nextTick } from 'vue'
import { renderManager } from '@/services/render-manager'
import type { D3LayoutData, D3LayoutResult, D3Node, D3Edge } from '@/workers/types'

export interface UseD3GraphOptions {
  width?: number
  height?: number
  iterations?: number
  linkDistance?: number
  chargeStrength?: number
}

export function useD3Graph(
  graphData: Ref<{ nodes: D3Node[]; edges: D3Edge[] } | null>,
  options: UseD3GraphOptions = {}
) {
  const nodes = ref<D3LayoutResult['nodes']>([])
  const edges = ref<D3LayoutResult['edges']>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const progress = ref(0)
  const alpha = ref(0)
  let cancelled = false

  watch(graphData, async (data) => {
    if (cancelled || !data) {
      nodes.value = []
      edges.value = []
      return
    }

    loading.value = true
    error.value = null
    progress.value = 0

    try {
      const layoutData: D3LayoutData = {
        nodes: data.nodes,
        edges: data.edges,
        width: options.width || 800,
        height: options.height || 500,
        iterations: options.iterations || 300,
        linkDistance: options.linkDistance || 120,
        chargeStrength: options.chargeStrength || -300,
      }

      const result = await renderManager.render('d3-layout', layoutData, {
        cache: false,
        onProgress: (p, phase) => {
          progress.value = p
        },
      }) as D3LayoutResult

      nodes.value = result.nodes
      edges.value = result.edges
      alpha.value = result.alpha
      progress.value = 100
    } catch (e: any) {
      error.value = e.message || 'Layout failed'
      console.error('[useD3Graph]', e)
    } finally {
      loading.value = false
    }
  }, { immediate: true })

  // 重新计算布局
  async function relayout() {
    if (!graphData.value) return
    const data = graphData.value
    graphData.value = null
    await nextTick()
    graphData.value = data
  }

  onUnmounted(() => {
    cancelled = true
  })

  return { nodes, edges, loading, error, progress, alpha, relayout }
}
