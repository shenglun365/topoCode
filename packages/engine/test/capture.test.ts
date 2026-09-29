import { describe, expect, it } from 'vitest';
import { capture, genericRules } from '../src/core/capture';
import { deriveKey, disambiguate, fnv1a, normalizeText } from '../src/core/key';
import { baseKeyOf } from '../src/core/layout';
import { edgePath, nodeG, svgDoc, titleGroup, anonRect } from './fixtures';

describe('key 派生', () => {
  it('优先级：name hint > label > 指纹', () => {
    const base = { kind: 'node' as const, style: {}, bbox: { x: 0, y: 0, width: 10, height: 10 }, shapeCount: 1 };
    expect(deriveKey({ ...base, hintText: 'Alice', labelText: '登录' }, 'generic')).toBe('ta:generic:name:Alice');
    expect(deriveKey({ ...base, hintText: null, labelText: '登录' }, 'generic')).toBe('ta:generic:label:node:登录');
    const fp = deriveKey({ ...base, hintText: null, labelText: '' }, 'generic');
    expect(fp.startsWith('ta:generic:fp:')).toBe(true);
  });

  it('sanitize 去除引号防选择器注入', () => {
    const k = deriveKey({
      kind: 'node', hintText: 'a"b\\c', labelText: '', style: {},
      bbox: { x: 0, y: 0, width: 1, height: 1 }, shapeCount: 0,
    }, 'generic');
    expect(k).not.toContain('"');
    expect(k).not.toContain('\\');
  });

  it('消歧：仅重复项追加 #i，首个保持原键', () => {
    expect(disambiguate(['a', 'a', 'b', 'a'])).toEqual(['a', 'a#2', 'b', 'a#3']);
  });

  it('normalizeText 与 fnv 稳定', () => {
    expect(normalizeText('  登录 \n 请求 ')).toBe('登录 请求');
    expect(fnv1a('abc')).toBe(fnv1a('abc'));
    expect(fnv1a('abc')).not.toBe(fnv1a('abd'));
  });
});

