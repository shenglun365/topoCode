import { describe, expect, it } from 'vitest';
import { capture } from '../src/core/capture';
import { keydiff } from '../src/core/diff';
import {
  createOfflineBackend, dotRules, mermaidRules, plantumlRules,
  resolveBackend, scoreAdapter, type AnimBackend, type BackendRegistration,
} from '../src/backends';
import { plantumlSeqBase, plantumlSeqChanged } from './fixtures/plantuml';
import { svgDoc } from './fixtures';

/* --------- mermaid v10 真实结构复刻 fixture --------- */
function mermaidSvg(nodes: { id: string; idx: number; x: number; y: number; label: string }[], edges: [string, string][]): string {
  const nodeSvg = nodes.map((n) =>
    `<g class="node default" id="flowchart-${n.id}-${n.idx}" data-look="classic" transform="translate(${n.x} ${n.y})">`
    + `<rect style="fill:#cde1f5;stroke:#9370DB" width="90" height="40"></rect>`
    + `<g class="label" style="" transform="translate(-24 0)"><foreignObject width="48" height="16"><div xmlns="http://www.w3.org/1999/xhtml">${n.label}</div></foreignObject></g></g>`).join('');
  const edgeSvg = edges.map(([a, b]) =>
    `<path d="M 100 50 L 300 50" id="L_${a}_${b}_0" class="flowchart-link LS-A LE-${b}" style="stroke:#999;stroke-width:1px"></path>`).join('');
  return '<svg xmlns="http://www.w3.org/2000/svg" class="flowchart" viewBox="0 0 500 300" width="100%">'
    + `<g class="output"><g class="edges">${edgeSvg}</g><g class="nodes">${nodeSvg}</g></g></svg>`;
}

describe('mermaid adapter', () => {
  it('v10 结构识别：节点/边/类型', () => {
    const { spec } = capture(mermaidSvg(
      [{ id: 'A', idx: 1, x: 60, y: 40, label: '开始' }, { id: 'B', idx: 2, x: 300, y: 40, label: '结束' }],
      [['A', 'B']],
    ), mermaidRules);
    expect(spec.type).toBe('flowchart');
    const byKind: Record<string, number> = {};
    for (const e of spec.elements) byKind[e.kind] = (byKind[e.kind] ?? 0) + 1;
    expect(byKind.node).toBe(2);
    expect(byKind.edge).toBe(1);
  });

  it('key 走用户声明名：translate 折叠 + foreignObject 文本', () => {
    const { spec } = capture(mermaidSvg(
      [{ id: 'A', idx: 1, x: 60, y: 40, label: '开始' }, { id: 'B', idx: 2, x: 300, y: 40, label: '结束' }],
      [['A', 'B']],
    ), mermaidRules);
    const keys = spec.elements.map((e) => e.key);
    expect(keys).toContain('ta:mermaid:name:A');
    expect(keys).toContain('ta:mermaid:name:B');
    expect(keys).toContain('ta:mermaid:name:A~B');
    const a = spec.elements.find((e) => e.key === 'ta:mermaid:name:A')!;
    expect(Math.abs(a.bbox.x - 15)).toBeLessThan(30); // translate(60,40) 折叠进坐标
    expect(a.text.map((t) => t.content).join('')).toContain('开始');
  });

  it('插节点重编号漂移 → 既有元素仍 stay（M1 退出标准核心场景）', () => {
    const before = capture(mermaidSvg(
      [{ id: 'A', idx: 1, x: 60, y: 40, label: '开始' }, { id: 'B', idx: 2, x: 300, y: 40, label: '结束' }],
      [['A', 'B']],
    ), mermaidRules).spec;
    // 在中间插入 NEW，B 的 id 从 flowchart-B-2 漂移到 flowchart-B-3
    const after = capture(mermaidSvg(
      [
        { id: 'A', idx: 1, x: 60, y: 40, label: '开始' },
        { id: 'NEW', idx: 2, x: 180, y: 120, label: '新步骤' },
        { id: 'B', idx: 3, x: 300, y: 40, label: '结束' },
      ],
      [['A', 'B']],
    ), mermaidRules).spec;
    const d = keydiff(before, after);
    expect(d.stay).toEqual(expect.arrayContaining(['ta:mermaid:name:A', 'ta:mermaid:name:B']));
    expect(d.enter.map((e) => e.key)).toContain('ta:mermaid:name:NEW');
    expect(d.exit.length).toBe(0);
  });

  it('边端点名漂移：L_A_B_0 保持键稳定', () => {
    const before = capture(mermaidSvg(
      [{ id: 'A', idx: 1, x: 60, y: 40, label: '开始' }, { id: 'B', idx: 2, x: 300, y: 40, label: '结束' }],
      [['A', 'B']],
    ), mermaidRules).spec;
    const after = capture(mermaidSvg(
      [{ id: 'A', idx: 1, x: 60, y: 40, label: '开始' }, { id: 'B', idx: 3, x: 300, y: 40, label: '结束' }],
      [['A', 'B']],
    ), mermaidRules).spec;
    const d = keydiff(before, after);
    expect(d.exit.length).toBe(0); // 边没被杀
  });

  it('subgraph cluster 以裸 id 为键：标题变宽不闪 (冒泡排序样本)', () => {
    const clusterSvg = (title: string) => capture(`<svg xmlns="http://www.w3.org/2000/svg"><g class="output"><g class="clusters"><g class="cluster" id="S"><path d="M 10 10 L 210 10 L 210 90 L 10 90 Z"/><g class="cluster-label" transform="translate(60 20)"><text>${title}</text></g></g></g></g></svg>`, mermaidRules).spec;
    const a = clusterSvg('初始: [5, 3, 8, 1, 2]');
    const b = clusterSvg('步骤1: 交换5和3 → [3, 5, 8, 1, 2]');
    expect(a.elements[0]!.key).toBe('ta:mermaid:name:S');
    const d = keydiff(a, b);
    expect(d.exit.length).toBe(0); // 框体存活，只有标题文本更新
    expect(d.text.length + d.update.length + d.stay.length).toBeGreaterThan(0);
  });
});

