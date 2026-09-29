/**
 * 官方样本守护（v2 纯帧序列）：封套语义改动导致样本失效时，此处先红（编辑器体验保险）。
 */
import { describe, expect, it } from 'vitest';
import { parseTopoScript, buildTopoStory, TOPO_SAMPLES, type TopoSampleName } from '../src/topo';

function buildSample(name: TopoSampleName) {
  const doc = parseTopoScript(TOPO_SAMPLES[name]);
  return buildTopoStory(doc);
}

describe('TOPO_SAMPLES 守护', () => {
  it('全部样本 parse+build 无 error', () => {
    for (const name of Object.keys(TOPO_SAMPLES) as TopoSampleName[]) {
      const b = buildSample(name);
      const errs = b.errors.filter((e) => e.severity === 'error').map((e) => `${name}@${e.line}: ${e.message}`);
      expect(errs, `sample ${name}`).toEqual([]);
      expect(b.ok).toBe(true);
    }
  });

  it('每帧结构区语法配平（subgraph/end、@startuml/@enduml、{ }）', () => {
    for (const name of Object.keys(TOPO_SAMPLES) as TopoSampleName[]) {
      const b = buildSample(name);
      for (const f of b.frames) {
        const sg = (f.source.match(/^\s*subgraph\b/gm) ?? []).length;
        const en = (f.source.match(/^\s*end\b/gm) ?? []).length;
        expect(sg, `${name}/${f.id} subgraph`).toBeLessThanOrEqual(en);
        if (name === 'plantuml') {
          expect(f.source).toContain('@startuml');
          expect(f.source).toContain('@enduml');
        }
        if (name === 'dot') {
          expect((f.source.match(/\{/g) ?? []).length).toBe((f.source.match(/\}/g) ?? []).length);
        }
      }
    }
  });

  it('bubble：5 帧手写线性链（真实连线进出 + 交换步两端点排序同键）', () => {
    const b = buildSample('bubble');
    expect(b.errors).toEqual([]);
    expect(b.frames.map((f) => f.id)).toEqual(['f1', 'f2', 'f3', 'f4', 'f5']);
    expect(b.graph.entry).toBe('f1');
    expect(b.graph.edges.map((e) => `${e.from}>${e.to}`)).toEqual(['f1>f2', 'f2>f3', 'f3>f4', 'f4>f5']);
    expect(b.frames[0]!.options.step).toBe(1600); // 全局默认生效
    expect(b.frames[1]!.source).toContain('---'); // 建立连线
    expect(b.frames[2]!.source).toContain('---'); // 交换步（连线保留 → morph 拉伸）
  });

  it('dot：3 帧拓扑渐增链；plantuml：4 帧消息逐条累加', () => {
    const d = buildSample('dot');
    expect(d.doc.backend).toBe('dot');
    expect(d.frames).toHaveLength(3);
    expect(d.graph.edges).toHaveLength(2);
    expect(d.frames[2]!.source).toContain('B -> C');
    const p = buildSample('plantuml');
    expect(p.doc.backend).toBe('plantuml');
    expect(p.frames.map((f) => f.id)).toEqual(['f1', 'f2', 'f3', 'f4']);
    expect(p.frames[3]!.source).toContain('OK(session)');
  });
});
