/** 自定义动画系统 Composable - 预留接口，后续细化设计 */

import { ref, type Ref, onUnmounted } from 'vue'

export interface AnimationStep {
  id: string
  type: 'fade' | 'slide' | 'scale' | 'morph' | 'flow' | 'custom'
  target: string // CSS selector 或元素 ID
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

export function useAnimation() {
  const playing = ref(false)
  const currentStep = ref(0)
  const totalSteps = ref(0)
  const progress = ref(0)
  const error = ref<string | null>(null)
  const sequences = new Map<string, AnimationSequence>()
  let currentSequence: AnimationSequence | null = null
  let rafId: number | null = null
  let startTime = 0

  /** 注册动画序列 */
  function registerSequence(seq: AnimationSequence): void {
    sequences.set(seq.id, seq)
  }

  /** 播放动画序列 */
  function play(sequenceId: string): void {
    const seq = sequences.get(sequenceId)
    if (!seq) {
      error.value = `Animation sequence not found: ${sequenceId}`
      return
    }

    currentSequence = seq
    totalSteps.value = seq.steps.length
    currentStep.value = 0
    playing.value = true
    progress.value = 0

    // TODO: 后续实现具体的动画播放逻辑
    // - Web Animations API
    // - CSS animation 动态注入
    // - requestAnimationFrame 驱动
  }

  /** 暂停 */
  function pause(): void {
    playing.value = false
    if (rafId) {
      cancelAnimationFrame(rafId)
      rafId = null
    }
  }

  /** 恢复 */
  function resume(): void {
    if (!currentSequence) return
    playing.value = true
    // TODO: 恢复动画
  }

  /** 停止 */
  function stop(): void {
    playing.value = false
    currentStep.value = 0
    progress.value = 0
    currentSequence = null
    if (rafId) {
      cancelAnimationFrame(rafId)
      rafId = null
    }
  }

  /** 跳转到指定步骤 */
  function seekTo(step: number): void {
    if (!currentSequence) return
    currentStep.value = Math.max(0, Math.min(step, currentSequence?.steps.length || 0 - 1))
    // TODO: 跳转到指定步骤
  }

  /** 移除动画序列 */
  function unregisterSequence(id: string): void {
    sequences.delete(id)
  }

  /** 获取已注册的序列 */
  function getSequences(): AnimationSequence[] {
    return Array.from(sequences.values())
  }

  onUnmounted(() => {
    stop()
    sequences.clear()
  })

  return {
    playing,
    currentStep,
    totalSteps,
    progress,
    error,
    registerSequence,
    unregisterSequence,
    getSequences,
    play,
    pause,
    resume,
    stop,
    seekTo,
  }
}
