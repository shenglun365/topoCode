<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FolderIcon,
  EllipsisVerticalIcon,
  PencilIcon,
  TrashIcon,
  MagnifyingGlassIcon,
  ExclamationTriangleIcon,
  ArchiveBoxXMarkIcon,
} from '@heroicons/vue/24/outline'
import { StarIcon } from '@heroicons/vue/24/solid'
import type { Project, GroupNode } from '@/types/ipc'
import { ipc } from '@/services/ipc'
import { useProjectStore } from '@/stores/project'
import ConfirmDialog from '@/components/shared/ConfirmDialog.vue'
import ClearCacheDialog from './ClearCacheDialog.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PR-002')
const { t } = useI18n()
const projectStore = useProjectStore()

const props = defineProps<{
  project: Project
}>()

// 存储空间统计
const storageStats = ref<{ dbSize: number; sourceSize: number } | null>(null)

async function loadStorageStats() {
  if (!window.api?.project?.getStorageStats) return
  try {
    const stats = await window.api.project.getStorageStats(props.project.id)
    storageStats.value = stats
  } catch (e) {
    // 静默失败
  }
}

onMounted(loadStorageStats)

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`
}

const emit = defineEmits<{
  select: [project: Project]
}>()

// 菜单状态
const menuVisible = ref(false)
const menuPosition = ref({ x: 0, y: 0 })

// 确认弹窗状态
const showDeleteConfirm = ref(false)
const showClearCacheDialog = ref(false)

// 修改信息弹窗
const showEditDialog = ref(false)
const editNameInput = ref('')
const allGroups = ref<GroupNode[]>([])
const selectedGroupIds = ref<string[]>([])

// 路径变更确认弹窗
const showPathConfirm = ref(false)
const pendingNewPath = ref('')
const pathConfirmMessage = ref('')

// 示例项目
const isSample = computed(() => !!props.project.isSample)

function getStatusBadge(status: string): string {
  switch (status) {
    case 'synced': return 'badge-green'
    case 'syncing': return 'badge-yellow'
    case 'error': return 'badge-red'
    default: return 'badge-gray'
  }
}

function getStatusText(status: string): string {
  switch (status) {
    case 'synced': return t('project.synced')
    case 'syncing': return t('project.syncing')
    case 'error': return t('common.error')
    default: return ''
  }
}

function formatTime(timeStr: string | null): string {
  if (!timeStr) return '-'
  const d = new Date(timeStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return t('datetime.justNow')
  if (mins < 60) return `${mins} ${t('datetime.minutesAgo')}`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} ${t('datetime.hoursAgo')}`
  const days = Math.floor(hours / 24)
  return `${days} ${t('datetime.daysAgo')}`
}

// 菜单操作
function showMenu(e: MouseEvent) {
  e.preventDefault()
  e.stopPropagation()
  menuVisible.value = true

  // 菜单尺寸（约 180x240）
  const menuW = 190
  const menuH = 260
  let x = e.clientX
  let y = e.clientY

  // 右边界：超出则左移
  if (x + menuW > window.innerWidth) x = window.innerWidth - menuW - 8
  // 下边界：超出则上移
  if (y + menuH > window.innerHeight) y = window.innerHeight - menuH - 8

  // 保底不超出视口
  if (x < 4) x = 4
  if (y < 4) y = 4

  menuPosition.value = { x, y }
}

function hideMenu() {
  menuVisible.value = false
}

// 收藏/置顶切换
async function toggleFavorite() {
  const newFav = props.project.favorite ? 0 : 1
  await projectStore.updateProjectMeta(props.project.id, { favorite: newFav })
}

async function togglePinned() {
  if (props.project.pinned) {
    // 取消置顶
    await projectStore.updateProjectMeta(props.project.id, { pinned: 0 })
  } else {
    // 检查置顶数量（最多10个）
    const pinnedCount = projectStore.projects.filter(p => p.pinned).length
    if (pinnedCount >= 10) {
      alert(t('project.maxPinnedReached'))
      return
    }
    await projectStore.updateProjectMeta(props.project.id, { pinned: 1 })
  }
}

