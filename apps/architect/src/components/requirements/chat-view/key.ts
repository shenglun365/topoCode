/**
 * AnalysisChat · 面板注入键（MS6-W3）。
 */
import { inject, provide } from 'vue'
import type { InjectionKey } from 'vue'
import type { ChatDeps } from './chatTypes'

export const WS_KEY: InjectionKey<ChatDeps> = Symbol('chat-ws')

export function provideChatWs(ws: ChatDeps) {
  provide(WS_KEY, ws)
}

export function useChatWs(): ChatDeps {
  const ws = inject(WS_KEY)
  if (!ws) throw new Error('AnalysisChat 工作区未由宿主 provide')
  return ws
}
