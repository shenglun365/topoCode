<script setup lang="ts">
/**
 * SceneCanvas —— 统一渲染内核的通用交互画布（批4-1）。
 *
 * 单 svg 常驻（engine sceneToSvg）+ pan/zoom + fit-once；节点/边点击事件委托
 * （data-ta-key 寻址）+ 高亮 API。TopoStory(播放) 与 资产图谱(静态/演化) 共用。
 */
import { onMounted, onUnmounted, ref, watch } from 'vue';
import { sceneToSvg } from '@topo/engine';
import type { SceneSpec } from '@topo/engine';

const props = withDefaults(
  defineProps<{
    /** 场景规格（graph-scene 布局产出）；null=空画布 */
    spec: SceneSpec | null;
    /** 画布高度（css 值） */
    height?: string;
    /** 点击交互开关（纯展示可关） */
    interactive?: boolean;
  }>(),
  { height: 'min(62vh, 680px)', interactive: true },
);

const emit = defineEmits<{
  'node-click': [key: string];
  'edge-click': [key: string];
  'bg-click': [];
  'spec-mounted': [svg: SVGSVGElement];
}>();

const canvasRef = ref<HTMLElement | null>(null);
const stageRef = ref<HTMLElement | null>(null);

// ── pan/zoom（TopoStory 同款：transform 挂 stage，与内容生命周期解耦） ──
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

let drag: { x: number; y: number; tx: number; ty: number; moved: boolean } | null = null;
function onDown(e: MouseEvent): void {
  if (e.button !== 0) return;
  drag = { x: e.clientX, y: e.clientY, tx: tx.value, ty: ty.value, moved: false };
  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', onUp, { once: true });
}
function onMove(e: MouseEvent): void {
  if (!drag) return;
  const dx = e.clientX - drag.x;
  const dy = e.clientY - drag.y;
  if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
  tx.value = drag.tx + dx;
  ty.value = drag.ty + dy;
  applyT();
}
function onUp(): void {
  drag = null;
  window.removeEventListener('mousemove', onMove);
}

let fitted = false;
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

// ── 挂载/重挂（spec 变更 = 新布局 → 重挂 + fit-once 语义重置） ──
function mountScene(): void {
  const spec = props.spec;
  const stage = stageRef.value;
  if (!stage) return;
  while (stage.firstChild) stage.removeChild(stage.firstChild);
  if (!spec) return;
  const svg = sceneToSvg(spec);
  svg.classList.add('scene-canvas__graph');
  stage.appendChild(svg);
  fitted = false;
  requestAnimationFrame(() => fitContent());
  emit('spec-mounted', svg);
}

watch(() => props.spec, () => mountScene());

// ── 事件委托（data-ta-key 寻址；data-ta-kind 区分节点/边） ──
function onClick(e: MouseEvent): void {
  if (!props.interactive) return;
  if (drag?.moved) return;   // 拖拽结束的 mouseup 不算点击
  const target = (e.target as Element)?.closest?.('[data-ta-key]') as SVGElement | null;
  if (!target) {
    emit('bg-click');
    return;
  }
  const key = target.getAttribute('data-ta-key') || '';
  const kind = target.getAttribute('data-ta-kind') || 'node';
  if (kind === 'edge') emit('edge-click', key);
  else emit('node-click', key);
}

// ── 高亮 API ──
function highlight(keys: string[]): void {
  const svg = stageRef.value?.querySelector('svg');
  if (!svg) return;
  const set = new Set(keys);
  for (const el of svg.querySelectorAll('g[data-ta-key]')) {
    el.classList.toggle('sc-hl', set.has(el.getAttribute('data-ta-key') || ''));
  }
}
function clearHighlight(): void {
  stageRef.value?.querySelectorAll('g[data-ta-key].sc-hl')
    .forEach((el) => el.classList.remove('sc-hl'));
}

onMounted(() => {
  window.addEventListener('resize', onResize);
  document.addEventListener('fullscreenchange', onResize);
  mountScene();
});
onUnmounted(() => {
  window.removeEventListener('resize', onResize);
  document.removeEventListener('fullscreenchange', onResize);
});

defineExpose({
  fitView: () => resetView(),
  highlight,
  clearHighlight,
  getSvg: () => stageRef.value?.querySelector('svg') ?? null,
});
</script>

<template>
  <div
    ref="canvasRef"
    class="scene-canvas"
    :style="{ height }"
    @wheel="onWheel"
    @mousedown="onDown"
    @click="onClick"
    @dblclick="resetView"
  >
    <div ref="stageRef" class="scene-canvas__stage" />
  </div>
</template>

<style scoped>
.scene-canvas {
  position: relative;
  width: 100%;
  overflow: hidden;
  cursor: grab;
}
.scene-canvas:active { cursor: grabbing; }
.scene-canvas__stage {
  position: relative;
  width: 100%;
  height: 100%;
}
.scene-canvas__stage :deep(svg) {
  position: absolute;
  left: 0;
  top: 0;
  max-width: none;
  background: transparent;
  display: block;
}
.scene-canvas__stage :deep(g[data-ta-key]) {
  cursor: pointer;
}
/* 高亮(选中/聚焦) */
.scene-canvas__stage :deep(g[data-ta-key].sc-hl) > * {
  stroke: #f5c2e7 !important;
}
.scene-canvas__stage :deep(g[data-ta-key].sc-hl) {
  filter: drop-shadow(0 0 5px #f5c2e7);
}
</style>
