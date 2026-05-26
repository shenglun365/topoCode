<script setup lang="ts">
import { computed } from 'vue'
import {
  ChevronRightIcon,
  FolderIcon,
  FolderOpenIcon,
  DocumentIcon,
} from '@heroicons/vue/24/outline'
import type { FileTreeNode } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PR-009')
const props = defineProps<{
  node: FileTreeNode
  depth: number
  isExpanded: boolean
  isLoading?: boolean
  hasLoadedChildren?: boolean
  getFileColor?: (node: FileTreeNode) => string
  // 展开状态管理（直接传递数组，让子节点自己查询）
  expandedNodes?: string[]
  getNodeKey?: (node: FileTreeNode, depth: number) => string
  loadingPaths?: string[]
  loadedPaths?: string[]
}>()

const emit = defineEmits<{
  toggle: [node: FileTreeNode, depth: number]
  select: [node: FileTreeNode]
  open: [node: FileTreeNode]
}>()

const icon = computed(() => {
  if (props.node.type === 'directory') {
    return props.isExpanded ? FolderOpenIcon : FolderIcon
  }
  return DocumentIcon
})

const iconColor = computed(() => {
  if (props.getFileColor) {
    return props.getFileColor(props.node)
  }
  if (props.node.type === 'directory') return 'text-accent'
  switch (props.node.language) {
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
})

function handleChildToggle(child: any, childDepth: number) {
  emit('toggle', child, depth.value + 1)
}

function handleChildSelect(child: any) {
  emit('select', child)
}

function handleChildOpen(child: any) {
  emit('open', child)
}

const depth = computed(() => props.depth)

/**
 * 压缩节点展开后的子节点列表（VS Code 风格：逐层展开）
 * 点击 "a/b/c" → 显示 "a/b/" 目录 + "c" 子节点
 */
const expandedChildren = computed(() => {
  if (!props.node.compressedPath || !props.isExpanded) return null

  const parts = props.node.compressedPath.split('/')
  if (parts.length <= 1) return null

  // 分离最后一层
  const lastPart = parts[parts.length - 1]
  const remainingParts = parts.slice(0, -1)
  const remainingPath = remainingParts.join('/')

  // 构建展开后的结构
  const lastNode = props.node.children?.find(c => c.name === lastPart)

  // 剩余部分作为父目录
  const parentForRemaining: any = {
    name: remainingPath,
    type: 'directory',
    compressedPath: remainingParts.length > 1 ? remainingPath : undefined,
    path: props.node.path ? props.node.path.split('/').slice(0, -1).join('/') : '',
    children: lastNode ? [lastNode] : [],
    is_empty: false,
  }

  return [parentForRemaining]
})

function handleClick() {
  if (props.node.type === 'directory') {
    emit('toggle', props.node, props.depth)
  } else {
    emit('select', props.node)
  }
}

function handleDblClick() {
  emit('open', props.node)
  if (props.node.type === 'directory') {
    emit('toggle', props.node, props.depth)
  }
}
</script>

<template>
  <div class="file-tree-node">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div
      class="tree-item"
      :class="{ 'tree-item-compressed': node.compressedPath }"
      :style="{ paddingLeft: `${depth * 16 + 8}px` }"
      @click="handleClick"
      @dblclick="handleDblClick"
    >
      <!-- 展开/折叠箭头 -->
      <div
        v-if="node.type === 'directory'"
        class="tree-arrow"
        :class="{ expanded: isExpanded }"
      >
        <ChevronRightIcon class="w-3 h-3" />
      </div>
      <div
        v-else
        class="tree-arrow-empty"
      />

      <!-- 图标 -->
      <component
        :is="icon"
        :class="['w-4 h-4', iconColor, 'shrink-0']"
      />

      <!-- 名称（压缩节点显示 a/b/c 格式） -->
      <span
        v-if="node.compressedPath"
        class="tree-name-compressed"
        :title="node.compressedPath"
      >
        <template
          v-for="(part, idx) in node.compressedPath.split('/')"
          :key="idx"
        >
          <span
            v-if="idx > 0"
            class="tree-name-separator"
          >/</span>
          <span class="tree-name-part">{{ part }}</span>
        </template>
      </span>
      <span
        v-else
        class="tree-name"
        :title="node.name"
      >
        {{ node.name }}
      </span>

      <!-- 懒加载指示器 -->
      <span
        v-if="node.type === 'directory' && isLoading"
        class="loading-indicator"
      >
        <svg
          class="w-3 h-3 loading-spin"
          viewBox="0 0 24 24"
        >
          <circle
            class="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            stroke-width="4"
            fill="none"
          />
          <path
            class="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      </span>

      <!-- 未加载子节点提示 -->
      <span
        v-else-if="node.type === 'directory' && !hasLoadedChildren && !isLoading"
        class="text-muted lazy-hint"
      >
        click to load
      </span>

      <!-- 语言标签 -->
      <span
        v-if="node.language && node.type === 'file'"
        class="badge badge-gray"
        style="font-size:8px; margin-left:auto;"
      >
        {{ node.language }}
      </span>

      <!-- 文件大小 -->
      <span
        v-if="node.size !== undefined && node.type === 'file'"
        class="text-muted"
        style="font-size:10px; margin-left:8px;"
      >
        {{ node.size > 1024 * 1024 ? `${(node.size / 1024 / 1024).toFixed(1)}MB` : node.size > 1024 ? `${(node.size / 1024).toFixed(1)}KB` : `${node.size}B` }}
      </span>
    </div>

    <!-- 子节点 -->
    <div v-if="node.type === 'directory' && isExpanded">
      <!-- 压缩节点：显示展开后的子节点 -->
      <template v-if="expandedChildren">
        <FileTreeNode
          v-for="child in expandedChildren"
          :key="child.path || child.name"
          :node="child"
          :depth="depth + 1"
          :is-expanded="expandedNodes && getNodeKey ? expandedNodes.includes(getNodeKey(child, depth + 1)) : false"
          :is-loading="loadingPaths ? loadingPaths.includes(child.path || '/') : false"
          :has-loaded-children="loadedPaths ? loadedPaths.includes(child.path || '/') : false"
          :get-file-color="getFileColor"
          :expanded-nodes="expandedNodes"
          :get-node-key="getNodeKey"
          :loading-paths="loadingPaths"
          :loaded-paths="loadedPaths"
          @toggle="handleChildToggle"
          @select="handleChildSelect"
          @open="handleChildOpen"
        />
      </template>
      <!-- 普通节点：显示原始子节点 -->
      <template v-else-if="node.children && node.children.length > 0">
        <FileTreeNode
          v-for="child in node.children"
          :key="child.path || child.name"
          :node="child"
          :depth="depth + 1"
          :is-expanded="expandedNodes && getNodeKey ? expandedNodes.includes(getNodeKey(child, depth + 1)) : false"
          :is-loading="loadingPaths ? loadingPaths.includes(child.path || '/') : false"
          :has-loaded-children="loadedPaths ? loadedPaths.includes(child.path || '/') : false"
          :get-file-color="getFileColor"
          :expanded-nodes="expandedNodes"
          :get-node-key="getNodeKey"
          :loading-paths="loadingPaths"
          :loaded-paths="loadedPaths"
          @toggle="handleChildToggle"
          @select="handleChildSelect"
          @open="handleChildOpen"
        />
      </template>
    </div>
  </div>
</template>

<style scoped>
.tree-item {
  display: flex;
  align-items: center;
  padding: 3px 8px;
  gap: 4px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-secondary);
  transition: all 0.1s;
  user-select: none;
}

.tree-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.tree-arrow {
  width: 16px;
  height: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-muted);
  transition: transform 0.15s;
  flex-shrink: 0;
}

.tree-arrow.expanded {
  transform: rotate(90deg);
}

.tree-arrow-empty {
  width: 16px;
  flex-shrink: 0;
}

.tree-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tree-name-compressed {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 1px;
}

.tree-name-part {
  color: var(--text-secondary);
}

.tree-name-separator {
  color: var(--text-muted);
  opacity: 0.5;
  margin: 0 1px;
}

.loading-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  color: var(--text-muted);
}

.loading-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.lazy-hint {
  font-size: 10px;
  font-style: italic;
  margin-left: 4px;
}
</style>
