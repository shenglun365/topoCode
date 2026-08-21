import { defineStore } from 'pinia'
import { ref } from 'vue'

export type RightTab = 'ai' | 'tasks'

export const usePanelStore = defineStore('panel', () => {
  const leftCollapsed = ref(false)
  const rightCollapsed = ref(true)
  const leftWidth = ref(240)
  const rightWidth = ref(280)
  const debugMode = ref(false)
  const rightTab = ref<RightTab>('ai')
  const isFullscreen = ref(false)
  const fullscreenLockLeft = ref(false)

  // 浮动窗口
  const rightFloating = ref(false)
  const rightFloatingX = ref(typeof window !== 'undefined' ? window.innerWidth - 400 : 600)
  const rightFloatingY = ref(80)
  const rightFloatingW = ref(380)
  const rightFloatingH = ref(480)

  function toggleLeft() {
    if (fullscreenLockLeft.value) return
    leftCollapsed.value = !leftCollapsed.value
  }

  function setLeftCollapsed(collapsed: boolean) {
    if (fullscreenLockLeft.value && !collapsed) return
    leftCollapsed.value = collapsed
  }

  function toggleRight() {
    rightCollapsed.value = !rightCollapsed.value
  }

  function setRightCollapsed(collapsed: boolean) {
    rightCollapsed.value = collapsed
  }

  function setRightTab(tab: RightTab) {
    rightTab.value = tab
  }

  function setLeftWidth(width: number) {
    leftWidth.value = Math.max(180, Math.min(400, width))
  }

  function setRightWidth(width: number) {
    rightWidth.value = Math.max(200, Math.min(500, width))
  }

  function resetPanels() {
    leftCollapsed.value = false
    rightCollapsed.value = false
    leftWidth.value = 240
    rightWidth.value = 280
  }

  function toggleDebug() {
    debugMode.value = !debugMode.value
  }

  function setFullscreen(fs: boolean) {
    isFullscreen.value = fs
    if (fs) {
      fullscreenLockLeft.value = true
      leftCollapsed.value = true
      rightCollapsed.value = true
    } else {
      fullscreenLockLeft.value = false
    }
  }

  /** 切换右面板浮动 / 停靠 */
  function toggleRightFloating() {
    rightFloating.value = !rightFloating.value
    if (rightFloating.value) {
      rightCollapsed.value = true // 浮动时收起侧栏占位
    }
  }

  return {
    leftCollapsed,
    rightCollapsed,
    leftWidth,
    rightWidth,
    debugMode,
    rightTab,
    isFullscreen,
    fullscreenLockLeft,
    rightFloating,
    rightFloatingX,
    rightFloatingY,
    rightFloatingW,
    rightFloatingH,
    toggleLeft,
    setLeftCollapsed,
    toggleRight,
    setRightCollapsed,
    setRightTab,
    setLeftWidth,
    setRightWidth,
    resetPanels,
    toggleDebug,
    setFullscreen,
    toggleRightFloating,
  }
})