// 修改信息（名称 + 分组）
async function startEditInfo() {
  hideMenu()
  editNameInput.value = props.project.name
  allGroups.value = await ipc.group.list()
  // 初始化当前项目已选的分组
  selectedGroupIds.value = props.project.groups ? [...props.project.groups] : []
  showEditDialog.value = true
}

function collectAllGroupIds(nodes: GroupNode[]): string[] {
  const ids: string[] = []
  for (const node of nodes) {
    ids.push(node.id)
    if (node.children) {
      ids.push(...collectAllGroupIds(node.children))
    }
  }
  return ids
}

function flattenGroups(nodes: GroupNode[]): GroupNode[] {
  const flat: GroupNode[] = []
  for (const node of nodes) {
    flat.push(node)
    if (node.children) {
      flat.push(...flattenGroups(node.children))
    }
  }
  return flat
}

function toggleGroupSelect(id: string) {
  const idx = selectedGroupIds.value.indexOf(id)
  if (idx >= 0) {
    selectedGroupIds.value.splice(idx, 1)
  } else {
    selectedGroupIds.value.push(id)
  }
}

function handleOpenGroupManagerFromDialog() {
  // 先关闭弹窗，再打开分组管理 tab
  showEditDialog.value = false
  // 等待弹窗关闭动画完成后再打开 tab
  setTimeout(() => {
    projectStore.openGroupManagerTab()
  }, 50)
}

async function confirmEditInfo() {
  const newName = editNameInput.value.trim()
  if (!newName) return

  // 更新名称
  if (newName !== props.project.name) {
    await projectStore.updateProjectMeta(props.project.id, { name: newName })
  }

  // 更新分组（对比当前项目分组）
  const currentGroups = props.project.groups || []
  const newGroups = selectedGroupIds.value
  const hasGroupChange = currentGroups.length !== newGroups.length ||
    !currentGroups.every(id => newGroups.includes(id))

  if (hasGroupChange) {
    // 移除所有旧分组
    for (const gid of currentGroups) {
      if (!newGroups.includes(gid)) {
        await ipc.group.removeProject(props.project.id, gid)
      }
    }
    // 添加新分组
    for (const gid of newGroups) {
      if (!currentGroups.includes(gid)) {
        await ipc.group.addProject(props.project.id, gid)
      }
    }
    // 刷新项目列表以获取最新分组
    await projectStore.loadProjects()
  }

  showEditDialog.value = false
  // 关闭分组管理 tab，回到项目列表
  projectStore.closeGroupManagerTab()
}

// 修改路径（带主目录名校验）
async function handleChangePath() {
  hideMenu()
  if (window.api && window.api.dialog) {
    const path = await window.api.dialog.openDirectory()
    if (path) {
      // 提取新路径的主目录名
      const newDirName = path.split('/').pop() || path
      const currentName = props.project.name

      // 如果新目录名与当前项目名称不一致，弹窗确认
      if (newDirName !== currentName) {
        pendingNewPath.value = path
        pathConfirmMessage.value = `${t('project.pathMismatchHint')}\n\n${t('project.currentName')}: ${currentName}\n${t('project.newDirName')}: ${newDirName}\n\n${t('project.confirmPathChange')}`
        showPathConfirm.value = true
      } else {
        // 一致则直接更新
        try {
          await projectStore.updatePath(props.project.id, path)
          await projectStore.loadProjects()
        } catch (err: any) {
          console.error('Failed to update path:', err)
        }
      }
    }
  }
}

async function confirmPathChange() {
  showPathConfirm.value = false
  try {
    await projectStore.updatePath(props.project.id, pendingNewPath.value)
    await projectStore.loadProjects()
  } catch (err: any) {
    console.error('Failed to update path:', err)
  }
}

async function handleDelete() {
  hideMenu()
  showDeleteConfirm.value = true
}

async function confirmDelete() {
  showDeleteConfirm.value = false
  await projectStore.removeProject(props.project.id)
}

async function handleClearCache() {
  hideMenu()
  showClearCacheDialog.value = true
}

async function onClearCacheDone() {
  showClearCacheDialog.value = false
  await projectStore.loadProjects()
}

