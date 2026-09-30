<script setup lang="ts">
/**
 * TopoStory —— 统一图 JSON 动画播放组件（公共能力，各模块可用）
 *
 * 机制：canonical 全量结构一次布局(elk) → 单 svg 常驻 → 帧推进 = 存在性 class 切换：
 *   新增元素淡入 / 消失元素淡出 / modified 脉冲高亮 —— 不变元素像素级静止，
 *   视角恒定(fit 一次全程有效)，无帧重挂/无鬼影。
 * 画布/交互复用 SceneCanvas(批4-1)；本组件只负责播放状态机与帧存在性投影。
 */
import { computed, onUnmounted, ref, watch } from 'vue';
import { useGraphStory } from '../story/useTopoStory';
import SceneCanvas from './SceneCanvas.vue';
import type { GraphFrameDataInput } from '@topo/engine';

const props = withDefaults(
  defineProps<{
    /** 统一图 JSON（canonical + 每帧存在性） */
    graph: GraphFrameDataInput;
    direction?: 'LR' | 'TB';
    autoPlay?: boolean;
    /** 帧驻留 ms（自动推进节奏） */
    stepMs?: number;
    theme?: 'light' | 'dark';
    /** 画布高度（透传 SceneCanvas） */
    height?: string;
  }>(),
  { direction: 'LR', autoPlay: true, stepMs: 1600, theme: 'dark', height: 'min(62vh, 680px)' },
);

const emit = defineEmits<{
  ready: [info: { frameIds: string[] }];
  'frame-change': [f: { index: number; id: string; label: string }];
  error: [e: { message: string }];
  'node-click': [key: string];
  'edge-click': [key: string];
}>();

const canvasRef = ref<InstanceType<typeof SceneCanvas> | null>(null);

// ── 帧存在性 → class 切换 ──
const api = useGraphStory({
  graph: computed(() => props.graph),
  direction: computed(() => props.direction),
  autoPlay: computed(() => props.autoPlay),
  stepMs: computed(() => props.stepMs),
  onFrameChange: (f) => {
    applyFrame();
    emit('frame-change', f);
  },
  onError: (e) => emit('error', e),
  onReady: (i) => {
    applyFrame();
    emit('ready', i);
  },
});

/** 帧存在性 → 元素显隐/高亮（CSS 过渡: 淡入淡出自动发生） */
function applyFrame(): void {
  const svg = canvasRef.value?.getSvg();
  const sc = api.scene.value;
  const f = api.current.value;
  if (!svg || !sc || !f) return;
  const prev = svg.getAttribute('data-frame');
  const prevSet = new Set<string>(prev ? prev.split(' ').filter(Boolean) : []);
  for (const el of sc.spec.elements) {
    const node = svg.querySelector(`[data-ta-key="${el.key}"]`) as SVGElement | null;
    if (!node) continue;
    const on = f.has.has(el.key);
    const was = prevSet.has(el.key);
    node.classList.toggle('ev-off', !on);
    // 进入动画: 本帧在场且上帧不在 → 淡入起点(下一 rAF 移除触发过渡)
    if (on && !was) {
      node.classList.add('ev-snap');
      requestAnimationFrame(() => requestAnimationFrame(() => node.classList.remove('ev-snap')));
    }
    node.classList.toggle('ev-mod', f.modified.has(el.key));
  }
  svg.setAttribute('data-frame', [...f.has].join(' '));
}

watch(() => api.scene.value, () => applyFrame());

onUnmounted(() => api.dispose());

defineExpose({ fitView: () => canvasRef.value?.fitView(), api });

const frameCount = computed(() => api.state.frameCount);
const labelOf = computed(() => api.current.value?.label ?? '');
</script>

<template>
  <div class="topo-story">
    <SceneCanvas
      ref="canvasRef"
      :spec="api.scene.value?.spec ?? null"
      :height="height"
      @spec-mounted="applyFrame"
      @node-click="(k) => emit('node-click', k)"
      @edge-click="(k) => emit('edge-click', k)"
    />
    <div class="topo-story__bar">
      <button class="ts-btn" :title="api.state.paused ? '继续' : '暂停'" @click="api.togglePause()">
        {{ api.state.paused ? '▶' : '⏸' }}
      </button>
      <button class="ts-btn" title="停止" @click="api.stop()">⏹</button>
      <button class="ts-btn" title="上一帧" @click="api.prev()">⏮</button>
      <button class="ts-btn" title="下一帧" @click="api.next()">⏭</button>
      <span class="ts-pos">
        <template v-if="api.state.ready">{{ api.state.index + 1 }}/{{ frameCount }} · {{ labelOf }}</template>
        <template v-else>–</template>
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
/* 存在性投影: 淡入淡出过渡(ev-off 隐藏/显现自动过渡); ev-snap=进入起点(无过渡瞬移) */
.topo-story :deep(g[data-ta-key]) {
  transition: opacity 0.45s ease;
}
.topo-story :deep(g[data-ta-key].ev-off) {
  opacity: 0;
  pointer-events: none;
}
.topo-story :deep(g[data-ta-key].ev-snap) {
  transition: none;
  opacity: 0;
}
/* modified: 呼吸辉光 */
.topo-story :deep(g[data-ta-key].ev-mod) {
  animation: ev-pulse 1.6s ease-in-out infinite;
}
@keyframes ev-pulse {
  0%, 100% { filter: none; }
  50% { filter: drop-shadow(0 0 6px #a6e3a1); }
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
</style>
