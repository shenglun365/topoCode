/**
 * 标准化动画指令类型定义
 * @module core/instructions/InstructionTypes
 *
 * @description
 * 动画指令集是脚本无关的标准化指令系统，用于统一不同脚本语言
 * 到统一的动画操作表示。
 *
 * ## 指令分类
 * - **Graph**: 图结构操作（节点/边/组的增删改）
 * - **Animation**: 动画变换（移动/缩放/淡入淡出/旋转）
 * - **Interaction**: 交互状态（高亮/选择/工具提示）
 * - **Control**: 控制流（等待/注释/条件/循环/调用）
 * - **Effect**: 视觉效果（脉冲/抖动/发光/粒子）
 */

import type { NodeId, EdgeId, GroupId, Duration, EasingName } from '../types';

// ==================== 基础接口 ====================

export interface BaseInstruction<T extends string, P> {
  type: T;
  payload: P;
}

// ==================== Graph 指令 Payload ====================

export interface AddNodePayload {
  nodeId: NodeId;
  position?: [number, number];
  label?: string;
  style?: Record<string, any>;
  metadata?: Record<string, any>;
}

export interface UpdateNodePayload {
  nodeId: NodeId;
  position?: [number, number];
  label?: string;
  style?: Record<string, any>;
}

export interface RemoveNodePayload {
  nodeId: NodeId;
}

export interface AddEdgePayload {
  edgeId: EdgeId;
  source: NodeId;
  target: NodeId;
  label?: string;
  style?: Record<string, any>;
  metadata?: Record<string, any>;
}

export interface UpdateEdgePayload {
  edgeId: EdgeId;
  label?: string;
  style?: Record<string, any>;
}

export interface RemoveEdgePayload {
  edgeId: EdgeId;
}

export interface CreateGroupPayload {
  groupId: GroupId;
  nodeIds: NodeId[];
  edgeIds?: EdgeId[];
  parentGroupId?: GroupId;
  label?: string;
  style?: Record<string, any>;
  metadata?: Record<string, any>;
}

export interface UpdateGroupPayload {
  groupId: GroupId;
  nodeIds?: NodeId[];
  edgeIds?: EdgeId[];
  label?: string;
  style?: Record<string, any>;
}

export interface RemoveGroupPayload {
  groupId: GroupId;
}

// ==================== Animation 指令 Payload ====================

export interface MoveToPayload {
  nodeId: NodeId;
  position: [number, number];
  duration?: Duration;
  easing?: EasingName;
}

export interface MoveByPayload {
  nodeId: NodeId;
  delta: [number, number];
  duration?: Duration;
  easing?: EasingName;
}

export interface ScaleToPayload {
  nodeId: NodeId;
  scale: number;
  duration?: Duration;
}

export interface ScaleByPayload {
  nodeId: NodeId;
  scaleDelta: number;
  duration?: Duration;
}

export interface FadeInPayload {
  nodeIds: NodeId[];
  duration?: Duration;
}

export interface FadeOutPayload {
  nodeIds: NodeId[];
  duration?: Duration;
}

export interface RotateToPayload {
  nodeId: NodeId;
  angle: number;
  duration?: Duration;
}

export interface RotateByPayload {
  nodeId: NodeId;
  angleDelta: number;
  duration?: Duration;
}

// ==================== Interaction 指令 Payload ====================

export interface HighlightPayload {
  nodeIds: NodeId[];
  color?: string;
  scale?: number;
  duration?: Duration;
}

export interface ClearHighlightPayload {
  nodeIds?: NodeId[];
}

export interface SelectPayload {
  nodeIds: NodeId[];
}

export interface ClearSelectionPayload {
  nodeIds?: NodeId[];
}

export interface ShowTooltipPayload {
  nodeId: NodeId;
  content: string;
  position?: [number, number];
}

export interface HideTooltipPayload {
  nodeId?: NodeId;
}

// ==================== Control 指令 Payload ====================

export interface WaitPayload {
  duration: Duration;
}

export interface CommentPayload {
  text: string;
}

export interface IfPayload {
  condition: string;
  thenBranch: AnimationInstruction[];
  elseBranch?: AnimationInstruction[];
}

export interface ForPayload {
  variable: string;
  from: number;
  to: number;
  step?: number;
  body: AnimationInstruction[];
}

export interface SwitchPayload {
  expression: string;
  cases: Array<{
    value: string | number;
    body: AnimationInstruction[];
  }>;
  default?: AnimationInstruction[];
}

export interface CallPayload {
  macroName: string;
  arguments: Record<string, any>;
}

// ==================== Effect 指令 Payload ====================

export interface PulsePayload {
  nodeIds: NodeId[];
  count?: number;
  duration?: Duration;
}

export interface ShakePayload {
  nodeIds: NodeId[];
  intensity?: number;
  duration?: Duration;
}

export interface GlowPayload {
  nodeIds: NodeId[];
  color?: string;
  intensity?: number;
  duration?: Duration;
}

export interface ParticlePayload {
  nodeId: NodeId;
  particleType?: 'spark' | 'heart' | 'star' | 'circle' | 'square' | 'triangle';
  count?: number;
  duration?: Duration;
  color?: string;
}

// ==================== 指令类型定义 ====================

