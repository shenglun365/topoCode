import { describe, expect, it } from 'vitest';
import { capture } from '../src/core/capture';
import { keydiff } from '../src/core/diff';
import { buildTimeline } from '../src/core/timeline';
import { applyLayout, deepCloneSpec, emptyLayout } from '../src/core/layout';
import { createSvgRenderer } from '../src/render/svg/svg-renderer';
import { plantumlRules } from '../src/backends';
import { plantumlSeqBase, plantumlSeqChanged } from './fixtures/plantuml';
import { nodeG, svgDoc } from './fixtures';
import type { FrameSource } from '../src/core/types';

// plantuml 根 svg 内联 style="width:..;height:..;background:.." 覆盖引擎统一画布
// （CSS 优先级 > 展示属性）→ 帧过渡期出现无覆盖白条 + 鬼影白纸盖住新内容（坑 #27）

const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));
const rootCss = (svg: Element): CSSStyleDeclaration => (svg as SVGElement).style;

describe('根 svg 规范化 —— plantuml 内联尺寸/背景', () => {
  it('capture 剥离根 style 的 width/height/background，background 入 spec', () => {
    const { spec, svg } = capture(plantumlSeqBase, plantumlRules);
    const st = rootCss(svg);
    expect(st.getPropertyValue('width')).toBe('');
    expect(st.getPropertyValue('height')).toBe('');
    expect(st.getPropertyValue('background')).toBe('');
    expect(spec.background).toMatch(/ff|255/i);
    expect(svg.getAttribute('preserveAspectRatio')).toBe('xMidYMid meet');
  });

  it('无内联样式的根（mermaid/dot 风格）不受影响', () => {
    const { svg, spec } = capture(svgDoc(nodeG(0, 0, 'A')));
    expect(rootCss(svg).getPropertyValue('background')).toBe('');
    expect(spec.background).toBeUndefined();
    expect(svg.getAttribute('preserveAspectRatio')).not.toBe('none');
  });

  it('applyLayout 后 style 盒 = 属性盒 = 统一画布，两帧完全一致', () => {
    const a = capture(plantumlSeqBase, plantumlRules);
    const b = capture(plantumlSeqChanged, plantumlRules);
    const layers: FrameSource[] = [a, b].map((l) => {
      const src: FrameSource = { spec: l.spec, svg: l.svg as SVGSVGElement };
      src.raw = src.svg.cloneNode(true) as SVGSVGElement;
      src.rawSpec = deepCloneSpec(src.spec);
      return src;
    });
    const info = applyLayout(layers, emptyLayout());
    const size = `${info.half * 2}px`;
    for (const l of layers) {
      expect(rootCss(l.svg).width).toBe(size);
      expect(rootCss(l.svg).height).toBe(size);
      expect(l.svg.getAttribute('width')).toBe(String(info.half * 2));
      expect(l.svg.getAttribute('preserveAspectRatio')).toBe('xMidYMid meet');
      expect(rootCss(l.svg).background).toBe('transparent');
    }
  });

  it('帧过渡中鬼影层根为透明，不盖住新帧内容', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const renderer = createSvgRenderer();
    renderer.mount(host);

    const c1 = capture(svgDoc(nodeG(10, 10, 'A') + nodeG(200, 10, 'B')));
    const c2 = capture(svgDoc(nodeG(10, 10, 'A')));
    const from = { spec: c1.spec, svg: c1.svg as SVGSVGElement };
    const to = { spec: c2.spec, svg: c2.svg as SVGSVGElement };
    const diff = keydiff(from.spec, to.spec);
    expect(diff.exit.length).toBe(1);
    const timeline = buildTimeline(diff, { opts: {} }, 400);

    renderer.setFrame(from);
    const done = renderer.applyDiff(diff, timeline, { from, to, animate: true, mode: 'transition', speed: 1 });
    expect(rootCss(c1.svg).background).toBe('transparent');
    await done;
    host.remove();
  });

  it('导出回贴原始背景（staticSvgString 第二参）', async () => {
    const { spec, svg } = capture(plantumlSeqBase, plantumlRules);
    const { staticSvgString } = await import('../src/core/sanitize');
    const out = staticSvgString(svg, spec.background);
    expect(/background:\s*(#ffffff|rgb\(255,\s*255,\s*255\))/i.test(out)).toBe(true);
    const bare = staticSvgString(svg);
    expect(/background:/i.test(bare)).toBe(false);
  });
});
