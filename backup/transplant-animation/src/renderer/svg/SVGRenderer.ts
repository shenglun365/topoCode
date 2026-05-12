/**
 * SVG 渲染器 (基于 D3.js)
 * @module renderer/svg/SVGRenderer
 *
 * @description
 * 使用 D3.js 渲染 SVG，支持 ~1000 节点。
 * 支持节点拖拽、缩放、悬停交互。
 */

import * as d3 from 'd3';
import type { AnimationState, RenderOptions, RenderTheme, NodeShape } from '../../core/types';
import type { IRenderer } from '../IRenderer';
import { defaultTheme } from '../theme/defaultTheme';
import { RENDERER } from '../../utils/logger';

export class SVGRenderer implements IRenderer {
  private container: HTMLElement | null = null;
  private svg: d3.Selection<SVGSVGElement, unknown, null, undefined> | null = null;
  private g: d3.Selection<SVGGElement, unknown, null, undefined> | null = null;
  private width: number = 800;
  private height: number = 600;
  private theme: RenderTheme = defaultTheme;
  private zoomBehavior: d3.ZoomBehavior<SVGSVGElement, unknown> | null = null;

  // 元素引用
  private nodeGroups = new Map<string, d3.Selection<SVGGElement, unknown, null, undefined>>();
  private edgeGroups = new Map<string, d3.Selection<SVGGElement, unknown, null, undefined>>();
  private groupRects = new Map<string, d3.Selection<SVGRectElement, unknown, null, undefined>>();

  // 交互
  private onNodeClick?: (nodeId: string) => void;
  private onNodeHover?: (nodeId: string | null) => void;

  init(options: RenderOptions): void {
    this.container =
      typeof options.container === 'string'
        ? document.querySelector(options.container) as HTMLElement
        : options.container;

    if (!this.container) {
      throw new Error('Container not found');
    }

    this.width = options.width || 800;
    this.height = options.height || 600;
    this.theme = options.theme || defaultTheme;

    // 清除旧内容
    this.container.innerHTML = '';

    // 创建 SVG
    this.svg = d3.select(this.container)
      .append('svg')
      .attr('width', this.width)
      .attr('height', this.height)
      .attr('viewBox', `0 0 ${this.width} ${this.height}`)
      .attr('style', `max-width: 100%; height: auto;`);

    // 背景
    this.svg
      .append('rect')
      .attr('width', this.width)
      .attr('height', this.height)
      .attr('fill', this.theme.background);

    // 主容器 (支持缩放)
    this.g = this.svg.append('g');

    // 缩放行为
    if (options.zoom !== false) {
      this.zoomBehavior = d3
        .zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.1, 4])
        .on('zoom', (event) => {
          this.g!.attr('transform', event.transform.toString());
        });

