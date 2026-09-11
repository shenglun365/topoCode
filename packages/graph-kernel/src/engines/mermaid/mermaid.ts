// mermaid(含 d3 全家桶, ~1MB+) 按需动态加载: 不静态进主包, 首次渲染/校验时拉起
type MermaidApi = typeof import('mermaid').default;
let _mermaidPromise: Promise<MermaidApi> | null = null;

function loadMermaid(): Promise<MermaidApi> {
  _mermaidPromise ??= import('mermaid').then((m) => (m.default ?? m) as MermaidApi);
  return _mermaidPromise;
}
import { getCapability } from '../../core/capabilities';
import type { DiagramSchema } from '../../core/types';
import { toMermaid, type DegradationPolicy } from '../../core/transpile';
import type { DiagramEngine, RenderContext, RenderResult, TranspileResult, ValidationResult } from '../types';

let idSeq = 0;

export class MermaidEngine implements DiagramEngine {
  readonly name = 'mermaid';
  readonly capabilities = getCapability('mermaid')!;
  private theme: 'light' | 'dark' = 'dark';

  toSource(schema: DiagramSchema, policy: DegradationPolicy = 'drop'): TranspileResult {
    return toMermaid(schema, policy);
  }

  async validate(code: string): Promise<ValidationResult> {
    try {
      const mermaid = await loadMermaid();
      const result = (await mermaid.parse(code)) as { diagramType?: string } | undefined;
      return { valid: true, diagramType: result?.diagramType };
    } catch (err) {
      return { valid: false, error: err instanceof Error ? err.message : String(err) };
    }
  }

  async render(ctx: RenderContext): Promise<RenderResult> {
    this.theme = ctx.theme ?? this.theme;
    const mermaid = await loadMermaid();
    mermaid.initialize({
      startOnLoad: false,
      // default 'strict': agent-generated source is untrusted; inline click callbacks are stripped.
      securityLevel: ctx.securityLevel ?? 'strict',
      theme: this.theme === 'dark' ? 'dark' : 'default',
      ...(ctx.themeVariables ? { themeVariables: ctx.themeVariables } : {}),
      flowchart: { useMaxWidth: true },
    });
    const id = `topo-one-mmd-${++idSeq}`;
    const result = await mermaid.render(id, ctx.code);
    return { svg: result.svg };
  }
}

// ── 共享 mermaid 访问（20c 合一：原 web-core services/render.ts 内私有单例删除） ──
// mermaid 模块本身即单例；此处只统一「首次 initialize」。渲染路径（render()）
// 仍按 ctx 每次覆盖配置；预览/解析等旁路经此拿到 antiscript 基线配置的 API。
let _ensureDone = false;

export async function ensureMermaid() {
  const mermaid = await loadMermaid();
  if (!_ensureDone) {
    mermaid.initialize({ startOnLoad: false, securityLevel: 'antiscript', theme: 'default' });
    _ensureDone = true;
  }
  return mermaid;
}

export function mermaidParseErrorDetail(e: any): string {
  const raw = e && (e.message || e.str || e.hash || String(e));
  return (raw && String(raw).trim()) || '图解法错误';
}
