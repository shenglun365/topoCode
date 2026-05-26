<script setup lang="ts">
/**
 * 动画舞台 — TopoScript 动画播放器
 *
 * 接受 TopoScript 源码，编译并通过 AnimationEngine 渲染播放。
 * Props:
 *   - source: TopoScript 源码
 *   - renderer: 渲染器类型 (d3/pixi/auto)
 *   - autoPlay: 是否自动播放
 *   - showToolbar: 是否显示工具栏
 */

import { ref, watch, onMounted, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAnimation } from '@/composables/useAnimation'
import {
  PlayIcon,
  PauseIcon,
  StopIcon,
  ArrowPathIcon,
} from '@heroicons/vue/24/outline'
import { useComponentId } from '@/composables/useComponentId'
const { showId, componentId } = useComponentId('VZ-001')


const { t } = useI18n()

const props = withDefaults(defineProps<{
  source?: string
  renderer?: 'd3' | 'pixi' | 'auto'
  autoPlay?: boolean
  showToolbar?: boolean
  width?: number
  height?: number
}>(), {
  source: '',
  renderer: 'd3',
  autoPlay: false,
  showToolbar: true,
  width: 800,
  height: 600,
})

const stageRef = ref<HTMLElement | null>(null)

const {
  playing,
  currentStep,
  totalSteps,
  progress,
  error,
  load,
  play,
  pause,
  stop,
} = useAnimation({
  renderer: props.renderer,
  width: props.width,
  height: props.height,
  autoPlay: props.autoPlay,
})

let loaded = false

// ==================== 初始化引擎 ====================
async function init() {
  if (!stageRef.value || !props.source || loaded) return

  await nextTick()

  const success = load(stageRef.value, props.source)
  loaded = success

  if (success && props.autoPlay) {
    play()
  }
}

// ==================== 进度条跳转 ====================
function onProgressClick(e: MouseEvent) {
  if (!totalSteps.value) return
  const rect = (e.target as HTMLElement).getBoundingClientRect()
  const ratio = (e.clientX - rect.left) / rect.width
  const step = Math.floor(ratio * (totalSteps.value - 1))
  const seek = (stageRef.value as any)?._seek
  if (seek) seek(step)
}

// ==================== 监听 source 变化 ====================
watch(() => props.source, () => {
  loaded = false
  stop()
  init()
})

onMounted(() => {
  init()
})

defineExpose({ play, pause, stop })
</script>

<template>
  <div class="animation-stage">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 工具栏 -->
    <div
      v-if="showToolbar"
      class="stage-toolbar"
    >
      <div class="toolbar-left">
        <span class="toolbar-label">{{ t('animation.animationStage') }}</span>
        <span
          v-if="playing"
          class="toolbar-status"
        >
          {{ t('animation.animationPlaying') }} {{ currentStep + 1 }}/{{ totalSteps }}
        </span>
        <span
          v-else-if="totalSteps > 0 && !playing"
          class="toolbar-status"
        >
          {{ t('animation.animationPaused') }}
        </span>
        <span
          v-else-if="error"
          class="toolbar-status error"
        >{{ error }}</span>
        <span
          v-else
          class="toolbar-status"
        >{{ t('animation.animationWaiting') }}</span>
      </div>

      <div class="toolbar-right">
        <button
          v-if="!playing"
          class="btn btn-ghost btn-sm"
          :disabled="!loaded"
          :title="t('animation.play')"
          @click="play"
        >
          <PlayIcon class="w-4 h-4" />
        </button>
        <button
          v-else
          class="btn btn-ghost btn-sm"
          :title="t('animation.pause')"
          @click="pause"
        >
          <PauseIcon class="w-4 h-4" />
        </button>

        <button
          class="btn btn-ghost btn-sm"
          :disabled="!loaded"
          :title="t('animation.stop')"
          @click="stop"
        >
          <StopIcon class="w-4 h-4" />
        </button>

        <button
          class="btn btn-ghost btn-sm"
          :disabled="!loaded"
          :title="t('animation.replay')"
          @click="() => { stop(); play() }"
        >
          <ArrowPathIcon class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- 进度条 -->
    <div
      v-if="totalSteps > 0"
      class="progress-track"
      @click="onProgressClick"
    >
      <div
        class="progress-fill"
        :style="{ width: `${progress}%` }"
      />
    </div>

    <!-- 动画舞台 (发动机渲染区域) -->
    <div
      ref="stageRef"
      class="stage-content"
    >
      <!-- 空状态 -->
      <div
        v-if="!source || !loaded"
        class="empty-state"
      >
        <div class="title">
          {{ t('animation.animationStage') }}
        </div>
        <div
          v-if="!source"
          class="desc"
        >
          {{ t('animation.sequenceHint') }}
        </div>
        <div
          v-else-if="error"
          class="desc error"
        >
          {{ error }}
        </div>
        <div
          v-if="!source"
          class="hint"
        >
          {{ t('animation.supportedEffects') }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.animation-stage {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-primary);
}

.stage-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-secondary);
  min-height: 40px;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.toolbar-status {
  font-size: 11px;
  color: var(--text-muted);
}

.toolbar-status.error {
  color: var(--danger);
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.progress-track {
  height: 4px;
  background: var(--bg-hover);
  cursor: pointer;
  position: relative;
}

.progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.1s;
}

.stage-content {
  flex: 1;
  overflow: hidden;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
}

.empty-state {
  text-align: center;
  color: var(--text-muted);
}

.empty-state .title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.empty-state .desc {
  font-size: 12px;
  margin-bottom: 8px;
}

.empty-state .desc.error {
  color: var(--danger);
}

.empty-state .hint {
  font-size: 11px;
  opacity: 0.6;
}
</style>
