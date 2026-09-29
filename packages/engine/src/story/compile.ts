import type { Plan, PlanCompiler } from './types';

/**
 * P0 占位编译器：整态作为一个 enter 步骤，时长取边编排 durationMs（默认 fallback）。
 * P1 替换为真实管线：capture/SceneState → keydiff → 位置模型（锁定+overrides）→ 元素级 Plan。
 */
export function placeholderCompiler(fallbackMs = 30): PlanCompiler {
  return {
    async compile(from, to, edge): Promise<Plan> {
      const dur = edge.choreography?.durationMs ?? fallbackMs;
      return {
        from: from?.id ?? null,
        to: to.id,
        steps: [{ key: '@state', action: 'enter', delayMs: 0, durationMs: dur }],
        totalMs: dur,
      };
    },
  };
}
