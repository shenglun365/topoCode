/**
 * 力导向布局 (复用 D3)
 * @module renderer/layout/force
 */

import * as d3 from 'd3';
import type { NodeState, EdgeState } from '../../core/types';

export interface LayoutResult {
  nodes: Map<string, NodeState>;
  edges: Map<string, EdgeState>;
}

/**
 * 力导向布局
 * @param nodes 节点集合
 * @param edges 边集合
 * @param width 画布宽度
 * @param height 画布高度
 * @param iterations 迭代次数
 * @returns 布局后的节点位置
 */
export function forceLayout(
  nodes: Map<string, NodeState>,
  edges: Map<string, EdgeState>,
  width: number = 800,
  height: number = 600,
  iterations: number = 300
): Map<string, NodeState> {
  const nodeArray = Array.from(nodes.values()).map((n) => ({
    id: n.id,
    x: n.position[0],
    y: n.position[1],
  }));

  const edgeArray = Array.from(edges.values()).map((e) => ({
    source: e.source,
    target: e.target,
  }));

  const simulation = d3
    .forceSimulation(nodeArray)
    .force('link', d3.forceLink(edgeArray).id((d: any) => d.id).distance(100))
    .force('charge', d3.forceManyBody().strength(-30))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius(20))
    .stop();

  // 运行迭代
  for (let i = 0; i < iterations; i++) {
    simulation.tick();
  }

  // 更新节点位置
  const result = new Map<string, NodeState>();
  for (const node of nodeArray) {
    const original = nodes.get(node.id);
    if (original) {
      result.set(node.id, {
        ...original,
        position: [node.x, node.y],
      });
    }
  }

  return result;
}
