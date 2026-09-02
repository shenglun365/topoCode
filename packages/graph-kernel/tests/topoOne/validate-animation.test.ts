import { afterEach, describe, expect, it } from 'vitest';
import { compileSchemaAnimation } from '../../src/topoOne/animation/compile';
import { createDiagram } from '../../src/topoOne/core/DiagramView';
import type { DiagramSchema } from '../../src/topoOne/core/types';
import { validateSemantics } from '../../src/topoOne/core/validate';

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function flowchart(): DiagramSchema {
  return {
    version: 1,
    type: 'flowchart',
    nodes: [
      { id: 'a', label: 'A' },
      { id: 'b', label: 'B' },
      { id: 'c', label: 'C' },
    ],
    edges: [
      { id: 'e1', from: 'a', to: 'b' },
      { id: 'e2', from: 'b', to: 'c' },
    ],
  };
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('compileSchemaAnimation (schema ids -> selector steps)', () => {
  it('compiles node/edge ids into #id selectors with default labels', () => {
    const doc = flowchart();
    doc.animation = {
      steps: [
        { nodes: ['a'] },
        { label: 'rest', nodes: ['b', 'c'], edges: ['e1', 'e2'] },
      ],
    };
    const compiled = compileSchemaAnimation(doc, doc.animation)!;
    expect(compiled.steps).toHaveLength(2);
    expect(compiled.steps[0]).toEqual({ label: 'Step 1', selectors: ['#a', '[id*="flowchart-a-"]'] });
    expect(compiled.steps[1]).toEqual({
      label: 'rest',
      selectors: ['#b', '[id*="flowchart-b-"]', '#c', '[id*="flowchart-c-"]', '#e1', '#e2'],
    });
  });

  it('passes mode/stepMs through and merges raw selectors', () => {
    const doc = flowchart();
    doc.animation = {
      mode: 'highlight',
      stepMs: 300,
      steps: [{ nodes: ['a'], selectors: ['.legend'] }],
    };
    const compiled = compileSchemaAnimation(doc, doc.animation)!;
    expect(compiled.mode).toBe('highlight');
    expect(compiled.stepMs).toBe(300);
    expect(compiled.steps[0].selectors).toEqual(['#a', '[id*="flowchart-a-"]', '.legend']);
  });

  it('returns null for missing/empty animation', () => {
    expect(compileSchemaAnimation(flowchart(), undefined)).toBeNull();
    const doc = flowchart();
    doc.animation = { steps: [] };
    expect(compileSchemaAnimation(doc, doc.animation)).toBeNull();
  });

  it('adds flowchart DOM-id candidates for the flowchart family only', () => {
    const doc = flowchart();
    doc.animation = { steps: [{ nodes: ['a'] }] };
    // mermaid flowchart node groups are <rid>-flowchart-<id>-<n>
    expect(compileSchemaAnimation(doc, doc.animation)!.steps[0].selectors).toEqual([
      '#a',
      '[id*="flowchart-a-"]',
    ]);
    const seq = {
      version: 1,
      type: 'sequence',
      participants: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }],
      messages: [{ from: 'a', to: 'b', label: 'hi', kind: 'sync' }],
      animation: { steps: [{ nodes: ['a'] }] },
    } as unknown as DiagramSchema;
    expect(compileSchemaAnimation(seq, seq.animation)!.steps[0].selectors).toEqual(['#a']);
  });
});

