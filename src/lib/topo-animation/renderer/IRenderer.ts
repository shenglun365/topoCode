/**
 * 渲染器接口
 * @module renderer/IRenderer
 */

import type { AnimationState, RenderOptions } from '../core/types';

/** 渲染器接口 */
export interface IRenderer {
  /** 初始化渲染器 */
  init(options: RenderOptions): void;

  /** 渲染一帧 */
  render(state: AnimationState): void;

  /** 销毁渲染器 */
  destroy(): void;

  /** 获取渲染容器 */
  getContainer(): HTMLElement;

  /** 获取 SVG 元素（如适用） */
  getSVGElement?(): SVGSVGElement | null;

  /** 获取 Canvas 元素（如适用） */
  getCanvasElement?(): HTMLCanvasElement | null;
}
