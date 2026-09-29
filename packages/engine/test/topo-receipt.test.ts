/**
 * 验收收据守护（B1）：checks 封闭清单、键稳定性阈值、digest、canonical 指纹语义等价。
 */
import { describe, expect, it } from 'vitest';
import { parseTopoScript, canonicalDoc } from '../src/topo/document';
import { buildTopoStory } from '../src/topo/build';
import { buildReceipt } from '../src/topo/receipt';
import { genericRules } from '../src/core/capture';
import type { AnimBackend } from '../src/backends';

/** 行文本 → 每行一个 node g/path（确定性，无需真实后端） */
const lineBackend: AnimBackend = {
  id: 'lines',
  rules: genericRules,
  async render(source: string): Promise<string> {
    const nodes = source.split('\n').map((l) => l.trim()).filter(Boolean);
    const gs = nodes.map((n, i) =>
      `<g class="node" data-name="${n}"><path d="M ${i * 60} 0 L ${i * 60 + 40} 20"/></g>`).join('');
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 120">${gs}</svg>`;
  },
};

const docOf = (frames: string[]): string => frames
  .map((src, i) => `@@frame f${i + 1}\n@@source\n${src}\n@@/source`)
  .join('\n');

async function receiptOf(text: string, withGraph = true) {
  const doc = parseTopoScript(text);
  const b = buildTopoStory(doc);
  return buildReceipt(doc, { backend: lineBackend, ...(withGraph ? { graph: b.graph } : {}) });
}

describe('buildReceipt', () => {
  it('稳定帧序：全 checks 过、稳定性 1.00、非空 perFrame', async () => {
    const r = await receiptOf(docOf(['A\nB', 'A\nB', 'A\nB\nC']));
    expect(r.ok).toBe(true);
    expect(r.frames).toBe(3);
    expect(r.checks.filter((c) => c.severity === 'error' && !c.ok)).toEqual([]);
    expect(r.keys.perFrame).toEqual([2, 2, 3]);
    expect(r.keys.stability).toEqual([1, 0.67]);
    expect(r.avgStability).toBe(0.83);
    expect(r.digest).toMatch(/^[a-f0-9-]{16,64}$/);
  });

  it('键大换血：stability <0.5 → warning fail（但不阻断 ok）', async () => {
    const r = await receiptOf(docOf(['A\nB', 'X\nY']));
    const st = r.checks.filter((c) => c.check === 'keys/stability');
    expect(st[0]!.ok).toBe(false);
    expect(st[0]!.severity).toBe('warning');
    expect(r.ok).toBe(true); // warning 不阻断
    expect(st[0]!.detail).toMatch(/大面积 enter\/exit/);
  });

  it('空帧 → error → receipt.ok=false', async () => {
    const r = await receiptOf(docOf(['A', '   ']), false);
    expect(r.ok).toBe(false);
    expect(r.checks.some((c) => c.check === 'frame/nonempty' && !c.ok)).toBe(true);
  });

  it('dwell 通道：auto=false 帧给 info 提示', async () => {
    const r = await receiptOf(docOf(['A', 'B']).replace('@@frame f2', '@@frame f2 auto=false'));
    const info = r.checks.find((c) => c.check === 'dwell/valid');
    expect(info).toEqual({ check: 'dwell/valid', frame: 'f2', severity: 'info', ok: true, detail: '手动驻留（auto=false）：播放到该帧等待 next' });
  });

  it('渲染失败 → frame/renders error', async () => {
    const bad: AnimBackend = { id: 'bad', rules: genericRules, async render() { throw new Error('后端炸了'); } };
    const doc = parseTopoScript(docOf(['A']));
    const r = await buildReceipt(doc, { backend: bad });
    expect(r.ok).toBe(false);
    expect(r.checks.find((c) => c.check === 'frame/renders')!.detail).toBe('后端炸了');
  });

  it('无 backend：渲染类检查跳过，仍可出帧级 nonempty 结论', async () => {
    const doc = parseTopoScript(docOf(['A']));
    const r = await buildReceipt(doc);
    expect(r.checks.filter((c) => c.check === 'frame/renders')).toEqual([]);
    expect(r.keys.stability).toEqual([]);
    expect(r.ok).toBe(true);
  });
});

describe('canonicalDoc 指纹', () => {
  it('注释/空白差异 → 同指纹；帧序/内容差异 → 不同指纹', () => {
    const a = parseTopoScript('# 头注释\n@@frame f1\n@@source\n  A  \n@@/source\n');
    const b = parseTopoScript('@@frame f1\n@@source\nA\n@@/source\n');
    expect(canonicalDoc(a)).toBe(canonicalDoc(b));
    const c = parseTopoScript('@@frame f1\n@@source\nA\n@@/source\n@@frame f2\n@@source\nB\n@@/source\n');
    expect(canonicalDoc(c)).not.toBe(canonicalDoc(b));
  });

  it('帧级选项参与指纹', () => {
    const a = parseTopoScript('@@frame f1 step=100\n@@source\nA\n@@/source\n');
    const b = parseTopoScript('@@frame f1 step=200\n@@source\nA\n@@/source\n');
    expect(canonicalDoc(a)).not.toBe(canonicalDoc(b));
  });
});
