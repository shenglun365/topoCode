import { describe, expect, it } from 'vitest';
import { MermaidEngine } from '../../src/engines/mermaid/mermaid';
import {
  resolveAdapter,
  mermaidSequenceAdapter,
  plantumlSequenceAdapter,
  mermaidGanttAdapter,
  mermaidGenericAdapter,
  plantumlGenericAdapter,
} from '../../src/animation/adapters';
import { guessType } from '../../src/animation/guessType';

async function renderMermaid(code: string): Promise<SVGSVGElement> {
  const el = document.createElement('div');
  document.body.appendChild(el);
  const res = await new MermaidEngine().render({ container: el, code, theme: 'dark' });
  el.innerHTML = res.svg;
  return el.querySelector('svg')!;
}

function svgFrom(html: string): SVGSVGElement {
  const el = document.createElement('div');
  el.innerHTML = html;
  return el.querySelector('svg')!;
}

describe('guessType', () => {
  it('detects mermaid types from the first keyword', () => {
    expect(guessType('sequenceDiagram\n  A->>B: x')).toBe('sequence');
    expect(guessType('gantt\n  title T')).toBe('gantt');
    expect(guessType('flowchart TD\n  A-->B')).toBe('flowchart');
    expect(guessType('graph LR\n  A-->B')).toBe('flowchart');
    expect(guessType('stateDiagram-v2\n  [*]-> A')).toBe('state');
    expect(guessType('classDiagram\n  class A')).toBe('class');
    expect(guessType('erDiagram\n  A ||--o{ B')).toBe('er');
    expect(guessType('C4Context\n  Person("a")')).toBe('architecture');
    expect(guessType('something else entirely')).toBe('any');
  });

  it('detects plantuml types from body heuristics', () => {
    expect(guessType('@startuml\nstart\n:do it;\nstop\n@enduml')).toBe('activity');
    expect(guessType('@startuml\nAlice -> Bob : hi\n@enduml')).toBe('sequence');
    expect(guessType('@startuml\nrectangle "x"\n@enduml')).toBe('any');
  });
});

describe('resolveAdapter', () => {
  it('prefers exact engine+type matches', () => {
    expect(resolveAdapter('mermaid', 'sequence')).toBe(mermaidSequenceAdapter);
    expect(resolveAdapter('plantuml', 'sequence')).toBe(plantumlSequenceAdapter);
    expect(resolveAdapter('mermaid', 'gantt')).toBe(mermaidGanttAdapter);
  });

  it('falls back to the engine-generic adapter', () => {
    expect(resolveAdapter('mermaid', 'flowchart')).toBe(mermaidGenericAdapter);
    expect(resolveAdapter('plantuml', 'activity')).toBe(plantumlGenericAdapter);
  });
});

describe('mermaid sequence adapter', () => {
  it('builds participants + one step per message', async () => {
    const svg = await renderMermaid('sequenceDiagram\n  Alice->>Bob: hello\n  Bob-->>Alice: hi\n  Alice->>Carol: bye');
    const plan = resolveAdapter('mermaid', 'sequence')!.build(svg, '');
    expect(plan).not.toBeNull();
    expect(plan!.mode).toBe('reveal');
    expect(plan!.steps).toHaveLength(4);
    expect(plan!.steps[0].label).toBe('participants');
    expect(plan!.steps[1].label).toBe('hello');
    expect(plan!.steps[2].label).toBe('hi');
    expect(plan!.steps[3].label).toBe('bye');
    for (let i = 1; i < 4; i++) expect(plan!.steps[i].elements).toHaveLength(2);
  });

  it('returns null when there are no messages', async () => {
    const svg = await renderMermaid('sequenceDiagram\n  participant Alice');
    const plan = mermaidSequenceAdapter.build(svg, '');
    expect(plan).toBeNull();
  });
});

describe('mermaid gantt adapter', () => {
  it('builds timeline frame + one step per task', async () => {
    const svg = await renderMermaid(
      'gantt\n  title Roadmap\n  section Core\n  Task A :a, 2024-01-01, 10d\n  Task B :b, after a, 5d\n  section Extra\n  Task C :c, 2024-02-01, 7d',
    );
    const plan = mermaidGanttAdapter.build(svg, '');
    expect(plan).not.toBeNull();
    expect(plan!.steps).toHaveLength(4);
    expect(plan!.steps[0].label).toBe('timeline');
    expect(plan!.steps[1].label).toContain('Task A');
    expect(plan!.steps[2].label).toContain('Task B');
    expect(plan!.steps[3].label).toContain('Task C');
    for (let i = 1; i < 4; i++) expect(plan!.steps[i].elements).toHaveLength(2);
  });
});

describe('plantuml sequence adapter (fixture)', () => {
  const FIXTURE = `
    <svg xmlns="http://www.w3.org/2000/svg">
      <g class="participant participant-head" data-entity-uid="part1" data-qualified-name="Alice" id="part1-head"><text>Alice</text></g>
      <g class="participant-lifeline" data-entity-uid="part1" id="part1-lifeline"></g>
      <g class="participant participant-head" data-entity-uid="part2" data-qualified-name="Bob" id="part2-head"><text>Bob</text></g>
      <g class="message" data-entity-1="part1" data-entity-2="part2" data-source-line="1" id="msg1"><text>hello</text></g>
      <g class="message" data-entity-1="part2" data-entity-2="part1" data-source-line="2" id="msg2"><text>hi</text></g>
    </svg>`;

  it('builds participants + one step per message group', () => {
    const plan = plantumlSequenceAdapter.build(svgFrom(FIXTURE), '');
    expect(plan).not.toBeNull();
    expect(plan!.steps).toHaveLength(3);
    expect(plan!.steps[0].label).toBe('participants');
    expect(plan!.steps[0].elements).toHaveLength(3);
    expect(plan!.steps[1].label).toBe('hello');
    expect(plan!.steps[2].label).toBe('hi');
  });
});

describe('generic adapters', () => {
  it('plantuml groups elements by data-source-line in order', () => {
    const html = `
      <svg xmlns="http://www.w3.org/2000/svg">
        <rect data-source-line="3"></rect>
        <rect data-source-line="1"></rect>
        <rect data-source-line="1"></rect>
        <rect data-source-line="2"></rect>
      </svg>`;
    const plan = plantumlGenericAdapter.build(svgFrom(html), '');
    expect(plan!.steps).toHaveLength(3);
    expect(plan!.steps[0].elements).toHaveLength(2);
    expect(plan!.steps.map((s) => s.label)).toEqual(['line 1', 'line 2', 'line 3']);
  });

  it('mermaid reveals identifiable elements in document order', () => {
    const html = `
      <svg xmlns="http://www.w3.org/2000/svg">
        <g id="a"><text>Alpha</text></g>
        <g id="b"><text>Beta</text></g>
      </svg>`;
    const plan = mermaidGenericAdapter.build(svgFrom(html), '');
    expect(plan!.steps).toHaveLength(2);
    expect(plan!.steps[0].label).toBe('Alpha');
  });
});
