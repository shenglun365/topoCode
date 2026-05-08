<template>
  <div class="animation-player">
    <!-- 控制栏 -->
    <div class="player-controls">
      <div class="control-buttons">
        <button class="control-btn" :title="t('animation.play')" @click="play">
          <PlayIcon class="w-5 h-5" />
        </button>
        <button class="control-btn" :title="t('animation.pause')" @click="pause">
          <PauseIcon class="w-5 h-5" />
        </button>
        <button class="control-btn" :title="t('animation.step')" @click="step">
          <ForwardIcon class="w-5 h-5" />
        </button>
        <button class="control-btn" :title="t('animation.reset')" @click="reset">
          <BackwardIcon class="w-5 h-5" />
        </button>
      </div>

      <div class="progress-area">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: `${progress}%` }"></div>
        </div>
        <span class="progress-text">{{ progress }}%</span>
      </div>

      <div class="speed-control">
        <select v-model="localSpeed" class="speed-select" @change="changeSpeed">
          <option :value="0.5">0.5x</option>
          <option :value="1">1x</option>
          <option :value="1.5">1.5x</option>
          <option :value="2">2x</option>
        </select>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="player-content">
      <!-- 代码区 -->
      <div class="code-area">
        <div class="code-header">
          <CodeBracketIcon class="w-4 h-4" />
          <span class="code-title">{{ animation?.title || t('animation.code') }}</span>
        </div>
        <div class="code-container">
          <pre class="code-block"><code>{{ code }}</code></pre>
          <div
            v-if="currentStep !== null"
            class="code-highlight"
            :style="{ top: `${currentStep.line * 24}px` }"
          ></div>
        </div>
      </div>

      <!-- 可视化区 -->
      <div class="visualization-area">
        <div class="viz-header">
          <ChartBarIcon class="w-4 h-4" />
          <span class="viz-title">{{ t('animation.visualization') }}</span>
        </div>
        <div class="viz-container">
          <div v-if="currentStep" class="step-info">
            <p class="step-description">{{ currentStep.description }}</p>
            <div class="state-vars">
              <span v-for="(value, key) in currentStep.state" :key="key" class="var-chip">
                {{ key }}={{ value }}
              </span>
            </div>
          </div>
          <div v-else class="empty-viz">
            <p class="empty-text">{{ t('animation.noStep') }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- 步骤指示器 -->
    <div class="step-indicator">
      <span class="step-label">{{ t('animation.currentStep') }}:</span>
      <span class="step-number">{{ currentStep ? currentStep.id : '-' }} / {{ totalSteps }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PlayIcon,
  PauseIcon,
  ForwardIcon,
  BackwardIcon,
  CodeBracketIcon,
  ChartBarIcon,
} from '@heroicons/vue/24/outline'

const { t } = useI18n()

export interface AnimationStep {
  id: number
  line: number
  description: string
  state: Record<string, any>
  visualization?: string
}

export interface AnimationData {
  id: string
  title: string
  steps: AnimationStep[]
  code: string
}

const props = defineProps<{
  animation?: AnimationData
  speed: number
}>()

const emit = defineEmits<{
  play: []
  pause: []
  step: []
  reset: []
  'speed-change': [speed: number]
}>()

const localSpeed = ref(props.speed)
const currentStepIndex = ref(-1)
const isPlaying = ref(false)

const totalSteps = computed(() => {
  return props.animation?.steps.length || 0
})

const currentStep = computed(() => {
  if (currentStepIndex.value < 0 || !props.animation) return null
  return props.animation.steps[currentStepIndex.value]
})

const progress = computed(() => {
  if (totalSteps.value === 0) return 0
  return Math.round(((currentStepIndex.value + 1) / totalSteps.value) * 100)
})

const code = computed(() => {
  return props.animation?.code || '// ' + t('animation.noCode')
})

function play() {
  isPlaying.value = true
  emit('play')
}

function pause() {
  isPlaying.value = false
  emit('pause')
}

function step() {
  if (currentStepIndex.value < totalSteps.value - 1) {
    currentStepIndex.value++
  }
  emit('step')
}

function reset() {
  currentStepIndex.value = -1
  isPlaying.value = false
  emit('reset')
}

function changeSpeed() {
  emit('speed-change', localSpeed.value)
}
</script>

<style scoped lang="scss">
.animation-player {
  @apply flex flex-col h-full bg-[--bg-secondary];
}

.player-controls {
  @apply flex items-center gap-4 p-3 border-b border-[--border] bg-[--bg-tertiary];
}

.control-buttons {
  @apply flex gap-2;
}

.control-btn {
  @apply p-2 rounded bg-[--bg-secondary] text-[--text-secondary] hover:bg-[--bg-hover] hover:text-[--text-primary] transition-colors;
}

.progress-area {
  @apply flex items-center gap-2 flex-1;
}

.progress-bar {
  @apply flex-1 h-1 rounded-full bg-[--bg-secondary] overflow-hidden;
}

.progress-fill {
  @apply h-full bg-[--accent] transition-all duration-300;
}

.progress-text {
  @apply text-xs text-[--text-muted] min-w-[3ch];
}

.speed-control {
  @apply flex items-center;
}

.speed-select {
  @apply px-2 py-1 text-xs rounded bg-[--bg-secondary] border border-[--border] text-[--text-secondary] focus:outline-none;
}

.player-content {
  @apply flex flex-1 overflow-hidden;
}

.code-area {
  @apply flex flex-col w-1/2 border-r border-[--border];
}

.code-header {
  @apply flex items-center gap-2 p-2 bg-[--bg-tertiary];
}

.code-title {
  @apply text-xs font-medium text-[--text-primary];
}

.code-container {
  @apply flex-1 overflow-y-auto relative;
}

.code-block {
  @apply p-4 text-xs font-mono text-[--text-secondary] bg-transparent;
}

.code-highlight {
  @apply absolute left-0 right-0 h-6 bg-[--accent]/20 pointer-events-none transition-all duration-300;
}

.visualization-area {
  @apply flex flex-col w-1/2;
}

.viz-header {
  @apply flex items-center gap-2 p-2 bg-[--bg-tertiary];
}

.viz-title {
  @apply text-xs font-medium text-[--text-primary];
}

.viz-container {
  @apply flex-1 overflow-y-auto p-4;
}

.step-info {
  @apply flex flex-col gap-3;
}

.step-description {
  @apply text-sm text-[--text-secondary];
}

.state-vars {
  @apply flex flex-wrap gap-2;
}

.var-chip {
  @apply px-2 py-1 text-xs rounded bg-[--bg-tertiary] text-[--accent] border border-[--accent]/30;
}

.empty-viz {
  @apply flex items-center justify-center h-full;
}

.empty-text {
  @apply text-xs text-[--text-muted];
}

.step-indicator {
  @apply flex items-center gap-2 p-2 border-t border-[--border] bg-[--bg-tertiary];
}

.step-label {
  @apply text-xs text-[--text-muted];
}

.step-number {
  @apply text-xs text-[--text-secondary];
}
</style>
