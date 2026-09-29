import type {
  Box, ElementKind, PathSpec, SceneElement, SceneSpec, StyleMap, TextSpec,
} from './types';
import { unionBox, zeroBox } from './types';
import { shapesToCommands, translateCommands, pathBbox, type Attrs } from './path';
import { deriveKey, disambiguate, normalizeText, selFor } from './key';

export interface ElementGroup {
  members: Element[];
  kind: ElementKind;
  nameHint?: string | null;
}

export interface CaptureRules {
  backend: string;
  typeOf(root: Element): string;
  /** 返回非 null 表示该元素是逻辑元素，整个子树被消费 */
  logicalKind(el: Element): ElementKind | null;
  /** 第一优先级 key 线索 */
  keyHint(el: Element, kind: ElementKind): string | null;
  /** 可选：将匿名平铺兄弟聚类为逻辑元素（PlantUML 等无分组产物的几何分组启发，§11.2） */
  grouping?(containers: Element[]): ElementGroup[];
  /** 可选：忽略产物噪音元素（如 graphviz 画布背景板） */
  ignore?(el: Element): boolean;
}

const SVG_NS = 'http://www.w3.org/2000/svg';
const PASS_CLASSES = new Set(['edges', 'nodes', 'root', 'output', 'viewport', 'layer', 'layers', 'subgraph', 'clusters', 'graph', 'a11y', 'main_anchored']);
const SKIP_TAGS = new Set(['defs', 'style', 'title', 'desc', 'metadata', 'script', 'marker', 'pattern', 'clippath', 'lineargradient', 'radialgradient', 'filter', 'mask', 'symbol', 'image', 'switch', 'use']);
const SHAPE_TAGS = new Set(['path', 'rect', 'line', 'polyline', 'polygon', 'circle', 'ellipse']);

export const genericRules: CaptureRules = {
  backend: 'generic',
  typeOf(root) {
    const t = root.getAttribute('data-diagram-type');
    if (t) return t.toLowerCase();
    const cls = (root.getAttribute('class') || '').toLowerCase();
    if (/flowchart|graph-/i.test(cls)) return 'flowchart';
    if (/sequence/i.test(cls)) return 'sequence';
    return 'diagram';
  },
  logicalKind(el) {
    if (el.tagName.toLowerCase() !== 'g') return null;
    const cls = (el.getAttribute('class') || '').toLowerCase().split(/[\s,]+/).filter(Boolean);
    if (cls.some((c) => PASS_CLASSES.has(c))) return null;
    if (cls.includes('edge') || cls.includes('edgeLabel'.toLowerCase()) || cls.includes('edge-path')) return 'edge';
    if (cls.includes('node') || cls.includes('cluster')) return 'node';
    for (const ch of Array.from(el.children)) {
      if (ch.tagName.toLowerCase() === 'title' && (ch.textContent || '').trim()) return 'node';
    }
    return null;
  },
  keyHint(el) {
    const dn = el.getAttribute('data-name');
    if (dn) return dn;
    // mermaid ≥11.6：边 path 与 label 组带未加渲染前缀的 data-id（裸 L_V5_V3_0）
    const di = el.getAttribute('data-id');
    if (di) {
      const me = /^L_(.+?)_(.+?)_\d+$/.exec(di);
      if (me) return `${me[1]}->${me[2]}`;
      return di;
    }
    for (const ch of Array.from(el.children)) {
      if (ch.tagName.toLowerCase() === 'title') {
        const t = (ch.textContent || '').trim();
        if (t) return t;
      }
    }
    // mermaid ≥11.6 id 带 renderId 前缀（"xf2-flowchart-V5-0"、cluster "xf2-S2"）：
    // 前缀随每次渲染 id 变化，剥除根 svg id 后再走既有正则；cluster 取剥净 id（跨帧 id 稳定键，
    // 标题文本变化走 textCross 而非整灭整生）
    const rawId = el.getAttribute('id') || '';
    const rootId = el.ownerDocument?.documentElement?.getAttribute('id');
    let id = rawId;
    if (rootId && id.startsWith(`${rootId}-`)) id = id.slice(rootId.length + 1);
    const mf = /^flowchart-(.+)-\d+$/.exec(id);
    if (mf) return mf[1] as string;
    const me = /^L_(.+?)_(.+?)_\d+$/.exec(id);
    if (me) return `${me[1]}->${me[2]}`;
    const cls = (el.getAttribute('class') || '').toLowerCase();
    if (cls.includes('cluster') && /^\w[\w.-]*$/.test(id)) return id;
    return null;
  },
};

