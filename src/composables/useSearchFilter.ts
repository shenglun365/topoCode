import { ref, computed, type Ref } from 'vue'

export function useSearchFilter<T extends Record<string, unknown>>(
  items: Ref<T[]>,
  accessor: (item: T) => string,
) {
  const searchQuery = ref('')

  const filtered = computed(() => {
    const q = searchQuery.value.toLowerCase().trim()
    if (!q) return items.value
    return items.value.filter(item =>
      accessor(item).toLowerCase().includes(q),
    )
  })

  const hasResults = computed(() => filtered.value.length > 0)
  const resultCount = computed(() => filtered.value.length)

  function clearSearch() {
    searchQuery.value = ''
  }

  return {
    searchQuery,
    filtered,
    hasResults,
    resultCount,
    clearSearch,
  }
}
