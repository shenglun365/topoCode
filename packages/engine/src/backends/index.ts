import type { CaptureRules, ElementGroup } from '../core/capture';
import { genericRules } from '../core/capture';

/** 宿主注入的模块加载器（避免引擎捆绑重依赖，浏览器端用真实 import） */
export type ModuleInjector = (name: string) => Promise<unknown>;

/**
 * 后端适配器：唯一认识 DSL 渲染库的一层（docs/engine-design.md §11）。
 * render 产物可为 SVG 字符串或 Element；rules 供 capture 规范化。
 */
export interface AnimBackend {
  id: string;
  rules: CaptureRules;
  render(source: string): Promise<string | Element>;
}

export interface BackendRegistration {
  engine: string;   // backend id 或 'any'
  type: string;     // 图类型或 'any'
  backend: AnimBackend;
}

/** 打分解析（参考方案 §4.1）：精确 +2/+2，'any' 通配 0，冲突 -1 */
export function scoreAdapter(r: BackendRegistration, engine: string, type: string): number {
  let s = 0;
  if (r.engine === engine) s += 2;
  else if (r.engine !== 'any') return -1;
  if (r.type === type) s += 2;
  else if (r.type !== 'any') return -1;
  return s;
}

export function resolveBackend(
  list: BackendRegistration[],
  engine: string,
  type: string,
): AnimBackend | null {
  let best: AnimBackend | null = null;
  let bestScore = -1;
  for (const r of list) {
    const s = scoreAdapter(r, engine, type);
    if (s > bestScore) {
      bestScore = s;
      best = r.backend;
    }
  }
  return best;
}

/* ---------------- mermaid ---------------- */

const mermaidRules: CaptureRules = {
  ...genericRules,
  backend: 'mermaid',
  typeOf(root) {
    const g = root.querySelector('g');
    const cls = `${root.getAttribute('class') ?? ''} ${g?.getAttribute('class') ?? ''}`;
    if (/flowchart/i.test(cls)) return 'flowchart';
    if (/sequence/i.test(cls)) return 'sequence';
    if (/state/i.test(cls)) return 'state';
    if (/classDiagram|class-/i.test(cls)) return 'class';
    return genericRules.typeOf(root);
  },
  logicalKind(el) {
    const cls = (el.getAttribute('class') || '').toLowerCase();
    const tag = el.tagName.toLowerCase();
    // v10+ 边是直接挂 class 的 path
    if (tag === 'path' && /flowchart-link/.test(cls)) return 'edge';
    if (tag !== 'g') return null;
    const tokens = cls.split(/[\s,]+/);
    if (tokens.includes('edgeLabel')) return null; // 标签独立成 label 元素
    if (tokens.includes('node') || tokens.includes('nodeLabel')) return 'node';
    if (tokens.includes('cluster')) return 'node';
    return genericRules.logicalKind(el);
  },
  keyHint(el, kind) {
    const g = genericRules.keyHint(el, kind);
    if (g) return g;
    const cls = el.getAttribute('class') || '';
    const id = el.getAttribute('id') || '';
    // subgraph cluster：id 即子图名（如 S）；不锚定则框体宽度随标题变化 → 指纹漂移、每帧闪烁
    if (/cluster/.test(cls) && id && !/\s/.test(id)) return id;
    const ls = /LS-([^\s]+)/.exec(cls);
    const le = /LE-([^\s]+)/.exec(cls);
    if (ls && le) return `${ls[1]}->${le[1]}`;
    // L_A_B_n 端点对由 genericRules 统一提取（键的排序归一在 capture 层）
    return null;
  },
};

export interface MermaidBackendOptions {
  securityLevel?: 'strict' | 'loose' | 'antiscript' | 'sandbox';
  theme?: string;
  /** 主题变量覆盖（如 catppuccin 调色板；与宿主 graph-kernel themes 共用口径） */
  themeVariables?: Record<string, string | number>;
  /** 其余 mermaid.initialize 配置透传 */
  initialize?: Record<string, unknown>;
}

export function createMermaidBackend(inject?: ModuleInjector, opts: MermaidBackendOptions = {}): AnimBackend {
  return {
    id: 'mermaid',
    rules: mermaidRules,
    async render(source: string): Promise<string | Element> {
      const load = inject ?? ((n: string) => import(/* @vite-ignore */ n));
      const mod = (await load('mermaid')) as { default?: { initialize(c: unknown): void; render(id: string, code: string): Promise<{ svg: string }> } };
      const mm = mod.default ?? mod;
      if (!('render' in mm)) throw new Error('[ta] mermaid module shape unexpected');
      mm.initialize({
        startOnLoad: false,
        securityLevel: 'loose',
        ...(opts.theme ? { theme: opts.theme } : {}),
        ...(opts.themeVariables ? { themeVariables: opts.themeVariables } : {}),
        ...(opts.initialize ?? {}),
      });
      const id = `ta-mermaid-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}`;
      const out = await mm.render(id, source);
      return out.svg;
    },
  };
}

