<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { MagnifyingGlassIcon, XMarkIcon } from '@heroicons/vue/24/outline'
import type { FileTreeNode as FileNodeType } from '@/types/ipc'
import { useProjectStore } from '@/stores/project'
import { useDebugStore } from '@/stores/debug'
import FileTreeNode from './FileTreeNode.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PR-008')
const debug = useDebugStore()

const props = defineProps<{
  nodes: FileNodeType[]
}>()

const emit = defineEmits<{
  select: [node: FileNodeType]
  open: [node: FileNodeType]
}>()

const { t } = useI18n()
const projectStore = useProjectStore()

const expandedNodes = ref<string[]>([])
const loadedPaths = ref<string[]>(['/'])
const loadingPaths = ref<string[]>([])
const lazyNodes = ref<FileNodeType[]>([...props.nodes])

// 监听 props.nodes 变化，同步到 lazyNodes
watch(() => props.nodes, (newNodes) => {
  lazyNodes.value = [...newNodes]
}, { deep: true })

// 搜索
const searchQuery = ref('')
const isSearching = computed(() => searchQuery.value.trim().length > 0)

function getNodeKey(node: FileNodeType, depth: number): string {
  // 统一使用 node.path 作为 key，避免 depth/name 组合导致的不一致
  return node.path || node.name
}

async function toggleNode(node: FileNodeType, depth: number) {
  if (node.type !== 'directory') return

  const key = getNodeKey(node, depth)
  const idx = expandedNodes.value.indexOf(key)
  const wasExpanded = idx >= 0
  const path = node.path || '/'
  const hasLoaded = loadedPaths.value.includes(path)

  if (wasExpanded) {
    expandedNodes.value.splice(idx, 1)
  } else {
    expandedNodes.value.push(key)
    if (!hasLoaded) {
      await loadChildren(path)
    }
  }
}

async function loadChildren(fromPath: string) {
  if (!projectStore.selectedProjectId) return
  if (loadingPaths.value.includes(fromPath)) return

  loadingPaths.value.push(fromPath)
  try {
    const children = await projectStore.getFileTree(projectStore.selectedProjectId, fromPath)
    if (!loadedPaths.value.includes(fromPath)) {
      loadedPaths.value.push(fromPath)
    }
    updateNodeChildren(lazyNodes.value, fromPath, children)
  } catch (err) {
    console.error('Failed to load children:', err)
  } finally {
    const idx = loadingPaths.value.indexOf(fromPath)
    if (idx >= 0) loadingPaths.value.splice(idx, 1)
  }
}

function updateNodeChildren(nodes: FileNodeType[], targetPath: string, children: FileNodeType[]): boolean {
  for (let i = 0; i < nodes.length; i++) {
    const node = nodes[i]
    const key = getNodeKey(node, 0)
    if (key === targetPath && node.type === 'directory') {
      // 强制触发响应式：替换整个节点
      nodes[i] = { ...node, children: [...children] }
      return true
    }
    if (node.children && updateNodeChildren(node.children, targetPath, children)) {
      return true
    }
  }
  return false
}

function isExpanded(node: FileNodeType, depth: number): boolean {
  return expandedNodes.value.includes(getNodeKey(node, depth))
}

function isLoading(node: FileNodeType): boolean {
  return loadingPaths.value.includes(node.path || '/')
}

function hasLoadedChildren(node: FileNodeType): boolean {
  return loadedPaths.value.includes(node.path || '/')
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

/**
 * 压缩连续空目录链（至少 2 层才压缩）
 * 将连续的空目录合并为一个压缩节点，如 java/main/com/example
 */
function compressEmptyDirectories(nodes: FileNodeType[]): FileNodeType[] {
  const result: FileNodeType[] = []
  for (const node of nodes) {
    if (node.type === 'directory' && node.is_empty && node.children && node.children.length > 0) {
      // 尝试压缩：收集连续空目录链
      const chain: string[] = [node.name]
      let current: FileNodeType | null = node
      let maxDepth = 20 // 防止无限递归

      while (current && current.type === 'directory' && current.is_empty
        && current.children && current.children.length === 1 && maxDepth-- > 0) {
        const child = current.children[0]
        if (child.type === 'directory' && child.is_empty) {
          chain.push(child.name)
          current = child
        }
        else {
          break
        }
      }

      // 至少 2 层才压缩
      if (chain.length >= 2) {
        // 构建压缩节点
        const compressedNode: FileNodeType = {
          ...node,
          name: chain.join('/'),
          compressedPath: chain.join('/'),
          path: current!.path || node.path,
          children: current!.children,
          is_empty: current!.is_empty,
        }
        result.push(compressedNode)
      }
      else {
        // 不压缩，递归处理子节点
        const cloned = { ...node }
        if (node.children) {
          cloned.children = compressEmptyDirectories(node.children)
        }
        result.push(cloned)
      }
    }
    else if (node.type === 'directory' && node.children) {
      // 非空目录，递归处理子节点
      const cloned = { ...node }
      cloned.children = compressEmptyDirectories(node.children)
      result.push(cloned)
    }
    else {
      result.push(node)
    }
  }
  return result
}

function handleToggle(node: FileNodeType, depth: number) {
  toggleNode(node, depth)
}

function handleSelect(node: FileNodeType) {
  if (node.type === 'file') {
    emit('select', node)
  }
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
  if (!isSearching.value) {
    // 非搜索模式：应用空目录压缩
    return compressEmptyDirectories(lazyNodes.value)
  }
  // 搜索模式：不压缩，展开所有层级以显示匹配文件（VS Code 行为）
  return filterTree(lazyNodes.value, searchQuery.value)
})

function clearSearch() {
  searchQuery.value = ''
}
</script>

<template>
  <div class="file-tree-container">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 搜索框 -->
    <div class="file-tree-search">
      <MagnifyingGlassIcon class="w-3.5 h-3.5 search-icon" />
      <input
        v-model="searchQuery"
        type="text"
        class="search-input"
        :placeholder="t('file.searchFiles')"
      >
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
      <div
        v-if="isSearching && filteredNodes.length === 0"
        class="no-results"
      >
        {{ t('common.noResults') }}
      </div>
      <template v-else>
        <FileTreeNode
          v-for="node in filteredNodes"
          :key="getNodeKey(node, 0)"
          :node="node"
          :depth="0"
          :is-expanded="expandedNodes.includes(getNodeKey(node, 0))"
          :is-loading="loadingPaths.includes(node.path || '/')"
          :has-loaded-children="loadedPaths.includes(node.path || '/')"
          :get-file-color="getFileColor"
          :expanded-nodes="expandedNodes"
          :get-node-key="getNodeKey"
          :loading-paths="loadingPaths"
          :loaded-paths="loadedPaths"
          @toggle="handleToggle"
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
