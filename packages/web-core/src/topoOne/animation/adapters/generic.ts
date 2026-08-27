import type { AnimationAdapter, AnimationStep } from '../types';

const MAX_STEPS = 60;

function firstLine(el: Element, fallback: string): string {
  const t = (el.textContent ?? '').trim();
  return t ? t.split('\n')[0] : fallback;
}

/**
 * plantuml generic: every shape carries data-source-line - reveal grouped by source line
 * (a natural top-down build-up of the diagram).
 */
export const plantumlGenericAdapter: AnimationAdapter = {
  engine: 'plantuml',
  type: 'any',
  build(svg) {
    const byLine = new Map<number, Element[]>();
    for (const el of svg.querySelectorAll('[data-source-line]')) {
      const line = Number(el.getAttribute('data-source-line')) || 0;
      const list = byLine.get(line);
      if (list) list.push(el);
      else byLine.set(line, [el]);
    }
    const steps: AnimationStep[] = [...byLine.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([line, elements]) => ({ label: `line ${line}`, elements }));
    if (steps.length < 2) return null;
    return { mode: 'reveal', stepMs: 450, steps };
  },
};

/**
 * mermaid generic: document-order reveal of every identifiable element (nodes, edges, labels).
 */
export const mermaidGenericAdapter: AnimationAdapter = {
  engine: 'mermaid',
  type: 'any',
  build(svg) {
    const els = [...svg.querySelectorAll('[id]')].filter((el) => el !== svg);
    if (els.length < 2) return null;
    const steps: AnimationStep[] = [];
    for (let i = 0; i < els.length; i++) {
      const el = els[i];
      if (steps.length === MAX_STEPS - 1 && i < els.length - 1) {
        steps.push({ label: 'rest', elements: els.slice(i) });
        break;
      }
      steps.push({ label: firstLine(el, el.id), elements: [el] });
    }
    return { mode: 'reveal', stepMs: 300, steps };
  },
};
