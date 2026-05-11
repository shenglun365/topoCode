/**
 * 网格布局 (自实现)
 * @module renderer/layout/grid
 */

import type { NodeState } from '../../core/types';

/**
 * 网格布局
 * @param nodes 节点集合
 * @param width 画布宽度
 * @param height 画布高度
 * @param cellSize 单元格大小
 * @returns 布局后的节点位置
 */
export function gridLayout(
  nodes: Map<string, NodeState>,
  width: number = 800,
  height: number = 600,
  cellSize: number = 120
): Map<string, NodeState> {
  const nodeArray = Array.from(nodes.values());
  const result = new Map<string, NodeState>();

  // 计算行列
  const cols = Math.ceil(Math.sqrt(nodeArray.length * (width / height)));
  const rows = Math.ceil(nodeArray.length / cols);

  // 计算起始偏移
  const startX = (width - cols * cellSize) / 2 + cellSize / 2;
  const startY = (height - rows * cellSize) / 2 + cellSize / 2;

  nodeArray.forEach((node, index) => {
    const col = index % cols;
    const row = Math.floor(index / cols);
    const x = startX + col * cellSize;
    const y = startY + row * cellSize;

    result.set(node.id, {
      ...node,
      position: [x, y],
    });
  });

  return result;
}
