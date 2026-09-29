/**
 * graph-scene —— 统一图 JSON → SceneSpec 适配 + elkjs 自动布局
 *
 * 动画数据机制（canonical + 存在性投影）：
 *   输入 = canonical 全量结构(节点/边/容器) + 每帧存在性清单；
 *   布局只做一次(elk layered)，所有帧投影到同一坐标系 ——
 *   不变节点位置帧间恒定(像素级静止)，播放层只做 enter/exit/modified 切换。
 * 来源解耦：DSL(mermaid/plantuml/dot) 与直接 JSON 均可产出 GraphFrameInput ——
 *   DSL 经 capture 提取后映射；架构演化(evolution.py) 直接输出本结构。
 */
import ELK from 'elkjs/lib/elk.bundled.js';
import type { ElkLayoutArguments, ElkNode, ElkExtendedEdge, ElkEdgeSection } from 'elkjs';
import type { PathCommand, SceneElement, SceneSpec, TextSpec } from './types';
import { estimateTextBox, estimateTextWidth } from './text';

/* ============ 统一图 JSON schema ============ */

export interface GraphNodeInput {
  key: string;
  label: string;
  /** 所属容器 key（缺省顶层） */
  container?: string;
}

export interface GraphEdgeInput {
  key?: string;
  from: string;
  to: string;
  label?: string;
}

export interface GraphContainerInput {
  key: string;
  label: string;
}

export interface GraphFrameInput {
  id: string;
  label?: string;
  /** 该帧存在的节点/边 key（缺省集合） */
  nodes: string[];
  edges: string[];
  /** 该帧处于 modified 状态的节点/边 key（播放层高亮脉冲） */
  modified?: string[];
}

export interface GraphFrameDataInput {
  canonical: {
    nodes: GraphNodeInput[];
    edges: GraphEdgeInput[];
    containers?: GraphContainerInput[];
  };
  frames: GraphFrameInput[];
}

/* ============ 布局产物 ============ */

export interface GraphSceneFrame {
  id: string;
  label: string;
  /** 存在的元素 key（节点 key 原样；边 key 缺省 `${from}->${to}`） */
  has: Set<string>;
  /** modified 高亮集合 */
  modified: Set<string>;
}

export interface GraphScene {
  /** canonical 布局定稿（单 svg 常驻渲染） */
  spec: SceneSpec;
  frames: GraphSceneFrame[];
  /** 节点/边/容器 key → 元素 key 对齐表（=spec.elements 的 key） */
  keys: { nodes: string[]; edges: string[]; containers: string[] };
}

export interface GraphSceneOptions {
  direction?: 'LR' | 'TB';
  /** 主题色（缺省 catppuccin dark 对齐） */
  theme?: {
    nodeFill?: string; nodeStroke?: string; nodeText?: string;
    edgeStroke?: string; edgeText?: string;
    containerStroke?: string; containerText?: string;
  };
}

const DARK = {
  nodeFill: '#181825', nodeStroke: '#585b70', nodeText: '#cdd6f4',
  edgeStroke: '#7f849c', edgeText: '#a6adc8',
  containerStroke: '#45475a', containerText: '#a6adc8',
} as const;

const NODE_H = 38;
const NODE_R = 8;
const CONT_PAD = 20;
const FONT = 13;

/* ============ 构造 ============ */

function roundRect(x: number, y: number, w: number, h: number, r = NODE_R): PathCommand[] {
  return [
    { c: 'M', x: x + r, y },
    { c: 'L', x: x + w - r, y }, { c: 'C', x1: x + w, y1: y, x2: x + w, y2: y + r, x: x + w, y: y + r },
    { c: 'L', x: x + w, y: y + h - r }, { c: 'C', x1: x + w, y1: y + h, x2: x + w - r, y2: y + h, x: x + w - r, y: y + h },
    { c: 'L', x: x + r, y: y + h }, { c: 'C', x1: x, y1: y + h, x2: x, y2: y + h - r, x, y: y + h - r },
    { c: 'L', x, y: y + r }, { c: 'C', x1: x, y1: y, x2: x + r, y2: y, x: x + r, y },
    { c: 'Z' },
  ];
}

function linePath(pts: { x: number; y: number }[]): PathCommand[] {
  return pts.map((p, i) => (i === 0 ? { c: 'M', x: p.x, y: p.y } : { c: 'L', x: p.x, y: p.y } as PathCommand));
}

/** 末段方向箭头三角（填充） */
function arrowHead(a: { x: number; y: number }, b: { x: number; y: number }, size = 8): PathCommand[] {
  const dx = b.x - a.x, dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  const px = -uy, py = ux;
  const tip = b;
  const back = { x: b.x - ux * size, y: b.y - uy * size };
  return [
    { c: 'M', x: tip.x, y: tip.y },
    { c: 'L', x: back.x + px * size * 0.55, y: back.y + py * size * 0.55 },
    { c: 'L', x: back.x - px * size * 0.55, y: back.y - py * size * 0.55 },
    { c: 'Z' },
  ];
}

