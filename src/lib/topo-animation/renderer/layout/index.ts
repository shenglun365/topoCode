/**
 * 布局算法模块
 * @module renderer/layout
 */

import { forceLayout } from './force';
import { hierarchyLayout } from './hierarchy';
import { gridLayout } from './grid';
import { circularLayout } from './circular';

export { forceLayout, hierarchyLayout, gridLayout, circularLayout };

/**
 * 根据布局类型执行布局
 */
import type { NodeState, EdgeState, LayoutType } from '../../core/types';

export function applyLayout(
  layout: LayoutType,
  nodes: Map<string, NodeState>,
  edges: Map<string, EdgeState>,
  width: number,
  height: number
): Map<string, NodeState> {
  switch (layout) {
    case 'force-directed':
      return forceLayout(nodes, edges, width, height);
    case 'hierarchy':
      return hierarchyLayout(nodes, edges, width, height);
    case 'grid':
      return gridLayout(nodes, width, height);
    case 'circular':
      return circularLayout(nodes, width, height);
    default:
      return forceLayout(nodes, edges, width, height);
  }
}
