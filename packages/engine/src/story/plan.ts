/**
 * Plan 编译器（§19.1 原语③）：(fromScene,toScene) × choreography → 元素级动作表。
 * P1 直接复用 v3 管线（keydiff + buildTimeline），diff 按 (from,to,chore) 惰性缓存；
 * relayout（committed 变更/锚配置）→ invalidate 全清。
 */

import type { FrameDiff, FrameOpts, SceneSpec, TimelineSpec } from '../core/types';
import { keydiff } from '../core/diff';
import { buildTimeline } from '../core/timeline';
import { emptySceneSpec } from '../core/frames';
import type {
  EdgeChoreography, Plan, PlanCompiler, PlanStep, StoryEdge, StoryStateDef,
} from './types';
import type { SceneState } from './scene';

export interface ScenePlanPayload {
  from: SceneState | null;
  to: SceneState;
  diff: FrameDiff;
  timeline: TimelineSpec;
}

export interface ScenePlanCompiler extends PlanCompiler {
  /** 布局/锚配置变更后清空边 diff 缓存 */
  invalidate(): void;
  stats(): { edges: number };
}

export function createSceneCompiler(deps: {
  /** 可同步（预编译完成）或返回惰性渲染 Promise（lazy 流式模式：自动插队等待该帧） */
  sceneOf(id: string): SceneState | Promise<SceneState>;
  stepMs?: number;
}): ScenePlanCompiler {
  const cache = new Map<string, Plan>();
  const compile = async (from: StoryStateDef | null, to: StoryStateDef, edge: StoryEdge): Promise<Plan> => {
    const choreKey = edge.choreography ? JSON.stringify(edge.choreography) : '';
    const key = `${from?.id ?? '@'}->${to.id}#${choreKey}`;
    const hit = cache.get(key);
    if (hit) return hit;
    const toScene = await deps.sceneOf(to.id);
    const fromScene = from ? await deps.sceneOf(from.id) : null;
    const prevSpec: SceneSpec = fromScene?.spec ?? emptySceneSpec();
    const diff = keydiff(prevSpec, toScene.spec);
    diff.from = from ? 1 : -1;
    diff.to = 2; // 图模式无线性序语义，占位（renderer 消费 ctx.from/to 对象）
    const chore = edge.choreography as EdgeChoreography | undefined;
    const frame: FrameOpts = chore ?? {};
    const timeline = buildTimeline(diff, { opts: frame }, deps.stepMs ?? 900);
    const steps: PlanStep[] = timeline.items.map((i) => ({
      key: i.key, action: i.cls, delayMs: i.delayMs, durationMs: i.transition.durationMs, easing: i.transition.easing,
    }));
    const plan: Plan = {
      from: from?.id ?? null,
      to: to.id,
      steps,
      totalMs: timeline.totalMs,
      payload: { from: fromScene, to: toScene, diff, timeline } satisfies ScenePlanPayload,
    };
    cache.set(key, plan);
    return plan;
  };
  return {
    compile: (from, to, edge) => compile(from, to, edge),
    invalidate: () => cache.clear(),
    stats: () => ({ edges: cache.size }),
  };
}
