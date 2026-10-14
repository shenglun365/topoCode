import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import mermaid from 'mermaid';
import { describe, expect, it } from 'vitest';
import { CAPABILITIES, supportsType } from '../../src/core/capabilities';
import { TranspileError, toMermaid, toPlantUml } from '../../src/core/transpile';
import type { DiagramSchema } from '../../src/core/types';
import { DIAGRAM_TYPES } from '../../src/core/types';
import { samples } from './samples';

const here = dirname(fileURLToPath(import.meta.url));
const golden = (engine: 'mermaid' | 'plantuml', name: string) =>
  readFileSync(resolve(here, `golden/${engine}/${name}.${engine === 'mermaid' ? 'mmd' : 'puml'}`), 'utf8');

describe('transpile goldens', () => {
  for (const name of Object.keys(samples)) {
    it(`mermaid :: ${name} matches golden`, () => {
      expect(toMermaid(samples[name]).code).toBe(golden('mermaid', name));
    });
    if (name !== 'gantt') {
      it(`plantuml :: ${name} matches golden`, () => {
        expect(toPlantUml(samples[name]).code).toBe(golden('plantuml', name));
      });
    }
  }
});

describe('transpile integration: mermaid parses its own output', () => {
  for (const name of Object.keys(samples)) {
    it(`mermaid.parse accepts toMermaid(${name})`, async () => {
      const { code } = toMermaid(samples[name]);
      await expect(mermaid.parse(code)).resolves.toBeTruthy();
    });
  }
});

describe('unsupported types', () => {
  it('plantuml rejects gantt with a helpful error', () => {
    try {
      toPlantUml(samples.gantt);
      expect.unreachable('should throw');
    } catch (e) {
      expect(e).toBeInstanceOf(TranspileError);
      expect((e as TranspileError).message).toContain("use engine 'mermaid'");
    }
  });
});

describe('degradation policies', () => {
  const usecase = samples.usecase;

  it('strict: emulated type throws', () => {
    expect(() => toMermaid(usecase, 'strict')).toThrow(TranspileError);
  });

  it('drop (default): emulated type warns with jsonPath', () => {
    const r = toMermaid(usecase);
    expect(r.warnings.some((w) => w.feature === 'type.usecase' && w.action === 'dropped' && w.jsonPath === '/type')).toBe(true);
  });

  it('flowchart dotted edge degrades to dashed with warning', () => {
    const schema: DiagramSchema = {
      version: 1,
      type: 'flowchart',
      nodes: [
        { id: 'a', label: 'A' },
        { id: 'b', label: 'B' },
      ],
      edges: [{ from: 'a', to: 'b', kind: 'dotted' }],
    };
    const m = toMermaid(schema);
    expect(m.code).toContain('-.->');
    expect(m.warnings.some((w) => w.feature === 'edge.line')).toBe(true);
    const p = toPlantUml(schema);
    expect(p.code).toContain('..>');
    expect(p.warnings).toHaveLength(0); // dotted is native in plantuml freeform
  });
});

describe('capability matrix completeness', () => {
  it('every engine declares support for all diagram types', () => {
    for (const engine of Object.keys(CAPABILITIES.engines)) {
      for (const type of DIAGRAM_TYPES) {
        expect(supportsType(engine, type), `${engine} missing type ${type}`).not.toBe('');
      }
    }
  });

  it('gantt is unsupported on plantuml (drives auto negotiation to mermaid)', () => {
    expect(supportsType('plantuml', 'gantt')).toBe('unsupported');
  });
});