function textOf(content: string, cx: number, cy: number, fill: string, size = FONT): TextSpec {
  const anchor = 'middle' as const;
  return {
    content, x: cx, y: cy + size * 0.35, anchor,
    box: estimateTextBox(content, cx, cy, anchor, size),
    style: { fill, 'font-size': `${size}px` },
  };
}

/** elk 返回坐标为「相对父容器」，递归累加为绝对坐标 */
function collectAbs(
  children: ElkNode[], ox: number, oy: number,
  pos: Map<string, { x: number; y: number; w: number; h: number }>,
): void {
  for (const ch of children ?? []) {
    const x = ox + (ch.x ?? 0), y = oy + (ch.y ?? 0);
    pos.set(ch.id, { x, y, w: ch.width ?? 0, h: ch.height ?? 0 });
    collectAbs(ch.children ?? [], x, y, pos);
  }
}


/**
 * 统一图 JSON → 布局定稿 SceneSpec + 每帧存在性。
 * 布局只跑一次：canonical 全量结构进 elk(layered)，所有帧共享同一坐标系。
 */
export async function buildGraphScene(input: GraphFrameDataInput, opts: GraphSceneOptions = {}): Promise<GraphScene> {
  const th = { ...DARK, ...opts.theme };
  const { canonical, frames: frameInputs } = input;
  const edgeKeyOf = (e: GraphEdgeInput) => e.key ?? `${e.from}->${e.to}`;
  const nodeById = new Map(canonical.nodes.map((n) => [n.key, n]));
  const containerOf = new Map(canonical.containers?.map((c) => [c.key, c]) ?? []);

  /* ---- elk 图构造（容器=嵌套 children；边统一声明在 root=绝对坐标） ---- */
  const elkNodeOf = (id: string, w: number, h: number): ElkNode => ({ id, width: w, height: h });
  const sizeOf = (label: string): { w: number; h: number } => {
    const w = Math.max(96, Math.min(320, estimateTextWidth(label, FONT) + 28));
    return { w, h: NODE_H };
  };
  const topChildren: ElkNode[] = [];
  const containerChildren = new Map<string, ElkNode[]>();
  for (const c of canonical.containers ?? []) { containerChildren.set(c.key, []); }
  for (const n of canonical.nodes) {
    const s = sizeOf(n.label);
    const elkN = elkNodeOf(n.key, s.w, s.h);
    if (n.container && containerChildren.has(n.container)) containerChildren.get(n.container)!.push(elkN);
    else topChildren.push(elkN);
  }
  for (const c of canonical.containers ?? []) {
    const members = containerChildren.get(c.key)!;
    const w = Math.max(120, ...members.map((m) => m.width ?? 0)) + CONT_PAD * 2;
    const h = Math.max(NODE_H, members.reduce((s, m) => s + (m.height ?? 0) + 16, 0)) + CONT_PAD * 2 + FONT;
    topChildren.push({ id: c.key, width: w, height: h, children: members });
  }
  const elkEdges: ElkExtendedEdge[] = canonical.edges.map((e) => ({ id: edgeKeyOf(e), sources: [e.from], targets: [e.to] }));
  const elkGraph = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': opts.direction ?? 'LR',
      'elk.spacing.nodeNode': '40',
      'elk.layered.spacing.nodeNodeBetweenLayers': '72',
      'elk.spacing.edgeNode': '18',
      'elk.edgeRouting': 'ORTHOGONAL',
      // 跨容器层级边(root 节点 → 容器内节点)的路由必须包含子层级处理, 否则 sections 为空
      'elk.hierarchyHandling': 'INCLUDE_CHILDREN',
      ...(containerOf.size ? { 'elk.padding': `[top=${CONT_PAD},left=${CONT_PAD},bottom=${CONT_PAD},right=${CONT_PAD}]` } : {}),
    },
    children: topChildren,
    edges: elkEdges,
  };

  const elk = new ELK();
  const laid = (await elk.layout(elkGraph as ElkNode)) as ElkNode;

  /* ---- 坐标回填 ---- */
  const pos = new Map<string, { x: number; y: number; w: number; h: number }>();
  collectAbs(laid.children ?? [], 0, 0, pos);

  const elements: SceneElement[] = [];
  let docIndex = 0;
  const el = (e: Omit<SceneElement, 'source' | 'z'> & Partial<Pick<SceneElement, 'z'>>): SceneElement => ({
    ...e, z: e.z ?? 1,
    source: { backend: 'graph-scene', docIndex: docIndex++, sel: `[data-ta-key="${e.key}"]` },
  } as SceneElement);

  // 容器（z0）：elk 给的容器 bbox 直接用
  for (const c of canonical.containers ?? []) {
    const p = pos.get(c.key);
    if (!p) continue;
    elements.push(el({
      key: c.key, kind: 'group', bbox: { x: p.x, y: p.y, width: p.w, height: p.h },
      paths: [{ d: roundRect(p.x, p.y, p.w, p.h, 10), style: { fill: 'none', stroke: th.containerStroke, 'stroke-dasharray': '6 4', 'stroke-width': '1' } }],
      text: [textOf(c.label, p.x + p.w / 2, p.y + 12, th.containerText, 12)],
      style: {},
      z: 0,
    }));
  }
  // 节点（z2）：roundrect + 居中 label
  for (const n of canonical.nodes) {
    const p = pos.get(n.key);
    if (!p) continue;
    elements.push(el({
      key: n.key, kind: 'node', bbox: { x: p.x, y: p.y, width: p.w, height: p.h },
      paths: [{ d: roundRect(p.x, p.y, p.w, p.h), style: { fill: th.nodeFill, stroke: th.nodeStroke, 'stroke-width': '1.4' } }],
      text: [textOf(n.label, p.x + p.w / 2, p.y + p.h / 2, th.nodeText)],
      style: {},
      z: 2,
    }));
  }
  // 边（z1）：elk sections → 折线 + 箭头 + 可选 label
  const laidEdges = new Map(((laid.edges ?? []) as ElkExtendedEdge[]).map((e) => [e.id, e]));
  for (const e of canonical.edges) {
    const key = edgeKeyOf(e);
    const le = laidEdges.get(key);
    const a = pos.get(e.from), b = pos.get(e.to);
    if (!le?.sections?.length || !a || !b) continue;
    const pts: { x: number; y: number }[] = [];
    for (const s of le.sections) {
      // section 坐标相对边的 LCA 容器(container 字段) —— 累加容器绝对偏移
      const co = (s as ElkEdgeSection & { container?: string }).container;
      const cpos = co && co !== 'root' ? pos.get(co) : undefined;
      const cx = cpos?.x ?? 0, cy = cpos?.y ?? 0;
      pts.push({ x: s.startPoint.x + cx, y: s.startPoint.y + cy });
      for (const bp of s.bendPoints ?? []) pts.push({ x: bp.x + cx, y: bp.y + cy });
      pts.push({ x: s.endPoint.x + cx, y: s.endPoint.y + cy });
    }
    // 收缩末段让箭头贴节点边缘
    const paths = [linePath(pts)];
    const styles: Record<string, string>[] = [{ fill: 'none', stroke: th.edgeStroke, 'stroke-width': '1.3' }];
    if (pts.length >= 2) {
      paths.push(arrowHead(pts[pts.length - 2]!, pts[pts.length - 1]!));
      styles.push({ fill: th.edgeStroke, stroke: 'none' });
    }
    const mid = pts[Math.floor(pts.length / 2)] ?? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
    const text = e.label ? [textOf(e.label, mid.x, mid.y - 8, th.edgeText, 11)] : [];
    elements.push(el({
      key, kind: 'edge',
      bbox: {
        x: Math.min(...pts.map((p) => p.x)), y: Math.min(...pts.map((p) => p.y)),
        width: Math.max(...pts.map((p) => p.x)) - Math.min(...pts.map((p) => p.x)),
        height: Math.max(...pts.map((p) => p.y)) - Math.min(...pts.map((p) => p.y)),
      },
      endpoints: { from: e.from, to: e.to },
      paths: paths.map((d, i) => ({ d, style: styles[i]! })),
      text,
      style: {},
      z: 1,
    }));
  }

  /* ---- 画布尺寸 ---- */
  const width = laid.width ?? 0, height = laid.height ?? 0;
  const spec: SceneSpec = {
    elements,
    width, height,
    type: 'graph', backend: 'graph-scene',
    origin: { x: 0, y: 0 },
    background: 'transparent',
  };

  /* ---- 帧存在性 ---- */
  const allKeys = new Set(elements.map((e) => e.key));
  const frames = frameInputs.map((f) => {
    const has = new Set<string>();
    for (const k of f.nodes) if (nodeById.has(k)) has.add(k);
    for (const e of canonical.edges) {
      const k = edgeKeyOf(e);
      if (f.edges.includes(k) && has.has(e.from) && has.has(e.to)) has.add(k);
    }
    const modified = new Set((f.modified ?? []).filter((k) => allKeys.has(k)));
    return { id: f.id, label: f.label ?? f.id, has, modified };
  });

  return {
    spec,
    frames,
    keys: {
      nodes: canonical.nodes.map((n) => n.key),
      edges: canonical.edges.map((e) => edgeKeyOf(e)),
      containers: (canonical.containers ?? []).map((c) => c.key),
    },
  };
}
