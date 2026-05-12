<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { ChevronRightIcon } from '@heroicons/vue/24/outline'
import type { DirTreeNode } from '@/types/ipc'

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
 */
function getCheckboxState(node: DirTreeNode): 'checked' | 'unchecked' | 'indeterminate' {
  const isSelected = props.selectedScopes.includes(node.path)
  
  if (!node.children || node.children.length === 0) {
    return isSelected ? 'checked' : 'unchecked'
  }
  
  // 检查子节点
  const checkedCount = node.children.filter(child => {
    const state = getCheckboxState(child)
    return state === 'checked'
  }).length
  
  if (checkedCount === 0) return 'unchecked'
  if (checkedCount === node.children.length) return 'checked'
  return 'indeterminate'
}

/**
 * 获取所有子目录的路径
 */
function getAllChildPaths(node: DirTreeNode): string[] {
  const paths: string[] = []
  if (node.children) {
    for (const child of node.children) {
      paths.push(child.path)
      paths.push(...getAllChildPaths(child))
    }
  }
  return paths
}

function handleClick() {
  const currentState = getCheckboxState(props.node)
  const childPaths = getAllChildPaths(props.node)
  
  if (currentState === 'checked') {
    // 取消当前节点和所有子节点
    const filtered = props.selectedScopes.filter(p => p !== props.node.path && !childPaths.includes(p))
    emit('toggle', { ...props.node, __action: 'deselect', __paths: [props.node.path, ...childPaths] as any })
  } else {
    // 选中当前节点和所有子节点
    const newPaths = [props.node.path, ...childPaths]
    emit('toggle', { ...props.node, __action: 'select', __paths: newPaths as any })
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
        <ChevronRightIcon v-if="node.children && node.children.length > 0" class="w-3 h-3" />
      </div>
      
      <!-- Checkbox -->
      <input
        ref="checkboxRef"
        type="checkbox"
        :checked="getCheckboxState(node) === 'checked'"
        @click.stop="handleClick"
      />
      
      <!-- Directory name -->
      <span class="dir-name" :title="node.path">{{ node.name }}</span>
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
