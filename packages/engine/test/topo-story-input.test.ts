/**
 * storyFromSources / storyFromFrames 双形态入口（topoOne 集成批 1.1/1.4）。
 */
import { describe, expect, it } from 'vitest';
import { storyFromSources, storyFromFrames } from '../src/topo/story-from-sources';
import { buildReceipt } from '../src/topo/receipt';

const svgOf = (names: string[]): string =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 120">` +
  names.map((n, i) => `<g class="node" data-name="${n}"><path d="M ${i * 60} 0 L ${i * 60 + 40} 20"/></g>`).join('') +
  '</svg>';

describe('storyFromSources', () => {
  it('源文数组 → 线性图（id 缺省 f1..fN、选项合并、entry 首帧）', () => {
    const b = storyFromSources(['A\nB', 'A\nB\nC'], { backend: 'dot', options: { step: 900 }, frameOptions: [undefined, { step: 1500 }] });
    expect(b.ok).toBe(true);
    expect(b.graph.entry).toBe('f1');
    expect(b.graph.states.map((s) => s.id)).toEqual(['f1', 'f2']);
    expect(b.graph.states[1]!.dwellMs).toBe(1500);
    expect(b.graph.edges).toEqual([{ from: 'f1', to: 'f2', choreography: { durationMs: 1500 } }]);
  });

  it('重复 frameIds 自动加后缀不冲突', () => {
    const b = storyFromSources(['A', 'B', 'C'], { frameIds: ['x', 'x', 'x-2'] });
    expect(b.ok).toBe(true);
    expect(b.graph.states.map((s) => s.id)).toEqual(['x', 'x-2', 'x-2-2']);
  });

  it('annotations 按帧注入（commit 信息通道）', () => {
    const b = storyFromSources(['A', 'B'], { annotations: [{ commit: 'abc123' }, undefined] });
    expect(b.graph.states[0]!.annotations).toEqual({ commit: 'abc123' });
    expect(b.graph.states[1]!.annotations).toBeUndefined();
  });

  it('空数组 → 构建错误', () => {
    const b = storyFromSources([]);
    expect(b.ok).toBe(false);
    expect(b.errors.some((e) => e.code === 'build/empty')).toBe(true);
  });

  it('产物可直接跑 buildReceipt', async () => {
    const b = storyFromSources(['A\nB', 'A\nB']);
    const r = await buildReceipt(b.doc);
    expect(r.ok).toBe(true);
  });
});

describe('storyFromFrames', () => {
  it('SVG 序列 → 线性图（states 走 svg 通道）', () => {
    const f = storyFromFrames([svgOf(['A', 'B']), svgOf(['A', 'B', 'C'])], { options: { step: 800 }, annotations: [{ commit: 'h1' }, { commit: 'h2' }] });
    expect(f.ok).toBe(true);
    expect(f.frameIds).toEqual(['f1', 'f2']);
    expect(f.graph.states[0]!.svg).toContain('<svg');
    expect(f.graph.states[0]!.source).toBeUndefined();
    expect(f.graph.states[0]!.dwellMs).toBe(800);
    expect(f.graph.edges[0]!.to).toBe('f2');
  });

  it('非 SVG 文本 → error', () => {
    const f = storyFromFrames(['not svg', svgOf(['A'])]);
    expect(f.ok).toBe(false);
    expect(f.errors.some((e) => e.message.includes('不是 SVG'))).toBe(true);
  });

  it('空数组 → error', () => {
    const f = storyFromFrames([]);
    expect(f.ok).toBe(false);
  });
});
