/**
 * useCard · actions 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { useProjectStore } from '@/stores/project'
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

async function handleCheckChanges() {
  D.menu.hideMenu()
  D.state.changesLoading.value = true
  D.state.changesResult.value = null
  D.state.changesError.value = null
  D.state.changesDialogVisible.value = true
  try {
    const result = await projectStore.checkFileChanges(props.project.id)
    D.state.changesResult.value = result
  } catch (err: any) {
    console.error('Failed to check changes:', err)
    D.state.changesError.value = err?.message || t('project.changes.checkFailed')
  } finally {
    D.state.changesLoading.value = false
  }
}

async function handleResyncFromDialog() {
  D.state.changesDialogVisible.value = false
  await projectStore.syncProject(props.project.id)
}

  return {
    confirmDelete,
    handleCheckChanges,
    handleClearCache,
    handleDelete,
    handleDeleteBackup,
    handleResetProject,
    handleResyncFromDialog,
    onClearCacheDone,
  }
}
