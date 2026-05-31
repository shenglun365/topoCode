/**
 * 缓动函数库
 * @module utils/easing
 */

import type { EasingFunction, EasingName } from '../core/types';

// ==================== 线性 ====================
export function linear(t: number): number {
  return t;
}

// ==================== 二次缓动 ====================
export function easeInQuad(t: number): number {
  return t * t;
}
export function easeOutQuad(t: number): number {
  return t * (2 - t);
}
export function easeInOutQuad(t: number): number {
  return t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
}

// ==================== 三次缓动 ====================
export function easeInCubic(t: number): number {
  return t * t * t;
}
export function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}
export function easeInOutCubic(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

// ==================== 指数缓动 ====================
export function easeInExpo(t: number): number {
  return t === 0 ? 0 : Math.pow(2, 10 * t - 10);
}
export function easeOutExpo(t: number): number {
  return t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
}
export function easeInOutExpo(t: number): number {
  if (t === 0 || t === 1) return t;
  return t < 0.5 ? Math.pow(2, 20 * t - 10) / 2 : (2 - Math.pow(2, -20 * t + 10)) / 2;
}

// ==================== 回弹缓动 ====================
export function easeInBack(t: number): number {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return c3 * t * t * t - c1 * t * t;
}
export function easeOutBack(t: number): number {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
}
export function easeInOutBack(t: number): number {
  const c1 = 1.70158;
  const c2 = c1 * 1.525;
  return t < 0.5
    ? (Math.pow(2 * t, 2) * ((c2 + 1) * 2 * t - c2)) / 2
    : (Math.pow(2 * t - 2, 2) * ((c2 + 1) * (t * 2 - 2) + c2) + 2) / 2;
}

// ==================== 弹性缓动 ====================
export function easeInElastic(t: number): number {
  if (t === 0 || t === 1) return t;
  return -Math.pow(2, 10 * t - 10) * Math.sin((t * 10 - 10.75) * (2 * Math.PI) / 3);
}
export function easeOutElastic(t: number): number {
  if (t === 0 || t === 1) return t;
  return Math.pow(2, -10 * t) * Math.sin((t * 10 - 0.75) * (2 * Math.PI) / 3) + 1;
}
export function easeInOutElastic(t: number): number {
  if (t === 0 || t === 1) return t;
  const p = 0.3;
  const s = p / 4;
  return t < 0.5
    ? -(Math.pow(2, 20 * t - 10) * Math.sin((20 * t - 11.125) * (2 * Math.PI) / (3 * s))) / 2
    : (Math.pow(2, -20 * t + 10) * Math.sin((20 * t - 11.125) * (2 * Math.PI) / (3 * s))) / 2 + 1;
}

// ==================== 弹跳缓动 ====================
export function easeInBounce(t: number): number {
  return 1 - easeOutBounce(1 - t);
}
export function easeOutBounce(t: number): number {
  const n1 = 7.5625;
  const d1 = 2.75;
  if (t < 1 / d1) {
    return n1 * t * t;
  } else if (t < 2 / d1) {
    return n1 * (t -= 1.5 / d1) * t + 0.75;
  } else if (t < 2.5 / d1) {
    return n1 * (t -= 2.25 / d1) * t + 0.9375;
  } else {
    return n1 * (t -= 2.625 / d1) * t + 0.984375;
  }
}
export function easeInOutBounce(t: number): number {
  return t < 0.5 ? (1 - easeOutBounce(1 - 2 * t)) / 2 : (1 + easeOutBounce(2 * t - 1)) / 2;
}

// ==================== 缓动函数映射 ====================

/** 所有缓动函数的映射表 */
export const EasingFunctions: Record<EasingName, EasingFunction> = {
  linear,
  easeInQuad,
  easeOutQuad,
  easeInOutQuad,
  easeInCubic,
  easeOutCubic,
  easeInOutCubic,
  easeInExpo,
  easeOutExpo,
  easeInOutExpo,
  easeInBack,
  easeOutBack,
  easeInOutBack,
  easeInElastic,
  easeOutElastic,
  easeInOutElastic,
  easeInBounce,
  easeOutBounce,
  easeInOutBounce,
};

/** 所有缓动函数名称列表 */
export const EasingFunctionNames: EasingName[] = Object.keys(EasingFunctions) as EasingName[];

/** 根据名称获取缓动函数 */
export function getEasingFunction(name: EasingName | string): EasingFunction {
  return EasingFunctions[name as EasingName] || linear;
}