async function handleCheckChanges() {
  hideMenu()
  try {
    const result = await projectStore.checkFileChanges(props.project.id)
    if (result.hasChanges) {
      const msg = `${result.added.length} added, ${result.modified.length} modified, ${result.deleted.length} deleted`
      if (confirm(`${msg}\n${t('project.resyncConfirm')}`)) {
        await projectStore.syncProject(props.project.id)
      }
    } else {
      alert(t('project.noChanges'))
    }
  } catch (err) {
    console.error('Failed to check changes:', err)
  }
}

</script>

<template>
  <div
    class="project-card card card-clickable"
    :class="{ 'card-pinned': project.pinned }"
    @click="emit('select', project)"
    @contextmenu="showMenu"
  >
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 头部: 名称 + 语言 + 菜单按钮 -->
    <div
      class="flex justify-between items-center"
      style="margin-bottom:8px;"
    >
      <div
        class="flex items-center gap-2"
        style="min-width:0;"
      >
        <!-- 置顶/收藏标识 -->
        <span
          v-if="project.pinned"
          class="badge badge-pinned shrink-0"
        >{{ t('project.pinnedBadge') }}</span>
        <StarIcon
          v-if="project.favorite"
          class="w-3.5 h-3.5 text-yellow-400 shrink-0"
          :title="t('project.favorited')"
        />
        <FolderIcon class="w-4 h-4 text-accent shrink-0" />
        <span style="font-weight:600; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
          {{ project.name }}
        </span>
        <!-- 分组 badge -->
        <span
          v-if="project.group"
          class="badge badge-purple"
          style="font-size:8px;"
        >{{ project.group }}</span>
        <!-- 示例 badge -->
        <span
          v-if="isSample"
          class="badge badge-blue"
          style="font-size:8px;"
        >{{ t('common.new') }}</span>
        <!-- 状态提示 -->
        <ExclamationTriangleIcon
          v-if="project.needsResync"
          class="w-3.5 h-3.5 text-yellow-500"
          :title="t('project.needsResync')"
        />
        <ExclamationTriangleIcon
          v-else-if="project.hasFileChanges"
          class="w-3.5 h-3.5 text-orange-500"
          :title="t('project.hasFileChanges')"
        />
      </div>
      <div class="flex items-center gap-1">
        <span :class="`badge ${languageBadge(project.language) || 'badge-gray'}`">
          {{ project.language }}
        </span>
        <!-- 操作按钮 -->
        <button
          class="btn btn-ghost btn-icon btn-sm card-menu-btn"
          @click.stop="showMenu($event)"
        >
          <EllipsisVerticalIcon class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- 路径 -->
    <div
      class="text-muted font-mono"
      style="font-size:11px; margin-bottom:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"
    >
      {{ project.rootPath || project.path }}
    </div>

    <div
      class="flex justify-between"
      style="font-size:11px; color:var(--text-muted);"
    >
      <span>{{ project.fileCount }} {{ t('file.files') }}</span>
      <span
        v-if="storageStats"
        :title="t('project.storageSize')"
      >{{ formatBytes(storageStats.dbSize + storageStats.sourceSize) }}</span>
      <span>{{ formatTime(project.lastSync) }}</span>
    </div>

    <!-- 进度条 -->
    <div
      class="progress-bar"
      style="margin-top:8px;"
    >
      <div
        class="progress-bar-fill"
        :style="{ width: project.status === 'synced' ? '100%' : '65%' }"
        :class="{ 'bg-success': project.status === 'synced' }"
      />
    </div>

    <div
      class="flex justify-between items-center"
      style="font-size:10px; color:var(--text-muted); margin-top:4px;"
    >
      <span>
        {{ project.status === 'synced' ? t('project.analysisComplete') : t('project.analysisInProgress') }}
      </span>
      <span
        :class="`badge ${getStatusBadge(project.status)}`"
        style="font-size:8px;"
      >
        {{ getStatusText(project.status) }}
      </span>
    </div>

    <!-- 右键菜单 -->
    <Teleport to="body">
      <div
        v-if="menuVisible"
        class="context-menu"
        :style="{ left: menuPosition.x + 'px', top: menuPosition.y + 'px' }"
        @click.stop
        @mouseleave="hideMenu"
      >
        <!-- 收藏/置顶 -->
        <div
          class="context-menu-item"
          @click="toggleFavorite"
        >
          <StarIcon :class="['w-4 h-4', project.favorite ? 'text-yellow-400' : '']" />
          <span>{{ project.favorite ? t('project.unfavorite') : t('project.favorite') }}</span>
        </div>
        <div
          class="context-menu-item"
          @click="togglePinned"
        >
          <span class="menu-icon-text">{{ project.pinned ? '✕' : '↑' }}</span>
          <span>{{ project.pinned ? t('project.unpin') : t('project.pin') }}</span>
        </div>
        <div class="context-menu-divider" />
        <!-- 修改信息 -->
        <div
          class="context-menu-item"
          @click="startEditInfo"
        >
          <PencilIcon class="w-4 h-4" />
          <span>{{ t('project.editInfo') }}</span>
        </div>
        <!-- 修改路径 -->
        <div
          class="context-menu-item"
          @click="handleChangePath"
        >
          <PencilIcon class="w-4 h-4" />
          <span>{{ t('project.changePath') }}</span>
        </div>
        <!-- 检查变更 -->
        <div
          class="context-menu-item"
          @click="handleCheckChanges"
        >
          <MagnifyingGlassIcon class="w-4 h-4" />
          <span>{{ t('project.checkChanges') }}</span>
        </div>
        <div class="context-menu-divider" />
        <!-- 清除缓存 -->
        <div
          v-if="!isSample"
          class="context-menu-item context-menu-item-warning"
          @click="handleClearCache"
        >
          <ArchiveBoxXMarkIcon class="w-4 h-4" />
          <span>{{ t('project.clearCache') }}</span>
        </div>
        <div class="context-menu-divider" />
        <!-- 删除 -->
        <div
          v-if="!isSample"
          class="context-menu-item context-menu-item-danger"
          @click="handleDelete"
        >
          <TrashIcon class="w-4 h-4" />
          <span>{{ t('common.delete') }}</span>
        </div>
      </div>
    </Teleport>

    <!-- 点击卡片其他区域关闭菜单 -->
    <div
      v-if="menuVisible"
      class="context-menu-backdrop"
      @click="hideMenu"
    />

    <!-- 删除确认弹窗 -->
    <ConfirmDialog
      v-model:visible="showDeleteConfirm"
      :title="t('common.delete')"
      :message="t('common.confirmDelete')"
      variant="danger"
      @confirm="confirmDelete"
    />

    <!-- 清除缓存 - 选择数据项弹窗 -->
    <ClearCacheDialog
      v-if="showClearCacheDialog"
      :project-id="project.id"
      @close="onClearCacheDone"
    />

    <!-- 修改信息弹窗 -->
    <ConfirmDialog
      v-model:visible="showEditDialog"
      :title="t('project.editInfo')"
      variant="info"
      @confirm="confirmEditInfo"
    >
      <template #message>
        <div class="edit-info-dialog">
          <div class="edit-info-field">
            <label class="edit-info-label">{{ t('project.projectName') || '项目名称' }}</label>
            <input
              v-model="editNameInput"
              class="edit-info-input"
              :placeholder="t('project.projectNamePlaceholder')"
              autofocus
              @keydown.enter="confirmEditInfo"
            >
          </div>
          <div class="edit-info-field">
            <label class="edit-info-label">{{ t('project.editGroups') }}</label>
            <div
              v-if="allGroups.length === 0"
              class="edit-info-no-groups"
            >
              <span class="text-muted">{{ t('project.noGroupsAvailable') }}</span>
              <button
                class="edit-info-set-groups-btn"
                @click="handleOpenGroupManagerFromDialog"
              >
                {{ t('group.setGroups') }}
              </button>
            </div>
            <div
              v-else
              class="edit-info-group-list"
            >
              <label
                v-for="group in flattenGroups(allGroups)"
                :key="group.id"
                class="edit-info-group-item"
              >
                <input
                  type="checkbox"
                  :checked="selectedGroupIds.includes(group.id)"
                  @change="toggleGroupSelect(group.id)"
                >
                <span :style="{ paddingLeft: (group.depth || 0) * 12 + 'px' }">{{ group.name }}</span>
              </label>
            </div>
          </div>
        </div>
      </template>
    </ConfirmDialog>

    <!-- 路径变更确认弹窗 -->
    <ConfirmDialog
      v-model:visible="showPathConfirm"
      :title="t('project.changePath')"
      :message="pathConfirmMessage"
      variant="warning"
      :confirm-label="t('project.confirmUpdate')"
      @confirm="confirmPathChange"
    />
  </div>
