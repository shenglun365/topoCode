import type { DiagramPlugin, PluginContext } from './types';

const DRAG_THRESHOLD_PX = 4;

/** mermaid v11 ids look like `flowchart-A-0`, `stateDiagram-new-0`, `er-USER-0`. */
const MERMAID_ID_RE = /^([a-zA-Z][a-zA-Z0-9]*)-([A-Za-z][\w-]*?)-\d+$/;

function firstText(el: Element): string {
  const title = el.querySelector('title');
  if (title?.textContent) return title.textContent.trim();
  return (el.textContent ?? '').trim().split('\n')[0] ?? '';
}

function resolvePlantuml(el: Element): { nodeId: string; label: string } | null {
  const uid = el.getAttribute('data-entity-uid');
  if (uid) {
    return { nodeId: uid, label: el.getAttribute('data-qualified-name') || firstText(el) };
  }
  // plantuml sequence message: <g class="message" data-entity-1=.. data-entity-2=.. id="msg3">
  if (el.classList?.contains('message') && /^msg\d+$/.test(el.id)) {
    return { nodeId: el.id, label: firstText(el) };
  }
  return null;
}

function resolveMermaid(el: Element, rootPrefix = ''): { nodeId: string; label: string } | null {
  const raw = rootPrefix && el.id?.startsWith(rootPrefix) ? el.id.slice(rootPrefix.length) : (el.id ?? '');
  const m = MERMAID_ID_RE.exec(raw);
  if (m) return { nodeId: m[2], label: firstText(el) };
  if (/^seq-\d+$/.test(raw)) {
    return { nodeId: raw, label: firstText(el) };
  }
  return null;
}

/**
 * Delegation-based node click. Walks up from the hit element to the nearest
 * addressable ancestor:
 * - plantuml: [data-entity-uid] (or sequence .message) - relies on data-* attrs
 * - mermaid:  `{diagramType}-{nodeId}-{n}` id pattern (loose, version-tolerant)
 * Clicks that were part of a pan drag are suppressed via shared.dragDistance.
 */
export function createNodeClickPlugin(): DiagramPlugin {
  let ctx: PluginContext | null = null;
  let cleanup: (() => void)[] = [];

  const onClick = (e: MouseEvent) => {
    if (!ctx?.onNodeClick || !ctx.svg) return;
    if ((ctx.shared.dragDistance ?? 0) > DRAG_THRESHOLD_PX) return;
    const containerRect = ctx.container.getBoundingClientRect();

    // 文本兜底：部分引擎/图型(plantuml class/er/state/activity/mindmap、mermaid mindmap)
    // 不产生可寻址 id，只有可见文本。
    // 优先取「离点击位置最近的文本」(节点内常有多段文本，如 UML 构造型 + 名称)；
    // 全部不可测(getBoundingClientRect 恒 0，如 jsdom)则退回向上遍历途中元素的第一个文本。
    // 仅当全程未命中正式寻址(uid/mermaid id)时作为降级 hit(nodeId = 'txt:' + 文本)。
    const px = e.clientX;
    const py = e.clientY;
    const nearestTextIn = (el: Element, px: number, py: number): string | null => {
      const ts = el.querySelectorAll('text');
      if (el.matches?.('text')) return el.textContent?.trim() || null;
      if (!ts.length) return null;
      let best: string | null = null;
      let bestD = Infinity;
      let measurable = false;
      ts.forEach((t) => {
        const label = t.textContent?.trim();
        if (!label) return;
        let r: DOMRect;
        try { r = t.getBoundingClientRect(); } catch { return; }
        if (!r || (!r.width && !r.height)) return;
        measurable = true;
        const dx = px - (r.left + r.width / 2);
        const dy = py - (r.top + r.height / 2);
        const d = dx * dx + dy * dy;
        if (d < bestD) { bestD = d; best = label; }
      });
      return (measurable && best) ? best : (ts[0]?.textContent?.trim() || null);
    };
    let textFallback: { nodeId: string; label: string } | null = null;
    const nearestText = (px: number, py: number): { nodeId: string; label: string } | null => {
      const svg = ctx?.svg;
      if (!svg) return null;
      const texts = svg.querySelectorAll('text');
      let best: { nodeId: string; label: string } | null = null;
      let bestD = Infinity;
      let measurable = false;
      texts.forEach((t) => {
        const label = t.textContent?.trim();
        if (!label) return;
        let r: DOMRect;
        try { r = t.getBoundingClientRect(); } catch { return; }
        if (!r || (!r.width && !r.height)) return;
        measurable = true;
        const dx = px - (r.left + r.width / 2);
        const dy = py - (r.top + r.height / 2);
        const d = dx * dx + dy * dy;
        if (d < bestD) { bestD = d; best = { nodeId: `txt:${label}`, label }; }
      });
      return measurable ? best : null;
    };

    let el: Element | null = (e.target as Element) ?? null;
    while (el && el !== ctx.svg) {
      const hit =
        ctx.engineName === 'plantuml'
          ? resolvePlantuml(el)
          : resolveMermaid(el, ctx.svg?.id ? `${ctx.svg.id}-` : '') ?? resolvePlantuml(el);
      if (hit) {
        ctx.onNodeClick({
          engine: ctx.engineName,
          nodeId: hit.nodeId,
          label: hit.label,
          diagramType: ctx.diagramType,
          x: Math.round(e.clientX - containerRect.left),
          y: Math.round(e.clientY - containerRect.top),
        });
        return;
      }
      if (!textFallback) {
        const t = nearestTextIn(el, px, py);
        if (t) textFallback = { nodeId: `txt:${t}`, label: t };
      }
      el = el.parentElement;
    }
    if (!textFallback && ctx?.svg) {
      // 注意坐标系一致：文本 rect 为视口坐标，点击也用原始 clientX/Y(不减 container 偏移)
      textFallback = nearestText(e.clientX, e.clientY);
    }
    if (textFallback) {
      ctx.onNodeClick({
        engine: ctx.engineName,
        nodeId: textFallback.nodeId,
        label: textFallback.label,
        diagramType: ctx.diagramType,
        x: Math.round(e.clientX - containerRect.left),
        y: Math.round(e.clientY - containerRect.top),
      });
    }
  };

  return {
    name: 'node-click',
    onAfterRender(c) {
      ctx = c;
      if (!c.svg) return;
      const svg = c.svg;
      svg.style.cursor = 'pointer';
      svg.addEventListener('click', onClick);
      cleanup.push(() => {
        svg.removeEventListener('click', onClick);
        svg.style.cursor = '';
      });
    },
    onBeforeDestroy() {
      for (const un of cleanup.splice(0)) un();
      ctx = null;
    },
  };
}
