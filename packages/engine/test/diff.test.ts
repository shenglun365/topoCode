import { describe, expect, it } from 'vitest';
import { capture } from '../src/core/capture';
import { keydiff } from '../src/core/diff';
import { edgeCurve, edgePath, nodeG, svgDoc } from './fixtures';

function cap(s: string) {
  return capture(s).spec;
}

describe('keydiff 分类回归基线', () => {
  it('完全相同 → 全部 stay，无动画工作量', () => {
    const src = svgDoc(nodeG(10, 10, '甲') + edgePath(90, 30, 200, 120));
    const d = keydiff(cap(src), cap(src));
    expect(d.stay.length).toBe(2);
    expect(d.enter.length + d.exit.length + d.move.length + d.update.length + d.text.length).toBe(0);
  });

  it('改名（name 键不变）→ text 类，不误判生死', () => {
    const a = svgDoc(nodeG(10, 10, '登录', { name: 'A' }));
    const b = svgDoc(nodeG(10, 10, '登出', { name: 'A' }));
    const d = keydiff(cap(a), cap(b));
    expect(d.text.length).toBe(1);
    expect(d.text[0]!.prev).toBe('登录');
    expect(d.text[0]!.next).toBe('登出');
    expect(d.enter.length + d.exit.length).toBe(0);
  });

  it('纯 label 键元素的文本变化 → 匹配链救回为 text 类（坑表 #3 的软失败）', () => {
    const a = svgDoc(nodeG(10, 10, '开始处理'));
    const b = svgDoc(nodeG(10, 10, '开始处理完'));
    const d = keydiff(cap(a), cap(b));
    expect(d.enter.length + d.exit.length).toBe(0);
    expect(d.text.length + d.stay.length).toBe(1);
  });

  it('插入新节点 → 唯一 enter，其余 stay', () => {
    const a = svgDoc(nodeG(10, 10, '甲', { name: 'A' }));
    const b = svgDoc(nodeG(10, 10, '甲', { name: 'A' }) + nodeG(200, 200, '乙', { name: 'B' }));
    const d = keydiff(cap(a), cap(b));
    expect(d.enter.length).toBe(1);
    expect(d.enter[0]!.key).toContain('B');
    expect(d.stay.length).toBe(1);
  });

  it('mermaid 位置性 id 漂移（插节点导致重编号）→ 键名稳定 stay', () => {
    const a = svgDoc('<g class="node" id="flowchart-A-0"><rect x="0" y="0" width="10" height="10"/></g>'
      + '<g class="node" id="flowchart-B-1"><rect x="100" y="0" width="10" height="10"/></g>');
    const b = svgDoc('<g class="node" id="flowchart-A-0"><rect x="0" y="0" width="10" height="10"/></g>'
      + '<g class="node" id="flowchart-N-1"><rect x="50" y="0" width="10" height="10"/></g>'
      + '<g class="node" id="flowchart-B-2"><rect x="100" y="0" width="10" height="10"/></g>');
    const d = keydiff(cap(a), cap(b));
    expect(d.stay).toEqual(expect.arrayContaining(['ta:generic:name:A', 'ta:generic:name:B']));
    expect(d.enter.map((e) => e.key)).toEqual(['ta:generic:name:N']); // 新增节点是 enter，不是全图重播
    expect(d.exit.length).toBe(0);
  });

  it('整体平移 → move 类（不重绘）', () => {
    const a = svgDoc(nodeG(10, 10, '甲', { name: 'A' }));
    const b = svgDoc(nodeG(70, 30, '甲', { name: 'A' }));
    const d = keydiff(cap(a), cap(b));
    expect(d.move.length).toBe(1);
    expect(d.move[0]!.dx).toBeCloseTo(60, 0);
    expect(d.move[0]!.dy).toBeCloseTo(20, 0);
  });

  it('同构几何变更 → update(morphable)', () => {
    const a = svgDoc(edgePath(0, 0, 100, 50));
    const b = svgDoc(edgePath(0, 0, 120, 80));
    const d = keydiff(cap(a), cap(b));
    expect(d.update.length).toBe(1);
    expect(d.update[0]!.morphable).toBe(true);
    expect(d.update[0]!.geom).toBe(true);
  });

  it('非同构（直变曲）→ 裁决 #6：拆为 exit + enter', () => {
    const a = svgDoc(edgePath(0, 0, 100, 50));
    const b = svgDoc(edgeCurve(0, 0, 100, 50));
    const d = keydiff(cap(a), cap(b));
    expect(d.update.length).toBe(0);
    expect(d.exit.length).toBe(1);
    expect(d.enter.length).toBe(1);
  });

  it('删除节点 → exit', () => {
    const a = svgDoc(nodeG(10, 10, '甲', { name: 'A' }) + nodeG(200, 10, '乙', { name: 'B' }));
    const b = svgDoc(nodeG(10, 10, '甲', { name: 'A' }));
    const d = keydiff(cap(a), cap(b));
    expect(d.exit.map((e) => e.key)).toEqual(['ta:generic:name:B']);
    expect(d.stay.length).toBe(1);
  });

  it('样式变化 → update(style)', () => {
    const a = svgDoc(nodeG(10, 10, '甲', { name: 'A' }));
    const b = svgDoc(nodeG(10, 10, '甲', { name: 'A', fill: '#ff0000' }));
    const d = keydiff(cap(a), cap(b));
    expect(d.update.length).toBe(1);
    expect(d.update[0]!.style).toBe(true);
    expect(d.update[0]!.geom).toBe(false);
  });

  it('双同名同构元素：首个键对位、第二个消歧键对位，均 stay', () => {
    const a = svgDoc(nodeG(10, 10, '步骤') + nodeG(200, 10, '步骤'));
    const b = svgDoc(nodeG(10, 10, '步骤') + nodeG(200, 10, '步骤'));
    const d = keydiff(cap(a), cap(b));
    expect(d.stay.length).toBe(2);
    expect(d.enter.length + d.exit.length).toBe(0);
  });
});
