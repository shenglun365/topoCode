/**
 * 时间轴控制器
 * @module runtime/TimelineController
 *
 * @description
 * 管理动画时间轴，支持播放、暂停、跳转。
 */

import type { AnimationState } from '../core/types';
import { EventEmitter } from './EventEmitter';
import { RUNTIME } from '../utils/logger';

export interface TimelineOptions {
  /** 默认帧率 */
  fps?: number;
  /** 是否循环播放 */
  loop?: boolean;
  /** 是否自动播放 */
  autoPlay?: boolean;
}

export interface TimelineState {
  playing: boolean;
  currentStep: number;
  totalSteps: number;
  progress: number;
  currentTime: number;
}

export class TimelineController {
  private states: AnimationState[] = [];
  private options: Required<TimelineOptions>;
  private emitter = new EventEmitter();

  // 播放状态
  private playing = false;
  private currentStep = 0;
  private startTime = 0;
  private elapsed = 0;
  private rafId: number | null = null;
  private frameInterval = 100; // ms per frame

  constructor(states: AnimationState[], options?: TimelineOptions) {
    this.states = states;
    this.options = {
      fps: 30,
      loop: false,
      autoPlay: false,
      ...options,
    };
    this.frameInterval = 1000 / this.options.fps;

    if (this.options.autoPlay && states.length > 0) {
      this.play();
    }
  }

  /** 播放 */
  play(fromStep?: number): void {
    if (this.states.length === 0) return;

    this.playing = true;
    if (fromStep !== undefined) {
      this.currentStep = fromStep;
    }
    this.startTime = performance.now() - this.elapsed;
    this.tick();

    this.emitter.emit('play', { step: this.currentStep });
    RUNTIME.info('Timeline play started');
  }

  /** 暂停 */
  pause(): void {
    this.playing = false;
    if (this.rafId) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    this.emitter.emit('pause', { step: this.currentStep });
  }

  /** 停止 */
  stop(): void {
    this.playing = false;
    this.currentStep = 0;
    this.elapsed = 0;
    if (this.rafId) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    this.emitter.emit('stop', {});
    this.emitter.emit('step-change', { step: 0, state: this.states[0] });
  }

  /** 跳转到指定步骤 */
  seek(step: number): void {
    const clamped = Math.max(0, Math.min(this.states.length - 1, step));
    this.currentStep = clamped;
    this.elapsed = 0;
    this.emitter.emit('seek', { step: this.currentStep });
    this.emitter.emit('step-change', { step: this.currentStep, state: this.states[this.currentStep] });
  }

  /** 获取当前状态 */
  getState(): TimelineState {
    return {
      playing: this.playing,
      currentStep: this.currentStep,
      totalSteps: this.states.length,
      progress: this.states.length > 0 ? this.currentStep / (this.states.length - 1) : 0,
      currentTime: this.elapsed,
    };
  }

  /** 获取当前帧 */
  getCurrentState(): AnimationState | null {
    if (this.currentStep >= this.states.length) return null;
    return this.states[this.currentStep];
  }

  /** 获取所有帧 */
  getStates(): AnimationState[] {
    return this.states;
  }

  /** 事件订阅 */
  on(event: string, handler: (...args: any[]) => void): void {
    this.emitter.on(event, handler);
  }

  off(event: string, handler: (...args: any[]) => void): void {
    this.emitter.off(event, handler);
  }

  /** 销毁 */
  destroy(): void {
    this.stop();
    this.states = [];
    this.emitter.removeAllListeners();
  }

  private tick(): void {
    if (!this.playing) return;

    const now = performance.now();
    this.elapsed = now - this.startTime;

    const newStep = Math.min(
      this.states.length - 1,
      Math.floor(this.elapsed / this.frameInterval)
    );

    if (newStep !== this.currentStep) {
      this.currentStep = newStep;
      this.emitter.emit('step-change', { step: this.currentStep, state: this.states[this.currentStep] });
    }

    if (this.currentStep >= this.states.length - 1) {
      if (this.options.loop) {
        this.currentStep = 0;
        this.startTime = performance.now();
        this.emitter.emit('loop', {});
        this.emitter.emit('step-change', { step: 0, state: this.states[0] });
      } else {
        this.playing = false;
        this.emitter.emit('complete', { step: this.currentStep });
        RUNTIME.info('Timeline play completed');
        return;
      }
    }

    this.rafId = requestAnimationFrame(() => this.tick());
  }
}

/** 便捷函数 */
export function createTimeline(states: AnimationState[], options?: TimelineOptions): TimelineController {
  return new TimelineController(states, options);
}
