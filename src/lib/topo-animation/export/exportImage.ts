/**
 * 静态图片导出
 * @module export/exportImage
 *
 * @description
 * 导出当前帧为 PNG 或 SVG 图片。
 */

import type { IRenderer } from '../renderer/IRenderer';

export interface ExportImageOptions {
  /** 渲染器 */
  renderer: IRenderer;
  /** 格式 */
  format?: 'png' | 'svg';
  /** PNG 质量 (0-1) */
  quality?: number;
  /** 缩放倍数 */
  scale?: number;
}

/**
 * 导出为 PNG
 */
export async function exportPNG(options: ExportImageOptions): Promise<Blob> {
  const { renderer, quality = 0.92, scale = 1 } = options;

  const canvasEl = renderer.getCanvasElement?.();
  const svgEl = renderer.getSVGElement?.();

  if (canvasEl) {
    // Canvas 直接导出
    return new Promise((resolve) => {
      canvasEl.toBlob((blob) => resolve(blob!), 'image/png', quality);
    });
  }

  if (svgEl) {
    // SVG 转 Canvas 再转 PNG
    const svgData = new XMLSerializer().serializeToString(svgEl);
    const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(svgBlob);

    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const canvas = document.createElement('canvas');
        canvas.width = svgEl.viewBox.baseVal.width * scale;
        canvas.height = svgEl.viewBox.baseVal.height * scale;
        const ctx = canvas.getContext('2d');
        if (!ctx) {
          reject(new Error('Cannot get canvas context'));
          return;
        }
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        canvas.toBlob((blob) => {
          URL.revokeObjectURL(url);
          resolve(blob!);
        }, 'image/png', quality);
      };
      img.onerror = () => reject(new Error('Failed to load SVG'));
      img.src = url;
    });
  }

  throw new Error('No renderable element found');
}

/**
 * 导出为 SVG
 */
export function exportSVG(options: ExportImageOptions): string {
  const svgEl = options.renderer.getSVGElement?.();

  if (!svgEl) {
    throw new Error('SVG element not found');
  }

  return new XMLSerializer().serializeToString(svgEl);
}

/**
 * 导出图片（通用）
 */
export async function exportImage(
  renderer: IRenderer,
  format: 'png' | 'svg' = 'png',
  options?: { quality?: number; scale?: number }
): Promise<Blob | string> {
  if (format === 'svg') {
    return exportSVG({ renderer, format: 'svg' });
  }
  return exportPNG({ renderer, format: 'png', ...options });
}

/**
 * 下载图片
 */
export function downloadImage(
  data: Blob | string,
  filename: string = 'animation.png',
  format: 'png' | 'svg' = 'png'
): void {
  const url = data instanceof Blob ? URL.createObjectURL(data) : `data:image/svg+xml;charset=utf-8,${encodeURIComponent(data)}`;
  const link = document.createElement('a');
  link.href = url;
  link.download = filename.endsWith('.svg') ? filename : `${filename}.${format}`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);

  if (data instanceof Blob) {
    URL.revokeObjectURL(url);
  }
}
