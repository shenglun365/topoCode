/**
 * 场景渲染器：包装 v3 SvgRenderer —— Plan payload 直通 applyDiff，
 * 复用其全部已验证机制（双层鬼影/wrapper 补间/textCross）。
 * v2：ambient/补丁/事件委托通道已随逻辑层移除；表达全部来自源文本结构 + diff 过渡。
 */

import type { Renderer } from '../core/types';
import { createSvgRenderer } from '../render/svg/svg-renderer';
import type { Plan } from './types';
import type { ScenePlanPayload } from './plan';

export interface SceneRendererOptions {
  speed?: number;
}

export interface SceneRenderer {
  inner: Renderer;
  mount(host: Element): void;
  applyPlan(plan: Plan): Promise<void>;
  /** 静态刷新当前状态（relayout 后免动画重绘） */
  applySnapshot(state: import('./scene').SceneState): void;
  setSpeed(multiplier: number): void;
  dispose(): void;
}

export function createSceneRenderer(o: SceneRendererOptions = {}): SceneRenderer {
  const inner = createSvgRenderer();
  let curSpeed = o.speed ?? 1;

  return {
    inner,
    mount(h: Element): void {
      inner.mount(h);
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
    setSpeed(m: number): void { curSpeed = Math.max(0.05, m); },
    applySnapshot(state): void {
      inner.setFrame(state, { hidden: false });
    },
    dispose(): void {
      inner.dispose();
    },
  };
}
