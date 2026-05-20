<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FolderIcon,
  EllipsisVerticalIcon,
  PencilIcon,
  TrashIcon,
  MagnifyingGlassIcon,
  ExclamationTriangleIcon,
  ArchiveBoxXMarkIcon,
  StarIcon,
  BookmarkSquareIcon,
} from '@heroicons/vue/24/outline'
import type { Project } from '@/types/ipc'
import { useProjectStore } from '@/stores/project'
import ConfirmDialog from '@/components/shared/ConfirmDialog.vue'

const { t } = useI18n()
const projectStore = useProjectStore()

const props = defineProps<{
  project: Project
}>()

const emit = defineEmits<{
  select: [project: Project]
}>()

// 菜单状态
const menuVisible = ref(false)
const menuPosition = ref({ x: 0, y: 0 })

// 确认弹窗状态
const showDeleteConfirm = ref(false)
const showClearCacheConfirm = ref(false)
const isClearingCache = ref(false)

// 修改名称弹窗
const showRenameDialog = ref(false)
const newNameInput = ref('')

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

// 修改名称
function startRename() {
  hideMenu()
  newNameInput.value = props.project.name
  showRenameDialog.value = true
}

async function confirmRename() {
  const newName = newNameInput.value.trim()
  if (!newName) return
  if (newName === props.project.name) {
    showRenameDialog.value = false
    return
  }
  await projectStore.updateProjectMeta(props.project.id, { name: newName })
  showRenameDialog.value = false
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
  showClearCacheConfirm.value = true
}

async function confirmClearCache() {
  showClearCacheConfirm.value = false
  isClearingCache.value = true
  try {
    const result = await projectStore.clearProjectCache(props.project.id)
    console.group(`${t('project.clearCache')} 完成`)
    console.log(`  删除 ${result.deletedTasks} 个分析任务`)
    console.log(`  保留 ${result.fileCount} 个源文件`)
    if (result.deletedTables) {
      for (const [table, count] of Object.entries(result.deletedTables)) {
        console.log(`  [${table}] 删除 ${count} 条记录`)
      }
    }
    console.groupEnd()
  } catch (err: any) {
    console.error('Failed to clear cache:', err)
  } finally {
    isClearingCache.value = false
  }
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
    <!-- 头部: 名称 + 语言 + 菜单按钮 -->
    <div class="flex justify-between items-center" style="margin-bottom:8px;">
      <div class="flex items-center gap-2" style="min-width:0;">
        <!-- 置顶/收藏图标 -->
        <BookmarkSquareIcon v-if="project.pinned" class="w-4 h-4 text-accent shrink-0" :title="t('project.pinned')" />
        <StarIcon v-if="project.favorite" class="w-3.5 h-3.5 text-yellow-400 shrink-0" :title="t('project.favorited')" />
        <FolderIcon class="w-4 h-4 text-accent shrink-0" />
        <span style="font-weight:600; font-size:13px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
          {{ project.name }}
        </span>
        <!-- 分组 badge -->
        <span v-if="project.group" class="badge badge-purple" style="font-size:8px;">{{ project.group }}</span>
        <!-- 示例 badge -->
        <span v-if="isSample" class="badge badge-blue" style="font-size:8px;">{{ t('common.new') }}</span>
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
    <div class="text-muted font-mono" style="font-size:11px; margin-bottom:4px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
      {{ project.rootPath || project.path }}
    </div>

    <div class="flex justify-between" style="font-size:11px; color:var(--text-muted);">
      <span>{{ project.fileCount }} {{ t('file.files') }}</span>
      <span>{{ formatTime(project.lastSync) }}</span>
    </div>

    <!-- 进度条 -->
    <div class="progress-bar" style="margin-top:8px;">
      <div
        class="progress-bar-fill"
        :style="{ width: project.status === 'synced' ? '100%' : '65%' }"
        :class="{ 'bg-success': project.status === 'synced' }"
      ></div>
    </div>

    <div class="flex justify-between items-center" style="font-size:10px; color:var(--text-muted); margin-top:4px;">
      <span>
        {{ project.status === 'synced' ? t('project.analysisComplete') : t('project.analysisInProgress') }}
      </span>
      <span :class="`badge ${getStatusBadge(project.status)}`" style="font-size:8px;">
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
        <div class="context-menu-item" @click="toggleFavorite">
          <StarIcon class="w-4 h-4" />
          <span>{{ project.favorite ? t('project.unfavorite') : t('project.favorite') }}</span>
        </div>
        <div class="context-menu-item" @click="togglePinned">
          <BookmarkSquareIcon class="w-4 h-4" />
          <span>{{ project.pinned ? t('project.unpin') : t('project.pin') }}</span>
        </div>
        <div class="context-menu-divider"></div>
        <!-- 修改名称 -->
        <div class="context-menu-item" @click="startRename">
          <PencilIcon class="w-4 h-4" />
          <span>{{ t('project.rename') }}</span>
        </div>
        <!-- 修改路径 -->
        <div class="context-menu-item" @click="handleChangePath">
          <PencilIcon class="w-4 h-4" />
          <span>{{ t('project.changePath') }}</span>
        </div>
        <!-- 检查变更 -->
        <div class="context-menu-item" @click="handleCheckChanges">
          <MagnifyingGlassIcon class="w-4 h-4" />
          <span>{{ t('project.checkChanges') }}</span>
        </div>
        <div class="context-menu-divider"></div>
        <!-- 清除缓存 -->
        <div
          v-if="!isSample"
          class="context-menu-item context-menu-item-warning"
          @click="handleClearCache"
        >
          <ArchiveBoxXMarkIcon class="w-4 h-4" />
          <span>{{ t('project.clearCache') }}</span>
        </div>
        <div class="context-menu-divider"></div>
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
    ></div>

    <!-- 删除确认弹窗 -->
    <ConfirmDialog
      v-model:visible="showDeleteConfirm"
      :title="t('common.delete')"
      :message="t('common.confirmDelete')"
      variant="danger"
      @confirm="confirmDelete"
    />

    <!-- 清除缓存确认弹窗 -->
    <ConfirmDialog
      v-model:visible="showClearCacheConfirm"
      :title="t('project.clearCache')"
      :message="t('project.clearCacheConfirm').replace('{name}', project.name)"
      variant="warning"
      :confirm-label="t('project.clearCache')"
      @confirm="confirmClearCache"
    />

    <!-- 修改名称弹窗 -->
    <ConfirmDialog
      v-model:visible="showRenameDialog"
      :title="t('project.rename')"
      variant="info"
      @confirm="confirmRename"
    >
      <template #message>
        <input
          v-model="newNameInput"
          class="rename-input"
          :placeholder="t('project.projectNamePlaceholder')"
          @keydown.enter="confirmRename"
          autofocus
        />
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
</style>
