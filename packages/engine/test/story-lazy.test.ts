/**
 * 流式帧管线（集成批 1.2/1.3）：lazy 渲染队列、插队、进度事件、帧缓存、失败隔离。
 */
import { describe, expect, it } from 'vitest';
import type { AnimBackend } from '../src/backends';
import { genericRules } from '../src/core/capture';
import { createStoryEngine } from '../src/story/engine';
import { createMemoryFrameCache } from '../src/story/frame-cache';
import { storyFromSources } from '../src/topo/story-from-sources';

const delay = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));

/** 慢后端：每帧 20ms；'BOOM' 源文必失败；记录渲染顺序 */
function slowBackend(log: string[]): AnimBackend {
  return {
    id: 'slow',
    rules: genericRules,
    async render(source: string): Promise<string> {
      log.push(source);
      await delay(20);
      if (source.includes('BOOM')) throw new Error(`boom: ${source}`);
      const nodes = source.split('\n').map((l) => l.trim()).filter(Boolean);
      return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 120">` +
        nodes.map((n, i) => `<g class="node" data-name="${n}"><path d="M ${i * 60} 0 L ${i * 60 + 40} 20"/></g>`).join('') +
        '</svg>';
    },
  };
}

const graphOf = (sources: string[]) => storyFromSources(sources, { options: { step: 0 } }).graph;
const host = (): HTMLElement => document.createElement('div');

describe('lazy 流式管线', () => {
  it('创建不等待全量；进度事件单调递增至 total', async () => {
    const log: string[] = [];
    const b = graphOf(['A', 'B', 'C', 'D']);
    const events: { ready: number; total: number }[] = [];
    const eng = await createStoryEngine({ graph: b, host: host(), backend: slowBackend(log), lazy: true });
    const off = eng.bus.subscribe((evt, payload) => {
      if (evt === 'sys:scenes:progress') events.push(payload as { ready: number; total: number });
    });
    expect(eng.scenesProgress().total).toBe(4);
    expect(eng.scenesProgress().ready).toBeLessThan(4); // 创建即返回（首帧都未必完）
    await eng.scenesDone();
    expect(eng.scenesProgress().ready).toBe(4);
    off();
    const seq = events.map((e) => e.ready);
    expect(seq.every((v, i) => i === 0 || v >= seq[i - 1]!)).toBe(true);
    expect(seq[seq.length - 1]).toBe(4);
    eng.dispose();
  });

  it('ensureScene 插队：追帧提到队首先渲', async () => {
    const log: string[] = [];
    const b = graphOf(['A', 'B', 'C', 'D']); // f1..f4
    const eng = await createStoryEngine({ graph: b, host: host(), backend: slowBackend(log), lazy: true });
    await eng.ensureScene('f4'); // f1 渲染中，f4 插到 f2/f3 之前
    expect(log).toEqual(['A', 'D']); // f1(f4 等待时) → 插队 f4 → 后续才轮到 B/C
    await eng.scenesDone();
    expect(log).toEqual(['A', 'D', 'B', 'C']);
    eng.dispose();
  });

  it('帧缓存：第二个引擎全命中，后端零调用', async () => {
    const cache = createMemoryFrameCache();
    const log1: string[] = [];
    const log2: string[] = [];
    const b = graphOf(['A', 'B']);
    const e1 = await createStoryEngine({ graph: b, host: host(), backend: slowBackend(log1), cache, lazy: true });
    await e1.scenesDone();
    expect(log1).toEqual(['A', 'B']);
    const e2 = await createStoryEngine({ graph: b, host: host(), backend: slowBackend(log2), cache, lazy: true });
    await e2.scenesDone();
    expect(log2).toEqual([]); // 全缓存命中
    expect(e2.scenesProgress().ready).toBe(2);
    e1.dispose(); e2.dispose();
  });

  it('失败帧隔离（lazy）：坏帧记录 failures 且邻居帧照常；追帧时 start 以错误收场', async () => {
    const log: string[] = [];
    const b = graphOf(['A', 'BOOM', 'C']);
    const errs: { frame: string; message: string }[] = [];
    const eng = await createStoryEngine({ graph: b, host: host(), backend: slowBackend(log), lazy: true });
    eng.bus.subscribe((evt, payload) => {
      if (evt === 'sys:scenes:error') errs.push(payload as { frame: string; message: string });
    });
    await eng.scenesDone().catch(() => undefined); // done 带失败 reject，忽略
    expect(eng.sceneFailures().map((f) => f.frame)).toEqual(['f2']);
    expect(errs.map((e) => e.frame)).toEqual(['f2']);
    expect(eng.scenes.has('f1')).toBe(true);
    expect(eng.scenes.has('f3')).toBe(true);
    await expect(eng.start()).rejects.toThrow(/boom/); // 播放追到 f2 → ensureScene 失败传播
    eng.dispose();
  });

  it('非 lazy：失败即创建 reject（旧语义保持）', async () => {
    const b = graphOf(['A', 'BOOM']);
    await expect(createStoryEngine({ graph: b, host: host(), backend: slowBackend([]) })).rejects.toThrow(/帧渲染失败 f2|boom/);
  });

  it('非 lazy：成功后立即可播且全帧就绪（回归保护）', async () => {
    const b = graphOf(['A', 'B', 'C']);
    const eng = await createStoryEngine({ graph: b, host: host(), backend: slowBackend([]) });
    expect(eng.scenesProgress()).toEqual({ ready: 3, total: 3 });
    await eng.start();
    expect(eng.snapshot().phase).toBe('ended');
    eng.dispose();
  });
});
