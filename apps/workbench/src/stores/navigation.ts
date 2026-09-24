import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import i18n from '@/i18n'
import type { PageType, Breadcrumb, NavigationState } from '@/types'

export const useNavigationStore = defineStore('navigation', () => {
  // State
  const currentPage = ref<PageType>('home')
  const breadcrumbs = ref<Breadcrumb[]>([])

  // Getters
  const currentBreadcrumb = computed(() => breadcrumbs.value[breadcrumbs.value.length - 1])

  // Actions
  function navigateTo(page: PageType) {
    currentPage.value = page
    updateBreadcrumbs(page)
  }

  function updateBreadcrumbs(page: PageType) {
    const pageNames: Record<PageType, string> = {
      home: i18n.global.t('nav.projectList'),
      code: i18n.global.t('nav.code'),
      analysis: i18n.global.t('pageTitle.analysis'),
      user: i18n.global.t('nav.userCenter'),
      settings: i18n.global.t('nav.settings'),
      coder: i18n.global.t('nav.coder'),
    }
    breadcrumbs.value = [
      { label: 'TopoCode', page: 'home' },
      { label: pageNames[page], page },
    ]
  }

  function addBreadcrumb(breadcrumb: Breadcrumb) {
    breadcrumbs.value.push(breadcrumb)
  }

  function clearBreadcrumbs() {
    breadcrumbs.value = []
  }

  return {
    currentPage,
    breadcrumbs,
    currentBreadcrumb,
    navigateTo,
    addBreadcrumb,
    clearBreadcrumbs,
  }
})
