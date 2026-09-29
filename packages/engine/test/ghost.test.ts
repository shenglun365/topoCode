import { describe, expect, it } from 'vitest';
import { capture } from '../src/core/capture';
import { keydiff } from '../src/core/diff';
import { buildTimeline } from '../src/core/timeline';
import { createSvgRenderer } from '../src/render/svg/svg-renderer';
import { mermaidRules } from '../src/backends';
import { svgDoc } from './fixtures';

// 坑 #30：text-only 鬼影整元素存活 → subgraph 黄色框（mermaid 默认 rgba(255,255,204,.66)）
// 以 z2 遮罩新帧内容直至 detachGhost（≈1s）。修复：text 鬼影只保留文字，形状隐藏。
const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

const clusterSvg = (title: string): string => svgDoc(
  `<g class="cluster" id="S">`
  + `<rect x="10" y="10" width="300" height="120" fill="rgba(255,255,204,.66)"/>`
  + `<text x="40" y="30" font-size="14">${title}</text>`
  + `<foreignObject x="40" y="40" width="200" height="30"><div xmlns="http://www.w3.org/1999/xhtml">${title}</div></foreignObject>`
  + `</g>`, 360, 160);

describe('text-only 鬼影 —— 不得以形状遮罩新帧（坑 #30）', () => {
  it('文本变化帧：旧框体立即隐藏，旧文字/foreignObject 参与交叉淡出，detach 后可复用', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const renderer = createSvgRenderer();
    renderer.mount(host);

    const c1 = capture(clusterSvg('初始: [5, 3, 8]'), mermaidRules);
    const c2 = capture(clusterSvg('步骤1: [3, 5, 8]'), mermaidRules);
    const from = { spec: c1.spec, svg: c1.svg as SVGSVGElement };
    const to = { spec: c2.spec, svg: c2.svg as SVGSVGElement };
    const diff = keydiff(from.spec, to.spec);
    expect(diff.exit.length).toBe(0);
    expect(diff.text.length).toBe(1); // 同键仅文本变 → textCross
    const timeline = buildTimeline(diff, { opts: {} }, 300);

    renderer.setFrame(from);
    const done = renderer.applyDiff(diff, timeline, { from, to, animate: true, mode: 'reveal', speed: 1 });
    await wait(30);

    const ghostRect = c1.svg.querySelector('rect') as SVGElement;
    expect(ghostRect.style.display).toBe('none'); // 黄框已隐藏，不再遮罩
    const ghostFo = c1.svg.querySelector('foreignObject') as SVGElement;
    expect(ghostFo.classList.contains('ta-el')).toBe(true); // 旧文字在淡出通道内
    expect(c1.svg.querySelector('g[data-ta-ghost]')).not.toBeNull();

    await done;
    // detach 后 FrameSource 干净：形状 display 已恢复、无 ghost 标记
    expect((c1.svg.querySelector('rect') as SVGElement).style.display).toBe('');
    expect(host.querySelectorAll('[data-ta-ghost]').length).toBe(0);
    // 旧帧可原样重挂载播放（复位/回看不残留遮罩状态）
    renderer.setFrame(from);
    expect((c1.svg.querySelector('rect') as SVGElement).style.display).toBe('');
    renderer.dispose();
    host.remove();
  });
});
