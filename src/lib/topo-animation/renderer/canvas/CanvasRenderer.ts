/**
 * Canvas 渲染器 (基于 PixiJS)
 * @module renderer/canvas/CanvasRenderer
 *
 * @description
 * 使用 PixiJS WebGL 渲染，支持 ~10000 节点。
 * 适合大规模节点渲染。
 */

import * as PIXI from 'pixi.js';
import type { AnimationState, RenderOptions, RenderTheme } from '../../core/types';
import type { IRenderer } from '../IRenderer';
import { defaultTheme } from '../theme/defaultTheme';
import { RENDERER } from '../../utils/logger';

export class CanvasRenderer implements IRenderer {
  private app: PIXI.Application | null = null;
  private container: HTMLElement | null = null;
  private nodeContainer: PIXI.Container | null = null;
  private edgeContainer: PIXI.Container | null = null;
  private groupContainer: PIXI.Container | null = null;
  private width: number = 800;
  private height: number = 600;
  private theme: RenderTheme = defaultTheme;
  private fps: number = 10;

  // 节点引用
  private nodeObjects = new Map<string, PIXI.Container>();

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
    this.fps = Math.min(60, Math.max(10, options.fps || 10));

    this.container.innerHTML = '';

    // 创建 Pixi 应用
    const bgColor = this.hexToNumber(this.theme.background);

    this.app = new PIXI.Application({
      background: bgColor,
      width: this.width,
      height: this.height,
      antialias: true,
      resolution: window.devicePixelRatio || 1,
      autoDensity: true,
    });

    this.container.appendChild(this.app.view);

    // 帧率控制
    this.app.ticker.maxFPS = 60;
    this.app.ticker.speed = this.fps / 60;

    // 创建层级
    this.groupContainer = new PIXI.Container();
    this.edgeContainer = new PIXI.Container();
    this.nodeContainer = new PIXI.Container();

    this.app.stage.addChild(this.groupContainer);
    this.app.stage.addChild(this.edgeContainer);
    this.app.stage.addChild(this.nodeContainer);

    RENDERER.info('CanvasRenderer initialized', {
      width: this.width,
      height: this.height,
      fps: this.fps,
    });
  }

  render(state: AnimationState): void {
    if (!this.nodeContainer || !this.edgeContainer || !this.groupContainer) return;

    this.renderGroups(state);
    this.renderEdges(state);
    this.renderNodes(state);
  }

  private renderNodes(state: AnimationState): void {
    if (!this.nodeContainer) return;

    const currentIds = new Set(state.nodes.keys());

    // 移除不存在的节点
    for (const [id] of this.nodeObjects) {
      if (!currentIds.has(id)) {
        this.nodeContainer.removeChild(this.nodeObjects.get(id)!);
        this.nodeObjects.delete(id);
      }
    }

    // 渲染节点
    for (const [, node] of state.nodes) {
      let obj = this.nodeObjects.get(node.id);

      if (!obj) {
        obj = new PIXI.Container();
        obj.eventMode = 'static';
        this.nodeContainer.addChild(obj);
        this.nodeObjects.set(node.id, obj);
      }

      obj.removeChildren();
      obj.x = node.position[0];
      obj.y = node.position[1];
      obj.alpha = node.style?.opacity ?? 1;

      const isHighlighted = state.highlights.includes(node.id);
      const isSelected = state.selections.includes(node.id);
      const fill = this.hexToNumber(node.style?.fillColor || this.theme.node.defaultFill);
      const stroke = this.hexToNumber(node.style?.strokeColor || this.theme.node.defaultStroke);

      // 高亮光晕
      if (isHighlighted) {
        const glow = new PIXI.Graphics();
        glow.beginFill(fill, 0.3);
        glow.drawCircle(0, 0, 35);
        glow.endFill();
        obj.addChild(glow);
      }

      // 主体
      const body = new PIXI.Graphics();
      body.beginFill(fill);
      body.lineStyle(node.style?.strokeWidth || 2, stroke);
      body.drawRoundedRect(-50, -20, 100, 40, node.style?.radius || 4);
      body.endFill();

      if (isSelected) {
        body.lineStyle(3, this.hexToNumber(this.theme.node.selectionStroke));
      }

      obj.addChild(body);

      // 标签
      if (node.label) {
        const style = new PIXI.TextStyle({
          fontSize: node.style?.fontSize || this.theme.node.defaultFontSize,
          fill: this.hexToNumber(node.style?.fontColor || this.theme.node.defaultFontColor),
          align: 'center',
        });
        const text = new PIXI.Text({ text: node.label, style });
        text.anchor.set(0.5, 0.5);
        obj.addChild(text);
      }
    }
  }

  private renderEdges(state: AnimationState): void {
    if (!this.edgeContainer) return;

    this.edgeContainer.removeChildren();

    for (const [, edge] of state.edges) {
      const source = state.nodes.get(edge.source);
      const target = state.nodes.get(edge.target);
      if (!source || !target) continue;

      const isHighlighted = state.highlights.includes(edge.source) || state.highlights.includes(edge.target);
      const color = isHighlighted
        ? this.hexToNumber(this.theme.edge.highlightColor)
        : this.hexToNumber(edge.style?.color || this.theme.edge.defaultColor);
      const width = isHighlighted ? this.theme.edge.highlightWidth : (edge.style?.strokeWidth || this.theme.edge.defaultWidth);

      const graphics = new PIXI.Graphics();
      graphics.lineStyle(width, color);
      graphics.moveTo(source.position[0], source.position[1]);
      graphics.lineTo(target.position[0], target.position[1]);

      this.edgeContainer.addChild(graphics);

      // 标签
      if (edge.label) {
        const mx = (source.position[0] + target.position[0]) / 2;
        const my = (source.position[1] + target.position[1]) / 2;
        const textStyle = new PIXI.TextStyle({
          fontSize: 10,
          fill: this.hexToNumber(this.theme.text.secondary),
        });
        const text = new PIXI.Text({ text: edge.label, style: textStyle });
        text.anchor.set(0.5, 0.5);
        text.x = mx;
        text.y = my - 8;
        this.edgeContainer.addChild(text);
      }
    }
  }

  private renderGroups(state: AnimationState): void {
    if (!this.groupContainer || !state.groups) return;

    this.groupContainer.removeChildren();

    for (const [, group] of state.groups) {
      const bounds = group.bounds;
      const style = group.style || {};
      const border = this.hexToNumber(style.borderColor || this.theme.group.defaultBorder);
      const fill = this.hexToNumber(style.fillColor || this.theme.group.defaultFill);

      const graphics = new PIXI.Graphics();
      graphics.lineStyle(style.borderWidth || 2, border);
      graphics.beginFill(fill, style.fillOpacity ?? this.theme.group.defaultFillOpacity);
      graphics.drawRoundedRect(bounds.x, bounds.y, bounds.width, bounds.height, style.cornerRadius || 8);
      graphics.endFill();

      this.groupContainer.addChild(graphics);
    }
  }

  private hexToNumber(hex: string): number {
    if (!hex) return 0xffffff;
    const cleaned = hex.replace('#', '');
    return parseInt(cleaned, 16);
  }

  getContainer(): HTMLElement {
    if (!this.container) throw new Error('Renderer not initialized');
    return this.container;
  }

  getCanvasElement(): HTMLCanvasElement | null {
    return this.app?.view || null;
  }

  destroy(): void {
    if (this.app) {
      this.app.destroy(true);
      this.app = null;
    }
    this.nodeObjects.clear();
    if (this.container) {
      this.container.innerHTML = '';
    }
    RENDERER.info('CanvasRenderer destroyed');
  }
}
