<script setup lang="ts">
/**
 * TopoStory —— 统一图 JSON 动画播放组件（公共能力，各模块可用）
 *
 * 机制：canonical 全量结构一次布局(elk) → 单 svg 常驻 → 帧推进 = 存在性 class 切换：
 *   新增元素淡入 / 消失元素淡出 / modified 脉冲高亮 —— 不变元素像素级静止，
 *   视角恒定(fit 一次全程有效)，无帧重挂/无鬼影。
 * 输入 graph: { canonical: {nodes,edges,containers}, frames: [{id,nodes,edges,modified}] }。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useGraphStory } from '../story/useTopoStory';
import { sceneToSvg } from '@topo/engine';
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
  }>(),
  { direction: 'LR', autoPlay: true, stepMs: 1600, theme: 'dark' },
);

const emit = defineEmits<{
  ready: [info: { frameIds: string[] }];
  'frame-change': [f: { index: number; id: string; label: string }];
  error: [e: { message: string }];
}>();

const canvasRef = ref<HTMLElement | null>(null);
/** 稳定视角层: 单 svg 常驻于此; pan/zoom transform 挂 stage, 与帧内容生命周期解耦 */
const stageRef = ref<HTMLElement | null>(null);

// ── pan/zoom ──
const scale = ref(1);
const tx = ref(0);
const ty = ref(0);

function applyT(): void {
  const stage = stageRef.value;
  if (!stage) return;
  stage.style.transformOrigin = '0 0';
  stage.style.transform = `translate(${tx.value}px, ${ty.value}px) scale(${scale.value})`;
}

function onWheel(e: WheelEvent): void {
  e.preventDefault();
  const host = canvasRef.value;
  if (!host) return;
  const rect = host.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const k = e.deltaY < 0 ? 1.15 : 1 / 1.15;
  const ns = Math.min(8, Math.max(0.3, scale.value * k));
  const kk = ns / scale.value;
  tx.value = mx - (mx - tx.value) * kk;
  ty.value = my - (my - ty.value) * kk;
  scale.value = ns;
  applyT();
}

let drag: { x: number; y: number; tx: number; ty: number } | null = null;
function onDown(e: MouseEvent): void {
  if (e.button !== 0) return;
  drag = { x: e.clientX, y: e.clientY, tx: tx.value, ty: ty.value };
  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', onUp, { once: true });
}
function onMove(e: MouseEvent): void {
  if (!drag) return;
  tx.value = drag.tx + (e.clientX - drag.x);
  ty.value = drag.ty + (e.clientY - drag.y);
  applyT();
}
function onUp(): void {
  drag = null;
  window.removeEventListener('mousemove', onMove);
}

let fitted = false;
/** fit: 单 svg 常驻 + 布局不变 ⇒ 只需一次(首次就绪/resize/双击/⌂) */
function fitContent(): void {
  const host = canvasRef.value;
  const svg = stageRef.value?.querySelector('svg');
  const g = svg?.querySelector('g');
  if (!host || !svg || !g) return;
  try {
    const b = g.getBBox();
    const hw = host.clientWidth, hh = host.clientHeight;
    if (!b.width || !b.height || !hw || !hh) return;
    const vb = (svg.getAttribute('viewBox') ?? '0 0 0 0').split(/[\s,]+/).map(Number);
    // svg CSS width:100% ⇒ 每用户单位像素 = hw/vbW; 不得用 getBoundingClientRect(transform 污染)
    const k0 = hw / (vb[2] || 1);
    const fit = Math.min(hw / (b.width * k0), hh / (b.height * k0), 2.5);
    scale.value = Math.max(0.05, fitted ? Math.min(scale.value, fit) : fit);
    fitted = true;
    const cx = (b.x + b.width / 2 - (vb[0] || 0)) * k0;
    const cy = (b.y + b.height / 2 - (vb[1] || 0)) * k0;
    tx.value = hw / 2 - cx * scale.value;
    ty.value = hh / 2 - cy * scale.value;
    applyT();
  } catch { /* 未就绪: resize 重试 */ }
}
function resetView(): void {
  fitted = false;
  fitContent();
}
function onResize(): void {
  if (fitted) fitContent();
}

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
    mountScene();
    emit('ready', i);
  },
});

function mountScene(): void {
  const sc = api.scene.value;
  const stage = stageRef.value;
  if (!sc || !stage) return;
  const svg = sceneToSvg(sc.spec);
  svg.classList.add('topo-story__graph');
  while (stage.firstChild) stage.removeChild(stage.firstChild);
  stage.appendChild(svg);
  applyFrame();
  requestAnimationFrame(() => fitContent());
}

/** 帧存在性 → 元素显隐/高亮（CSS 过渡: 淡入淡出自动发生） */
function applyFrame(): void {
  const svg = stageRef.value?.querySelector('svg');
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

onMounted(() => {
  window.addEventListener('resize', onResize);
  document.addEventListener('fullscreenchange', onResize);
});
onUnmounted(() => {
  api.dispose();
  window.removeEventListener('resize', onResize);
  document.removeEventListener('fullscreenchange', onResize);
});

defineExpose({ fitView: () => resetView(), api });

const frameCount = computed(() => api.state.frameCount);
const labelOf = computed(() => api.current.value?.label ?? '');
</script>

<template>
  <div class="topo-story">
    <div
      ref="canvasRef"
      class="topo-story__canvas"
      @wheel="onWheel"
      @mousedown="onDown"
      @dblclick="resetView"
    >
      <div ref="stageRef" class="topo-story__stage" />
    </div>
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
      <span v-if="scale !== 1" class="ts-progress ts-zoom">
        {{ Math.round(scale * 100) }}%
        <button class="ts-btn" title="重置视图" @click="resetView">⌂</button>
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
  height: min(62vh, 680px);
  overflow: hidden;
  cursor: grab;
}
.topo-story__canvas:active {
  cursor: grabbing;
}
.topo-story__stage {
  position: relative;
  width: 100%;
  height: 100%;
}
/* 单 svg 常驻: 原始尺寸渲染, 由 fit 统一缩放 */
.topo-story__stage :deep(svg) {
  position: absolute;
  left: 0;
  top: 0;
  max-width: none;
  background: transparent;
  display: block;
}
/* 存在性投影: 淡入淡出过渡(ev-off 隐藏/显现自动过渡); ev-snap=进入起点(无过渡瞬移) */
.topo-story__stage :deep(g[data-ta-key]) {
  transition: opacity 0.45s ease;
}
.topo-story__stage :deep(g[data-ta-key].ev-off) {
  opacity: 0;
  pointer-events: none;
}
.topo-story__stage :deep(g[data-ta-key].ev-snap) {
  transition: none;
  opacity: 0;
}
/* modified: 呼吸辉光 */
.topo-story__stage :deep(g[data-ta-key].ev-mod) {
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
.ts-progress { color: var(--ctp-overlay0, #6c7086); }
</style>
