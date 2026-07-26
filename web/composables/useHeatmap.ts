import { ref } from 'vue'
import * as api from '@web/services/api'

export function useHeatmap() {
  console.log('[useHeatmap] init')

  const heatmapData = ref<any>(null)
  const heatmapSize = ref(10)
  const heatmapLoading = ref(false)

  async function loadHeatmap(taskId: string, graphEdgeType: string, graphCommId?: string) {
    heatmapLoading.value = true
    try {
      const isExternal = graphEdgeType === 'EXTERNAL_INCLUDE' || graphEdgeType === 'EXTERNAL_CALL'
      if (isExternal) {
        const data = await api.getExternalStats(taskId)
        heatmapData.value = data ? { matrix: data.stats || [], rows: data.labels || [], cols: data.communities || [], maxCount: data.maxCount || 0 } : null
      } else {
        const data = await api.getHeatmap(taskId, graphEdgeType, heatmapSize.value, graphCommId || undefined)
        heatmapData.value = data ? sortHeatmap(data) : null
      }
    } catch (_) { heatmapData.value = null } finally { heatmapLoading.value = false }
  }

  function sortHeatmap(data: any): any {
    if (!data || !data.matrix || !data.matrix.length) return data
    const n = data.matrix.length
    const rowSums = data.matrix.map((row: number[]) => row.reduce((a: number, b: number) => a + b, 0))
    const colSums = data.matrix[0] ? data.matrix[0].map((_: number, ci: number) => data.matrix.reduce((a: number, r: number[]) => a + r[ci], 0)) : []
    const rowIdx = Array.from({ length: n }, (_, i) => i).sort((a, b) => rowSums[b] - rowSums[a])
    const colIdx = colSums.length ? Array.from({ length: colSums.length }, (_, i) => i).sort((a, b) => colSums[b] - colSums[a]) : []
    return {
      rows: rowIdx.map((i: number) => data.rows[i]),
      cols: colIdx.length ? colIdx.map((i: number) => data.cols[i]) : data.cols,
      matrix: rowIdx.map((i: number) => colIdx.length ? colIdx.map((j: number) => data.matrix[i][j]) : data.matrix[i]),
      maxCount: data.maxCount,
      commIds: data.commIds ? rowIdx.map((i: number) => data.commIds[i]) : undefined,
    }
  }

  function heatmapBg(val: number, max: number): string {
    if (val === 0 || !max) return 'transparent'
    const i = Math.min(val / max, 1)
    return `rgb(255,${Math.round(245 - 200 * i)},${Math.round(245 - 200 * i)})`
  }

  function setHeatmapSize(val: number) {
    heatmapSize.value = val
  }

  return {
    heatmapData, heatmapSize, heatmapLoading,
    loadHeatmap, sortHeatmap, heatmapBg, setHeatmapSize,
  }
}
