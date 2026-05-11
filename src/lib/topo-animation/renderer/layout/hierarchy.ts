/**
 * 树形布局 (复用 D3)
 * @module renderer/layout/hierarchy
 */

import * as d3 from 'd3';
import type { NodeState, EdgeState } from '../../core/types';
import { gridLayout } from './grid';

/**
 * 树形布局
 * @param nodes 节点集合
 * @param edges 边集合
 * @param width 画布宽度
 * @param height 画布高度
 * @returns 布局后的节点位置
 */
export function hierarchyLayout(
  nodes: Map<string, NodeState>,
  edges: Map<string, EdgeState>,
  width: number = 800,
  height: number = 600
): Map<string, NodeState> {
  // 构建树结构
  const rootId = findRoot(nodes, edges);
  if (!rootId) {
    // 无根节点，退化为网格布局
    return gridLayout(nodes, width, height);
  }

  const nodeArray = Array.from(nodes.values());
  const edgeArray = Array.from(edges.values());

  // 构建邻接表
  const childrenMap = new Map<string, string[]>();
  const parentMap = new Map<string, string>();

  for (const edge of edgeArray) {
    if (!childrenMap.has(edge.source)) {
      childrenMap.set(edge.source, []);
    }
    childrenMap.get(edge.source)!.push(edge.target);
    parentMap.set(edge.target, edge.source);
  }

  // 构建树数据
  const treeData = buildTree(rootId, childrenMap, nodeArray);

  // D3 树布局
  const root = d3.hierarchy(treeData);
  const tree = d3.tree().size([width - 100, height - 100]);
  tree(root);

  // 更新位置
  const result = new Map<string, NodeState>();
  const positionMap = new Map<string, [number, number]>();

  function assignPositions(node: any, depth: number = 0): void {
    positionMap.set(node.data.id, [node.x + 50, node.y + 50 + depth * 20]);

    for (const child of node.children || []) {
      assignPositions(child, depth + 1);
    }
  }

  assignPositions(root);

  for (const node of nodeArray) {
    const pos = positionMap.get(node.id);
    if (pos) {
      result.set(node.id, { ...node, position: pos });
    } else {
      result.set(node.id, node);
    }
  }

  return result;
}

function findRoot(nodes: Map<string, NodeState>, edges: Map<string, EdgeState>): string | null {
  const hasParent = new Set<string>();
  for (const [, edge] of edges) {
    hasParent.add(edge.target);
  }

  for (const [id] of nodes) {
    if (!hasParent.has(id)) {
      return id;
    }
  }
  return nodes.size > 0 ? Array.from(nodes.keys())[0] : null;
}

function buildTree(id: string, childrenMap: Map<string, string[]>, nodes: NodeState[]): any {
  const node = nodes.find((n) => n.id === id);
  const children = childrenMap.get(id) || [];

  return {
    id,
    label: node?.label || id,
    children: children.map((childId) => buildTree(childId, childrenMap, nodes)),
  };
}

// 导出供 hierarchy 使用
export { gridLayout } from './grid';
