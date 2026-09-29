import type { Box, FrameSource, PathCommand, SceneElement, SceneSpec } from './types';
import { unionBox } from './types';
import { shiftSpec, shiftSvg } from './align';
import { attachCommands, currentCommands, paramAlong, pathBbox, translateCommands, writeCommands, type Point } from './path';
import { estimateTextBox } from './text';

const SVG_NS = 'http://www.w3.org/2000/svg';
const PAD = 28;

/** 实体/整图平移量（统一坐标空间：锁定归一之后的帧坐标系） */
export interface EntityOffset {
  dx: number;
  dy: number;
}

/**
 * 手动位置覆盖（docs/engine-design.md §8.4 v2 位置模型）：
 * entities 按 baseKey 索引，同一实体 id 跨所有帧共享同一偏移；
 * global 为整图偏移（等价旧锚点切换）。原始位置永不清除（raw 幂等重建）。
 */
export interface LayoutOverrides {
  entities: Record<string, EntityOffset>;
  global: EntityOffset;
}

export interface LayoutInfo {
  /** 每帧的归一化平移（容器锚或首帧刚性锁定） */
  shifts: EntityOffset[];
  /** 统一画布半幅 */
  half: number;
  /** 实际采用的锚策略（调试/状态栏） */
  anchorKind: 'container' | 'median' | 'none';
  /** 容器锚命中的元素 baseKey */
  containerKey?: string;
}

export function baseKeyOf(key: string): string {
  const i = key.indexOf('#');
  return i > 0 ? key.slice(0, i) : key;
}

export function emptyLayout(): LayoutOverrides {
  return { entities: {}, global: { dx: 0, dy: 0 } };
}

function centerOf(el: SceneElement): { x: number; y: number } {
  return { x: el.bbox.x + el.bbox.width / 2, y: el.bbox.y + el.bbox.height / 2 };
}

/** 锁定基准点 = bbox 左上角：生长实体（生命线变高、框变宽）中心会漂移，角点稳定 */
function anchorPointOf(el: SceneElement): { x: number; y: number } {
  return { x: el.bbox.x, y: el.bbox.y };
}

const median = (a: number[]): number => {
  if (a.length === 0) return 0;
  const s = [...a].sort((x, y) => x - y);
  return s[Math.floor(s.length / 2)] as number;
};

/**
 * 帧级首帧刚性锁定：每帧整幅平移 = 共享实体「最早出现帧位置 − 当前位置」位移中位数。
 * 实体身份 = baseKey + 出现序对位（与 keydiff 基键配对一致）。
 * 效果：已出现实体默认停留在其首帧位置（抗后端刚性重排），新实体沿用本帧坐标。
 */
export function lockShifts(specs: SceneSpec[]): EntityOffset[] {
  const refs = new Map<string, SceneElement[]>();
  const out: EntityOffset[] = [];
  specs.forEach((spec, i) => {
    if (i === 0) {
      out.push({ dx: 0, dy: 0 });
    } else {
      const seen = new Map<string, number>();
      const dxs: number[] = [];
      const dys: number[] = [];
      for (const el of spec.elements) {
        const k = baseKeyOf(el.key);
        const idx = seen.get(k) ?? 0;
        seen.set(k, idx + 1);
        const ref = refs.get(k)?.[idx];
        if (!ref) continue;
        const rc = anchorPointOf(ref);
        const cc = anchorPointOf(el);
        dxs.push(rc.x - cc.x);
        dys.push(rc.y - cc.y);
      }
      out.push(dxs.length >= 2 ? { dx: median(dxs), dy: median(dys) } : { dx: 0, dy: 0 });
    }
    for (const el of spec.elements) {
      const k = baseKeyOf(el.key);
      const arr = refs.get(k);
      if (arr) arr.push(el);
      else refs.set(k, [el]);
    }
  });
  return out;
}

export function deepCloneSpec(spec: SceneSpec): SceneSpec {
  return JSON.parse(JSON.stringify(spec)) as SceneSpec;
}

