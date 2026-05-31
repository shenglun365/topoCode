/**
 * 状态机 - 将 StateDelta[] 转换为 AnimationState[]
 * @module core/StateMachine
 *
 * @description
 * StateMachine 维护动画的完整状态，通过应用增量（StateDelta）
 * 生成每一帧的完整状态（AnimationState）。
 *
 * ## 功能
 * - 增量应用：只更新变化的字段
 * - 状态继承：支持增量状态和完整状态
 * - 冗余合并：跳过无变化的帧
 * - 组边界计算：自动计算组的包围盒
 */

import type {
  AnimationState,
  StateDelta,
  NodeState,
  EdgeState,
  GroupState,
} from './types';

export interface StateMachineConfig {
  /** 是否合并冗余帧（跳过无变化的帧） */
  mergeRedundant?: boolean;
  /** 是否自动计算组边界 */
  autoGroupBounds?: boolean;
  /** 帧率（用于时间戳计算） */
  fps?: number;
}

const DEFAULT_CONFIG: Required<StateMachineConfig> = {
  mergeRedundant: true,
  autoGroupBounds: true,
  fps: 30,
};

export class StateMachine {
  private config: Required<StateMachineConfig>;
  private currentState: AnimationState | null = null;

  constructor(config?: StateMachineConfig) {
    this.config = { ...DEFAULT_CONFIG, ...config };
  }

  /**
   * 编译动画脚本，生成完整状态序列
   * @param initialState 初始状态
   * @param deltas 增量序列
   * @returns 完整状态数组
   */
  compile(initialState: AnimationState, deltas: StateDelta[]): AnimationState[] {
    const states: AnimationState[] = [this.cloneState(initialState)];
    this.currentState = initialState;

    for (const delta of deltas) {
      const nextState = this.applyDelta(delta);
      if (nextState) {
        // 合并冗余帧
        if (this.config.mergeRedundant && this.isRedundant(states[states.length - 1], nextState)) {
          continue;
        }
        states.push(nextState);
        this.currentState = nextState;
      }
    }

    return states;
  }

  /**
   * 应用增量到当前状态，生成新状态
   */
  private applyDelta(delta: StateDelta): AnimationState | null {
    if (!this.currentState) {
      return null;
    }

    const newState = this.cloneState(this.currentState);
    newState.stepIndex = delta.stepIndex;
    newState.timestamp = delta.stepIndex / this.config.fps * 1000;
    newState.comment = delta.comment;
    newState.metadata = { ...this.currentState.metadata, ...delta.metadata };

    // 应用节点更新
    for (const [nodeId, partial] of delta.nodeUpdates) {
      if (this.currentState.nodes.has(nodeId)) {
        // 更新现有节点
        const existing = this.currentState.nodes.get(nodeId)!;
        newState.nodes.set(nodeId, this.mergeNodeState(existing, partial));
      } else {
        // 新增节点
        const newNode: NodeState = {
          id: nodeId,
          position: partial.position || [0, 0],
          label: partial.label,
          style: partial.style || {},
          metadata: partial.metadata,
          changedFields: Object.keys(partial) as (keyof NodeState)[],
        };
        newState.nodes.set(nodeId, newNode);
      }
    }

    // 应用节点删除
    for (const nodeId of delta.nodeRemovals) {
      newState.nodes.delete(nodeId);
    }

    // 应用边更新
    for (const [edgeId, partial] of delta.edgeUpdates) {
      if (this.currentState.edges.has(edgeId)) {
        const existing = this.currentState.edges.get(edgeId)!;
        newState.edges.set(edgeId, this.mergeEdgeState(existing, partial));
      } else {
        const newEdge: EdgeState = {
          id: edgeId,
          source: partial.source || '',
          target: partial.target || '',
          label: partial.label,
          style: partial.style || {},
          metadata: partial.metadata,
          changedFields: Object.keys(partial) as (keyof EdgeState)[],
        };
        newState.edges.set(edgeId, newEdge);
      }
    }

    // 应用边删除
    for (const edgeId of delta.edgeRemovals) {
      newState.edges.delete(edgeId);
    }

    // 应用高亮/选中变更
    if (delta.highlights !== undefined) {
      newState.highlights = [...delta.highlights];
    }
    if (delta.selections !== undefined) {
      newState.selections = [...delta.selections];
    }

    // 应用组变更
    if (delta.groups) {
      this.applyGroupDelta(newState, delta.groups);
    }

    // 自动计算组边界
    if (this.config.autoGroupBounds && newState.groups) {
      this.calculateGroupBounds(newState);
    }

    return newState;
  }

  /** 合并节点状态 */
  private mergeNodeState(existing: NodeState, partial: Partial<NodeState>): NodeState {
    const changed: (keyof NodeState)[] = [];

    const merged: NodeState = {
      id: existing.id,
      position: partial.position ?? existing.position,
      label: partial.label ?? existing.label,
      style: { ...existing.style, ...partial.style },
      metadata: { ...existing.metadata, ...partial.metadata },
    };

    if (partial.position) changed.push('position');
    if (partial.label !== undefined) changed.push('label');
    if (partial.style) changed.push('style');
    if (partial.metadata) changed.push('metadata');

    merged.changedFields = changed.length > 0 ? changed : existing.changedFields;

    return merged;
  }

  /** 合并边状态 */
  private mergeEdgeState(existing: EdgeState, partial: Partial<EdgeState>): EdgeState {
    const changed: (keyof EdgeState)[] = [];

    const merged: EdgeState = {
      id: existing.id,
      source: existing.source,
      target: existing.target,
      label: partial.label ?? existing.label,
      style: { ...existing.style, ...partial.style },
      metadata: { ...existing.metadata, ...partial.metadata },
    };

    if (partial.label !== undefined) changed.push('label');
    if (partial.style) changed.push('style');
    if (partial.metadata) changed.push('metadata');

    merged.changedFields = changed.length > 0 ? changed : existing.changedFields;

    return merged;
  }

