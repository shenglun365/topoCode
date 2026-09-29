import { describe, expect, it } from 'vitest';
import { capture } from '../src/core/capture';
import { keydiff } from '../src/core/diff';
import { lockShifts } from '../src/core/layout';
import { shiftSpec } from '../src/core/align';
import { createStoryEngine, storyStaticSvg, type Plan, type PlanRenderer, type ScenePlanPayload } from '../src/story';
import type { LayoutOptions } from '../src/core/layout';
import { nodeG, svgDoc } from './fixtures';

const specOf = (s: string) => capture(s).spec;

describe('lockShifts —— 帧级首帧刚性锁定', () => {
  it('刚性重排：共享实体首帧位置为准，对齐后全 stay 零 move', () => {
    const prev = specOf(svgDoc(nodeG(10, 10, '甲', { name: 'A' }) + nodeG(200, 10, '乙', { name: 'B' })));
    const next = specOf(svgDoc(nodeG(47, 22, '甲', { name: 'A' }) + nodeG(237, 22, '乙', { name: 'B' })
      + nodeG(120, 150, '丙', { name: 'C' })));
    const shifts = lockShifts([prev, next]);
    expect(Math.round(shifts[1]!.dx)).toBe(-37);
    expect(Math.round(shifts[1]!.dy)).toBe(-12);
    shiftSpec(next, shifts[1]!.dx, shifts[1]!.dy);
    const d = keydiff(prev, next);
    expect(d.move.length).toBe(0);
    expect(d.exit.length).toBe(0);
    expect(d.stay.length).toBe(2);
    expect(d.enter.map((e) => e.key)).toEqual(['ta:generic:name:C']);
  });

  it('共享实体 <2：不移动（无法定义坐标系）', () => {
    const prev = specOf(svgDoc(nodeG(0, 0, '甲', { name: 'A' })));
    const next = specOf(svgDoc(nodeG(90, 90, '乙', { name: 'B' })));
    expect(lockShifts([prev, next])[1]).toEqual({ dx: 0, dy: 0 });
  });

  it('三帧链：每帧直接对「各自首帧位置」锁定，零累积漂移', () => {
    const f1 = specOf(svgDoc(nodeG(0, 0, '甲', { name: 'A' }) + nodeG(100, 0, '乙', { name: 'B' })));
    const f2 = specOf(svgDoc(nodeG(20, 0, '甲', { name: 'A' }) + nodeG(120, 0, '乙', { name: 'B' }) + nodeG(0, 100, '丙', { name: 'C' })));
    const f3 = specOf(svgDoc(nodeG(40, 0, '甲', { name: 'A' }) + nodeG(140, 0, '乙', { name: 'B' }) + nodeG(20, 100, '丙', { name: 'C' })));
    const s = lockShifts([f1, f2, f3]);
    expect(s[1]!.dx).toBeCloseTo(-20, 6);
    expect(s[2]!.dx).toBeCloseTo(-40, 6); // A/B 众数胜（-40），C 的 -20 被中位数吸收
    // 锁定后：A 恒在 0；C 归一后与其首帧(归一)位置一致
    shiftSpec(f3, s[2]!.dx, s[2]!.dy);
    const c3 = f3.elements.find((e) => e.key === 'ta:generic:name:C')!;
    expect(c3.bbox.x).toBeCloseTo(-20, 6); // = f2 归一后 -20
  });

  it('中位数抗离群：单元素局部重排不污染估计', () => {
    const f1 = specOf(svgDoc(
      nodeG(0, 0, 'A', { name: 'A' }) + nodeG(100, 0, 'B', { name: 'B' })
      + nodeG(200, 0, 'C', { name: 'C' }) + nodeG(300, 0, 'D', { name: 'D' }),
      600, 200,
    ));
    // A/C/D 右移 20；B 异常右移 500
    const f2 = specOf(svgDoc(
      nodeG(20, 0, 'A', { name: 'A' }) + nodeG(600, 0, 'B', { name: 'B' })
      + nodeG(220, 0, 'C', { name: 'C' }) + nodeG(320, 0, 'D', { name: 'D' }),
      700, 200,
    ));
    const s = lockShifts([f1, f2]);
    expect(s[1]!.dx).toBeCloseTo(-20, 6); // 中位数 = -20（B 的 -500 被忽略）
    shiftSpec(f2, s[1]!.dx, s[1]!.dy);
    const d = keydiff(f1, f2);
    expect(d.move.length).toBe(1); // 仅离群者 B 如实呈为 move
    expect(d.move[0]!.key).toBe('ta:generic:name:B');
  });
});

