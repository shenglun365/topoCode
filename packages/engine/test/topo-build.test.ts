/**
 * TopoScript v2 构建期：Document → 线性 StateGraphSpec lowering + 选项校验。
 */
import { describe, expect, it } from 'vitest';
import { parseTopoScript } from '../src/topo/document';
import { buildTopoStory } from '../src/topo/build';

const build = (text: string) => buildTopoStory(parseTopoScript(text));

const two = `@version 2
@backend mermaid
@options step=1000
@@frame a
@@source
graph TD
  A
@@/source
@@frame b
@@source
graph TD
  A --> B
@@/source
`;

describe('buildTopoStory —— 线性 lowering', () => {
  it('帧序列 → states + 链式出边 + entry=首帧', () => {
    const b = build(two + `@@frame c\n@@source\ngraph TD\n  B\n@@/source\n`);
    expect(b.ok).toBe(true);
    expect(b.graph.entry).toBe('a');
    expect(b.graph.states.map((s) => s.id)).toEqual(['a', 'b', 'c']);
    expect(b.graph.edges.map((e) => `${e.from}>${e.to}`)).toEqual(['a>b', 'b>c']);
    expect(b.graph.vars).toEqual({});
  });

  it('dwell：全局 step 生效，帧级 step 覆写；auto=false 强制手动', () => {
    const b = build(two + `@@frame c step=250\n@@source\nx\n@@/source\n@@frame d auto=false\n@@source\ny\n@@/source\n`);
    const dw = (id: string) => b.graph.states.find((s) => s.id === id)!.dwellMs;
    expect(dw('a')).toBe(1000);
    expect(dw('c')).toBe(250);
    expect(dw('d')).toBeUndefined();
    expect(b.graph.states.find((s) => s.id === 'd')!.auto).toBe(false);
  });

  it('过渡编排落进入边 choreography（duration/order/stagger/align/transitions）', () => {
    const b = build(`@options duration=800 order=degree stagger=40 enter=drawIn enterMs=200 exit=fade
@@frame a\n@@source\nA\n@@/source
@@frame b align=false\n@@source\nB\n@@/source
`);
    const e = b.graph.edges[0]!;
    expect(e.choreography).toEqual({
      durationMs: 800, order: 'degree', staggerMs: 40, align: false,
      transitions: { enter: { type: 'drawIn', durationMs: 200 }, exit: { type: 'fade', durationMs: 450 } },
    });
  });

  it('非法 enter/order → error', () => {
    const b = build(`@@frame a\n@@source\nA\n@@/source\n@@frame b enter=wobble order=chaos\n@@source\nB\n@@/source\n`);
    const msgs = b.errors.filter((e) => e.severity === 'error').map((e) => e.message);
    expect(msgs.some((m) => m.includes('enter 动画类型'))).toBe(true);
    expect(msgs.some((m) => m.includes('order'))).toBe(true);
    expect(b.ok).toBe(false);
  });

  it('解析错误透传：ok=false + 空图', () => {
    const b = build('@@frame a\n@@source\nA');
    expect(b.ok).toBe(false);
    expect(b.graph.states).toEqual([]);
    expect(b.errors.some((e) => e.message.includes('未闭合'))).toBe(true);
  });

  it('TopoFrameInfo：帧信息含生效选项（合并后）与行号', () => {
    const b = build(two);
    expect(b.frames[1]!.id).toBe('b');
    expect(b.frames[1]!.options.step).toBe(1000);
    expect(b.frames[1]!.frameLine).toBeGreaterThan(1);
  });
});
