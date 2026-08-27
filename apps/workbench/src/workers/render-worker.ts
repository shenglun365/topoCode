/** 渲染 Worker - D3 布局计算（mermaid 已收敛到 topoOne 内核主线程，见 useTopoRender）

注意: d3 使用动态导入以避免 Vite Worker IIFE 格式下 code-splitting 报错。
*/

import type {
  RenderRequest,
  RenderResponse,
  RenderProgress,
  RenderType,
  D3LayoutData,
  D3HierarchyData,
  D3LayoutResult,
} from './types'

// ==================== D3 力导向布局 ====================

// 动态导入 d3，避免 Vite Worker IIFE 格式下 code-splitting 报错
async function loadD3() {
  const d3 = await import('d3')
  return d3
}

async function computeD3Layout(data: D3LayoutData): Promise<D3LayoutResult> {
  const d3 = await loadD3()
  const {
    nodes,
    edges,
    width,
    height,
    iterations = 300,
    linkDistance = 120,
    chargeStrength = -300,
  } = data

  // 深拷贝避免修改原始数据
  const nodeData = nodes.map(n => ({ ...n })) as any[]
  const edgeData = edges.map(e => ({ ...e })) as any[]

  const simulation = d3
    .forceSimulation(nodeData)
    .force('link', d3.forceLink(edgeData).id((d: any) => d.id).distance(linkDistance))
    .force('charge', d3.forceManyBody().strength(chargeStrength))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius(30))
    .alphaDecay(0.02)

  // 发送进度
  const progressInterval = Math.max(1, Math.floor(iterations / 10))
  for (let i = 0; i < iterations; i++) {
    simulation.tick()
    if (i % progressInterval === 0) {
      postProgress('d3-layout', (i / iterations) * 100, `tick ${i}/${iterations}`)
    }
  }

  return {
    nodes: nodeData.map(n => ({
      id: n.id,
      x: n.x,
      y: n.y,
      label: n.label,
      group: n.group,
    })),
    edges: edgeData,
    alpha: simulation.alpha(),
  }
}

// ==================== D3 层次布局 ====================

async function computeD3Hierarchy(data: D3HierarchyData): Promise<any> {
  const d3 = await loadD3()
  const { root, width, height, nodeSize = [20, 60] } = data

  const hierarchy = d3.hierarchy(root)

  const treeLayout = d3
    .tree<any>()
    .size([height, width - nodeSize[0] * 2])
    .nodeSize(nodeSize)
    .separation((a, b) => (a.parent == b.parent ? 1 : 2))

  treeLayout(hierarchy)

  const nodes: any[] = hierarchy.descendants().map((d, i) => ({
    id: d.data.id || `node-${i}`,
    x: d.y,
    y: d.x,
    depth: d.depth,
    children: d.children?.map((_, j) => {
      // 找到子节点在结果中的索引
      const childIndex = hierarchy.descendants().indexOf(d.children![j])
      return childIndex
    }).filter((v): v is number => v !== undefined) || [],
    parents: d.parent ? [hierarchy.descendants().indexOf(d.parent)] : [],
    label: d.data.label || d.data.id || '',
  }))

  const links: any[] = hierarchy.links().map(link => ({
    source: nodes.find(n => n.x === link.source.y && n.y === link.source.x)?.id || '',
    target: nodes.find(n => n.x === link.target.y && n.y === link.target.x)?.id || '',
    depth: link.target.depth,
  }))

  return { nodes, links }
}

// ==================== Worker 消息分发 ====================

function postProgress(type: string, progress: number, phase: string): void {
  const msg = {
    id: '', // 由主线程填充
    type: type as RenderType,
    progress,
    phase,
  } as RenderProgress
  // @ts-ignore - self 在 Worker 环境中
  self.postMessage(msg)
}

// @ts-ignore - self 在 Worker 环境中
self.onmessage = async (e: MessageEvent<RenderRequest>) => {
  const { id, type, data, options } = e.data

  const response = { id, type } as RenderResponse

  try {
    switch (type) {
      case 'd3-layout': {
        const result = await computeD3Layout(data as D3LayoutData)
        response.result = result
        break
      }

      case 'd3-hierarchy': {
        const result = await computeD3Hierarchy(data as D3HierarchyData)
        response.result = result
        break
      }

      default:
        response.error = `Unknown render type: ${type}`
    }
  } catch (error: any) {
    response.error = error.message || String(error)
    console.error(`[Worker] Render error (${type}):`, error)
  }

  // @ts-ignore - self 在 Worker 环境中
  self.postMessage(response)
}

// 类型断言辅助
type RenderTypeKey = 'd3-layout' | 'd3-hierarchy'
