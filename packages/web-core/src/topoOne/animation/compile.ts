import type { DiagramSchema } from '../core/types';
import type { AnimationMode, AnimationStepSpec } from './types';

export interface CompiledAnimation {
  steps: AnimationStepSpec[];
  mode?: AnimationMode;
  stepMs?: number;
}

/**
 * Mermaid renders the flowchart family as a `flowchart` SVG where node group
 * ids look like `<renderId>-flowchart-<id>-<n>`; emit a suffix-match candidate
 * so declared steps resolve precisely. `#<id>` covers engines that keep raw
 * element ids. Edge ids have no stable DOM mapping in mermaid, so edge
 * references rely on the runtime fallback.
 */
const FLOW_DOM_HINT: Record<string, boolean> = {
  flowchart: true,
  activity: true,
  usecase: true,
  component: true,
};

function nodeSelectors(schema: DiagramSchema, id: string): string[] {
  return FLOW_DOM_HINT[schema.type] ? [`#${id}`, `[id*="flowchart-${id}-"]`] : [`#${id}`];
}

/**
 * Compile a schema-level animation block (node/edge id references, validated
 * server-side) into selector steps for the animation plugin.
 *
 * Ids become "#<id>" selectors (plus engine-aware candidates) resolved against
 * the rendered DOM; when nothing matches the plugin falls back to the
 * built-in adapter, so playback always degrades gracefully.
 * Raw `selectors` pass through.
 */
export function compileSchemaAnimation(
  schema: DiagramSchema,
  anim: import('../core/types').SchemaAnimation | undefined,
): CompiledAnimation | null {
  if (!anim || !anim.steps?.length) return null;
  const steps = anim.steps
    .map((s, i) => ({
      label: s.label ?? `Step ${i + 1}`,
      selectors: [
        ...(s.nodes ?? []).flatMap((id) => nodeSelectors(schema, id)),
        ...(s.edges ?? []).map((id) => `#${id}`),
        ...(s.selectors ?? []),
      ],
    }))
    .filter((s) => s.selectors.length > 0);
  if (!steps.length) return null;
  return { steps, mode: anim.mode, stepMs: anim.stepMs };
}
