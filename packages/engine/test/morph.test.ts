import { describe, expect, it } from 'vitest';
import { capture } from '../src/core/capture';
import { keydiff } from '../src/core/diff';
import { buildTimeline } from '../src/core/timeline';
import { createSvgRenderer } from '../src/render/svg/svg-renderer';
import { svgDoc } from './fixtures';

function edgeLine(x2: number): string {
  return svgDoc(`<g class="edge"><title>A->B</title><line x1="10" y1="10" x2="${x2}" y2="10" style="stroke:#999999;stroke-width:1"/></g>`);
}

function nodeRect(w: number): string {
  return svgDoc(`<g class="node"><title>A</title><rect x="10" y="10" width="${w}" height="30" style="fill:#fff;stroke:#000;stroke-width:1"/></g>`);
}

const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

async function morphSetup(html1: string, html2: string) {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const renderer = createSvgRenderer();
  renderer.mount(host);
  const c1 = capture(html1);
  const c2 = capture(html2);
  const from = { spec: c1.spec, svg: c1.svg as SVGSVGElement };
  const to = { spec: c2.spec, svg: c2.svg as SVGSVGElement };
  const diff = keydiff(from.spec, to.spec);
  const timeline = buildTimeline(diff, { opts: { transitions: { update: { type: 'morph', durationMs: 400 } } } }, 900);
  return { host, renderer, from, to, diff, timeline };
}

describe('morph 泛化：非 path 形状的原生属性形变', () => {
  it('line：x2 中途插值、终态精确', async () => {
    const { renderer, from, to, diff, timeline } = await morphSetup(edgeLine(100), edgeLine(180));
    expect(diff.update.length).toBe(1);
    expect(diff.update[0]!.morphable).toBe(true);
    renderer.setFrame(from);
    const done = renderer.applyDiff(diff, timeline, { from, to, animate: true, mode: 'transition', speed: 1 });
    await wait(180);
    const mid = (to.svg as Element).querySelector('line')!.getAttribute('x2')!;
    expect(Number(mid)).toBeGreaterThan(100);
    expect(Number(mid)).toBeLessThan(180);
    await done;
    expect(Number((to.svg as Element).querySelector('line')!.getAttribute('x2'))).toBeCloseTo(180, 0);
    renderer.dispose();
  });

  it('rect：width 形变', async () => {
    const { renderer, from, to, diff, timeline } = await morphSetup(nodeRect(40), nodeRect(120));
    expect(diff.update[0]!.morphable).toBe(true);
    renderer.setFrame(from);
    const done = renderer.applyDiff(diff, timeline, { from, to, animate: true, mode: 'transition', speed: 1 });
    await wait(180);
    const mid = Number((to.svg as Element).querySelector('rect')!.getAttribute('width'));
    expect(mid).toBeGreaterThan(40);
    expect(mid).toBeLessThan(120);
    await done;
    expect(Number((to.svg as Element).querySelector('rect')!.getAttribute('width'))).toBeCloseTo(120, 0);
    renderer.dispose();
  });

  it('同 label 结构变化不匹配 morph 时保持静默降级（无异常）', async () => {
    const { renderer, from, to, diff, timeline } = await morphSetup(
      svgDoc('<g class="edge"><title>A->B</title><line x1="0" y1="0" x2="50" y2="50"/></g>'),
      svgDoc('<g class="edge"><title>A->B</title><path d="M 0 0 C 10 10 40 40 50 50"/></g>'),
    );
    const done = renderer.applyDiff(diff, timeline, { from, to, animate: true, mode: 'transition', speed: 1 });
    await done; // 不抛异常即通过（非同构按裁决 #6 走 exit+enter，morph 阶段自然跳过）
    renderer.dispose();
  });
});
