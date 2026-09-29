/** useGraphStory —— graph 形态播放 hook 单测（canonical 布局 + 存在性投影） */
import { describe, expect, it } from 'vitest';
import { ref } from 'vue';
import { useGraphStory } from '../../src/story/useTopoStory';
import type { GraphFrameDataInput } from '@topo/engine';

// 真实时序(fake timers 会干扰 elk 内部异步): 短 stepMs + 轮询等待
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function waitReady(api: ReturnType<typeof useGraphStory>, ms = 4000): Promise<boolean> {
  const t0 = Date.now();
  while (!api.state.ready && Date.now() - t0 < ms) await sleep(20);
  return api.state.ready;
}

const graph: GraphFrameDataInput = {
  canonical: {
    nodes: [
      { key: 'a', label: 'A' },
      { key: 'b', label: 'B' },
      { key: 'c', label: 'C' },
    ],
    edges: [{ key: 'a->b', from: 'a', to: 'b' }, { key: 'b->c', from: 'b', to: 'c' }],
    containers: [],
  },
  frames: [
    { id: 'f1', label: 'one', nodes: ['a', 'b'], edges: ['a->b'] },
    { id: 'f2', label: 'two', nodes: ['a', 'b', 'c'], edges: ['a->b', 'b->c'], modified: ['b'] },
  ],
};

describe('useGraphStory', () => {
  it('构建: ready + 帧数 + 首帧存在性(边随两端存活)', async () => {
    const g = ref<GraphFrameDataInput | null>(graph);
    const api = useGraphStory({ graph: g, autoPlay: ref(false) });
    expect(await waitReady(api)).toBe(true);
    expect(api.state.ready).toBe(true);
    expect(api.state.frameCount).toBe(2);
    expect(api.state.index).toBe(0);
    expect(api.current.value?.has.has('a')).toBe(true);
    expect(api.current.value?.has.has('b')).toBe(true);
    expect(api.current.value?.has.has('c')).toBe(false);
    expect(api.current.value?.has.has('b->c')).toBe(false);
    api.dispose();
  });

  it('autoPlay: 定时推进至末帧自动停', async () => {
    const api = useGraphStory({ graph: ref(graph), autoPlay: ref(true), stepMs: ref(40) });
    expect(await waitReady(api)).toBe(true);
    expect(api.state.playing).toBe(true);
    await sleep(180);
    expect(api.state.index).toBe(1);
    expect(api.state.playing).toBe(false);
    api.dispose();
  });

  it('手动控制: next/prev/goto 边界钳制 + modified 标注', async () => {
    const api = useGraphStory({ graph: ref(graph), autoPlay: ref(false) });
    expect(await waitReady(api)).toBe(true);
    api.next();
    expect(api.state.index).toBe(1);
    expect(api.current.value?.modified.has('b')).toBe(true);
    expect(api.current.value?.has.has('b->c')).toBe(true);
    api.next(); // 末帧钳制
    expect(api.state.index).toBe(1);
    api.prev();
    expect(api.state.index).toBe(0);
    api.goto(5); // 越界钳制
    expect(api.state.index).toBe(1);
    api.dispose();
  });

  it('帧回调逐帧触发', async () => {
    const seen: number[] = [];
    const api = useGraphStory({ graph: ref(graph), autoPlay: ref(false), onFrameChange: (f) => seen.push(f.index) });
    expect(await waitReady(api)).toBe(true);
    api.goto(1);
    expect(seen).toEqual([0, 1]);
    api.dispose();
  });

  it('graph 变更 → 重建', async () => {
    const g = ref<GraphFrameDataInput | null>(graph);
    const api = useGraphStory({ graph: g, autoPlay: ref(false) });
    expect(await waitReady(api)).toBe(true);
    expect(api.state.frameCount).toBe(2);
    g.value = { ...graph, frames: graph.frames.slice(0, 1) };
    const t0 = Date.now();
    while (api.state.frameCount !== 1 && Date.now() - t0 < 4000) await sleep(20);
    expect(api.state.frameCount).toBe(1);
    api.dispose();
  });
});

import { mount } from '@vue/test-utils';
import TopoStory from '../../src/vue/TopoStory.vue';

describe('TopoStory (graph 形态, jsdom 挂载)', () => {
  it('单 svg 常驻: 元素渲染 + 帧切换 ev-off/ev-mod class 切换', async () => {
    const w = mount(TopoStory, { props: { graph, autoPlay: false, stepMs: 50 } });
    const t0 = Date.now();
    while (!w.vm.api.state.ready && Date.now() - t0 < 4000) await sleep(20);
    expect(w.vm.api.state.ready).toBe(true);
    await sleep(80); // rAF 挂载 + fit
    const svg = w.find('svg.topo-story__graph');
    expect(svg.exists()).toBe(true);
    // canonical 全量 6 元素(3 节点+2 边)常驻 DOM
    const keys = w.findAll('g[data-ta-key]').map((n) => n.attributes('data-ta-key'));
    expect(keys.length).toBe(5);
    expect(keys).toContain('a');
    expect(keys).toContain('a->b');
    // 首帧: c/b->c 隐藏
    const clsOf = (k: string) => w.find(`g[data-ta-key="${k}"]`).classes();
    expect(clsOf('c')).toContain('ev-off');
    expect(clsOf('b->c')).toContain('ev-off');
    expect(clsOf('a')).not.toContain('ev-off');
    // 切帧: c 淡入(移除 ev-off) + b 脉冲(ev-mod)
    w.vm.api.goto(1);
    await sleep(30);
    expect(clsOf('c')).not.toContain('ev-off');
    expect(clsOf('b->c')).not.toContain('ev-off');
    expect(clsOf('b')).toContain('ev-mod');
    w.unmount();
  });
});
