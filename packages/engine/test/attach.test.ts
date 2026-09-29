import { describe, expect, it } from 'vitest';
import { capture } from '../src/core/capture';
import { applyLayout, deepCloneSpec, emptyLayout } from '../src/core/layout';
import { nodeG, svgDoc } from './fixtures';
import type { FrameSource, PathCommand } from '../src/core/types';

// §19.3 D2/D3：边端点吸附——拖节点时连线首/末点钉住节点，另一端保持，线不缩不留缝
const src = (svgStr: string): FrameSource => {
  const c = capture(svgStr);
  const l: FrameSource = { spec: c.spec, svg: c.svg as SVGSVGElement };
  l.raw = l.svg.cloneNode(true) as SVGSVGElement;
  l.rawSpec = deepCloneSpec(l.spec);
  return l;
};

const endp = (d: PathCommand[], head: boolean): { x: number; y: number } => {
  const vs = d.filter((c) => c.c !== 'Z') as Array<{ x: number; y: number }>;
  const p = (head ? vs[0] : vs[vs.length - 1])!;
  return { x: p.x, y: p.y };
};

describe('端点吸附（resolveAttach + attachCommands 贯通 layout）', () => {
  it('endpoints 命中：拖 A 只动线的 A 端，B 端钉住', () => {
    const l = src(svgDoc(
      nodeG(0, 0, '甲', { name: 'A' }) + nodeG(200, 0, '乙', { name: 'B' })
      + `<g class="edge" data-name="A->B"><path d="M 80 20 L 200 20" style="stroke:#999"/></g>`,
    ));
    applyLayout([l], { entities: { 'ta:generic:name:A': { dx: 0, dy: 100 } }, global: { dx: 0, dy: 0 } });
    const edge = l.spec.elements.find((e) => e.kind === 'edge')!;
    expect(endp(edge.paths[0]!.d, true)).toEqual({ x: 80, y: 120 }); // A 端随动
    expect(endp(edge.paths[0]!.d, false)).toEqual({ x: 200, y: 20 }); // B 端不动（旧算法会整线平移）
    // DOM 同步
    const d = l.svg.querySelector('path')!.getAttribute('d')!;
    expect(d).toContain('M 80 120');
    expect(d).toContain('200 20');
  });

  it('几何邻近回退：plantuml 式无 endpoints 消息（line + 箭头 polygon + 标签 text）', () => {
    const l = src(svgDoc(
      `<g class="node" data-name="A"><rect x="18" y="0" width="8" height="200" fill="#000" fill-opacity="0"/></g>`
      + `<g class="node" data-name="B"><rect x="196" y="0" width="8" height="200" fill="#000" fill-opacity="0"/></g>`
      + `<g class="edge"><line x1="26" y1="50" x2="190" y2="50" style="stroke:#181818"/>`
      + `<polygon points="190,44 200,50 190,56" fill="#181818"/>`
      + `<text x="108" y="45" font-size="14">消息</text></g>`,
    ));
    applyLayout([l], { entities: { 'ta:generic:name:A': { dx: 60, dy: 0 } }, global: { dx: 0, dy: 0 } });
    const edge = l.spec.elements.find((e) => e.kind === 'edge')!;
    const line = endp(edge.paths[0]!.d, true);
    expect(line.x).toBeCloseTo(26 + 60, 6); // 起点吸附 A（几何回退）
    const lineEnd = endp(edge.paths[0]!.d, false);
    expect(lineEnd.x).toBeCloseTo(190, 6); // 终点钉住 B 侧
    // 箭头帽在 B 端附近 → paramAlong≈1 → 不跟随 A（旧"求和"会整体搬走）
    const tip = endp(edge.paths[1]!.d, true);
    expect(tip.x).toBeCloseTo(190, 6);
    // 标签随线中点过渡（w≈0.48 → +29 左右）
    expect(edge.text[0]!.x).toBeGreaterThan(26 + 60);
    expect(edge.text[0]!.x).toBeLessThan(190);
    // DOM：line 的 x1 写回
    expect(l.svg.querySelector('line')!.getAttribute('x1')).toBe('86');
  });

  it('两端同幅 → 退化为纯平移（与旧行为兼容）；两端皆零偏移 → 不处置', () => {
    const mk = () => src(svgDoc(
      nodeG(0, 0, '甲', { name: 'A' }) + nodeG(200, 0, '乙', { name: 'B' })
      + `<g class="edge" data-name="A->B"><path d="M 80 20 L 200 20" style="stroke:#999"/></g>`,
    ));
    const both = mk();
    applyLayout([both], { entities: { 'ta:generic:name:A': { dx: 30, dy: 10 }, 'ta:generic:name:B': { dx: 30, dy: 10 } }, global: { dx: 0, dy: 0 } });
    const d0 = both.spec.elements.find((e) => e.kind === 'edge')!.paths[0]!.d;
    expect(endp(d0, true)).toEqual({ x: 110, y: 30 });
    expect(endp(d0, false)).toEqual({ x: 230, y: 30 });
    const none = mk();
    applyLayout([none], emptyLayout());
    const dn = none.spec.elements.find((e) => e.kind === 'edge')!.paths[0]!.d;
    expect(endp(dn, true)).toEqual({ x: 80, y: 20 });
  });

  it('折线 segment 传播：首折角全额跟随、中段按弧长过渡、末段钉住（正交边保持）', () => {
    const l = src(svgDoc(
      nodeG(0, 0, '甲', { name: 'A' }) + nodeG(200, 200, '乙', { name: 'B' })
      + `<g class="edge" data-name="A->B"><path d="M 80 20 L 140 20 L 140 220 L 240 220" style="stroke:#999"/></g>`,
    ));
    applyLayout([l], { entities: { 'ta:generic:name:A': { dx: 0, dy: -60 } }, global: { dx: 0, dy: 0 } });
    const d = l.spec.elements.find((e) => e.kind === 'edge')!.paths[0]!.d;
    expect(endp(d, false)).toEqual({ x: 240, y: 220 }); // 终点钉 B
    // v0,v1（首段）全额 -60；末点 0；中段弧长过渡
    const vs = d.filter((c) => c.c !== 'Z') as Array<{ x: number; y: number }>;
    expect(vs[1]!.y).toBeCloseTo(-40, 6); // 首段两顶点全额跟随（保持水平正交）
    expect(vs[2]!.y).toBeCloseTo(220, 6); // 末段两顶点钉住 B 侧
    expect(vs[1]!.x).toBeCloseTo(140, 6);
  });

  it('多次 relayout 幂等（从 raw 重建，不叠加）', () => {
    const l = src(svgDoc(
      nodeG(0, 0, '甲', { name: 'A' }) + nodeG(200, 0, '乙', { name: 'B' })
      + `<g class="edge" data-name="A->B"><path d="M 80 20 L 200 20" style="stroke:#999"/></g>`,
    ));
    const ov = { entities: { 'ta:generic:name:A': { dx: 50, dy: 0 } }, global: { dx: 0, dy: 0 } };
    applyLayout([l], ov);
    const once = JSON.stringify(l.spec.elements.find((e) => e.kind === 'edge')!.paths[0]!.d);
    applyLayout([l], ov);
    expect(JSON.stringify(l.spec.elements.find((e) => e.kind === 'edge')!.paths[0]!.d)).toBe(once);
    applyLayout([l], emptyLayout());
    expect(endp(l.spec.elements.find((e) => e.kind === 'edge')!.paths[0]!.d, true)).toEqual({ x: 80, y: 20 });
    expect(l.svg.querySelectorAll('g[data-ta-offset]').length).toBe(0);
  });
});
