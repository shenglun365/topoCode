import type { PathCommand, SceneElement, SceneSpec, StyleMap } from '../../core/types';
import { commandsToD, lerpCommands } from '../../core/path';

/** 最小 2D 上下文契约（CanvasRenderingContext2D 与测试替身均满足） */
export interface Ctx2D {
  globalAlpha: number;
  fillStyle: string;
  strokeStyle: string;
  lineWidth: number;
  font: string;
  textAlign: 'left' | 'center' | 'right' | 'start' | 'end';
  textBaseline: string;
  lineDashOffset: number;
  save(): void;
  restore(): void;
  translate(x: number, y: number): void;
  beginPath(): void;
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
  bezierCurveTo(x1: number, y1: number, x2: number, y2: number, x: number, y: number): void;
  closePath(): void;
  fill(): void;
  stroke(): void;
  setLineDash(segments: number[]): void;
  clearRect(x: number, y: number, w: number, h: number): void;
  fillText(text: string, x: number, y: number): void;
  scale(x: number, y: number): void;
}

/** SVG 椭圆弧（endpoint 参数化）→ 贝塞尔段近似（W3C F.6） */
function traceArc(
  ctx: Ctx2D, x0: number, y0: number,
  rxIn: number, ryIn: number, rotDeg: number, fa: number, fs: number, x1: number, y1: number,
): void {
  if (x0 === x1 && y0 === y1) return;
  let rx = Math.abs(rxIn) || 0.01;
  let ry = Math.abs(ryIn) || 0.01;
  const phi = (rotDeg * Math.PI) / 180;
  const cos = Math.cos(phi);
  const sin = Math.sin(phi);
  const dx = (x0 - x1) / 2;
  const dy = (y0 - y1) / 2;
  const x1p = cos * dx + sin * dy;
  const y1p = -sin * dx + cos * dy;
  let rx2 = rx * rx;
  let ry2 = ry * ry;
  const lambda = (x1p * x1p) / rx2 + (y1p * y1p) / ry2;
  if (lambda > 1) {
    const s = Math.sqrt(lambda);
    rx *= s; ry *= s; rx2 = rx * rx; ry2 = ry * ry;
  }
  const sign = fa !== fs ? 1 : -1;
  const num = rx2 * ry2 - rx2 * y1p * y1p - ry2 * x1p * x1p;
  const den = rx2 * y1p * y1p + ry2 * x1p * x1p;
  const co = sign * Math.sqrt(Math.max(0, num / den || 0));
  const cxp = (co * rx * y1p) / ry;
  const cyp = (-co * ry * x1p) / rx;
  const cx = cos * cxp - sin * cyp + (x0 + x1) / 2;
  const cy = sin * cxp + cos * cyp + (y0 + y1) / 2;
  const u = (ux: number, uy: number) => Math.atan2(uy, ux);
  const start = u((x1p - cxp) / rx, (y1p - cyp) / ry);
  let delta = u((-x1p - cxp) / rx, (-y1p - cyp) / ry) - start;
  if (!fs && delta > 0) delta -= 2 * Math.PI;
  if (fs && delta < 0) delta += 2 * Math.PI;
  const segs = Math.max(1, Math.ceil(Math.abs(delta) / (Math.PI / 2 + 1e-9)));
  const d = delta / segs;
  const at = (a: number) => ({
    x: cx + rx * Math.cos(a) * cos - ry * Math.sin(a) * sin,
    y: cy + rx * Math.cos(a) * sin + ry * Math.sin(a) * cos,
  });
  const deriv = (a: number) => ({
    x: -rx * Math.sin(a) * cos - ry * Math.cos(a) * sin,
    y: -rx * Math.sin(a) * sin + ry * Math.cos(a) * cos,
  });
  let a0 = start;
  for (let i = 0; i < segs; i++) {
    const a1 = a0 + d;
    const p0 = at(a0);
    const p1 = at(a1);
    const m0 = deriv(a0);
    const m1 = deriv(a1);
    const third = d / 3;
    ctx.bezierCurveTo(p0.x + m0.x * third, p0.y + m0.y * third, p1.x - m1.x * third, p1.y - m1.y * third, p1.x, p1.y);
    a0 = a1;
  }
}