describe('story 链图位置锁定集成（线性 = 图特例）', () => {
  async function mkGraph(shift: { x: number; y: number }, layout?: LayoutOptions) {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const f1 = svgDoc(nodeG(10, 10, '甲', { name: 'A' }) + nodeG(200, 10, '乙', { name: 'B' }));
    const f2 = svgDoc(nodeG(10 + shift.x, 10 + shift.y, '甲', { name: 'A' })
      + nodeG(200 + shift.x, 10 + shift.y, '乙', { name: 'B' }));
    const plans: Plan[] = [];
    const rd: PlanRenderer = {
      mount() { /* noop */ },
      async applyPlan(p) { plans.push(p); },
      dispose() { /* noop */ },
    };
    const eng = await createStoryEngine({
      graph: {
        entry: 'a',
        states: [{ id: 'a', dwellMs: 0, svg: f1 }, { id: 'b', dwellMs: 0, svg: f2 }],
        edges: [{ from: 'a', to: 'b' }],
      },
      host, renderer: rd, layout,
    });
    await eng.start();
    return { eng, plans, host };
  }
  const diffOf = (p: Plan): ScenePlanPayload => p.payload as ScenePlanPayload;

  it('默认锁定：漂移 20px 被吸收 → 零 move，同实体两态同位', async () => {
    const { eng, plans } = await mkGraph({ x: 20, y: 20 });
    const d = diffOf(plans[1]!).diff;
    expect(d.move.length).toBe(0);
    expect(d.stay.length).toBe(2);
    const a0 = eng.scenes.get('a')!.spec.elements.find((e) => e.key === 'ta:generic:name:A')!;
    const a1 = eng.scenes.get('b')!.spec.elements.find((e) => e.key === 'ta:generic:name:A')!;
    expect(Math.abs(a0.bbox.x - a1.bbox.x)).toBeLessThan(0.01);
    expect(Math.abs(a0.bbox.y - a1.bbox.y)).toBeLessThan(0.01);
    // DOM 侧 align wrapper 存在；静态导出剥属性留几何
    const wrapper = eng.scenes.get('b')!.svg.querySelector('g[data-ta-align]');
    expect(wrapper).toBeTruthy();
    expect(wrapper!.getAttribute('transform') ?? '').toContain('translate(');
    const out = storyStaticSvg(eng, 'b');
    expect(out).not.toContain('data-ta-align');
    expect(out).toContain('translate(');
    eng.dispose();
  });

  it("anchor:'none'：漂移如实呈为 move，直出后端坐标", async () => {
    const { eng, plans } = await mkGraph({ x: 20, y: 0 }, { anchor: 'none' });
    const d = diffOf(plans[1]!).diff;
    expect(d.move.length).toBe(2);
    expect(eng.layoutInfo()?.anchorKind).toBe('none');
    expect(eng.scenes.get('b')!.svg.querySelector('g[data-ta-align]')).toBeNull();
    eng.dispose();
  });

  it('播放贯通：真实渲染器播完无残留', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const f1 = svgDoc(nodeG(10, 10, '甲', { name: 'A' }) + nodeG(230, -5, '乙', { name: 'B' }));
    const f2 = svgDoc(nodeG(40, 10, '甲', { name: 'A' }) + nodeG(230, -5, '乙', { name: 'B' }));
    const eng = await createStoryEngine({
      graph: {
        entry: 'a',
        states: [{ id: 'a', dwellMs: 0, svg: f1 }, { id: 'b', dwellMs: 0, svg: f2 }],
        edges: [{
          from: 'a', to: 'b',
          choreography: { durationMs: 60, staggerMs: 1, transitions: { enter: { type: 'fade', durationMs: 10 } } },
        }],
      },
      host,
    });
    await eng.start();
    expect(eng.snapshot().phase).toBe('ended');
    expect(host.querySelectorAll('.ta-hidden, .ta-el').length).toBe(0);
    eng.dispose();
    host.remove();
  }, 15000);
});
