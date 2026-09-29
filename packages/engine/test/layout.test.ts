import { describe, expect, it } from 'vitest';
import { capture } from '../src/core/capture';
import {
  applyLayout, baseKeyOf, containerShifts, deepCloneSpec, emptyLayout, hitTestAnchor,
  type LayoutOverrides,
} from '../src/core/layout';
import { nodeG, svgDoc } from './fixtures';
import type { FrameSource } from '../src/core/types';

function edgeAB(x1: number, y1: number, x2: number, y2: number): string {
  return `<g class="edge" data-name="A->B"><path d="M ${x1} ${y1} L ${x2} ${y2}" style="stroke:#999;stroke-width:1"/></g>`;
}

function frameSource(svgStr: string): FrameSource {
  const cap = capture(svgStr);
  const src: FrameSource = { spec: cap.spec, svg: cap.svg as SVGSVGElement };
  src.raw = src.svg.cloneNode(true) as SVGSVGElement;
  src.rawSpec = deepCloneSpec(src.spec);
  return src;
}

const el = (l: FrameSource, name: string) => l.spec.elements.find((e) => e.key === `ta:generic:name:${name}`)!;

describe('applyLayout —— 统一画布', () => {
  it('viewBox 对称、style 盒同步，多帧盒完全一致', () => {
    const a = frameSource(svgDoc(nodeG(0, 0, '甲', { name: 'A' }), 214, 218));
    const b = frameSource(svgDoc(nodeG(0, 0, '甲', { name: 'A' }) + nodeG(300, 200, '乙', { name: 'B' }), 420, 300));
    const info = applyLayout([a, b], emptyLayout());
    expect(info.half).toBeGreaterThan(200);
    const size = String(info.half * 2);
    for (const l of [a, b]) {
      expect(l.svg.getAttribute('viewBox')).toBe(`${-info.half} ${-info.half} ${size} ${size}`);
      expect((l.svg as SVGElement).style.width).toBe(`${size}px`);
      expect(l.spec.origin).toEqual({ x: -info.half, y: -info.half });
    }
  });

  it('首帧锁定进 shift 列表：frame0 零、frame1 反向 Δ', () => {
    const a = frameSource(svgDoc(nodeG(0, 0, '甲', { name: 'A' }) + nodeG(100, 0, '乙', { name: 'B' })));
    const b = frameSource(svgDoc(nodeG(30, 10, '甲', { name: 'A' }) + nodeG(130, 10, '乙', { name: 'B' })));
    const info = applyLayout([a, b], emptyLayout());
    expect(info.shifts[0]).toEqual({ dx: 0, dy: 0 });
    expect(info.shifts[1]).toEqual({ dx: -30, dy: -10 });
    expect(el(b, 'A').bbox.x).toBeCloseTo(-30 + 30, 6);
  });
});

