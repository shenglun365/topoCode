import { defineStore } from 'pinia'
import { ref } from 'vue'

export type RightTab = 'ai' | 'detail'

export const usePanelStore = defineStore('panel', () => {
  // State
  const leftCollapsed = ref(false)
  const rightCollapsed = ref(true)
  const leftWidth = ref(240)
  const rightWidth = ref(280)
  const debugMode = ref(false)
  const rightTab = ref<RightTab>('ai')

  // Actions
  function toggleLeft() {
    leftCollapsed.value = !leftCollapsed.value
  }

  function setLeftCollapsed(collapsed: boolean) {
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

  return {
    leftCollapsed,
    rightCollapsed,
    leftWidth,
    rightWidth,
    debugMode,
    rightTab,
    toggleLeft,
    setLeftCollapsed,
    toggleRight,
    setRightCollapsed,
    setRightTab,
    setLeftWidth,
    setRightWidth,
    resetPanels,
    toggleDebug,
  }
})
