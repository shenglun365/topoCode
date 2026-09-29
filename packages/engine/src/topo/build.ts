/**
 * TopoScript v2 构建期：Document → StateGraphSpec（纯帧序列 lowering）。
 *
 * 模型：帧按声明序线性链接 f0→f1→…→fN；每帧 = 静态结构源文；
 * 帧间过渡 = diff 管线（plan 编译器惰性缓存），帧驻留 = step/auto（HOLD 时长）。
 * 无任何逻辑产物（v1 @@logic/@generate/when/actions 已移除）。
 *
 * 选项语义（@options 全局默认，@@frame 行同名键覆写）：
 *   step=<ms>       帧驻留（HOLD）时长，到点自动进下一帧
 *   auto=false      该帧驻留后等待手动 next（全局设 auto=false 即"逐步播放"模式）
 *   enter|exit=<t>  进入/离场动画类型 ∈ {fade,scale,drawIn,slide,textCross,morph}
 *   enterMs|exitMs  上述动画时长
 *   duration=<ms>   主补间时长（move/morph/text 槽位）
 *   order=<o>       元素编排序 ∈ {source,degree,file,reverse}
 *   stagger=<ms>    槽位错峰
 *   align=false     关闭帧级首帧锁定
 */

import type { EdgeChoreography, StateGraphSpec, StoryEdge, StoryStateDef } from '../story/types';
import type { TopoDiagnostic, TopoDocument } from './types';
import { TOPO_DIAG_CODES } from './document';

const ENTER_TYPES = new Set(['fade', 'scale', 'drawIn', 'slide', 'textCross', 'morph']);
const ORDERS = new Set(['source', 'degree', 'file', 'reverse']);

export interface TopoFrameInfo {
  id: string;
  source: string;
  frameLine: number;
  /** 生效选项（全局默认 + 帧级覆写合并后） */
  options: Record<string, string | number | boolean>;
}

export interface TopoBuildResult {
  doc: TopoDocument;
  graph: StateGraphSpec;
  frames: TopoFrameInfo[];
  errors: TopoDiagnostic[];
  ok: boolean;
}

export type OptMap = Record<string, string | number | boolean>;
type ErrSink = (line: number, message: string, code?: string, fixes?: string[], frame?: string) => void;

function numOpt(v: string | number | boolean | undefined): number | undefined {
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined;
}

/** 帧驻留/推进语义（timingOf）：step/auto 键 → state.dwellMs/auto */
export function timingOf(o: OptMap): Pick<StoryStateDef, 'dwellMs' | 'auto'> {
  const step = o.auto === false ? undefined : (numOpt(o.step) ?? numOpt(o.auto));
  const auto = o.auto === false ? false : undefined;
  return { dwellMs: step, auto };
}

/** 进入边过渡编排（choreOf）：duration/order/stagger/overlap/enter/exit → EdgeChoreography；非法值经 err 上报 */
export function choreOf(o: OptMap, line: number, frameId: string, err: ErrSink): EdgeChoreography | undefined {
  const chore: EdgeChoreography = {};
  const duration = numOpt(o.duration) ?? numOpt(o.step);
  if (duration !== undefined) chore.durationMs = duration;
  if (typeof o.order === 'string') {
    if (!ORDERS.has(o.order)) err(line, `order "${o.order}" 不合法（∈ source|degree|file|reverse）`, TOPO_DIAG_CODES.buildBadOrder, ['order ∈ {source,degree,file,reverse}'], frameId);
    else chore.order = o.order as never;
  }
  const stagger = numOpt(o.stagger);
  if (stagger !== undefined) chore.staggerMs = stagger;
  const overlap = numOpt(o.overlap);
  if (overlap !== undefined) chore.overlap = overlap;
  if (o.align === false) chore.align = false;
  for (const side of ['enter', 'exit'] as const) {
    const t = o[side];
    if (t === undefined) continue;
    if (typeof t !== 'string' || !ENTER_TYPES.has(t)) { err(line, `${side} 动画类型需 ∈ {fade,scale,drawIn,slide,textCross,morph}，得到 "${String(t)}"`, TOPO_DIAG_CODES.buildBadEnter, [`${side} ∈ {fade,scale,drawIn,slide,textCross,morph}`], frameId); continue; }
    const ms = numOpt(o[`${side}Ms`]) ?? 450;
    chore.transitions = chore.transitions ?? {};
    chore.transitions[side] = { type: t as never, durationMs: ms };
  }
  return Object.keys(chore).length ? chore : undefined;
}

/** 帧序列 → 线性图（states + 链式 edges）；timing/编排键见本文件头注释。SVG 形态见 story-from-sources。 */
export function framesToGraph(
  frames: { id: string; source: string; options: OptMap }[],
  globalOptions: OptMap,
  err: ErrSink,
): { states: StoryStateDef[]; edges: StoryEdge[] } {
  const merged = frames.map((f) => ({ ...globalOptions, ...f.options }));
  const states: StoryStateDef[] = frames.map((f, i) => ({
    id: f.id, source: f.source, ...timingOf(merged[i] as OptMap),
  }));
  const edges: StoryEdge[] = [];
  for (let i = 1; i < frames.length; i++) {
    const chore = choreOf(merged[i] as OptMap, 0, frames[i].id, err);
    edges.push({ from: frames[i - 1].id, to: frames[i].id, choreography: chore });
  }
  return { states, edges };
}

export function buildTopoStory(doc: TopoDocument): TopoBuildResult {
  const errors: TopoDiagnostic[] = doc.errors.map((e) => ({ ...e }));
  const err: ErrSink = (line, message, code, fixes, frame) => {
    errors.push({ line, message, severity: 'error', ...(code ? { code } : {}), ...(fixes?.length ? { supportedFixes: fixes } : {}), ...(frame ? { frame } : {}) } as TopoDiagnostic);
  };

  const merged = doc.frames.map((f) => ({ ...doc.options, ...f.options }));
  const { states, edges } = framesToGraph(
    doc.frames.map((f, i) => ({ id: f.id, source: f.source, options: merged[i] as OptMap, frameLine: f.frameLine })),
    doc.options,
    (line, message, code, fixes, frame) => {
      const src = doc.frames.find((f) => f.id === frame);
      err(src?.frameLine ?? line, message, code, fixes, frame);
    },
  );

  if (doc.frames.length === 0) err(1, '无可构建帧', TOPO_DIAG_CODES.buildEmpty, ['补写至少一个 @@frame/@@source 块']);
  const fatal = errors.some((e) => e.severity === 'error');
  if (fatal) {
    return { doc, graph: { entry: '', states: [], edges: [], vars: {} }, frames: [], errors, ok: false };
  }

  const graph: StateGraphSpec = {
    entry: doc.frames[0].id,
    states,
    edges,
    vars: {},
  };
  const frames: TopoFrameInfo[] = doc.frames.map((f, i) => ({
    id: f.id, source: f.source, frameLine: f.frameLine, options: merged[i] as OptMap,
  }));
  return { doc, graph, frames, errors, ok: !errors.some((e) => e.severity === 'error') };
}
