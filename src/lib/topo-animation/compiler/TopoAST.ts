/**
 * TopoScript AST 类型定义
 * @module compiler/TopoAST
 *
 * @description
 * 统一两种语法风格的中间表示：
 * - 风格 A: `topo.xxx({...})`
 * - 风格 B: `node A at (x,y)`
 */

import type {
  LayoutType,
  RendererType,
  NodeShape,
  NodeType,
  EffectType,
  Position,
  Color,
  Duration,
} from '../core/types';

// ==================== 顶层 AST ====================

/** TopoScript 完整 AST */
export interface TopoAST {
  scene?: SceneNode;
  nodes: TopoNode[];
  edges: TopoEdge[];
  groups: TopoGroup[];
  sequences: SequenceNode[];
  interactions: InteractionNode[];
  // 插件扩展
  variables?: VariableNode[];
  functions?: FunctionNode[];
}

// ==================== 场景节点 ====================

export interface SceneNode {
  kind: 'scene';
  name?: string;
  layout?: LayoutType;
  width?: number;
  height?: number;
  renderer?: RendererType;
  background?: Color;
  grid?: boolean;
  fps?: number;
}

// ==================== 节点定义 ====================

export interface TopoNode {
  kind: 'node';
  id: string;
  label?: string;
  position?: Position;
  type?: NodeType;
  shape?: NodeShape;
  style?: Record<string, any>;
  metadata?: Record<string, any>;
}

// ==================== 边定义 ====================

export interface TopoEdge {
  kind: 'edge';
  id?: string;
  source: string;
  target: string;
  label?: string;
  style?: Record<string, any>;
  metadata?: Record<string, any>;
}

// ==================== 组定义 ====================

export interface TopoGroup {
  kind: 'group';
  id: string;
  label?: string;
  nodeIds: string[];
  edgeIds?: string[];
  style?: Record<string, any>;
  metadata?: Record<string, any>;
}

// ==================== 动画序列 ====================

export interface SequenceNode {
  kind: 'sequence';
  name: string;
  autoPlay?: boolean;
  loop?: boolean;
  steps: AnimationStepNode[];
}

export type AnimationStepNode =
  | EnterStep
  | ExitStep
  | DrawEdgeStep
  | FlowStep
  | HighlightStep
  | ResetStep
  | WaitStep
  | MorphStep
  | MoveStep
  | ScaleStep
  | FadeStep
  | RotateStep
  | PulseStep
  | ShakeStep
  | GlowStep
  | ParticleStep
  | ConditionalStep
  | LoopStep;

export interface BaseStep {
  duration?: Duration;
  delay?: Duration;
}

export interface EnterStep extends BaseStep {
  type: 'enter';
  targets: string[];
  effect?: EffectType;
}

export interface ExitStep extends BaseStep {
  type: 'exit';
  targets: string[];
  effect?: EffectType;
}

export interface DrawEdgeStep extends BaseStep {
  type: 'draw-edge';
  targets: string[];
}

export interface FlowStep extends BaseStep {
  type: 'flow';
  path: string[];
  particle?: {
    color?: Color;
    size?: number;
    speed?: number;
    type?: 'spark' | 'heart' | 'star' | 'circle' | 'square' | 'triangle';
  };
}

export interface HighlightStep extends BaseStep {
  type: 'highlight';
  targets: string[];
  color?: Color;
  scale?: number;
}

export interface ResetStep extends BaseStep {
  type: 'reset';
  targets: string[];
}

export interface WaitStep extends BaseStep {
  type: 'wait';
  duration: Duration;
}

export interface MorphStep extends BaseStep {
  type: 'morph';
  targets: string[];
  to: Record<string, any>;
}

export interface MoveStep extends BaseStep {
  type: 'move';
  target: string;
  position: Position;
  easing?: string;
}

export interface ScaleStep extends BaseStep {
  type: 'scale';
  target: string;
  scale: number;
}

export interface FadeStep extends BaseStep {
  type: 'fade';
  targets: string[];
  opacity: number;
}

export interface RotateStep extends BaseStep {
  type: 'rotate';
  target: string;
  angle: number;
}

export interface PulseStep extends BaseStep {
  type: 'pulse';
  targets: string[];
  count?: number;
}

export interface ShakeStep extends BaseStep {
  type: 'shake';
  targets: string[];
  intensity?: number;
}

export interface GlowStep extends BaseStep {
  type: 'glow';
  targets: string[];
  color?: Color;
  intensity?: number;
}

export interface ParticleStep extends BaseStep {
  type: 'particle';
  target: string;
  particleType?: 'spark' | 'heart' | 'star' | 'circle' | 'square' | 'triangle';
  count?: number;
  color?: Color;
}

export interface ConditionalStep extends BaseStep {
  type: 'conditional';
  condition: string;
  thenSteps: AnimationStepNode[];
  elseSteps?: AnimationStepNode[];
}

export interface LoopStep extends BaseStep {
  type: 'loop';
  variable: string;
  from: number;
  to: number;
  step?: number;
  body: AnimationStepNode[];
}

// ==================== 交互定义 ====================

export interface InteractionNode {
  kind: 'interaction';
  target: string;
  events: Record<string, string>;
}

// ==================== 插件扩展 ====================

export interface VariableNode {
  kind: 'variable';
  name: string;
  type: 'let' | 'const' | 'var';
  value?: ExpressionNode;
}

export interface FunctionNode {
  kind: 'function';
  name: string;
  params: string[];
  body: (TopoNode | TopoEdge | AnimationStepNode)[];
}

export type ExpressionNode =
  | { type: 'literal'; value: string | number | boolean | null }
  | { type: 'identifier'; name: string }
  | { type: 'binary'; op: string; left: ExpressionNode; right: ExpressionNode }
  | { type: 'unary'; op: string; operand: ExpressionNode }
  | { type: 'call'; func: string; args: ExpressionNode[] }
  | { type: 'member'; object: ExpressionNode; property: string }
  | { type: 'array'; elements: ExpressionNode[] }
  | { type: 'object'; properties: Record<string, ExpressionNode> };
