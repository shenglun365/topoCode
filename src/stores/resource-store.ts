import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Resource, ResourceCategory, ResourceListMeta } from '@/types'
import { resourceService } from '@/services/resource-service'

const DEFAULT_CATEGORIES: ResourceCategory[] = [
  { key: '', label: '全部' },
  { key: '__prerelease__', label: '即将上线', color: '#f59e0b' },
  { key: '__free__', label: '免费', color: '#10b981' },
  { key: '__points__', label: '积分兑换', color: '#3b82f6' },
  { key: '已购', label: '已购资源', color: '#22c55e', scope: 'owned' },
]

export const useResourceStore = defineStore('resource', () => {
  const resources = ref<Resource[]>([])
  const currentResource = ref<Resource | null>(null)
  const loading = ref(false)
  const meta = ref<ResourceListMeta | null>(null)
  const activeCategoryKey = ref('')
  const ownedMode = ref(false)
  const searchQuery = ref('')
  const sortBy = ref('time')
  const sortOrder = ref('desc')
  const pagination = ref({ page: 1, total: 0, pageSize: 12 })

  const categories = computed<ResourceCategory[]>(() => {
    const serverCats = meta.value?.categories
    if (!serverCats || serverCats.length === 0) return DEFAULT_CATEGORIES
    // Merge default special categories with server categories (server wins for same key)
    const merged = [...DEFAULT_CATEGORIES]
    const existingKeys = new Set(DEFAULT_CATEGORIES.map(c => c.key))
    for (const cat of serverCats) {
      if (existingKeys.has(cat.key)) {
        const idx = merged.findIndex(c => c.key === cat.key)
        if (idx >= 0) merged[idx] = cat
      } else {
        merged.push(cat)
      }
    }
    return merged
  })

  const activeCategory = computed(() => {
    return categories.value.find(c => c.key === activeCategoryKey.value)
  })

  const filteredResources = computed(() => {
    if (ownedMode.value) return resources.value
    if (!activeCategoryKey.value) return resources.value
    if (activeCategoryKey.value.startsWith('__')) return resources.value
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
      if (searchQuery.value) params.q = searchQuery.value
      if (sortBy.value) params.sort_by = sortBy.value
      if (sortOrder.value) params.sort_order = sortOrder.value
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
    } catch (e) {
      currentResource.value = null
      throw e
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

  function setSearch(q: string) {
    searchQuery.value = q
    pagination.value.page = 1
  }

  function setSort(by: string, order: string) {
    sortBy.value = by
    sortOrder.value = order
    pagination.value.page = 1
  }

  return {
    resources, currentResource, loading, meta,
    categories, activeCategory, activeCategoryKey, ownedMode,
    searchQuery, sortBy, sortOrder, pagination,
    filteredResources, fetchResources, fetchDetail,
    setCategory, clearOwned, getDownloadUrl,
    setSearch, setSort,
  }
})