export function traceCommands(ctx: Ctx2D, cmds: PathCommand[]): void {
  let x = 0;
  let y = 0;
  let sx = 0;
  let sy = 0;
  for (const c of cmds) {
    switch (c.c) {
      case 'M': ctx.moveTo(c.x, c.y); x = c.x; y = c.y; sx = x; sy = y; break;
      case 'L': ctx.lineTo(c.x, c.y); x = c.x; y = c.y; break;
      case 'C':
        ctx.bezierCurveTo(c.x1, c.y1, c.x2, c.y2, c.x, c.y);
        x = c.x; y = c.y;
        break;
      case 'Q': {
        const c1x = x + (2 / 3) * (c.x1 - x);
        const c1y = y + (2 / 3) * (c.y1 - y);
        const c2x = c.x + (2 / 3) * (c.x1 - c.x);
        const c2y = c.y + (2 / 3) * (c.y1 - c.y);
        ctx.bezierCurveTo(c1x, c1y, c2x, c2y, c.x, c.y);
        x = c.x; y = c.y;
        break;
      }
      case 'A':
        traceArc(ctx, x, y, c.rx, c.ry, c.rot, c.laf, c.sf, c.x, c.y);
        x = c.x; y = c.y;
        break;
      case 'Z': ctx.closePath(); x = sx; y = sy; break;
    }
  }
}

function num(s: StyleMap, k: string, d: number): number {
  const v = parseFloat(String(s[k] ?? ''));
  return Number.isNaN(v) ? d : v;
}

/** 路径近似周长（drawIn 的 dash 长度） */
export function pathLength(cmds: PathCommand[]): number {
  let len = 0;
  let x = 0;
  let y = 0;
  for (const c of cmds) {
    if (c.c === 'M' || c.c === 'L' || c.c === 'C' || c.c === 'Q' || c.c === 'A') {
      const ex = 'x' in c ? c.x : x;
      const ey = 'y' in c ? c.y : y;
      len += Math.hypot(ex - x, ey - y);
      x = ex; y = ey;
    }
  }
  return Math.max(2, len);
}

export interface DrawOpts {
  alpha?: number;
  dx?: number;
  dy?: number;
  /** 围绕 bbox 中心的缩放（enter scale 过渡） */
  scale?: number;
  /** drawIn 进度：0=不可见 1=完整；以 dash 偏移表达 */
  drawT?: number;
  /** morph 进度插值（与 base 命令同构） */
  morphFrom?: PathCommand[][];
  morphT?: number;
}

const FALLBACK_FILL: StyleMap = { fill: '#000000', stroke: 'none' };

export function drawElement(ctx: Ctx2D, el: SceneElement, o: DrawOpts = {}): void {
  const alpha = o.alpha ?? 1;
  if (alpha <= 0.001) return;
  ctx.save();
  ctx.globalAlpha = alpha * num(el.style, 'opacity', 1);
  if (o.scale !== undefined && o.scale !== 1) {
    const cx = el.bbox.x + el.bbox.width / 2;
    const cy = el.bbox.y + el.bbox.height / 2;
    ctx.translate(cx, cy);
    ctx.scale(o.scale, o.scale);
    ctx.translate(-cx, -cy);
  }
  if (o.dx || o.dy) ctx.translate(o.dx ?? 0, o.dy ?? 0);
  el.paths.forEach((p, i) => {
    const st: StyleMap = { ...FALLBACK_FILL, ...el.style, ...p.style };
    const cmds = o.morphFrom && o.morphFrom[i] && o.morphT !== undefined
      ? lerpCommands(o.morphFrom[i], p.d, o.morphT)
      : p.d;
    ctx.beginPath();
    traceCommands(ctx, cmds);
    if (o.drawT !== undefined && o.drawT < 1) {
      const len = pathLength(cmds);
      ctx.setLineDash([len]);
      ctx.lineDashOffset = len * (1 - o.drawT);
    } else {
      ctx.setLineDash([]);
    }
    const fill = st['fill'] ?? 'none';
    if (fill !== 'none') {
      ctx.fillStyle = String(fill);
      ctx.fill();
    }
    const stroke = st['stroke'] ?? 'none';
    if (stroke !== 'none') {
      ctx.strokeStyle = String(stroke);
      ctx.lineWidth = num(st, 'stroke-width', 1);
      ctx.stroke();
    }
  });
  ctx.setLineDash([]);
  for (const t of el.text) {
    const size = num(t.style, 'font-size', 14);
    ctx.font = `${size}px ${t.style['font-family'] ?? 'sans-serif'}`;
    ctx.textAlign = t.anchor === 'middle' ? 'center' : t.anchor === 'end' ? 'right' : 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = String(t.style['fill'] ?? el.style['fill'] ?? '#000000');
    ctx.fillText(t.content, t.x, t.y);
  }
  ctx.restore();
}

export function drawScene(
  ctx: Ctx2D,
  spec: SceneSpec,
  opts: { excludeKeys?: Set<string>; perElement?: (el: SceneElement) => DrawOpts } = {},
): void {
  for (const el of spec.elements) {
    if (opts.excludeKeys?.has(el.key)) continue;
    drawElement(ctx, el, opts.perElement?.(el) ?? {});
  }
}

/** 与 drawElement 平行：仅用于测试断言场景几何可序列化 */
export function sceneToDStrings(spec: SceneSpec): string[] {
  const out: string[] = [];
  for (const el of spec.elements) for (const p of el.paths) out.push(commandsToD(p.d));
  return out;
}
