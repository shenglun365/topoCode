import { describe, expect, it } from 'vitest';
import { buildTimeline, resolveOrder } from '../src/core/timeline';
import { keydiff } from '../src/core/diff';
import { capture } from '../src/core/capture';
import { emptyScene } from './helpers';
import { nodeG, svgDoc } from './fixtures';
import type { FrameDiff } from '../src/core/types';

function cap(s: string) {
  return capture(s).spec;
}

function enterDiff(count: number, xs: number[]): FrameDiff {
  const a = emptyScene();
  const inner = xs.map((x, i) => nodeG(x, 10, `N${i}`, { name: `N${i}` })).join('');
  const b = cap(svgDoc(inner));
  return keydiff(a, b);
}

describe('buildTimeline', () => {
  it('doc 序：enter 延迟按文档序递增', () => {
    const d = enterDiff(3, [10, 200, 350]);
    const t = buildTimeline(d, {}, 900);
    const enters = t.items.filter((i) => i.cls === 'enter');
    expect(enters.map((i) => i.delayMs)).toEqual([0, 60, 120]);
  });

  it('position 序：按 x 排序错峰', () => {
    const a = emptyScene();
    const b = cap(svgDoc(
      nodeG(300, 10, 'C', { name: 'C' }) + nodeG(10, 10, 'A', { name: 'A' }) + nodeG(150, 10, 'B', { name: 'B' }),
    ));
    const t = buildTimeline(keydiff(a, b), { opts: { order: 'position' } }, 900);
    expect(t.items.filter((i) => i.cls === 'enter').map((i) => i.el.key)).toEqual([
      'ta:generic:name:A', 'ta:generic:name:B', 'ta:generic:name:C',
    ]);
  });

  it('reverse + 自定义 stagger', () => {
    const t = buildTimeline(enterDiff(2, [10, 200]), { opts: { order: 'reverse', staggerMs: 200 } }, 900);
    const enters = t.items.filter((i) => i.cls === 'enter');
    expect(enters[0]!.el.key).toContain('N1');
    expect(enters[1]!.delayMs).toBe(200);
  });

  it('自定义 comparator', () => {
    const t = buildTimeline(
      enterDiff(2, [10, 200]),
      { opts: { order: (a, b) => a.bbox.x - b.bbox.x } },
      900,
    );
    expect(t.items.filter((i) => i.cls === 'enter')[0]!.el.bbox.x).toBeLessThan(100);
  });

  it('exit 槽先于 enter 槽（overlap=0 串行）', () => {
    const inner1 = nodeG(10, 10, '旧', { name: 'GONE' });
    const inner2 = nodeG(200, 10, '新', { name: 'NEW' });
    const d = keydiff(cap(svgDoc(inner1)), cap(svgDoc(inner2)));
    const t = buildTimeline(d, { opts: { overlap: 0 } }, 900);
    const exitAt = Math.min(...t.items.filter((i) => i.cls === 'exit').map((i) => i.delayMs));
    const enterAt = Math.max(...t.items.filter((i) => i.cls === 'enter').map((i) => i.delayMs));
    expect(exitAt).toBeLessThan(enterAt);
  });

  it('transitions 覆盖 + durationMs 强制帧长', () => {
    const d = enterDiff(1, [10]);
    const t = buildTimeline(
      d,
      { opts: { durationMs: 300, transitions: { enter: { type: 'fade', durationMs: 100 } } } },
      900,
    );
    expect(t.items[0]!.transition.type).toBe('fade');
    expect(t.frameMs).toBe(300);
  });

  it('frameMs 至少为 stepMs，totalMs 覆盖所有项', () => {
    const t = buildTimeline(enterDiff(4, [10, 100, 200, 300]), {}, 2000);
    expect(t.frameMs).toBeGreaterThanOrEqual(2000);
    for (const i of t.items) expect(i.delayMs + i.transition.durationMs).toBeLessThanOrEqual(t.totalMs + 0.001);
  });

  it('resolveOrder 回退：degree 无邻接数据时退文档序', () => {
    const cmp = resolveOrder('degree');
    const mk = (z: number, idx: number) => ({ z, source: { docIndex: idx } }) as never;
    expect(cmp(mk(5, 0), mk(1, 1))).toBeLessThan(0);
  });
});
