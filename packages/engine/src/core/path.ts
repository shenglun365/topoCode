import type { Box, PathCommand } from './types';
import { zeroBox } from './types';

export interface Point {
  x: number;
  y: number;
}

const CMD_ARGS: Record<string, number> = {
  m: 2, l: 2, h: 1, v: 1, t: 2, q: 4, s: 4, c: 6, a: 7, z: 0,
};
const CMD_REPEAT: Record<string, string> = { m: 'l', M: 'L' };

const TOKEN_RE = /([MmLlHhVvCcSsQqTtAaZz])|(-?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?)/g;

/** 解析 SVG path d 字符串为绝对指令序列（A 指令参数需以分隔符隔开） */
export function parsePathD(input: string): PathCommand[] {
  const out: PathCommand[] = [];
  let cmd = '';
  let args: number[] = [];
  let cur: Point = { x: 0, y: 0 };
  let start: Point = { x: 0, y: 0 };
  let prevCtrl: Point | null = null;
  let prevKind = '';

  const flush = (): void => {
    if (!cmd) return;
    const want = CMD_ARGS[cmd.toLowerCase()] ?? 0;
    while (args.length >= want && want > 0) {
      const a = args.splice(0, want);
      emit(a);
    }
    if (cmd.toLowerCase() === 'z' && args.length === 0) {
      emit([]);
    }
  };

  const emit = (a: number[]): void => {
    const rel = cmd === cmd.toLowerCase();
    const abs = (x: number, y: number): Point =>
      rel ? { x: cur.x + x, y: cur.y + y } : { x, y };
    switch (cmd.toLowerCase()) {
      case 'm': {
        const p = abs(a[0] as number, a[1] as number);
        out.push({ c: 'M', x: p.x, y: p.y });
        cur = p;
        start = p;
        prevCtrl = null;
        cmd = CMD_REPEAT[cmd] ?? cmd; // implicit M -> L
        break;
      }
      case 'l': {
        const p = abs(a[0] as number, a[1] as number);
        out.push({ c: 'L', x: p.x, y: p.y });
        cur = p;
        prevCtrl = null;
        break;
      }
      case 'h': {
        const p = rel ? { x: cur.x + (a[0] as number), y: cur.y } : { x: a[0] as number, y: cur.y };
        out.push({ c: 'L', x: p.x, y: p.y });
        cur = p;
        prevCtrl = null;
        break;
      }
      case 'v': {
        const p = rel ? { x: cur.x, y: cur.y + (a[0] as number) } : { x: cur.x, y: a[0] as number };
        out.push({ c: 'L', x: p.x, y: p.y });
        cur = p;
        prevCtrl = null;
        break;
      }
      case 'c': {
        const x1 = rel ? cur.x + a[0] : a[0];
        const y1 = rel ? cur.y + a[1] : a[1];
        const x2 = rel ? cur.x + a[2] : a[2];
        const y2 = rel ? cur.y + a[3] : a[3];
        const x = rel ? cur.x + a[4] : a[4];
        const y = rel ? cur.y + a[5] : a[5];
        out.push({ c: 'C', x1: x1 as number, y1: y1 as number, x2: x2 as number, y2: y2 as number, x: x as number, y: y as number });
        cur = { x: x as number, y: y as number };
        prevCtrl = { x: x2 as number, y: y2 as number };
        break;
      }
      case 's': {
        const refl = prevKind === 'C' || prevKind === 'S'
          ? { x: 2 * cur.x - (prevCtrl?.x ?? cur.x), y: 2 * cur.y - (prevCtrl?.y ?? cur.y) }
          : { ...cur };
        const x2 = rel ? cur.x + a[0] : a[0];
        const y2 = rel ? cur.y + a[1] : a[1];
        const x = rel ? cur.x + a[2] : a[2];
        const y = rel ? cur.y + a[3] : a[3];
        out.push({ c: 'C', x1: refl.x, y1: refl.y, x2: x2 as number, y2: y2 as number, x: x as number, y: y as number });
        cur = { x: x as number, y: y as number };
        prevCtrl = { x: x2 as number, y: y2 as number };
        break;
      }
      case 'q': {
        const x1 = rel ? cur.x + a[0] : a[0];
        const y1 = rel ? cur.y + a[1] : a[1];
        const x = rel ? cur.x + a[2] : a[2];
        const y = rel ? cur.y + a[3] : a[3];
        out.push({ c: 'Q', x1: x1 as number, y1: y1 as number, x: x as number, y: y as number });
        cur = { x: x as number, y: y as number };
        prevCtrl = { x: x1 as number, y: y1 as number };
        break;
      }
      case 't': {
        const refl = prevKind === 'Q' || prevKind === 'T'
          ? { x: 2 * cur.x - (prevCtrl?.x ?? cur.x), y: 2 * cur.y - (prevCtrl?.y ?? cur.y) }
          : { ...cur };
        const x = rel ? cur.x + a[0] : a[0];
        const y = rel ? cur.y + a[1] : a[1];
        out.push({ c: 'Q', x1: refl.x, y1: refl.y, x: x as number, y: y as number });
        cur = { x: x as number, y: y as number };
        prevCtrl = refl;
        break;
      }
      case 'a': {
        const x = rel ? cur.x + a[5] : a[5];
        const y = rel ? cur.y + a[6] : a[6];
        out.push({
          c: 'A', rx: a[0] as number, ry: a[1] as number, rot: a[2] as number,
          laf: a[3] as number, sf: a[4] as number, x: x as number, y: y as number,
        });
        cur = { x: x as number, y: y as number };
        prevCtrl = null;
        break;
      }
      case 'z': {
        out.push({ c: 'Z' });
        cur = { ...start };
        prevCtrl = null;
        break;
      }
    }
    prevKind = cmd.toUpperCase();
  };

  let m: RegExpExecArray | null;
  TOKEN_RE.lastIndex = 0;
  while ((m = TOKEN_RE.exec(input)) !== null) {
    if (m[1]) {
      flush();
      cmd = m[1];
      args = [];
      if (cmd.toLowerCase() === 'z') {
        flush();
        cmd = '';
      }
    } else if (cmd) {
      args.push(parseFloat(m[2] as string));
      const want = CMD_ARGS[cmd.toLowerCase()] ?? 0;
      if (args.length >= want && want > 0) {
        const a = args.splice(0, want);
        emit(a);
      }
    }
  }
  flush();
  return out;
}

