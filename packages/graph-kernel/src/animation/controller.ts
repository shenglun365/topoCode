import type { AnimationMode, AnimationPlan } from './types';

export interface AnimationState {
  /** -1 = reset (reveal: all hidden; highlight: nothing active). */
  index: number;
  playing: boolean;
}

export type AnimationListener = (state: AnimationState) => void;

export interface AnimationController {
  readonly mode: AnimationMode;
  readonly total: number;
  get index(): number;
  get playing(): boolean;
  play(): void;
  pause(): void;
  /** Pause and reset to index -1. */
  stop(): void;
  next(): void;
  prev(): void;
  seek(i: number): void;
  setSpeed(multiplier: number): void;
  subscribe(cb: AnimationListener): () => void;
  dispose(): void;
}

export interface AnimationControllerOptions {
  plan: AnimationPlan;
  stepMs?: number;
  autoPlay?: boolean;
}

const DEFAULT_STEP_MS = 600;

export function createAnimationController(opts: AnimationControllerOptions): AnimationController {
  const { plan } = opts;
  const stepMs = () => (opts.stepMs ?? plan.stepMs ?? DEFAULT_STEP_MS) / speed;
  const allEls = plan.steps.flatMap((s) => s.elements);
  for (const el of allEls) el.classList.add('td-anim-el');

  let index = -1;
  let playing = false;
  let speed = 1;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;
  const listeners = new Set<AnimationListener>();

  const emit = () => {
    for (const cb of [...listeners]) cb({ index, playing });
  };

  const apply = () => {
    plan.steps.forEach((s, i) => {
      for (const el of s.elements) {
        if (plan.mode === 'reveal') el.classList.toggle('td-anim-hidden', i > index);
        else el.classList.toggle('td-anim-active', i === index);
      }
    });
    emit();
  };

  const clearTimer = () => {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
  };

  const tick = () => {
    if (!playing || disposed) return;
    if (index >= plan.steps.length - 1) {
      playing = false;
      clearTimer();
      emit();
      return;
    }
    index += 1;
    apply();
    timer = setTimeout(tick, stepMs());
  };

  const controller: AnimationController = {
    mode: plan.mode,
    total: plan.steps.length,
    get index() {
      return index;
    },
    get playing() {
      return playing;
    },
    play() {
      if (disposed || playing) return;
      if (index >= plan.steps.length - 1) {
        index = -1;
        apply();
      }
      playing = true;
      clearTimer();
      timer = setTimeout(tick, stepMs());
      emit();
    },
    pause() {
      if (!playing) return;
      playing = false;
      clearTimer();
      emit();
    },
    stop() {
      playing = false;
      clearTimer();
      index = -1;
      apply();
    },
    next() {
      playing = false;
      clearTimer();
      if (index < plan.steps.length - 1) {
        index += 1;
        apply();
      }
    },
    prev() {
      playing = false;
      clearTimer();
      if (index > -1) {
        index -= 1;
        apply();
      }
    },
    seek(i) {
      playing = false;
      clearTimer();
      index = Math.max(-1, Math.min(plan.steps.length - 1, i));
      apply();
    },
    setSpeed(m) {
      speed = Math.max(0.1, m);
    },
    subscribe(cb) {
      listeners.add(cb);
      cb({ index, playing });
      return () => listeners.delete(cb);
    },
    dispose() {
      disposed = true;
      playing = false;
      clearTimer();
      for (const el of allEls) el.classList.remove('td-anim-el', 'td-anim-hidden', 'td-anim-active');
      listeners.clear();
    },
  };

  apply();
  if (opts.autoPlay) controller.play();
  return controller;
}