/* --------- graphviz adapter --------- */
const GV_NODE = (name: string, d: string, label: string) =>
  `<g id="node-1" class="node"><title>${name}</title><ellipse cx="50" cy="30" rx="45" ry="20" fill="none" stroke="black"/><text text-anchor="middle" x="50" y="26" font-size="14">${label}</text></g>`;

describe('dot adapter', () => {
  it('graphviz 原生 title 即稳定键', () => {
    const { spec } = capture('<svg xmlns="http://www.w3.org/2000/svg"><g class="graph"><g class="node"><title>A</title><ellipse cx="50" cy="30" rx="45" ry="20" fill="none" stroke="black"/><text text-anchor="middle" x="50" y="26">Alpha</text></g></g></svg>', dotRules);
    expect(spec.type).toBe('graphviz');
    expect(spec.elements.map((e) => e.key)).toEqual(['ta:dot:name:A']);
  });
});

/* --------- plantuml adapter（真实产物） --------- */
describe('plantuml adapter（v1.2026.8 真实 SVG）', () => {
  it('几何分组：参与者 name 节点保留，消息聚类为带 label 键的 edge', () => {
    const { spec } = capture(plantumlSeqBase, plantumlRules);
    const names = spec.elements.filter((e) => e.kind === 'node' && e.key.includes(':name:'));
    expect(names.length).toBe(3);
    const messages = spec.elements.filter((e) => e.kind === 'edge');
    expect(messages.length).toBe(4);
    expect(messages.map((e) => e.key)).toContain('ta:plantuml:label:edge:登录请求');
    expect(messages.map((e) => e.key)).toContain('ta:plantuml:label:edge:查询用户');
  });

  it('改消息文本+插新消息：参与者/未变消息 stay/move/update，仅目标消息 text/enter，零误杀', () => {
    const base = capture(plantumlSeqBase, plantumlRules).spec;
    const changed = capture(plantumlSeqChanged, plantumlRules).spec;
    const d = keydiff(base, changed);
    expect(d.exit.length).toBe(0); // 没有任何元素被误杀（裁决 #5 的最坏退化未触发）
    expect(d.text.map((t) => `${t.prev}->${t.next}`)).toContain('登录请求->登录请求V2');
    expect(d.enter.map((e) => e.key)).toContain('ta:plantuml:label:edge:审计写入');
    // 泳道拉宽：头部盒平移 → move；箭头加长/生命线加高 → morphable update（同一 DOM 身份保留）
    expect(d.move.length).toBeGreaterThanOrEqual(4);
    expect(d.update.length).toBeGreaterThanOrEqual(3);
    for (const u of d.update) expect(u.morphable).toBe(true);
    expect(d.stay.length).toBeGreaterThanOrEqual(1);
    // 守恒：13 个旧元素全部有去向（stay+move+update 配对；无 exit）
    expect(d.stay.length + d.move.length + d.update.length + d.text.length).toBeGreaterThanOrEqual(12);
  });
});

