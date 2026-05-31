/**
 * 脚本构建器 - 链式 API
 * @module runtime/ScriptBuilder
 *
 * @description
 * 通过链式 API 构建动画指令序列。
 *
 * @example
 * ```typescript
 * const instructions = new ScriptBuilder()
 *   .addNode('A', { position: [100, 100], label: 'A' })
 *   .addNode('B', { position: [200, 200], label: 'B' })
 *   .addEdge('A', 'B', { label: 'connects' })
 *   .fadeIn(['A', 'B'], { duration: 500 })
 *   .highlight(['A'], { duration: 800 })
 *   .wait(1000)
 *   .compile();
 * ```
 */

import type {
  NodeId,
  EdgeId,
  Position,
  Duration,
  NodeStyle,
  EdgeStyle,
} from '../core/types';
import type { AnimationInstruction } from '../core/instructions/InstructionTypes';
import { InstructionFactory } from '../core/instructions/InstructionFactory';

export interface ScriptBuilderConfig {
  /** 默认动画时长 */
  defaultDuration?: Duration;
}

export class ScriptBuilder {
  private instructions: AnimationInstruction[] = [];
  private config: Required<ScriptBuilderConfig>;
  private nodeCounter = 0;
  private edgeCounter = 0;

  constructor(config?: ScriptBuilderConfig) {
    this.config = {
      defaultDuration: 500,
      ...config,
    };
  }

  // ==================== Graph 操作 ====================

  /** 添加节点 */
  addNode(
    id: NodeId,
    options?: {
      position?: Position;
      label?: string;
      style?: Partial<NodeStyle>;
    }
  ): this {
    this.instructions.push(
      InstructionFactory.addNode({
        nodeId: id,
        position: options?.position,
        label: options?.label,
        style: options?.style,
      })
    );
    this.nodeCounter++;
    return this;
  }

  /** 更新节点 */
  updateNode(
    id: NodeId,
    options?: {
      position?: Position;
      label?: string;
      style?: Partial<NodeStyle>;
    }
  ): this {
    this.instructions.push(
      InstructionFactory.updateNode({
        nodeId: id,
        position: options?.position,
        label: options?.label,
        style: options?.style,
      })
    );
    return this;
  }

  /** 移除节点 */
  removeNode(id: NodeId): this {
    this.instructions.push(InstructionFactory.removeNode({ nodeId: id }));
    return this;
  }

  /** 添加边 */
  addEdge(
    source: NodeId,
    target: NodeId,
    options?: {
      id?: EdgeId;
      label?: string;
      style?: Partial<EdgeStyle>;
    }
  ): this {
    const edgeId = options?.id || `${source}-${target}`;
    this.instructions.push(
      InstructionFactory.addEdge({
        edgeId,
        source,
        target,
        label: options?.label,
        style: options?.style,
      })
    );
    this.edgeCounter++;
    return this;
  }

  /** 移除边 */
  removeEdge(id: EdgeId): this {
    this.instructions.push(InstructionFactory.removeEdge({ edgeId: id }));
    return this;
  }

  // ==================== 动画操作 ====================

  /** 移动到 */
  moveTo(id: NodeId, position: Position, duration?: Duration): this {
    this.instructions.push(
      InstructionFactory.moveTo({
        nodeId: id,
        position,
        duration: duration || this.config.defaultDuration,
      })
    );
    return this;
  }

  /** 淡入 */
  fadeIn(ids: NodeId[], duration?: Duration): this {
    this.instructions.push(
      InstructionFactory.fadeIn({
        nodeIds: ids,
        duration: duration || this.config.defaultDuration,
      })
    );
    return this;
  }

  /** 淡出 */
  fadeOut(ids: NodeId[], duration?: Duration): this {
    this.instructions.push(
      InstructionFactory.fadeOut({
        nodeIds: ids,
        duration: duration || this.config.defaultDuration,
      })
    );
    return this;
  }

