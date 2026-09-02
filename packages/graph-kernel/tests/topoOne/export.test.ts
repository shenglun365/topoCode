import { afterEach, describe, expect, it, vi } from 'vitest';
import { createExportPlugin, serializeSvg, svgToDataUrl } from '../../src/topoOne/plugins/export';
import type { PluginContext } from '../../src/topoOne/plugins/types';

const SVG_HTML =
  '<svg xmlns="http://www.w3.org/2000/svg" style="transform: scale(2)" viewBox="0 0 100 50"><rect width="100" height="50"></rect></svg>';

function setup(): { ctx: PluginContext; svg: SVGSVGElement; container: HTMLElement } {
  const container = document.createElement('div');
  document.body.appendChild(container);
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.innerHTML = SVG_HTML.replace(/^<svg[^>]*>/, '').replace('</svg>', '');
  svg.setAttribute('viewBox', '0 0 100 50');
  container.appendChild(svg);
  return { ctx: { container, svg, engineName: 'mermaid', shared: { dragDistance: 0, animation: null } }, svg, container };
}

afterEach(() => {
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

describe('serializeSvg', () => {
  it('adds xmlns and strips the live transform style', () => {
    const { svg } = setup();
    const out = serializeSvg(svg);
    expect(out).toContain('xmlns="http://www.w3.org/2000/svg"');
    expect(out).not.toContain('transform');
  });

  it('svgToDataUrl produces an svg data url', () => {
    const { svg } = setup();
    const url = svgToDataUrl(serializeSvg(svg));
    expect(url.startsWith('data:image/svg+xml;charset=utf-8,')).toBe(true);
  });
});

describe('export plugin', () => {
  it('renders copy/svg/png buttons', () => {
    const { ctx, container } = setup();
    const plugin = createExportPlugin();
    plugin.onAfterRender?.(ctx);
    const labels = [...container.querySelectorAll<HTMLButtonElement>('.td-toolbar button')].map((b) => b.textContent);
    expect(labels).toEqual(['⧉', 'SVG', 'PNG']);
    plugin.onBeforeDestroy?.(ctx);
  });

  it('copy button writes the serialized svg to the clipboard', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    const { ctx, container } = setup();
    const plugin = createExportPlugin();
    plugin.onAfterRender?.(ctx);

    const copyBtn = [...container.querySelectorAll<HTMLButtonElement>('.td-toolbar button')].find((b) => b.textContent === '⧉')!;
    copyBtn.click();
    await new Promise((r) => setTimeout(r, 10));

    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0][0]).toContain('<svg');
    plugin.onBeforeDestroy?.(ctx);
  });

  it('svg download triggers an anchor click with a blob url', () => {
    const click = vi.fn();
    const createObjectURL = vi.fn().mockReturnValue('blob:fake');
    const revokeObjectURL = vi.fn();
    Object.defineProperty(URL, 'createObjectURL', { value: createObjectURL, configurable: true });
    Object.defineProperty(URL, 'revokeObjectURL', { value: revokeObjectURL, configurable: true });
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      click(this.download, this.href);
    });

    const { ctx, container } = setup();
    const plugin = createExportPlugin();
    plugin.onAfterRender?.(ctx);
    const svgBtn = [...container.querySelectorAll<HTMLButtonElement>('.td-toolbar button')].find((b) => b.textContent === 'SVG')!;
    svgBtn.click();

    expect(click).toHaveBeenCalledWith('topo-one-mermaid.svg', 'blob:fake');
    plugin.onBeforeDestroy?.(ctx);
  });
});