function attrsOf(el: Element): Attrs {
  const a: Attrs = {};
  for (const at of Array.from(el.attributes)) a[at.name] = at.value;
  return a;
}

function readStyle(el: Element): StyleMap {
  const s: StyleMap = {};
  const styleAttr = el.getAttribute('style');
  if (styleAttr) {
    for (const decl of styleAttr.split(';')) {
      const i = decl.indexOf(':');
      if (i > 0) s[decl.slice(0, i).trim()] = decl.slice(i + 1).trim();
    }
  }
  for (const k of ['fill', 'stroke', 'stroke-width', 'opacity', 'stroke-dasharray', 'font-size', 'font-family']) {
    const v = el.getAttribute(k);
    if (v !== null) s[k] = String(v);
  }
  return s;
}

function parseTranslate(el: Element): { x: number; y: number } {
  const t = el.getAttribute('transform');
  if (!t) return { x: 0, y: 0 };
  const m = /translate\(\s*(-?[\d.]+)(?:[ ,]+(-?[\d.]+))?\s*\)/.exec(t);
  if (!m) return { x: 0, y: 0 };
  return { x: parseFloat(m[1] as string), y: m[2] !== undefined ? parseFloat(m[2]) : 0 };
}

function estimateTextWidth(content: string, fontSize: number): number {
  let w = 0;
  for (const ch of content) {
    w += (ch.codePointAt(0) ?? 0) > 0x2e80 ? fontSize : fontSize * 0.58;
  }
  return w;
}

function textToSpec(el: Element, dx: number, dy: number, inherited: StyleMap): TextSpec {
  const content = normalizeText(el.textContent || '');
  const style = { ...inherited, ...readStyle(el) };
  const fontSize = parseFloat(style['font-size'] ?? '14') || 14;
  const x = parseFloat(el.getAttribute('x') ?? '0') + dx;
  const y = parseFloat(el.getAttribute('y') ?? '0') + dy;
  const anchor = (el.getAttribute('text-anchor') === 'middle' ? 'middle'
    : el.getAttribute('text-anchor') === 'end' ? 'end' : 'start') as TextSpec['anchor'];
  const w = el.tagName.toLowerCase() === 'foreignobject'
    ? parseFloat(el.getAttribute('width') ?? '0') || estimateTextWidth(content, fontSize)
    : estimateTextWidth(content, fontSize);
  const h = el.tagName.toLowerCase() === 'foreignobject'
    ? parseFloat(el.getAttribute('height') ?? '0') || fontSize * 1.2
    : fontSize * 1.2;
  const x0 = anchor === 'middle' ? x - w / 2 : anchor === 'end' ? x - w : x;
  return { content, x, y, anchor, box: { x: x0, y: y - fontSize * 0.85, width: w, height: h }, style };
}

interface RawElement {
  node: Element;
  kind: ElementKind;
  paths: PathSpec[];
  text: TextSpec[];
  style: StyleMap;
  bbox: Box;
  hint: string | null;
}

