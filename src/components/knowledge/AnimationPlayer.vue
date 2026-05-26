<script setup lang="ts">
/**
 * 动画播放器 — 步骤同步 + 代码高亮
 *
 * 与 AnimationStage 配合使用，提供源码对照的步骤播放。
 * 当 AnimationStage 播放动画时，此组件同步高亮当前步骤对应的代码行。
 *
 * Props:
 *   - source: TopoScript 源码
 *   - steps: 编译后的步骤信息 (可选，用于描述文本)
 */

import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { compile } from '@topo-animation'
import {
  PlayIcon,
  PauseIcon,
  ForwardIcon,
  BackwardIcon,
  CodeBracketIcon,
  ChartBarIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
const { showId, componentId } = useComponentId('KN-006')


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
  source?: string
  speed?: number
  /** 从 AnimationStage 同步的播放状态 */
  currentStep?: number
  totalSteps?: number
  playing?: boolean
}>()

const emit = defineEmits<{
  'speed-change': [speed: number]
  'seek': [step: number]
  'play-step': [stepIndex: number]
}>()

const localSpeed = ref(props.speed || 1)

// 编译源码获取步骤信息
const compileInfo = computed(() => {
  if (!props.source) return null
  const result = compile(props.source)
  if (!result.success) return null
  return result
})

// 从源码中按行拆分，建立行号索引
const codeLines = computed(() => {
  if (!props.source) return []
  return props.source.split('\n')
})

// 估算当前步骤对应的行号 (按步骤比例)
const highlightLine = computed(() => {
  if (!props.totalSteps || !props.currentStep) return -1
  if (!props.source || !compileInfo.value?.stats) return -1

  // 简单映射：按步骤比例映射到行
  const ratio = props.currentStep / props.totalSteps
  return Math.floor(ratio * codeLines.value.length)
})

// 当前步骤的描述
const stepDescription = computed(() => {
  if (props.currentStep === 0) return t('animation.animationPlaying')
  if (props.totalSteps === 0) return t('animation.noStep')
  return `${t('animation.currentStep')}: ${props.currentStep} / ${props.totalSteps}`
})

const stepVars = computed<Record<string, string>>(() => {
  return {
    [t('animation.currentStep')]: String(props.currentStep || 0),
    [t('animation.progress')]: `${props.progress || 0}%`,
  }
})

const progress = computed(() => {
  if (!props.totalSteps || props.totalSteps === 0) return 0
  return Math.round((props.currentStep! / props.totalSteps) * 100)
})

function changeSpeed() {
  emit('speed-change', localSpeed.value)
}

function stepForward() {
  const next = (props.currentStep || 0) + 1
  if (props.totalSteps && next < props.totalSteps) {
    emit('seek', next)
    emit('play-step', next)
  }
}

function stepBackward() {
  const prev = Math.max(0, (props.currentStep || 0) - 1)
  emit('seek', prev)
  emit('play-step', prev)
}
</script>

