import { onBeforeUnmount, onMounted, ref, toValue, watch, type Ref } from 'vue';
import { createDiagram, type DiagramView } from '../core/DiagramView';
import type { DiagramSchema } from '../core/types';
import type { DegradeWarning, ThemeName } from '../engines/types';
import type { InteractionOptions } from '../plugins';
import type { NodeClickEvent } from '../plugins/types';
import type { AnimationController } from '../animation/controller';
import type { AnimationPluginOptions } from '../animation/plugin';

export type EngineName = 'auto' | 'mermaid' | 'plantuml';
export type SecurityLevel = 'strict' | 'loose' | 'antiscript' | 'sandbox';

export interface TopoDiagramSource {
  engine: EngineName;
  /** Raw code and schema sources are mutually exclusive. */
  code?: string;
  schema?: DiagramSchema;
}

export interface UseTopoDiagramOptions {
  /** Target element (template ref). Omit to use the returned `containerRef`. */
  container?: Ref<HTMLElement | null>;
  source: Ref<TopoDiagramSource> | TopoDiagramSource;
  theme?: Ref<ThemeName> | ThemeName;
  securityLevel?: SecurityLevel;
  themeVariables?: Record<string, string | number>;
  interactions?: InteractionOptions | false;
  /** Playback: autoPlay + optional custom steps (selectors) / plan factory. */
  animation?: AnimationPluginOptions;
  /** PlantUml engine only: rendering server base URL (default http://127.0.0.1:3491). */
  plantUmlBaseUrl?: string;
  onNodeClick?: (e: NodeClickEvent) => void;
  onReady?: (view: DiagramView) => void;
  onError?: (error: { engine: string; message: string }) => void;
  onWarning?: (warnings: DegradeWarning[]) => void;
}

export interface TopoDiagramApi {
  /** Element the diagram renders into (bind to a template ref). */
  containerRef: Ref<HTMLElement | null>;
  ready: Ref<boolean>;
  error: Ref<{ engine: string; message: string } | null>;
  warnings: Ref<DegradeWarning[]>;
  getAnimation(): AnimationController | null;
  getSvg(): SVGSVGElement | null;
  zoomToFit(): void;
  resetView(): void;
  zoomIn(): void;
  zoomOut(): void;
}

export function useTopoDiagram(opts: UseTopoDiagramOptions): TopoDiagramApi {
  const containerRef = opts.container ?? ref<HTMLElement | null>(null);
  const ready = ref(false);
  const error = ref<{ engine: string; message: string } | null>(null);
  const warnings = ref<DegradeWarning[]>([]);
  let view: DiagramView | null = null;

  const buildSource = () => {
    const src = toValue(opts.source);
    const hasCode = src.code !== undefined;
    const hasSchema = src.schema !== undefined;
    if (hasCode === hasSchema) {
      throw new Error("TopoDiagram: provide exactly one of 'code' / 'schema'");
    }
    return hasCode
      ? { engine: src.engine, code: src.code as string }
      : { engine: src.engine, schema: src.schema as DiagramSchema };
  };

  const destroy = () => {
    view?.destroy();
    view = null;
    ready.value = false;
  };

  const render = () => {
    if (!containerRef.value) return;
    destroy();
    error.value = null;
    warnings.value = [];
    view = createDiagram(containerRef.value, {
      source: buildSource(),
      theme: toValue(opts.theme),
      securityLevel: opts.securityLevel,
      themeVariables: opts.themeVariables,
      interactions: opts.interactions,
      animation: opts.animation,
      engineOptions: opts.plantUmlBaseUrl ? { baseUrl: opts.plantUmlBaseUrl } : undefined,
      onReady: (v) => {
        ready.value = true;
        opts.onReady?.(v);
      },
      onError: (e) => {
        error.value = e;
        opts.onError?.(e);
      },
      onWarning: (w) => {
        warnings.value = w;
        opts.onWarning?.(w);
      },
      onNodeClick: opts.onNodeClick,
    });
  };

  onMounted(render);
  watch(
    () => [toValue(opts.source), toValue(opts.theme)] as const,
    () => render(),
    { deep: true },
  );
  onBeforeUnmount(destroy);

  return {
    containerRef,
    ready,
    error,
    warnings,
    getAnimation: () => view?.getAnimation() ?? null,
    getSvg: () => view?.getSvg() ?? null,
    zoomToFit: () => view?.zoomToFit(),
    resetView: () => view?.resetView(),
    zoomIn: () => view?.zoomIn(),
    zoomOut: () => view?.zoomOut(),
  };
}