// Graph
export type AddNodeInstruction = BaseInstruction<'addNode', AddNodePayload>;
export type UpdateNodeInstruction = BaseInstruction<'updateNode', UpdateNodePayload>;
export type RemoveNodeInstruction = BaseInstruction<'removeNode', RemoveNodePayload>;
export type AddEdgeInstruction = BaseInstruction<'addEdge', AddEdgePayload>;
export type UpdateEdgeInstruction = BaseInstruction<'updateEdge', UpdateEdgePayload>;
export type RemoveEdgeInstruction = BaseInstruction<'removeEdge', RemoveEdgePayload>;
export type CreateGroupInstruction = BaseInstruction<'createGroup', CreateGroupPayload>;
export type UpdateGroupInstruction = BaseInstruction<'updateGroup', UpdateGroupPayload>;
export type RemoveGroupInstruction = BaseInstruction<'removeGroup', RemoveGroupPayload>;

// Animation
export type MoveToInstruction = BaseInstruction<'moveTo', MoveToPayload>;
export type MoveByInstruction = BaseInstruction<'moveBy', MoveByPayload>;
export type ScaleToInstruction = BaseInstruction<'scaleTo', ScaleToPayload>;
export type ScaleByInstruction = BaseInstruction<'scaleBy', ScaleByPayload>;
export type FadeInInstruction = BaseInstruction<'fadeIn', FadeInPayload>;
export type FadeOutInstruction = BaseInstruction<'fadeOut', FadeOutPayload>;
export type RotateToInstruction = BaseInstruction<'rotateTo', RotateToPayload>;
export type RotateByInstruction = BaseInstruction<'rotateBy', RotateByPayload>;

// Interaction
export type HighlightInstruction = BaseInstruction<'highlight', HighlightPayload>;
export type ClearHighlightInstruction = BaseInstruction<'clearHighlight', ClearHighlightPayload>;
export type SelectInstruction = BaseInstruction<'select', SelectPayload>;
export type ClearSelectionInstruction = BaseInstruction<'clearSelection', ClearSelectionPayload>;
export type ShowTooltipInstruction = BaseInstruction<'showTooltip', ShowTooltipPayload>;
export type HideTooltipInstruction = BaseInstruction<'hideTooltip', HideTooltipPayload>;

// Control
export type WaitInstruction = BaseInstruction<'wait', WaitPayload>;
export type CommentInstruction = BaseInstruction<'comment', CommentPayload>;
export type IfInstruction = BaseInstruction<'if', IfPayload>;
export type ForInstruction = BaseInstruction<'for', ForPayload>;
export type SwitchInstruction = BaseInstruction<'switch', SwitchPayload>;
export type CallInstruction = BaseInstruction<'call', CallPayload>;

// Effect
export type PulseInstruction = BaseInstruction<'pulse', PulsePayload>;
export type ShakeInstruction = BaseInstruction<'shake', ShakePayload>;
export type GlowInstruction = BaseInstruction<'glow', GlowPayload>;
export type ParticleInstruction = BaseInstruction<'particle', ParticlePayload>;

// ==================== 联合类型 ====================

/** 所有动画指令的联合类型 */
export type AnimationInstruction =
  // Graph (9)
  | AddNodeInstruction
  | UpdateNodeInstruction
  | RemoveNodeInstruction
  | AddEdgeInstruction
  | UpdateEdgeInstruction
  | RemoveEdgeInstruction
  | CreateGroupInstruction
  | UpdateGroupInstruction
  | RemoveGroupInstruction
  // Animation (8)
  | MoveToInstruction
  | MoveByInstruction
  | ScaleToInstruction
  | ScaleByInstruction
  | FadeInInstruction
  | FadeOutInstruction
  | RotateToInstruction
  | RotateByInstruction
  // Interaction (6)
  | HighlightInstruction
  | ClearHighlightInstruction
  | SelectInstruction
  | ClearSelectionInstruction
  | ShowTooltipInstruction
  | HideTooltipInstruction
  // Control (6)
  | WaitInstruction
  | CommentInstruction
  | IfInstruction
  | ForInstruction
  | SwitchInstruction
  | CallInstruction
  // Effect (4)
  | PulseInstruction
  | ShakeInstruction
  | GlowInstruction
  | ParticleInstruction;

/** 指令类型字符串 */
export type InstructionType = AnimationInstruction['type'];

// ==================== 辅助类型 ====================

/** 指令类型 → Payload 映射 */
export interface InstructionPayloadMap {
  addNode: AddNodePayload;
  updateNode: UpdateNodePayload;
  removeNode: RemoveNodePayload;
  addEdge: AddEdgePayload;
  updateEdge: UpdateEdgePayload;
  removeEdge: RemoveEdgePayload;
  createGroup: CreateGroupPayload;
  updateGroup: UpdateGroupPayload;
  removeGroup: RemoveGroupPayload;
  moveTo: MoveToPayload;
  moveBy: MoveByPayload;
  scaleTo: ScaleToPayload;
  scaleBy: ScaleByPayload;
  fadeIn: FadeInPayload;
  fadeOut: FadeOutPayload;
  rotateTo: RotateToPayload;
  rotateBy: RotateByPayload;
  highlight: HighlightPayload;
  clearHighlight: ClearHighlightPayload;
  select: SelectPayload;
  clearSelection: ClearSelectionPayload;
  showTooltip: ShowTooltipPayload;
  hideTooltip: HideTooltipPayload;
  wait: WaitPayload;
  comment: CommentPayload;
  if: IfPayload;
  for: ForPayload;
  switch: SwitchPayload;
  call: CallPayload;
  pulse: PulsePayload;
  shake: ShakePayload;
  glow: GlowPayload;
  particle: ParticlePayload;
}

/** 根据指令类型获取 Payload 类型 */
export type GetPayload<T extends InstructionType> = InstructionPayloadMap[T];