/**
 * 容器锚（§19.3 内在锚①）：跨所有帧同 baseKey 存活的 node 元素中，
 * 面积 ≥ 内容并集 20% 的最大者（subgraph cluster / graph 盒）视为"画布本身"——
 * 每帧平移 = 容器₀.左上 − 容器ᵢ.左上。容器钉住 ⇒ 画布漂移全消且**真实位移如实保留**
 * （修复中位数估计被多数真实移动劫持的缺陷）；无合格容器 → null，退回中位数链。
 */
export function containerShifts(
  specs: SceneSpec[], refKey?: string,
): { shifts: EntityOffset[]; key: string } | null {
  if (specs.length < 2) return null; // 单帧无坐标系问题
  const nodeKeys = (s: SceneSpec): Set<string> =>
    new Set(s.elements.filter((e) => e.kind === 'node').map((e) => baseKeyOf(e.key)));
  let shared = nodeKeys(specs[0]!);
  for (const s of specs.slice(1)) {
    const ks = nodeKeys(s);
    shared = new Set([...shared].filter((k) => ks.has(k)));
  }
  if (shared.size === 0) return null;
  const of = (k: string): { pts: { x: number; y: number }[]; minArea: number } | null => {
    const pts: { x: number; y: number }[] = [];
    let minArea = Infinity;
    for (const s of specs) {
      const e = s.elements.find((x) => baseKeyOf(x.key) === k);
      if (!e) return null;
      pts.push({ x: e.bbox.x, y: e.bbox.y });
      minArea = Math.min(minArea, e.bbox.width * e.bbox.height);
    }
    return { pts, minArea };
  };
  let key: string | null = null;
  if (refKey && shared.has(refKey)) {
    key = refKey;
  } else {
    let best = 0;
    for (const k of shared) {
      const o = of(k);
      if (o && o.minArea > best) { best = o.minArea; key = k; }
    }
  }
  if (!key) return null;
  const found = of(key);
  if (!found) return null;
  if (!refKey) {
    // 面积门槛：容器须近似包住内容（≥并集 50%），否则只是普通元素
    const u = contentUnion(specs[0]!);
    if (found.minArea < u.w * u.h * 0.5) return null;
  }
  const [base] = found.pts;
  const shifts = found.pts.map((p) => {
    const dx = (base?.x ?? 0) - p.x, dy = (base?.y ?? 0) - p.y;
    return { dx: Math.abs(dx) < 0.5 ? 0 : dx, dy: Math.abs(dy) < 0.5 ? 0 : dy };
  });
  return { shifts, key };
}

function contentUnion(spec: SceneSpec): { w: number; h: number } {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const el of spec.elements) {
    x0 = Math.min(x0, el.bbox.x); y0 = Math.min(y0, el.bbox.y);
    x1 = Math.max(x1, el.bbox.x + el.bbox.width); y1 = Math.max(y1, el.bbox.y + el.bbox.height);
  }
  return { w: x1 - x0, h: y1 - y0 };
}

function shiftElement(el: SceneElement, dx: number, dy: number): void {
  el.bbox = { ...el.bbox, x: el.bbox.x + dx, y: el.bbox.y + dy };
  el.paths = el.paths.map((p) => ({ d: translateCommands(p.d, dx, dy), style: p.style }));
  for (const t of el.text) {
    t.x += dx; t.y += dy;
    const size = parseFloat(t.style['font-size'] ?? '14') || 14;
    t.box = estimateTextBox(t.content, t.x, t.y, t.anchor, size);
  }
}

/* ---------------- 边端点吸附（§19.3 D2/D3：两端钉节点、中段平滑过渡、线不缩不留缝） ---------------- */

const SHAPE_DOM_SEL = 'path, line, polyline, polygon, rect, circle, ellipse';
const NEAR_PAD = 16;

interface EdgeAttach {
  from: EntityOffset;
  to: EntityOffset;
}

interface ElemPlan {
  off: EntityOffset | null;
  attach: EdgeAttach | null;
}

