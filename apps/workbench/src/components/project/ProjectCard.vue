<script setup lang="ts">
import { ref, computed, provide } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FolderIcon,
  BookOpenIcon,
  ArrowPathIcon,
  EllipsisVerticalIcon,
  PencilIcon,
  TrashIcon,
  MagnifyingGlassIcon,
  ExclamationTriangleIcon,
  ArchiveBoxXMarkIcon,
  XMarkIcon,
  CheckIcon,
  DocumentPlusIcon,
  DocumentMinusIcon,
} from '@heroicons/vue/24/outline'
import { StarIcon, ArrowUpOnSquareIcon } from '@heroicons/vue/24/solid'
import type { Project, GroupNode } from '@/types/ipc'
import { ipc } from '@/services/ipc'
import { getProjectStatusBadge } from '@/utils/statusBadge'
import { languageBadge } from '@/utils/languageBadge'
import ProjectContextMenu from './ProjectContextMenu.vue'
import { useProjectStore } from '@/stores/project'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ClearCacheDialog from './ClearCacheDialog.vue'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PR-002')
const { t } = useI18n()
const projectStore = useProjectStore()

import { useCardState } from './project-view/useCardState'
import { useCardMenu } from './project-view/useCardMenu'
import { useCardEdit } from './project-view/useCardEdit'
import { useCardActions } from './project-view/useCardActions'
import type { CardDeps } from './project-view/chatTypes'
import { WS_KEY } from './project-view/key'
import ProjectMainPanel from './project-view/panels/ProjectMainPanel.vue'

const emit = defineEmits<{
  select: [project: Project]
}>()

const props = defineProps<{
  project: Project
}>()

// 存储空间统计（主库缓存列，由 project.list 一次返回，避免逐项目开库）
const storageTotal = computed(() => {
  const db = props.project.dbSizeBytes ?? 0
  const src = props.project.sourceSizeBytes ?? 0
  return (db || src) ? db + src : 0
})

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`
}

// ---- MS6-W3: 逻辑层4域(project-view/)——本文件保留 props/emit/模板 ----
const D: CardDeps = { props, emit }
D.state = useCardState(D)
D.menu = useCardMenu(D)
D.edit = useCardEdit(D)
D.actions = useCardActions(D)
const ws = Object.assign({}, D.state, D.menu, D.edit, D.actions)
provide(WS_KEY, ws)
const {
  allGroups,
  changesActiveTab,
  changesDialogVisible,
  changesError,
  changesLoading,
  changesResult,
  collectAllGroupIds,
  confirmDelete,
  confirmEditInfo,
  confirmPathChange,
  deletePct,
  deletePhaseLabel,
  editBranch,
  editHead,
  editLocalRepoPath,
  editNameInput,
  editRemoteUrl,
  flattenGroups,
  handleChangePath,
  handleCheckChanges,
  handleClearCache,
  handleDelete,
  handleDeleteBackup,
  handleOpenGroupManagerFromDialog,
  handleResetProject,
  handleResyncFromDialog,
  hideMenu,
  isDeleting,
  isResourceProject,
  isSample,
  menuPosition,
  menuVisible,
  onClearCacheDone,
  onVersionUpdated,
  pathConfirmMessage,
  pendingNewPath,
  pinnedWarning,
  pinnedWarningTimer,
  selectedGroupIds,
  showClearCacheDialog,
  showDeleteConfirm,
  showEditDialog,
  showMenu,
  showPathConfirm,
  startEditInfo,
  startVersionUpdate,
  toggleFavorite,
  toggleGroupSelect,
  togglePinned,
} = ws
provide(WS_KEY, ws)

// 菜单状态

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

</script>

<template>
  <ProjectMainPanel :project="props.project" @select="(p: any) => emit('select', p)" />
</template>
