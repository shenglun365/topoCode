/**
 * useCard · edit 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { useProjectStore } from '@/stores/project'
import type { GroupNode } from '@/types/ipc'
import { ipc } from '@/services/ipc'
import { useI18n } from 'vue-i18n'

import type { CardDeps } from './chatTypes'

export function useCardEdit(D: CardDeps) {
  const projectStore = useProjectStore()
  const { t } = useI18n()
  const props = D.props

async function startEditInfo() {
  D.menu.hideMenu()
  D.state.editNameInput.value = props.project.name
  D.state.editRemoteUrl.value = props.project.remoteUrl || ''
  D.state.editLocalRepoPath.value = props.project.localRepoPath || ''
  // 从最新版本基线读取分支/head
  try {
    const versions = await ipc.version.list(props.project.id)
    const latest = versions?.[0]
    D.state.editBranch.value = latest?.branch || ''
    D.state.editHead.value = latest?.head || ''
  } catch {
    D.state.editBranch.value = ''
    D.state.editHead.value = ''
  }
  D.state.allGroups.value = await ipc.group.list()
  // 初始化当前项目已选的分组
  D.state.selectedGroupIds.value = props.project.groups ? [...props.project.groups] : []
  D.state.showEditDialog.value = true
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
  const idx = D.state.selectedGroupIds.value.indexOf(id)
  if (idx >= 0) {
    D.state.selectedGroupIds.value.splice(idx, 1)
  } else {
    D.state.selectedGroupIds.value.push(id)
  }
}

function handleOpenGroupManagerFromDialog() {
  // 先关闭弹窗，再打开分组管理 tab
  D.state.showEditDialog.value = false
  // 等待弹窗关闭动画完成后再打开 tab
  setTimeout(() => {
    projectStore.openGroupManagerTab()
  }, 50)
}

async function confirmEditInfo() {
  const newName = D.state.editNameInput.value.trim()
  if (!newName) return

  // 更新名称
  if (newName !== props.project.name) {
    await projectStore.updateProjectMeta(props.project.id, { name: newName })
  }

  // 保存版本基线（远端/本地仓库、分支、head）
  const hasBaselineChange =
    D.state.editRemoteUrl.value !== (props.project.remoteUrl || '') ||
    D.state.editLocalRepoPath.value !== (props.project.localRepoPath || '') ||
    !!D.state.editBranch.value || !!D.state.editHead.value
  if (hasBaselineChange) {
    try {
      await ipc.project.saveBaseline({
        projectId: props.project.id,
        remoteUrl: D.state.editRemoteUrl.value,
        localRepoPath: D.state.editLocalRepoPath.value,
        branch: D.state.editBranch.value,
        head: D.state.editHead.value,
      })
      await projectStore.loadProjects()
    } catch (e) {
      console.error('[ProjectCard] saveBaseline failed:', e)
    }
  }

  // 更新分组（对比当前项目分组）
  const currentGroups = props.project.groups || []
  const newGroups = D.state.selectedGroupIds.value
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

  D.state.showEditDialog.value = false
  // 关闭分组管理 tab，回到项目列表
  projectStore.closeGroupManagerTab()
}

// 修改路径（带主目录名校验）
async function handleChangePath() {
  D.menu.hideMenu()
  if (window.api && window.api.dialog) {
    const path = await window.api.dialog.openDirectory()
    if (path) {
      // 提取新路径的主目录名
      const newDirName = path.split('/').pop() || path
      const currentName = props.project.name

      // 如果新目录名与当前项目名称不一致，弹窗确认
      if (newDirName !== currentName) {
        D.state.pendingNewPath.value = path
        D.state.pathConfirmMessage.value = `${t('project.pathMismatchHint')}\n\n${t('project.currentName')}: ${currentName}\n${t('project.newDirName')}: ${newDirName}\n\n${t('project.confirmPathChange')}`
        D.state.showPathConfirm.value = true
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
  D.state.showPathConfirm.value = false
  try {
    await projectStore.updatePath(props.project.id, D.state.pendingNewPath.value)
    await projectStore.loadProjects()
  } catch (err: any) {
    console.error('Failed to update path:', err)
  }
}

  return {
    collectAllGroupIds,
    confirmEditInfo,
    confirmPathChange,
    flattenGroups,
    handleChangePath,
    handleOpenGroupManagerFromDialog,
    startEditInfo,
    toggleGroupSelect,
  }
}
