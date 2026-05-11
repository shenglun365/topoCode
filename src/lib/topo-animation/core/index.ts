/**
 * 核心模块
 * @module core
 */

export * from './types';
export * from './instructions';
export { StateMachine, compileScript } from './StateMachine';
export { AnimationEngine, createAnimationEngine } from './AnimationEngine';
export type { EngineOptions } from './AnimationEngine';
