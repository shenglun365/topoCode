import mermaid from 'mermaid';
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
      const result = (await mermaid.parse(code)) as { diagramType?: string } | undefined;
      return { valid: true, diagramType: result?.diagramType };
    } catch (err) {
      return { valid: false, error: err instanceof Error ? err.message : String(err) };
    }
  }

  async render(ctx: RenderContext): Promise<RenderResult> {
    this.theme = ctx.theme ?? this.theme;
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