function cubicAt(p0: Point, p1: Point, p2: Point, p3: Point, t: number): Point {
  const u = 1 - t;
  return {
    x: u * u * u * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t * t * t * p3.x,
    y: u * u * u * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t * t * t * p3.y,
  };
}

function quadAt(p0: Point, p1: Point, p2: Point, t: number): Point {
  const u = 1 - t;
  return {
    x: u * u * p0.x + 2 * u * t * p1.x + t * t * p2.x,
    y: u * u * p0.y + 2 * u * t * p1.y + t * t * p2.y,
  };
}

/** 展平为近似点列（用于 bbox 测量） */
export function pathPoints(cmds: PathCommand[]): Point[] {
  const pts: Point[] = [];
  let cur: Point = { x: 0, y: 0 };
  let start: Point = { x: 0, y: 0 };
  for (const c of cmds) {
    switch (c.c) {
      case 'M':
      case 'L':
        pts.push({ x: c.x, y: c.y });
        cur = { x: c.x, y: c.y };
        if (c.c === 'M') start = { ...cur };
        break;
      case 'C': {
        for (let i = 0.25; i <= 1.001; i += 0.25) {
          pts.push(cubicAt(cur, { x: c.x1, y: c.y1 }, { x: c.x2, y: c.y2 }, { x: c.x, y: c.y }, i));
        }
        cur = { x: c.x, y: c.y };
        break;
      }
      case 'Q': {
        for (let i = 0.25; i <= 1.001; i += 0.25) {
          pts.push(quadAt(cur, { x: c.x1, y: c.y1 }, { x: c.x, y: c.y }, i));
        }
        cur = { x: c.x, y: c.y };
        break;
      }
      case 'A': {
        pts.push({ x: c.x, y: c.y });
        cur = { x: c.x, y: c.y };
        break;
      }
      case 'Z':
        cur = { ...start };
        break;
    }
  }
  return pts;
}

export function pathBbox(cmds: PathCommand[]): Box {
  const pts = pathPoints(cmds);
  if (pts.length === 0) return zeroBox();
  let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
  for (const p of pts) {
    x1 = Math.min(x1, p.x); y1 = Math.min(y1, p.y);
    x2 = Math.max(x2, p.x); y2 = Math.max(y2, p.y);
  }
  return { x: x1, y: y1, width: x2 - x1, height: y2 - y1 };
}

const CMD_ORDER: Record<string, number> = { M: 0, L: 1, C: 2, Q: 3, A: 4, Z: 5 };

