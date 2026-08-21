/**
 * 动画播放器
 * @module animator/TopoAnimator
 *
 * @description
 * 播放动画序列，支持 play/pause/stop/seek。
 * 帧率通过脚本配置，默认 10FPS，上限 60FPS。
 */

import type { AnimationState, AnimationSequenceConfig } from '../core/types';
import type { IRenderer } from '../renderer/IRenderer';
import { EventEmitter } from '../runtime/EventEmitter';
import { RENDERER } from '../utils/logger';

export interface AnimatorOptions {
  /** 默认帧率 */
  defaultFps?: number;
  /** 是否自动播放 */
  autoPlay?: boolean;
}

export interface AnimatorState {
  playing: boolean;
  paused: boolean;
  currentStep: number;
  totalSteps: number;
  progress: number; // 0-1
  currentTime: number; // 毫秒
}

export class TopoAnimator {
  private renderer: IRenderer | null = null;
  private states: AnimationState[] = [];
  private sequence: AnimationSequenceConfig | null = null;
  private options: Required<AnimatorOptions>;

  // 播放状态
  private playing = false;
  private paused = false;
  private currentStep = 0;
  private startTime = 0;
  private elapsed = 0;
  private rafId: number | null = null;
  private timers: ReturnType<typeof setTimeout>[] = [];

  // 帧率
  private fps = 10;
  private frameInterval = 100; // ms per frame

  // 事件
  private emitter = new EventEmitter();

  constructor(options?: AnimatorOptions) {
    this.options = {
      defaultFps: 10,
      autoPlay: false,
      ...options,
    };
    this.fps = this.options.defaultFps;
    this.frameInterval = 1000 / this.fps;
  }

  /** 设置渲染器 */
  setRenderer(renderer: IRenderer): void {
    this.renderer = renderer;
  }

  /** 设置动画状态序列 */
  setStates(states: AnimationState[]): void {
    this.states = states;
    this.currentStep = 0;
  }

  /** 设置动画序列 */
  setSequence(sequence: AnimationSequenceConfig): void {
    this.sequence = sequence;

    // 帧率配置
    if (sequence.steps.length > 0) {
      const totalDuration = sequence.steps.reduce((sum, s) => sum + (s.duration || 0) + (s.delay || 0), 0);
      if (totalDuration > 0) {
        const calculatedFps = Math.min(60, Math.max(10, sequence.steps.length / (totalDuration / 1000)));
        this.fps = calculatedFps;
        this.frameInterval = 1000 / this.fps;
      }
    }
  }

  /** 播放 */
  play(fromStep?: number): void {
    if (this.states.length === 0) {
      RENDERER.warn('No states to play');
      return;
    }

    this.playing = true;
    this.paused = false;

    if (fromStep !== undefined) {
      this.currentStep = fromStep;
    }

    this.startTime = performance.now() - this.elapsed;
    this.renderCurrentFrame();
    this.scheduleNextFrame();

    this.emitter.emit('play', { step: this.currentStep });
    RENDERER.info('Animation started', { totalSteps: this.states.length });
  }

  /** 暂停 */
  pause(): void {
    this.paused = true;
    this.playing = false;
    this.clearTimers();

    if (this.rafId) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }

