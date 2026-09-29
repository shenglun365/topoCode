/**
 * useGraphStory —— 统一图 JSON 动画播放 hook（graph 形态专用）
 *
 * 机制（canonical + 存在性投影）：
 *   buildGraphScene 一次布局(canonical 全量, elk) → 单 svg 常驻渲染 →
 *   帧推进 = 存在性 class 切换（enter 淡入 / exit 淡出 / modified 脉冲）——
 *   不变元素像素级静止，无帧重挂/无鬼影/无视角漂移。
 *
 * 旧 sources/frames/script(逐帧 DSL 渲染 + diff 补间)形态已删减 ——
 *   DSL 作为输入格式的播放能力按产品边界后置到 AI CHAT 文档场景再建立。
 */
import { onBeforeUnmount, reactive, shallowRef, watch, type Ref } from 'vue';
import {
  buildGraphScene,
  type GraphFrameDataInput,
  type GraphScene,
} from '@topo/engine';

export interface GraphStoryState {
  ready: boolean;
  error: string;
  index: number;
  playing: boolean;
  paused: boolean;
  frameCount: number;
}

export interface GraphStoryApi {
  state: GraphStoryState;
  scene: Ref<GraphScene | null>;
  /** 当前帧存在集合（响应式，播放层据此切换 class） */
  current: Ref<GraphScene['frames'][number] | null>;
  play(): void;
  pause(): void;
  togglePause(): void;
  stop(): void;
  next(): void;
  prev(): void;
  goto(index: number): void;
  dispose(): void;
}

export interface UseGraphStoryOptions {
  graph: Ref<GraphFrameDataInput | null | undefined>;
  direction?: Ref<'LR' | 'TB' | undefined>;
  autoPlay?: Ref<boolean | undefined>;
  stepMs?: Ref<number | undefined>;
  /** 帧推进回调（存在性已应用） */
  onFrameChange?: (f: { index: number; id: string; label: string }) => void;
  onError?: (e: { message: string }) => void;
  onReady?: (info: { frameIds: string[] }) => void;
}

export function useGraphStory(o: UseGraphStoryOptions): GraphStoryApi {
  const state = reactive<GraphStoryState>({
    ready: false, error: '', index: 0, playing: false, paused: false, frameCount: 0,
  });
  const scene = shallowRef<GraphScene | null>(null);
  const current = shallowRef<GraphScene['frames'][number] | null>(null);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  function clearTimer(): void {
    if (timer) { clearTimeout(timer); timer = null; }
  }

  /** 应用第 i 帧存在性（不改播放状态） */
  function settle(i: number): void {
    const sc = scene.value;
    if (!sc || !sc.frames.length) return;
    const idx = Math.max(0, Math.min(i, sc.frames.length - 1));
    state.index = idx;
    const f = sc.frames[idx]!;
    current.value = f;
    o.onFrameChange?.({ index: idx, id: f.id, label: f.label });
  }

  function arm(): void {
    clearTimer();
    if (!state.playing || state.paused || disposed) return;
    const sc = scene.value;
    if (!sc) return;
    const step = o.stepMs?.value ?? 1600;
    timer = setTimeout(() => {
      if (!scene.value) return;
      if (state.index >= scene.value.frames.length - 1) {
        state.playing = false;
        return;
      }
      settle(state.index + 1);
      arm();
    }, step);
  }

  function build(): void {
    const g = o.graph.value;
    if (!g || disposed) return;
    state.error = '';
    buildGraphScene(g, { direction: o.direction?.value ?? 'LR' })
      .then((sc) => {
        if (disposed) return;
        scene.value = sc;
        state.ready = true;
        state.frameCount = sc.frames.length;
        settle(0);
        o.onReady?.({ frameIds: sc.frames.map((f) => f.id) });
        if ((o.autoPlay?.value ?? true) && sc.frames.length > 1) {
          state.playing = true;
          state.paused = false;
          arm();
        }
      })
      .catch((e: Error) => {
        if (disposed) return;
        state.error = e.message;
        o.onError?.({ message: e.message });
      });
  }

  // graph 输入变化 → 重建(布局重算 + 帧存在性重置)
  const stopWatch = watch(o.graph, () => {
    clearTimer();
    state.ready = false;
    state.playing = false;
    state.paused = false;
    state.index = 0;
    scene.value = null;
    current.value = null;
    build();
  }, { immediate: true, deep: false });

  const api: GraphStoryApi = {
    state,
    scene,
    current,
    play() {
      const sc = scene.value;
      if (!sc || state.playing) return;
      state.playing = true;
      state.paused = false;
      if (state.index >= sc.frames.length - 1) settle(0);
      arm();
    },
    pause() {
      if (!state.playing || state.paused) return;
      state.paused = true;
      clearTimer();
    },
    togglePause() { state.paused ? this.play() : this.pause(); },
    stop() {
      state.playing = false;
      state.paused = false;
      clearTimer();
      settle(0);
    },
    next() {
      clearTimer();
      if (!scene.value) return;
      settle(state.index + 1);
      if (state.playing && !state.paused) arm();
    },
    prev() {
      clearTimer();
      settle(state.index - 1);
      if (state.playing && !state.paused) arm();
    },
    goto(i: number) {
      clearTimer();
      settle(i);
      if (state.playing && !state.paused) arm();
    },
    dispose() {
      disposed = true;
      stopWatch();
      clearTimer();
    },
  };

  return api;
}
