/**
 * 节点样式映射 — symbol_node_type → 颜色/形状
 *
 * 默认映射 + 用户自定义覆盖
 */

import type { NodeStyle } from '@/lib/topo-animation/core/types'

// 默认节点样式映射
const DEFAULT_STYLE_MAP: Record<string, NodeStyle> = {
  function: {
    shape: 'rect',
    fillColor: '#4A90D9',
    strokeColor: '#2C5F8D',
    width: 100,
    height: 36,
    fontSize: 11,
    fontColor: '#FFFFFF',
  },
  class: {
    shape: 'hexagon',
    fillColor: '#50B86C',
    strokeColor: '#3A8C52',
    radius: 28,
    fontSize: 11,
    fontColor: '#FFFFFF',
  },
  method: {
    shape: 'rect',
    fillColor: '#7B68EE',
    strokeColor: '#5B4BC9',
    width: 90,
    height: 32,
    fontSize: 10,
    fontColor: '#FFFFFF',
  },
  macro: {
    shape: 'diamond',
    fillColor: '#E8A838',
    strokeColor: '#C48A20',
    radius: 22,
    fontSize: 10,
    fontColor: '#FFFFFF',
  },
  call_relation: {
    // 边样式，不是节点
    color: '#4A90D9',
    strokeWidth: 1.5,
    markerEnd: 'arrow',
  },
  dependence: {
    // 边样式
    color: '#50B86C',
    strokeWidth: 1.5,
    markerEnd: 'arrow',
  },
}

/**
 * 获取节点的默认样式
 */
export function getNodeStyle(symbolType: string): NodeStyle {
  return DEFAULT_STYLE_MAP[symbolType] || {
    shape: 'circle',
    fillColor: '#888888',
    strokeColor: '#666666',
    radius: 20,
    fontSize: 10,
    fontColor: '#FFFFFF',
  }
}

/**
 * 获取边的默认样式
 */
export function getEdgeStyle(edgeType: string): Record<string, any> {
  if (edgeType === 'CALL') {
    return {
      color: '#4A90D9',
      strokeWidth: 1.5,
      markerEnd: 'arrow',
    }
  } else if (edgeType === 'INCLUDE' || edgeType === 'DEPENDENCE') {
    return {
      color: '#50B86C',
      strokeWidth: 1.5,
      markerEnd: 'arrow',
    }
  }
  return {
    color: '#888888',
    strokeWidth: 1,
    markerEnd: 'arrow',
  }
}

/**
 * 获取社区节点的样式
 */
export function getCommunityStyle(depth: number = 0): NodeStyle {
  const colors = [
    { fill: '#FF6B6B', stroke: '#D94F4F' },
    { fill: '#4ECDC4', stroke: '#3AAFA8' },
    { fill: '#45B7D1', stroke: '#3597B0' },
    { fill: '#96CEB4', stroke: '#76AE94' },
  ]
  const color = colors[depth % colors.length]
  return {
    shape: 'ellipse',
    fillColor: color.fill,
    strokeColor: color.stroke,
    radius: 30 + depth * 5,
    fontSize: 10,
    fontColor: '#FFFFFF',
  }
}

/**
 * 应用用户自定义样式覆盖
 * @param baseStyle 基础样式
 * @param userStyleMap 用户自定义样式 { symbolType: { shape, fillColor, strokeColor } }
 * @param symbolType 符号类型
 */
export function applyUserStyle(
  baseStyle: NodeStyle,
  userStyleMap: Record<string, Partial<NodeStyle>> | null,
  symbolType: string
): NodeStyle {
  if (!userStyleMap || !userStyleMap[symbolType]) {
    return baseStyle
  }
  return {
    ...baseStyle,
    ...userStyleMap[symbolType],
  }
}