  /** 应用组增量 */
  private applyGroupDelta(state: AnimationState, groupDelta: NonNullable<StateDelta['groups']>): void {
    if (!state.groups) {
      state.groups = new Map();
    }

    // 创建/更新组
    if (groupDelta.createOrUpdate) {
      for (const groupData of groupDelta.createOrUpdate) {
        const existing = state.groups.get(groupData.id);
        const parentGroupId = (groupData.metadata as any)?.parentGroupId;
        const group: GroupState = existing
          ? {
              ...existing,
              label: groupData.label ?? existing.label,
              nodeIds: groupData.nodeIds,
              edgeIds: groupData.edgeIds ?? existing.edgeIds,
              style: groupData.style ? { ...existing.style, ...groupData.style } : existing.style,
              metadata: groupData.metadata ? { ...existing.metadata, ...groupData.metadata } : existing.metadata,
            }
          : {
              id: groupData.id,
              label: groupData.label,
              bounds: { x: 0, y: 0, width: 0, height: 0 },
              nodeIds: groupData.nodeIds,
              edgeIds: groupData.edgeIds || [],
              style: groupData.style,
              metadata: groupData.metadata,
              childGroupIds: [],
              nestingLevel: 0,
            };
        state.groups.set(groupData.id, group);

        // 处理父子关系
        if (parentGroupId) {
          group.metadata = group.metadata || {} as any;
          (group.metadata as any).parentGroupId = parentGroupId;
          // 设置嵌套层级
          const parent = state.groups.get(parentGroupId);
          group.nestingLevel = (parent?.nestingLevel || 0) + 1;
          // 加入父组的 childGroupIds
          if (parent && !parent.childGroupIds?.includes(groupData.id)) {
            if (!parent.childGroupIds) parent.childGroupIds = [];
            parent.childGroupIds.push(groupData.id);
          }
        }
      }
    }

    // 删除组
    if (groupDelta.remove) {
      for (const groupId of groupDelta.remove) {
        state.groups.delete(groupId);
        // 从父组中移除引用
        for (const [, group] of state.groups!) {
          if (group.childGroupIds) {
            const idx = group.childGroupIds.indexOf(groupId);
            if (idx !== -1) group.childGroupIds.splice(idx, 1);
          }
        }
      }
    }
  }

  /** 计算组的边界框 */
  private calculateGroupBounds(state: AnimationState): void {
    if (!state.groups) return;

    for (const [, group] of state.groups) {
      let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

      for (const nodeId of group.nodeIds) {
        const node = state.nodes.get(nodeId);
        if (node) {
          const [x, y] = node.position;
          minX = Math.min(minX, x);
          minY = Math.min(minY, y);
          maxX = Math.max(maxX, x);
          maxY = Math.max(maxY, y);
        }
      }

      if (maxX > -Infinity) {
        const padding = group.style?.padding || 20;
        group.bounds = {
          x: minX - padding,
          y: minY - padding,
          width: maxX - minX + padding * 2,
          height: maxY - minY + padding * 2,
        };
      }
    }
  }

  /** 判断两帧是否冗余（无视觉变化） */
  private isRedundant(prev: AnimationState, next: AnimationState): boolean {
    // 节点数量不同
    if (prev.nodes.size !== next.nodes.size || prev.edges.size !== next.edges.size) {
      return false;
    }

    // 高亮/选中不同
    if (
      JSON.stringify(prev.highlights) !== JSON.stringify(next.highlights) ||
      JSON.stringify(prev.selections) !== JSON.stringify(next.selections)
    ) {
      return false;
    }

    // 检查节点是否有变化
    for (const [nodeId, prevNode] of prev.nodes) {
      const nextNode = next.nodes.get(nodeId);
      if (!nextNode) return false;
      if (this.nodeChanged(prevNode, nextNode)) return false;
    }

    // 检查边是否有变化
    for (const [edgeId, prevEdge] of prev.edges) {
      const nextEdge = next.edges.get(edgeId);
      if (!nextEdge) return false;
      if (this.edgeChanged(prevEdge, nextEdge)) return false;
    }

    return true;
  }

  /** 判断节点是否变化 */
  private nodeChanged(a: NodeState, b: NodeState): boolean {
    if (a.position[0] !== b.position[0] || a.position[1] !== b.position[1]) return true;
    if (a.label !== b.label) return true;
    return JSON.stringify(a.style) !== JSON.stringify(b.style);
  }

  /** 判断边是否变化 */
  private edgeChanged(a: EdgeState, b: EdgeState): boolean {
    if (a.label !== b.label) return true;
    return JSON.stringify(a.style) !== JSON.stringify(b.style);
  }

  /** 深拷贝状态 */
  private cloneState(state: AnimationState): AnimationState {
    const nodes = new Map(state.nodes);
    const edges = new Map(state.edges);
    const groups = state.groups ? new Map(state.groups) : undefined;

    return {
      ...state,
      nodes,
      edges,
      groups,
      highlights: [...state.highlights],
      selections: [...state.selections],
      metadata: state.metadata ? { ...state.metadata } : undefined,
    };
  }

  /** 获取当前状态 */
  getCurrentState(): AnimationState | null {
    return this.currentState;
  }

  /** 重置状态机 */
  reset(): void {
    this.currentState = null;
  }
}

/** 便捷函数 - 编译脚本 */
export function compileScript(
  initialState: AnimationState,
  deltas: StateDelta[],
  config?: StateMachineConfig
): AnimationState[] {
  const machine = new StateMachine(config);
  return machine.compile(initialState, deltas);
}
