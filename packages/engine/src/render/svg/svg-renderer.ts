import type {
  AnimationMode, ApplyContext, FrameDiff, FrameSource, PathCommand, Renderer, SceneElement,
  TimelineItem, TimelineSpec,
} from '../../core/types';
import { commandsEqual, currentCommands, isomorphicPaths, lerpCommands, translateCommands, writeCommands } from '../../core/path';
import { injectStyle } from '../../css';
import { animDebug, shortKey } from '../../core/debug';

const SVG_NS = 'http://www.w3.org/2000/svg';
const SHAPE_SELECTOR = 'path, rect, line, polyline, polygon, circle, ellipse';
const INJECT_CLASSES = ['ta-el', 'ta-hidden', 'ta-active', 'ta-fx-drawin'];

interface Layer {
  src: FrameSource;
  svg: Element;
}

function selOf(el: SceneElement): string {
  return el.source.sel;
}

function parseTranslateAttr(el: Element): { x: number; y: number } {
  const t = el.getAttribute('transform');
  if (!t) return { x: 0, y: 0 };
  const m = /translate\(\s*(-?[\d.]+)(?:[ ,]+(-?[\d.]+))?\s*\)/.exec(t);
  if (!m) return { x: 0, y: 0 };
  return { x: parseFloat(m[1] as string), y: m[2] !== undefined ? parseFloat(m[2]) : 0 };
}

function accTranslate(el: Element, root: Element): { x: number; y: number } {
  let x = 0, y = 0;
  let cur: Element | null = el;
  while (cur && cur !== root) {
    const t = parseTranslateAttr(cur);
    x += t.x; y += t.y;
    cur = cur.parentElement;
  }
  return { x, y };
}

export interface SvgRendererOptions {
  mode?: AnimationMode;
}

/**
 * SVG 渲染器（docs/engine-design.md §9.1）：
 * 双层结构——新帧 SVG 为基底，上一帧 SVG 仅保留 exit 元素作为鬼影层淡出。
 * stay 元素零操作；move/morph 走 rAF 补间；enter/exit 走 class 切换。
 */