function numsOf(c: PathCommand): number[] {
  const { c: kind, ...rest } = c as unknown as Record<string, unknown>;
  return Object.values(rest).filter((v): v is number => typeof v === 'number');
}

/** 指令类型序列完全一致且点数一致 = 同构，可做 morph 插值 */
export function isomorphicPaths(a: PathCommand[], b: PathCommand[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].c !== b[i].c) return false;
  }
  return true;
}

function lerpNums(a: number[], b: number[], t: number): number[] {
  return a.map((v, i) => v + ((b[i] as number) - v) * t);
}

function rebuild(c: PathCommand, nums: number[]): PathCommand {
  switch (c.c) {
    case 'M':
    case 'L':
      return { c: c.c, x: nums[0] as number, y: nums[1] as number };
    case 'C':
      return { c: 'C', x1: nums[0] as number, y1: nums[1] as number, x2: nums[2] as number, y2: nums[3] as number, x: nums[4] as number, y: nums[5] as number };
    case 'Q':
      return { c: 'Q', x1: nums[0] as number, y1: nums[1] as number, x: nums[2] as number, y: nums[3] as number };
    case 'A':
      return { c: 'A', rx: nums[0] as number, ry: nums[1] as number, rot: nums[2] as number, laf: c.laf, sf: c.sf, x: nums[3] as number, y: nums[4] as number };
    default:
      return { c: 'Z' };
  }
}

/** 同构指令序列逐参数插值 */
export function lerpCommands(a: PathCommand[], b: PathCommand[], t: number): PathCommand[] {
  return a.map((c, i) => {
    const o = b[i] as PathCommand;
    if (c.c === 'Z' || o.c === 'Z') return { c: 'Z' };
    if (c.c === 'A' && o.c === 'A') {
      const ra = [c.rx, c.ry, c.rot, c.x, c.y];
      const rb = [o.rx, o.ry, o.rot, o.x, o.y];
      return rebuild(c, lerpNums(ra, rb, t));
    }
    return rebuild(c, lerpNums(numsOf(c), numsOf(o), t));
  });
}

function fmt(n: number): string {
  return String(Math.round(n * 1000) / 1000);
}

export function commandsToD(cmds: PathCommand[]): string {
  const parts: string[] = [];
  for (const c of cmds) {
    switch (c.c) {
      case 'M': parts.push(`M ${fmt(c.x)} ${fmt(c.y)}`); break;
      case 'L': parts.push(`L ${fmt(c.x)} ${fmt(c.y)}`); break;
      case 'C': parts.push(`C ${fmt(c.x1)} ${fmt(c.y1)} ${fmt(c.x2)} ${fmt(c.y2)} ${fmt(c.x)} ${fmt(c.y)}`); break;
      case 'Q': parts.push(`Q ${fmt(c.x1)} ${fmt(c.y1)} ${fmt(c.x)} ${fmt(c.y)}`); break;
      case 'A': parts.push(`A ${fmt(c.rx)} ${fmt(c.ry)} ${fmt(c.rot)} ${c.laf} ${c.sf} ${fmt(c.x)} ${fmt(c.y)}`); break;
      case 'Z': parts.push('Z'); break;
    }
  }
  return parts.join(' ');
}

export function translateCommands(cmds: PathCommand[], dx: number, dy: number): PathCommand[] {
  return cmds.map((c) => {
    switch (c.c) {
      case 'M':
      case 'L':
        return { c: c.c, x: c.x + dx, y: c.y + dy };
      case 'C':
        return { c: 'C', x1: c.x1 + dx, y1: c.y1 + dy, x2: c.x2 + dx, y2: c.y2 + dy, x: c.x + dx, y: c.y + dy };
      case 'Q':
        return { c: 'Q', x1: c.x1 + dx, y1: c.y1 + dy, x: c.x + dx, y: c.y + dy };
      case 'A':
        return { c: 'A', rx: c.rx, ry: c.ry, rot: c.rot, laf: c.laf, sf: c.sf, x: c.x + dx, y: c.y + dy };
      default:
        return { c: 'Z' };
    }
  });
}

export function commandsEqual(a: PathCommand[], b: PathCommand[], eps = 0.75): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    const x = a[i] as PathCommand, y = b[i] as PathCommand;
    if (x.c !== y.c) return false;
    if (x.c === 'Z') continue;
    const na = numsOf(x), nb = numsOf(y);
    if (na.length !== nb.length) return false;
    for (let j = 0; j < na.length; j++) {
      if (Math.abs((na[j] as number) - (nb[j] as number)) > eps) return false;
    }
  }
  return true;
}

