import type { Box } from './types';

export function estimateTextWidth(content: string, fontSize: number): number {
  let w = 0;
  for (const ch of content) {
    w += (ch.codePointAt(0) ?? 0) > 0x2e80 ? fontSize : fontSize * 0.58;
  }
  return w;
}

export function estimateTextBox(
  content: string, x: number, y: number,
  anchor: 'start' | 'middle' | 'end', fontSize: number,
): Box {
  const w = estimateTextWidth(content, fontSize);
  const h = fontSize * 1.2;
  const x0 = anchor === 'middle' ? x - w / 2 : anchor === 'end' ? x - w : x;
  return { x: x0, y: y - fontSize * 0.85, width: w, height: h };
}
