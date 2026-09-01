import { makeButton, ensureToolbar } from './ui';
import type { DiagramPlugin, PluginContext, SharedInteractionState } from './types';

export interface ZoomPanApi {
  zoomToFit(): void;
  resetView(): void;
  zoomIn(): void;
  zoomOut(): void;
}

export interface ZoomPanOptions {
  /** 自动适配(fit/reset)的最小缩放下限(默认 0.1)；避免宽/大图被整体适配缩到不可读。手动缩放仍受 MIN_SCALE 约束。 */
  minFitScale?: number;
}

interface ViewTransform {
  x: number;
  y: number;
  s: number;
}

const MIN_SCALE = 0.1;
const MAX_SCALE = 8;
const ZOOM_STEP = 1.25;

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

function parseViewBox(svg: SVGSVGElement): { w: number; h: number } | null {
  const raw = svg.getAttribute('viewBox');
  if (!raw) return null;
  const parts = raw.split(/[\s,]+/).map(Number);
  if (parts.length !== 4) return null;
  const [, , w, h] = parts;
  return w > 0 && h > 0 ? { w, h } : null;
}

/**
 * Wheel zoom (cursor anchored), drag pan, double-click zoom, fit/reset.
 * Implemented as a CSS transform on the <svg> element itself so engine DOM stays untouched.
 */
export function createZoomPanPlugin(opts?: ZoomPanOptions): DiagramPlugin & { api: ZoomPanApi } {
  const minFitScale = opts?.minFitScale ?? MIN_SCALE;
  let container: HTMLElement | null = null;
  let svg: SVGSVGElement | null = null;
  let shared: SharedInteractionState | null = null;
  let t: ViewTransform = { x: 0, y: 0, s: 1 };
  let disposed = false;
  let drag: { startX: number; startY: number; active: boolean } = { startX: 0, startY: 0, active: false };

  const cleanupFns: (() => void)[] = [];

  const watch = <E extends Event>(
    target: EventTarget,
    type: string,
    fn: (e: E) => void,
    opts?: AddEventListenerOptions,
  ) => {
    const listener = fn as unknown as EventListener;
    target.addEventListener(type, listener, opts);
    cleanupFns.push(() => target.removeEventListener(type, listener, opts));
  };

  const apply = () => {
    if (svg) {
      svg.style.transformOrigin = '0 0';
      svg.style.transform = `translate(${t.x}px, ${t.y}px) scale(${t.s})`;
    }
  };

  const naturalSize = (): { w: number; h: number } | null => {
    if (!svg) return null;
    return parseViewBox(svg) ?? (svg.clientWidth ? { w: svg.clientWidth, h: svg.clientHeight } : null);
  };

  const fit = () => {
    if (!svg || !container) return;
    const size = naturalSize();
    const cw = container.clientWidth;
    const ch = container.clientHeight;
    if (!size || !cw || !ch) return;
    // 宽图(宽高比明显大于容器)→ 按宽度适配(水平居中、顶对齐、垂直可平移)，
    // 避免整体适配把宽图缩到不可读；下限用 minFitScale(手动缩放仍受 MIN_SCALE 约束)。
    const wide = size.w / size.h > (cw / ch) * 1.25;
    let s: number;
    let x: number;
    let y: number;
    if (wide) {
      s = clamp((cw / size.w) * 0.96, minFitScale, MAX_SCALE);
      x = (cw - size.w * s) / 2;
      y = 0;
    } else {
      s = clamp(Math.min(cw / size.w, ch / size.h) * 0.96, minFitScale, MAX_SCALE);
      x = (cw - size.w * s) / 2;
      y = (ch - size.h * s) / 2;
    }
    t = { s, x, y };
    apply();
  };

  const zoomAt = (cx: number, cy: number, factor: number) => {
    const s2 = clamp(t.s * factor, MIN_SCALE, MAX_SCALE);
    const k = s2 / t.s;
    t = { s: s2, x: cx - (cx - t.x) * k, y: cy - (cy - t.y) * k };
    apply();
  };

  const zoomCenter = (factor: number) => {
    if (!container) return;
    zoomAt(container.clientWidth / 2, container.clientHeight / 2, factor);
  };

  const onWheel = (e: WheelEvent) => {
    if (!container) return;
    e.preventDefault();
    const rect = container.getBoundingClientRect();
    zoomAt(e.clientX - rect.left, e.clientY - rect.top, e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP);
  };

  const onDown = (e: MouseEvent) => {
    if (e.button !== 0) return;
    drag = { startX: e.clientX - t.x, startY: e.clientY - t.y, active: true };
    if (shared) shared.dragDistance = 0;
    if (container) container.style.cursor = 'grabbing';
  };

  const onMove = (e: MouseEvent) => {
    if (!drag.active) return;
    const nx = e.clientX - drag.startX;
    const ny = e.clientY - drag.startY;
    if (shared) shared.dragDistance += Math.abs(nx - t.x) + Math.abs(ny - t.y);
    t.x = nx;
    t.y = ny;
    apply();
  };

  const onUp = () => {
    drag.active = false;
    if (container) container.style.cursor = 'grab';
  };

  const onDblClick = (e: MouseEvent) => {
    if (!container) return;
    const rect = container.getBoundingClientRect();
    zoomAt(e.clientX - rect.left, e.clientY - rect.top, 1.5);
  };

  const api: ZoomPanApi = {
    zoomToFit: fit,
    resetView: fit,
    zoomIn: () => zoomCenter(ZOOM_STEP),
    zoomOut: () => zoomCenter(1 / ZOOM_STEP),
  };

  return {
    name: 'zoom-pan',
    api,
    onAfterRender(ctx: PluginContext) {
      if (disposed) return;
      container = ctx.container;
      svg = ctx.svg;
      shared = ctx.shared;
      if (!svg) return;

      container.style.overflow = 'hidden';
      container.style.cursor = 'grab';
      t = { x: 0, y: 0, s: 1 };
      apply();

      watch(svg, 'wheel', onWheel, { passive: false });
      watch(container, 'mousedown', onDown);
      watch(window, 'mousemove', onMove);
      watch(window, 'mouseup', onUp);
      watch(svg, 'dblclick', onDblClick);

      const bar = ensureToolbar(container);
      bar.appendChild(makeButton('−', 'Zoom out', () => api.zoomOut()));
      bar.appendChild(makeButton('+', 'Zoom in', () => api.zoomIn()));
      bar.appendChild(makeButton('⤢', 'Fit to screen', () => api.zoomToFit()));
      bar.appendChild(makeButton('⟲', 'Reset view', () => api.resetView()));

      requestAnimationFrame(fit);
    },
    onBeforeDestroy() {
      disposed = true;
      for (const un of cleanupFns.splice(0)) un();
    },
  };
}
