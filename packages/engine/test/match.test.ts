import { describe, expect, it } from 'vitest';
import { matchResiduals, similarity, textSim } from '../src/core/match';
import type { SceneElement } from '../src/core/types';

function el(key: string, over: Partial<SceneElement> = {}): SceneElement {
  return {
    key,
    kind: 'node',
    bbox: { x: 0, y: 0, width: 100, height: 40 },
    paths: [{ d: [], style: {} }],
    text: [{ content: '默认', x: 0, y: 0, anchor: 'start', box: { x: 0, y: 0, width: 10, height: 10 }, style: {} }],
    style: { fill: '#fff', stroke: '#000' },
    z: 0,
    source: { backend: 'generic', docIndex: 0, sel: `[data-ta-key="${key}"]` },
    ...over,
  };
}

describe('textSim', () => {
  it('相同/包含/不相干', () => {
    expect(textSim('登录请求', '登录请求')).toBe(1);
    expect(textSim('登录请求', '登录请求啊')).toBeGreaterThan(0.5);
    expect(textSim('ab', 'cd')).toBe(0);
    expect(textSim('', 'abc')).toBe(0);
  });
});

describe('similarity', () => {
  it('kind 不同直接 0 分', () => {
    expect(similarity(el('a', { kind: 'node' }), el('b', { kind: 'edge' }))).toBe(0);
  });

  it('同名同位高分，异名同位低于阈值', () => {
    const x = el('x');
    const y = el('y', { text: x.text });
    expect(similarity(x, y)).toBe(1);
    const z = el('z', { text: [{ ...x.text[0]!, content: '完全不同的内容啊啊' }] });
    expect(similarity(x, z)).toBeLessThan(0.9);
  });
});

describe('matchResiduals 贪心匹配', () => {
  it('键漂移但内容一致 → 全部匹配', () => {
    const prev = [el('ta:fp:1'), el('ta:fp:2')];
    const next = [el('ta:fp:9', { text: prev[0]!.text }), el('ta:fp:8', { text: prev[1]!.text })];
    const m = matchResiduals(prev, next);
    expect(m.size).toBe(2);
    expect(m.get('ta:fp:1')).toBe('ta:fp:9');
  });

  it('互斥分配：一个 prev 不会匹配两个 next', () => {
    const prev = [el('p1')];
    const next = [el('n1'), el('n2', { key: 'n2' })];
    const m = matchResiduals(prev, next);
    expect(m.size).toBe(1);
  });

  it('低于阈值不匹配（错位远处）', () => {
    const prev = [el('p', { bbox: { x: 0, y: 0, width: 10, height: 10 }, text: [] })];
    const next = [el('n', { bbox: { x: 500, y: 500, width: 10, height: 10 }, text: [], style: {} })];
    expect(matchResiduals(prev, next).size).toBe(0);
  });

  it('大图性能：600 匿名元素整体平移，网格预筛下近线性完成且不误匹配', () => {
    const N = 600;
    const prev: SceneElement[] = [];
    const next: SceneElement[] = [];
    for (let i = 0; i < N; i++) {
      const x = (i % 30) * 60;
      const y = Math.floor(i / 30) * 60;
      prev.push(el(`p${i}`, { text: [], bbox: { x, y, width: 40, height: 20 } }));
      next.push(el(`q${i}`, { text: [], bbox: { x: x + 8, y: y + 5, width: 40, height: 20 } }));
    }
    const t0 = Date.now();
    const m = matchResiduals(prev, next, 0.5);
    const dt = Date.now() - t0;
    expect(m.size).toBe(N);
    expect(dt).toBeLessThan(1500);
  });
});
