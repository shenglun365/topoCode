/**
 * 单帧预览编译（T4 编辑器 [渲帧]）：TopoScript 结构区原文 → 独立 SVG。
 * 与整图编译同路（backend.render → capture → sanitize），零状态副作用。
 */

import type { AnimBackend } from '../backends';
import { capture, genericRules, type CaptureRules } from '../core/capture';
import { staticSvgString } from '../core/sanitize';

export interface FramePreview {
  svg: string;
  error?: string;
}

export async function renderTopoFramePreview(
  backend: AnimBackend | null,
  source: string,
  rules?: CaptureRules,
): Promise<FramePreview> {
  if (!source.trim()) return { svg: '', error: '结构区为空' };
  if (!backend) return { svg: '', error: '后端未就绪' };
  try {
    const rendered = await backend.render(source);
    const cap = capture(rendered, rules ?? backend.rules ?? genericRules);
    return { svg: staticSvgString(cap.svg, cap.spec.background) };
  } catch (e) {
    return { svg: '', error: (e as Error).message };
  }
}