function sizeOf(svg: Element): { width: number; height: number } {
  const vb = svg.getAttribute('viewBox');
  if (vb) {
    const p = vb.split(/[\s,]+/).map(Number);
    if (p.length === 4 && p.every((n) => !Number.isNaN(n))) {
      return { width: p[2] as number, height: p[3] as number };
    }
  }
  const w = parseFloat(svg.getAttribute('width') ?? '0');
  const h = parseFloat(svg.getAttribute('height') ?? '0');
  return { width: Number.isNaN(w) ? 0 : w, height: Number.isNaN(h) ? 0 : h };
}

/**
 * 根 svg 规范化：内联 style 的 width/height/max-width 优先级高于展示属性，
 * 不清除会覆盖引擎统一的画布尺寸（plantuml 根 style 带 width/height/background，
 * 导致布局盒 ≠ viewBox → 非等比压缩 + 画布边缘空白）；
 * background 剥离入 spec（鬼影层白纸盖住底层内容直至过渡结束）。
 */
function normalizeRoot(svg: Element): { background?: string } {
  const el = svg as SVGElement;
  let background: string | undefined;
  if (el.style) {
    background =
      el.style.getPropertyValue('background') ||
      el.style.getPropertyValue('background-color') ||
      undefined;
    for (const p of ['width', 'height', 'max-width', 'max-height', 'background', 'background-color']) {
      el.style.removeProperty(p);
    }
  }
  if (svg.getAttribute('preserveAspectRatio') === 'none') {
    svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  }
  return { background: background?.trim() || undefined };
}

/**
 * 捕获：引擎产物 SVG -> 规范化 SceneSpec（docs/engine-design.md §5）。
 * 同时把内部键 data-ta-key 回写 DOM，供 Renderer 寻址。
 */