export function createSvgRenderer(_opts: SvgRendererOptions = {}): Renderer {
  let host: Element | null = null;
  let current: Layer | null = null;
  let ghost: Layer | null = null;
  let disposed = false;
  const timers = new Set<ReturnType<typeof setTimeout>>();
  const sleepResolvers: (() => void)[] = [];

  const getDoc = (): Document => (host?.ownerDocument ?? document);

  const after = (ms: number, fn: () => void): void => {
    const t = setTimeout(() => {
      timers.delete(t);
      if (!disposed) fn();
    }, ms);
    timers.add(t);
  };

  const sleep = (ms: number): Promise<void> =>
    new Promise((resolve) => {
      sleepResolvers.push(resolve);
      after(ms, () => {
        const i = sleepResolvers.indexOf(resolve);
        if (i >= 0) sleepResolvers.splice(i, 1);
        resolve();
      });
    });

  const scheduleFrame = (cb: () => void): (() => void) => {
    const w = getDoc().defaultView as (Window & { requestAnimationFrame?: (cb: () => void) => number }) | null;
    if (w && typeof w.requestAnimationFrame === 'function') {
      let alive = true;
      const loop = (): void => {
        if (!alive || disposed) return;
        cb();
      };
      w.requestAnimationFrame(loop);
      return () => { alive = false; };
    }
    const t = setTimeout(cb, 16);
    timers.add(t);
    return () => { clearTimeout(t); timers.delete(t); };
  };

  const tween = (durationMs: number, step: (p: number) => void): Promise<void> =>
    new Promise((resolve) => {
      if (disposed || durationMs <= 0) {
        step(1);
        resolve();
        return;
      }
      const start = Date.now();
      const tick = (): void => {
        if (disposed) return resolve();
        const p = Math.min(1, (Date.now() - start) / durationMs);
        step(p);
        if (p >= 1) return resolve();
        scheduleFrame(tick);
      };
      tick();
    });

  const layoutLayer = (svg: Element, z: number, interactive: boolean): void => {
    const s = svg as SVGElement & { style: CSSStyleDeclaration };
    s.style.position = 'absolute';
    s.style.left = '0';
    s.style.top = '0';
    s.style.zIndex = String(z);
    if (!interactive) s.style.pointerEvents = 'none';
  };

  const unmark = (layer: Layer): void => {
    for (const el of layer.src.spec.elements) {
      const node = layer.svg.querySelector(selOf(el));
      if (!node) continue;
      const html = node as Element & { classList: DOMTokenList; style: CSSStyleDeclaration };
      html.classList.remove(...INJECT_CLASSES);
      html.style.removeProperty('display');
      html.style.removeProperty('transform');
      html.style.removeProperty('transform-origin');
      html.style.removeProperty('transform-box');
      html.style.removeProperty('transition-duration');
      html.removeAttribute('data-ta-ghost');
      const cleanShape = (sh: Element): void => {
        sh.classList.remove('ta-fx-drawin');
        (sh as SVGElement).style.removeProperty('--ta-len');
        (sh as SVGElement).style.removeProperty('--ta-dur');
        (sh as SVGElement).style.removeProperty('display');
      };
      for (const p of Array.from(node.querySelectorAll(SHAPE_SELECTOR))) cleanShape(p);
      if (node.matches(SHAPE_SELECTOR)) cleanShape(node);
    }
  };

  const detachGhost = (): void => {
    if (ghost) {
      unmark(ghost);
      ghost.svg.parentNode?.removeChild(ghost.svg);
      ghost = null;
    }
  };

  const mountAsCurrent = (src: FrameSource): Layer => {
    if (current && current.src !== src) {
      current.svg.parentNode?.removeChild(current.svg);
    }
    const layer: Layer = { src, svg: src.svg };
    host?.appendChild(layer.svg);
    layoutLayer(layer.svg, 0, true);
    current = layer;
    return layer;
  };

  const enterPre = (node: Element): void => {
    node.classList.add('ta-el', 'ta-hidden');
  };

  const enterReveal = (node: Element, item: TimelineItem): Promise<void> => {
    node.classList.remove('ta-hidden');
    const kind = item.transition.type;
    if (kind === 'drawIn') {
      animDebug(`enter drawIn ${shortKey(item.key)}（连线消失重绘，非拉伸）`);
      const shapes = Array.from(node.querySelectorAll('path, line, polyline, polygon'));
      for (const sh of shapes) {
        const el = sh as SVGGeometryElement & { classList: DOMTokenList; style: CSSStyleDeclaration };
        let len = 1000;
        try {
          if (typeof el.getTotalLength === 'function') len = Math.ceil(el.getTotalLength()) || 1000;
        } catch { /* jsdom */ }
        el.style.setProperty('--ta-len', String(len));
        el.style.setProperty('--ta-dur', `${item.transition.durationMs}ms`);
        el.classList.add('ta-fx-drawin');
      }
      return Promise.resolve();
    }
    if (kind === 'scale') {
      // 关键：CSS style.transform 会整体覆盖引擎写在 transform 属性上的位移
      // （mermaid 节点 g[transform=translate(...)]），导致入场瞬间塌到左上、帧尾跳回。
      // 因此 scale 过渡用临时 wrapper 承载「缩放围绕全局 bbox 中心」的属性变换，
      // 绝不让元素自身的 transform 属性被样式覆盖。
      const bbox = item.el.bbox;
      const off = node.parentElement ? accTranslate(node.parentElement, currentLayerSvg(node)) : { x: 0, y: 0 };
      const cx = bbox.x + bbox.width / 2 - off.x;
      const cy = bbox.y + bbox.height / 2 - off.y;
      const { g, unwrap } = wrapNode(node);
      const dur = Math.max(1, item.transition.durationMs);
      return tween(dur, (p) => {
        const s = 0.85 + 0.15 * p;
        if (p >= 1) g.removeAttribute('transform');
        else g.setAttribute('transform', `translate(${cx} ${cy}) scale(${s}) translate(${-cx} ${-cy})`);
      }).then(() => { unwrap(); });
    }
    return Promise.resolve();
  };

  const wrapNode = (node: Element): { g: Element; unwrap: () => void } => {
    const parent = node.parentNode as Node;
    const g = getDoc().createElementNS(SVG_NS, 'g');
    parent.insertBefore(g, node);
    g.appendChild(node);
    return {
      g,
      unwrap: () => {
        if (g.parentNode === parent) parent.insertBefore(node, g);
        g.parentNode?.removeChild(g);
      },
    };
  };

  const runMove = async (node: Element, item: TimelineItem): Promise<void> => {
    const dx = item.el.bbox.x - (item.prev?.bbox.x ?? item.el.bbox.x);
    const dy = item.el.bbox.y - (item.prev?.bbox.y ?? item.el.bbox.y);
    if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
    animDebug(`runMove ${shortKey(item.key)} dx=${dx.toFixed(1)} dy=${dy.toFixed(1)} dur=${item.transition.durationMs}ms delay=${item.delayMs}ms`);
    const { g, unwrap } = wrapNode(node);
    // 起点 = 旧位置：节点 DOM 已在新位置，初始偏移应为 prev − el（= −dx），向 0 收敛
    await tween(item.transition.durationMs, (p) => {
      const k = 1 - p;
      g.setAttribute('transform', `translate(${-dx * k} ${-dy * k})`);
    });
    unwrap();
  };

  const runMorph = async (node: Element, item: TimelineItem): Promise<void> => {
    const prev = item.prev;
    const abort = (why: string): void => animDebug(`morph 放弃 ${shortKey(item.key)}: ${why}`);
    if (!prev || !prev.paths.length) { abort('无 prev 路径'); return; }
    if (prev.paths.length !== item.el.paths.length) { abort(`prev/el 路径数 ${prev.paths.length}≠${item.el.paths.length}`); return; }
    const shapes = Array.from(node.querySelectorAll('path,line,polyline,polygon,rect'));
    if (shapes.length !== prev.paths.length) { abort(`DOM 形状数 ${shapes.length}≠路径数 ${prev.paths.length}`); return; }
    const jobs: { from: PathCommand[]; to: PathCommand[]; el: Element }[] = [];
    for (let i = 0; i < shapes.length; i++) {
      const sh = shapes[i] as Element;
      const off = accTranslate(sh, currentLayerSvg(node));
      const localPrev = translateCommands(prev.paths[i]!.d, -off.x, -off.y);
      const localNext = translateCommands(item.el.paths[i]!.d, -off.x, -off.y);
      const cur = currentCommands(sh);
      if (!cur) { abort('DOM 无 d 属性'); return; }
      if (!isomorphicPaths(cur, localPrev)) { abort(`DOM 当前几何与 prev 不同构 d="${(cur[0]?.c ?? '').slice(0, 1)}…"`); return; }
      if (!isomorphicPaths(localPrev, localNext)) { abort('prev↔el 不同构'); return; }
      // to-DOM 已携带新几何（正常）；与新旧都不符 = 索引/偏移错位 → 放弃形变
      if (!commandsEqual(cur, localPrev, 3) && !commandsEqual(cur, localNext, 3)) { abort('当前 d 与 prev/next 均不符（偏移错位）'); return; }
      jobs.push({ from: localPrev, to: localNext, el: sh });
    }
    for (const j of jobs) writeCommands(j.el, j.from); // 先吸附旧形状再补间
    animDebug(`morph 执行 ${shortKey(item.key)}: ${jobs.length} 形状 from="${(jobs[0]?.from ?? []).length} 命令" delay=${item.delayMs}ms dur=${item.transition.durationMs}ms`);
    let mid = false;
    await tween(item.transition.durationMs, (p) => {
      for (const j of jobs) writeCommands(j.el, lerpCommands(j.from, j.to, p));
      if (!mid && p >= 0.5) {
        mid = true;
        const d0 = jobs[0]?.el.getAttribute('d') ?? '';
        animDebug(`morph 中点 ${shortKey(item.key)}: d="${d0.slice(0, 40)}…"`);
      }
    });
  };

  const currentLayerSvg = (node: Element): Element => {
    let cur: Element | null = node;
    while (cur && cur.tagName.toLowerCase() !== 'svg') cur = cur.parentElement;
    return cur ?? node;
  };

  const renderer: Renderer = {
    mount(h: Element): void {
      host = h;
      const el = h as HTMLElement;
      if (el.style && !el.style.position) el.style.position = 'relative';
      injectStyle(getDoc());
    },

    setFrame(src: FrameSource, o?: { hidden?: boolean }): void {
      if (disposed) return;
      detachGhost();
      const layer = mountAsCurrent(src);
      for (const el of src.spec.elements) {
        const node = layer.svg.querySelector(selOf(el));
        if (!node) continue;
        node.classList.remove('ta-el', 'ta-hidden');
        if (o?.hidden) enterPre(node);
      }
    },

    async applyDiff(diff: FrameDiff, timeline: TimelineSpec, ctx: ApplyContext): Promise<void> {
      if (disposed) return;
      const to = ctx.to;
      if (!ctx.animate) {
        renderer.setFrame(to);
        return;
      }
      // 上一帧转为鬼影层（exit 淡出 + text 旧内容交叉淡出）
      const ghostKeys = new Set<string>([...diff.exit.map((e) => e.key), ...diff.text.map((t) => t.key)]);
      if (current && current.src !== to && ghostKeys.size > 0) {
        const prevLayer = current;
        for (const el of prevLayer.src.spec.elements) {
          const node = prevLayer.svg.querySelector(selOf(el));
          if (!node) continue;
          if (ghostKeys.has(el.key)) {
            node.classList.add('ta-el');
            if (diff.exit.some((e) => e.key === el.key)) {
              node.classList.add('ta-active');
            } else {
              // 纯 text 鬼影：只允许文字交叉淡出；形状必须隐藏，
              // 否则旧框体（如 subgraph 黄色背景盒）会以 z2 遮罩新帧内容直至 detach
              for (const sh of Array.from(node.querySelectorAll(SHAPE_SELECTOR))) {
                (sh as SVGElement).style.display = 'none';
              }
              if (node.matches(SHAPE_SELECTOR)) (node as SVGElement).style.display = 'none';
            }
            node.setAttribute('data-ta-ghost', '1');
          } else {
            (node as SVGElement).style.display = 'none';
          }
        }
        layoutLayer(prevLayer.svg, 2, false);
        (prevLayer.svg as SVGElement).style.background = 'transparent'; // 鬼影不得以白纸盖住新帧内容
        ghost = prevLayer;
        current = null;
      }
      const layer = mountAsCurrent(to);

      const speedScale = 1 / Math.max(0.05, ctx.speed ?? 1);
      const items = timeline.items.map((it) => ({
        ...it,
        delayMs: it.delayMs * speedScale,
        transition: { ...it.transition, durationMs: it.transition.durationMs * speedScale },
      }));

      const jobs: Promise<void>[] = [];
      for (const item of items) {
        const node = layer.svg.querySelector(selOf(item.el));
        switch (item.cls) {
          case 'enter': {
            if (!node) break;
            enterPre(node);
            jobs.push(sleep(item.delayMs).then(() => (disposed ? undefined : enterReveal(node, item))));
            break;
          }
          case 'exit': {
            const gnode = ghost?.svg.querySelector(selOf(item.el));
            if (!gnode) break;
            after(item.delayMs, () => { gnode.classList.add('ta-hidden'); });
            break;
          }
          case 'move': {
            if (!node || !item.prev) break;
            jobs.push((async () => { await sleep(item.delayMs); if (!disposed) await runMove(node, item); })());
            break;
          }
          case 'update': {
            if (!node || !item.prev) break;
            if (item.transition.type === 'morph') {
              jobs.push((async () => { await sleep(item.delayMs); if (!disposed) await runMorph(node, item); })());
            }
            break;
          }
          case 'text': {
            if (!node) break;
            for (const t of Array.from(node.querySelectorAll('text, foreignObject'))) {
              t.classList.add('ta-el', 'ta-hidden');
              after(item.delayMs, () => t.classList.remove('ta-hidden'));
            }
            // 鬼影层旧文本淡出
            if (ghost) {
              const gp = ghost.svg.querySelector(selOf(item.el));
              if (gp) {
                for (const t of Array.from(gp.querySelectorAll('text, foreignObject'))) {
                  t.classList.add('ta-el');
                  after(item.delayMs, () => t.classList.add('ta-hidden'));
                }
              }
            }
            break;
          }
          case 'style':
          default:
            break; // 属性已是新值；style 过渡 CSS 自动处理
        }
      }

      await Promise.all(jobs);
      await sleep(timeline.totalMs * speedScale + 120);
      if (disposed) return;
      detachGhost();
      unmark(layer);
      current = layer;
    },

    snapshot(): FrameSource | null {
      return current?.src ?? null;
    },

    dispose(): void {
      disposed = true;
      for (const t of timers) clearTimeout(t);
      timers.clear();
      for (const r of sleepResolvers.splice(0)) r();
      if (ghost) {
        unmark(ghost);
        ghost.svg.parentNode?.removeChild(ghost.svg);
        ghost = null;
      }
      if (current) {
        unmark(current);
        current.svg.parentNode?.removeChild(current.svg);
      }
      current = null;
      host = null;
    },
  };
  return renderer;
}
