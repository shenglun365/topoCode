/**
 * StoryEngine —— 叙事引擎门面（§19 P1；集成批 1.2 流式化）：
 * graph + host → 帧渲染队列（lazy=后台逐帧流式；非 lazy=创建时 await 全量）→ relayout(锚+committed)
 * → ScenePlanCompiler(sceneOf 惰性等待) → Scheduler。store.committed 变化 → 幂等重布局 + 清边缓存。
 *
 * 流式管线（lazy）：
 *  - 渲染任务队列（并发 1，不阻塞交互）：初始按编译序后台预取全部帧；
 *  - ensureScene(id) 插队：播放/编译追到某帧时该帧提到队首；
 *  - 进度事件 sys:scenes:progress {ready,total}；单帧失败 sys:scenes:error（故事不因邻帧失败中断）；
 *  - deps.cache（FrameCache）在 compileScene 内透明加速（IndexedDB → 刷新不丢渲染进度）。
 */

import type { CaptureRules } from '../core/capture';
import type { AnimBackend } from '../backends';
import type { LayoutInfo, LayoutOptions } from '../core/layout';
import type { SchedulerSnapshot } from './types';
import type { EventBus } from './bus';
import { createEventBus } from './bus';
import { createStoryStore, type StoryStore } from './store';
import { createScheduler, type Scheduler } from './scheduler';
import { compileScene, relayoutScenes, type SceneDeps, type SceneState } from './scene';
import type { FrameCache } from './frame-cache';
import { createSceneCompiler, type ScenePlanCompiler } from './plan';
import { createSceneRenderer, type SceneRenderer } from './render-svg';
import type { PlanCompiler, PlanRenderer, StateGraphSpec, StoryStateDef } from './types';

export interface StoryEngineOptions {
  graph: StateGraphSpec;
  host: Element;
  rules?: CaptureRules;
  backend?: AnimBackend;
  store?: StoryStore;
  bus?: EventBus;
  /** 缺省 SceneRenderer（v3 SvgRenderer 包装）；测试可注入 spy */
  renderer?: PlanRenderer;
  compiler?: PlanCompiler;
  layout?: LayoutOptions;
  stepMs?: number;
  warn?: (msg: string) => void;
  /** true = 不等待全量帧渲染（首帧就绪即播，其余后台队列流式补齐） */
  lazy?: boolean;
  /** 帧渲染缓存（source 形态命中跳渲染；配合 IndexedDB 实现刷新不中断） */
  cache?: FrameCache;
}

export interface StoryEngine {
  graph: StateGraphSpec;
  scenes: ReadonlyMap<string, SceneState>;
  /** 状态的拓扑编译序（entry 起 BFS） */
  order: string[];
  store: StoryStore;
  bus: EventBus;
  scheduler: Scheduler;
  compiler: PlanCompiler;
  renderer: PlanRenderer;
  layoutInfo(): LayoutInfo | null;
  snapshot(): SchedulerSnapshot;
  start(): Promise<void>;
  stop(): void;
  /** committed 位置/锚配置变更后手动触发（store.subscribe 已自动挂接） */
  relayout(): void;
  /** 流式进度：已就绪帧数 / 总帧数 */
  scenesProgress(): { ready: number; total: number };
  /** 确保帧渲染就绪（渲染排队 + 插队）；svg/canvas 消费方追帧用 */
  ensureScene(id: string): Promise<SceneState>;
  /** 等待全部帧尝试完毕（含失败记录）；非 lazy 创建内部与导出打包用 */
  scenesDone(): Promise<void>;
  /** 失败帧清单（lazy 模式：单帧源文渲染失败不阻断故事） */
  sceneFailures(): { frame: string; message: string }[];
  dispose(): void;
}

/** 从 entry 起 BFS 的 def 序（script 状态基底 = 其拓扑前驱；不可达状态殿后） */
export function topoOrder(graph: StateGraphSpec): string[] {
  const adj = new Map<string, string[]>();
  for (const e of graph.edges) {
    const l = adj.get(e.from) ?? [];
    l.push(e.to);
    adj.set(e.from, l);
  }
  const seen = new Set<string>();
  const order: string[] = [];
  const queue = [graph.entry];
  while (queue.length) {
    const id = queue.shift() as string;
    if (seen.has(id)) continue;
    seen.add(id);
    if (graph.states.some((s) => s.id === id)) order.push(id);
    for (const n of adj.get(id) ?? []) if (!seen.has(n)) queue.push(n);
  }
  for (const s of graph.states) if (!seen.has(s.id)) order.push(s.id);
  return order;
}

