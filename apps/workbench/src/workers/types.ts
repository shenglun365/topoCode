/** Worker 消息类型定义 */

// ==================== 渲染类型 ====================

export type RenderType = 'mermaid' | 'd3-layout' | 'd3-hierarchy'

// ==================== 请求消息 ====================

export interface RenderRequest {
  id: string
  type: RenderType
  data: RenderData
  options?: RenderOptions
}

export type RenderData = MermaidData | D3LayoutData | D3HierarchyData

export interface MermaidData {
  diagram: string
  theme?: 'dark' | 'light' | 'forest' | 'neutral'
}

export interface D3LayoutData {
  nodes: D3Node[]
  edges: D3Edge[]
  width: number
  height: number
  iterations?: number
  linkDistance?: number
  chargeStrength?: number
}

export interface D3Node {
  id: string
  label?: string
  group?: string
  [key: string]: any
}

export interface D3Edge {
  source: string
  target: string
  type?: string
  [key: string]: any
}

export interface D3HierarchyData {
  root: HierarchyNode
  width: number
  height: number
  nodeSize?: [number, number]
  separation?: (a: any, b: any, left: number, depth: number, right: number) => number
}

export interface HierarchyNode {
  id: string
  label?: string
  children?: HierarchyNode[]
  [key: string]: any
}

export interface RenderOptions {
  timeout?: number
  cache?: boolean
}

// ==================== 响应消息 ====================

export interface RenderResponse {
  id: string
  type: RenderType
  result?: RenderResult
  error?: string
}

export type RenderResult = MermaidResult | D3LayoutResult | D3HierarchyResult

export interface MermaidResult {
  svg: string
  theme?: string
}

export interface D3LayoutResult {
  nodes: D3NodePosition[]
  edges: D3Edge[]
  alpha: number
}

export interface D3NodePosition {
  id: string
  x: number
  y: number
  label?: string
  group?: string
  [key: string]: any
}

export interface D3HierarchyResult {
  nodes: D3HierarchyNode[]
  links: D3HierarchyLink[]
}

export interface D3HierarchyNode {
  id: string
  x: number
  y: number
  depth: number
  children?: number[]
  parents?: number[]
  label?: string
  [key: string]: any
}

export interface D3HierarchyLink {
  source: string
  target: string
  depth: number
}

// ==================== 进度消息 ====================

export interface RenderProgress {
  id: string
  type: RenderType
  progress: number // 0-100
  phase: string
}
