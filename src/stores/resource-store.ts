import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Resource } from '@/types'
import { resourceService } from '@/services/resource-service'

export const useResourceStore = defineStore('resource', () => {
  const resources = ref<Resource[]>([])
  const currentResource = ref<Resource | null>(null)
  const loading = ref(false)
  const categories = ref<string[]>(['全部'])
  const activeCategory = ref('全部')
  const pagination = ref({ page: 1, total: 0, pageSize: 12 })

  const filteredResources = computed(() => {
    if (activeCategory.value === '全部') return resources.value
    return resources.value.filter(r => r.category === activeCategory.value)
  })

  async function fetchResources() {
    loading.value = true
    try {
      const result = await resourceService.list({ page: pagination.value.page, category: activeCategory.value === '全部' ? undefined : activeCategory.value })
      resources.value = result.items
      pagination.value.total = result.total
      const cats = new Set<string>()
      cats.add('全部')
      result.items.forEach(r => cats.add(r.category))
      categories.value = Array.from(cats)
    } finally {
      loading.value = false
    }
  }

  async function fetchDetail(id: number) {
    loading.value = true
    try {
      currentResource.value = await resourceService.detail(id)
    } finally {
      loading.value = false
    }
  }

  function setCategory(cat: string) {
    activeCategory.value = cat
    pagination.value.page = 1
  }

  async function getDownloadUrl(id: number, token: string): Promise<string> {
    return resourceService.getDownloadUrl(id, token)
  }

  return {
    resources, currentResource, loading, categories, activeCategory, pagination,
    filteredResources, fetchResources, fetchDetail, setCategory, getDownloadUrl,
  }
})