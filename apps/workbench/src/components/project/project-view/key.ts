/** ProjectCard · 面板注入键（MS6-W4）。 */
import { inject, provide } from 'vue'
import type { InjectionKey } from 'vue'
import type { CardDeps } from './chatTypes'

export const WS_KEY: InjectionKey<CardDeps> = Symbol('card-ws')

export function useCardWs(): CardDeps {
  const ws = inject(WS_KEY)
  if (!ws) throw new Error('ProjectCard 工作区未由宿主 provide')
  return ws
}
