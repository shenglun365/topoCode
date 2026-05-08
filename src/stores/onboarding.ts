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
}

export const useOnboardingStore = defineStore('onboarding', () => {
  const isCompleted = ref(false)
  const isRunning = ref(false)
  const currentStep = ref(0)

  const steps: OnboardingStep[] = [
    {
      id: 'activity-bar',
      title: t('onboarding.steps.activityBar.title'),
      description: t('onboarding.steps.activityBar.description'),
      target: '.activity-bar',
      position: 'right',
    },
    {
      id: 'project-list',
      title: t('onboarding.steps.projectList.title'),
      description: t('onboarding.steps.projectList.description'),
      target: '.project-list',
      position: 'right',
    },
    {
      id: 'import-zone',
      title: t('onboarding.steps.importZone.title'),
      description: t('onboarding.steps.importZone.description'),
      target: '.import-zone',
      position: 'bottom',
    },
    {
      id: 'file-tree',
      title: t('onboarding.steps.fileTree.title'),
      description: t('onboarding.steps.fileTree.description'),
      target: '.file-tree-container',
      position: 'right',
    },
    {
      id: 'tab-bar',
      title: t('onboarding.steps.tabBar.title'),
      description: t('onboarding.steps.tabBar.description'),
      target: '.tab-bar',
      position: 'bottom',
    },
    {
      id: 'status-bar',
      title: t('onboarding.steps.statusBar.title'),
      description: t('onboarding.steps.statusBar.description'),
      target: '.status-bar',
      position: 'top',
    },
  ]

  function start() {
    isRunning.value = true
    currentStep.value = 0
  }

  function next() {
    if (currentStep.value < steps.length - 1) {
      currentStep.value++
    } else {
      complete()
    }
  }

  function prev() {
    if (currentStep.value > 0) {
      currentStep.value--
    }
  }

  function skip() {
    isRunning.value = false
    isCompleted.value = true
  }

  function complete() {
    isRunning.value = false
    isCompleted.value = true
  }

  function reset() {
    isCompleted.value = false
    isRunning.value = false
    currentStep.value = 0
  }

  return {
    isCompleted,
    isRunning,
    currentStep,
    steps,
    start,
    next,
    prev,
    skip,
    complete,
    reset,
  }
})
