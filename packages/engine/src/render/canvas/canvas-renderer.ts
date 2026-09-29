import type { ApplyContext, FrameDiff, FrameSource, Renderer, TimelineSpec } from '../../core/types';
import type { Ctx2D } from './draw';
import { drawElement, drawScene } from './draw';

export interface CanvasRendererOptions {
  /** 注入 2D 上下文（测试替身通道）；缺省 canvas.getContext('2d') */
  contextFactory?: (canvas: HTMLCanvasElement) => Ctx2D | null;
  dpr?: number;
  /** 无尺寸信息时的兜底画布尺寸 */
  fallbackSize?: { width: number; height: number };
}

interface Layer {
  canvas: HTMLCanvasElement;
  ctx: Ctx2D;
}

const ease = (t: number): number => (t < 0.5 ? 2 * t * t : 1 - ((-2 * t + 2) ** 2) / 2);

/**
 * Canvas 渲染器（docs/engine-design.md §9.2，M2）：
 * 静态基层（committed scene，帧提交时重放一次）+ 动态上层（rAF 只画过渡中元素）。
 * stay 元素零重绘由架构保证；与 SvgRenderer 共享同一 SceneSpec IR。
 */
export function createCanvasRenderer(o: CanvasRendererOptions = {}): Renderer {
  let host: Element | null = null;
  let base: Layer | null = null;
  let fx: Layer | null = null;
  let current: FrameSource | null = null;
  let hiddenStatic = false;
  let disposed = false;
  const dpr = o.dpr ?? (globalThis.devicePixelRatio ?? 1);
  const factory = o.contextFactory ?? ((c: HTMLCanvasElement) => c.getContext('2d') as Ctx2D | null);

  const ensureLayers = (): void => {
    if (base && fx) return;
    const doc = host?.ownerDocument ?? document;
    const mk = (z: number): Layer => {
      const canvas = doc.createElement('canvas') as HTMLCanvasElement;
      canvas.style.position = 'absolute';
      canvas.style.left = '0';
      canvas.style.top = '0';
      const ctx = factory(canvas);
      if (!ctx) throw new Error('[ta] canvas 2d context unavailable');
      (canvas as HTMLCanvasElement & { __z: number }).__z = z;
      return { canvas, ctx };
    };
    base = mk(0);
    fx = mk(2);
    fx.canvas.style.zIndex = '2';
    base.canvas.style.zIndex = '1';
    host?.appendChild(base.canvas);
    host?.appendChild(fx.canvas);
  };

  const sizeTo = (w: number, h: number): void => {
    if (!base || !fx) return;
    const W = Math.max(1, Math.ceil(w));
    const H = Math.max(1, Math.ceil(h));
    for (const l of [base, fx]) {
      l.canvas.width = W * dpr;
      l.canvas.height = H * dpr;
      l.canvas.style.width = `${W}px`;
      l.canvas.style.height = `${H}px`;
      l.ctx.clearRect(0, 0, l.canvas.width, l.canvas.height);
    }
  };

  const commit = (src: FrameSource, excludeKeys?: Set<string>): void => {
    ensureLayers();
    const fb = o.fallbackSize ?? { width: 800, height: 600 };
    sizeTo(src.spec.width || fb.width, src.spec.height || fb.height);
    if (hiddenStatic) return;
    const b = base as Layer;
    b.ctx.save();
    b.ctx.scale(dpr, dpr);
    drawScene(b.ctx, src.spec, { excludeKeys });
    b.ctx.restore();
  };

  const clearFxLayer = (W: number, H: number): void => {
    const f = fx as Layer;
    f.ctx.clearRect(0, 0, W, H);
  };

  const raf = (cb: () => void): void => {
    const w = host?.ownerDocument?.defaultView as (Window & { requestAnimationFrame?: (cb: () => void) => number }) | null;
    if (w?.requestAnimationFrame) w.requestAnimationFrame(cb);
    else setTimeout(cb, 16);
  };

  const renderer: Renderer = {
    mount(h: Element): void {
      host = h;
      const el = h as HTMLElement;
      if (el.style && !el.style.position) el.style.position = 'relative';
    },

    setFrame(src: FrameSource, fo?: { hidden?: boolean }): void {
      if (disposed) return;
      hiddenStatic = !!fo?.hidden;
      commit(src);
      current = src;
    },

    async applyDiff(_diff: FrameDiff, timeline: TimelineSpec, ctx: ApplyContext): Promise<void> {
      if (disposed) return;
      const to = ctx.to;
      const scale = 1 / Math.max(0.05, ctx.speed ?? 1);
      if (!ctx.animate) {
        hiddenStatic = false;
        commit(to);
        current = to;
        return;
      }
      const animKeys = new Set<string>();
      for (const it of timeline.items) animKeys.add(it.key);
      // 基层：新场景全量，减去过渡中元素（一次性重放）
      commit(to, animKeys);
      current = to;

      const fromSpec = ctx.from?.spec;

      await new Promise<void>((resolve) => {
        const start = Date.now();
        const totalMs = timeline.totalMs * scale + 80;
        const tick = (): void => {
          if (disposed) return resolve();
          const now = Date.now() - start;
          const f = fx as Layer;
          clearFxLayer(f.canvas.width, f.canvas.height);
          f.ctx.save();
          f.ctx.scale(dpr, dpr);
          for (const it of timeline.items) {
            const delay = it.delayMs * scale;
            const dur = Math.max(1, it.transition.durationMs * scale);
            if (now < delay) continue;
            const p = ease(Math.min(1, (now - delay) / dur));
            if (it.cls === 'exit') {
              const prevEl = fromSpec?.elements.find((e) => e.key === it.key) ?? it.el;
              drawElement(f.ctx, prevEl, { alpha: 1 - p });
            } else if (it.cls === 'enter') {
              if (it.transition.type === 'drawIn') drawElement(f.ctx, it.el, { drawT: p });
              else if (it.transition.type === 'scale') drawElement(f.ctx, it.el, { alpha: Math.min(1, p * 2), scale: 0.85 + 0.15 * p });
              else drawElement(f.ctx, it.el, { alpha: p });
            } else if (it.cls === 'move' && it.prev) {
              const k = 1 - p;
              drawElement(f.ctx, it.el, { dx: (it.prev.bbox.x - it.el.bbox.x) * k, dy: (it.prev.bbox.y - it.el.bbox.y) * k });
            } else if (it.cls === 'update' && it.prev && it.transition.type === 'morph') {
              drawElement(f.ctx, it.el, { morphFrom: it.prev.paths.map((ps) => ps.d), morphT: p });
            } else if (it.cls === 'text') {
              const prevEl = it.prev ?? (fromSpec?.elements.find((e) => e.key === it.key));
              if (prevEl) drawElement(f.ctx, prevEl, { alpha: 1 - p });
              drawElement(f.ctx, it.el, { alpha: p });
            } else {
              drawElement(f.ctx, it.el, {});
            }
          }
          f.ctx.restore();
          if (now >= totalMs) return resolve();
          raf(tick);
        };
        tick();
      });
      if (disposed) return;
      // 完成：把过渡元素并入基层，清空动态层
      commit(to);
    },

    snapshot(): FrameSource | null {
      return current;
    },

    dispose(): void {
      disposed = true;
      for (const l of [base, fx]) l?.canvas.parentNode?.removeChild(l.canvas);
      base = null;
      fx = null;
      current = null;
      host = null;
    },
  };
  return renderer;
}