/* ---------------- graphviz / dot ---------------- */

const dotRules: CaptureRules = {
  ...genericRules,
  backend: 'dot',
  typeOf(root) {
    if (root.querySelector('g.graph, graph')) return 'graphviz';
    return genericRules.typeOf(root);
  },
  // graphviz 原生 SVG：g.node / g.edge 且各带 <title>名，generic 规则已覆盖
};

export function createGraphvizBackend(inject?: ModuleInjector): AnimBackend {
  return {
    id: 'dot',
    rules: dotRules,
    async render(source: string): Promise<string | Element> {
      const load = inject ?? ((n: string) => import(/* @vite-ignore */ n));
      const mod = (await load('@hpcc-js/wasm-graphviz')) as { Graphviz?: { load(): Promise<{ dot(input: string, format: string): Promise<string> }> } };
      const G = mod.Graphviz ?? (mod as unknown as { default: { Graphviz: typeof mod.Graphviz } }).default?.Graphviz;
      if (!G) throw new Error('[ta] graphviz module not found');
      const gv = await G.load();
      return gv.dot(source, 'svg');
    },
  };
}

/* ---------------- plantuml ---------------- */

/**
 * PlantUML v1.2026.8 实测产物无 id/class/data-source-line，消息与盒子为匿名平铺兄弟。
 * 分组启发：容器内连续图形元素累积，遇 <text> 收尾成组（文本 = 元素语义核心）；
 * 含 line/polygon 的组判 edge，纯 rect+text 判 node。
 */
const plantumlRules: CaptureRules = {
  ...genericRules,
  backend: 'plantuml',
  typeOf(root) {
    const t = root.getAttribute('data-diagram-type');
    if (t) return t.toLowerCase();
    return genericRules.typeOf(root);
  },
  grouping(roots): ElementGroup[] {
    const groups: ElementGroup[] = [];
    const containers: Element[] = [];
    for (const root of roots) {
      containers.push(root);
      for (const g of Array.from(root.querySelectorAll('g'))) {
        let isLogical = false;
        for (const ch of Array.from(g.children)) if (ch.tagName.toLowerCase() === 'title') isLogical = true;
        if (!isLogical) containers.push(g);
      }
    }
    for (const c of containers) {
      let members: Element[] = [];
      let hasGraphic = false;
      for (const child of Array.from(c.children)) {
        const tag = child.tagName.toLowerCase();
        if (tag === 'g') {
          // 已有 title 的组（参与者）走 logical 路径，中断累积
          if (members.length && hasGraphic) { pushGroup(groups, members); }
          members = []; hasGraphic = false;
          continue;
        }
        if (['rect', 'line', 'polygon', 'path', 'circle', 'ellipse', 'polyline'].includes(tag)) {
          members.push(child); hasGraphic = true;
        } else if (tag === 'text') {
          members.push(child);
          if (hasGraphic) pushGroup(groups, members);
          members = []; hasGraphic = false;
        }
      }
      if (members.length && hasGraphic) pushGroup(groups, members);
    }
    return groups;
  },
};

function pushGroup(groups: ElementGroup[], members: Element[]): void {
  const isEdge = members.some((m) => ['line', 'polygon', 'path'].includes(m.tagName.toLowerCase()))
    && !members.some((m) => m.tagName.toLowerCase() === 'rect');
  groups.push({ members: [...members], kind: isEdge ? 'edge' : 'node', nameHint: null });
}

export function createPlantumlBackend(endpoint: string): AnimBackend {
  return {
    id: 'plantuml',
    rules: plantumlRules,
    async render(source: string): Promise<string> {
      const res = await fetch(`${endpoint.replace(/\/$/, '')}/svg`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ source }),
      });
      if (!res.ok) throw new Error(`[ta] plantuml render failed: ${res.status}`);
      return res.text();
    },
  };
}

/** 离线模式：直接喂入产物 SVG（fixture / 手动渲染），三后端通用 */
export function createOfflineBackend(id: string, svgProvider: (source: string) => string | Promise<string | Element>): AnimBackend {
  const rules = id === 'plantuml' ? plantumlRules : id === 'mermaid' ? mermaidRules : id === 'dot' ? dotRules : genericRules;
  return { id, rules, render: async (s) => svgProvider(s) };
}

export { mermaidRules, dotRules, plantumlRules };
