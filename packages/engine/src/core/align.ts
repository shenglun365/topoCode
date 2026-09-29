import type { SceneElement, SceneSpec } from './types';
import { translateCommands } from './path';
import { estimateTextBox } from './text';

const SVG_NS = 'http://www.w3.org/2000/svg';
export const ALIGN_ATTR = 'data-ta-align';

function shiftText(el: SceneElement, dx: number, dy: number): void {
  for (const t of el.text) {
    t.x += dx; t.y += dy;
    const size = parseFloat(t.style['font-size'] ?? '14') || 14;
    t.box = estimateTextBox(t.content, t.x, t.y, t.anchor, size);
  }
}

/** IR 侧施加偏移（就地修改 spec 的元素几何；返回同一对象便于链式） */
export function shiftSpec(spec: SceneSpec, dx: number, dy: number): SceneSpec {
  for (const el of spec.elements) {
    el.bbox = { ...el.bbox, x: el.bbox.x + dx, y: el.bbox.y + dy };
    el.paths = el.paths.map((p) => ({ d: translateCommands(p.d, dx, dy), style: p.style }));
    shiftText(el, dx, dy);
  }
  return spec;
}

/** DOM 侧施加同一偏移：根级注入 <g transform>（脱敏时保留几何、仅剥 data-ta-align 属性） */
export function shiftSvg(svg: Element, dx: number, dy: number, doc?: Document): void {
  const d = doc ?? svg.ownerDocument ?? document;
  const wrap = d.createElementNS(SVG_NS, 'g');
  wrap.setAttribute(ALIGN_ATTR, `${dx} ${dy}`);
  wrap.setAttribute('transform', `translate(${dx} ${dy})`);
  while (svg.firstChild) wrap.appendChild(svg.firstChild);
  svg.appendChild(wrap);
}
