import type { Box, ElementKind, StyleMap } from './types';

export function normalizeText(s: string): string {
  return s.replace(/\s+/g, ' ').trim();
}

export function fnv1a(str: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return (h >>> 0).toString(36);
}

function sanitize(s: string): string {
  return normalizeText(s).replace(/["\\]/g, '');
}

export interface KeyInput {
  kind: ElementKind;
  hintText: string | null;
  labelText: string;
  style: StyleMap;
  bbox: Box;
  shapeCount: number;
}

/**
 * 内部键派生优先级链（docs/engine-design.md §6.1）：
 *   name hint（引擎名/title/data-name）> label 文本 > 几何指纹
 */
export function deriveKey(input: KeyInput, backend: string): string {
  if (input.hintText) return `ta:${backend}:name:${sanitize(input.hintText)}`;
  if (input.labelText) return `ta:${backend}:label:${input.kind}:${sanitize(input.labelText)}`;
  const q = (n: number): number => Math.round(n / 4);
  const fpSrc = [
    input.kind,
    q(input.bbox.x), q(input.bbox.y),
    Math.round(input.bbox.width), Math.round(input.bbox.height),
    input.shapeCount,
    input.style['fill'] ?? '', input.style['stroke'] ?? '',
  ].join('|');
  return `ta:${backend}:fp:${fnv1a(fpSrc)}`;
}

/** 同名冲突消歧：仅在出现次数 > 1 时追加 #i 后缀 */
export function disambiguate(keys: string[]): string[] {
  const total = new Map<string, number>();
  for (const k of keys) total.set(k, (total.get(k) ?? 0) + 1);
  const seen = new Map<string, number>();
  return keys.map((k) => {
    if ((total.get(k) ?? 0) <= 1) return k;
    const n = (seen.get(k) ?? 0) + 1;
    seen.set(k, n);
    return n === 1 ? k : `${k}#${n}`;
  });
}

export function selFor(key: string): string {
  return `[data-ta-key="${key.replace(/["\\]/g, '')}"]`;
}