describe('LayoutOverrides —— 实体偏移（跨帧共享）+ 边跟随', () => {
  const twoFrames = (): [FrameSource, FrameSource] => [
    frameSource(svgDoc(nodeG(0, 0, '甲', { name: 'A' }) + nodeG(200, 0, '乙', { name: 'B' }) + edgeAB(80, 20, 200, 20))),
    frameSource(svgDoc(nodeG(10, 0, '甲', { name: 'A' }) + nodeG(210, 0, '乙', { name: 'B' }) + edgeAB(90, 20, 210, 20) + nodeG(300, 100, '丙', { name: 'C' }))),
  ];

  it('同一 id 在所有帧共享偏移；端点相连的边跟随', () => {
    const [a, b] = twoFrames();
    const ov: LayoutOverrides = { entities: { 'ta:generic:name:A': { dx: 40, dy: 15 } }, global: { dx: 0, dy: 0 } };
    applyLayout([a, b], ov);
    // frame0 无锁定；A 首帧 = 原始 +40；frame1 锁定 -10 后回到首帧位，再 +40
    expect(el(a, 'A').bbox.x).toBeCloseTo(40, 6);
    expect(el(b, 'A').bbox.x).toBeCloseTo(40, 6);
    // 边 endpoints 含 A → 跟随
    const edge = b.spec.elements.find((e) => e.kind === 'edge')!;
    expect(edge.bbox.x).toBeCloseTo(90 - 10 + 40, 6);
    // B 不受影响
    expect(el(b, 'B').bbox.x).toBeCloseTo(200, 6);
    // DOM：A 节点被 offset wrapper 包裹
    expect(b.svg.querySelector('g[data-ta-offset]')).not.toBeNull();
  });

  it('两端都被拖的边：端点吸附（首点随 from、末点随 to，不再整体平移求和）', () => {
    const [a] = twoFrames();
    applyLayout([a], {
      entities: { 'ta:generic:name:A': { dx: 10, dy: 0 }, 'ta:generic:name:B': { dx: -6, dy: 4 } },
      global: { dx: 0, dy: 0 },
    });
    const edge = a.spec.elements.find((e) => e.kind === 'edge')!;
    const d = edge.paths[0]!.d;
    expect(d[0]!.c === 'M' && d[0]!.x).toBeCloseTo(80 + 10, 6); // 起点吸附 A 新位
    const last = d[d.length - 1]!;
    expect(last.c === 'L' && last.x).toBeCloseTo(200 - 6, 6); // 终点吸附 B 新位
    expect(last.c === 'L' && last.y).toBeCloseTo(20 + 4, 6);
  });

  it('global 偏移 = 整图平移（所有帧同幅，diff 关系不变）', () => {
    const [a, b] = twoFrames();
    applyLayout([a, b], { entities: {}, global: { dx: 55, dy: 0 } });
    expect(el(a, 'A').bbox.x).toBeCloseTo(55, 6);
    expect(el(b, 'A').bbox.x).toBeCloseTo(55, 6);
    expect(el(b, 'C').bbox.x).toBeCloseTo(300 - 10 + 55, 6); // 新实体随本帧锁定平移
  });

  it('幂等重建：反复改偏移/复位不叠加、不残留 wrapper', () => {
    const [a, b] = twoFrames();
    const base = applyLayout([a, b], emptyLayout());
    const x0 = el(b, 'A').bbox.x;
    applyLayout([a, b], { entities: { 'ta:generic:name:A': { dx: 99, dy: 0 } }, global: { dx: 12, dy: 12 } });
    expect(el(b, 'A').bbox.x).toBeCloseTo(x0 + 99 + 12, 6);
    const back = applyLayout([a, b], emptyLayout());
    expect(el(b, 'A').bbox.x).toBeCloseTo(x0, 6);
    expect(back.shifts[1]!.dx).toBeCloseTo(base.shifts[1]!.dx, 6);
    expect(b.svg.querySelectorAll('g[data-ta-offset]').length).toBe(0);
    // 锁定 wrapper 常驻（frame1 有 -10 平移），offset wrapper 已全部清除
    expect(b.svg.querySelector('g[data-ta-align]')).not.toBeNull();
    expect(a.svg.querySelector('g[data-ta-align]')).toBeNull();
  });

  it('canvasHalf 计入实体/全局偏移：拉出不裁切', () => {
    const [a, b] = twoFrames();
    const plain = applyLayout([a, b], emptyLayout());
    const grown = applyLayout([a, b], { entities: { 'ta:generic:name:C': { dx: 0, dy: 400 } }, global: { dx: 0, dy: 0 } });
    expect(grown.half).toBeGreaterThan(plain.half);
  });
});

describe('命中测试（热更新覆盖见 story-engine.test）', () => {
  it('hitTestAnchor + baseKeyOf：位置编辑 UI 命中语义', () => {
    const a = frameSource(svgDoc(nodeG(0, 0, '甲', { name: 'A' }) + nodeG(5, 5, '小', { name: 'S' }), 400, 400));
    const hit = hitTestAnchor(a.spec, { x: 2, y: 2 });
    expect(hit).not.toBeNull();
    expect(baseKeyOf(hit!.key)).toBe('ta:generic:name:A');
    expect(baseKeyOf('ta:plantuml:label:edge:A->B#2')).toBe('ta:plantuml:label:edge:A->B');
  });

  it('hitTestAnchor：节点未命中时落点命中边（可直接拖边）', () => {
    const f = frameSource(svgDoc(nodeG(0, 0, '甲', { name: 'A' }) + nodeG(200, 0, '乙', { name: 'B' }) + edgeAB(80, 20, 200, 20)));
    const hit = hitTestAnchor(f.spec, { x: 140, y: 20 });
    expect(hit?.key).toBe('ta:generic:name:A~B');
    expect(hit?.distance).toBe(0);
  });
});

/* ---------- P1a：容器锚（§19.3 内在锚①，修复中位数被多数真实移动劫持） ---------- */