describe('validateSemantics (mirror of server L3/L4)', () => {
  it('flags empty type-required collections (TYPE_EMPTY)', () => {
    const doc = { version: 1, type: 'gantt', tasks: [] } as unknown as DiagramSchema;
    const r = validateSemantics(doc);
    expect(r.valid).toBe(false);
    expect(r.errors.some((e) => e.path === '/tasks' && e.message.includes("requires non-empty 'tasks'"))).toBe(true);
  });

  it('detects gantt dependency cycles', () => {
    const doc = {
      version: 1,
      type: 'gantt',
      sections: [{ id: 's1', label: 'S' }],
      tasks: [
        { id: 't1', title: 'T1', section: 's1', start: '2026-01-01', duration: 1, dependsOn: ['t3'] },
        { id: 't2', title: 'T2', section: 's1', start: '2026-01-02', duration: 1, dependsOn: ['t1'] },
        { id: 't3', title: 'T3', section: 's1', start: '2026-01-03', duration: 1, dependsOn: ['t2'] },
      ],
    } as unknown as DiagramSchema;
    const r = validateSemantics(doc);
    expect(r.errors.some((e) => e.path === '/tasks' && e.message.includes('t1 -> t3 -> t2 -> t1'))).toBe(true);
  });

  it('checks class relation references and duplicate members', () => {
    const doc = {
      version: 1,
      type: 'class',
      classes: [
        { id: 'c1', name: 'C1', members: [{ name: 'm' }, { name: 'm' }] },
        { id: 'c2', name: 'C2' },
      ],
      classRelations: [{ from: 'c1', to: 'ghost', kind: 'assoc' }],
    } as unknown as DiagramSchema;
    const r = validateSemantics(doc);
    expect(r.errors.some((e) => e.path === '/classRelations/0/to' && e.message.includes("'ghost' does not exist"))).toBe(true);
    expect(r.errors.some((e) => e.path === '/classes/0/members/1')).toBe(true);
  });

  it('flags animation steps referencing unknown ids (per-type id space)', () => {
    const doc = flowchart();
    doc.animation = { steps: [{ nodes: ['ghost'] }, { edges: ['e9'] }] };
    const r = validateSemantics(doc);
    expect(r.valid).toBe(false);
    expect(r.errors.some((e) => e.path === '/animation/steps/0/nodes/0' && e.message.includes("'ghost'"))).toBe(true);
    expect(r.errors.some((e) => e.path === '/animation/steps/1/edges/0' && e.message.includes("'e9'"))).toBe(true);
  });

  it('resolves sequence animation nodes against participants', () => {
    const doc = {
      version: 1,
      type: 'sequence',
      participants: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }],
      messages: [{ from: 'a', to: 'b', label: 'hi', kind: 'sync' }],
      animation: { steps: [{ nodes: ['a', 'b'] }] },
    } as unknown as DiagramSchema;
    expect(validateSemantics(doc).valid).toBe(true);
  });

  it('rejects animation edges for edge-less types', () => {
    const doc = {
      version: 1,
      type: 'sequence',
      participants: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }],
      messages: [{ from: 'a', to: 'b', label: 'hi', kind: 'sync' }],
      animation: { steps: [{ nodes: ['a'], edges: ['m1'] }] },
    } as unknown as DiagramSchema;
    const r = validateSemantics(doc);
    expect(r.errors.some((e) => e.path === '/animation/steps/0/edges/0' && e.message.includes('no addressable edges'))).toBe(true);
  });

  it('collects orphan nodes and self loops as warnings, not errors', () => {
    const doc = flowchart();
    doc.nodes!.push({ id: 'd', label: 'D' });
    doc.edges!.push({ id: 'e3', from: 'a', to: 'a' });
    const r = validateSemantics(doc);
    expect(r.valid).toBe(true);
    expect(r.warnings.some((w) => w.message.includes("node 'd' has no edges"))).toBe(true);
    expect(r.warnings.some((w) => w.message.includes("edge from node 'a' to itself"))).toBe(true);
  });
});

describe('createDiagram wiring: schema animation block drives playback', () => {
  it('schema-level animation produces a controller (fallback-safe)', async () => {
    const el = document.createElement('div');
    el.style.width = '400px';
    el.style.height = '200px';
    document.body.appendChild(el);
    const doc = flowchart();
    doc.animation = { mode: 'reveal', stepMs: 200, steps: [{ label: 'first', nodes: ['a'] }] };
    const view = createDiagram(el, {
      source: { engine: 'mermaid', schema: doc },
      animation: { enabled: true, autoPlay: false },
      interactions: { zoomPan: false, export: false, nodeClick: false },
    });
    await sleep(500);
    expect(view.getAnimation()).not.toBeNull();
    view.destroy();
  }, 15000);

  it('user-provided steps take precedence over the schema animation block', async () => {
    const el = document.createElement('div');
    el.style.width = '400px';
    el.style.height = '200px';
    document.body.appendChild(el);
    const doc = flowchart();
    doc.animation = { steps: [{ label: 'schema', nodes: ['a', 'b', 'c'] }] };
    const view = createDiagram(el, {
      source: { engine: 'mermaid', schema: doc },
      animation: {
        enabled: true,
        autoPlay: false,
        steps: [{ label: 'user', selectors: ['.flowchart-link'] }],
      },
      interactions: { zoomPan: false, export: false, nodeClick: false },
    });
    await sleep(500);
    // user steps (3 links) win over schema steps (3 nodes) -> 1 step total
    expect(view.getAnimation()!.total).toBe(1);
    view.destroy();
  }, 15000);
});
