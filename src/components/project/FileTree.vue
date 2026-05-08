<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MagnifyingGlassIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import type { FileTreeNode as FileNodeType } from '@/types/ipc'
import { useProjectStore } from '@/stores/project'
import FileTreeNode from './FileTreeNode.vue'

const props = defineProps<{
  nodes: FileNodeType[]
}>()

const emit = defineEmits<{
  select: [node: FileNodeType]
  open: [node: FileNodeType]
}>()

const { t } = useI18n()
const projectStore = useProjectStore()

const expandedNodes = ref<Set<string>>(new Set())
const loadedPaths = ref<Set<string>>(new Set(['/']))
const loadingPaths = ref<Set<string>>(new Set())
const lazyNodes = ref<FileNodeType[]>([...props.nodes])

// 监听 props.nodes 变化，同步到 lazyNodes
watch(() => props.nodes, (newNodes) => {
  lazyNodes.value = [...newNodes]
}, { deep: true })

// 搜索
const searchQuery = ref('')
const isSearching = computed(() => searchQuery.value.trim().length > 0)

function getNodeKey(node: FileNodeType, depth: number): string {
  return node.path || `${depth}/${node.name}`
}

async function toggleNode(node: FileNodeType, depth: number) {
  if (node.type !== 'directory') return

  const key = getNodeKey(node, depth)
  const wasExpanded = expandedNodes.value.has(key)

  if (wasExpanded) {
    expandedNodes.value.delete(key)
  } else {
    expandedNodes.value.add(key)
    const path = node.path || '/'
    if (!loadedPaths.value.has(path)) {
      await loadChildren(path)
    }
  }
}

async function loadChildren(fromPath: string) {
  if (!projectStore.selectedProjectId) return
  if (loadingPaths.value.has(fromPath)) return

  loadingPaths.value.add(fromPath)
  try {
    const children = await projectStore.getFileTree(projectStore.selectedProjectId, fromPath)
    loadedPaths.value.add(fromPath)
    updateNodeChildren(lazyNodes.value, fromPath, children)
  } catch (err) {
    console.error('Failed to load children:', err)
  } finally {
    loadingPaths.value.delete(fromPath)
  }
}

function updateNodeChildren(nodes: FileNodeType[], targetPath: string, children: FileNodeType[]): boolean {
  for (const node of nodes) {
    const key = getNodeKey(node, 0)
    if (key === targetPath && node.type === 'directory') {
      node.children = children
      return true
    }
    if (node.children && updateNodeChildren(node.children, targetPath, children)) {
      return true
    }
  }
  return false
}

function isExpanded(node: FileNodeType, depth: number): boolean {
  return expandedNodes.value.has(getNodeKey(node, depth))
}

function isLoading(node: FileNodeType): boolean {
  return loadingPaths.value.has(node.path || '/')
}

function hasLoadedChildren(node: FileNodeType): boolean {
  return loadedPaths.value.has(node.path || '/')
}

function getFileColor(node: FileNodeType): string {
  if (node.type === 'directory') return 'text-accent'
  switch (node.language) {
    case 'python': return 'text-green-400'
    case 'javascript':
    case 'typescript': return 'text-blue-400'
    case 'html': return 'text-orange-400'
    case 'css':
    case 'scss': return 'text-purple-400'
    case 'json': return 'text-yellow-400'
    case 'markdown': return 'text-gray-400'
    case 'vue': return 'text-emerald-400'
    default: return 'text-muted'
  }
}

function handleToggle(node: FileNodeType, depth: number) {
  toggleNode(node, depth)
}

function handleSelect(node: FileNodeType) {
  emit('select', node)
}

function handleOpen(node: FileNodeType) {
  emit('open', node)
}
function filterTree(nodes: FileNodeType[], query: string): FileNodeType[] {
  if (!query.trim()) return nodes
  const lowerQuery = query.toLowerCase()
  return nodes.reduce<FileNodeType[]>((result, node) => {
    if (node.type === 'file') {
      if (node.name.toLowerCase().includes(lowerQuery)) {
        result.push({ ...node })
      }
    } else if (node.children) {
      const filteredChildren = filterTree(node.children, query)
      if (filteredChildren.length > 0) {
        result.push({ ...node, children: filteredChildren })
      }
    }
    return result
  }, [])
}

const filteredNodes = computed(() => {
  if (!isSearching.value) return lazyNodes.value
  return filterTree(lazyNodes.value, searchQuery.value)
})

function clearSearch() {
  searchQuery.value = ''
}
</script>

<template>
  <div class="file-tree-container">
    <!-- 搜索框 -->
    <div class="file-tree-search">
      <MagnifyingGlassIcon class="w-3.5 h-3.5 search-icon" />
      <input
        v-model="searchQuery"
        type="text"
        class="search-input"
        :placeholder="t('file.searchFiles')"
      />
      <button
        v-if="searchQuery"
        class="search-clear"
        @click="clearSearch"
      >
        <XMarkIcon class="w-3.5 h-3.5" />
      </button>
    </div>

    <!-- 文件树 -->
    <div class="file-tree">
      <div v-if="isSearching && filteredNodes.length === 0" class="no-results">
        {{ t('common.noResults') }}
      </div>
      <template v-else>
        <FileTreeNode
          v-for="node in filteredNodes"
          :key="getNodeKey(node, 0)"
          :node="node"
          :depth="0"
          :is-expanded="false"
          :get-file-color="getFileColor"
          @select="handleSelect"
          @open="handleOpen"
        />
      </template>
    </div>
  </div>
</template>

<style scoped>
.file-tree-container {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.file-tree-search {
  display: flex;
  align-items: center;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
  gap: 4px;
}

.search-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  border: none;
  background: transparent;
  outline: none;
  font-size: 12px;
  color: var(--text-primary);
}

.search-input::placeholder {
  color: var(--text-muted);
}

.search-clear {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-muted);
  border-radius: 3px;
}

.search-clear:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

.file-tree {
  flex: 1;
  padding: 4px 0;
  overflow: auto;
}

.no-results {
  padding: 20px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
}
</style>
