import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
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
      home: '项目导入',
      code: '代码解析',
      analysis: '代码分析',
      knowledge: '知识库',
      coder: 'AI 助手',
      user: '设置',
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
