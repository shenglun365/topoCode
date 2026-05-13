/**
 * 指令执行器 - 将 AnimationInstruction[] 转换为 StateDelta[]
 * @module core/instructions/InstructionExecutor
 *
 * @description
 * 执行器遍历指令序列，将每条指令转换为对应的状态增量（StateDelta）。
 * 支持 Graph/Animation/Interaction/Control/Effect 五大类指令。
 */

import type {
  AnimationInstruction,
  InstructionType,
} from './InstructionTypes';
import type { StateDelta, NodeState, EdgeState } from '../types';

export interface ExecuteOptions {
  /** 默认动画时长（毫秒） */
  defaultDuration?: number;
  /** 是否跳过控制流指令 */
  skipControl?: boolean;
  /** 是否跳过效果指令 */
  skipEffect?: boolean;
}

export interface ExecuteResult {
  deltas: StateDelta[];
  errors: string[];
  stats: {
    totalInstructions: number;
    executedInstructions: number;
    skippedInstructions: number;
  };
}

const DEFAULT_OPTIONS: Required<ExecuteOptions> = {
  defaultDuration: 500,
  skipControl: false,
  skipEffect: false,
};

export class InstructionExecutor {
  private options: Required<ExecuteOptions>;
  private deltas: StateDelta[];
  private errors: string[];
  private stepIndex: number;
  private executedCount: number;
  private skippedCount: number;

  constructor(options?: ExecuteOptions) {
    this.options = { ...DEFAULT_OPTIONS, ...options };
    this.deltas = [];
    this.errors = [];
    this.stepIndex = 0;
    this.executedCount = 0;
    this.skippedCount = 0;
  }

  /** 执行指令序列，返回状态增量数组 */
  execute(instructions: AnimationInstruction[]): ExecuteResult {
    this.reset();

    for (const instruction of instructions) {
      try {
        this.executeOne(instruction);
        this.executedCount++;
      } catch (error) {
        this.errors.push(
          `Instruction '${instruction.type}' failed: ${error instanceof Error ? error.message : String(error)}`
        );
      }
    }

    return {
      deltas: this.deltas,
      errors: this.errors,
      stats: {
        totalInstructions: instructions.length,
        executedInstructions: this.executedCount,
        skippedInstructions: this.skippedCount,
      },
    };
  }

  private executeOne(instruction: AnimationInstruction): void {
    const { type, payload } = instruction;

    // 控制流指令
    if (['wait', 'comment', 'if', 'for', 'switch', 'call'].includes(type)) {
      if (this.options.skipControl) {
        this.skippedCount++;
        return;
      }
      this.executeControl(type, payload);
      return;
    }

    // 效果指令
    if (['pulse', 'shake', 'glow', 'particle'].includes(type)) {
      if (this.options.skipEffect) {
        this.skippedCount++;
        return;
      }
      this.executeEffect(type, payload);
      return;
    }

    // Graph / Animation / Interaction 指令
    const delta = this.createDelta();
    this.executeStateChange(type, payload, delta);
  }

