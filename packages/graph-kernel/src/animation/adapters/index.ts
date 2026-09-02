import { mermaidGanttAdapter } from './gantt';
import { mermaidGenericAdapter, plantumlGenericAdapter } from './generic';
import { mermaidSequenceAdapter, plantumlSequenceAdapter } from './sequence';
import type { AnimationAdapter } from '../types';

const ADAPTERS: AnimationAdapter[] = [
  mermaidSequenceAdapter,
  plantumlSequenceAdapter,
  mermaidGanttAdapter,
  mermaidGenericAdapter,
  plantumlGenericAdapter,
];

function score(a: AnimationAdapter, engine: string, type: string): number {
  let s = 0;
  if (a.engine === engine) s += 2;
  else if (a.engine !== 'any') return -1;
  if (a.type === type) s += 2;
  else if (a.type !== 'any') return -1;
  return s;
}

/** Exact (engine, type) first, then engine-specific generic, then type-specific generic. */
export function resolveAdapter(engine: string, type: string): AnimationAdapter | null {
  let best: AnimationAdapter | null = null;
  let bestScore = 0;
  for (const a of ADAPTERS) {
    const s = score(a, engine, type);
    if (s > bestScore) {
      best = a;
      bestScore = s;
    }
  }
  return best;
}

export {
  mermaidSequenceAdapter,
  plantumlSequenceAdapter,
  mermaidGanttAdapter,
  mermaidGenericAdapter,
  plantumlGenericAdapter,
};
