/** Canvas 场景渲染器（story 门面 → v3 CanvasRenderer 直通，payload 适配） */

import type { Renderer } from '../core/types';
import { createCanvasRenderer, type CanvasRendererOptions } from '../render/canvas/canvas-renderer';
import type { Plan, PlanRenderer } from './types';
import type { ScenePlanPayload } from './plan';
import type { SceneState } from './scene';

export interface CanvasSceneRenderer extends PlanRenderer {
  inner: Renderer;
  applySnapshot(state: SceneState): void;
  setSpeed(multiplier: number): void;
}

export function createCanvasSceneRenderer(opts: CanvasRendererOptions & { speed?: number } = {}): CanvasSceneRenderer {
  const inner = createCanvasRenderer(opts);
  let curSpeed = opts.speed ?? 1;
  return {
    inner,
    mount(host: Element): void {
      inner.mount(host);
    },
    async applyPlan(plan: Plan): Promise<void> {
      const p = plan.payload as ScenePlanPayload | undefined;
      if (!p) {
        if (plan.totalMs > 0) await new Promise((r) => setTimeout(r, plan.totalMs));
        return;
      }
      await inner.applyDiff(p.diff, p.timeline, {
        from: p.from ?? undefined, to: p.to, animate: true, mode: 'transition', speed: curSpeed,
      });
    },
    applySnapshot(state): void {
      inner.setFrame(state, { hidden: false });
    },
    setSpeed(m: number): void { curSpeed = Math.max(0.05, m); },
    dispose(): void {
      inner.dispose();
    },
  };
}