describe('capture 规范化', () => {
  it('基本图：节点/边/文字/z 序/画布尺寸', () => {
    const { spec } = capture(svgDoc(nodeG(10, 10, '甲') + nodeG(200, 100, '乙') + edgePath(90, 30, 200, 120)));
    expect(spec.backend).toBe('generic');
    expect(spec.type).toBe('diagram');
    expect(spec.width).toBe(400);
    expect(spec.elements.map((e) => e.kind)).toEqual(['node', 'node', 'edge']);
    expect(spec.elements.map((e) => e.z)).toEqual([0, 1, 2]);
    expect(spec.elements[0]!.text[0]!.content).toBe('甲');
  });

  it('translate 折叠进坐标', () => {
    const { spec } = capture(svgDoc(nodeG(50, 30, '甲', { translate: true })));
    const el = spec.elements[0]!;
    expect(Math.abs(el.bbox.x - 50)).toBeLessThan(1);
    expect(Math.abs(el.bbox.y - 30)).toBeLessThan(1);
    expect(el.paths[0]!.d[0]).toMatchObject({ c: 'M', x: 50, y: 30 });
  });

  it('data-name / title / mermaid id 提取 name hint', () => {
    const { spec } = capture(svgDoc(
      nodeG(10, 10, '甲', { name: 'A' })
      + titleGroup('Alice', `<rect x="0" y="0" width="10" height="10"/>`)
      + `<g class="node" id="flowchart-B-3"><rect x="1" y="1" width="10" height="10"/></g>`,
    ));
    expect(spec.elements[0]!.key).toBe('ta:generic:name:A');
    expect(spec.elements[1]!.key).toBe('ta:generic:name:Alice');
    expect(spec.elements[2]!.key).toBe('ta:generic:name:B');
  });

  it('mermaid 边 id 提取端点对', () => {
    const { spec } = capture(svgDoc(
      `<g class="edge" id="L_A_B_0"><path d="M 0 0 L 10 10"/></g>`,
    ));
    expect(spec.elements[0]!.key).toBe('ta:generic:name:A~B');
  });

  it('同名 label 消歧 #2', () => {
    const { spec } = capture(svgDoc(nodeG(10, 10, '开始') + nodeG(200, 10, '开始')));
    const keys = spec.elements.map((e) => e.key);
    expect(keys[0]).toBe('ta:generic:label:node:开始');
    expect(keys[1]).toBe('ta:generic:label:node:开始#2');
  });

  it('匿名元素走指纹键；容器类 edges 不吞并子节点', () => {
    const { spec } = capture(svgDoc(
      `<g class="edges">${edgePath(0, 0, 10, 10)}${edgePath(20, 20, 30, 30)}</g>` + anonRect(100, 100),
    ));
    expect(spec.elements.map((e) => e.kind)).toEqual(['edge', 'edge', 'shape']);
    for (const e of spec.elements) expect(e.key).toContain(':fp:');
  });

  it('回写 data-ta-key，与 source.sel 一一对应', () => {
    const { spec, svg } = capture(svgDoc(nodeG(10, 10, '甲') + edgePath(0, 0, 10, 10)));
    for (const el of spec.elements) {
      const node = svg.querySelector(el.source.sel);
      expect(node).not.toBeNull();
      expect(node!.getAttribute('data-ta-key')).toBe(el.key);
    }
  });

  it('data-diagram-type 探测 plantuml 图类型', () => {
    const src = '<svg xmlns="http://www.w3.org/2000/svg" data-diagram-type="SEQUENCE" viewBox="0 0 10 10"></svg>';
    const { spec } = capture(src, genericRules);
    expect(spec.type).toBe('sequence');
  });

  it('text 锚点与近似排版盒', () => {
    const { spec } = capture(svgDoc(nodeG(100, 50, '登录请求')));
    const t = spec.elements[0]!.text[0]!;
    expect(t.anchor).toBe('middle');
    expect(Math.abs(t.box.x + t.box.width / 2 - 140)).toBeLessThan(2); // 盒中心 ≈ x+40
  });

  // 真实 mermaid v11.17 回归守护（探针实证结构）：id 全部带 renderId 前缀（"r1-flowchart-V5-0"、
  // cluster "r1-S1"），边是 edgePaths 下裸 path（id="r1-L_V5_V3_0" + 无污染的 data-id），
  // 无标签边伴随空 edgeLabel 壳（内层空 foreignObject 有 16px 排版盒且同样带 data-id——
  // 若当元素收会撞边键+漂移指纹）。曾因此：方向无关 canon 从未生效（hint 全 null）、
  // 节点/cluster 键退化为内容键（标题一改即整灭整生）→ 样本 stability 实测仅 40%。
  it('mermaid v11.17 结构：renderId 前缀剥除、data-id 边 hint、空 edgeLabel 壳跳过', () => {
    const doc = (renderId: string, inner: string) =>
      `<svg xmlns="http://www.w3.org/2000/svg" id="${renderId}" viewBox="0 0 400 400" width="400" height="400">${inner}</svg>`;
    const edge = (rid: string, ab: 'V5_V3' | 'V3_V5') =>
      `<g class="edgePaths"><path class="flowchart-link" id="${rid}-L_${ab}_0" data-id="L_${ab}_0" d="M 90 30 L 300 120" style="stroke:#999999;stroke-width:2"/></g>`;
    const shell = (rid: string, ab: 'V5_V3' | 'V3_V5') =>
      `<g class="edgeLabels"><g class="edgeLabel"><g class="label" data-id="L_${ab}_0" transform="translate(-20, -10)">`
      + `<foreignObject width="40" height="20"><div xmlns="http://www.w3.org/1999/xhtml"><span class="edgeLabel"></span></div></foreignObject></g></g></g>`;
    const node = (rid: string, name: string, n: number, label: string) =>
      `<g class="node default" id="${rid}-flowchart-${name}-${n}" transform="translate(65, 53)">`
      + `<rect class="basic label-container" x="-50" y="-25" width="100" height="50"/>`
      + `<g class="label" transform="translate(-20,-10)"><rect/><foreignObject width="40" height="20">`
      + `<div xmlns="http://www.w3.org/1999/xhtml"><span class="nodeLabel"><p>${label}</p></span></div></foreignObject></g></g>`;
    const cluster = (rid: string, sid: string, title: string) =>
      `<g class="cluster" id="${rid}-${sid}"><rect x="8" y="8" width="115" height="160"/>`
      + `<g class="cluster-label" transform="translate(45, 8)"><foreignObject width="40" height="20">`
      + `<div xmlns="http://www.w3.org/1999/xhtml"><span class="nodeLabel"><p>${title}</p></span></div></foreignObject></g></g>`;

    const f1 = capture(doc('r1', cluster('r1', 'S', '步骤 1 · 初始')
      + node('r1', 'V5', 0, '[5]') + node('r1', 'V3', 1, '[3]')));
    expect(f1.spec.elements.map((e) => e.key)).toEqual([
      'ta:generic:name:S', 'ta:generic:name:V5', 'ta:generic:name:V3',
    ]); // id hint 剥前缀命中（cluster 键=稳定 id，非标题内容）

    const f2a = capture(doc('r2', cluster('r2', 'S', '步骤 2 · 连线')
      + edge('r2', 'V5_V3') + shell('r2', 'V5_V3')
      + node('r2', 'V5', 0, '[5]') + node('r2', 'V3', 1, '[3]')));
    expect(f2a.spec.elements).toHaveLength(4); // 空壳未入元素表
    const f2b = capture(doc('r3', cluster('r3', 'S', '步骤 3 · 交换')
      + edge('r3', 'V3_V5') + shell('r3', 'V3_V5')
      + node('r3', 'V5', 0, '[5]') + node('r3', 'V3', 1, '[3]')));
    const edgeOf = (s: typeof f1.spec) => s.elements.find((e) => e.kind === 'shape')!;
    expect(edgeOf(f2a.spec).key).toBe('ta:generic:name:V3~V5');
    expect(edgeOf(f2b.spec).key).toBe(edgeOf(f2a.spec).key); // 方向交换 → 同键（morph 拉伸通道）

    const bases = (s: typeof f1.spec) => s.elements.map((e) => baseKeyOf(e.key));
    const inter = bases(f1.spec).filter((k) => bases(f2a.spec).includes(k)).length;
    expect(inter / Math.max(bases(f1.spec).length, bases(f2a.spec).length)).toBe(0.75); // 旧行为为 2/5=40%

    // 全画幅无 hint 背景形状跳过（graphviz 白底 polygon / plantuml 背景），小面积形状保留
    const bg = capture(doc('r9', '<polygon points="0,0 400,0 400,400 0,400" fill="white"/>'
      + '<rect x="10" y="10" width="40" height="20" fill="#eee"/>'));
    expect(bg.spec.elements).toHaveLength(1);
  });
});
