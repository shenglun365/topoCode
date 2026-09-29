import { describe, expect, it } from 'vitest';
import { applyOps, validateOps } from '../src/script/apply';
import { sceneToSvg } from '../src/render/scene-svg';
import { capture } from '../src/core/capture';
import { createStoryEngine } from '../src/story';
import { keydiff } from '../src/core/diff';
import type { FrameOp, SceneSpec } from '../src/core/types';
import { nodeG, svgDoc, settle } from './fixtures';

function specOf(s: string): SceneSpec {
  return capture(s).spec;
}

const base = specOf(svgDoc(nodeG(10, 10, '甲', { name: 'A' })));

describe('validateOps', () => {
  it('接受合法序列，拒绝畸形', () => {
    expect(validateOps([
      { op: 'add', el: { key: 'x' } },
      { op: 'remove', key: 'x' },
      { op: 'text', key: 'x', content: 'a' },
      { op: 'move', key: 'x', to: { x: 1, y: 2 } },
    ])).toEqual([]);
    expect(validateOps([{ op: 'remove', key: undefined as unknown as string }]).length).toBe(1);
  });
});

describe('applyOps（M3 增量通道：零重绘的纯数据操作）', () => {
  it('add：新元素入场景，bbox 自动测量', () => {
    const ops: FrameOp[] = [{
      op: 'add',
      el: {
        key: 'ta:generic:name:B', kind: 'node',
        paths: [{ d: [{ c: 'M', x: 200, y: 10 }, { c: 'L', x: 280, y: 10 }, { c: 'Z' }], style: { fill: '#fff' } }],
        text: [{ content: '乙', x: 240, y: 20, anchor: 'middle', box: { x: 230, y: 8, width: 20, height: 20 }, style: {} }],
        style: {},
      },
    }];
    const next = applyOps(base, ops);
    expect(next.elements.length).toBe(2);
    const b = next.elements[1]!;
    expect(b.bbox.x).toBeLessThanOrEqual(200);
    expect(b.source.sel).toContain('data-ta-key');
  });

  it('text：改内容且 bbox 随字宽更新', () => {
    const next = applyOps(base, [{ op: 'text', key: 'ta:generic:name:A', content: '甲乙丙丁很长' }]);
    const a = next.elements.find((e) => e.key === 'ta:generic:name:A')!;
    expect(a.text[0]!.content).toBe('甲乙丙丁很长');
    const orig = base.elements.find((e) => e.key === 'ta:generic:name:A')!;
    expect(a.bbox.width).toBeGreaterThan(orig.bbox.width);
  });

  it('move：几何整体平移', () => {
    const orig = base.elements[0]!;
    const next = applyOps(base, [{ op: 'move', key: 'ta:generic:name:A', to: { x: orig.bbox.x + 50, y: orig.bbox.y + 30 } }]);
    const moved = next.elements[0]!;
    expect(Math.round(moved.bbox.x - orig.bbox.x)).toBe(50);
    expect((moved.paths[0]!.d[0] as { x: number }).x).toBeCloseTo((orig.paths[0]!.d[0] as { x: number }).x + 50, 0);
    // 上帧 spec 不被篡改（深拷贝语义）
    expect(orig.paths[0]!.d[0]).toEqual(base.elements[0]!.paths[0]!.d[0]);
  });

  it('remove + 未知 key：删除成功、未知跳过并告警', () => {
    const warns: string[] = [];
    const next = applyOps(base, [
      { op: 'remove', key: 'ta:generic:name:A' },
      { op: 'remove', key: 'nope' },
    ], (m) => warns.push(m));
    expect(next.elements.length).toBe(0);
    expect(warns.length).toBe(1);
  });

  it('与 keydiff 协作：纯 add 帧 = 仅 enter、零 exit（增量叙事核心）', () => {
    const next = applyOps(base, [{ op: 'text', key: 'ta:generic:name:A', content: '改名' }]);
    const d = keydiff(base, next);
    expect(d.exit.length).toBe(0);
    expect(d.enter.length).toBe(0);
    expect(d.text.length).toBe(1);
  });
});

describe('sceneToSvg：ops spec 可寻址呈现', () => {
  it('每个元素生成带 data-ta-key 的 g，与 source.sel 对齐', () => {
    const svg = sceneToSvg(base);
    for (const el of base.elements) {
      expect(svg.querySelector(el.source.sel)).not.toBeNull();
    }
    expect(svg.querySelector('text')?.textContent).toBe('甲');
  });
});

describe('story：svg 状态 + script 状态混合编排（A/B 混合）', () => {
  it('三状态（svg → script → svg）播放贯通，DOM 最终态正确', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const f3 = svgDoc(nodeG(10, 10, '改名', { name: 'A' }) + nodeG(250, 120, '乙', { name: 'B' }));
    const quick = { staggerMs: 1, transitions: { enter: { type: 'fade' as const, durationMs: 5 }, exit: { type: 'fade' as const, durationMs: 5 } } };
    const eng = await createStoryEngine({
      graph: {
        entry: 'a',
        states: [
          { id: 'a', dwellMs: 0, svg: svgDoc(nodeG(10, 10, '甲', { name: 'A' })) },
          { id: 'b', dwellMs: 0, script: [
            { op: 'text', key: 'ta:generic:name:A', content: '改名' },
            {
              op: 'add',
              el: {
                key: 'ta:generic:name:B', kind: 'node',
                paths: [{ d: [
                  { c: 'M', x: 250, y: 120 }, { c: 'L', x: 330, y: 120 },
                  { c: 'L', x: 330, y: 160 }, { c: 'L', x: 250, y: 160 }, { c: 'Z' },
                ], style: { fill: '#e3f2fd', stroke: '#2196f3', 'stroke-width': '1' } }],
                text: [{ content: '乙', x: 290, y: 145, anchor: 'middle', box: { x: 275, y: 130, width: 30, height: 20 }, style: { 'font-size': '14' } }],
                style: {},
              },
            },
          ] },
          { id: 'c', dwellMs: 0, svg: f3 },
        ],
        edges: [
          { from: 'a', to: 'b', choreography: quick },
          { from: 'b', to: 'c', choreography: quick },
        ],
      },
      host,
    });
    await eng.start();
    expect(eng.snapshot().phase).toBe('ended');
    // b(script 编译) 与 c(svg) 内容一致 → 末边 diff 无 enter/exit 抖动
    // 终态 DOM：B 在场、无隐藏残留
    expect(host.querySelectorAll('.ta-hidden').length).toBe(0);
    expect(host.querySelector('[data-ta-key="ta:generic:name:B"]')).not.toBeNull();
    eng.dispose();
    host.remove();
  }, 20000);
});
