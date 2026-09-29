/**
 * 样本后端真渲染守护（headless）：dot 走 @hpcc-js/wasm-graphviz，plantuml 走本地 api(:3721) java 服务。
 * 服务不可达时 plantuml 组自动 skip（CI 友好）；mermaid 无浏览器环境不在此覆盖（浏览器实测）。
 */
import { describe, expect, it } from 'vitest';
import { parseTopoScript, buildTopoStory, TOPO_SAMPLES } from '../src/topo';
import { createGraphvizBackend, createPlantumlBackend } from '../src/backends';
import type { CaptureRules } from '../src/core/capture';
import { capture } from '../src/core/capture';

async function renderAll(backend: { render(s: string): Promise<string | Element>; rules: CaptureRules }, sample: 'dot' | 'plantuml') {
  const b = buildTopoStory(parseTopoScript(TOPO_SAMPLES[sample]));
  expect(b.ok).toBe(true);
  for (const f of b.frames) {
    const svg = await backend.render(f.source);
    if (typeof svg === 'string') expect(svg, `${sample}/${f.id}`).toContain('<svg');
    const cap = capture(svg, backend.rules);
    expect(cap.spec.elements.length, `${sample}/${f.id} 元素数`).toBeGreaterThan(1);
  }
  return b;
}

describe('dot 样本真实渲染（wasm graphviz）', () => {
  it('三帧全部 render+capture 成功，节点拿到 name 键', async () => {
    const { Graphviz } = await import('@hpcc-js/wasm-graphviz');
    const backend = createGraphvizBackend(async (n) => (n === '@hpcc-js/wasm-graphviz' ? { Graphviz } : {} as never));
    const b = buildTopoStory(parseTopoScript(TOPO_SAMPLES.dot));
    for (const f of b.frames) {
      const svg = await backend.render(f.source);
      const cap = capture(svg, backend.rules);
      expect(cap.spec.elements.filter((e) => e.kind === 'node').map((e) => e.key)).toContain('ta:dot:name:A');
    }
    expect(b.frames).toHaveLength(3);
  });
});

describe('plantuml 样本真实渲染（本地 java 服务）', () => {
  const EP = process.env.TOPO_PUML_ENDPOINT ?? 'http://localhost:3721/plantuml';

  it('四帧 @startuml 序列图全部出图，参与者有稳定键', async () => {
    let alive = true;
    try {
      await fetch(`${EP}/svg`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ source: '@startuml\nA -> B: x\n@enduml' }) });
    } catch { alive = false; }
    if (!alive) { console.warn('[skip] plantuml 服务不可达（pnpm dev 未起 api:3721）'); return; }
    const backend = createPlantumlBackend(EP);
    const b = await renderAll(backend, 'plantuml');
    expect(b.frames).toHaveLength(4);
    const cap = capture(await backend.render!(b.frames[0]!.source), backend.rules);
    const nodes = cap.spec.elements.filter((e) => e.kind === 'node').map((e) => e.key);
    expect(nodes.some((k) => k.endsWith(':Alice'))).toBe(true);
    expect(nodes.some((k) => k.endsWith(':Bob'))).toBe(true);
  });
});