</template>

<script lang="ts">
function languageBadge(lang: string): string {
  const map: Record<string, string> = {
    TypeScript: 'badge-blue',
    JavaScript: 'badge-yellow',
    Python: 'badge-green',
    Go: 'badge-cyan',
    Rust: 'badge-orange',
    Java: 'badge-red',
    Vue: 'badge-emerald',
    HTML: 'badge-orange',
    C: 'badge-blue',
    'C++': 'badge-purple',
  }
  return map[lang] || 'badge-gray'
}
</script>

<style scoped>
.project-card {
  padding: 14px;
  position: relative;
}

.project-card.card-pinned {
  border: 1px solid var(--accent);
}

.bg-success .progress-bar-fill {
  background: var(--success);
}

.card-menu-btn {
  opacity: 0;
  transition: opacity 0.15s;
}

.project-card:hover .card-menu-btn {
  opacity: 1;
}

.rename-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 13px;
  font-family: inherit;
  outline: none;
  margin-top: 8px;
}

.rename-input:focus {
  border-color: var(--accent);
}

.edit-info-dialog {
  width: 100%;
}

.edit-info-field {
  margin-bottom: 12px;
}

.edit-info-field:last-child {
  margin-bottom: 0;
}

.edit-info-label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 6px;
}

.edit-info-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 13px;
  font-family: inherit;
  outline: none;
}

