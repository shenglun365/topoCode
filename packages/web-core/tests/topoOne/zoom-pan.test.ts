import { afterEach, describe, expect, it, vi } from 'vitest';
import { createDiagram } from '../../src/topoOne/core/DiagramView';
import { createZoomPanPlugin } from '../../src/topoOne/plugins/zoom-pan';
import type { SharedInteractionState } from '../../src/topoOne/plugins/types';

function makeContainer(w: number, h: number): HTMLElement {
  const el = document.createElement('div');
  Object.defineProperty(el, 'clientWidth', { value: w, configurable: true });
  Object.defineProperty(el, 'clientHeight', { value: h, configurable: true });
  document.body.appendChild(el);
  return el;
}

function makeSvg(w: number, h: number): SVGSVGElement {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  return svg;
}

describe('zoom-pan plugin', () => {
  let container: HTMLElement;
  let svg: SVGSVGElement;
  let shared: SharedInteractionState;

  afterEach(() => {
    container.remove();
    vi.restoreAllMocks();
  });

  function setup() {
    container = makeContainer(400, 200);
    svg = makeSvg(800, 400);
    container.appendChild(svg);
    shared = { dragDistance: 0, animation: null };
    const plugin = createZoomPanPlugin();
    plugin.onAfterRender?.({ container, svg, engineName: 'mermaid', shared });
    return plugin;
  }

  it('zoomToFit scales to container with padding and centers', () => {
    const plugin = setup();
    plugin.api.zoomToFit();
    // 800x400 into 400x200 -> s = 0.5 * 0.96 = 0.48, centered: x=(400-384)/2=8, y=(200-192)/2=4
    expect(svg.style.transform).toBe('translate(8px, 4px) scale(0.48)');
  });

  it('wheel zooms anchored at cursor', () => {
    setup();
    const before = svg.style.transform;
    svg.dispatchEvent(
      new WheelEvent('wheel', { deltaY: -100, clientX: 200, clientY: 100, bubbles: true, cancelable: true }),
    );
    expect(svg.style.transform).not.toBe(before);
    expect(svg.style.transform).toMatch(/scale\((0\.5\d+|1\.2)/);
  });

  it('drag pan updates translate and records dragDistance', () => {
    setup();
    container.dispatchEvent(new MouseEvent('mousedown', { clientX: 10, clientY: 10, bubbles: true, button: 0 }));
    window.dispatchEvent(new MouseEvent('mousemove', { clientX: 60, clientY: 40, bubbles: true }));
    window.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    expect(svg.style.transform).toContain('translate(50px, 30px)');
    expect(shared.dragDistance).toBeGreaterThan(0);
  });

  it('zoomIn / zoomOut change scale around center', () => {
    const plugin = setup();
    plugin.api.zoomIn();
    const afterIn = svg.style.transform;
    plugin.api.zoomOut();
    plugin.api.zoomOut();
    expect(svg.style.transform).not.toBe(afterIn);
  });

  it('toolbar buttons are rendered', () => {
    setup();
    const buttons = container.querySelectorAll('.td-toolbar button');
    expect(buttons.length).toBe(4);
  });

  it('createDiagram exposes zoom api and wires plugins (mermaid jsdom render)', async () => {
    const el = makeContainer(300, 150);
    const view = createDiagram(el, {
      source: { engine: 'mermaid', code: 'flowchart TD\n  A[Start] --> B[End]' },
      interactions: { zoomPan: true, export: false, nodeClick: false, animation: false },
    });
    await new Promise((r) => setTimeout(r, 400));
    expect(el.querySelector('svg')).not.toBeNull();
    expect(el.querySelectorAll('.td-toolbar button').length).toBe(4);
    view.zoomToFit();
    expect(el.querySelector('svg')!.style.transform).toMatch(/scale\(/);
    view.destroy();
    el.remove();
  });
});
