<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ChevronDownIcon,
  ChevronRightIcon,
  XMarkIcon,
  FunnelIcon,
} from '@heroicons/vue/24/outline'
import type { GroupNode } from '@/types/ipc'
import { ipc } from '@/services/ipc'
import { useProjectStore } from '@/stores/project'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PR-005')
const { t } = useI18n()
const projectStore = useProjectStore()

const emit = defineEmits<{
  change: [groupIds: string[]]
}>()

const isOpen = ref(false)
const dropdownRef = ref<HTMLElement | null>(null)
let mouseLeaveTimer: ReturnType<typeof setTimeout> | null = null
const groups = ref<GroupNode[]>([])
const selectedIds = ref<string[]>([]) // 已确认的筛选
const pendingSelectedIds = ref<string[]>([]) // 临时选中（未确认）
const expandedIds = ref<Set<string>>(new Set())
const searchQuery = ref('')

async function loadGroups() {
  groups.value = await ipc.group.list()
  // 默认展开所有节点
  expandAll(groups.value)
}

function expandAll(nodeList: GroupNode[]) {
  for (const node of nodeList) {
    expandedIds.value.add(node.id)
    if (node.children && node.children.length > 0) {
      expandAll(node.children)
    }
  }
}

function toggleExpand(id: string) {
  if (expandedIds.value.has(id)) {
    expandedIds.value.delete(id)
  } else {
    expandedIds.value.add(id)
  }
}

function openDropdown() {
  // 打开时同步临时状态为当前已选
  pendingSelectedIds.value = [...selectedIds.value]
  isOpen.value = true
}

function toggleSelect(id: string) {
  const idx = pendingSelectedIds.value.indexOf(id)
  if (idx >= 0) {
    pendingSelectedIds.value.splice(idx, 1)
  } else {
    pendingSelectedIds.value.push(id)
  }
}

function confirmFilter() {
  selectedIds.value = [...pendingSelectedIds.value]
  emit('change', selectedIds.value)
  closeDropdown()
}

function cancelFilter() {
  pendingSelectedIds.value = [...selectedIds.value]
  closeDropdown()
}

function selectAll() {
  const allIds = collectAllIds(groups.value)
  pendingSelectedIds.value = [...allIds]
}

function clearAll() {
  pendingSelectedIds.value = []
}

function collectAllIds(nodeList: GroupNode[]): string[] {
  const ids: string[] = []
  for (const node of nodeList) {
    ids.push(node.id)
    if (node.children && node.children.length > 0) {
      ids.push(...collectAllIds(node.children))
    }
  }
  return ids
}

function isExpanded(node: GroupNode): boolean {
  return node.children && node.children.length > 0 && expandedIds.value.has(node.id)
}

function isSelected(node: GroupNode): boolean {
  // 下拉列表打开时显示临时选中状态
  if (isOpen.value) {
    return pendingSelectedIds.value.includes(node.id)
  }
  return selectedIds.value.includes(node.id)
}

function matchesSearch(node: GroupNode): boolean {
  if (!searchQuery.value.trim()) return true
  const q = searchQuery.value.toLowerCase()
  if (node.name.toLowerCase().includes(q)) return true
  if (node.children) {
    for (const child of node.children) {
      if (matchesSearch(child)) return true
    }
  }
  return false
}

function renderIndent(depth: number): string {
  return ' '.repeat(depth * 2)
}

function closeDropdown() {
  isOpen.value = false
}

function handleDropdownMouseEnter() {
  if (mouseLeaveTimer) {
    clearTimeout(mouseLeaveTimer)
    mouseLeaveTimer = null
  }
}

function handleDropdownMouseLeave() {
  mouseLeaveTimer = setTimeout(() => {
    closeDropdown()
  }, 150)
}

function handleOpenGroupManager() {
  // stop 阻止事件冒泡到 dropdown 的 click 关闭
  projectStore.openGroupManagerTab()
}

onMounted(() => {
  loadGroups()
})

// 暴露刷新方法
defineExpose({ loadGroups })
</script>

