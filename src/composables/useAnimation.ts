/**
 * useAnimation — TopoScript 动画引擎 Composable
 *
 * 对接 @topo-animation 的 AnimationEngine，提供响应式的播放状态。
 *
 * 基本用法：
 * ```ts
 * const { play, pause, stop, seek, load } = useAnimation()
 * load(container, topoScriptSource)
 * play()
 * ```
 */

import { ref, readonly, onUnmounted } from 'vue'
import { compile, createAnimationEngine } from '@topo-animation'
import type { AnimationState, CompileResult } from '@topo-animation'

export interface AnimationStep {
  id: string
  type: 'fade' | 'slide' | 'scale' | 'morph' | 'flow' | 'custom'
  target: string
  duration: number
  delay?: number
  easing?: string
  from?: Record<string, any>
  to?: Record<string, any>
}

export interface AnimationSequence {
  id: string
  name: string
  steps: AnimationStep[]
  loop?: boolean
  autoPlay?: boolean
}

export interface UseAnimationOptions {
  renderer?: 'd3' | 'pixi' | 'auto'
  width?: number
  height?: number
  autoPlay?: boolean
  zoom?: boolean
  layout?: 'force-directed' | 'hierarchy' | 'grid' | 'circular'
}

export type LayoutType = 'force-directed' | 'hierarchy' | 'grid' | 'circular'

export function useAnimation(options: UseAnimationOptions = {}) {
  // ==================== 响应式状态 ====================
  const playing = ref(false)
  const paused = ref(false)
  const currentStep = ref(0)
  const totalSteps = ref(0)
  const progress = ref(0)
  const error = ref<string | null>(null)
  const compileResult = ref<CompileResult | null>(null)

  // 交互事件回调
  const onNodeClick = ref<((nodeId: string) => void) | null>(null)
  const onNodeHover = ref<((nodeId: string | null) => void) | null>(null)
  const onEdgeClick = ref<((edgeId: string) => void) | null>(null)

  // ==================== 旧接口序列注册 ====================
  const sequences = new Map<string, AnimationSequence>()

  let engine: ReturnType<typeof createAnimationEngine> | null = null

  function registerSequence(seq: AnimationSequence): void {
    sequences.set(seq.id, seq)
  }

  function unregisterSequence(id: string): void {
    sequences.delete(id)
  }

  function getSequences(): AnimationSequence[] {
    return Array.from(sequences.values())
  }

  // ==================== 编译 ====================
  function compileSource(source: string): CompileResult {
    const result = compile(source)
    if (!result.success) {
      error.value = result.errors?.[0] || 'Compilation failed'
      console.error('[useAnimation] compileSource FAILED:', error.value, 'errors:', result.errors)
    } else {
      error.value = null
      compileResult.value = result
      totalSteps.value = result.stats?.steps || 0
    }
    return result
  }

  // ==================== 装载 ====================
  function load(container: HTMLElement, source: string): boolean {
    if (engine) {
      engine.destroy()
    }

    const merged = { ...options }
    const rendererType = merged.renderer || 'd3'

    engine = createAnimationEngine({
      container,
      renderer: rendererType,
      width: merged.width || container.clientWidth || 800,
      height: merged.height || container.clientHeight || 600,
      autoPlay: merged.autoPlay || false,
      zoom: merged.zoom !== false,
      layout: merged.layout || 'force-directed',
    })

    // 绑定事件
    engine.on('play', () => {
      playing.value = true
      paused.value = false
    })

    engine.on('pause', () => {
      playing.value = false
      paused.value = true
    })

    engine.on('stop', () => {
      playing.value = false
      paused.value = false
      currentStep.value = 0
      progress.value = 0
    })

    engine.on('complete', () => {
      playing.value = false
      paused.value = false
      progress.value = 100
    })

    engine.on('step-change', (data: { step: number; state: AnimationState }) => {
      currentStep.value = data.step
      progress.value = totalSteps.value > 0
        ? Math.round(((data.step + 1) / totalSteps.value) * 100)
        : 0
    })

    engine.on('error', (err: Error) => {
      error.value = err.message
      playing.value = false
    })

    // 节点/边交互事件
    engine.on('node-click', (data: { nodeId: string }) => {
      onNodeClick.value?.(data.nodeId)
    })
    engine.on('node-hover', (data: { nodeId: string | null }) => {
      onNodeHover.value?.(data.nodeId)
    })
    engine.on('edge-click', (data: { edgeId: string }) => {
      onEdgeClick.value?.(data.edgeId)
    })

    // 编译并加载
    const compileRes = compileSource(source)
    if (!compileRes.success) return false

    engine.load(source)
    return true
  }

  // ==================== 播放控制 ====================
  function play(): void {
    if (engine) {
      engine.play()
      return
    }

    error.value = 'No engine initialized. Call load() first.'
  }

  function pause(): void {
    engine?.pause()
  }

  function stop(): void {
    engine?.stop()
  }

  function seek(step: number): void {
    engine?.seek(step)
  }

  // ==================== 缩放 ====================
  function zoomToLevel(level: number): void {
    engine?.zoomToLevel(level)
  }

  function fitToScreen(padding?: number): void {
    engine?.fitToScreen(padding)
  }

  function resetZoom(): void {
    engine?.resetZoom()
  }

  // ==================== 布局切换 ====================
  function switchLayout(layout: LayoutType): void {
    engine?.switchLayout(layout)
  }

  // ==================== 导出 ====================
  function exportPNG(): string | null {
    if (!engine) return null
    // TODO: 接入 export exportImage
    return null
  }

  function exportSVG(): string | null {
    if (!engine) return null
    return null
  }

  // ==================== 清理 ====================
  function destroy(): void {
    stop()
    sequences.clear()
    compileResult.value = null

    if (engine) {
      engine.destroy()
      engine = null
    }
  }

  onUnmounted(() => {
    destroy()
  })

  return {
    // 状态（只读）
    playing: readonly(playing),
    paused: readonly(paused),
    currentStep: readonly(currentStep),
    totalSteps: readonly(totalSteps),
    progress: readonly(progress),
    error: readonly(error),
    compileResult: readonly(compileResult),

    // 编译
    compileSource,

    // 装载
    load,

    // 播放控制
    play,
    pause,
    stop,
    seek,

    // 缩放
    zoomToLevel,
    fitToScreen,
    resetZoom,

    // 布局切换
    switchLayout,

    // 交互事件
    onNodeClick,
    onNodeHover,
    onEdgeClick,

    // 旧接口兼容
    registerSequence,
    unregisterSequence,
    getSequences,

    // 导出
    exportPNG,
    exportSVG,

    // 生命周期
    destroy,
  }
}
