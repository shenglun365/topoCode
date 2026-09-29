import { describe, expect, it } from 'vitest';
import { capture } from '../src/core/capture';
import { keydiff } from '../src/core/diff';
import { buildTimeline } from '../src/core/timeline';
import { mermaidRules } from '../src/backends';

function mermaidSvg(): string {
  const node = (id: string, idx: number, x: number) =>
    `<g class="node" id="flowchart-${id}-${idx}" transform="translate(${x} 10)"><rect width="40" height="20"/></g>`;
  const edge = (a: string, b: string) =>
    `<path d="M 0 0 L 10 0" id="L_${a}_${b}_0" class="flowchart-link"/>`;
  return '<svg xmlns="http://www.w3.org/2000/svg" class="flowchart"><g class="output">'
    + `<g class="edges">${edge('A', 'B')}${edge('B', 'C')}${edge('C', 'D')}</g>`
    + `<g class="nodes">${node('A', 0, 0)}${node('B', 1, 100)}${node('C', 2, 200)}${node('D', 3, 300)}</g>`
    + '</g></svg>';
}

describe('order:degree —— capture BFS 波次', () => {
  it('链式图 A→B→C→D：端点解析与深度回填', () => {
    const { spec } = capture(mermaidSvg(), mermaidRules);
    const d = (key: string) => spec.elements.find((e) => e.key === key)!.depth;
    expect(d('ta:mermaid:name:A')).toBe(0);
    expect(d('ta:mermaid:name:B')).toBe(1);
    expect(d('ta:mermaid:name:C')).toBe(2);
    expect(d('ta:mermaid:name:D')).toBe(3);
    expect(d('ta:mermaid:name:A~B')).toBe(0.5); // 边随源节点之后
    expect(d('ta:mermaid:name:C~D')).toBe(2.5);
  });

  it('enter 全量帧按 degree 排序：源先于目标，边居中', () => {
    const { spec } = capture(mermaidSvg(), mermaidRules);
    const empty = { elements: [], width: 0, height: 0, type: '', backend: '' };
    const diff = keydiff(empty as never, spec);
    const t = buildTimeline(diff, { opts: { order: 'degree', staggerMs: 100 } }, 900);
    const keys = t.items.map((i) => i.key);
    expect(keys.indexOf('ta:mermaid:name:A')).toBeLessThan(keys.indexOf('ta:mermaid:name:A~B'));
    expect(keys.indexOf('ta:mermaid:name:A~B')).toBeLessThan(keys.indexOf('ta:mermaid:name:B'));
    expect(keys.indexOf('ta:mermaid:name:D')).toBe(keys.length - 1);
    // 延迟随波次递增
    const delays = t.items.map((i) => i.delayMs);
    expect([...delays].sort((a, b) => a - b)).toEqual(delays);
  });

  it('无端点信息时 degree 退化为文档序（安全兜底）', () => {
    const { spec } = capture('<svg xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="4" height="4"/><rect x="10" y="10" width="4" height="4"/></svg>');
    const empty = { elements: [], width: 0, height: 0, type: '', backend: '' };
    const t = buildTimeline(keydiff(empty as never, spec), { opts: { order: 'degree' } }, 900);
    expect(t.items.map((i) => i.el.source.docIndex)).toEqual([0, 1]);
  });
});
