/**
 * # Topo Animation Engine - 核心类型定义
 *
 * @packageDocumentation
 * @module core/types
 *
 * @description
 * 本模块定义了 Topo Animation Engine 的所有核心数据类型。
 *
 * ## 类型层次
 * ```
 * 基础类型 (NodeId, EdgeId, Timestamp, EasingFunction)
 *    ↓
 * 样式类型 (NodeStyle, EdgeStyle, GroupStyle)
 *    ↓
 * 状态类型 (NodeState, EdgeState, GroupState)
 *    ↓
 * 复合类型 (AnimationState, StateDelta)
 * ```
 *
 * ## 数据流
 * ```
 * TopoScript / ScriptBuilder → AnimationInstruction[]
 *    → InstructionExecutor → StateDelta[]
 *    → StateMachine → AnimationState[]
 *    → Renderer (SVG/Canvas)
 * ```
 */

// ==================== 基础类型 ====================

/** 节点唯一标识符 */
export type NodeId = string;

/** 边唯一标识符 */
export type EdgeId = string;

/** 组唯一标识符 */
export type GroupId = string;

/** 时间戳（毫秒） */
export type Timestamp = number;

/** 位置坐标 [x, y] */
export type Position = [number, number];

/** 颜色值（CSS 颜色字符串） */
export type Color = string;

/** 动画时长（毫秒） */
export type Duration = number;

/** 缓动函数名称 */
export type EasingName =
  | 'linear'
  | 'easeInQuad' | 'easeOutQuad' | 'easeInOutQuad'
  | 'easeInCubic' | 'easeOutCubic' | 'easeInOutCubic'
  | 'easeInExpo' | 'easeOutExpo' | 'easeInOutExpo'
  | 'easeInBack' | 'easeOutBack' | 'easeInOutBack'
  | 'easeInElastic' | 'easeOutElastic' | 'easeInOutElastic'
  | 'easeInBounce' | 'easeOutBounce' | 'easeInOutBounce';

/** 缓动函数类型：进度 [0,1] → 输出值 */
export type EasingFunction = (t: number) => number;

/** 节点形状 */
export type NodeShape =
  | 'circle'
  | 'rect'
  | 'diamond'
  | 'triangle'
  | 'hexagon'
  | 'ellipse'
  | 'image';

/** 节点类型（语义分类） */
export type NodeType =
  | 'service'
  | 'database'
  | 'queue'
  | 'external'
  | 'custom';

/** 布局类型 */
export type LayoutType =
  | 'force-directed'
  | 'hierarchy'
  | 'grid'
  | 'circular';

/** 渲染器类型 */
export type RendererType = 'd3' | 'pixi' | 'auto';

/** 动画效果类型 */
export type EffectType =
  | 'fade-scale'
  | 'slide-left'
  | 'slide-right'
  | 'slide-up'
  | 'slide-down'
  | 'bounce'
  | 'none';

/** 粒子类型 */
export type ParticleType =
  | 'spark'
  | 'heart'
  | 'star'
  | 'circle'
  | 'square'
  | 'triangle';

// ==================== 样式类型 ====================

/** 节点样式 */
export interface NodeStyle {
  shape?: NodeShape;
  fillColor?: Color;
  strokeColor?: Color;
  strokeWidth?: number;
  radius?: number;
  width?: number;
  height?: number;
  opacity?: number;
  fontSize?: number;
  fontColor?: Color;
  fontFamily?: string;
  imageUrl?: string;
  scale?: number;
  shadow?: {
    color: Color;
    blur: number;
    offsetX: number;
    offsetY: number;
  };
  gradient?: {
    type: 'linear' | 'radial';
    colors: Color[];
    positions?: number[];
  };
  [key: string]: any;
}

/** 边样式 */
export interface EdgeStyle {
  color?: Color;
  strokeWidth?: number;
  strokeDasharray?: string;
  opacity?: number;
  markerEnd?: string;
  markerStart?: string;
  curvature?: number;
  labelPosition?: number;
  type?: 'straight' | 'curved' | 'orthogonal';
  [key: string]: any;
}

/** 组样式 */
export interface GroupStyle {
  borderColor?: Color;
  borderWidth?: number;
  borderStyle?: 'solid' | 'dashed' | 'dotted' | 'none';
  fillColor?: Color;
  fillOpacity?: number;
  cornerRadius?: number;
  padding?: number;
  visible?: boolean;
  zIndex?: number;
  [key: string]: any;
}

