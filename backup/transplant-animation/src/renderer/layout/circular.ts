/**
 * 环形布局 (自实现)
 * @module renderer/layout/circular
 */

import type { NodeState } from '../../core/types';

/**
 * 环形布局
 * @param nodes 节点集合
 * @param width 画布宽度
 * @param height 画布高度
 * @param radius 半径
 * @returns 布局后的节点位置
 */
export function circularLayout(
  nodes: Map<string, NodeState>,
  width: number = 800,
  height: number = 600,
  radius?: number
): Map<string, NodeState> {
  const nodeArray = Array.from(nodes.values());
  const result = new Map<string, NodeState>();

  const cx = width / 2;
  const cy = height / 2;
  const r = radius || Math.min(width, height) / 2 - 60;

  nodeArray.forEach((node, index) => {
    const angle = (2 * Math.PI * index) / nodeArray.length - Math.PI / 2;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);

    result.set(node.id, {
      ...node,
      position: [x, y],
    });
  });

  return result;
}