export function capture(
  input: string | Element,
  rules: CaptureRules = genericRules,
): { spec: SceneSpec; svg: Element } {
  let svg: Element;
  if (typeof input === 'string') {
    const doc = new DOMParser().parseFromString(input, 'image/svg+xml');
    if (doc.querySelector('parsererror')) throw new Error('[ta] capture: invalid svg');
    svg = doc.documentElement;
  } else {
    svg = input as Element;
  }
  const root = normalizeRoot(svg);
  const canvas = sizeOf(svg);

  const raws: RawElement[] = [];
  const svgDoc = svg.ownerDocument ?? document;

  // 可选分组启发：将匿名平铺成员包裹进 <g data-ta-group>（dispose 时解包复原）
  const groupMap = new Map<Element, ElementGroup>();
  if (rules.grouping) {
    for (const g of rules.grouping([svg])) {
      if (g.members.length === 0) continue;
      const head = g.members[0] as Element;
      if (!head.parentNode) continue;
      const wrapper = svgDoc.createElementNS(SVG_NS, 'g');
      wrapper.setAttribute('data-ta-group', '1');
      if (g.nameHint) wrapper.setAttribute('data-name', g.nameHint);
      head.parentNode.insertBefore(wrapper, head);
      for (const m of g.members) wrapper.appendChild(m);
      groupMap.set(wrapper, g);
    }
  }

  const gatherFrom = (node: Element, dx: number, dy: number, acc: { paths: PathSpec[]; texts: TextSpec[]; style: StyleMap }): void => {
    for (const child of Array.from(node.children)) {
      const tag = child.tagName.toLowerCase();
      if (SKIP_TAGS.has(tag)) continue;
      const own = parseTranslate(child);
      const cdx = dx + own.x;
      const cdy = dy + own.y;
      if (SHAPE_TAGS.has(tag)) {
        const cmds = shapesToCommands(tag, attrsOf(child));
        acc.paths.push({ d: translateCommands(cmds, cdx, cdy), style: readStyle(child) });
      } else if (tag === 'text' || tag === 'foreignobject') {
        acc.texts.push(textToSpec(child, cdx, cdy, acc.style));
      } else {
        gatherFrom(child, cdx, cdy, acc);
      }
    }
  };

  const consume = (node: Element, kind: ElementKind, dx: number, dy: number): void => {
    const style = readStyle(node);
    const acc = { paths: [] as PathSpec[], texts: [] as TextSpec[], style };
    const tag = node.tagName.toLowerCase();
    if (SHAPE_TAGS.has(tag)) {
      acc.paths.push({ d: translateCommands(shapesToCommands(tag, attrsOf(node)), dx, dy), style });
    } else if (tag === 'text' || tag === 'foreignobject') {
      acc.texts.push(textToSpec(node, dx, dy, style));
    } else {
      gatherFrom(node, dx, dy, acc);
    }
    // 聚合首个形状的视觉样式到元素级（fill/stroke 常画在子形状上）
    const primary = acc.paths[0]?.style ?? {};
    for (const k of ['fill', 'stroke', 'stroke-width', 'opacity', 'stroke-dasharray', 'font-size']) {
      if (primary[k] !== undefined && style[k] === undefined) style[k] = primary[k];
    }
    let bbox = zeroBox();
    let first = true;
    for (const p of acc.paths) {
      const b = pathBbox(p.d);
      bbox = first ? b : unionBox(bbox, b);
      first = false;
    }
    for (const t of acc.texts) {
      bbox = first ? t.box : unionBox(bbox, t.box);
      first = false;
    }
    if (first) bbox = { x: dx, y: dy, width: 0, height: 0 };
    // 空壳逻辑组（无形状、文本全空——如 mermaid 无标签边的空 edgeLabel 壳，其内层空
    // foreignObject 带 16px 排版盒）无渲染语义：计入元素表会产生每帧漂移的指纹噪声并污染
    // stability 分母。跳过。（若不跳，其 data-id 还会与边本体撞键。）
    const hasVisibleText = acc.texts.some((t) => normalizeText(t.content) !== '');
    if (acc.paths.length === 0 && !hasVisibleText) return;
    raws.push({ node, kind, paths: acc.paths, text: acc.texts, style, bbox, hint: rules.keyHint(node, kind) });
  };

  const walkTop = (node: Element, dx: number, dy: number): void => {
    for (const child of Array.from(node.children)) {
      const tag = child.tagName.toLowerCase();
      if (SKIP_TAGS.has(tag)) continue;
      if (rules.ignore?.(child)) continue;
      const own = parseTranslate(child);
      const cdx = dx + own.x;
      const cdy = dy + own.y;
      const grp = groupMap.get(child);
      if (grp) {
        consume(child, grp.kind, cdx, cdy);
      } else if (rules.logicalKind(child)) {
        consume(child, rules.logicalKind(child)!, cdx, cdy);
      } else if (SHAPE_TAGS.has(tag)) {
        const style = readStyle(child);
        const shifted = translateCommands(shapesToCommands(tag, attrsOf(child)), cdx, cdy);
        // 全画幅背景形状（graphviz 白底 polygon / plantuml 背景 rect：无 hint 且覆盖 ~95% 画布）
        // 不参与叙事动画；计入会随画布伸缩产生每帧漂移的 fp 噪声键，污染 stability 分母
        const bb = pathBbox(shifted);
        if (!rules.keyHint(child, 'shape')
          && canvas.width > 0 && canvas.height > 0
          && bb.width * bb.height >= canvas.width * canvas.height * 0.9) continue;
        raws.push({
          node: child,
          kind: 'shape',
          paths: [{ d: shifted, style }],
          text: [],
          style,
          bbox: pathBbox(shifted),
          hint: rules.keyHint(child, 'shape'),
        });
      } else if (tag === 'text' || tag === 'foreignobject') {
        raws.push({
          node: child,
          kind: 'label',
          paths: [],
          text: [textToSpec(child, cdx, cdy, readStyle(child))],
          style: readStyle(child),
          bbox: textToSpec(child, cdx, cdy, readStyle(child)).box,
          hint: rules.keyHint(child, 'label'),
        });
      } else {
        walkTop(child, cdx, cdy);
      }
    }
  };

  walkTop(svg, 0, 0);

  // 键派生 + 消歧 + 回写 DOM
  const labelOf = (r: RawElement): string => normalizeText(r.text.map((t) => t.content).join(' '));
  // 边身份方向无关化：X->Y 形 hint 的键取端点排序（swap 拓扑不变 → 同键 → diff 落 morph 拉伸通道）。
  // 不限 kind：真实 mermaid 无标签边是 edgePaths 容器下的裸 path（walkTop 归 shape），
  // 同样携带 L_<src>_<dst>_n id hint——若只对 edge 类 canon，方向交换即换键重建（合成 fixture 曾掩盖此漏）。
  // 原 hint 仍供下方 endpoints/BFS 解析（degree 序需要方向信息）
  const canonEdgeHint = (hint: string): string => {
    const m = /^([\w.\u0080-\uffff]+)->([\w.\u0080-\uffff]+)$/.exec(hint);
    return m ? [m[1], m[2]].sort().join('~') : hint;
  };
  const baseKeys = raws.map((r) => deriveKey({
    kind: r.kind,
    hintText: r.hint ? canonEdgeHint(r.hint) : r.hint,
    labelText: labelOf(r),
    style: r.style,
    bbox: r.bbox,
    shapeCount: r.paths.length,
  }, rules.backend));
  const keys = disambiguate(baseKeys);

  const elements: SceneElement[] = raws.map((r, i): SceneElement => {
    const key = keys[i] as string;
    r.node.setAttribute('data-ta-key', key);
    return {
      key,
      kind: r.kind,
      bbox: r.bbox,
      paths: r.paths,
      text: r.text,
      style: r.style,
      z: i,
      source: { backend: rules.backend, docIndex: i, sel: selFor(key) },
    };
  });

  // 端点解析（X->Y hint）与 BFS 波次回填，供 order:'degree'
  const byNameKey = new Map(elements.map((e) => [e.key, e]));
  for (const e of elements) {
    const hint = raws[e.z]?.hint ?? '';
    const m = /^([^-]+)->(.+)$/.exec(hint);
    if (m && e.kind === 'edge') {
      const from = `ta:${rules.backend}:name:${m[1]}`;
      const to = `ta:${rules.backend}:name:${m[2]}`;
      if (byNameKey.has(from) && byNameKey.has(to)) e.endpoints = { from, to };
    }
  }
  {
    const incoming = new Map<string, string[]>();
    const nodes = elements.filter((e) => e.kind === 'node');
    for (const e of elements) {
      if (e.kind === 'edge' && e.endpoints) {
        const list = incoming.get(e.endpoints.to) ?? [];
        list.push(e.endpoints.from);
        incoming.set(e.endpoints.to, list);
      }
    }
    const depth = new Map<string, number>();
    let frontier = nodes.filter((n) => !incoming.has(n.key)).map((n) => n.key);
    if (frontier.length === 0 && nodes.length > 0) frontier = [nodes[0]!.key]; // 全环图兜底
    let d = 0;
    while (frontier.length) {
      const next: string[] = [];
      for (const k of frontier) {
        if (depth.has(k)) continue;
        depth.set(k, d);
        for (const e of elements) {
          if (e.kind === 'edge' && e.endpoints?.from === k && !depth.has(e.endpoints.to)) {
            e.depth = d + 0.5;
            next.push(e.endpoints.to);
          }
        }
      }
      frontier = next;
      d++;
    }
    for (const e of elements) {
      if (e.depth === undefined) e.depth = depth.get(e.key);
    }
  }

  const size = sizeOf(svg);
  const spec: SceneSpec = {
    elements,
    width: size.width,
    height: size.height,
    type: rules.typeOf(svg),
    backend: rules.backend,
    ...(root.background && root.background !== 'none' ? { background: root.background } : {}),
  };
  return { spec, svg };
}
