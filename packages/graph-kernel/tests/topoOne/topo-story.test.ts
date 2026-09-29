/**
 * useTopoStory（@topo/engine 适配层）：三形态输入、流式进度、控制 API、失败路径。
 * 后端经 opts.backend 注入离线确定性 SVG（不依赖真实 mermaid/wasm/java）。
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { nextTick, ref } from 'vue';
import type { AnimBackend } from '@topo/engine';
import { genericRules } from '@topo/engine';
import { useTopoStory, type TopoStorySource } from '../../src/story/useTopoStory';

const wait = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms));
/** jsdom rAF 补间慢于标称 duration（~2×），帧推进断言一律轮询而非固定 wait */
async function until(cond: () => boolean, ms = 4000, label = 'cond'): Promise<void> {
  const t0 = Date.now();
  while (!cond()) {
    if (Date.now() - t0 > ms) throw new Error(`until timeout: ${label}`);
    await wait(20);
  }
}

/** 行文本 → node g（确定性、零依赖）；'BOOM' 触发失败 */
const offline: AnimBackend = {
  id: 'offline',
  rules: genericRules,
  async render(source: string): Promise<string> {
    await wait(10);
    if (source.includes('BOOM')) throw new Error('boom render');
    const nodes = source.split('\n').map((l) => l.trim()).filter(Boolean);
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 120">` +
      nodes.map((n, i) => `<g class="node" data-name="${n}"><path d="M ${i * 60} 0 L ${i * 60 + 40} 20"/></g>`).join('') +
      '</svg>';
  },
};

const svgFrame = (names: string[]): string =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 120">` +
  names.map((n, i) => `<g class="node" data-name="${n}"><path d="M ${i * 60} 0 L ${i * 60 + 40} 20"/></g>`).join('') +
  '</svg>';

function mount(source: TopoStorySource, over: Partial<Parameters<typeof useTopoStory>[0]> = {}) {
  const el = document.createElement('div');
  document.body.appendChild(el); // 补间完成依赖元素在文档内（jsdom 布局/transition 行为）
  const container = ref<HTMLElement | null>(el);
  const events: string[] = [];
  const api = useTopoStory({
    container,
    source: ref(source),
    backend: offline,
    cache: false,
    onFrameChange: (f) => events.push(`frame:${f.nodeId}`),
    onProgress: (p) => events.push(`prog:${p.ready}/${p.total}`),
    onError: (e) => events.push(`err:${e.frame ?? '-'}`),
    ...over,
  });
  return { api, events, container };
}

describe('useTopoStory', () => {
  beforeEach(() => { });

  it('sources 形态：流式进度 + 播放帧序', async () => {
    const { api, events } = mount({ sources: ['A', 'A\nB', 'A\nB\nC'], options: { step: 0, duration: 5, enter: 'fade', enterMs: 1, exit: 'fade', exitMs: 1 }, frameIds: ['h1', 'h2', 'h3'], annotations: [{ commit: 'h1' }, { commit: 'h2' }, { commit: 'h3' }] });
    await api.waitReady();
    await until(() => api.state.current?.nodeId === 'h3', 6000, 'h3');
    expect(api.frameIds.value).toEqual(['h1', 'h2', 'h3']);
    expect(events).toContain('frame:h1');
    expect(events).toContain('frame:h2');
    expect(events).toContain('frame:h3');
    expect(api.state.current?.label).toBe('h3'); // commit 注记作 label
    expect(events).toContain('prog:3/3');
    api.dispose();
  });

  it('frames 形态（服务端 SVG 序列）：免渲染直接播', async () => {
    const { api } = mount({ frames: [svgFrame(['A']), svgFrame(['A', 'B'])], options: { step: 0, duration: 5, enter: 'fade', enterMs: 1, exit: 'fade', exitMs: 1 } });
    await api.waitReady();
    expect(api.state.progress.total).toBe(2);
    await until(() => api.state.current?.nodeId === 'f2', 6000, 'f2');
    api.dispose();
  });

  it('script 形态：TopoScript v2 全文（backend 由注入覆盖）', async () => {
    const script = '@version 2\n@backend mermaid\n@options step=0 duration=5 enter=fade enterMs=1 exit=fade exitMs=1\n@@frame s1\n@@source\nA\n@@/source\n@@frame s2\n@@source\nB\n@@/source\n';
    const { api } = mount({ script });
    await api.waitReady();
    expect(api.frameIds.value).toEqual(['s1', 's2']);
    api.dispose();
  });

  it('手动控制：autoPlay=false + next/prev/gotoIndex', async () => {
    const { api, events } = mount({ sources: ['A', 'B', 'C'], options: { step: 0, duration: 5, enter: 'fade', enterMs: 1, exit: 'fade', exitMs: 1 } }, { autoPlay: ref(false) });
    await api.waitReady();
    expect(events.some((e) => e.startsWith('frame:'))).toBe(false); // 未自动播
    api.play();
    await until(() => api.state.current?.nodeId === 'f1', 6000, 'f1');
    api.next();
    await until(() => api.state.current?.nodeId === 'f2', 6000, 'next→f2');
    api.prev();
    await until(() => api.state.current?.nodeId === 'f1', 6000, 'prev→f1');
    api.gotoIndex(2);
    await until(() => api.state.current?.nodeId === 'f3', 6000, 'goto→f3');
    api.dispose();
  });

  it('坏帧：sys:scenes:error 上报帧 id，其余帧照常', async () => {
    const { api, events } = mount({ sources: ['A', 'BOOM', 'C'], options: { step: 0, duration: 5, enter: 'fade', enterMs: 1, exit: 'fade', exitMs: 1 } });
    await api.waitReady();
    await wait(100);
    expect(events).toContain('err:f2');
    expect(api.state.progress.ready).toBe(2);
    api.dispose();
  });

  it('非法输入：空 script → onError 不抛', async () => {
    const errs: { message: string }[] = [];
    const el = document.createElement('div');
    document.body.appendChild(el);
    const container = ref<HTMLElement | null>(el);
    const api = useTopoStory({
      container, source: ref({ script: '游离内容' }), backend: offline, cache: false,
      onError: (e) => errs.push(e),
    });
    await nextTick();
    await wait(50);
    expect(errs.length).toBeGreaterThan(0);
    expect(api.engine.value).toBeNull();
    api.dispose();
  });
});
