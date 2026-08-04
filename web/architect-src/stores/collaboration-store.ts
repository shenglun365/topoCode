import { defineStore } from 'pinia'
import type { CollabMode, UserInteraction } from '@/types'
import { USER_INTERACTIONS } from '@/services/mock/order-system'

export const useArchCollabStore = defineStore('arch-collab', {
  state: () => ({
    mode: 'main-agent' as CollabMode,
    interactions: [] as UserInteraction[],
    loaded: false,
  }),
  getters: {
    pending(state): UserInteraction[] {
      return state.interactions.filter((i) => i.status === 'pending')
    },
    pendingCount(): number {
      return this.pending.length
    },
  },
  actions: {
    setMode(mode: CollabMode) {
      this.mode = mode
    },
    load() {
      if (this.loaded) return
      this.interactions = [...USER_INTERACTIONS]
      this.loaded = true
    },
    resolve(id: string, answer: string) {
      const item = this.interactions.find((i) => i.id === id)
      if (item) {
        item.status = 'resolved'
        item.answer = answer
      }
    },
    enqueue(interaction: Omit<UserInteraction, 'id' | 'status' | 'createdAt'>) {
      this.interactions.unshift({
        ...interaction,
        id: `ui-${Date.now()}`,
        status: 'pending',
        createdAt: Date.now(),
      })
    },
  },
})
