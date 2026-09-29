/**
 * 出口脱敏（docs/engine-design.md §6.4）：
 * 移除引擎注入的一切 DOM 痕迹（data-ta-* 属性、ta-* 类、分组 wrapper），
 * 产物与渲染引擎原始输出等价，对用户无感。
 */
const TA_ATTR_RE = /^data-ta-/;
const TA_CLASS_RE = /^ta-/;

export function sanitizeSvg(svg: Element): Element {
  // 先解包分组 wrapper（键在 wrapper 上，解包即一并消失）
  for (const g of Array.from(svg.querySelectorAll('g[data-ta-group]'))) {
    const parent = g.parentNode;
    if (!parent) continue;
    while (g.firstChild) parent.insertBefore(g.firstChild, g);
    parent.removeChild(g);
  }
  const nodes: Element[] = [svg, ...Array.from(svg.querySelectorAll<Element>('*'))];
  for (const el of nodes) {
    for (const attr of Array.from(el.attributes)) {
      if (TA_ATTR_RE.test(attr.name)) el.removeAttribute(attr.name);
    }
    if (el.classList) {
      for (const cls of Array.from(el.classList)) {
        if (TA_CLASS_RE.test(cls)) el.classList.remove(cls);
      }
      if (el.classList.length === 0 && el.getAttribute('class') === '') el.removeAttribute('class');
    }
    const style = (el as SVGElement).style;
    if (style) {
      style.removeProperty('display');
      style.removeProperty('transform');
      style.removeProperty('position');
      style.removeProperty('left');
      style.removeProperty('top');
      style.removeProperty('z-index');
      style.removeProperty('pointer-events');
      style.removeProperty('--ta-len');
      style.removeProperty('--ta-dur');
    }
  }
  return svg;
}

/** 深拷贝一帧产物并脱敏，返回 SVG 字符串（导出/静态呈现用；不影响引擎内部缓存） */
export function staticSvgString(svg: SVGSVGElement | Element, background?: string): string {
  const clone = svg.cloneNode(true) as Element;
  sanitizeSvg(clone);
  if (background) {
    const st = (clone as SVGElement).style;
    if (st) {
      st.removeProperty('background');
      st.background = background;
    }
  }
  return new XMLSerializer().serializeToString(clone);
}
