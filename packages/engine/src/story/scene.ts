/**
 * SceneState 编译（§19.1 原语②）：StoryStateDef → 可渲染场景。
 * 两阶段：phase1 raw 编译（render/capture/ops，一次）；phase2 布局重建
 * （applyLayout 从 raw 幂等，位置提交/锚配置变化时 relayout，不触发后端重渲染）。
 *
 * 流式友好拆分（集成批 1.2/1.3）：compileScene(def, deps, prev) 单帧编译
 * （source 经 FrameCache；script 形态基底 prev 显式传入）；compileScenes = 顺序循环封装。
 */

import type { FrameSource, SceneSpec } from '../core/types';
import { capture, genericRules, type CaptureRules } from '../core/capture';
import type { AnimBackend } from '../backends';
import { applyOps, validateOps } from '../script/apply';
import { sceneToSvg } from '../render/scene-svg';
import { applyLayout, type LayoutInfo, type LayoutOptions } from '../core/layout';
import type { FrameCache } from './frame-cache';
import { frameCacheKey } from './frame-cache';
import type { StoryStateDef } from './types';

export interface SceneState extends FrameSource {
  id: string;
  def: StoryStateDef;
}

export interface SceneDeps {
  rules?: CaptureRules;
  backend?: AnimBackend;
  warn?: (msg: string) => void;
  /** 帧渲染缓存（source 形态命中则跳过后端渲染） */
  cache?: FrameCache;
}

function toScene(id: string, def: StoryStateDef, spec: SceneSpec, svg: SVGSVGElement): SceneState {
  return { id, def, spec, svg, raw: svg.cloneNode(true) as SVGSVGElement, rawSpec: JSON.parse(JSON.stringify(spec)) as SceneSpec };
}

/** phase1：编译单帧。script 形态需 prev（拓扑前驱场景）；source 形态走 deps.cache 加速 */
export async function compileScene(def: StoryStateDef, deps: SceneDeps = {}, prev: SceneState | null = null): Promise<SceneState> {
  const warn = deps.warn ?? ((m: string): void => console.warn(`[story] ${m}`));
  const rules = deps.rules ?? genericRules;

  if (def.script) {
    if (!prev) throw new Error(`[story] script state "${def.id}" 无前态基底`);
    const errs = validateOps(def.script);
    for (const e of errs) warn(`state ${def.id} op[${e.index}] ${e.op}: ${e.message}`);
    if (errs.length === def.script.length) throw new Error(`[story] state "${def.id}" ops 全部非法`);
    const spec = applyOps(prev.rawSpec ?? prev.spec, def.script, (m) => warn(`state ${def.id}: ${m}`));
    const svg = sceneToSvg(spec);
    return toScene(def.id, def, spec, svg);
  }

  let input: string | Element;
  if (typeof def.svg === 'string') input = def.svg;
  else if (def.source && deps.backend) {
    const key = deps.cache ? frameCacheKey(deps.backend.id, def.source) : '';
    const hit = deps.cache && key ? await deps.cache.get(key) : null;
    if (typeof hit === 'string' && hit !== '') {
      console.log('[ta-scene] %s 缓存命中(%s, %d 字节)', def.id, key.slice(0, 18), hit.length);
      input = hit;
    } else {
      try {
        const rendered = await deps.backend.render(def.source);
        input = rendered;
        const len = typeof rendered === 'string' ? rendered.length : -1;
        const head = typeof rendered === 'string' ? rendered.slice(0, 60).replace(/\s+/g, ' ') : '(element)';
        console.log('[ta-scene] %s 渲染 ok(%d 字节) head=%s', def.id, len, head);
        if (deps.cache && key && typeof rendered === 'string') void deps.cache.put(key, rendered);
      } catch (e) {
        console.error('[ta-scene] %s 渲染失败:', def.id, (e as Error).message);
        throw e;
      }
    }
  } else if (def.source) {
    throw new Error(`[story] state "${def.id}" source 需 backend`);
  } else {
    throw new Error(`[story] state "${def.id}" 无 svg/source/script`);
  }
  const cap = capture(input, rules);
  return toScene(def.id, def, cap.spec, cap.svg as SVGSVGElement);
}

/** phase1：按给定顺序编译全部状态的 raw（script 状态以拓扑前驱为基底） */
export async function compileScenes(defs: StoryStateDef[], deps: SceneDeps = {}): Promise<SceneState[]> {
  const scenes: SceneState[] = [];
  for (const def of defs) scenes.push(await compileScene(def, deps, scenes[scenes.length - 1] ?? null));
  return scenes;
}

/** phase2：锚定 + 全局 + committed 实体偏移 的幂等重建（v3 applyLayout 的 story 包装） */
export function relayoutScenes(
  scenes: SceneState[],
  committed: Record<string, { dx: number; dy: number }>,
  opts: LayoutOptions = {},
  global: { dx: number; dy: number } = { dx: 0, dy: 0 },
): LayoutInfo {
  return applyLayout(scenes, { entities: { ...committed }, global: { ...global } }, opts);
}
