import { describe, expect, it } from 'vitest';
import { capture } from '../src/core/capture';
import { keydiff } from '../src/core/diff';
import { plantumlSeqBase, plantumlSeqChanged } from './fixtures/plantuml';

describe('真实 PlantUML 产物冒烟（v1.2026.8 实测）', () => {
  const base = capture(plantumlSeqBase).spec;
  const changed = capture(plantumlSeqChanged).spec;

  it('参与者按 title 获得稳定 name 键', () => {
    const names = base.elements.filter((e) => e.kind === 'node').map((e) => e.key);
    expect(names).toEqual(expect.arrayContaining([
      'ta:generic:name:Alice', 'ta:generic:name:Bob', 'ta:generic:name:DB',
    ]));
  });

  it('图类型探测 SEQUENCE', () => {
    expect(base.type).toBe('sequence');
  });

  it('消息帧间 diff：参与者生命线绝不误杀，改名走 text，插入走 enter', () => {
    const d = keydiff(base, changed);
    const participantKeys = base.elements
      .filter((e) => e.key.startsWith('ta:generic:name:'))
      .map((e) => e.key);
    expect(participantKeys.length).toBeGreaterThanOrEqual(3);
    for (const k of participantKeys) {
      expect(d.exit.map((e) => e.key)).not.toContain(k);
    }
    expect(d.text.length).toBeGreaterThanOrEqual(1);
    expect(d.enter.length).toBeGreaterThanOrEqual(1);
    expect(d.stay.length).toBeGreaterThan(0);
  });

  it('匿名消息元素获得 label/fp 键（无 id 的现实下仍被规范化）', () => {
    const keys = new Set(base.elements.map((e) => e.key));
    const labeled = [...keys].filter((k) => k.includes(':label:')).length;
    const fp = [...keys].filter((k) => k.includes(':fp:')).length;
    expect(labeled + fp).toBeGreaterThan(0);
  });

  it('所有回写 data-ta-key 均可寻址', () => {
    const { spec, svg } = capture(plantumlSeqBase);
    for (const el of spec.elements) {
      expect(svg.querySelector(el.source.sel)).not.toBeNull();
    }
  });
});