const firstV = (d: PathCommand[]): Point | null => {
  for (const c of d) if ('x' in c && 'y' in c) return { x: c.x, y: c.y };
  return null;
};
const lastV = (d: PathCommand[]): Point | null => {
  for (let i = d.length - 1; i >= 0; i--) {
    const c = d[i] as PathCommand;
    if ('x' in c && 'y' in c) return { x: c.x, y: c.y };
  }
  return null;
};
const vertexCount = (d: PathCommand[]): number => d.filter((c) => c.c !== 'Z').length;
const blend = (a: EntityOffset, b: EntityOffset, w: number): EntityOffset =>
  ({ dx: a.dx * (1 - w) + b.dx * w, dy: a.dy * (1 - w) + b.dy * w });

/**
 * 边附着量判定：endpoints（mermaid/dot）优先；
 * 无 endpoints（plantuml 消息等）→ 几何邻近回退：主路径首/末点命中被拖 node bbox（+16px）。
 */
function resolveAttach(el: SceneElement, spec: SceneSpec, ov: LayoutOverrides): EdgeAttach | null {
  let f: EntityOffset | undefined;
  let t: EntityOffset | undefined;
  if (el.endpoints) {
    f = ov.entities[baseKeyOf(el.endpoints.from)];
    t = ov.entities[baseKeyOf(el.endpoints.to)];
  }
  if (!f && !t) {
    const main = mainPathOf(el);
    if (!main) return null;
    const s = firstV(main);
    const e = lastV(main);
    const hitNear = (p: Point | null, k: string): boolean => {
      if (!p) return false;
      return spec.elements.some((n) => n.kind !== 'edge' && baseKeyOf(n.key) === k
        && p.x >= n.bbox.x - NEAR_PAD && p.x <= n.bbox.x + n.bbox.width + NEAR_PAD
        && p.y >= n.bbox.y - NEAR_PAD && p.y <= n.bbox.y + n.bbox.height + NEAR_PAD);
    };
    for (const k of Object.keys(ov.entities)) {
      if (!f && hitNear(s, k)) f = ov.entities[k];
      if (!t && hitNear(e, k)) t = ov.entities[k];
    }
  }
  if (!f && !t) return null;
  return { from: f ?? { dx: 0, dy: 0 }, to: t ?? { dx: 0, dy: 0 } };
}

function mainPathOf(el: SceneElement): PathCommand[] | null {
  let best: PathCommand[] | null = null;
  for (const p of el.paths) {
    if (!best || span(p.d) > span(best)) best = p.d;
  }
  return best && vertexCount(best) >= 2 ? best : null;
}

/** 路径首末点距离：主"线"判定用（跨度最长者，箭头帽/装饰不会抢主） */
function span(d: PathCommand[]): number {
  const a = firstV(d);
  const b = lastV(d);
  return a && b ? Math.hypot(b.x - a.x, b.y - a.y) : 0;
}

/** IR 侧附着形变：主路径 attachCommands；辅助形状（箭头帽等）/标签按沿线位置整体平移 */
function applyAttachSpec(el: SceneElement, att: EdgeAttach): void {
  const main = mainPathOf(el);
  if (!main) return;
  const a = firstV(main) as Point;
  const b = lastV(main) as Point;
  const mainIdx = el.paths.findIndex((p) => p.d === main);
  el.paths = el.paths.map((ps, i) => ({
    d: i === mainIdx
      ? attachCommands(ps.d, att.from, att.to)
      : translateCommands(ps.d, (() => { const w = paramAlong(midOf(ps.d), a, b); const o = blend(att.from, att.to, w); return o.dx; })(),
        (() => { const w = paramAlong(midOf(ps.d), a, b); const o = blend(att.from, att.to, w); return o.dy; })()),
    style: ps.style,
  }));
  for (const t of el.text) {
    const o = blend(att.from, att.to, paramAlong({ x: t.box.x + t.box.width / 2, y: t.box.y + t.box.height / 2 }, a, b));
    t.x += o.dx; t.y += o.dy;
    const size = parseFloat(t.style['font-size'] ?? '14') || 14;
    t.box = estimateTextBox(t.content, t.x, t.y, t.anchor, size);
  }
  let bbox: Box | null = null;
  for (const ps of el.paths) bbox = bbox ? unionBox(bbox, pathBbox(ps.d)) : pathBbox(ps.d);
  for (const t of el.text) bbox = bbox ? unionBox(bbox, t.box) : t.box;
  if (bbox) el.bbox = bbox;
}

