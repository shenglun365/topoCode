/**
 * 统一动画引擎
 * @module core/AnimationEngine
 *
 * @description
 * 整合编译、执行、渲染、播放的完整引擎。
 *
 * @example
 * ```typescript
 * const engine = new AnimationEngine({
 *   container: document.getElementById('stage'),
 *   renderer: 'svg',
 * });
 *
 * // 加载 TopoScript
 * engine.load(`
 *   topo.node({ id: "A", label: "A" })
 *   topo.node({ id: "B", label: "B" })
 *   topo.sequence({ steps: [
 *     { type: "enter", targets: ["A", "B"], duration: 500 }
 *   ]})
 * `);
 *
 * engine.play();
 * ```
 */

import type {
  AnimationState,
  RendererType,
  LayoutType,
  RenderTheme,
} from '../core/types';
import type { AnimationInstruction } from '../core/instructions/InstructionTypes';
import type { IRenderer } from '../renderer/IRenderer';
import type { AnimatorOptions } from '../animator/TopoAnimator';

import { compile } from '../compiler/compile';
import { executeInstructions } from '../core/instructions/InstructionExecutor';
import { StateMachine } from '../core/StateMachine';
import { SVGRenderer } from '../renderer/svg/SVGRenderer';
import { CanvasRenderer } from '../renderer/canvas/CanvasRenderer';
import { defaultTheme } from '../renderer/theme/defaultTheme';
import { applyLayout } from '../renderer/layout';
import { TopoAnimator } from '../animator/TopoAnimator';
import { EventEmitter } from '../runtime/EventEmitter';
import { RUNTIME } from '../utils/logger';

export interface EngineOptions extends AnimatorOptions {
  /** 渲染容器 */
  container: HTMLElement | string;
  /** 渲染器类型 */
  renderer?: RendererType;
  /** 画布宽度 */
  width?: number;
  /** 画布高度 */
  height?: number;
  /** 主题 */
  theme?: RenderTheme;
  /** 布局类型 */
  layout?: LayoutType;
  /** 帧率 */
  fps?: number;
  /** 是否自动播放 */
  autoPlay?: boolean;
  /** 缩放 */
  zoom?: boolean;
}

export class AnimationEngine {
  private options: Required<EngineOptions>;
  private renderer: IRenderer | null = null;
  private animator: TopoAnimator | null = null;
  private emitter = new EventEmitter();
  private states: AnimationState[] = [];
  private instructions: AnimationInstruction[] = [];

  constructor(options: EngineOptions) {
    this.options = {
      renderer: options.renderer || 'd3',
      width: options.width || 800,
      height: options.height || 600,
      theme: options.theme || defaultTheme,
      layout: options.layout || 'force-directed',
      fps: Math.min(60, Math.max(10, options.fps || 10)),
      autoPlay: options.autoPlay || false,
      zoom: options.zoom !== false,
      defaultFps: options.fps || 10,
      ...options,
    };
  }

  /** 初始化渲染器 */
  init(): void {
    const container =
      typeof this.options.container === 'string'
        ? document.querySelector(this.options.container) as HTMLElement
        : this.options.container;

    if (!container) {
      throw new Error('Container not found');
    }

    // 创建渲染器
    if (this.options.renderer === 'pixi') {
      this.renderer = new CanvasRenderer();
    } else {
      this.renderer = new SVGRenderer();
    }

    this.renderer.init({
      container,
      width: this.options.width,
      height: this.options.height,
      theme: this.options.theme,
      renderer: this.options.renderer,
      fps: this.options.fps,
      zoom: this.options.zoom,
    });

    // 创建动画播放器
    this.animator = new TopoAnimator({
      defaultFps: this.options.fps,
      autoPlay: this.options.autoPlay,
    });
    this.animator.setRenderer(this.renderer);

    // 订阅事件
    this.animator.on('play', (data) => this.emitter.emit('play', data));
    this.animator.on('pause', (data) => this.emitter.emit('pause', data));
    this.animator.on('stop', (data) => this.emitter.emit('stop', data));
    this.animator.on('complete', (data) => this.emitter.emit('complete', data));
    this.animator.on('step-change', (data) => this.emitter.emit('step-change', data));

    // 绑定渲染器交互事件
    this.renderer.setNodeClickHandler?.((nodeId) => {
      this.emitter.emit('node-click', { nodeId });
    });
    this.renderer.setNodeHoverHandler?.((nodeId) => {
      this.emitter.emit('node-hover', { nodeId });
    });
    this.renderer.setEdgeClickHandler?.((edgeId) => {
      this.emitter.emit('edge-click', { edgeId });
    });

    RUNTIME.info('AnimationEngine initialized', {
      renderer: this.options.renderer,
      width: this.options.width,
      height: this.options.height,
    });
  }