// ==================== 元数据类型 ====================

/** 节点元数据 */
export interface NodeMetadata {
  uniqueId?: string;
  semanticType?: string;
  algorithm?: {
    role?: 'pivot' | 'candidate' | 'visited' | 'unvisited' | 'sorted' | 'unsorted' | string;
    step?: number;
    iteration?: number;
    comparisons?: number;
    swaps?: number;
    visited?: boolean;
    distance?: number;
    priority?: number;
    parent?: NodeId;
    [key: string]: any;
  };
  validation?: {
    required?: boolean;
    dependencies?: NodeId[];
    edgeDependencies?: EdgeId[];
    status?: 'pending' | 'valid' | 'invalid';
    errors?: string[];
  };
  business?: Record<string, any>;
  interaction?: {
    clickable?: boolean;
    draggable?: boolean;
    selectable?: boolean;
    deletable?: boolean;
    onClick?: string;
    tooltip?: string;
  };
  [key: string]: any;
}

/** 边元数据 */
export interface EdgeMetadata {
  uniqueId?: string;
  semanticType?: string;
  relationship?: {
    type?: 'depends-on' | 'points-to' | 'connected-with' | 'parent-of' | 'sibling-of' | string;
    strength?: number;
    bidirectional?: boolean;
    weight?: number;
    [key: string]: any;
  };
  validation?: {
    required?: boolean;
    sourceRequired?: boolean;
    targetRequired?: boolean;
    status?: 'pending' | 'valid' | 'invalid';
    errors?: string[];
  };
  business?: Record<string, any>;
  interaction?: {
    clickable?: boolean;
    selectable?: boolean;
    deletable?: boolean;
    tooltip?: string;
  };
  [key: string]: any;
}

/** 组元数据 */
export interface GroupMetadata {
  uniqueId?: string;
  semanticType?: string;
  parentGroupId?: GroupId;
  childGroupIds?: GroupId[];
  business?: Record<string, any>;
  interaction?: {
    clickable?: boolean;
    collapsible?: boolean;
    collapsed?: boolean;
    tooltip?: string;
    onClick?: string;
  };
  [key: string]: any;
}

// ==================== 组类型 ====================

/** 组边界框 */
export interface GroupBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** 组状态 */
export interface GroupState {
  id: GroupId;
  label?: string;
  bounds: GroupBounds;
  nodeIds: NodeId[];
  edgeIds: EdgeId[];
  childGroupIds?: GroupId[];
  nestingLevel?: number;
  style?: GroupStyle;
  metadata?: GroupMetadata;
  changedFields?: (keyof GroupState)[];
}

// ==================== 状态类型 ====================

/** 节点状态 */
export interface NodeState {
  id: NodeId;
  position: Position;
  label?: string;
  style: NodeStyle;
  changedFields?: (keyof NodeState)[];
  metadata?: NodeMetadata;
}

/** 边状态 */
export interface EdgeState {
  id: EdgeId;
  source: NodeId;
  target: NodeId;
  label?: string;
  style: EdgeStyle;
  changedFields?: (keyof EdgeState)[];
  metadata?: EdgeMetadata;
}

/** 动画状态（完整帧） */
export interface AnimationState {
  stepIndex: number;
  timestamp: Timestamp;
  nodes: Map<NodeId, NodeState>;
  edges: Map<EdgeId, EdgeState>;
  groups?: Map<GroupId, GroupState>;
  highlights: NodeId[];
  selections: NodeId[];
  comment?: string;
  metadata?: Record<string, unknown>;
  inheritsFromPrevious: boolean;
  isKeyFrame?: boolean;
  isSegmentEnd?: boolean;
  segmentId?: string;
}

/** 状态增量 */
export interface StateDelta {
  stepIndex: number;
  nodeUpdates: Map<NodeId, Partial<NodeState>>;
  nodeRemovals: NodeId[];
  edgeUpdates: Map<EdgeId, Partial<EdgeState>>;
  edgeRemovals: EdgeId[];
  highlights?: NodeId[];
  selections?: NodeId[];
  comment?: string;
  metadata?: Record<string, unknown>;
  groups?: {
    createOrUpdate?: Array<{
      id: GroupId;
      nodeIds: NodeId[];
      edgeIds?: EdgeId[];
      label?: string;
      style?: GroupStyle;
      metadata?: GroupMetadata;
    }>;
    remove?: GroupId[];
  };
}