/* --------- registry 打分 --------- */
describe('后端注册表', () => {
  const mk = (id: string): AnimBackend => ({ id, rules: mermaidRules, render: async () => '' });
  const list: BackendRegistration[] = [
    { engine: 'mermaid', type: 'flowchart', backend: mk('m-specific') },
    { engine: 'mermaid', type: 'any', backend: mk('m-any') },
    { engine: 'any', type: 'flowchart', backend: mk('any-flow') },
    { engine: 'any', type: 'any', backend: mk('fallback') },
  ];
  it('精确 > 引擎通配 > 全通配', () => {
    expect(resolveBackend(list, 'mermaid', 'flowchart')!.id).toBe('m-specific');
    expect(resolveBackend(list, 'mermaid', 'sequence')!.id).toBe('m-any');
    expect(resolveBackend(list, 'plantuml', 'flowchart')!.id).toBe('any-flow');
    expect(resolveBackend(list, 'plantuml', 'activity')!.id).toBe('fallback');
  });
  it('score 判定', () => {
    expect(scoreAdapter(list[0]!, 'mermaid', 'flowchart')).toBe(4);
    expect(scoreAdapter(list[0]!, 'mermaid', 'x')).toBe(-1);
    expect(scoreAdapter(list[3]!, 'x', 'y')).toBe(0);
  });
});

/* --------- 离线 backend + player source 通道 --------- */
describe('createOfflineBackend + player source 帧', () => {
  it('render 产物为字符串，player 消费之', async () => {
    const b = createOfflineBackend('mermaid', (src) => {
      const n = Number(src);
      return svgDoc(`<g class="node" data-name="N${n}"><rect x="10" y="10" width="40" height="20"/></g>`);
    });
    const svg1 = await b.render('1');
    expect(typeof svg1).toBe('string');
    const { spec } = capture(svg1 as string, b.rules);
    expect(spec.elements[0]!.key).toBe('ta:mermaid:name:N1');
  });
});

describe('mermaid link 键方向无关（主线：拓扑不变则键不变 → swap 边走 morph）', () => {
  const edgeKeyOf = (id: string): string => {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg"><g id="${id}" class="edge"><path d="M 0 0 L 10 10"/></g></svg>`;
    const { spec } = capture(svg, mermaidRules);
    return spec.elements.find((e) => e.kind === 'edge')!.key;
  };
  it('L_V5_V3_0 与 L_V3_V5_0（正反序）捕获为同一键（端点排序归一）', () => {
    expect(edgeKeyOf('L_V5_V3_0')).toBe('ta:mermaid:name:V3~V5');
    expect(edgeKeyOf('L_V3_V5_0')).toBe('ta:mermaid:name:V3~V5');
  });
});
