import type { FrameDiff, PathSpec, SceneElement, SceneSpec, StyleMap } from './types';
import { commandsEqual, isomorphicPaths, translateCommands } from './path';
import { matchResiduals } from './match';
import { elementText } from './match';
import { normalizeText } from './key';
import { animDebug, animDebugOn, shortKey } from './debug';

const REL_STYLE_KEYS = ['fill', 'stroke', 'stroke-width', 'opacity', 'stroke-dasharray', 'font-size'];

function styleChanged(a: StyleMap, b: StyleMap): boolean {
  for (const k of REL_STYLE_KEYS) {
    if ((a[k] ?? '') !== (b[k] ?? '')) return true;
  }
  return false;
}

function samePaths(a: PathSpec[], b: PathSpec[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (!commandsEqual(a[i]!.d, b[i]!.d)) return false;
  }
  return true;
}

function geomChanged(a: PathSpec[], b: PathSpec[]): boolean {
  return !samePaths(a, b);
}

/** 整体一致平移检测（move 类，不算重绘） */
export function tryTranslation(a: PathSpec[], b: PathSpec[]): { dx: number; dy: number } | null {
  if (a.length !== b.length || a.length === 0) return null;
  const firstM = (cmds: PathSpec): { x: number; y: number } | null => {
    for (const c of cmds.d) if (c.c === 'M') return { x: c.x, y: c.y };
    return null;
  };
  const pa = firstM(a[0]!);
  const pb = firstM(b[0]!);
  if (!pa || !pb) return null;
  const dx = pb.x - pa.x;
  const dy = pb.y - pa.y;
  for (let i = 0; i < a.length; i++) {
    const shifted = translateCommands(a[i]!.d, dx, dy);
    if (!commandsEqual(shifted, b[i]!.d, 0.01)) return null;
  }
  return { dx, dy };
}

/** 同构判定（§7.1）：morph 的前提 */
export function isMorphable(a: SceneElement, b: SceneElement): boolean {
  if (a.paths.length === 0 || a.paths.length !== b.paths.length) return false;
  for (let i = 0; i < a.paths.length; i++) {
    if (!isomorphicPaths(a.paths[i]!.d, b.paths[i]!.d)) return false;
  }
  return true;
}

function textsChanged(a: SceneElement, b: SceneElement): boolean {
  return normalizeText(elementText(a)) !== normalizeText(elementText(b));
}

export interface DiffOptions {
  matchThreshold?: number;
}

/**
 * 帧间 keyed diff（docs/engine-design.md §7）。
 * 非同构几何变更按裁决 #6 拆为 exit + enter。
 */
export function keydiff(
  prev: SceneSpec,
  next: SceneSpec,
  opts: DiffOptions = {},
): FrameDiff {
  // 键规范化：同 (kind,label) 的消歧后缀元素（#2/#3）统一基键配对。
  // label 派生元素本就靠文本身份，位置抖动（如 text-anchor 居中）不应拆散身份。
  const normKey = (e: SceneElement): string => {
    const hash = e.key.indexOf('#');
    return hash > 0 ? e.key.slice(0, hash) : e.key;
  };
  const group = (els: SceneElement[]): Map<string, SceneElement[]> => {
    const map = new Map<string, SceneElement[]>();
    for (const e of els) {
      const k = normKey(e);
      const arr = map.get(k);
      if (arr) arr.push(e); else map.set(k, [e]);
    }
    return map;
  };

  const prevMap = group(prev.elements);
  const nextMap = group(next.elements);

  const usedPrev = new Set<SceneElement>();
  const usedNext = new Set<SceneElement>();
  const pairs: { p: SceneElement; n: SceneElement }[] = [];
  for (const [key, nList] of nextMap) {
    const pList = prevMap.get(key);
    if (!pList) continue;
    const m = Math.min(pList.length, nList.length);
    for (let i = 0; i < m; i++) {
      pairs.push({ p: pList[i]!, n: nList[i]! });
      usedPrev.add(pList[i]!);
      usedNext.add(nList[i]!);
    }
  }
  const residPrev = prev.elements.filter((e) => !usedPrev.has(e));
  const residNext = next.elements.filter((e) => !usedNext.has(e));
  const remap = matchResiduals(residPrev, residNext, opts.matchThreshold ?? 0.55);
  const prevByKey = new Map(residPrev.map((e) => [e.key, e]));
  const nextByKey = new Map(residNext.map((e) => [e.key, e]));
  for (const [pk, nk] of remap) {
    const p = prevByKey.get(pk);
    const n = nextByKey.get(nk);
    if (p && n) {
      pairs.push({ p, n });
      usedPrev.add(p);
      usedNext.add(n);
    }
  }

  const diff: FrameDiff = {
    from: -1,
    to: -1,
    enter: next.elements.filter((e) => !usedNext.has(e)).sort((a, b) => a.z - b.z),
    exit: prev.elements.filter((e) => !usedPrev.has(e)).sort((a, b) => a.z - b.z),
    move: [],
    update: [],
    text: [],
    stay: [],
  };

  for (const { p, n } of pairs) {
    const textChanged = textsChanged(p, n);
    const style = styleChanged(p.style, n.style);
    const geom = geomChanged(p.paths, n.paths);

    if (!textChanged && !style && !geom) {
      diff.stay.push(p.key);
      continue;
    }
    let split = false;
    if (geom) {
      const tr = tryTranslation(p.paths, n.paths);
      if (tr) {
        diff.move.push({ key: p.key, from: p.bbox, to: n.bbox, el: n, prev: p, dx: tr.dx, dy: tr.dy });
      } else if (isMorphable(p, n)) {
        diff.update.push({ key: p.key, prev: p, next: n, geom: true, style, morphable: true });
      } else {
        // 裁决 #6：非同构 → exit + enter
        diff.exit.push(p);
        diff.enter.push(n);
        split = true;
      }
    } else if (style) {
      diff.update.push({ key: p.key, prev: p, next: n, geom: false, style: true, morphable: false });
    }
    if (!split && textChanged) {
      diff.text.push({ key: p.key, prev: elementText(p), next: elementText(n), el: n, prevEl: p });
    }
  }

  diff.exit.sort((a, b) => a.z - b.z);
  diff.enter.sort((a, b) => a.z - b.z);
  if (animDebugOn()) {
    const K = (xs: { key: string }[]) => xs.map((x) => shortKey(x.key)).join(',');
    animDebug(`diff  move=[${K(diff.move)}]`,
      `| morph=[${K(diff.update.filter((u) => u.geom && u.morphable))}]`,
      `| style=[${K(diff.update.filter((u) => !(u.geom && u.morphable)))}]`,
      `| text=[${K(diff.text)}]`,
      `| exit=[${K(diff.exit)}]`,
      `| enter=[${K(diff.enter)}]`);
  }
  return diff;
}

export function diffIsEmpty(d: FrameDiff): boolean {
  return d.enter.length === 0 && d.exit.length === 0 && d.move.length === 0
    && d.update.length === 0 && d.text.length === 0;
}
