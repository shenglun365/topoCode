export interface GraphNode {
  id: string
  label: string
  nodeCount?: number
  qualityScore?: number | null
  status?: string
  hasChildren?: boolean
  isExternal?: boolean
  isMerged?: boolean
  remainingCount?: number
}

export interface GraphEdge {
  source: string
  target: string
  count?: number
}

export function getNodeRadius(n: GraphNode): number {
  return Math.round(Math.max(18, Math.min(40, (n.nodeCount || 5) * 1.5 + 12)))
}

export function nodeColor(n: GraphNode): string {
  if (n.isExternal) return '#e8792e'
  if (n.status === 'completed') return '#7c3aed'
  if (n.status === 'running' || n.status === 'queued') return '#3b82f6'
  if (n.status === 'error') return '#ef4444'
  return '#4b5563'
}
