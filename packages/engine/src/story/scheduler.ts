/**
 * Scheduler —— 纯帧序列运行时（v2）
 *
 * 循环：compile(过渡 Plan) → EXECUTING(播过渡) → HOLD(驻留 step/auto 毫秒 ∥ 手动 next/goto)
 *      → 下一帧；末帧到点/手动 next → ended。
 * 事件订阅、when 谓词、动作执行、环路回跳均为 v1 已移除分叉；帧序 = 图线性链。
 * pause：HOLD 计时冻结 + CSS .ta-paused；resume 续剩余时间。goto = 任意帧跳转（diff 直达）。
 */

import type { EventBus } from './bus';
import { createEventBus } from './bus';
import type { StoryStore } from './store';
import { createStoryStore } from './store';
import type {
  PlanCompiler, PlanRenderer, SchedulerSnapshot, StateGraphSpec, StoryEdge, StoryStateDef,
} from './types';
import { END_STATE, validateGraph } from './types';

export interface SchedulerOptions {
  graph: StateGraphSpec;
  compiler: PlanCompiler;
  renderer: PlanRenderer;
  bus?: EventBus;
  store?: StoryStore;
  /** 转移上限（环路保护/调试） */
  stepLimit?: number;
  onError?: (err: Error) => void;
}

export interface Scheduler {
  start(): Promise<void>;
  stop(): void;
  /** HOLD 计时冻结（EXECUTING 中的动画由 CSS .ta-paused 控制；resume 续剩余时间） */
  pause(): void;
  resume(): void;
  /** 手动进下一帧（HOLD 立即生效；EXECUTING/PAUSED 期间挂起至下一 HOLD 头） */
  next(): void;
  /** 任意帧跳转：hold 立即生效；否则下一 HOLD 头消费 */
  goto(stateId: string): void;
  get snapshot(): SchedulerSnapshot;
  subscribe(cb: (s: SchedulerSnapshot) => void): () => void;
}

type HoldOutcome = { kind: 'next' } | { kind: 'jump'; to: string } | { kind: 'end' } | { kind: 'stop' };

