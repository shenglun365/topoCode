<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PlusIcon,
  PencilIcon,
  TrashIcon,
  ChevronRightIcon,
  FolderIcon,
  ExclamationTriangleIcon,
} from '@heroicons/vue/24/outline'
import type { GroupNode } from '@/types/ipc'
import { ipc } from '@/services/ipc'
import { useProjectStore } from '@/stores/project'
import ConfirmDialog from '@/components/shared/ConfirmDialog.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PR-006')
const { t } = useI18n()
const projectStore = useProjectStore()

const groups = ref<GroupNode[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const showEditDialog = ref(false)
const showDeleteConfirm = ref(false)
const showDepthWarning = ref(false)

const newName = ref('')
const editId = ref<string | null>(null)
const editName = ref('')
const selectedParentId = ref<string | null>(null)
const deleteGroupId = ref<string | null>(null)

// 扁平化分组列表用于选择父分组
const flatGroups = computed(() => {
  const result: GroupNode[] = []
  function flatten(nodeList: GroupNode[], depth: number) {
    for (const node of nodeList) {
      result.push({ ...node, depth })
      if (node.children && node.children.length > 0) {
        flatten(node.children, depth + 1)
      }
    }
  }
  flatten(groups.value, 0)
  return result
})

async function loadGroups() {
  loading.value = true
  try {
    groups.value = await ipc.group.list()
  } catch (err) {
    console.error('Failed to load groups:', err)
  } finally {
    loading.value = false
  }
}

function startCreate() {
  newName.value = ''
  selectedParentId.value = null
  showCreateDialog.value = true
}

function startEdit(group: GroupNode) {
  editId.value = group.id
  editName.value = group.name
  showEditDialog.value = true
}

function startDelete(group: GroupNode) {
  deleteGroupId.value = group.id
  showDeleteConfirm.value = true
}

async function confirmCreate() {
  if (!newName.value.trim()) return
  try {
    if (selectedParentId.value) {
      const parent = findGroupById(groups.value, selectedParentId.value)
      if (parent && parent.depth >= 3) {
        showDepthWarning.value = true
        return
      }
    }
    await ipc.group.create(newName.value.trim(), selectedParentId.value)
    showCreateDialog.value = false
    await loadGroups()
  } catch (err: any) {
    alert(err.message || t('group.createFailed'))
  }
}

async function confirmEdit() {
  if (!editId.value || !editName.value.trim()) return
  try {
    await ipc.group.update(editId.value, editName.value.trim())
    showEditDialog.value = false
    await loadGroups()
  } catch (err: any) {
    alert(err.message || t('group.updateFailed'))
  }
}

async function confirmDelete() {
  if (!deleteGroupId.value) return
  try {
    await ipc.group.delete(deleteGroupId.value)
    showDeleteConfirm.value = false
    await loadGroups()
  } catch (err: any) {
    alert(err.message || t('group.deleteFailed'))
  }
}

function findGroupById(nodeList: GroupNode[], id: string): GroupNode | null {
  for (const node of nodeList) {
    if (node.id === id) return node
    if (node.children) {
      const found = findGroupById(node.children, id)
      if (found) return found
    }
  }
  return null
}

function getProjectCount(groupId: string): number {
  // 统计该分组及其子分组下的项目数
  const allGroupIds = collectGroupIds(groupId)
  return projectStore.projects.filter(p => {
    const pGroups = p.groups || []
    return allGroupIds.some(gid => pGroups.includes(gid))
  }).length
}

function collectGroupIds(groupId: string): string[] {
  const group = findGroupById(groups.value, groupId)
  const ids = [groupId]
  if (group?.children) {
    for (const child of group.children) {
      ids.push(...collectGroupIds(child.id))
    }
  }
  return ids
}

function renderTreeItem(group: GroupNode, depth: number) {
  const indent = depth * 16
  const hasChildren = group.children && group.children.length > 0
  const isExpanded = true // 默认全部展开

  return { group, indent, hasChildren, isExpanded }
}

onMounted(() => {
  loadGroups()
})

defineExpose({ loadGroups })
</script>

<template>
  <div class="group-manager">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 工具栏（新建按钮） -->
    <div class="group-manager-toolbar">
      <div />
      <button
        class="btn-primary-sm"
        @click="startCreate"
      >
        <PlusIcon class="w-3.5 h-3.5" />
        <span>{{ t('group.newGroup') }}</span>
      </button>
    </div>

    <!-- 分组树 -->
    <div class="group-manager-tree">
      <div
        v-if="loading"
        class="group-manager-empty"
      >
        {{ t('common.loading') }}
      </div>
      <div
        v-else-if="groups.length === 0"
        class="group-manager-empty"
      >
        <FolderIcon class="w-8 h-8 text-muted" />
        <p>{{ t('group.emptyHint') }}</p>
        <p class="group-manager-hint">
          {{ t('group.depthHint') }}
        </p>
      </div>
      <div v-else>
        <div
          v-for="group in groups"
          :key="group.id"
        >
          <div
            class="group-tree-node"
            @click="startEdit(group)"
          >
            <span
              class="group-tree-indent"
              :style="{ width: group.depth * 16 + 'px' }"
            />
            <FolderIcon class="w-4 h-4 group-icon" />
            <span class="group-name">{{ group.name }}</span>
            <span class="group-count">{{ getProjectCount(group.id) }}</span>
            <div class="group-actions">
              <button
                class="group-action-btn"
                :title="t('common.edit')"
                @click.stop="startEdit(group)"
              >
                <PencilIcon class="w-3.5 h-3.5" />
              </button>
              <button
                class="group-action-btn group-action-danger"
                :title="t('common.delete')"
                @click.stop="startDelete(group)"
              >
                <TrashIcon class="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
          <!-- 子节点 -->
          <div v-if="group.children && group.children.length > 0">
            <div
              v-for="child in group.children"
              :key="child.id"
            >
              <div
                class="group-tree-node"
                @click="startEdit(child)"
              >
                <span
                  class="group-tree-indent"
                  :style="{ width: child.depth * 16 + 'px' }"
                />
                <FolderIcon class="w-4 h-4 group-icon" />
                <span class="group-name">{{ child.name }}</span>
                <span class="group-count">{{ getProjectCount(child.id) }}</span>
                <div class="group-actions">
                  <button
                    class="group-action-btn"
                    :title="t('common.edit')"
                    @click.stop="startEdit(child)"
                  >
                    <PencilIcon class="w-3.5 h-3.5" />
                  </button>
                  <button
                    class="group-action-btn group-action-danger"
                    :title="t('common.delete')"
                    @click.stop="startDelete(child)"
                  >
                    <TrashIcon class="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
              <!-- 递归渲染更深层级 -->
              <div v-if="child.children && child.children.length > 0">
                <div
                  v-for="gc in child.children"
                  :key="gc.id"
                  class="group-tree-node"
                  @click="startEdit(gc)"
                >
                  <span
                    class="group-tree-indent"
                    :style="{ width: gc.depth * 16 + 'px' }"
                  />
                  <FolderIcon class="w-4 h-4 group-icon" />
                  <span class="group-name">{{ gc.name }}</span>
                  <span class="group-count">{{ getProjectCount(gc.id) }}</span>
                  <div class="group-actions">
                    <button
                      class="group-action-btn"
                      :title="t('common.edit')"
                      @click.stop="startEdit(gc)"
                    >
                      <PencilIcon class="w-3.5 h-3.5" />
                    </button>
                    <button
                      class="group-action-btn group-action-danger"
                      :title="t('common.delete')"
                      @click.stop="startDelete(gc)"
                    >
                      <TrashIcon class="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 创建分组对话框 -->
    <div
      v-if="showCreateDialog"
      class="dialog-overlay"
      @click="showCreateDialog = false"
    >
      <div
        class="dialog-content"
        @click.stop
      >
        <h3>{{ t('group.newGroup') }}</h3>
        <div class="dialog-field">
          <label>{{ t('group.groupName') }}</label>
          <input
            v-model="newName"
            :placeholder="t('group.namePlaceholder')"
            type="text"
            autofocus
            @keyup.enter="confirmCreate"
          >
        </div>
        <div class="dialog-field">
          <label>{{ t('group.parentGroup') }}</label>
          <select v-model="selectedParentId">
            <option :value="null">
              {{ t('group.noParent') }}
            </option>
            <option
              v-for="g in flatGroups"
              :key="g.id"
              :value="g.id"
              :disabled="g.depth >= 3"
            >
              {{ '  '.repeat(g.depth) }}{{ g.name }}
            </option>
          </select>
        </div>
        <div class="dialog-footer">
          <button
            class="btn-secondary-sm"
            @click="showCreateDialog = false"
          >
            {{ t('common.cancel') }}
          </button>
          <button
            class="btn-primary-sm"
            @click="confirmCreate"
          >
            {{ t('common.create') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 编辑分组对话框 -->
    <div
      v-if="showEditDialog"
      class="dialog-overlay"
      @click="showEditDialog = false"
    >
      <div
        class="dialog-content"
        @click.stop
      >
        <h3>{{ t('common.edit') }}</h3>
        <div class="dialog-field">
          <label>{{ t('group.groupName') }}</label>
          <input
            v-model="editName"
            :placeholder="t('group.namePlaceholder')"
            type="text"
            autofocus
            @keyup.enter="confirmEdit"
          >
        </div>
        <div class="dialog-footer">
          <button
            class="btn-secondary-sm"
            @click="showEditDialog = false"
          >
            {{ t('common.cancel') }}
          </button>
          <button
            class="btn-primary-sm"
            @click="confirmEdit"
          >
            {{ t('common.save') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 删除确认对话框 -->
    <ConfirmDialog
      v-model:visible="showDeleteConfirm"
      :title="t('common.deleteConfirm')"
      :message="t('group.deleteConfirm')"
      @confirm="confirmDelete"
    />

    <!-- 层级深度警告 -->
    <div
      v-if="showDepthWarning"
      class="dialog-overlay"
      @click="showDepthWarning = false"
    >
      <div
        class="dialog-content"
        @click.stop
      >
        <div class="dialog-warning">
          <ExclamationTriangleIcon class="w-8 h-8" />
          <h3>{{ t('group.depthLimit') }}</h3>
          <p>{{ t('group.depthHint') }}</p>
        </div>
        <div class="dialog-footer">
          <button
            class="btn-primary-sm"
            @click="showDepthWarning = false"
          >
            {{ t('common.close') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.group-manager {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.group-manager-toolbar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.btn-primary-sm {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 500;
  color: #fff;
  background: var(--accent);
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.15s;
}

.btn-primary-sm:hover {
  opacity: 0.9;
}

.btn-secondary-sm {
  padding: 4px 10px;
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all 0.15s;
}

.btn-secondary-sm:hover {
  background: var(--bg-hover);
}

.group-manager-tree {
  flex: 1;
  overflow-y: auto;
  padding: 8px 16px;
}

.group-manager-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 24px;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}

.group-manager-hint {
  font-size: 10px;
  margin-top: 8px;
  color: var(--text-muted);
}

.group-tree-node {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  margin: 2px 0;
  font-size: 12px;
  color: var(--text-secondary);
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: all 0.1s;
}

.group-tree-node:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.group-tree-indent {
  flex-shrink: 0;
}

.group-icon {
  flex-shrink: 0;
  color: var(--accent);
}

.group-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.group-count {
  font-size: 10px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.group-actions {
  display: flex;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.15s;
}

.group-tree-node:hover .group-actions {
  opacity: 1;
}

.group-action-btn {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: none;
  border: none;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text-muted);
  transition: all 0.1s;
}

.group-action-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

.group-action-danger:hover {
  color: #ef4444;
}

/* 对话框样式 */
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.dialog-content {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px;
  min-width: 320px;
  max-width: 400px;
}

.dialog-content h3 {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 12px 0;
}

.dialog-field {
  margin-bottom: 12px;
}

.dialog-field label {
  display: block;
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.dialog-field input,
.dialog-field select {
  width: 100%;
  padding: 6px 8px;
  font-size: 12px;
  color: var(--text-primary);
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  outline: none;
  box-sizing: border-box;
}

.dialog-field input:focus,
.dialog-field select:focus {
  border-color: var(--accent);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
}

.dialog-warning {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  color: #f59e0b;
  text-align: center;
}

.dialog-warning h3 {
  color: #f59e0b;
}

.dialog-warning p {
  font-size: 11px;
  color: var(--text-secondary);
  margin: 0;
}
</style>
