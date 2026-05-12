/**
 * # @topocode/topo-animation
 *
 * 纯前端动画引擎，用于架构可视化和算法教学。
 *
 * ## 快速开始
 *
 * ```typescript
 * import {
 *   compile,
 *   AnimationEngine,
 *   ScriptBuilder,
 *   SVGRenderer,
 *   CanvasRenderer,
 *   defaultTheme,
 * } from '@topocode/topo-animation';
 *
 * // 方式 1: TopoScript
 * const engine = new AnimationEngine({
 *   container: document.getElementById('stage'),
 *   renderer: 'svg',
 * });
 *
 * engine.load(`
 *   topo.scene({ name: "Demo", layout: "grid" })
 *   topo.node({ id: "A", label: "Node A" })
 *   topo.node({ id: "B", label: "Node B" })
 *   topo.edge({ source: "A", target: "B" })
 *   topo.sequence({ steps: [
 *     { type: "enter", targets: ["A", "B"], duration: 500 },
 *   ]})
 * `);
 *
 * engine.play();
 *
 * // 方式 2: TypeScript API
 * const states = new ScriptBuilder()
 *   .addNode('A', { position: [100, 100], label: 'A' })
 *   .addNode('B', { position: [200, 100], label: 'B' })
 *   .addEdge('A', 'B')
 *   .fadeIn(['A', 'B'], { duration: 500 })
 *   .compile();
 * ```
 *
 * @packageDocumentation
 */

// ==================== 版本 ====================

export const VERSION = '1.0.0';
export const VERSION_MAJOR = 1;
export const VERSION_MINOR = 0;
export const VERSION_PATCH = 0;

// ==================== 核心模块 ====================

export type {
  // 基础类型
  NodeId,
  EdgeId,
  GroupId,
  Timestamp,
  Position,
  Color,
  Duration,
  EasingName,
  EasingFunction,
  NodeShape,
  NodeType,
  LayoutType,
  RendererType,
  EffectType,
  ParticleType,

  // 样式类型
  NodeStyle,
  EdgeStyle,
  GroupStyle,

  // 状态类型
  NodeState,
  EdgeState,
  GroupState,
  AnimationState,
  StateDelta,

  // 元数据类型
  NodeMetadata,
  EdgeMetadata,
  GroupMetadata,

  // 配置类型
  NodeConfig,
  EdgeConfig,
  GraphConfig,
  AnimationScript,

  // 渲染类型
  RenderTheme,
  RenderOptions,

  // 事件类型
  AnimationEventType,
  AnimationEvent,
  EventHandler,

  // 场景配置
  SceneConfig,
  FlowParticleConfig,
  AnimationStepConfig,
  AnimationSequenceConfig,
  InteractionConfig,

  // 编译
  CompileOptions,
  CompileResult,
} from './core/types';

export {
  StateMachine,
  compileScript,
} from './core/StateMachine';

// ==================== 指令系统 ====================

export type {
  AnimationInstruction,
  InstructionType,
  InstructionPayloadMap,
  GetPayload,

  // Graph
  AddNodeInstruction,
  UpdateNodeInstruction,
  RemoveNodeInstruction,
  AddEdgeInstruction,
  UpdateEdgeInstruction,
  RemoveEdgeInstruction,
  CreateGroupInstruction,
  UpdateGroupInstruction,
  RemoveGroupInstruction,

  // Animation
  MoveToInstruction,
  MoveByInstruction,
  ScaleToInstruction,
  ScaleByInstruction,
  FadeInInstruction,
  FadeOutInstruction,
  RotateToInstruction,
  RotateByInstruction,

  // Interaction
  HighlightInstruction,
  ClearHighlightInstruction,
  SelectInstruction,
  ClearSelectionInstruction,
  ShowTooltipInstruction,
  HideTooltipInstruction,

  // Control
  WaitInstruction,
  CommentInstruction,
  IfInstruction,
  ForInstruction,
  SwitchInstruction,
  CallInstruction,

  // Effect
  PulseInstruction,
  ShakeInstruction,
  GlowInstruction,
  ParticleInstruction,
} from './core/instructions/InstructionTypes';

export {
  InstructionFactory,
  createInstruction,
  createInstructions,
  InstructionBuilder,
  createInstructionBuilder,
} from './core/instructions/InstructionFactory';

