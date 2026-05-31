<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  ArrowRightIcon,
  ArrowLeftIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import { useOnboardingStore } from '@/stores/onboarding'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('OT-003')
const { t } = useI18n()
const onboardingStore = useOnboardingStore()
const router = useRouter()
const route = useRoute()

const spotlightPosition = ref({ x: 0, y: 0, width: 0, height: 0 })
const dialogPosition = ref({ x: 0, y: 0 })
const highlightVisible = ref(false)

const currentStep = computed(() => onboardingStore.steps[onboardingStore.currentStep])
const progress = computed(() => ((onboardingStore.currentStep + 1) / onboardingStore.steps.length) * 100)

// 定位 spotlight
async function updateSpotlight() {
  if (!currentStep.value) { console.log('[Onboarding] No current step'); return }

  const el = document.querySelector(currentStep.value.target)
  console.log('[Onboarding] updateSpotlight step=', currentStep.value.id, 'target=', currentStep.value.target, 'found=', !!el, 'route=', route.path)
  if (!el) {
    highlightVisible.value = false
    // 目标不存在时自动跳到下一步，但不推送路由（避免干扰用户操作）
    console.log('[Onboarding] Target not found, advance silently')
    if (onboardingStore.currentStep < onboardingStore.steps.length - 1) {
      onboardingStore.currentStep++
      nextTick(() => updateSpotlight())
    } else {
      onboardingStore.complete()
    }
    return
  }

  await nextTick()
  const rect = el.getBoundingClientRect()
  spotlightPosition.value = {
    x: rect.left,
    y: rect.top,
    width: rect.width,
    height: rect.height,
  }

  // 计算对话框位置
  const padding = 16
  const dialogWidth = 320
  const dialogHeight = 180

  switch (currentStep.value.position) {
    case 'right':
      dialogPosition.value = { x: rect.right + padding, y: rect.top }
      break
    case 'left':
      dialogPosition.value = { x: rect.left - dialogWidth - padding, y: rect.top }
      break
    case 'bottom':
      dialogPosition.value = { x: rect.left + rect.width / 2 - dialogWidth / 2, y: rect.bottom + padding }
      break
    case 'top':
      dialogPosition.value = { x: rect.left + rect.width / 2 - dialogWidth / 2, y: rect.top - dialogHeight - padding }
      break
  }

  dialogPosition.value.x = Math.max(8, Math.min(dialogPosition.value.x, window.innerWidth - dialogWidth - 8))
  dialogPosition.value.y = Math.max(8, Math.min(dialogPosition.value.y, window.innerHeight - dialogHeight - 8))

  highlightVisible.value = true
  console.log('[Onboarding] Spotlight shown for', currentStep.value.id)
}

// 监听路由变化 → 通知 store → 定位 spotlight
watch(() => route.path, () => {
  if (!onboardingStore.isRunning) return
  console.log('[Onboarding] Route changed to', route.path)
  onboardingStore.onRouteChanged()
  nextTick(() => updateSpotlight())
})

// 监听步骤变化
watch(() => onboardingStore.currentStep, () => {
  if (!onboardingStore.isRunning) return  // 不运行时忽略步骤变化
  console.log('[Onboarding] Step changed to', onboardingStore.currentStep, currentStep.value?.id, 'routeNeeded=', currentStep.value?.route, 'currentRoute=', route.path)
  highlightVisible.value = false
  const step = currentStep.value
  if (step?.route && step.route !== route.path) {
    console.log('[Onboarding] Pushing route', step.route)
    router.push(step.route)
  } else {
    nextTick(() => updateSpotlight())
  }
}, { immediate: true })

// 键盘事件
function handleKeydown(e: KeyboardEvent) {
  if (!onboardingStore.isRunning) return
  if (e.key === 'Escape') onboardingStore.skip()
  else if (e.key === 'ArrowRight' || e.key === 'Enter') onboardingStore.next()
  else if (e.key === 'ArrowLeft') onboardingStore.prev()
}