/**
 * 端点吸附形变（§19.3 D3）：路径首点钉住 +from、末点钉住 +to，中段平滑过渡——
 * 两端始终与各自节点接合（线不缩、不留缝）。
 * 'linear'：顶点按指令序均匀加权（曲线/一般路径）；
 * 'segment'：折线首段两端全额跟随 from、末段跟随 to（保持正交折角），中段按弧长过渡；
 * 'auto'：纯折线用 segment，否则 linear。
 */
export interface AttachOffset {
  dx: number;
  dy: number;
}

const clamp01 = (v: number): number => Math.min(1, Math.max(0, v));

export function attachCommands(
  cmds: PathCommand[], from: AttachOffset, to: AttachOffset, mode: 'auto' | 'linear' | 'segment' = 'auto',
): PathCommand[] {
  const pts = cmds.flatMap((c) => ('x' in c && 'y' in c) ? [{ x: c.x, y: c.y }] : []);
  const n = pts.length;
  if (n < 2) return cmds.map((c) => ({ ...c }) as PathCommand);
  const poly = cmds.every((c) => c.c === 'M' || c.c === 'L' || c.c === 'Z');
  const seg = mode === 'segment' || (mode === 'auto' && poly && n > 2);
  const weights: number[] = [];
  if (!seg) {
    for (let i = 0; i < n; i++) weights.push(i / (n - 1));
  } else {
    const lens: number[] = [];
    let total = 0;
    for (let i = 1; i < n; i++) {
      const l = Math.hypot(pts[i]!.x - pts[i - 1]!.x, pts[i]!.y - pts[i - 1]!.y);
      lens.push(l);
      total += l;
    }
    const first = lens[0] as number;
    const last = lens[lens.length - 1] as number;
    const span = Math.max(1e-6, total - first - last);
    const s: number[] = [0];
    for (const l of lens) s.push((s[s.length - 1] as number) + l);
    for (let i = 0; i < n; i++) {
      if (i <= 1) weights.push(0);
      else if (i >= n - 2) weights.push(1);
      else weights.push(clamp01(((s[i] as number) - first) / span));
    }
  }
  let vk = -1;
  return cmds.map((c) => {
    if (c.c === 'Z') return { c: 'Z' as const };
    vk++;
    const w = weights[vk] ?? 0;
    const dx = from.dx * (1 - w) + to.dx * w;
    const dy = from.dy * (1 - w) + to.dy * w;
    switch (c.c) {
      case 'M':
      case 'L':
        return { c: c.c, x: c.x + dx, y: c.y + dy };
      case 'C':
        return { c: 'C', x1: c.x1 + dx, y1: c.y1 + dy, x2: c.x2 + dx, y2: c.y2 + dy, x: c.x + dx, y: c.y + dy };
      case 'Q':
        return { c: 'Q', x1: c.x1 + dx, y1: c.y1 + dy, x: c.x + dx, y: c.y + dy };
      case 'A':
        return { c: 'A', rx: c.rx, ry: c.ry, rot: c.rot, laf: c.laf, sf: c.sf, x: c.x + dx, y: c.y + dy };
      default:
        return { c: 'Z' as const };
    }
  });
}

/** 点在主路径首末点连线上的归一化位置（辅助路径/标签跟随权重） */
export function paramAlong(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x, dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  if (len2 < 1e-9) return 0;
  return clamp01(((p.x - a.x) * dx + (p.y - a.y) * dy) / len2);
}

export interface Attrs {
  [k: string]: string;
}

