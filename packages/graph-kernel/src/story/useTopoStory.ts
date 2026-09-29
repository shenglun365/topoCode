/**
 * TopoStory —— 帧序列叙事播放器（use 逻辑层，@topo/engine 适配）。
 *
 * 输入三形态（互斥，优先级 script > sources > frames）：
 *  - script：TopoScript v2 全文（@backend 决定渲染后端）
 *  - sources：每帧源文数组（mermaid/plantuml/dot 原文；前端流式渲染）
 *  - frames：服务端已渲染 SVG 数组（复用宿主渲染池，零前端渲染成本）
 * 引擎 lazy 流式管线：首帧就绪即播、其余后台逐帧补齐（progress 事件），
 * 帧缓存默认开启（IndexedDB → 刷新不丢渲染进度）。
 */
import { onBeforeUnmount, reactive, ref, shallowRef, watch, type Ref } from 'vue';
import {
  buildTopoStory, createFrameCache, createGraphvizBackend, createMermaidBackend, createPlantumlBackend,
  createStoryEngine, parseTopoScript, storyFromFrames, storyFromSources,
  type SchedulerSnapshot, type StoryEngine,
} from '@topo/engine';
import type { AnimBackend } from '@topo/engine';
import { themeVariablesFor } from '../vue/themes';

export type StoryEngineName = 'mermaid' | 'dot' | 'plantuml';

export interface TopoStorySource {
  script?: string;
  sources?: string[];
  /** 服务端渲染形态：SVG 文本数组 */
  frames?: string[];
  frameIds?: string[];
  annotations?: (Record<string, string> | undefined)[];
  /** 全局帧选项（step/auto/enter/exit/duration/order…，同 @options 语义） */
  options?: Record<string, string | number | boolean>;
}

export interface UseTopoStoryOptions {
  container: Ref<HTMLElement | null>;
  source: Ref<TopoStorySource | null | undefined>;
  /** sources/frames 形态的渲染后端（script 形态以 @backend 为准）；默认 mermaid */
  engineName?: StoryEngineName;
  theme?: Ref<'light' | 'dark' | undefined>;
  /** 整体覆盖后端（测试/定制注入通道） */
  backend?: AnimBackend;
  /** 帧渲染缓存（IndexedDB；默认开） */
  cache?: boolean;
  /** plantuml CLI 统一端点 base（默认 '/api/topo/plantuml'，同源网关自适应） */
  plantUmlBaseUrl?: string;
  autoPlay?: Ref<boolean | undefined>;
  onReady?: (info: { frameIds: string[]; edges: number }) => void;
  onProgress?: (p: { ready: number; total: number }) => void;
  onFrameChange?: (f: { nodeId: string; index: number; label: string }) => void;
  onError?: (e: { frame?: string; message: string }) => void;
}

export interface TopoStoryApi {
  /** 引擎实例（响应式，重建后替换） */
  engine: Ref<StoryEngine | null>;
  state: {
    playing: boolean;
    paused: boolean;
    progress: { ready: number; total: number };
    current: { nodeId: string; index: number; label: string } | null;
  };
  frameIds: Ref<string[]>;
  play(): void;
  stop(): void;
  togglePause(): void;
  next(): void;
  prev(): void;
  gotoFrame(id: string): void;
  gotoIndex(i: number): void;
  /** 等待最近一次重建完成且全部帧尝试渲染（失败帧不 reject，经 onError 上报）；engine 失败时为 null */
  waitReady(): Promise<StoryEngine | null>;
  dispose(): void;
}

/* 动态模块注入（对齐 MermaidEngine 的按需加载：不静态进主包） */
async function injectMermaid(n: string): Promise<{ default?: unknown }> {
  if (n !== 'mermaid') return {};
  const m = (await import('mermaid')) as unknown as { default?: unknown };
  return { default: m.default ?? m };
}
async function injectGraphviz(n: string): Promise<Record<string, unknown>> {
  if (n !== '@hpcc-js/wasm-graphviz') return {};
  return import('@hpcc-js/wasm-graphviz') as unknown as Record<string, unknown>;
}

export function resolveStoryBackend(
  name: StoryEngineName,
  opts: { theme?: 'light' | 'dark'; plantUmlBaseUrl?: string } = {},
): AnimBackend {
  const theme = opts.theme ?? 'dark';
  if (name === 'mermaid') {
    return createMermaidBackend(injectMermaid, {
      securityLevel: 'loose',
      theme: theme === 'dark' ? 'dark' : 'default',
      themeVariables: themeVariablesFor(theme),
    });
  }
  if (name === 'dot') return createGraphvizBackend(injectGraphviz);
  return createPlantumlBackend(opts.plantUmlBaseUrl ?? '/api/topo/plantuml');
}

