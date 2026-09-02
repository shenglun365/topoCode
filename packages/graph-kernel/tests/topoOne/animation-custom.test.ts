import { afterEach, describe, expect, it } from 'vitest';
import { buildPlanFromSelectors, createAnimationPlugin } from '../../src/animation';
import type { AnimationController } from '../../src/animation/controller';
import type { AnimationPlanContext, AnimationPluginOptions } from '../../src/animation';
import { createDiagram } from '../../src/core/DiagramView';

const SEQUENCE = 'sequenceDiagram\n  Alice->>Bob: hello\n  Bob-->>Alice: hi';

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function makeSvg(markup: string) {
  const container = document.createElement('div');
  document.body.appendChild(container);
  container.innerHTML = markup;
  return { container, svg: container.querySelector('svg')! };
}

function runPlugin(
  svg: SVGSVGElement,
  container: HTMLElement,
  opts: AnimationPluginOptions,
  engine = 'plantuml',
): AnimationController | null {
  const plugin = createAnimationPlugin(opts);
  const shared = { dragDistance: 0, animation: null as AnimationController | null };
  plugin.onAfterRender!({ container, svg, engineName: engine, code: '', shared });
  return shared.animation;
}

const SHAPE_SVG =
  '<svg><rect id="r1"/><rect id="r2"/><rect id="r3"/><text id="t1">x</text></svg>';

afterEach(() => {
  document.body.innerHTML = '';
});

describe('custom animation steps (CSS selectors)', () => {
  it('reveal: each step reveals exactly its selector-matched elements', () => {
    const { container, svg } = makeSvg(SHAPE_SVG);
    const c = runPlugin(svg, container, {
      steps: [
        { label: 'first', selectors: ['#r1'] },
        { label: 'rest', selectors: ['#r2', '#r3'] },
      ],
    })!;
    expect(c).not.toBeNull();
    expect(c.mode).toBe('reveal');
    expect(c.total).toBe(2);

    const hidden = () => svg.querySelectorAll('.td-anim-hidden').length;
    expect(svg.querySelectorAll('.td-anim-el').length).toBe(3); // t1 not in any step
    expect(hidden()).toBe(3); // reset: all step elements hidden

    c.next();
    expect(c.index).toBe(0);
    expect(svg.querySelector('#r1')!.classList.contains('td-anim-hidden')).toBe(false);
    expect(hidden()).toBe(2); // r2 r3 still hidden

    c.next();
    expect(c.index).toBe(1);
    expect(hidden()).toBe(0);
  });

  it('highlight: only the current step elements are active', () => {
    const { container, svg } = makeSvg(SHAPE_SVG);
    const c = runPlugin(svg, container, {
      mode: 'highlight',
      steps: [
        { label: 'first', selectors: ['#r1'] },
        { label: 'rest', selectors: ['#r2', '#r3'] },
      ],
    })!;

    c.next();
    expect(svg.querySelector('#r1')!.classList.contains('td-anim-active')).toBe(true);
    expect(svg.querySelector('#r2')!.classList.contains('td-anim-active')).toBe(false);

    c.next();
    expect(svg.querySelector('#r1')!.classList.contains('td-anim-active')).toBe(false);
    expect(svg.querySelector('#r2')!.classList.contains('td-anim-active')).toBe(true);
    expect(svg.querySelector('#r3')!.classList.contains('td-anim-active')).toBe(true);
  });

  it('combines multiple selectors of one step with OR', () => {
    const { container, svg } = makeSvg(SHAPE_SVG);
    const c = runPlugin(svg, container, {
      steps: [{ label: 'all', selectors: ['#r1', 'rect'] }],
    })!;
    // 'rect' matches r1,r2,r3; #r1 duplicates -> 3 unique elements, 1 step
    expect(c.total).toBe(1);
    c.next();
    expect(svg.querySelectorAll('.td-anim-el').length).toBe(3);
    expect(svg.querySelectorAll('.td-anim-hidden').length).toBe(0);
  });

  it('falls back to the built-in adapter when no selector matches', () => {
    const { container, svg } = makeSvg(
      '<svg><rect data-source-line="1"/><rect data-source-line="2"/><rect data-source-line="1"/></svg>',
    );
    const c = runPlugin(svg, container, { steps: [{ label: 'x', selectors: ['.does-not-exist'] }] })!;
    // plantuml generic adapter: grouped by data-source-line
    expect(c.total).toBe(2);
    expect(c.mode).toBe('reveal');
  });

  it('buildPlanFromSelectors returns null when nothing resolves', () => {
    const { svg } = makeSvg(SHAPE_SVG);
    expect(buildPlanFromSelectors(svg, [{ label: 'x', selectors: ['.nope'] }])).toBeNull();
  });
});

describe('custom animation plan factory', () => {
  it('plan factory takes precedence over steps and built-in adapters', () => {
    const { container, svg } = makeSvg(SHAPE_SVG);
    const calls: AnimationPlanContext[] = [];
    const r1 = svg.querySelector('#r1')!;
    const c = runPlugin(
      svg,
      container,
      {
        steps: [{ label: 'ignored', selectors: ['#r2'] }],
        plan: (ctx) => {
          calls.push(ctx);
          return { mode: 'highlight', stepMs: 120, steps: [{ label: 'only', elements: [r1] }] };
        },
      },
      'mermaid',
    )!;
    expect(c.total).toBe(1);
    expect(c.mode).toBe('highlight');
    expect(calls).toHaveLength(1);
    expect(calls[0].svg).toBe(svg);
    expect(calls[0].engine).toBe('mermaid');
  });

  it('plan factory returning null falls back to the built-in adapter', () => {
    // mermaid generic adapter animates every [id] element
    const { container, svg } = makeSvg('<svg><g id="a"><rect/></g><g id="b"><rect/></g></svg>');
    const c = runPlugin(svg, container, { plan: () => null }, 'mermaid')!;
    expect(c.total).toBe(2);
    expect(c.mode).toBe('reveal');
  });
});

describe('custom steps end-to-end (createDiagram + real mermaid DOM)', () => {
  it('groups message texts into one custom step', async () => {
    const el = document.createElement('div');
    document.body.appendChild(el);
    const view = createDiagram(el, {
      source: { engine: 'mermaid', code: SEQUENCE },
      animation: {
        enabled: true,
        autoPlay: false,
        steps: [{ label: 'all messages', selectors: ['text.messageText'] }],
      },
      interactions: { zoomPan: false, export: false, nodeClick: false },
    });
    await sleep(500);
    const c = view.getAnimation()!;
    expect(c).not.toBeNull();
    expect(c.total).toBe(1); // one custom step (built-in adapter would give 3)

    const msgs = el.querySelectorAll('text.messageText');
    expect(msgs.length).toBe(2);
    expect(el.querySelectorAll('text.messageText.td-anim-hidden').length).toBe(2);
    c!.next();
    expect(el.querySelectorAll('text.messageText.td-anim-hidden').length).toBe(0);
    view.destroy();
  }, 15000);
});
