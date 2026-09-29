import { describe, expect, it } from 'vitest';
import { readFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  createStoryEngine, serializeStoryPackage, buildStoryHtml,
  type StoryEngine, type StateGraphSpec,
} from '../src/story';
import { nodeG, svgDoc } from './fixtures';

const big = (x: number, y: number, w: number, h: number, name: string): string =>
  `<g class="node" data-name="${name}"><rect x="${x}" y="${y}" width="${w}" height="${h}" style="fill:#fff;stroke:#999"/></g>`;

const sA = svgDoc(big(0, 0, 300, 160, 'S') + nodeG(20, 20, '甲', { name: 'A' }) + nodeG(180, 20, '乙', { name: 'B' }), 320, 180);
const sB = svgDoc(big(0, 0, 300, 160, 'S') + nodeG(180, 20, '甲', { name: 'A' }) + nodeG(20, 20, '乙', { name: 'B' }), 320, 180);

const quick = { staggerMs: 1, transitions: { enter: { type: 'fade' as const, durationMs: 5 } } };

async function mkEngine(): Promise<StoryEngine> {
  const graph: StateGraphSpec = {
    entry: 'a',
    states: [{ id: 'a', dwellMs: 0, svg: sA }, { id: 'b', dwellMs: 0, svg: sB }],
    edges: [{
      from: 'a', to: 'b',
      
      choreography: { ...quick },
    }],
  };
  const host = document.createElement('div');
  document.body.appendChild(host);
  const eng = await createStoryEngine({ graph, host });
  await eng.start();
  return eng;
}

describe('叙事交付包（C3 可交互 HTML 单包）', () => {
  it('serialize：状态固化为 svg（后端通道清除）、committed/vars 随行', async () => {
    const eng = await mkEngine();
    eng.store.position.setDraft('ta:generic:name:A', { dx: 15, dy: 0 });
    eng.store.position.commitDraft();
    eng.store.setVar('phase', 3);
    const pkg = serializeStoryPackage(eng, '冒泡片段');
    expect(pkg.version).toBe(1);
    expect(pkg.title).toBe('冒泡片段');
    expect(pkg.graph.states.every((s) => typeof s.svg === 'string' && s.source === undefined && s.script === undefined)).toBe(true);
    expect(pkg.committed['ta:generic:name:A']).toEqual({ dx: 15, dy: 0 });
    expect(pkg.vars.phase).toBe(3);
    expect(JSON.parse(JSON.stringify(pkg))).toEqual(JSON.parse(JSON.stringify(pkg))); // 纯数据可序列化
    eng.dispose();
  });

  it('buildStoryHtml：数据/运行时内联，</script> 注入被转义', async () => {
    const eng = await mkEngine();
    const pkg = serializeStoryPackage(eng);
    const evil = JSON.parse(JSON.stringify(pkg)) as typeof pkg;
    evil.graph.states[0]!.svg = '<svg xmlns="http://www.w3.org/2000/svg"><text>a</text></svg></script><script>alert(1)</script>';
    const html = buildStoryHtml(evil, '/*__RUNTIME__*/const x=1;');
    expect(html).toContain('<!doctype html>');
    expect(html).toContain('id="story-package"');
    expect(html).toContain('/*__RUNTIME__*/');
    expect(html).toContain('<\\/script>'); // 注入闭合被转义
    expect((html.match(/<\/script>/g) ?? []).length).toBe(2); // 仅真实的两处闭合
    eng.dispose();
  });

  it('包自含性：反序列化 → 新引擎重建 → 全图可跑（含 committed 复放）', async () => {
    const eng = await mkEngine();
    eng.store.position.setDraft('ta:generic:name:B', { dx: 0, dy: 40 });
    eng.store.position.commitDraft();
    const pkg = JSON.parse(JSON.stringify(serializeStoryPackage(eng))) as ReturnType<typeof serializeStoryPackage>;
    eng.dispose();
    const host = document.createElement('div');
    document.body.appendChild(host);
    const eng2 = await createStoryEngine({ graph: pkg.graph, host });
    eng2.store.position.restore({ committed: pkg.committed });
    await eng2.start();
    expect(eng2.snapshot().nodeId).toBe('b');
    const bB = eng2.scenes.get('b')!.spec.elements.find((e) => e.key === 'ta:generic:name:B')!;
    const bA = eng2.scenes.get('b')!.spec.elements.find((e) => e.key === 'ta:generic:name:A')!;
    expect(bB.bbox.y - bA.bbox.y).toBeCloseTo(40, 6); // committed 在包内复放
  });

  it('runtime 资产存在且含导出面（build:runtime 产物已提交）', () => {
    const p = resolve(process.cwd(), 'assets/story-runtime.mjs');
    expect(existsSync(p)).toBe(true);
    const code = readFileSync(p, 'utf8');
    expect(code).toContain('createStoryEngine');
    expect(code).toContain('createStoryStore');
    expect(code).not.toContain('import('); // 单包：无外部动态依赖
  });
});
