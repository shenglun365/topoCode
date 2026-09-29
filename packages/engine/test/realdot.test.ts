import { describe, expect, it } from 'vitest';
import { capture } from '../src/core/capture';
import { keydiff } from '../src/core/diff';
import { dotRules } from '../src/backends';

async function renderDot(src: string): Promise<string> {
  const { Graphviz } = await import('@hpcc-js/wasm-graphviz');
  const gv = await Graphviz.load();
  return gv.dot(src);
}

const nameKeys = (els: { key: string; kind: string }[]) =>
  els.filter((e) => e.kind === 'node' || e.kind === 'edge').map((e) => e.key);

describe('真实 Graphviz dot 产物 diff 一致性（wasm 无头渲染）', () => {
  it('稳定节点/边跨帧零误杀，新元素 enter', async () => {
    const f1 = capture(await renderDot('digraph G { rankdir=LR; A [label="接入"]; B [label="网关"]; A -> B }'), dotRules).spec;
    const f2 = capture(await renderDot('digraph G { rankdir=LR; A [label="接入"]; B [label="网关"]; C [label="服务"]; A -> B -> C }'), dotRules).spec;
    const f3 = capture(await renderDot('digraph G { rankdir=LR; A [label="接入"]; B [label="网关"]; C [label="服务"]; D [label="存储"]; A -> B; B -> C; C -> D; A -> D }'), dotRules).spec;

    // dot 的节点/边均带 <title>，全部拿到 name 键
    expect(nameKeys(f1.elements)).toEqual(expect.arrayContaining([
      'ta:dot:name:A', 'ta:dot:name:B', 'ta:dot:name:A~B',
    ]));

    const d12 = keydiff(f1, f2);
    // 帧1 的既有元素（A、B、边 A~B）都不应被判 exit
    expect(d12.exit.map((e) => e.key)).toEqual([]);
    // 新节点 C 出现为 enter
    expect(d12.enter.map((e) => e.key)).toContain('ta:dot:name:C');
    // A/B 至少 stay 或 move（重排会移动位置）
    expect(d12.stay.concat(d12.move.map((m) => m.key))).toEqual(
      expect.arrayContaining(['ta:dot:name:A', 'ta:dot:name:B']),
    );

    const d23 = keydiff(f2, f3);
    // 引入 D 与新边：帧2 既有节点零 exit 误杀
    expect(d23.exit.filter((e) => e.kind === 'node').map((e) => e.key)).toEqual([]);
    expect(d23.enter.map((e) => e.key)).toContain('ta:dot:name:D');
  }, 30000);

  it('所有 name 元素 data-ta-key 可寻址', async () => {
    const s = await renderDot('digraph G { a -> b; b -> c }');
    const { spec, svg } = capture(s, dotRules);
    for (const el of nameKeys(spec.elements)) {
      const node = (svg as Element).querySelector(`[data-ta-key="${el}"]`);
      expect(node).not.toBeNull();
    }
  }, 30000);
});
