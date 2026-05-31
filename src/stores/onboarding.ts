import { ref } from 'vue'
import { defineStore } from 'pinia'
import i18n from '@/i18n'

const { t } = i18n.global

export interface OnboardingStep {
  id: string
  title: string
  description: string
  target: string  // CSS selector
  position: 'top' | 'bottom' | 'left' | 'right'
  route?: string  // 切换到目标路由后再定位元素
}

export const useOnboardingStore = defineStore('onboarding', () => {
  const isCompleted = ref(false)
  const isRunning = ref(false)
  const currentStep = ref(0)
  const pendingRoute = ref<string | null>(null)

  const steps: OnboardingStep[] = [
    {
      id: 'import-project',
      title: t('onboarding.steps.importProject.title'),
      description: t('onboarding.steps.importProject.description'),
      target: '.page-home',
      position: 'bottom',
      route: '/home',
    },
    {
      id: 'code-browse',
      title: t('onboarding.steps.codeBrowse.title'),
      description: t('onboarding.steps.codeBrowse.description'),
      target: '.file-tree-container',
      position: 'right',
      route: '/code',
    },
    {
      id: 'create-task',
      title: t('onboarding.steps.createTask.title'),
      description: t('onboarding.steps.createTask.description'),
      target: '.task-create-form',
      position: 'bottom',
      route: '/code',
    },
    {
      id: 'view-report',
      title: t('onboarding.steps.viewReport.title'),
      description: t('onboarding.steps.viewReport.description'),
      target: '.comp-analysis-body',
      position: 'right',
      route: '/analysis',
    },
    {
      id: 'ai-analysis',
      title: t('onboarding.steps.aiAnalysis.title'),
      description: t('onboarding.steps.aiAnalysis.description'),
      target: '.community-analysis-pipeline',
      position: 'left',
      route: '/analysis',
    },
    {
      id: 'model-config',
      title: t('onboarding.steps.modelConfig.title'),
      description: t('onboarding.steps.modelConfig.description'),
      target: '.model-config',
      position: 'right',
      route: '/user',
    },
    {
      id: 'template-manager',
      title: t('onboarding.steps.templateManager.title'),
      description: t('onboarding.steps.templateManager.description'),
      target: '.template-manager',
      position: 'right',
      route: '/user',
    },
    {
      id: 'web-viewer',
      title: t('onboarding.steps.webViewer.title'),
      description: t('onboarding.steps.webViewer.description'),
      target: '.status-bar',
      position: 'top',
    },
  ]

  function start() {
    isRunning.value = true
    currentStep.value = 0
    pendingRoute.value = steps[0]?.route || null
  }

  function navigateToStep(stepIndex: number) {
    const step = steps[stepIndex]
    if (step?.route) {
      pendingRoute.value = step.route
    } else {
      pendingRoute.value = null
    }
  }

  function next() {
    if (currentStep.value < steps.length - 1) {
      const nextIdx = currentStep.value + 1
      currentStep.value = nextIdx
      navigateToStep(nextIdx)
    } else {
      complete()
    }
  }

  function prev() {
    if (currentStep.value > 0) {
      const prevIdx = currentStep.value - 1
      currentStep.value = prevIdx
      navigateToStep(prevIdx)
    }
  }

  function onRouteChanged() {
    pendingRoute.value = null
  }

  function skip() {
    isRunning.value = false
    isCompleted.value = true
    pendingRoute.value = null
  }

  function complete() {
    isRunning.value = false
    isCompleted.value = true
    pendingRoute.value = null
  }

  function reset() {
    isCompleted.value = false
    isRunning.value = false
    currentStep.value = 0
    pendingRoute.value = null
  }

  return {
    isCompleted,
    isRunning,
    currentStep,
    steps,
    pendingRoute,
    start,
    next,
    prev,
    skip,
    complete,
    reset,
    navigateToStep,
    onRouteChanged,
  }
})
