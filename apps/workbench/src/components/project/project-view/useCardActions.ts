/**
 * useCard · actions 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { ref } from 'vue'
import { useProjectStore } from '@/stores/project'
import { ipc } from '@/services/ipc'

interface SyncCommit { hash: string; short: string; author: string; date: number; message: string }
import { useI18n } from 'vue-i18n'

import type { CardDeps } from './chatTypes'

export function useCardActions(D: CardDeps) {
  const projectStore = useProjectStore()
  const { t } = useI18n()
  const props = D.props

async function handleDelete() {
  D.menu.hideMenu()
  D.state.showDeleteConfirm.value = true
}

async function confirmDelete() {
  D.state.showDeleteConfirm.value = false
  await projectStore.removeProject(props.project.id)
}

async function handleClearCache() {
  D.menu.hideMenu()
  D.state.showClearCacheDialog.value = true
}

async function handleResetProject() {
  D.menu.hideMenu()
  const resourceId = props.project.id?.replace('TOPORES_ID:', '')
  if (!resourceId) return
  try {
    await (window.api as any)?.system?.importProjectArchive?.('reimport:' + resourceId)
    console.log('[ProjectCard] reset project:', resourceId)
    await projectStore.loadProjects()
  } catch (e) {
    console.error('[ProjectCard] reset failed:', e)
  }
}

async function handleDeleteBackup() {
  D.menu.hideMenu()
  const resourceId = props.project.id?.replace('TOPORES_ID:', '')
  if (!resourceId) return
  try {
    await (window.api as any)?.system?.importProjectArchive?.('delete_backup:' + resourceId)
    console.log('[ProjectCard] delete backup:', resourceId)
    await projectStore.loadProjects()
  } catch (e) {
    console.error('[ProjectCard] delete backup failed:', e)
  }
}

async function onClearCacheDone() {
  D.state.showClearCacheDialog.value = false
  await projectStore.loadProjects()
}

// ── 更新目标选择(分支/提交): 变更检查弹窗内可选, 缺省=源 HEAD ──
const syncBranches = ref<string[]>([])
const syncBranch = ref('')
const syncCommits = ref<SyncCommit[]>([])
const syncHead = ref('')
const syncTargetLoading = ref(false)

/** 打开变更检查弹窗时懒加载分支列表; 切分支时加载该分支提交列表。 */
async function loadSyncBranches() {
  syncTargetLoading.value = true
  try {
    const r = await ipc.project.listSourceBranches(props.project.id)
    syncBranches.value = r?.branches || []
    syncBranch.value = r?.current || syncBranches.value[0] || ''
    await loadSyncCommits()
  } catch { syncBranches.value = [] } finally { syncTargetLoading.value = false }
}

async function loadSyncCommits() {
  syncTargetLoading.value = true
  syncHead.value = ''
  try {
    const r = await ipc.project.listSourceCommits(props.project.id, syncBranch.value || undefined)
    syncCommits.value = r?.commits || []
  } catch { syncCommits.value = [] } finally { syncTargetLoading.value = false }
}

function pickSyncBranch(b: string) {
  if (b !== syncBranch.value) { syncBranch.value = b; loadSyncCommits() }
}

async function handleCheckChanges() {
  D.menu.hideMenu()
  D.state.changesLoading.value = true
  D.state.changesResult.value = null
  D.state.changesError.value = null
  D.state.changesDialogVisible.value = true
  try {
    const result = await projectStore.checkFileChanges(props.project.id)
    D.state.changesResult.value = result
    loadSyncBranches()
  } catch (err: any) {
    console.error('Failed to check changes:', err)
    D.state.changesError.value = err?.message || t('project.changes.checkFailed')
  } finally {
    D.state.changesLoading.value = false
  }
}

async function handleResyncFromDialog() {
  D.state.changesLoading.value = true
  try {
    await projectStore.syncProject(
      props.project.id,
      syncBranch.value || undefined,
      syncHead.value || undefined)
    // 更新后重查: 镜像已对齐 → 应显示无变更(head 变化时旧分析数据已自动清除)
    const result = await projectStore.checkFileChanges(props.project.id)
    D.state.changesResult.value = result
  } catch (err: any) {
    console.error('Failed to resync:', err)
    D.state.changesError.value = err?.message || t('project.changes.checkFailed')
  } finally {
    D.state.changesLoading.value = false
  }
}

  return {
    confirmDelete,
    handleCheckChanges,
    syncBranches, syncBranch, syncCommits, syncHead, syncTargetLoading,
    loadSyncBranches, loadSyncCommits, pickSyncBranch,
    handleClearCache,
    handleDelete,
    handleDeleteBackup,
    handleResetProject,
    handleResyncFromDialog,
    onClearCacheDone,
  }
}