/** 基础图形 -> 统一 path 指令 */
export function shapesToCommands(tag: string, a: Attrs): PathCommand[] {
  const num = (k: string, d = 0): number => (a[k] !== undefined && a[k] !== '' ? parseFloat(a[k] as string) : d);
  switch (tag) {
    case 'path':
      return parsePathD(a['d'] ?? '');
    case 'rect': {
      const x = num('x'), y = num('y'), w = num('width'), h = num('height');
      return [
        { c: 'M', x, y }, { c: 'L', x: x + w, y }, { c: 'L', x: x + w, y: y + h },
        { c: 'L', x, y: y + h }, { c: 'Z' },
      ];
    }
    case 'line':
      return [{ c: 'M', x: num('x1'), y: num('y1') }, { c: 'L', x: num('x2'), y: num('y2') }];
    case 'polyline':
    case 'polygon': {
      const pts = parsePoints(a['points'] ?? '');
      if (pts.length === 0) return [];
      const cmds: PathCommand[] = [{ c: 'M', x: pts[0]!.x, y: pts[0]!.y }];
      for (let i = 1; i < pts.length; i++) cmds.push({ c: 'L', x: pts[i]!.x, y: pts[i]!.y });
      if (tag === 'polygon') cmds.push({ c: 'Z' });
      return cmds;
    }
    case 'circle':
    case 'ellipse': {
      const cx = num('cx'), cy = num('cy');
      const rx = tag === 'circle' ? num('r') : num('rx');
      const ry = tag === 'circle' ? num('r') : num('ry');
      return [
        { c: 'M', x: cx - rx, y: cy },
        { c: 'A', rx, ry, rot: 0, laf: 1, sf: 0, x: cx + rx, y: cy },
        { c: 'A', rx, ry, rot: 0, laf: 1, sf: 0, x: cx - rx, y: cy },
        { c: 'Z' },
      ];
    }
    default:
      return [];
  }
}

function parsePoints(s: string): Point[] {
  const nums = s.match(/-?(?:\d*\.\d+|\d+)/g)?.map(Number) ?? [];
  const pts: Point[] = [];
  for (let i = 0; i + 1 < nums.length; i += 2) {
    pts.push({ x: nums[i] as number, y: nums[i + 1] as number });
  }
  return pts;
}

export function cmdTypeKey(c: PathCommand): string {
  return CMD_ORDER[c.c] !== undefined ? c.c : '?';
}

/** DOM 形状 -> 同构 PathCommand（path/line/polyline/polygon/rect 原生属性读取） */
export function currentCommands(el: Element): PathCommand[] | null {
  const tag = el.tagName.toLowerCase();
  const attr = (k: string): number => parseFloat(el.getAttribute(k) ?? '0') || 0;
  if (tag === 'path') return el.getAttribute('d') ? parsePathD(el.getAttribute('d') as string) : [];
  if (tag === 'line') return [{ c: 'M', x: attr('x1'), y: attr('y1') }, { c: 'L', x: attr('x2'), y: attr('y2') }];
  if (tag === 'polyline' || tag === 'polygon') {
    const nums = (el.getAttribute('points') ?? '').match(/-?\d*\.?\d+/g)?.map(Number) ?? [];
    const pts: Point[] = [];
    for (let i = 0; i + 1 < nums.length; i += 2) pts.push({ x: nums[i]!, y: nums[i + 1]! });
    const cmds: PathCommand[] = pts.length ? [{ c: 'M', x: pts[0]!.x, y: pts[0]!.y }, ...pts.slice(1).map((p) => ({ c: 'L' as const, x: p.x, y: p.y }))] : [];
    if (tag === 'polygon') cmds.push({ c: 'Z' });
    return cmds;
  }
  if (tag === 'rect') {
    const x = attr('x'), y = attr('y'), w = attr('width'), h = attr('height');
    return [
      { c: 'M', x, y }, { c: 'L', x: x + w, y }, { c: 'L', x: x + w, y: y + h },
      { c: 'L', x, y: y + h }, { c: 'Z' },
    ];
  }
  return null;
}

/** 插值/形变后的 PathCommand 写回元素原生属性 */
export function writeCommands(el: Element, cmds: PathCommand[]): void {
  const tag = el.tagName.toLowerCase();
  const set = (k: string, v: number): void => el.setAttribute(k, String(Math.round(v * 1000) / 1000));
  if (tag === 'path') { el.setAttribute('d', commandsToD(cmds)); return; }
  if (tag === 'line') {
    const a = cmds[0], b = cmds[1];
    if (a && b && 'x' in a && 'x' in b) { set('x1', a.x); set('y1', a.y); set('x2', b.x); set('y2', b.y); }
    return;
  }
  if (tag === 'polyline' || tag === 'polygon') {
    const pts = cmds.filter((c): c is Extract<PathCommand, { x: number }> => 'x' in c);
    el.setAttribute('points', pts.map((p) => `${Math.round(p.x * 1000) / 1000},${Math.round(p.y * 1000) / 1000}`).join(' '));
    return;
  }
  if (tag === 'rect') {
    const pts = cmds.filter((c): c is Extract<PathCommand, { x: number }> => 'x' in c);
    const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
    if (!xs.length) return;
    const x = Math.min(...xs), y = Math.min(...ys);
    set('x', x); set('y', y); set('width', Math.max(...xs) - x); set('height', Math.max(...ys) - y);
  }
}
