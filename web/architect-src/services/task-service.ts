import type { TaskNode } from '@/types'
import { apiGet } from './api-client'

export const taskService = {
  async tree(planId: string): Promise<TaskNode> {
    return apiGet<TaskNode>(`/plans/${planId}/task-tree`)
  },
  async flatten(root: TaskNode): Promise<TaskNode[]> {
    const out: TaskNode[] = []
    const walk = (n: TaskNode) => {
      out.push(n)
      ;(n.children ?? []).forEach(walk)
    }
    walk(root)
    return out
  },
}