export function createScheduler(o: SchedulerOptions): Scheduler {
  const bus = o.bus ?? createEventBus();
  const store = o.store ?? createStoryStore({ vars: o.graph.vars });
  const stepLimit = o.stepLimit ?? 10000;
  let running = false;
  let paused = false;
  let pendingJump: { kind: 'next' } | { kind: 'jump'; to: string } | null = null;
  let wakeHold: ((out: HoldOutcome) => void) | null = null;
  let holdCtl: { pause(): void; resume(): void } | null = null;
  let snap: SchedulerSnapshot = { nodeId: null, phase: 'idle', hops: 0 };
  const subs = new Set<(s: SchedulerSnapshot) => void>();

  const stateOf = (id: string): StoryStateDef => {
    const s = o.graph.states.find((x) => x.id === id);
    if (!s) throw new Error(`[story] state "${id}" not found`);
    return s;
  };
  const outEdge = (id: string): StoryEdge | undefined => o.graph.edges.find((e) => e.from === id);
  const inEdgeOf = (id: string): StoryEdge | undefined => o.graph.edges.find((e) => e.to === id);

  const emitErr = (kind: string, message: string, frame?: string): void => {
    const e = new Error(message);
    bus.emit('sys:error', { kind, message, frame });
    o.onError?.(e);
  };

  function setSnap(patch: Partial<SchedulerSnapshot>): void {
    snap = { ...snap, ...patch };
    for (const cb of [...subs]) cb(snap);
  }

  /** HOLD：pending 跳转 → 驻留计时（auto）→ 否则等手动 next/goto（无出边帧到点 = end） */
  function hold(cur: StoryStateDef, hasNext: boolean): Promise<HoldOutcome> {
    setSnap({ nodeId: cur.id, phase: paused ? 'paused' : 'hold' });
    const dwellMs = cur.dwellMs;
    const auto = cur.auto !== false && dwellMs !== undefined;
    return new Promise<HoldOutcome>((resolve) => {
      let done = false;
      let timer: ReturnType<typeof setTimeout> | null = null;
      let startedAt = 0;
      let remaining = 0;
      const finish = (out: HoldOutcome): void => {
        if (done) return;
        done = true;
        if (timer) clearTimeout(timer);
        timer = null;
        holdCtl = null;
        wakeHold = null;
        resolve(out);
      };
      const takePending = (): boolean => {
        if (!pendingJump) return false;
        const p = pendingJump;
        pendingJump = null;
        finish(p.kind === 'jump' ? p : hasNext ? { kind: 'next' } : { kind: 'end' });
        return true;
      };
      const arm = (ms: number): void => {
        remaining = ms;
        startedAt = Date.now();
        timer = setTimeout(() => finish(hasNext ? { kind: 'next' } : { kind: 'end' }), Math.max(0, ms));
      };
      holdCtl = {
        pause() { if (timer) { clearTimeout(timer); timer = null; remaining -= Date.now() - startedAt; } },
        resume() { if (takePending()) return; if (remaining > 0) arm(remaining); },
      };
      wakeHold = (out) => {
        if ((out.kind === 'next' || out.kind === 'jump') && paused) { pendingJump = out; return; }
        finish(out.kind === 'next' && !hasNext ? { kind: 'end' } : out);
      };
      if (takePending()) return;
      if (auto && hasNext) { arm(dwellMs ?? 0); if (paused) holdCtl.pause(); }
      else if (!hasNext && auto) finish({ kind: 'end' });
    });
  }

  async function run(): Promise<void> {
    const errs = validateGraph(o.graph);
    if (errs.length) throw new Error(`[story] invalid graph: ${errs.join('; ')}`);
    if (running) return;
    running = true;
    let hops = 0;
    let prev: StoryStateDef | null = null;
    let cur = stateOf(o.graph.entry);
    let edgeIn: StoryEdge = inEdgeOf(cur.id) ?? { from: cur.id, to: cur.id };
    try {
      while (running) {
        setSnap({ nodeId: cur.id });
        const plan = await o.compiler.compile(prev, cur, edgeIn, { vars: store.vars() });
        if (!running) break;
        setSnap({ phase: 'executing' });
        await o.renderer.applyPlan(plan);
        if (!running) break;
        const out = outEdge(cur.id);
        const hasNext = !!out && out.to !== END_STATE;
        const held = await hold(cur, hasNext);
        if (!running || held.kind === 'stop') break;
        if (held.kind === 'end') {
          setSnap({ phase: 'ended' });
          bus.emit('sys:done', { lastFrame: cur.id });
          return;
        }
        if (++hops > stepLimit) {
          emitErr('loop', `stepLimit ${stepLimit} exceeded`, cur.id);
          setSnap({ phase: 'ended' });
          bus.emit('sys:done', { lastFrame: cur.id });
          return;
        }
        prev = cur;
        if (held.kind === 'jump') {
          const target = o.graph.states.some((s) => s.id === held.to) ? held.to : null;
          if (!target) continue;
          cur = stateOf(target);
          edgeIn = inEdgeOf(target) ?? { from: cur.id, to: cur.id };
        } else {
          const e = outEdge(cur.id);
          if (!e || e.to === END_STATE) continue;
          cur = stateOf(e.to);
          edgeIn = e;
        }
        setSnap({ hops });
      }
    } finally {
      running = false;
    }
  }

  const api: Scheduler = {
    start: run,
    stop() {
      if (!running) return;
      running = false;
      paused = false;
      pendingJump = null;
      wakeHold?.({ kind: 'stop' });
      setSnap({ phase: 'stopped' });
      bus.emit('sys:stopped', {});
    },
    pause() {
      if (paused) return;
      paused = true;
      holdCtl?.pause();
      if (snap.phase === 'hold') setSnap({ phase: 'paused' });
      bus.emit('sys:pause', {});
    },
    resume() {
      if (!paused) return;
      paused = false;
      holdCtl?.resume();
      if (snap.phase === 'paused') setSnap({ phase: 'hold' });
      bus.emit('sys:resume', {});
    },
    next() {
      if (pendingJump) return;
      if (wakeHold) wakeHold({ kind: 'next' });
      else pendingJump = { kind: 'next' };
    },
    goto(stateId: string) {
      if (stateId !== END_STATE && !o.graph.states.some((s) => s.id === stateId)) return;
      if (stateId === END_STATE) {
        if (wakeHold) wakeHold({ kind: 'end' });
        else { setSnap({ phase: 'ended' }); bus.emit('sys:done', { lastFrame: snap.nodeId ?? undefined }); }
        return;
      }
      if (wakeHold) wakeHold({ kind: 'jump', to: stateId });
      else pendingJump = { kind: 'jump', to: stateId };
    },
    get snapshot() { return snap; },
    subscribe(cb) { subs.add(cb); return () => subs.delete(cb); },
  };
  return api;
}
