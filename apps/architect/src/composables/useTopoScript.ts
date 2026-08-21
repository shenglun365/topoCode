export interface TsNode {
  id: string
  label: string
  kind: string
}
export interface TsLink {
  from: string
  to: string
  label: string
}
export interface TsGraph {
  nodes: TsNode[]
  links: TsLink[]
}

/**
 * toposcript —— 自建动画 DSL(原型: 定义规范 + 占位解析)。
 *
 * 目标形态: 声明式描述「组件节点 + 数据流边」，由自研动画引擎
 * 渲染为带数据包流动/节点脉冲/事件时序的时序动画(类似 mermaid sequence + dataflow)。
 * 引擎尚未建成，当前版本提供:
 *   1. DSL 解析器(parseTopoScript)
 *   2. SVG 占位渲染器(TopoScriptCanvas.vue, 演示流动粒子)
 */
export function parseTopoScript(code: string): TsGraph {
  const nodes: TsNode[] = []
  const links: TsLink[] = []
  const nodeMap = new Map<string, TsNode>()

  for (const raw of code.split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('graph') || line.startsWith('```') || line.startsWith('#')) continue

    const nodeMatch = line.match(/^(\w[\w-]*)\s*\[([^\]]+)\](?:\s*::\s*(\w+))?$/)
    if (nodeMatch) {
      const node: TsNode = { id: nodeMatch[1], label: nodeMatch[2], kind: nodeMatch[3] ?? 'service' }
      nodes.push(node)
      nodeMap.set(node.id, node)
      continue
    }

    const linkMatch = line.match(/^(\w[\w-]*)\s*->\s*(\w[\w-]*)\s*:\s*(.+)$/)
    if (linkMatch) {
      if (nodeMap.has(linkMatch[1]) && nodeMap.has(linkMatch[2])) {
        links.push({ from: linkMatch[1], to: linkMatch[2], label: linkMatch[3].trim() })
      }
      continue
    }

    const edgeMatch = line.match(/^(\w[\w-]*)\s*->\s*(\w[\w-]*)$/)
    if (edgeMatch) {
      if (nodeMap.has(edgeMatch[1]) && nodeMap.has(edgeMatch[2])) {
        links.push({ from: edgeMatch[1], to: edgeMatch[2], label: '' })
      }
    }
  }

  return { nodes, links }
}

export function topoScriptSample(): string {
  return `graph
gw [API网关] :: gateway
order [订单服务] :: service
inv [库存服务] :: service
pay [支付服务] :: service
mq [RabbitMQ] :: infra
gw -> order : 下单请求(幂等键)
order -> inv : 预扣库存
order -> pay : 创建支付单
order -> mq : OrderCreated(事件)`
}
