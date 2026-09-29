import { describe, expect, it } from 'vitest';
import { sanitizeSvg, staticSvgString } from '../src/core/sanitize';
import { capture } from '../src/core/capture';
import { createStoryEngine, storyStaticSvg } from '../src/story';
import { genericRules } from '../src/core/capture';
import { plantumlRules } from '../src/backends';
import { plantumlSeqBase } from './fixtures/plantuml';
import { nodeG, svgDoc } from './fixtures';

describe('出口脱敏（§6.4 用户无感）', () => {
  it('basic: 移除 data-ta-key 与注入类，保留引擎原生 DOM', () => {
    const { svg } = capture(svgDoc(nodeG(10, 10, '甲', { name: 'A' })), genericRules);
    (svg as Element).classList.add('ta-el', 'ta-hidden');
    const out = staticSvgString(svg as Element);
    expect(out).not.toContain('data-ta-');
    expect(out).not.toMatch(/class="[^"]*\bta-/);
    expect(out).toContain('data-name="A"'); // 引擎原生属性保留
    expect(out).toContain('甲');
  });

  it('plantuml 分组 wrapper 被解包，成员上移且不丢内容', () => {
    const { svg } = capture(plantumlSeqBase, plantumlRules);
    const before = svg.querySelectorAll('g[data-ta-group]').length;
    expect(before).toBeGreaterThan(0);
    const out = staticSvgString(svg);
    expect(out).not.toContain('data-ta-group');
    expect(out).not.toContain('data-ta-key');
    expect(out).toContain('<title>Alice</title>'); // 引擎原生 title 保留
    expect(out).toContain('查询用户');
  });

  it('脱敏只作用于克隆：引擎内部缓存的 svg 仍带键可寻址', () => {
    const { spec, svg } = capture(plantumlSeqBase, plantumlRules);
    staticSvgString(svg);
    const el = spec.elements[0]!;
    expect(svg.querySelector(el.source.sel)).not.toBeNull();
  });

  it('storyStaticSvg：当前状态默认导出 + 指定状态', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    const f1 = svgDoc(nodeG(10, 10, '甲', { name: 'A' }));
    const f2 = svgDoc(nodeG(10, 10, '甲', { name: 'A' }) + nodeG(200, 10, '乙', { name: 'B' }));
    const eng = await createStoryEngine({
      graph: {
        entry: 'a',
        states: [{ id: 'a', dwellMs: 0, svg: f1 }, { id: 'b', dwellMs: 0, svg: f2 }],
        edges: [{ from: 'a', to: 'b', choreography: { staggerMs: 1, transitions: { enter: { type: 'fade', durationMs: 5 } } } }],
      },
      host,
    });
    await eng.start();
    expect(storyStaticSvg(eng)).toContain('乙');
    expect(storyStaticSvg(eng)).not.toContain('data-ta-key');
    expect(storyStaticSvg(eng, 'a')).not.toContain('乙');
    eng.dispose();
    host.remove();
  });});