const big = (x: number, y: number, w: number, h: number, name: string): string =>
  `<g class="node" data-name="${name}"><rect x="${x}" y="${y}" width="${w}" height="${h}" style="fill:#fff;stroke:#999"/></g>`;
const cellX = (l: FrameSource, name: string): number =>
  l.spec.elements.find((e) => e.key === `ta:generic:name:${name}`)!.bbox.x;

describe('containerShifts —— 容器锚（画布盒=坐标系）', () => {
  // f2 中 A/B/C 全体真实右移 50（cluster 不动）：中位数会误抵消，容器锚如实保留
  const driftCells = (): [FrameSource, FrameSource] => [
    frameSource(svgDoc(big(0, 0, 400, 200, 'S') + nodeG(20, 20, '甲', { name: 'A' }) + nodeG(120, 20, '乙', { name: 'B' }) + nodeG(220, 20, '丙', { name: 'C' }), 420, 220)),
    frameSource(svgDoc(big(0, 0, 400, 200, 'S') + nodeG(70, 20, '甲', { name: 'A' }) + nodeG(170, 20, '乙', { name: 'B' }) + nodeG(270, 20, '丙', { name: 'C' }), 420, 220)),
  ];

  it('容器稳定：真实移动不被抵消（对比 median 链误判）', () => {
    const [a, b] = driftCells();
    const info = applyLayout([a, b], emptyLayout());
    expect(info.anchorKind).toBe('container');
    expect(info.containerKey).toBe('ta:generic:name:S');
    expect(cellX(b, 'A')).toBeCloseTo(70, 6); // 如实 +50 → 呈 move
    expect(info.shifts[1]).toEqual({ dx: 0, dy: 0 });
    const [a2, b2] = driftCells();
    applyLayout([a2, b2], emptyLayout(), { anchor: 'median' });
    expect(cellX(b2, 'A')).toBeCloseTo(20, 6); // 旧行为：被中位数 -50 拉回（缺陷对照）
  });

  it('画布漂移（容器+内容同幅平移）：容器锚全消，零 move', () => {
    const a = frameSource(svgDoc(big(0, 0, 400, 200, 'S') + nodeG(20, 20, '甲', { name: 'A' }), 420, 220));
    const b = frameSource(svgDoc(big(40, 0, 400, 200, 'S') + nodeG(60, 20, '甲', { name: 'A' }), 460, 220));
    const info = applyLayout([a, b], emptyLayout());
    expect(info.shifts[1]).toEqual({ dx: -40, dy: 0 });
    expect(cellX(b, 'A')).toBeCloseTo(20, 6);
  });

  it('面积门槛：未包住内容(≥50%)的节点不配当画布 → 退回 median；refKey 可豁免', () => {
    const a = frameSource(svgDoc(nodeG(0, 0, '甲', { name: 'A' }) + nodeG(100, 0, '乙', { name: 'B' }), 400, 200));
    const b = frameSource(svgDoc(nodeG(30, 0, '甲', { name: 'A' }) + nodeG(130, 0, '乙', { name: 'B' }), 400, 200));
    expect(containerShifts([a.rawSpec!, b.rawSpec!])).toBeNull();
    const info = applyLayout([a, b], emptyLayout());
    expect(info.anchorKind).toBe('median');
    expect(cellX(b, 'A')).toBeCloseTo(0, 6); // median 吸收刚性 +30
    const [c, d] = [
      frameSource(svgDoc(nodeG(0, 0, '甲', { name: 'A' }) + nodeG(100, 0, '乙', { name: 'B' }), 400, 200)),
      frameSource(svgDoc(nodeG(30, 0, '甲', { name: 'A' }) + nodeG(180, 0, '乙', { name: 'B' }), 400, 200)),
    ];
    applyLayout([c, d], emptyLayout(), { refKey: 'ta:generic:name:A' });
    expect(cellX(d, 'A')).toBeCloseTo(0, 6);   // ref 钉 A
    expect(cellX(d, 'B')).toBeCloseTo(150, 6); // B 真实 +50 如实保留（median 会被 +30 拉回 120）
  });

  it('单帧图：anchorKind none；mermaid cluster 回归（真实键 ta:mermaid:name:S）', () => {
    const a = frameSource(svgDoc(big(0, 0, 100, 100, 'Solo'), 120, 120));
    expect(applyLayout([a], emptyLayout()).anchorKind).toBe('none');
  });
});