  private executeStateChange(
    type: InstructionType,
    payload: any,
    delta: StateDelta
  ): void {
    switch (type) {
      // ==================== Graph ====================
      case 'addNode': {
        const nodeUpdate: Partial<NodeState> = {
          id: payload.nodeId,
          position: payload.position || [0, 0],
          label: payload.label,
          style: payload.style || {},
          metadata: payload.metadata,
        };
        delta.nodeUpdates.set(payload.nodeId, nodeUpdate);
        break;
      }

      case 'updateNode': {
        const nodeUpdate: Partial<NodeState> = {};
        if (payload.position) nodeUpdate.position = payload.position;
        if (payload.label !== undefined) nodeUpdate.label = payload.label;
        if (payload.style) nodeUpdate.style = payload.style;
        if (Object.keys(nodeUpdate).length > 0) {
          delta.nodeUpdates.set(payload.nodeId, nodeUpdate);
        }
        break;
      }

      case 'removeNode': {
        delta.nodeRemovals.push(payload.nodeId);
        break;
      }

      case 'addEdge': {
        const edgeUpdate: Partial<EdgeState> = {
          id: payload.edgeId,
          source: payload.source,
          target: payload.target,
          label: payload.label,
          style: payload.style || {},
          metadata: payload.metadata,
        };
        delta.edgeUpdates.set(payload.edgeId, edgeUpdate);
        break;
      }

      case 'updateEdge': {
        const edgeUpdate: Partial<EdgeState> = {};
        if (payload.label !== undefined) edgeUpdate.label = payload.label;
        if (payload.style) edgeUpdate.style = payload.style;
        if (Object.keys(edgeUpdate).length > 0) {
          delta.edgeUpdates.set(payload.edgeId, edgeUpdate);
        }
        break;
      }

      case 'removeEdge': {
        delta.edgeRemovals.push(payload.edgeId);
        break;
      }

      // ==================== Group ====================
      case 'createGroup': {
        if (!delta.groups) delta.groups = { createOrUpdate: [] };
        delta.groups.createOrUpdate.push({
          id: payload.groupId,
          nodeIds: payload.nodeIds,
          edgeIds: payload.edgeIds,
          label: payload.label,
          style: payload.style,
          metadata: payload.metadata,
        });
        break;
      }

      case 'updateGroup': {
        if (!delta.groups) delta.groups = { createOrUpdate: [] };
        const groupUpdate: any = { id: payload.groupId };
        if (payload.nodeIds) groupUpdate.nodeIds = payload.nodeIds;
        if (payload.edgeIds) groupUpdate.edgeIds = payload.edgeIds;
        if (payload.label !== undefined) groupUpdate.label = payload.label;
        if (payload.style) groupUpdate.style = payload.style;
        delta.groups.createOrUpdate.push(groupUpdate);
        break;
      }

      case 'removeGroup': {
        if (!delta.groups) delta.groups = { remove: [] };
        delta.groups.remove.push(payload.groupId);
        break;
      }

      // ==================== Animation ====================
      case 'moveTo': {
        const nodeUpdate: Partial<NodeState> = {
          position: payload.position,
          style: { scale: 1 },
        };
        delta.nodeUpdates.set(payload.nodeId, nodeUpdate);
        break;
      }

      case 'moveBy': {
        // MoveBy needs current position, handled by StateMachine
        const nodeUpdate: Partial<NodeState> = {
          style: { ...payload },
        };
        delta.nodeUpdates.set(payload.nodeId, nodeUpdate);
        break;
      }

      case 'scaleTo': {
        const nodeUpdate: Partial<NodeState> = {
          style: { scale: payload.scale },
        };
        delta.nodeUpdates.set(payload.nodeId, nodeUpdate);
        break;
      }

      case 'scaleBy': {
        const nodeUpdate: Partial<NodeState> = {
          style: { scaleDelta: payload.scaleDelta },
        };
        delta.nodeUpdates.set(payload.nodeId, nodeUpdate);
        break;
      }

      case 'fadeIn': {
        for (const nodeId of payload.nodeIds) {
          const existing = delta.nodeUpdates.get(nodeId) || {};
          delta.nodeUpdates.set(nodeId, {
            ...existing,
            style: { ...existing.style, opacity: 1 },
          });
        }
        break;
      }

      case 'fadeOut': {
        for (const nodeId of payload.nodeIds) {
          const existing = delta.nodeUpdates.get(nodeId) || {};
          delta.nodeUpdates.set(nodeId, {
            ...existing,
            style: { ...existing.style, opacity: 0 },
          });
        }
        break;
      }

      case 'rotateTo':
      case 'rotateBy': {
        const nodeUpdate: Partial<NodeState> = {
          style: { rotation: type === 'rotateTo' ? payload.angle : payload.angleDelta },
        };
        delta.nodeUpdates.set(
          type === 'rotateTo' ? payload.nodeId : payload.nodeId,
          nodeUpdate
        );
        break;
      }

      // ==================== Interaction ====================
      case 'highlight': {
        delta.highlights = payload.nodeIds;
        break;
      }

      case 'clearHighlight': {
        delta.highlights = [];
        break;
      }

      case 'select': {
        delta.selections = payload.nodeIds;
        break;
      }

      case 'clearSelection': {
        delta.selections = [];
        break;
      }

      case 'showTooltip':
      case 'hideTooltip': {
        // Tooltips are renderer-specific, stored in metadata
        break;
      }

      default: {
        this.errors.push(`Unknown instruction type: ${type}`);
      }
    }

    if (this.hasContent(delta)) {
      this.deltas.push(delta);
      this.stepIndex++;
    }
  }

