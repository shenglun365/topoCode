/**
 * 帧序列便捷入口（topoOne 集成批 1.1/1.4）：跳过 TopoScript 封套仪式，直接吃帧数组。
 *
 * 消费方（如 architect「演化播放」）持有 源文数组（每帧 = mermaid/plantuml/dot 全文）
 * 或 已渲染 SVG 数组（服务端渲染池产物）→ 产出 StateGraphSpec，交 createStoryEngine 播放。
 * 驻留/过渡选项语义与 @options 完全一致（step/auto/enter/exit/duration/order/stagger/align）。
 */

import type { StateGraphSpec, StoryEdge, StoryStateDef } from '../story/types';
import { validateGraph } from '../story/types';
import { buildTopoStory, framesToGraph, type TopoBuildResult } from './build';
import type { OptMap } from './build';
import type { TopoDiagnostic } from './types';
import { emptyDocument } from './types';

export interface StoryInputOptions {
  /** 结构后端 id（mermaid|dot|plantuml|…），默认 mermaid；frames 形态忽略 */
  backend?: string;
  /** 全局默认帧选项（同 @options） */
  options?: OptMap;
  /** 帧 id（缺省 f1..fN，重复自动加后缀） */
  frameIds?: string[];
  /** 帧级选项覆写（与数组按下标对齐，可稀疏） */
  frameOptions?: (OptMap | undefined)[];
  /** 语义注解（随帧入 state.annotations，渲染/编排可消费；如 commit 信息） */
  annotations?: (Record<string, string> | undefined)[];
}

export interface StoryFramesResult {
  graph: StateGraphSpec;
  errors: TopoDiagnostic[];
  ok: boolean;
  frameIds: string[];
}

function uniqueId(base: string, taken: Set<string>): string {
  let id = base;
  let n = 2;
  while (taken.has(id)) id = `${base}-${n++}`;
  return id;
}

/** 源文数组 → 线性图（TopoScript 同构，返回含 doc 便于 receipt/serialize） */
export function storyFromSources(sources: string[], opts: StoryInputOptions = {}): TopoBuildResult {
  const doc = emptyDocument();
  if (opts.backend) doc.backend = opts.backend;
  doc.options = { ...(opts.options ?? {}) };
  const taken = new Set<string>();
  sources.forEach((src, i) => {
    const id = uniqueId(opts.frameIds?.[i] ?? `f${i + 1}`, taken);
    taken.add(id);
    doc.frames.push({
      id, source: src, frameLine: 0, sourceLine: 0,
      options: opts.frameOptions?.[i] ?? {},
    });
  });
  const out = buildTopoStory(doc);
  if (opts.annotations?.length) {
    out.graph.states.forEach((s, i) => {
      const a = opts.annotations?.[i];
      if (a) { const def: StoryStateDef = { ...s, annotations: a }; out.graph.states[i] = def; }
    });
  }
  return out;
}

/** 已渲染 SVG 数组 → 线性图（服务端渲染形态：animation 只做 capture→diff→播放） */
export function storyFromFrames(svgFrames: string[], opts: StoryInputOptions = {}): StoryFramesResult {
  const errors: TopoDiagnostic[] = [];
  const err = (line: number, message: string): void => { errors.push({ line, message, severity: 'error' }); };
  const taken = new Set<string>();
  const frameIds: string[] = [];
  const frames = svgFrames.map((svg, i) => {
    const id = uniqueId(opts.frameIds?.[i] ?? `f${i + 1}`, taken);
    taken.add(id);
    frameIds.push(id);
    if (!svg.includes('<svg')) err(i, `帧 ${id} 不是 SVG 文本`);
    return { id, source: '', svg, options: opts.frameOptions?.[i] ?? {} };
  });
  const { states, edges } = framesToGraph(frames, opts.options ?? {}, (line, message, code, fixes, frame) => {
    errors.push({ line, message, severity: 'error', ...(code ? { code } : {}), ...(fixes?.length ? { supportedFixes: fixes } : {}), ...(frame ? { frame } : {}) } as TopoDiagnostic);
  });
  // framesToGraph 把 source 写死了 ''：此处以 svg 覆盖 + annotations 注入
  const statesSvg: StoryStateDef[] = states.map((s, i) => ({
    ...s, source: undefined, svg: frames[i]!.svg,
    ...(opts.annotations?.[i] ? { annotations: opts.annotations[i] } : {}),
  }));
  const outEdges: StoryEdge[] = edges;
  if (frames.length === 0) err(1, '无可播放帧');
  const graph: StateGraphSpec = { entry: frameIds[0] ?? '', states: statesSvg, edges: outEdges, vars: {} };
  if (frames.length > 0) {
    for (const m of validateGraph(graph)) errors.push({ line: 0, message: m, severity: 'error', code: 'build/graph-invalid' });
  }
  const ok = errors.every((e) => e.severity !== 'error');
  return { graph, errors, ok, frameIds };
}
