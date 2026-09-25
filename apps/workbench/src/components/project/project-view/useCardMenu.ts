/**
 * useCard · menu 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */


import { useProjectStore } from '@/stores/project'
import type { CardDeps } from './chatTypes'

export function useCardMenu(D: CardDeps) {
  const projectStore = useProjectStore()
  const props = D.props

function showMenu(e: MouseEvent) {
  e.preventDefault()
  e.stopPropagation()
  D.state.menuVisible.value = true

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

  D.state.menuPosition.value = { x, y }
}

function hideMenu() {
  D.state.menuVisible.value = false
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
      D.state.pinnedWarning.value = true
      if (D.state.pinnedWarningTimer) clearTimeout(D.state.pinnedWarningTimer)
      D.state.pinnedWarningTimer = setTimeout(() => { D.state.pinnedWarning.value = false }, 2500)
      return
    }
    await projectStore.updateProjectMeta(props.project.id, { pinned: 1 })
  }
}

// 修改信息（名称 + 分组 + 版本基线）

  return {
    hideMenu,
    showMenu,
    toggleFavorite,
    togglePinned,
  }
}