  private executeControl(type: InstructionType, payload: any): void {
    switch (type) {
      case 'wait': {
        // Wait creates an empty delta with a timestamp offset
        const delta = this.createDelta();
        delta.comment = `wait ${payload.duration}ms`;
        this.deltas.push(delta);
        this.stepIndex++;
        break;
      }

      case 'comment': {
        // Comment is metadata only
        break;
      }

      case 'if':
      case 'for':
      case 'switch':
      case 'call': {
        // Control flow - recursively execute branches
        // For now, flatten to sequential execution
        let branchInstructions: AnimationInstruction[] = [];

        if (type === 'if') {
          branchInstructions = payload.thenBranch;
        } else if (type === 'for') {
          // Expand loop
          const { variable, from, to, step = 1, body } = payload;
          for (let i = from; i < to; i += step) {
            const expanded = JSON.parse(
              JSON.stringify(body, (key, value) =>
                key === variable && typeof value === 'string' ? String(i) : value
              )
            );
            branchInstructions.push(...expanded);
          }
        } else if (type === 'switch') {
          // Execute first matching case or default
          const firstCase = payload.cases[0];
          branchInstructions = firstCase?.body || payload.default || [];
        } else if (type === 'call') {
          // Macro call - placeholder
          break;
        }

        // Recursively execute branch
        if (branchInstructions.length > 0) {
          for (const instr of branchInstructions) {
            this.executeOne(instr);
          }
        }
        break;
      }
    }
  }

  private executeEffect(type: InstructionType, payload: any): void {
    // Effects are visual-only, stored as metadata for renderer
    const delta = this.createDelta();

    switch (type) {
      case 'pulse': {
        delta.metadata = { effect: 'pulse', nodeIds: payload.nodeIds, count: payload.count };
        break;
      }
      case 'shake': {
        delta.metadata = { effect: 'shake', nodeIds: payload.nodeIds, intensity: payload.intensity };
        break;
      }
      case 'glow': {
        delta.metadata = {
          effect: 'glow',
          nodeIds: payload.nodeIds,
          color: payload.color,
          intensity: payload.intensity,
        };
        break;
      }
      case 'particle': {
        delta.metadata = {
          effect: 'particle',
          nodeId: payload.nodeId,
          particleType: payload.particleType,
          count: payload.count,
          color: payload.color,
        };
        break;
      }
    }

    if (delta.metadata) {
      this.deltas.push(delta);
      this.stepIndex++;
    }
  }

  private createDelta(): StateDelta {
    return {
      stepIndex: this.stepIndex,
      nodeUpdates: new Map(),
      nodeRemovals: [],
      edgeUpdates: new Map(),
      edgeRemovals: [],
    };
  }

  private hasContent(delta: StateDelta): boolean {
    return (
      delta.nodeUpdates.size > 0 ||
      delta.nodeRemovals.length > 0 ||
      delta.edgeUpdates.size > 0 ||
      delta.edgeRemovals.length > 0 ||
      delta.highlights !== undefined ||
      delta.selections !== undefined ||
      delta.comment !== undefined ||
      delta.metadata !== undefined ||
      delta.groups !== undefined
    );
  }

  private reset(): void {
    this.deltas = [];
    this.errors = [];
    this.stepIndex = 0;
    this.executedCount = 0;
    this.skippedCount = 0;
  }
}

/** 便捷函数 - 执行指令并返回结果 */
export function executeInstructions(
  instructions: AnimationInstruction[],
  options?: ExecuteOptions
): ExecuteResult {
  const executor = new InstructionExecutor(options);
  return executor.execute(instructions);
}
