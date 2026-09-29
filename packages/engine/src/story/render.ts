import type { Plan, PlanRenderer } from './types';

export interface DebugRenderer extends PlanRenderer {
  readonly history: string[];
}

/** P0 冒烟渲染器：记录进入的状态序列并按 plan.totalMs 消耗时间（无 DOM） */
export function createDebugRenderer(): DebugRenderer {
  const history: string[] = [];
  return {
    history,
    mount() { /* P0 无宿主 */ },
    async applyPlan(plan: Plan): Promise<void> {
      history.push(plan.to);
      if (plan.totalMs > 0) await new Promise((r) => setTimeout(r, plan.totalMs));
    },
    dispose() { /* noop */ },
  };
}