export function useTopoStory(o: UseTopoStoryOptions): TopoStoryApi {
  const engine = shallowRef<StoryEngine | null>(null);
  const frameIds = ref<string[]>([]);
  const state = reactive({
    playing: false,
    paused: false,
    progress: { ready: 0, total: 0 },
    current: null as { nodeId: string; index: number; label: string } | null,
  });
  let unsubEngine: (() => void) | null = null;
  let disposed = false;

  const annotations = (): (Record<string, string> | undefined)[] => o.source.value?.annotations ?? [];
  const labelFor = (id: string): string => {
    const i = frameIds.value.indexOf(id);
    const a = i >= 0 ? annotations()[i] : undefined;
    return a?.commit ?? a?.label ?? id;
  };

  function pickBackend(graphBackend?: string): AnimBackend | undefined {
    if (o.backend) return o.backend;
    const name = (graphBackend as StoryEngineName | undefined) ?? o.engineName ?? 'mermaid';
    return resolveStoryBackend(name, { theme: o.theme?.value, plantUmlBaseUrl: o.plantUmlBaseUrl });
  }

  let lastRebuild: Promise<void> = Promise.resolve();
  async function rebuild(): Promise<void> {
    destroyEngine();
    const host = o.container.value;
    const src = o.source.value;
    if (disposed || !host || !src) return;

    const built = src.script !== undefined
      ? buildTopoStory(parseTopoScript(src.script))
      : src.sources !== undefined
        ? storyFromSources(src.sources, { frameIds: src.frameIds, annotations: src.annotations, ...(src.options ? { options: src.options } : {}) })
        : src.frames !== undefined
          ? storyFromFrames(src.frames, { frameIds: src.frameIds, annotations: src.annotations, ...(src.options ? { options: src.options } : {}) })
          : null;
    if (!built) return;
    const docBackend = (built as { doc?: { backend?: string } }).doc?.backend;
    if (!built.ok) {
      const first = built.errors.find((e) => e.severity === 'error');
      o.onError?.({ frame: first?.frame, message: first?.message ?? '构建失败' });
      return;
    }

    frameIds.value = built.graph.states.map((s) => s.id);
    try {
      const eng = await createStoryEngine({
        graph: built.graph,
        host,
        backend: pickBackend(docBackend),
        lazy: true,
        ...(o.cache === false ? {} : { cache: createFrameCache() }),
      });
      engine.value = eng;
      state.progress = { ready: 0, total: frameIds.value.length };
      unsubEngine = eng.bus.subscribe((evt, payload) => {
        if (evt === 'sys:scenes:progress') {
          state.progress = payload as { ready: number; total: number };
          o.onProgress?.(state.progress);
        } else if (evt === 'sys:scenes:error') {
          const p = payload as { frame: string; message: string };
          o.onError?.({ frame: p.frame, message: p.message });
        }
      });
      eng.scheduler.subscribe((s: SchedulerSnapshot) => {
        if (s.nodeId && s.nodeId !== state.current?.nodeId) {
          state.current = { nodeId: s.nodeId, index: frameIds.value.indexOf(s.nodeId), label: labelFor(s.nodeId) };
          o.onFrameChange?.(state.current);
        }
      });
      o.onReady?.({ frameIds: frameIds.value, edges: built.graph.edges.length });
      if (o.autoPlay?.value !== false) void eng.start().catch((e: Error) => o.onError?.({ message: e.message }));
    } catch (e) {
      o.onError?.({ message: (e as Error).message });
    }
  }

  function destroyEngine(): void {
    unsubEngine?.();
    unsubEngine = null;
    engine.value?.dispose();
    engine.value = null;
    state.playing = false;
    state.paused = false;
    state.current = null;
    state.progress = { ready: 0, total: 0 };
  }

  const togglePause = (): void => {
    const host = o.container.value;
    if (!engine.value) return;
    if (state.paused) {
      engine.value.scheduler.resume();
      host?.classList.remove('ta-paused');
      state.paused = false;
    } else {
      engine.value.scheduler.pause();
      host?.classList.add('ta-paused');
      state.paused = true;
    }
  };

  const runRebuild = (): void => { lastRebuild = rebuild(); };
  watch(() => o.source.value, runRebuild);
  watch(() => o.container.value, (el) => { if (el) runRebuild(); }, { immediate: true });
  onBeforeUnmount(() => { disposed = true; destroyEngine(); });

  return {
    engine,
    state,
    frameIds,
    play: () => { state.playing = true; void engine.value?.start().catch((e: Error) => o.onError?.({ message: e.message })); },
    stop: () => { engine.value?.scheduler.stop(); state.playing = false; },
    togglePause,
    next: () => engine.value?.scheduler.next(),
    prev: () => {
      const i = state.current ? state.current.index : -1;
      if (i > 0) engine.value?.scheduler.goto(frameIds.value[i - 1] as string);
    },
    gotoFrame: (id: string) => engine.value?.scheduler.goto(id),
    gotoIndex: (i: number) => { const id = frameIds.value[i]; if (id) engine.value?.scheduler.goto(id); },
    waitReady: async () => {
      await lastRebuild;
      await engine.value?.scenesDone().catch(() => undefined);
      return engine.value ?? null;
    },
    dispose: () => { disposed = true; destroyEngine(); },
  };
}
