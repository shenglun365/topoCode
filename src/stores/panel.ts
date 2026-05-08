import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { PanelState } from '@/types'

export const usePanelStore = defineStore('panel', () => {
  // State
  const leftCollapsed = ref(false)
  const rightCollapsed = ref(false)
  const leftWidth = ref(240)
  const rightWidth = ref(280)
  const debugMode = ref(false)

  // Actions
  function toggleLeft() {
    leftCollapsed.value = !leftCollapsed.value
  }

  function toggleRight() {
    rightCollapsed.value = !rightCollapsed.value
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
    toggleLeft,
    toggleRight,
    setLeftWidth,
    setRightWidth,
    resetPanels,
    toggleDebug,
  }
})
