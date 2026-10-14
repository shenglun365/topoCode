<script setup lang="ts">
/**
 * 信息流 Diagram 卡片(当前对话消息流内嵌图)——静态渲染。
 * (方向裁决: architect 图以 GIT DIFF 静态变化图为目标, 动态效果另行迭代。)
 * 支持全屏(svg 拷贝 + 滚轮缩放/拖拽, 同 web-core DiagramViewer 方案)。
 */
import { computed, ref } from 'vue'
import TopoDiagram from '@topo/graph-kernel/vue/TopoDiagram.vue'
import { themeVariablesFor } from '@topo/graph-kernel/vue/themes.ts'

const props = defineProps<{ schema: any; title?: string }>()

const themeMode = computed<'dark' | 'light'>(() =>
  (typeof document !== 'undefined' && document.documentElement.getAttribute('data-theme') === 'light') ? 'light' : 'dark')
const themeVars = computed(() => themeVariablesFor(themeMode.value))

/** 全屏: 拷贝当前 svg 到 overlay, 滚轮缩放 + 拖拽平移。 */
const wrapRef = ref<HTMLElement | null>(null)

function openFullscreen() {
  const svg = wrapRef.value?.querySelector('svg')
  if (!svg) return
  const ov = document.createElement('div')
  ov.style.cssText = 'position:fixed;inset:0;z-index:9999;background:rgba(10,12,18,.96);display:flex;align-items:center;justify-content:center;'
  const fc = document.createElement('div')
  fc.innerHTML = svg.outerHTML
  const fsSvg = fc.querySelector('svg')
  if (fsSvg) { fsSvg.style.maxWidth = '92vw'; fsSvg.style.maxHeight = '92vh'; fsSvg.style.width = ''; fsSvg.style.height = '' }
  const closeBtn = document.createElement('button')
  closeBtn.textContent = '×'
  closeBtn.title = '关闭'
  closeBtn.style.cssText = 'position:absolute;top:12px;right:16px;width:36px;height:36px;font-size:22px;line-height:1;border:none;border-radius:8px;cursor:pointer;background:#1d2330;color:#e6e6e6;'
  ov.append(closeBtn, fc)
  document.body.appendChild(ov)
  let s = 1, dx = 0, dy = 0, drag = false, sx0 = 0, sy0 = 0, sdx = 0, sdy = 0
  const apply = () => { fc.style.transform = `translate(${dx}px,${dy}px) scale(${s})` }
  ov.addEventListener('wheel', (e) => {
    e.preventDefault()
    const old = s
    s = Math.max(0.25, Math.min(6, s + (e.deltaY > 0 ? -0.15 : 0.15)))
    const r = fc.getBoundingClientRect()
    dx += (e.clientX - r.left) * (1 - s / old)
    dy += (e.clientY - r.top) * (1 - s / old)
    apply()
  }, { passive: false })
  ov.addEventListener('mousedown', (e) => {
    drag = true; sx0 = e.clientX; sy0 = e.clientY; sdx = dx; sdy = dy
  })
  const mm = (e: MouseEvent) => { if (drag) { dx = sdx + e.clientX - sx0; dy = sdy + e.clientY - sy0; apply() } }
  const mu = () => { drag = false }
  window.addEventListener('mousemove', mm)
  window.addEventListener('mouseup', mu)
  const close = () => {
    window.removeEventListener('mousemove', mm)
    window.removeEventListener('mouseup', mu)
    ov.remove()
  }
  closeBtn.addEventListener('click', close)
  ov.addEventListener('keydown', (e) => { if ((e as KeyboardEvent).key === 'Escape') close() })
}
</script>

<template>
  <div class="my-1.5 border border-ctp-surface0 rounded-lg overflow-hidden bg-ctp-mantle/30">
    <div class="flex items-center gap-1.5 px-2 py-1 border-b border-ctp-surface0/80">
      <span class="text-[10px] font-mono text-ctp-subtext0">{{ props.title || 'diagram' }}</span>
      <span class="flex-1" />
      <button
        class="text-[10px] px-1.5 py-0.5 rounded text-ctp-subtext1 hover:text-ctp-text hover:bg-ctp-surface1"
        title="全屏查看(滚轮缩放/拖拽)"
        @click="openFullscreen"
      >⛶ 全屏</button>
    </div>
    <div ref="wrapRef" class="h-[360px]">
      <TopoDiagram
        class="!h-full"
        :schema="props.schema"
        engine="auto"
        :theme="themeMode"
        :theme-variables="themeVars"
        security-level="loose"
      />
    </div>
  </div>
</template>
