import { describe, expect, it } from 'vitest';
import { parseTopoScript, serializeTopoScript } from '../src/topo/document';

const doc2 = `@version 2
@backend mermaid
@options step=1500 enter=fade
@@frame a
@@source
graph TD
  A["甲"]
@@/source
@@frame b step=300 enter=drawIn
@@source
graph TD
  A["甲"] --> B["乙"]
@@/source
`;

describe('TopoScript v2 封套解析', () => {
  it('基础：头指令 + 帧序列 + 区域原文 verbatim', () => {
    const d = parseTopoScript(doc2);
    expect(d.version).toBe(2);
    expect(d.backend).toBe('mermaid');
    expect(d.options).toEqual({ step: 1500, enter: 'fade' });
    expect(d.frames.map((f) => f.id)).toEqual(['a', 'b']);
    expect(d.frames[0]!.source).toBe('graph TD\n  A["甲"]');
    expect(d.errors).toEqual([]);
  });

  it('帧级选项（@@frame 行 k=v，含引号/布尔/数字 coerce）', () => {
    const d = parseTopoScript(`@@frame a step=300 enter=fade label="两 词" align=false
@@source
x
@@/source
`);
    expect(d.frames[0]!.options).toEqual({ step: 300, enter: 'fade', label: '两 词', align: false });
  });

  it('封套上下文 # 注释忽略；@@source 区内 # 保留', () => {
    const d = parseTopoScript(`# 头注释
@@frame a
@@source
# 这是图内容的一部分
A
@@/source
`);
    expect(d.frames[0]!.source).toBe('# 这是图内容的一部分\nA');
  });

  it('v1 已移除区域（@@logic/@@generate/@vars）→ error + 跳过内容继续解析', () => {
    const d = parseTopoScript(`@vars
{ x: 1 }
@/vars
@@generate
ta.frame('g1', 'X')
@@/generate
@@frame a
@@source
graph TD
  A
@@/source
@@logic
ta.auto(100)
@@/logic
`);
    const msgs = d.errors.filter((e) => e.severity === 'error').map((e) => e.message);
    expect(msgs.some((m) => m.includes('@vars 已移除'))).toBe(true);
    expect(msgs.some((m) => m.includes('@@generate 已移除'))).toBe(true);
    expect(msgs.some((m) => m.includes('@@logic 已移除'))).toBe(true);
    expect(d.frames.map((f) => f.id)).toEqual(['a']); // 移除区被跳过，帧正常解析
  });

  it('@@source 未闭合 / 游离内容 / 帧外 @@source → error', () => {
    expect(parseTopoScript('@@frame a\n@@source\nA').errors[0]!.message).toMatch(/未闭合/);
    expect(parseTopoScript('游离文字').errors[0]!.message).toMatch(/游离内容/);
    expect(parseTopoScript('@@source\nA\n@@/source').errors[0]!.message).toMatch(/必须在 @@frame 内/);
  });

  it('重复帧 id → error（保留先到者）', () => {
    const d = parseTopoScript('@@frame a\n@@source\nA\n@@/source\n@@frame a\n@@source\nB\n@@/source\n');
    expect(d.errors.some((e) => e.message.includes('重复'))).toBe(true);
    expect(d.frames.map((f) => f.id)).toEqual(['a']);
  });

  it('空文档 → error', () => {
    expect(parseTopoScript('# 只有注释\n').errors[0]!.message).toMatch(/为空/);
  });

  it('round-trip：serialize → parse 语义等价', () => {
    const d = parseTopoScript(doc2);
    const t = serializeTopoScript(d);
    const d2 = parseTopoScript(t);
    expect(d2.errors).toEqual([]);
    expect(d2.frames.map((f) => [f.id, f.options, f.source])).toEqual(
      d.frames.map((f) => [f.id, f.options, f.source]),
    );
    expect(d2.options).toEqual(d.options);
  });

  it('诊断协议：code/frame/supportedFixes 齐备', () => {
    const d = parseTopoScript('@@frame a\n@@source\nA');
    const e = d.errors.find((x) => x.code === 'parse/unclosed-region')!;
    expect(e.frame).toBe('a');
    expect(e.supportedFixes?.[0]).toMatch(/@@\/source/);
    const w = parseTopoScript('@mystery 1\n@@frame a\n@@source\nA\n@@/source\n');
    expect(w.errors[0]!.code).toBe('parse/unknown-directive');
    expect(w.errors[0]!.severity).toBe('warning');
  });

  it('未知 @ 指令 → warning（不中断）', () => {
    const d = parseTopoScript('@mystery 1\n@@frame a\n@@source\nA\n@@/source\n');
    expect(d.errors.every((e) => e.severity === 'warning')).toBe(true);
    expect(d.frames).toHaveLength(1);
  });
});