function midOf(d: PathCommand[]): Point {
  const pts = d.filter((c) => c.c !== 'Z') as Array<{ x: number; y: number }>;
  if (!pts.length) return { x: 0, y: 0 };
  const x = pts.reduce((s, p) => s + p.x, 0) / pts.length;
  const y = pts.reduce((s, p) => s + p.y, 0) / pts.length;
  return { x, y };
}

/** 每元素处置计划（直接拖拽 > 端点附着；同 plan 供 spec 与 DOM 两侧消费，保证一致） */
function elementPlans(spec: SceneSpec, ov: LayoutOverrides): Map<string, ElemPlan> {
  const plans = new Map<string, ElemPlan>();
  for (const el of spec.elements) {
    const own = ov.entities[baseKeyOf(el.key)] ?? null;
    if (own) plans.set(el.key, { off: own, attach: null });
    else if (el.kind === 'edge') plans.set(el.key, { off: null, attach: resolveAttach(el, spec, ov) });
    else plans.set(el.key, { off: null, attach: null });
  }
  return plans;
}

function applyPlansToSpec(spec: SceneSpec, plans: Map<string, ElemPlan>): void {
  for (const el of spec.elements) {
    const p = plans.get(el.key);
    if (!p) continue;
    if (p.off) shiftElement(el, p.off.dx, p.off.dy);
    else if (p.attach) applyAttachSpec(el, p.attach);
  }
}

/** 元素在 DOM 中的保守位移（画布预算用） */
function planExtent(p: ElemPlan): EntityOffset | null {
  if (p.off) return p.off;
  if (p.attach) {
    return {
      dx: Math.max(Math.abs(p.attach.from.dx), Math.abs(p.attach.to.dx)) * Math.sign(p.attach.from.dx + p.attach.to.dx || 1),
      dy: Math.max(Math.abs(p.attach.from.dy), Math.abs(p.attach.to.dy)) * Math.sign(p.attach.from.dy + p.attach.to.dy || 1),
    };
  }
  return null;
}

/** 统一画布半幅：锚定 + 全局 + 实体偏移/附着全部计入，保证不被裁切 */
function canvasHalf(specs: SceneSpec[], shifts: EntityOffset[], ov: LayoutOverrides, plans: Map<string, ElemPlan>[]): number {
  let half = PAD;
  specs.forEach((s, i) => {
    const g = { dx: shifts[i]!.dx + ov.global.dx, dy: shifts[i]!.dy + ov.global.dy };
    for (const el of s.elements) {
      const o = planExtent(plans[i]!.get(el.key) ?? { off: null, attach: null });
      const dx = g.dx + (o?.dx ?? 0);
      const dy = g.dy + (o?.dy ?? 0);
      const x = el.bbox.x + dx;
      const y = el.bbox.y + dy;
      half = Math.max(half, Math.abs(x), Math.abs(y), Math.abs(x + el.bbox.width), Math.abs(y + el.bbox.height));
    }
  });
  return Math.ceil(half + PAD);
}

/** 就地从 raw 重建 spec（锚定 + 全局 + 实体/附着，幂等） */
function rebuildSpec(layer: FrameSource, shift: EntityOffset, ov: LayoutOverrides): Map<string, ElemPlan> {
  const spec = deepCloneSpec(layer.rawSpec ?? layer.spec);
  const g = { dx: shift.dx + ov.global.dx, dy: shift.dy + ov.global.dy };
  if (g.dx || g.dy) shiftSpec(spec, g.dx, g.dy);
  const plans = elementPlans(spec, ov);
  applyPlansToSpec(spec, plans);
  layer.spec = spec;
  return plans;
}

