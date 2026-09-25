/** ReportHome · 面板注入键（MS6-W4）。 */
import { inject, provide } from 'vue'
import type { InjectionKey } from 'vue'
import type { ReportDeps } from './chatTypes'

export const WS_KEY: InjectionKey<ReportDeps> = Symbol('report-ws')

export function useReportWs(): ReportDeps {
  const ws = inject(WS_KEY)
  if (!ws) throw new Error('ReportHome 工作区未由宿主 provide')
  return ws
}
