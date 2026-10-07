import { afterEach, describe, expect, it } from 'vitest';
import { createApp, h, type App } from 'vue';
import TopoDiagram from '../../src/vue/TopoDiagram.vue';

const FLOWCHART_SCHEMA = {
  version: 1,
  type: 'flowchart',
  nodes: [
    { id: 'a', label: 'Start' },
    { id: 'b', label: 'Done' },
  ],
  edges: [{ from: 'a', to: 'b' }],
};

type Vm = {
  getSvg(): SVGSVGElement | null;
  zoomToFit(): void;
};

function mount(props: Record<string, unknown>, hooks: Record<string, (...args: unknown[]) => void> = {}) {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const listenerProps: Record<string, unknown> = {};
  for (const [name, fn] of Object.entries(hooks)) {
    listenerProps[`on${name[0].toUpperCase()}${name.slice(1)}`] = fn;
  }
  const app: App = createApp(h(TopoDiagram as never, { ...props, ...listenerProps }));
  const vm = app.mount(host) as unknown as Vm;
  return { app, host, vm };
}

async function waitFor(cond: () => boolean, ms = 20000) {
  const t0 = Date.now();
  while (!cond()) {
    if (Date.now() - t0 > ms) throw new Error('timeout waiting for condition');
    await new Promise((r) => setTimeout(r, 25));
  }
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('TopoDiagram (vue, jsdom)', () => {
  it('renders raw mermaid code and exposes the svg', async () => {
    const { app, host, vm } = mount({
      code: 'flowchart TD\n  A[Start] --> B[Done]',
      engine: 'mermaid',
    });
    await waitFor(() => host.querySelector('svg') !== null);
    expect(host.querySelector('svg')).toBeInstanceOf(SVGSVGElement);
    expect(vm.getSvg()).toBeInstanceOf(SVGSVGElement);
    expect(host.querySelector('.topo-diagram__canvas svg')).not.toBeNull();
    app.unmount();
  }, 30000);

  it('negotiates the engine for a schema source and emits ready', async () => {
    let readyFired = false;
    const { app, host } = mount(
      { engine: 'auto', schema: FLOWCHART_SCHEMA },
      { ready: () => (readyFired = true) },
    );
    await waitFor(() => readyFired);
    expect(host.querySelector('svg')).toBeInstanceOf(SVGSVGElement);
    app.unmount();
  }, 30000);

  it('emits error and shows an error card for bad code', async () => {
    let error: { engine: string; message: string } | null = null;
    const { app, host } = mount(
      { code: 'flowchart TD\n  A[unclosed', engine: 'mermaid' },
      { error: (e) => (error = e as never) },
    );
    await waitFor(() => host.querySelector('.td-error') !== null);
    expect(error).not.toBeNull();
    expect(error!.engine).toBe('mermaid');
    expect(host.querySelector('.td-error')!.textContent).toContain('[mermaid]');
    app.unmount();
  }, 30000);

  it('re-renders when the code prop changes reactively', async () => {
    const { ref } = await import('vue');
    const code = ref('flowchart TD\n  A[One] --> B[Two]');
    const Wrapper = {
      setup() {
        return () => h(TopoDiagram as never, { code: code.value, engine: 'mermaid' });
      },
    };
    const host = document.createElement('div');
    document.body.appendChild(host);
    const app = createApp(Wrapper);
    app.mount(host);

    await waitFor(() => host.textContent?.includes('One'));
    code.value = 'flowchart TD\n  C[Three] --> D[Four]';
    await waitFor(() => host.textContent?.includes('Three'));
    expect(host.textContent).not.toContain('One');
    app.unmount();
  }, 30000);
});