    this.emitter.emit('pause', { step: this.currentStep });
    RENDERER.info('Animation paused');
  }

  /** 恢复 */
  resume(): void {
    if (!this.paused) return;

    this.paused = false;
    this.playing = true;
    this.startTime = performance.now() - this.elapsed;
    this.scheduleNextFrame();

    this.emitter.emit('resume', { step: this.currentStep });
    RENDERER.info('Animation resumed');
  }

  /** 停止 */
  stop(): void {
    this.playing = false;
    this.paused = false;
    this.currentStep = 0;
    this.elapsed = 0;
    this.clearTimers();

    if (this.rafId) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }

    // 渲染第一帧
    if (this.states.length > 0) {
      this.renderFrame(0);
    }

    this.emitter.emit('stop', {});
    RENDERER.info('Animation stopped');
  }

  /** 跳转到指定步骤 */
  seek(step: number): void {
    const clampedStep = Math.max(0, Math.min(this.states.length - 1, step));
    this.currentStep = clampedStep;
    this.elapsed = 0;

    if (this.playing) {
      this.startTime = performance.now();
    }

    this.renderCurrentFrame();
    this.emitter.emit('seek', { step: this.currentStep });
  }

  /** 跳转到百分比 (0-1) */
  seekPercent(percent: number): void {
    const step = Math.floor(percent * this.states.length);
    this.seek(step);
  }

  /** 获取当前状态 */
  getState(): AnimatorState {
    return {
      playing: this.playing,
      paused: this.paused,
      currentStep: this.currentStep,
      totalSteps: this.states.length,
      progress: this.states.length > 0 ? this.currentStep / (this.states.length - 1) : 0,
      currentTime: this.elapsed,
    };
  }

  /** 设置帧率 (10-60) */
  setFps(fps: number): void {
    this.fps = Math.min(60, Math.max(10, fps));
    this.frameInterval = 1000 / this.fps;
  }

  /** 获取帧率 */
  getFps(): number {
    return this.fps;
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
    this.renderer = null;
    this.states = [];
    this.sequence = null;
    this.emitter.removeAllListeners();
  }

  // ==================== 私有方法 ====================

  private renderCurrentFrame(): void {
    if (this.currentStep < this.states.length) {
      this.renderFrame(this.currentStep);
    }
  }

  private renderFrame(step: number): void {
    if (!this.renderer || step >= this.states.length) return;

    const state = this.states[step];
    this.renderer.render(state);

    this.emitter.emit('frame-render', { step, state });
    this.emitter.emit('step-change', { step, state });
  }

  private scheduleNextFrame(): void {
    if (!this.playing || this.paused) return;

    this.rafId = requestAnimationFrame(() => {
      const now = performance.now();
      this.elapsed = now - this.startTime;

      // 计算当前应该渲染的帧
      if (this.sequence && this.sequence.steps.length > 0) {
        this.updateStepBySequence();
      } else {
        // 无序列，按帧率均匀播放
        const newStep = Math.floor(this.elapsed / this.frameInterval);
        if (newStep !== this.currentStep && newStep < this.states.length) {
          this.currentStep = newStep;
          this.renderCurrentFrame();
        }
      }

      // 检查是否结束
      if (this.currentStep >= this.states.length - 1) {
        if (this.sequence?.loop) {
          // 循环播放
          this.currentStep = 0;
          this.startTime = performance.now();
          this.renderCurrentFrame();
          this.scheduleNextFrame();
        } else {
          // 播放结束
          this.playing = false;
          this.emitter.emit('complete', { step: this.currentStep });
          RENDERER.info('Animation completed');
        }
        return;
      }

      this.scheduleNextFrame();
    });
  }

  private updateStepBySequence(): void {
    if (!this.sequence || this.sequence.steps.length === 0) return;

    let accumulatedTime = 0;
    for (let i = 0; i < this.sequence.steps.length; i++) {
      const step = this.sequence.steps[i];
      const stepDuration = (step.duration || 0) + (step.delay || 0);
      accumulatedTime += stepDuration;

      if (this.elapsed < accumulatedTime) {
        // 映射序列步骤到状态索引
        const mappedStep = Math.min(this.states.length - 1, i + 1);
        if (mappedStep !== this.currentStep) {
          this.currentStep = mappedStep;
          this.renderCurrentFrame();
        }
        return;
      }
    }
  }

  private clearTimers(): void {
    for (const timer of this.timers) {
      clearTimeout(timer);
    }
    this.timers = [];
  }
}

/** 便捷函数 */
export function createAnimator(options?: AnimatorOptions): TopoAnimator {
  return new TopoAnimator(options);
}
