/**
 * useCard · state 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { useProjectStore } from '@/stores/project'
import { ref, computed } from 'vue'
import type { GroupNode } from '@/types/ipc'
import { useI18n } from 'vue-i18n'

import type { CardDeps } from './chatTypes'

export function useCardState(D: CardDeps) {
  const projectStore = useProjectStore()
  const { t } = useI18n()
  const props = D.props

const menuVisible = ref(false)
const menuPosition = ref({ x: 0, y: 0 })
const pinnedWarning = ref(false)
let pinnedWarningTimer: ReturnType<typeof setTimeout> | null = null

const changesDialogVisible = ref(false)
const changesLoading = ref(false)
const changesResult = ref<{ added: string[]; modified: string[]; deleted: string[]; hasChanges: boolean; sourceHead?: string; mirrorHead?: string; branch?: string; note?: string } | null>(null)
const changesError = ref<string | null>(null)
const changesActiveTab = ref<'added' | 'modified' | 'deleted'>('modified')

// 确认弹窗状态
const showDeleteConfirm = ref(false)
const showClearCacheDialog = ref(false)

// 修改信息弹窗
const showEditDialog = ref(false)
const editNameInput = ref('')
const editRemoteUrl = ref('')
const editLocalRepoPath = ref('')
const editBranch = ref('')
const editHead = ref('')
const allGroups = ref<GroupNode[]>([])
const selectedGroupIds = ref<string[]>([])

// 路径变更确认弹窗
const showPathConfirm = ref(false)
const pendingNewPath = ref('')
const pathConfirmMessage = ref('')

// 示例项目
const isSample = computed(() => !!props.project.isSample)

// 删除进度（后端后台删除，卡片内联反馈）
const isDeleting = computed(() => projectStore.deleteProgress?.id === props.project.id)
const deletePct = computed(() => projectStore.deleteProgress?.progress ?? 0)
const deletePhaseLabel = computed(() => {
  const phase = projectStore.deleteProgress?.phase || ''
  const map: Record<string, string> = {
    prepare: t('project.deletePhase.prepare'),
    tasks: t('project.deletePhase.tasks'),
    database: t('project.deletePhase.database'),
    source: t('project.deletePhase.source'),
    record: t('project.deletePhase.record'),
  }
  return map[phase] || t('project.deleting')
})

// 资源中心导入的项目
const isResourceProject = computed(() => props.project.id?.startsWith?.('TOPORES_ID:'))

  return {
    allGroups,
    changesActiveTab,
    changesDialogVisible,
    changesError,
    changesLoading,
    changesResult,
    deletePct,
    deletePhaseLabel,
    editBranch,
    editHead,
    editLocalRepoPath,
    editNameInput,
    editRemoteUrl,
    isDeleting,
    isResourceProject,
    isSample,
    menuPosition,
    menuVisible,
    pathConfirmMessage,
    pendingNewPath,
    pinnedWarning,
    pinnedWarningTimer,
    selectedGroupIds,
    showClearCacheDialog,
    showDeleteConfirm,
    showEditDialog,
    showPathConfirm,
  }
}
