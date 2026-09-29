/**
 * move 补间方向回归（swap 镜像 bug）：动画起点视觉位置必须在**旧位置**侧，
 * 而不是目标位置镜像（表现为"从目标两侧向中间移动"）。
 */
import { describe, expect, it } from 'vitest';
import { createSvgRenderer } from '../src/render/svg/svg-renderer';
import { capture } from '../src/core/capture';
import { keydiff } from '../src/core/diff';
import { buildTimeline } from '../src/core/timeline';
import { genericRules } from '../src/core/capture';
import { nodeG, svgDoc } from './fixtures';

const a = capture(svgDoc(nodeG(20, 20, '甲', { name: 'M', translate: true })), genericRules);
const b = capture(svgDoc(nodeG(420, 20, '甲', { name: 'M', translate: true })), genericRules);

describe('move 起点方向', () => {
  it('svg 渲染器：补间中元素偏置指向旧位置（translate(-Δ…)），完成后解包', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const r = createSvgRenderer();
    r.mount(host);
    const diff = keydiff(a.spec, b.spec);
    expect(diff.move).toHaveLength(1);
    const timeline = buildTimeline(diff, { opts: { durationMs: 400 } }, 400);
    const p = r.applyDiff(diff, timeline, { to: b as never, animate: true, mode: 'transition' });
    await new Promise((res) => setTimeout(res, 60)); // 补间早期 k≈0.85
    const wrap = b.svg.querySelector('g[transform^="translate(-"]');
    const seen = wrap ? (wrap.getAttribute('transform') ?? '') : '';
    expect(seen, '早期 wrapper 应向旧位置（-Δx）偏置').toMatch(/translate\(-\d+/);
    await p;
    expect(b.svg.querySelector('[data-ta-key]')?.parentElement?.nodeName).not.toBe('g'); // wrapper 已解包
    r.dispose();
  });
});

/* —— 连线随节点拉伸：edge update-morph 与 move 同槽并行 —— */
const swapA = svgDoc(
  nodeG(20, 20, '甲', { name: 'M', translate: true })
  + nodeG(220, 20, '乙', { name: 'N', translate: true })
  + '<g class="edge"><title>M--&gt;N</title><path d="M 100 30 L 220 30" style="stroke:#999"/></g>',
  420, 60);
const swapB = svgDoc(
  nodeG(220, 20, '甲', { name: 'M', translate: true })
  + nodeG(20, 20, '乙', { name: 'N', translate: true })
  + '<g class="edge"><title>M--&gt;N</title><path d="M 300 30 L 20 30" style="stroke:#999"/></g>',
  420, 60);

describe('move+edge morph 同槽联动', () => {
  it('timeline：几何 morph 边并入 move 槽（同 delay/duration）', () => {
    const a2 = capture(swapA, genericRules);
    const b2 = capture(swapB, genericRules);
    const d = keydiff(a2.spec, b2.spec);
    expect(d.move.length).toBe(2); // 两节点
    expect(d.update.filter((u) => u.geom && u.morphable).length).toBe(1); // 边反向非平移 → morph
    const tl = buildTimeline(d, { opts: {} }, 400);
    const edgeIt = tl.items.find((i) => i.cls === 'update' && i.kind === 'edge');
    expect(edgeIt).toBeTruthy();
    const moveIts = tl.items.filter((i) => i.cls === 'move');
    expect(moveIts.every((m) => m.delayMs === edgeIt!.delayMs)).toBe(true);
    expect(edgeIt!.transition.durationMs).toBe(moveIts[0]!.transition.durationMs);
  });

  it('渲染补间中：边端点与节点视觉位置保持固定间隙', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const r = createSvgRenderer();
    r.mount(host);
    const a2 = capture(swapA, genericRules);
    const b2 = capture(swapB, genericRules);
    const d = keydiff(a2.spec, b2.spec);
    const tl = buildTimeline(d, { opts: {} }, 400);
    const p = r.applyDiff(d, tl, { to: b2 as never, animate: true, mode: 'transition' });
    await new Promise((res) => setTimeout(res, 110));
    const edgePath = b2.svg.querySelector('g.edge path')!;
    const dm = /M\s*([\d.]+)/.exec(edgePath.getAttribute('d') ?? '') ?? [];
    const edgeStart = Number(dm[1]);
    const nodeM = b2.svg.querySelector('[data-ta-key$="name:M"]')!;
    const wrapT = nodeM.parentElement!;
    const mm = /translate\((-?[\d.]+)/.exec(wrapT.getAttribute('transform') ?? '') ?? [];
    const nodeVisualX = 220 + Number(mm[1] ?? 0); // 新位置 220 + wrapper 偏移
    void nodeM;
    expect(edgeStart).toBeGreaterThan(101); // 确实在动（起点从 100 向 300）
    expect(edgeStart - nodeVisualX, '边起点−节点左缘 = 间隙(80) 恒定').toBeCloseTo(80, -1);
    await p;
    r.dispose();
  });
});