/** DOM 侧附着：形状按当前原生属性读回命令并写回（主路径 attachCommands，其余平移） */
function attachInDom(node: Element, att: EdgeAttach): void {
  const shapes = (node.matches(SHAPE_DOM_SEL) ? [node] : Array.from(node.querySelectorAll(SHAPE_DOM_SEL)))
    .map((sh) => ({ sh, cmds: currentCommands(sh) }))
    .filter((s): s is { sh: Element; cmds: PathCommand[] } => s.cmds !== null && vertexCount(s.cmds) >= 2);
  if (!shapes.length) return;
  let main = shapes[0] as { sh: Element; cmds: PathCommand[] };
  for (const s of shapes) if (span(s.cmds) > span(main.cmds)) main = s;
  const a = firstV(main.cmds) as Point;
  const b = lastV(main.cmds) as Point;
  for (const s of shapes) {
    if (s === main) writeCommands(s.sh, attachCommands(s.cmds, att.from, att.to));
    else {
      const o = blend(att.from, att.to, paramAlong(midOf(s.cmds), a, b));
      writeCommands(s.sh, translateCommands(s.cmds, o.dx, o.dy));
    }
  }
  const texts = Array.from(node.querySelectorAll('text'));
  for (const tEl of texts) {
    const tx = parseFloat(tEl.getAttribute('x') ?? '0') || 0;
    const ty = parseFloat(tEl.getAttribute('y') ?? '0') || 0;
    const o = blend(att.from, att.to, paramAlong({ x: tx, y: ty }, a, b));
    tEl.setAttribute('x', String(tx + o.dx));
    tEl.setAttribute('y', String(ty + o.dy));
  }
}

/** 就地从 raw 重建 DOM（与 rebuildSpec 施加同一 plan，幂等） */
function rebuildSvg(layer: FrameSource, shift: EntityOffset, ov: LayoutOverrides, plans: Map<string, ElemPlan>, doc: Document): void {
  const svg = layer.svg;
  const root = (layer.raw ?? svg).cloneNode(true) as Element;
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  // 根属性不动（渲染器注入的定位样式须保留）；几何属性随后由 applyViewBox 统一覆写
  while (root.firstChild) svg.appendChild(root.firstChild);
  const g = { dx: shift.dx + ov.global.dx, dy: shift.dy + ov.global.dy };
  if (Math.abs(g.dx) > 0.01 || Math.abs(g.dy) > 0.01) shiftSvg(svg, g.dx, g.dy, doc);
  for (const el of layer.spec.elements) {
    const p = plans.get(el.key);
    if (!p) continue;
    const node = svg.querySelector(el.source.sel);
    if (!node) continue;
    if (p.off && (Math.abs(p.off.dx) > 0.01 || Math.abs(p.off.dy) > 0.01)) {
      const wrap = doc.createElementNS(SVG_NS, 'g');
      wrap.setAttribute('data-ta-offset', `${p.off.dx} ${p.off.dy}`);
      wrap.setAttribute('transform', `translate(${p.off.dx} ${p.off.dy})`);
      node.parentNode?.insertBefore(wrap, node);
      wrap.appendChild(node);
    } else if (p.attach) {
      attachInDom(node, p.attach);
    }
  }
}

/** 统一画布：对称方盒 viewBox → 画布居中、帧间/拖动不跳 */
export function applyViewBox(layer: FrameSource, half: number): void {
  const size = String(half * 2);
  const svg = layer.svg as SVGSVGElement;
  svg.setAttribute('viewBox', `${-half} ${-half} ${size} ${size}`);
  svg.setAttribute('width', size);
  svg.setAttribute('height', size);
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  const st = (svg as SVGElement).style;
  if (st) {
    st.width = `${size}px`;
    st.height = `${size}px`;
    st.removeProperty('max-width');
    st.removeProperty('max-height');
    st.background = 'transparent';
  }
  layer.spec.width = half * 2;
  layer.spec.height = half * 2;
  layer.spec.origin = { x: -half, y: -half };
}