<template>
  <div class="animation-player">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 控制栏 -->
    <div class="player-controls">
      <div class="control-buttons">
        <button
          class="control-btn"
          :title="t('animation.step') + ' ←'"
          @click="stepBackward"
        >
          <BackwardIcon class="w-5 h-5" />
        </button>
        <button
          class="control-btn"
          :title="t('animation.step') + ' →'"
          @click="stepForward"
        >
          <ForwardIcon class="w-5 h-5" />
        </button>
      </div>

      <div class="progress-area">
        <div class="progress-bar">
          <div
            class="progress-fill"
            :style="{ width: `${progress}%` }"
          />
        </div>
        <span class="progress-text">{{ progress }}%</span>
      </div>

      <div class="speed-control">
        <select
          v-model="localSpeed"
          class="speed-select"
          @change="changeSpeed"
        >
          <option :value="0.5">
            0.5x
          </option>
          <option :value="1">
            1x
          </option>
          <option :value="1.5">
            1.5x
          </option>
          <option :value="2">
            2x
          </option>
        </select>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="player-content">
      <!-- 代码区 -->
      <div class="code-area">
        <div class="code-header">
          <CodeBracketIcon class="w-4 h-4" />
          <span class="code-title">{{ t('animation.code') }}</span>
        </div>
        <div class="code-container">
          <pre class="code-block"><code>{{ source || '// ' + t('animation.noCode') }}</code></pre>
          <div
            v-if="highlightLine >= 0 && playing"
            class="code-highlight"
            :style="{ top: `${highlightLine * 24}px` }"
          />
        </div>
      </div>

      <!-- 可视化区 -->
      <div class="visualization-area">
        <div class="viz-header">
          <ChartBarIcon class="w-4 h-4" />
          <span class="viz-title">{{ t('animation.visualization') }}</span>
        </div>
        <div class="viz-container">
          <div class="step-info">
            <p class="step-description">
              {{ stepDescription }}
            </p>
            <div class="state-vars">
              <span
                v-for="(value, key) in stepVars"
                :key="key"
                class="var-chip"
              >
                {{ key }}={{ value }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 步骤指示器 -->
    <div class="step-indicator">
      <span class="step-label">{{ t('animation.currentStep') }}:</span>
      <span class="step-number">
        {{ currentStep || 0 }} / {{ totalSteps || 0 }}
      </span>
      <span
        v-if="playing"
        class="step-status playing"
      >▶ {{ t('animation.animationPlaying') }}</span>
      <span
        v-else
        class="step-status"
      >{{ t('animation.animationStopped') }}</span>
    </div>
  </div>
</template>

<style scoped>
.animation-player {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-secondary);
}

.player-controls {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-tertiary);
}

.control-buttons {
  display: flex;
  gap: 4px;
}

.control-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius-sm);
  background: var(--bg-secondary);
  color: var(--text-secondary);
  border: none;
  cursor: pointer;
  transition: all 0.15s;
}

.control-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.progress-area {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
}

.progress-bar {
  flex: 1;
  height: 4px;
  border-radius: 2px;
  background: var(--bg-secondary);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.3s ease;
}

.progress-text {
  font-size: 11px;
  color: var(--text-muted);
  min-width: 36px;
  text-align: right;
}

.speed-select {
  padding: 2px 6px;
  font-size: 11px;
  border-radius: var(--radius-sm);
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  color: var(--text-secondary);
  outline: none;
}

.speed-select:focus {
  border-color: var(--accent);
}

.player-content {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.code-area {
  display: flex;
  flex-direction: column;
  width: 50%;
  border-right: 1px solid var(--border);
}

.code-header,
.viz-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border);
}

.code-title,
.viz-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-primary);
}

.code-container {
  flex: 1;
  overflow-y: auto;
  position: relative;
}

.code-block {
  padding: 12px;
  margin: 0;
  font-size: 12px;
  font-family: 'Fira Code', 'Cascadia Code', 'JetBrains Mono', monospace;
  color: var(--text-secondary);
  background: transparent;
  line-height: 24px;
  white-space: pre;
}

.code-highlight {
  position: absolute;
  left: 0;
  right: 0;
  height: 24px;
  background: var(--accent);
  opacity: 0.12;
  pointer-events: none;
  transition: top 0.2s ease;
}

.visualization-area {
  display: flex;
  flex-direction: column;
  width: 50%;
}

.viz-container {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.step-info {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.step-description {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
}

.state-vars {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.var-chip {
  padding: 2px 8px;
  font-size: 11px;
  font-family: 'Fira Code', 'Cascadia Code', 'JetBrains Mono', monospace;
  border-radius: var(--radius-sm);
  background: var(--bg-tertiary);
  color: var(--accent);
  border: 1px solid var(--accent);
  opacity: 0.8;
}

.step-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-top: 1px solid var(--border);
  background: var(--bg-tertiary);
}

.step-label {
  font-size: 11px;
  color: var(--text-muted);
}

.step-number {
  font-size: 11px;
  color: var(--text-secondary);
  font-family: 'Fira Code', 'Cascadia Code', 'JetBrains Mono', monospace;
}

.step-status {
  font-size: 11px;
  color: var(--text-muted);
  margin-left: auto;
}

.step-status.playing {
  color: var(--accent);
}
</style>
