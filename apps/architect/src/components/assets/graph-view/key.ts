/**
 * 语义图谱 · 面板注入键（MS6-W2-S2）。SFC provide 工作区实例，面板 inject——
 * 每挂载一套状态，语义与单体组件一致。
 */
import { inject, provide } from 'vue'
import type { InjectionKey } from 'vue'
import type { useGraphData } from './useGraphData'
import type { useGraphDetail } from './useGraphDetail'
import type { useGraphCode } from './useGraphCode'
import type { useGraphRender } from './useGraphRender'

export type SgvWs = ReturnType<typeof useGraphData> &
  ReturnType<typeof useGraphDetail> &
  ReturnType<typeof useGraphCode> &
  ReturnType<typeof useGraphRender>

export const SGV_WS_KEY: InjectionKey<SgvWs> = Symbol('sgv-ws')

export function provideSgvWs(ws: SgvWs) {
  provide(SGV_WS_KEY, ws)
}

export function useSgvWs(): SgvWs {
  const ws = inject(SGV_WS_KEY)
  if (!ws) throw new Error('SemanticGraphView 工作区未由宿主 provide')
  return ws
}
