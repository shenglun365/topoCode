/**
 * @topocode/topo-animation
 * TopoScript 动画引擎 — 统一的公共 API
 *
 * 使用方式：
 * ```ts
 * import { compile, createAnimationEngine } from '@topo-animation';
 *
 * const { instructions, sceneConfig } = compile(sourceCode);
 * const engine = createAnimationEngine({
 *   container: document.getElementById('canvas')!,
 *   renderer: 'd3',
 * });
 * engine.load(instructions, sceneConfig);
 * engine.play();
 * ```
 *
 * @module topo-animation
 */

// ==================== 核心 ====================
export * from './core';

// ==================== 编译器 ====================
export * from './compiler';
export * from './compiler/plugin';

// ==================== 渲染器 ====================
export * from './renderer';

// ==================== 动画播放器 ====================
export * from './animator';

// ==================== 运行时 ====================
export * from './runtime';

// ==================== 导出 ====================
export * from './export';

// ==================== 工具 ====================
export * from './utils';
