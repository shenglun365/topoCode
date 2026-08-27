import { afterEach, describe, expect, it, vi } from 'vitest';
import { createDiagram } from '../../src/topoOne/core/DiagramView';

const SEQUENCE = 'sequenceDiagram\n  Alice->>Bob: hello\n  Bob-->>Alice: hi';

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

afterEach(() => {
  document.body.innerHTML = '';
  vi.useRealTimers();
});

describe('animation plugin integration', () => {
  it('adds playback controls and animates a mermaid sequence', async () => {
    const el = document.createElement('div');
    el.style.width = '400px';
    el.style.height = '200px';
    document.body.appendChild(el);

    const view = createDiagram(el, {
      source: { engine: 'mermaid', code: SEQUENCE },
      animation: { enabled: true, autoPlay: false },
      interactions: { zoomPan: false, export: false, nodeClick: false },
    });

    await sleep(500);
    const svg = el.querySelector('svg')!;
    expect(svg).not.toBeNull();

    // playback toolbar present
    const labels = [...el.querySelectorAll<HTMLButtonElement>('.td-toolbar button')].map((b) => b.textContent);
    expect(labels).toContain('⏮');
    expect(labels).toContain('▶');
    expect(labels).toContain('⏭');
    expect(el.querySelector('.td-anim-progress')).not.toBeNull();

    const controller = view.getAnimation();
    expect(controller).not.toBeNull();
    expect(controller!.total).toBe(3); // participants + 2 messages

    // initially all step elements hidden
    const hidden = () => svg.querySelectorAll('.td-anim-hidden').length;
    expect(hidden()).toBeGreaterThan(0);

    vi.useFakeTimers();
    controller!.play();
    vi.advanceTimersByTime(700);
    expect(controller!.index).toBe(0);
    expect(hidden()).toBeLessThan(svg.querySelectorAll('.td-anim-el').length);
    vi.advanceTimersByTime(1400);
    expect(controller!.index).toBe(2);
    vi.advanceTimersByTime(700);
    expect(controller!.playing).toBe(false);
    expect(hidden()).toBe(0);

    // reset
    controller!.stop();
    expect(hidden()).toBeGreaterThan(0);

    vi.useRealTimers();
    view.destroy();
  });

  it('falls back to the generic document-order adapter for flowcharts', async () => {
    const el = document.createElement('div');
    el.style.width = '400px';
    el.style.height = '200px';
    document.body.appendChild(el);
    const view = createDiagram(el, {
      source: { engine: 'mermaid', code: 'flowchart TD\n  A[x] --> B[y]' },
      interactions: { zoomPan: false, export: false, nodeClick: false },
    });
    await sleep(400);
    // flowchart uses the generic adapter, which still produces steps -> controller exists
    expect(view.getAnimation()).not.toBeNull();
    view.destroy();
  });

  it('can be disabled entirely', async () => {
    const el = document.createElement('div');
    el.style.width = '400px';
    el.style.height = '200px';
    document.body.appendChild(el);
    const view = createDiagram(el, {
      source: { engine: 'mermaid', code: SEQUENCE },
      animation: { enabled: false },
      interactions: { zoomPan: false, export: false, nodeClick: false },
    });
    await sleep(400);
    expect(el.querySelector('.td-anim-progress')).toBeNull();
    expect(view.getAnimation()).toBeNull();
    view.destroy();
  });
});
