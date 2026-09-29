import { describe, expect, it } from 'vitest';
import {
  createStoryEngine, topoOrder,
  type Plan, type PlanRenderer, type ScenePlanCompiler, type StateGraphSpec,
} from '../src/story';
import { nodeG, svgDoc } from './fixtures';

const big = (x: number, y: number, w: number, h: number, name: string): string =>
  `<g class="node" data-name="${name}"><rect x="${x}" y="${y}" width="${w}" height="${h}" style="fill:#fff;stroke:#999"/></g>`;

const stateA = svgDoc(big(0, 0, 400, 200, 'S') + nodeG(20, 20, '甲', { name: 'A' }) + nodeG(120, 20, '乙', { name: 'B' }), 420, 220);
const stateB = svgDoc(big(0, 0, 400, 200, 'S') + nodeG(20, 20, '甲', { name: 'A' }) + nodeG(170, 20, '乙', { name: 'B' }), 420, 220);

function spyRenderer(): PlanRenderer & { plans: Plan[]; snaps: string[]; applySnapshot(s: { id: string }): void } {
  const plans: Plan[] = [];
  const snaps: string[] = [];
  return {
    plans,
    snaps,
    mount() { /* noop */ },
    async applyPlan(p) { plans.push(p); },
    applySnapshot(s) { snaps.push(s.id); },
    dispose() { /* noop */ },
  };
}

const chainGraph: StateGraphSpec = {
  entry: 'a',
  states: [{ id: 'a', dwellMs: 0, svg: stateA }, { id: 'b', dwellMs: 0, svg: stateB }],
  edges: [{ from: 'a', to: 'b' }],
};

describe('StoryEngine（P1 管线贯通）', () => {
  it('链图：entry 全 enter；容器锚下真实位移呈 move；anchorKind=container', async () => {
    const host = document.createElement('div');
    const rd = spyRenderer();
    const eng = await createStoryEngine({ graph: chainGraph, host, renderer: rd });
    await eng.start();
    expect(rd.plans.map((p) => p.to)).toEqual(['a', 'b']);
    const count = (p: Plan, act: string): number => p.steps.filter((s) => s.action === act).length;
    expect(count(rd.plans[0]!, 'enter')).toBe(3); // S/A/B 入场
    expect(count(rd.plans[1]!, 'move')).toBe(1);  // B 真实 +50（A/S 钉住）
    expect(count(rd.plans[1]!, 'enter')).toBe(0);
    expect(eng.layoutInfo()?.anchorKind).toBe('container');
    eng.dispose();
  });

  it('committed 变更 → 自动 relayout（跨状态共享偏移）+ 边缓存失效 + 当前状态刷新', async () => {
    const rd = spyRenderer();
    const eng = await createStoryEngine({ graph: chainGraph, host: document.createElement('div'), renderer: rd });
    await eng.start(); // 停在 b
    expect(eng.scheduler.snapshot.nodeId).toBe('b');
    const before = eng.scenes.get('a')!.spec.elements.find((e) => e.key === 'ta:generic:name:A')!.bbox.x;
    eng.store.position.setDraft('ta:generic:name:A', { dx: 40, dy: 0 });
    eng.store.position.commitDraft(); // subscribe → relayout
    const afterA = eng.scenes.get('a')!.spec.elements.find((e) => e.key === 'ta:generic:name:A')!.bbox.x;
    const afterB = eng.scenes.get('b')!.spec.elements.find((e) => e.key === 'ta:generic:name:A')!.bbox.x;
    expect(afterA - before).toBeCloseTo(40, 6);
    expect(afterB - afterA).toBeCloseTo(0, 6); // 同实体跨状态同位（B 移动场景下 relayout 语义仍一致）
    expect((eng.compiler as ScenePlanCompiler).stats().edges).toBe(0);
    expect(rd.snaps).toContain('b'); // 当前显示状态静态刷新
    // draft 不触发 relayout/不污染 committed 持久层
    eng.store.position.setDraft('ta:generic:name:B', { dx: 10, dy: 10 });
    const beforeEdges = (eng.compiler as ScenePlanCompiler).stats().edges;
    eng.store.position.discardDraft();
    expect(eng.scenes.get('a')!.spec.elements.find((e) => e.key === 'ta:generic:name:B')).toBeDefined();
    expect((eng.compiler as ScenePlanCompiler).stats().edges).toBe(beforeEdges);
    eng.dispose();
  });

  it('script 状态：ops 基底 = 拓扑前驱，add 呈 enter', async () => {
    const graph: StateGraphSpec = {
      entry: 'a',
      states: [
        { id: 'a', dwellMs: 0, svg: stateA },
        {
          id: 'b',
          dwellMs: 0,
          script: [{
            op: 'add',
            el: {
              key: 'ta:generic:name:C', kind: 'node',
              paths: [{ d: [{ c: 'M', x: 250, y: 30 }, { c: 'L', x: 330, y: 30 }, { c: 'L', x: 330, y: 70 }, { c: 'L', x: 250, y: 70 }, { c: 'Z' }], style: { fill: '#e8f5e9', stroke: '#4caf50' } }],
              text: [], style: {},
            },
          }],
        },
      ],
      edges: [{ from: 'a', to: 'b' }],
    };
    const rd = spyRenderer();
    const eng = await createStoryEngine({ graph, host: document.createElement('div'), renderer: rd });
    await eng.start();
    const planB = rd.plans.find((p) => p.to === 'b')!;
    const enters = planB.steps.filter((s) => s.action === 'enter');
    expect(enters.map((s) => s.key)).toContain('ta:generic:name:C');
    eng.dispose();
  });

  it('topoOrder：BFS 自 entry，不可达状态殿后', () => {
    const g: StateGraphSpec = {
      entry: 'a',
      states: [{ id: 'z', dwellMs: 0, svg: stateA }, { id: 'a', dwellMs: 0, svg: stateA }, { id: 'b', dwellMs: 0, svg: stateB }, { id: 'c', dwellMs: 0, svg: stateB }],
      edges: [{ from: 'a', to: 'b' }, { from: 'b', to: 'c' }],
    };
    expect(topoOrder(g)).toEqual(['a', 'b', 'c', 'z']);
  });

});

describe('StoryEngine 整图偏移（C2 global 两层）', () => {
  it('commitDraftGlobal 触发 relayout：全状态同幅平移、committed 独立入快照', async () => {
    const eng = await createStoryEngine({ graph: chainGraph, host: document.createElement('div'), renderer: spyRenderer() });
    await eng.start();
    const before = eng.scenes.get('a')!.spec.elements.find((e) => e.key === 'ta:generic:name:A')!.bbox.x;
    eng.store.position.setDraftGlobal({ dx: 50, dy: 0 });
    eng.store.position.commitDraftGlobal(); // snapshot 变化 → 自动 relayout
    const after = eng.scenes.get('a')!.spec.elements.find((e) => e.key === 'ta:generic:name:A')!.bbox.x;
    expect(after - before).toBeCloseTo(50, 6);
    const snap = eng.store.position.snapshot();
    expect(snap.global).toEqual({ dx: 50, dy: 0 });
    // draft 不触发布局
    const b0 = eng.scenes.get('b')!.spec.elements.find((e) => e.key === 'ta:generic:name:A')!.bbox.x;
    eng.store.position.setDraftGlobal({ dx: 30, dy: 0 });
    expect(eng.scenes.get('b')!.spec.elements.find((e) => e.key === 'ta:generic:name:A')!.bbox.x).toBeCloseTo(b0, 6);
    eng.dispose();
  });
});
