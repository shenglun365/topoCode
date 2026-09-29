import { describe, expect, it } from 'vitest';
import { capture } from '../src/core/capture';
import { keydiff } from '../src/core/diff';
import { buildTimeline } from '../src/core/timeline';
import { createSvgRenderer } from '../src/render/svg/svg-renderer';
import { svgDoc } from './fixtures';

// mermaid 风格：节点位移在 g 的 transform 属性上，子形状为局部坐标
function mNode(x: number, y: number, label: string): string {
  return `<g class="node" transform="translate(${x} ${y})">`
    + `<rect width="80" height="40" style="fill:#e3f2fd;stroke:#2196f3;stroke-width:1"/>`
    + `<text x="40" y="25" text-anchor="middle" font-size="14">${label}</text></g>`;
}

const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

describe('enter-scale 回归：CSS transform 不得覆盖引擎属性位移（坑 #23）', () => {
  it('带 transform 属性的节点入场：元素本体零内联样式，wrapper 承载缩放且终态解包', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const renderer = createSvgRenderer();
    renderer.mount(host);

    const c1 = capture(svgDoc(mNode(10, 10, 'A')));
    const c2 = capture(svgDoc(mNode(10, 10, 'A') + mNode(200, 120, 'B')));
    const from = { spec: c1.spec, svg: c1.svg as SVGSVGElement };
    const to = { spec: c2.spec, svg: c2.svg as SVGSVGElement };
    const diff = keydiff(from.spec, to.spec);
    expect(diff.enter.length).toBe(1);
    const bKey = diff.enter[0]!.key;
    const timeline = buildTimeline(diff, { opts: { transitions: { enter: { type: 'scale', durationMs: 300 } } } }, 600);

    renderer.setFrame(from);
    const done = renderer.applyDiff(diff, timeline, { from, to, animate: true, mode: 'transition', speed: 1 });

    await wait(150);
    const bNode = to.svg.querySelector(`[data-ta-key="${bKey}"]`)!;
    // 核心断言：元素自身 transform 属性保持引擎原值，无内联 style.transform
    expect(bNode.getAttribute('transform')).toBe('translate(200 120)');
    expect((bNode as SVGElement).style.transform).toBe('');
    // 动画由临时 wrapper 承载（缩放围绕全局 bbox 中心）
    const wrapper = bNode.parentElement as Element;
    expect(wrapper.tagName.toLowerCase()).toBe('g');
    expect(wrapper.getAttribute('transform') ?? '').toContain('scale(');

    await done;
    // 终态：wrapper 已解包、无残留
    expect(bNode.parentElement).toBe(to.svg);
    expect(wrapper.isConnected).toBe(false);
    expect(bNode.getAttribute('transform')).toBe('translate(200 120)');
    expect(to.svg.querySelectorAll('.ta-el, .ta-hidden').length).toBe(0);
    renderer.dispose();
  });
});
