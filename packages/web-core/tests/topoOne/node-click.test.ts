import { describe, expect, it, vi } from 'vitest';
import { createNodeClickPlugin } from '../../src/topoOne/plugins/node-click';
import type { NodeClickEvent, PluginContext } from '../../src/topoOne/plugins/types';

function ctxWith(engineName: string, svg: SVGSVGElement, onNodeClick?: (e: NodeClickEvent) => void): PluginContext {
  const container = document.createElement('div');
  document.body.appendChild(container);
  container.appendChild(svg);
  return { container, svg, engineName, shared: { dragDistance: 0, animation: null }, onNodeClick };
}

function el(html: string): Element {
  const div = document.createElement('div');
  div.innerHTML = html;
  return div.firstElementChild!;
}

describe('node-click plugin', () => {
  it('resolves mermaid flowchart node from id pattern', () => {
    const svg = el(
      '<svg xmlns="http://www.w3.org/2000/svg"><g id="flowchart-A-0" class="node"><text>Start</text></g></svg>',
    ) as SVGSVGElement;
    const seen: NodeClickEvent[] = [];
    const ctx = ctxWith('mermaid', svg, (e) => seen.push(e));
    const plugin = createNodeClickPlugin();
    plugin.onAfterRender?.(ctx);

    const text = svg.querySelector('text')!;
    text.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: 10, clientY: 12 }));

    expect(seen).toHaveLength(1);
    expect(seen[0].nodeId).toBe('A');
    expect(seen[0].label).toBe('Start');
    expect(seen[0].engine).toBe('mermaid');
    plugin.onBeforeDestroy?.(ctx);
  });

  it('resolves plantuml entity from data-entity-uid', () => {
    const svg = el(
      '<svg xmlns="http://www.w3.org/2000/svg"><g id="part1-head" data-entity-uid="part1" data-qualified-name="Alice"><text>Alice</text></g></svg>',
    ) as SVGSVGElement;
    const seen: NodeClickEvent[] = [];
    const ctx = ctxWith('plantuml', svg, (e) => seen.push(e));
    const plugin = createNodeClickPlugin();
    plugin.onAfterRender?.(ctx);

    svg.querySelector('text')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));

    expect(seen[0].nodeId).toBe('part1');
    expect(seen[0].label).toBe('Alice');
    plugin.onBeforeDestroy?.(ctx);
  });

  it('resolves plantuml sequence message', () => {
    const svg = el(
      '<svg xmlns="http://www.w3.org/2000/svg"><g class="message" data-entity-1="part1" data-entity-2="part2" id="msg3"><text>hello</text></g></svg>',
    ) as SVGSVGElement;
    const seen: NodeClickEvent[] = [];
    const ctx = ctxWith('plantuml', svg, (e) => seen.push(e));
    const plugin = createNodeClickPlugin();
    plugin.onAfterRender?.(ctx);

    svg.querySelector('text')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));

    expect(seen[0].nodeId).toBe('msg3');
    expect(seen[0].label).toBe('hello');
    plugin.onBeforeDestroy?.(ctx);
  });

  it('suppresses clicks that were part of a pan drag', () => {
    const svg = el(
      '<svg xmlns="http://www.w3.org/2000/svg"><g id="flowchart-A-0"><text>Start</text></g></svg>',
    ) as SVGSVGElement;
    const seen: NodeClickEvent[] = [];
    const ctx = ctxWith('mermaid', svg, (e) => seen.push(e));
    ctx.shared.dragDistance = 20;
    const plugin = createNodeClickPlugin();
    plugin.onAfterRender?.(ctx);

    svg.querySelector('text')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(seen).toHaveLength(0);
    plugin.onBeforeDestroy?.(ctx);
  });

  it('ignores clicks on empty svg area', () => {
    const svg = el(
      '<svg xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="10" height="10"></rect></svg>',
    ) as SVGSVGElement;
    const onNodeClick = vi.fn();
    const ctx = ctxWith('mermaid', svg, onNodeClick);
    const plugin = createNodeClickPlugin();
    plugin.onAfterRender?.(ctx);

    (svg.querySelector('rect') as Element).dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(onNodeClick).not.toHaveBeenCalled();
    plugin.onBeforeDestroy?.(ctx);
  });
});