      this.svg.call(this.zoomBehavior);
    }

    // 箭头标记
    this.renderArrowMarkers();

    RENDERER.info('SVGRenderer initialized', { width: this.width, height: this.height });
  }

  render(state: AnimationState): void {
    if (!this.g) return;

    this.renderGroups(state);
    this.renderEdges(state);
    this.renderNodes(state);
  }

  private renderNodes(state: AnimationState): void {
    if (!this.g) return;

    const nodesArray = Array.from(state.nodes.values());

    // 绑定数据
    const bound = this.g
      .selectAll<SVGGElement, any>('.topo-node')
      .data(nodesArray, (d: any) => d.id);

    // 移除
    bound.exit().remove();

    // 进入
    const enter = bound
      .enter()
      .append('g')
      .attr('class', 'topo-node')
      .attr('cursor', 'pointer')
      .call(this.dragBehavior());

    enter.on('click', (event: any, d: any) => {
        event.stopPropagation();
        this.onNodeClick?.(d.id);
      })
      .on('mouseenter', (event: any, d: any) => {
        this.onNodeHover?.(d.id);
      })
      .on('mouseleave', () => {
        this.onNodeHover?.(null);
      });

    // 更新 + 进入
    const merged = enter.merge(bound) as d3.Selection<SVGGElement, any, any, any>;

    merged
      .attr('transform', (d: any) => `translate(${d.position[0]}, ${d.position[1]})`);

    // 绘制形状
    merged.each(function (d: any) {
      const sel = d3.select<SVGGElement, any>(this);
      const shape = d.style?.shape || 'circle';
      const isHighlighted = state.highlights.includes(d.id);
      const isSelected = state.selections.includes(d.id);

      // 清除旧形状
      sel.select('.node-shape').remove();
      sel.select('.node-label').remove();
      sel.select('.node-glow').remove();

      // 高亮光晕
      if (isHighlighted) {
        sel.insert('circle', ':first-child')
          .attr('class', 'node-glow')
          .attr('r', 35)
          .attr('fill', 'none')
          .attr('stroke', this.theme.node.highlightStroke)
          .attr('stroke-width', 4)
          .attr('opacity', 0.6);
      }

      // 形状
      const shapeSel = sel.append('g').attr('class', 'node-shape');
      this.drawShape(shapeSel, shape, d);

      // 选中边框
      if (isSelected) {
        shapeSel.selectAll('*').attr('stroke', this.theme.node.selectionStroke).attr('stroke-width', 3);
      }

      // 标签
      if (d.label) {
        sel.append('text')
          .attr('class', 'node-label')
          .text(d.label)
          .attr('text-anchor', 'middle')
          .attr('dy', '0.35em')
          .attr('fill', d.style?.fontColor || this.theme.node.defaultFontColor)
          .attr('font-size', d.style?.fontSize || this.theme.node.defaultFontSize)
          .attr('pointer-events', 'none');
      }
    });

    // 透明度
    merged.select('.node-shape')
      .attr('opacity', (d: any) => d.style?.opacity ?? 1);
  }

  private drawShape(
    sel: d3.Selection<SVGGElement, any, any, any>,
    shape: NodeShape,
    node: any
  ): void {
    const fill = node.style?.fillColor || this.theme.node.defaultFill;
    const stroke = node.style?.strokeColor || this.theme.node.defaultStroke;
    const strokeWidth = node.style?.strokeWidth || 2;

    switch (shape) {
      case 'circle': {
        const r = node.style?.radius || 25;
        sel.append('circle')
          .attr('r', r)
          .attr('fill', fill)
          .attr('stroke', stroke)
          .attr('stroke-width', strokeWidth);
        break;
      }
      case 'rect': {
        const w = node.style?.width || 100;
        const h = node.style?.height || 40;
        const rx = node.style?.radius || 4;
        sel.append('rect')
          .attr('x', -w / 2)
          .attr('y', -h / 2)
          .attr('width', w)
          .attr('height', h)
          .attr('rx', rx)
          .attr('fill', fill)
          .attr('stroke', stroke)
          .attr('stroke-width', strokeWidth);
        break;
      }
      case 'diamond': {
        const r = node.style?.radius || 25;
        sel.append('polygon')
          .attr('points', `0,${-r} ${r},0 0,${r} ${-r},0`)
          .attr('fill', fill)
          .attr('stroke', stroke)
          .attr('stroke-width', strokeWidth);
        break;
      }
      case 'hexagon': {
        const r = node.style?.radius || 25;
        const points = Array.from({ length: 6 }, (_, i) => {
          const angle = (Math.PI / 3) * i - Math.PI / 6;
          return `${r * Math.cos(angle)},${r * Math.sin(angle)}`;
        }).join(' ');
        sel.append('polygon')
          .attr('points', points)
          .attr('fill', fill)
          .attr('stroke', stroke)
          .attr('stroke-width', strokeWidth);
        break;
      }
      case 'triangle': {
        const r = node.style?.radius || 25;
        sel.append('polygon')
          .attr('points', `0,${-r} ${r},${r} ${-r},${r}`)
          .attr('fill', fill)
          .attr('stroke', stroke)
          .attr('stroke-width', strokeWidth);
        break;
      }
      case 'ellipse': {
        const rx = node.style?.radius || 30;
        const ry = (node.style?.radius || 25) * 0.6;
        sel.append('ellipse')
          .attr('rx', rx)
          .attr('ry', ry)
          .attr('fill', fill)
          .attr('stroke', stroke)
          .attr('stroke-width', strokeWidth);
        break;
      }
      default:
        // 默认圆形
        sel.append('circle')
          .attr('r', 25)
          .attr('fill', fill)
          .attr('stroke', stroke)
          .attr('stroke-width', strokeWidth);
    }
  }

  private renderEdges(state: AnimationState): void {
    if (!this.g) return;

    const edgesArray = Array.from(state.edges.values());

    const bound = this.g
      .selectAll<SVGGElement, any>('.topo-edge')
      .data(edgesArray, (d: any) => d.id);

    bound.exit().remove();

    const enter = bound.enter().append('g').attr('class', 'topo-edge');

    enter.append('line').attr('class', 'edge-line');
    enter.append('text').attr('class', 'edge-label').attr('text-anchor', 'middle');

    const merged = enter.merge(bound) as d3.Selection<SVGGElement, any, any, any>;

    merged.each(function (d: any) {
      const sel = d3.select<SVGGElement, any>(this);
      const source = state.nodes.get(d.source);
      const target = state.nodes.get(d.target);

      if (!source || !target) return;

      const line = sel.select('.edge-line');
      const isHighlighted = state.highlights.includes(d.source) || state.highlights.includes(d.target);

      line
        .attr('x1', source.position[0])
        .attr('y1', source.position[1])
        .attr('x2', target.position[0])
        .attr('y2', target.position[1])
        .attr('stroke', isHighlighted ? this.theme.edge.highlightColor : (d.style?.color || this.theme.edge.defaultColor))
        .attr('stroke-width', isHighlighted ? this.theme.edge.highlightWidth : (d.style?.strokeWidth || this.theme.edge.defaultWidth))
        .attr('stroke-dasharray', d.style?.strokeDasharray || 'none')
        .attr('marker-end', d.style?.markerEnd ? 'url(#arrow)' : 'none');

      // 标签
      if (d.label) {
        const mx = (source.position[0] + target.position[0]) / 2;
        const my = (source.position[1] + target.position[1]) / 2;
        sel.select('.edge-label')
          .attr('x', mx)
          .attr('y', my - 5)
          .text(d.label)
          .attr('fill', this.theme.text.secondary)
          .attr('font-size', 10);
      } else {
        sel.select('.edge-label').text('');
      }
    });
  }

  private renderGroups(state: AnimationState): void {
    if (!this.g || !state.groups) return;

    for (const [, group] of state.groups) {
      const bounds = group.bounds;
      const style = group.style || {};

      let rectSel = this.groupRects.get(group.id);

      if (!rectSel) {
        rectSel = this.g.insert('rect', '.topo-edge')
          .attr('class', `topo-group topo-group-${group.id}`)
          .attr('rx', style.cornerRadius || 8)
          .attr('ry', style.cornerRadius || 8);
        this.groupRects.set(group.id, rectSel);
      }

      rectSel
        .attr('x', bounds.x)
        .attr('y', bounds.y)
        .attr('width', bounds.width)
        .attr('height', bounds.height)
        .attr('fill', style.fillColor || this.theme.group.defaultFill)
        .attr('fill-opacity', style.fillOpacity ?? this.theme.group.defaultFillOpacity)
        .attr('stroke', style.borderColor || this.theme.group.defaultBorder)
        .attr('stroke-width', style.borderWidth || 2)
        .attr('stroke-dasharray', style.borderStyle === 'dashed' ? '5,5' : 'none');
    }
  }

  private renderArrowMarkers(): void {
    if (!this.svg) return;

    const defs = this.svg.select('defs').empty() ? this.svg.append('defs') : this.svg.select('defs');

    defs.append('marker')
      .attr('id', 'arrow')
      .attr('viewBox', '0 -5 10 10')
      .attr('refX', 30)
      .attr('refY', 0)
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('orient', 'auto')
      .append('path')
      .attr('d', 'M0,-5L10,0L0,5')
      .attr('fill', this.theme.edge.defaultColor);
  }

  private dragBehavior() {
    return d3.drag<SVGGElement, any>()
      .on('start', (event) => {
        d3.select(event.sourceEvent.target.closest('.topo-node')).raise();
      })
      .on('drag', (event, d: any) => {
        d.position = [event.x, event.y];
        d3.select(event.sourceEvent.target.closest('.topo-node'))
          .attr('transform', `translate(${event.x}, ${event.y})`);
      });
  }

  // ==================== 公共 API ====================

  getNodePosition(nodeId: string): [number, number] | null {
    const group = this.nodeGroups.get(nodeId);
    if (!group) return null;
    const transform = group.attr('transform');
    if (!transform) return null;
    const match = transform.match(/translate\(([-\d.]+),\s*([-\d.]+)\)/);
    if (!match) return null;
    return [parseFloat(match[1]), parseFloat(match[2])];
  }

  setNodeClickHandler(handler: (nodeId: string) => void): void {
    this.onNodeClick = handler;
  }

  setNodeHoverHandler(handler: (nodeId: string | null) => void): void {
    this.onNodeHover = handler;
  }

  zoomToLevel(level: number): void {
    if (!this.svg || !this.zoomBehavior) return;
    this.svg.transition().duration(750).call(this.zoomBehavior.scaleTo, level);
  }

  fitToScreen(padding: number = 40): void {
    if (!this.svg) return;
    const bounds = this.g!.node()?.getBBox();
    if (!bounds || bounds.width === 0) return;

    const scale = Math.min(
      (this.width - padding * 2) / bounds.width,
      (this.height - padding * 2) / bounds.height
    );

    const tx = this.width / 2 - (bounds.x + bounds.width / 2) * scale;
    const ty = this.height / 2 - (bounds.y + bounds.height / 2) * scale;

    this.svg.transition().duration(750).call(
      (this.zoomBehavior || d3.zoom()).transform,
      d3.zoomIdentity.translate(tx, ty).scale(scale)
    );
  }

  getContainer(): HTMLElement {
    if (!this.container) throw new Error('Renderer not initialized');
    return this.container;
  }

  getSVGElement(): SVGSVGElement | null {
    return this.svg?.node() || null;
  }

  destroy(): void {
    if (this.container) {
      this.container.innerHTML = '';
    }
    this.svg = null;
    this.g = null;
    this.nodeGroups.clear();
    this.edgeGroups.clear();
    this.groupRects.clear();
    RENDERER.info('SVGRenderer destroyed');
  }
}
