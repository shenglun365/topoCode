import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Resource, ResourceCategory, ResourceListMeta } from '@/types'
import { resourceService } from '@/services/resource-service'

export const useResourceStore = defineStore('resource', () => {
  const resources = ref<Resource[]>([])
  const currentResource = ref<Resource | null>(null)
  const loading = ref(false)
  const meta = ref<ResourceListMeta | null>(null)
  const activeCategoryKey = ref('')
  const ownedMode = ref(false)
  const pagination = ref({ page: 1, total: 0, pageSize: 12 })

  const categories = computed<ResourceCategory[]>(() => {
    return meta.value?.categories || []
  })

  const activeCategory = computed(() => {
    return categories.value.find(c => c.key === activeCategoryKey.value)
  })

  const filteredResources = computed(() => {
    if (ownedMode.value) return resources.value
    if (!activeCategoryKey.value) return resources.value
    return resources.value.filter(r => r.category === activeCategoryKey.value)
  })

  async function fetchResources(owned?: boolean, token?: string) {
    loading.value = true
    try {
      const params: any = { page: pagination.value.page }
      if (owned) {
        params.owned = true
        params.token = token
      } else if (activeCategoryKey.value) {
        params.category = activeCategoryKey.value
      }
      const result = await resourceService.list(params)
      resources.value = result.items
      meta.value = result.meta
      pagination.value.total = result.total
    } finally {
      loading.value = false
    }
  }

  async function fetchDetail(id: number, token?: string) {
    loading.value = true
    try {
      currentResource.value = await resourceService.detail(id, token)
    } finally {
      loading.value = false
    }
  }

  function setCategory(key: string) {
    activeCategoryKey.value = key
    ownedMode.value = false
    pagination.value.page = 1

    if (key === 'owned') {
      ownedMode.value = true
    } else {
      const cat = categories.value.find(c => c.key === key)
      if (cat?.scope === 'owned') {
        ownedMode.value = true
      }
    }
  }

  function clearOwned() {
    ownedMode.value = false
    activeCategoryKey.value = ''
    pagination.value.page = 1
  }

  async function getDownloadUrl(id: number, token: string): Promise<string> {
    return resourceService.getDownloadUrl(id, token)
  }

  return {
    resources, currentResource, loading, meta,
    categories, activeCategory, activeCategoryKey, ownedMode, pagination,
    filteredResources, fetchResources, fetchDetail,
    setCategory, clearOwned, getDownloadUrl,
  }
})
