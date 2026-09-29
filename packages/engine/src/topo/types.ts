/**
 * TopoScript v2 —— 作者层文档模型（docs/topo-script.md 规范）
 *
 * **纯帧序列模型**：帧 = 静态结构源文本（mermaid/plantuml/dot 原文，独立可渲染），
 * 播放 = 帧序推进 + 帧间 diff 过渡动画。无任何脚本逻辑（v1 的 @@logic/@generate/@vars
 * 已按主线原则整通道移除）。
 *
 * 信封自建成分仅定界：@version/@backend/@options + @@frame/@@source。
 */

export type TopoSeverity = 'error' | 'warning';

export interface TopoDiagnostic {
  line: number;
  message: string;
  severity: TopoSeverity;
  /** 封闭诊断码（TOPO_DIAG_CODES），Agent/修复循环消费 */
  code?: string;
  /** subject：关联帧 id */
  frame?: string;
  /** 机器可读修复建议（诊断面板/Agent 消费） */
  supportedFixes?: string[];
}

/** 帧 = 静态结构源文 + 帧级播放选项（auto/step/enter/exit/order/…） */
export interface TopoFrame {
  id: string;
  /** @@source 区原文（独立可渲染的原生脚本） */
  source: string;
  /** @@frame 行的选项覆写（对"进入该帧"的过渡与驻留生效） */
  options: Record<string, string | number | boolean>;
  /** @@frame / @@source 行号（诊断定位，1-based） */
  frameLine: number;
  sourceLine: number;
}

export interface TopoDocument {
  version: number;
  backend: string;
  /** @options 全局默认（auto/step/enter/exit/order/duration/stagger…） */
  options: Record<string, string | number | boolean>;
  frames: TopoFrame[];
  errors: TopoDiagnostic[];
}

export const TOPO_DEFAULTS = {
  version: 2,
  backend: 'mermaid',
} as const;

export function emptyDocument(): TopoDocument {
  return {
    version: TOPO_DEFAULTS.version,
    backend: TOPO_DEFAULTS.backend,
    options: {},
    frames: [],
    errors: [],
  };
}
