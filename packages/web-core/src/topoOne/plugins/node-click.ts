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

function resolveMermaid(el: Element): { nodeId: string; label: string } | null {
  const m = MERMAID_ID_RE.exec(el.id ?? '');
  if (m) return { nodeId: m[2], label: firstText(el) };
  if (/^seq-\d+$/.test(el.id ?? '')) {
    return { nodeId: el.id, label: firstText(el) };
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

    let el: Element | null = (e.target as Element) ?? null;
    while (el && el !== ctx.svg) {
      const hit =
        ctx.engineName === 'plantuml'
          ? resolvePlantuml(el)
          : resolveMermaid(el) ?? resolvePlantuml(el);
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
      el = el.parentElement;
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
