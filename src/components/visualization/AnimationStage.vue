<script setup lang="ts">
/** 动画舞台 - 预留接口，后续细化设计 */

import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAnimation, type AnimationSequence } from '@/composables/useAnimation'
import {
  PlayIcon,
  PauseIcon,
  StopIcon,
  ArrowPathIcon,
} from '@heroicons/vue/24/outline'

const { t } = useI18n()

const props = withDefaults(defineProps<{
  sequenceId?: string
  autoPlay?: boolean
  showToolbar?: boolean
}>(), {
  sequenceId: '',
  autoPlay: false,
  showToolbar: true,
})

const stageRef = ref<HTMLElement | null>(null)
const {
  playing,
  currentStep,
  totalSteps,
  progress,
  error,
  play,
  pause,
  resume,
  stop,
  seekTo,
} = useAnimation()

// 进度条点击跳转
function onProgressClick(e: MouseEvent) {
  if (!stageRef.value || !totalSteps.value) return
  const rect = (e.target as HTMLElement).getBoundingClientRect()
  const ratio = (e.clientX - rect.left) / rect.width
  seekTo(Math.floor(ratio * totalSteps.value))
}

onMounted(() => {
  if (props.autoPlay && props.sequenceId) {
    play(props.sequenceId)
  }
})

defineExpose({ play, pause, resume, stop, seekTo })
</script>

<template>
  <div class="animation-stage">
    <!-- 工具栏 -->
    <div v-if="showToolbar" class="stage-toolbar">
      <div class="toolbar-left">
        <span class="toolbar-label">{{ t('animation.animationStage') }}</span>
        <span v-if="playing" class="toolbar-status">
          {{ t('animation.animationPlaying') }} {{ currentStep + 1 }}/{{ totalSteps }}
        </span>
        <span v-else-if="totalSteps > 0" class="toolbar-status">{{ t('animation.animationPaused') }}</span>
        <span v-else class="toolbar-status">{{ t('animation.animationWaiting') }}</span>
        <span v-if="error" class="toolbar-status error">{{ error }}</span>
      </div>

      <div class="toolbar-right">
        <button v-if="!playing" class="btn btn-ghost btn-sm" @click="play(sequenceId || '')" :title="t('animation.play')">
          <PlayIcon class="w-4 h-4" />
        </button>
        <button v-else class="btn btn-ghost btn-sm" @click="pause" :title="t('animation.pause')">
          <PauseIcon class="w-4 h-4" />
        </button>

        <button class="btn btn-ghost btn-sm" @click="stop" :title="t('animation.stop')">
          <StopIcon class="w-4 h-4" />
        </button>

        <button class="btn btn-ghost btn-sm" @click="play(sequenceId || '')" :title="t('animation.replay')">
          <ArrowPathIcon class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- 进度条 -->
    <div v-if="totalSteps > 0" class="progress-track" @click="onProgressClick">
      <div class="progress-fill" :style="{ width: `${(progress || 0)}%` }"></div>
    </div>

    <!-- 动画舞台 -->
    <div ref="stageRef" class="stage-content">
      <slot>
        <!-- 空状态 -->
        <div v-if="!sequenceId" class="empty-state">
          <div class="title">{{ t('animation.animationStage') }}</div>
          <div class="desc">{{ t('animation.sequenceHint') }}</div>
          <div class="hint">{{ t('animation.supportedEffects') }}</div>
        </div>
      </slot>
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

.empty-state .hint {
  font-size: 11px;
  opacity: 0.6;
}
</style>
