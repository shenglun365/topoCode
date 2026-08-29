<script setup lang="ts">
import { computed, ref } from 'vue';
import type { AnimationPlan } from '../animation';
import type { DiagramView } from '../core/DiagramView';
import type { DiagramSchema } from '../core/types';
import type { DegradeWarning } from '../engines/types';
import type { NodeClickEvent } from '../plugins/types';
import { useTopoDiagram, type EngineName, type SecurityLevel, type TopoDiagramApi } from './useTopoDiagram';

const props = withDefaults(
  defineProps<{
    /** Raw diagram code (mermaid or plantuml) — mutually exclusive with `schema`. */
    code?: string;
    /** Unified DiagramSchema — mutually exclusive with `code`. */
    schema?: DiagramSchema;
    /** 'auto' negotiates the engine from the schema type (schema source only). */
    engine?: EngineName;
    theme?: 'light' | 'dark';
    /** Auto-start animation playback for supported diagram types. */
    autoPlay?: boolean;
    /** Mermaid click-handler security level (main project convention: 'loose'). */
    securityLevel?: SecurityLevel;
    /** Mermaid theme variable overrides (e.g. catppuccinDark from ./themes). */
    themeVariables?: Record<string, string | number>;
    /** false disables the interaction plugins (zoom-pan / node-click / export). */
    interactions?: boolean;
    /** Custom playback: steps (CSS selectors per step) and/or a plan factory. */
    animation?: {
      steps?: { label: string; selectors: string[] }[];
      plan?: (ctx: { svg: SVGSVGElement; code: string; engine: string; type: string }) => AnimationPlan | null;
      mode?: 'reveal' | 'highlight';
      stepMs?: number;
    };
    /** PlantUml engine only: rendering server base URL. */
    plantUmlBaseUrl?: string;
  }>(),
  { engine: 'auto', theme: 'dark', autoPlay: false, interactions: true },
);

const emit = defineEmits<{
  ready: [view: DiagramView];
  error: [payload: { engine: string; message: string }];
  warning: [warnings: DegradeWarning[]];
  'node-click': [event: NodeClickEvent];
}>();

const canvasRef = ref<HTMLElement | null>(null);

const api = useTopoDiagram({
  container: canvasRef,
  source: computed(() => {
    if (props.code !== undefined) return { engine: props.engine, code: props.code };
    if (props.schema !== undefined) return { engine: props.engine, schema: props.schema };
    throw new Error("TopoDiagram: provide either the 'code' or the 'schema' prop");
  }),
  theme: computed(() => props.theme),
  securityLevel: props.securityLevel,
  themeVariables: props.themeVariables,
  interactions: props.interactions ? undefined : false,
  animation:
    props.autoPlay || props.animation
      ? { enabled: true, autoPlay: props.autoPlay, ...props.animation }
      : false, // 显式禁用动画插件；undefined 会被当作"启用默认"→ 停在第 0 步
  plantUmlBaseUrl: props.plantUmlBaseUrl,
  onNodeClick: (e) => emit('node-click', e),
  onReady: (view) => emit('ready', view),
  onError: (e) => emit('error', e),
  onWarning: (w) => emit('warning', w),
});

defineExpose<TopoDiagramApi>(api);
</script>

<template>
  <div class="topo-diagram">
    <div ref="canvasRef" class="topo-diagram__canvas" />
  </div>
</template>

<style scoped>
.topo-diagram {
  position: relative;
  width: 100%;
  overflow: hidden;
  border-radius: 8px;
}
.topo-diagram__canvas {
  width: 100%;
  /* 父级有确定高度时充满可视区；父级高度 auto(如聊天气泡)时百分比退化为 auto，按内容高。 */
  height: 100%;
  min-height: 120px;
}
.topo-diagram__canvas svg {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 0 auto;
}
</style>