  /** 高亮 */
  highlight(ids: NodeId[], options?: { color?: string; duration?: Duration }): this {
    this.instructions.push(
      InstructionFactory.highlight({
        nodeIds: ids,
        color: options?.color,
        duration: options?.duration || this.config.defaultDuration,
      })
    );
    return this;
  }

  /** 清除高亮 */
  clearHighlight(ids?: NodeId[]): this {
    this.instructions.push(
      InstructionFactory.clearHighlight(ids ? { nodeIds: ids } : undefined)
    );
    return this;
  }

  /** 选择 */
  select(ids: NodeId[]): this {
    this.instructions.push(InstructionFactory.select({ nodeIds: ids }));
    return this;
  }

  /** 清除选择 */
  clearSelection(ids?: NodeId[]): this {
    this.instructions.push(
      InstructionFactory.clearSelection(ids ? { nodeIds: ids } : undefined)
    );
    return this;
  }

  // ==================== 控制操作 ====================

  /** 等待 */
  wait(duration: Duration): this {
    this.instructions.push(InstructionFactory.wait({ duration }));
    return this;
  }

  /** 注释 */
  comment(text: string): this {
    this.instructions.push(InstructionFactory.comment({ text }));
    return this;
  }

  // ==================== 效果操作 ====================

  /** 脉冲 */
  pulse(ids: NodeId[], options?: { count?: number; duration?: Duration }): this {
    this.instructions.push(
      InstructionFactory.pulse({
        nodeIds: ids,
        count: options?.count,
        duration: options?.duration || this.config.defaultDuration,
      })
    );
    return this;
  }

  /** 抖动 */
  shake(ids: NodeId[], options?: { intensity?: number; duration?: Duration }): this {
    this.instructions.push(
      InstructionFactory.shake({
        nodeIds: ids,
        intensity: options?.intensity,
        duration: options?.duration || this.config.defaultDuration,
      })
    );
    return this;
  }

  /** 发光 */
  glow(ids: NodeId[], options?: { color?: string; intensity?: number; duration?: Duration }): this {
    this.instructions.push(
      InstructionFactory.glow({
        nodeIds: ids,
        color: options?.color,
        intensity: options?.intensity,
        duration: options?.duration || this.config.defaultDuration,
      })
    );
    return this;
  }

  // ==================== 便捷方法 ====================

  /** 交换两个节点的位置 */
  swap(id1: NodeId, id2: NodeId, _duration?: Duration): this {
    // 需要在执行时获取当前位置，这里简化处理
    this.instructions.push(
      InstructionFactory.comment({ text: `swap ${id1} <-> ${id2}` })
    );
    return this;
  }

  /** 批量添加节点 */
  addNodes(
    nodes: Array<{
      id: NodeId;
      position?: Position;
      label?: string;
      style?: Partial<NodeStyle>;
    }>
  ): this {
    for (const node of nodes) {
      this.addNode(node.id, {
        position: node.position,
        label: node.label,
        style: node.style,
      });
    }
    return this;
  }

  /** 批量添加边 */
  addEdges(
    edges: Array<{
      source: NodeId;
      target: NodeId;
      label?: string;
      style?: Partial<EdgeStyle>;
    }>
  ): this {
    for (const edge of edges) {
      this.addEdge(edge.source, edge.target, {
        label: edge.label,
        style: edge.style,
      });
    }
    return this;
  }

  // ==================== 编译 ====================

  /** 编译为指令序列 */
  compile(): AnimationInstruction[] {
    return [...this.instructions];
  }

  /** 获取指令数量 */
  getInstructionCount(): number {
    return this.instructions.length;
  }

  /** 重置构建器 */
  reset(): this {
    this.instructions = [];
    this.nodeCounter = 0;
    this.edgeCounter = 0;
    return this;
  }
}

/** 便捷函数 */
export function createScriptBuilder(config?: ScriptBuilderConfig): ScriptBuilder {
  return new ScriptBuilder(config);
}
