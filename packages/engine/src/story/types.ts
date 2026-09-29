/**
 * 叙事引擎 —— 纯帧序列模型（v2）
 *
 * StateGraph  帧序列线性图（状态=静态结构帧；边=帧间过渡编排）。环/分支/事件为 v1 已移除分叉。
 * SceneState  场景快照（keyed elements + 语义注解），编译自 DSL/svg/ops 帧源。
 * Plan        编排产物：(from,to)×Choreography 编译出的元素动作表 + 时间轨道。
 * Scheduler   运行时：EXECUTING(plan 过渡) → HOLD(驻留/手动) → 下一帧；pause/resume/next/goto/replay。
 * Store       黑板 + 位置两层（committed/draft）。
 */

import type { FrameOp, FrameOpts } from '../core/types';

/* ============ SceneState ============ */

/** 叙事状态定义：帧源三通道（source 后端渲染 / svg 离线 / script 增量 ops） */
export interface StoryStateDef {
  id: string;
  /** 模式A：DSL 文本（配后端渲染） */
  source?: string;
  /** 离线通道：完整 SVG */
  svg?: string;
  /** 模式B：相对上一状态的 ops */
  script?: FrameOp[];
  layout?: 'engine' | 'keep';
  /** 语义注解（编排/渲染可消费） */
  annotations?: Record<string, string>;
  /** HOLD 驻留毫秒（到点自动进下一帧；≤0/缺省 = 等待手动 next） */
  dwellMs?: number;
  /** false = 强制手动驻留（覆盖 dwell） */
  auto?: boolean;
}

/* ============ StateGraph ============ */

/** 边编排：FrameOpts 全量（order/stagger/transitions/durationMs/align） */
export type EdgeChoreography = FrameOpts;

export interface StoryEdge {
  from: string;
  to: string;
  label?: string;
  choreography?: EdgeChoreography;
}

/** 终止伪目标（'$END'） */
export const END_STATE = '$END';

export interface StateGraphSpec {
  id?: string;
  entry: string;
  states: StoryStateDef[];
  edges: StoryEdge[];
  vars?: Record<string, unknown>;
}

export function validateGraph(g: StateGraphSpec): string[] {
  const errs: string[] = [];
  const ids = new Set(g.states.map((s) => s.id));
  if (!ids.has(g.entry)) errs.push(`entry "${g.entry}" 不在 states 中`);
  for (const e of g.edges) {
    if (!ids.has(e.from)) errs.push(`edge from "${e.from}" 不存在`);
    if (e.to !== END_STATE && !ids.has(e.to)) errs.push(`edge to "${e.to}" 不存在`);
  }
  for (const s of g.states) {
    const outs = g.edges.filter((e) => e.from === s.id);
    if (outs.length > 1) errs.push(`状态 "${s.id}" 有 ${outs.length} 条出边（纯帧序列 ≤1）`);
  }
  return errs;
}

/* ============ Plan ============ */

export type PlanAction =
  | 'enter' | 'exit' | 'move' | 'update' | 'morph' | 'text' | 'style';

export interface PlanStep {
  key: string;
  action: PlanAction;
  delayMs: number;
  durationMs: number;
  easing?: string;
  payload?: unknown;
}

export interface Plan {
  from: string | null;
  to: string;
  steps: PlanStep[];
  totalMs: number;
  /** 编译期产物（ScenePlanPayload：diff/timeline/场景引用）；渲染层按能力消费 */
  payload?: unknown;
}

export interface CompileContext {
  vars: Record<string, unknown>;
}

export interface PlanCompiler {
  compile(from: StoryStateDef | null, to: StoryStateDef, edge: StoryEdge, ctx: CompileContext): Promise<Plan>;
}

/* ============ Renderer ============ */

export interface PlanRenderer {
  mount(host: Element): void;
  /** 执行一个 Plan（resolve = 播完） */
  applyPlan(plan: Plan): Promise<void>;
  dispose(): void;
}

/* ============ 运行时快照 ============ */

export type SchedulerPhase = 'idle' | 'executing' | 'hold' | 'paused' | 'ended' | 'stopped';

export interface SchedulerSnapshot {
  nodeId: string | null;
  phase: SchedulerPhase;
  /** 已执行的转移数（环路保护用） */
  hops: number;
}