export async function createStoryEngine(o: StoryEngineOptions): Promise<StoryEngine> {
  const bus = o.bus ?? createEventBus();
  const store = o.store ?? createStoryStore({ vars: o.graph.vars });
  const order = topoOrder(o.graph);
  const defOf = new Map(o.graph.states.map((s) => [s.id, s]));
  const defs = order.map((id) => defOf.get(id)).filter(Boolean) as StoryStateDef[];

  /* ============ 流式渲染队列（并发 1） ============ */
  const deps: SceneDeps = { rules: o.rules ?? o.backend?.rules, backend: o.backend, warn: o.warn, cache: o.cache };
  const sceneMap = new Map<string, SceneState>();
  const scenesList: SceneState[] = [];
  const queue: StoryStateDef[] = [...defs];
  const waiters = new Map<string, { p: Promise<SceneState>; res: (s: SceneState) => void; rej: (e: Error) => void }>();
  const doneWaiters: { res: () => void; rej: (e: Error) => void }[] = [];
  const failures: { frame: string; message: string }[] = [];
  let running = false;
  let runningDefId: string | null = null;
  let disposed = false;

  const notifyProgress = (): void => { bus.emit('sys:scenes:progress', { ready: sceneMap.size, total: defs.length }); };
  const settleDone = (): void => {
    if (queue.length || running || waiters.size) return;
    while (doneWaiters.length) {
      const w = doneWaiters.shift() as { res: () => void; rej: (e: Error) => void };
      if (failures.length) w.rej(new Error(`[story] 帧渲染失败 ${failures[0]!.frame}: ${failures[0]!.message}`));
      else w.res();
    }
  };

  async function renderOne(def: StoryStateDef): Promise<SceneState> {
    const exist = sceneMap.get(def.id);
    if (exist) return exist;
    let prev: SceneState | null = null;
    if (def.script) {
      const i = defs.findIndex((d) => d.id === def.id);
      const base = i > 0 ? defs[i - 1] as StoryStateDef : null;
      prev = base ? await renderOne(base) : null;
    }
    const scene = await compileScene(def, deps, prev);
    if (!sceneMap.has(scene.id)) { sceneMap.set(scene.id, scene); scenesList.push(scene); }
    return sceneMap.get(def.id) as SceneState;
  }

  function pump(): void {
    if (running || disposed) return;
    const def = queue.shift();
    if (!def) { settleDone(); return; }
    running = true;
    runningDefId = def.id;
    void renderOne(def)
      .then((s) => { const w = waiters.get(def.id); waiters.delete(def.id); w?.res(s); relayoutRef(); })
      .catch((e: Error) => {
        failures.push({ frame: def.id, message: e.message });
        bus.emit('sys:scenes:error', { frame: def.id, message: e.message });
        const w = waiters.get(def.id); waiters.delete(def.id); w?.rej(e);
      })
      .finally(() => {
        running = false;
        runningDefId = null;
        notifyProgress();
        if (!disposed) { pump(); settleDone(); }
      });
  }

  function ensureScene(id: string): Promise<SceneState> {
    const hit = sceneMap.get(id);
    if (hit) return Promise.resolve(hit);
    const pending = waiters.get(id);
    if (pending) return pending.p;
    let res!: (s: SceneState) => void;
    let rej!: (e: Error) => void;
    const p = new Promise<SceneState>((r, j) => { res = r; rej = j; });
    waiters.set(id, { p, res, rej });
    if (runningDefId !== id) {
      const idx = queue.findIndex((d) => d.id === id);
      const def = idx >= 0 ? queue.splice(idx, 1)[0] : defOf.get(id);
      if (def) queue.unshift(def);
      else { waiters.delete(id); rej(new Error(`[story] scene ${id} 不存在`)); return p; }
    }
    pump();
    return p;
  }

  function scenesDone(): Promise<void> {
    if (!queue.length && !running && !waiters.size) {
      return failures.length ? Promise.reject(new Error(`[story] ${failures.length} 帧渲染失败：${failures[0]!.frame}`)) : Promise.resolve();
    }
    return new Promise<void>((res, rej) => { doneWaiters.push({ res, rej }); });
  }

  /* ============ 布局（幂等；新帧就绪合并触发） ============ */
  /** 仅 committed+global 变化才触发布局重算（draft/keep-preview 走渲染层，不拆布局） */
  const snapshotKey = (): string => {
    const snap = store.position.snapshot();
    return JSON.stringify([snap.committed, snap.global]);
  };
  let layout: LayoutInfo | null = relayoutScenes(scenesList, store.position.snapshot().committed, o.layout ?? {}, store.position.globalCommitted());

  const compiler: ScenePlanCompiler = (o.compiler as ScenePlanCompiler | undefined)
    ?? createSceneCompiler({ sceneOf: (id) => ensureScene(id), stepMs: o.stepMs });
  const renderer = o.renderer ?? createSceneRenderer();
  renderer.mount(o.host);

  const scheduler = createScheduler({ graph: o.graph, compiler, renderer, bus, store });

  let lastCommitted = snapshotKey();
  let pendingRelayout = false;
  const relayout = (): void => {
    // applyLayout 对当前挂载层做结构性 DOM 操作（removeChild/包裹节点）——
    // 补间执行期禁止触碰，挂起至相位离开 executing 再重放（lazy 后台帧就绪的主要竞态源）
    if (scheduler.snapshot.phase === 'executing') { pendingRelayout = true; return; }
    pendingRelayout = false;
    const snap = store.position.snapshot();
    layout = relayoutScenes(scenesList, snap.committed, o.layout ?? {}, snap.global);
    compiler.invalidate?.();
    lastCommitted = snapshotKey();
    const cur = scheduler.snapshot.nodeId;
    const scene = cur ? sceneMap.get(cur) : null;
    // 补间进行中：跳过静态刷新（避免与 applyDiff 树操作竞态），下一帧 plan 自然覆盖；
    // lazy 模式的 idle 窗口（后台帧就绪早于 start）同样跳过——首帧展示由 plan0 的 applyDiff 完成
    // executing 已在函数头部整体挂起；lazy 模式的 idle 窗口跳过（首帧展示由 plan0 补间完成）
    if (scene && 'applySnapshot' in renderer && !(o.lazy && scheduler.snapshot.phase === 'idle')) (renderer as SceneRenderer).applySnapshot(scene);
  };
  // 前向引用（pump 早于 relayout 定义）
  let relayoutRef = (): void => { /* 初始化前不触发 */ };
  relayoutRef = relayout;
  const unsubStore = store.subscribe(() => {
    if (snapshotKey() === lastCommitted) return; // 仅 committed（entity/global）变化触发布局
    relayout();
  });
  scheduler.subscribe((s) => {
    if (pendingRelayout && s.phase !== 'executing') relayout();
  });

  /* ============ 启动：两种模式共享流式队列；非 lazy 在创建处等待全量 ============ */
  pump(); // 后台从 entry 序开始逐帧预取（并发 1，不阻塞）
  if (!o.lazy) {
    // 非流式：保持原语义——全部帧编译（含失败即 throw）后才返回
    await scenesDone().catch((e) => { disposed = true; throw e; });
    relayout(); // 全量就绪：初始布局与旧语义一致（scenes 完整后再定案）
  }
  notifyProgress();

  return {
    graph: o.graph,
    scenes: sceneMap,
    order,
    store,
    bus,
    scheduler,
    compiler,
    renderer,
    layoutInfo: () => layout,
    snapshot: () => scheduler.snapshot,
    start: () => scheduler.start(),
    stop: () => scheduler.stop(),
    relayout,
    scenesProgress: () => ({ ready: sceneMap.size, total: defs.length }),
    ensureScene,
    scenesDone,
    sceneFailures: () => [...failures],
    dispose() {
      disposed = true;
      queue.length = 0;
      scheduler.stop();
      unsubStore();
      renderer.dispose();
    },
  };
}