onMounted(() => {
  window.addEventListener('keydown', handleKeydown)
  console.log('[Onboarding] Mounted, isRunning=', onboardingStore.isRunning, 'currentStep=', onboardingStore.currentStep, 'route=', route.path)
})

onUnmounted(() => {
  window.removeEventListener('keydown', handleKeydown)
})
</script>

<template>
  <Teleport to="body">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div
      v-if="onboardingStore.isRunning"
      class="onboarding-overlay"
    >
      <!-- Spotlight 遮罩 -->
      <div class="spotlight-backdrop" />

      <!-- Spotlight 高亮区域 -->
      <transition name="spotlight">
        <div
          v-if="highlightVisible"
          class="spotlight-highlight"
          :style="{
            left: spotlightPosition.x + 'px',
            top: spotlightPosition.y + 'px',
            width: spotlightPosition.width + 'px',
            height: spotlightPosition.height + 'px',
          }"
        >
          <div class="spotlight-border" />
        </div>
      </transition>

      <!-- 引导对话框 -->
      <transition name="dialog">
        <div
          v-if="highlightVisible && currentStep"
          class="onboarding-dialog"
          :style="{
            left: dialogPosition.x + 'px',
            top: dialogPosition.y + 'px',
          }"
        >
          <!-- 进度条 -->
          <div class="dialog-progress">
            <div
              class="dialog-progress-fill"
              :style="{ width: progress + '%' }"
            />
          </div>

          <!-- 内容 -->
          <div class="dialog-content">
            <h3 class="dialog-title">
              {{ currentStep.title }}
            </h3>
            <p class="dialog-description">
              {{ currentStep.description }}
            </p>
          </div>

          <!-- 步骤指示器 -->
          <div class="dialog-steps">
            <span class="text-muted">
              {{ onboardingStore.currentStep + 1 }} / {{ onboardingStore.steps.length }}
            </span>
          </div>

          <!-- 操作按钮 -->
          <div class="dialog-actions">
            <button
              v-if="onboardingStore.currentStep > 0"
              class="btn btn-ghost btn-sm"
              @click="onboardingStore.prev"
            >
              <ArrowLeftIcon class="w-4 h-4" />
              <span>{{ t('common.back') }}</span>
            </button>
            <div class="flex-1" />
            <button
              class="btn btn-ghost btn-sm"
              @click="onboardingStore.skip"
            >
              <XMarkIcon class="w-4 h-4" />
              <span>{{ t('onboarding.skip') }}</span>
            </button>
            <button
              class="btn btn-primary btn-sm"
              @click="onboardingStore.next"
            >
              <span>{{ onboardingStore.currentStep < onboardingStore.steps.length - 1 ? t('common.next') : t('common.finish') }}</span>
              <ArrowRightIcon class="w-4 h-4" />
            </button>
          </div>
        </div>
      </transition>
    </div>
  </Teleport>
</template>

<style scoped>
.onboarding-overlay {
  position: fixed;
  inset: 0;
  z-index: 10000;
  pointer-events: none;
}

.spotlight-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(2px);
}

.spotlight-highlight {
  position: absolute;
  padding: 4px;
  z-index: 1;
}

.spotlight-border {
  width: 100%;
  height: 100%;
  border: 2px solid var(--accent);
  border-radius: 8px;
  box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.6);
  background: transparent;
}

.spotlight-enter-active,
.spotlight-leave-active {
  transition: opacity 0.2s;
}

.spotlight-enter-from,
.spotlight-leave-to {
  opacity: 0;
}

.onboarding-dialog {
  position: absolute;
  width: 320px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.3);
  pointer-events: auto;
  overflow: hidden;
  z-index: 2;
}

.dialog-progress {
  height: 3px;
  background: var(--bg-tertiary);
}

.dialog-progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.3s;
}

.dialog-content {
  padding: 16px;
}

.dialog-title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 8px;
}

.dialog-description {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}

.dialog-steps {
  padding: 8px 16px;
  font-size: 10px;
}

.dialog-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
}

.dialog-enter-active,
.dialog-leave-active {
  transition: all 0.2s;
}

.dialog-enter-from,
.dialog-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

</style>
