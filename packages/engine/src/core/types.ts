export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
}

export type StyleMap = Record<string, string>;

export type PathCommand =
  | { c: 'M' | 'L'; x: number; y: number }
  | { c: 'C'; x1: number; y1: number; x2: number; y2: number; x: number; y: number }
  | { c: 'Q'; x1: number; y1: number; x: number; y: number }
  | { c: 'A'; rx: number; ry: number; rot: number; laf: number; sf: number; x: number; y: number }
  | { c: 'Z' };

export interface PathSpec {
  d: PathCommand[];
  style: StyleMap;
}

export interface TextSpec {
  content: string;
  x: number;
  y: number;
  anchor: 'start' | 'middle' | 'end';
  box: Box;
  style: StyleMap;
}

export type ElementKind = 'node' | 'edge' | 'label' | 'shape' | 'group';

export interface ElementSource {
  backend: string;
  docIndex: number;
  sel: string;
}

export interface SceneElement {
  key: string;
  kind: ElementKind;
  bbox: Box;
  paths: PathSpec[];
  text: TextSpec[];
  style: StyleMap;
  z: number;
  source: ElementSource;
  /** 边元素端点键（若可解析），供 degree 排序 */
  endpoints?: { from: string; to: string };
  /** BFS 波次（capture 依据端点关系计算，供 order:'degree'） */
  depth?: number;
}

export interface SceneSpec {
  elements: SceneElement[];
  width: number;
  height: number;
  type: string;
  backend: string;
  /** 归一化后画布在 IR 空间的原点（锚定模式 = {-half,-half}） */
  origin?: { x: number; y: number };
  /** 产物根 svg 的原始背景（捕获时剥离入 IR；渲染画布自持背景，导出时回贴） */
  background?: string;
}

/** reveal = 构建式入场（逐帧累积显现）；transition = 帧间形变 */
export type AnimationMode = 'reveal' | 'transition';

export type OrderStrategy =
  | 'doc'
  | 'degree'
  | 'position'
  | 'reverse'
  | ((a: SceneElement, b: SceneElement) => number);

export type DiffClass = 'enter' | 'exit' | 'update' | 'move' | 'style' | 'text' | 'stay';

export interface MoveEntry {
  key: string;
  from: Box;
  to: Box;
  el: SceneElement;
  prev: SceneElement;
  dx: number;
  dy: number;
}

export interface UpdateEntry {
  key: string;
  prev: SceneElement;
  next: SceneElement;
  geom: boolean;
  style: boolean;
  morphable: boolean;
}

export interface TextEntry {
  key: string;
  prev: string;
  next: string;
  el: SceneElement;
  prevEl: SceneElement;
}

export interface FrameDiff {
  from: number;
  to: number;
  enter: SceneElement[];
  exit: SceneElement[];
  move: MoveEntry[];
  update: UpdateEntry[];
  text: TextEntry[];
  stay: string[];
}

export interface TransitionSpec {
  type: 'fade' | 'scale' | 'drawIn' | 'slide' | 'textCross' | 'morph';
  durationMs: number;
  easing?: string;
}

export type FrameOp =
  | { op: 'add'; el: { key: string } & Partial<Omit<SceneElement, 'key'>> }
  | { op: 'remove'; key: string }
  | { op: 'update'; key: string; patch: Partial<Pick<SceneElement, 'bbox' | 'paths' | 'style'>> }
  | { op: 'text'; key: string; content: string }
  | { op: 'move'; key: string; to: { x: number; y: number } };

export interface FrameOpts {
  durationMs?: number;
  order?: OrderStrategy;
  staggerMs?: number;
  overlap?: number;
  /** false = 关闭该动画的帧级首帧锁定（完全按后端原始坐标） */
  align?: boolean;
  transitions?: Partial<Record<'enter' | 'exit' | 'move' | 'update' | 'text' | 'style', TransitionSpec>>;
}

export interface Frame {
  /** 模式A：本帧完整 DSL 文本（需要 backend 渲染） */
  source?: string;
  /** 离线喂入通道：本帧完整 SVG 文本（M0/M2 测试与降级路径） */
  svg?: string;
  /** 模式B：相对上一帧的增量脚本（M3） */
  script?: FrameOp[];
  layout?: 'engine' | 'keep';
  opts?: FrameOpts;
}

export interface Animation {
  backend: string;
  frames: Frame[];
  mode?: AnimationMode;
  stepMs?: number;
  /** 'lock'(默认) = 帧级首帧刚性锁定 + 统一画布；'none' = 完全按后端原始坐标 */
  align?: 'lock' | 'none';
}

export interface TimelineItem {
  key: string;
  cls: 'enter' | 'exit' | 'move' | 'update' | 'text' | 'style';
  kind: ElementKind;
  el: SceneElement;
  prev?: SceneElement;
  delayMs: number;
  transition: TransitionSpec;
}

export interface TimelineSpec {
  items: TimelineItem[];
  totalMs: number;
  frameMs: number;
}

export interface FrameSource {
  spec: SceneSpec;
  svg: SVGSVGElement;
  /** 冻结的原始 DOM（任何布局/偏移变换之前；手动位置可无限次幂等重建的基底） */
  raw?: SVGSVGElement;
  /** 冻结的原始 IR（与 raw 同级；锁定/偏移均从此重算） */
  rawSpec?: SceneSpec;
}

export interface ApplyContext {
  from?: FrameSource;
  to: FrameSource;
  animate: boolean;
  mode: AnimationMode;
  /** 播放倍速（Renderer 缩放所有过渡时长与延迟） */
  speed?: number;
}

export interface Renderer {
  mount(host: Element): void;
  setFrame(src: FrameSource, opts?: { hidden?: boolean }): void;
  applyDiff(diff: FrameDiff, timeline: TimelineSpec, ctx: ApplyContext): Promise<void>;
  snapshot(): FrameSource | null;
  dispose(): void;
}

export interface AnimationState {
  index: number;
  playing: boolean;
}

export interface AnimationController {
  readonly mode: AnimationMode;
  readonly total: number;
  get index(): number;
  get playing(): boolean;
  play(): void;
  pause(): void;
  stop(): void;
  next(): void;
  prev(): void;
  seek(i: number): void;
  setSpeed(multiplier: number): void;
  /** 等待当前应用链落定（宿主编排/测试同步用） */
  idle(): Promise<void>;
  subscribe(cb: (s: AnimationState) => void): () => void;
  dispose(): void;
}

export interface ApplyInfo {
  animate: boolean;
  speed: number;
}

export function boxesEqual(a: Box, b: Box, eps = 1): boolean {
  return (
    Math.abs(a.x - b.x) < eps &&
    Math.abs(a.y - b.y) < eps &&
    Math.abs(a.width - b.width) < eps &&
    Math.abs(a.height - b.height) < eps
  );
}

export function unionBox(a: Box, b: Box): Box {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  const x2 = Math.max(a.x + a.width, b.x + b.width);
  const y2 = Math.max(a.y + a.height, b.y + b.height);
  return { x, y, width: x2 - x, height: y2 - y };
}

export function zeroBox(): Box {
  return { x: 0, y: 0, width: 0, height: 0 };
}

export function bboxIntersectionArea(a: Box, b: Box): number {
  const x = Math.max(0, Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x));
  const y = Math.max(0, Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y));
  return x * y;
}