<template>
  <div class="group-filter">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <button
      class="group-filter-btn"
      :class="{ active: selectedIds.length > 0 }"
      @click="openDropdown()"
    >
      <FunnelIcon class="w-3.5 h-3.5" />
      <span>{{ t('group.filter') }}</span>
      <span
        v-if="selectedIds.length > 0"
        class="group-filter-count"
      >{{ selectedIds.length }}</span>
      <ChevronDownIcon
        class="w-3 h-3 filter-chevron"
        :class="{ open: isOpen }"
      />
    </button>

    <div
      v-if="isOpen"
      ref="dropdownRef"
      class="group-filter-dropdown"
      @mouseenter="handleDropdownMouseEnter"
      @mouseleave="handleDropdownMouseLeave"
    >
      <!-- 搜索框 + 分组管理入口 -->
      <div class="group-filter-search">
        <input
          v-model="searchQuery"
          :placeholder="t('group.searchPlaceholder')"
          type="text"
        >
        <button
          class="group-filter-settings"
          @click.stop="handleOpenGroupManager"
        >
          {{ t('group.setGroups') }}
        </button>
      </div>

      <!-- 分组树 -->
      <div class="group-filter-tree">
        <div
          v-for="group in groups"
          v-if="matchesSearch(group)"
          :key="group.id"
        >
          <div
            class="group-tree-item"
            :class="{ selected: isSelected(group) }"
            @click="toggleSelect(group.id)"
          >
            <span
              v-if="isExpanded(group)"
              class="tree-expand"
              @click.stop="toggleExpand(group.id)"
            >
              <ChevronRightIcon class="w-3 h-3 expand-open" />
            </span>
            <span
              v-else
              class="tree-expand tree-expand-placeholder"
            />
            <span
              class="tree-checkbox"
              :class="{ checked: isSelected(group) }"
            >
              {{ isSelected(group) ? '✓' : '' }}
            </span>
            <span
              class="tree-label"
              :style="{ paddingLeft: renderIndent(group.depth) }"
            >{{ group.name }}</span>
          </div>
          <!-- 子节点 -->
          <div v-if="isExpanded(group) && group.children && group.children.length > 0">
            <div
              v-for="child in group.children"
              v-if="matchesSearch(child)"
              :key="child.id"
            >
              <div
                class="group-tree-item"
                :class="{ selected: isSelected(child) }"
                @click="toggleSelect(child.id)"
              >
                <span class="tree-expand tree-expand-placeholder" />
                <span
                  class="tree-checkbox"
                  :class="{ checked: isSelected(child) }"
                >
                  {{ isSelected(child) ? '✓' : '' }}
                </span>
                <span
                  class="tree-label"
                  :style="{ paddingLeft: renderIndent(child.depth) }"
                >{{ child.name }}</span>
              </div>
              <!-- 递归渲染更深层级 -->
              <div v-if="child.children && child.children.length > 0">
                <div
                  v-for="gc in child.children"
                  v-if="matchesSearch(gc)"
                  :key="gc.id"
                >
                  <div
                    class="group-tree-item"
                    :class="{ selected: isSelected(gc) }"
                    @click="toggleSelect(gc.id)"
                  >
                    <span class="tree-expand tree-expand-placeholder" />
                    <span
                      class="tree-checkbox"
                      :class="{ checked: isSelected(gc) }"
                    >
                      {{ isSelected(gc) ? '✓' : '' }}
                    </span>
                    <span
                      class="tree-label"
                      :style="{ paddingLeft: renderIndent(gc.depth) }"
                    >{{ gc.name }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部操作 -->
      <div class="group-filter-footer">
        <div class="group-filter-footer-left">
          <button
            class="group-filter-action"
            @click="selectAll"
          >
            {{ t('group.selectAll') }}
          </button>
          <button
            class="group-filter-action"
            @click="clearAll"
          >
            {{ t('group.clearAll') }}
          </button>
          <span class="group-filter-selected">{{ pendingSelectedIds.length }} {{ t('group.selected') }}</span>
        </div>
        <div class="group-filter-footer-right">
          <button
            class="group-filter-cancel"
            @click="cancelFilter"
          >
            {{ t('common.cancel') }}
          </button>
          <button
            class="group-filter-ok"
            @click="confirmFilter"
          >
            {{ t('common.ok') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.group-filter {
  position: relative;
}

.group-filter-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.15s;
}

.group-filter-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.group-filter-btn.active {
  color: var(--accent);
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

.group-filter-count {
  min-width: 14px;
  height: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 9px;
  font-weight: 600;
  color: var(--accent);
  background: var(--bg-tertiary);
  border-radius: 7px;
  padding: 0 4px;
}

.filter-chevron {
  transition: transform 0.15s;
}

.filter-chevron.open {
  transform: rotate(180deg);
}

.group-filter-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  width: 260px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  z-index: 1000;
  padding: 8px;
}

.group-filter-search {
  display: flex;
  align-items: center;
  gap: 4px;
}

.group-filter-settings {
  padding: 2px 8px;
  background: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text-muted);
  font-size: 11px;
  white-space: nowrap;
  flex-shrink: 0;
  transition: all 0.15s;
}

.group-filter-settings:hover {
  background: var(--bg-hover);
  color: var(--accent);
  border-color: var(--accent);
}

.group-filter-search input {
  flex: 1;
  padding: 4px 8px;
  font-size: 11px;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  outline: none;
  box-sizing: border-box;
}

.group-filter-search input:focus {
  border-color: var(--accent);
}

.group-filter-tree {
  max-height: 240px;
  overflow-y: auto;
  margin: 8px 0;
}

.group-tree-item {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 3px 6px;
  font-size: 11px;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: all 0.1s;
}

.group-tree-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.group-tree-item.selected {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}

.tree-expand {
  width: 12px;
  height: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.tree-expand-placeholder {
  width: 12px;
}

.expand-open {
  transform: rotate(90deg);
}

.tree-checkbox {
  width: 14px;
  height: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
  border: 1px solid var(--border);
  border-radius: 2px;
  flex-shrink: 0;
}

.tree-checkbox.checked {
  color: #fff;
  background: var(--accent);
  border-color: var(--accent);
}

.tree-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.group-filter-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
}

.group-filter-footer-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.group-filter-footer-right {
  display: flex;
  gap: 4px;
}

.group-filter-action {
  font-size: 10px;
  color: var(--text-secondary);
  background: none;
  border: none;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: var(--radius-sm);
}

.group-filter-action:hover {
  color: var(--accent);
  background: var(--bg-hover);
}

.group-filter-cancel {
  padding: 2px 8px;
  font-size: 10px;
  color: var(--text-secondary);
  background: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.group-filter-cancel:hover {
  background: var(--bg-hover);
}

.group-filter-ok {
  padding: 2px 8px;
  font-size: 10px;
  color: #fff;
  background: var(--accent);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.group-filter-ok:hover {
  opacity: 0.9;
}

.group-filter-selected {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-muted);
}
</style>