  /** 加载 TopoScript 源码 */
  load(source: string): this {
    // 确保渲染器已初始化
    if (!this.renderer) {
      this.init()
    }

    // 编译
    const compileResult = compile(source);

    if (!compileResult.success) {
      const error = new Error(`Compilation failed: ${compileResult.errors?.join(', ')}`);
      this.emitter.emit('error', { error });
      throw error;
    }

    this.instructions = compileResult.instructions || [];

    // 执行指令
    const execResult = executeInstructions(this.instructions);

    if (execResult.errors.length > 0) {
      RUNTIME.warn('Execution warnings:', execResult.errors);
    }

    // 构建初始状态
    const initialState: AnimationState = {
      stepIndex: 0,
      timestamp: 0,
      nodes: new Map(),
      edges: new Map(),
      highlights: [],
      selections: [],
      inheritsFromPrevious: false,
    };

    // 应用布局
    // 从所有 delta 累积初始节点/边（非动画场景下每个 addNode/addEdge 各占一个 delta）
    for (const delta of execResult.deltas) {
      for (const [nodeId, nodeData] of delta.nodeUpdates) {
        if (!initialState.nodes.has(nodeId)) {
          initialState.nodes.set(nodeId, {
            id: nodeId,
            position: nodeData.position || [0, 0],
            label: nodeData.label,
            style: nodeData.style || {},
            metadata: nodeData.metadata,
          })
        }
      }
      for (const [edgeId, edgeData] of delta.edgeUpdates) {
        if (!initialState.edges.has(edgeId)) {
          initialState.edges.set(edgeId, {
            id: edgeId,
            source: edgeData.source || '',
            target: edgeData.target || '',
            label: edgeData.label,
            style: edgeData.style || {},
          })
        }
      }
    }

    // 应用布局
    const laidOutNodes = applyLayout(
      this.options.layout,
      initialState.nodes,
      initialState.edges,
      this.options.width,
      this.options.height
    );
    initialState.nodes = laidOutNodes;

    // 编译状态序列
    const stateMachine = new StateMachine({ fps: this.options.fps });
    this.states = stateMachine.compile(initialState, execResult.deltas);

    // 设置到播放器
    if (this.animator) {
      this.animator.setStates(this.states);
    }

    // 渲染第一帧
    if (this.states.length > 0 && this.renderer) {
      const s0 = this.states[0]
      RUNTIME.info('Rendering first frame', {
        nodes: s0.nodes.size,
        edges: s0.edges.size,
        states: this.states.length,
      })
      // 输出前 3 个节点位置用于调试
      const sampleNodes = Array.from(s0.nodes.values()).slice(0, 3).map(n => ({
        id: n.id,
        pos: n.position,
        shape: n.style?.shape,
        fill: n.style?.fillColor,
      }))
      RUNTIME.info('Sample nodes:', sampleNodes)
      this.renderer.render(s0)
    }

    // 自动播放
    if (this.options.autoPlay) {
      this.play();
    }

    RUNTIME.info('Script loaded', {
      nodes: initialState.nodes.size,
      edges: initialState.edges.size,
      states: this.states.length,
    });

    return this;
  }

  /** 加载指令序列 */
  loadInstructions(instructions: AnimationInstruction[]): this {
    this.instructions = instructions;

    const execResult = executeInstructions(instructions);

    const initialState: AnimationState = {
      stepIndex: 0,
      timestamp: 0,
      nodes: new Map(),
      edges: new Map(),
      highlights: [],
      selections: [],
      inheritsFromPrevious: false,
    };

    const stateMachine = new StateMachine({ fps: this.options.fps });
    this.states = stateMachine.compile(initialState, execResult.deltas);

    if (this.animator) {
      this.animator.setStates(this.states);
    }

    if (this.states.length > 0 && this.renderer) {
      this.renderer.render(this.states[0]);
    }

    return this;
  }

  /** 播放 */
  play(): void {
    this.animator?.play();
  }

  /** 暂停 */
  pause(): void {
    this.animator?.pause();
  }

  /** 停止 */
  stop(): void {
    this.animator?.stop();
  }

  /** 跳转 */
  seek(step: number): void {
    this.animator?.seek(step);
  }

  /** 跳转到百分比 */
  seekPercent(percent: number): void {
    this.animator?.seekPercent(percent);
  }

  /** 获取渲染器 */
  getRenderer(): IRenderer | null {
    return this.renderer;
  }

  /** 获取当前状态 */
  getCurrentState(): AnimationState | null {
    return this.states[this.animator?.getState().currentStep || 0] || null;
  }

  /** 获取所有状态 */
  getStates(): AnimationState[] {
    return this.states;
  }

  /** 缩放到指定级别 */
  zoomToLevel(level: number): void {
    this.renderer?.zoomToLevel?.(level);
  }

  /** 适配屏幕 */
  fitToScreen(padding?: number): void {
    this.renderer?.fitToScreen?.(padding);
  }

  /** 重置缩放 */
  resetZoom(): void {
    this.renderer?.resetZoom?.();
  }

  /** 运行时切换布局 */
  switchLayout(layout: LayoutType): void {
    const currentState = this.getCurrentState();
    if (!currentState || !this.renderer) return;

    const laidOutNodes = applyLayout(
      layout,
      currentState.nodes,
      currentState.edges,
      this.options.width,
      this.options.height
    );
    currentState.nodes = laidOutNodes;
    this.renderer.render(currentState);

    RUNTIME.info('Layout switched', { layout });
  }

  /** 事件订阅 */
  on(event: string, handler: (...args: any[]) => void): void {
    this.emitter.on(event, handler);
  }

  off(event: string, handler: (...args: any[]) => void): void {
    this.emitter.off(event, handler);
  }

  /** 销毁 */
  destroy(): void {
    this.animator?.destroy()
    this.renderer?.destroy()
    this.emitter.removeAllListeners()
    this.states = []
    this.instructions = []
    this.renderer = undefined as any
    this.animator = undefined as any
    RUNTIME.info('AnimationEngine destroyed')
  }
}

/** 便捷函数 */
export function createAnimationEngine(options: EngineOptions): AnimationEngine {
  return new AnimationEngine(options);
}
