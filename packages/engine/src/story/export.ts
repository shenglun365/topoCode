/**
 * 叙事交付包（§19.4 C3：可交互 HTML 单包）
 * 序列化 = 图规格 + 各状态 **raw**（布局前捕获 DOM，运行时幂等重布局）
 *          + committed 位置层 + vars。运行时零后端：plantuml jar / mermaid / dot-wasm
 *          等渲染依赖在编译期即被固化为 svg 字符串。
 */

import type { EntityOffset } from '../core/layout';
import type { StateGraphSpec } from './types';
import type { StoryEngine } from './engine';

export interface StoryPackage {
  version: 1;
  title?: string;
  graph: StateGraphSpec;
  committed: Record<string, EntityOffset>;
  global: EntityOffset;
  vars: Record<string, unknown>;
}

export function serializeStoryPackage(engine: StoryEngine, title?: string): StoryPackage {
  const ser = new XMLSerializer();
  const graph: StateGraphSpec = {
    ...engine.graph,
    states: engine.graph.states.map((def) => {
      const scene = engine.scenes.get(def.id);
      if (scene?.raw) return { ...def, svg: ser.serializeToString(scene.raw), source: undefined, script: undefined };
      return { ...def };
    }),
  };
  const snap = engine.store.position.snapshot();
  return {
    version: 1,
    ...(title ? { title } : {}),
    graph,
    committed: { ...snap.committed },
    global: { ...snap.global },
    vars: JSON.parse(JSON.stringify(engine.store.vars())) as Record<string, unknown>,
  };
}

/** HTML 单包模板：数据 JSON + 内联 ESM runtime（dist/story-runtime.mjs 内容）+ bootstrap */
export function buildStoryHtml(pkg: StoryPackage, runtimeSource: string): string {
  const data = JSON.stringify(pkg).replace(/<\/script>/gi, '<\\/script>');
  const safeTitle = (pkg.title ?? 'Topo Story').replace(/[<>&"]/g, '');
  return `<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${safeTitle}</title>
<style>html,body{margin:0;height:100%;background:#fff}#stage{position:absolute;inset:0;overflow:hidden}</style>
</head>
<body>
<div id="stage"></div>
<script id="story-package" type="application/json">${data}</script>
<script type="module">
${runtimeSource}
const pkg = JSON.parse(document.getElementById('story-package').textContent);
const store = createStoryStore({ vars: pkg.vars, committed: pkg.committed, global: pkg.global });
const engine = await createStoryEngine({ graph: pkg.graph, host: document.getElementById('stage'), store });
await engine.start();
</script>
</body>
</html>`;
}

import { staticSvgString } from '../core/sanitize';

/** 当前/指定状态的脱敏静态 SVG（呈现交付物：与原始产物等价，§6.4 契约不变） */
export function storyStaticSvg(engine: StoryEngine, stateId?: string): string {
  const id = stateId ?? engine.snapshot().nodeId ?? engine.graph.entry;
  const scene = engine.scenes.get(id);
  return scene ? staticSvgString(scene.svg, scene.spec.background) : '';
}