export {
  InstructionExecutor,
  executeInstructions,
} from './core/instructions/InstructionExecutor';

export type {
  ExecuteOptions,
  ExecuteResult,
} from './core/instructions/InstructionExecutor';

// ==================== 工具函数 ====================

export {
  // 缓动函数
  EasingFunctions,
  EasingFunctionNames,
  getEasingFunction,
  linear,
  easeInQuad,
  easeOutQuad,
  easeInOutQuad,
  easeInCubic,
  easeOutCubic,
  easeInOutCubic,
  easeInExpo,
  easeOutExpo,
  easeInOutExpo,
  easeInBack,
  easeOutBack,
  easeInOutBack,
  easeInElastic,
  easeOutElastic,
  easeInOutElastic,
  easeInBounce,
  easeOutBounce,
  easeInOutBounce,
} from './utils/easing';

export {
  // 错误处理
  AnimationEngineError,
  CompilationError,
  RuntimeError,
  createSyntaxError,
  createSemanticError,
  createValidationError,
  createRuntimeError,
} from './utils/error';

export type {
  ErrorCode,
} from './utils/error';

export {
  // 日志
  Logger,
  COMPILER,
  PARSER,
  RUNTIME,
  RENDERER,
  BUILDER,
} from './utils/logger';

export type {
  LogLevel,
  LogEntry,
  LogHandler,
} from './utils/logger';

// ==================== 编译器 ====================

export {
  compile,
  validate,
  TopoTokenizer,
  tokenize,
  TopoParser,
  parse,
  TopoSemanticChecker,
  checkSemantics,
  TopoCodeGenerator,
  generateCode,
} from './compiler';

export type {
  Token,
  TokenType,
  TopoAST,
  SceneNode,
  TopoNode,
  TopoEdge,
  TopoGroup,
  SequenceNode,
  AnimationStepNode,
  InteractionNode,
  VariableNode,
  FunctionNode,
  ExpressionNode,
} from './compiler';

// ==================== 插件系统 ====================

export {
  PluginManager,
  pluginManager,
  VariableScopeImpl,
  createRootScope,
  FunctionRegistryImpl,
  createFunctionRegistry,
  registerBuiltins,
  ConditionEngineImpl,
  createConditionEngine,
} from './compiler/plugin';

export type {
  TopoScriptPlugin,
  TopoRuntime,
  VariableScope,
  FunctionRegistry,
  TopoFunction,
  ConditionEngine,
  PluginMeta,
} from './compiler/plugin';

// ==================== 渲染器 ====================

export type { IRenderer } from './renderer/IRenderer';
export { SVGRenderer } from './renderer/svg/SVGRenderer';
export { CanvasRenderer } from './renderer/canvas/CanvasRenderer';

export {
  themeManager,
  getTheme,
  setTheme,
  mergeTheme,
  defaultTheme,
  darkTheme,
  oceanTheme,
  forestTheme,
  sunsetTheme,
  monokaiTheme,
  themePresets,
} from './renderer/theme/defaultTheme';

export type { ThemeName } from './renderer/theme/defaultTheme';

export {
  forceLayout,
  hierarchyLayout,
  gridLayout,
  circularLayout,
  applyLayout,
} from './renderer/layout';

// ==================== 动画播放器 ====================

export { TopoAnimator, createAnimator } from './animator/TopoAnimator';
export type { AnimatorOptions, AnimatorState } from './animator/TopoAnimator';

// ==================== 运行时 ====================

export { EventEmitter } from './runtime/EventEmitter';
export { TimelineController, createTimeline } from './runtime/TimelineController';
export type { TimelineOptions, TimelineState } from './runtime/TimelineController';
export { ScriptBuilder, createScriptBuilder } from './runtime/ScriptBuilder';
export type { ScriptBuilderConfig } from './runtime/ScriptBuilder';

// ==================== 统一引擎 ====================

export { AnimationEngine, createAnimationEngine } from './core/AnimationEngine';
export type { EngineOptions } from './core/AnimationEngine';

// ==================== 导出功能 ====================

export {
  exportPNG,
  exportSVG,
  exportImage,
  downloadImage,
  exportHTML,
  downloadHTML,
  exportJSON,
  downloadJSON,
} from './export';

export type {
  ExportImageOptions,
  ExportHTMLOptions,
  ExportJSONOptions,
} from './export';
