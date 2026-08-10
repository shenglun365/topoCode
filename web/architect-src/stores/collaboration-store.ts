import { defineStore } from 'pinia'
import type { CollabMode, UserInteraction } from '@/types'
import { apiGet, apiPut, apiPost } from '@/services/api-client'
import { backendUp } from '@/services/backend'

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
    async setMode(mode: CollabMode) {
      this.mode = mode
      if (await backendUp()) apiPut<unknown>('/collab/mode', { mode }).catch(() => {})
    },
    async load() {
      if (this.loaded) return
      if (!(await backendUp())) throw new Error('后端不可达，无法加载协同交互')
      try {
        const [modeRes, interactions] = await Promise.all([
          apiGet<{ mode: CollabMode }>('/collab/mode'),
          apiGet<UserInteraction[]>('/collab/interactions'),
        ])
        this.mode = modeRes.mode ?? this.mode
        this.interactions = interactions ?? []
        this.loaded = true
      } catch (err) {
        throw err
      }
    },
    async resolve(id: string, answer: string) {
      const item = this.interactions.find((i) => i.id === id)
      if (item) {
        item.status = 'resolved'
        item.answer = answer
      }
      if (await backendUp()) apiPost<unknown>(`/collab/interactions/${id}/resolve`, { answer }).catch(() => {})
    },
    async enqueue(interaction: Omit<UserInteraction, 'id' | 'status' | 'createdAt'>) {
      this.interactions.unshift({
        ...interaction,
        id: `ui-${Date.now()}`,
        status: 'pending',
        createdAt: Date.now(),
      })
      if (await backendUp()) {
        apiPost<UserInteraction>('/collab/interactions', {
          kind: interaction.kind,
          taskId: interaction.taskId,
          prompt: interaction.prompt,
          status: 'pending',
        }).catch(() => {})
      }
    },
  },
})
