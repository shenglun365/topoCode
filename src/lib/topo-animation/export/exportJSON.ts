/**
 * JSON 数据导出
 * @module export/exportJSON
 *
 * @description
 * 导出动画数据为 JSON 格式。
 */

import type { AnimationState } from '../core/types';
import type { AnimationInstruction } from '../core/instructions/InstructionTypes';

export interface ExportJSONOptions {
  /** 指令 */
  instructions?: AnimationInstruction[];
  /** 状态 */
  states?: AnimationState[];
  /** 格式化 */
  pretty?: boolean;
}

/**
 * 导出为 JSON
 */
export function exportJSON(options: ExportJSONOptions): string {
  const data: any = {};

  if (options.instructions) {
    data.instructions = options.instructions;
  }

  if (options.states) {
    data.states = options.states.map((state) => ({
      ...state,
      nodes: Array.from(state.nodes.entries()),
      edges: Array.from(state.edges.entries()),
      groups: state.groups ? Array.from(state.groups.entries()) : undefined,
    }));
  }

  const indent = options.pretty ? 2 : undefined;
  return JSON.stringify(data, null, indent);
}

/**
 * 下载 JSON
 */
export function downloadJSON(json: string, filename: string = 'animation.json'): void {
  const blob = new Blob([json], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
