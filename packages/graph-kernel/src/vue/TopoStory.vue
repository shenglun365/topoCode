<script setup lang="ts">
/**
 * TopoStory —— 帧序列叙事动画组件（与 TopoDiagram 平级）：
 * 输入 script/sources/frames 三形态之一，帧间 diff 补间播放 + 控制条 + 渲染进度。
 * 逻辑层见 ../story/useTopoStory。
 */
import { computed, ref } from 'vue';
import { useTopoStory, type TopoStorySource } from '../story/useTopoStory';
import type { StoryEngineName } from '../story/useTopoStory';

const props = withDefaults(
  defineProps<{
    /** TopoScript v2 全文（与 sources/frames 互斥，优先级最高） */
    script?: string;
    /** 每帧源文数组（前端流式渲染） */
    sources?: string[];
    /** 服务端已渲染 SVG 数组 */
    frames?: string[];
    /** 帧 id（如 commit short），缺省 f1..N */
    frameIds?: string[];
    /** 每帧注记（label 取 commit） */
    annotations?: (Record<string, string> | undefined)[];
    /** sources/frames 形态渲染后端（script 形态以 @backend 为准） */
    engine?: StoryEngineName;
    theme?: 'light' | 'dark';
    autoPlay?: boolean;
    /** plantuml CLI 端点 base（同源网关缺省） */
    plantUmlBaseUrl?: string;
    /** false 关闭帧渲染缓存（IndexedDB） */
    cache?: boolean;
    /** 帧驻留 ms（自动推进节奏；script 形态忽略，以文档 @options 为准） */
    stepMs?: number;
  }>(),
  { engine: 'mermaid', theme: 'dark', autoPlay: true, cache: true, stepMs: 1200 },
);

const emit = defineEmits<{
  ready: [info: { frameIds: string[]; edges: number }];
  progress: [p: { ready: number; total: number }];
  'frame-change': [f: { nodeId: string; index: number; label: string }];
  error: [e: { frame?: string; message: string }];
}>();

const canvasRef = ref<HTMLElement | null>(null);

const source = computed<TopoStorySource | null>(() => {
  const base = { frameIds: props.frameIds, annotations: props.annotations };
  if (props.script !== undefined) return { script: props.script, ...base };
  const options = { step: props.stepMs };
  if (props.sources !== undefined) return { sources: props.sources, options, ...base };
  if (props.frames !== undefined) return { frames: props.frames, options, ...base };
  return null;
});

const api = useTopoStory({
  container: canvasRef,
  source,
  engineName: props.engine,
  theme: computed(() => props.theme),
  autoPlay: computed(() => props.autoPlay),
  cache: props.cache,
  plantUmlBaseUrl: props.plantUmlBaseUrl,
  onReady: (i) => emit('ready', i),
  onProgress: (p) => emit('progress', p),
  onFrameChange: (f) => emit('frame-change', f),
  onError: (e) => emit('error', e),
});

defineExpose(api);

const frameCount = computed(() => api.frameIds.value.length);
</script>

<template>
  <div class="topo-story">
    <div ref="canvasRef" class="topo-story__canvas" />
    <div class="topo-story__bar">
      <button class="ts-btn" :title="api.state.paused ? '继续' : '暂停'" @click="api.togglePause()">
        {{ api.state.paused ? '▶' : '⏸' }}
      </button>
      <button class="ts-btn" title="停止" @click="api.stop()">⏹</button>
      <button class="ts-btn" title="上一帧" @click="api.prev()">⏮</button>
      <button class="ts-btn" title="下一帧" @click="api.next()">⏭</button>
      <span class="ts-pos">
        <template v-if="api.state.current">
          {{ api.state.current.index + 1 }}/{{ frameCount }} · {{ api.state.current.label }}
        </template>
        <template v-else>–</template>
      </span>
      <span v-if="api.state.progress.ready < api.state.progress.total" class="ts-progress">
        渲染 {{ api.state.progress.ready }}/{{ api.state.progress.total }}
      </span>
      <slot name="bar-extra" />
    </div>
  </div>
</template>

<style scoped>
.topo-story {
  position: relative;
  width: 100%;
  overflow: hidden;
  border-radius: 8px;
}
.topo-story__canvas {
  width: 100%;
  height: 100%;
  min-height: 120px;
}
.topo-story__canvas svg {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 0 auto;
}
.topo-story__bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  font-size: 12px;
}
.ts-btn {
  border: none;
  border-radius: 6px;
  background: var(--ctp-surface1, #45475a);
  color: var(--ctp-text, #cdd6f4);
  padding: 3px 8px;
  cursor: pointer;
  line-height: 1.2;
}
.ts-btn:hover { background: var(--ctp-surface2, #585b70); }
.ts-pos { color: var(--ctp-subtext0, #a6adc8); font-variant-numeric: tabular-nums; }
.ts-progress { color: var(--ctp-overlay0, #6c7086); }
</style>