/** 位置编排选项：锚策略链（container 自动 > median 中位数链），refKey 显式逃生口 */
export interface LayoutOptions {
  /** 'container'(默认)：容器锚优先，无合格容器退中位数；'median'：直接中位数链；'none'：直出后端坐标 */
  anchor?: 'container' | 'median' | 'none';
  refKey?: string;
}

/**
 * 位置模型总入口（compileFrames 之后、keydiff 之前调用；改偏移后重调用即幂等重建）：
 * raw/rawSpec 冻结 → 每层按 锚定+全局+实体 重建 spec 与 DOM → 统一画布。
 * 锚优先级（§19.3 / D1）：refKey 显式 > 容器锚 > 首帧中位数链。
 */
export function applyLayout(layers: FrameSource[], overrides: LayoutOverrides, opts: LayoutOptions = {}): LayoutInfo {
  const doc = layers[0]?.svg.ownerDocument ?? document;
  const specs = layers.map((l) => l.rawSpec ?? l.spec);
  const mode = opts.anchor ?? 'container';
  const cont = mode === 'container' ? containerShifts(specs, opts.refKey) : null;
  const shifts = mode === 'none'
    ? specs.map(() => ({ dx: 0, dy: 0 }))
    : cont ? cont.shifts : lockShifts(specs);
  const plans = layers.map((layer, i) => rebuildSpec(layer, shifts[i] ?? { dx: 0, dy: 0 }, overrides));
  const half = canvasHalf(specs, shifts, overrides, plans);
  layers.forEach((layer, i) => {
    rebuildSvg(layer, shifts[i] ?? { dx: 0, dy: 0 }, overrides, plans[i]!, doc);
    applyViewBox(layer, half);
  });
  const info = {
    shifts, half,
    anchorKind: opts.anchor === 'none'
      ? 'none'
      : cont ? 'container' as const : (layers.length > 1 ? 'median' as const : 'none' as const),
    ...(cont ? { containerKey: cont.key } : {}),
  };
  console.info('[ta-layout] anchor=%s half=%d container=%s shifts=%s', info.anchorKind,
    Math.round(half), (info as { containerKey?: string }).containerKey ?? '-',
    JSON.stringify(shifts.map((sh) => ({ dx: Math.round(sh.dx), dy: Math.round(sh.dy) }))));
  return info;
}

/** 锚点/实体命中查询（位置编辑 UI 用）：node 包含点优先，其次边/形状，最后 maxDist 内最近 node */
export function hitTestAnchor(
  spec: SceneSpec, p: { x: number; y: number }, maxDist = 24,
): { key: string; center: { x: number; y: number }; distance: number } | null {
  const contains = (el: SceneElement) =>
    p.x >= el.bbox.x && p.x <= el.bbox.x + el.bbox.width && p.y >= el.bbox.y && p.y <= el.bbox.y + el.bbox.height;
  const pickSmallest = (list: SceneElement[]) => list.reduce((a, b) =>
    (a.bbox.width * a.bbox.height <= b.bbox.width * b.bbox.height ? a : b));
  const nodes = spec.elements.filter((el) => el.kind === 'node');
  const insideNodes = nodes.filter(contains);
  if (insideNodes.length > 0) {
    const hit = pickSmallest(insideNodes);
    return { key: hit.key, center: centerOf(hit), distance: 0 };
  }
  const insideOthers = spec.elements.filter((el) => el.kind !== 'node' && el.kind !== 'label' && contains(el));
  if (insideOthers.length > 0) {
    const hit = pickSmallest(insideOthers);
    return { key: hit.key, center: centerOf(hit), distance: 0 };
  }
  let best: { key: string; center: { x: number; y: number }; distance: number } | null = null;
  for (const el of nodes) {
    const c = centerOf(el);
    const d = Math.hypot(c.x - p.x, c.y - p.y);
    if (d <= maxDist && (!best || d < best.distance)) best = { key: el.key, center: c, distance: d };
  }
  return best;
}
