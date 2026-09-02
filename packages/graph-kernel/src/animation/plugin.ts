import { createAnimationController, type AnimationController } from './controller';
import { resolveAdapter } from './adapters';
import { guessType } from './guessType';
import { ensureToolbar, makeButton } from '../plugins/ui';
import type { DiagramPlugin, PluginContext } from '../plugins/types';
import type {
  AnimationMode,
  AnimationPlan,
  AnimationPlanFactory,
  AnimationStepSpec,
} from './types';

const ANIM_STYLE_ID = 'td-anim-style';
const ANIM_CSS = `
  .td-anim-el { transition: opacity 0.25s ease; }
  .td-anim-hidden { opacity: 0 !important; pointer-events: none; }
  .td-anim-active { filter: drop-shadow(0 0 4px #67e8f9); }
  .td-anim-progress { align-self: center; font-size: 11px; color: #8b93a7; padding: 0 4px; }
`;

export interface AnimationPluginOptions {
  enabled?: boolean;
  autoPlay?: boolean;
  /**
   * Custom steps: which elements each step reveals/highlights (CSS selectors
   * resolved inside the rendered SVG). Falls back to the built-in adapter when
   * nothing matches. `plan` takes precedence over `steps`.
   */
  steps?: AnimationStepSpec[];
  /** Full programmatic control: return the exact AnimationPlan (or null). */
  plan?: AnimationPlanFactory;
  /** Playback mode for selector steps (default 'reveal'). */
  mode?: AnimationMode;
  /** Per-step duration in ms (overrides plan.stepMs / default 600). */
  stepMs?: number;
}

/** Resolve user-declared selector steps into a plan (null when nothing matches). */
export function buildPlanFromSelectors(
  svg: SVGSVGElement,
  steps: AnimationStepSpec[],
  mode: AnimationMode = 'reveal',
): AnimationPlan | null {
  let total = 0;
  const resolved = steps.map((s) => {
    const els = s.selectors.length
      ? [...svg.querySelectorAll(s.selectors.join(', '))]
      : [];
    total += els.length;
    return { label: s.label, elements: els };
  });
  if (total === 0) return null;
  return { mode, steps: resolved };
}

function ensureStyle(): void {
  if (typeof document === 'undefined' || document.getElementById(ANIM_STYLE_ID)) return;
  const st = document.createElement('style');
  st.id = ANIM_STYLE_ID;
  st.textContent = ANIM_CSS;
  document.head.appendChild(st);
}

/**
 * Playback toolbar (reset / play-pause / step + progress) driven by an engine+type adapter.
 * The controller instance is published on shared.state so DiagramView can expose it.
 */
export function createAnimationPlugin(opts: AnimationPluginOptions = {}): DiagramPlugin {
  let controller: AnimationController | null = null;
  let teardown: (() => void) | null = null;

  return {
    name: 'animation',
    onAfterRender(ctx: PluginContext) {
      if (opts.enabled === false || !ctx.svg) return;
      ensureStyle();

      const type = ctx.diagramType ?? guessType(ctx.code ?? '');
      const planCtx = { svg: ctx.svg, code: ctx.code ?? '', engine: ctx.engineName, type };

      // Priority: explicit plan factory > selector steps > built-in adapter.
      let plan: AnimationPlan | null = null;
      if (opts.plan) {
        plan = opts.plan(planCtx);
      } else if (opts.steps?.length) {
        plan = buildPlanFromSelectors(ctx.svg, opts.steps, opts.mode);
      }
      if (!plan) {
        const adapter = resolveAdapter(ctx.engineName, type);
        plan = adapter ? adapter.build(ctx.svg, ctx.code ?? '') : null;
      }
      if (!plan) return;

      controller = createAnimationController({ plan, stepMs: opts.stepMs, autoPlay: opts.autoPlay === true });
      ctx.shared.animation = controller;

      const bar = ensureToolbar(ctx.container);
      const btnStop = makeButton('⏮', 'Reset animation', () => controller?.stop());
      const btnPlay = makeButton('▶', 'Play / pause animation', () => {
        if (!controller) return;
        if (controller.playing) controller.pause();
        else controller.play();
      });
      const btnNext = makeButton('⏭', 'Next step', () => controller?.next());
      const span = document.createElement('span');
      span.className = 'td-anim-progress';
      bar.append(btnStop, btnPlay, btnNext, span);

      const sync = () => {
        if (!controller) return;
        btnPlay.textContent = controller.playing ? '⏸' : '▶';
        span.textContent = `${Math.max(0, controller.index)}/${controller.total}`;
      };
      const unsub = controller.subscribe(sync);
      sync();

      teardown = () => {
        unsub();
        for (const n of [btnStop, btnPlay, btnNext, span]) n.remove();
      };
    },
    onBeforeDestroy(ctx) {
      controller?.dispose();
      controller = null;
      ctx.shared.animation = null;
      teardown?.();
      teardown = null;
    },
  };
}