// ==================== 配置类型 ====================

/** 节点配置（声明式） */
export interface NodeConfig {
  id: NodeId;
  position?: Position;
  pos?: Position;
  label?: string;
  style?: Partial<NodeStyle>;
  metadata?: NodeMetadata;
  type?: NodeType;
  shape?: NodeShape;
}

/** 边配置（声明式） */
export interface EdgeConfig {
  id?: EdgeId;
  source: NodeId;
  target: NodeId;
  label?: string;
  style?: Partial<EdgeStyle>;
  metadata?: EdgeMetadata;
}

/** 图配置 */
export interface GraphConfig {
  width?: number;
  height?: number;
  layout?: LayoutType;
  renderer?: RendererType;
  background?: Color;
  grid?: boolean;
  fps?: number;
}

/** 动画脚本（初始状态 + 增量序列） */
export interface AnimationScript {
  initialState: AnimationState;
  deltas: StateDelta[];
}

// ==================== 渲染类型 ====================

/** 渲染主题 */
export interface RenderTheme {
  name: string;
  background: Color;
  node: {
    defaultFill: Color;
    defaultStroke: Color;
    defaultFontSize: number;
    defaultFontColor: Color;
    highlightFill: Color;
    highlightStroke: Color;
    selectionStroke: Color;
  };
  edge: {
    defaultColor: Color;
    defaultWidth: number;
    highlightColor: Color;
    highlightWidth: number;
  };
  group: {
    defaultBorder: Color;
    defaultFill: Color;
    defaultFillOpacity: number;
  };
  text: {
    primary: Color;
    secondary: Color;
  };
}

/** 渲染选项 */
export interface RenderOptions {
  container: HTMLElement | string;
  width: number;
  height: number;
  theme?: RenderTheme;
  renderer?: RendererType;
  fps?: number;
  zoom?: boolean;
  pan?: boolean;
}

// ==================== 事件类型 ====================

/** 动画事件类型 */
export type AnimationEventType =
  | 'play'
  | 'pause'
  | 'stop'
  | 'seek'
  | 'step-change'
  | 'frame-render'
  | 'complete'
  | 'error'
  | 'node-click'
  | 'node-hover'
  | 'edge-click'
  | 'zoom'
  | 'pan';

/** 动画事件 */
export interface AnimationEvent {
  type: AnimationEventType;
  timestamp: Timestamp;
  data?: any;
}

/** 事件处理器 */
export type EventHandler = (event: AnimationEvent) => void;

// ==================== 场景配置 ====================

/** 场景配置（TopoScript scene 块） */
export interface SceneConfig {
  name?: string;
  layout: LayoutType;
  width: number;
  height: number;
  renderer: RendererType;
  background?: Color;
  grid?: boolean;
  fps?: number;
}

/** 流动粒子配置 */
export interface FlowParticleConfig {
  color?: Color;
  size?: number;
  speed?: number;
  type?: ParticleType;
}

/** 动画步骤配置 */
export interface AnimationStepConfig {
  type: 'enter' | 'exit' | 'draw-edge' | 'flow' | 'highlight' | 'reset' | 'wait' | 'morph';
  targets?: string[];
  path?: string[];
  effect?: EffectType;
  style?: Record<string, any>;
  particle?: FlowParticleConfig;
  duration: Duration;
  delay?: Duration;
}

/** 动画序列配置 */
export interface AnimationSequenceConfig {
  name: string;
  autoPlay?: boolean;
  loop?: boolean;
  steps: AnimationStepConfig[];
}

/** 交互配置 */
export interface InteractionConfig {
  target: string;
  events: Record<string, string>;
}

// ==================== 编译选项 ====================

/** 编译选项 */
export interface CompileOptions {
  scriptType?: 'toposcript' | 'api';
  validateOnly?: boolean;
  layout?: LayoutType;
  width?: number;
  height?: number;
}

/** 编译结果 */
export interface CompileResult {
  success: boolean;
  instructions?: any[];
  errors?: string[];
  warnings?: string[];
  stats?: {
    nodes: number;
    edges: number;
    steps: number;
    groups: number;
  };
}
