import { describe, expect, it } from 'vitest';
import { createDiagram } from '../../src/core/DiagramView';
import { pickEngine } from '../../src/core/capabilities';
import { samples } from './samples';

describe('createDiagram with schema source (full pipeline)', () => {
  it('renders a sequence schema via engine auto (mermaid path in jsdom)', async () => {
    const el = document.createElement('div');
    document.body.appendChild(el);
    const done = new Promise<void>((res, rej) => {
      createDiagram(el, {
        source: { engine: 'auto', schema: samples.sequence },
        onReady: () => res(),
        onError: (e) => rej(new Error(e.message)),
      });
    });
    await done;
    expect(el.querySelector('svg')).not.toBeNull();
    el.remove();
  });

  it('renders a flowchart schema (transpiled) and applies theme', async () => {
    const el = document.createElement('div');
    document.body.appendChild(el);
    const view = createDiagram(el, { source: { engine: 'mermaid', schema: samples.flowchart } });
    await new Promise((res) => setTimeout(res, 300));
    expect(el.querySelector('svg')).not.toBeNull();
    await view.setTheme('light');
    expect(el.querySelector('svg')).not.toBeNull();
    view.destroy();
    el.remove();
  });

  it('auto negotiation: gantt goes to mermaid, usecase prefers plantuml', () => {
    expect(pickEngine('gantt')).toBe('mermaid');
    expect(pickEngine('usecase')).toBe('plantuml');
  });

  it('invalid schema surfaces a validation error with jsonPath', async () => {
    const el = document.createElement('div');
    const done = new Promise<string>((res) => {
      createDiagram(el, {
        source: { engine: 'mermaid', schema: { version: 1, type: 'flowchart', nodes: [{ id: 'a', label: 'A' }], edges: [{ from: 'a', to: 'ghost' }] } },
        onError: (e) => res(e.message),
      });
    });
    const message = await done;
    expect(message).toContain("'ghost' does not exist");
    expect(message).toContain('/edges/0/to');
  });
});
