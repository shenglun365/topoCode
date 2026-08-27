import type { AnimationAdapter, AnimationStep } from '../types';

function firstLine(el: Element, fallback: string): string {
  const t = (el.textContent ?? '').trim();
  return t ? t.split('\n')[0] : fallback;
}

/**
 * mermaid gantt: grid/title/sections first, then tasks in DOM order.
 * Each task = its bar rect + its label text (paired by document order).
 */
export const mermaidGanttAdapter: AnimationAdapter = {
  engine: 'mermaid',
  type: 'gantt',
  build(svg) {
    const steps: AnimationStep[] = [];
    const frame = [...svg.querySelectorAll('.grid, .titleText, rect.section, .sectionTitle')];
    if (frame.length > 0) steps.push({ label: 'timeline', elements: frame });

    const rects = [...svg.querySelectorAll('rect.task')];
    const texts = [...svg.querySelectorAll('text.taskText, text.taskTextOutsideLeft, text.taskTextOutsideRight')];
    for (let i = 0; i < rects.length; i++) {
      const els = [rects[i]];
      let label = `task ${i + 1}`;
      const text = texts[i];
      if (text) {
        els.push(text);
        label = firstLine(text, label);
      }
      steps.push({ label, elements: els });
    }
    if (steps.length < 2) return null;
    return { mode: 'reveal', stepMs: 550, steps };
  },
};
