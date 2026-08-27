import { pickEngine, supportsType } from './capabilities';
import { validateDiagram } from './validate';
import { TranspileError, type DegradationPolicy } from './transpile';
import type { DiagramSchema } from './types';
import { resolveEngine } from '../engines/registry';
import type { DegradeWarning, EngineOptions, ThemeName } from '../engines/types';
import { createInteractionPlugins, type InteractionOptions, type PluginSet } from '../plugins';
import type { NodeClickEvent, SharedInteractionState } from '../plugins/types';
import type { AnimationController } from '../animation/controller';
import { compileSchemaAnimation } from '../animation/compile';
import type { AnimationPluginOptions } from '../animation/plugin';

export type DiagramSource =
  | { engine: string; code: string }
  | { engine: string; schema: DiagramSchema };

export interface DiagramOptions {
  source: DiagramSource;
  theme?: ThemeName;
  engineOptions?: EngineOptions;
  /** How unsupported features are handled during transpilation (schema source only). */
  policy?: DegradationPolicy;
   /** Interaction plugins. All enabled by default; `false` disables them entirely. */
   interactions?: InteractionOptions | false;
   /**
    * Playback. Built-in adapters decide what is animatable by default;
    * `steps` (CSS selectors per step) or `plan` (full factory) override them.
    */
   animation?: AnimationPluginOptions;
   /** Mermaid only: click-handler security level (default 'strict'; main project uses 'loose'). */
   securityLevel?: 'strict' | 'loose' | 'antiscript' | 'sandbox';
   /** Mermaid only: theme variable overrides (e.g. catppuccin palette, see themes.ts). */
   themeVariables?: Record<string, string | number>;
  onReady?: (view: DiagramView) => void;
  onError?: (error: { engine: string; message: string }) => void;
  onWarning?: (warnings: DegradeWarning[]) => void;
  onNodeClick?: (e: NodeClickEvent) => void;
}

export interface DiagramView {
  getSvg(): SVGSVGElement | null;
  setTheme(theme: ThemeName): Promise<void>;
  destroy(): void;
  zoomToFit(): void;
  resetView(): void;
  zoomIn(): void;
  zoomOut(): void;
  /** Controller of the animation plugin, or null when the diagram is not animatable. */
  getAnimation(): AnimationController | null;
}

interface Resolved {
  engineName: string;
  code: string;
  warnings: DegradeWarning[];
}

function resolveSource(opts: DiagramOptions): Resolved {
  const src = opts.source;
  if ('code' in src) {
    if (src.engine === 'auto') {
      throw new TranspileError("engine 'auto' requires a schema source (no diagram type to negotiate)", '/source/engine');
    }
    return { engineName: src.engine, code: src.code, warnings: [] };
  }

  const schema = src.schema;
  const validation = validateDiagram(schema);
  if (!validation.valid) {
    const first = validation.errors[0];
    throw new TranspileError(`invalid schema at ${first.path}: ${first.message}`, first.path);
  }

  const engineName = src.engine === 'auto' ? (pickEngine(schema.type) ?? 'mermaid') : src.engine;
  const support = supportsType(engineName, schema.type);
  if (support === 'unsupported') {
    const alt = pickEngine(schema.type);
    throw new TranspileError(
      `engine '${engineName}' cannot render type '${schema.type}'${alt ? `; try engine '${alt}'` : ''}`,
      '/source/engine',
    );
  }

  const engine = resolveEngine(engineName, opts.engineOptions);
  if (!engine.toSource) {
    throw new TranspileError(`engine '${engineName}' does not support schema sources (no toSource)`, '/source/engine');
  }
  const result = engine.toSource(schema, opts.policy ?? 'drop');
  return { engineName, code: result.code, warnings: result.warnings };
}

