import type { Box, SceneElement, StyleMap } from './types';
import { bboxIntersectionArea } from './types';
import { normalizeText } from './key';

function bigrams(s: string): Set<string> {
  const set = new Set<string>();
  if (s.length < 2) {
    if (s.length === 1) set.add(s);
    return set;
  }
  for (let i = 0; i < s.length - 1; i++) set.add(s.slice(i, i + 2));
  return set;
}

export function textSim(a: string, b: string): number {
  if (!a && !b) return 0;
  if (a === b) return 1;
  if (!a || !b) return 0;
  const A = bigrams(a), B = bigrams(b);
  if (A.size === 0 || B.size === 0) return 0;
  let inter = 0;
  for (const g of A) if (B.has(g)) inter++;
  return (2 * inter) / (A.size + B.size);
}

const STYLE_KEYS = ['fill', 'stroke', 'stroke-width', 'font-size'];

function styleSim(a: StyleMap, b: StyleMap): number {
  let hit = 0, total = 0;
  for (const k of STYLE_KEYS) {
    const va = a[k], vb = b[k];
    if (va === undefined && vb === undefined) continue;
    total++;
    if (va === vb) hit++;
  }
  return total === 0 ? 1 : hit / total;
}

function iou(a: Box, b: Box): number {
  const inter = bboxIntersectionArea(a, b);
  const union = a.width * a.height + b.width * b.height - inter;
  return union <= 0 ? 0 : inter / union;
}

export function elementText(e: SceneElement): string {
  return normalizeText(e.text.map((t) => t.content).join(' '));
}

/** 残差元素相似度（0~1），跨帧身份匹配链第二级（§6.2） */
export function similarity(a: SceneElement, b: SceneElement): number {
  if (a.kind !== b.kind) return 0;
  const ta = elementText(a), tb = elementText(b);
  const hasText = ta.length > 0 || tb.length > 0;
  const sT = hasText ? textSim(ta, tb) : 0;
  const sS = styleSim(a.style, b.style);
  const sI = iou(a.bbox, b.bbox);
  const sShp = a.paths.length === b.paths.length ? 1 : 0.4;
  if (hasText) {
    return 0.45 * sT + 0.55 * (0.45 * sS + 0.2 * sI + 0.35 * sShp);
  }
  return 0.5 * sS + 0.2 * sI + 0.3 * sShp;
}

/**
 * 键集不相交时的贪心最大权匹配：prev.key -> next.key。
 * 命中后 diff 层将其视为同一元素重分类（enter/exit 得以消除）。
 * 大图优化：候选来自两路近线性索引 —— 文本精确桶 + 空间网格邻域桶（3x3），
 * 覆盖「改名/同文本」与「位置重叠」两类身份线索，避免 O(prev×next)。
 */
export function matchResiduals(
  prev: SceneElement[],
  next: SceneElement[],
  threshold = 0.55,
): Map<string, string> {
  const pairs: { pk: string; nk: string; score: number }[] = [];
  const seen = new Set<string>();
  const consider = (p: SceneElement, n: SceneElement): void => {
    if (p.kind !== n.kind) return;
    const id = `${p.key} ${n.key}`;
    if (seen.has(id)) return;
    seen.add(id);
    const s = similarity(p, n);
    if (s >= threshold) pairs.push({ pk: p.key, nk: n.key, score: s });
  };

  const CELL = 96;
  const textBuckets = new Map<string, SceneElement[]>();
  const grid = new Map<string, SceneElement[]>();
  const put = (map: Map<string, SceneElement[]>, k: string, e: SceneElement): void => {
    const arr = map.get(k);
    if (arr) arr.push(e); else map.set(k, [e]);
  };
  const cellKey = (e: SceneElement): [number, number] => [
    Math.floor((e.bbox.x + e.bbox.width / 2) / CELL),
    Math.floor((e.bbox.y + e.bbox.height / 2) / CELL),
  ];
  for (const n of next) {
    const t = elementText(n);
    if (t) put(textBuckets, `${n.kind}|${t}`, n);
    const [cx, cy] = cellKey(n);
    put(grid, `${cx},${cy}`, n);
  }
  for (const p of prev) {
    const tp = elementText(p);
    if (tp) for (const n of textBuckets.get(`${p.kind}|${tp}`) ?? []) consider(p, n);
    const [cx, cy] = cellKey(p);
    for (let dx = -1; dx <= 1; dx++) {
      for (let dy = -1; dy <= 1; dy++) {
        for (const n of grid.get(`${cx + dx},${cy + dy}`) ?? []) consider(p, n);
      }
    }
  }
  // 小图兜底：网格可能漏掉「大幅平移的匿名同形元素」，规模小则直接全对全
  if (prev.length * next.length <= 4096) {
    for (const p of prev) for (const n of next) consider(p, n);
  }

  pairs.sort((a, b) => b.score - a.score);
  const usedPrev = new Set<string>(), usedNext = new Set<string>();
  const result = new Map<string, string>();
  for (const pr of pairs) {
    if (usedPrev.has(pr.pk) || usedNext.has(pr.nk)) continue;
    usedPrev.add(pr.pk);
    usedNext.add(pr.nk);
    result.set(pr.pk, pr.nk);
  }
  return result;
}
