/** Knowledge Store - 知识库管理 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { KnowledgeDoc, KnowledgeGraph, Dimensions } from '@/types/ipc'
import { ipc } from '@/services/ipc'

export interface KnowledgeFilter {
  search: string
  dimensions: {
    lifecycle: string[]
    techStack: string[]
    abstraction: string[]
    purpose: string[]
  }
  sortBy: 'updated-desc' | 'updated-asc' | 'created-desc' | 'created-asc' | 'name-asc'
}

export const useKnowledgeStore = defineStore('knowledge', () => {
  // State
  const docs = ref<KnowledgeDoc[]>([])
  const selectedDocId = ref<string | null>(null)
  const activeTab = ref<'graph' | 'categories' | 'documents' | 'animation'>('graph')
  const filter = ref<KnowledgeFilter>({
    search: '',
    dimensions: {
      lifecycle: [],
      techStack: [],
      abstraction: [],
      purpose: [],
    },
    sortBy: 'updated-desc',
  })
  const graph = ref<KnowledgeGraph>({ nodes: [], edges: [] })
  const dimensions = ref<Dimensions>({
    lifecycle: [],
    techStack: [],
    abstraction: [],
    purpose: [],
  })
  const loading = ref(false)

  // Getters
  const selectedDoc = computed(() =>
    docs.value.find(d => d.id === selectedDocId.value)
  )

  const filteredDocs = computed(() => {
    let result = [...docs.value]

    if (filter.value.search) {
      const search = filter.value.search.toLowerCase()
      result = result.filter(d =>
        d.title.toLowerCase().includes(search) ||
        d.description.toLowerCase().includes(search)
      )
    }

    const dims = filter.value.dimensions
    if (dims.lifecycle.length > 0) {
      result = result.filter(d => d.tags.lifecycle.some(t => dims.lifecycle.includes(t)))
    }
    if (dims.techStack.length > 0) {
      result = result.filter(d => d.tags.techStack.some(t => dims.techStack.includes(t)))
    }
    if (dims.abstraction.length > 0) {
      result = result.filter(d => d.tags.abstraction.some(t => dims.abstraction.includes(t)))
    }
    if (dims.purpose.length > 0) {
      result = result.filter(d => d.tags.purpose.some(t => dims.purpose.includes(t)))
    }

    result.sort((a, b) => {
      if (a.pinned && !b.pinned) return -1
      if (!a.pinned && b.pinned) return 1

      switch (filter.value.sortBy) {
        case 'updated-desc': return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
        case 'updated-asc': return new Date(a.updatedAt).getTime() - new Date(b.updatedAt).getTime()
        case 'created-desc': return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
        case 'created-asc': return new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
        case 'name-asc': return a.title.localeCompare(b.title, 'zh-CN')
        default: return 0
      }
    })

    return result
  })

  const docCount = computed(() => docs.value.length)

  // Actions
  async function loadDocs() {
    loading.value = true
    try {
      docs.value = await ipc.knowledge.listDocs({})
      dimensions.value = await ipc.knowledge.getDimensions()
    } finally {
      loading.value = false
    }
  }

  async function loadGraph(projectId?: string) {
    graph.value = await ipc.knowledge.getGraph({ projectId })
  }

  async function createDoc(title: string, content: string, projectId: string, tags?: Partial<Dimensions>) {
    const doc = await ipc.knowledge.createDoc({ title, content, projectId, tags })
    docs.value.push(doc)
    return doc
  }

  async function updateDoc(params: {
    id: string
    content?: string
    tags?: Partial<Dimensions>
    status?: string
    favorite?: boolean
    pinned?: boolean
  }) {
    const doc = await ipc.knowledge.updateDoc(params)
    const idx = docs.value.findIndex(d => d.id === params.id)
    if (idx >= 0) docs.value[idx] = doc
    return doc
  }

  async function deleteDoc(id: string) {
    await ipc.knowledge.deleteDoc(id)
    const idx = docs.value.findIndex(d => d.id === id)
    if (idx >= 0) docs.value.splice(idx, 1)
    if (selectedDocId.value === id) selectedDocId.value = null
  }

  function selectDoc(id: string) {
    selectedDocId.value = id
  }

  function deselectDoc() {
    selectedDocId.value = null
  }

  function setActiveTab(tab: 'graph' | 'categories' | 'documents' | 'animation') {
    activeTab.value = tab
  }

  function setSearch(search: string) {
    filter.value.search = search
  }

  function toggleDimension(dim: keyof KnowledgeFilter['dimensions'], tag: string) {
    const arr = filter.value.dimensions[dim]
    const idx = arr.indexOf(tag)
    if (idx >= 0) {
      arr.splice(idx, 1)
    } else {
      arr.push(tag)
    }
  }

  function clearFilters() {
    filter.value.search = ''
    filter.value.dimensions = {
      lifecycle: [],
      techStack: [],
      abstraction: [],
      purpose: [],
    }
  }

  function setSortBy(sortBy: KnowledgeFilter['sortBy']) {
    filter.value.sortBy = sortBy
  }

  async function toggleFavorite(docId: string) {
    const doc = docs.value.find(d => d.id === docId)
    if (doc) {
      await updateDoc({ id: docId, favorite: !doc.favorite })
    }
  }

  async function togglePin(docId: string) {
    const doc = docs.value.find(d => d.id === docId)
    if (doc) {
      await updateDoc({ id: docId, pinned: !doc.pinned })
    }
  }

  return {
    docs,
    selectedDocId,
    activeTab,
    filter,
    graph,
    dimensions,
    loading,
    selectedDoc,
    filteredDocs,
    docCount,
    loadDocs,
    loadGraph,
    createDoc,
    updateDoc,
    deleteDoc,
    selectDoc,
    deselectDoc,
    setActiveTab,
    setSearch,
    toggleDimension,
    clearFilters,
    setSortBy,
    toggleFavorite,
    togglePin,
  }
})
