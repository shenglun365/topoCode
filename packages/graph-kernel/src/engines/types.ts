import type { EngineCapability } from '../core/capabilities';
import type { DiagramSchema } from '../core/types';

export type ThemeName = 'light' | 'dark';
export type MermaidSecurityLevel = 'strict' | 'loose' | 'antiscript' | 'sandbox';

export interface RenderContext {
  container: HTMLElement;
  code: string;
  theme?: ThemeName;
  /** Mermaid only: click-handler security level (default 'strict'). */
  securityLevel?: MermaidSecurityLevel;
  /** Mermaid only: theme variable overrides (e.g. a catppuccin palette). */
  themeVariables?: Record<string, string | number>;
}

export interface RenderResult {
  svg: string;
  diagramType?: string;
}

export interface ValidationResult {
  valid: boolean;
  error?: string;
  diagramType?: string;
}

export interface DegradeWarning {
  feature: string;
  action: 'dropped' | 'fallback';
  reason: string;
  jsonPath?: string;
}

export interface TranspileResult {
  code: string;
  warnings: DegradeWarning[];
}

export interface TimelineStep {
  label: string;
  reveal: string[];
  hide: string[];
  highlight: string[];
}

export interface EngineOptions {
  /** Base URL of the rendering server (plantuml engine). */
  baseUrl?: string;
  /** 'post-json' = POST {base}/svg JSON {source}（CLI 统一端点，默认）;
      'get-encoded' = GET {base}/svg/{encoded}; 'post-raw' = POST {base}/svg text/plain. */
  protocol?: 'post-json' | 'get-encoded' | 'post-raw';
  /** Extra fetch headers (e.g. the host app's auth bearer). Host-injected; the kernel stays agnostic. */
  headers?: Record<string, string>;
}

/**
 * Engine plugin interface - the extension point for future rendering mechanisms.
 * Register new engines via registerEngine(); core stays engine-agnostic.
 */
export interface DiagramEngine {
  readonly name: string;
  readonly capabilities: EngineCapability;
  validate(code: string): Promise<ValidationResult>;
  render(ctx: RenderContext): Promise<RenderResult>;
  toSource?(schema: DiagramSchema, policy?: 'strict' | 'fallback' | 'drop'): TranspileResult;
  buildTimeline?(schema: DiagramSchema, svgRoot: SVGSVGElement): TimelineStep[];
}
