import { describe, expect, it } from 'vitest';
import { validateDiagram, validateSchema } from '../../src/topoOne/core/validate';

const validSequence = {
  version: 1,
  type: 'sequence',
  participants: [
    { id: 'a', label: 'Alice' },
    { id: 'b', label: 'Bob' },
  ],
  messages: [{ from: 'a', to: 'b', label: 'hello', kind: 'sync' }],
};

describe('validateSchema', () => {
  it('accepts a valid sequence schema', () => {
    expect(validateDiagram(validSequence).valid).toBe(true);
  });

  it('rejects an unknown diagram type', () => {
    expect(validateSchema({ version: 1, type: 'nope' }).valid).toBe(false);
  });

  it('requires participants+messages for sequence', () => {
    expect(validateSchema({ version: 1, type: 'sequence' }).valid).toBe(false);
  });

  it('requires nodes for flowchart', () => {
    expect(validateSchema({ version: 1, type: 'flowchart' }).valid).toBe(false);
  });

  it('rejects unknown top-level properties', () => {
    const bad = { ...validSequence, bogus: 1 };
    expect(validateSchema(bad).valid).toBe(false);
  });
});

describe('validateSemantics', () => {
  it('flags dangling edge references', () => {
    const r = validateDiagram({
      version: 1,
      type: 'flowchart',
      nodes: [{ id: 'a', label: 'A' }],
      edges: [{ from: 'a', to: 'ghost' }],
    });
    expect(r.valid).toBe(false);
    expect(r.errors.some((e) => e.path === '/edges/0/to' && e.message.includes("'ghost' does not exist"))).toBe(true);
  });

  it('flags duplicate node ids', () => {
    const r = validateDiagram({
      version: 1,
      type: 'flowchart',
      nodes: [
        { id: 'a', label: 'A' },
        { id: 'a', label: 'A2' },
      ],
    });
    expect(r.valid).toBe(false);
    expect(r.errors.some((e) => e.message.includes('duplicate'))).toBe(true);
  });

  it('flags dangling gantt dependsOn', () => {
    const r = validateDiagram({
      version: 1,
      type: 'gantt',
      sections: [{ id: 's1', label: 'S1' }],
      tasks: [
        { id: 't1', title: 'T1', section: 's1', start: '2026-01-01', duration: 3 },
        { id: 't2', title: 'T2', section: 's1', start: '2026-01-05', duration: 2, dependsOn: ['nope'] },
      ],
    });
    expect(r.valid).toBe(false);
  });
});
