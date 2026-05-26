<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { ChevronRightIcon } from '@heroicons/vue/24/outline'
import type { DirTreeNode } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('AN-006')
const props = withDefaults(defineProps<{
  node: DirTreeNode
  selectedScopes: string[]
  expandedDirs: Set<string>
  depth?: number
}>(), {
  depth: 0
})

const emit = defineEmits<{
  toggle: [node: DirTreeNode]
  expand: [path: string]
}>()

const checkboxRef = ref<HTMLInputElement | null>(null)

/**
 * 获取目录的三级状态：unchecked / checked / indeterminate
 * 使用 prefix 匹配和 glob 模式，不枚举子目录
 */
function getCheckboxState(node: DirTreeNode): 'checked' | 'unchecked' | 'indeterminate' {
  // 精确路径匹配
  if (props.selectedScopes.includes(node.path)) return 'checked'
  // glob 模式匹配 (dir/* / dir/**)
  if (isPathGlobSelected(node.path)) return 'checked'
  
  if (!node.children || node.children.length === 0) {
    return 'unchecked'
  }
  
  // 子节点中是否有任何被选中或间接匹配
  let checkedCount = 0
  for (const child of node.children) {
    const state = getCheckboxState(child)
    if (state === 'checked') checkedCount++
    else if (state === 'indeterminate') return 'indeterminate'
  }
  
  if (checkedCount === 0) return 'unchecked'
  if (checkedCount === node.children.length) return 'checked'
  return 'indeterminate'
}

/**
 * 检查路径是否被任何已选 glob scope 匹配
 */
function isPathGlobSelected(path: string): boolean {
  for (const s of props.selectedScopes) {
    if (s.endsWith('/*') || s.endsWith('/**')) {
      const prefix = s.slice(0, -2)  // "dir/*" → "dir"
      if (path === prefix) return true
      if (path.startsWith(prefix + '/')) return true
    }
  }
  return false
}

function handleClick() {
  const currentState = getCheckboxState(props.node)
  
  if (currentState === 'checked') {
    // 取消当前节点 — 移除精确路径和通配符模式
    const globPattern = props.node.path + '/*'
    const filtered = props.selectedScopes.filter(p => 
      p !== props.node.path && p !== globPattern && !p.startsWith(props.node.path + '/')
    )
    emit('toggle', {
      ...props.node,
      __action: 'deselect',
      __paths: [props.node.path, globPattern] as any,
    })
  } else {
    // 选中当前节点 — 只添加 dir/* 一个 glob 模式，不枚举子目录
    const globPattern = props.node.path + '/*'
    emit('toggle', {
      ...props.node,
      __action: 'select',
      __paths: [globPattern] as any,
    })
  }
}

function handleExpand() {
  if (props.node.children && props.node.children.length > 0) {
    emit('expand', props.node.path)
  }
}

// Set indeterminate state after mount and on changes
onMounted(() => {
  updateIndeterminate()
})

watch(() => props.selectedScopes, updateIndeterminate, { deep: true })

function updateIndeterminate() {
  if (checkboxRef.value) {
    const state = getCheckboxState(props.node)
    checkboxRef.value.indeterminate = state === 'indeterminate'
  }
}
</script>

<template>
  <div class="dir-tree-node">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div
      class="dir-item"
      :style="{ paddingLeft: `${depth * 16 + 8}px` }"
      @click="handleExpand"
    >
      <!-- Expand/collapse arrow -->
      <div
        class="tree-arrow"
        :class="{
          expanded: expandedDirs.has(node.path),
          'tree-arrow-empty': !node.children || node.children.length === 0
        }"
        @click.stop="handleExpand"
      >
        <ChevronRightIcon
          v-if="node.children && node.children.length > 0"
          class="w-3 h-3"
        />
      </div>
      
      <!-- Checkbox -->
      <input
        ref="checkboxRef"
        type="checkbox"
        :checked="getCheckboxState(node) === 'checked'"
        @click.stop="handleClick"
      >
      
      <!-- Directory name -->
      <span
        class="dir-name"
        :title="node.path"
      >{{ node.name }}</span>
    </div>
    
    <!-- Children -->
    <div v-if="node.children && node.children.length > 0 && expandedDirs.has(node.path)">
      <DirTreeNodeComponent
        v-for="child in node.children"
        :key="child.path"
        :node="child"
        :selected-scopes="selectedScopes"
        :expanded-dirs="expandedDirs"
        :depth="depth + 1"
        @toggle="emit('toggle', $event)"
        @expand="emit('expand', $event)"
      />
    </div>
  </div>
</template>

<style scoped>
.dir-tree-node {
  padding: 0;
}

.dir-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 4px;
  border-radius: 3px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-primary);
}

.dir-item:hover {
  background: var(--bg-hover);
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
  cursor: pointer;
}

.tree-arrow.expanded {
  transform: rotate(90deg);
}

.tree-arrow-empty {
  width: 16px;
  flex-shrink: 0;
}

.dir-item input[type="checkbox"] {
  accent-color: var(--accent);
  cursor: pointer;
}

.dir-name {
  font-family: monospace;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
