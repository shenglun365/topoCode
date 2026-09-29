import type { SceneElement, SceneSpec } from '../core/types';
import { commandsToD } from '../core/path';
import { selFor } from '../core/key';

const SVG_NS = 'http://www.w3.org/2000/svg';

/**
 * SceneSpec → 真实 SVG DOM（FrameScript/离线通道的呈现器）。
 * 每个 SceneElement 渲染为带 data-ta-key 的 <g>，使 SVG 渲染器可像对引擎产物一样寻址、增删类。
 */
export function sceneToSvg(spec: SceneSpec): SVGSVGElement {
  const root = document.createElementNS(SVG_NS, 'svg') as SVGSVGElement;
  const w = spec.width || 800;
  const h = spec.height || 600;
  root.setAttribute('xmlns', SVG_NS);
  root.setAttribute('viewBox', `0 0 ${w} ${h}`);
  root.setAttribute('width', String(w));
  root.setAttribute('height', String(h));
  root.setAttribute('data-ta-scene', '1');
  for (const el of spec.elements) root.appendChild(renderEl(el));
  return root;
}

function renderEl(el: SceneElement): SVGGElement {
  const g = document.createElementNS(SVG_NS, 'g');
  g.setAttribute('data-ta-key', el.key);
  g.setAttribute('data-ta-kind', el.kind);
  g.setAttribute('class', 'lf-ta-' + el.kind);
  for (const p of el.paths) {
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', commandsToD(p.d));
    applyStyle(path, { ...el.style, ...p.style });
    g.appendChild(path);
  }
  for (const t of el.text) {
    const text = document.createElementNS(SVG_NS, 'text');
    text.setAttribute('x', String(t.x));
    text.setAttribute('y', String(t.y));
    text.setAttribute('text-anchor', t.anchor);
    text.setAttribute('font-size', String(t.style['font-size'] ?? el.style['font-size'] ?? 14));
    text.setAttribute('fill', String(t.style['fill'] ?? el.style['fill'] ?? '#000'));
    text.textContent = t.content;
    g.appendChild(text);
  }
  return g;
}

function applyStyle(node: SVGElement, style: Record<string, string | number>): void {
  for (const k of ['fill', 'stroke', 'stroke-width', 'opacity', 'stroke-dasharray']) {
    if (style[k] !== undefined) node.setAttribute(k, String(style[k]));
  }
}

/** 用新 spec 就地重绘既有 scene svg（供帧复用/回跳） */
export function repaintScene(svg: SVGSVGElement, spec: SceneSpec): void {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const fresh = sceneToSvg(spec);
  while (fresh.firstChild) svg.appendChild(fresh.firstChild);
}

/** 在 scene svg 内按 key 定位元素根节点 */
export function findEl(svg: Element, el: SceneElement): Element | null {
  return svg.querySelector(selFor(el.key));
}
