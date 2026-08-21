/**
 * 指令工厂 - 创建各种类型的动画指令
 * @module core/instructions/InstructionFactory
 */

import type {
  AnimationInstruction,
  AddNodePayload,
  UpdateNodePayload,
  RemoveNodePayload,
  AddEdgePayload,
  UpdateEdgePayload,
  RemoveEdgePayload,
  CreateGroupPayload,
  UpdateGroupPayload,
  RemoveGroupPayload,
  MoveToPayload,
  MoveByPayload,
  ScaleToPayload,
  ScaleByPayload,
  FadeInPayload,
  FadeOutPayload,
  RotateToPayload,
  RotateByPayload,
  HighlightPayload,
  ClearHighlightPayload,
  SelectPayload,
  ClearSelectionPayload,
  ShowTooltipPayload,
  HideTooltipPayload,
  WaitPayload,
  CommentPayload,
  IfPayload,
  ForPayload,
  SwitchPayload,
  CallPayload,
  PulsePayload,
  ShakePayload,
  GlowPayload,
  ParticlePayload,
} from './InstructionTypes';

export class InstructionFactory {
  // ==================== Graph 指令 ====================

  static addNode(payload: AddNodePayload): AnimationInstruction {
    return { type: 'addNode', payload };
  }

  static updateNode(payload: UpdateNodePayload): AnimationInstruction {
    return { type: 'updateNode', payload };
  }

  static removeNode(payload: RemoveNodePayload): AnimationInstruction {
    return { type: 'removeNode', payload };
  }

  static addEdge(payload: AddEdgePayload): AnimationInstruction {
    return { type: 'addEdge', payload };
  }

  static updateEdge(payload: UpdateEdgePayload): AnimationInstruction {
    return { type: 'updateEdge', payload };
  }

  static removeEdge(payload: RemoveEdgePayload): AnimationInstruction {
    return { type: 'removeEdge', payload };
  }

  static createGroup(payload: CreateGroupPayload): AnimationInstruction {
    return { type: 'createGroup', payload };
  }

  static updateGroup(payload: UpdateGroupPayload): AnimationInstruction {
    return { type: 'updateGroup', payload };
  }

  static removeGroup(payload: RemoveGroupPayload): AnimationInstruction {
    return { type: 'removeGroup', payload };
  }

  // ==================== Animation 指令 ====================

  static moveTo(payload: MoveToPayload): AnimationInstruction {
    return { type: 'moveTo', payload };
  }

  static moveBy(payload: MoveByPayload): AnimationInstruction {
    return { type: 'moveBy', payload };
  }

  static scaleTo(payload: ScaleToPayload): AnimationInstruction {
    return { type: 'scaleTo', payload };
  }

  static scaleBy(payload: ScaleByPayload): AnimationInstruction {
    return { type: 'scaleBy', payload };
  }

  static fadeIn(payload: FadeInPayload): AnimationInstruction {
    return { type: 'fadeIn', payload };
  }

  static fadeOut(payload: FadeOutPayload): AnimationInstruction {
    return { type: 'fadeOut', payload };
  }

  static rotateTo(payload: RotateToPayload): AnimationInstruction {
    return { type: 'rotateTo', payload };
  }

  static rotateBy(payload: RotateByPayload): AnimationInstruction {
    return { type: 'rotateBy', payload };
  }

  // ==================== Interaction 指令 ====================

  static highlight(payload: HighlightPayload): AnimationInstruction {
    return { type: 'highlight', payload };
  }

  static clearHighlight(payload?: ClearHighlightPayload): AnimationInstruction {
    return { type: 'clearHighlight', payload: payload || {} };
  }

  static select(payload: SelectPayload): AnimationInstruction {
    return { type: 'select', payload };
  }

  static clearSelection(payload?: ClearSelectionPayload): AnimationInstruction {
    return { type: 'clearSelection', payload: payload || {} };
  }

  static showTooltip(payload: ShowTooltipPayload): AnimationInstruction {
    return { type: 'showTooltip', payload };
  }

  static hideTooltip(payload?: HideTooltipPayload): AnimationInstruction {
    return { type: 'hideTooltip', payload: payload || {} };
  }

  // ==================== Control 指令 ====================

