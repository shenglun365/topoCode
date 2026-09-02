import { describe, expect, it, vi } from 'vitest';
import { createNodeClickPlugin } from '../../src/plugins/node-click';
import type { NodeClickEvent, PluginContext } from '../../src/plugins/types';

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

  it('falls back to nearest text when plantuml has no addressable id (class/state/mindmap)', () => {
    const svg = el(
      '<svg xmlns="http://www.w3.org/2000/svg">' +
        '<g><polygon points="0,0"></polygon><text>动画能力</text></g>' +
        '<g><polygon points="1,1"></polygon><text>引擎能力</text></g>' +
      '</svg>',
    ) as SVGSVGElement;
    const seen: NodeClickEvent[] = [];
    const ctx = ctxWith('plantuml', svg, (e) => seen.push(e));
    const plugin = createNodeClickPlugin();
    plugin.onAfterRender?.(ctx);

    const texts = svg.querySelectorAll('text');
    texts[1].dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(seen).toHaveLength(1);
    expect(seen[0].nodeId).toBe('txt:引擎能力');
    expect(seen[0].label).toBe('引擎能力');

    // 正式寻址优先于文本兜底：带 uid 的元素内点击仍走原逻辑(而非 txt 兜底)
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('data-entity-uid', 'part9');
    const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    t.textContent = '参与';
    g.appendChild(t);
    svg.insertBefore(g, svg.firstChild);
    t.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(seen).toHaveLength(2);
    expect(seen[1].nodeId).toBe('part9');
    expect(seen[1].label).toBe('参与');
    plugin.onBeforeDestroy?.(ctx);
  });

  it('falls back to nearest text for mermaid diagrams without id pattern (mindmap)', () => {
    const svg = el(
      '<svg xmlns="http://www.w3.org/2000/svg"><g class="node"><circle></circle><text>订单聚合</text></g></svg>',
    ) as SVGSVGElement;
    const seen: NodeClickEvent[] = [];
    const ctx = ctxWith('mermaid', svg, (e) => seen.push(e));
    const plugin = createNodeClickPlugin();
    plugin.onAfterRender?.(ctx);

    svg.querySelector('text')!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(seen).toHaveLength(1);
    expect(seen[0].nodeId).toBe('txt:订单聚合');
    expect(seen[0].label).toBe('订单聚合');
    plugin.onBeforeDestroy?.(ctx);
  });

  it('strips the mermaid render-id prefix from node ids (er/flow with topo-one-mmd-N ids)', () => {
    const svg = el(
      '<svg xmlns="http://www.w3.org/2000/svg" id="topo-one-mmd-71">' +
        '<g class="node" id="topo-one-mmd-71-entity-sa_s_i_e_385-0"><text>385</text></g>' +
        '<g class="node" id="topo-one-mmd-71-flowchart-n1-2"><text>n1</text></g>' +
      '</svg>',
    ) as SVGSVGElement;
    const seen: NodeClickEvent[] = [];
    const ctx = ctxWith('mermaid', svg, (e) => seen.push(e));
    const plugin = createNodeClickPlugin();
    plugin.onAfterRender?.(ctx);

    svg.querySelector('#topo-one-mmd-71-entity-sa_s_i_e_385-0')!
      .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(seen).toHaveLength(1);
    expect(seen[0].nodeId).toBe('sa_s_i_e_385');
    svg.querySelector('#topo-one-mmd-71-flowchart-n1-2')!
      .dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(seen[1].nodeId).toBe('n1');
    plugin.onBeforeDestroy?.(ctx);
  });

  it('picks the nearest text within a plantuml entity (stereotype vs name · assetId)', () => {
    const svg = el(
      '<svg xmlns="http://www.w3.org/2000/svg">' +
        '<g class="entity" id="ent0078">' +
          '<rect x="0" y="0" width="200" height="60"></rect>' +
          '<text x="100" y="15">«process»</text>' +
          '<text x="100" y="48">toSource · sa-d-i-p-1253</text>' +
        '</g>' +
      '</svg>',
    ) as unknown as SVGSVGElement;
    // jsdom 无布局：按语义手工给定文本位置(构造型在上、名称在下)
    const texts = svg.querySelectorAll('text');
    (texts[0] as unknown as { getBoundingClientRect: () => DOMRect }).getBoundingClientRect =
      () => ({ left: 50, top: 5, right: 150, bottom: 25, width: 100, height: 20, x: 50, y: 5, toJSON: () => ({}) }) as DOMRect;
    (texts[1] as unknown as { getBoundingClientRect: () => DOMRect }).getBoundingClientRect =
      () => ({ left: 40, top: 38, right: 160, bottom: 58, width: 120, height: 20, x: 40, y: 38, toJSON: () => ({}) }) as DOMRect;
    const seen: NodeClickEvent[] = [];
    const ctx = ctxWith('plantuml', svg, (e) => seen.push(e));
    const plugin = createNodeClickPlugin();
    plugin.onAfterRender?.(ctx);

    // 点击节点下半部(名称·ID 附近)
    svg.querySelector('rect')!.dispatchEvent(
      new MouseEvent('click', { bubbles: true, clientX: 100, clientY: 48 }));
    expect(seen).toHaveLength(1);
    expect(seen[0].label).toBe('toSource · sa-d-i-p-1253');
    expect(seen[0].nodeId).toBe('txt:toSource · sa-d-i-p-1253');
    // 前端 onNodeClick 尾段解析即可映射: sa-d-i-p-1253
    expect(seen[0].label.split('·').pop()!.trim()).toBe('sa-d-i-p-1253');
    plugin.onBeforeDestroy?.(ctx);
  });
});