export function createDiagram(container: HTMLElement, opts: DiagramOptions): DiagramView {
  // Animation resolution: user plan/steps > schema-level animation block > built-in adapter.
  const userAnimRaw: AnimationPluginOptions | false | undefined =
    opts.animation ?? (opts.interactions ? opts.interactions.animation : undefined);
  const userAnim = userAnimRaw && typeof userAnimRaw === 'object' ? userAnimRaw : undefined;
  const animOpts: AnimationPluginOptions | false | undefined =
    userAnimRaw === false
      ? false
      : userAnim?.plan || userAnim?.steps?.length
        ? userAnim
        : (() => {
            const schema = opts.source && 'schema' in opts.source ? opts.source.schema : undefined;
            const compiled = schema ? compileSchemaAnimation(schema, schema.animation) : null;
            return compiled
              ? { ...userAnim, steps: compiled.steps, mode: userAnim?.mode ?? compiled.mode, stepMs: userAnim?.stepMs ?? compiled.stepMs }
              : userAnim;
          })();
  const pluginSet: PluginSet =
    opts.interactions === false
      ? { plugins: [], zoomPan: null }
      : createInteractionPlugins({
          ...opts.interactions,
          animation: animOpts,
        });
  const shared: SharedInteractionState = { dragDistance: 0, animation: null };
  let theme: ThemeName = opts.theme ?? 'dark';
  let disposed = false;
  let renderSeq = 0;
  let currentEngineName = 'unknown';
  let lastCode = '';

  const showError = (message: string) => {
    container.innerHTML = '';
    const el = document.createElement('div');
    el.className = 'td-error';
    el.textContent = `[${currentEngineName}] ${message}`;
    container.appendChild(el);
  };

  const attachPlugins = (svg: SVGSVGElement | null, code: string) => {
    shared.animation = null;
    for (const p of pluginSet.plugins) {
      try {
        p.onAfterRender?.({
          container,
          svg,
          engineName: currentEngineName,
          diagramType: opts.source && 'schema' in opts.source ? opts.source.schema.type : undefined,
          code,
          shared,
          onNodeClick: opts.onNodeClick,
        });
      } catch {
        /* plugin failure must not break rendering */
      }
    }
  };

  const detachPlugins = (code: string) => {
    for (const p of pluginSet.plugins) {
      try {
        p.onBeforeDestroy?.({
          container,
          svg: container.querySelector('svg'),
          engineName: currentEngineName,
          code,
          shared,
          onNodeClick: opts.onNodeClick,
        });
      } catch {
        /* ignore */
      }
    }
  };

  const render = async () => {
    const seq = ++renderSeq;
    let resolved: Resolved;
    try {
      resolved = resolveSource(opts);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      if (seq !== renderSeq || disposed) return;
      showError(message);
      opts.onError?.({ engine: currentEngineName, message });
      return;
    }

    currentEngineName = resolved.engineName;
    const engine = resolveEngine(resolved.engineName, opts.engineOptions);
    if (resolved.warnings.length) opts.onWarning?.(resolved.warnings);

    if (lastCode) detachPlugins(lastCode);
    container.innerHTML = '<div class="td-loading">rendering…</div>';
    try {
      const result = await engine.render({
        container,
        code: resolved.code,
        theme,
        securityLevel: opts.securityLevel,
        themeVariables: opts.themeVariables,
      });
      if (seq !== renderSeq || disposed) return;
      container.innerHTML = result.svg;
      const svg = container.querySelector('svg');
      lastCode = resolved.code;
      attachPlugins(svg, resolved.code);
      opts.onReady?.(view);
    } catch (err) {
      if (seq !== renderSeq || disposed) return;
      const message = err instanceof Error ? err.message : String(err);
      showError(message);
      opts.onError?.({ engine: currentEngineName, message });
    }
  };

  const view: DiagramView = {
    getSvg: () => container.querySelector('svg'),
    setTheme: async (next) => {
      theme = next;
      await render();
    },
    destroy: () => {
      disposed = true;
      renderSeq += 1;
      detachPlugins(lastCode);
      container.innerHTML = '';
    },
    zoomToFit: () => pluginSet.zoomPan?.zoomToFit(),
    resetView: () => pluginSet.zoomPan?.resetView(),
    zoomIn: () => pluginSet.zoomPan?.zoomIn(),
    zoomOut: () => pluginSet.zoomPan?.zoomOut(),
    getAnimation: () => shared.animation,
  };

  void render();
  return view;
}
