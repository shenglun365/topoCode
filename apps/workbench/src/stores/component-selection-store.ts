import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export interface ComponentRef {
  id: string
  type: 'community' | 'external_package'
  name: string
  taskId: string
  metadata?: {
    nodeCount?: number
    fileCount?: number
    qualityScore?: number
  }
}

export const useComponentSelectionStore = defineStore('component-selection', () => {
  const selecting = ref(false)
  const selected = ref<Record<string, ComponentRef>>({})

  const selectedList = computed(() => Object.values(selected.value))
  const selectedCount = computed(() => selectedList.value.length)

  function toggleSelecting() {
    selecting.value = !selecting.value
    if (!selecting.value) {
      clearAll()
    }
  }

  function setSelecting(v: boolean) {
    selecting.value = v
    if (!v) {
      clearAll()
    }
  }

  function toggle(ref: ComponentRef) {
    if (selected.value[ref.id]) {
      delete selected.value[ref.id]
    } else {
      selected.value[ref.id] = ref
    }
    selected.value = { ...selected.value }
  }

  function select(ref: ComponentRef) {
    selected.value[ref.id] = ref
    selected.value = { ...selected.value }
  }

  function deselect(id: string) {
    delete selected.value[id]
    selected.value = { ...selected.value }
  }

  function selectMany(refs: ComponentRef[]) {
    for (const r of refs) {
      selected.value[r.id] = r
    }
    selected.value = { ...selected.value }
  }

  function clearAll() {
    selected.value = {}
  }

  function isSelected(id: string): boolean {
    return !!selected.value[id]
  }

  function getContextForAI(): string {
    if (selectedList.value.length === 0) return ''
    let ctx = '当前用户引用了以下组件进行分析：\n'
    for (const r of selectedList.value) {
      const typeLabel = r.type === 'community' ? '社区' : '外部包'
      let line = `- ${typeLabel} ${r.name} (ID: ${r.id}`
      if (r.metadata) {
        const parts: string[] = []
        if (r.metadata.nodeCount !== undefined) parts.push(`节点数: ${r.metadata.nodeCount}`)
        if (r.metadata.fileCount !== undefined) parts.push(`文件数: ${r.metadata.fileCount}`)
        if (r.metadata.qualityScore !== undefined) parts.push(`质量分: ${(r.metadata.qualityScore * 100).toFixed(0)}%`)
        if (parts.length > 0) line += ', ' + parts.join(', ')
      }
      line += ')'
      ctx += line + '\n'
    }
    return ctx
  }

  return {
    selecting,
    selected,
    selectedList,
    selectedCount,
    toggleSelecting,
    setSelecting,
    toggle,
    select,
    deselect,
    selectMany,
    clearAll,
    isSelected,
    getContextForAI,
  }
})
