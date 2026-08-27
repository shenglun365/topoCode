/// <reference path="../../plantuml-encoder.d.ts" />
import DOMPurify from 'dompurify';
import { encode as plantumlEncode } from 'plantuml-encoder';
import { getCapability } from '../../core/capabilities';
import type { DiagramSchema } from '../../core/types';
import { toPlantUml, type DegradationPolicy } from '../../core/transpile';
import type { DiagramEngine, EngineOptions, RenderContext, RenderResult, TranspileResult, ValidationResult } from '../types';

const KEEP_ATTRS = [
  'data-entity-uid',
  'data-qualified-name',
  'data-entity-1',
  'data-entity-2',
  'data-source-line',
  'class',
  'id',
];

function extractErrorMessage(svg: string): string | undefined {
  const texts = [...svg.matchAll(/<text[^>]*>([^<]*)<\/text>/g)]
    .map((m) => m[1].trim())
    .filter(Boolean);
  return texts.length ? texts.join('\n') : undefined;
}

/**
 * PlantUML engine - renders via a server (JVM sidecar, kroki or plantuml.com).
 * The SVG response is inlined (not <img>) so interaction plugins can attach to it;
 * entity mapping and sequence animation rely on data-entity-* / data-source-line attrs.
 */
export class PlantUmlEngine implements DiagramEngine {
  readonly name = 'plantuml';
  readonly capabilities = getCapability('plantuml')!;
  private baseUrl: string;
  private protocol: 'get-encoded' | 'post-raw';
  private headers: Record<string, string>;

  constructor(options: EngineOptions = {}) {
    this.baseUrl = (options.baseUrl ?? 'http://127.0.0.1:3491').replace(/\/+$/, '');
    this.protocol = options.protocol ?? 'get-encoded';
    this.headers = options.headers ?? {};
  }

  toSource(schema: DiagramSchema, policy: DegradationPolicy = 'drop'): TranspileResult {
    return toPlantUml(schema, policy);
  }

  private async fetchSvg(code: string): Promise<{ status: number; body: string }> {
    let res: Response;
    if (this.protocol === 'get-encoded') {
      res = await fetch(`${this.baseUrl}/svg/${plantumlEncode(code)}`, { headers: this.headers });
    } else {
      res = await fetch(`${this.baseUrl}/plantuml/svg`, {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain', ...this.headers },
        body: code,
      });
    }
    return { status: res.status, body: await res.text() };
  }

  async render(ctx: RenderContext): Promise<RenderResult> {
    const { status, body } = await this.fetchSvg(ctx.code);
    if (status !== 200) throw new Error(`plantuml server returned HTTP ${status}`);
    if (/syntax error/i.test(body)) {
      throw new Error(extractErrorMessage(body) ?? 'plantuml syntax error');
    }
    const clean = DOMPurify.sanitize(body, {
      USE_PROFILES: { svg: true, svgFilters: true },
      ADD_ATTR: KEEP_ATTRS,
    });
    return { svg: clean };
  }

  async validate(code: string): Promise<ValidationResult> {
    const { status, body } = await this.fetchSvg(code);
    if (status === 400) {
      return { valid: false, error: extractErrorMessage(body) ?? 'plantuml syntax error' };
    }
    if (status === 302 || status >= 400) {
      return { valid: false, error: `plantuml server returned HTTP ${status}` };
    }
    if (/syntax error/i.test(body)) {
      return { valid: false, error: extractErrorMessage(body) ?? 'plantuml syntax error' };
    }
    return { valid: true };
  }
}