.edit-info-input:focus {
  border-color: var(--accent);
}

.edit-info-no-groups {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
}

.edit-info-set-groups-btn {
  padding: 4px 10px;
  font-size: 11px;
  background: var(--accent);
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}

.edit-info-set-groups-btn:hover {
  opacity: 0.9;
}

.edit-info-group-list {
  max-height: 160px;
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 4px;
}

.edit-info-group-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  font-size: 12px;
  color: var(--text-primary);
  cursor: pointer;
  border-radius: 4px;
}

.edit-info-group-item:hover {
  background: var(--bg-hover);
}

.edit-info-group-item input[type="checkbox"] {
  accent-color: var(--accent);
}
</style>

<style>
.context-menu {
  position: fixed;
  z-index: 9999;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 4px;
  min-width: 180px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
}

.context-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  font-size: 12px;
  color: var(--text-primary);
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.1s;
}

.context-menu-item:hover {
  background: var(--bg-hover);
}

.context-menu-item.disabled {
  opacity: 0.5;
  pointer-events: none;
}

.context-menu-item-danger {
  color: #ef4444;
}

.context-menu-item-danger:hover {
  background: color-mix(in srgb, #ef4444 10%, transparent);
}

.context-menu-item-warning {
  color: #f59e0b;
}

.context-menu-item-warning:hover {
  background: color-mix(in srgb, #f59e0b 10%, transparent);
}

.context-menu-divider {
  height: 1px;
  background: var(--border);
  margin: 4px 0;
}

.context-menu-backdrop {
  position: fixed;
  inset: 0;
  z-index: 9998;
}

.badge-pinned {
  display: inline-block;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 700;
  line-height: 1.4;
  border-radius: 3px;
  background: var(--accent);
  color: #fff;
}

.menu-icon-text {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  font-size: 11px;
  font-weight: 700;
}


.cache-processing-card {
  background: var(--bg-primary);
  border-radius: 12px;
  padding: 32px 40px;
  text-align: center;
  min-width: 280px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.2);
}
.cache-processing-spinner {
  width: 32px;
  height: 32px;
  margin: 0 auto 16px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.cache-processing-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 8px;
}
.cache-processing-message {
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 16px;
}
</style>
