export type AnimationMode = 'reveal' | 'highlight';

export interface AnimationStep {
  label: string;
  elements: Element[];
}

export interface AnimationPlan {
  mode: AnimationMode;
  /** Per-step duration in ms (before speed scaling). */
  stepMs?: number;
  steps: AnimationStep[];
}

export interface AnimationAdapter {
  /** 'mermaid' | 'plantuml' | 'any' */
  readonly engine: string;
  /** Diagram type, or 'any' for the generic adapter. */
  readonly type: string;
  /** Return null when the rendered SVG has no animatable structure. */
  build(svg: SVGSVGElement, code: string): AnimationPlan | null;
}

/**
 * User-declared step: a label + CSS selectors resolved inside the rendered SVG.
 * All matched elements become visible/active together at that step.
 */
export interface AnimationStepSpec {
  label: string;
  selectors: string[];
}

export interface AnimationPlanContext {
  svg: SVGSVGElement;
  code: string;
  engine: string;
  type: string;
}

/** Full programmatic control: return the exact playback plan (or null for none). */
export type AnimationPlanFactory = (ctx: AnimationPlanContext) => AnimationPlan | null;