  static wait(payload: WaitPayload): AnimationInstruction {
    return { type: 'wait', payload };
  }

  static comment(payload: CommentPayload): AnimationInstruction {
    return { type: 'comment', payload };
  }

  static ifBranch(payload: IfPayload): AnimationInstruction {
    return { type: 'if', payload };
  }

  static forLoop(payload: ForPayload): AnimationInstruction {
    return { type: 'for', payload };
  }

  static switchBranch(payload: SwitchPayload): AnimationInstruction {
    return { type: 'switch', payload };
  }

  static call(payload: CallPayload): AnimationInstruction {
    return { type: 'call', payload };
  }

  // ==================== Effect 指令 ====================

  static pulse(payload: PulsePayload): AnimationInstruction {
    return { type: 'pulse', payload };
  }

  static shake(payload: ShakePayload): AnimationInstruction {
    return { type: 'shake', payload };
  }

  static glow(payload: GlowPayload): AnimationInstruction {
    return { type: 'glow', payload };
  }

  static particle(payload: ParticlePayload): AnimationInstruction {
    return { type: 'particle', payload };
  }
}

/** 便捷函数 - 创建单个指令 */
export function createInstruction<T extends AnimationInstruction['type']>(
  type: T,
  payload: any
): AnimationInstruction {
  return { type, payload } as AnimationInstruction;
}

/** 便捷函数 - 批量创建指令 */
export function createInstructions(
  instructions: Array<{ type: AnimationInstruction['type']; payload: any }>
): AnimationInstruction[] {
  return instructions.map(({ type, payload }) => ({ type, payload } as AnimationInstruction));
}

/** 指令构建器 - 链式 API */
export class InstructionBuilder {
  private instructions: AnimationInstruction[] = [];

  addNode(payload: AddNodePayload): this {
    this.instructions.push(InstructionFactory.addNode(payload));
    return this;
  }

  updateNode(payload: UpdateNodePayload): this {
    this.instructions.push(InstructionFactory.updateNode(payload));
    return this;
  }

  removeNode(payload: RemoveNodePayload): this {
    this.instructions.push(InstructionFactory.removeNode(payload));
    return this;
  }

  addEdge(payload: AddEdgePayload): this {
    this.instructions.push(InstructionFactory.addEdge(payload));
    return this;
  }

  updateEdge(payload: UpdateEdgePayload): this {
    this.instructions.push(InstructionFactory.updateEdge(payload));
    return this;
  }

  removeEdge(payload: RemoveEdgePayload): this {
    this.instructions.push(InstructionFactory.removeEdge(payload));
    return this;
  }

  moveTo(payload: MoveToPayload): this {
    this.instructions.push(InstructionFactory.moveTo(payload));
    return this;
  }

  moveBy(payload: MoveByPayload): this {
    this.instructions.push(InstructionFactory.moveBy(payload));
    return this;
  }

  fadeIn(payload: FadeInPayload): this {
    this.instructions.push(InstructionFactory.fadeIn(payload));
    return this;
  }

  fadeOut(payload: FadeOutPayload): this {
    this.instructions.push(InstructionFactory.fadeOut(payload));
    return this;
  }

  highlight(payload: HighlightPayload): this {
    this.instructions.push(InstructionFactory.highlight(payload));
    return this;
  }

  clearHighlight(payload?: ClearHighlightPayload): this {
    this.instructions.push(InstructionFactory.clearHighlight(payload));
    return this;
  }

  wait(payload: WaitPayload): this {
    this.instructions.push(InstructionFactory.wait(payload));
    return this;
  }

  comment(payload: CommentPayload): this {
    this.instructions.push(InstructionFactory.comment(payload));
    return this;
  }

  pulse(payload: PulsePayload): this {
    this.instructions.push(InstructionFactory.pulse(payload));
    return this;
  }

  glow(payload: GlowPayload): this {
    this.instructions.push(InstructionFactory.glow(payload));
    return this;
  }

  particle(payload: ParticlePayload): this {
    this.instructions.push(InstructionFactory.particle(payload));
    return this;
  }

  build(): AnimationInstruction[] {
    return [...this.instructions];
  }

  clear(): this {
    this.instructions = [];
    return this;
  }
}

export function createInstructionBuilder(): InstructionBuilder {
  return new InstructionBuilder();
}
