/**
 * ChatSession · 面板注入键（MS7-W2）。
 */
import { inject, provide } from 'vue'
import type { InjectionKey } from 'vue'
import type { ChatDeps } from './chatTypes'

export const WS_KEY: InjectionKey<ChatDeps> = Symbol('chat-session-ws')

export function useChatSessionWs(): ChatDeps {
  const ws = inject(WS_KEY)
  if (!ws) throw new Error('ChatSession 工作区未由宿主 provide')
  return ws
}
